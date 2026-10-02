# Douyin downloads through f2

Public Douyin videos download without a login or cookies. `motio/douyin.py` calls the [f2](https://github.com/Johnserf-Seed/f2)
package (Apache-2.0, `f2==0.0.1.7`), which does Douyin's request signing; Motio never copies that code. `search.download`
tries it first for every Douyin link and falls back to yt-dlp when f2 cannot.

## How a download goes

1. `search.clean_links` picks the link out of whatever was pasted, including the whole sentence the Douyin app copies on
   Share ("7.43 复制打开抖音… https://v.douyin.com/xxx/ 复制此链接…").
2. `douyin.find_id` finds the post id: in the link (`/video|note|slides/<id>`, `?modal_id=`, `?vid=`) or, for a
   `v.douyin.com` short link, by following the redirect hop by hop inside Douyin's own hosts (`_resolve_id`). It is done
   once, in `search.download`, which hands the id to `douyin.download` and keeps it for the yt-dlp fallback.
3. `douyin._ask` asks Douyin for the post through f2 (an anonymous `ttwid`, a fresh `msToken`, a signed request). It asks up
   to three times: a passing 403, or a list of sizes thinner than usual (Douyin sometimes leaves out the 720 H.264 rung of a
   video whose source is bigger), is worth another try.
4. `douyin.pick_stream` takes the largest H.264 stream up to 1080 p on the short side (`DEFAULT_HEIGHT`; Tools → Download uses
   the quality picked there, 720 p by default). H.265 is never taken while an H.264 stream exists: the app's players (Windows especially) may not open it.
5. `douyin._save` streams it to `cache/sources/Douyin_<id>.mp4` through `.part`. The link must be https to a public address,
   redirects included (f2 does not check TLS certificates, so its reply could be forged). An empty or non-video reply moves
   on to the next CDN link.
6. The result has the same keys as the yt-dlp path (`path, url, id, title, platform, uploader, uploader_url, upload_date,
   duration, license, width, height`), so nothing downstream changes.

Fallback chain: f2 → yt-dlp on the plain `douyin.com/video/<id>` link (needs fresh browser cookies) → **Add a video file**.
A removed, private or photo-only post is final: Douyin gives the reason, so nothing else is tried. An answer with neither a
post nor a reason is not a verdict and falls back. The plain link is built from the id `find_id` found, so a `v.douyin.com`
short link, which is what a Share sentence holds, reaches yt-dlp as `douyin.com/video/<id>` too (yt-dlp has no extractor for
the short form). A link with no id (a user page, a live room, a short link that leads elsewhere) goes to yt-dlp unchanged
while Douyin answers.

When f2 could not connect to Douyin at all, `douyin.Unreachable` is raised: every try of `_ask` failed on a network error (no
connection, DNS, a timeout, a proxy that refuses; one answer from Douyin, even a strange one, means it was reachable), or
every CDN link of `_save` did (a link that answered with an error, an empty file or a refused address does not count).
`search.download` still tries yt-dlp, because a DNS filter or firewall can block f2's token server (`mssdk.bytedance.com`)
while `douyin.com` answers; if yt-dlp then fails with its "fresh cookies" message, which it gives even with no network, the
error is "Could not connect to Douyin. Check your internet connection (or VPN, proxy, DNS filter), then try again" instead.
Any other yt-dlp error (a 403, a removed video) is Douyin's real answer and is shown as it is. A link that has no id and
cannot be fetched for lack of a connection (a short link, a user page) stops there with the same message: yt-dlp could do
nothing with it.

## What was tested (2026-10-02, the owner's Mac, home network, guest only)

| Check | Result |
|---|---|
| Corpus | 680 real posts from 49 public accounts: 580 videos (405 portrait, 176 landscape, sources up to 4K, 4 s to 21 min), 97 photo posts |
| Download matrix, 38 stratified posts through `search.download` | 32/32 videos downloaded (4 s to 17 min); 25 at 1080 p, 7 at 720 p (their H.264 stops there); all H.264 + AAC; length within 0.1 s of what Douyin says; 0.3 to 164 MB (cap 600 MB); 3 s median under 30 s of video, 20 s for 2 to 10 min, 69 s for 17 min |
| Photo posts | 6/6 refused with "photos, not a video" |
| yt-dlp without cookies, same videos | 0/11 (this is what the integration replaces) |
| Downstream | 32/32 decode with no error; audio in all; Whisper reads the Chinese speech; scene cuts and `qa.probe` work; no watermark or end card in the frames looked at |
| Link forms | 29 cases: `/video/`, no `www`, `http`, trailing slash, tracking query, fragment, upper-case host, `/note/` on a video id, `modal_id` on jingxuan / user / discover / search pages, `iesdouyin` share (with and without a slash or query), `m.douyin.com`, `?vid=`, `v.douyin.com` short links to a photo post, a private video and a removed video, the pasted share sentence: all right. `/slides/` of a photo post says "photos". User page, live room, hashtag and collection links are not videos and fall to yt-dlp's "Unsupported URL" |
| Repeats | 70 single requests back to back or after a pause: 69 right, one passing 403 (now retried). A video that used to come out at 576 p: 12/12 at 720 p (3 extra requests); 5 videos: the size chosen never changed over 12 runs |
| Several threads | 4 threads x 16 videos: 16/16, no `./logs` folder made |
| Cold start | importing f2 about 1.0 s (it asks Douyin for an `msToken`); first download 2.2 to 3.9 s |
| Engine API | Tools → Download: progress, cancel mid-download (status `cancelled`, no fallback), removed video |
| PyInstaller | a frozen build with the engine's flags downloads from an empty working directory. The release workflow's macOS and Windows builds of this change passed (engine freeze with the f2 bundle check, installers); running the built app against Douyin was not done |
| Frozen engine on Linux (Python 3.12 and 3.13), no real Douyin | starts without contacting Douyin; a full link and a Share sentence download through f2 against a local stand-in; a removed video gives its message; no `./logs` folder; with the network cut it fails in 1 to 3 s |
| Offline and stalled network (after v0.7.13, real f2 and yt-dlp, no real Douyin) | a proxy that refuses every connection: full link, then short link, then the full link again all say "Could not connect to Douyin" within 3 s (the short link in 0.5 s, and it never reaches yt-dlp); a token-server address whose accept queue is full (SYNs dropped): the first `_f2()` gives up at 15.0 s, the next two at 0.0 s |

Not tested: Windows, the Hetzner server (a datacenter address may be refused: an f2 user reported a server blocked while a
local machine worked), long-term stability, keyword search, an author's video list.

## Risks

- **f2 is a fragile upstream.** One maintainer, bursty (no commit for 222 days, then 271 in September 2026). The last PyPI
  release is 2024-12-31; every fix since then sits on the unreleased `v0.0.1.8-pw3` branch. On the path Motio uses, Douyin
  broke the access four times in two years (June 2024, February 2025, March 2025, August to September 2026): fixed on git in
  10 days (median), on PyPI once of four. Douyin also began gating `aweme/detail` in mid-September 2026; the pinned build
  works today from a home connection, which is what the tests above show. Expect it to be down sometimes: that is why the
  fallback chain and **Add a video file** stay.
- **A stalled network.** When the packets to Douyin's token server are silently dropped (the connection never opens),
  importing f2 would retry its `msToken` request for about 135 s (twelve attempts inside f2's own `model.py`). The import
  runs in a background thread and `douyin._f2` waits for it at most 15 s (`_F2_LOAD_WAIT`): measured with the real f2 and a
  port whose accept queue was full, the first call gives up after 15.0 s (it was about 135 s) and the next ones fail at once.
  The load keeps going: if it ends well the next download uses f2 at once, if it fails the real error is kept (a load that
  stops without a result, for instance f2 calling `sys.exit` on a broken config file, is a failure, not a timeout). Only one
  load runs at a time, and a failed or timed-out one is not started again until `_F2_RETRY_AFTER` (two minutes) after it
  failed, so after the connection is back a download within those two minutes still skips f2 (and, with yt-dlp
  failing too, still says it could not connect). A server that accepts the connection and never answers costs about 20 s
  inside f2 and is cut at the same 15 s; a refused connection (a proxy that refuses everything) fails in under 3 s. With no
  route out at all, a short link or a Share sentence shows the connection message at once, but a full link takes about 17 s
  (f2 retries its token request with back-off until the 15 s cap, then yt-dlp fails). yt-dlp can still add up to 30 s
  on top before the error shows, and so can following a short link (30 s); a Cancel is only noticed once the import has been
  given up on or has finished (15 s at most).
- **The error used to blame cookies.** With no connection at all, yt-dlp's Douyin extractor still says fresh cookies are
  needed; see `douyin.Unreachable` above: that case now says "Could not connect to Douyin". If a DNS filter blocks only
  `mssdk.bytedance.com`, f2 cannot start (and if yt-dlp fails too the message says it could not connect) while yt-dlp may
  still work with cookies: unblock that host.
- **TLS.** f2 turns certificate checking off for its own calls (an on-path attacker could forge Douyin's reply). Motio only
  follows https links to public addresses, so a forged reply cannot reach local services; it could still hand over wrong
  metadata or another public file. The CDN download itself checks certificates.
- **Supply chain.** f2 runs inside the engine process, which holds the API keys. The wheel matches the GitHub tag, the pin
  and the hashes in `uv.lock`; PyPI uploads are manual and carry no attestations. Keep the exact pin, no auto-updates, and
  review the reachable files on every bump. Motio does not install `browser-cookie3` (LGPL, reads browser cookie stores) or
  `pyexecjs` (JavaScript for livestreams): `motio/douyin.py` hands f2 empty stand-in modules.
- **Terms.** Douyin's terms do not allow automated access, and f2 exists to get past its request signing. This is a personal
  tool like yt-dlp; the rights rules in CLAUDE.md (rights gate for dubs, no Content ID evasion) are unchanged.

## Updating f2

1. Read f2's releases / `CHANGELOG.md` and the issues labelled `douyin`.
2. Change the version in `pyproject.toml` (both `dependencies` and `[[tool.uv.dependency-metadata]]`; review its
   `requires-dist` against the new f2's imports), then `uv lock`. Check `git diff uv.lock` for packages that appear.
3. `uv run pytest`, then a live check with a throwaway `MOTIO_DATA`: a full `/video/` link, a `v.douyin.com` link, a photo
   post and a removed post (`uv run python -c "from motio import search; print(search.download('<link>', Path('/tmp/x')))"`).
4. If the new f2 only exists on a git branch, pin a commit SHA and keep its wheel; do not follow a branch.
5. Rebuild the engine (`tools/build_engine.py` checks that f2's yaml files are bundled).

## Alternatives looked at

- **Evil0ctal/Douyin_TikTok_Download_API (DTK) v5** (Apache-2.0, 20k stars; rewrite released 2026-09-10, v5.1.3 on
  2026-10-02): read in depth, never run. It is a Docker service, not a library: API, worker, PostgreSQL + TimescaleDB, Redis,
  a Go downloader and a browser container that mints guest identities with a proprietary stealth Chromium (CloakBrowser).
  `POST /api/v1/parse` with `include_raw` returns the same `aweme_detail` plus direct CDN URLs, so a `DTK_URL` backend in
  `douyin.py` would be a small adapter (size M). Not the default because: it does not embed (desktops would need Docker
  Desktop, about 6 GB of images and 2.6 to 4 GB of RAM; the 8 GB Hetzner box already runs Postiz, Temporal, Elasticsearch
  and Whisper); "maintained" rests on 22 days and one person (v4 was silent for 11 months) and nothing in its CI touches the
  live gateway; CloakBrowser's licence forbids redistribution and TimescaleDB's TSL and Redis 8 cannot ship in the
  installers; the browser container needs `SYS_ADMIN` and mints identities in the background all day, which is more ToS
  exposure than f2's one signed request. If f2 breaks for good, or the Hetzner address is refused, add it as an optional
  second tier on the server only (after f2, before yt-dlp), pinned to a version tag.
- jiji262/douyin-downloader (needs a logged-in cookie; its README says plain requests are blocked), DTK v4 (cookie pasted by
  hand), JoeanAmier/TikTokDownloader (GPL-3.0, cookie, signing removed in 2026-08): none works anonymously. yt-dlp: needs
  fresh cookies (0/11 here).

## Not done (options)

A Settings switch to turn f2 off; a "Test Douyin" button that fetches one fixed public video and shows the last result; a
check that a Dub source is at least 38 s before downloading it; following Douyin accounts in "New videos" (f2 can list an
author's posts anonymously); a run from the Hetzner server and the Windows PC.
