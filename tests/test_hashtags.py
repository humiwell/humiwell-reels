"""Hashtag research against a pretend Instagram."""
from reels import hashtags
from reels.graph import GraphError


class FakeGraph:
    ig_user_id = "123"

    def __init__(self, refuse=False):
        self.refuse = refuse
        self.calls = []

    def get(self, path, params=None, retries=3):
        self.calls.append(path)
        if self.refuse:
            raise GraphError(400, 10, None, "Application does not have permission for this action")
        if path == "ig_hashtag_search":
            return {"data": [{"id": "h-" + params["q"]}]}
        if path.endswith("/top_media"):
            return {"data": [
                {"id": "1", "caption": "Fibre hack #guthealth #fibre", "media_type": "VIDEO", "like_count": 10,
                 "comments_count": 1, "permalink": "https://instagram.com/p/1", "timestamp": "2026-11-20T10:00:00+0000"},
                {"id": "2", "caption": "Big one\nmore | text #fibre", "media_type": "IMAGE", "like_count": 500,
                 "comments_count": 40, "permalink": "https://instagram.com/p/2", "timestamp": "2026-11-21T10:00:00+0000"},
            ]}
        if path.endswith("/recent_media"):
            return {"data": [{"id": "3", "caption": "#fibre #ukwellness"}]}
        raise AssertionError(path)


CFG = {"hashtags": {"tags": ["#GutHealth", "fibre"], "top_posts": 5}}


def test_report_ranks_posts_and_lists_related_tags(monkeypatch):
    issues = []
    monkeypatch.setattr(hashtags, "open_issue", lambda *a, **k: issues.append(a[0]))
    text, problems = hashtags.run(CFG, FakeGraph(), dry=True)
    assert problems == []
    assert "## #guthealth" in text and "## #fibre" in text
    guthealth = text.split("## #guthealth")[1]
    assert guthealth.index("Big one") < guthealth.index("Fibre hack")  # higher score first
    assert "more / text" not in text  # only the first line is shown
    assert "#ukwellness" in text


def test_no_permission_stops_early_and_says_so(monkeypatch):
    issues = []
    monkeypatch.setattr(hashtags, "open_issue", lambda *a, **k: issues.append(a[0]))
    monkeypatch.setattr(hashtags, "OUT_DIR", __import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    g = FakeGraph(refuse=True)
    _, problems = hashtags.run(CFG, g)
    assert len(problems) == 1 and len(g.calls) == 1
    assert issues and issues[0].startswith("Hashtag research failed")
