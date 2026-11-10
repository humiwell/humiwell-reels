# Batch contract (for the weekly render session)

This is exactly what the render session must deliver each week so the robot can post it.
One "day" = one B-roll reel in 8 hook versions (A to H), posted on one date.

## 1. Videos go to a GitHub Release, never to the main branch

One release per posting day.

| Thing | Rule |
|---|---|
| Release tag | `day-YYYY-MM-DD` (the posting date, UK) |
| File names | `YYYY-MM-DD_A.mp4` ... `YYYY-MM-DD_H.mp4` |
| Format | MP4, H.264, 1080x1920, 23 to 60 fps, 3 to 90 s (about 10 s), under 100 MB |
| Sound | Silent is fine (trending audio is added by the robot from second 0) |

Upload with the GitHub CLI, for example:

```bash
gh release create day-2026-11-16 renders/2026-11-16_*.mp4 --repo humiwell/humiwell-reels --title "2026-11-16" --notes "Batch for 2026-11-16"
```

## 2. One manifest per day goes to the main branch

Path: `batches/YYYY-MM-DD/manifest.json` (folder name = posting date). Nothing else goes in that folder.

```json
{
  "contract_version": 1,
  "reel": "weekend-habits",
  "post_date": "2026-11-16",
  "caption": "One shared caption for all 8 versions. Max 2,200 characters, max 30 hashtags.",
  "variants": [
    {"id": "A", "lever": "curiosity",    "hook": "The 3 minute habit nobody talks about", "file": "2026-11-16_A.mp4", "length_s": 10.0},
    {"id": "B", "lever": "social proof", "hook": "...", "file": "2026-11-16_B.mp4", "length_s": 10.0},
    {"id": "C", "lever": "...", "hook": "...", "file": "2026-11-16_C.mp4", "length_s": 10.0},
    {"id": "D", "lever": "...", "hook": "...", "file": "2026-11-16_D.mp4", "length_s": 10.0},
    {"id": "E", "lever": "...", "hook": "...", "file": "2026-11-16_E.mp4", "length_s": 10.0},
    {"id": "F", "lever": "...", "hook": "...", "file": "2026-11-16_F.mp4", "length_s": 10.0},
    {"id": "G", "lever": "...", "hook": "...", "file": "2026-11-16_G.mp4", "length_s": 10.0},
    {"id": "H", "lever": "...", "hook": "...", "file": "2026-11-16_H.mp4", "length_s": 10.0}
  ]
}
```

Field rules:

| Field | Rule |
|---|---|
| `contract_version` | Always `1` for now |
| `reel` | Short name of the B-roll reel, lowercase with dashes |
| `post_date` | `YYYY-MM-DD`, same as the folder name and release tag |
| `caption` | The same caption is used for all versions, so only the hook differs |
| `variants` | 1 to 8 entries, normally exactly 8 (A to H) |
| `id` | Unique letter per day |
| `lever` | The psychology lever this hook uses (free text) |
| `hook` | The exact on-screen hook text |
| `file` | File name inside the `day-YYYY-MM-DD` release |
| `length_s` | Real video length in seconds (decimals fine). Used for watch % |

## 3. Timing

- Push the whole week (7 releases + 7 manifests) by Sunday 20:00 UK for the week starting Monday.
- Never change a manifest or video after its day has started posting. It would break the test.
- To cancel a day before it starts, delete its `batches/YYYY-MM-DD` folder.

## 4. Check before you finish

```bash
python -m reels validate --online
```

(`--online` also checks every upcoming video link really downloads.)

It must say `PROBLEM` zero times. The same check runs on GitHub after every push
(Actions tab, "Check"). A broken manifest also opens a GitHub issue when the robot runs.
