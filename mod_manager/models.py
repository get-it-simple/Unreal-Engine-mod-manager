from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

@dataclass
class ModItem:
    name: str
    src: Path
    dest: Path
    is_dir: bool
    installed: bool
