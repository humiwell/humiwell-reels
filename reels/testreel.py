"""One-off checks for the four unknowns. Only 'post' makes anything public, and only with confirm=POST."""
import json

import requests

from .common import REPO, ROOT, now_utc
from .graph import GraphError
from .publish import choose_audio, audio_config
from .results import METRICS

TEST_FILE = ROOT / "state" / "test.json"
owner, name = REPO.split("/")
HOSTS = {
    "release": f"https://github.com/{REPO}/releases/download/test/test.mp4",
    "pages": f"https://{owner}.github.io/{name}/test/test.mp4",
    "raw": f"https://raw.githubusercontent.com/{REPO}/media/test/test.mp4",
}


def _save(data):
    TEST_FILE.parent.mkdir(exist_ok=True)
    TEST_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _load():
    return json.loads(TEST_FILE.read_text(encoding="utf-8")) if TEST_FILE.exists() else {}


def check(cfg, graph):
    """Read-only checks plus upload-only containers that are never published."""
    out = _load()
    print("== 1. Token ==")
    try:
        info = graph.token_info()
        exp = int(info.get("expires_at") or 0)
        days = None if exp == 0 else round((exp - now_utc().timestamp()) / 86400, 1)
        print(f"valid={info.get('is_valid')} type={info.get('type')} days_left={days} scopes={info.get('scopes')}")
        out["token_days_left_before"] = days
    except GraphError as e:
        print(f"token check failed: {e}")

    print("\n== 2. Publishing allowance ==")
    try:
        print("used, total =", graph.publishing_limit())
    except GraphError as e:
        print(f"failed: {e}")

    print("\n== 3. Trending audio (top 5 of each) ==")
    tracks = {}
    for kind in ("music", "original_sound"):
        try:
            tracks[kind] = graph.trending_audio(kind)
            for t in tracks[kind][:5]:
                print(f"  {kind}: {t['title']} | {t['artist']} | id {t['id']} | ads_eligible {t['ads_eligible']}")
        except GraphError as e:
            tracks[kind] = []
            print(f"  {kind}: failed: {e}")

    print("\n== 4. Can the video links be reached? ==")
    for host, url in HOSTS.items():
        try:
            r = requests.head(url, allow_redirects=True, timeout=30)
            print(f"  {host}: HTTP {r.status_code}, type {r.headers.get('content-type')}, "
                  f"redirects {len(r.history)}")
        except requests.RequestException as e:
            print(f"  {host}: failed {e}")

    print("\n== 5. Upload-only tests (nothing is published) ==")
    trial = cfg.get("graduation_strategy", "MANUAL")
    url = HOSTS["release"]
    cases = [("trial only", url, trial, None)]
    for kind in ("music", "original_sound"):
        for t in tracks.get(kind, [])[:2]:
            aud = audio_config(cfg, t)
            name = f"{kind} '{t['title'][:30]}' (ads_eligible {t['ads_eligible']})"
            cases.append((f"{name}, no trial", url, None, aud))
            cases.append((f"{name}, with trial", url, trial, aud))
    out["containers"] = {}
    for label, url, strat, aud in cases:
        try:
            cid = graph.create_reel_container(url, "test", strat, aud)
            status = graph.wait_for_container(cid)
            print(f"  {label}: {status}")
        except GraphError as e:
            status = f"FAILED {e}"
            print(f"  {label}: {status}")
        out["containers"][label] = status

    print("\n== 6. Can the token be renewed? (new token is NOT saved) ==")
    try:
        new_token, expires_in = graph.exchange_token()
        new_info = graph.token_info(new_token)
        exp = int(new_info.get("expires_at") or 0)
        days = None if exp == 0 else round((exp - now_utc().timestamp()) / 86400, 1)
        print(f"  exchange worked. expires_in={expires_in} new days_left={days}")
        out["token_days_left_after_renew"] = days
    except GraphError as e:
        print(f"  renewal failed: {e}")
        out["token_days_left_after_renew"] = f"failed: {e}"
    _save(out)


def post(cfg, graph, host, confirm):
    if confirm != "POST":
        print("Not posted. Type POST in the confirm box to publish the one test reel.")
        return
    out = _load()
    if out.get("media_id"):
        print(f"A test reel was already posted (media id {out['media_id']}). Not posting another.")
        return
    audio = choose_audio(cfg, graph, "test")
    print(f"Audio: {audio.get('title')} by {audio.get('artist')} (id {audio.get('id')})")
    cid = graph.create_reel_container(HOSTS[host], "Test reel, please ignore.",
                                      cfg.get("graduation_strategy", "MANUAL"), audio_config(cfg, audio))
    status = graph.wait_for_container(cid, tries=20)
    print(f"Container: {status}")
    if status != "FINISHED":
        return
    media_id = graph.publish(cid)
    info = graph.media_info(media_id)
    print(f"Posted. media id {media_id}. Details: {info}")
    out.update(media_id=media_id, posted_at=now_utc().isoformat(), host=host, audio=audio, media_info=info)
    _save(out)


def insights(cfg, graph):
    out = _load()
    if not out.get("media_id"):
        print("No test reel posted yet.")
        return
    print(f"Insights for test reel {out['media_id']} (posted {out['posted_at']}):")
    found = {}
    for m in METRICS:
        try:
            found[m] = graph.insights(out["media_id"], [m])[m]
        except GraphError as e:
            found[m] = f"error: {e}"
        print(f"  {m}: {found[m]}")
    out.setdefault("insights", []).append({"at": now_utc().isoformat(), "values": found})
    _save(out)
