-- Default configuration for the Max Neovim client.
-- Override via require("max").setup({ ... }).

local M = {}

M.defaults = {
  -- Base URL of the local Max engine (desktop app runs it on 8001; dev uvicorn on 8000).
  engine_url = "http://127.0.0.1:8001",
  -- How a DSL command fires: "auto" (on the closing delimiter) or "manual" (keymap only).
  trigger = "auto",
  -- Ghost-text fill-in-the-middle completion as you type.
  autocomplete = true,
  -- Idle delay before requesting a ghost-text completion (ms).
  completion_delay_ms = 300,
  -- Max tokens for a ghost-text completion (small = snappy).
  max_completion_tokens = 96,
  -- Default keymaps. Set any to false/"" to skip mapping it.
  keymaps = {
    run = "<leader>mm",                  -- run command at cursor / over visual selection
    toggle_autocomplete = "<leader>ma",  -- toggle ghost-text completion
    accept_completion = "<Tab>",         -- accept the live ghost-text suggestion (insert mode)
  },
}

-- The live, merged config (populated by init.setup()).
M.options = vim.deepcopy(M.defaults)

function M.merge(opts)
  M.options = vim.tbl_deep_extend("force", vim.deepcopy(M.defaults), opts or {})
  return M.options
end

return M
