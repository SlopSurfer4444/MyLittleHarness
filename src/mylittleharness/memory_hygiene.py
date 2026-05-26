from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .atomic_files import AtomicFileDelete, AtomicFileWrite, FileTransactionError, apply_file_transaction
from .command_discovery import rails_not_cognition_boundary_finding
from .inventory import Inventory
from .models import Finding
from .parsing import parse_frontmatter
from .research_recovery import deep_research_rubric_recovery_findings
from .roadmap_semantics import roadmap_item_is_terminal_history_stub
from .safe_commands import mlh_command


RESEARCH_DIR_REL = "project/research"
INCUBATION_DIR_REL = "project/plan-incubation"
VERIFICATION_DIR_REL = "project/verification"
ARCHIVE_RESEARCH_DIR_REL = "project/archive/reference/research"
ARCHIVE_INCUBATION_DIR_REL = "project/archive/reference/incubation"
ARCHIVE_VERIFICATION_DIR_REL = "project/archive/reference/verification"
ROADMAP_REL = "project/roadmap.md"
DEFAULT_VERIFICATION_LEDGER_REL = f"{VERIFICATION_DIR_REL}/autonomous-mlh-swim-ledger.md"
VERIFICATION_LEDGER_CONTINUITY_MARKER = "<!-- mylittleharness-verification-ledger-continuity v1 -->"
ALLOWED_STATUS_VALUES = {"archived", "distilled", "implemented", "rejected"}
TERMINAL_ROADMAP_STATUSES = {"done", "rejected", "superseded"}
RELATIONSHIP_STATUS_FIELDS = {
    "archived_plan",
    "archived_to",
    "docs_decision",
    "implemented_by",
    "promoted_to",
    "related_plan",
    "related_roadmap",
    "related_roadmap_item",
    "verification_summary",
}
IMPLEMENTATION_TAIL_FIELDS = ("archived_plan", "implemented_by")
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
ENTRY_COVERAGE_HEADING = "entry coverage"
ENTRY_COVERAGE_TERMINAL_STATUSES = {"implemented", "rejected", "superseded", "merged", "split", "archived"}
ENTRY_COVERAGE_OPEN_STATUSES = {"accepted", "active", "blocked", "deferred", "incubating", "open", "pending", "todo"}
TERMINAL_INCUBATION_STATUSES = {"implemented", "archived", "rejected", "superseded"}
FINAL_DOCS_DECISIONS = {"updated", "not-needed"}
ROADMAP_CURRENT_POSTURE_TITLE = "Current Posture"
ROADMAP_CURRENT_POSTURE_FIELD = "current_posture"
META_FEEDBACK_CLUSTER_BEGIN = "<!-- BEGIN mylittleharness-meta-feedback-cluster v1 -->"
RECONSTRUCTED_ARCHIVE_STATUS_FIELDS = ("recovery_status", "reconstruction_status")
RECONSTRUCTED_ARCHIVE_BOUNDARY_FIELDS = ("authority", "closeout_boundary")
RECONSTRUCTED_ARCHIVE_BODY_MARKERS = (
    "recovered evidence card",
    "reconstructed historical pointer",
    "not proof of the original full plan body",
    "not the original implementation plan",
    "original file body was absent",
    "physical file was absent",
)


@dataclass(frozen=True)
class IncubationEntry:
    entry_id: str
    heading: str
    line: int


@dataclass(frozen=True)
class EntryCoverage:
    entry_id: str
    status: str
    detail: str
    line: int


@dataclass(frozen=True)
class EntryCoverageReport:
    entries: tuple[IncubationEntry, ...]
    coverage: tuple[EntryCoverage, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class MemoryHygieneRequest:
    source: str
    promoted_to: str
    status: str
    archive_to: str
    repair_links: bool = False
    scan: bool = False
    archive_covered: bool = False
    entry_coverage: tuple[str, ...] = ()
    rotate_ledger: bool = False
    source_hash: str = ""
    reason: str = ""
    proposal_token: str = ""


@dataclass(frozen=True)
class MemoryHygienePlan:
    source_rel: str
    source_path: Path
    promoted_to_rel: str
    promoted_to_path: Path | None
    status: str
    archive_rel: str
    archive_path: Path | None
    updated_source_text: str
    link_repairs: tuple[tuple[str, Path, str], ...]
    entry_coverage_updates: tuple[EntryCoverage, ...] = ()
    archive_covered: bool = False


@dataclass(frozen=True)
class VerificationLedgerRotationPlan:
    source_rel: str
    source_path: Path
    archive_rel: str
    archive_path: Path
    source_text: str
    source_hash: str
    fresh_text: str
    reason: str


@dataclass(frozen=True)
class RelationshipUpdatePlan:
    source_rel: str
    source_path: Path
    target_rel: str
    target_path: Path
    current_text: str
    updated_text: str
    changed_fields: tuple[str, ...]
    archive_rel: str = ""
    archive_path: Path | None = None
    archive_blockers: tuple[str, ...] = ()
    link_repairs: tuple[tuple[str, Path, str], ...] = ()


@dataclass(frozen=True)
class RoadmapCurrentPostureItem:
    item_id: str
    status: str
    order: str
    title: str
    execution_slice: str
    detail: str


@dataclass(frozen=True)
class MemoryHygieneBatchCandidate:
    candidate_id: str
    source_rel: str
    source_hash: str
    status: str
    archive_rel: str
    link_repairs: tuple[tuple[str, str, str], ...]
    dry_run_command: str
    apply_command: str


def sync_roadmap_current_posture_section(text: str) -> str:
    lines = text.splitlines(keepends=True)
    bounds = _roadmap_h2_section_bounds(lines, ROADMAP_CURRENT_POSTURE_TITLE)
    if bounds is None:
        return text
    items = _roadmap_current_posture_items(text)
    start, end = bounds
    newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
    replacement = [lines[start], *_roadmap_current_posture_body_lines(items, newline)]
    updated = "".join([*lines[:start], *replacement, *lines[end:]])
    return text if updated == text else updated


def make_memory_hygiene_request(
    source: str | None,
    promoted_to: str | None,
    status: str | None,
    archive_to: str | None,
    repair_links: bool = False,
    scan: bool = False,
    archive_covered: bool = False,
    entry_coverage: tuple[str, ...] | list[str] = (),
    rotate_ledger: bool = False,
    source_hash: str | None = None,
    reason: str | None = None,
    proposal_token: str | None = None,
) -> MemoryHygieneRequest:
    source_rel = _normalize_rel(source)
    if rotate_ledger and not source_rel:
        source_rel = DEFAULT_VERIFICATION_LEDGER_REL
    promoted = _normalize_rel(promoted_to)
    archive = _normalize_rel(archive_to)
    if archive_covered and not archive and source_rel.startswith(f"{INCUBATION_DIR_REL}/"):
        archive = _default_incubation_archive_rel(source_rel)
    normalized_status = _normalized_status(status, promoted, archive)
    return MemoryHygieneRequest(
        source=source_rel,
        promoted_to=promoted,
        status=normalized_status,
        archive_to=archive,
        repair_links=repair_links,
        scan=scan,
        archive_covered=archive_covered,
        entry_coverage=tuple(str(item or "").strip() for item in entry_coverage if str(item or "").strip()),
        rotate_ledger=rotate_ledger,
        source_hash=str(source_hash or "").strip().casefold(),
        reason=str(reason or "").strip(),
        proposal_token=str(proposal_token or "").strip().casefold(),
    )


def memory_hygiene_dry_run_findings(inventory: Inventory, request: MemoryHygieneRequest) -> list[Finding]:
    if request.rotate_ledger:
        return verification_ledger_rotate_dry_run_findings(inventory, request)

    findings = [
        Finding("info", "memory-hygiene-dry-run", "memory hygiene proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    if request.scan:
        findings.append(
            Finding(
                "info",
                "memory-hygiene-scan",
                "relationship hygiene scan is read-only and reports stale links, missing reciprocal links, orphan notes, text-input audit posture, entry coverage, split suggestions, incubation cleanup advisor classifications, Deep Research rubric recovery hints, and safe cleanup candidates",
            )
        )
        errors = _request_errors(inventory, request)
        if errors:
            findings.extend(_with_severity(errors, "warn"))
            return findings
        findings.extend(cli_text_audit_findings())
        findings.extend(relationship_hygiene_scan_findings(inventory))
        findings.extend(_relationship_scan_boundary_findings())
        return findings

    plan, errors = _memory_hygiene_plan(inventory, request)
    if plan:
        findings.extend(_plan_findings(plan, apply=False, repair_links=request.repair_links))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "memory-hygiene-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing lifecycle hygiene changes",
            )
        )
        return findings
    assert plan is not None
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "memory-hygiene-validation-posture",
            "apply would write only the declared source/archive/link targets in an eligible live operating root; dry-run writes no files",
            plan.source_rel,
        )
    )
    return findings


def memory_hygiene_apply_findings(inventory: Inventory, request: MemoryHygieneRequest) -> list[Finding]:
    if request.rotate_ledger:
        return verification_ledger_rotate_apply_findings(inventory, request)

    if request.scan:
        if request.proposal_token:
            return _memory_hygiene_batch_apply_findings(inventory, request)
        return [
            Finding(
                "error",
                "memory-hygiene-refused",
                "--scan is read-only unless paired with --apply --proposal-token from a reviewed dry-run scan",
            )
        ]

    plan, errors = _memory_hygiene_plan(inventory, request)
    if errors:
        return errors
    assert plan is not None

    operations: list[AtomicFileWrite | AtomicFileDelete] = []
    archive_rel = plan.archive_rel or plan.source_rel
    if plan.archive_path:
        archive_tmp = plan.archive_path.with_name(f".{plan.archive_path.name}.memory-hygiene.tmp")
        archive_backup = plan.archive_path.with_name(f".{plan.archive_path.name}.memory-hygiene.backup")
        source_backup = plan.source_path.with_name(f".{plan.source_path.name}.memory-hygiene.backup")
        operations.append(AtomicFileWrite(plan.archive_path, archive_tmp, plan.updated_source_text, archive_backup))
        operations.append(AtomicFileDelete(plan.source_path, source_backup))
    else:
        source_tmp = plan.source_path.with_name(f".{plan.source_path.name}.memory-hygiene.tmp")
        source_backup = plan.source_path.with_name(f".{plan.source_path.name}.memory-hygiene.backup")
        operations.append(AtomicFileWrite(plan.source_path, source_tmp, plan.updated_source_text, source_backup))

    for _, path, text in plan.link_repairs:
        link_tmp = path.with_name(f".{path.name}.memory-hygiene.tmp")
        link_backup = path.with_name(f".{path.name}.memory-hygiene.backup")
        operations.append(AtomicFileWrite(path, link_tmp, text, link_backup))

    try:
        cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
    except FileTransactionError as exc:
        return [Finding("error", "memory-hygiene-refused", f"memory hygiene apply failed before all target writes completed: {exc}", plan.source_rel)]

    findings = [
        Finding("info", "memory-hygiene-apply", "memory hygiene apply started"),
        _root_posture_finding(inventory),
        Finding("info", "memory-hygiene-frontmatter-updated", "updated lifecycle frontmatter", archive_rel),
    ]
    if plan.archive_rel:
        findings.append(Finding("info", "memory-hygiene-archived", f"archived source to {plan.archive_rel}", plan.archive_rel))
    for rel_path, _, _ in plan.link_repairs:
        findings.append(Finding("info", "memory-hygiene-link-repaired", f"repaired exact source-path references in {rel_path}", rel_path))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "memory-hygiene-backup-cleanup", warning, archive_rel))
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "memory-hygiene-validation-posture",
            "run check after apply to verify the live operating root remains healthy; hygiene output is not lifecycle approval",
            plan.archive_rel or plan.source_rel,
        )
    )
    return findings


def _memory_hygiene_batch_apply_findings(inventory: Inventory, request: MemoryHygieneRequest) -> list[Finding]:
    errors = _request_errors(inventory, request)
    if errors:
        return errors
    if not re.fullmatch(r"mhb-[0-9a-f]{16}", request.proposal_token):
        return [
            Finding(
                "error",
                "memory-hygiene-batch-refused",
                "--proposal-token must be the mhb-* token reported by memory-hygiene --dry-run --scan",
            )
        ]

    candidates = _incubation_cleanup_batch_candidates(inventory)
    if not candidates:
        return [
            Finding(
                "error",
                "memory-hygiene-batch-refused",
                "no current scan cleanup candidates match a token-bound batch apply; rerun memory-hygiene --dry-run --scan",
            )
        ]

    current_token = _batch_proposal_token(candidates)
    if request.proposal_token != current_token:
        return [
            Finding(
                "error",
                "memory-hygiene-batch-refused",
                (
                    "proposal token mismatch or stale scan; "
                    f"expected current token {current_token}, received {request.proposal_token}; rerun memory-hygiene --dry-run --scan"
                ),
            )
        ]

    plans: list[tuple[MemoryHygieneBatchCandidate, MemoryHygienePlan]] = []
    for candidate in candidates:
        plan_request = MemoryHygieneRequest(
            source=candidate.source_rel,
            promoted_to="",
            status=candidate.status,
            archive_to=candidate.archive_rel,
            repair_links=True,
        )
        plan, plan_errors = _memory_hygiene_plan(inventory, plan_request)
        if plan_errors:
            return plan_errors
        assert plan is not None
        plans.append((candidate, plan))

    operations: list[AtomicFileWrite | AtomicFileDelete] = []
    for _, plan in plans:
        if not plan.archive_path:
            return [Finding("error", "memory-hygiene-batch-refused", "batch cleanup requires archive targets", plan.source_rel)]
        archive_tmp = plan.archive_path.with_name(f".{plan.archive_path.name}.memory-hygiene-batch.tmp")
        archive_backup = plan.archive_path.with_name(f".{plan.archive_path.name}.memory-hygiene-batch.backup")
        source_backup = plan.source_path.with_name(f".{plan.source_path.name}.memory-hygiene-batch.backup")
        operations.append(AtomicFileWrite(plan.archive_path, archive_tmp, plan.updated_source_text, archive_backup))
        operations.append(AtomicFileDelete(plan.source_path, source_backup))

    link_text_by_path: dict[Path, str] = {}
    link_rel_by_path: dict[Path, str] = {}
    for _, plan in plans:
        for rel_path, path, _ in plan.link_repairs:
            if path not in link_text_by_path:
                try:
                    link_text_by_path[path] = path.read_text(encoding="utf-8")
                except OSError as exc:
                    return [Finding("error", "memory-hygiene-batch-refused", f"link repair target could not be read: {exc}", rel_path)]
                link_rel_by_path[path] = rel_path
            link_text_by_path[path] = link_text_by_path[path].replace(plan.source_rel, plan.archive_rel)

    for path, text in sorted(link_text_by_path.items(), key=lambda item: link_rel_by_path[item[0]]):
        link_tmp = path.with_name(f".{path.name}.memory-hygiene-batch.tmp")
        link_backup = path.with_name(f".{path.name}.memory-hygiene-batch.backup")
        operations.append(AtomicFileWrite(path, link_tmp, text, link_backup))

    try:
        cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
    except FileTransactionError as exc:
        return [
            Finding(
                "error",
                "memory-hygiene-batch-refused",
                f"token-bound memory hygiene batch apply failed before all target writes completed: {exc}",
            )
        ]

    findings = [
        Finding("info", "memory-hygiene-batch-apply", "token-bound memory hygiene batch apply started"),
        _root_posture_finding(inventory),
        Finding(
            "info",
            "memory-hygiene-batch-token-accepted",
            (
                f"accepted reviewed proposal token {request.proposal_token} for {len(plans)} candidate(s); "
                "token binds source hashes, candidate ids, archive targets, and exact link-repair file hashes"
            ),
        ),
    ]
    for candidate, plan in plans:
        findings.append(
            Finding(
                "info",
                "memory-hygiene-batch-candidate-applied",
                f"candidate_id={candidate.candidate_id}; archived source to {plan.archive_rel}",
                plan.archive_rel,
            )
        )
        findings.append(Finding("info", "memory-hygiene-frontmatter-updated", "updated lifecycle frontmatter", plan.archive_rel))
        findings.append(Finding("info", "memory-hygiene-archived", f"archived source to {plan.archive_rel}", plan.archive_rel))
    for path in sorted(link_text_by_path, key=lambda item: link_rel_by_path[item]):
        rel_path = link_rel_by_path[path]
        findings.append(Finding("info", "memory-hygiene-link-repaired", f"repaired exact source-path references in {rel_path}", rel_path))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "memory-hygiene-backup-cleanup", warning))
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "memory-hygiene-validation-posture",
            "run check after token-bound batch apply; hygiene output is not lifecycle approval",
        )
    )
    return findings


def verification_ledger_rotate_dry_run_findings(inventory: Inventory, request: MemoryHygieneRequest) -> list[Finding]:
    findings = [
        Finding("info", "verification-ledger-rotate-dry-run", "verification ledger rotation proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    plan, errors = _verification_ledger_rotation_plan(inventory, request, apply=False)
    if plan:
        findings.extend(_verification_ledger_rotation_plan_findings(plan, apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "verification-ledger-rotate-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before rotating verification ledger memory",
                request.source or None,
            )
        )
        return findings
    assert plan is not None
    findings.extend(_verification_ledger_rotation_boundary_findings())
    findings.append(
        Finding(
            "info",
            "verification-ledger-rotate-validation-posture",
            f"apply would write only {plan.archive_rel} and {plan.source_rel}; rerun apply with --source-hash {plan.source_hash}; dry-run writes no files",
            plan.source_rel,
        )
    )
    return findings


def verification_ledger_rotate_apply_findings(inventory: Inventory, request: MemoryHygieneRequest) -> list[Finding]:
    plan, errors = _verification_ledger_rotation_plan(inventory, request, apply=True)
    if errors:
        return errors
    assert plan is not None

    operations: list[AtomicFileWrite | AtomicFileDelete] = [
        AtomicFileWrite(
            plan.archive_path,
            plan.archive_path.with_name(f".{plan.archive_path.name}.verification-ledger.tmp"),
            plan.source_text,
            plan.archive_path.with_name(f".{plan.archive_path.name}.verification-ledger.backup"),
        ),
        AtomicFileWrite(
            plan.source_path,
            plan.source_path.with_name(f".{plan.source_path.name}.verification-ledger.tmp"),
            plan.fresh_text,
            plan.source_path.with_name(f".{plan.source_path.name}.verification-ledger.backup"),
        ),
    ]
    try:
        cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
    except FileTransactionError as exc:
        return [Finding("error", "verification-ledger-rotate-refused", f"verification ledger rotation failed before all target writes completed: {exc}", plan.source_rel)]

    findings = [
        Finding("info", "verification-ledger-rotate-apply", "verification ledger rotation apply started"),
        _root_posture_finding(inventory),
        Finding("info", "verification-ledger-archived", f"archived previous ledger to {plan.archive_rel}", plan.archive_rel),
        Finding("info", "verification-ledger-seeded", f"seeded fresh continuity ledger at {plan.source_rel}", plan.source_rel),
    ]
    findings.extend(_verification_ledger_rotation_plan_findings(plan, apply=True))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "verification-ledger-backup-cleanup", warning, plan.source_rel))
    findings.extend(_verification_ledger_rotation_boundary_findings())
    findings.append(
        Finding(
            "info",
            "verification-ledger-rotate-validation-posture",
            "run check after apply to verify fresh ledger and archived evidence posture; rotation output is not lifecycle approval",
            plan.source_rel,
        )
    )
    return findings


def _verification_ledger_rotation_plan(
    inventory: Inventory,
    request: MemoryHygieneRequest,
    *,
    apply: bool,
) -> tuple[VerificationLedgerRotationPlan | None, list[Finding]]:
    source_rel = request.source or DEFAULT_VERIFICATION_LEDGER_REL
    source_path = inventory.root / source_rel if source_rel else inventory.root
    archive_rel = _default_verification_archive_rel(source_rel)
    archive_path = inventory.root / archive_rel
    errors = _verification_ledger_rotation_errors(inventory, request, source_rel, source_path, archive_rel, archive_path, apply=apply)
    if errors:
        return None, errors
    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("error", "verification-ledger-rotate-refused", f"source ledger could not be read: {exc}", source_rel)]

    source_hash = _sha256_text(source_text)
    if apply:
        expected_hash = request.source_hash
        if not expected_hash:
            return None, [
                Finding(
                    "error",
                    "verification-ledger-rotate-refused",
                    f"--source-hash is required for apply; rerun dry-run and retry with --source-hash {source_hash}",
                    source_rel,
                )
            ]
        if expected_hash != source_hash:
            return None, [
                Finding(
                    "error",
                    "verification-ledger-rotate-refused",
                    f"source hash changed after review; expected {expected_hash}, current {source_hash}; rerun dry-run before apply",
                    source_rel,
                )
            ]

    reason = request.reason or "ledger rotation requested through memory-hygiene --rotate-ledger"
    fresh_text = _fresh_verification_ledger_text(source_rel, archive_rel, source_hash, reason)
    return (
        VerificationLedgerRotationPlan(
            source_rel=source_rel,
            source_path=source_path,
            archive_rel=archive_rel,
            archive_path=archive_path,
            source_text=source_text,
            source_hash=source_hash,
            fresh_text=fresh_text,
            reason=reason,
        ),
        [],
    )


def _verification_ledger_rotation_errors(
    inventory: Inventory,
    request: MemoryHygieneRequest,
    source_rel: str,
    source_path: Path,
    archive_rel: str,
    archive_path: Path,
    *,
    apply: bool,
) -> list[Finding]:
    errors: list[Finding] = []
    if inventory.root_kind == "product_source_fixture":
        errors.append(Finding("error", "verification-ledger-rotate-refused", "target is a product-source compatibility fixture; verification ledger rotation is refused", source_rel or None))
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(Finding("error", "verification-ledger-rotate-refused", "target is fallback/archive or generated-output evidence; verification ledger rotation is refused", source_rel or None))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "verification-ledger-rotate-refused", f"target root kind is {inventory.root_kind}; verification ledger rotation requires a live operating root"))

    if (
        request.scan
        or request.promoted_to
        or request.archive_to
        or request.status
        or request.repair_links
        or request.archive_covered
        or request.entry_coverage
        or request.proposal_token
    ):
        errors.append(
            Finding(
                "error",
                "verification-ledger-rotate-refused",
                "--rotate-ledger cannot be combined with scan, proposal-token, promotion, archive, status, link-repair, archive-covered, or entry-coverage fields",
                source_rel or None,
            )
        )
    if request.source_hash and not re.fullmatch(r"[0-9a-f]{64}", request.source_hash):
        errors.append(Finding("error", "verification-ledger-rotate-refused", "--source-hash must be a full lowercase sha256 hex digest from dry-run", source_rel or None))
    if not apply and request.source_hash:
        errors.append(Finding("error", "verification-ledger-rotate-refused", "--source-hash is apply-only; dry-run reports the current source hash", source_rel or None))
    if not source_rel:
        errors.append(Finding("error", "verification-ledger-rotate-refused", "--source is required and cannot be empty"))
        return errors
    if _rel_has_absolute_or_parent_parts(source_rel):
        errors.append(Finding("error", "verification-ledger-rotate-refused", "--source must be a root-relative path without parent segments", source_rel))
        return errors
    if not source_rel.startswith(f"{VERIFICATION_DIR_REL}/"):
        errors.append(Finding("error", "verification-ledger-rotate-refused", "source ledger must be under project/verification/", source_rel))
    if not source_rel.endswith(".md"):
        errors.append(Finding("error", "verification-ledger-rotate-refused", "source ledger must be a Markdown file", source_rel))
    if _path_escapes_root(inventory.root, source_path):
        errors.append(Finding("error", "verification-ledger-rotate-refused", "source ledger path escapes the target root", source_rel))
    elif not source_path.exists():
        errors.append(Finding("error", "verification-ledger-rotate-refused", "source ledger does not exist", source_rel))
    elif source_path.is_symlink():
        errors.append(Finding("error", "verification-ledger-rotate-refused", "source ledger is a symlink", source_rel))
    elif not source_path.is_file():
        errors.append(Finding("error", "verification-ledger-rotate-refused", "source ledger is not a regular file", source_rel))

    if _path_escapes_root(inventory.root, archive_path):
        errors.append(Finding("error", "verification-ledger-rotate-refused", "archive target path escapes the target root", archive_rel))
        return errors
    for parent in _parents_between(inventory.root, archive_path.parent):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "verification-ledger-rotate-refused", f"archive target directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "verification-ledger-rotate-refused", f"archive target directory contains a non-directory segment: {rel}", rel))
    if archive_path.exists():
        errors.append(Finding("error", "verification-ledger-rotate-refused", "archive target already exists", archive_rel))
    return errors


def _verification_ledger_rotation_plan_findings(plan: VerificationLedgerRotationPlan, *, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    return [
        Finding("info", "verification-ledger-source", f"{prefix}rotate source ledger: {plan.source_rel}", plan.source_rel),
        Finding("info", "verification-ledger-source-hash", f"current source sha256: {plan.source_hash}", plan.source_rel),
        Finding("info", "verification-ledger-archive-target", f"{prefix}archive previous ledger to {plan.archive_rel}", plan.archive_rel),
        Finding("info", "verification-ledger-fresh-target", f"{prefix}seed fresh continuity ledger at {plan.source_rel}", plan.source_rel),
        Finding("info", "verification-ledger-continuity-pointer", f"{prefix}record continuity pointer from {plan.source_rel} to {plan.archive_rel}", plan.source_rel),
        Finding("info", "verification-ledger-reason", f"rotation reason: {plan.reason}", plan.source_rel),
    ]


def _verification_ledger_rotation_boundary_findings() -> list[Finding]:
    return [
        rails_not_cognition_boundary_finding(VERIFICATION_DIR_REL),
        Finding(
            "info",
            "verification-ledger-rotate-boundary",
            "verification ledger rotation writes only the reviewed active ledger and deterministic archive/reference verification target in eligible live operating roots",
        ),
        Finding(
            "info",
            "verification-ledger-rotate-authority",
            "verification ledger rotation is evidence maintenance only; it cannot approve closeout, roadmap promotion, unrelated archive cleanup, staging, commit, push, rollback, or next-plan opening",
        ),
    ]


def _default_verification_archive_rel(source_rel: str) -> str:
    source = Path(source_rel)
    return f"{ARCHIVE_VERIFICATION_DIR_REL}/{date.today().isoformat()}-{source.stem}.md"


def _fresh_verification_ledger_text(source_rel: str, archive_rel: str, source_hash: str, reason: str) -> str:
    today = date.today().isoformat()
    title = Path(source_rel).stem.replace("-", " ").title()
    return (
        "---\n"
        f'title: "{_yaml_double_quoted_value(title)}"\n'
        'status: "active"\n'
        f'created: "{today}"\n'
        f'rotated_from: "{_yaml_double_quoted_value(archive_rel)}"\n'
        f'rotated_from_hash: "{source_hash}"\n'
        "---\n"
        f"# {title}\n\n"
        f"{VERIFICATION_LEDGER_CONTINUITY_MARKER}\n"
        f"- Previous ledger archive: `{archive_rel}`\n"
        f"- Previous ledger sha256: `{source_hash}`\n"
        f"- Rotated on: `{today}`\n"
        f"- Reason: {reason}\n"
        "- Boundary: this active ledger is fresh continuity only; archived verification evidence remains historical "
        "and cannot approve lifecycle movement, closeout, staging, commit, push, rollback, or next-plan opening.\n"
        "\n"
        "## Current Continuity\n\n"
        "- Start new verification observations below this heading.\n"
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _memory_hygiene_plan(inventory: Inventory, request: MemoryHygieneRequest) -> tuple[MemoryHygienePlan | None, list[Finding]]:
    errors: list[Finding] = []
    errors.extend(_request_errors(inventory, request))

    source_path = inventory.root / request.source if request.source else inventory.root
    promoted_to_path = inventory.root / request.promoted_to if request.promoted_to else None
    archive_path = inventory.root / request.archive_to if request.archive_to else None

    errors.extend(_source_errors(inventory, request.source, source_path))
    errors.extend(_promoted_to_errors(inventory, request.promoted_to, promoted_to_path))
    errors.extend(_archive_errors(inventory, request.archive_to, archive_path))

    if errors:
        return None, errors

    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("error", "memory-hygiene-refused", f"source could not be read: {exc}", request.source)]

    coverage_updates: tuple[EntryCoverage, ...] = ()
    if request.entry_coverage:
        source_text, coverage_updates, coverage_error = _source_text_with_entry_coverage(source_text, request.entry_coverage)
        if coverage_error:
            return None, [Finding("error", "memory-hygiene-refused", coverage_error, request.source)]

    if request.archive_covered:
        blockers = incubation_archive_blockers(source_text, require_entry_coverage=True)
        if blockers:
            return None, [
                Finding(
                    "error",
                    "memory-hygiene-refused",
                    f"--archive-covered requires terminal Entry Coverage and no archive blockers: {', '.join(blockers)}",
                    request.source,
                )
            ]

    updated_text, frontmatter_error = _source_text_with_lifecycle_frontmatter(source_text, request)
    if frontmatter_error:
        return None, [Finding("error", "memory-hygiene-refused", frontmatter_error, request.source)]

    link_repairs: tuple[tuple[str, Path, str], ...] = ()
    if request.repair_links and request.archive_to:
        link_repairs = tuple(_planned_link_repairs(inventory, request.source, request.archive_to))

    return (
        MemoryHygienePlan(
            source_rel=request.source,
            source_path=source_path,
            promoted_to_rel=request.promoted_to,
            promoted_to_path=promoted_to_path,
            status=request.status,
            archive_rel=request.archive_to,
            archive_path=archive_path,
            updated_source_text=updated_text,
            link_repairs=link_repairs,
            entry_coverage_updates=coverage_updates,
            archive_covered=request.archive_covered,
        ),
        [],
    )


def _request_errors(inventory: Inventory, request: MemoryHygieneRequest) -> list[Finding]:
    errors: list[Finding] = []
    if inventory.root_kind == "product_source_fixture":
        errors.append(Finding("error", "memory-hygiene-refused", "target is a product-source compatibility fixture; memory-hygiene --apply is refused", request.source or None))
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(Finding("error", "memory-hygiene-refused", "target is fallback/archive or generated-output evidence; memory-hygiene --apply is refused", request.source or None))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "memory-hygiene-refused", f"target root kind is {inventory.root_kind}; memory-hygiene requires a live operating root"))

    if request.scan:
        if request.source or request.promoted_to or request.archive_to or request.status or request.repair_links or request.archive_covered or request.entry_coverage:
            errors.append(Finding("error", "memory-hygiene-refused", "--scan cannot be combined with source, promotion, archive, status, link-repair, archive-covered, or entry-coverage fields"))
        return errors

    if request.proposal_token:
        errors.append(Finding("error", "memory-hygiene-refused", "--proposal-token requires --scan"))
    if not request.source:
        errors.append(Finding("error", "memory-hygiene-refused", "--source is required and cannot be empty"))
    if request.archive_covered and not request.source.startswith(f"{INCUBATION_DIR_REL}/"):
        errors.append(Finding("error", "memory-hygiene-refused", "--archive-covered requires an incubation source under project/plan-incubation/", request.source or None))
    if request.archive_covered and request.promoted_to:
        errors.append(Finding("error", "memory-hygiene-refused", "--archive-covered cannot be combined with --promoted-to", request.source or None))
    if not request.promoted_to and not request.archive_to:
        errors.append(Finding("error", "memory-hygiene-refused", "at least one of --promoted-to or --archive-to is required"))
    if request.status not in ALLOWED_STATUS_VALUES:
        errors.append(Finding("error", "memory-hygiene-refused", f"--status must be one of: {', '.join(sorted(ALLOWED_STATUS_VALUES))}"))
    if request.repair_links and not request.archive_to:
        errors.append(Finding("error", "memory-hygiene-refused", "--repair-links requires --archive-to"))
    return errors


def _source_errors(inventory: Inventory, source_rel: str, source_path: Path) -> list[Finding]:
    if not source_rel:
        return []
    errors: list[Finding] = []
    if _rel_has_absolute_or_parent_parts(source_rel):
        errors.append(Finding("error", "memory-hygiene-refused", "--source must be a root-relative path without parent segments", source_rel))
        return errors
    if not _source_route_allowed(source_rel):
        errors.append(Finding("error", "memory-hygiene-refused", "source must be under project/research/ or project/plan-incubation/", source_rel))
    if not source_rel.endswith(".md"):
        errors.append(Finding("error", "memory-hygiene-refused", "source must be a Markdown file", source_rel))
    if _path_escapes_root(inventory.root, source_path):
        errors.append(Finding("error", "memory-hygiene-refused", "source path escapes the target root", source_rel))
    elif not source_path.exists():
        errors.append(Finding("error", "memory-hygiene-refused", "source does not exist", source_rel))
    elif source_path.is_symlink():
        errors.append(Finding("error", "memory-hygiene-refused", "source is a symlink", source_rel))
    elif not source_path.is_file():
        errors.append(Finding("error", "memory-hygiene-refused", "source is not a regular file", source_rel))
    return errors


def _promoted_to_errors(inventory: Inventory, promoted_rel: str, promoted_path: Path | None) -> list[Finding]:
    if not promoted_rel or promoted_path is None:
        return []
    errors: list[Finding] = []
    if _rel_has_absolute_or_parent_parts(promoted_rel):
        errors.append(Finding("error", "memory-hygiene-refused", "--promoted-to must be a root-relative path without parent segments", promoted_rel))
        return errors
    if _path_escapes_root(inventory.root, promoted_path):
        errors.append(Finding("error", "memory-hygiene-refused", "promoted target path escapes the target root", promoted_rel))
    elif not promoted_path.exists():
        errors.append(Finding("error", "memory-hygiene-refused", "promoted target does not exist", promoted_rel))
    elif promoted_path.is_symlink():
        errors.append(Finding("error", "memory-hygiene-refused", "promoted target is a symlink", promoted_rel))
    elif not promoted_path.is_file():
        errors.append(Finding("error", "memory-hygiene-refused", "promoted target is not a regular file", promoted_rel))
    return errors


def _archive_errors(inventory: Inventory, archive_rel: str, archive_path: Path | None) -> list[Finding]:
    if not archive_rel or archive_path is None:
        return []
    errors: list[Finding] = []
    if _rel_has_absolute_or_parent_parts(archive_rel):
        errors.append(Finding("error", "memory-hygiene-refused", "--archive-to must be a root-relative path without parent segments", archive_rel))
        return errors
    if not _archive_route_allowed(archive_rel):
        errors.append(Finding("error", "memory-hygiene-refused", "--archive-to must be under project/archive/reference/research/ or project/archive/reference/incubation/", archive_rel))
    if not archive_rel.endswith(".md"):
        errors.append(Finding("error", "memory-hygiene-refused", "archive target must be a Markdown file", archive_rel))
    if _path_escapes_root(inventory.root, archive_path):
        errors.append(Finding("error", "memory-hygiene-refused", "archive target path escapes the target root", archive_rel))
        return errors
    for parent in _parents_between(inventory.root, archive_path.parent):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "memory-hygiene-refused", f"archive target directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "memory-hygiene-refused", f"archive target directory contains a non-directory segment: {rel}", rel))
    if archive_path.exists():
        errors.append(Finding("error", "memory-hygiene-refused", "archive target already exists", archive_rel))
    return errors


def _source_text_with_lifecycle_frontmatter(text: str, request: MemoryHygieneRequest) -> tuple[str, str | None]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text, "source frontmatter is required for lifecycle hygiene"
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return text, "source frontmatter is malformed"

    updates = {
        "status": request.status,
        "updated": date.today().isoformat(),
    }
    if request.promoted_to:
        updates["promoted_to"] = request.promoted_to
    if request.archive_to:
        updates["archived_to"] = request.archive_to

    seen, closing_index = _replace_frontmatter_scalar_blocks(lines, closing_index, updates)

    missing = [key for key in updates if key not in seen]
    if missing:
        lines[closing_index:closing_index] = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"\n' for key in missing]
    return "".join(lines), None


def _source_text_with_entry_coverage(text: str, raw_records: tuple[str, ...]) -> tuple[str, tuple[EntryCoverage, ...], str | None]:
    parsed_records: list[EntryCoverage] = []
    for raw in raw_records:
        parsed = _parse_entry_coverage_line(f"- {raw.strip()}", 0)
        if parsed is None:
            return text, (), "entry coverage value must be `<entry-id>: <status> <destination>`"
        parsed_records.append(parsed)
    if not parsed_records:
        return text, (), None
    report = incubation_entry_coverage_report(text)
    entry_ids = {entry.entry_id for entry in report.entries}
    for record in parsed_records:
        if record.entry_id not in entry_ids:
            valid_ids = ", ".join(f"`{entry.entry_id}`" for entry in report.entries) or "<none parsed>"
            return (
                text,
                (),
                (
                    f"entry coverage references unknown entry {record.entry_id!r}; valid entry ids: {valid_ids}; "
                    'retry with --entry-coverage "<entry-id>: implemented via <destination>" or '
                    '--entry-coverage "<entry-id>: rejected <reason>"'
                ),
            )
        blockers = _entry_coverage_record_blockers(record)
        if blockers:
            return text, (), "; ".join(blockers)

    lines = text.splitlines(keepends=True)
    section = _entry_coverage_section(text)
    record_text = "".join(f"- `{record.entry_id}`: `{record.status}` {record.detail}\n" for record in parsed_records)
    if section is None:
        separator = "" if text.endswith(("\n", "\r")) else "\n"
        return text + separator + "\n## Entry Coverage\n\n" + record_text, tuple(parsed_records), None

    start, end = section
    coverage_by_id = {record.entry_id: record for record in report.coverage}
    for record in parsed_records:
        coverage_by_id[record.entry_id] = record
    ordered_ids = [entry.entry_id for entry in report.entries if entry.entry_id in coverage_by_id]
    rendered = [f"- `{entry_id}`: `{coverage_by_id[entry_id].status}` {coverage_by_id[entry_id].detail}\n" for entry_id in ordered_ids]
    return "".join(lines[:start] + rendered + lines[end:]), tuple(parsed_records), None


def relationship_update_plan(
    inventory: Inventory,
    source_rel: str,
    updates: dict[str, str],
    *,
    archive_to: str = "",
    repair_links: bool = False,
    archive_blockers: tuple[str, ...] = (),
    clear_fields: tuple[str, ...] = (),
) -> tuple[RelationshipUpdatePlan | None, list[Finding]]:
    source_rel = _normalize_rel(source_rel)
    archive_rel = _normalize_rel(archive_to)
    source_path = inventory.root / source_rel if source_rel else inventory.root
    archive_path = inventory.root / archive_rel if archive_rel else None
    errors = _incubation_source_errors(inventory, source_rel, source_path)
    if archive_rel:
        errors.extend(_archive_errors(inventory, archive_rel, archive_path))
    if repair_links and not archive_rel:
        errors.append(Finding("error", "relationship-writeback-refused", "--repair-links requires an archive target", source_rel or None))
    if errors:
        return None, errors

    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("error", "relationship-writeback-refused", f"source could not be read: {exc}", source_rel)]

    update_values = {key: value for key, value in updates.items() if value not in (None, "")}
    clear_field_names = tuple(dict.fromkeys(field for field in clear_fields if field))
    if archive_rel:
        update_values["archived_to"] = archive_rel
    update_values["updated"] = date.today().isoformat()
    updated_text, frontmatter_error = _text_with_frontmatter_scalars(source_text, update_values, clear_fields=clear_field_names)
    if frontmatter_error:
        return None, [Finding("error", "relationship-writeback-refused", frontmatter_error, source_rel)]

    changed_fields = tuple(key for key in update_values if _frontmatter_value(source_text, key) != update_values[key])
    cleared_fields = tuple(
        key
        for key in clear_field_names
        if _frontmatter_field_present(source_text, key) and _frontmatter_value(updated_text, key) == ""
    )
    changed_fields = tuple(dict.fromkeys((*changed_fields, *cleared_fields)))
    link_repairs: tuple[tuple[str, Path, str], ...] = ()
    if repair_links and archive_rel:
        link_repairs = tuple(_planned_link_repairs(inventory, source_rel, archive_rel))

    return (
        RelationshipUpdatePlan(
            source_rel=source_rel,
            source_path=source_path,
            target_rel=archive_rel or source_rel,
            target_path=archive_path or source_path,
            current_text=source_text,
            updated_text=updated_text,
            changed_fields=changed_fields,
            archive_rel=archive_rel,
            archive_path=archive_path,
            archive_blockers=archive_blockers,
            link_repairs=link_repairs,
        ),
        [],
    )


def incubation_closeout_plan(
    inventory: Inventory,
    source_rel: str,
    *,
    roadmap_item: str,
    archived_plan: str,
    verification_summary: str,
    docs_decision: str,
    extra_archive_blockers: tuple[str, ...] = (),
) -> tuple[RelationshipUpdatePlan | None, list[Finding]]:
    source_rel = _normalize_rel(source_rel)
    source_path = inventory.root / source_rel if source_rel else inventory.root
    errors = _incubation_source_errors(inventory, source_rel, source_path)
    if errors:
        return None, errors
    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("error", "relationship-writeback-refused", f"source could not be read: {exc}", source_rel)]

    closeout_can_mark_implemented = bool(
        archived_plan and verification_summary and docs_decision in FINAL_DOCS_DECISIONS
    )
    blockers = incubation_archive_blockers(
        source_text,
        ignore_stale_implementation_tail=closeout_can_mark_implemented,
    )
    blockers = (*blockers, *extra_archive_blockers)
    if not archived_plan:
        blockers = (*blockers, "missing archived plan")
    if not verification_summary:
        blockers = (*blockers, "missing verification summary")
    if docs_decision not in {"updated", "not-needed"}:
        blockers = (*blockers, "docs_decision is not updated or not-needed")

    updates = {
        "related_roadmap": ROADMAP_REL,
        "related_roadmap_item": roadmap_item,
        "related_plan": archived_plan,
        "archived_plan": archived_plan,
        "implemented_by": archived_plan,
        "verification_summary": verification_summary,
        "docs_decision": docs_decision,
    }
    archive_rel = ""
    if not blockers:
        updates["status"] = "implemented"
        archive_rel = _default_incubation_archive_rel(source_rel)
    return relationship_update_plan(
        inventory,
        source_rel,
        updates,
        archive_to=archive_rel,
        repair_links=bool(archive_rel),
        archive_blockers=blockers,
    )


def incubation_archive_blockers(
    text: str,
    *,
    ignore_stale_implementation_tail: bool = False,
    require_entry_coverage: bool = False,
) -> tuple[str, ...]:
    blockers: list[str] = []
    frontmatter = parse_frontmatter(text)
    for key in OPEN_THREAD_FRONTMATTER_FIELDS:
        value = frontmatter.data.get(key)
        if _frontmatter_value_is_nonempty(value):
            blockers.append(f"frontmatter {key} is present")
    body = text
    if frontmatter.has_frontmatter:
        body = "\n".join(text.splitlines()[max(frontmatter.body_start_line - 1, 0) :])
    coverage_report = incubation_entry_coverage_report(text)
    if not ignore_stale_implementation_tail:
        blockers.extend(_active_implementation_tail_blockers(frontmatter.data, coverage_report))
    if require_entry_coverage:
        blockers.extend(_entry_coverage_archive_blockers(coverage_report))
    elif len(coverage_report.entries) > 1:
        blockers.extend(_entry_coverage_archive_blockers(coverage_report))
    else:
        blockers.extend(_explicit_open_entry_coverage_blockers(coverage_report))
    for heading in re.findall(r"(?m)^#{2,6}\s+(.+?)\s*$", body):
        normalized = re.sub(r"\s+", " ", heading.casefold()).strip()
        if any(marker in normalized for marker in OPEN_THREAD_HEADING_MARKERS):
            blockers.append(f"open-thread heading: {heading.strip()}")
    if re.search(r"(?m)^\s*[-*]\s+\[\s\]\s+", body):
        blockers.append("unchecked task list item")
    return tuple(dict.fromkeys(blockers))


def relationship_hygiene_scan_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return [Finding("info", "relationship-scan-skipped", "relationship hygiene scan runs only for live operating roots")]

    roadmap_items = _roadmap_items(inventory)
    findings: list[Finding] = []
    findings.extend(_roadmap_relationship_findings(inventory, roadmap_items))
    findings.extend(_incubation_relationship_findings(inventory, roadmap_items))
    findings.extend(_incubation_cleanup_advisor_findings(inventory, roadmap_items))
    findings.extend(deep_research_rubric_recovery_findings(inventory, include_present=True))
    if not findings:
        findings.append(Finding("info", "relationship-scan-ok", "no relationship hygiene findings were found"))
    return findings


def cli_text_audit_findings() -> list[Finding]:
    audited = (
        ("incubate --note", "preserves the parsed argv string; use --note-file for shell-safe multi-paragraph text"),
        ("incubate --note-file", "preserves UTF-8 file or stdin text and reports line, character, and hash identity"),
        ("plan --objective/--task", "preserves explicit task/objective text inside the generated plan body"),
        ("roadmap text fields", "single-line by contract and refused when newline or backtick input is supplied"),
        ("writeback closeout fields", "single-line by contract and refused when multiline input is supplied"),
        ("evidence/closeout reports", "read-only proposal surfaces; no operator text is persisted"),
    )
    findings = [
        Finding(
            "info",
            "cli-text-audit-summary",
            f"audited {len(audited)} text-bearing CLI paths; multiline persistence is explicit through file/stdin or plan body paths, while one-line summary fields fail closed instead of silently changing paragraph structure",
        )
    ]
    findings.extend(Finding("info", "cli-text-audit-path", f"{path}: {posture}") for path, posture in audited)
    return findings


def _planned_link_repairs(inventory: Inventory, source_rel: str, archive_rel: str) -> list[tuple[str, Path, str]]:
    repairs: list[tuple[str, Path, str]] = []
    for path in _iter_lifecycle_markdown_files(inventory.root):
        rel_path = path.relative_to(inventory.root).as_posix()
        if rel_path == source_rel or rel_path.startswith("project/archive/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        updated = _replace_exact_route_ref(text, source_rel, archive_rel)
        if updated == text:
            continue
        repairs.append((rel_path, path, updated))
    return repairs


def _incubation_source_errors(inventory: Inventory, source_rel: str, source_path: Path) -> list[Finding]:
    errors: list[Finding] = []
    if not source_rel:
        return [Finding("error", "relationship-writeback-refused", "source incubation path is required")]
    if _rel_has_absolute_or_parent_parts(source_rel):
        return [Finding("error", "relationship-writeback-refused", "source incubation path must be root-relative without parent segments", source_rel)]
    if not (
        source_rel.startswith(f"{INCUBATION_DIR_REL}/")
        or source_rel.startswith(f"{ARCHIVE_INCUBATION_DIR_REL}/")
    ):
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation must be under project/plan-incubation/ or project/archive/reference/incubation/", source_rel))
    if not source_rel.endswith(".md"):
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation must be a Markdown file", source_rel))
    if _path_escapes_root(inventory.root, source_path):
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation path escapes the target root", source_rel))
    elif not source_path.exists():
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation target is missing", source_rel))
    elif source_path.is_symlink():
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation is a symlink", source_rel))
    elif not source_path.is_file():
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation is not a regular file", source_rel))
    return errors


def _iter_lifecycle_markdown_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for rel in ("project/project-state.md", "project/implementation-plan.md", "project/roadmap.md"):
        path = root / rel
        if path.is_file() and not path.is_symlink():
            candidates.append(path)
    for base_rel in ("project/plan-incubation", "project/research", "project/specs", "project/adrs", "project/decisions", "project/verification"):
        base = root / base_rel
        if not base.is_dir() or base.is_symlink():
            continue
        candidates.extend(path for path in base.rglob("*.md") if path.is_file() and not path.is_symlink())
    return sorted(dict.fromkeys(candidates))


def _plan_findings(plan: MemoryHygienePlan, apply: bool, repair_links: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding("info", "memory-hygiene-source", f"{prefix}target source: {plan.source_rel}", plan.source_rel),
        Finding("info", "memory-hygiene-frontmatter-plan", f"{prefix}update lifecycle frontmatter with status={plan.status!r}", plan.source_rel),
    ]
    if plan.promoted_to_rel:
        findings.append(Finding("info", "memory-hygiene-promoted-to", f"{prefix}record promoted_to: {plan.promoted_to_rel}", plan.source_rel))
    if plan.archive_rel:
        findings.append(Finding("info", "memory-hygiene-archive-plan", f"{prefix}archive source to {plan.archive_rel}", plan.archive_rel))
    if plan.entry_coverage_updates:
        findings.append(
            Finding(
                "info",
                "memory-hygiene-entry-coverage-plan",
                f"{prefix}write terminal Entry Coverage for {len(plan.entry_coverage_updates)} entr{'y' if len(plan.entry_coverage_updates) == 1 else 'ies'}",
                plan.source_rel,
            )
        )
    if plan.archive_covered:
        findings.append(Finding("info", "memory-hygiene-archive-covered", f"{prefix}archive source only after terminal Entry Coverage validation", plan.archive_rel or plan.source_rel))
    if repair_links:
        count = len(plan.link_repairs)
        findings.append(Finding("info", "memory-hygiene-link-plan", f"{prefix}repair exact links in {count} file(s)", plan.archive_rel or plan.source_rel))
    return findings


def _boundary_findings() -> list[Finding]:
    return [
        rails_not_cognition_boundary_finding(INCUBATION_DIR_REL),
        Finding(
            "info",
            "memory-hygiene-boundary",
            "memory-hygiene writes only declared MLH-owned research/incubation source, explicit archive target, and exact source-path link repairs in eligible live operating roots",
        ),
        Finding(
            "info",
            "memory-hygiene-authority",
            "memory hygiene output is bounded mutation evidence only; it cannot approve closeout, archive, commit, rollback, or lifecycle decisions",
        ),
    ]


def _relationship_scan_boundary_findings() -> list[Finding]:
    return [
        rails_not_cognition_boundary_finding(INCUBATION_DIR_REL),
        Finding(
            "info",
            "relationship-scan-read-only",
            "relationship hygiene scan writes no files and cannot approve repair, closeout, archive, commit, rollback, or lifecycle decisions",
        ),
        Finding(
            "info",
            "relationship-scan-archive-route",
            "safe incubation auto-archive candidates use project/archive/reference/incubation/** unless a later route policy changes that lane",
        ),
    ]


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "memory-hygiene-root-posture", f"root kind: {inventory.root_kind}")


def _roadmap_items(inventory: Inventory) -> dict[str, dict[str, object]]:
    roadmap = inventory.surface_by_rel.get(ROADMAP_REL)
    if not roadmap or not roadmap.exists:
        return {}
    items: dict[str, dict[str, object]] = {}
    current: dict[str, object] | None = None
    for line in roadmap.content.splitlines():
        if re.match(r"^###\s+\S", line.strip()):
            if current and isinstance(current.get("id"), str):
                items[str(current["id"])] = current
            current = {}
            continue
        if current is None:
            continue
        match = re.match(r"^-\s+`([A-Za-z0-9_-]+)`:\s*(.*?)\s*$", line.strip())
        if not match:
            continue
        key = match.group(1)
        raw = match.group(2).strip()
        if raw.startswith("`") and raw.endswith("`"):
            raw = raw[1:-1]
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
                parsed = []
            current[key] = parsed if isinstance(parsed, list) else []
        else:
            current[key] = raw
    if current and isinstance(current.get("id"), str):
        items[str(current["id"])] = current
    return items


def _roadmap_relationship_findings(inventory: Inventory, roadmap_items: dict[str, dict[str, object]]) -> list[Finding]:
    findings: list[Finding] = []
    live_consumers_by_source = _live_source_incubation_consumers_by_source(roadmap_items)
    for source_incubation, item_ids in sorted(live_consumers_by_source.items()):
        if len(item_ids) <= 1:
            continue
        findings.append(
            Finding(
                "warn",
                "relationship-shared-source-incubation-consumers",
                (
                    f"source_incubation {source_incubation} has multiple live roadmap consumers: "
                    f"{', '.join(item_ids)}; convert non-owning consumers to related_incubation or add terminal coverage "
                    "before whole-note archive or source path retargeting"
                ),
                ROADMAP_REL,
            )
        )
    for item_id, fields in sorted(roadmap_items.items()):
        status = str(fields.get("status") or "")
        source_incubation = _normalize_rel(fields.get("source_incubation"))
        archived_plan = _normalize_rel(fields.get("archived_plan"))
        related_plan = _normalize_rel(fields.get("related_plan"))
        verification_summary = str(fields.get("verification_summary") or "").strip()
        docs_decision = str(fields.get("docs_decision") or "").strip()
        terminal_history_stub = roadmap_item_is_terminal_history_stub(fields)
        if source_incubation:
            source_path = inventory.root / source_incubation
            if not source_path.is_file():
                findings.append(Finding("warn", "relationship-stale-path", f"roadmap item {item_id!r} source_incubation target is missing: {source_incubation}", ROADMAP_REL))
            else:
                source_surface = inventory.surface_by_rel.get(source_incubation)
                data = source_surface.frontmatter.data if source_surface else parse_frontmatter(source_path.read_text(encoding="utf-8", errors="replace")).data
                reciprocal_item = str(data.get("related_roadmap_item") or "")
                promoted_to = _normalize_rel(data.get("promoted_to"))
                related_roadmap = _normalize_rel(data.get("related_roadmap"))
                if reciprocal_item != item_id and promoted_to != ROADMAP_REL and related_roadmap != ROADMAP_REL:
                    findings.append(
                        Finding(
                            "warn",
                            "relationship-missing-reciprocal",
                            f"roadmap item {item_id!r} points to {source_incubation}, but the incubation note does not point back to the roadmap item",
                            source_incubation,
                    )
                )
        if status == "done":
            if not archived_plan and not terminal_history_stub:
                findings.append(Finding("warn", "relationship-roadmap-done-missing-archive", f"done roadmap item {item_id!r} has no archived_plan", ROADMAP_REL))
            if not verification_summary:
                findings.append(Finding("warn", "relationship-roadmap-done-missing-verification", f"done roadmap item {item_id!r} has no verification_summary", ROADMAP_REL))
            if docs_decision not in {"updated", "not-needed"}:
                if _done_item_has_reconstructed_archive_docs_boundary(inventory, archived_plan):
                    findings.append(
                        Finding(
                            "info",
                            "relationship-roadmap-done-reconstructed-docs",
                            (
                                f"done roadmap item {item_id!r} keeps docs_decision provisional because its archived_plan "
                                "is reconstructed historical evidence; re-review docs only when a current lifecycle decision depends on it"
                            ),
                            archived_plan,
                        )
                    )
                else:
                    findings.append(Finding("warn", "relationship-roadmap-done-missing-docs", f"done roadmap item {item_id!r} lacks a final docs_decision", ROADMAP_REL))
            if archived_plan and related_plan == "project/implementation-plan.md":
                findings.append(Finding("warn", "relationship-stale-active-plan-link", f"done roadmap item {item_id!r} still has related_plan pointing at the active plan", ROADMAP_REL))
    return findings


def _incubation_relationship_findings(inventory: Inventory, roadmap_items: dict[str, dict[str, object]]) -> list[Finding]:
    findings: list[Finding] = []
    items_by_source: dict[str, tuple[str, dict[str, object]]] = {}
    for item_id, fields in roadmap_items.items():
        source = _normalize_rel(fields.get("source_incubation"))
        if source:
            items_by_source[source] = (item_id, fields)
    live_consumers_by_source = _live_source_incubation_consumers_by_source(roadmap_items)

    for surface in sorted(inventory.present_surfaces, key=lambda item: item.rel_path):
        if not surface.rel_path.startswith(f"{INCUBATION_DIR_REL}/") or surface.path.suffix.lower() != ".md":
            continue
        data = surface.frontmatter.data
        status = str(data.get("status") or "").strip().casefold()
        relation_values = [data.get(field) for field in RELATIONSHIP_STATUS_FIELDS]
        related_item = str(data.get("related_roadmap_item") or "")
        source_item = items_by_source.get(surface.rel_path)
        item_id = related_item or (source_item[0] if source_item else "")
        roadmap_detached_meta_feedback = _meta_feedback_candidate_is_roadmap_detached(data, surface.content, item_id)
        if status in {"implemented", "archived", "rejected", "superseded"}:
            findings.append(Finding("warn", "relationship-active-incubation-closed", f"closed incubation note is still in the active incubation lane with status {status!r}", surface.rel_path))
        if roadmap_detached_meta_feedback:
            findings.append(
                Finding(
                    "info",
                    "relationship-meta-feedback-candidate",
                    "meta-feedback candidate is roadmap-detached operating memory until explicit roadmap/spec/plan promotion",
                    surface.rel_path,
                )
            )
        elif not any(_frontmatter_value_is_nonempty(value) for value in relation_values):
            findings.append(Finding("warn", "relationship-orphan-incubation", "incubation note has no roadmap, plan, archive, rejection, or supersession relationship metadata", surface.rel_path))
        coverage_report = incubation_entry_coverage_report(surface.content)
        for blocker in _active_implementation_tail_blockers(data, coverage_report):
            findings.append(
                Finding(
                    "warn",
                    "relationship-active-incubation-stale-implementation-tail",
                    blocker,
                    surface.rel_path,
                )
            )
        if roadmap_detached_meta_feedback:
            continue
        findings.extend(_incubation_entry_coverage_findings(surface.rel_path, surface.content))
        findings.extend(_incubation_split_suggestion_findings(surface.rel_path, surface.content))
        item_fields = roadmap_items.get(item_id) if item_id else None
        if not item_fields or str(item_fields.get("status") or "") != "done":
            continue
        live_consumers = live_consumers_by_source.get(surface.rel_path, ())
        if live_consumers:
            findings.append(
                Finding(
                    "warn",
                    "relationship-mixed-incubation-blocker",
                    (
                        f"incubation note is linked to done roadmap item {item_id!r} but still has live "
                        f"source_incubation consumers: {', '.join(live_consumers)}"
                    ),
                    surface.rel_path,
                )
            )
            continue
        structurally_covered = False
        item_fields = roadmap_items.get(item_id) if item_id else None
        if item_fields:
            archived_plan = _normalize_rel(item_fields.get("archived_plan"))
            verification = str(item_fields.get("verification_summary") or "").strip()
            docs_decision = str(item_fields.get("docs_decision") or "").strip()
            structurally_covered = bool(archived_plan and verification and docs_decision in FINAL_DOCS_DECISIONS)
        blockers = incubation_archive_blockers(
            surface.content,
            ignore_stale_implementation_tail=structurally_covered,
        )
        if blockers:
            findings.append(
                Finding(
                    "warn",
                    "relationship-mixed-incubation-blocker",
                    f"incubation note is linked to done roadmap item {item_id!r} but is not safe for whole-file archive: {', '.join(blockers)}",
                    surface.rel_path,
                )
            )
            continue
        if structurally_covered:
            archive_rel = _default_incubation_archive_rel(surface.rel_path)
            findings.append(
                Finding(
                    "info",
                    "relationship-auto-archive-candidate",
                    (
                        f"single-entry incubation note is structurally covered by roadmap item {item_id!r}; "
                        "safe cleanup command: "
                        f"{mlh_command('memory-hygiene', '--dry-run', '--source', surface.rel_path, '--status', 'implemented', '--archive-to', archive_rel, '--repair-links')}"
                    ),
                    surface.rel_path,
                )
            )
    return findings


def _incubation_cleanup_advisor_findings(inventory: Inventory, roadmap_items: dict[str, dict[str, object]]) -> list[Finding]:
    surfaces = [
        surface
        for surface in sorted(inventory.present_surfaces, key=lambda item: item.rel_path)
        if surface.rel_path.startswith(f"{INCUBATION_DIR_REL}/") and surface.path.suffix.lower() == ".md"
    ]
    if not surfaces:
        return []

    items_by_source: dict[str, tuple[str, dict[str, object]]] = {}
    for item_id, fields in roadmap_items.items():
        source = _normalize_rel(fields.get("source_incubation"))
        if source:
            items_by_source[source] = (item_id, fields)
    live_consumers_by_source = _live_source_incubation_consumers_by_source(roadmap_items)

    findings: list[Finding] = []
    counts = {"archive": 0, "keep": 0, "ambiguous": 0}
    batch_candidates: list[MemoryHygieneBatchCandidate] = []
    for surface in surfaces:
        data = surface.frontmatter.data
        status = str(data.get("status") or "").strip().casefold()
        relation_values = [data.get(field) for field in RELATIONSHIP_STATUS_FIELDS]
        related_item = str(data.get("related_roadmap_item") or "")
        source_item = items_by_source.get(surface.rel_path)
        item_id = related_item or (source_item[0] if source_item else "")
        roadmap_detached_meta_feedback = _meta_feedback_candidate_is_roadmap_detached(data, surface.content, item_id)
        item_fields = roadmap_items.get(item_id) if item_id else None
        roadmap_status = str(item_fields.get("status") or "").strip().casefold() if item_fields else ""
        archived_plan = _normalize_rel(item_fields.get("archived_plan")) if item_fields else ""
        verification = str(item_fields.get("verification_summary") or "").strip() if item_fields else ""
        docs_decision = str(item_fields.get("docs_decision") or "").strip() if item_fields else ""
        structurally_covered = roadmap_status == "done" and bool(archived_plan and verification and docs_decision in FINAL_DOCS_DECISIONS)
        blockers = incubation_archive_blockers(
            surface.content,
            ignore_stale_implementation_tail=structurally_covered,
        )
        archive_rel = _default_incubation_archive_rel(surface.rel_path)

        if roadmap_detached_meta_feedback:
            counts["keep"] += 1
            findings.append(
                Finding(
                    "info",
                    "incubation-cleanup-keep-active",
                    "keep active: meta-feedback candidate is roadmap-detached operating memory until explicit promotion",
                    surface.rel_path,
                )
            )
            continue

        link_repairs = _planned_link_repairs(inventory, surface.rel_path, archive_rel)

        if link_repairs:
            findings.append(
                Finding(
                    "info",
                    "incubation-cleanup-link-repair-candidate",
                    f"exact source-path references appear in {len(link_repairs)} lifecycle file(s); include --repair-links when archiving {surface.rel_path}",
                    surface.rel_path,
                )
            )

        followup_markers = _incubation_followup_markers(surface.content)
        if followup_markers:
            findings.append(
                Finding(
                    "info",
                    "incubation-cleanup-followup-extraction",
                    f"extract or explicitly cover follow-up material before cleanup: {', '.join(followup_markers)}",
                    surface.rel_path,
                )
            )

        entry_coverage_blockers = _entry_coverage_cleanup_blockers(surface.content)
        if entry_coverage_blockers:
            findings.append(
                Finding(
                    "info",
                    "incubation-cleanup-entry-coverage-needed",
                    f"entry coverage must be terminal before whole-file cleanup: {', '.join(entry_coverage_blockers)}",
                    surface.rel_path,
                )
            )

        archive_status = _archive_candidate_status(status, structurally_covered)
        live_consumers = live_consumers_by_source.get(surface.rel_path, ())
        shared_live_consumers = tuple(live_consumers) if len(live_consumers) > 1 else ()
        if not shared_live_consumers and roadmap_status == "done":
            shared_live_consumers = tuple(item for item in live_consumers if item != item_id)
        if shared_live_consumers:
            counts["keep"] += 1
            findings.append(
                Finding(
                    "info",
                    "incubation-cleanup-keep-active",
                    (
                        "keep active while live source_incubation consumers remain: "
                        f"{', '.join(shared_live_consumers)}"
                    ),
                    surface.rel_path,
                )
            )
            continue
        if not blockers and (structurally_covered or status in ALLOWED_STATUS_VALUES):
            counts["archive"] += 1
            status_parts = () if archive_status == "archived" else ("--status", archive_status)
            dry_run_command = mlh_command(
                "memory-hygiene",
                "--dry-run",
                "--source",
                surface.rel_path,
                *status_parts,
                "--archive-to",
                archive_rel,
                "--repair-links",
            )
            apply_command = dry_run_command.replace("--dry-run", "--apply", 1)
            candidate = MemoryHygieneBatchCandidate(
                candidate_id=_batch_candidate_id(surface.rel_path, archive_status, archive_rel),
                source_rel=surface.rel_path,
                source_hash=_sha256_text(surface.content),
                status=archive_status,
                archive_rel=archive_rel,
                link_repairs=_batch_link_repair_records(link_repairs),
                dry_run_command=dry_run_command,
                apply_command=apply_command,
            )
            batch_candidates.append(candidate)
            findings.append(
                Finding(
                    "info",
                    "incubation-cleanup-archive-candidate",
                    f"preview safe cleanup: {dry_run_command}",
                    surface.rel_path,
                )
            )
            continue

        if not item_id and not any(_frontmatter_value_is_nonempty(value) for value in relation_values):
            counts["ambiguous"] += 1
            findings.append(
                Finding(
                    "warn",
                    "incubation-cleanup-ambiguous",
                    "incubation note has no route relationship metadata; record whether it belongs with roadmap, research, rejected, superseded, or explicitly kept posture before cleanup",
                    surface.rel_path,
                )
            )
            continue

        counts["keep"] += 1
        reason = _incubation_keep_active_reason(item_id, roadmap_status, blockers, status)
        findings.append(Finding("info", "incubation-cleanup-keep-active", f"keep active: {reason}", surface.rel_path))

    findings.append(
        Finding(
            "info",
            "incubation-cleanup-advisor-summary",
            (
                f"reported structural cleanup posture for {len(surfaces)} active incubation note(s): "
                f"{counts['archive']} archive candidate(s), {counts['keep']} keep-active, {counts['ambiguous']} ambiguous"
            ),
        )
    )
    if batch_candidates:
        findings.extend(_batch_proposal_findings(tuple(batch_candidates)))
    return findings


def _incubation_cleanup_batch_candidates(inventory: Inventory) -> tuple[MemoryHygieneBatchCandidate, ...]:
    roadmap_items = _roadmap_items(inventory)
    surfaces = [
        surface
        for surface in sorted(inventory.present_surfaces, key=lambda item: item.rel_path)
        if surface.rel_path.startswith(f"{INCUBATION_DIR_REL}/") and surface.path.suffix.lower() == ".md"
    ]
    items_by_source: dict[str, tuple[str, dict[str, object]]] = {}
    for item_id, fields in roadmap_items.items():
        source = _normalize_rel(fields.get("source_incubation"))
        if source:
            items_by_source[source] = (item_id, fields)
    live_consumers_by_source = _live_source_incubation_consumers_by_source(roadmap_items)

    candidates: list[MemoryHygieneBatchCandidate] = []
    for surface in surfaces:
        data = surface.frontmatter.data
        status = str(data.get("status") or "").strip().casefold()
        related_item = str(data.get("related_roadmap_item") or "")
        source_item = items_by_source.get(surface.rel_path)
        item_id = related_item or (source_item[0] if source_item else "")
        if _meta_feedback_candidate_is_roadmap_detached(data, surface.content, item_id):
            continue
        item_fields = roadmap_items.get(item_id) if item_id else None
        roadmap_status = str(item_fields.get("status") or "").strip().casefold() if item_fields else ""
        archived_plan = _normalize_rel(item_fields.get("archived_plan")) if item_fields else ""
        verification = str(item_fields.get("verification_summary") or "").strip() if item_fields else ""
        docs_decision = str(item_fields.get("docs_decision") or "").strip() if item_fields else ""
        structurally_covered = roadmap_status == "done" and bool(archived_plan and verification and docs_decision in FINAL_DOCS_DECISIONS)
        blockers = incubation_archive_blockers(
            surface.content,
            ignore_stale_implementation_tail=structurally_covered,
        )
        live_consumers = live_consumers_by_source.get(surface.rel_path, ())
        shared_live_consumers = tuple(live_consumers) if len(live_consumers) > 1 else ()
        if not shared_live_consumers and roadmap_status == "done":
            shared_live_consumers = tuple(item for item in live_consumers if item != item_id)
        if shared_live_consumers or blockers or not (structurally_covered or status in ALLOWED_STATUS_VALUES):
            continue

        archive_status = _archive_candidate_status(status, structurally_covered)
        archive_rel = _default_incubation_archive_rel(surface.rel_path)
        link_repairs = _planned_link_repairs(inventory, surface.rel_path, archive_rel)
        status_parts = () if archive_status == "archived" else ("--status", archive_status)
        dry_run_command = mlh_command(
            "memory-hygiene",
            "--dry-run",
            "--source",
            surface.rel_path,
            *status_parts,
            "--archive-to",
            archive_rel,
            "--repair-links",
        )
        apply_command = dry_run_command.replace("--dry-run", "--apply", 1)
        candidates.append(
            MemoryHygieneBatchCandidate(
                candidate_id=_batch_candidate_id(surface.rel_path, archive_status, archive_rel),
                source_rel=surface.rel_path,
                source_hash=_sha256_text(surface.content),
                status=archive_status,
                archive_rel=archive_rel,
                link_repairs=_batch_link_repair_records(link_repairs),
                dry_run_command=dry_run_command,
                apply_command=apply_command,
            )
        )
    return tuple(candidates)


def _batch_proposal_findings(candidates: tuple[MemoryHygieneBatchCandidate, ...]) -> list[Finding]:
    token = _batch_proposal_token(candidates)
    candidate_ids = ", ".join(candidate.candidate_id for candidate in candidates)
    batch_apply_command = mlh_command("memory-hygiene", "--apply", "--scan", "--proposal-token", token)
    findings = [
        Finding(
            "info",
            "incubation-cleanup-batch-preview",
            (
                f"reviewable batch proposal: candidate_count={len(candidates)}; candidate_ids={candidate_ids}; "
                f"batch_review_token={token}; batch_apply_command={batch_apply_command}; "
                "dry-run scan writes no files and the token binds this exact current proposal"
            ),
        )
    ]
    for candidate in candidates:
        link_repairs = ", ".join(_link_repair_rel_paths(candidate)) if candidate.link_repairs else "none"
        findings.append(
            Finding(
                "info",
                "incubation-cleanup-batch-candidate",
                (
                    f"candidate_id={candidate.candidate_id}; source={candidate.source_rel}; status={candidate.status}; "
                    f"source_hash={candidate.source_hash}; "
                    f"archive_target={candidate.archive_rel}; link_repairs={link_repairs}; "
                    f"next_safe_command={candidate.dry_run_command}; apply_command={candidate.apply_command}"
                ),
                candidate.source_rel,
            )
        )
    findings.append(
        Finding(
            "info",
            "incubation-cleanup-batch-token-command",
            (
                "copy-ready token-bound apply shape: review candidate ids, source hashes, archive targets, and link repairs, "
                f"then run {batch_apply_command} only while the scan proposal is still current. "
                "This does not open plans, mutate roadmap state, close out work, stage, commit, rollback, or move to a next plan."
            ),
        )
    )
    return findings


def _batch_link_repair_records(link_repairs: list[tuple[str, Path, str]]) -> tuple[tuple[str, str, str], ...]:
    records: list[tuple[str, str, str]] = []
    for rel_path, path, updated_text in link_repairs:
        try:
            current_text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        records.append((rel_path, _sha256_text(current_text), _sha256_text(updated_text)))
    return tuple(records)


def _link_repair_rel_paths(candidate: MemoryHygieneBatchCandidate) -> tuple[str, ...]:
    return tuple(record[0] for record in candidate.link_repairs)


def _batch_candidate_id(source_rel: str, status: str, archive_rel: str) -> str:
    return "mhc-" + _stable_digest({"source": source_rel, "status": status, "archive": archive_rel})[:12]


def _batch_proposal_token(candidates: tuple[MemoryHygieneBatchCandidate, ...]) -> str:
    payload = {
        "schema": "mylittleharness.memory-hygiene-batch-proposal.v1",
        "route_class": "memory-hygiene-covered-incubation-cleanup",
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "source": candidate.source_rel,
                "source_hash": candidate.source_hash,
                "status": candidate.status,
                "archive": candidate.archive_rel,
                "link_repairs": [
                    {
                        "path": rel_path,
                        "source_hash": source_hash,
                        "updated_hash": updated_hash,
                    }
                    for rel_path, source_hash, updated_hash in candidate.link_repairs
                ],
                "dry_run_command": candidate.dry_run_command,
                "apply_command": candidate.apply_command,
            }
            for candidate in candidates
        ],
        "boundary": "proposal token authorizes only exact current covered cleanup batch apply; per-source apply remains explicit",
    }
    return "mhb-" + _stable_digest(payload)[:16]


def _stable_digest(value: object) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _incubation_keep_active_reason(item_id: str, roadmap_status: str, blockers: tuple[str, ...], status: str) -> str:
    if blockers:
        if item_id and roadmap_status:
            return f"roadmap item {item_id!r} is {roadmap_status}; cleanup blockers remain: {', '.join(blockers)}"
        return f"cleanup blockers remain: {', '.join(blockers)}"
    if item_id and roadmap_status:
        return f"roadmap item {item_id!r} is {roadmap_status}, not done with final closeout evidence"
    if status and status not in TERMINAL_INCUBATION_STATUSES:
        return f"frontmatter status is {status!r}"
    return "no safe archive proof was found"


def _meta_feedback_candidate_is_active(content: str) -> bool:
    return META_FEEDBACK_CLUSTER_BEGIN in content and "[MLH-Fix-Candidate]" in content


def _meta_feedback_candidate_is_roadmap_detached(data: dict[str, object], content: str, item_id: str) -> bool:
    if item_id or not _meta_feedback_candidate_is_active(content):
        return False
    relation_values = [data.get(field) for field in RELATIONSHIP_STATUS_FIELDS]
    return not any(_frontmatter_value_is_nonempty(value) for value in relation_values)


def _done_item_has_reconstructed_archive_docs_boundary(inventory: Inventory, archived_plan: str) -> bool:
    if not archived_plan.startswith("project/archive/plans/"):
        return False
    archive_path = inventory.root / archived_plan
    if not archive_path.is_file():
        return False
    try:
        content = archive_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    frontmatter = parse_frontmatter(content)
    docs_decision = str(frontmatter.data.get("docs_decision") or "").strip().casefold()
    if docs_decision != "uncertain":
        return False
    status_values = " ".join(str(frontmatter.data.get(field) or "") for field in RECONSTRUCTED_ARCHIVE_STATUS_FIELDS).casefold()
    if "reconstruct" in status_values:
        return True
    boundary_values = " ".join(str(frontmatter.data.get(field) or "") for field in RECONSTRUCTED_ARCHIVE_BOUNDARY_FIELDS).casefold()
    if "reconstructed historical" in boundary_values or "recovered archive evidence" in boundary_values:
        return True
    body = content
    if frontmatter.has_frontmatter:
        body = "\n".join(content.splitlines()[max(frontmatter.body_start_line - 1, 0) :])
    normalized_body = body.casefold()
    return any(marker in normalized_body for marker in RECONSTRUCTED_ARCHIVE_BODY_MARKERS)


def _live_source_incubation_consumers_by_source(
    roadmap_items: dict[str, dict[str, object]]
) -> dict[str, tuple[str, ...]]:
    consumers: dict[str, list[str]] = {}
    for item_id, fields in roadmap_items.items():
        source = _normalize_rel(fields.get("source_incubation"))
        if not source:
            continue
        status = str(fields.get("status") or "").strip().casefold()
        if status in TERMINAL_ROADMAP_STATUSES:
            continue
        consumers.setdefault(source, []).append(item_id)
    return {source: tuple(item_ids) for source, item_ids in consumers.items()}


def _archive_candidate_status(status: str, structurally_covered: bool) -> str:
    if status in ALLOWED_STATUS_VALUES:
        return status
    if structurally_covered:
        return "implemented"
    return "archived"


def _active_implementation_tail_blockers(data: dict[str, object], coverage_report: EntryCoverageReport) -> tuple[str, ...]:
    fields = _stale_implementation_tail_fields(data)
    if not fields:
        return ()
    status = str(data.get("status") or "").strip().casefold().replace("_", "-")
    if status in ALLOWED_STATUS_VALUES or _entry_coverage_is_terminal(coverage_report):
        return ()
    status_label = status or "missing"
    return (
        (
            f"active incubation status {status_label!r} carries stale implementation tail field(s): "
            f"{', '.join(fields)}; add terminal Entry Coverage or set status implemented before archive"
        ),
    )


def _stale_implementation_tail_fields(data: dict[str, object]) -> tuple[str, ...]:
    return tuple(field for field in IMPLEMENTATION_TAIL_FIELDS if _frontmatter_value_is_nonempty(data.get(field)))


def _entry_coverage_is_terminal(report: EntryCoverageReport) -> bool:
    if not report.entries or not report.coverage or report.errors:
        return False
    entry_ids = {entry.entry_id for entry in report.entries}
    coverage_by_id = {record.entry_id: record for record in report.coverage}
    if set(coverage_by_id) != entry_ids:
        return False
    return all(not _entry_coverage_record_blockers(record) for record in report.coverage)


def _entry_coverage_cleanup_blockers(text: str) -> tuple[str, ...]:
    report = incubation_entry_coverage_report(text)
    if len(report.entries) > 1:
        return tuple(_entry_coverage_archive_blockers(report))
    return tuple(_explicit_open_entry_coverage_blockers(report))


def _incubation_followup_markers(text: str) -> tuple[str, ...]:
    markers: list[str] = []
    frontmatter = parse_frontmatter(text)
    for key in OPEN_THREAD_FRONTMATTER_FIELDS:
        if _frontmatter_value_is_nonempty(frontmatter.data.get(key)):
            markers.append(f"frontmatter {key}")
    body = text
    if frontmatter.has_frontmatter:
        body = "\n".join(text.splitlines()[max(frontmatter.body_start_line - 1, 0) :])
    for heading in re.findall(r"(?m)^#{2,6}\s+(.+?)\s*$", body):
        normalized = re.sub(r"\s+", " ", heading.casefold()).strip()
        if any(marker in normalized for marker in OPEN_THREAD_HEADING_MARKERS):
            markers.append(f"heading {heading.strip()!r}")
    if re.search(r"(?m)^\s*[-*]\s+\[\s\]\s+", body):
        markers.append("unchecked task list item")
    return tuple(dict.fromkeys(markers))


def incubation_entry_coverage_report(text: str) -> EntryCoverageReport:
    coverage, errors = _entry_coverage_records(text)
    return EntryCoverageReport(
        entries=tuple(_incubation_entries(text)),
        coverage=tuple(coverage),
        errors=tuple(errors),
    )


def _incubation_entries(text: str) -> list[IncubationEntry]:
    frontmatter = parse_frontmatter(text)
    lines = text.splitlines()
    start_index = max(frontmatter.body_start_line - 1, 0) if frontmatter.has_frontmatter else 0
    raw_entries: list[tuple[str, str, int]] = []
    for index in range(start_index, len(lines)):
        match = re.match(r"^###\s+(\d{4}-\d{2}-\d{2})(?:\s+[-:]\s+(.+?))?\s*$", lines[index].strip())
        if not match:
            continue
        raw_entries.append((match.group(1), lines[index].strip()[4:].strip(), index + 1))

    date_counts: dict[str, int] = {}
    for entry_date, _heading, _line in raw_entries:
        date_counts[entry_date] = date_counts.get(entry_date, 0) + 1

    seen: dict[str, int] = {}
    entries: list[IncubationEntry] = []
    for entry_date, heading, line in raw_entries:
        seen[entry_date] = seen.get(entry_date, 0) + 1
        entry_id = entry_date if date_counts[entry_date] == 1 else f"{entry_date}#{seen[entry_date]}"
        entries.append(IncubationEntry(entry_id=entry_id, heading=heading, line=line))
    return entries


def _entry_coverage_records(text: str) -> tuple[list[EntryCoverage], list[str]]:
    section = _entry_coverage_section(text)
    if section is None:
        return [], []
    start_index, end_index = section
    records: list[EntryCoverage] = []
    errors: list[str] = []
    seen: set[str] = set()
    lines = text.splitlines()
    for index in range(start_index, end_index):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped:
            continue
        if not stripped.startswith(("- ", "* ")):
            continue
        parsed = _parse_entry_coverage_line(stripped, index + 1)
        if parsed is None:
            errors.append(f"line {index + 1}: entry coverage bullet must be `<entry-id>: <status> <destination>`")
            continue
        if parsed.entry_id in seen:
            errors.append(f"line {index + 1}: duplicate entry coverage id {parsed.entry_id!r}")
            continue
        seen.add(parsed.entry_id)
        records.append(parsed)
    return records, errors


def _entry_coverage_section(text: str) -> tuple[int, int] | None:
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,6})\s+(.+?)\s*$", line.strip())
        if match:
            headings.append((index, len(match.group(1)), _normalized_heading(match.group(2))))
    for position, (start, level, title) in enumerate(headings):
        if title != ENTRY_COVERAGE_HEADING:
            continue
        end = len(lines)
        for next_start, next_level, _next_title in headings[position + 1 :]:
            if next_level <= level:
                end = next_start
                break
        return start + 1, end
    return None


def _parse_entry_coverage_line(line: str, line_number: int) -> EntryCoverage | None:
    match = re.match(r"^[-*]\s+`?(?P<entry_id>[^`:]+?)`?\s*:\s*(?P<rest>.+?)\s*$", line)
    if not match:
        return None
    entry_id = _normalized_entry_id(match.group("entry_id"))
    rest = match.group("rest").strip()
    status_match = re.match(r"`?(?P<status>[A-Za-z][A-Za-z0-9_-]*)`?(?P<detail>.*)$", rest)
    if not entry_id or not status_match:
        return None
    status = _normalized_coverage_status(status_match.group("status"))
    detail = status_match.group("detail").strip()
    detail = re.sub(r"^\s*[-;,:]\s*", "", detail).strip()
    return EntryCoverage(entry_id=entry_id, status=status, detail=detail, line=line_number)


def _entry_coverage_archive_blockers(report: EntryCoverageReport) -> list[str]:
    blockers: list[str] = []
    entry_ids = {entry.entry_id for entry in report.entries}
    coverage_by_id = {record.entry_id: record for record in report.coverage}
    if report.errors:
        blockers.append("entry coverage metadata is malformed")
    if not report.coverage:
        blockers.append("dated incubation entries without entry coverage")
        return blockers
    for entry in report.entries:
        record = coverage_by_id.get(entry.entry_id)
        if record is None:
            blockers.append(f"entry coverage missing {entry.entry_id}")
            continue
        blockers.extend(_entry_coverage_record_blockers(record))
    for record in report.coverage:
        if record.entry_id not in entry_ids:
            blockers.append(f"entry coverage references unknown entry {record.entry_id}")
    return blockers


def _explicit_open_entry_coverage_blockers(report: EntryCoverageReport) -> list[str]:
    blockers: list[str] = []
    if report.errors:
        blockers.append("entry coverage metadata is malformed")
    for record in report.coverage:
        blockers.extend(_entry_coverage_record_blockers(record))
    return blockers


def _entry_coverage_record_blockers(record: EntryCoverage) -> list[str]:
    if record.status in ENTRY_COVERAGE_OPEN_STATUSES:
        return [f"entry coverage {record.entry_id} is {record.status}"]
    if record.status not in ENTRY_COVERAGE_TERMINAL_STATUSES:
        return [f"entry coverage {record.entry_id} has unknown status {record.status!r}"]
    if not _entry_coverage_has_destination(record):
        return [f"entry coverage {record.entry_id} lacks destination detail"]
    return []


def _entry_coverage_has_destination(record: EntryCoverage) -> bool:
    if record.status == "rejected":
        return bool(record.detail)
    if not record.detail:
        return False
    return bool(_entry_coverage_destination_ref(record.detail))


def _entry_coverage_destination_ref(detail: str) -> str:
    normalized = detail.replace("\\", "/").strip()
    normalized = re.sub(r"^(via|to|as|in)\s+", "", normalized, flags=re.IGNORECASE).strip()
    normalized = normalized.strip("`\"'.,;:)]}")
    match = re.search(
        r"(?<![\w:/.-])((?:project|docs|src|tests|specs|\.agents|\.codex)/[A-Za-z0-9_./{}*\-]+|README\.md|AGENTS\.md|pyproject\.toml)(?![\w/.-])",
        normalized,
    )
    return match.group(1) if match else ""


def _replace_exact_route_ref(text: str, source_rel: str, archive_rel: str) -> str:
    pattern = re.compile(rf"(?<![A-Za-z0-9_./-]){re.escape(source_rel)}(?![A-Za-z0-9_./-])")
    return pattern.sub(archive_rel, text)


def _incubation_entry_coverage_findings(rel_path: str, text: str) -> list[Finding]:
    report = incubation_entry_coverage_report(text)
    if not report.entries:
        return []
    findings: list[Finding] = []
    for error in report.errors:
        findings.append(Finding("warn", "relationship-entry-coverage-malformed", error, rel_path))
    if len(report.entries) <= 1:
        for record in report.coverage:
            for blocker in _entry_coverage_record_blockers(record):
                findings.append(Finding("warn", "relationship-entry-coverage-open", blocker, rel_path, record.line))
        return findings

    blockers = _entry_coverage_archive_blockers(report)
    if blockers:
        findings.append(
            Finding(
                "warn",
                "relationship-entry-coverage-needed",
                f"mixed incubation note needs terminal Entry Coverage before whole-file archive: {', '.join(blockers)}",
                rel_path,
            )
        )
        return findings

    findings.append(
        Finding(
            "info",
            "relationship-entry-coverage-complete",
            f"all {len(report.entries)} dated incubation entries have terminal Entry Coverage metadata",
            rel_path,
        )
    )
    return findings


def _incubation_split_suggestion_findings(rel_path: str, text: str) -> list[Finding]:
    report = incubation_entry_coverage_report(text)
    if len(report.entries) <= 1:
        return []
    entry_ids = [entry.entry_id for entry in report.entries]
    if not report.coverage:
        return [
            Finding(
                "info",
                "relationship-semantic-split-suggestion",
                f"review split suggestion: dated entries {', '.join(entry_ids)} may be separate ideas; add Entry Coverage or split them into separate incubation notes before archiving",
                rel_path,
            )
        ]

    terminal_ids = {
        record.entry_id
        for record in report.coverage
        if record.status in ENTRY_COVERAGE_TERMINAL_STATUSES and _entry_coverage_has_destination(record)
    }
    open_ids = [entry.entry_id for entry in report.entries if entry.entry_id not in terminal_ids]
    if terminal_ids and open_ids:
        return [
            Finding(
                "info",
                "relationship-semantic-split-suggestion",
                f"review split suggestion: covered entries {', '.join(sorted(terminal_ids))} and open entries {', '.join(open_ids)} should be separated or explicitly covered before whole-file archive; this is a heuristic no-write suggestion",
                rel_path,
            )
        ]
    return []


def _text_with_frontmatter_scalars(text: str, updates: dict[str, str], *, clear_fields: tuple[str, ...] = ()) -> tuple[str, str | None]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text, "source frontmatter is required for relationship writeback"
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return text, "source frontmatter is malformed"

    replacement_values = {**updates, **{field: "" for field in clear_fields}}
    seen, closing_index = _replace_frontmatter_scalar_blocks(lines, closing_index, replacement_values)

    missing = [key for key in updates if key not in seen]
    if missing:
        lines[closing_index:closing_index] = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"\n' for key in missing]
    return "".join(lines), None


def _replace_frontmatter_scalar_blocks(lines: list[str], closing_index: int, updates: dict[str, str]) -> tuple[set[str], int]:
    seen: set[str] = set()
    index = 1
    while index < closing_index:
        match = re.match(r"^([A-Za-z0-9_-]+):(.*?)(\r?\n)?$", lines[index])
        if not match:
            index += 1
            continue
        key = match.group(1)
        if key not in updates:
            index += 1
            continue
        newline = match.group(3) or ("\n" if lines[index].endswith("\n") else "")
        end = index + 1
        while end < closing_index and _frontmatter_scalar_continuation_line(lines[end]):
            end += 1
        lines[index:end] = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"{newline}']
        closing_index -= end - index - 1
        seen.add(key)
        index += 1
    return seen, closing_index


def _frontmatter_scalar_continuation_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    return line.startswith((" ", "\t")) or stripped.startswith("- ")


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


def _frontmatter_field_present(text: str, key: str) -> bool:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        if re.match(rf"^{re.escape(key)}:\s*", line):
            return True
    return False


def _frontmatter_value_is_nonempty(value: object) -> bool:
    if value in (None, "", [], ()):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_frontmatter_value_is_nonempty(item) for item in value)
    return True


def _default_incubation_archive_rel(source_rel: str) -> str:
    source = Path(source_rel)
    return f"{ARCHIVE_INCUBATION_DIR_REL}/{date.today().isoformat()}-{source.stem}.md"


def _normalized_status(status: str | None, promoted_to: str, archive_to: str) -> str:
    normalized = str(status or "").strip().casefold().replace("_", "-")
    if normalized:
        return normalized
    if promoted_to:
        return "distilled"
    if archive_to:
        return "archived"
    return ""


def _normalized_heading(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold()).strip(" :")


def _normalized_entry_id(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().strip("`").casefold())


def _normalized_coverage_status(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _normalize_rel(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _source_route_allowed(rel_path: str) -> bool:
    return rel_path.startswith(f"{RESEARCH_DIR_REL}/") or rel_path.startswith(f"{INCUBATION_DIR_REL}/")


def _archive_route_allowed(rel_path: str) -> bool:
    return rel_path.startswith(f"{ARCHIVE_RESEARCH_DIR_REL}/") or rel_path.startswith(f"{ARCHIVE_INCUBATION_DIR_REL}/")


def _roadmap_current_posture_items(text: str) -> tuple[RoadmapCurrentPostureItem, ...]:
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,6})\s+(.+?)\s*$", line.strip())
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))

    items: list[RoadmapCurrentPostureItem] = []
    for position, (start, level, title) in enumerate(headings):
        if level not in {2, 3}:
            continue
        normalized_title = _normalized_heading(title)
        if normalized_title in {
            "archived completed history",
            "current posture",
            "future execution slice queue",
            "item schema",
            "items",
            "roadmap hygiene",
        }:
            continue
        end = len(lines)
        for next_start, next_level, _next_title in headings[position + 1 :]:
            if next_level <= level:
                end = next_start
                break
        fields = _roadmap_current_posture_fields(lines[start + 1 : end])
        item_id = _normalized_item_id(fields.get("id") or _legacy_heading_item_id(title))
        status = _normalized_status(fields.get("status"), "", "")
        if not item_id or not status:
            continue
        items.append(
            RoadmapCurrentPostureItem(
                item_id=item_id,
                status=status,
                order=str(fields.get("order") or "").strip() or "unspecified",
                title=title,
                execution_slice=_normalized_item_id(fields.get("execution_slice")) or item_id,
                detail=_roadmap_current_posture_detail(title, fields),
            )
        )
    return tuple(sorted(items, key=lambda item: (_roadmap_order_sort_key(item.order), item.item_id)))


def _roadmap_current_posture_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw in lines:
        stripped = raw.strip()
        canonical = re.match(r"^[-*]\s+`?(?P<key>[A-Za-z0-9_-]+)`?\s*:\s*(?P<value>.*?)\s*$", stripped)
        legacy = re.match(r"^(?P<key>[A-Za-z0-9_-]+)\s*:\s*(?P<value>.*?)\s*$", stripped)
        match = canonical or legacy
        if not match:
            continue
        key = match.group("key").strip().casefold().replace("-", "_")
        value = _strip_quotes(match.group("value").strip().strip("`"))
        if value.startswith("[") and value.endswith("]"):
            continue
        fields[key] = value.strip()
    return fields


def _roadmap_current_posture_detail(title: str, fields: dict[str, str]) -> str:
    detail = fields.get("slice_goal") or fields.get("carry_forward") or title
    return re.sub(r"\s+", " ", str(detail or "").replace("`", "'").strip()).rstrip(".")


def _roadmap_current_posture_body_lines(items: tuple[RoadmapCurrentPostureItem, ...], newline: str) -> list[str]:
    active = tuple(item for item in items if item.status == "active")
    accepted = tuple(item for item in items if item.status == "accepted")
    proposed = tuple(item for item in items if item.status == "proposed")
    lines = [newline]
    lines.append(
        "Current roadmap posture is derived from item metadata; this prose is advisory and cannot approve lifecycle movement."
        f"{newline}"
    )
    lines.append(newline)
    lines.append(_roadmap_current_posture_line("Active item", active, newline))
    lines.append(_roadmap_current_posture_line("Next accepted item", accepted, newline))
    lines.append(_roadmap_current_posture_line("Proposed later item", proposed, newline))
    lines.append("- Metadata source: roadmap item `status`, `order`, `execution_slice`, and `slice_goal` fields." f"{newline}")
    lines.append(newline)
    return lines


def _roadmap_current_posture_line(label: str, items: tuple[RoadmapCurrentPostureItem, ...], newline: str) -> str:
    if not items:
        return f"- {label}: none recorded.{newline}"
    first = items[0]
    if len(items) == 1:
        return f"- {label}: `{first.item_id}` (order `{first.order}`, slice `{first.execution_slice}`) - {first.detail}.{newline}"
    last = items[-1]
    return (
        f"- {label}: `{first.item_id}` (order `{first.order}`, slice `{first.execution_slice}`) "
        f"through `{last.item_id}` (order `{last.order}`, slice `{last.execution_slice}`); {len(items)} item(s) total.{newline}"
    )


def _roadmap_order_sort_key(value: str) -> tuple[int, str]:
    raw = str(value or "").strip()
    try:
        return (int(raw), raw)
    except ValueError:
        return (10**9, raw)


def _roadmap_h2_section_bounds(lines: list[str], title: str) -> tuple[int, int] | None:
    start = None
    pattern = re.compile(rf"^##\s+{re.escape(title)}\s*$")
    for index, line in enumerate(lines):
        if pattern.match(line.strip()):
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[index].strip()):
            end = index
            break
    return start, end


def _legacy_heading_item_id(title: str) -> str:
    match = re.match(r"^(RM-[0-9]+)\b", str(title or "").strip(), re.IGNORECASE)
    return match.group(1) if match else ""


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


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


def _yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _strip_quotes(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]
