"""Once a day: checks when the Instagram token runs out, renews it if allowed, reminds you if not."""
import os
from datetime import datetime, timedelta, timezone

from .common import open_issue, save_state, set_repo_secret
from .graph import GraphError


def run(cfg, state, graph, now, log=print):
    t = state.setdefault("token", {})
    if t.get("checked_at") and now - datetime.fromisoformat(t["checked_at"]) < timedelta(hours=20):
        return
    t_cfg = cfg["token"]
    dry = cfg.get("dry_run", True)
    try:
        info = graph.token_info()
    except GraphError as e:
        log(f"Token check failed: {e}")
        open_issue("Instagram token check failed",
                   f"The robot could not check the Instagram token:\n\n```\n{e}\n```\n\n"
                   "If it has expired, follow 'Renew the token' in the README.", dry)
        return
    if not info.get("is_valid", False):
        open_issue("Instagram token is not valid",
                   "Posting will fail until you make a new token. Follow 'Renew the token' in the README.", dry)
        return
    expires = int(info.get("expires_at") or 0)
    days_left = None if expires == 0 else (expires - now.timestamp()) / 86400
    log("Token: never expires." if days_left is None else f"Token: {days_left:.0f} days left.")

    renewed = False
    if days_left is not None and t_cfg.get("auto_renew", True) and days_left < 53:
        renewed, days_left = _renew(graph, days_left, dry, log)

    t["checked_at"] = now.isoformat()
    t["expires_on"] = None if days_left is None else (now + timedelta(days=days_left)).date().isoformat()
    if renewed:
        t["renewed_at"] = now.isoformat()
    warn = int(t_cfg.get("warn_days_before_expiry", 10))
    if days_left is not None and days_left <= warn:
        open_issue(f"Instagram token runs out on {t['expires_on']}",
                   f"About {days_left:.0f} days left and automatic renewal "
                   f"{'is not set up' if not os.environ.get('GH_SECRETS_TOKEN') else 'did not work'}. "
                   "Follow 'Renew the token' in the README before that date, or posting stops.", dry)
    save_state(state)


def _renew(graph, days_left, dry, log):
    if not os.environ.get("GH_SECRETS_TOKEN"):
        log("Auto renew skipped: GH_SECRETS_TOKEN secret is not set.")
        return False, days_left
    if dry:
        log("[DRY RUN] would renew the token now.")
        return False, days_left
    try:
        new_token, _ = graph.exchange_token()
        new_info = graph.token_info(new_token)
    except GraphError as e:
        log(f"Token renewal failed: {e}")
        return False, days_left
    new_exp = int(new_info.get("expires_at") or 0)
    new_days = None if new_exp == 0 else (new_exp - datetime.now(timezone.utc).timestamp()) / 86400
    if new_days is not None and new_days <= days_left + 1:
        log("Renewal gave no extra time, keeping the old token.")
        return False, days_left
    set_repo_secret("IG_ACCESS_TOKEN", new_token)
    graph.token = new_token
    log("Token renewed and saved." + ("" if new_days is None else f" Now {new_days:.0f} days left."))
    return True, new_days
