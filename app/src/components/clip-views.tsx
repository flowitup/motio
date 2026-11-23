import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ExternalLink, EyeOff, FolderOpen, Video } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { ExternalA } from "@/components/external-link";
import { HUE_BORDER, HUE_TEXT, SITE_HUE, toneText } from "@/components/studio";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Api, Clip } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

/** Make a video from a clip, or hide / show it again: the same two actions as the list rows. */
function useClipActions(api: Api, clip: Clip) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const status = useMutation({
    mutationFn: (s: "new" | "hidden") => api.setClipStatus(clip.id, s),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["clips"] });
      qc.invalidateQueries({ queryKey: ["watches"] });
    },
  });
  const make = () => navigate(`/projects/new?clip=${encodeURIComponent(clip.id)}`);
  return { status, make, open: () => clip.project_id && navigate(`/projects/${clip.project_id}`) };
}

function SiteBadge({ clip }: { clip: Clip }) {
  const hue = SITE_HUE[clip.site];
  return (
    <Badge variant="outline" className={cn("font-mono font-semibold uppercase", hue && [HUE_BORDER[hue], HUE_TEXT[hue]])}>
      {t.clips.sites[clip.site]}
    </Badge>
  );
}

/** Grid layout: a poster wall. The picture leads, the score sits on it, the two actions are one row below. */
export function ClipTile({ api, clip }: { api: Api; clip: Clip }) {
  const { status, make, open } = useClipActions(api, clip);
  const title = clip.title_fr || clip.title || clip.url;
  const used = clip.status === "used" && !!clip.project_id;
  return (
    <li data-slot="card" className="group flex flex-col overflow-hidden rounded-xl border bg-panel">
      <ExternalA href={clip.url} className="relative block">
        {clip.thumbnail ? (
          <img src={clip.thumbnail} alt="" loading="lazy" referrerPolicy="no-referrer" className="aspect-video w-full bg-muted object-cover" />
        ) : (
          <div className="aspect-video w-full bg-muted" />
        )}
        {clip.score != null && (
          <span className={cn("absolute top-2 left-2 rounded-md bg-black/80 px-2 py-0.5 font-mono text-lg leading-6 font-semibold tabular-nums", "text-white")}>
            <span className={toneText(clip.score)} style={{ filter: "brightness(1.6)" }}>{clip.score}</span>
          </span>
        )}
        {!!clip.duration && <span className="absolute right-2 bottom-2 rounded bg-black/75 px-1.5 text-xs text-white">{mmss(clip.duration)}</span>}
      </ExternalA>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="card-headline line-clamp-2 text-[13px] leading-[18px] font-semibold">{title}</div>
        {clip.reason && <div className="line-clamp-2 text-xs leading-4 text-muted-foreground">{clip.reason}</div>}
        <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <SiteBadge clip={clip} />
          {clip.views != null && <span>{t.clips.views(clip.views)}</span>}
          <span>· {t.age(clip.first_seen)}</span>
        </div>
        <div className="flex items-center gap-1 pt-1">
          {used ? (
            <Button variant="outline" size="sm" className="flex-1" onClick={open}>
              <FolderOpen />
              {t.clips.openProject}
            </Button>
          ) : (
            <>
              <Button variant={(clip.score ?? 0) >= 75 ? "default" : "outline"} size="sm" className="flex-1" onClick={make}>
                <Video />
                {t.clips.produce}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                title={clip.status === "hidden" ? t.clips.unhide : t.clips.hide}
                aria-label={clip.status === "hidden" ? t.clips.unhide : t.clips.hide}
                disabled={status.isPending}
                onClick={() => status.mutate(clip.status === "hidden" ? "new" : "hidden")}
              >
                <EyeOff />
              </Button>
            </>
          )}
        </div>
      </div>
    </li>
  );
}

/** Focus layout: one video at a time, large, decided with the keyboard (Enter = make it, H = hide, ← → = browse). */
export function ClipFocus({ api, list }: { api: Api; list: Clip[] }) {
  const [i, setI] = useState(0);
  const at = Math.min(i, Math.max(0, list.length - 1));
  const clip = list[at];
  const { status, make } = useClipActions(api, clip ?? ({ id: "", status: "new" } as Clip));
  const step = (d: number) => setI((n) => Math.min(Math.max(0, Math.min(n, list.length - 1) + d), list.length - 1));
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey || !clip) return;
      if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "Enter" && clip.status !== "used") {
        e.preventDefault();
        make();
      } else if (e.key.toLowerCase() === "h" && clip.status !== "used" && !status.isPending) status.mutate(clip.status === "hidden" ? "new" : "hidden");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  if (!clip) return null;
  const title = clip.title_fr || clip.title || clip.url;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span className="font-mono tabular-nums">{at + 1} / {list.length}</span>
        <span className="hidden text-xs sm:inline">{t.clips.focusKeys}</span>
      </div>
      <div data-slot="card" className="grid overflow-hidden rounded-2xl border bg-panel lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <ExternalA href={clip.url} className="relative block bg-monitor">
          {clip.thumbnail ? (
            <img src={clip.thumbnail} alt="" referrerPolicy="no-referrer" className="aspect-video size-full object-cover" />
          ) : (
            <div className="aspect-video w-full" />
          )}
          {!!clip.duration && <span className="absolute right-3 bottom-3 rounded bg-black/75 px-2 text-sm text-white">{mmss(clip.duration)}</span>}
        </ExternalA>
        <div className="flex flex-col gap-3 p-6">
          {clip.score != null && (
            <div className="flex items-baseline gap-2">
              <span className={cn("font-mono text-5xl leading-none font-medium tabular-nums", toneText(clip.score))}>{clip.score}</span>
              <span className="text-xs text-muted-foreground uppercase">/ 100</span>
            </div>
          )}
          <h2 className="card-headline font-heading text-xl leading-snug font-semibold">{title}</h2>
          {clip.title_fr && clip.title && <p className="text-sm text-muted-foreground">{clip.title}</p>}
          {clip.reason && <p className="text-sm">{clip.reason}</p>}
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <SiteBadge clip={clip} />
            {clip.uploader && <span>{clip.uploader}</span>}
            {clip.views != null && <span>· {t.clips.views(clip.views)}</span>}
            {clip.likes != null && <span>· {t.clips.likes(clip.likes)}</span>}
            <ExternalA href={clip.url} className="inline-flex items-center gap-1">
              <ExternalLink className="size-3" aria-label={t.clips.openOriginal} />
            </ExternalA>
          </div>
          <div className="mt-auto flex flex-wrap items-center gap-2 pt-4">
            <Button size="lg" onClick={make} disabled={clip.status === "used"}>
              <Video />
              {t.clips.produce}
            </Button>
            <Button
              size="lg"
              variant="outline"
              disabled={status.isPending || clip.status === "used"}
              onClick={() => status.mutate(clip.status === "hidden" ? "new" : "hidden")}
            >
              <EyeOff />
              {clip.status === "hidden" ? t.clips.unhide : t.clips.hide}
            </Button>
            <div className="ml-auto flex gap-1">
              <Button variant="ghost" size="icon" aria-label="←" onClick={() => step(-1)} disabled={at === 0}>
                <ChevronLeft />
              </Button>
              <Button variant="ghost" size="icon" aria-label="→" onClick={() => step(1)} disabled={at >= list.length - 1}>
                <ChevronRight />
              </Button>
            </div>
          </div>
          {status.error && <p className="text-sm text-destructive">{status.error.message}</p>}
        </div>
      </div>
    </div>
  );
}
