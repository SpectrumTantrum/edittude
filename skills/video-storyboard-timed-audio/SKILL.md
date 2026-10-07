---
name: video-storyboard-timed-audio
description: Convert already timed speech, lyrics, or dialogue chunks into matching visual scene queries while preserving every chunk ID and boundary. Use for audio-to-storyboard mapping, not timestamp detection.
metadata:
  source-role: "VideoConversion"
  source-path: "environment/roles/vid_conversion.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Map timed audio to scenes

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Create one visual intention for each timed audio chunk. The existing audio timing is the contract; this operation does not infer or alter it.

## Inputs and tools

- Audio chunks with stable `id`, text, and numeric `start`/`end` in seconds, or ordered chunk-end timestamps with an explicit starting offset.
- Audio path and measured duration when available, plus optional footage inventory, character references, and visual style.
- A text-capable agent and JSON/file tools are sufficient. Use media probing to validate duration and available image inspection to ground visual identities.
- If timing is absent or ambiguous, produce an untimed visual draft with null boundaries and report that alignment is required. Do not label estimated timing as measured.

Accept interval rows from `scenes` or `segments`. For legacy `sentence_data.chunks`, copy `content` to `text` and treat `timestamp` as the cumulative end only when that meaning is established. Conflicting aliases are an input error. Preserve `kind`, `unit_ids`, `speaker`, and parent scene IDs through this deterministic field mapping. An instrumental row has empty spoken text; its legacy `bgm` marker is not narration.

## Workflow

1. Read the actual chunk content and boundaries. Preserve existing IDs. For legacy endpoint-only records, define `start` from the previous endpoint and record the initial offset; verify the timestamp meaning before conversion.
2. Check ordering, finite numbers, positive durations, and intended coverage. Preserve pauses and overlapping speech as explicit intervals or flags. Resolve conflicts with the audio timing before assigning a single-track visual sequence.
3. For each spoken or lyric chunk, identify its visible subject, action, location, and emotional function. Write one concise visual query that can retrieve or guide a shot. For an instrumental interval, use the surrounding story, music, and brief to plan a visual hold or scene while keeping its spoken text empty.
4. Keep visual claims grounded in the source or supplied character references. If a named person's appearance is unknown, retain the name and mark the reference missing; do not invent physical attributes from the name. Label symbolic or illustrative footage as illustrative.
5. Use footage availability to make the query achievable. Preserve critical subjects and facts; report unavailable requirements rather than substituting unrelated dramatic action. Split no chunks and add no scenes unless explicitly revising the timing plan.
6. Save the original text beside the visual query and unchanged boundaries. Carry upstream `kind`, `unit_ids`, speaker, and parent references into the scene row so grouped lyrics or dialogue remain traceable. English queries can help a search backend trained for English, but preserve the original narration language and names.

## Output contract

```json
{
  "audio_path": "audio/narration.wav",
  "scenes": [
    {
      "id": "scene-01",
      "start": 0.0,
      "end": 3.25,
      "text": "The team returned to the workshop.",
      "visual_query": "Wide shot of the team entering the established workshop.",
      "visual_mode": "literal"
    }
  ],
  "unresolved": []
}
```

If a downstream consumer requires `/////` separators, derive both text and scene strings from the same rows and include the ordered ID list. Structured rows remain authoritative.

## Validation

- Input and output IDs, order, count, text, and timing are identical after the documented legacy field mapping. Keep lyric `unit_ids` unchanged. Every timed row has `0 <= start < end` and fits the measured audio duration when known.
- Every visual query is nonempty and refers to that row's content. Review pronouns, recurring characters, and locations across adjacent rows for continuity.
- Confirm no scene count drift, fabricated identity details, missing pause coverage, or hidden timing estimates before handing off to retrieval.
