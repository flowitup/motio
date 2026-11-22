import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChartColumn, Compass, Download, FolderKanban, Loader2, Plus, Settings as SettingsIcon, TriangleAlert, Tv, Wrench } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router";
import { inSection, type SectionKey } from "@/components/section-tabs";
import { Button } from "@/components/ui/button";
import { useProjectNotifications } from "@/hooks/use-project-notifications";
import { HUE_SOLID, HUE_TILE, Led, type Hue } from "@/components/studio";
import { useApi } from "@/lib/api";
import { useEngine } from "@/lib/engine";
import { BUSY_MS } from "@/lib/poll";
import { useUpdater } from "@/lib/updater";
import { cn } from "@/lib/utils";
import { t, useLang, type Messages } from "@/i18n";
import AccountPage from "@/pages/account";
import ChannelsPage from "@/pages/channels";
import ClipStudioPage from "@/pages/clip-studio";
import ClipsPage from "@/pages/clips";
import DelogoPage from "@/pages/delogo";
import ProjectDetailPage from "@/pages/project-detail";
import ProjectsPage from "@/pages/projects";
import ReviewPage from "@/pages/review";
import ScanPage from "@/pages/scan";
import SettingsPage from "@/pages/settings";
import StatsPage from "@/pages/stats";
import NewVideoPage from "@/pages/new-video";
import ToolsPage from "@/pages/tools";
import TrendsPage from "@/pages/trends";

type NavItem = { to: string; label: keyof Messages["nav"]; icon: typeof Compass; hue?: Hue; section?: SectionKey };
/** The slim icon rail on the left, in groups split by a thin rule: find + make, channels, tools, numbers. Settings sits at the bottom.
 * A `section` entry holds several pages as tabs (Discover: Trending, News topics, Followed, Scan; Tools: Quick jobs, Remove logo). */
const NAV: NavItem[][] = [
  [
    { to: "/clips", label: "discover", icon: Compass, hue: "amber", section: "discover" },
    { to: "/projects", label: "projects", icon: FolderKanban, hue: "violet" },
  ],
  [{ to: "/channels", label: "channels", icon: Tv, hue: "pink" }],
  [{ to: "/tools", label: "tools", icon: Wrench, hue: "lime", section: "tools" }],
  [{ to: "/stats", label: "stats", icon: ChartColumn, hue: "mint" }],
];

/** A count in the menu: pink = waiting for you (approvals), coral = failed lately. */
function NavBadge({ count, label, tone }: { count: number; label: string; tone: "amber" | "coral" }) {
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={cn(
        "dock-badge flex h-4 min-w-4 items-center justify-center gap-0.5 rounded-full px-1 font-mono text-[11px] leading-none font-medium tabular-nums",
        tone === "amber" ? "bg-pink text-on-pink" : "bg-coral text-on-amber",
      )}
    >
      {/* The warning sign tells the failed count from the pink "needs you" count when both show the same number. */}
      {tone === "coral" && <TriangleAlert className="size-2.5" strokeWidth={3} />}
      {count}
    </span>
  );
}

const railItem =
  "dock-item relative flex size-11 shrink-0 items-center justify-center rounded-lg transition-colors";

function RailItem({ to, label, icon: Icon, hue, count, failed, section }: { to: string; label: string; icon: typeof Compass; hue?: Hue; count?: number; failed?: number; section?: SectionKey }) {
  const { pathname } = useLocation();
  // A section entry is lit on every page of its tabs, not only on its own route.
  const isActive = section ? inSection(section, pathname) : pathname === to || pathname.startsWith(`${to}/`);
  return (
    <Link
      to={to}
      title={label}
      aria-label={label}
      aria-current={isActive ? "page" : undefined}
      className={cn(railItem, isActive ? "bg-tint/10 text-foreground" : "text-muted-foreground hover:bg-tint/5 hover:text-foreground")}
    >
      {/* Each section keeps its hue: a tinted tile, solid while it is the open page. */}
      <span className={cn("dock-tile flex size-8 items-center justify-center rounded-md", hue ? (isActive ? HUE_SOLID[hue] : HUE_TILE[hue]) : isActive ? "bg-foreground text-ground" : "")}>
        <Icon className="size-[18px]" />
      </span>
      {!!count && (
        <span className="absolute -top-0.5 -right-0.5">
          <NavBadge count={count} label={t.studio.needsYouCount(count)} tone="amber" />
        </span>
      )}
      {!!failed && (
        <span className="absolute -bottom-0.5 -right-0.5">
          <NavBadge count={failed} label={t.studio.failedCount(failed)} tone="coral" />
        </span>
      )}
    </Link>
  );
}

function EngineBadge() {
  const { info } = useEngine();
  const status = { ready: "done", starting: "review", error: "failed" }[info.status] as "done" | "review" | "failed";
  const label = { ready: t.engine.ready, starting: t.engine.starting, error: t.engine.error }[info.status];
  return (
    <NavLink
      to="/settings"
      className="dock-engine flex size-11 items-center justify-center rounded-lg hover:bg-tint/5"
      title={info.error ? `${label}: ${t.native(info.error)}` : `${label} · ${info.url}`}
      aria-label={label}
    >
      <Led status={status} className="size-2.5" />
    </NavLink>
  );
}

/** Có bản mới trên GitHub: nhắc trên dải menu, bấm để vào Cài đặt. */
function UpdateNotice() {
  const { result } = useUpdater();
  if (!result?.version) return null;
  return (
    <NavLink
      to="/settings"
      title={t.update.available(result.version)}
      aria-label={t.update.available(result.version)}
      className={cn(railItem, "text-mint hover:bg-tint/5 hover:text-mint")}
    >
      <Download className="size-[18px]" />
    </NavLink>
  );
}

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
    <div className="app-shell flex h-screen bg-background text-foreground">
      {/* A button, not a #link: the hash is the router's. */}
      <button
        type="button"
        onClick={() => main.current?.focus()}
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:top-2 focus-visible:left-16 focus-visible:z-50 focus-visible:rounded-lg focus-visible:bg-raised focus-visible:px-3 focus-visible:py-2 focus-visible:text-[13px] focus-visible:font-semibold"
      >
        {t.a11y.skip}
      </button>
      {/* A slim icon rail, like a video editor's: the page gets the whole height. Each icon names itself on hover. */}
      <nav aria-label={t.studio.mainNav} className="dock flex w-16 shrink-0 flex-col items-center border-r bg-monitor py-3">
        <NavLink to="/clips" title={t.appName} aria-label={t.appName} className="dock-brand mb-3 flex size-10 items-center justify-center">
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
        </NavLink>
        <NavLink
          to="/projects/new"
          title={t.board.newVideo}
          aria-label={t.board.newVideo}
          className="dock-new mb-2 flex size-10 items-center justify-center rounded-lg bg-pink text-on-pink hover:bg-primary-hover hover:text-on-pink"
        >
          <Plus className="size-5" />
        </NavLink>
        <div className="dock-groups flex min-h-0 w-full flex-1 flex-col items-center overflow-y-auto">
          {NAV.map((group, i) => (
            <div key={i} className={cn("dock-group flex flex-col items-center gap-1", i > 0 ? "mt-2 w-10 border-t pt-2" : "pt-1")}>
              {group.map(({ to, label, icon, hue, section }) => (
                <RailItem key={to} to={to} label={t.nav[label]} icon={icon} hue={hue} section={section} count={to === "/projects" ? counts?.review : undefined}
                  failed={to === "/projects" ? counts?.failed_recent : undefined}
                />
              ))}
            </div>
          ))}
        </div>
        <div className="dock-foot flex flex-col items-center gap-1 border-t pt-2">
          <UpdateNotice />
          <RailItem to="/settings" label={t.nav.settings} icon={SettingsIcon} />
          <EngineBadge />
        </div>
      </nav>
      <main ref={main} tabIndex={-1} className="app-main min-h-0 min-w-0 flex-1 overflow-y-auto outline-none">
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
