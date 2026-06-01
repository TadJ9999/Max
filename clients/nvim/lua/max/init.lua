-- Max Neovim client — public entry point.
--   require("max").setup({ ... })  (lazy.nvim: opts = { ... } does this for you)

local config = require("max.config")

local M = {}
M._setup_done = false

function M.toggle_autocomplete()
  config.options.autocomplete = not config.options.autocomplete
  if not config.options.autocomplete then
    require("max.complete").clear()
  end
  vim.notify("Max autocomplete " .. (config.options.autocomplete and "on" or "off"))
end

function M.setup(opts)
  config.merge(opts)
  if M._setup_done then
    return -- config re-merged; wiring happens once
  end
  M._setup_done = true

  local command = require("max.command")
  local complete = require("max.complete")
  local status = require("max.status")
  local dsl = require("max.dsl")

  status.start()

  -- ── keymaps ────────────────────────────────────────────────────────────
  local km = config.options.keymaps or {}
  if km.run and km.run ~= "" then
    vim.keymap.set("n", km.run, command.run_at_cursor, { desc = "Max: run command at cursor" })
    vim.keymap.set("x", km.run, function()
      -- leave visual so the '< '> marks are set, then operate on the selection
      local esc = vim.api.nvim_replace_termcodes("<Esc>", true, false, true)
      vim.api.nvim_feedkeys(esc, "x", false)
      command.run_visual()
    end, { desc = "Max: run command over selection" })
  end
  if km.toggle_autocomplete and km.toggle_autocomplete ~= "" then
    vim.keymap.set("n", km.toggle_autocomplete, M.toggle_autocomplete, { desc = "Max: toggle autocomplete" })
  end
  if km.accept_completion and km.accept_completion ~= "" then
    complete.map_accept(km.accept_completion)
  end

  -- ── autocmds ───────────────────────────────────────────────────────────
  local grp = vim.api.nvim_create_augroup("Max", { clear = true })
  local auto_timer = nil

  vim.api.nvim_create_autocmd("TextChangedI", {
    group = grp,
    callback = function()
      complete.on_text_changed()
      -- auto-trigger on a closing delimiter
      if config.options.trigger ~= "auto" or command.applying then
        return
      end
      local pos = vim.api.nvim_win_get_cursor(0)
      local line = vim.api.nvim_get_current_line()
      local last = line:sub(pos[2], pos[2])
      if last ~= "." and last ~= "~" then
        return
      end
      if not dsl.detect_command(line) then
        return
      end
      local buf, lnum = vim.api.nvim_get_current_buf(), pos[1] - 1
      if auto_timer then
        auto_timer:stop()
        auto_timer:close()
        auto_timer = nil
      end
      auto_timer = vim.uv.new_timer()
      auto_timer:start(250, 0, vim.schedule_wrap(function()
        if auto_timer then
          auto_timer:stop()
          auto_timer:close()
          auto_timer = nil
        end
        if command.applying or vim.api.nvim_get_current_buf() ~= buf then
          return
        end
        command.run_line(buf, lnum)
      end))
    end,
  })
  vim.api.nvim_create_autocmd("CursorMovedI", { group = grp, callback = complete.on_cursor_moved })
  vim.api.nvim_create_autocmd("InsertLeave", { group = grp, callback = complete.on_insert_leave })

  -- ── user commands ──────────────────────────────────────────────────────
  vim.api.nvim_create_user_command("Max", function(o)
    if o.range ~= 0 then
      command.run_visual()
    else
      command.run_at_cursor()
    end
  end, { range = true, desc = "Max: run DSL command at cursor / selection" })

  vim.api.nvim_create_user_command("MaxToggleAutocomplete", M.toggle_autocomplete,
    { desc = "Max: toggle ghost-text autocomplete" })

  vim.api.nvim_create_user_command("MaxHealth", function()
    status.poll()
    vim.defer_fn(function()
      local s = status.info()
      if s.online then
        vim.notify("Max: online — engine " .. tostring(s.version))
      else
        vim.notify("Max: offline — start the Max app or engine at " .. config.options.engine_url,
          vim.log.levels.WARN)
      end
    end, 400)
  end, { desc = "Max: report engine health" })
end

return M
