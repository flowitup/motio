# Motio · MVP tin nóng

Web app làm video tiếng Pháp 9:16 từ tin hot Trung Quốc (NewsNow): tìm clip nguồn trên YouTube và
Bilibili, bóc lời bằng Whisper, Claude viết lời bình tiếng Pháp và chọn đoạn, ElevenLabs đọc,
FFmpeg dựng (nền mờ, nhãn nguồn, phụ đề, công bố giọng AI).

## Chạy trên Mac

```bash
cd ~/Works/motio
uv sync                          # lần đầu
uv run python -m motio serve        # mở http://127.0.0.1:8765
```

1. Bấm **Cập nhật tin hot**: lấy bảng Douyin, Weibo, Baidu, Bilibili, Toutiao, The Paper; Claude dịch
   tiêu đề sang Pháp và chấm điểm cho khán giả Pháp.
2. Chọn tin, bấm **Làm video**. Trang dự án hiện tiến trình, nhật ký, video và nội dung bài đăng
   (tiêu đề, mô tả, nguồn, hashtag).

Dòng lệnh: `uv run python -m motio refresh`, `... trends`, `... produce douyin:2644652`.

## App desktop (Tauri)

```bash
cd app && pnpm install
pnpm tauri dev        # mở app; engine tự chạy bằng uv từ gốc repo
```

Cần Rust (`rustup`). App tự tìm `uv` trong PATH, `~/.local/bin`, Homebrew; đặt `MOTIO_UV` nếu ở chỗ khác.
Cài đặt → "Engine từ xa" để dùng engine trên máy khác (URL + token), khi đó app không tự chạy engine.

## Engine API (cho app desktop)

```bash
uv run python -m motio engine --port 0 --token <t>   # in {"event":"ready","port":N,...} rồi phục vụ
```

Mọi `/api/*` cần `Authorization: Bearer <t>`; `/media/*` và `/api/projects/{id}/events` (SSE) nhận thêm
`?token=`. `--host 0.0.0.0` (chạy từ xa) bắt buộc có `--token`. `--exit-with-stdin` tự thoát khi app cha đóng.

## Cấu hình (.env)

Cài đặt đổi trong app được lưu ở `data/settings.json`, đè lên `.env` và có hiệu lực ngay.

| Biến | Ý nghĩa |
|---|---|
| `LLM_PROVIDER` | `claude_cli` (Claude Code trên Mac, dùng gói Claude của bạn) hoặc `anthropic` (API key, cho server) |
| `LLM_MODEL` | `sonnet` / `opus` với claude_cli; model ID đầy đủ qua `ANTHROPIC_MODEL` với anthropic |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Giọng Pháp; bỏ trống voice để app tự chọn giọng tiếng Pháp trong tài khoản |
| `WHISPER_MODEL` | Mặc định `mlx-community/whisper-large-v3-turbo` |
| `NEWSNOW_URL`, `NEWS_SOURCES` | Bản NewsNow tự host (`http://newsnow:4444`) khi lên server |
| `MAX_VIDEOS_PER_DAY` | Giới hạn số video mỗi ngày (0 = không giới hạn) |
| `MOTIO_FFMPEG`, `MOTIO_FFPROBE`, `MOTIO_CLAUDE` | Đường dẫn binary nếu không nằm trong PATH |

Dữ liệu (SQLite, video nguồn, dự án) nằm trong `data/`.

## Cấu trúc

```
motio/newsnow.py   lấy tin + dịch + chấm điểm
motio/search.py    yt-dlp tìm / tải nguồn (giữ nền tảng, kênh, giấy phép)
motio/asr.py       Whisper (mlx trên Mac, faster-whisper nơi khác)
motio/llm.py       claude -p hoặc Claude API
motio/tts.py       ElevenLabs có mốc thời gian (giọng macOS nếu chưa có key)
motio/render.py    dựng 9:16: Pillow vẽ chữ, FFmpeg ghép
motio/pipeline.py  7 bước của một dự án
motio/settings.py  data/settings.json đè lên .env
motio/api.py       engine API JSON cho app desktop
motio/web.py       dashboard cũ (bỏ sau M2)
```

## Quy tắc nội dung có sẵn

Lời bình tiếng Pháp riêng có bối cảnh và phân tích; mỗi đoạn nguồn 3–6 giây có nhãn
“Source : nền tảng · kênh”; mô tả bài ghi đủ link nguồn; nhãn “Voix de synthèse (IA)” trên video.
