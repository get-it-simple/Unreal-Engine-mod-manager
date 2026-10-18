from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path


def _verify_files(root: Path, files: dict[str, str]) -> None:
    for name, expected in files.items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if actual != expected.lower():
            raise ValueError(f"SHA-256 mismatch: {name}")


def verify_archive_backend(project: Path) -> None:
    root = project / "assets/7zip"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    _verify_files(root, manifest["files"])
    if not (root / "License.txt").is_file():
        raise ValueError("7-Zip license is missing")


def prepare_archive_backend(project: Path) -> None:
    root = project / "assets/7zip"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not (root / "License.txt").is_file():
        raise ValueError("7-Zip license is missing")
    try:
        _verify_files(root, manifest["files"])
    except (OSError, ValueError):
        pass
    else:
        print("7-Zip build dependency is ready (SHA-256 verified).")
        return

    extractor = shutil.which("tar.exe" if os.name == "nt" else "tar")
    if extractor is None:
        raise OSError("Preparing 7-Zip requires tar with 7z support (included in current Windows).")
    cache = project / "build/7zip-package" / manifest["source_sha256"]
    cache.mkdir(parents=True, exist_ok=True)
    package = cache / "7zip-package.exe"
    try:
        _verify_files(cache, {package.name: manifest["source_sha256"]})
    except (OSError, ValueError):
        print(f"Downloading 7-Zip {manifest['version']} from {manifest['source']}")
        with tempfile.TemporaryDirectory(prefix="download-", dir=cache) as temporary:
            download = Path(temporary) / package.name
            with urllib.request.urlopen(manifest["source"], timeout=60) as response:
                with download.open("wb") as output:
                    shutil.copyfileobj(response, output)
            _verify_files(download.parent, {download.name: manifest["source_sha256"]})
            download.replace(package)

    with tempfile.TemporaryDirectory(prefix="prepare-", dir=cache) as temporary:
        staging = Path(temporary)
        subprocess.run(
            [extractor, "-xf", str(package.resolve()), "-C", str(staging.resolve()), *manifest["files"]],
            check=True, capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _verify_files(staging, manifest["files"])
        for name in manifest["files"]:
            (staging / name).replace(root / name)
    verify_archive_backend(project)
    print("7-Zip build dependency prepared (SHA-256 verified).")
