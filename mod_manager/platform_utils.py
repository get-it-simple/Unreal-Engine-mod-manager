from __future__ import annotations

import platform

def is_windows() -> bool:
    return platform.system().lower().startswith("win")
