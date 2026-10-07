---
name: video-adapt-standup
description: Adapt reference material into a segmented stand-up performance script with delivery tones and deliberate audience-reaction cues.
metadata:
  source-role: "StandUpAdapter"
  source-path: "environment/roles/stand_up/stand_up_adapter.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Adapt a stand-up script

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

Turn supplied material into a performable monologue whose setups, punchlines, and pauses survive later speech synthesis and video editing.

## Inputs

- Reference text or transcript and the user's requested topic, audience, language, and changes.
- Desired performance length and delivery style. Use the user's length; the source's 3-5 minutes is a fallback only when useful.
- Optional existing segment IDs, available delivery tones, and reaction assets.

## Workflow

1. Read the complete reference. Identify the premise, setups, punchlines, callbacks, and contextual facts that the adaptation needs.
2. Rework those beats for the requested audience and language. Localize references where needed, preserving the joke's cause and payoff. Make transitions speakable rather than leaving isolated rewritten jokes.
3. Divide the performance into meaningful spoken lines. Preserve IDs for adapted existing segments. If one segment must split, retain its parent ID and assign explicit child IDs; never renumber unrelated lines.
4. Assign delivery notes from the source vocabulary `Natural`, `Confused`, `Empathetic`, and `Exclamatory`, or the available backend's supported equivalents. Use tone to support meaning rather than rotating labels mechanically.
5. Add `Laughter` or `Cheers` after selected lines only when those reactions help the requested performance. Leave space after a punchline. The original suggested 3-4 reactions for a 3-5 minute set; adapt to the actual script rather than filling a quota.
6. Read the script aloud or rehearse its cadence. Estimate duration using plausible delivery and the planned reaction pauses; label this an estimate until synthesis or recording is measured. Trim weak setups or repeated explanations when it runs long.
7. Save title separately from spoken lines. Keep tone labels, reaction labels, and stage directions outside spoken `text`.

## Output and handoff

Return a script artifact containing a title and ordered segments, for example:

```json
{
  "title": "The build is almost done",
  "segments": [
    {"id": "line-01", "tone": "Natural", "text": "The progress bar says one minute."},
    {"id": "line-02", "tone": "Confused", "text": "It said that before lunch.", "reaction": "Laughter"}
  ]
}
```

If plain text is needed, write each spoken line as `[Tone] text [Reaction]` with a separately labeled title. Pass the structured records to synthesis so no parser needs to guess whether the first line is dialogue. Leave `start` and `end` unset or null until audio exists.

## Completion checks

- Every spoken line has an ID, nonempty text, and a clear delivery instruction; reactions are separate events or explicit post-line cues.
- The set makes sense when read continuously, and each punchline still has its required setup.
- The script meets the user's requested audience, language, and approximate length without claiming measured timing.

## Source adaptation

The original prompt both prohibited titles and requested one, while its synthesizer always skipped the first line. This skill removes that ambiguity by separating the title and spoken segments.
