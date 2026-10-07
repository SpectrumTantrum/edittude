#!/usr/bin/env bash
# Install edittude and put it on PATH.
#
#   curl -LsSf https://raw.githubusercontent.com/SpectrumTantrum/edittude/main/install.sh | bash
#
# From a checkout:
#
#   ./install.sh
#   ./install.sh update [--force]
#   ./install.sh --with-models[=asr,separation]
#
# Optional environment:
#   EDITTUDE_REPO         git URL to clone when this script is not next to pyproject.toml
#   EDITTUDE_REF          branch or tag (default: main)
#   EDITTUDE_HOME         clone destination (default: ~/.local/share/edittude)
#                         an existing ~/.local/share/edittude-v3 checkout is kept
#   EDITTUDE_CONFIG_HOME  API key / config directory (default: ~/.config/edittude)
#                         an existing ~/.config/edittude-v3/.env is copied once
#   EDITTUDE_BIN          launcher directory (default: ~/.local/bin)
#   EDITTUDE_PYTHON       Python version for uv (default: 3.13)

set -euo pipefail

REPO="${EDITTUDE_REPO:-https://github.com/SpectrumTantrum/edittude.git}"
REF="${EDITTUDE_REF:-main}"
BIN_DIR="${EDITTUDE_BIN:-${HOME}/.local/bin}"
PYTHON_VERSION="${EDITTUDE_PYTHON:-3.13}"

bold=""
reset=""
red=""
green=""
dim=""
if [ -t 1 ]; then
  bold="$(printf '\033[1m')"
  reset="$(printf '\033[0m')"
  red="$(printf '\033[31m')"
  green="$(printf '\033[32m')"
  dim="$(printf '\033[2m')"
fi

log() { printf '%s\n' "$*"; }
info() { printf '%sinfo%s %s\n' "$dim" "$reset" "$*" >&2; }
ok() { printf '%sok%s   %s\n' "$green" "$reset" "$*" >&2; }
die() { printf '%serror%s %s\n' "$red" "$reset" "$*" >&2; exit 1; }

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "Missing $1. Install it and run this again."
  fi
}

is_edittude_checkout() {
  [ -f "$1/pyproject.toml" ] && grep -Eq '^name = "edittude(-v3)?"$' "$1/pyproject.toml"
}

script_dir() {
  local source="${BASH_SOURCE[0]:-}"
  if [ -z "$source" ] || [ ! -f "$source" ]; then
    return 1
  fi
  local dir
  dir="$(cd "$(dirname "$source")" && pwd)"
  if is_edittude_checkout "$dir"; then
    printf '%s\n' "$dir"
    return 0
  fi
  return 1
}

find_uv() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi
  if [ -x "${HOME}/.local/bin/uv" ]; then
    printf '%s\n' "${HOME}/.local/bin/uv"
    return 0
  fi
  return 1
}

install_uv() {
  local uv_bin
  if uv_bin="$(find_uv)"; then
    info "uv already installed ($uv_bin)"
    printf '%s\n' "$uv_bin"
    return 0
  fi
  info "Installing uv"
  # This function's stdout is the uv path, so the installer's chatter goes to stderr.
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh >&2
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh >&2
  else
    die "Need curl or wget to install uv."
  fi
  if uv_bin="$(find_uv)"; then
    printf '%s\n' "$uv_bin"
    return 0
  fi
  die "uv installed but is not on PATH. Open a new shell or add ${HOME}/.local/bin to PATH."
}

update_checkout() {
  local dir="$1"
  local force="${2:-0}"
  need_cmd git
  if [ ! -d "${dir}/.git" ]; then
    die "${dir} is not a git checkout. Re-run the installer."
  fi
  if [ "$force" -eq 0 ] && [ -n "$(git -C "$dir" status --porcelain)" ]; then
    die "${dir} has local changes. Commit them, or run: edittude update --force"
  fi
  info "Updating ${dir}"
  git -C "$dir" fetch --depth 1 origin "$REF" >&2
  git -C "$dir" checkout --force -B "$REF" "FETCH_HEAD" >&2
}

choose_prefix() {
  if [ -n "${EDITTUDE_HOME:-}" ]; then
    printf '%s\n' "$EDITTUDE_HOME"
    return 0
  fi
  local preferred="${HOME}/.local/share/edittude"
  local legacy="${HOME}/.local/share/edittude-v3"
  if is_edittude_checkout "$preferred"; then
    printf '%s\n' "$preferred"
    return 0
  fi
  if is_edittude_checkout "$legacy"; then
    printf '%s\n' "$legacy"
    return 0
  fi
  printf '%s\n' "$preferred"
}

resolve_prefix() {
  local checkout
  if checkout="$(script_dir)"; then
    if [ "$UPDATE" -eq 1 ]; then
      update_checkout "$checkout" "$FORCE"
    fi
    printf '%s\n' "$checkout"
    return 0
  fi
  if [ "$UPDATE" -eq 1 ]; then
    if is_edittude_checkout "$PREFIX"; then
      update_checkout "$PREFIX" "$FORCE"
      printf '%s\n' "$PREFIX"
      return 0
    fi
    die "No edittude install at ${PREFIX}. Run the installer first."
  fi
  need_cmd git
  if is_edittude_checkout "$PREFIX"; then
    if [ -d "${PREFIX}/.git" ]; then
      update_checkout "$PREFIX" "$FORCE"
    else
      info "Using existing checkout ${PREFIX}"
    fi
    printf '%s\n' "$PREFIX"
    return 0
  fi
  if [ -e "$PREFIX" ] && [ ! -d "$PREFIX" ]; then
    die "${PREFIX} exists and is not a directory."
  fi
  if [ -d "$PREFIX" ] && [ -n "$(ls -A "$PREFIX" 2>/dev/null)" ]; then
    die "${PREFIX} exists and is not an edittude checkout. Set EDITTUDE_HOME to an empty directory."
  fi
  info "Cloning ${REPO} (${REF}) into ${PREFIX}"
  mkdir -p "$(dirname "$PREFIX")"
  if ! git clone --depth 1 --branch "$REF" "$REPO" "$PREFIX"; then
    die "Clone failed. Publish the repo, or run ./install.sh from a checkout. Override the URL with EDITTUDE_REPO."
  fi
  printf '%s\n' "$PREFIX"
}

LAUNCHER_MARKER="# generated by edittude/install.sh"
LEGACY_LAUNCHER_MARKER="# generated by edittude-v3/install.sh"

launcher_is_ours() {
  local target="$1"
  grep -qxF "$LAUNCHER_MARKER" "$target" 2>/dev/null && return 0
  grep -qxF "$LEGACY_LAUNCHER_MARKER" "$target" 2>/dev/null && return 0
  return 1
}

write_launcher() {
  local name="$1"
  local target="${BIN_DIR}/${name}"
  mkdir -p "$BIN_DIR"
  # A bare > writes through a symlink, so refuse anything that is not one of ours,
  # then unlink rather than overwrite.
  if [ -e "$target" ] || [ -L "$target" ]; then
    launcher_is_ours "$target" ||
      die "${target} exists and was not written by this installer. Remove it, or set EDITTUDE_BIN to another directory."
    rm -f "$target"
  fi
  cat >"$target" <<EOF
#!/bin/sh
${LAUNCHER_MARKER}
set -e
export EDITTUDE_ROOT="${PREFIX}"
if command -v uv >/dev/null 2>&1; then
  UV="\$(command -v uv)"
elif [ -x "\${HOME}/.local/bin/uv" ]; then
  UV="\${HOME}/.local/bin/uv"
else
  echo "uv is missing. Re-run the edittude installer." >&2
  exit 1
fi
exec "\$UV" run --project "${PREFIX}" ${name} "\$@"
EOF
  chmod +x "$target"
}

path_contains() {
  case ":${PATH}:" in
    *":${1}:"*) return 0 ;;
    *) return 1 ;;
  esac
}

UPDATE=0
FORCE=0
WITH_MODELS=""
if [ "${EDITTUDE_UPDATE:-}" = "1" ]; then
  UPDATE=1
fi
if [ "${EDITTUDE_FORCE:-}" = "1" ]; then
  FORCE=1
fi
while [ $# -gt 0 ]; do
  case "$1" in
    update) UPDATE=1 ;;
    --force) FORCE=1 ;;
    --with-models) WITH_MODELS="asr,separation" ;;
    --with-models=*) WITH_MODELS="${1#*=}" ;;
    -h|--help)
      log "Usage: install.sh [update] [--force] [--with-models[=LIST]]"
      log "  --with-models[=LIST]  also install the neural backends (default: asr,separation)"
      log "                        about 2.7 GB: torch runtime plus pinned weights"
      log "                        LIST names: asr, separation, seed-vc, diffsinger"
      log "                        seed-vc (GPL-3.0, ~2.5 GB) and diffsinger (non-commercial"
      log "                        checkpoint, ~0.5 GB) are opt-in only"
      exit 0
      ;;
    *) die "Unknown argument: $1. Try: ./install.sh or ./install.sh update" ;;
  esac
  shift
done

if [ "$(id -u)" -eq 0 ]; then
  die "Do not install edittude as root."
fi

log "${bold}edittude${reset}"
PREFIX="$(choose_prefix)"
PREFIX="$(resolve_prefix)"
UV_BIN="$(install_uv)"

if [ "${EDITTUDE_SKIP_SYNC:-}" != "1" ]; then
  info "Syncing Python ${PYTHON_VERSION} dependencies in ${PREFIX}"
  "$UV_BIN" sync --python "$PYTHON_VERSION" --project "$PREFIX"
fi

if [ -n "$WITH_MODELS" ]; then
  info "Installing neural backends (${WITH_MODELS}); this downloads a few GB"
  EDITTUDE_ROOT="$PREFIX" "$UV_BIN" run --project "$PREFIX" \
    edittude-media models install --models "$WITH_MODELS"
fi

CONFIG_HOME="${EDITTUDE_CONFIG_HOME:-${HOME}/.config/edittude}"
LEGACY_CONFIG="${HOME}/.config/edittude-v3"
if [ ! -f "${CONFIG_HOME}/.env" ]; then
  mkdir -p "${CONFIG_HOME}"
  if [ -z "${EDITTUDE_CONFIG_HOME:-}" ] && [ -f "${LEGACY_CONFIG}/.env" ]; then
    cp "${LEGACY_CONFIG}/.env" "${CONFIG_HOME}/.env"
    info "Copied config from ${LEGACY_CONFIG}"
  elif [ -f "${PREFIX}/.env.example" ]; then
    cp "${PREFIX}/.env.example" "${CONFIG_HOME}/.env"
  else
    printf 'DEEPSEEK_API_KEY=\n' > "${CONFIG_HOME}/.env"
  fi
  chmod 600 "${CONFIG_HOME}/.env"
  info "Wrote ${CONFIG_HOME}/.env"
fi

write_launcher edittude
write_launcher edittude-v3
write_launcher edittude-media
ok "Launchers in ${BIN_DIR}"

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  log "ffmpeg and ffprobe are not on PATH. Install them before you cut."
  if command -v brew >/dev/null 2>&1; then
    log "  brew install ffmpeg"
  else
    log "  https://ffmpeg.org/download.html"
  fi
fi

if ! path_contains "$BIN_DIR"; then
  log "Add this to your shell profile, then open a new terminal:"
  log "  export PATH=\"${BIN_DIR}:\$PATH\""
fi

if [ "$UPDATE" -eq 1 ]; then
  ok "Updated ${PREFIX}"
  log "  edittude --version"
  exit 0
fi

ok "Installed."
log
log "  edittude"
log "  edittude ask \"make a cut from /path/to/footage\""
log "  edittude update"
log
log "edittude-v3 still runs the same command."
log "First launch asks for a DeepSeek key (https://platform.deepseek.com)."
