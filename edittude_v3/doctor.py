"""Local environment check for a cut.

Required checks fail the process: ffmpeg and ffprobe on PATH, libx264, aac,
and the loudnorm and alimiter filters. Everything else is a warning or info.
Nothing here opens a network connection.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

FFMPEG_MIN = (7, 1)
DISK_WARN_BYTES = 1024**3
_VERSION = re.compile(r"version\s+(\d+)\.(\d+)(?:\.(\d+))?")
_REQUIRED_ENCODERS = ("libx264", "aac")
_OPTIONAL_ENCODERS = ("libopus", "libtheora")
_REQUIRED_FILTERS = ("loudnorm", "alimiter")
_NAME_WIDTH = 18


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
    cache: Path | None = None,
    footage: Path | None = None,
    footage_note: str | None = None,
    disk_usage: Callable[[Path], object] | None = None,
    model_rows: Sequence[tuple[str, str, str]] | None = None,
    key_present: bool | None = None,
    python_version: tuple[int, ...] | None = None,
    cuda_message: str | None = None,
) -> list[Check]:
    """Run every check. Inject the callables in tests so ffmpeg is not required."""
    env = os.environ if environ is None else environ
    spawn = _spawn if run is None else run
    usage = shutil.disk_usage if disk_usage is None else disk_usage
    checks: list[Check] = []
    ffmpeg = _tool_check("ffmpeg", which, spawn, version_floor=True)
    ffprobe = _tool_check("ffprobe", which, spawn, version_floor=False)
    checks.extend((ffmpeg, ffprobe))
    checks.extend(
        _named_tools(
            ffmpeg, which, spawn, "-encoders", _encoder_names, _REQUIRED_ENCODERS,
            optional=_OPTIONAL_ENCODERS, kind="encoder",
        )
    )
    checks.extend(
        _named_tools(
            ffmpeg, which, spawn, "-filters", _filter_names, _REQUIRED_FILTERS,
            optional=(), kind="filter",
        )
    )
    checks.append(_key_check(env, key_present))
    checks.append(_models_check(model_rows))
    footage_path = footage if footage is not None else Path.cwd()
    note = footage_note
    if footage is None and note is None:
        note = "cwd; no footage directory configured"
    checks.append(_disk_check("disk-footage", footage_path, usage, note))
    checks.append(_disk_check("disk-cache", cache if cache is not None else cache_dir(env), usage, None))
    checks.append(_python_check(python_version or sys.version_info[:3]))
    checks.append(_uv_check(which, spawn))
    checks.append(Check("cuda", "info", cuda_message if cuda_message is not None else _cuda_message(which, spawn)))
    return checks


def exit_code(checks: Sequence[Check]) -> int:
    return 1 if any(check.status == "fail" for check in checks) else 0


def format_text(checks: Sequence[Check]) -> str:
    """One line per check: OK, or a single fix sentence for warn and fail."""
    lines: list[str] = []
    for check in checks:
        if check.status in {"fail", "warn"}:
            lines.append(f"{check.name:<{_NAME_WIDTH}}  {check.hint or check.message}")
        elif check.message:
            lines.append(f"{check.name:<{_NAME_WIDTH}}  OK  {check.message}")
        else:
            lines.append(f"{check.name:<{_NAME_WIDTH}}  OK")
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


def _fail(name: str, sentence: str) -> Check:
    return Check(name, "fail", sentence, sentence)


def _warn(name: str, sentence: str) -> Check:
    return Check(name, "warn", sentence, sentence)


def _tool_check(
    name: str,
    which: Callable[[str], str | None],
    run: Callable[..., subprocess.CompletedProcess[str]],
    *,
    version_floor: bool,
) -> Check:
    path = which(name)
    if not path:
        return _fail(name, f"Install ffmpeg and put {name} on PATH.")
    try:
        result = run([path, "-version"], timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return _fail(name, f"Reinstall ffmpeg so {name} -version works.")
    text = f"{result.stdout or ''}{result.stderr or ''}"
    if result.returncode != 0:
        return _fail(name, f"Reinstall ffmpeg so {name} -version works.")
    parsed = _parse_version(text)
    if parsed is None:
        if version_floor:
            return _warn(name, "Could not parse the ffmpeg version; install ffmpeg 7.1 or newer.")
        return Check(name, "pass", "present")
    shown = ".".join(str(part) for part in parsed)
    if version_floor and parsed[:2] < FFMPEG_MIN:
        return _warn(name, f"ffmpeg {shown} is older than 7.1; install ffmpeg 7.1 or newer.")
    return Check(name, "pass", shown)


def _named_tools(
    ffmpeg: Check,
    which: Callable[[str], str | None],
    run: Callable[..., subprocess.CompletedProcess[str]],
    flag: str,
    parse: Callable[[str], set[str]],
    required: Sequence[str],
    *,
    optional: Sequence[str],
    kind: str,
) -> list[Check]:
    names: set[str] = set()
    available = ffmpeg.status != "fail"
    if available:
        path = which("ffmpeg")
        try:
            result = run([path or "ffmpeg", "-hide_banner", flag], timeout=15)
            names = parse(f"{result.stdout or ''}{result.stderr or ''}")
            if result.returncode != 0:
                available = False
        except (OSError, subprocess.TimeoutExpired):
            available = False
    checks: list[Check] = []
    for item in required:
        label = f"{kind}-{item}"
        if not available:
            checks.append(_fail(label, _tool_sentence(kind, item)))
        elif item in names:
            checks.append(Check(label, "pass", item))
        else:
            checks.append(_fail(label, _tool_sentence(kind, item)))
    for item in optional:
        label = f"{kind}-{item}"
        if not available or item not in names:
            checks.append(_warn(label, _tool_sentence(kind, item)))
        else:
            checks.append(Check(label, "pass", item))
    return checks


def _tool_sentence(kind: str, item: str) -> str:
    if kind == "filter":
        return f"Install an ffmpeg build that provides the {item} filter."
    if item == "libtheora":
        return "Install an ffmpeg build with libtheora to inventory .ogv files."
    return f"Install an ffmpeg build with {item}."


def _key_check(environ: Mapping[str, str], present: bool | None) -> Check:
    from edittude_v3.agent import API_KEY_ENV
    from edittude_v3.paths import env_file

    if present is None:
        present = _key_is_present(environ)
    if present:
        return Check("key", "info", "present")
    sentence = f"Set {API_KEY_ENV} or add it to {env_file()}."
    return _warn("key", sentence)


def _key_is_present(environ: Mapping[str, str]) -> bool:
    """True when the DeepSeek key is set. The value is never returned."""
    from edittude_v3.agent import API_KEY_ENV, _key_from_file
    from edittude_v3.paths import PACKAGE_ROOT, env_file, install_root, legacy_env_file

    if str(environ.get(API_KEY_ENV, "")).strip():
        return True
    paths = [env_file()]
    legacy = legacy_env_file()
    if legacy is not None:
        paths.append(legacy)
    paths.extend((install_root() / ".env", PACKAGE_ROOT / ".env"))
    for path in paths:
        try:
            if bool(_key_from_file(path)):
                return True
        except (OSError, UnicodeError):
            continue
    return False


def _models_check(rows: Sequence[tuple[str, str, str]] | None) -> Check:
    if rows is None:
        from tools.install_models import model_status

        rows = model_status(probe_vision=False)
    missing = [name for name, status, _reason in rows if status != "configured"]
    if not missing:
        names = ", ".join(name for name, _status, _reason in rows) or "configured"
        return Check("models", "pass", names)
    sentence = (
        "Optional models are not configured ("
        + ", ".join(missing)
        + "); run edittude media models install."
    )
    return _warn("models", sentence)


def _python_check(version: tuple[int, ...]) -> Check:
    shown = ".".join(str(part) for part in version[:3])
    return Check("python", "info", shown)


def _uv_check(
    which: Callable[[str], str | None],
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> Check:
    path = which("uv")
    if not path:
        return Check("uv", "info", "not on PATH")
    try:
        result = run([path, "--version"], timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return Check("uv", "info", "could not run")
    line = (result.stdout or result.stderr or "").strip().splitlines()
    message = line[0].strip() if line else "could not read the version"
    return Check("uv", "info", message)


def _disk_check(
    name: str,
    path: Path,
    disk_usage: Callable[[Path], object],
    note: str | None,
) -> Check:
    target = path if path.exists() else path.parent
    try:
        usage = disk_usage(target)
        free = int(getattr(usage, "free"))
    except (OSError, TypeError, ValueError, AttributeError):
        sentence = f"Could not read free space on {target}."
        return _warn(name, sentence)
    shown = f"{free / 1024**3:.1f} GiB free on {target}"
    if note:
        shown = f"{shown} ({note})"
    if free < DISK_WARN_BYTES:
        sentence = f"Free at least 1 GiB on {target} before rendering ({free / 1024**3:.1f} GiB free)."
        if note:
            sentence = sentence[:-1] + f"; {note}."
        return _warn(name, sentence)
    return Check(name, "pass", shown)


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


def _filter_names(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 3 and set(parts[0]) <= set("TSC.") and parts[1] != "=":
            names.add(parts[1])
    return names
