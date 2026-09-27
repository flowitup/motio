import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  FolderOpen,
  Loader2,
  RotateCcw,
  ScanSearch,
  Trash2,
  Undo2,
  Upload,
  WandSparkles,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Choice } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  useApi,
  type Api,
  type DelogoBox,
  type DelogoRights,
  type DelogoTarget,
} from "@/lib/api";
import { inTauri, openExternal, openFolder, useEngine } from "@/lib/engine";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const MAX_BOXES = 4;
const MIN_DRAW = 6; // px khung hình: nhỏ hơn thì coi như bấm nhầm

const sourceKey = (pid: number, i: number) => `p${pid}-${i}`;

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
  const remove = useMutation({
    mutationFn: (key: string) => api.delogoDelete(key),
    onSuccess: (_, key) => {
      qc.invalidateQueries({ queryKey: ["delogo-uploads"] });
      if (key === selected) onPick(null);
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
      <CardContent className="grid gap-5">
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
          {upload.error && <p className="text-sm text-destructive">{upload.error.message}</p>}
        </div>

        {!!uploads.data?.length && (
          <div className="grid gap-1">
            <div className="text-xs font-medium text-muted-foreground">{t.delogo.uploads}</div>
            {uploads.data.map((u) => (
              <div key={u.target} className="group flex items-center gap-1">
                <button type="button" className={row(u.target === selected)} onClick={() => onPick(u.target)}>
                  <span className="truncate">{u.name}</span>
                  {u.status === "done" && (
                    <span className="shrink-0 text-xs text-emerald-600 dark:text-emerald-400">{t.delogo.cleaned}</span>
                  )}
                </button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="opacity-0 group-hover:opacity-100 hover:text-destructive focus-visible:opacity-100"
                  onClick={() => remove.mutate(u.target)}
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

        {withSources.length > 0 && (
          <div className="grid gap-1.5">
            <div className="text-xs font-medium text-muted-foreground">{t.delogo.projectSources}</div>
            <Choice
              value={project ? String(project.id) : ""}
              onChange={setPid}
              options={withSources.map((p) => [String(p.id), `#${p.id} · ${p.meta.title || p.title}`])}
            />
            {project && (
              <div className="grid gap-1">
                {(project.meta.sources ?? []).map((s, i) => {
                  const key = sourceKey(project.id, i);
                  return (
                    <button key={key} type="button" className={row(key === selected)} onClick={() => onPick(key)}>
                      <span className="truncate">
                        {i + 1}. {s.platform} · {s.uploader || s.title || s.url}
                      </span>
                      {s.delogo && (
                        <span className="shrink-0 text-xs text-emerald-600 dark:text-emerald-400">
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
        <div key={i} className="absolute border-2 border-red-500 bg-red-500/20" style={pos(b)}>
          {!disabled && (
            <button
              type="button"
              className="absolute -top-2.5 -right-2.5 flex size-5 items-center justify-center rounded-full bg-red-500 text-white shadow"
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
      {draft && <div className="absolute border-2 border-dashed border-red-400 bg-red-400/10" style={pos(draft)} />}
    </div>
  );
}

/** Cột phải: vẽ / tự tìm khung, xác nhận quyền, xoá logo, xem kết quả. */
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
  const [confirmed, setConfirmed] = useState<boolean | null>(null);
  const [rights, setRights] = useState<DelogoRights | null>(null);
  const [at, setAt] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const shown = boxes ?? v?.boxes ?? [];
  const isConfirmed = confirmed ?? !!v?.rights;
  const chosenRights = rights ?? v?.rights ?? "owned";

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
    mutationFn: () => api.delogoRun(target, shown, chosenRights),
    onSuccess: (d) => {
      put(d);
      setBoxes(null);
    },
  });
  const restore = useMutation({
    mutationFn: () => api.delogoRestore(target),
    onSuccess: (d) => {
      put(d);
      qc.invalidateQueries({ queryKey: ["delogo-uploads"] });
    },
  });
  const rerender = useMutation({
    mutationFn: () => api.retry(v!.project_id!, "voice"),
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
        <CardContent className="flex items-center justify-between gap-3 text-sm text-destructive">
          {q.error.message}
          <Button variant="outline" size="sm" onClick={onGone}>
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
  const error = frame.error ?? detect.error ?? run.error ?? restore.error ?? rerender.error;

  return (
    <div className="min-w-0 space-y-5">
      <Card>
        <CardHeader>
          <CardTitle className="truncate">{v.name}</CardTitle>
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

          <div className="grid gap-3 rounded-lg border p-3">
            <label className="flex items-start gap-2 text-sm font-medium">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-primary"
                checked={isConfirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                disabled={busy}
              />
              {t.delogo.confirm}
            </label>
            {isConfirmed && (
              <div className="grid gap-1.5 pl-6">
                <Choice
                  value={chosenRights}
                  onChange={(r) => setRights(r as DelogoRights)}
                  options={(["owned", "licensed"] as const).map((r) => [r, t.delogo.rights[r]])}
                  className="w-full sm:w-56"
                />
                <p className="text-xs text-muted-foreground">{t.delogo.confirmHint}</p>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => run.mutate()} disabled={busy || !shown.length || !isConfirmed}>
              {busy ? <Loader2 className="animate-spin" /> : <WandSparkles />}
              {t.delogo.run}
            </Button>
            {error && <span className="text-sm text-destructive">{error.message}</span>}
            {v.status === "failed" && v.error && <span className="text-sm text-destructive">{v.error}</span>}
          </div>
          {active && (
            <div className="space-y-1.5">
              <div className="flex justify-between text-sm">
                <span>{v.status === "queued" ? t.delogo.queued : t.delogo.running}</span>
                <span className="text-muted-foreground">{v.pct}%</span>
              </div>
              <Progress value={v.pct} />
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
            {v.kind === "source" && <p className="text-sm text-muted-foreground">{t.delogo.resultSource}</p>}
            <div className="flex flex-wrap gap-2">
              {v.kind === "source" ? (
                <>
                  <Button onClick={() => rerender.mutate()} disabled={rerender.isPending}>
                    {rerender.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />}
                    {t.delogo.rerender}
                  </Button>
                  <Button variant="outline" onClick={() => restore.mutate()} disabled={restore.isPending}>
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
                  <Button variant="outline" onClick={() => restore.mutate()} disabled={restore.isPending}>
                    <Trash2 />
                    {t.delogo.deleteResult}
                  </Button>
                </>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function DelogoPage() {
  const api = useApi()!;
  const [params, setParams] = useSearchParams();
  const target = params.get("target");
  const pick = (key: string | null) => setParams(key ? { target: key } : {});
  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{t.delogo.title}</h1>
        <p className="text-sm text-muted-foreground">{t.delogo.hint}</p>
      </header>
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
  );
}
