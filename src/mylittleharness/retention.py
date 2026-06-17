from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .atomic_files import AtomicFileDelete, AtomicFileWrite, FileTransactionError, apply_file_transaction
from .models import Finding
from .parsing import parse_frontmatter
from .reporting import RouteWriteEvidence, route_write_findings
from .root_boundary import absolute_path


RETENTION_RECEIPTS_DIR_REL = "project/verification/retention-receipts"
RETENTION_RECEIPT_SCHEMA = "mylittleharness.retention-receipt.v1"
RETENTION_TOMBSTONE_SCHEMA = "mylittleharness.retention-tombstone.v1"
AGENT_RUNS_DIR_REL = "project/verification/agent-runs"
AGENT_RUN_RECORD_PREFIX = f"{AGENT_RUNS_DIR_REL}/"
AGENT_RUN_RETIREMENT_SUMMARY_REL = "project/verification/agent-run-retirement-summary.md"
GENERATED_LOCAL_PREFIXES = (".mylittleharness/generated/", ".mylittleharness/runtime/")
RETENTION_ACTIONS = ("scan", "retire", "tombstone", "purge")
RETENTION_POLICIES = ("exact-paths", "agent-runs-obsolete")
RETENTION_MUTATING_ACTIONS = ("retire", "tombstone", "purge")
ACTIVE_REFERENCE_PATHS = {
    "project/project-state.md",
    "project/implementation-plan.md",
    "project/roadmap.md",
}
ACTIVE_REFERENCE_PREFIXES = (
    "project/verification/work-claims/",
    "project/verification/handoffs/",
    "project/verification/approval-packets/",
    ".mylittleharness/runtime/",
)
SKIP_SCAN_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
SKIP_SCAN_PREFIXES = (
    ".mylittleharness/generated/",
    ".mylittleharness/runtime/",
)
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".rst",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
RECORD_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class RetentionRequest:
    action: str
    paths: tuple[str, ...]
    policy: str
    reason: str
    dry_run: bool
    apply: bool
    receipt_id: str


@dataclass(frozen=True)
class ReferenceHit:
    rel_path: str
    line: int
    current: bool


@dataclass(frozen=True)
class RetentionCandidate:
    rel_path: str
    exists: bool
    is_file: bool
    is_dir: bool
    git_status: str
    classification: str
    recommended_action: str
    inbound_refs: tuple[ReferenceHit, ...]
    warning_delta: str
    risks: tuple[str, ...]
    error: str = ""


@dataclass(frozen=True)
class RetentionPlan:
    request: RetentionRequest
    candidates: tuple[RetentionCandidate, ...]
    receipt_rel: str
    receipt_text: str
    writes: tuple[RouteWriteEvidence, ...]
    operations: tuple[AtomicFileWrite | AtomicFileDelete, ...]


def make_retention_request(args: object) -> RetentionRequest:
    action = str(getattr(args, "retention_action", "") or "").strip()
    policy = str(getattr(args, "policy", "exact-paths") or "exact-paths").strip()
    paths = tuple(str(path or "").strip() for path in tuple(getattr(args, "paths", ()) or ()) if str(path or "").strip())
    reason = str(getattr(args, "reason", "") or "").strip()
    receipt_id = str(getattr(args, "receipt_id", "") or "").strip()
    return RetentionRequest(
        action=action,
        paths=paths,
        policy=policy,
        reason=reason,
        dry_run=bool(getattr(args, "dry_run", False)),
        apply=bool(getattr(args, "apply", False)),
        receipt_id=receipt_id,
    )


def retention_scan_sections(inventory: object, request: RetentionRequest) -> list[tuple[str, list[Finding]]]:
    candidates, request_findings = _retention_candidates(inventory, request)
    return [
        ("Retention Candidates", [*_request_boundary_findings(inventory, request), *request_findings, *_candidate_findings(candidates)]),
        ("Reference Graph", _reference_graph_findings(candidates)),
        ("Git Posture", _git_posture_findings(candidates)),
        ("Boundary", _retention_boundary_findings(request, scan=True)),
    ]


def retention_dry_run_findings(inventory: object, request: RetentionRequest) -> list[Finding]:
    plan, findings = _retention_plan(inventory, request)
    if plan is None:
        return findings
    return [
        *findings,
        *_candidate_findings(plan.candidates),
        *_reference_graph_findings(plan.candidates),
        *_git_posture_findings(plan.candidates),
        *route_write_findings("retention-route-write", plan.writes, apply=False),
        Finding(
            "info",
            "retention-dry-run",
            f"retention {request.action} dry-run reviewed {len(plan.candidates)} candidate(s) and would write receipt {plan.receipt_rel}",
            plan.receipt_rel,
        ),
        *_retention_boundary_findings(request, scan=False),
    ]


def retention_apply_findings(inventory: object, request: RetentionRequest) -> list[Finding]:
    plan, findings = _retention_plan(inventory, request)
    if plan is None:
        return findings
    if any(finding.severity == "error" for finding in findings):
        return [
            *findings,
            *_candidate_findings(plan.candidates),
            *_reference_graph_findings(plan.candidates),
            *_git_posture_findings(plan.candidates),
            *route_write_findings("retention-route-write", plan.writes, apply=False),
            *_retention_boundary_findings(request, scan=False),
        ]
    try:
        cleanup_warnings = apply_file_transaction(plan.operations, root=_inventory_root(inventory))
    except FileTransactionError as exc:
        return [
            *findings,
            Finding("error", "retention-apply-failed", f"retention file transaction failed: {exc}", plan.receipt_rel),
            *_retention_boundary_findings(request, scan=False),
        ]
    cleanup_findings = [
        Finding("warn", "retention-apply-cleanup", warning, plan.receipt_rel)
        for warning in cleanup_warnings
    ]
    return [
        *findings,
        *_candidate_findings(plan.candidates),
        *_reference_graph_findings(plan.candidates),
        *_git_posture_findings(plan.candidates),
        *route_write_findings("retention-route-write", plan.writes, apply=True),
        Finding(
            "info",
            "retention-applied",
            f"retention {request.action} apply wrote reviewed receipt {plan.receipt_rel} for {len(plan.candidates)} candidate(s)",
            plan.receipt_rel,
        ),
        *cleanup_findings,
        *_retention_boundary_findings(request, scan=False),
    ]


def retention_receipt_findings(inventory: object, code_prefix: str = "retention") -> list[Finding]:
    root = _inventory_root(inventory)
    if str(getattr(inventory, "root_kind", "") or "") != "live_operating_root":
        return [
            Finding(
                "info",
                f"{code_prefix}-receipt",
                "retention receipt scan is live-root only; product fixtures and archive roots remain non-authority context",
                _inventory_state_source(inventory),
            )
        ]
    receipt_dir = root / RETENTION_RECEIPTS_DIR_REL
    if not receipt_dir.exists():
        return [
            Finding(
                "info",
                f"{code_prefix}-receipt",
                f"no retention receipts found at {RETENTION_RECEIPTS_DIR_REL}/*.json; receipts are optional until obsolete evidence is retired, tombstoned, or purged",
            )
        ]
    findings: list[Finding] = []
    for path in sorted(receipt_dir.glob("*.json")):
        rel_path = _to_rel_path(root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code_prefix}-receipt-malformed", "retention receipt path is not a regular file", rel_path))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", f"{code_prefix}-receipt-malformed", f"retention receipt could not be read as JSON: {exc}", rel_path))
            continue
        findings.extend(_retention_receipt_data_findings(rel_path, data, code_prefix))
    findings.append(
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "retention receipts are repo-visible cleanup evidence only; they cannot approve closeout, archive, Git, release, provider routing, or target-repo acceptance",
            RETENTION_RECEIPTS_DIR_REL,
        )
    )
    return findings


def _retention_plan(inventory: object, request: RetentionRequest) -> tuple[RetentionPlan | None, list[Finding]]:
    candidates, findings = _retention_candidates(inventory, request)
    findings = [*_request_boundary_findings(inventory, request), *findings]
    if request.action not in RETENTION_MUTATING_ACTIONS:
        findings.append(Finding("error", "retention-refused", f"retention action requires one of {', '.join(RETENTION_MUTATING_ACTIONS)}", None))
        return None, findings
    if request.policy not in RETENTION_POLICIES:
        findings.append(Finding("error", "retention-refused", f"retention policy is not supported: {request.policy}", None))
    if not request.reason:
        findings.append(Finding("error", "retention-refused", "retention mutating actions require --reason", None))
    if not candidates:
        findings.append(Finding("error", "retention-refused", "retention route needs at least one exact --path target", None))
        return None, findings

    action_errors = _action_refusal_findings(request, candidates)
    findings.extend(action_errors)
    plan = _build_plan(inventory, request, candidates)
    return plan, findings


def _retention_candidates(inventory: object, request: RetentionRequest) -> tuple[tuple[RetentionCandidate, ...], list[Finding]]:
    root = _inventory_root(inventory)
    findings: list[Finding] = []
    if str(getattr(inventory, "root_kind", "") or "") != "live_operating_root":
        findings.append(
            Finding(
                "error",
                "retention-refused",
                "retention is live-operating-root only; product fixtures and archive roots cannot mutate evidence retention state",
                _inventory_state_source(inventory),
            )
        )
        return (), findings
    if request.action not in RETENTION_ACTIONS:
        findings.append(Finding("error", "retention-refused", f"unknown retention action: {request.action}", None))
        return (), findings
    if not request.paths:
        findings.append(Finding("error", "retention-refused", "retention requires at least one exact --path", None))
        return (), findings

    rel_paths: list[str] = []
    for raw_path in request.paths:
        normalized, conflict = _normalize_request_path(raw_path)
        if conflict:
            findings.append(Finding("error", "retention-refused", f"retention path {conflict}: {raw_path}", raw_path))
            continue
        rel_paths.extend(_expand_retention_path(root, normalized))
    rel_paths = sorted(dict.fromkeys(rel_paths))
    all_refs = _reference_hits_by_target(root, rel_paths)
    return tuple(_candidate_for(root, rel_path, request, tuple(all_refs.get(rel_path, ()))) for rel_path in rel_paths), findings


def _candidate_for(root: Path, rel_path: str, request: RetentionRequest, inbound_refs: tuple[ReferenceHit, ...]) -> RetentionCandidate:
    target = root / rel_path
    exists = target.exists()
    is_file = target.is_file() if exists else False
    is_dir = target.is_dir() if exists else False
    git_status = _git_status(root, rel_path)
    classification = _classification(rel_path, request, inbound_refs, exists, is_file, is_dir)
    recommended_action = _recommended_action(request.action, classification)
    warning_delta = _warning_delta(request.action, rel_path, classification, inbound_refs)
    risks = _candidate_risks(request.action, rel_path, classification, inbound_refs, exists, is_file, is_dir)
    error = ""
    if not exists and classification != "prune-generated-local":
        error = "target path does not exist"
    elif is_dir and request.action != "scan":
        error = "mutating retention actions require exact file paths"
    return RetentionCandidate(
        rel_path=rel_path,
        exists=exists,
        is_file=is_file,
        is_dir=is_dir,
        git_status=git_status,
        classification=classification,
        recommended_action=recommended_action,
        inbound_refs=inbound_refs,
        warning_delta=warning_delta,
        risks=risks,
        error=error,
    )


def _classification(
    rel_path: str,
    request: RetentionRequest,
    inbound_refs: tuple[ReferenceHit, ...],
    exists: bool,
    is_file: bool,
    is_dir: bool,
) -> str:
    lowered = rel_path.casefold().rstrip("/") + ("/" if is_dir else "")
    if any(lowered.startswith(prefix) for prefix in GENERATED_LOCAL_PREFIXES):
        return "prune-generated-local"
    if not exists:
        return "keep-current"
    if any(hit.current for hit in inbound_refs) and request.action == "purge":
        return "tombstone-preserve-reference"
    if any(hit.current for hit in inbound_refs) and request.action == "retire" and not _is_agent_run_record(rel_path):
        return "refuse-active-current"
    if _is_agent_run_record(rel_path) and request.action in {"scan", "retire"}:
        return "retire-from-freshness"
    if request.action == "tombstone":
        return "tombstone-preserve-reference"
    if request.action == "purge" and not inbound_refs:
        return "purge-safe"
    if request.action == "purge":
        return "tombstone-preserve-reference"
    if is_file:
        return "keep-current"
    return "keep-current"


def _recommended_action(action: str, classification: str) -> str:
    if classification == "refuse-active-current":
        return "refuse"
    if classification == "tombstone-preserve-reference" and action == "purge":
        return "tombstone"
    if classification == "prune-generated-local":
        return "purge"
    if classification == "keep-current":
        return "keep"
    return action


def _warning_delta(action: str, rel_path: str, classification: str, inbound_refs: tuple[ReferenceHit, ...]) -> str:
    if action == "retire" and _is_agent_run_record(rel_path):
        return (
            "retire removes this agent-run record from active source-hash freshness/currentness checks through "
            f"{AGENT_RUN_RETIREMENT_SUMMARY_REL}; metadata and malformed source_hash entries remain checked"
        )
    if action == "purge" and inbound_refs:
        return "purge would break inbound references, so the route refuses and recommends tombstone-preserve-reference"
    if action == "tombstone":
        return "tombstone preserves the referenced path while making the retired status explicit"
    if classification == "prune-generated-local":
        return "generated/local cache pruning should not change authoritative lifecycle warnings"
    return "no warning delta is guaranteed; review check output after apply"


def _candidate_risks(
    action: str,
    rel_path: str,
    classification: str,
    inbound_refs: tuple[ReferenceHit, ...],
    exists: bool,
    is_file: bool,
    is_dir: bool,
) -> tuple[str, ...]:
    risks: list[str] = []
    if not exists:
        risks.append("target is missing, so apply cannot prove before-state content")
    if is_dir and action != "scan":
        risks.append("directory target is not accepted for mutating retention; pass exact file paths")
    if inbound_refs:
        risks.append(f"{len(inbound_refs)} inbound reference(s) must remain coherent after cleanup")
    if any(hit.current for hit in inbound_refs):
        risks.append("current/active references are present; destructive purge is refused")
    if action == "purge" and classification != "purge-safe":
        risks.append("purge is not safe for this candidate; use tombstone or retire")
    if action == "retire" and not _is_agent_run_record(rel_path):
        risks.append("retire currently integrates with agent-run freshness policy only")
    if not risks:
        risks.append("no active reference risk detected by exact path scan")
    return tuple(risks)


def _action_refusal_findings(request: RetentionRequest, candidates: tuple[RetentionCandidate, ...]) -> list[Finding]:
    findings: list[Finding] = []
    for candidate in candidates:
        if candidate.error:
            findings.append(Finding("error", "retention-refused", candidate.error, candidate.rel_path))
        if candidate.classification == "refuse-active-current":
            findings.append(
                Finding(
                    "error",
                    "retention-refused-active-current",
                    "retention refuses to mutate active/current referenced evidence; resolve the active reference or use a supported tombstone path",
                    candidate.rel_path,
                )
            )
        if request.action == "purge" and candidate.classification != "purge-safe" and candidate.classification != "prune-generated-local":
            findings.append(
                Finding(
                    "error",
                    "retention-purge-refused",
                    "purge requires no inbound references; run retention tombstone --dry-run for referenced evidence",
                    candidate.rel_path,
                )
            )
        if request.action == "retire" and not _is_agent_run_record(candidate.rel_path):
            findings.append(
                Finding(
                    "error",
                    "retention-retire-refused",
                    f"retire currently updates {AGENT_RUN_RETIREMENT_SUMMARY_REL} for {AGENT_RUN_RECORD_PREFIX}*.md only",
                    candidate.rel_path,
                )
            )
    return findings


def _build_plan(inventory: object, request: RetentionRequest, candidates: tuple[RetentionCandidate, ...]) -> RetentionPlan:
    root = _inventory_root(inventory)
    receipt_id = _receipt_id(request, candidates)
    receipt_rel = f"{RETENTION_RECEIPTS_DIR_REL}/{receipt_id}.json"
    receipt_text = _receipt_text(request, receipt_id, receipt_rel, candidates)
    writes: list[RouteWriteEvidence] = [_write_evidence(root, receipt_rel, receipt_text)]
    operations: list[AtomicFileWrite | AtomicFileDelete] = [_atomic_write(root, receipt_rel, receipt_text)]

    if request.action == "retire":
        summary_text = _retirement_summary_text(root, request, candidates, receipt_rel)
        writes.append(_write_evidence(root, AGENT_RUN_RETIREMENT_SUMMARY_REL, summary_text))
        operations.append(_atomic_write(root, AGENT_RUN_RETIREMENT_SUMMARY_REL, summary_text))
    elif request.action == "tombstone":
        for candidate in candidates:
            tombstone_text = _tombstone_text(request, candidate, receipt_rel)
            writes.append(_write_evidence(root, candidate.rel_path, tombstone_text))
            operations.append(_atomic_write(root, candidate.rel_path, tombstone_text))
    elif request.action == "purge":
        for candidate in candidates:
            writes.append(_write_evidence(root, candidate.rel_path, None))
            operations.append(_atomic_delete(root, candidate.rel_path))

    return RetentionPlan(request, candidates, receipt_rel, receipt_text, tuple(writes), tuple(operations))


def _receipt_text(
    request: RetentionRequest,
    receipt_id: str,
    receipt_rel: str,
    candidates: tuple[RetentionCandidate, ...],
) -> str:
    payload = {
        "schema": RETENTION_RECEIPT_SCHEMA,
        "record_type": "retention-receipt",
        "receipt_id": receipt_id,
        "action": request.action,
        "policy": request.policy,
        "reason": request.reason,
        "created_at_utc": _utc_now(),
        "receipt_ref": receipt_rel,
        "target_paths": [candidate.rel_path for candidate in candidates],
        "retirement_summary": AGENT_RUN_RETIREMENT_SUMMARY_REL if request.action == "retire" else "",
        "non_authority": (
            "repo-visible retention evidence only; cannot approve lifecycle, archive, cleanup beyond listed "
            "paths, Git, release, provider routing, daemon launch, or target-repo acceptance"
        ),
        "candidates": [
            {
                "path": candidate.rel_path,
                "classification": candidate.classification,
                "recommended_action": candidate.recommended_action,
                "git_status": candidate.git_status,
                "exists": candidate.exists,
                "is_file": candidate.is_file,
                "is_dir": candidate.is_dir,
                "inbound_refs": [
                    {"source": hit.rel_path, "line": hit.line, "current": hit.current}
                    for hit in candidate.inbound_refs
                ],
                "expected_warning_delta": candidate.warning_delta,
                "risks": list(candidate.risks),
            }
            for candidate in candidates
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _retirement_summary_text(
    root: Path,
    request: RetentionRequest,
    candidates: tuple[RetentionCandidate, ...],
    receipt_rel: str,
) -> str:
    existing = _read_existing_text(root / AGENT_RUN_RETIREMENT_SUMMARY_REL)
    existing_records = _existing_retired_records(existing)
    retired = sorted({*existing_records, *(candidate.rel_path for candidate in candidates if _is_agent_run_record(candidate.rel_path))})
    return "\n".join(
        [
            "---",
            'title: "Agent Run Retirement Summary"',
            'status: "archived"',
            'route: "verification"',
            'schema: "mylittleharness.agent-run-retirement-summary.v1"',
            "retired_agent_run_records:",
            *[f"  - {_quote_yaml(path)}" for path in retired],
            "retention_receipts:",
            f"  - {_quote_yaml(receipt_rel)}",
            "---",
            "# Agent Run Retirement Summary",
            "",
            "Agent-run records listed here are retired from active source-hash freshness checks.",
            "The records remain repo-visible historical evidence unless a separate tombstone or purge route is applied.",
            "",
            "## Latest Retention Action",
            "",
            f"- `action`: `{request.action}`",
            f"- `policy`: `{request.policy}`",
            f"- `receipt`: `{receipt_rel}`",
            f"- `reason`: `{request.reason}`",
            "",
        ]
    )


def _tombstone_text(request: RetentionRequest, candidate: RetentionCandidate, receipt_rel: str) -> str:
    return "\n".join(
        [
            "---",
            f'schema: "{RETENTION_TOMBSTONE_SCHEMA}"',
            'record_type: "retention-tombstone"',
            f'original_path: "{candidate.rel_path}"',
            f'action: "{request.action}"',
            f'policy: "{request.policy}"',
            f'receipt_ref: "{receipt_rel}"',
            f'reason: "{_escape_yaml_string(request.reason)}"',
            "---",
            "# Retention Tombstone",
            "",
            f"This path was tombstoned by `{receipt_rel}`.",
            "The tombstone preserves inbound references while making the retired status explicit.",
            "",
        ]
    )


def _retention_receipt_data_findings(rel_path: str, data: object, code_prefix: str) -> list[Finding]:
    code = f"{code_prefix}-receipt"
    if not isinstance(data, dict):
        return [Finding("warn", f"{code}-malformed", "retention receipt JSON root must be an object", rel_path)]
    findings: list[Finding] = []
    schema = str(data.get("schema") or "").strip()
    if schema != RETENTION_RECEIPT_SCHEMA:
        findings.append(Finding("warn", f"{code}-malformed", f"retention receipt schema should be {RETENTION_RECEIPT_SCHEMA}: {schema}", rel_path))
    if str(data.get("record_type") or "").strip() != "retention-receipt":
        findings.append(Finding("warn", f"{code}-malformed", "retention receipt record_type should be retention-receipt", rel_path))
    action = str(data.get("action") or "").strip()
    if action not in RETENTION_MUTATING_ACTIONS:
        findings.append(Finding("warn", f"{code}-malformed", f"retention receipt action is unsupported: {action}", rel_path))
    target_paths = data.get("target_paths")
    if not isinstance(target_paths, list) or not target_paths:
        findings.append(Finding("warn", f"{code}-malformed", "retention receipt target_paths must list exact paths", rel_path))
    non_authority = str(data.get("non_authority") or "").casefold()
    if "cannot approve" not in non_authority or "lifecycle" not in non_authority or "git" not in non_authority:
        findings.append(Finding("warn", f"{code}-malformed", "retention receipt non_authority must state it cannot approve lifecycle or Git", rel_path))
    if not findings:
        findings.append(
            Finding(
                "info",
                f"{code}-summary",
                f"retention receipt: action={action}; targets={len(target_paths or [])}; policy={data.get('policy') or '<missing>'}; evidence-only",
                rel_path,
            )
        )
    return findings


def _request_boundary_findings(inventory: object, request: RetentionRequest) -> list[Finding]:
    return [
        Finding(
            "info",
            "retention-root-boundary",
            "retention operates on the live operating root and treats repo-visible files as authority; command output is advisory until apply writes a receipt",
            _inventory_state_source(inventory),
        ),
        Finding(
            "info",
            "retention-request",
            f"action={request.action}; policy={request.policy}; paths={len(request.paths)}; dry_run={request.dry_run}; apply={request.apply}",
        ),
    ]


def _candidate_findings(candidates: tuple[RetentionCandidate, ...]) -> list[Finding]:
    findings: list[Finding] = []
    for candidate in candidates:
        severity = "warn" if candidate.error or candidate.classification in {"refuse-active-current", "tombstone-preserve-reference"} else "info"
        findings.append(
            Finding(
                severity,
                "retention-candidate",
                (
                    f"classification={candidate.classification}; recommended_action={candidate.recommended_action}; "
                    f"exists={candidate.exists}; git_status={candidate.git_status}; inbound_refs={len(candidate.inbound_refs)}; "
                    f"warning_delta={candidate.warning_delta}"
                ),
                candidate.rel_path,
            )
        )
        if candidate.error:
            findings.append(Finding("error", "retention-candidate-error", candidate.error, candidate.rel_path))
        for risk in candidate.risks:
            findings.append(Finding("info", "retention-risk", risk, candidate.rel_path))
    return findings


def _reference_graph_findings(candidates: tuple[RetentionCandidate, ...]) -> list[Finding]:
    findings: list[Finding] = []
    if not candidates:
        return [Finding("info", "retention-reference-graph", "no retention candidates were available for reference graph scan")]
    for candidate in candidates:
        if not candidate.inbound_refs:
            findings.append(Finding("info", "retention-reference-graph", "no inbound exact path references found", candidate.rel_path))
            continue
        for hit in candidate.inbound_refs:
            posture = "current" if hit.current else "historical"
            findings.append(
                Finding(
                    "info",
                    "retention-reference-graph",
                    f"inbound {posture} reference to {candidate.rel_path}",
                    hit.rel_path,
                    hit.line,
                )
            )
    return findings


def _git_posture_findings(candidates: tuple[RetentionCandidate, ...]) -> list[Finding]:
    if not candidates:
        return [Finding("info", "retention-git-posture", "no retention candidates were available for Git posture classification")]
    return [
        Finding(
            "info",
            "retention-git-posture",
            f"{candidate.rel_path}: {candidate.git_status}",
            candidate.rel_path,
        )
        for candidate in candidates
    ]


def _retention_boundary_findings(request: RetentionRequest, *, scan: bool) -> list[Finding]:
    if scan:
        return [
            Finding(
                "info",
                "retention-scan-read-only",
                "retention scan is read-only and cannot approve cleanup, closeout, archive, Git, release, provider routing, or target-repo acceptance",
            )
        ]
    return [
        Finding(
            "info",
            "retention-apply-boundary",
            (
                f"retention {request.action} dry-run/apply receipts are evidence-only; review check output after apply and use explicit local Git savepoints separately"
            ),
        )
    ]


def _reference_hits_by_target(root: Path, targets: Iterable[str]) -> dict[str, tuple[ReferenceHit, ...]]:
    target_set = tuple(sorted(set(targets)))
    refs: dict[str, list[ReferenceHit]] = {target: [] for target in target_set}
    if not target_set:
        return {}
    for path in _text_paths(root):
        rel_path = _to_rel_path(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            normalized_line = line.replace("\\", "/")
            for target in target_set:
                if rel_path == target:
                    continue
                if target in normalized_line:
                    refs[target].append(ReferenceHit(rel_path, line_number, _is_current_reference_source(rel_path)))
    return {target: tuple(hits) for target, hits in refs.items()}


def _text_paths(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        try:
            if path.is_dir():
                continue
            rel = _to_rel_path(root, path)
        except (OSError, RuntimeError, ValueError):
            continue
        parts = set(rel.split("/"))
        if parts & SKIP_SCAN_DIRS:
            continue
        lowered = rel.casefold()
        if any(lowered.startswith(prefix) for prefix in SKIP_SCAN_PREFIXES):
            continue
        if path.suffix.casefold() not in TEXT_SUFFIXES:
            continue
        yield path


def _is_current_reference_source(rel_path: str) -> bool:
    lowered = rel_path.casefold()
    if lowered in ACTIVE_REFERENCE_PATHS:
        return True
    return any(lowered.startswith(prefix) for prefix in ACTIVE_REFERENCE_PREFIXES)


def _expand_retention_path(root: Path, rel_path: str) -> list[str]:
    target = root / rel_path
    if target.exists() and target.is_dir():
        return sorted(_to_rel_path(root, path) for path in target.glob("*.md") if path.is_file())
    return [rel_path]


def _normalize_request_path(raw_path: str) -> tuple[str, str]:
    text = str(raw_path or "").replace("\\", "/").strip()
    if not text:
        return "", "is empty"
    if re.match(r"^[A-Za-z]:/", text) or text.startswith("/"):
        return "", "must be root-relative, not absolute"
    while text.startswith("./"):
        text = text[2:]
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        return "", "must not escape the root"
    if any(any(char in part for char in "*?[]") for part in parts):
        return "", "must be exact and cannot contain wildcard characters"
    return "/".join(parts), ""


def _git_status(root: Path, rel_path: str) -> str:
    tracked = _git_exit_zero(root, ["ls-files", "--error-unmatch", "--", rel_path])
    ignored = _git_exit_zero(root, ["check-ignore", "-q", "--", rel_path])
    status = _git_stdout(root, ["status", "--short", "--ignored", "--", rel_path])
    if tracked:
        return "tracked"
    if ignored:
        return "ignored"
    if status.strip().startswith("??"):
        return "untracked"
    if status.strip().startswith("!!"):
        return "ignored"
    if status.strip():
        return status.strip()
    if not (root / ".git").exists():
        return "not-a-git-worktree"
    return "untracked"


def _git_exit_zero(root: Path, args: list[str]) -> bool:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _git_stdout(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout or ""


def _write_evidence(root: Path, rel_path: str, after_text: str | None) -> RouteWriteEvidence:
    before_text = _read_existing_text(root / rel_path)
    return RouteWriteEvidence(rel_path, before_text, after_text)


def _atomic_write(root: Path, rel_path: str, text: str) -> AtomicFileWrite:
    target = root / rel_path
    sidecar = _sidecar_base(target)
    return AtomicFileWrite(target, sidecar.with_suffix(sidecar.suffix + ".tmp"), text, sidecar.with_suffix(sidecar.suffix + ".bak"))


def _atomic_delete(root: Path, rel_path: str) -> AtomicFileDelete:
    target = root / rel_path
    sidecar = _sidecar_base(target)
    return AtomicFileDelete(target, sidecar.with_suffix(sidecar.suffix + ".bak"))


def _sidecar_base(target: Path) -> Path:
    return target.with_name(f".{target.name}.mylittleharness")


def _read_existing_text(path: Path) -> str | None:
    try:
        if path.exists() and path.is_file() and not path.is_symlink():
            return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return None


def _existing_retired_records(text: str | None) -> tuple[str, ...]:
    if not text:
        return ()
    frontmatter = parse_frontmatter(text)
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return ()
    records = set(_frontmatter_string_list(frontmatter.data.get("retired_agent_run_records")))
    if not records:
        records.update(_intake_payload_retired_records(text))
    return tuple(sorted(records))


def _intake_payload_retired_records(text: str) -> tuple[str, ...]:
    marker_index = text.find("## Intake Payload Frontmatter")
    if marker_index < 0:
        return ()
    fence_index = text.find("```yaml", marker_index)
    if fence_index < 0:
        return ()
    yaml_start = text.find("\n", fence_index)
    if yaml_start < 0:
        return ()
    yaml_end = text.find("```", yaml_start + 1)
    if yaml_end < 0:
        return ()
    payload = parse_frontmatter(f"---\n{text[yaml_start + 1:yaml_end].strip()}\n---\n")
    if payload.errors:
        return ()
    return _frontmatter_string_list(payload.data.get("retired_agent_run_records"))


def _frontmatter_string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _receipt_id(request: RetentionRequest, candidates: tuple[RetentionCandidate, ...]) -> str:
    if request.receipt_id:
        raw = request.receipt_id
    else:
        seed = "-".join(Path(candidate.rel_path).stem for candidate in candidates[:3]) or "retention"
        raw = f"{request.action}-{_utc_now().replace(':', '').replace('-', '').replace('T', '-')}-{seed}"
    clean = RECORD_ID_RE.sub("-", raw).strip(".-").lower()
    return clean or "retention-receipt"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_agent_run_record(rel_path: str) -> bool:
    lowered = rel_path.casefold()
    return lowered.startswith(AGENT_RUN_RECORD_PREFIX.casefold()) and lowered.endswith(".md")


def _inventory_root(inventory: object) -> Path:
    return absolute_path(Path(getattr(inventory, "root")))


def _inventory_state_source(inventory: object) -> str | None:
    state = getattr(inventory, "state", None)
    return getattr(state, "rel_path", None) if state and getattr(state, "exists", False) else None


def _to_rel_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def _quote_yaml(value: object) -> str:
    return f'"{_escape_yaml_string(str(value))}"'


def _escape_yaml_string(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')
