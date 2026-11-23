import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronsLeft, ChevronsRight, Compass, Download, FolderKanban, Loader2, Plus, Settings as SettingsIcon, TriangleAlert, Wrench } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
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

type NavItem = { to: string; label: keyof Messages["nav"]; icon: typeof Compass; hue?: Hue; section?: SectionKey };
/** The slim icon rail on the left, in groups split by a thin rule: find + make, tools. Settings sits at the bottom and holds Channels and Stats as tabs.
 * A `section` entry holds several pages as tabs (Discover: Feed, News topics, Scan; Tools: Quick jobs, Remove logo). */
const NAV: NavItem[][] = [
  [
    { to: "/clips", label: "discover", icon: Compass, hue: "amber", section: "discover" },
    { to: "/projects", label: "projects", icon: FolderKanban, hue: "violet" },
  ],
  [{ to: "/tools", label: "tools", icon: Wrench, hue: "lime", section: "tools" }],
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

function RailItem({ to, label, icon: Icon, hue, count, failed, section, wide }: { to: string; label: string; icon: typeof Compass; hue?: Hue; count?: number; failed?: number; section?: SectionKey; wide?: boolean }) {
  const { pathname } = useLocation();
  // A section entry is lit on every page of its tabs, not only on its own route.
  const isActive = section ? inSection(section, pathname) : pathname === to || pathname.startsWith(`${to}/`);
  return (
    <Link
      to={to}
      title={label}
      aria-label={label}
      aria-current={isActive ? "page" : undefined}
      className={cn(railItem, wide && "h-10 w-full justify-start gap-3 px-2", isActive ? "bg-tint/10 text-foreground" : "text-muted-foreground hover:bg-tint/5 hover:text-foreground")}
    >
      {/* Each section keeps its hue: a tinted tile, solid while it is the open page. */}
      <span className={cn("dock-tile flex size-8 items-center justify-center rounded-md", hue ? (isActive ? HUE_SOLID[hue] : HUE_TILE[hue]) : isActive ? "bg-foreground text-ground" : "")}>
        <Icon className="size-[18px]" />
      </span>
      {wide && <span className="dock-label min-w-0 flex-1 truncate text-left text-[13px] font-medium">{label}</span>}
      {wide ? (
        <span className="flex shrink-0 items-center gap-1">
          {!!count && <NavBadge count={count} label={t.studio.needsYouCount(count)} tone="amber" />}
          {!!failed && <NavBadge count={failed} label={t.studio.failedCount(failed)} tone="coral" />}
        </span>
      ) : (
        <>
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
        </>
      )}
    </Link>
  );
}

function EngineBadge({ wide }: { wide?: boolean }) {
  const { info } = useEngine();
  const status = { ready: "done", starting: "review", error: "failed" }[info.status] as "done" | "review" | "failed";
  const label = { ready: t.engine.ready, starting: t.engine.starting, error: t.engine.error }[info.status];
  return (
    <NavLink
      to="/settings"
      className={cn("dock-engine flex items-center rounded-lg hover:bg-tint/5", wide ? "h-9 w-full gap-3 px-3.5 text-[12px] text-muted-foreground" : "size-11 justify-center")}
      title={info.error ? `${label}: ${t.native(info.error)}` : `${label} · ${info.url}`}
      aria-label={label}
    >
      <Led status={status} className="size-2.5" />
      {wide && <span className="min-w-0 flex-1 truncate">{label}</span>}
    </NavLink>
  );
}

/** Có bản mới trên GitHub: nhắc trên dải menu, bấm để vào Cài đặt. */
function UpdateNotice({ wide }: { wide?: boolean }) {
  const { result } = useUpdater();
  if (!result?.version) return null;
  return (
    <NavLink
      to="/settings"
      title={t.update.available(result.version)}
      aria-label={t.update.available(result.version)}
      className={cn(railItem, wide && "h-10 w-full justify-start gap-3 px-3", "text-mint hover:bg-tint/5 hover:text-mint")}
    >
      <Download className="size-[18px] shrink-0" />
      {wide && <span className="min-w-0 flex-1 truncate text-left text-[13px] font-medium">{t.update.available(result.version)}</span>}
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

const WIDE_STORE = "motio.menuWide";

/** The left menu: names next to the icons (default) or the slim icon rail. Remembered on this machine. */
function useWideMenu(): [boolean, () => void] {
  const [wide, setWide] = useState(() => {
    try {
      return localStorage.getItem(WIDE_STORE) !== "0";
    } catch {
      return true;
    }
  });
  const toggle = () =>
    setWide((w) => {
      try {
        localStorage.setItem(WIDE_STORE, w ? "0" : "1");
      } catch {
        // storage blocked: the choice lasts until the app closes
      }
      return !w;
    });
  return [wide, toggle];
}

export default function App() {
  const { info } = useEngine();
  const [wide, toggleWide] = useWideMenu();
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
      {/* The left menu: icon + name by default, or a slim icon rail (the chevron at the bottom switches). */}
      <nav aria-label={t.studio.mainNav} className={cn("dock flex shrink-0 flex-col border-r bg-monitor py-3", wide ? "w-52 items-stretch px-3" : "w-16 items-center")} data-wide={wide ? "true" : undefined}>
        <NavLink to="/clips" title={t.appName} aria-label={t.appName} className={cn("dock-brand mb-3 flex h-10 items-center", wide ? "gap-2.5 px-1.5" : "w-10 justify-center")}>
          {/* Logo C: seven rounded bars whose envelope forms an M; amber = original voice, cyan = French dub. */}
          <svg width="28" height="22" viewBox="6 8 106 84" fill="none" strokeWidth="10" strokeLinecap="round" aria-hidden="true" className="shrink-0">
            <g stroke="var(--amber)">
              <path d="M11 31v38M27 13v74M43 24v52" />
            </g>
            <path d="M59 40v20" stroke="var(--foreground)" />
            <g stroke="var(--cyan)">
              <path d="M75 24v52M91 13v74M107 31v38" />
            </g>
          </svg>
          {wide && <span className="dock-wordmark text-[17px] font-semibold tracking-tight">{t.appName}</span>}
        </NavLink>
        <NavLink
          to="/projects/new"
          title={t.board.newVideo}
          aria-label={t.board.newVideo}
          className={cn("dock-new mb-3 flex items-center justify-center rounded-lg bg-pink text-on-pink hover:bg-primary-hover hover:text-on-pink", wide ? "h-10 w-full gap-2 text-[13px] font-semibold" : "size-10 self-center")}
        >
          <Plus className="size-5" />
          {wide && t.board.newVideo}
        </NavLink>
        <div className={cn("dock-groups flex min-h-0 w-full flex-1 flex-col overflow-y-auto", !wide && "items-center")}>
          {NAV.map((group, i) => (
            <div key={i} className={cn("dock-group flex flex-col gap-1", wide ? "items-stretch" : "items-center", i > 0 ? cn("mt-2 border-t pt-2", !wide && "w-10") : "pt-1")}>
              {group.map(({ to, label, icon, hue, section }) => (
                <RailItem key={to} to={to} label={t.nav[label]} icon={icon} hue={hue} section={section} wide={wide} count={to === "/projects" ? counts?.review : undefined}
                  failed={to === "/projects" ? counts?.failed_recent : undefined}
                />
              ))}
            </div>
          ))}
        </div>
        <div className={cn("dock-foot flex flex-col gap-1 border-t pt-2", wide ? "items-stretch" : "items-center")}>
          <UpdateNotice wide={wide} />
          <RailItem to="/settings" label={t.nav.settings} icon={SettingsIcon} wide={wide} />
          <EngineBadge wide={wide} />
          <button
            type="button"
            onClick={toggleWide}
            title={wide ? t.studio.menuCollapse : t.studio.menuExpand}
            aria-label={wide ? t.studio.menuCollapse : t.studio.menuExpand}
            aria-pressed={wide}
            className={cn("dock-toggle flex items-center rounded-lg text-muted-foreground hover:bg-tint/5 hover:text-foreground", wide ? "h-9 w-full gap-3 px-3.5 text-[12px]" : "size-11 justify-center")}
          >
            {wide ? <ChevronsLeft className="size-4 shrink-0" /> : <ChevronsRight className="size-4" />}
            {wide && <span className="min-w-0 flex-1 truncate text-left">{t.studio.menuCollapse}</span>}
          </button>
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
