from __future__ import annotations

from typing import Dict, List, Tuple

from .mods import discover_mods, list_installed_mods, apply_mods_batch, deactivate_mod
from .storage import load_presets, save_presets
from .cli_utils import page_slice, paginate

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

def presets_view(cfg: Dict, page: int) -> Tuple[Dict, List[str], List[str], int, int]:
    presets = load_presets()
    keys = list(presets.keys())
    page, pages = paginate(len(keys) if keys else 1, page, cfg)
    page_keys = page_slice(keys, page, cfg)
    return presets, keys, page_keys, page, pages

def delete_presets_by_indexes(cfg: Dict, page: int, indexes: List[int]) -> Tuple[int, List[str]]:
    presets, _keys, page_keys, _page, _pages = presets_view(cfg, page)
    to_delete = []
    for num in indexes:
        if 1 <= num <= len(page_keys):
            to_delete.append(page_keys[num - 1])
    return delete_presets_by_names(to_delete)

def toggle_presets_by_indexes(cfg: Dict, page: int, indexes: List[int], installed_set: set[str]) -> Tuple[str, List[str], bool]:
    presets, _keys, page_keys, _page, _pages = presets_view(cfg, page)
    last_operation = ""
    messages: List[str] = []
    has_errors = False
    for num in indexes:
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
                has_errors = has_errors or errc > 0
            messages.extend(msgs)
    return last_operation, messages, has_errors

def apply_preset(cfg: Dict, name: str) -> Tuple[int, int, List[str]]:
    presets = load_presets()
    all_mods = {m.name: m for m in discover_mods(cfg)}
    names = presets.get(name, [])

    ok = 0
    err = 0
    msgs: List[str] = []

    work: List = []
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

    results = apply_mods_batch(work)
    for mod, (success, msg) in zip(work, results):
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
    
