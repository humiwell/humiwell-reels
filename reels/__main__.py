"""Entry point.  python -m reels <command>

Commands: run (token check + publish + results), validate, audio-shortlist, snapshot, account,
          test-check, test-post, test-insights, test-th-check
"""
import os
import sys
import time
from datetime import timedelta

from . import account, notion, publish, results, shortlist, testreel, tokencheck
from .common import (commit_progress, key_date, load_config, load_manifests, load_post_now, load_state, now_utc,
                     open_issue, save_state, video_url)
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
    post_now, req_problems = load_post_now()
    problems += req_problems
    if cmd == "validate":
        if "--online" in argv:
            # Also check every video link of today and later days actually downloads.
            import requests
            today = now_utc().date().isoformat()
            for d, m in sorted(manifests.items()):
                for v in m["variants"] if key_date(d) >= today else []:
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
    if cmd == "hashtags":
        # Read-only: weekly hashtag research (research/hashtags/<date>.md + a summary issue).
        if graph is None:
            print("IG_ACCESS_TOKEN is missing. Run it from GitHub: Actions, Hashtag research.")
            return 1
        from . import hashtags
        _, problems_h = hashtags.run(cfg, graph, dry="--dry" in argv)
        return 0
    if cmd == "snapshot":
        # Read-only: today's numbers for every posted version (prints one SNAP json line each).
        if graph is None:
            print("IG_ACCESS_TOKEN is missing. Run it from GitHub: Actions, Test reel, step snapshot.")
            return 1
        results.snapshot(load_state(), graph)
        return 0
    if cmd == "account":
        # Read-only: account numbers for the dashboard (dashboard/account.json and followers.csv).
        if graph is None:
            print("IG_ACCESS_TOKEN is missing. Run it from GitHub: Actions, Dashboard data.")
            return 1
        account.snapshot(graph, cfg)
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
        elif cmd == "test-th-check":
            testreel.th_check(cfg, graph, os.environ.get("TEST_VIDEO_URL", "").strip(),
                              os.environ.get("TEST_AUDIO_ID", "").strip())
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
    live = not cfg.get("dry_run", True)

    def checkpoint():
        """Saves to GitHub. Posting only goes ahead after a successful save (see commit_progress)."""
        save_state(state)
        return commit_progress()

    while True:
        if live:
            # Sync first: another run may have posted since this copy was made. Act only on the latest.
            if not checkpoint():
                return _sync_failed("before posting", cfg)
            cfg = load_config()
            state = load_state()
            manifests, _ = load_manifests()
            post_now, _ = load_post_now()
        publish.run(cfg, state, graph, manifests, now, checkpoint=checkpoint if live else None, post_now=post_now)
        if graph is not None:
            results.run(cfg, state, graph, manifests, now)
        try:
            notion.run(cfg, state, manifests)
        except Exception as e:  # noqa: BLE001 - Notion must never stop posting
            print(f"Notion step failed: {e}")
        if live and not checkpoint():
            return _sync_failed("after posting", cfg)
        nxt = publish.next_slot_with_work(cfg, state, manifests, now)
        if (cfg.get("dry_run", True) or cfg.get("paused") or state.get("paused_until")
                or nxt is None or nxt - now > window or nxt > stop_by):
            return 0
        # Nap in short steps rather than sleeping right through to the slot. Every wake-up syncs with
        # GitHub (top of the loop), so new batches, config edits and post-now requests are seen within
        # nap_minutes, and other runs never wait hours behind a sleeping one.
        wake = publish.wake_time(nxt, now, int(cfg.get("nap_minutes", 5)))
        print(f"Next slot at {nxt.isoformat()} ({(nxt - now).seconds // 60} min). Staying awake, "
              f"checking GitHub again at {wake.isoformat()}.")
        time.sleep(max(0.0, (wake - now).total_seconds()) + (15 if wake == nxt else 0))
        now = now_utc()  # the next loop syncs, which also picks up new batches and config edits


def _sync_failed(when, cfg):
    """Stop this run rather than risk posting from an out-of-date copy. The next run starts fresh."""
    print(f"Could not sync with GitHub {when}. Stopping this run so nothing is posted twice.")
    open_issue("Robot could not save its progress",
               f"A run could not sync with GitHub {when}, so it stopped posting. The next run starts from "
               "a fresh copy and carries on. If this keeps happening, check the Actions tab.",
               cfg.get("dry_run", True))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
