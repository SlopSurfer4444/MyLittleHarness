from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .command_discovery import rails_not_cognition_boundary_finding
from .inventory import Inventory
from .models import Finding
from .parsing import parse_frontmatter
from .reporting import RouteWriteEvidence, route_write_findings
from .roadmap import RoadmapItem, roadmap_items_for_diagnostics


INCUBATION_DIR_REL = "project/plan-incubation"
INCUBATION_SOURCE = "MyLittleHarness incubation route"
DEFAULT_PLAN_REL = "project/implementation-plan.md"
ROADMAP_REL = "project/roadmap.md"
NON_AUTHORITY_NOTE = (
    "incubation is temporary synthesis; promoted research/spec/plan/state remains authority when accepted."
)
RELATIONSHIP_FIELDS = (
    "related_plan",
    "related_roadmap",
    "related_roadmap_item",
    "source_incubation",
    "source_research",
    "promoted_to",
    "archived_to",
    "implemented_by",
    "archived_plan",
    "supersedes",
    "superseded_by",
    "merged_into",
    "merged_from",
    "split_from",
    "split_to",
    "rejected_by",
)
INCUBATION_RECONCILE_CLASSES = {
    "active-roadmap-source",
    "archived-covered",
    "promoted-compacted",
    "orphan-needs-triage",
    "duplicate-or-superseded",
    "still-live-followup",
}
RECONCILE_METADATA_FIELDS = (
    "lifecycle_status",
    "resolution",
    "resolved_by",
    "superseded_by",
    "last_reconciled",
)
FINAL_DOCS_DECISIONS = {"updated", "not-needed"}
LIVE_ROADMAP_STATUSES = {"accepted", "active"}
TERMINAL_ROADMAP_STATUSES = {"done", "rejected", "superseded"}
TERMINAL_INCUBATION_STATUSES = {"implemented", "archived", "rejected", "superseded"}
OPEN_THREAD_FRONTMATTER_FIELDS = {
    "contains",
    "open_questions",
    "open_threads",
    "remaining_threads",
    "todo",
    "todos",
}
OPEN_THREAD_HEADING_MARKERS = (
    "open question",
    "open questions",
    "future",
    "follow-up",
    "follow up",
    "followups",
    "remainder",
    "remaining",
    "deferred",
    "todo",
)
_RESERVED_SLUGS = {
    "aux",
    "con",
    "incubation",
    "nul",
    "plan-incubation",
    "prn",
    "project",
    *{f"com{index}" for index in range(1, 10)},
    *{f"lpt{index}" for index in range(1, 10)},
}


@dataclass(frozen=True)
class IncubateRequest:
    topic: str
    note: str
    note_source: str = "--note"
    fix_candidate: bool = False


@dataclass(frozen=True)
class IncubationTarget:
    topic: str
    note: str
    note_source: str
    fix_candidate: bool
    slug: str
    rel_path: str
    path: Path


@dataclass(frozen=True)
class IncubationWritePlan:
    text: str
    frontmatter_repair: str = ""
    relationship_fields: tuple[str, ...] = ()
    relationship_skip: str = ""


@dataclass(frozen=True)
class IncubationReconcileRequest:
    sources: tuple[str, ...] = ()
    lifecycle_classes: tuple[str, ...] = ()


@dataclass(frozen=True)
class IncubationLifecycleClassification:
    rel_path: str
    lifecycle_status: str
    resolution: str
    resolved_by: str
    evidence: str
    superseded_by: str = ""


@dataclass(frozen=True)
class IncubationReconcilePlan:
    rel_path: str
    path: Path
    current_text: str
    updated_text: str
    classification: IncubationLifecycleClassification
    changed_fields: tuple[str, ...]


def make_incubate_request(topic: str | None, note: str | None, note_source: str = "--note", fix_candidate: bool = False) -> IncubateRequest:
    normalized_note = _normalized_note(note)
    if fix_candidate:
        normalized_note = _fix_candidate_note(normalized_note)
    return IncubateRequest(
        topic=_normalized_text(topic),
        note=normalized_note,
        note_source=note_source,
        fix_candidate=fix_candidate,
    )


def make_incubation_reconcile_request(
    sources: list[str] | tuple[str, ...] | None = None,
    lifecycle_classes: list[str] | tuple[str, ...] | None = None,
) -> IncubationReconcileRequest:
    return IncubationReconcileRequest(
        sources=tuple(_normalize_rel(source) for source in sources or () if _normalize_rel(source)),
        lifecycle_classes=tuple(_normalized_item_id(value) for value in lifecycle_classes or () if _normalized_item_id(value)),
    )


def incubate_dry_run_findings(inventory: Inventory, request: IncubateRequest) -> list[Finding]:
    findings = [
        Finding("info", "incubate-dry-run", "incubate proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    target = _incubation_target(inventory, request)
    errors = _incubate_preflight_errors(inventory, request, target)
    if target:
        findings.extend(_target_findings(target, apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "incubate-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing incubation notes",
            )
        )
        return findings
    assert target is not None
    write_plan = _incubation_write_plan(inventory, target, existed=target.path.exists())
    findings.append(_note_body_finding(target))
    if request.fix_candidate:
        findings.append(Finding("info", "incubate-fix-candidate", "would record note with [MLH-Fix-Candidate] tag", target.rel_path))
    findings.extend(_frontmatter_repair_findings(target, write_plan, apply=False))
    findings.extend(_relationship_findings(target, write_plan, apply=False))
    findings.append(_note_posture_finding(target, apply=False))
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "incubate-validation-posture",
            "apply would write only the target incubation note in a live operating root; dry-run writes no files",
            target.rel_path,
        )
    )
    return findings


def incubate_apply_findings(inventory: Inventory, request: IncubateRequest) -> list[Finding]:
    target = _incubation_target(inventory, request)
    errors = _incubate_preflight_errors(inventory, request, target)
    if errors:
        return errors
    assert target is not None

    existed = target.path.exists()
    write_plan = _incubation_write_plan(inventory, target, existed=existed)
    tmp_path = target.path.with_name(f".{target.path.name}.incubate.tmp")
    backup_path = target.path.with_name(f".{target.path.name}.incubate.backup")
    try:
        cleanup_warnings = apply_file_transaction(
            (AtomicFileWrite(target.path, tmp_path, write_plan.text, backup_path),),
            root=inventory.root,
        )
    except OSError as exc:
        return [Finding("error", "incubate-refused", f"incubate apply failed before all target writes completed: {exc}", target.rel_path)]

    findings = [
        Finding("info", "incubate-apply", "incubation note apply started"),
        _root_posture_finding(inventory),
        *_target_findings(target, apply=True),
        _note_body_finding(target),
        *([Finding("info", "incubate-fix-candidate", "recorded note with [MLH-Fix-Candidate] tag", target.rel_path)] if request.fix_candidate else []),
        *_frontmatter_repair_findings(target, write_plan, apply=True),
        *_relationship_findings(target, write_plan, apply=True),
        _note_posture_finding(target, apply=True, existed=existed),
        *_boundary_findings(),
        Finding(
            "info",
            "incubate-validation-posture",
            "run check after apply to verify the live operating root remains healthy; incubation notes are non-authority until promoted",
            target.rel_path,
        ),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "incubate-backup-cleanup", warning, target.rel_path))
    return findings


def incubation_reconcile_dry_run_findings(
    inventory: Inventory,
    request: IncubationReconcileRequest,
) -> list[Finding]:
    findings = [
        Finding("info", "incubation-reconcile-dry-run", "incubation reconciliation proposal only; no files were written"),
        Finding("info", "incubation-reconcile-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    plans, errors = _incubation_reconcile_plans(inventory, request)
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "incubation-reconcile-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing reconciliation metadata",
            )
        )
        return findings
    findings.extend(_incubation_reconcile_plan_findings(plans, apply=False))
    findings.extend(_incubation_reconcile_boundary_findings())
    findings.append(
        Finding(
            "info",
            "incubation-reconcile-validation-posture",
            "apply would write only lifecycle_status, resolution, resolved_by, superseded_by, and last_reconciled metadata on selected incubation notes",
            INCUBATION_DIR_REL,
        )
    )
    return findings


def incubation_reconcile_apply_findings(
    inventory: Inventory,
    request: IncubationReconcileRequest,
) -> list[Finding]:
    plans, errors = _incubation_reconcile_plans(inventory, request)
    if errors:
        return errors

    operations = [
        AtomicFileWrite(
            target_path=plan.path,
            tmp_path=plan.path.with_name(f".{plan.path.name}.incubation-reconcile.tmp"),
            text=plan.updated_text,
            backup_path=plan.path.with_name(f".{plan.path.name}.incubation-reconcile.backup"),
        )
        for plan in plans
        if plan.current_text != plan.updated_text
    ]
    cleanup_warnings: tuple[str, ...] = ()
    if operations:
        try:
            cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
        except FileTransactionError as exc:
            return [
                Finding(
                    "error",
                    "incubation-reconcile-refused",
                    f"incubation reconciliation apply failed before all target writes completed: {exc}",
                    INCUBATION_DIR_REL,
                )
            ]

    findings = [
        Finding("info", "incubation-reconcile-apply", "incubation reconciliation apply started"),
        Finding("info", "incubation-reconcile-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    findings.extend(_incubation_reconcile_plan_findings(plans, apply=True))
    findings.extend(
        route_write_findings(
            "incubation-reconcile-route-write",
            tuple(RouteWriteEvidence(plan.rel_path, plan.current_text, plan.updated_text) for plan in plans),
            apply=True,
        )
    )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "incubation-reconcile-backup-cleanup", warning, INCUBATION_DIR_REL))
    findings.extend(_incubation_reconcile_boundary_findings())
    findings.append(
        Finding(
            "info",
            "incubation-reconcile-validation-posture",
            "run check after apply to verify the live operating root remains healthy; reconciliation metadata is not lifecycle approval",
            INCUBATION_DIR_REL,
        )
    )
    return findings


def _incubation_target(inventory: Inventory, request: IncubateRequest) -> IncubationTarget | None:
    slug = _safe_slug(request.topic)
    if not slug:
        return None
    rel_path = f"{INCUBATION_DIR_REL}/{slug}.md"
    return IncubationTarget(
        topic=request.topic,
        note=request.note,
        note_source=request.note_source,
        fix_candidate=request.fix_candidate,
        slug=slug,
        rel_path=rel_path,
        path=inventory.root / rel_path,
    )


def _incubate_preflight_errors(
    inventory: Inventory,
    request: IncubateRequest,
    target: IncubationTarget | None,
) -> list[Finding]:
    errors: list[Finding] = []
    if not request.topic:
        errors.append(Finding("error", "incubate-refused", "--topic is required and cannot be empty or whitespace-only"))
    if not request.note:
        errors.append(Finding("error", "incubate-refused", "--note is required and cannot be empty or whitespace-only"))
    if request.topic and _topic_looks_like_path(request.topic):
        errors.append(Finding("error", "incubate-refused", "topic looks like a path or reserved filename; provide a plain future-idea topic"))
    if request.topic and target is None:
        errors.append(Finding("error", "incubate-refused", "topic does not produce a safe non-empty ASCII slug"))
    elif target and target.slug in _RESERVED_SLUGS:
        errors.append(Finding("error", "incubate-refused", f"topic slug is reserved or ambiguous: {target.slug!r}"))

    if inventory.root_kind == "product_source_fixture":
        errors.append(
            Finding(
                "error",
                "incubate-refused",
                "target is a product-source compatibility fixture; incubate --apply is refused",
                target.rel_path if target else INCUBATION_DIR_REL,
            )
        )
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(
            Finding(
                "error",
                "incubate-refused",
                "target is fallback/archive or generated-output evidence; incubate --apply is refused",
                target.rel_path if target else INCUBATION_DIR_REL,
            )
        )
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "incubate-refused", f"target root kind is {inventory.root_kind}; incubate requires a live operating root"))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "incubate-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "incubate-refused", "project-state.md frontmatter is required for incubate apply", state.rel_path))
    elif state.frontmatter.errors:
        errors.append(Finding("error", "incubate-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "incubate-refused", "project-state.md is not a regular file", state.rel_path))
    elif state.path.is_symlink():
        errors.append(Finding("error", "incubate-refused", "project-state.md is a symlink", state.rel_path))

    incubation_dir = inventory.root / INCUBATION_DIR_REL
    if _path_escapes_root(inventory.root, incubation_dir):
        errors.append(Finding("error", "incubate-refused", "incubation directory path escapes the target root", INCUBATION_DIR_REL))
    for parent in _parents_between(inventory.root, incubation_dir):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "incubate-refused", f"incubation directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "incubate-refused", f"incubation directory contains a non-directory segment: {rel}", rel))

    if target:
        if _path_escapes_root(inventory.root, target.path):
            errors.append(Finding("error", "incubate-refused", "target note path escapes the target root", target.rel_path))
        elif target.path.exists():
            if target.path.is_symlink():
                errors.append(Finding("error", "incubate-refused", "target note is a symlink; append is refused", target.rel_path))
            elif not target.path.is_file():
                errors.append(Finding("error", "incubate-refused", "target note path exists but is not a regular file", target.rel_path))
    return errors


def _incubation_reconcile_plans(
    inventory: Inventory,
    request: IncubationReconcileRequest,
) -> tuple[tuple[IncubationReconcilePlan, ...], list[Finding]]:
    errors = _incubation_reconcile_preflight_errors(inventory, request)
    if errors:
        return (), errors

    roadmap_items, roadmap_findings = roadmap_items_for_diagnostics(inventory)
    blocking_roadmap_findings = [finding for finding in roadmap_findings if finding.severity in {"error", "warn"}]
    if blocking_roadmap_findings:
        return (), [
            Finding(
                "error",
                "incubation-reconcile-refused",
                f"roadmap item parsing must be clean before incubation reconciliation: {finding.message}",
                finding.source,
                finding.line,
            )
            for finding in blocking_roadmap_findings
        ]

    compacted_history = _compacted_done_roadmap_history(inventory)
    selected_sources = set(request.sources)
    selected_classes = set(request.lifecycle_classes)
    if unknown := sorted(selected_classes - INCUBATION_RECONCILE_CLASSES):
        return (), [
            Finding(
                "error",
                "incubation-reconcile-refused",
                f"unknown --class value(s): {', '.join(unknown)}; expected one of {', '.join(sorted(INCUBATION_RECONCILE_CLASSES))}",
                INCUBATION_DIR_REL,
            )
        ]

    plans: list[IncubationReconcilePlan] = []
    for rel_path, path, current_text in _incubation_reconcile_sources(inventory, selected_sources):
        classification = _classify_incubation_note(
            inventory,
            rel_path,
            current_text,
            roadmap_items,
            compacted_history,
        )
        if selected_classes and classification.lifecycle_status not in selected_classes:
            continue
        updated_text, changed_fields, metadata_error = _text_with_reconcile_metadata(current_text, classification)
        if metadata_error:
            return (), [Finding("error", "incubation-reconcile-refused", metadata_error, rel_path)]
        plans.append(
            IncubationReconcilePlan(
                rel_path=rel_path,
                path=path,
                current_text=current_text,
                updated_text=updated_text,
                classification=classification,
                changed_fields=changed_fields,
            )
        )
    return tuple(plans), []


def _incubation_reconcile_preflight_errors(
    inventory: Inventory,
    request: IncubationReconcileRequest,
) -> list[Finding]:
    errors: list[Finding] = []
    if inventory.root_kind == "product_source_fixture":
        errors.append(Finding("error", "incubation-reconcile-refused", "target is a product-source compatibility fixture; incubation-reconcile --apply is refused", INCUBATION_DIR_REL))
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(Finding("error", "incubation-reconcile-refused", "target is fallback/archive or generated-output evidence; incubation-reconcile --apply is refused", INCUBATION_DIR_REL))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "incubation-reconcile-refused", f"target root kind is {inventory.root_kind}; incubation-reconcile requires a live operating root", INCUBATION_DIR_REL))

    incubation_dir = inventory.root / INCUBATION_DIR_REL
    if incubation_dir.exists():
        if incubation_dir.is_symlink():
            errors.append(Finding("error", "incubation-reconcile-refused", "incubation directory is a symlink", INCUBATION_DIR_REL))
        elif not incubation_dir.is_dir():
            errors.append(Finding("error", "incubation-reconcile-refused", "incubation path exists but is not a directory", INCUBATION_DIR_REL))
    for source in request.sources:
        if _rel_has_absolute_or_parent_parts(source):
            errors.append(Finding("error", "incubation-reconcile-refused", "--source must be root-relative without parent segments", source))
            continue
        if not source.startswith(f"{INCUBATION_DIR_REL}/") or not source.endswith(".md"):
            errors.append(Finding("error", "incubation-reconcile-refused", "--source must be a Markdown note under project/plan-incubation/", source))
            continue
        path = inventory.root / source
        if _path_escapes_root(inventory.root, path):
            errors.append(Finding("error", "incubation-reconcile-refused", "source path escapes the target root", source))
        elif not path.exists():
            errors.append(Finding("error", "incubation-reconcile-refused", "source note does not exist", source))
        elif path.is_symlink():
            errors.append(Finding("error", "incubation-reconcile-refused", "source note is a symlink", source))
        elif not path.is_file():
            errors.append(Finding("error", "incubation-reconcile-refused", "source note is not a regular file", source))
    return errors


def _incubation_reconcile_sources(
    inventory: Inventory,
    selected_sources: set[str],
) -> tuple[tuple[str, Path, str], ...]:
    if selected_sources:
        rows = []
        for rel_path in sorted(selected_sources):
            path = inventory.root / rel_path
            try:
                rows.append((rel_path, path, path.read_text(encoding="utf-8")))
            except OSError:
                continue
        return tuple(rows)
    rows = []
    for surface in sorted(inventory.present_surfaces, key=lambda item: item.rel_path):
        if not surface.rel_path.startswith(f"{INCUBATION_DIR_REL}/") or surface.path.suffix.lower() != ".md":
            continue
        if surface.path.is_symlink() or not surface.path.is_file():
            continue
        rows.append((surface.rel_path, surface.path, surface.content))
    return tuple(rows)


def _classify_incubation_note(
    inventory: Inventory,
    rel_path: str,
    text: str,
    roadmap_items: dict[str, RoadmapItem],
    compacted_history: dict[str, str],
) -> IncubationLifecycleClassification:
    frontmatter = parse_frontmatter(text)
    data = frontmatter.data if frontmatter.has_frontmatter and not frontmatter.errors else {}
    status = _normalized_item_id(data.get("status"))
    related_item = _normalized_item_id(data.get("related_roadmap_item"))
    source_item_id, source_item = _roadmap_source_item(rel_path, roadmap_items)
    item_id = related_item or source_item_id
    item = roadmap_items.get(item_id) if item_id else source_item
    item_status = _normalized_item_id(_roadmap_field_scalar(item, "status") if item else "")

    superseded_by = _first_nonempty(
        _normalize_rel(data.get("superseded_by")),
        _normalize_rel(data.get("merged_into")),
        _normalize_rel(data.get("rejected_by")),
    )
    if status in {"rejected", "superseded"} or superseded_by:
        return IncubationLifecycleClassification(
            rel_path=rel_path,
            lifecycle_status="duplicate-or-superseded",
            resolution="superseded-or-rejected",
            resolved_by=superseded_by or _first_nonempty(_normalize_rel(data.get("rejected_by")), "frontmatter status"),
            evidence=f"incubation status={status or 'unspecified'}; supersession target={superseded_by or 'not recorded'}",
            superseded_by=_normalize_rel(data.get("superseded_by")),
        )

    if item and item_status in LIVE_ROADMAP_STATUSES:
        return IncubationLifecycleClassification(
            rel_path=rel_path,
            lifecycle_status="active-roadmap-source",
            resolution="keep-active",
            resolved_by=f"{ROADMAP_REL} item {item_id}",
            evidence=f"roadmap item {item_id!r} is {item_status}",
        )

    archive_evidence = _archived_coverage_evidence(inventory, data, item)
    if archive_evidence:
        return IncubationLifecycleClassification(
            rel_path=rel_path,
            lifecycle_status="archived-covered",
            resolution="covered-by-archive",
            resolved_by=archive_evidence,
            evidence=f"archive or done-roadmap closeout evidence exists: {archive_evidence}",
        )

    compacted_archive = compacted_history.get(item_id) if item_id else ""
    if (
        compacted_archive
        or (_normalize_rel(data.get("promoted_to")) == ROADMAP_REL and item_id and item_id not in roadmap_items)
        or (item_id and item_status in TERMINAL_ROADMAP_STATUSES)
    ):
        return IncubationLifecycleClassification(
            rel_path=rel_path,
            lifecycle_status="promoted-compacted",
            resolution="promoted-to-compacted-roadmap-history",
            resolved_by=compacted_archive or f"{ROADMAP_REL} item {item_id}",
            evidence=f"roadmap item {item_id!r} is compacted or terminal outside the live execution tail",
        )

    followup_markers = _incubation_followup_markers(text, data)
    if followup_markers:
        return IncubationLifecycleClassification(
            rel_path=rel_path,
            lifecycle_status="still-live-followup",
            resolution="keep-active",
            resolved_by=f"open follow-up marker: {followup_markers[0]}",
            evidence=f"open follow-up marker(s): {', '.join(followup_markers)}",
        )

    relation_values = [data.get(field) for field in RELATIONSHIP_FIELDS]
    if not item_id and not any(_frontmatter_value_is_nonempty(value) for value in relation_values):
        return IncubationLifecycleClassification(
            rel_path=rel_path,
            lifecycle_status="orphan-needs-triage",
            resolution="needs-triage",
            resolved_by="",
            evidence="no roadmap, plan, archive, rejection, supersession, or promotion relationship metadata was found",
        )

    return IncubationLifecycleClassification(
        rel_path=rel_path,
        lifecycle_status="still-live-followup",
        resolution="keep-active",
        resolved_by=f"{ROADMAP_REL} item {item_id}" if item_id else "existing relationship metadata",
        evidence="relationship metadata exists but no terminal archive or compacted coverage proof was found",
    )


def _roadmap_source_item(
    rel_path: str,
    roadmap_items: dict[str, RoadmapItem],
) -> tuple[str, RoadmapItem | None]:
    for item_id, item in roadmap_items.items():
        if _normalize_rel(_roadmap_field_scalar(item, "source_incubation")) == rel_path:
            return item_id, item
    return "", None


def _archived_coverage_evidence(
    inventory: Inventory,
    data: dict[str, object],
    item: RoadmapItem | None,
) -> str:
    candidates = (
        _normalize_rel(data.get("archived_to")),
        _normalize_rel(data.get("archived_plan")),
        _archive_plan_like(_normalize_rel(data.get("implemented_by"))),
        _archive_plan_like(_normalize_rel(data.get("related_plan"))),
    )
    for rel_path in candidates:
        if rel_path and _path_exists_safe(inventory, rel_path):
            return rel_path

    if item is None:
        return ""
    item_status = _normalized_item_id(_roadmap_field_scalar(item, "status"))
    archived_plan = _normalize_rel(_roadmap_field_scalar(item, "archived_plan"))
    verification = _roadmap_field_scalar(item, "verification_summary")
    docs_decision = _roadmap_field_scalar(item, "docs_decision")
    if item_status == "done" and archived_plan and verification and docs_decision in FINAL_DOCS_DECISIONS:
        return archived_plan
    return ""


def _archive_plan_like(value: str) -> str:
    return value if value.startswith("project/archive/plans/") else ""


def _path_exists_safe(inventory: Inventory, rel_path: str) -> bool:
    if _rel_has_absolute_or_parent_parts(rel_path):
        return False
    path = inventory.root / rel_path
    if _path_escapes_root(inventory.root, path):
        return False
    return path.is_file() and not path.is_symlink()


def _compacted_done_roadmap_history(inventory: Inventory) -> dict[str, str]:
    surface = inventory.surface_by_rel.get(ROADMAP_REL)
    if not surface or not surface.exists:
        return {}
    history: dict[str, str] = {}
    pattern = re.compile(r"Compacted done roadmap item `([^`]+)`: archived plan `([^`]+)`")
    for match in pattern.finditer(surface.content):
        history[_normalized_item_id(match.group(1))] = _normalize_rel(match.group(2))
    return history


def _text_with_reconcile_metadata(
    text: str,
    classification: IncubationLifecycleClassification,
) -> tuple[str, tuple[str, ...], str | None]:
    updates = {
        "lifecycle_status": classification.lifecycle_status,
        "resolution": classification.resolution,
        "last_reconciled": date.today().isoformat(),
    }
    if classification.resolved_by:
        updates["resolved_by"] = classification.resolved_by
    if classification.superseded_by:
        updates["superseded_by"] = classification.superseded_by

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text, (), "incubation note frontmatter is required for reconciliation metadata"
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return text, (), "incubation note frontmatter is malformed"

    before_values = {key: _frontmatter_value(text, key) for key in updates}
    updated_text = _text_with_frontmatter_scalars(text, updates)
    changed_fields = tuple(key for key, value in updates.items() if before_values.get(key) != value)
    return updated_text, changed_fields, None


def _incubation_reconcile_plan_findings(
    plans: tuple[IncubationReconcilePlan, ...],
    *,
    apply: bool,
) -> list[Finding]:
    prefix = "" if apply else "would "
    findings: list[Finding] = []
    counts = {key: 0 for key in sorted(INCUBATION_RECONCILE_CLASSES)}
    changed_count = 0
    for plan in plans:
        classification = plan.classification
        counts[classification.lifecycle_status] += 1
        if plan.changed_fields:
            changed_count += 1
        findings.append(
            Finding(
                "info",
                f"incubation-reconcile-{classification.lifecycle_status}",
                (
                    f"{prefix}report {plan.rel_path} structural posture as {classification.lifecycle_status}; "
                    f"resolution={classification.resolution}; resolved_by={classification.resolved_by or 'not-recorded'}; "
                    f"evidence={classification.evidence}"
                ),
                plan.rel_path,
            )
        )
        if plan.changed_fields:
            findings.append(
                Finding(
                    "info",
                    "incubation-reconcile-metadata-updated",
                    f"{prefix}update reconciliation metadata fields: {', '.join(plan.changed_fields)}",
                    plan.rel_path,
                )
            )
    summary = ", ".join(f"{key}={counts[key]}" for key in sorted(counts) if counts[key])
    if not summary:
        summary = "no selected incubation notes"
    findings.append(
        Finding(
            "info",
            "incubation-reconcile-summary",
            f"classified {len(plans)} selected incubation note(s) as report-only structural posture; metadata changes={changed_count}; {summary}",
            INCUBATION_DIR_REL,
        )
    )
    return findings


def _incubation_reconcile_boundary_findings() -> list[Finding]:
    return [
        rails_not_cognition_boundary_finding(INCUBATION_DIR_REL),
        Finding(
            "info",
            "incubation-reconcile-boundary",
            "incubation-reconcile writes only bounded reconciliation frontmatter metadata on selected project/plan-incubation/*.md notes in eligible live operating roots",
            INCUBATION_DIR_REL,
        ),
        Finding(
            "info",
            "incubation-reconcile-authority",
            "reconciliation metadata is diagnostic operating memory; it cannot delete notes, promote roadmap items, repair links, archive plans, stage, commit, or approve lifecycle movement",
            INCUBATION_DIR_REL,
        ),
    ]


def _roadmap_field_scalar(item: RoadmapItem | None, key: str) -> str:
    if item is None:
        return ""
    value = item.fields.get(key)
    if value in (None, "", [], ()):
        return ""
    if isinstance(value, (list, tuple)):
        for entry in value:
            text = str(entry).strip()
            if text:
                return text
        return ""
    return str(value).strip()


def _incubation_followup_markers(text: str, data: dict[str, object]) -> tuple[str, ...]:
    markers: list[str] = []
    for key in OPEN_THREAD_FRONTMATTER_FIELDS:
        if _frontmatter_value_is_nonempty(data.get(key)):
            markers.append(f"frontmatter {key}")
    body = text
    frontmatter = parse_frontmatter(text)
    if frontmatter.has_frontmatter:
        body = "\n".join(text.splitlines()[max(frontmatter.body_start_line - 1, 0) :])
    for heading in re.findall(r"(?m)^#{2,6}\s+(.+?)\s*$", body):
        normalized = re.sub(r"\s+", " ", heading.casefold()).strip()
        if any(marker in normalized for marker in OPEN_THREAD_HEADING_MARKERS):
            markers.append(f"heading {heading.strip()!r}")
    if re.search(r"(?m)^\s*[-*]\s+\[\s\]\s+", body):
        markers.append("unchecked task list item")
    return tuple(dict.fromkeys(markers))


def _target_findings(target: IncubationTarget, apply: bool) -> list[Finding]:
    verb = "target note path" if apply else "would target note path"
    return [
        Finding("info", "incubate-topic", f"normalized topic: {target.topic}; slug: {target.slug}", target.rel_path),
        Finding("info", "incubate-target-note", f"{verb}: {target.rel_path}", target.rel_path),
    ]


def _note_posture_finding(target: IncubationTarget, apply: bool, existed: bool | None = None) -> Finding:
    exists = target.path.exists() if existed is None else existed
    if apply:
        action = "appended to existing same-topic incubation note" if exists else "created same-topic incubation note"
    else:
        action = "would append to existing same-topic incubation note" if exists else "would create same-topic incubation note"
    return Finding("info", "incubate-note-posture", action, target.rel_path)


def _note_body_finding(target: IncubationTarget) -> Finding:
    digest = sha256(target.note.encode("utf-8")).hexdigest()[:16]
    line_count = len(target.note.splitlines()) or 1
    return Finding(
        "info",
        "incubate-note-body",
        f"note input: {target.note_source}; lines={line_count}; chars={len(target.note)}; sha256={digest}",
        target.rel_path,
    )


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "incubate-root-posture", f"root kind: {inventory.root_kind}")


def _boundary_findings() -> list[Finding]:
    return [
        rails_not_cognition_boundary_finding(INCUBATION_DIR_REL),
        Finding(
            "info",
            "incubate-boundary",
            "incubate writes only project/plan-incubation/<safe-topic-slug>.md in eligible live operating roots; it does not repair, archive, stage, commit, or mutate product-source fixtures",
        ),
        Finding(
            "info",
            "incubate-authority",
            "incubation notes are temporary non-authority operating memory until promoted into accepted research, specs, plans, or state",
        ),
    ]


def _incubation_write_plan(inventory: Inventory, target: IncubationTarget, *, existed: bool) -> IncubationWritePlan:
    relationships = _known_active_relationships(inventory, target)
    if not existed:
        return IncubationWritePlan(
            text=_new_note_text(target, relationships),
            relationship_fields=tuple(relationships),
            relationship_skip="" if relationships else "no active plan relationship facts were structurally known",
        )

    current_text = target.path.read_text(encoding="utf-8")
    updated_text, frontmatter_repair = _existing_note_text_with_frontmatter(target, current_text)
    relationship_fields: tuple[str, ...] = ()
    relationship_skip = ""
    if relationships:
        updated_text, relationship_fields, relationship_skip = _text_with_relationships_if_unclaimed(updated_text, relationships)
    else:
        relationship_skip = "no active plan relationship facts were structurally known"
    return IncubationWritePlan(
        text=updated_text + _append_entry(target.note),
        frontmatter_repair=frontmatter_repair,
        relationship_fields=relationship_fields,
        relationship_skip=relationship_skip,
    )


def _known_active_relationships(inventory: Inventory, target: IncubationTarget) -> dict[str, str]:
    state = inventory.state
    if state is None or not state.exists or not state.frontmatter.has_frontmatter or state.frontmatter.errors:
        return {}
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip() != "active":
        return {}
    active_plan = _normalize_rel(state_data.get("active_plan"))
    if active_plan != DEFAULT_PLAN_REL:
        return {}
    plan = inventory.active_plan_surface
    if plan is None or not plan.exists or plan.path.is_symlink() or not plan.path.is_file():
        return {}

    if not plan.frontmatter.has_frontmatter or plan.frontmatter.errors:
        return {}

    plan_data = plan.frontmatter.data
    roadmap_item = _normalized_item_id(plan_data.get("primary_roadmap_item") or plan_data.get("related_roadmap_item"))
    if not _target_matches_active_plan(target, plan_data, roadmap_item):
        return {}
    relationships = {"related_plan": DEFAULT_PLAN_REL}
    if roadmap_item:
        relationships["related_roadmap_item"] = roadmap_item
        roadmap = inventory.root / ROADMAP_REL
        if roadmap.is_file() and not roadmap.is_symlink():
            relationships["related_roadmap"] = ROADMAP_REL
    return relationships


def _target_matches_active_plan(target: IncubationTarget, plan_data: dict[str, object], roadmap_item: str) -> bool:
    target_keys = {_normalized_item_id(target.topic), _normalized_item_id(target.slug)}
    candidate_keys = {
        roadmap_item,
        _normalized_item_id(plan_data.get("related_roadmap_item")),
        _normalized_item_id(plan_data.get("primary_roadmap_item")),
        _normalized_item_id(plan_data.get("execution_slice")),
        _normalized_item_id(plan_data.get("plan_id")),
        _normalized_item_id(plan_data.get("title")),
    }
    for item in _frontmatter_list_values(plan_data.get("covered_roadmap_items")):
        candidate_keys.add(_normalized_item_id(item))
    return bool(target_keys & {key for key in candidate_keys if key})


def _existing_note_text_with_frontmatter(target: IncubationTarget, text: str) -> tuple[str, str]:
    frontmatter = parse_frontmatter(text)
    if frontmatter.has_frontmatter and not frontmatter.errors:
        return text, ""
    reason = "existing note frontmatter is malformed" if frontmatter.has_frontmatter else "existing note has no frontmatter"
    return (
        _prepend_incubation_frontmatter(target, text),
        f"{reason}; prepended canonical incubation frontmatter before appending",
    )


def _prepend_incubation_frontmatter(target: IncubationTarget, text: str) -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        f'topic: "{_yaml_double_quoted_value(target.topic)}"\n'
        'status: "incubating"\n'
        f'created: "{today}"\n'
        f'updated: "{today}"\n'
        f'source: "{INCUBATION_SOURCE}"\n'
        "---\n"
        + text.lstrip("\n")
    )


def _text_with_relationships_if_unclaimed(text: str, relationships: dict[str, str]) -> tuple[str, tuple[str, ...], str]:
    frontmatter = parse_frontmatter(text)
    if not frontmatter.has_frontmatter:
        return text, (), "existing note has no frontmatter; relationship metadata was left unchanged"
    if frontmatter.errors:
        return text, (), "existing note frontmatter is malformed; relationship metadata was left unchanged"
    if any(_frontmatter_value_is_nonempty(frontmatter.data.get(field)) for field in RELATIONSHIP_FIELDS):
        return text, (), "existing note already has relationship metadata; relationship metadata was left unchanged"

    updates = dict(relationships)
    updates["updated"] = date.today().isoformat()
    return _text_with_frontmatter_scalars(text, updates), tuple(relationships), ""


def _relationship_findings(target: IncubationTarget, plan: IncubationWritePlan, apply: bool) -> list[Finding]:
    if plan.relationship_fields:
        prefix = "" if apply else "would "
        return [
            Finding(
                "info",
                "incubate-relationship-sync",
                f"{prefix}record known active-plan relationship metadata: {', '.join(plan.relationship_fields)}",
                target.rel_path,
            )
        ]
    if plan.relationship_skip and apply:
        return [Finding("info", "incubate-relationship-skipped", plan.relationship_skip, target.rel_path)]
    return []


def _frontmatter_repair_findings(target: IncubationTarget, plan: IncubationWritePlan, apply: bool) -> list[Finding]:
    if not plan.frontmatter_repair:
        return []
    prefix = "" if apply else "would "
    return [
        Finding(
            "info",
            "incubate-frontmatter-prepended" if apply else "incubate-frontmatter-plan",
            f"{prefix}{plan.frontmatter_repair}",
            target.rel_path,
        )
    ]


def _new_note_text(target: IncubationTarget, relationships: dict[str, str] | None = None) -> str:
    today = date.today().isoformat()
    relationship_lines = _relationship_frontmatter_lines(relationships or {})
    return (
        "---\n"
        f'topic: "{_yaml_double_quoted_value(target.topic)}"\n'
        'status: "incubating"\n'
        f'created: "{today}"\n'
        f'updated: "{today}"\n'
        f'source: "{INCUBATION_SOURCE}"\n'
        f"{relationship_lines}"
        "---\n"
        f"# {target.topic}\n\n"
        "## Provenance\n\n"
        f"- Source: {INCUBATION_SOURCE}\n"
        f"- Non-authority note: {NON_AUTHORITY_NOTE}\n\n"
        "## Entries\n"
        f"{_entry_text(target.note)}"
    )


def _append_entry(note: str) -> str:
    return "\n" + _entry_text(note)


def _entry_text(note: str) -> str:
    return f"\n### {date.today().isoformat()}\n\n{note.rstrip()}\n"


def _safe_slug(topic: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _topic_looks_like_path(topic: str) -> bool:
    stripped = topic.strip()
    lowered = stripped.lower()
    if stripped in {".", ".."} or stripped.startswith("."):
        return True
    if any(separator in stripped for separator in ("/", "\\", ":")):
        return True
    if ".." in stripped or lowered.endswith((".md", ".txt", ".yaml", ".yml", ".toml")):
        return True
    if re.match(r"^[A-Za-z]:", stripped):
        return True
    return False


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _normalized_note(value: object) -> str:
    return str(value or "").strip()


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _fix_candidate_note(note: str) -> str:
    if note.lstrip().startswith("[MLH-Fix-Candidate]"):
        return note
    return f"[MLH-Fix-Candidate] {note}".strip()


def _relationship_frontmatter_lines(relationships: dict[str, str]) -> str:
    return "".join(f'{key}: "{_yaml_double_quoted_value(value)}"\n' for key, value in relationships.items() if value)


def _text_with_frontmatter_scalars(text: str, updates: dict[str, str]) -> str:
    if not updates:
        return text
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return text

    seen: set[str] = set()
    for index in range(1, closing_index):
        match = re.match(r"^([A-Za-z0-9_-]+):(.*?)(\r?\n)?$", lines[index])
        if not match:
            continue
        key = match.group(1)
        if key not in updates:
            continue
        newline = match.group(3) or ("\n" if lines[index].endswith("\n") else "")
        lines[index] = f'{key}: "{_yaml_double_quoted_value(updates[key])}"{newline}'
        seen.add(key)

    missing = [key for key in updates if key not in seen]
    if missing:
        lines[closing_index:closing_index] = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"\n' for key in missing]
    return "".join(lines)


def _frontmatter_value_is_nonempty(value: object) -> bool:
    if value in (None, "", [], ()):
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_frontmatter_value_is_nonempty(item) for item in value)
    return bool(str(value).strip())


def _frontmatter_value(text: str, key: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        match = re.match(rf"^{re.escape(key)}:\s*(.*?)\s*$", line)
        if match:
            return _strip_quotes(match.group(1).strip())
    return None


def _frontmatter_list_values(value: object) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _normalize_rel(value: object) -> str:
    return str(value or "").replace("\\", "/").strip()


def _yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _strip_quotes(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _first_nonempty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def _rel_has_absolute_or_parent_parts(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith("/") or re.match(r"^[A-Za-z]:", rel_path):
        return True
    parts = [part for part in rel_path.split("/") if part]
    return any(part in {".", ".."} for part in parts)


def _path_escapes_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _parents_between(root: Path, path: Path) -> list[Path]:
    parents: list[Path] = []
    current = path
    root_resolved = root.resolve()
    while True:
        try:
            current.resolve().relative_to(root_resolved)
        except ValueError:
            break
        if current.resolve() == root_resolved:
            break
        parents.append(current)
        current = current.parent
    return list(reversed(parents))


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]
