---
name: review-qc
description: Review and QC a render. Load for black frames, silence, loudness, freezes, duration, or frame grabs.
---

# review-qc

Look at what you made.

```
edittude media qc final.mp4 --out qc.json
edittude media frames final.mp4 --out frames
```

Read `qc.json`. Pass means no black spans, no long silences, no freezes, duration over 3s, audio present, integrated loudness near -16 LUFS.

Grab frames at 5/25/50/75/95. If a frame is black, smear, or a screen hold, recut.

Completion: a written report and stills. If it fails, say what to change, then load iterate-recut.
