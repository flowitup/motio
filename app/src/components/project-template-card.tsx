import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Loader2, Save } from "lucide-react";
import { useState } from "react";
import { Choice, Field } from "@/components/form";
import { Panel } from "@/components/studio";
import { TemplatePreview, useTemplates } from "@/components/template-choice";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Api, ProjectDetail } from "@/lib/api";
import { t } from "@/i18n";

/** How this video looks: pick another template (the video is rendered again with the voice it already has), or keep this
 * video's look, voice and source sound as a template of the owner's. */
export function ProjectTemplateCard({ api, p, active, onQueued }: { api: Api; p: ProjectDetail; active: boolean; onQueued: () => void }) {
  const qc = useQueryClient();
  const { data } = useTemplates(api);
  const list = data ?? [];
  const now = p.template?.template ?? null;
  const [key, setKey] = useState(now?.key ?? "b:classic");
  const [name, setName] = useState("");
  const [saved, setSaved] = useState("");
  const apply = useMutation({
    mutationFn: () => api.setProjectTemplate(p.id, key === "none" ? null : key),
    onSuccess: onQueued,
  });
  const save = useMutation({
    mutationFn: () => api.saveProjectTemplate(p.id, name.trim()),
    onSuccess: (tpl) => {
      setSaved(tpl.name);
      setName("");
      qc.invalidateQueries({ queryKey: ["templates"] });
    },
  });
  const shown = list.find((x) => x.key === key);
  const dirty = key !== (now?.key ?? "none");
  return (
    <Panel title={t.templates.project.title} bodyClassName="grid gap-3 text-[13px]">
      <p className="text-xs leading-[18px] text-muted-foreground">{t.templates.project.hint}</p>
      <div className="flex items-start gap-4">
        {shown && <TemplatePreview api={api} tpl={shown} className="w-[72px] shrink-0" />}
        <div className="grid min-w-0 flex-1 content-start gap-2">
          <Choice
            value={key}
            onChange={setKey}
            options={[["none", t.templates.picker.none], ...list.map((x): [string, string] => [x.key, x.name])]}
            label={t.templates.picker.label}
            className="h-10 w-full max-w-[300px]"
          />
          <p className="text-xs text-muted-foreground">{now ? t.templates.project.current(now.name) : t.templates.project.classic}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {apply.error && <p className="mr-auto text-destructive">{apply.error.message}</p>}
        <Button onClick={() => apply.mutate()} disabled={active || apply.isPending || !dirty}>
          {apply.isPending ? <Loader2 className="animate-spin" /> : <Clapperboard />}
          {t.templates.project.apply}
        </Button>
      </div>
      <div className="grid gap-2 border-t pt-3">
        <p className="text-xs font-semibold">{t.templates.project.saveTitle}</p>
        <p className="text-xs leading-[18px] text-muted-foreground">{t.templates.project.saveHint}</p>
        <Field label={t.templates.project.saveName}>
          <Input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
        </Field>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {save.error && <p className="mr-auto text-destructive">{save.error.message}</p>}
          {saved && !save.error && <p className="mr-auto text-muted-foreground">{t.templates.project.saved(saved)}</p>}
          <Button variant="outline" onClick={() => save.mutate()} disabled={save.isPending || !name.trim()}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <Save />}
            {t.templates.project.save}
          </Button>
        </div>
      </div>
    </Panel>
  );
}
