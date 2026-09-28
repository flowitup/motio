import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { openUrl } from "@tauri-apps/plugin-opener";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { t } from "@/i18n";

export type EngineMode = "local" | "remote";
export type EngineInfo = {
  status: "starting" | "ready" | "error";
  mode: EngineMode;
  url: string;
  token: string;
  version?: string | null;
  error?: string | null;
};
export type EngineConfig = { mode: EngineMode; url: string; token: string };

export const inTauri = "__TAURI_INTERNALS__" in window;

// Chạy frontend trong trình duyệt (không có Tauri) để thử: VITE_ENGINE_URL + VITE_ENGINE_TOKEN.
const browserInfo: EngineInfo = {
  status: import.meta.env.VITE_ENGINE_URL ? "ready" : "error",
  mode: "remote",
  url: import.meta.env.VITE_ENGINE_URL ?? "",
  token: import.meta.env.VITE_ENGINE_TOKEN ?? "",
  get error() {
    return t.engine.notInTauri;
  },
};

type Ctx = {
  info: EngineInfo;
  restart: () => Promise<void>;
  getConfig: () => Promise<EngineConfig>;
  setConfig: (c: EngineConfig) => Promise<void>;
};

const EngineCtx = createContext<Ctx | null>(null);

export function EngineProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<EngineInfo>(
    inTauri ? { status: "starting", mode: "local", url: "", token: "" } : browserInfo,
  );

  useEffect(() => {
    if (!inTauri) return;
    let off: (() => void) | undefined;
    listen<EngineInfo>("engine-changed", (e) => setInfo(e.payload)).then((u) => (off = u));
    invoke<EngineInfo>("engine_info").then(setInfo);
    return () => off?.();
  }, []);

  const restart = useCallback(async () => {
    if (inTauri) setInfo(await invoke<EngineInfo>("restart_engine"));
  }, []);
  const getConfig = useCallback(
    async () =>
      inTauri ? invoke<EngineConfig>("engine_config") : { mode: "remote" as const, url: browserInfo.url, token: "" },
    [],
  );
  const setConfig = useCallback(async (config: EngineConfig) => {
    if (inTauri) setInfo(await invoke<EngineInfo>("set_engine_config", { config }));
  }, []);

  const value = useMemo(() => ({ info, restart, getConfig, setConfig }), [info, restart, getConfig, setConfig]);
  return <EngineCtx.Provider value={value}>{children}</EngineCtx.Provider>;
}

export function useEngine() {
  const c = useContext(EngineCtx);
  if (!c) throw new Error("useEngine outside EngineProvider");
  return c;
}

export async function openFolder(path: string) {
  if (inTauri) await invoke("open_folder", { path });
}

export function openExternal(url: string) {
  if (inTauri) openUrl(url);
  else window.open(url, "_blank", "noreferrer");
}
