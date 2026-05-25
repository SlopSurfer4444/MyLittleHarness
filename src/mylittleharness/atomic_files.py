from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AtomicFileWrite:
    target_path: Path
    tmp_path: Path
    text: str
    backup_path: Path


@dataclass(frozen=True)
class AtomicFileDelete:
    target_path: Path
    backup_path: Path


@dataclass(frozen=True)
class _AppliedOperation:
    operation: AtomicFileWrite | AtomicFileDelete
    had_original: bool


class FileTransactionError(OSError):
    pass


def apply_file_transaction(
    operations: Iterable[AtomicFileWrite | AtomicFileDelete],
    *,
    root: Path | None = None,
) -> tuple[str, ...]:
    planned = tuple(operations)
    if not planned:
        return ()

    _validate_transaction_paths(planned, root=root)

    created_dirs: list[Path] = []
    written_tmps: list[Path] = []
    applied: list[_AppliedOperation] = []
    try:
        for operation in planned:
            if not isinstance(operation, AtomicFileWrite):
                continue
            created_dirs.extend(_missing_parent_dirs(operation.tmp_path))
            operation.tmp_path.parent.mkdir(parents=True, exist_ok=True)
            _write_text_exact(operation.tmp_path, operation.text)
            written_tmps.append(operation.tmp_path)

        for operation in planned:
            had_original = operation.target_path.exists()
            if had_original:
                _replace_path(operation.target_path, operation.backup_path)
            applied.append(_AppliedOperation(operation, had_original))
            if isinstance(operation, AtomicFileWrite):
                _replace_path(operation.tmp_path, operation.target_path)
                _remove_known_path(written_tmps, operation.tmp_path)
    except OSError as exc:
        rollback_errors = _rollback_applied_operations(applied)
        cleanup_errors = _cleanup_temporary_writes(written_tmps)
        cleanup_errors.extend(_cleanup_created_dirs(created_dirs))
        raise FileTransactionError(_transaction_failure_message(exc, rollback_errors + cleanup_errors)) from exc

    return tuple(_cleanup_success_backups(applied))


def _validate_transaction_paths(
    operations: tuple[AtomicFileWrite | AtomicFileDelete, ...],
    *,
    root: Path | None = None,
) -> None:
    targets = [operation.target_path for operation in operations]
    if len(set(targets)) != len(targets):
        raise FileTransactionError("file transaction target paths must be unique")
    backups = [operation.backup_path for operation in operations]
    if len(set(backups)) != len(backups):
        raise FileTransactionError("file transaction backup paths must be unique")
    tmps = [operation.tmp_path for operation in operations if isinstance(operation, AtomicFileWrite)]
    if len(set(tmps)) != len(tmps):
        raise FileTransactionError("file transaction temporary paths must be unique")

    protected = set(targets)
    protected.update(operation.backup_path for operation in operations)
    for operation in operations:
        if operation.backup_path in targets:
            raise FileTransactionError(f"backup path would overwrite another transaction target: {operation.backup_path}")
        if operation.backup_path.exists():
            raise FileTransactionError(f"transaction backup path already exists: {operation.backup_path}")
        if isinstance(operation, AtomicFileWrite):
            if operation.tmp_path in protected:
                raise FileTransactionError(f"temporary write path overlaps transaction target or backup: {operation.tmp_path}")
            if operation.tmp_path.exists():
                raise FileTransactionError(f"temporary write path already exists: {operation.tmp_path}")
    if root is not None:
        _validate_transaction_root_paths(operations, root)


def _validate_transaction_root_paths(operations: tuple[AtomicFileWrite | AtomicFileDelete, ...], root: Path) -> None:
    root_path = _absolute_path(root)
    if root_path.is_symlink():
        raise FileTransactionError(f"transaction root cannot be a symlink: {root}")
    root_resolved = root_path.resolve(strict=False)
    targets = [_validate_path_under_root(operation.target_path, root_path, root_resolved, "target") for operation in operations]
    backups = [_validate_path_under_root(operation.backup_path, root_path, root_resolved, "backup") for operation in operations]
    tmps = [
        _validate_path_under_root(operation.tmp_path, root_path, root_resolved, "temporary")
        for operation in operations
        if isinstance(operation, AtomicFileWrite)
    ]
    if len(set(targets)) != len(targets):
        raise FileTransactionError("file transaction target paths must resolve uniquely within the transaction root")
    if len(set(backups)) != len(backups):
        raise FileTransactionError("file transaction backup paths must resolve uniquely within the transaction root")
    if len(set(tmps)) != len(tmps):
        raise FileTransactionError("file transaction temporary paths must resolve uniquely within the transaction root")


def _validate_path_under_root(path: Path, root_path: Path, root_resolved: Path, label: str) -> Path:
    absolute_path = _absolute_path(path)
    symlink_path = _first_symlink_prefix(root_path, absolute_path)
    if symlink_path is not None:
        raise FileTransactionError(f"file transaction {label} path crosses symlink inside transaction root: {symlink_path}")
    resolved_path = absolute_path.resolve(strict=False)
    try:
        resolved_path.relative_to(root_resolved)
    except ValueError as exc:
        raise FileTransactionError(f"file transaction {label} path is outside transaction root: {path}") from exc
    return resolved_path


def _first_symlink_prefix(root_path: Path, path: Path) -> Path | None:
    try:
        relative = path.relative_to(root_path)
    except ValueError:
        return None
    current = root_path
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return current
    return None


def _absolute_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _rollback_applied_operations(applied: list[_AppliedOperation]) -> list[str]:
    errors: list[str] = []
    for applied_operation in reversed(applied):
        operation = applied_operation.operation
        try:
            if isinstance(operation, AtomicFileWrite) and operation.target_path.exists():
                _unlink_path(operation.target_path)
            if applied_operation.had_original and operation.backup_path.exists():
                _replace_path(operation.backup_path, operation.target_path)
        except OSError as rollback_exc:
            errors.append(f"{operation.target_path}: {rollback_exc}")
    return errors


def _cleanup_temporary_writes(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in tuple(paths):
        try:
            if path.exists():
                _unlink_path(path)
        except OSError as cleanup_exc:
            errors.append(f"{path}: {cleanup_exc}")
    paths.clear()
    return errors


def _cleanup_created_dirs(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in sorted(set(paths), key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except FileNotFoundError:
            pass
        except OSError as cleanup_exc:
            errors.append(f"{path}: {cleanup_exc}")
    paths.clear()
    return errors


def _cleanup_success_backups(applied: list[_AppliedOperation]) -> list[str]:
    warnings: list[str] = []
    for applied_operation in applied:
        backup = applied_operation.operation.backup_path
        if not backup.exists():
            continue
        try:
            _unlink_path(backup)
        except OSError as cleanup_exc:
            warnings.append(f"temporary backup remains at {backup}: {cleanup_exc}")
    return warnings


def _transaction_failure_message(exc: OSError, recovery_errors: list[str]) -> str:
    if recovery_errors:
        details = "; ".join(recovery_errors)
        return f"{exc}; attempted rollback but manual recovery may be needed: {details}"
    return f"{exc}; rolled back completed target writes"


def _remove_known_path(paths: list[Path], path: Path) -> None:
    try:
        paths.remove(path)
    except ValueError:
        pass


def _missing_parent_dirs(path: Path) -> list[Path]:
    missing: list[Path] = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    return missing


def _replace_path(source: Path, target: Path) -> None:
    source.replace(target)


def _unlink_path(path: Path) -> None:
    path.unlink()


def _write_text_exact(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))
