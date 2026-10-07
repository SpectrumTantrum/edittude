---
name: video-write-news
description: Turn supplied news transcripts into a sourced spoken news recap with aligned footage queries. Use for news narration grounded in reference material rather than general story commentary.
metadata:
  source-role: "NewsContentGenerator"
  source-path: "environment/roles/vid_news/news_story_gen.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Write a news video

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Produce a concise news script with traceable claims and scene queries that preserve the identity of the people, events, and products being discussed.

## Inputs and tools

- Selected reference transcripts or videos, requested angle, audience, language, length, and presentation style as text or a file.
- Optional footage inventory, publication dates, and source links. Decide whether the request is a recap of supplied reporting or an updated report.
- Use file readers and available speech recognition when transcripts are missing. Use available browsing only when external verification or updates are part of the task.
- Missing transcription, unreadable source, or unavailable verification must be reported per source. Existing transcripts can be used without invoking an audio-extraction pipeline again.

## Workflow

1. Inventory the selected sources and read their transcripts with file or source IDs intact. A directory may contain several stories; include the requested set and expose exclusions rather than silently taking the first transcript.
2. Read the presentation style content. Build a short fact ledger for the event, participants, date, location, quantities, attribution, and uncertainty. Retain source timestamps in seconds where available and anchors otherwise.
3. Reconcile conflicting claims and distinguish event dates from publication dates. Frame claims from a transcript as what that source reported unless separately verified. Preserve caveats, estimates, and the difference between announced and completed actions.
4. Draft a news lead and a logical spoken explanation in the requested language. Default to neutral third-person reporting when no other style is specified. Preserve meaningful numbers, names, and direct-quote wording; do not fabricate dialogue.
5. Meet the requested word or character count using a stated method. Split into speakable sentences or clauses and assign stable scene IDs. Keep punctuation for natural speech. Put number expansion or pronunciation hints in a separate voice field when needed so the factual text stays auditable.
6. For every segment, write a concise visual query containing exact entity or product names where useful. Identify literal evidence shots, screenshots/documents, and illustrative B-roll separately. Generic footage must not imply that it depicts the actual reported event.
7. Save aligned script and scene rows with claim references. Leave start/end null until recording or synthesis establishes real timing. If runtime is estimated, label the estimate and keep it separate from timestamps.

## Output contract

```json
{
  "scope": "recap of supplied reporting",
  "sources": [{"id": "source-01", "path": "references/report.txt"}],
  "scenes": [
    {
      "id": "scene-01",
      "text": "The company said its trial included twelve stores.",
      "visual_query": "The company's trial announcement showing the twelve-store figure.",
      "visual_mode": "document",
      "source_refs": [{"source_id": "source-01", "anchor": "paragraph-4"}],
      "start": null,
      "end": null
    }
  ],
  "unresolved_claims": []
}
```

## Validation

- Check every number, proper noun, date, quote, and central claim against its cited source. Confirm uncertainty and attribution survived shortening.
- Recount the final script and check pronunciation without changing entity identity. Retain source-linked canonical text.
- Confirm one visual query per scene ID and flag unavailable evidence footage. Reopen the saved artifact to check complete source and scene coverage.
- State the reporting scope and any sources that failed. Saving a transcript excerpt or error message is not successful news writing.
