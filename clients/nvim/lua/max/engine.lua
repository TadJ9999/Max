-- Thin client for the local Max engine, using `curl` driven by vim.system
-- (no Lua dependencies). The JSON body is sent on stdin (`-d @-`) and vim.system
-- runs without a shell, so Windows quoting / arg-length is a non-issue.
--
-- vim.system stdout/exit callbacks run in a libuv "fast" context, so anything
-- touching the Neovim API is dispatched through vim.schedule.

local config = require("max.config")

local M = {}

local function base_url()
  return (config.options.engine_url or "http://127.0.0.1:8001"):gsub("/+$", "")
end

-- Dispatch one SSE line to the handlers. `err_lines` collects non-SSE output
-- (e.g. an HTTP error body) for reporting on a non-zero exit.
local function handle_line(line, h, err_lines)
  local t = vim.trim(line)
  if t == "" then
    return
  end
  if not t:match("^data:") then
    err_lines[#err_lines + 1] = t -- likely an HTTP error body ({"detail": ...})
    return
  end
  local data = vim.trim(t:sub(6))
  if data == "" or data == "[DONE]" then
    return
  end
  local ok, obj = pcall(vim.json.decode, data)
  if not ok or type(obj) ~= "table" then
    return
  end
  if obj.error then
    local msg = (type(obj.error) == "table" and obj.error.message) or "engine error"
    if h.on_error then
      vim.schedule(function() h.on_error(msg) end)
    end
    return
  end
  if obj.model and h.on_model then
    vim.schedule(function() h.on_model(obj.model) end)
  end
  local choices = obj.choices
  local delta = choices and choices[1] and choices[1].delta and choices[1].delta.content
  if delta and delta ~= "" and h.on_delta then
    vim.schedule(function() h.on_delta(delta) end)
  end
end

--- Stream a DSL command via /command. `h` = { on_delta, on_model, on_done, on_error }.
--- Returns the vim.system job (has :kill(signal)) so callers can supersede a run.
function M.stream_command(text, h)
  h = h or {}
  local url = base_url()
  local buf = ""
  local err_lines = {}

  local function on_stdout(_, data)
    if not data then
      return
    end
    buf = buf .. data
    while true do
      local nl = buf:find("\n", 1, true)
      if not nl then
        break
      end
      handle_line(buf:sub(1, nl - 1), h, err_lines)
      buf = buf:sub(nl + 1)
    end
  end

  local cmd = {
    "curl", "-sN", "--fail-with-body", "-X", "POST",
    "-H", "content-type: application/json",
    "-d", "@-", url .. "/command",
  }
  local ok, job = pcall(vim.system, cmd, {
    stdin = vim.json.encode({ text = text }),
    stdout = on_stdout,
    text = true,
  }, function(obj)
    vim.schedule(function()
      if buf ~= "" then
        handle_line(buf, h, err_lines)
      end
      if obj.code ~= 0 then
        local msg
        if obj.code == 7 then
          msg = "engine unreachable at " .. url
        elseif obj.code == 22 then
          -- HTTP >= 400. 403 = cloud routing off; otherwise surface the body.
          local body = vim.trim(table.concat(err_lines, " "))
          msg = body ~= "" and body or "cloud routing is off (enable it in Max settings)"
        else
          msg = "engine error (curl exit " .. tostring(obj.code) .. ")"
        end
        if h.on_error then
          h.on_error(msg)
        end
      elseif h.on_done then
        h.on_done()
      end
    end)
  end)

  if not ok then
    if h.on_error then
      vim.schedule(function() h.on_error("could not run curl (is it installed?)") end)
    end
    return nil
  end
  return job
end

--- Fill-in-the-middle completion. Best-effort: cb("") on any failure.
function M.complete(prefix, suffix, cb)
  local url = base_url()
  local body = vim.json.encode({
    prefix = prefix,
    suffix = suffix or "",
    max_tokens = config.options.max_completion_tokens,
  })
  local cmd = {
    "curl", "-s", "--max-time", "20", "-X", "POST",
    "-H", "content-type: application/json",
    "-d", "@-", url .. "/complete",
  }
  local ok = pcall(vim.system, cmd, { stdin = body, text = true }, function(obj)
    local completion = ""
    if obj.code == 0 and obj.stdout and obj.stdout ~= "" then
      local pok, parsed = pcall(vim.json.decode, obj.stdout)
      if pok and type(parsed) == "table" and type(parsed.completion) == "string" then
        completion = parsed.completion
      end
    end
    vim.schedule(function() cb(completion) end)
  end)
  if not ok then
    vim.schedule(function() cb("") end)
  end
end

--- Health probe. cb(online: bool, version: string|nil).
function M.health(cb)
  local url = base_url()
  local ok = pcall(vim.system, { "curl", "-s", "--max-time", "2", url .. "/health" },
    { text = true },
    function(obj)
      local online, version = false, nil
      if obj.code == 0 and obj.stdout and obj.stdout ~= "" then
        local pok, parsed = pcall(vim.json.decode, obj.stdout)
        if pok and type(parsed) == "table" and parsed.status then
          online, version = true, parsed.version
        end
      end
      vim.schedule(function() cb(online, version) end)
    end)
  if not ok then
    vim.schedule(function() cb(false, nil) end)
  end
end

return M
