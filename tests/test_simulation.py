"""Pretends to run the robot every 15 minutes for several days against a fake Instagram."""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from reels import common, publish, results
from reels.common import load_config, slot_times
from tests.fake_graph import FakeGraph

LONDON = ZoneInfo("Europe/London")
IDS = list("ABCDEFGH")


def manifest(d):
    return {"contract_version": 1, "reel": f"reel-{d}", "post_date": d, "caption": "cap",
            "variants": [{"id": i, "lever": f"lever{i}", "hook": f"hook {i}", "file": f"{d}_{i}.mp4",
                          "length_s": 10} for i in IDS]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(results, "ROOT", tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg = load_config()
    cfg["dry_run"] = False
    cfg["audio"]["block_ids"] = ["111"]
    return cfg, tmp_path


def tick_through(cfg, state, graph, manifests, start, end, log):
    t = start
    while t <= end:
        publish.run(cfg, state, graph, manifests, t, log)
        results.run(cfg, state, graph, manifests, t, log)
        t += timedelta(minutes=15)


def test_full_days_post_on_time_with_one_audio(env):
    cfg, tmp = env
    days = ["2026-11-16", "2026-11-17"]
    manifests = {d: manifest(d) for d in days}
    state, graph, logs = common.load_state(), FakeGraph(), []
    start = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
    tick_through(cfg, state, graph, manifests, start, start + timedelta(days=2), logs.append)

    assert len(graph.posts) == 16
    for d in days:
        day = state["days"][d]
        assert all(v["status"] == "posted" for v in day["variants"].values())
        # every version of a reel uses the same track, and blocked track 111 is skipped
        audios = {p["audio"]["audio_id"] for p in graph.posts if d in p["url"]}
        assert audios == {"222"}
        assert all(p["strategy"] == "MANUAL" for p in graph.posts)
        # each post is at (or within 15 min after) its UK slot time
        slots = slot_times(cfg, datetime.fromisoformat(d).date())
        posted = sorted(datetime.fromisoformat(v["posted_at"]) for v in day["variants"].values())
        for s, p in zip(slots, posted):
            assert timedelta(0) <= p - s < timedelta(minutes=15)
    # rotation: the 07:00 slot goes to a different version each day
    assert state["days"][days[0]]["order"][0] != state["days"][days[1]]["order"][0]


def test_summer_time_slots():
    cfg = load_config()
    summer = slot_times(cfg, datetime(2026, 7, 1).date())
    winter = slot_times(cfg, datetime(2026, 12, 1).date())
    assert summer[0].hour == 6 and winter[0].hour == 7  # 07:00 UK in UTC


def test_rerun_is_safe(env):
    cfg, tmp = env
    manifests = {"2026-11-16": manifest("2026-11-16")}
    state, graph = common.load_state(), FakeGraph()
    t = datetime(2026, 11, 16, 7, 5, tzinfo=timezone.utc)
    for _ in range(5):
        publish.run(cfg, state, graph, manifests, t, lambda *_: None)
    assert len(graph.posts) == 1


def test_limit_stops_for_day_and_carries_over(env):
    cfg, tmp = env
    manifests = {d: manifest(d) for d in ["2026-11-16", "2026-11-17"]}
    state, graph, logs = common.load_state(), FakeGraph(limit_after=5), []
    start = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
    tick_through(cfg, state, graph, manifests, start, start + timedelta(hours=23, minutes=45), logs.append)
    assert len(graph.posts) == 5
    assert state["paused_until"] == "2026-11-17"
    graph.limit_after = None
    tick_through(cfg, state, graph, manifests, start + timedelta(days=1), start + timedelta(days=1, hours=23), logs.append)
    left = [v for v in state["days"]["2026-11-16"]["variants"].values() if v["status"] != "posted"]
    assert not left  # yesterday's leftovers went first
    assert len(graph.posts) == 13  # 5 + 8 slots on day two


def test_unfinished_upload_resumes(env):
    cfg, tmp = env
    manifests = {"2026-11-16": manifest("2026-11-16")}
    state, graph = common.load_state(), FakeGraph(busy_first=True)
    t = datetime(2026, 11, 16, 7, 5, tzinfo=timezone.utc)
    publish.run(cfg, state, graph, manifests, t, lambda *_: None)
    assert len(graph.posts) == 0
    graph.containers["c1"]["status"] = "FINISHED"
    publish.run(cfg, state, graph, manifests, t + timedelta(minutes=15), lambda *_: None)
    assert len(graph.posts) == 1 and len(graph.containers) == 1


def test_results_after_72h(env):
    cfg, tmp = env
    manifests = {"2026-11-16": manifest("2026-11-16")}
    state, graph, logs = common.load_state(), FakeGraph(), []
    start = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
    tick_through(cfg, state, graph, manifests, start, start + timedelta(days=3, hours=20), logs.append)
    assert not state["days"]["2026-11-16"]["results_done"]
    tick_through(cfg, state, graph, manifests, start + timedelta(days=3, hours=20),
                 start + timedelta(days=4), logs.append)
    assert state["days"]["2026-11-16"]["results_done"]
    report = json.loads((tmp / "results" / "2026-11-16.json").read_text())
    # fake numbers: later posts have higher watch time, so the last-posted version wins
    assert report["variants"][0]["media_id"] == "m8"
    assert report["variants"][0]["watch_pct"] == pytest.approx(86.0)
    assert (tmp / "results.csv").read_text().count("\n") == 9


def test_audio_refused_whole_reel_goes_without(env, capsys):
    cfg, tmp = env
    manifests = {"2026-11-16": manifest("2026-11-16")}
    state, graph = common.load_state(), FakeGraph(audio_fails=True)
    start = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
    tick_through(cfg, state, graph, manifests, start, start + timedelta(days=1), lambda *_: None)
    assert len(graph.posts) == 8
    assert all(p["audio"] is None for p in graph.posts)
    assert state["days"]["2026-11-16"]["audio"]["tried"]["id"] == "222"
    assert capsys.readouterr().out.count("Trending audio is not attaching") == 1


def test_verdict_rules():
    a = {"reach": 200, "watch_pct": 60, "sends_per_1k": 5}
    b = {"reach": 200, "watch_pct": 49, "sends_per_1k": 9}
    assert results.verdict([a, b], 150, 10)[0]
    assert not results.verdict([a, dict(b, watch_pct=55)], 150, 10)[0]
    assert not results.verdict([a, dict(b, reach=100)], 150, 10)[0]


def test_dry_run_posts_nothing(env):
    cfg, tmp = env
    cfg["dry_run"] = True
    manifests = {"2026-11-16": manifest("2026-11-16")}
    state, graph = common.load_state(), FakeGraph()
    publish.run(cfg, state, graph, manifests, datetime(2026, 11, 16, 12, 5, tzinfo=timezone.utc),
                lambda *_: None)
    assert graph.posts == [] and graph.containers == {}
