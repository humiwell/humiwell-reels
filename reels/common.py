"""Shared helpers: settings, saved state, daily batches, clock and GitHub issues."""
import json
import os
import subprocess
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "state.json"
BATCH_DIR = ROOT / "batches"
REPO = os.environ.get("GITHUB_REPOSITORY", "humiwell/humiwell-reels")


# ---- settings -------------------------------------------------------------
def load_config():
    cfg = yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8")) or {}
    if os.environ.get("FORCE_DRY_RUN") == "true":
        cfg["dry_run"] = True
    cfg.setdefault("audio", {})
    cfg.setdefault("results", {})
    cfg.setdefault("token", {})
    return cfg


# ---- clock ----------------------------------------------------------------
def now_utc():
    """The current time. Tests can pretend it is another time with NOW=2026-11-16T07:05+00:00."""
    fake = os.environ.get("NOW")
    if fake:
        return datetime.fromisoformat(fake).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def local_tz(cfg):
    return ZoneInfo(cfg.get("timezone", "Europe/London"))


def slot_times(cfg, day):
    """The posting times for one date, as UTC datetimes (summer time included)."""
    tz = local_tz(cfg)
    out = []
    for s in cfg["slots"]:
        h, m = (int(x) for x in s.split(":"))
        out.append(datetime(day.year, day.month, day.day, h, m, tzinfo=tz).astimezone(timezone.utc))
    return out


# ---- saved state ----------------------------------------------------------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"days": {}, "issues": {}, "token": {}, "paused_until": None}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---- daily batches --------------------------------------------------------
REQUIRED_VARIANT_KEYS = ("id", "lever", "hook", "file", "length_s")

# Three kinds of batch, each with its own posting "lane" (slots, audio, results timing):
#   broll         batches/YYYY-MM-DD/        silent B-roll list reels, 8 hooks (the original robot)
#   talking-head  batches/th-YYYY-MM-DD/     talking-head reels with voice, 4 hooks
#   song          batches/song-YYYY-MM-DD/   song reels: one version, the song is the only sound
KINDS = ("broll", "talking-head", "song")
TH_PREFIX = "th-"
SONG_PREFIX = "song-"
PREFIXES = {"broll": "", "talking-head": TH_PREFIX, "song": SONG_PREFIX}


def batch_kind(m):
    return (m or {}).get("kind", "broll")


def batch_key(m):
    """The folder name, release tag suffix and state key of a batch."""
    return PREFIXES.get(batch_kind(m), "") + m["post_date"]


def key_kind(key):
    if key.startswith(SONG_PREFIX):
        return "song"
    return "talking-head" if key.startswith(TH_PREFIX) else "broll"


def key_date(key):
    """The trial date of a batch key: 'song-2026-11-16', 'th-2026-11-16' and '2026-11-16' all give '2026-11-16'."""
    for prefix in (SONG_PREFIX, TH_PREFIX):
        if key.startswith(prefix):
            return key[len(prefix):]
    return key


def lane(cfg, kind):
    """Settings for one kind of batch. B-roll uses the top-level settings; talking head and song have their own blocks.

    "audio" says whether the robot adds a track at all. Song reels never get one: the song is the sound."""
    a, r = cfg.get("audio", {}), cfg.get("results", {})
    base = {"slots": cfg.get("slots", []),
            "audio_volume": int(a.get("audio_volume", 100)),
            "video_volume": int(a.get("video_volume", 0)),
            "issue_days_after": int(r.get("issue_days_after", 3)),
            "audio": True}
    if kind == "broll":
        return base
    if kind == "song":
        so = cfg.get("song") or {}
        return {"enabled": so.get("enabled", True),
                "slots": so.get("slots", []),
                "audio_volume": 0,
                "video_volume": 100,
                "issue_days_after": int(so.get("issue_days_after", 2)),
                "audio": False}
    th = cfg.get("talking_head") or {}
    return {"enabled": th.get("enabled", True),
            "slots": th.get("slots", []),
            "audio_volume": int(th.get("audio_volume", 12)),
            "video_volume": int(th.get("video_volume", 100)),
            "issue_days_after": int(th.get("issue_days_after", 2)),
            "audio": True}


def lane_slot_times(cfg, kind, day, manifests=None):
    """Slot times for one lane on one day. A B-roll day with 4 or fewer versions uses slots_4_versions
    (if set), so 4 versions spread over the day instead of filling the first 4 of the 8 slots."""
    slots = lane(cfg, kind)["slots"]
    if kind == "broll" and manifests and cfg.get("slots_4_versions"):
        m = manifests.get(day.isoformat())
        if m and len(m.get("variants", [])) <= 4:
            slots = cfg["slots_4_versions"]
    return slot_times(dict(cfg, slots=slots), day)


def load_manifests():
    """All batch manifests as {batch key: manifest}. Broken ones are reported, not used.

    The key is the folder name: '2026-11-16' for B-roll, 'th-2026-11-16' for talking head,
    'song-2026-11-16' for a song reel."""
    found, problems = {}, []
    for path in sorted(BATCH_DIR.glob("*/manifest.json")):
        try:
            m = json.loads(path.read_text(encoding="utf-8"))
            check_manifest(m, path.parent.name)
            found[path.parent.name] = m
        except Exception as e:  # noqa: BLE001 - any broken file is reported the same way
            problems.append(f"{path.relative_to(ROOT)}: {e}")
    return found, problems


POST_NOW_FILE = ROOT / "requests" / "post_now.json"


def load_post_now():
    """Requests to post one version of a batch straight away, outside its slots.

    requests/post_now.json is a list like [{"id": "2026-11-16T08:20", "batch": "th-2026-11-16"}].
    Each id is handled once (remembered in state), so the file never needs cleaning up.
    """
    if not POST_NOW_FILE.exists():
        return [], []
    try:
        items = json.loads(POST_NOW_FILE.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise ValueError("must be a list")
        good, ids = [], set()
        for r in items:
            if not isinstance(r, dict) or not r.get("id") or not r.get("batch"):
                raise ValueError("every entry needs an id and a batch")
            if r["id"] in ids:
                raise ValueError(f"id {r['id']} used twice")
            ids.add(r["id"]); good.append(r)
        return good, []
    except Exception as e:  # noqa: BLE001
        return [], [f"requests/post_now.json: {e}"]


def check_manifest(m, folder_name):
    for key in ("reel", "post_date", "caption", "variants"):
        if key not in m:
            raise ValueError(f"missing '{key}'")
    date.fromisoformat(m["post_date"])
    if batch_kind(m) not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if batch_key(m) != folder_name:
        raise ValueError(f"folder should be {batch_key(m)} for this post_date and kind, not {folder_name}")
    if not 1 <= len(m["variants"]) <= 8:
        raise ValueError("needs 1 to 8 variants")
    if batch_kind(m) == "song":
        if len(m["variants"]) != 1:
            raise ValueError("a song batch has exactly one version")
        if m.get("audio_id") is not None or m.get("audio_title") is not None:
            raise ValueError("a song batch can't set audio_id: the song in the video is the only sound")
    if len(m["caption"]) > 2200:
        raise ValueError("caption is over 2,200 characters")
    # Optional: one chosen track for the whole day.
    audio_id = m.get("audio_id")
    if audio_id is not None and not (isinstance(audio_id, str) and audio_id.isdigit()):
        raise ValueError("audio_id must be a text string of digits, for example \"1543916142623294\"")
    if m.get("audio_title") is not None:
        if not isinstance(m["audio_title"], str):
            raise ValueError("audio_title must be text")
        if audio_id is None:
            raise ValueError("audio_title is set but audio_id is missing")
    ids = set()
    for v in m["variants"]:
        for key in REQUIRED_VARIANT_KEYS:
            if key not in v:
                raise ValueError(f"variant missing '{key}'")
        if v["id"] in ids:
            raise ValueError(f"variant id {v['id']} used twice")
        ids.add(v["id"])
        if not 3 <= float(v["length_s"]) <= 90:
            raise ValueError(f"variant {v['id']} length_s should be 3 to 90 seconds")


def release_tag(key):
    return f"day-{key}"


def video_url(cfg, key, filename):
    """key is the batch key (folder name), for example 2026-11-16 or th-2026-11-16."""
    post_date = key
    owner, name = REPO.split("/")
    hosting = cfg.get("hosting", "release")
    if hosting == "pages":
        return f"https://{owner}.github.io/{name}/{post_date}/{filename}"
    if hosting == "raw":
        return f"https://raw.githubusercontent.com/{REPO}/media/{post_date}/{filename}"
    return f"https://github.com/{REPO}/releases/download/{release_tag(post_date)}/{filename}"


# ---- GitHub issues --------------------------------------------------------
def _gh_headers():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def open_issue(title, body, dry_run=False, labels=("robot",)):
    """Opens a GitHub issue unless one with the same title is already open."""
    headers = _gh_headers()
    if dry_run or not headers:
        print(f"[issue{' (dry run)' if dry_run else ''}] {title}\n{body}\n")
        return
    api = f"https://api.github.com/repos/{REPO}/issues"
    r = requests.get(api, headers=headers, params={"state": "open", "per_page": 100}, timeout=30)
    r.raise_for_status()
    if any(i["title"] == title for i in r.json()):
        print(f"[issue already open] {title}")
        return
    # Assigned to the repo owner so the GitHub phone app's "Assigned" push notification fires.
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or REPO.split("/")[0]
    r = requests.post(api, headers=headers, timeout=30,
                      json={"title": title, "body": body, "labels": list(labels), "assignees": [owner]})
    r.raise_for_status()
    print(f"[issue opened] {title}: {r.json().get('html_url')}")


def commit_progress():
    """On GitHub only: saves state and results to the repo, and pulls in new batches or settings.

    Returns True when this copy and GitHub agree afterwards (always True off GitHub). The robot only
    posts right after a True, so it never acts on an out-of-date copy (that is how duplicates happened).
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return True

    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)

    git("config", "user.name", "reels-robot")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    for p in ("state", "results", "results.csv"):
        if (ROOT / p).exists():
            git("add", p)
    if git("diff", "--cached", "--quiet").returncode != 0:
        git("commit", "-m", "Robot: update state and results")
    for _ in range(3):
        if git("pull", "--rebase", "--quiet").returncode == 0 and git("push", "--quiet").returncode == 0:
            return True
        git("rebase", "--abort")
        time.sleep(10)
    print("Could not sync progress with GitHub.")
    return False


def set_repo_secret(name, value):
    """Saves a new secret value with the GitHub CLI. Needs GH_SECRETS_TOKEN. Never prints the value."""
    admin = os.environ.get("GH_SECRETS_TOKEN")
    if not admin:
        return False
    env = dict(os.environ, GH_TOKEN=admin)
    subprocess.run(["gh", "secret", "set", name, "--repo", REPO], input=value.encode(),
                   env=env, check=True, capture_output=True)
    return True
