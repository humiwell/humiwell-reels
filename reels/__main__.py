"""Entry point.  python -m reels <command>

Commands: run (token check + publish + results), validate, audio-shortlist,
          test-check, test-post, test-insights
"""
import os
import sys
import time
from datetime import timedelta

from . import publish, results, shortlist, testreel, tokencheck
from .common import (commit_progress, load_config, load_manifests, load_state, now_utc, open_issue, save_state,
                     video_url)
from .graph import Graph


def make_graph(cfg):
    if os.environ.get("FAKE_API") == "1":
        from tests.fake_graph import FakeGraph
        return FakeGraph()
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        return None
    return Graph(token, os.environ.get("IG_USER_ID", ""), cfg.get("graph_api_version", "v27.0"),
                 os.environ.get("FB_APP_ID", ""), os.environ.get("FB_APP_SECRET", ""))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "run"
    cfg = load_config()
    manifests, problems = load_manifests()
    if cmd == "validate":
        if "--online" in argv:
            # Also check every video link of today and later days actually downloads.
            import requests
            today = now_utc().date().isoformat()
            for d, m in sorted(manifests.items()):
                for v in m["variants"] if d >= today else []:
                    url = video_url(cfg, d, v["file"])
                    r = requests.head(url, allow_redirects=True, timeout=30)
                    if r.status_code != 200:
                        problems.append(f"{url} gives HTTP {r.status_code}")
        for p in problems:
            print(f"PROBLEM: {p}")
        print(f"{len(manifests)} good batch day(s): {', '.join(sorted(manifests)) or 'none'}")
        return 1 if problems else 0

    graph = make_graph(cfg)
    if cmd == "audio-shortlist":
        if graph is None:
            print("IG_ACCESS_TOKEN is missing. Run it from GitHub: Actions, Test reel, step audio-shortlist.")
            return 1
        terms = [t.strip() for t in os.environ.get("AUDIO_SEARCH", "").split(",") if t.strip()]
        if terms:
            shortlist.run_search(graph, terms)
        else:
            shortlist.run(graph)
        return 0
    if cmd.startswith("test-"):
        if graph is None:
            print("IG_ACCESS_TOKEN is missing.")
            return 1
        if cmd == "test-check":
            testreel.check(cfg, graph)
        elif cmd == "test-post":
            testreel.post(cfg, graph, os.environ.get("TEST_HOST", "release"), os.environ.get("CONFIRM", ""),
                          audio_id=os.environ.get("TEST_AUDIO_ID", "").strip())
        elif cmd == "test-insights":
            testreel.insights(cfg, graph)
        return 0

    state = load_state()
    now = now_utc()
    print(f"Run at {now.isoformat()} | dry_run={cfg.get('dry_run')} | paused={cfg.get('paused')}")
    for p in problems:
        open_issue("Broken batch file", f"{p}\n\nSee docs/BATCH_CONTRACT.md.", cfg.get("dry_run", True))
    if graph is None and not cfg.get("dry_run", True):
        print("IG_ACCESS_TOKEN is missing, cannot post.")
        return 1
    if graph is not None:
        tokencheck.run(cfg, state, graph, now)
    # GitHub starts this job only about once an hour. So after doing what is due, the job stays
    # awake until the next slot (if it is close) and posts right on time, then saves progress.
    stop_by = now + timedelta(minutes=int(cfg.get("max_run_minutes", 300)))
    window = timedelta(minutes=int(cfg.get("wait_for_slot_minutes", 100)))
    while True:
        publish.run(cfg, state, graph, manifests, now)
        if graph is not None:
            results.run(cfg, state, graph, manifests, now)
        if not cfg.get("dry_run", True):
            save_state(state)
            commit_progress()
        nxt = publish.next_slot_with_work(cfg, state, manifests, now)
        if (cfg.get("dry_run", True) or cfg.get("paused") or state.get("paused_until")
                or nxt is None or nxt - now > window or nxt > stop_by):
            return 0
        print(f"Next slot at {nxt.isoformat()} ({(nxt - now).seconds // 60} min). Staying awake to post on time.")
        time.sleep((nxt - now).total_seconds() + 15)
        commit_progress()  # also pulls in new batches and config edits made while waiting
        now = now_utc()
        cfg = load_config()  # pick up a pause or other edits made while waiting
        manifests, _ = load_manifests()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
