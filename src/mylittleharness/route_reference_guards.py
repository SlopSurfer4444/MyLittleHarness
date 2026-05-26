from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .inventory import Inventory
from .models import Finding
from .parsing import parse_frontmatter
from .reporting import RouteWriteEvidence
from .root_boundary import source_path_boundary_violation


DEFAULT_STATE_REL = "project/project-state.md"
ROADMAP_REL = "project/roadmap.md"
REQUIRED_ROUTE_REFERENCE_STATUSES = {"done", "complete"}
ROOT_RELATIVE_LINK_PREFIXES = (
    ".mylittleharness/",
    ".agents/",
    ".codex/",
    "docs/",
    "project/",
    "specs/",
    "src/",
    "tests/",
)
ROOT_RELATIVE_LINK_NAMES = {"README.md", "AGENTS.md", "pyproject.toml"}
ROADMAP_FIELD_RE = re.compile(r"^- `([^`]+)`: `(.*)`\s*$")


@dataclass(frozen=True)
class RequiredRouteReference:
    source: str
    owner: str
    field: str
    target: str
    owner_status: str
    line: int | None = None

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return (self.source, self.owner, self.field, self.target, self.owner_status)


@dataclass(frozen=True)
class RouteReferenceGuardIssue:
    reference: RequiredRouteReference
    reason: str


def route_reference_transaction_guard_findings(
    inventory: Inventory,
    writes: tuple[RouteWriteEvidence, ...],
    *,
    apply: bool,
) -> list[Finding]:
    issues = _route_reference_transaction_guard_issues(inventory, writes)
    if issues:
        severity = "error" if apply else "warn"
        prefix = "" if apply else "would "
        return [
            Finding(
                severity,
                "route-reference-transaction-guard-unresolved",
                (
                    f"{prefix}refuse required route reference {issue.reference.source}."
                    f"{issue.reference.owner}.{issue.reference.field} -> {issue.reference.target}: "
                    f"{issue.reason}; boundary: no automatic target creation, repair, archive rewrite, "
                    "lifecycle movement, staging, commit, or rollback"
                ),
                issue.reference.source,
                issue.reference.line,
            )
            for issue in issues
        ]

    verb = "verified" if apply else "would verify"
    return [
        Finding(
            "info",
            "route-reference-transaction-guard",
            f"{verb} required route references after planned writes: no unresolved required targets",
        )
    ]


def _route_reference_transaction_guard_issues(
    inventory: Inventory,
    writes: tuple[RouteWriteEvidence, ...],
) -> list[RouteReferenceGuardIssue]:
    changed_writes = tuple(write for write in writes if write.before_text != write.after_text)
    if not changed_writes:
        return []

    final_texts = {_normalize_rel(write.rel_path): write.after_text for write in changed_writes}
    issues: list[RouteReferenceGuardIssue] = []

    for write in changed_writes:
        source_rel = _normalize_rel(write.rel_path)
        after_required = _required_route_references_for_text(source_rel, write.after_text or "")
        for reference in after_required:
            target_rel, reason = _required_target_resolution(inventory, reference.target)
            if reason:
                issues.append(RouteReferenceGuardIssue(reference, reason))
                continue
            assert target_rel is not None
            if not _required_target_exists_after_transaction(inventory, target_rel, final_texts):
                issues.append(
                    RouteReferenceGuardIssue(
                        reference,
                        f"target {target_rel} is absent after the planned transaction",
                    )
                )
    return issues


def _required_route_references_for_text(rel_path: str, text: str) -> tuple[RequiredRouteReference, ...]:
    if not text:
        return ()

    refs: list[RequiredRouteReference] = []
    if rel_path.endswith(".md"):
        frontmatter = parse_frontmatter(text)
        if frontmatter.has_frontmatter:
            data = frontmatter.data
            status = str(data.get("status") or "").strip().casefold()
            if rel_path == DEFAULT_STATE_REL:
                plan_status = str(data.get("plan_status") or "").strip().casefold()
                if plan_status == "active":
                    refs.extend(
                        _reference_values(
                            rel_path,
                            rel_path,
                            "active_plan",
                            data.get("active_plan"),
                            plan_status,
                            text,
                        )
                    )
                refs.extend(
                    _reference_values(
                        rel_path,
                        rel_path,
                        "last_archived_plan",
                        data.get("last_archived_plan"),
                        plan_status,
                        text,
                    )
                )
            if status in REQUIRED_ROUTE_REFERENCE_STATUSES:
                refs.extend(
                    _reference_values(
                        rel_path,
                        rel_path,
                        "archived_plan",
                        data.get("archived_plan"),
                        status,
                        text,
                    )
                )

    if rel_path == ROADMAP_REL:
        refs.extend(_roadmap_required_references(text))

    return tuple(refs)


def _roadmap_required_references(text: str) -> tuple[RequiredRouteReference, ...]:
    refs: list[RequiredRouteReference] = []
    current_title = ""
    current_start = 1
    current_fields: dict[str, object] = {}

    def flush() -> None:
        status = str(current_fields.get("status") or "").strip().casefold()
        if status not in REQUIRED_ROUTE_REFERENCE_STATUSES:
            return
        owner = str(current_fields.get("id") or current_title or ROADMAP_REL).strip()
        refs.extend(
            _reference_values(
                ROADMAP_REL,
                owner,
                "archived_plan",
                current_fields.get("archived_plan"),
                status,
                text,
                fallback_line=current_start,
            )
        )

    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("### "):
            flush()
            current_title = line.strip("# ").strip()
            current_start = line_number
            current_fields = {}
            continue
        match = ROADMAP_FIELD_RE.match(line)
        if match:
            key = match.group(1).strip()
            current_fields[key] = _parse_roadmap_field_value(match.group(2).strip())
    flush()
    return tuple(refs)


def _reference_values(
    source: str,
    owner: str,
    field: str,
    value: object,
    owner_status: str,
    text: str,
    fallback_line: int | None = None,
) -> list[RequiredRouteReference]:
    return [
        RequiredRouteReference(
            source=source,
            owner=owner,
            field=field,
            target=target,
            owner_status=owner_status,
            line=_frontmatter_key_line_from_text(text, field) or fallback_line,
        )
        for target in _path_values(value)
    ]


def _path_values(value: object) -> tuple[str, ...]:
    raw_values: list[str] = []
    if isinstance(value, str):
        raw_values.append(value)
    elif isinstance(value, list):
        raw_values.extend(str(item) for item in value if item not in (None, ""))
    return tuple(
        normalized
        for raw in raw_values
        if (normalized := _normalize_reference_target(raw)) and _value_is_path_like(normalized)
    )


def _parse_roadmap_field_value(value: str) -> object:
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value
        if isinstance(parsed, list):
            return parsed
    return value


def _required_target_resolution(inventory: Inventory, target: str) -> tuple[str | None, str]:
    normalized = _normalize_reference_target(target)
    if not normalized:
        return None, "target is empty"
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", normalized) or normalized.startswith("mailto:"):
        return None, "target is external, not a root-relative route"
    if _is_absolute_path(normalized):
        try:
            rel_path = Path(normalized).expanduser().resolve().relative_to(inventory.root.resolve()).as_posix()
        except (OSError, RuntimeError, ValueError):
            return None, "target is outside the operating root"
    else:
        rel_path = normalized[2:] if normalized.startswith("./") else normalized
    rel_path = _normalize_rel(rel_path)
    if _route_path_is_unsafe(rel_path):
        return rel_path, "target is not a safe root-relative route"
    if "*" in rel_path or "{" in rel_path:
        return rel_path, "required route references must name a concrete target, not a pattern"
    return rel_path, ""


def _required_target_exists_after_transaction(
    inventory: Inventory,
    target_rel: str,
    final_texts: dict[str, str | None],
) -> bool:
    if target_rel in final_texts:
        return final_texts[target_rel] is not None
    target = inventory.root / target_rel
    violation = source_path_boundary_violation(inventory.root, target, label="required route reference target")
    if violation is not None:
        return False
    return target.is_file() and not target.is_symlink()


def _normalize_reference_target(value: object) -> str:
    normalized = str(value or "").strip().strip("`\"'").strip("<>").replace("\\", "/")
    if normalized.startswith("[") and normalized.endswith("]"):
        return ""
    normalized = normalized.split("#", 1)[0]
    return re.sub(r"/+", "/", normalized).strip().rstrip(".,;:)]")


def _normalize_rel(value: object) -> str:
    return re.sub(r"/+", "/", str(value or "").strip().replace("\\", "/")).strip("/")


def _value_is_path_like(value: str) -> bool:
    return (
        value in ROOT_RELATIVE_LINK_NAMES
        or any(value.startswith(prefix) for prefix in ROOT_RELATIVE_LINK_PREFIXES)
        or _is_absolute_path(value)
    )


def _is_absolute_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or Path(value).is_absolute()


def _route_path_is_unsafe(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith(("/", "\\")) or _is_absolute_path(rel_path):
        return True
    return any(part in {"", ".", ".."} for part in Path(rel_path).parts)


def _frontmatter_key_line_from_text(text: str, key: str) -> int | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:", re.IGNORECASE)
    for line_number, line in enumerate(text.splitlines(), start=1):
        if pattern.match(line):
            return line_number
    return None
