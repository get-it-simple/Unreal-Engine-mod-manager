from __future__ import annotations

import os
import subprocess
from pathlib import Path
import tempfile
from typing import List, Tuple

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
            res = subprocess.run(cmd, capture_output=True, text=True, creationflags=0x08000000)
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

def mklink_batch(items: List[Tuple[Path, Path, bool]]) -> List[Tuple[bool, str]]:
    results: List[Tuple[bool, str]] = [(False, "mklink error") for _ in items]
    if not items:
        return results

    if not is_windows():
        for i, (src, dest, _is_dir) in enumerate(items):
            results[i] = mklink(src, dest)
        return results

    work_idxs: List[int] = []
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".bat", delete=False) as f:
        bat_path = f.name
        for i, (src, dest, is_dir) in enumerate(items):
            if dest.exists() or dest.is_symlink():
                results[i] = (False, f"Target already exists: {dest}")
                continue
            if not src.exists():
                results[i] = (False, f"Source not found: {src}")
                continue

            work_idxs.append(i)
            f.write(f"echo __BEGIN__{i}__\n")
            if is_dir:
                f.write(f'mklink /J "{str(dest)}" "{str(src)}" 2>&1\n')
            else:
                f.write(f'mklink "{str(dest)}" "{str(src)}" 2>&1\n')
            f.write(f"echo __RC__{i}__%errorlevel%\n")
            f.write(f"echo __END__{i}__\n")

    try:
        res = subprocess.run(["cmd", "/c", bat_path], capture_output=True, text=True, creationflags=0x08000000)
        out = (res.stdout or "").splitlines()

        state: dict[int, dict] = {}
        current: int | None = None

        def _is_begin(line: str) -> int | None:
            s = line.strip()
            if s.startswith("__BEGIN__") and s.endswith("__"):
                mid = s[len("__BEGIN__") : -2]
                return int(mid) if mid.isdigit() else None
            return None

        def _is_rc(line: str) -> Tuple[int, int] | None:
            s = line.strip()
            if s.startswith("__RC__") and "__" in s[len("__RC__") :]:
                rest = s[len("__RC__") :]
                a, b = rest.split("__", 1)
                b2 = b.strip()
                if a.isdigit() and b2.isdigit():
                    return int(a), int(b2)
            return None

        def _is_end(line: str) -> int | None:
            s = line.strip()
            if s.startswith("__END__") and s.endswith("__"):
                mid = s[len("__END__") : -2]
                return int(mid) if mid.isdigit() else None
            return None

        for line in out:
            bi = _is_begin(line)
            if bi is not None:
                current = bi
                state[current] = {"lines": [], "rc": None}
                continue

            rci = _is_rc(line)
            if rci is not None:
                idx, rc = rci
                st = state.get(idx)
                if st is not None:
                    st["rc"] = rc
                continue

            ei = _is_end(line)
            if ei is not None:
                current = None
                continue

            if current is not None:
                state[current]["lines"].append(line)

        for i in work_idxs:
            st = state.get(i)
            if not st:
                results[i] = (False, "mklink error")
                continue
            rc = st.get("rc")
            msg = "\n".join((st.get("lines") or [])).strip()
            if rc == 0:
                results[i] = (True, "OK")
            else:
                results[i] = (False, msg or "mklink error")

        return results
    except Exception as e:
        return [(False, str(e)) for _ in items]
    finally:
        try:
            os.remove(bat_path)
        except Exception:
            pass

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