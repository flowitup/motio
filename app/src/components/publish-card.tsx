import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Loader2, Send } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, type Api, type PublishMode, type PublishRecord } from "@/lib/api";
import { t } from "@/i18n";

const MODES: PublishMode[] = ["draft", "schedule", "now"];

/** Gửi video của dự án sang Postiz: chọn kênh, nháp / lên lịch / đăng ngay. */
export function PublishCard({
  api,
  projectId,
  history,
  onSent,
}: {
  api: Api;
  projectId: number;
  history: PublishRecord[];
  onSent: () => void;
}) {
  const { data: channels, error } = useQuery({
    queryKey: ["postiz-channels"],
    queryFn: () => api.postizChannels(),
    retry: false,
    staleTime: 60_000,
  });
  const [picked, setPicked] = useState<string[]>([]);
  const [mode, setMode] = useState<PublishMode>("draft");
  const [when, setWhen] = useState("");

  const send = useMutation({
    mutationFn: () =>
      api.publish(projectId, {
        channels: picked,
        mode,
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
                disabled={c.disabled}
                onChange={() => toggle(c.id)}
              />
              <span>{c.name}</span>
              <span className="text-muted-foreground">· {c.provider}</span>
            </label>
          ))}
        </div>

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
                {h.mode === "schedule" && ` ${new Date(h.date).toLocaleString("vi-VN")}`} ·{" "}
                {h.channels.map((c) => c.name).join(", ")} · {t.age(h.at)}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
