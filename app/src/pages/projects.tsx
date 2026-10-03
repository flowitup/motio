import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Clock, Film, Loader2, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { DeleteProjectDialog } from "@/components/delete-project";
import { Choice } from "@/components/form";
import { SetupCard } from "@/components/setup-notices";
import { FilterChip, Led, LedLabel, PageTitle, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, type Api, type Project, type ProjectStatus } from "@/lib/api";
import { BUSY_MS, IDLE_MS } from "@/lib/poll";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

type Filter = "all" | ProjectStatus;
const FILTERS: Filter[] = ["all", "review", "running", "queued", "failed", "done"];
const PAGE = 50; // projects per page; "Load more" asks for the next page
const ANY = ""; // the "all channels" / "all kinds" choice

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
        ? p.meta.review === "shots"
          ? t.studio.shotsGate
          : t.studio.scriptGate
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
  const kind = [t.projects.modes[p.mode] ?? p.mode, channelName, p.meta.postiz?.length ? t.projects.sentToPostiz : ""]
    .filter(Boolean)
    .join(" · ");
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
          {p.status === "failed" && p.error && <div className="line-clamp-2 text-xs leading-4 text-coral">{p.error}</div>}
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
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>("all");
  const [channel, setChannel] = useState(ANY);
  const [mode, setMode] = useState(ANY);
  const [text, setText] = useState("");
  const [q, setQ] = useState(""); // the search words the engine gets, a moment after typing stops
  const [deleting, setDeleting] = useState<Project | null>(null);
  useEffect(() => {
    const id = setTimeout(() => setQ(text.trim()), 300);
    return () => clearTimeout(id);
  }, [text]);

  // Counts are cheap: they tell if anything is running (then the list follows closely) and feed the filter chips.
  const counts = useQuery({
    queryKey: ["projects", "counts"],
    queryFn: () => api.projectCounts(),
    refetchInterval: (query) => (query.state.data && query.state.data.queued + query.state.data.running > 0 ? BUSY_MS : IDLE_MS),
  });
  const working = !!counts.data && counts.data.queued + counts.data.running > 0;
  const { data, isLoading, error, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ["projects", "page", filter, channel, mode, q],
    queryFn: ({ pageParam }) =>
      api.projectPage({
        limit: PAGE,
        before: pageParam,
        status: filter === "all" ? undefined : filter,
        channel: channel === ANY ? undefined : Number(channel),
        mode: mode || undefined,
        q: q || undefined,
      }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.length === PAGE ? last[last.length - 1].id : undefined),
    refetchInterval: working ? BUSY_MS : false,
  });
  // Something started, finished or was approved elsewhere: the counts changed, so the list is stale.
  const signature = counts.data ? [counts.data.queued, counts.data.running, counts.data.review, counts.data.done, counts.data.failed].join() : "";
  const lastSignature = useRef("");
  useEffect(() => {
    if (signature && lastSignature.current && signature !== lastSignature.current) qc.invalidateQueries({ queryKey: ["projects", "page"] });
    lastSignature.current = signature;
  }, [signature, qc]);
  const channels = useQuery({ queryKey: ["channels"], queryFn: () => api.channels(), staleTime: 30_000 });
  const channelName = useMemo(() => new Map((channels.data ?? []).map((c) => [c.id, c.name])), [channels.data]);

  const shown = data?.pages.flat() ?? [];
  const narrowed = channel !== ANY || mode !== ANY || q !== "";
  const total = counts.data ? counts.data.queued + counts.data.running + counts.data.review + counts.data.done + counts.data.failed : 0;
  const countOf = (f: Filter) => (f === "all" ? total : (counts.data?.[f] ?? 0));

  return (
    <div className="flex min-h-full flex-col">
      <TopBar>
        <PageTitle>{t.projects.title}</PageTitle>
        <Button size="lg" className="ml-auto" onClick={() => navigate("/projects/new")}>
          <Plus />
          {t.projects.create}
        </Button>
      </TopBar>
      <SetupCard />
      <div className="sticky top-14 z-10 flex min-h-14 shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b bg-ground px-6 py-2">
        <div className="flex items-center gap-2 overflow-x-auto">
          {FILTERS.map((f) => (
            <FilterChip key={f} on={filter === f} onClick={() => setFilter(f)} count={countOf(f)} led={f !== "all" && <Led status={f} />}>
              {f === "all" ? t.studio.filterAll : f === "review" ? t.studio.filterNeedsYou : t.projects.status[f]}
            </FilterChip>
          ))}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="relative w-52">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input value={text} onChange={(e) => setText(e.target.value)} placeholder={t.projects.searchPlaceholder} aria-label={t.projects.search} className="pl-9" />
          </div>
          {(channels.data?.length ?? 0) > 0 && (
            <Choice
              value={channel}
              onChange={setChannel}
              options={[[ANY, t.projects.allChannels], ["0", t.channels.none], ...(channels.data ?? []).map((c): [string, string] => [String(c.id), c.name])]}
              className="w-40"
            />
          )}
          <Choice
            value={mode}
            onChange={setMode}
            options={[[ANY, t.projects.allKinds], ...Object.entries(t.projects.modes)]}
            className="w-36"
          />
        </div>
      </div>
      <div className={cn("flex-1 p-6", !shown.length && !isLoading && "flex items-center justify-center")}>
        {error && <p className="mb-4 text-[13px] text-coral">{error.message}</p>}
        {data && !shown.length && !narrowed && filter === "all" && <p className="text-muted-foreground">{t.projects.empty}</p>}
        {data && !shown.length && (narrowed || filter !== "all") && <p className="text-muted-foreground">{t.studio.filterEmpty}</p>}
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
        {hasNextPage && (
          <div className="flex justify-center pt-8">
            <Button variant="secondary" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
              {isFetchingNextPage && <Loader2 className="animate-spin" />}
              {t.projects.loadMore}
            </Button>
          </div>
        )}
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
