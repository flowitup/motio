import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Loader2, RefreshCw, RotateCcw } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { ExternalA } from "@/components/external-link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useApi, type Api, type Settings } from "@/lib/api";
import { inTauri, openExternal, useEngine, type EngineConfig } from "@/lib/engine";
import { useUpdater } from "@/lib/updater";
import { t } from "@/i18n";

type Draft = Record<string, string | boolean>;

function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Choice({
  value,
  onChange,
  options,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
  className?: string;
}) {
  return (
    <Select value={value} onValueChange={(v) => v != null && onChange(v)}>
      <SelectTrigger className={className ?? "w-full"}>
        <SelectValue>{(v: string) => options.find(([k]) => k === v)?.[1] ?? v}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        {options.map(([k, label]) => (
          <SelectItem key={k} value={k}>
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function EngineCard() {
  const { info, getConfig, setConfig, restart } = useEngine();
  const [cfg, setCfg] = useState<EngineConfig | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    getConfig().then(setCfg);
  }, [getConfig]);
  if (!cfg) return null;

  const apply = async () => {
    setBusy(true);
    try {
      await setConfig(cfg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.settings.engine}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <Field label={t.settings.engineMode}>
          <Choice
            value={cfg.mode}
            onChange={(mode) => setCfg({ ...cfg, mode: mode as EngineConfig["mode"] })}
            options={[
              ["local", t.engine.local],
              ["remote", t.engine.remote],
            ]}
          />
        </Field>
        {cfg.mode === "remote" && (
          <>
            <Field label={t.settings.engineUrl}>
              <Input
                value={cfg.url}
                placeholder="http://100.x.y.z:8765"
                onChange={(e) => setCfg({ ...cfg, url: e.target.value })}
              />
            </Field>
            <Field label={t.settings.engineToken}>
              <Input type="password" value={cfg.token} onChange={(e) => setCfg({ ...cfg, token: e.target.value })} />
            </Field>
          </>
        )}
        <div className="flex items-center gap-2">
          <Button onClick={apply} disabled={busy || !inTauri}>
            {busy && <Loader2 className="animate-spin" />}
            {t.settings.applyEngine}
          </Button>
          {info.mode === "local" && inTauri && (
            <Button variant="outline" onClick={restart}>
              <RotateCcw />
              {t.engine.retry}
            </Button>
          )}
          <span className="text-sm text-muted-foreground">
            {info.status === "ready" ? `${t.engine.ready} · ${info.url}` : (info.error ?? t.engine.starting)}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function UpdateCard() {
  const u = useUpdater();
  const [token, setToken] = useState("");
  const [saving, setSaving] = useState(false);
  if (!inTauri) return null;

  const saveToken = async (value: string) => {
    setSaving(true);
    try {
      await u.setToken(value);
      setToken("");
    } finally {
      setSaving(false);
    }
  };
  const busy = u.checking || u.progress != null;
  const r = u.result;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.update.title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm">
            {t.update.current} <span className="font-medium">{u.current}</span>
          </span>
          <Button variant="outline" onClick={u.check} disabled={busy}>
            {u.checking ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {t.update.check}
          </Button>
          {r && !r.version && !u.checking && <span className="text-sm text-muted-foreground">{t.update.upToDate}</span>}
        </div>

        {r?.version && (
          <div className="grid gap-3 rounded-lg border p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium">{t.update.available(r.version)}</span>
              {r.url && (
                <Button variant="link" size="sm" onClick={() => openExternal(r.url!)}>
                  {t.update.releasePage}
                </Button>
              )}
            </div>
            {r.notes && (
              <pre className="max-h-48 overflow-y-auto font-sans text-xs whitespace-pre-wrap text-muted-foreground">
                {r.notes}
              </pre>
            )}
            {u.progress != null ? (
              <div className="grid gap-1.5">
                <span className="text-sm text-muted-foreground">
                  {t.update.downloading} {u.progress > 0 && `${u.progress}%`}
                </span>
                <Progress value={u.progress} />
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button onClick={u.install} disabled={busy}>
                  <Download />
                  {t.update.install}
                </Button>
                <span className="text-xs text-muted-foreground">{t.update.restartHint}</span>
              </div>
            )}
          </div>
        )}

        {u.error && <p className="text-sm text-destructive">{u.error}</p>}

        <Field
          label={t.update.token}
          hint={
            <>
              {t.update.tokenHint}{" "}
              <ExternalA href="https://github.com/settings/personal-access-tokens/new" className="underline">
                {t.update.createToken}
              </ExternalA>
            </>
          }
        >
          <div className="flex gap-2">
            <Input
              type="password"
              value={token}
              placeholder={u.hasToken ? t.update.tokenSaved : "github_pat_…"}
              onChange={(e) => setToken(e.target.value)}
            />
            <Button variant="outline" onClick={() => saveToken(token)} disabled={!token.trim() || saving}>
              {t.settings.save}
            </Button>
            {u.hasToken && (
              <Button variant="ghost" onClick={() => saveToken("")} disabled={saving}>
                {t.update.clearToken}
              </Button>
            )}
          </div>
        </Field>
      </CardContent>
    </Card>
  );
}

function HealthCard({ api }: { api: Api }) {
  const { data: h, error } = useQuery({ queryKey: ["health"], queryFn: () => api.health(), refetchInterval: 30_000 });
  if (error) return <p className="text-sm text-destructive">{error.message}</p>;
  if (!h) return null;
  const rows: [string, ReactNode][] = [
    [t.settings.version, h.version],
    [t.settings.platform, `${h.platform.system} ${h.platform.machine} · Python ${h.platform.python}`],
    ["LLM", `${h.providers.llm.provider} · ${h.providers.llm.model}`],
    ["TTS", h.providers.tts ?? <span className="text-destructive">{t.settings.none}</span>],
    ["ASR", `${h.providers.asr.engine} · ${h.providers.asr.model}`],
    ["ffmpeg", h.ffmpeg ?? <span className="text-destructive">{t.settings.notFound}</span>],
    ["claude CLI", h.claude_cli ?? <span className="text-muted-foreground">{t.settings.notFound}</span>],
    ["Postiz", h.postiz ? "✓" : <span className="text-muted-foreground">{t.settings.none}</span>],
    [t.settings.quotaLeft, h.quota_left ?? t.settings.unlimited],
    ["data", h.data_dir],
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.settings.health}</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-sm">
          {rows.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="break-all">{v}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

function VoicePicker({ api, value, onChange, hasKey }: { api: Api; value: string; onChange: (v: string) => void; hasKey: boolean }) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["voices"],
    queryFn: () => api.voices(),
    enabled: hasKey,
    staleTime: 5 * 60_000,
  });
  if (!hasKey) return <p className="text-sm text-muted-foreground">{t.settings.voiceNeedKey}</p>;
  if (error) return <p className="text-sm text-destructive">{error.message}</p>;
  if (isLoading) return <Loader2 className="size-4 animate-spin" />;
  const options: [string, string][] = [
    ["", t.settings.voiceAuto],
    ...(data ?? []).map((v): [string, string] => [
      v.id,
      [v.name, v.labels.language, v.labels.accent, v.labels.gender].filter(Boolean).join(" · "),
    ]),
  ];
  return <Choice value={value} onChange={onChange} options={options} />;
}

function SettingsForm({ api }: { api: Api }) {
  const qc = useQueryClient();
  const { data: s, error } = useQuery({ queryKey: ["settings"], queryFn: () => api.settings() });
  const [draft, setDraft] = useState<Draft>({});
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () => api.saveSettings(draft),
    onSuccess: (next: Settings) => {
      qc.setQueryData(["settings"], next);
      qc.invalidateQueries({ queryKey: ["health"] });
      qc.invalidateQueries({ queryKey: ["voices"] });
      setDraft({});
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    },
  });

  if (error) return <p className="text-sm text-destructive">{error.message}</p>;
  if (!s) return null;

  const val = (k: string) => (k in draft ? String(draft[k]) : (s[k]?.value ?? ""));
  const bool = (k: string) => (k in draft ? draft[k] === true : ["1", "true", "yes", "on"].includes(val(k).toLowerCase()));
  const set = (k: string, v: string | boolean) => setDraft((d) => ({ ...d, [k]: v }));
  const text = (k: string, placeholder?: string) => (
    <Input value={val(k)} placeholder={placeholder} onChange={(e) => set(k, e.target.value)} />
  );
  const secret = (k: string) => (
    <Input
      type="password"
      value={k in draft ? String(draft[k]) : ""}
      placeholder={s[k]?.value || t.settings.keyPlaceholder}
      onChange={(e) => set(k, e.target.value)}
    />
  );
  const src = (k: string) =>
    s[k]?.source === "settings" ? t.settings.fromSettings : s[k]?.source === "env" ? t.settings.fromEnv : undefined;
  const dirty = Object.keys(draft).length > 0;
  const hasElKey = !!s.ELEVENLABS_API_KEY?.value && draft.ELEVENLABS_API_KEY !== "";

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t.settings.llm}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label={t.settings.provider} hint={src("LLM_PROVIDER")}>
            <Choice
              value={val("LLM_PROVIDER") || "claude_cli"}
              onChange={(v) => set("LLM_PROVIDER", v)}
              options={[
                ["claude_cli", "Claude Code (claude -p)"],
                ["anthropic", "Anthropic API"],
              ]}
            />
          </Field>
          <Field label={t.settings.model} hint={src("LLM_MODEL")}>
            {text("LLM_MODEL", "sonnet")}
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.settings.keys}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="ANTHROPIC_API_KEY" hint={src("ANTHROPIC_API_KEY")}>
            {secret("ANTHROPIC_API_KEY")}
          </Field>
          <Field label="ELEVENLABS_API_KEY" hint={src("ELEVENLABS_API_KEY")}>
            {secret("ELEVENLABS_API_KEY")}
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.settings.voice}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Voice">
            <VoicePicker
              api={api}
              hasKey={hasElKey}
              value={val("ELEVENLABS_VOICE_ID")}
              onChange={(v) => set("ELEVENLABS_VOICE_ID", v)}
            />
          </Field>
          <Field label={t.settings.ttsModel} hint={src("ELEVENLABS_MODEL")}>
            {text("ELEVENLABS_MODEL", "eleven_multilingual_v2")}
          </Field>
          <Field label={t.settings.whisper} hint={src("WHISPER_MODEL")}>
            {text("WHISPER_MODEL")}
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.settings.postiz}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label={t.settings.postizUrl} hint={src("POSTIZ_URL") ?? t.settings.postizHint}>
            {text("POSTIZ_URL", "https://postiz.example.com/api")}
          </Field>
          <Field label="POSTIZ_API_KEY" hint={src("POSTIZ_API_KEY")}>
            {secret("POSTIZ_API_KEY")}
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.settings.content}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <label className="flex items-center justify-between gap-4">
            <span className="text-sm">{t.settings.creditOnVideo}</span>
            <Switch checked={bool("CREDIT_ON_VIDEO")} onCheckedChange={(v) => set("CREDIT_ON_VIDEO", v)} />
          </label>
          <label className="flex items-center justify-between gap-4">
            <span className="text-sm">{t.settings.creditInPost}</span>
            <Switch checked={bool("CREDIT_IN_POST")} onCheckedChange={(v) => set("CREDIT_IN_POST", v)} />
          </label>
          <Field label={t.settings.maxPerDay}>
            <Input
              type="number"
              min={0}
              className="w-32"
              value={val("MAX_VIDEOS_PER_DAY") || "0"}
              onChange={(e) => set("MAX_VIDEOS_PER_DAY", e.target.value)}
            />
          </Field>
          <Field label={t.settings.newsSources} hint={src("NEWS_SOURCES")}>
            {text("NEWS_SOURCES", "douyin,weibo,baidu,bilibili-hot-search,toutiao,thepaper")}
          </Field>
        </CardContent>
      </Card>

      <div className="sticky bottom-0 flex items-center gap-3 border-t bg-background/90 py-3 backdrop-blur">
        <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
          {save.isPending ? <Loader2 className="animate-spin" /> : saved ? <Check /> : null}
          {saved ? t.settings.saved : t.settings.save}
        </Button>
        {save.error && <span className="text-sm text-destructive">{save.error.message}</span>}
      </div>
    </>
  );
}

export default function SettingsPage() {
  const api = useApi();
  return (
    <div className="mx-auto max-w-3xl space-y-5 p-6">
      <h1 className="text-2xl font-semibold tracking-tight">{t.settings.title}</h1>
      <EngineCard />
      <UpdateCard />
      {api && (
        <>
          <HealthCard api={api} />
          <SettingsForm api={api} />
        </>
      )}
    </div>
  );
}
