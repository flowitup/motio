import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCheck, Loader2, Pencil, Play, RefreshCw, Undo2 } from "lucide-react";
import { useState } from "react";
import { Panel } from "@/components/studio";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { Api, Shot, ShotsView } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const BORDER: Record<Shot["state"], string> = {
  approved: "border-mint",
  ready: "border-border",
  failed: "border-coral",
  missing: "border-border",
};
const TEXT: Record<Shot["state"], string> = {
  approved: "text-mint",
  ready: "text-amber",
  failed: "text-coral",
  missing: "text-muted-foreground",
};

/** One shot: its picture, its line, and Approve / Redo. The prompt can be edited, then the shot is redone with it. */
function ShotTile({
  api,
  shot,
  version,
  busy,
  redoing,
  onApprove,
  onRedo,
}: {
  api: Api;
  shot: Shot;
  version: number;
  busy: boolean;
  redoing: boolean;
  onApprove: (on: boolean) => void;
  onRedo: (prompt?: string) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null); // null = not editing the prompt
  const approved = shot.state === "approved";
  return (
    <li className={cn("flex min-w-0 flex-col border bg-panel", BORDER[shot.state])}>
      <div className="relative aspect-[9/16] w-full overflow-hidden bg-monitor">
        {shot.picture ? (
          <img
            src={api.mediaUrl(shot.picture, version)}
            alt={`${t.shots.shot(shot.index + 1)}: ${shot.text}`}
            loading="lazy"
            className={cn("size-full object-cover", redoing && "opacity-30")}
          />
        ) : (
          <span className="grid size-full place-items-center p-2 text-center text-xs leading-[18px] text-muted-foreground">
            {shot.error ? shot.error : t.shots.noPicture}
          </span>
        )}
        {redoing && <Loader2 className="absolute inset-0 m-auto size-6 animate-spin text-amber" />}
        <span className="absolute top-1.5 left-1.5 bg-ground/85 px-1.5 py-0.5 font-mono text-[11px] leading-4 font-medium">
          {t.shots.shot(shot.index + 1)}
        </span>
        <span
          className={cn(
            "absolute top-1.5 right-1.5 bg-ground/85 px-1.5 py-0.5 font-mono text-[11px] leading-4 font-medium",
            TEXT[shot.state],
          )}
        >
          {t.shots.states[shot.state]}
        </span>
      </div>
      <p className="line-clamp-3 px-2.5 pt-2 text-xs leading-[18px] text-muted-foreground" title={shot.text}>
        {shot.text}
      </p>
      {draft !== null ? (
        <div className="grid min-w-0 gap-2 p-2.5">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={4}
            disabled={busy}
            aria-label={`${t.shots.prompt} ${shot.index + 1}`}
            className="min-h-0 w-full min-w-0 font-mono text-xs leading-5"
          />
          <Button
            size="sm"
            disabled={busy || !draft.trim()}
            onClick={() => {
              onRedo(draft.trim());
              setDraft(null);
            }}
          >
            <RefreshCw />
            {t.shots.redoPrompt}
          </Button>
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => setDraft(null)}>
            {t.shots.cancel}
          </Button>
        </div>
      ) : (
        <div className="grid gap-1.5 p-2.5">
          {approved ? (
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onApprove(false)} title={t.shots.unapprove}>
              <Undo2 />
              {t.shots.approved}
            </Button>
          ) : (
            <Button size="sm" disabled={busy || !shot.picture} onClick={() => onApprove(true)}>
              <Check />
              {t.shots.approve}
            </Button>
          )}
          <div className="grid grid-cols-2 gap-1.5">
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onRedo()} title={t.shots.redoTitle}>
              <RefreshCw />
              {t.shots.redo}
            </Button>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => setDraft(shot.image)} title={t.shots.editPrompt}>
              <Pencil />
              {t.shots.promptShort}
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

/** The project waits for the pictures to be reviewed: approve or redo each shot, then continue to the voice and render. */
export function ShotsCard({ api, id, onQueued }: { api: Api; id: number; onQueued: () => void }) {
  const qc = useQueryClient();
  const key = ["shots", id];
  const { data } = useQuery({ queryKey: key, queryFn: () => api.shots(id) });
  const set = (v: ShotsView) => qc.setQueryData(key, v);
  const redo = useMutation({ mutationFn: (a: { i: number; prompt?: string }) => api.redoShot(id, a.i, a.prompt), onSuccess: set });
  const approve = useMutation({ mutationFn: (a: { i: number; on: boolean }) => api.approveShot(id, a.i, a.on), onSuccess: set });
  const all = useMutation({ mutationFn: (on: boolean) => api.approveAllShots(id, on), onSuccess: set });
  const remake = useMutation({ mutationFn: () => api.redoFailedShots(id), onSuccess: onQueued });
  const go = useMutation({ mutationFn: () => api.continueShots(id), onSuccess: onQueued });
  const busy = redo.isPending || approve.isPending || all.isPending || remake.isPending || go.isPending;
  const error = redo.error ?? approve.error ?? all.error ?? remake.error ?? go.error;
  if (!data) return null;
  const open = data.failed + data.missing;
  return (
    <Panel title={t.shots.title} aside={t.shots.count(data.approved, data.total)} flush>
      <div className="grid gap-3 border-b p-4">
        <p className="text-xs leading-[18px] text-muted-foreground">{t.shots.hint}</p>
        {data.provider === "placeholder" && <p className="text-xs leading-[18px] text-amber">{t.shots.placeholderNote}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => all.mutate(true)}>
            {all.isPending && all.variables ? <Loader2 className="animate-spin" /> : <CheckCheck />}
            {t.shots.approveAll}
          </Button>
          <Button size="sm" variant="secondary" disabled={busy || data.approved === 0} onClick={() => all.mutate(false)}>
            <Undo2 />
            {t.shots.clearAll}
          </Button>
          {open > 0 && (
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => remake.mutate()}>
              {remake.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              {t.shots.redoFailed(open)}
            </Button>
          )}
          <span className="ml-auto font-mono text-xs text-muted-foreground tabular-nums">
            {data.ready ? t.shots.count(data.approved, data.total) : t.shots.left(data.total - data.approved)}
          </span>
          <Button size="lg" disabled={busy || !data.ready} onClick={() => go.mutate()}>
            {go.isPending ? <Loader2 className="animate-spin" /> : <Play />}
            {t.shots.continue}
          </Button>
        </div>
        <p className="font-mono text-[11px] leading-4 text-muted-foreground">{t.shots.cost(data.cost, data.price)}</p>
        {error && <p className="text-[13px] text-coral">{error.message}</p>}
      </div>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3 p-4">
        {data.shots.map((s) => (
          <ShotTile
            key={s.index}
            api={api}
            shot={s}
            version={data.version}
            busy={busy}
            redoing={redo.isPending && redo.variables?.i === s.index}
            onApprove={(on) => approve.mutate({ i: s.index, on })}
            onRedo={(prompt) => redo.mutate({ i: s.index, prompt })}
          />
        ))}
      </ul>
    </Panel>
  );
}
