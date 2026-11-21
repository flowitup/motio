import { useQuery } from "@tanstack/react-query";
import type { Api } from "@/lib/api";
import { cn } from "@/lib/utils";

/** What the engine saved about the last voice (audio/narration.json): total length, each line's span, the spoken words' starts. */
export type Narration = { duration: number; lines: { start: number; end: number }[]; texts: string[]; words: number[] | null };

/** "1:21" for the mono figures, "00:00:12" for the player timecode. */
export const mmss = (sec: number) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
export const hhmmss = (sec: number) => {
  const s = Math.max(0, Math.floor(sec));
  return `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

/** Start of every word in the ElevenLabs alignment (character starts → words split on spaces); null when the voice has none. */
function wordStarts(al: { characters?: string[]; character_start_times_seconds?: number[] } | null | undefined): number[] | null {
  const chars = al?.characters;
  const starts = al?.character_start_times_seconds;
  if (!chars?.length || !starts || starts.length !== chars.length) return null;
  const out: number[] = [];
  chars.forEach((c, i) => {
    if (c.trim() && (i === 0 || !chars[i - 1].trim())) out.push(starts[i]);
  });
  return out;
}

/** The measured timing of the last voice of a project, or null (no voice yet, another voice provider, an old project). */
export function useNarration(api: Api, id: number, bust?: number) {
  return useQuery({
    queryKey: ["narration", id, bust],
    queryFn: async (): Promise<Narration | null> => {
      try {
        const r = await fetch(api.mediaUrl(`projects/${id}/audio/narration.json`, bust));
        if (!r.ok) return null;
        const j = await r.json();
        if (!Array.isArray(j.lines) || !(j.duration > 0)) return null;
        return {
          duration: Number(j.duration),
          lines: j.lines.map((l: { start: number; end: number }) => ({ start: Number(l.start) || 0, end: Number(l.end) || 0 })),
          texts: Array.isArray(j.texts) ? j.texts.map(String) : [],
          words: wordStarts(j.alignment),
        };
      } catch {
        return null;
      }
    },
    retry: false,
    staleTime: 30_000,
  });
}

export type Mark = { start: number; end: number };

/** Index of the line spoken at `t` (the last one that has started), -1 before the first. */
export const lineAt = (marks: Mark[], t: number) => {
  let at = -1;
  marks.forEach((m, i) => {
    if (t >= m.start) at = i;
  });
  return at;
};

/** The editor's tracks, like a video editor's timeline: PICTURES (one block per script line, filled with stills of the
 *  finished video when there is one), VOICE (a bar per spoken word), ORIGINAL SOUND (the source's level under the voice,
 *  when the video keeps it) and CAPTIONS (a block per line with its text), under a ruler, with the pink playhead.
 *  Click anywhere on the tracks to move the video there. */
export function TimelineStrip({
  marks,
  texts,
  words,
  total,
  playhead,
  active,
  labels,
  onSeek,
  frame,
  sourceLevel,
}: {
  marks: Mark[];
  texts: string[];
  words: number[] | null;
  total: number;
  playhead: number;
  active: number;
  labels: { shots: string; voice: string; source: string; captions: string };
  onSeek: (sec: number) => void;
  frame?: (sec: number) => string; // a still of the video at that time; none = plain blocks
  sourceLevel?: number | null; // 0–1, the original sound under the voice; null = no original sound
}) {
  const pct = (sec: number) => `${Math.max(0, Math.min(100, (sec / total) * 100))}%`;
  const step = total > 240 ? 60 : total > 120 ? 30 : 10;
  const ticks = Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step);
  // Voice bars: the real word starts when there are any, otherwise evenly inside each line.
  const bars =
    words ??
    marks.flatMap((m, i) => {
      const n = Math.max(1, (texts[i] ?? "").split(/\s+/).filter(Boolean).length);
      return Array.from({ length: n * 2 }, (_, k) => m.start + ((m.end - m.start) * k) / (n * 2));
    });
  // Caption blocks: one per line, with its words (the burned captions show ~3 words at a time inside it).
  const blocks = marks.map((m, i) => ({ start: m.start, end: m.end, line: i, text: texts[i] ?? "" }));
  const hasSource = sourceLevel != null;
  const span = (a: number, b: number) => ({ left: pct(a), width: `calc(${pct(b)} - ${pct(a)} - 2px)` });
  return (
    <div className="timeline px-4 pt-2 pb-3">
      <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-x-3">
        <span />
        <div className="relative h-5 border-b font-mono text-xs leading-4 text-muted-foreground tabular-nums">
          {ticks.map((s) => (
            <span key={s} className="absolute top-0 flex flex-col" style={{ left: pct(s), transform: s === 0 ? undefined : "translateX(-50%)" }}>
              {mmss(s)}
            </span>
          ))}
        </div>
        <div className="space-y-1.5 pt-1.5 text-xs leading-4 text-muted-foreground">
          <div className="flex h-10 items-center">{labels.shots}</div>
          <div className="flex h-7 items-center">{labels.voice}</div>
          {hasSource && <div className="flex h-6 items-center">{labels.source}</div>}
          <div className="flex h-6 items-center">{labels.captions}</div>
        </div>
        <div
          className="relative cursor-crosshair space-y-1.5 pt-1.5"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            onSeek(Math.max(0, Math.min(total, ((e.clientX - r.left) / r.width) * total)));
          }}
        >
          <div className="relative h-10">
            {marks.map((m, i) => (
              <div
                key={i}
                className={cn(
                  "absolute inset-y-0 overflow-hidden rounded-sm bg-blue/70 bg-repeat-x",
                  i === active ? "ring-2 ring-cyan ring-inset" : "",
                )}
                style={{
                  ...span(m.start, m.end),
                  backgroundImage: frame ? `url("${frame((m.start + m.end) / 2)}")` : undefined,
                  backgroundSize: "auto 100%",
                }}
              >
                <span className="absolute top-1 left-1 rounded-xs bg-black/60 px-1 font-mono text-xs leading-4 text-white tabular-nums">
                  {String(i + 1).padStart(2, "0")}
                </span>
              </div>
            ))}
          </div>
          <div className="relative h-7">
            {marks.map((m, i) => (
              <div key={i} className="absolute inset-y-0 rounded-sm bg-violet/12" style={span(m.start, m.end)} />
            ))}
            {bars.map((tm, i) => (
              <span
                key={i}
                className="absolute bottom-1/2 w-0.5 translate-y-1/2 rounded-full bg-violet"
                style={{ left: pct(tm), height: `${6 + ((i * 37) % 7) * 3}px` }}
              />
            ))}
          </div>
          {hasSource && (
            <div className="relative h-6">
              <div className="absolute inset-y-0 flex items-center rounded-sm bg-violet/25 px-1.5 font-mono text-xs leading-4 text-muted-foreground tabular-nums" style={span(0, total)}>
                {Math.round((sourceLevel ?? 0) * 100)}%
              </div>
            </div>
          )}
          <div className="relative h-6">
            {blocks.map((b, i) => (
              <div
                key={i}
                title={b.text}
                className={cn(
                  "absolute inset-y-0 truncate rounded-sm px-1.5 text-xs leading-6 font-semibold",
                  b.line === active ? "bg-amber text-on-amber ring-2 ring-foreground ring-inset" : "bg-amber/85 text-on-amber",
                )}
                style={span(b.start, b.end)}
              >
                {b.text}
              </div>
            ))}
          </div>
          <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-pink" style={{ left: pct(playhead) }}>
            <span className="absolute -top-0.5 left-1/2 size-2.5 -translate-x-1/2 rounded-full bg-pink" />
          </div>
        </div>
      </div>
    </div>
  );
}
