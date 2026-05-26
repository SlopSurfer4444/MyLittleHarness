from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory
from .models import Finding


APPROVAL_PACKET_SCHEMA = "mylittleharness.approval-packet.v1"
APPROVAL_PACKETS_DIR_REL = "project/verification/approval-packets"
APPROVAL_STATUSES = {"pending", "approved", "rejected", "needs-review"}
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class ApprovalPacketRequest:
    approval_id: str
    requester: str
    subject: str
    requested_decision: str
    gate_class: str
    status: str
    input_refs: tuple[str, ...]
    human_gate_conditions: tuple[str, ...]
    notes: str


def make_approval_packet_request(args: object) -> ApprovalPacketRequest:
    return ApprovalPacketRequest(
        approval_id=str(getattr(args, "approval_id", "") or "").strip(),
        requester=str(getattr(args, "requester", "") or "").strip(),
        subject=str(getattr(args, "subject", "") or "").strip(),
        requested_decision=str(getattr(args, "requested_decision", "") or "").strip(),
        gate_class=str(getattr(args, "gate_class", "") or "").strip(),
        status=str(getattr(args, "status", "") or "").strip() or "pending",
        input_refs=_tuple_values(getattr(args, "input_refs", ())),
        human_gate_conditions=_tuple_values(getattr(args, "human_gate_conditions", ()), path_like=False),
        notes=str(getattr(args, "notes", "") or "").strip(),
    )


def approval_packet_dry_run_findings(inventory: Inventory, request: ApprovalPacketRequest) -> list[Finding]:
    findings = [
        Finding("info", "approval-packet-dry-run", "approval packet proposal only; no files were written"),
        Finding("info", "approval-packet-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _request_findings(inventory, request, apply=False)
    findings.extend(request_findings)
    if any(finding.severity in {"warn", "error"} for finding in request_findings):
        findings.append(Finding("info", "approval-packet-validation-posture", "dry-run refused before apply; fix explicit approval fields before writing packet evidence"))
        findings.extend(_boundary_findings())
        return findings

    text = _packet_json(_packet_data(request))
    rel_path = _packet_rel_path(request.approval_id)
    findings.append(Finding("info", "approval-packet-target", f"would write approval packet: {rel_path}", rel_path))
    findings.append(
        Finding(
            "info",
            "approval-packet-route-write",
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


def approval_packet_apply_findings(inventory: Inventory, request: ApprovalPacketRequest) -> list[Finding]:
    findings = [
        Finding("info", "approval-packet-apply", "approval packet apply started"),
        Finding("info", "approval-packet-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _request_findings(inventory, request, apply=True)
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "approval-packet-apply-refused", "approval packet apply refused before writing packet evidence"))
        findings.extend(_boundary_findings())
        return findings

    rel_path = _packet_rel_path(request.approval_id)
    target = inventory.root / rel_path
    text = _packet_json(_packet_data(request))
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
        findings.append(Finding("error", "approval-packet-refused", f"failed to write approval packet before apply completed: {exc}", rel_path))
        findings.extend(_boundary_findings())
        return findings

    findings.append(Finding("info", "approval-packet-written", f"created approval packet: {rel_path}", rel_path))
    findings.append(
        Finding(
            "info",
            "approval-packet-route-write",
            (
                f"created route {rel_path}; before_hash=missing; after_hash={_short_hash(text)}; "
                f"before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; "
                "source-bound write evidence is independent of Git tracking"
            ),
            rel_path,
        )
    )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "approval-packet-backup-cleanup", warning, rel_path))
    findings.extend(_packet_shape_findings(request))
    findings.extend(_boundary_findings())
    return findings


def _request_findings(inventory: Inventory, request: ApprovalPacketRequest, *, apply: bool) -> list[Finding]:
    severity = "error" if apply else "warn"
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(Finding(severity, "approval-packet-refused", f"target root kind is {inventory.root_kind}; approval packet writes require a live operating root"))
    for field, value in (
        ("--approval-id", request.approval_id),
        ("--requester", request.requester),
        ("--subject", request.subject),
        ("--requested-decision", request.requested_decision),
        ("--gate-class", request.gate_class),
    ):
        if not value:
            findings.append(Finding("error", "approval-packet-refused", f"{field} is required"))
    if request.approval_id and not ID_RE.match(request.approval_id):
        findings.append(Finding("error", "approval-packet-refused", "--approval-id may contain only letters, digits, dot, underscore, or dash"))
    if request.status not in APPROVAL_STATUSES:
        findings.append(Finding("error", "approval-packet-refused", f"--status must be one of {', '.join(sorted(APPROVAL_STATUSES))}"))
    if not request.input_refs:
        findings.append(Finding("error", "approval-packet-refused", "--input-ref must be supplied at least once"))
    if not request.human_gate_conditions:
        findings.append(Finding("error", "approval-packet-refused", "--human-gate-condition must be supplied at least once"))
    for rel_path in request.input_refs:
        conflict = _root_relative_path_conflict(rel_path)
        if conflict:
            findings.append(Finding("error", "approval-packet-refused", f"--input-ref {conflict}", rel_path))
    if request.approval_id:
        rel_path = _packet_rel_path(request.approval_id)
        target = inventory.root / rel_path
        if target.exists():
            findings.append(Finding(severity, "approval-packet-refused", "approval packet already exists; choose a new --approval-id", rel_path))
            findings.extend(_existing_packet_supersession_findings(inventory, request, rel_path, severity))
    return findings


def _existing_packet_supersession_findings(inventory: Inventory, request: ApprovalPacketRequest, rel_path: str, severity: str) -> list[Finding]:
    target = inventory.root / rel_path
    findings = [
        Finding(
            severity,
            "approval-packet-existing-route",
            (
                f"existing approval packet is append-only evidence; fingerprint={_file_fingerprint(target)}; "
                "do not hand-edit or treat packet status as lifecycle approval"
            ),
            rel_path,
        ),
        Finding(
            "info",
            "approval-packet-supersession-route",
            (
                "to record reviewed follow-up for this packet, create a new approval packet id and include the prior packet as "
                f"--input-ref {rel_path}; the new packet status remains evidence only and cannot transition the existing packet or approve lifecycle/archive/Git/release"
            ),
            rel_path,
        ),
    ]
    if request.status != "pending":
        findings.append(
            Finding(
                "info",
                "approval-packet-status-posture",
                (
                    f"requested status={request.status} would belong on a new superseding evidence packet, not as a mutation of {rel_path}"
                ),
                rel_path,
            )
        )
    return findings


def _packet_data(request: ApprovalPacketRequest) -> dict[str, object]:
    return {
        "schema": APPROVAL_PACKET_SCHEMA,
        "record_type": "approval-packet",
        "approval_id": request.approval_id,
        "requester": request.requester,
        "subject": request.subject,
        "requested_decision": request.requested_decision,
        "gate_class": request.gate_class,
        "status": request.status,
        "input_refs": list(request.input_refs),
        "human_gate_conditions": list(request.human_gate_conditions),
        "notes": request.notes,
        "created_at_utc": _utc_timestamp(),
        "authority_boundary": "approval packets record reviewed intent only; transport or approved status cannot approve lifecycle, archive, Git, or release by itself",
    }


def _packet_shape_findings(request: ApprovalPacketRequest) -> list[Finding]:
    status_note = "approved status is still append-only evidence" if request.status == "approved" else "status is append-only evidence"
    return [
        Finding(
            "info",
            "approval-packet-shape",
            (
                f"status={request.status}; gate_class={request.gate_class}; input_refs={len(request.input_refs)}; "
                f"human_gate_conditions={len(request.human_gate_conditions)}; {status_note}"
            ),
            _packet_rel_path(request.approval_id),
        )
    ]


def _boundary_findings(code_prefix: str = "approval-packet") -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "approval packets are human-gate evidence only; they cannot approve lifecycle transitions, archive, roadmap status, staging, commit, rollback, release, or external relay delivery",
            APPROVAL_PACKETS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-route",
            f"approval packets live under {APPROVAL_PACKETS_DIR_REL}/*.json as repo-visible evidence; no hidden transport, daemon, queue, database, adapter state, or secret store is created",
            APPROVAL_PACKETS_DIR_REL,
        ),
    ]


def _packet_rel_path(approval_id: str) -> str:
    return f"{APPROVAL_PACKETS_DIR_REL}/{approval_id}.json"


def _packet_json(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


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


def _root_relative_path_conflict(rel_path: str) -> str:
    normalized = _normalize_ref(rel_path)
    if not normalized:
        return "must be a non-empty root-relative path"
    if re.match(r"^[A-Za-z]:[\\/]", normalized) or normalized.startswith("/"):
        return "must be root-relative, not absolute"
    if any(part in {"..", ".", ""} for part in normalized.split("/")):
        return "must not contain parent traversal, current-directory, or empty path segments"
    return ""


def _normalize_ref(value: str) -> str:
    return str(value or "").replace("\\", "/").strip()


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _file_fingerprint(path) -> str:
    if not path.exists():
        return "missing"
    if path.is_symlink() or not path.is_file():
        return "invalid-path"
    try:
        return f"sha256={hashlib.sha256(path.read_bytes()).hexdigest()[:12]}"
    except OSError:
        return "unreadable"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
