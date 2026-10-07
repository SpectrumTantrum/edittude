---
name: video-mux-audio
description: Attach a finished audio mix to an existing video while preserving picture timing and choosing an explicit duration policy.
metadata:
  source-role: Merge
  source-path: environment/roles/merge.py
  source-revision: f207987e3cffb554aaa6ffdbe733efb30f4b51ed
---

# Attach audio to video

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

## Inputs and result

Take an existing video, finished audio, a new output path, the intended audio offset, and whether to replace or retain existing tracks. Return the video path, stream mapping, duration policy, actual audio/video durations, and sync checks. This step keeps the shot order; it does not retrieve or assemble footage.

## Workflow

1. Probe both sources for duration, start times, codecs, and stream layout. Keep the output path distinct from every input, including resolved aliases. Choose a new path if it exists.
2. Default to preserving the complete picture duration unless the brief specifies a trim. Pad a shorter replacement audio track with silence, or report the missing soundtrack if silence conflicts with the brief. Trim longer audio to picture duration with a suitable fade. Apply requested offsets explicitly.
3. Map the intended video/audio streams. Preserve subtitles, alternate language tracks, chapters, and metadata when requested and supported by the destination container. State omitted tracks. Copy compatible video streams to avoid a generation of picture loss; encode only when delivery requires it.
4. Render and reopen the file. Probe stream lengths and decode all delivered audio/video. Check lip sync or other known sound/picture events near the beginning, middle, and end.

For zero-offset replacement in an MP4-compatible video, bind `picture_duration` to its measured seconds. This example keeps the first picture stream and the new audio, pads audio when needed, and intentionally omits other tracks:

```sh
ffmpeg -nostdin -n -i "picture.mp4" -i "mixed.wav" -map 0:v:0 -map 1:a:0 -c:v copy -af apad -c:a aac -b:a 192k -t "$picture_duration" -movflags +faststart "final.mp4"
ffprobe -v error -show_streams -show_format -of json "final.mp4"
ffmpeg -v error -i "final.mp4" -map 0:v:0 -map 0:a:0 -f null -
```

Use an available editor's export/mux capability if FFmpeg is absent. A tool that cannot preserve the chosen duration/streams is a reported limitation.

## Completion

The output plays, contains the intended streams, retains picture duration within a frame plus codec padding, and has no unplanned cutoff or silence. Verify synchronization against actual events; equal durations alone do not prove sync. Record any playback or perceptual checks that were unavailable.
