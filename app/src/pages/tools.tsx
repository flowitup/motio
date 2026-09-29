import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Captions,
  Download,
  ExternalLink,
  FileText,
  FolderOpen,
  Languages,
  Loader2,
  Play,
  Square,
  Trash2,
  Upload,
  Volume2,
  type LucideIcon,
} from "lucide-react";
import { useRef, useState } from "react";
import { Choice, Field } from "@/components/form";
import { VoicePicker } from "@/components/voice-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { useApi, type Api, type ToolJob, type ToolKind, type ToolOutput } from "@/lib/api";
import { inTauri, openExternal, openFolder, useEngine } from "@/lib/engine";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const TOOLS: { kind: ToolKind; icon: LucideIcon }[] = [
  { kind: "download", icon: Download },
  { kind: "transcribe", icon: FileText },
  { kind: "translate", icon: Languages },
  { kind: "speak", icon: Volume2 },
  { kind: "burn", icon: Captions },
];
const ICON = Object.fromEntries(TOOLS.map((x) => [x.kind, x.icon])) as Record<ToolKind, LucideIcon>;
const HEIGHTS = [480, 720, 1080];
const MAX_TEXT = 5000;
/** Kết quả nào dùng tiếp được cho công cụ nào. */
const NEXT: Record<ToolOutput["kind"], ToolKind[]> = {
  video: ["transcribe", "burn"],
  subtitles: ["translate", "burn"],
  audio: [],
  text: [],
};
const isBusy = (j: ToolJob) => j.status === "queued" || j.status === "running";

/** Mở một công cụ với kết quả của một job đã chọn sẵn. */
type Preset = { kind: ToolKind; file_job?: string; subs_job?: string; n: number };
/** Đầu vào file: tải lên (job = "") hoặc kết quả của một job đã xong. */
type Source = { job: string; file: File | null };
const ready = (s: Source) => !!(s.job || s.file);

function SourcePicker({
  label,
  accept,
  kinds,
  jobs,
  value,
  onChange,
}: {
  label: string;
  accept: string;
  kinds: ToolOutput["kind"][];
  jobs: ToolJob[];
  value: Source;
  onChange: (s: Source) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const usable = jobs.flatMap((j) => {
    const o = j.status === "done" ? j.outputs.find((x) => kinds.includes(x.kind)) : undefined;
    return o ? [[j, o] as const] : [];
  });
  const options: [string, string][] = [
    ["", t.tools.uploadOption],
    ...usable.map(([j, o]): [string, string] => [j.id, t.tools.fromJob(j.title, o.name)]),
  ];
  return (
    <Field label={label}>
      <Choice value={value.job} onChange={(job) => onChange({ job, file: null })} options={options} />
      {!value.job && (
        <div className="flex items-center gap-3">
          <input
            ref={input}
            type="file"
            accept={accept}
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onChange({ job: "", file: f });
              e.target.value = "";
            }}
          />
          <Button variant="outline" onClick={() => input.current?.click()}>
            <Upload />
            {t.tools.chooseFile}
          </Button>
          <span className="min-w-0 truncate text-sm text-muted-foreground">{value.file?.name ?? t.tools.noFile}</span>
        </div>
      )}
    </Field>
  );
}

function ToolForm({ api, kind, jobs, preset }: { api: Api; kind: ToolKind; jobs: ToolJob[]; preset: Preset | null }) {
  const qc = useQueryClient();
  const [pct, setPct] = useState<number | null>(null);
  const [link, setLink] = useState("");
  const [height, setHeight] = useState("720");
  const [file, setFile] = useState<Source>({ job: preset?.file_job ?? "", file: null });
  const [subs, setSubs] = useState<Source>({ job: preset?.subs_job ?? "", file: null });
  const [language, setLanguage] = useState("fr");
  const [channel, setChannel] = useState("");
  const [text, setText] = useState("");
  const [voice, setVoice] = useState("");
  const [size, setSize] = useState("medium");
  const channels = useQuery({ queryKey: ["channels"], queryFn: () => api.channels(), enabled: kind === "translate" });
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: () => api.health(), staleTime: 30_000 });

  const canStart = {
    download: link.trim() !== "",
    transcribe: ready(file),
    translate: ready(subs),
    speak: text.trim() !== "" && text.length <= MAX_TEXT,
    burn: ready(file) && ready(subs),
  }[kind];

  const start = useMutation({
    mutationFn: () => {
      const up = (s: Source) => s.file ?? undefined;
      switch (kind) {
        case "download":
          return api.startTool(kind, { url: link.trim(), height });
        case "transcribe":
          return api.startTool(kind, { file_job: file.job }, { file: up(file) }, setPct);
        case "translate":
          return api.startTool(kind, { subs_job: subs.job, language, channel }, { subs: up(subs) }, setPct);
        case "speak":
          return api.startTool(kind, { text, voice });
        case "burn":
          return api.startTool(kind, { file_job: file.job, subs_job: subs.job, size }, { file: up(file), subs: up(subs) }, setPct);
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tool-jobs"] }),
    onSettled: () => setPct(null),
  });

  const media = "video/*,audio/*,.mkv,.m4v,.opus";
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.tools.kinds[kind]}</CardTitle>
        <CardDescription>{t.tools.kindHints[kind]}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {kind === "download" && (
          <>
            <Field label={t.tools.link}>
              <Input
                value={link}
                onChange={(e) => setLink(e.target.value)}
                placeholder="https://…"
                onKeyDown={(e) => e.key === "Enter" && canStart && start.mutate()}
              />
            </Field>
            <Field label={t.tools.quality}>
              <Choice
                value={height}
                onChange={setHeight}
                options={HEIGHTS.map((h): [string, string] => [String(h), t.tools.qualityOption(h)])}
                className="w-40"
              />
            </Field>
          </>
        )}
        {kind === "transcribe" && (
          <SourcePicker
            label={t.tools.videoOrAudio}
            accept={media}
            kinds={["video", "audio"]}
            jobs={jobs}
            value={file}
            onChange={setFile}
          />
        )}
        {kind === "burn" && (
          <SourcePicker label={t.tools.video} accept="video/*,.mkv,.m4v" kinds={["video"]} jobs={jobs} value={file} onChange={setFile} />
        )}
        {(kind === "translate" || kind === "burn") && (
          <SourcePicker
            label={t.tools.subtitles}
            accept=".srt,.vtt"
            kinds={["subtitles"]}
            jobs={jobs}
            value={subs}
            onChange={setSubs}
          />
        )}
        {kind === "translate" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t.tools.language}>
              <Choice value={language} onChange={setLanguage} options={Object.entries(t.tools.languages)} />
            </Field>
            <Field label={t.tools.channel} hint={t.tools.channelHint}>
              <Choice
                value={channel}
                onChange={setChannel}
                options={[["", t.tools.noChannel], ...(channels.data ?? []).map((c): [string, string] => [String(c.id), c.name])]}
              />
            </Field>
          </div>
        )}
        {kind === "speak" && (
          <>
            <Field label={t.tools.text} hint={t.tools.chars(text.length, MAX_TEXT)}>
              <Textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={7}
                placeholder={t.tools.textPlaceholder}
              />
            </Field>
            <Field label={t.tools.voice}>
              <VoicePicker
                api={api}
                value={voice}
                onChange={setVoice}
                hasKey={health?.providers.tts === "elevenlabs"}
                autoLabel={t.tools.voiceAuto}
              />
            </Field>
          </>
        )}
        {kind === "burn" && (
          <Field label={t.tools.size}>
            <Choice value={size} onChange={setSize} options={Object.entries(t.tools.sizes)} className="w-40" />
          </Field>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => start.mutate()} disabled={!canStart || start.isPending}>
            {start.isPending ? <Loader2 className="animate-spin" /> : <Play />}
            {start.isPending && pct != null ? t.tools.uploading(pct) : t.tools.start}
          </Button>
          {start.error && <p className="text-sm text-destructive">{start.error.message}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function JobRow({ api, job, onUse }: { api: Api; job: ToolJob; onUse: (kind: ToolKind, job: ToolJob, o: ToolOutput) => void }) {
  const qc = useQueryClient();
  const { info } = useEngine();
  const refresh = () => qc.invalidateQueries({ queryKey: ["tool-jobs"] });
  const stop = useMutation({ mutationFn: () => api.cancelTool(job.id), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => api.deleteToolJob(job.id), onSuccess: refresh });
  const busy = isBusy(job);
  const Icon = ICON[job.kind];
  const fileUrl = (o: ToolOutput) => api.mediaUrl(o.path.split("/").map(encodeURIComponent).join("/"));
  const tone = {
    done: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
    failed: "bg-red-500/15 text-red-700 dark:text-red-300",
    running: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
    queued: "bg-muted text-muted-foreground",
    cancelled: "bg-muted text-muted-foreground",
  }[job.status];

  return (
    <div className="grid gap-2 rounded-lg border p-3">
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium" title={job.title}>
            {job.title}
          </div>
          <div className="text-xs text-muted-foreground">
            {t.tools.kinds[job.kind]} · {new Date(job.created_at * 1000).toLocaleString()}
          </div>
        </div>
        <Badge variant="secondary" className={cn("border-transparent", tone)}>
          {t.tools.status[job.status]}
        </Badge>
        {busy ? (
          <Button variant="outline" size="sm" onClick={() => stop.mutate()} disabled={stop.isPending}>
            <Square />
            {t.tools.stop}
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="icon-sm"
            className="hover:text-destructive"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            aria-label={t.tools.delete}
            title={t.tools.delete}
          >
            <Trash2 />
          </Button>
        )}
      </div>
      {busy && <Progress value={job.pct} />}
      {(job.error || job.message) && (
        <p className={cn("text-xs", job.error ? "text-destructive" : "text-muted-foreground")}>{job.error ?? job.message}</p>
      )}
      {(remove.error || stop.error) && <p className="text-xs text-destructive">{(remove.error ?? stop.error)!.message}</p>}
      {job.status === "done" && job.outputs.length > 0 && (
        <div className="grid gap-1.5">
          {job.outputs.map((o) => (
            <div key={o.name} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="min-w-0 truncate">{o.name}</span>
              <span className="text-xs text-muted-foreground">{t.tools.outputKinds[o.kind]}</span>
              <Button variant="outline" size="xs" onClick={() => openExternal(fileUrl(o))}>
                <ExternalLink />
                {t.tools.open}
              </Button>
              {NEXT[o.kind].length > 0 && <span className="text-xs text-muted-foreground">{t.tools.thenUse}</span>}
              {NEXT[o.kind].map((k) => (
                <Button key={k} variant="outline" size="xs" onClick={() => onUse(k, job, o)}>
                  {t.tools.kinds[k]}
                </Button>
              ))}
            </div>
          ))}
          {inTauri && info.mode === "local" && (
            <div>
              <Button variant="ghost" size="xs" onClick={() => openFolder(job.folder)}>
                <FolderOpen />
                {t.tools.openFolder}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ToolsPage() {
  const api = useApi()!;
  const [kind, setKind] = useState<ToolKind>("download");
  const [preset, setPreset] = useState<Preset | null>(null);
  const jobs = useQuery({
    queryKey: ["tool-jobs"],
    queryFn: () => api.toolJobs(),
    refetchInterval: (query) => (query.state.data?.some(isBusy) ? 1000 : false),
  });
  const list = jobs.data ?? [];
  const use = (k: ToolKind, job: ToolJob, o: ToolOutput) => {
    setKind(k);
    setPreset({
      kind: k,
      n: Date.now(),
      ...(o.kind === "video" ? { file_job: job.id } : {}),
      ...(o.kind === "subtitles" ? { subs_job: job.id } : {}),
    });
    window.scrollTo?.({ top: 0 });
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5 p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{t.tools.title}</h1>
        <p className="text-sm text-muted-foreground">{t.tools.hint}</p>
      </header>
      <div className="flex flex-wrap gap-2">
        {TOOLS.map(({ kind: k, icon: Icon }) => (
          <Button key={k} variant={k === kind ? "default" : "outline"} onClick={() => setKind(k)}>
            <Icon />
            {t.tools.kinds[k]}
          </Button>
        ))}
      </div>
      <ToolForm
        key={`${kind}-${preset?.kind === kind ? preset.n : 0}`}
        api={api}
        kind={kind}
        jobs={list}
        preset={preset?.kind === kind ? preset : null}
      />
      <Card>
        <CardHeader>
          <CardTitle>{t.tools.jobs}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          {jobs.isLoading ? (
            <Loader2 className="size-4 animate-spin" />
          ) : list.length ? (
            list.map((j) => <JobRow key={j.id} api={api} job={j} onUse={use} />)
          ) : (
            <p className="text-sm text-muted-foreground">{t.tools.noJobs}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
