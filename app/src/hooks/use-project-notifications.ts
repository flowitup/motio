import { useQuery } from "@tanstack/react-query";
import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";
import { useEffect, useRef } from "react";
import { useApi } from "@/lib/api";
import { inTauri } from "@/lib/engine";
import { t } from "@/i18n";

async function notify(title: string) {
  if (!inTauri) return;
  let ok = await isPermissionGranted();
  if (!ok) ok = (await requestPermission()) === "granted";
  if (ok) sendNotification({ title: t.appName, body: title });
}

/** Thông báo hệ thống khi một dự án chuyển sang xong / lỗi / chờ duyệt. */
export function useProjectNotifications() {
  const api = useApi();
  const { data } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api!.projects(),
    enabled: !!api,
    refetchInterval: 4_000,
  });
  const seen = useRef<Map<number, string> | null>(null);

  useEffect(() => {
    if (!data) return;
    const prev = seen.current;
    seen.current = new Map(data.map((p) => [p.id, p.status]));
    if (!prev) return; // lần đầu: chỉ ghi nhận, không báo
    for (const p of data) {
      const before = prev.get(p.id);
      if (before && before !== p.status) {
        const title = p.meta.title || p.title;
        if (p.status === "done") notify(t.notify.done(title));
        if (p.status === "review") notify(t.notify.review(title));
        if (p.status === "failed") notify(t.notify.failed(title));
      }
    }
  }, [data]);

  useEffect(() => {
    seen.current = null;
  }, [api]);
}
