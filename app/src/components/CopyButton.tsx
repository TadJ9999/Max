// Small reusable "copy to clipboard" button for AI output fields.
// Shows a brief "copied ✓" confirmation. No-op (silent) if clipboard is blocked.

import { useState } from "react";

export function CopyButton({
  text,
  className = "",
  title = "Copy",
}: {
  text: string;
  className?: string;
  title?: string;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <button
      className={`copy-btn${copied ? " is-copied" : ""} ${className}`.trim()}
      onClick={() => void copy()}
      title={title}
      aria-label={title}
      disabled={!text}
    >
      {copied ? "copied ✓" : "copy"}
    </button>
  );
}
