-- Engine health + cloud-run indicator. Drop M.statusline into lualine/statusline:
--   require("lualine").setup({ sections = { lualine_x = { require("max.status").statusline } } })

local engine = require("max.engine")

local M = {}

local state = { online = false, version = nil, cloud = false, model = nil }
local timer = nil

function M.set_cloud(v)
  state.cloud = v and true or false
end

function M.set_model(m)
  state.model = m
end

function M.info()
  return state
end

function M.poll()
  engine.health(function(online, version)
    state.online = online
    state.version = version
  end)
end

function M.start()
  if timer then
    return
  end
  M.poll()
  timer = vim.uv.new_timer()
  timer:start(5000, 5000, vim.schedule_wrap(M.poll))
end

function M.stop()
  if timer then
    timer:stop()
    timer:close()
    timer = nil
  end
end

--- A short status string for a statusline component.
function M.statusline()
  if not state.online then
    return "⚡Max ⃠"
  end
  if state.cloud then
    return "⚡Max ☁"
  end
  return "⚡Max"
end

return M
