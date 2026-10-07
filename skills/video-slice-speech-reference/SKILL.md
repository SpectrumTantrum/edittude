---
name: video-slice-speech-reference
description: Slice recorded speech into clean reference clips with source timestamps for transcription, speech rewriting, or reference-based synthesis.
metadata:
  source-role: "TTSSlicer"
  source-path: "environment/roles/tts/tts_slicer.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Slice speech references

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `speech_transcribe`, `audio_timing`.

Create speech clips that retain their exact positions in the source recording. The manifest is the link back to the video when rewritten audio replaces the performance.

## Inputs

- Source audio path, output directory, and its offset relative to the source video if audio time zero differs.
- Any known speaker boundaries and the intended synthesis backend's reference duration limits.
- Optional slice settings. The original started with about 6-8 second clips, 0.5 seconds of silence, a -35 dBFS RMS threshold, 10 ms analysis windows (`audio_timing` `window_ms`, which has no separate hop), and up to 0.3 seconds of retained silence. These are starting points, not universal thresholds.

## Workflow

1. Probe and decode the source. Record duration, sample rate, and channels. Reject empty audio. Preserve the original file.
2. Detect speech and pauses using available VAD or energy analysis. Inspect quiet speech, background music, and channel differences before accepting the boundaries. A threshold crossing alone can mistake an unvoiced consonant for silence.
3. Place cuts in pauses or at verified word boundaries. Keep enough breath and consonant context for a natural reference. Split at speaker changes so a clip represents the intended speaker.
4. Bound clip duration for the selected backend. Split an overlong region near a safe boundary rather than through a word; if there is no suitable boundary, record the limitation. A short utterance can remain short when merging would mix speakers or remove meaningful pauses.
5. Preserve each clip's source sample offsets. When joining disjoint source intervals for a reference, record the interval list and its new local duration; a joined clip cannot truthfully claim one continuous source interval.
6. Write clips with stable IDs and a JSON manifest. Convert samples to seconds only for reporting, retaining enough precision to recover boundaries. Record any omitted silence or nonspeech gaps so later editing can preserve or deliberately remove them.
7. Listen to boundaries, inspect clips for empty or clipped speech, and verify every written file against its manifest entry.

## Output and handoff

Return `slice_dir` and `metadata_path`. A continuous source clip can be represented as:

```json
{
  "source_audio": "source.wav",
  "source_video_offset": 0.0,
  "segments": [
    {"id": "0000", "audio_path": "slices/0000.wav", "source_start": 0.25, "source_end": 6.4, "duration": 6.15, "speaker": "speaker-1"}
  ],
  "gaps": [{"source_start": 0.0, "source_end": 0.25, "reason": "leading silence"}]
}
```

Paths resolve against the manifest directory; all times are seconds. `source_start`/`source_end` refer to the original `source_audio`. The offset's sign is defined by `source_video_time = source_audio_time + source_video_offset`; apply it once when creating video replacement slots. Transcribe clips by ID, keeping full-recording context available for the later rewrite.

## Completion checks

- Every manifest path opens and has positive duration matching its actual samples.
- Source intervals are within the source duration and ordered. Gaps and any deliberate overlap are explicit.
- Listening confirms that slices retain complete speech and the intended speaker. A silent source yields a clear no-speech result, not an empty successful pack.

## Source adaptation

The original RMS slicer emitted timed WAVs but returned only a status. Its optional short-clip merge had a call-signature error and could misstate offsets across removed gaps. This skill makes the manifest an explicit output and preserves source timing through every operation.
