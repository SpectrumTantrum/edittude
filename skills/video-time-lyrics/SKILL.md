---
name: video-time-lyrics
description: Convert aligned singing lyrics, notes, and rests into phrase timestamps and instrumental intervals for captions, music-video storyboards, and edit timing.
metadata:
  source-role: "SVCConversion"
  source-path: "environment/roles/svc/svc_conversion.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Time lyrics for a video edit

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Produce explicit lyric and instrumental intervals from the final singing alignment, then verify them against the actual vocal used in the edit.

## Inputs and tools

- Required: `analysis_path` containing final adapted lyrics and timed musical units, plus the destination for timestamps. `adapted_lyrics` may accompany it for a text consistency check.
- The portable analysis has `duration_seconds` and ordered `units`. Each unit has `id`, `kind`, `text`, `start`, `end`, and `notes`. Lyric notes contain `pitch`, `start`, and `end`; rest units contain no notes. All times are seconds from audio start.
- Use the final `audio_path` if available, after any synthesis, conversion, or mix timing changes. Obtain the output frame rate for edit-boundary checks, and a project placement offset if needed.
- JSON handling needs no model. Use an audio player or waveform view for verification; an available forced aligner may refine boundaries but singing alignment must still be checked by listening.

## Workflow

1. Validate that every unit has a finite positive interval, all units are ordered, and they cover the intended duration. A lyric unit may contain several sequential notes; use the unit's total interval rather than assuming one note per character.
2. If importing legacy `text`/`notes_duration`, tokenize `AP` as one known rest marker and sum all durations inside each ` | ` group. Validate exact lyric/rest-to-duration counts before advancing a cursor. Never stop at whichever list ends first and silently drop the remainder.
3. Group neighboring lyric units into phrases at rests and meaningful syntactic or musical boundaries. Preserve each phrase's true first onset and final offset. Give each group a stable ID and retain its ordered `unit_ids`; reuse that ID when wording changes but grouping does not. Keep syllable boundaries when karaoke highlighting is requested.
4. Retain all instrumental intervals, including short gaps, the opening, and the tail. For scene planning, divide long instrumental passages at musically useful boundaries when the desired shot length warrants it. Twelve seconds is not a universal scene rule.
5. Check phrases against the final vocal and record any latency or drift adjustment. Distinguish score-derived timestamps from audio-verified timestamps. If timing remains uncertain, flag the specific interval.
6. Export explicit start/end intervals with stable IDs, `unit_ids`, readable `text`, and full precision. Reconstruct word boundaries from the adapted lyric and its unit mapping; syllable tokens alone may not preserve spelling or spaces. Round only for a target format, preserving ordering. For video cuts, round to frame boundaries at the final export; for captions, use their required timestamp precision.
7. Read the saved file back and verify coverage, final duration, counts, and text. Preserve the original analysis.

## Handoff

Return `timestamp_path` pointing to JSON with this structure:

```json
{
  "timebase": "seconds-from-audio-start",
  "duration_seconds": 2.0,
  "timing_basis": "score-derived",
  "segments": [
    {"id": "instrumental-01", "unit_ids": [1], "kind": "instrumental", "start": 0.0, "end": 0.5, "text": ""},
    {"id": "phrase-01", "unit_ids": [2], "kind": "lyric", "start": 0.5, "end": 2.0, "text": "home"}
  ]
}
```

`unit_ids` refers to the unchanged IDs in `analysis_path`, preserving the many-to-one relationship between sung units and phrases. Each source unit belongs to exactly one exported interval. Set `timing_basis` to `audio-verified` only after checking the final audio. Include a separate project placement offset if supplied.

For a legacy consumer, derive `sentence_data.chunks` from these rows with `timestamp = end`, `content = text`, and `count` equal to the row count. Only that legacy export uses `content: "bgm"` for instrumental rows. Retain the stable ID and `unit_ids`, or an explicit ID mapping if integer IDs are required. The portable interval records remain authoritative.

The storyboard stage can create images or shot descriptions from these intervals. Caption generation uses only lyric chunks. Shot boundaries are candidates: preserve held shots where the visual rhythm benefits from them.

## Verification

- Check the opening, a middle phrase, every timing correction, and the final lyric against the output audio. The end of the last lyric may precede the end of the song.
- Consecutive intervals have no unexplained gaps or overlaps; instrumental intervals account for the full remaining duration.
- Reconstruct phrase text from the aligned units and compare it with exported text. Verify that `unit_ids` partitions the complete source unit sequence without duplication or omission. Confirm frame rounding does not produce zero-length shots or reversed boundaries.
