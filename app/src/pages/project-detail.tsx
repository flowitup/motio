import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  CheckCheck,
  CircleCheck,
  Copy,
  Eraser,
  ExternalLink,
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
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { AddVideoFile } from "@/components/add-video-file";
import { DeleteProjectDialog } from "@/components/delete-project";
import { DubBlurCard, DubCompareCard, DubVoicesCard } from "@/components/dub-cards";
import { ExternalA } from "@/components/external-link";
import { Choice } from "@/components/form";
import { Monitor } from "@/components/monitor";
import { PublishCard } from "@/components/publish-card";
import { ScriptCard } from "@/components/script-card";
import { StatusChip } from "@/components/status-chip";
import { Kicker, Led, PageTitle, Panel } from "@/components/studio";
import { TimelineStrip, lineAt, mmss, useNarration, type Mark } from "@/components/timeline";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useProjectEvents } from "@/hooks/use-project-events";
import { useApi, type Api, type Channel, type ProjectDetail, type RetryStep, type Rights, type VideoVersion } from "@/lib/api";
import { inTauri, openFolder, useEngine } from "@/lib/engine";
import { cn } from "@/lib/utils";
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
    <Panel title={t.projects.sources} aside={sources.length ? t.studio.sourceCount(sources.length) : undefined} flush>
      {sources.length > 0 && (
        <ul>
          {sources.map((s, i) => (
            <li key={s.url} className="flex min-w-0 items-start gap-3 border-b px-4 py-3">
              <div className="min-w-0 flex-1 space-y-0.5">
                <div className="text-[13px] leading-5 font-semibold break-all">
                  {s.url.startsWith("file:") ? (
                    <>
                      {s.platform} · {s.title || s.url}
                    </>
                  ) : (
                    <ExternalA href={s.url} className="text-foreground hover:text-cyan">
                      {s.platform} · {s.uploader || s.url}
                    </ExternalA>
                  )}
                </div>
                {s.title && !s.url.startsWith("file:") && (
                  <div lang="zh" className="truncate text-xs leading-[18px] text-muted-foreground">
                    {s.title}
                  </div>
                )}
                <div className="text-xs leading-[18px] text-muted-foreground">
                  {pinned.has(s.url) && t.projects.pasted}
                  {s.delogo && <span className="text-mint">{pinned.has(s.url) ? " · " : ""}{t.delogo.cleaned}</span>}
                </div>
              </div>
              <Link to={`/delogo?target=p${p.id}-${i}`} className="mt-0.5 inline-flex h-6 shrink-0 items-center gap-1.5 text-xs font-medium">
                <Eraser className="size-3.5" />
                {t.delogo.removeLogo}
              </Link>
            </li>
          ))}
        </ul>
      )}
      <div className="grid gap-4 p-4">
        {p.mode !== "dub" && (
          <div className="grid gap-3">
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={"https://www.douyin.com/video/…\nhttps://x.com/…/status/…"}
              className="h-20 min-h-20 resize-none font-mono text-xs leading-5"
              aria-label={t.projects.addLinks}
            />
            <AddVideoFile api={api} disabled={active} onAdded={(l) => setText((x) => (x.trim() ? `${x.trimEnd()}\n` : "") + l)} />
            <p className="text-xs leading-[18px] text-muted-foreground">{t.projects.addLinksHint}</p>
            <div>
              <Button variant="secondary" onClick={() => add.mutate()} disabled={active || !links.length || add.isPending}>
                {add.isPending ? <Loader2 className="animate-spin" /> : <Link2 />}
                {t.projects.addAndRerun}
              </Button>
            </div>
            {add.error && <p className="text-[13px] text-coral">{add.error.message}</p>}
          </div>
        )}
        <div className="grid gap-2">
          <div className="text-[13px] font-medium">{t.projects.rights}</div>
          <Choice
            value={p.meta.rights ?? "unknown"}
            onChange={(v) => rights.mutate(v as Rights)}
            options={(["unknown", "owned", "licensed", "cc"] as const).map((r) => [r, t.projects.rightsOptions[r]])}
            className="w-full"
          />
          <p className="text-xs leading-[18px] text-muted-foreground">{t.projects.rightsHint}</p>
          {rights.error && <p className="text-[13px] text-coral">{rights.error.message}</p>}
        </div>
      </div>
    </Panel>
  );
}

/** Kết quả kiểm tra chất lượng của lần dựng gần nhất (qa.py): mức chung và từng mục. */
function QualityCard({ qa, held }: { qa: NonNullable<ProjectDetail["meta"]["qa"]>; held: boolean }) {
  const tone = { ok: "text-mint", warn: "text-amber", fail: "text-coral" };
  const Icon = { ok: CircleCheck, warn: TriangleAlert, fail: OctagonAlert };
  const LevelIcon = Icon[qa.level];
  const problems = qa.checks.filter((c) => c.level !== "ok");
  const passed = qa.checks.filter((c) => c.level === "ok");
  return (
    <Panel title={t.qa.card} bodyClassName="grid gap-3">
      {qa.level !== "ok" && (
        <div className={cn("flex items-center gap-2 text-[13px] leading-5 font-semibold", tone[qa.level])}>
          <LevelIcon className="size-4 shrink-0" />
          {t.qa.level[qa.level] ?? qa.level}
        </div>
      )}
      {qa.level === "fail" && held && <p className="text-[13px] leading-5 text-muted-foreground">{t.qa.failNote}</p>}
      {problems.map((c) => (
        <p key={`${c.id}-${c.msg}`} className="text-[13px] leading-5">
          {c.msg}
        </p>
      ))}
      {passed.length > 0 && (
        <div className="flex items-start gap-2 text-xs leading-[18px] text-muted-foreground">
          <CircleCheck className="mt-0.5 size-4 shrink-0 text-mint" />
          <span>{passed.map((c) => c.msg).join(" · ")}</span>
        </div>
      )}
    </Panel>
  );
}

/** Dự án dừng ở cổng duyệt của kênh: duyệt kịch bản (đọc giọng và dựng) hoặc duyệt video (gửi Postiz). */
function ReviewCard({ api, p, channel, onDone }: { api: Api; p: ProjectDetail; channel: Channel | undefined; onDone: () => void }) {
  const approve = useMutation({ mutationFn: (send: boolean) => api.approve(p.id, send), onSuccess: onDone });
  const video = p.meta.review === "video";
  const targets = channel?.postiz.length ?? 0;
  return (
    <section className="flex flex-col border border-amber bg-panel">
      <header className="flex h-10 shrink-0 items-center gap-2.5 border-b border-amber/35 bg-amber/12 px-4">
        <Led status="review" />
        <h2 className="font-mono text-[11px] leading-4 font-medium tracking-[0.06em] text-amber uppercase">{t.studio.review}</h2>
      </header>
      <div className="grid gap-3 p-4">
        <h3 className="text-[15px] leading-[22px] font-semibold">{video ? t.review.video : t.review.script}</h3>
        <p className="text-xs leading-[18px] text-muted-foreground">
          {video ? t.review.videoHint : t.review.scriptHint}
          {video && targets > 0 && ` ${t.review.videoHintSend(targets)}`}
        </p>
        {video && targets > 0 && p.dub?.needs_review && <p className="text-xs leading-[18px] text-muted-foreground">{t.dub.reviewNote}</p>}
        {video && targets > 0 && p.ai?.needs_review && (
          <p className="text-xs leading-[18px] text-muted-foreground">
            {p.ai.provider === "fal" && p.ai.clip_provider === "heygen" ? t.ai.clipReviewNote : t.ai.reviewNote}
          </p>
        )}
        <div className="grid gap-2">
          {video ? (
            <>
              <Button size="lg" onClick={() => approve.mutate(true)} disabled={approve.isPending}>
                {approve.isPending && approve.variables ? <Loader2 className="animate-spin" /> : targets ? <Send /> : <CheckCheck />}
                {targets ? t.review.approveSend : t.review.approve}
              </Button>
              {targets > 0 && (
                <Button size="lg" variant="secondary" onClick={() => approve.mutate(false)} disabled={approve.isPending}>
                  {approve.isPending && !approve.variables ? <Loader2 className="animate-spin" /> : <Check />}
                  {t.review.approveNoSend}
                </Button>
              )}
            </>
          ) : (
            <Button size="lg" onClick={() => approve.mutate(true)} disabled={approve.isPending}>
              {approve.isPending ? <Loader2 className="animate-spin" /> : <Play />}
              {t.review.approveScript}
            </Button>
          )}
          {approve.error && <span className="text-[13px] text-coral">{approve.error.message}</span>}
        </div>
      </div>
    </section>
  );
}

/** The post as it will go out: the title in bold, the description, and the #hashtags in mono cyan. */
function PostText({ text }: { text: string }) {
  const [title, ...rest] = text.split("\n\n");
  return (
    <div className="space-y-2 text-[13px] leading-5">
      <div className="font-semibold">{title}</div>
      {rest.length > 0 && (
        <p className="whitespace-pre-wrap text-muted-foreground">
          {rest
            .join("\n\n")
            .split(/(#[\p{L}\p{N}_]+)/u)
            .map((part, i) =>
              part.startsWith("#") ? (
                <span key={i} className="font-mono text-xs text-cyan">
                  {part}
                </span>
              ) : (
                part
              ),
            )}
        </p>
      )}
    </div>
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
  const [time, setTime] = useState(0); // player position and length (seconds)
  const [length, setLength] = useState(0);
  const logRef = useRef<HTMLPreElement>(null);
  const dubVideo = useRef<HTMLVideoElement>(null); // video lồng tiếng: "Phát cả hai" điều khiển nó cùng video gốc

  const { data: p, error, refetch } = useQuery({ queryKey: ["project", id], queryFn: () => api.project(id) });
  const { data: channels } = useQuery({ queryKey: ["channels"], queryFn: () => api.channels(), staleTime: 30_000 });
  const channel = channels?.find((c) => c.id === p?.meta.channel);
  const script = useQuery({ queryKey: ["script", id], queryFn: () => api.script(id), enabled: !!p?.has_script });
  const narration = useNarration(api, id, p?.updated_at);
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

  // The voice's measured line spans count only while they are the saved script's own lines (an edit not yet re-rendered makes them stale).
  const nar = narration.data;
  const lines = script.data?.script.lines;
  const marks: Mark[] | null = useMemo(
    () => (nar && lines && nar.texts.length === lines.length && nar.texts.every((x, i) => x === lines[i].text) ? nar.lines : null),
    [nar, lines],
  );

  if (error) return <p className="p-6 text-coral">{error.message}</p>;
  if (!p) return <p className="p-6 text-muted-foreground">{t.common.loading}</p>;

  const post = p.meta.description ? `${p.meta.title ?? p.title}\n\n${p.meta.description}` : "";
  const copy = async () => {
    await navigator.clipboard.writeText(post);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const seek = (sec: number) => {
    if (dubVideo.current) dubVideo.current.currentTime = sec;
  };
  const playable = !!p.meta.video && (status === "done" || (status === "review" && p.meta.review === "video")) && !deleting;
  const refreshAll = () => {
    refetch();
    qc.invalidateQueries({ queryKey: ["projects"] });
  };
  const metaLine = [
    t.projects.modes[p.mode] ?? p.mode,
    channel && t.projects.channel(channel.name),
    p.meta.auto && t.projects.auto,
    t.age(p.updated_at),
    p.usage?.tts_chars > 0 && t.projects.voiceCost(p.usage.tts_chars, p.usage.usd - (p.usage.clip_usd ?? 0)),
  ].filter(Boolean);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b bg-ground">
        <header className="flex min-h-14 flex-wrap items-center gap-x-4 gap-y-2 border-b px-6 py-2">
          <Link to="/projects" className="inline-flex h-10 items-center gap-2 text-[13px] font-medium">
            <ArrowLeft className="size-4" />
            {t.projects.back}
          </Link>
          <span aria-hidden className="font-mono text-[13px] text-muted-foreground">
            /
          </span>
          <PageTitle>{p.meta.title || p.title}</PageTitle>
          {status && <StatusChip status={status} className="text-[13px]" />}
          <div className="ml-auto flex items-center gap-2">
            <Select value={from ?? p.retry.auto} onValueChange={(v) => v != null && setFrom(v as RetryStep)}>
              <SelectTrigger className="w-[200px]" aria-label={t.projects.rerunFrom} disabled={active}>
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
              variant={status === "failed" ? "default" : "secondary"}
              onClick={() => retry.mutate(from)}
              disabled={active || retry.isPending}
            >
              {retry.isPending ? <Loader2 className="animate-spin" /> : status === "failed" && !from ? <Play /> : <RotateCcw />}
              {status === "failed" && !from ? t.projects.resume : t.projects.rerun}
            </Button>
            {inTauri && info.mode === "local" && (
              <Button variant="secondary" onClick={() => openFolder(p.folder)}>
                <FolderOpen />
                {t.projects.openFolder}
              </Button>
            )}
            <Button
              variant="destructive"
              onClick={() => setDeleting(true)}
              disabled={active}
              title={active ? t.projects.deleteBusy : undefined}
            >
              <Trash2 />
              {t.projects.delete}
            </Button>
          </div>
        </header>
        <div className="truncate px-6 font-mono text-xs leading-[35px] text-muted-foreground">
          <span className="text-foreground">#{p.id}</span> · {metaLine.join(" · ")}
        </div>
      </div>

      {retry.error && <p className="shrink-0 border-b px-6 py-2 text-[13px] text-coral">{retry.error.message}</p>}
      {!active && p.has_script && REDO_SCRIPT.includes(from ?? p.retry.auto) && (
        <p className="flex shrink-0 items-center gap-2 border-b px-6 py-2 text-[13px] text-amber">
          <TriangleAlert className="size-4 shrink-0" />
          {t.projects.redoReplacesScript}
        </p>
      )}
      {p.meta.send_error && (
        <p className="flex shrink-0 items-center gap-2 border-b px-6 py-2 text-[13px] text-amber">
          <TriangleAlert className="size-4 shrink-0" />
          {t.review.sendError}: {p.meta.send_error}
        </p>
      )}
      {active && (
        <div className="flex shrink-0 items-center gap-4 border-b px-6 py-2.5">
          <span className="text-[13px] text-cyan">{step}</span>
          <div className="h-1 min-w-0 flex-1 rounded-xs bg-white/12">
            <div className="h-full rounded-xs bg-cyan transition-all" style={{ width: `${pct}%` }} />
          </div>
          <span className="font-mono text-xs text-muted-foreground tabular-nums">{pct}%</span>
        </div>
      )}
      <DeleteProjectDialog
        api={api}
        id={p.id}
        title={p.meta.title || p.title}
        open={deleting}
        onOpenChange={setDeleting}
        onDeleted={() => navigate("/projects")}
      />

      {/* Three docked columns (monitor and sources · script, timeline, log · review and the post); a single page below 1180 px. */}
      <div className="grid min-h-0 flex-1 overflow-y-auto min-[1180px]:grid-cols-[400px_minmax(0,1fr)_340px] min-[1180px]:grid-rows-[minmax(0,1fr)] min-[1180px]:overflow-hidden">
        <div className="order-1 min-w-0 border-r min-[1180px]:overflow-y-auto">
          <Monitor
            api={api}
            p={p}
            playable={playable}
            active={active}
            view={view}
            onView={setView}
            videoRef={dubVideo}
            time={time}
            duration={length}
            onTime={(tm, d) => {
              setTime(tm);
              setLength(d);
            }}
          />
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
          {p.mode !== "ai" && <SourcesCard api={api} p={p} active={active} onQueued={() => refetch()} />}
        </div>

        <div className="order-3 min-w-0 border-r min-[1180px]:order-2 min-[1180px]:overflow-y-auto">
          {p.has_script && (
            <ScriptCard
              api={api}
              id={p.id}
              active={active}
              canRender={p.retry.steps.includes("render")}
              measured={marks}
              playhead={playable ? time : 0}
              onSeek={playable ? seek : undefined}
            />
          )}
          {marks && lines && nar && (
            <Panel title={t.studio.timeline} aside={mmss(Math.max(length, nar.duration))} flush>
              <TimelineStrip
                marks={marks}
                texts={lines.map((l) => l.text)}
                words={nar.words}
                total={Math.max(length, nar.duration)}
                playhead={playable ? time : 0}
                active={playable && time > 0 ? lineAt(marks, time) : -1}
                labels={{ shots: t.studio.shots, voice: t.studio.voice, captions: t.studio.captions }}
                onSeek={playable ? seek : () => undefined}
              />
            </Panel>
          )}
          <Panel title={t.projects.log} flush>
            <pre
              ref={logRef}
              className="max-h-80 overflow-auto p-4 font-mono text-xs leading-[18px] whitespace-pre-wrap"
            >
              {log.split("\n").map((ln, i) => {
                const m = /^(\d\d:\d\d:\d\d) (.*)$/.exec(ln);
                return m ? (
                  <div key={i} className={/Waiting for|Chờ/.test(m[2]) ? "text-amber" : undefined}>
                    <span className="text-muted-foreground">{m[1]}</span> {m[2]}
                  </div>
                ) : (
                  <div key={i}>{ln}</div>
                );
              })}
            </pre>
          </Panel>
        </div>

        <div className="order-2 min-w-0 min-[1180px]:order-3 min-[1180px]:overflow-y-auto">
          {status === "review" && p.status === "review" && (
            <div className="border-b p-4">
              <ReviewCard api={api} p={p} channel={channel} onDone={refreshAll} />
            </div>
          )}
          {p.meta.qa && p.meta.video && <QualityCard qa={p.meta.qa} held={p.status === "review" && p.meta.review === "video"} />}

          {post && (
            <Panel
              title={t.projects.post}
              aside={
                <button
                  type="button"
                  onClick={copy}
                  className="-mr-4 inline-flex h-10 items-center gap-1.5 border-l px-3.5 font-sans text-xs font-semibold text-foreground hover:bg-raised"
                >
                  {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                  {copied ? t.projects.copied : t.projects.copy}
                </button>
              }
            >
              <PostText text={post} />
            </Panel>
          )}

          {status === "done" && p.meta.video && (
            <PublishCard api={api} projectId={p.id} history={p.meta.postiz ?? []} hasWide={!!p.meta.wide} onSent={() => refetch()} />
          )}

          {p.ai && (
            <Panel title={t.ai.card} bodyClassName="space-y-1 text-[13px] leading-5">
              {p.ai.topic && <div>{p.ai.episode ? `${t.ai.episode(p.ai.episode)} · ${p.ai.topic}` : p.ai.topic}</div>}
              {p.ai.recap && (
                <div className="text-xs leading-[18px] text-muted-foreground">
                  {t.ai.recap}: {p.ai.recap}
                </div>
              )}
              <div className="text-muted-foreground">
                {t.ai.provider}: {t.ai.providers[p.ai.provider] ?? p.ai.provider}
                {p.ai.scenes != null && ` · ${t.ai.scenes(p.ai.scenes)}`}
                {!!p.ai.clips && ` · ${t.ai.clipsMade(p.ai.clips)}${p.ai.clip_provider ? ` (${t.ai.clipProviders[p.ai.clip_provider] ?? p.ai.clip_provider})` : ""}`}
                {!!p.ai.cost && ` · ${t.ai.cost(p.ai.cost, !!p.ai.clips)}`}
              </div>
              {p.ai.needs_review && (
                <div className="text-amber">
                  {p.ai.provider === "fal" && p.ai.clip_provider === "heygen" ? t.ai.clipReviewNote : t.ai.reviewNote}
                </div>
              )}
            </Panel>
          )}

          {p.mode === "topic" && (p.meta.topic || p.meta.subject) && (
            <Panel title={t.projects.topic} bodyClassName="space-y-1 text-[13px] leading-5">
              {p.meta.topic && <div>{p.meta.topic}</div>}
              {p.meta.subject?.angle && <div className="text-muted-foreground">{p.meta.subject.angle}</div>}
            </Panel>
          )}

          {p.trend && (
            <Panel title={t.projects.source} bodyClassName="space-y-2 text-[13px] leading-5">
              <div lang="zh" className="font-medium">
                {p.trend.title_zh}
              </div>
              {p.trend.angle && (
                <div className="space-y-1">
                  <Kicker>{t.studio.angle}</Kicker>
                  <div>{p.trend.angle}</div>
                </div>
              )}
              {p.trend.url && (
                <ExternalA href={p.trend.url} className="inline-flex items-center gap-2 font-medium">
                  <ExternalLink className="size-3.5" />
                  {t.studio.openStory}
                </ExternalA>
              )}
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}
