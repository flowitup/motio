# Chinese video sites besides Bilibili and Douyin

Owner's ask of 2026-10-17: more source videos from Xiaohongshu, Weibo, Xigua, Kuaishou and Haokan (Baidu). AcFun and Pear Video
were added in a first version by mistake and removed again the same day; Zhihu stays because the owner asked to test it. Research and options:
`motio/plans/research-261017-cn-video-platforms.md` in the project files. What is built is below. Everything here
removes the source's own voice like every other clip, and does nothing to hide where a video came from. Source rights
are no longer declared anywhere (owner, 2026-10-18).

## What works, per site

Checked from a cloud sandbox on 2026-10-16 with real links, through `search.download` (yt-dlp 2026.8.19). A person's own
Mac or PC may fare differently, and the sandbox's proxy resets connections now and then, so a failed try was repeated.

| Site | Pasted link | Followed list | Notes |
|---|---|---|---|
| Xiaohongshu | yt-dlp `XiaoHongShu`, downloaded a public note (960p, no cookies). `xhslink.com` short links are followed once | no | Many notes want a logged-in session: a cookies file or browser (Settings) is used; the error says so |
| Weibo | yt-dlp `Weibo`, downloaded a post | no | `weibo.com/2/detail/<id>` is rewritten to `m.weibo.cn/detail/<id>` (yt-dlp does not match the first); a post with only pictures says "No video formats found" |
| Xigua | A link is first tried on **Douyin** under the same id (`search._xigua_on_douyin`, f2, no cookies): Xigua mirrored many videos there. Otherwise yt-dlp `Ixigua`, which asks for cookies | no | Cookie-free only for videos that are also on Douyin (tested: `7296116808145175092`, 480p, 1136 s; 8 older ids were not). The web page is a bot check, the mobile page is app-only, videodl fails too. Videos not on Douyin need a cookies file or the file added by hand. If the user has set cookies, yt-dlp is tried first. Ids are written `…/<id>/` because yt-dlp drops the last digit of an id with nothing after it |
| Kuaishou | `kuaishou.py` runs the separate **videodl** program (`pipx install videofetch`, or `MOTIO_VIDEODL`) with only its Kuaishou client; no yt-dlp extractor exists | **yes, one list** (Trending → "Kuaishou · Featured", `kuaishou_feed.py`) | Works on some links, not all (Mac, 2026-10-17: 2 of 5; a sandbox run of a 6 s clip also worked). Without videodl, or when it reads nothing: download the video yourself and add the file. videodl is PolyForm Noncommercial: never bundled or imported, only called as a command |
| Haokan | `haokan.py`: the phone page carries the mp4 (`curVideoMeta.clarityUrl`), 360p to 720p+, no cookies | no | Needs the phone User-Agent; the desktop one gets an empty page. The home page lists no feed we could read |
| Zhihu | yt-dlp `Zhihu` got a 403 without cookies | no | Needs cookies. **Not tested with real cookies.** |

## Checked again on a Mac, 2026-10-17 (cookies off)

- Xiaohongshu: two public video notes downloaded without cookies, but only with the link as the site gives it, with
  `?xsec_token=…`. The same note without the token fails with "No video formats found"; Motio now says to paste the full
  link or the share link. (`normalize` keeps the query, so a pasted full link works.)
- Xigua: three links fail with yt-dlp's "Cookies … are needed" and show the cookie hint. The web site now sends visitors
  to "open the app", so cookies may not be enough: still unknown. A headless Chromium with no login gets a guest session
  but the mobile page carries no video data either. The Douyin route above is the cookie-free way.
- Zhihu: from the Mac two `zvideo` links answered 403 and showed the cookie hint; from the cloud sandbox the same day a
  `zvideo` downloaded with no cookies (476p, 93 s), so it depends on the network or the day. Browsing Zhihu without a login hits a verification page.
- Weibo (Mac, through the engine API): `weibo.com/2/detail/<id>` video posts download; a post with only pictures used to be
  saved as a .jpg "video" (now: "This post has no video, only pictures"), and two posts answered "No video formats
  found" (now a hint: pictures only, or a login is wanted).
- Haokan: two fresh videos downloaded; an old id from a search had been removed and gave "no such video".
- The cookies-on run is still to do: the browser cookie stores could not be read from the Remote Control session.

## Trending feeds (2026-10-18)

Owner's question: why does Trending show only Bilibili? Only Bilibili and Kuaishou have a list that a plain visitor can read:
- **Kuaishou**: the Featured page (`kuaishou.com/brilliant`) asks one GraphQL query (`brilliantTypeData`, channel `00`) that
  answers with no cookie: ~20 videos per answer with the mp4 address. It is a random draw, not a ranking, and there is no
  category. Its search (`visionSearchPhoto`) and detail (`visionVideoDetail`) answer `result: 2` (risk control) without a `did`
  cookie, so they are not used. Tested from a cloud sandbox: feed read and one video downloaded and probed.
- Douyin (needs f2's signed `tab/feed`, only a recommendation feed; not reachable from the sandbox, untested), Weibo (hot
  search answers 403 without a visitor cookie), Xiaohongshu (feed needs a signed header), Xigua (unreachable), Zhihu (403): no
  public list could be read, so these stay paste-a-link.

## Where it lives

- `motio/platforms.py`: hosts, `identify`, `normalize` (link shapes), `expand` (short links), `hint`.
- `motio/haokan.py`: Haokan download (public https only, same guard as Douyin's CDN fetch).
- `motio/kuaishou.py`: Kuaishou through the `videodl` command (`-a KuaishouVideoClient` only, never its generic parsers,
  which send the link to third-party watermark-removal sites); the saved file is moved to `Kuaishou_<id>.mp4`.
- `search.download`: `expand` and `normalize` first, then Haokan (own downloader), Kuaishou (clear error), then yt-dlp;
  a login/403 error from a site that may want cookies becomes `platforms.hint`.
- Tests: `tests/test_platforms.py`, `test_haokan.py`, `test_kuaishou.py`, the last block of `test_search.py`. They use
  mocked transports; the real sites were checked by hand (above), not in CI.

## Adding a site

A new site with a yt-dlp extractor: add a `Platform` in `platforms.py`, its extractor key in `EXTRACTORS`, and a test in
`test_platforms.py`.

## Still open

- Xigua with real browser cookies (for videos not on Douyin), Zhihu with cookies, and Xiaohongshu notes that need a login: try them on the Mac.
- A Xiaohongshu / Weibo / Haokan feed (category or account page): none could be read without a login.
- A Douyin feed through f2's `tab/feed` (home recommendation, signed by f2): worth a try on the owner's Mac, not testable from the cloud.
- Kuaishou: videodl reads some links only; share links (`v.kuaishou.com`, `/f/…`) failed in the Mac test. A logged-in crawler such as MediaCrawler would be a separate decision.
