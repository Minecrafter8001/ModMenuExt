from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .mods import build_update_database_zip_url, ModInfo


@dataclass
class ModpackEntry:
    mod_id: str
    name: str
    github_url: str


def extract_modpack_github_url(mod: ModInfo) -> str:
    links = mod.links if isinstance(mod.links, dict) else {}
    github_ref = links.get("HEVLIB_GITHUB")
    if isinstance(github_ref, dict):
        return str(github_ref.get("URL", "")).strip()
    if isinstance(github_ref, str):
        return github_ref.strip()
    return ""


def _build_update_database_url(mod_id: str, update_entry: Any) -> str:
    if not isinstance(update_entry, dict):
        return ""
    file_name = str(update_entry.get("file_name", "")).strip()
    if not file_name:
        return ""
    try:
        major = int(update_entry.get("major", 0))
        minor = int(update_entry.get("minor", 0))
        bugfix = int(update_entry.get("bugfix", 0))
    except (TypeError, ValueError):
        return ""
    return build_update_database_zip_url(mod_id, major, minor, bugfix, file_name)


def build_export_modpack_payload(
    mods: list[ModInfo],
    update_database_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, dict[str, str]], list[str]]:
    payload: dict[str, dict[str, str]] = {}
    unsupported: list[str] = []
    index = update_database_index or {}

    for mod in mods:
        mod_id = mod.mod_id.strip()
        if not mod_id:
            unsupported.append(f"{mod.display_name}: missing mod id in manifest")
            continue

        update_repo_url = _build_update_database_url(mod_id, index.get(mod_id))
        github_url = update_repo_url or extract_modpack_github_url(mod)
        if not github_url:
            unsupported.append(f"{mod.display_name}: missing update-db entry and links/HEVLIB_GITHUB URL")
            continue

        payload[mod_id] = {
            "name": mod.display_name,
            "github_url": github_url,
        }

    return payload, unsupported


def write_modpack_file(path: Path, payload: dict[str, dict[str, str]]) -> None:
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def read_modpack_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_modpack_entries(payload: Any) -> tuple[list[ModpackEntry], list[str]]:
    if not isinstance(payload, dict):
        raise ValueError("Modpack file must contain a JSON object keyed by mod id.")

    importable: list[ModpackEntry] = []
    unsupported: list[str] = []
    for mod_id, value in payload.items():
        if not isinstance(mod_id, str) or not mod_id.strip():
            unsupported.append("<unknown id>: invalid mod id key")
            continue
        if not isinstance(value, dict):
            unsupported.append(f"{mod_id}: entry is not an object")
            continue

        github_url = str(value.get("github_url", "")).strip()
        name = str(value.get("name", mod_id)).strip() or mod_id

        importable.append(ModpackEntry(mod_id=mod_id.strip(), name=name, github_url=github_url))

    return importable, unsupported


def build_import_candidate_urls(
    entry: ModpackEntry,
    update_database_index: dict[str, dict[str, Any]] | None,
    repository_zip_url: str,
) -> list[str]:
    candidates: list[str] = []
    if entry.github_url:
        candidates.append(entry.github_url)

    update_repo_url = _build_update_database_url(entry.mod_id, (update_database_index or {}).get(entry.mod_id))
    if update_repo_url and update_repo_url not in candidates:
        candidates.append(update_repo_url)

    repo_url = repository_zip_url.strip()
    if repo_url and repo_url not in candidates:
        candidates.append(repo_url)

    return candidates
