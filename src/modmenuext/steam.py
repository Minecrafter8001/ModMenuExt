from __future__ import annotations

from pathlib import Path
import os
import platform
import re
from typing import Any


def parse_vdf(text: str) -> dict[str, Any]:
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|\{|\}', text)
    position = 0

    def parse_object() -> dict[str, Any]:
        nonlocal position
        output: dict[str, Any] = {}
        while position < len(tokens):
            token = tokens[position]
            if token == "}":
                position += 1
                break
            key = _unquote(token)
            position += 1
            if position >= len(tokens):
                break
            next_token = tokens[position]
            if next_token == "{":
                position += 1
                output[key] = parse_object()
            else:
                output[key] = _unquote(next_token)
                position += 1
        return output

    root = parse_object()
    return root


def discover_steam_root() -> Path | None:
    system = platform.system()
    home = Path.home()
    if system == "Windows":
        candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Steam",
            Path(os.environ.get("PROGRAMFILES", "")) / "Steam",
            home / "AppData" / "Local" / "Steam",
        ]
    elif system == "Linux":
        candidates = [
            home / ".local" / "share" / "Steam",
            home / ".steam" / "steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
        ]
    else:
        candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Steam",
            Path(os.environ.get("PROGRAMFILES", "")) / "Steam",
            home / ".local" / "share" / "Steam",
            home / ".steam" / "steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
            home / "AppData" / "Local" / "Steam",
        ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "steamapps").exists():
            return candidate
    return None


def discover_steam_libraries(steam_root: Path | None = None) -> list[Path]:
    root = steam_root or discover_steam_root()
    if root is None:
        return []

    libraries = [root]
    library_file = root / "steamapps" / "libraryfolders.vdf"
    if not library_file.exists():
        return libraries

    try:
        parsed = parse_vdf(library_file.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return libraries

    library_data = parsed.get("libraryfolders", parsed)
    for value in library_data.values():
        if isinstance(value, dict):
            path_value = value.get("path")
            if path_value:
                candidate = Path(path_value)
                if candidate.exists() and candidate not in libraries:
                    libraries.append(candidate)
    return libraries


def discover_delta_v_install() -> Path | None:
    for library in discover_steam_libraries():
        steamapps = library / "steamapps"
        manifests = sorted(steamapps.glob("appmanifest_*.acf"))
        for manifest_path in manifests:
            try:
                parsed = parse_vdf(manifest_path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            app_state = parsed.get("AppState", parsed)
            name = str(app_state.get("name", ""))
            install_dir = str(app_state.get("installdir", ""))
            normalized = name.casefold()
            if "rings of saturn" in normalized or "delta-v" in normalized or install_dir.casefold() == "delta-v":
                candidate = steamapps / "common" / install_dir
                if candidate.exists():
                    return candidate

        for fallback in (steamapps / "common").glob("*Delta*V*"):
            if fallback.is_dir():
                return fallback
    return None


def discover_delta_v_user_dir() -> Path | None:
    system = platform.system()
    home = Path.home()
    roaming = Path(os.environ.get("APPDATA", ""))
    local = Path(os.environ.get("LOCALAPPDATA", ""))

    if system == "Windows":
        candidates = [
            roaming / "dV",
            roaming / "Godot" / "app_userdata" / "dV",
            roaming / "Godot" / "app_userdata" / "Delta-V",
            local / "dV",
        ]
    elif system == "Linux":
        candidates = [
            home / ".local" / "share" / "dV",
            home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "dV",
        ]
    else:
        candidates = [
            roaming / "dV",
            home / ".local" / "share" / "dV",
            home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "dV",
            roaming / "Godot" / "app_userdata" / "dV",
            roaming / "Godot" / "app_userdata" / "Delta-V",
            local / "dV",
        ]

    for candidate in candidates:
        if (candidate / "cfg").exists() or (candidate / "savegame.dv").exists():
            return candidate
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def discover_game_executable(game_dir: Path) -> Path | None:
    preferred = [
        game_dir / "Delta-V.exe",
        game_dir / "delta-v.exe",
        game_dir / "Delta-V.x86_64",
        game_dir / "delta-v.x86_64",
        game_dir / "Delta-V",
        game_dir / "delta-v",
    ]
    for candidate in preferred:
        if candidate.exists():
            return candidate
    executable_patterns = ["*.exe", "*.x86_64"]
    for pattern in executable_patterns:
        executables = list(game_dir.glob(pattern))
        if executables:
            return executables[0]
    return None


def _unquote(token: str) -> str:
    if token.startswith('"') and token.endswith('"'):
        return bytes(token[1:-1], "utf-8").decode("unicode_escape")
    return token
