---
name: zero-shot-cut
description: Zero-shot cut from a footage folder and a brief. Load when they say make a cut, edit this, or give a folder with no EDL.
---

# zero-shot-cut

Make a finished piece from a folder. Do not wait for an EDL.

## Steps

1. `ls` the folder they named. Completion: you can see the clip names.
2. Read `footage-inventory`. Write `inventory.json` under their `artifacts/` (create it). Completion: JSON exists with clip counts.
3. If the pictures are unclear, extract thumbs. Completion: stills exist or you already know the coverage.
4. Read `editorial-taste`. Write an EDL with `plan`, then edit the JSON if the first cut is wrong. Completion: `edl.json` with reasons on each event.
5. Read `assembly`, `mix`, `color-grade`, `titles`. Render picture, then `finish`. Completion: `final.mp4` on disk.
6. Read `review-qc`. If it fails, read `iterate-recut` and go again once. Completion: `qc.json` plus a path you would show a person.

Default delivery: the source frame, warm look, VO if present, one title. Write large files outside the repo.

```
edittude media proof FOLDER --out OUTDIR --title "TITLE"
```

Use `proof` when the brief is thin. Use the stepwise commands when you need to change the EDL by hand.

A second `proof` into the same OUTDIR needs `edittude media --force proof`; it will not overwrite an existing `final.mp4` or `edl.json` on its own.

A reply that only lists commands is a failed turn. The file has to exist.
