import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2, Pencil, Plus, Save, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Choice, Field } from "@/components/form";
import { Section } from "@/components/section";
import { Badge } from "@/components/ui/badge";
import { PageTitle, Segmented, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { VoicePicker } from "@/components/voice-picker";
import { useUnsavedGuard } from "@/hooks/use-unsaved-guard";
import { ApiError, useApi, type Api, type Channel, type ChannelInput, type SendMode } from "@/lib/api";
import { t } from "@/i18n";

const MODES: SendMode[] = ["draft", "schedule", "now"];
const BLANK: ChannelInput = {
  name: "",
  badge: "",
  style: "",
  glossary: "",
  voice_id: "",
  dub_voices: [],
  duration: 80,
  hashtags: [],
  gate_script: true,
  gate_video: true,
  postiz: [],
  send_mode: "draft",
  send_times: [],
  wide_postiz: [],
  auto_score: 0,
  auto_daily: 2,
  ai_clips: 0,
  series: "",
  cast: "",
  default: false,
};
const AUTO_SCORE = 85; // điểm gợi ý khi bật tự làm

/** Hồ sơ đang sửa; hashtag và giờ đăng giữ dạng chữ để gõ thoải mái, tách khi lưu. */
type Draft = Omit<ChannelInput, "hashtags" | "send_times"> & { hashtags: string; send_times: string };

// An older remote engine may send profiles without the newer fields: fill them from BLANK.
const toDraft = (x: ChannelInput): Draft => {
  const c = { ...BLANK, ...x };
  return { ...c, hashtags: c.hashtags.join(" "), send_times: c.send_times.join(" ") };
};
const words = (s: string) => s.split(/[\s,]+/).filter(Boolean);
const fromDraft = (d: Draft): ChannelInput => ({ ...d, hashtags: words(d.hashtags), send_times: words(d.send_times) });

/** A whole number that can be cleared while typing: the value is clamped into min..max once it is a number, and the text is tidied on blur. */
function NumberBox({ value, onChange, min, max, className }: { value: number; onChange: (v: number) => void; min: number; max: number; className?: string }) {
  const [text, setText] = useState(String(value));
  useEffect(() => {
    setText((x) => (Number(x) === value ? x : String(value)));
  }, [value]);
  return (
    <Input
      type="number"
      min={min}
      max={max}
      className={className}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        const n = Number(e.target.value);
        if (e.target.value !== "" && Number.isFinite(n)) onChange(Math.min(max, Math.max(min, Math.round(n))));
      }}
      onBlur={() => setText(String(value))}
    />
  );
}

function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint: string }) {
  return (
    <div className="grid gap-1">
      <label className="flex items-center gap-2 text-sm font-medium">
        <Switch checked={checked} onCheckedChange={onChange} />
        {label}
      </label>
      <p className="pl-11 text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

/** Kênh Postiz để tự gửi (và kênh nào nhận bản 16:9): danh sách chọn, hoặc lời nhắc khi Postiz chưa kết nối. */
function PostizPicker({
  api,
  value,
  onChange,
  wide,
  onWide,
}: {
  api: Api;
  value: string[];
  onChange: (v: string[]) => void;
  wide: string[];
  onWide: (v: string[]) => void;
}) {
  const { data, error } = useQuery({
    queryKey: ["postiz-channels"],
    queryFn: () => api.postizChannels(),
    retry: false,
    staleTime: 60_000,
  });
  if (error)
    return error instanceof ApiError && error.status === 409 ? (
      <p className="text-sm text-muted-foreground">
        {t.publish.notConfigured}{" "}
        <Link to="/settings" className="underline">
          {t.nav.settings}
        </Link>
      </p>
    ) : (
      <p role="alert" className="text-sm text-destructive">{error.message}</p>
    );
  if (!data) return <Loader2 className="size-4 animate-spin" />;
  if (!data.length) return <p className="text-sm text-muted-foreground">{t.publish.noChannels}</p>;
  const known = new Set(data.map((c) => c.id));
  const toggle = (id: string) => {
    if (value.includes(id)) {
      onChange(value.filter((x) => x !== id));
      onWide(wide.filter((x) => x !== id));
    } else onChange([...value, id]);
  };
  return (
    <div className="grid gap-1.5">
      {data.map((c) => (
        <div key={c.id} className="flex items-center gap-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              className="size-4 accent-primary"
              checked={value.includes(c.id)}
              disabled={c.disabled}
              onChange={() => toggle(c.id)}
            />
            <span>{c.name}</span>
            <span className="text-muted-foreground">· {c.provider}</span>
          </label>
          {value.includes(c.id) && (
            <label className="ml-2 flex items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                className="size-3.5 accent-primary"
                checked={wide.includes(c.id)}
                onChange={() => onWide(wide.includes(c.id) ? wide.filter((x) => x !== c.id) : [...wide, c.id])}
              />
              {t.channels.wide}
            </label>
          )}
        </div>
      ))}
      {value
        .filter((id) => !known.has(id))
        .map((id) => (
          <label key={id} className="flex items-center gap-2 text-sm text-muted-foreground">
            <input type="checkbox" className="size-4 accent-primary" checked onChange={() => toggle(id)} />
            {id}
          </label>
        ))}
    </div>
  );
}

/** The Auto refresh interval from Settings (minutes); null while unknown. */
function useRefreshMinutes(api: Api): number | null {
  const { data } = useQuery({ queryKey: ["settings"], queryFn: () => api.settings(), staleTime: 30_000 });
  const v = data?.REFRESH_EVERY_MIN?.value;
  return data ? Number(v || 0) || 0 : null;
}

function ChannelForm({
  api,
  initial,
  copyOf,
  hasKey,
  first,
  onDone,
}: {
  api: Api;
  initial: Channel | null; // null = kênh mới
  copyOf?: Channel; // kênh mới tạo từ bản sao của kênh này
  hasKey: boolean;
  first?: boolean; // kênh đầu tiên: chọn sẵn làm mặc định
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const refreshMin = useRefreshMinutes(api);
  const start = useRef<Draft>(
    toDraft(
      initial ??
        (copyOf
          ? // A copy keeps the writing and the voices; it must not send to the same Postiz channels or auto-make on its own.
            { ...copyOf, name: t.channels.copyName(copyOf.name), default: false, postiz: [], wide_postiz: [], auto_score: 0 }
          : { ...BLANK, default: !!first }),
    ),
  );
  const [d, setD] = useState<Draft>(start.current);
  const [confirming, setConfirming] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
  const changed = JSON.stringify(d) !== JSON.stringify(start.current);
  const guard = useUnsavedGuard(changed);
  const save = useMutation({
    mutationFn: () => (initial ? api.updateChannel(initial.id, fromDraft(d)) : api.createChannel(fromDraft(d))),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channels"] });
      onDone();
    },
  });
  const del = useMutation({
    mutationFn: () => api.deleteChannel(initial!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channels"] });
      onDone();
    },
  });
  const summary = { ...BLANK, ...fromDraft(d) };

  return (
    <div className="space-y-3">
      <h2 className="text-base leading-6 font-semibold">{initial ? initial.name : copyOf ? t.channels.copyName(copyOf.name) : t.channels.add}</h2>
      {copyOf && <p className="text-[13px] text-muted-foreground">{t.channels.copyNote(copyOf.name)}</p>}

      <Section id="channel-identity" title={t.channels.groupIdentity} bodyClassName="grid gap-4">
        <div className="grid items-start gap-4 sm:grid-cols-2">
          <Field label={t.channels.name}>
            <Input autoFocus value={d.name} maxLength={60} onChange={(e) => set("name", e.target.value)} placeholder={t.channels.namePlaceholder} />
          </Field>
          <Field label={t.channels.badge} hint={t.channels.badgeHint}>
            <Input value={d.badge} maxLength={24} onChange={(e) => set("badge", e.target.value)} placeholder={t.channels.badgePlaceholder} />
          </Field>
        </div>
        <Toggle checked={d.default} onChange={(v) => set("default", v)} label={t.channels.isDefault} hint={t.channels.defaultHint} />
      </Section>

      <Section id="channel-voice" title={t.channels.groupVoice} collapsible bodyClassName="grid gap-4" aside={t.projects.durations[String(d.duration)]}>
        <Field label={t.channels.style} hint={t.channels.styleHint}>
          <Textarea
            value={d.style}
            maxLength={1500}
            onChange={(e) => set("style", e.target.value)}
            placeholder={t.channels.stylePlaceholder}
            className="min-h-24 text-sm"
          />
        </Field>
        <Field label={t.channels.glossary} hint={t.channels.glossaryHint}>
          <Textarea
            value={d.glossary}
            maxLength={2000}
            onChange={(e) => set("glossary", e.target.value)}
            placeholder={t.channels.glossaryPlaceholder}
            className="min-h-20 font-mono text-xs"
          />
        </Field>
        <div className="grid items-start gap-4 sm:grid-cols-[1fr_180px]">
          <Field label={t.channels.voice}>
            <VoicePicker api={api} value={d.voice_id} onChange={(v) => set("voice_id", v)} hasKey={hasKey} autoLabel={t.channels.voiceDefault} />
          </Field>
          <Field label={t.channels.duration} hint={t.channels.durationHint}>
            <Choice
              value={String(d.duration)}
              onChange={(v) => set("duration", Number(v))}
              options={["70", "80", "90"].map((x) => [x, t.projects.durations[x]])}
            />
          </Field>
        </div>
        <Field label={t.channels.dubVoices} hint={t.channels.dubVoicesHint}>
          <div className="grid gap-2 sm:grid-cols-3">
            {Array.from({ length: Math.min(d.dub_voices.length + 1, 3) }, (_, i) => (
              <VoicePicker
                key={i}
                api={api}
                value={d.dub_voices[i] ?? ""}
                onChange={(v) => {
                  const next = [...d.dub_voices];
                  next[i] = v;
                  set("dub_voices", next.filter(Boolean));
                }}
                hasKey={hasKey}
                autoLabel={t.channels.dubVoiceNone}
              />
            ))}
          </div>
        </Field>
        <Field label={t.channels.hashtags} hint={t.channels.hashtagsHint}>
          <Input value={d.hashtags} onChange={(e) => set("hashtags", e.target.value)} placeholder="#Chine #ActuChine" />
        </Field>
      </Section>

      <Section
        id="channel-approval"
        title={t.channels.groupApproval}
        collapsible
        defaultOpen={false}
        bodyClassName="grid gap-4"
        aside={[t.channels.summaryGates(summary.gate_script, summary.gate_video), t.channels.summaryPostiz(summary.postiz.length, t.channels.sendModes[summary.send_mode])].join(" · ")}
      >
        <div className="grid gap-3">
          <div className="text-[13px] font-medium">{t.channels.gates}</div>
          <Toggle checked={d.gate_script} onChange={(v) => set("gate_script", v)} label={t.channels.gateScript} hint={t.channels.gateScriptHint} />
          <Toggle checked={d.gate_video} onChange={(v) => set("gate_video", v)} label={t.channels.gateVideo} hint={t.channels.gateVideoHint} />
        </div>

        <div className="grid gap-3 border-t pt-4">
          <div className="grid gap-1">
            <div className="text-[13px] font-medium">{t.channels.postiz}</div>
            <p className="text-xs text-muted-foreground">{t.channels.postizHint}</p>
          </div>
          <PostizPicker
            api={api}
            value={d.postiz}
            onChange={(v) => set("postiz", v)}
            wide={d.wide_postiz}
            onWide={(v) => set("wide_postiz", v)}
          />
          {d.postiz.length > 0 && (
            <>
              <p className="text-xs text-muted-foreground">{t.channels.wideHint}</p>
              <div className="grid gap-1.5">
                <div className="text-[13px]">{t.channels.sendMode}</div>
                <Segmented
                  label={t.channels.sendMode}
                  value={d.send_mode}
                  onChange={(m) => set("send_mode", m)}
                  className="w-full max-w-md"
                  options={MODES.map((m) => ({ value: m, label: t.channels.sendModes[m] }))}
                />
                <p className="text-xs text-muted-foreground">{t.channels.sendModeHint[d.send_mode]}</p>
              </div>
              {d.send_mode === "schedule" && (
                <Field label={t.channels.sendTimes} hint={t.channels.sendTimesHint}>
                  <Input value={d.send_times} onChange={(e) => set("send_times", e.target.value)} placeholder={t.channels.sendTimesPlaceholder} className="w-60" />
                </Field>
              )}
            </>
          )}
        </div>
      </Section>

      <Section
        id="channel-auto"
        title={t.channels.groupAuto}
        collapsible
        defaultOpen={false}
        bodyClassName="grid gap-3"
        aside={d.auto_score ? t.channels.summaryAuto(d.auto_score, d.auto_daily) : t.channels.autoOff}
      >
        <Toggle
          checked={d.auto_score > 0}
          onChange={(v) => set("auto_score", v ? AUTO_SCORE : 0)}
          label={t.channels.auto}
          hint={t.channels.autoHint}
        />
        {d.auto_score > 0 && refreshMin === 0 && (
          <p role="status" className="ml-11 flex items-start gap-2 rounded-lg border border-amber/40 bg-amber/10 px-3 py-2 text-[13px]">
            <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-amber" />
            <span>
              {t.channels.autoNoRefresh}{" "}
              <Link to="/settings" className="underline">
                {t.channels.autoNoRefreshLink}
              </Link>
            </span>
          </p>
        )}
        {d.auto_score > 0 && (
          <div className="grid items-start gap-4 pl-11 sm:grid-cols-2">
            <Field label={t.channels.autoScore} hint={t.channels.autoScoreHint}>
              <NumberBox min={1} max={100} className="w-28" value={d.auto_score} onChange={(v) => set("auto_score", v)} />
            </Field>
            <Field label={t.channels.autoDaily} hint={t.channels.autoDailyHint}>
              <NumberBox min={1} max={20} className="w-28" value={d.auto_daily} onChange={(v) => set("auto_daily", v)} />
            </Field>
          </div>
        )}
      </Section>

      <Section
        id="channel-ai"
        title={t.channels.groupAi}
        collapsible
        defaultOpen={false}
        bodyClassName="grid gap-4"
        aside={[summary.ai_clips ? t.channels.summaryClips(summary.ai_clips) : "", summary.series.trim() || summary.cast.trim() ? t.channels.summarySeries(summary.cast.split("\n").filter((l) => l.trim()).length) : ""].filter(Boolean).join(" · ") || undefined}
      >
        <Field label={t.channels.aiClips} hint={t.channels.aiClipsHint}>
          <NumberBox min={0} max={6} className="w-28" value={d.ai_clips} onChange={(v) => set("ai_clips", v)} />
        </Field>
        <Field label={t.channels.series} hint={t.channels.seriesHint}>
          <Textarea
            value={d.series}
            maxLength={1500}
            onChange={(e) => set("series", e.target.value)}
            placeholder={t.channels.seriesPlaceholder}
            className="min-h-20 text-sm"
          />
        </Field>
        <Field label={t.channels.cast} hint={t.channels.castHint}>
          <Textarea
            value={d.cast}
            maxLength={2500}
            onChange={(e) => set("cast", e.target.value)}
            placeholder={t.channels.castPlaceholder}
            className="min-h-24 font-mono text-xs"
          />
        </Field>
      </Section>

      <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-2 rounded-lg border bg-ground px-4 py-3">
        {initial && (
          <Button variant="destructive" onClick={() => setConfirming(true)}>
            <Trash2 />
            {t.channels.delete}
          </Button>
        )}
        {save.error && (
          <p role="alert" className="text-sm text-destructive">
            {save.error.message}
          </p>
        )}
        {changed && !save.error && (
          <span role="status" className="text-[13px] text-muted-foreground">
            {t.channels.unsaved}
          </span>
        )}
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" onClick={() => (changed ? setDiscarding(true) : onDone())}>
            {t.channels.cancel}
          </Button>
          <Button onClick={() => save.mutate()} disabled={!d.name.trim() || save.isPending}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <Save />}
            {t.channels.save}
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={discarding}
        onOpenChange={setDiscarding}
        title={t.confirm.discardTitle}
        description={t.confirm.discardBody}
        confirmLabel={t.confirm.discard}
        onConfirm={onDone}
      />
      {initial && (
        <ConfirmDialog
          open={confirming}
          onOpenChange={setConfirming}
          title={t.channels.delete}
          description={t.channels.confirmDelete(initial.name)}
          confirmLabel={t.channels.delete}
          pending={del.isPending}
          error={del.error?.message}
          onConfirm={() => del.mutate()}
        />
      )}
      {guard}
    </div>
  );
}

function Summary({ c: raw }: { c: Channel }) {
  const c = { ...BLANK, ...raw };
  const bits = [
    t.channels.summaryGates(c.gate_script, c.gate_video),
    t.channels.summaryPostiz(c.postiz.length, t.channels.sendModes[c.send_mode]),
    c.wide_postiz.length ? t.channels.summaryWide(c.wide_postiz.length) : "",
    c.auto_score ? t.channels.summaryAuto(c.auto_score, c.auto_daily) : "",
    c.ai_clips ? t.channels.summaryClips(c.ai_clips) : "",
    c.series.trim() || c.cast.trim() ? t.channels.summarySeries(c.cast.split("\n").filter((l) => l.trim()).length) : "",
    t.projects.durations[String(c.duration)],
  ].filter(Boolean);
  return <div className="text-[13px] text-muted-foreground">{bits.join(" · ")}</div>;
}

export default function ChannelsPage() {
  const api = useApi()!;
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [copyOf, setCopyOf] = useState<Channel | null>(null);
  const [saved, setSaved] = useState(false);
  const { data, isLoading, error } = useQuery({ queryKey: ["channels"], queryFn: () => api.channels() });
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: () => api.health(), staleTime: 30_000 });
  const hasKey = health?.providers.tts === "elevenlabs";
  const done = () => {
    setEditing(null);
    setCopyOf(null);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  return (
    <>
      <TopBar>
        <PageTitle>{t.channels.title}</PageTitle>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <span role="status" className="flex items-center gap-1 text-[13px] text-muted-foreground">
            {saved && (
              <>
                <Check className="size-4 text-mint" />
                {t.channels.saved}
              </>
            )}
          </span>
          {editing === null && (
            <Button
              onClick={() => {
                setCopyOf(null);
                setEditing("new");
              }}
            >
              <Plus />
              {t.channels.add}
            </Button>
          )}
        </div>
      </TopBar>
      <div className="max-w-4xl space-y-5 p-6">
        <p className="text-[13px] text-muted-foreground">{t.channels.intro}</p>
        {error && <p role="alert" className="text-sm text-destructive">{error.message}</p>}
        {editing === "new" && <ChannelForm key={copyOf?.id ?? "new"} api={api} initial={null} copyOf={copyOf ?? undefined} hasKey={hasKey} first={!data?.length} onDone={done} />}
        {isLoading && <Skeleton className="h-24 w-full rounded-xl" />}
        {data?.length === 0 && editing !== "new" && <p className="py-12 text-center text-muted-foreground">{t.channels.empty}</p>}
        <div className="space-y-3">
          {data?.map((c) =>
            editing === c.id ? (
              <ChannelForm key={c.id} api={api} initial={c} hasKey={hasKey} onDone={done} />
            ) : (
              <div key={c.id} className="rounded-lg border bg-panel p-4">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{c.name}</span>
                      {c.badge && <span className="rounded-xs bg-[#C8102E] px-1.5 py-0.5 text-xs font-bold text-white">{c.badge}</span>}
                      {c.default && <Badge variant="secondary">{t.channels.defaultBadge}</Badge>}
                    </div>
                    <Summary c={c} />
                    {c.style && <p className="line-clamp-2 text-[13px]">{c.style}</p>}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setCopyOf(c);
                      setEditing("new");
                    }}
                    disabled={editing !== null}
                    aria-label={`${t.channels.duplicate}: ${c.name}`}
                  >
                    <Copy />
                    {t.channels.duplicate}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setEditing(c.id)} disabled={editing !== null} aria-label={`${t.channels.edit}: ${c.name}`}>
                    <Pencil />
                    {t.channels.edit}
                  </Button>
                </div>
              </div>
            ),
          )}
        </div>
      </div>
    </>
  );
}
