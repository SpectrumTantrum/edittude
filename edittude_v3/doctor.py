"""Local environment check. Warnings do not fail the process; failures do."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

FFMPEG_MIN = (7, 1)
DISK_WARN_BYTES = 1024**3
_VERSION = re.compile(r"version\s+(\d+)\.(\d+)(?:\.(\d+))?")
_REQUIRED_ENCODERS = ("libx264", "aac", "libopus")
_OPTIONAL_ENCODER = "libtheora"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    message: str
    hint: str | None = None


def cache_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    override = env.get("EDITTUDE_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    base = env.get("XDG_CACHE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cache"
    return root / "edittude"


def collect_checks(
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    environ: Mapping[str, str] | None = None,
    temp_dir: Path | None = None,
    cache: Path | None = None,
    disk_usage: Callable[[Path], object] | None = None,
    model_items: Sequence[tuple[str, bool]] | None = None,
    python_version: tuple[int, int] | None = None,
    cuda_message: str | None = None,
) -> list[Check]:
    """Run every check. Inject the callables in tests so ffmpeg is not required."""
    env = os.environ if environ is None else environ
    spawn = _spawn if run is None else run
    usage = shutil.disk_usage if disk_usage is None else disk_usage
    checks: list[Check] = []
    ffmpeg = _tool_check("ffmpeg", which, spawn)
    ffprobe = _tool_check("ffprobe", which, spawn)
    checks.extend((ffmpeg, ffprobe))
    checks.extend(_encoder_checks(ffmpeg, which, spawn))
    checks.append(_python_check(python_version or sys.version_info[:3]))
    checks.append(_uv_check(which, spawn))
    temp = temp_dir if temp_dir is not None else Path(tempfile.gettempdir())
    cache_path = cache if cache is not None else cache_dir(env)
    checks.append(_writable_check("temp", temp, "set TMPDIR to a writable directory"))
    checks.append(
        _writable_check("cache", cache_path, "set EDITTUDE_CACHE_DIR to a writable directory")
    )
    checks.append(_disk_check(cache_path, usage))
    checks.append(_models_check(env, model_items))
    checks.append(Check("cuda", "info", cuda_message if cuda_message is not None else _cuda_message(which, spawn)))
    return checks


def exit_code(checks: Sequence[Check]) -> int:
    return 1 if any(check.status == "fail" for check in checks) else 0


def format_text(checks: Sequence[Check]) -> str:
    lines: list[str] = []
    for check in checks:
        line = f"{check.status:<4}  {check.name:<18}  {check.message}"
        if check.hint and check.status in {"fail", "warn"}:
            line += f"  hint: {check.hint}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def format_json(checks: Sequence[Check]) -> str:
    payload = {
        "ok": exit_code(checks) == 0,
        "checks": [
            {
                "name": check.name,
                "status": check.status,
                "message": check.message,
                "hint": check.hint,
            }
            for check in checks
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def _spawn(args: Sequence[str], timeout: float = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _tool_check(
    name: str,
    which: Callable[[str], str | None],
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> Check:
    path = which(name)
    if not path:
        return Check(name, "fail", "not on PATH", f"install ffmpeg and put {name} on PATH")
    try:
        result = run([path, "-version"], timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return Check(name, "fail", "could not run", f"reinstall ffmpeg so {name} -version works")
    text = f"{result.stdout or ''}{result.stderr or ''}"
    if result.returncode != 0:
        return Check(name, "fail", "could not read the version", f"reinstall ffmpeg so {name} -version works")
    parsed = _parse_version(text)
    if parsed is None:
        return Check(name, "warn", "could not parse the version", "install ffmpeg 7.1 or newer")
    shown = ".".join(str(part) for part in parsed)
    if parsed[:2] < FFMPEG_MIN:
        return Check(
            name,
            "warn",
            f"{shown} is older than 7.1",
            "install ffmpeg 7.1 or newer",
        )
    return Check(name, "pass", shown)


def _encoder_checks(
    ffmpeg: Check,
    which: Callable[[str], str | None],
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> list[Check]:
    names: set[str] = set()
    available = ffmpeg.status != "fail"
    if available:
        path = which("ffmpeg")
        try:
            result = run([path or "ffmpeg", "-hide_banner", "-encoders"], timeout=15)
            names = _encoder_names(f"{result.stdout or ''}{result.stderr or ''}")
            if result.returncode != 0:
                available = False
        except (OSError, subprocess.TimeoutExpired):
            available = False
    checks: list[Check] = []
    for encoder in _REQUIRED_ENCODERS:
        if not available:
            checks.append(
                Check(
                    f"encoder-{encoder}",
                    "fail",
                    "ffmpeg encoders could not be listed",
                    "install an ffmpeg build with libx264, aac, and libopus",
                )
            )
        elif encoder in names:
            checks.append(Check(f"encoder-{encoder}", "pass", encoder))
        else:
            checks.append(
                Check(
                    f"encoder-{encoder}",
                    "fail",
                    f"{encoder} is not available",
                    "install an ffmpeg build with libx264, aac, and libopus",
                )
            )
    if not available or _OPTIONAL_ENCODER not in names:
        checks.append(
            Check(
                f"encoder-{_OPTIONAL_ENCODER}",
                "warn",
                f"{_OPTIONAL_ENCODER} is not available",
                "install an ffmpeg build with libtheora to inventory .ogv files",
            )
        )
    else:
        checks.append(Check(f"encoder-{_OPTIONAL_ENCODER}", "pass", _OPTIONAL_ENCODER))
    return checks


def _python_check(version: tuple[int, ...]) -> Check:
    shown = ".".join(str(part) for part in version[:3])
    if version[:2] < (3, 13):
        return Check("python", "warn", f"{shown} is older than 3.13", "install Python 3.13 or newer")
    return Check("python", "pass", shown)


def _uv_check(
    which: Callable[[str], str | None],
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> Check:
    path = which("uv")
    if not path:
        return Check("uv", "warn", "not on PATH", "install uv from https://docs.astral.sh/uv/")
    try:
        result = run([path, "--version"], timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return Check("uv", "warn", "could not run", "reinstall uv from https://docs.astral.sh/uv/")
    line = (result.stdout or result.stderr or "").strip().splitlines()
    message = line[0].strip() if line else "could not read the version"
    if result.returncode != 0 or not line:
        return Check("uv", "warn", message, "reinstall uv from https://docs.astral.sh/uv/")
    return Check("uv", "pass", message)


def _writable_check(name: str, path: Path, hint: str) -> Check:
    probe = path / ".edittude-doctor"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        detail = exc.strerror or "not writable"
        return Check(name, "fail", f"{path} is not writable ({detail})", hint)
    return Check(name, "pass", f"writable {path}")


def _disk_check(path: Path, disk_usage: Callable[[Path], object]) -> Check:
    target = path if path.exists() else path.parent
    try:
        usage = disk_usage(target)
        free = int(getattr(usage, "free"))
    except (OSError, TypeError, ValueError, AttributeError):
        return Check("disk", "fail", f"could not read free space on {target}", "check that the cache directory is on a mounted filesystem")
    shown = f"{free / 1024**3:.1f} GiB free on {target}"
    if free < DISK_WARN_BYTES:
        return Check("disk", "warn", shown, "free at least 1 GiB on the cache filesystem before rendering")
    return Check("disk", "pass", shown)


def _models_check(
    environ: Mapping[str, str],
    model_items: Sequence[tuple[str, bool]] | None,
) -> Check:
    items = list(model_items) if model_items is not None else _installed_models(environ)
    missing = [name for name, present in items if not present]
    if not missing:
        return Check("models", "pass", "ASR, Demucs, Seed-VC, and DiffSinger caches are present")
    names = ", ".join(missing)
    return Check(
        "models",
        "warn",
        f"missing {names}",
        "optional: edittude media models install (seed-vc and diffsinger need --models seed-vc,diffsinger)",
    )


def _installed_models(environ: Mapping[str, str]) -> list[tuple[str, bool]]:
    from tools.common import models_root
    from tools.models import DEFAULTS

    root = models_root()

    def present(env_name: str, kind: str) -> bool:
        value = environ.get(env_name)
        path = Path(value).expanduser() if value else root / DEFAULTS[env_name]
        return path.is_dir() if kind == "dir" else path.is_file()

    return [
        ("ASR", present("EDITTUDE_ASR_MODEL_DIR", "dir")),
        ("Demucs", present("EDITTUDE_DEMUCS_REPO", "dir")),
        (
            "Seed-VC",
            present("EDITTUDE_SEED_VC_DIR", "dir")
            and present("EDITTUDE_SEED_VC_CHECKPOINT", "file"),
        ),
        ("DiffSinger", present("EDITTUDE_DIFFSINGER_DIR", "dir")),
    ]


def _cuda_message(
    which: Callable[[str], str | None],
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    path = which("nvidia-smi")
    if not path:
        return "no CUDA device"
    try:
        result = run([path, "-L"], timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return "no CUDA device"
    if result.returncode != 0:
        return "no CUDA device"
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "no CUDA device"


def _parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.search(text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def _encoder_names(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and set(parts[0]) <= set("VASFD."):
            names.add(parts[1])
    return names
