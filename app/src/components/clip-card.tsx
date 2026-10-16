import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, Eye, EyeOff, FolderOpen, Languages, Loader2, Video } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { ChannelChoice, useChannelChoice } from "@/components/channel-choice";
import { ExternalA } from "@/components/external-link";
import { Choice, Field } from "@/components/form";
import { ScoreBadge } from "@/components/status-chip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import type { Api, Clip } from "@/lib/api";
import { listName } from "@/lib/watch-name";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

/** The followed source a clip came from; a Bilibili list is named in the UI language, not with the engine's English text. */
const clipSource = (c: Clip) => (c.watch_kind === "trending" && c.watch_target ? listName(c.watch_target) : undefined) ?? c.watch_name;
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

/** Một video mới: ảnh, tiêu đề Pháp + gốc, kênh, độ dài, lượt xem; làm video / ẩn. */
export function ClipCard({ api, clip }: { api: Api; clip: Clip }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [duration, setDuration] = useState("80");
  // a trending video is made on its own; a followed channel's, when its rights are known
  const [only, setOnly] = useState(clip.watch_kind === "trending" || (clip.rights ?? "unknown") !== "unknown");
  const [mute, setMute] = useState(true); // the source's own voice (Chinese) off under the French one
  const choice = useChannelChoice(api);
  const produce = useMutation({
    mutationFn: () =>
      api.produceClip(clip.id, { duration: Number(duration), links_only: only, channel: choice.channel, mute_voice: mute }),
    onSuccess: ({ project_id }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
      navigate(`/projects/${project_id}`);
    },
  });
  const dub = useMutation({
    mutationFn: () => api.dubClip(clip.id, choice.channel),
    onSuccess: ({ project_id }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
      navigate(`/projects/${project_id}`);
    },
  });
  const status = useMutation({
    mutationFn: (s: "new" | "hidden") => api.setClipStatus(clip.id, s),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
    },
  });
  const title = clip.title_fr || clip.title || clip.url;
  const error = produce.error ?? dub.error ?? status.error;

  return (
    <Card className="gap-3 p-4">
      <div className="flex items-start gap-4">
        <ExternalA href={clip.url} className="relative hidden shrink-0 sm:block">
          {clip.thumbnail ? (
            <img
              src={clip.thumbnail}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
              className="aspect-video w-40 rounded-md bg-muted object-cover"
            />
          ) : (
            <div className="aspect-video w-40 rounded-md bg-muted" />
          )}
          {!!clip.duration && (
            <span className="absolute right-1 bottom-1 rounded bg-black/75 px-1 text-xs text-white">{mmss(clip.duration)}</span>
          )}
        </ExternalA>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-start gap-3">
            {clip.score != null && <ScoreBadge score={clip.score} />}
            <div className="min-w-0 space-y-1">
              <div className="font-medium leading-snug">{title}</div>
              {clip.title_fr && clip.title && <div className="text-sm text-muted-foreground">{clip.title}</div>}
              {clip.reason && <div className="text-sm">{clip.reason}</div>}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 pt-1 text-xs text-muted-foreground">
            <Badge variant="outline">{t.clips.sites[clip.site]}</Badge>
            {clip.uploader && <span>{clip.uploader}</span>}
            {clip.views != null && <span>· {t.clips.views(clip.views)}</span>}
            {clip.likes != null && <span>· {t.clips.likes(clip.likes)}</span>}
            {clip.category && <span>· {clip.category}</span>}
            {clip.rank != null && <span>· {t.clips.rank(clip.rank)}</span>}
            {clip.pubdate != null && <span>· {t.clips.posted} {t.age(clip.pubdate)}</span>}
            {clipSource(clip) && clipSource(clip) !== clip.uploader && (
              <span>
                ·{" "}
                {clip.watch_id ? (
                  <Link to={`/clips/${clip.watch_id}`} className="underline-offset-2 hover:underline" title={t.account.open}>
                    {clipSource(clip)}
                  </Link>
                ) : (
                  clipSource(clip)
                )}
              </span>
            )}
            {clip.status === "old" && (
              <Badge variant="outline" title={t.account.earlierHint}>
                {t.account.earlier}
              </Badge>
            )}
            {clip.status === "hidden" && <Badge variant="outline">{t.clips.tabs.hidden}</Badge>}
            <span>· {t.age(clip.first_seen)}</span>
            <ExternalA href={clip.url} className="inline-flex items-center gap-1">
              <ExternalLink className="size-3" aria-label={t.clips.openOriginal} />
            </ExternalA>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {clip.status === "used" && clip.project_id ? (
            <Button variant="outline" onClick={() => navigate(`/projects/${clip.project_id}`)}>
              <FolderOpen />
              {t.clips.openProject}
            </Button>
          ) : (
            <>
              <Button
                variant="ghost"
                size="icon"
                title={clip.status === "hidden" ? t.clips.unhide : t.clips.hide}
                aria-label={clip.status === "hidden" ? t.clips.unhide : t.clips.hide}
                disabled={status.isPending}
                onClick={() => status.mutate(clip.status === "hidden" ? "new" : "hidden")}
              >
                {clip.status === "hidden" ? <Eye /> : <EyeOff />}
              </Button>
              <Button variant={open ? "outline" : "default"} aria-expanded={open} onClick={() => setOpen(!open)}>
                <Video />
                {t.clips.produce}
                <ChevronDown className={cn("transition-transform", open && "rotate-180")} />
              </Button>
            </>
          )}
        </div>
      </div>
      {open && (
        <div className="flex flex-wrap items-end gap-4 border-t pt-3">
          {choice.channels.length > 0 && (
            <Field label={t.channels.pick}>
              <ChannelChoice choice={choice} className="w-44" />
            </Field>
          )}
          <Field label={t.projects.duration}>
            <Choice
              value={duration}
              onChange={setDuration}
              options={["70", "80", "90"].map((d) => [d, t.projects.durations[d]])}
              className="w-36"
            />
          </Field>
          <div className="grid gap-1 pb-1">
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={only} onCheckedChange={setOnly} />
              {t.clips.only}
            </label>
            <p className="text-xs text-muted-foreground">
              {t.projects.rightsOptions[clip.rights ?? "unknown"]}
              {!only && ` · ${t.clips.onlyHint}`}
            </p>
          </div>
          <label className="flex items-center gap-2 pb-1 text-sm">
            <Switch checked={mute} onCheckedChange={setMute} />
            {t.clips.muteVoice}
          </label>
          <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
            <Button variant="outline" onClick={() => dub.mutate()} disabled={produce.isPending || dub.isPending} title={t.clips.dubHint}>
              {dub.isPending ? <Loader2 className="animate-spin" /> : <Languages />}
              {t.clips.dub}
            </Button>
            <Button onClick={() => produce.mutate()} disabled={produce.isPending || dub.isPending}>
              {produce.isPending ? <Loader2 className="animate-spin" /> : <Video />}
              {t.clips.create}
            </Button>
          </div>
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error.message}</p>}
    </Card>
  );
}
