import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Loader2, RefreshCw, RotateCcw } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Choice, Field } from "@/components/form";
import { Section } from "@/components/section";
import { PageTitle, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { VoicePicker } from "@/components/voice-picker";
import { useUnsavedGuard } from "@/hooks/use-unsaved-guard";
import { useApi, type Api, type Settings } from "@/lib/api";
import { inTauri, openExternal, useEngine, type EngineConfig } from "@/lib/engine";
import { DEFAULT_FAL_MODEL, FAL_MODELS, FAL_PICTURE_USD } from "@/lib/image-models";
import { useUpdater } from "@/lib/updater";
import { LANGS, setLang, t, useLang, type Lang } from "@/i18n";

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
    [t.settings.quotaLeft, h.quota_left ?? t.settings.unlimited],
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


/** One entry of the section list on the left (and the order of the sections on the page). */
const SECTIONS = ["general", "llm", "voice", "costs", "images", "posting", "engine", "advanced"] as const;
type SectionId = (typeof SECTIONS)[number];
const TOC_LABEL: Record<SectionId, () => string> = {
  general: () => t.settings.general,
  llm: () => t.settings.llm,
  voice: () => t.settings.voice,
  costs: () => t.settings.costs,
  images: () => t.settings.imagesClips,
  posting: () => t.settings.posting,
  engine: () => t.settings.engine,
  advanced: () => t.settings.advanced,
};

function SettingsForm({ api, s, draft, setDraft, changed }: { api: Api; s: Settings; draft: Draft; setDraft: (f: (d: Draft) => Draft) => void; changed: string[] }) {
  const testSlack = useMutation({ mutationFn: () => api.testSlack() });
  const val = (k: string) => (k in draft ? String(draft[k]) : (s[k]?.value ?? ""));
  const bool = (k: string) => (k in draft ? draft[k] === true : ["1", "true", "yes", "on"].includes(val(k).toLowerCase()));
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
      placeholder={s[k]?.value || t.settings.keyPlaceholder}
      onChange={(e) => set(k, e.target.value)}
    />
  );
  const src = (k: string) =>
    s[k]?.source === "settings" ? t.settings.fromSettings : s[k]?.source === "env" ? t.settings.fromEnv : undefined;
  const hasElKey = !!s.ELEVENLABS_API_KEY?.value && draft.ELEVENLABS_API_KEY !== "";
  const dirty = changed.length > 0;
  const grid = "grid gap-4 sm:grid-cols-2";
  const switchRow = (k: string, label: string) => (
    <label className="flex items-center justify-between gap-4">
      <span className="text-[13px]">{label}</span>
      <Switch checked={bool(k)} onCheckedChange={(v) => set(k, v)} />
    </label>
  );

  return (
    <>
      <Section id="general" title={t.settings.general} bodyClassName={grid}>
        <LanguageField unsaved={changed.length} />
        <Field label={t.settings.refreshEvery} hint={src("REFRESH_EVERY_MIN") ?? t.settings.refreshHint}>
          {num("REFRESH_EVERY_MIN", "0", "1")}
        </Field>
        <div className="sm:col-span-2">
          <Field label={t.settings.newsSources} hint={src("NEWS_SOURCES")}>
            {text("NEWS_SOURCES", "douyin,weibo,baidu,bilibili-hot-search,toutiao,thepaper")}
          </Field>
        </div>
        <Field label={t.settings.maxPerDay}>{num("MAX_VIDEOS_PER_DAY", "0", "1")}</Field>
        <div className="grid content-start gap-3">
          {switchRow("CREDIT_ON_VIDEO", t.settings.creditOnVideo)}
          {switchRow("CREDIT_IN_POST", t.settings.creditInPost)}
        </div>
      </Section>

      <Section id="llm" title={t.settings.llm} bodyClassName={grid}>
        <Field label={t.settings.model} hint={src("LLM_MODEL")}>
          {text("LLM_MODEL", "claude-opus-5-5")}
        </Field>
        <Field label={t.settings.modelFast} hint={src("LLM_MODEL_FAST")}>
          {text("LLM_MODEL_FAST", "claude-haiku-5-5")}
        </Field>
        <Field label="ANTHROPIC_API_KEY" hint={src("ANTHROPIC_API_KEY")}>
          {secret("ANTHROPIC_API_KEY")}
        </Field>
        <p className="text-sm text-muted-foreground sm:col-span-2">{t.settings.modelHint}</p>
      </Section>

      <Section id="voice" title={t.settings.voice} bodyClassName={grid}>
        <Field label="ELEVENLABS_API_KEY" hint={src("ELEVENLABS_API_KEY")}>
          {secret("ELEVENLABS_API_KEY")}
        </Field>
        <Field label={t.settings.voiceLabel}>
          <VoicePicker api={api} hasKey={hasElKey} value={val("ELEVENLABS_VOICE_ID")} onChange={(v) => set("ELEVENLABS_VOICE_ID", v)} />
        </Field>
        <Field label={t.settings.ttsModel} hint={src("ELEVENLABS_MODEL")}>
          {text("ELEVENLABS_MODEL", "eleven_multilingual_v2")}
        </Field>
      </Section>

      <Section id="costs" title={t.settings.costs} bodyClassName={grid}>
        <Field label={t.settings.monthlyBudget} hint={t.settings.monthlyBudgetHint}>
          {num("MONTHLY_BUDGET_USD", "0", "1")}
        </Field>
        <Field label={t.settings.voicePrice} hint={t.settings.voicePriceHint}>
          {num("ELEVENLABS_USD_PER_1K_CHARS", "0.22", "0.01")}
        </Field>
        <Field label={t.settings.clipPrice} hint={t.settings.clipPriceHint}>
          {num("AI_CLIP_USD_PER_SEC", val("CLIP_PROVIDER") === "heygen" ? "0.02" : "0.08", "0.01")}
        </Field>
      </Section>

      <Section id="images" title={t.settings.imagesClips} bodyClassName={grid}>
        <Field label="FAL_KEY" hint={src("FAL_KEY") ?? t.settings.falKeyHint}>
          {secret("FAL_KEY")}
        </Field>
        <Field label={t.settings.imageStyle} hint={src("IMAGE_STYLE") ?? t.settings.imageStyleHint}>
          {text("IMAGE_STYLE", "photorealistic, natural light, sharp focus, no text, no watermark")}
        </Field>
      </Section>

      <Section id="posting" title={t.settings.posting} bodyClassName={grid}>
        <Field label={t.settings.postizUrl} hint={src("POSTIZ_URL") ?? t.settings.postizHint}>
          {text("POSTIZ_URL", "https://postiz.example.com/api")}
        </Field>
        <Field label="POSTIZ_API_KEY" hint={src("POSTIZ_API_KEY")}>
          {secret("POSTIZ_API_KEY")}
        </Field>
        <div className="grid gap-3 sm:col-span-2">
          <Field label={`${t.settings.slack} · SLACK_WEBHOOK_URL`} hint={src("SLACK_WEBHOOK_URL") ?? t.settings.slackHint}>
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
        </div>
      </Section>
    </>
  );
}

/** Technical options: the defaults work for most setups, so they sit folded at the bottom. */
function AdvancedSection({ s, draft, setDraft }: { s: Settings; draft: Draft; setDraft: (f: (d: Draft) => Draft) => void }) {
  const val = (k: string) => (k in draft ? String(draft[k]) : (s[k]?.value ?? ""));
  const set = (k: string, v: string) => setDraft((d) => ({ ...d, [k]: v }));
  const text = (k: string, placeholder?: string) => <Input value={val(k)} placeholder={placeholder} onChange={(e) => set(k, e.target.value)} />;
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
  return (
    <Section id="advanced" title={t.settings.advanced} aside={t.settings.advancedHint} collapsible defaultOpen={false} bodyClassName="grid gap-4 sm:grid-cols-2">
      <Field label={t.settings.whisper} hint={src("WHISPER_MODEL")}>
        {text("WHISPER_MODEL")}
      </Field>
      <Field label={t.settings.newsnowUrl} hint={src("NEWSNOW_URL") ?? t.settings.newsnowHint}>
        {text("NEWSNOW_URL", "https://newsnow.busiyi.world")}
      </Field>
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
      <Field label={t.settings.clipProvider} hint={src("CLIP_PROVIDER") ?? t.settings.clipProviderHint}>
        <Choice
          value={val("CLIP_PROVIDER") || "fal"}
          onChange={(v) => set("CLIP_PROVIDER", v)}
          options={(["fal", "heygen"] as const).map((k) => [k, t.ai.clipProviders[k]])}
        />
      </Field>
      <Field label="HEYGEN_API_KEY" hint={src("HEYGEN_API_KEY") ?? t.settings.heygenKeyHint}>
        {secret("HEYGEN_API_KEY")}
      </Field>
      <p className="text-xs text-muted-foreground sm:col-span-2">{t.settings.imageProviderHint}</p>
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
    </Section>
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

  // What really differs from the saved value: typing a value and typing it back is not a change.
  const original = (k: string): string | boolean => (typeof draft[k] === "boolean" ? ["1", "true", "yes", "on"].includes((s?.[k]?.value ?? "").toLowerCase()) : (s?.[k]?.value ?? ""));
  const secrets = new Set(Object.keys(s ?? {}).filter((k) => /KEY|WEBHOOK/.test(k)));
  const changed = Object.keys(draft).filter((k) => (secrets.has(k) ? draft[k] !== "" || !!s?.[k]?.value : draft[k] !== original(k)));
  const dirty = changed.length > 0;
  const guard = useUnsavedGuard(dirty);

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

  const toc = (id: SectionId) => document.getElementById(id)?.scrollIntoView({ block: "start", behavior: "smooth" });

  return (
    <>
      <TopBar>
        <PageTitle>{t.settings.title}</PageTitle>
      </TopBar>
      <div className="flex items-start gap-8 px-6 pt-6">
        <nav aria-label={t.settings.sections} className="sticky top-20 hidden w-40 shrink-0 min-[1180px]:grid">
          {SECTIONS.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => toc(id)}
              className="h-9 rounded-lg px-3 text-left text-[13px] font-medium text-muted-foreground transition-colors hover:bg-raised hover:text-foreground"
            >
              {TOC_LABEL[id]()}
            </button>
          ))}
        </nav>
        <div className="min-w-0 max-w-3xl flex-1 space-y-5 pb-6">
          {error && <p role="alert" className="text-sm text-destructive">{error.message}</p>}
          {api && s && (
            <>
              <SettingsForm api={api} s={s} draft={draft} setDraft={setDraft} changed={changed} />
              <EngineCard />
              <UpdateCard />
              <HealthCard api={api} />
              <AdvancedSection s={s} draft={draft} setDraft={setDraft} />
            </>
          )}
        </div>
      </div>
      <div className="sticky bottom-0 z-10 flex items-center gap-3 border-t bg-ground px-6 py-3">
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
      {guard}
    </>
  );
}
