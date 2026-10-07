---
name: video-separate-stems
description: Separate vocals or dialogue from music for voice replacement, lyric work, or remixing, and assess stem leakage before editing.
metadata:
  source-role: Separator
  source-path: environment/roles/separator.py
  source-revision: f207987e3cffb554aaa6ffdbe733efb30f4b51ed
---

# Separate stems

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `audio_separate`.

## Inputs and result

Take audio paths or a directory, the wanted stem types, and a fresh output directory. Return one record per source with `id`, `source_path`, actual stem paths, model/settings used, duration in seconds, and quality limitations. Preserve the original mix for comparison and possible fallback.

## Workflow

1. Inspect the mix. Extract audio from video when needed. Select an available separation model that supports the requested stems; a music-vocal model may leave sound effects or dialogue in both outputs.
2. Inspect the installed tool's help or documented interface before invocation. The original role invokes fish-audio-preprocess `fap separate`; Demucs or an editor's supported stem separator can perform the same capability. Check model availability with `get_capabilities`, and its permitted use, before downloading or running it. A simple EQ or a stereo center-channel subtraction is not equivalent to learned source separation.
3. Run into a new directory with a unique source-to-output mapping. For chunked inference, use the tool's overlap handling and retain offsets so chunks rejoin without missing samples.
4. Locate the files actually written; do not infer output filenames from the requested path. Inspect every stem's duration, sample rate, channels, and decoding. Keep all stems on the same timeline.
5. Compare the original, isolated voice, accompaniment, and recombined stems. Listen to consonants, reverb tails, sibilants, and music transients. Reject or qualify watery speech, missing syllables, residual lead vocals, or audible seams.

## Completion

Each source has usable stem paths or an explicit failure. State which downstream uses passed listening review. For speech replacement, check that the bed does not retain intelligible old words; for a song cover, check that the lead melody did not survive in the accompaniment. A file existing does not prove a clean separation. If no suitable model is installed, report that blocker and leave the source available for other edits.
