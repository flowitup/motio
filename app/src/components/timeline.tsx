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

/** The three tracks of the editor: SHOTS (a block per script line), VOICE (a bar per spoken word), CAPTIONS (blocks of ~3 words),
 *  with the cyan playhead. Click anywhere on the tracks to move the video there. */
export function TimelineStrip({
  marks,
  texts,
  words,
  total,
  playhead,
  active,
  labels,
  onSeek,
}: {
  marks: Mark[];
  texts: string[];
  words: number[] | null;
  total: number;
  playhead: number;
  active: number;
  labels: { shots: string; voice: string; captions: string };
  onSeek: (sec: number) => void;
}) {
  const pct = (sec: number) => `${Math.max(0, Math.min(100, (sec / total) * 100))}%`;
  const ticks = Array.from({ length: Math.floor(total / 20) + 1 }, (_, i) => i * 20);
  // Voice bars: the real word starts when there are any, otherwise evenly inside each line.
  const bars =
    words ??
    marks.flatMap((m, i) => {
      const n = Math.max(1, (texts[i] ?? "").split(/\s+/).filter(Boolean).length);
      return Array.from({ length: n }, (_, k) => m.start + ((m.end - m.start) * k) / n);
    });
  // Caption blocks: ~3 words each, spread over the line they belong to.
  const blocks = marks.flatMap((m, i) => {
    const n = Math.max(1, Math.ceil((texts[i] ?? "").split(/\s+/).filter(Boolean).length / 3));
    return Array.from({ length: n }, (_, k) => ({ start: m.start + ((m.end - m.start) * k) / n, end: m.start + ((m.end - m.start) * (k + 1)) / n, line: i }));
  });
  return (
    <div className="p-4">
      <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-x-3">
        <span />
        <div className="relative h-4 font-mono text-xs leading-4 text-muted-foreground tabular-nums">
          {ticks.map((s) => (
            <span key={s} className="absolute" style={{ left: pct(s), transform: s === 0 ? undefined : "translateX(-50%)" }}>
              {mmss(s)}
            </span>
          ))}
        </div>
        <div className="space-y-2 pt-2 font-mono text-xs leading-4 tracking-[0.06em] text-muted-foreground uppercase">
          <div className="flex h-8 items-center">{labels.shots}</div>
          <div className="flex h-9 items-center">{labels.voice}</div>
          <div className="flex h-6 items-center">{labels.captions}</div>
        </div>
        <div
          className="relative cursor-crosshair space-y-2 pt-2"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            onSeek(Math.max(0, Math.min(total, ((e.clientX - r.left) / r.width) * total)));
          }}
        >
          <div className="relative h-8">
            {marks.map((m, i) => (
              <div
                key={i}
                className={cn(
                  "absolute inset-y-0 overflow-hidden border px-1.5 font-mono text-xs leading-[30px] tabular-nums",
                  i === active ? "border-amber bg-amber/18 text-foreground" : "border-transparent bg-lift text-muted-foreground",
                )}
                style={{ left: pct(m.start), width: `calc(${pct(m.end)} - ${pct(m.start)} - 2px)` }}
              >
                {String(i + 1).padStart(2, "0")}
              </div>
            ))}
          </div>
          <div className="relative h-9">
            {bars.map((t, i) => (
              <span
                key={i}
                className="absolute bottom-1/2 w-0.5 translate-y-1/2 bg-cyan"
                style={{ left: pct(t), height: `${8 + ((i * 37) % 7) * 4}px` }}
              />
            ))}
          </div>
          <div className="relative h-6">
            {blocks.map((b, i) => (
              <div
                key={i}
                className={cn("absolute inset-y-0", b.line === active && playhead >= b.start && playhead < b.end ? "bg-amber" : "bg-lift")}
                style={{ left: pct(b.start), width: `calc(${pct(b.end)} - ${pct(b.start)} - 2px)` }}
              />
            ))}
          </div>
          <div className="pointer-events-none absolute inset-y-0 w-px bg-cyan" style={{ left: pct(playhead) }}>
            <span className="absolute -top-1 left-1/2 size-2 -translate-x-1/2 rounded-full bg-cyan" />
            <span className="absolute -top-5 left-1 rounded-xs bg-cyan px-1 font-mono text-xs leading-4 whitespace-nowrap text-monitor tabular-nums">
              {hhmmss(playhead)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
