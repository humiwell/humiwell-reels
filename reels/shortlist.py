"""Lists the current trending music with every field the Audio API returns."""
import json

# Words that would suggest a "how many reels use this" number.
USAGE_HINTS = ("count", "uses", "usage", "reels", "media", "popular", "posts", "videos")


def run(graph, audio_type="music"):
    body = graph.audio_search_raw(audio_type)
    tracks = body.get("audio") or body.get("data") or []
    print(f"Trending {audio_type}: {len(tracks)} tracks. Top-level keys in the answer: {sorted(body)}\n")
    fields = set()
    for rank, t in enumerate(tracks, 1):
        fields |= set(t)
        print(f"#{rank}  {t.get('title')}  |  {t.get('display_artist') or t.get('ig_username') or '-'}")
        print(json.dumps(t, indent=2, ensure_ascii=False))
        print()
    print(f"Every field seen: {sorted(fields)}")
    usage = [f for f in sorted(fields) if any(h in f.lower() for h in USAGE_HINTS)]
    if usage:
        print(f"Fields that might show how many reels use a track: {usage}. Check their values above.")
    else:
        print("No field shows how many reels use each track. Only the order (rank) shows what is trending.")
