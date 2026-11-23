from __future__ import annotations

import fcntl
import os
import shutil
import time
from pathlib import Path

from .paths import ARTIFACT_LOCK_PATH, artifact_root


TTL_SECONDS = 48 * 60 * 60
MAX_BYTES = 500 * 1024 * 1024


def _files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def prune_artifacts(
    root: Path | None = None,
    *,
    ttl_seconds: int = TTL_SECONDS,
    max_bytes: int = MAX_BYTES,
    now: float | None = None,
    active_roots: list[Path] | tuple[Path, ...] = (),
    protected_paths: list[Path] | tuple[Path, ...] = (),
) -> dict[str, int | float]:
    root = (root or artifact_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    now = time.time() if now is None else now
    active = {(path.resolve()) for path in active_roots}
    protected = {(path.resolve()) for path in protected_paths}

    ARTIFACT_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ARTIFACT_LOCK_PATH.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            removed_age = 0
            removed_size = 0
            live: list[tuple[float, int, Path]] = []
            protected_files: list[tuple[float, int, Path]] = []
            for path in _files(root):
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                is_protected = path.resolve() in protected or any(
                    path.resolve().is_relative_to(active_root) for active_root in active
                )
                age = now - stat.st_mtime
                if is_protected:
                    protected_files.append((stat.st_mtime, stat.st_size, path))
                    continue
                if age > ttl_seconds:
                    try:
                        path.unlink()
                        removed_age += 1
                        removed_size += stat.st_size
                    except FileNotFoundError:
                        pass
                else:
                    live.append((stat.st_mtime, stat.st_size, path))

            total = sum(size for _, size, _ in live) + sum(
                size for _, size, _ in protected_files
            )
            for _, size, path in sorted(live):
                if total <= max_bytes:
                    break
                try:
                    path.unlink()
                    total -= size
                    removed_size += size
                    removed_age += 1
                except FileNotFoundError:
                    pass

            for path in sorted(root.rglob("*"), reverse=True):
                if path.is_dir():
                    try:
                        path.rmdir()
                    except OSError:
                        pass

            return {
                "removed_files": removed_age,
                "removed_bytes": removed_size,
                "remaining_bytes": max(0, total),
                "root": str(root),
            }
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def new_artifact_path(name: str, suffix: str = ".yml") -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
    root = artifact_root()
    session_dir = root / safe
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir / f"{int(time.time() * 1000)}{suffix}"


def copy_to_artifact(source: Path, name: str) -> Path:
    target = new_artifact_path(name, source.suffix or ".bin")
    shutil.copy2(source, target)
    prune_artifacts()
    return target


def disk_free_bytes(path: Path) -> int:
    usage = shutil.disk_usage(path)
    return usage.free


def relative_to_artifact_root(path: Path) -> str:
    root = artifact_root().resolve()
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.chmod(temp, mode)
    os.replace(temp, path)
