from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .agent_roles import dispatcher_launch_contract, role_profile_for_id
from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .approval_packets import APPROVAL_PACKET_SCHEMA, APPROVAL_PACKETS_DIR_REL
from .claims import WORK_CLAIM_SCHEMA, WORK_CLAIMS_DIR_REL
from .evidence import AGENT_RUN_SCHEMA, AGENT_RUNS_DIR_REL
from .inventory import Inventory
from .models import Finding
from .parsing import parse_frontmatter
from .root_boundary import record_id_conflict, root_relative_path_conflict, source_path_boundary_violation


HANDOFF_PACKET_SCHEMA = "mylittleharness.handoff-packet.v1"
HANDOFF_PACKETS_DIR_REL = "project/verification/handoffs"
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
HANDOFF_PACKET_STATUSES = {"created", "accepted"}
HANDOFF_PACKET_REQUIRED_SCALARS = ("handoff_id", "worker_id", "role_id", "execution_slice", "status")
HANDOFF_PACKET_REQUIRED_LISTS = ("allowed_routes", "write_scope", "stop_conditions", "required_outputs", "evidence_refs", "claim_refs")
HANDOFF_PACKET_REF_LISTS = ("approval_packet_refs",)
HANDOFF_WORKER_FORBIDDEN_ROUTES = {
    "attach",
    "detach",
    "git",
    "incubate",
    "init",
    "memory-hygiene",
    "meta-feedback",
    "provider",
    "plan",
    "repair",
    "roadmap",
    "transition",
    "writeback",
}
SYMPHONY_QUEUE_DIR_REL = "project/symphony/queue"
SYMPHONY_QUEUE_READY_STATES = {
    "assigned",
    "assigned_to_worker",
    "pending",
    "queued",
    "ready",
    "todo",
}
SYMPHONY_QUEUE_BLOCKED_STATES = {
    "blocked",
    "paused",
    "waiting",
}
SYMPHONY_QUEUE_TERMINAL_STATES = {
    "cancelled",
    "canceled",
    "closed",
    "complete",
    "completed",
    "done",
    "failed",
    "skipped",
    "succeeded",
    "terminal",
}
DISPATCHER_LAUNCH_REQUIRED_MESSAGE = (
    "dispatcher cannot start work without a repo-visible handoff packet, compatible active claim, "
    "planned agent-run evidence path, and ready optional-orchestrator queue item with terminal upstream blockers"
)


@dataclass(frozen=True)
class HandoffPacketRequest:
    action: str
    handoff_id: str
    worker_id: str
    role_id: str
    execution_slice: str
    worktree_id: str
    branch: str
    base_revision: str
    head_revision: str
    allowed_routes: tuple[str, ...]
    write_scope: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    context_budget: str
    required_outputs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    approval_packet_refs: tuple[str, ...]
    claim_refs: tuple[str, ...]
    accepted_by: str
    acceptance_note: str


def make_handoff_packet_request(args: object) -> HandoffPacketRequest:
    return HandoffPacketRequest(
        action=str(getattr(args, "action", "") or "").strip() or "create",
        handoff_id=str(getattr(args, "handoff_id", "") or "").strip(),
        worker_id=str(getattr(args, "worker_id", "") or "").strip(),
        role_id=str(getattr(args, "role_id", "") or "").strip(),
        execution_slice=str(getattr(args, "execution_slice", "") or "").strip(),
        worktree_id=str(getattr(args, "worktree_id", "") or "").strip(),
        branch=str(getattr(args, "branch", "") or "").strip(),
        base_revision=str(getattr(args, "base_revision", "") or "").strip(),
        head_revision=str(getattr(args, "head_revision", "") or "").strip(),
        allowed_routes=_tuple_values(getattr(args, "allowed_routes", ()), path_like=False),
        write_scope=_tuple_values(getattr(args, "write_scope", ())),
        stop_conditions=_tuple_values(getattr(args, "stop_conditions", ()), path_like=False),
        context_budget=str(getattr(args, "context_budget", "") or "").strip() or "compact packet; target about 400 tokens; no hidden context",
        required_outputs=_tuple_values(getattr(args, "required_outputs", ()), path_like=False),
        evidence_refs=_tuple_values(getattr(args, "evidence_refs", ())),
        approval_packet_refs=_tuple_values(getattr(args, "approval_packet_refs", ())),
        claim_refs=_tuple_values(getattr(args, "claim_refs", ())),
        accepted_by=str(getattr(args, "accepted_by", "") or "").strip(),
        acceptance_note=str(getattr(args, "acceptance_note", "") or "").strip(),
    )


def handoff_packet_dry_run_findings(inventory: Inventory, request: HandoffPacketRequest) -> list[Finding]:
    findings = [
        Finding("info", "handoff-packet-dry-run", "handoff packet proposal only; no files were written"),
        Finding("info", "handoff-packet-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _request_findings(inventory, request, apply=False)
    findings.extend(request_findings)
    if any(finding.severity in {"warn", "error"} for finding in request_findings):
        findings.append(Finding("info", "handoff-packet-validation-posture", "dry-run refused before apply; fix explicit handoff fields before writing packet evidence"))
        findings.extend(_boundary_findings())
        return findings

    rel_path = _packet_rel_path(request.handoff_id)
    if request.action == "accept":
        before_data = _load_packet_data(inventory.root, request.handoff_id)
        after_data = {**before_data, **_accept_fields(request)}
        findings.append(Finding("info", "handoff-packet-target", f"would accept handoff packet: {rel_path}", rel_path))
        findings.append(_route_write_finding(rel_path, before_data, after_data, apply=False))
    else:
        text = _packet_json(_packet_data(request))
        findings.append(Finding("info", "handoff-packet-target", f"would write handoff packet: {rel_path}", rel_path))
        findings.append(
            Finding(
                "info",
                "handoff-packet-route-write",
                (
                    f"would create route {rel_path}; before_hash=missing; after_hash={_short_hash(text)}; "
                    f"before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; "
                    "source-bound write evidence is independent of Git tracking"
                ),
                rel_path,
            )
        )
    findings.extend(_packet_shape_findings(request))
    findings.extend(_boundary_findings())
    return findings


def handoff_packet_apply_findings(inventory: Inventory, request: HandoffPacketRequest) -> list[Finding]:
    findings = [
        Finding("info", "handoff-packet-apply", "handoff packet apply started"),
        Finding("info", "handoff-packet-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _request_findings(inventory, request, apply=True)
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "handoff-packet-apply-refused", "handoff packet apply refused before writing packet evidence"))
        findings.extend(_boundary_findings())
        return findings

    rel_path = _packet_rel_path(request.handoff_id)
    target = inventory.root / rel_path
    before_data: dict[str, object] | None = None
    if request.action == "accept":
        before_data = _load_packet_data(inventory.root, request.handoff_id)
        after_data = {**before_data, **_accept_fields(request)}
    else:
        after_data = _packet_data(request)
    text = _packet_json(after_data)
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
        findings.append(Finding("error", "handoff-packet-refused", f"failed to write handoff packet before apply completed: {exc}", rel_path))
        findings.extend(_boundary_findings())
        return findings

    if request.action == "accept":
        findings.append(Finding("info", "handoff-packet-accepted", f"accepted handoff packet: {rel_path}", rel_path))
        findings.append(_route_write_finding(rel_path, before_data, after_data, apply=True))
    else:
        findings.append(Finding("info", "handoff-packet-written", f"created handoff packet: {rel_path}", rel_path))
        findings.append(
            Finding(
                "info",
                "handoff-packet-route-write",
                (
                    f"created route {rel_path}; before_hash=missing; after_hash={_short_hash(text)}; "
                    f"before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; "
                    "source-bound write evidence is independent of Git tracking"
                ),
                rel_path,
            )
        )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "handoff-packet-backup-cleanup", warning, rel_path))
    findings.extend(_packet_shape_findings(request))
    findings.extend(_boundary_findings())
    return findings


def handoff_packet_status_findings(inventory: Inventory, code_prefix: str = "handoff-packet-status") -> list[Finding]:
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-non-authority",
                f"handoff packet diagnostics are live-root only; root kind is {inventory.root_kind}",
                HANDOFF_PACKETS_DIR_REL,
            )
        )
        findings.extend(_boundary_findings(code_prefix))
        return findings

    directory = inventory.root / HANDOFF_PACKETS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-records",
                f"no handoff packet records found at {HANDOFF_PACKETS_DIR_REL}/*.json",
                HANDOFF_PACKETS_DIR_REL,
            )
        )
        findings.extend(_boundary_findings(code_prefix))
        return findings

    for path in sorted(directory.glob("*.json")):
        rel_path = _to_rel_path(inventory.root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code_prefix}-malformed", "handoff packet record path is not a regular file", rel_path))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet record could not be read: {exc}", rel_path))
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet record could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", f"{code_prefix}-malformed", "handoff packet JSON root must be an object", rel_path))
            continue
        findings.extend(_handoff_packet_metadata_findings(data, rel_path, code_prefix))
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-packet",
                (
                    f"handoff_id={str(data.get('handoff_id') or Path(rel_path).stem)}; "
                    f"worker_id={str(data.get('worker_id') or '<missing>')}; "
                    f"evidence_refs={len(_json_list(data.get('evidence_refs')))}; "
                    f"approval_packet_refs={len(_json_list(data.get('approval_packet_refs')))}; "
                    f"claim_refs={len(_json_list(data.get('claim_refs')))}; "
                    f"fingerprint={_file_fingerprint(path)}; read-only handoff posture"
                ),
                rel_path,
            )
        )
        findings.extend(_handoff_packet_ref_findings(inventory.root, data, rel_path, code_prefix))

    if not any(finding.severity == "warn" for finding in findings):
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-clean",
                "no malformed handoff packets or degraded handoff refs were found",
                HANDOFF_PACKETS_DIR_REL,
            )
        )
    findings.extend(_boundary_findings(code_prefix))
    return findings


def dispatcher_launch_status_findings(inventory: Inventory, code_prefix: str = "dispatcher-launch") -> list[Finding]:
    contract = dispatcher_launch_contract()
    findings: list[Finding] = [
        Finding(
            "info",
            f"{code_prefix}-contract",
            (
                f"required_refs={', '.join(contract['required_refs'])}; "
                f"authority_boundary={contract['authority_boundary']}"
            ),
            HANDOFF_PACKETS_DIR_REL,
        )
    ]
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-non-authority",
                f"dispatcher launch readiness is live-root only; root kind is {inventory.root_kind}",
                HANDOFF_PACKETS_DIR_REL,
            )
        )
        findings.extend(_dispatcher_boundary_findings(code_prefix))
        return findings

    records, warnings = _load_handoff_packet_records(inventory.root, code_prefix)
    findings.extend(warnings)
    if not records:
        findings.append(Finding("warn", f"{code_prefix}-refused", f"no repo-visible handoff packet is launchable; {DISPATCHER_LAUNCH_REQUIRED_MESSAGE}", HANDOFF_PACKETS_DIR_REL))
        findings.extend(_dispatcher_boundary_findings(code_prefix))
        return findings

    ready_count = 0
    for rel_path, data in records:
        packet_ready, packet_findings = _dispatcher_packet_findings(inventory.root, rel_path, data, code_prefix)
        if packet_ready:
            ready_count += 1
        findings.extend(packet_findings)

    if ready_count:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-summary",
                f"{ready_count} handoff packet(s) have dispatcher launch-ready refs; no worker process was started by this report",
                HANDOFF_PACKETS_DIR_REL,
            )
        )
    else:
        findings.append(Finding("warn", f"{code_prefix}-summary", f"no handoff packet passed dispatcher launch preconditions; {DISPATCHER_LAUNCH_REQUIRED_MESSAGE}", HANDOFF_PACKETS_DIR_REL))
    findings.extend(_dispatcher_boundary_findings(code_prefix))
    return findings


def _load_handoff_packet_records(root: Path, code_prefix: str) -> tuple[list[tuple[str, dict[str, object]]], list[Finding]]:
    directory = root / HANDOFF_PACKETS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return [], []
    records: list[tuple[str, dict[str, object]]] = []
    findings: list[Finding] = []
    for path in sorted(directory.glob("*.json")):
        rel_path = _to_rel_path(root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code_prefix}-handoff-malformed", "handoff packet record path is not a regular file", rel_path))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", f"{code_prefix}-handoff-malformed", f"handoff packet record could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", f"{code_prefix}-handoff-malformed", "handoff packet JSON root must be an object", rel_path))
            continue
        records.append((rel_path, data))
    return records, findings


def _dispatcher_packet_findings(root: Path, rel_path: str, data: dict[str, object], code_prefix: str) -> tuple[bool, list[Finding]]:
    findings: list[Finding] = []
    blockers: list[str] = []
    handoff_id = str(data.get("handoff_id") or Path(rel_path).stem).strip() or Path(rel_path).stem
    worker_id = str(data.get("worker_id") or "").strip()
    role_id = str(data.get("role_id") or "").strip()
    execution_slice = str(data.get("execution_slice") or "").strip()
    status = str(data.get("status") or "").strip()

    if data.get("schema") != HANDOFF_PACKET_SCHEMA or data.get("record_type") != "handoff-packet":
        blockers.append("handoff packet schema or record_type is malformed")
    if status not in HANDOFF_PACKET_STATUSES:
        blockers.append(f"handoff status is not launchable: {status or '<missing>'}")
    if not worker_id:
        blockers.append("worker_id is missing")
    if not execution_slice:
        blockers.append("execution_slice is missing")
    if not role_id:
        blockers.append("role_id is missing")
    elif role_profile_for_id(role_id) is None:
        blockers.append(f"role_id is not in the advisory role manifest: {role_id}")
    forbidden_allowed_routes = _forbidden_allowed_routes(_json_list(data.get("allowed_routes")))
    if forbidden_allowed_routes:
        blockers.append(f"handoff allows lifecycle/provider-authority routes: {', '.join(forbidden_allowed_routes)}")

    claim_findings, claim_blockers = _dispatcher_claim_findings(root, data, rel_path, code_prefix)
    evidence_findings, evidence_blockers = _dispatcher_evidence_findings(root, data, rel_path, code_prefix)
    queue_findings, queue_blockers = _dispatcher_queue_findings(root, data, rel_path, code_prefix)
    scope_findings, scope_blockers = _dispatcher_scope_conflict_findings(root, data, rel_path, code_prefix)
    findings.extend(claim_findings)
    findings.extend(evidence_findings)
    findings.extend(queue_findings)
    findings.extend(scope_findings)
    blockers.extend(claim_blockers)
    blockers.extend(evidence_blockers)
    blockers.extend(queue_blockers)
    blockers.extend(scope_blockers)

    if blockers:
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-refused",
                (
                    f"handoff_id={handoff_id}; worker_id={worker_id or '<missing>'}; "
                    f"launch refused: {'; '.join(blockers)}; {DISPATCHER_LAUNCH_REQUIRED_MESSAGE}"
                ),
                rel_path,
            )
        )
        return False, findings

    findings.append(
        Finding(
            "info",
            f"{code_prefix}-ready",
            (
                f"handoff_id={handoff_id}; worker_id={worker_id}; role_id={role_id}; execution_slice={execution_slice}; "
                "repo-visible handoff, compatible active claim, planned/recorded agent-run evidence path, "
                "non-conflicting dispatch scope, and ready queue dependencies are present; "
                "this read-only status report did not start a worker"
            ),
            rel_path,
        )
    )
    return True, findings


def _dispatcher_claim_findings(root: Path, data: dict[str, object], rel_path: str, code_prefix: str) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    blockers: list[str] = []
    claim_refs = _json_list(data.get("claim_refs"))
    if not claim_refs:
        return findings, ["no work-claim ref is recorded on the handoff packet"]
    for ref in claim_refs:
        normalized = _normalize_ref(ref)
        if not normalized.startswith(f"{WORK_CLAIMS_DIR_REL}/") or not normalized.endswith(".json"):
            findings.append(Finding("warn", f"{code_prefix}-claim-ref-invalid", f"claim ref should point under {WORK_CLAIMS_DIR_REL}/*.json: {normalized}", rel_path))
            blockers.append(f"invalid claim ref {normalized}")
            continue
        conflict = _root_relative_path_conflict(normalized)
        if conflict:
            findings.append(Finding("warn", f"{code_prefix}-claim-ref-invalid", f"claim ref {conflict}: {normalized}", rel_path))
            blockers.append(f"unsafe claim ref {normalized}")
            continue
        target = root / normalized
        if not target.exists():
            findings.append(Finding("warn", f"{code_prefix}-claim-ref-missing", f"claim ref is missing: {normalized}", normalized))
            blockers.append(f"missing claim ref {normalized}")
            continue
        if target.is_symlink() or not target.is_file():
            findings.append(Finding("warn", f"{code_prefix}-claim-ref-invalid", f"claim ref is not a regular file: {normalized}", normalized))
            blockers.append(f"invalid claim ref {normalized}")
            continue
        try:
            claim_data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", f"{code_prefix}-claim-ref-malformed", f"claim ref could not be read as JSON: {exc}", normalized))
            blockers.append(f"malformed claim ref {normalized}")
            continue
        if not isinstance(claim_data, dict):
            findings.append(Finding("warn", f"{code_prefix}-claim-ref-malformed", "claim ref JSON root must be an object", normalized))
            blockers.append(f"malformed claim ref {normalized}")
            continue
        record_blockers = _dispatcher_claim_record_blockers(data, claim_data)
        if record_blockers:
            blockers.extend(f"{normalized}: {blocker}" for blocker in record_blockers)
            findings.append(Finding("warn", f"{code_prefix}-claim-ref-incompatible", f"claim ref is not compatible for launch: {'; '.join(record_blockers)}", normalized))
            continue
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-claim-ref-ready",
                f"compatible active claim ref: {normalized}; fingerprint={_file_fingerprint(target)}",
                normalized,
            )
        )
    return findings, blockers


def _dispatcher_claim_record_blockers(handoff_data: dict[str, object], claim_data: dict[str, object]) -> list[str]:
    blockers: list[str] = []
    if claim_data.get("schema") != WORK_CLAIM_SCHEMA or claim_data.get("record_type") != "work-claim":
        blockers.append(f"claim must be a {WORK_CLAIM_SCHEMA} work-claim record")
    status = str(claim_data.get("status") or "").strip()
    if status != "active":
        blockers.append(f"claim status is {status or '<missing>'}, not active")
    lease = str(claim_data.get("lease_expires_at") or "").strip()
    parsed_lease = _parse_utc_timestamp(lease) if lease else None
    if parsed_lease and parsed_lease < datetime.now(timezone.utc):
        blockers.append("claim lease is stale")
    handoff_slice = str(handoff_data.get("execution_slice") or "").strip()
    claim_slice = str(claim_data.get("execution_slice") or "").strip()
    if handoff_slice and claim_slice and handoff_slice != claim_slice:
        blockers.append(f"claim execution_slice {claim_slice} does not match handoff execution_slice {handoff_slice}")
    write_scope = _json_list(handoff_data.get("write_scope"))
    claimed_paths = _json_list(claim_data.get("claimed_paths"))
    if write_scope and claimed_paths and not any(_paths_overlap(scope, claimed) for scope in write_scope for claimed in claimed_paths):
        blockers.append("claim claimed_paths do not overlap handoff write_scope")
    return blockers


def _dispatcher_queue_findings(root: Path, data: dict[str, object], rel_path: str, code_prefix: str) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    blockers: list[str] = []
    directory = root / SYMPHONY_QUEUE_DIR_REL
    if not directory.exists() or not directory.is_dir():
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-queue-missing",
                f"no optional-orchestrator queue item directory exists at {SYMPHONY_QUEUE_DIR_REL}; dispatch preflight requires repo-visible queue readiness",
                rel_path,
            )
        )
        return findings, ["no ready optional-orchestrator queue item is repo-visible"]

    records, warnings = _dispatcher_queue_records(root, code_prefix)
    findings.extend(warnings)
    if not records:
        findings.append(Finding("warn", f"{code_prefix}-queue-missing", "no readable optional-orchestrator queue item records were found", rel_path))
        return findings, ["no readable optional-orchestrator queue item is repo-visible"]

    current_by_key = _dispatcher_queue_current_item_index(records)
    matches = _dispatcher_queue_matching_records(records, rel_path, data)
    if not matches:
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-queue-unmatched",
                "no optional-orchestrator queue item references this handoff/claim/agent-run contract; dispatch preflight remains refused",
                rel_path,
            )
        )
        return findings, ["no optional-orchestrator queue item matches the handoff contract"]

    ready_count = 0
    for queue_rel, queue_data in matches:
        item_blockers = _dispatcher_queue_item_blockers(root, current_by_key, queue_rel, queue_data)
        if item_blockers:
            blockers.extend(f"{queue_rel}: {blocker}" for blocker in item_blockers)
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-queue-not-ready",
                    f"queue item is not dispatch-ready: {'; '.join(item_blockers)}",
                    queue_rel,
                )
            )
            continue
        ready_count += 1
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-queue-ready",
                "queue item is dispatch-ready from current repo-visible state; embedded blocked_by snapshots are not authority",
                queue_rel,
            )
        )

    if ready_count:
        return findings, []
    return findings, blockers or ["no matched optional-orchestrator queue item passed readiness"]


def _dispatcher_queue_records(root: Path, code_prefix: str) -> tuple[list[tuple[str, dict[str, object]]], list[Finding]]:
    records: list[tuple[str, dict[str, object]]] = []
    findings: list[Finding] = []
    for path in sorted((root / SYMPHONY_QUEUE_DIR_REL).glob("*.json")):
        rel_path = _to_rel_path(root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code_prefix}-queue-malformed", "queue item path is not a regular file", rel_path))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", f"{code_prefix}-queue-malformed", f"queue item could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", f"{code_prefix}-queue-malformed", "queue item JSON root must be an object", rel_path))
            continue
        records.append((rel_path, data))
    return records, findings


def _dispatcher_queue_matching_records(
    records: list[tuple[str, dict[str, object]]],
    handoff_rel: str,
    handoff_data: dict[str, object],
) -> list[tuple[str, dict[str, object]]]:
    handoff_id = str(handoff_data.get("handoff_id") or Path(handoff_rel).stem).strip()
    worker_id = str(handoff_data.get("worker_id") or "").strip()
    execution_slice = str(handoff_data.get("execution_slice") or "").strip()
    handoff_refs = {handoff_rel, _normalize_ref(handoff_rel), handoff_id}
    claim_refs = set(_json_list(handoff_data.get("claim_refs")))
    evidence_refs = set(_json_list(handoff_data.get("evidence_refs")))
    matches: list[tuple[str, dict[str, object]]] = []
    for queue_rel, queue_data in records:
        queue_refs = set(_dispatcher_queue_ref_values(queue_rel, queue_data))
        if handoff_refs.intersection(queue_refs):
            matches.append((queue_rel, queue_data))
            continue
        if claim_refs.intersection(queue_refs) or evidence_refs.intersection(queue_refs):
            matches.append((queue_rel, queue_data))
            continue
        queue_worker = str(queue_data.get("assigned_to_worker") or queue_data.get("worker_id") or "").strip()
        queue_slice = str(queue_data.get("execution_slice") or queue_data.get("slice") or "").strip()
        if worker_id and execution_slice and queue_worker == worker_id and queue_slice == execution_slice:
            matches.append((queue_rel, queue_data))
    return matches


def _dispatcher_queue_ref_values(rel_path: str, data: dict[str, object]) -> tuple[str, ...]:
    values: list[str] = [rel_path, Path(rel_path).stem]
    for field in (
        "id",
        "identifier",
        "queue_item_id",
        "item_id",
        "handoff_id",
        "handoff_ref",
        "handoff",
        "claim_ref",
        "agent_run_ref",
        "evidence_ref",
        "execution_slice",
    ):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            values.append(_normalize_ref(value))
    for field in ("handoff_refs", "claim_refs", "agent_run_refs", "evidence_refs"):
        values.extend(_normalize_ref(value) for value in _json_list(data.get(field)))
    return tuple(dict.fromkeys(value for value in values if value))


def _dispatcher_queue_current_item_index(records: list[tuple[str, dict[str, object]]]) -> dict[str, tuple[str, dict[str, object]]]:
    current_by_key: dict[str, tuple[str, dict[str, object]]] = {}
    for rel_path, data in records:
        for value in _dispatcher_queue_ref_values(rel_path, data):
            key = _dispatcher_queue_key(value)
            if key:
                current_by_key.setdefault(key, (rel_path, data))
    return current_by_key


def _dispatcher_queue_item_blockers(
    root: Path,
    current_by_key: dict[str, tuple[str, dict[str, object]]],
    rel_path: str,
    data: dict[str, object],
) -> list[str]:
    blockers: list[str] = []
    state = _dispatcher_queue_state(data)
    if state in SYMPHONY_QUEUE_BLOCKED_STATES:
        blockers.append(f"queue state is blocked: {state}")
    elif state in SYMPHONY_QUEUE_TERMINAL_STATES:
        blockers.append(f"queue state is already terminal: {state}")
    elif state and state not in SYMPHONY_QUEUE_READY_STATES:
        blockers.append(f"queue state is not dispatch-ready: {state}")
    assigned = data.get("assigned_to_worker")
    if assigned is False or str(assigned).strip().casefold() in {"false", "none", "null", "unassigned"}:
        blockers.append("queue item is not assigned to a worker")
    planning_reliance = str(data.get("planning_reliance") or "").strip().casefold()
    if planning_reliance == "blocked":
        blockers.append("planning_reliance is blocked")
    for dependency in _dispatcher_queue_blocked_by_items(data.get("blocked_by")):
        current = _dispatcher_queue_resolve_dependency(root, current_by_key, dependency)
        label = _dispatcher_queue_dependency_label(dependency)
        if current is None:
            blockers.append(f"blocked_by dependency {label} is unresolved")
            continue
        current_rel, current_data = current
        current_state = _dispatcher_queue_state(current_data)
        if current_state not in SYMPHONY_QUEUE_TERMINAL_STATES:
            blockers.append(f"blocked_by dependency {label} resolves to non-terminal state {current_state or '<missing>'} from {current_rel}")
    return blockers


def _dispatcher_queue_blocked_by_items(value: object) -> tuple[dict[str, object], ...]:
    if isinstance(value, list):
        blockers: list[dict[str, object]] = []
        for item in value:
            if isinstance(item, dict):
                blockers.append(dict(item))
            elif str(item).strip():
                blockers.append({"id": str(item).strip()})
        return tuple(blockers)
    if isinstance(value, dict):
        return (dict(value),)
    if isinstance(value, str) and value.strip():
        return ({"id": value.strip()},)
    return ()


def _dispatcher_queue_resolve_dependency(
    root: Path,
    current_by_key: dict[str, tuple[str, dict[str, object]]],
    dependency: dict[str, object],
) -> tuple[str, dict[str, object]] | None:
    for field in ("id", "identifier", "queue_item_id", "item_id", "path", "ref", "url"):
        value = dependency.get(field)
        key = _dispatcher_queue_key(value)
        if key and key in current_by_key:
            return current_by_key[key]
        rel = _dispatcher_queue_ref_to_rel(root, value)
        if rel and rel in current_by_key:
            return current_by_key[rel]
    return None


def _dispatcher_queue_ref_to_rel(root: Path, value: object) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if not text or "://" in text:
        return ""
    while text.startswith("./"):
        text = text[2:]
    conflict = root_relative_path_conflict(text)
    if conflict:
        return ""
    path = Path(text)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root.resolve()).as_posix().casefold()
        except (OSError, RuntimeError, ValueError):
            return ""
    return text.strip("/").casefold()


def _dispatcher_queue_key(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/").casefold()


def _dispatcher_queue_state(data: dict[str, object]) -> str:
    return str(data.get("state") or data.get("status") or "").strip().casefold()


def _dispatcher_queue_dependency_label(dependency: dict[str, object]) -> str:
    for field in ("id", "identifier", "queue_item_id", "item_id", "path", "ref", "url"):
        value = str(dependency.get(field) or "").strip()
        if value:
            return f"{field}={value}"
    return "<unlabeled>"


def _dispatcher_scope_conflict_findings(root: Path, data: dict[str, object], rel_path: str, code_prefix: str) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    blockers: list[str] = []
    write_scope = _json_list(data.get("write_scope"))
    claim_refs = set(_normalize_ref(ref) for ref in _json_list(data.get("claim_refs")))
    if not write_scope:
        return findings, ["handoff write_scope is missing"]
    directory = root / WORK_CLAIMS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return findings, blockers
    for path in sorted(directory.glob("*.json")):
        claim_rel = _to_rel_path(root, path)
        if claim_rel in claim_refs:
            continue
        try:
            claim_data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(claim_data, dict):
            continue
        if claim_data.get("schema") != WORK_CLAIM_SCHEMA or claim_data.get("record_type") != "work-claim":
            continue
        if str(claim_data.get("status") or "").strip() != "active":
            continue
        claim_kind = str(claim_data.get("claim_kind") or "").strip()
        if claim_kind not in {"write", "lifecycle", "route", "path", "resource", "port", "database", "external_service"}:
            continue
        claimed_paths = _json_list(claim_data.get("claimed_paths"))
        overlap = next((f"{scope}<->{claimed}" for scope in write_scope for claimed in claimed_paths if _paths_overlap(scope, claimed)), "")
        if not overlap:
            continue
        blockers.append(f"overlapping active claim {claim_rel}: {overlap}")
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-scope-conflict",
                f"handoff write_scope conflicts with another active exclusive work claim: {overlap}; release or narrow the claim before dispatch",
                claim_rel,
            )
        )
    return findings, blockers


def _forbidden_allowed_routes(routes: tuple[str, ...]) -> tuple[str, ...]:
    forbidden: list[str] = []
    for route in routes:
        normalized = route.strip().casefold()
        command = normalized.split()[0] if normalized.split() else normalized
        if command in HANDOFF_WORKER_FORBIDDEN_ROUTES or "--apply" in normalized or "archive" in normalized:
            forbidden.append(route)
    return tuple(dict.fromkeys(forbidden))


def _dispatcher_evidence_findings(root: Path, data: dict[str, object], rel_path: str, code_prefix: str) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    blockers: list[str] = []
    evidence_refs = _json_list(data.get("evidence_refs"))
    if not evidence_refs:
        return findings, ["no agent-run evidence path is recorded on the handoff packet"]
    for ref in evidence_refs:
        normalized = _normalize_ref(ref)
        if not normalized.startswith(f"{AGENT_RUNS_DIR_REL}/") or not normalized.endswith(".md"):
            findings.append(Finding("warn", f"{code_prefix}-evidence-ref-invalid", f"evidence ref should point under {AGENT_RUNS_DIR_REL}/*.md: {normalized}", rel_path))
            blockers.append(f"invalid evidence ref {normalized}")
            continue
        conflict = _root_relative_path_conflict(normalized)
        if conflict:
            findings.append(Finding("warn", f"{code_prefix}-evidence-ref-invalid", f"evidence ref {conflict}: {normalized}", rel_path))
            blockers.append(f"unsafe evidence ref {normalized}")
            continue
        target = root / normalized
        boundary_violation = source_path_boundary_violation(root, target, label="dispatcher evidence ref")
        if boundary_violation is not None:
            findings.append(Finding("warn", f"{code_prefix}-evidence-ref-invalid", boundary_violation.message, normalized))
            blockers.append(f"unsafe evidence ref {normalized}")
            continue
        if not target.exists():
            findings.append(Finding("info", f"{code_prefix}-evidence-planned", f"planned agent-run evidence path is available for dispatcher tracking: {normalized}", normalized))
            continue
        if target.is_symlink() or not target.is_file():
            findings.append(Finding("warn", f"{code_prefix}-evidence-ref-invalid", f"evidence ref is not a regular file: {normalized}", normalized))
            blockers.append(f"invalid evidence ref {normalized}")
            continue
        try:
            frontmatter = parse_frontmatter(target.read_text(encoding="utf-8"))
        except OSError as exc:
            findings.append(Finding("warn", f"{code_prefix}-evidence-ref-unreadable", f"evidence ref could not be read: {exc}", normalized))
            blockers.append(f"unreadable evidence ref {normalized}")
            continue
        if not frontmatter.has_frontmatter or frontmatter.data.get("schema") != AGENT_RUN_SCHEMA:
            findings.append(Finding("warn", f"{code_prefix}-evidence-ref-malformed", f"evidence ref existing record should use schema {AGENT_RUN_SCHEMA}", normalized))
            blockers.append(f"malformed evidence ref {normalized}")
            continue
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-evidence-recorded",
                f"agent-run evidence path is already recorded/readable: {normalized}; fingerprint={_file_fingerprint(target)}",
                normalized,
            )
        )
    return findings, blockers


def _dispatcher_boundary_findings(code_prefix: str) -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-no-spawn-boundary",
            "dispatcher launch status is read-only; it starts no worker, daemon, queue, provider gateway, network listener, hook install, or runtime cache mutation",
            HANDOFF_PACKETS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-authority-boundary",
            "handoffs, claims, and agent-run evidence paths are repo-visible launch preconditions only; lifecycle, fan-in, archive, Git, release, and roadmap decisions remain explicit MLH rails",
            HANDOFF_PACKETS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-completion-claim-policy",
            "external completion claims must cite repo-visible handoff/claim/agent-run evidence; external tracker/orchestrator status alone is not launch or closeout evidence",
            HANDOFF_PACKETS_DIR_REL,
        ),
    ]


def _request_findings(inventory: Inventory, request: HandoffPacketRequest, *, apply: bool) -> list[Finding]:
    severity = "error" if apply else "warn"
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(Finding(severity, "handoff-packet-refused", f"target root kind is {inventory.root_kind}; handoff packet writes require a live operating root"))
    if request.action not in {"create", "accept"}:
        findings.append(Finding("error", "handoff-packet-refused", "--action must be create or accept"))
    if request.action == "accept":
        if not request.handoff_id:
            findings.append(Finding("error", "handoff-packet-refused", "--handoff-id is required"))
        elif not ID_RE.match(request.handoff_id):
            findings.append(Finding("error", "handoff-packet-refused", "--handoff-id may contain only letters, digits, dot, underscore, or dash"))
        elif record_id_conflict(request.handoff_id):
            findings.append(Finding("error", "handoff-packet-refused", f"--handoff-id {record_id_conflict(request.handoff_id)}"))
        if not request.accepted_by:
            findings.append(Finding("error", "handoff-packet-refused", "--accepted-by is required for --action accept"))
        if request.handoff_id:
            rel_path = _packet_rel_path(request.handoff_id)
            target = inventory.root / rel_path
            if not target.exists():
                findings.append(Finding(severity, "handoff-packet-refused", "cannot accept a missing handoff packet", rel_path))
            elif target.is_symlink() or not target.is_file():
                findings.append(Finding(severity, "handoff-packet-refused", "handoff packet target is not a regular file", rel_path))
            else:
                try:
                    data = json.loads(target.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    findings.append(Finding(severity, "handoff-packet-refused", f"cannot accept unreadable or malformed handoff packet: {exc}", rel_path))
                else:
                    if not isinstance(data, dict):
                        findings.append(Finding(severity, "handoff-packet-refused", "cannot accept handoff packet with non-object JSON root", rel_path))
                    elif data.get("status") == "accepted":
                        findings.append(Finding(severity, "handoff-packet-refused", "handoff packet is already accepted", rel_path))
        return findings
    for field, value in (
        ("--handoff-id", request.handoff_id),
        ("--worker-id", request.worker_id),
        ("--role-id", request.role_id),
        ("--execution-slice", request.execution_slice),
    ):
        if not value:
            findings.append(Finding("error", "handoff-packet-refused", f"{field} is required"))
    if request.handoff_id and not ID_RE.match(request.handoff_id):
        findings.append(Finding("error", "handoff-packet-refused", "--handoff-id may contain only letters, digits, dot, underscore, or dash"))
    elif request.handoff_id and record_id_conflict(request.handoff_id):
        findings.append(Finding("error", "handoff-packet-refused", f"--handoff-id {record_id_conflict(request.handoff_id)}"))
    if not request.allowed_routes:
        findings.append(Finding("error", "handoff-packet-refused", "--allowed-route must be supplied at least once"))
    if not request.write_scope:
        findings.append(Finding("error", "handoff-packet-refused", "--write-scope must be supplied at least once"))
    if not request.stop_conditions:
        findings.append(Finding("error", "handoff-packet-refused", "--stop-condition must be supplied at least once"))
    if not request.required_outputs:
        findings.append(Finding("error", "handoff-packet-refused", "--required-output must be supplied at least once"))
    if not request.evidence_refs:
        findings.append(Finding("error", "handoff-packet-refused", "--evidence-ref must be supplied at least once"))
    if not request.claim_refs:
        findings.append(Finding("error", "handoff-packet-refused", "--claim-ref must be supplied at least once"))
    forbidden_routes = sorted(_forbidden_allowed_routes(request.allowed_routes))
    if forbidden_routes:
        findings.append(
            Finding(
                "error",
                "handoff-packet-refused",
                f"worker handoff cannot allow lifecycle-authority routes: {', '.join(forbidden_routes)}",
            )
        )
    for flag, values in (
        ("--write-scope", request.write_scope),
        ("--evidence-ref", request.evidence_refs),
        ("--approval-packet-ref", request.approval_packet_refs),
        ("--claim-ref", request.claim_refs),
    ):
        for rel_path in values:
            conflict = _root_relative_path_conflict(rel_path)
            if conflict:
                findings.append(Finding("error", "handoff-packet-refused", f"{flag} {conflict}", rel_path))
    if request.handoff_id:
        rel_path = _packet_rel_path(request.handoff_id)
        target = inventory.root / rel_path
        conflict = _root_relative_path_conflict(rel_path)
        if conflict:
            findings.append(Finding("error", "handoff-packet-refused", f"handoff target {conflict}", rel_path))
        if target.exists():
            findings.append(Finding(severity, "handoff-packet-refused", "handoff packet already exists; choose a new --handoff-id", rel_path))
    return findings


def _handoff_packet_metadata_findings(data: dict[str, object], rel_path: str, code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    if data.get("schema") != HANDOFF_PACKET_SCHEMA:
        findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet schema should be {HANDOFF_PACKET_SCHEMA}", rel_path))
    if data.get("record_type") != "handoff-packet":
        findings.append(Finding("warn", f"{code_prefix}-malformed", "handoff packet record_type should be handoff-packet", rel_path))
    for field in HANDOFF_PACKET_REQUIRED_SCALARS:
        if not str(data.get(field) or "").strip():
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet {field} is required", rel_path))
    handoff_id = str(data.get("handoff_id") or "").strip()
    if handoff_id and not ID_RE.match(handoff_id):
        findings.append(Finding("warn", f"{code_prefix}-malformed", "handoff packet handoff_id may contain only letters, digits, dot, underscore, or dash", rel_path))
    elif handoff_id and record_id_conflict(handoff_id):
        findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet handoff_id {record_id_conflict(handoff_id)}", rel_path))
    status = str(data.get("status") or "").strip()
    if status and status not in HANDOFF_PACKET_STATUSES:
        findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet status is unsupported: {status}", rel_path))
    for field in (*HANDOFF_PACKET_REQUIRED_LISTS, *HANDOFF_PACKET_REF_LISTS):
        value = data.get(field)
        if value not in (None, "") and not isinstance(value, list):
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet {field} must be a list of strings", rel_path))
            continue
        if field in HANDOFF_PACKET_REQUIRED_LISTS and not _json_list(value):
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet {field} must contain at least one value", rel_path))
    for rel in _json_list(data.get("write_scope")):
        conflict = _root_relative_path_conflict(rel)
        if conflict:
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet write_scope {conflict}", rel_path))
    return findings


def _handoff_packet_ref_findings(root: Path, data: dict[str, object], rel_path: str, code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    for ref in _json_list(data.get("evidence_refs")):
        findings.extend(_generic_ref_findings(root, ref, rel_path, code_prefix, "evidence"))
    for ref in _json_list(data.get("approval_packet_refs")):
        findings.extend(
            _typed_json_ref_findings(
                root,
                ref,
                rel_path,
                code_prefix,
                label="approval-packet",
                directory_rel=APPROVAL_PACKETS_DIR_REL,
                schema=APPROVAL_PACKET_SCHEMA,
                record_type="approval-packet",
            )
        )
    for ref in _json_list(data.get("claim_refs")):
        findings.extend(
            _typed_json_ref_findings(
                root,
                ref,
                rel_path,
                code_prefix,
                label="work-claim",
                directory_rel=WORK_CLAIMS_DIR_REL,
                schema=WORK_CLAIM_SCHEMA,
                record_type="work-claim",
            )
        )
    return findings


def _generic_ref_findings(root: Path, ref: str, rel_path: str, code_prefix: str, label: str) -> list[Finding]:
    target, degraded = _ref_target(root, ref, rel_path, code_prefix, label)
    if degraded:
        return degraded
    try:
        target.read_bytes()
    except OSError as exc:
        return [Finding("warn", f"{code_prefix}-{label}-ref-unreadable", f"handoff packet {label} ref could not be read: {exc}", ref)]
    return [
        Finding(
            "info",
            f"{code_prefix}-{label}-ref",
            f"handoff packet {label} ref is readable: {ref}; fingerprint={_file_fingerprint(target)}",
            ref,
        )
    ]


def _typed_json_ref_findings(
    root: Path,
    ref: str,
    rel_path: str,
    code_prefix: str,
    *,
    label: str,
    directory_rel: str,
    schema: str,
    record_type: str,
) -> list[Finding]:
    findings: list[Finding] = []
    normalized = _normalize_ref(ref)
    if not normalized.startswith(f"{directory_rel}/") or not normalized.endswith(".json"):
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-{label}-ref-invalid",
                f"handoff packet {label} ref should point under {directory_rel}/*.json",
                rel_path,
            )
        )
    target, degraded = _ref_target(root, normalized, rel_path, code_prefix, label)
    if degraded:
        return [*findings, *degraded]
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return [*findings, Finding("warn", f"{code_prefix}-{label}-ref-unreadable", f"handoff packet {label} ref could not be read: {exc}", normalized)]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [*findings, Finding("warn", f"{code_prefix}-{label}-ref-malformed", f"handoff packet {label} ref is not valid JSON: {exc}", normalized)]
    if not isinstance(data, dict):
        return [*findings, Finding("warn", f"{code_prefix}-{label}-ref-malformed", f"handoff packet {label} ref JSON root must be an object", normalized)]
    if data.get("schema") != schema or data.get("record_type") != record_type:
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-{label}-ref-malformed",
                f"handoff packet {label} ref must be a {schema} {record_type} record",
                normalized,
            )
        )
    findings.append(
        Finding(
            "info",
            f"{code_prefix}-{label}-ref",
            f"handoff packet {label} ref is readable: {normalized}; fingerprint={_file_fingerprint(target)}",
            normalized,
        )
    )
    return findings


def _ref_target(root: Path, ref: str, rel_path: str, code_prefix: str, label: str) -> tuple[Path, list[Finding]]:
    normalized = _normalize_ref(ref)
    conflict = _root_relative_path_conflict(normalized)
    if conflict:
        return root / normalized, [Finding("warn", f"{code_prefix}-{label}-ref-invalid", f"handoff packet {label} ref {conflict}", rel_path)]
    target = root / normalized
    if not target.exists():
        return target, [Finding("warn", f"{code_prefix}-{label}-ref-missing", f"handoff packet {label} ref is missing: {normalized}", normalized)]
    if target.is_symlink() or not target.is_file():
        return target, [Finding("warn", f"{code_prefix}-{label}-ref-invalid", f"handoff packet {label} ref is not a regular file: {normalized}", normalized)]
    return target, []


def _packet_data(request: HandoffPacketRequest) -> dict[str, object]:
    return {
        "schema": HANDOFF_PACKET_SCHEMA,
        "record_type": "handoff-packet",
        "handoff_id": request.handoff_id,
        "status": "created",
        "worker_id": request.worker_id,
        "role_id": request.role_id,
        "execution_slice": request.execution_slice,
        "worktree_id": request.worktree_id,
        "branch": request.branch,
        "base_revision": request.base_revision,
        "head_revision": request.head_revision,
        "allowed_routes": list(request.allowed_routes),
        "write_scope": list(request.write_scope),
        "stop_conditions": list(request.stop_conditions),
        "context_budget": request.context_budget,
        "required_outputs": list(request.required_outputs),
        "evidence_refs": list(request.evidence_refs),
        "approval_packet_refs": list(request.approval_packet_refs),
        "claim_refs": list(request.claim_refs),
        "created_at_utc": _utc_timestamp(),
        "authority_boundary": "handoff packets are context and coordination evidence only; they do not grant lifecycle, archive, Git, or release authority",
    }


def _accept_fields(request: HandoffPacketRequest) -> dict[str, object]:
    data: dict[str, object] = {
        "status": "accepted",
        "accepted_by": request.accepted_by,
        "accepted_at_utc": _utc_timestamp(),
    }
    if request.acceptance_note:
        data["acceptance_note"] = request.acceptance_note
    return data


def _packet_shape_findings(request: HandoffPacketRequest) -> list[Finding]:
    return [
        Finding(
            "info",
            "handoff-packet-shape",
            (
                f"allowed_routes={len(request.allowed_routes)}; write_scope={len(request.write_scope)}; "
                f"stop_conditions={len(request.stop_conditions)}; required_outputs={len(request.required_outputs)}; "
                f"evidence_refs={len(request.evidence_refs)}; claim_refs={len(request.claim_refs)}; "
                f"approval_packet_refs={len(request.approval_packet_refs)}"
            ),
            _packet_rel_path(request.handoff_id),
        )
    ]


def _boundary_findings(code_prefix: str = "handoff-packet") -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "handoff packets carry allowed routes, write scope, stop conditions, context budget, required outputs, evidence refs, approval-packet refs, and claim refs without granting worker lifecycle authority",
            HANDOFF_PACKETS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-route",
            f"handoff packets live under {HANDOFF_PACKETS_DIR_REL}/*.json as repo-visible evidence; no hidden runtime, queue, database, adapter state, or worker spawn is created",
            HANDOFF_PACKETS_DIR_REL,
        ),
    ]


def _packet_rel_path(handoff_id: str) -> str:
    return f"{HANDOFF_PACKETS_DIR_REL}/{handoff_id}.json"


def _packet_json(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _load_packet_data(root: Path, handoff_id: str) -> dict[str, object]:
    return json.loads((root / _packet_rel_path(handoff_id)).read_text(encoding="utf-8"))


def _route_write_finding(rel_path: str, before_data: dict[str, object] | None, after_data: dict[str, object], *, apply: bool) -> Finding:
    before_text = None if before_data is None else _packet_json(before_data)
    after_text = _packet_json(after_data)
    operation = "created" if apply and before_data is None else "wrote" if apply else "create" if before_data is None else "write"
    prefix = "" if apply else "would "
    return Finding(
        "info",
        "handoff-packet-route-write",
        (
            f"{prefix}{operation} route {rel_path}; before_hash={_hash_or_missing(before_text)}; "
            f"after_hash={_short_hash(after_text)}; before_bytes={_bytes_or_missing(before_text)}; "
            f"after_bytes={len(after_text.encode('utf-8'))}; source-bound write evidence is independent of Git tracking"
        ),
        rel_path,
    )


def _tuple_values(values: object, *, path_like: bool = True) -> tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, str):
        values = (values,)
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        cleaned.append(_normalize_ref(text) if path_like else text)
    return tuple(dict.fromkeys(cleaned))


def _json_list(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _root_relative_path_conflict(rel_path: str) -> str:
    return root_relative_path_conflict(_normalize_ref(rel_path))


def _normalize_ref(value: str) -> str:
    return str(value or "").replace("\\", "/").strip()


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = tuple(_normalize_ref(left).split("/"))
    right_parts = tuple(_normalize_ref(right).split("/"))
    if not left_parts or not right_parts:
        return False
    shorter, longer = (left_parts, right_parts) if len(left_parts) <= len(right_parts) else (right_parts, left_parts)
    return longer[: len(shorter)] == shorter


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


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _hash_or_missing(text: str | None) -> str:
    return "missing" if text is None else _short_hash(text)


def _bytes_or_missing(text: str | None) -> str:
    return "missing" if text is None else str(len(text.encode("utf-8")))


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


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
