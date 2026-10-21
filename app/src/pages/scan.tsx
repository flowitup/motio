import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet, Loader2, Plus, ScanSearch, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { ExternalA } from "@/components/external-link";
import { Choice, Field } from "@/components/form";
import { PageTitle, TopBar } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useApi, type ScanJob, type ScanMode, type ScanRow, type Site } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const SITE_NAMES: Record<string, string> = { youtube: "YouTube", bilibili: "Bilibili", douyin: "Douyin", kuaishou: "Kuaishou", weibo: "Weibo" };
const SORTS = ["order", "views", "likes", "date", "duration"] as const;
type Sort = (typeof SORTS)[number];
const ACCOUNT_SITES: Site[] = ["kuaishou", "douyin", "weibo"]; // a bare id means an account only there
const num = (n: number | null) => (n == null ? t.scan.unknown : n.toLocaleString());
const mmss = (s: number | null) => (s == null ? t.scan.unknown : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`);
const day = (ts: number | null) => (ts ? new Date(ts * 1000).toLocaleDateString() : t.scan.unknown);

/** One CSV cell: quoted when it holds a comma, a quote or a line break. */
const cell = (v: unknown) => {
  const s = v == null ? "" : String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

function csv(rows: ScanRow[]) {
  const head = ["#", "video_id", "url", "title", "account", "likes", "views", "duration_s", "posted"];
  const lines = rows.map((r, i) =>
    [i + 1, r.video_id, r.url, r.title, r.uploader, r.likes, r.views, r.duration, r.pubdate ? new Date(r.pubdate * 1000).toISOString() : ""].map(cell).join(","),
  );
  return "﻿" + [head.join(","), ...lines].join("\r\n"); // BOM: Excel reads the Chinese titles as UTF-8
}

function saveCsv(rows: ScanRow[]) {
  const url = URL.createObjectURL(new Blob([csv(rows)], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `motio-scan-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Scan: read accounts, hashtags or keywords into a table, then download, follow or export from it. */
export default function ScanPage() {
  const api = useApi()!;
  const qc = useQueryClient();
  const options = useQuery({ queryKey: ["scan", "options"], queryFn: () => api.scanOptions() });
  const [site, setSite] = useState<Site>("youtube");
  const [mode, setMode] = useState<ScanMode>("account");
  const [text, setText] = useState("");
  const [limit, setLimit] = useState<number | null>(null);
  const [keyword, setKeyword] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [minViews, setMinViews] = useState("");
  const [sort, setSort] = useState<Sort>("order");
  const [range, setRange] = useState({ from: "1", to: "100" });
  const [notice, setNotice] = useState<string | null>(null);

  const platform = options.data?.platforms.find((p) => p.site === site);
  const modes = platform?.modes ?? ["account"];
  const effectiveMode = modes.includes(mode) ? mode : modes[0];
  const effectiveLimit = limit ?? options.data?.default_limit ?? 50;

  // the scan started last (also after leaving this screen): its input fills the form again
  const latest = useQuery({ queryKey: ["scan", "latest"], queryFn: () => api.latestScan(), staleTime: Infinity });
  useEffect(() => {
    const j = latest.data;
    if (!j || jobId) return;
    setJobId(j.id);
    setSite(j.site);
    setMode(j.mode);
    setText(j.lines.join("\n"));
    setLimit(j.limit);
    setKeyword(j.keyword ?? "");
  }, [latest.data, jobId]);

  const job = useQuery({
    queryKey: ["scan", "job", jobId],
    queryFn: () => api.scan(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1000 : false),
  });
  const current: ScanJob | undefined = job.data;
  const running = current?.status === "running";

  const start = useMutation({
    mutationFn: () => api.startScan({ site, mode: effectiveMode, text, limit: effectiveLimit, keyword }),
    onSuccess: (j) => {
      setJobId(j.id);
      setSelected(new Set());
      setNotice(null);
      qc.setQueryData(["scan", "job", j.id], j);
    },
  });
  const stop = useMutation({ mutationFn: () => api.stopScan(jobId!), onSuccess: (j) => qc.setQueryData(["scan", "job", j.id], j) });

  const rows = current?.rows ?? [];
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const min = Number(minViews) || 0;
    const keep = rows
      .map((r, i) => ({ r, i }))
      .filter(({ r }) => (!q || `${r.title} ${r.uploader} ${r.video_id}`.toLowerCase().includes(q)) && (r.views ?? 0) >= min);
    const key: Record<Sort, (r: ScanRow) => number> = {
      order: () => 0,
      views: (r) => r.views ?? -1,
      likes: (r) => r.likes ?? -1,
      date: (r) => r.pubdate ?? 0,
      duration: (r) => r.duration ?? -1,
    };
    return (sort === "order" ? keep : keep.sort((a, b) => key[sort](b.r) - key[sort](a.r) || a.i - b.i)).map(({ r }) => r);
  }, [rows, filter, minViews, sort]);
  const chosen = shown.filter((r) => selected.has(r.id));
  const totalViews = rows.reduce((n, r) => n + (r.views ?? 0), 0);

  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  const selectRange = () => {
    const from = Math.max(1, Number(range.from) || 1);
    const to = Math.max(from, Number(range.to) || from);
    setSelected(new Set(shown.slice(from - 1, to).map((r) => r.id)));
  };

  // each selected video goes to Tools → Download video, one job each (the engine fetches them one after another)
  const download = useMutation({
    mutationFn: async () => {
      const results = await Promise.allSettled(chosen.map((r) => api.startTool("download", { url: r.url })));
      return { ok: results.filter((x) => x.status === "fulfilled").length, bad: results.filter((x) => x.status === "rejected").length };
    },
    onSuccess: ({ ok, bad }) => {
      qc.invalidateQueries({ queryKey: ["tool-jobs"] });
      setNotice([ok ? t.scan.downloadStarted(ok) : "", bad ? t.scan.downloadFailed(bad) : ""].filter(Boolean).join(" · "));
    },
  });

  const follow = useMutation({
    mutationFn: async () => {
      const lines = current?.lines ?? [];
      const results = await Promise.allSettled(
        lines.map((line) => {
          const link = /^https?:\/\//i.test(line);
          const target = link ? line : ACCOUNT_SITES.includes(current!.site) ? `${current!.site}:user:${line}` : line;
          return api.addWatch({ target, site: current!.site });
        }),
      );
      const failed = results.flatMap((x) => (x.status === "rejected" ? [(x.reason as Error).message] : []));
      return { ok: results.length - failed.length, failed };
    },
    onSuccess: ({ ok, failed }) => {
      qc.invalidateQueries({ queryKey: ["watches"] });
      setNotice([ok ? t.scan.followed(ok) : "", ...failed.map((m) => `${t.scan.followFailed}: ${m}`)].filter(Boolean).join(" · "));
    },
  });

  const status = current
    ? running
      ? current.message ?? t.scan.reading
      : current.status === "done"
        ? current.keyword && current.read > rows.length
          ? t.scan.doneKeyword(rows.length, current.read, current.keyword)
          : t.scan.done(rows.length)
        : current.status === "stopped"
          ? t.scan.stopped(rows.length)
          : t.scan.failed
    : null;

  return (
    <>
      <TopBar>
        <PageTitle>{t.scan.title}</PageTitle>
        {rows.length > 0 && (
          <span className="ml-auto font-mono text-xs text-muted-foreground tabular-nums">
            {t.scan.totalViews(totalViews.toLocaleString())}
          </span>
        )}
      </TopBar>
      <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="grid content-start gap-4">
          <Card>
            <CardContent className="grid gap-4">
              <p className="text-sm text-muted-foreground">{t.scan.hint}</p>
              <Field label={t.scan.platform}>
                <div role="group" aria-label={t.scan.platform} className="grid grid-cols-3 gap-2">
                  {(options.data?.platforms ?? []).map((p) => (
                    <button
                      key={p.site}
                      type="button"
                      aria-pressed={site === p.site}
                      onClick={() => setSite(p.site)}
                      className={cn(
                        "h-10 rounded-lg border text-[13px] font-medium transition-colors",
                        site === p.site ? "border-cyan bg-cyan/10 text-foreground" : "border-input text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {SITE_NAMES[p.site]}
                    </button>
                  ))}
                </div>
              </Field>
              <Field label={t.scan.mode}>
                <Choice value={effectiveMode} onChange={(v) => setMode(v as ScanMode)} options={modes.map((m) => [m, t.scan.modes[m]])} />
              </Field>
              {modes.length === 1 && <p className="-mt-2 text-xs text-muted-foreground">{t.scan.noSearch}</p>}
              <Field label={t.scan.input[effectiveMode]} hint={t.scan.inputHint(options.data?.max_lines ?? 10)}>
                <Textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={t.scan.placeholders[effectiveMode]}
                  rows={5}
                  className="font-mono"
                />
              </Field>
              <Field label={t.scan.keyword} hint={t.scan.keywordHint}>
                <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder={t.scan.keywordPlaceholder} />
              </Field>
              <Field label={t.scan.limit}>
                <Choice
                  value={String(effectiveLimit)}
                  onChange={(v) => setLimit(Number(v))}
                  options={(options.data?.limits ?? [50]).map((n) => [String(n), t.scan.limitOption(n)])}
                />
              </Field>
              <p className="text-xs text-muted-foreground">{t.scan.notes[site]}</p>
              <div className="flex gap-2">
                <Button className="flex-1" disabled={!text.trim() || running || start.isPending} onClick={() => start.mutate()}>
                  {running || start.isPending ? <Loader2 className="animate-spin" /> : <ScanSearch />}
                  {t.scan.start}
                </Button>
                <Button variant="outline" disabled={!running || stop.isPending} onClick={() => stop.mutate()}>
                  <Square />
                  {stop.isPending ? t.scan.stopping : t.scan.stop}
                </Button>
              </div>
              {start.error && <p className="text-sm text-destructive">{start.error.message}</p>}
            </CardContent>
          </Card>
        </div>

        <div className="grid min-w-0 content-start gap-3">
          {status && (
            <p className={cn("text-sm", current?.status === "failed" ? "text-destructive" : "text-muted-foreground")} aria-live="polite">
              {status}
            </p>
          )}
          {!!current?.errors.length && (
            <div className="rounded-md border border-destructive/40 p-3 text-sm text-destructive">
              <p className="font-medium">{t.scan.someFailed}</p>
              <ul className="mt-1 grid gap-1 text-xs">
                {current.errors.map((e) => (
                  <li key={e} className="break-words">
                    {e}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!current && <p className="text-sm text-muted-foreground">{t.scan.empty}</p>}
          {rows.length > 0 && (
            <>
              <div className="flex flex-wrap items-end gap-3">
                <Field label={t.scan.search}>
                  <Input value={filter} onChange={(e) => setFilter(e.target.value)} className="w-56" />
                </Field>
                <Field label={t.scan.minViews}>
                  <Input inputMode="numeric" value={minViews} onChange={(e) => setMinViews(e.target.value.replace(/\D/g, ""))} placeholder="0" className="w-28" />
                </Field>
                <Field label={t.scan.sortBy}>
                  <Choice value={sort} onChange={(v) => setSort(v as Sort)} options={SORTS.map((k) => [k, t.scan.sorts[k]])} className="w-40" />
                </Field>
              </div>
              <div className="flex flex-wrap items-end gap-3">
                <Button disabled={!chosen.length || download.isPending} onClick={() => download.mutate()}>
                  {download.isPending ? <Loader2 className="animate-spin" /> : <Download />}
                  {t.scan.download(chosen.length)}
                </Button>
                <Button variant="outline" onClick={() => saveCsv(chosen.length ? chosen : shown)}>
                  <FileSpreadsheet />
                  {t.scan.exportCsv}
                </Button>
                {current?.mode === "account" && (
                  <Button variant="outline" disabled={follow.isPending} onClick={() => follow.mutate()}>
                    {follow.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
                    {t.scan.follow}
                  </Button>
                )}
                <div className="ml-auto flex flex-wrap items-end gap-2">
                  <Field label={t.scan.selectFrom}>
                    <Input inputMode="numeric" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value.replace(/\D/g, "") })} className="w-20" />
                  </Field>
                  <Field label={t.scan.selectTo}>
                    <Input inputMode="numeric" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value.replace(/\D/g, "") })} className="w-20" />
                  </Field>
                  <Button variant="outline" onClick={selectRange}>
                    {t.scan.selectRange}
                  </Button>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-sm" aria-live="polite">
                <span className="font-medium">{t.scan.selected(chosen.length)}</span>
                <button type="button" className="text-muted-foreground underline-offset-2 hover:underline" onClick={() => setSelected(new Set(shown.map((r) => r.id)))}>
                  {t.scan.selectAll}
                </button>
                {chosen.length > 0 && (
                  <button type="button" className="text-muted-foreground underline-offset-2 hover:underline" onClick={() => setSelected(new Set())}>
                    {t.scan.clearSelection}
                  </button>
                )}
                {notice && (
                  <span className="text-muted-foreground">
                    {notice} ·{" "}
                    <Link to="/tools" className="underline underline-offset-2">
                      {t.scan.openTools}
                    </Link>
                  </span>
                )}
              </div>
              {shown.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t.scan.noRows}</p>
              ) : (
                <div className="max-h-[70vh] overflow-auto rounded-md border">
                  <table className="w-full min-w-[56rem] border-collapse text-left text-[13px]">
                    <thead className="sticky top-0 z-10 bg-panel text-xs text-muted-foreground">
                      <tr>
                        <th className="w-10 p-2">
                          <input
                            type="checkbox"
                            aria-label={t.scan.selectAll}
                            checked={chosen.length === shown.length}
                            onChange={(e) => setSelected(e.target.checked ? new Set(shown.map((r) => r.id)) : new Set())}
                          />
                        </th>
                        <th className="w-12 p-2">{t.scan.columns.n}</th>
                        <th className="w-28 p-2">{t.scan.columns.cover}</th>
                        <th className="w-36 p-2">{t.scan.columns.id}</th>
                        <th className="p-2">{t.scan.columns.title}</th>
                        <th className="w-28 p-2">{t.scan.columns.account}</th>
                        <th className="w-20 p-2 text-right">{t.scan.columns.likes}</th>
                        <th className="w-24 p-2 text-right">{t.scan.columns.views}</th>
                        <th className="w-16 p-2 text-right">{t.scan.columns.length}</th>
                        <th className="w-24 p-2">{t.scan.columns.date}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.map((r, i) => (
                        <tr key={r.id} className={cn("border-t align-top", selected.has(r.id) && "bg-cyan/5")}>
                          <td className="p-2">
                            <input type="checkbox" aria-label={r.video_id} checked={selected.has(r.id)} onChange={() => toggle(r.id)} />
                          </td>
                          <td className="p-2 font-mono text-muted-foreground tabular-nums">{i + 1}</td>
                          <td className="p-2">
                            <ExternalA href={r.url}>
                              {r.thumbnail ? (
                                <img src={r.thumbnail} alt="" loading="lazy" referrerPolicy="no-referrer" className="aspect-video w-24 rounded bg-muted object-cover" />
                              ) : (
                                <div className="aspect-video w-24 rounded bg-muted" />
                              )}
                            </ExternalA>
                          </td>
                          <td className="p-2 font-mono text-xs break-all">{r.video_id}</td>
                          <td className="p-2">
                            <ExternalA href={r.url} className="line-clamp-3 break-words underline-offset-2 hover:underline">
                              {r.title || r.video_id}
                            </ExternalA>
                          </td>
                          <td className="p-2 text-xs break-words text-muted-foreground">{r.uploader || t.scan.unknown}</td>
                          <td className="p-2 text-right font-mono tabular-nums">{num(r.likes)}</td>
                          <td className="p-2 text-right font-mono tabular-nums">{num(r.views)}</td>
                          <td className="p-2 text-right font-mono text-muted-foreground tabular-nums">{mmss(r.duration)}</td>
                          <td className="p-2 text-xs text-muted-foreground">{day(r.pubdate)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
