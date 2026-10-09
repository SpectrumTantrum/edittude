# Video editing skills, inspired by HKU VideoAgent

33 portable skills, one for each role in the original HKUDS VideoAgent registry. Each folder contains a self-contained `SKILL.md` with a selection description, inputs, an editing workflow, output contracts, and completion checks.

These are instructions for an agent. The sibling tools folder supplies callable media operations; the skills themselves do not install models. A tool-capable agent can use its existing editor, FFmpeg, speech tools, and file tools to follow them. The sibling [tools folder](../tools/README.md) contains executable operations, dependency discovery, and runnable checks.

## Use the pack

Copy this `skills/` folder and its sibling `tools/` folder into any repository, keeping them next to each other. No Edittude installation, original checkout, bundled model directory, or absolute developer path is required. Existing destination folders can receive these files by an explicit merge after checking for name conflicts.

Point a skill-compatible host at the skill folders, or copy individual skill folders into that host's configured skill directory. Automatic discovery depends on the host. An agent without a skill loader can read the selected `SKILL.md` directly.

For example, give an agent the following request together with the repository path:

> Use `video-index-footage`, `video-write-commentary`, `video-narrate-scenes`, `video-find-shots`, and `video-assemble-edit` from the copied `skills/` folder. Make a 45-second explanation from the supplied footage and notes. Keep source claims grounded, preserve originals, and return the video plus its edit decisions and verification results. Report missing rendering or speech capabilities before promising an output.

Load only the skills needed for the edit. A simple trim needs neither a narration model nor a retrieval database. Writing and editorial judgment belong to the calling agent; tools inspect, transform, synthesize, render, and measure media.

## What the original repository contains

The analysis used the local `VideoAgent` checkout at commit `f207987e3cffb554aaa6ffdbe733efb30f4b51ed`. Its [registry](https://github.com/HKUDS/VideoAgent/blob/f207987e3cffb554aaa6ffdbe733efb30f4b51ed/environment/config/registry.json) contains exactly 33 role classes. The role, registry, and coordinator files matched that commit; unrelated local configuration changes were left alone.

The [base class](https://github.com/HKUDS/VideoAgent/blob/f207987e3cffb554aaa6ffdbe733efb30f4b51ed/environment/agents/base.py) describes tools with input/output schemas and an `execute` method. A [central coordinator](https://github.com/HKUDS/VideoAgent/blob/f207987e3cffb554aaa6ffdbe733efb30f4b51ed/environment/agents/multi.py#L287) chooses and runs them sequentially. These are not 33 independent agents deciding how to collaborate. An AST scan found direct named chat-model calls in 13 role files; VideoPreloader additionally reaches model-generated captions through VideoRAG. Other roles run speech/embedding models or ordinary media operations.

That distinction makes the conversion useful. The skills preserve the responsibilities and editorial knowledge, while the calling agent owns planning and review. The pack does not reproduce the original graph planner or mandate its model providers.

Some implementation choices would produce misleading or fragile skills if copied literally:

| Original behavior, verified in local source | Change in the skills |
| --- | --- |
| Loudness, resampling, and separation wrappers process the input directory with overwrite enabled; Merge sets its output to its input video path. | Distinct output paths, explicit per-file results, immutable sources. |
| VoiceGenerator ignores the supplied scene path and uses a fixed reference transcript. | Read the actual script and require the selected reference's own transcript. |
| Retrieval flattens away scenes with no match; the editor cycles candidate positions and skips unusable clips. | Join by scene ID, retain unmatched scenes, resolve gaps before rendering. |
| The editor removes the first description line and treats a sampled-frame index as elapsed seconds. | Preserve full descriptions and use actual source timestamps. |
| Rhythm detection uses smoothed RMS peaks, with fixed spacing and an initial exclusion window. | Distinguish energy cues from musical beats; expose evidence and deliberate cut choices. |
| Speech/comedy paths align positional lines, may skip failed units, and rely on fixed output files. | Stable utterance IDs, measured timing, complete coverage, explicit artifact manifests. |
| Singing paths assume lyric character counts match notes; tempo conversion is wrong after a tempo change. Original synthesis also passes an unsupported keyword to DiffSinger. | Explicit lyric/rest units, selected melody track, tempo-aware timing, and verified backend input/output. |
| Some content workflows truncate source evidence, choose one transcript, or substitute text when generation fails. | Account for the supplied evidence, label coverage limits and failures, preserve factual traceability. |

Evidence is in the original role files named in each skill's provenance metadata, plus the original repository's `tools/videorag/_opcontent.py`, `tools/videorag/_videoutil/split.py`, and `tools/DiffSinger/diff.py`. Those paths identify historical sources, not required files in the destination repository. The Edittude fork has already changed some of those implementations; the [tool reference](../tools/README.md) describes the portable implementations and their optional backends.

## The 33 conversions

The source hashes and exact mapping are in [manifest.json](manifest.json). Names describe the action an agent should select, rather than preserving ambiguous class names such as `VideoConversion`.

| Original role | Portable skill | Main result |
| --- | --- | --- |
| LoudnessNormalizer | [video-normalize-loudness](video-normalize-loudness/SKILL.md) | Measured loudness-normalized audio |
| Resampler | [video-resample-audio](video-resample-audio/SKILL.md) | Audio at a required rate/layout |
| Separator | [video-separate-stems](video-separate-stems/SKILL.md) | Checked vocal/accompaniment stems |
| Transcriber | [video-transcribe-audio](video-transcribe-audio/SKILL.md) | Source-linked transcript and timing |
| Mixer | [video-mix-audio](video-mix-audio/SKILL.md) | Balanced foreground/music mix |
| Merge | [video-mux-audio](video-mux-audio/SKILL.md) | Existing picture with its final soundtrack |
| AudioExtractor | [video-extract-audio](video-extract-audio/SKILL.md) | Extracted audio and stream provenance |
| VoiceGenerator | [video-narrate-scenes](video-narrate-scenes/SKILL.md) | Narration and measured scene timings |
| VideoEditor | [video-assemble-edit](video-assemble-edit/SKILL.md) | Rendered edit and decision list |
| VideoPreloader | [video-index-footage](video-index-footage/SKILL.md) | Searchable source scene records |
| VideoSearcher | [video-find-shots](video-find-shots/SKILL.md) | Candidate shots per scene ID |
| VideoConversion | [video-storyboard-timed-audio](video-storyboard-timed-audio/SKILL.md) | Visual queries preserving audio timing |
| TTSWriter | [video-write-speech-patches](video-write-speech-patches/SKILL.md) | Replacement text by source interval |
| TTSSlicer | [video-slice-speech-reference](video-slice-speech-reference/SKILL.md) | Voice reference clips and offset mapping |
| TTSInfer | [video-synthesize-speech-patches](video-synthesize-speech-patches/SKILL.md) | Replacement utterances with durations |
| TTSReplace | [video-replace-speech](video-replace-speech/SKILL.md) | Dialogue replacement preserving the edit |
| SVCAdapter | [video-adapt-lyrics](video-adapt-lyrics/SKILL.md) | Lyrics fitted to musical units |
| SVCAnalyzer | [video-transcribe-melody](video-transcribe-melody/SKILL.md) | Selected melody, lyric units, notes, rests |
| SVCSingle | [video-synthesize-singing](video-synthesize-singing/SKILL.md) | Singing rendered from timed notes/lyrics |
| SVCCoverist | [video-convert-singing-voice](video-convert-singing-voice/SKILL.md) | Singing with the selected voice timbre |
| SVCConversion | [video-time-lyrics](video-time-lyrics/SKILL.md) | Lyric phrases and instrumental intervals |
| StandUpAdapter | [video-adapt-standup](video-adapt-standup/SKILL.md) | Performable stand-up script |
| StandUpSynth | [video-synthesize-standup](video-synthesize-standup/SKILL.md) | Stand-up audio and utterance metadata |
| StandUpConversion | [video-time-standup](video-time-standup/SKILL.md) | Grouped comedy timing for edits |
| CrossTalkAdapter | [video-adapt-dialogue](video-adapt-dialogue/SKILL.md) | Two-speaker comic dialogue |
| CrossTalkSynth | [video-synthesize-dialogue](video-synthesize-dialogue/SKILL.md) | Speaker-assigned dialogue audio |
| CrossTalkConversion | [video-time-dialogue](video-time-dialogue/SKILL.md) | Speaker turns and edit intervals |
| RhythmDetector | [video-detect-beats](video-detect-beats/SKILL.md) | Measured rhythm or energy cues |
| RhythmContentGenerator | [video-plan-beat-montage](video-plan-beat-montage/SKILL.md) | Storyboard paced to selected cues |
| CommentaryContentGenerator | [video-write-commentary](video-write-commentary/SKILL.md) | Grounded narration and visual intentions |
| NewsContentGenerator | [video-write-news](video-write-news/SKILL.md) | Attributed news narration and visuals |
| VideoContentQA | [video-answer-questions](video-answer-questions/SKILL.md) | Evidence-linked answers about the sources |
| VideoSummarizationGenerator | [video-summarize](video-summarize/SKILL.md) | Source-grounded summary with coverage limits |

## Compose an edit

| Request | Useful sequence |
| --- | --- |
| Commentary or news video | Index footage; write commentary/news; narrate scenes; join measured narration timing to the script by ID; find shots; assemble; mix/normalize the soundtrack and mux if needed. |
| Beat montage | Detect cues; plan the montage; index and find shots; assemble to the selected cue boundaries. |
| Fix selected spoken words | Extract audio; slice reference speech; transcribe with slice offsets; write patches; synthesize patches; replace the chosen intervals; verify sync. |
| Song adaptation | Transcribe melody from MIDI; adapt lyrics; synthesize singing; optionally convert voice; mix accompaniment; time lyrics against final audio; storyboard; find shots; assemble. |
| Stand-up or two-speaker comedy | Adapt script; synthesize utterances; time stand-up/dialogue; storyboard timed audio; find shots and assemble if a video is required. |
| Answer questions or summarize | Transcribe and inspect the relevant evidence, then answer/summarize. Rendering is unnecessary. |

Skills use explicit artifact paths, stable IDs, and seconds. Each timing field states whether it is source-relative or output-relative. Preserve parent IDs when grouping lyrics or utterances; translate legacy field names once at the handoff. A measured timing file and a written script must be joined by identity, not zipped by position.

Quality comes from checks that change editorial decisions: a shot must support the narration, speech must fit its interval and remain intelligible, music cuts must match the selected cues, and the final export must cover the intended timeline. A successful model request or an existing file is not enough.

## Validation

From the parent of the copied `skills/` and `tools/` folders, run the pack check with Python 3.9 or later and PyYAML available:

```sh
python -m pip install -r tools/requirements.txt
python tools/validate.py
```

The validator locates `skills/` relative to its own file, so it also runs from another working directory. Pass `--skills-dir PATH` if the folders are no longer siblings. Optional `--source PATH_TO_ORIGINAL_VIDEOAGENT` additionally checks all 33 mappings against the original registry, class declarations, and recorded source hashes without importing model code. Normal validation does not need that repository. Source drift fails the optional provenance check rather than silently updating it. The bundled skill-creator validator also passed for all 33 skills, and every JSON example parsed.

With FFmpeg and ffprobe installed, reproduce the media smoke check using the Python standard library:

```sh
python tools/smoke_media.py
```

It creates a fresh temporary directory and reports the artifacts, measurements, and assertions in `results.json` and `evidence.json`. It does not call a model or require user media.

Portability was checked by copying only `skills/` and `tools/` into a clean destination and running both checks from an unrelated working directory, with spaces in the paths and no `PYTHONPATH`. All 33 skills validated and the media smoke test passed on macOS. This checks repository independence, not Windows or Linux execution.

An independent agent followed the extraction, resampling, mixing, loudness, and mux skills on synthetic local media. It produced a five-second H.264/AAC video with unchanged picture frames, a 16 kHz mono model input, and a final measurement of -15.96 LUFS / -5.78 dBTP. Source hashes remained unchanged. Cached offline ASR also processed the tone fixture and returned no speech. This validates those media operations and no-speech handling, not real transcription accuracy, the aesthetic quality of an edit, or unrun synthesis/separation models. Listening was not verified.

The edittude harness discovers these 33 skills alongside any existing project skills and registers the eleven callables from the sibling tools folder. Optional model configuration and supported features are reported by get_capabilities; registered does not mean every backend is installed.
