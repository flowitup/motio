import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Clock, Film, Languages, Link2, ListChecks, Loader2, Search, ShieldCheck, Sparkles, TriangleAlert, Tv, UsersRound, Video } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { AddVideoFile } from "@/components/add-video-file";
import { ChannelChoice, useChannelChoice, type ChannelChoiceState } from "@/components/channel-choice";
import { clock, parseClock } from "@/components/dub-cards";
import { BudgetNotice, SetupCard } from "@/components/setup-notices";
import { PageTitle, PanelHeader, Segmented, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useApi, type Api, type Rights } from "@/lib/api";
import { estimate } from "@/lib/estimate";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

type Kind = "topic" | "ai" | "dub";
const KINDS: { value: Kind; icon: typeof Search }[] = [
  { value: "topic", icon: Search },
  { value: "ai", icon: Sparkles },
  { value: "dub", icon: Languages },
];
const RIGHTS: Rights[] = ["unknown", "owned", "licensed", "cc"];
const PICTURE_USD: Record<string, string> = { fal: "0.50", modal: "0.15", placeholder: "0" }; // một video 12 cảnh, ước tính
const MIN_S = 62; // every video lasts 62–90 s (pipeline.MIN_SECONDS / MAX_SECONDS)
const MAX_S = 90;

/** One row of the form: an icon in the gutter, a label, the control and its hint, hairline below. */
function Section({ icon: Icon, label, hint, htmlFor, children }: { icon: typeof Link2; label: string; hint?: ReactNode; htmlFor?: string; children: ReactNode }) {
  return (
    <section className="grid grid-cols-[32px_minmax(0,1fr)] gap-x-4 border-b px-8 py-8 last:border-b-0">
      <Icon className="mt-0.5 size-4 text-muted-foreground" aria-hidden />
      <div className="grid min-w-0 gap-2">
        <Label htmlFor={htmlFor} className="text-[13px] leading-5 text-foreground">
          {label}
        </Label>
        {children}
        {hint && <p className="text-xs leading-[18px] text-muted-foreground">{hint}</p>}
      </div>
    </section>
  );
}

/** Segmented control for 70 / 80 / 90 s and for the four rights. */
function Pick<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: [T, string][]; label: string }) {
  return <Segmented label={label} value={value} onChange={onChange} options={options.map(([v, l]) => ({ value: v, label: l }))} className="w-full max-w-[672px]" />;
}

/** The left column (form, then a footer with a one-line summary, an estimate of the cost and the main action) and the right column (pipeline, rules). */
function Console({
  title,
  children,
  summary,
  estimate,
  notice,
  action,
  error,
  side,
}: {
  title: string;
  children: ReactNode;
  summary: string;
  estimate?: string;
  notice?: ReactNode;
  action: ReactNode;
  error?: string;
  side: ReactNode;
}) {
  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <PanelHeader className="h-10 border-b px-8">{title}</PanelHeader>
        <div className="min-h-0 flex-1 overflow-y-auto bg-panel">{children}</div>
        <footer className="flex shrink-0 items-center gap-4 border-t bg-ground px-8 py-4">
          <div className="min-w-0 flex-1 space-y-1">
            {error ? (
              <p role="alert" className="max-h-16 overflow-y-auto font-mono text-xs leading-4 break-words text-coral">
                {error}
              </p>
            ) : notice ? (
              <div role="status" className="text-[13px] leading-5 text-mint">
                {notice}
              </div>
            ) : (
              <p className="truncate font-mono text-xs text-muted-foreground">{summary}</p>
            )}
            {estimate && (
              <p className="truncate font-mono text-xs text-muted-foreground" title={estimate}>
                {estimate}
              </p>
            )}
          </div>
          {action}
        </footer>
      </div>
      <aside className="hidden w-[420px] shrink-0 overflow-y-auto border-l bg-panel lg:block">{side}</aside>
    </div>
  );
}

function SidePanel({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-b">
      <PanelHeader aside={aside}>{title}</PanelHeader>
      {children}
    </section>
  );
}

/** What the app does with this kind of video, as a vertical track of numbered steps. */
function Pipeline({ steps, aside }: { steps: [string, string][]; aside?: ReactNode }) {
  return (
    <SidePanel title={t.studio.pipeline} aside={aside}>
      <ol className="relative p-4 pl-5">
        <span aria-hidden className="absolute top-7 bottom-7 left-[27px] w-px bg-hairline-strong" />
        {steps.map(([title, text], i) => (
          <li key={title} className="relative grid grid-cols-[24px_minmax(0,1fr)] gap-x-3 py-2.5">
            <span className="relative z-10 flex size-6 items-center justify-center rounded-full border border-hairline-strong bg-ground font-mono text-[11px] text-muted-foreground tabular-nums">
              {i + 1}
            </span>
            <div className="min-w-0">
              <div className="text-[13px] leading-5 font-semibold">{title}</div>
              <div className="text-xs leading-[18px] text-muted-foreground">{text}</div>
            </div>
          </li>
        ))}
      </ol>
    </SidePanel>
  );
}

/** 1:02 – 1:30 as an instrument readout, with the allowed window on a 0 to 1:30 track. */
function LengthRule() {
  return (
    <div className="space-y-3 p-4">
      <div className="text-[11px] leading-4 font-semibold tracking-[0.08em] text-muted-foreground uppercase">{t.projects.duration}</div>
      <div className="flex items-end justify-between gap-4">
        <span className="font-mono text-[28px] leading-8 font-medium tracking-[-0.01em] tabular-nums">
          {clock(MIN_S)} – {clock(MAX_S)}
        </span>
        <div className="w-40 pb-1">
          <div className="relative h-1.5 rounded-xs bg-white/12">
            <div className="absolute inset-y-0 right-0 rounded-xs bg-cyan" style={{ left: `${(MIN_S / MAX_S) * 100}%` }} />
          </div>
          <div className="relative mt-1 h-4 font-mono text-[11px] leading-4 text-muted-foreground">
            <span className="absolute left-0">0:00</span>
            <span className="absolute -translate-x-1/2" style={{ left: `${(MIN_S / MAX_S) * 100}%` }}>
              {clock(MIN_S)}
            </span>
            <span className="absolute right-0">{clock(MAX_S)}</span>
          </div>
        </div>
      </div>
      <p className="text-xs leading-[18px] text-muted-foreground">{t.projects.durationHint}</p>
    </div>
  );
}

/** Which rights send a video to Postiz on its own and which stop it at the video gate. */
function RightsGate({ rights }: { rights: Rights }) {
  const open = rights !== "unknown";
  const rows: { on: boolean; ok: boolean; title: string; note: string }[] = [
    { on: open, ok: true, title: RIGHTS.slice(1).map((r) => t.projects.rightsOptions[r]).join(" · "), note: t.studio.gateOpen },
    { on: !open, ok: false, title: t.projects.rightsOptions.unknown, note: t.studio.gateStop },
  ];
  return (
    <SidePanel title={t.studio.gate}>
      <div className="grid gap-3 p-4">
        {rows.map((r) => (
          <div key={r.title} className={cn("flex items-center gap-3 border px-3 py-2.5", r.on ? "border-amber" : "border-hairline-strong")}>
            {r.ok ? <CircleCheck className="size-4 shrink-0 text-mint" /> : <TriangleAlert className="size-4 shrink-0 text-amber" />}
            <div className="min-w-0 flex-1">
              <div className="text-[13px] leading-5 font-medium">{r.title}</div>
              <div className="text-xs leading-[18px] text-muted-foreground">{r.note}</div>
            </div>
            {r.on && <span className="font-mono text-xs font-medium text-amber">{t.studio.selected}</span>}
          </div>
        ))}
        <p className="text-xs leading-[18px] text-muted-foreground">{t.studio.gateNote}</p>
      </div>
    </SidePanel>
  );
}

function ChannelRow({ choice }: { choice: ChannelChoiceState }) {
  return <ChannelChoice choice={choice} className="h-11 w-full max-w-[336px]" />;
}

/** The "Estimate: about $…" line of the footer: voice (Stats price), pictures and AI clips, and what is left of the month's budget. */
function useEstimateLine(api: Api) {
  const { data } = useQuery({ queryKey: ["stats"], queryFn: () => api.stats(), staleTime: 60_000 });
  return (o: Omit<Parameters<typeof estimate>[0], "pricePer1k">) => {
    if (!data) return undefined;
    const e = estimate({ ...o, pricePer1k: data.price_per_1k });
    const usd = (n: number) => n.toFixed(2);
    const parts = [t.est.voice(usd(e.voice))];
    if (e.pictures) parts.push(t.est.pictures(usd(e.pictures)));
    if (e.clips) parts.push(t.est.clips(usd(e.clips)));
    const left = data.budget.usd > 0 ? data.budget.usd - data.month.usd : null;
    const tail = left == null ? "" : ` · ${left > 0 ? t.est.left(usd(left)) : t.est.over}`;
    return `${t.est.total(usd(e.total))} (${parts.join(" · ")})${tail}`;
  };
}

const channelName = (choice: ChannelChoiceState) => choice.channels.find((c) => String(c.id) === choice.value)?.name;
const minSec = (n: number) => t.studio.minSec(n);

/** Lồng tiếng Pháp một video (Douyin, Bilibili, YouTube…), tuỳ chọn đặt đoạn cần lồng. */
function DubConsole({ api }: { api: Api }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [link, setLink] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [rights, setRights] = useState<Rights>("unknown");
  const choice = useChannelChoice(api);
  const start = parseClock(from);
  const end = parseClock(to);
  const badTime = Number.isNaN(start) || Number.isNaN(end);
  const create = useMutation({
    mutationFn: () =>
      api.createDub({
        link: link.trim(),
        ...(start != null ? { start } : {}),
        ...(end != null ? { end } : {}),
        rights,
        channel: choice.channel,
      }),
    onSuccess: ({ project_id }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${project_id}`);
    },
  });
  const part = start != null && end != null && !badTime && end > start ? end - start : null;
  const line = useEstimateLine(api);
  const summary = [
    link.trim().replace(/^https?:\/\/(www\.)?/, ""),
    part != null ? `${clock(start)} → ${clock(end)}` : "",
    part != null ? minSec(part) : "",
    t.studio.rightsLine(t.projects.rightsOptions[rights]),
    channelName(choice),
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Console
      title={t.dub.kinds.dub}
      summary={summary || t.dub.make}
      estimate={line({ seconds: part ?? (MIN_S + MAX_S) / 2, videos: 1 })}
      error={create.error?.message}
      action={
        <Button size="lg" onClick={() => create.mutate()} disabled={!link.trim() || badTime || create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" /> : <Languages />}
          {t.dub.make}
        </Button>
      }
      side={
        <>
          <Pipeline steps={t.studio.dubSteps} aside={part != null ? `${clock(start)} → ${clock(end)}` : undefined} />
          <SidePanel title={t.studio.rules}>
            <LengthRule />
          </SidePanel>
          <RightsGate rights={rights} />
        </>
      }
    >
      <Section icon={Link2} label={t.dub.link} htmlFor="dub-link" hint={t.dub.linkHint}>
        <div className="flex flex-wrap items-start gap-3">
          <Input
            id="dub-link"
            autoFocus
            value={link}
            onChange={(e) => setLink(e.target.value)}
            placeholder={t.dub.linkPlaceholder}
            className="h-11 min-w-0 flex-1 font-mono"
          />
          <AddVideoFile api={api} onAdded={setLink} size="lg" />
        </div>
      </Section>
      <Section
        icon={Clock}
        label={t.dub.part}
        hint={<span className={badTime ? "text-coral" : undefined}>{badTime ? t.dub.badTime : t.dub.partHint}</span>}
      >
        <div className="flex flex-wrap items-center gap-3">
          {(
            [
              [t.dub.from, from, setFrom, "0:40"],
              [t.dub.to, to, setTo, "1:50"],
            ] as const
          ).map(([label, value, set, ph], i) => (
            <div key={label} className="contents">
              {i === 1 && <span aria-hidden className="h-px w-4 bg-hairline-strong" />}
              <label className="flex h-11 w-[168px] items-center gap-2.5 rounded-lg border border-input bg-ground px-3 focus-within:border-cyan">
                <span className="text-xs leading-4 font-medium text-muted-foreground">{label}</span>
                <input
                  value={value}
                  onChange={(e) => set(e.target.value)}
                  placeholder={ph}
                  inputMode="numeric"
                  className="h-10 min-w-0 flex-1 bg-transparent text-right font-mono text-[15px] leading-5 font-medium tabular-nums outline-none placeholder:text-muted-foreground"
                />
              </label>
            </div>
          ))}
          {part != null && (
            <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
              <CircleCheck className="size-4 text-mint" />
              {minSec(part)}
            </span>
          )}
        </div>
      </Section>
      <Section icon={ShieldCheck} label={t.projects.rights} hint={t.projects.rightsHint}>
        <Pick label={t.projects.rights} value={rights} onChange={setRights} options={RIGHTS.map((r): [Rights, string] => [r, t.projects.rightsOptions[r]])} />
      </Section>
      {choice.channels.length > 0 && (
        <Section icon={Tv} label={t.channels.pick}>
          <ChannelRow choice={choice} />
        </Section>
      )}
    </Console>
  );
}

/** Video giải thích từ một chủ đề bất kỳ và / hoặc link video, không cần tin hot. */
function TopicConsole({ api }: { api: Api }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [text, setText] = useState("");
  const [linksOnly, setLinksOnly] = useState(false);
  const [duration, setDuration] = useState("80");
  const [rights, setRights] = useState<Rights>("unknown");
  const choice = useChannelChoice(api);
  const lines = (v: string) =>
    v
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
  const topics = lines(topic);
  const several = topics.length > 1; // one video per topic; links belong to a single topic
  const links = several ? [] : lines(text);
  const [result, setResult] = useState<{ done: number; total: number; error?: string } | null>(null);
  const create = useMutation({
    // One project per topic, one after the other; the first failure stops the rest and keeps those topics in the box.
    mutationFn: async () => {
      const list = topics.length ? topics : [""];
      let done = 0;
      let error: string | undefined;
      let first = 0;
      for (const tp of list) {
        try {
          const r = await api.createTopic({ topic: tp, links, links_only: linksOnly, duration: Number(duration), rights, channel: choice.channel });
          if (!done) first = r.project_id;
          done++;
        } catch (e) {
          if (!done) throw e;
          error = e instanceof Error ? e.message : String(e);
          break;
        }
      }
      return { first, done, total: list.length, error, rest: list.slice(done) };
    },
    onMutate: () => setResult(null),
    onSuccess: ({ first, done, total, error, rest }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      if (total === 1) return navigate(`/projects/${first}`);
      setResult({ done, total, error });
      setTopic(rest.join("\n"));
    },
  });
  const line = useEstimateLine(api);
  const summary = [
    several ? t.projects.topicsCount(topics.length) : topic.trim(),
    links.length ? t.studio.linkCount(links.length) : "",
    t.projects.durations[duration],
    t.studio.rightsLine(t.projects.rightsOptions[rights]),
    channelName(choice),
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Console
      title={t.dub.kinds.topic}
      summary={summary || t.projects.make}
      estimate={line({ seconds: Number(duration), videos: Math.max(1, topics.length) })}
      error={create.error?.message ?? (result?.error ? `${t.projects.madePartial(result.done, result.total)} ${result.error}` : undefined)}
      notice={
        result && !result.error ? (
          <>
            {t.projects.madeSeveral(result.done)}{" "}
            <Link to="/projects" className="font-medium">
              {t.projects.seeProjects}
            </Link>
          </>
        ) : undefined
      }
      action={
        <Button size="lg" onClick={() => create.mutate()} disabled={(!topics.length && !links.length) || create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" /> : <Video />}
          {t.projects.make}
        </Button>
      }
      side={
        <>
          <Pipeline steps={t.studio.topicSteps} />
          <SidePanel title={t.studio.rules}>
            <LengthRule />
          </SidePanel>
          <RightsGate rights={rights} />
        </>
      }
    >
      <Section icon={Search} label={t.projects.topic} htmlFor="topic" hint={`${t.projects.topicHint} ${t.projects.topicsHint}`}>
        <Textarea
          id="topic"
          autoFocus
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder={t.projects.topicPlaceholder}
          className="h-[92px] min-h-[92px] resize-none"
        />
      </Section>
      <Section icon={Link2} label={t.projects.links} htmlFor="topic-links" hint={`${t.projects.linksHint} ${t.upload.hint}`}>
        <Textarea
          id="topic-links"
          value={text}
          disabled={several}
          onChange={(e) => setText(e.target.value)}
          placeholder={"https://www.douyin.com/video/…\nhttps://www.bilibili.com/video/BV…\nhttps://www.facebook.com/reel/…"}
          className="h-24 min-h-24 resize-none font-mono text-xs leading-5"
        />
        <AddVideoFile api={api} onAdded={(l) => setText((x) => (x.trim() ? `${x.trimEnd()}\n` : "") + l)} />
        {topics.length > 0 && links.length > 0 && (
          <label className="mt-2 flex min-h-10 items-center gap-3 text-[13px]">
            <Switch checked={linksOnly} onCheckedChange={setLinksOnly} />
            {t.projects.linksOnly}
          </label>
        )}
      </Section>
      <Section icon={Clock} label={t.projects.duration} hint={t.projects.durationHint}>
        <Pick label={t.projects.duration} value={duration} onChange={setDuration} options={["70", "80", "90"].map((d): [string, string] => [d, t.projects.durations[d]])} />
      </Section>
      <Section icon={ShieldCheck} label={t.projects.rights} hint={t.projects.rightsHint}>
        <Pick label={t.projects.rights} value={rights} onChange={setRights} options={RIGHTS.map((r): [Rights, string] => [r, t.projects.rightsOptions[r]])} />
      </Section>
      {choice.channels.length > 0 && (
        <Section icon={Tv} label={t.channels.pick}>
          <ChannelRow choice={choice} />
        </Section>
      )}
    </Console>
  );
}

/** Video làm hoàn toàn bằng ảnh AI từ một chủ đề: Claude viết lời và prompt từng cảnh, mô hình ảnh làm ảnh. */
function AiConsole({ api }: { api: Api }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [duration, setDuration] = useState("80");
  const [clips, setClips] = useState(""); // trống = theo kênh
  const [reviewShots, setReviewShots] = useState(true); // dừng sau khi làm ảnh để duyệt từng ảnh
  const [cast, setCast] = useState(""); // nhân vật riêng của video, mỗi dòng "Tên: ngoại hình"
  const [sameFace, setSameFace] = useState(true); // cảnh làm từ ảnh chân dung tham chiếu của nhân vật
  const choice = useChannelChoice(api);
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: () => api.settings() });
  const provider = settings?.IMAGE_PROVIDER?.value || "fal";
  const needsKey = !!settings && provider === "fal" && !settings.FAL_KEY?.value;
  const clipProvider = settings?.CLIP_PROVIDER?.value === "heygen" ? "heygen" : "fal";
  const clipKey = clipProvider === "heygen" ? settings?.HEYGEN_API_KEY?.value : settings?.FAL_KEY?.value;
  const needsClipKey = !!settings && Number(clips) > 0 && !clipKey;
  const clipPerSec = Number(settings?.AI_CLIP_USD_PER_SEC?.value || (clipProvider === "heygen" ? "0.02" : "0.08"));
  const clipUsd = (5 * clipPerSec).toFixed(2);
  const line = useEstimateLine(api);
  const channelClips = choice.channels.find((c) => String(c.id) === choice.value)?.ai_clips ?? 0;
  const create = useMutation({
    mutationFn: () =>
      api.createAi({
        topic: topic.trim(),
        duration: Number(duration),
        channel: choice.channel,
        review_shots: reviewShots,
        cast: cast.trim(),
        same_face: sameFace,
        ...(clips !== "" ? { clips: Number(clips) } : {}),
      }),
    onSuccess: ({ project_id }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${project_id}`);
    },
  });
  const note = needsKey
    ? t.ai.needsKey
    : needsClipKey
      ? t.ai.needsClipKey(clipProvider === "heygen" ? "HeyGen" : "fal")
      : t.ai.providerHint(t.ai.providers[provider] ?? provider, PICTURE_USD[provider] ?? "0");
  const summary = [topic.trim(), t.projects.durations[duration], channelName(choice)].filter(Boolean).join(" · ");
  return (
    <Console
      title={t.dub.kinds.ai}
      summary={summary || t.ai.make}
      estimate={line({
        seconds: Number(duration),
        videos: 1,
        pictures: Number(PICTURE_USD[provider] ?? 0),
        clips: clips !== "" ? Number(clips) : channelClips,
        clipPerSec,
      })}
      error={create.error?.message}
      action={
        <Button size="lg" onClick={() => create.mutate()} disabled={!topic.trim() || needsKey || needsClipKey || create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
          {t.ai.make}
        </Button>
      }
      side={
        <>
          <Pipeline steps={t.studio.aiSteps} />
          <SidePanel title={t.studio.rules}>
            <LengthRule />
            <p className={cn("px-4 pb-4 text-xs leading-[18px]", needsKey || needsClipKey ? "text-coral" : "text-muted-foreground")}>{note}</p>
          </SidePanel>
        </>
      }
    >
      <Section icon={Sparkles} label={t.ai.topic} htmlFor="ai-topic" hint={t.ai.topicHint}>
        <Input id="ai-topic" autoFocus value={topic} onChange={(e) => setTopic(e.target.value)} placeholder={t.ai.topicPlaceholder} className="h-11" />
      </Section>
      <Section icon={Clock} label={t.projects.duration} hint={t.projects.durationHint}>
        <Pick label={t.projects.duration} value={duration} onChange={setDuration} options={["70", "80", "90"].map((d): [string, string] => [d, t.projects.durations[d]])} />
      </Section>
      <Section icon={Film} label={t.ai.clips} htmlFor="ai-clips" hint={t.ai.clipsHint(clipUsd)}>
        <Input
          id="ai-clips"
          type="number"
          min={0}
          max={6}
          className="h-11 w-28 font-mono"
          value={clips}
          onChange={(e) => setClips(e.target.value === "" ? "" : String(Math.min(6, Math.max(0, Math.round(Number(e.target.value) || 0)))))}
          placeholder={t.ai.clipsPlaceholder}
        />
      </Section>
      <Section icon={UsersRound} label={t.ai.cast} htmlFor="ai-cast">
        <Textarea
          id="ai-cast"
          value={cast}
          onChange={(e) => setCast(e.target.value)}
          rows={3}
          maxLength={2500}
          placeholder={t.ai.castPlaceholder}
          className="font-mono text-xs leading-5"
        />
        <p className="text-xs leading-[18px] text-muted-foreground">{t.ai.castHint}</p>
        <label className="mt-2 flex min-h-10 items-center gap-3 text-[13px]" title={t.ai.sameFaceHint}>
          <Switch checked={sameFace} onCheckedChange={setSameFace} />
          {t.ai.sameFace}
        </label>
        <p className="text-xs leading-[18px] text-muted-foreground">{t.ai.sameFaceHint}</p>
      </Section>
      <Section icon={ListChecks} label={t.ai.reviewSection} hint={t.ai.reviewShotsHint}>
        <label className="flex min-h-10 items-center gap-3 text-[13px]">
          <Switch checked={reviewShots} onCheckedChange={setReviewShots} />
          {t.ai.reviewShots}
        </label>
      </Section>
      {choice.channels.length > 0 && (
        <Section icon={Tv} label={t.channels.pick}>
          <ChannelRow choice={choice} />
        </Section>
      )}
    </Console>
  );
}

/** Video mới: giải thích một chủ đề / link video, video AI, hoặc lồng tiếng Pháp một video. */
export default function NewVideoPage() {
  const api = useApi()!;
  const [kind, setKind] = useState<Kind>("topic");
  return (
    <div className="flex h-full min-h-0 flex-col">
      <TopBar>
        <PageTitle>{t.projects.create}</PageTitle>
        <Segmented
          label={t.projects.create}
          value={kind}
          onChange={setKind}
          className="w-[460px] max-w-full"
          options={KINDS.map(({ value, icon: Icon }) => ({
            value,
            label: (
              <>
                <Icon className="size-4" />
                {t.dub.kinds[value]}
              </>
            ),
          }))}
        />
      </TopBar>
      <SetupCard />
      <BudgetNotice />
      {kind === "topic" ? <TopicConsole api={api} /> : kind === "ai" ? <AiConsole api={api} /> : <DubConsole api={api} />}
    </div>
  );
}
