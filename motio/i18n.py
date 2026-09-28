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
    "Unsupported LLM_PROVIDER: {provider}": "LLM_PROVIDER không hỗ trợ: {provider}",
    "claude -p failed ({code}): {error}": "claude -p lỗi ({code}): {error}",
    "claude -p did not return JSON: {output}": "claude -p trả về không phải JSON: {output}",
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
    "{key} must be an integer ≥ 0": "{key} phải là số nguyên ≥ 0",
    "UI_LANG must be one of {choices}": "UI_LANG phải là một trong {choices}",
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
    "Bilibili blocks requests without a login: pick a browser in Settings → Browser cookies":
        "Bilibili chặn khi chưa đăng nhập: chọn trình duyệt ở Cài đặt → Cookie trình duyệt",
    "Paste a channel / playlist link or enter search keywords": "Dán link kênh / playlist hoặc nhập từ khoá tìm",
    "Search works only on YouTube or Bilibili, not {site}":
        "Chỉ tìm được trên YouTube hoặc Bilibili, không phải {site}",
    "This source is already in the list": "Nguồn này đã có trong danh sách",
    "At most {n} sources": "Tối đa {n} nguồn",
}
