import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Film, Loader2, Plus, Sparkles, Trash2, Video, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { ChannelChoice, useChannelChoice } from "@/components/channel-choice";
import { DeleteProjectDialog } from "@/components/delete-project";
import { Choice, Field } from "@/components/form";
import { StatusChip } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { parseClock } from "@/components/dub-cards";
import { useApi, type Api, type Project, type Rights } from "@/lib/api";
import { t } from "@/i18n";

const RIGHTS: Rights[] = ["unknown", "owned", "licensed", "cc"];
const PICTURE_USD: Record<string, string> = { fal: "0.50", modal: "0.15", placeholder: "0" }; // một video 12 cảnh, ước tính

/** Video mới: giải thích một chủ đề / link video, hoặc lồng tiếng Pháp một video. */
function CreateCard({ api, onClose }: { api: Api; onClose: () => void }) {
  const [kind, setKind] = useState<"topic" | "dub" | "ai">("topic");
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.projects.create}</CardTitle>
        <CardAction className="flex items-center gap-2">
          <div className="flex gap-1">
            {(["topic", "ai", "dub"] as const).map((k) => (
              <Button key={k} size="sm" variant={kind === k ? "default" : "outline"} onClick={() => setKind(k)}>
                {t.dub.kinds[k]}
              </Button>
            ))}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label={t.projects.cancel}>
            <X />
          </Button>
        </CardAction>
      </CardHeader>
      {kind === "topic" ? <TopicForm api={api} /> : kind === "ai" ? <AiForm api={api} /> : <DubForm api={api} />}
    </Card>
  );
}

/** Video làm hoàn toàn bằng ảnh AI từ một chủ đề: Claude viết lời và prompt từng cảnh, mô hình ảnh làm ảnh. */
function AiForm({ api }: { api: Api }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [duration, setDuration] = useState("80");
  const choice = useChannelChoice(api);
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: () => api.settings() });
  const provider = settings?.IMAGE_PROVIDER?.value || "fal";
  const needsKey = !!settings && provider === "fal" && !settings.FAL_KEY?.value;
  const create = useMutation({
    mutationFn: () => api.createAi({ topic: topic.trim(), duration: Number(duration), channel: choice.channel }),
    onSuccess: ({ project_id }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${project_id}`);
    },
  });
  return (
    <CardContent className="grid gap-4">
      <Field label={t.ai.topic} hint={t.ai.topicHint}>
        <Input autoFocus value={topic} onChange={(e) => setTopic(e.target.value)} placeholder={t.ai.topicPlaceholder} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-[160px_auto]">
        <Field label={t.projects.duration} hint={t.projects.durationHint}>
          <Choice
            value={duration}
            onChange={setDuration}
            options={["70", "80", "90"].map((d) => [d, t.projects.durations[d]])}
          />
        </Field>
        {choice.channels.length > 0 && (
          <Field label={t.channels.pick}>
            <ChannelChoice choice={choice} className="w-full sm:w-56" />
          </Field>
        )}
      </div>
      <p className={needsKey ? "text-sm text-destructive" : "text-xs text-muted-foreground"}>
        {needsKey ? t.ai.needsKey : t.ai.providerHint(t.ai.providers[provider] ?? provider, PICTURE_USD[provider] ?? "0")}
      </p>
      <div className="flex items-center justify-end gap-3">
        {create.error && <p className="mr-auto text-sm text-destructive">{create.error.message}</p>}
        <Button onClick={() => create.mutate()} disabled={!topic.trim() || needsKey || create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
          {t.ai.make}
        </Button>
      </div>
    </CardContent>
  );
}

/** Lồng tiếng Pháp một video (Douyin, Bilibili, YouTube…), tuỳ chọn đặt đoạn cần lồng. */
function DubForm({ api }: { api: Api }) {
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
  return (
    <CardContent className="grid gap-4">
      <Field label={t.dub.link} hint={t.dub.linkHint}>
        <Input autoFocus value={link} onChange={(e) => setLink(e.target.value)} placeholder={t.dub.linkPlaceholder} />
      </Field>
      <Field
        label={t.dub.part}
        hint={<span className={badTime ? "text-destructive" : undefined}>{badTime ? t.dub.badTime : t.dub.partHint}</span>}
      >
        <div className="grid grid-cols-2 gap-3 sm:max-w-xs">
          <Input aria-label={t.dub.from} value={from} onChange={(e) => setFrom(e.target.value)} placeholder={`${t.dub.from} 0:40`} />
          <Input aria-label={t.dub.to} value={to} onChange={(e) => setTo(e.target.value)} placeholder={`${t.dub.to} 1:50`} />
        </div>
      </Field>
      <div className="grid gap-4 sm:grid-cols-[1fr_auto]">
        <Field label={t.projects.rights} hint={t.projects.rightsHint}>
          <Choice
            value={rights}
            onChange={(v) => setRights(v as Rights)}
            options={RIGHTS.map((r) => [r, t.projects.rightsOptions[r]])}
          />
        </Field>
        {choice.channels.length > 0 && (
          <Field label={t.channels.pick}>
            <ChannelChoice choice={choice} className="w-full sm:w-56" />
          </Field>
        )}
      </div>
      <div className="flex items-center justify-end gap-3">
        {create.error && <p className="mr-auto text-sm text-destructive">{create.error.message}</p>}
        <Button onClick={() => create.mutate()} disabled={!link.trim() || badTime || create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" /> : <Film />}
          {t.dub.make}
        </Button>
      </div>
    </CardContent>
  );
}

/** Video giải thích từ một chủ đề bất kỳ và / hoặc link video, không cần tin hot. */
function TopicForm({ api }: { api: Api }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [text, setText] = useState("");
  const [linksOnly, setLinksOnly] = useState(false);
  const [duration, setDuration] = useState("80");
  const [rights, setRights] = useState<Rights>("unknown");
  const choice = useChannelChoice(api);
  const links = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  const create = useMutation({
    mutationFn: () =>
      api.createTopic({
        topic: topic.trim(),
        links,
        links_only: linksOnly,
        duration: Number(duration),
        rights,
        channel: choice.channel,
      }),
    onSuccess: ({ project_id }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${project_id}`);
    },
  });
  return (
    <>
      <CardContent className="grid gap-4">
        <Field label={t.projects.topic} hint={t.projects.topicHint}>
          <Input autoFocus value={topic} onChange={(e) => setTopic(e.target.value)} placeholder={t.projects.topicPlaceholder} />
        </Field>
        <Field label={t.projects.links} hint={t.projects.linksHint}>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"https://www.douyin.com/video/…\nhttps://www.bilibili.com/video/BV…\nhttps://www.facebook.com/reel/…"}
            className="min-h-20 font-mono text-xs"
          />
        </Field>
        {topic.trim() && links.length > 0 && (
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={linksOnly} onCheckedChange={setLinksOnly} />
            {t.projects.linksOnly}
          </label>
        )}
        <div className="grid gap-4 sm:grid-cols-[160px_1fr]">
          <Field label={t.projects.duration} hint={t.projects.durationHint}>
            <Choice
              value={duration}
              onChange={setDuration}
              options={["70", "80", "90"].map((d) => [d, t.projects.durations[d]])}
            />
          </Field>
          <Field label={t.projects.rights} hint={t.projects.rightsHint}>
            <Choice
              value={rights}
              onChange={(v) => setRights(v as Rights)}
              options={RIGHTS.map((r) => [r, t.projects.rightsOptions[r]])}
            />
          </Field>
        </div>
        {choice.channels.length > 0 && (
          <Field label={t.channels.pick}>
            <ChannelChoice choice={choice} className="w-full sm:w-56" />
          </Field>
        )}
        <div className="flex items-center justify-end gap-3">
          {create.error && <p className="mr-auto text-sm text-destructive">{create.error.message}</p>}
          <Button onClick={() => create.mutate()} disabled={(!topic.trim() && !links.length) || create.isPending}>
            {create.isPending ? <Loader2 className="animate-spin" /> : <Video />}
            {t.projects.make}
          </Button>
        </div>
      </CardContent>
    </>
  );
}

export default function ProjectsPage() {
  const api = useApi()!;
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<Project | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.projects(),
    refetchInterval: 4_000,
  });

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <header className="flex items-center gap-3">
        <h1 className="mr-auto text-2xl font-semibold tracking-tight">{t.projects.title}</h1>
        {!creating && (
          <Button onClick={() => setCreating(true)}>
            <Plus />
            {t.projects.create}
          </Button>
        )}
      </header>
      {creating && <CreateCard api={api} onClose={() => setCreating(false)} />}
      {error && <p className="text-sm text-destructive">{error.message}</p>}
      {data?.length === 0 && <p className="py-12 text-center text-muted-foreground">{t.projects.empty}</p>}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4">
        {isLoading && Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="aspect-[9/16] rounded-xl" />)}
        {data?.map((p) => (
          <div key={p.id} className="group relative">
            <Link to={`/projects/${p.id}`} className="block">
              <Card className="gap-0 overflow-hidden p-0 transition-shadow group-hover:shadow-md">
                <div className="relative aspect-[9/16] bg-muted">
                  {p.meta.thumb ? (
                    <img
                      src={api.mediaUrl(p.meta.thumb, p.updated_at)}
                      alt=""
                      className="size-full object-cover"
                      loading="lazy"
                    />
                  ) : (
                    <Film className="absolute inset-0 m-auto size-10 text-muted-foreground/50" />
                  )}
                  <StatusChip status={p.status} className="absolute top-2 left-2" />
                </div>
                <div className="space-y-2 p-3">
                  <div className="line-clamp-2 text-sm font-medium leading-snug">{p.meta.title || p.title}</div>
                  {(p.status === "running" || p.status === "queued") && (
                    <>
                      <Progress value={p.pct} />
                      <div className="text-xs text-muted-foreground">{p.step}</div>
                    </>
                  )}
                  <div className="text-xs text-muted-foreground">
                    #{p.id} · {t.age(p.updated_at)}
                  </div>
                </div>
              </Card>
            </Link>
            {p.status !== "running" && p.status !== "queued" && (
              <Button
                size="icon-sm"
                variant="secondary"
                onClick={() => setDeleting(p)}
                aria-label={t.projects.delete}
                title={t.projects.delete}
                className="absolute top-2 right-2 opacity-0 shadow-sm group-hover:opacity-100 hover:text-destructive focus-visible:opacity-100"
              >
                <Trash2 />
              </Button>
            )}
          </div>
        ))}
      </div>
      {deleting && (
        <DeleteProjectDialog
          api={api}
          id={deleting.id}
          title={deleting.meta.title || deleting.title}
          open
          onOpenChange={(o) => !o && setDeleting(null)}
        />
      )}
    </div>
  );
}
