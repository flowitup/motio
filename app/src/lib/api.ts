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

export type ProjectMeta = {
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
  trend_id: string;
  title: string;
  status: ProjectStatus;
  step: string | null;
  pct: number;
  meta: ProjectMeta;
  created_at: number;
  updated_at: number;
};

export type ProjectDetail = Project & { log: string; folder: string; trend: Trend | null };

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
  return {
    health: () => call<Health>("GET", "/api/health"),
    state: () => call<RefreshState>("GET", "/api/state"),
    trends: (source?: string) =>
      call<Trend[]>("GET", `/api/trends?hours=24${source ? `&source=${encodeURIComponent(source)}` : ""}`),
    refresh: () => call<{ started: boolean }>("POST", "/api/trends/refresh"),
    produce: (id: string) => call<{ project_id: number }>("POST", `/api/trends/${encodeURIComponent(id)}/produce`),
    projects: () => call<Project[]>("GET", "/api/projects"),
    project: (id: number) => call<ProjectDetail>("GET", `/api/projects/${id}`),
    rerender: (id: number) => call<{ project_id: number }>("POST", `/api/projects/${id}/rerender`),
    voices: () => call<Voice[]>("GET", "/api/voices"),
    postizChannels: () => call<PostizChannel[]>("GET", "/api/postiz/channels"),
    publish: (id: number, body: { channels: string[]; mode: PublishMode; date?: string }) =>
      call<Omit<PublishRecord, "at">>("POST", `/api/projects/${id}/publish`, body),
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
