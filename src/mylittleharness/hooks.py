from __future__ import annotations

import json
import os
import re
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
HOOK_USER_PROMPT_SUBMIT = "user-prompt-submit"
HOOK_PRE_TOOL_USE = "pre-tool-use"
HOOK_POST_TOOL_USE = "post-tool-use"
HOOK_STOP = "stop"
CODEX_CLIENT = "codex"
CLAUDE_CODE_CLIENT = "claude-code"
GITHUB_COPILOT_CLIENT = "github-copilot"
NATIVE_HOOK_CLIENTS = (CODEX_CLIENT, CLAUDE_CODE_CLIENT, GITHUB_COPILOT_CLIENT)
CODEX_HOOK_ADAPTER_SCHEMA = "mylittleharness.codex-hook-adapter.v1"
CODEX_HOOKS_REL_PATH = ".codex/hooks.json"
CODEX_HOOK_SCRIPT_REL_PATH = ".codex/hooks/mylittleharness_session_start.py"
CLAUDE_CODE_HOOKS_REL_PATH = ".claude/settings.json"
CLAUDE_CODE_HOOK_SCRIPT_REL_PATH = ".claude/hooks/mylittleharness_hook.py"
GITHUB_COPILOT_HOOKS_REL_PATH = ".github/hooks/mylittleharness.json"
GITHUB_COPILOT_HOOK_SCRIPT_REL_PATH = ".github/hooks/mylittleharness_hook.py"
CODEX_HOOK_EVENTS = {
    HOOK_SESSION_START: "SessionStart",
    HOOK_USER_PROMPT_SUBMIT: "UserPromptSubmit",
    HOOK_PRE_TOOL_USE: "PreToolUse",
    HOOK_POST_TOOL_USE: "PostToolUse",
    HOOK_STOP: "Stop",
}
GITHUB_COPILOT_HOOK_EVENTS = {
    HOOK_SESSION_START: "sessionStart",
    HOOK_USER_PROMPT_SUBMIT: "userPromptSubmitted",
    HOOK_PRE_TOOL_USE: "preToolUse",
    HOOK_POST_TOOL_USE: "postToolUse",
    HOOK_STOP: "agentStop",
}
CODEX_SESSION_START_EVENT = CODEX_HOOK_EVENTS[HOOK_SESSION_START]
CODEX_HOOK_MATCHERS = {
    HOOK_SESSION_START: "startup|resume|clear",
    HOOK_USER_PROMPT_SUBMIT: "*",
    HOOK_PRE_TOOL_USE: "*",
    HOOK_POST_TOOL_USE: "*",
    HOOK_STOP: "*",
}
CODEX_HOOK_STATUS_MESSAGES = {
    HOOK_SESSION_START: "Loading MLH dashboard context",
    HOOK_USER_PROMPT_SUBMIT: "Checking MLH route context",
    HOOK_PRE_TOOL_USE: "Checking MLH shortcut rails",
    HOOK_POST_TOOL_USE: "Recording MLH tool-use posture",
    HOOK_STOP: "Checking MLH lifecycle tail",
}
INSTALLABLE_HOOKS = (HOOK_PRE_COMMIT,)
CODEX_NATIVE_HOOKS = (HOOK_SESSION_START, HOOK_USER_PROMPT_SUBMIT, HOOK_PRE_TOOL_USE, HOOK_POST_TOOL_USE, HOOK_STOP)
NATIVE_ADAPTER_HOOKS = CODEX_NATIVE_HOOKS
RUNNABLE_HOOKS = (HOOK_PRE_COMMIT, HOOK_AGENT_STATUS, *CODEX_NATIVE_HOOKS)
FIRST_CONTACT_HOOKS = (HOOK_SESSION_START, HOOK_USER_PROMPT_SUBMIT)
TOOL_USE_HOOKS = (HOOK_PRE_TOOL_USE, HOOK_POST_TOOL_USE)
WRITING_COMMAND_TOKENS = (
    ">",
    ">>",
    "set-content",
    "add-content",
    "out-file",
    "new-item",
    "remove-item",
    "move-item",
    "copy-item",
    "del ",
    "erase ",
    "rm ",
    "mv ",
    "cp ",
)
MLH_MUTATION_COMMANDS = (
    "mylittleharness",
    "python -m mylittleharness",
    "py -m mylittleharness",
)
LIFECYCLE_MARKDOWN_PREFIXES = (
    "project/plan-incubation/",
    "project/research/",
    "project/verification/",
    "project/decisions/",
    "project/adrs/",
    "project/specs/",
    "project/roadmap",
    "project/archive/",
)
LIFECYCLE_AUTHORITY_PATHS = (
    "project/project-state.md",
    "project/implementation-plan.md",
    "project/roadmap.md",
)
GENERATED_CACHE_PREFIXES = (".mylittleharness/generated/",)
CODE_WRITE_PREFIXES = ("src/", "tests/")
GIT_WRITE_COMMANDS = (
    " git add ",
    " git stage ",
    " git commit ",
    "git add ",
    "git stage ",
    "git commit ",
)
PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'`]+|(?:^|[\s\"'`])((?:\.?[\\/])?(?:project|src|tests|docs|\.mylittleharness)[\\/][^\s\"'`]+)")


@dataclass(frozen=True)
class HookInstallRequest:
    hook_id: str
    force: bool = False


@dataclass(frozen=True)
class CodexHookAdapterRequest:
    client: str = CODEX_CLIENT
    scope: str = "project"
    config_path: str = ""


def make_hook_install_request(args) -> HookInstallRequest:
    return HookInstallRequest(hook_id=args.hook, force=bool(getattr(args, "force", False)))


def make_codex_hook_adapter_request(args) -> CodexHookAdapterRequest:
    return CodexHookAdapterRequest(
        client=getattr(args, "client", None) or CODEX_CLIENT,
        scope=getattr(args, "scope", None) or "project",
        config_path=getattr(args, "config_path", None) or "",
    )


def hooks_doctor_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    return [
        ("Summary", _hooks_summary_findings(inventory)),
        ("Install Targets", _hook_install_target_findings(inventory, HookInstallRequest(HOOK_PRE_COMMIT))),
        ("Codex Native Adapter", _codex_hook_adapter_target_findings(inventory, CodexHookAdapterRequest())),
        (
            "Native Client Adapters",
            [
                finding
                for client in (CLAUDE_CODE_CLIENT, GITHUB_COPILOT_CLIENT)
                for finding in _codex_hook_adapter_target_findings(inventory, CodexHookAdapterRequest(client=client))
            ],
        ),
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
    prefix = _hook_adapter_code_prefix(request)
    label = _native_hook_client_label(request.client)
    findings = [
        Finding(
            "info",
            f"{prefix}-dry-run",
            (
                f"{label} native hook adapter preview only; client={request.client}; scope={request.scope}; "
                "no hook config, scripts, user config, lifecycle state, caches, generated reports, or Git state were written"
            ),
        )
    ]
    findings.extend(_codex_hook_adapter_target_findings(inventory, request))
    errors = _codex_hook_adapter_errors(inventory, request)
    if errors:
        findings.extend(errors)
    else:
        config_path = _native_hooks_config_path(inventory.root, request)
        script_path = _native_hook_script_path(inventory.root, request)
        status = _codex_hook_adapter_status(inventory.root, request)
        findings.append(
            Finding(
                "info",
                f"{prefix}-plan",
                (
                    f"would ensure {label} native hook adapter events={','.join(NATIVE_ADAPTER_HOOKS)}; status={status}; "
                    f"config={_rel_path(inventory.root, config_path)}; script={_rel_path(inventory.root, script_path)}"
                ),
                _rel_path(inventory.root, config_path),
            )
        )
    findings.extend(_hook_boundary_findings())
    return findings


def codex_hook_adapter_validation_findings(
    inventory: Inventory,
    request: CodexHookAdapterRequest,
    *,
    require_live_root: bool = True,
) -> list[Finding]:
    return _codex_hook_adapter_errors(inventory, request, require_live_root=require_live_root)


def codex_hook_adapter_adoption_payload(inventory: Inventory, request: CodexHookAdapterRequest | None = None) -> dict[str, object]:
    request = request or CodexHookAdapterRequest()
    config_path = _native_hooks_config_path(inventory.root, request)
    script_path = _native_hook_script_path(inventory.root, request)
    return {
        "schema": CODEX_HOOK_ADAPTER_SCHEMA,
        "client": request.client,
        "scope": request.scope,
        "status": _codex_hook_adapter_status(inventory.root, request),
        "configPath": _rel_path(inventory.root, config_path),
        "scriptPath": _rel_path(inventory.root, script_path),
        "events": [_native_hook_event_name(request.client, hook_id) for hook_id in NATIVE_ADAPTER_HOOKS],
        "dryRunCommand": "mylittleharness --root <root> hooks adapter --client codex --dry-run --scope project",
        "applyCommand": "mylittleharness --root <root> hooks adapter --client codex --apply --scope project",
        "includedInCodexMcpInstall": True,
        "includedInAttachApply": True,
        "boundary": {
            "writesRepoFilesOnApplyOnly": True,
            "writesUserConfig": False,
            "startsRuntime": False,
            "authorizesLifecycle": False,
            "eventsAreSensors": True,
        },
    }


def codex_hook_adapter_apply_findings(inventory: Inventory, request: CodexHookAdapterRequest) -> list[Finding]:
    prefix = _hook_adapter_code_prefix(request)
    label = _native_hook_client_label(request.client)
    findings = [
        Finding(
            "info",
            f"{prefix}-apply",
            (
                f"explicit {label} native hook adapter apply started; client={request.client}; scope={request.scope}; "
                "this route writes only the reviewed project-local hook config and helper script"
            ),
        )
    ]
    errors = _codex_hook_adapter_errors(inventory, request)
    if errors:
        findings.extend(errors)
        findings.extend(_hook_boundary_findings())
        return findings

    config_path = _native_hooks_config_path(inventory.root, request)
    script_path = _native_hook_script_path(inventory.root, request)
    before_config = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    before_script = script_path.read_text(encoding="utf-8") if script_path.exists() else None
    config_text = render_native_hooks_json(inventory.root, request)
    script_text = render_native_hook_script(request.client)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_text, encoding="utf-8")
    config_path.write_text(config_text, encoding="utf-8")

    if before_config == config_text and before_script == script_text:
        findings.append(
            Finding(
                "info",
                f"{prefix}-apply-unchanged",
                f"{label} native hook adapter already current at {_rel_path(inventory.root, config_path)}",
                _rel_path(inventory.root, config_path),
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                f"{prefix}-apply-written",
                (
                    f"installed {label} native hook adapter at {_rel_path(inventory.root, config_path)} "
                    f"with helper {_rel_path(inventory.root, script_path)}"
                ),
                _rel_path(inventory.root, config_path),
            )
        )
    findings.extend(_hook_boundary_findings())
    return findings


def hook_run_sections(inventory: Inventory, hook_id: str, hook_args: list[str], hook_input_text: str = "") -> list[tuple[str, list[Finding]]]:
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
            ("Native Hook Policy", _native_hook_policy_findings(inventory, hook_id, hook_input_text)),
            ("Boundary", _hook_boundary_findings()),
        ]
    if hook_id in TOOL_USE_HOOKS or hook_id == HOOK_STOP:
        return [
            ("Event", event_findings),
            ("Native Hook Policy", _native_hook_policy_findings(inventory, hook_id, hook_input_text)),
            ("Boundary", _hook_boundary_findings()),
        ]
    return [("Event", event_findings), *preflight_sections(inventory), ("Boundary", _hook_boundary_findings())]


def hook_event_payload(inventory: Inventory, hook_id: str, hook_args: list[str], hook_input_text: str = "") -> dict[str, object]:
    sections = hook_run_sections(inventory, hook_id, hook_args, hook_input_text)
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
    blocked = _hook_blocked(findings)
    status = "block" if blocked else _hook_status(findings)
    status_message = _hook_status_message(hook_id, lifecycle, cache_posture)
    additional_context = _hook_additional_context(agent_packet, cache_posture, accelerator_adoption) if hook_id in FIRST_CONTACT_HOOKS else _hook_event_context(inventory, hook_id)
    system_message = _hook_system_message(findings)
    codex_specific_output = _codex_hook_specific_output(hook_id, additional_context, blocked, system_message)
    return {
        "schema": "mylittleharness.hook-event.v1",
        "event": hook_id,
        "status": status,
        "policy_mode": "block" if blocked else "warn",
        "status_message": status_message,
        "system_message": system_message,
        "additional_context": additional_context,
        "continue": not blocked,
        "systemMessage": system_message,
        "hookSpecificOutput": codex_specific_output,
        "block": blocked,
        "arg_count": len(_clean_hook_args(hook_args)),
        "hook_input": _hook_input_summary(hook_input_text),
        "root": {"path": str(inventory.root), "kind": inventory.root_kind},
        "agentPacket": agent_packet,
        "cachePosture": cache_posture,
        "acceleratorAdoption": accelerator_adoption,
        "findings": [finding.to_dict() for finding in findings],
        "client_hints": {
            "codex": {
                "continue": not blocked,
                "statusMessage": status_message,
                "systemMessage": system_message,
                "hookSpecificOutput": codex_specific_output,
            }
        },
        "boundary": _hook_payload_boundary(),
    }


def codex_hook_command_output(inventory: Inventory, hook_id: str, hook_input_text: str = "") -> dict[str, object]:
    payload = hook_event_payload(inventory, hook_id, [], hook_input_text)
    codex_hints = payload.get("client_hints")
    codex_output = codex_hints.get(CODEX_CLIENT) if isinstance(codex_hints, dict) else {}
    if not isinstance(codex_output, dict):
        codex_output = {}
    system_message = codex_output.get("systemMessage")
    hook_specific = codex_output.get("hookSpecificOutput")
    blocked = bool(payload.get("block"))

    if hook_id == HOOK_PRE_TOOL_USE:
        result: dict[str, object] = {}
        if isinstance(system_message, str) and system_message:
            result["systemMessage"] = system_message
        if isinstance(hook_specific, dict):
            result["hookSpecificOutput"] = hook_specific
        return result

    if hook_id == HOOK_USER_PROMPT_SUBMIT and blocked:
        reason = system_message if isinstance(system_message, str) and system_message else "MyLittleHarness blocked this prompt by deterministic policy."
        result = {"decision": "block", "reason": reason}
        if isinstance(hook_specific, dict):
            result["hookSpecificOutput"] = hook_specific
        return result

    result = {"continue": bool(codex_output.get("continue", True))}
    if isinstance(system_message, str) and system_message:
        result["systemMessage"] = system_message
    if isinstance(hook_specific, dict):
        result["hookSpecificOutput"] = hook_specific
    return result


def codex_session_start_command_output(inventory: Inventory) -> dict[str, object]:
    return codex_hook_command_output(inventory, HOOK_SESSION_START)


def hook_client_command_output(inventory: Inventory, hook_id: str, client: str, hook_input_text: str = "") -> dict[str, object]:
    if client in {CODEX_CLIENT, CLAUDE_CODE_CLIENT}:
        return codex_hook_command_output(inventory, hook_id, hook_input_text)
    if client != GITHUB_COPILOT_CLIENT:
        return hook_client_failure_output(client, hook_id, f"unsupported native hook client={client}")

    payload = hook_event_payload(inventory, hook_id, [], hook_input_text)
    blocked = bool(payload.get("block"))
    system_message = payload.get("system_message")
    reason = system_message if isinstance(system_message, str) and system_message else "MyLittleHarness blocked this deterministic shortcut attempt."
    additional_context = payload.get("additional_context")

    if hook_id == HOOK_PRE_TOOL_USE and blocked:
        return {"permissionDecision": "deny", "permissionDecisionReason": reason}
    if hook_id == HOOK_SESSION_START and isinstance(additional_context, str) and additional_context:
        return {"additionalContext": additional_context}
    if hook_id == HOOK_STOP and blocked:
        return {"decision": "block", "reason": reason}
    return {}


def hook_client_failure_output(client: str, hook_id: str, message: str) -> dict[str, object]:
    if client == GITHUB_COPILOT_CLIENT:
        if hook_id == HOOK_SESSION_START:
            return {"additionalContext": f"MyLittleHarness hook failed open: {message}"}
        return {}
    event_name = CODEX_HOOK_EVENTS.get(hook_id, CODEX_SESSION_START_EVENT)
    return {
        "continue": True,
        "systemMessage": f"MLH hook failed: {message}",
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": "MyLittleHarness context unavailable; run `mylittleharness --root <root> check` before lifecycle-sensitive work.",
        },
    }


def render_codex_hooks_json(root: Path, request: CodexHookAdapterRequest | None = None) -> str:
    request = request or CodexHookAdapterRequest()
    config_path = _codex_hooks_config_path(root, request)
    existing = _read_codex_hooks_config(config_path)
    merged = _merge_codex_native_hooks(existing)
    return json.dumps(merged, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def render_native_hooks_json(root: Path, request: CodexHookAdapterRequest | None = None) -> str:
    request = request or CodexHookAdapterRequest()
    if request.client == CODEX_CLIENT:
        return render_codex_hooks_json(root, request)
    config_path = _native_hooks_config_path(root, request)
    existing = _read_native_hooks_config(config_path, request.client)
    if request.client == CLAUDE_CODE_CLIENT:
        merged = _merge_claude_code_native_hooks(existing)
    elif request.client == GITHUB_COPILOT_CLIENT:
        merged = _merge_github_copilot_native_hooks(existing)
    else:
        raise ValueError(f"unsupported native hook client={request.client}")
    return json.dumps(merged, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def render_codex_session_start_script() -> str:
    import_root_literal = repr(str(_module_import_root()))
    return "\n".join(
        [
            "# Generated by MyLittleHarness. Do not edit by hand unless replacing the hook adapter.",
            "from __future__ import annotations",
            "",
            "import os",
            "import sys",
            "from pathlib import Path",
            "",
            f"MLH_IMPORT_ROOT = {import_root_literal}",
            "if MLH_IMPORT_ROOT and MLH_IMPORT_ROOT not in sys.path:",
            "    sys.path.insert(0, MLH_IMPORT_ROOT)",
            "",
            "import json",
            "",
            "from mylittleharness.hooks import CODEX_HOOK_EVENTS, CODEX_SESSION_START_EVENT, HOOK_SESSION_START, codex_hook_command_output, codex_session_start_command_output",
            "from mylittleharness.inventory import load_inventory",
            "",
            "",
            "def _operating_root() -> Path:",
            "    return Path(__file__).resolve().parents[2]",
            "",
            "",
            "if __name__ == \"__main__\":",
            "    root = _operating_root()",
            "    hook_event = os.environ.get(\"MLH_HOOK_EVENT\") or HOOK_SESSION_START",
            "    hook_input = sys.stdin.read()",
            "    try:",
            "        if hook_event == HOOK_SESSION_START and not hook_input:",
            "            payload = codex_session_start_command_output(load_inventory(root))",
            "        else:",
            "            payload = codex_hook_command_output(load_inventory(root), hook_event, hook_input)",
            "    except Exception as exc:",
            "        payload = {",
            "            \"continue\": True,",
            "            \"systemMessage\": f\"MLH hook failed: {exc}\",",
            "            \"hookSpecificOutput\": {",
            "                \"hookEventName\": CODEX_HOOK_EVENTS.get(hook_event, CODEX_SESSION_START_EVENT),",
            "                \"additionalContext\": \"MyLittleHarness first-contact context unavailable; run `mylittleharness --root <root> check` before lifecycle-sensitive work.\",",
            "            },",
            "        }",
            "    json.dump(payload, sys.stdout, ensure_ascii=True)",
            "    sys.stdout.write(\"\\n\")",
            "    raise SystemExit(0)",
        ]
    ) + "\n"


def render_native_hook_script(client: str) -> str:
    if client == CODEX_CLIENT:
        return render_codex_session_start_script()
    import_root_literal = repr(str(_module_import_root()))
    client_literal = repr(client)
    return "\n".join(
        [
            "# Generated by MyLittleHarness. Do not edit by hand unless replacing the hook adapter.",
            "from __future__ import annotations",
            "",
            "import os",
            "import sys",
            "from pathlib import Path",
            "",
            f"MLH_IMPORT_ROOT = {import_root_literal}",
            "if MLH_IMPORT_ROOT and MLH_IMPORT_ROOT not in sys.path:",
            "    sys.path.insert(0, MLH_IMPORT_ROOT)",
            "",
            "import json",
            "",
            "from mylittleharness.hooks import HOOK_SESSION_START, hook_client_command_output, hook_client_failure_output",
            "from mylittleharness.inventory import load_inventory",
            "",
            f"MLH_HOOK_CLIENT = {client_literal}",
            "",
            "",
            "def _operating_root() -> Path:",
            "    cwd = Path.cwd().resolve()",
            "    for candidate in (cwd, *cwd.parents):",
            "        if (candidate / 'project' / 'project-state.md').is_file():",
            "            return candidate",
            "    return Path(__file__).resolve().parents[2]",
            "",
            "",
            "if __name__ == \"__main__\":",
            "    root = _operating_root()",
            "    hook_event = os.environ.get(\"MLH_HOOK_EVENT\") or HOOK_SESSION_START",
            "    hook_input = sys.stdin.read()",
            "    try:",
            "        payload = hook_client_command_output(load_inventory(root), hook_event, MLH_HOOK_CLIENT, hook_input)",
            "    except Exception as exc:",
            "        payload = hook_client_failure_output(MLH_HOOK_CLIENT, hook_event, str(exc))",
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
            "first-contact context is a runnable native-client event (`hooks --run session-start --json`); activation uses `hooks adapter --client <client> --dry-run|--apply --scope project`; Git pre-commit is only a warning shim",
        ),
    ]


def _codex_hook_adapter_target_findings(inventory: Inventory, request: CodexHookAdapterRequest) -> list[Finding]:
    config_path = _native_hooks_config_path(inventory.root, request)
    script_path = _native_hook_script_path(inventory.root, request)
    status = _codex_hook_adapter_status(inventory.root, request)
    prefix = _hook_adapter_code_prefix(request)
    label = _native_hook_client_label(request.client)
    event_names = _native_hook_event_names(request.client)
    return [
        Finding("info", f"{prefix}-target", f"client={request.client}; scope={request.scope}; config={_rel_path(inventory.root, config_path)}", _rel_path(inventory.root, config_path)),
        Finding("info", f"{prefix}-script", f"helper script target={_rel_path(inventory.root, script_path)}", _rel_path(inventory.root, script_path)),
        Finding("info", f"{prefix}-status", f"{label} hook adapter status={status}; project-local hooks require a trusted project and may need client hook review or a new session", _rel_path(inventory.root, config_path)),
        Finding(
            "info",
            f"{prefix}-event",
            f"{label} native events: {', '.join(event_names)}; hook stdout provides client-valid JSON for context, warning, or deterministic denial",
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
            "Native client activation is project-local and explicit: mylittleharness --root <root> hooks adapter --client codex|claude-code|github-copilot --dry-run --scope project, then --apply after review",
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
            "MLH installs Codex, Claude Code, and GitHub Copilot native hook configuration only through the explicit project-local adapter dry-run/apply rail",
        ),
    ]


def _hook_event_findings() -> list[Finding]:
    return [
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_PRE_COMMIT}; delegates to preflight and remains warning-only"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_AGENT_STATUS}; reports root posture without writing files"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_SESSION_START}; emits first-contact context without writing files"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_USER_PROMPT_SUBMIT}; emits dashboard-first context for prompt routing"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_PRE_TOOL_USE}; warns or blocks deterministic shortcut attempts before tool execution"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_POST_TOOL_USE}; reports post-tool shortcut posture without writing files"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_STOP}; warns about dangling lifecycle tails before final response"),
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


def _codex_hook_adapter_errors(inventory: Inventory, request: CodexHookAdapterRequest, *, require_live_root: bool = True) -> list[Finding]:
    findings: list[Finding] = []
    prefix = _hook_adapter_code_prefix(request)
    label = _native_hook_client_label(request.client)
    if request.client not in NATIVE_HOOK_CLIENTS:
        findings.append(Finding("error", f"{prefix}-refused", f"unsupported native hook client={request.client}; supported clients={','.join(NATIVE_HOOK_CLIENTS)}"))
        return findings
    if request.scope != "project":
        findings.append(Finding("error", f"{prefix}-refused", f"unsupported {label} hook adapter scope={request.scope}; only project scope is implemented"))
        return findings
    if require_live_root and inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "error",
                f"{prefix}-refused",
                f"{label} project hook adapter apply requires a live operating root; got root_kind={inventory.root_kind}; product fixtures and archive roots remain non-authority",
            )
        )
    config_path = _native_hooks_config_path(inventory.root, request)
    script_path = _native_hook_script_path(inventory.root, request)
    for path in (config_path, script_path):
        findings.extend(_unsafe_parent_directory_findings(inventory.root, path, f"{prefix}-refused"))
    for path in (config_path, script_path):
        if not _is_within_root(inventory.root, path):
            findings.append(Finding("error", f"{prefix}-refused", f"{label} hook target escapes root: {path}", _rel_path(inventory.root, path)))
        if path.is_symlink() or (path.exists() and not path.is_file()):
            findings.append(Finding("error", f"{prefix}-refused", f"{label} hook target is not a regular file: {_rel_path(inventory.root, path)}", _rel_path(inventory.root, path)))
    if config_path.exists() and config_path.is_file() and not config_path.is_symlink():
        try:
            _read_native_hooks_config(config_path, request.client)
        except ValueError as exc:
            findings.append(Finding("error", f"{prefix}-refused", str(exc), _rel_path(inventory.root, config_path)))
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
    sample = next((finding for finding in findings if finding.severity in {"error", "warn"}), None)
    return sample.message if sample else None


def _hook_blocked(findings: list[Finding]) -> bool:
    return any(finding.code.startswith("hooks-policy-block-") for finding in findings)


def _codex_hook_specific_output(hook_id: str, additional_context: str, blocked: bool, system_message: str | None) -> dict[str, object]:
    output: dict[str, object] = {
        "hookEventName": CODEX_HOOK_EVENTS.get(hook_id, hook_id),
        "additionalContext": additional_context,
    }
    if blocked:
        reason = system_message or "MyLittleHarness blocked this deterministic shortcut attempt."
        if hook_id == HOOK_PRE_TOOL_USE:
            output.pop("additionalContext", None)
            output["permissionDecision"] = "deny"
            output["permissionDecisionReason"] = reason
    return output


def _hook_event_context(inventory: Inventory, hook_id: str) -> str:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    plan_status = _payload_value(state, "plan_status")
    active_phase = _payload_value(state, "active_phase")
    return "\n".join(
        [
            f"MyLittleHarness hook context for {hook_id}:",
            f"- lifecycle: plan_status={plan_status}; active_phase={active_phase}",
            "- first-pass navigation: dashboard packet, MCP read/search/bundle when mounted, projection warm-cache if stale, then rg or bounded source reads for exact verification.",
            "- policy: deterministic unsafe shortcuts may be blocked; ambiguous cases are advisory warnings.",
            "- boundary: hook output cannot approve lifecycle, archive, roadmap, staging, commit, push, release, provider routing, daemon state, or cache truth.",
        ]
    )


def _hook_input_summary(hook_input_text: str) -> dict[str, object]:
    stripped = hook_input_text.strip()
    parsed: object = None
    if stripped:
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
    return {
        "provided": bool(stripped),
        "bytes": len(hook_input_text.encode("utf-8", errors="replace")),
        "json": isinstance(parsed, dict),
    }


def _native_hook_policy_findings(inventory: Inventory, hook_id: str, hook_input_text: str) -> list[Finding]:
    if hook_id == HOOK_USER_PROMPT_SUBMIT:
        return _user_prompt_policy_findings(inventory, hook_input_text)
    if hook_id == HOOK_PRE_TOOL_USE:
        return _pre_tool_policy_findings(inventory, hook_input_text)
    if hook_id == HOOK_POST_TOOL_USE:
        return _post_tool_policy_findings(inventory, hook_input_text)
    if hook_id == HOOK_STOP:
        return _stop_policy_findings(inventory)
    return [
        Finding(
            "info",
            "hooks-policy-context",
            f"{hook_id} has no blocking policy beyond dashboard-first context injection",
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        )
    ]


def _user_prompt_policy_findings(inventory: Inventory, hook_input_text: str) -> list[Finding]:
    text = _hook_input_search_text(hook_input_text)
    findings = [
        Finding(
            "info",
            "hooks-policy-user-prompt-submit",
            "user-prompt-submit injects dashboard-first navigation, cache posture, MCP adoption, and rg verification reminders before route-sensitive work",
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        )
    ]
    if _looks_like_shortcut_prompt(text):
        findings.append(
            Finding(
                "warn",
                "hooks-policy-shortcut-prompt",
                "prompt appears to ask for shortcut-prone lifecycle work; use dashboard, active plan, check, and explicit dry-run/apply rails before mutation",
                "project/project-state.md" if inventory.state and inventory.state.exists else None,
            )
        )
    return findings


def _pre_tool_policy_findings(inventory: Inventory, hook_input_text: str) -> list[Finding]:
    data = _hook_input_data(hook_input_text)
    text = _hook_input_search_text(hook_input_text)
    paths = _hook_input_paths(data, text)
    findings = [
        Finding(
            "info",
            "hooks-policy-pre-tool-use",
            "pre-tool-use inspects declared tool intent and blocks deterministic MLH shortcut attempts before tool execution",
        )
    ]
    for finding in _path_policy_findings(inventory, paths):
        findings.append(finding)
    command = _hook_input_command(data, text)
    lowered = command.casefold()
    if _looks_like_generated_cache_write(paths, command):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-generated-cache-write",
                "blocked deterministic generated-cache write; use `mylittleharness --root <root> projection --warm-cache --target all` or rebuild rails instead",
                ".mylittleharness/generated",
            )
        )
    if _looks_like_lifecycle_markdown_write(paths, command):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-lifecycle-markdown-shortcut",
                "blocked direct lifecycle Markdown write without MLH route/frontmatter evidence; use the owning dry-run/apply rail or repair route",
                paths[0] if paths else "project",
            )
        )
    if _looks_like_code_write(paths, command):
        out_of_scope = [path for path in paths if _is_code_path(path) and not _is_active_plan_target_artifact(inventory, path)]
        if not _has_active_plan(inventory):
            findings.append(
                Finding(
                    "warn",
                    "hooks-policy-warn-code-write-without-plan",
                    "tool request appears to write source/test code while no active implementation plan is open; keep edits bounded and record lifecycle evidence before closeout",
                    out_of_scope[0] if out_of_scope else (paths[0] if paths else None),
                )
            )
        elif out_of_scope:
            findings.append(
                Finding(
                    "error",
                    "hooks-policy-block-code-write-outside-plan-scope",
                    "blocked source/test write outside the active plan target_artifacts; update the roadmap/plan scope before editing this path",
                    out_of_scope[0],
                )
            )
    if _looks_like_unsafe_mlh_mutation(lowered) and not _has_explicit_mlh_review_mode(lowered):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-mlh-mutation-without-mode",
                "blocked MLH mutating command without explicit dry-run/apply or a recognized read-only/cache route",
            )
        )
    if _looks_like_next_plan_apply(lowered) and _has_active_plan(inventory):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-next-plan-while-active",
                "blocked opening a new active plan while the current plan is still active; close, cancel, or explicitly update the active plan first",
                "project/implementation-plan.md",
            )
        )
    if _looks_like_git_stage_or_commit(lowered) and _active_plan_not_ready_for_git(inventory):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-git-before-lifecycle-closeout",
                "blocked Git staging/commit while an active plan phase is not complete; record verification and lifecycle state transfer before Git mutation",
                "project/implementation-plan.md",
            )
        )
    if _looks_like_product_root_direct_edit(inventory, paths, command):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-product-root-direct-edit",
                "blocked direct product-source edit from a serviced operating-root hook context; edit the configured product_source_root deliberately",
                paths[0] if paths else None,
            )
        )
    if len(findings) == 1:
        findings.append(Finding("info", "hooks-policy-pre-tool-use-clear", "no deterministic shortcut block matched this tool request"))
    return findings


def _post_tool_policy_findings(inventory: Inventory, hook_input_text: str) -> list[Finding]:
    data = _hook_input_data(hook_input_text)
    text = _hook_input_search_text(hook_input_text)
    paths = _hook_input_paths(data, text)
    findings = [
        Finding(
            "info",
            "hooks-policy-post-tool-use",
            "post-tool-use reports shortcut posture after tool execution; it cannot repair or approve the result",
        )
    ]
    findings.extend(_path_policy_findings(inventory, paths, warn_only=True))
    if len(findings) == 1:
        findings.append(Finding("info", "hooks-policy-post-tool-use-clear", "no deterministic post-tool warning matched this tool result"))
    return findings


def _stop_policy_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "hooks-policy-stop",
            "stop checks for dangling active lifecycle posture before the agent finalizes; hook output remains advisory",
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        )
    ]
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    if str(state.get("plan_status") or "").casefold() == "active":
        findings.append(
            Finding(
                "warn",
                "hooks-policy-stop-active-plan-open",
                (
                    f"active plan remains open at {_payload_value(state, 'active_plan')}; "
                    "record phase writeback/verification before confident final closeout wording"
                ),
                _payload_value(state, "active_plan"),
            )
        )
    return findings


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
            "- mcp coverage: read_projection=current posture; read_source=bounded source slices; search=source-verified exact/path/full-text; related_or_bundle=links/fan-in/relationship bundle",
            f"- next legal dry-run: {_payload_value(next_legal, 'command')}",
            f"- recommended first-pass commands: {', '.join(str(command) for command in recommended[:4])}",
            "- exact verification: use `rg` or `mylittleharness.read_source` before source edits or closeout claims.",
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


def _hook_input_data(hook_input_text: str) -> dict[str, object]:
    if not hook_input_text.strip():
        return {}
    try:
        value = json.loads(hook_input_text)
    except json.JSONDecodeError:
        return {"raw": hook_input_text}
    return value if isinstance(value, dict) else {"raw": value}


def _hook_input_search_text(hook_input_text: str) -> str:
    data = _hook_input_data(hook_input_text)
    return _stringify_jsonish(data) if data else hook_input_text


def _stringify_jsonish(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_stringify_jsonish(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_stringify_jsonish(item) for item in value)
    return str(value or "")


def _hook_input_command(data: dict[str, object], fallback_text: str) -> str:
    candidates = (
        data.get("command"),
        data.get("shell_command"),
        data.get("cmd"),
        data.get("args"),
        data.get("input"),
        data.get("tool_input"),
        data.get("parameters"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
        if isinstance(candidate, dict):
            nested = _hook_input_command(candidate, "")
            if nested:
                return nested
        if isinstance(candidate, list) and candidate:
            return " ".join(str(item) for item in candidate)
    return fallback_text


def _hook_input_paths(data: dict[str, object], text: str) -> list[str]:
    paths: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).casefold() in {"path", "file", "filename", "target", "cwd", "workdir", "command", "shell_command"}:
                    collect(item)
                elif isinstance(item, (dict, list)):
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, str):
            paths.extend(_extract_paths(value))

    collect(data)
    paths.extend(_extract_paths(text))
    normalized: list[str] = []
    seen: set[str] = set()
    for path in paths:
        clean = _normalize_hook_path(path)
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)
    return normalized


def _extract_paths(text: str) -> list[str]:
    matches: list[str] = []
    for match in PATH_RE.finditer(text or ""):
        value = match.group(0).strip(" \t\r\n\"'`") or (match.group(1) or "").strip(" \t\r\n\"'`")
        if value:
            matches.append(value)
    return matches


def _normalize_hook_path(path: str) -> str:
    rel = str(path or "").strip().strip(".,;:)]}").replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def _path_policy_findings(inventory: Inventory, paths: list[str], *, warn_only: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for rel in paths:
        if _is_generated_cache_path(rel):
            findings.append(
                Finding(
                    "warn",
                    "hooks-policy-warn-generated-cache-path" if warn_only else "hooks-policy-generated-cache-path",
                    "tool request touches generated projection/cache paths; cache remains disposable and should be refreshed through projection rails",
                    rel,
                )
            )
        if _is_lifecycle_authority_path(rel):
            findings.append(
                Finding(
                    "warn",
                    "hooks-policy-lifecycle-authority-path",
                    "tool request touches lifecycle authority paths; use explicit MLH dry-run/apply routes and record docs_decision/verification as required",
                    rel,
                )
            )
        elif _is_lifecycle_markdown_path(rel):
            findings.append(
                Finding(
                    "warn",
                    "hooks-policy-lifecycle-markdown-path",
                    "tool request touches lifecycle Markdown routes; required frontmatter and owning route evidence must stay intact",
                    rel,
                )
            )
        if _is_under_configured_product_root(inventory, rel):
            findings.append(
                Finding(
                    "warn",
                    "hooks-policy-product-root-path",
                    "tool request names the configured product source root from an operating-root context; keep product edits deliberate and bounded",
                    rel,
                )
            )
    return findings


def _looks_like_shortcut_prompt(text: str) -> bool:
    lowered = (text or "").casefold()
    shortcut_terms = ("without plan", "skip check", "skip dry-run", "no frontmatter", "archive anyway", "mark done", "shortcut", "шорткат", "без плана", "без проверки")
    return any(term in lowered for term in shortcut_terms)


def _looks_like_generated_cache_write(paths: list[str], command: str) -> bool:
    return any(_is_generated_cache_path(path) for path in paths) and _looks_like_write_command(command)


def _looks_like_lifecycle_markdown_write(paths: list[str], command: str) -> bool:
    return any(_is_lifecycle_markdown_path(path) for path in paths) and _looks_like_write_command(command) and "mylittleharness" not in command.casefold()


def _looks_like_product_root_direct_edit(inventory: Inventory, paths: list[str], command: str) -> bool:
    if not _looks_like_write_command(command):
        return False
    return any(_is_under_configured_product_root(inventory, path) and not _is_active_plan_product_artifact(inventory, path) for path in paths)


def _looks_like_code_write(paths: list[str], command: str) -> bool:
    return _looks_like_write_command(command) and any(_is_code_path(path) for path in paths)


def _looks_like_write_command(command: str) -> bool:
    lowered = f" {command.casefold()} "
    return any(token in lowered for token in WRITING_COMMAND_TOKENS)


def _looks_like_git_stage_or_commit(lowered_command: str) -> bool:
    padded = f" {lowered_command} "
    return any(token in padded for token in GIT_WRITE_COMMANDS)


def _looks_like_next_plan_apply(lowered_command: str) -> bool:
    padded = f" {lowered_command} "
    if " --update-active" in padded:
        return False
    return "mylittleharness" in padded and " plan " in padded and " --apply" in padded


def _looks_like_unsafe_mlh_mutation(lowered_command: str) -> bool:
    if not any(token in lowered_command for token in MLH_MUTATION_COMMANDS):
        return False
    mutating_terms = (
        " repair ",
        " plan ",
        " writeback ",
        " transition ",
        " roadmap ",
        " meta-feedback ",
        " projection ",
        " memory-hygiene ",
        " hooks ",
        " adapter --install-client-config ",
    )
    padded = f" {lowered_command} "
    return any(term in padded for term in mutating_terms)


def _has_explicit_mlh_review_mode(lowered_command: str) -> bool:
    padded = f" {lowered_command} "
    if " --dry-run" in padded or " --apply" in padded or " --help" in padded or " -h" in padded:
        return True
    if " mylittleharness" in padded and " projection " in padded:
        return any(
            term in padded
            for term in (
                " --inspect",
                " --warm-cache",
                " --rebuild",
                " --build",
                " --delete",
            )
        )
    if " mylittleharness" in padded and " hooks " in padded:
        return " --doctor" in padded or " --run " in padded
    return False


def _is_generated_cache_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return any(rel.startswith(prefix) for prefix in GENERATED_CACHE_PREFIXES)


def _is_code_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.endswith(".py") and any(rel.startswith(prefix) for prefix in CODE_WRITE_PREFIXES)


def _has_active_plan(inventory: Inventory) -> bool:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return str(state.get("plan_status") or "").strip().casefold() == "active" and bool(str(state.get("active_plan") or "").strip())


def _active_plan_not_ready_for_git(inventory: Inventory) -> bool:
    if not _has_active_plan(inventory):
        return False
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return str(state.get("phase_status") or "").strip().casefold() != "complete"


def _is_lifecycle_authority_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel in LIFECYCLE_AUTHORITY_PATHS


def _is_lifecycle_markdown_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.endswith(".md") and any(rel.startswith(prefix) for prefix in LIFECYCLE_MARKDOWN_PREFIXES)


def _is_under_configured_product_root(inventory: Inventory, path: str) -> bool:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    product_root = str(state.get("product_source_root") or "").strip()
    if not product_root:
        return False
    try:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            return False
        candidate.resolve().relative_to(Path(product_root).expanduser().resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _is_active_plan_product_artifact(inventory: Inventory, path: str) -> bool:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return False
    rel = _product_relative_path(inventory, path)
    if not rel:
        return False
    artifacts = plan.frontmatter.data.get("target_artifacts")
    if not isinstance(artifacts, list):
        return False
    normalized = _normalize_hook_path(rel).casefold()
    for artifact in artifacts:
        candidate = _normalize_hook_path(str(artifact or "")).casefold()
        if candidate and normalized == candidate:
            return True
    return False


def _is_active_plan_target_artifact(inventory: Inventory, path: str) -> bool:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return False
    artifacts = plan.frontmatter.data.get("target_artifacts")
    if not isinstance(artifacts, list):
        return False
    normalized = _normalize_plan_artifact_candidate(inventory, path)
    if not normalized:
        return False
    for artifact in artifacts:
        candidate = _normalize_hook_path(str(artifact or "")).casefold()
        if candidate and normalized == candidate:
            return True
    return False


def _normalize_plan_artifact_candidate(inventory: Inventory, path: str) -> str:
    rel = _product_relative_path(inventory, path)
    if rel:
        return _normalize_hook_path(rel).casefold()
    try:
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            return candidate.resolve().relative_to(inventory.root.resolve()).as_posix().casefold()
    except (OSError, RuntimeError, ValueError):
        return ""
    return _normalize_hook_path(path).casefold()


def _product_relative_path(inventory: Inventory, path: str) -> str:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    product_root = str(state.get("product_source_root") or "").strip()
    if not product_root:
        return ""
    try:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            return ""
        return candidate.resolve().relative_to(Path(product_root).expanduser().resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return ""


def _codex_hooks_config_path(root: Path, request: CodexHookAdapterRequest) -> Path:
    return _native_hooks_config_path(root, request)


def _native_hooks_config_path(root: Path, request: CodexHookAdapterRequest) -> Path:
    if request.config_path:
        candidate = Path(request.config_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        return candidate
    if request.scope == "project":
        return root / _native_hooks_config_rel_path(request.client)
    return root / ".mylittleharness" / f"unsupported-{request.client}-hooks.json"


def _codex_hook_script_path(root: Path, request: CodexHookAdapterRequest) -> Path:
    return _native_hook_script_path(root, request)


def _native_hook_script_path(root: Path, request: CodexHookAdapterRequest) -> Path:
    if request.scope == "project":
        return root / _native_hook_script_rel_path(request.client)
    return root / ".mylittleharness" / f"unsupported-{request.client}-hook.py"


def _codex_hook_adapter_status(root: Path, request: CodexHookAdapterRequest) -> str:
    config_path = _native_hooks_config_path(root, request)
    script_path = _native_hook_script_path(root, request)
    try:
        config_current = config_path.is_file() and not config_path.is_symlink() and config_path.read_text(encoding="utf-8") == render_native_hooks_json(root, request)
    except (OSError, ValueError):
        config_current = False
    try:
        script_current = script_path.is_file() and not script_path.is_symlink() and script_path.read_text(encoding="utf-8") == render_native_hook_script(request.client)
    except OSError:
        script_current = False
    if config_current and script_current:
        return "mounted"
    if not config_path.exists() and not script_path.exists():
        return "missing"
    return "needs-update"


def _read_codex_hooks_config(config_path: Path) -> dict[str, object]:
    return _read_native_hooks_config(config_path, CODEX_CLIENT)


def _read_native_hooks_config(config_path: Path, client: str) -> dict[str, object]:
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{_native_hook_client_label(client)} hooks config is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"{_native_hook_client_label(client)} hooks config could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{_native_hook_client_label(client)} hooks config root must be a JSON object")
    hooks = payload.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{_native_hook_client_label(client)} hooks config `hooks` field must be a JSON object")
    if client == GITHUB_COPILOT_CLIENT and "version" in payload and payload.get("version") != 1:
        raise ValueError("GitHub Copilot hooks config `version` must be 1 when present")
    for event_name in _native_hook_event_names(client):
        event_hooks = hooks.get(event_name, [])
        if not isinstance(event_hooks, list):
            raise ValueError(f"{_native_hook_client_label(client)} hooks config `hooks.{event_name}` field must be a JSON array")
    return payload


def _merge_codex_native_hooks(existing: dict[str, object]) -> dict[str, object]:
    merged = json.loads(json.dumps(existing))
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        merged["hooks"] = hooks
    for hook_id in CODEX_NATIVE_HOOKS:
        codex_event = CODEX_HOOK_EVENTS[hook_id]
        existing_groups = hooks.get(codex_event, [])
        if not isinstance(existing_groups, list):
            existing_groups = []
        filtered_groups = [group for group in existing_groups if not _is_mlh_codex_hook_group(group)]
        filtered_groups.append(_codex_hook_group(hook_id))
        hooks[codex_event] = filtered_groups
    return merged


def _merge_claude_code_native_hooks(existing: dict[str, object]) -> dict[str, object]:
    merged = json.loads(json.dumps(existing))
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        merged["hooks"] = hooks
    for hook_id in NATIVE_ADAPTER_HOOKS:
        event_name = CODEX_HOOK_EVENTS[hook_id]
        existing_groups = hooks.get(event_name, [])
        if not isinstance(existing_groups, list):
            existing_groups = []
        filtered_groups = [group for group in existing_groups if not _is_mlh_native_hook_group(group, CLAUDE_CODE_HOOK_SCRIPT_REL_PATH)]
        filtered_groups.append(_claude_code_hook_group(hook_id))
        hooks[event_name] = filtered_groups
    return merged


def _merge_github_copilot_native_hooks(existing: dict[str, object]) -> dict[str, object]:
    merged = json.loads(json.dumps(existing))
    merged["version"] = 1
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        merged["hooks"] = hooks
    for hook_id in NATIVE_ADAPTER_HOOKS:
        event_name = GITHUB_COPILOT_HOOK_EVENTS[hook_id]
        existing_entries = hooks.get(event_name, [])
        if not isinstance(existing_entries, list):
            existing_entries = []
        filtered_entries = [entry for entry in existing_entries if not _is_mlh_github_copilot_hook_entry(entry)]
        filtered_entries.append(_github_copilot_hook_entry(hook_id))
        hooks[event_name] = filtered_entries
    return merged


def _codex_hook_group(hook_id: str) -> dict[str, object]:
    return {
        "matcher": CODEX_HOOK_MATCHERS[hook_id],
        "hooks": [
            {
                "type": "command",
                "command": _codex_hook_command(hook_id),
                "timeout": 30,
                "statusMessage": CODEX_HOOK_STATUS_MESSAGES[hook_id],
            }
        ],
    }


def _claude_code_hook_group(hook_id: str) -> dict[str, object]:
    group: dict[str, object] = {
        "hooks": [
            {
                "type": "command",
                "command": _native_hook_command(CLAUDE_CODE_CLIENT, hook_id),
                "timeout": 30,
                "statusMessage": CODEX_HOOK_STATUS_MESSAGES[hook_id],
            }
        ],
    }
    if hook_id not in {HOOK_USER_PROMPT_SUBMIT, HOOK_STOP}:
        group["matcher"] = CODEX_HOOK_MATCHERS[hook_id]
    return group


def _github_copilot_hook_entry(hook_id: str) -> dict[str, object]:
    return {
        "type": "command",
        "command": _native_hook_command(GITHUB_COPILOT_CLIENT, hook_id),
        "timeoutSec": 30,
    }


def _codex_hook_command(hook_id: str) -> str:
    return _native_hook_command(CODEX_CLIENT, hook_id)


def _native_hook_command(client: str, hook_id: str) -> str:
    if client == CODEX_CLIENT:
        script_rel = CODEX_HOOK_SCRIPT_REL_PATH
    else:
        script_rel = _native_hook_script_rel_path(client)
    parts_literal = _py_literal(tuple(script_rel.split("/")))
    script_label = "MLH Codex hook script" if client == CODEX_CLIENT else f"MLH {client} hook script"
    return (
        "python -c \"from pathlib import Path; import os; import runpy; "
        "p=Path.cwd().resolve(); roots=(p, *p.parents); "
        f"parts={parts_literal}; "
        "script=next((r.joinpath(*parts) for r in roots if r.joinpath(*parts).is_file()), None); "
        f"assert script is not None, {_py_literal(script_label + ' not found from cwd')}; "
        f"os.environ['MLH_HOOK_EVENT']={_py_literal(hook_id)}; "
        "runpy.run_path(str(script), run_name='__main__')\""
    )


def _is_mlh_codex_hook_group(group: object) -> bool:
    return _is_mlh_native_hook_group(group, CODEX_HOOK_SCRIPT_REL_PATH)


def _is_mlh_native_hook_group(group: object, script_rel_path: str) -> bool:
    if not isinstance(group, dict):
        return False
    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        return False
    for handler in handlers:
        if not isinstance(handler, dict):
            continue
        command = str(handler.get("command") or "")
        if Path(script_rel_path).name in command:
            return True
    return False


def _is_mlh_github_copilot_hook_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    command = str(entry.get("command") or "")
    return Path(GITHUB_COPILOT_HOOK_SCRIPT_REL_PATH).name in command


def _native_hooks_config_rel_path(client: str) -> str:
    if client == CLAUDE_CODE_CLIENT:
        return CLAUDE_CODE_HOOKS_REL_PATH
    if client == GITHUB_COPILOT_CLIENT:
        return GITHUB_COPILOT_HOOKS_REL_PATH
    return CODEX_HOOKS_REL_PATH


def _native_hook_script_rel_path(client: str) -> str:
    if client == CLAUDE_CODE_CLIENT:
        return CLAUDE_CODE_HOOK_SCRIPT_REL_PATH
    if client == GITHUB_COPILOT_CLIENT:
        return GITHUB_COPILOT_HOOK_SCRIPT_REL_PATH
    return CODEX_HOOK_SCRIPT_REL_PATH


def _native_hook_event_names(client: str) -> list[str]:
    if client == GITHUB_COPILOT_CLIENT:
        return [GITHUB_COPILOT_HOOK_EVENTS[hook_id] for hook_id in NATIVE_ADAPTER_HOOKS]
    return [CODEX_HOOK_EVENTS[hook_id] for hook_id in NATIVE_ADAPTER_HOOKS]


def _native_hook_event_name(client: str, hook_id: str) -> str:
    if client == GITHUB_COPILOT_CLIENT:
        return GITHUB_COPILOT_HOOK_EVENTS[hook_id]
    return CODEX_HOOK_EVENTS[hook_id]


def _native_hook_client_label(client: str) -> str:
    if client == CLAUDE_CODE_CLIENT:
        return "Claude Code"
    if client == GITHUB_COPILOT_CLIENT:
        return "GitHub Copilot"
    if client == CODEX_CLIENT:
        return "Codex"
    return client


def _hook_adapter_code_prefix(request: CodexHookAdapterRequest) -> str:
    return "hooks-codex-adapter" if request.client == CODEX_CLIENT else "hooks-native-adapter"


def _unsafe_parent_directory_findings(root: Path, path: Path, code: str) -> list[Finding]:
    findings: list[Finding] = []
    current = path.parent
    while True:
        if not _is_within_root(root, current):
            break
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            findings.append(Finding("error", code, f"hook target parent is not a safe directory: {_rel_path(root, current)}", _rel_path(root, current)))
            break
        if current == root:
            break
        current = current.parent
    return findings


def _py_literal(value: object) -> str:
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
