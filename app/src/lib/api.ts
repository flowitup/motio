import { useMemo } from "react";
import { useEngine } from "./engine";
import { t } from "@/i18n";

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
  project_id?: number | null; // dự án mới nhất đã làm từ tin này (status = "used")
};

export type SourceInfo = {
  url: string;
  platform: string;
  uploader: string;
  title: string;
  duration: number;
  // bản sạch thay nguồn này; ranges: các đoạn (giây) đã xoá logo, null = cả video
  delogo?: { boxes: DelogoBox[]; rights: DelogoRights | null; method?: "lama"; at: number; ranges?: Span[] | null };
};

/** Khung quanh logo, theo pixel của khung hình video. */
export type DelogoBox = { x: number; y: number; w: number; h: number };
export type DelogoRights = "owned" | "licensed";
export type DelogoStatus = "idle" | "queued" | "running" | "done" | "failed";
/** Phạm vi xoá logo: đoạn video thành phẩm đang dùng (nguồn dự án), cả video, hoặc một đoạn tự chọn. */
export type DelogoScope = "used" | "all" | "range";
export type Span = [number, number]; // [đầu, cuối] tính bằng giây
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
  scope: DelogoScope | null; // lựa chọn lần trước
  span: Span | null;
  used: Span[] | null; // đoạn video thành phẩm đang dùng (đã nới thêm vài giây), null = chưa dựng / file tải lên
  ranges: Span[] | null; // đoạn đã xoá logo của kết quả, null = cả video
  uncovered: Span[]; // đoạn video thành phẩm đang dùng mà kết quả chưa xoá logo
};
export type DelogoUpload = { target: string; name: string; created_at: number | null; status: DelogoStatus };

export type Rights = "unknown" | "owned" | "licensed" | "cc";

/** Trang Stats: chi phí ElevenLabs ước lượng (USD) và số video. Claude chạy trên gói Claude nên không tính. */
export type StatsChannel = {
  channel: number | null; // null = không kênh (và các công cụ lẻ)
  name: string;
  videos: number;
  failed: number;
  sent: number; // video đã gửi Postiz
  chars: number;
  usd: number;
  usd_per_video: number | null;
};
export type StatsDay = { date: string; videos: number; chars: number; usd: number };
export type Stats = {
  price_per_1k: number;
  month: { since: string; chars: number; usd: number; videos: number };
  budget: { usd: number; ratio: number; state: "none" | "ok" | "warn" | "over"; auto_paused: boolean };
  total: { chars: number; usd: number };
  days: StatsDay[];
  channels: StatsChannel[];
};

/** Công cụ lẻ: mỗi lần chạy là một job; kết quả của job này dùng làm đầu vào của job khác. */
export type ToolKind = "download" | "transcribe" | "translate" | "speak" | "burn";
export type ToolJobStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export type ToolOutput = { name: string; path: string; kind: "video" | "audio" | "subtitles" | "text" };
export type ToolJob = {
  id: string;
  kind: ToolKind;
  title: string;
  status: ToolJobStatus;
  pct: number;
  message: string | null;
  error: string | null;
  outputs: ToolOutput[];
  created_at: number;
  finished_at: number | null;
  folder: string; // thư mục kết quả trên máy chạy engine
};

export type QaLevel = "ok" | "warn" | "fail";
/** Kiểm tra chất lượng sau mỗi lần dựng: từng mục (đã dịch sang ngôn ngữ giao diện) và mức chung. */
export type QaResult = {
  level: QaLevel; // fail = video chưa đủ tốt để tự gửi Postiz
  checks: { id: string; level: QaLevel; msg: string }[];
  at: number;
};

export type ProjectMeta = {
  topic?: string; // dự án chủ đề: chủ đề tự do ("" = chỉ link)
  subject?: { title_fr: string; angle: string };
  duration?: number;
  rights?: Rights;
  links?: string[];
  sources?: SourceInfo[];
  video?: string;
  wide?: string | null; // bản 16:9 (khi kênh gửi sang kênh Postiz 16:9)
  thumb?: string;
  title?: string;
  description?: string;
  hashtags?: string[];
  tts?: string;
  voice?: string;
  elapsed?: number;
  postiz?: PublishRecord[];
  channel?: number; // hồ sơ kênh (Kênh), không có = chạy như trước
  qa?: QaResult; // kiểm tra chất lượng lần dựng gần nhất
  review?: Review | null; // đang chờ duyệt gì (status = "review")
  send_error?: string | null; // lần tự gửi Postiz gần nhất bị lỗi
  approved_at?: number;
  auto?: boolean; // tự làm vì tin đạt điểm của kênh
};

export type Review = "script" | "video";
export type SendMode = PublishMode;

/** Hồ sơ một kênh đăng: nhãn, giọng văn, giọng đọc, cổng duyệt, kênh Postiz để tự gửi. */
export type ChannelInput = {
  name: string;
  badge: string; // nhãn đỏ trên tiêu đề video, rỗng = không nhãn
  style: string; // ghi chú giọng văn thêm vào prompt kịch bản
  glossary: string; // bảng thuật ngữ (mỗi dòng một mục) cho kịch bản và bản dịch lồng tiếng
  voice_id: string; // rỗng = giọng trong Cài đặt
  dub_voices: string[]; // giọng thêm cho các người nói khác trong bản lồng tiếng (tối đa 3)
  duration: number; // 70 | 80 | 90, cho video tin nóng
  hashtags: string[];
  gate_script: boolean;
  gate_video: boolean;
  postiz: string[]; // id kênh Postiz
  send_mode: SendMode;
  send_times: string[]; // "HH:MM", giờ máy chạy engine
  wide_postiz: string[]; // trong `postiz`: kênh nhận bản 16:9
  auto_score: number; // tự làm video khi tin hot đạt điểm này; 0 = tắt
  auto_daily: number; // tối đa số video tự làm mỗi ngày
  ai_clips: number; // video AI: số cảnh thành clip AI mỗi video (0–10); 0 = chỉ ảnh chuyển động
  series: string; // video AI: tiền đề + luật của loạt phim; mỗi tập mới viết tiếp các tập trước của kênh
  cast: string; // video AI: nhân vật cố định, mỗi dòng "Tên: ngoại hình" (tiếng Anh, hư cấu)
  default: boolean;
};
export type Channel = ChannelInput & { id: number; created_at: number; updated_at: number };

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
  profile?: number; // gửi tự động theo hồ sơ kênh này
  version?: VideoVersion; // "wide" = đã gửi bản 16:9
};
export type VideoVersion = "vertical" | "wide";

/** Video có sẵn đã gửi lên engine: `link` dán vào chỗ nào nhận link (dạng `file:…`). */
export type UploadedVideo = { link: string; name: string; duration: number; width: number | null; height: number | null; size: number };

export type ProjectStatus = "queued" | "running" | "review" | "done" | "failed";
/** Số dự án theo trạng thái (`failed`: chỉ lỗi trong 7 ngày qua). */
export type ProjectCounts = Record<ProjectStatus, number>;
/** Bộ lọc danh sách dự án; before = id dự án cuối của trang trước. */
export type ProjectQuery = { limit?: number; before?: number; channel?: number; mode?: string; status?: string; q?: string };

export type Project = {
  id: number;
  trend_id: string | null;
  mode: "news" | "topic" | "dub" | "ai";
  title: string;
  status: ProjectStatus;
  step: string | null;
  pct: number;
  meta: ProjectMeta;
  created_at: number;
  updated_at: number;
};

export type RetryStep = "search" | "download" | "transcribe" | "script" | "voice" | "render";

/** Khung theo tỉ lệ khung hình (0..1): [x, y, rộng, cao]. */
export type BlurBox = [number, number, number, number];
/** Một người nói trong bản lồng tiếng: nhãn Claude gán, giới tính, giọng người dùng chọn và giọng đã dùng. */
export type DubSpeaker = {
  label: string;
  who: string;
  gender: "f" | "m" | "";
  voice_id: string; // giọng người dùng chọn, rỗng = Motio tự chọn
  voice_name: string; // giọng đã đọc lần dựng trước
};
/** Bản lồng tiếng: đoạn video gốc đã chọn, phần mở / kết (giây), khung làm mờ phụ đề cũ. */
export type DubView = {
  start: number | null; // đoạn do người dùng đặt, null = tự chọn
  end: number | null;
  excerpt: [number, number] | null; // đoạn đã chọn (sau bước kịch bản)
  pad: [number, number] | null; // giây mở / kết bằng khung hình đứng yên
  blur: BlurBox | null;
  blur_auto: boolean; // khung do Motio tự tìm
  source: string | null; // đường dẫn /media của video gốc đã tải
  needs_review: boolean; // quyền nguồn chưa rõ: không tự gửi Postiz
  speakers: DubSpeaker[]; // người nói có lời, theo thứ tự xuất hiện
};

export type ImageProvider = "fal" | "modal" | "placeholder";
/** Video AI: nhà cung cấp ảnh đã dùng, cổng duyệt video bắt buộc, tiền ảnh đã tốn (USD, ước tính). */
export type AiView = {
  topic: string | null;
  provider: ImageProvider;
  needs_review: boolean; // ảnh của nhà cung cấp chưa được phép cho kênh kiếm tiền: không tự gửi Postiz
  cost: number | null; // ảnh + clip AI, ước lượng
  scenes: number | null;
  clips: number | null; // số cảnh đang dùng clip AI ở lần dựng gần nhất
  clip_limit: number | null; // số clip riêng của video này; null = theo kênh
  clip_provider: string | null; // nhà cung cấp của các clip ở lần dựng gần nhất (fal | heygen)
  episode: number | null; // số tập trong loạt phim của kênh (kênh có "series"); null = video riêng lẻ
  recap: string | null; // tóm tắt tập này do Claude viết, để tập sau viết tiếp
};
export type Motion = "zoom_in" | "zoom_out" | "pan_left" | "pan_right";

export type ProjectDetail = Project & {
  log: string;
  folder: string;
  trend: Trend | null;
  retry: { auto: RetryStep; steps: RetryStep[] };
  has_script: boolean;
  dub: DubView | null;
  ai: AiView | null;
  usage: { tts_chars: number; usd: number; clip_usd: number }; // ElevenLabs: ký tự đã đọc cho dự án này (cộng dồn mọi lần đọc) và tiền ước lượng
};

export type ScriptClip = { src: number; start: number; end: number };
/** Bản lồng tiếng thêm: loại (intro | dub | outro), ai nói, câu gốc (zh), lúc vào / hạn (giây), số ký tự vừa chỗ. */
export type ScriptLine = {
  text: string;
  clips: ScriptClip[];
  kind?: "intro" | "dub" | "outro";
  speaker?: string;
  zh?: string;
  at?: number;
  until?: number;
  max_chars?: number;
  // Video AI: mỗi dòng là một cảnh
  image?: string; // prompt ảnh (tiếng Anh)
  motion?: Motion; // chuyển động máy quay chậm
  seed?: number; // đổi hạt giống = ảnh mới
  picture?: string | null; // đường dẫn /media của ảnh đã làm (chỉ đọc)
};
export type Script = { title_fr: string; lines: ScriptLine[]; description: string; hashtags: string[]; style?: string };
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
  dub: { register: string; speakers: Record<string, string>; language: string | null } | null;
  ai: AiView | null;
};

export type ProgressEvent = { status: ProjectStatus; step: string | null; pct: number; log_tail: string[] };

export type Health = {
  version: string;
  platform: { system: string; machine: string; python: string };
  headless: boolean;
  providers: {
    llm: { provider: string; model: string; fast_model: string; key: boolean };
    tts: string | null;
    asr: { engine: string; model: string };
  };
  ffmpeg: string | null;
  ffprobe: string | null;
  js_runtime: string | null;
  postiz: boolean;
  quota_left: number | null;
  data_dir: string;
  disk: { free: number; total: number } | null; // ổ chứa thư mục dữ liệu của engine (byte)
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
  last_auto: { at: number; projects: number[] } | null; // lượt tự làm gần nhất (sau lượt tự cập nhật)
};

export type WatchKind = "channel" | "playlist" | "space" | "search" | "trending";
export type Site = "youtube" | "bilibili";

/** Nguồn theo dõi: kênh / playlist YouTube, không gian Bilibili, tìm kiếm đã lưu, bảng xếp hạng Bilibili. */
export type Watch = {
  id: number;
  kind: WatchKind;
  site: Site;
  target: string; // URL, từ khoá khi kind = search, hoặc "bilibili:ranking:181" / "bilibili:popular" / "bilibili:weekly" khi kind = trending
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
  watch_kind?: string | null; // "trending" = a Bilibili list: the app translates its name from watch_target
  watch_target?: string | null;
  site: Site;
  url: string;
  title: string;
  title_fr: string | null;
  reason: string | null;
  uploader: string | null;
  duration: number | null;
  views: number | null;
  likes: number | null; // chỉ có ở video từ bảng xếp hạng
  pubdate: number | null; // giờ đăng gốc (giây Unix), chỉ có ở video từ bảng xếp hạng
  category: string | null; // chuyên mục Bilibili
  rank: number | null; // thứ hạng trong bảng
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
      x.onerror = () => reject(new ApiError(0, t.common.noEngine));
      const form = new FormData();
      form.append("file", file);
      x.send(form);
    });
  }
  /** Gửi form multipart (công cụ lẻ) bằng XHR để có tiến trình tải file lên. */
  function postForm<T>(path: string, form: FormData, onProgress?: (pct: number) => void, signal?: AbortSignal): Promise<T> {
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open("POST", url + path);
      signal?.addEventListener("abort", () => x.abort());
      x.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
      x.setRequestHeader("Authorization", `Bearer ${token}`);
      x.upload.onprogress = (e) => e.lengthComputable && onProgress?.(Math.round((100 * e.loaded) / e.total));
      x.onload = () => {
        let body: { detail?: string } = {};
        try {
          body = JSON.parse(x.responseText);
        } catch {
          /* không phải JSON */
        }
        if (x.status >= 200 && x.status < 300) resolve(body as T);
        else reject(new ApiError(x.status, body.detail ?? x.statusText));
      };
      x.onerror = () => reject(new ApiError(0, t.common.noEngine));
      x.send(form);
    });
  }
  return {
    /** Thêm file video có sẵn (tự tải từ Douyin hay nơi khác) làm nguồn. */
    uploadVideo: (file: File, onProgress?: (pct: number) => void, signal?: AbortSignal) => {
      const form = new FormData();
      form.append("file", file);
      return postForm<UploadedVideo>("/api/uploads", form, onProgress, signal);
    },
    health: () => call<Health>("GET", "/api/health"),
    state: () => call<RefreshState>("GET", "/api/state"),
    trends: (source?: string) =>
      call<Trend[]>("GET", `/api/trends?hours=24${source ? `&source=${encodeURIComponent(source)}` : ""}`),
    refresh: () => call<{ started: boolean }>("POST", "/api/trends/refresh"),
    /** channel: id hồ sơ kênh, 0 = không dùng kênh, bỏ trống = kênh mặc định. */
    produce: (id: string, opts?: { links?: string[]; links_only?: boolean; channel?: number }) =>
      call<{ project_id: number }>("POST", `/api/trends/${encodeURIComponent(id)}/produce`, opts),
    /** Video giải thích từ chủ đề tự do và / hoặc link video (Douyin, Bilibili, Facebook, YouTube…). */
    createTopic: (body: {
      topic: string;
      links: string[];
      links_only: boolean;
      duration: number;
      rights: Rights;
      channel?: number;
    }) =>
      call<{ project_id: number }>("POST", "/api/projects", body),
    /** Lồng tiếng Pháp một video; start / end (giây) bỏ trống = Motio tự chọn đoạn. */
    createDub: (body: { link: string; start?: number; end?: number; rights: Rights; channel?: number }) =>
      call<{ project_id: number }>("POST", "/api/dubs", body),
    /** Video làm hoàn toàn bằng ảnh AI từ một chủ đề. */
    createAi: (body: { topic: string; duration: number; channel?: number; clips?: number }) =>
      call<{ project_id: number }>("POST", "/api/ai", body),
    /** Video AI: xin ảnh mới cho cảnh `index`; dựng lại bằng retry(id, "render") để làm ảnh đó. */
    redoScene: (id: number, index: number) => call<ScriptView>("POST", `/api/projects/${id}/scenes/${index}/redo`),
    /** Lồng tiếng một video mới (quyền theo nguồn theo dõi). */
    dubClip: (id: string, channel?: number) =>
      call<{ project_id: number }>("POST", `/api/clips/${encodeURIComponent(id)}/dub`, { channel }),
    /** Đổi đoạn lồng tiếng / khung làm mờ (blur: null = tắt). rerun: bước nên chạy lại bằng retry(). */
    updateDub: (
      id: number,
      body: { start?: number | null; end?: number | null; blur?: BlurBox | null; voices?: Record<string, string> },
    ) =>
      call<{ project: ProjectDetail; rerun: RetryStep | null }>("PUT", `/api/projects/${id}/dub`, body),
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
    produceClip: (id: string, body: { duration: number; links_only: boolean; channel?: number }) =>
      call<{ project_id: number }>("POST", `/api/clips/${encodeURIComponent(id)}/produce`, body),
    projects: () => call<Project[]>("GET", "/api/projects"),
    /** Trang dự án có lọc (kênh, kiểu, trạng thái, tìm chữ) và "tải thêm" bằng `before`. */
    projectPage: (query: ProjectQuery) => {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== "") qs.set(k, String(v));
      return call<Project[]>("GET", `/api/projects?${qs}`);
    },
    projectCounts: () => call<ProjectCounts>("GET", "/api/projects/counts"),
    /** Ẩn / hiện lại một tin hot chưa làm. */
    hideTrend: (id: string, hidden: boolean) =>
      call<{ id: string; hidden: boolean }>("PATCH", `/api/trends/${encodeURIComponent(id)}`, { hidden }),
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
    /** Duyệt dự án đang chờ: kịch bản → đọc giọng và dựng; video → gửi Postiz theo kênh (send=false: không gửi). */
    approve: (id: number, send = true) =>
      call<{ project_id: number; review: Review }>("POST", `/api/projects/${id}/approve`, { send }),
    channels: () => call<Channel[]>("GET", "/api/channels"),
    createChannel: (body: ChannelInput) => call<Channel>("POST", "/api/channels", body),
    updateChannel: (id: number, body: ChannelInput) => call<Channel>("PUT", `/api/channels/${id}`, body),
    deleteChannel: (id: number) => call<{ deleted: number }>("DELETE", `/api/channels/${id}`),
    voices: () => call<Voice[]>("GET", "/api/voices"),
    postizChannels: () => call<PostizChannel[]>("GET", "/api/postiz/channels"),
    /** Gửi lại video đã xong sang Postiz đúng như kênh của dự án cài đặt (chế độ, giờ đăng, bản 16:9). */
    resend: (id: number) => call<{ sent: boolean; error: string | null }>("POST", `/api/projects/${id}/resend`),
    publish: (id: number, body: { channels: string[]; mode: PublishMode; date?: string; version?: VideoVersion }) =>
      call<Omit<PublishRecord, "at">>("POST", `/api/projects/${id}/publish`, body),
    delogoUploads: () => call<DelogoUpload[]>("GET", "/api/delogo/uploads"),
    delogoUpload: upload,
    delogoTarget: (key: string) => call<DelogoTarget>("GET", dl(key)),
    /** Lấy khung hình ở giây `at` (bỏ trống = 10 % độ dài) để vẽ khung. */
    delogoFrame: (key: string, at?: number) => call<DelogoTarget>("POST", `${dl(key)}/frame`, { at: at ?? null }),
    delogoDetect: (key: string) => call<{ boxes: DelogoBox[]; note: string | null }>("POST", `${dl(key)}/detect`),
    /** scope bỏ trống: nguồn dự án = đoạn video final dùng, file tải lên = cả video. */
    delogoRun: (key: string, boxes: DelogoBox[], scope?: DelogoScope, span?: Span) =>
      call<DelogoTarget>("POST", `${dl(key)}/run`, { boxes, scope, start: span?.[0], end: span?.[1] }),
    /** Bỏ bản đã xoá logo: nguồn dự án quay về video gốc. */
    delogoCancel: (key: string) => call<DelogoTarget>("POST", `${dl(key)}/cancel`),
    delogoRestore: (key: string) => call<DelogoTarget>("DELETE", `${dl(key)}/result`),
    delogoDelete: (key: string) => call<{ deleted: string }>("DELETE", dl(key)),
    stats: () => call<Stats>("GET", "/api/stats"),
    toolJobs: () => call<ToolJob[]>("GET", "/api/tools/jobs"),
    /** fields: ô chữ của công cụ; files: file tải lên (`file` video / âm thanh, `subs` .srt / .vtt). */
    startTool: (
      kind: ToolKind,
      fields: Record<string, string>,
      files: { file?: File; subs?: File } = {},
      onProgress?: (pct: number) => void,
    ) => {
      const form = new FormData();
      for (const [k, v] of Object.entries(fields)) if (v !== "") form.append(k, v);
      if (files.file) form.append("file", files.file);
      if (files.subs) form.append("subs", files.subs);
      return postForm<ToolJob>(`/api/tools/${kind}`, form, onProgress);
    },
    cancelTool: (id: string) => call<ToolJob>("POST", `/api/tools/jobs/${id}/cancel`),
    deleteToolJob: (id: string) => call<{ deleted: string }>("DELETE", `/api/tools/jobs/${id}`),
    settings: () => call<Settings>("GET", "/api/settings"),
    saveSettings: (changes: Record<string, string | boolean | null>) => call<Settings>("PUT", "/api/settings", changes),
    testSlack: () => call<{ sent: boolean }>("POST", "/api/notify/test"),
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
