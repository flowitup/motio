"""LLM adapter: every call goes to the Anthropic API (Messages API, `ANTHROPIC_API_KEY` in Settings or .env).

Two tiers, both set in Settings: `LLM_MODEL` (scripts, translations, scene writing; default Claude Opus 5.5) and
`LLM_MODEL_FAST` (scoring and picking, many small calls; default Claude Haiku 5.5). Each call is recorded in the
`usage` table with its token cost (`usage.record_llm`), so Stats shows what Claude costs next to the voice.
Short names (`sonnet`, `opus`, `haiku`) from older settings still work.
"""
import json
import re

from . import config
from .i18n import tr

MAIN_MODEL = "claude-opus-5-5"
FAST_MODEL = "claude-haiku-5-5"
ALIASES = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Models that take `output_config.effort`; older ones (Haiku 4.5, Sonnet 4.5, ...) answer 400 to it.
_EFFORT_MODELS = re.compile(r"^claude-(?:(?:opus|sonnet|haiku|fable|mythos)-5|opus-4-[5-8]|sonnet-4-6)")
MAX_TOKENS = 16000  # thinking is on by default on the 5.x models and counts inside this budget


class LLMError(RuntimeError):
    pass


def model_for(light: bool = False, model: str | None = None) -> str:
    name = (model or config.env("LLM_MODEL_FAST" if light else "LLM_MODEL", "") or "").strip()
    if not name:
        return FAST_MODEL if light else MAIN_MODEL
    return ALIASES.get(name.lower(), name)


def complete(prompt: str, system: str, model: str | None = None, max_tokens: int = MAX_TOKENS,
             effort: str | None = None, light: bool = False) -> str:
    import anthropic

    key = (config.env("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise LLMError(tr("No Anthropic API key: add ANTHROPIC_API_KEY in Settings"))
    model_id = model_for(light, model)
    args: dict = {"model": model_id, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": prompt}]}
    if effort in EFFORTS and _EFFORT_MODELS.match(model_id):
        args["output_config"] = {"effort": effort}
    client = anthropic.Anthropic(api_key=key, max_retries=4, timeout=240.0)  # a hung call must not block the queue
    try:
        with client.messages.stream(**args) as stream:  # streaming: a long answer never hits the request timeout
            msg = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise LLMError(tr("The Anthropic API key was refused: check ANTHROPIC_API_KEY in Settings")) from e
    except anthropic.PermissionDeniedError as e:
        raise LLMError(tr("The Anthropic API key cannot use {model}", model=model_id)) from e
    except anthropic.NotFoundError as e:
        raise LLMError(tr("Unknown Claude model: {model}", model=model_id)) from e
    except anthropic.RateLimitError as e:
        raise LLMError(tr("Anthropic API rate limit reached: try again in a minute")) from e
    except anthropic.APIConnectionError as e:
        raise LLMError(tr("Could not reach the Anthropic API: check the internet connection")) from e
    except anthropic.APIStatusError as e:
        raise LLMError(tr("Anthropic API error {code}: {error}", code=e.status_code, error=e.message)) from e
    _record(model_id, msg)
    if msg.stop_reason == "refusal":
        raise LLMError(tr("Claude declined this request: change the topic or the source and try again"))
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if msg.stop_reason == "max_tokens" and not text.strip():
        raise LLMError(tr("Claude ran out of tokens before answering"))
    return text


def _record(model: str, msg) -> None:
    from . import usage  # imported here: usage -> channels -> topic -> llm

    u = getattr(msg, "usage", None)
    if u is not None:
        usage.record_llm(model, u.input_tokens or 0, u.output_tokens or 0,
                         getattr(u, "cache_creation_input_tokens", 0) or 0,
                         getattr(u, "cache_read_input_tokens", 0) or 0)


def parse_json(text: str):
    """Lấy JSON đầu tiên trong câu trả lời (chịu được ```json … ``` và lời dẫn)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise LLMError(tr("No JSON found in the reply: {text}", text=text[:300]))
    s = min(starts)
    closer = "}" if text[s] == "{" else "]"
    e = text.rfind(closer)
    return json.loads(text[s:e + 1])


def ask_json(prompt: str, system: str, model: str | None = None, retries: int = 1, effort: str | None = None,
             light: bool = False):
    last = None
    for _ in range(retries + 1):
        out = complete(prompt, system, model, effort=effort, light=light)
        try:
            return parse_json(out)
        except (json.JSONDecodeError, LLMError) as e:
            last = e
            prompt += "\n\nRAPPEL : réponds uniquement avec du JSON valide, sans texte autour."
    raise LLMError(tr("Invalid JSON after {n} attempts: {error}", n=retries + 1, error=last))
