# Chạy Motio trên máy Windows ở nhà (máy chủ), Mac chỉ theo dõi

Máy Windows (ổ lớn, bật 24/7) chạy engine Motio và giữ mọi thứ: video nguồn đã tải, dự án, video đã làm, cơ sở dữ
liệu, khoá API. Mac chỉ mở app, chọn **Engine từ xa** và xem: video, ảnh bìa, kết quả công cụ đều được phát (stream)
từ máy Windows, file bạn tải lên (trang Xoá logo, Công cụ) đi thẳng lên máy Windows, nên Mac không giữ video nào.

```
App Mac ── HTTP + token, qua Tailscale ──▶ engine Motio trên Windows ──▶ D:\Motio\data (video, SQLite, cache)
                                            ├─ yt-dlp, faster-whisper, FFmpeg
                                            └─ Claude, ElevenLabs, fal, Postiz, Slack (đi ra Internet từ nhà)
```

Script `tools/windows/motio-server.ps1` cài engine chạy nền (Task Scheduler), mở cổng cho Tailscale và kiểm tra tình
trạng. Cả luồng dưới đây **chưa chạy trên máy Windows thật** (xem "Chưa kiểm chứng" ở cuối).

## 1. Chuẩn bị

- **Tailscale** trên cả Windows và Mac, cùng một tài khoản. Trên Windows: `tailscale ip -4` cho địa chỉ dạng
  `100.x.y.z`.
- **Motio MSI** (bản mới nhất ở GitHub Releases, cùng phiên bản với app Mac) cài trên Windows. Không cần mở app:
  script dùng engine nằm trong thư mục cài đặt (`motio-engine.exe`).
- **Thư mục dữ liệu** trên ổ lớn, ví dụ `D:\Motio\data`. Không đặt trên ổ C: nếu ổ đó nhỏ: mặc định engine ghi vào
  `%APPDATA%\Motio`.
- **Tài khoản Windows** bạn dùng hằng ngày, để máy tự đăng nhập (netplwiz) hoặc luôn đăng nhập: engine chạy trong
  phiên của tài khoản đó, nên `claude` CLI và cookie trình duyệt của tài khoản đó là cái engine nhìn thấy.
- **Claude** (viết kịch bản): mặc định engine gọi `claude -p` (tính vào gói Claude), nên cài Claude Code trên Windows và
  đăng nhập đúng tài khoản trên. Hoặc vào Cài đặt chọn nhà cung cấp `anthropic` và nhập khoá API (tính tiền theo token).
- **Bóc lời** trên Windows là faster-whisper (mlx chỉ có trên Mac): CPU (int8) mặc định; GPU NVIDIA chỉ được dùng nếu
  máy đã cài CUDA 12 và cuDNN 9 (bản đóng gói không kèm các thư viện này). Chưa đo tốc độ trên máy của bạn.

## 2. Cài engine chạy nền

Mở PowerShell **bằng quyền quản trị** (Run as administrator), tài khoản Windows ở trên:

```powershell
# lấy script (sau khi PR này đã vào master), hoặc chép từ repo
Invoke-WebRequest https://raw.githubusercontent.com/flowitup/motio/master/tools/windows/motio-server.ps1 -OutFile motio-server.ps1
Set-ExecutionPolicy -Scope Process Bypass
.\motio-server.ps1 -DataDir D:\Motio\data -KeepAwake
```

Script làm các việc sau và in ra URL + token cho Mac:

1. Tìm `motio-engine.exe` trong thư mục cài Motio (hoặc truyền `-Exe <đường dẫn>`) và địa chỉ Tailscale của máy
   (hoặc `-BindAddress`).
2. Tạo `D:\Motio\data`, thư mục model Whisper `D:\Motio\hf` (để ~1,6 GB model không chiếm ổ C:), và một token ngẫu nhiên
   (giữ trong `%LOCALAPPDATA%\MotioServer\token.txt`, chạy lại script thì dùng lại token cũ).
3. Tạo tác vụ **Motio engine** trong Task Scheduler: chạy mỗi lần bạn đăng nhập, tự chạy lại mỗi phút nếu engine dừng
   (ví dụ lúc Tailscale chưa lên). Engine nghe **chỉ trên địa chỉ Tailscale**, không trên mạng nhà.
4. Thêm luật Windows Firewall cho cổng 8765 chỉ từ dải Tailscale (`100.64.0.0/10`).
5. Với `-KeepAwake`: tắt chế độ ngủ / ngủ đông khi cắm điện (màn hình vẫn tắt được).
6. Khởi động tác vụ và chờ `/api/health` trả lời.

Các lệnh khác: `.\motio-server.ps1 -Status` (trạng thái tác vụ + engine + ổ đĩa), `.\motio-server.ps1 -Uninstall`
(gỡ tác vụ và luật tường lửa, dữ liệu giữ nguyên). Cổng đổi bằng `-Port`.

## 3. Nối Mac

1. Mac: Cài đặt → Engine → **Engine từ xa**, URL `http://100.x.y.z:8765`, Token như script in ra → Áp dụng.
2. Thẻ "Tình trạng engine" phải hiện OS **Windows**, `data` là `D:\Motio\data` và dòng **Ổ đĩa** còn bao nhiêu.
3. Nhập lại các khoá (Claude nếu dùng API, ElevenLabs, fal, Postiz, Slack) trong Cài đặt: chúng được lưu trong
   `settings.json` của máy Windows, không phải trên Mac. Muốn máy chủ tự cập nhật tin và tự làm video thì đặt
   "Tự cập nhật … mỗi N phút" (mặc định tắt trên bản desktop).
4. Bỏ mục khởi động trên Mac đang đặt `MOTIO_DATA`, và đừng chạy engine dev trên Mac song song: hai engine cùng lịch tự
   làm video sẽ làm trùng.

Đường Tailscale đã mã hoá (WireGuard) nên dùng `http://` không lộ nội dung. Nếu app Mac không nối được vì WebView macOS
chặn HTTP tới địa chỉ ngoài máy (chưa ai thử), dùng HTTPS của Tailscale: trên Windows chạy
`tailscale serve --bg --https=443 http://100.x.y.z:8765` rồi nhập URL `https://<tên-máy>.<tailnet>.ts.net`.

## 4. Cookie cho Bilibili (Douyin không cần)

Engine đọc cookie trình duyệt **trên máy nó chạy**, tức Windows, không phải Mac, và Chrome / Edge trên Windows thường
mã hoá cookie khiến yt-dlp không đọc được. Cách ổn định hơn là một file `cookies.txt`:

1. Đăng nhập Bilibili (và X nếu cần) trên trình duyệt bất kỳ, xuất `cookies.txt` bằng một tiện ích xuất cookie (định dạng
   Netscape; chỉ chọn bilibili.com / x.com).
2. Chép file sang máy Windows, **ngoài thư mục dữ liệu**, ví dụ `D:\Motio\cookies.txt` (Taildrop:
   `tailscale file cp cookies.txt <tên-máy-windows>:`).
3. Cài đặt → **File cookie (cookies.txt)** → nhập đường dẫn trên máy Windows → Lưu. Engine kiểm tra file đọc được rồi mới lưu.

Dùng cho: link dán tay (mọi trang), tìm kiếm và tải video Bilibili, danh sách Bilibili ở trang "Video mới". Được ưu tiên
hơn "Cookie trình duyệt"; YouTube tự tìm không dùng cookie. Cookie hết hạn thì xuất lại và chép đè. Engine dùng bản sao
tạm (yt-dlp ghi lại file khi đóng) nên file gốc không bị sửa, và `/media` không bao giờ phục vụ file này. Coi nó như
mật khẩu. Douyin không cần cookie: engine lấy video công khai bằng f2 (xem `docs/DOUYIN_F2.md`; chưa thử trên Windows, và
engine phải là bản 0.7.13 trở lên); cookie chỉ là đường dự phòng
của yt-dlp khi f2 không làm được, và chưa chắc đủ (yt-dlp có báo cáo lỗi "Fresh cookies are needed" dù cookie còn hạn).

## 5. Vận hành

```powershell
Get-Content D:\Motio\engine.err.log -Tail 50          # nhật ký (cái cũ: engine.err.log.prev)
Stop-ScheduledTask "Motio engine"; Start-ScheduledTask "Motio engine"   # khởi động lại
```

- **Cập nhật:** app Mac tự cập nhật, engine Windows thì không. Cài MSI mới trên Windows (hoặc mở app Motio trên Windows →
  Cài đặt → Cập nhật), rồi chạy lại `motio-server.ps1` (nó dừng engine cũ, ghi lại tác vụ). Giữ hai máy cùng phiên bản.
- **Windows tự khởi động lại** (Windows Update, mất điện): cần tự đăng nhập; tác vụ chạy lại khi đăng nhập. Dự án đang chạy
  lúc đó bị đánh dấu thất bại khi engine lên lại: mở dự án → Chạy lại.
- **Một việc một lúc:** engine dựng một video mỗi lần; Mac đóng hay mất mạng không làm dừng việc đang chạy.
- **Sao lưu:** `D:\Motio\data\motio.sqlite3` và `settings.json` (khoá API dạng chữ thường: giữ riêng tư). Video làm lại
  được, cơ sở dữ liệu thì không.
- Cảnh báo Slack (`SLACK_WEBHOOK_URL`) báo khi dự án chờ duyệt, xong hoặc lỗi, kể cả khi Mac đóng app.

## 6. Chép dữ liệu cũ từ Mac

Dự án và video đã có trên Mac (`~/Works/motio/data` hoặc `~/Library/Application Support/Motio`) chép sang được: dừng
tác vụ, chép nguyên thư mục `data` sang `D:\Motio\data`, bật lại. Video đã xong và ảnh bìa dùng đường dẫn tương đối
nên xem được ngay; chạy lại một dự án sẽ tìm lại video nguồn theo id trong `cache\sources`. Đường dẫn nguồn lưu trong dự án
là đường dẫn tuyệt đối của Mac, nên nguồn đã xoá logo và nút so sánh với video gốc của bản lồng tiếng có thể mất liên kết.
Chưa có script viết lại các đường dẫn đó. Chỉ xoá dữ liệu trên Mac sau khi đã kiểm tra bản trên Windows.

## Chưa kiểm chứng

- Script và cả luồng trên máy Windows thật (cú pháp PowerShell đã được phân tích bằng `pwsh`, chưa chạy các lệnh Windows).
- Engine đóng gói trên Windows: bóc lời, dựng video với font Windows; tốc độ faster-whisper trên CPU / GPU của bạn.
- Windows Defender / SmartScreen có thể hỏi khi chạy `motio-engine.exe` lần đầu (bản cài chưa ký).
- WebView macOS với HTTP tới địa chỉ Tailscale (cách dự phòng: `tailscale serve`, mục 3).
