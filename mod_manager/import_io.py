from __future__ import annotations

import shutil
from pathlib import Path
from threading import Event
from typing import BinaryIO


class ImportCancelled(RuntimeError):
    pass


def check_cancelled(cancelled: Event | None) -> None:
    if cancelled is not None and cancelled.is_set():
        raise ImportCancelled("Import cancelled.")


def copy_stream(incoming: BinaryIO, outgoing: BinaryIO, cancelled: Event | None = None) -> None:
    while True:
        check_cancelled(cancelled)
        chunk = incoming.read(1024 * 1024)
        if not chunk:
            break
        outgoing.write(chunk)


def copy_import_file(source: Path, target: Path, cancelled: Event | None = None) -> None:
    check_cancelled(cancelled)
    with source.open("rb") as incoming, target.open("wb") as outgoing:
        copy_stream(incoming, outgoing, cancelled)
    shutil.copystat(source, target)
