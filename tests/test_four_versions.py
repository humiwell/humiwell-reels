"""B-roll days with 4 versions post at slots_4_versions, spread over the day; 8-version days keep the 8 slots."""
from datetime import datetime, timedelta, timezone

from reels import common, results
from reels.common import lane_slot_times, load_config
from tests.fake_graph import FakeGraph
from tests.test_simulation import manifest, tick_through


def four(d):
    m = manifest(d)
    m["variants"] = [v for v in m["variants"] if v["id"] in "ABFC"]
    return m


def test_four_version_day_uses_spread_slots(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(results, "ROOT", tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg = load_config()
    cfg["dry_run"] = False
    cfg["talking_head"]["enabled"] = False
    cfg["song"]["enabled"] = False
    D4, D8 = "2026-11-27", "2026-11-26"
    manifests = {D8: manifest(D8), D4: four(D4)}
    state, graph, logs = common.load_state(), FakeGraph(), []
    start = datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc)
    tick_through(cfg, state, graph, manifests, start, start + timedelta(days=2), logs.append)

    assert len(graph.posts) == 12
    day4 = lane_slot_times(cfg, "broll", datetime.fromisoformat(D4).date(), manifests)
    assert [t.astimezone(common.local_tz(cfg)).strftime("%H:%M") for t in day4] == cfg["slots_4_versions"]
    posted = sorted(datetime.fromisoformat(v["posted_at"]) for v in state["days"][D4]["variants"].values())
    assert len(posted) == 4
    for s, p in zip(day4, posted):
        assert timedelta(0) <= p - s < timedelta(minutes=15)
    assert len(lane_slot_times(cfg, "broll", datetime.fromisoformat(D8).date(), manifests)) == 8
    assert all(v["status"] == "posted" for v in state["days"][D8]["variants"].values())
