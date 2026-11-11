"""Small client for the Instagram Graph API (Facebook Login route).

Secrets are only ever sent to graph.facebook.com and never printed.
"""
import json
import time

import requests

BASE = "https://graph.facebook.com"

# Error codes Meta uses for "try again later" problems.
TRANSIENT_CODES = {1, 2, 4, 17, 32, 341, 613, -1, -2}
TRANSIENT_SUBCODES = {2207001, 2207003, 2207008, 2207032, 2207053}
INVALID_METRIC_CODES = {100}


class GraphError(Exception):
    def __init__(self, status, code=None, subcode=None, message="", transient=False):
        self.status = status
        self.code = code
        self.subcode = subcode
        self.message = message
        self.transient = transient
        super().__init__(f"HTTP {status}, code {code}, subcode {subcode}: {message}")

    @property
    def is_limit(self):
        """True when Instagram says the posting (or trial reel) limit is reached."""
        if self.code == 9 or self.subcode == 2207042:
            return True
        msg = (self.message or "").lower()
        return "limit" in msg and ("trial" in msg or "maximum" in msg or "reached" in msg)

    @property
    def is_temporary(self):
        if self.transient or self.status >= 500:
            return True
        return self.code in TRANSIENT_CODES or self.subcode in TRANSIENT_SUBCODES


def _scrub(text, secrets):
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


class Graph:
    def __init__(self, token, ig_user_id, version="v27.0", app_id="", app_secret="",
                 sleep=time.sleep, log=print):
        self.token = token
        self.ig_user_id = ig_user_id
        self.version = version
        self.app_id = app_id
        self.app_secret = app_secret
        self.sleep = sleep
        self.log = log

    # ---- low level -------------------------------------------------------
    def _call(self, method, path, params=None, token=None, retries=3, versioned=True):
        params = dict(params or {})
        params["access_token"] = token or self.token
        for k, v in list(params.items()):
            if isinstance(v, (dict, list)):
                params[k] = json.dumps(v)
        url = f"{BASE}/{self.version}/{path}" if versioned else f"{BASE}/{path}"
        secrets = [self.token, self.app_secret, params["access_token"]]
        wait = 30
        for attempt in range(retries + 1):
            try:
                if method == "GET":
                    r = requests.get(url, params=params, timeout=60)
                else:
                    r = requests.post(url, data=params, timeout=120)
            except requests.RequestException as e:
                err = GraphError(0, message=_scrub(str(e), secrets), transient=True)
            else:
                try:
                    body = r.json()
                except ValueError:
                    body = {}
                if r.ok and "error" not in body:
                    return body
                e = body.get("error", {}) if isinstance(body, dict) else {}
                err = GraphError(
                    r.status_code,
                    e.get("code"),
                    e.get("error_subcode"),
                    _scrub(e.get("error_user_msg") or e.get("message") or r.text[:300], secrets),
                    bool(e.get("is_transient")),
                )
            if err.is_temporary and not err.is_limit and attempt < retries:
                self.log(f"  temporary error, waiting {wait}s then retrying: {err}")
                self.sleep(wait)
                wait *= 2
                continue
            raise err

    # ---- publishing ------------------------------------------------------
    def publishing_limit(self):
        body = self._call("GET", f"{self.ig_user_id}/content_publishing_limit",
                          {"fields": "config,quota_usage"})
        data = (body.get("data") or [{}])[0]
        return data.get("quota_usage"), (data.get("config") or {}).get("quota_total")

    def create_reel_container(self, video_url, caption, trial_strategy=None, audio=None, upload="url"):
        """upload: "url" (Instagram downloads video_url), "file_url" or "bytes" (resumable upload)."""
        params = {"media_type": "REELS", "caption": caption}
        if upload == "url":
            params["video_url"] = video_url
        else:
            params["upload_type"] = "resumable"
        if trial_strategy:
            params["trial_params"] = {"graduation_strategy": trial_strategy}
        if audio:
            params["audio_configuration"] = audio
        cid = self._call("POST", f"{self.ig_user_id}/media", params, retries=2)["id"]
        if upload != "url":
            self._resumable_upload(cid, video_url, upload)
        return cid

    def _resumable_upload(self, cid, video_url, how):
        url = f"https://rupload.facebook.com/ig-api-upload/{self.version}/{cid}"
        headers = {"Authorization": f"OAuth {self.token}"}
        if how == "file_url":
            headers["file_url"] = video_url
            r = requests.post(url, headers=headers, timeout=300)
        else:
            data = requests.get(video_url, timeout=300).content
            headers.update(offset="0", file_size=str(len(data)))
            r = requests.post(url, headers=headers, data=data, timeout=300)
        if not r.ok:
            raise GraphError(r.status_code, message=_scrub(r.text[:300], [self.token]))

    def container_status(self, container_id):
        body = self._call("GET", container_id, {"fields": "status_code,status"})
        return body.get("status_code"), body.get("status")

    def wait_for_container(self, container_id, tries=10, every=30):
        """Returns FINISHED, PUBLISHED or IN_PROGRESS (still busy). Raises on ERROR/EXPIRED."""
        for i in range(tries):
            code, status = self.container_status(container_id)
            if code in ("FINISHED", "PUBLISHED"):
                return code
            if code in ("ERROR", "EXPIRED"):
                raise GraphError(400, message=f"container {code}: {status}")
            if i < tries - 1:
                self.sleep(every)
        return "IN_PROGRESS"

    def publish(self, container_id):
        return self._call("POST", f"{self.ig_user_id}/media_publish",
                          {"creation_id": container_id}, retries=2)["id"]

    def media_info(self, media_id):
        return self._call("GET", media_id,
                          {"fields": "permalink,media_product_type,timestamp,media_audio_type"})

    # ---- audio -----------------------------------------------------------
    def audio_search_raw(self, audio_type, id_param="user_id", search=None):
        """The Audio API's answer exactly as Instagram sends it."""
        params = {"audio_type": audio_type, id_param: self.ig_user_id}
        if search:
            params["search_query"] = search
        return self._call("GET", "ig_audio", params)

    def trending_audio(self, audio_type, id_param="user_id", search=None):
        body = self.audio_search_raw(audio_type, id_param, search)
        items = body.get("audio") or body.get("data") or []
        return [normalise_audio(a, audio_type) for a in items]

    def audio_info(self, audio_id):
        body = self._call("GET", str(audio_id), {"user_id": self.ig_user_id})
        return normalise_audio(body, body.get("audio_type", ""))

    # ---- insights --------------------------------------------------------
    def insights(self, media_id, metrics):
        """Returns {metric: value or None}. Metrics Instagram refuses come back as None."""
        try:
            body = self._call("GET", f"{media_id}/insights", {"metric": ",".join(metrics)})
            return _parse_insights(body, metrics)
        except GraphError as e:
            if e.code not in INVALID_METRIC_CODES:
                raise
        out = {}
        for m in metrics:
            try:
                body = self._call("GET", f"{media_id}/insights", {"metric": m})
                out[m] = _parse_insights(body, [m])[m]
            except GraphError as e:
                if e.code not in INVALID_METRIC_CODES:
                    raise
                out[m] = None
        return out

    # ---- token -----------------------------------------------------------
    def token_info(self, token=None):
        body = self._call("GET", "debug_token",
                          {"input_token": token or self.token},
                          token=f"{self.app_id}|{self.app_secret}", versioned=False)
        return body.get("data", {})

    def exchange_token(self):
        body = self._call("GET", "oauth/access_token", {
            "grant_type": "fb_exchange_token",
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "fb_exchange_token": self.token,
        }, retries=1)
        return body["access_token"], body.get("expires_in")


def normalise_audio(a, audio_type):
    return {
        "id": str(a.get("audio_id") or a.get("id") or ""),
        "title": a.get("title") or "",
        "artist": a.get("display_artist") or a.get("ig_username") or "",
        "type": a.get("audio_type") or audio_type,
        "duration_ms": a.get("duration_in_ms"),
        "ads_eligible": a.get("is_ads_eligible"),
    }


def _parse_insights(body, metrics):
    out = {m: None for m in metrics}
    for row in body.get("data", []):
        values = row.get("values") or []
        if values:
            out[row.get("name")] = values[0].get("value")
        elif "total_value" in row:
            out[row.get("name")] = (row["total_value"] or {}).get("value")
    return out
