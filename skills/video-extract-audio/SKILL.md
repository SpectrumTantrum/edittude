---
name: video-extract-audio
description: Extract an audio track from a video or batch of videos for transcription, mixing, separation, or speech editing.
metadata:
  source-role: AudioExtractor
  source-path: environment/roles/audio_extractor.py
  source-revision: f207987e3cffb554aaa6ffdbe733efb30f4b51ed
---

# Extract audio

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

## Inputs and result

Take a video path or explicit list/directory, output directory, and optional audio stream and downstream format requirement. Return one record per source with `id`, `source_path`, `stream_index`, `audio_path`, `duration`, `sample_rate`, `channels`, and `status`. Use seconds. Record failed or silent sources with a reason instead of dropping them from the batch.

## Workflow

1. Enumerate the requested files, including all files if a directory was requested. Preserve relative directories or use unique IDs to avoid basename collisions. Choose a fresh output path for each file.
2. Inspect streams with ffprobe or the available editor's media inspector. Identify the intended language/track when multiple audio streams exist. A video with no audio is an explicit `no_audio` result.
3. Extract only the chosen audio stream. Preserve its sample rate and channels unless the next operation needs a conversion. Use PCM WAV for an editing intermediate. Stream copy is suitable when the original compressed track and a compatible output container are desired.
4. Check the output stream, duration, and decodability before adding its path to the result. Keep failed inputs in the report and continue independent files.

With FFmpeg available, this example extracts the first audio stream without changing its rate or channel count:

```sh
ffprobe -v error -show_streams -show_format -of json "input.mp4"
ffmpeg -nostdin -n -i "input.mp4" -map 0:a:0 -vn -c:a pcm_s16le "extracted.wav"
ffprobe -v error -show_streams -show_format -of json "extracted.wav"
ffmpeg -v error -i "extracted.wav" -f null -
```

Use the measured stream index, not necessarily the first stream in the example. Record the original audio start offset when it differs from video start, so later muxing can restore sync. If FFmpeg or equivalent extraction is unavailable, return that capability requirement and the inspected inputs.

## Completion

Every requested file has an output or explained failure. Outputs contain audio only, decode, and match their source track's duration within codec padding. Originals and existing outputs remain intact. Audition the beginning and end when playback is available; otherwise label listening as unverified.
