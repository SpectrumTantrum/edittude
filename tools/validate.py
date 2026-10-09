#!/usr/bin/env python3
"""Check pack coverage and optional original-source provenance. Requires PyYAML."""

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

import yaml


def _check(condition, message):
    """assert, minus the -O switch that would turn every check below into a no-op."""
    if not condition:
        raise SystemExit(message)


def validate(pack, source=None):
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["skills"]
    count = len(entries)
    _check(count, "Manifest lists no skills")
    _check(len({entry["role"] for entry in entries}) == count, "Duplicate role")
    names = {entry["skill"] for entry in entries}
    _check(len(names) == count, "Duplicate skill")
    _check(names.issubset({p.parent.name for p in pack.glob("*/SKILL.md")}), "Missing mapped skill")

    for entry in entries:
        name = entry["skill"]
        content = (pack / name / "SKILL.md").read_text(encoding="utf-8")
        parts = content.split("---", 2)
        _check(len(parts) == 3 and not parts[0], f"{name}: missing frontmatter")
        meta = yaml.safe_load(parts[1])
        _check(meta["name"] == name, f"{name}: name differs from folder")
        _check(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) and len(name) <= 64,
               f"{name}: unusable skill name")
        _check(isinstance(meta["description"], str) and 0 < len(meta["description"]) <= 1024,
               f"{name}: unusable description")
        _check(not {"<", ">"}.intersection(meta["description"]), f"{name}: description markup")
        provenance = meta["metadata"]
        _check(provenance["source-role"] == entry["role"], f"{name}: wrong role")
        _check(provenance["source-path"] == entry["source_path"], f"{name}: wrong source")
        _check(provenance["source-revision"] == manifest["source_revision"],
               f"{name}: wrong source revision")
        _check(all(isinstance(value, str) for value in provenance.values()),
               f"{name}: non-string metadata")
        _check(parts[2].strip(), f"{name}: empty instructions")
        _check("[TODO:" not in content, f"{name}: unfinished scaffold")

        if source is not None:
            raw = (source / entry["source_path"]).read_bytes()
            _check(hashlib.sha256(raw).hexdigest() == entry["source_sha256"], f"{name}: source drift")
            classes = [node for node in ast.parse(raw).body if isinstance(node, ast.ClassDef)]
            role = next((node for node in classes if node.name == entry["role"]), None)
            _check(role is not None, f"{name}: original class missing")
            _check(any(isinstance(base, ast.Name) and base.id == "BaseTool" for base in role.bases),
                   f"{name}: original class is not a BaseTool")

    if source is not None:
        registry = json.loads((source / manifest["registry_path"]).read_text(encoding="utf-8"))
        mapped = {entry["role"]: entry["source_path"].removesuffix(".py").replace("/", ".") for entry in entries}
        _check(registry == mapped, "Pack does not map exactly to the original registry")

    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "skills",
                        help="Skill pack directory; defaults to the sibling skills folder")
    parser.add_argument("--source", type=Path, help="Original VideoAgent checkout, for source/hash checks")
    args = parser.parse_args()
    count = validate(args.skills_dir.expanduser().resolve(), args.source)
    print(f"Validated {count} skills" + (" against original source" if args.source else ""))
