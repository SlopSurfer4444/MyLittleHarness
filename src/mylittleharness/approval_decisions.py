from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory
from .models import Finding
from .root_boundary import record_id_conflict, root_relative_path_conflict


APPROVAL_DECISION_SCHEMA = "mylittleharness.approval-decision.v1"
APPROVAL_DECISIONS_DIR_REL = "project/decisions/owner-decisions"
APPROVAL_DECISIONS_DIR_SOURCE = f"{APPROVAL_DECISIONS_DIR_REL}/"
APPROVAL_PACKET_SCHEMA = "mylittleharness.approval-packet.v1"
APPROVAL_PACKET_DIR_PREFIX = "project/verification/approval-packets/"
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PROVIDER_AUTHORITY_RE = re.compile(r"\b(provider|credential|secret|api[- ]?key|token|sdk|runtime|session[- ]?active)\b", re.IGNORECASE)
SESSION_AUTHORITY_RE = re.compile(r"\b(session[- ]?active|sdk success|runtime success|provider success|verifier success)\b", re.IGNORECASE)
DECISION_OUTCOMES = {"approved-for-lifecycle-route", "rejected", "needs-review", "blocked"}


@dataclass(frozen=True)
class ApprovalDecisionRequest:
    decision_id: str
    owner_id: str
    decision_intent: str
    outcome: str
    approval_packet_refs: tuple[str, ...]
    allowed_scopes: tuple[str, ...]
    forbidden_decisions: tuple[str, ...]
    follow_up_routes: tuple[str, ...]
    owner_attestation: str
    notes: str


def make_approval_decision_request(args: object) -> ApprovalDecisionRequest:
    return ApprovalDecisionRequest(
        decision_id=str(getattr(args, "decision_id", "") or "").strip(),
        owner_id=str(getattr(args, "owner_id", "") or "").strip(),
        decision_intent=str(getattr(args, "decision_intent", "") or "").strip(),
        outcome=str(getattr(args, "outcome", "") or "").strip(),
        approval_packet_refs=_tuple_values(getattr(args, "approval_packet_refs", ())),
        allowed_scopes=_tuple_values(getattr(args, "allowed_scopes", ()), path_like=False),
        forbidden_decisions=_tuple_values(getattr(args, "forbidden_decisions", ()), path_like=False),
        follow_up_routes=_tuple_values(getattr(args, "follow_up_routes", ()), path_like=False),
        owner_attestation=str(getattr(args, "owner_attestation", "") or "").strip(),
        notes=str(getattr(args, "notes", "") or "").strip(),
    )


def approval_decision_dry_run_findings(inventory: Inventory, request: ApprovalDecisionRequest) -> list[Finding]:
    findings = [
        Finding("info", "approval-decision-dry-run", "owner-decision proposal only; no files were written"),
        Finding("info", "approval-decision-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings, packet_bindings = _request_findings(inventory, request, apply=False)
    findings.extend(request_findings)
    if any(finding.severity in {"warn", "error"} for finding in request_findings):
        findings.append(
            Finding(
                "info",
                "approval-decision-validation-posture",
                "dry-run refused before apply; fix explicit owner identity, intent, packet refs, scope, and authority boundaries before writing decision evidence",
            )
        )
        findings.extend(_boundary_findings())
        return findings

    data = _decision_data(request, packet_bindings)
    text = _decision_json(data)
    rel_path = _decision_rel_path(request.decision_id)
    findings.append(Finding("info", "approval-decision-target", f"would write owner decision: {rel_path}", rel_path))
    findings.append(
        Finding(
            "info",
            "approval-decision-route-write",
            (
                f"would create route {rel_path}; before_hash=missing; after_hash={_short_hash(text)}; "
                f"before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; "
                "decision evidence is separate from approval-packet transport and later lifecycle consumption"
            ),
            rel_path,
        )
    )
    findings.extend(_decision_shape_findings(request, packet_bindings))
    findings.extend(_boundary_findings())
    return findings


def approval_decision_apply_findings(inventory: Inventory, request: ApprovalDecisionRequest) -> list[Finding]:
    findings = [
        Finding("info", "approval-decision-apply", "owner-decision apply started"),
        Finding("info", "approval-decision-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings, packet_bindings = _request_findings(inventory, request, apply=True)
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "approval-decision-apply-refused", "owner-decision apply refused before writing decision evidence"))
        findings.extend(_boundary_findings())
        return findings

    data = _decision_data(request, packet_bindings)
    text = _decision_json(data)
    rel_path = _decision_rel_path(request.decision_id)
    target = inventory.root / rel_path
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
        findings.append(Finding("error", "approval-decision-refused", f"failed to write owner decision before apply completed: {exc}", rel_path))
        findings.extend(_boundary_findings())
        return findings

    findings.append(Finding("info", "approval-decision-written", f"created owner decision: {rel_path}", rel_path))
    findings.append(
        Finding(
            "info",
            "approval-decision-route-write",
            (
                f"created route {rel_path}; before_hash=missing; after_hash={_short_hash(text)}; "
                f"before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; "
                "decision evidence is separate from approval-packet transport and later lifecycle consumption"
            ),
            rel_path,
        )
    )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "approval-decision-backup-cleanup", warning, rel_path))
    findings.extend(_decision_shape_findings(request, packet_bindings))
    findings.extend(_boundary_findings())
    return findings


def approval_decision_status_findings(inventory: Inventory, code_prefix: str = "approval-decision") -> list[Finding]:
    directory = inventory.root / APPROVAL_DECISIONS_DIR_REL
    if not directory.exists():
        return [
            Finding(
                "info",
                f"{code_prefix}-none",
                "no owner-decision records found; approval packets, relay output, session-active work, and SDK/provider success remain evidence only",
                APPROVAL_DECISIONS_DIR_SOURCE,
            )
        ]
    findings: list[Finding] = []
    for path in sorted(directory.glob("*.json")):
        rel_path = _rel(path, inventory.root)
        data = _load_json(path)
        if not isinstance(data, dict):
            findings.append(Finding("warn", f"{code_prefix}-invalid", "owner-decision record is not a JSON object", rel_path))
            continue
        if data.get("schema") != APPROVAL_DECISION_SCHEMA or data.get("record_type") != "approval-decision":
            findings.append(Finding("warn", f"{code_prefix}-invalid", "owner-decision record has an unexpected schema or record_type", rel_path))
            continue
        outcome = str(data.get("outcome") or "")
        packet_count = len(data.get("approval_packet_bindings") or [])
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-record",
                (
                    f"owner decision {data.get('decision_id')} outcome={outcome}; packet_bindings={packet_count}; "
                    "later lifecycle routes must consume this record explicitly and rerun their own dry-run/apply guardrails"
                ),
                rel_path,
            )
        )
        if _mentions_provider_authority(data):
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-authority-confusion",
                    "owner-decision record appears to mention provider/credential/session authority; treat as suspicious evidence until reviewed",
                    rel_path,
                )
            )
    if not findings:
        findings.append(Finding("info", f"{code_prefix}-none", "no owner-decision JSON records found", APPROVAL_DECISIONS_DIR_SOURCE))
    return findings


def _request_findings(
    inventory: Inventory,
    request: ApprovalDecisionRequest,
    *,
    apply: bool,
) -> tuple[list[Finding], tuple[dict[str, object], ...]]:
    severity = "error" if apply else "warn"
    findings: list[Finding] = []
    packet_bindings: list[dict[str, object]] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(Finding(severity, "approval-decision-refused", f"target root kind is {inventory.root_kind}; owner decisions require a live operating root"))
    for field, value in (
        ("--decision-id", request.decision_id),
        ("--owner-id", request.owner_id),
        ("--decision-intent", request.decision_intent),
        ("--outcome", request.outcome),
        ("--owner-attestation", request.owner_attestation),
    ):
        if not value:
            findings.append(Finding("error", "approval-decision-refused", f"{field} is required"))
    if request.decision_id and not ID_RE.match(request.decision_id):
        findings.append(Finding("error", "approval-decision-refused", "--decision-id may contain only letters, digits, dot, underscore, or dash"))
    elif request.decision_id and record_id_conflict(request.decision_id):
        findings.append(Finding("error", "approval-decision-refused", f"--decision-id {record_id_conflict(request.decision_id)}"))
    if request.outcome and request.outcome not in DECISION_OUTCOMES:
        findings.append(Finding("error", "approval-decision-refused", f"--outcome must be one of {', '.join(sorted(DECISION_OUTCOMES))}"))
    if request.owner_id and PROVIDER_AUTHORITY_RE.search(request.owner_id):
        findings.append(Finding("error", "approval-decision-refused", "--owner-id must identify a human or owner authority, not SDK, provider, credential, runtime, token, or session-active evidence"))
    if not request.approval_packet_refs:
        findings.append(Finding("error", "approval-decision-refused", "--approval-packet-ref must be supplied at least once"))
    if not request.allowed_scopes:
        findings.append(Finding("error", "approval-decision-refused", "--allowed-scope must be supplied at least once"))
    if not request.forbidden_decisions:
        findings.append(Finding("error", "approval-decision-refused", "--forbidden-decision must be supplied at least once"))
    for rel_path in request.approval_packet_refs:
        packet_bindings.extend(_packet_binding_findings(inventory, rel_path, findings))
    for rel_path in request.approval_packet_refs:
        conflict = _root_relative_path_conflict(rel_path)
        if conflict:
            findings.append(Finding("error", "approval-decision-refused", f"--approval-packet-ref {conflict}", rel_path))
        if not rel_path.startswith(APPROVAL_PACKET_DIR_PREFIX) or not rel_path.endswith(".json"):
            findings.append(Finding("error", "approval-decision-refused", "--approval-packet-ref must point to project/verification/approval-packets/*.json", rel_path))
    for scope in request.allowed_scopes:
        if PROVIDER_AUTHORITY_RE.search(scope):
            findings.append(Finding("error", "approval-decision-refused", "--allowed-scope cannot grant provider, credential, secret, SDK, runtime, token, or session-active authority"))
    if SESSION_AUTHORITY_RE.search(request.decision_intent):
        findings.append(Finding("error", "approval-decision-refused", "--decision-intent cannot use session-active, SDK, runtime, provider, or verifier success as owner approval"))
    if request.decision_id:
        rel_path = _decision_rel_path(request.decision_id)
        if (inventory.root / rel_path).exists():
            findings.append(Finding(severity, "approval-decision-refused", "owner-decision record already exists; choose a new --decision-id", rel_path))
    return findings, tuple(packet_bindings)


def _packet_binding_findings(inventory: Inventory, rel_path: str, findings: list[Finding]) -> tuple[dict[str, object], ...]:
    path = inventory.root / rel_path
    if _root_relative_path_conflict(rel_path):
        return ()
    if not rel_path.startswith(APPROVAL_PACKET_DIR_PREFIX) or not rel_path.endswith(".json"):
        return ()
    if not path.exists():
        findings.append(Finding("error", "approval-decision-refused", "approval packet ref is missing", rel_path))
        return ()
    if path.is_symlink() or not path.is_file():
        findings.append(Finding("error", "approval-decision-refused", "approval packet ref must be a regular file inside the operating root", rel_path))
        return ()
    data = _load_json(path)
    if not isinstance(data, dict):
        findings.append(Finding("error", "approval-decision-refused", "approval packet ref is not a JSON object", rel_path))
        return ()
    if data.get("schema") != APPROVAL_PACKET_SCHEMA or data.get("record_type") != "approval-packet":
        findings.append(Finding("error", "approval-decision-refused", "approval packet ref has an unexpected schema or record_type", rel_path))
        return ()
    status = str(data.get("status") or "")
    if status == "pending" and _packet_is_stale(data):
        findings.append(Finding("error", "approval-decision-refused", "pending approval packet ref is stale or lacks created_at_utc; refresh packet evidence before owner decision", rel_path))
    text = path.read_text(encoding="utf-8")
    if status == "approved":
        findings.append(
            Finding(
                "info",
                "approval-decision-packet-evidence-only",
                "approval packet already has status=approved, but packet status remains evidence only until this separate owner-decision record is explicitly consumed by a later route",
                rel_path,
            )
        )
    return (
        {
            "ref": rel_path,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "status": status,
            "approval_id": data.get("approval_id"),
            "requested_decision": data.get("requested_decision"),
            "gate_class": data.get("gate_class"),
        },
    )


def _packet_is_stale(data: dict[str, object]) -> bool:
    created_at = str(data.get("created_at_utc") or "").strip()
    if not created_at:
        return True
    try:
        created = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - created).days > 30


def _decision_data(request: ApprovalDecisionRequest, packet_bindings: tuple[dict[str, object], ...]) -> dict[str, object]:
    return {
        "schema": APPROVAL_DECISION_SCHEMA,
        "record_type": "approval-decision",
        "decision_id": request.decision_id,
        "owner_id": request.owner_id,
        "decision_intent": request.decision_intent,
        "outcome": request.outcome,
        "approval_packet_bindings": list(packet_bindings),
        "allowed_scopes": list(request.allowed_scopes),
        "forbidden_decisions": list(request.forbidden_decisions),
        "follow_up_routes": list(request.follow_up_routes),
        "owner_attestation": request.owner_attestation,
        "notes": request.notes,
        "created_at_utc": _utc_timestamp(),
        "authority_boundary": (
            "owner decisions are separate MLH-owned records; approval packets, relay transport, session-active work, SDK/provider success, "
            "and credential availability remain evidence only until a later lifecycle route explicitly consumes this owner-decision ref through dry-run/apply"
        ),
        "downstream_consumption": (
            "roadmap, transition, writeback, archive, accepted-work, provider, and credential routes must require an explicit owner-decision ref and "
            "rerun their own validations before any protected movement"
        ),
    }


def _decision_shape_findings(request: ApprovalDecisionRequest, packet_bindings: tuple[dict[str, object], ...]) -> list[Finding]:
    return [
        Finding(
            "info",
            "approval-decision-shape",
            (
                f"outcome={request.outcome}; owner_id={request.owner_id}; packet_bindings={len(packet_bindings)}; "
                f"allowed_scopes={len(request.allowed_scopes)}; forbidden_decisions={len(request.forbidden_decisions)}; "
                "decision record remains append-only owner evidence for later explicit route consumption"
            ),
            _decision_rel_path(request.decision_id),
        )
    ]


def _boundary_findings(code_prefix: str = "approval-decision") -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            (
                "approval-decision records are owner-decision evidence only; they do not directly approve lifecycle transitions, accepted-work, "
                "provider routing, credentials, archive, staging, commit, rollback, release, or external relay delivery"
            ),
            APPROVAL_DECISIONS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-route",
            f"owner decisions live under {APPROVAL_DECISIONS_DIR_REL}/*.json and must bind repo-visible approval-packet refs by hash",
            APPROVAL_DECISIONS_DIR_REL,
        ),
    ]


def _decision_rel_path(decision_id: str) -> str:
    return f"{APPROVAL_DECISIONS_DIR_REL}/{decision_id}.json"


def _decision_json(data: dict[str, object]) -> str:
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
    return root_relative_path_conflict(_normalize_ref(rel_path))


def _normalize_ref(value: str) -> str:
    return str(value or "").replace("\\", "/").strip()


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _mentions_provider_authority(data: dict[str, object]) -> bool:
    suspicious = {
        "decision_intent": data.get("decision_intent"),
        "allowed_scopes": data.get("allowed_scopes"),
        "notes": data.get("notes"),
    }
    text = json.dumps(suspicious, sort_keys=True, ensure_ascii=True)
    return bool(PROVIDER_AUTHORITY_RE.search(text))


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
