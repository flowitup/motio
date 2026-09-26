import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Copy, FolderOpen, Link2, Loader2, Play, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { ExternalA } from "@/components/external-link";
import { PublishCard } from "@/components/publish-card";
import { StatusChip } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useProjectEvents } from "@/hooks/use-project-events";
import { useApi, type Api, type ProjectDetail, type RetryStep } from "@/lib/api";
import { inTauri, openFolder, useEngine } from "@/lib/engine";
import { t } from "@/i18n";

function SourcesCard({ api, p, active, onQueued }: { api: Api; p: ProjectDetail; active: boolean; onQueued: () => void }) {
  const [text, setText] = useState("");
  const links = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  const add = useMutation({
    mutationFn: () => api.addLinks(p.id, links),
    onSuccess: () => {
      setText("");
      onQueued();
    },
  });
  const pinned = new Set(p.meta.links ?? []);
  const sources = p.meta.sources ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.projects.sources}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        {sources.length > 0 && (
          <ul className="grid gap-1.5">
            {sources.map((s) => (
              <li key={s.url} className="min-w-0">
                <ExternalA href={s.url} className="break-all">
                  {s.platform} · {s.uploader || s.url}
                </ExternalA>
                {pinned.has(s.url) && <span className="text-xs text-muted-foreground"> · {t.projects.pasted}</span>}
                {s.title && <div className="truncate text-xs text-muted-foreground">{s.title}</div>}
              </li>
            ))}
          </ul>
        )}
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={"https://www.douyin.com/video/…\nhttps://x.com/…/status/…"}
          className="min-h-16 font-mono text-xs"
          aria-label={t.projects.addLinks}
        />
        <div className="flex flex-wrap items-center gap-3">
          <p className="mr-auto text-xs text-muted-foreground">{t.projects.addLinksHint}</p>
          <Button size="sm" variant="outline" onClick={() => add.mutate()} disabled={active || !links.length || add.isPending}>
            {add.isPending ? <Loader2 className="animate-spin" /> : <Link2 />}
            {t.projects.addAndRerun}
          </Button>
        </div>
        {add.error && <p className="text-destructive">{add.error.message}</p>}
      </CardContent>
    </Card>
  );
}

export default function ProjectDetailPage() {
  const api = useApi()!;
  const { info } = useEngine();
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const [copied, setCopied] = useState(false);
  const [from, setFrom] = useState<RetryStep | null>(null); // null = bước hệ thống đề xuất
  const logRef = useRef<HTMLPreElement>(null);

  const { data: p, error, refetch } = useQuery({ queryKey: ["project", id], queryFn: () => api.project(id) });
  const active = p?.status === "queued" || p?.status === "running";
  const ev = useProjectEvents(api, id, active, () => {
    refetch();
    qc.invalidateQueries({ queryKey: ["projects"] });
  });

  // Không chọn bước: chạy tiếp từ bước lỗi (giữ bản bóc lời đã xong); chọn bước: làm lại từ bước đó.
  const retry = useMutation({
    mutationFn: (start: RetryStep | null) => api.retry(id, start ?? undefined),
    onSuccess: () => {
      setFrom(null);
      refetch();
    },
  });

  const status = ev?.status ?? p?.status;
  const pct = ev?.pct ?? p?.pct ?? 0;
  const step = ev?.step ?? p?.step;
  const log = active && ev ? ev.log_tail.join("\n") : (p?.log ?? "");

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [log]);

  if (error) return <p className="p-6 text-destructive">{error.message}</p>;
  if (!p) return <p className="p-6 text-muted-foreground">{t.common.loading}</p>;

  const post = p.meta.description ? `${p.meta.title ?? p.title}\n\n${p.meta.description}` : "";
  const copy = async () => {
    await navigator.clipboard.writeText(post);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <Link to="/projects" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft className="size-4" />
        {t.projects.back}
      </Link>

      <header className="flex flex-wrap items-start gap-3">
        <div className="mr-auto min-w-0 space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{p.meta.title || p.title}</h1>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            {status && <StatusChip status={status} />}#{p.id} · {t.age(p.updated_at)}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Select value={from ?? p.retry.auto} onValueChange={(v) => v != null && setFrom(v as RetryStep)}>
            <SelectTrigger className="w-44" aria-label={t.projects.rerunFrom} disabled={active}>
              <SelectValue>{(v: string) => t.projects.steps[v] ?? v}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {p.retry.steps.map((s) => (
                <SelectItem key={s} value={s}>
                  {t.projects.steps[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant={status === "failed" ? "default" : "outline"}
            onClick={() => retry.mutate(from)}
            disabled={active || retry.isPending}
          >
            {retry.isPending ? <Loader2 className="animate-spin" /> : status === "failed" && !from ? <Play /> : <RotateCcw />}
            {status === "failed" && !from ? t.projects.resume : t.projects.rerun}
          </Button>
        </div>
        {inTauri && info.mode === "local" && (
          <Button variant="outline" onClick={() => openFolder(p.folder)}>
            <FolderOpen />
            {t.projects.openFolder}
          </Button>
        )}
      </header>
      {retry.error && <p className="text-sm text-destructive">{retry.error.message}</p>}

      {active && (
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span>{step}</span>
            <span className="text-muted-foreground">{pct}%</span>
          </div>
          <Progress value={pct} />
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,360px)_1fr]">
        <div className="overflow-hidden rounded-xl bg-black">
          {p.meta.video && status === "done" ? (
            <video
              key={p.updated_at}
              src={api.mediaUrl(p.meta.video, p.updated_at)}
              poster={p.meta.thumb ? api.mediaUrl(p.meta.thumb, p.updated_at) : undefined}
              controls
              className="aspect-[9/16] w-full"
            />
          ) : (
            <div className="flex aspect-[9/16] items-center justify-center text-sm text-white/60">
              {active ? <Loader2 className="size-8 animate-spin" /> : t.projects.noVideo}
            </div>
          )}
        </div>

        <div className="min-w-0 space-y-5">
          {post && (
            <Card>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle>{t.projects.post}</CardTitle>
                <Button size="sm" variant="outline" onClick={copy}>
                  {copied ? <Check /> : <Copy />}
                  {copied ? t.projects.copied : t.projects.copy}
                </Button>
              </CardHeader>
              <CardContent>
                <Textarea readOnly value={post} className="min-h-40 text-sm" />
              </CardContent>
            </Card>
          )}

          {status === "done" && p.meta.video && (
            <PublishCard api={api} projectId={p.id} history={p.meta.postiz ?? []} onSent={() => refetch()} />
          )}

          <Card>
            <CardHeader>
              <CardTitle>{t.projects.log}</CardTitle>
            </CardHeader>
            <CardContent>
              <pre
                ref={logRef}
                className="max-h-80 overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap"
              >
                {log}
              </pre>
            </CardContent>
          </Card>

          <SourcesCard api={api} p={p} active={active} onQueued={() => refetch()} />

          {p.trend && (
            <Card>
              <CardHeader>
                <CardTitle>{t.projects.source}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                <div>{p.trend.title_zh}</div>
                <div className="text-muted-foreground">{p.trend.angle}</div>
                {p.trend.url && (
                  <ExternalA href={p.trend.url} className="text-xs break-all">
                    {p.trend.url}
                  </ExternalA>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
