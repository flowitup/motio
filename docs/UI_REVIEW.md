# UI review checklist

Run it on every PR that changes `app/src`. Rules are in `docs/DESIGN.md`.

1. **Type floor.** No `text-[10px]` / `text-[11px]` outside the rail count badge:
   `grep -rnE "text-\[(10|11)px\]" app/src`.
2. **Captions.** Panel, card and table titles use the mono caption style, not 14 to 15 px sans.
3. **Window sizes.** Look at each changed screen at 1440 x 900, 1280 x 820 and 960 x 640: no horizontal overflow,
   clipped or overlapping text, nothing hidden behind the sticky Save bar. A quick way:
   `node <ak-frontend-design>/scripts/render-check.mjs "http://localhost:1420/#/<route>" --viewports 1440x900,1280x820,960x640`
   against `pnpm dev` with `VITE_ENGINE_URL` / `VITE_ENGINE_TOKEN` pointing at an engine started with its own
   `MOTIO_DATA` (never the data of an open Motio app).
4. **Copy.** New text is in both catalogs, says what the screen does in plain words, and does not depend on layout
   ("on the left").
5. **Keyboard and focus.** Every control reaches the cyan focus ring with Tab; icon-only buttons have an `aria-label`.
6. **Motion.** Nothing animates except colour transitions and spinners; reduced motion is respected.
7. **Evidence.** Screenshots of changed screens go in the PR description or `plans/reports/` (not committed).
8. **Stop what you started.** Dev servers and engines used for the check are stopped afterwards.
