"""Read-only daily account snapshot for the Humiwell Command Center dashboard.

Writes, in dashboard/:
- account.json   followers, yesterday and 28-day account numbers, newest 40 posts, trending audio
- followers.csv  one real follower count per UTC date (taken when the snapshot runs)
- daily.json     one row per UTC day (last 90 days, kept forever) for period views and comparisons
- media.json     up to 300 recent posts with their numbers (old posts keep their cached numbers)
Posts nothing. Each section can fail on its own; problems go to "errors" in account.json.
"""
import csv
import json
from datetime import date as ddate, datetime, time as dtime, timedelta, timezone
from pathlib import Path

from .common import ROOT, load_state, now_utc
from .graph import INVALID_METRIC_CODES, GraphError, _parse_insights, normalise_audio

ACCOUNT_METRICS = ["reach", "views", "profile_views", "accounts_engaged", "total_interactions",
                   "follows_and_unfollows"]
AUDIO_LIMIT = 25
CSV_COLUMNS = ["date", "followers", "media_count", "reach_1d", "views_1d", "profile_views_1d",
               "accounts_engaged_1d", "follows_1d"]

# daily history (daily.json)
HISTORY_DAYS = 90          # keep the last 90 days filled
REFETCH_DAYS = 3           # numbers settle late, so the last 3 days (and today) are read again every run
HISTORY_CALL_CAP = 120     # Graph calls per run for the history; older missing days wait for later runs
DAILY_METRICS = ["reach", "views", "profile_views", "accounts_engaged", "total_interactions", "website_clicks"]
DAY_FIELDS = ["date"] + DAILY_METRICS[:5] + ["follows", "unfollows", "net_follows", "new_followers",
                                             "website_clicks", "followers", "followers_estimated"]
UNAVAILABLE_STREAK = 3     # this many old days in a row with no data: stop going further back this run

# media cache (media.json)
MEDIA_FIELDS = "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count"
MEDIA_CACHE_MAX = 300
MEDIA_PAGE = 50
MEDIA_REFRESH_DAYS = 14    # younger posts get fresh numbers every run, older ones keep cached numbers
MEDIA_CALL_CAP = 150       # insight calls per run, newest first
MEDIA_METRICS = ["views", "reach", "saved", "shares", "likes", "comments", "total_interactions",
                 "ig_reels_avg_watch_time", "follows"]
REEL_ONLY = {"ig_reels_avg_watch_time"}
DASHBOARD_MEDIA = 40       # posts copied into account.json
CAPTION_MAX = 140

RATE_LIMIT_CODES = {4, 17, 32, 613}


class RateLimited(Exception):
    pass


class Unavailable(Exception):
    """Instagram refused every metric for this day or post."""


def _short(e):
    if isinstance(e, GraphError):
        return f"code {e.code}: {(e.message or '')[:120]}"
    return f"{type(e).__name__}: {str(e)[:120]}"


def _unix(dt):
    return int(dt.timestamp())


def _midnight(d):
    return datetime.combine(d, dtime(0), tzinfo=timezone.utc)


def _parse_time(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        return None


def _read_json(path, key):
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        return [r for r in body.get(key) or [] if isinstance(r, dict)]
    except (OSError, ValueError, AttributeError):
        return []


def _write_json(path, body):
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


class Budget:
    """Counts Graph calls for one section and turns rate-limit errors into RateLimited."""

    def __init__(self, graph, cap):
        self.graph, self.cap, self.used = graph, cap, 0

    def left(self):
        return self.cap - self.used

    def get(self, path, params):
        self.used += 1
        try:
            return self.graph.get(path, params, retries=1)
        except GraphError as e:
            if e.code in RATE_LIMIT_CODES:
                raise RateLimited(f"rate limited ({_short(e)})") from e
            raise


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


# ---- daily history ----------------------------------------------------------
def _fetch_day(budget, graph, day, now, seen, errors):
    """One UTC day of account numbers. `seen` remembers refused metrics for the rest of this run."""
    path = f"{graph.ig_user_id}/insights"
    since = _midnight(day)
    until = min(since + timedelta(days=1), now)
    base = {"period": "day", "metric_type": "total_value", "since": _unix(since), "until": _unix(until)}
    row = {m: None for m in DAILY_METRICS}
    wanted = [m for m in DAILY_METRICS if m not in seen["refused"]]
    if wanted:
        try:
            row.update(_parse_insights(budget.get(path, {**base, "metric": ",".join(wanted)}), wanted))
        except GraphError as e:
            if e.code not in INVALID_METRIC_CODES:
                raise
            bad = {}
            for m in wanted:
                try:
                    row[m] = _parse_insights(budget.get(path, {**base, "metric": m}), [m])[m]
                except GraphError as e1:
                    if e1.code not in INVALID_METRIC_CODES:
                        raise
                    bad[m] = e1
            if len(bad) == len(wanted):
                raise Unavailable(_short(e))
            for m, e1 in bad.items():
                seen["refused"].add(m)
                errors.append(f"daily.{m} refused ({_short(e1)})")
    if not seen["follows_refused"]:
        try:
            body = budget.get(path, {**base, "metric": "follows_and_unfollows", "breakdown": "follow_type"})
            split = _follow_split(body)
            if body.get("data"):  # an answer with no breakdown rows means nobody followed or left
                split["follows"] = split["follows"] or 0
                split["unfollows"] = split["unfollows"] or 0
                split["net"] = split["follows"] - split["unfollows"]
            row.update(follows=split["follows"], unfollows=split["unfollows"], net_follows=split["net"])
        except GraphError as e:
            if e.code not in INVALID_METRIC_CODES:
                raise
            seen["follows_refused"] = True
            errors.append(f"daily.follows_and_unfollows refused ({_short(e)})")
    row["partial"] = until < since + timedelta(days=1)
    row["fetched_at"] = now.isoformat(timespec="seconds")
    return row


def _follower_series(budget, graph, now, errors):
    """follower_count as a day series (Instagram: last 30 days only, 100+ followers). {date: new followers}."""
    path = f"{graph.ig_user_id}/insights"
    until = _unix(now)
    try:
        body = budget.get(path, {"metric": "follower_count", "period": "day",
                                 "since": until - 29 * 86400, "until": until})
    except GraphError as e:
        if e.code not in INVALID_METRIC_CODES:
            raise
        errors.append(f"daily.follower_count refused ({_short(e)})")
        return {}
    out = {}
    for row in body.get("data") or []:
        for v in row.get("values") or []:
            end = _parse_time(v.get("end_time"))
            if end is not None and v.get("value") is not None:
                # checked against follows_and_unfollows: the value with end_time on date D is UTC day D
                out[end.date().isoformat()] = v["value"]
    return out


def _merge_row(days, date, new):
    old = days.setdefault(date, {"date": date})
    for k, v in new.items():
        if v is not None or k not in old:
            old[k] = v


def follower_curve(days, today, profile_followers, real):
    """Fills "followers" on each row, newest to oldest.

    Today = profile followers_count. A real snapshot (followers.csv) wins over an estimate.
    Otherwise followers(d-1) = followers(d) - net_follows(d), or - new_followers(d) when net is unknown.
    """
    today_s = today.isoformat()
    dates = sorted(d for d in days if d <= today_s)
    if not dates:
        return
    prev_value, prev_row = None, None
    d = today
    first = ddate.fromisoformat(dates[0])
    while d >= first:
        key = d.isoformat()
        row = days.get(key)
        value, estimated = None, False
        if key == today_s and profile_followers is not None:
            value = profile_followers
        elif real.get(key) is not None:
            value = real[key]
        elif prev_value is not None and prev_row is not None:
            delta = prev_row.get("net_follows")
            if delta is None:
                delta = prev_row.get("new_followers")
            if delta is None and prev_row["date"] == today_s:
                delta = 0  # today has no numbers yet: yesterday ended close to the count right now
            if delta is not None:
                value, estimated = prev_value - delta, True
        if row is not None:
            row["followers"] = value
            row["followers_estimated"] = estimated
        prev_value, prev_row = value, row
        d -= timedelta(days=1)


def _real_followers(csv_path):
    out = {}
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    out[r["date"]] = int(r["followers"])
                except (KeyError, TypeError, ValueError):
                    continue
    return out


def update_daily(graph, out, now, profile, errors, log=print, cap=None):
    """Backfills and refreshes dashboard/daily.json. Returns the number of days in the file."""
    cap = HISTORY_CALL_CAP if cap is None else cap
    path = out / "daily.json"
    days = {r["date"]: r for r in _read_json(path, "days") if r.get("date")}
    today = now.date()
    recent = [today - timedelta(days=i) for i in range(REFETCH_DAYS + 1)]
    older = [today - timedelta(days=i) for i in range(REFETCH_DAYS + 1, HISTORY_DAYS + 1)]
    targets = recent + [d for d in older if not days.get(d.isoformat(), {}).get("fetched_at")]
    budget = Budget(graph, cap)
    seen = {"refused": set(), "follows_refused": False}
    fetched, streak = 0, 0
    try:
        for date, value in _follower_series(budget, graph, now, errors).items():
            _merge_row(days, date, {"new_followers": value})
        for d in targets:
            need = (len(DAILY_METRICS) > len(seen["refused"])) + (not seen["follows_refused"])
            if budget.used + need > cap:
                break
            try:
                row = _fetch_day(budget, graph, d, now, seen, errors)
                days.get(d.isoformat(), {}).pop("unavailable", None)
                streak = 0
            except Unavailable as e:
                if d == today:
                    errors.append(f"daily: no numbers for today yet ({e})")
                    continue
                row = {"unavailable": True, "fetched_at": now.isoformat(timespec="seconds")}
                streak += 1
                if streak >= UNAVAILABLE_STREAK and d < recent[-1]:
                    _merge_row(days, d.isoformat(), row)
                    errors.append(f"daily: Instagram has no numbers before {d.isoformat()} ({e})")
                    break
            _merge_row(days, d.isoformat(), row)
            fetched += 1
    except RateLimited as e:
        errors.append(f"daily: stopped after {budget.used} calls, {e}; kept what we had")
    except GraphError as e:
        errors.append(f"daily: stopped after {budget.used} calls ({_short(e)}); kept what we had")

    days.setdefault(today.isoformat(), {"date": today.isoformat()})
    follower_curve(days, today, (profile or {}).get("followers_count"), _real_followers(out / "followers.csv"))
    rows = []
    for key in sorted(days):
        r = days[key]
        rows.append({**{f: r.get(f) for f in DAY_FIELDS}, **{k: v for k, v in r.items() if k not in DAY_FIELDS}})
    missing = sum(1 for d in recent[1:] + older if not days.get(d.isoformat(), {}).get("fetched_at"))
    _write_json(path, {"updated_at": now.isoformat(timespec="seconds"), "missing_days": missing, "days": rows})
    log(f"Daily history: {fetched} day(s) read with {budget.used} calls, {len(rows)} in file, "
        f"{missing} of the last {HISTORY_DAYS} still missing.")
    return len(rows)


# ---- media cache ------------------------------------------------------------
def list_media(graph, limit, errors):
    """Newest posts first. Returns (items, complete)."""
    items, after = [], None
    try:
        while len(items) < limit:
            params = {"fields": MEDIA_FIELDS, "limit": min(MEDIA_PAGE, limit - len(items))}
            if after:
                params["after"] = after
            body = graph.get(f"{graph.ig_user_id}/media", params)
            page = body.get("data") or []
            items += page
            paging = body.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if not page or not paging.get("next") or not after:
                return items[:limit], True
    except Exception as e:  # noqa: BLE001 - keep the pages we already have
        errors.append(f"media list: stopped after {len(items)} posts ({_short(e)})")
        return items, False
    return items[:limit], True


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


def _media_numbers(budget, media_id, wanted, refused):
    """{metric: value}. Learns metrics Instagram refuses for this kind of post (only when others worked)."""
    path = f"{media_id}/insights"
    try:
        return _parse_insights(budget.get(path, {"metric": ",".join(wanted)}), wanted)
    except GraphError as e:
        if e.code not in INVALID_METRIC_CODES:
            raise
        first = e
    out, bad = {}, set()
    for m in wanted:
        try:
            out[m] = _parse_insights(budget.get(path, {"metric": m}), [m])[m]
        except GraphError as e:
            if e.code not in INVALID_METRIC_CODES:
                raise
            out[m] = None
            bad.add(m)
    if len(bad) == len(wanted):
        raise Unavailable(_short(first))
    refused.update(bad)
    return out


def update_media(graph, out, now, trial_ids, errors, log=print, cap=None):
    """Refreshes dashboard/media.json. Returns the cached posts, newest first."""
    cap = MEDIA_CALL_CAP if cap is None else cap
    path = out / "media.json"
    cached = {str(m.get("id")): m for m in _read_json(path, "media") if m.get("id")}
    raw, complete = list_media(graph, MEDIA_CACHE_MAX, errors)
    items = {}
    for m in raw:
        mid = str(m.get("id"))
        old = cached.get(mid, {})
        items[mid] = {
            "id": mid,
            "caption": (m.get("caption") or "")[:CAPTION_MAX],
            "media_type": m.get("media_type"),
            "media_product_type": m.get("media_product_type"),
            "permalink": m.get("permalink"),
            "timestamp": m.get("timestamp"),
            "like_count": m.get("like_count"),
            "comments_count": m.get("comments_count"),
            "is_trial": mid in trial_ids,
            "insights": old.get("insights"),
            "insights_at": old.get("insights_at"),
        }
    if not complete:  # keep cached posts the listing did not reach this time
        for mid, old in cached.items():
            items.setdefault(mid, {k: v for k, v in old.items() if k != "thumbnail_url"})
    media = sorted(items.values(), key=lambda m: m.get("timestamp") or "", reverse=True)[:MEDIA_CACHE_MAX]

    budget = Budget(graph, cap)
    refused = {"reel": set(), "other": set()}
    young_from = now - timedelta(days=MEDIA_REFRESH_DAYS)
    refreshed = failed = waiting = fails_in_row = 0
    first_error = None
    stopped = False
    for m in media:
        ts = _parse_time(m.get("timestamp"))
        if m.get("insights_at") and not (ts and ts >= young_from):
            continue
        if stopped or budget.used >= cap:
            waiting += 1
            continue
        kind = "reel" if m.get("media_product_type") == "REELS" else "other"
        wanted = [x for x in MEDIA_METRICS if x not in refused[kind] and (kind == "reel" or x not in REEL_ONLY)]
        try:
            numbers = _media_numbers(budget, m["id"], wanted, refused[kind])
            m["insights"] = {x: numbers.get(x) for x in MEDIA_METRICS}
            m["insights_at"] = now.isoformat(timespec="seconds")
            m.pop("insights_error", None)
            refreshed += 1
            fails_in_row = 0
        except Unavailable as e:  # e.g. posted before the account became a business account
            m["insights"] = m.get("insights") or {x: None for x in MEDIA_METRICS}
            m["insights_at"] = now.isoformat(timespec="seconds")
            m["insights_error"] = str(e)[:120]
            failed += 1
            first_error = first_error or str(e)
        except RateLimited as e:
            errors.append(f"media insights: stopped after {budget.used} calls, {e}")
            stopped = True
            waiting += 1
        except GraphError as e:
            failed += 1
            fails_in_row += 1
            first_error = first_error or _short(e)
            if fails_in_row >= 5:
                errors.append(f"media insights: stopped after 5 failures in a row ({_short(e)})")
                stopped = True
    if failed:
        errors.append(f"media insights failed for {failed} post(s) ({first_error})")
    for kind, metrics in sorted(refused.items()):
        if metrics:
            errors.append(f"media ({kind}) metrics refused: {', '.join(sorted(metrics))}")
    _write_json(path, {"updated_at": now.isoformat(timespec="seconds"), "pending_insights": waiting,
                       "media": media})
    log(f"Media cache: {len(media)} posts, {refreshed} refreshed with {budget.used} calls, "
        f"{waiting} waiting for a later run.")
    return media


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
    today = _midnight(now.date())
    errors = []
    data = {"generated_at": now.isoformat(timespec="seconds"), "profile": None, "account_day": None,
            "follows_1d": None, "account_28d": None, "media": None, "trending_audio": None, "errors": errors,
            "daily_days": None, "media_cached": None}
    out = Path(out_dir)
    if not out.is_absolute():
        out = Path(root) / out
    out.mkdir(parents=True, exist_ok=True)

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

    profile, day = data["profile"] or {}, data["account_day"] or {}
    try:
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
    except Exception as e:  # noqa: BLE001
        errors.append(f"followers.csv: {_short(e)}")
    try:
        data["daily_days"] = update_daily(graph, out, now, data["profile"], errors, log)
    except Exception as e:  # noqa: BLE001
        errors.append(f"daily: {_short(e)}")
    try:
        media = update_media(graph, out, now, trial_media_ids(root), errors, log)
        data["media_cached"] = len(media)
        data["media"] = [dict(m) for m in media[:DASHBOARD_MEDIA]]
    except Exception as e:  # noqa: BLE001
        errors.append(f"media: {_short(e)}")
    try:
        body = graph.audio_search_raw("music")
        tracks = body.get("audio") or body.get("data") or []
        data["trending_audio"] = [normalise_audio(a, "music") for a in tracks[:AUDIO_LIMIT]]
    except Exception as e:  # noqa: BLE001
        errors.append(f"trending_audio: {_short(e)}")

    (out / "account.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"Account snapshot: {profile.get('followers_count')} followers, "
        f"{len(data['media'] or [])} posts in account.json, {len(errors)} problem(s).")
    for e in errors:
        log(f"  {e}")
    return data
