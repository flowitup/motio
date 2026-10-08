import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, Eye, EyeOff, FolderOpen, Languages, Loader2, Plus, RefreshCw, Trash2, Video } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { ChannelChoice, useChannelChoice } from "@/components/channel-choice";
import { ConfirmAction } from "@/components/confirm-action";
import { ExternalA } from "@/components/external-link";
import { Choice, Field } from "@/components/form";
import { ScoreBadge } from "@/components/status-chip";
import { Badge } from "@/components/ui/badge";
import { PageTitle, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useApi, type Api, type Clip, type ClipStatus, type Rights, type Site, type Watch } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const ALL = "__all__";
const TABS: ClipStatus[] = ["new", "used", "hidden"];
const RIGHTS: Rights[] = ["unknown", "owned", "licensed", "cc"];
const BELOW = [40, 50, 60, 70, 80]; // "Hide below score" choices

const watchName = (w: Watch) => (w.kind === "trending" ? t.watches.lists[w.target] : undefined) ?? (w.name || w.target);
/** The followed source a clip came from; a Bilibili list is named in the UI language, not with the engine's English text. */
const clipSource = (c: Clip) =>
  (c.watch_kind === "trending" && c.watch_target ? t.watches.lists[c.watch_target] : undefined) ?? c.watch_name;
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

/** The rights to the videos of a followed source (a dub of an "owned" source can go to Postiz without a stop). */
function RightsSelect({ value, onChange, label, className }: { value: Rights; onChange: (r: Rights) => void; label: string; className?: string }) {
  return (
    <Select value={value} onValueChange={(v) => v != null && onChange(v as Rights)}>
      <SelectTrigger className={className} aria-label={label} title={label}>
        <SelectValue>{(v: string) => t.projects.rightsOptions[v] ?? v}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        {RIGHTS.map((r) => (
          <SelectItem key={r} value={r}>
            {t.projects.rightsOptions[r]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Danh sách nguồn theo dõi + ô thêm nguồn. */
function WatchesCard({ api, watches }: { api: Api; watches: Watch[] }) {
  const qc = useQueryClient();
  const [target, setTarget] = useState("");
  const [site, setSite] = useState<Site>("youtube");
  const [list, setList] = useState("bilibili:ranking:181");
  const [rights, setRights] = useState<Rights>("unknown");
  const [removing, setRemoving] = useState<Watch | null>(null);
  const isLink = /^https?:\/\//i.test(target.trim());
  const changed = () => {
    qc.invalidateQueries({ queryKey: ["watches"] });
    qc.invalidateQueries({ queryKey: ["state"] });
    qc.invalidateQueries({ queryKey: ["clips"] });
  };
  const add = useMutation({
    mutationFn: () => api.addWatch({ target: target.trim(), site, rights }),
    onSuccess: () => {
      setTarget("");
      changed();
    },
  });
  const addList = useMutation({ mutationFn: () => api.addWatch({ target: list, site: "bilibili" }), onSuccess: changed });
  const patch = useMutation({
    mutationFn: ({ id, ...body }: { id: number; enabled?: boolean; rights?: Rights }) => api.patchWatch(id, body),
    onSuccess: changed,
  });
  const remove = useMutation({ mutationFn: (id: number) => api.deleteWatch(id), onSuccess: changed });
  // the error of the action tried last: an older failure of another form must not hide it, nor outlive a later success
  const latest = [add, addList, patch, remove].reduce((a, b) => (b.submittedAt > a.submittedAt ? b : a));
  const error = latest.error;

  return (
    <CardContent className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <form
        className="grid gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (target.trim()) add.mutate();
        }}
      >
        <Field label={t.watches.target} hint={t.watches.hint}>
          <Input value={target} onChange={(e) => setTarget(e.target.value)} placeholder={t.watches.placeholder} />
        </Field>
        <div className="flex flex-wrap items-end gap-3">
          {!isLink && (
            <Field label={t.watches.searchOn}>
              <Choice
                value={site}
                onChange={(v) => setSite(v as Site)}
                options={[["youtube", "YouTube"], ["bilibili", "Bilibili"]]}
                className="w-36"
              />
            </Field>
          )}
          <Field label={t.watches.rights}>
            <RightsSelect value={rights} onChange={setRights} label={t.watches.rights} className="w-44" />
          </Field>
          <Button type="submit" className="ml-auto" disabled={!target.trim() || add.isPending}>
            {add.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
            {t.watches.add}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">{t.watches.rightsHint}</p>
      </form>
      <div className="flex flex-wrap items-end gap-3 border-t pt-3">
        <Field label={t.watches.trending} hint={t.watches.trendingHint}>
          <Choice value={list} onChange={setList} options={Object.entries(t.watches.lists)} className="w-64" />
        </Field>
        <Button variant="outline" className="ml-auto" onClick={() => addList.mutate()} disabled={addList.isPending}>
          {addList.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
          {t.watches.trendingAdd}
        </Button>
      </div>
      {error && <p className="text-sm text-destructive">{error.message}</p>}
      {watches.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t.clips.noWatches}</p>
      ) : (
        <ul className="divide-y rounded-md border">
          {watches.map((w) => (
            <li key={w.id} className={cn("flex flex-wrap items-center gap-3 px-3 py-2", !w.enabled && "opacity-60")}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{t.clips.sites[w.site]}</Badge>
                  <Badge variant="secondary">{t.watches.kinds[w.kind]}</Badge>
                  <span className="truncate text-sm font-medium" title={w.target}>
                    {watchName(w)}
                  </span>
                  {w.new_count > 0 && <span className="text-xs text-muted-foreground">{t.watches.newCount(w.new_count)}</span>}
                </div>
                <div className="truncate text-xs text-muted-foreground" title={w.last_error ?? undefined}>
                  {w.last_checked ? `${t.clips.lastCheck}: ${t.age(w.last_checked)}` : t.watches.notChecked}
                  {w.last_error && <span className="text-destructive"> · {w.last_error}</span>}
                </div>
              </div>
              <RightsSelect
                value={w.rights}
                onChange={(r) => patch.mutate({ id: w.id, rights: r })}
                label={`${t.watches.rights}: ${watchName(w)}`}
                className="w-40"
              />
              <label className="flex items-center gap-2 text-sm" title={t.watches.enabled}>
                <Switch
                  checked={w.enabled}
                  aria-label={`${t.watches.enabled}: ${watchName(w)}`}
                  onCheckedChange={(on) => patch.mutate({ id: w.id, enabled: on })}
                />
              </label>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`${t.watches.remove}: ${watchName(w)}`}
                title={t.watches.remove}
                onClick={() => setRemoving(w)}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <ConfirmAction
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t.watches.remove}
        body={removing ? t.watches.confirmRemove(watchName(removing)) : ""}
        confirm={t.watches.remove}
        icon={<Trash2 />}
        destructive
        busy={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.id);
          setRemoving(null);
        }}
      />
    </CardContent>
  );
}

/** Một video mới: ảnh, tiêu đề Pháp + gốc, kênh, độ dài, lượt xem; làm video / ẩn. */
function ClipCard({ api, clip }: { api: Api; clip: Clip }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [duration, setDuration] = useState("80");
  const [only, setOnly] = useState((clip.rights ?? "unknown") !== "unknown");
  const choice = useChannelChoice(api);
  const produce = useMutation({
    mutationFn: () =>
      api.produceClip(clip.id, { duration: Number(duration), links_only: only, channel: choice.channel }),
    onSuccess: ({ project_id }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
      navigate(`/projects/${project_id}`);
    },
  });
  const dub = useMutation({
    mutationFn: () => api.dubClip(clip.id, choice.channel),
    onSuccess: ({ project_id }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
      navigate(`/projects/${project_id}`);
    },
  });
  const status = useMutation({
    mutationFn: (s: "new" | "hidden") => api.setClipStatus(clip.id, s),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
    },
  });
  const title = clip.title_fr || clip.title || clip.url;
  const error = produce.error ?? dub.error ?? status.error;

  return (
    <Card className="gap-3 p-4">
      <div className="flex items-start gap-4">
        <ExternalA href={clip.url} className="relative hidden shrink-0 sm:block">
          {clip.thumbnail ? (
            <img
              src={clip.thumbnail}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
              className="aspect-video w-40 rounded-md bg-muted object-cover"
            />
          ) : (
            <div className="aspect-video w-40 rounded-md bg-muted" />
          )}
          {!!clip.duration && (
            <span className="absolute right-1 bottom-1 rounded bg-black/75 px-1 text-xs text-white">{mmss(clip.duration)}</span>
          )}
        </ExternalA>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-start gap-3">
            {clip.score != null && <ScoreBadge score={clip.score} />}
            <div className="min-w-0 space-y-1">
              <div className="font-medium leading-snug">{title}</div>
              {clip.title_fr && clip.title && <div className="text-sm text-muted-foreground">{clip.title}</div>}
              {clip.reason && <div className="text-sm">{clip.reason}</div>}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 pt-1 text-xs text-muted-foreground">
            <Badge variant="outline">{t.clips.sites[clip.site]}</Badge>
            {clip.uploader && <span>{clip.uploader}</span>}
            {clip.views != null && <span>· {t.clips.views(clip.views)}</span>}
            {clip.likes != null && <span>· {t.clips.likes(clip.likes)}</span>}
            {clip.category && <span>· {clip.category}</span>}
            {clip.rank != null && <span>· {t.clips.rank(clip.rank)}</span>}
            {clip.pubdate != null && <span>· {t.clips.posted} {t.age(clip.pubdate)}</span>}
            {clipSource(clip) && clipSource(clip) !== clip.uploader && <span>· {clipSource(clip)}</span>}
            <span>· {t.age(clip.first_seen)}</span>
            <ExternalA href={clip.url} className="inline-flex items-center gap-1">
              <ExternalLink className="size-3" aria-label={t.clips.openOriginal} />
            </ExternalA>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {clip.status === "used" && clip.project_id ? (
            <Button variant="outline" onClick={() => navigate(`/projects/${clip.project_id}`)}>
              <FolderOpen />
              {t.clips.openProject}
            </Button>
          ) : (
            <>
              <Button
                variant="ghost"
                size="icon"
                title={clip.status === "hidden" ? t.clips.unhide : t.clips.hide}
                aria-label={clip.status === "hidden" ? t.clips.unhide : t.clips.hide}
                disabled={status.isPending}
                onClick={() => status.mutate(clip.status === "hidden" ? "new" : "hidden")}
              >
                {clip.status === "hidden" ? <Eye /> : <EyeOff />}
              </Button>
              <Button variant={open ? "outline" : "default"} aria-expanded={open} onClick={() => setOpen(!open)}>
                <Video />
                {t.clips.produce}
                <ChevronDown className={cn("transition-transform", open && "rotate-180")} />
              </Button>
            </>
          )}
        </div>
      </div>
      {open && (
        <div className="flex flex-wrap items-end gap-4 border-t pt-3">
          {choice.channels.length > 0 && (
            <Field label={t.channels.pick}>
              <ChannelChoice choice={choice} className="w-44" />
            </Field>
          )}
          <Field label={t.projects.duration}>
            <Choice
              value={duration}
              onChange={setDuration}
              options={["70", "80", "90"].map((d) => [d, t.projects.durations[d]])}
              className="w-36"
            />
          </Field>
          <div className="grid gap-1 pb-1">
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={only} onCheckedChange={setOnly} />
              {t.clips.only}
            </label>
            <p className="text-xs text-muted-foreground">
              {t.projects.rightsOptions[clip.rights ?? "unknown"]}
              {!only && ` · ${t.clips.onlyHint}`}
            </p>
          </div>
          <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
            <Button variant="outline" onClick={() => dub.mutate()} disabled={produce.isPending || dub.isPending} title={t.clips.dubHint}>
              {dub.isPending ? <Loader2 className="animate-spin" /> : <Languages />}
              {t.clips.dub}
            </Button>
            <Button onClick={() => produce.mutate()} disabled={produce.isPending || dub.isPending}>
              {produce.isPending ? <Loader2 className="animate-spin" /> : <Video />}
              {t.clips.create}
            </Button>
          </div>
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error.message}</p>}
    </Card>
  );
}

/** Hide (or show again) many videos at once: all of those shown, or those scored under a threshold. */
function BulkBar({ api, tab, list }: { api: Api; tab: ClipStatus; list: Clip[] }) {
  const qc = useQueryClient();
  const [below, setBelow] = useState("60");
  const target = tab === "hidden" ? "new" : "hidden";
  const low = list.filter((c) => c.score != null && c.score < Number(below));
  const run = useMutation({
    mutationFn: (ids: string[]) => Promise.all(ids.map((id) => api.setClipStatus(id, target))),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
    },
  });
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="secondary" onClick={() => run.mutate(list.map((c) => c.id))} disabled={run.isPending}>
        {run.isPending ? <Loader2 className="animate-spin" /> : tab === "hidden" ? <Eye /> : <EyeOff />}
        {tab === "hidden" ? t.clips.showAll(list.length) : t.clips.hideAll(list.length)}
      </Button>
      {tab === "new" && (
        <div className="flex items-center gap-2">
          <Select value={below} onValueChange={(v) => v != null && setBelow(v)}>
            <SelectTrigger className="w-24" aria-label={t.clips.belowLabel}>
              <SelectValue>{(v: string) => `< ${v}`}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {BELOW.map((n) => (
                <SelectItem key={n} value={String(n)}>
                  {`< ${n}`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => run.mutate(low.map((c) => c.id))} disabled={run.isPending || !low.length}>
            <EyeOff />
            {t.clips.hideBelow(Number(below), low.length)}
          </Button>
        </div>
      )}
      {run.error && <span className="text-sm text-destructive">{run.error.message}</span>}
    </div>
  );
}

export default function ClipsPage() {
  const api = useApi()!;
  const qc = useQueryClient();
  const [tab, setTab] = useState<ClipStatus>("new");
  const [watchId, setWatchId] = useState<string>(ALL);
  const [showWatches, setShowWatches] = useState<boolean | null>(null); // null = mở khi chưa có nguồn

  const watches = useQuery({ queryKey: ["watches"], queryFn: () => api.watches() });
  const state = useQuery({
    queryKey: ["state"],
    queryFn: () => api.state(),
    refetchInterval: (q) => (q.state.data?.watching ? 1_500 : 30_000),
  });
  const watching = !!state.data?.watching;
  const clips = useQuery({
    queryKey: ["clips", tab, watchId],
    queryFn: () => api.clips(tab, watchId === ALL ? undefined : Number(watchId)),
  });

  // Kiểm tra xong → tải lại nguồn và video.
  useEffect(() => {
    if (!watching) {
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
    }
  }, [watching, qc]);

  const check = useMutation({
    mutationFn: () => api.checkWatches(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["state"] }),
  });

  const list = watches.data ?? [];
  const open = showWatches ?? (watches.isSuccess && list.length === 0);
  const last = state.data?.last_watch_result;
  const errors = Object.keys(last?.errors ?? {}).length;

  return (
    <>
      <TopBar>
        <PageTitle>{t.clips.title}</PageTitle>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <Select value={watchId} onValueChange={(v) => setWatchId(v ?? ALL)}>
            <SelectTrigger className="w-52">
              <SelectValue>
                {(v: string) => {
                  const w = list.find((x) => String(x.id) === v);
                  return w ? watchName(w) : t.clips.allWatches;
                }}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t.clips.allWatches}</SelectItem>
              {list.map((w) => (
                <SelectItem key={w.id} value={String(w.id)}>
                  {watchName(w)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button onClick={() => check.mutate()} disabled={watching || check.isPending || list.length === 0}>
            {watching ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {watching ? t.clips.checking : t.clips.check}
          </Button>
        </div>
      </TopBar>
      <div className="mx-auto max-w-5xl space-y-5 p-6">

        <p className="text-sm text-muted-foreground">
          {t.clips.lastCheck}: {t.age(state.data?.last_watch)}
          {" · "}
          {state.data?.refresh_every_min ? (
            <>
              {t.clips.autoCheck(state.data.refresh_every_min)}
              {state.data.next_watch && ` (${t.clips.next} ${t.clock(state.data.next_watch)})`}
            </>
          ) : (
            t.clips.manualCheck
          )}
          {last?.new !== undefined && ` · ${t.clips.found(last.new)}`}
          {last?.error && <span className="text-destructive"> · {t.clips.checkError}: {last.error}</span>}
          {errors > 0 && <span className="text-destructive"> · {t.clips.checkError}: {errors}</span>}
          {last?.score_error && <span className="text-destructive"> · {t.clips.scoreError}: {last.score_error}</span>}
        </p>

        <Card className={cn(!open && "gap-0 pb-0")}>
          <CardHeader>
            <CardTitle>
              {t.watches.title} ({list.length})
            </CardTitle>
            <CardAction>
              <Button variant="ghost" size="icon" aria-expanded={open} aria-label={t.watches.title} onClick={() => setShowWatches(!open)}>
                <ChevronDown className={cn("transition-transform", open && "rotate-180")} />
              </Button>
            </CardAction>
          </CardHeader>
          {open && <WatchesCard api={api} watches={list} />}
        </Card>

        <div className="flex gap-1 border-b">
          {TABS.map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={tab === s}
              onClick={() => setTab(s)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
                tab === s ? "border-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {t.clips.tabs[s]}
            </button>
          ))}
        </div>

        {clips.error && <p className="text-sm text-destructive">{clips.error.message}</p>}
        {tab !== "used" && !!clips.data?.length && <BulkBar key={tab} api={api} tab={tab} list={clips.data} />}
        <div className="space-y-3">
          {clips.isLoading && Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28 w-full rounded-xl" />)}
          {clips.data?.length === 0 && <p className="py-12 text-center text-muted-foreground">{t.clips.empty[tab]}</p>}
          {clips.data?.map((c) => <ClipCard key={c.id} api={api} clip={c} />)}
        </div>
      </div>
    </>
  );
}
