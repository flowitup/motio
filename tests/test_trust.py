"""Engine safety: voice request retries and a news scoring answer that does not match what was asked."""
import base64

import httpx
import pytest

from motio import db, newsnow, tts


class Reply:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.text = "x"

    def json(self):
        return {"audio_base64": base64.b64encode(b"mp3").decode(), "alignment": None}


def _post_sequence(monkeypatch, outcomes):
    calls = []

    def post(url, **kw):
        calls.append(url)
        o = outcomes[len(calls) - 1]
        if isinstance(o, Exception):
            raise o
        return o

    monkeypatch.setattr(tts.httpx, "post", post)
    monkeypatch.setattr(tts.time, "sleep", lambda s: None)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    return calls


def test_voice_request_tries_again_after_a_dropped_connection_and_a_5xx(monkeypatch):
    calls = _post_sequence(monkeypatch, [httpx.ConnectError("down"), Reply(503), Reply(200)])
    assert tts._post_with_retry("http://el/x", {}).status_code == 200
    assert len(calls) == 3


def test_voice_request_never_retries_a_refusal(monkeypatch):
    calls = _post_sequence(monkeypatch, [Reply(401), Reply(200)])
    assert tts._post_with_retry("http://el/x", {}).status_code == 401
    assert len(calls) == 1


def test_voice_request_gives_up_after_three_tries(monkeypatch):
    calls = _post_sequence(monkeypatch, [Reply(500), Reply(500), Reply(502)])
    assert tts._post_with_retry("http://el/x", {}).status_code == 502
    assert len(calls) == 3
    calls = _post_sequence(monkeypatch, [httpx.ReadTimeout("t")] * 3)
    with pytest.raises(httpx.ReadTimeout):
        tts._post_with_retry("http://el/x", {})
    assert len(calls) == 3


def _items(n):
    return [{"id": f"weibo:{i}", "source": "weibo", "rank": i, "title_zh": f"标题{i}", "url": None} for i in range(n)]


def test_news_scoring_accepts_a_wrapped_list_and_skips_unanswered_items(monkeypatch):
    items = _items(3)
    monkeypatch.setattr(newsnow, "fetch", lambda s: items)
    monkeypatch.setattr(newsnow.config, "news_sources", lambda: ["weibo"])
    answer = {"items": [{"id": "weibo:0", "title_fr": "Un", "score": 80},
                        {"id": "weibo:1", "title_fr": "Deux", "score": 40}]}
    monkeypatch.setattr(newsnow.llm, "ask_json", lambda *a, **k: answer)
    out = newsnow.refresh(["weibo"])
    assert out["scored"] == 2
    known = db.known_trend_ids()
    assert "weibo:0" in known and "weibo:1" in known
    assert "weibo:2" not in known  # not saved as score 0: the next refresh scores it
