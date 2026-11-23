import { Compass, Download, FolderKanban, Plus, Settings as SettingsIcon, TriangleAlert, Wrench } from "lucide-react";
import { Link, NavLink, useLocation } from "react-router";
import { inSection, type SectionKey } from "@/components/section-tabs";
import { HUE_SOLID, HUE_TILE, Led, type Hue } from "@/components/studio";
import { useEngine } from "@/lib/engine";
import { useUpdater } from "@/lib/updater";
import { cn } from "@/lib/utils";
import { t, type Messages } from "@/i18n";

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

function Item({ to, label, icon: Icon, hue, count, failed, section }: { to: string; label: string; icon: typeof Compass; hue?: Hue; count?: number; failed?: number; section?: SectionKey }) {
  const { pathname } = useLocation();
  // A section entry is lit on every page of its tabs, not only on its own route.
  const isActive = section ? inSection(section, pathname) : pathname === to || pathname.startsWith(`${to}/`);
  return (
    <Link
      to={to}
      title={label}
      aria-label={label}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "dock-item relative flex h-14 w-[4.5rem] shrink-0 flex-col items-center justify-center gap-0.5 rounded-xl transition-colors",
        isActive ? "bg-tint/10 text-foreground" : "text-muted-foreground hover:bg-tint/5 hover:text-foreground",
      )}
    >
      {/* Each section keeps its hue: a tinted tile, solid while it is the open page. */}
      <span className={cn("dock-tile flex size-8 shrink-0 items-center justify-center rounded-lg", hue ? (isActive ? HUE_SOLID[hue] : HUE_TILE[hue]) : isActive ? "bg-foreground text-ground" : "")}>
        <Icon className="size-[18px]" />
      </span>
      <span className="dock-label max-w-full truncate text-[11px] font-medium">{label}</span>
      {!!count && (
        <span className="absolute top-0.5 right-2">
          <NavBadge count={count} label={t.studio.needsYouCount(count)} tone="amber" />
        </span>
      )}
      {!!failed && (
        <span className="absolute top-0.5 left-2">
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
      className="dock-engine flex size-10 items-center justify-center rounded-lg hover:bg-tint/5"
      title={info.error ? `${label}: ${t.native(info.error)}` : `${label} · ${info.url}`}
      aria-label={label}
    >
      <Led status={status} className="size-2.5" />
    </NavLink>
  );
}

/** Có bản mới trên GitHub: nhắc trên dock, bấm để vào Cài đặt. */
function UpdateNotice() {
  const { result } = useUpdater();
  if (!result?.version) return null;
  return (
    <NavLink
      to="/settings"
      title={t.update.available(result.version)}
      aria-label={t.update.available(result.version)}
      className="dock-item flex size-11 items-center justify-center rounded-lg text-mint hover:bg-tint/5 hover:text-mint"
    >
      <Download className="size-[18px]" />
    </NavLink>
  );
}

/** Logo: a paper plane taking off with a ribbon trail (cyan wing, magenta wing); same drawing as the app icon, without its tile. */
function Logo() {
  return (
    <svg width="30" height="30" viewBox="405 120 695 610" fill="none" aria-hidden="true" className="shrink-0">
      <defs>
        <linearGradient id="lg-wing" x1="570" y1="277" x2="1095" y2="122" gradientUnits="userSpaceOnUse">
          <stop stopColor="#22f0ff" />
          <stop offset="1" stopColor="#d5f6ff" />
        </linearGradient>
        <linearGradient id="lg-pink" x1="810" y1="360" x2="1040" y2="260" gradientUnits="userSpaceOnUse">
          <stop stopColor="#ffc6ff" />
          <stop offset=".45" stopColor="#ff3fe0" />
          <stop offset="1" stopColor="#ff6fd8" />
        </linearGradient>
        <linearGradient id="lg-rib" x1="480" y1="710" x2="820" y2="470" gradientUnits="userSpaceOnUse">
          <stop stopColor="#4f1cff" />
          <stop offset=".55" stopColor="#b21fff" />
          <stop offset="1" stopColor="#ff3fc8" />
        </linearGradient>
      </defs>
      <path d="M428 664C540 600 700 562 822 462 772 572 700 642 588 672 535 688 500 704 476 724 455 708 440 688 428 664Z" fill="url(#lg-rib)" />
      <path d="M405 608C520 545 640 520 745 488L765 486C640 540 520 598 428 664 418 646 410 628 405 608Z" fill="#25d9ff" />
      <polygon points="570,277 773,310 705,495 710,374" fill="#6b4dff" />
      <polygon points="570,277 1095,122 773,310" fill="url(#lg-wing)" />
      <polygon points="773,310 1095,122 805,355 705,495" fill="#4a14d8" />
      <polygon points="805,355 1095,122 948,475" fill="url(#lg-pink)" />
      <polygon points="805,355 865,405 705,495" fill="#b02cff" />
    </svg>
  );
}

/** The menu: a floating dock at the bottom of the window, icon over name, like a Mac dock. The page keeps the whole window. */
export function AppMenu({ counts }: { counts: Counts }) {
  return (
    <nav aria-label={t.studio.mainNav} className="dock fixed bottom-4 left-1/2 z-40 flex max-w-[calc(100vw-1.5rem)] -translate-x-1/2 items-center gap-1 rounded-2xl border bg-monitor/95 px-2 py-1.5 shadow-2xl backdrop-blur">
      <NavLink to="/clips" title={t.appName} aria-label={t.appName} className="dock-brand flex size-10 shrink-0 items-center justify-center">
        <Logo />
      </NavLink>
      <div className="dock-sep mx-1 h-8 w-px bg-border" />
      {NAV.map((group, i) => (
        <div key={i} className="dock-group flex items-center gap-1">
          {i > 0 && <div className="dock-sep mx-1 h-8 w-px bg-border" />}
          {group.map(({ to, label, icon, hue, section }) => (
            <Item key={to} to={to} label={t.nav[label]} icon={icon} hue={hue} section={section} count={to === "/projects" ? counts?.review : undefined} failed={to === "/projects" ? counts?.failed_recent : undefined} />
          ))}
        </div>
      ))}
      <div className="dock-sep mx-1 h-8 w-px bg-border" />
      <NavLink
        to="/projects/new"
        title={t.board.newVideo}
        aria-label={t.board.newVideo}
        className="dock-new flex size-11 shrink-0 items-center justify-center rounded-xl bg-pink text-on-pink hover:bg-primary-hover hover:text-on-pink"
      >
        <Plus className="size-5" />
      </NavLink>
      <div className="dock-sep mx-1 h-8 w-px bg-border" />
      <UpdateNotice />
      <Item to="/settings" label={t.nav.settings} icon={SettingsIcon} />
      <EngineBadge />
    </nav>
  );
}
