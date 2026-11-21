import json

import pytest

from tools.prune_releases import load, main, plan


def rel(tag, draft=False, id=None):
    return {"id": id or abs(hash(tag)) % 10**6, "tag_name": tag, "draft": draft}


def tags(out):
    return sorted(x["tag"] for x in out)


def test_keeps_the_three_newest_published_by_version_not_by_string():
    rels = [rel(t) for t in ["v0.7.0", "v0.7.9", "v0.7.10", "v0.7.11", "v0.7.12", "v0.6.0"]]
    assert tags(plan(rels, 3)) == ["v0.6.0", "v0.7.0", "v0.7.9"]


def test_a_draft_in_progress_does_not_count_and_stays():
    rels = [rel("v0.7.26", draft=True), rel("v0.7.24"), rel("v0.7.23"), rel("v0.7.21"), rel("v0.7.20")]
    assert tags(plan(rels, 3)) == ["v0.7.20"]


def test_a_draft_older_than_the_newest_published_is_stale():
    rels = [rel("v0.7.22", draft=True), rel("v0.7.25", draft=True), rel("v0.7.24"), rel("v0.7.23")]
    out = plan(rels, 3)
    assert tags(out) == ["v0.7.22"]
    assert out[0]["draft"] is True


def test_the_latest_release_is_never_deleted():
    rels = [rel(t, id=i) for i, t in enumerate(["v0.7.1", "v0.7.2", "v0.7.3", "v0.7.4"], 1)]
    assert plan(rels, 3, latest_id=1) == []


def test_other_tags_are_ignored_and_few_releases_change_nothing():
    assert plan([rel("nightly"), rel("v1.0.0-rc1"), rel("v0.7.1")], 3) == []


def test_keep_must_be_positive():
    with pytest.raises(ValueError):
        plan([rel("v0.7.1")], 0)


def test_load_reads_several_paginated_arrays(tmp_path):
    f = tmp_path / "r.json"
    f.write_text(json.dumps([rel("v0.1.1")]) + "\n" + json.dumps([rel("v0.1.2")]) + "\n")
    assert [r["tag_name"] for r in load(f)] == ["v0.1.1", "v0.1.2"]


def test_cli_prints_the_plan(tmp_path, capsys):
    f = tmp_path / "r.json"
    f.write_text(json.dumps([rel(f"v0.1.{n}", id=n) for n in range(1, 6)]))
    assert main(["--releases", str(f), "--keep", "3"]) == 0
    assert [x["tag"] for x in json.loads(capsys.readouterr().out)] == ["v0.1.2", "v0.1.1"]
