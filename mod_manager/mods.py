from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List, Tuple

from .models import ModItem
from .links import mklink, mklink_batch, unlink_path
from .platform_utils import is_windows
from .storage import load_labels, save_labels, mark_mods_managed, load_mod_records, ensure_mod_records
from .cli_utils import filter_items_by_query, page_slice, paginate, sort_items

IMAGE_EXTENSIONS = {".png", ".gif", ".jpg", ".jpeg", ".bmp", ".webp", ".ppm", ".pgm"}

def parse_extensions(cfg: Dict) -> Tuple[bool, List[str]]:
    exts_raw = (cfg.get("mod_extensions") or "").strip()
    if not exts_raw:
        return True, []
    exts = [e.lower().strip() if e.startswith(".") else "." + e.lower().strip() for e in exts_raw.split(",") if e.strip()]
    return False, exts

def is_mod_file(path: Path, cfg: Dict) -> bool:
    if path.is_dir():
        return path.name != "images"
    if not path.is_file() or is_image_file(path):
        return False
    show_all, exts = parse_extensions(cfg)
    return show_all or path.suffix.lower() in exts

def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS

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
            if p.name == "images":
                continue
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

def import_mod_file(cfg: Dict, src: Path, replace: bool = False) -> Tuple[bool, str]:
    dst_dir = Path(cfg.get("mods_source_dir") or "").expanduser()
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists() and not replace:
        return False, "exists"
    if src.resolve() == dst.resolve():
        ensure_mod_records([dst.name])
        return True, dst.name
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    ensure_mod_records([dst.name])
    return True, dst.name

def mod_image_path(cfg: Dict, mod_name: str) -> Path | None:
    images_dir = Path(cfg.get("mods_source_dir") or "").expanduser() / "images"
    for ext in [".png", ".gif", ".jpg", ".jpeg", ".bmp", ".webp", ".ppm", ".pgm"]:
        candidate = images_dir / f"{mod_name}{ext}"
        if candidate.exists():
            return candidate
    return None

def import_mod_image(cfg: Dict, mod_name: str, src: Path) -> Tuple[bool, str]:
    from .image import save_as_png
    images_dir = Path(cfg.get("mods_source_dir") or "").expanduser() / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    dst_png = images_dir / f"{mod_name}.png"
    if src.suffix.lower() == ".png" and src.resolve() == dst_png.resolve():
        return True, dst_png.name
    if save_as_png(src, dst_png):
        return True, dst_png.name
    dst = images_dir / f"{mod_name}{src.suffix.lower()}"
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return True, dst.name

def apply_mods_batch(mods: List[ModItem]) -> List[Tuple[bool, str]]:
    if not mods:
        return []
    if not is_windows():
        return [apply_mod(m) for m in mods]
    return mklink_batch([(m.src, m.dest, m.is_dir) for m in mods])

def deactivate_mod(mod: ModItem) -> Tuple[bool, str]:
    return unlink_path(mod.dest)

def mods_view(cfg: Dict, page: int, label_filter: str, search_query: str, order_mode: str) -> Tuple[List[ModItem], List[ModItem], int, int, Dict]:
    items_all = discover_mods(cfg)
    ensure_mod_records([m.name for m in items_all])
    items = filter_items_by_query(items_all, search_query)
    labels = load_labels()
    records = load_mod_records()
    if label_filter:
        lf = label_filter.lower()
        items = [m for m in items if (labels.get(m.name) or "").lower() == lf]
    reverse = order_mode.startswith("-")
    mode = order_mode[1:] if reverse else order_mode
    if mode == "name":
        items = sorted(items, key=lambda m: m.name.lower(), reverse=reverse)
    elif mode == "installed":
        items = sorted(items, key=lambda m: (m.installed, m.name.lower()), reverse=reverse)
    elif mode == "label":
        items = sorted(items, key=lambda m: ((labels.get(m.name) or "").lower(), m.name.lower()), reverse=reverse)
    elif mode == "last_managed":
        items = sorted(items, key=lambda m: (records.get(m.name, {}).get("last_managed") or "", m.name.lower()), reverse=reverse)
    else:
        items = sort_items(items, order_mode)
    page, pages = paginate(len(items) if items else 1, page, cfg)
    shown = page_slice(items, page, cfg) if items else []
    return items, shown, page, pages, labels

def add_label_to_mods(label_name: str, targets: List[str]) -> str:
    labels = load_labels()
    for file_name in targets:
        labels[file_name] = label_name
    save_labels(labels)
    mark_mods_managed(targets, "label")
    return f"Label added: {label_name} -> {', '.join(targets)}"

def remove_label_from_mods(label_name: str, targets: List[str]) -> str:
    labels = load_labels()
    removed = []
    for file_name in targets:
        if labels.get(file_name) == label_name:
            labels.pop(file_name, None)
            removed.append(file_name)
    if removed:
        save_labels(labels)
        mark_mods_managed(removed, "label")
        return f"Label removed: {label_name} -> {', '.join(removed)}"
    return "Label not found."

def deactivate_mods_page(cfg: Dict, page: int, label_filter: str, search_query: str, order_mode: str) -> Tuple[int, int]:
    _items, shown, target_page, _pages, _labels = mods_view(cfg, page, label_filter, search_query, order_mode)
    count = 0
    removed_names = []
    for m in shown:
        if m.installed:
            ok, _msg = deactivate_mod(m)
            if ok:
                count += 1
                removed_names.append(m.name)
    if count:
        mark_mods_managed(removed_names, "uninstalled")
    return target_page, count

def apply_mods_page(cfg: Dict, page: int, label_filter: str, search_query: str, order_mode: str) -> Tuple[int, int, int]:
    _items, shown, target_page, _pages, _labels = mods_view(cfg, page, label_filter, search_query, order_mode)
    to_install = [m for m in shown if not m.installed]
    total = len(to_install)
    err = 0
    for idx, m in enumerate(to_install, start=1):
        print(f"[{idx}/{total}] Installing {m.name} ...")
    results = apply_mods_batch(to_install)
    installed_names = []
    for _m, (ok, msg) in zip(to_install, results):
        if not ok:
            err += 1
            print(f"  ERR — {msg}")
        else:
            installed_names.append(_m.name)
    if installed_names:
        mark_mods_managed(installed_names, "installed")
    return target_page, total, err

def toggle_mods_by_indexes(shown: List[ModItem], indexes: List[int]) -> str:
    to_install: List[ModItem] = []
    uninstalled_names = []
    uninstalled = 0
    uninstall_errors = 0
    for num in indexes:
        if 1 <= num <= len(shown):
            m = shown[num - 1]
            if m.installed:
                ok, msg = deactivate_mod(m)
                if ok:
                    uninstalled += 1
                    uninstalled_names.append(m.name)
                else:
                    uninstall_errors += 1
            else:
                to_install.append(m)
    install_errors = 0
    if to_install:
        results = apply_mods_batch(to_install)
        install_errors = sum(1 for ok, _msg in results if not ok)
        mark_mods_managed([m.name for m, (ok, _msg) in zip(to_install, results) if ok], "installed")
    if uninstalled_names:
        mark_mods_managed(uninstalled_names, "uninstalled")
    installed = len(to_install) - install_errors
    parts = []
    if to_install:
        parts.append(f"Installed {installed}/{len(to_install)}. Errors: {install_errors}.")
    if uninstalled or uninstall_errors:
        parts.append(f"Uninstalled {uninstalled}. Errors: {uninstall_errors}.")
    return " ".join(parts)

def mods_records() -> Dict[str, Dict]:
    return load_mod_records()

def get_mod_file_name(items: List[ModItem], page: int, file_name: str, cfg: Dict) -> str:
    if file_name.isdigit() and int(file_name) > 0 and int(file_name) < int(cfg.get("page_size", 10)) + 1:
        return items[int(file_name) - 1 + (int(cfg.get("page_size", 10)) * (page - 1))].name
    else:
        return file_name
