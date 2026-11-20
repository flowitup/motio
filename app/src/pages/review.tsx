import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCheck, ChevronLeft, ExternalLink, FileText, Film, Images, Loader2, Play, Send, SkipForward } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { ConfirmAction } from "@/components/confirm-action";
import { Kicker, PageTitle, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, type Api, type Channel, type Project, type Review } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const POLL_MS = 15_000;
const KIND_ICON: Record<Review, typeof Film> = { script: FileText, shots: Images, video: Film };

/** A key hint next to a button's label. */
function Key({ children }: { children: string }) {
  return (
    <kbd className="rounded border border-hairline-strong bg-black/20 px-1.5 font-mono text-xs leading-5 font-medium text-inherit opacity-80">
      {children}
    </kbd>
  );
}

function titleOf(p: Project): string {
  return p.meta.title || p.title;
}

/** The narration as it will be read: the script gate is a read, edits happen on the project page. */
function ScriptPreview({ api, p }: { api: Api; p: Project }) {
  const { data, isLoading, error } = useQuery({ queryKey: ["script", p.id], queryFn: () => api.script(p.id) });
  if (isLoading) return <Skeleton className="h-64 w-full rounded-lg" />;
  if (error || !data) return <p className="text-[13px] text-coral">{error?.message}</p>;
  const { script } = data;
  const words = script.lines.reduce((n, ln) => n + ln.text.split(/\s+/).filter(Boolean).length, 0);
  return (
    <article className="mx-auto w-full max-w-2xl space-y-4">
      <header className="space-y-1">
        <Kicker>{t.script.videoTitle}</Kicker>
        <h2 className="text-xl leading-7 font-semibold">{script.title_fr}</h2>
        <p className="font-mono text-xs text-muted-foreground tabular-nums">
          {t.queue.scriptStats(script.lines.length, words, Math.round(words / data.words_per_sec + data.tail))}
        </p>
      </header>
      <ol className="space-y-2">
        {script.lines.map((ln, i) => (
          <li key={i} className="flex gap-3 rounded-lg border bg-panel px-3 py-2">
            <span className="w-5 shrink-0 pt-0.5 text-right font-mono text-xs text-muted-foreground tabular-nums">{i + 1}</span>
            <p className="min-w-0 text-[15px] leading-6 break-words">{ln.text}</p>
          </li>
        ))}
      </ol>
      {script.description && (
        <section className="space-y-1">
          <Kicker>{t.script.description}</Kicker>
          <p className="text-[13px] leading-5 whitespace-pre-wrap text-muted-foreground">{script.description}</p>
        </section>
      )}
    </article>
  );
}

function VideoPreview({ api, p, videoRef }: { api: Api; p: Project; videoRef: React.RefObject<HTMLVideoElement | null> }) {
  const qa = p.meta.qa;
  const problems = qa?.checks.filter((c) => c.level !== "ok") ?? [];
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-wrap items-start justify-center gap-6">
      <div className="rounded-xl border border-hairline-strong bg-monitor p-2">
        {p.meta.video ? (
          <video
            key={p.id}
            ref={videoRef}
            src={api.mediaUrl(p.meta.video, p.updated_at)}
            poster={p.meta.thumb ? api.mediaUrl(p.meta.thumb, p.updated_at) : undefined}
            controls
            playsInline
            className="aspect-[9/16] h-[min(62vh,640px)] rounded-xs bg-black"
          />
        ) : (
          <div className="flex aspect-[9/16] h-[min(62vh,640px)] items-center justify-center text-[13px] text-muted-foreground">
            {t.studio.noVideoYet}
          </div>
        )}
      </div>
      <div className="min-w-64 flex-1 basis-72 space-y-4">
        <section className="space-y-1">
          <Kicker>{t.projects.post}</Kicker>
          <h2 className="text-[15px] leading-[22px] font-semibold">{titleOf(p)}</h2>
          {p.meta.description && <p className="text-[13px] leading-5 whitespace-pre-wrap text-muted-foreground">{p.meta.description}</p>}
          {!!p.meta.hashtags?.length && <p className="text-[13px] leading-5 text-cyan">{p.meta.hashtags.join(" ")}</p>}
        </section>
        {qa && (
          <section className="space-y-1">
            <Kicker>{t.queue.quality}</Kicker>
            {problems.length ? (
              <ul className="space-y-1">
                {problems.map((c) => (
                  <li key={c.id} className={cn("text-[13px] leading-5", c.level === "fail" ? "text-coral" : "text-amber")}>
                    {c.msg}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[13px] leading-5 text-mint">{t.queue.qualityOk}</p>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

export default function ReviewPage() {
  const api = useApi()!;
  const qc = useQueryClient();
  const navigate = useNavigate();
  const video = useRef<HTMLVideoElement>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const [gone, setGone] = useState<Set<number>>(new Set()); // approved here: out of the list before the next poll
  const [confirming, setConfirming] = useState(false);
  const [batch, setBatch] = useState(false);

  const list = useQuery({
    queryKey: ["projects", "review-queue"],
    queryFn: () => api.projectPage({ status: "review", limit: 100 }),
    refetchInterval: POLL_MS,
  });
  const channels = useQuery({ queryKey: ["channels"], queryFn: () => api.channels(), staleTime: 30_000 });
  const channelOf = useMemo(() => new Map((channels.data ?? []).map((c) => [c.id, c])), [channels.data]);
  // Oldest first: the queue is worked from the top, what waited longest goes first.
  const items = useMemo(
    () => [...(list.data ?? [])].filter((p) => p.status === "review" && p.meta.review && !gone.has(p.id)).reverse(),
    [list.data, gone],
  );
  const index = Math.max(0, items.findIndex((p) => p.id === picked));
  const p: Project | undefined = items[index];
  const channel: Channel | undefined = p?.meta.channel ? channelOf.get(p.meta.channel) : undefined;
  const kind = p?.meta.review ?? null;
  const targets = channel?.postiz.length ?? 0;
  const mode = channel?.send_mode ?? "draft";
  const publicNow = kind === "video" && targets > 0 && mode === "now"; // posts publicly at once: asks first
  const scripts = items.filter((x) => x.meta.review === "script");

  const names = useQuery({
    queryKey: ["postiz-channels"],
    queryFn: () => api.postizChannels(),
    retry: false,
    staleTime: 60_000,
    enabled: publicNow,
  });
  const channelNames = (channel?.postiz ?? []).map((id) => names.data?.find((c) => c.id === id)?.name ?? id);

  const move = useCallback(
    (step: number) => {
      if (!items.length) return;
      setPicked(items[(index + step + items.length) % items.length].id);
    },
    [items, index],
  );
  const settle = (ids: number[]) => {
    const next = items.find((x, i) => i > index && !ids.includes(x.id)) ?? items.find((x) => !ids.includes(x.id));
    setGone((g) => new Set([...g, ...ids]));
    setPicked(next?.id ?? null);
    qc.invalidateQueries({ queryKey: ["projects"] });
  };
  const approve = useMutation({
    mutationFn: ({ id, send }: { id: number; send: boolean }) => api.approve(id, send),
    onSuccess: (_r, v) => settle([v.id]),
    onSettled: () => setConfirming(false),
  });
  const approveScripts = useMutation({
    mutationFn: async (ids: number[]) => {
      const done: number[] = [];
      try {
        for (const id of ids) {
          await api.approve(id, true);
          done.push(id);
        }
      } finally {
        if (done.length) settle(done); // some went through before one failed: they are out of the queue all the same
      }
      return done;
    },
    onSettled: () => setBatch(false),
  });
  const busy = approve.isPending || approveScripts.isPending;

  const act = useCallback(
    (send: boolean) => {
      if (!p || busy || kind === "shots") return;
      if (send && publicNow) setConfirming(true);
      else approve.mutate({ id: p.id, send });
    },
    [p, busy, kind, publicNow, approve],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || confirming || batch) return;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      const key = e.key.toLowerCase();
      if (key === "j" || key === "arrowdown") move(1);
      else if (key === "k" || key === "arrowup") move(-1);
      else if (key === "a") act(true);
      else if (key === "s" && kind === "video" && targets > 0) act(false);
      else if ((key === "o" || key === "enter") && p && el?.tagName !== "BUTTON" && el?.tagName !== "A") navigate(`/projects/${p.id}`);
      else if (key === " " && video.current && el?.tagName !== "BUTTON" && el?.tagName !== "VIDEO") {
        if (video.current.paused) void video.current.play();
        else video.current.pause();
      } else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [move, act, kind, targets, p, navigate, confirming, batch]);

  const error = approve.error?.message ?? approveScripts.error?.message;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <TopBar>
        <Link to="/projects" className="flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground">
          <ChevronLeft className="size-4" aria-hidden />
          {t.queue.back}
        </Link>
        <PageTitle>{t.queue.title}</PageTitle>
        {items.length > 0 && <span className="font-mono text-[13px] text-muted-foreground tabular-nums">{t.queue.waiting(items.length)}</span>}
        {scripts.length > 1 && (
          <Button variant="secondary" className="ml-auto" onClick={() => setBatch(true)} disabled={busy}>
            {approveScripts.isPending ? <Loader2 className="animate-spin" /> : <CheckCheck />}
            {t.queue.approveScripts(scripts.length)}
          </Button>
        )}
      </TopBar>
      {list.isLoading ? (
        <div className="p-6">
          <Skeleton className="h-64 w-full rounded-lg" />
        </div>
      ) : !p ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
          <CheckCheck className="size-8 text-mint" />
          <p className="text-[15px] font-semibold">{t.queue.empty}</p>
          <p className="max-w-md text-[13px] text-muted-foreground">{t.queue.emptyHint}</p>
          {list.error && <p className="text-[13px] text-coral">{list.error.message}</p>}
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(220px,280px)_minmax(0,1fr)]">
          <ul aria-label={t.queue.title} className="min-h-0 overflow-y-auto border-r">
            {items.map((x) => {
              const Icon = KIND_ICON[x.meta.review as Review] ?? Film;
              const on = x.id === p.id;
              return (
                <li key={x.id}>
                  <button
                    type="button"
                    aria-current={on}
                    onClick={() => setPicked(x.id)}
                    className={cn(
                      "flex w-full items-start gap-3 border-b border-l-2 px-3 py-2.5 text-left",
                      on ? "border-l-amber bg-white/8" : "border-l-transparent hover:bg-white/5",
                    )}
                  >
                    <Icon className={cn("mt-0.5 size-4 shrink-0", on ? "text-amber" : "text-muted-foreground")} aria-hidden />
                    <span className="min-w-0 space-y-0.5">
                      <span className="line-clamp-2 text-[13px] leading-[18px] font-semibold">{titleOf(x)}</span>
                      <span className="block truncate text-xs leading-4 text-muted-foreground">
                        {[t.queue.kinds[x.meta.review as Review], x.meta.channel ? channelOf.get(x.meta.channel)?.name : "", t.age(x.updated_at)]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="flex min-h-0 flex-col">
            <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b px-6 py-3">
              <div className="min-w-0 flex-1 basis-64">
                <h2 className="truncate text-[15px] leading-[22px] font-semibold">{titleOf(p)}</h2>
                <p className="truncate text-xs leading-[18px] text-muted-foreground">
                  {[`#${p.id}`, t.projects.modes[p.mode] ?? p.mode, channel?.name, p.meta.auto ? t.queue.auto : ""].filter(Boolean).join(" · ")}
                </p>
              </div>
              <Link to={`/projects/${p.id}`} className="flex items-center gap-1.5 text-[13px] text-cyan hover:text-cyan-hover">
                <ExternalLink className="size-4" aria-hidden />
                {kind === "script" ? t.queue.openToEdit : t.queue.open}
              </Link>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-6">
              {kind === "video" && <VideoPreview api={api} p={p} videoRef={video} />}
              {kind === "script" && <ScriptPreview api={api} p={p} />}
              {kind === "shots" && (
                <div className="mx-auto flex max-w-md flex-col items-center gap-3 pt-10 text-center">
                  <Images className="size-8 text-amber" />
                  <p className="text-[13px] leading-5 text-muted-foreground">{t.queue.shotsHint}</p>
                  <Button onClick={() => navigate(`/projects/${p.id}`)}>
                    <ExternalLink />
                    {t.queue.open}
                  </Button>
                </div>
              )}
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-t border-amber bg-amber/8 px-6 py-3">
              <p className="min-w-0 flex-1 basis-64 text-xs leading-[18px] text-muted-foreground">
                {error ? (
                  <span className="text-[13px] text-coral">{error}</span>
                ) : kind === "video" ? (
                  targets > 0 ? (
                    t.review.sendPlan(targets, mode)
                  ) : (
                    t.queue.noPostiz
                  )
                ) : kind === "script" ? (
                  t.queue.scriptPlan
                ) : (
                  ""
                )}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {items.length > 1 && (
                  <Button variant="ghost" onClick={() => move(1)} disabled={busy}>
                    <SkipForward />
                    {t.queue.skip}
                    <Key>J</Key>
                  </Button>
                )}
                {kind === "video" && targets > 0 && (
                  <Button variant="secondary" size="lg" onClick={() => act(false)} disabled={busy}>
                    {approve.isPending && approve.variables?.send === false ? <Loader2 className="animate-spin" /> : <Check />}
                    {t.review.approveNoSend}
                    <Key>S</Key>
                  </Button>
                )}
                {kind !== "shots" && (
                  <Button size="lg" onClick={() => act(true)} disabled={busy}>
                    {approve.isPending && approve.variables?.send !== false ? (
                      <Loader2 className="animate-spin" />
                    ) : kind === "script" ? (
                      <Play />
                    ) : targets ? (
                      <Send />
                    ) : (
                      <CheckCheck />
                    )}
                    {kind === "script" ? t.review.approveScript : targets ? t.review.approveSend : t.review.approve}
                    <Key>A</Key>
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
      {p && (
        <ConfirmAction
          open={confirming}
          onOpenChange={setConfirming}
          title={t.publish.nowTitle}
          body={t.publish.nowBody(channelNames)}
          confirm={t.publish.nowConfirm}
          icon={<Send />}
          busy={approve.isPending}
          onConfirm={() => approve.mutate({ id: p.id, send: true })}
        />
      )}
      <ConfirmAction
        open={batch}
        onOpenChange={setBatch}
        title={t.queue.batchTitle(scripts.length)}
        body={t.queue.batchBody}
        confirm={t.queue.batchConfirm}
        icon={<CheckCheck />}
        busy={approveScripts.isPending}
        onConfirm={() => approveScripts.mutate(scripts.map((x) => x.id))}
      />
    </div>
  );
}
