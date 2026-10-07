---
name: video-write-commentary
description: Adapt supplied story or reference text into grounded spoken commentary and aligned visual queries. Use for narrated reviews, recaps, or explanations that need a voice-ready script and storyboard.
metadata:
  source-role: "CommentaryContentGenerator"
  source-path: "environment/roles/vid_comm/comm_story_gen.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Write commentary

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Create spoken commentary that preserves the source's causal story and gives each spoken segment a useful visual intention.

## Inputs and tools

- Source text or files, creative requirements, language, length or runtime target, and presentation style supplied as text or a file.
- Optional footage inventory and character references for grounded scene queries.
- A text-capable agent and file-reading tools are sufficient. Media duration and actual speech synthesis are needed only to verify runtime later.
- If a required source or style file cannot be read, report its path and stop that dependent stage. Decode text faithfully; corrupted replacement characters are not a successful source read.

## Workflow

1. Read the style content when a file was supplied. Read the full requested source scope; for large works, summarize by section with source anchors and retain the ending and causal links. Report any intentionally omitted scope.
2. Extract the story facts needed for the requested angle: initial situation, goals, turning points, consequences, and outcome. Keep dialogue verbatim only where present in the source. Distinguish interpretation from factual recap.
3. Draft a coherent spoken narrative in the requested language and tone. Establish context quickly, retain plot-changing events, and remove repetition or descriptions that do not serve the requested angle. Match the user's specified spoiler boundary.
4. Check the requested word or character count with a declared counting method. For runtime targets, estimate from an appropriate speech rate and label the estimate. Actual recording or synthesis duration will determine final timing.
5. Split at speakable sentence or clause boundaries. Give each segment a stable `id`; retain punctuation that helps speech delivery. Make only renderer-specific punctuation changes in a derived export when a real downstream requirement calls for them.
6. Write one visual query per segment. Prefer source-supported actions and established appearances. For abstract commentary, use relevant illustrative footage and label it as such. Do not replace a quiet statement with an invented fight or other unsupported event.
7. Save the segmented script, visual queries, and source anchors. Keep canonical names and wording intact; voice-specific pronunciation can use a separate field. Untimed segments keep null start/end fields until aligned to real audio.

## Output contract

```json
{
  "language": "en",
  "count_method": "whitespace-separated words",
  "word_count": 9,
  "scenes": [
    {
      "id": "scene-01",
      "text": "The team returned to the workshop after the trial.",
      "visual_query": "The established team entering their workshop.",
      "visual_mode": "literal",
      "source_refs": ["source-01:paragraph-12"],
      "start": null,
      "end": null
    }
  ]
}
```

Count the actual completed script; the small example is illustrative. Timing values, when added, are seconds on the final narration timeline.

## Validation

- Trace factual claims, named characters, turning points, and quoted dialogue to source anchors. Check the ending against the requested scope.
- Recount length after the final edit. Read aloud or use available playback to catch awkward clauses and unclear pronouns.
- Confirm every script ID has exactly one visual query and that ordered exports preserve those IDs. Keep source text and generated narration distinguishable.
- Return any missing visual references and estimated runtime as limitations. A raw source excerpt is not a completed commentary script.
