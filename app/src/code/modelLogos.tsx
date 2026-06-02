// Inline-runner model logos — the little mark that rides the progress track,
// one per invoked model family. Drawn with currentColor so the runner can tint
// them with each provider's accent. `logoForModel` maps a model id (or, before
// the first token arrives, the command sigil) to a logo kind.

export type LogoKind = "llama" | "qwen" | "claude" | "gpt" | "google" | "local";

// Provider accent colors (used for the trail glow + logo tint).
export const ACCENT: Record<LogoKind, string> = {
  llama: "#e8a06b",   // warm Ollama amber
  qwen: "#7c83ff",    // Qwen indigo
  claude: "#d08a5e",  // Anthropic terracotta
  gpt: "#19c37d",     // OpenAI green
  google: "#4285f4",  // Gemini blue
  local: "#8aa0b4",   // generic slate
};

export const KIND_LABEL: Record<LogoKind, string> = {
  llama: "ollama", qwen: "qwen", claude: "claude",
  gpt: "openai", google: "gemini", local: "local",
};

/** Parse a leading provider sigil from a command, if present. */
export function sigilOf(text: string): string | undefined {
  const c = text.trim()[0];
  return c && "@q#!%^".includes(c) ? c : undefined;
}

/** Best logo for the invoked model. Uses the real model id when known; before
 * the first streamed token, falls back to the sigil's provider. */
export function logoForModel(model?: string, sigil?: string): LogoKind {
  const m = (model || "").toLowerCase();
  if (m) {
    if (m.startsWith("claude")) return "claude";
    if (m.startsWith("gpt") || m.startsWith("o1") || m.startsWith("o3") || m.startsWith("chatgpt"))
      return "gpt";
    if (m.includes("gemini")) return "google";
    if (m.includes("qwen")) return "qwen";
    return "llama"; // llama / mistral / phi / gemma / deepseek / … → Ollama family
  }
  switch (sigil) {
    case "!": case "#": return "claude";
    case "%": return "gpt";
    case "q": return "qwen";
    case "^": return "local";
    default: return "llama"; // "@" or no sigil → local Ollama default
  }
}

// ── the SVGs ────────────────────────────────────────────────────────────────

function Llama({ s }: { s: number }) {
  // Friendly line-art llama: ears, head + muzzle, S-neck, body, four legs.
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9.4 5 l0.2 -2.1 l1.1 1.8" />
      <path d="M11.1 5.1 l0.5 -1.9 l1 2" />
      <path d="M10 4.7 q2 0.2 2 2.4 q0 1.6 -1.4 2 l-2.3 0.3" />
      <path d="M8.4 9.4 l-1.8 0.5 v1.1 l1.9 -0.2" />
      <path d="M9 9.6 q-1.6 -3.3 -0.7 -6.1" opacity="0" />
      <path d="M8.6 13.8 q-1.6 -3.4 -0.9 -6.4 q0.5 -2 2.4 -2.6" />
      <path d="M8.6 13.8 q4.6 -1.2 8.1 0.6 q1.9 1.1 1.1 5.6" />
      <path d="M8.7 13.9 q-1 4 0.4 6" />
      <path d="M9.6 19.6 v2.1 M12.3 20 v1.8 M15.6 19.7 v2 M17.5 19.2 v1.8" />
      <circle cx="10.3" cy="6.7" r="0.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

function Qwen({ s }: { s: number }) {
  // Abstract interlocking-knot Q mark.
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="7" />
      <path d="M12 7 v10 M7.3 9.5 L16.7 14.5 M16.7 9.5 L7.3 14.5" opacity="0.85" />
    </svg>
  );
}

function Claude({ s }: { s: number }) {
  // Anthropic burst mark (path reused from ModelManager).
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
      <path d="M13.827 3.52h3.603L24 20h-3.603l-6.57-16.48zM6.394 3.52L0 20h3.603l1.498-3.858h7.197L10.8 20h3.604L8.012 3.52H6.394zm1.113 9.908 2.523-6.498 2.524 6.498H7.507z" />
    </svg>
  );
}

function Gpt({ s }: { s: number }) {
  // OpenAI knot (path reused from ModelManager).
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
      <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855-5.833-3.387L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667zm2.01-3.023-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08L8.704 5.46a.795.795 0 0 0-.393.681zm1.097-2.365 2.602-1.5 2.607 1.5v2.999l-2.597 1.5-2.607-1.5Z" />
    </svg>
  );
}

function Google({ s }: { s: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12.48 10.92v3.28h7.84c-.24 1.84-.853 3.187-1.787 4.133-1.147 1.147-2.933 2.4-6.053 2.4-4.827 0-8.6-3.893-8.6-8.72s3.773-8.72 8.6-8.72c2.6 0 4.507 1.027 5.907 2.347l2.307-2.307C18.747 1.44 16.133 0 12.48 0 5.867 0 .307 5.387.307 12s5.56 12 12.173 12c3.573 0 6.267-1.173 8.373-3.36 2.16-2.16 2.84-5.213 2.84-7.667 0-.76-.053-1.467-.173-2.053H12.48z" />
    </svg>
  );
}

function Local({ s }: { s: number }) {
  // Server-rack mark for a custom local OpenAI-compatible endpoint (^).
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="4" width="16" height="6" rx="1.5" />
      <rect x="4" y="14" width="16" height="6" rx="1.5" />
      <circle cx="7.5" cy="7" r="0.6" fill="currentColor" stroke="none" />
      <circle cx="7.5" cy="17" r="0.6" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function ModelLogo({ kind, size = 18 }: { kind: LogoKind; size?: number }) {
  switch (kind) {
    case "llama": return <Llama s={size} />;
    case "qwen": return <Qwen s={size} />;
    case "claude": return <Claude s={size} />;
    case "gpt": return <Gpt s={size} />;
    case "google": return <Google s={size} />;
    default: return <Local s={size} />;
  }
}
