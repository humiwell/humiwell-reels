"""Weekly hashtag research: what is getting the most likes and comments in Humiwell's niche.

Uses Instagram hashtag search (read-only). Instagram allows 30 different hashtags per 7 days
per account, so keep the list in config.yml at 30 or fewer.
Writes research/hashtags/<date>.md and opens a short summary issue.
"""
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .common import ROOT, open_issue
from .graph import GraphError

FIELDS = "id,caption,media_type,comments_count,like_count,permalink,timestamp"
OUT_DIR = ROOT / "research" / "hashtags"
TAG_RE = re.compile(r"#(\w+)", re.UNICODE)
RECENT_PAGES = 4  # count up to 200 posts from the last 24 hours
RECENT_TOP_DAYS = 90  # Instagram's "top posts" are all-time; keep only recent ones


def _score(m):
    return (m.get("like_count") or 0) + 3 * (m.get("comments_count") or 0)


def _first_line(caption, n=110):
    line = next((l.strip() for l in (caption or "").splitlines() if l.strip()), "")
    line = line.replace("|", "/")
    return line if len(line) <= n else line[: n - 1].rstrip() + "…"


def _table(posts):
    if not posts:
        return "_None._"
    rows = ["| Post | Type | Likes | Comments | Posted | First line |", "|---|---|---|---|---|---|"]
    for m in posts:
        kind = {"VIDEO": "video", "IMAGE": "photo", "CAROUSEL_ALBUM": "carousel"}.get(m.get("media_type"), "?")
        likes = m.get("like_count")
        rows.append(f"| [Open]({m.get('permalink', '')}) | {kind} | {likes if likes is not None else 'hidden'} | "
                    f"{m.get('comments_count', 0)} | {(m.get('timestamp') or '')[:10]} | {_first_line(m.get('caption'))} |")
    return "\n".join(rows)


AD_WORDS = ("#ad ", "#ad\n", "ad -", "ad |", "advert", "sponsored", "gifted", "black friday", "discount code", "% off")


def _is_ad(m):
    c = (m.get("caption") or "").lower() + " "
    return c.startswith("ad ") or any(w in c for w in AD_WORDS)


def fetch_tag(graph, tag, top_n, now):
    """Returns (top posts of the last 90 days, hottest posts of the last 24 hours, count, related hashtags)."""
    found = graph.get("ig_hashtag_search", {"user_id": graph.ig_user_id, "q": tag})
    ids = found.get("data") or []
    if not ids:
        raise GraphError(404, message=f"Instagram has no hashtag #{tag}")
    hid = ids[0]["id"]
    top = graph.get(f"{hid}/top_media", {"user_id": graph.ig_user_id, "fields": FIELDS, "limit": 50}).get("data", [])
    recent, after, more = [], None, False
    for _ in range(RECENT_PAGES):  # same hashtag again does not count against the 30-a-week limit
        params = {"user_id": graph.ig_user_id, "fields": FIELDS, "limit": 50}
        if after:
            params["after"] = after
        body = graph.get(f"{hid}/recent_media", params)
        page = body.get("data", [])
        recent += page
        after = (body.get("paging") or {}).get("cursors", {}).get("after")
        more = bool((body.get("paging") or {}).get("next")) and len(page) == 50
        if not more or not after:
            break
    recent_count = f"{len(recent)}+" if more else str(len(recent))
    related = Counter()
    for m in top + recent:
        for t in {x.lower() for x in TAG_RE.findall(m.get("caption") or "")}:
            if t != tag.lower():
                related[t] += 1
    cutoff = (now - timedelta(days=RECENT_TOP_DAYS)).strftime("%Y-%m-%d")
    top = sorted([m for m in top if (m.get("timestamp") or "")[:10] >= cutoff], key=_score, reverse=True)[:top_n]
    hot = sorted([m for m in recent if not _is_ad(m)], key=_score, reverse=True)[:top_n]
    return top, hot, recent_count, related


def run(cfg, graph, now=None, log=print, dry=False):
    h = cfg.get("hashtags") or {}
    tags = [t.strip().lstrip("#").lower() for t in h.get("tags", []) if t.strip()]
    if len(tags) > 30:
        log(f"Only the first 30 of {len(tags)} hashtags are used (Instagram's weekly limit).")
        tags = tags[:30]
    top_n = int(h.get("top_posts", 8))
    now = now or datetime.now(timezone.utc)
    day = now.date().isoformat()

    sections, summary, problems, all_related, picks = [], [], [], Counter(), []
    for tag in tags:
        try:
            top, hot, recent_count, related = fetch_tag(graph, tag, top_n, now)
        except GraphError as e:
            problems.append(f"#{tag}: {e}")
            log(f"#{tag}: {e}")
            if e.code in (10, 200) or "permission" in (e.message or "").lower():
                break  # no access at all: the other tags will fail the same way
            continue
        all_related.update(related)
        best = hot[0] if hot else (top[0] if top else {})
        summary.append((tag, recent_count, _score(best), best.get("permalink", "")))
        if hot:
            picks.append((tag, hot[0]))
        rel = ", ".join(f"#{t}" for t, _ in related.most_common(8)) or "none"
        sections.append(f"## #{tag}\n\nPosts in the last 24 hours: {recent_count}. "
                        f"Hashtags used alongside it: {rel}\n\n"
                        f"**Hot in the last 24 hours**\n\n{_table(hot)}\n\n"
                        f"**Top posts from the last {RECENT_TOP_DAYS} days**\n\n{_table(top)}")
        log(f"#{tag}: {len(hot)} hot, {len(top)} recent top posts, {recent_count} in the last 24 hours")

    lines = [f"# Hashtag research, week of {day}", "",
             "For each hashtag: the hottest posts of the last 24 hours, the top posts of the last 90 days "
             "(ranked by likes + 3 x comments), and how busy the tag was in the last 24 hours.",
             "Use it for reel, song and carousel ideas and hook patterns. Edit the list in config.yml under `hashtags:`.", ""]
    if picks:
        lines += ["## Top picks this week (start here)", "",
                  "The five hottest posts of the last 24 hours, one per hashtag, adverts left out.", ""]
        for tag, m in sorted(picks, key=lambda x: _score(x[1]), reverse=True)[:5]:
            likes = m.get("like_count")
            lines.append(f"- **#{tag}**: \"{_first_line(m.get('caption'), 90)}\" "
                         f"({likes if likes is not None else 'hidden'} likes, {m.get('comments_count', 0)} comments) "
                         f"[Open post]({m.get('permalink', '')})")
        lines.append("")
    if summary:
        lines += ["## At a glance", "", "| Hashtag | Posts in last 24 h | Hottest post score | Hottest post |", "|---|---|---|---|"]
        lines += [f"| #{t} | {c} | {s} | {'[Open post](' + p + ')' if p else ''} |" for t, c, s, p in summary]
        lines += ["", "**Most common hashtags across all of them:** "
                  + (", ".join(f"#{t} ({n})" for t, n in all_related.most_common(15)) or "none"), ""]
    if problems:
        lines += ["## Problems", ""] + [f"- {p}" for p in problems] + [""]
    lines += sections
    text = "\n".join(lines) + "\n"

    if dry:
        print(text)
        return text, problems
    if summary:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"{day}.md"
        path.write_text(text, encoding="utf-8")
        rel_path = f"research/hashtags/{day}.md"
        busiest = sorted(summary, key=lambda s: -int(str(s[1]).rstrip("+") or 0))[:5]
        body = (f"This week's report: [{rel_path}](../blob/main/{rel_path})\n\n"
                "Busiest hashtags in the last 24 hours: " + ", ".join(f"#{t} ({c})" for t, c, _, _ in busiest) + "\n\n"
                + (f"{len(problems)} hashtag(s) had problems, see the report.\n\n" if problems else "")
                + "Close this issue once you've read it.")
        open_issue(f"Hashtag research for week of {day}", body, False, labels=("research",))
    else:
        open_issue(f"Hashtag research failed on {day}",
                   "Instagram refused every hashtag:\n\n" + "\n".join(f"- {p}" for p in problems[:5])
                   + "\n\nIf it says permission or feature, the Meta app needs 'Instagram Public Content Access' "
                     "approved in App Review.", False)
    return text, problems
