import { useMutation } from "@tanstack/react-query";
import { Clapperboard, Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Field } from "@/components/form";
import { Panel } from "@/components/studio";
import { Button } from "@/components/ui/button";
import type { Api, ProjectDetail } from "@/lib/api";
import { t } from "@/i18n";

const pct = (v: number) => Math.round(v * 100);

/** How loud the source video's own sound is under the French voice: 0 % silent, 100 % as recorded. The video is rendered
 * again with the voice it already has (no new voice cost). */
export function SourceSoundCard({
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
  const s = p.source_sound;
  const [value, setValue] = useState(s ? pct(s.volume) : 0);
  const save = useMutation({
    mutationFn: () => api.setSourceVolume(p.id, value / 100),
    onSuccess: onQueued,
  });
  if (!s) return null;
  const dirty = value !== pct(s.volume);
  return (
    <Panel title={t.sourceSound.title} bodyClassName="grid gap-3 text-[13px]">
      <p className="text-xs leading-[18px] text-muted-foreground">{t.sourceSound.hint}</p>
      <Field label={t.sourceSound.volume(value)}>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={value}
          onChange={(e) => setValue(Number(e.target.value))}
          className="w-full"
          aria-label={t.sourceSound.title}
          disabled={active}
        />
      </Field>
      <p className="text-xs text-muted-foreground">
        {s.chosen ? t.sourceSound.chosen : s.volume === 0 ? t.sourceSound.muted : t.sourceSound.default(pct(s.default))}
      </p>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {save.error && <p className="mr-auto text-destructive">{save.error.message}</p>}
        <Button variant="ghost" onClick={() => setValue(pct(s.default))} disabled={active || value === pct(s.default)}>
          <RotateCcw />
          {t.sourceSound.reset}
        </Button>
        <Button onClick={() => save.mutate()} disabled={active || save.isPending || !dirty}>
          {save.isPending ? <Loader2 className="animate-spin" /> : <Clapperboard />}
          {t.sourceSound.save}
        </Button>
      </div>
    </Panel>
  );
}
