from __future__ import annotations

import argparse
from typing import Dict, List

from .cli_utils import ensure_paths, open_folder, parse_multi_choice
from .mods import (
    add_label_to_mods,
    apply_mods_page,
    deactivate_mod,
    deactivate_mods_page,
    list_broken_links,
    mods_view,
    remove_label_from_mods,
    toggle_mods_by_indexes,
)
from .presets import (
    delete_presets_by_indexes,
    presets_view,
    save_preset_from_installed,
    toggle_presets_by_indexes,
)
from .storage import load_config, save_config

def _indexes(value: str) -> List[int]:
    return parse_multi_choice(value or "")

def _order(value: str) -> str:
    v = (value or "d").strip().lower()
    if v in ["d", "default"]:
        return "d"
    if v in ["cd", "created date"]:
        return "cd"
    raise argparse.ArgumentTypeError("order must be one of: d, default, cd, created date")

def _add_view_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--label", default="")
    parser.add_argument("--search", default="")
    parser.add_argument("--order", type=_order, default="d")

def _print_mods(cfg: Dict, page: int, label: str, search: str, order: str) -> int:
    items, shown, page, pages, labels = mods_view(cfg, page, label, search, order)
    print(f"Page {page}/{pages}")
    for i, mod in enumerate(shown, 1):
        mark = "X" if mod.installed else " "
        label_text = labels.get(mod.name, "-")
        print(f"{i}. [{mark}] {mod.name} [{label_text}]")
    if not items:
        print("No mods.")
    return 0

def _print_presets(cfg: Dict, page: int) -> int:
    presets, keys, page_keys, page, pages = presets_view(cfg, page)
    installed = {m.name for m in mods_view(cfg, 1, "", "", "d")[0] if m.installed}
    print(f"Page {page}/{pages}")
    for i, name in enumerate(page_keys, 1):
        mods = presets.get(name, [])
        mark = "X" if bool(mods) and all(nm in installed for nm in mods) else " "
        print(f"{i}. [{mark}] {name} [{len(mods)}]")
    if not keys:
        print("No presets saved.")
    return 0

def _selected_mod_names(cfg: Dict, page: int, label: str, search: str, order: str, indexes: List[int]) -> List[str]:
    _items, shown, _page, _pages, _labels = mods_view(cfg, page, label, search, order)
    return [shown[i - 1].name for i in indexes if 1 <= i <= len(shown)]

def _run_mods(args: argparse.Namespace, cfg: Dict) -> int:
    if not ensure_paths(cfg):
        return 1
    if args.mods_cmd in ["list", "search", "label", "page", "order"]:
        search = args.text if args.mods_cmd == "search" else args.search
        label = args.text if args.mods_cmd == "label" else args.label
        page = args.number if args.mods_cmd == "page" else args.page
        order = args.mode if args.mods_cmd == "order" else args.order
        return _print_mods(cfg, page, label, search, order)
    if args.mods_cmd == "install":
        page, total, err = apply_mods_page(cfg, args.page, args.label, args.search, args.order)
        print(f"Installed {total - err}/{total} on page {page}. Errors: {err}.")
        return 1 if err else 0
    if args.mods_cmd == "uninstall":
        page, count = deactivate_mods_page(cfg, args.page, args.label, args.search, args.order)
        print(f"Uninstalled {count} on page {page}.")
        return 0
    if args.mods_cmd == "toggle":
        _items, shown, _page, _pages, _labels = mods_view(cfg, args.page, args.label, args.search, args.order)
        msg = toggle_mods_by_indexes(shown, args.indexes)
        print(msg or "No mods toggled.")
        return 0
    if args.mods_cmd == "label-add":
        targets = _selected_mod_names(cfg, args.page, args.filter_label, args.search, args.order, args.indexes)
        print(add_label_to_mods(args.label, targets) if targets else "Invalid index.")
        return 0 if targets else 1
    if args.mods_cmd == "label-remove":
        targets = _selected_mod_names(cfg, args.page, args.filter_label, args.search, args.order, args.indexes)
        print(remove_label_from_mods(args.label, targets) if targets else "Invalid index.")
        return 0 if targets else 1
    return 1

def _run_presets(args: argparse.Namespace, cfg: Dict) -> int:
    if not ensure_paths(cfg):
        return 1
    if args.presets_cmd in ["list", "page"]:
        page = args.number if args.presets_cmd == "page" else args.page
        return _print_presets(cfg, page)
    if args.presets_cmd == "save":
        ok, msg = save_preset_from_installed(cfg, args.name)
        print(msg)
        return 0 if ok else 1
    if args.presets_cmd == "delete":
        count, missing = delete_presets_by_indexes(cfg, args.page, args.indexes)
        print(f"Deleted: {count}. Missing: {', '.join(missing) if missing else 'none'}")
        return 0
    if args.presets_cmd == "toggle":
        installed = {m.name for m in mods_view(cfg, 1, "", "", "d")[0] if m.installed}
        msg, messages, has_errors = toggle_presets_by_indexes(cfg, args.page, args.indexes, installed)
        print(msg or "No presets toggled.")
        for item in messages:
            print(" - ", item)
        return 1 if has_errors else 0
    return 1

def _run_settings(args: argparse.Namespace, cfg: Dict) -> int:
    if args.settings_cmd == "show":
        for key in sorted(cfg):
            print(f"{key}: {cfg[key]}")
        return 0
    changed = False
    for key in ["game_mods_dir", "mods_source_dir", "mod_extensions", "page_size", "max_mod_name_len", "max_preset_name_len", "max_label_name_len"]:
        value = getattr(args, key)
        if value is not None:
            cfg[key] = value
            changed = True
    if changed:
        save_config(cfg)
        print("Saved.")
    else:
        print("Nothing changed.")
    return 0

def _run_open(args: argparse.Namespace, cfg: Dict) -> int:
    key = "mods_source_dir" if args.target == "source" else "game_mods_dir"
    ok, msg = open_folder(cfg.get(key, ""))
    print(f"Open {args.target} folder: {'OK' if ok else 'ERR'} — {msg}")
    return 0 if ok else 1

def _run_broken(args: argparse.Namespace, cfg: Dict) -> int:
    if not ensure_paths(cfg):
        return 1
    broken = list_broken_links(cfg)
    if args.broken_cmd == "list":
        for i, mod in enumerate(broken, 1):
            kind = "DIR" if mod.is_dir else "FILE"
            print(f"{i}. [!] {mod.name} ({kind}) -> missing source: {mod.src}")
        if not broken:
            print("No broken links detected.")
        return 0
    targets = broken if args.all else [broken[i - 1] for i in args.indexes if 1 <= i <= len(broken)]
    for mod in targets:
        ok, msg = deactivate_mod(mod)
        print(f"Remove {mod.dest.name}: {'OK' if ok else 'ERR'} — {msg}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mod-manager.py")
    sub = parser.add_subparsers(dest="cmd")

    mods = sub.add_parser("mods")
    mods_sub = mods.add_subparsers(dest="mods_cmd", required=True)
    for name in ["list", "install", "uninstall", "toggle"]:
        p = mods_sub.add_parser(name)
        _add_view_args(p)
    p = mods_sub.add_parser("search")
    p.add_argument("text")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--label", default="")
    p.add_argument("--order", type=_order, default="d")
    p = mods_sub.add_parser("label")
    p.add_argument("text")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--search", default="")
    p.add_argument("--order", type=_order, default="d")
    p = mods_sub.add_parser("page")
    p.add_argument("number", type=int)
    p.add_argument("--label", default="")
    p.add_argument("--search", default="")
    p.add_argument("--order", type=_order, default="d")
    p = mods_sub.add_parser("order")
    p.add_argument("mode", type=_order)
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--label", default="")
    p.add_argument("--search", default="")
    mods_sub.choices["toggle"].add_argument("indexes", type=_indexes)
    for name in ["label-add", "label-remove"]:
        p = mods_sub.add_parser(name)
        p.add_argument("label")
        p.add_argument("indexes", type=_indexes)
        p.add_argument("--page", type=int, default=1)
        p.add_argument("--filter-label", default="")
        p.add_argument("--search", default="")
        p.add_argument("--order", type=_order, default="d")

    presets = sub.add_parser("presets")
    presets_sub = presets.add_subparsers(dest="presets_cmd", required=True)
    presets_sub.add_parser("list").add_argument("--page", type=int, default=1)
    presets_sub.add_parser("page").add_argument("number", type=int)
    presets_sub.add_parser("save").add_argument("name")
    for name in ["delete", "toggle"]:
        p = presets_sub.add_parser(name)
        p.add_argument("indexes", type=_indexes)
        p.add_argument("--page", type=int, default=1)

    settings = sub.add_parser("settings")
    settings_sub = settings.add_subparsers(dest="settings_cmd", required=True)
    settings_sub.add_parser("show")
    settings_set = settings_sub.add_parser("set")
    settings_set.add_argument("--game-mods-dir")
    settings_set.add_argument("--mods-source-dir")
    settings_set.add_argument("--mod-extensions")
    settings_set.add_argument("--page-size", type=int)
    settings_set.add_argument("--max-mod-name-len", type=int)
    settings_set.add_argument("--max-preset-name-len", type=int)
    settings_set.add_argument("--max-label-name-len", type=int)

    open_parser = sub.add_parser("open")
    open_parser.add_argument("target", choices=["source", "game"])

    broken = sub.add_parser("broken")
    broken_sub = broken.add_subparsers(dest="broken_cmd", required=True)
    broken_sub.add_parser("list")
    broken_remove = broken_sub.add_parser("remove")
    broken_remove.add_argument("indexes", nargs="?", type=_indexes, default=[])
    broken_remove.add_argument("--all", action="store_true")

    sub.add_parser("gui")

    return parser

def run_cli(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.cmd == "mods":
        return _run_mods(args, cfg)
    if args.cmd == "presets":
        return _run_presets(args, cfg)
    if args.cmd == "settings":
        return _run_settings(args, cfg)
    if args.cmd == "open":
        return _run_open(args, cfg)
    if args.cmd == "broken":
        return _run_broken(args, cfg)
    if args.cmd == "gui":
        from .gui import run_gui
        return run_gui()
    parser.print_help()
    return 0
