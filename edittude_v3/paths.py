from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIRNAME = "edittude"
LEGACY_CONFIG_DIRNAME = "edittude-v3"
STATE_DIRNAME = ".edittude"
LEGACY_STATE_DIRNAME = ".edittude-v3"


def install_root() -> Path:
    """Checkout that holds skills/ and tools/."""
    override = os.environ.get("EDITTUDE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return PACKAGE_ROOT


def config_home() -> Path:
    """User config directory. The API key lives here, not in the project folder.

    Default is ~/.config/edittude. EDITTUDE_CONFIG_HOME replaces that entirely.
    An older ~/.config/edittude-v3/.env is copied in on first use; see
    adopt_legacy_config() in agent.py. The old directory is left in place.
    """
    override = os.environ.get("EDITTUDE_CONFIG_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".config" / CONFIG_DIRNAME


def legacy_config_home() -> Path | None:
    """Previous config directory, when it is not the active one.

    EDITTUDE_CONFIG_HOME pins a single directory, so the legacy path is ignored.
    """
    if os.environ.get("EDITTUDE_CONFIG_HOME"):
        return None
    legacy = Path.home() / ".config" / LEGACY_CONFIG_DIRNAME
    if legacy.resolve() == config_home().resolve():
        return None
    return legacy


def env_file() -> Path:
    return config_home() / ".env"


def legacy_env_file() -> Path | None:
    home = legacy_config_home()
    if home is None:
        return None
    return home / ".env"


def state_dir(workspace: Path) -> Path:
    """Per-project scratch: TUI history, offloaded conversation history, media.

    New projects use .edittude/. A project that already has .edittude-v3/ keeps
    using it, so history is not split across two folders.
    """
    root = workspace.expanduser().resolve()
    preferred = root / STATE_DIRNAME
    legacy = root / LEGACY_STATE_DIRNAME
    if preferred.is_dir():
        path = preferred
    elif legacy.is_dir():
        path = legacy
    else:
        path = preferred
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SystemExit(f"cannot create {path}: {exc.strerror}") from None
    return path


def unique_existing_dirs(*candidates: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate.expanduser().resolve()
        if not path.is_dir() or path in seen:
            continue
        found.append(path)
        seen.add(path)
    return found
