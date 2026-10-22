#!/usr/bin/env python3
"""Run with an optional fresh output directory; requires installed ffmpeg/ffprobe."""
import hashlib
import array
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="videoagent-audio-smoke-"))
out.mkdir(parents=True, exist_ok=True)
commands = []


def run(args):
    commands.append(args)
    result = subprocess.run(args, text=True, capture_output=True, check=True)
    return result.stdout, result.stderr


def ff(*args):
    return run(["ffmpeg", "-hide_banner", "-nostdin", "-n", *map(str, args)])


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])[0])


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def meter(path):
    _, stderr = ff("-i", path, "-map", "0:a:0", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-")
    return json.loads(re.findall(r'\{\s*"input_i".*?\}', stderr, re.S)[-1])


source = out / "source.mov"
bed = out / "tone-bed.wav"
extracted = out / "extracted.wav"
model_input = out / "model-input.wav"
mixed = out / "mixed.wav"
normalized = out / "normalized.wav"
final = out / "final.mp4"

# Timecoded picture, with white flashes matching loud tone markers.
markers = "between(t,0.5,0.6)+between(t,2.5,2.6)+between(t,4.5,4.6)"
ff("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=5",
   "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=5",
   "-vf", f"drawbox=x=0:y=0:w=30:h=30:color=white:t=fill:enable='{markers}'",
   "-af", f"volume='if({markers},1,0.25)':eval=frame", "-ac", "2",
   "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
   "-c:a", "pcm_s16le", source)
ff("-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=2",
   "-ac", "2", "-c:a", "pcm_s16le", bed)
original_hashes = {str(p): digest(p) for p in (source, bed)}

ff("-i", source, "-map", "0:a:0", "-vn", "-c:a", "pcm_s16le", extracted)
ff("-i", extracted, "-map", "0:a:0", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", model_input)
ff("-i", extracted, "-stream_loop", "-1", "-i", bed,
   "-filter_complex", "[1:a:0]volume=0.16,afade=t=in:st=0:d=0.05,afade=t=out:st=4.8:d=0.2[bed];[0:a:0][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]",
   "-map", "[mix]", "-c:a", "pcm_s24le", mixed)
before = meter(mixed)
filter_text = ("loudnorm=I=-16:TP=-1.5:LRA=11:linear=true:print_format=json:"
               f"measured_I={before['input_i']}:measured_TP={before['input_tp']}:"
               f"measured_LRA={before['input_lra']}:measured_thresh={before['input_thresh']}:"
               f"offset={before['target_offset']}")
_, normalized_log = ff("-i", mixed, "-map", "0:a:0", "-af", filter_text,
                       "-ar", "48000", "-c:a", "pcm_s24le", normalized)
processing = json.loads(re.findall(r'\{\s*"input_i".*?\}', normalized_log, re.S)[-1])
picture_duration = float(next(s for s in probe(source)["streams"] if s["codec_type"] == "video")["duration"])
ff("-i", source, "-i", normalized, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
   "-af", "apad", "-c:a", "aac", "-b:a", "192k", "-t", picture_duration,
   "-movflags", "+faststart", final)

probes = {p.name: probe(p) for p in (source, bed, extracted, model_input, mixed, normalized, final)}
for path in (source, bed, extracted, model_input, mixed, normalized, final):
    ff("-v", "error", "-xerror", "-i", path, "-f", "null", "-")
after = meter(normalized)
delivered = meter(final)
audio = probes[model_input.name]["streams"][0]
assert audio["sample_rate"] == "16000" and audio["channels"] == 1
assert abs(float(audio["duration"]) - 5) <= 1 / 16000
for path in (extracted, mixed, normalized):
    assert abs(float(probes[path.name]["format"]["duration"]) - 5) <= 1 / 48000
for measurement in (after, delivered):
    assert math.isfinite(float(measurement["input_i"]))
    assert abs(float(measurement["input_i"]) + 16) <= 0.5
    assert float(measurement["input_tp"]) <= -1.5
final_video = next(s for s in probes[final.name]["streams"] if s["codec_type"] == "video")
assert abs(float(final_video["duration"]) - picture_duration) <= 1 / 30
assert final_video["nb_frames"] == "150"
assert original_hashes == {str(p): digest(p) for p in (source, bed)}

# Decoded picture hashes prove all original frames survive unchanged.
frame_hashes = {}
for path in (source, final):
    stdout, _ = ff("-v", "error", "-i", path, "-map", "0:v:0", "-f", "framemd5", "-")
    frame_hashes[path.name] = [line for line in stdout.splitlines() if line and not line.startswith("#")]
assert frame_hashes[source.name] == frame_hashes[final.name]
markers = {}
for path in (extracted, final):
    data = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0",
                           "-ar", "48000", "-ac", "1", "-f", "f32le", "-"],
                          check=True, capture_output=True).stdout
    samples = array.array("f", data)
    if sys.byteorder != "little":
        samples.byteswap()
    rms = [math.sqrt(sum(v*v for v in samples[i:i+480])/len(samples[i:i+480]))
           for i in range(0, len(samples), 480)]
    threshold = (max(rms) + min(rms)) / 2
    markers[path.name] = [i / 100 for i, value in enumerate(rms)
                          if value > threshold and (i == 0 or rms[i-1] <= threshold)]
assert len(markers[extracted.name]) == len(markers[final.name]) == 3
sync_errors = [b-a for a, b in zip(markers[extracted.name], markers[final.name])]
assert all(abs(error) <= 0.01 for error in sync_errors)
results = {
    "status": "passed", "output_directory": str(out),
    "original_sha256": original_hashes, "original_hashes_unchanged": True,
    "duration_seconds": 5.0, "model_input": {"sample_rate": 16000, "channels": 1},
    "mix": {"foreground": str(extracted), "bed": str(bed), "bed_gain": 0.16,
            "bed_loops_to_foreground_duration": True, "fade_in_seconds": 0.05, "fade_out_seconds": 0.2},
    "loudness_before": {"integrated_lufs": before["input_i"], "true_peak_dbtp": before["input_tp"]},
    "normalization_type": processing["normalization_type"],
    "loudness_after": {"integrated_lufs": after["input_i"], "true_peak_dbtp": after["input_tp"]},
    "loudness_delivered_aac": {"integrated_lufs": delivered["input_i"], "true_peak_dbtp": delivered["input_tp"]},
    "identical_decoded_picture_frames": 150,
    "all_outputs_decode": True, "listening": "unverified; synthetic tones, no human speech",
    "sync": {"method": "10 ms RMS marker onset comparison", "marker_onsets": markers,
             "source_relative_errors_seconds": sync_errors},
}
(out / "evidence.json").write_text(json.dumps({"probes": probes, "commands": commands,
    "loudness_before": before, "normalization_processing": processing,
    "loudness_after": after, "loudness_delivered_aac": delivered}, indent=2) + "\n")
(out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps({k: v for k, v in results.items() if k not in {"probes", "commands"}}, indent=2))
