-- Detect a Max DSL command in editor text. Mirrors the engine grammar:
--   [sigil] <operator> body <operator>
-- sigil in { @ # ! % ^ } (optional), operator in { . , .. , ~ }.
-- The raw matched text is sent verbatim to /command — the engine re-parses the
-- sigil + operator and routes accordingly.
--
-- Cloud sigils ("!" Claude, "%" OpenAI) leave the machine; "@" "#" "^" stay local.

local M = {}

-- Lua patterns are not full regex (no non-greedy quantifiers), so we anchor on
-- the literal delimiters and capture the middle greedily, then trim. Order
-- matters: try ".." before "." so a ".. .." line isn't matched as ". .".
-- Captures: (1) optional sigil, (2) body.
local RULES = {
  { op = "summarize", pat = "^([@#!%%%^]?)%.%.(.*)%.%.$" },
  { op = "fix", pat = "^([@#!%%%^]?)~(.*)~$" },
  { op = "generate", pat = "^([@#!%%%^]?)%.(.*)%.$" },
}

local CLOUD = { ["!"] = true, ["%"] = true }

-- Trim leading/trailing whitespace.
local function trim(s)
  return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

--- Detect a command in `raw`. Returns a table or nil.
--- @return table|nil  { text, operator, sigil, body, cloud }
function M.detect_command(raw)
  local text = trim(raw or "")
  if text == "" then
    return nil
  end
  for _, rule in ipairs(RULES) do
    local sigil, body = text:match(rule.pat)
    if body ~= nil then
      body = trim(body)
      -- Require real content (a word char) so ".  ." / "..  .." aren't commands.
      if body:match("%w") then
        sigil = sigil or ""
        return {
          text = text,
          operator = rule.op,
          sigil = sigil,
          body = body,
          cloud = CLOUD[sigil] == true,
        }
      end
    end
  end
  return nil
end

return M
