"""72 hours after a reel's last version, pulls the numbers and names a winner."""
import csv
import json
from datetime import datetime, timedelta

from .common import ROOT, open_issue, save_state
from .graph import GraphError

METRICS = ["reach", "views", "ig_reels_avg_watch_time", "shares", "saved", "likes",
           "comments", "reels_skip_rate", "total_interactions", "follows"]
CSV_COLUMNS = ["post_date", "reel", "variant", "lever", "hook", "slot", "posted_at",
               "audio_title", "audio_artist", "audio_id", "length_s", "reach", "views",
               "avg_watch_s", "watch_pct", "shares", "saved", "likes", "comments", "follows",
               "skip_rate", "sends_per_1k", "saves_per_1k", "follows_per_1k", "rank", "winner"]


def per_1k(x, reach):
    if x is None or not reach:
        return None
    return round(x * 1000 / reach, 1)


def score(variant, numbers, unit):
    reach = numbers.get("reach") or 0
    avg = numbers.get("ig_reels_avg_watch_time")
    avg_s = None if avg is None else (avg / 1000 if unit == "ms" else float(avg))
    length = float(variant["length_s"])
    return {
        "reach": reach,
        "views": numbers.get("views"),
        "avg_watch_s": None if avg_s is None else round(avg_s, 2),
        "watch_pct": None if avg_s is None else round(100 * avg_s / length, 1),
        "shares": numbers.get("shares"),
        "saved": numbers.get("saved"),
        "likes": numbers.get("likes"),
        "comments": numbers.get("comments"),
        "follows": numbers.get("follows"),
        "skip_rate": numbers.get("reels_skip_rate"),
        "sends_per_1k": per_1k(numbers.get("shares"), reach),
        "saves_per_1k": per_1k(numbers.get("saved"), reach),
        "follows_per_1k": per_1k(numbers.get("follows"), reach),
    }


def rank(rows):
    """Best first: highest watch %, then most sends per 1,000 reach."""
    return sorted(rows, key=lambda r: (r["watch_pct"] if r["watch_pct"] is not None else -1,
                                       r["sends_per_1k"] if r["sends_per_1k"] is not None else -1),
                  reverse=True)


def verdict(ranked, min_reach, min_gap):
    if len(ranked) < 2:
        return False, "Only one version has numbers, so there is nothing to compare."
    a, b = ranked[0], ranked[1]
    if a["reach"] < min_reach or b["reach"] < min_reach:
        return False, (f"Not trusted yet: the top two reached {a['reach']} and {b['reach']} people "
                       f"(both need {min_reach}+).")
    gap = (a["watch_pct"] or 0) - (b["watch_pct"] or 0)
    if gap < min_gap:
        return False, f"Not trusted: the watch % lead is only {gap:.1f} points (needs {min_gap}+)."
    return True, f"Trusted: {gap:.1f} point watch % lead, both with {min_reach}+ reach."


def run(cfg, state, graph, manifests, now, log=print):
    r_cfg = cfg["results"]
    wait = timedelta(hours=float(r_cfg.get("wait_hours", 72)))
    dry = cfg.get("dry_run", True)
    for d, day in sorted(state["days"].items()):
        if day.get("results_done"):
            continue
        statuses = [v["status"] for v in day["variants"].values()]
        if any(s in ("pending", "container") for s in statuses):
            continue
        posted = [v for v in day["variants"].values() if v["status"] == "posted"]
        if not posted:
            day["results_done"] = True
            continue
        last = max(datetime.fromisoformat(v["posted_at"]) for v in posted)
        if now < last + wait:
            continue
        log(f"Results for {d}:")
        try:
            report = build_report(cfg, d, day, manifests.get(d), graph)
        except GraphError as e:
            log(f"  could not read insights yet: {e}")
            continue
        write_report(d, report)
        title, body = issue_text(report)
        open_issue(title, body, dry, labels=("robot", "results"))
        day["results_done"] = True
        save_state(state)


def build_report(cfg, d, day, manifest, graph):
    r_cfg = cfg["results"]
    unit = r_cfg.get("avg_watch_time_unit", "ms")
    variants = {v["id"]: v for v in (manifest or {}).get("variants", [])}
    rows = []
    for vid, rec in day["variants"].items():
        if rec["status"] != "posted" or not rec.get("media_id"):
            continue
        v = variants.get(vid, {"id": vid, "lever": "", "hook": "", "length_s": 10})
        numbers = graph.insights(rec["media_id"], METRICS)
        row = {"variant": vid, "lever": v.get("lever", ""), "hook": v.get("hook", ""),
               "length_s": v["length_s"], "slot": rec.get("slot"), "posted_at": rec["posted_at"],
               "media_id": rec["media_id"], "permalink": rec.get("permalink"), "raw": numbers}
        row.update(score(v, numbers, unit))
        rows.append(row)
    ranked = rank(rows)
    for i, row in enumerate(ranked, 1):
        row["rank"] = i
    trusted, why = verdict(ranked, int(r_cfg.get("min_reach", 150)), float(r_cfg.get("min_gap_points", 10)))
    audio = day.get("audio") or {}
    return {"post_date": d, "reel": day["reel"], "audio": audio, "winner": ranked[0]["variant"] if ranked else None,
            "trusted": trusted, "why": why, "variants": ranked,
            "not_posted": [k for k, v in day["variants"].items() if v["status"] != "posted"]}


def write_report(d, report):
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / f"{d}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    csv_path = ROOT / "results.csv"
    new = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        for row in report["variants"]:
            w.writerow({**row, "post_date": d, "reel": report["reel"],
                        "audio_title": report["audio"].get("title"),
                        "audio_artist": report["audio"].get("artist"),
                        "audio_id": report["audio"].get("id"),
                        "winner": row["variant"] == report["winner"]})


def _fmt(x, suffix=""):
    return "n/a" if x is None else f"{x}{suffix}"


def issue_text(report):
    w = report["winner"]
    status = "winner" if report["trusted"] else "early leader (not trusted yet)"
    title = f"Results {report['post_date']} ({report['reel']}): variant {w} is the {status}"
    lines = [f"**{report['why']}**", "",
             f"Audio: {report['audio'].get('title') or 'none'} by {report['audio'].get('artist') or '-'}", "",
             "| Rank | Variant | Lever | Hook | Reach | Watch % | Sends/1k | Saves/1k | Follows/1k |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in report["variants"]:
        lines.append(f"| {r['rank']} | {r['variant']} | {r['lever']} | {r['hook']} | {r['reach']} | "
                     f"{_fmt(r['watch_pct'], '%')} | {_fmt(r['sends_per_1k'])} | {_fmt(r['saves_per_1k'])} | "
                     f"{_fmt(r['follows_per_1k'])} |")
    if report["not_posted"]:
        lines += ["", f"Not posted: {', '.join(report['not_posted'])}"]
    top = report["variants"][0] if report["variants"] else {}
    lines += ["", "**What to do:** open Instagram, find this trial reel"
              + (f" ({top['permalink']})" if top.get("permalink") else "")
              + " and tap *Share to followers* if you are happy with it. Then close this issue."]
    return title, "\n".join(lines)
