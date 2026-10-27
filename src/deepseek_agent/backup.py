"""backup.py — Backup utilities for file modifications."""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

_current_session_id: str | None = None


def set_session_id(session_id: str) -> None:
    global _current_session_id
    _current_session_id = session_id


def get_backup_dir() -> Path:
    global _current_session_id
    if not _current_session_id:
        _current_session_id = f"session_{int(time.time() * 1000)}"
    return Path.cwd() / "backups" / _current_session_id


def create_backup(file_path: str | Path) -> Path | None:
    """Create a backup of a file before modification. Returns the backup path, or None."""
    abs_path = Path(file_path)
    if not abs_path.is_absolute():
        abs_path = Path.cwd() / abs_path

    if not abs_path.exists():
        return None  # No backup needed for new files
    if abs_path.is_dir():
        return None

    backup_root = get_backup_dir()

    relative_path = abs_path.relative_to(Path.cwd()) if _is_relative_to(abs_path, Path.cwd()) else abs_path.name
    backup_path = backup_root / relative_path

    if backup_path.exists():
        # Backup already exists for this session — keep the first one.
        return backup_path

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(abs_path, backup_path)
    return backup_path


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def _read_manifest(manifest_path: Path) -> list:
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _write_manifest(manifest_path: Path, manifest: list) -> None:
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def create_backup_with_metadata(file_path: str | Path, operation: str) -> dict:
    backup_path = create_backup(file_path)

    metadata = {
        "timestamp": int(time.time() * 1000),
        "operation": operation,
        "filePath": str(file_path),
        "backupPath": str(backup_path) if backup_path else None,
        "sessionId": _current_session_id,
        "fileExists": backup_path is not None,
        "originalSize": backup_path.stat().st_size if backup_path else 0,
    }

    backup_dir = get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    log_path = backup_dir / "backup_manifest.json"

    manifest = _read_manifest(log_path)
    manifest.append(metadata)
    _write_manifest(log_path, manifest)

    return metadata


def backup_user_prompt(task_content: str) -> dict:
    if not task_content or not isinstance(task_content, str):
        raise ValueError("Task content must be a non-empty string")

    backup_dir = get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = backup_dir / "backup_manifest.json"
    manifest = _read_manifest(manifest_path)

    existing = next((e for e in manifest if e.get("type") == "user_prompt"), None)
    if existing is not None:
        existing["timestamp"] = int(time.time() * 1000)
        existing["taskContent"] = task_content
        existing["taskLength"] = len(task_content)
        existing["updatedAt"] = datetime.now(timezone.utc).isoformat()
        _write_manifest(manifest_path, manifest)
        return existing

    timestamp = int(time.time() * 1000)
    metadata = {
        "timestamp": timestamp,
        "type": "user_prompt",
        "operation": "backup_user_prompt",
        "sessionId": _current_session_id,
        "taskContent": task_content,
        "taskLength": len(task_content),
        "createdAt": datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).isoformat(),
    }

    manifest.append(metadata)
    _write_manifest(manifest_path, manifest)
    return metadata


def list_backups() -> list:
    log_path = get_backup_dir() / "backup_manifest.json"
    return _read_manifest(log_path)


def clear_backups() -> None:
    backup_dir = get_backup_dir()
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)
