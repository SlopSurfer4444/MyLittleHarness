from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .claims import (
    WORK_CLAIMS_DIR_REL,
    fan_in_evidence_gate,
    work_claim_completion_policy_payload,
    work_claim_status_findings,
)
from .evidence import agent_run_record_findings
from .handoff import HANDOFF_PACKETS_DIR_REL, dispatcher_launch_status_findings, handoff_packet_status_findings
from .inventory import Inventory
from .lifecycle_focus import session_active_work_findings
from .models import Finding
from .roadmap import roadmap_items_for_diagnostics
from .root_boundary import record_id_conflict, root_relative_path_conflict
from .standing_delegations import (
    HARD_HUMAN_BOUNDARIES,
    STANDING_DELEGATION_SCHEMA,
    STANDING_DELEGATIONS_DIR_REL,
)
from .vcs import probe_vcs


TASK_SESSION_INSPECT_SCHEMA = "mylittleharness.task-session.inspect.v1"
TASK_SESSION_RECEIPT_SCHEMA = "mylittleharness.task-session.receipt.v1"
TASK_SESSION_FAN_IN_SCHEMA = "mylittleharness.task-session.fan-in.inspect.v1"
TASK_SESSION_CONDUCTOR_SCHEMA = "mylittleharness.task-session.conductor.inspect.v1"
TASK_SESSION_PROVIDER_LAUNCHER_SCHEMA = "mylittleharness.task-session.provider-launcher.v1"
STANDING_DELEGATION_CORRIDOR_ACTIONS = {
    "bounded-slice-selection",
    "scoped-product-edits",
    "verification",
    "evidence-writing",
    "writeback-when-legal",
    "transition-when-legal",
    "archive-when-legal",
    "reassessment",
    "continuation",
}

TASK_SESSIONS_DIR_REL = "project/verification/task-sessions"
SYMPHONY_QUEUE_DIR_REL = "project/symphony/queue"
PROVIDER_LAUNCHER_PROFILE = "conductor_full_dev"
PROVIDER_LAUNCHER_REQUIRED_ENV = ("OPENAI_API_KEY",)
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
TASK_SESSION_BOUNDARY = (
    "task-session inspect is read-only preflight contract data for external runtimes; MLH remains lifecycle "
    "authority, repo-visible MLH files remain truth, and this packet cannot approve fan-in, route proposals, multi-root "
    "execution, provider routing, staging, commit, push, archive, roadmap status, or closeout"
)
TASK_SESSION_RECEIPT_BOUNDARY = (
    "task-session receipt writes one repo-visible route receipt under project/verification/task-sessions; "
    "it records runtime intent and MLH preflight posture, but cannot launch workers, approve fan-in, accept route proposals, "
    "move lifecycle, writeback, archive, stage, commit, push, release, or choose providers"
)
TASK_SESSION_FAN_IN_BOUNDARY = (
    "task-session fan-in inspect is read-only session-graph readiness evidence; it can report ready, blocked, "
    "not-required, or refused from repo-visible receipts, claims, handoffs, agent-runs, dirty-start posture, and source "
    "hashes, but cannot approve lifecycle, writeback, archive, roadmap status, Git, provider routing, worker launch, "
    "route proposals, or multi-root execution"
)
TASK_SESSION_CONDUCTOR_BOUNDARY = (
    "task-session conductor inspect is a read-only coordination packet for a shared living root; workers may append "
    "repo-visible claims, handoffs, agent-run evidence, task-session receipts, and fan-in proposals through explicit "
    "owner routes, but this packet cannot launch workers, choose providers, approve fan-in, writeback, archive, roadmap "
    "status, staging, commit, push, release, or lifecycle movement"
)
TASK_SESSION_PROVIDER_LAUNCHER_BOUNDARY = (
    "task-session provider-launcher inspect reports secret-safe runtime configuration readiness only; it records env var "
    "names and boolean presence, but cannot read or persist secret values, call a provider, select a provider, launch "
    "workers, create queue items, approve fan-in, move lifecycle, writeback, archive, stage, commit, push, or release"
)
TASK_SESSION_RECEIPT_FORBIDDEN_ROUTES = {
    "attach",
    "cleanup",
    "detach",
    "git",
    "hooks",
    "incubate",
    "init",
    "memory-hygiene",
    "meta-feedback",
    "migrate",
    "plan",
    "plan-cancel",
    "provider",
    "repair",
    "roadmap",
    "transition",
    "writeback",
}
TASK_SESSION_RECEIPT_FORBIDDEN_WRITE_PATHS = {
    ".git",
    ".mylittleharness/generated",
    ".mylittleharness/runtime",
    "project/archive",
    "project/implementation-plan.md",
    "project/project-state.md",
    "project/roadmap.md",
}
TASK_SESSION_RECEIPT_PATH_FIELDS = (
    ("--read-context", "read_context"),
    ("--write-scope", "write_scope"),
    ("--evidence-ref", "evidence_refs"),
    ("--claim-ref", "claim_refs"),
    ("--handoff-ref", "handoff_refs"),
    ("--route-proposal-ref", "route_proposal_refs"),
)


@dataclass(frozen=True)
class TaskSessionReceiptRequest:
    session_id: str
    task_id: str
    objective: str
    execution_slice: str
    runtime_owner: str
    runtime_backend: str
    read_context: tuple[str, ...]
    write_scope: tuple[str, ...]
    allowed_routes: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    required_outputs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    claim_refs: tuple[str, ...]
    handoff_refs: tuple[str, ...]
    route_proposal_refs: tuple[str, ...]
    provider_refs: tuple[str, ...]


def register_task_session_parser(parser: argparse.ArgumentParser) -> None:
    subparsers = _subparsers_action(parser)
    if subparsers is None or "task-session" in subparsers.choices:
        return
    task_session = subparsers.add_parser(
        "task-session",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: inspect the task/session preflight contract or write a bounded runtime receipt.",
    )
    mode = task_session.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inspect", action="store_true", help="Inspect the task/session contract without writing files.")
    mode.add_argument("--dry-run", action="store_true", help="Preview a task/session receipt without writing files.")
    mode.add_argument("--apply", action="store_true", help="Write one repo-visible task/session receipt.")
    task_session.add_argument("--json", action="store_true", help="Emit the task/session contract as structured JSON.")
    task_session.add_argument("--fan-in", action="store_true", help="Inspect task/session fan-in readiness without writing files.")
    task_session.add_argument("--conductor", action="store_true", help="Inspect the shared conductor coordination packet without writing files.")
    task_session.add_argument("--provider-launcher", action="store_true", help="Include secret-safe provider runtime launcher readiness in conductor inspect.")
    task_session.add_argument("--session-id", default="", help="Stable task/session receipt id.")
    task_session.add_argument("--task-id", default="", help="Optional external task id.")
    task_session.add_argument("--objective", default="", help="Human-readable task objective recorded in the receipt.")
    task_session.add_argument("--execution-slice", default="", help="Execution slice; defaults to the active plan slice when present.")
    task_session.add_argument("--runtime-owner", default="external-runtime", help="Runtime owner recorded in the receipt.")
    task_session.add_argument("--runtime-backend", default="", help="Runtime backend recorded as evidence, not provider authority.")
    task_session.add_argument("--read-context", action="append", default=None, help="Root-relative context file the runtime used.")
    task_session.add_argument("--write-scope", action="append", default=None, help="Root-relative write scope requested for the runtime.")
    task_session.add_argument("--allowed-route", action="append", default=None, help="Runtime route allowed by the operator-level plan.")
    task_session.add_argument("--stop-condition", action="append", default=None, help="Stop condition the runtime must honor.")
    task_session.add_argument("--required-output", action="append", default=None, help="Output or evidence expected from the runtime.")
    task_session.add_argument("--evidence-ref", action="append", default=None, help="Planned or produced root-relative evidence ref.")
    task_session.add_argument("--claim-ref", action="append", default=None, help="Root-relative work-claim ref.")
    task_session.add_argument("--handoff-ref", action="append", default=None, help="Root-relative handoff ref.")
    task_session.add_argument("--route-proposal-ref", action="append", default=None, help="Root-relative route proposal ref.")
    task_session.add_argument("--provider-ref", action="append", default=None, help="Provider/runtime provenance ref; evidence only.")
    subparsers._choices_actions = [action for action in subparsers._choices_actions if action.help != argparse.SUPPRESS]


def make_task_session_receipt_request(args: object) -> TaskSessionReceiptRequest:
    return TaskSessionReceiptRequest(
        session_id=str(getattr(args, "session_id", "") or "").strip(),
        task_id=str(getattr(args, "task_id", "") or "").strip(),
        objective=str(getattr(args, "objective", "") or "").strip(),
        execution_slice=str(getattr(args, "execution_slice", "") or "").strip(),
        runtime_owner=str(getattr(args, "runtime_owner", "") or "").strip() or "external-runtime",
        runtime_backend=str(getattr(args, "runtime_backend", "") or "").strip() or "unspecified",
        read_context=_tuple_values(getattr(args, "read_context", ())),
        write_scope=_tuple_values(getattr(args, "write_scope", ())),
        allowed_routes=_tuple_values(getattr(args, "allowed_route", ()), path_like=False),
        stop_conditions=_tuple_values(getattr(args, "stop_condition", ()), path_like=False),
        required_outputs=_tuple_values(getattr(args, "required_output", ()), path_like=False),
        evidence_refs=_tuple_values(getattr(args, "evidence_ref", ())),
        claim_refs=_tuple_values(getattr(args, "claim_ref", ())),
        handoff_refs=_tuple_values(getattr(args, "handoff_ref", ())),
        route_proposal_refs=_tuple_values(getattr(args, "route_proposal_ref", ())),
        provider_refs=_tuple_values(getattr(args, "provider_ref", ()), path_like=False),
    )


def task_session_receipt_dry_run_findings(inventory: Inventory, request: TaskSessionReceiptRequest) -> list[Finding]:
    findings = [
        Finding("info", "task-session-receipt-dry-run", "task-session receipt proposal only; no files were written"),
        Finding("info", "task-session-receipt-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _receipt_request_findings(inventory, request, apply=False)
    findings.extend(request_findings)
    if any(finding.severity in {"warn", "error"} for finding in request_findings):
        findings.append(Finding("info", "task-session-receipt-validation-posture", "dry-run refused before apply; fix explicit task-session receipt fields before writing receipt evidence"))
        findings.extend(_receipt_boundary_findings())
        return findings

    rel_path = _receipt_rel_path(request.session_id)
    data = _receipt_data(inventory, request)
    text = _receipt_json(data)
    findings.append(Finding("info", "task-session-receipt-target", f"would write task-session receipt: {rel_path}", rel_path))
    findings.append(_receipt_route_write_finding(rel_path, None, data, apply=False))
    findings.extend(_receipt_shape_findings(data))
    findings.extend(_receipt_boundary_findings())
    return findings


def task_session_receipt_apply_findings(inventory: Inventory, request: TaskSessionReceiptRequest) -> list[Finding]:
    findings = [
        Finding("info", "task-session-receipt-apply", "task-session receipt apply started"),
        Finding("info", "task-session-receipt-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _receipt_request_findings(inventory, request, apply=True)
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "task-session-receipt-apply-refused", "task-session receipt apply refused before writing receipt evidence"))
        findings.extend(_receipt_boundary_findings())
        return findings

    rel_path = _receipt_rel_path(request.session_id)
    data = _receipt_data(inventory, request)
    text = _receipt_json(data)
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
        findings.append(Finding("error", "task-session-receipt-refused", f"failed to write task-session receipt before apply completed: {exc}", rel_path))
        findings.extend(_receipt_boundary_findings())
        return findings

    findings.append(Finding("info", "task-session-receipt-written", f"created task-session receipt: {rel_path}", rel_path))
    findings.append(_receipt_route_write_finding(rel_path, None, data, apply=True))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "task-session-receipt-backup-cleanup", warning, rel_path))
    findings.extend(_receipt_shape_findings(data))
    findings.extend(_receipt_boundary_findings())
    return findings


def task_session_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    lifecycle = _lifecycle_findings(inventory)
    topology = _topology_findings(inventory)
    coordination = _coordination_findings(inventory)
    return [
        ("Task Session", _summary_findings(inventory)),
        ("Lifecycle", lifecycle),
        ("Roadmap", _roadmap_findings(inventory)),
        ("Topology", topology),
        ("Authority", _authority_findings()),
        ("Coordination Evidence", coordination),
        ("Capabilities", _capability_findings()),
        ("Boundary", _boundary_findings()),
    ]


def task_session_payload(inventory: Inventory, sections: list[tuple[str, list[Finding]]] | None = None) -> dict[str, object]:
    sections = task_session_sections(inventory) if sections is None else sections
    findings = [finding for _name, section_findings in sections for finding in section_findings]
    coordination_findings = _coordination_raw_findings(inventory)
    return {
        "schema": TASK_SESSION_INSPECT_SCHEMA,
        "root": str(inventory.root),
        "root_kind": inventory.root_kind,
        "read_only": True,
        "source_refs": _source_refs(inventory),
        "session": _session_payload(inventory),
        "lifecycle": _lifecycle_payload(inventory),
        "active_plan": _active_plan_payload(inventory),
        "roadmap": _roadmap_payload(inventory),
        "topology": _topology_payload(inventory),
        "authority": _authority_payload(),
        "coordination": _coordination_payload(coordination_findings),
        "capabilities": _capabilities_payload(),
        "next_safe_command": _next_safe_command_payload(inventory),
        "findings": [finding.to_dict() for finding in findings],
        "sections": [
            {"name": name, "findings": [finding.to_dict() for finding in section_findings]}
            for name, section_findings in sections
        ],
        "authority_boundary": TASK_SESSION_BOUNDARY,
    }


def task_session_fan_in_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    state = _fan_in_state(inventory)
    return [
        ("Task Session Fan-In", _fan_in_summary_findings(inventory, state)),
        ("Evidence Graph", _fan_in_graph_findings(state)),
        ("Task Session Receipts", _fan_in_receipt_findings(state)),
        ("Dirty Start", _fan_in_dirty_start_findings(state)),
        ("Authority", _fan_in_authority_findings()),
        ("Boundary", _fan_in_boundary_findings()),
    ]


def task_session_fan_in_payload(inventory: Inventory, sections: list[tuple[str, list[Finding]]] | None = None) -> dict[str, object]:
    state = _fan_in_state(inventory)
    sections = task_session_fan_in_sections(inventory) if sections is None else sections
    findings = [finding for _name, section_findings in sections for finding in section_findings]
    return {
        "schema": TASK_SESSION_FAN_IN_SCHEMA,
        "root": str(inventory.root),
        "root_kind": inventory.root_kind,
        "read_only": True,
        "source_refs": _source_refs(inventory),
        "session": _session_payload(inventory),
        "lifecycle": _lifecycle_payload(inventory),
        "active_plan": _active_plan_payload(inventory),
        "topology": _topology_payload(inventory),
        "fan_in": _fan_in_payload(state),
        "receipts": state["receipts"],
        "dirty_start": state["dirty_start"],
        "authority": {
            **_authority_payload(),
            "fan_in_approval": False,
            "route_proposal_approval": False,
        },
        "capabilities": {**_capabilities_payload(), "fan_in_inspect": True},
        "approvals": {
            "lifecycle": False,
            "fan_in": False,
            "route_proposal": False,
            "provider_routing": False,
            "git": False,
        },
        "next_safe_command": _fan_in_next_safe_command(state),
        "findings": [finding.to_dict() for finding in findings],
        "sections": [
            {"name": name, "findings": [finding.to_dict() for finding in section_findings]}
            for name, section_findings in sections
        ],
        "authority_boundary": TASK_SESSION_FAN_IN_BOUNDARY,
    }


def task_session_conductor_sections(inventory: Inventory, *, include_provider_launcher: bool = False) -> list[tuple[str, list[Finding]]]:
    state = _conductor_state(inventory)
    sections = [
        ("Conductor", _conductor_summary_findings(state)),
        ("Coordination Roots", _conductor_root_findings(state)),
        ("Living Evidence Routes", _conductor_route_findings(state)),
        ("Evidence Graph", _conductor_graph_findings(state)),
        ("Authority", _conductor_authority_findings()),
        ("Boundary", _conductor_boundary_findings()),
    ]
    if include_provider_launcher:
        sections.insert(4, ("Provider Runtime Launcher", _provider_launcher_findings(inventory, state)))
    return sections


def task_session_conductor_payload(
    inventory: Inventory,
    sections: list[tuple[str, list[Finding]]] | None = None,
    *,
    include_provider_launcher: bool = False,
) -> dict[str, object]:
    state = _conductor_state(inventory)
    sections = task_session_conductor_sections(inventory, include_provider_launcher=include_provider_launcher) if sections is None else sections
    findings = [finding for _name, section_findings in sections for finding in section_findings]
    conductor = _conductor_payload(state)
    payload: dict[str, object] = {
        "schema": TASK_SESSION_CONDUCTOR_SCHEMA,
        "root": str(inventory.root),
        "root_kind": inventory.root_kind,
        "read_only": True,
        "source_refs": _source_refs(inventory),
        "session": _session_payload(inventory),
        "lifecycle": _lifecycle_payload(inventory),
        "active_plan": _active_plan_payload(inventory),
        "topology": _topology_payload(inventory),
        "fan_in": _fan_in_payload(dict(state.get("fan_in") or {})),
        "conductor": conductor,
        "coordination": {
            "evidence_counts": dict(state.get("evidence_counts") or {}),
            "warning_count": len(_string_tuple(state.get("warnings"))),
            "error_count": len(_string_tuple(state.get("errors"))),
        },
        "authority": {
            **_authority_payload(),
            "worker_launch_approval": False,
            "conductor_approval": False,
        },
        "capabilities": {**_capabilities_payload(), "conductor_inspect": True, "worker_launch": False},
        "approvals": {
            "lifecycle": False,
            "fan_in": False,
            "route_proposal": False,
            "provider_routing": False,
            "worker_launch": False,
            "roadmap": False,
            "archive": False,
            "git": False,
        },
        "next_safe_command": _conductor_next_safe_command(state),
        "findings": [finding.to_dict() for finding in findings],
        "sections": [
            {"name": name, "findings": [finding.to_dict() for finding in section_findings]}
            for name, section_findings in sections
        ],
        "authority_boundary": TASK_SESSION_CONDUCTOR_BOUNDARY,
    }
    if include_provider_launcher:
        provider_launcher = _provider_launcher_payload(inventory, state)
        conductor["provider_launcher"] = provider_launcher
        payload["provider_launcher"] = provider_launcher
    return payload


def _fan_in_state(inventory: Inventory) -> dict[str, object]:
    active_plan_data = _active_plan_data(inventory)
    active_plan = _active_plan_payload(inventory)
    session = _session_payload(inventory)
    corridor = _standing_delegation_corridor_payload(inventory)
    corridor_policy_ids = tuple(str(policy_id) for policy_id in _json_list(corridor.get("policy_ids")) if str(policy_id).strip())
    execution_slice = str(active_plan.get("execution_slice") or active_plan.get("primary_roadmap_item") or (corridor_policy_ids[0] if corridor_policy_ids else "")).strip()
    dirty_start = _dirty_start_payload(inventory.root)
    product_diff_proof = {
        "dirty_paths": [
            str(item.get("path") or "")
            for item in _json_list(dirty_start.get("changed_paths"))
            if isinstance(item, dict) and str(item.get("path") or "").strip()
        ],
        "out_of_scope": [],
    }
    gate = fan_in_evidence_gate(inventory.root, active_plan_data, product_diff_proof=product_diff_proof)
    receipts, receipt_findings = _task_session_receipts(inventory.root, execution_slice, str(session.get("session_id") or ""))
    receipt_refs = tuple(str(receipt.get("rel_path") or "") for receipt in receipts if str(receipt.get("rel_path") or "").strip())
    route_proposal_refs = tuple(
        dict.fromkeys(
            str(ref)
            for receipt in receipts
            for ref in _json_list(receipt.get("route_proposal_refs"))
            if str(ref or "").strip()
        )
    )
    missing = list(gate.missing)
    blockers = list(gate.blockers)

    if inventory.root_kind != "live_operating_root":
        status = "refused"
        blockers.append(f"target root kind is {inventory.root_kind}; task-session fan-in inspect requires a live operating root")
    elif not session.get("active_plan_exists") and not corridor.get("active"):
        status = "blocked"
        missing.append("active-plan")
        blockers.append("active plan is missing; fan-in readiness requires repo-visible active-plan metadata")
    elif not session.get("active_plan_exists") and corridor.get("active"):
        status = "not-required"
    elif not gate.activated:
        status = "not-required"
    else:
        if not receipt_refs:
            missing.append("task-session-receipt")
            blockers.append("no matching task-session receipt records found for the active session or execution slice")
        status = "blocked" if missing else "ready"

    return {
        "status": status,
        "gate": gate,
        "activated": gate.activated,
        "reasons": gate.reasons,
        "missing": tuple(dict.fromkeys(missing)),
        "blockers": tuple(dict.fromkeys(blockers)),
        "claim_refs": gate.claim_refs,
        "handoff_refs": gate.handoff_refs,
        "agent_run_refs": gate.agent_run_refs,
        "receipt_refs": receipt_refs,
        "route_proposal_refs": route_proposal_refs,
        "receipts": receipts,
        "receipt_findings": receipt_findings,
        "dirty_start": dirty_start,
        "execution_slice": execution_slice,
        "session_id": str(session.get("session_id") or ""),
        "standing_delegation_corridor": corridor,
        "docs_decision": str(active_plan.get("docs_decision") or ""),
    }


def _conductor_state(inventory: Inventory) -> dict[str, object]:
    session = _session_payload(inventory)
    active_plan = _active_plan_payload(inventory)
    topology = _topology_payload(inventory)
    fan_in_state = _fan_in_state(inventory)
    coordination_findings = _coordination_raw_findings(inventory)
    corridor = _standing_delegation_corridor_payload(inventory)
    corridor_active = bool(corridor.get("active"))
    corridor_policy_ids = tuple(str(policy_id) for policy_id in _json_list(corridor.get("policy_ids")) if str(policy_id).strip())
    corridor_scope_roots = tuple(
        str(root)
        for record in _json_list(corridor.get("records"))
        if isinstance(record, dict)
        for root in _json_list(record.get("scope_roots"))
        if str(root or "").strip()
    )
    errors = tuple(finding.code for finding in coordination_findings if finding.severity == "error")
    warnings = tuple(finding.code for finding in coordination_findings if finding.severity == "warn")
    evidence_counts = _coordination_counts(coordination_findings)
    receipt_refs = _string_tuple(fan_in_state.get("receipt_refs"))
    queue_count = _queue_item_count(inventory.root)
    status = "ready"
    blockers: list[str] = []
    if inventory.root_kind != "live_operating_root":
        status = "refused"
        blockers.append(f"target root kind is {inventory.root_kind}; conductor inspect requires a live operating root")
    elif not session.get("active_plan_exists") and not corridor_active:
        status = "blocked"
        blockers.append("active plan is missing; conductor packet needs a repo-visible active plan before scheduling")
    elif errors:
        status = "blocked"
        blockers.append("coordination evidence has error-level diagnostics; inspect check --focus agents")
    elif str(fan_in_state.get("status") or "") == "blocked" and not corridor_active:
        status = "blocked"
        blockers.append("fan-in graph has missing repo-visible coordination evidence")
    execution_slice = str(active_plan.get("execution_slice") or active_plan.get("primary_roadmap_item") or (corridor_policy_ids[0] if corridor_policy_ids else "standing-delegation-corridor" if corridor_active else ""))

    return {
        "status": status,
        "blockers": tuple(blockers),
        "session_id": str(session.get("session_id") or ""),
        "execution_slice": execution_slice,
        "coordination_root": str(topology.get("coordination_root") or ""),
        "integration_root": str(topology.get("coordination_root") or ""),
        "edit_worktree_roots": tuple(str(root) for root in _json_list(topology.get("target_roots")) if str(root).strip()),
        "living_routes": (
            WORK_CLAIMS_DIR_REL,
            HANDOFF_PACKETS_DIR_REL,
            "project/verification/agent-runs",
            TASK_SESSIONS_DIR_REL,
            STANDING_DELEGATIONS_DIR_REL,
            "project/research",
            "project/verification",
            SYMPHONY_QUEUE_DIR_REL,
        ),
        "safe_worker_routes": ("claim", "handoff", "evidence", "task-session", "approval-packet"),
        "forbidden_routes": tuple(sorted(TASK_SESSION_RECEIPT_FORBIDDEN_ROUTES | {"archive", "commit", "push", "release"})),
        "write_scope": _string_tuple(active_plan.get("target_artifacts")) or corridor_scope_roots,
        "evidence_counts": {**evidence_counts, "task-session-receipt": len(receipt_refs), "symphony-queue": queue_count, "standing-delegation": len(_json_list(corridor.get("records")))},
        "fan_in": fan_in_state,
        "standing_delegation_corridor": corridor,
        "warnings": warnings,
        "errors": errors,
    }


def _conductor_payload(state: dict[str, object]) -> dict[str, object]:
    return {
        "status": str(state.get("status") or ""),
        "session_id": str(state.get("session_id") or ""),
        "execution_slice": str(state.get("execution_slice") or ""),
        "coordination_root": str(state.get("coordination_root") or ""),
        "integration_root": str(state.get("integration_root") or ""),
        "edit_worktree_roots": list(_string_tuple(state.get("edit_worktree_roots"))),
        "living_routes": list(_string_tuple(state.get("living_routes"))),
        "safe_worker_routes": list(_string_tuple(state.get("safe_worker_routes"))),
        "forbidden_routes": list(_string_tuple(state.get("forbidden_routes"))),
        "write_scope": list(_string_tuple(state.get("write_scope"))),
        "blockers": list(_string_tuple(state.get("blockers"))),
        "standing_delegation_corridor": dict(state.get("standing_delegation_corridor") or {}),
        "worker_launch_approved": False,
        "lifecycle_approval_granted": False,
        "provider_routing_authority": False,
        "completion_claim_policy": work_claim_completion_policy_payload(),
        "authority_boundary": TASK_SESSION_CONDUCTOR_BOUNDARY,
    }


def _conductor_summary_findings(state: dict[str, object]) -> list[Finding]:
    status = str(state.get("status") or "")
    severity = "warn" if status in {"blocked", "refused"} else "info"
    return [
        Finding(
            "info",
            "task-session-conductor-read-only",
            "task-session conductor inspect writes no files, launches no workers, creates no queue item, and grants no lifecycle authority",
        ),
        Finding(
            severity,
            "task-session-conductor-status",
            (
                f"conductor_status={status}; session_id={state.get('session_id') or '<none>'}; "
                f"execution_slice={state.get('execution_slice') or '<none>'}; "
                f"fan_in_status={dict(state.get('fan_in') or {}).get('status') or '<none>'}; "
                f"standing_delegation_corridor={str(bool(dict(state.get('standing_delegation_corridor') or {}).get('active'))).lower()}"
            ),
            "project/implementation-plan.md",
        ),
    ]


def _conductor_root_findings(state: dict[str, object]) -> list[Finding]:
    return [
        Finding(
            "info",
            "task-session-conductor-root",
            (
                f"coordination_root={state.get('coordination_root') or '<none>'}; "
                f"integration_root={state.get('integration_root') or '<none>'}; "
                f"edit_worktree_roots={_sample_text(_string_tuple(state.get('edit_worktree_roots')))}"
            ),
            "project/project-state.md",
        ),
        Finding(
            "info",
            "task-session-conductor-root-boundary",
            "the coordination root is a living evidence root, not a sealed worker memory sandbox or hidden runtime authority",
            "project/project-state.md",
        ),
    ]


def _conductor_route_findings(state: dict[str, object]) -> list[Finding]:
    return [
        Finding(
            "info",
            "task-session-conductor-living-routes",
            f"living coordination routes={_sample_text(_string_tuple(state.get('living_routes')), limit=8)}",
            "project/verification",
        ),
        Finding(
            "info",
            "task-session-conductor-safe-worker-routes",
            f"worker evidence routes={_sample_text(_string_tuple(state.get('safe_worker_routes')))}; forbidden authority routes={_sample_text(_string_tuple(state.get('forbidden_routes')), limit=8)}",
            "project/verification",
        ),
    ]


def _conductor_graph_findings(state: dict[str, object]) -> list[Finding]:
    counts = dict(state.get("evidence_counts") or {})
    details = ", ".join(f"{key}={counts[key]}" for key in sorted(counts)) or "none"
    findings = [
        Finding(
            "info",
            "task-session-conductor-evidence-graph",
            f"coordination evidence counts: {details}",
            "project/verification",
        )
    ]
    blockers = _string_tuple(state.get("blockers"))
    findings.extend(Finding("warn", "task-session-conductor-blocker", blocker, "project/verification") for blocker in blockers)
    if not blockers:
        findings.append(
            Finding(
                "info",
                "task-session-conductor-conflict-control",
                "source edits stay conflict-controlled by work claims, handoff scope, fan-in evidence, and explicit lifecycle rails",
                "project/verification",
            )
        )
    return findings


def _conductor_authority_findings() -> list[Finding]:
    return [
        Finding("info", "task-session-conductor-authority-worker-launch", "worker_launch=false; no worker process, provider call, shell, or queue consumer is started"),
        Finding("info", "task-session-conductor-authority-lifecycle", "lifecycle, roadmap, writeback, archive, Git, release, and provider-routing approvals remain false"),
        Finding("info", "task-session-conductor-authority-completion-claims", "external tracker/orchestrator completion claims are report-only; repo-visible completion evidence remains required and cannot approve closeout"),
        Finding("info", "task-session-conductor-authority-route-proposals", "route proposals are evidence only and must be reviewed through explicit dry-run/apply rails before execution"),
    ]


def _conductor_boundary_findings() -> list[Finding]:
    return [
        Finding("info", "task-session-conductor-boundary", TASK_SESSION_CONDUCTOR_BOUNDARY),
        Finding("info", "task-session-conductor-route", "conductor inspect is terminal-only/read-only and creates no claim, handoff, agent-run, receipt, queue, archive, writeback, or Git mutation"),
    ]


def _provider_launcher_payload(inventory: Inventory, state: dict[str, object]) -> dict[str, object]:
    required_env = tuple(_provider_env_presence(name) for name in PROVIDER_LAUNCHER_REQUIRED_ENV)
    gate_status = "configured" if all(row["present"] for row in required_env) else "missing-runtime-config"
    active_plan = _active_plan_payload(inventory)
    execution_slice = str(state.get("execution_slice") or active_plan.get("execution_slice") or active_plan.get("primary_roadmap_item") or "task-session").strip()
    session_id = _launcher_record_id(str(state.get("session_id") or active_plan.get("plan_id") or "task-session"))
    task_id = _launcher_record_id(execution_slice or "provider-runtime")
    dry_run_command = (
        "mylittleharness --root <root> task-session --dry-run "
        f"--session-id {session_id}-provider-runtime "
        f"--task-id {task_id} "
        "--objective \"Record secret-safe provider runtime config readiness\" "
        "--runtime-owner optional-orchestrator "
        "--runtime-backend openai-sdk "
        "--provider-ref env:OPENAI_API_KEY "
        "--read-context project/implementation-plan.md "
        "--allowed-route claim "
        "--allowed-route handoff "
        "--allowed-route evidence "
        "--required-output task-session-receipt "
        "--required-output work-claim "
        "--required-output handoff "
        "--required-output agent-run "
        "--required-output fan-in-inspect"
    )
    return {
        "schema": TASK_SESSION_PROVIDER_LAUNCHER_SCHEMA,
        "profile": PROVIDER_LAUNCHER_PROFILE,
        "provider_gate_status": gate_status,
        "read_only": True,
        "secret_safe": True,
        "stores_secret_material": False,
        "secret_values_recorded": False,
        "required_env": [dict(row) for row in required_env],
        "runtime_owner": "optional-orchestrator",
        "runtime_backend": "openai-sdk",
        "provider_refs": ["env:OPENAI_API_KEY"],
        "provider_routing_authority": False,
        "provider_auto_selection": False,
        "provider_call": False,
        "worker_launch": False,
        "queue_item_created": False,
        "required_repo_visible_evidence": [
            "task-session-receipt",
            "work-claim",
            "handoff",
            "agent-run",
            "fan-in-inspect",
        ],
        "receipt_dry_run_command": dry_run_command,
        "approvals": {
            "lifecycle": False,
            "fan_in": False,
            "provider_routing": False,
            "worker_launch": False,
            "roadmap": False,
            "archive": False,
            "git": False,
        },
        "authority_boundary": TASK_SESSION_PROVIDER_LAUNCHER_BOUNDARY,
    }


def _provider_launcher_findings(inventory: Inventory, state: dict[str, object]) -> list[Finding]:
    launcher = _provider_launcher_payload(inventory, state)
    env_rows = [row for row in _json_list(launcher.get("required_env")) if isinstance(row, dict)]
    present = sum(1 for row in env_rows if row.get("present"))
    total = len(env_rows)
    severity = "info" if str(launcher.get("provider_gate_status") or "") == "configured" else "warn"
    return [
        Finding(
            "info",
            "task-session-provider-launcher-read-only",
            "provider runtime launcher report writes no files, starts no worker, creates no queue item, and calls no provider",
            "project/implementation-plan.md",
        ),
        Finding(
            severity,
            "task-session-provider-launcher-gate",
            (
                f"profile={launcher['profile']}; provider_gate_status={launcher['provider_gate_status']}; "
                f"required_env_present={present}/{total}; secret_material_recorded=false"
            ),
            "project/implementation-plan.md",
        ),
        Finding(
            "info",
            "task-session-provider-launcher-authority",
            "provider_routing_authority=false; provider_auto_selection=false; provider_call=false; worker_launch=false",
            "project/implementation-plan.md",
        ),
        Finding(
            "info",
            "task-session-provider-launcher-receipt-dry-run",
            f"receipt dry-run command: {launcher['receipt_dry_run_command']}",
            "project/verification/task-sessions",
        ),
        Finding("info", "task-session-provider-launcher-boundary", TASK_SESSION_PROVIDER_LAUNCHER_BOUNDARY),
    ]


def _provider_env_presence(name: str) -> dict[str, object]:
    return {
        "name": name,
        "present": bool(os.environ.get(name)),
        "secret_material_recorded": False,
    }


def _launcher_record_id(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return candidate if candidate else "task-session"


def _conductor_next_safe_command(state: dict[str, object]) -> dict[str, object]:
    command = "mylittleharness --root <root> check --focus agents"
    if str(state.get("status") or "") == "ready":
        command = "mylittleharness --root <root> task-session --inspect --fan-in --json"
    return {
        "command": command,
        "advisory": True,
        "requires_explicit_operator_action": True,
        "approves_lifecycle": False,
        "approves_worker_launch": False,
        "boundary": "next command is navigation only; worker launch, provider routing, fan-in, writeback, archive, roadmap, and Git remain explicit decisions",
    }


def _fan_in_payload(state: dict[str, object]) -> dict[str, object]:
    return {
        "status": str(state.get("status") or ""),
        "activated": bool(state.get("activated")),
        "execution_slice": str(state.get("execution_slice") or ""),
        "session_id": str(state.get("session_id") or ""),
        "docs_decision": str(state.get("docs_decision") or ""),
        "reasons": list(_string_tuple(state.get("reasons"))),
        "missing": list(_string_tuple(state.get("missing"))),
        "blockers": list(_string_tuple(state.get("blockers"))),
        "claim_refs": list(_string_tuple(state.get("claim_refs"))),
        "handoff_refs": list(_string_tuple(state.get("handoff_refs"))),
        "agent_run_refs": list(_string_tuple(state.get("agent_run_refs"))),
        "receipt_refs": list(_string_tuple(state.get("receipt_refs"))),
        "route_proposal_refs": list(_string_tuple(state.get("route_proposal_refs"))),
        "approval_granted": False,
        "authority_boundary": TASK_SESSION_FAN_IN_BOUNDARY,
    }


def _fan_in_summary_findings(inventory: Inventory, state: dict[str, object]) -> list[Finding]:
    status = str(state.get("status") or "")
    status_code = {
        "ready": "task-session-fan-in-ready",
        "blocked": "task-session-fan-in-blocked",
        "refused": "task-session-fan-in-refused",
        "not-required": "task-session-fan-in-not-required",
    }.get(status, "task-session-fan-in-status")
    severity = "warn" if status in {"blocked", "refused"} else "info"
    source = "project/implementation-plan.md" if inventory.active_plan_surface and inventory.active_plan_surface.exists else "project/project-state.md"
    return [
        Finding(
            "info",
            "task-session-fan-in-read-only",
            "task-session fan-in inspect writes no files, launches no workers, executes no route proposals, and grants no lifecycle or provider authority",
        ),
        Finding(
            severity,
            status_code,
            (
                f"fan_in_status={status}; activated={str(bool(state.get('activated'))).lower()}; "
                f"execution_slice={state.get('execution_slice') or '<none>'}; "
                f"missing={_sample_text(_string_tuple(state.get('missing')))}; "
                f"docs_decision={state.get('docs_decision') or '<none>'}"
            ),
            source,
        ),
    ]


def _fan_in_graph_findings(state: dict[str, object]) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "task-session-fan-in-activation",
            f"activation_reasons={_sample_text(_string_tuple(state.get('reasons')))}",
            "project/implementation-plan.md",
        ),
        Finding(
            "info",
            "task-session-fan-in-refs",
            (
                f"claims={len(_string_tuple(state.get('claim_refs')))}; "
                f"handoffs={len(_string_tuple(state.get('handoff_refs')))}; "
                f"agent_runs={len(_string_tuple(state.get('agent_run_refs')))}; "
                f"receipts={len(_string_tuple(state.get('receipt_refs')))}; "
                f"route_proposal_refs={len(_string_tuple(state.get('route_proposal_refs')))}"
            ),
            "project/verification",
        ),
    ]
    blockers = _string_tuple(state.get("blockers"))
    if blockers:
        findings.extend(
            Finding("warn", "task-session-fan-in-blocker", blocker, "project/verification")
            for blocker in blockers[:8]
        )
    elif bool(state.get("activated")):
        findings.append(
            Finding(
                "info",
                "task-session-fan-in-source-hashes",
                "accepted agent-run source hashes and residual/docs checks are current for the matched fan-in graph",
                "project/verification/agent-runs",
            )
        )
    return findings


def _fan_in_receipt_findings(state: dict[str, object]) -> list[Finding]:
    findings = list(state.get("receipt_findings") or [])
    receipts = list(state.get("receipts") or [])
    if receipts:
        findings.append(
            Finding(
                "info",
                "task-session-fan-in-receipts",
                (
                    f"matching task-session receipts={len(receipts)}; "
                    f"refs={_sample_text(_string_tuple(state.get('receipt_refs')))}"
                ),
                TASK_SESSIONS_DIR_REL,
            )
        )
        for receipt in receipts[:5]:
            findings.append(
                Finding(
                    "info",
                    "task-session-fan-in-receipt",
                    (
                        f"receipt={receipt.get('rel_path')}; session_id={receipt.get('session_id')}; "
                        f"runtime={receipt.get('runtime_owner')}/{receipt.get('runtime_backend')}; "
                        f"evidence_refs={len(_json_list(receipt.get('evidence_refs')))}; "
                        f"route_proposal_refs={len(_json_list(receipt.get('route_proposal_refs')))}"
                    ),
                    str(receipt.get("rel_path") or TASK_SESSIONS_DIR_REL),
                )
            )
    else:
        findings.append(
            Finding(
                "info",
                "task-session-fan-in-receipts",
                f"no matching task-session receipt records found under {TASK_SESSIONS_DIR_REL}/*.json",
                TASK_SESSIONS_DIR_REL,
            )
        )
    return findings


def _fan_in_dirty_start_findings(state: dict[str, object]) -> list[Finding]:
    dirty_start = dict(state.get("dirty_start") or {})
    changed_paths = _json_list(dirty_start.get("changed_paths"))
    samples = ", ".join(str(item.get("path") or "") for item in changed_paths[:5] if isinstance(item, dict)) or "none"
    return [
        Finding(
            "info",
            "task-session-fan-in-dirty-start",
            (
                f"vcs_state={dirty_start.get('state') or '<unknown>'}; "
                f"changed_count={dirty_start.get('changed_count')}; sample={samples}"
            ),
        )
    ]


def _fan_in_authority_findings() -> list[Finding]:
    return [
        Finding("info", "task-session-fan-in-authority-mlh", "MLH may report session fan-in readiness, but approval remains a separate lifecycle/writeback/archive route decision"),
        Finding("info", "task-session-fan-in-authority-runtime", "external runtimes may consume this packet as evidence only; private traces or SDK state are not authoritative"),
        Finding("info", "task-session-fan-in-authority-provider", "provider routing and worker launch remain false in this fan-in packet"),
    ]


def _fan_in_boundary_findings() -> list[Finding]:
    return [
        Finding("info", "task-session-fan-in-boundary", TASK_SESSION_FAN_IN_BOUNDARY),
        Finding("info", "task-session-fan-in-route", "task-session fan-in inspect is terminal-only/read-only and creates no queue, receipt, handoff, work claim, agent run, archive, writeback, or Git mutation"),
    ]


def _fan_in_next_safe_command(state: dict[str, object]) -> dict[str, object]:
    status = str(state.get("status") or "")
    command = "mylittleharness --root <root> check"
    if status == "ready":
        command = "mylittleharness --root <root> writeback --dry-run"
    elif status == "blocked":
        command = "mylittleharness --root <root> check --focus agents"
    return {
        "command": command,
        "advisory": True,
        "requires_explicit_operator_action": True,
        "approves_lifecycle": False,
        "approves_fan_in": False,
        "boundary": "next command is navigation or dry-run only; fan-in readiness still cannot archive, writeback, stage, commit, push, launch workers, or choose providers",
    }


def _summary_findings(inventory: Inventory) -> list[Finding]:
    session = _session_payload(inventory)
    corridor = dict(session.get("standing_delegation_corridor") or {})
    findings = [
        Finding("info", "task-session-inspect-read-only", "task-session inspect starts no worker, daemon, provider call, shell, queue consumer, writeback, archive, or Git operation"),
        Finding("info", "task-session-inspect-root", f"root_kind={inventory.root_kind}; root={inventory.root}"),
        Finding(
            "info",
            "task-session-inspect-readiness",
            (
                f"session_id={session['session_id']}; readiness={session['readiness']}; "
                f"active_plan_exists={session['active_plan_exists']}; docs_decision={session['docs_decision'] or '<none>'}"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
    ]
    if corridor.get("active"):
        findings.append(
            Finding(
                "info",
                "task-session-standing-delegation-corridor",
                "standing-delegation corridor is active for bounded routine work; protected owner approvals, provider routing, Git, release, destructive cleanup, and policy changes remain gated",
                STANDING_DELEGATIONS_DIR_REL,
            )
        )
    for warning in _string_tuple(corridor.get("warnings"))[:5]:
        findings.append(Finding("warn", "task-session-standing-delegation-corridor-warning", warning, STANDING_DELEGATIONS_DIR_REL))
    return findings


def _lifecycle_findings(inventory: Inventory) -> list[Finding]:
    lifecycle = _lifecycle_payload(inventory)
    return [
        Finding(
            "info",
            "task-session-lifecycle",
            (
                f"plan_status={lifecycle['plan_status'] or '<none>'}; "
                f"active_plan={lifecycle['active_plan'] or '<none>'}; "
                f"active_phase={lifecycle['active_phase'] or '<none>'}; "
                f"phase_status={lifecycle['phase_status'] or '<none>'}; "
                f"last_archived_plan={lifecycle['last_archived_plan'] or '<none>'}"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
        Finding(
            "info",
            "task-session-lifecycle-authority",
            "project-state lifecycle frontmatter remains authority; task-session inspect only projects it for runtime preflight",
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
    ]


def _roadmap_findings(inventory: Inventory) -> list[Finding]:
    items, parse_findings = roadmap_items_for_diagnostics(inventory)
    queue = _roadmap_queue(items)
    details = ", ".join(f"{status}={count}" for status, count in sorted(_roadmap_counts(items).items())) or "none"
    queue_detail = ", ".join(item["id"] for item in queue[:5]) or "none"
    return [
        *parse_findings,
        Finding("info", "task-session-roadmap", f"roadmap status counts: {details}", "project/roadmap.md"),
        Finding("info", "task-session-roadmap-queue", f"active/accepted queue: {queue_detail}", "project/roadmap.md"),
        Finding("info", "task-session-roadmap-authority", "roadmap rows sequence accepted work but cannot launch workers or approve lifecycle by themselves", "project/roadmap.md"),
    ]


def _topology_findings(inventory: Inventory) -> list[Finding]:
    topology = _topology_payload(inventory)
    return [
        Finding(
            "info",
            "task-session-topology",
            (
                f"root_id={topology['root_id']}; coordination_root={topology['coordination_root']}; "
                f"target_roots={', '.join(str(root) for root in topology['target_roots']) or '<none>'}"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
        Finding(
            "info",
            "task-session-topology-reserved",
            "multi-root fields are present as contract data only; this inspect slice does not execute across roots or authorize cross-root routes",
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
    ]


def _authority_findings() -> list[Finding]:
    return [
        Finding("info", "task-session-authority-mlh", "MLH owns lifecycle, readiness, evidence, writeback, archive, closeout, roadmap, and Git boundaries"),
        Finding("info", "task-session-authority-runtime", "external runtimes may consume this packet to schedule work, but they do not gain lifecycle or provider-routing authority"),
        Finding("info", "task-session-authority-provider", "provider/model/runtime provenance is evidence only; provider_routing=false in this contract"),
    ]


def _coordination_findings(inventory: Inventory) -> list[Finding]:
    findings = _coordination_raw_findings(inventory)
    counts = _coordination_counts(findings)
    warnings = [finding for finding in findings if finding.severity == "warn"]
    errors = [finding for finding in findings if finding.severity == "error"]
    summary = ", ".join(f"{key}={value}" for key, value in counts.items())
    samples = [*errors, *warnings][:5]
    return [
        Finding(
            "error" if errors else "warn" if warnings else "info",
            "task-session-coordination-summary",
            f"coordination evidence findings: {summary}; errors={len(errors)}; warnings={len(warnings)}",
            "project/verification",
        ),
        *[
            Finding(
                finding.severity,
                "task-session-coordination-sample",
                f"{finding.code}: {finding.message}",
                finding.source,
                finding.line,
            )
            for finding in samples
        ],
        Finding(
            "info",
            "task-session-coordination-boundary",
            "coordination evidence is summarized for runtime preflight; inspect dedicated handoff/claim/evidence/fan-in routes for full detail before lifecycle movement",
            "project/verification",
        ),
    ]


def _coordination_raw_findings(inventory: Inventory) -> list[Finding]:
    return [
        *session_active_work_findings(inventory, "task-session-active-work"),
        *work_claim_status_findings(inventory, "task-session-work-claim"),
        *handoff_packet_status_findings(inventory, "task-session-handoff"),
        *dispatcher_launch_status_findings(inventory, "task-session-dispatcher-launch"),
        *agent_run_record_findings(inventory, "task-session-agent-run"),
    ]


def _capability_findings() -> list[Finding]:
    capabilities = _capabilities_payload()
    return [
        Finding(
            "info",
            "task-session-capabilities",
            (
                f"inspect={str(capabilities['inspect']).lower()}; "
                f"receipt_apply={str(capabilities['receipt_apply']).lower()}; "
                f"fan_in_authority={str(capabilities['fan_in_authority']).lower()}; "
                f"route_proposal_validation={str(capabilities['route_proposal_validation']).lower()}; "
                f"multi_root_execution={str(capabilities['multi_root_execution']).lower()}; "
                f"provider_routing={str(capabilities['provider_routing']).lower()}"
            ),
        )
    ]


def _standing_delegation_corridor_payload(inventory: Inventory) -> dict[str, object]:
    records: list[dict[str, object]] = []
    warnings: list[str] = []
    authority_boundary = "standing delegation is routine-work corridor evidence only; protected owner decisions keep their own gates"
    directory = inventory.root / STANDING_DELEGATIONS_DIR_REL
    if inventory.root_kind != "live_operating_root" or not directory.exists():
        return {
            "active": False,
            "records": [],
            "policy_ids": [],
            "warnings": [],
            "record_count": 0,
            "authority_boundary": authority_boundary,
        }
    for path in sorted(directory.glob("*.json")):
        rel_path = _to_rel_path(inventory.root, path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            warnings.append(f"{rel_path}: unreadable standing-delegation record: {exc}")
            continue
        if not isinstance(data, dict):
            warnings.append(f"{rel_path}: standing-delegation record is not a JSON object")
            continue
        if data.get("schema") != STANDING_DELEGATION_SCHEMA or data.get("record_type") != "standing-delegation":
            warnings.append(f"{rel_path}: standing-delegation record has an unexpected schema or record_type")
            continue
        expires_at = str(data.get("expires_at") or "").strip()
        if _standing_delegation_expired(expires_at):
            warnings.append(f"{rel_path}: standing-delegation record is expired or has an invalid expiration")
            continue
        allowed_actions = tuple(
            str(action).strip()
            for action in _json_list(data.get("allowed_actions"))
            if str(action or "").strip()
        )
        hard_boundaries = {str(item).strip() for item in _json_list(data.get("hard_human_boundaries"))}
        missing_boundaries = sorted(set(HARD_HUMAN_BOUNDARIES).difference(hard_boundaries))
        corridor_actions = tuple(action for action in allowed_actions if action in STANDING_DELEGATION_CORRIDOR_ACTIONS)
        if missing_boundaries:
            warnings.append(f"{rel_path}: standing-delegation record is missing hard boundaries: {', '.join(missing_boundaries)}")
            continue
        if not corridor_actions:
            continue
        records.append(
            {
                "policy_id": str(data.get("policy_id") or Path(rel_path).stem),
                "rel_path": rel_path,
                "allowed_actions": list(corridor_actions),
                "scope_roots": list(_json_list(data.get("scope_roots"))),
                "expires_at": expires_at,
            }
        )
    return {
        "active": bool(records),
        "records": records,
        "policy_ids": [str(record.get("policy_id") or "") for record in records],
        "warnings": warnings,
        "record_count": len(records),
        "authority_boundary": authority_boundary,
    }


def _standing_delegation_expired(value: str) -> bool:
    try:
        expires_at = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return expires_at <= datetime.now(timezone.utc)


def _boundary_findings() -> list[Finding]:
    return [
        Finding("info", "task-session-boundary", TASK_SESSION_BOUNDARY),
        Finding("info", "task-session-source-boundary", "repo-visible MLH files remain truth; private runtime traces are never the only accepted evidence"),
    ]


def _session_payload(inventory: Inventory) -> dict[str, object]:
    lifecycle = _lifecycle_payload(inventory)
    active_plan = _active_plan_payload(inventory)
    corridor = _standing_delegation_corridor_payload(inventory)
    corridor_policy_id = next((str(policy_id) for policy_id in _json_list(corridor.get("policy_ids")) if str(policy_id).strip()), "")
    session_id = str(active_plan.get("plan_id") or lifecycle.get("active_phase") or corridor_policy_id or "no-active-plan")
    active_plan_exists = bool(active_plan.get("exists"))
    active_plan_open = str(lifecycle.get("plan_status") or "").strip().casefold() == "active" or bool(str(lifecycle.get("active_plan") or "").strip())
    if inventory.root_kind != "live_operating_root":
        readiness = "non-authority-root"
    elif active_plan_open and active_plan_exists:
        readiness = "ready"
    elif active_plan_open:
        readiness = "blocked-missing-active-plan"
    elif corridor.get("active"):
        readiness = "standing-delegation-corridor"
    else:
        readiness = "no-active-plan"
    return {
        "session_id": session_id,
        "readiness": readiness,
        "active_plan_open": active_plan_open,
        "active_plan_exists": active_plan_exists,
        "docs_decision": str(active_plan.get("docs_decision") or ""),
        "external_runtime_may_launch_workers": readiness in {"ready", "standing-delegation-corridor"},
        "lifecycle_approval_granted": False,
        "standing_delegation_corridor": corridor,
    }


def _lifecycle_payload(inventory: Inventory) -> dict[str, object]:
    data = _state_data(inventory)
    return {
        "plan_status": str(data.get("plan_status") or ""),
        "active_plan": str(data.get("active_plan") or ""),
        "active_phase": str(data.get("active_phase") or ""),
        "phase_status": str(data.get("phase_status") or ""),
        "last_archived_plan": str(data.get("last_archived_plan") or ""),
        "product_source_root": str(data.get("product_source_root") or data.get("projection_root") or ""),
        "operating_mode": str(data.get("operating_mode") or ""),
    }


def _active_plan_payload(inventory: Inventory) -> dict[str, object]:
    surface = inventory.active_plan_surface
    exists = bool(surface and surface.exists)
    data = surface.frontmatter.data if exists and surface else {}
    return {
        "rel_path": surface.rel_path if surface else _lifecycle_payload(inventory).get("active_plan", ""),
        "exists": exists,
        "plan_id": str(data.get("plan_id") or ""),
        "title": str(data.get("title") or ""),
        "status": str(data.get("status") or ""),
        "active_phase": str(data.get("active_phase") or ""),
        "phase_status": str(data.get("phase_status") or ""),
        "docs_decision": str(data.get("docs_decision") or ""),
        "execution_slice": str(data.get("execution_slice") or ""),
        "primary_roadmap_item": str(data.get("primary_roadmap_item") or ""),
        "covered_roadmap_items": _string_list(data.get("covered_roadmap_items")),
        "target_artifacts": _string_list(data.get("target_artifacts")),
        "execution_policy": str(data.get("execution_policy") or ""),
        "auto_continue": bool(data.get("auto_continue")) if "auto_continue" in data else False,
        "closeout_boundary": str(data.get("closeout_boundary") or ""),
    }


def _roadmap_payload(inventory: Inventory) -> dict[str, object]:
    items, parse_findings = roadmap_items_for_diagnostics(inventory)
    queue = _roadmap_queue(items)
    primary_id = str(_active_plan_payload(inventory).get("primary_roadmap_item") or "")
    primary_item = items.get(primary_id) if primary_id else None
    return {
        "item_count": len(items),
        "status_counts": dict(sorted(_roadmap_counts(items).items())),
        "active_or_accepted_queue": queue[:10],
        "primary_item": _roadmap_item_payload(primary_id, primary_item) if primary_id else {},
        "parse_findings": [finding.to_dict() for finding in parse_findings],
    }


def _roadmap_counts(items: dict[str, object]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in items.values():
        status = str(item.fields.get("status") or "<missing>").strip() or "<missing>"
        counts[status] += 1
    return counts


def _roadmap_queue(items: dict[str, object]) -> list[dict[str, object]]:
    rows: list[tuple[int, str, dict[str, object]]] = []
    for item_id, item in items.items():
        status = str(item.fields.get("status") or "").strip()
        if status.casefold() not in {"active", "accepted"}:
            continue
        order = item.fields.get("order")
        sort_order = order if isinstance(order, int) else 999999
        rows.append(
            (
                sort_order,
                item_id,
                {
                    "id": item_id,
                    "status": status,
                    "execution_slice": str(item.fields.get("execution_slice") or item_id),
                    "order": order if isinstance(order, int) else None,
                    "target_artifacts": _string_list(item.fields.get("target_artifacts")),
                },
            )
        )
    return [row for _order, _item_id, row in sorted(rows, key=lambda item: (item[0], item[1]))]


def _roadmap_item_payload(item_id: str, item: object | None) -> dict[str, object]:
    if item is None:
        return {"id": item_id, "found": False}
    fields = getattr(item, "fields", {})
    return {
        "id": item_id,
        "found": True,
        "title": str(getattr(item, "title", "") or ""),
        "status": str(fields.get("status") or ""),
        "stage": str(fields.get("stage") or ""),
        "execution_slice": str(fields.get("execution_slice") or ""),
        "slice_goal": str(fields.get("slice_goal") or ""),
        "target_artifacts": _string_list(fields.get("target_artifacts")),
        "docs_decision": str(fields.get("docs_decision") or ""),
    }


def _topology_payload(inventory: Inventory) -> dict[str, object]:
    lifecycle = _lifecycle_payload(inventory)
    product_source_root = str(lifecycle.get("product_source_root") or "").strip()
    target_roots = [product_source_root] if product_source_root else [str(inventory.root)]
    root_id = _root_id(inventory.root)
    return {
        "root_id": root_id,
        "coordination_root": str(inventory.root),
        "target_roots": target_roots,
        "evidence_owner": root_id,
        "fan_in_owner": root_id,
        "queue_owner": root_id,
        "cross_root_allowed_routes": [],
        "multi_root_reserved": True,
        "multi_root_execution_enabled": False,
    }


def _authority_payload() -> dict[str, object]:
    return {
        "lifecycle_authority": "MLH",
        "runtime_authority": "external-runtime-may-schedule-only-after-MLH-preflight",
        "provider_routing": False,
        "provider_runtime_config_authoritative": False,
        "private_traces_authoritative": False,
        "repo_visible_evidence_required": True,
        "external_completion_claims_authoritative": False,
        "completion_claim_policy": work_claim_completion_policy_payload(),
        "external_runtime_approves_lifecycle": False,
    }


def _coordination_payload(findings: list[Finding]) -> dict[str, object]:
    return {
        "finding_counts": _coordination_counts(findings),
        "warning_count": sum(1 for finding in findings if finding.severity == "warn"),
        "error_count": sum(1 for finding in findings if finding.severity == "error"),
        "warning_codes": [finding.code for finding in findings if finding.severity == "warn"][:20],
        "error_codes": [finding.code for finding in findings if finding.severity == "error"][:20],
    }


def _coordination_counts(findings: list[Finding]) -> dict[str, int]:
    prefixes = (
        "task-session-active-work",
        "task-session-work-claim",
        "task-session-handoff",
        "task-session-dispatcher-launch",
        "task-session-agent-run",
    )
    return {prefix: sum(1 for finding in findings if finding.code.startswith(prefix)) for prefix in prefixes}


def _capabilities_payload() -> dict[str, bool]:
    return {
        "inspect": True,
        "receipt_apply": True,
        "fan_in_authority": False,
        "route_proposal_validation": False,
        "multi_root_execution": False,
        "provider_routing": False,
        "provider_runtime_launcher": True,
        "completion_claim_policy": True,
        "worker_launch": False,
        "writeback": False,
        "archive": False,
        "git": False,
    }


def _next_safe_command_payload(inventory: Inventory) -> dict[str, object]:
    command = "mylittleharness --root <root> handoff --status"
    if not _session_payload(inventory).get("active_plan_open"):
        command = "mylittleharness --root <root> check"
    return {
        "command": command,
        "advisory": True,
        "requires_explicit_operator_action": True,
        "approves_lifecycle": False,
        "boundary": "next command is navigation only; apply/closeout/archive/Git remain separate explicit MLH routes",
    }


def _source_refs(inventory: Inventory) -> list[str]:
    refs = ["AGENTS.md", "project/project-state.md"]
    if inventory.manifest_surface and inventory.manifest_surface.exists:
        refs.append(inventory.manifest_surface.rel_path)
    if inventory.active_plan_surface and inventory.active_plan_surface.exists:
        refs.append(inventory.active_plan_surface.rel_path)
    if (inventory.root / "project/roadmap.md").exists():
        refs.append("project/roadmap.md")
    return list(dict.fromkeys(refs))


def _task_session_receipts(root: Path, execution_slice: str, session_id: str) -> tuple[list[dict[str, object]], list[Finding]]:
    directory = root / TASK_SESSIONS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return [], []
    receipts: list[dict[str, object]] = []
    findings: list[Finding] = []
    for path in sorted(directory.glob("*.json")):
        rel_path = _to_rel_path(root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", "task-session-fan-in-receipt-malformed", "task-session receipt path is not a regular file", rel_path))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", "task-session-fan-in-receipt-malformed", f"task-session receipt could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict) or data.get("schema") != TASK_SESSION_RECEIPT_SCHEMA:
            findings.append(Finding("warn", "task-session-fan-in-receipt-malformed", "task-session receipt schema is missing or unsupported", rel_path))
            continue
        receipt_execution_slice = str(data.get("execution_slice") or "").strip()
        receipt_session_id = str(data.get("session_id") or "").strip()
        if execution_slice and receipt_execution_slice != execution_slice and receipt_session_id != session_id:
            continue
        runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
        receipts.append(
            {
                "rel_path": rel_path,
                "session_id": receipt_session_id,
                "task_id": str(data.get("task_id") or ""),
                "execution_slice": receipt_execution_slice,
                "runtime_owner": str(runtime.get("owner") or ""),
                "runtime_backend": str(runtime.get("backend") or ""),
                "write_scope": _string_list(data.get("write_scope")),
                "read_context": _string_list(data.get("read_context")),
                "evidence_refs": _string_list(data.get("evidence_refs")),
                "claim_refs": _string_list(data.get("claim_refs")),
                "handoff_refs": _string_list(data.get("handoff_refs")),
                "route_proposal_refs": _string_list(data.get("route_proposal_refs")),
                "provider_refs": _string_list(data.get("provider_refs")),
            }
        )
    return receipts, findings


def _queue_item_count(root: Path) -> int:
    directory = root / SYMPHONY_QUEUE_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return 0
    return sum(1 for path in directory.glob("*.json") if path.is_file() and not path.is_symlink())


def _state_data(inventory: Inventory) -> dict[str, object]:
    if inventory.state and inventory.state.exists:
        return inventory.state.frontmatter.data
    return {}


def _active_plan_data(inventory: Inventory) -> dict[str, object]:
    if inventory.active_plan_surface and inventory.active_plan_surface.exists:
        return inventory.active_plan_surface.frontmatter.data
    return {}


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item or "").strip()]
    return [str(value)] if str(value).strip() else []


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(_string_list(value))


def _sample_text(values: tuple[str, ...], limit: int = 4) -> str:
    if not values:
        return "<none>"
    head = ", ".join(values[:limit])
    if len(values) > limit:
        return f"{head}, +{len(values) - limit} more"
    return head


def _to_rel_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _receipt_request_findings(inventory: Inventory, request: TaskSessionReceiptRequest, *, apply: bool) -> list[Finding]:
    severity = "error" if apply else "warn"
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(Finding(severity, "task-session-receipt-refused", f"target root kind is {inventory.root_kind}; task-session receipt writes require a live operating root"))
    if not request.session_id:
        findings.append(Finding(severity, "task-session-receipt-refused", "--session-id is required"))
    elif not ID_RE.match(request.session_id):
        findings.append(Finding(severity, "task-session-receipt-refused", "--session-id may contain only letters, digits, dot, underscore, or dash"))
    elif record_id_conflict(request.session_id):
        findings.append(Finding(severity, "task-session-receipt-refused", f"--session-id {record_id_conflict(request.session_id)}"))
    if not request.objective:
        findings.append(Finding(severity, "task-session-receipt-refused", "--objective is required"))
    if request.session_id:
        rel_path = _receipt_rel_path(request.session_id)
        conflict = root_relative_path_conflict(rel_path)
        if conflict:
            findings.append(Finding(severity, "task-session-receipt-refused", f"receipt target {conflict}", rel_path))
        target = inventory.root / rel_path
        if target.exists():
            findings.append(Finding(severity, "task-session-receipt-refused", "task-session receipt already exists; choose a new --session-id", rel_path))
        elif target.parent.exists() and target.parent.is_symlink():
            findings.append(Finding(severity, "task-session-receipt-refused", "task-session receipt directory is a symlink", TASK_SESSIONS_DIR_REL))
    findings.extend(_receipt_scope_findings(request, severity))
    return findings


def _receipt_scope_findings(request: TaskSessionReceiptRequest, severity: str) -> list[Finding]:
    findings: list[Finding] = []
    for flag, field_name in TASK_SESSION_RECEIPT_PATH_FIELDS:
        for rel_path in getattr(request, field_name):
            conflict = root_relative_path_conflict(rel_path)
            if conflict:
                findings.append(Finding(severity, "task-session-receipt-refused", f"{flag} {conflict}", rel_path))
    forbidden_paths = _forbidden_write_scope_paths(request.write_scope)
    if forbidden_paths:
        findings.append(
            Finding(
                severity,
                "task-session-receipt-refused",
                f"--write-scope cannot include lifecycle authority paths: {', '.join(forbidden_paths)}",
            )
        )
    forbidden_routes = _forbidden_receipt_routes(request.allowed_routes)
    if forbidden_routes:
        findings.append(
            Finding(
                severity,
                "task-session-receipt-refused",
                f"task-session receipt cannot allow lifecycle-authority routes: {', '.join(forbidden_routes)}",
            )
        )
    return findings


def _receipt_data(inventory: Inventory, request: TaskSessionReceiptRequest) -> dict[str, object]:
    topology = _topology_payload(inventory)
    active_plan = _active_plan_payload(inventory)
    execution_slice = (
        request.execution_slice
        or str(active_plan.get("execution_slice") or "").strip()
        or str(active_plan.get("primary_roadmap_item") or "").strip()
        or request.session_id
    )
    return {
        "schema": TASK_SESSION_RECEIPT_SCHEMA,
        "record_type": "task-session-receipt",
        "session_id": request.session_id,
        "task_id": request.task_id or request.session_id,
        "objective": request.objective,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runtime": {
            "owner": request.runtime_owner,
            "backend": request.runtime_backend,
            "provider_routing_authority": False,
        },
        "root_id": topology["root_id"],
        "coordination_root": topology["coordination_root"],
        "target_roots": topology["target_roots"],
        "evidence_owner": topology["evidence_owner"],
        "fan_in_owner": topology["fan_in_owner"],
        "queue_owner": topology["queue_owner"],
        "cross_root_allowed_routes": topology["cross_root_allowed_routes"],
        "execution_slice": execution_slice,
        "read_context": list(request.read_context),
        "write_scope": list(request.write_scope),
        "allowed_routes": list(request.allowed_routes),
        "stop_conditions": list(request.stop_conditions),
        "required_outputs": list(request.required_outputs),
        "evidence_refs": list(request.evidence_refs),
        "claim_refs": list(request.claim_refs),
        "handoff_refs": list(request.handoff_refs),
        "route_proposal_refs": list(request.route_proposal_refs),
        "provider_refs": list(request.provider_refs),
        "dirty_start": _dirty_start_payload(inventory.root),
        "source_refs": _source_refs(inventory),
        "preflight": {
            "session": _session_payload(inventory),
            "lifecycle": _lifecycle_payload(inventory),
            "active_plan": active_plan,
            "roadmap": _roadmap_payload(inventory),
            "topology": topology,
            "authority": _authority_payload(),
            "capabilities": _capabilities_payload(),
            "next_safe_command": _next_safe_command_payload(inventory),
        },
        "approvals": {
            "lifecycle": False,
            "fan_in": False,
            "route_proposal": False,
            "provider_routing": False,
            "git": False,
        },
        "authority_boundary": TASK_SESSION_RECEIPT_BOUNDARY,
    }


def _receipt_shape_findings(data: dict[str, object]) -> list[Finding]:
    return [
        Finding(
            "info",
            "task-session-receipt-shape",
            (
                f"session_id={data.get('session_id')}; execution_slice={data.get('execution_slice')}; "
                f"write_scope={len(_json_list(data.get('write_scope')))}; "
                f"evidence_refs={len(_json_list(data.get('evidence_refs')))}; "
                f"fan_in_approved={str(dict(data.get('approvals') or {}).get('fan_in')).lower()}"
            ),
            _receipt_rel_path(str(data.get("session_id") or "receipt")),
        )
    ]


def _receipt_boundary_findings() -> list[Finding]:
    return [
        Finding("info", "task-session-receipt-boundary", TASK_SESSION_RECEIPT_BOUNDARY, TASK_SESSIONS_DIR_REL),
        Finding("info", "task-session-receipt-route", f"task-session receipts live under {TASK_SESSIONS_DIR_REL}/*.json as repo-visible evidence; no hidden queue, daemon, provider gateway, lifecycle state, archive, or Git operation is created", TASK_SESSIONS_DIR_REL),
    ]


def _receipt_route_write_finding(rel_path: str, before_data: dict[str, object] | None, after_data: dict[str, object], *, apply: bool) -> Finding:
    before_text = None if before_data is None else _receipt_json(before_data)
    after_text = _receipt_json(after_data)
    operation = "created" if apply and before_data is None else "wrote" if apply else "create" if before_data is None else "write"
    prefix = "" if apply else "would "
    return Finding(
        "info",
        "task-session-receipt-route-write",
        (
            f"{prefix}{operation} route {rel_path}; before_hash={_hash_or_missing(before_text)}; "
            f"after_hash={_short_hash(after_text)}; before_bytes={_bytes_or_missing(before_text)}; "
            f"after_bytes={len(after_text.encode('utf-8'))}; source-bound write evidence is independent of Git tracking"
        ),
        rel_path,
    )


def _receipt_rel_path(session_id: str) -> str:
    return f"{TASK_SESSIONS_DIR_REL}/{session_id}.json"


def _receipt_json(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _dirty_start_payload(root: Path) -> dict[str, object]:
    posture = probe_vcs(root)
    return {
        "git_available": posture.git_available,
        "is_worktree": posture.is_worktree,
        "state": posture.state,
        "top_level": posture.top_level or "",
        "changed_count": posture.changed_count,
        "changed_paths": [{"status": item.status, "path": item.path} for item in posture.changed_paths],
        "detail": posture.detail or "",
    }


def _forbidden_write_scope_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    forbidden: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/").strip().rstrip("/")
        if not normalized:
            continue
        if normalized in TASK_SESSION_RECEIPT_FORBIDDEN_WRITE_PATHS:
            forbidden.append(path)
            continue
        prefix = normalized + "/"
        if any(prefix.startswith(forbidden_path + "/") for forbidden_path in TASK_SESSION_RECEIPT_FORBIDDEN_WRITE_PATHS):
            forbidden.append(path)
    return tuple(dict.fromkeys(forbidden))


def _forbidden_receipt_routes(routes: tuple[str, ...]) -> tuple[str, ...]:
    forbidden: list[str] = []
    for route in routes:
        command = route.strip().split(None, 1)[0].casefold() if route.strip() else ""
        if command in TASK_SESSION_RECEIPT_FORBIDDEN_ROUTES:
            forbidden.append(route)
    return tuple(dict.fromkeys(forbidden))


def _tuple_values(value: object, *, path_like: bool = True) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = [str(item) for item in value]
    else:
        values = [str(value)]
    result = []
    for item in values:
        text = item.strip()
        if not text:
            continue
        result.append(text.replace("\\", "/") if path_like else text)
    return tuple(dict.fromkeys(result))


def _json_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _hash_or_missing(text: str | None) -> str:
    if text is None:
        return "missing"
    return _short_hash(text)


def _bytes_or_missing(text: str | None) -> str:
    if text is None:
        return "missing"
    return str(len(text.encode("utf-8")))


def _root_id(root: Path) -> str:
    name = root.name.strip()
    return name or "root"


def _subparsers_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None
