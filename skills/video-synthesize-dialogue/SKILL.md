---
name: video-synthesize-dialogue
description: Synthesize a two-speaker dialogue or crosstalk script with consistent performer voices, explicit delivery cues, and per-turn audio metadata.
metadata:
  source-role: "CrossTalkSynth"
  source-path: "environment/roles/cross_talk/cross_talk_synth.py"
  source-revision: "f207987e3cffb554aaa6ffdbe733efb30f4b51ed"
---

# Synthesize comedy dialogue

For footage and renders use `uv run edittude media` (same as `python -m edittude_v3.media`): inventory, thumbs, plan, assemble, mix, grade, titles, captions (needs an ffmpeg with libass), reframe, finish, qc, frames, recut, proof. Do not call `media_inspect` or `media_render`. Other helpers if present: `speech_synthesize`.

Render dialogue turn by turn with each performer consistently mapped to the intended voice and delivery.

## Inputs

- Ordered turns with stable `id`, explicit `speaker`, `tone`, and spoken `text`.
- A speaker-to-voice mapping, language, and any reference audio with its accurate transcript. Carry forward existing voice authorization.
- Output directory, planned pauses, and any requested reaction assets.

For legacy text, parse `[Tone] Speaker: text` directly. Recognize a separately identified title; preserve the first actual spoken turn. The original tone vocabulary is `Natural`, `Confused`, and `Emphatic`.

## Workflow

1. Validate every turn against the declared speaker and tone mapping. Resolve missing voices or ambiguous speaker labels before synthesis; do not infer identities from similar filenames.
2. Inspect a suitable available TTS backend's language, voice, and style capabilities. Map tones to supported controls or appropriate references for that same speaker. Name any missing capability instead of inventing a command or pretending the requested delivery was produced.
3. Prepare references as the backend requires. When it needs prompt text, use the reference's actual words. Keep the two performers' reference assets distinct across every tone.
4. Synthesize only the spoken text, collecting all returned chunks for a turn. Save to that turn's stable ID and measure the decoded result. Listen for the right speaker, intended language, complete words, and useful emphasis.
5. Assemble turns in script order with deliberate response gaps. If an overlap is explicitly requested, record the overlapping event placement and mix it intentionally; ordinary concatenation cannot represent simultaneous speech.
6. If audience reactions were requested, append or mix the supplied assets at their specified positions and measure the result. A reaction marker in metadata alone does not mean the audio contains a reaction. Keep missing reaction assets explicitly unresolved.
7. Listen to the whole exchange for speaker swaps, unnatural gaps, clipping, and interrupted punchlines. Save individual turns, merged audio, and the measured assembly metadata to new paths.

## Output and handoff

Return `audio_path`, `seg_dir`, and a real `metadata_path`. Example turn record:

```json
{
  "id": "turn-02",
  "speaker": "partner",
  "tone": "Confused",
  "text": "By teaching it to you?",
  "audio_path": "turns/turn-02.wav",
  "speech_duration": 1.5,
  "pause_duration": 0.2,
  "duration": 1.7
}
```

State whether each file includes its pause or whether the pause is a separate assembly event. Relative paths resolve against the metadata file. Preserve upstream visual queries and scene IDs for timing and speaker-aware footage selection.

## Completion checks

- Every script ID maps to one verified audio result from the correct voice, with no omitted or duplicated turns.
- The merged audio duration agrees with the measured assembly, including pauses, reactions, and any explicit overlap.
- Listening verifies intelligible speech and consistent speaker assignment across tone changes. Report unresolved turns or cues before claiming completion.

## Source adaptation

The original used CosyVoice2 with speaker/tone reference pairs and a model to parse tags. It parsed reaction labels but did not insert reaction audio, and silently skipped failed turns. This skill makes parsing, missing outputs, and actual reaction rendering explicit.
