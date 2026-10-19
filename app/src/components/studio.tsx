import { useRef, type KeyboardEvent, type ReactNode } from "react";
import type { ProjectStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

/* Pieces of the "Studio" look that more than one screen uses: LED statuses, score meters, docked panels,
   the 56 px top bar and the segmented control. Colours come from the tokens in index.css. */

/** The palette's hues: each section, panel and chip gets one so the screen is told apart by colour, not only by position. */
export type Hue = "pink" | "amber" | "cyan" | "mint" | "coral" | "lime" | "violet" | "orange" | "blue";
export const HUE_TEXT: Record<Hue, string> = {
  pink: "text-pink",
  amber: "text-amber",
  cyan: "text-cyan",
  mint: "text-mint",
  coral: "text-coral",
  lime: "text-lime",
  violet: "text-violet",
  orange: "text-orange",
  blue: "text-blue",
};
export const HUE_DOT: Record<Hue, string> = {
  pink: "bg-pink",
  amber: "bg-amber",
  cyan: "bg-cyan",
  mint: "bg-mint",
  coral: "bg-coral",
  lime: "bg-lime",
  violet: "bg-violet",
  orange: "bg-orange",
  blue: "bg-blue",
};
export const HUE_BORDER: Record<Hue, string> = {
  pink: "border-pink/55",
  amber: "border-amber/55",
  cyan: "border-cyan/55",
  mint: "border-mint/55",
  coral: "border-coral/55",
  lime: "border-lime/55",
  violet: "border-violet/55",
  orange: "border-orange/55",
  blue: "border-blue/55",
};
export const HUE_TILE: Record<Hue, string> = {
  pink: "bg-pink/16 text-pink",
  amber: "bg-amber/16 text-amber",
  cyan: "bg-cyan/16 text-cyan",
  mint: "bg-mint/16 text-mint",
  coral: "bg-coral/16 text-coral",
  lime: "bg-lime/16 text-lime",
  violet: "bg-violet/16 text-violet",
  orange: "bg-orange/16 text-orange",
  blue: "bg-blue/16 text-blue",
};
export const HUE_SOLID: Record<Hue, string> = {
  pink: "bg-pink text-on-pink",
  amber: "bg-amber text-on-amber",
  cyan: "bg-cyan text-ground",
  mint: "bg-mint text-ground",
  coral: "bg-coral text-ground",
  lime: "bg-lime text-ground",
  violet: "bg-violet text-ground",
  orange: "bg-orange text-ground",
  blue: "bg-blue text-ground",
};
const HUE_ORDER: Hue[] = ["cyan", "violet", "lime", "pink", "amber", "mint", "orange", "coral"];
/** A panel with no hue of its own gets a steady one from its title, so the same panel is always the same colour. */
export function hueFor(key: string): Hue {
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return HUE_ORDER[h % HUE_ORDER.length];
}

const LED: Record<ProjectStatus, string> = {
  queued: "box-border border-2 border-muted-foreground",
  running: "bg-cyan shadow-[0_0_0_3px_rgb(63_224_245/0.22)]",
  review: "bg-amber shadow-[0_0_0_3px_rgb(255_178_36/0.22)]",
  done: "bg-mint",
  failed: "bg-coral",
};
/** The hue of each project status (queued has none: it stays neutral). */
export const STATUS_HUE: Record<ProjectStatus, Hue | undefined> = { queued: undefined, running: "cyan", review: "amber", done: "mint", failed: "coral" };
/** Followed sources, one hue per site. */
export const SITE_HUE: Record<string, Hue> = { bilibili: "cyan", douyin: "pink", kuaishou: "amber", weibo: "coral", acfun: "violet", pearvideo: "lime", youtube: "orange" };

const LED_TEXT: Record<ProjectStatus, string> = {
  queued: "text-muted-foreground",
  running: "text-cyan",
  review: "text-amber",
  done: "text-mint",
  failed: "text-coral",
};

/** The dot alone: a ring for queued, a halo for running and awaiting approval, solid for done / failed. */
export function Led({ status, className }: { status: ProjectStatus; className?: string }) {
  return <span aria-hidden className={cn("size-2 shrink-0 rounded-full", LED[status], className)} />;
}

/** LED + the word, never a filled pill: the word carries the meaning, the colour only helps. */
export function LedLabel({ status, children, className }: { status: ProjectStatus; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-xs leading-4 font-medium whitespace-nowrap", LED_TEXT[status], className)}>
      <Led status={status} />
      {children}
    </span>
  );
}

const STICKER: Record<ProjectStatus, string> = {
  queued: "bg-lift text-foreground",
  running: "bg-cyan text-ground",
  review: "bg-amber text-on-amber",
  done: "bg-mint text-ground",
  failed: "bg-coral text-ground",
};
/** A solid, coloured status label for use on top of a picture (the project poster). */
export function StatusSticker({ status, children, className }: { status: ProjectStatus; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex h-[26px] items-center gap-1.5 rounded-full px-2.5 text-xs leading-4 font-bold whitespace-nowrap", STICKER[status], className)}>
      <span aria-hidden className="size-2 shrink-0 rounded-full bg-current" />
      {children}
    </span>
  );
}

export type Tone = "hot" | "warm" | "cool";
export const toneOf = (score: number): Tone => (score >= 75 ? "hot" : score >= 50 ? "warm" : "cool");
const TONE_TEXT: Record<Tone, string> = { hot: "text-pink", warm: "text-cyan", cool: "text-muted-foreground" };
const TONE_FILL: Record<Tone, string> = { hot: "bg-pink", warm: "bg-cyan", cool: "bg-muted-foreground" };

/** A thin bar filled to `value` %, with a 1 px gap at 50 and 75 (the tone thresholds). `gap` = the colour behind it. */
export function Meter({ value, tone, height = 4, gap = "bg-panel", className }: { value: number; tone: Tone; height?: 4 | 8; gap?: string; className?: string }) {
  return (
    <div className={cn("relative overflow-hidden rounded-xs bg-white/12", height === 8 ? "h-2" : "h-1", className)}>
      <div className={cn("h-full", TONE_FILL[tone])} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      <div className={cn("absolute top-0 left-1/2 h-full w-px", gap)} />
      <div className={cn("absolute top-0 left-3/4 h-full w-px", gap)} />
    </div>
  );
}

/** Ledger score: mono number over a meter (75+ pink, 50 to 74 cyan, under 50 grey). */
export function ScoreBadge({ score, gap, className }: { score: number; gap?: string; className?: string }) {
  const tone = toneOf(score);
  return (
    <div className={cn("flex w-14 shrink-0 flex-col gap-1.5", className)}>
      <span className={cn("font-mono text-[22px] leading-6 font-medium tabular-nums", TONE_TEXT[tone])}>{score}</span>
      <Meter value={score} tone={tone} gap={gap} />
    </div>
  );
}
export const toneText = (score: number) => TONE_TEXT[toneOf(score)];

/** The news source (Weibo, Douyin…) as a small mono badge. */
export function SourceBadge({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-lg border border-hairline-strong px-1.5 font-mono text-xs leading-4 font-medium tracking-[0.04em] whitespace-nowrap text-foreground uppercase",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Small uppercase overline inside content ("Angle", "Narration"). */
export function Kicker({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("text-xs leading-4 font-semibold tracking-[0.08em] text-muted-foreground uppercase", className)}>{children}</div>;
}

/** The 56 px bar at the top of a page: title (or breadcrumb) on the left, actions on the right. */
export function TopBar({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <header className={cn("sticky top-0 z-20 flex h-14 shrink-0 items-center gap-4 border-b bg-ground px-6", className)}>{children}</header>
  );
}
export function PageTitle({ children, className }: { children: ReactNode; className?: string }) {
  return <h1 className={cn("min-w-0 truncate text-xl leading-7 font-semibold tracking-[-0.01em] whitespace-nowrap", className)}>{children}</h1>;
}

/** A docked panel: 40 px header strip with a mono caption (and an optional readout / action), then the body. No gaps, no shadows. */
export function Panel({
  title,
  aside,
  children,
  className,
  bodyClassName,
  flush,
  hue,
}: {
  title: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  flush?: boolean; // body without padding
  hue?: Hue;
}) {
  return (
    <section className={cn("flex flex-col border-b bg-panel", className)}>
      <PanelHeader aside={aside} hue={hue}>
        {title}
      </PanelHeader>
      <div className={cn(!flush && "p-4", bodyClassName)}>{children}</div>
    </section>
  );
}
export function PanelHeader({ children, aside, className, hue }: { children: ReactNode; aside?: ReactNode; className?: string; hue?: Hue }) {
  const h = hue ?? (typeof children === "string" ? hueFor(children) : "cyan");
  return (
    <header className={cn("flex h-10 shrink-0 items-center justify-between gap-3 border-b bg-strip px-4", className)}>
      <h2 className={cn("flex items-center gap-2.5 font-mono text-xs leading-4 font-medium tracking-[0.06em] uppercase", HUE_TEXT[h])}>
        <span aria-hidden className={cn("size-2 shrink-0 rounded-full", HUE_DOT[h])} />
        {children}
      </h2>
      {aside && <div className="font-mono text-xs leading-4 whitespace-nowrap text-muted-foreground tabular-nums">{aside}</div>}
    </header>
  );
}

/**
 * Segmented control: the selected option is filled: pink for the page's main switch (accent="pink"), cyan when it picks a value.
 * One stop in the Tab order; the arrow keys, Home and End move the choice. `tabs` makes it a tab strip (role tablist)
 * instead of a one-of-n value (role radiogroup).
 */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  className,
  label,
  tabs,
  accent = "cyan",
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode }[];
  className?: string;
  label?: string;
  tabs?: boolean;
  accent?: "cyan" | "pink";
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const current = options.some((o) => o.value === value) ? value : options[0]?.value;
  const onKey = (e: KeyboardEvent, i: number) => {
    const n = options.length;
    const j = { ArrowRight: (i + 1) % n, ArrowDown: (i + 1) % n, ArrowLeft: (i - 1 + n) % n, ArrowUp: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
    if (j === undefined) return;
    e.preventDefault();
    onChange(options[j].value);
    refs.current[j]?.focus();
  };
  return (
    <div role={tabs ? "tablist" : "radiogroup"} aria-label={label} className={cn("inline-flex h-11 overflow-hidden rounded-md border border-field bg-ground", className)}>
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role={tabs ? "tab" : "radio"}
            {...(tabs ? { "aria-selected": on } : { "aria-checked": on })}
            tabIndex={o.value === current ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKey(e, i)}
            className={cn(
              "relative inline-flex min-w-0 flex-1 items-center justify-center gap-2 px-3 text-[13px] leading-4 font-semibold whitespace-nowrap transition-colors focus-visible:-outline-offset-2",
              i > 0 && "border-l border-hairline-strong",
              on ? (accent === "pink" ? "bg-pink font-bold text-on-pink" : "bg-cyan font-bold text-ground") : "text-muted-foreground hover:bg-raised hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** A filter chip with a count (Projects status filter): outlined in its hue, filled white when chosen. */
export function FilterChip({
  on,
  onClick,
  children,
  count,
  led,
  hue,
}: {
  on: boolean;
  onClick: () => void;
  children: ReactNode;
  count: number;
  led?: ReactNode;
  hue?: Hue;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "relative inline-flex h-10 items-center gap-2 rounded-full border px-3.5 text-[13px] leading-4 font-semibold whitespace-nowrap transition-colors",
        on
          ? "border-foreground bg-foreground text-ground"
          : cn(hue ? HUE_BORDER[hue] : "border-hairline-strong", "bg-panel text-foreground hover:bg-raised"),
      )}
    >
      {led}
      {children}
      <span className="font-mono text-xs tabular-nums">{count}</span>
    </button>
  );
}
