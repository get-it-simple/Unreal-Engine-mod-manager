from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from app_paths import CONFIG_PATH, PRESETS_PATH, LABELS_PATH, PROFILE_DATA_DIR, DEFAULT_CONFIG

GAME_PROFILE_KEYS = ("game_mods_dir", "mods_source_dir", "mod_extensions", "mod_recursive_scan", "link_prefix")

def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_config() -> Dict:
    cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG.copy())
    for key, val in DEFAULT_CONFIG.items():
        cfg.setdefault(key, val)
    cfg = normalize_game_profiles(cfg)
    return cfg

def save_config(cfg: Dict) -> None:
    active_id = str(cfg.get("active_game_profile_id") or "")
    for profile in cfg.get("game_profiles", []) or []:
        if isinstance(profile, dict) and profile.get("id") == active_id:
            for key in GAME_PROFILE_KEYS:
                if key in cfg:
                    profile[key] = cfg.get(key, "")
            break
    cfg = normalize_game_profiles(dict(cfg))
    save_json(CONFIG_PATH, cfg)

def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")

def profile_id_for(name: str, created_at: str) -> str:
    raw = f"{name.strip()}|{created_at.strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]

def game_abbreviation(name: str) -> str:
    words = [part for part in "".join(ch if ch.isalnum() else " " for ch in name).split() if part]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    if words:
        return words[0][:2].upper()
    return "??"

def _profile_from_legacy(cfg: Dict) -> Dict | None:
    if not any(str(cfg.get(key) or "").strip() for key in GAME_PROFILE_KEYS):
        return None
    name = str(cfg.get("game_name") or "Default game").strip() or "Default game"
    created_at = str(cfg.get("game_profile_created_at") or _now_iso())
    profile = {
        "id": profile_id_for(name, created_at),
        "name": name,
        "created_at": created_at,
    }
    for key in GAME_PROFILE_KEYS:
        profile[key] = cfg.get(key, "")
    return profile

def normalize_game_profiles(cfg: Dict) -> Dict:
    profiles = [p for p in cfg.get("game_profiles", []) if isinstance(p, dict)]
    normalized = []
    seen = set()
    for profile in profiles:
        name = str(profile.get("name") or "Game").strip() or "Game"
        created_at = str(profile.get("created_at") or _now_iso())
        profile_id = str(profile.get("id") or profile_id_for(name, created_at))
        if profile_id in seen:
            created_at = _now_iso()
            profile_id = profile_id_for(name, created_at)
        seen.add(profile_id)
        item = {"id": profile_id, "name": name, "created_at": created_at}
        for key in GAME_PROFILE_KEYS:
            item[key] = profile.get(key, "")
        normalized.append(item)

    if not normalized:
        legacy = _profile_from_legacy(cfg)
        if legacy:
            normalized.append(legacy)

    active_id = str(cfg.get("active_game_profile_id") or "")
    if normalized and not any(p["id"] == active_id for p in normalized):
        active_id = normalized[0]["id"]
    if not normalized:
        active_id = ""

    cfg["game_profiles"] = normalized
    cfg["active_game_profile_id"] = active_id
    active = active_game_profile(cfg)
    if active:
        for key in GAME_PROFILE_KEYS:
            cfg[key] = active.get(key, "")
    return cfg

def active_game_profile(cfg: Dict | None = None) -> Dict | None:
    if cfg is None:
        cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG.copy())
    active_id = str(cfg.get("active_game_profile_id") or "")
    for profile in cfg.get("game_profiles", []) or []:
        if isinstance(profile, dict) and profile.get("id") == active_id:
            return profile
    profiles = cfg.get("game_profiles", []) or []
    return profiles[0] if profiles else None

def create_game_profile(name: str, values: Dict | None = None, cfg: Dict | None = None) -> Dict:
    values = values or {}
    created_at = str(values.get("created_at") or _now_iso())
    profile = {
        "id": profile_id_for(name, created_at),
        "name": str(name or "Game").strip() or "Game",
        "created_at": created_at,
    }
    for key in GAME_PROFILE_KEYS:
        profile[key] = values.get(key, "")
    if cfg is not None:
        cfg.setdefault("game_profiles", []).append(profile)
        cfg["active_game_profile_id"] = profile["id"]
        normalize_game_profiles(cfg)
    return profile

def update_game_profile(cfg: Dict, profile_id: str, values: Dict) -> bool:
    for profile in cfg.get("game_profiles", []):
        if profile.get("id") == profile_id:
            if "name" in values:
                profile["name"] = str(values.get("name") or "Game").strip() or "Game"
            for key in GAME_PROFILE_KEYS:
                if key in values:
                    profile[key] = values[key]
            normalize_game_profiles(cfg)
            return True
    return False

def set_active_game_profile(cfg: Dict, profile_id: str) -> bool:
    if any(profile.get("id") == profile_id for profile in cfg.get("game_profiles", [])):
        cfg["active_game_profile_id"] = profile_id
        normalize_game_profiles(cfg)
        return True
    return False

def delete_game_profile(cfg: Dict, profile_id: str) -> bool:
    profiles = cfg.get("game_profiles", [])
    kept = [profile for profile in profiles if profile.get("id") != profile_id]
    if len(kept) == len(profiles):
        return False
    cfg["game_profiles"] = kept
    if cfg.get("active_game_profile_id") == profile_id:
        cfg["active_game_profile_id"] = kept[0]["id"] if kept else ""
    normalize_game_profiles(cfg)
    return True

def _active_profile_context(base_path: Path) -> tuple[Path, Dict | None, Dict]:
    raw = load_json(CONFIG_PATH, DEFAULT_CONFIG.copy())
    raw = normalize_game_profiles(raw)
    profile = active_game_profile(raw)
    if not profile:
        return base_path, None, raw
    PROFILE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILE_DATA_DIR / f"{profile['id']}-{base_path.name}", profile, raw

def _active_profile_data_path(base_path: Path) -> Path:
    path, _profile, _cfg = _active_profile_context(base_path)
    return path

def _is_first_profile(profile: Dict | None, cfg: Dict) -> bool:
    profiles = cfg.get("game_profiles", []) or []
    return bool(profile and profiles and profiles[0].get("id") == profile.get("id"))

def _merge_legacy_records(profile_data, legacy_data):
    if not isinstance(profile_data, dict) or not isinstance(legacy_data, dict):
        return profile_data
    merged = dict(profile_data)
    changed = False
    for name, legacy_value in legacy_data.items():
        current = merged.get(name)
        if current is None:
            merged[name] = legacy_value
            changed = True
        elif isinstance(current, dict) and isinstance(legacy_value, dict):
            legacy_label = legacy_value.get("label")
            if legacy_label and not current.get("label"):
                current = dict(current)
                current["label"] = legacy_label
                current.setdefault("last_managed", legacy_value.get("last_managed"))
                current.setdefault("state", legacy_value.get("state", "undefined"))
                merged[name] = current
                changed = True
        elif isinstance(current, dict) and legacy_value and not current.get("label"):
            current = dict(current)
            current["label"] = legacy_value
            merged[name] = current
            changed = True
    return merged if changed else profile_data

def _load_profile_json(base_path: Path, default):
    path, profile, cfg = _active_profile_context(base_path)
    if path != base_path and not path.exists() and base_path.exists():
        data = load_json(base_path, default)
        save_json(path, data)
        return data
    data = load_json(path, default)
    if path != base_path and base_path.exists() and _is_first_profile(profile, cfg):
        merged = _merge_legacy_records(data, load_json(base_path, default))
        if merged is not data:
            save_json(path, merged)
            return merged
    return data

def load_presets() -> Dict[str, List[str]]:
    records = load_preset_records()
    return {name: rec.get("mods", []) for name, rec in records.items()}

def save_presets(presets: Dict[str, List[str]]) -> None:
    current = load_preset_records()
    data = {}
    for name, mods in presets.items():
        rec = current.get(name, {})
        data[name] = {
            "mods": mods,
            "last_managed": rec.get("last_managed"),
            "state": rec.get("state", "undefined"),
        }
    save_json(_active_profile_data_path(PRESETS_PATH), data)

def load_labels() -> Dict[str, str]:
    records = load_mod_records()
    return {name: rec.get("label", "") for name, rec in records.items() if rec.get("label")}

def save_labels(labels: Dict[str, str]) -> None:
    current = load_mod_records()
    data = {}
    for name, label in labels.items():
        rec = current.get(name, {})
        data[name] = {
            "label": label,
            "last_managed": rec.get("last_managed"),
            "state": rec.get("state", "undefined"),
        }
    for name, rec in current.items():
        if name not in data and (rec.get("last_managed") or rec.get("state") != "undefined"):
            data[name] = {
                "label": "",
                "last_managed": rec.get("last_managed"),
                "state": rec.get("state", "undefined"),
            }
    save_json(_active_profile_data_path(LABELS_PATH), data)

def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")

def load_mod_records() -> Dict[str, Dict]:
    raw = _load_profile_json(LABELS_PATH, {})
    data = {}
    changed = False
    for name, value in raw.items():
        if isinstance(value, dict):
            data[name] = {
                "label": value.get("label", ""),
                "last_managed": value.get("last_managed"),
                "state": value.get("state", "undefined"),
            }
        else:
            data[name] = {
                "label": value or "",
                "last_managed": None,
                "state": "undefined",
            }
            changed = True
    if changed:
        save_json(_active_profile_data_path(LABELS_PATH), data)
    return data

def save_mod_records(records: Dict[str, Dict]) -> None:
    save_json(_active_profile_data_path(LABELS_PATH), records)

def mark_mods_managed(names: List[str], state: str) -> None:
    records = load_mod_records()
    managed_at = _now()
    for name in names:
        rec = records.setdefault(name, {"label": "", "last_managed": None, "state": "undefined"})
        rec["last_managed"] = managed_at
        rec["state"] = state
    save_mod_records(records)

def ensure_mod_records(names: List[str]) -> None:
    records = load_mod_records()
    changed = False
    for name in names:
        if name not in records:
            records[name] = {"label": "", "last_managed": None, "state": "undefined"}
            changed = True
    if changed:
        save_mod_records(records)

def load_preset_records() -> Dict[str, Dict]:
    raw = _load_profile_json(PRESETS_PATH, {})
    data = {}
    changed = False
    for name, value in raw.items():
        if isinstance(value, dict):
            data[name] = {
                "mods": value.get("mods", []),
                "last_managed": value.get("last_managed"),
                "state": value.get("state", "undefined"),
            }
        else:
            data[name] = {
                "mods": value or [],
                "last_managed": None,
                "state": "undefined",
            }
            changed = True
    if changed:
        save_json(_active_profile_data_path(PRESETS_PATH), data)
    return data

def save_preset_records(records: Dict[str, Dict]) -> None:
    save_json(_active_profile_data_path(PRESETS_PATH), records)

def mark_preset_managed(name: str, state: str) -> None:
    records = load_preset_records()
    rec = records.setdefault(name, {"mods": [], "last_managed": None, "state": "undefined"})
    rec["last_managed"] = _now()
    rec["state"] = state
    save_preset_records(records)
