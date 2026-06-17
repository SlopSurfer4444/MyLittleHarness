from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .claims import WorkClaimRecord, work_claim_active_overlap_findings, work_claim_record_metadata_findings
from .evidence import agent_run_retired_records
from .handoff import handoff_packet_status_findings
from .inventory import Inventory
from .models import Finding
from .parsing import parse_frontmatter
from .root_boundary import root_relative_path_conflict, source_path_boundary_violation


AGENT_RUNS_DIR_REL = "project/verification/agent-runs"
APPROVAL_PACKETS_DIR_REL = "project/verification/approval-packets"
WORK_CLAIMS_DIR_REL = "project/verification/work-claims"
WORKER_RESIDUE_DIR_RELS = (
    "project/verification/worktrees",
    "project/verification/worker-outputs",
    ".mylittleharness/worktrees",
)
STALE_APPROVAL_AGE = timedelta(days=7)
SOURCE_HASH_RE = re.compile(r"^(.+?)\s+(?:sha256=([a-fA-F0-9]{64})|(missing)|(unreadable)|(invalid-path))$")
HASH_RE = re.compile(r"^[a-fA-F0-9]{64}$")


@dataclass(frozen=True)
class ReconcileObservation:
    kind: str
    rel_path: str
    status: str
    fingerprint: str
    evidence_ref: str
    detail: str


def reconcile_findings(inventory: Inventory, code_prefix: str = "reconcile") -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", f"{code_prefix}-read-only", "reconcile reports current repo-visible drift posture without writing files"),
        Finding("info", f"{code_prefix}-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-non-authority",
                "reconcile is live-root only; product fixtures and archive roots remain read-only context",
                inventory.state.rel_path if inventory.state and inventory.state.exists else None,
            )
        )
        findings.extend(_boundary_findings(code_prefix))
        return findings

    observations: list[ReconcileObservation] = []
    findings.extend(_active_plan_scope_findings(inventory, code_prefix))
    observations.extend(_active_plan_observations(inventory))

    agent_records, agent_warnings = _load_agent_run_records(inventory.root, code_prefix)
    findings.extend(agent_warnings)
    observations.extend(_agent_run_observations(inventory.root, agent_records))

    claim_records, claim_warnings = _load_json_records(inventory.root, WORK_CLAIMS_DIR_REL, "claim_id", code_prefix, "work-claim")
    findings.extend(claim_warnings)
    findings.extend(_work_claim_findings(inventory.root, claim_records, agent_records, code_prefix))

    approval_records, approval_warnings = _load_json_records(
        inventory.root,
        APPROVAL_PACKETS_DIR_REL,
        "approval_id",
        code_prefix,
        "approval-packet",
    )
    findings.extend(approval_warnings)
    findings.extend(_approval_packet_findings(inventory.root, approval_records, code_prefix))
    findings.extend(handoff_packet_status_findings(inventory, f"{code_prefix}-handoff-packet"))

    findings.extend(_worker_residue_findings(inventory.root, claim_records, code_prefix))
    findings.extend(_observation_findings(observations, code_prefix))
    if not any(finding.severity == "warn" for finding in findings):
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-agents-clean",
                "no stale or overlapping claims, stale approval packets, drifted evidence hashes, or worker residue were found",
            )
        )
    findings.extend(_boundary_findings(code_prefix))
    return findings


def _active_plan_observations(inventory: Inventory) -> list[ReconcileObservation]:
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    plan_status = str(state_data.get("plan_status") or "")
    state_active_plan = str(state_data.get("active_plan") or "")
    manifest_plan = str(inventory.manifest.get("memory", {}).get("plan_file", "project/implementation-plan.md"))
    active_plan = state_active_plan or (manifest_plan if plan_status == "active" else "")
    observations: list[ReconcileObservation] = []
    if active_plan:
        observations.append(_path_observation(inventory.root, active_plan, "route", "project-state active_plan", expected_hash=""))
    surface = inventory.active_plan_surface
    if not surface or not surface.exists:
        return observations
    data = surface.frontmatter.data
    for rel_path in _frontmatter_paths(data.get("source_research")):
        observations.append(_path_observation(inventory.root, rel_path, "source", surface.rel_path, expected_hash=""))
    for rel_path in _frontmatter_paths(data.get("related_specs")):
        observations.append(_path_observation(inventory.root, rel_path, "route", surface.rel_path, expected_hash=""))
    for rel_path in _frontmatter_paths(data.get("target_artifacts")):
        observations.append(_path_observation(inventory.root, rel_path, "source", surface.rel_path, expected_hash=""))
    return observations


def _active_plan_scope_findings(inventory: Inventory, code_prefix: str) -> list[Finding]:
    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    plan_status = str(state_data.get("plan_status") or "")
    state_active_plan = str(state_data.get("active_plan") or "")
    if plan_status not in {"", "none"} or state_active_plan:
        return []
    surface = inventory.active_plan_surface
    if surface and surface.exists:
        return [
            Finding(
                "info",
                f"{code_prefix}-active-plan-scope",
                "plan_status is none and active_plan is empty; existing implementation plan file is inactive route context for reconcile",
                surface.rel_path,
            )
        ]
    return [
        Finding(
            "info",
            f"{code_prefix}-active-plan-scope",
            "plan_status is none and active_plan is empty; default implementation plan route is lazy and skipped for reconcile assessment",
            state.rel_path if state else None,
        )
    ]


def _agent_run_observations(root: Path, records: list[dict[str, object]]) -> list[ReconcileObservation]:
    observations: list[ReconcileObservation] = []
    for record in records:
        rel_path = str(record.get("_rel_path") or "")
        data = record.get("data")
        if not isinstance(data, dict):
            continue
        for entry in _frontmatter_paths(data.get("source_hashes")):
            match = SOURCE_HASH_RE.match(entry.strip())
            if not match:
                observations.append(
                    ReconcileObservation(
                        kind="evidence",
                        rel_path=rel_path,
                        status="partially_verified",
                        fingerprint="malformed-source-hash",
                        evidence_ref=rel_path,
                        detail=f"agent-run source_hashes entry is malformed: {entry}",
                    )
                )
                continue
            source_rel = _normalize_ref(match.group(1))
            expected_hash = match.group(2)
            expected_missing = bool(match.group(3))
            expected_unreadable = bool(match.group(4))
            expected_invalid = bool(match.group(5))
            observations.append(
                _path_observation(
                    root,
                    source_rel,
                    "evidence",
                    rel_path,
                    expected_hash=expected_hash or "",
                    expected_missing=expected_missing,
                    expected_degraded=expected_unreadable or expected_invalid,
                )
            )
    return observations


def _path_observation(
    root: Path,
    rel_path: str,
    kind: str,
    evidence_ref: str,
    *,
    expected_hash: str,
    expected_missing: bool = False,
    expected_degraded: bool = False,
) -> ReconcileObservation:
    normalized = _normalize_ref(rel_path)
    conflict = _root_relative_path_conflict(normalized)
    if conflict:
        return ReconcileObservation(kind, normalized or rel_path, "drift_detected", "invalid-path", evidence_ref, conflict)

    path = root / normalized
    if expected_degraded:
        return ReconcileObservation(
            kind,
            normalized,
            "partially_verified",
            _file_fingerprint(path),
            evidence_ref,
            "recorded evidence is degraded and needs review",
        )
    if expected_missing:
        status = "stale" if path.exists() else "unassessed"
        detail = "recorded missing path now exists" if path.exists() else "path remains missing"
        return ReconcileObservation(kind, normalized, status, _file_fingerprint(path), evidence_ref, detail)
    if not path.exists():
        status = "stale" if expected_hash else "unassessed"
        detail = "expected hashed source is now missing" if expected_hash else "path is not present for assessment"
        return ReconcileObservation(kind, normalized, status, "missing", evidence_ref, detail)
    if path.is_symlink() or not path.is_file():
        return ReconcileObservation(kind, normalized, "drift_detected", "invalid-path", evidence_ref, "path is not a regular file")

    digest = _sha256_file(path)
    if expected_hash:
        status = "synced" if digest.lower() == expected_hash.lower() else "drift_detected"
        detail = "recorded source hash matches current file" if status == "synced" else f"expected={expected_hash[:12]} current={digest[:12]}"
        return ReconcileObservation(kind, normalized, status, f"sha256={digest[:12]}", evidence_ref, detail)
    return ReconcileObservation(kind, normalized, "partially_verified", f"sha256={digest[:12]}", evidence_ref, "current file fingerprint recorded without a bound expected hash")


def _work_claim_findings(root: Path, records: list[dict[str, object]], agent_records: list[dict[str, object]], code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    agent_refs = _agent_evidence_refs(agent_records)
    now = datetime.now(timezone.utc)
    for record in records:
        data = record.get("data")
        if not isinstance(data, dict):
            continue
        rel_path = str(record.get("_rel_path") or "")
        findings.extend(work_claim_record_metadata_findings(data, rel_path, f"{code_prefix}-work-claim"))
        claim_id = str(data.get("claim_id") or Path(rel_path).stem)
        status = str(data.get("status") or "").strip()
        stale = status == "active" and _timestamp_before(data.get("lease_expires_at"), now)
        displayed_status = "stale" if stale else status or "unassessed"
        findings.append(
            Finding(
                "warn" if stale else "info",
                f"{code_prefix}-claim-status",
                f"claim_id={claim_id}; status={displayed_status}; route fingerprint={_file_fingerprint(root / rel_path)}; read-only claim posture",
                rel_path,
            )
        )
        has_run_evidence = _claim_has_agent_evidence(rel_path, data, agent_refs)
        if status == "active" and not has_run_evidence:
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-missing-run-evidence",
                    f"active claim {claim_id} has no matching agent-run evidence for its claim route, worktree_id, or claimed paths",
                    rel_path,
                )
            )
        if stale:
            findings.append(Finding("warn", f"{code_prefix}-stale-claim", f"active claim {claim_id} has an expired lease", rel_path))
            if str(data.get("worktree_id") or "").strip():
                findings.append(
                    Finding(
                        "warn",
                        f"{code_prefix}-abandoned-worktree",
                        f"claim {claim_id} references worktree_id={data.get('worktree_id')} after its lease expired",
                        rel_path,
                    )
                )
            if not has_run_evidence:
                findings.append(
                    Finding(
                        "warn",
                        f"{code_prefix}-no-progress-residue",
                        f"stale claim {claim_id} has no progress evidence; coordinator review is required before cleanup",
                        rel_path,
                    )
                )
                findings.append(_human_gated_proposal(code_prefix, f"review stale claim {claim_id} before release, cleanup, archive, or fan-in", rel_path))
    overlap_records = [
        WorkClaimRecord(rel_path=str(record.get("_rel_path") or ""), data=data)
        for record in records
        if isinstance((data := record.get("data")), dict)
    ]
    findings.extend(work_claim_active_overlap_findings(overlap_records, f"{code_prefix}-work-claim"))
    return findings


def _approval_packet_findings(root: Path, records: list[dict[str, object]], code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    now = datetime.now(timezone.utc)
    for record in records:
        data = record.get("data")
        if not isinstance(data, dict):
            continue
        rel_path = str(record.get("_rel_path") or "")
        approval_id = str(data.get("approval_id") or Path(rel_path).stem)
        status = str(data.get("status") or "").strip() or "unassessed"
        stale = status in {"pending", "needs-review"} and _approval_is_stale(data, now)
        findings.append(
            Finding(
                "warn" if stale else "info",
                f"{code_prefix}-approval-packet",
                f"approval_id={approval_id}; status={'stale' if stale else status}; evidence fingerprint={_file_fingerprint(root / rel_path)}; read-only approval posture",
                rel_path,
            )
        )
        if stale:
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-stale-approval-packet",
                    f"approval packet {approval_id} is still {status} after its review window; human review remains required",
                    rel_path,
                )
            )
            findings.append(_human_gated_proposal(code_prefix, f"review stale approval packet {approval_id} before relying on it for fan-in", rel_path))
    return findings


def _worker_residue_findings(root: Path, claim_records: list[dict[str, object]], code_prefix: str) -> list[Finding]:
    active_worktree_ids = {
        str(data.get("worktree_id") or "").strip()
        for record in claim_records
        if isinstance((data := record.get("data")), dict) and str(data.get("status") or "") == "active"
    }
    active_worktree_ids.discard("")
    findings: list[Finding] = []
    for directory_rel in WORKER_RESIDUE_DIR_RELS:
        directory = root / directory_rel
        if not directory.exists() or not directory.is_dir():
            continue
        for child in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
            rel_path = _to_rel_path(root, child)
            if child.is_symlink():
                findings.append(Finding("warn", f"{code_prefix}-worker-residue", "worker residue path is a symlink and requires manual review", rel_path))
                continue
            if child.name not in active_worktree_ids:
                findings.append(
                    Finding(
                        "warn",
                        f"{code_prefix}-worker-residue",
                        f"unclaimed worker-space residue found at {rel_path}; cleanup remains report-only and requires review",
                        rel_path,
                    )
                )
                findings.append(_human_gated_proposal(code_prefix, f"review worker residue {rel_path} before deletion or adoption", rel_path))
            else:
                findings.append(Finding("info", f"{code_prefix}-worker-residue", f"worker residue is claimed by active worktree_id={child.name}", rel_path))
    return findings


def _observation_findings(observations: list[ReconcileObservation], code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    for observation in observations:
        severity = "warn" if observation.status in {"stale", "drift_detected", "unassessed"} else "info"
        findings.append(
            Finding(
                severity,
                f"{code_prefix}-status",
                (
                    f"{observation.kind}={observation.rel_path}; status={observation.status}; "
                    f"fingerprint={observation.fingerprint}; evidence_ref={observation.evidence_ref or '<none>'}; {observation.detail}"
                ),
                observation.rel_path,
            )
        )
        if observation.status == "drift_detected":
            findings.append(_human_gated_proposal(code_prefix, f"review drift for {observation.rel_path} before fan-in or lifecycle writeback", observation.rel_path))
    return findings


def _load_agent_run_records(root: Path, code_prefix: str) -> tuple[list[dict[str, object]], list[Finding]]:
    directory = root / AGENT_RUNS_DIR_REL
    boundary_violation = source_path_boundary_violation(root, directory, label="agent run record directory")
    if boundary_violation is not None:
        return [], [Finding("warn", f"{code_prefix}-agent-run-malformed", boundary_violation.message, AGENT_RUNS_DIR_REL)]
    if not directory.exists() or not directory.is_dir():
        return [], [
            Finding(
                "info",
                f"{code_prefix}-agent-runs",
                f"no agent run records found at {AGENT_RUNS_DIR_REL}/*.md; reconcile can still report claims and residue",
                AGENT_RUNS_DIR_REL,
            )
        ]
    records: list[dict[str, object]] = []
    retired_records, retirement_findings = agent_run_retired_records(root, code_prefix)
    findings: list[Finding] = [*retirement_findings]
    for path in sorted(directory.glob("*.md")):
        rel_path = _to_rel_path(root, path)
        if rel_path in retired_records:
            continue
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code_prefix}-agent-run-malformed", "agent run record is not a regular file", rel_path))
            continue
        try:
            frontmatter = parse_frontmatter(path.read_text(encoding="utf-8"))
        except OSError as exc:
            findings.append(Finding("warn", f"{code_prefix}-agent-run-malformed", f"agent run record could not be read: {exc}", rel_path))
            continue
        records.append({"_rel_path": rel_path, "data": frontmatter.data})
    return records, findings


def _load_json_records(root: Path, directory_rel: str, id_field: str, code_prefix: str, label: str) -> tuple[list[dict[str, object]], list[Finding]]:
    directory = root / directory_rel
    boundary_violation = source_path_boundary_violation(root, directory, label=f"{label} record directory")
    if boundary_violation is not None:
        return [], [Finding("warn", f"{code_prefix}-{label}-malformed", boundary_violation.message, directory_rel)]
    if not directory.exists() or not directory.is_dir():
        return [], [Finding("info", f"{code_prefix}-{label}s", f"no {label} records found at {directory_rel}/*.json", directory_rel)]
    records: list[dict[str, object]] = []
    findings: list[Finding] = []
    for path in sorted(directory.glob("*.json")):
        rel_path = _to_rel_path(root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code_prefix}-{label}-malformed", f"{label} record path is not a regular file", rel_path))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", f"{code_prefix}-{label}-malformed", f"{label} record could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", f"{code_prefix}-{label}-malformed", f"{label} record JSON root must be an object", rel_path))
            continue
        if not str(data.get(id_field) or "").strip():
            findings.append(Finding("warn", f"{code_prefix}-{label}-malformed", f"{label} record missing {id_field}", rel_path))
        records.append({"_rel_path": rel_path, "data": data})
    return records, findings


def _claim_has_agent_evidence(claim_rel_path: str, data: dict[str, object], agent_refs: set[str]) -> bool:
    candidates = {_normalize_ref(claim_rel_path)}
    for value in _json_list(data.get("claimed_paths")):
        candidates.add(_normalize_ref(value))
    worktree_id = str(data.get("worktree_id") or "").strip()
    if worktree_id:
        candidates.add(worktree_id)
    return bool(candidates.intersection(agent_refs))


def _agent_evidence_refs(agent_records: list[dict[str, object]]) -> set[str]:
    refs: set[str] = set()
    for record in agent_records:
        rel_path = str(record.get("_rel_path") or "")
        if rel_path:
            refs.add(_normalize_ref(rel_path))
        data = record.get("data")
        if not isinstance(data, dict):
            continue
        for field in ("input_refs", "output_refs", "claimed_paths", "source_hashes"):
            for value in _frontmatter_paths(data.get(field)):
                match = SOURCE_HASH_RE.match(value.strip())
                refs.add(_normalize_ref(match.group(1) if match else value))
        repeated_failure = str(data.get("repeated_failure_signature") or "").strip()
        if repeated_failure:
            refs.add(repeated_failure)
    return refs


def _approval_is_stale(data: dict[str, object], now: datetime) -> bool:
    for field in ("stale_after_utc", "lease_expires_at", "expires_at_utc"):
        if _timestamp_before(data.get(field), now):
            return True
    created = _parse_utc_timestamp(data.get("created_at_utc"))
    return bool(created and created < now - STALE_APPROVAL_AGE)


def _timestamp_before(value: object, now: datetime) -> bool:
    parsed = _parse_utc_timestamp(value)
    return bool(parsed and parsed < now)


def _parse_utc_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
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


def _human_gated_proposal(code_prefix: str, message: str, source: str) -> Finding:
    return Finding(
        "warn",
        f"{code_prefix}-human-gated-proposal",
        f"human-gated proposal: {message}; no autofix, deletion, lifecycle approval, archive, staging, or commit is authorized",
        source,
        requires_human_gate=True,
        gate_class="coordinator-review",
        human_gate_reason=message,
        allowed_decisions=("review", "defer", "ignore"),
    )


def _boundary_findings(code_prefix: str) -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "reconcile is report-only; cleanup remains report-only and no authority, lifecycle, Git, archive, deletion, or release decision is approved",
        ),
        Finding(
            "info",
            f"{code_prefix}-states",
            "status vocabulary: synced, partially_verified, stale, drift_detected, unassessed",
        ),
    ]


def _frontmatter_paths(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _json_list(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _root_relative_path_conflict(rel_path: str) -> str:
    return root_relative_path_conflict(_normalize_ref(rel_path))


def _normalize_ref(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _file_fingerprint(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_symlink() or not path.is_file():
        return "invalid-path"
    try:
        return f"sha256={_sha256_file(path)[:12]}"
    except OSError:
        return "unreadable"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _to_rel_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
