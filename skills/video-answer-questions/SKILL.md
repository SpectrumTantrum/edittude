---
name: video-answer-questions
description: Answer questions about supplied videos or audio from source-linked transcripts, with explicit evidence gaps. Use for finding facts in footage; visual questions require actual frame inspection.
metadata:
  source-role: "VideoContentQA"
  source-path: "environment/roles/vid_qa/content_loader.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Answer questions about footage

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `speech_transcribe`.

Answer from the supplied media evidence and make it possible to find the supporting moment. The original role is transcript-based; transcript evidence alone does not establish what appeared on screen.

## Inputs and tools

- One or more questions, selected media or transcripts, and optional history/output location.
- File search and reading tools for existing transcripts. Use available speech recognition for missing transcripts, and media probing for duration. Frame extraction or playback is needed only for visual evidence.
- Reuse a transcript only when its source identity and coverage match. Report missing speech recognition, media, or visual-inspection support by file and question; answer supported portions when possible.

## Workflow

1. Inventory the requested files and assign stable source IDs. Distinguish readable transcripts, media needing transcription, silent media, and failures. Count only successfully processed sources as processed.
2. Transcribe needed audio with the detected or requested language. Retain source-relative start/end timestamps in seconds, speaker labels when supported, and uncertain words. Preserve file identity in a combined index instead of flattening all speech into one anonymous text block.
3. Search all requested transcripts for the question's entities and concepts. Read context around each hit and compare other sources when the answer depends on them. For long collections, retrieve relevant passages across the full set rather than truncating the first portion.
4. Classify evidence before answering. Spoken content can support what a speaker said; appearance, action, and on-screen text require inspected frames. If the question exceeds available evidence, identify the precise gap.
5. Answer directly, citing source ID or filename and source timestamps for each material claim. Where transcripts lack timestamps, cite a paragraph or line anchor and say timing is unavailable. Preserve uncertainty and conflicting statements.
6. Return the answer for the current question without opening a blocking terminal question loop. Subsequent questions can reuse the validated source index. Save conversation history only when requested or part of the established workflow.

## Output contract

```json
{
  "question_id": "question-01",
  "answer": "The speaker says the trial included twelve stores.",
  "evidence": [
    {"source_id": "src-01", "source_path": "media/report.mp4", "source_start": 24.1, "source_end": 28.6, "kind": "transcript"}
  ],
  "coverage": {"requested_sources": 2, "processed_sources": 1},
  "failures": [{"source_id": "src-02", "reason": "Audio could not be decoded."}],
  "limitations": ["Answer reflects the successfully transcribed source only."]
}
```

For an unsupported answer, use an empty evidence list and state that the supplied evidence does not establish it. Distinguish absence of evidence from a negative factual conclusion.

## Validation

- Read each cited passage or inspect each cited frame again. Confirm the answer does not turn an allegation, prediction, or speaker opinion into an established fact.
- Verify source paths and timestamp bounds; check names or numbers against the audio when recognition is uncertain.
- Account for every requested source, including silence, partial transcription, and errors. Error strings never become source content.
- If saving output or history, reopen it and verify the current question, answer, evidence, and actual processing status.
