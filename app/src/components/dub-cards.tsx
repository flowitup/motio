import { useMutation, useQuery } from "@tanstack/react-query";
import { Clapperboard, Eraser, Loader2, Mic, Pause, Play, RotateCcw } from "lucide-react";
import { type PointerEvent, type RefObject, useRef, useState } from "react";
import { Field } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/studio";
import { Input } from "@/components/ui/input";
import { VoicePicker } from "@/components/voice-picker";
import type { Api, BlurBox, ProjectDetail } from "@/lib/api";
import { t } from "@/i18n";

/** "1:05" hoặc "65" → giây; "" → null; sai → NaN. */
export function parseClock(text: string): number | null {
  const s = text.trim();
  if (!s) return null;
  const m = /^(?:(\d+):)?(\d+(?:\.\d+)?)$/.exec(s);
  return m ? Number(m[1] ?? 0) * 60 + Number(m[2]) : NaN;
}

export function clock(sec: number | null | undefined): string {
  if (sec == null) return "";
  const s = Math.round(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const sameBox = (a: BlurBox | null, b: BlurBox | null) => JSON.stringify(a) === JSON.stringify(b);

/** Đoạn gốc bên cạnh bản lồng tiếng (video ở cột trái): phát cả hai cùng lúc, và đổi đoạn cần lồng. */
export function DubCompareCard({
  api,
  p,
  dubVideo,
  active,
  onQueued,
}: {
  api: Api;
  p: ProjectDetail;
  dubVideo: RefObject<HTMLVideoElement | null>;
  active: boolean;
  onQueued: () => void;
}) {
  const d = p.dub!;
  const orig = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [a, b] = d.excerpt ?? [0, 0];
  const [from, setFrom] = useState(clock(d.start)); // trống = Motio tự chọn
  const [to, setTo] = useState(clock(d.end));
  const padIn = d.pad?.[0] ?? 0;
  const start = parseClock(from);
  const end = parseClock(to);
  const badTime = Number.isNaN(start) || Number.isNaN(end);

  const toggle = async () => {
    const o = orig.current;
    const v = dubVideo.current;
    if (!o) return;
    if (playing) {
      o.pause();
      v?.pause();
      return;
    }
    o.currentTime = a;
    if (v) v.currentTime = padIn;
    await Promise.all([o.play(), v?.play()]).catch(() => undefined);
  };
  const redo = useMutation({
    mutationFn: async () => {
      const r = await api.updateDub(p.id, { start, end });
      if (r.rerun) await api.retry(p.id, "script");
      return r;
    },
    onSuccess: onQueued,
  });
  if (!d.source || !d.excerpt) return null;
  const changed = (start ?? null) !== (d.start ?? null) || (end ?? null) !== (d.end ?? null);

  return (
    <Panel title={t.dub.compare} bodyClassName="grid gap-3 text-[13px]">
      <p className="text-xs leading-[18px] text-muted-foreground">{t.dub.compareHint}</p>
        <div className="overflow-hidden rounded-lg bg-black">
          <video
            ref={orig}
            src={`${api.mediaUrl(d.source)}#t=${a},${b}`}
            preload="metadata"
            controls
            className="block max-h-96 w-full"
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onTimeUpdate={(e) => {
              if (e.currentTarget.currentTime >= b) {
                e.currentTarget.pause();
                dubVideo.current?.pause();
              }
            }}
          />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" onClick={toggle} disabled={active}>
            {playing ? <Pause /> : <Play />}
            {playing ? t.dub.pause : t.dub.playBoth}
          </Button>
          <span className="text-xs text-muted-foreground">
            {t.dub.part2(clock(a), clock(b))}
            {padIn + (d.pad?.[1] ?? 0) > 0.5 && ` · ${t.dub.pads(padIn + (d.pad?.[1] ?? 0))}`}
          </span>
        </div>
        <div className="grid items-end gap-3 border-t pt-3 sm:grid-cols-[1fr_1fr_auto]">
          <Field label={t.dub.from}>
            <Input value={from} onChange={(e) => setFrom(e.target.value)} placeholder={clock(a)} disabled={active} />
          </Field>
          <Field label={t.dub.to}>
            <Input value={to} onChange={(e) => setTo(e.target.value)} placeholder={clock(b)} disabled={active} />
          </Field>
          <Button
            variant="outline"
            onClick={() => redo.mutate()}
            disabled={active || redo.isPending || badTime || !changed}
          >
            {redo.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />}
            {t.dub.usePart}
          </Button>
        </div>
        {changed && <p className="text-xs text-amber">{t.dub.partRedo}</p>}
        {badTime && <p className="text-xs text-destructive">{t.dub.badTime}</p>}
        {redo.error && <p className="text-destructive">{redo.error.message}</p>}
    </Panel>
  );
}

/** Khung làm mờ phụ đề in sẵn của video gốc: vẽ trên một khung hình của đoạn đã chọn. */
export function DubBlurCard({
  api,
  p,
  active,
  onQueued,
}: {
  api: Api;
  p: ProjectDetail;
  active: boolean;
  onQueued: () => void;
}) {
  const d = p.dub!;
  const vid = useRef<HTMLVideoElement>(null);
  const drag = useRef<[number, number] | null>(null);
  const [box, setBox] = useState<BlurBox | null>(d.blur);
  const [at, setAt] = useState(0.3);
  const [a, b] = d.excerpt ?? [0, 0];
  const seek = (frac: number) => {
    setAt(frac);
    if (vid.current) vid.current.currentTime = a + (b - a) * frac;
  };
  const point = (e: PointerEvent<HTMLDivElement>): [number, number] => {
    const r = e.currentTarget.getBoundingClientRect();
    return [Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1), Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1)];
  };
  const rect = (p0: [number, number], p1: [number, number]): BlurBox => [
    Math.min(p0[0], p1[0]),
    Math.min(p0[1], p1[1]),
    Math.abs(p1[0] - p0[0]),
    Math.abs(p1[1] - p0[1]),
  ];
  const save = useMutation({
    mutationFn: async () => {
      const r = await api.updateDub(p.id, { blur: box });
      if (r.rerun) await api.retry(p.id, r.rerun);
      return r;
    },
    onSuccess: onQueued,
  });
  if (!d.source || !d.excerpt) return null;
  const dirty = !sameBox(box, d.blur);
  const tooSmall = !!box && (box[2] < 0.02 || box[3] < 0.02);

  return (
    <Panel title={t.dub.blur} bodyClassName="grid gap-3 text-[13px]">
      <p className="text-xs leading-[18px] text-muted-foreground">{t.dub.blurHint}</p>
        <div className="relative overflow-hidden rounded-lg bg-black">
          <video
            ref={vid}
            src={`${api.mediaUrl(d.source)}#t=${a + (b - a) * 0.3}`}
            preload="auto"
            muted
            playsInline
            className="pointer-events-none block max-h-96 w-full"
          />
          <div
            className="absolute inset-0 cursor-crosshair touch-none"
            onPointerDown={(e) => {
              if (active) return;
              e.currentTarget.setPointerCapture(e.pointerId);
              drag.current = point(e);
            }}
            onPointerMove={(e) => drag.current && setBox(rect(drag.current, point(e)))}
            onPointerUp={() => (drag.current = null)}
          >
            {box && (
              <div
                className="pointer-events-none absolute border-2 border-dashed border-amber bg-amber/25"
                style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${box[2] * 100}%`, height: `${box[3] * 100}%` }}
              />
            )}
          </div>
        </div>
        <Field label={t.dub.moment}>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={at}
            onChange={(e) => seek(Number(e.target.value))}
            className="w-full"
            aria-label={t.dub.moment}
          />
        </Field>
        <p className="text-xs text-muted-foreground">
          {box ? (d.blur_auto && !dirty ? t.dub.blurAuto : t.dub.blurMine) : t.dub.blurNone} · {t.dub.blurDraw}
        </p>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {save.error && <p className="mr-auto text-destructive">{save.error.message}</p>}
          <Button variant="ghost" onClick={() => setBox(null)} disabled={active || !box}>
            <Eraser />
            {t.dub.blurClear}
          </Button>
          <Button onClick={() => save.mutate()} disabled={active || save.isPending || !dirty || tooSmall}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <Clapperboard />}
            {t.dub.blurSave}
          </Button>
        </div>
    </Panel>
  );
}

/** Giọng cho từng người nói (khi có nhiều hơn một): Motio tự chọn từ giọng của kênh, ở đây chọn lại từng người. */
export function DubVoicesCard({
  api,
  p,
  active,
  onQueued,
}: {
  api: Api;
  p: ProjectDetail;
  active: boolean;
  onQueued: () => void;
}) {
  const speakers = p.dub?.speakers ?? [];
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: () => api.health(), staleTime: 30_000 });
  const hasKey = health?.providers.tts === "elevenlabs";
  const saved = Object.fromEntries(speakers.map((s) => [s.label, s.voice_id]));
  const [picks, setPicks] = useState<Record<string, string>>(saved);
  const changed = speakers.some((s) => (picks[s.label] ?? "") !== s.voice_id);
  const save = useMutation({
    mutationFn: async () => {
      const r = await api.updateDub(p.id, { voices: picks });
      if (r.rerun) await api.retry(p.id, r.rerun);
      return r;
    },
    onSuccess: onQueued,
  });
  if (speakers.length < 2) return null;

  return (
    <Panel title={t.dub.voices} bodyClassName="grid gap-3 text-[13px]">
      <p className="text-xs leading-[18px] text-muted-foreground">{hasKey ? t.dub.voicesHint : t.dub.voicesNeedKey}</p>
        {speakers.map((s) => (
          <div key={s.label} className="grid items-center gap-2 sm:grid-cols-[1fr_1fr]">
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <Mic className="size-3.5 self-center text-muted-foreground" />
                <span className="font-medium">{s.label}</span>
                {s.gender && <span className="text-xs text-muted-foreground">{t.dub.gender[s.gender]}</span>}
              </div>
              {s.who && <div className="truncate text-xs text-muted-foreground">{s.who}</div>}
              {s.voice_name && (
                <div className="text-xs text-muted-foreground">
                  {t.dub.voiceUsed}: {s.voice_name}
                </div>
              )}
            </div>
            <VoicePicker
              api={api}
              value={picks[s.label] ?? ""}
              onChange={(v) => setPicks((x) => ({ ...x, [s.label]: v }))}
              hasKey={hasKey}
              autoLabel={t.dub.voiceAuto}
            />
          </div>
        ))}
        <div className="flex flex-wrap items-center justify-end gap-2">
          {save.error && <p className="mr-auto text-destructive">{save.error.message}</p>}
          <Button onClick={() => save.mutate()} disabled={active || save.isPending || !changed}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <Clapperboard />}
            {t.dub.voicesSave}
          </Button>
        </div>
    </Panel>
  );
}
