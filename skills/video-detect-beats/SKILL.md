---
name: video-detect-beats
description: Measure music rhythm and propose timestamped edit cues with spacing and exclusion controls. Use to prepare beat or energy-based cuts before planning a montage.
metadata:
  source-role: "RhythmDetector"
  source-path: "environment/roles/vid_rhythm/rhythm_detector.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Detect rhythm cues

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `audio_timing`.

Measure candidate cut points from the audio, then distinguish detected musical events from the smaller set chosen for editing.

## Inputs and tools

- Music file, analysis range, desired pacing or minimum shot length, optional exclusion ranges, and output location.
- Use an available audio analyzer or installed librosa/SciPy with a decoder. `ffprobe` supplies duration and stream metadata. An editor's beat grid is usable when its source and offset are known.
- Report missing decoder or analyzer support explicitly. Without audio access, accept an existing verified beat grid or produce a pacing draft labeled unmeasured; do not invent detected beats.

## Workflow

1. Probe duration and sample rate, decode the requested range, and retain its source offset. Use a mono analysis copy if needed while preserving the original soundtrack.
2. Select a detector appropriate to the material. Beat tracking or onset detection can identify rhythmic events; smoothed RMS peaks identify energy accents. Call RMS results energy peaks, because sustained loudness and musical beats differ.
3. For RMS analysis, compute short-window energy, guard against empty/silent input before normalization, smooth only enough to suppress jitter, and pick separated peaks above a documented threshold. Convert sample or frame positions to seconds using the actual sample rate and hop size.
4. For beat tracking, inspect tempo ambiguity and missed or doubled beats. Retain detector output and method settings. Avoid forcing a constant tempo on rubato passages or treating low-confidence events as exact downbeats.
5. Choose edit cues from the measured candidates according to requested pacing. Prefer meaningful accents or phrase boundaries; several musical beats may belong to one shot. Apply only supplied or justified exclusions, and record why each excluded range exists.
6. Keep zero and the selected audio end as timeline boundaries, separate from detected events. A cue list can be empty for silence or a deliberate uninterrupted shot. Add no arbitrary early exclusion or fixed minimum shot length unrelated to the brief.
7. Save measured events, selected cut points, settings, and optional waveform/energy plot. Summarize interval statistics when at least two events exist; otherwise mark them unavailable.

## Output contract

All times are seconds relative to the soundtrack start; an analyzed subrange retains its source offset.

```json
{
  "audio_path": "music/theme.wav",
  "duration": 12.0,
  "method": "rms-peaks",
  "settings": {"sample_rate": 16000, "window_ms": 50, "threshold_ratio": 0.35, "minimum_interval": 1.5},
  "events": [{"id": "event-01", "time": 4.0, "kind": "energy_peak"}],
  "cut_points": [{"id": "cut-01", "time": 4.0, "event_id": "event-01"}],
  "boundaries": [0.0, 4.0, 12.0],
  "excluded_ranges": [],
  "review_status": "auditioned"
}
```

## Validation

- Read the saved file and check finite, sorted, unique event times in `[0, duration]`. Interior cut points fall strictly inside the chosen range; boundaries contain its exact start and end.
- Confirm selected cues obey the stated spacing and exclusions. Report any deliberate exception instead of silently changing settings.
- Audition the opening, a quiet section, a loud section, and the ending with cue markers. Check offset and tempo ambiguity against what is heard.
- Mark unreviewed output when audition is unavailable. Detector execution alone does not prove cuts feel synchronized.
