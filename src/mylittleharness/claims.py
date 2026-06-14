from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory
from .models import Finding
from .parsing import parse_frontmatter
from .root_boundary import record_id_conflict, root_relative_path_conflict, source_path_boundary_violation


WORK_CLAIM_SCHEMA = "mylittleharness.work-claim.v1"
WORK_CLAIM_COMPLETION_POLICY_SCHEMA = "mylittleharness.work-claim.completion-policy.v1"
WORK_CLAIMS_DIR_REL = "project/verification/work-claims"
WORK_CLAIM_STATUSES = {"active", "released", "stale", "conflicted"}
WORK_CLAIM_KINDS = {
    "read",
    "write",
    "lifecycle",
    "route",
    "path",
    "resource",
    "port",
    "database",
    "external_service",
    "generated_cache",
}
EXCLUSIVE_CLAIM_KINDS = {"write", "lifecycle", "route", "path", "resource", "port", "database", "external_service"}
WORK_CLAIM_REQUIRED_SCALARS = ("claim_id", "claim_kind", "owner_role", "owner_actor", "execution_slice", "status")
WORK_CLAIM_SCOPE_FIELDS = ("claimed_routes", "claimed_paths", "claimed_resources")
WORK_CLAIM_COMPLETION_POLICY_AUTHORITY_FIELDS = (
    "external_done_claims_authoritative",
    "external_tracker_status_authoritative",
    "linear_status_authority",
    "runtime_memory_authority",
    "approves_lifecycle",
    "approves_roadmap_done",
    "approves_archive",
    "approves_git",
)
WORK_CLAIM_COMPLETION_REQUIRED_EVIDENCE = ("release_condition", "work-claim", "handoff", "agent-run")
WORK_CLAIM_COMPLETION_REQUIRED_ROUTES = ("claim", "handoff", "evidence")
WORK_CLAIM_MUTATION_LOCK_NAME = ".work-claim-mutation.lock"
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
COMPLETION_EVIDENCE_REF_RE = re.compile(r"(project/verification/(?:work-claims|handoffs|agent-runs|task-sessions)/[A-Za-z0-9._/-]+(?:\.(?:json|md))?)")
FAN_IN_HANDOFFS_DIR_REL = "project/verification/handoffs"
FAN_IN_AGENT_RUNS_DIR_REL = "project/verification/agent-runs"
FAN_IN_HANDOFF_SCHEMA = "mylittleharness.handoff-packet.v1"
FAN_IN_AGENT_RUN_SCHEMA = "mylittleharness.agent-run.v1"
FAN_IN_AGENT_RUN_SUCCESS_STATUSES = {"succeeded"}
FAN_IN_AGENT_RUN_DOCS_DECISIONS = {"updated", "not-needed", "uncertain"}
FAN_IN_AGENT_RUN_REQUIRED_LISTS = ("input_refs", "output_refs", "claimed_paths", "changed_files", "commands", "verification_refs", "source_hashes")
FAN_IN_HIGH_BLAST_DIRTY_PATH_THRESHOLD = 8
FAN_IN_HIGH_BLAST_CLUSTER_THRESHOLD = 4
FAN_IN_HIGH_BLAST_EXCLUDED_PREFIXES = (".agents/", ".codex/", ".mylittleharness/")
FAN_IN_BOOLEAN_METADATA_FIELDS = (
    "fan_in_required",
    "fan_in_evidence_required",
    "coordination_required",
    "delegated",
    "concurrent",
    "multi_agent",
    "parallel_agents",
    "high_blast",
)
FAN_IN_MODE_METADATA_FIELDS = (
    "agent_topology",
    "blast_radius",
    "coordination_mode",
    "execution_mode",
    "work_mode",
)
FAN_IN_ACTIVATING_MODE_TERMS = {
    "delegated",
    "concurrent",
    "high",
    "high-blast",
    "high blast",
    "multi-agent",
    "multiagent",
    "parallel",
    "worker",
    "workers",
}
FAN_IN_SOURCE_HASH_RE = re.compile(r"^(.+?)\s+(?:sha256=([a-fA-F0-9]{64})|(missing)|(unreadable)|(invalid-path))$")
FAN_IN_BLOCKING_RESIDUAL_TERMS = {
    "blocker",
    "blocking",
    "blocked",
    "danger",
    "failed",
    "failure",
    "must-fix",
    "regression",
    "unresolved",
    "unsafe",
}
FAN_IN_NONBLOCKING_RESIDUALS = {"", "n/a", "no", "none", "not-needed", "not needed"}


@dataclass(frozen=True)
class WorkClaimRequest:
    action: str
    claim_id: str
    claim_kind: str
    owner_role: str
    owner_actor: str
    execution_slice: str
    worktree_id: str
    base_revision: str
    claimed_routes: tuple[str, ...]
    claimed_paths: tuple[str, ...]
    claimed_resources: tuple[str, ...]
    lease_expires_at: str
    ttl: str
    release_condition: str


@dataclass(frozen=True)
class WorkClaimRecord:
    rel_path: str
    data: dict[str, object]

    @property
    def claim_id(self) -> str:
        return str(self.data.get("claim_id") or "")

    @property
    def status(self) -> str:
        return str(self.data.get("status") or "")

    @property
    def claim_kind(self) -> str:
        return str(self.data.get("claim_kind") or "")

    @property
    def claimed_routes(self) -> tuple[str, ...]:
        return _string_tuple(self.data.get("claimed_routes"))

    @property
    def claimed_paths(self) -> tuple[str, ...]:
        return _string_tuple(self.data.get("claimed_paths"))

    @property
    def claimed_resources(self) -> tuple[str, ...]:
        return _string_tuple(self.data.get("claimed_resources"))

    @property
    def lease_expires_at(self) -> str:
        return str(self.data.get("lease_expires_at") or "")


@dataclass(frozen=True)
class FanInEvidenceGate:
    activated: bool
    reasons: tuple[str, ...]
    missing: tuple[str, ...]
    claim_refs: tuple[str, ...] = ()
    handoff_refs: tuple[str, ...] = ()
    agent_run_refs: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if not self.activated:
            return "not-required"
        reason_text = _sample_text(self.reasons)
        if self.missing:
            blocker_text = f"; blockers={_sample_text(self.blockers)}" if self.blockers else ""
            return f"missing:{','.join(self.missing)}; activated_by={reason_text}{blocker_text}"
        return (
            f"present; claims={len(self.claim_refs)}; handoffs={len(self.handoff_refs)}; "
            f"agent_runs={len(self.agent_run_refs)}; activated_by={reason_text}"
        )


@dataclass(frozen=True)
class _WorkClaimMutationLock:
    path: Path
    fd: int


class WorkClaimMutationLockError(OSError):
    pass


def fan_in_evidence_gate(
    root: Path,
    plan_data: dict[str, object],
    *,
    product_diff_proof: dict[str, object] | None = None,
) -> FanInEvidenceGate:
    execution_slice = _fan_in_execution_slice(plan_data)
    reasons = _fan_in_activation_reasons(plan_data, product_diff_proof)
    if not reasons:
        return FanInEvidenceGate(activated=False, reasons=(), missing=())

    claim_refs, claim_blockers = _fan_in_matching_claim_refs(root, execution_slice)
    handoff_refs, handoff_blockers = _fan_in_matching_handoff_refs(root, execution_slice)
    agent_run_refs, agent_run_blockers = _fan_in_matching_agent_run_refs(root, execution_slice, claim_refs, handoff_refs)
    overlap_blockers = _fan_in_active_overlap_blockers(root)
    missing = []
    if not claim_refs:
        missing.append("released-work-claim" if claim_blockers else "work-claim")
    if not handoff_refs:
        missing.append("accepted-handoff" if handoff_blockers else "handoff")
    if not agent_run_refs:
        missing.append("fresh-agent-run" if agent_run_blockers else "agent-run")
    if overlap_blockers:
        missing.append("overlap-claim")
    return FanInEvidenceGate(
        activated=True,
        reasons=reasons,
        missing=tuple(missing),
        claim_refs=claim_refs,
        handoff_refs=handoff_refs,
        agent_run_refs=agent_run_refs,
        blockers=tuple((*claim_blockers, *handoff_blockers, *agent_run_blockers, *overlap_blockers)),
    )


def make_work_claim_request(args: object) -> WorkClaimRequest:
    return WorkClaimRequest(
        action=str(getattr(args, "action", "") or "").strip() or "create",
        claim_id=str(getattr(args, "claim_id", "") or "").strip(),
        claim_kind=str(getattr(args, "claim_kind", "") or "").strip() or "write",
        owner_role=str(getattr(args, "owner_role", "") or "").strip(),
        owner_actor=str(getattr(args, "owner_actor", "") or "").strip(),
        execution_slice=str(getattr(args, "execution_slice", "") or "").strip(),
        worktree_id=str(getattr(args, "worktree_id", "") or "").strip(),
        base_revision=str(getattr(args, "base_revision", "") or "").strip(),
        claimed_routes=_tuple_values(getattr(args, "claimed_routes", ())),
        claimed_paths=_tuple_values(getattr(args, "claimed_paths", ())),
        claimed_resources=_tuple_values(getattr(args, "claimed_resources", ())),
        lease_expires_at=str(getattr(args, "lease_expires_at", "") or "").strip(),
        ttl=str(getattr(args, "ttl", "") or "").strip(),
        release_condition=str(getattr(args, "release_condition", "") or "").strip(),
    )


def work_claim_completion_policy_payload() -> dict[str, object]:
    return {
        "schema": WORK_CLAIM_COMPLETION_POLICY_SCHEMA,
        "decision": "repo-visible-evidence-only",
        "external_done_claims_authoritative": False,
        "external_tracker_status_authoritative": False,
        "external_tracker_mutation": False,
        "linear_status_authority": False,
        "runtime_memory_authority": False,
        "requires_release_condition": True,
        "requires_repo_visible_evidence": True,
        "required_evidence": list(WORK_CLAIM_COMPLETION_REQUIRED_EVIDENCE),
        "required_routes": list(WORK_CLAIM_COMPLETION_REQUIRED_ROUTES),
        "approves_lifecycle": False,
        "approves_roadmap_done": False,
        "approves_archive": False,
        "approves_git": False,
    }


def work_claim_dry_run_findings(inventory: Inventory, request: WorkClaimRequest) -> list[Finding]:
    findings = [
        Finding("info", "work-claim-dry-run", "work claim proposal only; no files were written"),
        Finding("info", "work-claim-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    findings.extend(_completion_policy_findings(request))
    findings.extend(_request_findings(inventory, request, apply=False))
    if any(finding.severity in {"warn", "error"} for finding in findings if finding.code == "work-claim-refused"):
        findings.append(Finding("info", "work-claim-validation-posture", "dry-run refused before apply; fix explicit claim fields before writing claim evidence"))
        findings.extend(_boundary_findings())
        return findings

    if request.action == "release":
        current, read_findings = _load_claim_record_for_mutation(inventory.root, request.claim_id, severity="warn")
        findings.extend(read_findings)
        if current is None:
            findings.append(Finding("info", "work-claim-validation-posture", "dry-run refused before apply; fix explicit claim fields before writing claim evidence"))
            findings.extend(_boundary_findings())
            return findings
        text = _claim_json({**current.data, **_release_fields(request)})
        findings.append(Finding("info", "work-claim-target", f"would release work claim: {_claim_rel_path(request.claim_id)}", _claim_rel_path(request.claim_id)))
        findings.append(_route_write_finding(_claim_rel_path(request.claim_id), current.data, json.loads(text), apply=False))
    elif request.action == "extend":
        current, read_findings = _load_claim_record_for_mutation(inventory.root, request.claim_id, severity="warn")
        findings.extend(read_findings)
        if current is None:
            findings.append(Finding("info", "work-claim-validation-posture", "dry-run refused before apply; fix explicit claim fields before writing claim evidence"))
            findings.extend(_boundary_findings())
            return findings
        text = _claim_json({**current.data, **_extend_fields(request)})
        findings.append(Finding("info", "work-claim-target", f"would extend work claim: {_claim_rel_path(request.claim_id)}", _claim_rel_path(request.claim_id)))
        findings.append(_route_write_finding(_claim_rel_path(request.claim_id), current.data, json.loads(text), apply=False))
    else:
        record = _created_claim_record(request)
        text = _claim_json(record)
        findings.append(Finding("info", "work-claim-target", f"would write work claim: {_claim_rel_path(request.claim_id)}", _claim_rel_path(request.claim_id)))
        findings.append(
            Finding(
                "info",
                "work-claim-route-write",
                (
                    f"would create route {_claim_rel_path(request.claim_id)}; before_hash=missing; "
                    f"after_hash={_short_hash(text)}; before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; "
                    "source-bound write evidence is independent of Git tracking"
                ),
                _claim_rel_path(request.claim_id),
            )
        )
    findings.extend(_scope_findings(request))
    findings.extend(_boundary_findings())
    return findings


def work_claim_apply_findings(inventory: Inventory, request: WorkClaimRequest) -> list[Finding]:
    findings = [
        Finding("info", "work-claim-apply", "work claim apply started"),
        Finding("info", "work-claim-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    findings.extend(_completion_policy_findings(request))
    request_findings = _request_findings(inventory, request, apply=True)
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "work-claim-apply-refused", "work claim apply refused before writing claim evidence"))
        findings.extend(_boundary_findings())
        return findings

    try:
        mutation_lock = _acquire_work_claim_mutation_lock(inventory.root)
    except WorkClaimMutationLockError as exc:
        findings.append(Finding("error", "work-claim-refused", str(exc), _work_claim_mutation_lock_rel_path()))
        findings.append(Finding("info", "work-claim-apply-refused", "work claim apply refused before writing claim evidence"))
        findings.extend(_boundary_findings())
        return findings

    try:
        locked_findings = _request_findings(inventory, request, apply=True)
        locked_errors = [finding for finding in locked_findings if finding.severity == "error"]
        if locked_errors:
            findings.extend(locked_errors)
            findings.append(Finding("info", "work-claim-apply-refused", "work claim apply refused after rechecking current claim records under the mutation lock"))
            findings.extend(_boundary_findings())
            return findings

        rel_path = _claim_rel_path(request.claim_id)
        target = inventory.root / rel_path
        if request.action == "release":
            current, read_findings = _load_claim_record_for_mutation(inventory.root, request.claim_id, severity="error")
            findings.extend(read_findings)
            if current is None:
                findings.append(Finding("info", "work-claim-apply-refused", "work claim apply refused before writing claim evidence"))
                findings.extend(_boundary_findings())
                return findings
            before_data = current.data
            after_data = {**before_data, **_release_fields(request)}
        elif request.action == "extend":
            current, read_findings = _load_claim_record_for_mutation(inventory.root, request.claim_id, severity="error")
            findings.extend(read_findings)
            if current is None:
                findings.append(Finding("info", "work-claim-apply-refused", "work claim apply refused before writing claim evidence"))
                findings.extend(_boundary_findings())
                return findings
            before_data = current.data
            after_data = {**before_data, **_extend_fields(request)}
        else:
            before_data = None
            after_data = _created_claim_record(request)

        text = _claim_json(after_data)
        try:
            cleanup_warnings = apply_file_transaction(
                (
                    AtomicFileWrite(
                        target_path=target,
                        tmp_path=target.with_name(f".{target.name}.tmp"),
                        text=text,
                        backup_path=target.with_name(f".{target.name}.bak"),
                    ),
                ),
                root=inventory.root,
            )
        except FileTransactionError as exc:
            findings.append(Finding("error", "work-claim-refused", f"failed to write work claim before apply completed: {exc}", rel_path))
            findings.extend(_boundary_findings())
            return findings

        if request.action == "release":
            findings.append(Finding("info", "work-claim-released", f"released work claim: {rel_path}", rel_path))
        elif request.action == "extend":
            findings.append(Finding("info", "work-claim-extended", f"extended work claim lease: {rel_path}", rel_path))
        else:
            findings.append(Finding("info", "work-claim-written", f"created work claim: {rel_path}", rel_path))
        findings.append(_route_write_finding(rel_path, before_data, after_data, apply=True))
        for warning in cleanup_warnings:
            findings.append(Finding("warn", "work-claim-backup-cleanup", warning, rel_path))
        findings.extend(_scope_findings(request))
        findings.extend(_boundary_findings())
        return findings
    finally:
        _release_work_claim_mutation_lock(mutation_lock)


def work_claim_status_findings(inventory: Inventory, code_prefix: str = "work-claim") -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "info",
                f"{code_prefix}-status",
                "work claim status scan is live-root only; product fixtures and archive roots remain non-authority context",
            ),
            *_boundary_findings(code_prefix),
        ]
    records, warnings = _load_claim_records(inventory.root)
    findings: list[Finding] = [*warnings]
    if not records:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-status",
                f"no work claim records found at {WORK_CLAIMS_DIR_REL}/*.json; claims are optional evidence and absence does not block closeout",
                WORK_CLAIMS_DIR_REL,
            )
        )
        findings.extend(_boundary_findings(code_prefix))
        return findings

    for record in records:
        stale = _claim_is_stale(record)
        severity = "warn" if stale and record.status == "active" else "info"
        code = f"{code_prefix}-stale" if stale and record.status == "active" else f"{code_prefix}-status"
        status = "stale" if stale and record.status == "active" else record.status
        findings.append(
            Finding(
                severity,
                code,
                (
                    f"claim_id={record.claim_id or '<missing>'}; status={status or '<missing>'}; "
                    f"kind={record.claim_kind or '<missing>'}; routes={len(record.claimed_routes)}; "
                    f"paths={len(record.claimed_paths)}; resources={len(record.claimed_resources)}; "
                    "read-only claim evidence only"
                ),
                record.rel_path,
            )
        )
        findings.extend(_record_metadata_findings(record, code_prefix))
        findings.extend(_record_completion_policy_findings(record, code_prefix))
    findings.extend(work_claim_active_overlap_findings(records, code_prefix))
    findings.extend(_boundary_findings(code_prefix))
    return findings


def work_claim_record_hashes(root: Path, refs: tuple[str, ...]) -> tuple[list[str], list[Finding]]:
    hashes: list[str] = []
    findings: list[Finding] = []
    for ref in refs:
        normalized = _normalize_ref(ref)
        conflict = _root_relative_path_conflict(normalized)
        if conflict:
            hashes.append(f"{ref} invalid-path")
            findings.append(Finding("warn", "work-claim-ref-hash", f"{ref} was recorded as invalid-path: {conflict}", ref))
            continue
        path = root / normalized
        if not path.exists():
            hashes.append(f"{normalized} missing")
            findings.append(Finding("warn", "work-claim-ref-hash", f"{normalized} is missing", normalized))
            continue
        if not path.is_file() or path.is_symlink():
            hashes.append(f"{normalized} invalid-path")
            findings.append(Finding("warn", "work-claim-ref-hash", f"{normalized} is not a regular file", normalized))
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes.append(f"{normalized} sha256={digest}")
        findings.append(Finding("info", "work-claim-ref-hash", f"{normalized} sha256={digest[:12]}", normalized))
    return hashes, findings


def work_claim_record_metadata_findings(data: dict[str, object], rel_path: str, code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    if data.get("schema") != WORK_CLAIM_SCHEMA:
        findings.append(Finding("warn", f"{code_prefix}-malformed", f"work claim schema should be {WORK_CLAIM_SCHEMA}", rel_path))
    if data.get("record_type") != "work-claim":
        findings.append(Finding("warn", f"{code_prefix}-malformed", "work claim record_type should be work-claim", rel_path))

    for field in WORK_CLAIM_REQUIRED_SCALARS:
        if not str(data.get(field) or "").strip():
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"work claim {field} is required", rel_path))

    claim_id = str(data.get("claim_id") or "").strip()
    if claim_id and not ID_RE.match(claim_id):
        findings.append(Finding("warn", f"{code_prefix}-malformed", "work claim claim_id may contain only letters, digits, dot, underscore, or dash", rel_path))
    elif claim_id and record_id_conflict(claim_id):
        findings.append(Finding("warn", f"{code_prefix}-malformed", f"work claim claim_id {record_id_conflict(claim_id)}", rel_path))
    claim_kind = str(data.get("claim_kind") or "").strip()
    if claim_kind and claim_kind not in WORK_CLAIM_KINDS:
        findings.append(Finding("warn", f"{code_prefix}-malformed", f"unsupported work claim kind: {claim_kind}", rel_path))
    status = str(data.get("status") or "").strip()
    if status and status not in WORK_CLAIM_STATUSES:
        findings.append(Finding("warn", f"{code_prefix}-malformed", f"unsupported work claim status: {status}", rel_path))

    scoped_values: list[str] = []
    for field in WORK_CLAIM_SCOPE_FIELDS:
        raw_value = data.get(field)
        if raw_value not in (None, "") and not isinstance(raw_value, list):
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"work claim {field} must be a list of strings", rel_path))
        scoped_values.extend(_string_tuple(raw_value))
    if not scoped_values:
        findings.append(Finding("warn", f"{code_prefix}-malformed", "work claim requires at least one claimed route, path, or resource", rel_path))

    for rel in _string_tuple(data.get("claimed_paths")):
        conflict = _root_relative_path_conflict(rel)
        if conflict:
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"work claim claimed_path {conflict}", rel_path))

    lease = str(data.get("lease_expires_at") or "").strip()
    if lease and _parse_utc_timestamp(lease) is None:
        findings.append(Finding("warn", f"{code_prefix}-malformed", "work claim lease_expires_at is not a valid UTC timestamp", rel_path))
    findings.extend(_completion_policy_metadata_findings(data, rel_path, code_prefix))
    return findings


def work_claim_active_overlap_findings(records: list[WorkClaimRecord], code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    for index, left in enumerate(records):
        if left.status != "active" or left.claim_kind not in EXCLUSIVE_CLAIM_KINDS:
            continue
        for right in records[index + 1 :]:
            if right.status != "active" or right.claim_kind not in EXCLUSIVE_CLAIM_KINDS:
                continue
            overlap = _claim_overlap_records(left, right)
            if not overlap:
                continue
            left_id = left.claim_id or Path(left.rel_path).stem
            right_id = right.claim_id or Path(right.rel_path).stem
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-overlap",
                    (
                        f"overlapping active work claims {left_id} and {right_id}: {overlap}; "
                        "release or narrow one claim before fan-in or additional overlapping work"
                    ),
                    left.rel_path,
                )
            )
    return findings


def _request_findings(inventory: Inventory, request: WorkClaimRequest, *, apply: bool) -> list[Finding]:
    severity = "error" if apply else "warn"
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(Finding(severity, "work-claim-refused", f"target root kind is {inventory.root_kind}; work claim writes require a live operating root"))
    if request.action not in {"create", "extend", "release"}:
        findings.append(Finding("error", "work-claim-refused", "--action must be create, extend, or release"))
    if not request.claim_id:
        findings.append(Finding("error", "work-claim-refused", "--claim-id is required"))
    elif not ID_RE.match(request.claim_id):
        findings.append(Finding("error", "work-claim-refused", "--claim-id may contain only letters, digits, dot, underscore, or dash"))
    elif record_id_conflict(request.claim_id):
        findings.append(Finding("error", "work-claim-refused", f"--claim-id {record_id_conflict(request.claim_id)}"))
    lease_findings = _lease_request_findings(request)
    findings.extend(lease_findings)
    if request.action == "release":
        target = inventory.root / _claim_rel_path(request.claim_id)
        if not request.release_condition:
            source = _claim_rel_path(request.claim_id) if request.claim_id else WORK_CLAIMS_DIR_REL
            findings.append(
                Finding(
                    severity,
                    "work-claim-refused",
                    (
                        "release requires --release-condition citing repo-visible evidence or reviewed abandonment; "
                        "external completion claims without evidence are refused"
                    ),
                    source,
                )
            )
        if request.claim_id and not target.exists():
            findings.append(Finding(severity, "work-claim-refused", "cannot release a missing work claim", _claim_rel_path(request.claim_id)))
        elif request.claim_id:
            _, read_findings = _load_claim_record_for_mutation(inventory.root, request.claim_id, severity=severity)
            findings.extend(read_findings)
        return findings
    if request.action == "extend":
        if request.claim_id:
            rel_path = _claim_rel_path(request.claim_id)
            target = inventory.root / rel_path
            if not target.exists():
                findings.append(Finding(severity, "work-claim-refused", "cannot extend a missing work claim", rel_path))
            elif not lease_findings:
                current, read_findings = _load_claim_record_for_mutation(inventory.root, request.claim_id, severity=severity)
                findings.extend(read_findings)
                if current is None:
                    pass
                elif current.status != "active":
                    findings.append(Finding(severity, "work-claim-refused", "can only extend an active work claim", rel_path))
                elif _claim_is_stale(current):
                    findings.append(Finding(severity, "work-claim-refused", "cannot extend stale work claim; release it or create a new reviewed claim", rel_path))
        if not (request.lease_expires_at or request.ttl):
            findings.append(Finding("error", "work-claim-refused", "extend requires --ttl or --lease-expires-at"))
        return findings

    for field, value in (
        ("--claim-kind", request.claim_kind),
        ("--owner-role", request.owner_role),
        ("--owner-actor", request.owner_actor),
        ("--execution-slice", request.execution_slice),
    ):
        if not value:
            findings.append(Finding("error", "work-claim-refused", f"{field} is required"))
    if request.claim_kind and request.claim_kind not in WORK_CLAIM_KINDS:
        findings.append(Finding("error", "work-claim-refused", f"--claim-kind must be one of {', '.join(sorted(WORK_CLAIM_KINDS))}"))
    if not (request.claimed_routes or request.claimed_paths or request.claimed_resources):
        findings.append(Finding("error", "work-claim-refused", "at least one --claimed-route, --claimed-path, or --claimed-resource is required"))
    for rel_path in request.claimed_paths:
        conflict = _root_relative_path_conflict(rel_path)
        if conflict:
            findings.append(Finding("error", "work-claim-refused", f"--claimed-path {conflict}", rel_path))
    if request.claim_id:
        rel_path = _claim_rel_path(request.claim_id)
        target = inventory.root / rel_path
        findings.extend(_target_findings(inventory.root, rel_path, severity))
        if target.exists():
            findings.append(Finding(severity, "work-claim-refused", "work claim already exists; release it or choose a new --claim-id", rel_path))
    findings.extend(_overlap_findings(inventory.root, request, severity))
    return findings


def _target_findings(root: Path, target_rel: str, severity: str) -> list[Finding]:
    conflict = _root_relative_path_conflict(target_rel)
    if conflict:
        return [Finding(severity, "work-claim-refused", f"claim target {conflict}", target_rel)]
    if not target_rel.startswith(f"{WORK_CLAIMS_DIR_REL}/") or not target_rel.endswith(".json"):
        return [Finding(severity, "work-claim-refused", f"claim target must be under {WORK_CLAIMS_DIR_REL}/*.json", target_rel)]
    target = root / target_rel
    boundary_violation = source_path_boundary_violation(root, target, label="work claim target")
    if boundary_violation is not None:
        return [Finding(severity, "work-claim-refused", boundary_violation.message, target_rel)]
    target = target.resolve(strict=False)
    try:
        target.relative_to(root.resolve(strict=False))
    except ValueError:
        return [Finding(severity, "work-claim-refused", "claim target escapes the target root", target_rel)]
    return []


def _overlap_findings(root: Path, request: WorkClaimRequest, severity: str) -> list[Finding]:
    if request.claim_kind not in EXCLUSIVE_CLAIM_KINDS:
        return []
    records, warnings = _load_claim_records(root)
    findings = [Finding("warn", warning.code, warning.message, warning.source, warning.line) for warning in warnings]
    for record in records:
        if record.claim_id == request.claim_id or record.status != "active":
            continue
        if record.claim_kind not in EXCLUSIVE_CLAIM_KINDS:
            continue
        overlap = _claim_overlap(record, request)
        if not overlap:
            continue
        findings.append(
            Finding(
                severity,
                "work-claim-overlap",
                f"overlapping active work claim {record.claim_id}: {overlap}; release or narrow the existing claim before applying",
                record.rel_path,
            )
        )
    return findings


def _claim_overlap(record: WorkClaimRecord, request: WorkClaimRequest) -> str:
    routes = sorted(set(record.claimed_routes).intersection(request.claimed_routes))
    resources = sorted(set(record.claimed_resources).intersection(request.claimed_resources))
    paths = sorted(
        existing
        for existing in record.claimed_paths
        for candidate in request.claimed_paths
        if _paths_overlap(existing, candidate)
    )
    parts: list[str] = []
    if routes:
        parts.append(f"routes={', '.join(routes)}")
    if paths:
        parts.append(f"paths={', '.join(dict.fromkeys(paths))}")
    if resources:
        parts.append(f"resources={', '.join(resources)}")
    return "; ".join(parts)


def _claim_overlap_records(left: WorkClaimRecord, right: WorkClaimRecord) -> str:
    routes = sorted(set(left.claimed_routes).intersection(right.claimed_routes))
    resources = sorted(set(left.claimed_resources).intersection(right.claimed_resources))
    path_pairs = []
    for left_path in left.claimed_paths:
        for right_path in right.claimed_paths:
            if _paths_overlap(left_path, right_path):
                path_pairs.append(f"{left_path}<->{right_path}")
    parts: list[str] = []
    if routes:
        parts.append(f"routes={', '.join(routes)}")
    if path_pairs:
        parts.append(f"paths={', '.join(dict.fromkeys(path_pairs))}")
    if resources:
        parts.append(f"resources={', '.join(resources)}")
    return "; ".join(parts)


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = tuple(_normalize_ref(left).split("/"))
    right_parts = tuple(_normalize_ref(right).split("/"))
    if not left_parts or not right_parts:
        return False
    shorter, longer = (left_parts, right_parts) if len(left_parts) <= len(right_parts) else (right_parts, left_parts)
    return longer[: len(shorter)] == shorter


def _load_claim_records(root: Path) -> tuple[list[WorkClaimRecord], list[Finding]]:
    directory = root / WORK_CLAIMS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return [], []
    records: list[WorkClaimRecord] = []
    findings: list[Finding] = []
    for path in sorted(directory.glob("*.json")):
        rel_path = _to_rel_path(root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", "work-claim-malformed", "work claim record path is not a regular file", rel_path))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", "work-claim-malformed", f"work claim record could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", "work-claim-malformed", "work claim record JSON root must be an object", rel_path))
            continue
        records.append(WorkClaimRecord(rel_path=rel_path, data=data))
    return records, findings


def _load_claim_record(root: Path, claim_id: str) -> WorkClaimRecord:
    path = root / _claim_rel_path(claim_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    return WorkClaimRecord(_to_rel_path(root, path), data)


def _load_claim_record_for_mutation(root: Path, claim_id: str, *, severity: str) -> tuple[WorkClaimRecord | None, list[Finding]]:
    path = root / _claim_rel_path(claim_id)
    rel_path = _to_rel_path(root, path)
    if path.is_symlink() or not path.is_file():
        return None, [Finding(severity, "work-claim-refused", "existing work claim record path is not a regular file", rel_path)]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [Finding(severity, "work-claim-refused", f"existing work claim record could not be read as JSON: {exc}", rel_path)]
    if not isinstance(data, dict):
        return None, [Finding(severity, "work-claim-refused", "existing work claim record JSON root must be an object", rel_path)]
    return WorkClaimRecord(rel_path, data), []


def _work_claim_mutation_lock_rel_path() -> str:
    return f"{WORK_CLAIMS_DIR_REL}/{WORK_CLAIM_MUTATION_LOCK_NAME}"


def _acquire_work_claim_mutation_lock(root: Path) -> _WorkClaimMutationLock:
    lock_path = root / _work_claim_mutation_lock_rel_path()
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WorkClaimMutationLockError(f"failed to prepare work claim mutation lock: {exc}") from exc
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        raise WorkClaimMutationLockError("work claim mutation lock is already held; retry after the in-flight claim mutation finishes") from exc
    except OSError as exc:
        raise WorkClaimMutationLockError(f"failed to acquire work claim mutation lock: {exc}") from exc
    return _WorkClaimMutationLock(path=lock_path, fd=fd)


def _release_work_claim_mutation_lock(lock: _WorkClaimMutationLock) -> None:
    try:
        os.close(lock.fd)
    finally:
        try:
            lock.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _created_claim_record(request: WorkClaimRequest) -> dict[str, object]:
    return {
        "schema": WORK_CLAIM_SCHEMA,
        "record_type": "work-claim",
        "claim_id": request.claim_id,
        "claim_kind": request.claim_kind,
        "owner_role": request.owner_role,
        "owner_actor": request.owner_actor,
        "execution_slice": request.execution_slice,
        "worktree_id": request.worktree_id,
        "base_revision": request.base_revision,
        "claimed_routes": list(request.claimed_routes),
        "claimed_paths": list(request.claimed_paths),
        "claimed_resources": list(request.claimed_resources),
        "lease_expires_at": _lease_expires_at_for_request(request),
        "status": "active",
        "release_condition": request.release_condition,
        "created_at_utc": _utc_timestamp(),
        "authority_boundary": "work claims coordinate fan-in only; they cannot approve lifecycle transitions, archive, staging, commit, or release",
    }


def _release_fields(request: WorkClaimRequest) -> dict[str, object]:
    return {
        "status": "released",
        "released_at_utc": _utc_timestamp(),
        "release_condition": request.release_condition,
        "completion_policy": work_claim_completion_policy_payload(),
        "completion_evidence": _completion_evidence_payload(request.release_condition),
    }


def _completion_policy_findings(request: WorkClaimRequest) -> list[Finding]:
    if request.action != "release":
        return []
    source = _claim_rel_path(request.claim_id) if request.claim_id else WORK_CLAIMS_DIR_REL
    return [
        Finding(
            "info",
            "work-claim-completion-policy",
            (
                "work claim release records reviewed evidence only; completion_policy=repo-visible-evidence-only; "
                "required_routes=claim,handoff,evidence; external Linear/Symphony done state is report-only and does not approve MLH closeout"
            ),
            source,
        )
    ]


def _extend_fields(request: WorkClaimRequest) -> dict[str, object]:
    data: dict[str, object] = {
        "lease_expires_at": _lease_expires_at_for_request(request),
        "extended_at_utc": _utc_timestamp(),
    }
    if request.release_condition:
        data["extension_note"] = request.release_condition
    return data


def _scope_findings(request: WorkClaimRequest) -> list[Finding]:
    if request.action != "create":
        return []
    return [
        Finding(
            "info",
            "work-claim-scope",
            (
                f"claim_kind={request.claim_kind}; routes={len(request.claimed_routes)}; "
                f"paths={len(request.claimed_paths)}; resources={len(request.claimed_resources)}; "
                "overlap checks are route/path/resource scoped"
            ),
            _claim_rel_path(request.claim_id),
        )
    ]


def _record_metadata_findings(record: WorkClaimRecord, code_prefix: str) -> list[Finding]:
    return work_claim_record_metadata_findings(record.data, record.rel_path, code_prefix)


def _record_completion_policy_findings(record: WorkClaimRecord, code_prefix: str) -> list[Finding]:
    if record.status != "released":
        return []
    policy = record.data.get("completion_policy")
    evidence = record.data.get("completion_evidence")
    ref_count = 0
    if isinstance(evidence, dict):
        ref_count = len(_string_tuple(evidence.get("repo_visible_refs")))
    policy_summary = "legacy-release-no-policy"
    if isinstance(policy, dict):
        policy_summary = str(policy.get("decision") or "repo-visible-evidence-only")
    return [
        Finding(
            "info",
            f"{code_prefix}-completion-policy",
            (
                f"claim_id={record.claim_id or '<missing>'}; completion_policy={policy_summary}; "
                f"repo_visible_refs={ref_count}; external_done_claims_authoritative=false; read-only claim evidence only"
            ),
            record.rel_path,
        )
    ]


def _completion_policy_metadata_findings(data: dict[str, object], rel_path: str, code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    policy = data.get("completion_policy")
    if policy in (None, ""):
        return findings
    if not isinstance(policy, dict):
        return [Finding("warn", f"{code_prefix}-malformed", "work claim completion_policy must be an object when present", rel_path)]
    if policy.get("schema") != WORK_CLAIM_COMPLETION_POLICY_SCHEMA:
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-malformed",
                f"work claim completion_policy schema should be {WORK_CLAIM_COMPLETION_POLICY_SCHEMA}",
                rel_path,
            )
        )
    for field in WORK_CLAIM_COMPLETION_POLICY_AUTHORITY_FIELDS:
        if _metadata_truthy(policy.get(field)):
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-completion-policy-authority",
                    f"work claim completion_policy {field} must remain false; external completion claims are evidence only",
                    rel_path,
                )
            )
    evidence = data.get("completion_evidence")
    if evidence in (None, ""):
        return findings
    if not isinstance(evidence, dict):
        findings.append(Finding("warn", f"{code_prefix}-malformed", "work claim completion_evidence must be an object when present", rel_path))
        return findings
    refs = evidence.get("repo_visible_refs")
    if refs not in (None, "") and not isinstance(refs, list):
        findings.append(Finding("warn", f"{code_prefix}-malformed", "work claim completion_evidence.repo_visible_refs must be a list of strings", rel_path))
    for ref in _string_tuple(refs):
        conflict = _root_relative_path_conflict(ref)
        if conflict:
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"work claim completion_evidence repo_visible_ref {conflict}", rel_path))
    if _metadata_truthy(evidence.get("external_tracker_status_authoritative")):
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-completion-policy-authority",
                "work claim completion_evidence external_tracker_status_authoritative must remain false",
                rel_path,
            )
        )
    return findings


def _completion_evidence_payload(release_condition: str) -> dict[str, object]:
    refs = tuple(
        dict.fromkeys(
            match.group(1).rstrip(").,;:")
            for match in COMPLETION_EVIDENCE_REF_RE.finditer(_normalize_ref(release_condition))
        )
    )
    return {
        "release_condition": release_condition,
        "repo_visible_refs": list(refs),
        "ref_count": len(refs),
        "required_evidence": list(WORK_CLAIM_COMPLETION_REQUIRED_EVIDENCE),
        "external_tracker_status_authoritative": False,
        "reviewed_abandonment": _release_condition_mentions_abandonment(release_condition),
    }


def _release_condition_mentions_abandonment(release_condition: str) -> bool:
    text = release_condition.casefold()
    return any(term in text for term in ("abandon", "abandoned", "abandonment"))


def _claim_is_stale(record: WorkClaimRecord) -> bool:
    if not record.lease_expires_at:
        return False
    parsed = _parse_utc_timestamp(record.lease_expires_at)
    return bool(parsed and parsed < datetime.now(timezone.utc))


def _parse_utc_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _lease_request_findings(request: WorkClaimRequest) -> list[Finding]:
    findings: list[Finding] = []
    if request.lease_expires_at and _parse_utc_timestamp(request.lease_expires_at) is None:
        findings.append(Finding("error", "work-claim-refused", "--lease-expires-at must be a valid UTC timestamp"))
    if request.ttl and _parse_ttl_delta(request.ttl) is None:
        findings.append(Finding("error", "work-claim-refused", "--ttl must be a positive duration such as 900s, 30m, 2h, or 1d"))
    if request.lease_expires_at and request.ttl:
        findings.append(Finding("error", "work-claim-refused", "use either --ttl or --lease-expires-at, not both"))
    return findings


def _lease_expires_at_for_request(request: WorkClaimRequest) -> str:
    if request.lease_expires_at:
        parsed = _parse_utc_timestamp(request.lease_expires_at)
        return parsed.strftime("%Y-%m-%dT%H:%M:%SZ") if parsed is not None else request.lease_expires_at
    if request.ttl:
        delta = _parse_ttl_delta(request.ttl)
        if delta is not None:
            return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ""


def _parse_ttl_delta(value: str) -> timedelta | None:
    match = re.fullmatch(r"([1-9][0-9]*)([smhd]?)", value.strip().lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2) or "s"
    if unit == "s":
        return timedelta(seconds=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    return None


def _claim_rel_path(claim_id: str) -> str:
    return f"{WORK_CLAIMS_DIR_REL}/{claim_id}.json"


def _claim_json(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _route_write_finding(rel_path: str, before_data: dict[str, object] | None, after_data: dict[str, object], *, apply: bool) -> Finding:
    before_text = None if before_data is None else _claim_json(before_data)
    after_text = _claim_json(after_data)
    operation = "created" if apply and before_data is None else "wrote" if apply else "create" if before_data is None else "write"
    prefix = "" if apply else "would "
    return Finding(
        "info",
        "work-claim-route-write",
        (
            f"{prefix}{operation} route {rel_path}; before_hash={_hash_or_missing(before_text)}; "
            f"after_hash={_short_hash(after_text)}; before_bytes={_bytes_or_missing(before_text)}; "
            f"after_bytes={len(after_text.encode('utf-8'))}; source-bound write evidence is independent of Git tracking"
        ),
        rel_path,
    )


def _boundary_findings(code_prefix: str = "work-claim") -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "work claims coordinate scoped work and fan-in only; they cannot approve lifecycle transitions, archive, roadmap status, staging, commit, rollback, or release",
            WORK_CLAIMS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-route",
            f"work claims live under {WORK_CLAIMS_DIR_REL}/*.json as repo-visible evidence; no hidden queue, daemon, database, adapter state, or provider gateway is created",
            WORK_CLAIMS_DIR_REL,
        ),
    ]


def _fan_in_execution_slice(plan_data: dict[str, object]) -> str:
    for field in ("execution_slice", "primary_roadmap_item", "related_roadmap_item", "plan_id"):
        value = str(plan_data.get(field) or "").strip()
        if value:
            return value
    return ""


def _fan_in_activation_reasons(plan_data: dict[str, object], product_diff_proof: dict[str, object] | None) -> tuple[str, ...]:
    reasons: list[str] = []
    for field in FAN_IN_BOOLEAN_METADATA_FIELDS:
        if _metadata_truthy(plan_data.get(field)):
            reasons.append(f"metadata:{field}")

    for field in FAN_IN_MODE_METADATA_FIELDS:
        for value in _metadata_values(plan_data.get(field)):
            if _metadata_mode_activates(field, value):
                reasons.append(f"metadata:{field}={value}")
                break

    dirty_paths = tuple(str(path) for path in (product_diff_proof or {}).get("dirty_paths", ()) if str(path))
    out_of_scope = {str(path) for path in (product_diff_proof or {}).get("out_of_scope", ()) if str(path)}
    in_scope_dirty = tuple(path for path in dirty_paths if path not in out_of_scope)
    high_blast_dirty = tuple(path for path in in_scope_dirty if _fan_in_high_blast_path(path))
    if len(high_blast_dirty) >= FAN_IN_HIGH_BLAST_DIRTY_PATH_THRESHOLD:
        reasons.append(f"observed-diff:in-scope-dirty-paths>={FAN_IN_HIGH_BLAST_DIRTY_PATH_THRESHOLD}")
    clusters = {_path_cluster(path) for path in high_blast_dirty if _path_cluster(path)}
    if len(clusters) >= FAN_IN_HIGH_BLAST_CLUSTER_THRESHOLD:
        reasons.append(f"observed-diff:dirty-clusters>={FAN_IN_HIGH_BLAST_CLUSTER_THRESHOLD}")
    return tuple(dict.fromkeys(reasons))


def _metadata_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, list):
        return any(_metadata_truthy(item) for item in value)
    text = str(value or "").strip().casefold()
    return text in {"1", "true", "yes", "y", "required", "enabled", "on"}


def _metadata_values(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value or "").strip()
    return (text,) if text else ()


def _metadata_mode_activates(field: str, value: str) -> bool:
    text = value.strip().casefold().replace("_", "-")
    if not text:
        return False
    if field == "blast_radius":
        return text in {"high", "high-blast", "broad", "wide", "large"}
    return text in FAN_IN_ACTIVATING_MODE_TERMS or any(f" {term} " in f" {text} " for term in FAN_IN_ACTIVATING_MODE_TERMS)


def _fan_in_high_blast_path(path: str) -> bool:
    normalized = _normalize_ref(path).strip("/").casefold()
    if not normalized:
        return False
    return not normalized.startswith(FAN_IN_HIGH_BLAST_EXCLUDED_PREFIXES)


def _path_cluster(path: str) -> str:
    normalized = _normalize_ref(path).strip("/")
    if not normalized:
        return ""
    if "/" not in normalized:
        return normalized
    first, second, *_rest = normalized.split("/")
    if first in {"src", "tests", "docs", "project"} and second:
        return f"{first}/{second}"
    return first


def _fan_in_matching_claim_refs(root: Path, execution_slice: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    refs: list[str] = []
    blockers: list[str] = []
    for path in sorted((root / WORK_CLAIMS_DIR_REL).glob("*.json")):
        rel_path = _to_rel_path(root, path)
        data = _read_json_object(path)
        if data is None:
            continue
        if data.get("schema") != WORK_CLAIM_SCHEMA or data.get("record_type") != "work-claim":
            continue
        if execution_slice and str(data.get("execution_slice") or "").strip() != execution_slice:
            continue
        status = str(data.get("status") or "").strip()
        if status != "released":
            blockers.append(f"{rel_path}: claim status is {status or '<missing>'}, not released")
            continue
        refs.append(rel_path)
    return tuple(refs), tuple(blockers)


def _fan_in_matching_handoff_refs(root: Path, execution_slice: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    refs: list[str] = []
    blockers: list[str] = []
    for path in sorted((root / FAN_IN_HANDOFFS_DIR_REL).glob("*.json")):
        rel_path = _to_rel_path(root, path)
        data = _read_json_object(path)
        if data is None:
            continue
        if data.get("schema") != FAN_IN_HANDOFF_SCHEMA or data.get("record_type") != "handoff-packet":
            continue
        if execution_slice and str(data.get("execution_slice") or "").strip() != execution_slice:
            continue
        status = str(data.get("status") or "").strip()
        if status != "accepted":
            blockers.append(f"{rel_path}: handoff status is {status or '<missing>'}, not accepted")
            continue
        refs.append(rel_path)
    return tuple(refs), tuple(blockers)


def _fan_in_matching_agent_run_refs(
    root: Path,
    execution_slice: str,
    claim_refs: tuple[str, ...],
    handoff_refs: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    refs: list[str] = []
    blockers: list[str] = []
    for path in sorted((root / FAN_IN_AGENT_RUNS_DIR_REL).glob("*.md")):
        rel_path = _to_rel_path(root, path)
        if path.is_symlink() or not path.is_file():
            continue
        try:
            frontmatter = parse_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        data = frontmatter.data
        if data.get("schema") != FAN_IN_AGENT_RUN_SCHEMA or data.get("record_type") != "agent-run":
            continue
        if execution_slice and str(data.get("assigned_scope") or data.get("execution_slice") or "").strip() != execution_slice:
            continue
        record_blockers = _fan_in_agent_run_blockers(root, rel_path, data, claim_refs, handoff_refs)
        if record_blockers:
            blockers.extend(record_blockers)
            continue
        refs.append(rel_path)
    return tuple(refs), tuple(blockers)


def _fan_in_agent_run_blockers(
    root: Path,
    rel_path: str,
    data: dict[str, object],
    claim_refs: tuple[str, ...],
    handoff_refs: tuple[str, ...],
) -> list[str]:
    blockers: list[str] = []
    status = str(data.get("status") or "").strip()
    if status not in FAN_IN_AGENT_RUN_SUCCESS_STATUSES:
        blockers.append(f"{rel_path}: agent-run status is {status or '<missing>'}, not succeeded")
    docs_decision = str(data.get("docs_decision") or "").strip()
    if docs_decision not in FAN_IN_AGENT_RUN_DOCS_DECISIONS:
        blockers.append(f"{rel_path}: docs_decision is missing or unsupported")
    residual = str(data.get("residual_risk") or "").strip().casefold()
    if residual not in FAN_IN_NONBLOCKING_RESIDUALS and any(term in residual for term in FAN_IN_BLOCKING_RESIDUAL_TERMS):
        blockers.append(f"{rel_path}: residual_risk contains blocking risk")
    for field in FAN_IN_AGENT_RUN_REQUIRED_LISTS:
        if not _string_tuple(data.get(field)):
            blockers.append(f"{rel_path}: agent-run missing required evidence list {field}")
    agent_claim_refs = set(_normalize_ref(ref) for ref in _string_tuple(data.get("claim_refs")))
    expected_claim_refs = set(_normalize_ref(ref) for ref in claim_refs)
    if expected_claim_refs and not expected_claim_refs.intersection(agent_claim_refs):
        blockers.append(f"{rel_path}: agent-run does not cite released work-claim refs")
    agent_handoff_refs = set(_normalize_ref(ref) for ref in _string_tuple(data.get("handoff_refs")))
    expected_handoff_refs = set(_normalize_ref(ref) for ref in handoff_refs)
    if expected_handoff_refs and not expected_handoff_refs.intersection(agent_handoff_refs):
        blockers.append(f"{rel_path}: agent-run does not cite accepted handoff refs")
    blockers.extend(f"{rel_path}: {blocker}" for blocker in _fan_in_source_hash_blockers(root, data))
    return blockers


def _fan_in_source_hash_blockers(root: Path, data: dict[str, object]) -> list[str]:
    blockers: list[str] = []
    for entry in _string_tuple(data.get("source_hashes")):
        match = FAN_IN_SOURCE_HASH_RE.match(entry.strip())
        if not match:
            blockers.append(f"malformed source_hashes entry: {entry}")
            continue
        source_rel = match.group(1).strip()
        expected_hash = match.group(2)
        expected_missing = bool(match.group(3))
        expected_unreadable = bool(match.group(4))
        expected_invalid = bool(match.group(5))
        conflict = _root_relative_path_conflict(source_rel)
        if conflict:
            blockers.append(f"source hash path {conflict}: {source_rel}")
            continue
        source_path = root / source_rel
        if expected_missing:
            if source_path.exists():
                blockers.append(f"source hash recorded missing path now exists: {source_rel}")
            continue
        if expected_unreadable or expected_invalid:
            blockers.append(f"source hash entry records degraded evidence for {source_rel}")
            continue
        if not source_path.exists():
            blockers.append(f"source hash target is now missing: {source_rel}")
            continue
        if not source_path.is_file():
            blockers.append(f"source hash target is no longer a regular file: {source_rel}")
            continue
        try:
            current_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except OSError as exc:
            blockers.append(f"source hash target is now unreadable: {source_rel}: {exc}")
            continue
        if expected_hash and current_hash.lower() != expected_hash.lower():
            blockers.append(f"source hash mismatch for {source_rel}: expected={expected_hash[:12]} current={current_hash[:12]}")
    return blockers


def _fan_in_active_overlap_blockers(root: Path) -> tuple[str, ...]:
    records: list[WorkClaimRecord] = []
    for path in sorted((root / WORK_CLAIMS_DIR_REL).glob("*.json")):
        data = _read_json_object(path)
        if data is None:
            continue
        if data.get("schema") != WORK_CLAIM_SCHEMA or data.get("record_type") != "work-claim":
            continue
        records.append(WorkClaimRecord(_to_rel_path(root, path), data))
    blockers: list[str] = []
    for left_index, left in enumerate(records):
        if left.status != "active" or left.claim_kind not in EXCLUSIVE_CLAIM_KINDS:
            continue
        for right in records[left_index + 1 :]:
            if right.status != "active" or right.claim_kind not in EXCLUSIVE_CLAIM_KINDS:
                continue
            overlap = _claim_overlap_records(left, right)
            if overlap:
                blockers.append(f"overlapping active work claims {left.claim_id} and {right.claim_id}: {overlap}")
    return tuple(blockers)


def _read_json_object(path: Path) -> dict[str, object] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _sample_text(values: tuple[str, ...], limit: int = 4) -> str:
    if not values:
        return "<none>"
    head = ", ".join(values[:limit])
    if len(values) > limit:
        return f"{head}, +{len(values) - limit} more"
    return head


def _tuple_values(values: object) -> tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, str):
        values = (values,)
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text:
            cleaned.append(_normalize_ref(text))
    return tuple(dict.fromkeys(cleaned))


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _root_relative_path_conflict(rel_path: str) -> str:
    return root_relative_path_conflict(_normalize_ref(rel_path))


def _normalize_ref(value: str) -> str:
    return str(value or "").replace("\\", "/").strip()


def _to_rel_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _hash_or_missing(text: str | None) -> str:
    return "missing" if text is None else _short_hash(text)


def _bytes_or_missing(text: str | None) -> str:
    return "missing" if text is None else str(len(text.encode("utf-8")))


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
