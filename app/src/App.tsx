import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, TriangleAlert } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import { AppMenu } from "@/components/app-menu";
import { Button } from "@/components/ui/button";
import { useProjectNotifications } from "@/hooks/use-project-notifications";
import { useApi } from "@/lib/api";
import { useEngine } from "@/lib/engine";
import { BUSY_MS } from "@/lib/poll";
import { useNavLayout } from "@/lib/nav-layout";
import { cn } from "@/lib/utils";
import { t, useLang, type Messages } from "@/i18n";
import AccountPage from "@/pages/account";
import ClipStudioPage from "@/pages/clip-studio";
import ClipsPage from "@/pages/clips";
import DelogoPage from "@/pages/delogo";
import ProjectDetailPage from "@/pages/project-detail";
import ProjectsPage from "@/pages/projects";
import ReviewPage from "@/pages/review";
import ScanPage from "@/pages/scan";
import SettingsPage from "@/pages/settings";
import NewVideoPage from "@/pages/new-video";
import ToolsPage from "@/pages/tools";
import TrendsPage from "@/pages/trends";

/** Trang cần engine: hiện trạng thái khởi động / lỗi thay vì nội dung. */
export function EngineGate({ children }: { children: ReactNode }) {
  const { info, restart } = useEngine();
  const navigate = useNavigate();
  if (info.status === "ready") return <>{children}</>;
  return (
    <div role={info.status === "starting" ? "status" : "alert"} className="flex h-full flex-col items-center justify-center gap-4 text-center">
      {info.status === "starting" ? (
        <>
          <Loader2 className="size-8 animate-spin text-muted-foreground" />
          <p className="text-muted-foreground">{t.engine.starting}</p>
        </>
      ) : (
        <>
          <TriangleAlert className="size-8 text-destructive" />
          <p className="font-medium">{t.engine.error}</p>
          {info.error && <p className="max-w-md text-sm text-muted-foreground">{t.native(info.error)}</p>}
          <div className="flex gap-2">
            <Button onClick={restart}>{t.engine.retry}</Button>
            <Button variant="outline" onClick={() => navigate("/settings")}>
              {t.engine.openSettings}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

/** The engine writes its steps, log lines and errors in the app's language (UI_LANG in its settings). */
function useEngineLang() {
  const api = useApi();
  const lang = useLang();
  useEffect(() => {
    if (!api) return;
    api
      .settings()
      .then((s) => ((s.UI_LANG?.value || "en") === lang ? undefined : api.saveSettings({ UI_LANG: lang })))
      .catch(() => {}); // engine older than the language switch: it stays in English
  }, [api, lang]);
}

/** The window title follows the page, with the number of projects waiting for you in front. */
function useDocumentTitle(needsYou: number) {
  const { pathname } = useLocation();
  const section = pathname.split("/")[1] as keyof Messages["nav"];
  const page = section in t.nav ? t.nav[section] : t.appName;
  useEffect(() => {
    document.title = `${needsYou > 0 ? `(${needsYou}) ` : ""}${page} · ${t.appName}`;
  }, [page, needsYou]);
}

export default function App() {
  const { info } = useEngine();
  const layout = useNavLayout();
  const qc = useQueryClient();
  // Đổi engine (khởi động lại, local ↔ từ xa) hoặc đổi ngôn ngữ (App dựng lại): tải lại dữ liệu.
  useEffect(() => {
    qc.resetQueries();
  }, [info.url, info.token, qc]);
  useProjectNotifications();
  useEngineLang();

  const api = useApi();
  const { data: counts } = useQuery({
    queryKey: ["projects", "counts"],
    queryFn: () => api!.projectCounts(),
    enabled: !!api,
    refetchInterval: (q) => (q.state.data && q.state.data.queued + q.state.data.running > 0 ? BUSY_MS : 15_000),
  });
  useDocumentTitle(counts?.review ?? 0);
  const main = useRef<HTMLElement>(null);

  return (
    <div className={cn("app-shell flex h-screen bg-background text-foreground", layout === "top" && "flex-col")} data-nav={layout}>
      {/* A button, not a #link: the hash is the router's. */}
      <button
        type="button"
        onClick={() => main.current?.focus()}
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:top-2 focus-visible:left-16 focus-visible:z-50 focus-visible:rounded-lg focus-visible:bg-raised focus-visible:px-3 focus-visible:py-2 focus-visible:text-[13px] focus-visible:font-semibold"
      >
        {t.a11y.skip}
      </button>
      <AppMenu counts={counts} />
      <main ref={main} tabIndex={-1} className={cn("app-main min-h-0 min-w-0 flex-1 overflow-y-auto outline-none", layout === "dock" && "pb-24")}>
        <Routes>
          <Route path="/" element={<Navigate to="/clips" replace />} />
          <Route path="/trends" element={<Navigate to="/clips" replace />} /> {/* Trending lists are part of the Feed now */}
          <Route path="/news" element={<EngineGate><TrendsPage /></EngineGate>} />
          <Route path="/scan" element={<EngineGate><ScanPage /></EngineGate>} />
          <Route path="/clips" element={<EngineGate><ClipsPage /></EngineGate>} />
          <Route path="/clips/:id" element={<EngineGate><AccountPage /></EngineGate>} />
          <Route path="/projects" element={<EngineGate><ProjectsPage /></EngineGate>} />
          <Route path="/review" element={<EngineGate><ReviewPage /></EngineGate>} />
          <Route path="/projects/new" element={<EngineGate><NewVideoPage /></EngineGate>} />
          <Route path="/clip-studio" element={<EngineGate><ClipStudioPage /></EngineGate>} />
          <Route path="/projects/:id" element={<EngineGate><ProjectDetailPage /></EngineGate>} />
          <Route path="/channels" element={<Navigate to="/settings?tab=channels" replace />} />
          <Route path="/delogo" element={<EngineGate><DelogoPage /></EngineGate>} />
          <Route path="/tools" element={<EngineGate><ToolsPage /></EngineGate>} />
          <Route path="/stats" element={<Navigate to="/settings?tab=stats" replace />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
