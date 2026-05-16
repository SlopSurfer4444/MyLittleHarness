from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .adapter import codex_mcp_adoption_payload
from .claims import work_claim_status_findings
from .evidence import agent_run_record_findings, lifecycle_mutation_provenance_findings
from .handoff import handoff_packet_status_findings
from .inventory import Inventory
from .lifecycle_focus import session_active_work_findings
from .models import Finding
from .projection import build_projection, projection_summary_to_dict
from .projection_artifacts import (
    ARTIFACT_DIR_REL,
    ARTIFACT_DIRTY_MARKER_NAME,
    CACHE_OPERATION_MARKER_NAME,
    INDEX_DIRTY_MARKER_NAME,
    artifact_dir,
    inspect_projection_artifacts,
    projection_cache_posture_payload,
)
from .projection_index import inspect_projection_index
from .roadmap import roadmap_items_for_diagnostics
from .vcs import worktree_coordination_findings


DASHBOARD_SCHEMA = "mylittleharness.dashboard.v1"
MLHD_RUNTIME_SCHEMA = "mylittleharness.mlhd-runtime.v1"
MLHD_RUNTIME_DIR_REL = ".mylittleharness/runtime/mlhd"


def dashboard_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    coordination = _coordination_findings(inventory)
    runtime = mlhd_runtime_findings(inventory)
    return [
        ("Dashboard", _dashboard_summary_findings(inventory)),
        ("Lifecycle", _lifecycle_findings(inventory)),
        ("Roadmap", _roadmap_findings(inventory)),
        ("Coordination", coordination),
        ("mlhd Runtime", runtime),
        ("Projection", _projection_findings(inventory)),
        ("Lifecycle Provenance", lifecycle_mutation_provenance_findings(inventory, "dashboard-lifecycle-provenance")),
        ("Alerts", _alert_findings([*coordination, *runtime])),
        ("Boundary", _boundary_findings()),
    ]


def dashboard_payload(inventory: Inventory, sections: list[tuple[str, list[Finding]]] | None = None) -> dict[str, object]:
    sections = dashboard_sections(inventory) if sections is None else sections
    findings = [finding for _section, section_findings in sections for finding in section_findings]
    return {
        "schema": DASHBOARD_SCHEMA,
        "root": str(inventory.root),
        "root_kind": inventory.root_kind,
        "read_only": True,
        "source_refs": _dashboard_source_refs(sections),
        "lifecycle": _lifecycle_payload(inventory),
        "roadmap": _roadmap_payload(inventory),
        "mlhd": mlhd_runtime_payload(inventory),
        "projection": projection_summary_to_dict(build_projection(inventory)),
        "cachePosture": _cache_posture_payload(inventory),
        "agentPacket": dashboard_agent_packet(inventory),
        "acceleratorAdoption": _accelerator_adoption_payload(inventory),
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
            f"cache_posture schema=mylittleharness.projection-cache-posture.v1; refresh_by_dashboard=false; next_safe={refresh_commands}",
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
            "mylittleharness --root <root> projection --warm-cache --target all",
            "rg \"<exact symbol or route>\"",
        ],
        "nextLegalDryRun": _next_legal_dry_run_payload(inventory),
        "acceleratorAdoption": adoption,
        "lifecycle": {
            "plan_status": str(data.get("plan_status") or ""),
            "active_plan": str(data.get("active_plan") or ""),
            "active_phase": str(data.get("active_phase") or ""),
            "phase_status": str(data.get("phase_status") or ""),
        },
        "boundary": "agent packet is read-only navigation guidance and cannot approve lifecycle movement, repair, archive, staging, commit, or next-plan opening",
    }


def _accelerator_adoption_payload(inventory: Inventory) -> dict[str, object]:
    return {
        "schema": "mylittleharness.agent-accelerator-adoption.v1",
        "dashboardPacketAvailable": True,
        "mcp": codex_mcp_adoption_payload(inventory),
        "firstContactHookCommand": "mylittleharness --root <root> hooks --run session-start --json",
        "codexHookAdapterCommand": "mylittleharness --root <root> hooks adapter --client codex --dry-run --scope project",
        "projectionWarmCacheCommand": "mylittleharness --root <root> projection --warm-cache --target all",
        "rgVerificationRequired": True,
        "sequence": [
            "dashboard packet",
            "MCP read/search/bundle when mounted",
            "Codex native hook adapter when project-local hooks are explicitly applied",
            "projection warm-cache when stale or missing",
            "rg exact verification before edits or closeout claims",
        ],
        "boundary": (
            "accelerators are first-contact helpers only; they cannot approve lifecycle movement, repair, archive, "
            "roadmap status, staging, commit, push, provider routing, product diffs, or cache truth"
        ),
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
            "projection_warm_cache_command=`mylittleharness --root <root> projection --warm-cache --target all`; "
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


def mlhd_runtime_findings(inventory: Inventory, code_prefix: str = "dashboard-mlhd") -> list[Finding]:
    posture = mlhd_runtime_payload(inventory)
    pulse = projection_pulse_payload(inventory)
    runtime_dir_rel = str(posture["runtime_dir"])
    findings = [
        Finding(
            "info",
            f"{code_prefix}-optional-runtime",
            (
                "mlhd runtime is optional cockpit support for read-only logs, process/session posture, notifications, "
                "WebSocket update posture, projection refresh cues, and attach/watch convenience"
            ),
            runtime_dir_rel,
        )
    ]
    status = posture["runtime_cache_status"]
    if status == "present":
        examples = ", ".join(str(item) for item in posture["cache_file_examples"]) or "none"
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-runtime-cache-present",
                (
                    f"optional mlhd runtime cache is present; cache_files={posture['cache_file_count']}; "
                    f"examples={examples}; cache remains disposable"
                ),
                runtime_dir_rel,
            )
        )
    elif status == "invalid":
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-runtime-cache-invalid",
                "optional mlhd runtime cache path is not a regular directory; ignoring it as non-authoritative runtime state",
                runtime_dir_rel,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-runtime-cache-absent",
                "mlhd runtime cache is absent; dashboard and check posture continue from repo-visible route files",
                runtime_dir_rel,
            )
        )
    findings.extend(
        [
            Finding(
                "info",
                f"{code_prefix}-disposable-cache-boundary",
                "deleting .mylittleharness/runtime/mlhd must not change active, accepted, verified, blocked, closeable, or archived repo truth",
                runtime_dir_rel,
            ),
            Finding(
                "info",
                f"{code_prefix}-durable-mutation-boundary",
                "durable mutations must delegate to explicit MyLittleHarness CLI dry-run/apply rails; mlhd cache cannot write lifecycle, roadmap, archive, Git, or release authority",
                runtime_dir_rel,
            ),
            Finding(
                "info",
                f"{code_prefix}-localhost-defaults",
                "this cockpit starts no listener; any future mlhd serve rail must be explicit, local-only by default, and avoid provider credential storage",
                runtime_dir_rel,
            ),
            Finding(
                "info",
                f"{code_prefix}-authority-boundary",
                "mlhd cache, logs, notifications, process observations, and WebSocket events are adapter data only; repo-visible files remain authority",
                runtime_dir_rel,
            ),
            Finding(
                "info" if pulse["status"] in {"idle", "warmable"} else "warn",
                f"{code_prefix}-projection-pulse",
                (
                    f"projection pulse status={pulse['status']}; dirty_since={pulse['dirty_since_utc'] or '<none>'}; "
                    f"last_operation={pulse['operation'] or '<none>'}; optional warm-cache ticks cannot write lifecycle authority"
                ),
                ARTIFACT_DIR_REL,
            ),
        ]
    )
    return findings


def mlhd_runtime_payload(inventory: Inventory) -> dict[str, object]:
    runtime_dir = inventory.root / MLHD_RUNTIME_DIR_REL
    status = _runtime_cache_status(runtime_dir)
    cache_files = _runtime_cache_files(inventory.root, runtime_dir) if status == "present" else []
    return {
        "schema": MLHD_RUNTIME_SCHEMA,
        "runtime_dir": MLHD_RUNTIME_DIR_REL,
        "runtime_cache_status": status,
        "runtime_dir_exists": runtime_dir.exists(),
        "cache_file_count": len(cache_files),
        "cache_file_examples": cache_files[:10],
        "disposable_cache": True,
        "network_listener_started": False,
        "default_bind_host": "127.0.0.1",
        "durable_mutations_delegate_to_cli": True,
        "stores_provider_credentials": False,
        "approves_lifecycle": False,
        "projection_pulse": projection_pulse_payload(inventory),
    }


def projection_pulse_payload(inventory: Inventory) -> dict[str, object]:
    dirty_payloads = [_read_json_marker(inventory.root, ARTIFACT_DIRTY_MARKER_NAME), _read_json_marker(inventory.root, INDEX_DIRTY_MARKER_NAME)]
    dirty_payloads = [payload for payload in dirty_payloads if payload]
    operation_payload = _read_json_marker(inventory.root, CACHE_OPERATION_MARKER_NAME)
    dirty_since_values = [str(payload.get("dirty_since_utc") or "") for payload in dirty_payloads if isinstance(payload, dict)]
    status = "updating-or-interrupted" if operation_payload else "warmable" if dirty_payloads else "idle"
    return {
        "schema": "mylittleharness.projection-pulse.v1",
        "status": status,
        "dirty": bool(dirty_payloads),
        "dirty_since_utc": sorted(value for value in dirty_since_values if value)[:1][0] if any(dirty_since_values) else "",
        "dirty_marker_count": len(dirty_payloads),
        "operation": str(operation_payload.get("operation") or "") if isinstance(operation_payload, dict) else "",
        "operation_created_at_utc": str(operation_payload.get("created_at_utc") or "") if isinstance(operation_payload, dict) else "",
        "warm_cache_command": "mylittleharness --root <root> projection --warm-cache --target all",
        "authority": "watch/pulse state is disposable; source files and lifecycle routes remain authoritative",
    }


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


def _runtime_cache_status(runtime_dir: Path) -> str:
    if runtime_dir.is_symlink() or (runtime_dir.exists() and not runtime_dir.is_dir()):
        return "invalid"
    return "present" if runtime_dir.exists() else "absent"


def _runtime_cache_files(root: Path, runtime_dir: Path) -> list[str]:
    files: list[str] = []
    for path in sorted(runtime_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            files.append(path.relative_to(root).as_posix())
        except ValueError:
            continue
    return files


def _read_json_marker(root: Path, name: str) -> dict[str, object]:
    path = artifact_dir(root) / name
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
