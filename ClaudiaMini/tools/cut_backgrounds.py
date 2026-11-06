# Cuts Claudia out of pictures that have a whole scene behind her (a room, a park), which
# make_sprites.py's own backdrop cutting can't handle. Writes transparent PNGs that make_sprites.py
# then uses as they are.
#
# Needs rembg, kept in its own environment on D: with its model on E::
#   set U2NET_HOME=E:\AIModels\rembg
#   D:\venvs\claudia-rembg\Scripts\python tools\cut_backgrounds.py <picture folder> <output folder>

import os
import sys

from PIL import Image
from rembg import new_session, remove

MODEL = "birefnet-general"  # the sharpest of rembg's models on hair and tails


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: cut_backgrounds.py <picture folder> <output folder>")
    source, target = sys.argv[1], sys.argv[2]
    os.makedirs(target, exist_ok=True)
    session = new_session(MODEL)
    for name in sorted(os.listdir(source)):
        if not name.lower().endswith((".jpg", ".png")):
            continue
        cut = remove(Image.open(os.path.join(source, name)).convert("RGB"), session=session)
        cut.save(os.path.join(target, os.path.splitext(name)[0] + ".png"))
        print("  " + name, flush=True)


if __name__ == "__main__":
    main()
