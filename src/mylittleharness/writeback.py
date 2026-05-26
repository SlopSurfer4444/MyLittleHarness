from __future__ import annotations

import hashlib
import re
from datetime import date
from dataclasses import dataclass, replace
from pathlib import Path

from .atomic_files import AtomicFileDelete, AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory, Surface
from .lifecycle_focus import sync_current_focus_block
from .memory_hygiene import (
    ARCHIVE_INCUBATION_DIR_REL,
    ROADMAP_CURRENT_POSTURE_FIELD,
    RelationshipUpdatePlan,
    incubation_closeout_plan,
    incubation_entry_coverage_report,
    relationship_update_plan,
    sync_roadmap_current_posture_section,
)
from .models import Finding
from .parsing import parse_frontmatter
from .reporting import (
    RouteWriteEvidence,
    render_work_result_capsule_line,
    route_write_findings,
    work_result_capsule_from_closeout_values,
)
from .route_reference_guards import route_reference_transaction_guard_findings
from .safe_commands import mlh_command, safe_double_quoted
from .roadmap import (
    ROADMAP_STATUS_VALUES,
    TERMINAL_RELATED_PLAN_RETARGET_FIELD,
    RoadmapPlan,
    active_plan_roadmap_item_ids,
    make_roadmap_request,
    roadmap_batch_slice_gate_findings,
    roadmap_item_fields,
    roadmap_items_for_diagnostics,
    roadmap_plans_for_requests,
    roadmap_source_incubation_consumers,
    roadmap_text_with_terminal_related_plan_retargets,
)
from .vcs import product_diff_write_scope_findings


WRITEBACK_BEGIN = "<!-- BEGIN mylittleharness-closeout-writeback v1 -->"
WRITEBACK_END = "<!-- END mylittleharness-closeout-writeback v1 -->"
PHASE_WRITEBACK_BEGIN = "<!-- BEGIN mylittleharness-phase-writeback v1 -->"
PHASE_WRITEBACK_END = "<!-- END mylittleharness-phase-writeback v1 -->"
PHASE_WRITEBACK_HEADING = "mlh phase writeback"
STATE_COMPACTION_LINE_THRESHOLD = 250
STATE_COMPACTION_CHAR_THRESHOLD = 25_000

CLOSEOUT_WRITEBACK_FIELDS = (
    "worktree_start_state",
    "task_scope",
    "docs_decision",
    "state_writeback",
    "verification",
    "commit_decision",
    "residual_risk",
    "carry_forward",
    "work_result",
)
CLOSEOUT_IDENTITY_FIELDS = ("plan_id", "active_plan", "archived_plan")
LIFECYCLE_WRITEBACK_FIELDS = ("active_phase", "phase_status", "last_archived_plan", "product_source_root")
DOCS_DECISION_VALUES = {"updated", "not-needed", "uncertain"}
PHASE_STATUS_VALUES = {"pending", "active", "in_progress", "blocked", "complete", "skipped", "paused"}
UNSUCCESSFUL_ARCHIVE_ROADMAP_PHASE_STATUS = {"blocked": "blocked", "superseded": "skipped"}
ARCHIVE_COLLISION_POLICY_VALUES = {"refuse", "preserve-existing"}
PHASE_BODY_COMPLETE_STATUS = "done"
PHASE_BODY_STATUS_VALUES = {*PHASE_STATUS_VALUES, PHASE_BODY_COMPLETE_STATUS}
PHASE_HANDOFF_TERMINAL_STATUS_VALUES = {"complete", "done", "skipped"}
COMPLETED_CLOSEOUT_REQUIRED_FIELDS = ("docs_decision", "state_writeback", "verification", "commit_decision")
INCOMPLETE_CLOSEOUT_VALUES = {"", "pending", "uncertain", "unknown", "tbd", "todo"}
GENERIC_ACCEPTANCE_EVIDENCE_VALUES = {
    "complete",
    "completed",
    "done",
    "focused tests passed",
    "passed",
    "tests passed",
    "unit suite passed",
    "validation passed",
    "verification passed",
}
NON_IMPLEMENTATION_DELIVERABLE_CLASSES = {"audit", "proposal", "diagnostic", "evidence", "fan-in-review", "review", "research"}
DECLARED_EVIDENCE_TARGET_PREFIXES = (
    "project/adrs/",
    "project/decisions/",
    "project/research/",
    "project/specs/",
    "project/verification/",
)
DECLARED_TARGET_SUBSTITUTION_MARKERS = (
    "artifact substitution",
    "evidence substitution",
    "substitute artifact",
    "substitute evidence",
    "substituted artifact",
    "target substitution",
)
SCOPED_INTERRUPT_WORK_INTENT = "scoped_interrupt"
SCOPED_INTERRUPT_ROADMAP_STATUS_POLICY = "no-roadmap-status-movement-without-explicit-request"
FAN_IN_REVIEW_REQUIRED_EVIDENCE_MARKERS = (
    ("source snapshot", ("source snapshot", "source hash", "source ref", "source reference")),
    ("cluster disposition", ("cluster disposition", "disposition matrix", "disposition rationale")),
    ("missing evidence", ("missing evidence", "evidence gap", "evidence gaps")),
    ("forbidden shortcuts", ("forbidden shortcut", "forbidden shortcuts", "forbidden write", "forbidden writes")),
    ("owner route", ("owner route", "owner command", "expected owner command")),
    ("follow-up slice", ("follow up slice", "follow up slices", "followup slice", "followup slices", "next slice", "next slices")),
    (
        "no implicit product-diff acceptance",
        (
            "no implicit product diff acceptance",
            "no product diff acceptance",
            "product diff remains unaccepted",
            "dirty product diff remains unaccepted",
            "without accepting product diff",
        ),
    ),
)
DEFAULT_PLAN_REL = "project/implementation-plan.md"
DEFAULT_ARCHIVE_DIR_REL = "project/archive/plans"
DEFAULT_STATE_REL = "project/project-state.md"
DEFAULT_STATE_HISTORY_DIR_REL = "project/archive/reference"
_CLOSEOUT_BODY_SECTION_TITLES = frozenset(
    {
        "closeout",
        "closeout fields",
        "closeout facts",
        "closeout summary",
        "closeout writeback",
        "docs decision",
        "mlh closeout",
        "mlh closeout fields",
        "mlh closeout facts",
        "mlh closeout summary",
        "mlh closeout writeback",
        "state transfer",
        "state transfer facts",
        "state transfer summary",
    }
)

_FIELD_LABELS = {
    "plan_id": ("plan_id", "plan id"),
    "active_plan": ("active_plan", "active plan"),
    "archived_plan": ("archived_plan", "archived plan"),
    "worktree_start_state": ("worktree_start_state", "worktree start state"),
    "task_scope": ("task_scope", "task scope"),
    "docs_decision": ("docs_decision", "docs decision"),
    "state_writeback": ("state_writeback", "state writeback"),
    "verification": ("verification", "validation"),
    "commit_decision": ("commit_decision", "commit decision"),
    "residual_risk": ("residual_risk", "residual risk", "residual risks"),
    "carry_forward": ("carry_forward", "carry-forward", "carry forward"),
    "work_result": ("work_result", "work result", "work result capsule", "result capsule"),
}


@dataclass(frozen=True)
class WritebackFact:
    field: str
    value: str
    source: str
    line: int


@dataclass(frozen=True)
class PhaseBodyStatusFact:
    phase: str
    value: str
    source: str
    line: int


@dataclass(frozen=True)
class PhaseHandoffFact:
    field: str
    value: str
    source: str
    line: int | None = None


@dataclass(frozen=True)
class CloseoutIdentity:
    plan_id: str = ""
    active_plan: str = ""
    archived_plan: str = ""


@dataclass(frozen=True)
class CloseoutWritebackPlan:
    values: dict[str, str]
    identity: CloseoutIdentity
    decision: str
    message: str
    errors: tuple[Finding, ...] = ()


@dataclass(frozen=True)
class AcceptanceEvidenceContract:
    deliverable_class: str
    item_ids: tuple[str, ...]
    target_artifacts: tuple[str, ...]
    acceptance_terms: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class WritebackRequest:
    closeout: dict[str, str]
    lifecycle: dict[str, str]
    archive_active_plan: bool = False
    compact_only: bool = False
    allow_auto_compaction: bool = False
    source_hash: str = ""
    from_active_plan: bool = False
    roadmap_item: str = ""
    roadmap_status: str = ""
    archived_plan: str = ""
    archive_retarget_skip_rels: tuple[str, ...] = ()
    archive_collision_policy: str = "refuse"
    input_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoadmapWritebackPlan:
    target_rel: str
    target_path: Path
    item_plans: tuple[RoadmapPlan, ...]

    @property
    def current_text(self) -> str:
        return self.item_plans[0].current_text if self.item_plans else ""

    @property
    def updated_text(self) -> str:
        return self.item_plans[-1].updated_text if self.item_plans else ""

    @property
    def item_ids(self) -> tuple[str, ...]:
        return tuple(plan.item_id for plan in self.item_plans)


@dataclass(frozen=True)
class ArchivedPlanRefreshPlan:
    surface: Surface
    updated_text: str
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class RouteRetargetPlan:
    source_rel: str
    target_path: Path
    current_text: str
    updated_text: str
    changed_fields: tuple[str, ...]


@dataclass(frozen=True)
class PhaseBlockSpan:
    active_phase: str
    start_index: int
    end_index: int


@dataclass(frozen=True)
class BodySectionSpan:
    start_index: int
    end_index: int


def make_writeback_request(
    archive_active_plan: bool = False,
    compact_only: bool = False,
    allow_auto_compaction: bool = False,
    source_hash: str | None = None,
    from_active_plan: bool = False,
    roadmap_item: str | None = None,
    roadmap_status: str | None = None,
    archived_plan: str | None = None,
    archive_retarget_skip_rels: tuple[str, ...] | list[str] = (),
    archive_collision_policy: str | None = None,
    **values: str | None,
) -> WritebackRequest:
    input_errors = tuple(_text_field_input_errors(values))
    closeout = {
        field: _normalized_value(values.get(field))
        for field in CLOSEOUT_WRITEBACK_FIELDS
        if _normalized_value(values.get(field))
    }
    lifecycle = {
        field: _normalized_value(values.get(field))
        for field in LIFECYCLE_WRITEBACK_FIELDS
        if _normalized_value(values.get(field))
    }
    return WritebackRequest(
        closeout=closeout,
        lifecycle=lifecycle,
        archive_active_plan=archive_active_plan,
        compact_only=compact_only,
        allow_auto_compaction=allow_auto_compaction,
        source_hash=str(source_hash or "").strip().casefold(),
        from_active_plan=from_active_plan,
        roadmap_item=_normalized_item_id(roadmap_item),
        roadmap_status=_normalized_status(roadmap_status),
        archived_plan=_normalize_rel(_normalized_value(archived_plan)),
        archive_retarget_skip_rels=tuple(_dedupe_nonempty(_normalize_rel(rel) for rel in archive_retarget_skip_rels)),
        archive_collision_policy=_normalized_archive_collision_policy(archive_collision_policy),
        input_errors=input_errors,
    )


def canonical_phase_body_status(phase_status: str) -> str:
    return PHASE_BODY_COMPLETE_STATUS if phase_status == "complete" else phase_status


def closeout_values_are_complete(values: dict[str, str]) -> bool:
    docs_decision = values.get("docs_decision", "")
    if docs_decision not in {"updated", "not-needed"}:
        return False
    for field in COMPLETED_CLOSEOUT_REQUIRED_FIELDS:
        if not _closeout_value_is_complete(values.get(field, "")):
            return False
    return True


def missing_complete_closeout_fields(values: dict[str, str]) -> tuple[str, ...]:
    missing: list[str] = []
    docs_decision = values.get("docs_decision", "")
    if docs_decision not in {"updated", "not-needed"}:
        missing.append("docs_decision")
    for field in COMPLETED_CLOSEOUT_REQUIRED_FIELDS:
        if field == "docs_decision":
            continue
        if not _closeout_value_is_complete(values.get(field, "")):
            missing.append(field)
    return tuple(missing)


def state_writeback_facts(state: Surface | None) -> dict[str, WritebackFact]:
    return _state_writeback_block_facts(state, CLOSEOUT_WRITEBACK_FIELDS)


def state_writeback_identity_facts(state: Surface | None) -> dict[str, WritebackFact]:
    return _state_writeback_block_facts(state, CLOSEOUT_IDENTITY_FIELDS)


def _state_writeback_block_facts(state: Surface | None, allowed_fields: tuple[str, ...]) -> dict[str, WritebackFact]:
    if state is None or not state.exists:
        return {}
    lines = state.content.splitlines()
    ranges: list[tuple[int, int]] = []
    begin: int | None = None
    for index, line in enumerate(lines, start=1):
        if line.strip() == WRITEBACK_BEGIN:
            begin = index
            continue
        if line.strip() == WRITEBACK_END and begin is not None:
            ranges.append((begin, index))
            begin = None
    if not ranges:
        return {}

    start, end = ranges[-1]
    allowed = set(allowed_fields)
    facts: dict[str, WritebackFact] = {}
    for line_number in range(start + 1, end):
        field, value = _field_line_value(lines[line_number - 1])
        if field and field in allowed and value:
            facts[field] = WritebackFact(field=field, value=value, source=state.rel_path, line=line_number)
    return facts


def active_plan_body_facts(plan: Surface | None) -> dict[str, WritebackFact]:
    if plan is None or not plan.exists:
        return {}
    lines = plan.content.splitlines()
    facts: dict[str, WritebackFact] = {}
    for index in _closeout_body_field_line_indexes(plan.content):
        line_number = index + 1
        line = lines[index]
        field, value = _field_line_value(line)
        if field and field in CLOSEOUT_WRITEBACK_FIELDS and value:
            facts.setdefault(field, WritebackFact(field=field, value=value, source=plan.rel_path, line=line_number))
    return facts


def active_plan_phase_body_status_fact(plan: Surface | None, active_phase: str) -> WritebackFact | None:
    if plan is None or not plan.exists or not active_phase:
        return None
    block = _find_phase_block(plan.content, active_phase)
    if block is None:
        return None
    lines = plan.content.splitlines(keepends=True)
    status_index = _phase_status_line_index(lines, block)
    if status_index is None:
        return None
    status = _phase_status_line_value(lines[status_index])
    if not status:
        return None
    return WritebackFact(field="phase_status", value=status, source=plan.rel_path, line=status_index + 1)


def active_plan_preceding_phase_body_status_facts(plan: Surface | None, active_phase: str) -> tuple[PhaseBodyStatusFact, ...]:
    if plan is None or not plan.exists or not active_phase:
        return ()
    lines = plan.content.splitlines(keepends=True)
    blocks = _phase_blocks_from_lines(lines)
    active_index = _phase_block_index(lines, blocks, active_phase)
    if active_index is None:
        return ()
    facts: list[PhaseBodyStatusFact] = []
    for block, title in blocks[:active_index]:
        status_index = _phase_status_line_index(lines, block)
        if status_index is None:
            continue
        status = _phase_status_line_value(lines[status_index])
        if not status:
            continue
        facts.append(
            PhaseBodyStatusFact(
                phase=_phase_block_label(lines, block, title),
                value=status,
                source=plan.rel_path,
                line=status_index + 1,
            )
        )
    return tuple(facts)


def active_plan_completed_phase_handoff_facts(inventory: Inventory) -> tuple[PhaseHandoffFact, ...]:
    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    if state_data.get("plan_status") != "active":
        return ()
    if str(state_data.get("phase_status") or "") != "pending":
        return ()
    active_phase = str(state_data.get("active_phase") or "")
    plan = inventory.active_plan_surface
    if not active_phase or plan is None or not plan.exists:
        return ()

    facts: list[PhaseHandoffFact] = []
    body_fact = active_plan_phase_body_status_fact(plan, active_phase)
    if body_fact and _is_phase_handoff_terminal_status(body_fact.value):
        facts.append(
            PhaseHandoffFact(
                field=f"phase block {active_phase} status",
                value=body_fact.value,
                source=body_fact.source,
                line=body_fact.line,
            )
        )

    if plan.frontmatter.has_frontmatter:
        for field in ("phase_status", "status"):
            value = str(plan.frontmatter.data.get(field) or "")
            if _is_phase_handoff_terminal_status(value):
                facts.append(PhaseHandoffFact(field=f"frontmatter {field}", value=value, source=plan.rel_path))
    return tuple(facts)


def active_plan_completed_phase_handoff_findings(
    inventory: Inventory,
    *,
    code: str = "active-plan-completed-phase-handoff",
    requested_phase_status: str = "",
) -> list[Finding]:
    facts = active_plan_completed_phase_handoff_facts(inventory)
    if not facts:
        return []

    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    active_phase = str(state_data.get("active_phase") or "")
    fact_summary = "; ".join(f"{fact.field}={fact.value!r}" for fact in facts)
    if requested_phase_status == "complete":
        severity = "info"
        action = (
            "the requested phase_status complete is the reviewed lifecycle synchronization path for that handoff evidence"
        )
    else:
        severity = "warn"
        action = (
            "review verification evidence, then run writeback --apply --phase-status complete to synchronize lifecycle, "
            "or restore the derived active-plan copy if the phase is still pending"
        )
    first_fact = facts[0]
    return [
        Finding(
            severity,
            code,
            (
                f"project-state active_phase is {active_phase!r} with phase_status 'pending', but repo-visible active-plan "
                f"handoff evidence records {fact_summary}; {action}; this does not treat chat handoff text as authority "
                "and does not approve closeout, archive, roadmap done-status, next-plan opening, staging, or commit"
            ),
            first_fact.source,
            first_fact.line,
        )
    ]


def _phase_closeout_handoff_sequence_findings(request: WritebackRequest, findings: list[Finding]) -> list[Finding]:
    if not _needs_phase_closeout_handoff_sequence(request, findings):
        return []
    roadmap_item = request.roadmap_item or "<id>"
    return [
        Finding(
            "info",
            "writeback-phase-closeout-handoff-sequence",
            (
                "phase evidence handoff and archive closeout replacement can be reviewed as a composed two-step sequence: "
                "`mylittleharness --root <root> writeback --dry-run --phase-status complete --docs-decision uncertain`, "
                "then after review `mylittleharness --root <root> writeback --dry-run --archive-active-plan "
                f"--roadmap-item {roadmap_item} --roadmap-status done --docs-decision <updated|not-needed> "
                "--state-writeback \"<text>\" --verification \"<text>\" --commit-decision \"<text>\"`; archive-active-plan owns "
                "plan_status, active_plan, and last_archived_plan lifecycle pointers, so omit explicit --active-phase "
                "and --last-archived-plan from the archive command. This advice is read-only and does not approve "
                "archive, roadmap done-status, staging, commit, rollback, or next-plan opening"
            ),
            DEFAULT_PLAN_REL,
        )
    ]


def _needs_phase_closeout_handoff_sequence(request: WritebackRequest, findings: list[Finding]) -> bool:
    if request.archive_active_plan and any(field in request.lifecycle for field in ("active_phase", "last_archived_plan")):
        return True
    if request.archive_active_plan and any("archive-active-plan requires phase_status complete" in finding.message for finding in findings):
        return True
    if request.lifecycle.get("phase_status") == "complete" and request.closeout:
        return any(finding.code == "writeback-closeout-identity-refused" for finding in findings)
    return False


def writeback_dry_run_findings(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    findings = [
        Finding("info", "writeback-dry-run", "writeback proposal only; no files were written"),
        Finding(
            "info",
            "writeback-boundary",
            "writeback --apply is the explicit MLH-owned closeout/state writeback path; read-only reports remain no-write",
        ),
    ]
    request, harvest_findings, harvest_errors = _writeback_request_with_active_plan_facts(inventory, request, apply=False)
    findings.extend(harvest_findings)
    findings.extend(
        active_plan_completed_phase_handoff_findings(
            inventory,
            code="writeback-completed-phase-handoff-sync",
            requested_phase_status=request.lifecycle.get("phase_status", ""),
        )
    )
    errors = _writeback_preflight_errors(inventory, request)
    errors.extend(harvest_errors)
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.extend(_phase_closeout_handoff_sequence_findings(request, errors))
        findings.append(
            Finding(
                "info",
                "writeback-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run and check before relying on lifecycle close",
            )
        )
        return findings

    if request.compact_only:
        findings.append(
            Finding(
                "info",
                "writeback-compact-only",
                "compact-only proposal checks safe project-state history archival without changing closeout fields, lifecycle frontmatter, or active-plan copies",
                DEFAULT_STATE_REL,
            )
        )
        findings.extend(state_compaction_dry_run_findings(inventory))
        findings.append(
            Finding(
                "info",
                "writeback-validation-posture",
                "dry-run writes no files; after compact-only apply, run check to verify compact operating memory and archive/reference pointer posture",
            )
        )
        return findings

    archive_plan = _archive_plan(inventory, request)
    archive_context_rel = archive_plan.archive_rel_path if archive_plan else request.archived_plan or None
    closeout_plan = _closeout_writeback_plan(inventory, request, archive_context_rel)
    planned = closeout_plan.values
    findings.append(_planned_closeout_finding(planned))
    findings.extend(_closeout_writeback_plan_findings(closeout_plan, apply=False))
    findings.extend(_scoped_interrupt_writeback_boundary_findings(inventory, request, apply=False))
    completion_reason = _writeback_acceptance_completion_reason(inventory, request, planned)
    findings.extend(
        acceptance_evidence_findings(
            inventory,
            planned,
            completion_reason=completion_reason,
            apply=False,
            code_prefix="writeback",
            include_success=True,
        )
    )
    findings.extend(
        product_diff_write_scope_findings(
            inventory,
            planned,
            completion_reason=completion_reason,
            apply=False,
            code_prefix="writeback",
        )
    )
    planned_lifecycle = _planned_lifecycle_values(
        request,
        archive_plan.archive_rel_path if archive_plan else None,
        _archive_phase_status(inventory, request) if archive_plan else "",
    )
    active_plan_lifecycle = _active_plan_lifecycle_values(inventory, request, planned_lifecycle)
    roadmap_plan, roadmap_errors = _writeback_roadmap_plan(inventory, request, archive_context_rel)
    if roadmap_errors:
        findings.extend(_with_severity(roadmap_errors, "warn"))
        findings.append(
            Finding(
                "info",
                "writeback-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run and check before relying on lifecycle close",
            )
        )
        return findings
    findings.extend(_writeback_batch_slice_gate_findings(inventory, request, apply=False))
    incubation_plan, incubation_errors = _writeback_incubation_plan(inventory, request, archive_context_rel)
    if incubation_errors:
        findings.extend(_with_severity(incubation_errors, "warn"))
        findings.append(
            Finding(
                "info",
                "writeback-validation-posture",
                "dry-run refused before apply; fix relationship writeback refusal reasons, then rerun dry-run and check before relying on lifecycle close",
            )
        )
        return findings
    route_retarget_plans = _archive_route_retarget_plans(
        inventory,
        archive_context_rel if archive_plan else "",
        skip_rels=(*_incubation_plan_source_rels(incubation_plan), *request.archive_retarget_skip_rels),
    )
    projected_state_text = _state_text_with_writeback(inventory.state.content, planned, planned_lifecycle, closeout_plan.identity) if inventory.state else ""
    projected_active_plan_text = _projected_active_plan_text(
        inventory,
        planned,
        active_plan_lifecycle,
        completed_phase="" if archive_plan else _phase_advancement_completed_phase(inventory, active_plan_lifecycle),
    )
    archive_capsule_findings: list[Finding] = []
    if archive_plan and projected_active_plan_text is not None:
        projected_active_plan_text, archive_capsule_findings = _archive_plan_text_with_closeout_evidence_capsule(
            projected_active_plan_text,
            planned,
            closeout_plan.identity,
            archive_plan.archive_rel_path,
            apply=False,
        )
    archived_refresh_plan = _archived_plan_refresh_plan(inventory, request, planned, closeout_plan.identity, apply=False)
    projected_state_text, projected_active_plan_text, roadmap_plan, route_retarget_plans = _with_incubation_archive_replacements(
        projected_state_text,
        projected_active_plan_text,
        roadmap_plan,
        route_retarget_plans,
        incubation_plan,
    )
    incubation_plan = _relationship_plan_without_subsumed_link_repairs(
        incubation_plan,
        _writeback_subsumed_link_repair_rels(
            inventory,
            projected_active_plan_text,
            roadmap_plan,
            route_retarget_plans,
            archive_plan,
            archived_refresh_plan,
        ),
    )
    if archive_plan:
        findings.extend(_archive_plan_findings(inventory, archive_plan, apply=False))
    if planned_lifecycle:
        findings.append(
            Finding(
                "info",
                "writeback-lifecycle-plan",
                f"would update project-state lifecycle frontmatter: {', '.join(planned_lifecycle)}",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        findings.append(_phase_execution_boundary_finding(planned_lifecycle, inventory.state.rel_path if inventory.state else None, apply=False))
        advancement_finding = _phase_advancement_finding(inventory, planned_lifecycle, inventory.state.rel_path if inventory.state else None, apply=False)
        if advancement_finding:
            findings.append(advancement_finding)
        ready_finding = _ready_for_closeout_boundary_finding(planned_lifecycle, inventory.state.rel_path if inventory.state else None, apply=False)
        if ready_finding:
            findings.append(ready_finding)
    findings.extend(_phase_writeback_tail_retirement_findings(inventory, projected_state_text, apply=False))
    compaction_plan = _state_compaction_plan(inventory, projected_state_text) if inventory.state else None
    if compaction_plan:
        findings.extend(_state_compaction_findings(compaction_plan, apply=False))
        boundary_findings = _auto_compaction_boundary_findings(request, planned_lifecycle, compaction_plan, apply=False)
        findings.extend(boundary_findings)
        if any(finding.severity == "warn" for finding in boundary_findings):
            findings.append(
                Finding(
                    "info",
                    "writeback-validation-posture",
                    "dry-run found lifecycle writeback would cross the project-state auto-compaction boundary; rerun with --allow-auto-compaction or run writeback --compact-only separately before apply",
                    DEFAULT_STATE_REL,
                )
            )
            return findings
    findings.extend(
        _writeback_route_write_findings(
            inventory,
            projected_state_text,
            projected_active_plan_text,
            roadmap_plan,
            incubation_plan,
            route_retarget_plans,
            archive_plan,
            projected_active_plan_text if archive_plan else None,
            archived_refresh_plan,
            apply=False,
        )
    )
    findings.extend(_active_plan_sync_plan_findings(inventory, planned, active_plan_lifecycle, apply=False))
    findings.extend(archive_capsule_findings)
    if archived_refresh_plan:
        findings.extend(archived_refresh_plan.findings)
    if roadmap_plan:
        findings.extend(_writeback_roadmap_findings(roadmap_plan, apply=False))
    if incubation_plan:
        findings.extend(_writeback_incubation_findings(incubation_plan, apply=False))
    if route_retarget_plans:
        findings.extend(_archive_route_retarget_findings(route_retarget_plans, apply=False))
    if archive_plan:
        findings.extend(_post_archive_verification_posture_findings(inventory, apply=False))
    findings.append(
        Finding(
            "info",
            "writeback-validation-posture",
            "after apply, run check to verify lifecycle state and stale-plan-file posture; dry-run writes no files",
        )
    )
    return findings


def writeback_apply_findings(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    request, harvest_findings, harvest_errors = _writeback_request_with_active_plan_facts(inventory, request, apply=True)
    if harvest_errors:
        return harvest_errors
    errors = _writeback_preflight_errors(inventory, request)
    if errors:
        return [*errors, *_phase_closeout_handoff_sequence_findings(request, errors)]

    if request.compact_only:
        findings = [
            Finding("info", "writeback-apply", "compact-only writeback apply started"),
            Finding(
                "info",
                "writeback-compact-only",
                "compact-only apply may write only project/project-state.md and a project/archive/reference state-history archive",
                DEFAULT_STATE_REL,
            ),
        ]
        findings.extend(state_compaction_apply_findings(inventory, expected_source_hash=request.source_hash, require_source_hash=True))
        return findings

    if _should_archive_active_plan(inventory, request):
        archive_findings = _writeback_archive_apply_findings(inventory, request)
        if harvest_findings and not any(finding.severity == "error" for finding in archive_findings):
            return [*harvest_findings, *archive_findings]
        return archive_findings

    state = inventory.state
    assert state is not None
    archive_context_rel = request.archived_plan or None
    closeout_plan = _closeout_writeback_plan(inventory, request, archive_context_rel)
    planned = closeout_plan.values
    roadmap_plan, roadmap_errors = _writeback_roadmap_plan(inventory, request, archive_context_rel)
    if roadmap_errors:
        return roadmap_errors
    batch_gate_findings = _writeback_batch_slice_gate_findings(inventory, request, apply=True)
    incubation_plan, incubation_errors = _writeback_incubation_plan(inventory, request, archive_context_rel)
    if incubation_errors:
        return incubation_errors
    state_text = _state_text_with_writeback(state.content, planned, request.lifecycle, closeout_plan.identity)
    compaction_plan = _state_compaction_plan(inventory, state_text)
    boundary_findings = _auto_compaction_boundary_findings(request, request.lifecycle, compaction_plan, apply=True)
    if any(finding.severity == "error" for finding in boundary_findings):
        return [
            *boundary_findings,
            *_state_compaction_findings(compaction_plan, apply=False),
            Finding(
                "info",
                "writeback-validation-posture",
                "writeback apply refused before writing files; review --allow-auto-compaction or run writeback --compact-only as a separate lifecycle decision",
                DEFAULT_STATE_REL,
            ),
        ]
    plan_changes: tuple[Surface, str, list[Finding]] | None = None
    if inventory.active_plan_surface and inventory.active_plan_surface.exists:
        plan = inventory.active_plan_surface
        plan_text, sync_findings = _active_plan_text_with_synced_values(
            plan,
            planned,
            request.lifecycle,
            _requested_or_current_active_phase(inventory, request.lifecycle),
            _phase_advancement_completed_phase(inventory, request.lifecycle),
        )
        plan_changes = (plan, plan_text, sync_findings)
    else:
        sync_findings = [
            Finding("info", "writeback-active-plan-skipped", "no readable active plan exists; only project-state writeback is planned")
        ]
    archived_refresh_plan = _archived_plan_refresh_plan(inventory, request, planned, closeout_plan.identity, apply=True)
    state_tmp = state.path.with_name(f".{state.path.name}.writeback.tmp") if state_text != state.content else None
    state_backup = state.path.with_name(f".{state.path.name}.writeback.backup") if state_tmp else None
    plan_tmp = (
        plan_changes[0].path.with_name(f".{plan_changes[0].path.name}.writeback.tmp")
        if plan_changes and plan_changes[1] != plan_changes[0].content
        else None
    )
    plan_backup = (
        plan_changes[0].path.with_name(f".{plan_changes[0].path.name}.writeback.backup")
        if plan_tmp and plan_changes
        else None
    )
    archived_refresh_tmp = (
        archived_refresh_plan.surface.path.with_name(f".{archived_refresh_plan.surface.path.name}.writeback.tmp")
        if archived_refresh_plan and archived_refresh_plan.updated_text != archived_refresh_plan.surface.content
        else None
    )
    archived_refresh_backup = (
        archived_refresh_plan.surface.path.with_name(f".{archived_refresh_plan.surface.path.name}.writeback.backup")
        if archived_refresh_tmp and archived_refresh_plan
        else None
    )
    roadmap_tmp = _roadmap_writeback_tmp(roadmap_plan)
    roadmap_backup = _roadmap_writeback_backup(roadmap_plan) if roadmap_tmp else None
    incubation_tmp = _incubation_writeback_tmp(incubation_plan)
    incubation_backup = _incubation_writeback_backup(incubation_plan) if incubation_tmp else None
    for candidate, label in (
        (state_tmp, "temporary state write path"),
        (state_backup, "temporary state backup path"),
        (plan_tmp, "temporary active-plan write path"),
        (plan_backup, "temporary active-plan backup path"),
        (archived_refresh_tmp, "temporary archived-plan refresh write path"),
        (archived_refresh_backup, "temporary archived-plan refresh backup path"),
        (roadmap_tmp, "temporary roadmap write path"),
        (roadmap_backup, "temporary roadmap backup path"),
        (incubation_tmp, "temporary incubation relationship write path"),
        (incubation_backup, "temporary incubation relationship backup path"),
    ):
        if candidate and candidate.exists():
            return [Finding("error", "writeback-refused", f"{label} already exists: {candidate.relative_to(inventory.root).as_posix()}")]

    findings: list[Finding] = [
        Finding("info", "writeback-apply", "closeout/state writeback apply started"),
        _planned_closeout_finding(planned),
    ]
    findings.extend(harvest_findings)
    findings.extend(batch_gate_findings)
    findings.extend(
        active_plan_completed_phase_handoff_findings(
            inventory,
            code="writeback-completed-phase-handoff-sync",
            requested_phase_status=request.lifecycle.get("phase_status", ""),
        )
    )
    findings.extend(_closeout_writeback_plan_findings(closeout_plan, apply=True))
    findings.extend(_scoped_interrupt_writeback_boundary_findings(inventory, request, apply=True))
    completion_reason = _writeback_acceptance_completion_reason(inventory, request, planned)
    findings.extend(
        acceptance_evidence_findings(
            inventory,
            planned,
            completion_reason=completion_reason,
            apply=True,
            code_prefix="writeback",
            include_success=True,
        )
    )
    findings.extend(
        product_diff_write_scope_findings(
            inventory,
            planned,
            completion_reason=completion_reason,
            apply=True,
            code_prefix="writeback",
        )
    )
    if request.lifecycle:
        findings.append(
            Finding(
                "info",
                "writeback-lifecycle-updated",
                f"updated project-state lifecycle frontmatter: {', '.join(request.lifecycle)}",
                state.rel_path,
            )
        )
        findings.append(_phase_execution_boundary_finding(request.lifecycle, state.rel_path, apply=True))
        advancement_finding = _phase_advancement_finding(inventory, request.lifecycle, state.rel_path, apply=True)
        if advancement_finding:
            findings.append(advancement_finding)
        ready_finding = _ready_for_closeout_boundary_finding(request.lifecycle, state.rel_path, apply=True)
        if ready_finding:
            findings.append(ready_finding)
        findings.extend(_auto_compaction_boundary_findings(request, request.lifecycle, compaction_plan, apply=True))

    operations: list[AtomicFileWrite] = []
    if state_tmp and state_backup:
        operations.append(AtomicFileWrite(state.path, state_tmp, state_text, state_backup))
    if plan_tmp and plan_backup and plan_changes:
        operations.append(AtomicFileWrite(plan_changes[0].path, plan_tmp, plan_changes[1], plan_backup))
    if archived_refresh_tmp and archived_refresh_backup and archived_refresh_plan:
        operations.append(
            AtomicFileWrite(
                archived_refresh_plan.surface.path,
                archived_refresh_tmp,
                archived_refresh_plan.updated_text,
                archived_refresh_backup,
            )
        )
    if roadmap_tmp and roadmap_backup and roadmap_plan:
        operations.append(AtomicFileWrite(roadmap_plan.target_path, roadmap_tmp, roadmap_plan.updated_text, roadmap_backup))
    if incubation_tmp and incubation_backup and incubation_plan:
        operations.append(AtomicFileWrite(incubation_plan.target_path, incubation_tmp, incubation_plan.updated_text, incubation_backup))
    route_writes = _writeback_route_write_evidence(
        inventory,
        state_text,
        plan_changes[1] if plan_changes else None,
        roadmap_plan,
        incubation_plan,
        (),
        None,
        None,
        archived_refresh_plan,
    )
    guard_findings = route_reference_transaction_guard_findings(inventory, route_writes, apply=True)
    if any(finding.severity == "error" for finding in guard_findings):
        return [
            *guard_findings,
            Finding(
                "info",
                "writeback-validation-posture",
                "writeback apply refused before writing files; review unresolved required route references, then rerun dry-run",
                state.rel_path,
            ),
        ]
    route_write_evidence = route_write_findings("writeback-route-write", route_writes, apply=True)
    if operations:
        try:
            cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
        except FileTransactionError as exc:
            return [Finding("error", "writeback-refused", f"writeback failed before all target files were written: {exc}")]
    else:
        cleanup_warnings = ()

    if planned and state_text != state.content:
        findings.append(
            Finding(
                "info",
                "writeback-state-updated",
                "wrote MLH-owned closeout writeback block in project/project-state.md",
                state.rel_path,
            )
        )
    elif request.lifecycle and state_text != state.content:
        findings.append(
            Finding(
                "info",
                "writeback-state-updated",
                "updated project-state lifecycle frontmatter and Current Focus managed block without adding a closeout writeback block",
                state.rel_path,
            )
        )
    elif request.archived_plan and not _route_writes_have_changes(route_writes):
        findings.append(_archived_plan_already_closed_finding(request.archived_plan, apply=True))
    if plan_changes:
        findings.extend(plan_changes[2])
    else:
        findings.extend(sync_findings)
    if archived_refresh_plan:
        findings.extend(archived_refresh_plan.findings)
    findings.extend(route_write_evidence)
    findings.extend(guard_findings)
    if roadmap_plan:
        findings.extend(_writeback_roadmap_findings(roadmap_plan, apply=True))
    if incubation_plan:
        findings.extend(_writeback_incubation_findings(incubation_plan, apply=True))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "writeback-backup-cleanup", warning, state.rel_path))
    findings.append(
        Finding(
            "info",
            "writeback-authority",
            "project-state frontmatter remains lifecycle authority; the MLH closeout writeback block is current closeout fact authority; active-plan frontmatter/body copies are synchronized derived metadata when present",
            state.rel_path,
        )
    )
    if state_text != state.content:
        compaction_plan = _state_compaction_plan(inventory, state.path.read_text(encoding="utf-8"))
        findings.extend(_apply_state_compaction(inventory, compaction_plan))
    return findings


def _writeback_preflight_errors(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    errors: list[Finding] = []
    for error in request.input_errors:
        errors.append(Finding("error", "writeback-refused", error))
    if request.from_active_plan and request.compact_only:
        errors.append(Finding("error", "writeback-refused", "--from-active-plan cannot be combined with --compact-only"))
    if request.compact_only and request.allow_auto_compaction:
        errors.append(Finding("error", "writeback-refused", "--allow-auto-compaction cannot be combined with --compact-only; compact-only is already the explicit compaction rail"))
    if request.compact_only and (request.closeout or request.lifecycle or request.archive_active_plan or request.roadmap_item or request.roadmap_status or request.archived_plan):
        errors.append(Finding("error", "writeback-refused", "--compact-only cannot be combined with closeout fields, lifecycle fields, --archive-active-plan, --archived-plan, or roadmap sync fields"))
    if request.source_hash and not request.compact_only:
        errors.append(Finding("error", "writeback-refused", "--source-hash is valid only with --compact-only"))
    if request.source_hash and not re.fullmatch(r"[0-9a-f]{64}", request.source_hash):
        errors.append(Finding("error", "writeback-refused", "--source-hash must be a full lowercase sha256 hex digest from compact-only dry-run"))
    if not request.closeout and not request.lifecycle and not request.archive_active_plan and not request.compact_only and not request.archived_plan:
        errors.append(Finding("error", "writeback-refused", "writeback requires at least one closeout or lifecycle field"))
    if request.roadmap_status and not request.roadmap_item:
        errors.append(Finding("error", "writeback-refused", "--roadmap-status requires --roadmap-item"))
    if request.archived_plan and request.archive_active_plan:
        errors.append(Finding("error", "writeback-refused", "--archived-plan cannot be combined with --archive-active-plan; one command either archives the active plan or refreshes an already archived plan"))
    if request.archived_plan:
        errors.extend(_archived_plan_request_errors(inventory, request.archived_plan))
        if not request.roadmap_item:
            errors.extend(_archived_plan_identity_boundary_errors(inventory, request.archived_plan))
    if request.roadmap_status and request.roadmap_status not in ROADMAP_STATUS_VALUES:
        errors.append(Finding("error", "writeback-refused", f"--roadmap-status must be one of: {', '.join(sorted(ROADMAP_STATUS_VALUES))}"))
    if request.archive_active_plan and any(field in request.lifecycle for field in ("active_phase", "last_archived_plan")):
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                "--archive-active-plan owns plan_status, active_plan, and last_archived_plan lifecycle updates; do not combine it with explicit active_phase or last_archived_plan fields",
            )
        )
    if request.archive_active_plan and request.lifecycle.get("phase_status") and request.lifecycle.get("phase_status") != "complete":
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                "--archive-active-plan may combine with --phase-status complete to atomically complete and archive the current plan; other explicit phase_status values are refused",
            )
        )
    docs_decision = request.closeout.get("docs_decision")
    if docs_decision and docs_decision not in DOCS_DECISION_VALUES:
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                f"docs_decision is {docs_decision!r}; expected one of: not-needed, uncertain, updated",
            )
        )
    phase_status = request.lifecycle.get("phase_status")
    if phase_status and phase_status not in PHASE_STATUS_VALUES:
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                f"phase_status is {phase_status!r}; expected one of: active, blocked, complete, in_progress, paused, pending, skipped",
            )
        )
    product_source_root = request.lifecycle.get("product_source_root")
    if product_source_root:
        errors.extend(_product_source_root_errors(inventory, product_source_root))
    errors.extend(_writeback_root_state_preflight_errors(inventory))
    if request.compact_only:
        return errors
    closeout_plan = _closeout_writeback_plan(inventory, request, request.archived_plan or None)
    errors.extend(closeout_plan.errors)
    completion_reason = _writeback_acceptance_completion_reason(inventory, request, closeout_plan.values)
    errors.extend(
        acceptance_evidence_findings(
            inventory,
            closeout_plan.values,
            completion_reason=completion_reason,
            apply=True,
            code_prefix="writeback",
        )
    )
    product_diff_preflight = product_diff_write_scope_findings(
        inventory,
        closeout_plan.values,
        completion_reason=completion_reason,
        apply=True,
        code_prefix="writeback",
        preflight=True,
    )
    errors.extend(finding for finding in product_diff_preflight if finding.severity == "error")

    plan = inventory.active_plan_surface
    if plan and plan.exists:
        if not plan.path.is_file():
            errors.append(Finding("error", "writeback-refused", "active plan is not a regular file", plan.rel_path))
        elif plan.path.is_symlink():
            errors.append(Finding("error", "writeback-refused", "active plan is a symlink; archive apply is refused", plan.rel_path))
        elif plan.frontmatter.has_frontmatter and plan.frontmatter.errors:
            errors.append(Finding("error", "writeback-refused", "active plan frontmatter is malformed", plan.rel_path))
    if request.archive_active_plan:
        errors.extend(_archive_preflight_errors(inventory, request))
    return errors


def _writeback_request_with_active_plan_facts(
    inventory: Inventory,
    request: WritebackRequest,
    apply: bool,
) -> tuple[WritebackRequest, list[Finding], list[Finding]]:
    if not request.from_active_plan:
        return request, [], []
    plan = inventory.active_plan_surface
    source = plan.rel_path if plan else DEFAULT_PLAN_REL
    if plan is None or not plan.exists:
        return request, [], [
            Finding("error", "writeback-refused", "--from-active-plan requires a readable active plan", DEFAULT_PLAN_REL)
        ]
    facts = active_plan_body_facts(plan)
    active_plan_values = {field: fact.value for field, fact in facts.items()}
    state_fallback = False
    finding_source = source
    candidate = dict(active_plan_values)
    candidate.update(request.closeout)
    if active_plan_values and closeout_values_are_complete(candidate):
        harvested = active_plan_values
    else:
        harvested, fallback_errors = _state_closeout_authority_facts(inventory)
        if fallback_errors:
            if active_plan_values:
                missing = ", ".join(missing_complete_closeout_fields(candidate))
                return request, [], [
                    Finding(
                        "error",
                        "writeback-refused",
                        (
                            "--from-active-plan found incomplete active-plan closeout facts; "
                            f"missing fields: {missing or '<none>'}; no complete matching project-state closeout authority was available"
                        ),
                        source,
                    ),
                    *fallback_errors,
                ]
            return request, [], fallback_errors
        state_fallback = True
        finding_source = inventory.state.rel_path if inventory.state else DEFAULT_STATE_REL
    merged = dict(harvested)
    if state_fallback and active_plan_values:
        merged.update(active_plan_values)
    merged.update(request.closeout)
    fields = ", ".join(field for field in CLOSEOUT_WRITEBACK_FIELDS if field in harvested)
    override_fields = ", ".join(field for field in CLOSEOUT_WRITEBACK_FIELDS if field in request.closeout and field in harvested)
    verb = "harvested" if apply else "would harvest"
    origin = "project-state closeout authority" if state_fallback else "active plan"
    message = f"{verb} closeout facts from {origin}: {fields}"
    if override_fields:
        message += f"; same-request fields override harvested values: {override_fields}"
    findings = []
    if state_fallback and active_plan_values:
        missing = ", ".join(missing_complete_closeout_fields(candidate))
        active_fields = ", ".join(field for field in CLOSEOUT_WRITEBACK_FIELDS if field in active_plan_values)
        findings.append(
            Finding(
                "info",
                "writeback-from-active-plan-incomplete",
                (
                    "active-plan closeout facts were incomplete "
                    f"(fields: {active_fields or '<none>'}; missing: {missing or '<none>'}); "
                    "using project-state closeout authority fallback"
                ),
                source,
            )
        )
        override_fields = ", ".join(field for field in CLOSEOUT_WRITEBACK_FIELDS if field in active_plan_values and field in harvested)
        if override_fields:
            findings.append(
                Finding(
                    "info",
                    "writeback-from-active-plan-partial-overrides",
                    (
                        "active-plan partial closeout facts override matching project-state fallback facts: "
                        f"{override_fields}; project-state supplies only missing fallback fields"
                    ),
                    source,
                )
            )
    findings.append(Finding("info", "writeback-from-active-plan", message, finding_source))
    return (
        replace(request, closeout=_ordered_closeout_values(merged)),
        findings,
        [],
    )


def _state_closeout_authority_facts(inventory: Inventory) -> tuple[dict[str, str], list[Finding]]:
    facts = state_writeback_facts(inventory.state)
    harvested = {field: fact.value for field, fact in facts.items()}
    source = inventory.state.rel_path if inventory.state else DEFAULT_STATE_REL
    if not harvested:
        return {}, [
            Finding(
                "error",
                "writeback-refused",
                "--from-active-plan found no closeout facts in an explicit Closeout Summary/Facts/Fields section or the project-state closeout authority block",
                source,
            )
        ]
    if not closeout_values_are_complete(harvested):
        missing = ", ".join(missing_complete_closeout_fields(harvested))
        return {}, [
            Finding(
                "error",
                "writeback-refused",
                (
                    "--from-active-plan fallback found incomplete project-state closeout facts; "
                    f"missing fields: {missing or '<none>'}; supply complete closeout facts explicitly"
                ),
                source,
            )
        ]

    existing_identity = _identity_from_facts(state_writeback_identity_facts(inventory.state))
    current_identity = _current_closeout_identity(inventory, None)
    if not _closeout_identity_matches(existing_identity, current_identity):
        return {}, [
            Finding(
                "error",
                "writeback-refused",
                "--from-active-plan fallback refused project-state closeout facts because recorded identity "
                f"{_closeout_identity_summary(existing_identity)} does not match current identity {_closeout_identity_summary(current_identity)}",
                source,
            )
        ]
    return harvested, []


def state_writeback_identity_matches_current_plan(inventory: Inventory) -> bool:
    existing_identity = _identity_from_facts(state_writeback_identity_facts(inventory.state))
    current_identity = _current_closeout_identity(inventory, None)
    return _closeout_identity_matches(existing_identity, current_identity)


def current_state_writeback_facts(inventory: Inventory) -> dict[str, WritebackFact]:
    facts = state_writeback_facts(inventory.state)
    if _satisfied_post_archive_carry_forward_fact(inventory, facts.get("carry_forward")):
        facts = dict(facts)
        facts.pop("carry_forward", None)
    return facts


def satisfied_post_archive_carry_forward_finding(inventory: Inventory, code: str) -> Finding | None:
    fact = state_writeback_facts(inventory.state).get("carry_forward")
    if not _satisfied_post_archive_carry_forward_fact(inventory, fact):
        return None
    return Finding(
        "info",
        code,
        (
            "historical satisfied carry-forward only: "
            f"{fact.value}; not a current closeout candidate or next action"
        ),
        fact.source,
        fact.line,
    )


def _satisfied_post_archive_carry_forward_fact(inventory: Inventory, fact: WritebackFact | None) -> bool:
    if fact is None or fact.field != "carry_forward":
        return False
    state = inventory.state
    if state is None or not state.exists or not state.frontmatter.has_frontmatter or state.frontmatter.errors:
        return False
    state_data = state.frontmatter.data
    plan_status = str(state_data.get("plan_status") or "").strip().casefold()
    active_plan = _normalize_rel(str(state_data.get("active_plan") or ""))
    last_archived_plan = _normalize_rel(str(state_data.get("last_archived_plan") or ""))
    if plan_status != "none" or active_plan or not last_archived_plan:
        return False
    if not state_writeback_identity_matches_current_plan(inventory):
        return False
    if not _carry_forward_mentions_completed_archive_action(fact.value):
        return False
    return _roadmap_archive_done_item_exists(inventory, last_archived_plan)


def _carry_forward_mentions_completed_archive_action(value: str) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").casefold())
    archive_action = (
        "archive active plan" in text
        or "archive this active plan" in text
        or "active plan archive" in text
        or "plan will be archived" in text
    )
    roadmap_done = "roadmap item" in text and ("done" in text or "mark" in text)
    return archive_action and roadmap_done


def _roadmap_archive_done_item_exists(inventory: Inventory, archived_plan: str) -> bool:
    items, errors = roadmap_items_for_diagnostics(inventory)
    if errors:
        return False
    archived_item_ids = set(_archived_plan_roadmap_item_ids(inventory, archived_plan))
    for item in items.values():
        fields = item.fields
        status = _normalized_status(_scalar_field_value(fields.get("status")))
        if status != "done":
            continue
        item_archived_plan = _normalize_rel(_scalar_field_value(fields.get("archived_plan")))
        item_related_plan = _normalize_rel(_scalar_field_value(fields.get("related_plan")))
        if archived_plan in {item_archived_plan, item_related_plan}:
            return True
        if _normalized_item_id(fields.get("id")) in archived_item_ids:
            return True
    return False


def _archived_plan_roadmap_item_ids(inventory: Inventory, archived_plan: str) -> tuple[str, ...]:
    path = inventory.root / archived_plan
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    frontmatter = parse_frontmatter(text)
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return ()
    data = frontmatter.data
    return tuple(
        _dedupe_nonempty(
            (
                _normalized_item_id(data.get("primary_roadmap_item")),
                _normalized_item_id(data.get("related_roadmap_item")),
                *_frontmatter_item_list(data.get("covered_roadmap_items")),
            )
        )
    )


def _scalar_field_value(value: object) -> str:
    if value in (None, "", [], ()):
        return ""
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    return str(value).strip()


def _writeback_root_state_preflight_errors(inventory: Inventory) -> list[Finding]:
    errors: list[Finding] = []
    if inventory.root_kind == "product_source_fixture":
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                "target is a product-source compatibility fixture; writeback --apply is refused",
                inventory.state.rel_path if inventory.state else "project/project-state.md",
            )
        )
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                "target is fallback/archive or generated-output evidence; writeback --apply is refused",
                inventory.state.rel_path if inventory.state else "project/project-state.md",
            )
        )
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "writeback-refused", f"target root kind is {inventory.root_kind}; writeback requires a live operating root"))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "writeback-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                "project-state.md must have frontmatter before closeout/state writeback; run the bounded state-frontmatter repair first",
                state.rel_path,
            )
        )
    elif state.frontmatter.errors:
        errors.append(Finding("error", "writeback-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "writeback-refused", "project-state.md is not a regular file", state.rel_path))
    return errors


def _product_source_root_errors(inventory: Inventory, value: str) -> list[Finding]:
    errors: list[Finding] = []
    if "\n" in value or "\r" in value:
        errors.append(Finding("error", "writeback-refused", "--product-source-root must be a one-line path value"))
        return errors
    try:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = inventory.root / candidate
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        errors.append(Finding("error", "writeback-refused", f"--product-source-root could not be resolved: {exc}"))
        return errors
    if not resolved.exists():
        errors.append(Finding("error", "writeback-refused", f"--product-source-root does not exist: {value}"))
    elif not resolved.is_dir():
        errors.append(Finding("error", "writeback-refused", f"--product-source-root is not a directory: {value}"))
    elif str(resolved).casefold() == str(inventory.root.resolve()).casefold():
        errors.append(Finding("error", "writeback-refused", "--product-source-root must not point at the operating root"))
    return errors


def _archived_plan_request_errors(inventory: Inventory, rel_path: str) -> list[Finding]:
    errors: list[Finding] = []
    rel_path = _normalize_rel(rel_path)
    if not rel_path:
        return [Finding("error", "writeback-refused", "--archived-plan must be a non-empty root-relative route")]
    if Path(rel_path).is_absolute() or ".." in Path(rel_path).parts:
        return [Finding("error", "writeback-refused", "--archived-plan must be a safe root-relative route")]
    archive_dir = _normalize_rel(_manifest_memory_value(inventory, "archive_dir", DEFAULT_ARCHIVE_DIR_REL))
    if rel_path == archive_dir or not rel_path.startswith(f"{archive_dir}/"):
        errors.append(Finding("error", "writeback-refused", f"--archived-plan must be under {archive_dir}", rel_path))
        return errors
    path = inventory.root / rel_path
    if _path_escapes_root(inventory.root, path):
        errors.append(Finding("error", "writeback-refused", "--archived-plan escapes the target root", rel_path))
    elif not path.exists():
        errors.append(Finding("error", "writeback-refused", f"--archived-plan does not exist: {rel_path}", rel_path))
    elif not path.is_file():
        errors.append(Finding("error", "writeback-refused", "--archived-plan is not a regular file", rel_path))
    elif path.is_symlink():
        errors.append(Finding("error", "writeback-refused", "--archived-plan is a symlink; inactive refresh is refused", rel_path))
    return errors


def _archived_plan_identity_boundary_errors(inventory: Inventory, rel_path: str) -> list[Finding]:
    rel_path = _normalize_rel(rel_path)
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    last_archived_plan = _normalize_rel(str(state_data.get("last_archived_plan") or ""))
    if last_archived_plan == rel_path:
        return []

    current_identity = _current_closeout_identity(inventory, rel_path)
    state_identity = _identity_from_facts(state_writeback_identity_facts(inventory.state))
    if _closeout_identity_matches(state_identity, current_identity):
        return []

    archived_surface = _archived_plan_surface(inventory, rel_path)
    archived_identity = _identity_from_facts(state_writeback_identity_facts(archived_surface))
    if _closeout_identity_matches(archived_identity, current_identity):
        return []

    return [
        Finding(
            "error",
            "writeback-archived-plan-identity-refused",
            (
                "--archived-plan without --roadmap-item must be identity-bound to the current last_archived_plan "
                "or to matching project-state/archived-plan closeout identity; "
                f"requested {rel_path}; current identity {_closeout_identity_summary(current_identity)}; "
                f"project-state identity {_closeout_identity_summary(state_identity)}; "
                f"archived-plan identity {_closeout_identity_summary(archived_identity)}"
            ),
            rel_path,
        )
    ]


def _archived_plan_surface(inventory: Inventory, rel_path: str) -> Surface | None:
    rel_path = _normalize_rel(rel_path)
    path = inventory.root / rel_path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return Surface(
        root=inventory.root,
        rel_path=rel_path,
        role="archive",
        required=False,
        path=path,
        exists=True,
        content=text,
        frontmatter=parse_frontmatter(text),
        memory_route="archive",
        memory_route_target="historical evidence",
        memory_route_authority="cold evidence; not lifecycle authority",
    )


def _archived_plan_refresh_plan(
    inventory: Inventory,
    request: WritebackRequest,
    closeout_values: dict[str, str],
    identity: CloseoutIdentity,
    *,
    apply: bool,
) -> ArchivedPlanRefreshPlan | None:
    if not request.archived_plan:
        return None
    surface = _archived_plan_surface(inventory, request.archived_plan)
    if surface is None:
        return None
    text, findings = _archived_plan_text_with_synced_closeout_values(surface, closeout_values, identity, apply=apply)
    findings.extend(_archived_plan_compacted_history_findings(inventory, request.archived_plan))
    return ArchivedPlanRefreshPlan(surface=surface, updated_text=text, findings=tuple(findings))


def _archived_plan_text_with_synced_closeout_values(
    surface: Surface,
    closeout_values: dict[str, str],
    identity: CloseoutIdentity,
    *,
    apply: bool,
) -> tuple[str, list[Finding]]:
    prefix = "" if apply else "would "
    text = surface.content
    findings: list[Finding] = []
    if not closeout_values:
        return text, [Finding("info", "writeback-archived-plan-closeout-skipped", "no closeout facts available for archived-plan refresh", surface.rel_path)]

    frontmatter_text, frontmatter_keys = _update_existing_frontmatter_scalars(text, closeout_values)
    text = frontmatter_text
    if frontmatter_keys:
        findings.append(
            Finding(
                "info",
                "writeback-archived-plan-frontmatter-updated",
                f"{prefix}sync archived-plan frontmatter keys: {', '.join(frontmatter_keys)}",
                surface.rel_path,
            )
        )

    body_text, body_fields = _update_exact_body_fields(text, closeout_values)
    text = body_text
    if body_fields:
        findings.append(
            Finding(
                "info",
                "writeback-archived-plan-body-updated",
                f"{prefix}sync archived-plan closeout body fields: {', '.join(body_fields)}",
                surface.rel_path,
            )
        )

    block_text = _replace_or_append_writeback_block(text, closeout_values, identity)
    if block_text != text:
        findings.append(
            Finding(
                "info",
                "writeback-archived-plan-closeout-updated",
                f"{prefix}sync archived-plan MLH closeout writeback copy by archived-plan identity",
                surface.rel_path,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "writeback-archived-plan-closeout-noop",
                "archived-plan MLH closeout writeback copy already matches planned identity-bound facts",
                surface.rel_path,
            )
        )
    return block_text, findings


def _archived_plan_compacted_history_findings(inventory: Inventory, rel_path: str) -> list[Finding]:
    roadmap = inventory.surface_by_rel.get("project/roadmap.md")
    if not roadmap or not roadmap.exists:
        return []
    rel_path = _normalize_rel(rel_path)
    item_ids = []
    pattern = re.compile(r"-\s+Compacted done roadmap item `([^`]+)`:\s+archived plan `([^`]+)`\.")
    for match in pattern.finditer(roadmap.content):
        if _normalize_rel(match.group(2)) == rel_path:
            item_ids.append(_normalized_item_id(match.group(1)))
    if not item_ids:
        return []
    return [
        Finding(
            "info",
            "writeback-archived-plan-compacted-history",
            (
                "Archived Completed History names this archived plan for compacted done roadmap item(s): "
                f"{', '.join(_dedupe_nonempty(item_ids))}; this is evidence only and does not recreate a roadmap item block"
            ),
            roadmap.rel_path,
        )
    ]


def _archived_plan_already_closed_finding(rel_path: str, apply: bool) -> Finding:
    prefix = "" if apply else "would "
    return Finding(
        "info",
        "writeback-archived-plan-already-closed",
        f"{prefix}leave archived-plan closeout unchanged because project-state and archived-plan closeout copies are already synchronized",
        rel_path,
    )


def _writeback_archive_apply_findings(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    state = inventory.state
    assert state is not None
    archive_plan = _archive_plan(inventory, request)
    if archive_plan is None:
        return [Finding("error", "writeback-refused", "archive-active-plan could not determine a safe archive target")]

    closeout_plan = _closeout_writeback_plan(inventory, request, archive_plan.archive_rel_path)
    planned = closeout_plan.values
    lifecycle_values = _planned_lifecycle_values(request, archive_plan.archive_rel_path, _archive_phase_status(inventory, request))
    roadmap_plan, roadmap_errors = _writeback_roadmap_plan(inventory, request, archive_plan.archive_rel_path)
    if roadmap_errors:
        return roadmap_errors
    batch_gate_findings = _writeback_batch_slice_gate_findings(inventory, request, apply=True)
    incubation_plan, incubation_errors = _writeback_incubation_plan(inventory, request, archive_plan.archive_rel_path)
    if incubation_errors:
        return incubation_errors
    route_retarget_plans = _archive_route_retarget_plans(
        inventory,
        archive_plan.archive_rel_path,
        skip_rels=(*_incubation_plan_source_rels(incubation_plan), *request.archive_retarget_skip_rels),
    )
    state_text = _state_text_with_writeback(state.content, planned, lifecycle_values, closeout_plan.identity)
    active_plan_lifecycle = _active_plan_lifecycle_values(inventory, request, lifecycle_values)
    plan_text, sync_findings = _active_plan_text_with_synced_values(
        archive_plan.plan,
        planned,
        active_plan_lifecycle,
        _requested_or_current_active_phase(inventory, active_plan_lifecycle),
        "",
    )
    plan_text, capsule_findings = _archive_plan_text_with_closeout_evidence_capsule(
        plan_text,
        planned,
        closeout_plan.identity,
        archive_plan.archive_rel_path,
        apply=True,
    )
    findings: list[Finding] = [
        Finding("info", "writeback-apply", "closeout/state writeback apply started"),
        _planned_closeout_finding(planned),
    ]
    findings.extend(batch_gate_findings)
    findings.extend(_closeout_writeback_plan_findings(closeout_plan, apply=True))
    findings.extend(_scoped_interrupt_writeback_boundary_findings(inventory, request, apply=True))
    findings.extend(_archive_plan_findings(inventory, archive_plan, apply=True))
    findings.append(
        Finding(
            "info",
            "writeback-lifecycle-updated",
            f"updated project-state lifecycle frontmatter: {', '.join(lifecycle_values)}",
            state.rel_path,
        )
    )
    findings.append(_phase_execution_boundary_finding(lifecycle_values, state.rel_path, apply=True))
    findings.extend(_phase_writeback_tail_retirement_findings(inventory, state_text, apply=True))

    state_tmp = state.path.with_name(f".{state.path.name}.writeback.tmp")
    state_backup = state.path.with_name(f".{state.path.name}.writeback.backup")
    archive_write_needed = archive_plan.existing_archive_text != plan_text
    archive_tmp = archive_plan.archive_path.with_name(f".{archive_plan.archive_path.name}.writeback.tmp") if archive_write_needed else None
    archive_backup = archive_plan.archive_path.with_name(f".{archive_plan.archive_path.name}.writeback.backup") if archive_write_needed else None
    plan_backup = archive_plan.plan.path.with_name(f".{archive_plan.plan.path.name}.writeback.backup")
    roadmap_tmp = _roadmap_writeback_tmp(roadmap_plan)
    incubation_tmp = _incubation_writeback_tmp(incubation_plan)
    incubation_backup = _incubation_source_backup(incubation_plan)
    if incubation_plan and incubation_plan.archive_rel:
        state_text = state_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel)
        plan_text = plan_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel)
        if roadmap_plan:
            roadmap_plan = _roadmap_writeback_plan_with_updated_text(
                roadmap_plan,
                roadmap_plan.updated_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel),
            )
            roadmap_tmp = _roadmap_writeback_tmp(roadmap_plan)
        route_retarget_plans = tuple(
            _route_retarget_plan_with_updated_text(plan, plan.updated_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel))
            for plan in route_retarget_plans
        )
    incubation_plan = _relationship_plan_without_subsumed_link_repairs(
        incubation_plan,
        _writeback_subsumed_link_repair_rels(
            inventory,
            plan_text,
            roadmap_plan,
            route_retarget_plans,
            archive_plan,
            None,
        ),
    )
    roadmap_backup = _roadmap_writeback_backup(roadmap_plan) if roadmap_tmp else None
    incubation_write_backup = _incubation_writeback_backup(incubation_plan) if incubation_tmp else None
    link_repair_skip_targets = {state.path, archive_plan.plan.path}
    if roadmap_plan:
        link_repair_skip_targets.add(roadmap_plan.target_path)
    link_repair_skip_targets.update(plan.target_path for plan in route_retarget_plans)
    incubation_link_tmps = [
        (tmp_path, backup_path, target_path, text)
        for tmp_path, backup_path, target_path, text in _incubation_link_tmp_paths(incubation_plan)
        if target_path not in link_repair_skip_targets
    ]
    route_writes = _writeback_route_write_evidence(
        inventory,
        state_text,
        plan_text,
        roadmap_plan,
        incubation_plan,
        route_retarget_plans,
        archive_plan,
        plan_text,
    )
    route_write_evidence = _writeback_route_write_report_findings(
        route_writes,
        apply=True,
        archive_plan=archive_plan,
        incubation_plan=incubation_plan,
    )
    guard_findings = route_reference_transaction_guard_findings(inventory, route_writes, apply=True)
    route_retarget_tmps = [
        (
            plan.target_path.with_name(f".{plan.target_path.name}.writeback-retarget.tmp"),
            plan.target_path.with_name(f".{plan.target_path.name}.writeback-retarget.backup"),
            plan,
        )
        for plan in route_retarget_plans
        if plan.current_text != plan.updated_text
    ]
    tmp_checks = [
        (state_tmp, "temporary state write path"),
        (state_backup, "temporary state backup path"),
        (plan_backup, "temporary active-plan backup path"),
    ]
    if archive_tmp:
        tmp_checks.append((archive_tmp, "temporary archive write path"))
    if archive_backup:
        tmp_checks.append((archive_backup, "temporary archive backup path"))
    if roadmap_tmp:
        tmp_checks.append((roadmap_tmp, "temporary roadmap write path"))
    if roadmap_backup:
        tmp_checks.append((roadmap_backup, "temporary roadmap backup path"))
    if incubation_tmp:
        tmp_checks.append((incubation_tmp, "temporary incubation relationship write path"))
    if incubation_write_backup:
        tmp_checks.append((incubation_write_backup, "temporary incubation relationship backup path"))
    if incubation_backup:
        tmp_checks.append((incubation_backup, "temporary incubation source backup path"))
    tmp_checks.extend((tmp_path, "temporary route-retarget write path") for tmp_path, _backup_path, _plan in route_retarget_tmps)
    tmp_checks.extend((backup_path, "temporary route-retarget backup path") for _tmp_path, backup_path, _plan in route_retarget_tmps)
    tmp_checks.extend((tmp_path, "temporary incubation link-repair write path") for tmp_path, _backup_path, _target, _text in incubation_link_tmps)
    tmp_checks.extend((backup_path, "temporary incubation link-repair backup path") for _tmp_path, backup_path, _target, _text in incubation_link_tmps)
    for tmp_path, label in tmp_checks:
        if tmp_path.exists():
            return [Finding("error", "writeback-refused", f"{label} already exists: {tmp_path.relative_to(inventory.root).as_posix()}")]

    if any(finding.severity == "error" for finding in guard_findings):
        return [
            *guard_findings,
            Finding(
                "info",
                "writeback-validation-posture",
                "archive-active-plan apply refused before writing files; review unresolved required route references, then rerun dry-run",
                state.rel_path,
            ),
        ]

    operations: list[AtomicFileWrite | AtomicFileDelete] = [
        AtomicFileWrite(state.path, state_tmp, state_text, state_backup),
        AtomicFileDelete(archive_plan.plan.path, plan_backup),
    ]
    if archive_tmp and archive_backup:
        operations.insert(1, AtomicFileWrite(archive_plan.archive_path, archive_tmp, plan_text, archive_backup))
    if roadmap_tmp and roadmap_backup and roadmap_plan:
        operations.append(AtomicFileWrite(roadmap_plan.target_path, roadmap_tmp, roadmap_plan.updated_text, roadmap_backup))
    if incubation_tmp and incubation_write_backup and incubation_plan:
        operations.append(AtomicFileWrite(incubation_plan.target_path, incubation_tmp, incubation_plan.updated_text, incubation_write_backup))
        if incubation_plan.archive_rel and incubation_backup:
            operations.append(AtomicFileDelete(incubation_plan.source_path, incubation_backup))
    for tmp_path, backup_path, retarget_plan in route_retarget_tmps:
        operations.append(AtomicFileWrite(retarget_plan.target_path, tmp_path, retarget_plan.updated_text, backup_path))
    for tmp_path, backup_path, target_path, text in incubation_link_tmps:
        operations.append(AtomicFileWrite(target_path, tmp_path, text, backup_path))

    try:
        cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
    except FileTransactionError as exc:
        return [Finding("error", "writeback-refused", f"archive-active-plan failed before all target files were written: {exc}")]

    if planned:
        findings.append(
            Finding(
                "info",
                "writeback-state-updated",
                "wrote MLH-owned closeout writeback block in project/project-state.md",
                state.rel_path,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "writeback-state-updated",
                "updated project-state lifecycle frontmatter and Current Focus managed block without adding a closeout writeback block",
                state.rel_path,
            )
        )
    findings.extend(sync_findings)
    findings.extend(capsule_findings)
    findings.extend(route_write_evidence)
    findings.extend(guard_findings)
    if roadmap_plan:
        findings.extend(_writeback_roadmap_findings(roadmap_plan, apply=True))
    if incubation_plan:
        findings.extend(_writeback_incubation_findings(incubation_plan, apply=True))
    if route_retarget_plans:
        findings.extend(_archive_route_retarget_findings(route_retarget_plans, apply=True))
    findings.extend(_post_archive_verification_posture_findings(inventory, apply=True))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "writeback-archive-backup-cleanup", warning, archive_plan.archive_rel_path))
    findings.extend(
        [
            Finding("info", "writeback-active-plan-archived", f"moved active plan to {archive_plan.archive_rel_path}", archive_plan.archive_rel_path),
            Finding(
                "info",
                "writeback-validation-posture",
                "run check after archive apply to verify inactive lifecycle state and absence of stale-plan-file drift",
            ),
            Finding(
                "info",
                "writeback-authority",
                "project-state frontmatter remains lifecycle authority; the MLH closeout writeback block is current closeout fact authority; archived plans are historical evidence",
                state.rel_path,
            ),
        ]
    )
    compaction_plan = _state_compaction_plan(inventory, state.path.read_text(encoding="utf-8"))
    findings.extend(_apply_state_compaction(inventory, compaction_plan))
    return findings


def _post_archive_verification_posture_findings(inventory: Inventory, apply: bool) -> list[Finding]:
    verification_rels = _verification_artifact_rels(inventory)
    if not verification_rels:
        return []
    prefix = "" if apply else "would "
    sample = ", ".join(verification_rels[:3])
    if len(verification_rels) > 3:
        sample = f"{sample}, ..."
    return [
        Finding(
            "info",
            "writeback-post-archive-verification-posture",
            (
                f"{prefix}treat existing verification artifact(s) as pre-archive lifecycle snapshots after archive route writes: "
                f"{sample}; rerun check or regenerate explicit verification evidence when final post-archive route state must be audited"
            ),
            "project/verification",
        )
    ]


def _verification_artifact_rels(inventory: Inventory) -> tuple[str, ...]:
    verification_dir = inventory.root / "project/verification"
    if not verification_dir.is_dir():
        return ()
    rels: list[str] = []
    for path in sorted(verification_dir.glob("*.md"), key=lambda item: item.name.casefold()):
        if path.is_file():
            rels.append(path.relative_to(inventory.root).as_posix())
    return tuple(rels)


def _should_carry_current_closeout_values(request: WritebackRequest) -> bool:
    if request.roadmap_item:
        return False
    return bool(request.closeout)


def _is_phase_only_uncertain_docs_writeback(request: WritebackRequest) -> bool:
    if request.archive_active_plan or request.roadmap_item or request.roadmap_status:
        return False
    if request.closeout.get("docs_decision") != "uncertain":
        return False
    if not set(request.lifecycle).issubset({"active_phase", "phase_status"}):
        return False
    phase_status = request.lifecycle.get("phase_status")
    if request.closeout == {"docs_decision": "uncertain"}:
        return phase_status == "complete"
    return phase_status in {"complete", "pending"} and _has_provisional_phase_evidence(request.closeout)


def _has_provisional_phase_evidence(values: dict[str, str]) -> bool:
    if not values.get("verification"):
        return False
    return bool(values.get("state_writeback") or values.get("work_result"))


def _writeback_acceptance_completion_reason(
    inventory: Inventory,
    request: WritebackRequest,
    closeout_values: dict[str, str],
) -> str:
    if request.archive_active_plan:
        return "archive-active-plan closeout"
    if request.roadmap_status in {"done", "complete"}:
        return f"roadmap status {request.roadmap_status}"
    phase_status = request.lifecycle.get("phase_status", "")
    if phase_status == "complete":
        return "phase_status complete"
    completed_phase = _phase_advancement_completed_phase(inventory, request.lifecycle)
    if completed_phase:
        return f"phase advancement completes {completed_phase}"
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    if str(state_data.get("phase_status") or "") == "complete" and closeout_values:
        return "completed-phase closeout writeback"
    if closeout_values_are_complete(closeout_values):
        return "complete closeout facts"
    return ""


def acceptance_evidence_findings(
    inventory: Inventory,
    closeout_values: dict[str, str],
    *,
    completion_reason: str,
    apply: bool = False,
    code_prefix: str = "writeback",
    include_success: bool = False,
) -> list[Finding]:
    if not completion_reason:
        return []
    contract = _active_acceptance_evidence_contract(inventory)
    if contract is None:
        return []

    severity = "error" if apply else "warn"
    findings: list[Finding] = []
    missing = _missing_acceptance_evidence_fields(closeout_values)
    if missing:
        findings.append(
            Finding(
                severity,
                f"{code_prefix}-acceptance-evidence-missing",
                (
                    f"{completion_reason} would complete a {contract.deliverable_class} deliverable, but "
                    f"acceptance evidence is missing field(s): {', '.join(missing)}; record docs_decision, "
                    "state_writeback, verification, and residual_risk before lifecycle acceptance"
                ),
                contract.source,
            )
        )

    verification = closeout_values.get("verification", "")
    if verification and _verification_evidence_is_generic(verification):
        findings.append(
            Finding(
                severity,
                f"{code_prefix}-acceptance-evidence-generic",
                (
                    f"{completion_reason} evidence is too generic for the acceptance claim: "
                    "verification must name a concrete command, artifact, target path, or route-specific proof"
                ),
                contract.source,
            )
        )

    evidence_text = _acceptance_evidence_text(closeout_values)
    if evidence_text and not _acceptance_evidence_matches_contract(evidence_text, contract):
        findings.append(
            Finding(
                severity,
                f"{code_prefix}-acceptance-evidence-mismatch",
                (
                    f"{completion_reason} evidence does not match the active acceptance claim; mention the roadmap "
                    "item, execution slice, declared target artifact, or concrete acceptance terms before closeout"
                ),
                contract.source,
            )
        )

    class_mismatch = _acceptance_deliverable_class_mismatch(contract, evidence_text)
    if class_mismatch:
        findings.append(
            Finding(
                severity,
                f"{code_prefix}-acceptance-evidence-class-mismatch",
                f"{completion_reason} evidence has the wrong deliverable class: {class_mismatch}",
                contract.source,
            )
        )

    findings.extend(
        _declared_target_evidence_findings(
            inventory,
            closeout_values,
            contract,
            completion_reason=completion_reason,
            severity=severity,
            code_prefix=code_prefix,
        )
    )

    fan_in_missing = _fan_in_review_disposition_missing_fields(inventory, contract, evidence_text)
    if fan_in_missing:
        findings.append(
            Finding(
                severity,
                f"{code_prefix}-fan-in-review-disposition-missing",
                (
                    f"{completion_reason} would complete fan-in review evidence without required disposition field(s): "
                    f"{', '.join(fan_in_missing)}; fan-in review artifacts must name source snapshot, cluster disposition, "
                    "missing evidence, forbidden shortcuts, owner route, follow-up slice, and no implicit product-diff "
                    "acceptance before lifecycle acceptance"
                ),
                contract.source,
            )
        )

    docs_risk = _docs_decision_residual_risk_mismatch(closeout_values)
    if docs_risk:
        findings.append(
            Finding(
                severity,
                f"{code_prefix}-acceptance-evidence-docs-risk",
                f"{completion_reason} evidence does not reconcile docs_decision with residual risk: {docs_risk}",
                contract.source,
            )
        )

    if findings or not include_success:
        return findings
    return [
        Finding(
            "info",
            f"{code_prefix}-acceptance-evidence",
            (
                f"{completion_reason} has acceptance-aligned evidence for "
                f"deliverable_class={contract.deliverable_class}; item(s)={', '.join(contract.item_ids) or '<none>'}"
            ),
            contract.source,
        )
    ]


def _scoped_interrupt_writeback_boundary_findings(
    inventory: Inventory,
    request: WritebackRequest,
    *,
    apply: bool,
) -> list[Finding]:
    plan = inventory.active_plan_surface
    if plan is None or not plan.exists or not plan.frontmatter.has_frontmatter or plan.frontmatter.errors:
        return []
    data = plan.frontmatter.data
    work_intent = str(data.get("work_intent") or "").strip().casefold()
    if work_intent != SCOPED_INTERRUPT_WORK_INTENT:
        return []
    policy = str(data.get("roadmap_status_policy") or "").strip() or "<empty>"
    prefix = "" if apply else "would "
    if request.roadmap_item or request.roadmap_status:
        movement = (
            f"explicit roadmap sync requested: item={request.roadmap_item or '<empty>'!r}, "
            f"status={request.roadmap_status or '<empty>'!r}"
        )
    else:
        movement = "no roadmap status movement requested"
    severity = "info" if policy == SCOPED_INTERRUPT_ROADMAP_STATUS_POLICY else "warn"
    return [
        Finding(
            severity,
            "writeback-scoped-interrupt-boundary",
            (
                f"{prefix}handle scoped_interrupt closeout/archive with roadmap_status_policy {policy!r}; "
                f"{movement}; record verification, docs_decision, residual risk, and carry_forward/return-to-roadmap evidence"
            ),
            plan.rel_path,
        )
    ]


def _active_acceptance_evidence_contract(inventory: Inventory) -> AcceptanceEvidenceContract | None:
    plan = inventory.active_plan_surface
    if plan is None or not plan.exists or not plan.frontmatter.has_frontmatter or plan.frontmatter.errors:
        return None
    data = plan.frontmatter.data
    plan_ids = (
        _normalized_item_id(data.get("primary_roadmap_item")),
        _normalized_item_id(data.get("related_roadmap_item")),
        *(_normalized_item_id(value) for value in _metadata_list_values(data.get("covered_roadmap_items"))),
        *active_plan_roadmap_item_ids(inventory),
    )
    item_ids = tuple(_dedupe_nonempty(plan_ids))
    roadmap_fields = [roadmap_item_fields(inventory, item_id) for item_id in item_ids]
    target_artifacts = tuple(
        _dedupe_nonempty(
            (
                *(_normalize_rel(value) for value in _metadata_list_values(data.get("target_artifacts"))),
                *(
                    _normalize_rel(value)
                    for fields in roadmap_fields
                    for value in _metadata_list_values(fields.get("target_artifacts"))
                ),
            )
        )
    )
    has_explicit_contract = bool(
        data.get("execution_slice")
        or data.get("deliverable_class")
        or data.get("work_class")
        or target_artifacts
        or any(fields.get("deliverable_class") or fields.get("work_class") for fields in roadmap_fields)
    )
    if not has_explicit_contract:
        return None
    deliverable_class = _acceptance_deliverable_class(data, roadmap_fields, target_artifacts)
    text_parts = [
        str(data.get("plan_id") or ""),
        str(data.get("title") or ""),
        str(data.get("execution_slice") or ""),
        str(data.get("objective") or ""),
        str(data.get("closeout_boundary") or ""),
        plan.content,
    ]
    for fields in roadmap_fields:
        text_parts.extend(
            str(_scalar_field_value(fields.get(field)) or "")
            for field in ("slice_goal", "verification_summary", "carry_forward", "slice_closeout_boundary")
        )
    acceptance_terms = _acceptance_terms((*item_ids, *text_parts))
    if not item_ids and not target_artifacts and not acceptance_terms:
        return None
    return AcceptanceEvidenceContract(
        deliverable_class=deliverable_class,
        item_ids=item_ids,
        target_artifacts=target_artifacts,
        acceptance_terms=acceptance_terms,
        source=plan.rel_path,
    )


def _acceptance_deliverable_class(
    plan_data: dict[str, object],
    roadmap_fields: list[dict[str, object]],
    target_artifacts: tuple[str, ...],
) -> str:
    candidates = [
        plan_data.get("deliverable_class"),
        plan_data.get("work_class"),
        *(fields.get("deliverable_class") for fields in roadmap_fields),
        *(fields.get("work_class") for fields in roadmap_fields),
    ]
    for candidate in candidates:
        normalized = _normalize_deliverable_class(str(candidate or ""))
        if normalized:
            return normalized
    combined = " ".join(
        str(value or "")
        for value in (
            plan_data.get("title"),
            plan_data.get("objective"),
            plan_data.get("closeout_boundary"),
            *(fields.get("slice_goal") for fields in roadmap_fields),
            *(fields.get("slice_closeout_boundary") for fields in roadmap_fields),
        )
    ).casefold()
    if ("fan-in" in combined or "fan in" in combined) and "review" in combined:
        return "fan-in-review"
    for marker in ("audit", "proposal", "diagnostic", "evidence", "review", "research"):
        if marker in combined:
            return marker
    if any(_normalize_rel(path).startswith(("src/", "tests/")) for path in target_artifacts):
        return "implementation"
    return "implementation"


def _normalize_deliverable_class(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().casefold()).strip("-")
    aliases = {
        "impl": "implementation",
        "implement": "implementation",
        "implementation-work": "implementation",
        "diagnostics": "diagnostic",
        "audit-only": "audit",
        "fan-in": "fan-in-review",
        "fan-in-diagnostic": "fan-in-review",
        "fan-in-review-diagnostic": "fan-in-review",
        "fan_in": "fan-in-review",
        "fan_in_diagnostic": "fan-in-review",
        "fan_in_review": "fan-in-review",
        "fan_in_review_diagnostic": "fan-in-review",
        "proposal-only": "proposal",
        "review-only": "review",
    }
    normalized = aliases.get(normalized, normalized)
    allowed = {"implementation", "audit", "proposal", "diagnostic", "evidence", "fan-in-review", "review", "research", "documentation"}
    return normalized if normalized in allowed else ""


def _metadata_list_values(value: object) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip().strip("`\"'") for item in value if str(item).strip())
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
        return tuple(part.strip().strip("`\"'") for part in text.split(",") if part.strip().strip("`\"'"))
    return (text.strip("`\"'"),) if text.strip("`\"'") else ()


def _acceptance_terms(values: tuple[str, ...]) -> tuple[str, ...]:
    stop_words = {
        "active",
        "artifact",
        "artifacts",
        "class",
        "closeout",
        "complete",
        "current",
        "decision",
        "deliverable",
        "docs",
        "implementation",
        "mylittleharness",
        "phase",
        "plan",
        "project",
        "route",
        "slice",
        "source",
        "status",
        "target",
        "workflow",
    }
    terms: list[str] = []
    for value in values:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_/-]{4,}", str(value or "").casefold()):
            token = token.strip("_/-")
            if token and token not in stop_words:
                terms.append(token)
    return tuple(_dedupe_nonempty(terms[:80]))


def _missing_acceptance_evidence_fields(values: dict[str, str]) -> tuple[str, ...]:
    missing: list[str] = []
    docs_decision = str(values.get("docs_decision") or "").strip().casefold()
    if docs_decision not in DOCS_DECISION_VALUES:
        missing.append("docs_decision")
    for field in ("state_writeback", "verification", "residual_risk"):
        if not _acceptance_evidence_value_is_present(values.get(field, "")):
            missing.append(field)
    return tuple(missing)


def _acceptance_evidence_value_is_present(value: object) -> bool:
    normalized = re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".").casefold()
    return normalized not in INCOMPLETE_CLOSEOUT_VALUES


def _verification_evidence_is_generic(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".").casefold()
    if normalized in GENERIC_ACCEPTANCE_EVIDENCE_VALUES:
        return True
    concrete_markers = (
        " exit 0",
        " passed with ",
        "--root ",
        "mylittleharness ",
        "project/verification/",
        "pytest ",
        "pythonpath=src",
        "status ok",
        "status: ok",
        "tests/",
        "uv run ",
    )
    if any(marker in f" {normalized} " for marker in concrete_markers):
        return False
    generic_words = {"focused", "full", "suite", "test", "tests", "unit", "validation", "verification", "passed", "complete"}
    tokens = re.findall(r"[a-z0-9_-]+", normalized)
    return bool(tokens) and len(tokens) <= 5 and all(token in generic_words for token in tokens)


def _acceptance_evidence_text(values: dict[str, str]) -> str:
    return "\n".join(
        str(values.get(field) or "")
        for field in ("state_writeback", "verification", "residual_risk", "carry_forward", "work_result")
        if values.get(field)
    )


def _acceptance_evidence_matches_contract(text: str, contract: AcceptanceEvidenceContract) -> bool:
    normalized = _normalized_evidence_text(text)
    for item_id in contract.item_ids:
        if item_id and item_id.casefold() in normalized:
            return True
    for target in contract.target_artifacts:
        target_norm = _normalize_rel(target).casefold()
        target_name = Path(target_norm).name
        if target_norm and target_norm in normalized:
            return True
        if target_name and target_name in normalized:
            return True
    matched_terms = [term for term in contract.acceptance_terms if term and term in normalized]
    return len(matched_terms) >= min(2, max(1, len(contract.acceptance_terms)))


def _acceptance_deliverable_class_mismatch(contract: AcceptanceEvidenceContract, evidence_text: str) -> str:
    if not evidence_text:
        return ""
    normalized = _normalized_evidence_text(evidence_text)
    deliverable_class = contract.deliverable_class
    has_command_or_path = any(
        marker in normalized
        for marker in ("pytest", "mylittleharness", "project/verification/", "tests/", "src/", ".py", "status: ok", "exit 0")
    )
    if deliverable_class == "implementation":
        non_implementation_markers = ("audit only", "proposal only", "diagnostic only", "review only")
        implementation_markers = ("implemented", "changed", "tests/", "src/", "pytest", "product", "code")
        if any(marker in normalized for marker in non_implementation_markers) and not any(
            marker in normalized for marker in implementation_markers
        ):
            return "implementation closeout cites only audit/proposal/diagnostic evidence"
        return ""
    if deliverable_class in NON_IMPLEMENTATION_DELIVERABLE_CLASSES:
        missing_artifact_markers = (
            "artifact not produced",
            "artifact was not produced",
            "no artifact",
            "without artifact",
            "report not produced",
            "matrix not produced",
        )
        if any(marker in normalized for marker in missing_artifact_markers):
            return f"{deliverable_class} deliverable explicitly says the required artifact/report was not produced"
        class_markers = (
            deliverable_class,
            "artifact",
            "matrix",
            "report",
            "project/verification/",
            "route-by-route",
            "analysis",
        )
        if has_command_or_path and not any(marker in normalized for marker in class_markers):
            return f"{deliverable_class} deliverable cites implementation/test evidence without the required artifact or report proof"
    return ""


def _declared_target_evidence_findings(
    inventory: Inventory,
    closeout_values: dict[str, str],
    contract: AcceptanceEvidenceContract,
    *,
    completion_reason: str,
    severity: str,
    code_prefix: str,
) -> list[Finding]:
    findings: list[Finding] = []
    evidence_text = _acceptance_evidence_text(closeout_values)
    normalized = _normalized_evidence_text(evidence_text)
    for target in contract.target_artifacts:
        target_rel = _normalize_rel(target)
        if not _is_declared_evidence_target(target_rel):
            continue
        if _declared_evidence_target_exists(inventory, target_rel):
            if target_rel.casefold() not in normalized and Path(target_rel).name.casefold() not in normalized:
                findings.append(
                    Finding(
                        severity,
                        f"{code_prefix}-target-evidence-uncited",
                        (
                            f"{completion_reason} declares target_artifacts evidence target {target_rel}, but closeout "
                            "evidence does not cite that artifact path or filename"
                        ),
                        contract.source,
                    )
                )
            continue
        if _declared_target_substitution_recorded(inventory, closeout_values, target_rel):
            continue
        findings.append(
            Finding(
                severity,
                f"{code_prefix}-target-evidence-missing",
                (
                    f"{completion_reason} declares target_artifacts evidence target {target_rel}, but that artifact is "
                    "missing and closeout does not record a reviewed artifact substitution with before/after paths and "
                    "a residual-risk marker"
                ),
                contract.source,
            )
        )
    return findings


def _is_declared_evidence_target(rel_path: str) -> bool:
    normalized = _normalize_rel(rel_path).casefold()
    if not normalized.endswith(".md"):
        return False
    return any(normalized.startswith(prefix) for prefix in DECLARED_EVIDENCE_TARGET_PREFIXES)


def _declared_evidence_target_exists(inventory: Inventory, rel_path: str) -> bool:
    target = inventory.root / rel_path
    if _path_escapes_root(inventory.root, target):
        return False
    return target.is_file() and not target.is_symlink()


def _declared_target_substitution_recorded(
    inventory: Inventory,
    closeout_values: dict[str, str],
    target_rel: str,
) -> bool:
    evidence_text = _acceptance_evidence_text(closeout_values)
    normalized = _normalized_evidence_text(evidence_text)
    residual_risk = _normalized_evidence_text(closeout_values.get("residual_risk", ""))
    target_norm = _normalize_rel(target_rel).casefold()
    if target_norm not in normalized:
        return False
    if not any(marker in normalized for marker in DECLARED_TARGET_SUBSTITUTION_MARKERS):
        return False
    if not any(marker in residual_risk for marker in ("substitution", "substitute", "residual risk")):
        return False
    if "before" not in normalized or "after" not in normalized:
        return False
    for replacement in _route_markdown_paths(normalized):
        if replacement == target_norm:
            continue
        replacement_path = inventory.root / replacement
        if not _path_escapes_root(inventory.root, replacement_path) and replacement_path.is_file() and not replacement_path.is_symlink():
            return True
    return False


def _route_markdown_paths(text: str) -> tuple[str, ...]:
    paths = re.findall(r"project/[a-z0-9_./-]+\.md", text)
    return tuple(_dedupe_nonempty(_normalize_rel(path).casefold() for path in paths))


def _fan_in_review_disposition_missing_fields(
    inventory: Inventory,
    contract: AcceptanceEvidenceContract,
    evidence_text: str,
) -> tuple[str, ...]:
    if contract.deliverable_class != "fan-in-review":
        return ()
    corpus = _fan_in_review_evidence_corpus(inventory, contract, evidence_text)
    if not corpus.strip():
        return tuple(label for label, _markers in FAN_IN_REVIEW_REQUIRED_EVIDENCE_MARKERS)
    normalized = _normalized_fan_in_review_text(corpus)
    missing: list[str] = []
    for label, markers in FAN_IN_REVIEW_REQUIRED_EVIDENCE_MARKERS:
        if not any(marker in normalized for marker in markers):
            missing.append(label)
    return tuple(missing)


def _fan_in_review_evidence_corpus(
    inventory: Inventory,
    contract: AcceptanceEvidenceContract,
    evidence_text: str,
) -> str:
    parts = [str(evidence_text or "")]
    for target in contract.target_artifacts:
        rel = _normalize_rel(str(target or ""))
        if not rel.startswith(("project/verification/", "project/research/")):
            continue
        path = inventory.root / rel
        if _path_escapes_root(inventory.root, path) or not path.is_file():
            continue
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
    return "\n".join(part for part in parts if part)


def _normalized_fan_in_review_text(text: str) -> str:
    normalized = _normalized_evidence_text(text)
    return re.sub(r"[-_]+", " ", normalized)


def _docs_decision_residual_risk_mismatch(values: dict[str, str]) -> str:
    docs_decision = str(values.get("docs_decision") or "").strip().casefold()
    if docs_decision != "uncertain":
        return ""
    risk_text = _normalized_evidence_text(
        "\n".join(str(values.get(field) or "") for field in ("residual_risk", "carry_forward", "work_result"))
    )
    if any(marker in risk_text for marker in ("docs", "documentation", "uncertain", "provisional", "impact", "risk")):
        return ""
    return "docs_decision is uncertain, but residual_risk/carry_forward/work_result does not explain the uncertainty"


def _normalized_evidence_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("\\", "/").casefold())


def _closeout_writeback_plan(inventory: Inventory, request: WritebackRequest, archive_rel_path: str | None) -> CloseoutWritebackPlan:
    identity = _current_closeout_identity(inventory, archive_rel_path)
    if not request.closeout:
        archived_refresh_carry = _archived_plan_closeout_authority_carry_plan(inventory, request, identity)
        if archived_refresh_carry is not None:
            return archived_refresh_carry
        if request.archived_plan:
            source = request.archived_plan or DEFAULT_STATE_REL
            error = Finding(
                "error",
                "writeback-archived-plan-refresh-refused",
                (
                    "--archived-plan without explicit closeout fields found no complete matching project-state "
                    "or archived-plan closeout authority; supply complete closeout facts or refresh the matching "
                    "closeout authority first"
                ),
                source,
            )
            return CloseoutWritebackPlan({}, identity, "refuse", error.message, (error,))
        archive_carry = _archive_closeout_authority_carry_plan(inventory, request, identity)
        if archive_carry is not None:
            return archive_carry
        return CloseoutWritebackPlan({}, identity, "skipped", "no closeout facts were requested")
    if not _should_carry_current_closeout_values(request):
        values = _ordered_closeout_values(request.closeout)
        return CloseoutWritebackPlan(
            values,
            identity,
            "replace",
            "use same-request closeout facts only; existing project-state closeout facts are not carried",
        )

    current = {field: fact.value for field, fact in state_writeback_facts(inventory.state).items()}
    if not current:
        return CloseoutWritebackPlan(
            _ordered_closeout_values(request.closeout),
            identity,
            "replace",
            "start the current closeout block with same-request facts because no existing closeout facts were present",
        )

    existing_identity = _identity_from_facts(state_writeback_identity_facts(inventory.state))
    if not _identity_has_plan_anchor(identity):
        values = dict(current)
        values.update(request.closeout)
        return CloseoutWritebackPlan(
            _ordered_closeout_values(values),
            identity,
            "carry",
            "carry existing closeout facts because no active or archived plan identity is available for this closeout",
        )
    if _closeout_identity_matches(existing_identity, identity):
        values = dict(current)
        values.update(request.closeout)
        return CloseoutWritebackPlan(
            _ordered_closeout_values(values),
            identity,
            "carry",
            "carry existing closeout facts because recorded identity matches the current plan identity",
        )
    if closeout_values_are_complete(request.closeout):
        return CloseoutWritebackPlan(
            _ordered_closeout_values(request.closeout),
            identity,
            "replace",
            f"replace existing closeout facts because recorded identity {_closeout_identity_summary(existing_identity)} does not match current identity {_closeout_identity_summary(identity)}",
        )
    if _is_phase_only_uncertain_docs_writeback(request):
        message = (
            "replace existing closeout facts with same-request docs_decision uncertain for phase-only "
            "ready-for-closeout writeback; existing project-state closeout facts are not carried"
        )
        if _has_provisional_phase_evidence(request.closeout):
            message = (
                "replace existing closeout facts with same-request provisional phase evidence for phase-only "
                "lifecycle writeback; docs_decision remains uncertain and existing project-state closeout facts "
                "are not carried"
            )
        return CloseoutWritebackPlan(
            _ordered_closeout_values(request.closeout),
            identity,
            "replace",
            message,
        )

    source = inventory.state.rel_path if inventory.state else DEFAULT_STATE_REL
    error = Finding(
        "error",
        "writeback-closeout-identity-refused",
        "partial closeout writeback would carry existing facts without a matching plan identity; "
        f"recorded identity {_closeout_identity_summary(existing_identity)}; current identity {_closeout_identity_summary(identity)}; "
        "supply complete closeout facts with docs_decision updated/not-needed plus state_writeback, verification, and commit_decision to replace them",
        source,
    )
    return CloseoutWritebackPlan(_ordered_closeout_values(request.closeout), identity, "refuse", error.message, (error,))


def _archived_plan_closeout_authority_carry_plan(
    inventory: Inventory,
    request: WritebackRequest,
    identity: CloseoutIdentity,
) -> CloseoutWritebackPlan | None:
    if not request.archived_plan:
        return None
    if not _identity_has_plan_anchor(identity):
        return None

    current = {field: fact.value for field, fact in state_writeback_facts(inventory.state).items()}
    existing_identity = _identity_from_facts(state_writeback_identity_facts(inventory.state))
    if current and closeout_values_are_complete(current) and _closeout_identity_matches(existing_identity, identity):
        return CloseoutWritebackPlan(
            _ordered_closeout_values(current),
            identity,
            "carry",
            "carry matching project-state closeout authority into archived-plan refresh",
        )

    archived_surface = _archived_plan_surface(inventory, request.archived_plan)
    if archived_surface is None:
        return None
    archived_current = {field: fact.value for field, fact in state_writeback_facts(archived_surface).items()}
    if not archived_current:
        archived_current = {field: fact.value for field, fact in active_plan_body_facts(archived_surface).items()}
    archived_identity = _identity_from_facts(state_writeback_identity_facts(archived_surface))
    if (
        archived_current
        and closeout_values_are_complete(archived_current)
        and _closeout_identity_matches(archived_identity, identity)
    ):
        return CloseoutWritebackPlan(
            _ordered_closeout_values(archived_current),
            identity,
            "carry",
            "carry matching archived-plan closeout copy into project-state refresh",
        )
    return None


def _archive_closeout_authority_carry_plan(
    inventory: Inventory,
    request: WritebackRequest,
    identity: CloseoutIdentity,
) -> CloseoutWritebackPlan | None:
    if not request.archive_active_plan:
        return None
    if not _identity_has_plan_anchor(identity):
        return None

    current = {field: fact.value for field, fact in state_writeback_facts(inventory.state).items()}
    if not current or not closeout_values_are_complete(current):
        return None

    existing_identity = _identity_from_facts(state_writeback_identity_facts(inventory.state))
    if not _closeout_identity_matches(existing_identity, identity):
        return None

    return CloseoutWritebackPlan(
        _ordered_closeout_values(current),
        identity,
        "carry",
        (
            "carry matching project-state closeout authority into archive-active-plan writeback "
            "and retarget closeout identity to the archived plan"
        ),
    )


def _current_closeout_identity(inventory: Inventory, archive_rel_path: str | None) -> CloseoutIdentity:
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    active_plan = _normalize_rel(str(state_data.get("active_plan") or ""))
    archived_plan = _normalize_rel(str(archive_rel_path or ""))
    if not archived_plan and not active_plan:
        archived_plan = _normalize_rel(str(state_data.get("last_archived_plan") or ""))
    plan_id = ""
    plan = inventory.active_plan_surface
    if plan and plan.exists and plan.frontmatter.has_frontmatter and not plan.frontmatter.errors:
        plan_id = _normalized_value(plan.frontmatter.data.get("plan_id") or "")
    if not plan_id and archived_plan:
        plan_id = _archived_plan_id(inventory, archived_plan)
    return CloseoutIdentity(plan_id=plan_id, active_plan=active_plan, archived_plan=archived_plan)


def _archived_plan_id(inventory: Inventory, rel_path: str) -> str:
    path = inventory.root / _normalize_rel(rel_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    frontmatter = parse_frontmatter(text)
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return ""
    return _normalized_value(frontmatter.data.get("plan_id") or "")


def _identity_from_facts(facts: dict[str, WritebackFact]) -> CloseoutIdentity:
    return CloseoutIdentity(
        plan_id=facts["plan_id"].value if "plan_id" in facts else "",
        active_plan=_normalize_rel(facts["active_plan"].value) if "active_plan" in facts else "",
        archived_plan=_normalize_rel(facts["archived_plan"].value) if "archived_plan" in facts else "",
    )


def _identity_has_plan_anchor(identity: CloseoutIdentity) -> bool:
    return bool(identity.plan_id or identity.active_plan or identity.archived_plan)


def _closeout_identity_matches(existing: CloseoutIdentity, current: CloseoutIdentity) -> bool:
    if not _identity_has_plan_anchor(current):
        return True
    if not _identity_has_plan_anchor(existing):
        return False
    if current.plan_id and existing.plan_id != current.plan_id:
        return False
    active_match = bool(current.active_plan and existing.active_plan == current.active_plan)
    archived_match = bool(current.archived_plan and existing.archived_plan == current.archived_plan)
    if active_match or archived_match:
        return True
    return bool(current.plan_id and existing.plan_id == current.plan_id and not (current.active_plan or current.archived_plan))


def _ordered_closeout_values(values: dict[str, str]) -> dict[str, str]:
    ordered = {field: values[field] for field in CLOSEOUT_WRITEBACK_FIELDS if field in values and values[field]}
    if ordered and "work_result" not in ordered:
        capsule = work_result_capsule_from_closeout_values(ordered)
        if capsule is not None:
            ordered["work_result"] = render_work_result_capsule_line(capsule)
    return {field: ordered[field] for field in CLOSEOUT_WRITEBACK_FIELDS if field in ordered}


def _closeout_writeback_plan_findings(plan: CloseoutWritebackPlan, apply: bool) -> list[Finding]:
    if plan.decision == "skipped":
        return []
    prefix = "" if apply else "would "
    code = {
        "carry": "writeback-closeout-carry",
        "replace": "writeback-closeout-replace",
        "refuse": "writeback-closeout-identity-refused",
    }.get(plan.decision, "writeback-closeout-identity")
    return [
        Finding(
            "info",
            "writeback-closeout-identity",
            f"{prefix}record closeout identity: {_closeout_identity_summary(plan.identity)}",
            DEFAULT_STATE_REL,
        ),
        Finding("info", code, f"{prefix}{plan.message}", DEFAULT_STATE_REL),
    ]


def _closeout_identity_summary(identity: CloseoutIdentity) -> str:
    parts = [
        f"plan_id={identity.plan_id!r}",
        f"active_plan={identity.active_plan!r}",
        f"archived_plan={identity.archived_plan!r}",
    ]
    return ", ".join(parts)


def _planned_lifecycle_values(request: WritebackRequest, archive_rel_path: str | None, archive_phase_status: str = "") -> dict[str, str]:
    values = dict(request.lifecycle)
    if archive_rel_path:
        values.update({"plan_status": "none", "active_plan": "", "last_archived_plan": archive_rel_path})
        if archive_phase_status and archive_phase_status != "complete":
            values.setdefault("phase_status", archive_phase_status)
    return values


def _phase_execution_boundary_finding(lifecycle_values: dict[str, str], source: str | None, apply: bool) -> Finding:
    verb = "updated" if apply else "would update"
    fields = ", ".join(lifecycle_values) or "lifecycle fields"
    return Finding(
        "info",
        "writeback-phase-execution-boundary",
        f"{verb} {fields} only; lifecycle writeback does not authorize auto_continue, closeout, archive, commit, or next-slice movement",
        source,
    )


def _phase_advancement_finding(inventory: Inventory, lifecycle_values: dict[str, str], source: str | None, apply: bool) -> Finding | None:
    completed_phase = _phase_advancement_completed_phase(inventory, lifecycle_values)
    next_phase = lifecycle_values.get("active_phase", "")
    if not completed_phase or not next_phase:
        return None
    verb = "completed" if apply else "would complete"
    return Finding(
        "info",
        "writeback-phase-advancement",
        (
            f"{verb} active-plan phase block {completed_phase!r} and advance project-state active_phase to {next_phase!r} "
            "with phase_status pending in one lifecycle writeback; this does not authorize auto_continue, closeout, archive, "
            "roadmap done-status, next-plan opening, staging, or commit"
        ),
        source,
    )


def _ready_for_closeout_boundary_finding(lifecycle_values: dict[str, str], source: str | None, apply: bool) -> Finding | None:
    if lifecycle_values.get("phase_status") != "complete":
        return None
    verb = "updated" if apply else "would update"
    return Finding(
        "info",
        "writeback-ready-for-closeout-boundary",
        (
            f"{verb} phase_status complete as a ready-for-closeout state only; "
            "explicit --archive-active-plan is required to archive the plan, default roadmap items to done, "
            "or move the lifecycle past the active plan"
        ),
        source,
    )


def _auto_compaction_boundary_findings(
    request: WritebackRequest,
    lifecycle_values: dict[str, str],
    compaction_plan: StateCompactionPlan,
    apply: bool,
) -> list[Finding]:
    if not lifecycle_values or not request.lifecycle or compaction_plan.posture != "would run":
        return []
    if request.allow_auto_compaction:
        verb = "authorized" if apply else "would authorize"
        return [
            Finding(
                "info",
                "writeback-auto-compaction-authorized",
                (
                    f"{verb} project-state auto-compaction after explicit lifecycle writeback because "
                    "--allow-auto-compaction was supplied; compact-only maintenance, archive, roadmap status, "
                    "staging, commit, and next-plan opening remain separate decisions"
                ),
                DEFAULT_STATE_REL,
            )
        ]
    severity = "error" if apply else "warn"
    verb = "refused" if apply else "would refuse"
    return [
        Finding(
            severity,
            "writeback-auto-compaction-boundary",
            (
                f"{verb} lifecycle writeback before writing files because project-state auto-compaction would run; "
                "rerun with --allow-auto-compaction after reviewing the dry-run, or run writeback --compact-only "
                "as a separate reviewed maintenance step"
            ),
            DEFAULT_STATE_REL,
        )
    ]


def _planned_closeout_finding(values: dict[str, str]) -> Finding:
    summary = ", ".join(f"{field}={values[field]!r}" for field in CLOSEOUT_WRITEBACK_FIELDS if field in values)
    return Finding("info", "writeback-closeout-fields", f"closeout writeback fields: {summary or 'none'}", "project/project-state.md")


def _writeback_roadmap_plan(inventory: Inventory, request: WritebackRequest, archive_rel_path: str | None) -> tuple[RoadmapWritebackPlan | None, list[Finding]]:
    if not request.roadmap_item:
        return None, []
    if not archive_rel_path and (not inventory.active_plan_surface or not inventory.active_plan_surface.exists):
        return None, [
            Finding(
                "error",
                "writeback-refused",
                "--roadmap-item requires a readable active plan or explicit --archived-plan so roadmap closeout sync is target-bound",
                DEFAULT_PLAN_REL,
            )
        ]
    roadmap_status = request.roadmap_status or ("done" if archive_rel_path else "")
    related_plan = archive_rel_path or DEFAULT_PLAN_REL
    roadmap_requests = tuple(
        make_roadmap_request(
            "update",
            item_id,
            status=roadmap_status,
            related_plan=related_plan,
            archived_plan=archive_rel_path or "",
            verification_summary=request.closeout.get("verification", ""),
            docs_decision=request.closeout.get("docs_decision", ""),
            carry_forward=_roadmap_carry_forward_value(request.closeout),
        )
        for item_id in _writeback_roadmap_item_ids(inventory, request)
    )
    allowed_missing_paths = {related_plan}
    if archive_rel_path:
        allowed_missing_paths.add(archive_rel_path)
    plans, errors = roadmap_plans_for_requests(inventory, roadmap_requests, allowed_missing_paths=allowed_missing_paths)
    if errors:
        return None, errors
    if not plans:
        return None, []
    active_item_ids = () if archive_rel_path else active_plan_roadmap_item_ids(inventory)
    plans = _writeback_roadmap_plans_with_current_posture(plans, active_item_ids=active_item_ids)
    return RoadmapWritebackPlan(target_rel=plans[-1].target_rel, target_path=plans[-1].target_path, item_plans=plans), []


def _writeback_roadmap_item_ids(inventory: Inventory, request: WritebackRequest) -> tuple[str, ...]:
    requested = _normalized_item_id(request.roadmap_item)
    if not requested:
        return ()
    plan = inventory.active_plan_surface
    if not plan or not plan.exists or not plan.frontmatter.has_frontmatter:
        return (requested,)
    data = plan.frontmatter.data
    primary = _normalized_item_id(data.get("primary_roadmap_item") or data.get("related_roadmap_item"))
    covered = tuple(_dedupe_nonempty(_frontmatter_item_list(data.get("covered_roadmap_items"))))
    if covered and requested in {*covered, primary}:
        return tuple(_dedupe_nonempty((requested, *covered)))
    return (requested,)


def _writeback_batch_slice_gate_findings(inventory: Inventory, request: WritebackRequest, *, apply: bool) -> list[Finding]:
    return roadmap_batch_slice_gate_findings(
        inventory,
        _writeback_roadmap_item_ids(inventory, request),
        route="writeback",
        source=DEFAULT_PLAN_REL,
        apply=apply,
    )


def _roadmap_writeback_tmp(plan: RoadmapWritebackPlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.writeback.tmp")


def _roadmap_writeback_backup(plan: RoadmapWritebackPlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.writeback.backup")


def _roadmap_writeback_plan_with_updated_text(plan: RoadmapWritebackPlan, updated_text: str) -> RoadmapWritebackPlan:
    if not plan.item_plans:
        return plan
    item_plans = (*plan.item_plans[:-1], replace(plan.item_plans[-1], updated_text=updated_text))
    return replace(plan, item_plans=item_plans)


def _writeback_roadmap_plans_with_current_posture(
    plans: tuple[RoadmapPlan, ...],
    *,
    active_item_ids: tuple[str, ...] = (),
) -> tuple[RoadmapPlan, ...]:
    if not plans:
        return plans
    last = plans[-1]
    updated_text, retargeted_item_ids = roadmap_text_with_terminal_related_plan_retargets(
        last.updated_text,
        active_item_ids=active_item_ids,
    )
    changed_fields = last.changed_fields
    if updated_text != last.updated_text:
        changed_fields = tuple(_dedupe_nonempty((*changed_fields, TERMINAL_RELATED_PLAN_RETARGET_FIELD)))

    refreshed_text = sync_roadmap_current_posture_section(updated_text)
    if refreshed_text != updated_text:
        changed_fields = tuple(_dedupe_nonempty((*changed_fields, ROADMAP_CURRENT_POSTURE_FIELD)))
        updated_text = refreshed_text

    if updated_text == last.updated_text and not retargeted_item_ids:
        return plans
    return (
        *plans[:-1],
        replace(
            last,
            updated_text=updated_text,
            changed_fields=changed_fields,
            retargeted_terminal_item_ids=tuple(_dedupe_nonempty((*last.retargeted_terminal_item_ids, *retargeted_item_ids))),
        ),
    )


def _roadmap_carry_forward_value(closeout: dict[str, str]) -> str:
    parts: list[str] = []
    if closeout.get("residual_risk"):
        parts.append(f"Residual risk: {closeout['residual_risk']}")
    if closeout.get("carry_forward"):
        parts.append(f"Carry-forward: {closeout['carry_forward']}")
    return "; ".join(parts)


def _frontmatter_item_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [_normalized_item_id(item) for item in value]
    normalized = _normalized_item_id(value)
    return [normalized] if normalized else []


def _dedupe_nonempty(values) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _writeback_roadmap_findings(plan: RoadmapWritebackPlan, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    changed_plans = tuple(item_plan for item_plan in plan.item_plans if item_plan.changed_fields)
    action = "updated" if apply and changed_plans else "checked" if apply else "would update"
    findings = [
        Finding("info", "writeback-roadmap-sync", f"{action} roadmap item(s) {list(plan.item_ids)!r} with selected writeback facts", plan.target_rel),
        Finding("info", "writeback-roadmap-target", f"{prefix}write roadmap sync target: {plan.target_rel}", plan.target_rel),
    ]
    if changed_plans:
        for item_plan in plan.item_plans:
            findings.extend(
                Finding(
                    "info",
                    "writeback-roadmap-changed-field",
                    f"{prefix}change roadmap item {item_plan.item_id!r} field: {field}",
                    plan.target_rel,
                )
                for field in item_plan.changed_fields
            )
    else:
        findings.append(Finding("info", "writeback-roadmap-noop", "roadmap item(s) already match selected writeback facts", plan.target_rel))
    retargeted = tuple(_dedupe_nonempty(item_id for item_plan in plan.item_plans for item_id in item_plan.retargeted_terminal_item_ids))
    if retargeted:
        findings.append(
            Finding(
                "info",
                "writeback-roadmap-terminal-retarget",
                f"{prefix}retarget terminal roadmap related_plan link(s): {', '.join(retargeted)}",
                plan.target_rel,
            )
        )
    findings.append(
        Finding(
            "info",
            "writeback-roadmap-boundary",
            "roadmap sync is separate from lifecycle and archive writes and bounded to the requested item plus covered_roadmap_items from the active plan; roadmap output cannot approve closeout, archive, commit, rollback, repair, or lifecycle decisions",
            plan.target_rel,
        )
    )
    return findings


def _projected_active_plan_text(
    inventory: Inventory,
    closeout_values: dict[str, str],
    lifecycle_values: dict[str, str],
    *,
    completed_phase: str,
) -> str | None:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return None
    active_phase = _requested_or_current_active_phase(inventory, lifecycle_values)
    text, _findings = _active_plan_text_with_synced_values(
        plan,
        closeout_values,
        lifecycle_values,
        active_phase,
        completed_phase,
    )
    return text


def _with_incubation_archive_replacements(
    state_text: str,
    active_plan_text: str | None,
    roadmap_plan: RoadmapWritebackPlan | None,
    route_retarget_plans: tuple[RouteRetargetPlan, ...],
    incubation_plan: RelationshipUpdatePlan | None,
) -> tuple[str, str | None, RoadmapWritebackPlan | None, tuple[RouteRetargetPlan, ...]]:
    if not incubation_plan or not incubation_plan.archive_rel:
        return state_text, active_plan_text, roadmap_plan, route_retarget_plans
    state_text = state_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel)
    if active_plan_text is not None:
        active_plan_text = active_plan_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel)
    if roadmap_plan:
        roadmap_plan = _roadmap_writeback_plan_with_updated_text(
            roadmap_plan,
            roadmap_plan.updated_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel),
        )
    route_retarget_plans = tuple(
        _route_retarget_plan_with_updated_text(plan, plan.updated_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel))
        for plan in route_retarget_plans
    )
    return state_text, active_plan_text, roadmap_plan, route_retarget_plans


def _writeback_route_write_evidence(
    inventory: Inventory,
    state_text: str,
    active_plan_text: str | None,
    roadmap_plan: RoadmapWritebackPlan | None,
    incubation_plan: RelationshipUpdatePlan | None,
    route_retarget_plans: tuple[RouteRetargetPlan, ...],
    archive_plan: ArchivePlan | None,
    archive_plan_text: str | None,
    archived_refresh_plan: ArchivedPlanRefreshPlan | None = None,
) -> tuple[RouteWriteEvidence, ...]:
    writes: list[RouteWriteEvidence] = []
    if inventory.state:
        writes.append(RouteWriteEvidence(inventory.state.rel_path, inventory.state.content, state_text))
    if archive_plan:
        writes.append(RouteWriteEvidence(archive_plan.archive_rel_path, archive_plan.existing_archive_text, archive_plan_text))
        writes.append(RouteWriteEvidence(archive_plan.plan.rel_path, archive_plan.plan.content, None))
    elif archived_refresh_plan:
        writes.append(
            RouteWriteEvidence(
                archived_refresh_plan.surface.rel_path,
                archived_refresh_plan.surface.content,
                archived_refresh_plan.updated_text,
            )
        )
    elif active_plan_text is not None and inventory.active_plan_surface and inventory.active_plan_surface.exists:
        writes.append(RouteWriteEvidence(inventory.active_plan_surface.rel_path, inventory.active_plan_surface.content, active_plan_text))
    if roadmap_plan:
        writes.append(RouteWriteEvidence(roadmap_plan.target_rel, roadmap_plan.current_text, roadmap_plan.updated_text))
    if incubation_plan:
        writes.extend(_relationship_route_write_evidence(incubation_plan))
    writes.extend(
        RouteWriteEvidence(plan.source_rel, plan.current_text, plan.updated_text)
        for plan in route_retarget_plans
    )
    return tuple(writes)


def _writeback_route_write_findings(
    inventory: Inventory,
    state_text: str,
    active_plan_text: str | None,
    roadmap_plan: RoadmapWritebackPlan | None,
    incubation_plan: RelationshipUpdatePlan | None,
    route_retarget_plans: tuple[RouteRetargetPlan, ...],
    archive_plan: ArchivePlan | None,
    archive_plan_text: str | None,
    archived_refresh_plan: ArchivedPlanRefreshPlan | None = None,
    *,
    apply: bool,
) -> list[Finding]:
    writes = _writeback_route_write_evidence(
        inventory,
        state_text,
        active_plan_text,
        roadmap_plan,
        incubation_plan,
        route_retarget_plans,
        archive_plan,
        archive_plan_text,
        archived_refresh_plan,
    )
    findings = [
        *_writeback_route_write_report_findings(
            writes,
            apply=apply,
            archive_plan=archive_plan,
            incubation_plan=incubation_plan,
        ),
        *route_reference_transaction_guard_findings(inventory, writes, apply=apply),
    ]
    if archived_refresh_plan and not _route_writes_have_changes(writes):
        findings.append(_archived_plan_already_closed_finding(archived_refresh_plan.surface.rel_path, apply=apply))
    return findings


def _route_writes_have_changes(writes: tuple[RouteWriteEvidence, ...]) -> bool:
    return any(write.before_text != write.after_text for write in writes)


def _writeback_route_write_report_findings(
    writes: tuple[RouteWriteEvidence, ...],
    *,
    apply: bool,
    archive_plan: ArchivePlan | None = None,
    incubation_plan: RelationshipUpdatePlan | None = None,
) -> list[Finding]:
    findings = route_write_findings("writeback-route-write", writes, apply=apply)
    if not archive_plan:
        return findings

    changed_writes = tuple(write for write in writes if write.before_text != write.after_text)
    annotated: list[Finding] = []
    for index, finding in enumerate(findings):
        write = changed_writes[index] if index < len(changed_writes) else None
        annotated.append(_archive_route_write_context_finding(finding, write, archive_plan, incubation_plan))
    return annotated


def _archive_route_write_context_finding(
    finding: Finding,
    write: RouteWriteEvidence | None,
    archive_plan: ArchivePlan,
    incubation_plan: RelationshipUpdatePlan | None,
) -> Finding:
    if write is None:
        return finding
    transaction_stage, final_state = _archive_route_write_context(write, archive_plan, incubation_plan)
    if not transaction_stage:
        return finding
    context = f"transaction_stage={transaction_stage}; final_state={final_state}"
    if "; before_hash=" in finding.message:
        message = finding.message.replace("; before_hash=", f"; {context}; before_hash=", 1)
    else:
        message = f"{finding.message}; {context}"
    return Finding(finding.severity, finding.code, message, finding.source, finding.line)


def _archive_route_write_context(
    write: RouteWriteEvidence,
    archive_plan: ArchivePlan,
    incubation_plan: RelationshipUpdatePlan | None,
) -> tuple[str, str]:
    rel_path = _normalize_rel(write.rel_path)
    link_repair_rels = {_normalize_rel(rel_path) for rel_path, _path, _text in (incubation_plan.link_repairs if incubation_plan else ())}
    if rel_path in link_repair_rels:
        return "archive-link-repair", "source-incubation-reference-retargeted"
    if rel_path == DEFAULT_STATE_REL:
        return "archive-final-state", "project-state-lifecycle-closed"
    if rel_path == _normalize_rel(archive_plan.archive_rel_path):
        if write.before_text is None:
            return "archive-final-state", "archived-plan-route-created"
        return "archive-final-state", "archived-plan-route-reused"
    if rel_path == _normalize_rel(archive_plan.plan.rel_path) and write.after_text is None:
        return "archive-final-state", "active-plan-route-deleted"
    if incubation_plan and rel_path == _normalize_rel(incubation_plan.target_rel) and write.before_text is None:
        return "archive-final-state", "source-incubation-archive-created"
    if incubation_plan and rel_path == _normalize_rel(incubation_plan.source_rel) and write.after_text is None:
        return "archive-final-state", "source-incubation-live-route-deleted"
    if rel_path == "project/roadmap.md":
        return "archive-final-state", "roadmap-closeout-synced"
    return "archive-final-state", "route-updated"


def _relationship_plan_without_subsumed_link_repairs(
    plan: RelationshipUpdatePlan | None,
    skip_rels: tuple[str, ...],
) -> RelationshipUpdatePlan | None:
    if plan is None or not plan.link_repairs or not skip_rels:
        return plan
    skip = {_normalize_rel(rel_path) for rel_path in skip_rels}
    link_repairs = tuple(repair for repair in plan.link_repairs if _normalize_rel(repair[0]) not in skip)
    if link_repairs == plan.link_repairs:
        return plan
    return replace(plan, link_repairs=link_repairs)


def _writeback_subsumed_link_repair_rels(
    inventory: Inventory,
    active_plan_text: str | None,
    roadmap_plan: RoadmapWritebackPlan | None,
    route_retarget_plans: tuple[RouteRetargetPlan, ...],
    archive_plan: ArchivePlan | None,
    archived_refresh_plan: ArchivedPlanRefreshPlan | None,
) -> tuple[str, ...]:
    rels: set[str] = set()
    if inventory.state:
        rels.add(inventory.state.rel_path)
    if archive_plan:
        rels.add(archive_plan.plan.rel_path)
        rels.add(archive_plan.archive_rel_path)
    elif active_plan_text is not None and inventory.active_plan_surface and inventory.active_plan_surface.exists:
        rels.add(inventory.active_plan_surface.rel_path)
    if roadmap_plan:
        rels.add(roadmap_plan.target_rel)
    if archived_refresh_plan:
        rels.add(archived_refresh_plan.surface.rel_path)
    rels.update(plan.source_rel for plan in route_retarget_plans)
    return tuple(sorted(_normalize_rel(rel_path) for rel_path in rels if rel_path))


def _relationship_route_write_evidence(plan: RelationshipUpdatePlan) -> list[RouteWriteEvidence]:
    writes: list[RouteWriteEvidence] = []
    if plan.archive_rel:
        writes.append(RouteWriteEvidence(plan.target_rel, None, plan.updated_text))
        writes.append(RouteWriteEvidence(plan.source_rel, plan.current_text, None))
    else:
        writes.append(RouteWriteEvidence(plan.target_rel, plan.current_text, plan.updated_text))
    writes.extend(_link_repair_route_write_evidence(plan.link_repairs))
    return writes


def _link_repair_route_write_evidence(link_repairs: tuple[tuple[str, Path, str], ...]) -> list[RouteWriteEvidence]:
    writes: list[RouteWriteEvidence] = []
    for rel_path, path, updated_text in link_repairs:
        writes.append(RouteWriteEvidence(rel_path, _read_route_text(path), updated_text))
    return writes


def _read_route_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _writeback_incubation_plan(
    inventory: Inventory,
    request: WritebackRequest,
    archive_rel_path: str | None,
) -> tuple[RelationshipUpdatePlan | None, list[Finding]]:
    if not request.roadmap_item or not archive_rel_path:
        return None, []
    fields = roadmap_item_fields(inventory, request.roadmap_item)
    source_incubation = _normalize_rel(str(fields.get("source_incubation") or ""))
    if not source_incubation:
        return None, []
    if source_incubation.startswith(f"{ARCHIVE_INCUBATION_DIR_REL}/"):
        return relationship_update_plan(
            inventory,
            source_incubation,
            {
                "related_roadmap": "project/roadmap.md",
                "related_roadmap_item": request.roadmap_item,
                "related_plan": archive_rel_path,
                "archived_plan": archive_rel_path,
                "implemented_by": archive_rel_path,
                "verification_summary": request.closeout.get("verification", ""),
                "docs_decision": request.closeout.get("docs_decision", ""),
            },
        )
    if request.archived_plan:
        return relationship_update_plan(
            inventory,
            source_incubation,
            {
                "related_roadmap": "project/roadmap.md",
                "related_roadmap_item": request.roadmap_item,
                "related_plan": archive_rel_path,
                "archived_plan": archive_rel_path,
                "implemented_by": archive_rel_path,
                "verification_summary": request.closeout.get("verification", ""),
                "docs_decision": request.closeout.get("docs_decision", ""),
            },
        )
    live_consumers = roadmap_source_incubation_consumers(inventory, source_incubation, live_only=True)
    extra_blockers: tuple[str, ...] = ()
    if len(live_consumers) > 1:
        extra_blockers = (
            "shared live source_incubation consumers: " + ", ".join(live_consumers),
        )
    return incubation_closeout_plan(
        inventory,
        source_incubation,
        roadmap_item=request.roadmap_item,
        archived_plan=archive_rel_path,
        verification_summary=request.closeout.get("verification", ""),
        docs_decision=request.closeout.get("docs_decision", ""),
        extra_archive_blockers=extra_blockers,
    )


def _writeback_incubation_findings(plan: RelationshipUpdatePlan, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding("info", "writeback-incubation-sync", f"{prefix}sync source incubation relationship metadata", plan.source_rel),
        Finding("info", "writeback-incubation-target", f"{prefix}write source incubation target: {plan.target_rel}", plan.target_rel),
    ]
    if plan.changed_fields:
        findings.extend(
            Finding("info", "writeback-incubation-changed-field", f"{prefix}change source incubation field: {field}", plan.source_rel)
            for field in plan.changed_fields
        )
    else:
        findings.append(Finding("info", "writeback-incubation-noop", "source incubation relationship metadata already matches same-request closeout facts", plan.source_rel))
    if plan.archive_blockers:
        findings.append(
            Finding(
                "warn",
                "writeback-incubation-archive-blocked",
                f"source incubation was not auto-archived because: {', '.join(plan.archive_blockers)}",
                plan.source_rel,
            )
        )
        findings.extend(_writeback_incubation_archive_retry_findings(plan))
    elif plan.archive_rel:
        findings.append(Finding("info", "writeback-incubation-auto-archive", f"{prefix}archive fully covered source incubation to {plan.archive_rel}", plan.archive_rel))
    if plan.link_repairs:
        findings.append(Finding("info", "writeback-incubation-link-repair", f"{prefix}repair exact source-incubation links in {len(plan.link_repairs)} file(s)", plan.archive_rel or plan.source_rel))
    findings.append(
        Finding(
            "info",
            "writeback-incubation-boundary",
            "incubation relationship writeback uses only the roadmap item's explicit source_incubation and same-request closeout facts; mixed notes stay active",
            plan.source_rel,
        )
    )
    return findings


def _writeback_incubation_archive_retry_findings(plan: RelationshipUpdatePlan) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "writeback-incubation-archive-evaluation",
            (
                "source-incubation archive eligibility was evaluated against same-request closeout facts after planned "
                "relationship metadata sync; remaining blockers are operating-memory hygiene, not lifecycle refusal"
            ),
            plan.source_rel,
        )
    ]
    report = incubation_entry_coverage_report(plan.updated_text)
    if report.entries:
        entry_ids = tuple(entry.entry_id for entry in report.entries)
        coverage_by_id = {record.entry_id: record for record in report.coverage}
        terminal_ids = tuple(
            record.entry_id
            for record in report.coverage
            if record.entry_id in entry_ids and record.status in {"implemented", "rejected", "superseded", "merged", "split", "archived"} and record.detail
        )
        missing_ids = tuple(entry_id for entry_id in entry_ids if entry_id not in coverage_by_id)
        open_ids = tuple(
            record.entry_id
            for record in report.coverage
            if record.entry_id in entry_ids and record.entry_id not in terminal_ids
        )
        parts = [f"valid entry ids: {', '.join(entry_ids)}"]
        if terminal_ids:
            parts.append(f"terminal entry ids: {', '.join(terminal_ids)}")
        if missing_ids:
            parts.append(f"missing entry ids: {', '.join(missing_ids)}")
        if open_ids:
            parts.append(f"non-terminal entry ids: {', '.join(open_ids)}")
        if report.errors:
            parts.append(f"malformed entry coverage: {'; '.join(report.errors)}")
        findings.append(
            Finding(
                "info",
                "writeback-incubation-entry-coverage-report",
                "; ".join(parts),
                plan.source_rel,
            )
        )
    if plan.source_rel.startswith("project/plan-incubation/"):
        retry_command = _writeback_incubation_archive_retry_command(plan, report)
        findings.append(
            Finding(
                "info",
                "writeback-incubation-archive-retry",
                (
                    "review retry after adding terminal Entry Coverage where needed: "
                    f"{retry_command}"
                ),
                plan.source_rel,
            )
        )
    return findings


def _writeback_incubation_archive_retry_command(plan: RelationshipUpdatePlan, report) -> str:
    parts: list[object] = [
        "memory-hygiene",
        "--dry-run",
        "--source",
        plan.source_rel,
        "--archive-covered",
        "--repair-links",
    ]
    entry_ids = tuple(entry.entry_id for entry in report.entries)
    if not entry_ids:
        return mlh_command(*parts)
    covered_ids = {record.entry_id for record in report.coverage}
    destination = _writeback_incubation_retry_destination(plan)
    for entry_id in entry_ids:
        if entry_id in covered_ids:
            continue
        parts.extend(("--entry-coverage", safe_double_quoted(f"{entry_id}: implemented via {destination}")))
    return mlh_command(*parts)


def _writeback_incubation_retry_destination(plan: RelationshipUpdatePlan) -> str:
    frontmatter = parse_frontmatter(plan.updated_text)
    archived_plan = _normalize_rel(str(frontmatter.data.get("archived_plan") or ""))
    return archived_plan or "<destination>"


def _incubation_writeback_tmp(plan: RelationshipUpdatePlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.writeback-incubation.tmp")


def _incubation_writeback_backup(plan: RelationshipUpdatePlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.writeback-incubation.backup")


def _incubation_source_backup(plan: RelationshipUpdatePlan | None) -> Path | None:
    if plan is None or not plan.archive_rel:
        return None
    return plan.source_path.with_name(f".{plan.source_path.name}.writeback-incubation.backup")


def _incubation_link_tmp_paths(plan: RelationshipUpdatePlan | None) -> list[tuple[Path, Path, Path, str]]:
    if plan is None:
        return []
    return [
        (
            path.with_name(f".{path.name}.writeback-incubation.tmp"),
            path.with_name(f".{path.name}.writeback-incubation.backup"),
            path,
            text,
        )
        for _rel, path, text in plan.link_repairs
    ]


def _incubation_plan_source_rels(plan: RelationshipUpdatePlan | None) -> tuple[str, ...]:
    if plan is None:
        return ()
    return (plan.source_rel,)


def _archive_route_retarget_plans(
    inventory: Inventory,
    archive_rel_path: str,
    *,
    skip_rels: tuple[str, ...] = (),
) -> tuple[RouteRetargetPlan, ...]:
    archive_rel_path = _normalize_rel(archive_rel_path)
    if not archive_rel_path:
        return ()
    skip = {DEFAULT_STATE_REL, DEFAULT_PLAN_REL, "project/roadmap.md", *skip_rels}
    plans: list[RouteRetargetPlan] = []
    for surface in inventory.present_surfaces:
        if surface.rel_path in skip or surface.rel_path.startswith("project/archive/"):
            continue
        if surface.memory_route not in {"research", "incubation", "verification", "decisions", "adrs", "stable-specs"}:
            continue
        if surface.path.suffix.lower() != ".md" or not surface.frontmatter.has_frontmatter or surface.frontmatter.errors:
            continue
        updates = _archive_route_retarget_updates(surface, archive_rel_path)
        if not updates:
            continue
        updated_text = _update_frontmatter_scalars(surface.content, updates, only_existing=False)
        changed_fields = tuple(
            field
            for field, value in updates.items()
            if _frontmatter_value(surface.content, field) != value and _frontmatter_value(updated_text, field) == value
        )
        if changed_fields:
            plans.append(
                RouteRetargetPlan(
                    source_rel=surface.rel_path,
                    target_path=surface.path,
                    current_text=surface.content,
                    updated_text=updated_text,
                    changed_fields=changed_fields,
                )
            )
    return tuple(plans)


def _archive_route_retarget_updates(surface: Surface, archive_rel_path: str) -> dict[str, str]:
    data = surface.frontmatter.data
    updates: dict[str, str] = {}
    related_plan = _normalize_rel(str(data.get("related_plan") or ""))
    if related_plan == DEFAULT_PLAN_REL:
        updates["related_plan"] = archive_rel_path
        updates.update(_archive_route_implementation_updates(surface, archive_rel_path, add_missing=True))
        return updates
    updates.update(_archive_route_implementation_updates(surface, archive_rel_path, add_missing=False))
    return updates


def _archive_route_implementation_updates(surface: Surface, archive_rel_path: str, *, add_missing: bool) -> dict[str, str]:
    if surface.memory_route == "incubation" and not _incubation_route_has_implementation_coverage(surface):
        return _unproven_incubation_implementation_field_updates(surface, archive_rel_path)

    data = surface.frontmatter.data
    updates: dict[str, str] = {}
    for field in ("archived_plan", "implemented_by"):
        value = _normalize_rel(str(data.get(field) or ""))
        if value == DEFAULT_PLAN_REL or (add_missing and value == ""):
            updates[field] = archive_rel_path
    return updates


def _unproven_incubation_implementation_field_updates(surface: Surface, archive_rel_path: str) -> dict[str, str]:
    updates: dict[str, str] = {}
    for field in ("archived_plan", "implemented_by"):
        value = _normalize_rel(str(surface.frontmatter.data.get(field) or ""))
        if value in {DEFAULT_PLAN_REL, archive_rel_path}:
            updates[field] = ""
    return updates


def _incubation_route_has_implementation_coverage(surface: Surface) -> bool:
    report = incubation_entry_coverage_report(surface.content)
    if not report.entries or report.errors:
        return False
    coverage_by_id = {record.entry_id: record for record in report.coverage}
    for entry in report.entries:
        record = coverage_by_id.get(entry.entry_id)
        if record is None or record.status != "implemented" or not record.detail:
            return False
    return True


def _route_retarget_plan_with_updated_text(plan: RouteRetargetPlan, updated_text: str) -> RouteRetargetPlan:
    return replace(plan, updated_text=updated_text)


def _archive_route_retarget_findings(plans: tuple[RouteRetargetPlan, ...], apply: bool) -> list[Finding]:
    if not plans:
        return []
    prefix = "" if apply else "would "
    findings = [
        Finding(
            "info",
            "writeback-route-retarget",
            f"{prefix}retarget archive relationship metadata in {len(plans)} route file(s)",
        )
    ]
    for plan in plans:
        for field in plan.changed_fields:
            findings.append(
                Finding(
                    "info",
                    "writeback-route-retarget-field",
                    f"{prefix}change {plan.source_rel} frontmatter field: {field}",
                    plan.source_rel,
                )
            )
    findings.append(
        Finding(
            "info",
            "writeback-route-retarget-boundary",
            "archive relationship retargeting updates only MLH route frontmatter that pointed at the active plan; it does not rewrite historical archives or approve lifecycle decisions",
        )
    )
    return findings


def _state_compaction_plan(inventory: Inventory, state_text: str) -> StateCompactionPlan:
    state = inventory.state
    line_count = len(state_text.splitlines())
    char_count = len(state_text)
    source_hash = _sha256_text(state_text)
    trigger_reason = _state_compaction_trigger_reason(line_count, char_count)
    if not trigger_reason:
        return StateCompactionPlan(
            posture="skipped",
            reason=(
                f"project/project-state.md is {line_count} lines, {char_count} chars; "
                f"default trigger is > {STATE_COMPACTION_LINE_THRESHOLD} lines or > {STATE_COMPACTION_CHAR_THRESHOLD} chars"
            ),
            source_hash=source_hash,
        )
    if inventory.root_kind != "live_operating_root":
        return StateCompactionPlan("refused", f"target root kind is {inventory.root_kind}; auto-compaction requires a live operating root", source_hash=source_hash)
    if state is None or not state.exists:
        return StateCompactionPlan("refused", "project/project-state.md is missing", source_hash=source_hash)
    if state.rel_path != DEFAULT_STATE_REL:
        return StateCompactionPlan("refused", f"unsafe state path for auto-compaction: {state.rel_path}", source_hash=source_hash)
    if _path_escapes_root(inventory.root, state.path):
        return StateCompactionPlan("refused", "project-state path escapes the target root", source_hash=source_hash)
    if not state.path.is_file():
        return StateCompactionPlan("refused", "project-state.md is not a regular file", source_hash=source_hash)
    if state.path.is_symlink():
        return StateCompactionPlan("refused", "project-state.md is a symlink", source_hash=source_hash)
    if not state.frontmatter.has_frontmatter or state.frontmatter.errors:
        return StateCompactionPlan("refused", "project-state.md frontmatter is missing or malformed", source_hash=source_hash)

    archive_target = _state_history_archive_target(inventory)
    if isinstance(archive_target, str):
        return StateCompactionPlan("refused", archive_target, source_hash=source_hash)
    archive_rel_path, archive_path = archive_target
    parsed = _parse_state_compaction_sections(state_text)
    if isinstance(parsed, str):
        return StateCompactionPlan("refused", parsed, archive_rel_path=archive_rel_path, archive_path=archive_path, source_hash=source_hash)
    prefix, sections = parsed
    partition = _partition_state_sections(sections)
    if isinstance(partition, str):
        return StateCompactionPlan("refused", partition, archive_rel_path=archive_rel_path, archive_path=archive_path, source_hash=source_hash)
    kept_sections, archived_sections, prior_history_paths = partition
    if not archived_sections:
        return StateCompactionPlan("refused", "project-state.md has no clearly archivable history sections", archive_rel_path=archive_rel_path, archive_path=archive_path, source_hash=source_hash)

    compacted_state_text = _render_compacted_state(prefix, kept_sections, [*prior_history_paths, archive_rel_path])
    archive_text = _render_state_history_archive(DEFAULT_STATE_REL, archive_rel_path, archived_sections, trigger_reason, source_hash)
    return StateCompactionPlan(
        posture="would run",
        reason=f"project/project-state.md is {line_count} lines, {char_count} chars; {trigger_reason}",
        archive_rel_path=archive_rel_path,
        archive_path=archive_path,
        compacted_state_text=compacted_state_text,
        archive_text=archive_text,
        source_hash=source_hash,
        kept_sections=tuple(section.title for section in kept_sections),
        archived_sections=tuple(section.title for section in archived_sections),
    )


def _state_compaction_trigger_reason(line_count: int, char_count: int) -> str:
    reasons: list[str] = []
    if line_count > STATE_COMPACTION_LINE_THRESHOLD:
        reasons.append(f"exceeded {STATE_COMPACTION_LINE_THRESHOLD} line default")
    if char_count > STATE_COMPACTION_CHAR_THRESHOLD:
        reasons.append(f"exceeded {STATE_COMPACTION_CHAR_THRESHOLD} character default")
    return " and ".join(reasons)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _state_compaction_findings(plan: StateCompactionPlan, apply: bool) -> list[Finding]:
    if apply and plan.posture == "would run":
        posture = "ran"
    else:
        posture = plan.posture
    findings = [
        Finding(_state_compaction_posture_severity(plan, posture), "state-auto-compaction-posture", f"auto-compaction {posture}: {plan.reason}", DEFAULT_STATE_REL)
    ]
    if plan.archive_rel_path:
        findings.append(Finding("info", "state-auto-compaction-target", f"target archive path: {plan.archive_rel_path}", plan.archive_rel_path))
    if plan.source_hash:
        findings.append(Finding("info", "state-auto-compaction-source-hash", f"current project-state sha256: {plan.source_hash}", DEFAULT_STATE_REL))
    if posture in {"would run", "ran"}:
        findings.append(
            Finding(
                "info",
                "state-auto-compaction-selection-policy",
                "selection scans the whole project-state and archives older/non-current sections; it keeps current focus, role map, closeout authority, and the latest relevant update instead of trimming only the newest note",
                DEFAULT_STATE_REL,
            )
        )
        if not apply:
            findings.append(
                Finding(
                    "info",
                    "state-auto-compaction-apply-command",
                    f"after review, apply this exact project-state snapshot with: mylittleharness --root <root> writeback --apply --compact-only --source-hash {plan.source_hash}",
                    DEFAULT_STATE_REL,
                )
            )
    if plan.kept_sections:
        findings.append(Finding("info", "state-auto-compaction-kept-sections", f"sections that would stay: {', '.join(plan.kept_sections)}", DEFAULT_STATE_REL))
    if plan.archived_sections:
        findings.append(
            Finding("info", "state-auto-compaction-archived-sections", f"sections that would be archived: {', '.join(plan.archived_sections)}", plan.archive_rel_path or DEFAULT_STATE_REL)
        )
    validation = (
        "after apply, run check to verify compact operating memory and archive/reference pointer posture"
        if posture in {"would run", "ran"}
        else "auto-compaction did not write; state writeback posture remains separately verifiable with check"
    )
    findings.append(Finding("info", "state-auto-compaction-validation-posture", validation, DEFAULT_STATE_REL))
    return findings


def _state_compaction_posture_severity(plan: StateCompactionPlan, posture: str) -> str:
    if posture in {"would run", "ran", "skipped"}:
        return "info"
    if "--source-hash" in plan.reason or "source hash changed" in plan.reason:
        return "error"
    return "warn"


def state_compaction_dry_run_findings(inventory: Inventory, state_text: str | None = None) -> list[Finding]:
    if state_text is None and inventory.state is not None:
        state_text = inventory.state.content
    if state_text is None:
        return _state_compaction_findings(StateCompactionPlan("refused", "project/project-state.md is missing"), apply=False)
    return _state_compaction_findings(_state_compaction_plan(inventory, state_text), apply=False)


def state_compaction_apply_findings(
    inventory: Inventory,
    state_text: str | None = None,
    *,
    expected_source_hash: str = "",
    require_source_hash: bool = False,
) -> list[Finding]:
    if state_text is None and inventory.state is not None:
        state_text = inventory.state.path.read_text(encoding="utf-8")
    if state_text is None:
        return _state_compaction_findings(StateCompactionPlan("refused", "project/project-state.md is missing"), apply=True)
    return _apply_state_compaction(
        inventory,
        _state_compaction_plan(inventory, state_text),
        expected_source_hash=expected_source_hash,
        require_source_hash=require_source_hash,
    )


def _apply_state_compaction(
    inventory: Inventory,
    plan: StateCompactionPlan,
    *,
    expected_source_hash: str = "",
    require_source_hash: bool = False,
) -> list[Finding]:
    if plan.posture != "would run":
        return _state_compaction_findings(plan, apply=True)
    if require_source_hash:
        if not expected_source_hash:
            refused = StateCompactionPlan(
                "refused",
                f"--source-hash is required for compact-only apply; rerun dry-run and retry with --source-hash {plan.source_hash}",
                plan.archive_rel_path,
                plan.archive_path,
                source_hash=plan.source_hash,
            )
            return _state_compaction_findings(refused, apply=True)
        if expected_source_hash != plan.source_hash:
            refused = StateCompactionPlan(
                "refused",
                f"project-state source hash changed after review; expected {expected_source_hash}, current {plan.source_hash}; rerun dry-run before apply",
                plan.archive_rel_path,
                plan.archive_path,
                source_hash=plan.source_hash,
            )
            return _state_compaction_findings(refused, apply=True)
    state = inventory.state
    assert state is not None
    assert plan.archive_path is not None
    assert plan.archive_text is not None
    assert plan.compacted_state_text is not None

    state_tmp = state.path.with_name(f".{state.path.name}.compact.tmp")
    state_backup = state.path.with_name(f".{state.path.name}.compact.backup")
    archive_tmp = plan.archive_path.with_name(f".{plan.archive_path.name}.compact.tmp")
    archive_backup = plan.archive_path.with_name(f".{plan.archive_path.name}.compact.backup")
    try:
        for candidate, label in (
            (state_tmp, "temporary state compaction path"),
            (state_backup, "temporary state compaction backup path"),
            (archive_tmp, "temporary state-history archive path"),
            (archive_backup, "temporary state-history archive backup path"),
        ):
            if candidate.exists():
                refused = StateCompactionPlan("refused", f"{label} already exists: {candidate.relative_to(inventory.root).as_posix()}", plan.archive_rel_path, plan.archive_path)
                return _state_compaction_findings(refused, apply=True)
        if plan.archive_path.exists():
            refused = StateCompactionPlan("refused", f"state-history archive target already exists: {plan.archive_rel_path}", plan.archive_rel_path, plan.archive_path)
            return _state_compaction_findings(refused, apply=True)
        apply_file_transaction(
            (
                AtomicFileWrite(plan.archive_path, archive_tmp, plan.archive_text, archive_backup),
                AtomicFileWrite(state.path, state_tmp, plan.compacted_state_text, state_backup),
            ),
            root=inventory.root,
        )
    except (FileTransactionError, OSError) as exc:
        refused = StateCompactionPlan("refused", f"auto-compaction failed after state writeback: {exc}", plan.archive_rel_path, plan.archive_path)
        return _state_compaction_findings(refused, apply=True)
    return _state_compaction_findings(plan, apply=True)


def _parse_state_compaction_sections(text: str) -> tuple[str, list[StateSection]] | str:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "project-state.md frontmatter is missing or malformed"
    frontmatter_end = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            frontmatter_end = index
            break
    if frontmatter_end is None:
        return "project-state.md frontmatter is missing or malformed"

    h1_indexes = [index for index, line in enumerate(lines) if re.match(r"^#\s+.+?\s*$", line)]
    if len(h1_indexes) != 1:
        return "unclear section boundaries: project-state.md must have exactly one top-level title"
    h1_index = h1_indexes[0]
    if h1_index <= frontmatter_end:
        return "unclear section boundaries: project-state.md title must follow frontmatter"

    h2_indexes = [index for index, line in enumerate(lines) if re.match(r"^##\s+.+?\s*$", line)]
    if not h2_indexes:
        return "unclear section boundaries: no second-level sections were found"
    if any(line.strip() for line in lines[h1_index + 1 : h2_indexes[0]]):
        return "unclear section boundaries: loose title text before the first section"

    sections: list[StateSection] = []
    for offset, start in enumerate(h2_indexes):
        end = h2_indexes[offset + 1] if offset + 1 < len(h2_indexes) else len(lines)
        title_match = re.match(r"^##\s+(.+?)\s*$", lines[start])
        if not title_match:
            return "unclear section boundaries: section heading could not be parsed"
        title = title_match.group(1).strip()
        sections.append(StateSection(title=title, start=start + 1, end=end, text="".join(lines[start:end])))
    return "".join(lines[: h2_indexes[0]]), sections


def _partition_state_sections(sections: list[StateSection]) -> tuple[list[StateSection], list[StateSection], list[str]] | str:
    keep_titles = {"Current Focus", "Memory Routing Roadmap", "Repository Role Map"}
    latest_update = _latest_relevant_update_section(sections)
    kept: list[StateSection] = []
    archived: list[StateSection] = []
    prior_history_paths: list[str] = []
    for section in sections:
        if section.title == "Archived State History":
            prior_history_paths.extend(_state_history_paths(section.text))
            continue
        if section.title in keep_titles:
            kept.append(section)
            continue
        if section.title == "Notes" and len(section.text.splitlines()) <= 12:
            kept.append(section)
            continue
        if latest_update and section is latest_update:
            kept.append(section)
            continue
        if section.title == "MLH Closeout Writeback" and WRITEBACK_BEGIN in section.text and WRITEBACK_END in section.text:
            kept.append(section)
            continue
        archived.append(section)
    missing_keep_sections = [
        title
        for title in ("Current Focus", "Repository Role Map")
        if title not in {section.title for section in kept}
    ]
    if missing_keep_sections:
        return f"unclear section boundaries: required keep section(s) not found: {', '.join(missing_keep_sections)}"
    return kept, archived, prior_history_paths


def _latest_relevant_update_section(sections: list[StateSection]) -> StateSection | None:
    candidates = [
        section
        for section in sections
        if section.title.startswith(("Ad Hoc Update", "Active Plan Implementation Update", "Active Plan Validation Refresh", "Research Update"))
    ]
    return candidates[-1] if candidates else None


def _state_history_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(r"project/archive/reference/project-state-history-[A-Za-z0-9_.-]+\.md", text):
        path = match.group(0)
        if path not in paths:
            paths.append(path)
    return paths


def _render_compacted_state(prefix: str, kept_sections: list[StateSection], archive_paths: list[str]) -> str:
    parts = [prefix.rstrip(), ""]
    for section in kept_sections:
        parts.append(section.text.rstrip())
        parts.append("")
    parts.append("## Archived State History")
    parts.append("")
    parts.append("Archived history is reference material; current `project/project-state.md` remains operating memory authority.")
    parts.append("")
    for path in dict.fromkeys(archive_paths):
        parts.append(f"- `{path}`")
    return "\n".join(parts).rstrip() + "\n"


def _render_state_history_archive(source_rel_path: str, archive_rel_path: str, archived_sections: list[StateSection], reason: str, source_hash: str) -> str:
    section_titles = "\n".join(f"- {section.title}" for section in archived_sections)
    archived_text = "\n\n".join(section.text.rstrip() for section in archived_sections)
    return (
        f"# Project State History - {date.today().isoformat()}\n\n"
        "## Provenance\n\n"
        f"- Source state path: `{source_rel_path}`\n"
        f"- Archive path: `{archive_rel_path}`\n"
        f"- Compaction date: {date.today().isoformat()}\n"
        f"- Reason: {reason}\n"
        f"- Source state sha256: `{source_hash}`\n"
        "- Non-authority note: archived history is reference; current `project/project-state.md` remains operating memory authority.\n\n"
        "## Archived Sections\n\n"
        f"{section_titles}\n\n"
        "## Archived Content\n\n"
        f"{archived_text}\n"
    )


def _state_history_archive_target(inventory: Inventory) -> tuple[str, Path] | str:
    archive_dir_path = inventory.root / DEFAULT_STATE_HISTORY_DIR_REL
    if _path_escapes_root(inventory.root, archive_dir_path):
        return "state history archive path escapes the target root"
    for parent in _parents_between(inventory.root, archive_dir_path):
        if parent.exists() and parent.is_symlink():
            return f"state history archive directory contains a symlink segment: {parent.relative_to(inventory.root).as_posix()}"
        if parent.exists() and not parent.is_dir():
            return f"state history archive directory contains a non-directory segment: {parent.relative_to(inventory.root).as_posix()}"
    today = date.today().isoformat()
    for suffix in ("", *[f"-{index}" for index in range(2, 100)]):
        rel_path = f"{DEFAULT_STATE_HISTORY_DIR_REL}/project-state-history-{today}{suffix}.md"
        path = inventory.root / rel_path
        if _path_escapes_root(inventory.root, path):
            return "state history archive target escapes the target root"
        if not path.exists():
            return rel_path, path
    return f"state history archive target conflict: no conflict-free same-day path available under {DEFAULT_STATE_HISTORY_DIR_REL}"


@dataclass(frozen=True)
class ArchivePlan:
    plan: Surface
    archive_rel_path: str
    archive_path: Path
    canonical_archive_rel_path: str = ""
    preserved_collision_rel_path: str = ""
    existing_archive_text: str | None = None
    existing_archive_match: str = ""


@dataclass(frozen=True)
class StateSection:
    title: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class StateCompactionPlan:
    posture: str
    reason: str
    archive_rel_path: str | None = None
    archive_path: Path | None = None
    compacted_state_text: str | None = None
    archive_text: str | None = None
    source_hash: str = ""
    kept_sections: tuple[str, ...] = ()
    archived_sections: tuple[str, ...] = ()


def _archive_plan(inventory: Inventory, request: WritebackRequest) -> ArchivePlan | None:
    if not _should_archive_active_plan(inventory, request):
        return None
    plan = inventory.active_plan_surface
    if plan is None or not plan.exists:
        return None
    canonical_rel_path = f"{DEFAULT_ARCHIVE_DIR_REL}/{date.today().isoformat()}-{_archive_slug(plan)}.md"
    rel_path = canonical_rel_path
    preserved_collision_rel_path = ""
    canonical_path = inventory.root / canonical_rel_path
    existing_archive_text: str | None = None
    existing_archive_match = ""
    if canonical_path.exists():
        existing_archive_text = _read_route_text(canonical_path)
        existing_archive_match = _archive_existing_match_kind(
            inventory,
            request,
            plan,
            canonical_rel_path,
            existing_archive_text,
        )
        if not existing_archive_match and request.archive_collision_policy == "preserve-existing":
            rel_path = _next_archive_collision_rel(inventory.root, canonical_rel_path)
            preserved_collision_rel_path = canonical_rel_path
            existing_archive_text = None
    return ArchivePlan(
        plan=plan,
        archive_rel_path=rel_path,
        archive_path=inventory.root / rel_path,
        canonical_archive_rel_path=canonical_rel_path,
        preserved_collision_rel_path=preserved_collision_rel_path,
        existing_archive_text=existing_archive_text,
        existing_archive_match=existing_archive_match,
    )


def _should_archive_active_plan(_inventory: Inventory, request: WritebackRequest) -> bool:
    return request.archive_active_plan


def _archive_plan_findings(inventory: Inventory, archive_plan: ArchivePlan, apply: bool) -> list[Finding]:
    verb = "archived" if apply else "would archive"
    findings = [
        Finding("info", "writeback-archive-active-plan", f"active plan: {archive_plan.plan.rel_path}", archive_plan.plan.rel_path),
        Finding("info", "writeback-archive-target", f"{verb} active plan to {archive_plan.archive_rel_path}", archive_plan.archive_rel_path),
        Finding(
            "info",
            "writeback-archive-boundary",
            "archive-active-plan moves only the active plan and updates project-state lifecycle frontmatter plus the Current Focus managed block; it does not stage, commit, clean archives, repair files, or delete unrelated content",
            inventory.state.rel_path if inventory.state else None,
        ),
    ]
    if archive_plan.existing_archive_match:
        match_label = (
            "planned archive content"
            if archive_plan.existing_archive_match == "planned-archive"
            else "current active-plan content"
        )
        findings.insert(
            2,
            Finding(
                "info",
                "writeback-archive-existing-target-reused",
                (
                    f"{verb} by reusing existing archive target {archive_plan.archive_rel_path} "
                    f"because it matches {match_label}"
                ),
                archive_plan.archive_rel_path,
            ),
        )
    if archive_plan.preserved_collision_rel_path:
        preserve_verb = "preserved" if apply else "would preserve"
        findings.insert(
            2,
            Finding(
                "info",
                "writeback-archive-collision-preserved",
                f"{preserve_verb} existing archive target {archive_plan.preserved_collision_rel_path} and write incoming active plan to {archive_plan.archive_rel_path}",
                archive_plan.preserved_collision_rel_path,
            ),
        )
    return findings


def _archive_preflight_errors(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    errors: list[Finding] = []
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    plan_status = str(data.get("plan_status") or "")
    active_plan_value = str(data.get("active_plan") or "")
    phase_status = _archive_phase_status(inventory, request)
    manifest_plan = _manifest_memory_value(inventory, "plan_file", DEFAULT_PLAN_REL)
    archive_dir = _manifest_memory_value(inventory, "archive_dir", DEFAULT_ARCHIVE_DIR_REL)

    if request.archive_collision_policy not in ARCHIVE_COLLISION_POLICY_VALUES:
        errors.append(Finding("error", "writeback-refused", "--on-archive-collision must be one of: preserve-existing, refuse"))
    if plan_status != "active":
        errors.append(Finding("error", "writeback-refused", f"archive-active-plan requires plan_status active; current plan_status is {plan_status or '<empty>'!r}", state.rel_path if state else None))
    if phase_status != "complete" and request.roadmap_status not in UNSUCCESSFUL_ARCHIVE_ROADMAP_PHASE_STATUS:
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                (
                    "archive-active-plan requires phase_status complete before lifecycle close; "
                    f"current/requested phase_status is {phase_status or '<empty>'!r}"
                ),
                state.rel_path if state else None,
            )
        )
    if not active_plan_value:
        errors.append(Finding("error", "writeback-refused", "archive-active-plan requires active_plan in project-state frontmatter", state.rel_path if state else None))
    if _normalize_rel(manifest_plan) != DEFAULT_PLAN_REL:
        errors.append(Finding("error", "writeback-refused", f"non-default manifest plan_file is refused for archive-active-plan: {manifest_plan}", inventory.manifest_surface.rel_path if inventory.manifest_surface else None))
    if _normalize_rel(active_plan_value) != DEFAULT_PLAN_REL:
        errors.append(Finding("error", "writeback-refused", f"active_plan must be {DEFAULT_PLAN_REL} for archive-active-plan; got {active_plan_value or '<empty>'}", state.rel_path if state else None))
    if _normalize_rel(archive_dir) != DEFAULT_ARCHIVE_DIR_REL:
        errors.append(Finding("error", "writeback-refused", f"non-default archive_dir is refused for archive-active-plan: {archive_dir}", inventory.manifest_surface.rel_path if inventory.manifest_surface else None))

    plan = inventory.active_plan_surface
    if plan is None or not plan.exists:
        errors.append(Finding("error", "writeback-refused", f"active plan file is missing: {active_plan_value or DEFAULT_PLAN_REL}", active_plan_value or DEFAULT_PLAN_REL))
    elif _path_escapes_root(inventory.root, plan.path):
        errors.append(Finding("error", "writeback-refused", "active plan path escapes the target root", plan.rel_path))

    archive_dir_path = inventory.root / DEFAULT_ARCHIVE_DIR_REL
    for parent in _parents_between(inventory.root, archive_dir_path):
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "writeback-refused", f"archive directory contains a symlink segment: {parent.relative_to(inventory.root).as_posix()}"))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "writeback-refused", f"archive directory contains a non-directory segment: {parent.relative_to(inventory.root).as_posix()}"))

    archive_plan = _archive_plan(inventory, request)
    if archive_plan:
        if _path_escapes_root(inventory.root, archive_plan.archive_path):
            errors.append(Finding("error", "writeback-refused", "archive target escapes the target root", archive_plan.archive_rel_path))
        elif archive_plan.archive_path.exists() and not archive_plan.existing_archive_match:
            errors.append(Finding("error", "writeback-refused", f"archive target already exists: {archive_plan.archive_rel_path}", archive_plan.archive_rel_path))
    return errors


def _archive_phase_status(inventory: Inventory, request: WritebackRequest) -> str:
    unsuccessful_status = UNSUCCESSFUL_ARCHIVE_ROADMAP_PHASE_STATUS.get(request.roadmap_status)
    if unsuccessful_status:
        return unsuccessful_status
    requested = str(request.lifecycle.get("phase_status") or "")
    if requested:
        return requested
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    return str(data.get("phase_status") or "")


def _active_plan_lifecycle_values(
    inventory: Inventory,
    request: WritebackRequest,
    lifecycle_values: dict[str, str],
) -> dict[str, str]:
    if not _should_archive_active_plan(inventory, request):
        return lifecycle_values
    phase_status = _archive_phase_status(inventory, request)
    if phase_status != "complete":
        return lifecycle_values
    values = dict(lifecycle_values)
    values.setdefault("phase_status", phase_status)
    return values


def _archive_slug(plan: Surface) -> str:
    raw = str(plan.frontmatter.data.get("title") or _first_heading(plan.content) or "implementation-plan")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", raw.strip().lower()).strip("-")
    return slug or "implementation-plan"


def _next_archive_collision_rel(root: Path, canonical_rel_path: str) -> str:
    canonical = Path(canonical_rel_path)
    parent = canonical.parent.as_posix()
    stem = canonical.stem
    suffix = canonical.suffix or ".md"
    for index in range(2, 1000):
        rel_path = f"{parent}/{stem}-collision-{index}{suffix}"
        if not (root / rel_path).exists():
            return rel_path
    digest = hashlib.sha256(canonical_rel_path.encode("utf-8")).hexdigest()[:12]
    return f"{parent}/{stem}-collision-{digest}{suffix}"


def _archive_existing_match_kind(
    inventory: Inventory,
    request: WritebackRequest,
    plan: Surface,
    archive_rel_path: str,
    existing_text: str | None,
) -> str:
    if existing_text is None:
        return ""
    if existing_text == _archive_expected_plan_text(inventory, request, plan, archive_rel_path):
        return "planned-archive"
    if existing_text == plan.content:
        return "active-plan"
    return ""


def _archive_expected_plan_text(
    inventory: Inventory,
    request: WritebackRequest,
    plan: Surface,
    archive_rel_path: str,
) -> str:
    closeout_plan = _closeout_writeback_plan(inventory, request, archive_rel_path)
    lifecycle_values = _planned_lifecycle_values(request, archive_rel_path, _archive_phase_status(inventory, request))
    active_plan_lifecycle = _active_plan_lifecycle_values(inventory, request, lifecycle_values)
    plan_text, _findings = _active_plan_text_with_synced_values(
        plan,
        closeout_plan.values,
        active_plan_lifecycle,
        _requested_or_current_active_phase(inventory, active_plan_lifecycle),
        "",
    )
    plan_text, _capsule_findings = _archive_plan_text_with_closeout_evidence_capsule(
        plan_text,
        closeout_plan.values,
        closeout_plan.identity,
        archive_rel_path,
        apply=False,
    )
    return plan_text


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return None


def _manifest_memory_value(inventory: Inventory, key: str, default: str) -> str:
    memory = inventory.manifest.get("memory", {}) if isinstance(inventory.manifest, dict) else {}
    return str(memory.get(key) or default)


def _normalize_rel(value: str) -> str:
    return value.replace("\\", "/").strip()


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
            current.relative_to(root_resolved)
        except ValueError:
            break
        if current == root_resolved:
            break
        parents.append(current)
        current = current.parent
    return list(reversed(parents))


def _active_plan_sync_plan_findings(
    inventory: Inventory,
    closeout_values: dict[str, str],
    lifecycle_values: dict[str, str],
    apply: bool,
) -> list[Finding]:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return [Finding("info", "writeback-active-plan-skipped", "no readable active plan exists")]
    _, findings = _active_plan_text_with_synced_values(
        plan,
        closeout_values,
        lifecycle_values,
        _requested_or_current_active_phase(inventory, lifecycle_values),
        _phase_advancement_completed_phase(inventory, lifecycle_values),
    )
    if apply:
        return findings
    return [
        Finding(finding.severity, finding.code.replace("updated", "plan"), finding.message.replace("updated", "would update"), finding.source, finding.line)
        for finding in findings
    ]


def _archive_plan_text_with_closeout_evidence_capsule(
    text: str,
    closeout_values: dict[str, str],
    identity: CloseoutIdentity,
    archive_rel_path: str,
    *,
    apply: bool,
) -> tuple[str, list[Finding]]:
    prefix = "" if apply else "would "
    if not closeout_values:
        return text, [
            Finding(
                "info",
                "writeback-archive-closeout-evidence-capsule-skipped",
                (
                    f"{prefix}leave archived plan without an MLH closeout evidence capsule "
                    "because no closeout facts were available for archive-active-plan"
                ),
                archive_rel_path,
            )
        ]

    updated = _replace_or_append_writeback_block(text, closeout_values, identity)
    if updated == text:
        return text, [
            Finding(
                "info",
                "writeback-archive-closeout-evidence-capsule-noop",
                "archived plan already contains an MLH closeout evidence capsule matching planned facts",
                archive_rel_path,
            )
        ]
    return updated, [
        Finding(
            "info",
            "writeback-archive-closeout-evidence-capsule",
            (
                f"{prefix}materialize archived-plan MLH closeout evidence capsule "
                "before deleting the active plan route"
            ),
            archive_rel_path,
        )
    ]


def _state_text_with_writeback(
    text: str,
    closeout_values: dict[str, str],
    lifecycle_values: dict[str, str],
    identity: CloseoutIdentity | None = None,
) -> str:
    updated = _update_frontmatter_scalars(text, lifecycle_values, only_existing=False) if lifecycle_values else text
    if closeout_values:
        updated = _replace_or_append_writeback_block(updated, closeout_values, identity or CloseoutIdentity())
    updated = _state_text_with_retired_phase_writeback_tail(updated, lifecycle_values)
    return sync_current_focus_block(updated)


def _state_text_with_retired_phase_writeback_tail(text: str, lifecycle_values: dict[str, str]) -> str:
    if not _lifecycle_closes_default_active_plan(lifecycle_values):
        return text
    lines = text.splitlines(keepends=True)
    removals: list[tuple[int, int]] = []
    for start, end in _phase_writeback_marker_spans(lines):
        if not _phase_writeback_span_references_default_plan(lines, start, end):
            continue
        remove_start, remove_end = start, end + 1
        section_start, section_end = _phase_writeback_only_section_span(lines, start, end)
        if section_start is not None and section_end is not None:
            remove_start, remove_end = section_start, section_end
        removals.append((remove_start, remove_end))
    if not removals:
        return text
    merged: list[tuple[int, int]] = []
    for start, end in sorted(removals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    output: list[str] = []
    cursor = 0
    for start, end in merged:
        output.extend(lines[cursor:start])
        cursor = end
    output.extend(lines[cursor:])
    return "".join(output)


def _lifecycle_closes_default_active_plan(lifecycle_values: dict[str, str]) -> bool:
    return lifecycle_values.get("plan_status") == "none" and lifecycle_values.get("active_plan") == ""


def _phase_writeback_marker_spans(lines: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(lines):
        if PHASE_WRITEBACK_BEGIN in line:
            start = index
        elif start is not None and PHASE_WRITEBACK_END in line:
            spans.append((start, index))
            start = None
    return spans


def _phase_writeback_span_references_default_plan(lines: list[str], start: int, end: int) -> bool:
    for line in lines[start + 1 : end]:
        match = re.match(r"^\s*[-*]\s*`?active_plan`?\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
        if not match:
            continue
        return _normalize_phase_writeback_path_value(match.group(1)) == DEFAULT_PLAN_REL
    return False


def _normalize_phase_writeback_path_value(value: str) -> str:
    raw = _strip_quotes(value.strip())
    if raw.startswith("`") and raw.endswith("`") and len(raw) >= 2:
        raw = raw[1:-1].strip()
    return raw.replace("\\", "/").strip("/").casefold()


def _phase_writeback_only_section_span(lines: list[str], marker_start: int, marker_end: int) -> tuple[int | None, int | None]:
    heading_index: int | None = None
    for index in range(marker_start - 1, -1, -1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*(?:\r?\n)?$", lines[index])
        if not match:
            continue
        if _normalized_heading_title(match.group(2)) == PHASE_WRITEBACK_HEADING:
            heading_index = index
        break
    if heading_index is None:
        return None, None
    next_heading = len(lines)
    for index in range(marker_end + 1, len(lines)):
        if re.match(r"^#{1,6}\s+", lines[index]):
            next_heading = index
            break
    if any(line.strip() for line in lines[heading_index + 1 : marker_start]):
        return None, None
    if any(line.strip() for line in lines[marker_end + 1 : next_heading]):
        return None, None
    return heading_index, next_heading


def _phase_writeback_tail_retirement_findings(inventory: Inventory, updated_state_text: str, apply: bool) -> list[Finding]:
    state = inventory.state
    if state is None or not state.exists:
        return []
    before_count = _phase_writeback_default_plan_tail_count(state.content)
    after_count = _phase_writeback_default_plan_tail_count(updated_state_text)
    retired = before_count - after_count
    if retired <= 0:
        return []
    verb = "retired" if apply else "would retire"
    return [
        Finding(
            "info",
            "writeback-phase-writeback-tail-retired",
            (
                f"{verb} {retired} stale MLH Phase Writeback tail(s) during archive-active-plan close; "
                "archived plan and closeout writeback remain the durable evidence, and this cleanup does not approve "
                "repair, staging, commit, rollback, or next-plan opening"
            ),
            state.rel_path,
        )
    ]


def _phase_writeback_default_plan_tail_count(text: str) -> int:
    lines = text.splitlines(keepends=True)
    return sum(
        1
        for start, end in _phase_writeback_marker_spans(lines)
        if _phase_writeback_span_references_default_plan(lines, start, end)
    )


def _active_plan_text_with_synced_values(
    plan: Surface,
    closeout_values: dict[str, str],
    lifecycle_values: dict[str, str],
    active_phase: str,
    completed_phase: str = "",
) -> tuple[str, list[Finding]]:
    text = plan.content
    findings: list[Finding] = []
    frontmatter_updates = {**closeout_values, **lifecycle_values}
    if "phase_status" in lifecycle_values:
        frontmatter_updates["status"] = lifecycle_values["phase_status"]
    if plan.frontmatter.has_frontmatter:
        updated_text, updated_keys = _update_existing_frontmatter_scalars(text, frontmatter_updates)
        text = updated_text
        if updated_keys:
            findings.append(
                Finding(
                    "info",
                    "writeback-active-plan-frontmatter-updated",
                    f"updated active-plan frontmatter keys: {', '.join(updated_keys)}",
                    plan.rel_path,
                )
            )
        else:
            findings.append(
                Finding(
                    "info",
                    "writeback-active-plan-frontmatter-skipped",
                    "active-plan frontmatter had no matching closeout/lifecycle keys to synchronize",
                    plan.rel_path,
                )
            )
    else:
        findings.append(
            Finding(
                "info",
                "writeback-active-plan-frontmatter-skipped",
                "active plan has no frontmatter; no diagnostic frontmatter copy was synchronized",
                plan.rel_path,
            )
        )

    body_text, body_fields = _update_exact_body_fields(text, closeout_values)
    text = body_text
    if body_fields:
        findings.append(
            Finding(
                "info",
                "writeback-active-plan-body-updated",
                f"updated active-plan closeout body fields: {', '.join(body_fields)}",
                plan.rel_path,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "writeback-active-plan-body-skipped",
                "active-plan body had no matching exact closeout field lines to synchronize",
                plan.rel_path,
            )
        )
    phase_text, phase_findings = _active_plan_text_with_phase_body_statuses(text, plan.rel_path, active_phase, lifecycle_values, completed_phase)
    text = phase_text
    findings.extend(phase_findings)
    return text, findings


def _active_plan_text_with_phase_body_statuses(
    text: str,
    rel_path: str,
    active_phase: str,
    lifecycle_values: dict[str, str],
    completed_phase: str,
) -> tuple[str, list[Finding]]:
    findings: list[Finding] = []
    if completed_phase and completed_phase != active_phase:
        completed_text, completed_finding = _active_plan_text_with_phase_body_status(
            text,
            rel_path,
            completed_phase,
            {"phase_status": "complete"},
        )
        text = completed_text
        if completed_finding:
            findings.append(completed_finding)
    phase_text, phase_finding = _active_plan_text_with_phase_body_status(text, rel_path, active_phase, lifecycle_values)
    text = phase_text
    if phase_finding:
        findings.append(phase_finding)
    return text, findings


def _active_plan_text_with_phase_body_status(
    text: str,
    rel_path: str,
    active_phase: str,
    lifecycle_values: dict[str, str],
) -> tuple[str, Finding | None]:
    phase_status = lifecycle_values.get("phase_status")
    if not phase_status:
        return text, None
    if not active_phase:
        return (
            text,
            Finding(
                "info",
                "writeback-active-plan-phase-block-skipped",
                "phase_status was written but no active_phase was available for active-plan phase body synchronization",
                rel_path,
            ),
        )
    block = _find_phase_block(text, active_phase)
    if block is None:
        return (
            text,
            Finding(
                "info",
                "writeback-active-plan-phase-block-skipped",
                f"active-plan phase block {active_phase!r} was not found; no phase status body copy was synchronized",
                rel_path,
            ),
        )
    lines = text.splitlines(keepends=True)
    status_index = _phase_status_line_index(lines, block)
    if status_index is None:
        return (
            text,
            Finding(
                "info",
                "writeback-active-plan-phase-block-skipped",
                f"active-plan phase block {active_phase!r} has no status line to synchronize",
                rel_path,
            ),
        )
    current = _phase_status_line_value(lines[status_index])
    desired = canonical_phase_body_status(phase_status)
    if current == desired:
        return (
            text,
            Finding(
                "info",
                "writeback-active-plan-phase-block-skipped",
                f"active-plan phase block {active_phase!r} status body copy already records {desired!r}",
                rel_path,
                status_index + 1,
            ),
        )
    lines[status_index] = _updated_phase_status_line(lines[status_index], desired)
    return (
        "".join(lines),
        Finding(
            "info",
            "writeback-active-plan-phase-block-updated",
            f"updated active-plan phase block {active_phase!r} status body copy to {desired!r}",
            rel_path,
            status_index + 1,
        ),
    )


def _requested_or_current_active_phase(inventory: Inventory, lifecycle_values: dict[str, str]) -> str:
    if lifecycle_values.get("active_phase"):
        return lifecycle_values["active_phase"]
    state = inventory.state
    if state and state.exists:
        value = state.frontmatter.data.get("active_phase")
        if value not in (None, ""):
            return str(value)
    plan = inventory.active_plan_surface
    if plan and plan.exists and plan.frontmatter.has_frontmatter:
        value = plan.frontmatter.data.get("active_phase")
        if value not in (None, ""):
            return str(value)
    return ""


def _phase_advancement_completed_phase(inventory: Inventory, lifecycle_values: dict[str, str]) -> str:
    if lifecycle_values.get("phase_status") != "pending":
        return ""
    requested_active_phase = lifecycle_values.get("active_phase", "")
    if not requested_active_phase:
        return ""
    state = inventory.state
    if not state or not state.exists:
        return ""
    current_active_phase = str(state.frontmatter.data.get("active_phase") or "")
    if not current_active_phase or current_active_phase == requested_active_phase:
        return ""
    return current_active_phase


def _find_phase_block(text: str, active_phase: str) -> PhaseBlockSpan | None:
    target = active_phase.strip()
    if not target:
        return None
    lines = text.splitlines(keepends=True)
    candidates = [
        block
        for block, title in _phase_blocks_from_lines(lines)
        if _phase_block_matches(lines, block, title, target)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda block: (block.end_index - block.start_index, block.start_index))


def _phase_blocks_from_lines(lines: list[str]) -> list[tuple[PhaseBlockSpan, str]]:
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,6})\s+(.+?)\s*#*\s*(?:\r?\n)?$", line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))
    blocks: list[tuple[PhaseBlockSpan, str]] = []
    for heading_index, (start, level, title) in enumerate(headings):
        end = len(lines)
        for next_start, next_level, _next_title in headings[heading_index + 1 :]:
            if next_level <= level:
                end = next_start
                break
        blocks.append((PhaseBlockSpan(active_phase=title, start_index=start, end_index=end), title))
    return blocks


def _phase_block_index(lines: list[str], blocks: list[tuple[PhaseBlockSpan, str]], active_phase: str) -> int | None:
    target = active_phase.strip()
    candidates = [
        (index, block)
        for index, (block, title) in enumerate(blocks)
        if _phase_block_matches(lines, block, title, target)
    ]
    if not candidates:
        return None
    index, _block = min(candidates, key=lambda item: (item[1].end_index - item[1].start_index, item[1].start_index))
    return index


def _phase_block_matches(lines: list[str], block: PhaseBlockSpan, title: str, active_phase: str) -> bool:
    return _phase_heading_matches(title, active_phase) or _phase_block_has_id(lines, block, active_phase)


def _phase_block_label(lines: list[str], block: PhaseBlockSpan, title: str) -> str:
    for line in lines[block.start_index + 1 : block.end_index]:
        match = re.match(r"^\s*[-*]\s*id\s*:\s*(.+?)\s*(?:\r?\n)?$", line, re.IGNORECASE)
        if match:
            return _strip_inline_code(match.group(1).strip())
    return _strip_inline_code(title)


def _phase_heading_matches(title: str, active_phase: str) -> bool:
    normalized_title = _strip_inline_code(title).casefold()
    normalized_phase = active_phase.casefold()
    return normalized_title == normalized_phase or normalized_phase in normalized_title


def _phase_block_has_id(lines: list[str], block: PhaseBlockSpan, active_phase: str) -> bool:
    for line in lines[block.start_index + 1 : block.end_index]:
        match = re.match(r"^\s*[-*]\s*id\s*:\s*(.+?)\s*(?:\r?\n)?$", line, re.IGNORECASE)
        if match and _strip_inline_code(match.group(1).strip()) == active_phase:
            return True
    return False


def _phase_status_line_index(lines: list[str], block: PhaseBlockSpan) -> int | None:
    for index in range(block.start_index + 1, block.end_index):
        if _phase_status_line_match(lines[index]):
            return index
    return None


def _phase_status_line_value(line: str) -> str | None:
    match = _phase_status_line_match(line)
    if not match:
        return None
    return _strip_inline_code(match.group("value").strip())


def _updated_phase_status_line(line: str, desired: str) -> str:
    match = _phase_status_line_match(line)
    if not match:
        return line
    newline = match.group("newline") or ""
    tick = "`" if match.group("open") or match.group("close") else ""
    return f"{match.group('prefix')}{tick}{desired}{tick}{match.group('suffix')}{newline}"


def _phase_status_line_match(line: str) -> re.Match[str] | None:
    return re.match(
        r"^(?P<prefix>\s*[-*]\s*status\s*:\s*)(?P<open>`?)(?P<value>[^`\r\n]+?)(?P<close>`?)(?P<suffix>\s*)(?P<newline>\r?\n)?$",
        line,
        re.IGNORECASE,
    )


def _strip_inline_code(value: str) -> str:
    stripped = _strip_quotes(value.strip())
    if stripped.startswith("`") and stripped.endswith("`") and len(stripped) >= 2:
        return stripped[1:-1].strip()
    return stripped.strip()


def _replace_or_append_writeback_block(text: str, closeout_values: dict[str, str], identity: CloseoutIdentity | None = None) -> str:
    block = _render_writeback_block(closeout_values, identity or CloseoutIdentity())
    begin_index = text.rfind(WRITEBACK_BEGIN)
    end_index = text.rfind(WRITEBACK_END)
    if begin_index != -1 and end_index != -1 and end_index > begin_index:
        end_after = end_index + len(WRITEBACK_END)
        if end_after < len(text) and text[end_after : end_after + 2] == "\r\n":
            end_after += 2
        elif end_after < len(text) and text[end_after : end_after + 1] == "\n":
            end_after += 1
        return text[:begin_index] + block + text[end_after:]

    separator = "" if text.endswith(("\n", "\r")) else "\n"
    return text + separator + "\n## MLH Closeout Writeback\n\n" + block


def _render_writeback_block(closeout_values: dict[str, str], identity: CloseoutIdentity | None = None) -> str:
    lines = [WRITEBACK_BEGIN]
    current_identity = identity or CloseoutIdentity()
    for field in CLOSEOUT_IDENTITY_FIELDS:
        value = getattr(current_identity, field)
        if value:
            lines.append(f"- {field}: {value}")
    for field in CLOSEOUT_WRITEBACK_FIELDS:
        value = closeout_values.get(field)
        if value:
            lines.append(f"- {field}: {value}")
    lines.append(WRITEBACK_END)
    return "\n".join(lines) + "\n"


def _update_existing_frontmatter_scalars(text: str, updates: dict[str, str]) -> tuple[str, list[str]]:
    if not updates:
        return text, []
    new_text = _update_frontmatter_scalars(text, updates, only_existing=True)
    changed = [
        key
        for key, value in updates.items()
        if _frontmatter_value(text, key) not in (None, value) and _frontmatter_value(new_text, key) == value
    ]
    return new_text, changed


def _update_frontmatter_scalars(text: str, updates: dict[str, str], only_existing: bool) -> str:
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

    if not only_existing:
        missing = [key for key in updates if key not in seen]
        if missing:
            insert_lines = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"\n' for key in missing]
            lines[closing_index:closing_index] = insert_lines
    return "".join(lines)


def _frontmatter_value(text: str, key: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        match = re.match(rf"^{re.escape(key)}:\s*(.*?)\s*$", line)
        if match:
            return _strip_quotes(match.group(1))
    return None


def _update_exact_body_fields(text: str, closeout_values: dict[str, str]) -> tuple[str, list[str]]:
    if not closeout_values:
        return text, []
    lines = text.splitlines(keepends=True)
    updated_fields: list[str] = []
    for index in _closeout_body_field_line_indexes(text):
        line = lines[index]
        field, _value = _field_line_value(line)
        if field not in closeout_values:
            continue
        prefix_match = _field_line_prefix(field, line)
        if not prefix_match:
            continue
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        lines[index] = f"{prefix_match}{closeout_values[field]}{newline}"
        if field not in updated_fields:
            updated_fields.append(field)
    return "".join(lines), updated_fields


def _closeout_body_field_line_indexes(text: str) -> list[int]:
    lines = text.splitlines(keepends=True)
    indexes: list[int] = []
    for span in _closeout_body_sections(lines):
        for index in range(span.start_index, span.end_index):
            field, value = _field_line_value(lines[index])
            if field and value:
                indexes.append(index)
    return indexes


def _closeout_body_sections(lines: list[str]) -> list[BodySectionSpan]:
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*(?:\r?\n)?$", line)
        if match:
            headings.append((index, len(match.group(1)), _normalized_heading_title(match.group(2))))

    sections: list[BodySectionSpan] = []
    for heading_index, (start, level, title) in enumerate(headings):
        if title not in _CLOSEOUT_BODY_SECTION_TITLES:
            continue
        end = len(lines)
        for next_start, next_level, _next_title in headings[heading_index + 1 :]:
            if next_level <= level:
                end = next_start
                break
        sections.append(BodySectionSpan(start_index=start + 1, end_index=end))
    return sections


def _normalized_heading_title(title: str) -> str:
    return re.sub(r"\s+", " ", _strip_inline_code(title).casefold()).strip(" :")


def _field_line_value(line: str) -> tuple[str | None, str | None]:
    compact = line.strip()
    for field, labels in _FIELD_LABELS.items():
        for label in labels:
            match = re.match(rf"^[-*]\s*`?{re.escape(label)}`?\s*:\s*(.+?)\s*$", compact, re.IGNORECASE)
            if match:
                return field, _normalized_value(match.group(1))
    return None, None


def _field_line_prefix(field: str, line: str) -> str | None:
    for label in _FIELD_LABELS.get(field, (field,)):
        match = re.match(rf"^(\s*[-*]\s*`?{re.escape(label)}`?\s*:\s*).*$", line.rstrip("\r\n"), re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]


def _text_field_input_errors(values: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for field in CLOSEOUT_WRITEBACK_FIELDS:
        value = values.get(field)
        if value is None:
            continue
        text = str(value)
        if "\n" in text or "\r" in text:
            errors.append(
                f"--{field.replace('_', '-')} is a one-line closeout field; put multi-paragraph evidence in the active plan or project/verification and pass a concise summary"
            )
    return errors


def _normalized_value(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _normalized_status(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _normalized_archive_collision_policy(value: object) -> str:
    return str(value or "refuse").strip().casefold().replace("_", "-") or "refuse"


def _is_phase_handoff_terminal_status(value: object) -> bool:
    return _strip_inline_code(str(value or "")).casefold() in PHASE_HANDOFF_TERMINAL_STATUS_VALUES


def _closeout_value_is_complete(value: object) -> bool:
    normalized = _normalized_value(value).casefold()
    return normalized not in INCOMPLETE_CLOSEOUT_VALUES


def _strip_quotes(value: str) -> str:
    raw = value.strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


def _yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
