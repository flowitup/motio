# Video templates

A template keeps **how a video looks**, apart from what it says. It is plain data (`motio/looks.py`, the "look"):
caption font, size, colours, outline, box, the word being spoken (colour, highlight box, grow, glow), where the captions
sit; the title band (colours, position, alignment, capitals, key words in an accent colour); the frame behind the source
picture (blur and darkness, or a flat colour); the camera move of an AI video's pictures. Optionally it also keeps a
voice, a length and the source sound level.

- The default look is exactly what Motio drew before templates existed: a project with no template renders byte for
  byte as it always did (a test keeps the md5 of the old output).
- A video keeps a **snapshot** of its look in `meta.look` (and the template's name in `meta.template`): editing or
  deleting a template never changes a video already made. Another template can be applied from the project page; the
  video is rendered again with the voice it already has (nothing is recorded or paid again).
- Where a template is picked: New video (all modes), Feed / Trending and Clip Studio, a channel's **Default template**,
  the project page. Where it is made: Tools → Templates (create, edit with a live preview drawn by the real renderer,
  duplicate, delete, copy / import JSON) and **Save as template** on a finished video.
- Built-in templates are in code (`motio/video_templates.py`, key `b:<slug>`); the owner's are in SQLite (`template`
  table, key `u:<id>`). The preview pictures are cached under `data/cache/templates/`.
- A clip (Clip mode) and a dub use the template's title band and captions; a clip has no French voice, so its voice
  and length are not used.
- Not in the engine, so not in a template: background music and transitions between pieces.

## Sources of the starter set

Only **ideas** were taken from other projects (a caption layout, a colour mood). No code, preset file or picture of
theirs is copied, and nothing is downloaded from them at run time.

| Template | Idea from |
|---|---|
| Classic news | Motio's own look before templates |
| Bold impact, Gaming pop, Tall caps | public caption guides (big outlined capitals, the spoken word in a bright colour) |
| Orange pill, Clean box, Comic hype | [pycaps](https://github.com/francozanardi/pycaps) (MIT): word focus, minimalist, hype presets |
| Cinematic gold, Neon glow, News desk, Highlighter, Documentary | Captioneer presets (MIT): cinematic-gold, glow, news-ticker, highlighter, documentary |
| Series card | the fixed card layout of a public Vietnamese TikTok series (@tuantudo86): heavy white capitals in the upper third with the spoken word in yellow and a thick black outline, a dark green title card in the lower part with key words in yellow; layout idea only (looked at on the profile and two videos, 23/11) |

Add a new one only when its licence is MIT, Apache-2.0, CC0 or similar, with its credit here, or take just the idea.

## Fonts

Bundled in `motio/assets/fonts/` (the engine installers carry them: `tools/build_engine.py --add-data`). All are
SIL Open Font License 1.1; the licence text of each sits next to the file (`OFL-*.txt`). All have the French accents.

| Font | Copyright holder |
|---|---|
| Poppins Bold / ExtraBold | The Poppins Project Authors |
| Anton | The Anton Project Authors |
| Bebas Neue | Dharma Type |
| Archivo Black | The Archivo Black Project Authors |
| Bangers | The Bangers Project Authors |
| Lilita One | Juan Montoreano |
| DM Serif Display | Adobe and Google LLC (as its licence file says) |

Chinese, Japanese and Korean captions always use the system CJK font, whatever the template says.

## API

`GET/POST /api/templates`, `PUT/DELETE /api/templates/{key}` (own ones), `GET /api/templates/{key}/export`,
`POST /api/templates/import`, `POST /api/templates/preview` (a look → picture),
`PUT /api/projects/{id}/template` (`{key}` or `null`), `POST /api/projects/{id}/template/save`. Every create call
(`/api/ai`, `/api/dubs`, `/api/clipper/*`, produce, topic) takes `template` (`""` = the channel's default, `"none"` = classic).
