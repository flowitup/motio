"""Kuaishou through the separate videodl program (motio/kuaishou.py): the command, the result file, the failures."""
import json
import subprocess

import pytest

from motio import kuaishou, qa

URL = "https://www.kuaishou.com/short-video/3xh8drz8ugugnrm"


@pytest.fixture
def videodl(monkeypatch):
    """A fake `videodl` command. `state`: what it saves (name → bytes), the calls, an error to raise."""
    state = {"saves": {"KuaishouVideoClient/某个视频.mp4": b"v" * 3000}, "calls": [], "raise": None}

    def run(cmd):
        state["calls"].append(cmd)
        if state["raise"]:
            raise state["raise"]
        work = json.loads(cmd[cmd.index("-c") + 1])[kuaishou.CLIENT]["work_dir"]
        from pathlib import Path
        for name, data in state["saves"].items():
            f = Path(work) / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(kuaishou, "tool", lambda: "/usr/bin/videodl")
    monkeypatch.setattr(kuaishou, "_run", run)
    probed = {"duration": 565.0, "video": {"width": 1440, "height": 1080}, "audio": {}}
    monkeypatch.setattr(qa, "probe", lambda p: probed)
    return state


@pytest.mark.parametrize("url,vid", [(URL, "3xh8drz8ugugnrm"), (URL + "?authorId=1", "3xh8drz8ugugnrm"),
                                     ("https://v.kuaishou.com/AbCdEf", "AbCdEf"), ("https://www.kuaishou.com/", "")])
def test_find_id(url, vid):
    assert kuaishou.find_id(url) == vid


def test_download_runs_only_the_kuaishou_client_and_names_the_file(videodl, tmp_path):
    seen = []
    info = kuaishou.download(URL, tmp_path, [seen.append])
    cmd = videodl["calls"][0]
    assert cmd[:5] == ["/usr/bin/videodl", "-i", URL, "-a", "KuaishouVideoClient"]
    assert "-g" not in cmd  # never the generic parsers that send the link to third-party sites
    assert info == {"path": str(tmp_path / "Kuaishou_3xh8drz8ugugnrm.mp4"), "url": URL, "id": "3xh8drz8ugugnrm",
                    "title": "某个视频", "platform": "Kuaishou", "uploader": "", "uploader_url": "", "upload_date": "",
                    "duration": 565.0, "license": "", "width": 1440, "height": 1080}
    assert (tmp_path / "Kuaishou_3xh8drz8ugugnrm.mp4").read_bytes() == b"v" * 3000
    assert [p.name for p in tmp_path.iterdir()] == ["Kuaishou_3xh8drz8ugugnrm.mp4"]  # the work folder is gone
    assert seen[-1]["status"] == "finished" and seen[-1]["downloaded_bytes"] == 3000


def test_the_biggest_video_is_kept_and_a_second_call_uses_the_file(videodl, tmp_path):
    videodl["saves"] = {"a.mp4": b"x" * 10, "b.mp4": b"y" * 99, "cover.jpg": b"z" * 999}
    kuaishou.download(URL, tmp_path)
    assert (tmp_path / "Kuaishou_3xh8drz8ugugnrm.mp4").read_bytes() == b"y" * 99
    kuaishou.download(URL, tmp_path)
    assert len(videodl["calls"]) == 1


def test_videodl_not_installed_says_how_to_get_it(monkeypatch, tmp_path):
    monkeypatch.setattr(kuaishou, "tool", lambda: None)
    with pytest.raises(kuaishou.Unavailable, match="videodl.*not installed.*add the file"):
        kuaishou.download(URL, tmp_path)


def test_a_link_videodl_cannot_read_says_so(videodl, tmp_path):
    videodl["saves"] = {}
    with pytest.raises(kuaishou.Unavailable, match="could not read this Kuaishou link"):
        kuaishou.download(URL, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_command_that_cannot_run_or_hangs_is_reported(videodl, tmp_path):
    videodl["raise"] = subprocess.TimeoutExpired("videodl", 300)
    with pytest.raises(kuaishou.Unavailable, match="Could not run videodl"):
        kuaishou.download(URL, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_file_that_is_not_a_video_is_refused(videodl, monkeypatch, tmp_path):
    def bad(p):
        raise RuntimeError("moov atom not found")

    monkeypatch.setattr(qa, "probe", bad)
    with pytest.raises(kuaishou.Unavailable, match="not a video"):
        kuaishou.download(URL, tmp_path)
    assert list(tmp_path.iterdir()) == []
