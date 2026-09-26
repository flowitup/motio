import { useEffect, useState } from "react";
import type { Api, ProgressEvent } from "@/lib/api";

/** Theo dõi tiến trình dự án qua SSE khi dự án chưa xong. */
export function useProjectEvents(api: Api, id: number, active: boolean, onEnd: () => void) {
  const [ev, setEv] = useState<ProgressEvent | null>(null);

  useEffect(() => {
    if (!active) return;
    setEv(null);
    const es = new EventSource(api.eventsUrl(id));
    es.onmessage = (m) => setEv(JSON.parse(m.data));
    es.addEventListener("end", () => {
      es.close();
      onEnd();
    });
    return () => es.close();
    // onEnd cố ý không nằm trong deps: chỉ mở lại luồng khi đổi dự án / trạng thái.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, id, active]);

  return ev;
}
