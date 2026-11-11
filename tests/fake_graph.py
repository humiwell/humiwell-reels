"""A pretend Instagram used by the tests. Never touches the internet."""
from reels.graph import GraphError


class FakeGraph:
    def __init__(self, limit_after=None, busy_first=False, audio_fails=False, refuse_ids=()):
        self.posts = []
        self.containers = {}
        self.limit_after = limit_after
        self.busy_first = busy_first
        self.audio_fails = audio_fails
        self.refuse_ids = set(refuse_ids)
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
        if audio and (self.audio_fails or audio["audio_id"] in self.refuse_ids):
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
