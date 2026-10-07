---
name: video-index-footage
description: Index source footage into timestamped visual descriptions and transcripts for later shot retrieval. Use when a footage library needs searchable scene records.
metadata:
  source-role: "VideoPreloader"
  source-path: "environment/roles/vid_preloader.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Index footage

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `image_describe`.

Create a searchable inventory that preserves the link between every description and its source interval. This skill produces an index, not an edited video.

## Inputs and tools

- Source files or a directory, indexing scope, and an output location separate from source media.
- Optional existing scene index, transcript files, and desired granularity. Reuse records only when their source identity and duration still match.
- Use available media inspection and extraction tools such as `ffprobe`, `ffmpeg`, an editor's scene detector, or an installed video library. Use available speech recognition and image inspection for semantic records; `image_describe` reads extracted frames when it is configured. Embeddings are optional.
- If media cannot be decoded, report the file and missing decoder. If visual inspection or speech recognition is unavailable, mark that field unavailable. Metadata alone is not a semantic index.

## Workflow

1. Enumerate the complete requested scope deterministically. Probe each file for duration, streams, frame rate, dimensions, and rotation. Record unsupported and unreadable files separately. Assign stable `source_id` values and explicit paths; filenames alone can collide.
2. Segment using shot boundaries when available. Otherwise use documented fixed windows sized for the footage and intended edit. Cover `[0, duration]`, including fractional final seconds. Keep source timestamps in seconds rather than deriving them from filenames.
3. Sample frames at known timestamps inside each interval. Inspect additional frames around action changes or ambiguous samples. Preserve aspect ratio in previews. Record what was actually sampled so sparse coverage remains visible.
4. Describe visible subjects, actions, setting, shot size, motion, and useful edit constraints. Keep observed visuals separate from speech claims and inferred story context. Name a person only when established by the supplied material; describe visible attributes otherwise.
5. Transcribe speech if available, retaining local timestamps and converting them to source time. A silent or absent audio stream gets an empty transcript and an explicit status. Synthetic noise is not a substitute for missing audio.
6. Save structured scene records and the per-file inventory. For a small collection, JSON plus text search is sufficient. If an existing semantic index is available, retain IDs and provenance when adding embeddings.

## Output contract

Return index path, indexed source count, scene count, coverage, and per-file failures. Each scene has a stable `id`, `source_id`, `source_path`, numeric `source_start` and `source_end`, visual description, transcript or reference, and evidence timestamps. Example scene:

```json
{
  "id": "src-01-shot-004",
  "source_id": "src-01",
  "source_path": "media/interview.mov",
  "source_start": 12.4,
  "source_end": 18.2,
  "visual": "Medium shot of the speaker turning toward a whiteboard.",
  "frame_times": [12.5, 15.0, 18.0],
  "transcript": [{"start": 13.0, "end": 15.4, "text": "Here is the result."}],
  "visual_status": "inspected",
  "audio_status": "transcribed"
}
```

## Validation

- Reopen the saved index. IDs are unique; every path resolves to its recorded source; all intervals satisfy `0 <= source_start < source_end <= duration`.
- Account for every requested file as indexed, partially indexed, or failed. State sampling limitations and uncovered intervals.
- Decode previews from the first, middle, and final indexed intervals and inspect representative semantic records. Confirm a known subject can be found in the saved records.
- Report partial completion when decoding, visual inspection, or transcription failed. Keep failures outside searchable content.
