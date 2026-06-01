-- Run a DSL command and stream the result into the buffer, replacing the command
-- span in place. Mirrors the VS Code extension's run/stream/inline-replace.

local dsl = require("max.dsl")
local pp = require("max.postprocess")
local engine = require("max.engine")
local status = require("max.status")

local M = {}

-- True while the plugin is editing the buffer, so the auto-trigger and ghost-text
-- autocmds ignore the plugin's own edits.
M.applying = false

local current_job = nil
local active_run = 0

local USAGE = "no command here. Use  . generate .   .. document ..   ~ fix ~  (optionally @ # ! % ^)."

local function notify(msg, level)
  vim.notify("Max: " .. msg, level or vim.log.levels.INFO)
end

-- 0-indexed span over the non-whitespace content of line `lnum` (0-indexed).
local function trimmed_line_range(buf, lnum)
  local line = vim.api.nvim_buf_get_lines(buf, lnum, lnum + 1, false)[1] or ""
  local first = line:find("%S")
  if not first then
    return lnum, 0, lnum, 0
  end
  local trimmed = line:gsub("%s+$", "")
  return lnum, first - 1, lnum, #trimmed
end

-- End position after inserting `lines` starting at (srow, scol).
local function end_pos(srow, scol, lines)
  if #lines == 1 then
    return srow, scol + #lines[1]
  end
  return srow + #lines - 1, #lines[#lines]
end

--- Stream a detected command, replacing [srow,scol .. erow,ecol] with the output.
function M.run_match(buf, srow, scol, erow, ecol, match)
  -- Supersede any in-flight run.
  if current_job then
    pcall(function() current_job:kill(15) end)
    current_job = nil
  end
  active_run = active_run + 1
  local run = active_run

  local cmd_line = vim.api.nvim_buf_get_lines(buf, srow, srow + 1, false)[1] or ""
  local base_indent = cmd_line:match("^%s*") or ""

  M.applying = true
  status.set_cloud(match.cloud)

  -- Clear the command span; output streams in at (srow, scol).
  vim.api.nvim_buf_set_text(buf, srow, scol, erow, ecol, { "" })

  local acc = ""
  local last_erow, last_ecol = srow, scol

  local function finish()
    M.applying = false
    status.set_cloud(false)
    if run == active_run then
      current_job = nil
    end
  end

  current_job = engine.stream_command(match.text, {
    on_model = function(model)
      if run ~= active_run then
        return
      end
      status.set_model(model)
    end,
    on_delta = function(delta)
      if run ~= active_run or not vim.api.nvim_buf_is_valid(buf) then
        return
      end
      acc = acc .. delta
      local processed = pp.process(acc, base_indent)
      local lines = vim.split(processed, "\n", { plain = true })
      vim.api.nvim_buf_set_text(buf, srow, scol, last_erow, last_ecol, lines)
      last_erow, last_ecol = end_pos(srow, scol, lines)
    end,
    on_error = function(msg)
      if run ~= active_run then
        return
      end
      notify(msg, vim.log.levels.ERROR)
      finish()
    end,
    on_done = function()
      if run ~= active_run then
        return
      end
      if acc:match("^%s*$") then
        notify("the model returned nothing.", vim.log.levels.WARN)
      end
      finish()
    end,
  })

  if not current_job then
    -- stream_command failed synchronously (e.g. curl missing) and already
    -- reported via on_error; restore the applying flag.
    M.applying = false
    status.set_cloud(false)
  end
end

--- Detect + run a command on a specific 0-indexed line.
function M.run_line(buf, lnum)
  local srow, scol, erow, ecol = trimmed_line_range(buf, lnum)
  local text = vim.api.nvim_buf_get_text(buf, srow, scol, erow, ecol, {})[1] or ""
  local match = dsl.detect_command(text)
  if not match then
    return false
  end
  M.run_match(buf, srow, scol, erow, ecol, match)
  return true
end

--- Run the command on the current cursor line.
function M.run_at_cursor()
  local buf = vim.api.nvim_get_current_buf()
  local lnum = vim.api.nvim_win_get_cursor(0)[1] - 1
  if not M.run_line(buf, lnum) then
    notify(USAGE)
  end
end

--- Run the command formed by the current visual selection.
function M.run_visual()
  local buf = vim.api.nvim_get_current_buf()
  local s = vim.api.nvim_buf_get_mark(buf, "<")
  local e = vim.api.nvim_buf_get_mark(buf, ">")
  local srow, scol = s[1] - 1, s[2]
  local erow, ecol = e[1] - 1, e[2] + 1 -- '> column is inclusive
  local eline = vim.api.nvim_buf_get_lines(buf, erow, erow + 1, false)[1] or ""
  if ecol > #eline then
    ecol = #eline
  end
  local text = table.concat(vim.api.nvim_buf_get_text(buf, srow, scol, erow, ecol, {}), "\n")
  local match = dsl.detect_command(text)
  if not match then
    notify("no command in selection. Wrap it like  ~ fix this ~ .")
    return
  end
  M.run_match(buf, srow, scol, erow, ecol, match)
end

return M
