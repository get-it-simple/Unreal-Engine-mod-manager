#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import os
import platform
import subprocess
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

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
    "page_size": 10
}

@dataclass
class ModItem:
    name: str
    src: Path
    dest: Path
    is_dir: bool
    installed: bool

# ----------------------------- Helpers -----------------------------

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

def parse_extensions(cfg: Dict) -> Tuple[bool, List[str]]:
    exts_raw = (cfg.get("mod_extensions") or "").strip()
    if not exts_raw:
        return True, []
    exts = [e.lower().strip() if e.startswith(".") else "." + e.lower().strip() for e in exts_raw.split(",") if e.strip()]
    return False, exts

def is_windows() -> bool:
    return platform.system().lower().startswith("win")

def mklink(src: Path, dest: Path) -> Tuple[bool, str]:
    try:
        if dest.exists() or dest.is_symlink():
            return False, f"Target already exists: {dest}"
        if not src.exists():
            return False, f"Source not found: {src}"

        if is_windows():
            if src.is_dir():
                cmd = ["cmd", "/c", "mklink", "/J", str(dest), str(src)]
            else:
                cmd = ["cmd", "/c", "mklink", str(dest), str(src)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                return False, res.stderr.strip() or res.stdout.strip() or "mklink error"
            return True, "OK"
        else:
            if src.is_dir():
                os.symlink(src, dest, target_is_directory=True)
            else:
                os.symlink(src, dest)
            return True, "OK"
    except Exception as e:
        return False, str(e)

def unlink_path(path: Path) -> Tuple[bool, str]:
    try:
        if not path.exists() and not path.is_symlink():
            return False, "Already removed"
        if path.is_dir() and not path.is_symlink():
            try:
                os.rmdir(path)
            except OSError:
                return False, "Not a link or not empty"
        else:
            path.unlink()
        return True, "OK"
    except Exception as e:
        return False, str(e)

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

def deactivate_mod(mod: ModItem) -> Tuple[bool, str]:
    return unlink_path(mod.dest)

def get_mod_file_name(items: List[ModItem], page: int, file_name: str, cfg: Dict) -> str:
    if file_name.isdigit() and int(file_name) > 0 and int(file_name) < int(cfg.get("page_size", 10)) + 1:
        return items[int(file_name) - 1 + (int(cfg.get("page_size", 10)) * (page - 1))].name
    else:
        return file_name
                            

# ----------------------------- Presets -----------------------------

def save_preset_from_installed(cfg: Dict, name: str) -> Tuple[bool, str]:
    presets = load_presets()
    installed = list_installed_mods(cfg)
    if not installed:
        return False, "No installed mods to save"
    presets[name] = [m.name for m in installed]
    save_presets(presets)
    return True, f"Preset '{name}' saved ({len(installed)} mods)"

def delete_presets_by_names(names: List[str]) -> Tuple[int, List[str]]:
    presets = load_presets()
    removed = 0
    missing = []
    for nm in names:
        if nm in presets:
            presets.pop(nm, None)
            removed += 1
        else:
            missing.append(nm)
    save_presets(presets)
    return removed, missing

def apply_preset(cfg: Dict, name: str) -> Tuple[int, int, List[str]]:
    presets = load_presets()
    all_mods = {m.name: m for m in discover_mods(cfg)}
    names = presets.get(name, [])

    ok = 0
    err = 0
    msgs: List[str] = []

    work: List[ModItem] = []
    skipped_missing: List[str] = []
    for nm in names:
        m = all_mods.get(nm)
        if not m:
            skipped_missing.append(nm)
            continue
        if not m.installed:
            work.append(m)

    total = len(work)
    if skipped_missing:
        for nm in skipped_missing:
            msgs.append(f"Skipped: {nm} (not in source)")

    if total == 0:
        msgs.append("Nothing to install (all present or missing).")
        return ok, err, msgs

    for idx, mod in enumerate(work, start=1):
        print(f"[{idx}/{total}] Installing {mod.name} ...")
        success, msg = apply_mod(mod)
        if success:
            ok += 1
        else:
            err += 1
        msgs.append(f"{mod.name}: {'OK' if success else 'ERR'} ({msg})")

    print(f"Done: installed {ok}/{total}. Errors: {err}.")
    return ok, err, msgs

def deactivate_preset(cfg: Dict, name: str) -> Tuple[int, int, List[str]]:
    presets = load_presets()
    mods = {m.name: m for m in discover_mods(cfg)}
    names = presets.get(name, [])
    ok = 0
    fail = 0
    msgs = []
    for nm in names:
        m = mods.get(nm)
        if not m or not m.installed:
            continue
        success, msg = deactivate_mod(m)
        if success:
            ok += 1
        else:
            fail += 1
        msgs.append(f"{nm}: {'OK' if success else 'ERR'} ({msg})")
    return ok, fail, msgs

# ----------------------------- Text Interface -----------------------------

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

# ---- Open Folders ----

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

# ---- Fix Broken Links ----

def menu_fix_broken(cfg: Dict):
    if not ensure_paths(cfg):
        return
    broken = list_broken_links(cfg)
    page = 1
    while True:
        os.system("cls" if is_windows() else "clear")
        broken = list_broken_links(cfg)
        if not broken:
            print("No broken links detected.")
            return
        page, pages = paginate(len(broken), page, cfg)
        shown = page_slice(broken, page)
        print("Fix broken links — remove game links whose source is missing")
        print("=" * PRINT_SIZE)
        for i, m in enumerate(shown, 1):
            kind = "DIR" if m.is_dir else "FILE"
            print(f"{i:2d}) [!] {m.name} ({kind})  -> missing source: {m.src}")
        print_pager(pages, page)
        print("0) Back  |  pN to change page  |  a) Remove ALL on page  |  numbers (comma-separated) to remove selected")
        choice = prompt("> ").strip().lower()
        if choice == "0":
            return
        if choice == "a":
            for m in shown:
                deactivate_mod(m)
            print("Removed all broken links on this page.")
            continue
        page_sel = parse_page_choice(choice)
        if page_sel:
            page = page_sel
            continue
        nums = parse_multi_choice(choice)
        for num in nums:
            if 1 <= num <= len(shown):
                m = shown[num - 1]
                ok, msg = deactivate_mod(m)
                print(f"Remove {m.dest.name}: {'OK' if ok else 'ERR'} — {msg}")

# ----------------------------- Menus -----------------------------

def menu_settings(cfg: Dict):
    while True:
        os.system("cls" if is_windows() else "clear")
        print("Settings")
        print("=" * PRINT_SIZE)
        print(f"1) Game mods folder: {cfg.get('game_mods_dir') or '-not set-'}")
        print(f"2) Mods source folder: {cfg.get('mods_source_dir') or '-not set-'}")
        print(f"3) Mod file extensions: {cfg.get('mod_extensions') or '(all)'}")
        print(f"4) Page size: {cfg.get('page_size') or 10}")
        print("\n0) Save and back\n")
        choice = prompt("Select [0-4]: ").strip()
        if choice == "1":
            p = prompt("Enter full path to game mods folder: ").strip().strip('"')
            cfg["game_mods_dir"] = str(Path(p).expanduser()) if p else cfg.get("game_mods_dir", "")
        elif choice == "2":
            p = prompt("Enter full path to mods source folder: ").strip().strip('"')
            cfg["mods_source_dir"] = str(Path(p).expanduser()) if p else cfg.get("mods_source_dir", "")
        elif choice == "3":
            p = prompt("Enter extensions (comma-separated) or leave empty for all: ").strip()
            cfg["mod_extensions"] = p
        elif choice == "4":
            p = prompt("Enter page size: ").strip()
            if p.isdigit() and int(p) > 0:
                cfg["page_size"] = int(p)
            else:
                print("incorect format, please enter a number")
        elif choice == "0":
            save_config(cfg)
            print("Saved.")
            return

def filter_items_by_query(items: List[ModItem], query: str) -> List[ModItem]:
    q = (query or "").lower()
    if not q:
        return items
    return [m for m in items if q in m.name.lower()]

# ---- Sorting support ----

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

# Unified mods list & toggle (install/uninstall) with search

def menu_mods_toggle(cfg: Dict):
    if not ensure_paths(cfg):
        return
    page = 1
    last_operation = ""
    search_query = ""
    label_filter = ""
    order_mode = "d"
    while True:
        os.system("cls" if is_windows() else "clear")
        items_all = discover_mods(cfg)
        items = filter_items_by_query(items_all, search_query)
        labels = load_labels()
        if label_filter:
            lf = label_filter.lower()
            items = [m for m in items if (labels.get(m.name) or "").lower() == lf]
        items = sort_items(items, order_mode)
        if not items:
            print("Mods — install/uninstall (toggle)")
            print("=" * PRINT_SIZE)
            if order_mode == "d":
                print("Order: default ↓")
            else:
                print("Order: created date ↓")
            if label_filter:
                print(f"Label: '{label_filter}'")
            if search_query:
                print(f"Filter: '{search_query}' (no matches)")
            else:
                print("Filter: '' (no matches)")
            print("\nCommands:")
            print("  - f <text>: (filter)")
            print('  - l "labelName": (label filter)')
            print('  - label add/remove "file name" "labelName"')
            print("  - o: <orderType> order mode (d or default, cd or created date)")
            print("  - clear: (clear filter)")
            print("  - 0: Back")
            print(f"    {last_operation}")
            choice = prompt("> ").strip()
            if choice == "0":
                return
            low = choice.lower()
            if low == "clear":
                search_query = ""
                label_filter = ""
                continue
            if low.startswith("f ") or low.startswith("find "):
                search_query = choice.split(" ", 1)[1].strip()
                page = 1
                continue
            if low.startswith("l ") or low.startswith("l:"):
                label_filter = choice.split(" ", 1)[1].strip().strip('"')
                page = 1
                continue
            if low.startswith("label "):
                try:
                    args = shlex.split(choice)
                except ValueError:
                    continue
                if len(args) == 4 and args[1].lower() in ["add", "remove"]:
                    action = args[1].lower()
                    file_name = args[2]
                    label_name = args[3]
                    labels = load_labels()
                    if action == "add":
                        labels[file_name] = label_name
                        save_labels(labels)
                    else:
                        if labels.get(file_name) == label_name:
                            labels.pop(file_name, None)
                            save_labels(labels)
                continue
            # anything else just continue
            continue
        page, pages = paginate(len(items), page, cfg)
        shown = page_slice(items, page, cfg)
        print("Mods — install/uninstall (toggle)")
        print("=" * PRINT_SIZE)
        if order_mode == "d":
            print("Order: default ↓")
        else:
            print("Order: created date ↓")
        if label_filter:
            print(f"Label: '{label_filter}'")
        if search_query:
            print(f"Filter: '{search_query}'")
        for i, m in enumerate(shown, 1):
            mark = "[X]" if m.installed else "[ ]"
            kind = "DIR" if m.is_dir else "FILE"
            prefix = f"{i:2d}) {mark} "
            print(f"{prefix}{m.name} ({kind})")
            if label_filter == "":
                lbl = labels.get(m.name) if labels else None
                print(f"{' ' * len(prefix)}{lbl if lbl else '-'}\n")
        print("")
        print_pager(pages, page)
        print("Commands:")
        print("  - f: <text> (search) | clear: (clear search filter)")
        print('  - l <labelName>: (label filter)')
        print('  - label <add|remove> (labelName) (fileName)')
        print("  - o: <orderType> order mode (d or default, cd or created date)")
        print("  - numbers (comma-separated): toggle selected")
        print("  - a: Uninstall ALL (current page)")
        print("  - i: Install ALL (current page)")
        print("  - pN: go to page N   |   0: back")
        print(f"    {last_operation}")
        choice = prompt("> ").strip()
        if choice == "0":
            return
        low = choice.lower()
        if low == "clear":
            search_query = ""
            label_filter = ""
            page = 1
            continue
        if low.startswith("f ") or low.startswith("find "):
            search_query = choice.split(" ", 1)[1].strip()
            page = 1
            continue
        if low.startswith("l ") or low.startswith("l:"):
            label_filter = choice.split(" ", 1)[1].strip().strip('"')
            page = 1
            continue
        if low.startswith("label "):
            try:
                args = shlex.split(choice)
            except ValueError:
                continue
            if len(args) == 4 and args[1].lower() in ["add", "remove"]:
                action = args[1].lower()
                label_name = args[2]
                file_name = get_mod_file_name(items, page, args[3], cfg)
                labels = load_labels()
                if action == "add":
                    labels[file_name] = label_name
                    save_labels(labels)
                    last_operation = f'Label added: {file_name} -> {label_name}'
                else:
                    if labels.get(file_name) == label_name:
                        labels.pop(file_name, None)
                        save_labels(labels)
                        last_operation = f'Label removed: {file_name} -> {label_name}'
                    else:
                        last_operation = "Label not found."
            else:
                last_operation = 'Use: label add/remove "file name" "labelName"'
            continue
        if low.startswith("o "):
            arg = low.split(" ", 1)[1].strip()
            if arg in ["d", "default"]:
                order_mode = "d"
                print("Order mode set to: default")
            elif arg in ["cd", "created date"]:
                order_mode = "cd"
                last_operation = "Order mode set to: created date"
            else:
                last_operation = "Invalid order mode. Use: d, default, cd, or created date."
            continue
        if low == "a":
            for idx, m in enumerate(shown, start=1):
                if m.installed:
                    print(f"[{idx}/{len(shown)}] Uninstalling {m.name} ...")
                    deactivate_mod(m)
            last_operation = "All on this page uninstalled."
            continue
        if low == "i":
            to_install = [m for m in shown if not m.installed]
            total = len(to_install)
            err = 0
            for idx, m in enumerate(to_install, start=1):
                print(f"[{idx}/{total}] Installing {m.name} ...")
                ok, msg = apply_mod(m)
                if not ok:
                    err += 1
                    print(f"  ERR — {msg}")
            print(f"Installed {len(to_install) - err}/{total} on this page. Errors: {err}.")
            if total > 0 & err > 0:
                pause()
            continue
        page_sel = parse_page_choice(choice)
        if page_sel:
            page = page_sel
            continue
        nums = parse_multi_choice(choice)
        for num in nums:
            if 1 <= num <= len(shown):
                m = shown[num - 1]
                if m.installed:
                    ok, msg = deactivate_mod(m)
                    last_operation = f"Uninstall {m.name}: {'OK' if ok else 'ERR'} — {msg}"
                else:
                    ok, msg = apply_mod(m)
                    last_operation = f"Install {m.name}: {'OK' if ok else 'ERR'} — {msg}"

# Unified presets: save/apply/toggle/delete

def menu_presets(cfg: Dict):
    if not ensure_paths(cfg):
        return
    last_operation = ""
    page = 1
    while True:
        os.system("cls" if is_windows() else "clear")
        presets = load_presets()
        keys = list(presets.keys())
        if not keys:
            print("No presets saved.")
        page, pages = paginate(len(keys) if keys else 1, page, cfg)
        page_keys = page_slice(keys, page)

        items = discover_mods(cfg)
        installed_set = {m.name for m in items if m.installed}
        print("Presets — save/apply(toggle)/delete")
        print("=" * PRINT_SIZE)
        for i, key in enumerate(page_keys, 1):
            mods = presets[key]
            all_on = bool(mods) and all(nm in installed_set for nm in mods)
            mark = "[X]" if all_on else "[ ]"
            print(f"{i:2d}) {mark} {key}  — {len(mods)} mods")
        print("\n")
        print_pager(pages, page)
        print("Commands:")
        print("  - numbers (comma-separated): toggle selected preset(s)")
        print("  - s: save current installed as a new preset (will ask for name)")
        print("  - d N,N2,...: delete selected presets by number(s)")
        print("  - pN: go to page N   |   0: back")
        print(f"    {last_operation}")
        choice = prompt("> ").strip()
        if choice == "0":
            return
        # save new preset
        low = choice.strip().lower()

        if low == "s" or low == "s:":
            name = prompt("Enter new preset name: ").strip()
            if not name:
                print("Canceled — empty name")
            else:
                ok, msg = save_preset_from_installed(cfg, name)
                print(msg)
            continue

        if low.startswith("s ") or low.startswith("s:"):
            # support: s name | s: name | s "name with spaces"
            rest = choice.strip()[1:]  # remove leading 's'
            if rest.startswith(":"):
                rest = rest[1:]
            rest = rest.strip()

            if not rest:
                print('Error: missing preset name. Use: s <name> or s "name with spaces"')
                continue

            try:
                args = shlex.split(rest)
            except ValueError:
                print('Error: invalid name format. If you need spaces use: s "імя"')
                continue

            if len(args) != 1:
                print('Error: preset name must be exactly 1 argument. If you need spaces use: s "імя"')
                continue

            name = args[0].strip()
            if not name:
                print("Canceled — empty name")
                continue

            ok, msg = save_preset_from_installed(cfg, name)
            print(msg)
            continue
        # delete presets by numbers
        low = choice.lower()
        if low.startswith("d ") or low.startswith("del "):
            after = low.split(" ", 1)[1].strip()
            nums = parse_multi_choice(after)
            to_delete = []
            for num in nums:
                if 1 <= num <= len(page_keys):
                    to_delete.append(page_keys[num - 1])
            count, missing = delete_presets_by_names(to_delete)
            last_operation = f"Deleted: {count}. Missing: {', '.join(missing) if missing else 'none'}"
            continue
        # page change
        page_sel = parse_page_choice(choice)
        if page_sel:
            page = page_sel
            continue
        # toggle presets by numbers
        nums = parse_multi_choice(choice)
        for num in nums:
            if 1 <= num <= len(page_keys):
                name = page_keys[num - 1]
                mods = presets.get(name, [])
                all_on = bool(mods) and all(nm in installed_set for nm in mods)
                if all_on:
                    okc, errc, msgs = deactivate_preset(cfg, name)
                    last_operation = f"Deactivated: {okc}, Errors: {errc}"
                else:
                    okc, errc, msgs = apply_preset(cfg, name)
                    last_operation = f"Installed: {okc}, Errors: {errc}"
                    if errc > 0:
                        pause()
                for m in msgs:
                    print(" - ", m)


def main_menu():
    cfg = load_config()
    while True:
        os.system("cls" if is_windows() else "clear")
        print("Mod Manager — Menu")
        print("=" * PRINT_SIZE)
        print("1) ⚙️ Settings")
        print("2) 🔄 Mods    - list, toggle, search")
        print("3) 🗃️ Presets - save,  apply, toggle, delete")
        print("4) 📋 Open mods source folder")
        print("5) 📂 Open game mods folder")
        print("6) 🛠️ Fix missing mods")
        print("0) 🏠 Exit")
        choice = prompt("Select [0-6]: ").strip()
        if choice == "1":
            menu_settings(cfg)
            cfg = load_config()
        elif choice == "2":
            menu_mods_toggle(cfg)
        elif choice == "3":
            menu_presets(cfg)
        elif choice == "4":
            ms = load_config().get("mods_source_dir", "")
            ok, msg = open_folder(ms)
            print(f"Open source folder: {'OK' if ok else 'ERR'} — {msg}")
        elif choice == "5":
            gs = load_config().get("game_mods_dir", "")
            ok, msg = open_folder(gs)
            print(f"Open game folder: {'OK' if ok else 'ERR'} — {msg}")
        elif choice == "6":
            menu_fix_broken(cfg)
        elif choice == "0":
            print("Goodbye!")
            return

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nExit…")
