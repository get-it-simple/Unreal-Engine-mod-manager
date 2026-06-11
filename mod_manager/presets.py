from __future__ import annotations

from typing import Dict, List, Tuple

from .mods import discover_mods, list_installed_mods, apply_mods_batch, deactivate_mod
from .storage import load_presets, save_presets, load_preset_records, mark_preset_managed
from .cli_utils import page_slice, paginate

def save_preset_from_installed(cfg: Dict, name: str) -> Tuple[bool, str]:
    presets = load_presets()
    installed = list_installed_mods(cfg)
    if not installed:
        return False, "No installed mods to save"
    presets[name] = [m.name for m in installed]
    save_presets(presets)
    mark_preset_managed(name, "saved")
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

def toggle_presets_by_names(cfg: Dict, names: List[str], installed_set: set[str]) -> Tuple[str, List[str], bool]:
    presets = load_presets()
    last_operation = ""
    messages: List[str] = []
    has_errors = False
    for name in names:
        mods = presets.get(name, [])
        if name not in presets:
            messages.append(f"Skipped: {name} (preset not found)")
            has_errors = True
            continue
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

def presets_view(cfg: Dict, page: int, order_mode: str = "d") -> Tuple[Dict, List[str], List[str], int, int]:
    presets = load_presets()
    records = load_preset_records()
    keys = list(presets.keys())
    reverse = order_mode.startswith("-")
    mode = order_mode[1:] if reverse else order_mode
    if mode == "name":
        keys = sorted(keys, key=lambda k: k.lower(), reverse=reverse)
    elif mode == "mods":
        keys = sorted(keys, key=lambda k: (len(presets.get(k, [])), k.lower()), reverse=reverse)
    elif mode == "last_managed":
        keys = sorted(keys, key=lambda k: (records.get(k, {}).get("last_managed") or "", k.lower()), reverse=reverse)
    elif mode == "state":
        keys = sorted(keys, key=lambda k: (records.get(k, {}).get("state") or "undefined", k.lower()), reverse=reverse)
    page, pages = paginate(len(keys) if keys else 1, page, cfg)
    page_keys = page_slice(keys, page, cfg)
    return presets, keys, page_keys, page, pages

def presets_records() -> Dict[str, Dict]:
    return load_preset_records()

def delete_presets_by_indexes(cfg: Dict, page: int, indexes: List[int]) -> Tuple[int, List[str]]:
    presets, _keys, page_keys, _page, _pages = presets_view(cfg, page)
    to_delete = []
    for num in indexes:
        if 1 <= num <= len(page_keys):
            to_delete.append(page_keys[num - 1])
    return delete_presets_by_names(to_delete)

def toggle_presets_by_indexes(cfg: Dict, page: int, indexes: List[int], installed_set: set[str]) -> Tuple[str, List[str], bool]:
    presets, _keys, page_keys, _page, _pages = presets_view(cfg, page)
    names = [page_keys[num - 1] for num in indexes if 1 <= num <= len(page_keys)]
    return toggle_presets_by_names(cfg, names, installed_set)

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
        mark_preset_managed(name, "applied")
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
    mark_preset_managed(name, "applied")
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
    mark_preset_managed(name, "deactivated")
    return ok, fail, msgs
    
