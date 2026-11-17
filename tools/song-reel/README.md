# Song reel toolkit

Edits one raw song reel (Humaira or Sajjad lip-syncing a Suno song) into the finished 1080x1920 video.
Used by the `humiwell-songs` Claude skill. Nothing here is used by the posting robot.

The look was approved on 16 Nov 2026 ("Seven Cubes" v3): the presenter on screen the whole time, the raw
video's own audio untouched, lyric captions with a gold word highlight, a name card, brand-coloured chips,
and food stickers and sugar cubes that come alive with faces, arms and legs. One CTA at the end, tapped by
a finger, never a mouse cursor.

## Setup (once per machine)

```bash
pip install faster-whisper numpy "opencv-python-headless==4.10.0.84"
npm i playwright @fontsource/fraunces @fontsource/inter     # in WORKDIR/fonts (core.html loads fonts/node_modules/...)
npx playwright install chromium                              # or set PWCH=chrome to use the installed Chrome
```
Emoji stickers need the Noto Color Emoji font (installed on most Linux images; on Windows Chrome uses Segoe, which also works).

## Steps

```bash
T=tools/song-reel; W=work/2026-11-23-turn-it-over
python3 $T/prep.py "RAW.mp4" $W --hold 1.5          # cam frames, face track, frame map, cam.wav
python3 -I $T/lyrics.py $W lyrics.txt [suno.mp3]     # caption word timings in raw-video time
# write $W/scenes.js (start from example_seven_cubes_scenes.js), then:
python3 $T/build.py $W $W/scenes.js
cd $W && node ../../$T/render.js 0 N/2 1 frames & node ../../$T/render.js N/2 N 1 frames   # two halves in parallel
python3 $T/sfx.py $W events.json SECONDS
ffmpeg -i RAW.mp4 -i $W/sfx.wav -filter_complex "[0:a]aresample=44100,aformat=channel_layouts=stereo,afade=t=out:st=END-0.6:d=0.6,apad=whole_dur=SECONDS[s];[1:a]volume=0.2,aformat=channel_layouts=stereo[f];[s][f]amix=inputs=2:normalize=0:duration=longest,atrim=0:SECONDS,loudnorm=I=-14:TP=-1.5:LRA=11[m]" -map "[m]" -ar 44100 -ac 2 $W/mix.wav
ffmpeg -framerate 30 -i $W/frames/%05d.jpg -i $W/mix.wav -c:v libx264 -preset slow -crf 24 -maxrate 8M -bufsize 16M -pix_fmt yuv420p -movflags +faststart -c:a aac -b:a 192k -ar 44100 -ac 2 -shortest OUT.mp4
```

## Writing scenes.js

All times are seconds in the raw video (the same clock as lyrics.json). Helpers from core.html:

| Helper | What it draws |
|---|---|
| `nameCard(name, title, t0, t1)` | lower-third card, cream with a gold edge |
| `sticker(emoji, size, x, y, t0, t1, {script, geo})` | emoji sticker with a white outline; with `script` it gets a face, arms and legs |
| `chip(text, x, y, t0, t1, 'chip' or 'lbl', style)` | cream pill (chip) or small caps label (lbl) |
| `bigtxt(html, size, x, y, t0, t1, colour)` | big Fraunces number or word with a cream outline |
| `stamp(text, x, y, t0, t1, rot)` | terracotta rubber stamp that slams in |
| `cubeRow(y, n, {appear, knock, end, drop})` | a row of living sugar cubes; `knock[i]` sends cube i flying |
| `swap(t0, t1, L, Ltxt, R, Rtxt)` | "this to that" swap card; the left food is sad, the right one cheers |
| `confetti([t...])` | brand-colour confetti bursts |
| `shareCTA(T0, TAP, html)` | the ONE end card with a Send button tapped by a finger |
| `window.ZOOM`, `SHAKES`, `FLASHES`, `GLITCH` | camera push-ins, beat bounces (`beatPulse`), shakes, white flashes, RGB-split glitch |

Character behaviours for `script` (a list of `[time, behaviour, extras]`): idle, wave, wave2, dance, run,
flail, shock, worried, sad, smug, angel (halo), busted (halo slipping), whistle, tiptoe, tap (impatient foot),
flex, laugh, cheer, squish, sleepy, kiss, think. `geo` moves the face and limbs to fit the emoji
(for a bowl: `{fx:50,fy:68,fs:.72,ax:6,axr:94,ay:64,ly:86,ll:14}`).

Layout: the wall above the head (y 230 to 650) holds the animations, captions sit at y 1300 over the chest,
the name card at y 1110 on the left. Nothing important in the top 220px, the bottom 420px or the right 120px.
Brand: ivory #FAF6EC, forest #1F4D3A, antique gold #B08D57, terracotta #C2553B, green #3E8E5E, Fraunces + Inter.
