from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .command_discovery import rails_not_cognition_boundary_finding
from .inventory import Inventory, Surface
from .models import Finding
from .evidence_cues import CLOSEOUT_FIELD_NAMES, closeout_field_cues, cue_findings, find_cues
from .parsing import Frontmatter, parse_frontmatter
from .writeback import (
    WritebackFact,
    acceptance_evidence_findings,
    current_state_writeback_facts,
    satisfied_post_archive_carry_forward_finding,
    state_writeback_facts,
)


ANCHOR_PATTERNS = (
    ("plan", (r"\bplan anchors?\b", r"\bplan\b.*\banchors?\b")),
    ("integration", (r"\bintegration anchors?\b", r"\bintegration\b.*\banchors?\b")),
    ("closeout", (r"\bcloseout anchors?\b", r"\bcloseout\b.*\banchors?\b")),
)

CARRY_FORWARD_PATTERNS = (
    r"carry-forward",
    r"deferred",
    r"unresolved",
    r"optional-next",
    r"later-extension",
    r"needs-more-research",
    r"\bopen questions?\b",
)
GIT_CONTEXT_TRAILERS = (
    ("MLH-Plan", ("plan_id",)),
    ("MLH-Phase", ("active_phase",)),
    ("MLH-Slice", ("execution_slice", "primary_roadmap_item", "related_roadmap_item")),
)
SKIP_RATIONALE_PATTERNS = (
    r"skip rationale",
    r"explicit skip",
    r"verified skip",
    r"explicitly skipped",
    r"skipped because",
)
DURABLE_PROOF_RECORD_PREFIX = "project/verification/"
DURABLE_PROOF_RECORD_LIMIT = 5
AGENT_RUNS_DIR_REL = "project/verification/agent-runs"
AGENT_RUN_RECORD_PREFIX = f"{AGENT_RUNS_DIR_REL}/"
AGENT_RUN_SCHEMA = "mylittleharness.agent-run.v1"
COORDINATION_RECORD_DIRS = (
    "project/verification/work-claims",
    "project/verification/handoffs",
    "project/verification/session-active-work",
)
AGENT_RUN_REQUIRED_SCALARS = (
    "schema",
    "record_type",
    "record_id",
    "role",
    "actor",
    "task",
    "assigned_scope",
    "runtime",
    "worktree_id",
    "status",
    "stop_reason",
    "attempt_budget",
    "docs_decision",
    "residual_risk",
)
AGENT_RUN_REQUIRED_LISTS = ("input_refs", "output_refs", "claimed_paths", "changed_files", "commands", "verification_refs", "source_hashes")
AGENT_RUN_STATUSES = {
    "succeeded",
    "failed",
    "blocked",
    "skipped",
    "needs-refinement",
    "needs-human-review",
}
AGENT_RUN_DOCS_DECISIONS = {"updated", "not-needed", "uncertain"}
RECORD_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SOURCE_HASH_RE = re.compile(r"^(.+?)\s+(?:sha256=([a-fA-F0-9]{64})|(missing)|(unreadable)|(invalid-path))$")


@dataclass(frozen=True)
class AgentRunRecordRequest:
    record_id: str
    role: str
    actor: str
    task: str
    assigned_scope: str
    runtime: str
    worktree_id: str
    status: str
    stop_reason: str
    attempt_budget: str
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]
    claimed_paths: tuple[str, ...]
    changed_files: tuple[str, ...]
    commands: tuple[str, ...]
    verification_refs: tuple[str, ...]
    docs_decision: str
    residual_risk: str
    handoff_refs: tuple[str, ...]
    claim_refs: tuple[str, ...]
    repeated_failure_signature: str
    provider: str
    model_id: str
    tools: tuple[str, ...]


def make_agent_run_record_request(args: object) -> AgentRunRecordRequest:
    return AgentRunRecordRequest(
        record_id=str(getattr(args, "record_id", "") or "").strip(),
        role=str(getattr(args, "agent_role", "") or "").strip(),
        actor=str(getattr(args, "actor", "") or "").strip(),
        task=str(getattr(args, "task", "") or "").strip(),
        assigned_scope=str(getattr(args, "assigned_scope", "") or "").strip(),
        runtime=str(getattr(args, "runtime", "") or "").strip(),
        worktree_id=str(getattr(args, "worktree_id", "") or "").strip(),
        status=str(getattr(args, "status", "") or "").strip(),
        stop_reason=str(getattr(args, "stop_reason", "") or "").strip(),
        attempt_budget=str(getattr(args, "attempt_budget", "") or "").strip(),
        input_refs=_tuple_values(getattr(args, "input_refs", ())),
        output_refs=_tuple_values(getattr(args, "output_refs", ())),
        claimed_paths=_tuple_values(getattr(args, "claimed_paths", ())),
        changed_files=_tuple_values(getattr(args, "changed_files", ())),
        commands=_tuple_values(getattr(args, "commands", ())),
        verification_refs=_tuple_values(getattr(args, "verification_refs", ())),
        docs_decision=str(getattr(args, "docs_decision", "") or "").strip(),
        residual_risk=str(getattr(args, "residual_risk", "") or "").strip(),
        handoff_refs=_tuple_values(getattr(args, "handoff_refs", ())),
        claim_refs=_tuple_values(getattr(args, "claim_refs", ())),
        repeated_failure_signature=str(getattr(args, "repeated_failure_signature", "") or "").strip(),
        provider=str(getattr(args, "provider", "") or "").strip(),
        model_id=str(getattr(args, "model_id", "") or "").strip(),
        tools=_tuple_values(getattr(args, "tools", ())),
    )


def agent_run_record_dry_run_findings(inventory: Inventory, request: AgentRunRecordRequest) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "agent-run-record-dry-run", "agent run evidence record proposal only; no files were written"),
        Finding("info", "agent-run-record-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _agent_run_request_findings(inventory, request, apply=False)
    findings.extend(request_findings)
    if any(finding.severity in {"warn", "error"} and finding.code == "agent-run-record-refused" for finding in request_findings):
        findings.append(Finding("info", "agent-run-record-validation-posture", "dry-run refused before apply; fix explicit record fields before writing evidence"))
        findings.extend(_agent_run_record_boundary_findings())
        return findings

    target_rel = _agent_run_record_target_rel(request)
    text, hash_findings = _render_agent_run_record(inventory.root, request)
    findings.extend(hash_findings)
    findings.extend(
        [
            Finding("info", "agent-run-record-target", f"would write agent run record: {target_rel}", target_rel),
            Finding(
                "info",
                "agent-run-record-route-write",
                f"would create route {target_rel}; before_hash=missing; after_hash={_short_hash(text)}; before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; source-bound write evidence is independent of Git tracking",
                target_rel,
            ),
        ]
    )
    findings.extend(_agent_run_record_boundary_findings())
    return findings


def agent_run_record_apply_findings(inventory: Inventory, request: AgentRunRecordRequest) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "agent-run-record-apply", "agent run evidence record apply started"),
        Finding("info", "agent-run-record-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _agent_run_request_findings(inventory, request, apply=True)
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "agent-run-record-validation-posture", "apply refused before writing evidence"))
        findings.extend(_agent_run_record_boundary_findings())
        return findings

    target_rel = _agent_run_record_target_rel(request)
    target = inventory.root / target_rel
    text, hash_findings = _render_agent_run_record(inventory.root, request)
    findings.extend(hash_findings)
    tmp_path = target.with_name(f".{target.name}.tmp")
    backup_path = target.with_name(f".{target.name}.bak")
    try:
        cleanup_warnings = apply_file_transaction((AtomicFileWrite(target, tmp_path, text, backup_path),))
    except FileTransactionError as exc:
        findings.append(Finding("error", "agent-run-record-refused", f"failed to write agent run record before apply completed: {exc}", target_rel))
        findings.extend(_agent_run_record_boundary_findings())
        return findings

    findings.extend(
        [
            Finding("info", "agent-run-record-written", f"created agent run evidence record: {target_rel}", target_rel),
            Finding(
                "info",
                "agent-run-record-route-write",
                f"created route {target_rel}; before_hash=missing; after_hash={_short_hash(text)}; before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; source-bound write evidence is independent of Git tracking",
                target_rel,
            ),
        ]
    )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "agent-run-record-backup-cleanup", warning, target_rel))
    findings.extend(_agent_run_record_boundary_findings())
    return findings


def agent_run_record_findings(inventory: Inventory, code_prefix: str = "agent-run") -> list[Finding]:
    code = f"{code_prefix}-record"
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "info",
                code,
                "agent run record scan is live-root only; product fixtures and archive roots remain non-authority context",
                inventory.state.rel_path if inventory.state and inventory.state.exists else None,
            )
        ]

    paths = _agent_run_record_paths(inventory.root)
    if not paths:
        return [
            Finding(
                "info",
                code,
                "no agent run evidence records found at project/verification/agent-runs/*.md; records are optional evidence and absence does not block closeout",
            ),
            *_agent_run_record_boundary_findings(code_prefix),
        ]

    findings: list[Finding] = []
    for path in paths:
        rel_path = _to_rel_path(inventory.root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code}-malformed", "agent run record path is not a regular file", rel_path))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            findings.append(Finding("warn", f"{code}-malformed", f"agent run record could not be read: {exc}", rel_path))
            continue
        frontmatter = parse_frontmatter(text)
        data = frontmatter.data
        record_id = str(data.get("record_id") or "").strip() or "<missing>"
        role = str(data.get("role") or "").strip() or "<missing>"
        status = str(data.get("status") or "").strip() or "<missing>"
        findings.append(
            Finding(
                "info",
                code,
                f"candidate: agent run record: {rel_path}; record_id={record_id}; role={role}; status={status}; read-only evidence input only",
                rel_path,
            )
        )
        findings.extend(_agent_run_record_metadata_findings(rel_path, frontmatter, data, code_prefix))
        findings.extend(_agent_run_source_hash_findings(inventory.root, rel_path, data, code_prefix))

    findings.extend(_agent_run_record_boundary_findings(code_prefix))
    return findings


def lifecycle_mutation_provenance_findings(inventory: Inventory, code_prefix: str = "lifecycle-provenance") -> list[Finding]:
    state = inventory.state
    state_source = state.rel_path if state and state.exists else "project/project-state.md"
    state_data = state.frontmatter.data if state and state.exists else {}
    facts = state_writeback_facts(state)
    records = _agent_run_record_paths(inventory.root) if inventory.root_kind == "live_operating_root" else []
    coordination_records = _coordination_record_paths(inventory.root) if inventory.root_kind == "live_operating_root" else []
    findings = [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "lifecycle mutation provenance is read-only visibility; it cannot repair, rollback, close out, archive, mark roadmap done, stage, commit, push, or approve concurrent work",
            state_source,
        )
    ]
    if facts:
        fact_fields = ", ".join(sorted(facts)[:8])
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-state-writeback",
                f"project-state closeout/writeback facts are present: fields={fact_fields}; source={state_source}",
                state_source,
            )
        )
    plan_status = str(state_data.get("plan_status") or "").strip()
    active_plan = str(state_data.get("active_plan") or "").strip()
    if plan_status == "active" or active_plan:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-active-lifecycle",
                (
                    f"active lifecycle posture visible: plan_status={plan_status or '<none>'}; "
                    f"active_plan={active_plan or '<none>'}; active_phase={state_data.get('active_phase') or '<none>'}; "
                    f"phase_status={state_data.get('phase_status') or '<none>'}"
                ),
                state_source,
            )
        )
    if records:
        examples = ", ".join(_to_rel_path(inventory.root, path) for path in records[:3])
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-agent-run-visibility",
                f"agent-run evidence records available for recent run visibility: count={len(records)}; examples={examples}",
                AGENT_RUNS_DIR_REL,
            )
        )
    elif (plan_status == "active" or facts) and coordination_records:
        examples = ", ".join(_to_rel_path(inventory.root, path) for path in coordination_records[:3])
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-unknown-owner",
                (
                    "lifecycle/writeback posture is present but no agent-run evidence records were found; "
                    f"concurrent coordination records exist at {examples}; inspect project-state, roadmap, handoff, claim, and Git status before assuming ownership"
                ),
                AGENT_RUNS_DIR_REL,
            )
        )
    elif plan_status == "active" or facts:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-agent-run-absent",
                "active lifecycle/writeback posture is visible and no agent-run evidence records were found; no concurrent coordination records were found",
                AGENT_RUNS_DIR_REL,
            )
        )
    else:
        findings.append(Finding("info", f"{code_prefix}-quiet", "no active lifecycle mutation or agent-run evidence was found", state_source))
    return findings


def evidence_findings(inventory: Inventory) -> list[Finding]:
    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    active_plan = inventory.active_plan_surface if inventory.active_plan_surface and inventory.active_plan_surface.exists else None
    findings: list[Finding] = [
        rails_not_cognition_boundary_finding("project/verification"),
        Finding(
            "info",
            "evidence-boundary",
            "terminal-only read-only report; persistent evidence manifest remains deferred and no files, caches, databases, generated artifacts, VCS probes, hooks, adapters, or mutations are written",
        ),
        Finding("info", "evidence-root-kind", f"root kind: {inventory.root_kind}"),
    ]

    if inventory.root_kind == "product_source_fixture":
        findings.append(
            Finding(
                "info",
                "evidence-non-authority",
                "product source checkout contains compatibility fixtures only; evidence findings do not make it an operating project root",
                state.rel_path if state else None,
            )
        )

    findings.extend(_active_plan_findings(inventory, active_plan, state_data))
    findings.extend(durable_proof_record_findings(inventory, "evidence"))
    findings.extend(agent_run_record_findings(inventory, "evidence-agent-run"))
    findings.extend(_source_set_findings(active_plan, inventory))
    findings.extend(_anchor_findings(active_plan, inventory))
    findings.extend(_identity_findings(active_plan))
    findings.extend(_closeout_findings(active_plan, inventory))
    findings.extend(_git_trailer_suggestion_findings(active_plan, inventory))
    findings.extend(_quality_cue_findings(active_plan, inventory))
    findings.extend(_acceptance_evidence_findings(inventory, state_data))
    findings.extend(_operator_required_findings(inventory))
    findings.extend(_line_group_findings(active_plan, "evidence-residual-risk", "residual risk", (r"residual risk", r"residual risks"), inventory))
    findings.extend(_line_group_findings(active_plan, "evidence-skip-rationale", "skip rationale", SKIP_RATIONALE_PATTERNS, inventory))
    findings.extend(_line_group_findings(active_plan, "evidence-carry-forward", "carry-forward", CARRY_FORWARD_PATTERNS, inventory))
    findings.append(
        Finding(
            "info",
            "evidence-non-authority",
            "candidate evidence can guide closeout assembly, but source files, observed verification, and operator decisions remain authority",
        )
    )
    return findings


def git_context_trailer_values(
    inventory: Inventory,
    active_plan: Surface | None,
    facts: dict[str, WritebackFact],
) -> list[tuple[str, str]]:
    plan_data = active_plan.frontmatter.data if active_plan and active_plan.exists else {}
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    values: list[tuple[str, str]] = []
    for trailer_name, keys in GIT_CONTEXT_TRAILERS:
        value = _first_trailer_value(plan_data, state_data, facts, keys)
        if value:
            values.append((trailer_name, value))
    return values


def _first_trailer_value(
    plan_data: dict[str, object],
    state_data: dict[str, object],
    facts: dict[str, WritebackFact],
    keys: tuple[str, ...],
) -> str:
    for key in keys:
        for value in (plan_data.get(key), facts.get(key).value if key in facts else "", state_data.get(key)):
            normalized = _normalize_trailer_value(value)
            if normalized:
                return normalized
    return ""


def _normalize_trailer_value(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _git_trailer_suggestion_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    facts = state_writeback_facts(inventory.state)
    source = active_plan.rel_path if active_plan else (inventory.state.rel_path if inventory.state and inventory.state.exists else None)
    findings = [
        Finding(
            "info",
            "evidence-git-trailer-boundary",
            "paste-ready Git trailer suggestions are report text only; evidence does not run Git, stage, commit, amend, push, mutate Git config, install hooks, or write evidence manifests",
            source,
        )
    ]
    values = git_context_trailer_values(inventory, active_plan, facts)
    if not values:
        findings.append(
            Finding(
                "info",
                "evidence-git-trailer-skipped",
                "no plan, phase, or slice metadata is available for paste-ready Git trailer suggestions",
                source,
            )
        )
        return findings
    for trailer_name, value in values:
        findings.append(Finding("info", "evidence-git-trailer", f"suggestion: {trailer_name}: {value}", source))
    return findings


def durable_proof_record_findings(inventory: Inventory, code_prefix: str) -> list[Finding]:
    code = f"{code_prefix}-proof-record"
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "info",
                code,
                "durable proof/evidence record scan is live-root only; product fixtures and archive roots remain non-authority context",
                inventory.state.rel_path if inventory.state and inventory.state.exists else None,
            )
        ]

    records = _durable_proof_record_surfaces(inventory)
    if not records:
        return [
            Finding(
                "info",
                code,
                (
                    "no durable proof/evidence records found at project/verification/*.md; "
                    "the active-plan verification block remains the default evidence surface and absence does not block closeout"
                ),
            )
        ]

    findings: list[Finding] = []
    for record in records[:DURABLE_PROOF_RECORD_LIMIT]:
        status = _record_status(record)
        title = _record_title(record)
        findings.append(
            Finding(
                "info",
                code,
                (
                    f"candidate: durable proof/evidence record: {record.rel_path}; "
                    f"status={status}; title={title}; read-only closeout assembly input only"
                ),
                record.rel_path,
            )
        )
        if record.frontmatter.errors or status == "unrecorded" or title == "untitled":
            findings.append(
                Finding(
                    "warn",
                    f"{code}-ambiguous",
                    (
                        f"ambiguous durable proof/evidence record metadata: {record.rel_path}; "
                        "record status and heading should be explicit before relying on it for closeout assembly"
                    ),
                    record.rel_path,
                )
            )
    if len(records) > DURABLE_PROOF_RECORD_LIMIT:
        findings.append(
            Finding(
                "info",
                code,
                f"durable proof/evidence record scan truncated at {DURABLE_PROOF_RECORD_LIMIT} of {len(records)} records",
            )
        )
    findings.append(
        Finding(
            "info",
            f"{code}-non-authority",
            "durable proof/evidence records are report inputs only; they do not satisfy closeout fields, approve lifecycle changes, or write evidence manifests",
        )
    )
    return findings


def _durable_proof_record_surfaces(inventory: Inventory) -> list[Surface]:
    return sorted(
        (
            surface
            for surface in inventory.present_surfaces
            if surface.memory_route == "verification"
            and surface.rel_path.startswith(DURABLE_PROOF_RECORD_PREFIX)
            and surface.path.suffix.lower() == ".md"
        ),
        key=lambda surface: surface.rel_path,
    )


def _tuple_values(values: object) -> tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, str):
        values = (values,)
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text:
            cleaned.append(text)
    return tuple(cleaned)


def _agent_run_request_findings(inventory: Inventory, request: AgentRunRecordRequest, *, apply: bool) -> list[Finding]:
    severity = "error" if apply else "warn"
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                severity,
                "agent-run-record-refused",
                f"target root kind is {inventory.root_kind}; evidence --record --apply requires a live operating root",
            )
        )
    if not request.record_id:
        findings.append(Finding("error", "agent-run-record-refused", "--record-id is required"))
    elif not RECORD_ID_RE.match(request.record_id):
        findings.append(Finding("error", "agent-run-record-refused", "--record-id may contain only letters, digits, dot, underscore, or dash"))

    for field, value in (
        ("--role", request.role),
        ("--actor", request.actor),
        ("--task", request.task),
        ("--assigned-scope", request.assigned_scope),
        ("--runtime", request.runtime),
        ("--worktree-id", request.worktree_id),
        ("--status", request.status),
        ("--stop-reason", request.stop_reason),
        ("--attempt-budget", request.attempt_budget),
        ("--docs-decision", request.docs_decision),
        ("--residual-risk", request.residual_risk),
    ):
        if not value:
            findings.append(Finding("error", "agent-run-record-refused", f"{field} is required"))

    if request.status and request.status not in AGENT_RUN_STATUSES:
        findings.append(
            Finding(
                "error",
                "agent-run-record-refused",
                f"--status must be one of {', '.join(sorted(AGENT_RUN_STATUSES))}",
            )
        )

    if request.docs_decision and request.docs_decision not in AGENT_RUN_DOCS_DECISIONS:
        findings.append(
            Finding(
                "error",
                "agent-run-record-refused",
                f"--docs-decision must be one of {', '.join(sorted(AGENT_RUN_DOCS_DECISIONS))}",
            )
        )

    for field, values in (
        ("--input-ref", request.input_refs),
        ("--output-ref", request.output_refs),
        ("--claimed-path", request.claimed_paths),
        ("--changed-file", request.changed_files),
        ("--command", request.commands),
        ("--verification-ref", request.verification_refs),
    ):
        if not values:
            findings.append(Finding("error", "agent-run-record-refused", f"{field} must be supplied at least once"))

    for field, values in (
        ("--input-ref", request.input_refs),
        ("--output-ref", request.output_refs),
        ("--claimed-path", request.claimed_paths),
        ("--changed-file", request.changed_files),
        ("--verification-ref", request.verification_refs),
        ("--handoff-ref", request.handoff_refs),
        ("--claim-ref", request.claim_refs),
    ):
        for value in values:
            conflict = _root_relative_path_conflict(value)
            if conflict:
                findings.append(Finding("error", "agent-run-record-refused", f"{field} {conflict}", value))

    if request.record_id:
        target_rel = _agent_run_record_target_rel(request)
        target = inventory.root / target_rel
        findings.extend(_agent_run_record_target_findings(inventory.root, target_rel, severity))
        if target.exists():
            findings.append(Finding(severity, "agent-run-record-refused", "agent run record already exists; choose a new --record-id", target_rel))
    return findings


def _agent_run_record_target_findings(root: Path, target_rel: str, severity: str) -> list[Finding]:
    findings: list[Finding] = []
    conflict = _root_relative_path_conflict(target_rel)
    if conflict:
        return [Finding(severity, "agent-run-record-refused", f"record target {conflict}", target_rel)]
    if not target_rel.startswith(AGENT_RUN_RECORD_PREFIX) or not target_rel.endswith(".md"):
        return [Finding(severity, "agent-run-record-refused", f"record target must be under {AGENT_RUN_RECORD_PREFIX}*.md", target_rel)]
    target = (root / target_rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return [Finding(severity, "agent-run-record-refused", "record target escapes the target root", target_rel)]
    parent = root.resolve()
    rel_parts = Path(target_rel).parts[:-1]
    current = parent
    for part in rel_parts:
        current = current / part
        if current.is_symlink():
            findings.append(Finding(severity, "agent-run-record-refused", f"record target directory contains a symlink segment: {_to_rel_path(root, current)}", target_rel))
            break
        if current.exists() and not current.is_dir():
            findings.append(Finding(severity, "agent-run-record-refused", f"record target directory contains a non-directory segment: {_to_rel_path(root, current)}", target_rel))
            break
    if target.exists() and not target.is_file():
        findings.append(Finding(severity, "agent-run-record-refused", "record target is not a regular file", target_rel))
    return findings


def _render_agent_run_record(root: Path, request: AgentRunRecordRequest) -> tuple[str, list[Finding]]:
    source_hashes, findings = _source_hash_entries(root, request)
    fields: list[tuple[str, object]] = [
        ("schema", AGENT_RUN_SCHEMA),
        ("record_type", "agent-run"),
        ("record_id", request.record_id),
        ("role", request.role),
        ("actor", request.actor),
        ("task", request.task),
        ("assigned_scope", request.assigned_scope),
        ("runtime", request.runtime),
        ("worktree_id", request.worktree_id),
        ("status", request.status),
        ("stop_reason", request.stop_reason),
        ("attempt_budget", request.attempt_budget),
        ("input_refs", request.input_refs),
        ("output_refs", request.output_refs),
        ("claimed_paths", request.claimed_paths),
        ("changed_files", request.changed_files),
        ("commands", request.commands),
        ("verification_refs", request.verification_refs),
        ("docs_decision", request.docs_decision),
        ("residual_risk", request.residual_risk),
        ("handoff_refs", request.handoff_refs),
        ("claim_refs", request.claim_refs),
        ("source_hashes", tuple(source_hashes)),
        ("created_at_utc", _utc_timestamp()),
    ]
    if request.repeated_failure_signature:
        fields.append(("repeated_failure_signature", request.repeated_failure_signature))
    if request.provider:
        fields.append(("provider", request.provider))
    if request.model_id:
        fields.append(("model_id", request.model_id))
    if request.tools:
        fields.append(("tools", request.tools))

    frontmatter = ["---"]
    for key, value in fields:
        frontmatter.extend(_frontmatter_lines(key, value))
    frontmatter.append("---")

    lines = [
        *frontmatter,
        f"# Agent Run Record: {request.record_id}",
        "",
        "This record is source-bound agent work evidence. It cannot approve lifecycle transitions, archive, staging, commit, or next-plan opening.",
        "",
        "## Summary",
        "",
        f"- role: `{request.role}`",
        f"- actor: `{request.actor}`",
        f"- assigned_scope: `{request.assigned_scope}`",
        f"- runtime: `{request.runtime}`",
        f"- worktree_id: `{request.worktree_id}`",
        f"- status: `{request.status}`",
        f"- stop_reason: `{request.stop_reason}`",
        f"- attempt_budget: `{request.attempt_budget}`",
        f"- docs_decision: `{request.docs_decision}`",
        f"- residual_risk: `{request.residual_risk}`",
        "",
        "## Task",
        "",
        request.task,
        "",
        "## Changed Files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in request.changed_files)
    lines.extend(
        [
            "",
            "## Verification",
            "",
        ]
    )
    lines.extend(f"- `{ref}`" for ref in request.verification_refs)
    lines.extend(
        [
            "",
            "## Handoff And Claim Pointers",
            "",
        ]
    )
    if request.handoff_refs or request.claim_refs:
        lines.extend(f"- handoff: `{ref}`" for ref in request.handoff_refs)
        lines.extend(f"- claim: `{ref}`" for ref in request.claim_refs)
    else:
        lines.append("- none recorded")
    lines.extend(
        [
            "",
            "## Commands",
            "",
        ]
    )
    lines.extend(f"- `{command}`" for command in request.commands)
    lines.extend(["", "## Source Hashes", ""])
    lines.extend(f"- `{entry}`" for entry in source_hashes)
    lines.append("")
    return "\n".join(lines), findings


def _frontmatter_lines(key: str, value: object) -> list[str]:
    if isinstance(value, tuple):
        lines = [f"{key}:"]
        lines.extend(f"  - {_quote_yaml(item)}" for item in value)
        return lines
    return [f"{key}: {_quote_yaml(str(value))}"]


def _quote_yaml(value: object) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _source_hash_entries(root: Path, request: AgentRunRecordRequest) -> tuple[list[str], list[Finding]]:
    entries: list[str] = []
    findings: list[Finding] = []
    for rel_path in _source_bound_refs(request):
        conflict = _root_relative_path_conflict(rel_path)
        if conflict:
            entries.append(f"{rel_path} invalid-path")
            findings.append(Finding("warn", "agent-run-record-source-hash", f"{rel_path} was recorded as invalid-path: {conflict}", rel_path))
            continue
        path = root / rel_path
        if not path.exists():
            entries.append(f"{rel_path} missing")
            findings.append(Finding("info", "agent-run-record-source-hash", f"{rel_path} recorded as missing source", rel_path))
            continue
        if not path.is_file():
            entries.append(f"{rel_path} invalid-path")
            findings.append(Finding("warn", "agent-run-record-source-hash", f"{rel_path} is not a regular file and was recorded as invalid-path", rel_path))
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            entries.append(f"{rel_path} unreadable")
            findings.append(Finding("warn", "agent-run-record-source-hash", f"{rel_path} could not be read for hashing: {exc}", rel_path))
            continue
        entries.append(f"{rel_path} sha256={digest}")
        findings.append(Finding("info", "agent-run-record-source-hash", f"{rel_path} sha256={digest[:12]}", rel_path))
    return entries, findings


def _source_bound_refs(request: AgentRunRecordRequest) -> tuple[str, ...]:
    refs: list[str] = []
    seen: set[str] = set()
    for rel_path in (
        *request.input_refs,
        *request.output_refs,
        *request.claimed_paths,
        *request.changed_files,
        *request.verification_refs,
        *request.handoff_refs,
        *request.claim_refs,
    ):
        normalized = rel_path.replace("\\", "/").strip()
        if normalized and normalized not in seen:
            refs.append(normalized)
            seen.add(normalized)
    return tuple(refs)


def _agent_run_record_metadata_findings(
    rel_path: str,
    frontmatter: Frontmatter,
    data: dict[str, object],
    code_prefix: str,
) -> list[Finding]:
    code = f"{code_prefix}-record-malformed"
    findings: list[Finding] = []
    if not frontmatter.has_frontmatter:
        return [Finding("warn", code, "agent run record is missing frontmatter", rel_path)]
    for error in frontmatter.errors:
        findings.append(Finding("warn", code, error, rel_path))
    for field in AGENT_RUN_REQUIRED_SCALARS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            findings.append(Finding("warn", code, f"agent run record missing required field: {field}", rel_path))
    if data.get("schema") != AGENT_RUN_SCHEMA:
        findings.append(Finding("warn", code, f"agent run record schema should be {AGENT_RUN_SCHEMA}", rel_path))
    if data.get("record_type") != "agent-run":
        findings.append(Finding("warn", code, "agent run record record_type should be agent-run", rel_path))
    status = str(data.get("status") or "").strip()
    if status and status not in AGENT_RUN_STATUSES:
        findings.append(Finding("warn", code, f"agent run record status is unsupported: {status}", rel_path))
    docs_decision = str(data.get("docs_decision") or "").strip()
    if docs_decision and docs_decision not in AGENT_RUN_DOCS_DECISIONS:
        findings.append(Finding("warn", code, f"agent run record docs_decision is unsupported: {docs_decision}", rel_path))
    for field in AGENT_RUN_REQUIRED_LISTS:
        values = _frontmatter_string_list(data.get(field))
        if not values:
            findings.append(Finding("warn", code, f"agent run record missing required list field: {field}", rel_path))
    for field in ("input_refs", "output_refs", "claimed_paths", "changed_files", "verification_refs", "handoff_refs", "claim_refs"):
        for value in _frontmatter_string_list(data.get(field)):
            conflict = _root_relative_path_conflict(value)
            if conflict:
                findings.append(Finding("warn", code, f"agent run record {field} path {conflict}: {value}", rel_path))
    return findings


def _agent_run_source_hash_findings(root: Path, rel_path: str, data: dict[str, object], code_prefix: str) -> list[Finding]:
    code = f"{code_prefix}-record"
    findings: list[Finding] = []
    for entry in _frontmatter_string_list(data.get("source_hashes")):
        match = SOURCE_HASH_RE.match(entry.strip())
        if not match:
            findings.append(Finding("warn", f"{code}-malformed", f"malformed source_hashes entry: {entry}", rel_path))
            continue
        source_rel = match.group(1).strip()
        expected_hash = match.group(2)
        expected_missing = bool(match.group(3))
        expected_unreadable = bool(match.group(4))
        expected_invalid = bool(match.group(5))
        conflict = _root_relative_path_conflict(source_rel)
        if conflict:
            findings.append(Finding("warn", f"{code}-malformed", f"source hash path {conflict}: {source_rel}", rel_path))
            continue
        source_path = root / source_rel
        if expected_missing:
            if source_path.exists():
                findings.append(Finding("warn", f"{code}-stale", f"source hash recorded missing path now exists: {source_rel}", rel_path))
            continue
        if expected_unreadable or expected_invalid:
            findings.append(Finding("info", f"{code}-hash", f"source hash entry records {source_rel} as degraded evidence", rel_path))
            continue
        if not source_path.exists():
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is now missing: {source_rel}", rel_path))
            continue
        if not source_path.is_file():
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is no longer a regular file: {source_rel}", rel_path))
            continue
        try:
            current_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except OSError as exc:
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is now unreadable: {source_rel}: {exc}", rel_path))
            continue
        if expected_hash and current_hash.lower() != expected_hash.lower():
            findings.append(
                Finding(
                    "warn",
                    f"{code}-stale",
                    f"source hash mismatch for {source_rel}: expected={expected_hash[:12]} current={current_hash[:12]}",
                    rel_path,
                )
            )
        else:
            findings.append(Finding("info", f"{code}-hash", f"source hash current for {source_rel}: {current_hash[:12]}", rel_path))
    return findings


def _frontmatter_string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _agent_run_record_paths(root: Path) -> list[Path]:
    directory = root / AGENT_RUNS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(directory.glob("*.md"))


def _coordination_record_paths(root: Path) -> list[Path]:
    records: list[Path] = []
    for directory_rel in COORDINATION_RECORD_DIRS:
        directory = root / directory_rel
        if not directory.exists() or not directory.is_dir():
            continue
        records.extend(path for path in directory.iterdir() if path.is_file() and path.suffix == ".json")
    return sorted(records)


def _agent_run_record_target_rel(request: AgentRunRecordRequest) -> str:
    return f"{AGENT_RUN_RECORD_PREFIX}{request.record_id}.md"


def _agent_run_record_boundary_findings(code_prefix: str = "agent-run-record") -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "agent run records are evidence only; they cannot approve lifecycle transitions, archive, roadmap status, staging, commit, rollback, or next-plan opening",
            AGENT_RUNS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-route",
            "agent run records live under project/verification/agent-runs/*.md and no hidden runtime, queue, database, cache, adapter state, or provider gateway is created",
            AGENT_RUNS_DIR_REL,
        ),
    ]


def _root_relative_path_conflict(rel_path: str) -> str:
    normalized = str(rel_path or "").replace("\\", "/").strip()
    if not normalized:
        return "must be a non-empty root-relative path"
    if re.match(r"^[A-Za-z]:[\\/]", normalized) or normalized.startswith("/"):
        return "must be root-relative, not absolute"
    if any(part in {"..", ""} for part in normalized.split("/")):
        return "must not contain parent traversal or empty path segments"
    return ""


def _to_rel_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_status(surface: Surface) -> str:
    status = surface.frontmatter.data.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return "unrecorded"


def _record_title(surface: Surface) -> str:
    if surface.headings:
        return surface.headings[0].title
    return "untitled"


def _active_plan_findings(inventory: Inventory, active_plan: Surface | None, state_data: dict[str, object]) -> list[Finding]:
    state = inventory.state
    plan_status = str(state_data.get("plan_status") or "")
    configured_plan = str(state_data.get("active_plan") or inventory.manifest.get("memory", {}).get("plan_file", "project/implementation-plan.md"))
    if active_plan:
        return [
            Finding(
                "info",
                "evidence-active-plan",
                f"candidate: active plan present: {active_plan.rel_path}",
                active_plan.rel_path,
            )
        ]
    if plan_status == "active":
        return [
            Finding(
                "warn",
                "evidence-active-plan",
                f"missing: plan_status is active but active plan is not readable: {configured_plan}",
                state.rel_path if state else configured_plan,
            )
        ]
    return [
        Finding(
            "info",
            "evidence-active-plan",
            "no active plan is required by current state",
            state.rel_path if state else None,
        )
    ]


def _source_set_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    if not active_plan:
        return [
            Finding(
                "info",
                "evidence-source-set",
                "source-set scan skipped because no active plan is present",
            )
        ]
    cues = find_cues(active_plan, "source-set", "source-set candidate", (r"\bsource set\b", r"\bsource_set\b"))
    if not cues:
        return [
            Finding(
                "warn",
                "evidence-source-set",
                "missing: active plan has no source-set candidate",
                active_plan.rel_path,
            )
        ]
    return cue_findings("evidence-source-set", "source-set candidate", cues)


def _anchor_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    if not active_plan:
        return [
            Finding(
                "info",
                "evidence-anchor-missing",
                "anchor scan skipped because no active plan is present",
            )
        ]
    findings: list[Finding] = []
    for anchor_name, patterns in ANCHOR_PATTERNS:
        cues = find_cues(active_plan, f"{anchor_name}-anchor", f"{anchor_name} anchor candidate", patterns)
        if cues:
            findings.extend(cue_findings("evidence-anchor-candidate", f"{anchor_name} anchor candidate", cues, limit=2))
        else:
            findings.append(
                Finding(
                    "warn",
                    "evidence-anchor-missing",
                    f"missing: {anchor_name} anchor candidate not found in active plan",
                    active_plan.rel_path,
                )
            )
    return findings


def _identity_findings(active_plan: Surface | None) -> list[Finding]:
    if not active_plan:
        return [
            Finding(
                "info",
                "evidence-identity",
                "cue identity scan skipped because no active plan is present; persistent evidence manifest remains deferred and no evidence manifest was written",
            )
        ]
    return [
        Finding(
            "info",
            "evidence-identity",
            "report-only cue identity uses kind, source path, line number, normalized preview, and a deterministic hash; persistent evidence manifest remains deferred and no generated report is written",
            active_plan.rel_path,
        )
    ]


def _closeout_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    policy = inventory.manifest.get("policy", {}) if isinstance(inventory.manifest, dict) else {}
    closeout_commit = policy.get("closeout_commit")
    facts = current_state_writeback_facts(inventory)
    if closeout_commit:
        findings.append(
            Finding(
                "info",
                "evidence-closeout-candidate",
                f"candidate: manifest closeout_commit policy is {closeout_commit}",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else None,
            )
        )

    if not active_plan and not facts:
        findings.append(
            Finding(
                "info",
                "evidence-closeout-missing",
                "closeout field scan skipped because no active plan is present",
            )
        )
        return findings

    for field in CLOSEOUT_FIELD_NAMES:
        fact = facts.get(field)
        if fact:
            findings.append(_writeback_fact_finding("evidence-closeout-candidate", f"{field} candidate", fact))
            continue
        if not active_plan:
            findings.append(
                Finding(
                    "warn",
                    "evidence-closeout-missing",
                    f"missing: concrete closeout field candidate not found: {field}",
                )
            )
            continue
        concrete, broad = closeout_field_cues(active_plan, field)
        if concrete:
            findings.extend(cue_findings("evidence-closeout-candidate", f"{field} candidate", concrete, limit=2))
        else:
            findings.append(
                Finding(
                    "warn",
                    "evidence-closeout-missing",
                    f"missing: concrete closeout field candidate not found: {field}",
                    active_plan.rel_path,
                )
            )
            if broad:
                findings.extend(cue_findings("evidence-closeout-context", f"{field} context", broad, limit=2))
    return findings


def _writeback_fact_finding(code: str, label: str, fact: WritebackFact) -> Finding:
    return Finding(
        "info",
        code,
        f"candidate: {label}: - {fact.field}: {fact.value}; source={fact.source}:{fact.line}",
        fact.source,
        fact.line,
    )


def _quality_cue_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    facts = current_state_writeback_facts(inventory)
    if not active_plan and not facts:
        return [
            Finding(
                "info",
                "evidence-quality-cue",
                "quality cue scan skipped because no active plan is present; no quality-gate state was written",
            )
        ]
    missing = [
        field
        for field in CLOSEOUT_FIELD_NAMES
        if field not in facts and (not active_plan or not closeout_field_cues(active_plan, field)[0])
    ]
    fact_source = active_plan.rel_path if active_plan else (inventory.state.rel_path if inventory.state and inventory.state.exists else None)
    if missing:
        return [
            Finding(
                "warn",
                "evidence-quality-cue",
                f"report-only closeout readiness cue: concrete field evidence missing for {', '.join(missing)}; this does not approve or block lifecycle decisions",
                fact_source,
            )
        ]
    return [
        Finding(
            "info",
            "evidence-quality-cue",
            "report-only closeout readiness cue: concrete closeout field evidence is present; operator decisions and observed verification remain required",
            fact_source,
        )
    ]


def _acceptance_evidence_findings(inventory: Inventory, state_data: dict[str, object]) -> list[Finding]:
    if str(state_data.get("phase_status") or "") != "complete":
        return []
    facts = current_state_writeback_facts(inventory)
    values = {field: fact.value for field, fact in facts.items()}
    return acceptance_evidence_findings(
        inventory,
        values,
        completion_reason="completed active-plan phase",
        apply=False,
        code_prefix="evidence",
        include_success=True,
    )


def _operator_required_findings(inventory: Inventory) -> list[Finding]:
    source = inventory.manifest_surface.rel_path if inventory.manifest_surface and inventory.manifest_surface.exists else None
    return [
        Finding(
            "info",
            "evidence-operator-required",
            "operator-required: collect worktree_start_state before closeout; evidence does not run Git or VCS commands",
            source,
        ),
        Finding(
            "info",
            "evidence-operator-required",
            "operator-required: classify task_scope before closeout from the actual work performed",
            source,
        ),
    ]


def _line_group_findings(
    active_plan: Surface | None,
    code: str,
    label: str,
    patterns: Iterable[str],
    inventory: Inventory,
) -> list[Finding]:
    fact_key = "residual_risk" if "residual" in label else "carry_forward" if "carry" in label else ""
    fact = current_state_writeback_facts(inventory).get(fact_key) if fact_key else None
    if fact:
        return [_writeback_fact_finding(code, f"{label} candidate", fact)]
    if fact_key == "carry_forward":
        historical = satisfied_post_archive_carry_forward_finding(inventory, code)
        if historical:
            return [historical]
    if not active_plan:
        return [Finding("info", code, f"{label} scan skipped because no active plan is present")]
    cues = find_cues(active_plan, label.replace(" ", "-"), f"{label} candidate", patterns)
    if not cues:
        return [Finding("warn", code, f"missing: {label} candidate not found in active plan", active_plan.rel_path)]
    return cue_findings(code, f"{label} candidate", cues)
