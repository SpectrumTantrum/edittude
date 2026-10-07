---
name: video-transcribe-melody
description: Extract a timed vocal melody and align lyrics from MIDI for a singing video or cover. Use before adapting lyrics, synthesizing singing, or timing lyric-driven edits.
metadata:
  source-role: "SVCAnalyzer"
  source-path: "environment/roles/svc/svc_analyzer.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Transcribe a melody for video

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `score_read`.

Produce a score that preserves the vocal melody, rests, and lyric placement on the audio timeline. The source role analyzes MIDI; audio-to-MIDI transcription is a separate capability and requires listening checks.

## Inputs and tools

- Required: `midi_path`, lyrics text or `lyrics_path`, lyric language, and a destination for the analysis.
- Use an identified vocal track/channel or select it by listening and inspecting its range and phrasing. A track whose note count matches the character count is not sufficient evidence.
- Obtain the intended audio duration and reference recording when available. Record any MIDI-to-audio offset or tempo discrepancy.
- Use a MIDI reader such as Mido, a score editor, or an available DAW. If only audio exists, use an available melody transcription tool and label uncertain pitches and boundaries. Do not invent a MIDI file or claim audio transcription from text alone.

## Workflow

1. Read the MIDI division, track/channel events, and tempo map. For ticks per beat, use 500,000 microseconds per beat only until the first tempo event. Handle SMPTE timing through a reader that supports it, or report that limitation.
2. Pair note-on and note-off events by track, channel, and pitch. Treat note-on with zero velocity as note-off. Flag unmatched events or overlapping instances that cannot be paired reliably.
3. Convert event boundaries to seconds by integrating each tempo interval that overlaps the boundary range. For a constant-tempo interval, seconds equal ticks times microseconds-per-beat divided by ticks-per-beat and 1,000,000. Skip intervals entirely before the range; a later note must never acquire negative time from an earlier tempo interval.
4. Select the vocal line. Separate harmony/chord notes from sequential melody notes. Keep sequential notes on one sung syllable together as a melisma; simultaneous pitches are not a melisma.
5. Align sung units with the melody using the score, recording, and pronunciation. A unit is a syllable or model-supported lyric token, not automatically a Unicode character. Preserve consonant placement, held vowels, repeated syllables, and breaths.
6. Represent every gap as a rest, including the lead-in and trailing duration needed by the edit. Use absolute seconds from the start of the intended audio. Mark disputed lyric-to-note mappings for correction before synthesis.
7. Save the analysis and read it back. Preserve the source MIDI and lyrics.

## Handoff

Return `name` and the absolute `analysis_path`. The JSON contract shared with lyric adaptation, singing synthesis, and lyric timing is:

```json
{
  "name": "song",
  "language": "zh",
  "duration_seconds": 2.0,
  "units": [
    {"id": 1, "kind": "rest", "text": "", "start": 0.0, "end": 0.5, "notes": []},
    {"id": 2, "kind": "lyric", "text": "家", "start": 0.5, "end": 2.0,
     "notes": [{"pitch": "C4", "start": 0.5, "end": 1.0},
               {"pitch": "D4", "start": 1.0, "end": 2.0}]}
  ]
}
```

`units` are ordered, nonoverlapping intervals covering `0..duration_seconds`. Each lyric unit contains sequential notes that cover its interval. Rest units contain no notes. Times are seconds relative to audio start, not project timecode. Record a project placement offset separately when supplied. Retain enough precision for later sample-boundary rounding.

For the original DiffSinger word-level interchange, `text` uses `AP` at rests, `notes` and `notes_duration` use ` | ` between lyric units, and spaces within a unit represent sequential notes and matching durations. `input_type` is `word`. Export this only when the selected language frontend can tokenize the lyrics consistently. Store the explicit units as the authoritative timing data. The bundled `singing_synthesize` adapter takes Mandarin only, one Chinese character per lyric unit, as in the example above.

## Verification

- Every note has a valid pitch and finite positive duration; all intervals lie inside the total duration.
- Every lyric unit is accounted for, including melismas and rests. No leftover notes or lyrics are silently dropped.
- Check the first note, a tempo-change boundary, each phrase onset, and the final note against the score or audio. State any source offset and unresolved uncertainty.
- If the model needs a monophonic melody and the intended part remains ambiguous, return the candidate analysis with that blocker instead of guessing a singer's line.
