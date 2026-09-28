import { useMemo } from "react";
import { useEngine } from "./engine";

export type Trend = {
  id: string;
  source: string;
  source_name: string;
  url: string | null;
  title_zh: string;
  title_fr: string;
  angle: string | null;
  reason: string | null;
  score: number;
  status: string;
  last_seen: number;
};

export type SourceInfo = {
  url: string;
  platform: string;
  uploader: string;
  title: string;
  duration: number;
  delogo?: { boxes: DelogoBox[]; rights: DelogoRights | null; method?: "lama"; at: number }; // bản sạch thay nguồn này
};

/** Khung quanh logo, theo pixel của khung hình video. */
export type DelogoBox = { x: number; y: number; w: number; h: number };
export type DelogoRights = "owned" | "licensed";
export type DelogoStatus = "idle" | "queued" | "running" | "done" | "failed";
/** Một video để xoá logo: nguồn dự án ("p<id>-<i>") hoặc file tải lên ("u<hex>"). */
export type DelogoTarget = {
  target: string;
  kind: "source" | "upload";
  name: string;
  project_id: number | null;
  index: number | null;
  url: string | null;
  width: number;
  height: number;
  duration: number;
  frame: string | null;
  frame_at: number | null;
  boxes: DelogoBox[];
  rights: DelogoRights | null; // xác nhận đã lưu của người dùng
  status: DelogoStatus;
  pct: number;
  error: string | null;
  phase: "model" | "fill" | null; // model = đang tải mô hình AI (lần đầu), fill = đang vẽ lại vùng logo
  eta: number | null; // giây còn lại, ước tính
  stopping: boolean;
  model_ready: boolean; // mô hình AI đã tải về máy chạy engine
  output: string | null;
  done_at: number | null;
  folder: string;
};
export type DelogoUpload = { target: string; name: string; created_at: number | null; status: DelogoStatus };

export type Rights = "unknown" | "owned" | "licensed" | "cc";

export type ProjectMeta = {
  topic?: string; // dự án chủ đề: chủ đề tự do ("" = chỉ link)
  subject?: { title_fr: string; angle: string };
  duration?: number;
  rights?: Rights;
  links?: string[];
  sources?: SourceInfo[];
  video?: string;
  thumb?: string;
  title?: string;
  description?: string;
  hashtags?: string[];
  tts?: string;
  voice?: string;
  elapsed?: number;
  postiz?: PublishRecord[];
};

export type PublishMode = "draft" | "schedule" | "now";
export type PostizChannel = {
  id: string;
  name: string;
  provider: string;
  picture: string | null;
  profile: string | null;
  disabled: boolean;
};
export type PublishRecord = {
  at: number;
  mode: PublishMode;
  date: string;
  channels: { id: string; name: string; provider: string }[];
  posts: { postId: string; integration: string }[];
};

export type ProjectStatus = "queued" | "running" | "done" | "failed";

export type Project = {
  id: number;
  trend_id: string | null;
  mode: "news" | "topic";
  title: string;
  status: ProjectStatus;
  step: string | null;
  pct: number;
  meta: ProjectMeta;
  created_at: number;
  updated_at: number;
};

export type RetryStep = "search" | "download" | "transcribe" | "script" | "voice";

export type ProjectDetail = Project & {
  log: string;
  folder: string;
  trend: Trend | null;
  retry: { auto: RetryStep; steps: RetryStep[] };
  has_script: boolean;
};

export type ScriptClip = { src: number; start: number; end: number };
export type ScriptLine = { text: string; clips: ScriptClip[] };
export type Script = { title_fr: string; lines: ScriptLine[]; description: string; hashtags: string[] };
/** Kịch bản cho trình sửa, kèm số liệu để ước lượng độ dài video. */
export type ScriptView = {
  script: Script;
  edited_at: number | null;
  stale: boolean; // video dựng trước lần sửa lời bình / tiêu đề gần nhất
  words_per_sec: number;
  min_seconds: number;
  max_seconds: number;
  tail: number;
  version: number;
};

export type ProgressEvent = { status: ProjectStatus; step: string | null; pct: number; log_tail: string[] };

export type Health = {
  version: string;
  platform: { system: string; machine: string; python: string };
  headless: boolean;
  providers: {
    llm: { provider: string; model: string };
    tts: string | null;
    asr: { engine: string; model: string };
  };
  ffmpeg: string | null;
  ffprobe: string | null;
  js_runtime: string | null;
  claude_cli: string | null;
  postiz: boolean;
  quota_left: number | null;
  data_dir: string;
};

export type RefreshState = {
  refreshing: boolean;
  last_refresh: number | null;
  last_result: { new?: number; scored?: number; errors?: Record<string, string>; error?: string } | null;
  busy: boolean;
  refresh_every_min: number; // 0 = chỉ cập nhật bằng tay
  next_refresh: number | null;
  watching: boolean;
  last_watch: number | null;
  last_watch_result: {
    checked?: number;
    new?: number;
    scored?: number;
    errors?: Record<string, string>; // id nguồn → lỗi
    score_error?: string;
    error?: string;
  } | null;
  next_watch: number | null;
};

export type WatchKind = "channel" | "playlist" | "space" | "search";
export type Site = "youtube" | "bilibili";

/** Nguồn theo dõi: kênh / playlist YouTube, không gian Bilibili, tìm kiếm đã lưu. */
export type Watch = {
  id: number;
  kind: WatchKind;
  site: Site;
  target: string; // URL, hoặc từ khoá khi kind = search
  name: string | null;
  rights: Rights;
  enabled: boolean;
  created_at: number;
  last_checked: number | null;
  last_error: string | null;
  new_count: number;
};

export type ClipStatus = "new" | "used" | "hidden";

/** Video mới tìm thấy ở một nguồn theo dõi. */
export type Clip = {
  id: string;
  watch_id: number | null;
  watch_name: string | null;
  site: Site;
  url: string;
  title: string;
  title_fr: string | null;
  reason: string | null;
  uploader: string | null;
  duration: number | null;
  views: number | null;
  thumbnail: string | null;
  score: number | null;
  first_seen: number;
  status: ClipStatus;
  rights: Rights | null;
  project_id: number | null;
};

export type SettingValue = { value: string; secret: boolean; source: "settings" | "env" | "default" };
export type Settings = Record<string, SettingValue>;
export type Voice = { id: string; name: string; labels: Record<string, string>; preview_url: string | null };

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function makeApi(url: string, token: string) {
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const r = await fetch(url + path, {
      method,
      headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) {
      let msg = r.statusText;
      try {
        msg = (await r.json()).detail ?? msg;
      } catch {
        /* không phải JSON */
      }
      throw new ApiError(r.status, msg);
    }
    return r.json();
  }
  const q = `token=${encodeURIComponent(token)}`;
  const dl = (key: string) => `/api/delogo/targets/${encodeURIComponent(key)}`;
  /** Tải file lên (multipart) bằng XHR để có tiến trình. */
  function upload(file: File, onProgress?: (pct: number) => void): Promise<DelogoTarget> {
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open("POST", `${url}/api/delogo/uploads`);
      x.setRequestHeader("Authorization", `Bearer ${token}`);
      x.upload.onprogress = (e) => e.lengthComputable && onProgress?.(Math.round((100 * e.loaded) / e.total));
      x.onload = () => {
        let body: { detail?: string } & Partial<DelogoTarget> = {};
        try {
          body = JSON.parse(x.responseText);
        } catch {
          /* không phải JSON */
        }
        if (x.status >= 200 && x.status < 300) resolve(body as DelogoTarget);
        else reject(new ApiError(x.status, body.detail ?? x.statusText));
      };
      x.onerror = () => reject(new ApiError(0, "Không kết nối được engine"));
      const form = new FormData();
      form.append("file", file);
      x.send(form);
    });
  }
  return {
    health: () => call<Health>("GET", "/api/health"),
    state: () => call<RefreshState>("GET", "/api/state"),
    trends: (source?: string) =>
      call<Trend[]>("GET", `/api/trends?hours=24${source ? `&source=${encodeURIComponent(source)}` : ""}`),
    refresh: () => call<{ started: boolean }>("POST", "/api/trends/refresh"),
    produce: (id: string, opts?: { links: string[]; links_only: boolean }) =>
      call<{ project_id: number }>("POST", `/api/trends/${encodeURIComponent(id)}/produce`, opts),
    /** Video giải thích từ chủ đề tự do và / hoặc link video (Douyin, Bilibili, Facebook, YouTube…). */
    createTopic: (body: { topic: string; links: string[]; links_only: boolean; duration: number; rights: Rights }) =>
      call<{ project_id: number }>("POST", "/api/projects", body),
    setRights: (id: number, rights: Rights) => call<ProjectDetail>("PATCH", `/api/projects/${id}`, { rights }),
    /** Thêm link nguồn (Douyin, X, …) rồi chạy lại từ bước tải video. */
    addLinks: (id: number, links: string[]) =>
      call<{ project_id: number; start: RetryStep }>("POST", `/api/projects/${id}/links`, { links }),
    watches: () => call<Watch[]>("GET", "/api/watches"),
    addWatch: (body: { target: string; site: Site; rights?: Rights }) => call<Watch>("POST", "/api/watches", body),
    patchWatch: (id: number, body: { name?: string; rights?: Rights; enabled?: boolean }) =>
      call<Watch>("PATCH", `/api/watches/${id}`, body),
    deleteWatch: (id: number) => call<{ deleted: number }>("DELETE", `/api/watches/${id}`),
    checkWatches: () => call<{ started: boolean }>("POST", "/api/watches/check"),
    clips: (status: ClipStatus, watchId?: number) =>
      call<Clip[]>("GET", `/api/clips?status=${status}${watchId ? `&watch_id=${watchId}` : ""}`),
    setClipStatus: (id: string, status: "new" | "hidden") =>
      call<Clip>("PATCH", `/api/clips/${encodeURIComponent(id)}`, { status }),
    /** Video giải thích từ một video mới; links_only bỏ trống = chỉ dùng video này khi nguồn có quyền rõ ràng. */
    produceClip: (id: string, body: { duration: number; links_only: boolean }) =>
      call<{ project_id: number }>("POST", `/api/clips/${encodeURIComponent(id)}/produce`, body),
    projects: () => call<Project[]>("GET", "/api/projects"),
    project: (id: number) => call<ProjectDetail>("GET", `/api/projects/${id}`),
    rerender: (id: number) => call<{ project_id: number }>("POST", `/api/projects/${id}/rerender`),
    /** Xoá dự án và thư mục của nó; bài đã gửi Postiz vẫn ở Postiz. */
    deleteProject: (id: number) => call<{ deleted: number }>("DELETE", `/api/projects/${id}`),
    script: (id: number) => call<ScriptView>("GET", `/api/projects/${id}/script`),
    /** Lưu kịch bản; dựng lại bằng retry(id, "voice"). */
    saveScript: (id: number, script: Script) => call<ScriptView>("PUT", `/api/projects/${id}/script`, script),
    /** Chạy lại từ `start`; bỏ trống = chạy tiếp từ bước bị lỗi, giữ kết quả đã có. */
    retry: (id: number, start?: RetryStep) =>
      call<{ project_id: number; start: RetryStep }>("POST", `/api/projects/${id}/retry`, start ? { start } : {}),
    voices: () => call<Voice[]>("GET", "/api/voices"),
    postizChannels: () => call<PostizChannel[]>("GET", "/api/postiz/channels"),
    publish: (id: number, body: { channels: string[]; mode: PublishMode; date?: string }) =>
      call<Omit<PublishRecord, "at">>("POST", `/api/projects/${id}/publish`, body),
    delogoUploads: () => call<DelogoUpload[]>("GET", "/api/delogo/uploads"),
    delogoUpload: upload,
    delogoTarget: (key: string) => call<DelogoTarget>("GET", dl(key)),
    /** Lấy khung hình ở giây `at` (bỏ trống = 10 % độ dài) để vẽ khung. */
    delogoFrame: (key: string, at?: number) => call<DelogoTarget>("POST", `${dl(key)}/frame`, { at: at ?? null }),
    delogoDetect: (key: string) => call<{ boxes: DelogoBox[]; note: string | null }>("POST", `${dl(key)}/detect`),
    delogoRun: (key: string, boxes: DelogoBox[], rights?: DelogoRights) =>
      call<DelogoTarget>("POST", `${dl(key)}/run`, { boxes, rights }),
    /** Bỏ bản đã xoá logo: nguồn dự án quay về video gốc. */
    delogoCancel: (key: string) => call<DelogoTarget>("POST", `${dl(key)}/cancel`),
    delogoRestore: (key: string) => call<DelogoTarget>("DELETE", `${dl(key)}/result`),
    delogoDelete: (key: string) => call<{ deleted: string }>("DELETE", dl(key)),
    settings: () => call<Settings>("GET", "/api/settings"),
    saveSettings: (changes: Record<string, string | boolean | null>) => call<Settings>("PUT", "/api/settings", changes),
    mediaUrl: (rel: string, bust?: number) => `${url}/media/${rel}?${q}${bust ? `&v=${bust}` : ""}`,
    eventsUrl: (id: number) => `${url}/api/projects/${id}/events?${q}`,
  };
}

export type Api = ReturnType<typeof makeApi>;

/** API của engine hiện tại; null khi engine chưa sẵn sàng. */
export function useApi(): Api | null {
  const { info } = useEngine();
  return useMemo(
    () => (info.status === "ready" ? makeApi(info.url, info.token) : null),
    [info.status, info.url, info.token],
  );
}
