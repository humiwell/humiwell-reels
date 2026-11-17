"""Step 2: word timings for the captions, from the raw video's own audio.

Usage: python3 -I lyrics.py WORKDIR LYRICS.txt [SUNO.mp3]
LYRICS.txt = the sung lines exactly as on screen (one caption line per text line, no [tags]),
with the live spoken first line at the top. Writes WORKDIR/lyrics.json (in raw-video time).

If the Suno file is given, the words are timed on the clean song and moved to video time with a
cross-correlation offset (more accurate). Otherwise faster-whisper runs on the raw audio with the
lyrics as a prompt. Check the printed table: every line should start roughly where it is sung.
"""
import difflib, json, re, subprocess, sys, wave
import numpy as np
from faster_whisper import WhisperModel

work, lyr = sys.argv[1], sys.argv[2]
suno = sys.argv[3] if len(sys.argv) > 3 else None
lines = [l.strip() for l in open(lyr, encoding="utf-8") if l.strip() and not l.strip().startswith("[")]

def rd(p):
    w = wave.open(p); return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768

cam = rd(f"{work}/cam.wav")
model = WhisperModel("medium.en", compute_type="int8")
prompt = " ".join(lines)[:800]

def words_of(audio, chunk=10, step=8):
    out = []
    for st in range(0, int(len(audio) / 16000), step):
        seg = audio[st * 16000:(st + chunk) * 16000]
        segs, _ = model.transcribe(seg, word_timestamps=True, initial_prompt=prompt,
                                   condition_on_previous_text=False, vad_filter=False)
        for s in segs:
            for w in s.words:
                t = st + w.start
                if not out or t > out[-1][0] + 0.05:
                    out.append((t, st + w.end, w.word.strip()))
    return out

offset = 0.0
if suno:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", suno, "-ac", "1", "-ar", "16000", f"{work}/suno.wav"], check=True)
    s = rd(f"{work}/suno.wav")
    a, b = cam.astype(np.float64), s.astype(np.float64)
    N = 1 << (len(a) + len(b)).bit_length()
    R = np.fft.rfft(a, N) * np.conj(np.fft.rfft(b, N)); R /= np.abs(R) + 1e-9
    r = np.fft.irfft(R, N); k = int(np.argmax(r)); k = k if k < N // 2 else k - N
    offset = k / 16000
    print(f"song starts at {offset:.2f}s in the raw video")
    W = [(t + offset, e + offset, w) for t, e, w in words_of(s)]
else:
    W = words_of(cam)

norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())
toks = [(li, w) for li, l in enumerate(lines) for w in l.split()]
A = [norm(w) for _, w in toks]; B = [norm(w) for _, _, w in W]
tim = [None] * len(A)
for a, b, n in difflib.SequenceMatcher(None, A, B, autojunk=False).get_matching_blocks():
    for k in range(n):
        tim[a + k] = (W[b + k][0], W[b + k][1])
have = [i for i, t in enumerate(tim) if t]
for i in range(len(tim)):
    if tim[i] is None:
        p = max([j for j in have if j < i], default=None); q = min([j for j in have if j > i], default=None)
        if p is None: tim[i] = (tim[q][0] - 0.3, tim[q][0] - 0.05)
        elif q is None: tim[i] = (tim[p][1] + 0.05, tim[p][1] + 0.35)
        else:
            f = (i - p) / (q - p); s0 = tim[p][1] + (tim[q][0] - tim[p][1]) * f; tim[i] = (s0, s0 + 0.25)
out = []
for li, l in enumerate(lines):
    ws = [[toks[i][1], round(tim[i][0], 2), round(tim[i][1], 2)] for i in range(len(toks)) if toks[i][0] == li]
    out.append({"text": l, "words": ws})
    print(f"{ws[0][1]:6.2f} {ws[-1][2]:6.2f}  {l}")
json.dump(out, open(f"{work}/lyrics.json", "w"))
print(f"matched {len(have)}/{len(A)} words")
