import { useMutation } from "@tanstack/react-query";
import { Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";
import { clock, parseClock } from "@/components/dub-cards";
import { Choice, Field } from "@/components/form";
import { Panel } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import type { Api, ClipCaptions, ClipCrop, ProjectDetail } from "@/lib/api";
import { t } from "@/i18n";

/** A clip project (cut from a long video): its part of the source, the hook on top, the captions and the 9:16 frame. Saving renders again from the right step. */
export function ClipEditCard({ api, p, active, onQueued }: { api: Api; p: ProjectDetail; active: boolean; onQueued: () => void }) {
  const c = p.clip!;
  const [from, setFrom] = useState(clock(c.start));
  const [to, setTo] = useState(clock(c.end));
  const [hook, setHook] = useState(c.hook ?? "");
  const [captions, setCaptions] = useState<ClipCaptions>(c.captions);
  const [crop, setCrop] = useState<ClipCrop>(c.crop);
  const start = parseClock(from);
  const end = parseClock(to);
  const bad = start == null || end == null || Number.isNaN(start) || Number.isNaN(end);
  const fixed = crop.x.length <= 1;
  const save = useMutation({
    mutationFn: async () => {
      const r = await api.setClip(p.id, { start: start!, end: end!, hook, crop, captions });
      if (r.rerun) await api.retry(p.id, r.rerun);
      return r;
    },
    onSuccess: onQueued,
  });
  const dirty = !bad && (start !== c.start || end !== c.end || hook !== (c.hook ?? "") || captions !== c.captions || JSON.stringify(crop) !== JSON.stringify(c.crop));
  return (
    <Panel title={t.clipper.cardTitle} aside={`${clock(c.start)} → ${clock(c.end)}`}>
      <div className="grid gap-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label={t.clipper.start}>
            <Input value={from} onChange={(e) => setFrom(e.target.value)} className="font-mono" inputMode="numeric" />
          </Field>
          <Field label={t.clipper.end}>
            <Input value={to} onChange={(e) => setTo(e.target.value)} className="font-mono" inputMode="numeric" />
          </Field>
        </div>
        {bad && <p className="text-xs text-coral">{t.dub.badTime}</p>}
        <Field label={t.clipper.hook} hint={c.hook_auto && !hook ? t.clipper.hookAuto : undefined}>
          <Input value={hook} onChange={(e) => setHook(e.target.value.slice(0, 80))} placeholder={t.clipper.hookPlaceholder} />
        </Field>
        <Field label={t.clipper.captions}>
          <Choice
            value={captions}
            onChange={(v) => setCaptions(v as ClipCaptions)}
            options={[
              ["fr", t.clipper.captionOptions.fr],
              ["source", t.clipper.captionOptions.source],
              ["off", t.clipper.captionOptions.off],
            ]}
          />
        </Field>
        <label className="flex min-h-9 items-center gap-3 text-[13px]" title={t.clipper.fitHint}>
          <Switch checked={crop.fit} onCheckedChange={(fit) => setCrop({ ...crop, fit })} />
          {t.clipper.fit}
        </label>
        {!crop.fit &&
          (fixed ? (
            <Field label={t.clipper.cropPosition(Math.round((crop.x[0]?.[1] ?? 0.5) * 100))}>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round((crop.x[0]?.[1] ?? 0.5) * 100)}
                onChange={(e) => setCrop({ ...crop, x: [[0, Number(e.target.value) / 100]] })}
                className="w-full accent-cyan"
              />
            </Field>
          ) : (
            <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
              <span>{t.clipper.moving(crop.x.length)}</span>
              <Button size="sm" variant="secondary" onClick={() => setCrop({ ...crop, x: [[0, crop.x[0][1]]] })}>
                {t.clipper.fixFrame}
              </Button>
            </div>
          ))}
        <div className="flex items-center gap-3">
          <Button onClick={() => save.mutate()} disabled={active || !dirty || save.isPending}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />}
            {t.clipper.saveRender}
          </Button>
          {save.error && <p className="text-[13px] text-coral">{save.error.message}</p>}
        </div>
      </div>
    </Panel>
  );
}
