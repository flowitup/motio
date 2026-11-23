import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Clipboard, Copy, Film, Loader2, Pencil, Plus, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Choice, Field } from "@/components/form";
import { SectionTabs } from "@/components/section-tabs";
import { Section } from "@/components/section";
import { PageTitle, TopBar } from "@/components/studio";
import { TemplatePreview, useTemplates } from "@/components/template-choice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { VoicePicker } from "@/components/voice-picker";
import { hasVoiceProvider, useApi, type Api, type Look, type TemplateInput, type VideoTemplate } from "@/lib/api";
import { useEngine } from "@/lib/engine";
import { t } from "@/i18n";

const FONTS = ["system", "poppins", "poppins_bold", "anton", "bebas", "archivo", "bangers", "lilita", "dmserif"];
const MAX_NOTE = 200;

function ColorField({ label, value, onChange, hint }: { label: string; value: string; onChange: (v: string) => void; hint?: string }) {
  return (
    <Field label={label} hint={hint}>
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={value || "#000000"}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          aria-label={label}
          className="h-9 w-12 cursor-pointer rounded-md border border-field bg-ground p-1"
        />
        <span className="font-mono text-xs text-muted-foreground">{value}</span>
      </div>
    </Field>
  );
}

/** A colour that can be switched off (empty = off). */
function OptionalColor({ label, value, onChange, fallback, hint }: { label: string; value: string; onChange: (v: string) => void; fallback: string; hint?: string }) {
  return (
    <div className="grid gap-1.5">
      <label className="flex items-center gap-2 text-sm font-medium">
        <Switch checked={!!value} onCheckedChange={(on) => onChange(on ? fallback : "")} aria-label={label} />
        {label}
      </label>
      {value && <ColorField label={t.templates.editor.color} value={value} onChange={onChange} hint={hint} />}
      {!value && hint && <p className="pl-11 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Slider({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) {
  return (
    <Field label={label}>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full" aria-label={label} />
    </Field>
  );
}

function Switched({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm font-medium">
      <Switch checked={checked} onCheckedChange={onChange} />
      {label}
    </label>
  );
}

const opts = (m: Record<string, string>): [string, string][] => Object.entries(m);

/** The template editor: every part of a look, with the engine's own picture of it beside the form. */
function Editor({ api, initial, onClose, saving, error, onSave }: { api: Api; initial: VideoTemplate | null; onClose: () => void; saving: boolean; error?: string; onSave: (body: TemplateInput) => void }) {
  const e = t.templates.editor;
  const { data: all } = useTemplates(api);
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: () => api.health(), staleTime: 30_000 });
  const start = initial ?? all?.find((x) => x.key === "b:classic");
  const [name, setName] = useState(initial?.name ?? "");
  const [note, setNote] = useState(initial?.note ?? "");
  const [look, setLook] = useState<Look>(() => structuredClone(start?.look as Look));
  const [voice, setVoice] = useState(initial?.voice_id ?? "");
  const [duration, setDuration] = useState(initial?.duration ? String(initial.duration) : "");
  const [vol, setVol] = useState<number | null>(initial?.src_volume ?? null);
  const c = look.caption;
  const ti = look.title;
  const setCap = <K extends keyof Look["caption"]>(k: K, v: Look["caption"][K]) => setLook((l) => ({ ...l, caption: { ...l.caption, [k]: v } }));
  const setTitle = <K extends keyof Look["title"]>(k: K, v: Look["title"][K]) => setLook((l) => ({ ...l, title: { ...l.title, [k]: v } }));
  const setFrame = <K extends keyof Look["frame"]>(k: K, v: Look["frame"][K]) => setLook((l) => ({ ...l, frame: { ...l.frame, [k]: v } }));
  const setMotion = <K extends keyof Look["motion"]>(k: K, v: Look["motion"][K]) => setLook((l) => ({ ...l, motion: { ...l.motion, [k]: v } }));

  // The picture is drawn by the engine; ask again a moment after the last change.
  const [shown, setShown] = useState<string | null>(initial?.preview ?? null);
  const [drawing, setDrawing] = useState(false);
  const seq = useRef(0);
  useEffect(() => {
    const mine = ++seq.current;
    const timer = setTimeout(() => {
      setDrawing(true);
      api
        .previewLook(look)
        .then((r) => mine === seq.current && setShown(r.preview))
        .catch(() => undefined)
        .finally(() => mine === seq.current && setDrawing(false));
    }, 250);
    return () => clearTimeout(timer);
  }, [api, look]);

  const body = (): TemplateInput => ({ name: name.trim(), note: note.trim(), look, voice_id: voice, duration: duration ? Number(duration) : null, src_volume: vol });
  return (
    <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
      <div className="grid gap-4">
        <Section title={initial ? e.titleEdit : e.titleNew} bodyClassName="grid gap-4">
          <div className="grid items-start gap-4 sm:grid-cols-2">
            <Field label={e.name}>
              <Input autoFocus value={name} maxLength={60} onChange={(ev) => setName(ev.target.value)} />
            </Field>
            <Field label={e.note}>
              <Textarea value={note} maxLength={MAX_NOTE} onChange={(ev) => setNote(ev.target.value)} className="min-h-9 text-sm" rows={2} />
            </Field>
          </div>
        </Section>

        <Section title={e.caption} collapsible bodyClassName="grid gap-4">
          <div className="grid items-start gap-4 sm:grid-cols-3">
            <Field label={e.font}>
              <Choice value={c.font} onChange={(v) => setCap("font", v)} options={FONTS.map((f): [string, string] => [f, t.templates.fonts[f] ?? f])} />
            </Field>
            <Field label={e.pos}>
              <Choice value={c.pos} onChange={(v) => setCap("pos", v as Look["caption"]["pos"])} options={opts(e.positions)} />
            </Field>
            <Slider label={e.size(c.size)} value={c.size} min={36} max={100} step={2} onChange={(v) => setCap("size", v)} />
          </div>
          <div className="grid items-start gap-4 sm:grid-cols-4">
            <ColorField label={e.color} value={c.color} onChange={(v) => setCap("color", v)} />
            <ColorField label={e.spoken} value={c.spoken} onChange={(v) => setCap("spoken", v)} />
            <ColorField label={e.stroke} value={c.stroke} onChange={(v) => setCap("stroke", v)} />
            <Slider label={e.strokeW(c.stroke_w)} value={c.stroke_w} min={0} max={12} step={1} onChange={(v) => setCap("stroke_w", v)} />
          </div>
          <div className="grid items-start gap-4 sm:grid-cols-2">
            <OptionalColor label={e.active} value={c.active} onChange={(v) => setCap("active", v)} fallback="#FFFFFF" hint={e.activeHint} />
            <OptionalColor label={e.activeBox} value={c.active_box} onChange={(v) => setCap("active_box", v)} fallback="#F76F00" />
            <OptionalColor label={e.glow} value={c.glow} onChange={(v) => setCap("glow", v)} fallback="#00C8FF" />
            <Slider label={e.pop(Math.round(c.pop * 100))} value={Math.round(c.pop * 100)} min={0} max={40} step={5} onChange={(v) => setCap("pop", v / 100)} />
          </div>
          <div className="grid items-start gap-4 sm:grid-cols-3">
            <Field label={e.box}>
              <Choice value={c.box} onChange={(v) => setCap("box", v as Look["caption"]["box"])} options={opts(e.boxes)} />
            </Field>
            {c.box !== "none" && <ColorField label={e.boxColor} value={c.box_color} onChange={(v) => setCap("box_color", v)} />}
            {c.box !== "none" && <Slider label={e.boxAlpha(Math.round(c.box_alpha * 100))} value={Math.round(c.box_alpha * 100)} min={0} max={100} step={5} onChange={(v) => setCap("box_alpha", v / 100)} />}
          </div>
          <Switched label={e.upper} checked={c.upper} onChange={(v) => setCap("upper", v)} />
        </Section>

        <Section title={e.titleBand} collapsible defaultOpen={false} bodyClassName="grid gap-4">
          <Switched label={e.showTitle} checked={ti.show} onChange={(v) => setTitle("show", v)} />
          {ti.show && (
            <>
              <div className="grid items-start gap-4 sm:grid-cols-3">
                <Field label={e.font}>
                  <Choice value={ti.font} onChange={(v) => setTitle("font", v)} options={FONTS.map((f): [string, string] => [f, t.templates.fonts[f] ?? f])} />
                </Field>
                <Field label={e.pos}>
                  <Choice value={ti.pos} onChange={(v) => setTitle("pos", v as Look["title"]["pos"])} options={opts(e.titlePos)} />
                </Field>
                <Field label={e.align}>
                  <Choice value={ti.align} onChange={(v) => setTitle("align", v as Look["title"]["align"])} options={opts(e.aligns)} />
                </Field>
              </div>
              <div className="grid items-start gap-4 sm:grid-cols-4">
                <ColorField label={e.color} value={ti.color} onChange={(v) => setTitle("color", v)} />
                <ColorField label={e.bar} value={ti.bar} onChange={(v) => setTitle("bar", v)} />
                <ColorField label={e.badge} value={ti.badge} onChange={(v) => setTitle("badge", v)} />
                <Slider label={e.barAlpha(Math.round(ti.bar_alpha * 100))} value={Math.round(ti.bar_alpha * 100)} min={0} max={100} step={5} onChange={(v) => setTitle("bar_alpha", v / 100)} />
              </div>
              <div className="grid items-start gap-4 sm:grid-cols-2">
                <OptionalColor label={e.accent} value={ti.accent} onChange={(v) => setTitle("accent", v)} fallback="#FFD60A" hint={e.accentHint} />
                <Switched label={e.upper} checked={ti.upper} onChange={(v) => setTitle("upper", v)} />
              </div>
            </>
          )}
        </Section>

        <Section title={e.frame} collapsible defaultOpen={false} bodyClassName="grid gap-4">
          <div className="grid items-start gap-4 sm:grid-cols-3">
            <Slider label={e.blur(look.frame.blur)} value={look.frame.blur} min={0} max={80} step={2} onChange={(v) => setFrame("blur", v)} />
            <Slider label={e.dim(Math.round(look.frame.dim * 100))} value={Math.round(look.frame.dim * 100)} min={0} max={80} step={5} onChange={(v) => setFrame("dim", v / 100)} />
            <OptionalColor label={e.flat} value={look.frame.color} onChange={(v) => setFrame("color", v)} fallback="#0F1115" />
          </div>
        </Section>

        <Section title={e.camera} collapsible defaultOpen={false} bodyClassName="grid gap-4">
          <div className="grid items-start gap-4 sm:grid-cols-2">
            <Field label={e.camera}>
              <Choice value={look.motion.mode} onChange={(v) => setMotion("mode", v as Look["motion"]["mode"])} options={opts(e.modes)} />
            </Field>
            <Slider label={e.zoom(Math.round(look.motion.zoom * 100))} value={Math.round(look.motion.zoom * 100)} min={0} max={40} step={2} onChange={(v) => setMotion("zoom", v / 100)} />
          </div>
        </Section>

        <Section title={e.defaults} collapsible defaultOpen={!!(initial && (initial.voice_id || initial.duration || initial.src_volume != null))} bodyClassName="grid gap-4">
          <p className="text-xs text-muted-foreground">{e.defaultsHint}</p>
          <div className="grid items-start gap-4 sm:grid-cols-3">
            <Field label={e.voice}>
              <VoicePicker api={api} value={voice} onChange={setVoice} hasKey={hasVoiceProvider(health)} autoLabel={e.anyVoice} />
            </Field>
            <Field label={e.duration}>
              <Choice value={duration} onChange={setDuration} options={[["", e.anyDuration], ...["70", "80", "90"].map((x): [string, string] => [x, t.projects.durations[x]])]} />
            </Field>
            <div className="grid gap-2">
              <Switched label={e.srcOff} checked={vol == null} onChange={(on) => setVol(on ? null : 0.1)} />
              {vol != null && <Slider label={e.srcVolume(Math.round(vol * 100))} value={Math.round(vol * 100)} min={0} max={100} step={5} onChange={(v) => setVol(v / 100)} />}
            </div>
          </div>
        </Section>

        <div className="flex flex-wrap items-center justify-end gap-2">
          {error && <p role="alert" className="mr-auto text-sm text-destructive">{error}</p>}
          <Button variant="ghost" onClick={onClose}>{e.cancel}</Button>
          <Button onClick={() => onSave(body())} disabled={saving || !name.trim()}>
            {saving ? <Loader2 className="animate-spin" /> : <Check />}
            {e.save}
          </Button>
        </div>
      </div>

      <div className="sticky top-4 grid gap-2">
        <div className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{e.preview}</div>
        <div className="relative">
          {shown ? <TemplatePreview api={api} tpl={{ preview: shown, name: name || e.preview }} className="w-full" /> : <div className="aspect-[9/16] rounded-md border bg-muted" />}
          {drawing && <Loader2 className="absolute top-2 right-2 size-4 animate-spin text-white drop-shadow" />}
        </div>
        <p className="text-xs text-muted-foreground">{e.previewHint}</p>
      </div>
    </div>
  );
}

function TemplateCard({ api, tpl, onEdit, onDuplicate, onDelete, onUse }: { api: Api; tpl: VideoTemplate; onEdit: () => void; onDuplicate: () => void; onDelete: () => void; onUse: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = useMutation({
    mutationFn: async () => {
      const json = JSON.stringify(await api.exportTemplate(tpl.key), null, 2);
      await navigator.clipboard.writeText(json);
    },
    onSuccess: () => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    },
  });
  const a = (icon: ReactNode, label: string, fn: () => void, extra?: string) => (
    <Button variant="ghost" size="sm" onClick={fn} title={label} aria-label={label} className={extra}>
      {icon}
      <span className="sr-only sm:not-sr-only">{label}</span>
    </Button>
  );
  return (
    <Card className="overflow-hidden">
      <CardContent className="flex gap-4 p-4">
        <TemplatePreview api={api} tpl={tpl} className="w-[112px] shrink-0" />
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold">{tpl.name}</h3>
            {tpl.builtin && <Badge variant="secondary">{t.templates.starter}</Badge>}
          </div>
          <p className="text-[13px] leading-5 text-muted-foreground">{tpl.note}</p>
          {tpl.credit && <p className="text-xs leading-[18px] text-muted-foreground/80">{t.templates.credit(tpl.credit)}</p>}
          <div className="mt-auto flex flex-wrap items-center gap-1 pt-1">
            <Button size="sm" onClick={onUse}>
              <Film />
              {t.templates.use}
            </Button>
            {a(<Copy />, t.templates.duplicate, onDuplicate)}
            {!tpl.builtin && a(<Pencil />, t.templates.edit, onEdit)}
            {a(copied ? <Check /> : <Clipboard />, copied ? t.templates.copied : t.templates.copyJson, () => copy.mutate())}
            {!tpl.builtin && a(<Trash2 />, t.templates.delete, onDelete, "text-destructive")}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ImportBox({ api, onDone }: { api: Api; onDone: () => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const run = useMutation({
    mutationFn: () => api.importTemplate(text),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      setText("");
      onDone();
    },
  });
  return (
    <Section title={t.templates.importTitle} bodyClassName="grid gap-3">
      <p className="text-xs text-muted-foreground">{t.templates.importHint}</p>
      <Textarea value={text} onChange={(e) => setText(e.target.value)} className="min-h-28 font-mono text-xs" spellCheck={false} aria-label={t.templates.importTitle} />
      <div className="flex items-center justify-end gap-2">
        {run.error && <p role="alert" className="mr-auto text-sm text-destructive">{run.error.message}</p>}
        <Button variant="ghost" onClick={onDone}>{t.templates.editor.cancel}</Button>
        <Button onClick={() => run.mutate()} disabled={!text.trim() || run.isPending}>
          {run.isPending ? <Loader2 className="animate-spin" /> : <Upload />}
          {t.templates.importDo}
        </Button>
      </div>
    </Section>
  );
}

export default function TemplatesPage() {
  const api = useApi()!;
  useEngine();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data, isLoading, error } = useTemplates(api);
  const [mode, setMode] = useState<{ kind: "list" } | { kind: "edit"; tpl: VideoTemplate | null; seed?: VideoTemplate } | { kind: "import" }>({ kind: "list" });
  const [doomed, setDoomed] = useState<VideoTemplate | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["templates"] });
  const list = useMemo(() => data ?? [], [data]);
  const starter = list.filter((x) => x.builtin);
  const mine = list.filter((x) => !x.builtin);

  const save = useMutation({
    mutationFn: (body: TemplateInput) => (mode.kind === "edit" && mode.tpl ? api.updateTemplate(mode.tpl.key, body) : api.createTemplate(body)),
    onSuccess: () => {
      refresh();
      setMode({ kind: "list" });
    },
  });
  const del = useMutation({
    mutationFn: (key: string) => api.deleteTemplate(key),
    onSuccess: () => {
      refresh();
      setDoomed(null);
    },
  });
  const duplicate = (tpl: VideoTemplate) => setMode({ kind: "edit", tpl: null, seed: { ...tpl, name: t.templates.copyOf(tpl.name) } });
  const card = (tpl: VideoTemplate) => (
    <TemplateCard
      key={tpl.key}
      api={api}
      tpl={tpl}
      onUse={() => navigate(`/projects/new?template=${encodeURIComponent(tpl.key)}`)}
      onEdit={() => setMode({ kind: "edit", tpl })}
      onDuplicate={() => duplicate(tpl)}
      onDelete={() => setDoomed(tpl)}
    />
  );

  return (
    <>
      <TopBar>
        <PageTitle>{t.nav.tools}</PageTitle>
        <SectionTabs section="tools" />
        {mode.kind === "list" && (
          <div className="ml-auto flex items-center gap-2">
            <Button variant="secondary" onClick={() => setMode({ kind: "import" })}>
              <Upload />
              {t.templates.importOpen}
            </Button>
            <Button onClick={() => setMode({ kind: "edit", tpl: null })}>
              <Plus />
              {t.templates.create}
            </Button>
          </div>
        )}
      </TopBar>
      <div className="space-y-5 p-6">
        {mode.kind === "edit" ? (
          <Editor key={mode.tpl?.key ?? `new:${mode.seed?.key ?? ""}`} api={api} initial={mode.tpl ?? (mode.seed ? { ...mode.seed, key: "" } : null)} onClose={() => setMode({ kind: "list" })} saving={save.isPending} error={save.error?.message} onSave={(b) => save.mutate(b)} />
        ) : mode.kind === "import" ? (
          <ImportBox api={api} onDone={() => setMode({ kind: "list" })} />
        ) : (
          <>
            <p className="max-w-3xl text-[13px] text-muted-foreground">{t.templates.hint}</p>
            {error && <p role="alert" className="text-sm text-destructive">{error.message}</p>}
            {isLoading && <Loader2 className="size-5 animate-spin text-muted-foreground" />}
            <section className="space-y-3">
              <h2 className="text-sm font-semibold">{t.templates.mine}</h2>
              {mine.length ? <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">{mine.map(card)}</div> : !isLoading && <p className="text-[13px] text-muted-foreground">{t.templates.mineEmpty}</p>}
            </section>
            <section className="space-y-3">
              <h2 className="text-sm font-semibold">{t.templates.starter}</h2>
              <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">{starter.map(card)}</div>
            </section>
          </>
        )}
      </div>
      <ConfirmDialog
        open={!!doomed}
        onOpenChange={(o) => !o && setDoomed(null)}
        title={doomed ? t.templates.deleteTitle(doomed.name) : ""}
        description={t.templates.deleteBody}
        confirmLabel={t.templates.delete}
        pending={del.isPending}
        error={del.error?.message}
        onConfirm={() => doomed && del.mutate(doomed.key)}
      />
    </>
  );
}
