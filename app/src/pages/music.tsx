import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, ExternalLink, Loader2, Plus, Trash2, TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router";
import { ConfirmAction } from "@/components/confirm-action";
import { ExternalA } from "@/components/external-link";
import { Choice, Field } from "@/components/form";
import { Section } from "@/components/section";
import { PageTitle, TopBar } from "@/components/studio";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, type Api, type MusicList, type MusicTrack } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const clock = (s: number | null) => {
  if (!s) return "";
  const total = Math.round(s);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
};

/** Who may hear a track: free everywhere (mint), pre-cleared on TikTok only (amber), nothing known (coral). */
function UsableBadge({ track }: { track: MusicTrack }) {
  const tone = track.usable_on === "all" ? "text-mint" : track.usable_on === "tiktok" ? "text-amber" : "text-coral";
  return (
    <Badge variant="outline" className={tone} title={track.source === "country_chart" ? t.music.chartHint : t.music.usableHint[track.usable_on]}>
      {t.music.usable[track.usable_on]}
    </Badge>
  );
}

function TrackRow({ api, track, rank }: { api: Api; track: MusicTrack; rank?: number | null }) {
  const qc = useQueryClient();
  const [license, setLicense] = useState(track.license);
  const [note, setNote] = useState(track.note);
  const [removing, setRemoving] = useState(false);
  const idea = track.license === "tiktok_cml"; // an idea: a TikTok chart or a country chart, never mixed
  const dirty = license !== track.license || note !== track.note;
  const refresh = () => qc.invalidateQueries({ queryKey: ["music"] });
  const save = useMutation({ mutationFn: () => api.updateMusic(track.id, { license, note }), onSuccess: refresh });
  const del = useMutation({
    mutationFn: () => api.deleteMusic(track.id),
    onSuccess: () => {
      setRemoving(false);
      refresh();
    },
  });
  return (
    <li className="grid gap-3 border-b p-4 last:border-0 md:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium">{track.title}</span>
          {track.artist && <span className="truncate text-sm text-muted-foreground">{track.artist}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <UsableBadge track={track} />
          {(rank ?? track.rank) != null && <span>{t.music.rank((rank ?? track.rank)!)}</span>}
          {track.source === "tiktok_tag" ? (
            track.uses ? <span>{t.music.usedIn(track.uses, track.plays ?? 0)}</span> : null
          ) : (
            track.genre && <span>{track.genre}</span>
          )}
          {track.duration ? <span className="font-mono tabular-nums">{clock(track.duration)}</span> : null}
        </div>
        {track.audio ? (
          <audio controls preload="none" src={api.mediaUrl(track.audio)} className="h-9 w-full max-w-md" />
        ) : (
          <p className="text-xs text-muted-foreground">{t.music.listedOnly}</p>
        )}
      </div>
      <div className="grid content-start gap-2">
        {idea ? (
          <p className="text-xs text-muted-foreground">{t.music.ideaOnly}</p>
        ) : (
          <>
            <Choice
              value={license}
              onChange={setLicense}
              options={Object.keys(t.music.licenses).filter((k) => k !== "tiktok_cml").map((k): [string, string] => [k, t.music.licenses[k]])}
              label={t.music.license}
            />
            <Input value={note} maxLength={400} onChange={(e) => setNote(e.target.value)} aria-label={t.music.note} placeholder={t.music.notePlaceholder} />
          </>
        )}
        <div className="flex items-center gap-2">
          {idea ? (
            <ExternalA href={track.find} className="inline-flex items-center gap-1.5 text-sm text-cyan hover:underline">
              <ExternalLink className="size-4" />
              {t.music.findOnTikTok}
            </ExternalA>
          ) : (
            <Button size="sm" variant="secondary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? <Loader2 className="animate-spin" /> : <Check />}
              {t.music.save}
            </Button>
          )}
          <Button size="sm" variant="ghost" className="ml-auto text-destructive" onClick={() => setRemoving(true)}>
            <Trash2 />
            {t.music.remove}
          </Button>
        </div>
        {(save.error || del.error) && <p role="alert" className="text-xs text-destructive">{(save.error ?? del.error)!.message}</p>}
      </div>
      <ConfirmAction
        open={removing}
        onOpenChange={setRemoving}
        title={t.music.removeTitle(track.title)}
        body={t.music.removeBody}
        confirm={t.music.remove}
        icon={<Trash2 />}
        destructive
        busy={del.isPending}
        onConfirm={() => del.mutate()}
      />
    </li>
  );
}

type Source = "country" | "tiktok" | "tag";

/** Sound ideas, never mixed: a country's most-played chart (no key) or TikTok's trending cuts per tag (service key). */
function IdeasPanel(props: {
  api: Api;
  list: MusicList;
  source: Source;
  setSource: (s: Source) => void;
  genre: string;
  setGenre: (g: string) => void;
  region: string;
  setRegion: (r: string) => void;
  tag: string;
  setTag: (t: string) => void;
}) {
  const { api, list, source, setSource, genre, setGenre, region, setRegion, tag, setTag } = props;
  const qc = useQueryClient();
  const fetchNow = useMutation({
    mutationFn: () => api.fetchMusic(source === "country" ? { region } : source === "tag" ? { tag } : { genre }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["music"] }),
  });
  return (
    <Section title={t.music.trending} bodyClassName="grid gap-3">
      <Choice
        value={source}
        onChange={(v) => setSource(v as Source)}
        options={[["country", t.music.byCountry], ["tag", t.music.byHashtag], ["tiktok", t.music.byTag]]}
        label={t.music.trending}
        className="w-56"
      />
      <p className="flex items-start gap-2 text-[13px] text-muted-foreground">
        <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-amber" />
        {source === "country" ? t.music.countryNote : source === "tag" ? t.music.hashtagNote : t.music.licenseNote}
      </p>
      {source === "tag" && !list.browser ? (
        <p className="text-[13px]">{t.music.needBrowser}</p>
      ) : source === "tiktok" && !list.fetch ? (
        <p className="text-[13px]">
          {t.music.needKey}{" "}
          <Link to="/settings" className="text-cyan hover:underline">
            {t.nav.settings}
          </Link>
        </p>
      ) : (
        <div className="flex flex-wrap items-end gap-3">
          {source === "tag" ? (
            <Field label={t.music.hashtag}>
              <Input
                value={tag}
                maxLength={40}
                placeholder={t.music.hashtagPlaceholder}
                onChange={(e) => setTag(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && tag.trim() && !fetchNow.isPending && fetchNow.mutate()}
                className="w-56"
              />
            </Field>
          ) : source === "country" ? (
            <Field label={t.music.country}>
              <Choice value={region} onChange={setRegion} options={Object.entries(list.regions).map(([c, n]): [string, string] => [c, n])} className="w-56" />
            </Field>
          ) : (
            <Field label={t.music.genre}>
              <Choice value={genre} onChange={setGenre} options={list.genres.map((g): [string, string] => [g, g])} className="w-56" />
            </Field>
          )}
          <Button onClick={() => fetchNow.mutate()} disabled={fetchNow.isPending || (source === "tag" && !tag.trim())}>
            {fetchNow.isPending ? <Loader2 className="animate-spin" /> : <Download />}
            {source === "country" ? t.music.fetchCountry : source === "tag" ? t.music.fetchHashtag : t.music.fetch}
          </Button>
        </div>
      )}
      <span role="status" className="contents">
        {fetchNow.data && (
          <p className="text-[13px] text-muted-foreground">
            {fetchNow.data.videos !== undefined
              ? t.music.fetchedTag(fetchNow.data.videos, fetchNow.data.added, fetchNow.data.updated, fetchNow.data.removed)
              : t.music.fetched(fetchNow.data.added, fetchNow.data.updated, fetchNow.data.no_audio ?? 0, fetchNow.data.removed)}
          </p>
        )}
      </span>
      {fetchNow.error && <p role="alert" className="text-sm text-destructive">{fetchNow.error.message}</p>}
    </Section>
  );
}

/** A track from the owner's own files: the license says where it may be used. */
function AddPanel({ api, list }: { api: Api; list: MusicList }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [license, setLicense] = useState("own");
  const [note, setNote] = useState("");
  const [pct, setPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const send = async (file: File) => {
    setError(null);
    setPct(0);
    try {
      await api.addMusic(file, { title, artist, license, note }, setPct);
      setTitle("");
      setArtist("");
      setNote("");
      qc.invalidateQueries({ queryKey: ["music"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPct(null);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <Section title={t.music.add} collapsible defaultOpen={!list.tracks.length} bodyClassName="grid gap-3 sm:grid-cols-2">
      <Field label={t.music.trackTitle}>
        <Input value={title} maxLength={140} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <Field label={t.music.artist}>
        <Input value={artist} maxLength={100} onChange={(e) => setArtist(e.target.value)} />
      </Field>
      <Field label={t.music.license}>
        <Choice
          value={license}
          onChange={setLicense}
          options={list.licenses.filter((k) => k !== "tiktok_cml").map((k): [string, string] => [k, t.music.licenses[k] ?? k])}
        />
      </Field>
      <Field label={t.music.note}>
        <Input value={note} maxLength={400} onChange={(e) => setNote(e.target.value)} placeholder={t.music.notePlaceholder} />
      </Field>
      <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
        <input
          ref={input}
          type="file"
          accept="audio/*,.mp3,.m4a,.aac,.wav,.ogg,.opus,.flac"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void send(f);
          }}
        />
        <Button type="button" onClick={() => input.current?.click()} disabled={pct !== null}>
          {pct !== null ? <Loader2 className="animate-spin" /> : <Plus />}
          {pct !== null ? `${pct} %` : t.music.chooseFile}
        </Button>
        {error && <p role="alert" className={cn("text-sm text-destructive")}>{error}</p>}
      </div>
    </Section>
  );
}

function TrackList({ api, title, hint, empty, tracks, rank }: { api: Api; title: string; hint?: string; empty: string; tracks: MusicTrack[]; rank?: (x: MusicTrack) => number | null }) {
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium">{title}</h2>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      {tracks.length ? (
        <ul className="overflow-hidden rounded-lg border bg-panel">
          {tracks.map((x) => (
            <TrackRow key={`${x.id}:${x.license}:${x.note}`} api={api} track={x} rank={rank?.(x)} />
          ))}
        </ul>
      ) : (
        <p className="py-4 text-center text-sm text-muted-foreground">{empty}</p>
      )}
    </section>
  );
}

export default function MusicPage() {
  const api = useApi()!;
  const { data, isLoading, error } = useQuery({ queryKey: ["music"], queryFn: () => api.music() });
  const [pick, setPick] = useState<string | null>(null);
  const [pickRegion, setPickRegion] = useState<string | null>(null);
  const [tag, setTag] = useState("");
  const [source, setSource] = useState<Source>("country"); // the owner posts from France: a country chart first
  const genre = pick ?? data?.default_genre ?? "POP";
  const region = pickRegion ?? data?.default_region ?? "FR";
  const tagKey = tag.trim().replace(/^#/, "").toLowerCase();
  const ideas = (data?.tracks ?? []).filter((x) =>
    source === "country"
      ? x.source === "country_chart" && x.region === region
      : source === "tag"
        ? x.source === "tiktok_tag" && x.genre === tagKey
        : x.source === "tiktok_cml" && x.genre === genre,
  );
  const byRank = (key: "rank" | "rank_month") =>
    ideas.filter((x) => x[key] !== null).sort((a, b) => a[key]! - b[key]!);
  return (
    <>
      <TopBar>
        <PageTitle>{t.music.title}</PageTitle>
      </TopBar>
      <div className="max-w-4xl space-y-5 p-6">
        <p className="text-[13px] text-muted-foreground">{t.music.hint}</p>
        {error && <p role="alert" className="text-sm text-destructive">{error.message}</p>}
        {isLoading && <Skeleton className="h-40 w-full rounded-xl" />}
        {data && (
          <>
            <IdeasPanel api={api} list={data} source={source} setSource={setSource} genre={genre} setGenre={setPick} region={region} setRegion={setPickRegion} tag={tag} setTag={setTag} />
            {source === "tag" ? (
              <TrackList api={api} title={t.music.hashtagList(tagKey)} hint={t.music.hashtagHint} empty={t.music.hashtagEmpty} tracks={byRank("rank")} rank={(x) => x.rank} />
            ) : source === "country" ? (
              <TrackList api={api} title={t.music.countryList(data.regions[region] ?? region)} hint={t.music.countryHint} empty={t.music.countryEmpty} tracks={byRank("rank")} rank={(x) => x.rank} />
            ) : (
              <>
                <TrackList api={api} title={t.music.trendingList(genre)} hint={t.music.trendingHint} empty={t.music.ideasEmpty} tracks={byRank("rank")} rank={(x) => x.rank} />
                <TrackList api={api} title={t.music.popularList(genre)} hint={t.music.popularHint} empty={t.music.ideasEmpty} tracks={byRank("rank_month")} rank={(x) => x.rank_month} />
              </>
            )}
            <AddPanel api={api} list={data} />
            <TrackList api={api} title={t.music.mine} empty={t.music.empty} tracks={data.tracks.filter((x) => x.source === "upload")} />
          </>
        )}
      </div>
    </>
  );
}
