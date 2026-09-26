import pytest

from motio import llm, newsnow
from motio.render import Piece, build_timeline, caption_chunks, split_by_captions


def test_caption_chunks_short_and_long():
    assert caption_chunks("  Bonjour   la France ") == ["Bonjour la France"]
    text = "La Chine a lancé une nouvelle fusée hier soir, et les images ont fait le tour des réseaux sociaux"
    chunks = caption_chunks(text, max_chars=58)
    assert len(chunks) == 2
    assert all(len(c) <= 58 for c in chunks)
    assert " ".join(chunks) == text
    assert chunks[0].endswith(",")  # ngắt ưu tiên sau dấu phẩy


def test_caption_chunks_without_spaces():
    assert caption_chunks("x" * 120, max_chars=50) == ["x" * 50, "x" * 50, "x" * 20]


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


def test_split_by_captions():
    pieces = [Piece(src=0, src_start=10.0, dur=4.0, t0=0.0)]
    events = [(0.0, 1.5, "un"), (1.5, 3.0, "deux"), (3.0, 4.0, "trois")]
    out = split_by_captions(pieces, events)
    assert [p.caption for p in out] == ["un", "deux", "trois"]
    assert [p.t0 for p in out] == [0.0, 1.5, 3.0]
    assert [p.src_start for p in out] == [10.0, 11.5, 13.0]
    assert sum(p.dur for p in out) == pytest.approx(4.0)


def test_split_ignores_cuts_near_edges():
    out = split_by_captions([Piece(0, 0.0, 4.0, 0.0)], [(0.0, 0.1, "a"), (0.1, 4.0, "b")])
    assert len(out) == 1 and out[0].caption == "b"


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
