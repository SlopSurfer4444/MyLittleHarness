from __future__ import annotations

import json
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
CODEX_CLIENT = "codex"
CODEX_HOOK_ADAPTER_SCHEMA = "mylittleharness.codex-hook-adapter.v1"
CODEX_HOOKS_REL_PATH = ".codex/hooks.json"
CODEX_HOOK_SCRIPT_REL_PATH = ".codex/hooks/mylittleharness_session_start.py"
CODEX_SESSION_START_EVENT = "SessionStart"
CODEX_SESSION_START_MATCHER = "startup|resume|clear"
CODEX_SESSION_START_STATUS_MESSAGE = "Loading MLH dashboard context"
INSTALLABLE_HOOKS = (HOOK_PRE_COMMIT,)
RUNNABLE_HOOKS = (HOOK_PRE_COMMIT, HOOK_AGENT_STATUS, HOOK_SESSION_START)
FIRST_CONTACT_HOOKS = (HOOK_SESSION_START,)


@dataclass(frozen=True)
class HookInstallRequest:
    hook_id: str
    force: bool = False


@dataclass(frozen=True)
class CodexHookAdapterRequest:
    client: str = CODEX_CLIENT
    scope: str = "project"


def make_hook_install_request(args) -> HookInstallRequest:
    return HookInstallRequest(hook_id=args.hook, force=bool(getattr(args, "force", False)))


def make_codex_hook_adapter_request(args) -> CodexHookAdapterRequest:
    return CodexHookAdapterRequest(client=getattr(args, "client", None) or CODEX_CLIENT, scope=getattr(args, "scope", None) or "project")


def hooks_doctor_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    return [
        ("Summary", _hooks_summary_findings(inventory)),
        ("Install Targets", _hook_install_target_findings(inventory, HookInstallRequest(HOOK_PRE_COMMIT))),
        ("Codex Native Adapter", _codex_hook_adapter_target_findings(inventory, CodexHookAdapterRequest())),
        ("First Contact Adoption", _hook_first_contact_adoption_findings(inventory)),
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


def codex_hook_adapter_dry_run_findings(inventory: Inventory, request: CodexHookAdapterRequest) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "hooks-codex-adapter-dry-run",
            (
                f"Codex native hook adapter preview only; client={request.client}; scope={request.scope}; "
                "no hooks.json, scripts, user config, lifecycle state, caches, generated reports, or Git state were written"
            ),
        )
    ]
    findings.extend(_codex_hook_adapter_target_findings(inventory, request))
    errors = _codex_hook_adapter_errors(inventory, request)
    if errors:
        findings.extend(errors)
    else:
        config_path = _codex_hooks_config_path(inventory.root, request)
        script_path = _codex_hook_script_path(inventory.root, request)
        status = _codex_hook_adapter_status(inventory.root, request)
        findings.append(
            Finding(
                "info",
                "hooks-codex-adapter-plan",
                (
                    f"would ensure Codex SessionStart hook adapter; status={status}; "
                    f"config={_rel_path(inventory.root, config_path)}; script={_rel_path(inventory.root, script_path)}"
                ),
                _rel_path(inventory.root, config_path),
            )
        )
    findings.extend(_hook_boundary_findings())
    return findings


def codex_hook_adapter_apply_findings(inventory: Inventory, request: CodexHookAdapterRequest) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "hooks-codex-adapter-apply",
            (
                f"explicit Codex native hook adapter apply started; client={request.client}; scope={request.scope}; "
                "this route writes only the reviewed project-local hooks.json entry and helper script"
            ),
        )
    ]
    errors = _codex_hook_adapter_errors(inventory, request)
    if errors:
        findings.extend(errors)
        findings.extend(_hook_boundary_findings())
        return findings

    config_path = _codex_hooks_config_path(inventory.root, request)
    script_path = _codex_hook_script_path(inventory.root, request)
    before_config = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    before_script = script_path.read_text(encoding="utf-8") if script_path.exists() else None
    config_text = render_codex_hooks_json(inventory.root, request)
    script_text = render_codex_session_start_script()

    config_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_text, encoding="utf-8")
    config_path.write_text(config_text, encoding="utf-8")

    if before_config == config_text and before_script == script_text:
        findings.append(
            Finding(
                "info",
                "hooks-codex-adapter-apply-unchanged",
                f"Codex SessionStart hook adapter already current at {_rel_path(inventory.root, config_path)}",
                _rel_path(inventory.root, config_path),
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "hooks-codex-adapter-apply-written",
                (
                    f"installed Codex SessionStart hook adapter at {_rel_path(inventory.root, config_path)} "
                    f"with helper {_rel_path(inventory.root, script_path)}"
                ),
                _rel_path(inventory.root, config_path),
            )
        )
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
    codex_specific_output = _codex_hook_specific_output(hook_id, additional_context)
    system_message = _hook_system_message(findings)
    return {
        "schema": "mylittleharness.hook-event.v1",
        "event": hook_id,
        "status": status,
        "policy_mode": "warn",
        "status_message": status_message,
        "system_message": system_message,
        "additional_context": additional_context,
        "continue": True,
        "systemMessage": system_message,
        "hookSpecificOutput": codex_specific_output,
        "block": False,
        "arg_count": len(_clean_hook_args(hook_args)),
        "root": {"path": str(inventory.root), "kind": inventory.root_kind},
        "agentPacket": agent_packet,
        "cachePosture": cache_posture,
        "acceleratorAdoption": accelerator_adoption,
        "findings": [finding.to_dict() for finding in findings],
        "client_hints": {
            "codex": {
                "continue": True,
                "statusMessage": status_message,
                "systemMessage": system_message,
                "hookSpecificOutput": codex_specific_output,
            }
        },
        "boundary": _hook_payload_boundary(),
    }


def codex_session_start_command_output(inventory: Inventory) -> dict[str, object]:
    payload = hook_event_payload(inventory, HOOK_SESSION_START, [])
    codex_hints = payload.get("client_hints")
    codex_output = codex_hints.get(CODEX_CLIENT) if isinstance(codex_hints, dict) else {}
    if not isinstance(codex_output, dict):
        codex_output = {}
    result: dict[str, object] = {"continue": bool(codex_output.get("continue", True))}
    system_message = codex_output.get("systemMessage")
    if isinstance(system_message, str) and system_message:
        result["systemMessage"] = system_message
    hook_specific = codex_output.get("hookSpecificOutput")
    if isinstance(hook_specific, dict):
        result["hookSpecificOutput"] = hook_specific
    return result


def render_codex_hooks_json(root: Path, request: CodexHookAdapterRequest | None = None) -> str:
    request = request or CodexHookAdapterRequest()
    config_path = _codex_hooks_config_path(root, request)
    existing = _read_codex_hooks_config(config_path)
    merged = _merge_codex_session_start_hook(existing)
    return json.dumps(merged, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def render_codex_session_start_script() -> str:
    import_root_literal = repr(str(_module_import_root()))
    return "\n".join(
        [
            "# Generated by MyLittleHarness. Do not edit by hand unless replacing the hook adapter.",
            "from __future__ import annotations",
            "",
            "import sys",
            "from pathlib import Path",
            "",
            f"MLH_IMPORT_ROOT = {import_root_literal}",
            "if MLH_IMPORT_ROOT and MLH_IMPORT_ROOT not in sys.path:",
            "    sys.path.insert(0, MLH_IMPORT_ROOT)",
            "",
            "import json",
            "",
            "from mylittleharness.hooks import CODEX_SESSION_START_EVENT, codex_session_start_command_output",
            "from mylittleharness.inventory import load_inventory",
            "",
            "",
            "def _operating_root() -> Path:",
            "    return Path(__file__).resolve().parents[2]",
            "",
            "",
            "if __name__ == \"__main__\":",
            "    root = _operating_root()",
            "    try:",
            "        payload = codex_session_start_command_output(load_inventory(root))",
            "    except Exception as exc:",
            "        payload = {",
            "            \"continue\": True,",
            "            \"systemMessage\": f\"MLH SessionStart hook failed: {exc}\",",
            "            \"hookSpecificOutput\": {",
            "                \"hookEventName\": CODEX_SESSION_START_EVENT,",
            "                \"additionalContext\": \"MyLittleHarness first-contact context unavailable; run `mylittleharness --root <root> check` before lifecycle-sensitive work.\",",
            "            },",
            "        }",
            "    json.dump(payload, sys.stdout, ensure_ascii=True)",
            "    sys.stdout.write(\"\\n\")",
            "    raise SystemExit(0)",
        ]
    ) + "\n"


def render_hook_shim(root: Path, hook_id: str) -> str:
    if hook_id != HOOK_PRE_COMMIT:
        raise ValueError(f"unsupported installable hook: {hook_id}")
    root_literal = shlex.quote(str(root.resolve()))
    import_root_literal = shlex.quote(str(_module_import_root()))
    return "\n".join(
        [
            "#!/bin/sh",
            "# MyLittleHarness warning-only hook shim.",
            "# Installed only by explicit `mylittleharness hooks --apply`; never by init/attach.",
            "# This shim does not approve lifecycle, archive, roadmap, staging, commit, push, or release.",
            f"MLH_ROOT={root_literal}",
            f"MLH_PYTHONPATH={import_root_literal}",
            "",
            "run_mlh() {",
            "    if command -v mylittleharness >/dev/null 2>&1; then",
            "        mylittleharness \"$@\"",
            "        return $?",
            "    fi",
            "    if command -v python >/dev/null 2>&1; then",
            "        PYTHONPATH=\"$MLH_PYTHONPATH\" python -m mylittleharness \"$@\"",
            "        return $?",
            "    fi",
            "    if command -v py >/dev/null 2>&1; then",
            "        PYTHONPATH=\"$MLH_PYTHONPATH\" py -m mylittleharness \"$@\"",
            "        return $?",
            "    fi",
            "    return 127",
            "}",
            "",
            'run_mlh --root "$MLH_ROOT" hooks --run git-pre-commit -- "$@"',
            "MLH_STATUS=$?",
            "if [ \"$MLH_STATUS\" -eq 127 ]; then",
            "    printf '%s\\n' 'warning: mylittleharness is not available via console script or Python module; skipping advisory hook.' >&2",
            "elif [ \"$MLH_STATUS\" -ne 0 ]; then",
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
        Finding(
            "info",
            "hooks-doctor-first-contact",
            "first-contact context is a runnable native-client event (`hooks --run session-start --json`); Codex activation uses `hooks adapter --client codex --dry-run|--apply --scope project`; Git pre-commit is only a warning shim",
        ),
    ]


def _codex_hook_adapter_target_findings(inventory: Inventory, request: CodexHookAdapterRequest) -> list[Finding]:
    config_path = _codex_hooks_config_path(inventory.root, request)
    script_path = _codex_hook_script_path(inventory.root, request)
    status = _codex_hook_adapter_status(inventory.root, request)
    return [
        Finding("info", "hooks-codex-adapter-target", f"client={request.client}; scope={request.scope}; config={_rel_path(inventory.root, config_path)}", _rel_path(inventory.root, config_path)),
        Finding("info", "hooks-codex-adapter-script", f"helper script target={_rel_path(inventory.root, script_path)}", _rel_path(inventory.root, script_path)),
        Finding("info", "hooks-codex-adapter-status", f"Codex SessionStart hook adapter status={status}; project-local hooks require a trusted project and may need /hooks review or a new Codex session", _rel_path(inventory.root, config_path)),
        Finding(
            "info",
            "hooks-codex-adapter-event",
            "Codex SessionStart matcher=startup|resume|clear; hook stdout provides hookSpecificOutput.additionalContext for dashboard-first navigation",
            _rel_path(inventory.root, config_path),
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
    findings.append(
        Finding(
            "info",
            "hooks-target-runtime-fallback",
            "installed Git shim tries the mylittleharness console script first, then falls back to `python -m mylittleharness` with the install-time package import root",
        )
    )
    return findings


def _hook_first_contact_adoption_findings(inventory: Inventory) -> list[Finding]:
    state_ref = "project/project-state.md" if inventory.state and inventory.state.exists else None
    return [
        Finding(
            "info",
            "hooks-first-contact-command",
            f"native first-contact command: mylittleharness --root {shlex.quote(str(inventory.root))} hooks --run session-start --json",
            state_ref,
        ),
        Finding(
            "info",
            "hooks-first-contact-codex-adapter",
            "Codex native activation is project-local and explicit: mylittleharness --root <root> hooks adapter --client codex --dry-run --scope project, then --apply after review",
            ".codex/hooks.json",
        ),
        Finding(
            "info",
            "hooks-first-contact-dashboard-first",
            "session-start emits the dashboard agent packet, projection/SQLite posture, MCP adoption posture, and rg-verification reminder before agent navigation",
            state_ref,
        ),
        Finding(
            "info",
            "hooks-first-contact-native-client-boundary",
            "MLH installs Codex native hook configuration only through the explicit project-local adapter dry-run/apply rail; other IDE/native clients remain future scoped adapters",
        ),
    ]


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


def _codex_hook_adapter_errors(inventory: Inventory, request: CodexHookAdapterRequest) -> list[Finding]:
    findings: list[Finding] = []
    if request.client != CODEX_CLIENT:
        findings.append(Finding("error", "hooks-codex-adapter-refused", f"unsupported native hook client={request.client}; only codex is implemented"))
        return findings
    if request.scope != "project":
        findings.append(Finding("error", "hooks-codex-adapter-refused", f"unsupported Codex hook adapter scope={request.scope}; only project scope is implemented"))
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "error",
                "hooks-codex-adapter-refused",
                f"Codex project hook adapter apply requires a live operating root; got root_kind={inventory.root_kind}; product fixtures and archive roots remain non-authority",
            )
        )
    codex_dir = inventory.root / ".codex"
    hooks_dir = _codex_hook_script_path(inventory.root, request).parent
    for path, label in ((codex_dir, ".codex"), (hooks_dir, ".codex/hooks")):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            findings.append(Finding("error", "hooks-codex-adapter-refused", f"{label} is not a safe directory target", label))
    config_path = _codex_hooks_config_path(inventory.root, request)
    script_path = _codex_hook_script_path(inventory.root, request)
    for path in (config_path, script_path):
        if not _is_within_root(inventory.root, path):
            findings.append(Finding("error", "hooks-codex-adapter-refused", f"Codex hook target escapes root: {path}", _rel_path(inventory.root, path)))
        if path.is_symlink() or (path.exists() and not path.is_file()):
            findings.append(Finding("error", "hooks-codex-adapter-refused", f"Codex hook target is not a regular file: {_rel_path(inventory.root, path)}", _rel_path(inventory.root, path)))
    if config_path.exists() and config_path.is_file() and not config_path.is_symlink():
        try:
            _read_codex_hooks_config(config_path)
        except ValueError as exc:
            findings.append(Finding("error", "hooks-codex-adapter-refused", str(exc), _rel_path(inventory.root, config_path)))
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


def _codex_hook_specific_output(hook_id: str, additional_context: str) -> dict[str, object]:
    if hook_id == HOOK_SESSION_START:
        return {
            "hookEventName": CODEX_SESSION_START_EVENT,
            "additionalContext": additional_context,
        }
    return {"additionalContext": additional_context}


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


def _codex_hooks_config_path(root: Path, request: CodexHookAdapterRequest) -> Path:
    if request.scope == "project":
        return root / CODEX_HOOKS_REL_PATH
    return root / ".mylittleharness" / "unsupported-codex-hooks.json"


def _codex_hook_script_path(root: Path, request: CodexHookAdapterRequest) -> Path:
    if request.scope == "project":
        return root / CODEX_HOOK_SCRIPT_REL_PATH
    return root / ".mylittleharness" / "unsupported-codex-hook.py"


def _codex_hook_adapter_status(root: Path, request: CodexHookAdapterRequest) -> str:
    config_path = _codex_hooks_config_path(root, request)
    script_path = _codex_hook_script_path(root, request)
    try:
        config_current = config_path.is_file() and not config_path.is_symlink() and config_path.read_text(encoding="utf-8") == render_codex_hooks_json(root, request)
    except (OSError, ValueError):
        config_current = False
    try:
        script_current = script_path.is_file() and not script_path.is_symlink() and script_path.read_text(encoding="utf-8") == render_codex_session_start_script()
    except OSError:
        script_current = False
    if config_current and script_current:
        return "mounted"
    if not config_path.exists() and not script_path.exists():
        return "missing"
    return "needs-update"


def _read_codex_hooks_config(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Codex hooks config is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Codex hooks config could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Codex hooks config root must be a JSON object")
    hooks = payload.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Codex hooks config `hooks` field must be a JSON object")
    session_start = hooks.get(CODEX_SESSION_START_EVENT, [])
    if not isinstance(session_start, list):
        raise ValueError("Codex hooks config `hooks.SessionStart` field must be a JSON array")
    return payload


def _merge_codex_session_start_hook(existing: dict[str, object]) -> dict[str, object]:
    merged = json.loads(json.dumps(existing))
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        merged["hooks"] = hooks
    existing_groups = hooks.get(CODEX_SESSION_START_EVENT, [])
    if not isinstance(existing_groups, list):
        existing_groups = []
    filtered_groups = [group for group in existing_groups if not _is_mlh_codex_session_start_group(group)]
    filtered_groups.append(_codex_session_start_group())
    hooks[CODEX_SESSION_START_EVENT] = filtered_groups
    return merged


def _codex_session_start_group() -> dict[str, object]:
    return {
        "matcher": CODEX_SESSION_START_MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": _codex_session_start_command(),
                "timeout": 30,
                "statusMessage": CODEX_SESSION_START_STATUS_MESSAGE,
            }
        ],
    }


def _codex_session_start_command() -> str:
    script_rel = CODEX_HOOK_SCRIPT_REL_PATH
    return (
        "python -c \"from pathlib import Path; import runpy; "
        "p=Path.cwd().resolve(); roots=(p, *p.parents); "
        f"script=next((r/{_py_literal(script_rel.split('/')[0])}/{_py_literal(script_rel.split('/')[1])}/{_py_literal(script_rel.split('/')[2])} "
        f"for r in roots if (r/{_py_literal(script_rel.split('/')[0])}/{_py_literal(script_rel.split('/')[1])}/{_py_literal(script_rel.split('/')[2])}).is_file()), None); "
        "assert script is not None, 'MLH Codex hook script not found from cwd'; "
        "runpy.run_path(str(script), run_name='__main__')\""
    )


def _is_mlh_codex_session_start_group(group: object) -> bool:
    if not isinstance(group, dict):
        return False
    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        return False
    for handler in handlers:
        if not isinstance(handler, dict):
            continue
        command = str(handler.get("command") or "")
        if "mylittleharness_session_start.py" in command:
            return True
    return False


def _py_literal(value: str) -> str:
    return repr(value)


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


def _module_import_root() -> Path:
    return Path(__file__).resolve().parents[1]
