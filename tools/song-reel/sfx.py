"""Step 4: sound effects from a list of events, mixed quietly under the raw audio.

Usage: python3 sfx.py WORKDIR EVENTS.json SECONDS
EVENTS.json: [[time_s, "pop"|"pop_hi"|"tick"|"thud"|"ding"|"chime"|"whoosh"|"scratch"|"buzz"|"click", gain], ...]
Writes WORKDIR/sfx.wav. Times are raw-video time (the same clock as the scenes file).
"""
import json, sys, wave
import numpy as np
work, events, dur = sys.argv[1], sys.argv[2], float(sys.argv[3])
SR = 44100; out = np.zeros(int(SR * dur)); rng = np.random.default_rng(3)
def env(n, a=.003, d=.1):
    t = np.arange(n) / SR; return np.minimum(t / a, 1) * np.exp(-t / d)
def pop(f=600):
    n = int(.12 * SR); t = np.arange(n) / SR; fr = f * (1 + 2 * np.exp(-t * 40)); return np.sin(2 * np.pi * np.cumsum(fr) / SR) * env(n, .002, .035)
def tick():
    n = int(.05 * SR); return (rng.standard_normal(n) * .5 + np.sin(2 * np.pi * 2400 * np.arange(n) / SR)) * env(n, .0005, .008)
def thud():
    n = int(.25 * SR); t = np.arange(n) / SR; return np.sin(2 * np.pi * (90 + 60 * np.exp(-t * 30)) * t) * env(n, .002, .07) + rng.standard_normal(n) * env(n, .001, .012) * .3
def ding(f=1320):
    n = int(.9 * SR); t = np.arange(n) / SR; return (np.sin(2 * np.pi * f * t) + .4 * np.sin(2 * np.pi * f * 2.01 * t) + .2 * np.sin(2 * np.pi * f * 3.02 * t)) * env(n, .002, .28)
def chime(): return sum(ding(f) * g for f, g in [(1568, .5), (1976, .4), (2349, .35)])
def whoosh(d=.35):
    n = int(d * SR); return np.convolve(rng.standard_normal(n), np.ones(30) / 30, "same") * np.hanning(n) * 1.5
def scratch():
    n = int(.45 * SR); t = np.arange(n) / SR; f = 600 + 500 * np.sin(2 * np.pi * 5 * t)
    y = np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR)) * .3 + rng.standard_normal(n) * .4; return np.convolve(y, np.ones(8) / 8, "same") * np.hanning(n)
def buzz():
    n = int(.22 * SR); t = np.arange(n) / SR; return np.sign(np.sin(2 * np.pi * 140 * t)) * env(n, .003, .12) * .35
def click():
    n = int(.03 * SR); return rng.standard_normal(n) * env(n, .0003, .004) * 1.2
SOUNDS = {"pop": lambda: pop(600), "pop_hi": lambda: pop(950), "tick": tick, "thud": thud, "ding": ding, "chime": chime,
          "whoosh": whoosh, "scratch": scratch, "buzz": buzz, "click": click}
for t, name, g in json.load(open(events)):
    x = SOUNDS[name](); i = int(t * SR); x = x[:max(0, len(out) - i)]; out[i:i + len(x)] += x * g
out = out / (np.max(np.abs(out)) or 1) * .9
w = wave.open(f"{work}/sfx.wav", "w"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
w.writeframes((out * 32767).astype(np.int16).tobytes()); w.close(); print("wrote sfx.wav")
