---
name: video-convert-singing-voice
description: Change the timbre of an existing singing vocal using a supplied target voice reference while preserving melody, lyrics, and timing for a video soundtrack.
metadata:
  source-role: "SVCCoverist"
  source-path: "environment/roles/svc/svc_coverist.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Convert a singing voice

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `voice_convert`. Pass the skill's `target_vocal_path` as the callable's `reference_audio_path`.

Change vocal timbre while retaining the source performance's lyrics, pitch contour, rhythm, and placement. The output is a dry converted vocal stem for mixing.

## Inputs and capabilities

- Required: `audio_path`, the source singing vocal; `target_vocal_path`, the user-provided or authorized target reference; and an output destination.
- Carry the source's timeline offset, duration, sample rate, and any score or lyric alignment supplied by the preceding stage.
- Use an available singing voice conversion system such as Seed-VC with pitch conditioning enabled. Inspect the installed interface and read `get_capabilities` for model support before forming a command.
- Confirm that the target reference is intended for this conversion. Keep the requested voice identity and permitted use within the user's scope; do not replace it with an unrelated identifiable singer.
- Missing conversion weights, compatible compute, or target reference blocks rendering. Report the specific missing item and keep the usable source stem.

## Workflow

1. Probe and listen to both files. Use a dry source vocal and a clean single-voice reference where possible. Separate accompaniment before conversion if it masks the source voice, and retain it for later mixing.
2. Choose a reference excerpt with clear singing, adequate pitch coverage, and little noise or reverb. Inspect the model's supported reference length; more reference audio is not automatically used. Preserve the original reference file.
3. Configure pitch-conditioned conversion for singing. Preserve duration and pitch by default. With a compatible Seed-VC interface, the relevant controls are `--f0-condition True`, `--length-adjust 1.0`, `--auto-f0-adjust False`, and `--semi-tone-shift 0`. Verify those flags locally before use. Auto pitch adjustment or transposition requires an intended musical change.
4. Convert a phrase containing both sustained and articulated notes. Compare it with the source for intelligibility, target timbre, range, and timing. If the reference or settings fail, correct that specific issue before processing the full track.
5. Run conversion into a dedicated destination. Capture model/version settings and the actual output filename from the result or directory contents. Do not derive a supposed filename from source and target basenames alone.
6. Decode the output and measure its duration and onset offset. Correct a known constant model delay without changing the rhythm. Recheck chunk joins and any drift across the full song; investigate material drift before using time stretch.
7. Export a lossless vocal at the required editor sample rate. Keep the source and reference intact. Deliver the converted vocal separately from the accompaniment, then pass it to mixing if requested.

## Handoff

Return `audio_path` pointing to the verified converted file, source and target reference paths, sample rate, channels, measured duration, source-relative onset offset, and conversion settings. Carry the score/lyric alignment forward only after checking that conversion retained its timing.

The next mixer needs the converted vocal, original accompaniment, common start time, and any delay correction. The video editor needs the resulting audio duration and lyric or phrase timestamps measured against this converted stem.

## Verification

- Listen across the full performance, including transitions between model chunks. Compare difficult consonants, octave jumps, vibrato, long vowels, and the last phrase against the source.
- Compare voiced pitch contours when a pitch analyzer is available. Check for unintended octave shifts; exclude unvoiced intervals from pitch comparison.
- Confirm source lyrics remain intelligible and no reference lyrics leak into the conversion. Timbre similarity alone does not establish a successful cover.
- Check clipping, silence, sample rate, duration, and synchronization with accompaniment. State any remaining artifacts and any perceptual checks that were unavailable.
