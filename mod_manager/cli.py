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
from .storage import (
    GAME_PROFILE_KEYS,
    create_game_profile,
    delete_game_profile,
    game_abbreviation,
    load_config,
    save_config,
    set_active_game_profile,
    update_game_profile,
)

def _indexes(value: str) -> List[int]:
    return parse_multi_choice(value or "")

def _order(value: str) -> str:
    v = (value or "d").strip().lower()
    aliases = {
        "d": "default",
        "default": "default",
        "default desc": "-default",
        "cd": "created_date",
        "created date": "created_date",
        "created_date": "created_date",
        "created date desc": "-created_date",
        "created_date desc": "-created_date",
        "name": "name",
        "name desc": "-name",
        "label": "label",
        "label desc": "-label",
        "installed": "installed",
        "installed desc": "-installed",
        "last managed": "last_managed",
        "last_managed": "last_managed",
        "last managed desc": "-last_managed",
        "last_managed desc": "-last_managed",
    }
    if v.startswith("-"):
        key = v[1:]
        if key in {"default", "created_date", "created date", "name", "label", "installed", "last_managed", "last managed"}:
            return "-" + aliases.get(key, key.replace(" ", "_"))
    if v in aliases:
        return aliases[v]
    raise argparse.ArgumentTypeError("order must be one of: default, created_date, name, label, installed, last_managed, with optional '-' prefix or ' desc'")

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
    for key in ["game_mods_dir", "mods_source_dir", "mod_extensions", "page_size", "max_mod_name_len", "max_preset_name_len", "max_label_name_len", "gui_theme", "gui_accent_color_mode", "gui_accent_color", "gui_text_color_mode", "gui_text_color"]:
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

def _profile_values_from_args(args: argparse.Namespace) -> Dict:
    values = {}
    if getattr(args, "name", None) is not None:
        values["name"] = args.name
    for key in GAME_PROFILE_KEYS:
        value = getattr(args, key, None)
        if value is not None:
            values[key] = value
    return values

def _run_games(args: argparse.Namespace, cfg: Dict) -> int:
    profiles = cfg.get("game_profiles", []) or []
    if args.games_cmd == "list":
        active_id = cfg.get("active_game_profile_id", "")
        for profile in profiles:
            mark = "*" if profile.get("id") == active_id else " "
            print(f"{mark} {profile.get('id')} {game_abbreviation(profile.get('name', ''))} {profile.get('name')}")
        if not profiles:
            print("No game profiles.")
        return 0
    if args.games_cmd == "select":
        if set_active_game_profile(cfg, args.profile_id):
            save_config(cfg)
            print("Selected.")
            return 0
        print("Game profile not found.")
        return 1
    if args.games_cmd == "add":
        values = _profile_values_from_args(args)
        create_game_profile(values.pop("name"), values, cfg)
        save_config(cfg)
        print("Added.")
        return 0
    if args.games_cmd == "edit":
        if update_game_profile(cfg, args.profile_id, _profile_values_from_args(args)):
            save_config(cfg)
            print("Saved.")
            return 0
        print("Game profile not found.")
        return 1
    if args.games_cmd == "delete":
        if delete_game_profile(cfg, args.profile_id):
            save_config(cfg)
            print("Deleted.")
            return 0
        print("Game profile not found.")
        return 1
    return 1

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
    settings_set.add_argument("--gui-theme", choices=["system", "light", "dark"])
    settings_set.add_argument("--gui-accent-color-mode", choices=["system", "custom"])
    settings_set.add_argument("--gui-accent-color")
    settings_set.add_argument("--gui-text-color-mode", choices=["system", "custom"])
    settings_set.add_argument("--gui-text-color")

    games = sub.add_parser("games")
    games_sub = games.add_subparsers(dest="games_cmd", required=True)
    games_sub.add_parser("list")
    games_select = games_sub.add_parser("select")
    games_select.add_argument("profile_id")
    games_delete = games_sub.add_parser("delete")
    games_delete.add_argument("profile_id")
    games_add = games_sub.add_parser("add")
    games_add.add_argument("name")
    games_add.add_argument("--game-mods-dir", default="")
    games_add.add_argument("--mods-source-dir", default="")
    games_add.add_argument("--mod-extensions", default="")
    games_add.add_argument("--link-prefix", default="")
    games_edit = games_sub.add_parser("edit")
    games_edit.add_argument("profile_id")
    games_edit.add_argument("--name")
    games_edit.add_argument("--game-mods-dir")
    games_edit.add_argument("--mods-source-dir")
    games_edit.add_argument("--mod-extensions")
    games_edit.add_argument("--link-prefix")

    open_parser = sub.add_parser("open")
    open_parser.add_argument("target", choices=["source", "game"])

    broken = sub.add_parser("broken")
    broken_sub = broken.add_subparsers(dest="broken_cmd", required=True)
    broken_sub.add_parser("list")
    broken_remove = broken_sub.add_parser("remove")
    broken_remove.add_argument("indexes", nargs="?", type=_indexes, default=[])
    broken_remove.add_argument("--all", action="store_true")

    sub.add_parser("gui")

    help_p = sub.add_parser("help", help="Show help for a command")
    help_p.add_argument("topic", nargs="*", metavar="command", help="Command and optional subcommand (e.g. mods toggle)")

    return parser

def _subparsers_map(parser: argparse.ArgumentParser) -> dict:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}

def _run_help(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    topics = args.topic
    if not topics:
        parser.print_help()
        return 0
    top = _subparsers_map(parser)
    if topics[0] not in top:
        print(f"Unknown command: '{topics[0]}'. Available: {', '.join(top)}")
        return 1
    cmd_parser = top[topics[0]]
    if len(topics) == 1:
        cmd_parser.print_help()
        return 0
    sub = _subparsers_map(cmd_parser)
    if topics[1] not in sub:
        print(f"Unknown subcommand: '{topics[1]}'. Available: {', '.join(sub) or 'none'}")
        cmd_parser.print_help()
        return 1
    sub[topics[1]].print_help()
    return 0

def run_cli(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "help":
        return _run_help(args, parser)
    cfg = load_config()
    if args.cmd == "mods":
        return _run_mods(args, cfg)
    if args.cmd == "presets":
        return _run_presets(args, cfg)
    if args.cmd == "settings":
        return _run_settings(args, cfg)
    if args.cmd == "games":
        return _run_games(args, cfg)
    if args.cmd == "open":
        return _run_open(args, cfg)
    if args.cmd == "broken":
        return _run_broken(args, cfg)
    if args.cmd == "gui":
        from .gui import run_gui
        return run_gui()
    parser.print_help()
    return 0
