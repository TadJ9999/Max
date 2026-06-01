-- Pure-function specs for dsl.detect_command and postprocess.process.
-- Returns a list of { name, fn } cases; the fn raises (error) on failure.

local dsl = require("max.dsl")
local pp = require("max.postprocess")

local function eq(a, b, what)
  if a ~= b then
    error(string.format("%s: expected %q, got %q", what or "value", tostring(b), tostring(a)), 2)
  end
end

-- Assert a detected command matches the expected operator/sigil/cloud/body.
local function detects(text, op, sigil, cloud, body)
  local m = dsl.detect_command(text)
  if not m then
    error(string.format("expected %q to parse, got nil", text), 2)
  end
  eq(m.operator, op, text .. " operator")
  eq(m.sigil, sigil, text .. " sigil")
  eq(m.cloud, cloud, text .. " cloud")
  if body then
    eq(m.body, body, text .. " body")
  end
end

local function rejects(text)
  local m = dsl.detect_command(text)
  if m ~= nil then
    error(string.format("expected %q to be rejected, got operator=%s", text, m.operator), 2)
  end
end

local specs = {}
local function it(name, fn)
  specs[#specs + 1] = { name = name, fn = fn }
end

-- ── operators ────────────────────────────────────────────────────────────
it("generate (.)", function()
  detects(". add two numbers .", "generate", "", false, "add two numbers")
end)
it("summarize (..)", function()
  detects(".. document this ..", "summarize", "", false, "document this")
end)
it("fix (~)", function()
  detects("~ tidy this block ~", "fix", "", false, "tidy this block")
end)

-- ── sigils ───────────────────────────────────────────────────────────────
it("@ local ollama", function()
  detects("@. local gen .", "generate", "@", false)
end)
it("# qwen", function()
  detects("#.. doc ..", "summarize", "#", false)
end)
it("! cloud claude", function()
  detects("!. cloud gen .", "generate", "!", true)
end)
it("% cloud openai", function()
  detects("%. openai gen .", "generate", "%", true)
end)
it("^ local server", function()
  detects("^. local server gen .", "generate", "^", false)
end)

-- ── whitespace + rejection ─────────────────────────────────────────────────
it("trims surrounding whitespace", function()
  detects("   . spaced .   ", "generate", "", false, "spaced")
end)
it("rejects empty bodies", function()
  rejects(".  .")
  rejects("..  ..")
  rejects("~  ~")
end)
it("rejects non-commands", function()
  rejects("just some prose")
  rejects("")
  rejects("x = 1")
end)

-- ── postprocess ────────────────────────────────────────────────────────────
it("strips a fenced block with language", function()
  eq(pp.process("```python\nprint(1)\n```", ""), "print(1)", "fenced")
end)
it("strips a bare fence", function()
  eq(pp.process("```\na\nb\n```\n", ""), "a\nb", "bare fence")
end)
it("leaves unfenced text alone", function()
  eq(pp.process("no fence here", ""), "no fence here", "unfenced")
end)
it("strips the opening fence mid-stream", function()
  eq(pp.process("```python\nprint(", ""), "print(", "partial")
end)
it("re-indents continuation lines", function()
  eq(pp.process("def f():\n    return 1", "  "), "def f():\n      return 1", "reindent")
end)
it("keeps blank lines blank when re-indenting", function()
  eq(pp.process("a\n\nb", "  "), "a\n\n  b", "blank line")
end)

return specs
