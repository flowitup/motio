import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Eye, EyeOff, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ClipCard } from "@/components/clip-card";
import { ConfirmAction } from "@/components/confirm-action";
import { Choice, Field } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { PageTitle, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useApi, type Api, type Clip, type ClipStatus, type Site, type Watch } from "@/lib/api";
import { listName } from "@/lib/watch-name";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const ALL = "__all__";
const TABS: ClipStatus[] = ["new", "used", "hidden"];
const BELOW = [40, 50, 60, 70, 80]; // "Hide below score" choices

const watchName = (w: Watch) => (w.kind === "trending" ? listName(w.target) : undefined) ?? (w.name || w.target);

/** Danh sách nguồn theo dõi + ô thêm nguồn. */
function WatchesCard({ api, watches }: { api: Api; watches: Watch[] }) {
  const qc = useQueryClient();
  const [target, setTarget] = useState("");
  const [site, setSite] = useState<Site>("youtube");
  const [list, setList] = useState("bilibili:ranking:181");
  const [removing, setRemoving] = useState<Watch | null>(null);
  const isLink = /^https?:\/\//i.test(target.trim());
  const changed = () => {
    qc.invalidateQueries({ queryKey: ["watches"] });
    qc.invalidateQueries({ queryKey: ["state"] });
    qc.invalidateQueries({ queryKey: ["clips"] });
  };
  const add = useMutation({
    mutationFn: () => api.addWatch({ target: target.trim(), site }),
    onSuccess: () => {
      setTarget("");
      changed();
    },
  });
  const addList = useMutation({ mutationFn: () => api.addWatch({ target: list, site: "bilibili" }), onSuccess: changed });
  const patch = useMutation({
    mutationFn: ({ id, ...body }: { id: number; enabled?: boolean }) => api.patchWatch(id, body),
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
          <Button type="submit" className="ml-auto" disabled={!target.trim() || add.isPending}>
            {add.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
            {t.watches.add}
          </Button>
        </div>
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
                  <Link to={`/clips/${w.id}`} className="truncate text-sm font-medium underline-offset-2 hover:underline" title={t.account.open}>
                    {watchName(w)}
                  </Link>
                  {w.new_count > 0 && <span className="text-xs text-muted-foreground">{t.watches.newCount(w.new_count)}</span>}
                </div>
                <div className="truncate text-xs text-muted-foreground" title={w.last_error ?? undefined}>
                  {w.last_checked ? `${t.clips.lastCheck}: ${t.age(w.last_checked)}` : t.watches.notChecked}
                  {w.last_error && <span className="text-destructive"> · {w.last_error}</span>}
                </div>
              </div>
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
