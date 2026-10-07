---
name: assembly
description: Assemble an EDL with ffmpeg. Load when rendering a picture cut, concat, or trim-and-join.
---

# assembly

Turn the EDL into a picture file. Do not hand-write concat lists.

```
edittude media assemble edl.json --out picture.mp4 --work OUT/work
```

A second assemble onto the same `picture.mp4` needs `edittude media --force assemble`.

The command re-encodes each event onto the EDL canvas at 30fps, stereo 48k, then concat-copies. With `"aspect": "source"` that canvas is the display resolution of the clip holding the most screen time; off-aspect events are padded onto it unless `"fit"` is `"crop"`. Per-event `zoom`/`cx`/`cy` is applied here too. iPhone extra data streams stay off the map.

If the EDL already has title, look, and voiceover paths, prefer `finish` after assemble instead of stacking one-off encodes.

Completion: `picture.mp4` exists and ffprobe duration is within 0.3s of the EDL duration.
