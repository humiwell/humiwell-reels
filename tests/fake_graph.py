"""A pretend Instagram used by the tests. Never touches the internet."""
from datetime import datetime, timedelta, timezone

from reels.graph import GraphError


class FakeGraph:
    def __init__(self, limit_after=None, busy_first=False, audio_fails=False, refuse_ids=(), refuse_with_voice=False):
        self.posts = []
        self.containers = {}
        self.limit_after = limit_after
        self.busy_first = busy_first
        self.audio_fails = audio_fails
        self.refuse_ids = set(refuse_ids)
        self.refuse_with_voice = refuse_with_voice  # pretend Instagram refuses a track when the voice is on
        self.token = "fake"

    def publishing_limit(self):
        return len(self.posts), 50

    def trending_audio(self, kind):
        return [{"id": "111", "title": "Blocked Song", "artist": "Nobody", "type": kind},
                {"id": "222", "title": f"Top {kind}", "artist": "Artist", "type": kind}]

    def audio_info(self, audio_id):
        return {"id": audio_id, "title": "Pinned", "artist": "Someone", "type": "music"}

    def create_reel_container(self, url, caption, strategy=None, audio=None, upload="url"):
        if self.limit_after is not None and len(self.posts) >= self.limit_after:
            raise GraphError(400, 9, 2207042, "You reached maximum number of posts")
        cid = f"c{len(self.containers) + 1}"
        status = "IN_PROGRESS" if self.busy_first else "FINISHED"
        voice_refused = self.refuse_with_voice and audio and audio.get("video_volume", 0) > 0
        if audio and (self.audio_fails or audio["audio_id"] in self.refuse_ids or voice_refused):
            status = "ERROR"
        self.containers[cid] = {"url": url, "audio": audio, "strategy": strategy, "status": status}
        self.busy_first = False
        return cid

    def container_status(self, cid):
        return self.containers[cid]["status"], None

    def wait_for_container(self, cid, tries=10, every=30):
        status = self.containers[cid]["status"]
        if status == "ERROR":
            raise GraphError(400, message="container ERROR: Media upload has failed with error code 2207082")
        return status

    def publish(self, cid):
        self.containers[cid]["status"] = "PUBLISHED"
        self.posts.append(self.containers[cid])
        return f"m{len(self.posts)}"

    def media_info(self, media_id):
        return {"permalink": f"https://instagram.com/reel/{media_id}"}

    def insights(self, media_id, metrics):
        n = int(media_id[1:])
        return {"reach": 100 + 40 * n, "views": 300, "ig_reels_avg_watch_time": 3000 + 700 * n,
                "shares": n, "saved": 2, "likes": 10, "comments": 1, "reels_skip_rate": 30,
                "total_interactions": 13, "follows": None}

    def token_info(self, token=None):
        return {"is_valid": True, "expires_at": 0}

    # ---- read-only calls used by the dashboard snapshot (reels/account.py) ----
    ig_user_id = "17840000000000000"
    media_total = 45           # how many posts the fake account has (paged 25 at a time)
    refuse_account = {"profile_views", "website_clicks"}  # account metrics Instagram "refuses" (code 100)
    refuse_media = {"REELS": {"follows"}}                 # media metrics refused per media_product_type
    audio_down = False
    rate_limit_after = None    # account insight calls allowed before Instagram says "too many calls"

    def get(self, path, params=None, retries=None):
        params = params or {}
        self.reads = getattr(self, "reads", []) + [(path, dict(params))]
        if path == self.ig_user_id:
            return {"id": self.ig_user_id, "username": "humiwell", "followers_count": 1234,
                    "follows_count": 56, "media_count": self.media_total}
        if path == f"{self.ig_user_id}/insights":
            self.account_calls = getattr(self, "account_calls", 0) + 1
            if self.rate_limit_after is not None and self.account_calls > self.rate_limit_after:
                raise GraphError(400, 4, None, "Application request limit reached")
            metrics = params["metric"].split(",")
            if any(m in self.refuse_account for m in metrics):
                raise GraphError(400, 100, None, "The metric is not supported")
            if metrics == ["follower_count"]:
                first = datetime.fromtimestamp(params["since"], timezone.utc).date()
                last = datetime.fromtimestamp(params["until"], timezone.utc).date()
                values, d = [], first
                while d < last:  # value for day d ends next day 08:00 UTC (midnight Pacific)
                    values.append({"value": 3, "end_time": (d + timedelta(days=1)).strftime("%Y-%m-%dT08:00:00+0000")})
                    d += timedelta(days=1)
                return {"data": [{"name": "follower_count", "period": "day", "values": values}]}
            if metrics == ["follows_and_unfollows"]:
                return {"data": [{"name": "follows_and_unfollows", "period": "day", "total_value": {
                    "value": 9, "breakdowns": [{"dimension_keys": ["follow_type"], "results": [
                        {"dimension_values": ["FOLLOWER"], "value": 7},
                        {"dimension_values": ["NON_FOLLOWER"], "value": 2}]}]}}]}
            scale = 28 if params["until"] - params["since"] > 86400 else 1
            return {"data": [{"name": m, "period": "day", "total_value": {"value": 10 * scale}} for m in metrics]}
        if path == f"{self.ig_user_id}/media":
            start = int(params.get("after") or 0)
            end = min(start + int(params.get("limit", 25)), self.media_total)
            data = [self._media(i) for i in range(start, end)]
            paging = {"cursors": {"after": str(end)}}
            if end < self.media_total:
                paging["next"] = "https://graph.facebook.com/next"
            return {"data": data, "paging": paging}
        if path.endswith("/insights") and path.startswith("m"):
            i = int(path.split("/")[0][1:]) - 1
            kind = self._media(i)["media_product_type"]
            metrics = params["metric"].split(",")
            if any(m in self.refuse_media.get(kind, set()) for m in metrics):
                raise GraphError(400, 100, None, "metric not supported for this media")
            return {"data": [{"name": m, "period": "lifetime", "values": [{"value": 100 + i}]} for m in metrics]}
        raise GraphError(400, 100, None, f"unknown path {path}")

    def _media(self, i):
        """Post m{i+1}: newest first, one a day back from 2026-11-22; even i are reels."""
        when = datetime(2026, 11, 22, 10, tzinfo=timezone.utc) - timedelta(days=i)
        return {"id": f"m{i + 1}", "caption": "x" * 500, "media_type": "VIDEO",
                "media_product_type": "REELS" if i % 2 == 0 else "FEED", "permalink": f"https://p/{i}",
                "timestamp": when.strftime("%Y-%m-%dT%H:%M:%S+0000"), "like_count": 3, "comments_count": 1,
                "thumbnail_url": f"https://cdn/{i}.jpg?secret-ish"}

    def audio_search_raw(self, audio_type, id_param="user_id", search=None):
        if self.audio_down:
            raise GraphError(500, 2, None, "audio down")
        return {"audio": [{"audio_id": str(i), "title": f"Song {i}", "display_artist": "Band",
                           "duration_in_ms": 30000} for i in range(30)]}
