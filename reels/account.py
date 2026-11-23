"""Read-only daily account snapshot for the Humiwell Command Center dashboard.

Writes dashboard/account.json (followers, account numbers, recent posts with their numbers,
trending audio) and keeps one row per UTC date in dashboard/followers.csv. Posts nothing.
"""
import csv
import json
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

from .common import ROOT, load_state, now_utc
from .graph import INVALID_METRIC_CODES, GraphError, _parse_insights, normalise_audio

ACCOUNT_METRICS = ["reach", "views", "profile_views", "accounts_engaged", "total_interactions",
                   "follows_and_unfollows"]
REEL_METRICS = ["views", "reach", "saved", "shares", "likes", "comments", "total_interactions",
                "ig_reels_avg_watch_time"]
OTHER_METRICS = ["views", "reach", "saved", "shares", "likes", "comments"]
MEDIA_FIELDS = ("id,caption,media_type,media_product_type,permalink,timestamp,like_count,"
                "comments_count,thumbnail_url")
MEDIA_LIMIT = 40
AUDIO_LIMIT = 25
CAPTION_MAX = 300
CSV_COLUMNS = ["date", "followers", "media_count", "reach_1d", "views_1d", "profile_views_1d",
               "accounts_engaged_1d", "follows_1d"]


def _short(e):
    if isinstance(e, GraphError):
        return f"code {e.code}: {(e.message or '')[:120]}"
    return f"{type(e).__name__}: {str(e)[:120]}"


def _unix(dt):
    return int(dt.timestamp())


# ---- account insights -------------------------------------------------------
def _follow_split(body):
    """follows_and_unfollows with breakdown follow_type: FOLLOWER = follows, NON_FOLLOWER = unfollows."""
    follows = unfollows = None
    total = None
    for row in body.get("data", []):
        tv = row.get("total_value") or {}
        total = tv.get("value")
        for b in tv.get("breakdowns") or []:
            for r in b.get("results") or []:
                kind = (r.get("dimension_values") or [""])[0]
                if kind == "FOLLOWER":
                    follows = r.get("value")
                elif kind == "NON_FOLLOWER":
                    unfollows = r.get("value")
    net = None
    if follows is not None or unfollows is not None:
        net = (follows or 0) - (unfollows or 0)
    return {"total": total, "follows": follows, "unfollows": unfollows, "net": net}


def account_insights(graph, since, until, label, errors):
    """Account numbers summed over since..until. Metrics Instagram refuses come back as None."""
    path = f"{graph.ig_user_id}/insights"
    base = {"period": "day", "metric_type": "total_value", "since": _unix(since), "until": _unix(until)}
    simple = [m for m in ACCOUNT_METRICS if m != "follows_and_unfollows"]
    out = {"since": since.isoformat(), "until": until.isoformat()}
    try:
        out.update(_parse_insights(graph.get(path, {**base, "metric": ",".join(simple)}), simple))
    except GraphError as e:
        if e.code not in INVALID_METRIC_CODES:
            raise
        for m in simple:
            try:
                out[m] = _parse_insights(graph.get(path, {**base, "metric": m}), [m])[m]
            except GraphError as e1:
                out[m] = None
                errors.append(f"{label}.{m} refused ({_short(e1)})")
    try:
        split = _follow_split(graph.get(path, {**base, "metric": "follows_and_unfollows",
                                                "breakdown": "follow_type"}))
    except GraphError as e:
        split = None
        errors.append(f"{label}.follows_and_unfollows refused ({_short(e)})")
    out["follows_and_unfollows"] = split
    return out


# ---- media ------------------------------------------------------------------
def recent_media(graph, limit=MEDIA_LIMIT):
    items, after = [], None
    while len(items) < limit:
        params = {"fields": MEDIA_FIELDS, "limit": min(25, limit - len(items))}
        if after:
            params["after"] = after
        body = graph.get(f"{graph.ig_user_id}/media", params)
        page = body.get("data") or []
        items += page
        paging = body.get("paging") or {}
        after = (paging.get("cursors") or {}).get("after")
        if not page or not paging.get("next") or not after:
            break
    return items[:limit]


def trial_media_ids(root=ROOT):
    """Media ids the robot posted, from results/*.json and state/state.json."""
    ids = set()
    for p in sorted((Path(root) / "results").glob("*.json")):
        try:
            for v in json.loads(p.read_text(encoding="utf-8")).get("variants", []):
                if v.get("media_id"):
                    ids.add(str(v["media_id"]))
        except (ValueError, OSError, AttributeError):
            continue
    try:
        state = load_state()
    except (ValueError, OSError):
        state = {}
    for day in (state.get("days") or {}).values():
        for v in (day.get("variants") or {}).values():
            if v.get("media_id") and v.get("status") == "posted":
                ids.add(str(v["media_id"]))
    return ids


def media_with_insights(graph, raw, trial_ids, errors):
    refused = {}   # media kind -> metrics Instagram refused for a post whose other numbers worked
    failed, first_error = 0, None
    out = []
    for m in raw:
        is_reel = m.get("media_product_type") == "REELS"
        kind = "reel" if is_reel else "other"
        wanted = [x for x in (REEL_METRICS if is_reel else OTHER_METRICS) if x not in refused.get(kind, set())]
        try:
            numbers = graph.insights(m["id"], wanted)
            if any(numbers.get(k) is not None for k in wanted):
                refused.setdefault(kind, set()).update(k for k in wanted if numbers.get(k) is None)
            numbers = {x: numbers.get(x) for x in (REEL_METRICS if is_reel else OTHER_METRICS)}
        except GraphError as e:
            numbers = None
            failed += 1
            first_error = first_error or _short(e)
        caption = m.get("caption") or ""
        out.append({
            "id": str(m.get("id")),
            "caption": caption[:CAPTION_MAX],
            "media_type": m.get("media_type"),
            "media_product_type": m.get("media_product_type"),
            "permalink": m.get("permalink"),
            "timestamp": m.get("timestamp"),
            "like_count": m.get("like_count"),
            "comments_count": m.get("comments_count"),
            "thumbnail_url": m.get("thumbnail_url"),
            "is_trial": str(m.get("id")) in trial_ids,
            "insights": numbers,
        })
    if failed:
        errors.append(f"media insights failed for {failed} of {len(raw)} posts ({first_error})")
    for kind, metrics in sorted(refused.items()):
        if metrics:
            errors.append(f"media ({kind}) metrics refused: {', '.join(sorted(metrics))}")
    return out


# ---- files ------------------------------------------------------------------
def upsert_csv(path, row):
    rows = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("date") and r["date"] != row["date"]]
    rows.append({k: ("" if row.get(k) is None else row.get(k)) for k in CSV_COLUMNS})
    rows.sort(key=lambda r: r["date"])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def snapshot(graph, cfg, out_dir="dashboard", log=print, root=ROOT):
    """Reads the account and writes the dashboard files. Each section can fail on its own."""
    now = now_utc()
    today = datetime.combine(now.date(), dtime(0), tzinfo=timezone.utc)
    errors = []
    data = {"generated_at": now.isoformat(timespec="seconds"), "profile": None, "account_day": None,
            "follows_1d": None, "account_28d": None, "media": None, "trending_audio": None, "errors": errors}

    try:
        data["profile"] = graph.get(str(graph.ig_user_id),
                                    {"fields": "username,followers_count,follows_count,media_count"})
    except Exception as e:  # noqa: BLE001 - one section failing must not stop the others
        errors.append(f"profile: {_short(e)}")
    try:
        data["account_day"] = account_insights(graph, today - timedelta(days=1), today, "account_day", errors)
        data["follows_1d"] = (data["account_day"].get("follows_and_unfollows") or {}).get("net")
    except Exception as e:  # noqa: BLE001
        errors.append(f"account_day: {_short(e)}")
    try:
        data["account_28d"] = account_insights(graph, today - timedelta(days=28), today, "account_28d", errors)
    except Exception as e:  # noqa: BLE001
        errors.append(f"account_28d: {_short(e)}")
    try:
        data["media"] = media_with_insights(graph, recent_media(graph), trial_media_ids(root), errors)
    except Exception as e:  # noqa: BLE001
        errors.append(f"media: {_short(e)}")
    try:
        body = graph.audio_search_raw("music")
        tracks = body.get("audio") or body.get("data") or []
        data["trending_audio"] = [normalise_audio(a, "music") for a in tracks[:AUDIO_LIMIT]]
    except Exception as e:  # noqa: BLE001
        errors.append(f"trending_audio: {_short(e)}")

    out = Path(out_dir)
    if not out.is_absolute():
        out = Path(root) / out
    out.mkdir(parents=True, exist_ok=True)
    (out / "account.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    profile, day = data["profile"] or {}, data["account_day"] or {}
    upsert_csv(out / "followers.csv", {
        "date": now.date().isoformat(),
        "followers": profile.get("followers_count"),
        "media_count": profile.get("media_count"),
        "reach_1d": day.get("reach"),
        "views_1d": day.get("views"),
        "profile_views_1d": day.get("profile_views"),
        "accounts_engaged_1d": day.get("accounts_engaged"),
        "follows_1d": data["follows_1d"],
    })
    log(f"Account snapshot: {profile.get('followers_count')} followers, "
        f"{len(data['media'] or [])} posts read, {len(errors)} problem(s).")
    for e in errors:
        log(f"  {e}")
    return data
