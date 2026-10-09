"""llm.py: the Anthropic client is faked, so no test needs a key or the network."""
import types

import anthropic
import pytest

from motio import db, llm, settings, usage


class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.msg


def message(text="{\"a\": 1}", stop="end_turn", tin=1000, tout=500):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="thinking", thinking=""), types.SimpleNamespace(type="text", text=text)],
        stop_reason=stop, usage=types.SimpleNamespace(input_tokens=tin, output_tokens=tout,
                                                      cache_creation_input_tokens=0, cache_read_input_tokens=0))


@pytest.fixture
def fake_api(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    sent: list[dict] = []
    box = {"msg": message(), "error": None}

    class FakeClient:
        def __init__(self, **kw):
            sent.append({"client": kw})
            self.messages = self

        def stream(self, **kw):
            sent.append(kw)
            if box["error"]:
                raise box["error"]
            return FakeStream(box["msg"])

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    return sent, box


def test_main_and_fast_models_and_aliases(monkeypatch):
    assert llm.model_for() == "claude-opus-5-5" and llm.model_for(light=True) == "claude-haiku-5-5"
    monkeypatch.setenv("LLM_MODEL", "sonnet")
    monkeypatch.setenv("LLM_MODEL_FAST", "claude-sonnet-5-5")
    assert llm.model_for() == "claude-sonnet-5-5" and llm.model_for(light=True) == "claude-sonnet-5-5"
    assert llm.model_for(model="claude-opus-4-8") == "claude-opus-4-8"


def test_no_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(llm.LLMError, match="ANTHROPIC_API_KEY"):
        llm.complete("hi", "sys")


def test_complete_sends_the_request_and_returns_only_the_text(fake_api):
    sent, _ = fake_api
    assert llm.complete("bonjour", "system text", effort="low") == "{\"a\": 1}"
    req = sent[-1]
    assert req["model"] == "claude-opus-5-5" and req["system"] == "system text"
    assert req["messages"] == [{"role": "user", "content": "bonjour"}]
    assert req["output_config"] == {"effort": "low"} and "thinking" not in req and "temperature" not in req
    assert sent[0]["client"]["api_key"] == "sk-ant-test"


def test_effort_is_not_sent_to_a_model_that_rejects_it(fake_api, monkeypatch):
    sent, _ = fake_api
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-5")
    llm.complete("x", "y", effort="low")
    assert "output_config" not in sent[-1]


def test_ask_json_uses_the_fast_model_for_light_work(fake_api):
    sent, _ = fake_api
    assert llm.ask_json("p", "s", effort="low", light=True) == {"a": 1}
    assert sent[-1]["model"] == "claude-haiku-5-5"


def test_ask_json_asks_again_once_when_the_answer_is_not_json(fake_api):
    sent, box = fake_api
    box["msg"] = message("pas de json")
    with pytest.raises(llm.LLMError, match="Invalid JSON"):
        llm.ask_json("p", "s")
    assert len([s for s in sent if "messages" in s]) == 2
    assert "RAPPEL" in sent[-1]["messages"][0]["content"]


def test_a_cut_answer_fails_at_once_without_asking_again(fake_api):
    sent, box = fake_api
    box["msg"] = message('{"lines": [', stop="max_tokens")
    with pytest.raises(llm.LLMError, match="tokens"):
        llm.ask_json("p", "s")
    assert len([s for s in sent if "messages" in s]) == 1


def test_parse_json_ignores_words_with_braces_after_the_value():
    assert llm.parse_json('Voici : {"a": 1} (fin {de réponse})') == {"a": 1}


def test_refusal_and_empty_truncation_raise(fake_api):
    _, box = fake_api
    box["msg"] = message("", stop="refusal")
    with pytest.raises(llm.LLMError, match="declined"):
        llm.complete("p", "s")
    box["msg"] = message("", stop="max_tokens")
    with pytest.raises(llm.LLMError, match="tokens"):
        llm.complete("p", "s")


def test_api_errors_become_readable_llm_errors(fake_api):
    import httpx
    _, box = fake_api
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(401, request=req)
    box["error"] = anthropic.AuthenticationError("bad", response=resp, body=None)
    with pytest.raises(llm.LLMError, match="refused"):
        llm.complete("p", "s")
    box["error"] = anthropic.APIConnectionError(request=req)
    with pytest.raises(llm.LLMError, match="Could not reach"):
        llm.complete("p", "s")


def test_each_call_is_recorded_with_its_cost_in_the_project(fake_api):
    p = db.create_project(None, "x", "topic")
    before = db.usage_sum(0, project_id=p, kind="llm")[1]
    with usage.context(project_id=p):
        llm.complete("p", "s")  # 1000 in + 500 out on Opus 5.5 = 4 + 10 per 1000 tokens... = $0.014
    assert db.usage_sum(0, project_id=p, kind="llm")[1] - before == pytest.approx(0.014)
    assert usage.for_project(p)["usd"] >= 0.014


def test_price_table_matches_the_model_family():
    assert usage.llm_cost("claude-opus-5-5", 1_000_000, 0) == pytest.approx(4.0)
    assert usage.llm_cost("claude-opus-4-8", 0, 1_000_000) == pytest.approx(25.0)
    assert usage.llm_cost("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.6)
    assert usage.llm_cost("claude-sonnet-5-5", 1_000_000, 0) == pytest.approx(2.0)
    assert usage.llm_cost("claude-unknown-9", 1_000_000, 0) == pytest.approx(3.0)


def test_old_settings_file_with_the_removed_provider_key_still_loads():
    settings.path().write_text('{"LLM_PROVIDER": "claude_cli", "LLM_MODEL": "sonnet"}', encoding="utf-8")
    assert settings.load() == {"LLM_MODEL": "sonnet"}
    assert llm.model_for() == "claude-sonnet-5-5"
