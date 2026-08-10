/**
 * A small Markdown renderer — enough for what a chat model actually emits:
 * fenced code, inline code, headings, lists, blockquotes, rules, bold, italic,
 * strikethrough and links.
 *
 * Why hand-rolled instead of `marked` from a CDN: model output is untrusted, so
 * it has to be escaped before it ever reaches innerHTML. Here escaping happens
 * first and formatting is applied to already-escaped text, so there is no path
 * from model output to live HTML. It also means no network dependency inside the
 * container.
 */

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (char) => ESCAPES[char]);
}

const SAFE_URL = /^(https?:\/\/|mailto:|\/|#)/i;

/** Inline spans. Code spans are pulled out first so nothing rewrites them. */
function inline(text) {
  const codeSpans = [];
  let out = text.replace(/`([^`\n]+)`/g, (_, code) => {
    codeSpans.push(code);
    return `\u0000${codeSpans.length - 1}\u0000`;
  });

  out = escapeHtml(out);

  out = out.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (whole, label, href) => {
    const url = href.replace(/&amp;/g, "&");
    if (!SAFE_URL.test(url)) return whole; // javascript:, data:, ... stay as text
    return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });

  out = out
    .replace(/\*\*([^\n]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^\n]+?)__/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\n]+?)\*(?![*\w])/g, "$1<em>$2</em>")
    .replace(/(^|[^_\w])_([^_\n]+?)_(?![_\w])/g, "$1<em>$2</em>")
    .replace(/~~([^\n]+?)~~/g, "<del>$1</del>");

  return out.replace(
    /\u0000(\d+)\u0000/g,
    (_, index) => `<code>${escapeHtml(codeSpans[Number(index)])}</code>`,
  );
}

function codeBlock(language, source) {
  const label = language ? ` data-lang="${escapeHtml(language)}"` : "";
  return `<pre${label}><code>${escapeHtml(source)}</code></pre>`;
}

const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^(\s*)[-*+]\s+(.*)$/;
const NUMBERED = /^(\s*)\d+[.)]\s+(.*)$/;
const RULE = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/;
const QUOTE = /^\s*>\s?(.*)$/;

/** Block-level rendering of a chunk that contains no fenced code. */
function renderBlocks(text) {
  const lines = text.split("\n");
  const html = [];
  let paragraph = [];
  let quote = [];
  // Open list levels, outermost first: { tag, itemOpen }. `itemOpen` matters
  // because a nested list has to go *inside* the parent's still-open <li> —
  // a <ul> as a direct child of a <ul> is invalid HTML.
  const lists = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${paragraph.map(inline).join("<br>")}</p>`);
    paragraph = [];
  };

  const flushQuote = () => {
    if (!quote.length) return;
    html.push(`<blockquote>${quote.map(inline).join("<br>")}</blockquote>`);
    quote = [];
  };

  const closeListsTo = (depth) => {
    while (lists.length > depth) {
      const level = lists.pop();
      if (level.itemOpen) html.push("</li>");
      html.push(`</${level.tag}>`);
    }
  };

  const flushAll = () => {
    flushParagraph();
    flushQuote();
    closeListsTo(0);
  };

  for (const line of lines) {
    if (!line.trim()) {
      flushAll();
      continue;
    }

    const rule = RULE.exec(line);
    if (rule && !paragraph.length) {
      flushAll();
      html.push("<hr>");
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flushAll();
      const level = heading[1].length;
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }

    const quoted = QUOTE.exec(line);
    if (quoted) {
      flushParagraph();
      closeListsTo(0);
      quote.push(quoted[1]);
      continue;
    }

    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    const item = bullet || numbered;
    if (item) {
      flushParagraph();
      flushQuote();
      const tag = bullet ? "ul" : "ol";
      // Two spaces of indent per nesting level, the usual convention.
      const depth = Math.floor(item[1].replace(/\t/g, "  ").length / 2) + 1;

      closeListsTo(depth);
      // Opening a deeper level leaves the parent's <li> open, so the new list
      // nests inside it.
      while (lists.length < depth) {
        html.push(`<${tag}>`);
        lists.push({ tag, itemOpen: false });
      }

      const level = lists[lists.length - 1];
      if (level.itemOpen) html.push("</li>");
      html.push(`<li>${inline(item[2])}`);
      level.itemOpen = true;
      continue;
    }

    flushQuote();
    closeListsTo(0);
    paragraph.push(line);
  }

  flushAll();
  return html.join("");
}

/**
 * Render Markdown to safe HTML. An unterminated fence renders as a code block
 * anyway, so a stream that stops mid-block still looks right.
 */
export function renderMarkdown(source) {
  const lines = String(source ?? "").split("\n");
  const html = [];
  let plain = [];
  let i = 0;

  while (i < lines.length) {
    const opening = /^\s*```(.*)$/.exec(lines[i]);
    if (!opening) {
      plain.push(lines[i]);
      i += 1;
      continue;
    }

    html.push(renderBlocks(plain.join("\n")));
    plain = [];

    const language = opening[1].trim();
    const code = [];
    i += 1;
    while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
      code.push(lines[i]);
      i += 1;
    }
    i += 1; // step over the closing fence, or past the end if there isn't one
    html.push(codeBlock(language, code.join("\n")));
  }

  html.push(renderBlocks(plain.join("\n")));
  return html.join("");
}
