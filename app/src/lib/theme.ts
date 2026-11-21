import { useSyncExternalStore } from "react";

/** The app's looks (Settings → Appearance). Each one is a set of tokens in themes.css; "neon" is the original Neon Studio. */
export const THEMES = ["neon", "daylight", "paper", "terminal", "aurora", "pop"] as const;
export type Theme = (typeof THEMES)[number];
const DARK: ReadonlySet<Theme> = new Set(["neon", "terminal", "aurora"]);
const STORE = "motio.theme";

function stored(): Theme {
  try {
    const v = localStorage.getItem(STORE);
    return (THEMES as readonly string[]).includes(v ?? "") ? (v as Theme) : "neon";
  } catch {
    return "neon";
  }
}

let theme: Theme = stored();
const listeners = new Set<() => void>();

function apply(next: Theme) {
  const html = document.documentElement;
  html.dataset.theme = next;
  html.classList.toggle("dark", DARK.has(next)); // shadcn's dark: variants follow the theme
}
apply(theme);

/** Switch the look now and remember it on this machine. Nothing is rebuilt: only the tokens change. */
export function setTheme(next: Theme) {
  if (next === theme) return;
  theme = next;
  apply(next);
  try {
    localStorage.setItem(STORE, next);
  } catch {
    // storage blocked: the choice lasts until the app closes
  }
  listeners.forEach((f) => f());
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    (f) => {
      listeners.add(f);
      return () => {
        listeners.delete(f);
      };
    },
    () => theme,
  );
}

/** The type the app is set in (Settings → Appearance → Font). "theme" keeps the look's own fonts; the others put one
 *  pairing (text + numbers) over any look. Every face is bundled and covers Vietnamese. */
export const FONTS = ["theme", "inter", "jakarta", "vietnam", "lexend", "archivo"] as const;
export type Font = (typeof FONTS)[number];
const FONT_STORE = "motio.font";
/** Be Vietnam Pro over every look until the owner picks another (owner, 2026-11-21: "4 đi"). */
export const DEFAULT_FONT: Font = "vietnam";

function storedFont(): Font {
  try {
    const v = localStorage.getItem(FONT_STORE);
    return (FONTS as readonly string[]).includes(v ?? "") ? (v as Font) : DEFAULT_FONT;
  } catch {
    return DEFAULT_FONT;
  }
}

let font: Font = storedFont();
const fontListeners = new Set<() => void>();

function applyFont(next: Font) {
  const html = document.documentElement;
  if (next === "theme") delete html.dataset.font;
  else html.dataset.font = next;
}
applyFont(font);

export function setFont(next: Font) {
  if (next === font) return;
  font = next;
  applyFont(next);
  try {
    localStorage.setItem(FONT_STORE, next);
  } catch {
    // storage blocked: the choice lasts until the app closes
  }
  fontListeners.forEach((f) => f());
}

export function useFont(): Font {
  return useSyncExternalStore(
    (f) => {
      fontListeners.add(f);
      return () => {
        fontListeners.delete(f);
      };
    },
    () => font,
  );
}
