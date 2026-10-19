import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ClipCard } from "@/components/clip-card";
import { ConfirmAction } from "@/components/confirm-action";
import { Choice, Field } from "@/components/form";
import { FilterChip, hueFor, PageTitle, SITE_HUE, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, type Site, type Watch } from "@/lib/api";
import { isCategory, listName } from "@/lib/watch-name";
import { t } from "@/i18n";

const ALL = "__all__";
/** What the "start" button follows: the categories the owner named first. */
const STARTER = ["tech", "ai", "ai_film", "lifestyle"].map((k) => ({ target: `bilibili:category:${k}`, site: "bilibili" as Site }));
/** The sources the owner can switch on or off, and what switching one on follows when nothing of it is followed yet. */
const SOURCES = ["bilibili", "kuaishou", "douyin", "weibo", "acfun", "pearvideo"] as const;
/** Followed lists that are not a Bilibili category: target → key of the name in `t.trendVideos.categories`. */
const FEED_KEYS: Record<string, string> = { "kuaishou:featured": "kuaishou_featured", "douyin:feed": "douyin_feed", "weibo:hot": "weibo_hot" };
const STARTERS: Record<(typeof SOURCES)[number], { target: string; site: Site }[]> = {
  bilibili: STARTER,
  kuaishou: [{ target: "kuaishou:featured", site: "kuaishou" }],
  douyin: [{ target: "douyin:feed", site: "douyin" }],
  weibo: [{ target: "weibo:hot", site: "weibo" }],
  acfun: [{ target: "acfun:rank", site: "acfun" }],
  pearvideo: [{ target: "pearvideo:home", site: "pearvideo" }],
};

/** "Tech", "Tag · 人工智能": what a chip and a message call the source. */
const nameOf = (w: Watch) => {
  const key = FEED_KEYS[w.target] ?? (/^(acfun|pearvideo):/.test(w.target) ? w.target.replace(/:/g, "_") : w.target.match(/^bilibili:category:(.+)$/)?.[1]);
  return (key && t.trendVideos.categories[key]) || listName(w.target) || w.name || w.target;
};

/** Trending: the videos trending on Bilibili in the categories (or tags) you follow, ready to become a French video. */
export default function TrendVideosPage() {
  const api = useApi()!;
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string>(ALL);
  const [pick, setPick] = useState("");
  const [tag, setTag] = useState("");
  const [removing, setRemoving] = useState<Watch | null>(null);

  const watches = useQuery({ queryKey: ["watches"], queryFn: () => api.watches() });
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api.categories() });
  const state = useQuery({
    queryKey: ["state"],
    queryFn: () => api.state(),
    refetchInterval: (q) => (q.state.data?.watching ? 1_500 : 30_000),
  });
  const watching = !!state.data?.watching;
  const following = (watches.data ?? []).filter((w) => w.kind === "trending" && isCategory(w.target));
  const followed = following.filter((w) => w.enabled); // a paused source keeps its list but is not checked or shown
  const current = followed.find((w) => String(w.id) === selected);
  const activeIds = new Set(followed.map((w) => w.id));
  const clips = useQuery({
    queryKey: ["clips", "new", "trending", current?.id ?? ALL, [...activeIds].sort().join(",")],
    queryFn: async () => {
      const rows = await api.clips("new", current?.id);
      return current ? rows : rows.filter((c) => isCategory(c.watch_target) && c.watch_id != null && activeIds.has(c.watch_id));
    },
  });

  // Check finished → reload the sources and the videos.
  useEffect(() => {
    if (!watching) {
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
    }
  }, [watching, qc]);

  const changed = () => {
    qc.invalidateQueries({ queryKey: ["watches"] });
    qc.invalidateQueries({ queryKey: ["state"] });
    qc.invalidateQueries({ queryKey: ["clips"] });
  };
  const follow = useMutation({
    mutationFn: (targets: { target: string; site: Site }[]) => targets.reduce((p, body) => p.then(() => api.addWatch(body).then(() => {})), Promise.resolve()),
    onSuccess: () => {
      setPick("");
      setTag("");
      changed();
    },
  });
  const unfollow = useMutation({
    mutationFn: (id: number) => api.deleteWatch(id),
    onSuccess: () => {
      setSelected(ALL);
      changed();
    },
  });
  const check = useMutation({ mutationFn: () => api.checkWatches(), onSuccess: () => qc.invalidateQueries({ queryKey: ["state"] }) });

  const have = new Set(following.map((w) => w.target));
  const left = (categories.data ?? []).filter((c) => !have.has(c.target));
  const chosen = left.some((c) => c.target === pick) ? pick : (left[0]?.target ?? "");
  const word = tag.trim().replace(/\s+/g, " ");
  const broken = followed.filter((w) => w.last_error);
  const none = watches.isSuccess && following.length === 0;
  const platformOn = (site: keyof typeof STARTERS) => following.some((w) => w.site === site && w.enabled);
  const toggleSource = useMutation({
    mutationFn: async (site: keyof typeof STARTERS) => {
      const mine = following.filter((w) => w.site === site);
      if (platformOn(site)) {
        await Promise.all(mine.map((w) => api.patchWatch(w.id, { enabled: false })));
      } else if (mine.length > 0) {
        await Promise.all(mine.map((w) => api.patchWatch(w.id, { enabled: true })));
      } else {
        for (const body of STARTERS[site]) await api.addWatch(body);
      }
    },
    onSuccess: () => {
      setSelected(ALL);
      changed();
    },
  });
  const error = follow.error ?? unfollow.error ?? check.error ?? toggleSource.error;

  return (
    <>
      <TopBar>
        <PageTitle>{t.trendVideos.title}</PageTitle>
        <div className="ml-auto flex items-center gap-3">
          <Button onClick={() => check.mutate()} disabled={watching || check.isPending || followed.length === 0}>
            {watching ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {watching ? t.trendVideos.checking : t.trendVideos.check}
          </Button>
        </div>
      </TopBar>
      <div className="mx-auto max-w-5xl space-y-5 p-6">
        <p className="text-sm text-muted-foreground">{t.trendVideos.intro}</p>

        <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t.trendVideos.sources}>
          <span className="text-sm font-medium">{t.trendVideos.sources}</span>
          {SOURCES.map((site) => (
            <FilterChip key={site} hue={SITE_HUE[site]} on={platformOn(site)} onClick={() => toggleSource.mutate(site)} count={followed.filter((w) => w.site === site).reduce((n, w) => n + w.new_count, 0)}>
              {t.clips.sites[site]}
            </FilterChip>
          ))}
          <span className="text-xs text-muted-foreground">{t.trendVideos.sourcesHint}</span>
        </div>

        {none && (
          <Card>
            <CardContent className="grid gap-3">
              <h2 className="font-medium">{t.trendVideos.starterTitle}</h2>
              <p className="text-sm text-muted-foreground">{t.trendVideos.starterBody}</p>
              <div>
                <Button onClick={() => follow.mutate(STARTER)} disabled={follow.isPending}>
                  {follow.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
                  {t.trendVideos.starter}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {!none && (
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t.trendVideos.title}>
            <FilterChip on={selected === ALL} onClick={() => setSelected(ALL)} count={followed.reduce((n, w) => n + w.new_count, 0)}>
              {t.trendVideos.all}
            </FilterChip>
            {followed.map((w) => (
              <FilterChip key={w.id} hue={hueFor(nameOf(w))} on={selected === String(w.id)} onClick={() => setSelected(String(w.id))} count={w.new_count}>
                {nameOf(w)}
              </FilterChip>
            ))}
            {current && (
              <Button variant="ghost" size="icon" title={t.trendVideos.unfollow(nameOf(current))} aria-label={t.trendVideos.unfollow(nameOf(current))} onClick={() => setRemoving(current)}>
                <Trash2 />
              </Button>
            )}
          </div>
        )}

        <div className="grid gap-2">
          <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
            {left.length > 0 && (
              <div className="flex items-end gap-3">
                <Field label={t.trendVideos.add}>
                  <Choice
                    value={chosen}
                    onChange={setPick}
                    options={left.map((c) => [c.target, t.trendVideos.categories[c.key] ?? c.name])}
                    className="w-64"
                  />
                </Field>
                <Button variant="outline" onClick={() => follow.mutate([{ target: chosen, site: left.find((c) => c.target === chosen)?.site ?? "bilibili" }])} disabled={!chosen || follow.isPending}>
                  {follow.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
                  {t.trendVideos.follow}
                </Button>
              </div>
            )}
            <form
              className="flex items-end gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (word) follow.mutate([{ target: `bilibili:tag:${word}`, site: "bilibili" }]);
              }}
            >
              <Field label={t.trendVideos.tag}>
                <Input lang="zh" value={tag} onChange={(e) => setTag(e.target.value)} placeholder={t.trendVideos.tagPlaceholder} maxLength={40} className="w-64" />
              </Field>
              <Button type="submit" variant="outline" disabled={!word || follow.isPending}>
                <Plus />
                {t.trendVideos.follow}
              </Button>
            </form>
          </div>
          <p className="text-xs text-muted-foreground">{t.trendVideos.tagHint}</p>
        </div>
        {chosen in FEED_KEYS && <p className="text-xs text-muted-foreground">{t.trendVideos.feedHint}</p>}
        {error && <p className="text-sm text-destructive">{error.message}</p>}
        {broken.map((w) => (
          <p key={w.id} className="text-sm text-destructive">
            {t.trendVideos.errorFor(nameOf(w), w.last_error!)}
          </p>
        ))}

        {!none && (
          <p className="text-sm text-muted-foreground">
            {t.trendVideos.lastCheck}: {t.age(state.data?.last_watch)}
            {" · "}
            {state.data?.refresh_every_min ? t.trendVideos.autoCheck(state.data.refresh_every_min) : t.trendVideos.manualCheck}
          </p>
        )}

        {!none && (
          <div className="space-y-3">
            {clips.isLoading && Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28 w-full rounded-xl" />)}
            {clips.error && <p className="text-sm text-destructive">{clips.error.message}</p>}
            {clips.data?.length === 0 && (
              <p className="py-12 text-center text-muted-foreground">{current ? t.trendVideos.emptyFor : t.trendVideos.empty}</p>
            )}
            {clips.data?.map((c) => <ClipCard key={c.id} api={api} clip={c} />)}
          </div>
        )}
      </div>
      <ConfirmAction
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={removing ? t.trendVideos.unfollow(nameOf(removing)) : ""}
        body={removing ? t.trendVideos.confirmUnfollow(nameOf(removing)) : ""}
        confirm={t.watches.remove}
        icon={<Trash2 />}
        destructive
        busy={unfollow.isPending}
        onConfirm={() => {
          if (removing) unfollow.mutate(removing.id);
          setRemoving(null);
        }}
      />
    </>
  );
}
