from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from .dashboard import dashboard_agent_packet, dashboard_payload
from .inventory import Inventory
from .models import Finding
from .preflight import preflight_sections


HOOK_PRE_COMMIT = "git-pre-commit"
HOOK_AGENT_STATUS = "agent-status"
HOOK_SESSION_START = "session-start"
INSTALLABLE_HOOKS = (HOOK_PRE_COMMIT,)
RUNNABLE_HOOKS = (HOOK_PRE_COMMIT, HOOK_AGENT_STATUS, HOOK_SESSION_START)
FIRST_CONTACT_HOOKS = (HOOK_SESSION_START,)


@dataclass(frozen=True)
class HookInstallRequest:
    hook_id: str
    force: bool = False


def make_hook_install_request(args) -> HookInstallRequest:
    return HookInstallRequest(hook_id=args.hook, force=bool(getattr(args, "force", False)))


def hooks_doctor_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    return [
        ("Summary", _hooks_summary_findings(inventory)),
        ("Install Targets", _hook_install_target_findings(inventory, HookInstallRequest(HOOK_PRE_COMMIT))),
        ("Runnable Events", _hook_event_findings()),
        ("Boundary", _hook_boundary_findings()),
    ]


def hook_install_dry_run_findings(inventory: Inventory, request: HookInstallRequest) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "hooks-install-dry-run",
            f"hook install preview only; hook_id={request.hook_id}; no files, Git config, lifecycle state, caches, or generated reports were written",
        )
    ]
    findings.extend(_hook_install_target_findings(inventory, request))
    errors = _hook_install_errors(inventory, request)
    if errors:
        findings.extend(errors)
    else:
        target = _hook_target(inventory.root, request.hook_id)
        findings.append(
            Finding(
                "info",
                "hooks-install-plan",
                f"would install warning-only {request.hook_id} shim at {_rel_path(inventory.root, target)}",
                _rel_path(inventory.root, target),
            )
        )
    findings.extend(_hook_boundary_findings())
    return findings


def hook_install_apply_findings(inventory: Inventory, request: HookInstallRequest) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "hooks-install-apply",
            f"explicit hook install apply started; hook_id={request.hook_id}; this route writes only the selected hook shim",
        )
    ]
    errors = _hook_install_errors(inventory, request)
    if errors:
        findings.extend(errors)
        findings.extend(_hook_boundary_findings())
        return findings

    target = _hook_target(inventory.root, request.hook_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    before = target.read_text(encoding="utf-8") if target.exists() else None
    content = render_hook_shim(inventory.root, request.hook_id)
    target.write_text(content, encoding="utf-8")
    if before == content:
        findings.append(Finding("info", "hooks-install-unchanged", f"hook shim already current at {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    else:
        findings.append(Finding("info", "hooks-install-written", f"installed warning-only hook shim at {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    findings.extend(_hook_boundary_findings())
    return findings


def hook_run_sections(inventory: Inventory, hook_id: str, hook_args: list[str]) -> list[tuple[str, list[Finding]]]:
    event_findings = [
        Finding("info", "hooks-run-event", f"hook event: {hook_id}; arg_count={len(_clean_hook_args(hook_args))}"),
        Finding("info", "hooks-run-root", f"root kind: {inventory.root_kind}; root={inventory.root}"),
        Finding(
            "info",
            "hooks-run-adapter",
            "hook run is a foreground sensor/context adapter; it reads repo-visible files and emits advisory findings only",
        ),
    ]
    if hook_id not in RUNNABLE_HOOKS:
        event_findings.append(Finding("error", "hooks-run-unknown", f"unsupported hook event: {hook_id}"))
    if hook_id == HOOK_AGENT_STATUS:
        event_findings.append(
            Finding(
                "info",
                "hooks-run-agent-status",
                "agent-status hook currently reports root posture only; repo-visible claims, runs, handoffs, and project-state remain authority",
            )
        )
        return [("Event", event_findings), ("Boundary", _hook_boundary_findings())]
    if hook_id in FIRST_CONTACT_HOOKS:
        return [
            ("Event", event_findings),
            ("First Contact Context", _first_contact_context_findings(inventory, hook_id)),
            ("Boundary", _hook_boundary_findings()),
        ]
    return [("Event", event_findings), *preflight_sections(inventory), ("Boundary", _hook_boundary_findings())]


def hook_event_payload(inventory: Inventory, hook_id: str, hook_args: list[str]) -> dict[str, object]:
    sections = hook_run_sections(inventory, hook_id, hook_args)
    findings = [finding for _section, section_findings in sections for finding in section_findings]
    dashboard = dashboard_payload(inventory) if hook_id in FIRST_CONTACT_HOOKS else {}
    agent_packet = dashboard.get("agentPacket") if isinstance(dashboard.get("agentPacket"), dict) else dashboard_agent_packet(inventory)
    cache_posture = dashboard.get("cachePosture") if isinstance(dashboard.get("cachePosture"), dict) else {}
    accelerator_adoption = (
        agent_packet.get("acceleratorAdoption") if isinstance(agent_packet.get("acceleratorAdoption"), dict) else dashboard.get("acceleratorAdoption")
    )
    if not isinstance(accelerator_adoption, dict):
        accelerator_adoption = {}
    lifecycle = agent_packet.get("lifecycle") if isinstance(agent_packet.get("lifecycle"), dict) else {}
    status = _hook_status(findings)
    status_message = _hook_status_message(hook_id, lifecycle, cache_posture)
    additional_context = _hook_additional_context(agent_packet, cache_posture, accelerator_adoption) if hook_id in FIRST_CONTACT_HOOKS else ""
    return {
        "schema": "mylittleharness.hook-event.v1",
        "event": hook_id,
        "status": status,
        "policy_mode": "warn",
        "status_message": status_message,
        "system_message": _hook_system_message(findings),
        "additional_context": additional_context,
        "block": False,
        "arg_count": len(_clean_hook_args(hook_args)),
        "root": {"path": str(inventory.root), "kind": inventory.root_kind},
        "agentPacket": agent_packet,
        "cachePosture": cache_posture,
        "acceleratorAdoption": accelerator_adoption,
        "findings": [finding.to_dict() for finding in findings],
        "client_hints": {
            "codex": {
                "statusMessage": status_message,
                "systemMessage": _hook_system_message(findings),
                "hookSpecificOutput": {"additionalContext": additional_context},
            }
        },
        "boundary": _hook_payload_boundary(),
    }


def render_hook_shim(root: Path, hook_id: str) -> str:
    if hook_id != HOOK_PRE_COMMIT:
        raise ValueError(f"unsupported installable hook: {hook_id}")
    root_literal = shlex.quote(str(root.resolve()))
    return "\n".join(
        [
            "#!/bin/sh",
            "# MyLittleHarness warning-only hook shim.",
            "# Installed only by explicit `mylittleharness hooks --apply`; never by init/attach.",
            "# This shim does not approve lifecycle, archive, roadmap, staging, commit, push, or release.",
            f"MLH_ROOT={root_literal}",
            "",
            "if ! command -v mylittleharness >/dev/null 2>&1; then",
            "    printf '%s\\n' 'warning: mylittleharness is not available; skipping advisory hook.' >&2",
            "    exit 0",
            "fi",
            "",
            'if ! mylittleharness --root "$MLH_ROOT" hooks --run git-pre-commit -- "$@"; then',
            "    printf '%s\\n' 'warning: mylittleharness hook did not complete; this shim remains warning-only.' >&2",
            "fi",
            "",
            "exit 0",
        ]
    ) + "\n"


def _hooks_summary_findings(inventory: Inventory) -> list[Finding]:
    return [
        Finding("info", "hooks-doctor-root", f"root kind: {inventory.root_kind}; root={inventory.root}"),
        Finding(
            "info",
            "hooks-doctor-posture",
            "hooks doctor is read-only; install requires explicit hooks --dry-run followed by hooks --apply",
        ),
    ]


def _hook_install_target_findings(inventory: Inventory, request: HookInstallRequest) -> list[Finding]:
    if request.hook_id not in INSTALLABLE_HOOKS:
        return [Finding("warn", "hooks-install-unsupported", f"hook_id={request.hook_id} is runnable but not installable by the current product surface")]
    target = _hook_target(inventory.root, request.hook_id)
    git_dir = inventory.root / ".git"
    findings = [
        Finding("info", "hooks-target", f"hook_id={request.hook_id}; target={_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)),
        Finding("info", "hooks-root-kind", f"root kind: {inventory.root_kind}"),
    ]
    if git_dir.exists() and git_dir.is_dir():
        findings.append(Finding("info", "hooks-git-dir", "local .git directory is present; hook install target can be evaluated", ".git"))
    else:
        findings.append(Finding("warn", "hooks-git-dir-missing", "local .git directory is absent; hook install apply would be refused", ".git"))
    if target.exists():
        findings.append(Finding("info", "hooks-target-existing", f"hook target already exists: {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    else:
        findings.append(Finding("info", "hooks-target-missing", f"hook target is absent: {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    return findings


def _hook_event_findings() -> list[Finding]:
    return [
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_PRE_COMMIT}; delegates to preflight and remains warning-only"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_AGENT_STATUS}; reports root posture without writing files"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_SESSION_START}; emits first-contact context without writing files"),
    ]


def _hook_install_errors(inventory: Inventory, request: HookInstallRequest) -> list[Finding]:
    findings: list[Finding] = []
    if request.hook_id not in INSTALLABLE_HOOKS:
        findings.append(Finding("error", "hooks-install-refused", f"unsupported installable hook_id={request.hook_id}"))
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "error",
                "hooks-install-refused",
                f"hook install apply requires a live operating root; got root_kind={inventory.root_kind}; product fixtures and archive roots remain non-authority",
            )
        )
    git_dir = inventory.root / ".git"
    if not git_dir.exists() or not git_dir.is_dir():
        findings.append(Finding("error", "hooks-install-refused", "hook install apply requires an existing local .git directory", ".git"))
    target = _hook_target(inventory.root, request.hook_id)
    if not _is_within_root(inventory.root, target):
        findings.append(Finding("error", "hooks-install-refused", f"hook target escapes root: {target}", _rel_path(inventory.root, target)))
    if target.exists() and not target.is_file():
        findings.append(Finding("error", "hooks-install-refused", f"hook target is not a regular file: {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    if target.exists() and not request.force and target.read_text(encoding="utf-8", errors="replace") != render_hook_shim(inventory.root, request.hook_id):
        findings.append(Finding("error", "hooks-install-refused", f"hook target already exists; rerun with --force after reviewing {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    return findings


def _hook_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "hooks-boundary",
            "hooks are sensors, blockers, or context injectors only; hook output cannot approve lifecycle movement, closeout, archive, roadmap status, staging, commit, push, rollback, release, product-diff acceptance, dispatcher work, provider routing, or next-plan opening",
        ),
        Finding(
            "info",
            "hooks-runtime-boundary",
            "hooks create no daemon, listener, dashboard server, queue, cache authority, provider gateway, hidden worker, or lifecycle runtime",
        ),
    ]


def _first_contact_context_findings(inventory: Inventory, hook_id: str) -> list[Finding]:
    payload = dashboard_payload(inventory)
    agent_packet = payload["agentPacket"]
    cache_posture = payload["cachePosture"]
    accelerator_adoption = payload["acceleratorAdoption"]
    assert isinstance(agent_packet, dict)
    assert isinstance(cache_posture, dict)
    assert isinstance(accelerator_adoption, dict)
    lifecycle = agent_packet.get("lifecycle", {})
    components = cache_posture.get("components", {})
    mcp = accelerator_adoption.get("mcp", {})
    assert isinstance(mcp, dict)
    artifacts = _component_status(components, "artifacts")
    sqlite_index = _component_status(components, "sqlite_index")
    return [
        Finding(
            "info",
            "hooks-first-contact-context",
            (
                f"{hook_id} emits a bounded dashboard-backed agent packet for first contact; "
                f"plan_status={_payload_value(lifecycle, 'plan_status')}; "
                f"active_phase={_payload_value(lifecycle, 'active_phase')}; "
                "use --json for the structured hook event payload"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
        Finding(
            "info" if artifacts == "current" and sqlite_index == "current" else "warn",
            "hooks-first-contact-cache-posture",
            (
                f"projection cache posture for first contact: artifacts={artifacts}; sqlite_index={sqlite_index}; "
                "hook output reports stale/degraded cache but does not refresh it or make cache truth"
            ),
            ".mylittleharness/generated/projection",
        ),
        Finding(
            "info",
            "hooks-first-contact-accelerator-adoption",
            (
                f"MCP adoption status for first contact: {str(mcp.get('status') or 'unknown')}; "
                f"mounted={str(mcp.get('mounted') is True).lower()}; dashboard_packet=available; "
                "config_merge=idempotent-explicit; rg_verification=required"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
        Finding(
            "info",
            "hooks-first-contact-boundary",
            "first-contact hook context cannot approve lifecycle, Git, dispatcher, provider, product-diff, cache, archive, roadmap, staging, commit, push, or release decisions",
        ),
    ]


def _hook_status(findings: list[Finding]) -> str:
    if any(finding.severity == "error" for finding in findings):
        return "error"
    if any(finding.severity == "warn" for finding in findings):
        return "warn"
    return "ok"


def _hook_status_message(hook_id: str, lifecycle: object, cache_posture: object) -> str:
    if hook_id not in FIRST_CONTACT_HOOKS:
        return f"MLH hook {hook_id}: advisory context only"
    components = cache_posture.get("components", {}) if isinstance(cache_posture, dict) else {}
    lifecycle_data = lifecycle if isinstance(lifecycle, dict) else {}
    return (
        "MLH first contact: "
        f"plan_status={_payload_value(lifecycle_data, 'plan_status')}; "
        f"phase={_payload_value(lifecycle_data, 'active_phase')}; "
        f"artifacts={_component_status(components, 'artifacts')}; "
        f"sqlite={_component_status(components, 'sqlite_index')}"
    )


def _hook_system_message(findings: list[Finding]) -> str | None:
    sample = next((finding for finding in findings if finding.severity in {"warn", "error"}), None)
    return sample.message if sample else None


def _hook_additional_context(agent_packet: object, cache_posture: object, accelerator_adoption: object) -> str:
    if not isinstance(agent_packet, dict):
        return ""
    lifecycle = agent_packet.get("lifecycle", {})
    next_legal = agent_packet.get("nextLegalDryRun", {})
    recommended = agent_packet.get("recommendedCommands", [])
    components = cache_posture.get("components", {}) if isinstance(cache_posture, dict) else {}
    adoption = accelerator_adoption if isinstance(accelerator_adoption, dict) else {}
    mcp = adoption.get("mcp", {}) if isinstance(adoption.get("mcp"), dict) else {}
    return "\n".join(
        [
            "MyLittleHarness first-contact context:",
            f"- lifecycle: plan_status={_payload_value(lifecycle, 'plan_status')}; active_plan={_payload_value(lifecycle, 'active_plan')}; active_phase={_payload_value(lifecycle, 'active_phase')}; phase_status={_payload_value(lifecycle, 'phase_status')}",
            f"- cache: artifacts={_component_status(components, 'artifacts')}; sqlite_index={_component_status(components, 'sqlite_index')}",
            f"- accelerators: dashboard_packet=available; mcp={_payload_value(mcp, 'status')}; mounted={str(mcp.get('mounted') is True).lower()}; warm_cache=mylittleharness --root <root> projection --warm-cache --target all; rg_verification=required",
            f"- next legal dry-run: {_payload_value(next_legal, 'command')}",
            f"- recommended first-pass commands: {', '.join(str(command) for command in recommended[:4])}",
            "- boundary: this hook is advisory context only and approves no lifecycle, Git, dispatcher, provider, product-diff, cache, archive, staging, commit, push, or release action.",
        ]
    )


def _hook_payload_boundary() -> dict[str, object]:
    return {
        "readOnly": True,
        "writesFiles": False,
        "installsHook": False,
        "startsListener": False,
        "startsDaemon": False,
        "refreshesGeneratedCache": False,
        "createsAdapterState": False,
        "authorizesLifecycle": False,
        "authorizesGit": False,
        "authorizesDispatcher": False,
        "authorizesProvider": False,
        "authorizesProductDiff": False,
        "authorizesCacheTruth": False,
    }


def _component_status(components: object, key: str) -> str:
    if not isinstance(components, dict):
        return "unknown"
    value = components.get(key)
    if not isinstance(value, dict):
        return "unknown"
    return str(value.get("status") or "unknown")


def _payload_value(payload: object, key: str) -> str:
    if not isinstance(payload, dict):
        return "<none>"
    value = payload.get(key)
    return str(value) if value not in (None, "") else "<none>"


def _hook_target(root: Path, hook_id: str) -> Path:
    if hook_id != HOOK_PRE_COMMIT:
        return root / ".mylittleharness" / "hooks" / hook_id
    return root / ".git" / "hooks" / "pre-commit"


def _clean_hook_args(args: list[str]) -> list[str]:
    return args[1:] if args[:1] == ["--"] else args


def _is_within_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _rel_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
