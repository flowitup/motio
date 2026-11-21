import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Film, Loader2, Pause, Play, Plus, Scissors, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ChannelChoice, useChannelChoice } from "@/components/channel-choice";
import { clock, parseClock } from "@/components/dub-cards";
import { Choice } from "@/components/form";
import { PageTitle, Panel, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useApi, type Api, type ClipCaptions, type ClipCrop, type ClipMoment, type ClipperJob } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const MAX_LEN = 90; // clipper.MAX_LEN: Facebook Reels limit
const LONG_MIN = 62; // clipper.MIN_LONG
const SHORT_MIN = 15; // clipper.MIN_SHORT
const SNAP = 0.4; // seconds: a handle close to a scene cut jumps onto it
const KEY_NEAR = 0.4; // seconds: dragging the frame near a position changes that position instead of adding one
const COLORS = ["bg-cyan", "bg-pink", "bg-amber", "bg-mint", "bg-violet", "bg-orange"];

type Moment = ClipMoment & { id: number; on: boolean };

const minLen = (short: boolean) => (short ? SHORT_MIN : LONG_MIN);
const round1 = (n: number) => Math.round(n * 10) / 10;
const clamp = (n: number, lo: number, hi: number) => Math.min(Math.max(n, lo), hi);

/** Centre of the crop frame (0..1) at `tRel` seconds into the clip: linear between positions, constant outside them (as the engine renders it). */
function xAt(keys: [number, number][], tRel: number): number {
  if (keys.length === 0) return 0.5;
  if (tRel <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) {
    const [t1, x1] = keys[i];
    if (tRel < t1) {
      const [t0, x0] = keys[i - 1];
      return x0 + ((x1 - x0) * (tRel - t0)) / Math.max(t1 - t0, 0.01);
    }
  }
  return keys[keys.length - 1][1];
}

/** Move the crop frame at `tRel`: one position = a fixed frame (it moves); several = the one near `tRel` moves, else a new one is added. */
function moveCrop(crop: ClipCrop, tRel: number, x: number): ClipCrop {
  const keys = crop.x.map((k) => [...k] as [number, number]);
  x = Math.round(clamp(x, 0, 1) * 1000) / 1000;
  if (keys.length <= 1) return { ...crop, x: [[keys[0]?.[0] ?? 0, x]] };
  const near = keys.findIndex(([tt]) => Math.abs(tt - tRel) < KEY_NEAR);
  if (near >= 0) keys[near][1] = x;
  else keys.push([round1(tRel), x]);
  return { ...crop, x: keys.sort((a, b) => a[0] - b[0]) };
}

/** Opens when the engine has read the video: the player with the 9:16 frame, the timeline, one card per moment, and Make videos. */
function Editor({ api, job }: { api: Api; job: ClipperJob }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const src = job.source!;
  const duration = src.duration ?? 0;
  const aspect = src.width && src.height ? src.width / src.height : 16 / 9;
  const lo = minLen(job.short);
  const nextId = useRef(job.clips.length);
  const [moments, setMoments] = useState<Moment[]>(() => job.clips.map((c, i) => ({ ...c, id: i, on: true })));
  const [sel, setSel] = useState(0);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number | null>(null);
  const choice = useChannelChoice(api);

  const cur = moments[Math.min(sel, moments.length - 1)];
  const patch = (id: number, p: Partial<Moment>) => setMoments((all) => all.map((m) => (m.id === id ? { ...m, ...p } : m)));
  const seek = (sec: number) => {
    if (video.current) video.current.currentTime = clamp(sec, 0, duration);
    setTime(clamp(sec, 0, duration));
  };
  const play = (until?: number) => {
    stopAt.current = until ?? null;
    void video.current?.play();
  };
  const cut = (sec: number) => job.cuts.find((c) => Math.abs(c - sec) < SNAP) ?? sec;

  const valid = (m: Moment) => m.end - m.start >= lo - 0.01 && m.end - m.start <= MAX_LEN + 0.01 && m.start >= 0 && m.end <= duration + 0.5;
  const chosen = moments.filter((m) => m.on);
  const ready = chosen.length > 0 && chosen.every(valid);
  const make = useMutation({
    mutationFn: () =>
      api.clipperExport({
        link: job.link,
        short: job.short,
        duration,
        channel: choice.channel,
        clips: chosen.map((m) => ({ start: m.start, end: m.end, hook: m.hook, crop: m.crop, captions: m.captions ?? "fr" })),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate("/projects");
    },
  });

  const add = () => {
    const a = round1(clamp(time, 0, Math.max(duration - lo, 0)));
    const m: Moment = { id: nextId.current++, on: true, start: a, end: round1(Math.min(a + Math.max(lo, 20), duration)), hook: "", crop: { fit: false, x: [[0, 0.5]] }, captions: "fr" };
    setMoments((all) => [...all, m]);
    setSel(moments.length);
  };

  // 9:16 frame over the video: its centre follows the crop positions at the playhead.
  const tRel = cur ? time - cur.start : 0;
  const inside = cur && time >= cur.start && time <= cur.end;
  const frameW = Math.min((9 / 16) / aspect, 1);
  const centre = cur ? xAt(cur.crop.x, clamp(tRel, 0, cur.end - cur.start)) : 0.5;
  const left = clamp(centre - frameW / 2, 0, 1 - frameW);
  const dragFrame = (e: PointerEvent<HTMLDivElement>) => {
    if (!cur || cur.crop.fit || (e.type === "pointermove" && e.buttons !== 1)) return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = clamp((e.clientX - r.left) / r.width, frameW / 2, 1 - frameW / 2);
    patch(cur.id, { crop: moveCrop(cur.crop, clamp(tRel, 0, cur.end - cur.start), x) });
  };

  const trackRef = useRef<HTMLDivElement>(null);
  const at = (e: PointerEvent) => {
    const r = trackRef.current!.getBoundingClientRect();
    return clamp(((e.clientX - r.left) / r.width) * duration, 0, duration);
  };
  const drag = (m: Moment) => (e: PointerEvent<HTMLSpanElement>) => {
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    setSel(moments.indexOf(m));
  };
  const moveEdge = (m: Moment, edge: "start" | "end") => (e: PointerEvent<HTMLSpanElement>) => {
    if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
    const sec = round1(cut(at(e)));
    if (edge === "start") patch(m.id, { start: clamp(sec, Math.max(m.end - MAX_LEN, 0), m.end - lo) });
    else patch(m.id, { end: clamp(sec, m.start + lo, Math.min(m.start + MAX_LEN, duration)) });
    seek(sec);
  };

  const keys = cur?.crop.x ?? [];
  return (
    <>
      <div className="grid min-h-0 flex-1 overflow-y-auto min-[1100px]:grid-cols-[minmax(0,1fr)_400px] min-[1100px]:overflow-hidden">
        <div className="min-w-0 border-r min-[1100px]:overflow-y-auto">
          <Panel title={src.title || t.clipper.title} aside={`${clock(time)} / ${clock(duration)}`} flush>
            <div className="bg-black">
              <div className="relative mx-auto max-h-[44vh]" style={{ aspectRatio: String(aspect), maxWidth: `calc(44vh * ${aspect})` }}>
                <video
                  ref={video}
                  src={api.mediaUrl(src.path!)}
                  className="size-full"
                  preload="metadata"
                  onLoadedMetadata={() => moments[0] && seek(moments[0].start)}
                  onTimeUpdate={(e) => {
                    const tm = e.currentTarget.currentTime;
                    setTime(tm);
                    if (stopAt.current != null && tm >= stopAt.current) {
                      e.currentTarget.pause();
                      stopAt.current = null;
                    }
                  }}
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                />
                {cur && (
                  <div
                    className="absolute inset-0 touch-none"
                    onPointerDown={(e) => {
                      e.currentTarget.setPointerCapture(e.pointerId);
                      dragFrame(e);
                    }}
                    onPointerMove={dragFrame}
                    aria-label={t.clipper.cropHint}
                  >
                    {!cur.crop.fit && inside && (
                      <>
                        <div className="absolute inset-y-0 left-0 bg-black/55" style={{ width: `${left * 100}%` }} />
                        <div className="absolute inset-y-0 right-0 bg-black/55" style={{ width: `${(1 - left - frameW) * 100}%` }} />
                        <div className="absolute inset-y-0 border-2 border-cyan" style={{ left: `${left * 100}%`, width: `${frameW * 100}%` }}>
                          <span className="absolute top-1 left-1 rounded bg-cyan px-1.5 font-mono text-[11px] leading-4 text-black">9:16 · {Math.round(centre * 100)}%</span>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center gap-3 border-t px-4 py-2">
              <Button size="sm" variant="secondary" onClick={() => (playing ? video.current?.pause() : play())}>
                {playing ? <Pause /> : <Play />}
                {playing ? t.clipper.pause : t.clipper.play}
              </Button>
              <Button size="sm" variant="secondary" onClick={add}>
                <Plus />
                {t.clipper.add}
              </Button>
              <span className="min-w-0 truncate text-xs text-muted-foreground">{t.clipper.addHint}</span>
            </div>
          </Panel>

          <Panel title={t.clipper.timeline} aside={t.clipper.cuts(job.cuts.length)} flush>
            <div className="p-4">
              <div
                ref={trackRef}
                className="relative h-14 cursor-pointer touch-none rounded-md border bg-ground"
                onPointerDown={(e) => seek(at(e))}
                role="slider"
                aria-label={t.clipper.timeline}
                aria-valuemin={0}
                aria-valuemax={Math.round(duration)}
                aria-valuenow={Math.round(time)}
              >
                {job.cuts.map((c) => (
                  <span key={c} aria-hidden className="absolute inset-y-0 w-px bg-hairline-strong" style={{ left: `${(c / duration) * 100}%` }} />
                ))}
                {moments.map((m, i) => (
                  <div
                    key={m.id}
                    className={cn("absolute inset-y-2 rounded-sm border", COLORS[i % COLORS.length], i === sel ? "border-white opacity-100" : "opacity-45", !m.on && "opacity-20", !valid(m) && "outline outline-2 outline-coral")}
                    style={{ left: `${(m.start / duration) * 100}%`, width: `${((m.end - m.start) / duration) * 100}%` }}
                    onPointerDown={(e) => {
                      e.stopPropagation();
                      setSel(i);
                      seek(m.start);
                    }}
                    title={`${clock(m.start)} → ${clock(m.end)}`}
                  >
                    <span className="pointer-events-none absolute top-0.5 left-2 font-mono text-[11px] leading-4 font-semibold text-black">{i + 1}</span>
                    {(["start", "end"] as const).map((edge) => (
                      <span
                        key={edge}
                        className={cn("absolute inset-y-0 w-2.5 cursor-ew-resize bg-white/70", edge === "start" ? "left-0" : "right-0")}
                        onPointerDown={drag(m)}
                        onPointerMove={moveEdge(m, edge)}
                        role="separator"
                        aria-label={edge === "start" ? t.clipper.start : t.clipper.end}
                      />
                    ))}
                  </div>
                ))}
                <span aria-hidden className="pointer-events-none absolute inset-y-0 w-0.5 bg-cyan" style={{ left: `${(time / Math.max(duration, 1)) * 100}%` }} />
              </div>
            </div>
          </Panel>

          {cur && (
            <Panel title={t.clipper.crop} aside={cur.crop.fit ? t.clipper.fitOn : `${keys.length}`} flush>
              <div className="grid gap-3 p-4">
                <label className="flex min-h-9 items-center gap-3 text-[13px]" title={t.clipper.fitHint}>
                  <Switch checked={cur.crop.fit} onCheckedChange={(fit) => patch(cur.id, { crop: { ...cur.crop, fit } })} />
                  {t.clipper.fit}
                </label>
                {!cur.crop.fit && (
                  <>
                    <p className="text-xs leading-[18px] text-muted-foreground">{t.clipper.cropHint}</p>
                    <ul className="flex flex-wrap gap-2">
                      {keys.map(([tt, x], i) => (
                        <li key={`${tt}:${i}`} className="inline-flex items-center gap-1 rounded-md border bg-ground py-0.5 pr-1 pl-2 font-mono text-xs">
                          <button type="button" className="hover:text-cyan" onClick={() => seek(cur.start + tt)}>
                            {clock(tt)} · {Math.round(x * 100)}%
                          </button>
                          {keys.length > 1 && (
                            <button
                              type="button"
                              className="rounded p-1 text-muted-foreground hover:text-coral"
                              aria-label={t.clipper.removePosition}
                              onClick={() => patch(cur.id, { crop: { ...cur.crop, x: keys.filter((_, k) => k !== i) } })}
                            >
                              <X className="size-3" />
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                    <div>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={!inside}
                        onClick={() => patch(cur.id, { crop: { ...cur.crop, x: [...keys.filter(([tt]) => Math.abs(tt - tRel) >= KEY_NEAR), [round1(tRel), Math.round(centre * 1000) / 1000] as [number, number]].sort((a, b) => a[0] - b[0]) } })}
                      >
                        <Plus />
                        {t.clipper.addPosition}
                      </Button>
                    </div>
                  </>
                )}
              </div>
            </Panel>
          )}
        </div>

        <aside className="min-w-0 min-[1100px]:overflow-y-auto">
          <Panel title={t.clipper.moments} aside={t.clipper.chosen(chosen.length, moments.length)} flush>
            {moments.length === 0 && <p className="p-4 text-[13px] text-muted-foreground">{t.clipper.noMoments}</p>}
            <ul>
              {moments.map((m, i) => (
                <MomentCard
                  key={m.id}
                  m={m}
                  i={i}
                  lo={lo}
                  active={i === sel}
                  bad={!valid(m)}
                  onSelect={() => {
                    setSel(i);
                    seek(m.start);
                  }}
                  onPatch={(p) => patch(m.id, p)}
                  onPreview={() => {
                    setSel(i);
                    seek(m.start);
                    play(m.end);
                  }}
                  onRemove={() => {
                    setMoments((all) => all.filter((x) => x.id !== m.id));
                    setSel(0);
                  }}
                />
              ))}
            </ul>
          </Panel>
          {job.language && (
            <p className="px-4 py-3 font-mono text-xs text-muted-foreground">
              {t.clipper.language(job.language)}
              {job.speech === false ? ` · ${t.clipper.noSpeech}` : ""}
            </p>
          )}
        </aside>
      </div>
      <footer className="flex shrink-0 flex-wrap items-center gap-4 border-t bg-ground px-6 py-3">
        <div className="min-w-0 flex-1">
          {make.error ? (
            <p role="alert" className="max-h-16 overflow-y-auto font-mono text-xs break-words text-coral">
              {make.error.message}
            </p>
          ) : (
            <p className="truncate font-mono text-xs text-muted-foreground">
              {ready || chosen.length === 0 ? t.clipper.summary(chosen.length, Math.round(chosen.reduce((s, m) => s + (m.end - m.start), 0))) : t.clipper.lengthBad(lo, MAX_LEN)}
            </p>
          )}
        </div>
        <ChannelChoice choice={choice} className="h-10 w-[220px]" />
        <Button size="lg" onClick={() => make.mutate()} disabled={!ready || make.isPending}>
          {make.isPending ? <Loader2 className="animate-spin" /> : <Film />}
          {t.clipper.make(chosen.length)}
        </Button>
      </footer>
    </>
  );
}

/** One moment: include box, from / to, length, hook, captions, preview and remove. */
function MomentCard({
  m,
  i,
  lo,
  active,
  bad,
  onSelect,
  onPatch,
  onPreview,
  onRemove,
}: {
  m: Moment;
  i: number;
  lo: number;
  active: boolean;
  bad: boolean;
  onSelect: () => void;
  onPatch: (p: Partial<Moment>) => void;
  onPreview: () => void;
  onRemove: () => void;
}) {
  const [from, setFrom] = useState(clock(m.start));
  const [to, setTo] = useState(clock(m.end));
  useEffect(() => {
    setFrom(clock(m.start));
    setTo(clock(m.end));
  }, [m.start, m.end]);
  const commit = (text: string, edge: "start" | "end") => {
    if (text === clock(edge === "start" ? m.start : m.end)) return; // untouched: keep the exact time (the box shows whole seconds)
    const v = parseClock(text);
    if (v == null || Number.isNaN(v)) return onPatch({});
    onPatch(edge === "start" ? { start: v } : { end: v });
  };
  const len = m.end - m.start;
  return (
    <li className={cn("grid gap-3 border-b p-4", active && "bg-strip")} onClick={onSelect}>
      <div className="flex items-center gap-3">
        <Switch checked={m.on} onCheckedChange={(on) => onPatch({ on })} aria-label={t.clipper.include} onClick={(e) => e.stopPropagation()} />
        <span className={cn("flex size-6 items-center justify-center rounded-full font-mono text-xs text-black", COLORS[i % COLORS.length])}>{i + 1}</span>
        <div className="flex min-w-0 flex-1 items-center gap-1.5 font-mono text-[13px]" onClick={(e) => e.stopPropagation()}>
          <input
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            onBlur={() => commit(from, "start")}
            className="h-8 w-16 rounded-md border border-input bg-ground px-2 text-center tabular-nums"
            aria-label={t.clipper.start}
          />
          →
          <input
            value={to}
            onChange={(e) => setTo(e.target.value)}
            onBlur={() => commit(to, "end")}
            className="h-8 w-16 rounded-md border border-input bg-ground px-2 text-center tabular-nums"
            aria-label={t.clipper.end}
          />
        </div>
        <button type="button" className="rounded p-1.5 text-muted-foreground hover:text-cyan" aria-label={t.clipper.preview} onClick={(e) => (e.stopPropagation(), onPreview())}>
          <Play className="size-4" />
        </button>
        <button type="button" className="rounded p-1.5 text-muted-foreground hover:text-coral" aria-label={t.clipper.remove} onClick={(e) => (e.stopPropagation(), onRemove())}>
          <Trash2 className="size-4" />
        </button>
      </div>
      <p className="flex flex-wrap items-center gap-x-3 text-xs leading-[18px] text-muted-foreground">
        <span className={cn("font-mono whitespace-nowrap tabular-nums", bad && "text-coral")} title={bad ? t.clipper.lengthBad(lo, MAX_LEN) : undefined}>
          {Math.round(len)} s
        </span>
        {m.score != null && <span className="font-mono">{m.score}/10</span>}
        {m.why && <span className="min-w-0">{m.why}</span>}
      </p>
      <div className="grid gap-2" onClick={(e) => e.stopPropagation()}>
        <Input value={m.hook} onChange={(e) => onPatch({ hook: e.target.value.slice(0, 80) })} placeholder={t.clipper.hookPlaceholder} aria-label={t.clipper.hook} />
        <Choice
          value={m.captions ?? "fr"}
          onChange={(v) => onPatch({ captions: v as ClipCaptions })}
          options={[
            ["fr", t.clipper.captionOptions.fr],
            ["source", t.clipper.captionOptions.source],
            ["off", t.clipper.captionOptions.off],
          ]}
          label={t.clipper.captions}
        />
      </div>
    </li>
  );
}

/** Clip Studio: Claude's suggested moments of a long video, for you to move, cut, crop, rename and send to production. `?link=…&count=…&short=1`. */
export default function ClipStudioPage() {
  const api = useApi()!;
  const [params] = useSearchParams();
  const link = params.get("link") ?? "";
  const count = Number(params.get("count") ?? 4) || 4;
  const short = params.get("short") === "1";
  const [jobId, setJobId] = useState<string | null>(null);
  const started = useRef(false);
  const start = useMutation({ mutationFn: () => api.clipperAnalyze({ link, count, short }), onSuccess: (j) => setJobId(j.id) });
  useEffect(() => {
    if (link && !started.current) {
      started.current = true;
      start.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const { data: job } = useQuery({
    queryKey: ["clipper", jobId],
    queryFn: () => api.clipperJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1500 : false),
  });
  const ready = useMemo(() => job?.status === "done" && !!job.source?.path, [job]);
  const failed = start.error?.message || (job?.status === "failed" ? job.error || t.clipper.failed : "");
  return (
    <div className="flex h-full min-h-0 flex-col">
      <TopBar>
        <Link to="/projects/new" className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:text-foreground" aria-label={t.clipper.back}>
          <ArrowLeft className="size-4" />
        </Link>
        <PageTitle>{t.clipper.title}</PageTitle>
        <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">{link.replace(/^https?:\/\/(www\.)?/, "")}</span>
      </TopBar>
      {!link ? (
        <p role="alert" className="px-8 py-6 text-sm text-destructive">
          {t.clipper.noLink}
        </p>
      ) : failed ? (
        <div className="grid gap-4 px-8 py-6">
          <p role="alert" className="font-mono text-sm break-words text-coral">
            {failed}
          </p>
          <div>
            <Button
              variant="secondary"
              onClick={() => {
                setJobId(null);
                start.mutate();
              }}
            >
              <Scissors />
              {t.clipper.retry}
            </Button>
          </div>
        </div>
      ) : ready && job ? (
        <Editor api={api} job={job} />
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
          <Loader2 className="animate-spin text-cyan" />
          <p className="text-sm">{job?.message || t.clipper.analyzing}</p>
          <div className="h-1.5 w-64 overflow-hidden rounded-full bg-hairline-strong">
            <div className="h-full bg-cyan transition-all" style={{ width: `${job?.pct ?? 2}%` }} />
          </div>
          <p className="max-w-md text-xs text-muted-foreground">{t.clipper.analyzingHint}</p>
        </div>
      )}
    </div>
  );
}
