"""Talking-head lane: own slots, quiet track under the voice, 2-day results, never blocks B-roll."""
from datetime import datetime, timedelta, timezone

import pytest

from reels import common, publish, results
from reels.common import check_manifest, lane_slot_times, load_config
from tests.fake_graph import FakeGraph
from tests.test_simulation import manifest as broll_manifest, tick_through

D = "2026-11-16"


def th_manifest(d, audio_id=None):
    m = {"contract_version": 1, "kind": "talking-head", "reel": "iron-twice", "post_date": d, "caption": "cap",
         "variants": [{"id": i, "lever": f"lever{i}", "hook": f"hook {i}", "file": f"{d}_{i}.mp4",
                       "length_s": 54} for i in "ABCD"]}
    if audio_id:
        m.update(audio_id=audio_id, audio_title="Song (Artist)")
    return m


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(results, "ROOT", tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg = load_config()
    cfg["dry_run"] = False
    cfg["audio"]["block_ids"] = ["111"]
    return cfg


def test_both_lanes_post_on_their_own_slots(env):
    cfg = env
    manifests = {D: broll_manifest(D), f"th-{D}": th_manifest(D, audio_id="999")}
    state, graph, logs = common.load_state(), FakeGraph(), []
    start = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
    tick_through(cfg, state, graph, manifests, start, start + timedelta(days=1), logs.append)

    assert len(graph.posts) == 12
    th = [p for p in graph.posts if "th-" in p["url"]]
    br = [p for p in graph.posts if "th-" not in p["url"]]
    assert len(th) == 4 and len(br) == 8
    # talking head: one pinned track for all 4, quiet under the voice
    assert {(p["audio"]["audio_id"], p["audio"]["audio_volume"], p["audio"]["video_volume"]) for p in th} == {("999", 3, 100)}
    # B-roll keeps its own settings (silent video, full-volume track)
    assert {(p["audio"]["audio_volume"], p["audio"]["video_volume"]) for p in br} == {(100, 0)}
    assert all(p["url"].endswith(".mp4") and "/day-th-2026-11-16/" in p["url"] for p in th)
    # each talking-head post is within 15 min after its own slot
    slots = lane_slot_times(cfg, "talking-head", datetime.fromisoformat(D).date())
    posted = sorted(datetime.fromisoformat(v["posted_at"]) for v in state["days"][f"th-{D}"]["variants"].values())
    for s, p in zip(slots, posted):
        assert timedelta(0) <= p - s < timedelta(minutes=15)
    assert state["days"][f"th-{D}"]["kind"] == "talking-head"


def test_talking_head_audio_refusal_never_blocks_broll(env, capsys):
    cfg = env
    manifests = {D: broll_manifest(D), f"th-{D}": th_manifest(D)}
    state, graph, logs = common.load_state(), FakeGraph(refuse_with_voice=True), []
    start = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
    tick_through(cfg, state, graph, manifests, start, start + timedelta(hours=23), logs.append)

    assert len(graph.posts) == 8 and all("th-" not in p["url"] for p in graph.posts)
    assert all(v["status"] == "pending" for v in state["days"][f"th-{D}"]["variants"].values())
    assert state.get("th_audio_retry_after") and not state.get("audio_retry_after")
    assert "Talking-head audio is not attaching" in capsys.readouterr().out


def test_talking_head_results_after_two_days(env):
    cfg = env
    due_th = results.issue_due(cfg, f"th-{D}")
    due_br = results.issue_due(cfg, D)
    assert due_th.date().isoformat() == "2026-11-18" and due_br.date().isoformat() == "2026-11-19"
    manifests = {f"th-{D}": th_manifest(D, audio_id="999")}
    state, graph = common.load_state(), FakeGraph()
    start = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
    tick_through(cfg, state, graph, manifests, start, start + timedelta(days=2, hours=18), lambda *_: None)
    assert state["days"][f"th-{D}"]["results_done"]
    import json
    report = json.loads((results.ROOT / "results" / f"th-{D}.json").read_text())
    assert report["kind"] == "talking-head" and report["post_date"] == D and len(report["variants"]) == 4


def test_folder_names():
    check_manifest(th_manifest(D), f"th-{D}")
    with pytest.raises(ValueError):
        check_manifest(th_manifest(D), D)
    with pytest.raises(ValueError):
        check_manifest(broll_manifest(D), f"th-{D}")
    bad = dict(th_manifest(D), kind="podcast")
    with pytest.raises(ValueError):
        check_manifest(bad, f"th-{D}")
