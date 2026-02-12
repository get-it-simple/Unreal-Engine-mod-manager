from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Tuple

from .platform_utils import is_windows

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
