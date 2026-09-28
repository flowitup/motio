"""LLM adapter.

- claude_cli: gọi Claude Code trên máy (`claude -p`), tính vào gói Claude của bạn. Tắt công cụ,
  MCP và settings để mỗi lần gọi chỉ tốn vài trăm token hệ thống.
- anthropic: Claude API (ANTHROPIC_API_KEY), dùng khi chạy trên server.
"""
import json
import os
import re
import subprocess
import tempfile

from . import config
from .i18n import tr


class LLMError(RuntimeError):
    pass


def complete(prompt: str, system: str, model: str | None = None, max_tokens: int = 8000,
             effort: str | None = None) -> str:
    provider = config.env("LLM_PROVIDER", "claude_cli")
    model = model or config.env("LLM_MODEL", "sonnet")
    if provider == "claude_cli":
        return _claude_cli(prompt, system, model, effort)
    if provider == "anthropic":
        return _anthropic(prompt, system, model, max_tokens)
    raise LLMError(tr("Unsupported LLM_PROVIDER: {provider}", provider=provider))


def _claude_cli(prompt: str, system: str, model: str, effort: str | None = None) -> str:
    cmd = [config.which("claude"), "-p", "--output-format", "json", "--model", model,
           "--system-prompt", system, "--tools", "", "--strict-mcp-config",
           "--setting-sources", "", "--no-session-persistence"]
    if effort:  # low = trả lời nhanh cho việc đơn giản (dịch tiêu đề, chấm điểm)
        cmd += ["--effort", effort]
    # Không truyền ANTHROPIC_API_KEY: có biến này thì claude -p tính tiền vào tài khoản API thay vì gói Claude.
    # Tắt telemetry và lưu lượng phụ của Claude Code cho các lần gọi tự động.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env.update({"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1",
                "DISABLE_ERROR_REPORTING": "1"})
    with tempfile.TemporaryDirectory() as tmp:  # cwd trống: không nạp CLAUDE.md của repo nào
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900, cwd=tmp, env=env)
    if r.returncode != 0 and not r.stdout.strip():
        raise LLMError(tr("claude -p failed ({code}): {error}", code=r.returncode, error=r.stderr[-800:]))
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(tr("claude -p did not return JSON: {output}", output=r.stdout[-500:])) from e
    if data.get("is_error"):
        raise LLMError(f"claude -p: {data.get('result') or data}")
    return data.get("result") or ""


def _anthropic(prompt: str, system: str, model: str, max_tokens: int) -> str:
    import anthropic
    # Trên API cần model ID đầy đủ; "sonnet" chỉ là tên tắt của Claude Code.
    model_id = config.env("ANTHROPIC_MODEL", "claude-sonnet-5") if model in ("sonnet", "opus", "haiku") else model
    client = anthropic.Anthropic(api_key=config.env("ANTHROPIC_API_KEY") or None)
    msg = client.messages.create(model=model_id, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


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


def ask_json(prompt: str, system: str, model: str | None = None, retries: int = 1, effort: str | None = None):
    last = None
    for _ in range(retries + 1):
        out = complete(prompt, system, model, effort=effort)
        try:
            return parse_json(out)
        except (json.JSONDecodeError, LLMError) as e:
            last = e
            prompt += "\n\nRAPPEL : réponds uniquement avec du JSON valide, sans texte autour."
    raise LLMError(tr("Invalid JSON after {n} attempts: {error}", n=retries + 1, error=last))
