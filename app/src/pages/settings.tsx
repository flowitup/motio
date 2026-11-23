import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Loader2, RefreshCw, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Choice, Field } from "@/components/form";
import { LogosCard } from "@/components/logos-card";
import { Section } from "@/components/section";
import { PageTitle, Segmented, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { VoicePicker } from "@/components/voice-picker";
import { ChannelsPanel } from "@/pages/channels";
import { StatsPanel } from "@/pages/stats";
import { useUnsavedGuard } from "@/hooks/use-unsaved-guard";
import { useApi, type Api, type Settings } from "@/lib/api";
import { inTauri, openExternal, useEngine, type EngineConfig } from "@/lib/engine";
import { DEFAULT_FAL_MODEL, FAL_MODELS, FAL_PICTURE_USD } from "@/lib/image-models";
import { useUpdater } from "@/lib/updater";
import { cn } from "@/lib/utils";
import { LANGS, setLang, t, useLang, type Lang } from "@/i18n";
import { setTheme, THEMES, useTheme, type Theme, FONTS, setFont, useFont, type Font } from "@/lib/theme";

type Draft = Record<string, string | boolean>;

/** The language also rebuilds every screen, so unsaved settings would be lost: ask first. */
function LanguageField({ unsaved }: { unsaved: number }) {
  const lang = useLang();
  const [next, setNext] = useState<Lang | null>(null);
  return (
    <>
      <Field label={t.settings.language} hint={t.settings.languageHint}>
        <Choice value={lang} onChange={(v) => (unsaved ? setNext(v as Lang) : setLang(v as Lang))} options={LANGS} className="w-48" />
      </Field>
      <ConfirmDialog
        open={next !== null}
        onOpenChange={(o) => !o && setNext(null)}
        title={t.confirm.langTitle}
        description={t.confirm.langBody(unsaved)}
        confirmLabel={t.confirm.langSwitch}
        destructive={false}
        onConfirm={() => next && setLang(next)}
      />
    </>
  );
}

/** The look of the app: switches at once, nothing is reloaded. */
function ThemeField() {
  const theme = useTheme();
  return (
    <Field label={t.settings.themeLabel} hint={t.settings.themeHints[theme]}>
      <Choice value={theme} onChange={(v) => setTheme(v as Theme)} options={THEMES.map((k) => [k, t.settings.themes[k]] as [string, string])} className="w-56" />
    </Field>
  );
}

function FontField() {
  const font = useFont();
  return (
    <Field label={t.settings.font} hint={t.settings.fontHints[font]}>
      <Choice value={font} onChange={(v) => setFont(v as Font)} options={FONTS.map((k) => [k, t.settings.fonts[k]] as [string, string])} className="w-56" />
    </Field>
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
    <Section id="engine" title={t.settings.engine} bodyClassName="grid gap-4">
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
            <p className="text-xs text-muted-foreground">{t.settings.engineRemoteHint}</p>
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
          <span role="status" className="text-sm text-muted-foreground">
            {info.status === "ready"
              ? `${t.engine.ready} · ${info.url}`
              : info.error
                ? t.native(info.error)
                : t.engine.starting}
          </span>
        </div>
    </Section>
  );
}

function UpdateCard() {
  const u = useUpdater();
  if (!inTauri) return null;

  const busy = u.checking || u.progress != null;
  const r = u.result;

  return (
    <Section id="update" title={t.update.title} bodyClassName="grid gap-4">
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

        {u.error && <p role="alert" className="text-sm text-destructive">{t.native(u.error)}</p>}
    </Section>
  );
}

function bytes(n: number) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1000 && i < units.length - 1) {
    n /= 1000;
    i++;
  }
  return `${n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

/** Sign in to Google, see what is on Drive, and move finished work now. Needs the client ID / secret saved first. */
function DriveActions({ api, dirty }: { api: Api; dirty: boolean }) {
  const qc = useQueryClient();
  const [code, setCode] = useState<{ code: string; url: string; interval: number } | null>(null);
  const [outcome, setOutcome] = useState<"denied" | "expired" | null>(null);
  const { data: d } = useQuery({
    queryKey: ["drive"],
    queryFn: () => api.drive(),
    refetchInterval: (q) => (q.state.data?.sync.running ? 3000 : 30_000),
  });
  const signIn = useMutation({
    mutationFn: () => api.driveSignIn(),
    onSuccess: (r) => {
      setOutcome(null);
      setCode(r);
    },
  });
  const signOut = useMutation({
    mutationFn: () => api.driveSignOut(),
    onSuccess: (next) => {
      qc.setQueryData(["drive"], next);
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });
  const sync = useMutation({ mutationFn: () => api.driveSync(), onSuccess: () => qc.invalidateQueries({ queryKey: ["drive"] }) });

  useEffect(() => {
    if (!code) return;
    const timer = setInterval(async () => {
      try {
        const { state } = await api.driveSignInCheck();
        if (state === "pending") return;
        setCode(null);
        if (state === "ok") {
          qc.invalidateQueries({ queryKey: ["drive"] });
          qc.invalidateQueries({ queryKey: ["settings"] });
        } else setOutcome(state);
      } catch {
        // try again on the next tick
      }
    }, Math.max(code.interval, 3) * 1000);
    return () => clearInterval(timer);
  }, [code, api, qc]);

  if (!d) return null;
  const error = signIn.error ?? signOut.error ?? sync.error;
  return (
    <div className="grid gap-3 rounded-lg border bg-strip p-4">
      {!d.client ? (
        <p className="text-sm text-muted-foreground">{t.settings.driveNeedClient}</p>
      ) : d.signed_in ? (
        <>
          <p className="flex items-center gap-1 text-sm">
            <Check className="size-4 text-mint" />
            {d.account.email ? t.settings.driveAccount(d.account.email) : t.settings.driveSignedIn}
          </p>
          {d.account.used != null && d.account.limit != null && (
            <p className="text-xs text-muted-foreground">{t.settings.driveSpace(bytes(d.account.used), bytes(d.account.limit))}</p>
          )}
          <p className="text-xs text-muted-foreground">{t.settings.driveOnDrive(d.files, bytes(d.bytes))}</p>
          {!d.enabled && <p className="text-xs text-muted-foreground">{t.settings.driveOffNote}</p>}
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" onClick={() => sync.mutate()} disabled={dirty || !d.enabled || d.sync.running || sync.isPending}>
              {(d.sync.running || sync.isPending) && <Loader2 className="animate-spin" />}
              {d.sync.running ? t.settings.driveSyncRunning : t.settings.driveSync}
            </Button>
            <Button variant="outline" size="sm" onClick={() => signOut.mutate()} disabled={signOut.isPending}>
              {t.settings.driveSignOut}
            </Button>
            {dirty && <span className="text-xs text-muted-foreground">{t.settings.driveSaveFirst}</span>}
            {!d.sync.running && d.sync.finished > 0 && !d.sync.error && (
              <span role="status" className="text-sm text-muted-foreground">{t.settings.driveSyncDone(bytes(d.sync.freed))}</span>
            )}
          </div>
          {d.sync.error && <p role="alert" className="text-sm text-destructive">{d.sync.error}</p>}
        </>
      ) : code ? (
        <div className="grid gap-2">
          <p className="text-sm">{t.settings.driveCodeIntro(code.code)}</p>
          <Button variant="link" size="sm" className="justify-self-start px-0" onClick={() => openExternal(code.url)}>
            {code.url}
          </Button>
          <p className="font-mono text-2xl tracking-widest">{code.code}</p>
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            {t.settings.driveWaiting}
          </p>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" onClick={() => signIn.mutate()} disabled={dirty || signIn.isPending}>
            {signIn.isPending && <Loader2 className="animate-spin" />}
            {t.settings.driveSignIn}
          </Button>
          {dirty && <span className="text-xs text-muted-foreground">{t.settings.driveSaveFirst}</span>}
          {outcome === "denied" && <span className="text-sm text-destructive">{t.settings.driveDenied}</span>}
          {outcome === "expired" && <span className="text-sm text-destructive">{t.settings.driveExpired}</span>}
        </div>
      )}
      {error && <p role="alert" className="text-sm text-destructive">{error.message}</p>}
    </div>
  );
}

function HealthCard({ api }: { api: Api }) {
  const { data: h, error } = useQuery({ queryKey: ["health"], queryFn: () => api.health(), refetchInterval: 30_000 });
  if (error) return <p role="alert" className="text-sm text-destructive">{error.message}</p>;
  if (!h) return null;
  const rows: [string, ReactNode][] = [
    [t.settings.version, h.version],
    [t.settings.platform, `${h.platform.system} ${h.platform.machine} · Python ${h.platform.python}`],
    [
      "LLM",
      h.providers.llm.key ? (
        `${h.providers.llm.model} · ${h.providers.llm.fast_model}`
      ) : (
        <span className="text-destructive">{t.settings.llmNoKey}</span>
      ),
    ],
    ["TTS", h.providers.tts ?? <span className="text-destructive">{t.settings.none}</span>],
    ["ASR", `${h.providers.asr.engine} · ${h.providers.asr.model}`],
    ["ffmpeg", h.ffmpeg ?? <span className="text-destructive">{t.settings.notFound}</span>],
    [t.settings.jsRuntime, h.js_runtime ?? <span className="text-destructive">{t.settings.jsRuntimeMissing}</span>],
    ["Postiz", h.postiz ? "✓" : <span className="text-muted-foreground">{t.settings.none}</span>],
    ["data", h.data_dir],
    [t.settings.disk, h.disk ? t.settings.diskFree(bytes(h.disk.free), bytes(h.disk.total)) : "—"],
  ];
  const missing = [!h.providers.tts && "TTS", !h.ffmpeg && "ffmpeg"].filter(Boolean).join(", ");
  return (
    <Section id="health" title={t.settings.health} collapsible defaultOpen={false} aside={missing ? <span className="text-coral">{missing}</span> : `${t.settings.version} ${h.version}`}>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="break-all">{v}</dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}

/** The tabs of the page, in order. Each one holds what a person looks for together; the technical options sit last. */
const TABS = ["general", "ai", "publishing", "channels", "storage", "stats", "app", "advanced"] as const;
/** Tabs that save by themselves (their own forms), so the page-wide Save bar stays out of their way. */
const OWN_SAVE: readonly TabId[] = ["channels", "stats"];
type TabId = (typeof TABS)[number];

/** Which tab a setting lives on (to mark a tab that holds unsaved changes). */
function tabOf(key: string): TabId {
  if (/^(REFRESH_EVERY_MIN|NEWS_TOPICS)$/.test(key)) return "general";
  if (/^(LLM_|ANTHROPIC_|ELEVENLABS_|MONTHLY_BUDGET_USD|AI_CLIP_USD_PER_SEC|FAL_KEY|IMAGE_STYLE)/.test(key)) return "ai";
  if (/^(POSTIZ_|SLACK_)/.test(key)) return "publishing";
  if (/^DRIVE_/.test(key)) return "storage";
  return "advanced";
}

/** A small "set up / not set up" readout for the header of a service card. */
function KeyStatus({ on }: { on: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className={on ? "size-2 rounded-full bg-mint" : "size-2 rounded-full border border-muted-foreground"} />
      {on ? t.settings.keyOn : t.settings.keyOff}
    </span>
  );
}

/** The controls every tab shares: they read and write the one draft of the page. */
function useKit(s: Settings, draft: Draft, setDraft: (f: (d: Draft) => Draft) => void) {
  const val = (k: string) => (k in draft ? String(draft[k]) : (s[k]?.value ?? ""));
  const bool = (k: string, dflt = false) =>
    k in draft ? draft[k] === true : val(k) === "" ? dflt : ["1", "true", "yes", "on"].includes(val(k).toLowerCase());
  const set = (k: string, v: string | boolean) => setDraft((d) => ({ ...d, [k]: v }));
  const text = (k: string, placeholder?: string) => (
    <Input value={val(k)} placeholder={placeholder} onChange={(e) => set(k, e.target.value)} />
  );
  // A number stays what the person types (even empty); empty means "the default", which the placeholder shows.
  const num = (k: string, placeholder: string, step?: string) => (
    <Input
      type="number"
      min={0}
      step={step}
      inputMode="decimal"
      className="w-32"
      value={val(k)}
      placeholder={placeholder}
      onChange={(e) => set(k, e.target.value)}
    />
  );
  const secret = (k: string) => (
    <Input
      type="password"
      value={k in draft ? String(draft[k]) : ""}
      placeholder={s[k]?.value || t.settings.keyEmpty}
      onChange={(e) => set(k, e.target.value)}
    />
  );
  const src = (k: string) =>
    s[k]?.source === "settings" ? t.settings.fromSettings : s[k]?.source === "env" ? t.settings.fromEnv : undefined;
  const saved = (k: string) => !!s[k]?.value;
  const switchRow = (k: string, label: string, hint?: string, dflt = false) => (
    <div className="grid content-start gap-1">
      <label className="flex items-center justify-between gap-4">
        <span className="text-[13px]">{label}</span>
        <Switch checked={bool(k, dflt)} onCheckedChange={(v) => set(k, v)} />
      </label>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
  return { val, bool, set, text, num, secret, src, saved, switchRow };
}
type Kit = ReturnType<typeof useKit>;

/** Two fields per row once the card itself is wide enough (the card is a container: half-width cards on a wide window stay readable). */
const GRID = "grid items-start gap-4 @md:grid-cols-2";

function GeneralTab({ kit, unsaved }: { kit: Kit; unsaved: number }) {
  const { src, num, switchRow } = kit;
  return (
    <>
      <Section id="general" title={t.settings.general} bodyClassName={GRID}>
        <LanguageField unsaved={unsaved} />
        <Field label={t.settings.refreshEvery} hint={src("REFRESH_EVERY_MIN") ?? t.settings.refreshHint}>
          {num("REFRESH_EVERY_MIN", "0", "1")}
        </Field>
        <div className="@md:col-span-2">{switchRow("NEWS_TOPICS", t.settings.newsTopics, t.settings.newsTopicsHint)}</div>
      </Section>
      <Section id="appearance" title={t.settings.theme} bodyClassName={GRID}>
        <ThemeField />
        <FontField />
      </Section>
    </>
  );
}

function AiTab({ api, kit }: { api: Api; kit: Kit }) {
  const { val, set, text, num, secret, src, saved } = kit;
  const hasElKey = saved("ELEVENLABS_API_KEY");
  const ttsProviders: [string, string][] = [
    ["", t.settings.ttsProviderAuto],
    ["elevenlabs", "ElevenLabs"],
    ["gemini", "Gemini"],
  ];
  return (
    <>
      <Section id="llm" title={t.settings.llm} aside={<KeyStatus on={saved("ANTHROPIC_API_KEY")} />} bodyClassName={GRID}>
        <p className="text-sm text-muted-foreground @md:col-span-2">{t.settings.modelHint}</p>
        <div className="@md:col-span-2">
          <Field label={t.settings.apiKey} hint={src("ANTHROPIC_API_KEY")}>
            {secret("ANTHROPIC_API_KEY")}
          </Field>
        </div>
        <Field label={t.settings.model} hint={src("LLM_MODEL")}>
          {text("LLM_MODEL", "claude-opus-5-5")}
        </Field>
        <Field label={t.settings.modelFast} hint={src("LLM_MODEL_FAST")}>
          {text("LLM_MODEL_FAST", "claude-haiku-5-5")}
        </Field>
      </Section>

      <Section id="voice" title={t.settings.voice} aside={<KeyStatus on={hasElKey || saved("GEMINI_API_KEY")} />} bodyClassName={GRID}>
        <div className="@md:col-span-2">
          <Field label={t.settings.ttsProvider} hint={src("TTS_PROVIDER") ?? t.settings.ttsProviderHint}>
            <Choice value={val("TTS_PROVIDER")} onChange={(v) => set("TTS_PROVIDER", v)} options={ttsProviders} className="w-64" />
          </Field>
        </div>
        <Field label="ELEVENLABS_API_KEY" hint={src("ELEVENLABS_API_KEY")}>
          {secret("ELEVENLABS_API_KEY")}
        </Field>
        <Field label={t.settings.voiceLabel}>
          <VoicePicker
            api={api}
            hasKey={hasElKey}
            provider="elevenlabs"
            value={val("ELEVENLABS_VOICE_ID")}
            onChange={(v) => set("ELEVENLABS_VOICE_ID", v)}
          />
        </Field>
        <Field label={t.settings.ttsModel} hint={src("ELEVENLABS_MODEL")}>
          {text("ELEVENLABS_MODEL", "eleven_multilingual_v2")}
        </Field>
        <Field label="GEMINI_API_KEY" hint={src("GEMINI_API_KEY") ?? t.settings.geminiKeyHint}>
          {secret("GEMINI_API_KEY")}
        </Field>
        <Field label={t.settings.geminiVoice}>
          <VoicePicker
            api={api}
            hasKey
            provider="gemini"
            autoLabel={t.settings.geminiVoiceAuto}
            value={val("GEMINI_VOICE")}
            onChange={(v) => set("GEMINI_VOICE", v)}
          />
        </Field>
        <Field label={t.settings.geminiModel} hint={src("GEMINI_TTS_MODEL") ?? t.settings.geminiModelHint}>
          {text("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")}
        </Field>
      </Section>

      <Section id="images" title={t.settings.imagesClips} aside={<KeyStatus on={saved("FAL_KEY")} />} bodyClassName={GRID}>
        <div className="@md:col-span-2">
          <Field label={t.settings.apiKey} hint={src("FAL_KEY") ?? t.settings.falKeyHint}>
            {secret("FAL_KEY")}
          </Field>
        </div>
        <div className="@md:col-span-2">
          <Field label={t.settings.imageStyle} hint={src("IMAGE_STYLE") ?? t.settings.imageStyleHint}>
            {text("IMAGE_STYLE", "photorealistic, natural light, sharp focus, no text, no watermark")}
          </Field>
        </div>
      </Section>

      <Section id="costs" title={t.settings.costs} bodyClassName={GRID}>
        <Field label={t.settings.monthlyBudget} hint={t.settings.monthlyBudgetHint}>
          {num("MONTHLY_BUDGET_USD", "0", "1")}
        </Field>
        <Field label={t.settings.voicePrice} hint={t.settings.voicePriceHint}>
          {num("ELEVENLABS_USD_PER_1K_CHARS", "0.22", "0.01")}
        </Field>
        <Field label={t.settings.geminiPrice} hint={t.settings.geminiPriceHint}>
          {num("GEMINI_TTS_USD_PER_MIN", "0.03", "0.01")}
        </Field>
        <Field label={t.settings.clipPrice} hint={t.settings.clipPriceHint}>
          {num("AI_CLIP_USD_PER_SEC", val("CLIP_PROVIDER") === "heygen" ? "0.02" : "0.08", "0.01")}
        </Field>
      </Section>
    </>
  );
}

function PublishingTab({ api, s, kit, dirty }: { api: Api; s: Settings; kit: Kit; dirty: boolean }) {
  const { text, secret, src, saved } = kit;
  const testSlack = useMutation({ mutationFn: () => api.testSlack() });
  const testPostiz = useMutation({ mutationFn: () => api.postizChannels() });
  return (
    <>
      <Section id="posting" title={t.settings.postiz} aside={<KeyStatus on={saved("POSTIZ_URL") && saved("POSTIZ_API_KEY")} />} bodyClassName={GRID}>
        <Field label={t.settings.postizUrl} hint={src("POSTIZ_URL") ?? t.settings.postizHint}>
          {text("POSTIZ_URL", "https://postiz.example.com/api")}
        </Field>
        <Field label={t.settings.apiKey} hint={src("POSTIZ_API_KEY")}>
          {secret("POSTIZ_API_KEY")}
        </Field>
        <div className="flex flex-wrap items-center gap-3 @md:col-span-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => testPostiz.mutate()}
            disabled={dirty || !s.POSTIZ_URL?.value || !s.POSTIZ_API_KEY?.value || testPostiz.isPending}
          >
            {testPostiz.isPending && <Loader2 className="animate-spin" />}
            {t.settings.postizTest}
          </Button>
          {dirty && <span className="text-xs text-muted-foreground">{t.settings.postizSaveFirst}</span>}
          <span role="status" className="contents">
            {testPostiz.isSuccess && !dirty && (
              <span className="flex items-center gap-1 text-sm text-muted-foreground">
                <Check className="size-4" />
                {t.settings.postizConnected(testPostiz.data.length)}
              </span>
            )}
          </span>
          {testPostiz.error && <span role="alert" className="text-sm text-destructive">{testPostiz.error.message}</span>}
        </div>
      </Section>

      <Section id="slack" title={t.settings.slack} aside={<KeyStatus on={saved("SLACK_WEBHOOK_URL")} />} bodyClassName="grid gap-4">
        <Field label={t.settings.slackLink} hint={src("SLACK_WEBHOOK_URL") ?? t.settings.slackHint}>
          {secret("SLACK_WEBHOOK_URL")}
        </Field>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => testSlack.mutate()}
            disabled={dirty || !s.SLACK_WEBHOOK_URL?.value || testSlack.isPending}
          >
            {testSlack.isPending && <Loader2 className="animate-spin" />}
            {t.settings.slackTest}
          </Button>
          {dirty && <span className="text-xs text-muted-foreground">{t.settings.slackSaveFirst}</span>}
          <span role="status" className="contents">
            {testSlack.isSuccess && !dirty && (
              <span className="flex items-center gap-1 text-sm text-muted-foreground">
                <Check className="size-4" />
                {t.settings.slackSent}
              </span>
            )}
          </span>
          {testSlack.error && <span role="alert" className="text-sm text-destructive">{testSlack.error.message}</span>}
        </div>
      </Section>
    </>
  );
}

function StorageTab({ api, kit, dirty }: { api: Api; kit: Kit; dirty: boolean }) {
  const { text, secret, src, switchRow } = kit;
  return (
    <>
      <Section id="storage" title={t.settings.storage} bodyClassName={GRID}>
        <div className="@md:col-span-2">{switchRow("DRIVE_ON", t.settings.driveOn, t.settings.driveOnHint)}</div>
        <Field label={t.settings.driveClientId} hint={src("DRIVE_CLIENT_ID") ?? t.settings.driveClientHint}>
          {text("DRIVE_CLIENT_ID")}
        </Field>
        <Field label={t.settings.driveClientSecret} hint={src("DRIVE_CLIENT_SECRET") ?? t.settings.driveSecretHint}>
          {secret("DRIVE_CLIENT_SECRET")}
        </Field>
        <Field label={t.settings.driveFolder} hint={src("DRIVE_FOLDER") ?? t.settings.driveFolderHint}>
          {text("DRIVE_FOLDER", "Motio")}
        </Field>
        {switchRow("DRIVE_KEEP_LOCAL", t.settings.driveKeep, t.settings.driveKeepHint)}
        <div className="@md:col-span-2">
          <DriveActions api={api} dirty={dirty} />
        </div>
      </Section>
      <LogosCard api={api} />
    </>
  );
}

function AppTab({ api }: { api: Api }) {
  return (
    <>
      <EngineCard />
      <UpdateCard />
      <HealthCard api={api} />
    </>
  );
}

/** Technical options: the defaults work for most setups, so they have a tab of their own, last. */
function AdvancedTab({ kit }: { kit: Kit }) {
  const { val, set, text, secret, src } = kit;
  return (
    <>
      <Section id="providers" title={t.settings.aiProviders} bodyClassName={GRID}>
        <Field label={t.settings.imageProvider} hint={src("IMAGE_PROVIDER")}>
          <Choice
            value={val("IMAGE_PROVIDER") || "fal"}
            onChange={(v) => set("IMAGE_PROVIDER", v)}
            options={(["fal", "modal", "placeholder"] as const).map((k) => [k, t.ai.providers[k]])}
          />
        </Field>
        {(val("IMAGE_PROVIDER") || "fal") === "fal" && (
          <Field label={t.settings.falModel} hint={src("FAL_IMAGE_MODEL") ?? t.settings.falModelHint}>
            <Choice
              value={val("FAL_IMAGE_MODEL") || DEFAULT_FAL_MODEL}
              onChange={(v) => set("FAL_IMAGE_MODEL", v)}
              options={FAL_MODELS.map((k) => [k, `${t.ai.falModels[k]} · ~$${FAL_PICTURE_USD[k].toFixed(3)}`])}
            />
          </Field>
        )}
        <p className="text-xs text-muted-foreground @md:col-span-2">{t.settings.imageProviderHint}</p>
        <Field label={t.settings.clipProvider} hint={src("CLIP_PROVIDER") ?? t.settings.clipProviderHint}>
          <Choice
            value={val("CLIP_PROVIDER") || "fal"}
            onChange={(v) => set("CLIP_PROVIDER", v)}
            options={(["fal", "heygen"] as const).map((k) => [k, t.ai.clipProviders[k]])}
          />
        </Field>
        <Field label={t.settings.heygenKey} hint={src("HEYGEN_API_KEY") ?? t.settings.heygenKeyHint}>
          {secret("HEYGEN_API_KEY")}
        </Field>
      </Section>

      <Section id="sources" title={t.settings.sourcesAdv} bodyClassName={GRID}>
        <Field label={t.settings.cookies} hint={t.settings.cookiesHint}>
          <Choice
            value={val("YTDLP_COOKIES_FROM_BROWSER") || "none"}
            onChange={(v) => set("YTDLP_COOKIES_FROM_BROWSER", v === "none" ? "" : v)}
            options={[
              ["none", t.settings.cookiesNone],
              ["chrome", "Chrome"],
              ["safari", "Safari"],
              ["firefox", "Firefox"],
              ["edge", "Edge"],
              ["brave", "Brave"],
            ]}
            className="w-48"
          />
        </Field>
        <Field label={t.settings.cookiesFile} hint={t.settings.cookiesFileHint}>
          {text("YTDLP_COOKIES_FILE", cookieExample())}
        </Field>
        <Field label={t.settings.newsnowUrl} hint={src("NEWSNOW_URL") ?? t.settings.newsnowHint}>
          {text("NEWSNOW_URL", "https://newsnow.busiyi.world")}
        </Field>
        <Field label={t.settings.whisper} hint={src("WHISPER_MODEL")}>
          {text("WHISPER_MODEL")}
        </Field>
      </Section>
    </>
  );
}

/** The tabs as a vertical rail (wide windows): same tablist, arrow keys move the choice. */
function SideTabs<T extends string>({ value, onChange, options, label, className }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[]; label: string; className?: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const n = options.length;
    const j = { ArrowDown: (i + 1) % n, ArrowUp: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
    if (j === undefined) return;
    e.preventDefault();
    onChange(options[j].value);
    refs.current[j]?.focus();
  };
  return (
    <div role="tablist" aria-orientation="vertical" aria-label={label} className={cn("flex-col gap-1", className)}>
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKey(e, i)}
            className={cn(
              "flex h-10 items-center justify-between gap-2 rounded-md px-3 text-left text-[13px] font-semibold transition-colors",
              on ? "bg-cyan font-bold text-on-hue" : "text-muted-foreground hover:bg-raised hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** A path in the style of the engine's computer (the app's own OS is the best guess for a local engine). */
const cookieExample = () => (navigator.userAgent.includes("Windows") ? "C:\\Motio\\cookies.txt" : "/Users/me/cookies.txt");

export default function SettingsPage() {
  const api = useApi();
  const qc = useQueryClient();
  const { data: s, error } = useQuery({ queryKey: ["settings"], queryFn: () => api!.settings(), enabled: !!api });
  const [draft, setDraft] = useState<Draft>({});
  const [saved, setSaved] = useState(false);
  // The tab lives in state, not in the address: the unsaved-changes guard blocks any address change. `?tab=` only opens one.
  const [params] = useSearchParams();
  const asked = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as TabId) : null;
  const [tab, setTab] = useState<TabId>(asked ?? "general");
  // A link to another tab while the page is open (Channels → "Auto refresh" is in General).
  useEffect(() => {
    if (asked) setTab(asked);
  }, [asked]);

  // What really differs from the saved value: typing a value and typing it back is not a change.
  const original = (k: string): string | boolean => (typeof draft[k] === "boolean" ? ["1", "true", "yes", "on"].includes((s?.[k]?.value ?? "").toLowerCase()) : (s?.[k]?.value ?? ""));
  const secrets = new Set(Object.keys(s ?? {}).filter((k) => /KEY|WEBHOOK|SECRET|TOKEN/.test(k)));
  const changed = Object.keys(draft).filter((k) => (secrets.has(k) ? draft[k] !== "" || !!s?.[k]?.value : draft[k] !== original(k)));
  const dirty = changed.length > 0;
  const guard = useUnsavedGuard(dirty);
  const kit = useKit(s ?? {}, draft, setDraft);

  const save = useMutation({
    mutationFn: () => api!.saveSettings(Object.fromEntries(changed.map((k) => [k, draft[k]]))),
    onSuccess: (next: Settings) => {
      qc.setQueryData(["settings"], next);
      qc.invalidateQueries({ queryKey: ["health"] });
      qc.invalidateQueries({ queryKey: ["voices"] });
      setDraft({});
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    },
  });

  const dirtyTabs = new Set(changed.map(tabOf));
  const wide = OWN_SAVE.includes(tab);
  const tabOptions = TABS.map((id) => ({
    value: id,
    label: (
      <>
        {t.settings.tabs[id]}
        {dirtyTabs.has(id) && <span role="img" aria-label={t.settings.tabUnsaved} className="size-2 shrink-0 rounded-full bg-amber" />}
      </>
    ),
  }));

  return (
    <>
      <TopBar>
        <PageTitle>{t.settings.title}</PageTitle>
      </TopBar>
      {/* Narrow window: tabs on top, one column. Wide window: the tabs become a rail on the left and the cards fill the width in two columns. */}
      <div className="mx-auto w-full max-w-[88rem] px-6 pt-6 lg:grid lg:grid-cols-[12rem_minmax(0,1fr)] lg:items-start lg:gap-8">
        <div className="lg:sticky lg:top-6">
          <Segmented tabs className="w-full lg:hidden" label={t.settings.sections} value={tab} onChange={setTab} options={tabOptions} />
          <SideTabs className="hidden lg:flex" label={t.settings.sections} value={tab} onChange={setTab} options={tabOptions} />
        </div>
        <div className="min-w-0">
          {/* Channels and Stats explain themselves below */}
          {!wide && <p className="text-sm text-muted-foreground max-lg:mt-3">{t.settings.tabHints[tab]}</p>}
          <div className="space-y-5 pt-5 pb-6 lg:pt-4">
            {error && <p role="alert" className="text-sm text-destructive">{error.message}</p>}
            {api && s && (
              <div role="tabpanel" className={cn("space-y-5", !wide && "xl:block xl:columns-2 xl:gap-5 xl:space-y-0 xl:*:mb-5 xl:*:break-inside-avoid")}>
                {tab === "general" && <GeneralTab kit={kit} unsaved={changed.length} />}
                {tab === "ai" && <AiTab api={api} kit={kit} />}
                {tab === "publishing" && <PublishingTab api={api} s={s} kit={kit} dirty={dirty} />}
                {tab === "channels" && <ChannelsPanel />}
                {tab === "stats" && <StatsPanel />}
                {tab === "storage" && <StorageTab api={api} kit={kit} dirty={dirty} />}
                {tab === "app" && <AppTab api={api} />}
                {tab === "advanced" && <AdvancedTab kit={kit} />}
              </div>
            )}
          </div>
          {/* Inside the content column, so Save sits under the cards and not at the window's left edge; only there while there is something to save */}
          <div className={cn("sticky bottom-24 z-10 my-3 flex w-fit max-w-full flex-wrap items-center gap-3 rounded-xl border bg-monitor/95 px-3 py-2 shadow-lg backdrop-blur", !dirty && !saved && !save.isPending && !save.error && "hidden")}>
            <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending || !api}>
              {save.isPending && <Loader2 className="animate-spin" />}
              {t.settings.save}
            </Button>
            {dirty && (
              <Button variant="ghost" onClick={() => setDraft({})} disabled={save.isPending}>
                {t.settings.discard}
              </Button>
            )}
            <span role="status" className="flex items-center gap-1 text-[13px] text-muted-foreground">
              {saved ? (
                <>
                  <Check className="size-4 text-mint" />
                  {t.settings.saved}
                </>
              ) : dirty ? (
                t.settings.changes(changed.length)
              ) : (
                ""
              )}
            </span>
            {save.error && <span role="alert" className="text-sm text-destructive">{save.error.message}</span>}
          </div>
        </div>
      </div>
      {guard}
    </>
  );
}
