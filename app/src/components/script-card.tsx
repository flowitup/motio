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
import { Choice, Field } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { Api, Motion, Script, ScriptLine, ScriptView } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const MIN_LINES = 3; // như engine (edit.MIN_LINES)

const clockOf = (sec: number) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;

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
}: {
  api: Api;
  id: number;
  active: boolean;
  canRender: boolean; // engine: giọng đã đọc còn khớp kịch bản đã lưu (chạy lại được từ bước dựng)
}) {
  const { data, error } = useQuery({ queryKey: ["script", id], queryFn: () => api.script(id) });
  const [justSaved, setJustSaved] = useState(false); // ở ngoài form: form được dựng lại sau mỗi lần lưu
  const onSaved = () => {
    setJustSaved(true);
    setTimeout(() => setJustSaved(false), 1500);
  };
  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t.script.title}</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-destructive">{error.message}</CardContent>
      </Card>
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
}: {
  api: Api;
  id: number;
  view: ScriptView;
  active: boolean;
  canRender: boolean;
  justSaved: boolean;
  onSaved: () => void;
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

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.script.title}</CardTitle>
        <CardDescription>{isAi ? t.ai.scriptHint : isDub ? t.script.dubHint : t.script.hint}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm">
        <Field label={t.script.videoTitle}>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={100}
            disabled={busy}
            aria-label={t.script.videoTitle}
          />
        </Field>

        {isAi && (
          <Field label={t.ai.style} hint={t.ai.styleHint}>
            <Input value={style} onChange={(e) => setStyle(e.target.value)} maxLength={300} disabled={busy} aria-label={t.ai.style} />
          </Field>
        )}

        <div className="grid gap-2">
          <div className="flex flex-wrap items-baseline gap-x-3 text-sm">
            <span className="font-medium">{t.script.lines}</span>
            {isDub && view.dub?.register && (
              <span className="text-xs text-muted-foreground">
                {t.dub.register}: {view.dub.register}
              </span>
            )}
          </div>
          <ol className="grid gap-2">
            {rows.map((r, i) => (
              <li key={r.key} className="flex items-start gap-2">
                <span className="w-5 shrink-0 pt-2 text-right text-xs text-muted-foreground tabular-nums">{i + 1}</span>
                {isAi && (
                  <div className="aspect-[9/16] w-14 shrink-0 overflow-hidden rounded-md bg-muted">
                    {r.picture ? (
                      <img
                        src={api.mediaUrl(r.picture, view.version)}
                        alt=""
                        loading="lazy"
                        className={cn("size-full object-cover", r.image !== r.was && "opacity-40")}
                      />
                    ) : (
                      <span className="grid size-full place-items-center p-1 text-center text-[10px] leading-tight text-muted-foreground">
                        {t.ai.noPicture}
                      </span>
                    )}
                  </div>
                )}
                <div className="min-w-0 flex-1 space-y-1">
                  {isDub && (
                    <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
                      {r.at != null && <span className="tabular-nums">{clockOf(r.at)}</span>}
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
                  <Textarea
                    value={r.text}
                    onChange={(e) => edit(i, e.target.value)}
                    className="min-h-0 text-sm"
                    rows={2}
                    disabled={busy}
                    aria-label={`${t.script.lines} ${i + 1}`}
                  />
                  {isAi && (
                    <>
                      <Textarea
                        value={r.image ?? ""}
                        onChange={(e) => patch(i, { image: e.target.value })}
                        className="min-h-0 text-xs text-muted-foreground"
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
                          className="h-7 w-32 text-xs"
                        />
                        <Button
                          size="xs"
                          variant="outline"
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
                  <div
                    className={cn(
                      "text-xs text-muted-foreground",
                      isDub && r.max_chars != null && r.text.length > r.max_chars && "text-amber-700 dark:text-amber-400",
                    )}
                  >
                    {isDub && r.max_chars != null
                      ? t.script.chars(r.text.length, r.max_chars)
                      : isAi
                        ? t.script.words(countWords(r.text))
                        : `${t.script.words(countWords(r.text))} · ${t.script.clips(r.clips.length)}`}
                  </div>
                </div>
                {!isDub && (
                  <div className="grid shrink-0 grid-cols-2 gap-0.5">
                    <IconAction label={t.script.moveUp} onClick={() => move(i, -1)} disabled={busy || i === 0}>
                      <ArrowUp />
                    </IconAction>
                    <IconAction label={t.script.insertBelow} onClick={() => insert(i + 1)} disabled={busy}>
                      <ListPlus />
                    </IconAction>
                    <IconAction label={t.script.moveDown} onClick={() => move(i, 1)} disabled={busy || i === rows.length - 1}>
                      <ArrowDown />
                    </IconAction>
                    <IconAction label={t.script.removeLine} onClick={() => remove(i)} disabled={busy} className="hover:text-destructive">
                      <Trash2 />
                    </IconAction>
                  </div>
                )}
              </li>
            ))}
          </ol>
          {!isDub && (
            <div>
              <Button size="sm" variant="outline" onClick={() => insert(rows.length)} disabled={busy}>
                <Plus />
                {t.script.addLine}
              </Button>
            </div>
          )}
        </div>

        <Field label={t.script.description}>
          <Textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="min-h-16 text-sm"
            disabled={busy}
            aria-label={t.script.description}
          />
        </Field>
        <Field label={t.script.hashtags} hint={t.script.hashtagsHint}>
          <Input value={tags} onChange={(e) => setTags(e.target.value)} disabled={busy} aria-label={t.script.hashtags} />
        </Field>

        <div className="grid gap-1 text-xs">
          {!isDub && (
            <>
              <div className={cn("text-muted-foreground", !inRange && "text-amber-700 dark:text-amber-400")}>
                {t.script.words(words)} · {t.script.estimate(est)}
              </div>
              {!inRange && (
                <div className="text-amber-700 dark:text-amber-400">{t.script.outOfRange(view.min_seconds, view.max_seconds)}</div>
              )}
              {filled.length < MIN_LINES && <div className="text-destructive">{t.script.minLines(MIN_LINES)}</div>}
            </>
          )}
          {view.stale && !dirty && <div className="text-amber-700 dark:text-amber-400">{t.script.stale}</div>}
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2">
          {(save.error || render.error || redo.error) && (
            <p className="mr-auto text-destructive">{(save.error ?? render.error ?? redo.error)?.message}</p>
          )}
          {dirty && (
            <Button variant="ghost" onClick={reset} disabled={busy}>
              <Undo2 />
              {t.script.reset}
            </Button>
          )}
          <Button variant="outline" onClick={() => save.mutate()} disabled={busy || !dirty || !valid}>
            {save.isPending ? <Loader2 className="animate-spin" /> : justSaved ? <Check /> : <Save />}
            {justSaved ? t.script.saved : t.script.save}
          </Button>
          <Button
            variant={dirty || view.stale ? "default" : "outline"}
            onClick={() => render.mutate()}
            disabled={busy || !valid}
          >
            {render.isPending ? <Loader2 className="animate-spin" /> : <Clapperboard />}
            {dirty ? t.script.saveAndRender : t.script.render}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
