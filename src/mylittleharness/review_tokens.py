from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .agent_roles import role_manifest
from .claims import work_claim_record_hashes
from .inventory import Inventory
from .models import Finding
from .root_boundary import source_path_boundary_violation
from .routes import route_manifest


REVIEW_TOKEN_SCHEMA = "mylittleharness.review-token.v1"
TOKEN_PREFIX = "rt-"
HEX_RE = re.compile(r"^[a-fA-F0-9]{8,128}$")
REF_HASH_WARNING_CODES = {"work-claim-ref-hash", "evidence-ref-hash", "human-gate-ref-hash"}


@dataclass(frozen=True)
class ReviewTokenRequest:
    operation_id: str
    routes: tuple[str, ...]
    claim_refs: tuple[str, ...]
    claim_hashes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    evidence_hashes: tuple[str, ...]
    patch_hashes: tuple[str, ...]
    verifier_outputs: tuple[str, ...]
    human_gate_refs: tuple[str, ...]
    human_gate_hashes: tuple[str, ...]
    expected_token: str


def make_review_token_request(args: object) -> ReviewTokenRequest:
    return ReviewTokenRequest(
        operation_id=str(getattr(args, "operation_id", "") or "").strip(),
        routes=_tuple_values(getattr(args, "routes", ()), path_like=False),
        claim_refs=_tuple_values(getattr(args, "claim_refs", ())),
        claim_hashes=_tuple_values(getattr(args, "claim_hashes", ()), path_like=False),
        evidence_refs=_tuple_values(getattr(args, "evidence_refs", ())),
        evidence_hashes=_tuple_values(getattr(args, "evidence_hashes", ()), path_like=False),
        patch_hashes=_tuple_values(getattr(args, "patch_hashes", ()), path_like=False),
        verifier_outputs=_tuple_values(getattr(args, "verifier_outputs", ()), path_like=False),
        human_gate_refs=_tuple_values(getattr(args, "human_gate_refs", ())),
        human_gate_hashes=_tuple_values(getattr(args, "human_gate_hashes", ()), path_like=False),
        expected_token=str(getattr(args, "expected_token", "") or "").strip(),
    )


def review_token_findings(inventory: Inventory, request: ReviewTokenRequest) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "review-token-read-only", "review token computed from current repo-visible inputs without writing files"),
        Finding("info", "review-token-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    input_findings = _request_findings(inventory, request)
    findings.extend(input_findings)
    if any(finding.severity == "error" for finding in input_findings):
        findings.append(Finding("info", "review-token-validation-posture", "review token refused before token trust; fix input fields and recompute"))
        findings.extend(_boundary_findings())
        return findings

    payload, payload_findings = review_token_payload(inventory, request)
    degraded_ref_findings = [
        finding
        for finding in payload_findings
        if finding.severity == "warn" and finding.code in REF_HASH_WARNING_CODES
    ]
    if degraded_ref_findings:
        findings.extend(payload_findings)
        findings.append(
            Finding(
                "error",
                "review-token-refused",
                (
                    "ref inputs must resolve to readable repo-visible files before token trust; "
                    "fix missing/unreadable refs or supply explicit reviewed --claim-hash, --evidence-hash, or --human-gate-hash inputs"
                ),
            )
        )
        findings.append(Finding("info", "review-token-validation-posture", "review token refused before token trust; no review token was emitted"))
        findings.extend(_boundary_findings())
        return findings
    token = review_token_from_payload(payload)
    findings.extend(payload_findings)
    findings.extend(_payload_digest_findings(payload))
    findings.append(Finding("info", "review-token-computed", f"review token: {token}"))
    if request.expected_token:
        if request.expected_token == token:
            findings.append(Finding("info", "review-token-match", f"expected token matches current repo-visible inputs: {token}"))
        else:
            findings.append(
                Finding(
                    "error",
                    "review-token-mismatch",
                    (
                        "--expected-token does not match current repo-visible inputs; "
                        f"expected={request.expected_token}; current={token}; refuse fan-in/apply until the token is refreshed"
                    ),
                )
            )
    findings.extend(_boundary_findings())
    return findings


def review_token_payload(inventory: Inventory, request: ReviewTokenRequest) -> tuple[dict[str, object], list[Finding]]:
    findings: list[Finding] = []
    claim_ref_hashes, claim_findings = work_claim_record_hashes(inventory.root, request.claim_refs)
    evidence_ref_hashes, evidence_findings = _ref_hashes(inventory.root, request.evidence_refs, "evidence-ref-hash")
    human_gate_ref_hashes, human_gate_findings = _ref_hashes(inventory.root, request.human_gate_refs, "human-gate-ref-hash")
    findings.extend(claim_findings)
    findings.extend(evidence_findings)
    findings.extend(human_gate_findings)
    active_plan_ref, active_plan_hash = _active_plan_hash(inventory)
    payload = {
        "schema": REVIEW_TOKEN_SCHEMA,
        "operation_id": request.operation_id,
        "routes": list(request.routes),
        "route_manifest_hash": _json_hash(route_manifest()),
        "role_manifest_hash": _json_hash(role_manifest()),
        "active_plan_ref": active_plan_ref,
        "active_plan_hash": active_plan_hash,
        "claim_inputs": sorted([*claim_ref_hashes, *request.claim_hashes]),
        "evidence_inputs": sorted([*evidence_ref_hashes, *request.evidence_hashes]),
        "patch_hashes": sorted(request.patch_hashes),
        "verifier_output_hashes": sorted(_raw_value_hashes(request.verifier_outputs, "verifier-output")),
        "human_gate_inputs": sorted([*human_gate_ref_hashes, *request.human_gate_hashes]),
        "boundary": "review tokens bind fan-in evidence only; matching tokens cannot approve lifecycle, archive, Git, or release without an explicit apply rail",
    }
    return payload, findings


def review_token_from_payload(payload: dict[str, object]) -> str:
    return TOKEN_PREFIX + _json_hash(payload)[:24]


def _request_findings(inventory: Inventory, request: ReviewTokenRequest) -> list[Finding]:
    findings: list[Finding] = []
    if not request.operation_id:
        findings.append(Finding("error", "review-token-refused", "--operation-id is required"))
    if not request.routes:
        findings.append(Finding("error", "review-token-refused", "--route must be supplied at least once"))
    if not (request.claim_refs or request.claim_hashes or request.evidence_refs or request.evidence_hashes or request.patch_hashes or request.verifier_outputs or request.human_gate_refs or request.human_gate_hashes):
        findings.append(
            Finding(
                "error",
                "review-token-refused",
                "at least one claim, evidence, patch, verifier, or human-gate input must be supplied",
            )
        )
    for field, values in (
        ("--claim-ref", request.claim_refs),
        ("--evidence-ref", request.evidence_refs),
        ("--human-gate-ref", request.human_gate_refs),
    ):
        for rel_path in values:
            conflict = _root_relative_path_conflict(rel_path)
            if conflict:
                findings.append(Finding("error", "review-token-refused", f"{field} {conflict}", rel_path))
    for field, values in (
        ("--claim-hash", request.claim_hashes),
        ("--evidence-hash", request.evidence_hashes),
        ("--patch-hash", request.patch_hashes),
        ("--human-gate-hash", request.human_gate_hashes),
    ):
        for digest in values:
            if not HEX_RE.match(digest):
                findings.append(Finding("error", "review-token-refused", f"{field} must be a hex digest-like value"))
    return findings


def _payload_digest_findings(payload: dict[str, object]) -> list[Finding]:
    return [
        Finding("info", "review-token-input-digest", f"route_manifest_hash={payload['route_manifest_hash']}; role_manifest_hash={payload['role_manifest_hash']}"),
        Finding("info", "review-token-input-digest", f"active_plan_ref={payload['active_plan_ref']}; active_plan_hash={payload['active_plan_hash']}"),
        Finding(
            "info",
            "review-token-input-digest",
            (
                f"claim_inputs={len(payload['claim_inputs'])}; evidence_inputs={len(payload['evidence_inputs'])}; "
                f"patch_hashes={len(payload['patch_hashes'])}; verifier_output_hashes={len(payload['verifier_output_hashes'])}; "
                f"human_gate_inputs={len(payload['human_gate_inputs'])}"
            ),
        ),
    ]


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "review-token-boundary",
            "review tokens are deterministic fan-in guards; they do not write files, approve lifecycle transitions, archive, roadmap status, staging, commit, rollback, or release",
        ),
        Finding(
            "info",
            "review-token-refresh",
            "when any bound route, role manifest, claim, evidence, patch, verifier, human-gate, or active-plan input drifts, recompute and review a new token before apply/fan-in",
        ),
    ]


def _active_plan_hash(inventory: Inventory) -> tuple[str, str]:
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    plan_status = str(state_data.get("plan_status") or "")
    state_active_plan = str(state_data.get("active_plan") or "")
    if not state_active_plan and plan_status != "active":
        return "<inactive>", "not-active"

    active_plan = state_active_plan or str(inventory.manifest.get("memory", {}).get("plan_file", "project/implementation-plan.md"))
    surface = inventory.surface_by_rel.get(active_plan.replace("\\", "/")) or inventory.active_plan_surface
    if not surface or not surface.exists:
        return active_plan, "missing"
    return surface.rel_path, hashlib.sha256(surface.content.encode("utf-8")).hexdigest()


def _ref_hashes(root: Path, refs: tuple[str, ...], code: str) -> tuple[list[str], list[Finding]]:
    hashes: list[str] = []
    findings: list[Finding] = []
    for ref in refs:
        normalized = _normalize_ref(ref)
        conflict = _root_relative_path_conflict(normalized)
        if conflict:
            hashes.append(f"{ref} invalid-path")
            findings.append(Finding("warn", code, f"{ref} was recorded as invalid-path: {conflict}", ref))
            continue
        path = root / normalized
        boundary_violation = source_path_boundary_violation(root, path, label="review token ref")
        if boundary_violation is not None:
            hashes.append(f"{normalized} invalid-path")
            findings.append(Finding("warn", code, boundary_violation.message, normalized))
            continue
        if not path.exists():
            hashes.append(f"{normalized} missing")
            findings.append(Finding("warn", code, f"{normalized} is missing", normalized))
            continue
        if not path.is_file() or path.is_symlink():
            hashes.append(f"{normalized} invalid-path")
            findings.append(Finding("warn", code, f"{normalized} is not a regular file", normalized))
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            hashes.append(f"{normalized} unreadable")
            findings.append(Finding("warn", code, f"{normalized} could not be read for hashing: {exc}", normalized))
            continue
        hashes.append(f"{normalized} sha256={digest}")
        findings.append(Finding("info", code, f"{normalized} sha256={digest[:12]}", normalized))
    return hashes, findings


def _raw_value_hashes(values: tuple[str, ...], prefix: str) -> tuple[str, ...]:
    hashes: list[str] = []
    for value in values:
        hashes.append(f"{prefix} sha256={hashlib.sha256(value.encode('utf-8')).hexdigest()}")
    return tuple(hashes)


def _json_hash(value: object) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
