import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Check,
  Clapperboard,
  ListPlus,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  Undo2,
} from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { Choice } from "@/components/form";
import { Panel } from "@/components/studio";
import { lineAt, mmss, type Mark } from "@/components/timeline";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Api, Motion, Script, ScriptLine, ScriptView } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const MIN_LINES = 3; // như engine (edit.MIN_LINES)

type Row = ScriptLine & { key: number; was?: string }; // was: prompt ảnh đã lưu (ảnh hiện có ứng với prompt này)

const MOTIONS: Motion[] = ["zoom_in", "zoom_out", "pan_left", "pan_right"];

const countWords = (text: string) => text.split(/\s+/).filter(Boolean).length;
/** Chỉ phần gửi lên engine: bản lồng tiếng còn giữ thêm ai nói, câu gốc… để hiện, không gửi. Video AI gửi thêm
 * prompt ảnh, chuyển động và hạt giống của từng cảnh. */
const plain = (l: ScriptLine): ScriptLine => ({
  text: l.text,
  clips: l.clips,
  ...(l.image !== undefined ? { image: l.image, motion: l.motion, seed: l.seed } : {}),
});
const parseTags = (text: string) => text.split(/[\s,]+/).filter((w) => w.replace(/^#+/, ""));

function IconAction({
  label,
  onClick,
  disabled,
  className,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Button
      size="icon-xs"
      variant="ghost"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={className}
    >
      {children}
    </Button>
  );
}

/** Sửa kịch bản của dự án: tiêu đề trên video, từng dòng lời bình, mô tả, hashtag; rồi đọc và dựng lại. */
export function ScriptCard({
  api,
  id,
  active,
  canRender,
  measured,
  playhead = 0,
  onSeek,
}: {
  api: Api;
  id: number;
  active: boolean;
  canRender: boolean; // engine: giọng đã đọc còn khớp kịch bản đã lưu (chạy lại được từ bước dựng)
  measured?: Mark[] | null; // spans of the lines of the last voice, when it matches the saved script
  playhead?: number; // seconds into the video the player is at
  onSeek?: (sec: number) => void;
}) {
  const { data, error } = useQuery({ queryKey: ["script", id], queryFn: () => api.script(id) });
  const [justSaved, setJustSaved] = useState(false); // ở ngoài form: form được dựng lại sau mỗi lần lưu
  const onSaved = () => {
    setJustSaved(true);
    setTimeout(() => setJustSaved(false), 1500);
  };
  if (error) {
    return (
      <Panel title={t.script.title}>
        <p className="text-[13px] text-coral">{error.message}</p>
      </Panel>
    );
  }
  if (!data) return null;
  // Lưu xong (script.json đổi) thì dựng lại form từ bản engine trả về.
  return (
    <ScriptForm
      key={data.version}
      api={api}
      id={id}
      view={data}
      active={active}
      canRender={canRender}
      justSaved={justSaved}
      onSaved={onSaved}
      measured={measured}
      playhead={playhead}
      onSeek={onSeek}
    />
  );
}

function ScriptForm({
  api,
  id,
  view,
  active,
  canRender,
  justSaved,
  onSaved,
  measured,
  playhead,
  onSeek,
}: {
  api: Api;
  id: number;
  view: ScriptView;
  active: boolean;
  canRender: boolean;
  justSaved: boolean;
  onSaved: () => void;
  measured?: Mark[] | null;
  playhead: number;
  onSeek?: (sec: number) => void;
}) {
  const qc = useQueryClient();
  const saved = view.script;
  const isDub = view.dub != null; // bản lồng tiếng: mỗi dòng gắn với một câu gốc, không thêm / dời / xoá
  const isAi = view.ai != null; // video AI: mỗi dòng là một cảnh (lời + prompt ảnh + chuyển động)
  const nextKey = useRef(saved.lines.length);
  const [title, setTitle] = useState(saved.title_fr);
  const [style, setStyle] = useState(saved.style ?? "");
  const [rows, setRows] = useState<Row[]>(() => saved.lines.map((l, i) => ({ ...l, key: i, was: l.image })));
  const [description, setDescription] = useState(saved.description);
  const [tags, setTags] = useState(saved.hashtags.join(" "));

  const draft: Script = {
    title_fr: title,
    lines: rows.map(plain),
    description,
    hashtags: parseTags(tags),
    ...(isAi ? { style } : {}),
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify({ ...saved, lines: saved.lines.map(plain) });
  const filled = rows.filter((r) => r.text.trim());
  const words = filled.reduce((n, r) => n + countWords(r.text), 0);
  const est = words / view.words_per_sec + view.tail;
  const inRange = est >= view.min_seconds && est <= view.max_seconds;
  const valid = title.trim() !== "" && filled.length >= (isDub ? 1 : MIN_LINES);

  const refresh = (v?: ScriptView) => {
    if (v) qc.setQueryData(["script", id], v);
    qc.invalidateQueries({ queryKey: ["project", id] });
    qc.invalidateQueries({ queryKey: ["projects"] });
  };
  const save = useMutation({
    mutationFn: () => api.saveScript(id, draft),
    onSuccess: (v) => {
      onSaved();
      refresh(v);
    },
  });
  // Lưu (nếu có sửa) rồi chạy lại từ bước Giọng đọc và dựng, giữ kịch bản này. Video AI mà lời đọc không đổi thì
  // chỉ dựng lại (không đọc lại giọng): ảnh đổi prompt được làm lúc dựng.
  const sameText = rows.length === saved.lines.length && rows.every((r, i) => r.text.trim() === saved.lines[i].text.trim());
  const render = useMutation({
    mutationFn: async () => {
      const v = dirty ? await api.saveScript(id, draft) : undefined;
      await api.retry(id, isAi && canRender && sameText ? "render" : "voice");
      return v;
    },
    onSuccess: (v) => refresh(v),
  });
  // Video AI: xin ảnh mới cho một cảnh (hạt giống mới); ảnh được làm ở lần dựng tới.
  const redo = useMutation({ mutationFn: (i: number) => api.redoScene(id, i), onSuccess: (v) => refresh(v) });
  const busy = active || save.isPending || render.isPending || redo.isPending;

  const edit = (i: number, text: string) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, text } : r)));
  const patch = (i: number, p: Partial<ScriptLine>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const move = (i: number, d: -1 | 1) =>
    setRows((rs) => {
      const out = [...rs];
      [out[i], out[i + d]] = [out[i + d], out[i]];
      return out;
    });
  const insert = (at: number) =>
    setRows((rs) => [
      ...rs.slice(0, at),
      { text: "", clips: [], ...(isAi ? { image: "", motion: "zoom_in" as Motion, seed: 0 } : {}), key: nextKey.current++ },
      ...rs.slice(at),
    ]);
  const remove = (i: number) => setRows((rs) => rs.filter((_, j) => j !== i));
  const reset = () => {
    setTitle(saved.title_fr);
    setStyle(saved.style ?? "");
    setRows(saved.lines.map((l, i) => ({ ...l, key: nextKey.current + i, was: l.image })));
    nextKey.current += saved.lines.length;
    setDescription(saved.description);
    setTags(saved.hashtags.join(" "));
  };

  // Start of each line: the measured voice when the rows are what was voiced, otherwise counted from the words (≈).
  const exact = !dirty && !!measured && measured.length === rows.length;
  const spans: Mark[] = exact
    ? measured!
    : rows.reduce<Mark[]>((acc, r) => {
        const start = acc.length ? acc[acc.length - 1].end : 0;
        return [...acc, { start, end: start + countWords(r.text) / view.words_per_sec }];
      }, []);
  const startOf = (i: number, r: Row) => (isDub && r.at != null ? r.at : spans[i]?.start);
  const playRow = lineAt(spans, playhead);
  const [editing, setEditing] = useState<number | null>(null); // row being edited (focus is inside it)
  const current = editing ?? (playhead > 0 ? playRow : -1);

  return (
    <section className="flex flex-col border-b bg-panel">
      <PanelHead title={t.script.title} aside={t.studio.lineCount(rows.length)} />
      <p className="px-4 pt-4 text-xs leading-[18px] text-muted-foreground">{isAi ? t.ai.scriptHint : isDub ? t.script.dubHint : t.script.hint}</p>
      <div className="grid gap-4 p-4">
        <Field label={t.script.videoTitle}>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={100} disabled={busy} aria-label={t.script.videoTitle} />
        </Field>
        {isAi && (
          <Field label={t.ai.style} hint={t.ai.styleHint}>
            <Input value={style} onChange={(e) => setStyle(e.target.value)} maxLength={300} disabled={busy} aria-label={t.ai.style} />
          </Field>
        )}
      </div>

      <div className="flex h-9 items-center justify-between gap-3 border-y bg-ground px-4 font-mono text-xs leading-4 tracking-[0.06em] text-muted-foreground uppercase">
        <span>
          {t.script.lines}
          {isDub && view.dub?.register && <span className="ml-3 normal-case tracking-normal">{t.dub.register}: {view.dub.register}</span>}
        </span>
        {!isDub && <span className="normal-case tracking-normal">{t.studio.wordsClips}</span>}
      </div>
      <ol onBlur={(e) => !e.currentTarget.contains(e.relatedTarget as Node | null) && setEditing(null)}>
        {rows.map((r, i) => {
          const on = i === current;
          const start = startOf(i, r);
          return (
            <li
              key={r.key}
              onFocus={() => setEditing(i)}
              className={cn("relative grid grid-cols-[28px_52px_minmax(0,1fr)_auto] items-start gap-x-3 border-b px-4 py-3", on ? "bg-raised" : "bg-panel")}
            >
              {on && <span className="absolute inset-y-0 left-0 w-0.5 bg-amber" />}
              <span className={cn("pt-2 font-mono text-xs tabular-nums", on ? "text-amber" : "text-muted-foreground")}>{String(i + 1).padStart(2, "0")}</span>
              <button
                type="button"
                disabled={!onSeek || start == null}
                onClick={() => start != null && onSeek?.(start)}
                title={t.studio.seekTo}
                className={cn("mt-1.5 h-6 text-left font-mono text-xs tabular-nums", on ? "text-cyan" : "text-muted-foreground", onSeek && "hover:text-cyan")}
              >
                {start != null ? `${exact || (isDub && r.at != null) ? "" : "≈"}${mmss(start)}` : ""}
              </button>
              <div className="min-w-0 space-y-2">
                {isDub && (
                  <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
                    {r.kind === "intro" || r.kind === "outro" ? (
                      <span className="font-medium">{r.kind === "intro" ? t.script.intro : t.script.outro}</span>
                    ) : (
                      r.speaker && <span className="font-medium">{r.speaker}</span>
                    )}
                    {r.zh && (
                      <span className="min-w-0 truncate" title={r.zh} lang="zh">
                        {t.script.original}: {r.zh}
                      </span>
                    )}
                  </div>
                )}
                {isAi && (
                  <div className="flex gap-3">
                    <div className="aspect-[9/16] w-14 shrink-0 overflow-hidden rounded-xs border bg-monitor">
                      {r.picture ? (
                        <img
                          src={api.mediaUrl(r.picture, view.version)}
                          alt=""
                          loading="lazy"
                          className={cn("size-full object-cover", r.image !== r.was && "opacity-40")}
                        />
                      ) : (
                        <span className="grid size-full place-items-center p-1 text-center text-xs leading-tight text-muted-foreground">
                          {t.ai.noPicture}
                        </span>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <Textarea
                        value={r.text}
                        onChange={(e) => edit(i, e.target.value)}
                        className={rowField(on)}
                        rows={2}
                        disabled={busy}
                        aria-label={`${t.script.lines} ${i + 1}`}
                      />
                    </div>
                  </div>
                )}
                {!isAi && (
                  <Textarea
                    value={r.text}
                    onChange={(e) => edit(i, e.target.value)}
                    className={rowField(on)}
                    rows={2}
                    disabled={busy}
                    aria-label={`${t.script.lines} ${i + 1}`}
                  />
                )}
                {isAi && (
                  <>
                    <Textarea
                      value={r.image ?? ""}
                      onChange={(e) => patch(i, { image: e.target.value })}
                      className="min-h-0 font-mono text-xs leading-5 text-muted-foreground"
                      rows={2}
                      disabled={busy}
                      placeholder={t.ai.imagePlaceholder}
                      aria-label={`${t.ai.image} ${i + 1}`}
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <Choice
                        value={r.motion ?? "zoom_in"}
                        onChange={(v) => patch(i, { motion: v as Motion })}
                        options={MOTIONS.map((m) => [m, t.ai.motions[m]])}
                        className="h-8 w-36 text-xs"
                      />
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => redo.mutate(i)}
                        disabled={busy || dirty}
                        title={dirty ? t.ai.saveFirst : t.ai.newPictureTitle}
                      >
                        <RefreshCw />
                        {t.ai.newPicture}
                      </Button>
                      {!r.picture && !!r.seed && <span className="text-xs text-muted-foreground">{t.ai.pending}</span>}
                    </div>
                  </>
                )}
                {!isDub && on && (
                  <div className="flex items-center gap-1">
                    <IconAction label={t.script.moveUp} onClick={() => move(i, -1)} disabled={busy || i === 0}>
                      <ArrowUp />
                    </IconAction>
                    <IconAction label={t.script.moveDown} onClick={() => move(i, 1)} disabled={busy || i === rows.length - 1}>
                      <ArrowDown />
                    </IconAction>
                    <IconAction label={t.script.insertBelow} onClick={() => insert(i + 1)} disabled={busy}>
                      <ListPlus />
                    </IconAction>
                    <IconAction label={t.script.removeLine} onClick={() => remove(i)} disabled={busy} className="text-coral hover:text-coral">
                      <Trash2 />
                    </IconAction>
                  </div>
                )}
              </div>
              <div
                className={cn(
                  "w-[112px] pt-2 text-right font-mono text-xs leading-4 tabular-nums text-muted-foreground",
                  isDub && r.max_chars != null && r.text.length > r.max_chars && "text-amber",
                )}
              >
                {isDub && r.max_chars != null ? (
                  t.script.chars(r.text.length, r.max_chars)
                ) : isAi ? (
                  t.script.words(countWords(r.text))
                ) : (
                  <>
                    {t.script.words(countWords(r.text))}
                    <br />
                    {t.script.clips(r.clips.length)}
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      <div className="flex min-h-12 items-center justify-between gap-3 border-b px-4">
        {!isDub ? (
          <Button variant="ghost" onClick={() => insert(rows.length)} disabled={busy}>
            <Plus />
            {t.script.addLine}
          </Button>
        ) : (
          <span />
        )}
        {!isDub && (
          <span className={cn("font-mono text-xs tabular-nums", inRange ? "text-muted-foreground" : "text-amber")}>
            {t.script.words(words)} · {t.script.estimate(est)}
          </span>
        )}
      </div>
      {(!inRange && !isDub) || (!isDub && filled.length < MIN_LINES) || (view.stale && !dirty) ? (
        <div className="grid gap-1 border-b px-4 py-3 text-xs leading-[18px]">
          {!isDub && !inRange && <div className="text-amber">{t.script.outOfRange(view.min_seconds, view.max_seconds)}</div>}
          {!isDub && filled.length < MIN_LINES && <div className="text-coral">{t.script.minLines(MIN_LINES)}</div>}
          {view.stale && !dirty && <div className="text-amber">{t.script.stale}</div>}
        </div>
      ) : null}

      <div className="grid gap-4 border-b p-4">
        <Field label={t.script.description}>
          <Textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="min-h-16"
            disabled={busy}
            aria-label={t.script.description}
          />
        </Field>
        <Field label={t.script.hashtags} hint={t.script.hashtagsHint}>
          <Input value={tags} onChange={(e) => setTags(e.target.value)} disabled={busy} aria-label={t.script.hashtags} />
        </Field>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 bg-strip p-4">
        {(save.error || render.error || redo.error) && (
          <p className="mr-auto text-[13px] text-coral">{(save.error ?? render.error ?? redo.error)?.message}</p>
        )}
        {dirty && (
          <Button variant="ghost" className="mr-auto" onClick={reset} disabled={busy}>
            <Undo2 />
            {t.script.reset}
          </Button>
        )}
        <Button variant="secondary" onClick={() => save.mutate()} disabled={busy || !dirty || !valid}>
          {save.isPending ? <Loader2 className="animate-spin" /> : justSaved ? <Check /> : <Save />}
          {justSaved ? t.script.saved : t.script.save}
        </Button>
        <Button
          size="lg"
          variant={dirty || view.stale ? "default" : "secondary"}
          onClick={() => render.mutate()}
          disabled={busy || !valid}
        >
          {render.isPending ? <Loader2 className="animate-spin" /> : <Clapperboard />}
          {dirty ? t.script.saveAndRender : t.script.render}
        </Button>
      </div>
    </section>
  );
}

/** A line's text box: it blends into the row until it is the one being edited. */
const rowField = (on: boolean) =>
  cn("min-h-0 resize-none px-2.5 py-1.5 leading-5", on ? "bg-ground" : "border-transparent bg-transparent hover:border-hairline-strong");

function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs leading-[18px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

function PanelHead({ title, aside }: { title: string; aside?: ReactNode }) {
  return (
    <header className="flex h-10 shrink-0 items-center justify-between gap-3 border-b bg-strip px-4">
      <h2 className="font-mono text-xs leading-4 font-medium tracking-[0.06em] text-muted-foreground uppercase">{title}</h2>
      {aside && <span className="font-mono text-xs text-muted-foreground tabular-nums">{aside}</span>}
    </header>
  );
}
