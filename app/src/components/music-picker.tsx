import { Choice } from "@/components/form";
import type { MusicTrack } from "@/lib/api";
import { t } from "@/i18n";

const VOLUMES = ["0.1", "0.15", "0.25", "0.4", "0.6"];
/** The closest level the picker offers (the engine accepts any value between 0.05 and 0.6). */
export const nearestVolume = (v: number) => VOLUMES.reduce((a, b) => (Math.abs(Number(b) - v) < Math.abs(Number(a) - v) ? b : a));

/** A track of the music library (only your own files; a TikTok sound idea is never mixed) and how loud it plays under the voice. */
export function MusicPicker({
  tracks,
  value,
  volume,
  onChange,
  onVolume,
  noneLabel = t.music.none,
}: {
  tracks: MusicTrack[];
  value: number;
  volume: number;
  onChange: (id: number) => void;
  onVolume: (v: number) => void;
  noneLabel?: string;
}) {
  const options: [string, string][] = [
    ["0", noneLabel],
    ...tracks
      .filter((x) => x.mixable || x.id === value)
      .map((x): [string, string] => [String(x.id), `${x.title}${x.artist ? ` · ${x.artist}` : ""} (${t.music.usable[x.usable_on]})`]),
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_10rem]">
      <Choice value={String(value)} onChange={(v) => onChange(Number(v))} options={options} label={t.music.card} />
      <Choice
        value={nearestVolume(volume)}
        onChange={(v) => onVolume(Number(v))}
        options={VOLUMES.map((v): [string, string] => [v, t.music.volumes[v]])}
        label={t.music.volume}
      />
    </div>
  );
}
