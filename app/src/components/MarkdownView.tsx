// Lightweight Markdown renderer for streamed assistant replies. Splits fenced
// code blocks (```lang … ```) into copyable code cards, and renders the rest as
// real Markdown — headings, bold/italic, inline code, links, bullet/numbered
// lists, and horizontal rules — built as React nodes (no dependencies, no
// innerHTML). Tolerant of an unclosed trailing fence (common mid-stream).

import { createElement, type ReactNode, useState } from "react";

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

// ---- inline formatting: **bold**, *italic*, `code`, [text](url) -------------

const INLINE = /(\*\*|__)(.+?)\1|(\*|_)(.+?)\3|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  INLINE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = INLINE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const key = `${keyPrefix}-${i++}`;
    if (m[2] != null) out.push(<strong key={key}>{m[2]}</strong>);
    else if (m[4] != null) out.push(<em key={key}>{m[4]}</em>);
    else if (m[5] != null) out.push(<code key={key} className="md__code">{m[5]}</code>);
    else if (m[6] != null)
      out.push(
        <a key={key} href={m[7]} target="_blank" rel="noreferrer noopener">
          {m[6]}
        </a>,
      );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// ---- block parsing: headings, lists, rules, paragraphs ----------------------

type Block =
  | { type: "h"; level: number; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "hr" }
  | { type: "p"; text: string };

function parseBlocks(src: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  let list: { type: "ul" | "ol"; items: string[] } | null = null;

  const flushPara = () => {
    if (para.length) {
      blocks.push({ type: "p", text: para.join("\n") });
      para = [];
    }
  };
  const flushList = () => {
    if (list) {
      blocks.push(list);
      list = null;
    }
  };

  for (const line of src.split("\n")) {
    if (line.trim() === "") {
      flushPara();
      flushList();
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    const hr = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line);

    if (h) {
      flushPara();
      flushList();
      blocks.push({ type: "h", level: h[1].length, text: h[2] });
    } else if (hr) {
      flushPara();
      flushList();
      blocks.push({ type: "hr" });
    } else if (ul) {
      flushPara();
      if (!list || list.type !== "ul") {
        flushList();
        list = { type: "ul", items: [] };
      }
      list.items.push(ul[1]);
    } else if (ol) {
      flushPara();
      if (!list || list.type !== "ol") {
        flushList();
        list = { type: "ol", items: [] };
      }
      list.items.push(ol[1]);
    } else {
      flushList();
      para.push(line);
    }
  }
  flushPara();
  flushList();
  return blocks;
}

function Blocks({ text }: { text: string }) {
  return (
    <>
      {parseBlocks(text).map((b, i) => {
        if (b.type === "h") {
          const lvl = Math.min(b.level, 6);
          return createElement(
            `h${lvl}`,
            { key: i, className: `md__h md__h${lvl}` },
            renderInline(b.text, `h${i}`),
          );
        }
        if (b.type === "hr") return <hr key={i} className="md__hr" />;
        if (b.type === "ul")
          return (
            <ul key={i} className="md__ul">
              {b.items.map((it, j) => (
                <li key={j}>{renderInline(it, `u${i}-${j}`)}</li>
              ))}
            </ul>
          );
        if (b.type === "ol")
          return (
            <ol key={i} className="md__ol">
              {b.items.map((it, j) => (
                <li key={j}>{renderInline(it, `o${i}-${j}`)}</li>
              ))}
            </ol>
          );
        return (
          <p key={i} className="md__text">
            {renderInline(b.text, `p${i}`)}
          </p>
        );
      })}
    </>
  );
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
          <Blocks key={i} text={s.content} />
        ),
      )}
    </div>
  );
}
