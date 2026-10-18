from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import storage


def _registry_path(cfg: dict) -> Path:
    profile = str(cfg.get("active_game_profile_id") or "default")
    return storage.PROFILE_DATA_DIR / f"{profile}-imports.json"


def _source_key(cfg: dict) -> str:
    return os.path.normcase(str(Path(cfg["mods_source_dir"]).expanduser().resolve()))


def directory_mods(cfg: dict) -> set[str]:
    data = storage.load_json(_registry_path(cfg), {})
    sources = data.get("sources", {}) if isinstance(data, dict) else {}
    names = sources.get(_source_key(cfg), []) if isinstance(sources, dict) else []
    return {name.casefold() for name in names if isinstance(name, str) and Path(name).name == name} if isinstance(names, list) else set()


def register_directory_mod(cfg: dict, name: str) -> None:
    path = _registry_path(cfg)
    data = storage.load_json(path, {})
    if not isinstance(data, dict):
        data = {}
    sources = data.setdefault("sources", {})
    key = _source_key(cfg)
    names = sources.setdefault(key, [])
    if name.casefold() in {value.casefold() for value in names}:
        return
    names.append(name)
    data["version"] = 1
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="imports-", suffix=".json", dir=path.parent)
    os.close(handle)
    try:
        storage.save_json(Path(temporary), data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
