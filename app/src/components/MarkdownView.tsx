// Lightweight renderer for streamed assistant replies: splits fenced code
// blocks (```lang … ```) into copyable code cards and renders the rest as
// preserved-whitespace text. Tolerant of an unclosed trailing fence (common
// mid-stream). No dependencies, no innerHTML.

import { useState } from "react";

type Seg = { type: "text" | "code"; lang?: string; content: string };

function parseSegments(src: string): Seg[] {
  const lines = src.split("\n");
  const segs: Seg[] = [];
  let mode: "text" | "code" = "text";
  let lang = "";
  let buf: string[] = [];

  const flush = () => {
    if (mode === "code") {
      segs.push({ type: "code", lang, content: buf.join("\n") });
    } else if (buf.join("").trim().length > 0) {
      segs.push({ type: "text", content: buf.join("\n").replace(/^\n+|\n+$/g, "") });
    }
    buf = [];
  };

  for (const line of lines) {
    const m = line.match(/^\s*```(\w*)\s*$/);
    if (m) {
      flush();
      if (mode === "text") {
        mode = "code";
        lang = m[1] ?? "";
      } else {
        mode = "text";
        lang = "";
      }
      continue;
    }
    buf.push(line);
  }
  flush();
  return segs;
}

function CodeBlock({ lang, content }: { lang?: string; content: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <div className="code">
      <div className="code__bar">
        <span className="code__lang">{lang || "code"}</span>
        <button className="code__copy" onClick={copy} title="Copy">
          {copied ? "copied ✓" : "copy"}
        </button>
      </div>
      <pre className="code__pre">
        <code>{content}</code>
      </pre>
    </div>
  );
}

export function MarkdownView({ source }: { source: string }) {
  const segs = parseSegments(source);
  return (
    <div className="md">
      {segs.map((s, i) =>
        s.type === "code" ? (
          <CodeBlock key={i} lang={s.lang} content={s.content} />
        ) : (
          <p key={i} className="md__text">
            {s.content}
          </p>
        ),
      )}
    </div>
  );
}
