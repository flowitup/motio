import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ClipCard } from "@/components/clip-card";
import { ConfirmAction } from "@/components/confirm-action";
import { Choice, Field } from "@/components/form";
import { FilterChip, PageTitle, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, type Watch } from "@/lib/api";
import { isCategory, listName } from "@/lib/watch-name";
import { t } from "@/i18n";

const ALL = "__all__";
/** What the "start" button follows: the categories the owner named first. */
const STARTER = ["tech", "ai", "ai_film", "lifestyle"].map((k) => `bilibili:category:${k}`);

/** "Tech", "Tag · 人工智能": what a chip and a message call the source. */
const nameOf = (w: Watch) => {
  const key = w.target.match(/^bilibili:category:(.+)$/)?.[1];
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
  const followed = (watches.data ?? []).filter((w) => w.kind === "trending" && isCategory(w.target));
  const current = followed.find((w) => String(w.id) === selected);
  const clips = useQuery({
    queryKey: ["clips", "new", "trending", current?.id ?? ALL],
    queryFn: async () => {
      const rows = await api.clips("new", current?.id);
      return current ? rows : rows.filter((c) => isCategory(c.watch_target));
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
    mutationFn: (targets: string[]) => targets.reduce((p, target) => p.then(() => api.addWatch({ target, site: "bilibili" }).then(() => {})), Promise.resolve()),
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

  const have = new Set(followed.map((w) => w.target));
  const left = (categories.data ?? []).filter((c) => !have.has(c.target));
  const chosen = left.some((c) => c.target === pick) ? pick : (left[0]?.target ?? "");
  const word = tag.trim().replace(/\s+/g, " ");
  const error = follow.error ?? unfollow.error ?? check.error;
  const broken = followed.filter((w) => w.last_error);
  const none = watches.isSuccess && followed.length === 0;

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
              <FilterChip key={w.id} on={selected === String(w.id)} onClick={() => setSelected(String(w.id))} count={w.new_count}>
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
                <Button variant="outline" onClick={() => follow.mutate([chosen])} disabled={!chosen || follow.isPending}>
                  {follow.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
                  {t.trendVideos.follow}
                </Button>
              </div>
            )}
            <form
              className="flex items-end gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (word) follow.mutate([`bilibili:tag:${word}`]);
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
