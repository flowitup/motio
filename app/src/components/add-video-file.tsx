import { Loader2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { Api } from "@/lib/api";
import { t } from "@/i18n";

/** Thêm file video có sẵn (tự tải từ Douyin hay nơi khác) làm nguồn: gửi lên engine rồi trả link `file:…` để dùng như link. */
export function AddVideoFile({ api, onAdded, disabled }: { api: Api; onAdded: (link: string) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [pct, setPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const send = async (file: File) => {
    setError(null);
    setPct(0);
    try {
      onAdded((await api.uploadVideo(file, setPct)).link);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPct(null);
      if (input.current) input.current.value = "";
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
