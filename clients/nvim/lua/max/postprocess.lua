-- Strip opening/closing markdown code fences and re-apply the command line's
-- indentation to continuation lines. Applied to the *accumulated* stream buffer
-- on every chunk so a fence never appears in the buffer even mid-stream.
--
-- base_indent: whitespace prefix of the command line — prepended to every line
-- after the first so the whole block sits at the right column.

local M = {}

-- Split on "\n", keeping empty trailing segments (so a trailing newline shows).
local function split_lines(text)
  local lines = {}
  local start = 1
  while true do
    local nl = text:find("\n", start, true)
    if not nl then
      lines[#lines + 1] = text:sub(start)
      break
    end
    lines[#lines + 1] = text:sub(start, nl - 1)
    start = nl + 1
  end
  return lines
end

function M.process(text, base_indent)
  base_indent = base_indent or ""
  local lines = split_lines(text)

  -- Strip opening fence (first line begins with ```).
  local first = 1
  if lines[1] ~= nil and lines[1]:match("^```") then
    first = 2
  end

  -- Strip closing fence (last non-empty line is ``` only).
  local last = #lines
  while last > first and (lines[last] or ""):match("^%s*$") do
    last = last - 1
  end
  if last >= first and (lines[last] or ""):match("^```%s*$") then
    last = last - 1
  end

  -- Re-indent: first line sits at the cursor (already indented); later lines get
  -- base_indent prepended. Blank lines stay blank.
  local out = {}
  for i = first, last do
    local line = lines[i]
    if i == first or line == "" or base_indent == "" then
      out[#out + 1] = line
    else
      out[#out + 1] = base_indent .. line
    end
  end
  return table.concat(out, "\n")
end

return M
