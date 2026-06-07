from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REQUIRED_RUNTIME_PACKAGES = {"PySide6": "PySide6>=6.7.0"}
REQUIRED_EXE_PACKAGES = {"PyInstaller": "pyinstaller>=6.0.0"}

def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
    else:
        return
    print(f"Removed {path}")

def _clean_before() -> None:
    for target in [
        Path("dist/mod-manager-gui.pyz"),
        Path("dist/mod-manager-gui.exe"),
        Path("dist/mod-manager-gui"),
    ]:
        _remove(target)

def _clean_after() -> None:
    for target in [
        Path("build/mod-manager-gui"),
        Path("mod-manager-gui.spec"),
    ]:
        _remove(target)

def _build_pyz() -> int:
    out_dir = Path("dist")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "mod-manager-gui.pyz"
    files = [Path("app_paths.py"), Path("mod-manager-gui.py")]
    files.extend(sorted(Path("mod_manager").glob("*.py")))
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("__main__.py", "from mod_manager.gui import run_gui\nraise SystemExit(run_gui())\n")
        for path in files:
            zf.write(path, path.as_posix())
    print(f"Built {out_path}")
    return 0

def _missing_packages(modules: dict[str, str]) -> list[str]:
    return [requirement for module, requirement in modules.items() if importlib.util.find_spec(module) is None]

def _prompt_install(packages: list[str]) -> bool:
    if not packages:
        return True
    if not sys.stdin.isatty():
        print(f"Missing required package(s): {', '.join(packages)}")
        print("Run: python -m pip install -r requirements.txt")
        return False
    answer = input(f"Install missing package(s) now: {', '.join(packages)}? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Build cancelled.")
        return False
    cmd = [sys.executable, "-m", "pip", "install", *packages]
    return subprocess.call(cmd) == 0

def _ensure_packages(modules: dict[str, str]) -> bool:
    missing = _missing_packages(modules)
    if not missing:
        return True
    if not _prompt_install(missing):
        return False
    still_missing = _missing_packages(modules)
    if still_missing:
        print(f"Package check failed after install: {', '.join(still_missing)}")
        return False
    return True

def _build_exe(onefile: bool) -> int:
    if not _ensure_packages({**REQUIRED_RUNTIME_PACKAGES, **REQUIRED_EXE_PACKAGES}):
        return 1
    mode = "--onefile" if onefile else "--onedir"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "-y",
        mode,
        "--windowed",
        "--name",
        "mod-manager-gui",
        "mod-manager-gui.py",
    ]
    return subprocess.call(cmd)

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Mod Manager GUI artifacts.")
    artifact = parser.add_mutually_exclusive_group()
    artifact.add_argument("--exe", action="store_true", help="Build an executable with PyInstaller when available.")
    artifact.add_argument("--pyz", action="store_true", help="Build the portable Python archive.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--onefile", action="store_true", help="Build a single executable file.")
    mode.add_argument("--onedir", action="store_true", help="Build an onedir executable.")
    parser.add_argument("--no-clean-before", action="store_true", help="Do not remove old dist artifacts before building.")
    parser.add_argument("--no-clean-after", action="store_true", help="Do not remove build/spec artifacts after building.")
    return parser

def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    build_exe = args.exe or (not args.pyz and os.environ.get("MOD_MANAGER_BUILD_EXE") == "1")
    onefile = args.onefile or (not args.onedir and os.environ.get("MOD_MANAGER_ONEFILE") == "1")
    if not build_exe and not _ensure_packages(REQUIRED_RUNTIME_PACKAGES):
        return 1
    if not args.no_clean_before:
        _clean_before()
    result = _build_exe(onefile) if build_exe else _build_pyz()
    if not args.no_clean_after:
        _clean_after()
    return result

if __name__ == "__main__":
    raise SystemExit(main())
