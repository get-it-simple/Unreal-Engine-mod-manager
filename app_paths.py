#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
PRESETS_PATH = APP_DIR / "presets.json"
LABELS_PATH = APP_DIR / "labels.json"

PAGE_SIZE = 10

PRINT_SIZE = 48

DEFAULT_CONFIG = {
    "mods_source_dir": "",
    "game_mods_dir": "",
    "mod_extensions": "",
    "page_size": 10,
    "max_mod_name_len": 28,
    "max_preset_name_len": 28,
    "max_label_name_len": 12
}
