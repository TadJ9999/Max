-- Plugin entry. Loaded automatically from the runtimepath.
-- Guards against double-load and version, then zero-config bootstraps on VimEnter
-- if the user never called require("max").setup() explicitly.

if vim.g.loaded_max then
  return
end
vim.g.loaded_max = true

if vim.fn.has("nvim-0.10") == 0 then
  vim.schedule(function()
    vim.notify("max.nvim requires Neovim 0.10+", vim.log.levels.WARN)
  end)
  return
end

-- Explicit setup() (e.g. via lazy.nvim `opts`) wins; this is only a fallback so
-- the plugin works with zero configuration.
vim.api.nvim_create_autocmd("VimEnter", {
  once = true,
  callback = function()
    local ok, max = pcall(require, "max")
    if ok and not max._setup_done then
      max.setup({})
    end
  end,
})
