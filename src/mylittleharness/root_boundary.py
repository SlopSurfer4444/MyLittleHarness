from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


LIVE_OPERATING_ROOT = "live_operating_root"
PRODUCT_SOURCE_FIXTURE = "product_source_fixture"
FALLBACK_OR_ARCHIVE = "fallback_or_archive"
AMBIGUOUS_ROOT = "ambiguous"

PRODUCT_SOURCE_OPERATOR_LANE_STEPS = (
    "open a live operating-root plan that declares product-source target_artifacts",
    "edit only those declared product-source files from the product source checkout",
    "run focused product tests from product_source_root",
    "close or archive the operating-root lifecycle through reviewed MLH routes",
    "after plan_status=none, exact-stage and commit only the product-source files",
)
PRODUCT_SOURCE_OPERATOR_LANE_BOUNDARY = (
    "product-source changes require MLH-dev authority, declared target_artifacts, focused tests, "
    "reviewed lifecycle closeout before Git checkpointing, exact local staging, and no public remote mutation"
)

WINDOWS_RESERVED_DEVICE_BASENAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://|^mailto:", re.IGNORECASE)
_WINDOWS_DRIVE_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_DRIVE_RELATIVE_RE = re.compile(r"^[A-Za-z]:(?:$|[^\\/])")


@dataclass(frozen=True)
class BoundaryViolation:
    code: str
    message: str
    path: Path
    rel_path: str


def product_source_operator_lane_summary() -> str:
    steps = "; ".join(PRODUCT_SOURCE_OPERATOR_LANE_STEPS)
    return f"governed product-source operator lane: {steps}; boundary: {PRODUCT_SOURCE_OPERATOR_LANE_BOUNDARY}"


def absolute_path(path: Path | str, *, base: Path | str | None = None) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    root = Path(base).expanduser() if base is not None else Path.cwd()
    return root / candidate


def first_symlink_prefix(root: Path | str, path: Path | str) -> Path | None:
    root_path = absolute_path(root)
    candidate = absolute_path(path, base=root_path)
    try:
        relative = candidate.relative_to(root_path)
    except ValueError:
        return None
    current = root_path
    for part in relative.parts:
        current = current / part
        try:
            if current.is_symlink():
                return current
        except OSError:
            return current
    return None


def path_resolves_within_root(root: Path | str, path: Path | str) -> bool:
    root_path = absolute_path(root)
    candidate = absolute_path(path, base=root_path)
    try:
        candidate.resolve(strict=False).relative_to(root_path.resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def same_resolved_path(first: Path | str, second: Path | str) -> bool:
    try:
        return str(absolute_path(first).resolve()).casefold() == str(absolute_path(second).resolve()).casefold()
    except (OSError, RuntimeError):
        first_text = str(first).replace("/", "\\").rstrip("\\").casefold()
        second_text = str(second).replace("/", "\\").rstrip("\\").casefold()
        return first_text == second_text


def normalize_path_ref(value: object, *, strip_outer_slashes: bool = False) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    return normalized.strip("/") if strip_outer_slashes else normalized


def windows_path_reference_reason(value: object, *, allow_uri: bool = False, allow_rooted: bool = False) -> str | None:
    normalized = normalize_path_ref(value)
    if not normalized:
        return None
    if normalized.startswith("//"):
        return "UNC path"
    if _WINDOWS_DRIVE_ABSOLUTE_RE.match(normalized):
        return "Windows drive-absolute path"
    if _WINDOWS_DRIVE_RELATIVE_RE.match(normalized):
        return "Windows drive-relative path"
    if allow_uri and _URI_SCHEME_RE.match(normalized):
        return None
    if normalized.startswith("/") and not allow_rooted:
        return "rooted path"
    if ":" in normalized:
        return "Windows alternate data stream path"
    if has_reserved_windows_device_basename(normalized):
        return "reserved Windows device basename"
    return None


def has_reserved_windows_device_basename(value: object) -> bool:
    normalized = normalize_path_ref(value)
    for part in normalized.split("/"):
        if not part:
            continue
        basename = part.split(":", 1)[0].rstrip(" .")
        stem = basename.split(".", 1)[0].casefold().upper()
        if stem in WINDOWS_RESERVED_DEVICE_BASENAMES:
            return True
    return False


def record_id_conflict(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "must be non-empty"
    if windows_path_reference_reason(normalized, allow_uri=False, allow_rooted=False):
        return "must not use reserved Windows device names or Windows path aliases"
    return ""


def root_relative_path_conflict(value: object, *, allow_current_dir: bool = False) -> str:
    normalized = normalize_path_ref(value)
    if not normalized:
        return "must be a non-empty root-relative path"
    reason = windows_path_reference_reason(normalized, allow_uri=False, allow_rooted=False)
    if reason in {"UNC path", "Windows drive-absolute path", "rooted path"}:
        return "must be root-relative, not absolute, rooted, or UNC"
    if reason == "Windows drive-relative path":
        return "must be root-relative, not Windows drive-relative"
    if reason == "Windows alternate data stream path":
        return "must not use Windows alternate data stream syntax"
    if reason == "reserved Windows device basename":
        return "must not use reserved Windows device basenames"
    forbidden_parts = {"..", ""}
    if not allow_current_dir:
        forbidden_parts.add(".")
    if any(part in forbidden_parts for part in normalized.split("/")):
        if allow_current_dir:
            return "must not contain parent traversal or empty path segments"
        return "must not contain parent traversal, current-directory, or empty path segments"
    return ""


def hardlink_alias_violation(root: Path | str, path: Path | str, *, label: str = "source path") -> BoundaryViolation | None:
    root_path = absolute_path(root)
    candidate = absolute_path(path, base=root_path)
    try:
        if not candidate.exists() or candidate.is_symlink() or not candidate.is_file():
            return None
        if getattr(candidate.stat(), "st_nlink", 1) <= 1:
            return None
    except OSError:
        return None
    rel_path = root_relative_display(root_path, candidate)
    return BoundaryViolation(
        code="hardlink",
        message=f"{label} has multiple hardlink aliases and is not accepted as source-bound evidence: {rel_path}",
        path=candidate,
        rel_path=rel_path,
    )


def source_path_boundary_violation(root: Path | str, path: Path | str, *, label: str = "source path") -> BoundaryViolation | None:
    root_path = absolute_path(root)
    candidate = absolute_path(path, base=root_path)
    if root_path.is_symlink():
        return BoundaryViolation(
            code="root-symlink",
            message=f"{label} root is a symlink: {root_path}",
            path=candidate,
            rel_path=root_path.as_posix(),
        )
    symlink_prefix = first_symlink_prefix(root_path, candidate)
    if symlink_prefix is not None:
        rel_path = root_relative_display(root_path, symlink_prefix)
        return BoundaryViolation(
            code="symlink",
            message=f"{label} crosses symlink inside root: {rel_path}",
            path=candidate,
            rel_path=rel_path,
        )
    if not path_resolves_within_root(root_path, candidate):
        rel_path = root_relative_display(root_path, candidate)
        return BoundaryViolation(
            code="outside-root",
            message=f"{label} resolves outside root: {rel_path}",
            path=candidate,
            rel_path=rel_path,
        )
    hardlink_violation = hardlink_alias_violation(root_path, candidate, label=label)
    if hardlink_violation is not None:
        return hardlink_violation
    return None


def root_relative_display(root: Path | str, path: Path | str) -> str:
    root_path = absolute_path(root)
    candidate = absolute_path(path, base=root_path)
    try:
        return candidate.relative_to(root_path).as_posix()
    except ValueError:
        return str(candidate)
