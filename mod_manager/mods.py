from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from .models import ModItem
from .links import mklink, mklink_batch, unlink_path
from .platform_utils import is_windows

def parse_extensions(cfg: Dict) -> Tuple[bool, List[str]]:
    exts_raw = (cfg.get("mod_extensions") or "").strip()
    if not exts_raw:
        return True, []
    exts = [e.lower().strip() if e.startswith(".") else "." + e.lower().strip() for e in exts_raw.split(",") if e.strip()]
    return False, exts

def discover_mods(cfg: Dict) -> List[ModItem]:
    src_dir = Path(cfg.get("mods_source_dir") or "").expanduser()
    dst_dir = Path(cfg.get("game_mods_dir") or "").expanduser()
    show_all, exts = parse_extensions(cfg)

    items: List[ModItem] = []
    if not src_dir.exists():
        return items

    for p in sorted(src_dir.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        if p.is_file():
            if (show_all or p.suffix.lower() in exts):
                dest = dst_dir / p.name
                installed = dest.exists() or dest.is_symlink()
                items.append(ModItem(name=p.name, src=p, dest=dest, is_dir=False, installed=installed))
        elif p.is_dir():
            dest = dst_dir / p.name
            installed = dest.exists() or dest.is_symlink()
            items.append(ModItem(name=p.name, src=p, dest=dest, is_dir=True, installed=installed))
    return items

def list_installed_mods(cfg: Dict) -> List[ModItem]:
    items = discover_mods(cfg)
    return [m for m in items if m.installed]

def list_broken_links(cfg: Dict) -> List[ModItem]:
    items = discover_mods(cfg)
    return [m for m in items if m.installed and not m.src.exists()]

def apply_mod(mod: ModItem) -> Tuple[bool, str]:
    return mklink(mod.src, mod.dest)

def apply_mods_batch(mods: List[ModItem]) -> List[Tuple[bool, str]]:
    if not mods:
        return []
    if not is_windows():
        return [apply_mod(m) for m in mods]
    return mklink_batch([(m.src, m.dest, m.is_dir) for m in mods])

def deactivate_mod(mod: ModItem) -> Tuple[bool, str]:
    return unlink_path(mod.dest)

def get_mod_file_name(items: List[ModItem], page: int, file_name: str, cfg: Dict) -> str:
    if file_name.isdigit() and int(file_name) > 0 and int(file_name) < int(cfg.get("page_size", 10)) + 1:
        return items[int(file_name) - 1 + (int(cfg.get("page_size", 10)) * (page - 1))].name
    else:
        return file_name