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


def run_search(graph, terms, audio_type="music"):
    """Searches the Audio API for each word and lists the tracks found, one line each."""
    seen = set()
    for term in terms:
        try:
            body = graph.audio_search_raw(audio_type, search=term)
        except Exception as e:  # keep going with the other words
            print(f"\n'{term}': failed: {e}")
            continue
        tracks = body.get("audio") or body.get("data") or []
        print(f"\n== Search '{term}': {len(tracks)} tracks ==")
        for rank, t in enumerate(tracks, 1):
            aid = str(t.get("audio_id") or t.get("id") or "")
            dup = " (seen above)" if aid in seen else ""
            seen.add(aid)
            mins = round((t.get("duration_in_ms") or 0) / 60000, 1)
            print(f"#{rank:<3} {t.get('title')}  |  {t.get('display_artist') or t.get('ig_username') or '-'}"
                  f"  |  id {aid}  |  {mins} min{dup}")
