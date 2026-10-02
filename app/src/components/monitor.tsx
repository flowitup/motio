import { CircleCheck, Loader2, Pause, Play, Volume2, VolumeX } from "lucide-react";
import { useState, type RefObject } from "react";
import { hhmmss, mmss } from "@/components/timeline";
import { Panel, Segmented } from "@/components/studio";
import { Button } from "@/components/ui/button";
import type { Api, ProjectDetail, VideoVersion } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

/** The 9:16 (or 16:9) player in a monitor frame with the safe-area guide, a mono timecode and a transport row. */
export function Monitor({
  api,
  p,
  playable,
  active,
  view,
  onView,
  videoRef,
  time,
  duration,
  onTime,
}: {
  api: Api;
  p: ProjectDetail;
  playable: boolean; // a video exists and nothing is deleting it (Windows can't delete a file the player holds open)
  active: boolean;
  view: VideoVersion;
  onView: (v: VideoVersion) => void;
  videoRef: RefObject<HTMLVideoElement | null>;
  time: number;
  duration: number;
  onTime: (time: number, duration: number) => void;
}) {
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const wide = view === "wide" && !!p.meta.wide;
  const src = wide ? p.meta.wide! : p.meta.video;
  const toggle = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) void v.play().catch(() => undefined);
    else v.pause();
  };
  return (
    <Panel
      title={t.studio.monitor}
      aside={wide ? "16:9" : "9:16"}
      // The body never grows past the 400 px column, so the stacked layout (under 1180 px) keeps a phone-sized picture.
      bodyClassName={cn("mx-auto w-full space-y-3", wide ? "max-w-[672px]" : "max-w-[400px]")}
    >
      <div className="rounded-lg border border-hairline-strong bg-monitor px-3 pt-3 pb-2">
        <div className={cn("relative overflow-hidden rounded-xs bg-black", wide ? "aspect-video" : "aspect-[9/16]")}>
          {playable && src ? (
            <>
              <video
                // Another version or a new render is another element: it starts from 0.
                key={`${wide ? "w" : "v"}${p.updated_at}`}
                ref={videoRef}
                src={api.mediaUrl(src, p.updated_at)}
                poster={!wide && p.meta.thumb ? api.mediaUrl(p.meta.thumb, p.updated_at) : undefined}
                muted={muted}
                playsInline
                onTimeUpdate={(e) => onTime(e.currentTarget.currentTime, e.currentTarget.duration || 0)}
                onLoadedMetadata={(e) => onTime(e.currentTarget.currentTime, e.currentTarget.duration || 0)}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onEnded={() => setPlaying(false)}
                onClick={toggle}
                className="size-full object-contain"
              />
              <div aria-hidden className="pointer-events-none absolute inset-x-[4%] inset-y-[7%] border border-dashed border-white/25" />
            </>
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-[13px] text-white/60">
              {active ? <Loader2 className="size-8 animate-spin" /> : t.projects.noVideo}
            </div>
          )}
        </div>
        <div className="flex h-8 items-center justify-between font-mono text-xs text-muted-foreground tabular-nums">
          <span>
            <span className="text-cyan">{hhmmss(time)}</span> / {hhmmss(duration)}
          </span>
          <span>{wide ? "16:9" : "9:16"}</span>
        </div>
      </div>

      {playable && src && (
        <div className="flex items-center gap-3">
          <Button variant="secondary" size="icon" onClick={toggle} aria-label={playing ? t.studio.pause : t.studio.play} title={playing ? t.studio.pause : t.studio.play}>
            {playing ? <Pause /> : <Play />}
          </Button>
          <input
            type="range"
            min={0}
            max={duration || 0}
            step={0.1}
            value={Math.min(time, duration || 0)}
            onChange={(e) => {
              if (videoRef.current) videoRef.current.currentTime = Number(e.target.value);
            }}
            aria-label={t.studio.seek}
            className="h-10 min-w-0 flex-1 accent-cyan"
          />
          <span className="w-10 text-right font-mono text-xs text-muted-foreground tabular-nums">{mmss(duration)}</span>
          <Button variant="ghost" size="icon" onClick={() => setMuted((m) => !m)} aria-label={muted ? t.studio.unmute : t.studio.mute} title={muted ? t.studio.unmute : t.studio.mute}>
            {muted ? <VolumeX /> : <Volume2 />}
          </Button>
        </div>
      )}

      {p.meta.wide && (
        <div className="flex items-center justify-between gap-3">
          <Segmented
            label={t.publish.version}
            value={view}
            onChange={onView}
            className="h-10 w-[176px]"
            options={(["vertical", "wide"] as const).map((v) => ({ value: v, label: t.projects.versions[v] }))}
          />
          <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
            <CircleCheck className="size-4 text-mint" aria-hidden />
            {t.studio.wideReady}
          </span>
        </div>
      )}
    </Panel>
  );
}
