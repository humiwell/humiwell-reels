"""The dashboard snapshot: reads the account (read-only) and writes dashboard files."""
import csv
import json

from reels import account, common
from tests.fake_graph import FakeGraph


def run(tmp_path, monkeypatch, now, graph=None):
    monkeypatch.setenv("NOW", now)
    graph = graph or FakeGraph()
    data = account.snapshot(graph, {}, out_dir=tmp_path / "dashboard", log=lambda *_: None, root=tmp_path)
    return graph, data


def test_snapshot_writes_json_and_upserts_csv(tmp_path, monkeypatch):
    # m3 was posted by the robot (results file), m5 too (state)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "2026-11-20.json").write_text(json.dumps({"variants": [{"media_id": "m3"}]}))
    monkeypatch.setattr(common, "STATE_FILE", tmp_path / "state.json")
    common.save_state({"days": {"2026-11-21": {"variants": {"A": {"media_id": "m5", "status": "posted"}}}}})

    graph, _ = run(tmp_path, monkeypatch, "2026-11-23T06:45+00:00")
    assert graph.posts == []  # read-only
    data = json.loads((tmp_path / "dashboard" / "account.json").read_text(encoding="utf-8"))
    assert set(data) == {"generated_at", "profile", "account_day", "follows_1d", "account_28d", "media",
                         "trending_audio", "errors"}
    assert data["generated_at"].startswith("2026-11-23T06:45")
    assert data["profile"]["followers_count"] == 1234
    day = data["account_day"]
    assert day["reach"] == 10 and day["views"] == 10 and day["profile_views"] is None
    assert day["since"].startswith("2026-11-22T00:00") and day["until"].startswith("2026-11-23T00:00")
    assert data["follows_1d"] == 5
    assert data["account_28d"]["reach"] == 280
    assert len(data["media"]) == 40
    assert all(len(m["caption"]) == 300 for m in data["media"])
    trial = {m["id"] for m in data["media"] if m["is_trial"]}
    assert trial == {"m3", "m5"}
    reel = data["media"][0]
    assert reel["media_product_type"] == "REELS" and "ig_reels_avg_watch_time" in reel["insights"]
    assert "ig_reels_avg_watch_time" not in data["media"][1]["insights"]
    assert len(data["trending_audio"]) == 25 and data["trending_audio"][0]["title"] == "Song 0"
    assert any("profile_views" in e for e in data["errors"])
    assert "fake" not in json.dumps(data)  # no token

    # same day again replaces the row, a new day adds one
    graph = FakeGraph()
    graph.get = _with_followers(graph, 1300)
    run(tmp_path, monkeypatch, "2026-11-23T09:00+00:00", graph)
    run(tmp_path, monkeypatch, "2026-11-24T06:45+00:00")
    with (tmp_path / "dashboard" / "followers.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["date"] for r in rows] == ["2026-11-23", "2026-11-24"]
    assert rows[0]["followers"] == "1300" and rows[1]["followers"] == "1234"
    assert rows[0]["reach_1d"] == "10" and rows[0]["profile_views_1d"] == "" and rows[0]["follows_1d"] == "5"
    assert list(rows[0]) == account.CSV_COLUMNS


def _with_followers(graph, n):
    real = graph.get

    def get(path, params=None):
        body = real(path, params)
        if path == graph.ig_user_id:
            body["followers_count"] = n
        return body
    return get


def test_one_failing_section_does_not_stop_the_others(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "STATE_FILE", tmp_path / "state.json")
    graph = FakeGraph()
    graph.audio_down = True
    graph.refuse_account = {"reach", "views", "profile_views", "accounts_engaged", "total_interactions",
                            "follows_and_unfollows"}
    _, data = run(tmp_path, monkeypatch, "2026-11-23T06:45+00:00", graph)
    assert data["trending_audio"] is None
    assert any(e.startswith("trending_audio") for e in data["errors"])
    assert data["account_day"]["reach"] is None and data["follows_1d"] is None
    assert data["profile"]["followers_count"] == 1234
    assert len(data["media"]) == 40
