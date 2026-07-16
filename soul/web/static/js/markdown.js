// markdown.js — tiny, dependency-free Markdown → DOM renderer for
// agent-written content (SOUL.md, wiki pages, daily reports, step outputs).
//
// SECURITY: every node is built via document.createElement / textContent —
// input text is NEVER assembled into an HTML string, so there is no injection
// surface. Unknown / unclosed syntax degrades to literal text and never throws.
//
// Supported: #–###### headings · paragraphs · **bold** · *italic* / _italic_ ·
// `inline code` · ``` fenced code blocks (rendered as <pre>, no highlighting) ·
// -/* unordered and 1. ordered lists · > blockquotes · --- horizontal rules ·
// [label](url) links (http/https only; other schemes stay literal) ·
// [[wiki-slug]] links (calls opts.onWikiLink(slug) when provided). Inline marks
// nest one level (e.g. bold inside a list item). Presentation lives in the
// injected `.p-md` stylesheet below — every class is `p-` prefixed, matching
// panels.js's convention.

// One-time stylesheet. `.p-md` fenced <pre> mirrors panels.js's CONTENT_PRE.
const MD_CSS = `
.p-md{word-break:inherit;line-height:inherit}
.p-md h1{font-size:var(--fs-xl);margin:0 0 12px;letter-spacing:-.01em}
.p-md h2{font-size:var(--fs-lg);margin:16px 0 8px}
.p-md h3{font-size:var(--fs-md);margin:14px 0 6px}
.p-md h4,.p-md h5,.p-md h6{font-size:var(--fs-sm);margin:12px 0 6px}
.p-md p{margin:0 0 10px}
.p-md code{font-family:var(--mono);font-size:12.5px;background:var(--panel-2);border:1px solid var(--line-soft);border-radius:4px;padding:1px 5px}
.p-md pre{margin:0 0 10px;background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:14px;font-family:var(--mono);font-size:12.5px;overflow-x:auto;color:var(--ink-soft);white-space:pre-wrap;word-break:break-word}
.p-md blockquote{margin:0 0 10px;border-left:2px solid var(--line);padding-left:10px;color:var(--ink-soft);font-style:italic}
.p-md ul,.p-md ol{margin:0 0 10px;padding-left:20px}
.p-md li{margin:2px 0}
.p-md hr{border:none;border-top:1px solid var(--line-soft);margin:14px 0}
.p-md > :last-child{margin-bottom:0}
.p-md .p-wikilink{color:var(--accent-ink);cursor:pointer;text-decoration:none}
.p-md .p-wikilink:hover{color:var(--accent);text-decoration:underline}
`;
function injectMarkdownStyle() {
  if (typeof document === "undefined" || document.getElementById("p-md-style")) return;
  const style = document.createElement("style");
  style.id = "p-md-style";
  style.textContent = MD_CSS;
  document.head.appendChild(style);
}

// --- block-level parse -----------------------------------------------------

function isBlockStart(line) {
  return /^```/.test(line.trim())
    || /^\s*---+\s*$/.test(line)
    || /^#{1,6}\s+/.test(line)
    || /^\s*>/.test(line)
    || /^\s*[-*]\s+/.test(line)
    || /^\s*\d+\.\s+/.test(line);
}

// Line-based block parser → an array of typed block descriptors.
function parseBlocks(lines) {
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    // Fenced code — content is literal (no inline parsing).
    if (/^```/.test(line.trim())) {
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i].trim())) { buf.push(lines[i]); i++; }
      if (i < lines.length) i++; // consume closing fence (unclosed → EOF ends it)
      blocks.push({ type: "code", content: buf.join("\n") });
      continue;
    }
    if (line.trim() === "") { i++; continue; }
    if (/^\s*---+\s*$/.test(line)) { blocks.push({ type: "hr" }); i++; continue; }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) { blocks.push({ type: "heading", level: h[1].length, text: h[2] }); i++; continue; }
    if (/^\s*>/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) { buf.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
      blocks.push({ type: "quote", text: buf.join("\n") });
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*[-*]\s+/, "")); i++; }
      blocks.push({ type: "list", ordered: false, items });
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*\d+\.\s+/, "")); i++; }
      blocks.push({ type: "list", ordered: true, items });
      continue;
    }
    // Paragraph — consecutive lines until a blank line or a new block start.
    const buf = [];
    while (i < lines.length && lines[i].trim() !== "" && !isBlockStart(lines[i])) { buf.push(lines[i]); i++; }
    blocks.push({ type: "para", text: buf.join("\n") });
  }
  return blocks;
}

// --- inline tokenizer ------------------------------------------------------

function makeWikiLink(slug, opts) {
  if (opts && typeof opts.onWikiLink === "function") {
    const a = document.createElement("a");
    a.href = "#";
    a.className = "p-wikilink";
    a.textContent = slug;
    a.addEventListener("click", (ev) => { ev.preventDefault(); opts.onWikiLink(slug); });
    return a;
  }
  const span = document.createElement("span");
  span.className = "p-wikilink";
  span.textContent = slug;
  return span;
}

// Single-pass inline tokenizer. Appends text/element nodes to `parent`.
// `depth` caps nesting at one level: inner content of bold/italic/links is
// re-tokenized only while depth < 1, otherwise it stays plain text.
function appendInline(parent, text, opts, depth) {
  depth = depth || 0;
  const s = String(text == null ? "" : text);
  let i = 0;
  let plainStart = 0;
  const flush = (end) => { if (end > plainStart) parent.appendChild(document.createTextNode(s.slice(plainStart, end))); };
  const nest = (node, inner) => {
    if (depth < 1) appendInline(node, inner, opts, depth + 1);
    else node.textContent = inner;
  };
  while (i < s.length) {
    const c = s[i];
    // `inline code` — literal content.
    if (c === "`") {
      const close = s.indexOf("`", i + 1);
      if (close > i) {
        flush(i);
        const code = document.createElement("code");
        code.textContent = s.slice(i + 1, close);
        parent.appendChild(code);
        i = close + 1; plainStart = i; continue;
      }
    }
    // **bold**
    if (c === "*" && s[i + 1] === "*") {
      const close = s.indexOf("**", i + 2);
      if (close > i + 1) {
        flush(i);
        const strong = document.createElement("strong");
        nest(strong, s.slice(i + 2, close));
        parent.appendChild(strong);
        i = close + 2; plainStart = i; continue;
      }
    }
    // *italic* / _italic_ (underscore ignored intra-word, e.g. snake_case).
    if (c === "*" || c === "_") {
      const intraWord = c === "_" && i > 0 && /\w/.test(s[i - 1]);
      if (!intraWord) {
        const close = s.indexOf(c, i + 1);
        if (close > i + 1 && (c === "*" || !/\w/.test(s[close + 1] || ""))) {
          flush(i);
          const em = document.createElement("em");
          nest(em, s.slice(i + 1, close));
          parent.appendChild(em);
          i = close + 1; plainStart = i; continue;
        }
      }
    }
    // [[wiki-slug]]
    if (c === "[" && s[i + 1] === "[") {
      const close = s.indexOf("]]", i + 2);
      if (close > i + 1) {
        flush(i);
        parent.appendChild(makeWikiLink(s.slice(i + 2, close).trim(), opts));
        i = close + 2; plainStart = i; continue;
      }
    }
    // [label](url) — http/https only; any other scheme stays literal text.
    if (c === "[") {
      const m = /^\[([^\]]*)\]\(([^)\s]+)\)/.exec(s.slice(i));
      if (m && /^https?:\/\//i.test(m[2])) {
        flush(i);
        const a = document.createElement("a");
        a.href = m[2];
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        nest(a, m[1]);
        parent.appendChild(a);
        i += m[0].length; plainStart = i; continue;
      }
    }
    i++;
  }
  flush(s.length);
}

// --- block render ----------------------------------------------------------

function renderBlock(b, opts) {
  switch (b.type) {
    case "heading": {
      const lvl = Math.min(6, Math.max(1, b.level));
      const h = document.createElement("h" + lvl);
      appendInline(h, b.text, opts);
      return h;
    }
    case "code": {
      const pre = document.createElement("pre");
      pre.textContent = b.content;
      return pre;
    }
    case "hr":
      return document.createElement("hr");
    case "quote": {
      const bq = document.createElement("blockquote");
      appendInline(bq, b.text, opts);
      return bq;
    }
    case "list": {
      const list = document.createElement(b.ordered ? "ol" : "ul");
      b.items.forEach((it) => {
        const li = document.createElement("li");
        appendInline(li, it, opts);
        list.appendChild(li);
      });
      return list;
    }
    case "para":
    default: {
      const p = document.createElement("p");
      appendInline(p, b.text, opts);
      return p;
    }
  }
}

// Render `text` as Markdown into a fresh detached <div class="p-md">. `opts`:
//   onWikiLink(slug)  — invoked when a [[slug]] link is clicked (optional).
export function renderMarkdown(text, opts) {
  injectMarkdownStyle();
  const container = document.createElement("div");
  container.className = "p-md";
  try {
    const lines = String(text == null ? "" : text).replace(/\r\n?/g, "\n").split("\n");
    parseBlocks(lines).forEach((b) => container.appendChild(renderBlock(b, opts || {})));
  } catch (_e) {
    // Never throw — degrade to the literal source text.
    container.textContent = String(text == null ? "" : text);
  }
  return container;
}
