-- Headless test harness. Run from anywhere:
--   nvim --headless -l clients/nvim/test/run.lua
-- Exits non-zero if any case fails.

-- Make `require("max.*")` resolve regardless of cwd, by deriving the plugin root
-- from this script's own path.
local src = debug.getinfo(1, "S").source:sub(2) -- strip leading "@"
local here = src:gsub("[\\/][^\\/]*$", "") -- .../test
local root = here:gsub("[\\/][^\\/]*$", "") -- .../nvim
package.path = root .. "/lua/?.lua;" .. root .. "/lua/?/init.lua;" .. package.path

local specs = dofile(here .. "/dsl_spec.lua")

local passed, failed = 0, 0
for _, case in ipairs(specs) do
  local ok, err = pcall(case.fn)
  if ok then
    passed = passed + 1
    print("  ok  - " .. case.name)
  else
    failed = failed + 1
    print("  FAIL- " .. case.name .. "\n        " .. tostring(err))
  end
end

print(string.format("\n%d passed, %d failed", passed, failed))
-- `nvim -l` does not forward Lua's exit code unless we ask it to.
os.exit(failed == 0 and 0 or 1)
