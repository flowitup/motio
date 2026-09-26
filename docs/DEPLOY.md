# Chạy Motio + Postiz trên server Hetzner

Một server Hetzner Cloud chạy engine Motio (API cho app desktop, dựng video 24/7) và Postiz (đăng bài lên
TikTok, YouTube, Instagram, Facebook, X…), cùng sau Caddy lo HTTPS. Mọi thứ nằm trong `deploy/`.

```
App desktop ──https + token──▶ Caddy ─┬─ motio.<domain>   → engine (FastAPI, Whisper CPU, FFmpeg)
Trình duyệt ─────────https───────────▶ └─ postiz.<domain>  → Postiz ─ Postgres, Redis, Temporal (+ Postgres, Elasticsearch)
engine ── http://postiz:5000/api (mạng nội bộ Docker) ──▶ Postiz Public API ──▶ các mạng xã hội
engine ── http://newsnow:4444 (mạng nội bộ) ──▶ NewsNow tự host ──▶ bảng tin hot Douyin, Weibo, Baidu…
```

Engine tự cập nhật tin mỗi `REFRESH_EVERY_MIN` phút (mặc định 30 trên server, 0 = tắt) từ NewsNow tự host
(dịch vụ `newsnow`, ảnh `ghcr.io/ourongxing/newsnow`, không mở ra Internet).

| File | Vai trò |
|---|---|
| `Dockerfile` | ảnh engine: Python 3.12, ffmpeg, font DejaVu + Noto CJK, faster-whisper |
| `deploy/compose.yaml` | toàn bộ stack (Caddy, engine, NewsNow, Postiz và các dịch vụ đi kèm) |
| `deploy/Caddyfile` | 2 tên miền → engine / Postiz, chứng chỉ Let's Encrypt tự động |
| `deploy/env.example` | mẫu `/opt/motio/.env` trên server (bí mật, tên miền, key) |
| `deploy/bootstrap.sh` | cài server mới một lần: Docker, user `deploy`, swap, tường lửa |
| `.github/workflows/deploy.yml` | build ảnh engine lên GHCR rồi SSH vào server cập nhật stack |

## 1. Chuẩn bị

- **Server**: Hetzner Cloud, Ubuntu 24.04, **4 vCPU / 8 GB RAM trở lên** (16 GB thoải mái hơn), ổ ≥ 80 GB.
  Postiz + Temporal + Elasticsearch chiếm khoảng 3 GB RAM, Whisper large-v3-turbo thêm 2–3 GB khi bóc lời.
  Máy x86 (dòng CX/CPX) dùng mặc định; máy ARM (CAX) thì đặt biến `MOTIO_PLATFORM=linux/arm64` ở bước 4.
- **Tên miền**: hai bản ghi A (và AAAA nếu có IPv6) trỏ về IP server, vd. `motio.example.com` và
  `postiz.example.com`. Caddy chỉ lấy được chứng chỉ khi DNS đã trỏ đúng.
- **Key**: `ANTHROPIC_API_KEY` (server không có Claude Code CLI nên dùng Claude API) và `ELEVENLABS_API_KEY`.

## 2. Cài server (một lần)

```bash
ssh-keygen -t ed25519 -f motio-deploy -N "" -C github-actions        # key riêng cho GitHub Actions
ssh root@<ip> "DEPLOY_PUBKEY='$(cat motio-deploy.pub)' bash -s" < deploy/bootstrap.sh
```

Script cài Docker + Compose, tạo user `deploy` (vào bằng key của root và key GitHub Actions), thư mục
`/opt/motio`, 4 GB swap, mở cổng 22/80/443 bằng ufw và tắt đăng nhập SSH bằng mật khẩu. Nên bật thêm
Hetzner Cloud Firewall (22, 80, 443 TCP và 443 UDP) và Backups trong Hetzner Console.

## 3. File `.env` trên server

```bash
scp deploy/env.example deploy@<ip>:/opt/motio/.env
ssh deploy@<ip>
cd /opt/motio && chmod 600 .env
openssl rand -hex 32     # chạy 4 lần: MOTIO_TOKEN, POSTIZ_JWT_SECRET, POSTIZ_DB_PASSWORD, TEMPORAL_DB_PASSWORD
nano .env                # điền tên miền, 4 chuỗi trên, ANTHROPIC_API_KEY, ELEVENLABS_API_KEY
```

Mật khẩu dùng chuỗi hex (không ký tự đặc biệt) vì nằm trong URL Postgres. `POSTIZ_API_KEY` và key các mạng
xã hội điền sau (bước 6). Cài đặt thêm cho Postiz (LinkedIn, SMTP, Cloudflare R2…) để trong
`/opt/motio/postiz.env`; workflow deploy không ghi đè `.env` và `postiz.env`.

## 4. GitHub: secrets và biến

Repo → Settings → Secrets and variables → Actions:

| Secret | Giá trị |
|---|---|
| `HETZNER_HOST` | IP (hoặc tên miền) của server |
| `HETZNER_USER` | `deploy` (bỏ trống cũng được) |
| `HETZNER_SSH_KEY` | nội dung file `motio-deploy` (private key) |
| `HETZNER_KNOWN_HOSTS` | kết quả `ssh-keyscan -t ed25519 <ip>` |

| Biến (Variables), tuỳ chọn | Tác dụng |
|---|---|
| `AUTO_DEPLOY=true` | tự deploy mỗi lần push lên `master` có sửa engine hoặc `deploy/` |
| `MOTIO_PLATFORM=linux/arm64` | build ảnh cho server ARM (CAX) |

Ảnh engine nằm ở `ghcr.io/flowitup/motio-engine` (private). Mỗi lần deploy, server đăng nhập GHCR bằng token
tạm của workflow rồi đăng xuất, nên không cần PAT.

## 5. Deploy

Actions → **Deploy (Hetzner)** → Run workflow (nhánh `master`). Workflow build ảnh `sha-<commit>`, chép
`compose.yaml`, `Caddyfile`, `temporal/` lên `/opt/motio`, ghim `MOTIO_IMAGE` trong `.env`, rồi
`docker compose pull && docker compose up -d --wait`. Lần đầu mất vài phút (Postiz khởi động khoảng 2 phút).

Kiểm tra: `curl -H "Authorization: Bearer <MOTIO_TOKEN>" https://motio.<domain>/api/health` trả JSON, và
`https://postiz.<domain>` mở trang đăng nhập Postiz.

## 6. Postiz: tài khoản, kênh, API key

1. Mở `https://postiz.<domain>` và đăng ký. `POSTIZ_DISABLE_REGISTRATION=true` chỉ cho tài khoản đầu tiên
   đăng ký, sau đó khoá trang đăng ký.
2. Mỗi mạng xã hội cần **app developer của chính bạn** (Postiz tự host không dùng app chung). Redirect URI:
   `https://postiz.<domain>/integrations/social/<provider>` (`youtube`, `tiktok`, `instagram-standalone`,
   `facebook`, `x`, `threads`). Hướng dẫn từng nền tảng: docs.postiz.com → Self-host → Providers. Điền Client
   ID / Secret vào `.env` rồi chạy lại workflow (hoặc `docker compose up -d postiz` trên server).
3. Trong Postiz bấm **Add Channel** cho từng kênh.
4. Postiz → Settings → Developers → **Public API** → copy key. Điền `POSTIZ_API_KEY` vào `.env` rồi
   `docker compose up -d engine`, hoặc nhập trong app Motio → Cài đặt → Đăng bài (Postiz).

Lưu ý khi app developer chưa được duyệt:
- **TikTok**: app chưa qua audit chỉ đăng được ở chế độ riêng tư. Motio gửi `PUBLIC_TO_EVERYONE`, nên trước khi
  có audit hãy gửi **Nháp** rồi đổi quyền trong Postiz. Nộp audit sớm.
- **YouTube**: project Google Cloud chưa qua audit thì video tải lên bị để private.
- Motio luôn giữ dòng "Voix off générée par IA." trong bài và bật nhãn AI của TikTok (`video_made_with_ai`).

## 7. App desktop

Cài đặt → Engine → chế độ **Engine từ xa**, URL `https://motio.<domain>`, Token = `MOTIO_TOKEN`.
Trang một dự án đã xong có thẻ **Đăng bài (Postiz)**: chọn kênh, rồi **Nháp** (duyệt trong Postiz),
**Lên lịch** (Postiz tự đăng đúng giờ) hoặc **Đăng ngay**. Các lần gửi được ghi vào nhật ký dự án.

API tương ứng: `GET /api/postiz/channels`, `POST /api/projects/{id}/publish`
`{"channels": ["<id>"], "mode": "draft" | "schedule" | "now", "date": "<ISO 8601 có múi giờ>"}`.

## 8. Vận hành

```bash
ssh deploy@<ip>
cd /opt/motio
docker compose ps
docker compose logs -f engine            # hoặc newsnow, postiz, caddy, temporal
docker compose up -d                     # áp dụng thay đổi trong .env
docker compose --profile ops up -d temporal-ui
#   rồi trên máy bạn: ssh -L 8080:127.0.0.1:8080 deploy@<ip> → http://localhost:8080
```

Sao lưu (ngoài Hetzner Backups):

```bash
docker compose exec -T postiz-postgres pg_dump -U postiz postiz | gzip > postiz-$(date +%F).sql.gz
docker run --rm -v motio_motio-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/motio-data-$(date +%F).tgz -C /data --exclude=./cache .
```

Nâng Postiz: đọc release notes, so `deploy/compose.yaml` với
[postiz-docker-compose](https://github.com/gitroomhq/postiz-docker-compose), đổi `POSTIZ_VERSION` trong `.env`
rồi `docker compose up -d`.

## Giới hạn đã biết

- YouTube hay chặn tải video từ IP datacenter ("Sign in to confirm you're not a bot"); nguồn Bilibili thường
  không bị. Khi thiếu nguồn, xem nhật ký dự án.
- Whisper chạy CPU (faster-whisper int8), chậm hơn mlx-whisper trên Mac.
- LLM trên server là Claude API, tính tiền theo token.
- Engine dựng một video một lúc.
