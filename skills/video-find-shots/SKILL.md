---
name: video-find-shots
description: Match storyboard scenes to usable intervals in existing footage, preserving one result per scene and explaining unmatched requirements. Use for semantic shot retrieval before editing.
metadata:
  source-role: "VideoSearcher"
  source-path: "environment/roles/vid_searcher.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Find shots

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `image_describe`.

Find footage that can support each requested scene and fit its duration. Keep scene identity intact through retrieval and selection.

## Inputs and tools

- Ordered scenes with stable `id`, a `visual_query`, required duration or timeline `start`/`end`, and any subject, continuity, or framing constraints.
- A footage index containing source IDs, paths, source intervals, and inspected descriptions; source media for candidate verification.
- Use available text search for a small index or an existing semantic search tool for a larger one. Use frame extraction with `image_describe`, video playback, or an editor preview to verify matches.
- Missing index: build or inspect enough source records to support the requested scope. Missing media or visual inspection: label candidates unverified and report the exact dependency instead of declaring a match.

## Workflow

1. Validate scene IDs and required durations. Import delimiter-based text only by creating an explicit ID for every nonempty scene; retain the mapping in the output.
2. Search each visual query for the subject, action, setting, and shot requirements. Expand synonyms only while preserving mandatory subjects and actions. Consider all available records needed for coverage; disclose any search limit.
3. Filter by actual constraints: decodability, usable duration, requested exclusions, and framing. Exclude credits or titles only when detected or requested. A fixed percentage of runtime is not evidence of credits.
4. Inspect promising intervals in source media. Check that the relevant action persists long enough and is not merely mentioned in the transcript. Rank by semantic fit, usable duration, visual quality, and continuity with adjacent selections.
5. Prefer varied shots when several fit, while allowing deliberate reuse when the brief requires it. If one shot is too short, return a candidate sequence with explicit source ranges or mark the scene unresolved. Never silently substitute another scene's match.
6. Return one record for every input scene, including those with no match. Keep a small set of useful alternatives and the reason for the selected candidate. Source timestamps remain source-relative seconds.

## Output contract

```json
{
  "scenes": [
    {
      "id": "scene-01",
      "required_duration": 3.0,
      "status": "matched",
      "selected": {
        "source_id": "src-01",
        "source_path": "media/interview.mov",
        "source_start": 12.4,
        "source_end": 18.2,
        "reason": "Speaker and whiteboard remain visible for the full interval."
      },
      "alternatives": []
    },
    {"id": "scene-02", "status": "unmatched", "selected": null, "reason": "No supplied footage shows the required location."}
  ]
}
```

The selected interval is a verified candidate range. Final trim points may be narrower when assembling the edit.

## Validation

- Output scene IDs and order exactly match the input, including unmatched rows. Join records by IDs rather than position.
- Each candidate resolves to a real source and lies inside its duration. Confirm sufficient usable footage for the requested timeline interval.
- Spot-check selected frames against their queries and check neighboring scenes for accidental repeats or continuity breaks.
- Report unmatched scenes and unverified candidates separately from successful matches. A retrieval score alone does not establish visual fit.
