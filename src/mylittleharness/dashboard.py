from __future__ import annotations

from collections import Counter
from pathlib import Path

from .adapter import codex_mcp_adoption_payload
from .claims import work_claim_status_findings
from .context_memory import context_memory_capsule_findings, context_memory_capsule_payload
from .daemon import inspect_mlhd_control_state, mlhd_runtime_findings, mlhd_runtime_payload
from .evidence import agent_run_record_findings, lifecycle_mutation_provenance_findings
from .handoff import handoff_packet_status_findings
from .inventory import Inventory
from .lifecycle_focus import session_active_work_findings
from .models import Finding
from .projection import build_projection, projection_summary_to_dict
from .projection_artifacts import (
    ARTIFACT_DIR_REL,
    inspect_projection_artifacts,
    projection_cache_posture_payload,
)
from .projection_index import inspect_projection_index
from .roadmap import roadmap_items_for_diagnostics
from .vcs import worktree_coordination_findings


DASHBOARD_SCHEMA = "mylittleharness.dashboard.v1"
CONNECT_READINESS_SCHEMA = "mylittleharness.connect-readiness-action-packet.v1"
MLHD_RUNTIME_DIR_REL = ".mylittleharness/runtime/mlhd"
PROJECT_ROUTE_DIR = "project"
STATE_ROUTE_REL = f"{PROJECT_ROUTE_DIR}/project-state.md"
ROADMAP_ROUTE_REL = f"{PROJECT_ROUTE_DIR}/roadmap.md"
ACTIVE_PLAN_ROUTE_REL = f"{PROJECT_ROUTE_DIR}/implementation-plan.md"
DOCMAP_ROUTE_REL = ".agents/" "docmap.yaml"
DOCS_GLOB_REL = "docs/**/*.md"
WORKFLOW_SPECS_GLOB_REL = f"{PROJECT_ROUTE_DIR}/specs/**/*.md"


def dashboard_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    coordination = _coordination_findings(inventory)
    runtime = [*mlhd_runtime_findings(inventory), *_mlhd_freshness_findings(inventory)]
    return [
        ("Dashboard", _dashboard_summary_findings(inventory)),
        ("Connect Readiness", connect_readiness_findings(inventory, "dashboard-connect-readiness")),
        ("Lifecycle", _lifecycle_findings(inventory)),
        ("Roadmap", _roadmap_findings(inventory)),
        ("Coordination", coordination),
        ("mlhd Runtime", runtime),
        ("Context Memory", context_memory_capsule_findings(inventory, "dashboard-context-memory")),
        ("Projection", _projection_findings(inventory)),
        ("Lifecycle Provenance", lifecycle_mutation_provenance_findings(inventory, "dashboard-lifecycle-provenance")),
        ("Alerts", _alert_findings([*coordination, *runtime])),
        ("Boundary", _boundary_findings()),
    ]


def dashboard_payload(inventory: Inventory, sections: list[tuple[str, list[Finding]]] | None = None) -> dict[str, object]:
    sections = dashboard_sections(inventory) if sections is None else sections
    findings = [finding for _section, section_findings in sections for finding in section_findings]
    cache_posture = _cache_posture_payload(inventory)
    agent_packet = dashboard_agent_packet(inventory)
    accelerator_adoption = _accelerator_adoption_payload(inventory)
    return {
        "schema": DASHBOARD_SCHEMA,
        "root": str(inventory.root),
        "root_kind": inventory.root_kind,
        "read_only": True,
        "source_refs": _dashboard_source_refs(sections),
        "lifecycle": _lifecycle_payload(inventory),
        "roadmap": _roadmap_payload(inventory),
        "mlhd": mlhd_freshness_payload(inventory),
        "contextMemory": context_memory_capsule_payload(inventory),
        "projection": projection_summary_to_dict(build_projection(inventory)),
        "cachePosture": cache_posture,
        "agentPacket": agent_packet,
        "authorityCards": agent_packet.get("authorityCards", []),
        "acceleratorAdoption": accelerator_adoption,
        "connectReadiness": connect_readiness_packet(
            inventory,
            cache_posture=cache_posture,
            agent_packet=agent_packet,
            accelerator_adoption=accelerator_adoption,
        ),
        "nextLegalDryRun": _next_legal_dry_run_payload(inventory),
        "coordination": _coordination_payload(findings),
        "alerts": _alert_payload(findings),
        "sections": [
            {"name": name, "findings": [finding.to_dict() for finding in section_findings]}
            for name, section_findings in sections
        ],
        "authority_boundary": (
            "dashboard is a read-only cockpit projection; repo-visible files remain truth and no dashboard output "
            "approves lifecycle movement, archive, staging, commit, push, release, dispatcher work, or daemon state"
        ),
    }


def dashboard_check_findings(inventory: Inventory, code_prefix: str = "check-dashboard") -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-available",
            (
                "dashboard --inspect is a read-only cockpit over project-state, roadmap, claims, agent-run records, "
                "handoffs, session active work, worktree diagnostics, and projection posture"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
        Finding(
            "info",
            f"{code_prefix}-boundary",
            (
                "dashboard data is derived from repo-visible routes and disposable/in-memory projection data; it has no "
                "mutation buttons, daemon authority, lifecycle authority, dispatcher authority, Git authority, or cache truth"
            ),
            ".mylittleharness/generated/projection",
        ),
        Finding(
            "info",
            f"{code_prefix}-agent-packet",
            (
                "agent packet default path: read project-state/roadmap lifecycle posture, inspect dashboard cache posture, "
                "query intelligence for fuzzy route discovery, use MCP read/search/bundle for bounded source context, then verify exact symbols with rg"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
        _authority_cards_finding(inventory, code_prefix),
        _accelerator_adoption_finding(inventory, code_prefix),
    ]


def _dashboard_summary_findings(inventory: Inventory) -> list[Finding]:
    return [
        Finding("info", "dashboard-read-only", f"read-only dashboard cockpit; root_kind={inventory.root_kind}; root={inventory.root}"),
        Finding(
            "info",
            "dashboard-inputs",
            (
                "inputs: project-state, roadmap, claims, agent-run records, handoffs, session active work, "
                "worktree diagnostics, check posture, mlhd runtime posture, and in-memory projection summary"
            ),
        ),
        Finding(
            "info",
            "dashboard-no-runtime-required",
            "dashboard inspect starts no server, daemon, watcher, dispatcher, worker, hook install, network listener, or cache refresh",
        ),
    ]


def _lifecycle_findings(inventory: Inventory) -> list[Finding]:
    data = _state_data(inventory)
    source = inventory.state.rel_path if inventory.state and inventory.state.exists else None
    next_route = _next_legal_dry_run_payload(inventory)
    return [
        Finding(
            "info",
            "dashboard-lifecycle",
            (
                f"plan_status={_value(data, 'plan_status')}; active_plan={_value(data, 'active_plan')}; "
                f"active_phase={_value(data, 'active_phase')}; phase_status={_value(data, 'phase_status')}; "
                f"last_archived_plan={_value(data, 'last_archived_plan')}"
            ),
            source,
        ),
        Finding(
            "info",
            "dashboard-lifecycle-authority",
            "project-state lifecycle fields remain authority; dashboard lifecycle rows are projection only",
            source,
        ),
        Finding(
            "info",
            "dashboard-next-legal-dry-run",
            (
                f"next legal dry-run candidate: {next_route['command']}; "
                "dashboard names this route as advisory navigation only and does not approve running or applying it"
            ),
            source,
        ),
    ]


def _roadmap_findings(inventory: Inventory) -> list[Finding]:
    items, parse_findings = roadmap_items_for_diagnostics(inventory)
    counts = _roadmap_counts(items)
    queue = _roadmap_queue(items)
    details = ", ".join(f"{status}={count}" for status, count in sorted(counts.items())) or "none"
    queue_detail = ", ".join(queue[:5]) if queue else "none"
    findings = [*parse_findings]
    findings.append(Finding("info", "dashboard-roadmap", f"roadmap status counts: {details}", "project/roadmap.md"))
    findings.append(Finding("info", "dashboard-roadmap-queue", f"active/accepted queue: {queue_detail}", "project/roadmap.md"))
    findings.append(Finding("info", "dashboard-roadmap-authority", "roadmap rows are sequencing evidence only and cannot open plans or mark work done from the dashboard", "project/roadmap.md"))
    return findings


def _coordination_findings(inventory: Inventory) -> list[Finding]:
    return [
        *session_active_work_findings(inventory, "dashboard-session-active-work"),
        *worktree_coordination_findings(inventory, code_prefix="dashboard-worktree-coordination"),
        *agent_run_record_findings(inventory, "dashboard-agent-run"),
        *work_claim_status_findings(inventory, "dashboard-work-claim"),
        *handoff_packet_status_findings(inventory, "dashboard-handoff-packet"),
    ]


def _projection_findings(inventory: Inventory) -> list[Finding]:
    projection = build_projection(inventory)
    posture = _cache_posture_payload(inventory, projection)
    refresh_commands = ", ".join(str(command) for command in posture.get("recommended_refresh_commands", [])[:2])
    runtime_dir = inventory.root / ".mylittleharness" / "runtime"
    return [
        Finding(
            "info",
            "dashboard-projection",
            (
                f"in-memory projection: sources={projection.summary.source_count}; "
                f"readable={projection.summary.readable_source_count}; links={projection.summary.link_record_count}; "
                f"fan_in={projection.summary.fan_in_record_count}; relationship_edges={projection.summary.relationship_edge_count}"
            ),
            ".mylittleharness/generated/projection",
        ),
        _runtime_cache_finding(inventory.root, runtime_dir),
        Finding(
            "info",
            "dashboard-projection-authority",
            "generated projection artifacts and runtime cache are optional inputs; source files remain truth when they are missing or stale",
            ".mylittleharness/generated/projection",
        ),
        Finding(
            "info",
            "dashboard-cache-posture",
            (
                "cache_posture schema=mylittleharness.projection-cache-posture.v1; "
                "refresh_by_dashboard=false; commands_are_suggestions_only=true; "
                f"displayed_refresh_commands={refresh_commands}"
            ),
            ".mylittleharness/generated/projection",
        ),
        Finding(
            "info",
            "dashboard-agent-packet",
            (
                "default first context path: dashboard packet, intelligence query, MCP read/search/bundle, then rg exact verification; "
                "dashboard remains read-only"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
    ]


def _alert_findings(coordination: list[Finding]) -> list[Finding]:
    warnings = [finding for finding in coordination if finding.severity == "warn"]
    errors = [finding for finding in coordination if finding.severity == "error"]
    if not warnings and not errors:
        return [
            Finding(
                "info",
                "dashboard-alerts-clean",
                "no warning/error alerts were emitted by dashboard coordination diagnostics; absence of optional records degrades to read-only status",
            )
        ]
    sample = ", ".join(finding.code for finding in [*errors, *warnings][:5])
    return [
        Finding(
            "warn" if warnings else "error",
            "dashboard-alerts",
            f"coordination alerts: errors={len(errors)}; warnings={len(warnings)}; sample={sample}",
        )
    ]


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "dashboard-boundary",
            "dashboard has no mutation buttons and cannot approve lifecycle movement, archive, roadmap status, staging, commit, push, rollback, release, dispatcher work, product-diff acceptance, cache truth, provider output, or daemon authority",
        ),
        Finding(
            "info",
            "dashboard-cache-boundary",
            "dashboard may display disposable projection/runtime posture, but deleting caches must not change repo-visible truth",
        ),
    ]


def _lifecycle_payload(inventory: Inventory) -> dict[str, object]:
    data = _state_data(inventory)
    keys = (
        "project",
        "operating_mode",
        "plan_status",
        "active_plan",
        "active_phase",
        "phase_status",
        "last_archived_plan",
        "product_source_root",
    )
    return {key: data.get(key, "") for key in keys}


def _roadmap_payload(inventory: Inventory) -> dict[str, object]:
    items, parse_findings = roadmap_items_for_diagnostics(inventory)
    return {
        "item_count": len(items),
        "status_counts": dict(sorted(_roadmap_counts(items).items())),
        "active_or_accepted_queue": _roadmap_queue(items)[:10],
        "parse_findings": [finding.to_dict() for finding in parse_findings],
    }


def _coordination_payload(findings: list[Finding]) -> dict[str, object]:
    prefixes = (
        "dashboard-session-active-work",
        "dashboard-worktree-coordination",
        "dashboard-agent-run",
        "dashboard-work-claim",
        "dashboard-handoff-packet",
    )
    counts = {
        prefix: sum(1 for finding in findings if finding.code.startswith(prefix))
        for prefix in prefixes
    }
    return {
        "finding_counts": counts,
        "warning_count": sum(1 for finding in findings if finding.severity == "warn"),
        "error_count": sum(1 for finding in findings if finding.severity == "error"),
    }


def _alert_payload(findings: list[Finding]) -> dict[str, object]:
    warnings = [finding.code for finding in findings if finding.severity == "warn"]
    errors = [finding.code for finding in findings if finding.severity == "error"]
    return {
        "warning_count": len(warnings),
        "error_count": len(errors),
        "warning_codes": warnings[:20],
        "error_codes": errors[:20],
    }


def _roadmap_counts(items: dict[str, object]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in items.values():
        status = str(item.fields.get("status") or "<missing>").strip() or "<missing>"
        counts[status] += 1
    return counts


def _roadmap_queue(items: dict[str, object]) -> list[str]:
    selected = [
        (
            _item_order(item),
            item_id,
            str(item.fields.get("execution_slice") or item_id),
            str(item.fields.get("status") or ""),
        )
        for item_id, item in items.items()
        if str(item.fields.get("status") or "").strip().casefold() in {"active", "accepted"}
    ]
    return [f"{item_id} ({execution_slice}; {status})" for _order, item_id, execution_slice, status in sorted(selected)]


def _item_order(item: object) -> int:
    value = getattr(item, "fields", {}).get("order")
    return value if isinstance(value, int) else 999999


def _runtime_cache_finding(root: Path, runtime_dir: Path) -> Finding:
    try:
        rel_path = runtime_dir.relative_to(root).as_posix()
    except ValueError:
        rel_path = runtime_dir.as_posix()
    if runtime_dir.exists():
        return Finding(
            "info",
            "dashboard-runtime-cache-present",
            f"optional runtime cache path is present but non-authoritative: {rel_path}",
            rel_path,
        )
    return Finding(
        "info",
        "dashboard-runtime-cache-absent",
        "optional dashboard/mlhd runtime cache is absent; cockpit rebuilds from repo-visible routes and in-memory projection",
        rel_path,
    )


def _state_data(inventory: Inventory) -> dict[str, object]:
    if inventory.state and inventory.state.exists:
        return inventory.state.frontmatter.data
    return {}


def _value(data: dict[str, object], key: str) -> str:
    return str(data.get(key) or "<none>")


def dashboard_agent_packet(inventory: Inventory) -> dict[str, object]:
    data = _state_data(inventory)
    adoption = _accelerator_adoption_payload(inventory)
    mcp_tool_coverage = _mcp_tool_coverage_payload()
    exact_verification = _exact_verification_payload()
    next_legal = _next_legal_dry_run_payload(inventory)
    authority_cards = _authority_cards_payload(inventory, next_legal)
    return {
        "schema": "mylittleharness.dashboard-agent-packet.v1",
        "source_refs": [
            "AGENTS.md",
            ".codex/project-workflow.toml",
            "project/project-state.md",
            "project/roadmap.md",
            "project/implementation-plan.md",
        ],
        "readOrder": [
            "AGENTS.md",
            ".codex/project-workflow.toml",
            "project/project-state.md",
            "project/roadmap.md",
            "project/implementation-plan.md when plan_status is active",
        ],
        "recommendedCommands": [
            "mylittleharness --root <root> dashboard --inspect --json",
            "mylittleharness --root <root> intelligence --query \"<task or route question>\"",
            "mylittleharness --root <root> adapter --client-config --target mcp-read-projection",
            "mylittleharness --root <root> adapter --install-client-config --target mcp-read-projection --dry-run",
            "mylittleharness --root <root> mlhd run-once --apply",
            "rg \"<exact symbol or route>\"",
        ],
        "firstPassSequence": [
            "dashboard --inspect --json",
            "intelligence --query for fuzzy route discovery",
            "MCP read_projection/search/related_or_bundle when mounted",
            "mlhd run-once --apply when cache posture or context capsule is stale or missing",
            "rg or mylittleharness.read_source for exact source verification",
        ],
        "mcpToolCoverage": mcp_tool_coverage,
        "exactVerification": exact_verification,
        "contextMemory": context_memory_capsule_payload(inventory),
        "nextLegalDryRun": next_legal,
        "authorityCards": authority_cards,
        "authoritySummary": _authority_cards_summary(authority_cards),
        "acceleratorAdoption": adoption,
        "connectReadiness": connect_readiness_packet(
            inventory,
            agent_packet={"nextLegalDryRun": next_legal, "authorityCards": authority_cards},
            accelerator_adoption=adoption,
        ),
        "lifecycle": {
            "plan_status": str(data.get("plan_status") or ""),
            "active_plan": str(data.get("active_plan") or ""),
            "active_phase": str(data.get("active_phase") or ""),
            "phase_status": str(data.get("phase_status") or ""),
        },
        "boundary": "agent packet is read-only navigation guidance and cannot approve lifecycle movement, repair, archive, staging, commit, or next-plan opening",
    }


def connect_readiness_packet(
    inventory: Inventory,
    *,
    cache_posture: dict[str, object] | None = None,
    agent_packet: dict[str, object] | None = None,
    accelerator_adoption: dict[str, object] | None = None,
) -> dict[str, object]:
    data = _state_data(inventory)
    cache = cache_posture or _cache_posture_payload(inventory)
    components = cache.get("components", {}) if isinstance(cache, dict) else {}
    adoption = accelerator_adoption or _accelerator_adoption_payload(inventory)
    mcp = adoption.get("mcp", {}) if isinstance(adoption.get("mcp"), dict) else {}
    next_legal = (
        agent_packet.get("nextLegalDryRun", {})
        if isinstance(agent_packet, dict) and isinstance(agent_packet.get("nextLegalDryRun"), dict)
        else _next_legal_dry_run_payload(inventory)
    )
    repair_targets = _repair_target_payload(inventory)
    docmap = _docmap_readiness_payload(inventory)
    mlhd = mlhd_freshness_payload(inventory)
    context_memory = context_memory_capsule_payload(inventory)
    plan_status = str(data.get("plan_status") or "")
    authority_cards = (
        agent_packet.get("authorityCards", [])
        if isinstance(agent_packet, dict) and isinstance(agent_packet.get("authorityCards"), list)
        else _authority_cards_payload(inventory, next_legal)
    )
    return {
        "schema": CONNECT_READINESS_SCHEMA,
        "lifecycle": {
            "plan_status": plan_status,
            "active_plan": str(data.get("active_plan") or ""),
            "active_phase": str(data.get("active_phase") or ""),
            "phase_status": str(data.get("phase_status") or ""),
        },
        "hooks": {
            "firstContactCommand": str(adoption.get("firstContactHookCommand") or "mylittleharness --root <root> hooks --run session-start --json"),
            "codexAdapterDryRun": str(adoption.get("codexHookAdapterCommand") or "mylittleharness --root <root> hooks adapter --client codex --dry-run --scope project"),
            "projectHookStatus": _project_hook_status(mcp),
        },
        "mcp": {
            "status": str(mcp.get("status") or "unknown"),
            "mounted": mcp.get("mounted") is True,
            "toolCoverage": adoption.get("mcpToolCoverage", {}),
        },
        "cache": {
            "artifacts": _component_status(components, "artifacts"),
            "sqlite_index": _component_status(components, "sqlite_index"),
            "selfHealCommand": str(cache.get("self_heal_command") or "mylittleharness --root <root> projection --warm-cache --target all"),
            "manualRecoveryCommand": str(cache.get("manual_recovery_command") or "mylittleharness --root <root> projection --warm-cache --target all"),
            "readOnlyPayload": cache.get("read_only") is True,
            "readOnlySurfacesExecuteRefresh": cache.get("read_only_surfaces_execute_refresh") is True,
            "displayedCommandsOnly": cache.get("displayed_commands_only") is True,
            "generatedCacheMutationBoundary": str(cache.get("generated_cache_mutation_boundary") or ".mylittleharness/generated/projection"),
            "manualRecoveryWriteClass": str(cache.get("manual_recovery_write_class") or "disposable-generated-cache-only"),
            "commandBoundary": cache.get("command_boundary", {}),
        },
        "mlhd": {
            "controlStatus": str(mlhd.get("control_status") or "unknown"),
            "runtimeCacheStatus": str(mlhd.get("runtime_cache_status") or "unknown"),
            "pidStatus": str(mlhd.get("pid_status") or "unknown"),
            "lastTickUtc": str(mlhd.get("last_tick_utc") or ""),
            "lastAction": str(mlhd.get("last_action") or ""),
            "lastRefreshStatus": str(mlhd.get("last_refresh_status") or ""),
            "lastSuccessfulRefreshUtc": str(mlhd.get("last_successful_refresh_utc") or ""),
            "lastFailedRefreshUtc": str(mlhd.get("last_failed_refresh_utc") or ""),
            "dirtyCount": int(mlhd.get("dirty_count") or 0),
            "changedPathCount": int(mlhd.get("changed_path_count") or 0),
            "nextSafeCommand": str(mlhd.get("next_safe_command") or "mylittleharness --root <root> mlhd run-once --dry-run"),
        },
        "contextMemory": {
            "status": str(context_memory.get("status") or "unknown"),
            "capsuleRelPath": str(context_memory.get("capsule_rel_path") or ""),
            "capsuleId": str(context_memory.get("capsule_id") or ""),
            "sourceRefCount": int(context_memory.get("source_ref_count") or 0),
            "nextSafeCommand": str(context_memory.get("next_safe_command") or "mylittleharness --root <root> mlhd run-once --apply"),
        },
        "docs": docmap,
        "repairTargets": repair_targets,
        "authorityCards": authority_cards,
        "writeback": {
            "requiredWhenPlanStatusActive": plan_status.casefold() == "active",
            "dryRunCommand": str(next_legal.get("command") or ""),
            "reason": str(next_legal.get("reason") or ""),
        },
        "nextSafeCommand": _readiness_next_safe_command(next_legal, cache, repair_targets),
        "recoveryCommand": _readiness_recovery_command(cache, repair_targets),
        "boundary": (
            "connect readiness is an LLM-compact action packet only; it cannot approve lifecycle movement, repair, "
            "archive, roadmap status, staging, commit, push, release, provider routing, source mutation, or cache truth"
        ),
    }


def connect_readiness_findings(inventory: Inventory, code_prefix: str = "connect-readiness") -> list[Finding]:
    packet = connect_readiness_packet(inventory)
    lifecycle = packet["lifecycle"]
    cache = packet["cache"]
    repair = packet["repairTargets"]
    docs = packet["docs"]
    writeback = packet["writeback"]
    hooks = packet["hooks"]
    mcp = packet["mcp"]
    mlhd = packet["mlhd"]
    context_memory = packet["contextMemory"]
    return [
        Finding(
            "info",
            f"{code_prefix}-action-packet",
            (
                "compact action packet: "
                f"plan_status={lifecycle['plan_status'] or '<none>'}; active_phase={lifecycle['active_phase'] or '<none>'}; "
                f"phase_status={lifecycle['phase_status'] or '<none>'}; hooks={hooks['projectHookStatus']}; "
                f"mcp={mcp['status']}; cache artifacts={cache['artifacts']}; sqlite_index={cache['sqlite_index']}; "
                f"mlhd={mlhd['controlStatus']}; dirty_count={mlhd['dirtyCount']}; "
                f"context_memory={context_memory['status']}; "
                f"docmap={docs['docmapStatus']}; writeback_required={str(writeback['requiredWhenPlanStatusActive']).lower()}; "
                f"next_safe={packet['nextSafeCommand']}"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
        Finding(
            "info",
            f"{code_prefix}-repair-targets",
            (
                f"required_repair_targets={repair['requiredMissingCount']}; "
                f"optional_repair_targets={repair['optionalMissingCount']}; "
                f"required_examples={_display_examples(repair['requiredExamples'])}; "
                f"optional_examples={_display_examples(repair['optionalExamples'])}; "
                f"recovery={packet['recoveryCommand']}"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
        Finding(
            "info",
            f"{code_prefix}-docs-docmap",
            (
                f"docs_decision={docs['docsDecision']}; docmap_hygiene={docs['docmapStatus']}; "
                f"candidate_check={docs['hygieneCheckCommand']}; repair_preview={docs['repairPreviewCommand']}"
            ),
            ".agents/docmap.yaml",
        ),
        _authority_cards_finding(inventory, code_prefix),
        Finding(
            "info",
            f"{code_prefix}-boundary",
            str(packet["boundary"]),
        ),
    ]


def _authority_cards_payload(inventory: Inventory, next_legal: dict[str, object] | None = None) -> list[dict[str, object]]:
    data = _state_data(inventory)
    plan_status = str(data.get("plan_status") or "").strip().casefold()
    active_plan = str(data.get("active_plan") or "").strip() or ACTIVE_PLAN_ROUTE_REL
    lifecycle_refs = [STATE_ROUTE_REL]
    if plan_status == "active":
        lifecycle_refs.append(active_plan)
    next_legal = next_legal or _next_legal_dry_run_payload(inventory)
    blocked_actions = [
        "apply",
        "closeout",
        "archive",
        "roadmap done",
        "staging",
        "commit",
        "push",
        "release",
    ]
    return [
        {
            "id": "lifecycle",
            "label": "Lifecycle",
            "authorityRefs": lifecycle_refs,
            "nonAuthority": ["check output", "dashboard output", "hook output", "chat memory"],
            "nextSafeCommand": str(next_legal.get("command") or "mylittleharness --root <root> check"),
            "cannotApprove": blocked_actions,
            "boundary": "project-state lifecycle frontmatter wins; reports and hooks are navigation only",
        },
        {
            "id": "roadmap",
            "label": "Roadmap",
            "authorityRefs": [ROADMAP_ROUTE_REL],
            "nonAuthority": ["roadmap readiness summaries", "dashboard queue rows", "suggest output"],
            "nextSafeCommand": _roadmap_authority_next_safe_command(inventory, plan_status),
            "cannotApprove": blocked_actions,
            "boundary": "roadmap rows sequence accepted work but cannot open plans or mark work done without explicit rails",
        },
        {
            "id": "projection",
            "label": "Projection Cache",
            "authorityRefs": ["repo-visible source files"],
            "nonAuthority": [ARTIFACT_DIR_REL, MLHD_RUNTIME_DIR_REL],
            "nextSafeCommand": "mylittleharness --root <root> projection --inspect --target all",
            "cannotApprove": blocked_actions,
            "boundary": "generated projection and runtime cache are disposable accelerators; source files remain truth",
        },
        {
            "id": "docs",
            "label": "Docs And Docmap",
            "authorityRefs": [DOCS_GLOB_REL, WORKFLOW_SPECS_GLOB_REL],
            "nonAuthority": [f"{DOCMAP_ROUTE_REL} as routing aid", "docs/docmap hygiene summaries"],
            "nextSafeCommand": "mylittleharness --root <root> check --focus validation",
            "cannotApprove": blocked_actions,
            "boundary": "docmap routes docs impact but does not override product docs, specs, or lifecycle docs_decision",
        },
        {
            "id": "verification",
            "label": "Exact Verification",
            "authorityRefs": ["source files", "repo-visible verification evidence"],
            "nonAuthority": ["MCP search summaries", "SQLite full-text hits", "dashboard summaries"],
            "nextSafeCommand": 'rg "<exact symbol or route>"',
            "cannotApprove": blocked_actions,
            "boundary": "navigation hits must be reconciled against exact source before edits or closeout claims",
        },
    ]


def _roadmap_authority_next_safe_command(inventory: Inventory, plan_status: str) -> str:
    if plan_status == "active":
        return "mylittleharness --root <root> check"
    queue = _roadmap_payload(inventory).get("active_or_accepted_queue", [])
    item_id = str(queue[0]).split(" ", 1)[0] if queue else ""
    if item_id:
        return f"mylittleharness --root <root> plan --dry-run --roadmap-item {item_id}"
    return "mylittleharness --root <root> check"


def _authority_cards_summary(cards: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for card in cards:
        card_id = str(card.get("id") or "")
        refs = card.get("authorityRefs", [])
        if card_id and isinstance(refs, list) and refs:
            parts.append(f"{card_id}={'+'.join(str(ref) for ref in refs[:2])}")
    return "; ".join(parts)


def _authority_cards_finding(inventory: Inventory, code_prefix: str) -> Finding:
    cards = _authority_cards_payload(inventory)
    next_legal = next((card for card in cards if card.get("id") == "lifecycle"), {})
    return Finding(
        "info",
        f"{code_prefix}-authority-cards",
        (
            f"authority cards: {_authority_cards_summary(cards)}; "
            f"next_legal={next_legal.get('nextSafeCommand', 'mylittleharness --root <root> check')}; "
            "non-authority outputs include dashboard/check/hooks/cache/search; cards cannot approve apply, closeout, archive, staging, commit, or push"
        ),
        STATE_ROUTE_REL if inventory.state and inventory.state.exists else None,
    )


def _accelerator_adoption_payload(inventory: Inventory) -> dict[str, object]:
    return {
        "schema": "mylittleharness.agent-accelerator-adoption.v1",
        "dashboardPacketAvailable": True,
        "mcp": codex_mcp_adoption_payload(inventory),
        "mcpToolCoverage": _mcp_tool_coverage_payload(),
        "firstContactHookCommand": "mylittleharness --root <root> hooks --run session-start --json",
        "codexHookAdapterCommand": "mylittleharness --root <root> hooks adapter --client codex --dry-run --scope project",
        "mlhdRefreshCommand": "mylittleharness --root <root> mlhd run-once --apply",
        "projectionWarmCacheCommand": "mylittleharness --root <root> projection --warm-cache --target all",
        "exactVerification": _exact_verification_payload(),
        "rgVerificationRequired": True,
        "sequence": [
            "dashboard packet",
            "MCP read/search/bundle when mounted",
            "Codex native hook adapter when project-local hooks are explicitly applied",
            "mlhd projection refresh tick when stale or missing",
            "projection warm-cache only as manual recovery/debug",
            "rg exact verification before edits or closeout claims",
        ],
        "boundary": (
            "accelerators are first-contact helpers only; they cannot approve lifecycle movement, repair, archive, "
            "roadmap status, staging, commit, push, provider routing, product diffs, or cache truth"
        ),
    }


def _mcp_tool_coverage_payload() -> dict[str, object]:
    return {
        "read_projection": "current root posture, cache posture, source records, adapter boundary, and next-safe navigation hints",
        "read_source": "bounded source slices for exact line-level verification without copying whole route bodies",
        "search": "source-verified exact, path, and SQLite full-text lookup when the generated index is current",
        "related_or_bundle": "links, fan-in, relationship rows, and nearby source bundle records for impact navigation",
        "boundary": "MCP tools are read-only accelerators and cannot approve lifecycle, mutation, archive, staging, commit, push, or cache truth",
    }


def _exact_verification_payload() -> dict[str, object]:
    return {
        "required": True,
        "methods": ["rg", "mylittleharness.read_source", "direct source reads"],
        "reason": "dashboard, MCP, SQLite, and hooks accelerate navigation; exact symbols, files, and closeout claims still need source verification",
    }


def _accelerator_adoption_finding(inventory: Inventory, code_prefix: str) -> Finding:
    adoption = _accelerator_adoption_payload(inventory)
    mcp = adoption["mcp"]
    assert isinstance(mcp, dict)
    status = str(mcp.get("status") or "unknown")
    return Finding(
        "info",
        f"{code_prefix}-accelerator-adoption",
        (
            f"first-contact accelerators: dashboard_packet=available; mcp={status}; "
            "native_hooks=`mylittleharness --root <root> hooks --run session-start|user-prompt-submit|pre-tool-use|post-tool-use|stop --json`; "
            "codex_hook_adapter=`mylittleharness --root <root> hooks adapter --client codex --dry-run --scope project`; "
            "mlhd_refresh_command=`mylittleharness --root <root> mlhd run-once --apply`; "
            "projection_warm_cache_recovery=`mylittleharness --root <root> projection --warm-cache --target all`; "
            "rg_verification=required; config_merge=idempotent-explicit"
        ),
        "project/project-state.md" if inventory.state and inventory.state.exists else None,
    )


def _cache_posture_payload(inventory: Inventory, projection=None) -> dict[str, object]:
    projection = projection or build_projection(inventory)
    return projection_cache_posture_payload(
        inspect_projection_artifacts(inventory, projection),
        inspect_projection_index(inventory, projection),
    )


def _component_status(components: dict[str, object], name: str) -> str:
    component = components.get(name, {}) if isinstance(components, dict) else {}
    if isinstance(component, dict):
        return str(component.get("status") or "unknown")
    return "unknown"


def _project_hook_status(mcp: dict[str, object]) -> str:
    project_hooks = mcp.get("projectHooks") if isinstance(mcp, dict) else {}
    if isinstance(project_hooks, dict):
        return str(project_hooks.get("status") or "unknown")
    return "unknown"


def _docmap_readiness_payload(inventory: Inventory) -> dict[str, object]:
    docmap = inventory.surface_by_rel.get(".agents/docmap.yaml")
    docs_decision = _active_plan_docs_decision(inventory)
    if docmap is None or not docmap.exists:
        status = "missing"
    elif docmap.read_error:
        status = "unreadable"
    else:
        status = "present"
    return {
        "docmapStatus": status,
        "docsDecision": docs_decision,
        "hygieneCheckCommand": "mylittleharness --root <root> check --focus validation",
        "repairPreviewCommand": "mylittleharness --root <root> repair --dry-run",
        "candidateTargets": [
            ".agents/docmap.yaml",
            "README.md",
            "docs/README.md",
            "docs/specs/adapter-boundary.md",
            "docs/specs/attach-repair-status-cli.md",
            "docs/specs/generated-state-search-and-sqlite.md",
            "docs/specs/metadata-routing-and-evidence.md",
        ],
        "roleMetadata": {
            "docmapIsRoutingAid": True,
            "productDocsAreLightweight": True,
            "strictSpecPostureFields": ["spec_status", "implementation_posture"],
            "strictSpecCandidates": ["project/specs/**/*.md", "docs/specs/**/*.md"],
            "normalizationDryRunCommand": "mylittleharness --root <root> repair --dry-run",
        },
    }


def _active_plan_docs_decision(inventory: Inventory) -> str:
    plan = inventory.active_plan_surface
    if plan and plan.exists and plan.frontmatter.data.get("docs_decision"):
        return str(plan.frontmatter.data.get("docs_decision") or "")
    state = _state_data(inventory)
    return str(state.get("docs_decision") or "unknown")


def _repair_target_payload(inventory: Inventory) -> dict[str, object]:
    required = _missing_surface_examples(inventory, required=True)
    optional = _missing_surface_examples(inventory, required=False)
    return {
        "requiredMissingCount": required[0],
        "requiredExamples": required[1],
        "optionalMissingCount": optional[0],
        "optionalExamples": optional[1],
        "repairDryRunCommand": "mylittleharness --root <root> repair --dry-run",
    }


def _missing_surface_examples(inventory: Inventory, *, required: bool) -> tuple[int, list[str]]:
    missing = [
        surface.rel_path
        for surface in inventory.surfaces
        if surface.required is required and (not surface.exists or bool(surface.read_error))
    ]
    return len(missing), missing[:5]


def _readiness_next_safe_command(
    next_legal: dict[str, object],
    cache: dict[str, object],
    repair_targets: dict[str, object],
) -> str:
    if int(repair_targets.get("requiredMissingCount") or 0) > 0:
        return str(repair_targets.get("repairDryRunCommand") or "mylittleharness --root <root> repair --dry-run")
    components = cache.get("components", {}) if isinstance(cache, dict) else {}
    if _component_status(components, "artifacts") not in {"current", "unknown"} or _component_status(components, "sqlite_index") not in {"current", "unknown"}:
        return str(cache.get("self_heal_command") or "mylittleharness --root <root> projection --warm-cache --target all")
    return str(next_legal.get("command") or "mylittleharness --root <root> check")


def _readiness_recovery_command(cache: dict[str, object], repair_targets: dict[str, object]) -> str:
    if int(repair_targets.get("requiredMissingCount") or 0) > 0:
        return str(repair_targets.get("repairDryRunCommand") or "mylittleharness --root <root> repair --dry-run")
    components = cache.get("components", {}) if isinstance(cache, dict) else {}
    if _component_status(components, "artifacts") != "current" or _component_status(components, "sqlite_index") != "current":
        return str(cache.get("self_heal_command") or "mylittleharness --root <root> projection --warm-cache --target all")
    return "mylittleharness --root <root> check"


def _display_examples(examples: object) -> str:
    if isinstance(examples, list) and examples:
        return ", ".join(str(item) for item in examples[:5])
    return "none"


def mlhd_freshness_payload(inventory: Inventory) -> dict[str, object]:
    runtime = dict(mlhd_runtime_payload(inventory))
    control = inspect_mlhd_control_state(inventory)
    pulse = runtime.get("projection_pulse") if isinstance(runtime.get("projection_pulse"), dict) else {}
    runtime.update(
        {
            "control_status": str(control.get("control_status") or "unknown"),
            "pid_status": str(control.get("pid_status") or "unknown"),
            "last_action": str(control.get("last_action") or ""),
            "last_tick_utc": str(control.get("heartbeat_at_utc") or ""),
            "last_refresh_status": str(pulse.get("last_refresh_status") or ""),
            "last_successful_refresh_utc": str(pulse.get("last_successful_refresh_utc") or ""),
            "last_failed_refresh_utc": str(pulse.get("last_failed_refresh_utc") or ""),
            "dirty_count": int(pulse.get("dirty_marker_count") or 0),
            "changed_path_count": int(pulse.get("changed_path_count") or 0),
            "next_safe_command": str(pulse.get("next_safe_command") or "mylittleharness --root <root> mlhd run-once --dry-run"),
        }
    )
    return runtime


def _mlhd_freshness_findings(inventory: Inventory, code_prefix: str = "dashboard-mlhd") -> list[Finding]:
    mlhd = mlhd_freshness_payload(inventory)
    return [
        Finding(
            "info" if mlhd["control_status"] not in {"invalid", "stale"} else "warn",
            f"{code_prefix}-control-freshness",
            (
                f"mlhd control_status={mlhd['control_status']}; runtime_cache={mlhd['runtime_cache_status']}; "
                f"pid_status={mlhd['pid_status']}; last_tick={mlhd['last_tick_utc'] or '<none>'}; "
                f"last_action={mlhd['last_action'] or '<none>'}"
            ),
            MLHD_RUNTIME_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-refresh-freshness",
            (
                f"projection dirty_count={mlhd['dirty_count']}; changed_path_count={mlhd['changed_path_count']}; "
                f"last_refresh={mlhd['last_refresh_status'] or '<none>'}; "
                f"last_success={mlhd['last_successful_refresh_utc'] or '<none>'}; "
                f"last_failure={mlhd['last_failed_refresh_utc'] or '<none>'}; next_safe={mlhd['next_safe_command']}"
            ),
            ARTIFACT_DIR_REL,
        ),
    ]


def _dashboard_source_refs(sections: list[tuple[str, list[Finding]]]) -> list[str]:
    refs = {
        "AGENTS.md",
        ".codex/project-workflow.toml",
        "project/project-state.md",
        "project/roadmap.md",
    }
    for _section, findings in sections:
        for finding in findings:
            if finding.source:
                refs.add(str(finding.source))
    return sorted(refs)


def _next_legal_dry_run_payload(inventory: Inventory) -> dict[str, object]:
    data = _state_data(inventory)
    plan_status = str(data.get("plan_status") or "").strip().casefold()
    source_refs = ["project/project-state.md"]
    if plan_status == "active":
        active_plan = str(data.get("active_plan") or "project/implementation-plan.md").strip() or "project/implementation-plan.md"
        source_refs.append(active_plan)
        command = "mylittleharness --root <root> writeback --dry-run --phase-status complete --docs-decision uncertain"
        reason = "active plan phase movement must be previewed through writeback after deterministic phase evidence exists"
    else:
        queue = _roadmap_payload(inventory).get("active_or_accepted_queue", [])
        item_id = str(queue[0]).split(" ", 1)[0] if queue else ""
        if item_id:
            source_refs.append("project/roadmap.md")
            command = f"mylittleharness --root <root> plan --dry-run --roadmap-item {item_id}"
            reason = "accepted roadmap work must be previewed before opening an active plan"
        else:
            command = "mylittleharness --root <root> check"
            reason = "no active plan or accepted roadmap item was found; start with read-only validation"
    return {
        "command": command,
        "source_refs": source_refs,
        "reason": reason,
        "read_only_preview": True,
        "approves_lifecycle": False,
        "approves_archive": False,
        "approves_roadmap_done": False,
        "approves_git": False,
        "boundary": "dashboard names a legal dry-run candidate only; it does not approve apply, closeout, archive, staging, commit, push, release, or product-diff acceptance",
    }
