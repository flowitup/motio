import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  FolderOpen,
  Loader2,
  RotateCcw,
  Square,
  ScanSearch,
  Trash2,
  Undo2,
  Upload,
  WandSparkles,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Choice } from "@/components/form";
import { Kicker, PageTitle, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  useApi,
  type Api,
  type DelogoBox,
  type DelogoScope,
  type DelogoTarget,
  type Span,
} from "@/lib/api";
import { inTauri, openExternal, openFolder, useEngine } from "@/lib/engine";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const MAX_BOXES = 4;
const MIN_DRAW = 6; // px khung hình: nhỏ hơn thì coi như bấm nhầm

const sourceKey = (pid: number, i: number) => `p${pid}-${i}`;

/** 83.4 → "1:23" */
const clock = (sec: number) => {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
/** "1:23" / "1:02:03" / "83.5" → giây; sai dạng → NaN */
const parseClock = (text: string) => {
  const parts = text.trim().split(":");
  if (parts.length > 3 || parts.some((x) => !/^\d+(\.\d+)?$/.test(x))) return NaN;
  return parts.reduce((acc, x) => acc * 60 + Number(x), 0);
};
const total = (spans: Span[]) => spans.reduce((acc, [a, b]) => acc + b - a, 0);
const spansText = (spans: Span[]) => spans.map(([a, b]) => `${clock(a)}–${clock(Math.ceil(b))}`).join(", ");

/** Cột trái: tải video lên, file đã tải lên, video nguồn của các dự án. */
function PickCard({ api, selected, onPick }: { api: Api; selected: string | null; onPick: (key: string | null) => void }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [pct, setPct] = useState<number | null>(null);
  const uploads = useQuery({ queryKey: ["delogo-uploads"], queryFn: api.delogoUploads });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const withSources = (projects.data ?? []).filter((p) => p.meta.sources?.length);
  const fromSelected = selected?.match(/^p(\d+)-/)?.[1];
  const [pid, setPid] = useState<string>(fromSelected ?? "");
  const project = withSources.find((p) => String(p.id) === (pid || String(withSources[0]?.id ?? "")));

  const upload = useMutation({
    mutationFn: (file: File) => api.delogoUpload(file, setPct),
    onSuccess: (v) => {
      qc.invalidateQueries({ queryKey: ["delogo-uploads"] });
      qc.setQueryData(["delogo", v.target], v);
      onPick(v.target);
    },
    onSettled: () => setPct(null),
  });
  const [removing, setRemoving] = useState<{ target: string; name: string } | null>(null);
  const remove = useMutation({
    mutationFn: (key: string) => api.delogoDelete(key),
    onSuccess: (_, key) => {
      qc.invalidateQueries({ queryKey: ["delogo-uploads"] });
      if (key === selected) onPick(null);
      setRemoving(null);
    },
  });

  const row = (active: boolean) =>
    cn(
      "flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent",
      active && "bg-accent font-medium",
    );

  return (
    <Card className="self-start">
      <CardHeader>
        <CardTitle>{t.delogo.pick}</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-[minmax(0,1fr)] gap-5">
        <div className="grid gap-1.5">
          <input
            ref={input}
            type="file"
            accept="video/*,.mkv,.m4v"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload.mutate(f);
              e.target.value = "";
            }}
          />
          <Button variant="outline" onClick={() => input.current?.click()} disabled={upload.isPending}>
            {upload.isPending ? <Loader2 className="animate-spin" /> : <Upload />}
            {upload.isPending && pct != null ? t.delogo.uploading(pct) : t.delogo.upload}
          </Button>
          <p className="text-xs text-muted-foreground">{t.delogo.uploadHint}</p>
          {upload.error && <p role="alert" className="text-sm text-destructive">{upload.error.message}</p>}
        </div>

        {!!uploads.data?.length && (
          <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
            <Kicker>{t.delogo.uploads}</Kicker>
            {uploads.data.map((u) => (
              <div key={u.target} className="group flex items-center gap-1">
                <button type="button" className={row(u.target === selected)} onClick={() => onPick(u.target)}>
                  <span className="truncate">{u.name}</span>
                  {u.status === "done" && (
                    <span className="shrink-0 text-xs text-mint">{t.delogo.cleaned}</span>
                  )}
                </button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="opacity-60 hover:text-destructive hover:opacity-100 focus-visible:opacity-100"
                  onClick={() => setRemoving(u)}
                  disabled={u.status === "queued" || u.status === "running"}
                  aria-label={t.delogo.deleteUpload}
                  title={t.delogo.deleteUpload}
                >
                  <Trash2 />
                </Button>
              </div>
            ))}
          </div>
        )}
        <ConfirmDialog
          open={removing !== null}
          onOpenChange={(o) => !o && setRemoving(null)}
          title={t.delogo.deleteUpload}
          description={removing && t.delogo.confirmDeleteUpload(removing.name)}
          confirmLabel={t.delogo.deleteUpload}
          pending={remove.isPending}
          error={remove.error?.message}
          onConfirm={() => removing && remove.mutate(removing.target)}
        />

        {withSources.length > 0 && (
          <div className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
            <Kicker>{t.delogo.projectSources}</Kicker>
            <Choice
              value={project ? String(project.id) : ""}
              onChange={setPid}
              options={withSources.map((p) => [String(p.id), `#${p.id} · ${p.meta.title || p.title}`])}
            />
            {project && (
              <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
                {(project.meta.sources ?? []).map((s, i) => {
                  const key = sourceKey(project.id, i);
                  return (
                    <button key={key} type="button" className={row(key === selected)} onClick={() => onPick(key)}>
                      <span className="truncate">
                        {i + 1}. {s.platform} · {s.uploader || s.title || s.url}
                      </span>
                      {s.delogo && (
                        <span className="shrink-0 text-xs text-mint">
                          {t.delogo.cleaned}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** Khung hình + vẽ khung quanh logo bằng chuột (toạ độ theo pixel của khung hình). */
function BoxCanvas({
  src,
  width,
  height,
  boxes,
  onChange,
  disabled,
}: {
  src: string;
  width: number;
  height: number;
  boxes: DelogoBox[];
  onChange: (b: DelogoBox[]) => void;
  disabled: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const [draft, setDraft] = useState<DelogoBox | null>(null);
  const canDraw = !disabled && boxes.length < MAX_BOXES;

  const at = (e: PointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const clamp = (v: number, max: number) => Math.min(Math.max(v, 0), max);
    return {
      x: clamp(((e.clientX - r.left) / r.width) * width, width),
      y: clamp(((e.clientY - r.top) / r.height) * height, height),
    };
  };
  const rect = (a: { x: number; y: number }, b: { x: number; y: number }): DelogoBox => ({
    x: Math.round(Math.min(a.x, b.x)),
    y: Math.round(Math.min(a.y, b.y)),
    w: Math.round(Math.abs(a.x - b.x)),
    h: Math.round(Math.abs(a.y - b.y)),
  });
  const pos = (b: DelogoBox) => ({
    left: `${(100 * b.x) / width}%`,
    top: `${(100 * b.y) / height}%`,
    width: `${(100 * b.w) / width}%`,
    height: `${(100 * b.h) / height}%`,
  });

  return (
    <div
      ref={ref}
      className={cn("relative mx-auto touch-none overflow-hidden rounded-lg bg-black select-none", canDraw && "cursor-crosshair")}
      style={{ aspectRatio: `${width} / ${height}`, width: `min(100%, calc(62vh * ${width / height}))` }}
      onPointerDown={(e) => {
        if (!canDraw || e.button !== 0) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        start.current = at(e);
        setDraft({ ...start.current, w: 0, h: 0 });
      }}
      onPointerMove={(e) => start.current && setDraft(rect(start.current, at(e)))}
      onPointerUp={(e) => {
        if (!start.current) return;
        const b = rect(start.current, at(e));
        start.current = null;
        setDraft(null);
        if (b.w >= MIN_DRAW && b.h >= MIN_DRAW) onChange([...boxes, b]);
      }}
    >
      <img src={src} alt="" draggable={false} className="pointer-events-none absolute inset-0 size-full" />
      {boxes.map((b, i) => (
        <div key={i} className="absolute border-2 border-coral bg-coral/20" style={pos(b)}>
          {!disabled && (
            <button
              type="button"
              className="absolute -top-2.5 -right-2.5 flex size-5 items-center justify-center rounded-full bg-coral text-monitor"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => onChange(boxes.filter((_, j) => j !== i))}
              aria-label={t.delogo.removeBox}
              title={t.delogo.removeBox}
            >
              <X className="size-3" />
            </button>
          )}
        </div>
      ))}
      {draft && <div className="absolute border-2 border-dashed border-coral bg-coral/10" style={pos(draft)} />}
    </div>
  );
}

/** Cột phải: vẽ / tự tìm khung, xoá logo, xem kết quả. */
function Editor({ api, target, onGone }: { api: Api; target: string; onGone: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { info } = useEngine();
  const q = useQuery({
    queryKey: ["delogo", target],
    queryFn: () => api.delogoTarget(target),
    refetchInterval: (query) => (["queued", "running"].includes(query.state.data?.status ?? "") ? 1000 : false),
  });
  const v = q.data;
  const active = v?.status === "queued" || v?.status === "running";
  const [boxes, setBoxes] = useState<DelogoBox[] | null>(null); // null = chưa sửa, dùng khung đã lưu
  const [at, setAt] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [scope, setScope] = useState<DelogoScope | null>(null); // null = lựa chọn lần trước / mặc định
  const [from, setFrom] = useState<string | null>(null);
  const [to, setTo] = useState<string | null>(null);
  const shown = boxes ?? v?.boxes ?? [];
  // nguồn dự án: chỉ xoá các đoạn video final dùng; file tải lên: cả video hoặc một đoạn
  const saved = v?.scope === "all" || v?.scope === "range" ? v.scope : null;
  const chosenScope: DelogoScope = v?.kind === "source" ? "used" : (scope ?? saved ?? "all");
  const fromText = from ?? clock(v?.span?.[0] ?? 0);
  const toText = to ?? clock(Math.ceil(v?.span?.[1] ?? v?.duration ?? 0));
  const span: Span = [parseClock(fromText), parseClock(toText)];
  const spanBad = chosenScope === "range" && !(span[1] - span[0] >= 0.5);
  const scopeBad = spanBad || (chosenScope === "used" && !v?.used);

  const put = (d: DelogoTarget) => qc.setQueryData(["delogo", target], d);
  const frame = useMutation({ mutationFn: (sec?: number) => api.delogoFrame(target, sec), onSuccess: put });
  const detect = useMutation({
    mutationFn: () => api.delogoDetect(target),
    onSuccess: (r) => {
      setNote(r.note ?? t.delogo.detectFound(r.boxes.length));
      if (r.boxes.length) setBoxes(r.boxes);
    },
  });
  const run = useMutation({
    mutationFn: () => api.delogoRun(target, shown, chosenScope, chosenScope === "range" ? span : undefined),
    onSuccess: (d) => {
      put(d);
      setBoxes(null);
    },
  });
  const [confirmRestore, setConfirmRestore] = useState(false);
  const stop = useMutation({ mutationFn: () => api.delogoCancel(target), onSuccess: put });
  const restore = useMutation({
    mutationFn: () => api.delogoRestore(target),
    onSuccess: (d) => {
      put(d);
      qc.invalidateQueries({ queryKey: ["delogo-uploads"] });
      setConfirmRestore(false);
    },
  });
  // dựng lại với giọng đọc cũ khi còn (không tốn lượt ElevenLabs), không thì đọc lại
  const project = useQuery({
    queryKey: ["project", v?.project_id],
    queryFn: () => api.project(v!.project_id!),
    enabled: v?.project_id != null,
  });
  const keepVoice = !!project.data?.retry.steps.includes("render");
  const rerender = useMutation({
    mutationFn: () => api.retry(v!.project_id!, keepVoice ? "render" : "voice"),
    onSuccess: () => navigate(`/projects/${v!.project_id}`),
  });

  // Nguồn dự án chưa có khung hình nào: lấy một khung (10 % độ dài) để vẽ.
  const needFrame = !!v && !v.frame && !frame.isPending && !frame.isError;
  useEffect(() => {
    if (needFrame) frame.mutate(undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needFrame]);

  // Kéo thanh trượt: đợi dừng tay rồi mới lấy khung hình mới.
  useEffect(() => {
    if (at == null || at === v?.frame_at) return;
    const id = setTimeout(() => frame.mutate(at), 350);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [at]);

  // Xong: danh sách "đã tải lên" / dự án đổi trạng thái.
  const prev = useRef(v?.status);
  useEffect(() => {
    if (prev.current !== v?.status && v?.status === "done") {
      qc.invalidateQueries({ queryKey: ["delogo-uploads"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
      if (v.project_id) qc.invalidateQueries({ queryKey: ["project", v.project_id] });
    }
    prev.current = v?.status;
  }, [v?.status, v?.project_id, qc]);

  if (q.error) {
    return (
      <Card>
        <CardContent role="alert" className="flex items-center justify-between gap-3 text-sm text-destructive">
          {q.error.message}
          <Button variant="outline" size="sm" onClick={onGone} aria-label={t.a11y.close} title={t.a11y.close}>
            <X />
          </Button>
        </CardContent>
      </Card>
    );
  }
  if (!v) return <p className="text-sm text-muted-foreground">{t.common.loading}</p>;

  const busy = active || run.isPending;
  // ?v= đổi theo thời điểm để trình duyệt không giữ khung hình / kết quả cũ
  const media = (rel: string, stamp?: number | null) => api.mediaUrl(rel, Math.round((stamp ?? 0) * 1000) + 1);
  const error = frame.error ?? detect.error ?? run.error ?? stop.error ?? restore.error ?? rerender.error;

  return (
    <div className="min-w-0 space-y-5">
      <Card>
        <CardHeader>
          <CardTitle className="truncate font-sans text-[15px] leading-[22px] font-semibold tracking-normal text-foreground normal-case">{v.name}</CardTitle>
          <p className="text-sm text-muted-foreground">
            {t.delogo.info(v.width, v.height, v.duration)}
            {v.project_id != null && (
              <>
                {" · "}
                <Link to={`/projects/${v.project_id}`} className="hover:underline">
                  {t.delogo.openProject} #{v.project_id}
                </Link>
              </>
            )}
          </p>
        </CardHeader>
        <CardContent className="grid gap-4">
          {v.frame ? (
            <BoxCanvas
              src={media(v.frame, v.frame_at)}
              width={v.width}
              height={v.height}
              boxes={shown}
              onChange={setBoxes}
              disabled={busy}
            />
          ) : (
            <div className="flex aspect-video items-center justify-center rounded-lg bg-black text-white/60">
              <Loader2 className="size-6 animate-spin" />
            </div>
          )}
          <label className="grid gap-1 text-xs text-muted-foreground">
            <span>
              {t.delogo.frameAt} · {(at ?? v.frame_at ?? 0).toFixed(1)} s
              {frame.isPending && <Loader2 className="ml-1 inline size-3 animate-spin" />}
            </span>
            <input
              type="range"
              min={0}
              max={Math.max(v.duration - 0.25, 0)}
              step={0.1}
              value={at ?? v.frame_at ?? 0}
              onChange={(e) => setAt(Number(e.target.value))}
              disabled={busy || !v.frame}
              className="w-full accent-primary"
            />
          </label>
          <p className="text-xs text-muted-foreground">{t.delogo.drawHint}</p>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => detect.mutate()} disabled={busy || detect.isPending}>
              {detect.isPending ? <Loader2 className="animate-spin" /> : <ScanSearch />}
              {t.delogo.detect}
            </Button>
            <Button variant="ghost" onClick={() => setBoxes([])} disabled={busy || !shown.length}>
              <RotateCcw />
              {t.delogo.clearBoxes}
            </Button>
            {note && <span className="text-sm text-muted-foreground">{note}</span>}
          </div>

          <div className="grid gap-2">
            <Kicker>{t.delogo.scope}</Kicker>
            {v.kind === "upload" && (
              <Choice
                value={chosenScope}
                onChange={(x) => setScope(x as DelogoScope)}
                options={(["all", "range"] as const).map((x) => [x, t.delogo.scopes[x]])}
                className="w-full sm:w-64"
              />
            )}
            {chosenScope === "used" && (
              <p className={cn("text-xs", v.used ? "text-muted-foreground" : "text-destructive")}>
                {v.used ? t.delogo.usedHint(v.used.length, total(v.used), v.duration) : t.delogo.notRendered}
              </p>
            )}
            {chosenScope === "all" && <p className="text-xs text-muted-foreground">{t.delogo.allHint}</p>}
            {chosenScope === "range" && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span>{t.delogo.from}</span>
                <Input
                  value={fromText}
                  onChange={(e) => setFrom(e.target.value)}
                  aria-label={t.delogo.from}
                  aria-invalid={Number.isNaN(span[0]) || undefined}
                  disabled={busy}
                  className="w-20"
                />
                <Button variant="ghost" size="sm" onClick={() => setFrom(clock(at ?? v.frame_at ?? 0))} disabled={busy}>
                  {t.delogo.here}
                </Button>
                <span>{t.delogo.to}</span>
                <Input
                  value={toText}
                  onChange={(e) => setTo(e.target.value)}
                  aria-label={t.delogo.to}
                  aria-invalid={Number.isNaN(span[1]) || undefined}
                  disabled={busy}
                  className="w-20"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setTo(clock(Math.ceil(at ?? v.frame_at ?? 0)))}
                  disabled={busy}
                >
                  {t.delogo.here}
                </Button>
                {spanBad && (
                  <span className="text-xs text-destructive">
                    {span.some(Number.isNaN) ? t.delogo.badTime : t.delogo.badSpan}
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => run.mutate()} disabled={busy || !shown.length || scopeBad}>
              {busy ? <Loader2 className="animate-spin" /> : <WandSparkles />}
              {t.delogo.run}
            </Button>
            {error && <span role="alert" className="text-sm text-destructive">{error.message}</span>}
            {v.status === "failed" && v.error && <span role="alert" className="text-sm text-destructive">{v.error}</span>}
          </div>
          {!v.model_ready && !active && <p className="text-xs text-muted-foreground">{t.delogo.modelHint}</p>}
          {active && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span>
                  {v.stopping
                    ? t.delogo.stopping
                    : v.status === "queued"
                      ? t.delogo.queued
                      : v.phase === "model"
                        ? t.delogo.downloading
                        : t.delogo.running}
                </span>
                <span className="flex items-center gap-3 text-muted-foreground">
                  {v.status === "running" && v.phase === "fill" && v.eta != null && t.delogo.eta(v.eta)}
                  <span>{v.pct}%</span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => stop.mutate()}
                    disabled={v.stopping || stop.isPending}
                  >
                    <Square />
                    {t.delogo.stop}
                  </Button>
                </span>
              </div>
              <Progress value={v.pct} aria-label={v.name} />
            </div>
          )}
        </CardContent>
      </Card>

      {v.status === "done" && v.output && (
        <Card>
          <CardHeader>
            <CardTitle>{t.delogo.result}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <video
              key={v.done_at ?? 0}
              src={media(v.output, v.done_at)}
              controls
              className="mx-auto max-h-[62vh] rounded-lg bg-black"
            />
            {v.ranges && (
              <p className="text-sm text-muted-foreground">{t.delogo.cleanedParts(v.ranges.length, total(v.ranges))}</p>
            )}
            {v.uncovered.length > 0 && (
              <p className="text-sm text-destructive">{t.delogo.uncovered(spansText(v.uncovered))}</p>
            )}
            {v.kind === "source" && (
              <p className="text-sm text-muted-foreground">
                {keepVoice ? t.delogo.resultSourceKeepVoice : t.delogo.resultSource}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {v.kind === "source" ? (
                <>
                  <Button onClick={() => rerender.mutate()} disabled={rerender.isPending || project.isPending}>
                    {rerender.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />}
                    {keepVoice ? t.delogo.rerenderKeepVoice : t.delogo.rerender}
                  </Button>
                  <Button variant="outline" onClick={() => setConfirmRestore(true)} disabled={restore.isPending}>
                    <Undo2 />
                    {t.delogo.restore}
                  </Button>
                </>
              ) : (
                <>
                  <Button onClick={() => openExternal(media(v.output!, v.done_at))}>
                    <Download />
                    {t.delogo.download}
                  </Button>
                  {inTauri && info.mode === "local" && (
                    <Button variant="outline" onClick={() => openFolder(v.folder)}>
                      <FolderOpen />
                      {t.delogo.openFolder}
                    </Button>
                  )}
                  <Button variant="outline" onClick={() => setConfirmRestore(true)} disabled={restore.isPending}>
                    <Trash2 />
                    {t.delogo.deleteResult}
                  </Button>
                </>
              )}
            </div>
          </CardContent>
        </Card>
      )}
      <ConfirmDialog
        open={confirmRestore}
        onOpenChange={setConfirmRestore}
        title={v.kind === "source" ? t.delogo.restore : t.delogo.deleteResult}
        description={v.kind === "source" ? t.delogo.confirmRestore : t.delogo.confirmDeleteResult}
        confirmLabel={v.kind === "source" ? t.delogo.restore : t.delogo.deleteResult}
        pending={restore.isPending}
        error={restore.error?.message}
        onConfirm={() => restore.mutate()}
      />
    </div>
  );
}

export default function DelogoPage() {
  const api = useApi()!;
  const [params, setParams] = useSearchParams();
  const target = params.get("target");
  const pick = (key: string | null) => setParams(key ? { target: key } : {});
  return (
    <>
      <TopBar>
        <PageTitle>{t.delogo.title}</PageTitle>
      </TopBar>
      <div className="space-y-5 p-6">
        <p className="text-[13px] text-muted-foreground">{t.delogo.hint}</p>
        <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
          <PickCard api={api} selected={target} onPick={pick} />
          {target ? (
            <Editor key={target} api={api} target={target} onGone={() => pick(null)} />
          ) : (
            <Card>
              <CardContent className="py-16 text-center text-sm text-muted-foreground">{t.delogo.empty}</CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
