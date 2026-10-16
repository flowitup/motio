import { useQuery } from "@tanstack/react-query";
import { Check, Loader2, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { MusicPicker, nearestVolume } from "@/components/music-picker";
import { Panel } from "@/components/studio";
import { Button } from "@/components/ui/button";
import type { Api, ProjectDetail } from "@/lib/api";
import { t } from "@/i18n";

/** The background music of a video: pick a track from the library and how loud it is, then render again with the voice the video has. */
export function MusicCard(props: { api: Api; p: ProjectDetail; active: boolean; onQueued: () => void }) {
  return props.p.music ? <MusicCardBody {...props} /> : null; // an engine from before the music library does not send it
}

function MusicCardBody({ api, p, active, onQueued }: { api: Api; p: ProjectDetail; active: boolean; onQueued: () => void }) {
  const music = p.music;
  const { data } = useQuery({ queryKey: ["music"], queryFn: () => api.music(), enabled: music.supported });
  const now = music.supported ? { id: music.id ?? 0, volume: nearestVolume(music.volume) } : { id: 0, volume: "0.25" };
  const [pick, setPick] = useState<{ id: number; volume: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!music.supported) {
    return (
      <Panel title={t.music.card} bodyClassName="text-[13px] text-muted-foreground">
        {t.music.dub}
      </Panel>
    );
  }
  const id = pick?.id ?? now.id;
  const volume = pick?.volume ?? Number(now.volume);
  const changed = !!pick && (pick.id !== now.id || String(nearestVolume(pick.volume)) !== now.volume);
  const chosen = data?.tracks.find((x) => x.id === id);
  const held = chosen ? chosen.usable_on !== "all" : music.needs_review;
  const finished = p.status === "done" || (p.status === "review" && p.meta.review === "video");

  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.setProjectMusic(p.id, { track_id: id || null, volume });
      setPick(null);
      onQueued();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title={t.music.card}
      aside={music.from === "channel" && !pick ? t.music.fromChannel : undefined}
      bodyClassName="space-y-3 text-[13px] leading-5"
    >
      <MusicPicker
        tracks={data?.tracks ?? []}
        value={id}
        volume={volume}
        onChange={(v) => setPick({ id: v, volume })}
        onVolume={(v) => setPick({ id, volume: v })}
      />
      {id > 0 && held && (
        <p className="flex items-start gap-2 text-amber">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          {t.music.held}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" onClick={apply} disabled={!changed || active || busy}>
          {busy ? <Loader2 className="animate-spin" /> : <Check />}
          {finished ? t.music.apply : t.music.save}
        </Button>
        <Link to="/music" className="text-cyan hover:underline">
          {t.music.library}
        </Link>
      </div>
      <p className="text-xs text-muted-foreground">{finished ? t.music.applyHint : t.music.applyIdle}</p>
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </Panel>
  );
}
