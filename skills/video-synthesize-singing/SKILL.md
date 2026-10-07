---
name: video-synthesize-singing
description: Render a dry singing vocal from timed lyrics and melody for a video soundtrack. Use when lyric syllables, pitch, rests, and phrase timing must follow a supplied score.
metadata:
  source-role: "SVCSingle"
  source-path: "environment/roles/svc/svc_single.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Synthesize timed singing

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `singing_synthesize`.

Render the adapted lyric on its specified melody, with a dry vocal stem that stays synchronized to the video timeline.

## Inputs and capabilities

- Required: `name` and `analysis_path` containing the final lyric alignment. `adapted_lyrics` may accompany it as readable text; resolve any disagreement with the aligned lyric before rendering.
- The portable analysis has `language`, `duration_seconds`, and `units`. Each unit contains `id`, `kind`, `text`, `start`, `end`, and `notes`. Lyric notes contain `pitch`, `start`, and `end`; rest units contain no notes. All times are seconds from audio start.
- `singing_synthesize` accepts Mandarin only. It rejects an analysis whose `language` is not `zh`, or whose lyric unit holds anything but one Chinese character.
- Use an available singing synthesizer such as DiffSinger with an installed compatible voice, language frontend, acoustic model, and vocoder. Confirm the actual installed interface and checkpoint requirements with `get_capabilities`. A text-to-speech model without melody control does not fulfill this task.
- Establish the destination, desired voice, sample rate, and output duration. Use the editor's audio rate when practical; resample the rendered stem once if the model requires another rate.
- If singing capability or the required language/voice model is unavailable, deliver the validated score and identify the missing capability. Do not report a rendered stem.

## Workflow

1. Validate positive finite durations, ordered intervals, full timeline coverage, and lyric-to-note alignment. Include leading and trailing rests in the total duration.
2. Translate lyrics through the selected model's pronunciation frontend. Inspect polyphonic words and names. For phoneme input, keep phoneme, pitch, duration, and slur arrays aligned according to that model's contract. A model may repeat a note duration for multiple phonemes; do not sum those duplicated conditioning values as elapsed audio time.
3. Keep sequential notes of a melisma on their intended vowel. For DiffSinger word input, separate lyric units with ` | ` in `notes` and `notes_duration`; use spaces inside a unit for sequential notes with matching durations. `AP`/`SP` require that frontend's supported rest handling. Simultaneous chord pitches require separate vocal parts.
4. Render by musical phrase within the model's context limit. Each call takes its own analysis file: re-base that phrase's units and notes so the first starts at 0.0, keep them contiguous, and cover its `duration_seconds` with explicit leading and trailing rests. `singing_synthesize` rejects units that start late, leave a gap, or stop short of the stated duration; absolute timeline times belong in the phrase's recorded start, not in its analysis. Group very short notes with neighboring notes to retain consonant and vowel transitions; choose groups from phrasing and the model limit, not a universal duration threshold. Use a task-specific output directory so old renders cannot enter a batch.
5. Render a short phrase first and listen for pronunciation, pitch, and timing. Correct the input or model settings before completing the song. Track the actual output file returned or created for every phrase and reject failed, empty, or undecodable renders.
6. Place each rendered phrase on the timeline at the absolute start it was re-based from, trimming the leading rest it was rendered with when that rest already exists in the timeline. Account for model lead-in and tail latency before any duration correction. Prefer rerendering incorrect timing; use pitch-preserving stretch only when the resulting diction remains acceptable. Retain word endings and breath tails rather than blindly trimming voiced audio.
7. Place rests as silence. Derive boundaries with `round(time_seconds * sample_rate)` and allocate each segment by the difference between adjacent absolute boundaries. This avoids drift from independently rounded segment lengths. Crossfade only inside allowed overlap or silence, without shifting later onsets.
8. Export a lossless vocal stem, preserve intermediate renders needed for correction, and read back its actual sample rate, channels, duration, and peak level. Keep accompaniment separate for the mix stage.

## Handoff

Return `audio_path` for the verified vocal stem, `analysis_path`, `name`, sample rate, channels, measured duration, and any timing correction applied. Preserve audio-start time zero; include a separate project placement offset when one was supplied.

Pass the stem to singing voice conversion only when a different timbre is required. Pass the same analysis to lyric timing, then mix the vocal with the intended accompaniment before the final video render.

## Verification

- Listen to the full stem or every generated phrase, with special attention to consonant joins, high notes, sustained vowels, and breaths. A successful inference exit code is insufficient.
- Compare phrase onsets and endings against the score and, when available, accompaniment. Check the final onset as well as the first to expose accumulated drift.
- Confirm no clipped peaks, NaNs, unexpected silence, truncated phonemes, or missing segments. Total sample count matches the intended timeline, with any intentional reverb tail reported separately.
- Report untested perceptual quality explicitly when audio playback or analysis is unavailable.
