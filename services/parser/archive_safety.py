"""Bounded archive extraction helpers for untrusted source uploads."""
from __future__ import annotations

import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_COPY_CHUNK_BYTES = 1024 * 1024


class ArchiveLimitExceededError(ValueError):
    """Raised when an archive exceeds configured resource limits."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_members: int
    max_member_bytes: int
    max_extracted_bytes: int
    copy_chunk_bytes: int = DEFAULT_COPY_CHUNK_BYTES


def copy_stream_limited(
    source: Any,
    target: Path,
    *,
    limits: ArchiveLimits,
    member_name: str,
    total_so_far: int = 0,
    member_limit: int | None = None,
) -> int:
    copied = 0
    with target.open("wb") as output:
        while True:
            member_remaining = (
                limits.max_extracted_bytes - total_so_far - copied
                if member_limit is None
                else member_limit - copied
            )
            total_remaining = limits.max_extracted_bytes - total_so_far - copied
            remaining = min(member_remaining, total_remaining)
            read_size = min(limits.copy_chunk_bytes, max(1, remaining + 1))
            chunk = source.read(read_size)
            if not chunk:
                return copied
            if member_limit is not None and copied + len(chunk) > member_limit:
                raise ArchiveLimitExceededError(
                    f"Archive member exceeds maximum size: {member_name}"
                )
            if total_so_far + copied + len(chunk) > limits.max_extracted_bytes:
                raise ArchiveLimitExceededError(
                    "Archive extracted content exceeds maximum size"
                )
            output.write(chunk)
            copied += len(chunk)


def _archive_member_target(extract_dir: Path, member_name: str) -> Path:
    extract_root = extract_dir.resolve()
    target = (extract_root / member_name).resolve()
    try:
        target.relative_to(extract_root)
    except ValueError as exc:
        raise ValueError(f"unsafe archive member: {member_name}") from exc
    return target


def _archive_target_parent_paths(extract_root: Path, target: Path) -> list[Path]:
    relative_target = target.relative_to(extract_root)
    parent_paths: list[Path] = []
    parent_path = extract_root
    for part in relative_target.parts[:-1]:
        parent_path = parent_path / part
        parent_paths.append(parent_path)
    return parent_paths


def _check_archive_member_layout(
    extract_root: Path,
    target: Path,
    member_name: str,
    is_dir: bool,
    archive_files: set[Path],
    archive_dirs: set[Path],
) -> None:
    parent_paths = _archive_target_parent_paths(extract_root, target)
    for parent_path in parent_paths:
        if parent_path in archive_files or (
            parent_path.exists() and not parent_path.is_dir()
        ):
            raise ValueError(f"unsafe archive member: {member_name}")

    if is_dir:
        if target in archive_files or (target.exists() and not target.is_dir()):
            raise ValueError(f"unsafe archive member: {member_name}")
        archive_dirs.update(parent_paths)
        archive_dirs.add(target)
        return

    if target in archive_dirs or (target.exists() and target.is_dir()):
        raise ValueError(f"unsafe archive member: {member_name}")
    archive_dirs.update(parent_paths)
    archive_files.add(target)


def _check_archive_member_count(member_count: int, limits: ArchiveLimits) -> None:
    if member_count > limits.max_members:
        raise ArchiveLimitExceededError("Archive member count exceeds maximum")


def _check_archive_member_size(
    member_name: str,
    size: int,
    limits: ArchiveLimits,
) -> None:
    if size > limits.max_member_bytes:
        raise ArchiveLimitExceededError(
            f"Archive member exceeds maximum size: {member_name}"
        )


def _add_archive_extracted_size(
    total_size: int,
    member_name: str,
    size: int,
    limits: ArchiveLimits,
) -> int:
    _check_archive_member_size(member_name, size, limits)
    next_total = total_size + size
    if next_total > limits.max_extracted_bytes:
        raise ArchiveLimitExceededError("Archive extracted content exceeds maximum size")
    return next_total


def _read_limited_tar_members(
    tar: tarfile.TarFile,
    limits: ArchiveLimits,
) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    extracted_size = 0
    while True:
        member = tar.next()
        if member is None:
            return members
        members.append(member)
        _check_archive_member_count(len(members), limits)
        if not (member.isdir() or member.isfile()):
            raise ValueError(f"unsafe archive member: {member.name}")
        if member.isfile():
            extracted_size = _add_archive_extracted_size(
                extracted_size,
                member.name,
                member.size,
                limits,
            )


def safe_extract_tar_gz(
    archive_path: str | Path,
    extract_dir: str | Path,
    *,
    limits: ArchiveLimits,
) -> list[Path]:
    archive_path = Path(archive_path)
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    extract_root = extract_dir.resolve()

    with tarfile.open(archive_path, "r:gz") as tar:
        members = _read_limited_tar_members(tar, limits)
        archive_files: set[Path] = set()
        archive_dirs: set[Path] = {extract_root}
        for member in members:
            target = _archive_member_target(extract_dir, member.name)
            _check_archive_member_layout(
                extract_root,
                target,
                member.name,
                member.isdir(),
                archive_files,
                archive_dirs,
            )

        written_size = 0
        for member in members:
            target = _archive_member_target(extract_dir, member.name)
            if member.isdir():
                try:
                    target.mkdir(parents=True, exist_ok=True)
                except (FileExistsError, NotADirectoryError) as exc:
                    raise ValueError(f"unsafe archive member: {member.name}") from exc
                continue

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
            except (FileExistsError, NotADirectoryError) as exc:
                raise ValueError(f"unsafe archive member: {member.name}") from exc
            source = tar.extractfile(member)
            if source is None:
                raise ValueError(f"unsafe archive member: {member.name}")
            try:
                with source:
                    written_size += copy_stream_limited(
                        source,
                        target,
                        limits=limits,
                        member_name=member.name,
                        total_so_far=written_size,
                        member_limit=limits.max_member_bytes,
                    )
            except IsADirectoryError as exc:
                raise ValueError(f"unsafe archive member: {member.name}") from exc

    return [path for path in extract_dir.rglob("*") if path.is_file()]


def safe_extract_zip(
    archive_path: str | Path,
    extract_dir: str | Path,
    *,
    limits: ArchiveLimits,
) -> list[Path]:
    archive_path = Path(archive_path)
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    extract_root = extract_dir.resolve()

    with zipfile.ZipFile(archive_path, "r") as zf:
        infos = zf.infolist()
        _check_archive_member_count(len(infos), limits)
        archive_files = set()
        archive_dirs = {extract_root}
        extracted_size = 0
        for info in infos:
            target = _archive_member_target(extract_dir, info.filename)
            if not info.is_dir():
                extracted_size = _add_archive_extracted_size(
                    extracted_size,
                    info.filename,
                    info.file_size,
                    limits,
                )
            _check_archive_member_layout(
                extract_root,
                target,
                info.filename,
                info.is_dir(),
                archive_files,
                archive_dirs,
            )

        written_size = 0
        for info in infos:
            target = _archive_member_target(extract_dir, info.filename)
            if info.is_dir():
                try:
                    target.mkdir(parents=True, exist_ok=True)
                except (FileExistsError, NotADirectoryError) as exc:
                    raise ValueError(f"unsafe archive member: {info.filename}") from exc
                continue

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
            except (FileExistsError, NotADirectoryError) as exc:
                raise ValueError(f"unsafe archive member: {info.filename}") from exc
            try:
                with zf.open(info, "r") as source:
                    written_size += copy_stream_limited(
                        source,
                        target,
                        limits=limits,
                        member_name=info.filename,
                        total_so_far=written_size,
                        member_limit=limits.max_member_bytes,
                    )
            except IsADirectoryError as exc:
                raise ValueError(f"unsafe archive member: {info.filename}") from exc

    return [path for path in extract_dir.rglob("*") if path.is_file()]


def safe_extract_archive(
    archive_path: str | Path,
    extract_dir: str | Path,
    *,
    limits: ArchiveLimits,
) -> list[Path]:
    archive_path = Path(archive_path)
    if archive_path.name.endswith((".tar.gz", ".tgz")):
        return safe_extract_tar_gz(archive_path, extract_dir, limits=limits)
    if archive_path.suffix.lower() == ".zip":
        return safe_extract_zip(archive_path, extract_dir, limits=limits)
    raise ValueError(f"Unsupported archive type: {archive_path.name}")
