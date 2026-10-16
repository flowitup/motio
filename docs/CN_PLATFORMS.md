# Chinese video sites besides Bilibili and Douyin

Owner's ask of 2026-10-17: more source videos from the big Chinese platforms. Research and options:
`motio/plans/research-261017-cn-video-platforms.md` in the project files. What is built is below. Everything here
treats rights as `unknown` (a person approves a video before it is posted), removes the source's own voice like every
other clip, and does nothing to hide where a video came from.

## What works, per site

Checked from a cloud sandbox on 2026-10-16 with real links, through `search.download` (yt-dlp 2026.8.19). A person's own
Mac or PC may fare differently, and the sandbox's proxy resets connections now and then, so a failed try was repeated.

| Site | Pasted link | Followed list | Notes |
|---|---|---|---|
| Xiaohongshu | yt-dlp `XiaoHongShu`, downloaded a public note (960p, no cookies). `xhslink.com` short links are followed once | no | Many notes want a logged-in session: a cookies file or browser (Settings) is used; the error says so |
| Weibo | yt-dlp `Weibo`, downloaded a post | no | `weibo.com/2/detail/<id>` is rewritten to `m.weibo.cn/detail/<id>` (yt-dlp does not match the first); a post with only pictures says "No video formats found" |
| Xigua | yt-dlp `Ixigua` asks for cookies ("not necessarily logged in"); a bare `ttwid` guest cookie was **not** enough | no | Needs a cookies file or browser. **Not tested with real cookies.** Ids are written `…/<id>/` because yt-dlp drops the last digit of an id with nothing after it |
| Kuaishou | not downloadable: no yt-dlp extractor, no f2 support, and the web answers a risk-control page to a script | no | Recognised so the error is clear: download the video yourself and add the file |
| Haokan | `haokan.py`: the phone page carries the mp4 (`curVideoMeta.clarityUrl`), 360p to 720p+, no cookies | no | Needs the phone User-Agent; the desktop one gets an empty page. The home page lists no feed we could read |
| Pear Video | yt-dlp `PearVideo`, downloaded a clip | `pearvideo:home` (the home page, no length or views) | Pear Video sells its clips to newsrooms: expect claims, approve by hand |
| AcFun | yt-dlp `AcFunVideo`, downloaded a video | `acfun:rank` and `acfun:channel:<id>` (daily ranking, JSON, no login) | Sections with only articles ("Life", 63) are left out; AcFun has no tech section |
| Zhihu | yt-dlp `Zhihu` got a 403 without cookies | no | Needs cookies. **Not tested with real cookies.** |

## Where it lives

- `motio/platforms.py`: hosts, `identify`, `normalize` (link shapes), `expand` (short links), `hint`.
- `motio/haokan.py`: Haokan download (public https only, same guard as Douyin's CDN fetch).
- `motio/feeds.py`: AcFun and Pear Video lists as followed sources (`kind = trending`, site `acfun` / `pearvideo`),
  `TARGETS` offered by `GET /api/categories`; `watch.classify` / `watch.check` route them; the Trending screen's
  "Add a category" lists them with Bilibili's.
- `search.download`: `expand` and `normalize` first, then Haokan (own downloader), Kuaishou (clear error), then yt-dlp;
  a login/403 error from a site that may want cookies becomes `platforms.hint`.
- Tests: `tests/test_platforms.py`, `test_haokan.py`, `test_feeds.py`, the last block of `test_search.py`. They use
  mocked transports; the real sites were checked by hand (above), not in CI.

## Adding a site or a section

An AcFun section is one line in `feeds.ACFUN_CHANNELS` (the id is the `channelId` of the live ranking) plus its two names in
`app/src/i18n.ts` (`feedsEn` / `feedsVi`). A new site with a yt-dlp extractor: add a `Platform` in `platforms.py`, its
extractor key in `EXTRACTORS`, and a test in `test_platforms.py`.

## Still open

- Xigua and Zhihu with real browser cookies, and Xiaohongshu notes that need a login: try them on the Mac.
- A Xiaohongshu / Weibo / Haokan feed (category or account page): none could be read without a login.
- Kuaishou: only a hand-added file for now. A logged-in crawler such as MediaCrawler would be a separate decision.
