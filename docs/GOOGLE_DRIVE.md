# Google Drive làm kho chính của Motio

Máy chỉ giữ phần video đang làm dở. Khi một video xong, Motio đưa file lớn của nó lên Google Drive của bạn, kiểm tra
bản trên Drive giống hệt rồi mới xoá bản trên máy. Cái gì chuyển và cái gì ở lại:

| Chuyển lên Drive (và xoá trên máy) | Ở lại trên máy |
|---|---|
| `projects/<id>/`: video 9:16, bản 16:9, giọng đọc, ảnh và clip AI, kết quả tách giọng (mọi file từ 1 MiB) | CSDL SQLite, `settings.json`, model (Whisper, LaMa, tách giọng) |
| `cache/sources/`: video nguồn đã tải mà không dự án nào đang làm dở dùng (và đã tải hơn 1 giờ) | `script.json`, `post.txt`, `sources.txt`, phụ đề, ảnh bìa và mọi file nhỏ dưới 1 MiB |

Motio nói chuyện với Drive qua API (không cài thêm gì, không mount ổ đĩa), nên chạy giống nhau trên Mac, máy Windows ở
nhà và server. Nó dùng quyền `drive.file`: chỉ thấy các file do chính nó tạo, không đụng vào phần còn lại của Drive.

## Việc bạn làm một lần (khoảng 5 phút)

1. Vào <https://console.cloud.google.com>, tạo một project mới (tên tuỳ ý, ví dụ "Motio"). Dùng tài khoản nào cũng được,
   nhưng nên chính tài khoản giữ Drive.
2. **APIs & Services → Library** → tìm **Google Drive API** → **Enable**.
3. **APIs & Services → OAuth consent screen** (hoặc "Google Auth platform"): chọn **External**, điền tên app (Motio) và
   email của bạn. Google chỉ cho Publish khi trang **Branding** có link trang chủ và link chính sách quyền riêng tư công
   khai (cùng domain đó trong **Authorised domains**); app của owner dùng <https://yaiba2307.github.io/motio-privacy/> và
   `.../privacy.html` (repo công khai `yaiba2307/motio-privacy`). Ở phần **Audience** bấm **Publish app** để chuyển sang
   **In production**. Bước này quan trọng: ở chế độ
   *Testing*, Google huỷ đăng nhập sau 7 ngày. Scope `drive.file` không cần Google duyệt app; lúc đăng nhập bạn sẽ thấy
   cảnh báo "Google hasn't verified this app": chọn **Advanced → Go to Motio (unsafe)**, đó là app của chính bạn.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**, loại ứng dụng **TVs and Limited Input
   devices**. Chép **Client ID** và **Client secret** ngay (hoặc **Download JSON**): Google chỉ hiện secret lúc vừa tạo,
   đóng hộp thoại rồi thì phải tạo secret mới.
5. Trong Motio: **Cài đặt → Kho lưu trữ (Google Drive)**. Dán Client ID và Client secret, bật "Dùng Google Drive làm kho
   chính", bấm **Lưu**.
6. Bấm **Đăng nhập Google**. Motio hiện một mã; mở địa chỉ hiện ra (google.com/device) trên bất kỳ thiết bị nào, chọn tài
   khoản giữ Drive (mtbui.creative@gmail.com) và nhập mã. Xong, Cài đặt hiện email và dung lượng Drive.
7. Bấm **Chuyển lên Drive ngay** để dọn các video đã làm từ trước. Từ đó mỗi video xong tự chuyển lên.

Với engine từ xa (máy Windows ở nhà, server): làm các bước 5-7 từ app đang nối vào engine đó; token nằm trong
`settings.json` của engine, mỗi engine đăng nhập riêng.

## Nó hoạt động thế nào

- **Upload**: phiên upload tiếp tục được (chunk 16 MiB) vào `<thư mục Drive>/<đường dẫn trong data>`, ví dụ
  `Motio/projects/12/final.mp4`. Xong thì so dung lượng và md5 với số Drive báo. Lệch thì bản trên Drive vào thùng rác,
  bản trên máy giữ nguyên.
- **Chỉ xoá trên máy khi chắc**: dự án phải đang rảnh (xong, lỗi, hoặc chờ duyệt video), file không đổi trong lúc upload.
  Đang chờ duyệt kịch bản hoặc ảnh thì chưa chuyển gì.
- **Xem lại**: app phát video thẳng từ Drive (đường `/media` chuyển tiếp, hỗ trợ tua).
- **Dựng lại / thử lại / sửa kịch bản**: trước khi chạy, engine kéo về giọng đọc, ảnh và clip của dự án (không kéo video
  cuối vì sắp được dựng lại). Video nguồn bị chuyển đi cũng được kéo về khi cần. Gửi Postiz bằng tay cũng kéo video về.
- **Xoá dự án**: file của nó trên Drive vào thùng rác Drive (khôi phục được trong 30 ngày). Nếu lúc xoá không nối được
  Drive, lần dọn sau sẽ bỏ các file mồ côi đó.
- **Giữ một bản trên máy**: bật thì Drive chỉ là bản sao lưu, không xoá gì trên máy.
- **Offline**: video vẫn làm bình thường; file chưa lên được thì ở lại máy, lần dọn sau gửi tiếp. Muốn xem hoặc dựng
  lại video đã chuyển đi thì cần mạng.

## Giới hạn đã biết

- Chưa thử với Google thật: logic chạy trên Drive giả trong `tests/test_drive.py`. Lần đầu hãy thử với một video ngắn.
- Chỉ dự án và video nguồn được chuyển. Công cụ lẻ (Tải, Xoá logo, Công cụ) và model vẫn ở máy.
- Tải một video nguồn đã chuyển đi, lúc thêm lại cùng link, tải lại từ nguồn thay vì lấy từ Drive.
- Đổi thư mục Drive hay đăng nhập tài khoản khác: các file đã chuyển vẫn trỏ về tài khoản cũ. Đừng đổi khi còn file ở đó.
- Google giới hạn khoảng 750 GB upload mỗi ngày cho mỗi tài khoản.
- Đăng nhập hết hạn (đổi mật khẩu, thu hồi quyền ở myaccount.google.com/permissions): Cài đặt báo lỗi, đăng nhập lại là xong.
