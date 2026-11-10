"""Shared helpers: settings, saved state, daily batches, clock and GitHub issues."""
import json
import os
import subprocess
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


def load_manifests():
    """All day manifests as {date string: manifest}. Broken ones are reported, not used."""
    found, problems = {}, []
    for path in sorted(BATCH_DIR.glob("*/manifest.json")):
        try:
            m = json.loads(path.read_text(encoding="utf-8"))
            check_manifest(m, path.parent.name)
            found[m["post_date"]] = m
        except Exception as e:  # noqa: BLE001 - any broken file is reported the same way
            problems.append(f"{path.relative_to(ROOT)}: {e}")
    return found, problems


def check_manifest(m, folder_name):
    for key in ("reel", "post_date", "caption", "variants"):
        if key not in m:
            raise ValueError(f"missing '{key}'")
    date.fromisoformat(m["post_date"])
    if m["post_date"] != folder_name:
        raise ValueError(f"post_date {m['post_date']} does not match folder {folder_name}")
    if not 1 <= len(m["variants"]) <= 8:
        raise ValueError("needs 1 to 8 variants")
    if len(m["caption"]) > 2200:
        raise ValueError("caption is over 2,200 characters")
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


def release_tag(post_date):
    return f"day-{post_date}"


def video_url(cfg, post_date, filename):
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
    r = requests.post(api, headers=headers, json={"title": title, "body": body, "labels": list(labels)},
                      timeout=30)
    r.raise_for_status()
    print(f"[issue opened] {title}: {r.json().get('html_url')}")


def set_repo_secret(name, value):
    """Saves a new secret value with the GitHub CLI. Needs GH_SECRETS_TOKEN. Never prints the value."""
    admin = os.environ.get("GH_SECRETS_TOKEN")
    if not admin:
        return False
    env = dict(os.environ, GH_TOKEN=admin)
    subprocess.run(["gh", "secret", "set", name, "--repo", REPO], input=value.encode(),
                   env=env, check=True, capture_output=True)
    return True
