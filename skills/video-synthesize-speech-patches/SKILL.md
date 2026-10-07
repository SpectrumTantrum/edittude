---
name: video-synthesize-speech-patches
description: Synthesize rewritten video speech segments from matching voice references while preserving patch IDs and source timing for replacement.
metadata:
  source-role: "TTSInfer"
  source-path: "environment/roles/tts/tts_infer.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Synthesize speech patches

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `speech_synthesize`.

Produce one replacement recording per rewritten segment, with enough metadata to replace the corresponding source speech reliably.

## Inputs

- Ordered patches with stable `id`, replacement `text`, `source_start`, and `source_end` in seconds.
- Reference audio and its accurate original transcript for each patch, with speaker identity where available.
- Requested voice, language, timing policy, and output directory. Carry forward any authorization already provided for the voice request.

## Workflow

1. Match patches, source intervals, reference recordings, and transcripts by ID. Report missing, duplicate, or unmatched IDs before synthesis; extra rewrite lines must not disappear silently.
2. Inspect an available backend's documented reference and language requirements. Use a supported reference-based voice mode for matching the source speaker, or the chosen stock voice if that is the request. Name the exact unavailable capability if the requested output cannot be produced.
3. Check reference quality and transcript agreement. If a reference is too short for this backend, extend it with nearby speech from the same speaker, carrying the matching transcript and source interval list. Use the backend's actual minimum; the original's one-second threshold is not portable. Never borrow another speaker's voice to fill the duration.
4. Synthesize each replacement into a separate file. Use the replacement as target text and the original reference transcript as prompt text. Collect every generated audio chunk in sequence.
5. Decode and listen to each patch for correct words, intended speaker, intelligibility, and clipped beginnings or endings. A failed patch stays failed under its ID; retry or repair it without shifting later assignments.
6. Measure generated duration from samples. For fixed source timing, compare against `source_end - source_start`; revise wording or adjust a supported speech rate when needed. Preserve natural delivery rather than claiming arbitrary time compression is transparent.
7. Save all individual patches and a manifest. An optional concatenated preview is useful for listening, but it does not replace the per-patch files or establish sync with the source video.

## Output and handoff

Return `patches_path` and the audio directory. Example record:

```json
{
  "id": "0003",
  "source_start": 12.4,
  "source_end": 18.7,
  "text": "We waited all day for the build.",
  "audio_path": "patches/0003.wav",
  "duration": 5.91,
  "reference_ids": ["0003"],
  "status": "ready"
}
```

Paths resolve against the manifest directory. Pass measured duration and source bounds to the replacement step so it can preserve the video timeline or perform the explicitly chosen retiming.

## Completion checks

- Every requested patch has a verified decoded output, or appears in an explicit failure list that blocks a complete render claim.
- Original transcript, replacement text, reference speaker, and output file remain associated with the same ID.
- Measured durations are positive. Listen to a continuous preview and the joins before treating the patches as ready for video replacement.

## Source adaptation

The original used a Fish Speech encoding, text-to-semantic, and decoding pipeline with positional `.lab` files and shared temporary paths. This skill keeps the reference-based synthesis capability while selecting a real supported backend and making the output mapping explicit.
