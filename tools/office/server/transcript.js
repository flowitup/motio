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

function inputLabel(input) {
  if (!input || typeof input !== 'object') return '';
  for (const k of ['command', 'file_path', 'path', 'pattern', 'url', 'query', 'description']) {
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
      out.push({ kind: o.type === 'user' ? 'user' : 'assistant', ts, text: clip(b.text), ...side });
    } else if (b.type === 'thinking' && b.thinking?.trim()) {
      out.push({ kind: 'thinking', ts, text: clip(b.thinking, 1500), ...side });
    } else if (b.type === 'tool_use') {
      out.push({ kind: 'tool', ts, tool: b.name, text: clip(inputLabel(b.input), 600), ...side });
    } else if (b.type === 'tool_result') {
      out.push({ kind: 'result', ts, text: clip(textOf(b.content) || '(no output)', 1500), error: !!b.is_error, ...side });
    }
  }
  return out;
}
