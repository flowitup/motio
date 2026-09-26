import pytest

from motio import captions
from motio.captions import NBSP, Cue, Word, build_cues, fr_typography, french_words, karaoke_frames, word_times


@pytest.mark.parametrize("text,expected", [
    ("Pourquoi ?", f"Pourquoi{NBSP}?"),
    ("Pourquoi?", f"Pourquoi{NBSP}?"),
    ("Attention : danger ; vraiment !", f"Attention{NBSP}: danger{NBSP}; vraiment{NBSP}!"),
    ("Quoi ?!", f"Quoi{NBSP}?!"),
    ('Il a dit "bonjour" hier', f"Il a dit «{NBSP}bonjour{NBSP}» hier"),
    ("« Oui » dit-il", f"«{NBSP}Oui{NBSP}» dit-il"),
    ("“Non”, répond-il", f"«{NBSP}Non{NBSP}», répond-il"),
    ("l'État", "l’État"),
    ("À 12:30 sur https://x.fr", "À 12:30 sur https://x.fr"),  # giờ và link không đổi
])
def test_fr_typography(text, expected):
    assert fr_typography(text) == expected


def test_french_words_merges_detached_punctuation_with_times():
    ws = french_words([Word("«", 0.0, 0.1), Word("Oui", 0.1, 0.5), Word("»", 0.5, 0.6), Word("vraiment", 0.6, 1.0),
                       Word("?", 1.0, 1.1)])
    assert [w.text for w in ws] == [f"«{NBSP}Oui{NBSP}»", f"vraiment{NBSP}?"]
    assert (ws[0].start, ws[0].end, ws[1].end) == (0.0, 0.6, 1.1)


def test_word_times_uses_alignment_when_it_matches():
    lines = ["Bonjour la", "France"]
    text = "Bonjour la France"
    starts = [i * 0.1 for i in range(len(text))]
    al = {"characters": list(text), "character_start_times_seconds": starts,
          "character_end_times_seconds": [s + 0.1 for s in starts]}
    out = word_times(lines, [{"start": 0, "end": 1}, {"start": 1, "end": 2}], al)
    assert [[w.text for w in ln] for ln in out] == [["Bonjour", "la"], ["France"]]
    assert out[1][0].start == pytest.approx(1.1) and out[1][0].end == pytest.approx(1.7)
    assert out[0][1].start == pytest.approx(0.8)


def test_word_times_falls_back_to_line_spans():
    out = word_times(["ab cd"], [{"start": 2.0, "end": 3.0}], {"characters": ["x"]})
    assert [(w.text, w.start, w.end) for w in out[0]] == [("ab", 2.0, 2.4), ("cd", 2.6, 3.0)]


def test_cues_respect_42_chars_two_lines_and_keep_timing():
    text = ("La Chine a lancé une nouvelle fusée hier soir depuis le désert de Gobi, et les images du décollage "
            "ont fait le tour des réseaux sociaux en quelques heures seulement.")
    words = word_times([text], [{"start": 0.0, "end": 12.0}])
    cues = build_cues(words, total=13.0)
    for c in cues:
        assert 1 <= len(c.lines) <= 2
        assert all(len(" ".join(w.text for w in ln)) <= 42 for ln in c.lines)
    assert " ".join(c.text(" ") for c in cues) == text
    assert cues[0].start == 0.0 and cues[-1].end == 13.0
    for a, b in zip(cues, cues[1:], strict=False):  # liền mạch, không chồng
        assert a.end == pytest.approx(b.start)
    assert cues[0].text(" ").endswith("Gobi,")  # ngắt ưu tiên sau dấu phẩy


def test_cues_never_join_two_script_lines_and_merge_orphans():
    words = word_times(["Une ligne courte.", "Puis une autre phrase qui continue encore un peu ici. Fin."],
                       [{"start": 0, "end": 2}, {"start": 2, "end": 8}])
    cues = build_cues(words, total=8.5, shift=0.15)
    assert cues[0].text(" ") == "Une ligne courte."
    assert cues[0].start == pytest.approx(0.15)
    assert not any(c.text(" ") == "Fin." for c in cues)  # một từ lẻ ở cuối được gộp lên


def test_short_tail_is_rebalanced():
    words = word_times(["Pourquoi la Chine lance-t-elle une fusée ce soir ?"], [{"start": 0, "end": 4}])
    cues = build_cues(words, total=4, fits=lambda s: len(s) <= 25)
    assert [c.text(" ") for c in cues] == ["Pourquoi la Chine lance-t-elle", f"une fusée ce soir{NBSP}?"]


def test_cues_use_custom_fit():
    words = word_times(["un deux trois quatre"], [{"start": 0, "end": 4}])
    cues = build_cues(words, total=4, fits=lambda s: len(s) <= 9)
    assert [c.text("|") for c in cues] == ["un deux", "trois|quatre"]  # đuôi "quatre" được chia lại cho cân


def test_karaoke_frames_cover_timeline():
    c1 = Cue(0.5, 2.0, [[Word("a", 0.5, 0.9), Word("b", 1.0, 1.4)]])
    c2 = Cue(2.0, 3.0, [[Word("c", 2.0, 2.5)]])
    frames = karaoke_frames([c1, c2])
    assert [(a, b, lit) for a, b, _, lit in frames] == [(0.0, 0.5, 0), (0.5, 1.0, 1), (1.0, 2.0, 2), (2.0, 3.0, 1)]
    assert frames[0][2] is None and frames[3][2] is c2


def test_srt_and_ass():
    cues = [Cue(0.15, 1.2, [[Word("Bonjour", 0.15, 0.6)], [Word("France", 0.7, 1.1)]])]
    srt = captions.to_srt(cues)
    assert srt.startswith("1\n00:00:00,150 --> 00:00:01,200\nBonjour\nFrance\n")
    ass = captions.to_ass(cues)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Dialogue: 0,0:00:00.15,0:00:01.20,Karaoke,,0,0,0,,{\\kf55}Bonjour\\N{\\kf50}France" in ass
