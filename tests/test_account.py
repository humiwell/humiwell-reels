"""The dashboard snapshot: reads the account (read-only) and writes dashboard files."""
import csv
import json
from datetime import datetime, timezone

from reels import account, common
from tests.fake_graph import FakeGraph

NOW = datetime(2026, 11, 23, 6, 45, tzinfo=timezone.utc)


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
    text = (tmp_path / "dashboard" / "account.json").read_text(encoding="utf-8")
    data = json.loads(text)
    assert set(data) == {"generated_at", "profile", "account_day", "follows_1d", "account_28d", "media",
                         "trending_audio", "errors", "daily_days", "media_cached"}
    assert data["generated_at"].startswith("2026-11-23T06:45")
    assert data["profile"]["followers_count"] == 1234
    day = data["account_day"]
    assert day["reach"] == 10 and day["views"] == 10 and day["profile_views"] is None
    assert day["since"].startswith("2026-11-22T00:00") and day["until"].startswith("2026-11-23T00:00")
    assert data["follows_1d"] == 5
    assert data["account_28d"]["reach"] == 280
    assert len(data["media"]) == 40 and data["media_cached"] == 45
    assert all(len(m["caption"]) == 140 for m in data["media"])
    assert "thumbnail_url" not in text
    trial = {m["id"] for m in data["media"] if m["is_trial"]}
    assert trial == {"m3", "m5"}
    reel, feed = data["media"][0], data["media"][1]
    assert reel["media_product_type"] == "REELS" and reel["insights"]["ig_reels_avg_watch_time"] == 100
    assert reel["insights"]["follows"] is None and feed["insights"]["follows"] == 101
    assert feed["insights"]["ig_reels_avg_watch_time"] is None and feed["insights_at"]
    assert len(data["trending_audio"]) == 25 and data["trending_audio"][0]["title"] == "Song 0"
    assert any("profile_views" in e for e in data["errors"])
    assert any(e.startswith("daily.website_clicks refused") for e in data["errors"])
    assert "media (reel) metrics refused: follows" in data["errors"]
    assert data["daily_days"] > 30
    assert "fake" not in text  # no token
    assert "thumbnail_url" not in (tmp_path / "dashboard" / "media.json").read_text(encoding="utf-8")

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

    # the follower curve uses the real snapshot of 2026-11-23 rather than an estimate
    daily = {r["date"]: r for r in json.loads((tmp_path / "dashboard" / "daily.json").read_text())["days"]}
    assert daily["2026-11-24"]["followers"] == 1234 and daily["2026-11-24"]["followers_estimated"] is False
    assert daily["2026-11-23"]["followers"] == 1300 and daily["2026-11-23"]["followers_estimated"] is False
    assert daily["2026-11-22"]["followers"] == 1295 and daily["2026-11-22"]["followers_estimated"] is True


def _with_followers(graph, n):
    real = graph.get

    def get(path, params=None, retries=None):
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
                            "follows_and_unfollows", "website_clicks", "follower_count"}
    _, data = run(tmp_path, monkeypatch, "2026-11-23T06:45+00:00", graph)
    assert data["trending_audio"] is None
    assert any(e.startswith("trending_audio") for e in data["errors"])
    assert data["account_day"]["reach"] is None and data["follows_1d"] is None
    assert data["profile"]["followers_count"] == 1234
    assert len(data["media"]) == 40
    assert data["daily_days"] >= 1


# ---- daily history ----------------------------------------------------------
def _daily(tmp_path, graph, cap, now=NOW):
    out = tmp_path / "dashboard"
    out.mkdir(exist_ok=True)
    errors = []
    account.update_daily(graph, out, now, {"followers_count": 1000}, errors, log=lambda *_: None, cap=cap)
    body = json.loads((out / "daily.json").read_text(encoding="utf-8"))
    return {r["date"]: r for r in body["days"]}, body, errors


def _days_read(graph):
    return {datetime.fromtimestamp(p["since"], timezone.utc).date().isoformat()
            for path, p in graph.reads if path.endswith("/insights") and p.get("metric") != "follower_count"}


def test_backfill_fills_newest_missing_days_and_respects_the_call_cap(tmp_path):
    graph = FakeGraph()
    days, body, errors = _daily(tmp_path, graph, cap=20)
    assert graph.account_calls <= 20
    fetched = sorted((d for d, r in days.items() if r.get("fetched_at")), reverse=True)
    assert fetched[0] == "2026-11-23" and len(fetched) >= 5
    assert fetched == [f"2026-11-{23 - i}" for i in range(len(fetched))]  # newest first, no gaps
    assert body["missing_days"] == 90 - (len(fetched) - 1)
    row = days["2026-11-22"]
    assert row["reach"] == 10 and row["profile_views"] is None and row["website_clicks"] is None
    assert row["follows"] == 7 and row["unfollows"] == 2 and row["net_follows"] == 5
    assert row["new_followers"] == 3 and row["partial"] is False
    assert days["2026-11-23"]["partial"] is True
    assert days["2026-10-26"]["new_followers"] == 3 and not days["2026-10-26"].get("fetched_at")  # series only
    assert any(e.startswith("daily.profile_views refused") for e in errors)
    oldest_first_run = fetched[-1]

    # the next run reads the last days again, skips filled older days and goes further back
    graph = FakeGraph()
    days, body2, _ = _daily(tmp_path, graph, cap=20)
    read = _days_read(graph)
    assert graph.account_calls <= 20
    assert {"2026-11-23", "2026-11-22", "2026-11-21", "2026-11-20"} <= read
    assert oldest_first_run not in read
    assert body2["missing_days"] < body["missing_days"]
    newly = [d for d in read if d < oldest_first_run]
    assert newly and all(days[d].get("fetched_at") for d in newly)


def test_merge_keeps_old_days(tmp_path):
    out = tmp_path / "dashboard"
    out.mkdir()
    (out / "daily.json").write_text(json.dumps({"days": [
        {"date": "2026-01-01", "reach": 5, "fetched_at": "2026-01-02T06:45:00+00:00"},
        {"date": "2026-11-10", "reach": 77, "fetched_at": "2026-11-11T06:45:00+00:00"},
        {"date": "2026-11-21", "reach": 1, "follows": 99, "fetched_at": "2026-11-22T06:45:00+00:00"}]}))
    graph = FakeGraph()
    days, _, _ = _daily(tmp_path, graph, cap=120)
    assert days["2026-01-01"]["reach"] == 5
    assert days["2026-11-10"]["reach"] == 77 and "2026-11-10" not in _days_read(graph)
    assert days["2026-11-21"]["reach"] == 10 and days["2026-11-21"]["follows"] == 7  # re-read (last 3 days)
    assert list(days) == sorted(days)


def test_rate_limit_stops_history_and_keeps_what_we_have(tmp_path):
    out = tmp_path / "dashboard"
    out.mkdir()
    (out / "daily.json").write_text(json.dumps({"days": [{"date": "2026-09-01", "reach": 4, "fetched_at": "x"}]}))
    graph = FakeGraph()
    graph.refuse_account = set()
    graph.rate_limit_after = 7  # follower series + 3 days
    days, _, errors = _daily(tmp_path, graph, cap=120)
    assert graph.account_calls == 8  # stopped at the first refusal
    assert any(e.startswith("daily: stopped after") and "rate limited" in e for e in errors)
    assert days["2026-09-01"]["reach"] == 4
    assert [d for d, r in days.items() if r.get("fetched_at") and d != "2026-09-01"] == \
        ["2026-11-21", "2026-11-22", "2026-11-23"]


def test_follower_estimate_walks_back():
    days = {d: {"date": d, **v} for d, v in {
        "2026-11-23": {"net_follows": 3},
        "2026-11-22": {"net_follows": None, "new_followers": 2},
        "2026-11-21": {"net_follows": None, "new_followers": None},
        "2026-11-20": {"net_follows": 4},
        "2026-11-19": {"net_follows": 1},
        "2026-11-18": {"net_follows": 0},
        "2026-11-16": {"net_follows": 0},  # 2026-11-17 is missing, so the walk cannot reach it
    }.items()}
    account.follower_curve(days, NOW.date(), 100, {"2026-11-19": 80})
    got = {d: (r["followers"], r["followers_estimated"]) for d, r in days.items()}
    assert got == {"2026-11-23": (100, False), "2026-11-22": (97, True), "2026-11-21": (95, True),
                   "2026-11-20": (None, False), "2026-11-19": (80, False), "2026-11-18": (79, True),
                   "2026-11-16": (None, False)}


# ---- media cache ------------------------------------------------------------
def _media(tmp_path, graph, cap):
    out = tmp_path / "dashboard"
    out.mkdir(exist_ok=True)
    errors = []
    account.update_media(graph, out, NOW, set(), errors, log=lambda *_: None, cap=cap)
    text = (out / "media.json").read_text(encoding="utf-8")
    body = json.loads(text)
    return {m["id"]: m for m in body["media"]}, body, errors, text


def _media_read(graph):
    return [path.split("/")[0] for path, _ in graph.reads if path.startswith("m") and path.endswith("/insights")]


def test_media_cache_refreshes_only_young_or_missing(tmp_path):
    out = tmp_path / "dashboard"
    out.mkdir()
    old = {"views": 1, "reach": 1}
    (out / "media.json").write_text(json.dumps({"media": [
        {"id": "m40", "insights": old, "insights_at": "2026-11-01T06:45:00+00:00", "thumbnail_url": "u"},
        {"id": "m2", "insights": old, "insights_at": "2026-11-22T06:45:00+00:00"},
        {"id": "m41", "insights": None, "insights_at": None}]}))
    graph = FakeGraph()
    media, body, errors, text = _media(tmp_path, graph, cap=150)
    read = _media_read(graph)
    assert "m40" not in read and media["m40"]["insights"] == old  # old (39 days) and cached
    assert "m2" in read and media["m2"]["insights"]["views"] == 101  # young: refreshed
    assert "m41" in read and media["m41"]["insights"]["views"] == 140  # old but never fetched
    assert len(media) == 45 and body["pending_insights"] == 0
    assert "thumbnail_url" not in text
    assert all(len(m["caption"]) <= 140 for m in media.values())
    assert media["m1"]["insights"]["follows"] is None and media["m2"]["insights"]["follows"] == 101
    assert "media (reel) metrics refused: follows" in errors


def test_media_cache_respects_the_call_cap_newest_first(tmp_path):
    graph = FakeGraph()
    media, body, _, _ = _media(tmp_path, graph, cap=12)
    read = _media_read(graph)
    assert len(read) <= 12
    done = [m["id"] for m in body["media"] if m["insights_at"]]
    assert done == ["m1", "m2", "m3"]  # m1 costs 10 calls (follows refused for reels), then 1 each
    assert body["pending_insights"] == 42
    # a later run with room fills the rest
    media, body, _, _ = _media(tmp_path, FakeGraph(), cap=150)
    assert body["pending_insights"] == 0 and all(m["insights_at"] for m in media.values())
