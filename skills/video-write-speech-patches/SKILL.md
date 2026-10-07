---
name: video-write-speech-patches
description: Rewrite transcribed speech segments for a video redub while preserving segment identity, phrasing, and timing constraints.
metadata:
  source-role: "TTSWriter"
  source-path: "environment/roles/tts/tts_writer.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Write speech patches

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Rewrite a source performance one segment at a time while preserving the connection between each line, its reference audio, and its source interval.

## Inputs

- User's requested changes, intended language, tone, and facts that must remain.
- Full transcript for context and an ordered segment manifest with `id`, original `text`, `source_start`, `source_end`, and reference `audio_path`.
- Any fixed timing or lip-sync constraint. All times are seconds on the source timeline.

If only sliced WAV and `.lab` files exist, join each transcript to its matching audio filename and timing record. Establish IDs from those filenames; do not rely on two independently sorted lists having matching positions. Missing or uncertain transcript text needs transcription or review before rewriting.

For structured ASR output, join `transcript.source_id` to the slice `id` and combine that slice's child `segments` in local-time order to obtain `original_text`. Keep the slice ID as the patch ID and retain child IDs as `transcript_segment_ids`. Preserve the full slice bounds rather than shrinking the replacement slot to the first and last recognized words. Missing or duplicate source IDs block that patch.

When the slice bounds are relative to extracted audio, convert them once to the source-video timeline: `video_time = audio_time + source_video_offset`. Record that the resulting patch bounds use `seconds-from-source-video-start`; downstream replacement must not apply the offset again. A noncontinuous reference clip retains its source interval list and cannot define a single replacement slot without an explicit edit decision.

## Workflow

1. Read the full transcript and every segment. Identify setup, response, payoff, and connections across boundaries so a local substitution does not break the surrounding thought.
2. Rewrite each requested segment in the source's sentence structure and delivery style. Apply the user's desired changes; preserve unaffected segments and facts unless the requested adaptation changes them.
3. Keep the replacement close to the original spoken length. For Chinese word substitutions, the source's heuristic was a difference of at most two characters; treat that as a drafting aid, not proof of equal duration. In other languages, compare syllables and plausible spoken phrasing.
4. Retain exactly one output record per input ID, in order. Separate spoken text from notes. Record an intentional deletion as a deletion, never as a vanished row.
5. Read the rewritten segments continuously for coherence and comic or narrative timing. Shorten awkward lines before synthesis and mark any timing requirement that still needs measurement.
6. Save structured patches directly. A second model call is unnecessary just to extract text from a format the writing agent controls.

## Output and handoff

Return `speech_path` to a UTF-8 JSON file, for example:

```json
[
  {
    "id": "0003",
    "source_start": 12.4,
    "source_end": 18.7,
    "audio_path": "references/0003.wav",
    "timebase": "seconds-from-source-video-start",
    "transcript_segment_ids": ["0003-001", "0003-002"],
    "original_text": "We waited all day for the bus.",
    "text": "We waited all day for the build.",
    "timing_status": "awaiting_synthesis"
  }
]
```

Resolve relative audio paths against the manifest directory. Pass this file with the original reference transcripts to speech synthesis. Export one plain-text line per segment only if a consumer needs it, and include the ID order alongside that export.

## Completion checks

- Input and output ID sets and order match; every rewrite is tied to its correct source interval.
- The continuous rewrite satisfies the request without broken references between segments.
- Timing claims remain provisional until synthesized audio is measured. Similar word or character count does not establish sync.

## Source adaptation

The original used Claude to write and DeepSeek to extract line-based text. This skill preserves the slice-by-slice adaptation without vendor dependence or positional-only handoffs.
