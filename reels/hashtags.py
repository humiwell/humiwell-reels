"""Weekly hashtag research: what is getting the most likes and comments in Humiwell's niche.

Uses Instagram hashtag search (read-only). Instagram allows 30 different hashtags per 7 days
per account, so keep the list in config.yml at 30 or fewer.
Writes research/hashtags/<date>.md and opens a short summary issue.
"""
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .common import ROOT, open_issue
from .graph import GraphError

FIELDS = "id,caption,media_type,comments_count,like_count,permalink,timestamp"
OUT_DIR = ROOT / "research" / "hashtags"
TAG_RE = re.compile(r"#(\w+)", re.UNICODE)


def _score(m):
    return (m.get("like_count") or 0) + 3 * (m.get("comments_count") or 0)


def _first_line(caption, n=110):
    line = next((l.strip() for l in (caption or "").splitlines() if l.strip()), "")
    line = line.replace("|", "/")
    return line if len(line) <= n else line[: n - 1].rstrip() + "…"


def fetch_tag(graph, tag, top_n):
    """Returns (top posts, number of posts in the last 24 hours, related hashtags)."""
    found = graph.get("ig_hashtag_search", {"user_id": graph.ig_user_id, "q": tag})
    ids = found.get("data") or []
    if not ids:
        raise GraphError(404, message=f"Instagram has no hashtag #{tag}")
    hid = ids[0]["id"]
    top = graph.get(f"{hid}/top_media", {"user_id": graph.ig_user_id, "fields": FIELDS, "limit": 50}).get("data", [])
    recent_body = graph.get(f"{hid}/recent_media", {"user_id": graph.ig_user_id, "fields": "id,caption", "limit": 50})
    recent = recent_body.get("data", [])
    if recent_body.get("paging", {}).get("next") and len(recent) >= 50:
        recent_count = "50+"
    else:
        recent_count = str(len(recent))
    related = Counter()
    for m in top + recent:
        for t in {x.lower() for x in TAG_RE.findall(m.get("caption") or "")}:
            if t != tag.lower():
                related[t] += 1
    top = sorted(top, key=_score, reverse=True)[:top_n]
    return top, recent_count, related


def run(cfg, graph, now=None, log=print, dry=False):
    h = cfg.get("hashtags") or {}
    tags = [t.strip().lstrip("#").lower() for t in h.get("tags", []) if t.strip()]
    if len(tags) > 30:
        log(f"Only the first 30 of {len(tags)} hashtags are used (Instagram's weekly limit).")
        tags = tags[:30]
    top_n = int(h.get("top_posts", 8))
    now = now or datetime.now(timezone.utc)
    day = now.date().isoformat()

    sections, summary, problems, all_related = [], [], [], Counter()
    for tag in tags:
        try:
            top, recent_count, related = fetch_tag(graph, tag, top_n)
        except GraphError as e:
            problems.append(f"#{tag}: {e}")
            log(f"#{tag}: {e}")
            if e.code in (10, 200) or "permission" in (e.message or "").lower():
                break  # no access at all: the other tags will fail the same way
            continue
        all_related.update(related)
        best = top[0] if top else {}
        summary.append((tag, recent_count, _score(best), best.get("permalink", "")))
        rows = ["| # | Type | Likes | Comments | Posted | First line |", "|---|---|---|---|---|---|"]
        for i, m in enumerate(top, 1):
            kind = {"VIDEO": "video", "IMAGE": "photo", "CAROUSEL_ALBUM": "carousel"}.get(m.get("media_type"), "?")
            likes = m.get("like_count")
            rows.append(f"| [{i}]({m.get('permalink', '')}) | {kind} | {likes if likes is not None else 'hidden'} | "
                        f"{m.get('comments_count', 0)} | {(m.get('timestamp') or '')[:10]} | {_first_line(m.get('caption'))} |")
        rel = ", ".join(f"#{t}" for t, _ in related.most_common(8)) or "none"
        sections.append(f"## #{tag}\n\nPosts in the last 24 hours: {recent_count}. "
                        f"Hashtags used alongside it: {rel}\n\n" + "\n".join(rows))
        log(f"#{tag}: {len(top)} top posts, {recent_count} in the last 24 hours")

    lines = [f"# Hashtag research, week of {day}", "",
             "Top posts for each hashtag (ranked by likes + 3 x comments) and how busy each tag was in the last 24 hours.",
             "Use it for reel, song and carousel ideas and hook patterns. Edit the list in config.yml under `hashtags:`.", ""]
    if summary:
        lines += ["## At a glance", "", "| Hashtag | Posts in last 24 h | Best post score | Best post |", "|---|---|---|---|"]
        lines += [f"| #{t} | {c} | {s} | {'[open](' + p + ')' if p else ''} |" for t, c, s, p in summary]
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
