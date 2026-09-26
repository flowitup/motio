import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Film, Loader2, Plus, Video, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { Choice, Field } from "@/components/form";
import { StatusChip } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useApi, type Api, type Rights } from "@/lib/api";
import { t } from "@/i18n";

const RIGHTS: Rights[] = ["unknown", "owned", "licensed", "cc"];

/** Video giải thích từ một chủ đề bất kỳ và / hoặc link video, không cần tin hot. */
function CreateCard({ api, onClose }: { api: Api; onClose: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [text, setText] = useState("");
  const [linksOnly, setLinksOnly] = useState(false);
  const [duration, setDuration] = useState("60");
  const [rights, setRights] = useState<Rights>("unknown");
  const links = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  const create = useMutation({
    mutationFn: () =>
      api.createTopic({ topic: topic.trim(), links, links_only: linksOnly, duration: Number(duration), rights }),
    onSuccess: ({ project_id }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${project_id}`);
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.projects.create}</CardTitle>
        <CardAction>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label={t.projects.cancel}>
            <X />
          </Button>
        </CardAction>
      </CardHeader>
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
          <Field label={t.projects.duration}>
            <Choice
              value={duration}
              onChange={setDuration}
              options={["30", "60", "90"].map((d) => [d, t.projects.durations[d]])}
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
        <div className="flex items-center justify-end gap-3">
          {create.error && <p className="mr-auto text-sm text-destructive">{create.error.message}</p>}
          <Button onClick={() => create.mutate()} disabled={(!topic.trim() && !links.length) || create.isPending}>
            {create.isPending ? <Loader2 className="animate-spin" /> : <Video />}
            {t.projects.make}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function ProjectsPage() {
  const api = useApi()!;
  const [creating, setCreating] = useState(false);
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
          <Link key={p.id} to={`/projects/${p.id}`} className="group">
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
        ))}
      </div>
    </div>
  );
}
