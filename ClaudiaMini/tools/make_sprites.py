# Turns Claudia's generated poses into the overlay's pixel-art sprites.
# Each pose folder becomes art/sprites/<state>/NN.png: background cut away, shrunk to true pixels,
# and every frame drawn from one shared palette so her colours don't shimmer between poses.
#
#   python tools\make_sprites.py            (uses the folders in data\sprite_sources.json)

import json
import os
import shutil
import sys

import cv2
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cutout(path):
    # A picture that already has transparency (from cut_backgrounds.py) is used as it is
    img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_UNCHANGED)
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = np.where(img[..., 3] >= 128, 255, 0).astype(np.uint8)
        return np.dstack([cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2RGB), alpha]), True
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    img = img[..., :3]
    # The generated images sit on an off-white backdrop with a soft grey floor shadow. Both are bright
    # and nearly colourless; whatever of that touches the image border is background. Her white shirt
    # is just as pale, but it's walled in by her outline, so it never connects to the border.
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    pale = ((hsv[..., 2] > 150) & (hsv[..., 1] < 28)).astype(np.uint8)
    count, labels = cv2.connectedComponents(pale, connectivity=4)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    edge = [label for label in edge if label != 0 or pale[labels == 0].all()]
    background = np.isin(labels, edge) & (pale == 1)
    alpha = np.where(background, 0, 255).astype(np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    # One more pixel off the rim takes the pale fringe the backdrop leaves around her braids
    alpha = cv2.erode(alpha, np.ones((3, 3), np.uint8))
    return np.dstack([cv2.cvtColor(img, cv2.COLOR_BGR2RGB), alpha]), False


def fit(rgba, box_w, box_h):
    # A pre-cut picture came from a scene, so where she sat in it means nothing: crop to her and
    # size her to fit the box. The overlay stands smaller frames on the bottom edge, centred
    ys, xs = np.where(rgba[..., 3] > 0)
    rgba = rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = rgba.shape[:2]
    return shrink(rgba, max(1, round(w * min(box_w / w, box_h / h))))


def shrink(rgba, target_width):
    # Box filter on premultiplied colour, so the backdrop doesn't bleed into her edge pixels.
    # Sized by the picture's width, so a 1024 Flux image and a 1408 Grok one give her the same height
    h, w = rgba.shape[:2]
    size = (target_width, max(1, round(h * target_width / w)))
    a = rgba[..., 3:4].astype(np.float32) / 255
    premult = rgba[..., :3].astype(np.float32) * a
    small_rgb = cv2.resize(premult, size, interpolation=cv2.INTER_AREA)
    small_a = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
    rgb = np.clip(small_rgb / np.maximum(small_a[..., None], 1e-4), 0, 255).astype(np.uint8)
    solid = small_a >= 0.5
    return rgb, solid


def main():
    with open(os.path.join(HERE, "data", "sprite_sources.json"), encoding="utf-8") as handle:
        config = json.load(handle)
    root = config["source_root"]
    width = config["picture_width_in_pixels"]

    frames = []  # (state, name, rgb, solid)
    pre_cut = []  # (state, name, rgba), sized once the others have set the box
    for state, folder in config["states"].items():
        folder = os.path.join(root, folder)  # an absolute folder ignores source_root
        if not os.path.isdir(folder):
            print("  %-9s no folder yet (%s)" % (state, folder), flush=True)
            continue
        files = sorted(f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".png")))
        files = [f for f in files if f not in config.get("skip", [])]
        for name in files:
            rgba, was_cut = cutout(os.path.join(folder, name))
            if was_cut:
                pre_cut.append((state, name, rgba))
            else:
                frames.append((state, name) + shrink(rgba, width))
        print("  %-9s %d poses from %s" % (state, len(files), folder), flush=True)
    if not frames:
        sys.exit("no poses on a plain backdrop found; they set the sprite size")

    # Every frame is cropped to the same box, so a pose's place in the original picture is kept:
    # a jump stays a jump, rather than everything being stood on the bottom edge
    union = np.zeros_like(frames[0][3])
    for _, _, _, solid in frames:
        union |= solid
    ys, xs = np.where(union)
    top, bottom, left, right = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    # Pre-cut poses are mostly her lying curled up: as wide as the box, about two-thirds as tall
    box_w, box_h = right - left, (bottom - top) * 2 // 3
    placed = [(state, name) + fit(rgba, box_w, box_h) for state, name, rgba in pre_cut]

    # One palette for everything, built from all her solid pixels together
    pixels = np.concatenate([rgb[solid] for _, _, rgb, solid in frames + placed])
    strip = Image.fromarray(pixels.reshape(1, -1, 3))
    palette = strip.quantize(config["colours"], method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)

    out_root = os.path.join(HERE, "art", "sprites")
    if os.path.isdir(out_root):
        shutil.rmtree(out_root)
    numbers = {}
    cropped = [(s, n, rgb[top:bottom, left:right], solid[top:bottom, left:right]) for s, n, rgb, solid in frames]
    for state, name, rgb, solid in cropped + placed:
        flat = Image.fromarray(rgb).quantize(palette=palette, dither=Image.Dither.NONE).convert("RGB")
        rgba = np.dstack([np.array(flat), np.where(solid, 255, 0).astype(np.uint8)])
        numbers[state] = numbers.get(state, 0) + 1
        folder = os.path.join(out_root, state)
        os.makedirs(folder, exist_ok=True)
        Image.fromarray(rgba).save(os.path.join(folder, "%02d.png" % numbers[state]))
    print("  %d sprites, %d x %d true pixels, in %s" % (len(frames) + len(placed), right - left, bottom - top, out_root))


if __name__ == "__main__":
    main()
