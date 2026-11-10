"""Posts every trial reel that is due and not yet posted. Safe to run again and again."""
from datetime import date, datetime, timedelta

from .common import local_tz, open_issue, save_state, slot_times, video_url
from .graph import GraphError

OPEN = ("pending", "container")


def rotation(variant_ids, day):
    """Which variant goes in which slot. Shifts by one every day so no hook always gets the best time."""
    k = day.toordinal() % len(variant_ids)
    return variant_ids[k:] + variant_ids[:k]


def register_day(state, manifest):
    d = manifest["post_date"]
    if d in state["days"]:
        return
    ids = [v["id"] for v in manifest["variants"]]
    state["days"][d] = {
        "reel": manifest["reel"],
        "order": rotation(ids, date.fromisoformat(d)),
        "audio": None,
        "variants": {i: {"status": "pending"} for i in ids},
        "results_done": False,
    }


def choose_audio(cfg, graph, post_date, log=print):
    """Picks ONE track for all versions of a reel, so the test stays fair."""
    a = cfg["audio"]
    if not a.get("enabled", True):
        return {"id": None, "note": "audio turned off in config"}
    pins = {str(k): str(v) for k, v in (a.get("pin_by_date") or {}).items()}
    pin = pins.get(post_date) or str(a.get("pin_audio_id") or "")
    if pin:
        try:
            info = graph.audio_info(pin)
        except GraphError as e:
            log(f"  could not look up pinned track {pin}: {e}")
            info = {"id": pin, "title": "(unknown)", "artist": "", "type": ""}
        info["id"] = pin
        info["note"] = "pinned in config"
        return info
    blocked_ids = {str(x) for x in a.get("block_ids") or []}
    blocked_words = [w.lower() for w in a.get("block_words") or []]
    first = a.get("prefer", "music")
    kinds = [first]
    if a.get("fallback_to_other_type", True):
        kinds.append("original_sound" if first == "music" else "music")
    for kind in kinds:
        try:
            tracks = graph.trending_audio(kind)
        except GraphError as e:
            log(f"  could not get trending {kind}: {e}")
            continue
        for rank, t in enumerate(tracks, 1):
            text = f"{t['title']} {t['artist']}".lower()
            if not t["id"] or t["id"] in blocked_ids or any(w in text for w in blocked_words):
                continue
            t["note"] = f"trending {kind}, rank {rank}"
            return t
    return {"id": None, "note": "no usable trending audio found"}


def audio_config(cfg, audio):
    if not audio or not audio.get("id"):
        return None
    a = cfg["audio"]
    return {"audio_id": audio["id"],
            "audio_volume": int(a.get("audio_volume", 100)),
            "video_volume": int(a.get("video_volume", 100))}


def run(cfg, state, graph, manifests, now, log=print):
    dry = cfg.get("dry_run", True)
    tz = local_tz(cfg)
    today = now.astimezone(tz).date()
    tag = "[DRY RUN] " if dry else ""
    if cfg.get("paused"):
        log("Paused in config.yml. Nothing posted.")
        return
    if state.get("paused_until") and today.isoformat() < state["paused_until"]:
        log(f"Daily limit was reached. Posting resumes on {state['paused_until']}.")
        return

    if not dry and not state.get("started_on"):
        state["started_on"] = today.isoformat()
    start = state.get("started_on") or today.isoformat()
    oldest = (today - timedelta(days=cfg.get("max_carry_days", 2))).isoformat()

    # 1. Add today's batch (and any recent ones) to the queue.
    for d, m in sorted(manifests.items()):
        if max(start, oldest) <= d <= today.isoformat():
            register_day(state, m)

    # 2. Drop versions that waited too long.
    for d, day in state["days"].items():
        if d < oldest:
            late = [i for i, v in day["variants"].items() if v["status"] in OPEN]
            for i in late:
                day["variants"][i]["status"] = "skipped"
            if late:
                open_issue(f"Skipped {len(late)} version(s) of {d}",
                           f"Versions {', '.join(late)} of '{day['reel']}' were not posted within "
                           f"{cfg.get('max_carry_days', 2)} days and were dropped. Results for this "
                           "day will compare only the versions that went out.", dry)

    # 3. How many posts are due right now?
    slots = slot_times(cfg, today)
    due = sum(1 for t in slots if t <= now)
    posted_today = sum(
        1 for day in state["days"].values() for v in day["variants"].values()
        if v.get("posted_at") and _local_date(v["posted_at"], tz) == today)
    todo = min(due - posted_today, int(cfg.get("max_posts_per_run", 2)))
    if todo <= 0:
        upcoming = [t for t in slots if t > now]
        when = upcoming[0].astimezone(tz).strftime("%H:%M") if upcoming else "tomorrow"
        log(f"Nothing due. {posted_today} posted today. Next slot: {when}.")
        return

    queue = [(d, i) for d in sorted(state["days"]) for i in state["days"][d]["order"]
             if state["days"][d]["variants"][i]["status"] in OPEN]
    # A half-finished upload from an earlier run goes first.
    queue.sort(key=lambda q: state["days"][q[0]]["variants"][q[1]]["status"] != "container")
    if not queue:
        log("Slot is due but the queue is empty. Has this week's batch been pushed?")
        if due and not any(d == today.isoformat() for d in state["days"]):
            open_issue(f"No batch for {today}",
                       f"A slot was due on {today} but batches/{today}/manifest.json is missing. "
                       "See docs/BATCH_CONTRACT.md.", dry)
        return

    # 4. Check the official daily allowance before posting.
    if not dry:
        try:
            used, total = graph.publishing_limit()
            log(f"Publishing allowance: {used} of {total} used in the last 24 h.")
            if used is not None and total and used >= total:
                return _limit_reached(state, today, "content_publishing_limit says the quota is used up", dry)
        except GraphError as e:
            log(f"  could not read the publishing allowance: {e}")

    for d, vid in queue[:todo]:
        result = post_one(cfg, state, graph, manifests, d, vid, now, log)
        if result == "limit":
            return _limit_reached(state, today, state["days"][d]["variants"][vid].get("error", ""), dry)
        if result in ("busy", "error"):
            return
        if not dry:
            save_state(state)


def post_one(cfg, state, graph, manifests, d, vid, now, log=print):
    dry = cfg.get("dry_run", True)
    day = state["days"][d]
    rec = day["variants"][vid]
    manifest = manifests.get(d)
    if manifest is None:
        rec["status"], rec["error"] = "failed", "manifest removed"
        return "error"
    v = next(x for x in manifest["variants"] if x["id"] == vid)
    url = video_url(cfg, d, v["file"])
    slot_no = day["order"].index(vid) + 1

    if day["audio"] is None:
        audio = choose_audio(cfg, graph, d, log) if graph else {"id": None, "note": "no API in dry run"}
        log(f"Audio for {d}: {audio.get('title') or '-'} by {audio.get('artist') or '-'} "
            f"(id {audio.get('id')}, {audio['note']})")
        if not dry:
            day["audio"] = audio
            save_state(state)
    if dry:
        log(f"[DRY RUN] would post {d} variant {vid} (slot {slot_no}): {v['hook']!r} from {url}")
        return "ok"

    log(f"Posting {d} variant {vid} (slot {slot_no}): {v['hook']!r}")
    try:
        if rec["status"] == "container":
            code, _ = graph.container_status(rec["container_id"])
            if code in ("ERROR", "EXPIRED"):
                log(f"  old upload {code.lower()}, starting again")
                rec["status"] = "pending"
        if rec["status"] == "pending":
            try:
                status = _upload(cfg, state, graph, rec, url, manifest["caption"], day["audio"])
            except GraphError as e:
                nobody_posted = all(x["status"] != "posted" for x in day["variants"].values())
                if e.is_limit or not (day["audio"] or {}).get("id") or not nobody_posted:
                    raise
                # Keep the test fair: the whole reel switches to no audio, not just this version.
                # Every new reel tries audio again, so it comes back by itself once Instagram allows it.
                log(f"  Instagram refused the upload with audio ({e}). This reel goes out without audio.")
                open_issue("Trending audio is not attaching",
                           f"On {d} Instagram refused the upload with track {day['audio'].get('title')!r} "
                           f"(id {day['audio']['id']}):\n\n```\n{e.message}\n```\n\nAll versions of that reel "
                           "post without audio so the test stays fair. Each new reel tries audio again. "
                           "Close this issue once you have looked; it reopens if it happens again.", dry)
                day["audio"] = {"id": None, "note": f"audio refused: {e.message}", "tried": day["audio"]}
                status = _upload(cfg, state, graph, rec, url, manifest["caption"], None)
        else:
            status = graph.wait_for_container(rec["container_id"])
        if status == "IN_PROGRESS":
            log("  Instagram is still processing the video. Will finish on the next run.")
            return "busy"
        if status == "PUBLISHED":
            media_id = None  # posted by an earlier run that stopped before saving
        else:
            media_id = graph.publish(rec["container_id"])
    except GraphError as e:
        rec["error"] = str(e)
        if e.is_limit:
            return "limit"
        rec["attempts"] = rec.get("attempts", 0) + 1
        log(f"  failed (attempt {rec['attempts']}): {e}")
        if rec["attempts"] >= 3:
            rec["status"] = "failed"
            open_issue(f"Could not post {d} variant {vid}",
                       f"Tried 3 times. Last error:\n\n```\n{e}\n```\n\nThe robot moved on to the next "
                       f"version. Video link used: {url}", dry)
        save_state(state)
        return "error"

    rec.update(status="posted", media_id=media_id, posted_at=now.isoformat(), slot=slot_no)
    rec.pop("error", None)
    try:
        if media_id:
            rec["permalink"] = graph.media_info(media_id).get("permalink")
    except GraphError:
        pass
    log(f"  posted. media id {media_id}")
    return "ok"


def _upload(cfg, state, graph, rec, url, caption, audio):
    """Hands the video to Instagram and waits for it to be processed."""
    cid = graph.create_reel_container(url, caption, cfg.get("graduation_strategy", "MANUAL"),
                                      audio_config(cfg, audio))
    rec.update(status="container", container_id=cid)
    save_state(state)
    return graph.wait_for_container(cid)


def _limit_reached(state, today, why, dry):
    tomorrow = (today + timedelta(days=1)).isoformat()
    state["paused_until"] = tomorrow
    open_issue(f"Daily limit reached on {today}",
               f"Instagram said the posting limit is reached ({why}).\n\nThe robot stopped for today. "
               f"Unposted versions stay in the queue and go out from {tomorrow}. If this keeps "
               "happening, remove a slot or two in config.yml.", dry)
    if not dry:
        save_state(state)


def _local_date(iso, tz):
    return datetime.fromisoformat(iso).astimezone(tz).date()
