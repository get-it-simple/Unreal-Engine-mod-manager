from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

from .models import ModFile, ModItem
from .links import copy_batch, mklink, mklink_batch, remove_path, unlink_path
from .platform_utils import is_windows
from .storage import (
    ensure_mod_records,
    load_favorites,
    load_labels,
    load_mod_records,
    mark_mods_managed,
    save_labels,
    update_favorites,
)
from .cli_utils import filter_items_by_query, page_slice, paginate, sort_items

IMAGE_EXTENSIONS = (".png", ".gif", ".jpg", ".jpeg", ".bmp", ".webp", ".ppm", ".pgm")

def _name_without_prefix(name: str, link_prefix: str) -> str:
    if not link_prefix:
        return name.lower()
    path = Path(name)
    if path.stem.endswith(link_prefix):
        return (path.stem[: -len(link_prefix)] + path.suffix).lower()
    if name.startswith(link_prefix):
        return name[len(link_prefix):].lower()
    return name.lower()

FOLDER_TOKENS = {"folder", "folders"}

def _split_tokens(raw: str) -> List[str]:
    return [token.strip() for token in (raw or "").split(",") if token.strip()]

def _normalize_extensions(tokens: List[str]) -> List[str]:
    """Lowercase, dot-prefix and de-duplicate extension tokens, keeping their order."""
    exts: List[str] = []
    for token in tokens:
        if token.lower() in FOLDER_TOKENS:
            continue
        ext = token.lower() if token.startswith(".") else "." + token.lower()
        if ext not in exts:
            exts.append(ext)
    return exts

def parse_group_extensions(cfg: Dict) -> List[str]:
    """Extensions joined into one mod by shared file name, in the configured order."""
    return _normalize_extensions(_split_tokens(cfg.get("mod_group_extensions") or ""))

def parse_extensions(cfg: Dict) -> Tuple[bool, List[str], bool]:
    """Return (show_all, extensions, include_folders) parsed from mod_extensions.

    mod_extensions is a comma-separated list, e.g. ".pak,.utoc,folders".
    The "folder"/"folders" token (case-insensitive) controls whether
    directories under the source folder are treated as mod units. When
    mod_extensions is empty, every file/extension and folders are allowed
    (preserves the historical default behavior). Grouped extensions always
    count as mod files so a group never loses a member to the filter.
    """
    tokens = _split_tokens(cfg.get("mod_extensions") or "")
    if not tokens:
        return True, [], True
    include_folders = any(token.lower() in FOLDER_TOKENS for token in tokens)
    exts = _normalize_extensions(tokens)
    for ext in parse_group_extensions(cfg):
        if ext not in exts:
            exts.append(ext)
    return False, exts, include_folders

def is_mod_file(path: Path, cfg: Dict) -> bool:
    show_all, exts, include_folders = parse_extensions(cfg)
    if path.is_dir():
        return include_folders and path.name != "images"
    if not path.is_file() or is_image_file(path):
        return False
    return show_all or path.suffix.lower() in exts

def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS

def _link_dest_name(p: Path, link_prefix: str) -> str:
    if not link_prefix or p.is_dir():
        return p.name
    if p.stem.endswith(link_prefix):
        return p.name
    return p.stem + link_prefix + p.suffix

def _iter_mod_sources(src_dir: Path, recursive: bool, include_folders: bool, imported_folders: set[str] | None = None):
    """Yield (path, is_dir) candidates from src_dir, honoring folder/recursive options."""
    for p in sorted(src_dir.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        if p.is_dir():
            if p.name.casefold() == "images" or (p.name.startswith(".mod-import-") and p.name.casefold() not in (imported_folders or set())):
                continue
            if include_folders or p.name.casefold() in (imported_folders or set()):
                yield p, True
            elif recursive:
                yield from _iter_mod_sources(p, recursive, include_folders)
        elif p.is_file():
            yield p, False

def _is_installed(dest: Path) -> bool:
    return dest.exists() or dest.is_symlink()

def _mod_file(p: Path, is_dir: bool, dst_dir: Path, link_prefix: str) -> ModFile:
    dest = dst_dir / (p.name if is_dir else _link_dest_name(p, link_prefix))
    return ModFile(src=p, dest=dest, is_dir=is_dir)

def _build_mod(members: List[ModFile], group_exts: List[str], copy_install: bool) -> ModItem:
    """Turn one or more member files into a mod named after its primary member."""
    if len(members) > 1:
        members = sorted(members, key=lambda f: (group_exts.index(f.src.suffix.lower()), f.src.name.lower()))
    primary = members[0]
    return ModItem(
        name=primary.src.name,
        src=primary.src,
        dest=primary.dest,
        is_dir=primary.is_dir,
        installed=all(_is_installed(f.dest) for f in members),
        files=tuple(members) if len(members) > 1 else (),
        copy_install=copy_install,
    )

def discover_mods(cfg: Dict) -> List[ModItem]:
    src_dir = Path(cfg.get("mods_source_dir") or "").expanduser()
    dst_dir = Path(cfg.get("game_mods_dir") or "").expanduser()
    show_all, exts, include_folders = parse_extensions(cfg)
    group_exts = parse_group_extensions(cfg)
    recursive = bool(cfg.get("mod_recursive_scan"))
    link_prefix = (cfg.get("link_prefix") or "").strip()
    copy_install = is_copy_install(cfg)

    if not src_dir.exists():
        return []

    order: List = []
    groups: Dict = {}
    from .import_registry import directory_mods

    for p, is_dir in _iter_mod_sources(src_dir, recursive, include_folders, directory_mods(cfg)):
        if not is_dir and not (show_all or p.suffix.lower() in exts):
            continue
        key = p
        if not is_dir and p.suffix.lower() in group_exts:
            key = (p.parent, p.stem.lower())
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(_mod_file(p, is_dir, dst_dir, link_prefix))
    return [_build_mod(groups[key], group_exts, copy_install) for key in order]

def list_installed_mods(cfg: Dict) -> List[ModItem]:
    items = discover_mods(cfg)
    return [m for m in items if m.installed]

def list_broken_links(cfg: Dict) -> List[ModItem]:
    items = discover_mods(cfg)
    return [m for m in items if m.installed and not m.src.exists()]

def is_copy_install(cfg: Dict) -> bool:
    return str(cfg.get("install_mode") or "").strip().lower() == "copy"

def apply_mod(mod: ModItem, overwrite: bool = False) -> Tuple[bool, str]:
    return apply_mods_batch([mod], overwrite)[0]

def import_mod_file(cfg: Dict, src: Path, replace: bool = False, target_name: str = "") -> Tuple[bool, str]:
    from .imports import PlannedMod, ignored_file, publish_plan

    dst_dir = Path(cfg.get("mods_source_dir") or "").expanduser()
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / (target_name or src.name)
    if dst.exists() and not replace:
        return False, "exists"
    if src.resolve() == dst.resolve():
        ensure_mod_records([dst.name])
        return True, dst.name
    if src.is_symlink() or (hasattr(src, "is_junction") and src.is_junction()):
        return False, "Linked import paths are unsupported."
    directories = []
    if src.is_dir():
        members = []
        for path in src.rglob("*"):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                return False, f"Linked import paths are unsupported: {path.name}"
            if path.is_file() and not ignored_file(path, cfg):
                members.append((path, path.relative_to(src)))
            elif path.is_dir():
                directories.append(path.relative_to(src))
        files = tuple(members)
    elif ignored_file(src, cfg):
        return False, f"Ignored extension: {src.name}"
    else:
        files = ((src, Path(dst.name)),)
    return publish_plan(cfg, PlannedMod(dst.name, files, src.is_dir(), replace_existing=replace, directories=tuple(directories)))

def mod_image_path(cfg: Dict, mod_name: str) -> Path | None:
    images_dir = Path(cfg.get("mods_source_dir") or "").expanduser() / "images"
    for ext in IMAGE_EXTENSIONS:
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

def import_mod_images(cfg: Dict, names: list[str], src: Path) -> tuple[list[str], list[str]]:
    applied, errors = [], []
    images_dir = Path(cfg.get("mods_source_dir") or "").expanduser() / "images"
    for name in names:
        try:
            images_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".mod-preview-", dir=images_dir) as staging:
                staged_cfg = {**cfg, "mods_source_dir": staging}
                ok, message = import_mod_image(staged_cfg, name, src)
                if ok:
                    (Path(staging) / "images" / message).replace(images_dir / message)
        except OSError as exc:
            errors.append(f"{name}: {exc}")
        else:
            if ok:
                applied.append(name)
            else:
                errors.append(f"{name}: {message}")
    return applied, errors


def _pending_files(mod: ModItem, overwrite: bool) -> List[ModFile]:
    """Members to write: everything when replacing, otherwise only what a half installed group misses."""
    if overwrite and mod.copy_install:
        return list(mod.install_files)
    pending = [f for f in mod.install_files if not _is_installed(f.dest)]
    return pending or list(mod.install_files)

def _fold_results(results: List[Tuple[bool, str]]) -> Tuple[bool, str]:
    for ok, msg in results:
        if not ok:
            return False, msg
    return True, "OK"

def _link_files(files: List[ModFile]) -> List[Tuple[bool, str]]:
    items = [(f.src, f.dest, f.is_dir) for f in files]
    if not is_windows():
        return [mklink(src, dest) for src, dest, _is_dir in items]
    return mklink_batch(items)

def apply_mods_batch(mods: List[ModItem], overwrite: bool = False) -> List[Tuple[bool, str]]:
    if not mods:
        return []
    work = [(index, f) for index, m in enumerate(mods) for f in _pending_files(m, overwrite)]
    linked = [(index, f) for index, f in work if not mods[index].copy_install]
    copied = [(index, f) for index, f in work if mods[index].copy_install]

    per_mod: List[List[Tuple[bool, str]]] = [[] for _ in mods]
    for items, results in (
        (linked, _link_files([f for _index, f in linked])),
        (copied, copy_batch([(f.src, f.dest, f.is_dir) for _index, f in copied], overwrite)),
    ):
        for (index, _f), result in zip(items, results):
            per_mod[index].append(result)
    return [_fold_results(results) for results in per_mod]

OVERWRITE_PREVIEW_COUNT = 10
OVERWRITE_MESSAGE = "{count} file(s) already exist in the game mods folder:\n\n{names}"

def existing_targets(mods: List[ModItem]) -> List[str]:
    """Names in the game mods folder that a copy install would overwrite."""
    return [
        f.dest.name
        for m in mods
        if m.copy_install
        for f in m.install_files
        if _is_installed(f.dest)
    ]

def overwrite_message(names: List[str]) -> str:
    """Shared wording for the overwrite warning in every interface."""
    listed = "\n".join(names[:OVERWRITE_PREVIEW_COUNT])
    if len(names) > OVERWRITE_PREVIEW_COUNT:
        listed += f"\n... and {len(names) - OVERWRITE_PREVIEW_COUNT} more"
    return OVERWRITE_MESSAGE.format(count=len(names), names=listed)

def deactivate_mod(mod: ModItem) -> Tuple[bool, str]:
    remove = remove_path if mod.copy_install else unlink_path
    results = [remove(f.dest) for f in mod.install_files if _is_installed(f.dest)]
    if not results:
        return False, "Already removed"
    return _fold_results(results)

def mods_view(
    cfg: Dict,
    page: int,
    label_filter: str,
    search_query: str,
    order_mode: str,
    favorite_only: bool = False,
) -> Tuple[List[ModItem], List[ModItem], int, int, Dict]:
    items_all = discover_mods(cfg)
    ensure_mod_records([m.name for m in items_all])
    items = filter_items_by_query(items_all, search_query)
    labels = load_labels()
    records = load_mod_records()
    if label_filter:
        lf = label_filter.lower()
        items = [m for m in items if (labels.get(m.name) or "").lower() == lf]
    if favorite_only:
        favorites = load_favorites(cfg)
        items = [m for m in items if m.name in favorites]
    reverse = order_mode.startswith("-")
    mode = order_mode[1:] if reverse else order_mode
    if mode in {"d", "default"}:
        link_prefix = (cfg.get("link_prefix") or "").strip()
        items = sorted(items, key=lambda m: ((not m.is_dir), _name_without_prefix(m.name, link_prefix)), reverse=reverse)
    elif mode == "name":
        items = sorted(items, key=lambda m: m.name.lower(), reverse=reverse)
    elif mode == "installed":
        items = sorted(items, key=lambda m: (m.installed, m.name.lower()), reverse=reverse)
    elif mode == "label":
        items = sorted(items, key=lambda m: ((labels.get(m.name) or "").lower(), m.name.lower()), reverse=reverse)
    elif mode == "last_managed":
        items = sorted(items, key=lambda m: (records.get(m.name, {}).get("last_managed") or "", m.name.lower()), reverse=reverse)
    elif mode in {"cd", "created_date", "created date"}:
        ctimes = {m.name: (m.src.stat().st_ctime if m.src.exists() else 0) for m in items}
        items = sorted(items, key=lambda m: (ctimes[m.name], m.name.lower()), reverse=reverse)
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

def add_favorites_to_mods(cfg: Dict, targets: List[str]) -> str:
    update_favorites(cfg, targets, True)
    return f"Favorites added: {', '.join(targets)}"

def remove_favorites_from_mods(cfg: Dict, targets: List[str]) -> str:
    update_favorites(cfg, targets, False)
    return f"Favorites removed: {', '.join(targets)}"

def deactivate_mods_page(
    cfg: Dict,
    page: int,
    label_filter: str,
    search_query: str,
    order_mode: str,
    favorite_only: bool = False,
) -> Tuple[int, int]:
    _items, shown, target_page, _pages, _labels = mods_view(
        cfg, page, label_filter, search_query, order_mode, favorite_only
    )
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

def apply_mods_page(
    cfg: Dict,
    page: int,
    label_filter: str,
    search_query: str,
    order_mode: str,
    favorite_only: bool = False,
    overwrite: bool = False,
) -> Tuple[int, int, int]:
    _items, shown, target_page, _pages, _labels = mods_view(
        cfg, page, label_filter, search_query, order_mode, favorite_only
    )
    to_install = [m for m in shown if not m.installed]
    total = len(to_install)
    err = 0
    for idx, m in enumerate(to_install, start=1):
        print(f"[{idx}/{total}] Installing {m.name} ...")
    results = apply_mods_batch(to_install, overwrite)
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

def mods_by_indexes(shown: List[ModItem], indexes: List[int]) -> List[ModItem]:
    return [shown[num - 1] for num in indexes if 1 <= num <= len(shown)]

def toggle_mods_by_indexes(shown: List[ModItem], indexes: List[int], overwrite: bool = False) -> str:
    to_install: List[ModItem] = []
    uninstalled_names = []
    uninstalled = 0
    uninstall_errors = 0
    for m in mods_by_indexes(shown, indexes):
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
        results = apply_mods_batch(to_install, overwrite)
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
