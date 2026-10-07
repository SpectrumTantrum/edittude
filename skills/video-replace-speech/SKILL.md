---
name: video-replace-speech
description: Replace source video speech with synthesized patches, preserving source coverage and applying the chosen audio or video timing policy.
metadata:
  source-role: "TTSReplace"
  source-path: "environment/roles/tts/tts_replace.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Replace video speech

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Integrate replacement recordings into a video with an explicit relationship between the source timeline and the edited timeline.

## Inputs

- Source video and a patch manifest with `id`, `source_start`, `source_end`, replacement `audio_path`, and measured `duration` in seconds.
- Desired output path and timing policy: preserve the source video timeline, or retime affected visuals to the new speech.
- Audio treatment for original speech, music, ambience, and intentional nonspeech gaps. Use existing edit intent; preserve timing and unaffected material when the request leaves them unchanged.

## Workflow

1. Probe the source and every patch. Check interval bounds, positive durations, duplicate IDs, overlapping replacements, audio/video start offsets, and complete intended patch coverage. Missing patches are a blocker for a complete replacement, not permission to drop video.
2. Build an edit map covering the whole source, including leading, intermediate, and trailing material. Apply explicit requested deletions; otherwise retain the gaps between speech slices and all unaffected visuals.
3. For a preserved video timeline, place each patch in its source interval. Fit speech with suitable wording or a supported rate adjustment and recheck intelligibility. Add room tone or silence for unused time as appropriate. If a patch still overflows, report the specific ID and duration mismatch instead of clipping words.
4. For an explicitly retimed video, use the ratio `replacement_duration / source_interval_duration` to scale the affected video's presentation timestamps. Measure the resulting clip and build new cumulative output bounds. Apply the same mapping to captions, overlays, and other time-based assets. Retiming alone does not create lip sync.
5. Replace the original spoken content in the affected region. If speech shares a mixed track with music or ambience, use available separated stems or the agreed whole-track replacement. State the limitation if the original speech cannot be removed without losing requested background sound.
6. Assemble with compatible video dimensions, frame cadence, audio sample rate, and channel layout. Use installed media tooling and its real command or API contract. Write to a new output; preserve source media and reusable patches.
7. Decode the full export and inspect the edited transitions. Keep intermediates needed to repair failures until the final output has passed checks.

## Output and handoff

Return `video_path` and `edit_map_path`. For each affected interval, record source bounds, final output bounds, patch ID and file, and the applied timing ratio. Example:

```json
{
  "id": "0003",
  "source_start": 12.4,
  "source_end": 18.7,
  "start": 12.4,
  "end": 18.7,
  "audio_path": "patches/0003.wav",
  "timing_policy": "preserve-video"
}
```

The example keeps the video interval fixed; the patch must actually fit it. Resolve relative paths against the manifest directory. Include every preserved interval in the complete edit map, not just patches.

## Completion checks

- Output opens and decodes with expected streams and duration; every requested patch and preserved source interval is present.
- Listening confirms no original speech accidentally doubles the replacement, no clipped words, and acceptable joins and background continuity.
- Visual inspection confirms intended pacing and caption alignment. Report lip-sync or retiming limitations that remain.

## Source adaptation

The original retimed each selected video slice to its replacement audio, skipped missing patches, and concatenated only those slices. This skill retains that retiming option while making omissions, source coverage, and timeline changes explicit.
