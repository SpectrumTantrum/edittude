---
name: video-time-dialogue
description: Build measured speaker-aware video timing from dialogue turn recordings and their assembly metadata, including pauses and overlapping turns.
metadata:
  source-role: "CrossTalkConversion"
  source-path: "environment/roles/cross_talk/cross_talk_conversion.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Time dialogue for video

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Create a timeline that preserves who speaks, what they say, and when their audio actually occurs so editing and captions can follow the exchange.

## Inputs

- Ordered metadata with stable `id`, `speaker`, `text`, and final per-turn `audio_path`.
- The assembled dialogue audio and its pause, reaction, or overlap placement records.
- Optional source scene IDs and visual queries to carry forward.

## Workflow

1. Resolve every turn to an audio file using its ID. Validate declared speakers and unique IDs. For original numbered WAVs, make an explicit number-to-turn mapping before measuring anything.
2. Probe or decode audio to measure real durations. Count sample frames rather than channel samples. Reject absent, empty, or corrupt recordings rather than shifting later turns into their place.
3. Determine whether each file includes leading/trailing silence or reactions. Count each audio event exactly once. Use actual assembly placements for gaps, crossfades, and overlaps.
4. For concatenated turns, accumulate unrounded durations from time zero to obtain `start` and `end` in seconds. For overlapping turns, retain each independent interval on the shared timeline; the total duration is the latest event end, not the sum of turn durations.
5. Carry `speaker`, `text`, tone, source scene IDs, and visual queries into the timing record. These support speaker cuts or reaction shots without forcing a cut at every change of speaker.
6. Compare boundaries against the final assembled audio and listen at speaker changes. Derive caption words through separate alignment if needed; sentence timing alone cannot provide word-level sync.
7. Write the timing manifest and return its path. Preserve IDs unchanged, including across optional legacy exports.

## Output and handoff

Example record, with all times in seconds:

```json
{
  "id": "turn-02",
  "speaker": "partner",
  "text": "By teaching it to you?",
  "tone": "Confused",
  "start": 2.6,
  "end": 4.3,
  "duration": 1.7
}
```

Return `timestamp_path` to the complete manifest. Relative file paths resolve against that manifest. For a legacy VideoAgent consumer, export `sentence_data.chunks` with `id`, end `timestamp`, and `content` formatted as `[speaker] text`; use the actual count and retain an ID mapping if the consumer requires integers. That legacy end-only format cannot fully describe overlaps, so keep the full interval manifest authoritative.

## Completion checks

- Every requested turn appears with its original ID and correct speaker. Each interval is finite and positive.
- Nonoverlapping turns are ordered; intentional overlaps and gaps match the assembly records. No cumulative rounding drift remains.
- The latest event end matches the decoded final audio within sample or documented container tolerance, including silence and reactions.

## Source adaptation

The original summed numbered WAV durations, prefixed text with the speaker name, and skipped missing files. This skill preserves the speaker-aware handoff while validating coverage and supporting the actual assembled timeline.
