"""Engine messages in the UI language (motio/i18n.py): every English message has its Vietnamese."""
import ast
import string
from pathlib import Path

import pytest

from motio import i18n, pipeline, settings, watch
from motio.i18n import VI, tr, tr_n

ENGINE = Path(i18n.__file__).parent


def _literals(node: ast.AST) -> list[str]:
    """String literal(s) a message argument can be: "x", or "a" if c else "b"."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _literals(node.body) + _literals(node.orelse)
    return []


def _messages() -> dict[str, str]:
    """English messages the engine passes to tr() / tr_n() / step labels, with where they are."""
    found: dict[str, str] = {}
    for path in sorted(ENGINE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name == "tr" or name == "step" or (isinstance(f, ast.Call) and getattr(f.func, "id", "") == "Step"):
                args = [node.args[0]]
            elif name == "tr_n":
                args = node.args[1:2]
            else:
                continue
            for arg in args:
                for s in _literals(arg):
                    found.setdefault(s, f"{path.name}:{node.lineno}")
    for s in [*pipeline.STEP_LABELS.values(), *pipeline.REVIEW_STEPS.values(), watch.NOT_A_LIST,
              watch.UNSUPPORTED, watch.BILI_BLOCKED]:
        found.setdefault(s, "constant")
    return found


def _fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f is not None}


def test_every_message_has_vietnamese():
    missing = {s: where for s, where in _messages().items() if s not in VI}
    assert not missing, "add these to motio/i18n.py VI:\n" + "\n".join(f"{w}: {s!r}" for s, w in missing.items())


def test_no_unused_vietnamese():
    unused = set(VI) - set(_messages())
    assert not unused, f"VI entries no code uses (typo, or the English changed): {sorted(unused)}"


def test_vietnamese_keeps_the_fields():
    wrong = {en: vi for en, vi in VI.items() if _fields(en) != _fields(vi)}
    assert not wrong


def test_english_by_default():
    assert i18n.lang() == "en"
    assert tr("Project not found") == "Project not found"
    assert tr("Invalid step: {step}", step="x") == "Invalid step: x"
    assert (tr_n(1, "line"), tr_n(3, "line")) == ("1 line", "3 lines")
    assert (tr_n(1, "box", "boxes"), tr_n(2, "box", "boxes")) == ("1 box", "2 boxes")


def test_vietnamese_when_the_app_says_so():
    settings.update({"UI_LANG": "vi"})
    assert i18n.lang() == "vi"
    assert tr("Project not found") == "Không có dự án này"
    assert tr("Invalid step: {step}", step="x") == "Bước không hợp lệ: x"
    assert (tr_n(1, "line"), tr_n(3, "box", "boxes")) == ("1 dòng", "3 khung")
    assert tr("not in the catalog") == "not in the catalog"  # thiếu bản dịch: giữ tiếng Anh
    settings.update({"UI_LANG": None})
    assert i18n.lang() == "en"


def test_ui_lang_is_validated():
    with pytest.raises(ValueError):
        settings.update({"UI_LANG": "fr"})
    settings.update({"UI_LANG": ""})  # trống = mặc định (tiếng Anh)
    assert i18n.lang() == "en"


def test_api_errors_follow_the_saved_language():
    from fastapi.testclient import TestClient

    from motio import api

    h = {"Authorization": "Bearer t"}
    with TestClient(api.create_app("t")) as c:
        assert c.get("/api/projects/999999", headers=h).json()["detail"] == "Project not found"
        r = c.put("/api/settings", headers=h, json={"UI_LANG": "vi"})
        assert r.status_code == 200 and r.json()["UI_LANG"]["value"] == "vi"
        assert c.get("/api/projects/999999", headers=h).json()["detail"] == "Không có dự án này"
        assert c.put("/api/settings", headers=h, json={"UI_LANG": "de"}).status_code == 400
