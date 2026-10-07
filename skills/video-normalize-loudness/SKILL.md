---
name: video-normalize-loudness
description: Measure and normalize audio loudness to an explicit LUFS and true-peak target for consistent dialogue, narration, or final video delivery.
metadata:
  source-role: LoudnessNormalizer
  source-path: environment/roles/loudness_normalizer.py
  source-revision: f207987e3cffb554aaa6ffdbe733efb30f4b51ed
---

# Normalize loudness

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

## Inputs and result

Take audio files, new output paths, and integrated loudness/true-peak targets from the delivery brief. For a draft without a specification, propose and record a working target such as -16 LUFS and -1.5 dBTP; this is not a platform requirement. Return each output path plus measured before/after integrated LUFS, true peak, duration, and the target used.

## Workflow

1. Inspect channels and sample rate. Extract audio first if given video. Keep originals and work in a per-job output directory.
2. Measure the whole program with an EBU R128 loudness meter or FFmpeg `loudnorm`. Peak normalization alone does not match perceived loudness. Silence or non-finite measurements need a reported skip, not extreme gain.
3. Apply measured two-pass normalization when FFmpeg is available. Pass one's `input_i`, `input_tp`, `input_lra`, `input_thresh`, and `target_offset` become pass two's measured values and offset. Choose dynamics processing only if constant gain would breach the peak ceiling; report that choice.
4. Preserve the requested output rate and channels. Normalize the final mix again only if mixing changed the delivered program level. A collection of independent programs can be measured separately; pieces of one continuous performance should retain intentional relative levels.
5. Measure the output again. A tool's exit code does not establish that the target was met.

First-pass example:

```sh
ffmpeg -nostdin -i "mix.wav" -map 0:a:0 -af "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json" -f null -
```

For pass two, bind these shell variables to the numeric values from that measurement and `output_rate` to the required Hz:

```sh
ffmpeg -nostdin -n -i "mix.wav" -map 0:a:0 -af "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=${input_i}:measured_TP=${input_tp}:measured_LRA=${input_lra}:measured_thresh=${input_thresh}:offset=${target_offset}:linear=true:print_format=json" -ar "$output_rate" -c:a pcm_s24le "normalized.wav"
```

Use one set of targets throughout both passes; the numbers above are a worked draft choice. If no measuring/processing tool is available, report that requirement without claiming normalization.

## Completion

Confirm loudness within the delivery tolerance, or a stated working tolerance such as 0.5 LU for a draft, and true peak at or below the chosen ceiling. Preserve duration and channel layout. Listen to quiet speech, loud sections, and transitions for pumping or distortion. Record any checks that could not be performed.
