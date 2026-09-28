import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Link2, Loader2, RefreshCw, Video } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { ChannelChoice, useChannelChoice } from "@/components/channel-choice";
import { ExternalA } from "@/components/external-link";
import { ScoreBadge } from "@/components/status-chip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useApi } from "@/lib/api";
import { t } from "@/i18n";

const ALL = "__all__";

export default function TrendsPage() {
  const api = useApi()!;
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [source, setSource] = useState<string>(ALL);
  const [linksFor, setLinksFor] = useState<string | null>(null); // tin đang mở ô dán link
  const [linksText, setLinksText] = useState("");
  const [linksOnly, setLinksOnly] = useState(false);
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

  const sources = useMemo(() => {
    const m = new Map<string, string>();
    for (const tr of all.data ?? []) m.set(tr.source, tr.source_name);
    return [...m.entries()];
  }, [all.data]);
  const trends = (all.data ?? []).filter((tr) => source === ALL || tr.source === source);
  const pasted = linksText
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  const toggleLinks = (id: string) => {
    setLinksFor(linksFor === id ? null : id);
    setLinksText("");
    setLinksOnly(false);
  };
  const last = state.data?.last_result;

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-6">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="mr-auto text-2xl font-semibold tracking-tight">{t.trends.title}</h1>
        <ChannelChoice choice={choice} label={t.trends.forChannel} className="w-44" />
        <Select value={source} onValueChange={(v) => setSource(v ?? ALL)}>
          <SelectTrigger className="w-48">
            <SelectValue>{(v: string) => (v === ALL ? t.trends.allSources : sources.find(([s]) => s === v)?.[1] ?? v)}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t.trends.allSources}</SelectItem>
            {sources.map(([s, name]) => (
              <SelectItem key={s} value={s}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button onClick={() => refresh.mutate()} disabled={refreshing || refresh.isPending}>
          {refreshing ? <Loader2 className="animate-spin" /> : <RefreshCw />}
          {refreshing ? t.trends.refreshing : t.trends.refresh}
        </Button>
      </header>

      <p className="text-sm text-muted-foreground">
        {t.trends.lastRefresh}: {t.age(state.data?.last_refresh)}
        {!!state.data?.refresh_every_min && (
          <>
            {" · "}
            {t.trends.autoRefresh(state.data.refresh_every_min)}
            {state.data.next_refresh && ` (${t.trends.nextRefresh} ${t.clock(state.data.next_refresh)})`}
          </>
        )}
        {last?.new !== undefined && ` · ${t.trends.newScored(last.new)}`}
        {last?.error && <span className="text-destructive"> · {t.trends.refreshError}: {last.error}</span>}
        {last?.errors && Object.keys(last.errors).length > 0 && (
          <span className="text-destructive"> · {t.trends.refreshError}: {Object.keys(last.errors).join(", ")}</span>
        )}
      </p>

      {produce.error && <p className="text-sm text-destructive">{produce.error.message}</p>}
      {all.error && <p className="text-sm text-destructive">{all.error.message}</p>}

      <div className="space-y-3">
        {all.isLoading &&
          Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-24 w-full rounded-xl" />)}
        {all.data && trends.length === 0 && <p className="py-12 text-center text-muted-foreground">{t.trends.empty}</p>}
        {trends.map((tr) => (
          <Card key={tr.id} className="gap-3 p-4">
            <div className="flex items-start gap-4">
              <ScoreBadge score={tr.score} />
              <div className="min-w-0 flex-1 space-y-1">
                <div className="font-medium leading-snug">{tr.title_fr}</div>
                <div className="text-sm text-muted-foreground">{tr.title_zh}</div>
                {tr.angle && <div className="text-sm">{tr.angle}</div>}
                <div className="flex flex-wrap items-center gap-2 pt-1 text-xs text-muted-foreground">
                  <Badge variant="outline">{tr.source_name}</Badge>
                  {tr.reason && <span>{tr.reason}</span>}
                  {tr.url && (
                    <ExternalA href={tr.url} className="inline-flex items-center gap-1">
                      <ExternalLink className="size-3" />
                    </ExternalA>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  title={t.trends.links}
                  aria-label={t.trends.links}
                  aria-expanded={linksFor === tr.id}
                  onClick={() => toggleLinks(tr.id)}
                >
                  <Link2 />
                </Button>
                <Button
                  variant={tr.status === "used" ? "outline" : "default"}
                  onClick={() => produce.mutate({ id: tr.id })}
                  disabled={produce.isPending}
                >
                  {produce.isPending && produce.variables?.id === tr.id ? <Loader2 className="animate-spin" /> : <Video />}
                  {tr.status === "used" ? t.trends.used : t.trends.produce}
                </Button>
              </div>
            </div>
            {linksFor === tr.id && (
              <div className="grid gap-2 border-t pt-3">
                <Textarea
                  autoFocus
                  value={linksText}
                  onChange={(e) => setLinksText(e.target.value)}
                  placeholder={"https://www.douyin.com/video/…\nhttps://x.com/…/status/…"}
                  className="min-h-20 font-mono text-xs"
                />
                <p className="text-xs text-muted-foreground">{t.trends.linksHint}</p>
                <div className="flex flex-wrap items-center gap-3">
                  <label className="mr-auto flex items-center gap-2 text-sm">
                    <Switch checked={linksOnly} onCheckedChange={setLinksOnly} />
                    {t.trends.linksOnly}
                  </label>
                  <Button onClick={() => produce.mutate({ id: tr.id, links: pasted })} disabled={!pasted.length || produce.isPending}>
                    <Video />
                    {t.trends.produceWithLinks}
                  </Button>
                </div>
              </div>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
