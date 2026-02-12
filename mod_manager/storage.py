from __future__ import annotations

import json
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
    return load_json(PRESETS_PATH, {})

def save_presets(presets: Dict[str, List[str]]) -> None:
    save_json(PRESETS_PATH, presets)

def load_labels() -> Dict[str, str]:
    return load_json(LABELS_PATH, {})

def save_labels(labels: Dict[str, str]) -> None:
    save_json(LABELS_PATH, labels)
