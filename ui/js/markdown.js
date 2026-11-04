// A tiny, safe markdown renderer for the PRD/HLD/LLD documents.
// Everything is HTML-escaped first; only the markup generated here reaches the page.
// Supports: headings, paragraphs, bold/italic, inline code, code fences, links (http/https/relative),
// bullet and numbered lists (with one level of nesting), blockquotes, rules and simple tables.

import { escapeHtml as esc } from "./format.js";

function safeUrl(url) {
  const u = url.trim();
  if (/^(https?:|mailto:|\/|#|\.\/|\.\.\/)/i.test(u) || !/^[a-z][a-z0-9+.-]*:/i.test(u)) return u;
  return "#";
}

function inline(src) {
  // Pull out code spans first so their contents stay literal.
  const codes = [];
  let s = src.replace(/`([^`]+)`/g, (_, c) => {
    codes.push(c);
    return `\u0000${codes.length - 1}\u0000`;
  });
  s = esc(s);
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, text, url) => {
    // url is already escaped; unescape &amp; only for the check
    const href = safeUrl(url.replace(/&amp;/g, "&"));
    const ext = /^https?:/i.test(href) ? ' target="_blank" rel="noopener noreferrer"' : "";
    return `<a href="${esc(href)}"${ext}>${text}</a>`;
  });
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  s = s.replace(/(^|\W)_([^_\s][^_]*)_(?=\W|$)/g, "$1<em>$2</em>");
  s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[Number(i)])}</code>`);
  return s;
}

const isTableSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
const cells = (l) =>
  l
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());

export function renderMarkdown(md) {
  const lines = String(md ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (/^\s*$/.test(line)) {
      i++;
      continue;
    }

    // fenced code
    const fence = line.match(/^\s*(```|~~~)/);
    if (fence) {
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) buf.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
      continue;
    }

    const hm = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (hm) {
      const level = hm[1].length;
      out.push(`<h${level}>${inline(hm[2])}</h${level}>`);
      i++;
      continue;
    }

    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      out.push("<hr>");
      i++;
      continue;
    }

    if (/^\s*>/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${renderMarkdown(buf.join("\n"))}</blockquote>`);
      continue;
    }

    if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push(
        `<div class="md-table"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead>` +
          `<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
      );
      continue;
    }

    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const [html, next] = list(lines, i);
      out.push(html);
      i = next;
      continue;
    }

    // paragraph: gather until a blank line or another block starts
    const buf = [line.trim()];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,6}\s|\s*```|\s*~~~|\s*>|\s*([-*+]|\d+[.)])\s+)/.test(lines[i])
    ) {
      buf.push(lines[i++].trim());
    }
    out.push(`<p>${inline(buf.join(" "))}</p>`);
  }
  return out.join("\n");
}

function list(lines, start) {
  const indentOf = (l) => l.match(/^\s*/)[0].length;
  const base = indentOf(lines[start]);
  const ordered = /^\s*\d+[.)]/.test(lines[start]);
  const items = [];
  let i = start;
  while (i < lines.length) {
    const l = lines[i];
    if (!l.trim()) {
      // a blank line ends the list unless the next line continues it
      if (i + 1 < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i + 1]) && indentOf(lines[i + 1]) >= base) {
        i++;
        continue;
      }
      break;
    }
    const m = l.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
    if (m && m[1].length === base) {
      items.push({ text: m[3], children: [] });
      i++;
    } else if (m && m[1].length > base && items.length) {
      const [html, next] = list(lines, i);
      items[items.length - 1].children.push(html);
      i = next;
    } else if (indentOf(l) > base && items.length) {
      items[items.length - 1].text += " " + l.trim();
      i++;
    } else break;
  }
  const tag = ordered ? "ol" : "ul";
  const body = items.map((it) => `<li>${inline(it.text)}${it.children.join("")}</li>`).join("");
  return [`<${tag}>${body}</${tag}>`, i];
}
