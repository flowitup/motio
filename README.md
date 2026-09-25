# Studio · MVP tin nóng

Web app làm video tiếng Pháp 9:16 từ tin hot Trung Quốc (NewsNow): tìm clip nguồn trên YouTube và
Bilibili, bóc lời bằng Whisper, Claude viết lời bình tiếng Pháp và chọn đoạn, ElevenLabs đọc,
FFmpeg dựng (nền mờ, nhãn nguồn, phụ đề, công bố giọng AI).

## Chạy trên Mac

```bash
cd ~/Works/studio
uv sync                          # lần đầu
uv run python -m studio serve        # mở http://127.0.0.1:8765
```

1. Bấm **Cập nhật tin hot**: lấy bảng Douyin, Weibo, Baidu, Bilibili, Toutiao, The Paper; Claude dịch
   tiêu đề sang Pháp và chấm điểm cho khán giả Pháp.
2. Chọn tin, bấm **Làm video**. Trang dự án hiện tiến trình, nhật ký, video và nội dung bài đăng
   (tiêu đề, mô tả, nguồn, hashtag).

Dòng lệnh: `uv run python -m studio refresh`, `... trends`, `... produce douyin:2644652`.

## Cấu hình (.env)

| Biến | Ý nghĩa |
|---|---|
| `LLM_PROVIDER` | `claude_cli` (Claude Code trên Mac, dùng gói Claude của bạn) hoặc `anthropic` (API key, cho server) |
| `LLM_MODEL` | `sonnet` / `opus` với claude_cli; model ID đầy đủ qua `ANTHROPIC_MODEL` với anthropic |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Giọng Pháp; bỏ trống voice để app tự chọn giọng tiếng Pháp trong tài khoản |
| `WHISPER_MODEL` | Mặc định `mlx-community/whisper-large-v3-turbo` |
| `NEWSNOW_URL`, `NEWS_SOURCES` | Bản NewsNow tự host (`http://newsnow:4444`) khi lên server |

Dữ liệu (SQLite, video nguồn, dự án) nằm trong `data/`.

## Cấu trúc

```
studio/newsnow.py   lấy tin + dịch + chấm điểm
studio/search.py    yt-dlp tìm / tải nguồn (giữ nền tảng, kênh, giấy phép)
studio/asr.py       Whisper (mlx trên Mac, faster-whisper nơi khác)
studio/llm.py       claude -p hoặc Claude API
studio/tts.py       ElevenLabs có mốc thời gian (giọng macOS nếu chưa có key)
studio/render.py    dựng 9:16: Pillow vẽ chữ, FFmpeg ghép
studio/pipeline.py  7 bước của một dự án
studio/web.py       dashboard
```

## Quy tắc nội dung có sẵn

Lời bình tiếng Pháp riêng có bối cảnh và phân tích; mỗi đoạn nguồn 3–6 giây có nhãn
“Source : nền tảng · kênh”; mô tả bài ghi đủ link nguồn; nhãn “Voix de synthèse (IA)” trên video.
