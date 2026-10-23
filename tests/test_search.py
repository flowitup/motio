"""Cookie cho yt-dlp (motio/search.py): file cookies.txt cho máy không có trình duyệt."""
import threading
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from motio import bilibili_dl, douyin, haokan, kuaishou, platforms, search, settings

JAR = ("# Netscape HTTP Cookie File\n"
       ".bilibili.com\tTRUE\t/\tTRUE\t2000000000\tSESSDATA\tsecret\n")


class FakeYDL:
    opts: list = []
    urls: list = []
    fail: Exception | None = None  # extract_info raises it (a download that fails)

    def __init__(self, opts):
        FakeYDL.opts.append(opts)
        self.out = Path(opts["outtmpl"]).parent if "outtmpl" in opts else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False, process=True):
        FakeYDL.urls.append(url)
        if FakeYDL.fail:
            raise FakeYDL.fail
        if not download:
            return {"entries": []}
        (self.out / "Fake_1.mp4").write_bytes(b"video")
        return {"id": "1", "extractor_key": "Fake"}

    def prepare_filename(self, info):
        return str(self.out / "Fake_1.mp4")


@pytest.fixture(autouse=True)
def fake_ydl(monkeypatch, tmp_path):
    FakeYDL.opts, FakeYDL.urls, FakeYDL.fail = [], [], None
    monkeypatch.setattr(search, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(search.config, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(search, "_jar_dir", None)  # thư mục bản sao riêng của từng test
    search._jar.__dict__.clear()


SHORT = "https://v.douyin.com/iNUBcHxM/"


@pytest.fixture(autouse=True)
def short_links(monkeypatch):
    """A short link is followed over the network (douyin._resolve_id): here it is a table, and the calls are counted.
    A link that is not in the table has no id, like a short link that leads nowhere. No waiting between f2's tries."""
    monkeypatch.setattr(douyin, "_pause", lambda: None)
    table = {SHORT: "7683844732023911406"}
    calls = []

    def resolve(url):
        calls.append(url)
        return douyin._post_id(url) or table.get(url)

    monkeypatch.setattr(douyin, "_resolve_id", resolve)
    return calls


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

    def fake(url, out_dir, max_height, hooks, post_id=None):
        calls.append((url, max_height, post_id))
        return {"path": str(out_dir / "Douyin_1.mp4"), "id": "1", "platform": "Douyin"}

    monkeypatch.setattr(douyin, "download", fake)
    info = search.download(SHORT, tmp_path, 480, cookies=True)
    assert info["id"] == "1" and calls == [(SHORT, 480, "7683844732023911406")] and FakeYDL.opts == []
    search.download(SHORT, tmp_path)  # không nói cỡ: Douyin lấy bản lớn nhất đến 1080
    assert calls[-1] == (SHORT, 1080, "7683844732023911406")


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


def test_yt_dlp_gets_the_plain_video_link_when_f2_cannot(tmp_path, short_links):
    """yt-dlp only knows www.douyin.com/video/<id>: the other forms, a short link too, are turned into it before the
    fallback, and the short link is followed once for both f2 and yt-dlp."""
    search.download("https://www.douyin.com/jingxuan?modal_id=7686432847778982833", tmp_path)
    search.download("https://www.iesdouyin.com/share/video/7683844732023911406/?region=CN", tmp_path)
    assert short_links == [  # a link that already holds its id is not looked up on the network
        "https://www.douyin.com/jingxuan?modal_id=7686432847778982833",
        "https://www.iesdouyin.com/share/video/7683844732023911406/?region=CN"]
    del short_links[:]
    search.download(SHORT, tmp_path)  # what the app's Share sentence holds
    assert short_links == [SHORT]
    assert FakeYDL.urls == ["https://www.douyin.com/video/7686432847778982833",
                            "https://www.douyin.com/video/7683844732023911406",
                            "https://www.douyin.com/video/7683844732023911406"]


def test_a_short_link_that_leads_nowhere_goes_to_yt_dlp_as_it_was(tmp_path):
    search.download("https://v.douyin.com/unknown/", tmp_path)
    assert FakeYDL.urls == ["https://v.douyin.com/unknown/"]


NO_CONNECTION = "Could not connect to Douyin"


def test_no_connection_to_douyin_is_blamed_on_the_network_not_on_cookies(monkeypatch, tmp_path):
    """f2 could not connect and yt-dlp then asks for cookies (it does so even with no network at all)."""
    def offline(*a, **k):
        raise douyin.Unreachable("no route")

    monkeypatch.setattr(douyin, "download", offline)
    FakeYDL.fail = DownloadError("ERROR: [Douyin] 1: Fresh cookies (not necessarily logged in) are needed")
    with pytest.raises(RuntimeError, match=NO_CONNECTION):
        search.download("https://www.douyin.com/video/1", tmp_path)
    assert FakeYDL.urls == ["https://www.douyin.com/video/1"]  # yt-dlp still had its turn


def test_a_real_answer_from_douyin_is_not_relabelled_as_no_connection(monkeypatch, tmp_path):
    """Only yt-dlp's cookie hint is ambiguous: a 403 or a removed video is what Douyin said, whatever f2 saw."""
    def offline(*a, **k):
        raise douyin.Unreachable("no route")

    monkeypatch.setattr(douyin, "download", offline)
    FakeYDL.fail = DownloadError("ERROR: [Douyin] 1: HTTP Error 403: Forbidden")
    with pytest.raises(DownloadError, match="403"):
        search.download("https://www.douyin.com/video/1", tmp_path)


def test_yt_dlp_can_still_save_the_video_when_only_f2_was_cut_off(monkeypatch, tmp_path):
    """A DNS filter or a firewall can block f2's token server while douyin.com itself answers."""
    def offline(*a, **k):
        raise douyin.Unreachable("token server blocked")

    monkeypatch.setattr(douyin, "download", offline)
    assert search.download("https://www.douyin.com/video/1", tmp_path)["id"] == "1"


def test_no_connection_while_following_a_short_link_stops_there(monkeypatch, tmp_path):
    """yt-dlp has no extractor for a short link, so it is not asked about one that could not even be followed."""
    def offline(url):
        raise douyin.Unreachable("no route")

    monkeypatch.setattr(douyin, "find_id", offline)
    with pytest.raises(RuntimeError, match=NO_CONNECTION):
        search.download(SHORT, tmp_path)
    assert FakeYDL.urls == []


def test_the_cookie_hint_stays_when_f2_was_not_cut_off(tmp_path):
    FakeYDL.fail = DownloadError("ERROR: [Douyin] 1: Fresh cookies (not necessarily logged in) are needed")
    with pytest.raises(RuntimeError, match="fresh browser cookies"):  # conftest: f2 is off, not a network error
        search.download("https://www.douyin.com/video/1", tmp_path)


def test_other_sites_keep_their_own_download_error(tmp_path):
    FakeYDL.fail = DownloadError("ERROR: Unsupported URL")
    with pytest.raises(DownloadError):
        search.download("https://example.com/video/1", tmp_path)


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


def test_clean_links_refuses_two_links_on_one_line_instead_of_dropping_one():
    """The app splits the box on new lines only: two links pasted on one line were refused in 0.7.12 and must not
    lose the second one without a word now that a link is taken out of a sentence."""
    for text in ("https://a.example/x https://b.example/y", "https://a.example/x, https://b.example/y",
                 SHARE + " https://v.douyin.com/other/"):
        with pytest.raises(ValueError, match="Invalid link"):
            search.clean_links([text])


def test_without_a_height_other_sites_stay_at_720(tmp_path):
    search.download("https://www.youtube.com/watch?v=abc", tmp_path)
    search.download("https://www.youtube.com/watch?v=abc", tmp_path, 1080)
    assert "height<=720" in FakeYDL.opts[0]["format"] and "height<=1080" in FakeYDL.opts[1]["format"]


# ---------- Chinese sites besides Bilibili and Douyin (platforms.py, haokan.py) ----------
def test_a_weibo_link_is_given_to_yt_dlp_in_the_shape_it_understands(tmp_path):
    search.download("https://weibo.com/2/detail/5354603969514346", tmp_path, cookies=True)
    assert FakeYDL.urls == ["https://m.weibo.cn/detail/5354603969514346"]


def test_a_short_xiaohongshu_link_is_followed_first(monkeypatch, tmp_path):
    followed = []
    monkeypatch.setattr(platforms, "expand", lambda url: followed.append(url) or "https://www.xiaohongshu.com/explore/ab12")
    search.download("http://xhslink.com/a/AbC123", tmp_path, cookies=True)
    assert followed == ["http://xhslink.com/a/AbC123"] and FakeYDL.urls == ["https://www.xiaohongshu.com/explore/ab12"]


def test_haokan_links_do_not_go_through_yt_dlp(monkeypatch, tmp_path):
    seen = []

    def fake(url, out_dir, max_height, hooks):
        seen.append((url, max_height))
        return {"path": str(out_dir / "Haokan_1.mp4"), "id": "1", "platform": "Haokan"}

    monkeypatch.setattr(haokan, "download", fake)
    info = search.download("https://haokan.baidu.com/v?vid=123", tmp_path, 480, cookies=True)
    assert info["platform"] == "Haokan" and seen == [("https://haokan.baidu.com/v?vid=123", 480)] and FakeYDL.opts == []


def test_kuaishou_says_to_add_the_file_instead_of_trying(monkeypatch, tmp_path):
    monkeypatch.setattr(kuaishou, "tool", lambda: None)  # videodl not installed
    with pytest.raises(RuntimeError, match="Kuaishou.*add the file"):
        search.download("https://v.kuaishou.com/AbCdEf", tmp_path, cookies=True)
    assert FakeYDL.opts == []


@pytest.mark.parametrize("url,site", [("https://www.xiaohongshu.com/explore/ab12", "Xiaohongshu"),
                                      ("https://www.ixigua.com/6863073327775547912", "Xigua"),
                                      ("https://www.zhihu.com/zvideo/1387089980523728897", "Zhihu")])
@pytest.mark.parametrize("error", ["Cookies (not necessarily logged in) are needed", "HTTP Error 403: Forbidden",
                                   "Please log in to view this note"])
def test_a_site_that_wants_a_session_gets_a_hint_about_cookies(url, site, error, tmp_path):
    FakeYDL.fail = DownloadError(error)
    with pytest.raises(RuntimeError, match=f"{site} asks for a browser session.*cookies"):
        search.download(url, tmp_path, cookies=True)


def test_a_xiaohongshu_link_without_its_token_says_to_paste_the_full_link(tmp_path):
    FakeYDL.fail = DownloadError("[XiaoHongShu] ab12: No video formats found!; please report this issue")
    with pytest.raises(RuntimeError, match="xsec_token"):
        search.download("https://www.xiaohongshu.com/explore/ab12", tmp_path)
    with pytest.raises(RuntimeError, match="Xiaohongshu gave no video"):  # with a token: not the missing-token case
        search.download("https://www.xiaohongshu.com/explore/ab12?xsec_token=T", tmp_path)


def test_a_picture_saved_instead_of_a_video_is_not_returned(monkeypatch, tmp_path):
    class Pictures(FakeYDL):  # Weibo post with only pictures: yt-dlp leaves a .jpg under the post id
        def extract_info(self, url, download=False, process=True):
            (self.out / "Weibo_1.jpg").write_bytes(b"jpeg")
            return {"id": "1", "extractor_key": "Weibo"}

        def prepare_filename(self, info):
            return str(self.out / "Weibo_1.jpg")

    monkeypatch.setattr(search, "YoutubeDL", Pictures)
    with pytest.raises(RuntimeError, match="only pictures"):
        search.download("https://m.weibo.cn/detail/5354603969514346", tmp_path, cookies=True)
    assert list(tmp_path.iterdir()) == []


def test_a_xigua_video_that_is_also_on_douyin_comes_from_douyin(monkeypatch, tmp_path):
    asked = []

    def fake(url, out_dir, max_height, hooks, post_id):
        asked.append((url, max_height, post_id))
        return {"path": str(out_dir / f"Douyin_{post_id}.mp4"), "id": post_id, "platform": "Douyin"}

    monkeypatch.setattr(douyin, "download", fake)
    for link in ("https://www.ixigua.com/7296116808145175092", "https://m.ixigua.com/video/7296116808145175092",
                 "https://www.ixigua.com/7296116808145175092?logTag=x"):
        info = search.download(link, tmp_path, 480, cookies=True)
        assert info["platform"] == "Douyin"
    assert asked[0] == ("https://www.douyin.com/video/7296116808145175092", 480, "7296116808145175092")
    assert FakeYDL.opts == []  # yt-dlp was not needed


def test_a_xigua_video_not_on_douyin_goes_to_yt_dlp_and_then_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(douyin, "download", lambda *a, **k: None)
    FakeYDL.fail = DownloadError("Cookies (not necessarily logged in) are needed")
    with pytest.raises(RuntimeError, match="Xigua asks for a browser session.*not on Douyin either.*cookies"):
        search.download("https://www.ixigua.com/7359024563227656714", tmp_path, cookies=True)
    assert FakeYDL.urls == ["https://www.ixigua.com/7359024563227656714/"]


def test_xigua_cookies_set_by_the_user_are_used_before_douyin(monkeypatch, tmp_path):
    monkeypatch.setattr(search, "_cookie_opts", lambda: {"cookiefile": "x"})
    monkeypatch.setattr(douyin, "download", lambda *a, **k: pytest.fail("Douyin tried first"))
    search.download("https://www.ixigua.com/7359024563227656714", tmp_path, cookies=True)
    assert FakeYDL.urls == ["https://www.ixigua.com/7359024563227656714/"]


def test_no_video_formats_on_weibo_or_xiaohongshu_with_token_gets_a_hint(tmp_path):
    FakeYDL.fail = DownloadError("[Weibo] 1: No video formats found!; please report this issue")
    with pytest.raises(RuntimeError, match="Weibo gave no video.*only pictures.*cookies"):
        search.download("https://m.weibo.cn/detail/5354603969514346", tmp_path, cookies=True)
    FakeYDL.fail = DownloadError("[XiaoHongShu] ab12: No video formats found!")
    with pytest.raises(RuntimeError, match="Xiaohongshu gave no video"):
        search.download("https://www.xiaohongshu.com/explore/ab12?xsec_token=T", tmp_path)


def test_other_yt_dlp_errors_on_those_sites_are_kept(tmp_path):
    FakeYDL.fail = DownloadError("[Zhihu] 1: Unable to download webpage: HTTP Error 404")
    with pytest.raises(DownloadError, match="404"):
        search.download("https://www.zhihu.com/zvideo/1", tmp_path)
    FakeYDL.fail = DownloadError("Extractor failed to obtain id")
    with pytest.raises(DownloadError, match="obtain id"):
        search.download("https://www.xiaohongshu.com/explore/ab12", tmp_path)  # not a login problem: yt-dlp's text


def test_downloaded_videos_name_their_site():
    assert search.PLATFORM["XiaoHongShu"] == "Xiaohongshu" and search.PLATFORM["Ixigua"] == "Xigua"
    assert search.PLATFORM["Zhihu"] == "Zhihu"


# ---------- Bilibili: yt-dlp cannot read the page any more, the site's own API takes over (bilibili_dl.py) ----------
BILI = "https://www.bilibili.com/video/BV1UaJ96UEmt"


def test_a_bilibili_video_yt_dlp_cannot_read_comes_from_the_bilibili_api(monkeypatch, tmp_path):
    seen = []

    def fake(url, out_dir, max_height, hooks):
        seen.append((url, max_height))
        return {"path": str(out_dir / "BiliBili_1UaJ96UEmt.mp4"), "id": "1UaJ96UEmt", "platform": "Bilibili"}

    FakeYDL.fail = DownloadError("[BiliBili] 1UaJ96UEmt: Unable to extract initial state")
    monkeypatch.setattr(bilibili_dl, "download", fake)
    info = search.download(BILI, tmp_path, 480, cookies=False)
    assert info["platform"] == "Bilibili" and seen == [(BILI, 480)] and FakeYDL.urls == [BILI]


def test_yt_dlp_is_tried_first_so_a_cookie_session_still_works(monkeypatch, tmp_path):
    monkeypatch.setattr(bilibili_dl, "download", lambda *a: pytest.fail("yt-dlp worked: no fallback"))
    assert search.download(BILI, tmp_path, cookies=False)["id"] == "1"


def test_a_bilibili_link_that_is_not_a_video_keeps_yt_dlps_answer(monkeypatch, tmp_path):
    def refuse(*a):
        raise bilibili_dl.NotSupported("series")

    FakeYDL.fail = DownloadError("This video is only available for premium members")
    monkeypatch.setattr(bilibili_dl, "download", refuse)
    with pytest.raises(DownloadError, match="premium"):
        search.download("https://www.bilibili.com/bangumi/play/ep1", tmp_path)


def test_a_bilibili_video_the_api_does_not_give_says_why(monkeypatch, tmp_path):
    def refuse(*a):
        raise bilibili_dl.Unavailable("Bilibili does not give this video to a guest (paid, a film or a series)")

    FakeYDL.fail = DownloadError("Unable to extract initial state")
    monkeypatch.setattr(bilibili_dl, "download", refuse)
    with pytest.raises(RuntimeError, match="paid, a film or a series"):
        search.download(BILI, tmp_path)


def test_other_sites_never_reach_the_bilibili_api(monkeypatch, tmp_path):
    monkeypatch.setattr(bilibili_dl, "download", lambda *a: pytest.fail("not a Bilibili link"))
    FakeYDL.fail = DownloadError("Unable to extract initial state")
    with pytest.raises(DownloadError):
        search.download("https://www.youtube.com/watch?v=abc", tmp_path)
