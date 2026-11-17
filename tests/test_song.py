"""Song lane: one version a day, its own slot, the song is the only sound (no track added)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from reels import common, results
from reels.common import check_manifest, key_date, key_kind, lane, lane_slot_times, load_config
from tests.fake_graph import FakeGraph
from tests.test_simulation import manifest as broll_manifest, tick_through
from tests.test_talking_head import th_manifest

D = "2026-11-22"


def song_manifest(d, **extra):
    m = {"contract_version": 1, "kind": "song", "reel": "seven-cubes", "post_date": d, "caption": "cap",
         "variants": [{"id": "A", "lever": "song", "hook": "Seven Cubes",
                       "file": f"{d}_seven-cubes.mp4", "length_s": 69.3}]}
    m.update(extra)
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


def test_keys():
    assert key_kind(f"song-{D}") == "song" and key_date(f"song-{D}") == D
    assert key_kind(f"th-{D}") == "talking-head" and key_kind(D) == "broll"


def test_song_posts_once_at_its_slot_with_its_own_sound(env):
    cfg = env
    manifests = {D: broll_manifest(D), f"th-{D}": th_manifest(D, audio_id="999"), f"song-{D}": song_manifest(D)}
    state, graph, logs = common.load_state(), FakeGraph(), []
    start = datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc)
    tick_through(cfg, state, graph, manifests, start, start + timedelta(days=1), logs.append)

    songs = [p for p in graph.posts if "/day-song-" in p["url"]]
    assert len(songs) == 1
    assert songs[0]["audio"] is None  # no audio_configuration: Instagram keeps the video's own sound
    assert songs[0]["strategy"] == "MANUAL"  # still a trial reel
    # the other lanes are untouched
    assert len([p for p in graph.posts if "/day-th-" in p["url"]]) == 4
    assert len([p for p in graph.posts if f"/day-{D}/" in p["url"]]) == 8
    slot = lane_slot_times(cfg, "song", datetime.fromisoformat(D).date())[0]
    posted = datetime.fromisoformat(state["days"][f"song-{D}"]["variants"]["A"]["posted_at"])
    assert timedelta(0) <= posted - slot < timedelta(minutes=15)
    assert state["days"][f"song-{D}"]["kind"] == "song"


def test_song_never_waits_for_audio(env):
    cfg = env
    manifests = {f"song-{D}": song_manifest(D)}
    state, graph = common.load_state(), FakeGraph(audio_fails=True)
    start = datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc)
    tick_through(cfg, state, graph, manifests, start, start + timedelta(days=1), lambda *_: None)
    assert len(graph.posts) == 1 and not state.get("song_audio_retry_after")


def test_song_scorecard_issue(env, capsys):
    cfg = env
    assert results.issue_due(cfg, f"song-{D}").date().isoformat() == "2026-11-24"
    manifests = {f"song-{D}": song_manifest(D)}
    state, graph = common.load_state(), FakeGraph()
    start = datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc)
    tick_through(cfg, state, graph, manifests, start, start + timedelta(days=2, hours=18), lambda *_: None)
    assert state["days"][f"song-{D}"]["results_done"]
    report = json.loads((results.ROOT / "results" / f"song-{D}.json").read_text())
    assert report["kind"] == "song" and len(report["variants"]) == 1
    out = capsys.readouterr().out
    assert f"Song results {D} (seven-cubes)" in out and "Share to followers" in out


def test_song_manifest_rules():
    check_manifest(song_manifest(D), f"song-{D}")
    with pytest.raises(ValueError):
        check_manifest(song_manifest(D), D)
    with pytest.raises(ValueError):
        check_manifest(song_manifest(D, audio_id="123"), f"song-{D}")
    two = song_manifest(D)
    two["variants"] = two["variants"] * 2
    with pytest.raises(ValueError):
        check_manifest(two, f"song-{D}")


def test_song_lane_settings(env):
    L = lane(env, "song")
    assert L["audio"] is False and L["slots"] == ["18:30"]
