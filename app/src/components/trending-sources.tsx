import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";
import { useState } from "react";
import { Choice, Field } from "@/components/form";
import { FilterChip, SITE_HUE } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { type Api, type Site, type Watch } from "@/lib/api";
import { isCategory, listName } from "@/lib/watch-name";
import { t } from "@/i18n";

/** What the "start" button follows: the categories the owner named first. */
const STARTER = [
  { target: "bilibili:weekly", site: "bilibili" as Site },
  { target: "bilibili:popular", site: "bilibili" as Site },
  ...["tech", "ai", "ai_film", "lifestyle"].map((k) => ({ target: `bilibili:category:${k}`, site: "bilibili" as Site })),
];
/** The sources the owner can switch on or off, and what switching one on follows when nothing of it is followed yet. */
const SOURCES = ["bilibili", "kuaishou", "douyin", "weibo", "acfun", "pearvideo"] as const;
/** Followed lists that are not a Bilibili category: target → key of the name in `t.trendVideos.categories`. */
const FEED_KEYS: Record<string, string> = { "kuaishou:featured": "kuaishou_featured", "douyin:hot": "douyin_hot", "douyin:featured": "douyin_featured", "douyin:feed": "douyin_feed", "weibo:hot": "weibo_hot" };
const STARTERS: Record<(typeof SOURCES)[number], { target: string; site: Site }[]> = {
  bilibili: STARTER,
  kuaishou: [{ target: "kuaishou:featured", site: "kuaishou" }],
  douyin: [{ target: "douyin:hot", site: "douyin" }, { target: "douyin:featured", site: "douyin" }, { target: "douyin:feed", site: "douyin" }],
  weibo: [{ target: "weibo:hot", site: "weibo" }],
  acfun: [{ target: "acfun:rank", site: "acfun" }],
  pearvideo: [{ target: "pearvideo:home", site: "pearvideo" }],
};

/** "Tech", "Tag · 人工智能": what a chip and a message call the source. */
const nameOf = (w: Watch) => {
  const key = FEED_KEYS[w.target] ?? (/^(acfun|pearvideo):/.test(w.target) ? w.target.replace(/:/g, "_") : w.target.match(/^bilibili:category:(.+)$/)?.[1]);
  return (key && t.trendVideos.categories[key]) || listName(w.target) || w.name || w.target;
};

/** The Bilibili rankings by section, offered next to the categories (the categories are a curated few of them). */
const RANKINGS = (): [string, string][] => Object.entries(t.watches.lists).filter(([target]) => /^bilibili:ranking:\d+$/.test(target));

/**
 * What to fetch trending videos from: platform switches, a Bilibili category / ranking / tag to follow.
 * Part of the Feed's sources card: the sources it adds are ordinary followed sources, listed (and removed) below it.
 */
export function TrendingSources({ api, watches }: { api: Api; watches: Watch[] }) {
  const qc = useQueryClient();
  const [pick, setPick] = useState("");
  const [tag, setTag] = useState("");
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api.categories() });
  const following = watches.filter((w) => w.kind === "trending" && isCategory(w.target));
  const followed = following.filter((w) => w.enabled); // a paused source keeps its list but is not checked or shown

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
  const have = new Set(following.map((w) => w.target));
  const offered: [string, string, Site][] = [
    ...(categories.data ?? []).map((c): [string, string, Site] => [c.target, t.trendVideos.categories[c.key] ?? c.name, c.site]),
    ...RANKINGS().map(([target, name]): [string, string, Site] => [target, name, "bilibili"]),
  ].filter(([target], i, all) => !have.has(target) && all.findIndex((x) => x[0] === target) === i);
  const chosen = offered.some(([target]) => target === pick) ? pick : (offered[0]?.[0] ?? "");
  const word = tag.trim().replace(/\s+/g, " ");
  const broken = followed.filter((w) => w.last_error);
  const none = following.length === 0;
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
    onSuccess: changed,
  });
  const error = follow.error ?? toggleSource.error;

  return (
    <CardContent className="grid gap-4 border-b pb-4">
      <div className="grid gap-1">
        <h3 className="text-sm font-medium">{t.clips.trendingSources}</h3>
        <p className="text-xs text-muted-foreground">{t.trendVideos.intro}</p>
      </div>
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
        <div className="grid gap-2 rounded-md border p-3">
          <h4 className="font-medium">{t.trendVideos.starterTitle}</h4>
          <p className="text-sm text-muted-foreground">{t.trendVideos.starterBody}</p>
          <div>
            <Button onClick={() => follow.mutate(STARTER)} disabled={follow.isPending}>
              {follow.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
              {t.trendVideos.starter}
            </Button>
          </div>
        </div>
      )}

      <div className="grid gap-2">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          {offered.length > 0 && (
            <div className="flex items-end gap-3">
              <Field label={t.trendVideos.add}>
                <Choice value={chosen} onChange={setPick} options={offered.map(([target, name]): [string, string] => [target, name])} className="w-64" />
              </Field>
              <Button
                variant="outline"
                onClick={() => follow.mutate([{ target: chosen, site: offered.find(([target]) => target === chosen)?.[2] ?? "bilibili" }])}
                disabled={!chosen || follow.isPending}
              >
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
    </CardContent>
  );
}
