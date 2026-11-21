import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleAlert, Clock, Film, Loader2, RotateCcw, Sparkles } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router";
import { HUE_TEXT, type Hue } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { type Api, type Project, type ProjectCounts, type ProjectStatus } from "@/lib/api";
import { BUSY_MS, IDLE_MS } from "@/lib/poll";
import { cn } from "@/lib/utils";
import { t, useLang } from "@/i18n";

/** Where a project is on the line, from the first wait to the finished video. A gate splits "review" in two. */
export type Stage = "queued" | "running" | "script" | "video" | "failed" | "done";
export const STAGES: Stage[] = ["queued", "running", "script", "video", "failed", "done"];
/** The stages a project goes through in order (failed is a detour, not a step). */
export const LINE: Stage[] = ["queued", "running", "script", "video", "done"];
export const STAGE_HUE: Record<Stage, Hue | undefined> = {
  queued: undefined,
  running: "cyan",
  script: "violet",
  video: "amber",
  failed: "coral",
  done: "mint",
};
const DOT: Record<Stage, string> = {
  queued: "bg-tint/40",
  running: "bg-cyan",
  script: "bg-violet",
  video: "bg-amber",
  failed: "bg-coral",
  done: "bg-mint",
};

export function stageOf(p: Pick<Project, "status" | "meta">): Stage {
  if (p.status === "review") return p.meta.review === "video" ? "video" : "script";
  return p.status;
}

type Filters = { channel?: number; mode?: string; q?: string };
const COLUMN = 30; // cards each column asks for; "See all" opens the grid with that filter

function useColumn(api: Api, status: ProjectStatus, f: Filters, working: boolean) {
  return useQuery({
    queryKey: ["projects", "board", status, f.channel, f.mode, f.q],
    queryFn: () => api.projectPage({ limit: COLUMN, status, channel: f.channel, mode: f.mode, q: f.q }),
    refetchInterval: working ? BUSY_MS : IDLE_MS,
  });
}

function Poster({ api, p }: { api: Api; p: Project }) {
  const icon =
    p.status === "running" ? (
      <Loader2 className="size-4 animate-spin text-cyan" />
    ) : p.status === "queued" ? (
      <Clock className="size-4 text-muted-foreground" />
    ) : p.status === "failed" ? (
      <CircleAlert className="size-4 text-coral" />
    ) : p.status === "review" ? (
      <Sparkles className="size-4 text-amber" />
    ) : (
      <Film className="size-4 text-muted-foreground" />
    );
  return (
    <div data-slot="poster" data-status={p.status} className="flex h-[71px] w-10 shrink-0 items-center justify-center overflow-hidden rounded-sm bg-monitor">
      {p.meta.thumb ? <img src={api.mediaUrl(p.meta.thumb, p.updated_at)} alt="" className="size-full object-cover" loading="lazy" /> : icon}
    </div>
  );
}

/** Where the last Postiz send went, as one short line: "Posted", "Draft", or the planned day and hour. */
function sentLine(p: Project, lang: string): string | null {
  const last = p.meta.postiz?.[p.meta.postiz.length - 1];
  if (!last) return null;
  if (last.mode === "draft") return t.board.draft;
  const d = new Date(last.date);
  if (last.mode === "now" || Number.isNaN(d.getTime()) || d.getTime() <= Date.now()) return t.board.posted;
  return t.board.planned(d.toLocaleString(lang, { weekday: "short", hour: "2-digit", minute: "2-digit" }));
}

function Card({ api, p, channelName }: { api: Api; p: Project; channelName?: string }) {
  const qc = useQueryClient();
  const lang = useLang();
  const stage = stageOf(p);
  const title = p.meta.title || p.title;
  const retry = useMutation({
    mutationFn: () => api.retry(p.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
  const kind = [t.projects.modes[p.mode] ?? p.mode, channelName].filter(Boolean).join(" · ");
  const sent = stage === "done" ? sentLine(p, lang) : null;
  return (
    <li
      className={cn(
        "board-card relative flex gap-2.5 rounded-lg border bg-panel p-2.5",
        stage === "script" || stage === "video" ? "border-amber ring-1 ring-amber" : stage === "failed" ? "border-coral/60" : "border-hairline",
      )}
    >
      <Poster api={api} p={p} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <Link to={`/projects/${p.id}`} className="line-clamp-2 text-[13px] leading-[18px] font-semibold text-foreground after:absolute after:inset-0 hover:text-foreground">
          {title}
        </Link>
        {p.status === "running" && (
          <>
            <div className="h-1 rounded-xs bg-tint/12">
              <div className="h-full rounded-xs bg-cyan transition-all" style={{ width: `${p.pct}%` }} />
            </div>
            <div className="truncate text-xs leading-4 text-cyan">{p.step}</div>
          </>
        )}
        {p.status === "failed" && p.error && <div className="line-clamp-2 text-xs leading-4 text-coral">{p.error}</div>}
        {(stage === "script" || stage === "video") && (
          <div className="text-xs leading-4 font-semibold text-amber">{p.meta.review === "shots" ? t.studio.shotsGate : t.studio.filterNeedsYou}</div>
        )}
        {sent && (
          <div className="flex items-center gap-1 text-xs leading-4 text-mint">
            <Check className="size-3" />
            {sent}
          </div>
        )}
        <div className="truncate text-xs leading-4 text-muted-foreground">{kind}</div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs leading-4 text-muted-foreground">
            #{p.id} · {t.age(p.updated_at)}
          </span>
          {p.status === "failed" && (
            <Button size="xs" variant="secondary" className="relative z-10 ml-auto" onClick={() => retry.mutate()} disabled={retry.isPending}>
              {retry.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />}
              {t.board.retry}
            </Button>
          )}
        </div>
      </div>
    </li>
  );
}

function Column({
  stage,
  rows,
  count,
  loading,
  api,
  channelName,
  onSeeAll,
}: {
  stage: Stage;
  rows: Project[];
  count: number;
  loading: boolean;
  api: Api;
  channelName: Map<number, string>;
  onSeeAll: () => void;
}) {
  const hue = STAGE_HUE[stage];
  return (
    <section aria-label={t.board.cols[stage]} className="board-col flex min-w-[176px] flex-1 basis-0 flex-col">
      <h2 className="flex h-9 shrink-0 items-center gap-2 px-1 text-[13px] font-semibold">
        <span aria-hidden className={cn("size-2 rounded-full", DOT[stage])} />
        <span className={hue ? HUE_TEXT[hue] : undefined}>{t.board.cols[stage]}</span>
        <span className="font-mono text-xs font-medium text-muted-foreground tabular-nums">{count}</span>
      </h2>
      <ul className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1 pb-2">
        {loading && <li className="h-24 animate-pulse rounded-lg bg-panel" />}
        {!loading && !rows.length && <li className="rounded-lg border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">{t.board.empty}</li>}
        {rows.map((p) => (
          <Card key={p.id} api={api} p={p} channelName={p.meta.channel ? channelName.get(p.meta.channel) : undefined} />
        ))}
        {count > rows.length && (
          <li>
            <Button variant="ghost" size="sm" className="w-full" onClick={onSeeAll}>
              {t.board.seeAll(count)}
            </Button>
          </li>
        )}
      </ul>
    </section>
  );
}

/** The week ahead from what Motio sent to Postiz: planned posts by day, and the days nothing is planned. */
function Week({ done }: { done: Project[] }) {
  const lang = useLang();
  const days = useMemo(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return Array.from({ length: 7 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  }, []);
  const byDay = useMemo(() => {
    const out = new Map<string, { id: number; title: string; at: Date; draft: boolean }[]>();
    for (const p of done)
      for (const r of p.meta.postiz ?? []) {
        const at = new Date(r.date);
        if (Number.isNaN(at.getTime())) continue;
        const key = at.toDateString();
        out.set(key, [...(out.get(key) ?? []), { id: p.id, title: p.meta.title || p.title, at, draft: r.mode === "draft" }]);
      }
    for (const list of out.values()) list.sort((a, b) => a.at.getTime() - b.at.getTime());
    return out;
  }, [done]);
  const today = new Date().toDateString();
  return (
    <section aria-label={t.board.week} className="board-week grid shrink-0 grid-cols-[120px_repeat(7,minmax(0,1fr))] border-t bg-panel">
      <div className="flex flex-col gap-1 border-r px-3 py-2.5">
        <span className="font-mono text-xs font-medium tracking-[0.08em] text-muted-foreground uppercase">{t.board.week}</span>
        <span className="text-xs leading-4 text-muted-foreground">{t.board.weekHint}</span>
      </div>
      {days.map((d) => {
        const list = byDay.get(d.toDateString()) ?? [];
        return (
          <div key={d.toISOString()} className="flex min-h-[112px] min-w-0 flex-col gap-1 border-r px-2 py-2.5 last:border-r-0">
            <span className={cn("text-xs leading-4 font-semibold", d.toDateString() === today && "text-pink")}>
              {d.toDateString() === today ? t.board.today : d.toLocaleDateString(lang, { weekday: "short" })} {d.getDate()}
            </span>
            {list.length === 0 && <span className="text-xs leading-4 text-amber">{t.board.free}</span>}
            {list.slice(0, 3).map((e, i) => (
              <Link
                key={`${e.id}-${i}`}
                to={`/projects/${e.id}`}
                title={e.title}
                className={cn(
                  "truncate rounded-sm px-1.5 py-0.5 text-xs leading-4 font-semibold",
                  e.draft ? "bg-lift text-muted-foreground hover:text-foreground" : "bg-blue text-on-hue hover:text-on-hue",
                )}
              >
                {e.draft ? t.board.draft : e.at.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" })} {e.title}
              </Link>
            ))}
            {list.length > 3 && <span className="text-xs text-muted-foreground">+{list.length - 3}</span>}
          </div>
        );
      })}
    </section>
  );
}

/** Projects as a production line: one column per stage, the cards that need you outlined in amber, the posting week below. */
export function PipelineBoard({
  api,
  filters,
  counts,
  channelName,
  onSeeAll,
}: {
  api: Api;
  filters: Filters;
  counts?: ProjectCounts;
  channelName: Map<number, string>;
  onSeeAll: (status: ProjectStatus) => void;
}) {
  const working = !!counts && counts.queued + counts.running > 0;
  const queued = useColumn(api, "queued", filters, working);
  const running = useColumn(api, "running", filters, working);
  const review = useColumn(api, "review", filters, working);
  const failed = useColumn(api, "failed", filters, working);
  const done = useColumn(api, "done", filters, working);
  const reviewRows = review.data ?? [];
  const scriptRows = reviewRows.filter((p) => stageOf(p) === "script");
  const videoRows = reviewRows.filter((p) => stageOf(p) === "video");
  const narrowed = !!(filters.channel !== undefined || filters.mode || filters.q);
  // The counts are for every project; once the list is narrowed, a column counts what it shows.
  const count = (status: ProjectStatus, rows: Project[]) => (narrowed || !counts ? rows.length : counts[status]);
  const cols: { stage: Stage; status: ProjectStatus; rows: Project[]; count: number; loading: boolean }[] = [
    { stage: "queued", status: "queued", rows: queued.data ?? [], count: count("queued", queued.data ?? []), loading: queued.isLoading },
    { stage: "running", status: "running", rows: running.data ?? [], count: count("running", running.data ?? []), loading: running.isLoading },
    // The review count covers both gates, so each gate column counts its own cards (up to a page of reviews).
    { stage: "script", status: "review", rows: scriptRows, count: scriptRows.length, loading: review.isLoading },
    { stage: "video", status: "review", rows: videoRows, count: videoRows.length, loading: review.isLoading },
    { stage: "failed", status: "failed", rows: failed.data ?? [], count: count("failed", failed.data ?? []), loading: failed.isLoading },
    { stage: "done", status: "done", rows: done.data ?? [], count: count("done", done.data ?? []), loading: done.isLoading },
  ];
  const error = [queued, running, review, failed, done].find((q) => q.error)?.error;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {error && <p className="px-6 pt-3 text-[13px] text-coral">{error.message}</p>}
      <div className="board flex min-h-0 flex-1 gap-3 overflow-x-auto px-6 pt-3">
        {cols.map((c) => (
          <Column
            key={c.stage}
            stage={c.stage}
            rows={c.rows}
            count={c.count}
            loading={c.loading}
            api={api}
            channelName={channelName}
            onSeeAll={() => onSeeAll(c.status)}
          />
        ))}
      </div>
      <Week done={done.data ?? []} />
    </div>
  );
}

/** The project page's line: the stages done, the one it is at (or where it failed), the ones still to come. */
export function StageBar({ p }: { p: Pick<Project, "status" | "meta"> }) {
  const stage = stageOf(p);
  const at = stage === "failed" ? -1 : LINE.indexOf(stage);
  return (
    <ol aria-label={t.board.stage} className="flex flex-wrap items-center gap-1">
      {LINE.map((s, i) => {
        const done = stage === "done" || (at >= 0 && i < at);
        const now = s === stage;
        return (
          <li
            key={s}
            aria-current={now ? "step" : undefined}
            className={cn(
              "inline-flex h-6 items-center gap-1 rounded-full px-2 text-xs leading-4 font-medium whitespace-nowrap",
              now && s === "done" ? "bg-mint text-on-hue" : now && s === "running" ? "bg-cyan text-on-hue" : now ? "bg-amber text-on-amber" : done ? "text-mint" : "text-muted-foreground",
            )}
          >
            {done && !now && <Check className="size-3" />}
            {t.board.cols[s]}
          </li>
        );
      })}
      {stage === "failed" && <li className="inline-flex h-6 items-center rounded-full bg-coral px-2 text-xs leading-4 font-semibold text-on-hue">{t.board.cols.failed}</li>}
    </ol>
  );
}
