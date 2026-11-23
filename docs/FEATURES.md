# Features

What each part of Motio does. Setup and settings are in the [README](../README.md).

Every video lasts 62–90 s (the 90 s cap is what Facebook Reels takes through its API). Exceptions: a dub with
*Whole video*, an AI video with a chosen length, and a clip (15–90 s). A finished video longer than 90 s is never
sent to Postiz on its own.

## Finding videos

- **Trending**: videos by category or tag from Bilibili (16 categories, popular, weekly, free tags), plus fresh
  draws from Kuaishou, Douyin (home feed, Featured, hot board) and Weibo, and AcFun / Pear Video lists. Original
  uploads only; no login. News from NewsNow is off unless `NEWS_TOPICS` is on.
- **Followed**: follow YouTube channels and playlists, Bilibili spaces, saved searches, and accounts on Kuaishou,
  Douyin and Weibo. Motio checks them every `REFRESH_EVERY_MIN` minutes or on *Check now*. A new source shows its
  latest 10 videos, then only unseen ones. Claude gives each a French title and a score; *Make video* starts an
  explainer. Bilibili spaces often need the browser-cookie setting.
- **Scan**: one platform, by account, hashtag or keyword, 1–10 lines, with an optional title filter. Nothing is
  saved or made. Douyin keyword search uses your own douyin.com cookies, or reads the public search site in a
  headless Chrome (needs Chrome, Chromium or Edge installed).
- **Pasted links**: Douyin, Bilibili, YouTube, Facebook, Xiaohongshu, Weibo, Xigua, Kuaishou, Haokan and more.
  If a link cannot be fetched, download the video yourself and use **Add a video file** (MP4, MOV, M4V, MKV, WebM,
  AVI, TS or FLV, up to 2 GB), available next to every place that takes links.
- **Douyin** links need no login: any form works, including the sentence the Douyin app copies on Share. Motio uses
  [f2](https://github.com/Johnserf-Seed/f2) first, then yt-dlp (which needs fresh browser cookies). Details:
  [DOUYIN_F2.md](DOUYIN_F2.md), [CN_PLATFORMS.md](CN_PLATFORMS.md).

## Video modes

- **Explainer** (*New video*, 70 / 80 / 90 s): any topic in any language and/or video links. The source's own voice
  is muted by default; the source sound can be set to a level on the project page.
- **French dub**: one video (Douyin, Bilibili, YouTube…) in French, keeping its pictures, music and sounds.
  - Motio transcribes it and takes one 62–90 s part: the whole video if short, else Claude picks a part that starts
    and ends on a sentence, or you type from–to. *Whole video* dubs everything, any length.
  - Claude translates each line to fit the original's timing: *tu* or *vous*, the channel's glossary, and each
    line's speaker and gender.
  - ElevenLabs voices every line where the original started, one voice per speaker (the channel voice, then up to 3
    extra voices of the profile). Change voices on the project page: **Voices** → **Save and re-voice**.
  - An AI model (UVR MDX-Net, run on the CPU; downloaded once, 67 MB) separates voice from music; the music and
    sounds stay under the French voice.
  - Old burned-in subtitles are blurred: only the subtitle band, found automatically or drawn by you, never a logo.
  - **Play both** compares the original part with the dub; each French line is editable.
- **AI video**: no source footage. Claude writes scenes (spoken line, English picture prompt, camera move), an image
  model draws one 9:16 picture per scene, and the usual voice and render steps add Ken Burns moves and captions.
  - Pictures come from Settings → AI pictures: **fal** (default, Seedream 5 Pro, about $0.07 per picture),
    **Modal** (your own app; dev engine or server only) or **Placeholder** (free, to try the flow).
  - No provider is cleared for monetized channels, so these videos always stop at *Awaiting video approval*. The
    script gate stops before any picture is paid for.
  - Edit a scene's prompt or move and only that picture is made again; **New picture** redraws it.
  - Length: 70 / 80 / 90 s, or any length from 30 s to 30 min.
  - **Review the pictures first** pauses after the pictures so you can approve or redo each shot, then continue.
  - **AI clips**: some scenes become 5 s image-to-video clips (fal H3 Max, about $0.40 each, or HeyGen Video 1).
    Set the count per channel or per video; the first scene is always included. Clips are cached, count in Stats and
    stop at the monthly budget. HeyGen clips also force the video gate.
  - **Series and cast** (Channels → *Series*, *Cast*): `Name: look` lines keep characters consistent (same-face
    portraits are made from the look); each episode knows the recaps of earlier ones.
  - Never makes a picture of a real, recognizable person. The post adds "Images générées par IA." (and "Images et
    vidéos générées par IA." with clips).
- **Clip**: a long video (VOD, trailer, reaction) becomes vertical 9:16 clips that keep the original sound; no
  voice-over.
  - *Claude picks*: Whisper and Claude choose the moments and make one project each. *I'll pick* (Clip Studio): drag
    in/out marks, the 9:16 crop frame over time, and edit the hook.
  - Captions come from the speech (translated to French if needed). *Follow the face* centres the frame on the
    face (OpenCV YuNet; it never identifies anyone) and stays editable.

## Channels

One profile per channel you post to: red badge ("ACTU CHINE", "INSOLITE", or none), script style notes, voice,
default length, hashtags that go first, a glossary and extra dub voices, AI clips, and:

- **Approval gates**: with the script gate on, a project stops at *Awaiting script approval* until you edit and
  press **Approve and continue**. With the video gate on it stops at *Awaiting video approval* until **Approve and
  send**. The **Review** screen lists everything waiting.
- **Postiz auto-send**: after approval, as a draft, at the next free posting time, or right away (once per
  project). Tick **16:9** on a Postiz channel to also render and send a 16:9 copy with the same cut.
- **Make videos automatically**: after each refresh, make videos for new trends at or above a minimum score, up to
  a per-day cap. They stop at the gates and are marked "Made automatically".

Without a channel, a video runs straight through (news videos carry the "ACTU CHINE" badge, explainers none).

## Quality check

After every render (FFmpeg and ffprobe, nothing leaves the machine) Motio checks: length 62–90 s, 1080×1920 H.264,
sound at about -14 LUFS without clipping, no silence over 1.5 s, and a non-black first picture. A **problem**
holds the video at the gate (you can still approve it); a **warning** is only shown. It also warns about a source,
title or script used in the last 30 days.

## Project page

- Edit the script (title, each voice-over line, description, hashtags), then re-voice and re-render; rerun from any
  step; delete the project.
- **Hide text or watermark**: per source, drag **Blur** boxes (optionally **Cover with logo** from Settings →
  Logos) or an **Area to keep (zoom)**, up to 6 boxes. Applied at render; nothing is detected for you.
- **Mirror / colour filter** per source (one setting for a whole AI video), and **Original sound** level.

## Templates

A template keeps how a video looks: caption font, colours, outline, box, the spoken word, where the captions sit, the
title band, the background and the camera moves, and optionally a voice, a length and the source sound level. 13
starter templates are built in; make your own in **Tools → Templates** (live preview), import / export JSON, or
**Save as template** on a finished video. Pick one on a new video, or set a channel's **Default template**; change a
finished video's template from its page (rendered again with the same voice). Details and sources: `docs/TEMPLATES.md`.

## Tools

One-off jobs that need no project; each input is an uploaded file or the result of another job, so they chain:
**Download video** (480 / 720 / 1080 / 1440p; the default is Settings → General → Source video quality, 1080), **Transcribe** (Whisper → `.srt` + text), **Translate subtitles** (Claude →
French / English / Vietnamese), **Read text aloud** (ElevenLabs, up to 5,000 characters) and **Burn subtitles**.

**Remove logo** cleans a static logo from a video you pick (a project source or an uploaded file): draw a box or
use **Auto-detect**. The LaMa model (92 MB, downloaded once, CPU) redraws what was behind it. A project source is
cleaned only where the final video uses it; the original is kept. It never runs by itself in the pipelines.

## Stats, alerts, storage

- **Stats**: ElevenLabs characters, Claude calls, AI pictures and AI clips, with estimated cost per project,
  channel and tool job. A monthly budget (Settings) warns at 80% and pauses automatic making at 100%; videos you
  start yourself still run.
- **Slack alerts**: one message when a project waits for approval, is done (and whether Postiz took it) or fails.
- **Google Drive**: finished project files and idle sources move to Drive and leave this machine. See
  [GOOGLE_DRIVE.md](GOOGLE_DRIVE.md).

## Servers

The engine can run 24/7 on a Hetzner server with Postiz ([DEPLOY.md](DEPLOY.md)) or on a Windows PC at home over
Tailscale ([WINDOWS_SERVER.md](WINDOWS_SERVER.md)). The app then uses it through Settings → *Remote engine*.
