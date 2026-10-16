import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { useEffect } from "react";
import { Link, useParams } from "react-router";
import { ClipCard } from "@/components/clip-card";
import { ExternalA } from "@/components/external-link";
import { PageTitle, TopBar } from "@/components/studio";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, type Clip, type Watch } from "@/lib/api";
import { listName } from "@/lib/watch-name";
import { t } from "@/i18n";

const UNKNOWN = "unknown";
const watchName = (w: Watch) => (w.kind === "trending" ? listName(w.target) : undefined) ?? (w.name || w.target);

/** The local calendar day of a video (YYYY-MM-DD), or UNKNOWN when its upload date could not be read. */
const dayKey = (c: Clip) => {
  if (!c.pubdate) return UNKNOWN;
  const d = new Date(c.pubdate * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

/** "Today", "Yesterday", or the date; `sample` is any video of that day. */
function dayLabel(key: string, sample: Clip) {
  if (key === UNKNOWN) return t.account.unknownDate;
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86_400_000);
  const same = (d: Date) => dayKey({ pubdate: d.getTime() / 1000 } as Clip) === key;
  if (same(today)) return t.account.today;
  if (same(yesterday)) return t.account.yesterday;
  return t.day(sample.pubdate!);
}

/** The videos of one followed account, newest upload first, under one heading per day. */
export default function AccountPage() {
  const api = useApi()!;
  const qc = useQueryClient();
  const id = Number(useParams().id);
  const watches = useQuery({ queryKey: ["watches"], queryFn: () => api.watches() });
  const state = useQuery({
    queryKey: ["state"],
    queryFn: () => api.state(),
    refetchInterval: (q) => (q.state.data?.watching ? 1_500 : 30_000),
  });
  const videos = useQuery({ queryKey: ["clips", "account", id], queryFn: () => api.watchVideos(id) });
  const watching = !!state.data?.watching;

  // a check that ends brings the new videos
  useEffect(() => {
    if (!watching) {
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
    }
  }, [watching, qc]);

  const check = useMutation({
    mutationFn: () => api.checkWatch(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["state"] }),
  });

  const w = watches.data?.find((x) => x.id === id);
  const days: { key: string; clips: Clip[] }[] = [];
  for (const c of videos.data ?? []) {
    const key = dayKey(c);
    const last = days[days.length - 1];
    if (last?.key === key) last.clips.push(c);
    else days.push({ key, clips: [c] });
  }
  const link = w && /^https?:\/\//.test(w.target) ? w.target : undefined;

  return (
    <>
      <TopBar>
        <Link to="/clips" className="inline-flex h-10 items-center gap-2 text-[13px] font-medium">
          <ArrowLeft className="size-4" />
          {t.account.back}
        </Link>
        <span aria-hidden className="font-mono text-[13px] text-muted-foreground">
          /
        </span>
        <PageTitle>{w ? watchName(w) : "…"}</PageTitle>
        <div className="ml-auto flex items-center gap-3">
          <Button onClick={() => check.mutate()} disabled={watching || check.isPending || !w}>
            {watching ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {watching ? t.clips.checking : t.clips.check}
          </Button>
        </div>
      </TopBar>
      <div className="mx-auto max-w-5xl space-y-5 p-6">
        {w && (
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <Badge variant="outline">{t.clips.sites[w.site]}</Badge>
            <Badge variant="secondary">{t.watches.kinds[w.kind]}</Badge>
            <span>
              {t.clips.lastCheck}: {t.age(w.last_checked)}
            </span>
            {link && (
              <ExternalA href={link} className="inline-flex items-center gap-1 underline-offset-2 hover:underline">
                {t.account.openSource}
                <ExternalLink className="size-3" />
              </ExternalA>
            )}
            {w.last_error && <span className="text-destructive">· {w.last_error}</span>}
          </div>
        )}
        {videos.error && <p className="text-sm text-destructive">{videos.error.message}</p>}
        {check.error && <p className="text-sm text-destructive">{check.error.message}</p>}
        {videos.isLoading && Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28 w-full rounded-xl" />)}
        {videos.data?.length === 0 && <p className="py-12 text-center text-muted-foreground">{t.account.empty}</p>}
        {days.map(({ key, clips }) => (
          <section key={key} className="space-y-3">
            <h2 className="flex items-baseline gap-2 border-b pb-1 text-[15px] font-semibold" title={key === UNKNOWN ? t.account.unknownDateHint : undefined}>
              {dayLabel(key, clips[0])}
              <span className="text-xs font-normal text-muted-foreground">{t.account.videos(clips.length)}</span>
            </h2>
            {clips.map((c) => (
              <ClipCard key={c.id} api={api} clip={c} />
            ))}
          </section>
        ))}
      </div>
    </>
  );
}
