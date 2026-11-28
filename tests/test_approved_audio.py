"""B-roll reels only use tracks from audio.approved_ids, rotate by date, and never fall back to trending."""
from reels.common import load_config
from reels.publish import choose_audio
from tests.fake_graph import FakeGraph

LIST = ["900", "901", "902"]


def cfg_with_list():
    cfg = load_config()
    cfg["audio"]["approved_ids"] = list(LIST)
    cfg["audio"]["pin_audio_id"] = ""
    cfg["audio"]["pin_by_date"] = {}
    cfg["audio"]["block_ids"] = ["111"]
    return cfg


def test_rotates_through_the_list_by_date():
    cfg, g = cfg_with_list(), FakeGraph()
    picks = [choose_audio(cfg, g, d, lambda *_: None)["id"] for d in ("2026-11-28", "2026-11-29", "2026-11-30")]
    assert set(picks) == set(LIST)
    assert all(p in LIST for p in picks)


def test_manifest_track_on_the_list_is_used_and_one_off_the_list_is_skipped():
    cfg, g = cfg_with_list(), FakeGraph()
    assert choose_audio(cfg, g, "2026-11-28", lambda *_: None, manifest={"audio_id": "901"})["id"] == "901"
    logs = []
    t = choose_audio(cfg, g, "2026-11-28", logs.append, manifest={"audio_id": "555"})
    assert t["id"] in LIST and t["note"] == "approved list"
    assert any("not on the approved list" in l for l in logs)


def test_refused_tracks_move_to_the_next_one_and_never_to_trending():
    cfg, g = cfg_with_list(), FakeGraph()
    first = choose_audio(cfg, g, "2026-11-28", lambda *_: None)["id"]
    second = choose_audio(cfg, g, "2026-11-28", lambda *_: None, refused=[first])["id"]
    assert second in LIST and second != first
    none_left = choose_audio(cfg, g, "2026-11-28", lambda *_: None, refused=LIST)
    assert none_left["id"] is None  # never the trending "222"


def test_talking_head_and_empty_list_keep_the_old_behaviour():
    cfg, g = cfg_with_list(), FakeGraph()
    assert choose_audio(cfg, g, "2026-11-28", lambda *_: None, kind="talking-head")["id"] == "222"
    cfg["audio"]["approved_ids"] = []
    assert choose_audio(cfg, g, "2026-11-28", lambda *_: None)["id"] == "222"


def test_live_config_uses_robot_track_ids():
    # The app link ids (instagram.com/reels/audio/<id>) were refused on 28 Nov 2026 (2207065).
    ids = load_config()["audio"]["approved_ids"]
    app_link_ids = {"455812557024565", "249449497488410", "305788179957624", "1930837273888588",
                    "1701789246605792", "1830329143809311", "1115846560430696"}
    assert ids and all(i.isdigit() for i in ids) and not set(ids) & app_link_ids
