from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from app_paths import CONFIG_PATH, PRESETS_PATH, LABELS_PATH, DEFAULT_CONFIG

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
    return cfg

def save_config(cfg: Dict) -> None:
    save_json(CONFIG_PATH, cfg)

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
    save_json(PRESETS_PATH, data)

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
    save_json(LABELS_PATH, data)

def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")

def load_mod_records() -> Dict[str, Dict]:
    raw = load_json(LABELS_PATH, {})
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
        save_json(LABELS_PATH, data)
    return data

def save_mod_records(records: Dict[str, Dict]) -> None:
    save_json(LABELS_PATH, records)

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
    raw = load_json(PRESETS_PATH, {})
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
        save_json(PRESETS_PATH, data)
    return data

def save_preset_records(records: Dict[str, Dict]) -> None:
    save_json(PRESETS_PATH, records)

def mark_preset_managed(name: str, state: str) -> None:
    records = load_preset_records()
    rec = records.setdefault(name, {"mods": [], "last_managed": None, "state": "undefined"})
    rec["last_managed"] = _now()
    rec["state"] = state
    save_preset_records(records)
