import { useQuery } from "@tanstack/react-query";
import { CircleAlert, Clock, Film, Loader2, Plus, Sparkles, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { DeleteProjectDialog } from "@/components/delete-project";
import { FilterChip, Led, LedLabel, PageTitle, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, type Api, type Project, type ProjectStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

type Filter = "all" | ProjectStatus;
const FILTERS: Filter[] = ["all", "review", "running", "queued", "failed", "done"];

/** What the poster shows while there is no picture yet: the step that is running, the gate, or where it stopped. */
function PosterPlaceholder({ p }: { p: Project }) {
  const busy = p.status === "running" || p.status === "queued";
  const icon =
    p.status === "running" ? (
      <Loader2 className="size-6 animate-spin text-cyan" />
    ) : p.status === "queued" ? (
      <Clock className="size-6 text-foreground" />
    ) : p.status === "failed" ? (
      <CircleAlert className="size-6 text-coral" />
    ) : p.status === "review" ? (
      <Sparkles className="size-6 text-amber" />
    ) : (
      <Film className="size-6 text-muted-foreground" />
    );
  const text =
    busy || p.status === "failed"
      ? p.step
      : p.status === "review"
        ? t.studio.scriptGate
        : t.studio.noVideoYet;
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4 text-center">
      {icon}
      <span className="text-[13px] leading-[18px] font-medium">{text}</span>
      {busy && <span className="font-mono text-xs text-muted-foreground tabular-nums">{p.pct}%</span>}
    </div>
  );
}

function ProjectCard({
  api,
  p,
  channelName,
  onDelete,
}: {
  api: Api;
  p: Project;
  channelName?: string;
  onDelete: () => void;
}) {
  const title = p.meta.title || p.title;
  const busy = p.status === "running" || p.status === "queued";
  const kind = [t.projects.modes[p.mode] ?? p.mode, channelName].filter(Boolean).join(" · ");
  return (
    <li className="group relative">
      <Link
        to={`/projects/${p.id}`}
        aria-label={t.studio.openProject(title)}
        className="block rounded-lg text-foreground hover:text-foreground"
      >
        <div className="rounded-lg border border-hairline-strong bg-monitor p-2">
          <div className="relative aspect-[9/16] overflow-hidden rounded-xs bg-monitor">
            {p.meta.thumb ? (
              <img src={api.mediaUrl(p.meta.thumb, p.updated_at)} alt="" className="size-full object-cover" loading="lazy" />
            ) : (
              <PosterPlaceholder p={p} />
            )}
            <span className="absolute top-2 left-2 inline-flex h-6 items-center rounded-lg border border-hairline-strong bg-monitor px-2">
              <LedLabel status={p.status}>{t.projects.status[p.status] ?? p.status}</LedLabel>
            </span>
            {busy && (
              <div className="absolute inset-x-0 bottom-0 h-[3px] bg-white/12">
                <div className="h-full bg-cyan" style={{ width: `${p.pct}%` }} />
              </div>
            )}
          </div>
        </div>
        <div className="space-y-1 pt-3">
          <div className="line-clamp-2 min-h-9 text-[13px] leading-[18px] font-semibold">{title}</div>
          {busy && <div className="truncate text-xs leading-4 text-cyan">{p.step}</div>}
          <div className="truncate font-mono text-xs leading-4 text-muted-foreground">
            #{p.id} · {t.age(p.updated_at)}
          </div>
          <div className="truncate text-xs leading-4 text-muted-foreground">{kind}</div>
        </div>
      </Link>
      {!busy && (
        <Button
          size="icon"
          variant="secondary"
          onClick={onDelete}
          aria-label={t.projects.delete}
          title={t.projects.delete}
          className="absolute top-4 right-4 border-hairline-strong bg-monitor text-coral opacity-0 group-hover:opacity-100 hover:bg-lift focus-visible:opacity-100"
        >
          <Trash2 />
        </Button>
      )}
    </li>
  );
}

export default function ProjectsPage() {
  const api = useApi()!;
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>("all");
  const [deleting, setDeleting] = useState<Project | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.projects(),
    refetchInterval: 4_000,
  });
  const channels = useQuery({ queryKey: ["channels"], queryFn: () => api.channels(), staleTime: 30_000 });
  const channelName = useMemo(() => new Map((channels.data ?? []).map((c) => [c.id, c.name])), [channels.data]);

  const count = (f: Filter) => (data ?? []).filter((p) => f === "all" || p.status === f).length;
  const shown = (data ?? []).filter((p) => filter === "all" || p.status === filter);

  return (
    <div className="flex min-h-full flex-col">
      <TopBar>
        <PageTitle>{t.projects.title}</PageTitle>
        <Button size="lg" className="ml-auto" onClick={() => navigate("/projects/new")}>
          <Plus />
          {t.projects.create}
        </Button>
      </TopBar>
      <div className="sticky top-14 z-10 flex h-14 shrink-0 items-center gap-2 overflow-x-auto border-b bg-ground px-6">
        {FILTERS.map((f) => (
          <FilterChip
            key={f}
            on={filter === f}
            onClick={() => setFilter(f)}
            count={count(f)}
            led={f !== "all" && <Led status={f} />}
          >
            {f === "all" ? t.studio.filterAll : f === "review" ? t.studio.filterNeedsYou : t.projects.status[f]}
          </FilterChip>
        ))}
      </div>
      <div className={cn("flex-1 p-6", !shown.length && !isLoading && "flex items-center justify-center")}>
        {error && <p className="mb-4 text-[13px] text-coral">{error.message}</p>}
        {data?.length === 0 && <p className="text-muted-foreground">{t.projects.empty}</p>}
        {!!data?.length && !shown.length && <p className="text-muted-foreground">{t.studio.filterEmpty}</p>}
        <ul className="grid w-full grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-8 empty:hidden">
          {isLoading && Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="aspect-[9/16] rounded-lg" />)}
          {shown.map((p) => (
            <ProjectCard
              key={p.id}
              api={api}
              p={p}
              channelName={p.meta.channel ? channelName.get(p.meta.channel) : undefined}
              onDelete={() => setDeleting(p)}
            />
          ))}
        </ul>
      </div>
      {deleting && (
        <DeleteProjectDialog
          api={api}
          id={deleting.id}
          title={deleting.meta.title || deleting.title}
          open
          onOpenChange={(o) => !o && setDeleting(null)}
        />
      )}
    </div>
  );
}
