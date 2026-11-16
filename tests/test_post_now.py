"""Post-now requests and short naps: a pushed batch can go out in minutes, never twice."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from reels import common, publish, results
from reels.common import load_config, load_post_now
from tests.fake_graph import FakeGraph
from tests.test_simulation import manifest as broll_manifest, tick_through
from tests.test_talking_head import th_manifest

D = "2026-11-16"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(results, "ROOT", tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg = load_config()
    cfg["dry_run"] = False
    cfg["audio"]["block_ids"] = ["111"]
    return cfg, tmp_path


def at(h, m):
    return datetime(2026, 11, 16, h, m, tzinfo=timezone.utc)


def test_post_now_goes_out_at_once_and_only_once(env):
    cfg, _ = env
    manifests = {D: broll_manifest(D), f"th-{D}": th_manifest(D, audio_id="999")}
    req = [{"id": "2026-11-16T08:20", "batch": f"th-{D}"}]
    state, g = common.load_state(), FakeGraph()
    # 08:20 UK: no talking-head slot is due yet (first is 09:15), but the request posts one now
    publish.run(cfg, state, g, manifests, at(8, 20), lambda *_: None, post_now=req)
    th = [p for p in g.posts if "th-" in p["url"]]
    assert len(th) == 1 and th[0]["audio"]["audio_volume"] == 3
    # the same request on later runs does nothing more
    for minute in (25, 30, 35):
        publish.run(cfg, state, g, manifests, at(8, minute), lambda *_: None, post_now=req)
    assert len([p for p in g.posts if "th-" in p["url"]]) == 1
    # the rest of the day: every version posted exactly once, B-roll untouched (8 posts)
    tick_through(cfg, state, g, manifests, at(8, 40), at(23, 45), lambda *_: None)
    th_urls = [p["url"] for p in g.posts if "th-" in p["url"]]
    assert len(th_urls) == 4 and len(set(th_urls)) == 4
    assert len([p for p in g.posts if "th-" not in p["url"]]) == 8
    assert state["post_now_done"] == ["2026-11-16T08:20"]


def test_post_now_for_unknown_batch_is_ignored(env):
    cfg, _ = env
    state, g, logs = common.load_state(), FakeGraph(), []
    publish.run(cfg, state, g, {}, at(8, 20), logs.append, post_now=[{"id": "x1", "batch": "th-2026-11-16"}])
    assert g.posts == [] and state["post_now_done"] == ["x1"]
    assert any("Ignored" in line for line in logs)


def test_post_now_waits_for_a_future_day(env):
    cfg, _ = env
    manifests = {"th-2026-11-17": th_manifest("2026-11-17")}
    state, g = common.load_state(), FakeGraph()
    publish.run(cfg, state, g, manifests, at(8, 20), lambda *_: None, post_now=[{"id": "x2", "batch": "th-2026-11-17"}])
    assert g.posts == [] and "x2" not in state.get("post_now_done", [])


def test_wake_time_naps_before_the_slot():
    now = at(8, 0)
    assert publish.wake_time(at(9, 15), now, 5) == at(8, 5)
    assert publish.wake_time(at(8, 3), now, 5) == at(8, 3)


def test_request_file_checks(tmp_path, monkeypatch):
    f = tmp_path / "post_now.json"
    monkeypatch.setattr(common, "POST_NOW_FILE", f)
    assert load_post_now() == ([], [])
    f.write_text(json.dumps([{"id": "a", "batch": "th-2026-11-16"}]))
    assert load_post_now()[0] == [{"id": "a", "batch": "th-2026-11-16"}]
    f.write_text(json.dumps([{"id": "a"}]))
    assert load_post_now()[1]
    f.write_text("{not json")
    assert load_post_now()[1]
