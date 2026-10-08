"""Engine messages the app shows (step labels, log lines, errors) in the UI language.

English is the default. The app saves its language as `UI_LANG` (en | vi) in the engine settings, so steps, logs
and errors written from then on follow it; lines already in a project's log stay as they were written.
Write every message in English with `{named}` fields, wrap it in `tr()` (counts in `tr_n()`), and add its
Vietnamese to `VI`: `tests/test_i18n.py` fails when one is missing. Video content, prompts and posts stay French.
"""
from . import settings

LANGS = ("en", "vi")


def lang() -> str:
    """UI_LANG from the settings / env, read at call time. Anything else means English."""
    value = (settings.get("UI_LANG") or "").strip().lower()
    return value if value in LANGS else "en"


def tr(msg: str, **fields) -> str:
    """The message in the UI language, with its {fields} filled in."""
    if lang() == "vi":
        msg = VI.get(msg, msg)
    return msg.format(**fields) if fields else msg


def tr_n(count: int, one: str, many: str | None = None) -> str:
    """A count with its noun: "1 line" / "3 lines" in English; Vietnamese nouns don't change ("3 dòng")."""
    if lang() == "vi":
        return f"{count} {VI.get(one, one)}"
    return f"{count} {one if count == 1 else many or one + 's'}"


VI = {
    # pipeline steps
    "Find sources": "Tìm nguồn",
    "Download": "Tải video",
    "Transcribe": "Bóc lời",
    "Script": "Kịch bản",
    "Voice": "Giọng đọc",
    "Render": "Dựng",
    "Done": "Xong",
    "Send to Postiz": "Gửi Postiz",
    "Awaiting script approval": "Chờ duyệt kịch bản",
    "Awaiting video approval": "Chờ duyệt video",
    "Queued for re-render": "Chờ dựng lại",
    "Queued for voice and render": "Chờ đọc giọng và dựng",
    "Queued to rerun: {step}": "Chờ chạy lại: {step}",
    # counted nouns (tr_n)
    "pasted link": "link dán tay",
    "candidate": "ứng viên",
    "source": "nguồn",
    "segment": "đoạn",
    "scene": "cảnh",
    "word": "từ",
    "line": "dòng",
    "sentence": "câu",
    "clip": "đoạn",
    "source link": "link nguồn",
    "part": "đoạn",
    "box": "khung",
    # pipeline logs
    "Claude is interpreting the topic: {topic}": "Claude diễn giải chủ đề: {topic}",
    "Topic: {title} · {angle}": "Chủ đề: {title} · {angle}",
    "Using only the {links}": "Chỉ dùng {links}",
    "Keywords: {keywords}": "Từ khoá: {keywords}",
    "no search results": "không có kết quả tự tìm",
    "{candidates}, picked {picked}": "{candidates}, chọn {picked}",
    "Downloading {url}": "Tải {url}",
    "Skipped (download error): {error}": "Bỏ qua (lỗi tải): {error}",
    "Downloaded {sources}": "Đã tải {sources}",
    "Whisper + scene cuts: {name}": "Whisper + cắt cảnh: {name}",
    "Transcribed: {done}": "Xong bóc lời: {done}",
    "Claude is writing the French narration": "Claude viết lời bình tiếng Pháp",
    "Script has {words}, too short for a video ≥ {min} s: making it longer":
        "Kịch bản {words}, quá ngắn cho video ≥ {min} s: viết dài thêm",
    "Rerun from step {step}": "Chạy lại từ bước {step}",
    "Queued to rerun from step {step}": "Xếp hàng chạy lại từ {step}",
    "Channel {name}: awaiting your script approval before voice and render":
        "Kênh {name}: chờ bạn duyệt kịch bản rồi mới đọc giọng và dựng",
    "Channel {name}: awaiting your video approval": "Kênh {name}: chờ bạn duyệt video",
    "Channel {name}: awaiting your video approval before sending to Postiz":
        "Kênh {name}: chờ bạn duyệt video rồi gửi sang Postiz",
    "ERROR: {error}": "LỖI: {error}",
    "Added {links}": "Thêm {links}",
    "Generating the French voice": "Tạo giọng đọc tiếng Pháp",
    "Video is {length} s, needs {min}–{max} s: adjusting the script to ~{words} words":
        "Video {length} s, cần {min}–{max} s: chỉnh kịch bản còn ~{words} từ",
    "Re-voiced: {duration} s": "Đọc lại: {duration} s",
    "Video is {length} s, max {max} s: dropping {sentences} near the end and re-voicing":
        "Video {length} s, tối đa {max} s: bỏ {sentences} gần cuối rồi đọc lại",
    "Keeping the previous voice ({voice})": "Giữ giọng đọc cũ ({voice})",
    "Voice is {length} s: extending the ending with source footage to {min} s":
        "Giọng đọc {length} s: kéo dài phần cuối bằng hình nguồn tới {min} s",
    "Video is {length} s, still over {max} s: Facebook Reels (API) will reject it":
        "Video {length} s vẫn quá {max} s: Facebook Reels (API) sẽ không nhận",
    "Source #{n}: the new video also uses parts where the logo was not removed ({spans}). Open Remove logo, "
    "click Remove logo again, then Re-render video":
        "Nguồn #{n}: video mới dùng cả đoạn chưa xoá logo ({spans}). Mở Xoá logo, bấm Xoá logo lần nữa rồi Dựng "
        "lại video",
    "Rendered in {seconds} s · {clips} · {rest}": "Dựng xong trong {seconds} s · {clips} · {rest}",
    "Sending to Postiz ({mode}) for channel {name}": "Gửi sang Postiz ({mode}) cho kênh {name}",
    "Could not send to Postiz: {error}": "Chưa gửi được sang Postiz: {error}",
    " + 16:9 copy": " + bản 16:9",
    "16:9 copy missing: sending the 9:16 video to every channel": "Thiếu bản 16:9: gửi video 9:16 cho mọi kênh",
    "Made automatically: score {score} (channel {name} makes {min}+)":
        "Tự làm: điểm {score} (kênh {name} tự làm từ {min} điểm)",
    "Video approved": "Đã duyệt video",
    "Video approved, not sent to Postiz": "Đã duyệt video, không gửi Postiz",
    "Script approved": "Đã duyệt kịch bản",
    "Pasted source links: {n}": "{n} link nguồn dán tay",
    "Source rights: {rights}": "Quyền nguồn: {rights}",
    "Channel: {name}": "Kênh: {name}",
    "Topic: {topic} · links: {links} · {duration} s": "Chủ đề: {topic} · {links} link · {duration} s",
    "(links only)": "(chỉ link)",
    "Video from {site}": "Video từ {site}",
    "From New videos: {source} · {url}": "Từ Video mới: {source} · {url}",
    "Script edited: {parts}": "Sửa kịch bản: {parts}",
    "Script edited: {parts} · re-render to update the video": "Sửa kịch bản: {parts} · cần dựng lại để video đổi theo",
    "title": "tiêu đề",
    "narration ({lines}, {words})": "lời bình ({lines}, {words})",
    "clips": "đoạn hình",
    "description": "mô tả",
    "hashtags": "hashtag",
    "ERROR: the engine stopped while the project was running. Click Re-render or create it again.":
        "LỖI: engine đã dừng khi dự án đang chạy. Bấm Dựng lại hoặc tạo lại.",
    # pipeline errors
    "Daily limit reached: {n} videos (MAX_VIDEOS_PER_DAY)": "Đã đủ {n} video hôm nay (MAX_VIDEOS_PER_DAY)",
    "No voice: add ELEVENLABS_API_KEY in Settings":
        "Chưa có giọng đọc: nhập ELEVENLABS_API_KEY trong Cài đặt",
    "No source links yet": "Chưa có link nguồn nào",
    "No videos found for this topic": "Không tìm thấy video nào cho chủ đề này",
    "No videos found for this story": "Không tìm thấy video nào cho tin này",
    "Could not download any source video": "Không tải được video nguồn nào",
    "Script too short": "Kịch bản quá ngắn",
    "Source file missing: {url}": "Mất file nguồn {url}",
    "Invalid step: {step}": "Bước không hợp lệ: {step}",
    "Not enough data to rerun from step {step}": "Chưa đủ dữ liệu để chạy lại từ bước {step}",
    "The previous voice is gone or the script has changed: rerun from step Voice":
        "Giọng đọc cũ không còn hoặc kịch bản đã đổi: chạy lại từ bước Giọng đọc",
    "Project is not awaiting video approval": "Dự án không chờ duyệt video",
    # API errors
    "Missing or invalid token": "Sai hoặc thiếu token",
    "Trend not found": "Không có tin này",
    "“Use only these links” needs at least one link": "Chọn “chỉ dùng link” thì cần ít nhất một link",
    "Source not found": "Không có nguồn này",
    "Invalid source rights: {rights}": "Quyền nguồn không hợp lệ: {rights}",
    "Video not found": "Không có video này",
    "Only videos not made yet can be hidden or shown again": "Chỉ ẩn hoặc hiện lại được video chưa làm",
    "Project not found": "Không có dự án này",
    "Project is running": "Dự án đang chạy",
    "Project has no script (script.json) to re-render": "Dự án chưa có kịch bản (script.json) để dựng lại",
    "No links given": "Chưa có link nào",
    "Project is not awaiting approval": "Dự án không chờ duyệt",
    "Channel not found": "Không có kênh này",
    "Postiz is not configured (POSTIZ_URL, POSTIZ_API_KEY)": "Chưa cấu hình Postiz (POSTIZ_URL, POSTIZ_API_KEY)",
    "Postiz error: {error}": "Postiz lỗi: {error}",
    "Project has no finished video yet": "Dự án chưa có video hoàn chỉnh",
    "This project's channel has no Postiz channel to send to": "Kênh của dự án này chưa có kênh Postiz để gửi",
    "Project has no 16:9 copy yet": "Dự án chưa có bản 16:9",
    "ELEVENLABS_API_KEY is not set": "Chưa có ELEVENLABS_API_KEY",
    "ElevenLabs error: {error}": "ElevenLabs lỗi: {error}",
    "File not found": "Không có file",
    # channels
    "The channel needs a name": "Kênh cần có tên",
    "Duration must be one of {choices} seconds": "Độ dài phải là {choices} giây",
    "Send mode must be one of {choices}": "Cách gửi phải là một trong {choices}",
    "Invalid posting time: {time} (format 18:30)": "Giờ đăng không hợp lệ: {time} (dạng 18:30)",
    "Scheduling needs at least one posting time": "Lên lịch cần ít nhất một giờ đăng",
    "No free posting time in the next 60 days": "Hết khung giờ đăng trong 60 ngày tới",
    "Auto-make score and videos per day must be numbers": "Điểm tự làm và số video mỗi ngày phải là số",
    "Auto-make score must be between 1 and 100 (0 = off)": "Điểm tự làm phải từ 1 đến 100 (0 = tắt)",
    "Auto-made videos per day must be between 1 and {n}": "Số video tự làm mỗi ngày phải từ 1 đến {n}",
    # config
    "{name} not found": "Không tìm thấy {name}",
    # edit
    "Project #{id} not found": "Không có dự án #{id}",
    "Project is running: wait until it finishes, then try again": "Dự án đang chạy, chờ xong rồi thử lại",
    "Project has no script yet": "Dự án chưa có kịch bản",
    "script.json is corrupt: {error}": "script.json hỏng: {error}",
    "script.json is corrupt: the lines list is missing": "script.json hỏng: thiếu danh sách dòng",
    "Title can't be empty": "Tiêu đề không được để trống",
    "Title can be at most {n} characters": "Tiêu đề dài tối đa {n} ký tự",
    "Line {line} is longer than {n} characters": "Dòng {line} dài quá {n} ký tự",
    "The script needs at least {n} narration lines": "Kịch bản cần ít nhất {n} dòng lời bình",
    "The script can have at most {n} lines": "Kịch bản tối đa {n} dòng",
    "Description can be at most {n} characters": "Mô tả dài tối đa {n} ký tự",
    "Could not delete the project folder ({error}). Close any open files and try again.":
        "Không xoá được thư mục dự án ({error}). Đóng file đang mở rồi thử lại.",
    "The project was just restarted: wait until it finishes, then try again":
        "Dự án vừa được chạy lại, chờ xong rồi thử lại",
    # inpaint (logo removal AI)
    "Could not download the logo removal AI model ({error}). Check your connection and try again.":
        "Không tải được mô hình AI xoá logo ({error}). Kiểm tra mạng rồi thử lại.",
    "The downloaded AI model is not the version Motio needs (sha256 mismatch). Please report it so Motio can be "
    "updated.": "Mô hình AI tải về không đúng bản Motio cần (sai sha256). Báo lại để cập nhật Motio.",
    "Could not prepare the logo removal AI model": "Không chuẩn bị được mô hình AI xoá logo",
    "The logo removal AI model was corrupt and has been deleted to download again: {error}":
        "Mô hình AI xoá logo bị hỏng, đã xoá để tải lại: {error}",
    "The part to remove the logo from is outside the video": "Khoảng cần xoá logo nằm ngoài video",
    "Logo removal stopped": "Đã dừng xoá logo",
    "FFmpeg failed while decoding: {error}": "FFmpeg lỗi khi giải mã: {error}",
    "FFmpeg failed while encoding: {error}": "FFmpeg lỗi khi mã hoá: {error}",
    "FFmpeg stopped midway while encoding the video": "FFmpeg dừng giữa chừng khi mã hoá video",
    "Could not read any frame from the video": "Không đọc được khung hình nào từ video",
    # delogo
    "This file has no readable video stream": "Không đọc được hình của video này",
    "Could not grab a frame: {error}": "Không lấy được khung hình: {error}",
    "FFmpeg could not read the video: {error}": "FFmpeg không đọc được video: {error}",
    "No boxes yet: draw a box around the logo or click Auto-detect":
        "Chưa có khung nào: vẽ khung quanh logo hoặc bấm Tự tìm",
    "At most {n} boxes": "Tối đa {n} khung",
    "Invalid box": "Khung không hợp lệ",
    "Box is too small or outside the frame": "Khung quá nhỏ hoặc nằm ngoài khung hình",
    "Video is too short to detect the logo: draw a box by hand": "Video quá ngắn để tự tìm logo: hãy vẽ khung bằng tay",
    "The picture barely moves, so the logo can't be told apart from it: draw a box by hand":
        "Hình gần như đứng yên nên không tách được logo: hãy vẽ khung bằng tay",
    "Too many static details (fixed frame, black bars…): draw a box by hand":
        "Quá nhiều chi tiết đứng yên (khung cố định, viền đen…): hãy vẽ khung bằng tay",
    "No static logo found: draw a box by hand": "Không thấy logo đứng yên: hãy vẽ khung bằng tay",
    "Source video file missing: rerun the project from step Download":
        "Mất file video nguồn: chạy lại dự án từ bước Tải video",
    "Source video not found": "Không có video nguồn này",
    "For a project source, the logo is only removed in the parts the final video uses":
        "Nguồn của dự án chỉ xoá logo ở các đoạn video final dùng",
    "The project's final video does not use this source yet: render the video first, then remove the logo":
        "Video final của dự án chưa dùng nguồn này: dựng video trước rồi xoá logo",
    "Pick a part at least {min} s long, within 0:00–{end}": "Chọn đoạn dài ít nhất {min} s, trong 0:00–{end}",
    "Invalid logo removal scope": "Phạm vi xoá logo không hợp lệ",
    "Invalid source rights": "Quyền nguồn không hợp lệ",
    "user confirmed rights {rights}, ": "người dùng xác nhận quyền {rights}, ",
    "The logo is already being removed from this video": "Video này đang được xoá logo",
    "whole video": "cả video",
    "{parts}, {seconds} s / {total} s": "{parts}, {seconds} s / {total} s",
    "Remove logo from source #{n} ({name}): {declaration}{boxes}, {where}":
        "Xoá logo nguồn #{n} ({name}): {declaration}{boxes}, {where}",
    "The project source changed while waiting: pick the video again":
        "Nguồn của dự án đã đổi trong lúc chờ: chọn lại video",
    "Stopped removing the logo from source #{n}": "Đã dừng xoá logo nguồn #{n}",
    "No logo removal is running for this video": "Video này không có việc xoá logo nào đang chạy",
    "The project source changed while removing the logo": "Nguồn của dự án đã đổi trong lúc xoá logo",
    "Logo removed from source #{n}: rerun from step Render to re-render the video":
        "Đã xoá logo nguồn #{n}: chạy lại từ bước Dựng để dựng lại video",
    "Source #{n} is back to the original video (logo-free version dropped)":
        "Nguồn #{n} dùng lại video gốc (bỏ bản đã xoá logo)",
    "Only video files are accepted: {types}": "Chỉ nhận video {types}",
    "File too large (max {n} GB)": "File quá lớn (tối đa {n} GB)",
    "Only uploaded files can be deleted": "Chỉ xoá được file tải lên",
    "Could not delete the file ({error}). Close the open video and try again.":
        "Không xoá được file ({error}). Đóng video đang mở rồi thử lại.",
    # llm
    "No Anthropic API key: add ANTHROPIC_API_KEY in Settings":
        "Chưa có khoá Anthropic API: nhập ANTHROPIC_API_KEY trong Cài đặt",
    "The Anthropic API key was refused: check ANTHROPIC_API_KEY in Settings":
        "Anthropic từ chối khoá API: kiểm tra ANTHROPIC_API_KEY trong Cài đặt",
    "The Anthropic API key cannot use {model}": "Khoá Anthropic API không dùng được model {model}",
    "Unknown Claude model: {model}": "Không có model Claude này: {model}",
    "Anthropic API rate limit reached: try again in a minute":
        "Anthropic API đang giới hạn tốc độ: thử lại sau một phút",
    "Could not reach the Anthropic API: check the internet connection":
        "Không kết nối được Anthropic API: kiểm tra mạng",
    "Anthropic API error {code}: {error}": "Anthropic API lỗi {code}: {error}",
    "Claude declined this request: change the topic or the source and try again":
        "Claude từ chối yêu cầu này: đổi chủ đề hoặc nguồn rồi thử lại",
    "Claude ran out of tokens before answering": "Claude hết token trước khi trả lời",
    "No JSON found in the reply: {text}": "Không thấy JSON trong câu trả lời: {text}",
    "Invalid JSON after {n} attempts: {error}": "JSON không hợp lệ sau {n} lần: {error}",
    # postiz
    "POSTIZ_URL and POSTIZ_API_KEY are not configured": "Chưa cấu hình POSTIZ_URL và POSTIZ_API_KEY",
    "Scheduling needs a posting time (date)": "Lên lịch cần thời điểm đăng (date)",
    "Invalid time: {time}": "Thời điểm không hợp lệ: {time}",
    "The time needs a time zone, e.g. 2026-10-01T18:00:00+02:00":
        "Thời điểm cần có múi giờ, vd. 2026-10-01T18:00:00+02:00",
    "The posting time must be in the future": "Thời điểm đăng phải ở tương lai",
    "mode must be one of {choices}": "mode phải là một trong {choices}",
    "version must be one of {choices}": "version phải là một trong {choices}",
    "Pick at least one channel": "Chọn ít nhất một kênh",
    "Channels not found in Postiz: {names}": "Kênh không có trong Postiz: {names}",
    # render, search, settings, topic, tts, watch
    "ffmpeg failed: {error}": "ffmpeg lỗi: {error}",
    "Invalid link: {url}": "Link không hợp lệ: {url}",
    "At most {n} links": "Tối đa {n} link",
    "yt-dlp did not create a file for {url}": "yt-dlp không tạo file cho {url}",
    "Unknown settings: {keys}": "Khoá không hợp lệ: {keys}",
    "{key} must be a number ≥ 0": "{key} phải là số ≥ 0",
    "{key} must be an integer ≥ 0": "{key} phải là số nguyên ≥ 0",
    "UI_LANG must be one of {choices}": "UI_LANG phải là một trong {choices}",
    "SLACK_WEBHOOK_URL must be a https://hooks.slack.com/… link":
        "SLACK_WEBHOOK_URL phải là link dạng https://hooks.slack.com/…",
    # Slack notifications (notify.py)
    "Slack webhook is not set, or is not a https://hooks.slack.com/… link":
        "Chưa đặt webhook Slack, hoặc không phải link https://hooks.slack.com/…",
    "Could not reach Slack: {error}": "Không kết nối được Slack: {error}",
    "Slack refused the message: {error}": "Slack từ chối tin nhắn: {error}",
    "Script ready for your approval: {title}": "Kịch bản chờ bạn duyệt: {title}",
    "Video ready for your approval: {title}": "Video chờ bạn duyệt: {title}",
    "Video failed: {title}": "Video lỗi: {title}",
    "Video ready: {title}": "Video đã xong: {title}",
    "Sent to Postiz ({mode})": "Đã gửi sang Postiz ({mode})",
    "Not sent to Postiz: {error}": "Chưa gửi được sang Postiz: {error}",
    "Motio test message: Slack alerts are working.": "Tin thử của Motio: thông báo Slack đang hoạt động.",
    "Enter a topic or at least one video link": "Nhập chủ đề hoặc ít nhất một link video",
    "No ElevenLabs API key. Go to Settings → enter ELEVENLABS_API_KEY (the macOS voice only works on a Mac).":
        "Chưa có ElevenLabs API key. Vào Cài đặt → nhập ELEVENLABS_API_KEY (giọng macOS chỉ có trên Mac).",
    "The ElevenLabs account has no voices": "Tài khoản ElevenLabs không có giọng nào",
    "This is a link to a single video: paste a channel or playlist link, or use Projects → New video":
        "Đây là link một video: dán link kênh hoặc playlist, hoặc dùng Dự án → Tạo video",
    "Only YouTube channels and playlists, Bilibili spaces or search keywords can be followed. Douyin, Facebook: "
    "paste each video link in Projects → New video":
        "Chỉ theo dõi được kênh, playlist YouTube, không gian Bilibili hoặc từ khoá tìm. Douyin, Facebook: dán link "
        "từng video vào Dự án → Tạo video",
    "Bilibili blocks requests without a login: pick a browser or set a cookie file in Settings → Browser cookies":
        "Bilibili chặn khi chưa đăng nhập: chọn trình duyệt hoặc đặt file cookie ở Cài đặt → Cookie trình duyệt",
    "Cookie file not found: {path}": "Không thấy file cookie: {path}",
    "Not a cookies.txt file (Netscape format): {path}": "Không phải file cookies.txt (định dạng Netscape): {path}",
    "Paste a channel / playlist link or enter search keywords": "Dán link kênh / playlist hoặc nhập từ khoá tìm",
    "Search works only on YouTube or Bilibili, not {site}":
        "Chỉ tìm được trên YouTube hoặc Bilibili, không phải {site}",
    "This source is already in the list": "Nguồn này đã có trong danh sách",
    "At most {n} sources": "Tối đa {n} nguồn",
    "Unknown Bilibili trending list: {target}": "Không có bảng xếp hạng Bilibili này: {target}",
    "Could not reach Bilibili: {error}": "Không kết nối được Bilibili: {error}",
    "Bilibili blocked the request ({code}): try again later": "Bilibili chặn yêu cầu ({code}): thử lại sau",
    "Bilibili returned an error: {error}": "Bilibili báo lỗi: {error}",
    # French dub (dub.py, separate.py)
    "French line": "dòng tiếng Pháp",
    "Dub: {site}": "Lồng tiếng: {site}",
    " · part {a}–{b}": " · đoạn {a}–{b}",
    "end": "cuối",
    "auto": "tự chọn",
    "Dub in French: {url}{part}": "Lồng tiếng Pháp: {url}{part}",
    "Enter the link of the video to dub": "Nhập link video cần lồng tiếng",
    "Dub project not found": "Không có dự án lồng tiếng này",
    "The part to dub must start at 0 s or later": "Đoạn lồng tiếng phải bắt đầu từ giây 0 trở đi",
    "The part to dub can be at most {max} s (videos last up to {video_max} s)":
        "Đoạn lồng tiếng dài tối đa {max} s (video dài tối đa {video_max} s)",
    "The part to dub must be at least {min} s": "Đoạn lồng tiếng dài ít nhất {min} s",
    "The part to dub is {n} s: at most {max} s": "Đoạn lồng tiếng dài {n} s: tối đa {max} s",
    "The part to dub is only {n} s: a dub needs at least {min} s of video (videos last {lo}–{hi} s)":
        "Đoạn lồng tiếng chỉ dài {n} s: cần ít nhất {min} s hình (video dài {lo}–{hi} s)",
    "your choice": "bạn chọn",
    "picked by Claude": "Claude chọn",
    "the start of the video (Claude's pick was unusable)": "đầu video (đoạn Claude chọn không dùng được)",
    "Choosing the part to dub": "Chọn đoạn để lồng tiếng",
    "No speech found in this video: there is nothing to dub": "Video không có lời nói: không có gì để lồng tiếng",
    "No speech between {a} and {b}: pick another part to dub":
        "Không có lời nói từ {a} đến {b}: chọn đoạn khác để lồng tiếng",
    "Part {a}–{b} ({length} s, {why}) + {pad} s of French intro and outro":
        "Đoạn {a}–{b} ({length} s, {why}) + {pad} s mở và kết tiếng Pháp",
    "Part {a}–{b} ({length} s, {why})": "Đoạn {a}–{b} ({length} s, {why})",
    "Old subtitles found: blurring them (move or turn off the box on the project page)":
        "Thấy phụ đề cũ: làm mờ (dời hoặc tắt khung trên trang dự án)",
    "No burned-in subtitles found (add a blur box on the project page if there are some)":
        "Không thấy phụ đề in sẵn (nếu có, thêm khung làm mờ trên trang dự án)",
    "Claude is translating {lines} into French": "Claude dịch {lines} sang tiếng Pháp",
    "Claude returned no French lines": "Claude không trả dòng tiếng Pháp nào",
    " ({n} left silent)": " ({n} dòng để im)",
    "The blur box needs x, y, width and height": "Khung làm mờ cần x, y, rộng và cao",
    "The blur box is too small": "Khung làm mờ quá nhỏ",
    "Blur box set at {a}–{b} % of the height": "Khung làm mờ ở {a}–{b} % chiều cao",
    "Blur box turned off": "Đã tắt khung làm mờ",
    "Part to dub: {a}–{b}": "Đoạn lồng tiếng: {a}–{b}",
    "Part to dub: automatic": "Đoạn lồng tiếng: tự chọn",
    "The dub has no French line to read": "Bản lồng tiếng không có dòng tiếng Pháp nào để đọc",
    "Generating the French voice ({lines})": "Tạo giọng tiếng Pháp ({lines})",
    "Generating {voices} French voices ({lines})": "Tạo {voices} giọng tiếng Pháp ({lines})",
    "Voices must map each speaker to a voice": "Giọng phải gán cho từng người nói",
    "Unknown speaker: {label}": "Không có người nói tên {label}",
    "Voices chosen for {speakers}": "Đã chọn giọng cho {speakers}",
    "Voices back to automatic": "Giọng trở lại tự chọn",
    "{voice} · {lines} placed": "{voice} · đã đặt {lines}",
    ", {n} read up to {pct} % faster": ", {n} dòng đọc nhanh hơn tới {pct} %",
    ", {n} start late (French longer than the original)": ", {n} dòng vào trễ (tiếng Pháp dài hơn bản gốc)",
    "The dub would last {n} s, over {max} s: shorten the French lines or pick a shorter part":
        "Bản lồng tiếng sẽ dài {n} s, quá {max} s: rút ngắn lời Pháp hoặc chọn đoạn ngắn hơn",
    "Downloading the voice separation AI model (67 MB, first dub only)":
        "Tải mô hình AI tách giọng (67 MB, chỉ lần lồng tiếng đầu tiên)",
    "Separating the original voices from the music and sound effects": "Tách giọng gốc khỏi nhạc nền và tiếng động",
    "Could not separate the original voices ({error}): keeping the original sound quietly under the French voice":
        "Không tách được giọng gốc ({error}): giữ tiếng gốc nhỏ dưới giọng Pháp",
    "ffmpeg could not mix the dub: {error}": "ffmpeg không trộn được bản lồng tiếng: {error}",
    "A dub keeps one French line per original line: lines can't be added or removed":
        "Bản lồng tiếng giữ mỗi câu gốc một dòng Pháp: không thêm hay xoá dòng được",
    "The dub needs at least one French line": "Bản lồng tiếng cần ít nhất một dòng tiếng Pháp",
    " · original music and sound kept": " · giữ nhạc nền và tiếng động gốc",
    " · original sound turned down": " · tiếng gốc được hạ nhỏ",
    "No video link to dub": "Chưa có link video để lồng tiếng",
    "Video to dub: {url}": "Video lồng tiếng: {url}",
    "Whisper: {name}": "Whisper: {name}",
    " (a dub of someone else's video: set the source rights to owned, licensed or CC to send it without approval)":
        " (bản lồng tiếng video của người khác: đặt quyền nguồn là của bạn, có giấy phép hoặc CC để gửi mà không "
        "cần duyệt)",
    " (an explainer built on someone else's videos: set the source rights to owned, licensed or CC to send it "
    "without approval)":
        " (video giải thích dựng từ video của người khác: đặt quyền nguồn là của bạn, có giấy phép hoặc CC để gửi "
        "mà không cần duyệt)",
    "ffmpeg did not finish in {minutes} min": "ffmpeg không xong sau {minutes} phút",
    "ffmpeg could not read the audio: {error}": "ffmpeg không đọc được âm thanh: {error}",
    "The source has no audio in this part": "Đoạn nguồn này không có âm thanh",
    "The downloaded voice separation model is not the version Motio needs (sha256 mismatch)":
        "Mô hình tách giọng tải về không đúng phiên bản Motio cần (sha256 không khớp)",
    "Could not download the voice separation AI model ({error})": "Không tải được mô hình AI tách giọng ({error})",
    "The voice separation model was corrupt and has been deleted: {error}":
        "Mô hình tách giọng bị hỏng và đã bị xoá: {error}",
    # tools (toolbox.py)
    "subtitle": "câu phụ đề",
    "Job not found": "Không tìm thấy việc này",
    "The job is still running: stop it first": "Việc đang chạy: hãy dừng nó trước",
    "Unsupported file type. Use one of: {types}": "Loại file không được nhận. Dùng một trong: {types}",
    "File too large (max {n} MB)": "File quá lớn (tối đa {n} MB)",
    "The file is empty": "File trống",
    "That job has not finished yet": "Việc đó chưa xong",
    "That job has no video or audio file": "Việc đó không có file video hoặc âm thanh",
    "That job has no video": "Việc đó không có video",
    "That job has no subtitles": "Việc đó không có phụ đề",
    "Choose a video or audio file first": "Hãy chọn file video hoặc âm thanh trước",
    "Choose a video first": "Hãy chọn video trước",
    "Choose a subtitle file first": "Hãy chọn file phụ đề trước",
    "Paste a video link first": "Hãy dán link video trước",
    "Quality must be one of {choices}": "Chất lượng phải là một trong: {choices}",
    "Language must be one of {choices}": "Ngôn ngữ phải là một trong: {choices}",
    "Size must be one of {choices}": "Cỡ chữ phải là một trong: {choices}",
    "Type or paste the text to read first": "Hãy gõ hoặc dán văn bản cần đọc trước",
    "The text can have at most {n} characters": "Văn bản tối đa {n} ký tự",
    "Unknown tool: {kind}": "Công cụ không có: {kind}",
    "Waiting to start…": "Đang chờ chạy…",
    "Starting…": "Đang bắt đầu…",
    "Stopped": "Đã dừng",
    "Interrupted: the engine was restarted": "Bị ngắt: engine đã khởi động lại",
    "Downloading…": "Đang tải…",
    "Downloaded: {info}": "Đã tải: {info}",
    "Transcribing: this can take a few minutes…": "Đang bóc lời: có thể mất vài phút…",
    "Transcribed ({lang}): {n}": "Đã bóc lời ({lang}): {n}",
    "No speech found in this file": "Không nghe thấy lời nói nào trong file này",
    "No subtitles found in this file": "Không tìm thấy phụ đề trong file này",
    "At most {n} subtitles per file": "Mỗi file tối đa {n} câu phụ đề",
    "Translating {n}…": "Đang dịch {n}…",
    "Translated {done} of {total}": "Đã dịch {done} / {total}",
    "Translated into {lang}: {n}": "Đã dịch sang {lang}: {n}",
    "The translation came back in the wrong shape": "Bản dịch Claude trả về sai định dạng",
    "Reading the text…": "Đang đọc văn bản…",
    "Read by {voice}": "Giọng đọc: {voice}",
    "Drawing the subtitles…": "Đang vẽ phụ đề…",
    "No subtitles fall inside the video": "Không có phụ đề nào nằm trong thời lượng video",
    "Subtitles added ({n})": "Đã ghi phụ đề lên video ({n})",
    # AI video (creator.py, images.py)
    "Pictures": "Ảnh",
    "Enter a topic for the AI video": "Hãy nhập chủ đề cho video AI",
    "AI video: {topic} · {duration} s · pictures from {provider}":
        "Video AI: {topic} · {duration} giây · ảnh từ {provider}",
    "Picture {n} of {total} ({provider})": "Ảnh {n} / {total} ({provider})",
    "Picture {n} failed: {error}": "Ảnh {n} bị lỗi: {error}",
    "Made {fresh} of {total} pictures · about ${cost}": "Đã làm {fresh} / {total} ảnh · khoảng ${cost}",
    "All {total} pictures were already made": "Cả {total} ảnh đã có sẵn",
    "Claude is writing the French narration and the picture prompts":
        "Claude đang viết lời bình tiếng Pháp và prompt ảnh",
    "Voice is {length} s: holding the last picture until {min} s":
        "Giọng đọc dài {length} s: giữ ảnh cuối tới {min} s",
    " (pictures from a provider that isn't cleared for monetized channels: approve the video yourself before it "
    "goes out)":
        " (ảnh của nhà cung cấp chưa được phép cho kênh kiếm tiền: bạn phải tự duyệt video trước khi đăng)",
    "The picture prompt of line {line} is longer than {n} characters":
        "Prompt ảnh của dòng {line} dài quá {n} ký tự",
    "Only AI videos have pictures to redo": "Chỉ video AI mới có ảnh để làm lại",
    "Scene {n} does not exist": "Không có cảnh {n}",
    "New picture asked for scene {n} · re-render to make it": "Đã xin ảnh mới cho cảnh {n} · dựng lại để làm ảnh đó",
    "pictures": "ảnh",
    "camera moves": "chuyển động máy quay",
    "IMAGE_PROVIDER must be one of {choices}": "IMAGE_PROVIDER phải là một trong: {choices}",
    "CLIP_PROVIDER must be one of {choices}": "CLIP_PROVIDER phải là một trong: {choices}",
    "Add your fal key in Settings → Image provider (or choose the Placeholder provider to try the flow)":
        "Hãy nhập khoá fal trong Cài đặt → Nhà cung cấp ảnh (hoặc chọn Ảnh giữ chỗ để thử luồng này)",
    "The Modal provider needs the `modal` Python package and a Modal login: it runs from the dev engine or the server, "
    "not the packaged app":
        "Nhà cung cấp Modal cần gói Python `modal` và đã đăng nhập Modal: chỉ chạy được từ engine dev hoặc server, "
        "không chạy trong app đóng gói",
    "Could not reach the image provider: {error}": "Không kết nối được nhà cung cấp ảnh: {error}",
    "fal refused the request ({error}): check the key and the credit on your fal account":
        "fal từ chối yêu cầu ({error}): kiểm tra khoá và số dư trong tài khoản fal",
    "fal could not make the picture: {error}": "fal không làm được ảnh: {error}",
    "fal returned no picture (the prompt may have been filtered)": "fal không trả ảnh nào (prompt có thể bị lọc)",
    "Could not download the picture from fal: {error}": "Không tải được ảnh từ fal: {error}",
    "Modal could not make the picture: {error}": "Modal không làm được ảnh: {error}",
    "The provider did not return a picture": "Nhà cung cấp không trả về ảnh",
    # AI clips (aiclips.py, creator.animate)
    "Clips": "Clip AI",
    "AI clips need your fal key: add it in Settings → Image provider, or set AI clips to 0":
        "Clip AI cần khoá fal của bạn: hãy nhập trong Cài đặt → Nhà cung cấp ảnh, hoặc đặt số clip AI về 0",
    "AI clips per video must be a number": "Số clip AI mỗi video phải là một số",
    "Cast line {n} must look like “Name: how they look”, with a name not used before":
        "Dòng nhân vật {n} phải có dạng “Tên: ngoại hình”, và tên chưa dùng ở dòng nào trước đó",
    "At most {n} characters in the cast": "Tối đa {n} nhân vật trong danh sách",
    "AI clips per video must be between 0 and {n}": "Số clip AI mỗi video phải từ 0 đến {n}",
    "AI clips need your HeyGen key: add it in Settings → AI pictures, or set AI clips to 0":
        "Clip AI cần khoá HeyGen của bạn: hãy nhập trong Cài đặt → Ảnh AI, hoặc đặt số clip AI về 0",
    "Could not reach HeyGen: {error}": "Không kết nối được HeyGen: {error}",
    "HeyGen refused the request ({error}): check the API key":
        "HeyGen từ chối yêu cầu ({error}): hãy kiểm tra khoá API",
    "HeyGen has no credit left: top up the API balance in your HeyGen account":
        "HeyGen hết tiền: hãy nạp thêm vào số dư API trong tài khoản HeyGen",
    "HeyGen could not make the clip: {error}": "HeyGen không làm được clip: {error}",
    "HeyGen returned no clip": "HeyGen không trả clip nào",
    "HeyGen took too long to make the clip": "HeyGen làm clip quá lâu",
    "Could not download the clip from HeyGen: {error}": "Không tải được clip từ HeyGen: {error}",
    "The clip from HeyGen is not a readable video": "Clip từ HeyGen không phải video đọc được",
    " (clips from a provider whose terms for monetized channels are not checked yet: approve the video yourself "
    "before it goes out)":
        " (clip của nhà cung cấp chưa kiểm tra điều khoản cho kênh kiếm tiền: bạn phải tự duyệt video trước khi đăng)",
    "Could not reach fal: {error}": "Không kết nối được fal: {error}",
    "fal could not make the clip: {error}": "fal không làm được clip: {error}",
    "fal returned no clip (the prompt may have been filtered)": "fal không trả clip nào (prompt có thể bị lọc)",
    "Could not download the clip from fal: {error}": "Không tải được clip từ fal: {error}",
    "The clip from fal is not a readable video": "Clip từ fal không phải video đọc được",
    "Clip {n} of {total} (scene {scene})": "Clip {n} / {total} (cảnh {scene})",
    "Clip for scene {scene} failed ({error}): it keeps its camera move":
        "Clip của cảnh {scene} bị lỗi ({error}): cảnh này giữ chuyển động máy quay",
    "Monthly budget reached: the other scenes keep their camera move":
        "Đã hết ngân sách tháng: các cảnh còn lại giữ chuyển động máy quay",
    "{made} of {total} AI clips ready · about ${cost}": "Đã có {made} / {total} clip AI · khoảng ${cost}",
    # Quality check after the render (qa.py)
    "Quality check passed": "Kiểm tra chất lượng: đạt",
    "Quality check: {problems}": "Kiểm tra chất lượng: {problems}",
    " (quality check failed: {problems}; fix it, or approve the video yourself before it goes out)":
        " (kiểm tra chất lượng không đạt: {problems}; hãy sửa, hoặc tự duyệt video trước khi đăng)",
    "Length {seconds} s": "Độ dài {seconds} s",
    "Length {seconds} s: it must be {lo} to {hi} s": "Độ dài {seconds} s: phải từ {lo} đến {hi} s",
    "No picture track": "Không có luồng hình",
    "Picture {size}, H.264": "Hình {size}, H.264",
    "Picture is {codec} {size} {pix}: platforms expect H.264 {want} yuv420p":
        "Hình là {codec} {size} {pix}: các nền tảng cần H.264 {want} yuv420p",
    "No sound track": "Không có luồng tiếng",
    "Sound track present": "Có luồng tiếng",
    "Sound is {codec}: platforms expect AAC": "Tiếng là {codec}: các nền tảng cần AAC",
    "The video is almost silent ({share}% silence)": "Video gần như im lặng ({share}% là im lặng)",
    "Loudness {lufs} LUFS": "Độ to {lufs} LUFS",
    "Loudness {lufs} LUFS: Motio aims for {target}": "Độ to {lufs} LUFS: Motio nhắm tới {target}",
    "Sound peaks at {peak} dBFS: it may clip": "Đỉnh âm thanh {peak} dBFS: có thể bị vỡ tiếng",
    "No long silence": "Không có đoạn im lặng dài",
    "Silence of {seconds} s at {at}": "Im lặng {seconds} s lúc {at}",
    " (and {n} more)": " (và {n} đoạn nữa)",
    "No black picture": "Không có hình đen",
    "Black picture for {seconds} s at {at}": "Hình đen {seconds} s lúc {at}",
    "The first picture is black for {seconds} s: the cover would be black":
        "Hình đầu tiên đen {seconds} s: ảnh bìa sẽ bị đen",
    "The video file cannot be read: {error}": "Không đọc được file video: {error}",
    "Could not check sound and black pictures: {error}": "Không kiểm tra được tiếng và hình đen: {error}",
    "Could not compare with earlier videos: {error}": "Không so sánh được với các video trước: {error}",
    "The same source video was already used in project #{n} ({days} d ago)":
        "Video nguồn này đã được dùng ở dự án #{n} ({days} ngày trước)",
    "The title is almost the same as project #{n} ({days} d ago)":
        "Tiêu đề gần giống dự án #{n} ({days} ngày trước)",
    "The script is very close to project #{n} ({days} d ago)":
        "Kịch bản rất giống dự án #{n} ({days} ngày trước)",
    # A video file added by hand as a source (localfile.py)
    "video file": "file video",
    "The video file is no longer here: add it again": "File video không còn ở đây: hãy thêm lại",
    "This video file cannot be read: {error}": "Không đọc được file video này: {error}",
    "This file has no video to use": "File này không có hình để dùng",
    "Douyin asks for fresh browser cookies to download this. Download the video yourself and add the file, or set a "
    "cookies file in Settings":
        "Douyin yêu cầu cookie trình duyệt còn mới để tải video này. Hãy tự tải video rồi thêm file vào, hoặc đặt "
        "file cookie trong Cài đặt",
    "Could not connect to Douyin. Check your internet connection (or VPN, proxy, DNS filter), then try again":
        "Không kết nối được tới Douyin. Hãy kiểm tra mạng (hoặc VPN, proxy, bộ lọc DNS) rồi thử lại",
    # Douyin through f2 (douyin.py)
    "This Douyin video was removed": "Video Douyin này đã bị xoá",
    "This Douyin video is private or restricted": "Video Douyin này ở chế độ riêng tư hoặc bị hạn chế",
    "Douyin did not give a video for this link ({reason})": "Douyin không trả video cho link này ({reason})",
    "This Douyin post is photos, not a video": "Bài Douyin này là ảnh, không phải video",
    "This video is larger than {mb} MB": "Video này lớn hơn {mb} MB",
    "This video is too short to use (under {n} s)": "Video quá ngắn để dùng (dưới {n} giây)",
    "Quality check failed: {problems}": "Kiểm tra chất lượng không đạt: {problems}",
}
