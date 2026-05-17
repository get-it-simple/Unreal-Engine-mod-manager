from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

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

def _build_exe() -> int:
    pyinstaller = shutil.which("pyinstaller")
    if not pyinstaller:
        return _build_pyz()
    mode = "--onefile" if os.environ.get("MOD_MANAGER_ONEFILE") == "1" else "--onedir"
    cmd = [
        pyinstaller,
        "-y",
        mode,
        "--windowed",
        "--name",
        "mod-manager-gui",
        "mod-manager-gui.py",
    ]
    return subprocess.call(cmd)

def main() -> int:
    _clean_before()
    result = _build_exe() if os.environ.get("MOD_MANAGER_BUILD_EXE") == "1" else _build_pyz()
    _clean_after()
    return result

if __name__ == "__main__":
    raise SystemExit(main())
