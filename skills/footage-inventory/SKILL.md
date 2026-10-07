---
name: footage-inventory
description: Inventory footage folders with ffprobe. Load when they name a clip folder, ask what they shot, or before any cut.
---

# footage-inventory

Know the bin before you cut.

## Steps

1. `ls` the folder. Inventory skips `.edittude/`, `.edittude-v3/`, `.git/`, `.venv/`, `__pycache__/`, `artifacts/`, `cache/`, `dataset/`.
2. Run:

```
edittude media inventory FOLDER --out OUT/inventory.json
```

3. Read the JSON. Note video count, total seconds, fps/resolution mix, and any audio-only file that looks like voiceover or music. Read `display_width`/`display_height` for the frame as it plays: coded `width`/`height` are pre-rotation, so a portrait phone clip reports 1920x1080 with `rotation` ±90. That `rotation` field is iPhone display-matrix and ffmpeg applies it on decode. Do not transpose again. Note the orientation mix too, since the delivery canvas follows the dominant footage.
4. If you need eyes:

```
edittude media thumbs OUT/inventory.json --out OUT/thumbs
```

Completion: a written inventory, and thumbs if you could not name the coverage without them.

Helper: `skills/footage-inventory/scripts/inventory.sh`
