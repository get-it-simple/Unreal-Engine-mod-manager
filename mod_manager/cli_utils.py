from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

from .models import ModItem
from .platform_utils import is_windows

def prompt(msg: str) -> str:
    try:
        return input(msg)
    except EOFError:
        return ""

def pause(msg: str = "Press Enter to continue...") -> None:
    prompt(f"{msg}")


def ensure_paths(cfg: Dict) -> bool:
    gs = cfg.get("game_mods_dir")
    ms = cfg.get("mods_source_dir")
    if not gs or not ms:
        print("Please configure paths first.")
        return False
    Path(gs).mkdir(parents=True, exist_ok=True)
    Path(ms).mkdir(parents=True, exist_ok=True)
    return True

def parse_multi_choice(choice: str) -> List[int]:
    parts = [p.strip() for p in choice.split(",") if p.strip()]
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
    return nums

def parse_page_choice(choice: str) -> int | None:
    c = choice.strip().lower()
    if c.startswith("p") and c[1:].isdigit():
        return int(c[1:])
    return None

def paginate(total: int, page: int, cfg: Dict) -> Tuple[int, int]:
    pages = max(1, (total + int(cfg.get("page_size", 10)) - 1) // int(cfg.get("page_size", 10)))
    page = max(1, min(page, pages))
    return page, pages

def page_slice(items: List, page: int, cfg: Dict) -> List:
    start = (page - 1) * int(cfg.get("page_size", 10))
    end = start + int(cfg.get("page_size", 10))
    return items[start:end]

def print_pager(pages: int, current: int):
    if pages <= 1:
        return
    labels = []
    for i in range(1, pages + 1):
        labels.append(f"[p{i}]" if i != current else f"(p{i})")
    print("Pages:")
    for i in range(0, len(labels), 10):
        print(" ".join(labels[i:i+10]))

def open_folder(path_str: str) -> Tuple[bool, str]:
    try:
        if not path_str:
            return False, "Path is empty"
        p = Path(path_str).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        if is_windows():
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True, "Opened"
    except Exception as e:
        return False, str(e)

def filter_items_by_query(items: List[ModItem], query: str) -> List[ModItem]:
    q = (query or "").lower()
    if not q:
        return items
    return [m for m in items if q in m.name.lower()]

def sort_items(items: List[ModItem], order_mode: str) -> List[ModItem]:
    # Supports short and full names:
    # 'd' or 'default' -> default order (files grouped & name asc)
    # 'cd' or 'created date' -> by creation time (ctime)
    if order_mode in ["cd", "created date"]:
        try:
            return sorted(items, key=lambda m: m.src.stat().st_ctime, reverse=True)
        except Exception:
            # Fallback to default order if stat not available
            pass
    return sorted(items, key=lambda m: ((not m.is_dir), m.name.lower()))
