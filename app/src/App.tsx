import { useQueryClient } from "@tanstack/react-query";
import { Download, Eraser, FolderKanban, Flame, Loader2, Rss, Settings as SettingsIcon, TriangleAlert } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { useProjectNotifications } from "@/hooks/use-project-notifications";
import { useEngine } from "@/lib/engine";
import { useUpdater } from "@/lib/updater";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";
import ClipsPage from "@/pages/clips";
import DelogoPage from "@/pages/delogo";
import ProjectDetailPage from "@/pages/project-detail";
import ProjectsPage from "@/pages/projects";
import SettingsPage from "@/pages/settings";
import TrendsPage from "@/pages/trends";

const NAV = [
  { to: "/trends", label: t.nav.trends, icon: Flame },
  { to: "/clips", label: t.nav.clips, icon: Rss },
  { to: "/projects", label: t.nav.projects, icon: FolderKanban },
  { to: "/delogo", label: t.nav.delogo, icon: Eraser },
  { to: "/settings", label: t.nav.settings, icon: SettingsIcon },
];

function EngineBadge() {
  const { info } = useEngine();
  const color = { ready: "bg-emerald-500", starting: "bg-amber-500", error: "bg-red-500" }[info.status];
  const label = { ready: t.engine.ready, starting: t.engine.starting, error: t.engine.error }[info.status];
  return (
    <div className="flex items-center gap-2 px-3 text-xs text-muted-foreground" title={info.error ?? info.url}>
      <span className={cn("size-2 rounded-full", color)} />
      <span className="truncate">{label}</span>
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
      className="mx-2 mb-3 flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-medium transition-colors hover:bg-emerald-500/20"
    >
      <Download className="size-4 shrink-0" />
      <span className="truncate">{t.update.available(result.version)}</span>
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
          {info.error && <p className="max-w-md text-sm text-muted-foreground">{info.error}</p>}
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

export default function App() {
  const { info } = useEngine();
  const qc = useQueryClient();
  // Đổi engine (khởi động lại, local ↔ từ xa): bỏ dữ liệu cũ.
  useEffect(() => {
    qc.resetQueries();
  }, [info.url, info.token, qc]);
  useProjectNotifications();

  return (
    <div className="flex h-screen bg-background text-foreground">
      <aside className="flex w-52 shrink-0 flex-col border-r bg-muted/30 py-4">
        <div className="px-5 pb-6 text-lg font-semibold tracking-tight">{t.appName}</div>
        <nav className="flex flex-1 flex-col gap-1 px-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent",
                  isActive && "bg-accent font-medium",
                )
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <UpdateNotice />
        <EngineBadge />
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<Navigate to="/trends" replace />} />
          <Route path="/trends" element={<EngineGate><TrendsPage /></EngineGate>} />
          <Route path="/clips" element={<EngineGate><ClipsPage /></EngineGate>} />
          <Route path="/projects" element={<EngineGate><ProjectsPage /></EngineGate>} />
          <Route path="/projects/:id" element={<EngineGate><ProjectDetailPage /></EngineGate>} />
          <Route path="/delogo" element={<EngineGate><DelogoPage /></EngineGate>} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
