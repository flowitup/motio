import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChartColumn, Download, Eraser, FolderKanban, Flame, Loader2, Rss, Settings as SettingsIcon, TriangleAlert, Tv, Wrench } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { useProjectNotifications } from "@/hooks/use-project-notifications";
import { Led } from "@/components/studio";
import { useApi } from "@/lib/api";
import { useEngine } from "@/lib/engine";
import { useUpdater } from "@/lib/updater";
import { cn } from "@/lib/utils";
import { t, useLang, type Messages } from "@/i18n";
import ChannelsPage from "@/pages/channels";
import ClipsPage from "@/pages/clips";
import DelogoPage from "@/pages/delogo";
import ProjectDetailPage from "@/pages/project-detail";
import ProjectsPage from "@/pages/projects";
import SettingsPage from "@/pages/settings";
import StatsPage from "@/pages/stats";
import NewVideoPage from "@/pages/new-video";
import ToolsPage from "@/pages/tools";
import TrendsPage from "@/pages/trends";

type NavItem = { to: string; label: keyof Messages["nav"]; icon: typeof Flame };
/** The rail's groups, separated by thin dividers. Settings sits at the bottom, above the engine status. */
const NAV: NavItem[][] = [
  [
    { to: "/trends", label: "trends", icon: Flame },
    { to: "/clips", label: "clips", icon: Rss },
    { to: "/projects", label: "projects", icon: FolderKanban },
  ],
  [{ to: "/channels", label: "channels", icon: Tv }],
  [
    { to: "/delogo", label: "delogo", icon: Eraser },
    { to: "/tools", label: "tools", icon: Wrench },
  ],
  [{ to: "/stats", label: "stats", icon: ChartColumn }],
];

const railItem =
  "relative flex h-14 flex-col items-center justify-center gap-1 text-xs leading-4 font-medium whitespace-nowrap transition-colors";

function RailItem({ to, label, icon: Icon, count }: { to: string; label: string; icon: typeof Flame; count?: number }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) => cn(railItem, isActive ? "bg-raised text-foreground" : "text-muted-foreground hover:bg-raised/60 hover:text-foreground")}
    >
      {({ isActive }) => (
        <>
          {isActive && <span className="absolute inset-y-0 left-0 w-0.5 bg-amber" />}
          <span className="relative">
            <Icon className={cn("size-5", isActive && "text-amber")} />
            {!!count && (
              <span
                role="img"
                aria-label={t.studio.needsYouCount(count)}
                className="absolute -top-1.5 -right-3 flex h-4 min-w-4 items-center justify-center rounded-full bg-amber px-1 font-mono text-[11px] leading-none font-medium text-on-amber tabular-nums"
              >
                {count}
              </span>
            )}
          </span>
          <span>{label}</span>
        </>
      )}
    </NavLink>
  );
}

function EngineBadge() {
  const { info } = useEngine();
  const status = { ready: "done", starting: "review", error: "failed" }[info.status] as "done" | "review" | "failed";
  const label = { ready: t.engine.ready, starting: t.engine.starting, error: t.engine.error }[info.status];
  return (
    <div
      className="flex flex-col items-center gap-1.5 px-2 pt-3 pb-4"
      title={info.error ? t.native(info.error) : info.url}
    >
      <Led status={status} />
      <span className="w-full text-center text-xs leading-4 font-medium text-balance text-muted-foreground">{label}</span>
    </div>
  );
}

/** Có bản mới trên GitHub: nhắc ở thanh bên, bấm để vào Cài đặt. */
function UpdateNotice() {
  const { result } = useUpdater();
  if (!result?.version) return null;
  return (
    <NavLink
      to="/settings"
      title={t.update.available(result.version)}
      className={cn(railItem, "text-mint hover:bg-raised/60 hover:text-mint")}
    >
      <Download className="size-5" />
      <span>{t.update.short}</span>
    </NavLink>
  );
}

/** Trang cần engine: hiện trạng thái khởi động / lỗi thay vì nội dung. */
export function EngineGate({ children }: { children: ReactNode }) {
  const { info, restart } = useEngine();
  const navigate = useNavigate();
  if (info.status === "ready") return <>{children}</>;
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
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

export default function App() {
  const { info } = useEngine();
  const qc = useQueryClient();
  // Đổi engine (khởi động lại, local ↔ từ xa) hoặc đổi ngôn ngữ (App dựng lại): tải lại dữ liệu.
  useEffect(() => {
    qc.resetQueries();
  }, [info.url, info.token, qc]);
  useProjectNotifications();
  useEngineLang();

  const api = useApi();
  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api!.projects(),
    enabled: !!api,
    refetchInterval: 4_000,
  });
  const needsYou = (projects ?? []).filter((p) => p.status === "review").length;

  return (
    <div className="flex h-screen bg-background text-foreground">
      <nav aria-label={t.studio.mainNav} className="flex w-20 shrink-0 flex-col border-r bg-ground">
        <div className="flex h-14 shrink-0 flex-col items-center justify-center gap-[3px] border-b">
          {/* Logo C: seven rounded bars whose envelope forms an M; amber = original voice, cyan = French dub. */}
          <svg width="28" height="22" viewBox="6 8 106 84" fill="none" strokeWidth="10" strokeLinecap="round" aria-hidden="true">
            <g stroke="var(--amber)">
              <path d="M11 31v38M27 13v74M43 24v52" />
            </g>
            <path d="M59 40v20" stroke="var(--foreground)" />
            <g stroke="var(--cyan)">
              <path d="M75 24v52M91 13v74M107 31v38" />
            </g>
          </svg>
          <span className="font-mono text-xs leading-4 font-medium tracking-[0.02em]">{t.appName}</span>
        </div>
        <div className="flex flex-1 flex-col overflow-y-auto pt-2">
          {NAV.map((group, i) => (
            <div key={i} className={cn("flex flex-col", i > 0 && "mt-2 border-t pt-2")}>
              {group.map(({ to, label, icon }) => (
                <RailItem key={to} to={to} label={t.nav[label]} icon={icon} count={to === "/projects" ? needsYou : undefined} />
              ))}
            </div>
          ))}
        </div>
        <div className="flex flex-col border-t">
          <UpdateNotice />
          <RailItem to="/settings" label={t.nav.settings} icon={SettingsIcon} />
          <EngineBadge />
        </div>
      </nav>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<Navigate to="/trends" replace />} />
          <Route path="/trends" element={<EngineGate><TrendsPage /></EngineGate>} />
          <Route path="/clips" element={<EngineGate><ClipsPage /></EngineGate>} />
          <Route path="/projects" element={<EngineGate><ProjectsPage /></EngineGate>} />
          <Route path="/projects/new" element={<EngineGate><NewVideoPage /></EngineGate>} />
          <Route path="/projects/:id" element={<EngineGate><ProjectDetailPage /></EngineGate>} />
          <Route path="/channels" element={<EngineGate><ChannelsPage /></EngineGate>} />
          <Route path="/delogo" element={<EngineGate><DelogoPage /></EngineGate>} />
          <Route path="/tools" element={<EngineGate><ToolsPage /></EngineGate>} />
          <Route path="/stats" element={<EngineGate><StatsPage /></EngineGate>} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
