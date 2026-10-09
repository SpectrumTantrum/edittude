# edittude

Video-editing agent. Model is DeepSeek Flash.

It inventories a footage folder, plans a cut, renders with ffmpeg, mixes voiceover, grades, titles, then QCs. You do not have to supply an EDL.

## Install

```bash
curl -LsSf https://raw.githubusercontent.com/SpectrumTantrum/edittude/main/install.sh | bash
```

That installs `uv` if needed, syncs the project, and puts `edittude` in `~/.local/bin`. From a checkout you can run `./install.sh` instead. Later, `edittude update` refreshes that same install. A checkout that already lives in `~/.local/share/edittude-v3` stays there. New installs clone to `~/.local/share/edittude`.

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

That creates a separate `.venv-models` (Python 3.11, torch) beside the install and puts weights in `models/`; the agent's own virtualenv is untouched. Budget about 2.5 GB for the torch runtime plus the weights for whichever backends you pick. Override locations with `EDITTUDE_MODELS_DIR`, `EDITTUDE_MODEL_PYTHON`, or the per-backend `EDITTUDE_*` variables.


| backend      | tool                 | weights      | notes                          |
| ------------ | -------------------- | ------------ | ------------------------------ |
| `asr`        | `speech_transcribe`  | ~0.15 GB     | default                        |
| `separation` | `audio_separate`     | ~0.1-0.35 GB | default                        |
| `seed-vc`    | `voice_convert`      | ~2.5 GB      | explicit opt-in                |
| `diffsinger` | `singing_synthesize` | ~0.5 GB      | explicit opt-in, Mandarin only |


`seed-vc` and `diffsinger` stay out of the default list because they are large and carry terms of their own:

- **Seed-VC is GPL-3.0.** The installer clones it from upstream at a pinned commit into `models/seed-vc` and applies `tools/patches/seed-vc.patch`. Your use of `voice_convert` is subject to the GPL.
- The `0228_opencpop_ds100_rel` checkpoint is trained on Opencpop (CC BY-NC-ND 4.0) and is non-commercial only. The installer prints this when you install `diffsinger`. `singing_synthesize` sings Mandarin and nothing else.

The singing feature (`singing_synthesize`) is for non-commercial use only.

`voice_convert` also downloads `rmvpe.pt`, whose license file states research use only.

Both are fetched at install time and never committed. Everything runs offline afterwards.

## License

Edittude's own code is MIT. Optional singing (DiffSinger, non-commercial) and voice conversion (Seed-VC, GPL-3.0, plus research-only `rmvpe.pt`) keep their own licenses. See `THIRD_PARTY_LICENSES`.

The patches in `tools/patches/` (`DiffSinger.patch`, `seed-vc.patch`) modify third-party code and are under the upstream project's license, not MIT.

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
