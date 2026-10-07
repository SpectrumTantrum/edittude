---
name: video-narrate-scenes
description: Generate scene narration and measured audio timings from an ordered video script. Use for commentary, news, or other added voiceovers.
metadata:
  source-role: "VoiceGenerator"
  source-path: "environment/roles/voice_generator.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Narrate scenes

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `speech_synthesize`.

Turn an ordered script into narration audio and a scene timing manifest. Preserve scene IDs so the editor can match the narration to its intended visuals.

## Inputs

- Ordered scenes with stable `id`, spoken `text`, and any delivery or pronunciation notes. Visual descriptions are context, not automatically spoken text.
- Voice selection, language, optional authorized voice reference and its accurate transcript, and an output directory.
- Existing timing constraints, if any. Distinguish a fixed video timeline from a new video whose cuts can follow narration.

Legacy input may have `content_created` separated by lines of slashes. Convert those blocks to scenes once. Keep existing IDs; assign IDs only when the source has none.

## Workflow

1. Read the supplied script path and account for every scene. Resolve empty narration explicitly as a silent scene or an input error. Keep the chosen language, scene order, visual queries, and upstream scene metadata.
2. Inspect the available speech tool's supported voices, language, reference requirements, and output format. Use an existing suitable backend. If the requested voice capability is unavailable, return the prepared script and name that missing capability. Carry forward authorization already provided for the requested voice.
3. For reference-based synthesis, pair actual reference audio with its own transcript when the backend requires one. Use the selected stock voice when a reference is unnecessary.
4. Synthesize each scene. Split long text at natural sentence boundaries, including Chinese punctuation when relevant, within the backend's limit. Concatenate every returned chunk in order and retain the scene ID. Keep labels, stage directions, and delimiters out of the spoken text.
5. Listen to each scene for omissions, repeated words, pronunciation, and abrupt joins. Repair failed chunks without dropping the scene. For a fixed duration, revise wording or use a supported speaking-rate control, then remeasure.
6. Assemble audio in scene order with intentional pauses. Match sample rate and channel layout before concatenation. Derive timings from the final samples, including pauses; do not estimate timings from character counts.
7. Save the audio and manifest together. Preserve the input media and report any incomplete scene as incomplete, with its ID.

## Output and handoff

Return `audio_path` and `timestamp_path`. The manifest uses seconds and records the actual timeline, for example:

```json
{
  "audio_path": "narration.wav",
  "scenes": [
    {"id": "scene-01", "text": "The train arrives.", "start": 0.0, "end": 2.45, "duration": 2.45}
  ]
}
```

Resolve relative artifact paths against the manifest directory. Preserve upstream scene IDs exactly. If a legacy editor requires `sentence_data.chunks`, export each record as `id`, cumulative end `timestamp`, and `content`; set `count` to the actual records and retain an ID mapping if the consumer only accepts integers.

## Completion checks

- Every intended spoken scene has decoded, nonempty audio and exactly one manifest entry.
- Scene boundaries are ordered, `duration = end - start`, and the final end matches the decoded assembled audio within one output sample or documented container tolerance.
- Listening confirms the final narration says the intended words and leaves room for the planned cuts. A successful tool exit alone is insufficient.

## Source adaptation

The original used CosyVoice2, ignored its supplied scene path, and supplied a fixed reference transcript. This skill uses the actual input and backend contract. It also treats missing generated chunks as failures instead of silently shortening the narration.
