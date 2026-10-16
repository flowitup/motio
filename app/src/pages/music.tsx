import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Loader2, Plus, Trash2, TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router";
import { ConfirmAction } from "@/components/confirm-action";
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

const clock = (s: number | null) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "");

/** Who may hear a track: free everywhere (mint), pre-cleared on TikTok only (amber), nothing known (coral). */
function UsableBadge({ track }: { track: MusicTrack }) {
  const tone = track.usable_on === "all" ? "text-mint" : track.usable_on === "tiktok" ? "text-amber" : "text-coral";
  return (
    <Badge variant="outline" className={tone} title={t.music.usableHint[track.usable_on]}>
      {t.music.usable[track.usable_on]}
    </Badge>
  );
}

function TrackRow({ api, track }: { api: Api; track: MusicTrack }) {
  const qc = useQueryClient();
  const [license, setLicense] = useState(track.license);
  const [note, setNote] = useState(track.note);
  const [removing, setRemoving] = useState(false);
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
          {track.rank !== null && <span>{t.music.rank(track.rank)}</span>}
          {track.genre && <span>{track.genre}</span>}
          {track.duration ? <span className="font-mono tabular-nums">{clock(track.duration)}</span> : null}
        </div>
        {track.audio ? (
          <audio controls preload="none" src={api.mediaUrl(track.audio)} className="h-9 w-full max-w-md" />
        ) : (
          <p className="text-xs text-muted-foreground">{t.music.listedOnly}</p>
        )}
      </div>
      <div className="grid content-start gap-2">
        <Choice
          value={license}
          onChange={setLicense}
          options={Object.keys(t.music.licenses).map((k): [string, string] => [k, t.music.licenses[k]])}
          label={t.music.license}
        />
        <Input value={note} maxLength={400} onChange={(e) => setNote(e.target.value)} aria-label={t.music.note} placeholder={t.music.notePlaceholder} />
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <Check />}
            {t.music.save}
          </Button>
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

/** Trending sounds of TikTok's Commercial Music Library, through the music data service set in Settings. */
function TrendingPanel({ api, list }: { api: Api; list: MusicList }) {
  const qc = useQueryClient();
  const [genre, setGenre] = useState(list.default_genre);
  const [window, setWindow] = useState(list.default_window);
  const fetchNow = useMutation({
    mutationFn: () => api.fetchMusic({ genre, window }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["music"] }),
  });
  return (
    <Section title={t.music.trending} bodyClassName="grid gap-3">
      <p className="flex items-start gap-2 text-[13px] text-muted-foreground">
        <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-amber" />
        {t.music.licenseNote}
      </p>
      {!list.fetch ? (
        <p className="text-[13px]">
          {t.music.needKey}{" "}
          <Link to="/settings" className="text-cyan hover:underline">
            {t.nav.settings}
          </Link>
        </p>
      ) : (
        <div className="flex flex-wrap items-end gap-3">
          <Field label={t.music.genre}>
            <Input value={genre} maxLength={30} onChange={(e) => setGenre(e.target.value.toUpperCase())} className="w-40" />
          </Field>
          <Field label={t.music.period}>
            <Choice
              value={window}
              onChange={setWindow}
              options={list.windows.map((w): [string, string] => [w, t.music.periods[w] ?? w])}
              className="w-44"
            />
          </Field>
          <Button onClick={() => fetchNow.mutate()} disabled={fetchNow.isPending || !genre.trim()}>
            {fetchNow.isPending ? <Loader2 className="animate-spin" /> : <Download />}
            {t.music.fetch}
          </Button>
        </div>
      )}
      <span role="status" className="contents">
        {fetchNow.data && <p className="text-[13px] text-muted-foreground">{t.music.fetched(fetchNow.data.added, fetchNow.data.updated, fetchNow.data.no_audio)}</p>}
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

export default function MusicPage() {
  const api = useApi()!;
  const { data, isLoading, error } = useQuery({ queryKey: ["music"], queryFn: () => api.music() });
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
            <TrendingPanel api={api} list={data} />
            <AddPanel api={api} list={data} />
            {data.tracks.length ? (
              <ul className="overflow-hidden rounded-lg border bg-panel">
                {data.tracks.map((x) => (
                  <TrackRow key={`${x.id}:${x.license}:${x.note}`} api={api} track={x} />
                ))}
              </ul>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">{t.music.empty}</p>
            )}
          </>
        )}
      </div>
    </>
  );
}
