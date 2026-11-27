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


def _rotation_start(post_date, n):
    """Where to start in the approved list for this day, so consecutive days get different tracks."""
    try:
        return date.fromisoformat(str(post_date)[-10:]).toordinal() % n
    except ValueError:
        return 0


def choose_audio(cfg, graph, post_date, log=print, refused=(), manifest=None, kind="broll"):
    """Picks ONE track for all versions of a reel, so the test stays fair.

    Order: config pin for this date, the manifest's audio_id, config pin for every reel, then trending.
    Tracks Instagram already refused for this reel are skipped.
    B-roll reels with an approved list (audio.approved_ids, set by Sajjad on 28 Nov 2026) only ever use
    tracks from that list: pins outside it are skipped, and instead of trending the robot rotates
    through the list by date. It never falls back to trending.
    """
    a = cfg["audio"]
    if not a.get("enabled", True):
        return {"id": None, "note": "audio turned off in config"}
    manifest = manifest or {}
    approved = [str(x) for x in (a.get("approved_ids") or []) if str(x).strip()] if kind == "broll" else []
    by_date = {str(k): str(v) for k, v in (a.get("pin_by_date") or {}).items()}
    pins = [(by_date.get(post_date), "pinned for this day in config", ""),
            (str(manifest.get("audio_id") or ""), "set in manifest", manifest.get("audio_title") or ""),
            (str(a.get("pin_audio_id") or ""), "pinned in config", "")]
    if approved:
        n = len(approved)
        start = _rotation_start(post_date, n)
        pins += [(approved[(start + i) % n], "approved list", "") for i in range(n)]
    for pin, note, title in pins:
        if not pin or pin in refused:
            continue
        if approved and pin not in approved:
            log(f"  track {pin} ({note}) is not on the approved list, skipped")
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
    if approved:
        return {"id": None, "note": "every track on the approved list was refused or skipped"}
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
    """Talking head keeps the voice (video_volume 100) under a quiet track (audio_volume 12)."""
    if not audio or not audio.get("id"):
        return None
    L = lane(cfg, kind)
    return {"audio_id": audio["id"],
            "audio_volume": L["audio_volume"],
            "video_volume": L["video_volume"]}


def _retry_key(kind):
    return {"broll": "audio_retry_after", "talking-head": "th_audio_retry_after"}.get(kind, f"{kind}_audio_retry_after")


LANE_TAGS = {"broll": "", "talking-head": "[talking head] ", "song": "[song] "}


def wake_time(nxt, now, nap_minutes):
    """When an awake run should look again: the next slot, or sooner (nap), whichever comes first.

    Short naps mean a batch, a config edit or a post-now request pushed while the robot waits
    is picked up within a few minutes instead of at the next slot."""
    return min(nxt, now + timedelta(minutes=nap_minutes))


def run(cfg, state, graph, manifests, now, log=print, checkpoint=None, post_now=()):
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

    # 3. Post-now requests: one version of the named batch goes out straight away, outside its slots.
    #    It counts towards that day, so the remaining versions keep their usual slots (nothing doubles).
    if _post_now(cfg, state, graph, manifests, now, today, log, checkpoint, post_now) == "stop":
        return

    # 4. Each kind of batch posts in its own slots. A problem in one lane never stops the other.
    for kind in KINDS:
        if _run_lane(cfg, state, graph, manifests, now, today, kind, log, checkpoint) == "stop":
            return


def _post_now(cfg, state, graph, manifests, now, today, log, checkpoint, requests):
    dry = cfg.get("dry_run", True)
    done = state.setdefault("post_now_done", [])
    for req in requests:
        rid, key = req["id"], req["batch"]
        if rid in done:
            continue
        day = state["days"].get(key)
        if day is None:
            if key in manifests and key_date(key) > today.isoformat():
                log(f"Post-now {rid}: {key} is a future day, waiting until its date.")
            else:
                log(f"Post-now {rid}: no batch {key} in the queue (missing manifest or too old). Ignored.")
                if not dry:
                    done.append(rid)
            continue
        open_ids = [i for i in day["order"] if day["variants"][i]["status"] in OPEN]
        # a half-finished upload goes first
        open_ids.sort(key=lambda i: day["variants"][i]["status"] != "container")
        if not open_ids:
            log(f"Post-now {rid}: every version of {key} is already posted or closed.")
            if not dry:
                done.append(rid)
            continue
        retry = state.get(_retry_key(day.get("kind", "broll")))
        if retry and now < datetime.fromisoformat(retry):
            log(f"Post-now {rid}: waiting for audio to work again (after {retry}).")
            continue
        if not dry:
            try:
                used, total = graph.publishing_limit()
                if used is not None and total and used >= total:
                    _limit_reached(state, today, "content_publishing_limit says the quota is used up", dry)
                    return "stop"
            except GraphError as e:
                log(f"  could not read the publishing allowance: {e}")
        log(f"Post-now {rid}: posting {key} variant {open_ids[0]} straight away.")
        result = post_one(cfg, state, graph, manifests, key, open_ids[0], now, log, checkpoint)
        if result == "limit":
            _limit_reached(state, today, day["variants"][open_ids[0]].get("error", ""), dry)
            return "stop"
        if result == "ok" and not dry:
            done.append(rid)
            save_state(state)
            if checkpoint and not checkpoint():
                return "stop"
    return None


def _run_lane(cfg, state, graph, manifests, now, today, kind, log, checkpoint):
    dry = cfg.get("dry_run", True)
    tz = local_tz(cfg)
    L = lane(cfg, kind)
    if not L.get("enabled", True) or not L["slots"]:
        return None
    tag = LANE_TAGS.get(kind, f"[{kind}] ")
    days = [d for d in sorted(state["days"]) if state["days"][d].get("kind", "broll") == kind]

    # How many posts are due right now in this lane?
    slots = lane_slot_times(cfg, kind, today, manifests)
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
            # Talking-head and song days depend on filming, so an empty day is normal: no issue.
            log(f"{tag}Slot is due but there is no {kind} batch waiting.")
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

    adds_audio = lane(cfg, day.get("kind", "broll")).get("audio", True)
    required = adds_audio and cfg["audio"].get("required", True) and cfg["audio"].get("enabled", True)
    if day["audio"] is None and not adds_audio:
        # Song reels: the song in the video is the only sound, so no track is added.
        day["audio"] = {"id": None, "note": "own sound (song reel), no track added"}
        log(f"Audio for {d}: the video's own sound (song reel)")
        if not dry:
            save_state(state)
    if day["audio"] is None:
        audio = (choose_audio(cfg, graph, d, log, day.get("audio_refused", []), manifest, day.get("kind", "broll")) if graph
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
                        new = choose_audio(cfg, graph, d, log, day["audio_refused"], manifest, day.get("kind", "broll"))
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
                      for t in lane_slot_times(cfg, kind, d, manifests) if t > now)
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
                   "voice on (video_volume 100) under a quiet trending track (audio_volume 12), and Instagram "
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
    """Stop for today and drop everything still waiting from today or earlier.
    Nothing carries over, so tomorrow's schedule starts clean on its own batches (rule set 18 Nov 2026)."""
    tomorrow = (today + timedelta(days=1)).isoformat()
    state["paused_until"] = tomorrow
    dropped = []
    for d, day in sorted(state["days"].items()):
        if key_date(d) > today.isoformat():
            continue
        for i, v in day["variants"].items():
            if v["status"] in OPEN:
                v["status"] = "skipped"
                v["skip_reason"] = "daily limit"
                dropped.append(f"{d} {i}")
    left = (f"These versions were dropped, not moved to tomorrow: {', '.join(dropped)}."
            if dropped else "Nothing else was waiting today.")
    open_issue(f"Daily limit reached on {today}",
               f"Instagram said the posting limit is reached ({why}).\n\nThe robot stopped for today. "
               f"{left} Tomorrow posts its own batches on the usual schedule. Instagram allows 10 trial "
               "reels a day, including ones posted by hand, so if this keeps happening, remove a slot "
               "in config.yml.", dry)
    if not dry:
        save_state(state)


def _local_date(iso, tz):
    return datetime.fromisoformat(iso).astimezone(tz).date()
