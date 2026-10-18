import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Eye, EyeOff, FolderOpen, Video } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { ExternalA } from "@/components/external-link";
import { ScoreBadge } from "@/components/status-chip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { Api, Clip } from "@/lib/api";
import { listName } from "@/lib/watch-name";
import { t } from "@/i18n";

/** The followed source a clip came from; a Bilibili list is named in the UI language, not with the engine's English text. */
const clipSource = (c: Clip) => (c.watch_kind === "trending" && c.watch_target ? listName(c.watch_target) : undefined) ?? c.watch_name;
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

/** Một video mới: ảnh, tiêu đề Pháp + gốc, kênh, độ dài, lượt xem; làm video / ẩn. */
export function ClipCard({ api, clip }: { api: Api; clip: Clip }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const status = useMutation({
    mutationFn: (s: "new" | "hidden") => api.setClipStatus(clip.id, s),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
    },
  });
  const title = clip.title_fr || clip.title || clip.url;
  const error = status.error;

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
              <Button onClick={() => navigate(`/projects/new?clip=${encodeURIComponent(clip.id)}`)}>
                <Video />
                {t.clips.produce}
              </Button>
            </>
          )}
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error.message}</p>}
    </Card>
  );
}
