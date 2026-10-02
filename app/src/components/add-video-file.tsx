import { Loader2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { Api } from "@/lib/api";
import { t } from "@/i18n";

/** Thêm file video có sẵn (tự tải từ Douyin hay nơi khác) làm nguồn: gửi lên engine rồi trả link `file:…` để dùng như link. */
export function AddVideoFile({ api, onAdded, disabled }: { api: Api; onAdded: (link: string) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [pct, setPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const upload = useRef<AbortController | null>(null);
  // The panel that holds this button can close (or another trend's panel can open) while a big file is still on its way:
  // the upload stops with it, so a finished file never lands in the wrong list of links.
  useEffect(() => () => upload.current?.abort(), []);
  const send = async (file: File) => {
    const ctl = new AbortController();
    upload.current = ctl;
    setError(null);
    setPct(0);
    try {
      const done = await api.uploadVideo(file, setPct, ctl.signal);
      if (!ctl.signal.aborted) onAdded(done.link);
    } catch (e) {
      if (!ctl.signal.aborted) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (!ctl.signal.aborted) {
        setPct(null);
        if (input.current) input.current.value = "";
      }
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        ref={input}
        type="file"
        accept="video/*,.mkv,.flv,.ts"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void send(f);
        }}
      />
      <Button type="button" size="sm" variant="outline" disabled={disabled || pct !== null} onClick={() => input.current?.click()}>
        {pct !== null ? <Loader2 className="animate-spin" /> : <Upload />}
        {pct !== null ? t.upload.uploading(pct) : t.upload.add}
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </div>
  );
}
