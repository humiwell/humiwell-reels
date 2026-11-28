# Batch contract (for the weekly render session)

This is exactly what the render session must deliver each week so the robot can post it.
One "day" = one B-roll reel in 4 hook versions, posted on one date. From trial date 27 Nov 2026 the versions are
A (original), B (loss framing), F (low effort) and one challenger (C, D, E, G, H or a new idea with a new letter).
Days up to 26 Nov 2026 have 8 versions (A to H). A day with 4 or fewer versions posts at `slots_4_versions`.

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
  "caption": "One shared caption for all versions. Max 2,200 characters, max 30 hashtags.",
  "audio_id": "1543916142623294",
  "audio_title": "Feelinga",
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
| `audio_id` | **Optional.** Instagram track id as text of digits (in quotes). Used for all versions of the day. Leave it out to use the top trending track (B-roll: a track from `audio: approved_ids` instead). Get ids from `python -m reels audio-shortlist` |
| `audio_title` | **Optional.** Track name, for people reading the issues and results. Only allowed together with `audio_id` |
| `notion_page` | **Optional.** The Notion row's link or page id. Without it the robot finds the row by date (B-roll: Reels row dated trial date + 3; talking head and song: row dated the trial date). As soon as the first version is posted the row gets Status "Posted", and once the winner issue is written it gets Winner, Winner hook, Winner link and Winner note (B-roll and talking head) |
| `variants` | 1 to 8 entries, normally exactly 4 (A, B, F and the challenger) |
| `id` | Unique letter per day |
| `lever` | The psychology lever this hook uses (free text) |
| `hook` | The exact on-screen hook text |
| `file` | File name inside the `day-YYYY-MM-DD` release |
| `length_s` | Real video length in seconds (decimals fine). Used for watch % |

How the track is picked for a day (first one that applies):

1. `audio: pin_by_date` for that date in `config.yml`
2. `audio_id` in the manifest
3. `audio: pin_audio_id` in `config.yml`
4. The top trending track (respecting `block_ids` and `block_words`)

**Approved list (B-roll, from 28 Nov 2026):** when `audio: approved_ids` in `config.yml` has tracks, a B-roll
day only ever uses one of them. Steps 1 to 3 still apply but only for ids on the list (others are skipped),
step 4 is replaced by rotating through the list by date, and the robot never falls back to trending. If
Instagram refuses a track it moves to the next one on the list. Put a listed id in the manifest's
`audio_id` to choose the track; otherwise the robot picks one. Talking head and song days are not affected.

If Instagram refuses a chosen track before any version of the day is posted, the robot switches to
the top trending track for all versions and opens an issue "Chosen audio failed for YYYY-MM-DD"
naming both tracks and the error. Videos must stay silent: the robot sets the video's own volume to 0.

## 2b. Talking-head batches (4 hooks, with voice)

Talking-head reels use the same contract with these differences:

| Thing | Rule |
|---|---|
| Folder | `batches/th-YYYY-MM-DD/manifest.json` (the `th-` prefix keeps them apart from B-roll on the same date) |
| Manifest | add `"kind": "talking-head"`; `post_date` is the plain date `YYYY-MM-DD` |
| Release tag | `day-th-YYYY-MM-DD` |
| File names | `YYYY-MM-DD_<topic>_A-surprising-fact.mp4`, `_B-relatable-problem`, `_C-myth-buster`, `_D-everyday-habit` (lowercase, hyphens, no spaces; versions A to D = hook 1 to 4) |
| Format | MP4, H.264, 1080x1920, 30 fps, under 60 s, under 100 MB, **with the voice track** |
| Audio | one **instrumental** track (no vocals) for all 4 (`audio_id` strongly recommended), played at `talking_head.audio_volume` (12) under the voice (`video_volume` 100) |
| Slots | `talking_head.slots` in config.yml, separate from the B-roll slots |
| Winner issue | `talking_head.issue_days_after` (2) days after the trial date, titled "Talking head results ..." |

Each version must differ beyond its hook (the render session gives each its own zoom, speed, brightness and grain), and a version that has been posted is **never posted again**, even after deleting it on Instagram: Instagram matches the video and limits re-uploads ("looks like something you've shared before", 16 Nov 2026). Don't reset a posted variant to pending to repost it.

If Instagram refuses the track with the voice on, nothing from that talking-head day is posted, the robot opens
"Talking-head audio is not attaching" and retries hourly. B-roll posting is never held up by it.

```bash
gh release create day-th-2026-11-16 "Output/Final/2026-11-16 iron twice/2026-11-16_iron-twice_"*.mp4 --repo humiwell/humiwell-reels --title "th-2026-11-16" --notes "Talking head for 2026-11-16"
```

## 2d. Song batches (1 version, the song is the sound)

Song reels are made by the `humiwell-songs` render session: Humaira or Sajjad lip-syncing a short AI song.
Same contract with these differences:

| Thing | Rule |
|---|---|
| Folder | `batches/song-YYYY-MM-DD/manifest.json` |
| Manifest | add `"kind": "song"`; exactly **one** variant (id `A`); no `audio_id` or `audio_title` |
| Release tag | `day-song-YYYY-MM-DD` |
| File name | `YYYY-MM-DD_<song-name>.mp4` (lowercase, hyphens, no spaces) |
| Format | MP4, H.264, 1080x1920, 30 fps, under 90 s, under 100 MB, **with the song as its own audio** |
| Audio | the robot adds **no** track and keeps the video's own sound (no `audio_configuration`) |
| Slots | `song.slots` in config.yml (one a day, 18:30 UK) |
| Results | a "Song results ..." scorecard issue `song.issue_days_after` (2) days after the trial date. There is no winner: share it to followers if the numbers look good |

```bash
gh release create day-song-2026-11-22 "2026-11-22_seven-cubes.mp4" --repo humiwell/humiwell-reels --title "song-2026-11-22" --notes "Song reel for 2026-11-22"
```

To post a song straight away, use `requests/post_now.json` with `"batch": "song-2026-11-22"`.

## 2c. Post one version now (outside the slots)

To post a version straight away (a live test, or a day pushed late), add an entry to `requests/post_now.json` on main:

```json
[{"id": "2026-11-16T08:20", "batch": "th-2026-11-16"}]
```

- `id`: any unique text (use the time you asked). Each id is handled once; old entries can stay in the file.
- `batch`: the batch folder name (`2026-11-16` for B-roll, `th-2026-11-16` for talking head). It must be today's (or a still-queued) batch.
- An awake robot run checks GitHub every `nap_minutes` (5), so it posts within about 5 minutes. If no run is awake, start one: `gh workflow run "Reels robot"`.
- The post counts towards that day, so the remaining versions keep their usual slots and nothing is posted twice.

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
