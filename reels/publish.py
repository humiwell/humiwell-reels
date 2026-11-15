"""Posts every trial reel that is due and not yet posted. Safe to run again and again."""
from datetime import date, datetime, timedelta

from .common import (KINDS, batch_kind, key_date, key_kind, lane, lane_slot_times, local_tz, open_issue,
                     save_state, video_url)
from .graph import GraphError

OPEN = ("pending", "container")


def rotation(variant_ids, day):
    """Which variant goes in which slot. Shifts by one every day so no hook always gets the best time."""
    k = day.toordinal() % len(variant_ids)
    return variant_ids[k:] + variant_ids[:k]


def register_day(state, manifest, key=None):
    """key is the batch key (folder name). Defaults to post_date, the B-roll key."""
    d = key or manifest["post_date"]
    if d in state["days"]:
        return
    ids = [v["id"] for v in manifest["variants"]]
    state["days"][d] = {
        "reel": manifest["reel"],
        "kind": batch_kind(manifest),
        "order": rotation(ids, date.fromisoformat(key_date(d))),
        "audio": None,
        "variants": {i: {"status": "pending"} for i in ids},
        "results_done": False,
    }


def choose_audio(cfg, graph, post_date, log=print, refused=(), manifest=None):
    """Picks ONE track for all versions of a reel, so the test stays fair.

    Order: config pin for this date, the manifest's audio_id, config pin for every reel, then trending.
    Tracks Instagram already refused for this reel are skipped.
    """
    a = cfg["audio"]
    if not a.get("enabled", True):
        return {"id": None, "note": "audio turned off in config"}
    manifest = manifest or {}
    by_date = {str(k): str(v) for k, v in (a.get("pin_by_date") or {}).items()}
    pins = [(by_date.get(post_date), "pinned for this day in config", ""),
            (str(manifest.get("audio_id") or ""), "set in manifest", manifest.get("audio_title") or ""),
            (str(a.get("pin_audio_id") or ""), "pinned in config", "")]
    for pin, note, title in pins:
        if not pin or pin in refused:
            continue
        try:
            info = graph.audio_info(pin)
        except GraphError as e:
            log(f"  could not look up chosen track {pin}: {e}")
            info = {"title": "", "artist": "", "type": ""}
        info.update(id=pin, note=note, pinned=True)
        info["title"] = info.get("title") or title or "(unknown)"
        if title:
            info["manifest_title"] = title
        return info
    blocked_ids = {str(x) for x in a.get("block_ids") or []} | set(refused)
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


def audio_config(cfg, audio, kind="broll"):
    """Talking head keeps the voice (video_volume 100) under a quiet track (audio_volume 3)."""
    if not audio or not audio.get("id"):
        return None
    L = lane(cfg, kind)
    return {"audio_id": audio["id"],
            "audio_volume": L["audio_volume"],
            "video_volume": L["video_volume"]}


def _retry_key(kind):
    return "audio_retry_after" if kind == "broll" else "th_audio_retry_after"


def run(cfg, state, graph, manifests, now, log=print, checkpoint=None):
    dry = cfg.get("dry_run", True)
    tz = local_tz(cfg)
    today = now.astimezone(tz).date()
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

    # 1. Add today's batches (and any recent ones) to the queue.
    for key, m in sorted(manifests.items()):
        if not lane(cfg, batch_kind(m)).get("enabled", True):
            continue
        if max(start, oldest) <= key_date(key) <= today.isoformat():
            register_day(state, m, key)

    # 2. Drop versions that waited too long.
    for d, day in state["days"].items():
        if key_date(d) < oldest:
            late = [i for i, v in day["variants"].items() if v["status"] in OPEN]
            for i in late:
                day["variants"][i]["status"] = "skipped"
            if late:
                open_issue(f"Skipped {len(late)} version(s) of {d}",
                           f"Versions {', '.join(late)} of '{day['reel']}' were not posted within "
                           f"{cfg.get('max_carry_days', 2)} days and were dropped. Results for this "
                           "day will compare only the versions that went out.", dry)

    # 3. Each kind of batch posts in its own slots. A problem in one lane never stops the other.
    for kind in KINDS:
        if _run_lane(cfg, state, graph, manifests, now, today, kind, log, checkpoint) == "stop":
            return


def _run_lane(cfg, state, graph, manifests, now, today, kind, log, checkpoint):
    dry = cfg.get("dry_run", True)
    tz = local_tz(cfg)
    L = lane(cfg, kind)
    if not L.get("enabled", True) or not L["slots"]:
        return None
    tag = "" if kind == "broll" else "[talking head] "
    days = [d for d in sorted(state["days"]) if state["days"][d].get("kind", "broll") == kind]

    # How many posts are due right now in this lane?
    slots = lane_slot_times(cfg, kind, today)
    due = sum(1 for t in slots if t <= now)
    posted_today = sum(
        1 for d in days for v in state["days"][d]["variants"].values()
        if v.get("posted_at") and _local_date(v["posted_at"], tz) == today)
    todo = min(due - posted_today, int(cfg.get("max_posts_per_run", 2)))
    if todo <= 0:
        upcoming = [t for t in slots if t > now]
        when = upcoming[0].astimezone(tz).strftime("%H:%M") if upcoming else "tomorrow"
        log(f"{tag}Nothing due. {posted_today} posted today. Next slot: {when}.")
        return None

    queue = [(d, i) for d in days for i in state["days"][d]["order"]
             if state["days"][d]["variants"][i]["status"] in OPEN]
    # A half-finished upload from an earlier run goes first.
    queue.sort(key=lambda q: state["days"][q[0]]["variants"][q[1]]["status"] != "container")
    if not queue:
        if kind != "broll":
            # Talking-head days depend on filming, so an empty day is normal: no issue.
            log(f"{tag}Slot is due but there is no talking-head batch waiting.")
            return None
        log("Slot is due but the queue is empty. Has this week's batch been pushed?")
        if due and not any(key_date(d) == today.isoformat() for d in days):
            open_issue(f"No batch for {today}",
                       f"A slot was due on {today} but batches/{today}/manifest.json is missing. "
                       "See docs/BATCH_CONTRACT.md.", dry)
        return None

    # Audio is required and was refused recently: wait before trying again.
    retry = state.get(_retry_key(kind))
    if retry and now < datetime.fromisoformat(retry):
        log(f"{tag}Waiting for audio to work again. Next try after {retry}. Nothing posted.")
        return None

    # 4. Check the official daily allowance before posting.
    if not dry:
        try:
            used, total = graph.publishing_limit()
            log(f"Publishing allowance: {used} of {total} used in the last 24 h.")
            if used is not None and total and used >= total:
                _limit_reached(state, today, "content_publishing_limit says the quota is used up", dry)
                return "stop"
        except GraphError as e:
            log(f"  could not read the publishing allowance: {e}")

    for d, vid in queue[:todo]:
        result = post_one(cfg, state, graph, manifests, d, vid, now, log, checkpoint)
        if result == "limit":
            _limit_reached(state, today, state["days"][d]["variants"][vid].get("error", ""), dry)
            return "stop"
        if result in ("busy", "error", "audio"):
            return None
        if not dry:
            save_state(state)
            if checkpoint and not checkpoint():
                log("  could not save this post to GitHub. Posting nothing more this run.")
                return "stop"
    return None


def post_one(cfg, state, graph, manifests, d, vid, now, log=print, checkpoint=None):
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

    required = cfg["audio"].get("required", True) and cfg["audio"].get("enabled", True)
    if day["audio"] is None:
        audio = (choose_audio(cfg, graph, d, log, day.get("audio_refused", []), manifest) if graph
                 else {"id": manifest.get("audio_id"), "title": manifest.get("audio_title"),
                       "note": "set in manifest" if manifest.get("audio_id") else "no API in dry run"})
        log(f"Audio for {d}: {audio.get('title') or '-'} by {audio.get('artist') or '-'} "
            f"(id {audio.get('id')}, {audio['note']})")
        if required and not audio.get("id") and not dry:
            return _audio_blocked(state, now, d, f"No usable trending audio was found ({audio['note']}).", dry)
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
            status = None
            while status is None:
                try:
                    status = _upload(cfg, state, graph, rec, url, manifest["caption"], day["audio"],
                                     day.get("kind", "broll"))
                except GraphError as e:
                    nobody_posted = all(x["status"] != "posted" for x in day["variants"].values())
                    track = day["audio"] or {}
                    if e.is_limit or not track.get("id"):
                        raise
                    if track.get("pinned") and nobody_posted:
                        # The chosen track (manifest or config) was refused: switch to trending now.
                        day.setdefault("audio_refused", []).append(track["id"])
                        new = choose_audio(cfg, graph, d, log, day["audio_refused"], manifest)
                        log(f"  chosen track {track['id']} was refused ({e}). "
                            f"Falling back to {new.get('title') or 'nothing'} ({new['note']}).")
                        open_issue(f"Chosen audio failed for {d}",
                                   f"Instagram refused the chosen track {track.get('title')!r} "
                                   + (f"(manifest calls it {track['manifest_title']!r}) "
                                      if track.get("manifest_title") else "")
                                   + f"(id {track['id']}, {track['note']}):\n\n```\n{e.message}\n```\n\n"
                                   f"Fell back to {new.get('title') or 'no track'} by {new.get('artist') or '-'} "
                                   f"(id {new.get('id')}, {new['note']}) for all versions of this reel.", dry)
                        if new.get("id"):
                            day["audio"] = new
                            save_state(state)
                            continue
                        if not required:
                            day["audio"] = new
                            continue
                        rec.update(status="pending", error=str(e))
                        rec.pop("container_id", None)
                        day["audio"] = None
                        return _audio_blocked(state, now, d, f"No usable trending audio was found ({new['note']}).",
                                              dry)
                    if required:
                        # Never post without audio. If nothing went out yet, try the next trending track
                        # later; otherwise keep the same track so every version still matches.
                        rec.update(status="pending", error=str(e))
                        rec.pop("container_id", None)
                        if nobody_posted:
                            day.setdefault("audio_refused", []).append(track["id"])
                            day["audio"] = None
                        return _audio_blocked(state, now, d, f"Instagram refused the upload with track "
                                              f"{track.get('title')!r} (id {track['id']}):\n\n```\n{e.message}\n```",
                                              dry)
                    if not nobody_posted:
                        raise
                    # Keep the test fair: the whole reel switches to no audio, not just this version.
                    log(f"  Instagram refused the upload with audio ({e}). This reel goes out without audio.")
                    open_issue("Trending audio is not attaching",
                               f"On {d} Instagram refused the upload with track {track.get('title')!r} "
                               f"(id {track['id']}):\n\n```\n{e.message}\n```\n\nAll versions of that reel "
                               "post without audio so the test stays fair. Each new reel tries audio again. "
                               "Close this issue once you have looked; it reopens if it happens again.", dry)
                    day["audio"] = {"id": None, "note": f"audio refused: {e.message}", "tried": track}
        else:
            status = graph.wait_for_container(rec["container_id"])
        if status == "IN_PROGRESS":
            log("  Instagram is still processing the video. Will finish on the next run.")
            return "busy"
        if status == "PUBLISHED":
            media_id = None  # posted by an earlier run that stopped before saving
        else:
            # Claim first: record the upload on GitHub before publishing, so any later run sees it and
            # finishes this same upload instead of making a second post.
            if checkpoint and not checkpoint():
                log("  could not save the upload to GitHub, so not publishing it now (avoids a duplicate).")
                return "busy"
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


def next_slot_with_work(cfg, state, manifests, now):
    """The next slot time (any lane), if something will be waiting to post then. Otherwise None."""
    tz = local_tz(cfg)
    today = now.astimezone(tz).date()
    upcoming = sorted(t for d in (today, today + timedelta(days=1)) for kind in KINDS
                      if lane(cfg, kind).get("enabled", True)
                      for t in lane_slot_times(cfg, kind, d) if t > now)
    if not upcoming:
        return None
    nxt = upcoming[0]
    slot_day = nxt.astimezone(tz).date().isoformat()
    queued = any(v["status"] in OPEN for day in state["days"].values() for v in day["variants"].values())
    new_batch = (any(key_date(k) == slot_day for k in manifests)
                 and slot_day >= (state.get("started_on") or slot_day))
    return nxt if queued or new_batch else None


def _audio_blocked(state, now, d, why, dry):
    """Audio is required but did not work: post nothing in this lane, try again in an hour."""
    kind = key_kind(d)
    state[_retry_key(kind)] = (now + timedelta(hours=1)).isoformat()
    if kind == "broll":
        open_issue("Trending audio is not attaching",
                   f"{why}\n\nOn {d} nothing was posted, because posting without audio is turned off "
                   "(`audio: required: true`). The robot tries again every hour, and the queue waits. "
                   "See 'Audio problems' in the README.", dry)
    else:
        open_issue("Talking-head audio is not attaching",
                   f"{why}\n\nNothing from talking-head batch {d} was posted. Talking-head reels keep the "
                   "voice on (video_volume 100) under a quiet trending track (audio_volume 3), and Instagram "
                   "refused that. The robot tries again every hour and B-roll posting carries on as normal. "
                   "To post this day by hand instead, download its videos from the GitHub Release, post them "
                   "as trial reels in the app with one track at a low volume, and delete the batch folder.", dry)
    save_state(state)
    return "audio"


def _upload(cfg, state, graph, rec, url, caption, audio, kind="broll"):
    """Hands the video to Instagram and waits for it to be processed."""
    # Only "url" keeps the trial setting. Resumable uploads drop trial and audio (tested 2026-11-10).
    cid = graph.create_reel_container(url, caption, cfg.get("graduation_strategy", "MANUAL"),
                                      audio_config(cfg, audio, kind), upload="url")
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
