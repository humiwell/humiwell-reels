"""Step 1: raw video -> upscaled frames, face track, frame map.

Usage: python3 prep.py RAW.mp4 WORKDIR [--hold 1.5]
Writes WORKDIR/cam/%05d.jpg (1080x1920), WORKDIR/face.json, WORKDIR/frames.json and WORKDIR/cam.wav.
The raw video is used exactly as filmed: its own audio, its own timing. --hold adds that many seconds of the
last frame at the end so the CTA can finish.
"""
import json, os, subprocess, sys
import numpy as np

raw, work = sys.argv[1], sys.argv[2]
hold = float(sys.argv[sys.argv.index("--hold") + 1]) if "--hold" in sys.argv else 1.5
os.makedirs(f"{work}/cam", exist_ok=True)
run = lambda *a: subprocess.run(a, check=True, capture_output=True, text=True).stdout
dur = float(run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", raw))
# 9:16 centre crop if needed, then 1080x1920 with a light sharpen (phone/WhatsApp files are often 576x1024)
run("ffmpeg", "-v", "error", "-y", "-i", raw, "-vf",
    "fps=30,crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920:flags=lanczos,unsharp=5:5:0.6",
    "-q:v", "3", f"{work}/cam/%05d.jpg")
run("ffmpeg", "-v", "error", "-y", "-i", raw, "-ac", "1", "-ar", "16000", f"{work}/cam.wav")
n = len([f for f in os.listdir(f"{work}/cam") if f.endswith(".jpg")])

import cv2  # needs opencv-python-headless==4.10.0.84 (5.x has no CascadeClassifier)
cc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
pts = {}
for i in range(0, n, 5):
    g = cv2.cvtColor(cv2.resize(cv2.imread(f"{work}/cam/{i+1:05d}.jpg"), (540, 960)), cv2.COLOR_BGR2GRAY)
    d = [r for r in cc.detectMultiScale(g, 1.1, 6, minSize=(80, 80)) if 2 * (r[1] + r[3] / 2) < 1250 and 2 * r[2] < 460]
    if d:
        x, y, w, h = max(d, key=lambda r: r[2] * r[3]); pts[i] = (2 * (x + w / 2), 2 * (y + h / 2))
idx = np.arange(n)
if pts:
    k = np.array(sorted(pts))
    med = lambda a, m=7: np.array([np.median(a[max(0, j - m // 2):j + m // 2 + 1]) for j in range(len(a))])
    X = np.interp(idx, k, med(np.array([pts[j][0] for j in k]))); Y = np.interp(idx, k, med(np.array([pts[j][1] for j in k])))
else:
    X, Y = np.full(n, 540.0), np.full(n, 900.0)
sm = lambda a, m=45: np.convolve(np.pad(a, m // 2, mode="edge"), np.ones(m) / m, "valid")
json.dump({"x": sm(X).round(1).tolist(), "y": sm(Y).round(1).tolist()}, open(f"{work}/face.json", "w"))
# frame map: [cam frame index (1-based), time in seconds]; the tail holds the last frame
total = n + int(round(hold * 30))
json.dump([[min(i + 1, n), round(i / 30, 4)] for i in range(total)], open(f"{work}/frames.json", "w"))
print(f"{n} frames ({dur:.2f}s), {len(pts)} face hits, output {total / 30:.2f}s")
