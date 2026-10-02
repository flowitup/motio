"""Cookie cho yt-dlp (motio/search.py): file cookies.txt cho máy không có trình duyệt."""
import threading
from pathlib import Path

import pytest

from motio import douyin, search, settings

JAR = ("# Netscape HTTP Cookie File\n"
       ".bilibili.com\tTRUE\t/\tTRUE\t2000000000\tSESSDATA\tsecret\n")


class FakeYDL:
    opts: list = []
    urls: list = []

    def __init__(self, opts):
        FakeYDL.opts.append(opts)
        self.out = Path(opts["outtmpl"]).parent if "outtmpl" in opts else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False, process=True):
        FakeYDL.urls.append(url)
        if not download:
            return {"entries": []}
        (self.out / "Fake_1.mp4").write_bytes(b"video")
        return {"id": "1", "extractor_key": "Fake"}

    def prepare_filename(self, info):
        return str(self.out / "Fake_1.mp4")


@pytest.fixture(autouse=True)
def fake_ydl(monkeypatch, tmp_path):
    FakeYDL.opts, FakeYDL.urls = [], []
    monkeypatch.setattr(search, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(search.config, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(search, "_jar_dir", None)  # thư mục bản sao riêng của từng test
    search._jar.__dict__.clear()


@pytest.fixture
def jar(tmp_path):
    f = tmp_path / "cookies.txt"
    f.write_text(JAR, encoding="utf-8")
    settings.update({"YTDLP_COOKIES_FILE": str(f)})
    return f


def test_no_cookies_by_default():
    assert search.cookie_file() is None and search._cookie_opts() == {}
    search.search("熊猫", "bilibili")
    assert "cookiefile" not in FakeYDL.opts[0]


def test_cookie_file_is_validated_when_saved(tmp_path):
    with pytest.raises(ValueError, match="Cookie file not found"):
        settings.update({"YTDLP_COOKIES_FILE": str(tmp_path / "nope.txt")})
    bad = tmp_path / "bad.txt"
    bad.write_text("not a cookie jar\n")
    with pytest.raises(ValueError, match="Netscape"):
        settings.update({"YTDLP_COOKIES_FILE": str(bad)})
    assert settings.public()["YTDLP_COOKIES_FILE"]["value"] == ""
    settings.update({"YTDLP_COOKIES_FILE": ""})  # xoá được dù đang trống


def test_quoted_path_from_explorer_works(tmp_path):
    f = tmp_path / "cookies.txt"
    f.write_text(JAR, encoding="utf-8")
    settings.update({"YTDLP_COOKIES_FILE": f'"{f}"'})  # Explorer: Copy as path
    assert search.cookie_file() == f


def test_file_wins_over_browser_and_is_never_the_original(jar, monkeypatch):
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "firefox")
    opts = search._cookie_opts()
    assert "cookiesfrombrowser" not in opts and opts["cookiefile"] != str(jar)
    assert open(opts["cookiefile"], encoding="utf-8").read() == JAR
    jar.unlink()  # file biến mất: quay về trình duyệt
    assert search._cookie_opts() == {"cookiesfrombrowser": ("firefox",)}


def test_bilibili_search_and_download_use_the_file_but_youtube_does_not(jar):
    search.search("熊猫", "bilibili")
    search.search("panda", "youtube")
    search.download("https://www.bilibili.com/video/BV1x", jar.parent / "out")
    search.download("https://b23.tv/abc", jar.parent / "out")
    search.download("https://www.youtube.com/watch?v=abc", jar.parent / "out")
    used = ["cookiefile" in o for o in FakeYDL.opts]
    assert used == [True, False, True, True, False]


def test_pasted_links_use_cookies_on_any_site(jar):
    search.download("https://www.douyin.com/video/1", jar.parent / "out", cookies=True)
    assert "cookiefile" in FakeYDL.opts[0]


def test_each_thread_gets_its_own_copy_and_the_original_stays_untouched(jar):
    mine = search._cookie_opts()["cookiefile"]
    theirs: list[str] = []
    t = threading.Thread(target=lambda: theirs.append(search._cookie_opts()["cookiefile"]))
    t.start()
    t.join()
    assert theirs[0] != mine
    open(mine, "a", encoding="utf-8").write("# yt-dlp saved here\n")  # yt-dlp ghi lại khi đóng
    assert jar.read_text(encoding="utf-8") == JAR
    assert search._cookie_opts()["cookiefile"] == mine  # cùng luồng dùng lại, không chép đè lúc file gốc chưa đổi
    assert "yt-dlp saved" in open(mine, encoding="utf-8").read()
    jar.write_text(JAR + ".bilibili.com\tTRUE\t/\tTRUE\t2000000000\tbuvid3\tx\n", encoding="utf-8")
    assert "buvid3" in open(search._cookie_opts()["cookiefile"], encoding="utf-8").read()  # file gốc đổi: chép lại


def test_douyin_links_try_f2_first_and_skip_yt_dlp_when_it_works(monkeypatch, tmp_path):
    calls = []

    def fake(url, out_dir, max_height, hooks):
        calls.append((url, max_height))
        return {"path": str(out_dir / "Douyin_1.mp4"), "id": "1", "platform": "Douyin"}

    monkeypatch.setattr(douyin, "download", fake)
    info = search.download("https://v.douyin.com/iNUBcHxM/", tmp_path, 480, cookies=True)
    assert info["id"] == "1" and calls == [("https://v.douyin.com/iNUBcHxM/", 480)] and FakeYDL.opts == []
    search.download("https://v.douyin.com/iNUBcHxM/", tmp_path)  # không nói cỡ: Douyin lấy bản lớn nhất đến 1080
    assert calls[-1] == ("https://v.douyin.com/iNUBcHxM/", 1080)


def test_douyin_links_fall_back_to_yt_dlp_when_f2_cannot(tmp_path):
    info = search.download("https://www.douyin.com/video/1", tmp_path)  # conftest: f2 tắt trong test
    assert info["id"] == "1" and len(FakeYDL.opts) == 1


def test_a_douyin_video_that_is_gone_is_not_retried_with_yt_dlp(monkeypatch, tmp_path):
    def gone(*a, **k):
        raise douyin.Unavailable("This Douyin video was removed")

    monkeypatch.setattr(douyin, "download", gone)
    with pytest.raises(douyin.Unavailable, match="removed"):
        search.download("https://www.douyin.com/video/1", tmp_path, cookies=True)
    assert FakeYDL.opts == []


def test_other_sites_never_go_through_f2(monkeypatch, tmp_path):
    monkeypatch.setattr(douyin, "download", lambda *a, **k: pytest.fail("f2 is for Douyin only"))
    search.download("https://www.youtube.com/watch?v=abc", tmp_path)
    search.download("https://www.bilibili.com/video/BV1x", tmp_path)
    assert len(FakeYDL.opts) == 2


def test_yt_dlp_gets_the_plain_video_link_when_f2_cannot(tmp_path):
    """yt-dlp only knows www.douyin.com/video/<id>: the other forms are turned into it before the fallback."""
    search.download("https://www.douyin.com/jingxuan?modal_id=7686432847778982833", tmp_path)
    search.download("https://www.iesdouyin.com/share/video/7683844732023911406/?region=CN", tmp_path)
    search.download("https://v.douyin.com/iNUBcHxM/", tmp_path)  # no id without following the redirect: as it was
    assert FakeYDL.urls == ["https://www.douyin.com/video/7686432847778982833",
                            "https://www.douyin.com/video/7683844732023911406", "https://v.douyin.com/iNUBcHxM/"]


SHARE = ("7.43 复制打开抖音，看看【某某的作品】标题 # 话题 https://v.douyin.com/iR2syBRn/ L@s.Fw 06/11 "
         "复制此链接，打开Dou音搜索，直接观看视频！")


@pytest.mark.parametrize("text, expected", [
    (SHARE, "https://v.douyin.com/iR2syBRn/"),
    ("https://v.douyin.com/iR2syBRn/ 复制此链接", "https://v.douyin.com/iR2syBRn/"),
    ("看看 https://v.douyin.com/abc/复制此链接，打开", "https://v.douyin.com/abc/"),  # chữ Hán dính sát link
    ("see (https://example.com/video/1).", "https://example.com/video/1"),
    ("https://www.douyin.com/video/7686432847778982833", "https://www.douyin.com/video/7686432847778982833"),
    ("https://example.com/视频/1", "https://example.com/视频/1"),  # link thuần có chữ Hán trong đường dẫn: giữ nguyên
])
def test_clean_links_takes_the_link_out_of_a_pasted_share_sentence(text, expected):
    assert search.clean_links([text]) == [expected]
    assert search.clean_links([text, expected]) == [expected]  # cùng link thì chỉ giữ một


@pytest.mark.parametrize("text", ["7.43 复制打开抖音，没有链接 www.douyin.com", "复制此链接", "ftp://example.com/x y",
                                  "a b"])
def test_clean_links_still_refuses_text_without_a_link(text):
    with pytest.raises(ValueError, match="Invalid link"):
        search.clean_links([text])


def test_without_a_height_other_sites_stay_at_720(tmp_path):
    search.download("https://www.youtube.com/watch?v=abc", tmp_path)
    search.download("https://www.youtube.com/watch?v=abc", tmp_path, 1080)
    assert "height<=720" in FakeYDL.opts[0]["format"] and "height<=1080" in FakeYDL.opts[1]["format"]
