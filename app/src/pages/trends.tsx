import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, EyeOff, FolderOpen, Link2, Loader2, Plus, RefreshCw, Sparkles, Undo2, Video } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { AddVideoFile } from "@/components/add-video-file";
import { ChannelChoice, useChannelChoice } from "@/components/channel-choice";
import { ConfirmAction } from "@/components/confirm-action";
import { ExternalA } from "@/components/external-link";
import { BudgetNotice, SetupCard } from "@/components/setup-notices";
import { Kicker, Meter, PageTitle, ScoreBadge, Segmented, SourceBadge, TopBar, toneOf, toneText } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useApi, type Trend } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const ALL = "__all__";

/** One topic of the ledger: score, French title over the Chinese one, source, why, and its actions. */
function LedgerRow({
  tr,
  selected,
  busy,
  error,
  onSelect,
  onLinks,
  onMake,
  onOpen,
}: {
  tr: Trend;
  selected: boolean;
  busy: boolean;
  error?: string;
  onSelect: () => void;
  onLinks: () => void;
  onMake: () => void;
  onOpen: (id: number) => void;
}) {
  const made = tr.status === "used" && !!tr.project_id; // made: the button opens the project, making again asks first
  return (
    <li
      onClick={onSelect}
      className={cn(
        "group relative grid min-h-[72px] cursor-pointer grid-cols-[56px_minmax(0,1fr)_192px] items-center gap-x-4 border-b px-5 py-3 transition-colors lg:grid-cols-[56px_minmax(0,1fr)_96px_minmax(0,150px)_192px]",
        selected ? "bg-raised" : "bg-panel hover:bg-strip",
      )}
    >
      {selected && <span className="absolute inset-y-0 left-0 w-0.5 bg-amber" />}
      <ScoreBadge score={tr.score} gap={selected ? "bg-raised" : "bg-panel"} />
      <div className="min-w-0 space-y-0.5">
        <button
          type="button"
          onClick={onSelect}
          aria-current={selected || undefined}
          className="block max-w-full truncate text-left text-sm leading-5 font-medium text-foreground"
        >
          {tr.title_fr}
        </button>
        <div lang="zh" className="truncate text-xs leading-[18px] text-muted-foreground">
          {tr.title_zh}
        </div>
        {tr.angle && (
          <div className="flex items-center gap-1.5 truncate text-xs leading-[18px] text-muted-foreground">
            <Sparkles className="size-3 shrink-0 text-cyan" aria-hidden />
            <span className="truncate">{tr.angle}</span>
          </div>
        )}
      </div>
      <div className="hidden lg:block">
        <SourceBadge>{tr.source_name}</SourceBadge>
      </div>
      <div className="hidden truncate text-xs leading-[18px] text-muted-foreground lg:block">{tr.reason}</div>
      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
        <Button
          variant="ghost"
          size="icon"
          className={cn("text-muted-foreground", selected && "bg-lift text-amber hover:bg-lift")}
          title={t.trends.links}
          aria-label={t.trends.links}
          aria-pressed={selected}
          onClick={onLinks}
        >
          <Link2 className="size-[18px]" />
        </Button>
        {tr.url ? (
          <ExternalA
            href={tr.url}
            className="inline-flex size-10 items-center justify-center rounded-lg text-muted-foreground hover:bg-lift hover:text-foreground hover:no-underline"
          >
            <ExternalLink className="size-[18px]" aria-label={t.studio.openStory} />
          </ExternalA>
        ) : (
          <span className="size-10" />
        )}
        <Button
          variant={made ? "outline" : "secondary"}
          className={cn("w-[104px]", made && "gap-1.5 bg-transparent px-2")}
          onClick={() => (made ? onOpen(tr.project_id!) : onMake())}
          disabled={busy}
        >
          {busy ? <Loader2 className="animate-spin" /> : made ? <FolderOpen className="size-3.5" /> : null}
          {made ? t.trends.open : t.trends.produce}
        </Button>
      </div>
      {error && (
        <p role="alert" className="col-span-full pt-2 text-xs leading-[18px] text-coral">
          {error}
        </p>
      )}
    </li>
  );
}

export default function TrendsPage() {
  const api = useApi()!;
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [source, setSource] = useState<string>(ALL);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [linksText, setLinksText] = useState("");
  const [linksOnly, setLinksOnly] = useState(false);
  const linksRef = useRef<HTMLTextAreaElement>(null);
  const [again, setAgain] = useState<Trend | null>(null); // a topic already made, waiting for "make it again?"
  const [hidden, setHidden] = useState<Trend | null>(null); // the topic just hidden, kept for Undo
  const choice = useChannelChoice(api);

  const all = useQuery({ queryKey: ["trends"], queryFn: () => api.trends() });
  const state = useQuery({
    queryKey: ["state"],
    queryFn: () => api.state(),
    refetchInterval: (q) => (q.state.data?.refreshing ? 1_500 : 30_000),
  });
  const refreshing = !!state.data?.refreshing;

  // Cập nhật xong → tải lại danh sách tin.
  useEffect(() => {
    if (!refreshing) qc.invalidateQueries({ queryKey: ["trends"] });
  }, [refreshing, qc]);

  const refresh = useMutation({
    mutationFn: () => api.refresh(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["state"] }),
  });
  const produce = useMutation({
    mutationFn: ({ id, links }: { id: string; links?: string[] }) =>
      api.produce(id, { ...(links?.length ? { links, links_only: linksOnly } : {}), channel: choice.channel }),
    onSuccess: ({ project_id }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["trends"] });
      navigate(`/projects/${project_id}`);
    },
  });

  const hide = useMutation({
    mutationFn: ({ tr, hide }: { tr: Trend; hide: boolean }) => api.hideTrend(tr.id, hide),
    onSuccess: (_, { tr, hide }) => {
      setHidden(hide ? tr : null);
      qc.invalidateQueries({ queryKey: ["trends"] });
    },
  });
  const open = (id: number) => navigate(`/projects/${id}`);

  const sources = useMemo(() => {
    const m = new Map<string, string>();
    for (const tr of all.data ?? []) m.set(tr.source, tr.source_name);
    return [...m.entries()];
  }, [all.data]);
  const trends = (all.data ?? []).filter((tr) => source === ALL || tr.source === source);
  const selected = trends.find((tr) => tr.id === selectedId) ?? trends[0];
  const pasted = linksText
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  const select = (id: string) => {
    if (id === selected?.id) return;
    setSelectedId(id);
    setLinksText("");
    setLinksOnly(false);
  };
  const last = state.data?.last_result;

  const statusLine = (
    <p className="min-w-0 truncate font-mono text-xs leading-4 text-muted-foreground" title={undefined}>
      {t.trends.lastRefresh}: {t.age(state.data?.last_refresh)}
      {!!state.data?.refresh_every_min && (
        <>
          {" · "}
          {t.trends.autoRefresh(state.data.refresh_every_min)}
          {state.data.next_refresh && ` (${t.trends.nextRefresh} ${t.clock(state.data.next_refresh)})`}
        </>
      )}
      {last?.new !== undefined && <span className="text-amber">{` · ${t.trends.newScored(last.new)}`}</span>}
      {state.data?.last_auto && ` · ${t.trends.autoMade(state.data.last_auto.projects.length, t.clock(state.data.last_auto.at))}`}
      {last?.error && <span className="text-coral"> · {t.trends.refreshError}: {last.error}</span>}
      {last?.errors && Object.keys(last.errors).length > 0 && (
        <span className="text-coral"> · {t.trends.refreshError}: {Object.keys(last.errors).join(", ")}</span>
      )}
    </p>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <TopBar>
        <PageTitle>{t.trends.title}</PageTitle>
        <div className="ml-auto flex min-w-0 items-center gap-4">
          {statusLine}
          <Button size="lg" className="shrink-0" onClick={() => navigate("/projects/new")}>
            <Plus />
            {t.projects.create}
          </Button>
        </div>
      </TopBar>
      <SetupCard />
      <BudgetNotice />

      <div className="flex min-h-0 flex-1">
        {/* Ledger */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex min-h-14 shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b bg-ground px-5 py-1.5">
            <div className="max-w-full min-w-0 overflow-x-auto">
              <Segmented
                label={t.studio.sourceTabs}
                value={source}
                onChange={setSource}
                options={[{ value: ALL, label: t.trends.allSources }, ...sources.map(([s, name]) => ({ value: s, label: name }))]}
              />
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-3">
              <ChannelChoice choice={choice} label={t.trends.forChannel} className="w-44" />
              <Button variant="secondary" onClick={() => refresh.mutate()} disabled={refreshing || refresh.isPending}>
                {refreshing ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                {refreshing ? t.trends.refreshing : t.trends.refresh}
              </Button>
            </div>
          </div>

          {all.error && <p className="border-b px-5 py-3 text-sm text-coral">{all.error.message}</p>}
          {hidden && (
            <div role="status" className="flex shrink-0 items-center gap-3 border-b bg-strip px-5 py-1 text-[13px]">
              <span className="min-w-0 truncate">{t.trends.hiddenNote(hidden.title_fr)}</span>
              <Button variant="ghost" className="ml-auto shrink-0" onClick={() => hide.mutate({ tr: hidden, hide: false })} disabled={hide.isPending}>
                <Undo2 />
                {t.trends.undo}
              </Button>
            </div>
          )}
          <div className="grid h-10 shrink-0 grid-cols-[56px_minmax(0,1fr)_192px] gap-x-4 border-b bg-strip px-5 font-mono text-xs leading-10 font-medium tracking-[0.06em] text-muted-foreground uppercase lg:grid-cols-[56px_minmax(0,1fr)_96px_minmax(0,150px)_192px]">
            <span>{t.studio.colScore}</span>
            <span>{t.studio.colTopic}</span>
            <span className="hidden lg:block">{t.studio.colSource}</span>
            <span className="hidden lg:block">{t.studio.colWhy}</span>
            <span className="w-[192px] text-right">{t.studio.colAction}</span>
          </div>
          <ul className="min-h-0 flex-1 overflow-y-auto bg-panel">
            {all.isLoading && Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-[72px] w-full rounded-none border-b" />)}
            {all.data && trends.length === 0 && <li className="py-16 text-center text-muted-foreground">{t.trends.empty}</li>}
            {trends.map((tr) => (
              <LedgerRow
                key={tr.id}
                tr={tr}
                selected={tr.id === selected?.id}
                busy={produce.isPending && produce.variables?.id === tr.id}
                error={produce.error && produce.variables?.id === tr.id && !produce.variables.links ? produce.error.message : undefined}
                onOpen={open}
                onSelect={() => select(tr.id)}
                onLinks={() => {
                  select(tr.id);
                  setTimeout(() => linksRef.current?.focus(), 0);
                }}
                onMake={() => {
                  select(tr.id);
                  produce.mutate({ id: tr.id });
                }}
              />
            ))}
          </ul>
          <footer className="flex h-11 shrink-0 items-center justify-between gap-4 border-t bg-ground px-5 font-mono text-xs text-muted-foreground">
            <span>{t.studio.topics(trends.length)}</span>
            <span className="flex items-center gap-4">
              {(["hot", "warm", "cool"] as const).map((k) => (
                <span key={k} className="flex items-center gap-2">
                  <span className={cn("h-1 w-4 rounded-xs", k === "hot" ? "bg-amber" : k === "warm" ? "bg-cyan" : "bg-muted-foreground")} />
                  {t.studio.legend[k]}
                </span>
              ))}
            </span>
          </footer>
        </div>

        {/* Inspector */}
        <aside className="hidden w-[360px] shrink-0 flex-col border-l bg-panel md:flex">
          {selected ? (
            <>
              <div className="flex h-10 shrink-0 items-center justify-between border-b bg-strip px-4">
                <h2 className="font-mono text-xs leading-4 font-medium tracking-[0.06em] text-muted-foreground uppercase">{t.studio.selectedTopic}</h2>
                <span className="font-mono text-xs text-muted-foreground tabular-nums">
                  {t.studio.position(trends.indexOf(selected) + 1, trends.length)}
                </span>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto">
                <div className="space-y-5 p-4">
                  <div className="space-y-2.5">
                    <div className="flex items-end gap-3">
                      <span className={cn("font-mono text-[56px] leading-[56px] font-medium tracking-[-0.02em] tabular-nums", toneText(selected.score))}>
                        {selected.score}
                      </span>
                      <div className="flex flex-col pb-1">
                        <span className="font-mono text-sm leading-5 text-muted-foreground">/100</span>
                        <span className={cn("text-[13px] leading-5 font-semibold", toneText(selected.score))}>
                          {t.studio.tone[toneOf(selected.score)]}
                        </span>
                      </div>
                    </div>
                    <Meter value={selected.score} tone={toneOf(selected.score)} height={8} />
                    <div className="relative h-4 font-mono text-xs leading-4 text-muted-foreground">
                      <span className="absolute left-0">0</span>
                      <span className="absolute left-1/2 -translate-x-1/2">50</span>
                      <span className="absolute left-3/4 -translate-x-1/2">75</span>
                      <span className="absolute right-0">100</span>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <h3 className="text-lg leading-[26px] font-semibold tracking-[-0.005em]">{selected.title_fr}</h3>
                    <div lang="zh" className="text-sm leading-[22px] text-muted-foreground">
                      {selected.title_zh}
                    </div>
                  </div>
                  {selected.angle && (
                    <div className="space-y-1">
                      <Kicker className="flex items-center gap-1.5">
                        <Sparkles className="size-3 text-cyan" aria-hidden />
                        {t.studio.angle}
                      </Kicker>
                      <p className="text-[13px] leading-5">{selected.angle}</p>
                    </div>
                  )}
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
                    <SourceBadge>{selected.source_name}</SourceBadge>
                    {selected.reason && <span>{selected.reason}</span>}
                  </div>
                  {selected.url && (
                    <ExternalA href={selected.url} className="inline-flex items-center gap-2 text-[13px] font-medium">
                      <ExternalLink className="size-4" />
                      {t.studio.openStory}
                    </ExternalA>
                  )}
                  <section className="border bg-panel">
                    <header className="flex h-10 items-center gap-2 border-b bg-strip px-4">
                      <Link2 className="size-3.5 text-muted-foreground" aria-hidden />
                      <h2 className="font-mono text-xs leading-4 font-medium tracking-[0.06em] text-muted-foreground uppercase">{t.trends.links}</h2>
                    </header>
                    <div className="grid gap-3 p-4">
                      <Textarea
                        ref={linksRef}
                        value={linksText}
                        onChange={(e) => setLinksText(e.target.value)}
                        aria-label={t.trends.links}
                        placeholder={"https://www.douyin.com/video/…\nhttps://x.com/…/status/…"}
                        className="h-24 min-h-24 resize-none font-mono text-xs leading-5"
                      />
                      <AddVideoFile
                        key={selected.id}
                        api={api}
                        onAdded={(l) => setLinksText((x) => (x.trim() ? `${x.trimEnd()}\n` : "") + l)}
                      />
                      <p className="text-xs leading-[18px] text-muted-foreground">{t.trends.linksHint}</p>
                      <label className="flex min-h-10 items-center justify-between gap-3 text-[13px]">
                        {t.trends.linksOnly}
                        <Switch checked={linksOnly} onCheckedChange={setLinksOnly} />
                      </label>
                      <Button
                        variant="secondary"
                        onClick={() => produce.mutate({ id: selected.id, links: pasted })}
                        disabled={!pasted.length || produce.isPending}
                      >
                        <Video />
                        {t.trends.produceWithLinks}
                      </Button>
                    </div>
                  </section>
                </div>
              </div>
              <div className="shrink-0 space-y-2 border-t p-4">
                {produce.error && (!produce.variables || produce.variables.id === selected.id) && (
                  <p role="alert" className="text-xs leading-[18px] text-coral">
                    {produce.error.message}
                  </p>
                )}
                {selected.status === "used" && selected.project_id ? (
                  <>
                    <Button size="lg" className="w-full" onClick={() => open(selected.project_id!)}>
                      <FolderOpen />
                      {t.trends.open}
                    </Button>
                    <Button variant="secondary" className="w-full" onClick={() => setAgain(selected)} disabled={produce.isPending}>
                      {produce.isPending && produce.variables?.id === selected.id ? <Loader2 className="animate-spin" /> : <Video />}
                      {t.trends.makeAgain}
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      size="lg"
                      className="w-full"
                      onClick={() => produce.mutate({ id: selected.id })}
                      disabled={produce.isPending}
                    >
                      {produce.isPending && produce.variables?.id === selected.id ? <Loader2 className="animate-spin" /> : <Video />}
                      {t.trends.produce}
                    </Button>
                    <Button
                      variant="ghost"
                      className="w-full text-muted-foreground"
                      onClick={() => hide.mutate({ tr: selected, hide: true })}
                      disabled={hide.isPending || selected.status === "used"}
                    >
                      <EyeOff />
                      {t.trends.hide}
                    </Button>
                  </>
                )}
              </div>
            </>
          ) : (
            <div className="p-6 text-center text-muted-foreground">{t.trends.empty}</div>
          )}
        </aside>
      </div>
      <ConfirmAction
        open={!!again}
        onOpenChange={(o) => !o && setAgain(null)}
        title={t.trends.againTitle}
        body={again ? t.trends.againBody(again.title_fr, again.project_id ?? 0) : ""}
        confirm={t.trends.makeAgain}
        icon={<Video />}
        onConfirm={() => {
          if (again) produce.mutate({ id: again.id });
          setAgain(null);
        }}
      />
    </div>
  );
}
