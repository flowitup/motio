import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  CheckCheck,
  CircleCheck,
  Copy,
  Eraser,
  FolderOpen,
  Link2,
  Loader2,
  OctagonAlert,
  Play,
  RotateCcw,
  Send,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { DeleteProjectDialog } from "@/components/delete-project";
import { DubBlurCard, DubCompareCard, DubVoicesCard } from "@/components/dub-cards";
import { ExternalA } from "@/components/external-link";
import { Choice, Field } from "@/components/form";
import { PublishCard } from "@/components/publish-card";
import { ScriptCard } from "@/components/script-card";
import { StatusChip } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useProjectEvents } from "@/hooks/use-project-events";
import { useApi, type Api, type Channel, type ProjectDetail, type RetryStep, type Rights, type VideoVersion } from "@/lib/api";
import { inTauri, openFolder, useEngine } from "@/lib/engine";
import { t } from "@/i18n";

// Chạy lại từ các bước này thì Claude viết kịch bản mới, thay bản hiện tại.
const REDO_SCRIPT: RetryStep[] = ["search", "download", "transcribe", "script"];

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
  const rights = useMutation({ mutationFn: (r: Rights) => api.setRights(p.id, r), onSuccess: onQueued });
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
            {sources.map((s, i) => (
              <li key={s.url} className="flex min-w-0 items-start gap-2">
                <div className="min-w-0 flex-1">
                  <ExternalA href={s.url} className="break-all">
                    {s.platform} · {s.uploader || s.url}
                  </ExternalA>
                  {pinned.has(s.url) && <span className="text-xs text-muted-foreground"> · {t.projects.pasted}</span>}
                  {s.delogo && (
                    <span className="text-xs text-emerald-600 dark:text-emerald-400"> · {t.delogo.cleaned}</span>
                  )}
                  {s.title && <div className="truncate text-xs text-muted-foreground">{s.title}</div>}
                </div>
                <Link
                  to={`/delogo?target=p${p.id}-${i}`}
                  className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline"
                >
                  <Eraser className="size-3.5" />
                  {t.delogo.removeLogo}
                </Link>
              </li>
            ))}
          </ul>
        )}
        {p.mode !== "dub" && (
          <>
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
          </>
        )}
        <Field label={t.projects.rights} hint={t.projects.rightsHint}>
          <Choice
            value={p.meta.rights ?? "unknown"}
            onChange={(v) => rights.mutate(v as Rights)}
            options={(["unknown", "owned", "licensed", "cc"] as const).map((r) => [r, t.projects.rightsOptions[r]])}
            className="w-full sm:w-56"
          />
        </Field>
        {rights.error && <p className="text-destructive">{rights.error.message}</p>}
      </CardContent>
    </Card>
  );
}

/** Kết quả kiểm tra chất lượng của lần dựng gần nhất (qa.py): mức chung và từng mục. */
function QualityCard({ qa }: { qa: NonNullable<ProjectDetail["meta"]["qa"]> }) {
  const tone = { ok: "text-emerald-700 dark:text-emerald-400", warn: "text-amber-700 dark:text-amber-400", fail: "text-destructive" };
  const Icon = { ok: CircleCheck, warn: TriangleAlert, fail: OctagonAlert };
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>{t.qa.card}</CardTitle>
        <span className={`text-sm font-medium ${tone[qa.level]}`}>{t.qa.level[qa.level] ?? qa.level}</span>
      </CardHeader>
      <CardContent className="grid gap-1.5 text-sm">
        {qa.level === "fail" && <p className="text-muted-foreground">{t.qa.failNote}</p>}
        {qa.checks
          .filter((c) => c.level !== "ok")
          .map((c) => {
            const I = Icon[c.level];
            return (
              <div key={`${c.id}-${c.msg}`} className={`flex items-start gap-2 ${tone[c.level]}`}>
                <I className="mt-0.5 size-4 shrink-0" />
                <span>{c.msg}</span>
              </div>
            );
          })}
        {qa.checks.every((c) => c.level === "ok") && <p className="text-muted-foreground">{qa.checks.map((c) => c.msg).join(" · ")}</p>}
      </CardContent>
    </Card>
  );
}

/** Dự án dừng ở cổng duyệt của kênh: duyệt kịch bản (đọc giọng và dựng) hoặc duyệt video (gửi Postiz). */
function ReviewCard({ api, p, channel, onDone }: { api: Api; p: ProjectDetail; channel: Channel | undefined; onDone: () => void }) {
  const approve = useMutation({ mutationFn: (send: boolean) => api.approve(p.id, send), onSuccess: onDone });
  const video = p.meta.review === "video";
  const targets = channel?.postiz.length ?? 0;
  return (
    <Card className="border-amber-500/50 bg-amber-500/5">
      <CardHeader>
        <CardTitle>{video ? t.review.video : t.review.script}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        <p className="text-muted-foreground">
          {video ? t.review.videoHint : t.review.scriptHint}
          {video && targets > 0 && ` ${t.review.videoHintSend(targets)}`}
        </p>
        {video && targets > 0 && p.dub?.needs_review && <p className="text-muted-foreground">{t.dub.reviewNote}</p>}
        {video && targets > 0 && p.ai?.needs_review && (
          <p className="text-muted-foreground">
            {p.ai.provider === "fal" && p.ai.clip_provider === "heygen" ? t.ai.clipReviewNote : t.ai.reviewNote}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {video ? (
            <>
              <Button onClick={() => approve.mutate(true)} disabled={approve.isPending}>
                {approve.isPending && approve.variables ? <Loader2 className="animate-spin" /> : targets ? <Send /> : <CheckCheck />}
                {targets ? t.review.approveSend : t.review.approve}
              </Button>
              {targets > 0 && (
                <Button variant="outline" onClick={() => approve.mutate(false)} disabled={approve.isPending}>
                  {approve.isPending && !approve.variables ? <Loader2 className="animate-spin" /> : <Check />}
                  {t.review.approveNoSend}
                </Button>
              )}
            </>
          ) : (
            <Button onClick={() => approve.mutate(true)} disabled={approve.isPending}>
              {approve.isPending ? <Loader2 className="animate-spin" /> : <Play />}
              {t.review.approveScript}
            </Button>
          )}
          {approve.error && <span className="text-destructive">{approve.error.message}</span>}
        </div>
      </CardContent>
    </Card>
  );
}

export default function ProjectDetailPage() {
  const api = useApi()!;
  const { info } = useEngine();
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [copied, setCopied] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [from, setFrom] = useState<RetryStep | null>(null); // null = bước hệ thống đề xuất
  const [view, setView] = useState<VideoVersion>("vertical"); // khổ đang xem khi có bản 16:9
  const logRef = useRef<HTMLPreElement>(null);
  const dubVideo = useRef<HTMLVideoElement>(null); // video lồng tiếng: "Phát cả hai" điều khiển nó cùng video gốc

  const { data: p, error, refetch } = useQuery({ queryKey: ["project", id], queryFn: () => api.project(id) });
  const { data: channels } = useQuery({ queryKey: ["channels"], queryFn: () => api.channels(), staleTime: 30_000 });
  const channel = channels?.find((c) => c.id === p?.meta.channel);
  const active = p?.status === "queued" || p?.status === "running";
  const ev = useProjectEvents(api, id, active, () => {
    refetch();
    qc.invalidateQueries({ queryKey: ["projects"] });
    qc.invalidateQueries({ queryKey: ["script", id] });
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

  const wide = view === "wide" && !!p.meta.wide;
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
            {status && <StatusChip status={status} />}#{p.id} · {t.projects.modes[p.mode] ?? p.mode} ·{" "}
            {channel && `${t.projects.channel(channel.name)} · `}
            {p.meta.auto && `${t.projects.auto} · `}
            {t.age(p.updated_at)}
            {p.usage?.tts_chars > 0 && ` · ${t.projects.voiceCost(p.usage.tts_chars, p.usage.usd - (p.usage.clip_usd ?? 0))}`}
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
        <Button
          variant="outline"
          onClick={() => setDeleting(true)}
          disabled={active}
          title={active ? t.projects.deleteBusy : undefined}
          className="hover:text-destructive"
        >
          <Trash2 />
          {t.projects.delete}
        </Button>
      </header>
      {retry.error && <p className="text-sm text-destructive">{retry.error.message}</p>}
      {!active && p.has_script && REDO_SCRIPT.includes(from ?? p.retry.auto) && (
        <p className="flex items-center gap-1.5 text-sm text-amber-700 dark:text-amber-400">
          <TriangleAlert className="size-4 shrink-0" />
          {t.projects.redoReplacesScript}
        </p>
      )}
      <DeleteProjectDialog
        api={api}
        id={p.id}
        title={p.meta.title || p.title}
        open={deleting}
        onOpenChange={setDeleting}
        onDeleted={() => navigate("/projects")}
      />

      {status === "review" && p.status === "review" && (
        <ReviewCard
          api={api}
          p={p}
          channel={channel}
          onDone={() => {
            refetch();
            qc.invalidateQueries({ queryKey: ["projects"] });
          }}
        />
      )}
      {p.meta.send_error && (
        <p className="flex items-center gap-1.5 text-sm text-amber-700 dark:text-amber-400">
          <TriangleAlert className="size-4 shrink-0" />
          {t.review.sendError}: {p.meta.send_error}
        </p>
      )}

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
        <div className="space-y-2">
          <div className="overflow-hidden rounded-xl bg-black">
            {/* Đang hỏi xoá: bỏ trình phát để engine không còn giữ final.mp4 (Windows không xoá được file đang mở). */}
            {p.meta.video && (status === "done" || (status === "review" && p.meta.review === "video")) && !deleting ? (
              wide ? (
                <video key={`w${p.updated_at}`} src={api.mediaUrl(p.meta.wide!, p.updated_at)} controls className="aspect-video w-full" />
              ) : (
                <video
                  ref={dubVideo}
                  key={p.updated_at}
                  src={api.mediaUrl(p.meta.video, p.updated_at)}
                  poster={p.meta.thumb ? api.mediaUrl(p.meta.thumb, p.updated_at) : undefined}
                  controls
                  className="aspect-[9/16] w-full"
                />
              )
            ) : (
              <div className="flex aspect-[9/16] items-center justify-center text-sm text-white/60">
                {active ? <Loader2 className="size-8 animate-spin" /> : t.projects.noVideo}
              </div>
            )}
          </div>
          {p.meta.wide && (
            <div className="flex justify-center gap-2">
              {(["vertical", "wide"] as const).map((v) => (
                <Button key={v} size="sm" variant={view === v ? "default" : "outline"} onClick={() => setView(v)}>
                  {t.projects.versions[v]}
                </Button>
              ))}
            </div>
          )}
        </div>

        <div className="min-w-0 space-y-5">
          {p.meta.qa && p.meta.video && <QualityCard qa={p.meta.qa} />}

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
            <PublishCard api={api} projectId={p.id} history={p.meta.postiz ?? []} hasWide={!!p.meta.wide} onSent={() => refetch()} />
          )}

          {p.dub && (
            <>
              <DubCompareCard api={api} p={p} dubVideo={dubVideo} active={active} onQueued={() => refetch()} />
              <DubVoicesCard
                key={p.dub.speakers.map((s) => `${s.label}:${s.voice_id}`).join("|")}
                api={api}
                p={p}
                active={active}
                onQueued={() => refetch()}
              />
              <DubBlurCard key={`${p.dub.blur}`} api={api} p={p} active={active} onQueued={() => refetch()} />
            </>
          )}

          {p.has_script && <ScriptCard api={api} id={p.id} active={active} canRender={p.retry.steps.includes("render")} />}

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

          {p.mode !== "ai" && <SourcesCard api={api} p={p} active={active} onQueued={() => refetch()} />}

          {p.ai && (
            <Card>
              <CardHeader>
                <CardTitle>{t.ai.card}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                {p.ai.topic && <div>{p.ai.topic}</div>}
                <div className="text-muted-foreground">
                  {t.ai.provider}: {t.ai.providers[p.ai.provider] ?? p.ai.provider}
                  {p.ai.scenes != null && ` · ${t.ai.scenes(p.ai.scenes)}`}
                  {!!p.ai.clips && ` · ${t.ai.clipsMade(p.ai.clips)}${p.ai.clip_provider ? ` (${t.ai.clipProviders[p.ai.clip_provider] ?? p.ai.clip_provider})` : ""}`}
                  {!!p.ai.cost && ` · ${t.ai.cost(p.ai.cost, !!p.ai.clips)}`}
                </div>
                {p.ai.needs_review && (
                  <div className="text-amber-700 dark:text-amber-400">
                    {p.ai.provider === "fal" && p.ai.clip_provider === "heygen" ? t.ai.clipReviewNote : t.ai.reviewNote}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {p.mode === "topic" && (p.meta.topic || p.meta.subject) && (
            <Card>
              <CardHeader>
                <CardTitle>{t.projects.topic}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                {p.meta.topic && <div>{p.meta.topic}</div>}
                {p.meta.subject?.angle && <div className="text-muted-foreground">{p.meta.subject.angle}</div>}
              </CardContent>
            </Card>
          )}

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
