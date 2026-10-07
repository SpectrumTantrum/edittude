---
name: video-time-standup
description: Convert generated stand-up line audio and script metadata into measured video timing, including pauses and audience reactions.
metadata:
  source-role: "StandUpConversion"
  source-path: "environment/roles/stand_up/stand_up_conversion.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Time a stand-up performance

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Build the measured timeline that lets a video editor hold the setup, land the punchline, and leave space for the audience reaction.

## Inputs

- Ordered script metadata with stable `id`, `text`, `tone`, and final per-line `audio_path`.
- Assembled performance audio and any separately represented pauses or reactions.
- Optional visual queries or existing scene IDs. Preserve them for the later footage search and edit.

## Workflow

1. Match every metadata record to its explicit audio path by ID. For legacy numbered WAV files, establish and validate that mapping once. Resolve relative paths from the metadata file's directory.
2. Probe or decode every clip and measure its duration from sample count and sample rate. For multichannel audio, count frames, not total channel samples. Reject missing, zero-length, or unreadable segments.
3. Determine exactly what each line's file contains. If laughter and pauses are already appended, count that duration once. If they are separate events, include them in the actual assembly order.
4. Accumulate `start` and `end` in seconds from unrounded durations. Use the complete performance's actual sequence and crossfades, if any; a simple sum is correct only for butt-joined clips. Keep source IDs unchanged.
5. Retain tone, reaction, and visual query information so the editor can choose appropriate holds and cuts. A sentence boundary is a possible cut, not an instruction to cut away during every reaction.
6. Compare the final boundary with the decoded full performance and listen at selected line joins. Investigate disagreement before writing a ready timeline.
7. Save a timing manifest. Where word-level captions are required, align the final audio separately; line durations do not supply word timestamps.

## Output and handoff

Return `timestamp_path`. Example timeline record, with all values in seconds:

```json
{
  "id": "line-02",
  "text": "It said that before lunch.",
  "tone": "Confused",
  "reaction": "Laughter",
  "start": 2.8,
  "end": 6.7,
  "duration": 3.9
}
```

For an original VideoAgent consumer, also export `sentence_data.chunks` with `id`, end `timestamp`, and `content`; use the real entry count. If integer IDs are required, retain an explicit mapping to the original IDs. Empty input produces a no-segments result, not fabricated timing.

## Completion checks

- Every intended line and audio event is accounted for exactly once and retains its identity.
- Bounds are finite and ordered, and `duration = end - start`. Rounding happens only at export, not on each cumulative addition.
- The final end agrees with the actual assembled performance within output-sample or documented container tolerance, including reactions and silence.

## Source adaptation

The original accumulated WAV durations and emitted cumulative end timestamps. This skill preserves that behavior while retaining stable IDs, reporting missing files, and verifying against the final audio instead of silently shortening the timeline.
