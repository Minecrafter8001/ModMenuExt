from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
import zipfile

from .godot_variant import parse_variant


def load_archive_translations(archive_path) -> tuple[dict[str, dict[str, Any]], str]:
    if not zipfile.is_zipfile(archive_path):
        return {}, "en"

    with zipfile.ZipFile(archive_path) as archive:
        translation_entry = next(
            (name for name in archive.namelist() if PurePosixPath(name).name == "REPLACE_TRANSLATIONS.gd"),
            "",
        )
        if not translation_entry:
            return {}, "en"
        text = archive.read(translation_entry).decode("utf-8-sig", errors="replace")
        base_folder = PurePosixPath(translation_entry).parent
        translations = _extract_translation_dictionary(text)
        if not isinstance(translations, dict):
            return {}, "en"
        master_locale = str(translations.get("master_locale", "en"))
        merged = _normalize_translation_dict(translations)
        file_entries = translations.get("file", {})
        if isinstance(file_entries, dict):
            for relative_path, metadata in file_entries.items():
                delimiter = "|"
                if isinstance(metadata, str):
                    delimiter = metadata
                elif isinstance(metadata, dict):
                    delimiter = str(metadata.get("string", delimiter))
                csv_path = str((base_folder / str(relative_path)).as_posix())
                if csv_path in archive.namelist():
                    csv_text = archive.read(csv_path).decode("utf-8-sig", errors="replace")
                    parsed = parse_translation_csv(csv_text, delimiter)
                    for locale, strings in parsed.items():
                        merged.setdefault(locale, {}).update(strings)
        return merged, master_locale


def parse_translation_csv(text: str, delimiter: str = "|") -> dict[str, dict[str, str]]:
    lines = text.splitlines()
    if not lines:
        return {}
    header = lines[0].split(delimiter)
    if not header or header[0] != "locale" or len(header) <= 1:
        return {}
    languages = header[1:]
    dictionary = {language: {} for language in languages}
    for line in lines[1:]:
        if not line or line.startswith("#"):
            continue
        parts = line.split(delimiter)
        while len(parts) > 2:
            merged = False
            for index, part in enumerate(parts[:-1]):
                if part.endswith("\\"):
                    parts[index] = part.rstrip("\\") + delimiter + parts[index + 1]
                    del parts[index + 1]
                    merged = True
                    break
            if not merged:
                break
        if len(parts) <= 1 or len(parts) - 1 < len(languages):
            continue
        key = parts[0]
        for index, language in enumerate(languages):
            dictionary[language][key] = parts[index + 1]
    return dictionary


def resolve_translation_key(
    value: Any,
    translations: dict[str, dict[str, Any]],
    locale: str,
    master_locale: str = "en",
) -> str:
    if not isinstance(value, str) or not value:
        return "" if value is None else str(value)
    candidates = _build_locale_candidates(locale)
    for candidate in candidates:
        resolved = _resolve_from_locale(value, translations.get(candidate, {}))
        if resolved is not None:
            return resolved
    for candidate in _build_locale_candidates(master_locale):
        resolved = _resolve_from_locale(value, translations.get(candidate, {}))
        if resolved is not None:
            return resolved
    return value


def _resolve_from_locale(key: str, locale_data: dict[str, Any]) -> str | None:
    if key not in locale_data:
        return None
    value = locale_data[key]
    if isinstance(value, dict):
        string_value = value.get("string")
        return str(string_value) if string_value is not None else None
    return str(value)


def _build_locale_candidates(locale: str) -> list[str]:
    normalized = str(locale or "").replace("-", "_")
    candidates: list[str] = []
    for candidate in (normalized, normalized.split("_", 1)[0] if normalized else ""):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _normalize_translation_dict(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for locale, values in raw.items():
        if locale in {"master_locale", "file"}:
            continue
        if isinstance(values, dict):
            merged[str(locale)] = dict(values)
    return merged


def _extract_translation_dictionary(text: str) -> dict[str, Any]:
    marker = "const TRANSLATIONS"
    start = text.find(marker)
    if start == -1:
        return {}
    brace_start = text.find("{", start)
    if brace_start == -1:
        return {}
    depth = 0
    in_string = False
    escaped = False
    end = -1
    for index in range(brace_start, len(text)):
        current = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == '"':
                in_string = False
            continue
        if current == '"':
            in_string = True
            continue
        if current == "{":
            depth += 1
            continue
        if current == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end == -1:
        return {}
    parsed = parse_variant(text[brace_start:end])
    return parsed if isinstance(parsed, dict) else {}