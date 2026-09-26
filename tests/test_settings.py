import pytest

from motio import config, settings


def test_mask():
    assert settings.mask("") == ""
    assert settings.mask("short") == "••••"
    assert settings.mask("sk-abcdef1234") == "••••1234"


def test_secrets_are_masked_and_env_is_layered(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-secret-9876")
    monkeypatch.setenv("LLM_MODEL", "opus")
    pub = settings.public()
    assert pub["ELEVENLABS_API_KEY"] == {"value": "••••9876", "secret": True, "source": "env"}
    assert pub["LLM_MODEL"]["value"] == "opus"
    assert pub["ANTHROPIC_API_KEY"]["source"] == "default"


def test_update_overrides_env_at_call_time(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "opus")
    settings.update({"LLM_MODEL": "haiku", "CREDIT_ON_VIDEO": True})
    assert config.env("LLM_MODEL") == "haiku"
    assert config.flag("CREDIT_ON_VIDEO") is True
    settings.update({"LLM_MODEL": None})  # xoá ghi đè → quay về .env
    assert config.env("LLM_MODEL") == "opus"


def test_masked_value_is_not_saved(monkeypatch):
    settings.update({"ELEVENLABS_API_KEY": "real-key-5555"})
    settings.update({"ELEVENLABS_API_KEY": "••••5555"})
    assert config.env("ELEVENLABS_API_KEY") == "real-key-5555"


def test_empty_string_disables_env_value(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-secret-9876")
    settings.update({"ELEVENLABS_API_KEY": ""})
    assert config.env("ELEVENLABS_API_KEY") == ""


def test_update_rejects_unknown_and_bad_values():
    with pytest.raises(KeyError):
        settings.update({"NOPE": "1"})
    with pytest.raises(ValueError):
        settings.update({"MAX_VIDEOS_PER_DAY": "abc"})
    settings.update({"MAX_VIDEOS_PER_DAY": 3})
    assert config.max_videos_per_day() == 3


def test_refresh_interval_and_newsnow_url(monkeypatch):
    assert config.refresh_every_min() == 0
    assert config.newsnow_url() == config.DEFAULT_NEWSNOW
    monkeypatch.setenv("NEWSNOW_URL", "http://newsnow:4444/")
    assert config.newsnow_url() == "http://newsnow:4444"
    settings.update({"REFRESH_EVERY_MIN": "30"})
    assert config.refresh_every_min() == 30
    with pytest.raises(ValueError):
        settings.update({"REFRESH_EVERY_MIN": "-5"})


def test_put_ffmpeg_on_path(monkeypatch, tmp_path):
    exe = tmp_path / "ffmpeg"
    exe.write_text("")
    monkeypatch.setenv("MOTIO_FFMPEG", str(exe))
    monkeypatch.setenv("PATH", "/usr/bin")
    config.put_ffmpeg_on_path()
    config.put_ffmpeg_on_path()
    assert config.os.environ["PATH"].split(config.os.pathsep) == [str(tmp_path), "/usr/bin"]
