from __future__ import annotations

from pathlib import Path
from typing import Any

from .godot_variant import parse_variant, serialize_variant


def truncate_mod_id(mod_id: str) -> str:
    return mod_id.replace("/", "").replace(" ", "")


def truncate_section(section: str) -> str:
    return section.replace("/", "")


def truncate_section_key(mod_id: str, section: str) -> str:
    return f"{truncate_mod_id(mod_id)}/{truncate_section(section)}"


def parse_godot_config_text(text: str) -> dict[str, dict[str, Any]]:
    sections: dict[str, dict[str, Any]] = {}
    current_section: str | None = None
    lines = text.splitlines()
    index = 0

    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(";") or stripped.startswith("#"):
            index += 1
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].strip()
            sections.setdefault(current_section, {})
            index += 1
            continue
        if current_section is None or "=" not in raw_line:
            index += 1
            continue

        key, value_start = raw_line.split("=", 1)
        value_lines = [value_start.strip()]
        while True:
            candidate = "\n".join(value_lines).strip()
            if _looks_complete(candidate):
                value = parse_variant(candidate)
                sections[current_section][key.strip()] = value
                break
            index += 1
            if index >= len(lines):
                raise ValueError(f"unterminated value for {key.strip()!r} in section {current_section!r}")
            value_lines.append(lines[index].rstrip())
        index += 1

    return sections


def load_godot_config(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return parse_godot_config_text(path.read_text(encoding="utf-8-sig"))


def write_godot_config(path: Path, sections: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[str] = []
    for section_name, values in sections.items():
        chunks.append(f"[{section_name}]")
        for key, value in values.items():
            chunks.append(f"{key}={serialize_variant(value)}")
        chunks.append("")
    path.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")


def _looks_complete(text: str) -> bool:
    if not text:
        return False

    depth = 0
    in_string = False
    escaped = False
    opening = {"[": "]", "{": "}", "(": ")"}
    closing = {value: key for key, value in opening.items()}
    stack: list[str] = []

    for current in text:
        if in_string:
            if escaped:
                escaped = False
                continue
            if current == "\\":
                escaped = True
                continue
            if current == '"':
                in_string = False
            continue
        if current == '"':
            in_string = True
            continue
        if current in opening:
            stack.append(current)
            depth += 1
            continue
        if current in closing:
            if not stack or stack[-1] != closing[current]:
                return True
            stack.pop()
            depth -= 1
    return not in_string and depth == 0
