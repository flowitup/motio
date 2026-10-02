import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Loader2, Send } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Panel, Segmented } from "@/components/studio";
import { Input } from "@/components/ui/input";
import { ApiError, type Api, type PublishMode, type PublishRecord, type VideoVersion } from "@/lib/api";
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
            onClick={() => send.mutate()}
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
