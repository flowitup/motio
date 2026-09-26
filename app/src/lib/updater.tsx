import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { inTauri } from "@/lib/engine";

// Tự cập nhật từ GitHub Releases (xem app/src-tauri/src/updater.rs).
export type UpdateCheck = {
  current: string;
  version?: string | null;
  notes?: string | null;
  date?: string | null;
  url?: string | null;
};
type UpdaterStatus = { current: string; hasToken: boolean };
type Progress = { downloaded: number; total?: number | null };

type Ctx = {
  current: string;
  hasToken: boolean;
  checking: boolean;
  result: UpdateCheck | null;
  error: string | null;
  /** 0–100 khi đang tải bản cập nhật, null khi không. */
  progress: number | null;
  check: () => Promise<void>;
  install: () => Promise<void>;
  setToken: (token: string) => Promise<void>;
};

const UpdaterCtx = createContext<Ctx | null>(null);

export function UpdaterProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState("");
  const [hasToken, setHasToken] = useState(false);
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<UpdateCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);

  const check = useCallback(async () => {
    if (!inTauri) return;
    setChecking(true);
    setError(null);
    try {
      setResult(await invoke<UpdateCheck>("check_update"));
    } catch (e) {
      setError(String(e));
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    if (!inTauri) return;
    let off: (() => void) | undefined;
    listen<Progress>("update-progress", ({ payload: p }) =>
      setProgress(p.total ? Math.round((p.downloaded / p.total) * 100) : 0),
    ).then((u) => (off = u));
    invoke<UpdaterStatus>("updater_status").then((s) => {
      setCurrent(s.current);
      setHasToken(s.hasToken);
    });
    // Kiểm tra một lần khi mở app (chỉ bản đã build).
    if (!import.meta.env.DEV) check();
    return () => off?.();
  }, [check]);

  const install = useCallback(async () => {
    setError(null);
    setProgress(0);
    try {
      await invoke("install_update"); // thành công thì app tự khởi động lại
    } catch (e) {
      setError(String(e));
      setProgress(null);
    }
  }, []);

  const setToken = useCallback(
    async (token: string) => {
      const s = await invoke<UpdaterStatus>("set_update_token", { token });
      setHasToken(s.hasToken);
      if (s.hasToken) await check();
      else setResult(null);
    },
    [check],
  );

  const value = useMemo(
    () => ({ current, hasToken, checking, result, error, progress, check, install, setToken }),
    [current, hasToken, checking, result, error, progress, check, install, setToken],
  );
  return <UpdaterCtx.Provider value={value}>{children}</UpdaterCtx.Provider>;
}

export function useUpdater() {
  const c = useContext(UpdaterCtx);
  if (!c) throw new Error("useUpdater outside UpdaterProvider");
  return c;
}
