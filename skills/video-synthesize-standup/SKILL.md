---
name: video-synthesize-standup
description: Synthesize a segmented stand-up script with controlled delivery and audience reactions, retaining per-line audio and metadata for video timing.
metadata:
  source-role: "StandUpSynth"
  source-path: "environment/roles/stand_up/stand_up_synth.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Synthesize stand-up audio

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `speech_synthesize`.

Render a monologue line by line, keeping comic delivery and reaction pauses intact through the final audio assembly.

## Inputs

- Ordered script records with stable `id`, spoken `text`, `tone`, and optional post-line `reaction`.
- Selected voice, language, delivery references if needed, and reaction audio such as laughter or cheers.
- Output directory and target performance length, if constrained. Existing voice authorization carries forward.

For legacy text, parse `[Natural]`, `[Confused]`, `[Empathetic]`, or `[Exclamatory]` and optional `[Laughter]` or `[Cheers]` markers directly. Treat an explicit title as metadata; keep the first spoken line. Ambiguous lines need correction rather than a model guessing a missing marker.

## Workflow

1. Resolve the complete line list and IDs. Inspect available TTS language, voice, style, and reference controls before selecting a backend. If it cannot provide a requested delivery, name the limitation and prepare the remaining inputs.
2. Map each tone to a supported style control or a matching reference from the same intended speaker. When reference transcripts are required, use the actual spoken reference words. The original expected tone-named WAV and `.lab` pairs; any explicit mapping with the same information is suitable.
3. Synthesize only spoken text. Collect all output chunks for each line, retaining its ID. Listen for correct words and delivery before moving the line into the final assembly.
4. For a reaction cue, append its requested asset after the punchline and any deliberate pause. Adjust the reaction's level and duration to fit the performance. If the required reaction asset is unavailable, keep that cue unresolved rather than silently omitting it.
5. Keep speech duration, reaction duration, and inserted silence distinct in metadata. Measure each final assembled line from samples, then concatenate lines in script order using a consistent sample rate and channel layout.
6. Listen to the set continuously. Revise rushed setups, reactions that bury the next line, or abrupt voice changes. Recompute durations after every audio edit.
7. Save the merged audio, individual line audio, and metadata to explicit paths. Preserve all IDs and notes needed by the timing and video stages.

## Output and handoff

Return `audio_path`, `seg_dir`, and `metadata_path` as real paths. Metadata records include:

```json
{
  "id": "line-02",
  "tone": "Confused",
  "text": "It said that before lunch.",
  "audio_path": "segments/line-02.wav",
  "speech_duration": 2.4,
  "pause_duration": 0.3,
  "reaction": "Laughter",
  "reaction_duration": 1.2,
  "duration": 3.9
}
```

The line's audio contains all listed parts. Relative paths resolve against the metadata file. Pass these records and the merged audio to timing so reaction time is included in video cuts.

## Completion checks

- All script IDs occur once in metadata with readable nonempty audio; no title or tone marker is spoken.
- Each requested reaction is present or explicitly unresolved. The final audio duration equals the measured assembled parts within sample or container tolerance.
- Listening confirms intelligible speech, consistent speaker identity, and room for punchlines. Missing lines block a complete-performance claim.

## Source adaptation

The original used a model to parse simple tags, skipped the first line, and returned metadata records where its schema promised a path. This skill parses explicit labels, retains dialogue, and returns an actual metadata file path.
