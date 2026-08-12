from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import shutil
import tempfile
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

from .godot_config import load_godot_config, truncate_section_key, write_godot_config
from .localization import load_archive_translations


@dataclass
class ModInfo:
    archive_path: Path
    enabled: bool
    manifest: dict[str, dict[str, Any]] = field(default_factory=dict)
    mod_id: str = ""
    name: str = ""
    description: str = ""
    author: str = ""
    version: str = ""
    links: dict[str, Any] = field(default_factory=dict)
    configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    manifest_url: str = ""
    master_locale: str = "en"
    translations: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.name or self.archive_path.name


@dataclass
class RepositoryMod:
    mod_id: str
    name: str
    author: str
    readme: str
    icon_url: str
    zip_url: str
    zip_name: str


def scan_mods(mods_dir: Path) -> list[ModInfo]:
    if not mods_dir.exists():
        return []
    mods: list[ModInfo] = []
    for entry in sorted(mods_dir.iterdir(), key=lambda path: path.name.casefold()):
        if entry.is_dir():
            continue
        lower_name = entry.name.casefold()
        if not lower_name.endswith((".zip", ".pck", ".zip.disabled", ".pck.disabled", ".disabled")):
            continue
        enabled = not lower_name.endswith(".disabled")
        manifest = _read_manifest_from_archive(entry)
        translations, master_locale = load_archive_translations(entry)
        mod_information = manifest.get("mod_information", {})
        version_info = manifest.get("version", {})
        mod = ModInfo(
            archive_path=entry,
            enabled=enabled,
            manifest=manifest,
            mod_id=str(mod_information.get("id", "")),
            name=str(mod_information.get("name", "")),
            description=str(mod_information.get("description", mod_information.get("brief", ""))),
            author=str(mod_information.get("author", "")),
            version=_format_version(version_info),
            links=dict(manifest.get("links", {})),
            configs=_normalize_configs(manifest.get("configs", {})),
            manifest_url=str(manifest.get("manifest_definitions", {}).get("manifest_url", "")),
            master_locale=master_locale,
            translations=translations,
        )
        if not mod.name:
            details = _read_mod_details(entry)
            mod.mod_id = mod.mod_id or details.get("MOD_ID", "")
            mod.name = details.get("MOD_NAME", entry.name)
        mods.append(mod)
    return mods


def toggle_mod(mod: ModInfo) -> Path:
    current = mod.archive_path
    if mod.enabled:
        target = current.with_name(current.name + ".disabled")
    else:
        target_name = current.name[:-9] if current.name.endswith(".disabled") else current.stem
        target = current.with_name(target_name)
    current.rename(target)
    return target


def load_runtime_config(config_path: Path) -> dict[str, dict[str, Any]]:
    return load_godot_config(config_path)


def save_runtime_value(config_path: Path, document: dict[str, dict[str, Any]], mod_id: str, section: str, key: str, value: Any) -> None:
    section_key = truncate_section_key(mod_id, section)
    document.setdefault(section_key, {})[key] = value
    write_godot_config(config_path, document)


def get_runtime_value(document: dict[str, dict[str, Any]], mod_id: str, section: str, key: str) -> Any:
    section_key = truncate_section_key(mod_id, section)
    return document.get(section_key, {}).get(key)


def install_mod_from_path(source: Path, mods_dir: Path) -> Path:
    mods_dir.mkdir(parents=True, exist_ok=True)
    target = mods_dir / source.name
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return target


def install_mod_from_url(url: str, mods_dir: Path) -> Path:
    download_url, filename = resolve_download_url(url)
    mods_dir.mkdir(parents=True, exist_ok=True)
    safe_name = filename or Path(urlparse(download_url).path).name or "downloaded_mod.zip"
    if not safe_name.casefold().endswith(".zip"):
        safe_name = f"{safe_name}.zip"
    target = mods_dir / safe_name
    request = Request(download_url, headers={"User-Agent": "ModMenuExt/0.1"})
    with urlopen(request) as response, tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temporary:
        shutil.copyfileobj(response, temporary)
        temporary_path = Path(temporary.name)
    temporary_path.replace(target)
    return target


def fetch_repository_catalog() -> list[RepositoryMod]:
    url = "https://raw.githubusercontent.com/rwqfsfasxc100/dv_update_database/refs/heads/main/github_fetcher_store/compiled_topic_store.json"
    request = Request(url, headers={"User-Agent": "ModMenuExt/0.1"})
    with urlopen(request) as response:
        payload = json.load(response)

    mods: list[RepositoryMod] = []
    if not isinstance(payload, dict):
        return mods

    for mod_id, item in payload.items():
        if not isinstance(item, dict):
            continue
        formatted = item.get("formatted", {})
        header = formatted.get("header_data", {}) if isinstance(formatted, dict) else {}
        mods.append(
            RepositoryMod(
                mod_id=str(header.get("MOD_ID", mod_id)),
                name=str(header.get("MOD_NAME", mod_id)),
                author=str(header.get("AUTHOR", "")),
                readme=str(formatted.get("readme", "")),
                icon_url=str(item.get("icon_path", "")),
                zip_url=str(item.get("zip_filename", "")),
                zip_name=str(header.get("MOD_ZIP_NAME", Path(str(item.get("zip_filename", "downloaded_mod.zip"))).name)),
            )
        )
    mods.sort(key=lambda entry: entry.name.casefold())
    return mods


def fetch_latest_manifest(manifest_url: str) -> dict[str, dict[str, Any]]:
    if not manifest_url:
        return {}
    request = Request(manifest_url, headers={"User-Agent": "ModMenuExt/0.1"})
    with urlopen(request) as response:
        text = response.read().decode("utf-8-sig", errors="replace")
    from .godot_config import parse_godot_config_text

    return parse_godot_config_text(text)


def compare_versions(current_version: str, latest_version: str) -> int:
    current_parts = _parse_version_string(current_version)
    latest_parts = _parse_version_string(latest_version)
    width = max(len(current_parts), len(latest_parts), 3)
    current_parts.extend([0] * (width - len(current_parts)))
    latest_parts.extend([0] * (width - len(latest_parts)))
    if current_parts < latest_parts:
        return -1
    if current_parts > latest_parts:
        return 1
    return 0


def _parse_version_string(value: str) -> list[int]:
    parts: list[int] = []
    for part in str(value).split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return parts


def resolve_download_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("download URL must start with http:// or https://")
    if parsed.netloc.casefold().endswith("github.com"):
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
            request = Request(api_url, headers={"User-Agent": "ModMenuExt/0.1", "Accept": "application/vnd.github+json"})
            with urlopen(request) as response:
                payload = json.load(response)
            assets = payload.get("assets", [])
            for asset in assets:
                asset_name = str(asset.get("name", ""))
                if asset_name.casefold().endswith(".zip") and "source code" not in asset_name.casefold():
                    return str(asset["browser_download_url"]), asset_name
            zipball = payload.get("zipball_url")
            if zipball:
                return str(zipball), f"{repo}-latest.zip"
    return url, Path(parsed.path).name


def _read_manifest_from_archive(archive_path: Path) -> dict[str, dict[str, Any]]:
    if not zipfile.is_zipfile(archive_path):
        return {}
    with zipfile.ZipFile(archive_path) as archive:
        manifest_name = next((name for name in archive.namelist() if name.casefold().endswith("mod.manifest")), "")
        if not manifest_name:
            return {}
        raw_bytes = archive.read(manifest_name)
    from .godot_config import parse_godot_config_text

    text = raw_bytes.decode("utf-8-sig", errors="replace")
    return parse_godot_config_text(text)


def _read_mod_details(archive_path: Path) -> dict[str, str]:
    if not zipfile.is_zipfile(archive_path):
        return {}
    with zipfile.ZipFile(archive_path) as archive:
        details_name = next((name for name in archive.namelist() if name.casefold().endswith("mod_details.txt")), "")
        if not details_name:
            return {}
        text = archive.read(details_name).decode("utf-8-sig", errors="replace")
    output: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(";") or "|" not in line:
            continue
        key, value = line[1:].split("|", 1)
        output[key.strip()] = value.strip()
    return output


def _normalize_configs(value: Any) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    if not isinstance(value, dict):
        return output
    for section_name, section_value in value.items():
        if isinstance(section_value, dict):
            output[str(section_name)] = {str(key): item for key, item in section_value.items() if isinstance(item, dict)}
    return output


def _format_version(version_info: dict[str, Any]) -> str:
    major = version_info.get("version_major")
    minor = version_info.get("version_minor")
    bugfix = version_info.get("version_bugfix")
    parts = [part for part in (major, minor, bugfix) if part is not None]
    return ".".join(str(part) for part in parts)
