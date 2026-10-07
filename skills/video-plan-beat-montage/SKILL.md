---
name: video-plan-beat-montage
description: Plan a visual montage across measured music intervals, matching scene energy to accents and available footage. Use when rhythm cues exist and a timed storyboard is needed.
metadata:
  source-role: "RhythmContentGenerator"
  source-path: "environment/roles/vid_rhythm/rhythm_story_gen.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Plan a beat montage

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Build a storyboard around actual soundtrack intervals and the user's visual idea. The result is a timed scene plan ready for shot search.

## Inputs and tools

- Creative brief, measured soundtrack duration, rhythm events or selected cut boundaries, and optional energy measurements or rhythm plot.
- Available footage descriptions or an explicit request to design scenes for new footage. Keep these modes distinct in feasibility reporting.
- JSON/file tools and reasoning are sufficient for planning. Audio playback or image inspection can verify the musical pattern; a referenced plot must be opened to use its visual evidence.
- If timing data is missing, report the missing artifact and return only an untimed concept if useful. Do not invent a default scene count and call it synchronized.

## Workflow

1. Read the cue data and its detector method. Validate the intended soundtrack range, sorted boundaries, and exclusions. Interior cut points produce one more interval than their count when both endpoints are included.
2. Inspect the musical energy or audition the track. Identify phrase changes, builds, pauses, and releases. A path to an unread plot conveys no energy information; when evidence is absent, mark intensity choices as editorial suggestions.
3. If footage is supplied, review the full inventory or make source-linked summaries of manageable batches, then combine them while retaining source references. Do not truncate the library to its first entries or assume summaries describe every usable shot.
4. Outline the requested narrative or thematic progression across the intervals. Assign impact shots to supported accents and allow calmer spans to breathe. Avoid changing scenes on every detected event when that would make the subject unreadable.
5. Write one or two sentences per scene describing visible subject, action, setting, framing, and motion. Maintain recurring identity from references; appearance not established by the material remains unspecified.
6. Preserve cue boundaries unless revising the cut plan is part of the request. If a selected interval is too short or long for its intended scene, record the conflict and proposed alternate grouping. Keep original cue IDs for traceability.
7. Save stable scene IDs, start/end times, visual queries, and cut rationale. A storyboard for existing footage must expose unsupported scene requirements before retrieval or rendering.

## Output contract

```json
{
  "audio_path": "music/theme.wav",
  "duration": 12.0,
  "scenes": [
    {
      "id": "scene-01",
      "start": 0.0,
      "end": 4.0,
      "visual_query": "Wide shot of the empty workshop as the lights come on.",
      "end_cue_id": "cut-01",
      "cut_reason": "Reveal the team on the measured accent.",
      "footage_status": "supported",
      "source_refs": ["src-01-shot-004"]
    }
  ],
  "unresolved": []
}
```

The example contains one row only; a complete plan includes every interval through the intended end. Narration is optional and remains separate from visual queries.

## Validation

- Every requested interval has exactly one identified scene, or an explicit documented grouping. Confirm continuous coverage, positive durations, and the intended final endpoint.
- Compare scene descriptions with inventory evidence and check that action can be understood within the allotted duration.
- Review energy progression against measured or auditioned music. Report inferred intensity separately from measured cues.
- Reopen the saved plan and verify each cut references the correct cue, without positional pairing or lost unmatched scenes.
