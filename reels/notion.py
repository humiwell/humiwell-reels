"""Keeps the Notion calendars in step with the robot.

- When every version of a day has been posted, the day's Notion row gets Status "Posted".
- When the results issue for a day with several versions is written (B-roll and talking head), the row
  gets the winner: whichever of "Winner", "Winner hook", "Winner link" and "Winner note" the database has.

Notion never holds up posting: any problem is logged, kept in the state and tried again next run.
The row is found by the manifest's optional "notion_page" (a page id or link), otherwise by its Date:
trial date + notion.<lane>.days_after_trial (B-roll reels go on the feed 3 days after the trial).
Needs the NOTION_TOKEN secret, from a Notion integration that is connected to the three databases.
"""
import json
import os
import re
from datetime import date, timedelta

import requests

from . import results
from .common import key_date, key_kind, open_issue

API = "https://api.notion.com/v1"
VERSION = "2025-09-03"
OPEN = ("pending", "container")
# When a date has more than one row, these statuses mark the one the robot is posting.
LIVE_STATUSES = ("Approved", "Scheduled", "Posted", "Hooks approved")
LANE_KEYS = {"broll": "broll", "talking-head": "talking_head", "song": "song"}


class NotionError(Exception):
    pass


class Notion:
    def __init__(self, token, session=None):
        self.s = session or requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Notion-Version": VERSION,
                               "Content-Type": "application/json"})
        self._schemas = {}

    def _call(self, method, path, body=None):
        r = self.s.request(method, f"{API}/{path}", data=None if body is None else json.dumps(body), timeout=30)
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", "")
            except ValueError:
                msg = r.text[:200]
            raise NotionError(f"HTTP {r.status_code}: {msg}")
        return r.json()

    def schema(self, data_source):
        if data_source not in self._schemas:
            self._schemas[data_source] = self._call("GET", f"data_sources/{data_source}").get("properties", {})
        return self._schemas[data_source]

    def rows_on(self, data_source, day):
        body = {"filter": {"property": "Date", "date": {"equals": day}}, "page_size": 20}
        return self._call("POST", f"data_sources/{data_source}/query", body).get("results", [])

    def page(self, page_id):
        return self._call("GET", f"pages/{page_id}")

    def update(self, page_id, properties):
        return self._call("PATCH", f"pages/{page_id}", {"properties": properties})


def make_client():
    # strip() also drops the invisible BOM Windows PowerShell adds when a secret is piped to gh.
    token = os.environ.get("NOTION_TOKEN", "").replace("﻿", "").strip()
    return Notion(token) if token else None


def page_id(text):
    """A page id from an id or a Notion link (the last 32 hex characters)."""
    found = re.findall(r"(?<![0-9a-fA-F])([0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?"
                       r"[0-9a-fA-F]{12})(?![0-9a-fA-F])", str(text or ""))
    return found[-1].replace("-", "").lower() if found else None


def _status_of(page):
    prop = (page.get("properties") or {}).get("Status") or {}
    val = prop.get("select") or prop.get("status") or {}
    return val.get("name")


def find_row(client, lane_cfg, key, manifest):
    """The Notion page id for a batch, or raises NotionError saying why it can't be found."""
    if manifest and manifest.get("notion_page"):
        pid = page_id(manifest["notion_page"])
        if pid:
            return pid
    day = (date.fromisoformat(key_date(key)) + timedelta(days=int(lane_cfg.get("days_after_trial", 0)))).isoformat()
    rows = client.rows_on(lane_cfg["data_source"], day)
    if len(rows) > 1:
        rows = [r for r in rows if _status_of(r) in LIVE_STATUSES] or rows
    if len(rows) != 1:
        raise NotionError(f"{len(rows)} rows dated {day}, so the robot can't tell which one is {key}")
    return rows[0]["id"].replace("-", "")


def _value(prop_type, value):
    if prop_type in ("select", "status"):
        return {prop_type: {"name": str(value)[:100]}}
    if prop_type == "url":
        return {"url": value or None}
    if prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": str(value)[:2000]}}]}
    return None


def props_for(schema, wanted):
    """Only the properties the database actually has, written in the right shape for their type."""
    out = {}
    for name, value in wanted.items():
        if value is None or name not in schema:
            continue
        v = _value(schema[name].get("type"), value)
        if v is not None:
            out[name] = v
    return out


def winner_fields(report):
    top = next((r for r in report.get("variants", []) if r.get("variant") == report.get("winner")), {})
    note = ("Winner. " if report.get("trusted") else "Early leader, not trusted yet. ") + str(report.get("why", ""))
    if top.get("watch_pct") is not None:
        note += f" Watch {top['watch_pct']}%, reach {top.get('reach')}."
    return {"Winner": report.get("winner"), "Winner hook": top.get("hook"),
            "Winner link": top.get("permalink"), "Winner note": note.strip()}


def _done_posting(day):
    statuses = [v.get("status") for v in day.get("variants", {}).values()]
    return bool(statuses) and not any(s in OPEN for s in statuses) and "posted" in statuses


def _report(key):
    path = results.ROOT / "results" / f"{key}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def check(cfg, manifests, client=None, log=print):
    """Read-only: for each lane, opens the database and finds the row for its first trial day from today."""
    client = client or make_client()
    if client is None:
        log("NOTION_TOKEN is not set.")
        return 1
    n_cfg = cfg.get("notion") or {}
    today = date.today().isoformat()
    bad = 0
    for kind, lane in LANE_KEYS.items():
        lane_cfg = n_cfg.get(lane) or {}
        if not lane_cfg.get("data_source"):
            continue
        try:
            schema = client.schema(lane_cfg["data_source"])
            missing = [p for p in ("Status", "Date") if p not in schema]
            log(f"{lane}: database OK ({len(schema)} properties){'; missing ' + str(missing) if missing else ''}")
            keys = sorted(k for k in manifests if key_kind(k) == kind and key_date(k) >= today)
            if keys:
                pid = find_row(client, lane_cfg, keys[0], manifests.get(keys[0]))
                log(f"  next day {keys[0]} -> row {pid}")
            else:
                log("  no upcoming batch to look up")
        except (NotionError, requests.RequestException) as e:
            bad += 1
            log(f"{lane}: PROBLEM {e}")
    return 1 if bad else 0


def run(cfg, state, manifests, client=None, log=print):
    n_cfg = cfg.get("notion") or {}
    if not n_cfg.get("enabled", False):
        return
    if client is None:
        client = make_client()
    if client is None:
        log("Notion: NOTION_TOKEN is not set, so Notion is not updated.")
        return
    dry = cfg.get("dry_run", True)
    start = str(n_cfg.get("start_date", "2000-01-01"))
    posted_name = n_cfg.get("posted_status", "Posted")
    for key, day in sorted(state.get("days", {}).items()):
        lane_cfg = n_cfg.get(LANE_KEYS.get(key_kind(key), ""), {})
        if key_date(key) < start or not lane_cfg.get("data_source"):
            continue
        rec = day.setdefault("notion", {})
        want_posted = not rec.get("posted") and _done_posting(day)
        report = _report(key) if day.get("results_done") and not rec.get("winner") else None
        want_winner = bool(report and report.get("winner") and len(report.get("variants", [])) > 1)
        if not (want_posted or want_winner):
            continue
        try:
            schema = client.schema(lane_cfg["data_source"])
            if not rec.get("page"):
                rec["page"] = find_row(client, lane_cfg, key, manifests.get(key))
            if want_posted:
                props = props_for(schema, {"Status": posted_name})
                if dry:
                    log(f"Notion (dry run): would set {key} to {posted_name}")
                else:
                    client.update(rec["page"], props)
                    rec["posted"] = True
                    log(f"Notion: {key} set to {posted_name}")
            if want_winner:
                props = props_for(schema, winner_fields(report))
                if dry:
                    log(f"Notion (dry run): would add winner {report['winner']} to {key}")
                else:
                    if props:
                        client.update(rec["page"], props)
                    rec["winner"] = report["winner"]
                    log(f"Notion: {key} winner {report['winner']}")
            rec.pop("error", None)
        except (NotionError, requests.RequestException) as e:
            msg = str(e)
            log(f"Notion: could not update {key}: {msg}")
            if rec.get("error") != msg:
                rec["error"] = msg
                open_issue(f"Notion not updated for {key}",
                           f"The robot could not update the Notion row for {key}: {msg}\n\n"
                           "Posting is not affected. The robot tries again every run. If the row can't be found, "
                           "add \"notion_page\" (the row's link) to the day's manifest. If it says the page or "
                           "database is not shared, connect the Humiwell robot integration to the database "
                           "(... menu, Connections).", dry)
