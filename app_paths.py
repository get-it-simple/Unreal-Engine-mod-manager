#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
elif Path(sys.argv[0]).suffix.lower() == ".pyz":
    APP_DIR = Path(sys.argv[0]).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
PRESETS_PATH = APP_DIR / "presets.json"
LABELS_PATH = APP_DIR / "labels.json"
PROFILE_DATA_DIR = APP_DIR / "profiles"

PAGE_SIZE = 10

PRINT_SIZE = 48

DEFAULT_CONFIG = {
    "active_game_profile_id": "",
    "game_profiles": [],
    "mods_source_dir": "",
    "game_mods_dir": "",
    "mod_extensions": "",
    "link_prefix": "",
    "page_size": 10,
    "max_mod_name_len": 28,
    "max_preset_name_len": 28,
    "max_label_name_len": 12,
    "button_size_percent": 100,
    "gui_theme": "system",
    "gui_font_family": "",
    "gui_font_size": 10,
    "placeholder_image_col_width": 56,
    "mod_view_mode": "list",
    "tile_size": 140,
    "window_width": 1200,
    "window_height": 750,
    "order_var": "Default",
    "mod_sort_key": "d",
    "mod_sort_reverse": False,
    "preset_sort_key": "name",
    "preset_sort_reverse": False,
}
