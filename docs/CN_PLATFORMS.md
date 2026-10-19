# Chinese video sites besides Bilibili and Douyin

Owner's ask of 2026-10-17: more source videos from Xiaohongshu, Weibo, Xigua, Kuaishou and Haokan (Baidu). AcFun and Pear Video
were added in a first version, removed on 2026-10-17 and put back on the owner's word of 2026-10-18 (see "Trending feeds");
Zhihu stays because the owner asked to test it. Research and options:
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

Owner's question: why does Trending show only Bilibili? Only Bilibili, Kuaishou, Douyin, Weibo, AcFun and Pear Video have a list that a plain visitor can read:
- **Kuaishou**: the Featured page (`kuaishou.com/brilliant`) asks one GraphQL query (`brilliantTypeData`, channel `00`) that
  answers with no cookie: ~20 videos per answer with the mp4 address. It is a random draw, not a ranking, and there is no
  category. Its search (`visionSearchPhoto`) and detail (`visionVideoDetail`) answer `result: 2` (risk control) without a `did`
  cookie, so they are not used. Tested from a cloud sandbox: feed read and one video downloaded and probed.
- **Douyin**: the home recommendation feed through f2 (`douyin_feed.py`, Trending → "Douyin · Home feed"): fresh draw, no category. The cloud sandbox cannot reach Douyin's API, so it was tried on the owner's Mac (result below).
- **AcFun** (`feeds.py`, Trending → "AcFun · …"): the daily ranking `acfun.cn/rest/pc-direct/rank/channel?channelId=<id>&rankPeriod=DAY`
  answers JSON with no login (up to 100 videos with length, views, likes, upload time); `channelId` empty = all sections,
  eight sections are offered. Read from a cloud sandbox on 2026-10-16; on 2026-10-18 `acfun.cn` did not answer at all from the
  sandbox (timeouts on the home page too), so today's run of this source is only covered by mocked tests.
- **Pear Video** (`feeds.py`, Trending → "Pear Video · Today"): the home page lists the day's clips as `video_<id>` links
  with a title (no length or view count, so a row can be a few seconds long). Checked 2026-10-18 from the sandbox: 15 clips
  read, one downloaded through `search.download` (yt-dlp `PearVideo`, 406x720 h264 + aac, 9 s).
- **Weibo** (`weibo_feed.py`, Trending → "Weibo · Hot videos"): the hot timeline (`/ajax/feed/hottimeline?group_id=102803`)
  answers a visitor once the browser has asked Weibo's own guest endpoint (`passport.weibo.com/visitor/genvisitor2`, one POST,
  `SUB` / `SUBP` cookies); without that cookie it is a 403, which is why the first try failed. About half of the posts are videos,
  each with its mp4 address (an http address on `*.weibocdn.com`; the CDN resets https), kept in `data/cache/weibo_media.json` so
  `search.download` can fetch the file without yt-dlp (which wants a login for Weibo). Fresh draw, no category. Tested from a cloud
  sandbox (feed read, one video downloaded and probed: 852x480 h264 + aac) and from the owner's Mac (guest session + timeline
  in Chrome and in Python). The hot-search words (`hotSearch`) are not used: they are topics, not videos.
- Xiaohongshu: its feed is only readable in a logged-in browser (checked in the owner's Chrome: `/explore` lists ~30 cards, ~60 %
  video, with title and likes; every note link carries a per-session `xsec_token`), and its API needs a signed header. Motio does
  not copy that signing, so it stays paste-a-link. Xigua (unreachable) and Zhihu (hot list readable, but only text questions)
  also stay paste-a-link.

## Accounts and the Scan screen (2026-10-18)

Owner's ask: follow a channel on Kuaishou, Douyin and Weibo, and a scanner (platform, link / id / hashtag / keyword, results table).
- **Weibo**: `weibo.com/ajax/profile/getWaterFallContent?uid=<id>&cursor=` answers the same guest session as the hot feed (the
  profile's `mymblog` list is a 403 for a guest). Views = `media_info.online_users_number`. Tested from a cloud sandbox.
- **Douyin**: f2's `fetch_user_post` (signed by f2, `sec_user_id`), same anonymous session as a download. Not tested from the
  cloud sandbox (Douyin's API is out of its reach) nor yet on the Mac.
- **Kuaishou**: `visionProfilePhotoList` with a guest `did` cookie answers `result: 400002` and a slider captcha (checked
  2026-10-18), so Motio reads it only with the owner's own cookies (cookie file or browser) and reports a captcha as an error. Not
  tried with real cookies yet. Kuaishou's search stays unread (it wants a `did`-bound session too).
- Hashtag / keyword scans: YouTube (`ytsearch`, `/hashtag/`) and Bilibili (tag search, up to 20). None for the other three.
- Xiaohongshu, Haokan, Xigua: no account page that a visitor can read (see above), so no account follow.

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
- A Xiaohongshu / Haokan feed (category or account page): none could be read without a login. Weibo has the hot-video feed only (no category, no account page).
- Kuaishou: videodl reads some links only; share links (`v.kuaishou.com`, `/f/…`) failed in the Mac test. A logged-in crawler such as MediaCrawler would be a separate decision.

### Keyword and hashtag scan on Kuaishou (2026-10-19, not tried on the real site)

The Scan screen's keyword / hashtag mode works on Kuaishou through its own search page (`visionSearchPhoto`, the same
GraphQL call the page makes), read with the owner's cookies like an account (`accounts.search_kuaishou`). It was built
from the page's public request and tested only against a mock. Douyin has no keyword scan (f2 has no search method; its
search is signed, and Motio does not write signing code). Weibo's search wants a login and was not reachable as a guest.
