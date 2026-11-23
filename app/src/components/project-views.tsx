import { CircleAlert, Clock, Film, FolderOpen, Loader2, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { StatusSticker } from "@/components/studio";
import { Button } from "@/components/ui/button";
import type { Api, Project, ProjectStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

type Props = { api: Api; rows: Project[]; channelName: Map<number, string>; onDelete: (p: Project) => void };

const kindOf = (p: Project, channelName: Map<number, string>) =>
  [t.projects.modes[p.mode] ?? p.mode, p.meta.channel ? channelName.get(p.meta.channel) : "", p.meta.postiz?.length ? t.projects.sentToPostiz : ""].filter(Boolean).join(" · ");

function StatusIcon({ status, className }: { status: ProjectStatus; className?: string }) {
  if (status === "running") return <Loader2 className={cn("animate-spin text-cyan", className)} />;
  if (status === "queued") return <Clock className={className} />;
  if (status === "failed") return <CircleAlert className={cn("text-coral", className)} />;
  if (status === "review") return <Sparkles className={cn("text-amber", className)} />;
  return <Film className={cn("text-muted-foreground", className)} />;
}

function Thumb({ api, p, className }: { api: Api; p: Project; className?: string }) {
  return (
    <div data-slot="poster" data-status={p.status} className={cn("relative flex aspect-[9/16] shrink-0 items-center justify-center overflow-hidden rounded-md bg-monitor", className)}>
      {p.meta.thumb ? <img src={api.mediaUrl(p.meta.thumb, p.updated_at)} alt="" className="size-full object-cover" loading="lazy" /> : <StatusIcon status={p.status} className="size-5" />}
    </div>
  );
}

/** Table layout: one dense row per project, to scan many at once. */
export function ProjectTable({ api, rows, channelName, onDelete }: Props) {
  return (
    <ul className="divide-y rounded-xl border bg-panel" data-slot="table-wrap">
      {rows.map((p) => {
        const title = p.meta.title || p.title;
        const busy = p.status === "running" || p.status === "queued";
        return (
          <li key={p.id} className="group relative flex items-center gap-4 px-4 py-2 hover:bg-tint/5">
            <Link to={`/projects/${p.id}`} aria-label={t.studio.openProject(title)} className="absolute inset-0" />
            <Thumb api={api} p={p} className="h-14" />
            <div className="min-w-0 flex-1">
              <div className="card-headline truncate text-[13px] leading-5 font-semibold">{title}</div>
              <div className="truncate text-xs leading-4 text-muted-foreground">{kindOf(p, channelName)}</div>
            </div>
            <div className="hidden w-56 min-w-0 md:block">
              {busy ? (
                <>
                  <div className="truncate text-xs text-cyan">{p.step}</div>
                  <div className="mt-1 h-1 overflow-hidden rounded-full bg-tint/12">
                    <div className="h-full bg-cyan" style={{ width: `${p.pct}%` }} />
                  </div>
                </>
              ) : p.status === "failed" && p.error ? (
                <div className="line-clamp-2 text-xs leading-4 text-coral">{p.error}</div>
              ) : p.status === "review" ? (
                <div className="truncate text-xs text-amber">{p.meta.review === "video" ? t.board.cols.video : p.meta.review === "shots" ? t.studio.shotsGate : t.studio.scriptGate}</div>
              ) : null}
            </div>
            <div className="w-28 shrink-0">
              <StatusSticker status={p.status}>{t.projects.status[p.status] ?? p.status}</StatusSticker>
            </div>
            <div className="w-36 shrink-0 text-right font-mono whitespace-nowrap text-xs text-muted-foreground tabular-nums">
              #{p.id} · {t.age(p.updated_at)}
            </div>
            {!busy ? (
              <Button size="icon" variant="ghost" onClick={() => onDelete(p)} aria-label={t.projects.delete} title={t.projects.delete} className="relative text-coral opacity-0 group-hover:opacity-100 focus-visible:opacity-100">
                <Trash2 />
              </Button>
            ) : (
              <span className="size-9" />
            )}
          </li>
        );
      })}
    </ul>
  );
}

const ORDER: ProjectStatus[] = ["review", "failed", "running", "queued", "done"];

/** Inbox layout: what needs you first in a list, the picked project big on the right. */
export function ProjectInbox({ api, rows, channelName, onDelete }: Props) {
  const navigate = useNavigate();
  const sorted = ORDER.flatMap((s) => rows.filter((p) => p.status === s));
  const [picked, setPicked] = useState<number | null>(null);
  const cur = sorted.find((p) => p.id === picked) ?? sorted[0];
  if (!cur) return null;
  const title = cur.meta.title || cur.title;
  const busy = cur.status === "running" || cur.status === "queued";
  return (
    <div className="grid min-h-[28rem] gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <ul className="space-y-1.5" aria-label={t.projects.title}>
        {ORDER.map((s) => {
          const group = sorted.filter((p) => p.status === s);
          if (!group.length) return null;
          return (
            <li key={s}>
              <p className="px-2 pt-3 pb-1 font-mono text-[11px] tracking-wider text-muted-foreground uppercase">
                {s === "review" ? t.studio.filterNeedsYou : t.projects.status[s]} · {group.length}
              </p>
              <ul className="space-y-1">
                {group.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => setPicked(p.id)}
                      aria-current={p.id === cur.id ? "true" : undefined}
                      className={cn("flex w-full items-center gap-3 rounded-xl border p-2 text-left transition-colors", p.id === cur.id ? "border-hairline-strong bg-tint/10" : "border-transparent hover:bg-tint/5", p.status === "review" && "border-amber/60")}
                    >
                      <Thumb api={api} p={p} className="h-12" />
                      <span className="min-w-0 flex-1">
                        <span className="card-headline line-clamp-2 block text-[13px] leading-[18px] font-semibold">{p.meta.title || p.title}</span>
                        <span className="block truncate font-mono text-xs text-muted-foreground">#{p.id} · {t.age(p.updated_at)}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
      <div data-slot="card" className="sticky top-32 grid h-fit gap-6 rounded-2xl border bg-panel p-6 sm:grid-cols-[14rem_minmax(0,1fr)]">
        <Thumb api={api} p={cur} className="w-56 rounded-xl" />
        <div className="flex min-w-0 flex-col gap-3">
          <StatusSticker status={cur.status} className="self-start">{t.projects.status[cur.status] ?? cur.status}</StatusSticker>
          <h2 className="card-headline font-heading text-xl leading-snug font-semibold">{title}</h2>
          <p className="text-sm text-muted-foreground">{kindOf(cur, channelName)}</p>
          {busy && (
            <div>
              <div className="text-sm text-cyan">{cur.step}</div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-tint/12">
                <div className="h-full bg-cyan" style={{ width: `${cur.pct}%` }} />
              </div>
            </div>
          )}
          {cur.status === "failed" && cur.error && <p className="text-sm text-coral">{cur.error}</p>}
          {cur.status === "review" && <p className="text-sm text-amber">{cur.meta.review === "video" ? t.board.cols.video : cur.meta.review === "shots" ? t.studio.shotsGate : t.studio.scriptGate}</p>}
          <p className="font-mono text-xs text-muted-foreground">#{cur.id} · {t.age(cur.updated_at)}</p>
          <div className="mt-auto flex flex-wrap gap-2 pt-4">
            <Button size="lg" onClick={() => navigate(`/projects/${cur.id}`)}>
              <FolderOpen />
              {t.clips.openProject}
            </Button>
            {!busy && (
              <Button size="lg" variant="outline" className="text-coral" onClick={() => onDelete(cur)}>
                <Trash2 />
                {t.projects.delete}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
