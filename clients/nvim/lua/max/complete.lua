-- Ghost-text fill-in-the-middle completion via /complete, shown as inline
-- virtual text (Neovim 0.10+) and accepted with the configured key (default <Tab>).

local engine = require("max.engine")
local config = require("max.config")

local M = {}

local ns = vim.api.nvim_create_namespace("max_ghost")
local MAX_CTX = 2000

local timer = nil
-- Live suggestion state.
local sugg = { text = nil, buf = nil, row = nil, col = nil }

local function in_insert()
  return vim.api.nvim_get_mode().mode:sub(1, 1) == "i"
end

function M.clear()
  if sugg.buf and vim.api.nvim_buf_is_valid(sugg.buf) then
    vim.api.nvim_buf_clear_namespace(sugg.buf, ns, 0, -1)
  end
  sugg = { text = nil, buf = nil, row = nil, col = nil }
end

function M.has_suggestion()
  return sugg.text ~= nil and sugg.text ~= ""
end

local function render(buf, row, col, text)
  local lines = vim.split(text, "\n", { plain = true })
  local opts = {
    virt_text = { { lines[1], "Comment" } },
    virt_text_pos = "inline",
    hl_mode = "combine",
  }
  if #lines > 1 then
    local vl = {}
    for i = 2, #lines do
      vl[#vl + 1] = { { lines[i], "Comment" } }
    end
    opts.virt_lines = vl
  end
  vim.api.nvim_buf_clear_namespace(buf, ns, 0, -1)
  vim.api.nvim_buf_set_extmark(buf, ns, row, col, opts)
  sugg = { text = text, buf = buf, row = row, col = col }
end

-- Byte offset of the cursor within the joined buffer text.
local function cursor_offset(lines, row, col)
  local off = 0
  for i = 1, row do
    off = off + #lines[i] + 1 -- +1 for the newline
  end
  return off + col
end

local function request()
  if not config.options.autocomplete or require("max.command").applying then
    return
  end
  if not in_insert() then
    return
  end
  local buf = vim.api.nvim_get_current_buf()
  local cur = vim.api.nvim_win_get_cursor(0)
  local row, col = cur[1] - 1, cur[2]
  local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
  local all = table.concat(lines, "\n")
  local off = cursor_offset(lines, row, col)
  local prefix = all:sub(math.max(1, off - MAX_CTX + 1), off)
  local suffix = all:sub(off + 1, off + MAX_CTX)
  if prefix:match("^%s*$") then
    return
  end

  engine.complete(prefix, suffix, function(completion)
    if completion == "" or not config.options.autocomplete or not in_insert() then
      return
    end
    if vim.api.nvim_get_current_buf() ~= buf then
      return
    end
    local now = vim.api.nvim_win_get_cursor(0)
    if now[1] - 1 ~= row or now[2] ~= col then
      return -- cursor moved; suggestion is stale
    end
    render(buf, row, col, completion)
  end)
end

local function schedule_request()
  if timer then
    timer:stop()
    timer:close()
    timer = nil
  end
  if not config.options.autocomplete then
    return
  end
  timer = vim.uv.new_timer()
  timer:start(config.options.completion_delay_ms, 0, vim.schedule_wrap(function()
    if timer then
      timer:stop()
      timer:close()
      timer = nil
    end
    request()
  end))
end

-- Autocmd handlers (wired in init.lua).
function M.on_text_changed()
  M.clear()
  schedule_request()
end

function M.on_cursor_moved()
  M.clear()
  schedule_request()
end

function M.on_insert_leave()
  M.clear()
  if timer then
    timer:stop()
    timer:close()
    timer = nil
  end
end

--- Accept the live suggestion. Returns true if one was inserted.
function M.accept()
  if not M.has_suggestion() then
    return false
  end
  local buf, row, col, text = sugg.buf, sugg.row, sugg.col, sugg.text
  M.clear()
  local lines = vim.split(text, "\n", { plain = true })
  vim.api.nvim_buf_set_text(buf, row, col, row, col, lines)
  local erow, ecol
  if #lines == 1 then
    erow, ecol = row, col + #lines[1]
  else
    erow, ecol = row + #lines - 1, #lines[#lines]
  end
  vim.api.nvim_win_set_cursor(0, { erow + 1, ecol })
  return true
end

--- Map `key` (insert mode) to accept the suggestion, falling back to a literal key.
function M.map_accept(key)
  vim.keymap.set("i", key, function()
    if not M.accept() then
      local k = vim.api.nvim_replace_termcodes(key, true, false, true)
      vim.api.nvim_feedkeys(k, "n", false)
    end
  end, { desc = "Max: accept ghost-text suggestion" })
end

return M
