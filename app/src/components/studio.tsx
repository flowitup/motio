import { useRef, type KeyboardEvent, type ReactNode } from "react";
import type { ProjectStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

/* Pieces of the "Studio" look that more than one screen uses: LED statuses, score meters, docked panels,
   the 56 px top bar and the segmented control. Colours come from the tokens in index.css. */

const LED: Record<ProjectStatus, string> = {
  queued: "box-border border-2 border-muted-foreground",
  running: "bg-cyan shadow-[0_0_0_3px_rgb(92_200_245/0.22)]",
  review: "bg-amber shadow-[0_0_0_3px_rgb(255_178_36/0.22)]",
  done: "bg-mint",
  failed: "bg-coral",
};
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

export type Tone = "hot" | "warm" | "cool";
export const toneOf = (score: number): Tone => (score >= 75 ? "hot" : score >= 50 ? "warm" : "cool");
const TONE_TEXT: Record<Tone, string> = { hot: "text-amber", warm: "text-cyan", cool: "text-muted-foreground" };
const TONE_FILL: Record<Tone, string> = { hot: "bg-amber", warm: "bg-cyan", cool: "bg-muted-foreground" };

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

/** Ledger score: mono number over a meter (75+ amber, 50 to 74 cyan, under 50 grey). */
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
}: {
  title: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  flush?: boolean; // body without padding
}) {
  return (
    <section className={cn("flex flex-col border-b bg-panel", className)}>
      <PanelHeader aside={aside}>{title}</PanelHeader>
      <div className={cn(!flush && "p-4", bodyClassName)}>{children}</div>
    </section>
  );
}
export function PanelHeader({ children, aside, className }: { children: ReactNode; aside?: ReactNode; className?: string }) {
  return (
    <header className={cn("flex h-10 shrink-0 items-center justify-between gap-3 border-b bg-strip px-4", className)}>
      <h2 className="font-mono text-xs leading-4 font-medium tracking-[0.06em] text-muted-foreground uppercase">{children}</h2>
      {aside && <div className="font-mono text-xs leading-4 whitespace-nowrap text-muted-foreground tabular-nums">{aside}</div>}
    </header>
  );
}

/**
 * Segmented control: the selected option is raised and carries a 2 px amber bar along its bottom edge.
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
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode }[];
  className?: string;
  label?: string;
  tabs?: boolean;
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
              on ? "bg-lift text-foreground" : "text-muted-foreground hover:bg-raised hover:text-foreground",
            )}
          >
            {o.label}
            {on && <span className="absolute inset-x-2.5 bottom-0 h-0.5 bg-amber" />}
          </button>
        );
      })}
    </div>
  );
}

/** A filter chip with a count (Projects status filter): same marker as the segmented control. */
export function FilterChip({
  on,
  onClick,
  children,
  count,
  led,
}: {
  on: boolean;
  onClick: () => void;
  children: ReactNode;
  count: number;
  led?: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "relative inline-flex h-10 items-center gap-2 rounded-lg border px-3 text-[13px] leading-4 font-medium whitespace-nowrap transition-colors",
        on ? "border-hairline-strong bg-lift text-foreground" : "border-hairline-strong bg-transparent text-muted-foreground hover:bg-raised hover:text-foreground",
      )}
    >
      {led}
      {children}
      <span className="font-mono text-xs tabular-nums">{count}</span>
      {on && <span className="absolute inset-x-2.5 bottom-0 h-0.5 bg-amber" />}
    </button>
  );
}
