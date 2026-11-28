"""Notion rows get Status "Posted" once the first version of a day is posted, and the winner once results are in."""
from datetime import datetime, timedelta, timezone

from reels import common, notion, results
from reels.common import load_config
from tests.fake_graph import FakeGraph
from tests.test_simulation import manifest, tick_through

REELS = "396a51a3-46ad-49e7-945d-e6d69fcf7253"
TH = "419f6635-23bd-816f-bb0f-000b800d400d"
REELS_SCHEMA = {"Status": {"type": "select"}, "Winner": {"type": "select"}, "Winner hook": {"type": "rich_text"},
                "Winner link": {"type": "url"}, "Winner note": {"type": "rich_text"}, "Hook": {"type": "title"}}
TH_SCHEMA = {"Status": {"type": "select"}, "Winner": {"type": "select"}}


class FakeNotion:
    def __init__(self, rows=None, fail=None):
        self.rows = rows or {}   # (data_source, date) -> [page, ...]
        self.updates = []
        self.queries = []
        self.fail = fail

    def schema(self, ds):
        return REELS_SCHEMA if ds == REELS else TH_SCHEMA

    def rows_on(self, ds, day):
        self.queries.append((ds, day))
        if self.fail:
            raise notion.NotionError(self.fail)
        return self.rows.get((ds, day), [])

    def update(self, page, props):
        self.updates.append((page, props))


def page(pid, status="Approved"):
    return {"id": pid, "properties": {"Status": {"type": "select", "select": {"name": status}}}}


def four(d):
    m = manifest(d)
    m["variants"] = [v for v in m["variants"] if v["id"] in "ABFC"]
    return m


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(results, "ROOT", tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg = load_config()
    cfg["dry_run"] = False
    cfg["talking_head"]["enabled"] = False
    cfg["song"]["enabled"] = False
    cfg["audio"]["approved_ids"] = []
    cfg["notion"]["start_date"] = "2026-11-01"
    return cfg


def test_broll_day_posted_then_winner(tmp_path, monkeypatch):
    cfg = setup(tmp_path, monkeypatch)
    D = "2026-11-29"
    manifests = {D: four(D)}
    state, graph = common.load_state(), FakeGraph()
    fake = FakeNotion({(REELS, "2026-12-02"): [page("p" * 32)]})
    start = datetime(2026, 11, 29, 0, 0, tzinfo=timezone.utc)

    # Before 08:00 nothing is live, so nothing is written.
    tick_through(cfg, state, graph, manifests, start, start + timedelta(hours=7), lambda *_: None)
    notion.run(cfg, state, manifests, client=fake, log=lambda *_: None)
    assert fake.updates == []

    # Once the first version (08:00) is live the row (dated trial + 3) is set to Posted, once only,
    # even though three versions are still to post.
    tick_through(cfg, state, graph, manifests, start + timedelta(hours=7), start + timedelta(hours=9), lambda *_: None)
    assert any(v["status"] == "pending" for v in state["days"][D]["variants"].values())
    notion.run(cfg, state, manifests, client=fake, log=lambda *_: None)
    tick_through(cfg, state, graph, manifests, start + timedelta(hours=9), start + timedelta(hours=23), lambda *_: None)
    notion.run(cfg, state, manifests, client=fake, log=lambda *_: None)
    assert fake.queries == [(REELS, "2026-12-02")]
    assert fake.updates == [("p" * 32, {"Status": {"select": {"name": "Posted"}}})]

    # The winner issue (3 days later at 17:00) adds the winner, hook, link and note.
    tick_through(cfg, state, graph, manifests, start + timedelta(hours=23), start + timedelta(days=3, hours=18),
                 lambda *_: None)
    assert state["days"][D]["results_done"]
    notion.run(cfg, state, manifests, client=fake, log=lambda *_: None)
    assert len(fake.updates) == 2
    pid, props = fake.updates[1]
    assert pid == "p" * 32
    assert props["Winner"]["select"]["name"] in "ABFC"
    assert props["Winner hook"]["rich_text"][0]["text"]["content"].startswith("hook ")
    assert "Winner note" in props and "Status" not in props
    assert state["days"][D]["notion"]["winner"] == props["Winner"]["select"]["name"]
    notion.run(cfg, state, manifests, client=fake, log=lambda *_: None)
    assert len(fake.updates) == 2  # never written twice


def test_manifest_notion_page_wins_and_untouched_before_start(tmp_path, monkeypatch):
    cfg = setup(tmp_path, monkeypatch)
    cfg["notion"]["start_date"] = "2026-11-28"
    old, new = "2026-11-20", "2026-11-29"
    manifests = {old: four(old), new: dict(four(new), notion_page="https://www.notion.so/Reel-" + "ab" * 16)}
    state = {"days": {d: {"variants": {i: {"status": "posted"} for i in "ABFC"}} for d in (old, new)}}
    fake = FakeNotion()
    notion.run(cfg, state, manifests, client=fake, log=lambda *_: None)
    assert fake.queries == []  # page id taken from the manifest; the old day is left alone
    assert fake.updates == [("ab" * 16, {"Status": {"select": {"name": "Posted"}}})]
    assert "notion" not in state["days"][old]


def test_two_rows_on_a_date_picks_the_approved_one(tmp_path, monkeypatch):
    cfg = setup(tmp_path, monkeypatch)
    D = "2026-11-29"
    state = {"days": {D: {"variants": {i: {"status": "posted"} for i in "AB"}}}}
    fake = FakeNotion({(REELS, "2026-12-02"): [page("1" * 32, "Not approved"), page("2" * 32, "Approved")]})
    notion.run(cfg, state, {D: four(D)}, client=fake, log=lambda *_: None)
    assert fake.updates[0][0] == "2" * 32


def test_problems_never_raise_and_issue_once(tmp_path, monkeypatch):
    cfg = setup(tmp_path, monkeypatch)
    issues = []
    monkeypatch.setattr(notion, "open_issue", lambda title, body, dry: issues.append(title))
    D = "2026-11-29"
    state = {"days": {D: {"variants": {i: {"status": "posted"} for i in "AB"}}}}
    fake = FakeNotion(fail="HTTP 404: Could not find data source")
    for _ in range(3):
        notion.run(cfg, state, {D: four(D)}, client=fake, log=lambda *_: None)
    assert issues == [f"Notion not updated for {D}"]
    assert not state["days"][D]["notion"].get("posted")
    fake.fail = None
    fake.rows = {(REELS, "2026-12-02"): [page("3" * 32)]}
    notion.run(cfg, state, {D: four(D)}, client=fake, log=lambda *_: None)
    assert state["days"][D]["notion"]["posted"] and "error" not in state["days"][D]["notion"]


def test_talking_head_uses_trial_date_and_song_gets_no_winner(tmp_path, monkeypatch):
    cfg = setup(tmp_path, monkeypatch)
    th, song = "th-2026-11-30", "song-2026-11-30"
    state = {"days": {th: {"variants": {"A": {"status": "posted"}, "B": {"status": "skipped"}}},
                      song: {"variants": {"A": {"status": "posted"}}, "results_done": True}}}
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / f"{song}.json").write_text('{"winner": "A", "variants": [{"variant": "A"}]}')
    fake = FakeNotion({(TH, "2026-11-30"): [page("4" * 32)],
                       ("41bf6635-23bd-8168-aac1-000b28cdafb6", "2026-11-30"): [page("5" * 32)]})
    notion.run(cfg, state, {}, client=fake, log=lambda *_: None)
    assert sorted(p for p, _ in fake.updates) == ["4" * 32, "5" * 32]
    assert all(list(props) == ["Status"] for _, props in fake.updates)


def test_dry_run_and_no_token_write_nothing(tmp_path, monkeypatch):
    cfg = setup(tmp_path, monkeypatch)
    D = "2026-11-29"
    state = {"days": {D: {"variants": {"A": {"status": "posted"}}}}}
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    notion.run(cfg, state, {}, log=lambda *_: None)  # no token: quietly skipped
    cfg["dry_run"] = True
    fake = FakeNotion({(REELS, "2026-12-02"): [page("6" * 32)]})
    notion.run(cfg, state, {}, client=fake, log=lambda *_: None)
    assert fake.updates == [] and not state["days"][D]["notion"].get("posted")


def test_page_id_from_links():
    assert notion.page_id("https://www.notion.so/Hair-reel-" + "c" * 32 + "?pvs=4") == "c" * 32
    assert notion.page_id("cccccccc-cccc-cccc-cccc-cccccccccccc") == "c" * 32
    assert notion.page_id("nope") is None
