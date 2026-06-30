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


STANDING_DELEGATION_SCHEMA = "mylittleharness.standing-delegation.v1"
STANDING_DELEGATIONS_DIR_REL = "project/decisions/standing-delegations"
STANDING_DELEGATIONS_DIR_SOURCE = f"{STANDING_DELEGATIONS_DIR_REL}/"
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PROVIDER_AUTHORITY_RE = re.compile(r"\b(provider|credential|secret|api[- ]?key|token|sdk|runtime|session[- ]?active)\b", re.IGNORECASE)
SESSION_AUTHORITY_RE = re.compile(r"\b(session[- ]?active|sdk success|runtime success|provider success|verifier success)\b", re.IGNORECASE)
ALLOWED_AUTONOMOUS_ACTIONS = (
    "bounded-slice-selection",
    "plan-opening",
    "scoped-product-edits",
    "verification",
    "evidence-writing",
    "writeback-when-legal",
    "transition-when-legal",
    "archive-when-legal",
    "exact-local-commit",
    "reassessment",
    "continuation",
)
HARD_HUMAN_BOUNDARIES = (
    "push",
    "release",
    "tag",
    "publication",
    "secrets",
    "credentials",
    "provider-routing-approval",
    "destructive-cleanup",
    "policy-changes",
    "scope-expansion",
    "accepting-red-tests",
    "accepting-unverified-risk",
    "deferred-global-control-ui",
)


@dataclass(frozen=True)
class StandingDelegationRequest:
    policy_id: str
    owner_id: str
    delegation_intent: str
    scope_roots: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    expires_at: str
    revocation_posture: str
    owner_attestation: str
    notes: str


def make_standing_delegation_request(args: object) -> StandingDelegationRequest:
    return StandingDelegationRequest(
        policy_id=str(getattr(args, "policy_id", "") or "").strip(),
        owner_id=str(getattr(args, "owner_id", "") or "").strip(),
        delegation_intent=str(getattr(args, "delegation_intent", "") or "").strip(),
        scope_roots=_tuple_values(getattr(args, "scope_roots", ())),
        allowed_actions=_tuple_values(getattr(args, "allowed_actions", ()), path_like=False),
        forbidden_actions=_tuple_values(getattr(args, "forbidden_actions", ()), path_like=False),
        expires_at=str(getattr(args, "expires_at", "") or "").strip(),
        revocation_posture=str(getattr(args, "revocation_posture", "") or "").strip(),
        owner_attestation=str(getattr(args, "owner_attestation", "") or "").strip(),
        notes=str(getattr(args, "notes", "") or "").strip(),
    )


def standing_delegation_dry_run_findings(inventory: Inventory, request: StandingDelegationRequest) -> list[Finding]:
    findings = [
        Finding("info", "standing-delegation-dry-run", "standing-delegation policy proposal only; no files were written"),
        Finding("info", "standing-delegation-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _request_findings(inventory, request, apply=False)
    findings.extend(request_findings)
    if any(finding.severity in {"warn", "error"} for finding in request_findings):
        findings.append(
            Finding(
                "info",
                "standing-delegation-validation-posture",
                "dry-run refused before apply; fix policy identity, owner attestation, scope roots, allowed actions, expiration, and authority boundaries before writing policy evidence",
            )
        )
        findings.extend(_boundary_findings())
        return findings

    data = _policy_data(request)
    text = _policy_json(data)
    rel_path = _policy_rel_path(request.policy_id)
    findings.append(Finding("info", "standing-delegation-target", f"would write standing delegation policy: {rel_path}", rel_path))
    findings.append(
        Finding(
            "info",
            "standing-delegation-route-write",
            (
                f"would create route {rel_path}; before_hash=missing; after_hash={_short_hash(text)}; "
                f"before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; "
                "policy evidence is separate from later lifecycle, Git, provider, and release consumption"
            ),
            rel_path,
        )
    )
    findings.extend(_policy_shape_findings(request))
    findings.extend(_boundary_findings())
    return findings


def standing_delegation_apply_findings(inventory: Inventory, request: StandingDelegationRequest) -> list[Finding]:
    findings = [
        Finding("info", "standing-delegation-apply", "standing-delegation apply started"),
        Finding("info", "standing-delegation-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _request_findings(inventory, request, apply=True)
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "standing-delegation-apply-refused", "standing-delegation apply refused before writing policy evidence"))
        findings.extend(_boundary_findings())
        return findings

    data = _policy_data(request)
    text = _policy_json(data)
    rel_path = _policy_rel_path(request.policy_id)
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
        findings.append(Finding("error", "standing-delegation-refused", f"failed to write standing delegation before apply completed: {exc}", rel_path))
        findings.extend(_boundary_findings())
        return findings

    findings.append(Finding("info", "standing-delegation-written", f"created standing delegation policy: {rel_path}", rel_path))
    findings.append(
        Finding(
            "info",
            "standing-delegation-route-write",
            (
                f"created route {rel_path}; before_hash=missing; after_hash={_short_hash(text)}; "
                f"before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; "
                "policy evidence is separate from later lifecycle, Git, provider, and release consumption"
            ),
            rel_path,
        )
    )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "standing-delegation-backup-cleanup", warning, rel_path))
    findings.extend(_policy_shape_findings(request))
    findings.extend(_boundary_findings())
    return findings


def standing_delegation_status_findings(inventory: Inventory, code_prefix: str = "standing-delegation") -> list[Finding]:
    directory = inventory.root / STANDING_DELEGATIONS_DIR_REL
    if not directory.exists():
        return [
            Finding(
                "info",
                f"{code_prefix}-none",
                "no standing-delegation records found; routine autonomy still requires explicit route-by-route dry-run/apply decisions",
                STANDING_DELEGATIONS_DIR_SOURCE,
            )
        ]
    findings: list[Finding] = []
    for path in sorted(directory.glob("*.json")):
        rel_path = _rel(path, inventory.root)
        data = _load_json(path)
        if not isinstance(data, dict):
            findings.append(Finding("warn", f"{code_prefix}-invalid", "standing-delegation record is not a JSON object", rel_path))
            continue
        if data.get("schema") != STANDING_DELEGATION_SCHEMA or data.get("record_type") != "standing-delegation":
            findings.append(Finding("warn", f"{code_prefix}-invalid", "standing-delegation record has an unexpected schema or record_type", rel_path))
            continue
        allowed_count = len(data.get("allowed_actions") or [])
        boundary_count = len(data.get("hard_human_boundaries") or [])
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-record",
                (
                    f"standing delegation {data.get('policy_id')} allowed_actions={allowed_count}; "
                    f"scope_roots={len(data.get('scope_roots') or [])}; hard_human_boundaries={boundary_count}; "
                    f"expires_at={data.get('expires_at')}; later routes must consume this policy explicitly and rerun their own dry-run/apply guardrails"
                ),
                rel_path,
            )
        )
        if _expires_at_is_past(str(data.get("expires_at") or "")):
            findings.append(Finding("warn", f"{code_prefix}-expired", "standing-delegation record is expired; do not treat it as a current green corridor", rel_path))
        if _mentions_protected_authority(data):
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-authority-confusion",
                    "standing-delegation record appears to grant provider/credential/session authority; treat as suspicious evidence until reviewed",
                    rel_path,
                )
            )
    if not findings:
        findings.append(Finding("info", f"{code_prefix}-none", "no standing-delegation JSON records found", STANDING_DELEGATIONS_DIR_SOURCE))
    return findings


def _request_findings(inventory: Inventory, request: StandingDelegationRequest, *, apply: bool) -> list[Finding]:
    severity = "error" if apply else "warn"
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(Finding(severity, "standing-delegation-refused", f"target root kind is {inventory.root_kind}; standing delegation records require a live operating root"))
    for field, value in (
        ("--policy-id", request.policy_id),
        ("--owner-id", request.owner_id),
        ("--delegation-intent", request.delegation_intent),
        ("--expires-at", request.expires_at),
        ("--owner-attestation", request.owner_attestation),
    ):
        if not value:
            findings.append(Finding("error", "standing-delegation-refused", f"{field} is required"))
    if request.policy_id and not ID_RE.match(request.policy_id):
        findings.append(Finding("error", "standing-delegation-refused", "--policy-id may contain only letters, digits, dot, underscore, or dash"))
    elif request.policy_id and record_id_conflict(request.policy_id):
        findings.append(Finding("error", "standing-delegation-refused", f"--policy-id {record_id_conflict(request.policy_id)}"))
    if request.owner_id and PROVIDER_AUTHORITY_RE.search(request.owner_id):
        findings.append(Finding("error", "standing-delegation-refused", "--owner-id must identify a human or owner authority, not SDK, provider, credential, runtime, token, or session-active evidence"))
    if SESSION_AUTHORITY_RE.search(request.delegation_intent) or PROVIDER_AUTHORITY_RE.search(request.delegation_intent):
        findings.append(Finding("error", "standing-delegation-refused", "--delegation-intent cannot use provider, credential, session-active, SDK, runtime, or verifier success as standing owner delegation"))
    if PROVIDER_AUTHORITY_RE.search(request.owner_attestation):
        findings.append(Finding("error", "standing-delegation-refused", "--owner-attestation cannot rely on provider, credential, secret, SDK, runtime, token, or session-active evidence"))
    if not request.scope_roots:
        findings.append(Finding("error", "standing-delegation-refused", "--scope-root must be supplied at least once"))
    for scope in request.scope_roots:
        conflict = root_relative_path_conflict(scope, allow_current_dir=True)
        if conflict:
            findings.append(Finding("error", "standing-delegation-refused", f"--scope-root {conflict}", scope))
        if PROVIDER_AUTHORITY_RE.search(scope):
            findings.append(Finding("error", "standing-delegation-refused", "--scope-root cannot name provider, credential, secret, SDK, runtime, token, or session-active authority", scope))
    if not request.allowed_actions:
        findings.append(Finding("error", "standing-delegation-refused", "--allowed-action must be supplied at least once"))
    allowed_set = set(ALLOWED_AUTONOMOUS_ACTIONS)
    hard_boundary_set = set(HARD_HUMAN_BOUNDARIES)
    for action in request.allowed_actions:
        if action in hard_boundary_set:
            findings.append(Finding("error", "standing-delegation-refused", f"--allowed-action cannot include hard human boundary: {action}"))
        elif action not in allowed_set:
            findings.append(Finding("error", "standing-delegation-refused", f"--allowed-action must be one of {', '.join(ALLOWED_AUTONOMOUS_ACTIONS)}; got {action!r}"))
    expires_at = _parse_expires_at(request.expires_at)
    if request.expires_at and expires_at is None:
        findings.append(Finding("error", "standing-delegation-refused", "--expires-at must use UTC format YYYY-MM-DDTHH:MM:SSZ"))
    elif expires_at is not None and expires_at <= datetime.now(timezone.utc):
        findings.append(Finding("error", "standing-delegation-refused", "--expires-at must be in the future"))
    if request.policy_id:
        rel_path = _policy_rel_path(request.policy_id)
        if (inventory.root / rel_path).exists():
            findings.append(Finding(severity, "standing-delegation-refused", "standing-delegation record already exists; choose a new --policy-id", rel_path))
    return findings


def _policy_data(request: StandingDelegationRequest) -> dict[str, object]:
    forbidden = _dedupe((*HARD_HUMAN_BOUNDARIES, *request.forbidden_actions))
    return {
        "schema": STANDING_DELEGATION_SCHEMA,
        "record_type": "standing-delegation",
        "policy_id": request.policy_id,
        "owner_id": request.owner_id,
        "delegation_intent": request.delegation_intent,
        "scope_roots": list(request.scope_roots),
        "allowed_actions": list(request.allowed_actions),
        "hard_human_boundaries": list(HARD_HUMAN_BOUNDARIES),
        "forbidden_actions": list(forbidden),
        "expires_at": request.expires_at,
        "revocation_posture": request.revocation_posture
        or "policy expires at expires_at; owner may supersede or revoke by recording a later explicit policy route",
        "owner_attestation": request.owner_attestation,
        "notes": request.notes,
        "created_at_utc": _utc_timestamp(),
        "authority_boundary": (
            "standing-delegation records define a bounded green corridor for routine autonomous work only when later routes explicitly consume "
            "the policy through their own dry-run/apply guardrails; they do not approve protected owner decisions by themselves"
        ),
        "non_authority": (
            "does not approve push, release, tag, publication, secrets, credentials, provider routing, destructive cleanup, policy changes, "
            "scope expansion, accepting red tests, accepting unverified risk, deferred global control UI, staging, commit, archive, or lifecycle movement by itself"
        ),
        "downstream_consumption": (
            "later MLH or target-workflow routes must check policy id, scope_roots, allowed_actions, hard_human_boundaries, expiration, and revocation posture "
            "before using this record as input evidence; each protected action keeps its own owner gate"
        ),
    }


def _policy_shape_findings(request: StandingDelegationRequest) -> list[Finding]:
    return [
        Finding(
            "info",
            "standing-delegation-shape",
            (
                f"policy_id={request.policy_id}; owner_id={request.owner_id}; scope_roots={len(request.scope_roots)}; "
                f"allowed_actions={len(request.allowed_actions)}; hard_human_boundaries={len(HARD_HUMAN_BOUNDARIES)}; "
                "standing delegation remains append-only policy evidence for later explicit route consumption"
            ),
            _policy_rel_path(request.policy_id),
        )
    ]


def _boundary_findings(code_prefix: str = "standing-delegation") -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            (
                "standing-delegation records define a bounded autonomy green corridor only; they do not directly approve lifecycle transitions, "
                "accepted-work, provider routing, credentials, archive, staging, commit, push, tag, release, publication, destructive cleanup, policy changes, "
                "scope expansion, red-test acceptance, unverified risk acceptance, or deferred global control UI"
            ),
            STANDING_DELEGATIONS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-route",
            f"standing delegations live under {STANDING_DELEGATIONS_DIR_REL}/*.json and must be consumed explicitly by later routes",
            STANDING_DELEGATIONS_DIR_REL,
        ),
    ]


def _policy_rel_path(policy_id: str) -> str:
    return f"{STANDING_DELEGATIONS_DIR_REL}/{policy_id}.json"


def _policy_json(data: dict[str, object]) -> str:
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


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _normalize_ref(value: str) -> str:
    return str(value or "").replace("\\", "/").strip()


def _parse_expires_at(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _expires_at_is_past(value: str) -> bool:
    parsed = _parse_expires_at(value)
    return parsed is None or parsed <= datetime.now(timezone.utc)


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _mentions_protected_authority(data: dict[str, object]) -> bool:
    suspicious = {
        "delegation_intent": data.get("delegation_intent"),
        "scope_roots": data.get("scope_roots"),
        "allowed_actions": data.get("allowed_actions"),
        "owner_attestation": data.get("owner_attestation"),
    }
    text = json.dumps(suspicious, sort_keys=True, ensure_ascii=True)
    return bool(PROVIDER_AUTHORITY_RE.search(text))


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
