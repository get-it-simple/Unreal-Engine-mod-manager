from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

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
    cmd = [
        pyinstaller,
        "--onefile",
        "--windowed",
        "--name",
        "mod-manager-gui",
        "mod-manager-gui.py",
    ]
    return subprocess.call(cmd)

def main() -> int:
    if os.environ.get("MOD_MANAGER_BUILD_EXE") == "1":
        return _build_exe()
    return _build_pyz()

if __name__ == "__main__":
    raise SystemExit(main())
