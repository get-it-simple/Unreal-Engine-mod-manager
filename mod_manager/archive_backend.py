from __future__ import annotations

import atexit
import functools
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from threading import Event

from .import_io import check_cancelled, copy_stream


ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".rar"})
INVALID_WINDOWS_NAME = re.compile(r'[<>:"|?*\x00-\x1f]')
RESERVED_WINDOWS_NAME = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE)


class ArchiveError(ValueError):
    pass


def safe_relative_path(name: str) -> Path:
    normalized = name.replace("\\", "/")
    parts = normalized.rstrip("/").split("/")
    if not normalized or normalized.startswith("/") or any(
        not part or part in {".", ".."} or part.endswith((".", " "))
        or INVALID_WINDOWS_NAME.search(part) or RESERVED_WINDOWS_NAME.match(part)
        for part in parts
    ):
        raise ArchiveError(f"Unsafe archive path: {name!r}")
    return Path(*PurePosixPath(normalized).parts)


@functools.lru_cache(maxsize=1)
def seven_zip_path() -> Path:
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    bundled = resources / "assets" / "7zip" / "7z.exe"
    if bundled.is_file():
        return bundled
    launcher = Path(sys.argv[0])
    if launcher.suffix.lower() == ".pyz" and launcher.is_file():
        owner = tempfile.TemporaryDirectory(prefix="mods-7zip-")
        try:
            with zipfile.ZipFile(launcher) as archive:
                for name in ("7z.exe", "7z.dll"):
                    (Path(owner.name) / name).write_bytes(archive.read(f"assets/7zip/{name}"))
        except Exception:
            owner.cleanup()
            raise
        atexit.register(owner.cleanup)
        return Path(owner.name) / "7z.exe"
    found = shutil.which("7zz") or shutil.which("7z")
    if found:
        return Path(found)
    raise ArchiveError("The bundled 7-Zip is missing. Restore assets/7zip or reinstall the application.")


def _run_seven_zip(arguments: list[str], cancelled: Event | None = None) -> str:
    check_cancelled(cancelled)
    with subprocess.Popen(
        [str(seven_zip_path()), *arguments], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as process:
        while True:
            if cancelled is not None and cancelled.is_set():
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                check_cancelled(cancelled)
            try:
                output, error = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise ArchiveError((error or output).strip() or "7-Zip could not read the archive.")
        return output


def _validate_entries(entries: list[tuple[str, bool]]) -> None:
    seen = {}
    for name, is_directory in entries:
        relative = safe_relative_path(name)
        key = relative.as_posix().casefold()
        if key in seen:
            raise ArchiveError(f"Duplicate archive path: {name}")
        seen[key] = is_directory
    for name, _is_directory in entries:
        relative = safe_relative_path(name)
        for parent in relative.parents:
            if parent != Path(".") and seen.get(parent.as_posix().casefold()) is False:
                raise ArchiveError(f"File and directory conflict: {name}")


def _extract_zip(source: Path, destination: Path, cancelled: Event | None = None) -> None:
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        _validate_entries([(entry.filename, entry.is_dir()) for entry in entries])
        for entry in entries:
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ArchiveError(f"Archive links and special files are unsupported: {entry.filename}")
            if entry.flag_bits & 1:
                raise ArchiveError("Password-protected archives are unsupported.")
        for entry in entries:
            check_cancelled(cancelled)
            target = destination / safe_relative_path(entry.filename)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as incoming, target.open("wb") as outgoing:
                    copy_stream(incoming, outgoing, cancelled)


def _extract_seven_zip(source: Path, destination: Path, cancelled: Event | None = None) -> None:
    listing = _run_seven_zip(["l", "-slt", "-ba", "-sccUTF-8", "--", str(source.resolve())], cancelled)
    records = []
    for block in re.split(r"\r?\n\s*\r?\n", listing.strip()):
        record = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if "Path" in record:
            records.append(record)
    if not records:
        raise ArchiveError("The archive is empty or its file list could not be read.")
    _validate_entries([(record["Path"], record.get("Folder") == "+" or "D" in record.get("Attributes", "")) for record in records])
    for record in records:
        attributes = record.get("Attributes", "")
        if any(record.get(key) for key in ("Symbolic Link", "Hard Link", "Copy Link")) or record.get("Alternate Stream") == "+" or "L" in attributes:
            raise ArchiveError(f"Archive links are unsupported: {record['Path']}")
        if record.get("Encrypted") == "+":
            raise ArchiveError("Password-protected archives are unsupported.")
    _run_seven_zip(["x", "-y", "-sccUTF-8", "-spd", f"-o{destination.resolve()}", "--", str(source.resolve())], cancelled)
    for path in destination.rglob("*"):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ArchiveError(f"Archive links are unsupported: {path.name}")


def extract_archive(source: Path, destination: Path, cancelled: Event | None = None) -> None:
    try:
        if source.suffix.lower() == ".zip":
            _extract_zip(source, destination, cancelled)
        else:
            _extract_seven_zip(source, destination, cancelled)
    except (OSError, zipfile.BadZipFile, RuntimeError, subprocess.SubprocessError) as exc:
        raise ArchiveError(f"Cannot extract {source.name}: {exc}") from exc
