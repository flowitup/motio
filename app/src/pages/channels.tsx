import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Pencil, Plus, Save, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Choice, Field } from "@/components/form";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { PageTitle, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { VoicePicker } from "@/components/voice-picker";
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
      <p className="text-sm text-destructive">{error.message}</p>
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

function ChannelForm({
  api,
  initial,
  hasKey,
  first,
  onDone,
}: {
  api: Api;
  initial: Channel | null; // null = kênh mới
  hasKey: boolean;
  first?: boolean; // kênh đầu tiên: chọn sẵn làm mặc định
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [d, setD] = useState<Draft>(() => toDraft(initial ?? { ...BLANK, default: !!first }));
  const [confirming, setConfirming] = useState(false);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
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

  return (
    <Card>
      <CardHeader>
        <CardTitle>{initial ? initial.name : t.channels.add}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid items-start gap-4 sm:grid-cols-2">
          <Field label={t.channels.name}>
            <Input autoFocus value={d.name} maxLength={60} onChange={(e) => set("name", e.target.value)} placeholder={t.channels.namePlaceholder} />
          </Field>
          <Field label={t.channels.badge} hint={t.channels.badgeHint}>
            <Input value={d.badge} maxLength={24} onChange={(e) => set("badge", e.target.value)} placeholder={t.channels.badgePlaceholder} />
          </Field>
        </div>
        <Toggle checked={d.default} onChange={(v) => set("default", v)} label={t.channels.isDefault} hint={t.channels.defaultHint} />

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

        <div className="grid gap-3 border-t pt-4">
          <div className="text-sm font-medium">{t.channels.gates}</div>
          <Toggle checked={d.gate_script} onChange={(v) => set("gate_script", v)} label={t.channels.gateScript} hint={t.channels.gateScriptHint} />
          <Toggle checked={d.gate_video} onChange={(v) => set("gate_video", v)} label={t.channels.gateVideo} hint={t.channels.gateVideoHint} />
        </div>

        <div className="grid gap-3 border-t pt-4">
          <div className="grid gap-1">
            <div className="text-sm font-medium">{t.channels.postiz}</div>
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
                <div className="text-sm">{t.channels.sendMode}</div>
                <div className="flex flex-wrap gap-2">
                  {MODES.map((m) => (
                    <Button key={m} size="sm" variant={d.send_mode === m ? "default" : "outline"} onClick={() => set("send_mode", m)}>
                      {t.channels.sendModes[m]}
                    </Button>
                  ))}
                </div>
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

        <div className="grid gap-3 border-t pt-4">
          <Toggle
            checked={d.auto_score > 0}
            onChange={(v) => set("auto_score", v ? AUTO_SCORE : 0)}
            label={t.channels.auto}
            hint={t.channels.autoHint}
          />
          {d.auto_score > 0 && (
            <div className="grid items-start gap-4 pl-11 sm:grid-cols-2">
              <Field label={t.channels.autoScore} hint={t.channels.autoScoreHint}>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  className="w-28"
                  value={d.auto_score}
                  onChange={(e) => set("auto_score", Math.min(100, Math.max(1, Number(e.target.value) || 1)))}
                />
              </Field>
              <Field label={t.channels.autoDaily} hint={t.channels.autoDailyHint}>
                <Input
                  type="number"
                  min={1}
                  max={20}
                  className="w-28"
                  value={d.auto_daily}
                  onChange={(e) => set("auto_daily", Math.min(20, Math.max(1, Number(e.target.value) || 1)))}
                />
              </Field>
            </div>
          )}
        </div>

        <div className="grid gap-3 border-t pt-4">
          <Field label={t.channels.aiClips} hint={t.channels.aiClipsHint}>
            <Input
              type="number"
              min={0}
              max={6}
              className="w-28"
              value={d.ai_clips}
              onChange={(e) => set("ai_clips", Math.min(6, Math.max(0, Math.round(Number(e.target.value) || 0))))}
            />
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
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t pt-4">
          {initial && (
            <Button variant="outline" className="hover:text-destructive" onClick={() => setConfirming(true)}>
              <Trash2 />
              {t.channels.delete}
            </Button>
          )}
          {save.error && <p className="text-sm text-destructive">{save.error.message}</p>}
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={onDone}>
              {t.channels.cancel}
            </Button>
            <Button onClick={() => save.mutate()} disabled={!d.name.trim() || save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : <Save />}
              {t.channels.save}
            </Button>
          </div>
        </div>
      </CardContent>
      {initial && (
        <AlertDialog open={confirming} onOpenChange={setConfirming}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t.channels.delete}</AlertDialogTitle>
              <AlertDialogDescription>{t.channels.confirmDelete(initial.name)}</AlertDialogDescription>
            </AlertDialogHeader>
            {del.error && <p className="text-sm text-destructive">{del.error.message}</p>}
            <AlertDialogFooter>
              <AlertDialogCancel>{t.channels.cancel}</AlertDialogCancel>
              <Button variant="destructive" onClick={() => del.mutate()} disabled={del.isPending}>
                {del.isPending ? <Loader2 className="animate-spin" /> : <Trash2 />}
                {t.channels.delete}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </Card>
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
  return <div className="text-sm text-muted-foreground">{bits.join(" · ")}</div>;
}

export default function ChannelsPage() {
  const api = useApi()!;
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [saved, setSaved] = useState(false);
  const { data, isLoading, error } = useQuery({ queryKey: ["channels"], queryFn: () => api.channels() });
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: () => api.health(), staleTime: 30_000 });
  const hasKey = health?.providers.tts === "elevenlabs";
  const done = () => {
    setEditing(null);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  return (
    <>
      <TopBar>
        <PageTitle>{t.channels.title}</PageTitle>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          {saved && (
            <span className="flex items-center gap-1 text-sm text-muted-foreground">
              <Check className="size-4" />
              {t.channels.saved}
            </span>
          )}
          {editing === null && (
            <Button onClick={() => setEditing("new")}>
              <Plus />
              {t.channels.add}
            </Button>
          )}
        </div>
      </TopBar>
      <div className="mx-auto max-w-4xl space-y-5 p-6">
        <p className="text-sm text-muted-foreground">{t.channels.intro}</p>
        {error && <p className="text-sm text-destructive">{error.message}</p>}
        {editing === "new" && <ChannelForm api={api} initial={null} hasKey={hasKey} first={!data?.length} onDone={done} />}
        {isLoading && <Skeleton className="h-24 w-full rounded-xl" />}
        {data?.length === 0 && editing !== "new" && <p className="py-12 text-center text-muted-foreground">{t.channels.empty}</p>}
        <div className="space-y-3">
          {data?.map((c) =>
            editing === c.id ? (
              <ChannelForm key={c.id} api={api} initial={c} hasKey={hasKey} onDone={done} />
            ) : (
              <Card key={c.id} className="gap-2 p-4">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{c.name}</span>
                      {c.badge && <span className="rounded-xs bg-[#C8102E] px-1.5 py-0.5 text-xs font-bold text-white">{c.badge}</span>}
                      {c.default && <Badge variant="secondary">{t.channels.defaultBadge}</Badge>}
                    </div>
                    <Summary c={c} />
                    {c.style && <p className="line-clamp-2 text-sm">{c.style}</p>}
                  </div>
                  <Button variant="outline" size="sm" onClick={() => setEditing(c.id)} disabled={editing !== null}>
                    <Pencil />
                    {t.channels.edit}
                  </Button>
                </div>
              </Card>
            ),
          )}
        </div>
      </div>
    </>
  );
}
