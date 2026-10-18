import { useMutation, useQuery } from "@tanstack/react-query";
import { Clapperboard, Eraser, Loader2, X } from "lucide-react";
import { useRef, useState, type PointerEvent } from "react";
import { Choice, Field } from "@/components/form";
import { Panel } from "@/components/studio";
import { Button } from "@/components/ui/button";
import type { Api, BlurBox, ProjectDetail, SourceMasks } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const MAX_BOXES = 6; // như masks.MAX_BOXES trong engine
const MIN_SIDE = 0.02; // khung nhỏ hơn thì bỏ (engine từ chối)
const MIN_KEEP = 0.25; // vùng giữ lại nhỏ nhất (masks.MIN_KEEP): phóng to tối đa 4×

type Tool = "blur" | "logo" | "keep";

/** Những gì người dùng tự vẽ trên từng video nguồn để giấu chữ in sẵn hoặc watermark đứng yên: khung làm mờ, khung phủ
 * logo của mình (thư viện Logo trong Cài đặt), vùng giữ lại (phóng to cho phần ngoài ra khỏi khung). Không có gì tự tìm
 * hay tự áp: chỉ những gì vẽ ở đây, trên hình nguồn (dưới tiêu đề và phụ đề tiếng Pháp). */
export function SourceMasksCard({
  api,
  p,
  active,
  onQueued,
}: {
  api: Api;
  p: ProjectDetail;
  active: boolean;
  onQueued: () => void;
}) {
  const masks = p.masks ?? [];
  const vid = useRef<HTMLVideoElement>(null);
  const drag = useRef<[number, number] | null>(null);
  const [sel, setSel] = useState(0);
  const [edits, setEdits] = useState<SourceMasks[]>(() => masks.map((m) => ({ boxes: m.boxes, keep: m.keep })));
  const [tool, setTool] = useState<Tool>("blur");
  const [logoId, setLogoId] = useState("");
  const [drawing, setDrawing] = useState<BlurBox | null>(null);
  const [warn, setWarn] = useState("");
  const [at, setAt] = useState(0.3);
  const [length, setLength] = useState(0);
  const { data: logos = [] } = useQuery({ queryKey: ["logos"], queryFn: () => api.logos() });
  const save = useMutation({ mutationFn: () => api.setMasks(p.id, edits), onSuccess: onQueued });
  if (!masks.length) return null;

  const m = masks[Math.min(sel, masks.length - 1)];
  const mine = edits[sel] ?? { boxes: [], keep: null };
  const dur = m.duration || length;
  const dirty = JSON.stringify(edits) !== JSON.stringify(masks.map((x) => ({ boxes: x.boxes, keep: x.keep })));
  const logo = logos.find((l) => l.id === logoId) ?? logos[0];
  const logoOf = (id: string | null) => logos.find((l) => l.id === id);
  const full = tool !== "keep" && mine.boxes.length >= MAX_BOXES;
  const blocked = active || full || (tool === "logo" && !logo);
  const setMine = (next: Partial<SourceMasks>) => setEdits((all) => all.map((e, i) => (i === sel ? { ...e, ...next } : e)));
  const seek = (frac: number) => {
    setAt(frac);
    if (vid.current && dur) vid.current.currentTime = dur * frac;
  };
  const point = (e: PointerEvent<HTMLDivElement>): [number, number] => {
    const r = e.currentTarget.getBoundingClientRect();
    return [Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1), Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1)];
  };
  const rect = (p0: [number, number], p1: [number, number]): BlurBox => [
    Math.min(p0[0], p1[0]),
    Math.min(p0[1], p1[1]),
    Math.abs(p1[0] - p0[0]),
    Math.abs(p1[1] - p0[1]),
  ];
  const finish = () => {
    const b = drawing;
    drag.current = null;
    setDrawing(null);
    if (!b) return;
    if (tool === "keep") {
      if (b[2] < MIN_KEEP || b[3] < MIN_KEEP) return setWarn(t.masks.keepSmall);
      setMine({ keep: b });
    } else if (b[2] >= MIN_SIDE && b[3] >= MIN_SIDE) {
      setMine({ boxes: [...mine.boxes, { box: b, logo: tool === "logo" ? (logo?.id ?? null) : null }] });
    }
    setWarn("");
  };
  const style = (b: BlurBox) => ({ left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${b[2] * 100}%`, height: `${b[3] * 100}%` });
  const shown = [
    ...mine.boxes.map((b) => ({ ...b, kept: true })),
    ...(drawing && tool !== "keep" ? [{ box: drawing, logo: tool === "logo" ? (logo?.id ?? null) : null, kept: false }] : []),
  ];
  const keepBox = drawing && tool === "keep" ? drawing : mine.keep;

  return (
    <Panel title={t.masks.title} aside={t.masks.count(mine.boxes.length, MAX_BOXES)} bodyClassName="grid gap-3 text-[13px]">
      <p className="text-xs leading-[18px] text-muted-foreground">{t.masks.hint}</p>
      {masks.length > 1 && (
        <Choice
          value={String(sel)}
          onChange={(v) => {
            setSel(Number(v));
            setLength(0);
          }}
          options={masks.map((_, i) => [String(i), t.masks.source(i + 1)])}
          label={t.masks.title}
        />
      )}
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label={t.masks.tool}>
          <Choice
            value={tool}
            onChange={(v) => {
              setTool(v as Tool);
              setWarn("");
            }}
            options={(["blur", "logo", "keep"] as const).map((k) => [k, t.masks.tools[k]])}
          />
        </Field>
        {tool === "logo" && logos.length > 0 && (
          <Field label={t.masks.logo}>
            <Choice value={logo?.id ?? ""} onChange={setLogoId} options={logos.map((l) => [l.id, l.name])} />
          </Field>
        )}
      </div>
      <p className={cn("text-xs", tool === "logo" && !logos.length ? "text-coral" : "text-muted-foreground")}>
        {tool === "logo" && !logos.length ? t.masks.noLogos : t.masks.toolHint[tool]}
      </p>
      {m.media ? (
        <>
          <div className="overflow-hidden rounded-lg bg-black">
            {/* the drawing layer has the video's own size, so boxes match the picture even when it is letterboxed */}
            <div className="relative mx-auto w-fit overflow-hidden">
              <video
                key={m.media}
                ref={vid}
                src={`${api.mediaUrl(m.media)}#t=${(m.duration || 0) * at}`}
                preload="auto"
                muted
                playsInline
                onLoadedMetadata={(e) => setLength(e.currentTarget.duration || 0)}
                className="pointer-events-none block max-h-96 max-w-full"
              />
              <div
                className={cn("absolute inset-0 touch-none", blocked ? "cursor-not-allowed" : "cursor-crosshair")}
                onPointerDown={(e) => {
                  if (blocked) return;
                  e.currentTarget.setPointerCapture(e.pointerId);
                  drag.current = point(e);
                }}
                onPointerMove={(e) => drag.current && setDrawing(rect(drag.current, point(e)))}
                onPointerUp={finish}
              >
                {keepBox && (
                  // the part that will be cut is dimmed
                  <div
                    className="pointer-events-none absolute border-2 border-cyan shadow-[0_0_0_9999px_rgb(0_0_0/0.6)]"
                    style={style(keepBox)}
                  />
                )}
                {shown.map((b, i) => {
                  const lg = logoOf(b.logo);
                  return (
                    <div
                      key={i}
                      className="pointer-events-none absolute grid place-items-center border-2 border-dashed border-amber bg-amber/25 backdrop-blur-sm"
                      style={style(b.box)}
                    >
                      {lg && <img src={api.mediaUrl(lg.media)} alt="" className="size-full object-contain" />}
                      {b.kept && (
                        <span className="absolute top-0 left-0 bg-amber px-1 text-[10px] leading-4 font-semibold text-black">{i + 1}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
          <Field label={t.masks.moment}>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={at}
              onChange={(e) => seek(Number(e.target.value))}
              className="w-full"
              aria-label={t.masks.moment}
            />
          </Field>
        </>
      ) : (
        <p className="text-xs text-coral">{t.masks.missing}</p>
      )}
      {warn && <p className="text-xs text-coral">{warn}</p>}
      {mine.boxes.length || mine.keep ? (
        <ul className="flex flex-wrap gap-1.5">
          {mine.boxes.map((b, i) => (
            <li key={i}>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setMine({ boxes: mine.boxes.filter((_, j) => j !== i) })}
                disabled={active}
                aria-label={t.masks.removeBox(i + 1)}
              >
                {t.masks.box(i + 1)}
                {b.logo && ` · ${logoOf(b.logo)?.name ?? t.masks.logo}`}
                <X />
              </Button>
            </li>
          ))}
          {mine.keep && (
            <li>
              <Button variant="secondary" size="sm" onClick={() => setMine({ keep: null })} disabled={active} aria-label={t.masks.removeKeep}>
                {t.masks.keep}
                <X />
              </Button>
            </li>
          )}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">{t.masks.none}</p>
      )}
      {save.data && !save.data.queued && !dirty && <p className="text-xs text-mint">{t.masks.saved}</p>}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {save.error && <p className="mr-auto text-destructive">{save.error.message}</p>}
        <Button variant="ghost" onClick={() => setMine({ boxes: [], keep: null })} disabled={active || (!mine.boxes.length && !mine.keep)}>
          <Eraser />
          {t.masks.clear}
        </Button>
        <Button onClick={() => save.mutate()} disabled={active || save.isPending || !dirty}>
          {save.isPending ? <Loader2 className="animate-spin" /> : <Clapperboard />}
          {t.masks.save}
        </Button>
      </div>
    </Panel>
  );
}
