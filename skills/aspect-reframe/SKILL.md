---
name: aspect-reframe
description: Delivery frame and reframing. Load when the brief names an aspect, asks for vertical, square, or horizontal conversion, or when a shot wants a punch-in, zoom, or reframe.
---

# aspect-reframe

The canvas is the source. `--aspect source` is the default: the clip with the
most screen time in the EDL sets the display resolution, so vertical footage
delivers vertical and horizontal delivers horizontal. Under `source` an
explicit top-level `width`/`height` in `edl.json` is honoured, so set those
two if you need a specific canvas.

Change aspect only when the brief names a delivery format. Then the presets
are there:

```
edittude media reframe final.mp4 --out vertical.mp4 --aspect 9:16
edittude media reframe final.mp4 --out square.mp4 --aspect 1:1
```

A second reframe onto the same output needs `edittude media --force reframe`.

Or set `"aspect": "9:16"` on the EDL and run `edittude media --force assemble edl.json --out picture.mp4`
again so every event lands on that canvas.

## pad or crop

Top-level `"fit"`, or `--fit {pad,crop}`. `"pad"` is the default: an off-aspect
clip is letterboxed or pillarboxed onto the canvas with all of its picture
intact. `"crop"` fills the canvas and center-crops, which loses the edges.
Pick `crop` when the brief wants edge-to-edge and the subjects sit centre
frame. In a mixed-orientation folder the minority orientation pads unless a
crop of those shots reads better.

Inventory `display_width`/`display_height` are the frame as it plays. Coded
`width`/`height` are pre-rotation: a portrait phone clip reports 1920x1080
with rotation ±90.

## punch-in

Cropping inside a shot is the creative use. Per event, `zoom` between 1.0 and
4.0 with `cx`/`cy` normalized 0-1 for the focus point, default 0.5/0.5:

```json
{
  "src": "/footage/IMG_0412.MOV",
  "in": 12.4,
  "out": 16.1,
  "zoom": 1.35,
  "cx": 0.42,
  "cy": 0.38,
  "reason": "push on her reaction to the line"
}
```

Use it for emphasis on a line or reaction, a second angle out of a single take
to cover a jump cut, reframing dead space or a distraction out of the shot, a
push on a detail, or hitting a beat. A punch-in is an upscale: stay around
1.3-1.5x on a 1080p source, go further only with 4K headroom. Grab a frame and
look at it before you pick `cx`/`cy`, or the subject ends up outside the window.

Completion: ffprobe the output and the display size equals the canvas you
intended, with no crop you did not ask for.
