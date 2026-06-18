from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from .adapter import (
    APPROVAL_RELAY_TARGET,
    MCP_READ_PROJECTION_TARGET,
    approval_relay_client_config,
    approval_relay_sections,
    codex_mcp_install_sections,
    mcp_read_projection_client_config,
    mcp_read_projection_sections,
    serve_mcp_read_projection,
)
from .agent_roles import role_manifest
from .approval_packets import (
    approval_packet_apply_findings,
    approval_packet_dry_run_findings,
    make_approval_packet_request,
)
from .attachments import (
    attachment_import_apply_findings,
    attachment_import_dry_run_findings,
    make_attachment_import_request,
)
from .bootstrap import bootstrap_sections, package_smoke_sections
from .checks import (
    archive_context_findings,
    attach_apply_findings,
    attach_dry_run_findings,
    audit_link_findings,
    check_drift_findings,
    cleanup_apply_findings,
    cleanup_dry_run_findings,
    command_surface_findings,
    command_surface_manifest,
    coordination_evidence_identity_findings,
    context_budget_findings,
    doctor_findings,
    external_orchestrator_shell_preflight_findings,
    flatten_sections,
    intelligence_sections,
    intelligence_route_sections,
    intake_apply_findings,
    intake_dry_run_findings,
    load_for_root,
    make_cleanup_request,
    make_intake_request,
    migrate_apply_findings,
    migrate_dry_run_findings,
    projection_cache_status_findings,
    detach_apply_sections,
    repair_apply_findings,
    repair_dry_run_findings,
    route_reference_inventory_findings,
    snapshot_inspect_findings,
    status_findings,
    detach_dry_run_sections,
    validation_findings,
)
from .claims import (
    make_work_claim_request,
    work_claim_apply_findings,
    work_claim_dry_run_findings,
    work_claim_status_findings,
)
from .closeout import closeout_sections
from .command_discovery import (
    command_intent_registry,
    command_suggestion_boundary_findings,
    command_suggestion_findings,
    command_suggestions_for_intent,
    command_suggestions_to_dict,
    rails_not_cognition_boundary_finding,
)
from .context_memory import CONTEXT_MEMORY_DIR_REL, CONTEXT_MEMORY_LATEST_REL, refresh_context_memory_capsule
from .dashboard import dashboard_payload, dashboard_sections
from .daemon import mlhd_control_payload, mlhd_control_sections
from .evidence import (
    agent_run_record_apply_findings,
    agent_run_record_dry_run_findings,
    agent_run_record_findings,
    evidence_findings,
    make_agent_run_record_request,
)
from .retention import (
    make_retention_request,
    retention_apply_findings,
    retention_dry_run_findings,
    retention_receipt_findings,
    retention_scan_sections,
)
from .incubate import (
    incubate_apply_findings,
    incubate_dry_run_findings,
    incubation_reconcile_apply_findings,
    incubation_reconcile_dry_run_findings,
    make_incubate_request,
    make_incubation_reconcile_request,
)
from .grain import grain_findings
from .handoff import (
    dispatcher_launch_status_findings,
    handoff_packet_apply_findings,
    handoff_packet_dry_run_findings,
    handoff_packet_status_findings,
    make_handoff_packet_request,
)
from .hooks import (
    codex_hook_adapter_apply_findings,
    codex_hook_adapter_dry_run_findings,
    hook_event_payload,
    hook_install_apply_findings,
    hook_install_dry_run_findings,
    hook_run_sections,
    hooks_doctor_sections,
    make_codex_hook_adapter_request,
    make_hook_install_request,
)
from .inventory import RootLoadError
from .lifecycle_focus import session_active_work_findings
from .meta_feedback import (
    META_FEEDBACK_ENABLE_ENV_VAR,
    META_FEEDBACK_ROOT_ENV_VAR,
    is_central_meta_feedback_inventory,
    make_meta_feedback_request,
    meta_feedback_cli_enabled,
    meta_feedback_env_destination_root,
    meta_feedback_apply_findings,
    meta_feedback_dry_run_findings,
)
from .memory_hygiene import (
    make_memory_hygiene_request,
    memory_hygiene_apply_findings,
    memory_hygiene_dry_run_findings,
)
from .models import Finding
from .parsing import extract_headings, extract_path_refs, parse_frontmatter
from .planning import (
    make_plan_cancel_request,
    make_plan_request,
    plan_apply_findings,
    plan_cancel_apply_findings,
    plan_cancel_dry_run_findings,
    plan_dry_run_findings,
    resolve_plan_request_from_roadmap,
)
from .projection_artifacts import (
    ARTIFACT_DIR_REL,
    build_projection_artifacts,
    delete_projection_artifacts,
    inspect_projection_artifacts,
    mark_projection_cache_dirty,
    rebuild_projection_artifacts,
    warm_projection_artifacts,
)
from .projection_index import (
    build_projection_index,
    delete_projection_index,
    inspect_projection_index,
    rebuild_projection_index,
    warm_projection_index,
)
from .preflight import orchestrator_workspace_preflight_sections, preflight_sections, render_git_pre_commit_template
from .vcs import dispatcher_worktree_coordination_findings, worktree_coordination_findings
from .reconcile import reconcile_findings
from .reporting import emit_text, render_intelligence_report, render_json_report, render_quick_check_report, render_report, render_sectioned_report
from .root_boundary import PRODUCT_SOURCE_FIXTURE
from .relationship_drift import (
    make_relationship_drift_request,
    relationship_drift_apply_findings,
    relationship_drift_dry_run_findings,
)
from .research_compare import make_research_compare_request, research_compare_apply_findings, research_compare_dry_run_findings
from .research_distill import make_research_distill_request, research_distill_apply_findings, research_distill_dry_run_findings
from .research_intake import (
    discovery_packet_apply_findings,
    discovery_packet_dry_run_findings,
    make_discovery_packet_request,
    make_research_import_request,
    research_import_apply_findings,
    research_import_dry_run_findings,
)
from .review_tokens import make_review_token_request, review_token_findings
from .routes import route_manifest
from .roadmap import (
    make_roadmap_request,
    roadmap_batch_apply_findings,
    roadmap_batch_dry_run_findings,
    roadmap_apply_findings,
    roadmap_dry_run_findings,
    roadmap_item_fields,
    roadmap_normalize_apply_findings,
    roadmap_normalize_dry_run_findings,
    roadmap_plan_deliverable_class_blockers,
    roadmap_plan_deliverable_class_next_safe_command,
    roadmap_plan_scope_blockers,
    roadmap_plan_scope_next_safe_command,
)
from .semantic import semantic_evaluate_sections, semantic_inspect_sections
from .tasks import tasks_sections
from .task_session import (
    make_task_session_receipt_request,
    register_task_session_parser,
    task_session_conductor_payload,
    task_session_conductor_sections,
    task_session_fan_in_payload,
    task_session_fan_in_sections,
    task_session_payload,
    task_session_receipt_apply_findings,
    task_session_receipt_dry_run_findings,
    task_session_sections,
)
from .writeback import make_writeback_request, writeback_apply_findings, writeback_dry_run_findings
from .cli_parser import build_parser


COMMANDS = (
    "init",
    "check",
    "suggest",
    "manifest",
    "migrate",
    "dashboard",
    "mlhd",
    "repair",
    "detach",
    "status",
    "validate",
    "context-budget",
    "audit-links",
    "doctor",
    "preflight",
    "hooks",
    "tasks",
    "task-session",
    "bootstrap",
    "semantic",
    "intelligence",
    "evidence",
    "claim",
    "handoff",
    "approval-packet",
    "review-token",
    "reconcile",
    "closeout",
    "intake",
    "discover",
    "attachment-import",
    "research-import",
    "research-distill",
    "research-compare",
    "incubate",
    "incubation-reconcile",
    "plan",
    "plan-cancel",
    "writeback",
    "transition",
    "memory-hygiene",
    "relationship-drift",
    "cleanup",
    "roadmap",
    "meta-feedback",
    "projection",
    "snapshot",
    "attach",
    "adapter",
)
CACHE_DIRTY_APPLY_COMMANDS = {
    "evidence",
    "retention",
    "task-session",
    "claim",
    "handoff",
    "approval-packet",
    "incubate",
    "incubation-reconcile",
    "intake",
    "discover",
    "attachment-import",
    "memory-hygiene",
    "relationship-drift",
    "meta-feedback",
    "migrate",
    "plan",
    "plan-cancel",
    "research-compare",
    "research-import",
    "research-distill",
    "repair",
    "roadmap",
    "transition",
    "writeback",
    "cleanup",
}


@dataclass(frozen=True)
class LifecyclePosture:
    plan_status: str
    active_plan: str
    active_phase: str
    phase_status: str
    active_plan_exists: bool
    active_plan_hash: str


@dataclass(frozen=True)
class TransitionRouteWriteEntry:
    rel_path: str
    operation: str
    code: str


_TRANSITION_ROUTE_WRITE_RE = re.compile(r"^(?:would )?(create|write|delete|created|wrote|deleted) route ([^;]+);")


def _normalize_argv(argv: list[str] | None) -> list[str]:
    raw = sys.argv[1:] if argv is None else list(argv)
    normalized: list[str] = []
    i = 0
    while i < len(raw):
        token = raw[i]
        normalized.append(token)
        if token == "--root" and i + 1 < len(raw):
            i += 1
            normalized.append(raw[i])
        elif token == "hooks" and i + 1 < len(raw) and raw[i + 1] == "adapter":
            normalized.append("--adapter")
            i += 1
        i += 1
    return normalized


def _known_option_strings(parser: argparse.ArgumentParser) -> set[str]:
    known: set[str] = set()
    pending = [parser]
    while pending:
        current = pending.pop()
        for action in current._actions:
            known.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                pending.extend(action.choices.values())
    return known


def _underscore_option_typo_hint(argv: list[str], parser: argparse.ArgumentParser) -> tuple[str, str] | None:
    known_options = _known_option_strings(parser)
    for token in argv:
        option = token.split("=", 1)[0]
        if not option.startswith("--") or "_" not in option:
            continue
        dashed = option.replace("_", "-")
        if option not in known_options and dashed in known_options:
            return option, dashed
    return None




def main(argv: list[str] | None = None) -> int:
    argv = _normalize_argv(argv)
    parser = build_parser()
    register_task_session_parser(parser)
    option_hint = _underscore_option_typo_hint(argv, parser)
    if option_hint is not None:
        unknown, suggested = option_hint
        parser.error(f"unknown option {unknown}; did you mean {suggested}?")
    args = parser.parse_args(argv)
    if args.command == "adapter":
        if not args.serve and args.transport is not None:
            parser.error("--transport is only valid with adapter --serve")
        if args.serve and args.transport != "stdio":
            parser.error("adapter --serve requires --transport stdio")
        if args.serve and args.target != MCP_READ_PROJECTION_TARGET:
            parser.error("adapter --serve is only supported for --target mcp-read-projection")
        if args.install_client_config and args.target != MCP_READ_PROJECTION_TARGET:
            parser.error("adapter --install-client-config is only supported for --target mcp-read-projection")
        if args.install_client_config and not (args.dry_run or args.apply):
            parser.error("adapter --install-client-config requires --dry-run or --apply")
        if not args.install_client_config and (args.dry_run or args.apply):
            parser.error("adapter --dry-run/--apply are only valid with --install-client-config")
        if args.apply and args.dry_run:
            parser.error("adapter --dry-run and --apply are mutually exclusive")
        if args.config_path and not (args.client_config or args.install_client_config):
            parser.error("adapter --config-path is only valid with --client-config or --install-client-config")
        if args.target == APPROVAL_RELAY_TARGET and args.config_path:
            parser.error("adapter --config-path is only supported for --target mcp-read-projection")
        if args.target != APPROVAL_RELAY_TARGET and (args.approval_packet_refs or args.relay_channel != "manual" or args.relay_recipient):
            parser.error("--approval-packet-ref and --relay-* are only valid with adapter --target approval-relay")
    if args.command == "meta-feedback" and not meta_feedback_cli_enabled():
        parser.error(
            "meta-feedback is disabled by default for product users; set "
            f"{META_FEEDBACK_ENABLE_ENV_VAR}=1 or {META_FEEDBACK_ROOT_ENV_VAR}=<central-root> for local developer use"
        )
    if args.command == "hooks":
        hooks_adapter = bool(getattr(args, "adapter", False) or getattr(args, "client", None))
        if getattr(args, "json", False) and not getattr(args, "run", None):
            parser.error("hooks --json is only valid with --run")
        if hooks_adapter:
            if not (getattr(args, "dry_run", False) or getattr(args, "apply", False)):
                parser.error("hooks adapter requires --dry-run or --apply")
            if getattr(args, "doctor", False) or getattr(args, "run", None):
                parser.error("hooks adapter is only valid with --dry-run or --apply")
            if getattr(args, "force", False):
                parser.error("hooks --force is only valid for local Git hook shim installation")
        elif getattr(args, "config_path", None):
            parser.error("hooks --config-path is only valid with hooks adapter")
    if args.command == "adapter" and args.serve and args.root is None:
        return serve_mcp_read_projection(None, sys.stdin, sys.stdout)

    root = Path(args.root or ".").expanduser()
    try:
        inventory = load_for_root(root)
    except RootLoadError as exc:
        emit_text(f"mylittleharness: {exc}", stream=sys.stderr)
        return 2

    command = args.command
    if command == "suggest":
        suggestions = command_intent_registry() if args.list else command_suggestions_for_intent(args.intent, args.limit)
        context_pack_findings = _context_pack_suggestion_findings(args.intent, args.list)
        sections = [
            ("Command Suggestions", command_suggestion_findings(suggestions, intent=args.intent, list_all=args.list)),
        ]
        if context_pack_findings:
            sections.append(("Context Pack", context_pack_findings))
        sections.append(("Boundary", command_suggestion_boundary_findings()))
        findings = flatten_sections(sections)
        result = _result_for(findings)
        report_name = "suggest --list" if args.list else "suggest --intent"
        report_suggestions = _suggestions(command, findings)
        if args.json:
            emit_text(
                _render_suggest_json_report(
                    report_name,
                    inventory.root,
                    result,
                    inventory.sources_for_report(),
                    findings,
                    report_suggestions,
                    sections,
                    suggestions,
                    args.intent,
                    args.list,
                )
            )
        else:
            emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, report_suggestions))
        return 0
    if command == "manifest":
        route_findings = _route_manifest_findings()
        role_findings = _agent_role_manifest_findings()
        command_surface_report_findings = command_surface_findings()
        findings = [*route_findings, *role_findings, *command_surface_report_findings]
        result = _result_for(findings)
        report_name = "manifest --inspect"
        sections = [
            ("Route Manifest", route_findings),
            ("Role Profiles", role_findings),
            ("Command Surface", command_surface_report_findings),
        ]
        suggestions = _suggestions(command, findings)
        manifest_rows = route_manifest()
        role_rows = role_manifest()
        command_surface_rows = command_surface_manifest()
        if args.json:
            emit_text(
                _render_manifest_json_report(
                    report_name,
                    inventory.root,
                    result,
                    inventory.sources_for_report(),
                    findings,
                    suggestions,
                    sections,
                    manifest_rows,
                    role_rows,
                    command_surface_rows,
                )
            )
        else:
            emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, suggestions))
        return 0
    if command == "migrate":
        report_name = "migrate --apply" if args.apply else "migrate --dry-run"
        findings = migrate_apply_findings(inventory) if args.apply else migrate_dry_run_findings(inventory)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "dashboard":
        detail = str(getattr(args, "detail", "auto") or "auto")
        if args.json:
            payload = dashboard_payload(inventory, detail=detail)
            emit_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True))
            error = any(
                finding.get("severity") == "error"
                for section in payload.get("sections", [])
                if isinstance(section, dict)
                for finding in section.get("findings", [])
                if isinstance(finding, dict)
            )
            return 1 if error else 0
        sections = dashboard_sections(inventory, detail=detail)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        suggestions = _suggestions(command, findings)
        emit_text(render_sectioned_report("dashboard --inspect", inventory.root, result, inventory.sources_for_report(), sections, suggestions))
        return 1 if any(finding.severity == "error" for finding in findings) else 0
    if command == "mlhd":
        action = str(getattr(args, "mlhd_action", "") or "status")
        dry_run = bool(getattr(args, "dry_run", False))
        apply = bool(getattr(args, "apply", False))
        quiet_period_seconds = float(getattr(args, "quiet_period_seconds", 1.0))
        sections = mlhd_control_sections(
            inventory,
            action,
            dry_run=dry_run,
            apply=apply,
            quiet_period_seconds=quiet_period_seconds,
        )
        findings = flatten_sections(sections)
        result = _result_for(findings)
        suggestions = _suggestions(command, findings)
        if getattr(args, "json", False):
            payload = mlhd_control_payload(
                inventory,
                action,
                dry_run=dry_run,
                apply=apply,
                quiet_period_seconds=quiet_period_seconds,
            )
            payload["result"] = {"status": result}
            payload["findings"] = [finding.to_dict() for finding in findings]
            emit_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True))
        else:
            emit_text(render_sectioned_report(f"mlhd {action}", inventory.root, result, inventory.sources_for_report(), sections, suggestions))
        return 1 if any(finding.severity == "error" for finding in findings) else 0
    if command == "check":
        report_name, sections = _check_report(args, inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        suggestions = _suggestions(command, findings)
        if args.json:
            payload = json.loads(
                render_json_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, suggestions, sections, route_manifest())
            )
            if args.focus:
                payload["report_scope"] = _focused_report_scope(args.focus, sections)
            if getattr(args, "quick", False):
                payload["report_scope"] = _quick_report_scope(sections)
            emit_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
        elif getattr(args, "quick", False):
            emit_text(render_quick_check_report(inventory.root, result, inventory.sources_for_report(), sections, suggestions))
        else:
            emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, suggestions))
        return 1 if any(finding.severity == "error" for finding in findings) else 0
    if command == "detach":
        report_name = "detach --dry-run"
        if args.apply:
            sections = detach_apply_sections(inventory)
            report_name = "detach --apply"
        else:
            sections = detach_dry_run_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "status":
        findings = status_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("status", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "validate":
        findings = validation_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("validate", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 1 if any(finding.severity == "error" for finding in findings) else 0
    if command == "context-budget":
        findings = context_budget_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("context-budget", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "audit-links":
        findings = audit_link_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("audit-links", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "doctor":
        integration = getattr(args, "integration", None)
        findings = doctor_findings(inventory.root, inventory, integration=integration)
        result = _result_for(findings)
        report_name = f"doctor --integration {integration}" if integration else "doctor"
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "preflight":
        if args.template == "git-pre-commit":
            emit_text(render_git_pre_commit_template(inventory.root))
            return 0
        if args.orchestrator_workspace:
            sections = orchestrator_workspace_preflight_sections(inventory, args.orchestrator_workspace, args.product_root or "")
            sections.append(
                (
                    "External Orchestrator Capability",
                    external_orchestrator_shell_preflight_findings(inventory, args.orchestrator_workspace, args.product_root or ""),
                )
            )
            report_name = "preflight --orchestrator-workspace"
        else:
            sections = preflight_sections(inventory)
            report_name = "preflight"
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command == "hooks":
        hooks_adapter = bool(getattr(args, "adapter", False) or getattr(args, "client", None))
        if getattr(args, "input_file", None) and not getattr(args, "run", None):
            emit_text("mylittleharness: --input-file is valid only with hooks --run", stream=sys.stderr)
            return 2
        if args.doctor:
            sections = hooks_doctor_sections(inventory)
            findings = flatten_sections(sections)
            result = _result_for(findings)
            emit_text(render_sectioned_report("hooks --doctor", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
            return 0
        if args.run:
            hook_input_text = ""
            if getattr(args, "input_file", None):
                hook_input_text, read_error = _read_text_argument("--input-file", args.input_file)
                if read_error:
                    emit_text(f"mylittleharness: {read_error}", stream=sys.stderr)
                    return 2
                hook_input_text = hook_input_text or ""
            sections = hook_run_sections(inventory, args.run, args.hook_args, hook_input_text)
            findings = flatten_sections(sections)
            result = _result_for(findings)
            if args.json:
                emit_text(json.dumps(hook_event_payload(inventory, args.run, args.hook_args, hook_input_text), sort_keys=True, indent=2, ensure_ascii=True))
                return 1 if any(finding.severity == "error" for finding in findings) else 0
            emit_text(render_sectioned_report(f"hooks --run {args.run}", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
            return 0
        if hooks_adapter:
            request = make_codex_hook_adapter_request(args)
            report_name = "hooks adapter --apply" if args.apply else "hooks adapter --dry-run"
            findings = codex_hook_adapter_apply_findings(inventory, request) if args.apply else codex_hook_adapter_dry_run_findings(inventory, request)
            result = _result_for(findings)
            emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
            return 2 if args.apply and result == "error" else 0
        request = make_hook_install_request(args)
        report_name = "hooks --apply" if args.apply else "hooks --dry-run"
        findings = hook_install_apply_findings(inventory, request) if args.apply else hook_install_dry_run_findings(inventory, request)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "tasks":
        sections = tasks_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report("tasks --inspect", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command == "task-session":
        if args.inspect:
            fan_in = bool(getattr(args, "fan_in", False))
            conductor = bool(getattr(args, "conductor", False))
            provider_launcher = bool(getattr(args, "provider_launcher", False))
            if fan_in and conductor:
                parser.error("task-session --fan-in and --conductor cannot be combined")
            if provider_launcher and not conductor:
                parser.error("task-session --provider-launcher is only valid with --inspect --conductor")
            sections = (
                task_session_conductor_sections(inventory, include_provider_launcher=provider_launcher)
                if conductor
                else task_session_fan_in_sections(inventory) if fan_in else task_session_sections(inventory)
            )
            findings = flatten_sections(sections)
            result = _result_for(findings)
            suggestions = _suggestions(command, findings)
            report_name = (
                "task-session --inspect --conductor --provider-launcher"
                if conductor and provider_launcher
                else "task-session --inspect --conductor"
                if conductor
                else "task-session --inspect --fan-in" if fan_in else "task-session --inspect"
            )
            if args.json:
                payload = (
                    task_session_conductor_payload(inventory, sections, include_provider_launcher=provider_launcher)
                    if conductor
                    else task_session_fan_in_payload(inventory, sections) if fan_in else task_session_payload(inventory, sections)
                )
                emit_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True))
            else:
                emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, suggestions))
            return 1 if any(finding.severity == "error" for finding in findings) else 0
        if getattr(args, "fan_in", False):
            parser.error("task-session --fan-in is only valid with --inspect")
        if getattr(args, "conductor", False):
            parser.error("task-session --conductor is only valid with --inspect")
        if getattr(args, "provider_launcher", False):
            parser.error("task-session --provider-launcher is only valid with --inspect --conductor")
        if args.json:
            parser.error("task-session --json is only valid with --inspect")
        request = make_task_session_receipt_request(args)
        report_name = "task-session --apply" if args.apply else "task-session --dry-run"
        findings = task_session_receipt_apply_findings(inventory, request) if args.apply else task_session_receipt_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "bootstrap":
        if args.package_smoke:
            sections = package_smoke_sections(inventory)
            report_name = "bootstrap --package-smoke"
        else:
            sections = bootstrap_sections(inventory)
            report_name = "bootstrap --inspect"
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 1 if args.package_smoke and result == "error" else 0
    if command == "semantic":
        if args.evaluate:
            sections = semantic_evaluate_sections(inventory)
            report_name = "semantic --evaluate"
        else:
            sections = semantic_inspect_sections(inventory)
            report_name = "semantic --inspect"
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command == "intelligence":
        sections = (
            intelligence_route_sections(inventory)
            if args.focus == "routes"
            else intelligence_sections(inventory, args.search, args.path, args.full_text, args.limit, args.query, focus=args.focus)
        )
        findings = flatten_sections(sections)
        result = _result_for(findings)
        display_sections = _focused_intelligence_sections(sections, args.focus)
        emit_text(
            render_intelligence_report(
                inventory.root,
                result,
                inventory.sources_for_report(),
                display_sections,
                _suggestions(command, findings),
                compact_sources=args.focus is not None,
            )
        )
        return 0
    if command == "evidence":
        if args.record and not (args.dry_run or args.apply):
            parser.error("evidence --record requires --dry-run or --apply")
        if (args.dry_run or args.apply) and not args.record:
            parser.error("evidence --dry-run/--apply are only valid with --record")
        if args.record:
            request = make_agent_run_record_request(args)
            report_name = "evidence --record --apply" if args.apply else "evidence --record --dry-run"
            findings = agent_run_record_apply_findings(inventory, request) if args.apply else agent_run_record_dry_run_findings(inventory, request)
            findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
            result = _result_for(findings)
            emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
            return 2 if args.apply and result == "error" else 0
        findings = evidence_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("evidence", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "retention":
        request = make_retention_request(args)
        action = str(getattr(args, "retention_action", "") or "")
        if action == "scan":
            sections = retention_scan_sections(inventory, request)
            findings = flatten_sections(sections)
            result = _result_for(findings)
            suggestions = _suggestions(command, findings)
            if args.json:
                emit_text(render_json_report("retention scan", inventory.root, result, inventory.sources_for_report(), findings, suggestions, sections, route_manifest()))
            else:
                emit_text(render_sectioned_report("retention scan", inventory.root, result, inventory.sources_for_report(), sections, suggestions))
            return 1 if any(finding.severity == "error" for finding in findings) else 0
        report_name = f"retention {action} --apply" if args.apply else f"retention {action} --dry-run"
        findings = retention_apply_findings(inventory, request) if args.apply else retention_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        suggestions = _suggestions(command, findings)
        sections = [("Retention", findings)]
        if args.json:
            emit_text(render_json_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, suggestions, sections, route_manifest()))
        else:
            emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, suggestions))
        return 2 if args.apply and result == "error" else 1 if result == "error" else 0
    if command == "claim":
        if args.status:
            findings = [
                *work_claim_status_findings(inventory),
                *coordination_evidence_identity_findings(inventory, "work-claim-identity", ("work-claim",)),
            ]
            result = _result_for(findings)
            suggestions = _suggestions(command, findings)
            if args.json:
                emit_text(render_json_report("claim --status", inventory.root, result, inventory.sources_for_report(), findings, suggestions, [("Work Claims", findings)], route_manifest()))
            else:
                emit_text(render_report("claim --status", inventory.root, result, inventory.sources_for_report(), findings, suggestions))
            return 1 if any(finding.severity == "error" for finding in findings) else 0
        request = make_work_claim_request(args)
        report_name = "claim --apply" if args.apply else "claim --dry-run"
        findings = work_claim_apply_findings(inventory, request) if args.apply else work_claim_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        suggestions = _suggestions(command, findings)
        if args.json:
            emit_text(render_json_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, suggestions, [("Work Claims", findings)], route_manifest()))
        else:
            emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, suggestions))
        return 2 if args.apply and result == "error" else 0
    if command == "handoff":
        if args.status:
            findings = [
                *handoff_packet_status_findings(inventory),
                *dispatcher_launch_status_findings(inventory),
                *dispatcher_worktree_coordination_findings(inventory),
                *coordination_evidence_identity_findings(inventory, "handoff-identity", ("handoff",)),
            ]
            result = _result_for(findings)
            emit_text(render_report("handoff --status", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
            return 1 if any(finding.severity == "error" for finding in findings) else 0
        request = make_handoff_packet_request(args)
        report_name = "handoff --apply" if args.apply else "handoff --dry-run"
        findings = handoff_packet_apply_findings(inventory, request) if args.apply else handoff_packet_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "approval-packet":
        request = make_approval_packet_request(args)
        report_name = "approval-packet --apply" if args.apply else "approval-packet --dry-run"
        findings = approval_packet_apply_findings(inventory, request) if args.apply else approval_packet_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "review-token":
        request = make_review_token_request(args)
        findings = review_token_findings(inventory, request)
        result = _result_for(findings)
        emit_text(render_report("review-token", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 1 if result == "error" else 0
    if command == "reconcile":
        findings = [
            *reconcile_findings(inventory),
            *coordination_evidence_identity_findings(inventory, "reconcile-coordination-evidence"),
        ]
        result = _result_for(findings)
        emit_text(render_report("reconcile", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 1 if result == "error" else 0
    if command == "closeout":
        sections = closeout_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report("closeout", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command == "intake":
        intake_text = args.text
        intake_source = "--text"
        if args.text_file is not None:
            text_result = _read_text_argument("--text-file", args.text_file)
            if text_result[1]:
                emit_text(f"mylittleharness: {text_result[1]}", stream=sys.stderr)
                return 2
            intake_text = text_result[0]
            intake_source = f"--text-file {args.text_file}"
        request = make_intake_request(intake_text, intake_source, args.title, args.target, args.status)
        report_name = "intake --apply" if args.apply else "intake --dry-run"
        findings = intake_apply_findings(inventory, request) if args.apply else intake_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "attachment-import":
        request = make_attachment_import_request(
            args.file,
            kind=args.kind,
            topic=args.topic,
            title=args.title,
            received_at=args.received_at,
            source_label=args.source_label,
            related_research=tuple(args.related_research or ()),
        )
        report_name = "attachment-import --apply" if args.apply else "attachment-import --dry-run"
        findings = attachment_import_apply_findings(inventory, request) if args.apply else attachment_import_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "research-import":
        research_text = args.text
        text_source = "--text"
        input_path = ""
        if args.text_file is not None:
            text_result = _read_text_argument("--text-file", args.text_file)
            if text_result[1]:
                emit_text(f"mylittleharness: {text_result[1]}", stream=sys.stderr)
                return 2
            research_text = text_result[0]
            text_source = f"--text-file {args.text_file}"
            input_path = args.text_file
        elif args.from_attachment is not None:
            research_text = ""
            text_source = f"--from-attachment {args.from_attachment}"
        request = make_research_import_request(
            args.title,
            research_text,
            text_source=text_source,
            target=args.target,
            topic=args.topic,
            source_label=args.source_label,
            related_prompt=args.related_prompt,
            input_path=input_path,
            source_attachment=args.from_attachment,
        )
        report_name = "research-import --apply" if args.apply else "research-import --dry-run"
        findings = research_import_apply_findings(inventory, request) if args.apply else research_import_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "discover":
        request = make_discovery_packet_request(
            args.topic,
            goal=args.goal,
            target=args.target,
            packet_id=args.packet_id,
            quality_status=args.quality_status,
            planning_reliance=args.planning_reliance,
            discovery_status=args.discovery_status,
            source_refs=args.source_refs,
            source_members=args.source_members,
            evidence_refs=args.evidence_refs,
            selected_option=args.selected_option,
            rationale=args.rationale,
            open_questions=args.open_questions,
            stop_conditions=args.stop_conditions,
        )
        report_name = "discover --apply" if args.apply else "discover --dry-run"
        findings = discovery_packet_apply_findings(inventory, request) if args.apply else discovery_packet_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "research-distill":
        request = make_research_distill_request(
            args.source,
            title=args.title,
            target=args.target,
            topic=args.topic,
        )
        report_name = "research-distill --apply" if args.apply else "research-distill --dry-run"
        findings = research_distill_apply_findings(inventory, request) if args.apply else research_distill_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "research-compare":
        request = make_research_compare_request(
            args.sources,
            title=args.title,
            target=args.target,
            topic=args.topic,
            archive_sources=args.archive_sources,
            repair_links=args.repair_links,
        )
        report_name = "research-compare --apply" if args.apply else "research-compare --dry-run"
        findings = research_compare_apply_findings(inventory, request) if args.apply else research_compare_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "writeback":
        request = make_writeback_request(
            archive_active_plan=args.archive_active_plan,
            compact_only=args.compact_only,
            allow_auto_compaction=args.allow_auto_compaction,
            source_hash=args.source_hash,
            from_active_plan=args.from_active_plan,
            roadmap_item=args.roadmap_item,
            roadmap_status=args.roadmap_status,
            archived_plan=args.archived_plan,
            archive_collision_policy=args.archive_collision_policy,
            worktree_start_state=args.worktree_start_state,
            task_scope=args.task_scope,
            docs_decision=args.docs_decision,
            state_writeback=args.state_writeback,
            verification=args.verification,
            commit_decision=args.commit_decision,
            residual_risk=args.residual_risk,
            next_state=args.next_state,
            carry_forward=args.carry_forward,
            work_result=args.work_result,
            active_phase=args.active_phase,
            phase_status=args.phase_status,
            last_archived_plan=args.last_archived_plan,
            product_source_root=args.product_source_root,
        )
        report_name = "writeback --apply" if args.apply else "writeback --dry-run"
        if args.compact_only:
            report_name += " --compact-only"
        if args.allow_auto_compaction:
            report_name += " --allow-auto-compaction"
        findings = writeback_apply_findings(inventory, request) if args.apply else writeback_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "transition":
        report_name = "transition --apply" if args.apply else "transition --dry-run"
        if args.allow_auto_compaction:
            report_name += " --allow-auto-compaction"
        findings = _transition_apply_findings(inventory, args) if args.apply else _transition_dry_run_findings(inventory, args)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "plan":
        request = make_plan_request(args.title, args.objective, args.task, args.update_active, args.roadmap_item, args.only_requested_item)
        report_name = "plan --apply" if args.apply else "plan --dry-run"
        findings = plan_apply_findings(inventory, request) if args.apply else plan_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "plan-cancel":
        request = make_plan_cancel_request(args.roadmap_item, args.keep_plan, args.source_hash)
        report_name = "plan-cancel --apply" if args.apply else "plan-cancel --dry-run"
        findings = plan_cancel_apply_findings(inventory, request) if args.apply else plan_cancel_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "memory-hygiene":
        request = make_memory_hygiene_request(
            args.source,
            args.promoted_to,
            args.status,
            args.archive_to,
            args.repair_links,
            args.scan,
            args.archive_covered,
            tuple(args.entry_coverage),
            args.rotate_ledger,
            args.source_hash,
            args.reason,
            args.proposal_token,
            args.archive_list_file,
            args.archive_folder,
        )
        report_name = "memory-hygiene --apply" if args.apply else "memory-hygiene --dry-run"
        if args.scan:
            report_name += " --scan"
        if args.rotate_ledger:
            report_name += " --rotate-ledger"
        if args.archive_list_file or args.archive_folder:
            report_name += " --archive-list"
        findings = memory_hygiene_apply_findings(inventory, request) if args.apply else memory_hygiene_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "relationship-drift":
        request = make_relationship_drift_request(args.roadmap_item)
        report_name = "relationship-drift --apply" if args.apply else "relationship-drift --dry-run"
        findings = relationship_drift_apply_findings(inventory, request) if args.apply else relationship_drift_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "cleanup":
        request = make_cleanup_request(args.target, args.reason)
        report_name = "cleanup --apply" if args.apply else "cleanup --dry-run"
        findings = cleanup_apply_findings(inventory, request) if args.apply else cleanup_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "roadmap":
        normalize_requested = args.operation == "normalize" or args.action == "normalize"
        if normalize_requested:
            if args.operation == "normalize" and args.action not in (None, "normalize"):
                parser.error("roadmap normalize cannot be combined with --action add or --action update")
            if args.item_id or args.items_file or _roadmap_item_mutation_args_present(args):
                parser.error("roadmap normalize does not accept item mutation fields")
            report_name = "roadmap normalize --apply" if args.apply else "roadmap normalize --dry-run"
            findings = roadmap_normalize_apply_findings(inventory) if args.apply else roadmap_normalize_dry_run_findings(inventory)
            findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
            result = _result_for(findings)
            emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
            return 2 if args.apply and result == "error" else 0
        if not args.action:
            parser.error("roadmap requires --action add/update/add-many/update-many or the normalize operation")
        if args.action in {"add-many", "update-many"}:
            if not args.items_file:
                parser.error(f"roadmap --action {args.action} requires --items-file")
            if args.item_id or _roadmap_item_mutation_args_present(args):
                parser.error(f"roadmap --action {args.action} reads item fields from --items-file only")
            manifest_result = _read_text_argument("--items-file", args.items_file)
            if manifest_result[1]:
                emit_text(f"mylittleharness: {manifest_result[1]}", stream=sys.stderr)
                return 2
            report_name = f"roadmap {args.action} --apply" if args.apply else f"roadmap {args.action} --dry-run"
            findings = (
                roadmap_batch_apply_findings(inventory, manifest_result[0] or "", args.items_file, action=args.action)
                if args.apply
                else roadmap_batch_dry_run_findings(inventory, manifest_result[0] or "", args.items_file, action=args.action)
            )
            findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
            result = _result_for(findings)
            emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
            return 2 if args.apply and result == "error" else 0
        if args.items_file:
            parser.error("roadmap --items-file is valid only with --action add-many or --action update-many")
        if not args.item_id:
            parser.error("roadmap --action add/update requires --item-id")
        request = make_roadmap_request(
            action=args.action,
            item_id=args.item_id,
            title=args.title,
            status=args.status,
            stage=args.stage,
            order=args.order,
            execution_slice=args.execution_slice,
            slice_goal=args.slice_goal,
            slice_members=args.slice_members,
            slice_dependencies=args.slice_dependencies,
            slice_closeout_boundary=args.slice_closeout_boundary,
            source_incubation=args.source_incubation,
            source_research=args.source_research,
            source_members=args.source_members,
            related_specs=args.related_specs,
            related_plan=args.related_plan,
            archived_plan=args.archived_plan,
            target_artifacts=args.target_artifacts,
            verification_summary=args.verification_summary,
            docs_decision=args.docs_decision,
            carry_forward=args.carry_forward,
            dependencies=args.dependencies,
            supersedes=args.supersedes,
            superseded_by=args.superseded_by,
            clear_fields=args.clear_fields,
            custom_fields=args.custom_fields,
        )
        report_name = "roadmap --apply" if args.apply else "roadmap --dry-run"
        findings = roadmap_apply_findings(inventory, request) if args.apply else roadmap_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "meta-feedback":
        note_text = args.note
        note_source = "--note"
        if args.note_file is not None:
            note_result = _read_text_argument("--note-file", args.note_file)
            if note_result[1]:
                emit_text(f"mylittleharness: {note_result[1]}", stream=sys.stderr)
                return 2
            note_text = note_result[0]
            note_source = f"--note-file {args.note_file}"
        destination_inventory = inventory
        env_destination_root = meta_feedback_env_destination_root()
        destination_root = args.to_root or env_destination_root
        if destination_root:
            try:
                destination_inventory = load_for_root(Path(destination_root).expanduser())
            except RootLoadError as exc:
                emit_text(f"mylittleharness: {exc}", stream=sys.stderr)
                return 2
        request = make_meta_feedback_request(
            topic=args.topic,
            note=note_text,
            note_source=note_source,
            from_root=args.from_root or str(inventory.root),
            signal_type=args.signal_type,
            severity=args.severity,
            roadmap_item=args.roadmap_item,
            order=args.order,
            dedupe_to=args.dedupe_to,
            correction_of=args.correction_of,
            capture_mode="apply" if args.apply else "dry-run",
            requested_root=str(inventory.root),
            destination_root=str(destination_inventory.root),
            destination_source=_meta_feedback_destination_source(args.to_root, env_destination_root),
            env_destination_root=env_destination_root,
            to_root=args.to_root,
            hook_event=args.hook_event,
            tool_name=args.tool_name,
            blocked_surface=args.blocked_surface,
            intended_route=args.intended_route,
            legal_route_available=args.legal_route_available,
            next_safe_command=args.next_safe_command,
            hook_classification=args.hook_classification,
            false_positive_shape=args.false_positive_shape,
            false_negative_shape=args.false_negative_shape,
            output_suppression=args.output_suppression,
            partial_execution_risk=args.partial_execution_risk,
            suggested_policy_change=args.suggested_policy_change,
        )
        report_name = "meta-feedback --apply" if args.apply else "meta-feedback --dry-run"
        lifecycle_before = _lifecycle_posture(destination_inventory) if args.apply else None
        findings = (
            meta_feedback_apply_findings(destination_inventory, request)
            if args.apply
            else meta_feedback_dry_run_findings(destination_inventory, request)
        )
        findings = _meta_feedback_destination_selection_findings(
            requested_inventory=inventory,
            destination_root=destination_inventory.root,
            to_root=args.to_root,
            env_root=env_destination_root,
        ) + findings
        findings = _with_projection_cache_dirty_findings(command, args, destination_inventory, findings)
        if lifecycle_before and not any(finding.severity == "error" for finding in findings):
            lifecycle_after = _lifecycle_posture(load_for_root(destination_inventory.root))
            findings.extend(_meta_feedback_lifecycle_posture_findings(lifecycle_before, lifecycle_after))
        result = _result_for(findings)
        emit_text(
            render_report(
                report_name,
                destination_inventory.root,
                result,
                destination_inventory.sources_for_report(),
                findings,
                _suggestions(command, findings),
            )
        )
        return 2 if args.apply and result == "error" else 0
    if command == "incubate":
        note_text = args.note
        note_source = "--note"
        if args.note_file is not None:
            note_result = _read_text_argument("--note-file", args.note_file)
            if note_result[1]:
                emit_text(f"mylittleharness: {note_result[1]}", stream=sys.stderr)
                return 2
            note_text = note_result[0]
            note_source = f"--note-file {args.note_file}"
        request = make_incubate_request(args.topic, note_text, note_source, fix_candidate=args.fix_candidate)
        report_name = "incubate --apply" if args.apply else "incubate --dry-run"
        findings = incubate_apply_findings(inventory, request) if args.apply else incubate_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "incubation-reconcile":
        request = make_incubation_reconcile_request(args.sources, args.classes)
        report_name = "incubation-reconcile --apply" if args.apply else "incubation-reconcile --dry-run"
        findings = (
            incubation_reconcile_apply_findings(inventory, request)
            if args.apply
            else incubation_reconcile_dry_run_findings(inventory, request)
        )
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "projection":
        if not args.warm_cache and args.quiet_period_seconds:
            emit_text("mylittleharness: --quiet-period-seconds is only valid with projection --warm-cache", stream=sys.stderr)
            return 2
        report_name = f"projection --inspect --target {args.target}"
        if args.build:
            findings = _projection_target_findings(args.target, build_projection_artifacts, build_projection_index, inventory)
            report_name = f"projection --build --target {args.target}"
        elif args.delete:
            findings = _projection_target_findings(args.target, delete_projection_artifacts, delete_projection_index, inventory)
            report_name = f"projection --delete --target {args.target}"
        elif args.rebuild:
            findings = _projection_target_findings(args.target, rebuild_projection_artifacts, rebuild_projection_index, inventory)
            report_name = f"projection --rebuild --target {args.target}"
        elif args.warm_cache:
            findings = _projection_target_findings(
                args.target,
                lambda target_inventory: warm_projection_artifacts(target_inventory, quiet_period_seconds=args.quiet_period_seconds),
                lambda target_inventory: warm_projection_index(target_inventory, quiet_period_seconds=args.quiet_period_seconds),
                inventory,
            )
            report_name = f"projection --warm-cache --target {args.target}"
            if args.quiet_period_seconds:
                report_name = f"{report_name} --quiet-period-seconds {args.quiet_period_seconds:g}"
        else:
            findings = _projection_target_findings(args.target, inspect_projection_artifacts, inspect_projection_index, inventory)
        result = _result_for(findings)
        suggestions = _projection_suggestions(report_name, findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, suggestions))
        return 2 if any(finding.severity == "error" for finding in findings) else 0
    if command == "snapshot":
        findings = snapshot_inspect_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("snapshot --inspect", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "adapter":
        if args.serve:
            return serve_mcp_read_projection(inventory, sys.stdin, sys.stdout)
        if args.client_config:
            config = approval_relay_client_config(inventory) if args.target == APPROVAL_RELAY_TARGET else mcp_read_projection_client_config(inventory, codex_config_path=args.config_path)
            emit_text(json.dumps(config, sort_keys=True, indent=2, ensure_ascii=True))
            return 0
        if args.install_client_config:
            sections = codex_mcp_install_sections(inventory, codex_config_path=args.config_path, apply=args.apply)
            findings = flatten_sections(sections)
            result = _result_for(findings)
            report_name = f"adapter --install-client-config --target {args.target} {'--apply' if args.apply else '--dry-run'}"
            emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
            return 2 if args.apply and any(finding.severity == "error" for finding in findings) else 0
        if args.target == APPROVAL_RELAY_TARGET:
            sections = approval_relay_sections(
                inventory,
                tuple(args.approval_packet_refs),
                relay_channel=args.relay_channel,
                relay_recipient=args.relay_recipient,
            )
        else:
            sections = mcp_read_projection_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report(f"adapter --inspect --target {args.target}", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command in {"init", "attach"}:
        report_name = f"{command} --dry-run"
        if args.apply:
            findings = attach_apply_findings(inventory, args.project)
            report_name = f"{command} --apply"
        else:
            findings = attach_dry_run_findings(inventory, args.project)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "repair":
        report_name = "repair --dry-run"
        if args.apply:
            findings = repair_apply_findings(inventory)
            report_name = "repair --apply"
        else:
            findings = repair_dry_run_findings(inventory)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        if args.apply:
            return _repair_apply_exit_code(findings)
        return 0
    parser.error(f"unknown command: {command}")
    return 2


def _transition_dry_run_findings(inventory, args) -> list[Finding]:
    next_plan_resolution = _transition_next_plan_resolution(inventory, args)
    preview_findings = _transition_preview_delegate_findings(inventory, args, next_plan_resolution)
    preview_errors = _transition_preview_input_errors(preview_findings)
    review_payload = _transition_review_payload(inventory, args, next_plan_resolution, preview_findings)
    token = _transition_review_token_from_payload(review_payload)
    findings = [
        Finding("info", "transition-dry-run", "transition proposal only; no files were written"),
        Finding(
            "info",
            "transition-boundary",
            "transition composes explicit writeback and plan rails; dry-run output cannot approve closeout, archive, next-plan opening, stage, commit, rollback, or future mutations",
        ),
        Finding("info", "transition-review-token", f"review token: {token}"),
        Finding("info", "transition-targets", f"primary target files: {', '.join(_transition_target_rels(inventory, args)) or 'none'}"),
    ]
    findings.extend(_transition_review_token_input_findings(review_payload))
    if preview_errors:
        findings.extend(_with_severity(preview_errors, "warn"))
        findings.append(Finding("info", "transition-validation-posture", "dry-run refused before apply; fix refusal reasons and rerun transition --dry-run"))
        return findings
    findings.extend(preview_findings)
    findings.extend(_transition_effective_write_set_findings(inventory, args, findings))
    findings.append(Finding("info", "transition-validation-posture", "apply requires the same flags plus --review-token; token mismatch refuses before writes"))
    return findings


def _transition_apply_findings(inventory, args) -> list[Finding]:
    next_plan_resolution = _transition_next_plan_resolution(inventory, args)
    preview_findings = _transition_preview_delegate_findings(inventory, args, next_plan_resolution)
    review_payload = _transition_review_payload(inventory, args, next_plan_resolution, preview_findings)
    token = _transition_review_token_from_payload(review_payload)
    errors = _transition_input_errors(inventory, args, next_plan_resolution.request, apply=True)
    if args.review_token and args.review_token != token:
        errors.append(
            Finding(
                "error",
                "transition-review-token-mismatch",
                (
                    "--review-token does not match current repo-visible inputs; "
                    f"expected {token}; current input digests: {_transition_review_input_digest_summary(review_payload)}"
                ),
            )
        )
        errors.extend(_transition_review_token_input_findings(review_payload, current=True))
        errors.append(_transition_review_token_refresh_finding())
    if errors:
        return errors

    findings = [
        Finding("info", "transition-apply", "transition apply started"),
        Finding("info", "transition-review-token", f"accepted review token: {token}"),
        Finding("info", "transition-targets", f"primary target files: {', '.join(_transition_target_rels(inventory, args)) or 'none'}"),
        Finding("info", "transition-no-vcs", "transition does not stage, commit, push, or mutate Git state"),
    ]
    current = inventory
    completed_write_steps: list[str] = []
    if args.complete_current_phase:
        findings.append(Finding("info", "transition-step", "completing current phase through writeback --phase-status complete", "project/project-state.md"))
        step_findings = _transition_delegate_apply_findings(
            "phase-complete",
            "phase completion writeback",
            "project/project-state.md",
            lambda: writeback_apply_findings(current, _transition_phase_complete_request(args)),
        )
        findings.extend(step_findings)
        if any(finding.severity == "error" for finding in step_findings):
            findings.extend(_transition_partial_apply_recovery_findings(inventory, args, findings, completed_write_steps, "phase completion writeback"))
            return findings
        _transition_record_completed_write_step(completed_write_steps, "phase completion writeback", step_findings)
        current, reload_findings = _reload_transition_inventory(current)
        findings.extend(reload_findings)
        if reload_findings:
            findings.extend(_transition_partial_apply_recovery_findings(inventory, args, findings, completed_write_steps, "post-phase reload"))
            return findings
    if args.archive_active_plan:
        findings.append(
            Finding(
                "info",
                "transition-step",
                f"archiving active plan through writeback --archive-active-plan with current roadmap status {_transition_current_roadmap_status(args)!r}",
                "project/implementation-plan.md",
            )
        )
        step_findings = _transition_delegate_apply_findings(
            "archive-active-plan",
            "active-plan archive writeback",
            "project/implementation-plan.md",
            lambda: writeback_apply_findings(current, _transition_archive_request(current, args)),
        )
        findings.extend(step_findings)
        if any(finding.severity == "error" for finding in step_findings):
            findings.extend(_transition_partial_apply_recovery_findings(inventory, args, findings, completed_write_steps, "active-plan archive writeback"))
            return findings
        _transition_record_completed_write_step(completed_write_steps, "active-plan archive writeback", step_findings)
        current, reload_findings = _reload_transition_inventory(current)
        findings.extend(reload_findings)
        if reload_findings:
            findings.extend(_transition_partial_apply_recovery_findings(inventory, args, findings, completed_write_steps, "post-archive reload"))
            return findings
    if args.next_roadmap_item:
        findings.append(Finding("info", "transition-step", f"opening next active plan for roadmap item {args.next_roadmap_item!r}", "project/implementation-plan.md"))
        current_next_plan_resolution = _transition_next_plan_resolution(current, args)
        findings.extend(_transition_next_plan_input_findings(current_next_plan_resolution, apply=True))
        step_findings = _transition_delegate_apply_findings(
            "next-plan",
            "next active-plan opening",
            "project/implementation-plan.md",
            lambda: plan_apply_findings(current, _transition_next_plan_request(args)),
        )
        findings.extend(step_findings)
        if any(finding.severity == "error" for finding in step_findings):
            findings.extend(_transition_partial_apply_recovery_findings(inventory, args, findings, completed_write_steps, "next active-plan opening"))
            return findings
        _transition_record_completed_write_step(completed_write_steps, "next active-plan opening", step_findings)
        current, reload_findings = _reload_transition_inventory(current)
        findings.extend(reload_findings)
        if reload_findings:
            findings.extend(_transition_partial_apply_recovery_findings(inventory, args, findings, completed_write_steps, "post-next-plan reload"))
            return findings
        findings.append(Finding("info", "transition-step", f"marking next roadmap item {args.next_roadmap_item!r} active", "project/roadmap.md"))
        step_findings = _transition_delegate_apply_findings(
            "next-roadmap",
            "next roadmap status update",
            "project/roadmap.md",
            lambda: roadmap_apply_findings(current, _transition_next_roadmap_status_request(args)),
        )
        findings.extend(step_findings)
        if any(finding.severity == "error" for finding in step_findings):
            findings.extend(_transition_partial_apply_recovery_findings(inventory, args, findings, completed_write_steps, "next roadmap status update"))
            return findings
        _transition_record_completed_write_step(completed_write_steps, "next roadmap status update", step_findings)
    findings.extend(_transition_effective_write_set_findings(inventory, args, findings))
    findings.append(
        Finding(
            "info",
            "transition-authority",
            "repo-visible project-state, archived plan, active plan, and roadmap files remain the only transition authority",
            "project/project-state.md",
        )
    )
    return findings


def _transition_delegate_apply_findings(step_code: str, step_label: str, source: str, callback) -> list[Finding]:
    try:
        return callback()
    except Exception as exc:
        return [
            Finding(
                "error",
                f"transition-{step_code}-failed-after-prior-write",
                f"transition delegate failed while running {step_label}: {type(exc).__name__}: {exc}",
                source,
            )
        ]


def _transition_record_completed_write_step(completed_steps: list[str], step_label: str, step_findings: list[Finding]) -> None:
    if _transition_route_write_entries(step_findings):
        completed_steps.append(step_label)


def _transition_partial_apply_recovery_findings(
    inventory,
    args,
    findings: list[Finding],
    completed_write_steps: list[str],
    failed_step: str,
) -> list[Finding]:
    recovery: list[Finding] = []
    recovery.extend(_transition_effective_write_set_findings(inventory, args, findings))
    if not completed_write_steps and not _transition_route_write_entries(findings):
        return recovery
    completed = ", ".join(completed_write_steps) if completed_write_steps else "route-write evidence above"
    recovery.append(
        Finding(
            "error",
            "transition-partial-apply-recovery",
            (
                f"partial transition apply: earlier delegated rail(s) already wrote repo-visible files ({completed}) before {failed_step} failed or was refused. "
                "Run `mylittleharness --root <root> check`, review the transition-effective-write-set evidence above, then rerun transition --dry-run from current repo-visible state; "
                "the previous review token must not be reused, and partial output does not approve archive, roadmap, next-plan, Git, or release decisions."
            ),
            "project/project-state.md",
        )
    )
    return recovery


def _transition_preview_delegate_findings(inventory, args, next_plan_resolution=None) -> list[Finding]:
    next_plan_resolution = next_plan_resolution or _transition_next_plan_resolution(inventory, args)
    errors = _transition_input_errors(inventory, args, next_plan_resolution.request, apply=False)
    if errors:
        return errors

    phase_completion_inventory = inventory
    phase_completion_preview_ok = True
    findings: list[Finding] = []
    if args.complete_current_phase:
        findings.append(Finding("info", "transition-step", "would complete current phase through writeback --phase-status complete", "project/project-state.md"))
        phase_findings = writeback_dry_run_findings(inventory, _transition_phase_complete_request(args))
        findings.extend(phase_findings)
        phase_completion_preview_ok = not any(finding.severity in {"warn", "error"} for finding in phase_findings)
        if phase_completion_preview_ok:
            phase_completion_inventory = _transition_phase_complete_preview_inventory(inventory)
    if args.archive_active_plan:
        findings.append(
            Finding(
                "info",
                "transition-step",
                f"would archive active plan through writeback --archive-active-plan with current roadmap status {_transition_current_roadmap_status(args)!r}",
                "project/implementation-plan.md",
            )
        )
        if args.complete_current_phase and _state_phase_status(inventory) != "complete":
            if phase_completion_preview_ok:
                findings.append(
                    Finding(
                        "info",
                        "transition-sequenced-preview",
                        "archive preview uses the projected phase-complete state, then reports archive-active-plan route writes without writing files",
                        "project/project-state.md",
                    )
                )
                findings.extend(writeback_dry_run_findings(phase_completion_inventory, _transition_archive_request(phase_completion_inventory, args)))
            else:
                findings.append(
                    Finding(
                        "info",
                        "transition-sequenced-preview",
                        "archive preview is sequenced after phase completion; phase-completion preview has warnings or errors, so detailed archive route-write evidence is deferred",
                        "project/project-state.md",
                    )
                )
        else:
            findings.extend(writeback_dry_run_findings(inventory, _transition_archive_request(inventory, args)))
    if args.next_roadmap_item:
        findings.append(Finding("info", "transition-step", f"would open next active plan for roadmap item {args.next_roadmap_item!r}", "project/implementation-plan.md"))
        findings.extend(_transition_next_plan_input_findings(next_plan_resolution, apply=False))
        if args.archive_active_plan and _state_plan_status(inventory) == "active":
            findings.append(
                Finding(
                    "info",
                    "transition-sequenced-preview",
                    "next-plan preview is sequenced after archive-active-plan clears the active lifecycle pointer",
                    "project/implementation-plan.md",
                )
            )
        else:
            findings.extend(plan_dry_run_findings(inventory, _transition_next_plan_request(args)))
        findings.append(Finding("info", "transition-step", f"would mark next roadmap item {args.next_roadmap_item!r} active", "project/roadmap.md"))
        findings.extend(roadmap_dry_run_findings(inventory, _transition_next_roadmap_status_request(args)))
    return findings


def _transition_preview_input_errors(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.code in {"transition-refused", "transition-next-plan-preflight-refused"}]


def _transition_effective_write_set_findings(inventory, args, findings: list[Finding]) -> list[Finding]:
    entries = _transition_route_write_entries(findings)
    summary_findings: list[Finding] = []
    if entries:
        summary_findings.append(
            Finding(
                "info",
                "transition-effective-write-set",
                f"effective route writes from delegated rails: {_transition_format_route_write_entries(entries)}",
                _transition_route_write_summary_source(entries),
            )
        )
        summary_findings.append(
            Finding(
                "info",
                "transition-targets-boundary",
                (
                    "transition-targets lists primary review surfaces; transition-effective-write-set summarizes delegated route-write evidence "
                    "from writeback, plan, and roadmap rails, including source-incubation, research, verification, decision, or ADR route metadata when those rails produce it"
                ),
                _transition_route_write_summary_source(entries),
            )
        )
    if args.archive_active_plan:
        archive_rel = _transition_archive_target_rel(inventory, args) or "project/archive/plans/<date>-<plan>.md"
        summary_findings.append(
            Finding(
                "info",
                "transition-active-plan-archive-alias",
                (
                    f"active-plan/archive alias semantics: project/implementation-plan.md is the live active-plan route; {archive_rel} is the durable archived-plan route. "
                    "Archive steps can create the archive route and delete the active-plan route; a same transition that opens a next plan can create project/implementation-plan.md again for the new plan."
                ),
                "project/implementation-plan.md",
            )
        )
    return summary_findings


def _transition_route_write_entries(findings: list[Finding]) -> tuple[TransitionRouteWriteEntry, ...]:
    entries: list[TransitionRouteWriteEntry] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        if finding.severity == "error" or not str(finding.code).endswith("-route-write"):
            continue
        match = _TRANSITION_ROUTE_WRITE_RE.match(str(finding.message or ""))
        if not match:
            continue
        operation, rel_path = match.groups()
        key = (rel_path, operation, finding.code)
        if key in seen:
            continue
        seen.add(key)
        entries.append(TransitionRouteWriteEntry(rel_path=rel_path, operation=operation, code=finding.code))
    return tuple(entries)


def _transition_format_route_write_entries(entries: tuple[TransitionRouteWriteEntry, ...]) -> str:
    grouped: dict[str, list[TransitionRouteWriteEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.rel_path, []).append(entry)
    return "; ".join(_transition_format_route_write_group(rel_path, route_entries) for rel_path, route_entries in grouped.items())


def _transition_format_route_write_group(rel_path: str, entries: list[TransitionRouteWriteEntry]) -> str:
    actions = ", ".join(f"{entry.operation} via {entry.code}" for entry in entries)
    disposition = _transition_route_write_final_disposition(rel_path, entries)
    return f"{rel_path}: {actions} ({disposition})"


def _transition_route_write_final_disposition(rel_path: str, entries: list[TransitionRouteWriteEntry]) -> str:
    final_state = _transition_route_write_final_state(entries)
    if rel_path != "project/implementation-plan.md":
        return f"final route: {final_state}"

    operation_kinds = {_transition_route_write_operation_kind(entry.operation) for entry in entries}
    if final_state == "present" and "delete" in operation_kinds:
        return "final route: present; active plan route recreated for next plan after archive"
    if final_state == "absent" and "write" in operation_kinds:
        return "final route: absent; active plan route archived/removed after interim write"
    if final_state == "absent":
        return "final route: absent; active plan route archived/removed"
    return f"final route: {final_state}"


def _transition_route_write_final_state(entries: list[TransitionRouteWriteEntry]) -> str:
    if not entries:
        return "unknown"
    return "absent" if _transition_route_write_operation_kind(entries[-1].operation) == "delete" else "present"


def _transition_route_write_operation_kind(operation: str) -> str:
    return "delete" if operation in {"delete", "deleted"} else "write"


def _transition_route_write_summary_source(entries: tuple[TransitionRouteWriteEntry, ...]) -> str | None:
    for entry in entries:
        if entry.rel_path == "project/project-state.md":
            return entry.rel_path
    return entries[0].rel_path if entries else None


def _transition_input_errors(inventory, args, next_plan_request, apply: bool) -> list[Finding]:
    errors: list[Finding] = []
    if not (args.complete_current_phase or args.archive_active_plan or args.next_roadmap_item):
        errors.append(Finding("error", "transition-refused", "transition requires at least one explicit action flag"))
    if apply and not args.review_token:
        errors.append(Finding("error", "transition-refused", "transition --apply requires --review-token from a matching dry-run"))
    if args.from_active_plan and not args.archive_active_plan:
        errors.append(Finding("error", "transition-refused", "--from-active-plan requires --archive-active-plan"))
    if args.current_roadmap_item and not args.archive_active_plan:
        errors.append(Finding("error", "transition-refused", "--current-roadmap-item requires --archive-active-plan"))
    current_roadmap_status = _transition_current_roadmap_status(args, default="")
    if current_roadmap_status and not args.archive_active_plan:
        errors.append(Finding("error", "transition-refused", "--current-roadmap-status requires --archive-active-plan"))
    if current_roadmap_status and not args.current_roadmap_item:
        errors.append(Finding("error", "transition-refused", "--current-roadmap-status requires --current-roadmap-item"))
    if current_roadmap_status in {"blocked", "superseded"} and args.complete_current_phase:
        errors.append(
            Finding(
                "error",
                "transition-refused",
                "--complete-current-phase cannot be combined with blocked or superseded current roadmap status",
            )
        )
    if args.only_requested_item and not args.next_roadmap_item:
        errors.append(Finding("error", "transition-refused", "--only-requested-item requires --next-roadmap-item"))
    if args.next_roadmap_item:
        if not next_plan_request.title:
            errors.append(Finding("error", "transition-refused", "--next-title is required when it cannot be derived from --next-roadmap-item"))
        if not next_plan_request.objective:
            errors.append(Finding("error", "transition-refused", "--next-objective is required when it cannot be derived from --next-roadmap-item"))
        errors.extend(_transition_next_plan_preflight_errors(inventory, args.next_roadmap_item))
        if _state_plan_status(inventory) == "active" and not args.archive_active_plan:
            errors.append(Finding("error", "transition-refused", "--next-roadmap-item with an active plan requires --archive-active-plan"))
    return errors


def _transition_next_plan_preflight_errors(inventory, next_roadmap_item: str) -> list[Finding]:
    errors: list[Finding] = []
    scope_next_safe_command = roadmap_plan_scope_next_safe_command(next_roadmap_item)
    for blocker in roadmap_plan_scope_blockers(inventory, next_roadmap_item):
        errors.append(
            Finding(
                "error",
                "transition-next-plan-preflight-refused",
                f"next plan would be refused before route writes: {blocker}; next_safe_command={scope_next_safe_command}",
                "project/" + "roadmap.md",
            )
        )
    deliverable_next_safe_command = roadmap_plan_deliverable_class_next_safe_command(next_roadmap_item)
    for blocker in roadmap_plan_deliverable_class_blockers(inventory, next_roadmap_item):
        errors.append(
            Finding(
                "error",
                "transition-next-plan-preflight-refused",
                f"next plan would be refused before route writes: {blocker}; next_safe_command={deliverable_next_safe_command}",
                "project/" + "roadmap.md",
            )
        )
    return errors


def _transition_archive_request(inventory, args):
    return make_writeback_request(
        archive_active_plan=True,
        allow_auto_compaction=args.allow_auto_compaction,
        from_active_plan=args.from_active_plan,
        roadmap_item=args.current_roadmap_item,
        roadmap_status=_transition_current_roadmap_status(args, default=""),
        archive_retarget_skip_rels=_transition_next_source_incubation_rels(inventory, args),
        archive_collision_policy=args.archive_collision_policy,
        worktree_start_state=args.worktree_start_state,
        task_scope=args.task_scope,
        docs_decision=args.docs_decision,
        state_writeback=args.state_writeback,
        verification=args.verification,
        commit_decision=args.commit_decision,
        residual_risk=args.residual_risk,
        next_state=args.next_state,
        carry_forward=args.carry_forward,
        work_result=args.work_result,
    )


def _transition_phase_complete_request(args):
    return make_writeback_request(
        allow_auto_compaction=args.allow_auto_compaction,
        from_active_plan=args.from_active_plan,
        worktree_start_state=args.worktree_start_state,
        task_scope=args.task_scope,
        docs_decision=args.docs_decision,
        state_writeback=args.state_writeback,
        verification=args.verification,
        commit_decision=args.commit_decision,
        residual_risk=args.residual_risk,
        next_state=args.next_state,
        carry_forward=args.carry_forward,
        work_result=args.work_result,
        phase_status="complete",
    )


def _transition_current_roadmap_status(args, default: str = "done") -> str:
    return str(getattr(args, "current_roadmap_status", None) or default)


def _transition_next_source_incubation_rels(inventory, args) -> tuple[str, ...]:
    if not args.next_roadmap_item:
        return ()
    fields = roadmap_item_fields(inventory, args.next_roadmap_item)
    source = str(fields.get("source_incubation") or "").strip().replace("\\", "/")
    return (source,) if source else ()


def _transition_next_plan_resolution(inventory, args):
    return resolve_plan_request_from_roadmap(inventory, _transition_next_plan_request(args))


def _transition_next_plan_request(args):
    return make_plan_request(
        args.next_title,
        args.next_objective,
        args.next_task,
        False,
        args.next_roadmap_item,
        args.only_requested_item,
    )


def _transition_next_plan_input_findings(resolution, apply: bool) -> list[Finding]:
    if not resolution.derived_fields:
        return []
    prefix = "" if apply else "would "
    findings = [
        Finding(
            "info",
            "transition-next-plan-derived-input",
            f"{prefix}use roadmap-derived next-plan field(s): {', '.join(resolution.derived_fields)}",
            "project/implementation-plan.md",
        )
    ]
    if resolution.candidate_objective:
        findings.append(
            Finding(
                "info",
                "transition-next-plan-candidate-objective",
                f"candidate objective: {resolution.candidate_objective}",
                "project/implementation-plan.md",
            )
        )
    if resolution.candidate_task:
        findings.append(
            Finding(
                "info",
                "transition-next-plan-candidate-task",
                f"candidate task: {resolution.candidate_task}",
                "project/implementation-plan.md",
            )
        )
    return findings


def _transition_next_roadmap_status_request(args):
    return make_roadmap_request("update", args.next_roadmap_item, status="active")


def _roadmap_item_mutation_args_present(args: argparse.Namespace) -> bool:
    scalar_names = (
        "title",
        "status",
        "stage",
        "order",
        "execution_slice",
        "slice_goal",
        "slice_closeout_boundary",
        "source_incubation",
        "source_research",
        "related_plan",
        "archived_plan",
        "verification_summary",
        "docs_decision",
        "carry_forward",
    )
    list_names = (
        "slice_members",
        "slice_dependencies",
        "source_members",
        "related_specs",
        "target_artifacts",
        "clear_fields",
        "custom_fields",
        "dependencies",
        "supersedes",
        "superseded_by",
    )
    return any(getattr(args, name, None) not in (None, "") for name in scalar_names) or any(
        bool(getattr(args, name, ())) for name in list_names
    )


def _transition_phase_complete_preview_inventory(inventory):
    state = inventory.state
    if state is None or not state.exists:
        return inventory
    state_text = _transition_frontmatter_text_with_scalars(state.content, {"phase_status": "complete"})
    if state_text == state.content:
        return inventory
    state_surface = _transition_surface_with_content(state, state_text)
    return _transition_inventory_with_surface(inventory, state_surface)


def _transition_surface_with_content(surface, content: str):
    if surface.path.suffix.lower() == ".md":
        frontmatter = parse_frontmatter(content)
        headings = extract_headings(content)
    else:
        frontmatter = surface.frontmatter
        headings = []
    return replace(
        surface,
        content=content,
        read_error=None,
        frontmatter=frontmatter,
        headings=headings,
        links=extract_path_refs(content),
    )


def _transition_inventory_with_surface(inventory, updated_surface):
    replaced = False
    surfaces = []
    for surface in inventory.surfaces:
        if surface.rel_path == updated_surface.rel_path:
            surfaces.append(updated_surface)
            replaced = True
        else:
            surfaces.append(surface)
    if not replaced:
        surfaces.append(updated_surface)
    surface_by_rel = dict(inventory.surface_by_rel)
    surface_by_rel[updated_surface.rel_path] = updated_surface
    state = updated_surface if inventory.state and inventory.state.rel_path == updated_surface.rel_path else inventory.state
    active_plan = (
        updated_surface
        if inventory.active_plan_surface and inventory.active_plan_surface.rel_path == updated_surface.rel_path
        else inventory.active_plan_surface
    )
    return replace(inventory, surfaces=surfaces, surface_by_rel=surface_by_rel, state=state, active_plan_surface=active_plan)


def _transition_frontmatter_text_with_scalars(text: str, updates: dict[str, str]) -> str:
    if not updates:
        return text
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return text
    for index in range(1, closing_index):
        match = re.match(r"^([A-Za-z0-9_-]+):(.*?)(\r?\n)?$", lines[index])
        if not match or match.group(1) not in updates:
            continue
        newline = match.group(3) or ("\n" if lines[index].endswith("\n") else "")
        lines[index] = f'{match.group(1)}: "{_transition_yaml_double_quoted_value(updates[match.group(1)])}"{newline}'
    return "".join(lines)


def _transition_yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _reload_transition_inventory(inventory):
    try:
        return load_for_root(inventory.root), []
    except RootLoadError as exc:
        return inventory, [Finding("error", "transition-refused", f"could not reload root after transition step: {exc}")]


def _transition_review_token(inventory, args) -> str:
    return _transition_review_token_from_payload(_transition_review_payload(inventory, args))


def _transition_review_payload(inventory, args, next_plan_resolution=None, preview_findings: list[Finding] | None = None) -> dict[str, object]:
    next_plan_resolution = next_plan_resolution or _transition_next_plan_resolution(inventory, args)
    next_plan_request = next_plan_resolution.request
    if preview_findings is None:
        preview_findings = _transition_preview_delegate_findings(inventory, args, next_plan_resolution)
    return {
        "actions": {
            "complete_current_phase": bool(args.complete_current_phase),
            "archive_active_plan": bool(args.archive_active_plan),
            "from_active_plan": bool(args.from_active_plan),
            "current_roadmap_item": args.current_roadmap_item or "",
            "current_roadmap_status": _transition_current_roadmap_status(args, default=""),
            "archive_collision_policy": args.archive_collision_policy or "refuse",
            "next_roadmap_item": args.next_roadmap_item or "",
            "next_title": next_plan_request.title if args.next_roadmap_item else args.next_title or "",
            "next_objective": next_plan_request.objective if args.next_roadmap_item else args.next_objective or "",
            "next_task": next_plan_request.task if args.next_roadmap_item else args.next_task or "",
            "next_derived_fields": list(next_plan_resolution.derived_fields),
            "only_requested_item": bool(args.only_requested_item),
            "allow_auto_compaction": bool(args.allow_auto_compaction),
        },
        "closeout": _transition_closeout_values(args),
        "files": _transition_file_digests(inventory, args),
        "targets": _transition_target_rels(inventory, args),
        "route_writes": _transition_review_route_write_inputs(preview_findings),
        "blockers": _transition_review_blocker_inputs(preview_findings),
        "dirty_cache": _transition_review_dirty_cache_inputs(inventory, preview_findings),
    }


def _transition_review_token_from_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _transition_review_token_input_findings(payload: dict[str, object], current: bool = False) -> list[Finding]:
    prefix = "current " if current else ""
    compare_hint = "; compare with the reviewed dry-run before rerunning apply" if current else ""
    findings = [
        Finding(
            "info",
            "transition-review-token-inputs",
            f"{prefix}review token input digests: {_transition_review_input_digest_summary(payload)}{compare_hint}",
            "project/project-state.md",
        )
    ]
    file_digests = payload.get("files")
    if isinstance(file_digests, dict):
        findings.append(
            Finding(
                "info",
                "transition-review-token-file-inputs",
                f"{prefix}review token file inputs: {_transition_review_file_digest_summary(file_digests)}",
                "project/project-state.md",
            )
        )
    return findings


def _transition_review_token_refresh_finding() -> Finding:
    return Finding(
        "info",
        "transition-review-token-refresh",
        (
            "no files were written; rerun the same transition --dry-run command against current repo-visible inputs, "
            "review the new transition-review-token-file-inputs and preview/effective-write-set digests, then apply with the refreshed token. "
            "Review-token inputs are scoped to transition input routes, derived targets, delegated route writes, blockers, and cache-dirty effects, "
            "so unrelated route changes outside that set do not invalidate the token."
        ),
        "project/project-state.md",
    )


def _transition_review_input_digest_summary(payload: dict[str, object]) -> str:
    keys = ("actions", "closeout", "files", "targets", "route_writes", "blockers", "dirty_cache")
    return "; ".join(f"{key}={_transition_payload_digest(payload.get(key, {}))}" for key in keys)


def _transition_review_file_digest_summary(file_digests: dict[object, object]) -> str:
    return "; ".join(f"{key}={str(value)[:12]}" for key, value in sorted(file_digests.items()))


def _transition_payload_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _transition_closeout_values(args) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in (
        "worktree_start_state",
        "task_scope",
        "docs_decision",
        "state_writeback",
        "verification",
        "commit_decision",
        "residual_risk",
        "next_state",
        "carry_forward",
        "work_result",
    ):
        value = getattr(args, field, None)
        if value:
            values[field] = str(value)
    return values


def _transition_file_digests(inventory, args) -> dict[str, str]:
    digests: dict[str, str] = {}
    for rel in _transition_review_file_input_rels(args):
        path = inventory.root / rel
        if not path.exists():
            digests[rel] = "<missing>"
        elif not path.is_file():
            digests[rel] = "<not-file>"
        else:
            digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def _transition_review_route_write_inputs(findings: list[Finding]) -> list[dict[str, str]]:
    inputs: list[dict[str, str]] = []
    for finding in findings:
        if str(finding.code).endswith("-route-write"):
            inputs.append(
                {
                    "severity": str(finding.severity),
                    "code": str(finding.code),
                    "source": str(finding.source or ""),
                    "message": str(finding.message or ""),
                }
            )
    return inputs


def _transition_review_blocker_inputs(findings: list[Finding]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    for finding in findings:
        if finding.severity not in {"warn", "error"}:
            continue
        blockers.append(
            {
                "severity": str(finding.severity),
                "code": str(finding.code),
                "source": str(finding.source or ""),
                "message": str(finding.message or ""),
            }
        )
    return blockers


def _transition_review_dirty_cache_inputs(inventory, findings: list[Finding]) -> dict[str, object]:
    changed_paths = _projection_cache_changed_paths(findings)
    has_error = any(finding.severity == "error" for finding in findings)
    capsule_present = _existing_context_memory_capsule(inventory)
    would_mark_dirty = not has_error
    return {
        "command": "transition --apply",
        "would_mark_projection_cache_dirty": would_mark_dirty,
        "changed_paths": list(changed_paths),
        "context_memory_capsule_present": capsule_present,
        "would_refresh_context_memory": bool(would_mark_dirty and changed_paths and capsule_present),
    }


def _transition_review_file_input_rels(args) -> tuple[str, ...]:
    rels = ["project/project-state.md"]
    if args.complete_current_phase or args.archive_active_plan or args.next_roadmap_item:
        rels.append("project/implementation-plan.md")
    if args.current_roadmap_item or args.next_roadmap_item:
        rels.append("project/roadmap.md")
    return tuple(dict.fromkeys(rels))


def _transition_target_rels(inventory, args) -> list[str]:
    targets: list[str] = []
    if args.complete_current_phase or args.archive_active_plan or args.next_roadmap_item:
        targets.append("project/project-state.md")
        targets.append("project/implementation-plan.md")
    if args.archive_active_plan:
        archive_rel = _transition_archive_target_rel(inventory, args)
        if archive_rel:
            targets.append(archive_rel)
    if args.current_roadmap_item or args.next_roadmap_item:
        targets.append("project/roadmap.md")
    return sorted(dict.fromkeys(targets))


def _transition_archive_target_rel(inventory, args) -> str:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return ""
    title = ""
    if plan.frontmatter.has_frontmatter and not plan.frontmatter.errors:
        title = str(plan.frontmatter.data.get("title") or "")
    if not title:
        title = _transition_first_heading(plan.content) or "implementation-plan"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title.strip().lower()).strip("-") or "implementation-plan"
    from datetime import date

    rel_path = f"project/archive/plans/{date.today().isoformat()}-{slug}.md"
    if getattr(args, "archive_collision_policy", "refuse") == "preserve-existing" and (inventory.root / rel_path).exists():
        return _transition_archive_collision_rel(inventory.root, rel_path)
    return rel_path


def _transition_archive_collision_rel(root: Path, canonical_rel_path: str) -> str:
    canonical = Path(canonical_rel_path)
    parent = canonical.parent.as_posix()
    stem = canonical.stem
    suffix = canonical.suffix or ".md"
    for index in range(2, 1000):
        rel_path = f"{parent}/{stem}-collision-{index}{suffix}"
        if not (root / rel_path).exists():
            return rel_path
    digest = hashlib.sha256(canonical_rel_path.encode("utf-8")).hexdigest()[:12]
    return f"{parent}/{stem}-collision-{digest}{suffix}"


def _transition_first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return None


def _state_phase_status(inventory) -> str:
    data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return str(data.get("phase_status") or "")


def _state_plan_status(inventory) -> str:
    data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return str(data.get("plan_status") or "")


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]


def _context_pack_suggestion_findings(intent: str | None, list_all: bool) -> list[Finding]:
    if list_all or not intent or not _looks_like_context_pack_intent(intent):
        return []
    return [
        Finding(
            "info",
            "context-pack-bootstrap-pointers",
            (
                "context-pack bootstrap pointers only: read AGENTS.md, .mylittleharness/project-workflow.toml "
                "or the .codex fallback manifest, project/project-state.md, project/roadmap.md, and "
                "project/implementation-plan.md only when plan_status is active; then run check, dashboard --inspect, "
                "and adapter --client-config --target mcp-read-projection as optional read-only navigation"
            ),
            "AGENTS.md",
        ),
        Finding(
            "info",
            "context-pack-exact-verification",
            (
                "the packet should carry root-relative pointers and commands, not duplicate authority bodies; "
                "agents verify exact source with rg or bounded source reads before edits or closeout claims"
            ),
            "project/project-state.md",
        ),
        Finding(
            "info",
            "context-pack-deep-research-flow",
            (
                "Deep Research remains a manual external request; after human review, import evidence with "
                "research-import --dry-run before --apply, then use research-distill --dry-run before --apply "
                "before any later explicit roadmap promotion"
            ),
            "project/research",
        ),
        Finding(
            "info",
            "context-pack-authority-boundary",
            (
                "context-pack guidance works for any file-reading, shell-capable agent; Codex, MCP, hooks, dashboard, "
                "and mlhd are optional helpers and the packet does not call an external model, create a public repo, "
                "publish, mutate lifecycle, stage, commit, push, release, or approve provider routing"
            ),
            "project/project-state.md",
        ),
    ]


def _looks_like_context_pack_intent(intent: str) -> bool:
    normalized = intent.casefold()
    if "context" not in normalized:
        return False
    context_pack_terms = ("pack", "packet", "bundle", "onboard", "adoption", "handoff", "пак", "контекст")
    return any(term in normalized for term in context_pack_terms)


def _result_for(findings) -> str:
    if any(finding.severity == "error" for finding in findings):
        return "error"
    if any(finding.severity == "warn" for finding in findings):
        return "warn"
    return "ok"


def _render_manifest_json_report(
    report_name: str,
    root: Path,
    result: str,
    sources: list[str],
    findings: list[Finding],
    suggestions: list[str],
    sections: list[tuple[str, list[Finding]]],
    route_rows: tuple[dict[str, object], ...],
    role_rows: tuple[dict[str, object], ...],
    command_surface_rows: tuple[dict[str, object], ...],
) -> str:
    payload = json.loads(render_json_report(report_name, root, result, sources, findings, suggestions, sections, route_rows))
    payload["role_manifest"] = list(role_rows)
    payload["command_surface"] = list(command_surface_rows)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)


def _render_suggest_json_report(
    report_name: str,
    root: Path,
    result: str,
    sources: list[str],
    findings: list[Finding],
    suggestions: list[str],
    sections: list[tuple[str, list[Finding]]],
    command_suggestions: tuple[object, ...],
    intent: str | None,
    list_all: bool,
) -> str:
    payload = json.loads(render_json_report(report_name, root, result, sources, findings, suggestions, sections))
    payload["intent_query"] = intent
    payload["list_all"] = list_all
    payload["command_suggestions"] = command_suggestions_to_dict(command_suggestions)
    payload["boundary"]["suggestions_execute_commands"] = False
    payload["boundary"]["suggestions_approve_lifecycle"] = False
    payload["boundary"]["rails_not_cognition"] = True
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)


def _route_manifest_findings() -> list[Finding]:
    findings: list[Finding] = []
    for row in route_manifest():
        route_id = str(row["route_id"])
        target = str(row["target"])
        findings.append(
            Finding(
                "info",
                "route-manifest-entry",
                (
                    f"{route_id}: target={target}; authority={row['authority']}; "
                    f"mutability={row['mutability']}; gate_class={row['gate_class']}"
                ),
                target,
                route_id=route_id,
            )
        )
    findings.append(
        Finding(
            "info",
            "route-manifest-boundary",
            "route manifest is advisory protocol data; repo-visible files and explicit apply rails remain authority",
            route_id="unclassified",
        )
    )
    return findings


def _agent_role_manifest_findings() -> list[Finding]:
    findings: list[Finding] = []
    for row in role_manifest():
        role_id = str(row["role_id"])
        permissions = list(row["permissions"])
        gate_classes = sorted({str(permission["gate_class"]) for permission in permissions if permission["human_gate"]["required"]})
        findings.append(
            Finding(
                "info",
                "agent-role-profile-entry",
                (
                    f"{role_id}: permissions={len(permissions)}; "
                    f"required_outputs={len(row['required_outputs'])}; "
                    f"human_gate_classes={gate_classes or ['none']}; "
                    f"apply_authority={row['apply_authority']}"
                ),
                route_id="unclassified",
            )
        )
    findings.append(
        Finding(
            "info",
            "agent-role-manifest-boundary",
            "role profiles are advisory protocol data; they do not grant direct lifecycle apply authority or spawn workers",
            route_id="unclassified",
        )
    )
    return findings


def _check_report(args: argparse.Namespace, inventory: object) -> tuple[str, list[tuple[str, list[Finding]]]]:
    boundary_section = [
        Finding("info", "check-read-only", "check diagnostics write no files, reports, caches, generated outputs, snapshots, Git state, hooks, package artifacts, adapter state, or workstation state"),
        rails_not_cognition_boundary_finding(),
    ]
    if args.focus:
        focus_sections = {
            "validation": ("Validation", lambda: validation_findings(inventory)),
            "links": ("Links", lambda: audit_link_findings(inventory)),
            "context": ("Context", lambda: context_budget_findings(inventory)),
            "hygiene": ("Hygiene", lambda: doctor_findings(inventory.root, inventory)),
            "grain": ("Grain", lambda: grain_findings(inventory)),
            "archive-context": ("Archive Context", lambda: archive_context_findings(inventory)),
            "route-references": ("Route References", lambda: route_reference_inventory_findings(inventory)),
            "retention": ("Retention", lambda: retention_receipt_findings(inventory, "check-retention")),
            "agents": (
                "Agents",
                lambda: [
                    *reconcile_findings(inventory, "check-agents"),
                    *coordination_evidence_identity_findings(inventory, "check-agents-coordination-evidence"),
                ],
            ),
        }
        section_name, build_focus_findings = focus_sections[args.focus]
        section = (section_name, build_focus_findings())
        boundary_section.append(Finding("info", "check-focus-read-only", f"check --focus {args.focus} runs one compatibility diagnostic without writing files"))
        return f"check --focus {args.focus}", [section, ("Boundary", boundary_section)]

    sections = [
        ("Status", status_findings(inventory)),
        ("Session Active Work", session_active_work_findings(inventory, "check-session-active-work")),
        ("Worktree Coordination", worktree_coordination_findings(inventory, code_prefix="check-worktree-coordination")),
        ("Validation", validation_findings(inventory)),
        ("Agent Run Evidence", agent_run_record_findings(inventory, "check-agent-run")),
        ("Retention", retention_receipt_findings(inventory, "check-retention")),
        ("Work Claims", work_claim_status_findings(inventory, "check-work-claim")),
        ("Handoff Packets", handoff_packet_status_findings(inventory, "check-handoff-packet")),
        ("Coordination Evidence", coordination_evidence_identity_findings(inventory, "check-coordination-evidence")),
        ("Projection Cache", projection_cache_status_findings(inventory)),
        ("Drift", check_drift_findings(inventory)),
    ]
    if args.deep:
        sections.extend(
            [
                ("Links", audit_link_findings(inventory)),
                ("Context", context_budget_findings(inventory)),
                ("Hygiene", doctor_findings(inventory.root, inventory)),
                ("Grain", grain_findings(inventory)),
            ]
        )
        boundary_section.append(Finding("info", "check-deep-read-only", "check --deep composes links, context, hygiene, and grain diagnostics without writing files"))
        return "check --deep", [*sections, ("Boundary", boundary_section)]

    if getattr(args, "quick", False):
        boundary_section.append(Finding("info", "check-quick-read-only", "check --quick renders a compact routine report without writing files or hiding JSON authority boundaries"))
        return "check --quick", [*sections, ("Boundary", boundary_section)]

    boundary_section.append(Finding("info", "check-compatibility-diagnostics", "use check --deep or check --focus for consolidated links, context, and hygiene diagnostics; compatibility commands remain available"))
    return "check", [*sections, ("Boundary", boundary_section)]


def _focused_report_scope(focus: str, sections: list[tuple[str, list[Finding]]]) -> dict[str, object]:
    included = [name for name, _findings in sections]
    all_focus_sections = {
        "Validation",
        "Links",
        "Context",
        "Hygiene",
        "Grain",
        "Archive Context",
        "Route References",
        "Retention",
        "Agents",
    }
    return {
        "scope": "focused",
        "focus": focus,
        "included_sections": included,
        "omitted_sections": sorted(all_focus_sections.difference(included)),
        "global_status_uncomputed": True,
        "status_represents_included_sections_only": True,
        "boundary": (
            "focused JSON reports include only the selected diagnostic and boundary findings; "
            "they do not compute whole-root clean posture or approve lifecycle, archive, staging, commit, or push"
        ),
    }


def _quick_report_scope(sections: list[tuple[str, list[Finding]]]) -> dict[str, object]:
    return {
        "scope": "quick",
        "included_sections": [name for name, _findings in sections],
        "text_report_omits_source_inventory": True,
        "json_report_keeps_full_sources_and_findings": True,
        "boundary": (
            "quick text reports compact the display only; they do not skip check sections, "
            "write files, approve lifecycle, archive, staging, commit, or push"
        ),
    }


def _read_text_argument(flag: str, value: str) -> tuple[str | None, str | None]:
    if value == "-":
        stdin_buffer = getattr(sys.stdin, "buffer", None)
        if stdin_buffer is not None:
            try:
                return stdin_buffer.read().decode("utf-8"), None
            except (OSError, UnicodeError) as exc:
                return None, f"{flag} could not be read as UTF-8 text from stdin: {exc}"
        return sys.stdin.read(), None
    path = Path(value).expanduser()
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError) as exc:
        return None, f"{flag} could not be read as UTF-8 text: {exc}"


def _projection_target_findings(target: str, artifacts_fn, index_fn, inventory: object) -> list[Finding]:
    if target == "artifacts":
        return artifacts_fn(inventory)
    if target == "index":
        return index_fn(inventory)
    return artifacts_fn(inventory) + index_fn(inventory)


def _projection_inspect_suggestions(findings: list[Finding]) -> list[str]:
    if any(finding.severity == "error" for finding in findings):
        return ["projection inspect was refused before reading generated cache posture; no files were written."]
    if any(finding.severity == "warn" for finding in findings):
        return ["projection inspect reported generated cache warnings without writing files; direct source files remain authoritative."]
    return ["projection inspect reported generated cache posture without writing files; direct source files remain authoritative."]


def _projection_suggestions(report_name: str, findings: list[Finding]) -> list[str]:
    lowered = report_name.casefold()
    if lowered.startswith("projection --inspect"):
        return _projection_inspect_suggestions(findings)
    errors = any(finding.severity == "error" for finding in findings)
    warnings = any(finding.severity == "warn" for finding in findings)
    if "--build" in lowered:
        if errors:
            return ["projection build was refused before generated cache was written."]
        if warnings:
            return ["projection build completed with generated-cache warnings; repo-visible files remain authoritative."]
        return ["projection build wrote explicit disposable generated cache under the owned boundary; repo-visible files remain authoritative."]
    if "--rebuild" in lowered:
        if errors:
            return ["projection rebuild was refused before generated cache was refreshed."]
        if warnings:
            return ["projection rebuild completed with generated-cache warnings; review degraded cache posture before relying on generated navigation."]
        return ["projection rebuild refreshed explicit disposable generated cache under the owned boundary; repo-visible files remain authoritative."]
    if "--delete" in lowered:
        if errors:
            return ["projection delete was refused before generated cache was removed."]
        if warnings:
            return ["projection delete completed with generated-cache warnings; direct repo files remain authoritative."]
        return ["projection delete removed only disposable generated cache under the owned boundary; repo-visible files remain authoritative."]
    if "--warm-cache" in lowered:
        if errors:
            return ["projection warm-cache was refused before optional generated cache refresh completed."]
        if warnings:
            return ["projection warm-cache completed with advisory warnings; direct repo files remain authoritative."]
        return ["projection warm-cache explicitly refreshed generated-cache-only state inside the owned boundary; repo-visible files remain authoritative."]
    return _suggestions("projection", findings)


def _with_projection_cache_dirty_findings(command: str, args: object, inventory: object, findings: list[Finding]) -> list[Finding]:
    if command not in CACHE_DIRTY_APPLY_COMMANDS or not bool(getattr(args, "apply", False)):
        return findings
    if any(finding.severity == "error" for finding in findings):
        return findings
    changed_paths = _projection_cache_changed_paths(findings)
    result = [*findings, *mark_projection_cache_dirty(inventory, changed_paths, f"{command} --apply")]
    if not changed_paths or not _existing_context_memory_capsule(inventory):
        return result
    return [*result, *_refresh_context_memory_after_apply(command, inventory)]


def _existing_context_memory_capsule(inventory: object) -> bool:
    try:
        root = Path(getattr(inventory, "root"))
    except (TypeError, ValueError):
        return False
    return (root / CONTEXT_MEMORY_LATEST_REL).is_file()


def _refresh_context_memory_after_apply(command: str, inventory: object) -> list[Finding]:
    recovery_command = _context_memory_recovery_command(inventory)
    try:
        refreshed_inventory = load_for_root(Path(getattr(inventory, "root")))
    except (OSError, RootLoadError, TypeError, ValueError) as exc:
        return [
            Finding(
                "warn",
                "context-memory-capsule-refresh-skipped",
                (
                    f"could not reload source refs after {command} --apply; generated context capsule was left as-is "
                    f"and the next safe recovery command is {recovery_command}: {exc}"
                ),
                CONTEXT_MEMORY_DIR_REL,
            )
        ]
    try:
        refresh_findings, _ = refresh_context_memory_capsule(refreshed_inventory, trigger=f"{command} --apply")
    except (OSError, TypeError, ValueError) as exc:
        return [
            Finding(
                "warn",
                "context-memory-capsule-refresh-skipped",
                (
                    f"could not refresh generated context capsule after {command} --apply; source files remain authoritative "
                    f"and the next safe recovery command is {recovery_command}: {exc}"
                ),
                CONTEXT_MEMORY_DIR_REL,
            )
        ]
    return refresh_findings


def _context_memory_recovery_command(inventory: object) -> str:
    if str(getattr(inventory, "root_kind", "") or "") == PRODUCT_SOURCE_FIXTURE:
        return "mylittleharness --root <root> check"
    return "mylittleharness --root <root> mlhd run-once --apply"


def _projection_cache_changed_paths(findings: list[Finding]) -> tuple[str, ...]:
    paths: set[str] = set()
    for finding in findings:
        if finding.source:
            paths.add(finding.source)
    return tuple(sorted(paths))


def _lifecycle_posture(inventory: object) -> LifecyclePosture:
    state = getattr(inventory, "state", None)
    state_data = getattr(getattr(state, "frontmatter", None), "data", {}) if state else {}
    plan_surface = getattr(inventory, "active_plan_surface", None)
    plan_exists = bool(plan_surface and getattr(plan_surface, "exists", False))
    plan_content = str(getattr(plan_surface, "content", "") or "") if plan_exists else ""
    return LifecyclePosture(
        plan_status=str(state_data.get("plan_status") or ""),
        active_plan=str(state_data.get("active_plan") or ""),
        active_phase=str(state_data.get("active_phase") or ""),
        phase_status=str(state_data.get("phase_status") or ""),
        active_plan_exists=plan_exists,
        active_plan_hash=_short_text_hash(plan_content) if plan_exists else "missing",
    )


def _short_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _meta_feedback_lifecycle_posture_findings(before: LifecyclePosture, after: LifecyclePosture) -> list[Finding]:
    if before == after:
        return [
            Finding(
                "info",
                "meta-feedback-lifecycle-posture",
                (
                    "lifecycle posture preserved after meta-feedback apply: "
                    f"plan_status={after.plan_status or '<empty>'!r}; "
                    f"active_plan={after.active_plan or '<empty>'!r}; "
                    f"active_phase={after.active_phase or '<empty>'!r}; "
                    f"phase_status={after.phase_status or '<empty>'!r}; "
                    f"active_plan_exists={after.active_plan_exists}; "
                    f"active_plan_hash={after.active_plan_hash}; "
                    "next-plan opening remains explicit"
                ),
                "project/project-state.md",
            )
        ]
    return [
        Finding(
            "warn",
            "meta-feedback-lifecycle-drift",
            (
                "lifecycle posture changed during meta-feedback apply; "
                f"before=({_format_lifecycle_posture(before)}); "
                f"after=({_format_lifecycle_posture(after)}); "
                "meta-feedback did not request or approve lifecycle movement; run check and inspect repo-visible routes "
                "before closeout, archive, commit, or next-plan decisions"
            ),
            "project/project-state.md",
        )
    ]


def _format_lifecycle_posture(posture: LifecyclePosture) -> str:
    return (
        f"plan_status={posture.plan_status or '<empty>'!r}, "
        f"active_plan={posture.active_plan or '<empty>'!r}, "
        f"active_phase={posture.active_phase or '<empty>'!r}, "
        f"phase_status={posture.phase_status or '<empty>'!r}, "
        f"active_plan_exists={posture.active_plan_exists}, "
        f"active_plan_hash={posture.active_plan_hash}"
    )


def _meta_feedback_destination_selection_findings(
    *,
    requested_inventory,
    destination_root: Path,
    to_root: str | None,
    env_root: str | None,
) -> list[Finding]:
    requested_root = requested_inventory.root
    if to_root:
        source = "--to-root"
    elif env_root:
        source = f"${META_FEEDBACK_ROOT_ENV_VAR}"
    else:
        source = "--root"
    findings = [
        Finding(
            "info",
            "meta-feedback-destination-selection",
            f"destination selected from {source}: {destination_root}",
        )
    ]
    if env_root and to_root:
        findings.append(
            Finding(
                "info",
                "meta-feedback-env-destination-overridden",
                (
                    f"{META_FEEDBACK_ROOT_ENV_VAR}={env_root} was ignored because --to-root was supplied; "
                    f"destination={destination_root}"
                ),
            )
        )
    elif env_root:
        findings.append(
            Finding(
                "info",
                "meta-feedback-env-destination-used",
                (
                    f"{META_FEEDBACK_ROOT_ENV_VAR}={env_root} selected the destination instead of --root {requested_root}; "
                    "use --to-root <path> to override the environment explicitly"
                ),
            )
        )
        if is_central_meta_feedback_inventory(requested_inventory) and requested_root.resolve() != destination_root.resolve():
            findings.append(
                Finding(
                    "info",
                    "meta-feedback-env-destination-override-command",
                    (
                        f"requested --root is the central destination; if that root was intended, rerun with "
                        f"--to-root {requested_root.resolve()} to bypass stale {META_FEEDBACK_ROOT_ENV_VAR}"
                    ),
                )
            )
    return findings


def _meta_feedback_destination_source(to_root: str | None, env_root: str | None) -> str:
    if to_root:
        return "--to-root"
    if env_root:
        return f"${META_FEEDBACK_ROOT_ENV_VAR}"
    return "--root"


def _repair_apply_exit_code(findings) -> int:
    invalid_codes = {
        "repair-refused",
        "repair-target-conflict",
        "snapshot-apply-refused",
        "agents-contract-create-refused",
        "docmap-create-refused",
        "stable-spec-create-refused",
        "state-frontmatter-refused",
        "lifecycle-frontmatter-refused",
        "lifecycle-source-provenance-refused",
        "spec-posture-frontmatter-refused",
    }
    if any(finding.severity == "error" and finding.code in invalid_codes for finding in findings):
        return 2
    if any(finding.severity == "error" for finding in findings):
        return 1
    return 0


def _focused_intelligence_sections(sections: list[tuple[str, list[Finding]]], focus: str | None) -> list[tuple[str, list[Finding]]]:
    if focus is None:
        return sections
    summary = _section_named(sections, "Summary")
    if focus == "search":
        return [summary, _section_named(sections, "Search")]
    if focus == "projection":
        return [summary, _section_named(sections, "Boundary"), _section_named(sections, "Projection")]
    if focus == "warnings":
        findings = [finding for _, section_findings in sections for finding in section_findings if finding.severity in {"warn", "error"}]
        if not findings:
            findings = [Finding("info", "actionable-warnings-empty", "no actionable intelligence warnings were found")]
        return [summary, ("Actionable Warnings", findings)]
    return sections


def _section_named(sections: list[tuple[str, list[Finding]]], name: str) -> tuple[str, list[Finding]]:
    for section in sections:
        if section[0] == name:
            return section
    return (name, [])


def _suggestions(command: str, findings) -> list[str]:
    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warn"]
    dry_run_refusal = "" if command in {"approval-packet", "claim", "handoff", "task-session"} else _dry_run_refusal_suggestion(command, findings)
    if dry_run_refusal:
        return [dry_run_refusal]
    if command == "check":
        if errors:
            return ["check found validation errors; inspect the validation section before running repair."]
        if any(finding.code == "check-deep-read-only" for finding in findings):
            return ["check --deep completed as a read-only status, validation, drift, links, context, hygiene, and grain report."]
        if any(finding.code == "check-quick-read-only" for finding in findings):
            return ["check --quick completed as a compact read-only report; rerun without --quick for full source inventory and section details."]
        focus_finding = next((finding for finding in findings if finding.code == "check-focus-read-only"), None)
        if focus_finding:
            return [f"{focus_finding.message}."]
        if any(finding.code == "state-compaction-section-boundary-missing" for finding in warnings):
            return [
                "check completed with compact-only hygiene warnings; restore missing project-state section boundaries, then preview/apply `mylittleharness --root <root> writeback --dry-run --compact-only` and `mylittleharness --root <root> writeback --apply --compact-only --source-hash <sha256-from-dry-run>`; no manual trimming, lifecycle closeout, archive, staging, commit, or next-plan opening is approved."
            ]
        if any(finding.code == "rule-context-surface-large" and finding.source == "project/project-state.md" for finding in warnings):
            return ["check completed as a read-only report; preview whole-state history compaction with `mylittleharness --root <root> writeback --dry-run --compact-only`."]
        if warnings:
            return ["check completed as a read-only report with advisory findings; use advanced diagnostics only when needed."]
        return ["check completed as a read-only status plus validation report."]
    if command == "suggest":
        if warnings:
            return ["suggest completed as a read-only command-intent report; no suggested command was executed."]
        return ["suggest matched deterministic command intent advice without writing files or executing suggested commands."]
    if command == "manifest":
        if warnings:
            return ["Review manifest warnings manually; route and role manifests are advisory protocol data only."]
        return ["manifest inspection completed as a terminal-only read-only protocol report; it did not grant apply authority, spawn workers, or approve lifecycle decisions."]
    if command == "migrate":
        if any(finding.code == "migrate-refused" for finding in errors):
            return ["migrate apply was refused before writing the neutral workflow manifest."]
        if any(finding.code == "migrate-dry-run" for finding in findings):
            return ["migrate dry-run reported the legacy-to-neutral manifest copy posture without writing files."]
        if any(finding.code == "migrate-copied" for finding in findings):
            return ["migrate apply copied the legacy workflow manifest to the neutral path and preserved the legacy file."]
        return ["migrate apply completed without changing lifecycle, adapter, Git, or legacy manifest deletion state."]
    if command == "detach":
        if any(finding.code == "detach-marker-created" for finding in findings):
            return ["detach apply created the marker-only evidence file; preserved repo-visible files remain the authority."]
        if any(finding.code == "detach-marker-unchanged" for finding in findings):
            return ["detach apply found an existing valid marker and left it unchanged."]
        if any(finding.severity == "error" for finding in findings):
            return ["detach apply was refused before authority files were changed."]
        if any(finding.severity == "warn" for finding in findings):
            return ["detach dry-run completed without writes; warnings are fail-closed inputs for detach apply."]
        return ["detach dry-run completed without writes; repo-visible files remain the authority."]
    if command == "intelligence":
        if warnings:
            return ["Use the listed source paths and line numbers for direct inspection; intelligence reports are advisory and never apply fixes."]
        return ["intelligence completed as a terminal-only advisory report; disposable navigation cache may be refreshed, but repo files remain the authority."]
    if command == "projection":
        if any(finding.severity == "error" for finding in findings):
            return ["projection artifact command was refused before writing or deleting outside the owned boundary."]
        if any(finding.severity == "warn" for finding in findings):
            return ["Generated projection artifacts are advisory; rebuild them if useful, or inspect repo files directly."]
        return ["projection artifacts are disposable generated output; deleting them does not change repo authority."]
    if command == "snapshot":
        if any(finding.severity == "warn" for finding in findings):
            return ["Use snapshot inspection as safety-evidence review only; manual rollback and source files remain operator decisions."]
        return ["snapshot inspection completed as a terminal-only read-only report; it did not approve repair, rollback, cleanup, closeout, archive, commit, or lifecycle decision."]
    if command == "evidence":
        is_agent_record_dry_run = any(finding.code == "agent-run-record-dry-run" for finding in findings)
        if is_agent_record_dry_run and any(
            finding.code == "agent-run-record-refused" and finding.severity in {"warn", "error"} for finding in findings
        ):
            return ["evidence record dry-run was refused before any agent run evidence record preview became reliable."]
        if is_agent_record_dry_run:
            return ["evidence record dry-run reported the agent run evidence target, source hashes, and route-write preview without writing files."]
        if any(finding.code == "agent-run-record-written" for finding in findings):
            return ["evidence record apply wrote one source-bound agent run evidence record; lifecycle, archive, roadmap, staging, commit, and next-plan decisions remain explicit."]
        if any(finding.severity == "warn" for finding in findings):
            return ["Use evidence findings as closeout assembly prompts; source files and observed verification remain authority."]
        return ["evidence completed as a terminal-only read-only report; it did not approve lifecycle, archive, commit, or repair actions."]
    if command == "retention":
        if any(finding.code == "retention-purge-refused" for finding in findings):
            return ["retention purge was refused because inbound references remain; preview a tombstone or retire route instead."]
        if any(finding.code == "retention-refused" for finding in findings):
            return ["retention route was refused before cleanup evidence was written."]
        if any(finding.code == "retention-scan-read-only" for finding in findings):
            return ["retention scan classified candidates, reference graph, and Git posture without writing files."]
        if any(finding.code == "retention-dry-run" for finding in findings):
            return ["retention dry-run reported candidate classification and receipt writes without mutating evidence."]
        if any(finding.code == "retention-applied" for finding in findings):
            return ["retention apply wrote reviewed cleanup evidence; run check before closeout, archive, staging, or commit."]
        return ["retention completed as evidence-only cleanup review; lifecycle, archive, Git, release, and target-repo acceptance remain explicit decisions."]
    if command == "task-session":
        if any(finding.code.startswith("task-session-provider-launcher") for finding in findings):
            return ["task-session provider-launcher inspect reported secret-safe runtime config readiness only; provider calls, worker launch, lifecycle movement, and Git remain separate explicit decisions."]
        if any(finding.code.startswith("task-session-fan-in") for finding in findings):
            if any(finding.code == "task-session-fan-in-ready" for finding in findings):
                return ["task-session fan-in inspect reports the session graph ready as evidence only; writeback, archive, Git, provider routing, and worker launch remain separate explicit decisions."]
            if any(finding.code == "task-session-fan-in-blocked" for finding in findings):
                return ["task-session fan-in inspect found blocking session-graph evidence gaps; add or repair repo-visible receipts, claims, handoffs, or agent-run evidence before closeout."]
            if any(finding.code == "task-session-fan-in-refused" for finding in findings):
                return ["task-session fan-in inspect refused this root posture; use a live operating root and rerun the read-only report."]
            return ["task-session fan-in inspect completed as read-only readiness evidence; it did not approve lifecycle, writeback, archive, Git, provider routing, or worker launch."]
        is_dry_run = any(finding.code == "task-session-receipt-dry-run" for finding in findings)
        if any(finding.severity == "error" for finding in findings):
            if is_dry_run:
                return ["task-session receipt dry-run was refused before any receipt evidence was written."]
            return ["task-session receipt apply was refused before any receipt evidence was written."]
        if is_dry_run:
            return ["task-session receipt dry-run reported the receipt target, scope, runtime owner, and route-write preview without writing files."]
        if any(finding.code == "task-session-receipt-written" for finding in findings):
            return ["task-session receipt apply wrote only one repo-visible receipt; worker launch, fan-in, lifecycle, archive, staging, commit, and provider-routing decisions remain explicit."]
        if any(finding.severity == "warn" for finding in findings):
            return ["Review task-session warnings manually; receipt evidence records runtime intent but cannot approve lifecycle or fan-in."]
        return ["task-session inspect completed as a terminal-only read-only preflight report; it did not write receipts, spawn workers, or approve lifecycle movement."]
    if command == "claim":
        is_dry_run = any(finding.code == "work-claim-dry-run" for finding in findings)
        if any(finding.severity == "error" for finding in findings):
            if is_dry_run:
                return ["claim dry-run was refused before any work-claim evidence was written or released."]
            return ["claim apply was refused before any work-claim evidence was written or released."]
        if is_dry_run:
            return ["claim dry-run reported the work-claim create/extend/release target and overlap posture without writing files."]
        if any(finding.code in {"work-claim-written", "work-claim-extended", "work-claim-released"} for finding in findings):
            return ["claim apply updated only repo-visible work-claim evidence; fan-in, lifecycle, archive, staging, commit, and release decisions remain explicit."]
        if any(finding.severity == "warn" for finding in findings):
            return ["Review claim warnings manually; claim status is evidence only and cannot release claims or approve lifecycle movement."]
        return ["claim status completed as a terminal-only read-only work-claim report; it did not create, release, or approve claims."]
    if command == "handoff":
        is_dry_run = any(finding.code == "handoff-packet-dry-run" for finding in findings)
        if any(finding.severity == "error" for finding in findings):
            if is_dry_run:
                return ["handoff dry-run was refused before any handoff packet was written."]
            return ["handoff apply was refused before any handoff packet was written."]
        if is_dry_run:
            return ["handoff dry-run reported the packet target, scope, and evidence refs without writing files."]
        if any(finding.code in {"handoff-packet-written", "handoff-packet-accepted"} for finding in findings):
            return ["handoff apply wrote only one repo-visible handoff packet update; worker fan-in and lifecycle decisions remain explicit."]
        if any(finding.code == "dispatcher-launch-ready" for finding in findings):
            return ["handoff status reported dispatcher launch-ready refs from repo-visible handoff, claim, and evidence paths; it did not start workers or approve lifecycle movement."]
        if any(finding.code == "dispatcher-launch-refused" for finding in findings):
            return ["handoff status refused dispatcher launch readiness until a handoff packet, compatible active claim, and planned agent-run evidence path are repo-visible."]
        return ["handoff status completed as a terminal-only read-only handoff packet report; it did not spawn workers or approve lifecycle movement."]
    if command == "approval-packet":
        is_dry_run = any(finding.code == "approval-packet-dry-run" for finding in findings)
        is_approved_status = any(finding.code == "approval-packet-shape" and "status=approved" in finding.message for finding in findings)
        if any(finding.severity == "error" for finding in findings):
            if is_dry_run:
                return ["approval-packet dry-run was refused before any approval evidence was written."]
            return ["approval-packet apply was refused before any approval evidence was written."]
        if is_dry_run:
            if is_approved_status:
                return ["approval-packet dry-run previewed a packet already marked approved; matching apply records repo-visible human-gate evidence only and cannot grant approval, transition an existing packet, or approve lifecycle/archive/Git/release."]
            return ["approval-packet dry-run reported the packet target, requested decision, and gate boundary without writing files."]
        if is_approved_status:
            return ["approval-packet apply wrote one repo-visible human-gate evidence packet with status=approved; packet status cannot grant approval, transition existing packets, or approve lifecycle, archive, staging, commit, or release."]
        return ["approval-packet apply wrote only one repo-visible human-gate evidence packet; packet status cannot approve lifecycle, archive, staging, commit, or release."]
    if command == "review-token":
        if any(finding.severity == "error" for finding in findings):
            return ["review-token refused before token trust; refresh inputs and recompute before fan-in or apply review."]
        if any(finding.severity == "warn" for finding in findings):
            return ["Review token warnings manually; matching tokens are fan-in guards only and cannot approve lifecycle movement."]
        return ["review-token computed a deterministic fan-in guard without writing files; matching tokens remain evidence, not lifecycle authority."]
    if command == "reconcile":
        if any(finding.severity == "warn" for finding in findings):
            return ["Review reconcile warnings manually; reconcile does not apply cleanup, release claims, archive, stage, commit, or approve lifecycle movement."]
        return ["reconcile completed as a terminal-only read-only drift and worker-residue report."]
    if command == "cleanup":
        if any(finding.severity == "error" for finding in findings):
            return ["cleanup was refused before deleting any file; review the target, JSON shape, Git tracking, and root boundary."]
        if any(finding.code == "cleanup-dry-run" for finding in findings):
            return ["cleanup dry-run reported the exact temporary roadmap manifest deletion boundary without writing files."]
        if any(finding.code == "cleanup-deleted" for finding in findings):
            return ["cleanup apply deleted only the reviewed temporary roadmap JSON manifest; lifecycle, archive, roadmap, Git, and hook-policy decisions remain explicit."]
        return ["cleanup apply found no delete target and left repo-visible authority unchanged."]
    if command == "closeout":
        if any(finding.severity == "warn" for finding in findings):
            return ["Use closeout findings as assembly inputs; operator decisions, source files, manifest policy, and observed verification remain authority."]
        return ["closeout completed as a terminal-only read-only report; it did not approve archive, commit, repair, or lifecycle decisions."]
    if command == "writeback":
        if any(finding.severity == "error" for finding in findings):
            return ["writeback apply was refused before closeout/state writeback became authoritative."]
        if any(finding.code == "writeback-compact-only" for finding in findings):
            if any(finding.code == "writeback-dry-run" for finding in findings):
                return ["writeback compact-only dry-run reported whole-state compaction posture without writing files."]
            return ["writeback compact-only apply ran the bounded whole-state compaction rail; run check to verify the archive pointer posture."]
        if any(finding.code == "writeback-dry-run" for finding in findings):
            return ["writeback dry-run reported the planned closeout/state synchronization without writing files."]
        return ["writeback apply synchronized project-state closeout facts and matching active-plan derived copies."]
    if command == "incubate":
        if any(finding.severity == "error" for finding in findings):
            return ["incubate apply was refused before any incubation note was changed."]
        if any(finding.code == "incubate-dry-run" for finding in findings):
            return ["incubate dry-run reported the target note and create/append posture without writing files."]
        return ["incubate apply updated the same-topic incubation note; promote accepted facts through research, specs, plans, or state later."]
    if command == "incubation-reconcile":
        if any(finding.severity == "error" for finding in findings):
            return ["incubation-reconcile apply was refused before any reconciliation metadata was changed."]
        if any(finding.code == "incubation-reconcile-dry-run" for finding in findings):
            return ["incubation-reconcile dry-run classified selected incubation notes without writing files."]
        return ["incubation-reconcile apply updated only bounded lifecycle metadata on selected incubation notes."]
    if command == "meta-feedback":
        if any(finding.severity == "error" for finding in findings):
            return ["meta-feedback apply was refused before any candidate note or cluster metadata was changed."]
        if any(
            finding.code in {"meta-feedback-refused", "meta-feedback-central-root-refused"}
            or (finding.code == "meta-feedback-validation-posture" and "dry-run refused" in str(finding.message or ""))
            for finding in findings
        ):
            return ["meta-feedback dry-run was refused before any candidate note or cluster metadata preview became reliable."]
        if any(finding.code == "meta-feedback-dry-run" for finding in findings):
            if any(
                finding.code == "meta-feedback-dedupe"
                and "append to existing canonical incubation cluster" in str(finding.message or "")
                for finding in findings
            ):
                return [
                    "meta-feedback dry-run reported the existing-cluster append path, dedupe decision, "
                    "cluster metadata, and explicit roadmap-detached boundary without new-note guidance."
                ]
            return ["meta-feedback dry-run reported the candidate note, dedupe decision, cluster metadata, and explicit roadmap-detached boundary without writing files."]
        return ["meta-feedback apply collected the candidate note and cluster metadata; roadmap promotion, next-plan opening, and release removal remain explicit."]
    if command == "intake":
        if any(finding.severity == "error" for finding in findings):
            return ["intake apply was refused before any routed note was written."]
        if any(finding.code == "intake-dry-run" for finding in findings):
            if any(
                finding.code == "intake-route-advisor"
                and any(marker in str(finding.message or "") for marker in ("classify input as adrs", "classify input as decisions"))
                for finding in findings
            ):
                return ["intake dry-run routed durable architecture/decision knowledge to a reviewed draft lane without writing files."]
            return ["intake dry-run classified the incoming text without writing files."]
        if any(
            finding.code == "intake-route-advisor"
            and any(marker in str(finding.message or "") for marker in ("classify input as adrs", "classify input as decisions"))
            for finding in findings
        ):
            return ["intake apply wrote one explicit draft ADR/decision note; acceptance remains a separate review decision."]
        return ["intake apply wrote one explicit routed note; classification remains advisory and does not approve lifecycle movement."]
    if command == "attachment-import":
        if any(finding.severity == "error" for finding in findings):
            return ["attachment-import apply was refused before any binary or metadata card was written."]
        if any(finding.code == "attachment-import-dry-run" for finding in findings):
            return ["attachment-import dry-run reported the binary target, metadata card, hash, size, MIME type, and research handoff without writing files."]
        return ["attachment-import apply copied one binary and wrote its sidecar metadata card; research, roadmap, plan, purchase, staging, and commit decisions remain explicit."]
    if command == "research-import":
        if any(finding.severity == "error" for finding in findings):
            return ["research-import apply was refused before any research artifact was written."]
        if any(finding.code == "research-import-dry-run" for finding in findings):
            return ["research-import dry-run reported the target research artifact and provenance hashes without writing files."]
        return ["research-import apply wrote one non-authority research artifact; promotion into specs, plans, or state remains explicit."]
    if command == "discover":
        if any(finding.severity == "error" for finding in findings):
            return ["discover apply was refused before any discovery packet was written."]
        if any(finding.code == "discover-dry-run" for finding in findings):
            return ["discover dry-run reported the target discovery packet, source refs, hashes, and readiness gates without writing files."]
        return ["discover apply wrote one non-authority discovery packet; roadmap and plan consumption remains gated by explicit readiness fields."]
    if command == "research-distill":
        if any(finding.severity == "error" for finding in findings):
            return ["research-distill apply was refused before any distillate artifact was written."]
        if any(finding.code == "research-distill-dry-run" for finding in findings):
            return ["research-distill dry-run reported the target distillate, source hash, candidates, gaps, and route proposals without writing files."]
        return ["research-distill apply wrote one non-authority distillate artifact; promotion into specs, incubation, plans, or state remains explicit."]
    if command == "research-compare":
        if any(finding.severity == "error" for finding in findings):
            return ["research-compare apply was refused before any comparison artifact was written."]
        if any(finding.code == "research-compare-dry-run" for finding in findings):
            if any(finding.code == "research-compare-archive-before-removal" for finding in findings):
                return ["research-compare dry-run reported compared sources, archive-before-removal source cleanup, exact link repair posture, conflicts, gaps, route proposals, and source hashes without writing files."]
            return ["research-compare dry-run reported compared sources, conflicts, gaps, route proposals, and source hashes without writing files."]
        if any(finding.code == "research-compare-source-archived" for finding in findings):
            return ["research-compare apply wrote one non-authority comparison artifact and archived compared source artifacts with source metadata and exact link repairs; promotion into specs, incubation, plans, or state remains explicit."]
        return ["research-compare apply wrote one non-authority comparison artifact; promotion into specs, incubation, plans, or state remains explicit."]
    if command == "plan":
        if any(finding.severity == "error" for finding in findings):
            return ["plan apply was refused before active-plan or lifecycle files were changed."]
        if any(finding.code == "plan-dry-run" for finding in findings):
            return ["plan dry-run reported deterministic plan synthesis and lifecycle update posture without writing files."]
        return ["plan apply wrote the active implementation plan scaffold and project-state lifecycle pointers."]
    if command == "transition":
        if any(finding.severity == "error" for finding in findings):
            return ["transition apply was refused or stopped before the next unreviewed step."]
        if any(finding.code == "transition-dry-run" for finding in findings):
            return ["transition dry-run reported the reviewed closeout/archive/next-plan proposal and token without writing files."]
        return ["transition apply completed the explicitly reviewed writeback/plan sequence without VCS side effects."]
    if command == "memory-hygiene":
        if any(finding.severity == "error" for finding in findings):
            if any(finding.code == "verification-ledger-rotate-refused" for finding in findings):
                return ["verification ledger rotation was refused before active ledger or archive targets were changed."]
            if any(finding.code == "incubation-archive-list-refused" for finding in findings):
                return ["incubation archive-list maintenance was refused before protected incubation sources, archive index, or link targets were changed."]
            return ["memory-hygiene apply was refused before lifecycle source, archive, or link targets were changed."]
        if any(finding.code == "incubation-archive-list-dry-run" for finding in findings):
            return ["incubation archive-list dry-run reported reviewed source moves, manifest evidence, proposal token, and optional exact link repairs without writing files."]
        if any(finding.code == "incubation-archive-list-apply" for finding in findings):
            return ["incubation archive-list apply moved the reviewed eligible notes, wrote the archive index, and repaired exact links when requested; lifecycle decisions remain explicit."]
        if any(finding.code == "verification-ledger-rotate-dry-run" for finding in findings):
            return ["verification ledger rotation dry-run reported source hash, archive target, and fresh continuity seed without writing files."]
        if any(finding.code == "verification-ledger-rotate-apply" for finding in findings):
            return ["verification ledger rotation apply archived the reviewed ledger and seeded a fresh continuity ledger; lifecycle decisions remain explicit."]
        if any(finding.code == "memory-hygiene-batch-apply" for finding in findings):
            return ["memory-hygiene token-bound batch apply archived the reviewed cleanup candidates and repaired exact links; lifecycle decisions remain explicit."]
        if any(finding.code == "memory-hygiene-scan" for finding in findings):
            return ["memory-hygiene scan reviewed relationship/incubation hygiene without writing files."]
        if any(finding.code == "memory-hygiene-dry-run" for finding in findings):
            return ["memory-hygiene dry-run reported bounded research/incubation lifecycle hygiene without writing files."]
        return ["memory-hygiene apply updated only declared lifecycle source, archive, and exact link targets."]
    if command == "relationship-drift":
        if any(finding.severity == "error" for finding in findings):
            return ["relationship-drift apply was refused before relationship metadata was changed."]
        if any(finding.code == "relationship-drift-dry-run" for finding in findings):
            return ["relationship-drift dry-run reported before/after relationship graph, retarget/detach decisions, and missing-route impact without writing files."]
        return ["relationship-drift apply updated only roadmap/source-incubation relationship metadata; lifecycle decisions remain explicit."]
    if command == "roadmap":
        if any(finding.severity == "error" for finding in findings):
            return ["roadmap apply was refused before roadmap files were changed."]
        if any(finding.code == "roadmap-normalize-dry-run" for finding in findings):
            return ["roadmap normalize dry-run reported physical item block ordering without writing files."]
        if any(finding.code == "roadmap-normalize-written" for finding in findings):
            return ["roadmap normalize apply reordered only the managed roadmap item blocks and refreshed derived roadmap summaries."]
        if any(finding.code == "roadmap-dry-run" for finding in findings):
            return ["roadmap dry-run reported the planned item mutation without writing files."]
        return ["roadmap apply updated only the declared roadmap route and any explicitly owned relationship metadata."]
    if command == "adapter":
        if any(finding.code == "adapter-codex-config-apply-refused" for finding in findings):
            return ["adapter install apply was refused before writing Codex MCP config or project-local native hook files."]
        if any(finding.code == "adapter-codex-config-apply-written" for finding in findings):
            return ["adapter install apply wrote the reviewed Codex MCP config mount and project-local Codex native hook adapter; lifecycle, Git, provider, product diff, and cache authority remain unchanged."]
        if any(finding.code == "adapter-codex-config-apply-unchanged" for finding in findings):
            return ["adapter install apply found the Codex MCP config already mounted and kept project-local Codex native hook posture idempotent; lifecycle, Git, provider, product diff, and cache authority remain unchanged."]
        if any(finding.severity == "warn" for finding in findings):
            return ["Use adapter findings as optional read/projection input; repo files and the generic CLI remain authoritative."]
        return ["adapter inspection completed as a terminal-only read-only report; it did not install MCP tooling, write adapter state, or approve lifecycle decisions."]
    if command == "mlhd":
        if any(finding.severity == "error" for finding in findings):
            return ["mlhd control-plane command was refused before writing runtime state."]
        if any("dry-run" in str(finding.code or "") for finding in findings):
            return ["mlhd dry-run reported disposable runtime targets without writing files."]
        if any(finding.code.endswith("-apply") for finding in findings):
            return ["mlhd apply wrote disposable runtime evidence and optional generated projection cache only; lifecycle, source, archive, Git, provider, and release authority remain unchanged."]
        return ["mlhd status inspected disposable runtime state without writing files."]
    if command == "preflight":
        if any(finding.severity in {"warn", "error"} for finding in findings):
            return ["Use preflight findings as optional warning inputs; source files, observed verification, and operator decisions remain authority."]
        return ["preflight completed as a terminal-only optional report; it did not install hooks, add CI, write reports, or approve lifecycle decisions."]
    if command == "hooks":
        if any(finding.code in {"hooks-codex-adapter-refused", "hooks-native-adapter-refused"} for finding in findings):
            return ["hooks adapter apply was refused before writing project-local hook adapter files; rerun the matching dry-run after fixing the reported posture."]
        if any(finding.code in {"hooks-codex-adapter-apply-written", "hooks-codex-adapter-apply-unchanged"} for finding in findings):
            return ["hooks adapter apply installed only the project-local Codex native event adapter; hook output remains advisory and cannot approve lifecycle, archive, roadmap, staging, commit, push, or release decisions."]
        if any(finding.code in {"hooks-native-adapter-apply-written", "hooks-native-adapter-apply-unchanged"} for finding in findings):
            return ["hooks adapter apply installed only the project-local native event adapter for the selected client; hook output remains advisory and cannot approve lifecycle, archive, roadmap, staging, commit, push, or release decisions."]
        if any(finding.code == "hooks-install-written" for finding in findings):
            return ["hooks apply installed only the selected warning-only shim; hook output remains advisory and cannot approve lifecycle, archive, roadmap, staging, commit, push, or release decisions."]
        if any(finding.code == "hooks-install-refused" for finding in findings):
            return ["hooks apply was refused before writing a hook shim; fix root or target posture and rerun hooks --dry-run before apply."]
        if any(finding.code == "hooks-run-event" for finding in findings):
            return ["hooks run completed as a foreground read-only adapter; repo-visible files remain authority."]
        return ["hooks doctor/dry-run reported hook posture without installing hooks, mutating Git config, or approving lifecycle decisions."]
    if command == "tasks":
        return ["tasks inspection completed as a terminal-only read-only task map; existing commands and repo files remain authoritative."]
    if command == "bootstrap":
        if any(finding.code == "package-smoke-install-ok" for finding in findings):
            return ["package smoke passed in temporary locations; product-root files and workstation state were not changed."]
        if any(finding.code.startswith("package-smoke-") and finding.severity == "error" for finding in findings):
            return ["package smoke failed before creating product-root package artifacts or workstation changes."]
        if any(finding.severity in {"warn", "error"} for finding in findings):
            return ["Use bootstrap readiness findings as planning inputs; no-write workstation readiness is advisory, package smoke remains explicit verification, standalone bootstrap apply is rejected, and publishing requires a separate scoped contract."]
        return ["bootstrap inspection completed as terminal-only read-only output; it did not install, publish, change target roots, write artifacts, or mutate workstation state."]
    if command == "semantic":
        if any(finding.severity in {"warn", "error"} for finding in findings):
            return ["Use semantic warnings as planning inputs; exact/path/full-text source-backed search and repo files remain authority."]
        return ["semantic report completed as terminal-only read-only output; it did not install runtimes, write indexes, or approve lifecycle decisions."]
    if any(finding.code in {"attach-refused", "attach-project-required", "attach-target-conflict"} for finding in errors):
        return ["attach apply was refused before any files were written."]
    if any(
        finding.code
        in {
            "repair-refused",
            "repair-target-conflict",
            "snapshot-apply-refused",
            "agents-contract-create-refused",
            "docmap-create-refused",
            "stable-spec-create-refused",
            "state-frontmatter-refused",
            "lifecycle-frontmatter-refused",
            "lifecycle-source-provenance-refused",
            "spec-posture-frontmatter-refused",
        }
        for finding in errors
    ):
        return ["repair apply was refused before any files were written."]
    if any(finding.code == "repair-validation-error" for finding in errors):
        return ["repair apply completed its allowed create-only pass, but post-repair validation still has errors."]
    if any(finding.code == "attach-created" for finding in findings):
        return ["attach apply completed create-only writes; run validate to inspect any remaining required surfaces."]
    if any(finding.code == "attach-unchanged" for finding in findings):
        return ["attach apply completed without changes; existing scaffold/template paths were preserved."]
    if any(finding.code == "repair-docmap-updated" for finding in findings):
        return ["repair apply created a repair snapshot, updated the selected docmap routes, and ran post-repair validation."]
    if any(finding.code == "state-frontmatter-updated" for finding in findings):
        return ["repair apply created a repair snapshot, prepended project-state frontmatter, and stopped before other repair classes."]
    if any(finding.code == "lifecycle-frontmatter-updated" for finding in findings):
        return ["repair apply created a repair snapshot, prepended lifecycle markdown frontmatter, and stopped before other repair classes."]
    if any(finding.code == "lifecycle-source-provenance-updated" for finding in findings):
        return ["repair apply created a repair snapshot, normalized lifecycle source provenance, and stopped before other repair classes."]
    if any(finding.code == "spec-posture-frontmatter-updated" for finding in findings):
        return ["repair apply created a repair snapshot, added missing spec posture frontmatter, and stopped before other repair classes."]
    if any(finding.code == "agents-contract-create-created" for finding in findings):
        return ["repair apply created the selected AGENTS.md operator contract without creating a repair snapshot and ran post-repair validation."]
    if any(finding.code == "docmap-create-created" for finding in findings):
        return ["repair apply created the selected docmap file without creating a repair snapshot and ran post-repair validation."]
    if any(finding.code == "stable-spec-create-created" for finding in findings):
        return ["repair apply created the selected stable spec fixtures without creating a repair snapshot and ran post-repair validation."]
    if any(finding.code == "repair-created" for finding in findings):
        return ["repair apply completed allowed writes and ran post-repair validation."]
    if any(finding.code == "repair-unchanged" for finding in findings):
        return ["repair apply completed without changes and ran post-repair validation."]
    if any(
        finding.code
        in {
            "state-frontmatter-plan",
            "state-frontmatter-refused",
            "state-frontmatter-skipped",
            "lifecycle-frontmatter-plan",
            "lifecycle-frontmatter-plan-refused",
            "lifecycle-frontmatter-plan-skipped",
            "lifecycle-source-provenance-plan",
            "lifecycle-source-provenance-plan-refused",
            "lifecycle-source-provenance-plan-skipped",
            "spec-posture-frontmatter-plan",
            "spec-posture-frontmatter-plan-refused",
            "spec-posture-frontmatter-plan-skipped",
            "snapshot-plan",
            "snapshot-plan-refused",
            "snapshot-plan-skipped",
            "agents-contract-create-plan",
            "agents-contract-create-refused",
            "agents-contract-create-skipped",
            "docmap-create-plan",
            "docmap-create-refused",
            "stable-spec-create-plan",
            "stable-spec-create-refused",
        }
        for finding in findings
    ):
        return ["repair dry-run reported repair planning posture only; no files or snapshots were written."]
    if any(finding.code in {"attach-proposal", "repair-proposal"} for finding in findings):
        return [f"{command} completed as a dry-run proposal; no files were written."]
    if not errors and not warnings:
        return [f"{command} completed without required follow-up."]
    suggestions: list[str] = []
    if any(finding.code == "missing-required-surface" for finding in errors):
        suggestions.append("Restore the missing required repo-native surface before relying on the workflow state.")
    if any(finding.code == "mirror-drift" for finding in errors):
        suggestions.append("Resync package-source mirrors from project/specs/workflow only after confirming mirror parity is still intended.")
    if any(finding.code in {"missing-link", "unresolved-link"} for finding in warnings):
        suggestions.append("Review missing local path references manually; the CLI reports candidate fixes but never rewrites files.")
    if any(finding.code in {"file-budget", "start-set-budget"} for finding in warnings):
        suggestions.append("Treat large context-budget findings as measurement signals; the CLI does not compact or impose binding budgets.")
    if any(finding.code in {"forbidden-product-surface", "product-debris"} for finding in warnings):
        suggestions.append("Review product hygiene findings manually; the CLI reports debris but never deletes files.")
    if not suggestions:
        suggestions.append("Review warnings manually; this report does not apply fixes automatically.")
    return suggestions


def _dry_run_refusal_suggestion(command: str, findings) -> str:
    if not any("dry-run" in str(finding.code or "") for finding in findings):
        return ""
    if not any(
        str(finding.code or "").endswith("-refused")
        or "dry-run refused before" in str(finding.message or "")
        for finding in findings
    ):
        return ""
    subjects = {
        "approval-packet": "approval evidence",
        "claim": "work-claim evidence",
        "handoff": "handoff packet",
        "incubate": "incubation note",
        "intake": "routed note",
        "discover": "discovery packet",
        "evidence": "agent run evidence record",
        "meta-feedback": "candidate note or cluster metadata",
        "plan": "active-plan or lifecycle update",
        "roadmap": "roadmap mutation",
        "transition": "lifecycle transition",
        "writeback": "closeout/state writeback",
    }
    subject = subjects.get(command, "apply target")
    if command == "evidence":
        return f"evidence record dry-run was refused before any {subject} preview became reliable."
    return f"{command} dry-run was refused before any {subject} preview became reliable."


if __name__ == "__main__":
    raise SystemExit(main())
