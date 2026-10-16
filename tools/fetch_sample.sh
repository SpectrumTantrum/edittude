#!/usr/bin/env bash
# Download the day-out sample pack listed in tools/samples.json.
# Checks the HTTP body size and sha256, deletes a body that does not match,
# and unpacks archive_member when a clip is zipped. Tries the primary url,
# then https://github.com/SpectrumTantrum/edittude/releases/download/samples-v1/<basename>.
# That release is only a fallback. This script does not create it.
# Files already on disk with the right sha are left in place.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/tools/samples.json"
PACK="$ROOT/samples/day-out"
MIRROR="https://github.com/SpectrumTantrum/edittude/releases/download/samples-v1"
UA="edittude-fetch-sample/1.0"

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

[[ -f "$MANIFEST" ]] || die "missing $MANIFEST"
command -v curl >/dev/null 2>&1 || die "curl is not on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 is not on PATH"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is not on PATH"

mkdir -p "$PACK/.fetch"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

body_ok() {
  local path="$1" sha="$2" size="$3"
  local actual_size actual_sha
  [[ -f "$path" ]] || return 1
  actual_size="$(stat -c%s "$path")"
  actual_sha="$(sha256sum "$path" | awk 'NR==1 {print $1}')"
  [[ "$actual_size" == "$size" && "$actual_sha" == "$sha" ]]
}

extract_member() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import os
import shutil
import sys
import zipfile

zip_path, member, expected, dest = sys.argv[1:5]
expected = int(expected)
if not member or member.startswith("/") or ".." in member.split("/"):
    sys.exit(f"refusing archive member {member!r}")
with zipfile.ZipFile(zip_path) as archive:
    try:
        info = archive.getinfo(member)
    except KeyError:
        sys.exit(f"archive missing {member}")
    if info.file_size != expected:
        sys.exit(f"archive member {member} is {info.file_size} bytes, want {expected}")
    with archive.open(info, "r") as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out)
written = os.path.getsize(dest)
if written != expected:
    sys.exit(f"unpacked {member} is {written} bytes, want {expected}")
PY
}

list="$tmpdir/clips.tsv"
python3 - "$MANIFEST" >"$list" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
clips = data.get("clips")
if not isinstance(clips, list) or not clips:
    sys.exit("samples.json has no clips")
for clip in clips:
    member = clip.get("archive_member") or ""
    member_size = clip.get("archive_member_size") or ""
    if member and not str(member_size):
        sys.exit(f"{clip.get('file')}: archive_member without archive_member_size")
    fields = [
        str(clip["file"]),
        str(clip["url"]),
        str(clip["sha256"]),
        str(clip["size"]),
        str(member),
        str(member_size),
    ]
    if any("\t" in field or "\n" in field for field in fields):
        sys.exit(f"{clip.get('file')}: field contains a tab or newline")
    print("\t".join(fields))
PY

fetched=0
skipped=0

while IFS=$'\t' read -r rel url sha size member member_size; do
  [[ -n "${rel:-}" ]] || continue
  case "$rel" in
    samples/day-out/*) ;;
    *) die "refusing path outside samples/day-out: $rel" ;;
  esac
  case "$url" in
    https://*) ;;
    *) die "refusing non-https url for $rel" ;;
  esac
  [[ "$sha" =~ ^[0-9a-f]{64}$ ]] || die "bad sha256 for $rel"
  dest="$ROOT/$rel"
  base="${url##*/}"
  [[ -n "$base" && "$base" != */* ]] || die "bad basename for $url"
  cache="$PACK/.fetch/$base"
  mkdir -p "$(dirname "$dest")"

  if [[ -n "$member" && -f "$cache" ]] && body_ok "$cache" "$sha" "$size"; then
    if [[ -f "$dest" && "$(stat -c%s "$dest")" == "$member_size" ]]; then
      printf 'skip %s (sha256 ok)\n' "$rel"
      skipped=$((skipped + 1))
      continue
    fi
    printf 'unpacking %s from verified cache\n' "$rel"
    rm -f "$dest"
    if extract_member "$cache" "$member" "$member_size" "$dest"; then
      skipped=$((skipped + 1))
      continue
    fi
    printf 'refusing %s: archive member check failed; deleted\n' "$rel" >&2
    rm -f "$dest" "$cache"
  elif [[ -z "$member" && -f "$dest" ]] && body_ok "$dest" "$sha" "$size"; then
    printf 'skip %s (sha256 ok)\n' "$rel"
    skipped=$((skipped + 1))
    continue
  fi

  if [[ -f "$dest" && -z "$member" ]]; then
    printf 'refusing %s: size or sha256 mismatch; deleted\n' "$rel" >&2
    rm -f "$dest"
  fi
  if [[ -f "$cache" ]] && ! body_ok "$cache" "$sha" "$size"; then
    printf 'refusing %s: size or sha256 mismatch; deleted\n' "$cache" >&2
    rm -f "$cache"
  fi

  ok=0
  for host in "$url" "$MIRROR/$base"; do
    tmp="$tmpdir/body-$base"
    rm -f "$tmp"
    if ! curl -fsSL --retry 3 --retry-delay 1 --connect-timeout 20 --max-time 600 \
      -A "$UA" -o "$tmp" "$host"; then
      printf 'fetch failed %s\n' "$host" >&2
      rm -f "$tmp"
      continue
    fi
    if ! body_ok "$tmp" "$sha" "$size"; then
      printf 'refusing %s: size or sha256 mismatch; deleted\n' "$host" >&2
      rm -f "$tmp"
      continue
    fi
    if [[ -n "$member" ]]; then
      part="$tmpdir/member-$base"
      rm -f "$part" "$dest"
      if ! extract_member "$tmp" "$member" "$member_size" "$part"; then
        printf 'refusing %s: archive member check failed; deleted\n' "$host" >&2
        rm -f "$tmp" "$part" "$dest"
        continue
      fi
      mv -f "$part" "$dest"
      mv -f "$tmp" "$cache"
    else
      mv -f "$tmp" "$dest"
    fi
    printf 'fetched %s from %s\n' "$rel" "$host"
    ok=1
    fetched=$((fetched + 1))
    break
  done
  [[ "$ok" == 1 ]] || die "could not fetch $rel"
done <"$list"

printf 'done: fetched %s, skipped %s\n' "$fetched" "$skipped"
