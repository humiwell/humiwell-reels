"""Step 3: core.html + a scenes file + the data -> WORKDIR/comp.html.

Usage: python3 build.py WORKDIR SCENES.js
Needs WORKDIR/frames.json, face.json, lyrics.json, cam/ and fonts/ (see README).
"""
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
work, scenes = sys.argv[1], sys.argv[2]
s = open(os.path.join(here, "core.html"), encoding="utf-8").read()
s = s.replace("/*__SCENES__*/", open(scenes, encoding="utf-8").read())
for key, f in (("__FRAMES__", "frames.json"), ("__FACE__", "face.json"), ("__LYRICS__", "lyrics.json")):
    s = s.replace(key, open(os.path.join(work, f), encoding="utf-8").read())
open(os.path.join(work, "comp.html"), "w", encoding="utf-8").write(s)
print("wrote", os.path.join(work, "comp.html"))
