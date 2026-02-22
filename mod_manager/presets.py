from __future__ import annotations

from typing import Dict, List, Tuple

from .mods import discover_mods, list_installed_mods, apply_mods_batch, deactivate_mod
from .storage import load_presets, save_presets

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
    