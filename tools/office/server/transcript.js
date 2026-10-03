// Turns raw Claude Code transcript JSONL lines into small display entries for the log panel.

const clip = (s, n = 4000) => (s.length > n ? s.slice(0, n) + `\n… (${s.length - n} more chars)` : s);

function textOf(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content
      .map((c) => (typeof c === 'string' ? c : c?.type === 'text' ? c.text : c?.type === 'image' ? '[image]' : ''))
      .filter(Boolean)
      .join('\n');
  }
  return '';
}

const unescape = (t) => t.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');

/**
 * Projects threads receive their brief wrapped in harness envelopes:
 *   <session-context …> project instructions, memory, files </session-context>
 *   <wake …><project …><thread …><message from="human" author="…">TEXT</message>…<system-note>…</system-note></wake>
 * Returns { kind, text } with the envelope removed, or null when the text is not wrapped.
 */
export function unwrapBrief(raw) {
  const t = String(raw || '').trim();
  if (t.startsWith('<session-context')) {
    return { kind: 'system', text: `Session context loaded (project instructions, memory and files, ${t.length.toLocaleString('en')} chars)` };
  }
  if (t.startsWith('<wake')) {
    const msgs = [...t.matchAll(/<message\b([^>]*)>([\s\S]*?)<\/message>/g)];
    const pick = msgs.find((m) => /trigger="true"/.test(m[1])) || msgs[msgs.length - 1];
    if (pick) {
      const author = /author="([^"]*)"/.exec(pick[1])?.[1];
      const body = unescape(pick[2].replace(/<[^>]+>/g, '')).trim();
      return { kind: 'user', text: body, author };
    }
    return { kind: 'user', text: unescape(t.replace(/<system-note>[\s\S]*?<\/system-note>/g, '').replace(/<[^>]+>/g, '')).trim() };
  }
  return null;
}

/** A one-line thread title from a prompt (envelopes removed). Empty string when there is nothing useful. */
export function titleFrom(prompt) {
  // The hook truncates prompts, which can cut a <wake> envelope before </message>; leave the title to the transcript then.
  if (/^\s*<wake/.test(prompt || '') && !/<\/message>/.test(prompt)) return '';
  const w = unwrapBrief(prompt);
  if (w && w.kind !== 'user') return '';
  const text = (w ? w.text : String(prompt || '')).trim();
  return text.split('\n').find((l) => l.trim())?.trim().slice(0, 80) || '';
}

// mcp__hearthbot__update_status → update_status
const toolName = (n) => (typeof n === 'string' && n.startsWith('mcp__') ? n.split('__').slice(2).join('__') || n : n);

function inputLabel(input) {
  if (!input || typeof input !== 'object') return '';
  for (const k of ['command', 'file_path', 'path', 'pattern', 'url', 'query', 'description', 'text']) {
    if (typeof input[k] === 'string' && input[k]) return input[k];
  }
  return JSON.stringify(input).slice(0, 300);
}

/** @returns {Array<{kind:string, ts?:string, text:string, tool?:string, error?:boolean}>} */
export function parseLine(line) {
  let o;
  try {
    o = JSON.parse(line);
  } catch {
    return [];
  }
  const ts = o.timestamp;
  const side = o.isSidechain ? { sub: true } : {};
  const out = [];
  if (o.type === 'summary' && o.summary) return [{ kind: 'system', ts, text: `Summary: ${o.summary}` }];
  if (o.type === 'system' && o.content) return [{ kind: 'system', ts, text: clip(String(o.content), 600) }];
  const msg = o.message;
  if (!msg) return [];
  const blocks = typeof msg.content === 'string' ? [{ type: 'text', text: msg.content }] : msg.content || [];
  for (const b of blocks) {
    if (!b) continue;
    if (b.type === 'text' && b.text?.trim()) {
      if (o.type === 'user' && /^<(command|local-command|system-reminder)/.test(b.text.trim())) continue;
      const w = o.type === 'user' ? unwrapBrief(b.text) : null;
      if (w) { out.push({ kind: w.kind, ts, text: clip(w.text), ...(w.author ? { author: w.author } : {}), ...side }); continue; }
      out.push({ kind: o.type === 'user' ? 'user' : 'assistant', ts, text: clip(b.text), ...side });
    } else if (b.type === 'thinking' && b.thinking?.trim()) {
      out.push({ kind: 'thinking', ts, text: clip(b.thinking, 1500), ...side });
    } else if (b.type === 'tool_use') {
      out.push({ kind: 'tool', ts, tool: toolName(b.name), text: clip(inputLabel(b.input), 600), ...side });
    } else if (b.type === 'tool_result') {
      out.push({ kind: 'result', ts, text: clip(textOf(b.content) || '(no output)', 1500), error: !!b.is_error, ...side });
    }
  }
  return out;
}
