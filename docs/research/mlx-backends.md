# Apple-Silicon-native (MLX) options for the edittude model backends

Research date: **2026-09-20**. Every version/date/existence claim below was read off a page
fetched on that date; anything not fetched is marked **UNVERIFIED**. Contract details come from
`tools/models.py` and `tools/install_models.py` at the current checkout.

Headline: **four of the five backends should stay on their current runtime.** The only
unambiguous win is replacing `say`/`espeak-ng` with MLX Kokoro. The only real MLX contender for
an existing backend is `demucs-mlx`, and it is not yet worth a second inference implementation.

---

## 1. Per-backend recommendation

| Backend (tool) | Current | Recommended **darwin-arm64** | Recommended **linux-cuda** | Recommended **linux-cpu** | Confidence | Why |
|---|---|---|---|---|---|---|
| `asr` (`speech_transcribe`) | faster-whisper / CTranslate2, `device='cpu'`, `int8` | **Keep faster-whisper CPU int8.** `mlx-whisper` as opt-in `EDITTUDE_ASR_BACKEND=mlx` | faster-whisper, `device='cuda'`, `compute_type='float16'` | faster-whisper CPU int8 (unchanged) | **Medium-high** | `mlx-whisper` meets the word-timestamp + language contract but has **no VAD** (contract uses `vad_filter=True`), is 13 months without a release, declares a phantom `torch` dep, and needs `numba` for the DTW. No same-machine M-series benchmark vs `base`+int8 exists anywhere. |
| `separation` (`audio_separate`) | demucs 4.1 torch, `--device mps/cuda/cpu` | **Keep demucs torch on MPS.** `demucs-mlx` as opt-in | demucs torch `--device cuda` | demucs torch `--device cpu` | **Medium** | `demucs-mlx` is real, maintained, torch-free and ~2.6× faster than MPS — but 41 stars, one self-reported benchmark, no `--two-stems`, and it hard-pins `mlx==0.31.2`. MPS is already ~7–8× CPU and is the *same code and weights* as Linux. |
| `seed-vc` (`voice_convert`) | Seed-VC torch (GPL-3.0 clone) | **Seed-VC torch on MPS — already works, zero code change** | Seed-VC torch CUDA | Seed-VC torch CPU (~300× RTF, effectively unusable) | **High** | **No MLX port of Seed-VC exists.** Upstream PR #138 added MPS auto-detect and is *already inside our pinned sha*. |
| `diffsinger` (`singing_synthesize`) | DiffSinger torch, falls to CPU on Mac | **DiffSinger torch on MPS** — one-line `device=` patch + `PYTORCH_ENABLE_MPS_FALLBACK=1` | DiffSinger torch CUDA | DiffSinger torch CPU | **Medium** | **Zero MLX singing-synthesis projects exist** (GitHub search `total_count: 0`). `BaseSVSInfer` already takes a `device` arg; the hardcoded `.cuda()` calls are all on the training path. Untested on MPS by anyone — needs a spike. |
| — (`speech_synthesize`) | macOS `say` / `espeak-ng`, refuses reference voices | **`mlx-audio` + `mlx-community/Kokoro-82M-bf16`** | `kokoro-onnx[gpu]` | `kokoro-onnx` | **Medium-high** | Genuine upgrade: MIT code, Apache-2.0 weights, **no torch**, CLI with `--voice` (54 presets) and a `speed` knob that maps to the existing `rate` parameter. Same Kokoro weights on both platforms. |

---

## 2. Does MLX-on-Linux collapse the platform split? **No.**

`mlx` 0.32.2 (uploaded 2026-08-25, MIT, `requires_python >=3.10`) ships
`manylinux_2_35_x86_64` / `manylinux_2_35_aarch64` / `win_amd64` wheels alongside
`macosx_{14,15,26}_0_arm64`, and its `requires_dist` is explicit
(<https://pypi.org/pypi/mlx/json>):

```
mlx-metal==0.32.2 ; platform_system == "Darwin"
mlx-cuda-12==0.32.2 ; platform_system == "Linux" and extra == "cuda"
mlx-cuda-13==0.32.2 ; platform_system == "Linux" and extra == "cuda13"
mlx-cpu==0.32.2    ; platform_system == "Linux" and extra == "cpu"
```

The README confirms `pip install mlx[cuda]` / `mlx[cpu]` with no maturity caveat
(<https://raw.githubusercontent.com/ml-explore/mlx/main/README.md>). Note macOS 13 wheels are
gone — **minimum macOS 14**.

But the *ports* have not followed, verified from their own docs:

- **mlx-whisper** — PyPI summary is "OpenAI Whisper on Apple silicon with MLX"; README mentions
  only Homebrew/macOS. Zero Linux or CUDA mentions.
  (<https://raw.githubusercontent.com/ml-explore/mlx-examples/main/whisper/README.md>)
- **parakeet-mlx** — repo description: "…for Apple Silicon using MLX". No Linux claim.
  (<https://github.com/senstella/parakeet-mlx>)
- **mlx-audio** — README states the requirement "Apple Silicon Mac (M1/M2/M3/M4)".
  (<https://raw.githubusercontent.com/Blaizzy/mlx-audio/main/README.md>)
- **demucs-mlx** — decisive: its dependency `mlx-audio-io` 1.3.11 declares
  `mlx[cpu]==0.31.2 ; platform_system == "Linux"` (<https://pypi.org/pypi/mlx-audio-io/json>).
  On Linux the MLX stack installs the **CPU-only** backend. It would run, and it would be slower
  than torch+CUDA.

**Conclusion:** MLX-on-Linux is a core-framework capability that no audio port has adopted. A
single MLX backend per tool across darwin-arm64 and linux-cuda is not viable in 2026-09. Plan a
platform split, or — better — keep one torch path everywhere and treat MLX as opt-in acceleration.

---

## 3. Per-candidate notes

### 3.1 ASR

**mlx-whisper — contract-complete, semi-stale. The only MLX ASR that fits.**
- Repo <https://github.com/ml-explore/mlx-examples> (whisper still lives here, *not* moved to
  mlx-audio). 8,955 stars, MIT, not archived, repo `pushed_at` **2026-04-06**; the `whisper/`
  path's last commit is **2025-12-15**.
- PyPI `mlx-whisper` **0.4.3, 2025-08-29**, MIT, `requires_python >=3.8`, wheel `py3-none-any`.
  ~13 months since a release, and the Dec-2025 safetensors-loader commit is **unreleased**.
- Contract, read from source
  (<https://raw.githubusercontent.com/ml-explore/mlx-examples/main/whisper/mlx_whisper/transcribe.py>,
  `timing.py`):
  - segments: `{id, seek, start, end, text, tokens, temperature, avg_logprob, compression_ratio, no_speech_prob}` — **OK**
  - words: `timing.py` `WordTiming` has a `probability: float` field; emitted as
    `dict(word=…, start=…, end=…, probability=…)` — **OK**, but the key is `word`, not `text`
  - language auto-detect returned as top-level `language` — **OK**
  - **VAD: absent.** Only `no_speech_threshold=0.6` + `logprob_threshold`. This is the one hard
    contract gap vs `vad_filter=True`.
  - long-form: 30 s sliding window + `clip_timestamps` + `hallucination_silence_threshold` — OK
  - offline: `path_or_hf_repo` accepts a local dir — OK
- Install footprint: `requirements.txt` lists **`torch`**, but torch is never imported by any
  module (`transcribe/timing/decoding/audio/load_models/whisper.py`). Install with `--no-deps`
  to avoid ~2.5 GB. **`numba` is required and imported** (`@numba.jit` DTW) — word timestamps do
  not work without it, and it adds a first-call JIT warmup. `scipy` imported. `audio.py` shells
  out to `ffmpeg`.
- MLX weights: `mlx-community/whisper-base-mlx` **143.7 MB** (`weights.npz`),
  `whisper-base-mlx-q4` 80.5 MB, `whisper-small-mlx` 481.3 MB,
  `whisper-large-v3-turbo` 1614 MB / `-8bit` 863.7 MB / `-4bit` 463.5 MB.
  Format split: older repos ship `weights.npz`, newer ones `model.safetensors` — pinned 0.4.3
  may not read the newer 4/8-bit turbo repos.
- **Missing decisive fact:** no primary source publishes an M-series benchmark of
  `mlx-whisper base` vs `faster-whisper base int8 cpu_threads=4`. **UNVERIFIED.** That one
  20-minute experiment settles the whole question.

**parakeet-mlx — cleanest install, wrong shape.**
- <https://github.com/senstella/parakeet-mlx>, 982 stars, Apache-2.0, pushed **2026-08-29**.
- PyPI **0.5.2, 2026-06-05**, `requires_python >=3.10`. Deps: `dacite, huggingface-hub, librosa,
  mlx>=0.22.1, numpy>=2.2.5, typer` — **no torch, no numba**.
- Real long-form chunking (`--chunk-duration` 120 s, `--overlap-duration` 15 s).
- **Disqualifiers:** no language detection (breaks `info.language`), no VAD, per-token
  probability not found in `AlignedToken(text, start, end, duration)` (**UNVERIFIED** whether one
  is exposed), and weights are `mlx-community/parakeet-tdt-0.6b-v3` at **2508 MB, cc-by-4.0** vs
  our 150 MB default.

**lightning-whisper-mlx — dead. Disqualified.**
<https://github.com/mustafaaljadery/lightning-whisper-mlx>, 958 stars, `pushed_at` **2024-05-08**,
**no license**, PyPI 0.0.10 (2024-04-02) pinning `tiktoken==0.3.3`. The "10× faster than
whisper.cpp" README claim is **UNVERIFIED** (no methodology).

**mlx-audio (STT side) — the only MLX stack with real Silero VAD.**
7,914 stars, MIT, pushed **2026-09-18**; PyPI **0.5.4, 2026-09-14**. STT models: Whisper,
Distil-Whisper, Qwen3-ASR, Parakeet, VibeVoice-ASR, Voxtral, Qwen2-Audio. Ships
`mlx-community/silero-vad` and a Qwen3-ForcedAligner for word-level alignment. Risk: 0.x with 6
releases in 5 weeks, 107 open issues, and `transformers>=5.14.0` is a heavy, very new pin.
Whether its Whisper path exposes per-word `probability` is **UNVERIFIED**.

**Non-MLX comparators.**
- **pywhispercpp / whisper.cpp — the real dark horse.** whisper.cpp is now under `ggml-org`
  (<https://github.com/ggml-org/whisper.cpp>), 53,781 stars, MIT, pushed **2026-09-18**; Metal is
  the Apple default. Bindings: PyPI `pywhispercpp` **1.5.1, 2026-08-22**, MIT, deps only
  `numpy, requests, tqdm, platformdirs`, with binary wheels for `macosx_11_0_arm64` **and**
  `manylinux_2_28_{x86_64,aarch64}` + musllinux — *one backend for both platforms, no torch*.
  Blocked on: whisper.cpp DTW word timestamps are widely considered weaker than faster-whisper's,
  and per-token probability plumbing through pywhispercpp is **UNVERIFIED**.
- **WhisperKit** — Swift only; no `whisperkit`/`whisperkit-cli` package on PyPI (404). Access is
  Homebrew CLI or a local HTTP server. macOS 14+/Xcode 16+. Heavier install story than the thing
  it replaces. Disqualified for a pip-installable CLI.
- **ONNX Runtime CoreML EP for Whisper** — **UNVERIFIED**, not investigated. Prior expectation is
  heavy CPU fallback plus building word-timestamp DTW yourself. Low expected value.

**Linux/incumbent health.**
- `faster-whisper` PyPI **1.2.1, 2025-10-31**, MIT, `requires_python >=3.9`; deps
  `ctranslate2>=4.0,<5, huggingface-hub, tokenizers, onnxruntime>=1.14,<2, av>=11, tqdm` — no
  torch. Repo <https://github.com/SYSTRAN/faster-whisper> 25,470 stars, pushed **2025-11-19**
  (~10 months idle, 323 open issues, no deprecation notice).
- `ctranslate2` PyPI **4.8.2, 2026-08-31**, MIT, deps only `numpy, pyyaml`; wheels for
  `macosx_11_0_arm64` (CPU only — the install docs list GPU support for Linux/Windows wheels
  only) and `manylinux_2_28_{x86_64,aarch64}`. Engine is healthy; the Python wrapper is the stale
  layer, wrapping a frozen API. **Still the right Linux default.**
- **CUDA footgun:** faster-whisper's README says cuBLAS for CUDA 12 + **cuDNN 9**;
  <https://opennmt.net/CTranslate2/installation.html> says CUDA 12.x + **cuDNN 8**. The two
  primary sources disagree; the CT2 docs page looks stale against the shipped 4.8.x wheels.
  Because ASR lives in its own venv here, this only bites if torch and ctranslate2 ever share one.

### 3.2 Separation

**demucs-mlx — the single credible MLX port in this whole report.**
- <https://github.com/ssmall256/demucs-mlx> — 41 stars, MIT, not archived, created 2026-02-19,
  last push **2026-08-12**.
- PyPI `demucs-mlx` **1.4.6, 2026-08-12**, MIT, `requires_python >=3.10`, **11 releases** from
  2026-02-20 to 2026-08-12 — steady cadence.
- **Torch-free at inference.** Deps: `mlx==0.31.2, mlx-audio-io==1.3.11, mlx-spectro>=0.2.4,
  numpy, packaging, tqdm`; `torch>=2.6` + `demucs>=4.0` only in the `[convert]` extra.
- Models: `htdemucs, htdemucs_ft, htdemucs_6s, hdemucs_mmi, mdx, mdx_extra` — covers 4-stem and
  6-stem.
- Weights: <https://huggingface.co/mlx-community/demucs-mlx> (MIT, verified: all models as
  `{name}.safetensors` + `{name}_config.json`, ~105 MB–1.3 GB each, 6.72 GB total) and an fp16
  twin <https://huggingface.co/mlx-community/demucs-mlx-fp16> (MIT, same file list). Both
  `lastModified` 2026-03-16.
- Self-reported benchmark (README; M4 Max 128 GB, 3:15 stereo 44.1 kHz): demucs 4.0.1 torch **CPU
  52.3 s**, torch **MPS 6.9 s**, **demucs-mlx 2.7 s**. Vendor claim, no third-party SDR table.
  "Bit-exact parity within floating-point tolerance" is likewise the author's own claim.
- **Contract gaps:** CLI has `-n/--name, -o/--out, --shifts, --seed, --overlap, -b/--batch-size,
  --write-workers, --list-models`. **No `--two-stems`, no `--float32`, no `--repo`.** Two-stem is
  reconstructible (vocals + sum of the rest) via the Python API. Output bit depth undocumented —
  **UNVERIFIED**.
- **Env hazard:** hard pin `mlx==0.31.2` (MLX 0.32 support "pending"). Any other MLX package in
  the same venv will conflict — notably `mlx-audio` requires `mlx>=0.31.1` and Kokoro TTS would
  drag in the newer core.

**Not credible enough:** `lextoumbourou/mlx-demucs` (5 stars, ~5 commits, **no license**, pushed
2026-05-18); `ssmall256/mlx-audio-separator` (15 stars, same author, broader but less proven).
Other HF hits (`iky1e/demucs-mlx`, `jasonvassallo/demucs-htdemucs-mlx`, `starkdmi/Demucs_MLX`,
`lexandstuff/mlx-demucs`) exist but their provenance is **UNVERIFIED**.
**`Blaizzy/mlx-audio` does not do separation** — its `sts/models/` tree is enhancement/dialogue
(deepfilternet, mel_roformer, mossformer2_se, moshi, …), no Demucs.

**Demucs upstream moved — and our pin is from the old world.**
- PyPI `demucs` **4.1.0, 2026-07-11** (previous release was 4.0.1 in Sept 2023 — a ~3-year gap,
  now broken). `requires_python >=3.10`; `torch>=2.1` off macOS-x86_64. **`torchaudio` is gone
  from the inference deps** (verified in `requires_dist`); new deps `sphn>=0.1.12` and
  `safetensors`.
- **`facebookresearch/demucs` is ARCHIVED** (`archived: true`, last push 2024-04-24, 10,364
  stars). The live repo is <https://github.com/adefossez/demucs> (3,231 stars, pushed
  **2026-08-31**, MIT) and it is the `Homepage` in 4.1.0's PyPI metadata. **This is the right
  pin in 2026.** Maintainer's README: "I'm not actively working on Demucs anymore" — life
  support.
- 4.1.0 release notes relevant to us: min Python 3.10 / torch 2.1; **"Resolved checkpoint loading
  compatibility with torch >= 2.6"** (the `weights_only=True` breakage — our `demucs>=4.1,<5`
  pin already dodges it); pretrained models now on **HuggingFace Hub as safetensors**, which makes
  our `dl.fbaipublicfiles.com` + `955717e8-8726e21a.th` fetch the legacy path (still works via
  `--repo`); audio decoding via `sphn` with ffmpeg fallback; new `demucs.api` for programmatic
  access; new `--other-method` flag.
- `sphn` PyPI **0.2.1, 2026-01-07** ships `macosx_11_0_arm64` + `manylinux_2_24_x86_64` +
  `win_amd64` — **no linux-aarch64 wheel**, so ARM Linux builds from source. Minor, but note it.

**htdemucs under torch MPS — works, ~7–8× CPU, one handled fallback.**
- `facebookresearch/demucs` #503 "avoid using mps for complex numbers" (closed 2023-05-30): MPS
  lacks complex-number support, affected ops fall back to CPU. This is exactly why
  `PYTORCH_ENABLE_MPS_FALLBACK=1` is in our invocation, and it is correctness-preserving.
- 4.0.1 changelog lists "MPS device optimization for complex number computations" — the hybrid
  transformer STFT path is handled upstream.
- #575 "Use mps by default if available" (still open, 2023-12-03): contributor reports "about 8x
  faster on an M2 MBP". Still open → MPS is **not** upstream's default device; we pass it
  ourselves, which we already do.
- Corroborated by the demucs-mlx table: 52.3 s CPU vs 6.9 s MPS = 7.6×.
- **No credible report of wrong or degraded stems on MPS.** No published SDR-on-MPS comparison
  either — **UNVERIFIED**.

**Other fallbacks.** `demucs.cpp` (<https://github.com/sevagh/demucs.cpp>, 178 stars, MIT, last
push **2024-12-01**) covers htdemucs/htdemucs_6s/htdemucs_ft/hdemucs_mmi but accelerates with
**OpenBLAS + OpenMP only — no Metal, no CoreML, no Accelerate**. On our hardware that is the
~52 s class, not the ~7 s class. Strictly worse than MPS.
`audio-separator` PyPI **0.47.0, 2026-08-27**, MIT, `requires_python !=3.14.1,>=3.10`; repo moved
to `nomadkaraoke/python-audio-separator` (PyPI `project_urls` still points at `karaokenerds`).
Covers both platforms with one dep and adds UVR/MDX/Roformer, but installs **torch *and*
onnxruntime** — heavier than what we have. `spleeter` is TF-based, 4-stem max, 280 open issues —
ignore. Open-Unmix's Wiener filtering is already vendored into `demucs.wiener`.

### 3.3 Voice conversion (Seed-VC)

**No MLX Seed-VC. The one artefact that exists does not fit our contract.**
- GitHub search `voice+conversion+mlx` returns 4 repos; none is Seed-VC.
  `Acelogic/Retrieval-based-Voice-Conversion-MLX` (29 stars, pushed 2026-03-05, **no license**)
  is the only substantive one — full RVC + MLX RMVPE, claiming 8.71× over torch MPS (1.27 s vs
  11.08 s, M3 Max, 2026-01-06). **RVC is not zero-shot** (needs a per-speaker trained model +
  FAISS index), so it fails the contract outright, and it is unlicensed.
- <https://huggingface.co/Avdpro/MLX-Seed-VC-v2> **does exist** (GPL-3.0, `lastModified`
  2026-09-05, 48 downloads, 0 likes, tags `mlx, voice-conversion, seed-vc`) and is described as a
  "torch-free native MLX conversion of the pinned Seed-VC v2 inference pipeline **for AI2Apps**".
  It is **weights + a JSON checkpoint for a closed product** — no public inference code, no PyPI
  package (`seed-vc-mlx`, `mlx-seed-vc`, `seedvc-mlx` all 404). Its `NOTICE.md` also shows it is
  the **wrong variant**: Seed-VC *v2* (ASTRAL quantizer + HuBERT Large content encoder) with
  **BigVGAN v2 22 kHz**, versus our v1 `..._f0_44k_bigvgan_..._v2.pth` + whisper-small +
  **44 kHz** BigVGAN, and no F0-conditioning mode is documented. Not usable.
- **`mlx-audio` has no voice conversion.** In-repo search for `seedvc`: 0 hits. Its "voice
  cloning" is TTS-from-reference (CSM, Qwen3-TTS, OmniVoice) — a different contract.
- Component-level MLX coverage is partial and would have to be stitched: BigVGAN exists inside
  `mlx-audio` (`mlx_audio/codec/models/bigvgan/`, MIT, maintained) and as the dead
  `yrom/mlx-bigvgan` (1 star, 2025-05-14); CAMPPlus has real MLX weights
  (`mlx-community/campplus_multilingual_16k_advanced`, 2026-01-16, 23 downloads, plus q4 variants
  — but these are the **16 kHz ModelScope** CAMPPlus, not necessarily identical to our
  `funasr/campplus` `campplus_cn_common.bin`); RMVPE has only `lextoumbourou/mlx-rmvpe` and
  `blossom-slopware/rmvpe-mlx`, **both 0 stars**. Porting the DiT + length regulator + F0
  conditioning is multi-week bespoke work with no upstream to inherit fixes from.

**Upstream: `Plachtaa/seed-vc` is ARCHIVED** — `archived: true`, 3,893 stars, GPL-3.0, final
commit `51383efd` 2025-04-20, no GitHub releases. Our pinned `8695971` is ~1 month behind final.
Archived is tolerable given we pin a sha and vendor patches, but there will be no upstream fixes
ever, and issue #213 (44.1 kHz BigVGAN v2 training) will stay open forever.

**MPS on Seed-VC is already merged and already in our sha.**
- PR #138 "Add mac support" — `merged: true`, merged **2025-03-04**, merge commit `c3f45913`.
  `compare/c3f45913...86959712` returns `{"status":"ahead","ahead_by":11,"behind_by":0}` — our
  checkout contains it. `inference.py` auto-detects `cuda → mps → cpu`; no `--device` flag needed.
- The biggest feared risk is a non-issue: `bigvgan.BigVGAN.from_pretrained(..., use_cuda_kernel=False)`
  is **hardcoded** on every path, so the custom anti-aliased-activation CUDA kernel is never
  compiled or invoked. RMVPE takes `device=device, is_half=False`, matching our `--fp16 False`.
- PR author's benchmark (MacBook Pro M1 32 GB): CPU-only 25 diffusion steps ≈ **20 m 46 s** per
  clip (RTF 308); MPS **1.57 it/s** ≈ 16 s per clip — roughly **80× faster**. At our
  `--diffusion-steps 30` that extrapolates to ~19–20 s on an M1.
- **Gotcha:** `WhisperModel.from_pretrained(whisper_name, torch_dtype=torch.float16).to(device)`
  hardcodes fp16 on the content encoder *regardless of `--fp16 False`*. Most likely source of
  NaN/dtype surprises on MPS. Related: open issue #128 "Could not infer dtype of numpy.float32".
- Core ML / ONNX export of Seed-VC: no evidence anyone has done it; the DiT + length adjustment
  is export-hostile and upstream is archived. **Not viable.**

### 3.4 Singing synthesis (DiffSinger)

**No MLX singing synthesis exists at all.** GitHub repo search: `diffsinger mlx` →
`total_count: 0`; `singing voice synthesis mlx` → `0`; `nsf-hifigan mlx` → `0`;
`so-vits-svc mlx` → `0` (all verified against the GitHub search API today). The only
hifigan-on-MLX hit is `gwenn-ha-dev/HiFiGAN-WavLM-port` (0 stars, MLX-Swift, knn-vc variant) —
not DiffSinger's NSF-HiFiGAN.

**Upstream `MoonInTheRiver/DiffSinger`: dormant, not archived.** 4,862 stars, MIT; `pushed_at`
2026-07-24 is **doc churn** — the last *code* commit is 2023-04-30. Zero issues mention
mps/mac/apple, so there is no field evidence either way; we would be first.

**MPS is plumbable, unmeasured.** `inference/svs/base_svs_infer.py`:
```
def __init__(self, hparams, device=None):
    if device is None:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
```
No MPS branch, so on a Mac it silently runs CPU today — but the constructor **takes** `device`,
and everything downstream uses `.to(self.device)`. Passing `device='mps'` is the whole change.
The hardcoded `.cuda()` calls live in `modules/commons/ssim.py`, `tasks/tts/tts.py`,
`modules/parallel_wavegan/stft_loss.py`, `usr/diffsinger_task.py`,
`data_gen/tts/base_binarizer.py`, `modules/fastspeech/tts_modules.py` — all training/loss/binarizer
paths, none on `ds_e2e.py` inference (confirm the `tts_modules.py` one is in a training-only
branch before shipping). Our contract — output duration within 0.1 s of the score — is a
frontend/length-regulator property, not a device property, so MPS cannot silently break it: it
either runs or it doesn't.

**Alternatives.** `openvpi/DiffSinger` (3,206 stars, pushed **2026-09-18**, **Apache-2.0**) is the
live DiffSinger and the obvious migration target if we ever move off the pinned fork — no MLX,
but a mature ONNX export path (which is the realistic route to ONNX Runtime CoreML EP).
`ace-step/ACE-Step` (4,843 stars, Apache-2.0) has several Apple/MLX community ports
(`Moro-w/ACE-Step` 9 stars, `clockworksquirrel/ace-step-apple-silicon` 5 stars) but is a
text/tag → song music-generation model: it cannot take a Mandarin timed score and match duration
within 0.1 s. **Rejects on contract, not on Apple support.** `nnsvs/nnsvs` last pushed 2023-10-09
— dead.

### 3.5 Speech synthesis (`speech_synthesize`) — the one clear win

**mlx-audio + Kokoro.**
- <https://github.com/Blaizzy/mlx-audio> 7,914 stars, MIT, created 2024-11-27, pushed
  **2026-09-18**, 107 open issues. PyPI `mlx-audio` **0.5.4, 2026-09-14**, MIT,
  `requires_python >=3.10`.
- Core deps (**no torch**): `huggingface_hub>=1.0, miniaudio>=1.61, mlx>=0.31.1, numpy, scipy,
  sounddevice>=0.5.3, tqdm, transformers>=5.14.0`. Extras `tts` (`mistral-common[audio]`,
  `sentencepiece`), `stt`, `sts`, `server`.
- CLI:
  `python -m mlx_audio.tts.generate --model mlx-community/Kokoro-82M-bf16 --text '…' --voice af_heart`
  with `--output_path`, `--stream`, `--save`, `--join_audio`. **Voice by name** (54 Kokoro
  presets) and a **`speed` parameter** — both knobs `speech_synthesize` already exposes.
- **Reference-voice cloning is supported** via `--ref_audio` (CSM `mlx-community/csm-1b`;
  OmniVoice takes `ref_audio` + `ref_text`). That is the path to un-refusing
  `speech_synthesize(reference_audio_path=…)` — but keep it a separate opt-in model, and settle
  the weights licence first (CSM-1B and OmniVoice weight licences are **UNVERIFIED**).
- Weights: `mlx-community/Kokoro-82M-bf16` (lastModified 2025-12-02, **83,878 downloads**, card
  says 355 MB, Apache-2.0) plus `-8bit`, `-6bit`, `-4bit` (sizes **UNVERIFIED**). Upstream
  <https://huggingface.co/hexgrad/Kokoro-82M> is Apache-2.0, 82M params, 8 languages / 54 voices;
  upstream stores **one `.pt` per voice** under `voices/` (not a single voices.json) — the layout
  inside the mlx-community repos is **UNVERIFIED**.
- **Real-time factor on Apple Silicon: UNVERIFIED** — no primary source publishes one.
- Risk: fast-moving 0.x, and `transformers>=5.14.0` is a hard, very new pin.

**Linux parity with the same model.** `kokoro-onnx` PyPI **0.6.1, 2026-08-19**, MIT,
`requires_python >=3.10,<3.14`, deps `onnxruntime>=1.20.1, espeakng-loader>=0.2.4,
phonemizer>=3.4.0, numpy>=2.0.2`, with a `gpu` extra pulling `onnxruntime-gpu>=1.20.1` gated to
x86_64 non-Darwin. **No torch anywhere**, and `espeakng-loader` ships espeak-ng so there is no
apt prerequisite. Same Kokoro weights, same voice names, same `speed` concept as the MLX path.
The torch-based `kokoro` PyPI package (**0.9.4, 2025-04-05**, `>=3.10,<3.13`, pulls torch +
transformers + `misaki[en]` → spacy, phonemizer-fork, pyopenjtalk) is the wrong choice.

**Other MLX TTS.** `f5-tts-mlx` PyPI **0.2.6, 2025-03-19**, MIT, no torch, does reference-audio
cloning — but the repo's last push is **2025-03-19** (18 months stale) and **F5-TTS base weights
are widely reported CC-BY-NC — UNVERIFIED and the likeliest licensing landmine**; do not ship it
without fetching the SWivid/F5-TTS card. `csm-mlx` is not on PyPI (404) — CSM is reachable only
through mlx-audio. `orpheus-tts` on PyPI is a thin websockets client, not local weights.
`kittentts` (0.1.3, 2025-08-10) is ONNX/cross-platform but its licence field is empty —
**UNVERIFIED**. `outetts` and `chatterbox-tts` both drag in torch; use them via mlx-audio if at
all.

---

## 4. Proposed installer platform matrix

### 4.1 Detection rule

```python
# tools/install_models.py
import platform, sys

def target() -> str:
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "darwin-arm64"
    if sys.platform.startswith("linux"):
        return "linux-cuda" if _cuda() else "linux-cpu"
    raise SystemExit("edittude model backends support macOS arm64 and Linux only")
```

**Do not hand-roll CUDA detection for the torch install.** `_venv()` already shells to
`uv pip install`, and uv 0.10.11 has the flag (verified locally with `uv pip install --help`):

```
--torch-backend <TORCH_BACKEND>   [env: UV_TORCH_BACKEND=]  [possible values: auto, cpu,
                                   cu130, cu129, cu128, cu126, ... rocm7.1, ...]
```

uv's docs (<https://docs.astral.sh/uv/guides/integration/pytorch/>) describe `auto` as querying
"the installed CUDA driver, AMD GPU versions, and Intel GPU presence", falling back to CPU-only
when no GPU is found. **Caveat from the same page: the feature currently works with `uv pip`
only** — which is exactly what `_venv()` uses. One flag replaces a whole detector:

```python
_run([_uv(), "pip", "install", "--quiet", "--python", python, "--torch-backend=auto", *deps])
```

Only write `_cuda()` for the *non-torch* decision (e.g. `faster-whisper` device selection, or
picking `kokoro-onnx[gpu]`). Matching uv's semantics (driver presence, not binary presence):

```python
def _cuda() -> bool:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return False
    out = subprocess.run([smi, "-L"], capture_output=True, text=True)
    return out.returncode == 0 and out.stdout.strip().startswith("GPU")
```

`shutil.which("nvidia-smi")` **alone over-reports** (a container can have the binary with no
usable driver); requiring exit 0 *and* a `GPU`-prefixed line is the cheap correct version. There
is no authoritative doc endorsing either trick — **UNVERIFIED** as a documented standard.
`/proc/driver/nvidia/version` and `/dev/nvidia0` are real signals but miss WSL2 and some
container setups.

Runtime-side, `tools/models.py` already does the right thing for demucs
(`cuda → mps → cpu` probed inside the model venv). Keep that pattern: **detect at install time
for dependency selection, at run time for device selection.**

### 4.2 Shared deps

| | darwin-arm64 | linux-cuda | linux-cpu |
|---|---|---|---|
| `SHARED` | `torch>=2.6`, `numpy<3`, `soundfile`, `huggingface-hub>=0.34,<1` | same, `--torch-backend=auto` | same, `--torch-backend=auto` |
| torch index | PyPI default (Apple-Silicon wheel; `torch-2.14.0-cp31x-macosx_14_0_arm64.whl` exists — **no index URL needed**; PyTorch publishes no CUDA builds for macOS) | `https://download.pytorch.org/whl/cu126` or `cu130` via `--torch-backend` | `https://download.pytorch.org/whl/cpu` |
| `torchaudio` | **drop it** | **drop it** | **drop it** |

**Two fixes to the current pins, independent of any MLX decision:**

1. **`torchaudio>=2.6,<2.9` is actively wrong.** `pytorch/audio`'s README states TorchAudio is in
   a "maintenance phase", that features "deprecated from TorchAudio 2.8 [were] removed in 2.9",
   and that **"TorchAudio 2.11 works with `torch` 2.11 and with every future `torch` release …
   installing TorchAudio does not pin `torch` to a specific version"** (latest is 2.11.0,
   2026-03-23; `requires_dist` is now empty). The `<2.9` bound pins us into the pre-removal
   range for no reason. **demucs 4.1.0 dropped torchaudio from its inference deps entirely**, and
   neither Seed-VC's CLI path nor DiffSinger's requires it via our install list — so the lazy fix
   is to **delete `torchaudio` from `SHARED`** and re-add `torchaudio>=2.11` (no upper bound)
   only if an import actually fails.
2. **Live wheel indexes, checked today** (HTTP 200 for `cpu, cu118, cu121, cu124, cu126, cu128,
   cu129, cu130, rocm6.4, rocm7.2, xpu, nightly`; **403 for `cu131`**). Version coverage for
   cp312 Linux: `cpu` 2.7.1→2.14.0, `cu126` 2.8.0→2.14.0, `cu130` 2.9.0→2.14.0, but **`cu128`
   stops at 2.11.0** — do not pin cu128 for torch ≥ 2.12. `cu129` range **UNVERIFIED**.
   Also note torch 2.14.0's own Linux `requires_dist` now pulls `cuda-toolkit==13.0.3`,
   `nvidia-cudnn-cu13==9.24.0.43` etc. as **PyPI dependencies** — a plain `pip install torch` on
   a CPU-only Linux box drags CUDA 13 in. The `cpu` index is not optional there.

### 4.3 Per-backend dep lists and weight repos

**asr → `speech_transcribe`**

| | darwin-arm64 | linux-cuda | linux-cpu |
|---|---|---|---|
| deps | `faster-whisper>=1.2,<2` | `faster-whisper>=1.2,<2` | `faster-whisper>=1.2,<2` |
| weights | `Systran/faster-whisper-base` (unchanged) | same | same |
| device | `cpu`, `int8` | `cuda`, `float16` | `cpu`, `int8` |
| opt-in | `EDITTUDE_ASR_BACKEND=mlx` → `uv pip install --no-deps mlx-whisper` + `mlx numba scipy tiktoken more-itertools huggingface-hub tqdm numpy`; weights `mlx-community/whisper-base-mlx` (143.7 MB) | — | — |

Note the CUDA row needs cuBLAS + **cuDNN 9** for CUDA 12 in the model venv (faster-whisper README),
which `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` supplies; CT2's own docs say cuDNN 8 —
sources conflict, prefer 9.

**separation → `audio_separate`**

| | darwin-arm64 | linux-cuda | linux-cpu |
|---|---|---|---|
| deps | `demucs>=4.1,<5` (+ torch) | same | same |
| weights | `demucs/htdemucs.yaml` + `955717e8-8726e21a.th` (legacy path; 4.1.0 also publishes safetensors on the Hub) | same | same |
| device | `mps` (with `PYTORCH_ENABLE_MPS_FALLBACK=1`) | `cuda` | `cpu` |
| opt-in | `EDITTUDE_SEPARATION_BACKEND=mlx` → `demucs-mlx>=1.4,<2` in a **separate venv** (it pins `mlx==0.31.2`); weights `mlx-community/demucs-mlx` or `-fp16` | — | — |

**seed-vc → `voice_convert`** — identical everywhere: current `deps` list unchanged, current HF
pins unchanged, device auto-detected by upstream `inference.py` (`cuda → mps → cpu`). No MLX row.

**diffsinger → `singing_synthesize`** — identical everywhere; current `deps` and
`PillowTa1k/DiffSinger` checkpoints unchanged. Add a `device='mps'` line to
`tools/patches/DiffSinger.patch` and set `PYTORCH_ENABLE_MPS_FALLBACK=1`. No MLX row.

**tts → `speech_synthesize`** (new optional backend)

| | darwin-arm64 | linux-cuda | linux-cpu |
|---|---|---|---|
| deps | `mlx-audio>=0.5,<0.6` | `kokoro-onnx>=0.6,<0.7` + `onnxruntime-gpu` (`[gpu]` extra, x86_64 only) | `kokoro-onnx>=0.6,<0.7` |
| weights | `mlx-community/Kokoro-82M-bf16` (~355 MB, Apache-2.0) | Kokoro ONNX + voices | same |
| fallback | `say` stays as the zero-install default | `espeak-ng` | `espeak-ng` |

`speed = rate / 180` is the obvious mapping from the existing `rate` parameter to Kokoro's
`speed`; Kokoro's natural WPM at `speed=1.0` is **UNVERIFIED** — calibrate empirically and leave
the constant as a tunable, not a literal.

---

## 5. What each swap costs in `tools/models.py`

The tool signatures and return payloads do not change in any scenario — only the runner inside
`_model_run`. Risks ranked.

| Swap | Change | Risk |
|---|---|---|
| **DiffSinger → MPS** | Patch `BaseSVSInfer.__init__` to take/choose `mps`; add `PYTORCH_ENABLE_MPS_FALLBACK=1` to `_OFFLINE_ENV` (or per-call env). No change to `singing_synthesize`. | **Low-medium.** Nobody has run DiffSinger on MPS; the diffusion decoder may hit op gaps. Fallback is silent per-op CPU, so worst case is "no faster". The 0.1 s duration assertion still guards output. |
| **Seed-VC → MPS** | **None.** Already auto-detects. | **Low.** Watch the hardcoded fp16 Whisper content encoder for NaNs on MPS; `_publish_audio` → `_audio()` would surface a dead file, and `duration_difference` would surface timing drift. |
| **Drop `torchaudio` from `SHARED`** | One line in `install_models.py`. | **Low.** demucs 4.1 no longer needs it; if Seed-VC or DiffSinger import it transitively the install fails loudly at first run, and `capabilities()` reports it. |
| **`speech_synthesize` → Kokoro** | Real work: `speech_synthesize` currently shells to `say`/`espeak` in the **agent** venv (it is the only tool that does not use `_model_run`). Kokoro must run in the model venv via `_model_run("TTS", …)`, and `capabilities()` needs a `TTS` entry in `modules`/the backend loop. Voice validation changes from `say -v ?` to a fixed Kokoro voice list; `rate` maps to `speed`. | **Medium.** Biggest diff of the five, but it is additive: keep `say`/`espeak-ng` as the fallback when the TTS backend is not installed, so nothing regresses for users who never run `models install tts`. |
| **ASR → mlx-whisper (opt-in)** | New runner: `import mlx_whisper; mlx_whisper.transcribe(src, path_or_hf_repo=…, word_timestamps=True, language=… or None, temperature=0, condition_on_previous_text=False)`. Rename each word's `word` key to `text`. **Replace `vad_filter=True`** — either accept `no_speech_prob` filtering or add Silero separately. | **Medium-high.** The VAD loss is a real behaviour change: `vad_filter` currently removes long silences, and without it the strict segment-ordering assertions in `speech_transcribe` see different segmentation. Also `--no-deps` install is fragile (a future real dep would be silently missed). |
| **Separation → demucs-mlx (opt-in)** | New runner (Python API, not `demucs.separate`), plus reimplementing `--two-stems` as vocals + sum-of-rest, plus confirming float32 output. Needs its own venv because of `mlx==0.31.2`. | **Medium-high.** Second inference implementation, second set of weights (6.7 GB), a hard MLX pin that fights `mlx-audio`, and "bit-exact parity" is the author's unreviewed claim. Payoff is 6.9 s → 2.7 s on a 3-minute track. |

---

## 6. Explicit "no good MLX option — use torch (+MPS)" list

1. **`voice_convert` / Seed-VC.** No MLX port. The only MLX artefact
   (`Avdpro/MLX-Seed-VC-v2`, GPL-3.0) is weights-only for a closed app, is Seed-VC **v2** with a
   22 kHz BigVGAN and an ASTRAL/HuBERT content encoder rather than our 44 kHz f0 v1 pipeline, and
   ships no runnable code. RVC-MLX exists but is not zero-shot and is unlicensed.
   → **torch + MPS, already working, ~80× CPU.**
2. **`singing_synthesize` / DiffSinger.** Zero MLX singing-synthesis projects exist —
   `diffsinger mlx`, `singing voice synthesis mlx`, `nsf-hifigan mlx` all return zero repos.
   → **torch + MPS via a one-line device patch** (unmeasured; keep `PYTORCH_ENABLE_MPS_FALLBACK=1`).
3. **`audio_separate` / Demucs — for the default path.** A credible MLX port (`demucs-mlx`)
   *does* exist, so this is a judgement call rather than an absence: 41 stars, one self-reported
   benchmark, missing `--two-stems`, and a conflicting `mlx==0.31.2` pin do not justify routing
   every Mac user through a second implementation for 6.9 s → 2.7 s.
   → **torch + MPS as the default; MLX behind an env flag.**
4. **`speech_transcribe` / ASR — for the default path.** `mlx-whisper` fits the contract except
   VAD, but is 13 months without a release with a phantom torch dep, and no same-machine
   benchmark exists to prove it beats `base` + int8 on CPU.
   → **faster-whisper everywhere; MLX behind an env flag until someone measures.**
5. **Component models (RMVPE, CAMPPlus, NSF-HiFiGAN).** MLX ports are 0–1 star abandonware or
   wrong-variant. Not a path to a hand-assembled MLX pipeline.

Only `speech_synthesize` has a clean MLX answer, and only because it is currently `say`.

---

## 7. Open questions worth one experiment each

1. **The decisive ASR number:** `mlx-whisper base` vs `faster-whisper base int8 cpu_threads=4` on
   the same M-series machine. Nobody publishes it. ~20 minutes.
2. **DiffSinger on MPS:** does the diffusion decoder run without falling back to CPU for
   everything? Timeboxed spike; CPU still works if not.
3. **Seed-VC fp16 content encoder on MPS:** NaN check on one real conversion.
4. **demucs-mlx output:** bit depth, and stem parity against the torch stems (SDR or null test).
5. **Licences before shipping any cloning TTS:** F5-TTS (likely CC-BY-NC), CSM-1B, OmniVoice,
   KittenTTS — all currently **UNVERIFIED**.
