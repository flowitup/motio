import pytest

from motio import llm, newsnow
from motio.render import CUT_PAD, build_timeline, snap_end, snap_start

SOURCES = [{"duration": 120}, {"duration": 60}]


def _lines():
    return [{"text": "a", "start": 0.0, "end": 4.0, "clips": [{"src": 0, "start": 20, "end": 24}]},
            {"text": "b", "start": 4.0, "end": 9.0, "clips": [{"src": 1, "start": 1, "end": 3}]},
            {"text": "c", "start": 9.0, "end": 15.0, "clips": []}]


def test_build_timeline_covers_total_without_gaps():
    total = 15.6
    pieces = build_timeline(_lines(), SOURCES, total)
    assert pieces[0].t0 == 0.0
    assert pieces[0].src == 0 and pieces[0].src_start == 20
    for a, b in zip(pieces, pieces[1:], strict=False):
        assert b.t0 == pytest.approx(a.t0 + a.dur)
    assert pieces[-1].t0 + pieces[-1].dur == pytest.approx(total)
    for p in pieces:  # không dùng intro/outro của nguồn
        lo = 6.0 if SOURCES[p.src]["duration"] > 40 else 0
        assert p.src_start >= lo
        assert p.src_start + p.dur <= SOURCES[p.src]["duration"] - 10 + 1e-6


def test_build_timeline_ignores_invalid_src():
    lines = [{"text": "a", "start": 0, "end": 5, "clips": [{"src": 9, "start": 0, "end": 4}, {"src": "x"}]}]
    pieces = build_timeline(lines, SOURCES, 5.0)
    assert sum(p.dur for p in pieces) == pytest.approx(5.0)
    assert all(p.src in (0, 1) for p in pieces)


def test_snap_start_and_end_to_cuts():
    assert snap_start(10.0, 15.0, [10.5]) == pytest.approx(10.5 + CUT_PAD)  # cú cắt ngay sau điểm vào
    assert snap_start(10.0, 15.0, [11.5]) == 10.0  # xa hơn 0.8 s: giữ nguyên
    assert snap_start(10.0, 11.0, [10.5]) == 10.0  # còn lại quá ngắn sau cú cắt
    assert snap_end(10.0, 4.0, [13.6]) == pytest.approx(3.6 - CUT_PAD)  # cú cắt ngay trước điểm ra
    assert snap_end(10.0, 4.0, [12.0]) == 4.0
    assert snap_end(10.0, 1.2, [10.5]) == 1.2  # không cắt mảnh xuống dưới 1 s


def test_build_timeline_follows_scene_cuts():
    sources = [{"duration": 120, "cuts": [20.4, 23.7, 40.0]}, {"duration": 60, "cuts": []}]
    lines = [{"text": "a", "start": 0.0, "end": 6.0, "clips": [{"src": 0, "start": 20, "end": 24.3}]},
             {"text": "b", "start": 6.0, "end": 12.0, "clips": []}]
    pieces = build_timeline(lines, sources, 12.0)
    first = pieces[0]
    assert first.src == 0 and first.src_start == pytest.approx(20.4 + CUT_PAD)  # vào từ cú cắt 20.4
    assert first.src_start + first.dur == pytest.approx(23.7 - CUT_PAD)  # dừng trước cú cắt 23.7
    assert pieces[-1].t0 + pieces[-1].dur == pytest.approx(12.0)
    for a, b in zip(pieces, pieces[1:], strict=False):
        assert b.t0 == pytest.approx(a.t0 + a.dur)


@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', {"a": 1}),
    ('Voici :\n```json\n{"a": [1, 2]}\n```\nVoilà', {"a": [1, 2]}),
    ('Réponse: [{"id": "x"}] fin', [{"id": "x"}]),
    ('bla {"a": {"b": 2}} bla', {"a": {"b": 2}}),
])
def test_parse_json(text, expected):
    assert llm.parse_json(text) == expected


def test_parse_json_without_json():
    with pytest.raises(llm.LLMError):
        llm.parse_json("pas de json ici")


def test_safe_id():
    assert newsnow.safe_id("douyin", "2644652") == "douyin:2644652"
    hashed = newsnow.safe_id("baidu", "https://www.baidu.com/s?wd=热搜")
    assert hashed.startswith("baidu:") and len(hashed) == len("baidu:") + 12
    assert hashed == newsnow.safe_id("baidu", "https://www.baidu.com/s?wd=热搜")
    assert newsnow.safe_id("weibo", 12345) == "weibo:12345"
