// Detect a Max DSL command in editor text. Mirrors the engine grammar:
//   [sigil] <operator> body <operator>
// sigil ∈ { @ # ! } (optional), operator ∈ { . , .. , ~ }.
// The raw matched text is sent verbatim to /command — the engine re-parses the
// sigil + operator and routes accordingly.

export type Operator = "generate" | "summarize" | "fix";

export interface DslMatch {
  text: string; // the trimmed command, sent as-is to the engine
  operator: Operator;
  sigil: string; // "" | "@" | "#" | "!"
  body: string;
  cloud: boolean; // sigil === "!"
}

const SUMMARIZE = /^([@#!]?)\.\.\s?([\s\S]*?)\s?\.\.$/;
const FIX = /^([@#!]?)~\s?([\s\S]*?)\s?~$/;
const GENERATE = /^([@#!]?)\.\s?([\s\S]*?)\s?\.$/;

// Try `..` before `.` (the single-dot pattern would otherwise match a `..` line).
const RULES: [Operator, RegExp][] = [
  ["summarize", SUMMARIZE],
  ["fix", FIX],
  ["generate", GENERATE],
];

export function detectCommand(raw: string): DslMatch | null {
  const text = raw.trim();
  if (!text) return null;
  for (const [operator, re] of RULES) {
    const m = re.exec(text);
    // Require real content (a word char), so `..  ..` / `.  .` aren't commands.
    if (m && /\w/.test(m[2])) {
      const sigil = m[1] ?? "";
      return { text, operator, sigil, body: m[2].trim(), cloud: sigil === "!" };
    }
  }
  return null;
}
