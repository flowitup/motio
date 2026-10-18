import { useMutation } from "@tanstack/react-query";
import { Clapperboard, Copy, Eraser, Loader2 } from "lucide-react";
import { useState } from "react";
import { Choice, Field } from "@/components/form";
import { Panel } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import type { Api, ProjectDetail, SourceEffects } from "@/lib/api";
import { t } from "@/i18n";

const NONE: SourceEffects = { mirror: false, color: null };

// gần giống render.COLOR_FILTERS của engine, chỉ để xem trước trên trình duyệt
const PREVIEW: Record<string, string> = {
  warm: "sepia(0.25) saturate(1.15) hue-rotate(-8deg)",
  cool: "hue-rotate(12deg) saturate(0.95) brightness(1.02)",
  mono: "grayscale(1)",
  sepia: "sepia(1)",
  vivid: "saturate(1.35) contrast(1.08)",
  faded: "saturate(0.7) contrast(0.9) brightness(1.03)",
};

/** Lật gương, bộ lọc màu người dùng bật tay trên từng nguồn (video AI: một thiết lập cho mọi cảnh). */
export function SourceEffectsCard({
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
  const fx = p.effects;
  const saved = (fx?.sources ?? []).map(({ mirror, color }) => ({ mirror, color }));
  const [sel, setSel] = useState(0);
  const [edits, setEdits] = useState<SourceEffects[]>(saved);
  const save = useMutation({ mutationFn: () => api.setEffects(p.id, edits), onSuccess: onQueued });
  if (!fx || !fx.sources.length) return null;

  const src = fx.sources[Math.min(sel, fx.sources.length - 1)];
  const mine = edits[sel] ?? NONE;
  const dirty = JSON.stringify(edits) !== JSON.stringify(saved);
  const off = active;
  const isOn = (e: SourceEffects) => e.mirror || !!e.color;
  const setMine = (next: Partial<SourceEffects>) => setEdits((all) => all.map((e, i) => (i === sel ? { ...e, ...next } : e)));

  return (
    <Panel title={t.effects.title} bodyClassName="grid gap-3 text-[13px]">
      <p className="text-xs leading-[18px] text-muted-foreground">{fx.whole_video ? t.effects.hintAi : t.effects.hint}</p>
      {fx.sources.length > 1 && (
        <Choice
          value={String(sel)}
          onChange={(v) => setSel(Number(v))}
          options={fx.sources.map((_, i) => [String(i), t.effects.source(i + 1)])}
          label={t.effects.title}
        />
      )}
      <label className="flex min-h-10 items-center gap-3">
        <Switch checked={mine.mirror} onCheckedChange={(v) => setMine({ mirror: v })} disabled={off} />
        {t.effects.mirror}
      </label>
      <Field label={t.effects.color}>
        {/* Choice không có trạng thái tắt: khi khoá thì chỉ hiện tên bộ lọc */}
        {off ? (
          <p className="text-muted-foreground">{t.effects.colors[mine.color ?? "none"] ?? mine.color}</p>
        ) : (
          <Choice
            value={mine.color ?? "none"}
            onChange={(v) => setMine({ color: v === "none" ? null : v })}
            options={["none", ...fx.colors].map((c) => [c, t.effects.colors[c] ?? c])}
          />
        )}
      </Field>
      {!fx.whole_video &&
        (src.media ? (
          <Field label={t.effects.preview}>
            <div className="overflow-hidden rounded-lg bg-black">
              <video
                key={src.media}
                src={`${api.mediaUrl(src.media)}#t=1`}
                preload="metadata"
                muted
                playsInline
                className="mx-auto block max-h-72 max-w-full"
                style={{ transform: mine.mirror ? "scaleX(-1)" : undefined, filter: mine.color ? PREVIEW[mine.color] : undefined }}
              />
            </div>
          </Field>
        ) : (
          <p className="text-xs text-coral">{t.effects.missing}</p>
        ))}
      {save.data && !save.data.queued && !dirty && <p className="text-xs text-mint">{t.effects.saved}</p>}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {save.error && <p className="mr-auto text-destructive">{save.error.message}</p>}
        {fx.sources.length > 1 && (
          <Button variant="ghost" onClick={() => setEdits(edits.map(() => ({ ...mine })))} disabled={off}>
            <Copy />
            {t.effects.all}
          </Button>
        )}
        <Button variant="ghost" onClick={() => setMine(NONE)} disabled={active || !isOn(mine)}>
          <Eraser />
          {t.effects.clear}
        </Button>
        <Button onClick={() => save.mutate()} disabled={active || save.isPending || !dirty}>
          {save.isPending ? <Loader2 className="animate-spin" /> : <Clapperboard />}
          {t.effects.save}
        </Button>
      </div>
    </Panel>
  );
}
