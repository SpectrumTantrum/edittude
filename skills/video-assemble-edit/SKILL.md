---
name: video-assemble-edit
description: Trim retrieved footage into a timed sequence, attach or mix the intended audio, and render a verified video. Use when scene timing and candidate source intervals already exist.
metadata:
  source-role: "VideoEditor"
  source-path: "environment/roles/vid_editor.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Assemble an edit

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `image_describe`.

Turn scene selections and a timing plan into a playable video without losing scene alignment or shortening the intended story through skipped clips.

## Inputs and tools

- Scene IDs, visual descriptions, target timeline `start`/`end`, and candidate source IDs, paths, and `source_start`/`source_end` in seconds.
- Intended soundtrack or narration, source-audio policy, target aspect ratio/resolution/frame rate, and output path separate from inputs. Use the brief or existing project settings; disclose unresolved delivery choices.
- Use an available editor, `ffmpeg`/`ffprobe`, or installed MoviePy. Inspect the installed interface before using version-specific library methods. Image inspection or playback is needed for shot selection and quality review; `image_describe` reads extracted frames when it is configured.
- If rendering or decoding support is missing, deliver the validated edit decision list and name the missing capability. Do not claim a rendered result.

## Workflow

1. Probe every source and soundtrack. Join timing, scene text, and selections by stable scene ID. Reject missing or duplicate IDs, negative intervals, and unresolved required scenes before rendering.
2. Build explicit timeline intervals. If the input supplies only cut endpoints, prepend zero and resolve the final endpoint against the intended soundtrack duration. Distinguish interior beat markers from the final boundary. Preserve intentional gaps or overlaps; flag accidental ones.
3. Within each candidate range, inspect frames and choose a continuous span of the required duration. Use each sampled frame's actual source timestamp; a frame-list index is not elapsed seconds. Recheck the end boundary after choosing the start.
4. Resolve short candidates using a suitable alternate or an explicit multi-shot plan. Speed changes, loops, still holds, or omitted scenes require support from the brief or a disclosed revision. Keep the original timing until the gap has a valid solution.
5. Assemble trims in timeline order. Normalize orientation, pixel aspect ratio, dimensions, and frame rate as needed. Choose crop or letterbox according to the brief and visible subjects. Use hard cuts unless a transition serves the requested style; account for any overlap in the timeline.
6. Attach the intended soundtrack. Keep, replace, or mix source audio according to the input policy. For mixes, check dialogue intelligibility, ducking where needed, peaks, and start offsets. Decide the music tail explicitly rather than truncating it to an accidentally shortened video.
7. Render to a new file, retaining the edit decision list. Read the renderer result, probe the output, and decode the full file to catch late failures before reporting completion.

## Output contract

Return output video path, actual duration and media properties, edit decision list, audio policy, and unresolved issues. Example decision row:

```json
{
  "id": "scene-01",
  "start": 0.0,
  "end": 3.0,
  "source_id": "src-01",
  "source_path": "media/interview.mov",
  "source_start": 12.4,
  "source_end": 15.4,
  "speed": 1.0,
  "source_audio": "mute"
}
```

## Validation

- Check `(source_end - source_start) / speed` against timeline duration for every trim. Check source bounds and the complete timeline through its intended end.
- Probe the render for expected video/audio streams, dimensions, frame rate, and duration. Compare duration with the plan to within the target frame interval plus known audio encoding padding.
- Inspect the opening, each cut boundary, and the ending; listen across joins and narration/music overlaps. Flag black frames, freezes, stretched faces, clipped speech, or unexpected silence.
- An output path or successful encoder exit alone is insufficient. State which playback, visual, and audio checks were completed and which remain unavailable.
