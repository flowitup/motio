import { useQuery } from "@tanstack/react-query";
import { ChevronsLeft, ChevronsRight, Compass, Download, FolderKanban, Plus, Settings as SettingsIcon, TriangleAlert, Wrench } from "lucide-react";
import { Link, NavLink, useLocation } from "react-router";
import { inSection, SECTIONS, type SectionKey } from "@/components/section-tabs";
import { HUE_SOLID, HUE_TILE, Led, type Hue } from "@/components/studio";
import { useApi } from "@/lib/api";
import { useEngine } from "@/lib/engine";
import { setNavLayout, useNavLayout, type NavLayout } from "@/lib/nav-layout";
import { useUpdater } from "@/lib/updater";
import { cn } from "@/lib/utils";
import { t, type Messages } from "@/i18n";
import { SETTINGS_TABS } from "@/pages/settings";

type NavItem = { to: string; label: keyof Messages["nav"]; icon: typeof Compass; hue?: Hue; section?: SectionKey };
/** The menu entries in groups split by a thin rule: find + make, tools. Settings sits apart and holds Channels and Stats as tabs.
 * A `section` entry holds several pages as tabs (Discover: Feed, News topics, Scan; Tools: Quick jobs, Remove logo). */
const NAV: NavItem[][] = [
  [
    { to: "/clips", label: "discover", icon: Compass, hue: "amber", section: "discover" },
    { to: "/projects", label: "projects", icon: FolderKanban, hue: "violet" },
  ],
  [{ to: "/tools", label: "tools", icon: Wrench, hue: "lime", section: "tools" }],
];

/** How one entry is drawn: a tile only (rail), icon + name in a row (wide), a compact row (inline), or icon over name (stack). */
type Mode = "rail" | "wide" | "inline" | "stack";
type Counts = { review?: number; failed_recent?: number } | undefined;

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

const SHAPE: Record<Mode, string> = {
  rail: "size-11 justify-center",
  wide: "h-10 w-full justify-start gap-3 px-2",
  inline: "h-9 justify-start gap-2 px-2.5",
  stack: "h-14 w-[4.5rem] flex-col justify-center gap-0.5",
};

function Item({ to, label, icon: Icon, hue, count, failed, section, mode }: { to: string; label: string; icon: typeof Compass; hue?: Hue; count?: number; failed?: number; section?: SectionKey; mode: Mode }) {
  const { pathname } = useLocation();
  // A section entry is lit on every page of its tabs, not only on its own route.
  const isActive = section ? inSection(section, pathname) : pathname === to || pathname.startsWith(`${to}/`);
  const badges = (
    <>
      {!!count && <NavBadge count={count} label={t.studio.needsYouCount(count)} tone="amber" />}
      {!!failed && <NavBadge count={failed} label={t.studio.failedCount(failed)} tone="coral" />}
    </>
  );
  const floating = mode === "rail" || mode === "stack";
  return (
    <Link
      to={to}
      title={label}
      aria-label={label}
      aria-current={isActive ? "page" : undefined}
      className={cn("dock-item relative flex shrink-0 items-center rounded-lg transition-colors", SHAPE[mode], isActive ? "bg-tint/10 text-foreground" : "text-muted-foreground hover:bg-tint/5 hover:text-foreground")}
    >
      {/* Each section keeps its hue: a tinted tile, solid while it is the open page. */}
      <span className={cn("dock-tile flex shrink-0 items-center justify-center rounded-md", mode === "inline" ? "size-6" : "size-8", hue ? (isActive ? HUE_SOLID[hue] : HUE_TILE[hue]) : isActive ? "bg-foreground text-ground" : "")}>
        <Icon className={mode === "inline" ? "size-4" : "size-[18px]"} />
      </span>
      {mode !== "rail" && <span className={cn("dock-label truncate font-medium", mode === "stack" ? "text-[11px]" : "min-w-0 flex-1 text-left text-[13px]")}>{label}</span>}
      {floating ? (
        <>
          {!!count && <span className="absolute -top-0.5 -right-0.5"><NavBadge count={count} label={t.studio.needsYouCount(count)} tone="amber" /></span>}
          {!!failed && <span className="absolute -bottom-0.5 -right-0.5"><NavBadge count={failed} label={t.studio.failedCount(failed)} tone="coral" /></span>}
        </>
      ) : (
        <span className="flex shrink-0 items-center gap-1">{badges}</span>
      )}
    </Link>
  );
}

function EngineBadge({ mode }: { mode: Mode }) {
  const { info } = useEngine();
  const status = { ready: "done", starting: "review", error: "failed" }[info.status] as "done" | "review" | "failed";
  const label = { ready: t.engine.ready, starting: t.engine.starting, error: t.engine.error }[info.status];
  const text = mode === "wide" || mode === "inline";
  return (
    <NavLink
      to="/settings"
      className={cn("dock-engine flex items-center rounded-lg hover:bg-tint/5", text ? "h-9 gap-3 px-3.5 text-[12px] text-muted-foreground" : "size-11 justify-center", mode === "wide" && "w-full")}
      title={info.error ? `${label}: ${t.native(info.error)}` : `${label} · ${info.url}`}
      aria-label={label}
    >
      <Led status={status} className="size-2.5" />
      {text && <span className="min-w-0 flex-1 truncate">{label}</span>}
    </NavLink>
  );
}

/** Có bản mới trên GitHub: nhắc trên dải menu, bấm để vào Cài đặt. */
function UpdateNotice({ mode }: { mode: Mode }) {
  const { result } = useUpdater();
  if (!result?.version) return null;
  const text = mode === "wide" || mode === "inline";
  return (
    <NavLink
      to="/settings"
      title={t.update.available(result.version)}
      aria-label={t.update.available(result.version)}
      className={cn("dock-item flex items-center rounded-lg text-mint hover:bg-tint/5 hover:text-mint", text ? "h-10 gap-3 px-3" : "size-11 justify-center", mode === "wide" && "w-full")}
    >
      <Download className="size-[18px] shrink-0" />
      {text && <span className="min-w-0 flex-1 truncate text-left text-[13px] font-medium">{t.update.available(result.version)}</span>}
    </NavLink>
  );
}

/** Logo C: seven rounded bars whose envelope forms an M; amber = original voice, cyan = French dub. */
function Logo() {
  return (
    <svg width="28" height="22" viewBox="6 8 106 84" fill="none" strokeWidth="10" strokeLinecap="round" aria-hidden="true" className="shrink-0">
      <g stroke="var(--amber)">
        <path d="M11 31v38M27 13v74M43 24v52" />
      </g>
      <path d="M59 40v20" stroke="var(--foreground)" />
      <g stroke="var(--cyan)">
        <path d="M75 24v52M91 13v74M107 31v38" />
      </g>
    </svg>
  );
}

function Brand({ word }: { word: boolean }) {
  return (
    <NavLink to="/clips" title={t.appName} aria-label={t.appName} className={cn("dock-brand flex h-10 shrink-0 items-center", word ? "gap-2.5 px-1.5" : "w-10 justify-center")}>
      <Logo />
      {word && <span className="dock-wordmark text-[17px] font-semibold tracking-tight">{t.appName}</span>}
    </NavLink>
  );
}

function NewVideo({ mode }: { mode: Mode }) {
  return (
    <NavLink
      to="/projects/new"
      title={t.board.newVideo}
      aria-label={t.board.newVideo}
      className={cn(
        "dock-new flex shrink-0 items-center justify-center rounded-lg bg-pink text-on-pink hover:bg-primary-hover hover:text-on-pink",
        mode === "wide" ? "h-10 w-full gap-2 text-[13px] font-semibold" : mode === "inline" ? "h-9 gap-1.5 px-3 text-[13px] font-semibold" : "size-10",
      )}
    >
      <Plus className="size-5" />
      {(mode === "wide" || mode === "inline") && t.board.newVideo}
    </NavLink>
  );
}

function Entries({ mode, counts, row }: { mode: Mode; counts: Counts; row?: boolean }) {
  return (
    <>
      {NAV.map((group, i) => (
        <div
          key={i}
          className={cn(
            "dock-group flex gap-1",
            row ? "flex-row items-center" : cn("flex-col", mode === "rail" ? "items-center" : "items-stretch"),
            i > 0 && (row ? "ml-1 border-l pl-2" : cn("mt-2 border-t pt-2", mode === "rail" && "w-10")),
            i === 0 && !row && "pt-1",
          )}
        >
          {group.map(({ to, label, icon, hue, section }) => (
            <Item key={to} to={to} label={t.nav[label]} icon={icon} hue={hue} section={section} mode={mode} count={to === "/projects" ? counts?.review : undefined} failed={to === "/projects" ? counts?.failed_recent : undefined} />
          ))}
        </div>
      ))}
    </>
  );
}

/** Pages of the open section for the second column of the "split" layout. */
function useSubPages(counts: Counts): { to: string; label: string; count?: number; active: boolean; section?: boolean }[] {
  const api = useApi();
  const { pathname, search } = useLocation();
  const { data: state } = useQuery({ queryKey: ["state"], queryFn: () => api!.state(), enabled: !!api, refetchInterval: 30_000 });
  for (const key of Object.keys(SECTIONS) as SectionKey[]) {
    if (!inSection(key, pathname)) continue;
    return SECTIONS[key].tabs
      .filter((tab) => tab.to !== "/news" || !!state?.news_topics)
      .map((tab) => ({ to: tab.to, label: t.nav[tab.label], active: pathname === tab.to || pathname.startsWith(`${tab.to}/`) }));
  }
  if (pathname.startsWith("/settings")) {
    const tab = new URLSearchParams(search).get("tab") ?? "general";
    return SETTINGS_TABS.map((id) => ({ to: `/settings?tab=${id}`, label: t.settings.tabs[id], active: tab === id }));
  }
  if (pathname.startsWith("/projects") || pathname.startsWith("/review") || pathname.startsWith("/clip-studio")) {
    return [
      { to: "/projects", label: t.nav.projects, active: pathname === "/projects" },
      { to: "/review", label: t.queue.title, count: counts?.review, active: pathname.startsWith("/review") },
      { to: "/projects/new", label: t.board.newVideo, active: pathname === "/projects/new" },
    ];
  }
  return [];
}

function SubColumn({ counts, title }: { counts: Counts; title: string }) {
  const pages = useSubPages(counts);
  return (
    <div className="dock-sub flex w-48 shrink-0 flex-col gap-1 border-r bg-monitor/60 px-3 py-4" aria-label={title}>
      <p className="px-2 pb-2 font-mono text-[11px] tracking-wider text-muted-foreground uppercase">{title}</p>
      {pages.map((p) => (
        <Link
          key={p.to}
          to={p.to}
          aria-current={p.active ? "page" : undefined}
          className={cn("flex h-9 items-center justify-between gap-2 rounded-lg px-2.5 text-[13px] font-medium", p.active ? "bg-tint/10 text-foreground" : "text-muted-foreground hover:bg-tint/5 hover:text-foreground")}
        >
          <span className="truncate">{p.label}</span>
          {!!p.count && <NavBadge count={p.count} label={t.studio.needsYouCount(p.count)} tone="amber" />}
        </Link>
      ))}
    </div>
  );
}

function sectionTitle(pathname: string) {
  if (pathname.startsWith("/settings")) return t.nav.settings;
  for (const key of Object.keys(SECTIONS) as SectionKey[]) if (inSection(key, pathname)) return t.nav[key];
  return t.nav.projects;
}

/** The menu, drawn for the layout picked in Settings → Appearance → Menu. */
export function AppMenu({ counts }: { counts: Counts }) {
  const layout: NavLayout = useNavLayout();
  const { pathname } = useLocation();
  const aria = t.studio.mainNav;

  if (layout === "top")
    return (
      <nav aria-label={aria} className="dock dock-top flex h-14 w-full shrink-0 items-center gap-3 border-b bg-monitor px-4">
        <Brand word />
        <div className="ml-3 flex items-center gap-1">
          <Entries mode="inline" counts={counts} row />
        </div>
        <div className="flex-1" />
        <NewVideo mode="inline" />
        <UpdateNotice mode="inline" />
        <Item to="/settings" label={t.nav.settings} icon={SettingsIcon} mode="inline" />
        <EngineBadge mode="rail" />
      </nav>
    );

  if (layout === "dock")
    return (
      <nav aria-label={aria} className="dock dock-float fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-1 rounded-2xl border bg-monitor/95 px-2 py-1.5 shadow-2xl backdrop-blur">
        <Brand word={false} />
        <div className="mx-1 h-8 w-px bg-border" />
        <Entries mode="stack" counts={counts} row />
        <div className="mx-1 h-8 w-px bg-border" />
        <NewVideo mode="rail" />
        <div className="mx-1 h-8 w-px bg-border" />
        <UpdateNotice mode="rail" />
        <Item to="/settings" label={t.nav.settings} icon={SettingsIcon} mode="stack" />
        <EngineBadge mode="rail" />
      </nav>
    );

  const wide = layout === "sidebar";
  const mode: Mode = wide ? "wide" : "rail";
  return (
    <>
      <nav aria-label={aria} className={cn("dock flex shrink-0 flex-col border-r bg-monitor py-3", wide ? "w-52 items-stretch px-3" : "w-16 items-center")}>
        <div className="mb-3"><Brand word={wide} /></div>
        <div className={cn("mb-3", !wide && "self-center")}><NewVideo mode={mode} /></div>
        <div className={cn("dock-groups flex min-h-0 w-full flex-1 flex-col overflow-y-auto", !wide && "items-center")}>
          <Entries mode={mode} counts={counts} />
        </div>
        <div className={cn("dock-foot flex flex-col gap-1 border-t pt-2", wide ? "items-stretch" : "items-center")}>
          <UpdateNotice mode={mode} />
          <Item to="/settings" label={t.nav.settings} icon={SettingsIcon} mode={mode} />
          <EngineBadge mode={mode} />
          {layout !== "split" && (
            <button
              type="button"
              onClick={() => setNavLayout(wide ? "rail" : "sidebar")}
              title={wide ? t.studio.menuCollapse : t.studio.menuExpand}
              aria-label={wide ? t.studio.menuCollapse : t.studio.menuExpand}
              className={cn("dock-toggle flex items-center rounded-lg text-muted-foreground hover:bg-tint/5 hover:text-foreground", wide ? "h-9 w-full gap-3 px-3.5 text-[12px]" : "size-11 justify-center")}
            >
              {wide ? <ChevronsLeft className="size-4 shrink-0" /> : <ChevronsRight className="size-4" />}
              {wide && <span className="min-w-0 flex-1 truncate text-left">{t.studio.menuCollapse}</span>}
            </button>
          )}
        </div>
      </nav>
      {layout === "split" && <SubColumn counts={counts} title={sectionTitle(pathname)} />}
    </>
  );
}
