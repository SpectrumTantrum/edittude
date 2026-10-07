---
name: video-summarize
description: Summarize supplied videos, audio, or transcripts to a requested language, angle, and length with source coverage. Use for a concise content summary, not a timed storyboard or rendered highlight reel.
metadata:
  source-role: "VideoSummarizationGenerator"
  source-path: "environment/roles/vid_summ/summ_loader.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Summarize footage

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `speech_transcribe`.

Produce a source-grounded summary that preserves the important developments across the requested material, including its ending or conclusion.

## Inputs and tools

- Video/audio files, a directory, or transcript text; requested angle, language, length, and presentation style as text or a file.
- Output file path or requested response format. Optional source timestamps and a spoiler boundary.
- Use a file reader for transcripts. Use available speech recognition only when audio must be transcribed; initialize no model merely to read text. Use frame inspection only when the requested summary depends on visual content.
- Report missing source, decoder, transcription, or visual-inspection capabilities. A transcript-only summary must identify that scope rather than imply visual review.

## Workflow

1. Inventory the requested scope and distinguish media from text. Read presentation style files as content. Validate that existing transcripts belong to the selected media and retain file identity.
2. Transcribe media in its detected or requested language when needed. Keep timestamped chunks, uncertainty, and per-file failures. Silence is a valid observation, while an error message is not transcript content.
3. Cover the full requested material. For long inputs, make source-linked section summaries, then combine them while preserving key chronology, causal links, and disagreements. Track processed sections so later material is not lost to a context limit.
4. Identify the main subject, important developments or claims, and conclusion. Follow the requested angle and spoiler boundary. Separate speech claims from observed visuals and interpretation. Use original dialogue only when the source supports it.
5. Draft in the requested language and presentation style. Favor connected prose unless another format was requested. Remove duplication and detail that does not affect the requested summary, while retaining caveats that change meaning.
6. Check the requested length with a declared word or character counting method. For a runtime target, provide a labeled estimate until real narration exists. This skill does not assign edit timestamps or claim a rendered video.
7. Save the summary and its source coverage. Keep source references in the text or a compact adjacent record according to the requested format; they must remain available for review.

## Output contract

Return summary text or its saved path, actual word/character count, source list, processed coverage, and limitations. A structured delivery can use:

```json
{
  "summary_path": "output/summary.md",
  "language": "en",
  "count_method": "whitespace-separated words",
  "word_count": 180,
  "sources": [
    {"id": "src-01", "path": "media/interview.mov", "status": "transcribed", "coverage_start": 0.0, "coverage_end": 420.5}
  ],
  "summary_sections": [
    {"id": "summary-01", "source_refs": [{"source_id": "src-01", "source_start": 24.1, "source_end": 45.0}]}
  ],
  "limitations": ["Based on spoken content; visuals were not inspected."]
}
```

Use null source times plus text anchors when timestamps are unavailable. The example counts are illustrative; compute delivery values from the actual artifact.

## Validation

- Compare the summary with evidence from the beginning, middle, and ending of every included source. Confirm the requested theme and important caveats survived compression.
- Check names, numbers, quotations, and causal claims against source passages. Attribute disagreement rather than merging incompatible accounts.
- Recount final length and reopen any saved file. Confirm that successful sources, partial sources, and failed sources are reported accurately.
- A copied source prefix or a generic fallback is not a completed summary. Return partial status when missing coverage prevents the requested account.
