# Motio UI design rules

The look is "Studio": a dark editing suite. The tokens live in `app/src/index.css`, the shared pieces in
`app/src/components/studio.tsx` and `app/src/components/ui/*`. This file records the rules those files follow, so a
new screen matches without copying a neighbour.

## Brand

Motio, a calm dark workbench for turning news into videos. Amber is the one action colour, cyan is for selection and
focus, mint / coral are status only. The wordmark is the Motio logo (waveform bars) with "Motio" in mono.

## Type

- Fonts: IBM Plex Sans for text, IBM Plex Mono for numbers, ids, timecode and captions. Both are bundled (the app
  works offline). Chinese text uses the system font.
- Scale: body 13 / 20 px, `text-xs` 12 px, `text-sm` 14 px, page title `text-xl`, big numbers `text-2xl`.
- **Nothing is smaller than 12 px.** The only 11 px text is the count badge on the left rail (a 16 px circle). Do not
  add `text-[10px]` or `text-[11px]`.
- Captions (panel and card titles, table heads, tile labels) are mono, 12 px, uppercase, `tracking-[0.06em]`, in
  `text-muted-foreground`. `Kicker` and `PanelHeader` in `studio.tsx` and `CardTitle` in `ui/card.tsx` already do it.
- Numbers that line up use `tabular-nums`; stat values and scores are mono.

## Surfaces

- Depth comes from the fill ladder (`ground` < `panel` < `strip` < `raised` < `lift` < `pressed`), never shadows.
- A panel or card has a 40 px `strip` header with the caption, then the body. `Card` is the floating version (rounded,
  ring), `Panel` the docked one (full width, bottom border). Use the same caption style in both.
- Corners are 4 px (`--radius`), buttons are 40 px high (`h-10`), segmented controls 44 px.
- Muted text never goes dimmer than `--muted-foreground` (`#9CA3B0`, about 6.9:1 on `panel`).

## Layout

- The window is 1280 x 820 by default and never smaller than 960 x 640 (`tauri.conf.json`). Check every screen at
  1440 x 900, 1280 x 820 and 960 x 640. There is no tablet or phone layout.
- Left rail 80 px, top bar 56 px. Page content: centred column with `max-w-3xl` (settings), `max-w-4xl` (channels, tools,
  stats), `max-w-5xl` (new videos), `max-w-6xl` (remove logo); docked pages (Trending, Projects) use the full width.
- Text that points ("on the left") must hold at every window size; prefer neutral words.

## Motion

- State changes are `transition-colors`, 100 to 300 ms. Spinners are the only looping motion.
- `prefers-reduced-motion: reduce` turns transitions and enter / exit animations off (`index.css`); spinners stay.

## Language

Every UI string goes in both catalogs of `app/src/i18n.ts` (English and Vietnamese); see the repository `CLAUDE.md`.
