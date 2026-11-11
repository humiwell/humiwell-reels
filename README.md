# Humiwell trial reel robot

This repo posts 8 Instagram Trial Reels a day to @humiwell, each with a trending sound,
and tells you which hook won 72 hours later. It runs for free on GitHub Actions.

## How it works

1. **Every week** the render session uploads 7 days of videos (8 hook versions per day, A to H)
   and one small `manifest.json` per day. The rules are in [docs/BATCH_CONTRACT.md](docs/BATCH_CONTRACT.md).
2. **Every 15 minutes** the robot wakes up (Actions tab, "Reels robot") and:
   - checks the Instagram token once a day,
   - posts any version whose time slot has arrived and that is not posted yet,
   - judges any reel whose last version went out 72 hours ago.
3. **Fair test:** all 8 versions of one reel use the same sound, picked once (the top trending
   track unless you pin one). Which version gets which time slot shifts by one every day.
4. **Memory:** what was posted is saved in `state/state.json`, so running twice never posts twice.
5. **Results:** saved in `results/<date>.json` and added to `results.csv`. An issue names the winner.
   You then open the trial reel in the Instagram app and tap *Share to followers* by hand.

Posting slots (UK time, summer time handled): 07:00, 08:30, 10:00, 12:00, 14:00, 17:00, 19:00, 21:00.
GitHub sometimes starts runs a few minutes late, so a post can land up to about 20 minutes after its slot.

## Everyday controls (all in `config.yml`)

Open `config.yml` on GitHub, click the pencil, change a line, click *Commit changes*.
The next run uses it.

| I want to... | Change this |
|---|---|
| Pause posting | `paused: true` (back to `false` to restart) |
| Stop everything, including results | Actions tab, "Reels robot", `...` menu, *Disable workflow* |
| Practice without posting | `dry_run: true` |
| Change posting times | edit the `slots:` list, for example `["08:00", "12:00", "18:00"]` |
| Use one specific sound | put its id in `audio: pin_audio_id:` |
| Use a sound for one day only | `pin_by_date: {"2026-11-16": "1234567890"}` |
| Avoid a sound | add its id to `block_ids`, or a word to `block_words` |
| Prefer creator sounds | `prefer: original_sound` |

The sound used for each reel (title, artist, id) is in the run log and in the results file.

## How a winner is picked

- **Watch %** = average watch time divided by video length.
- Ranked by watch %, then by sends (shares) per 1,000 people reached.
- Saves and follows per 1,000 reach are shown too. (Instagram does not give follows for reels
  through the API yet, so that column may say n/a.)
- A lead is **trusted** only when the top two both reached 150+ people and the watch % gap is
  10 points or more. Otherwise the issue says "early leader (not trusted yet)".

## What each issue means

| Issue title | What happened | What you do |
|---|---|---|
| Results ... variant X is the winner | Clear winner | Share that reel to followers in the app, close the issue |
| Results ... early leader (not trusted yet) | Too close or too few views | Optional: share it anyway, or just close |
| Daily limit reached on ... | Instagram stopped posts for today | Nothing. The rest posts tomorrow. If it repeats, remove a slot |
| Skipped N version(s) of ... | Versions waited more than 2 days | Nothing. That day's results compare only what went out |
| Could not post ... variant X | Failed 3 times | Read the error. Often a video link problem |
| Chosen audio failed for ... | The track set in the manifest or config was refused | Nothing. That day uses the top trending track instead |
| Trending audio is not attaching | Instagram refused the sound. Nothing is posted | See "Audio problems" below. The robot retries every hour |
| No batch for ... | A slot came but there is no manifest for today | Ask the render session to push the week |
| Broken batch file | A manifest has a mistake | Fix it using docs/BATCH_CONTRACT.md |
| Instagram token runs out on ... | Token ends soon | Follow "Renew the token" below |
| Instagram token is not valid / check failed | Token expired or was revoked | Follow "Renew the token" below |

## Audio problems

Trending audio is required (`audio: required: true`): a reel is never posted without it.
If Instagram refuses a track, the robot tries the next trending track an hour later, and the
queue waits. Common causes:

- The Meta app is not published (Live). Meta for Developers, your app, Dashboard: the line
  "Check that all requirements are met, then publish your app" must have a green tick.
- The token was made before the app went Live. Make a new one ("Renew the token" below).

To allow posting without audio instead, set `required: false`.

## Renew the token

The Instagram token lasts about 60 days.

**Automatic (recommended):** the robot renews it itself once it has fewer than 53 days left,
if you give it permission to update secrets once:

1. GitHub, your picture, *Settings*, *Developer settings*, *Fine-grained tokens*, *Generate new token*.
2. Repository access: only `humiwell-reels`. Permissions: *Secrets: Read and write*. Expiry: up to 1 year.
3. Copy it. In this repo: *Settings*, *Secrets and variables*, *Actions*, *New repository secret*,
   name `GH_SECRETS_TOKEN`, paste, save.

**By hand (if a reminder issue opens):**

1. Open the [Graph API Explorer](https://developers.facebook.com/tools/explorer/), pick the Humiwell app,
   tick `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`,
   `pages_show_list`, `pages_read_engagement`, and click *Generate Access Token*.
2. Open the [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/), paste it,
   click *Extend Access Token* at the bottom, copy the long token.
3. Repo *Settings*, *Secrets and variables*, *Actions*, edit `IG_ACCESS_TOKEN`, paste, save.

Never paste a token into an issue, a file or a chat.

## One-off tests

Actions tab, "Test reel", *Run workflow*:

- `check`: safe. Checks the token, trending sounds, video links, and uploads test videos with
  trial + sound settings without ever publishing them. Also checks token renewal.
- `post` with confirm `POST`: publishes ONE test trial reel.
- `insights`: reads that test reel's numbers.

## Files

| Path | What it is |
|---|---|
| `config.yml` | Your settings |
| `batches/` | One manifest per posting day (from the render session) |
| `state/state.json` | The robot's memory. Do not edit unless asked |
| `results/`, `results.csv` | Test results |
| `reels/` | The code |
| `tests/` | Practice runs against a fake Instagram |
