---
name: video-mix-audio
description: Mix dialogue or narration with background music, choose the mix duration, and balance intelligibility before attaching audio to video.
metadata:
  source-role: Mixer
  source-path: environment/roles/mixer.py
  source-revision: f207987e3cffb554aaa6ffdbe733efb30f4b51ed
---

# Mix audio

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`.

## Inputs and result

Take foreground audio, music, desired output duration, offsets, and any loudness/delivery requirements. Return a new mixed audio file and the chosen timing, gain, loop/fade, and loudness settings. This step outputs audio; attaching it to video is a separate mux operation.

## Workflow

1. Inspect both sources. Reject empty or undecodable music before looping. Agree on the timeline: default to the foreground duration when the brief only asks for backing music, and report that choice. Retain a requested intro/outro explicitly.
2. Place tracks at their intended offsets. Loop or trim the music to that timeline, choose musically sensible seams, and fade the ends. Preserve deliberate pauses in speech.
3. Start with music below speech, then audition dense passages and quiet phrases. A fixed gain difference cannot guarantee intelligibility. Automate gain or use a supported sidechain compressor when a static balance masks words.
4. Render to a fresh path using an editor, FFmpeg, or an installed audio library. Leave headroom, measure the resulting peaks/loudness, and correct overload before delivery.

This FFmpeg example loops music under foreground audio at zero offset and ends with the foreground. `0.16` is a starting music gain, not a loudness guarantee:

```sh
ffmpeg -nostdin -n -i "voice.wav" -stream_loop -1 -i "music.wav" -filter_complex "[1:a:0]volume=0.16[bed];[0:a:0][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]" -map "[mix]" -c:a pcm_s24le "mixed.wav"
ffprobe -v error -show_streams -show_format -of json "mixed.wav"
ffmpeg -v error -i "mixed.wav" -f null -
```

Add fades, ducking, or lower gain as the actual sources require. Check available filter options with the installed FFmpeg help. If no mixing tool is available, provide the timing/gain plan and identify the missing capability.

## Completion

Verify intended duration, offsets, no clipped peaks, intelligible speech over the busiest music, smooth loop/fade boundaries, and appropriate final loudness. Listen on a speech-relevant playback path and check mono compatibility where required. Report measurements and any listening checks left unverified.
