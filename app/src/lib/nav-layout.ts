import { useSyncExternalStore } from "react";

/** How the menu is laid out (Settings → Appearance → Menu). Only the arrangement changes, never the pages. */
export const NAV_LAYOUTS = ["sidebar", "rail", "top", "dock", "split"] as const;
export type NavLayout = (typeof NAV_LAYOUTS)[number];
export const DEFAULT_NAV: NavLayout = "sidebar";
const STORE = "motio.nav";

function stored(): NavLayout {
  try {
    const v = localStorage.getItem(STORE);
    if ((NAV_LAYOUTS as readonly string[]).includes(v ?? "")) return v as NavLayout;
    if (localStorage.getItem("motio.menuWide") === "0") return "rail"; // the collapse button of the first wide menu
  } catch {
    // storage blocked
  }
  return DEFAULT_NAV;
}

let layout: NavLayout = stored();
const listeners = new Set<() => void>();

export function setNavLayout(next: NavLayout) {
  if (next === layout) return;
  layout = next;
  try {
    localStorage.setItem(STORE, next);
  } catch {
    // storage blocked: the choice lasts until the app closes
  }
  listeners.forEach((f) => f());
}

export function useNavLayout(): NavLayout {
  return useSyncExternalStore(
    (f) => {
      listeners.add(f);
      return () => {
        listeners.delete(f);
      };
    },
    () => layout,
  );
}
