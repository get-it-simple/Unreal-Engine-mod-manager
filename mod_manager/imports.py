from __future__ import annotations

import shutil
import os
import stat
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable
from threading import Event

from .archive_backend import ARCHIVE_EXTENSIONS, ArchiveError, extract_archive, safe_relative_path
from .import_registry import register_directory_mod
from .import_io import check_cancelled, copy_import_file
from .log import logger
from .mods import IMAGE_EXTENSIONS, ensure_mod_records, import_mod_image, parse_extensions, parse_group_extensions


ConflictResolver = Callable[[str], str]


def ignored_extensions(cfg: dict) -> set[str]:
    return {"." + token.strip().lstrip(".").lower() for token in str(cfg.get("import_ignore_extensions") or "").split(",") if token.strip().lstrip(".")}


def ignored_file(path: Path, cfg: dict) -> bool:
    return path.suffix.lower() in ignored_extensions(cfg)


@dataclass(frozen=True)
class ImportUnit:
    name: str
    members: tuple[Path, ...]


@dataclass
class PreparedArchive:
    name: str
    root: Path
    units: list[ImportUnit]
    owner: tempfile.TemporaryDirectory | None = None
    mode: str = "together"
    preserve_structure: bool = False
    selected: set[int] = field(default_factory=set)
    images: dict[int, Path] = field(default_factory=dict)
    source_name: str = ""

    def close(self) -> None:
        if self.owner is not None:
            self.owner.cleanup()
            self.owner = None


@dataclass(frozen=True)
class PlannedMod:
    name: str
    files: tuple[tuple[Path, Path], ...]
    is_directory: bool
    image: Path | None = None
    replace_existing: bool = False
    directories: tuple[Path, ...] = ()

    @property
    def targets(self) -> tuple[str, ...]:
        return (self.name,) if self.is_directory else tuple(relative.name for _source, relative in self.files)


def scan_units(root: Path, cfg: dict) -> list[ImportUnit]:
    show_all, extensions, _include_folders = parse_extensions(cfg)
    grouped = parse_group_extensions(cfg)
    members = []
    for source in sorted(root.rglob("*"), key=lambda path: path.as_posix().casefold()):
        if source.is_symlink() or (hasattr(source, "is_junction") and source.is_junction()):
            raise ArchiveError(f"Linked import paths are unsupported: {source.name}")
        if not source.is_file() or ignored_file(source, cfg) or source.suffix.lower() in IMAGE_EXTENSIONS:
            continue
        if not show_all and extensions and source.suffix.lower() not in extensions:
            continue
        if source.suffix.lower() in ARCHIVE_EXTENSIONS:
            continue
        relative = source.relative_to(root)
        safe_relative_path(relative.as_posix())
        members.append(relative)
    return group_members(members, grouped)


def group_members(members: list[Path], grouped: list[str], directories: set[Path] | None = None) -> list[ImportUnit]:
    groups = {}
    for member in dict.fromkeys(members):
        key = (member.parent, member.stem.casefold()) if member.suffix.lower() in grouped and member not in (directories or set()) else member
        groups.setdefault(key, []).append(member)
    units = []
    for members in groups.values():
        if len(members) > 1:
            members.sort(key=lambda path: grouped.index(path.suffix.lower()))
        units.append(ImportUnit(members[0].name, tuple(members)))
    return units


def prepare_archive(source: Path, cfg: dict, cancelled: Event | None = None) -> PreparedArchive:
    owner = tempfile.TemporaryDirectory(prefix="mods-archive-")
    root = Path(owner.name) / "content"
    root.mkdir()
    try:
        check_cancelled(cancelled)
        if source.is_dir():
            for path in source.rglob("*"):
                if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                    raise ArchiveError(f"Linked import paths are unsupported: {path.name}")
            shutil.copytree(source, root, dirs_exist_ok=True, copy_function=lambda source, target: copy_import_file(Path(source), Path(target), cancelled))
        else:
            snapshot = Path(owner.name) / f"source{source.suffix.lower()}"
            copy_import_file(source, snapshot, cancelled)
            extract_archive(snapshot, root, cancelled)
        check_cancelled(cancelled)
        units = scan_units(root, cfg)
        if not units:
            raise ArchiveError(f"No supported mod files in {source.name}.")
        prepared = PreparedArchive(
            source.name if source.is_dir() else source.stem, root, units, owner,
            str(cfg.get("archive_import_mode") or "together"),
            bool(cfg.get("archive_preserve_structure", False)), set(range(len(units))),
        )
        prepared.source_name = source.name
        return prepared
    except Exception:
        owner.cleanup()
        raise


def _rename_files(files: tuple[tuple[Path, Path], ...], number: int) -> tuple[tuple[Path, Path], ...]:
    return tuple((source, relative.with_name(f"{relative.stem} ({number}){relative.suffix}")) for source, relative in files)


def _container_files(archive: PreparedArchive, choose: ConflictResolver) -> tuple[tuple[Path, Path], ...]:
    groups = []
    for unit in archive.units:
        files = tuple((archive.root / member, member if archive.preserve_structure else Path(member.name)) for member in unit.members)
        names = {relative.as_posix().casefold() for _source, relative in files}
        collisions = [group for group in groups if names & {relative.as_posix().casefold() for _source, relative in group}]
        if collisions:
            decision = choose(f"{archive.name}: {unit.members[0].as_posix()}")
            if decision == "skip":
                continue
            if decision == "replace":
                groups = [group for group in groups if group not in collisions]
            else:
                taken = {relative.as_posix().casefold() for group in groups for _source, relative in group}
                number = 1
                while any(relative.as_posix().casefold() in taken for _source, relative in _rename_files(files, number)):
                    number += 1
                files = _rename_files(files, number)
        groups.append(files)
    return tuple(member for group in groups for member in group)


def create_plans(archives: list[PreparedArchive], choose: ConflictResolver) -> list[PlannedMod]:
    plans = []
    for archive in archives:
        if archive.mode == "together":
            files = _container_files(archive, choose)
            if files:
                plans.append(PlannedMod(archive.name, files, True))
        else:
            for index, unit in enumerate(archive.units):
                if index not in archive.selected:
                    continue
                preserve = archive.preserve_structure
                name = Path(unit.name).stem if preserve else unit.name
                files = tuple((archive.root / member, member if preserve else Path(member.name)) for member in unit.members)
                plans.append(PlannedMod(name, files, preserve, archive.images.get(index)))
    return plans


def resolve_plans(cfg: dict, plans: list[PlannedMod], choose: ConflictResolver, existing_names: set[str] | None = None) -> list[PlannedMod]:
    root = Path(cfg["mods_source_dir"]).expanduser()
    existing = {path.name.casefold() for path in root.iterdir()} if root.exists() else set()
    existing.update(name.casefold() for name in (existing_names or set()))
    accepted = []
    for plan in plans:
        safe_relative_path(plan.name)
        taken = existing | {name.casefold() for accepted_plan in accepted for name in accepted_plan.targets} | {"images"}
        names = {name.casefold() for name in plan.targets}
        collision = bool(names & taken)
        decision = choose(plan.name) if collision and "images" not in names else "keep_both"
        if collision:
            if decision == "skip":
                continue
            if decision == "replace":
                accepted = [other for other in accepted if not names & {name.casefold() for name in other.targets}]
                plan = replace(plan, replace_existing=True)
            else:
                number = 1
                original = plan
                while names & taken:
                    if original.is_directory:
                        plan = replace(original, name=f"{original.name} ({number})")
                    else:
                        files = _rename_files(original.files, number)
                        plan = replace(original, name=files[0][1].name, files=files)
                    names = {name.casefold() for name in plan.targets}
                    number += 1
        accepted.append(plan)
    return accepted


def regular_import_tasks(cfg: dict, paths: list[Path], existing: set[str], choose: ConflictResolver) -> list[tuple]:
    units = group_members(paths, parse_group_extensions(cfg), {path for path in paths if path.is_dir()})
    plans = [PlannedMod(unit.name, tuple((path, Path(path.name)) for path in unit.members), unit.members[0].is_dir()) for unit in units]
    plans = resolve_plans(cfg, plans, choose, existing)
    tasks = []
    for plan in plans:
        if len(plan.files) > 1:
            tasks.append(("group", plan, "", plan.replace_existing))
        else:
            source = plan.files[0][0]
            tasks.append(("mod", source, plan.name if plan.name != source.name else "", plan.replace_existing))
    return tasks


def _retry_remove(function, name, error) -> None:
    if not isinstance(error[1], PermissionError) or function not in (os.unlink, os.rmdir):
        raise error[1]
    Path(name).chmod(stat.S_IREAD | stat.S_IWRITE)
    function(name)


def _remove_import_path(path: Path) -> None:
    if hasattr(path, "is_junction") and path.is_junction():
        path.rmdir()
    elif path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onerror=_retry_remove)
    else:
        if path.exists() and not path.is_symlink():
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
        path.unlink(missing_ok=True)


def _publish_files(cfg: dict, plan: PlannedMod, cancelled: Event | None) -> tuple[bool, str]:
    root = Path(cfg["mods_source_dir"]).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=".mod-import-", dir=root))
    published, backups = [], []
    retain_backups = False
    try:
        payload = workspace / "payload"
        payload.mkdir()
        check_cancelled(cancelled)
        if safe_relative_path(plan.name).name != plan.name or plan.name.casefold() == "images":
            raise ValueError(f"Invalid mod name: {plan.name}")
        for relative in plan.directories:
            (payload / safe_relative_path(relative.as_posix())).mkdir(parents=True, exist_ok=True)
        for source, relative in plan.files:
            relative = safe_relative_path(relative.as_posix())
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            copy_import_file(source, target, cancelled)
        writes = [(payload, root / plan.name)] if plan.is_directory else [(payload / relative, root / relative.name) for _source, relative in plan.files]
        for index, (source, target) in enumerate(writes):
            check_cancelled(cancelled)
            if target.exists() or target.is_symlink():
                if not plan.replace_existing:
                    raise FileExistsError(f"Already exists: {target.name}")
                backup = workspace / f"backup-{index}"
                original = next((path for path in root.iterdir() if path.name.casefold() == target.name.casefold()), target)
                original.rename(backup)
                backups.append((backup, original))
            source.rename(target)
            published.append(target)
        ensure_mod_records([plan.name])
        if plan.is_directory:
            register_directory_mod(cfg, plan.name)
    except Exception as exc:
        recovery_errors = []
        for path in reversed(published):
            try:
                _remove_import_path(path)
            except OSError as recovery_error:
                recovery_errors.append(str(recovery_error))
        for backup, target in reversed(backups):
            try:
                if target.exists() or target.is_symlink():
                    raise FileExistsError(str(target))
                backup.rename(target)
            except OSError as recovery_error:
                recovery_errors.append(str(recovery_error))
        if recovery_errors:
            retain_backups = True
            return False, f"{plan.name}: {exc}. Recovery incomplete. Original data retained at {workspace}. {'; '.join(recovery_errors)}"
        return False, f"{plan.name}: {exc}"
    finally:
        if not retain_backups:
            try:
                _remove_import_path(workspace)
            except OSError as exc:
                logger.warning("Cannot remove import staging directory %s: %s", workspace, exc)
    return True, plan.name


def publish_plan(cfg: dict, plan: PlannedMod, cancelled: Event | None = None) -> tuple[bool, str]:
    ok, message = _publish_files(cfg, plan, cancelled)
    if not ok:
        return ok, message
    if plan.image:
        try:
            ok, message = import_mod_image(cfg, plan.name, plan.image)
            if not ok:
                return True, f"{plan.name} (preview failed: {message})"
        except Exception as exc:
            return True, f"{plan.name} (preview failed: {exc})"
    return True, plan.name


def execute_plans(cfg: dict, plans: list[PlannedMod], cancelled: Event | None = None) -> tuple[list[str], list[str]]:
    imported, failed = [], []
    for plan in plans:
        if cancelled is not None and cancelled.is_set():
            failed.append("Import cancelled.")
            break
        try:
            ok, message = publish_plan(cfg, plan, cancelled)
        except (OSError, ValueError) as exc:
            ok, message = False, f"{plan.name}: {exc}"
        (imported if ok else failed).append(message)
    return imported, failed
