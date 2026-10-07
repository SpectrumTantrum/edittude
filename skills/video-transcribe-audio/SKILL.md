---
name: video-transcribe-audio
description: Transcribe spoken audio with source-linked timestamps for video search, subtitles, script adaptation, or selective dialogue replacement.
metadata:
  source-role: Transcriber
  source-path: environment/roles/transcriber.py
  source-revision: f207987e3cffb554aaa6ffdbe733efb30f4b51ed
---

# Transcribe audio

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `speech_transcribe`.

## Inputs and result

Take audio files or a directory, optional language/vocabulary hints, and required timing precision. Return UTF-8 text plus structured segments keyed to each source. Use source-relative seconds and stable IDs:

```json
{"source_id":"take-01","audio_path":"audio/take-01.wav","segments":[{"id":"take-01-001","start":1.2,"end":3.7,"text":"The train arrives at noon."}]}
```

This illustrates the contract, not a transcript to reuse. Include speaker labels only when grounded in diarization or user-provided identities. Keep uncertain words and timing uncertainty explicit.

For a speech-slice manifest, use each slice's existing `id` as the transcript's `source_id`, retain its `audio_path`, and keep ASR child segments under that row. Their `start`/`end` are local to the slice audio, not the original video. Carry the slice's source interval and `source_video_offset` as provenance without applying the offset to local ASR times. Do not replace slice IDs with new sequential transcript IDs.

## Workflow

1. Inspect audio and extract the selected stream from video if needed. Preserve the original and record any extraction offset. Avoid summing separate speakers' channels before deciding whether channel-based transcription is useful.
2. Choose an available ASR tool supporting the language and timing needed. The original uses FunASR through `fap transcribe`; another installed transcriber is acceptable. Inspect its actual interface, and `get_capabilities` for model availability, before running.
3. Transcribe the entire requested recording. For chunked input, keep chunk offsets and reconcile duplicate words in overlaps. Distinguish silence, music, and unintelligible speech from missing processing coverage.
4. Inspect disputed names/numbers and sample the beginning, middle, and end against the audio. Correct recognition errors while preserving spoken meaning. Label a cleaned reading transcript separately from a verbatim transcript.
5. For word-level replacement or subtitle sync, obtain actual word alignment. Sentence timestamps or estimated reading speed cannot establish word boundaries. When the tool lacks the necessary precision, report that limitation or use a supported aligner.
6. Save the transcript and timing files at explicit new paths. Preserve per-file errors in batch results. For speech rewriting, join each transcript `source_id` to its original slice `id`; combine that slice's ordered spoken text while retaining child segment IDs. Keep the full slice interval, including boundary silence, as the replacement slot.

## Completion

Verify finite, ordered timestamps within source duration, positive segment spans, complete processing coverage, and that overlapping spans are intentional speaker overlap. Check that silence did not produce repeated hallucinated speech. If audio cannot be listened to, label accuracy unreviewed. If no ASR tool is available, return the capability blocker; never invent a transcript from a filename or video description.
