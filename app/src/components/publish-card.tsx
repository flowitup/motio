import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Loader2, RotateCcw, Send } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { ConfirmAction } from "@/components/confirm-action";
import { Button } from "@/components/ui/button";
import { Panel, Segmented } from "@/components/studio";
import { Input } from "@/components/ui/input";
import { ApiError, type Api, type Channel, type PublishMode, type PublishRecord, type VideoVersion } from "@/lib/api";
import { t } from "@/i18n";

const MODES: PublishMode[] = ["draft", "schedule", "now"];
const VERSIONS: VideoVersion[] = ["vertical", "wide"];

/** Gửi video của dự án sang Postiz: chọn kênh, nháp / lên lịch / đăng ngay. */
export function PublishCard({
  api,
  projectId,
  channel,
  history,
  hasWide,
  sendError,
  onSent,
}: {
  api: Api;
  projectId: number;
  channel?: Channel; // kênh của dự án: chọn sẵn kênh Postiz và chế độ gửi của nó
  history: PublishRecord[];
  hasWide: boolean; // dự án có bản 16:9
  sendError?: string | null; // lần tự gửi gần nhất bị lỗi
  onSent: () => void;
}) {
  const { data: channels, error } = useQuery({
    queryKey: ["postiz-channels"],
    queryFn: () => api.postizChannels(),
    retry: false,
    staleTime: 60_000,
  });
  const [touched, setTouched] = useState<string[] | null>(null); // null = the channel's own Postiz channels
  const [chosenMode, setMode] = useState<PublishMode | null>(null); // null = the channel's send mode
  const [when, setWhen] = useState("");
  const [version, setVersion] = useState<VideoVersion>("vertical");
  const [confirming, setConfirming] = useState<"send" | "again" | null>(null);
  const fromChannel = (channel?.postiz ?? []).filter((id) => channels?.some((c) => c.id === id && !c.disabled));
  const picked = touched ?? fromChannel;
  const mode = chosenMode ?? channel?.send_mode ?? "draft";
  const nameOf = (id: string) => channels?.find((c) => c.id === id)?.name ?? id;

  const send = useMutation({
    mutationFn: () =>
      api.publish(projectId, {
        channels: picked,
        mode,
        version: hasWide ? version : "vertical",
        // datetime-local là giờ máy; toISOString() đổi sang UTC có "Z" cho engine
        ...(mode === "schedule" ? { date: new Date(when).toISOString() } : {}),
      }),
    onSuccess: () => {
      setTouched([]);
      onSent();
    },
    onSettled: () => setConfirming(null),
  });
  // One click: the channel's own Postiz channels, mode, posting time and 16:9 split, as an automatic send would do.
  const again = useMutation({
    mutationFn: async () => {
      const r = await api.resend(projectId);
      if (!r.sent && r.error) throw new Error(r.error);
      return r;
    },
    onSettled: () => {
      setConfirming(null);
      onSent();
    },
  });

  const toggle = (id: string) => {
    send.reset();
    setTouched((p) => {
      const cur = p ?? fromChannel;
      return cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    });
  };

  let body: ReactNode;
  if (error) {
    body =
      error instanceof ApiError && error.status === 409 ? (
        <p className="text-[13px] text-muted-foreground">
          {t.publish.notConfigured}{" "}
          <Link to="/settings" className="font-medium">
            {t.nav.settings}
          </Link>
        </p>
      ) : (
        <p className="text-[13px] text-coral">{error.message}</p>
      );
  } else if (!channels) {
    body = <Loader2 className="size-4 animate-spin" />;
  } else if (!channels.length) {
    body = <p className="text-[13px] text-muted-foreground">{t.publish.noChannels}</p>;
  } else {
    body = (
      <div className="space-y-4">
        {fromChannel.length > 0 && channel && (
          <div className="space-y-2 border-b pb-4">
            <p className="text-xs leading-[18px] text-muted-foreground">
              {t.publish.channelSetting(channel.name, fromChannel.map(nameOf), t.publish.modes[channel.send_mode])}
            </p>
            {sendError && <p className="text-xs leading-[18px] text-amber">{t.review.sendError}: {sendError}</p>}
            <Button
              variant="secondary"
              size="lg"
              className="w-full"
              onClick={() => (channel.send_mode === "now" ? setConfirming("again") : again.mutate())}
              disabled={again.isPending}
            >
              {again.isPending ? <Loader2 className="animate-spin" /> : <RotateCcw />}
              {t.publish.sendAgain}
            </Button>
            {again.error && <p className="text-[13px] text-coral">{again.error.message}</p>}
          </div>
        )}
        <div className="space-y-1">
          <div className="text-[13px] font-medium">{t.publish.channels}</div>
          {channels.map((c) => (
            <label key={c.id} className="flex min-h-10 items-center gap-3 text-[13px]">
              <input
                type="checkbox"
                className="size-[18px] accent-amber"
                checked={picked.includes(c.id)}
                disabled={c.disabled}
                onChange={() => toggle(c.id)}
              />
              <span>{c.name}</span>
              <span className="font-mono text-xs text-muted-foreground">· {c.provider}</span>
            </label>
          ))}
        </div>

        {hasWide && (
          <div className="space-y-2">
            <div className="text-[13px] font-medium">{t.publish.version}</div>
            <Segmented
              label={t.publish.version}
              value={version}
              onChange={setVersion}
              className="h-10 w-full"
              options={VERSIONS.map((v) => ({ value: v, label: t.projects.versions[v] }))}
            />
            <p className="text-xs leading-[18px] text-muted-foreground">{t.publish.versionHint}</p>
          </div>
        )}

        <div className="space-y-2">
          <div className="text-[13px] font-medium">{t.publish.sendAs}</div>
          <Segmented
            label={t.publish.sendAs}
            value={mode}
            onChange={setMode}
            className="h-10 w-full"
            options={MODES.map((m) => ({ value: m, label: t.publish.modes[m] }))}
          />
          <p className="text-xs leading-[18px] text-muted-foreground">{t.publish.modeHint[mode]}</p>
        </div>

        {mode === "schedule" && (
          <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
            {t.publish.when}
            <Input type="datetime-local" className="w-60 font-mono" value={when} onChange={(e) => setWhen(e.target.value)} />
          </label>
        )}

        <div className="grid gap-2">
          <Button
            variant="secondary"
            size="lg"
            className="w-full"
            onClick={() => (mode === "now" ? setConfirming("send") : send.mutate())}
            disabled={!picked.length || send.isPending || (mode === "schedule" && !when)}
          >
            {send.isPending ? <Loader2 className="animate-spin" /> : send.isSuccess ? <Check /> : <Send />}
            {send.isSuccess ? t.publish.sent : t.publish.send}
          </Button>
          {send.error && <span className="text-[13px] text-coral">{send.error.message}</span>}
        </div>
      </div>
    );
  }

  return (
    <Panel title={t.publish.title} bodyClassName="space-y-4">
        {body}
        <ConfirmAction
          open={confirming !== null}
          onOpenChange={(o) => !o && setConfirming(null)}
          title={t.publish.nowTitle}
          body={t.publish.nowBody((confirming === "again" ? fromChannel : picked).map(nameOf))}
          confirm={t.publish.nowConfirm}
          icon={<Send />}
          busy={send.isPending || again.isPending}
          onConfirm={() => (confirming === "again" ? again.mutate() : send.mutate())}
        />
        {history.length > 0 && (
          <div className="space-y-1 border-t pt-3 text-xs leading-[18px]">
            <div className="text-[13px] font-medium">{t.publish.history}</div>
            {[...history].reverse().map((h) => (
              <div key={h.at} className="text-muted-foreground">
                {t.publish.modes[h.mode]}
                {h.mode === "schedule" && ` ${t.dateTime(h.date)}`} ·{" "}
                {h.channels.map((c) => c.name).join(", ")}
                {h.version === "wide" && ` · ${t.projects.versions.wide}`} · {t.age(h.at)}
              </div>
            ))}
          </div>
        )}
    </Panel>
  );
}
