---
name: video-resample-audio
description: Convert audio sample rate or channel layout to a video delivery or speech-model requirement while preserving duration and pitch.
metadata:
  source-role: Resampler
  source-path: environment/roles/resampler.py
  source-revision: f207987e3cffb554aaa6ffdbe733efb30f4b51ed
---

# Resample audio

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

## Inputs and result

Take audio files or a directory, a required sample rate in Hz, optional channel layout, and a new output directory. Obtain the target from the next model or delivery specification. Return `id`, `source_path`, `audio_path`, source and output sample rates/channel layouts, measured `duration` in seconds, and per-file failures.

## Workflow

1. Inspect each source's rate, channels, and duration. Extract an audio track first when the input is video. Keep the source immutable.
2. Keep files that already satisfy the requirement as explicit reused inputs. Resampling upward cannot recover missing frequencies. Convert once at the boundary that needs it.
3. Use a supported resampler in FFmpeg, the editor, or an installed audio library. Preserve pitch and elapsed time; changing the declared sample rate alone changes playback speed. Preserve stereo unless mono is required. Audition a mono fold-down for cancellation before accepting it.
4. Write unique output names and inspect the result. List every requested input, including failures.

Example for a model that explicitly requires 16 kHz mono:

```sh
ffprobe -v error -show_streams -show_format -of json "source.wav"
ffmpeg -nostdin -n -i "source.wav" -map 0:a:0 -ar 16000 -ac 1 -c:a pcm_s16le "model-input.wav"
ffprobe -v error -show_streams -show_format -of json "model-input.wav"
ffmpeg -v error -i "model-input.wav" -f null -
```

For a video mix, derive a different rate/layout from the project settings. An installed resampler is required to produce media; report the missing capability if none is available.

## Completion

Verify the exact target sample rate and channel count, successful decoding, and unchanged duration within one input/output sample interval for PCM, or explained codec padding for compressed sources. Listen for altered pitch, speed, channel loss, or clipping. Report listening as unverified when playback is unavailable.
