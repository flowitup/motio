import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Loader2, Send } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, isTiktok, type Api, type PublishMode, type PublishRecord, type VideoVersion } from "@/lib/api";
import { t } from "@/i18n";

const MODES: PublishMode[] = ["draft", "schedule", "now"];
const VERSIONS: VideoVersion[] = ["vertical", "wide"];

/** Gửi video của dự án sang Postiz: chọn kênh, nháp / lên lịch / đăng ngay. */
export function PublishCard({
  api,
  projectId,
  history,
  hasWide,
  onSent,
}: {
  api: Api;
  projectId: number;
  history: PublishRecord[];
  hasWide: boolean; // dự án có bản 16:9
  onSent: () => void;
}) {
  const { data: channels, error } = useQuery({
    queryKey: ["postiz-channels"],
    queryFn: () => api.postizChannels(),
    retry: false,
    staleTime: 60_000,
  });
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: () => api.health(), staleTime: 30_000 });
  const [picked, setPicked] = useState<string[]>([]);
  const [mode, setMode] = useState<PublishMode>("draft");
  const [when, setWhen] = useState("");
  const [version, setVersion] = useState<VideoVersion>("vertical");

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
      setPicked([]);
      onSent();
    },
  });

  const toggle = (id: string) => {
    send.reset();
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  };

  // Một video chỉ lên một tài khoản TikTok: tài khoản đã lên lịch / đã đăng (nháp không tính) hoặc đang chọn
  const sentTiktok = new Set(
    history.filter((h) => h.mode !== "draft").flatMap((h) => h.channels.filter((c) => isTiktok(c.provider)).map((c) => c.id)),
  );
  const pickedTiktok = channels?.find((c) => picked.includes(c.id) && isTiktok(c.provider));
  const tiktokLocked = (id: string) =>
    (!!pickedTiktok && pickedTiktok.id !== id) || (sentTiktok.size > 0 && !sentTiktok.has(id));
  const manyTiktok = (channels?.filter((c) => isTiktok(c.provider)).length ?? 0) > 1;

  let body: ReactNode;
  if (error) {
    body =
      error instanceof ApiError && error.status === 409 ? (
        <p className="text-sm text-muted-foreground">
          {t.publish.notConfigured}{" "}
          <Link to="/settings" className="underline">
            {t.nav.settings}
          </Link>
        </p>
      ) : (
        <p className="text-sm text-destructive">{error.message}</p>
      );
  } else if (!channels) {
    body = <Loader2 className="size-4 animate-spin" />;
  } else if (!channels.length) {
    body = <p className="text-sm text-muted-foreground">{t.publish.noChannels}</p>;
  } else {
    body = (
      <div className="space-y-4">
        <div className="space-y-1.5">
          <div className="text-sm font-medium">{t.publish.channels}</div>
          {channels.map((c) => (
            <label key={c.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 accent-primary"
                checked={picked.includes(c.id)}
                disabled={c.disabled || (isTiktok(c.provider) && tiktokLocked(c.id))}
                onChange={() => toggle(c.id)}
              />
              <span>{c.name}</span>
              <span className="text-muted-foreground">· {c.provider}</span>
            </label>
          ))}
          {manyTiktok && <p className="text-xs text-muted-foreground">{t.publish.oneTiktok}</p>}
          {pickedTiktok && health && !health.tiktok_direct && (
            <p className="text-xs text-muted-foreground">{t.publish.tiktokInbox}</p>
          )}
        </div>

        {hasWide && (
          <div className="space-y-1.5">
            <div className="text-sm font-medium">{t.publish.version}</div>
            <div className="flex flex-wrap gap-2">
              {VERSIONS.map((v) => (
                <Button key={v} size="sm" variant={version === v ? "default" : "outline"} onClick={() => setVersion(v)}>
                  {t.projects.versions[v]}
                </Button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">{t.publish.versionHint}</p>
          </div>
        )}

        <div className="space-y-1.5">
          <div className="flex flex-wrap gap-2">
            {MODES.map((m) => (
              <Button key={m} size="sm" variant={mode === m ? "default" : "outline"} onClick={() => setMode(m)}>
                {t.publish.modes[m]}
              </Button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">{t.publish.modeHint[mode]}</p>
        </div>

        {mode === "schedule" && (
          <label className="grid gap-1.5 text-sm">
            {t.publish.when}
            <Input type="datetime-local" className="w-60" value={when} onChange={(e) => setWhen(e.target.value)} />
          </label>
        )}

        <div className="flex items-center gap-3">
          <Button
            onClick={() => send.mutate()}
            disabled={!picked.length || send.isPending || (mode === "schedule" && !when)}
          >
            {send.isPending ? <Loader2 className="animate-spin" /> : send.isSuccess ? <Check /> : <Send />}
            {send.isSuccess ? t.publish.sent : t.publish.send}
          </Button>
          {send.error && <span className="text-sm text-destructive">{send.error.message}</span>}
        </div>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.publish.title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {body}
        {history.length > 0 && (
          <div className="space-y-1 border-t pt-3 text-sm">
            <div className="font-medium">{t.publish.history}</div>
            {[...history].reverse().map((h) => (
              <div key={h.at} className="text-muted-foreground">
                {t.publish.modes[h.mode]}
                {h.mode === "schedule" && ` ${t.dateTime(h.date)}`} ·{" "}
                {h.channels.map((c) => c.name).join(", ")}
                {h.version === "wide" && ` · ${t.projects.versions.wide}`}
                {!!h.tiktok_inbox?.length && ` · ${t.publish.inbox}`} · {t.age(h.at)}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
