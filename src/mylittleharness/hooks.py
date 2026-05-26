from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from .context_memory import context_memory_hook_context
from .dashboard import dashboard_agent_packet, dashboard_payload, mlhd_freshness_payload
from .inventory import Inventory
from .models import Finding
from .parsing import parse_frontmatter
from .preflight import preflight_sections
from .routes import classify_memory_route
from .root_boundary import PRODUCT_SOURCE_FIXTURE
from .safe_commands import mlh_command, safe_double_quoted, safe_intent_text, shell_arg


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
HOOK_POLICY_SCHEMA = "mylittleharness.hook-policy.v1"
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
FAST_COMMAND_OUTPUT_HOOKS = (HOOK_USER_PROMPT_SUBMIT, HOOK_PRE_TOOL_USE, HOOK_POST_TOOL_USE, HOOK_STOP)
BOUNDED_MLH_READ_TOOL_SUFFIXES = (
    "mylittleharness_read_projection",
    "mylittleharness_read_source",
    "mylittleharness_related_or_bundle",
    "mylittleharness_search",
)
READ_ONLY_SOURCE_DISCOVERY_COMMANDS = {
    "cat",
    "dir",
    "rg",
    "ripgrep",
    "select-string",
    "findstr",
    "gc",
    "get-childitem",
    "get-content",
    "get-item",
    "ls",
    "more",
    "resolve-path",
    "test-path",
    "type",
}
READ_ONLY_SOURCE_DISCOVERY_PREFIX_TOKENS = {
    "&",
    "=",
    "catch",
    "do",
    "else",
    "elseif",
    "finally",
    "for",
    "foreach",
    "if",
    "in",
    "try",
    "where",
    "where-object",
    "while",
}
READ_ONLY_GIT_INSPECTION_COMMANDS = {"diff", "show", "status", "log"}
GIT_MUTATION_COMMANDS = {"add", "stage", "commit", "push", "reset", "checkout", "clean", "restore", "rm", "mv"}
GIT_OPTIONS_WITH_VALUES = {
    "-c",
    "--config-env",
    "--exec-path",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}
MLH_OWNER_ROUTE_REVIEW_COMMANDS = {
    "intake",
    "incubate",
    "memory-hygiene",
    "meta-feedback",
    "plan",
    "projection",
    "repair",
    "research-import",
    "roadmap",
    "suggest",
    "transition",
    "writeback",
}
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
WRITING_COMMAND_NAMES = {
    "ac",
    "add-content",
    "copy",
    "copy-item",
    "cp",
    "cpi",
    "del",
    "erase",
    "mi",
    "move-item",
    "mv",
    "new",
    "new-item",
    "ni",
    "out-file",
    "remove-item",
    "ri",
    "rm",
    "sc",
    "set-content",
    "tee",
    "tee-object",
}
SHELL_COMMAND_SEPARATORS = {";", "&", "&&", "||", "|", "{", "}", "then", "do", "else", "elseif"}
SINGLE_TARGET_WRITING_COMMAND_NAMES = WRITING_COMMAND_NAMES - {"copy", "copy-item", "cp", "cpi", "mi", "move-item", "mv"}
PAIRED_TARGET_WRITING_COMMAND_NAMES = {"copy", "copy-item", "cp", "cpi", "mi", "move-item", "mv"}
WRITING_COMMAND_PATH_OPTIONS = {"-path", "-literalpath", "-filepath", "-destination"}
WRITING_COMMAND_NON_TARGET_OPTIONS_WITH_VALUES = {
    "-encoding",
    "-filter",
    "-include",
    "-inputobject",
    "-itemtype",
    "-name",
    "-type",
    "-value",
}
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
EDITABLE_ROUTE_PATCH_IDS = (
    "adrs",
    "archive",
    "decisions",
    "incubation",
    "research",
    "stable-specs",
    "verification",
)
ACTIVE_PLAN_SPEC_DOC_PREFIXES = ("docs/specs/", "project/specs/")
GENERATED_CACHE_PREFIXES = (".mylittleharness/generated/",)
NONROUTE_PROJECT_MARKDOWN_EXEMPT_PREFIXES = (
    "project/cache/",
    "project/generated/",
    "project/private/",
    "project/scratch/",
    "project/secrets/",
    "project/temp/",
    "project/tmp/",
)
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
POWERSHELL_HERE_STRING_RE = re.compile(r"@(['\"])\r?\n.*?\r?\n\1@", re.DOTALL)
POSIX_HEREDOC_START_RE = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")


@dataclass(frozen=True)
class HookInstallRequest:
    hook_id: str
    force: bool = False


@dataclass(frozen=True)
class CodexHookAdapterRequest:
    client: str = CODEX_CLIENT
    scope: str = "project"
    config_path: str = ""


@dataclass(frozen=True)
class HookToolIntent:
    command: str
    paths: list[str]
    write_command: str
    write_target_paths: list[str]


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
    policy = _hook_policy_identity()
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
                    f"config={_rel_path(inventory.root, config_path)}; script={_rel_path(inventory.root, script_path)}; "
                    f"policy_hash={policy['sourceHash']}"
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
    policy = _hook_policy_identity()
    return {
        "schema": CODEX_HOOK_ADAPTER_SCHEMA,
        "client": request.client,
        "scope": request.scope,
        "status": _codex_hook_adapter_status(inventory.root, request),
        "configPath": _rel_path(inventory.root, config_path),
        "scriptPath": _rel_path(inventory.root, script_path),
        "events": [_native_hook_event_name(request.client, hook_id) for hook_id in NATIVE_ADAPTER_HOOKS],
        "policy": policy,
        "dryRunCommand": _hook_adapter_review_command(request, "--dry-run"),
        "applyCommand": _hook_adapter_review_command(request, "--apply"),
        "includedInCodexMcpInstall": True,
        "includedInAttachApply": True,
        "boundary": {
            "writesRepoFilesOnApplyOnly": True,
            "writesUserConfig": False,
            "startsRuntime": False,
            "authorizesLifecycle": False,
            "correctnessPrerequisite": False,
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
    connect_readiness = dashboard.get("connectReadiness") if isinstance(dashboard.get("connectReadiness"), dict) else {}
    if not connect_readiness and isinstance(agent_packet.get("connectReadiness"), dict):
        connect_readiness = agent_packet["connectReadiness"]
    mlhd = dashboard.get("mlhd") if isinstance(dashboard.get("mlhd"), dict) else mlhd_freshness_payload(inventory)
    accelerator_adoption = (
        agent_packet.get("acceleratorAdoption") if isinstance(agent_packet.get("acceleratorAdoption"), dict) else dashboard.get("acceleratorAdoption")
    )
    if not isinstance(accelerator_adoption, dict):
        accelerator_adoption = {}
    lifecycle = agent_packet.get("lifecycle") if isinstance(agent_packet.get("lifecycle"), dict) else {}
    blocked = _hook_blocked(findings)
    status = "block" if blocked else _hook_status(findings)
    status_message = _hook_status_message(hook_id, lifecycle, cache_posture)
    policy = _hook_policy_identity()
    additional_context = (
        _hook_additional_context(agent_packet, cache_posture, accelerator_adoption, connect_readiness, mlhd)
        if hook_id in FIRST_CONTACT_HOOKS
        else _hook_event_context(inventory, hook_id)
    )
    system_message = _hook_system_message(findings)
    codex_specific_output = _codex_hook_specific_output(hook_id, additional_context, blocked, system_message)
    return {
        "schema": "mylittleharness.hook-event.v1",
        "event": hook_id,
        "status": status,
        "policy_mode": "block" if blocked else "warn",
        "policy": policy,
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
        "connectReadiness": connect_readiness,
        "mlhd": mlhd,
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
    if hook_id in FAST_COMMAND_OUTPUT_HOOKS:
        return _codex_hook_command_output_fast(inventory, hook_id, hook_input_text)

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

    if hook_id == HOOK_STOP:
        if blocked:
            reason = system_message if isinstance(system_message, str) and system_message else "MyLittleHarness blocked this stop event by deterministic policy."
            return {"decision": "block", "reason": reason}
        return {}

    result = {"continue": bool(codex_output.get("continue", True))}
    if isinstance(system_message, str) and system_message:
        result["systemMessage"] = system_message
    if isinstance(hook_specific, dict):
        result["hookSpecificOutput"] = hook_specific
    return result


def _codex_hook_command_output_fast(inventory: Inventory, hook_id: str, hook_input_text: str = "") -> dict[str, object]:
    findings = _native_hook_policy_findings(inventory, hook_id, hook_input_text)
    blocked = _hook_blocked(findings)
    system_message = _hook_system_message(findings)
    hook_specific = _codex_hook_specific_output(hook_id, _hook_event_context(inventory, hook_id), blocked, system_message)

    if hook_id == HOOK_PRE_TOOL_USE:
        result: dict[str, object] = {}
        if isinstance(system_message, str) and system_message:
            result["systemMessage"] = system_message
        if hook_specific:
            result["hookSpecificOutput"] = hook_specific
        return result

    if hook_id == HOOK_USER_PROMPT_SUBMIT and blocked:
        reason = system_message if isinstance(system_message, str) and system_message else "MyLittleHarness blocked this prompt by deterministic policy."
        return {"decision": "block", "reason": reason}

    if hook_id == HOOK_STOP:
        if blocked:
            reason = system_message if isinstance(system_message, str) and system_message else "MyLittleHarness blocked this stop event by deterministic policy."
            return {"decision": "block", "reason": reason}
        return {}

    result: dict[str, object] = {"continue": not blocked}
    if isinstance(system_message, str) and system_message:
        result["systemMessage"] = system_message
    if hook_specific:
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
    policy = _hook_policy_identity()
    return "\n".join(
        [
            "# Generated by MyLittleHarness. Do not edit by hand unless replacing the hook adapter.",
            f"# Hook policy schema: {policy['schema']}",
            f"# Hook policy source: {policy['source']}",
            f"# Hook policy hash: {policy['sourceHash']}",
            "from __future__ import annotations",
            "",
            "import os",
            "import sys",
            "from pathlib import Path",
            "",
            f"MLH_IMPORT_ROOT = {import_root_literal}",
            f"MLH_HOOK_POLICY_SCHEMA = {policy['schema']!r}",
            f"MLH_HOOK_POLICY_SOURCE = {policy['source']!r}",
            f"MLH_HOOK_POLICY_HASH = {policy['sourceHash']!r}",
            "if MLH_IMPORT_ROOT and MLH_IMPORT_ROOT not in sys.path:",
            "    sys.path.insert(0, MLH_IMPORT_ROOT)",
            "",
            "import json",
            "",
            "from mylittleharness.hooks import CODEX_HOOK_EVENTS, CODEX_SESSION_START_EVENT, HOOK_SESSION_START, HOOK_STOP, codex_hook_command_output, codex_session_start_command_output",
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
            "        if hook_event == HOOK_STOP:",
            "            payload = {}",
            "        else:",
            "            payload = {",
            "                \"continue\": True,",
            "                \"systemMessage\": f\"MLH hook failed: {exc}\",",
            "                \"hookSpecificOutput\": {",
            "                    \"hookEventName\": CODEX_HOOK_EVENTS.get(hook_event, CODEX_SESSION_START_EVENT),",
            "                    \"additionalContext\": \"MyLittleHarness first-contact context unavailable; run `mylittleharness --root <root> check` before lifecycle-sensitive work.\",",
            "                },",
            "            }",
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
    policy = _hook_policy_identity()
    return "\n".join(
        [
            "# Generated by MyLittleHarness. Do not edit by hand unless replacing the hook adapter.",
            f"# Hook policy schema: {policy['schema']}",
            f"# Hook policy source: {policy['source']}",
            f"# Hook policy hash: {policy['sourceHash']}",
            "from __future__ import annotations",
            "",
            "import os",
            "import sys",
            "from pathlib import Path",
            "",
            f"MLH_IMPORT_ROOT = {import_root_literal}",
            f"MLH_HOOK_POLICY_SCHEMA = {policy['schema']!r}",
            f"MLH_HOOK_POLICY_SOURCE = {policy['source']!r}",
            f"MLH_HOOK_POLICY_HASH = {policy['sourceHash']!r}",
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
    policy = _hook_policy_identity()
    findings = [
        Finding("info", f"{prefix}-target", f"client={request.client}; scope={request.scope}; config={_rel_path(inventory.root, config_path)}", _rel_path(inventory.root, config_path)),
        Finding("info", f"{prefix}-script", f"helper script target={_rel_path(inventory.root, script_path)}", _rel_path(inventory.root, script_path)),
        Finding("info", f"{prefix}-status", f"{label} hook adapter status={status}; project-local hooks require a trusted project and may need client hook review or a new session", _rel_path(inventory.root, config_path)),
        Finding(
            "info",
            f"{prefix}-policy",
            (
                f"{label} hook policy source={policy['source']}; policy_hash={policy['sourceHash']}; "
                f"refresh_dry_run={_hook_adapter_review_command(request, '--dry-run')}; "
                f"refresh_apply={_hook_adapter_review_command(request, '--apply')}"
            ),
            _rel_path(inventory.root, script_path),
        ),
        Finding(
            "info",
            f"{prefix}-event",
            f"{label} native events: {', '.join(event_names)}; hook stdout provides client-valid JSON for context, warning, or deterministic denial",
            _rel_path(inventory.root, config_path),
        ),
    ]
    if status == "needs-update":
        findings.append(
            Finding(
                "warn",
                f"{prefix}-refresh-needed",
                (
                    f"{label} native hook adapter is not current for policy_hash={policy['sourceHash']}; "
                    f"next_safe_command={_hook_adapter_review_command(request, '--dry-run')} then "
                    f"{_hook_adapter_review_command(request, '--apply')}"
                ),
                _rel_path(inventory.root, script_path),
            )
        )
    return findings


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
    if target.is_symlink():
        findings.append(Finding("warn", "hooks-target-symlink", f"hook target is a symlink and apply would be refused: {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    elif target.exists():
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
    findings.extend(_unsafe_parent_directory_findings(inventory.root, target, "hooks-install-refused"))
    if target.is_symlink():
        findings.append(Finding("error", "hooks-install-refused", f"hook target is a symlink: {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    elif target.exists() and not target.is_file():
        findings.append(Finding("error", "hooks-install-refused", f"hook target is not a regular file: {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    if target.exists() and not target.is_symlink() and not request.force and target.read_text(encoding="utf-8", errors="replace") != render_hook_shim(inventory.root, request.hook_id):
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
            "hooks are sensors, blockers, or context injectors only; they are optional and not correctness prerequisites; hook output cannot approve lifecycle movement, closeout, archive, roadmap status, staging, commit, push, rollback, release, product-diff acceptance, dispatcher work, provider routing, or next-plan opening",
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
    return any(finding.severity == "error" and finding.code.startswith("hooks-policy-block-") for finding in findings)


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
    policy = _hook_policy_identity()
    return "\n".join(
        [
            f"MyLittleHarness hook context for {hook_id}:",
            f"- lifecycle: plan_status={plan_status}; active_phase={active_phase}",
            f"- hook_policy: schema={policy['schema']}; source_hash={policy['sourceHash']}; import_root={policy['importRoot']}",
            context_memory_hook_context(inventory),
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
                "hooks-policy-block-shortcut-prompt",
                "prompt appears to ask for shortcut-prone lifecycle work; use dashboard, active plan, check, and explicit dry-run/apply rails before mutation",
                "project/project-state.md" if inventory.state and inventory.state.exists else None,
            )
        )
    return findings


def _pre_tool_policy_findings(inventory: Inventory, hook_input_text: str) -> list[Finding]:
    data = _hook_input_data(hook_input_text)
    text = _hook_input_search_text(hook_input_text)
    intent = _hook_tool_intent(data, text)
    paths = intent.paths
    command = intent.command
    write_command = intent.write_command
    lowered = command.casefold()
    findings = [
        Finding(
            "info",
            "hooks-policy-pre-tool-use",
            "pre-tool-use inspects declared tool intent and blocks deterministic MLH shortcut attempts before tool execution",
        )
    ]
    allow_read_only_source_paths = (
        _is_read_only_source_discovery_command(command)
        or _is_read_only_git_inspection_command(command)
        or _is_bounded_mlh_read_tool_request(data)
    )
    allow_read_only_roadmap_path = _is_read_only_roadmap_direct_read_command(command, paths)
    allow_research_import_related_prompt = _is_research_import_related_prompt_provenance_command(command)
    allow_mlh_owner_route_paths = _is_mlh_owner_route_review_command(command) or allow_research_import_related_prompt
    allow_existing_route_patch = _is_existing_route_markdown_patch_request(inventory, data)
    allow_active_plan_spec_doc_patch = _is_active_plan_spec_doc_patch_request(inventory, data)
    if _active_plan_roadmap_policy_relevant(inventory, command, paths):
        findings.append(
            Finding(
                "info",
                "hooks-policy-active-plan-roadmap-intake-matrix",
                (
                    "active plan is open: allow read-only lifecycle inspection and first-class MLH dry-run/apply "
                    "route review; capture new candidates through meta-feedback/incubation now; defer accepted "
                    "roadmap status/order/dependency/next-item promotion until plan_status=none or explicit "
                    "active-plan coverage; next_safe_candidate=mylittleharness --root <root> meta-feedback "
                    "--dry-run ...; next_safe_after_close=mylittleharness --root <root> roadmap --dry-run ..."
                ),
                "project/" + "implementation-plan.md",
            )
        )
    for finding in _path_policy_findings(
        inventory,
        paths,
        allow_read_only_source_paths=allow_read_only_source_paths,
        allow_read_only_roadmap_path=allow_read_only_roadmap_path,
        allow_mlh_owner_route_paths=allow_mlh_owner_route_paths,
        allow_existing_route_patch=allow_existing_route_patch,
        allow_active_plan_spec_doc_patch=allow_active_plan_spec_doc_patch,
    ):
        findings.append(finding)
    if _looks_like_opaque_shell_payload(command):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-opaque-shell-command",
                (
                    "blocked opaque shell payload such as PowerShell -EncodedCommand; use a visible reviewed "
                    "command or a first-class MLH dry-run route instead"
                ),
            )
        )
    if _looks_like_generated_cache_write(paths, write_command):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-generated-cache-write",
                "blocked deterministic generated-cache write; use `mylittleharness --root <root> projection --warm-cache --target all` or rebuild rails instead",
                ".mylittleharness/generated",
            )
        )
    if (
        _looks_like_lifecycle_markdown_write(paths, write_command)
        and not allow_existing_route_patch
        and not allow_active_plan_spec_doc_patch
    ):
        route_path = paths[0] if paths else "project"
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-lifecycle-markdown-shortcut",
                (
                    "blocked direct lifecycle Markdown write without MLH route/frontmatter evidence; "
                    f"next_safe_command={_hook_route_next_safe_command(inventory, route_path)}"
                ),
                route_path,
            )
        )
    if allow_existing_route_patch:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-existing-route-markdown-patch",
                "allowed bounded apply_patch update of existing frontmatter-bearing route Markdown; authority paths, create/delete, and malformed route files remain blocked",
                paths[0] if paths else None,
            )
        )
    if allow_active_plan_spec_doc_patch:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-active-plan-spec-doc-route-patch",
                (
                    "allowed bounded apply_patch update of active-phase write_scope docs/spec route file(s); "
                    "frontmatter-bearing existing files only, with lifecycle authority paths and create/delete still blocked"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_mlh_owner_route_paths:
        owner_route_evidence_path = _first_mlh_owner_route_evidence_path(inventory, paths)
        if owner_route_evidence_path:
            findings.append(
                Finding(
                    "info",
                    "hooks-policy-allow-mlh-owner-route-evidence-paths",
                    "allowed MLH owner-route dry-run/apply evidence paths; direct lifecycle or product-source writes remain blocked",
                    owner_route_evidence_path,
                )
            )
    if allow_research_import_related_prompt:
        related_prompt = _research_import_related_prompt_path(command)
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-research-import-related-prompt-provenance",
                "allowed research-import related-prompt as read-only provenance; the referenced lifecycle Markdown is not treated as a mutation target",
                related_prompt or None,
            )
        )
    if allow_read_only_source_paths and any(_is_lifecycle_route_path(path) for path in paths):
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-read-only-lifecycle-inspection",
                "allowed read-only lifecycle inspection; route files remain authority and this hook output cannot approve mutation or lifecycle movement",
                paths[0] if paths else None,
            )
        )
    nonroute_markdown = _nonroute_project_markdown_write_path(paths, write_command)
    if nonroute_markdown:
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-nonroute-project-markdown-write",
                (
                    "blocked project Markdown write outside an MLH-visible route; use intake or an owned route such as "
                    "project/adrs, project/decisions, project/research, project/plan-incubation, or project/verification "
                    "for durable knowledge; next_safe_command=mylittleharness --root <root> intake --dry-run --text-file -"
                ),
                nonroute_markdown,
            )
        )
    code_write_paths = _hook_code_write_paths(inventory, paths, write_command)
    if code_write_paths:
        allowed_scope = [
            _hook_plan_path_display(inventory, path)
            for path in code_write_paths
            if _is_active_plan_target_artifact(inventory, path)
        ]
        out_of_scope = [path for path in code_write_paths if not _is_active_plan_target_artifact(inventory, path)]
        blocked_scope = [_hook_plan_path_display(inventory, path) for path in out_of_scope]
        scope_message = _hook_scope_diagnostic_message(allowed_scope, blocked_scope)
        if len(code_write_paths) > 1:
            findings.append(
                Finding(
                    "info",
                    "hooks-policy-code-write-scope-diagnostic",
                    (
                        "source/test write scope diagnostic: "
                        f"{scope_message}; next_safe_command=mylittleharness --root <root> check"
                    ),
                    blocked_scope[0] if blocked_scope else (allowed_scope[0] if allowed_scope else None),
                )
            )
        if not _has_active_plan(inventory):
            findings.append(
                Finding(
                    "error",
                    "hooks-policy-block-code-write-without-plan",
                    (
                        "tool request appears to write source/test code while no active implementation plan is open; "
                        f"{scope_message}; next_safe_command=mylittleharness --root <root> plan --dry-run --roadmap-item <id>"
                    ),
                    blocked_scope[0] if blocked_scope else (allowed_scope[0] if allowed_scope else None),
                )
            )
        elif out_of_scope:
            findings.append(
                Finding(
                    "error",
                    "hooks-policy-block-code-write-outside-plan-scope",
                    (
                        "blocked source/test write outside the active plan target_artifacts; "
                        f"{scope_message}; next_safe_command=mylittleharness --root <root> roadmap --dry-run "
                        "--action update --item-id <id> --target-artifact <rel-path>"
                    ),
                    blocked_scope[0] if blocked_scope else out_of_scope[0],
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
    if _looks_like_product_root_direct_edit(inventory, paths, write_command):
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
    paths = _hook_tool_intent(data, text).paths
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


def _hook_additional_context(
    agent_packet: object,
    cache_posture: object,
    accelerator_adoption: object,
    connect_readiness: object,
    mlhd: object,
) -> str:
    if not isinstance(agent_packet, dict):
        return ""
    lifecycle = agent_packet.get("lifecycle", {})
    next_legal = agent_packet.get("nextLegalDryRun", {})
    recommended = agent_packet.get("recommendedCommands", [])
    components = cache_posture.get("components", {}) if isinstance(cache_posture, dict) else {}
    adoption = accelerator_adoption if isinstance(accelerator_adoption, dict) else {}
    mcp = adoption.get("mcp", {}) if isinstance(adoption.get("mcp"), dict) else {}
    readiness = connect_readiness if isinstance(connect_readiness, dict) else {}
    docs = readiness.get("docs", {}) if isinstance(readiness.get("docs"), dict) else {}
    writeback = readiness.get("writeback", {}) if isinstance(readiness.get("writeback"), dict) else {}
    mlhd_refresh = str(adoption.get("mlhdRefreshCommand") or "<refused for product-source roots>")
    authority_summary = agent_packet.get("authoritySummary") if isinstance(agent_packet.get("authoritySummary"), str) else ""
    if not authority_summary:
        authority_summary = _authority_cards_context(agent_packet.get("authorityCards") or readiness.get("authorityCards"))
    mlhd_payload = mlhd if isinstance(mlhd, dict) else {}
    context_memory_payload = agent_packet.get("contextMemory") if isinstance(agent_packet.get("contextMemory"), dict) else {}
    return "\n".join(
        [
            "MyLittleHarness first-contact context:",
            f"- lifecycle: plan_status={_payload_value(lifecycle, 'plan_status')}; active_plan={_payload_value(lifecycle, 'active_plan')}; active_phase={_payload_value(lifecycle, 'active_phase')}; phase_status={_payload_value(lifecycle, 'phase_status')}",
            f"- cache: artifacts={_component_status(components, 'artifacts')}; sqlite_index={_component_status(components, 'sqlite_index')}",
            f"- mlhd: control_status={_payload_value(mlhd_payload, 'control_status')}; runtime_cache={_payload_value(mlhd_payload, 'runtime_cache_status')}; dirty_count={_payload_value(mlhd_payload, 'dirty_count')}; last_tick={_payload_value(mlhd_payload, 'last_tick_utc')}; last_failure={_payload_value(mlhd_payload, 'last_failed_refresh_utc')}",
            f"- context memory: status={_payload_value(context_memory_payload, 'status')}; capsule={_payload_value(context_memory_payload, 'capsule_rel_path')}; source_refs={_payload_value(context_memory_payload, 'source_ref_count')}",
            f"- connect readiness: writeback_required={str(writeback.get('requiredWhenPlanStatusActive') is True).lower()}; docs_decision={_payload_value(docs, 'docsDecision')}; docmap={_payload_value(docs, 'docmapStatus')}; next_safe={_payload_value(readiness, 'nextSafeCommand')}",
            f"- authority cards: {authority_summary or 'unavailable'}; dashboard/check/hooks/cache/search output remains non-authority.",
            "- cache command boundary: read-only hook payload displays recovery commands only; hooks do not execute generated-cache refreshes.",
            f"- accelerators: dashboard_packet=available; mcp={_payload_value(mcp, 'status')}; mounted={str(mcp.get('mounted') is True).lower()}; mlhd_refresh={mlhd_refresh}; rg_verification=required",
            "- mcp coverage: read_projection=current posture; read_source=bounded source slices; search=source-verified exact/path/full-text; related_or_bundle=links/fan-in/relationship bundle",
            f"- next legal dry-run: {_payload_value(next_legal, 'command')}",
            f"- recommended first-pass commands: {', '.join(str(command) for command in recommended[:4])}",
            "- exact verification: use `rg` or `mylittleharness.read_source` before source edits or closeout claims.",
            "- boundary: this hook is advisory context only and approves no lifecycle, Git, dispatcher, provider, product-diff, cache, archive, staging, commit, push, or release action.",
        ]
    )


def _authority_cards_context(cards: object) -> str:
    if not isinstance(cards, list):
        return ""
    parts: list[str] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        card_id = str(card.get("id") or "")
        refs = card.get("authorityRefs")
        if card_id and isinstance(refs, list) and refs:
            parts.append(f"{card_id}={'+'.join(str(ref) for ref in refs[:2])}")
    return "; ".join(parts)


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
        data.get("arguments"),
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


def _hook_tool_intent(data: dict[str, object], text: str) -> HookToolIntent:
    command = _hook_input_command(data, text)
    write_target_paths = _hook_write_target_paths(data, command)
    paths = _hook_input_paths(data, text, command=command, write_target_paths=write_target_paths)
    return HookToolIntent(
        command=command,
        paths=paths,
        write_command=_hook_write_command(data, command),
        write_target_paths=write_target_paths,
    )


def _hook_write_command(data: dict[str, object], command: str) -> str:
    if _hook_apply_patch_target_paths(data):
        return f"{command}\n; set-content"
    return command


def _hook_input_paths(
    data: dict[str, object],
    text: str,
    *,
    command: str | None = None,
    write_target_paths: list[str] | None = None,
) -> list[str]:
    apply_patch_targets = _hook_apply_patch_target_paths(data)
    if apply_patch_targets:
        return _dedupe_normalized_hook_paths(apply_patch_targets)
    explicit_write_targets = (
        write_target_paths if write_target_paths is not None else _hook_write_target_paths(data, command or _hook_input_command(data, text))
    )
    if explicit_write_targets:
        return _dedupe_normalized_hook_paths(explicit_write_targets)

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
    return _dedupe_normalized_hook_paths(paths)


def _hook_write_target_paths(data: dict[str, object], command: str) -> list[str]:
    apply_patch_targets = _hook_apply_patch_target_paths(data)
    if apply_patch_targets:
        return _dedupe_normalized_hook_paths(apply_patch_targets)
    targets = _shell_write_target_paths(command)
    targets.extend(_workdir_relative_write_targets(data, targets))
    return _dedupe_normalized_hook_paths(targets)


def _shell_write_target_paths(command: str, *, depth: int = 0) -> list[str]:
    if depth > 2:
        return []
    tokens = _shell_tokens(command)
    targets: list[str] = []
    targets.extend(_git_output_target_paths(tokens))
    targets.extend(_runtime_code_write_target_paths(command))
    expect_command = True
    index = 0
    while index < len(tokens):
        raw = str(tokens[index] or "").strip()
        clean = _clean_token(raw)
        inline_redirect_target = _inline_redirection_target(raw)
        if inline_redirect_target:
            targets.append(inline_redirect_target)
            index += 1
            continue
        if _is_shell_redirection_token(raw, clean):
            if index + 1 < len(tokens):
                target = _path_argument_value(tokens[index + 1])
                if target:
                    targets.append(target)
            index += 2
            continue
        if not clean:
            if _is_shell_command_separator(raw, clean):
                expect_command = True
            index += 1
            continue
        if expect_command and clean in WRITING_COMMAND_NAMES:
            command_targets, next_index = _write_command_target_paths(tokens, index)
            targets.extend(command_targets)
            index = next_index
            expect_command = False
            continue
        if _is_shell_command_separator(raw, clean):
            expect_command = True
            index += 1
            continue
        expect_command = False
        if raw.endswith(";"):
            expect_command = True
        index += 1
    for nested in _nested_shell_commands_from_tokens(tokens):
        targets.extend(_shell_write_target_paths(nested, depth=depth + 1))
    return targets


def _workdir_relative_write_targets(data: dict[str, object], targets: list[str]) -> list[str]:
    workdir = _hook_workdir_value(data)
    if not workdir:
        return []
    workdir_rel = _path_argument_value(workdir) or str(workdir or "").strip()
    if not workdir_rel:
        return []
    normalized_workdir = _normalize_hook_path(workdir_rel).rstrip("/")
    if not normalized_workdir or re.match(r"^[a-z]:/", normalized_workdir):
        return []
    resolved: list[str] = []
    for target in targets:
        normalized = _normalize_hook_path(target)
        if (
            normalized
            and not re.match(r"^[a-z]:/", normalized)
            and not normalized.startswith(("../", "./", "project/", "src/", "tests/", "docs/", ".mylittleharness/"))
        ):
            resolved.append(f"{normalized_workdir}/{normalized}")
    return resolved


def _hook_workdir_value(data: dict[str, object]) -> str:
    for key in ("cwd", "workdir", "working_directory", "workingDirectory"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for value in data.values():
        if isinstance(value, dict):
            nested = _hook_workdir_value(value)
            if nested:
                return nested
    return ""


def _write_command_target_paths(tokens: list[str], command_index: int) -> tuple[list[str], int]:
    command = _clean_token(tokens[command_index])
    max_positional = 2 if command in PAIRED_TARGET_WRITING_COMMAND_NAMES else 1
    single_target = command in SINGLE_TARGET_WRITING_COMMAND_NAMES
    targets: list[str] = []
    positional_count = 0
    index = command_index + 1
    while index < len(tokens):
        raw = str(tokens[index] or "").strip()
        clean = _clean_token(raw)
        if _is_shell_command_separator(raw, clean):
            break
        if _is_shell_redirection_token(raw, clean):
            break
        option_value = _write_path_option_value(raw, clean)
        if option_value:
            targets.append(option_value)
            if single_target:
                return targets, index + 1
            index += 1
            continue
        if clean in WRITING_COMMAND_PATH_OPTIONS and index + 1 < len(tokens):
            target = _path_argument_value(tokens[index + 1])
            if target:
                targets.append(target)
            if single_target:
                return targets, index + 2
            index += 2
            continue
        if clean in WRITING_COMMAND_NON_TARGET_OPTIONS_WITH_VALUES:
            index += 2
            continue
        if clean.startswith("-"):
            index += 1
            continue
        target = _path_argument_value(raw)
        if target:
            targets.append(target)
            positional_count += 1
            if single_target or positional_count >= max_positional:
                return targets, index + 1
        index += 1
    return targets, index


def _write_path_option_value(raw: str, clean: str) -> str:
    for option in WRITING_COMMAND_PATH_OPTIONS:
        for separator in ("=", ":"):
            prefix = f"{option}{separator}"
            if clean.startswith(prefix):
                value = raw.split(separator, 1)[1]
                return _path_argument_value(value)
    return ""


def _inline_redirection_target(raw: str) -> str:
    stripped = str(raw or "").strip(" \t\r\n\"'`")
    match = re.match(r"^(?:\d+|\*)?(>>?)(.+)$", stripped)
    if match:
        return _path_argument_value(match.group(2))
    return ""


def _path_argument_value(token: str) -> str:
    value = str(token or "").strip(" \t\r\n\"'`")
    if not value:
        return ""
    normalized = value.replace("\\", "/")
    if re.match(r"^[A-Za-z]:[\\/]", value) or normalized.startswith(
        ("../", "./", "project/", "src/", "tests/", "docs/", ".mylittleharness/")
    ):
        return value
    if re.match(r"^[A-Za-z0-9_.-]+\.(?:md|py|json|toml|ya?ml|txt)$", normalized):
        return value
    extracted = _extract_paths(value)
    return extracted[0] if extracted else ""


def _git_output_target_paths(tokens: list[str]) -> list[str]:
    targets: list[str] = []
    for index, token in enumerate(tokens):
        clean = _clean_token(token)
        if clean == "--output" and index + 1 < len(tokens):
            target = _path_argument_value(tokens[index + 1])
            if target:
                targets.append(target)
        elif clean.startswith("--output="):
            target = _path_argument_value(str(token).split("=", 1)[1])
            if target:
                targets.append(target)
    return targets


def _runtime_code_write_target_paths(command: str) -> list[str]:
    if not _runtime_code_payload_looks_like_write(command):
        return []
    return _extract_paths(command)


def _runtime_code_payload_looks_like_write(command: str) -> bool:
    lowered = str(command or "").casefold()
    if not re.search(r"\b(?:python|python\.exe|py|py\.exe|node|node\.exe)\b", lowered):
        return False
    if not any(marker in lowered for marker in ("write_text(", "write_bytes(", "open(", "writefilesync", "appendfilesync", "createwritestream")):
        return False
    if "open(" in lowered and not re.search(r"open\([^)]*,\s*['\"][wa+x]", lowered):
        return False
    return bool(_extract_paths(command))


def _nested_shell_commands_from_tokens(tokens: list[str]) -> list[str]:
    nested: list[str] = []
    index = 0
    while index < len(tokens):
        raw = str(tokens[index] or "")
        clean = _clean_token(raw)
        name = Path(clean).name
        if name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            payload, next_index = _powershell_payload(tokens, index + 1)
            if payload:
                nested.append(payload)
            index = next_index
            continue
        if name in {"cmd", "cmd.exe"}:
            payload, next_index = _shell_payload_after_option(tokens, index + 1, {"/c", "/k"})
            if payload:
                nested.append(payload)
            index = next_index
            continue
        if name in {"sh", "bash", "zsh", "fish"}:
            payload, next_index = _shell_payload_after_option(tokens, index + 1, {"-c"})
            if payload:
                nested.append(payload)
            index = next_index
            continue
        if clean == "eval" and index + 1 < len(tokens):
            nested.append(_strip_shell_payload_token(" ".join(tokens[index + 1 :])))
            break
        index += 1
    return nested


def _powershell_payload(tokens: list[str], start: int) -> tuple[str, int]:
    index = start
    while index < len(tokens):
        clean = _clean_token(tokens[index])
        if clean in {"-encodedcommand", "-enc", "-e"}:
            return "<MLH_ENCODED_COMMAND>", index + 2
        if clean in {"-command", "-c"} and index + 1 < len(tokens):
            return _strip_shell_payload_token(tokens[index + 1]), index + 2
        index += 1
    return "", index


def _shell_payload_after_option(tokens: list[str], start: int, options: set[str]) -> tuple[str, int]:
    index = start
    while index < len(tokens):
        clean = _clean_token(tokens[index])
        if clean in options and index + 1 < len(tokens):
            return _strip_shell_payload_token(" ".join(tokens[index + 1 :])), len(tokens)
        index += 1
    return "", index


def _strip_shell_payload_token(value: object) -> str:
    return str(value or "").strip(" \t\r\n\"'")


def _dedupe_normalized_hook_paths(paths: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for path in paths:
        clean = _normalize_hook_path(path)
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)
    return normalized


def _hook_apply_patch_target_paths(data: dict[str, object]) -> list[str]:
    patch_text = _hook_apply_patch_text(data)
    if not patch_text:
        return []
    targets: list[str] = []
    for line in patch_text.splitlines():
        for marker in ("*** Update File: ", "*** Add File: ", "*** Delete File: ", "*** Move to: "):
            if line.startswith(marker):
                target = line[len(marker) :].strip()
                if target:
                    targets.append(target)
    return targets


def _is_existing_route_markdown_patch_request(inventory: Inventory, data: dict[str, object]) -> bool:
    operations = _hook_apply_patch_target_operations(data)
    if not operations:
        return False
    if any(operation != "update" for operation, _path in operations):
        return False
    paths = [path for _operation, path in operations]
    return bool(paths) and all(_is_editable_route_patch_path(inventory, path) for path in paths)


def _is_active_plan_spec_doc_patch_request(inventory: Inventory, data: dict[str, object]) -> bool:
    operations = _hook_apply_patch_target_operations(data)
    if not operations:
        return False
    if any(operation != "update" for operation, _path in operations):
        return False
    paths = [path for _operation, path in operations]
    return bool(paths) and all(_is_active_plan_spec_doc_patch_path(inventory, path) for path in paths)


def _hook_apply_patch_target_operations(data: dict[str, object]) -> list[tuple[str, str]]:
    patch_text = _hook_apply_patch_text(data)
    if not patch_text:
        return []
    operations: list[tuple[str, str]] = []
    markers = (
        ("update", "*** Update File: "),
        ("add", "*** Add File: "),
        ("delete", "*** Delete File: "),
        ("move", "*** Move to: "),
    )
    for line in patch_text.splitlines():
        for operation, marker in markers:
            if line.startswith(marker):
                target = line[len(marker) :].strip()
                if target:
                    operations.append((operation, target))
    return operations


def _is_editable_route_patch_path(inventory: Inventory, path: str) -> bool:
    rel = _hook_route_rel_path(inventory, path)
    if not rel or _is_lifecycle_authority_path(rel):
        return False
    if classify_memory_route(rel).route_id not in EDITABLE_ROUTE_PATCH_IDS:
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        frontmatter = parse_frontmatter(route_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    return frontmatter.has_frontmatter and not frontmatter.errors


def _is_active_plan_spec_doc_patch_path(inventory: Inventory, path: str) -> bool:
    rel = _hook_route_rel_path(inventory, path)
    if not rel or _is_lifecycle_authority_path(rel):
        return False
    normalized = _normalize_hook_path(rel).casefold()
    if not any(normalized.startswith(prefix) for prefix in ACTIVE_PLAN_SPEC_DOC_PREFIXES):
        return False
    if not _active_phase_write_scope_allows_path(inventory, normalized):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        frontmatter = parse_frontmatter(route_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    return frontmatter.has_frontmatter and not frontmatter.errors


def _hook_route_rel_path(inventory: Inventory, path: str) -> str:
    normalized = _normalize_hook_path(path)
    candidate = _resolve_hook_path_from_root(inventory, path)
    if candidate is not None:
        try:
            return candidate.relative_to(inventory.root.resolve()).as_posix()
        except (OSError, RuntimeError, ValueError):
            return "" if _path_escapes_root(path) else normalized
    try:
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            return candidate.resolve().relative_to(inventory.root.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return ""
    return normalized


def _hook_route_file_path(inventory: Inventory, path: str) -> Path | None:
    rel = _hook_route_rel_path(inventory, path)
    if not rel:
        return None
    try:
        route_path = (inventory.root / rel).resolve()
        route_path.relative_to(inventory.root.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return route_path


def _hook_apply_patch_text(data: dict[str, object]) -> str:
    candidates = (
        data.get("input"),
        data.get("patch"),
        data.get("tool_input"),
        data.get("parameters"),
        data.get("arguments"),
        data.get("command"),
        data.get("shell_command"),
        data.get("cmd"),
        data.get("raw"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and "*** Begin Patch" in candidate:
            return candidate
        if isinstance(candidate, dict):
            nested = _hook_apply_patch_text(candidate)
            if nested:
                return nested
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, str) and "*** Begin Patch" in item:
                    return item
                if isinstance(item, dict):
                    nested = _hook_apply_patch_text(item)
                    if nested:
                        return nested
    return ""


def _extract_paths(text: str) -> list[str]:
    matches: list[str] = []
    for match in PATH_RE.finditer(text or ""):
        value = match.group(0).strip(" \t\r\n\"'`") or (match.group(1) or "").strip(" \t\r\n\"'`")
        if value:
            matches.append(value)
    return matches


def _clean_hook_path_token(path: str) -> str:
    return str(path or "").strip().strip(" \t\r\n\"'`([{").rstrip(".,;:)]}")


def _normalize_hook_path(path: str) -> str:
    rel = _clean_hook_path_token(path).replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def _resolve_hook_path_from_root(inventory: Inventory, path: str) -> Path | None:
    raw = _clean_hook_path_token(path)
    if not raw:
        return None
    try:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = inventory.root / candidate
        return candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _path_escapes_root(path: str) -> bool:
    return _normalize_hook_path(path).startswith("../")


def _path_policy_findings(
    inventory: Inventory,
    paths: list[str],
    *,
    warn_only: bool = False,
    allow_read_only_source_paths: bool = False,
    allow_read_only_roadmap_path: bool = False,
    allow_mlh_owner_route_paths: bool = False,
    allow_existing_route_patch: bool = False,
    allow_active_plan_spec_doc_patch: bool = False,
) -> list[Finding]:
    findings: list[Finding] = []
    severity = "warn" if warn_only else "error"
    for rel in paths:
        if _is_generated_cache_path(rel):
            recovery_command = _generated_cache_recovery_command(inventory)
            findings.append(
                Finding(
                    severity,
                    "hooks-policy-block-generated-cache-path",
                    (
                        "tool request touches generated projection/cache paths; cache remains disposable and should be "
                        f"refreshed through projection rails; next_safe_command={recovery_command}"
                    ),
                    rel,
                )
            )
        if (allow_read_only_source_paths or allow_mlh_owner_route_paths) and _is_lifecycle_route_path(rel):
            continue
        if allow_read_only_roadmap_path and _is_roadmap_path(rel):
            continue
        if allow_existing_route_patch and _is_editable_route_patch_path(inventory, rel):
            continue
        if allow_active_plan_spec_doc_patch and _is_active_plan_spec_doc_patch_path(inventory, rel):
            continue
        if _is_lifecycle_authority_path(rel):
            findings.append(
                Finding(
                    severity,
                    "hooks-policy-block-lifecycle-authority-path",
                    (
                        "tool request touches lifecycle authority paths; use explicit MLH dry-run/apply routes "
                        f"and record docs_decision/verification as required; next_safe_command={_hook_route_next_safe_command(inventory, rel)}"
                    ),
                    rel,
                )
            )
        elif _is_lifecycle_markdown_path(rel):
            findings.append(
                Finding(
                    severity,
                    "hooks-policy-block-lifecycle-markdown-path",
                    (
                        "tool request touches lifecycle Markdown routes; required frontmatter and owning route evidence "
                        f"must stay intact; next_safe_command={_hook_route_next_safe_command(inventory, rel)}"
                    ),
                    rel,
                )
            )
        if _is_under_configured_product_root(inventory, rel):
            if allow_read_only_source_paths or allow_mlh_owner_route_paths or _is_active_plan_product_artifact(inventory, rel):
                continue
            findings.append(
                Finding(
                    severity,
                    "hooks-policy-block-product-root-path",
                    (
                        "tool request names the configured product source root from an operating-root context; "
                        "keep product edits deliberate and bounded; next_safe_command=mylittleharness --root <root> check"
                    ),
                    rel,
                )
            )
    return findings


def _first_mlh_owner_route_evidence_path(inventory: Inventory, paths: list[str]) -> str:
    for rel in paths:
        if (
            _is_lifecycle_route_path(rel)
            or _is_under_configured_product_root(inventory, rel)
            or _is_code_path(rel)
        ):
            return rel
    return ""


def _is_bounded_mlh_read_tool_request(data: dict[str, object]) -> bool:
    candidates = (data.get("toolName"), data.get("tool_name"), data.get("tool"))
    for candidate in candidates:
        lowered = str(candidate or "").strip().casefold()
        if lowered.endswith(BOUNDED_MLH_READ_TOOL_SUFFIXES):
            return True
    return False


def _is_mlh_owner_route_review_command(command: str) -> bool:
    lowered = command.casefold()
    padded = f" {lowered} "
    subcommand = _mlh_cli_subcommand(lowered)
    if subcommand == "suggest":
        return (
            not _looks_like_write_command(command)
            and (" --intent " in padded or " --intent=" in padded or " --help" in padded or " -h" in padded)
        )
    return (
        subcommand in MLH_OWNER_ROUTE_REVIEW_COMMANDS
        and not _looks_like_write_command(command)
        and (" --dry-run" in padded or " --apply" in padded or " --help" in padded or " -h" in padded)
    )


def _is_research_import_related_prompt_provenance_command(command: str) -> bool:
    related_prompt = _research_import_related_prompt_path(command)
    if not related_prompt:
        return False
    lowered = command.casefold()
    padded = f" {lowered} "
    return (
        _mlh_cli_subcommand(lowered) == "research-import"
        and (" --dry-run" in padded or " --apply" in padded)
        and not _looks_like_write_command(command)
    )


def _research_import_related_prompt_path(command: str) -> str:
    if _mlh_cli_subcommand(command.casefold()) != "research-import":
        return ""
    tokens = _shell_tokens(command)
    for index, token in enumerate(tokens):
        clean = _clean_token(token)
        if clean == "--related-prompt" and index + 1 < len(tokens):
            return _clean_token(tokens[index + 1])
        if clean.startswith("--related-prompt="):
            return clean.partition("=")[2].strip()
    return ""


def _is_read_only_source_discovery_command(command: str) -> bool:
    if _looks_like_write_command(command):
        return False
    tokens = _shell_tokens(command)
    for index, token in enumerate(tokens):
        clean = _clean_token(token)
        if not clean or clean.startswith("-"):
            continue
        if clean not in READ_ONLY_SOURCE_DISCOVERY_COMMANDS:
            continue
        return _has_read_only_discovery_prefix(tokens[:index])
    return False


def _has_read_only_discovery_prefix(tokens: list[str]) -> bool:
    for token in tokens:
        clean = _clean_token(token)
        if not clean:
            continue
        if clean in READ_ONLY_SOURCE_DISCOVERY_PREFIX_TOKENS:
            continue
        if clean.startswith("$") or _is_hook_pathish_token(clean):
            continue
        return False
    return True


def _is_hook_pathish_token(token: str) -> bool:
    clean = _normalize_hook_path(token).casefold()
    if re.match(r"^[a-z]:/", clean):
        return True
    return clean.startswith(("project/", "src/", "tests/", "docs/", ".mylittleharness/"))


def _is_read_only_git_inspection_command(command: str) -> bool:
    if _looks_like_write_command(command):
        return False
    return _git_subcommand(command) in READ_ONLY_GIT_INSPECTION_COMMANDS


def _git_subcommand(command: str) -> str:
    tokens = [_clean_token(token) for token in _shell_tokens(command)]
    tokens = [token for token in tokens if token]
    for index, token in enumerate(tokens):
        if not _is_git_executable_token(token):
            continue
        return _git_subcommand_after_options(tokens, index + 1)
    return ""


def _git_subcommand_after_options(tokens: list[str], start: int) -> str:
    index = start
    while index < len(tokens):
        token = tokens[index]
        if not token:
            index += 1
            continue
        if token == "-c":
            index += 2
            continue
        if token in GIT_OPTIONS_WITH_VALUES:
            index += 2
            continue
        if any(token.startswith(option + "=") for option in GIT_OPTIONS_WITH_VALUES if option.startswith("--")):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return ""


def _is_git_executable_token(token: str) -> bool:
    clean = _clean_token(token)
    return clean in {"git", "git.exe"} or Path(clean).name in {"git", "git.exe"}


def _is_read_only_roadmap_direct_read_command(command: str, paths: list[str]) -> bool:
    if _looks_like_write_command(command):
        return False
    tokens = _shell_tokens(command)
    command_token = ""
    for token in tokens:
        clean = _clean_token(token)
        if not clean or clean.startswith("-"):
            continue
        command_token = clean
        break
    if command_token != "get-content":
        return False
    return bool(paths) and all(_is_roadmap_path(path) for path in paths)


def _active_plan_roadmap_policy_relevant(inventory: Inventory, command: str, paths: list[str]) -> bool:
    if not _has_active_plan(inventory):
        return False
    lowered = command.casefold()
    subcommand = _mlh_cli_subcommand(lowered)
    if subcommand in {"roadmap", "meta-feedback", "incubate", "plan", "writeback", "transition"}:
        return True
    if any(_is_roadmap_path(path) for path in paths):
        return True
    return "roadmap" in lowered or "active plan" in lowered or "active-plan" in lowered


def _looks_like_shortcut_prompt(text: str) -> bool:
    lowered = (text or "").casefold()
    shortcut_terms = ("without plan", "skip check", "skip dry-run", "no frontmatter", "archive anyway", "mark done", "shortcut", "шорткат", "без плана", "без проверки")
    return any(term in lowered for term in shortcut_terms)


def _looks_like_generated_cache_write(paths: list[str], command: str) -> bool:
    return any(_is_generated_cache_path(path) for path in paths) and _looks_like_write_command(command)


def _looks_like_lifecycle_markdown_write(paths: list[str], command: str) -> bool:
    return any(_is_lifecycle_route_path(path) for path in paths) and _looks_like_write_command(command) and "mylittleharness" not in command.casefold()


def _nonroute_project_markdown_write_path(paths: list[str], command: str) -> str:
    if not _looks_like_write_command(command):
        return ""
    for path in paths:
        if _is_nonroute_project_markdown_path(path):
            return path
    return ""


def _looks_like_product_root_direct_edit(inventory: Inventory, paths: list[str], command: str) -> bool:
    if not _looks_like_write_command(command):
        return False
    return any(_is_under_configured_product_root(inventory, path) and not _is_active_plan_product_artifact(inventory, path) for path in paths)


def _hook_code_write_paths(inventory: Inventory, paths: list[str], command: str) -> list[str]:
    if not _looks_like_write_command(command):
        return []
    code_paths: list[str] = []
    for path in paths:
        product_rel = _product_relative_path(inventory, path)
        if _is_code_path(path) or (product_rel and _is_code_path(product_rel)):
            code_paths.append(path)
    return code_paths


def _hook_plan_path_display(inventory: Inventory, path: str) -> str:
    product_rel = _product_relative_path(inventory, path)
    if product_rel:
        return _normalize_hook_path(product_rel)
    normalized = _normalize_plan_artifact_candidate(inventory, path)
    return normalized or _normalize_hook_path(path)


def _hook_scope_diagnostic_message(allowed_scope: list[str], blocked_scope: list[str]) -> str:
    allowed = ", ".join(_dedupe_nonempty(allowed_scope)) or "none"
    blocked = ", ".join(_dedupe_nonempty(blocked_scope)) or "none"
    return f"allowed_paths={allowed}; blocked_paths={blocked}"


def _hook_route_next_safe_command(inventory: Inventory, path: str) -> str:
    rel = _hook_route_rel_path(inventory, path) or _normalize_hook_path(path)
    route_id = classify_memory_route(rel).route_id
    topic = _route_topic_from_path(rel)
    if _is_roadmap_path(rel) or route_id == "roadmap":
        return mlh_command("roadmap", "--dry-run", "--action", "update", "--item-id", "<id>")
    if route_id == "state":
        return mlh_command("writeback", "--dry-run", "--phase-status", "<phase-status>", "--docs-decision", "<docs-decision>")
    if route_id == "active-plan":
        return mlh_command("plan", "--dry-run", "--roadmap-item", "<id>")
    if route_id == "incubation":
        return mlh_command("incubate", "--dry-run", "--topic", safe_double_quoted(topic, placeholder="<topic>"), "--note-file", "-")
    if route_id == "research":
        return mlh_command("research-import", "--dry-run", "--title", '"<title>"', "--topic", safe_double_quoted(topic, placeholder="<topic>"), "--text-file", "-")
    if route_id in {"adrs", "decisions", "product-docs"}:
        return mlh_command("intake", "--dry-run", "--text-file", "-", "--target", rel)
    if route_id == "verification":
        return mlh_command("intake", "--dry-run", "--text-file", "-", "--target", rel)
    if route_id == "stable-specs":
        return mlh_command("check", "--focus", "route-references")
    if route_id == "archive":
        return mlh_command("memory-hygiene", "--dry-run", "--scan")
    return mlh_command("suggest", "--intent", safe_double_quoted(f"route owner for {safe_intent_text(rel or path, placeholder='<path>')}"))


def _generated_cache_recovery_command(inventory: Inventory) -> str:
    if inventory.root_kind == PRODUCT_SOURCE_FIXTURE:
        return "mylittleharness --root <root> projection --warm-cache --target all"
    return "mylittleharness --root <root> mlhd run-once --apply"


def _route_topic_from_path(path: str) -> str:
    stem = Path(_normalize_hook_path(path)).stem.strip()
    return stem or "<topic>"


def _dedupe_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _looks_like_write_command(command: str) -> bool:
    if _looks_like_opaque_shell_payload(command) or _runtime_code_payload_looks_like_write(command):
        return True
    expect_command = True
    tokens = _shell_tokens(command)
    if _git_output_target_paths(tokens):
        return True
    for nested in _nested_shell_commands_from_tokens(tokens):
        if nested == "<MLH_ENCODED_COMMAND>" or _looks_like_write_command(nested):
            return True
    for token in tokens:
        raw = str(token or "").strip()
        clean = _clean_token(raw)
        if _is_shell_redirection_token(raw, clean):
            return True
        if not clean:
            if _is_shell_command_separator(raw, clean):
                expect_command = True
            continue
        if expect_command and clean in WRITING_COMMAND_NAMES:
            return True
        if _is_shell_command_separator(raw, clean):
            expect_command = True
            continue
        expect_command = False
        if raw.endswith(";"):
            expect_command = True
    return False


def _is_shell_redirection_token(raw: str, clean: str) -> bool:
    stripped = raw.strip(" \t\r\n\"'`")
    return (
        clean in {">", ">>"}
        or stripped in {">", ">>"}
        or bool(re.match(r"^(?:\d+|\*)?>>?", stripped))
    )


def _is_shell_command_separator(raw: str, clean: str) -> bool:
    stripped = raw.strip(" \t\r\n\"'`")
    return clean in SHELL_COMMAND_SEPARATORS or stripped in SHELL_COMMAND_SEPARATORS or stripped.endswith(";")


def _looks_like_git_stage_or_commit(lowered_command: str) -> bool:
    padded = f" {lowered_command} "
    return any(token in padded for token in GIT_WRITE_COMMANDS) or _git_subcommand(lowered_command) in GIT_MUTATION_COMMANDS


def _looks_like_opaque_shell_payload(command: str) -> bool:
    tokens = _shell_tokens(command)
    return any(nested == "<MLH_ENCODED_COMMAND>" for nested in _nested_shell_commands_from_tokens(tokens))


def _looks_like_next_plan_apply(lowered_command: str) -> bool:
    padded = f" {lowered_command} "
    if " --update-active" in padded:
        return False
    return _mlh_cli_subcommand(lowered_command) == "plan" and " --apply" in padded


def _looks_like_unsafe_mlh_mutation(lowered_command: str) -> bool:
    subcommand = _mlh_cli_subcommand(lowered_command)
    if not subcommand:
        return False
    padded = f" {lowered_command} "
    if subcommand == "adapter":
        return " --install-client-config " in padded
    return subcommand in {
        "repair",
        "plan",
        "writeback",
        "transition",
        "roadmap",
        "meta-feedback",
        "projection",
        "memory-hygiene",
        "hooks",
    }


def _mlh_cli_subcommand(command: str) -> str:
    tokens = _shell_tokens(command)
    for index, token in enumerate(tokens):
        if _is_mlh_executable_token(token):
            return _next_mlh_subcommand(tokens, index + 1)
        if _is_python_executable_token(token) and index + 2 < len(tokens):
            if _clean_token(tokens[index + 1]) == "-m" and _clean_token(tokens[index + 2]) == "my" + "littleharness":
                return _next_mlh_subcommand(tokens, index + 3)
    return ""


def _shell_tokens(command: str) -> list[str]:
    command = _command_without_shell_literal_payloads(command or "")
    try:
        return shlex.split(command or "", posix=False)
    except ValueError:
        return str(command or "").split()


def _command_without_shell_literal_payloads(command: str) -> str:
    text = POWERSHELL_HERE_STRING_RE.sub(" <MLH_STDIN_PAYLOAD> ", command or "")
    return _command_without_posix_heredoc_payloads(text)


def _command_without_posix_heredoc_payloads(command: str) -> str:
    lines = str(command or "").splitlines(keepends=True)
    if not lines:
        return ""
    result: list[str] = []
    pending_delimiter = ""
    for line in lines:
        if pending_delimiter:
            if line.strip() == pending_delimiter:
                pending_delimiter = ""
            continue
        result.append(line)
        match = POSIX_HEREDOC_START_RE.search(line)
        if match:
            pending_delimiter = match.group(1)
    return "".join(result)


def _next_mlh_subcommand(tokens: list[str], start: int) -> str:
    options_with_values = {"--root", "--config", "--config-path"}
    index = start
    while index < len(tokens):
        token = _clean_token(tokens[index])
        if not token:
            index += 1
            continue
        if token in options_with_values:
            index += 2
            continue
        if token.startswith("--root=") or token.startswith("--config=") or token.startswith("--config-path="):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return ""


def _is_mlh_executable_token(token: str) -> bool:
    clean = _clean_token(token)
    if clean in {"my" + "littleharness", "my" + "littleharness.exe"}:
        return True
    return Path(clean).name in {"my" + "littleharness", "my" + "littleharness.exe"}


def _is_python_executable_token(token: str) -> bool:
    clean = _clean_token(token)
    name = Path(clean).name
    return name in {"python", "python.exe", "py", "py.exe"}


def _clean_token(token: str) -> str:
    return str(token or "").strip(" \t\r\n\"'`{}[](),;").casefold()


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
        return " --doctor" in padded or " hooks doctor " in padded or " --run " in padded
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


def _is_lifecycle_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold().rstrip("/")
    if _is_lifecycle_authority_path(rel) or _is_lifecycle_markdown_path(rel):
        return True
    for prefix in LIFECYCLE_MARKDOWN_PREFIXES:
        route = prefix.rstrip("/")
        if prefix.endswith("/") and (rel == route or rel.startswith(prefix)):
            return True
        if not prefix.endswith("/") and (rel == route or rel.startswith(route + "/")):
            return True
    return False


def _is_roadmap_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel == "project/" + "roadmap.md"


def _is_nonroute_project_markdown_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    if not rel.startswith("project/") or not rel.endswith(".md"):
        return False
    if any(rel.startswith(prefix) for prefix in NONROUTE_PROJECT_MARKDOWN_EXEMPT_PREFIXES):
        return False
    return classify_memory_route(rel).route_id == "unclassified"


def _is_under_configured_product_root(inventory: Inventory, path: str) -> bool:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    product_root = str(state.get("product_source_root") or "").strip()
    if not product_root:
        return False
    try:
        candidate = _resolve_hook_path_from_root(inventory, path)
        if candidate is None:
            return False
        candidate.relative_to(Path(product_root).expanduser().resolve())
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


def _active_phase_write_scope_allows_path(inventory: Inventory, rel: str) -> bool:
    scope = _active_phase_write_scope_paths(inventory)
    return bool(scope) and _normalize_hook_path(rel).casefold() in scope


def _active_phase_write_scope_paths(inventory: Inventory) -> set[str]:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return set()
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    active_phase = str(state_data.get("active_phase") or plan.frontmatter.data.get("active_phase") or "").strip()
    block = _active_phase_block_text(plan.content, active_phase)
    if not block:
        return set()
    paths: set[str] = set()
    for line in block.splitlines():
        match = re.match(r"^\s*[-*]\s*write_scope\s*:\s*(.+?)\s*$", line, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1)
        extracted = re.findall(r"`([^`]+)`", value)
        for item in extracted or re.split(r"\s*,\s*", value):
            normalized = _normalize_hook_path(item.strip().strip("`'\"")).casefold()
            if normalized and normalized != "<none>":
                paths.add(normalized)
    return paths


def _active_phase_block_text(text: str, active_phase: str) -> str:
    if not active_phase:
        return ""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^\s*###\s+(.+?)\s*$", line)
        if not match:
            continue
        next_index = len(lines)
        for candidate in range(index + 1, len(lines)):
            if re.match(r"^\s*###\s+", lines[candidate]):
                next_index = candidate
                break
        block = "\n".join(lines[index:next_index])
        title = _normalize_phase_identifier(match.group(1))
        if title == _normalize_phase_identifier(active_phase) or re.search(
            rf"^\s*[-*]\s*id\s*:\s*`?{re.escape(active_phase)}`?\s*$",
            block,
            flags=re.MULTILINE,
        ):
            return block
    return ""


def _normalize_phase_identifier(value: str) -> str:
    return _normalize_hook_path(value.strip().strip("`")).casefold().replace(" ", "-")


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
        candidate = _resolve_hook_path_from_root(inventory, path)
        if candidate is None:
            return ""
        return candidate.relative_to(Path(product_root).expanduser().resolve()).as_posix()
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


def _hook_policy_identity() -> dict[str, str]:
    source = Path(__file__).resolve()
    return {
        "schema": HOOK_POLICY_SCHEMA,
        "source": source.as_posix(),
        "sourceHash": _hook_policy_source_hash(source),
        "importRoot": _module_import_root().as_posix(),
    }


def _hook_policy_source_hash(source: Path) -> str:
    try:
        return hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    except OSError:
        return "unavailable"


def _hook_adapter_review_command(request: CodexHookAdapterRequest, mode: str) -> str:
    parts = ["hooks", "adapter", "--client", request.client, mode, "--scope", request.scope]
    if request.config_path:
        parts.extend(["--config-path", request.config_path])
    return mlh_command(*parts)


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
