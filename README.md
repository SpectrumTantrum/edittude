# edittude

Video-editing agent. Model is DeepSeek Flash.

It inventories a footage folder, plans a cut, renders with ffmpeg, mixes voiceover, grades, titles, then QCs. You do not have to supply an EDL.

## Install

```bash
curl -LsSf https://raw.githubusercontent.com/SpectrumTantrum/edittude/main/install.sh | bash
```

That installs `uv` if needed, syncs the project, and puts `edittude` in `~/.local/bin`. From a checkout you can run `./install.sh` instead. Later, `edittude update` refreshes that same install. A checkout that already lives in `~/.local/share/edittude-v3` stays there. New installs clone to `~/.local/share/edittude`.

This path does not download the neural models. Sizes below are decimal (1 MB = 1,000,000 bytes), taken from `uv.lock`, the wheels `uv` resolves, and the pinned weight files. A first install that still needs `uv` and CPython downloads 85.246 MB on Linux x86_64 (4.369 MB shallow clone, 16.739 MB `uv`, 35.083 MB CPython 3.13, 29.055 MB of locked wheels) and 66.147 MB on macOS arm64 (4.369 MB clone, 14.280 MB `uv`, 25.258 MB CPython 3.13, 22.240 MB of wheels). An install that already has `uv` and Python downloads only the clone and the wheels.

ffmpeg and ffprobe must be on PATH. On a Mac: `brew install ffmpeg`.

First launch asks for a DeepSeek API key and writes it to `~/.config/edittude/.env`. If `~/.config/edittude-v3/.env` already exists, it is copied once and left in place. Get a key from [https://platform.deepseek.com](https://platform.deepseek.com). The app reads the new file, and `DEEPSEEK_API_KEY` if it is already in the environment. After that copy, the new file is the one to edit.

## CLI

```bash
edittude
edittude ask "make a cut from /path/to/footage"
edittude skills
edittude media --help
edittude update
edittude -C /path/to/project
```

`edittude-v3` is the same program, kept so older installs keep working.

`edittude update` pulls the latest checkout into the current install, then re-syncs. Use `--force` if that checkout has local edits you want overwritten.

`edittude` with no args opens a session in the current directory. Transcript stays in normal terminal scrollback. The composer sits at the bottom. Session history for a new project is `.edittude/`. A project that already has `.edittude-v3/` keeps using that folder.

From a checkout without the installer:

```bash
uv sync
uv run edittude
```



## Media tools

These are what the agent should run instead of inventing ffmpeg filters:

```bash
edittude media inventory FOLDER --out inventory.json
edittude media plan inventory.json --out edl.json --title "A DAY OUT"
edittude media assemble edl.json --out picture.mp4
edittude media finish picture.mp4 edl.json --out final.mp4
edittude media qc final.mp4 --out qc.json
edittude media proof FOLDER --out /path/to/artifacts
```

None of these overwrite an existing output. Rerunning one onto the same file needs `--force`, before or after the subcommand: `edittude media --force assemble edl.json --out picture.mp4`.

Write large renders next to the footage, not into this repo.

## Neural models (opt-in)

Transcription, stem separation, voice conversion and singing synthesis need extra runtimes and weights. Nothing is downloaded unless you ask:

```bash
./install.sh --with-models                          # or --with-models=asr,separation
edittude-media models install                       # same thing, after the fact
edittude-media models install --models seed-vc,diffsinger
edittude-media models install --check               # status only, no network
```

`--with-models` and `edittude-media models install` install `asr` and `separation` only. `seed-vc` and `diffsinger` stay out of that list until you name them. Either way the installer creates a separate `.venv-models` (Python 3.11) beside the install and puts weights in `models/`. The agent's own virtualenv is untouched. Override locations with `EDITTUDE_MODELS_DIR`, `EDITTUDE_MODEL_PYTHON`, or the per-backend `EDITTUDE_*` variables.

The shared runtime is PyPI `torch==2.8.0` and `torchaudio==2.8.0` (`torch>=2.6,<2.9`). On Linux x86_64 the torch wheel is 888.1 MB and it pulls the CUDA 12 libraries, so the shared packages are 3.946 GB before any weights. On macOS arm64 the same pins are 106.5 MB and do not include CUDA. CPython 3.11, downloaded only when it is missing, is 30.8 MB on Linux x86_64 and 27.0 MB on macOS arm64.

Default opt-in (`asr` and `separation`), including that runtime, its extra Python packages, the weights, and CPython 3.11 when it is missing:

| platform | Python packages | weights | CPython 3.11 if missing | total |
| --- | ---: | ---: | ---: | ---: |
| Linux x86_64 | 4.069 GB | 232.0 MB | 30.8 MB | 4.332 GB |
| macOS arm64 | 136.9 MB | 232.0 MB | 27.0 MB | 395.9 MB |

Weights are the same on every platform. The two explicit backends also clone upstream source.

| backend | tool | download | when |
| --- | --- | --- | --- |
| `asr` | `speech_transcribe` | 147.9 MB of weights | default opt-in (`--with-models`) |
| `separation` | `audio_separate` | 84.1 MB of weights | default opt-in (`--with-models`) |
| `seed-vc` | `voice_convert` | 2.486 GB of weights, a 69.5 MB git clone, and 174.0 MB (Linux) or 143.5 MB (macOS) of Python packages beyond the shared runtime | only when named |
| `diffsinger` | `singing_synthesize` | 461.0 MB of weights, a 66.5 MB git clone, and 156.2 MB (Linux) or 114.6 MB (macOS) of Python packages beyond the shared runtime | only when named; Mandarin only |

`seed-vc` and `diffsinger` stay out of the default list because they are large and carry terms of their own:

- **Seed-VC is GPL-3.0.** The installer clones it from upstream at a pinned commit into `models/seed-vc` and applies `tools/patches/seed-vc.patch`. Your use of `voice_convert` is subject to the GPL.
- The `0228_opencpop_ds100_rel` checkpoint is trained on Opencpop (CC BY-NC-ND 4.0) and is non-commercial only. The installer prints this when you install `diffsinger`. `singing_synthesize` sings Mandarin and nothing else.

The singing feature (`singing_synthesize`) is for non-commercial use only.

`voice_convert` also downloads `rmvpe.pt` (181.2 MB, included in the seed-vc weight total above). Its license file states research use only.

Those two backends are fetched only when you name them, and they are never committed. Everything runs offline afterwards.

## License

Edittude's own code is MIT. Optional singing (DiffSinger, non-commercial) and voice conversion (Seed-VC, GPL-3.0, plus research-only `rmvpe.pt`) keep their own licenses. See `THIRD_PARTY_LICENSES`.

The patches in `tools/patches/` (`DiffSinger.patch`, `seed-vc.patch`) modify third-party code and are under the upstream project's license, not Edittude's MIT grant.

## Keys

```
enter                 send
alt+enter / ctrl+j    newline
/                     slash commands
@                     mention a file
esc                   interrupt the current turn
ctrl+c                interrupt
ctrl+d                quit
↑ / ↓                 history
```



## Slash commands

```
/help     commands and keys
/new      fresh thread
/skills   list skill folders
/status   model, thread, workspace
/clear    clear the transcript
/quit     exit
```



## Skills

Each skill is a folder with a `SKILL.md`:

```
skills/
  footage-inventory/
    SKILL.md
```

The agent loads the install `skills/` plus `./skills/` in the current directory. Drop more folders in.

## Credit

Thanks to [Deep Agents](https://github.com/langchain-ai/deepagents) for the harness, and to [HKU Data Science](https://github.com/HKUDS) for [VideoAgent](https://github.com/HKUDS/VideoAgent), the voice agents project that inspired this one.

tools/ and skills/ are inspired by HKU Data Intelligence Lab's VideoAgent; no HKU code is included.
