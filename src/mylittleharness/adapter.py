from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from . import __version__
from .approval_packets import APPROVAL_PACKET_SCHEMA, APPROVAL_PACKETS_DIR_REL
from .inventory import Inventory, RootLoadError, load_inventory
from .models import Finding
from .projection import Projection, build_projection
from .projection_artifacts import inspect_projection_artifacts, projection_cache_posture_payload
from .projection_index import inspect_projection_index, source_verified_full_text_results
from .root_boundary import PRODUCT_SOURCE_FIXTURE, source_path_boundary_violation


MCP_READ_PROJECTION_TARGET = "mcp-read-projection"
APPROVAL_RELAY_TARGET = "approval-relay"
APPROVAL_RELAY_PREVIEW_SCHEMA = "mylittleharness.approval-relay-preview.v1"
MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_READ_PROJECTION_TOOL = "mylittleharness.read_projection"
MCP_READ_SOURCE_TOOL = "mylittleharness.read_source"
MCP_SEARCH_TOOL = "mylittleharness.search"
MCP_RELATED_OR_BUNDLE_TOOL = "mylittleharness.related_or_bundle"
MCP_READ_PROJECTION_SERVER_NAME = "mylittleharness"
CODEX_CONFIG_DISPLAY_PATH = "%USERPROFILE%\\.codex\\config.toml"
CODEX_MCP_ADOPTION_SCHEMA = "mylittleharness.codex-mcp-adoption.v1"
CODEX_MCP_BLOCK_START = "# BEGIN MyLittleHarness mcp-read-projection"
CODEX_MCP_BLOCK_END = "# END MyLittleHarness mcp-read-projection"
MCP_TOOL_NAMES = (
    MCP_READ_PROJECTION_TOOL,
    MCP_READ_SOURCE_TOOL,
    MCP_SEARCH_TOOL,
    MCP_RELATED_OR_BUNDLE_TOOL,
)
MCP_SOURCE_READ_DEFAULT_LIMIT = 80
MCP_SOURCE_READ_MAX_LIMIT = 200
MCP_SOURCE_START_MAX = 1_000_000
MCP_SEARCH_DEFAULT_LIMIT = 10
MCP_SEARCH_MAX_LIMIT = 50
MCP_RELATED_DEFAULT_LIMIT = 20
MCP_RELATED_MAX_LIMIT = 100
InventoryLoader = Callable[[Path | str], Inventory]


def approval_relay_sections(
    inventory: Inventory,
    approval_packet_refs: tuple[str, ...],
    *,
    relay_channel: str = "manual",
    relay_recipient: str = "",
) -> list[tuple[str, list[Finding]]]:
    packets, packet_findings = _approval_relay_packets(inventory, approval_packet_refs)
    payload = _approval_relay_payload(
        inventory,
        packets,
        relay_channel=relay_channel,
        relay_recipient=relay_recipient,
    )
    return [
        ("Adapter", _approval_relay_adapter_findings(inventory)),
        ("Approval Packets", packet_findings),
        ("Relay Payload", _approval_relay_payload_findings(payload, packets)),
        ("Boundary", _approval_relay_boundary_findings()),
    ]


def approval_relay_client_config(inventory: Inventory) -> dict[str, object]:
    return {
        "status": "available",
        "adapter": {
            "id": APPROVAL_RELAY_TARGET,
            "group": "Relay",
            "role": "approval-packet transport preview",
            "owner": "MyLittleHarness adapter boundary",
        },
        "command": [
            "mylittleharness",
            "--root",
            str(inventory.root),
            "adapter",
            "--inspect",
            "--target",
            APPROVAL_RELAY_TARGET,
            "--approval-packet-ref",
            "<project/verification/approval-packets/id.json>",
        ],
        "inputs": {
            "approvalPacketRefs": "root-relative repo-visible approval packet JSON paths",
            "relayChannel": "label only; no delivery transport is opened",
            "relayRecipient": "label only; no credentials or secret state are stored",
        },
        "boundary": {
            "writesFiles": False,
            "attemptsDelivery": False,
            "storesSecrets": False,
            "installsDaemon": False,
            "authorizesLifecycle": False,
            "fallback": "approval packets remain repo-visible evidence and can be reviewed without this adapter",
        },
    }


def _approval_relay_adapter_findings(inventory: Inventory) -> list[Finding]:
    return [
        Finding(
            "info",
            "approval-relay-adapter",
            "adapter_id=approval-relay; group=Relay; role=approval-packet transport preview; owner=MyLittleHarness adapter boundary",
        ),
        Finding("info", "approval-relay-root", f"input root: {inventory.root}; root kind: {inventory.root_kind}"),
        Finding(
            "info",
            "approval-relay-runtime",
            "adapter-only relay report; no network call, webhook, credential lookup, daemon, queue, database, or adapter state is created",
        ),
    ]


def _approval_relay_packets(inventory: Inventory, approval_packet_refs: tuple[str, ...]) -> tuple[list[dict[str, object]], list[Finding]]:
    refs = _relay_ref_tuple(approval_packet_refs)
    if not refs:
        return (
            [],
            [
                Finding(
                    "warn",
                    "approval-relay-packet-ref-missing",
                    "supply --approval-packet-ref for each repo-visible approval packet to include in the relay preview",
                    APPROVAL_PACKETS_DIR_REL,
                )
            ],
        )

    packets: list[dict[str, object]] = []
    findings: list[Finding] = []
    for rel_path in refs:
        conflict = _relay_ref_conflict(rel_path)
        if conflict:
            findings.append(Finding("warn", "approval-relay-packet-ref-invalid", f"--approval-packet-ref {conflict}", rel_path))
            continue
        target = inventory.root / rel_path
        boundary_violation = source_path_boundary_violation(inventory.root, target, label="approval relay packet")
        if boundary_violation is not None:
            findings.append(Finding("warn", "approval-relay-packet-boundary", boundary_violation.message, rel_path))
            continue
        if not target.exists():
            findings.append(Finding("warn", "approval-relay-packet-missing", f"approval packet ref is missing: {rel_path}", rel_path))
            continue
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            findings.append(Finding("warn", "approval-relay-packet-unreadable", f"approval packet ref could not be read: {exc}", rel_path))
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            findings.append(Finding("warn", "approval-relay-packet-invalid-json", f"approval packet ref is not valid JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", "approval-relay-packet-invalid-shape", "approval packet JSON must be an object", rel_path))
            continue
        if data.get("schema") != APPROVAL_PACKET_SCHEMA or data.get("record_type") != "approval-packet":
            findings.append(
                Finding(
                    "warn",
                    "approval-relay-packet-invalid-shape",
                    "approval relay accepts only mylittleharness approval-packet evidence records",
                    rel_path,
                )
            )
            continue
        packet = {
            "ref": rel_path,
            "packet_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "schema": str(data.get("schema", "")),
            "approval_id": str(data.get("approval_id", "")),
            "status": str(data.get("status", "")),
            "gate_class": str(data.get("gate_class", "")),
            "subject": str(data.get("subject", "")),
            "requested_decision": str(data.get("requested_decision", "")),
        }
        packets.append(packet)
        status_note = "approved status remains evidence only" if packet["status"] == "approved" else "status remains evidence only"
        findings.append(
            Finding(
                "info",
                "approval-relay-packet",
                (
                    f"{rel_path}; approval_id={packet['approval_id']}; status={packet['status']}; "
                    f"gate_class={packet['gate_class']}; packet_hash={_hash_prefix(str(packet['packet_hash']))}; {status_note}"
                ),
                rel_path,
            )
        )
    return packets, findings


def _approval_relay_payload(
    inventory: Inventory,
    packets: list[dict[str, object]],
    *,
    relay_channel: str,
    relay_recipient: str,
) -> dict[str, object]:
    channel = _clean_relay_label(relay_channel) or "manual"
    recipient = _clean_relay_label(relay_recipient)
    return {
        "schema": APPROVAL_RELAY_PREVIEW_SCHEMA,
        "record_type": "approval-relay-preview",
        "adapter_id": APPROVAL_RELAY_TARGET,
        "root": str(inventory.root),
        "root_kind": inventory.root_kind,
        "transport": {
            "channel": channel,
            "recipient": recipient,
            "delivery_attempted": False,
            "stores_secrets": False,
            "installs_daemon": False,
            "persists_adapter_state": False,
        },
        "packet_refs": [packet["ref"] for packet in packets],
        "packets": packets,
        "authority_boundary": (
            "relay delivery or approved packet status cannot approve lifecycle, archive, roadmap status, staging, commit, push, or release"
        ),
    }


def _approval_relay_payload_findings(payload: dict[str, object], packets: list[dict[str, object]]) -> list[Finding]:
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    transport = payload["transport"]
    assert isinstance(transport, dict)
    return [
        Finding(
            "info",
            "approval-relay-payload",
            (
                f"relay payload is serializable; packet_count={len(packets)}; channel={transport['channel']}; "
                f"delivery_attempted=false; payload_hash={_payload_hash(payload)[:12]}"
            ),
        ),
        Finding(
            "info",
            "approval-relay-output-shape",
            f"payload_bytes={len(rendered.encode('utf-8'))}; packet_refs={len(payload['packet_refs'])}; source bodies are not copied into adapter state",
        ),
    ]


def _approval_relay_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "approval-relay-boundary",
            "approval relay is adapter-only transport preview; it does not send messages, store secrets, install daemons, persist adapter state, or treat delivery as human approval",
        ),
        Finding(
            "info",
            "approval-relay-no-authority",
            "approval relay output cannot authorize lifecycle transitions, archive, repair, roadmap movement, staging, commit, push, release, or next-plan opening",
        ),
        Finding(
            "info",
            "approval-relay-fail-open",
            "approval packets remain repo-visible evidence under project/verification/approval-packets and can be reviewed without any relay adapter",
            APPROVAL_PACKETS_DIR_REL,
        ),
    ]


def _relay_ref_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    cleaned: list[str] = []
    for value in values:
        text = _normalize_relay_ref(value)
        if text:
            cleaned.append(text)
    return tuple(dict.fromkeys(cleaned))


def _relay_ref_conflict(rel_path: str) -> str:
    if not rel_path:
        return "must be a non-empty root-relative path"
    if re.match(r"^[A-Za-z]:[\\/]", rel_path) or rel_path.startswith("/"):
        return "must be root-relative, not absolute"
    if any(part in {"..", ".", ""} for part in rel_path.split("/")):
        return "must not contain parent traversal, current-directory, or empty path segments"
    if not rel_path.startswith(f"{APPROVAL_PACKETS_DIR_REL}/") or not rel_path.endswith(".json"):
        return f"must point under {APPROVAL_PACKETS_DIR_REL}/*.json"
    return ""


def _normalize_relay_ref(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _clean_relay_label(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def mcp_read_projection_sections(
    inventory: Inventory,
    *,
    default_root: Path | None = None,
    requested_root: str | None = None,
) -> list[tuple[str, list[Finding]]]:
    projection = build_projection(inventory)
    root_selection = _root_selection_payload(inventory, _selection_default_root(inventory, default_root, requested_root), requested_root)
    return [
        ("Adapter", _adapter_findings(inventory, root_selection=root_selection)),
        ("Projection", _projection_findings(projection)),
        ("Sources", _source_findings(projection)),
        ("Generated Inputs", _generated_input_findings(inventory, projection)),
        ("Agent Action Packet", _agent_action_packet_findings(inventory)),
        ("Boundary", _boundary_findings()),
    ]


def mcp_read_projection_payload(
    inventory: Inventory,
    *,
    default_root: Path | None = None,
    requested_root: str | None = None,
) -> dict[str, object]:
    root_selection = _root_selection_payload(inventory, _selection_default_root(inventory, default_root, requested_root), requested_root)
    runtime = _adapter_runtime_payload(inventory, root_selection)
    sections = mcp_read_projection_sections(inventory, default_root=default_root, requested_root=requested_root)
    findings = [finding for _, section_findings in sections for finding in section_findings]
    projection = build_projection(inventory)
    artifact_findings = inspect_projection_artifacts(inventory, projection)
    index_findings = inspect_projection_index(inventory, projection)
    cache_posture = projection_cache_posture_payload(
        artifact_findings,
        index_findings,
        runtime_refresh_allowed=_runtime_refresh_allowed(inventory),
    )
    from .dashboard import connect_readiness_packet, dashboard_agent_packet, mlhd_freshness_payload

    agent_packet = dashboard_agent_packet(inventory)
    mlhd = mlhd_freshness_payload(inventory)
    return {
        "adapter": {
            "id": MCP_READ_PROJECTION_TARGET,
            "tool": MCP_READ_PROJECTION_TOOL,
            "group": "MCP",
            "role": "read/projection helper",
            "owner": "MyLittleHarness adapter boundary",
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "transport": "stdio",
        },
        "activation": mcp_read_projection_client_config(inventory),
        "root": _root_payload(inventory),
        "tools": list(MCP_TOOL_NAMES),
        "runtime": runtime,
        "rootSelection": root_selection,
        "cachePosture": cache_posture,
        "mlhd": mlhd,
        "agentPacket": agent_packet,
        "connectReadiness": connect_readiness_packet(
            inventory,
            cache_posture=cache_posture,
            agent_packet=agent_packet,
        ),
        "status": _result_for(findings),
        "sources": inventory.sources_for_report(),
        "sections": [
            {
                "name": section_name,
                "findings": [_finding_payload(finding) for finding in section_findings],
            }
            for section_name, section_findings in sections
        ],
        "boundary": {
            **_mcp_tool_boundary(root_selection, source_bodies_included=False, source_body_mode="none"),
            "serveCommand": mcp_read_projection_serve_command(inventory),
            "refreshPolicy": (
                "tool calls reload the selected root inventory in memory; generated projection artifacts and SQLite indexes "
                "remain optional inputs and are never refreshed by the adapter"
            ),
            "fallback": "generic CLI and repo-visible files remain sufficient without MCP tooling",
            "rootSelection": root_selection,
        },
    }


def mcp_read_projection_serve_command(inventory: Inventory | None = None, *, bind_root: bool = False) -> list[str]:
    command = ["mylittleharness"]
    if bind_root:
        if inventory is None:
            raise ValueError("bind_root requires an inventory")
        command.extend(["--root", str(inventory.root)])
    command.extend(["adapter", "--serve", "--target", MCP_READ_PROJECTION_TARGET, "--transport", "stdio"])
    return command


def mcp_read_projection_client_config(inventory: Inventory, *, codex_config_path: str | Path | None = None) -> dict[str, object]:
    command = mcp_read_projection_serve_command(inventory)
    adoption = codex_mcp_adoption_payload(inventory, codex_config_path=codex_config_path, include_snippet=True)
    server = {
        "name": MCP_READ_PROJECTION_SERVER_NAME,
        "command": command[0],
        "args": command[1:],
        "transport": "stdio",
    }
    return {
        "status": "available",
        "defaultActive": True,
        "serverName": MCP_READ_PROJECTION_SERVER_NAME,
        "tool": MCP_READ_PROJECTION_TOOL,
        "tools": [
            {"name": definition["name"], "inputSchema": definition["inputSchema"]}
            for definition in _tool_definitions()
        ],
        "recommendedUse": (
            "call before or alongside CLI/file reads when route discovery, source snippets, text search, "
            "relationship lookup, impact checks, or root selection would reduce navigation"
        ),
        "toolInputSchema": _read_projection_input_schema(),
        "rootSelection": {
            "defaultRoot": str(inventory.root),
            "defaultRootOptional": True,
            "toolArgument": "root",
            "supportsPerCallRoot": True,
            "refreshesInventoryPerCall": True,
            "serverLaunch": "rootless-router",
            "boundary": (
                "per-call root selection reads another MLH-serviced root without installing scaffold, lifecycle debris, "
                "generated cache authority, or another runtime layer"
            ),
        },
        "codex": {
            "configPath": "%USERPROFILE%\\.codex\\config.toml",
            "resolvedConfigPath": adoption["configPath"],
            "server": server,
            "toml": _codex_mcp_toml(command),
            "adoption": adoption,
        },
        "generic": {
            "server": server,
            "json": {"mcpServers": {MCP_READ_PROJECTION_SERVER_NAME: {"command": command[0], "args": command[1:]}}},
        },
        "adoption": adoption,
        "boundary": {
            "writesUserConfig": False,
            "writesUserConfigOnApplyOnly": True,
            "writesRepoFiles": False,
            "writesProjectCodexHooksOnInstallApplyOnly": True,
            "storesSecrets": False,
            "authorizesLifecycle": False,
            "fallback": "repo-visible files and generic CLI remain authoritative when no MCP client is active",
        },
    }


def codex_mcp_adoption_payload(
    inventory: Inventory,
    *,
    codex_config_path: str | Path | None = None,
    include_snippet: bool = False,
) -> dict[str, object]:
    from .hooks import codex_hook_adapter_adoption_payload

    command = mcp_read_projection_serve_command(inventory)
    config_path = _codex_config_path(codex_config_path)
    expected_server = _codex_expected_server(command)
    snippet = _codex_mcp_toml(command)
    status, mounted, reason, extra_keys = _codex_config_status(config_path, expected_server)
    merge_mode = _codex_merge_mode(status)
    payload: dict[str, object] = {
        "schema": CODEX_MCP_ADOPTION_SCHEMA,
        "client": "codex",
        "serverName": MCP_READ_PROJECTION_SERVER_NAME,
        "status": status,
        "mounted": mounted,
        "configPath": str(config_path),
        "displayConfigPath": CODEX_CONFIG_DISPLAY_PATH if codex_config_path is None else str(config_path),
        "expectedServer": expected_server,
        "expectedSnippetHash": _payload_hash(snippet)[:12],
        "merge": {
            "mode": merge_mode,
            "idempotent": True,
            "dryRunCommand": "mylittleharness --root <root> adapter --install-client-config --target mcp-read-projection --dry-run",
            "applyCommand": "mylittleharness --root <root> adapter --install-client-config --target mcp-read-projection --apply",
            "backupExistingConfigOnApply": True,
            "writesUserConfigOnApply": True,
            "writesProjectCodexHooksOnApply": True,
            "storesSecrets": False,
            "printsExistingConfigValues": False,
        },
        "projectHooks": codex_hook_adapter_adoption_payload(inventory),
        "dashboardPacketAvailable": True,
        "firstPass": [
            "mylittleharness --root <root> dashboard --inspect --json",
            "mylittleharness --root <root> adapter --client-config --target mcp-read-projection",
            "mylittleharness --root <root> projection --warm-cache --target all",
            "rg \"<exact symbol or route>\"",
        ],
        "toolCoverage": _mcp_navigation_tool_coverage_payload(),
        "exactVerification": {
            "required": True,
            "methods": ["rg", MCP_READ_SOURCE_TOOL, "direct source reads"],
            "reason": "MCP search and SQLite accelerate discovery; exact source claims still need rg or bounded source reads",
        },
        "boundary": (
            "Codex MCP and project-hook adoption is helper tooling only; mounted or missing status cannot approve lifecycle movement, repair, "
            "archive, roadmap status, staging, commit, push, provider routing, product diffs, or cache truth"
        ),
    }
    if reason:
        payload["reason"] = reason
    if extra_keys:
        payload["extraFieldNames"] = list(extra_keys)
    if include_snippet:
        payload["toml"] = snippet
    return payload


def codex_mcp_install_sections(
    inventory: Inventory,
    *,
    codex_config_path: str | Path | None = None,
    apply: bool = False,
) -> list[tuple[str, list[Finding]]]:
    from .hooks import CodexHookAdapterRequest, codex_hook_adapter_apply_findings, codex_hook_adapter_dry_run_findings

    command = mcp_read_projection_serve_command(inventory)
    config_path = _codex_config_path(codex_config_path)
    expected_server = _codex_expected_server(command)
    status, mounted, reason, extra_keys = _codex_config_status(config_path, expected_server)
    hook_request = CodexHookAdapterRequest()
    findings: list[Finding] = [
        Finding(
            "info",
            "adapter-codex-config-boundary",
            (
                "Codex MCP config adoption is explicit and client-local; dry-run writes nothing, apply writes only "
                "the reviewed MCP server table plus project-local MLH Codex native hooks, and repo-visible files remain authority"
            ),
        ),
        Finding(
            "info",
            "adapter-codex-config-target",
            f"client=codex; server={MCP_READ_PROJECTION_SERVER_NAME}; config_path={config_path}; mounted={str(mounted).lower()}; status={status}",
        ),
        Finding(
            "info",
            "adapter-codex-config-snippet",
            f"expected idempotent server snippet hash={_payload_hash(_codex_mcp_toml(command))[:12]}; existing config values are not printed",
        ),
        Finding(
            "info",
            "adapter-codex-config-merge",
            (
                f"merge_mode={_codex_merge_mode(status)}; backup_existing_config_on_apply=true; "
                "stores_secrets=false; apply is refused for conflicting or invalid existing server tables"
            ),
        ),
    ]
    if reason:
        findings.append(Finding("info" if mounted else "warn", "adapter-codex-config-status", reason))
    if extra_keys:
        findings.append(
            Finding(
                "info",
                "adapter-codex-config-extra-fields",
                f"existing server table has extra field names only: {', '.join(extra_keys)}; values are not printed",
            )
        )
    if not apply:
        if status in {"conflict", "invalid-toml", "blocked", "unreadable"}:
            findings.append(
                Finding(
                    "warn",
                    "adapter-codex-config-dry-run-refused",
                    "apply would be refused until the existing Codex config is reviewed; no workstation file was changed",
                )
            )
        elif mounted:
            findings.append(Finding("info", "adapter-codex-config-dry-run", "MCP server is already mounted; apply would be a no-op"))
        else:
            findings.append(
                Finding(
                    "info",
                    "adapter-codex-config-dry-run",
                    f"would append MCP server table to {config_path}; no workstation file was changed",
                )
            )
        hook_findings = [
            Finding(
                "info",
                "adapter-codex-hook-autoadoption",
                "project-local Codex native hooks are included in the same adoption preview by default",
                ".codex/hooks.json",
            )
        ]
        hook_findings.extend(codex_hook_adapter_dry_run_findings(inventory, hook_request))
        findings.extend(_codex_config_install_boundary_findings())
        return [("Codex MCP Config", findings), ("Codex Native Hooks", hook_findings)]

    apply_findings = _apply_codex_mcp_config(config_path, command, status, mounted)
    findings.extend(apply_findings)
    hook_findings = [
        Finding(
            "info",
            "adapter-codex-hook-autoadoption",
            "project-local Codex native hooks are included in the same adoption apply by default",
            ".codex/hooks.json",
        )
    ]
    if any(finding.severity == "error" for finding in apply_findings):
        hook_findings.append(
            Finding(
                "warn",
                "adapter-codex-hook-autoadoption-skipped",
                "project-local Codex hooks were not written because the Codex MCP config apply was refused",
                ".codex/hooks.json",
            )
        )
    else:
        hook_findings.extend(codex_hook_adapter_apply_findings(inventory, hook_request))
    findings.extend(_codex_config_install_boundary_findings())
    return [("Codex MCP Config", findings), ("Codex Native Hooks", hook_findings)]


def _mcp_navigation_tool_coverage_payload() -> dict[str, object]:
    return {
        MCP_READ_PROJECTION_TOOL: "current root posture, cache posture, source records, adapter boundary, and root selection",
        MCP_READ_SOURCE_TOOL: "bounded source slices for exact line-level verification",
        MCP_SEARCH_TOOL: "source-verified exact, path, and SQLite full-text navigation",
        MCP_RELATED_OR_BUNDLE_TOOL: "links, fan-in, relationship rows, and nearby bundle source records",
        "nextSafeGuidance": "dashboard and check still name the next legal dry-run/apply candidate; MCP output stays advisory",
    }


def serve_mcp_read_projection(
    inventory: Inventory | None,
    stdin: TextIO,
    stdout: TextIO,
    inventory_loader: InventoryLoader = load_inventory,
) -> int:
    for line in stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            _write_message(stdout, _error_response(None, -32700, "Parse error", {"detail": str(exc)}))
            continue
        response = _handle_jsonrpc_message(inventory, message, inventory_loader)
        if response is not None:
            _write_message(stdout, response)
    return 0


def _adapter_findings(inventory: Inventory, *, root_selection: dict[str, object]) -> list[Finding]:
    runtime = _adapter_runtime_payload(inventory, root_selection)
    findings = [
        Finding(
            "info",
            "adapter-boundary",
            "terminal-only read-only adapter inspection; no files, generated reports, caches, databases, hooks, adapter state, or mutations are written",
        ),
        Finding(
            "info",
            "adapter-target",
            "adapter_id=mcp-read-projection; group=MCP; role=read/projection helper; owner=MyLittleHarness adapter boundary",
        ),
        Finding(
            "info",
            "adapter-root",
            (
                f"input root: {inventory.root}; root kind: {inventory.root_kind}; "
                "classification is coarse routing posture, not lifecycle validity proof"
            ),
        ),
        Finding(
            "info",
            "adapter-output-shape",
            "sectioned terminal report and MCP stdio tool payloads for adapter metadata, projection summary, bounded source reads, search, related bundles, generated-input posture, and boundary notes",
        ),
        Finding(
            "info",
            "adapter-runtime",
            "dependency-free MCP stdio serving is explicit and foreground-only; no MCP SDK, HTTP server, network dependency, hook, IDE, browser, GitHub, CI, or task-runner runtime is required",
        ),
        Finding(
            "info",
            "adapter-runtime-provenance",
            (
                f"package_version={runtime['packageVersion']}; module_path={runtime['modulePath']}; "
                f"startup_root={runtime['startupRoot']}; selected_root={runtime['selectedRoot']}; "
                f"requested_root={runtime['requestedRoot'] or '<none>'}"
            ),
        ),
        Finding(
            "info",
            "adapter-mcp-helper",
            (
                "read-only MCP helper can be served rootless with `mylittleharness adapter --serve --target "
                "mcp-read-projection --transport stdio`; each tool call can select an MLH root while generated inputs remain optional"
            ),
        ),
        Finding(
            "info",
            "adapter-mcp-tools",
            (
                "MCP tools: mylittleharness.read_projection, mylittleharness.read_source, "
                "mylittleharness.search, mylittleharness.related_or_bundle; source-body policy is per-tool"
            ),
        ),
        Finding(
            "info",
            "adapter-default-agent-tooling",
            (
                "default agent tooling config is available for MCP server `mylittleharness` and tool "
                "`mylittleharness.read_projection`; MyLittleHarness reports the config but does not write user config"
            ),
        ),
        Finding(
            "info",
            "adapter-agent-use",
            (
                "agents should call MCP read/search/bundle tools with optional root selection before or alongside CLI/file reads "
                "when projection context helps navigation, relationship lookup, route discovery, source snippets, or impact checks"
            ),
        ),
        Finding(
            "info",
            "adapter-root-selection",
            (
                "MCP tools accept optional `root` per call and reload that MLH-serviced root read-only; rootless server launches "
                "require `root`, while legacy root-bound launches may omit it to reload the startup root"
            ),
        ),
    ]
    if runtime.get("routerMode") is True:
        findings.append(
            Finding(
                "info",
                "adapter-runtime-rootless-router",
                "MCP server is operating without a startup authority root; each tool call must select a root or fail read-only",
            )
        )
    if runtime["requestedRoot"] and runtime["startupRoot"] != runtime["selectedRoot"]:
        findings.append(
            Finding(
                "info",
                "adapter-runtime-root-override",
                (
                    "per-call root selection differs from the MCP server startup root; this call uses selected_root, "
                    "but omitted-root calls use startup_root. If startup_root is unexpected, restart or reconfigure the MCP server "
                    "with the reported serve command, or fall back to direct CLI/source reads."
                ),
            )
        )
    return findings


def _projection_findings(projection: Projection) -> list[Finding]:
    summary = projection.summary
    return [
        Finding(
            "info",
            "adapter-projection-rebuild",
            (
                "in-memory projection rebuilt from inventory; storage_boundary=none; "
                f"source_set_hash={_source_set_hash(projection)}; record_set_hash={_record_set_hash(projection)}"
            ),
        ),
        Finding(
            "info",
            "adapter-projection-summary",
            (
                f"sources={summary.source_count}; present={summary.present_source_count}; "
                f"readable={summary.readable_source_count}; hashed={summary.hashed_source_count}; "
                f"missing_required={summary.missing_required_count}"
            ),
        ),
        Finding(
            "info",
            "adapter-record-counts",
            f"links={summary.link_record_count}; fan_in={summary.fan_in_record_count}",
        ),
    ]


def _agent_action_packet_findings(inventory: Inventory) -> list[Finding]:
    from .dashboard import connect_readiness_packet, mlhd_freshness_payload

    readiness = connect_readiness_packet(inventory)
    lifecycle = readiness.get("lifecycle", {}) if isinstance(readiness.get("lifecycle"), dict) else {}
    writeback = readiness.get("writeback", {}) if isinstance(readiness.get("writeback"), dict) else {}
    docs = readiness.get("docs", {}) if isinstance(readiness.get("docs"), dict) else {}
    mlhd = mlhd_freshness_payload(inventory)
    return [
        Finding(
            "info",
            "adapter-agent-action-packet",
            (
                f"read_projection surfaces active_phase={_payload_value(lifecycle, 'active_phase')}; "
                f"phase_status={_payload_value(lifecycle, 'phase_status')}; "
                f"writeback_required={str(writeback.get('requiredWhenPlanStatusActive') is True).lower()}; "
                f"docmap={_payload_value(docs, 'docmapStatus')}; docs_decision={_payload_value(docs, 'docsDecision')}; "
                f"mlhd={mlhd['control_status']}; dirty_count={mlhd['dirty_count']}; next_safe={readiness.get('nextSafeCommand')}"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
        Finding(
            "info",
            "adapter-agent-action-boundary",
            "MCP action packet fields are derived navigation hints only; they cannot approve lifecycle, cache truth, source mutation, VCS, release, or provider routing",
        ),
    ]


def _payload_value(payload: object, key: str) -> str:
    if isinstance(payload, dict):
        value = payload.get(key)
        if value is not None and value != "":
            return str(value)
    return "<none>"


def _runtime_refresh_allowed(inventory: Inventory) -> bool:
    return inventory.root_kind != PRODUCT_SOURCE_FIXTURE


def _source_findings(projection: Projection) -> list[Finding]:
    findings: list[Finding] = []
    for source in projection.sources:
        if source.readable:
            posture = "readable"
        elif not source.present:
            posture = "missing"
        else:
            posture = f"unreadable: {source.read_error or 'unknown read error'}"
        findings.append(
            Finding(
                "info",
                "adapter-source-record",
                (
                    f"{source.path}; role={source.role}; required={source.required}; posture={posture}; "
                    f"lines={source.line_count}; bytes={source.byte_count}; headings={source.heading_count}; "
                    f"links={source.link_count}; hash={_hash_prefix(source.content_hash)}"
                ),
                source.path,
            )
        )
    return findings


def _generated_input_findings(inventory: Inventory, projection: Projection) -> list[Finding]:
    artifact_findings = inspect_projection_artifacts(inventory, projection)
    index_findings = inspect_projection_index(inventory, projection)
    posture = projection_cache_posture_payload(
        artifact_findings,
        index_findings,
        runtime_refresh_allowed=_runtime_refresh_allowed(inventory),
    )
    refresh_commands = ", ".join(str(command) for command in posture.get("recommended_refresh_commands", [])[:2])
    return [
        Finding(
            "info",
            "adapter-generated-input-boundary",
            "generated projection artifacts and SQLite indexes are optional adapter inputs; direct repo files and the current in-memory projection remain authoritative",
        ),
        Finding(
            "info",
            "adapter-cache-posture",
            (
                "cache_posture schema=mylittleharness.projection-cache-posture.v1; "
                f"source_refs={len(posture['source_refs'])}; refresh_by_adapter=false; "
                "adapter_executes_refresh=false; commands_are_suggestions_only=true; "
                f"displayed_refresh_commands={refresh_commands}"
            ),
        ),
        _generated_posture("artifacts", artifact_findings),
        _generated_posture("index", index_findings),
    ]


def _generated_posture(kind: str, findings: list[Finding]) -> Finding:
    degraded = [
        finding
        for finding in findings
        if finding.severity in {"warn", "error"} or finding.code in {"projection-artifact-missing", "projection-index-missing"}
    ]
    if not degraded:
        return Finding(
            "info",
            f"adapter-generated-{kind}",
            f"generated {kind} posture is current; adapter output still treats generated data as advisory",
        )
    severity = "warn" if any(finding.severity in {"warn", "error"} for finding in degraded) else "info"
    sample = "; ".join(f"{finding.code}: {_trim(finding.message)}" for finding in degraded[:3])
    return Finding(
        severity,
        f"adapter-generated-{kind}",
        (
            f"generated {kind} posture is degraded but optional: {sample}; adapter fails open to repo files and in-memory projection; "
            "run projection --inspect/--rebuild on the selected root if useful, and if CLI posture is current while MCP remains degraded, "
            "restart/reconfigure the MCP server or use direct CLI/source reads"
        ),
    )


def _adapter_runtime_payload(inventory: Inventory, root_selection: dict[str, object]) -> dict[str, object]:
    startup_root = str(root_selection.get("defaultRoot") or "")
    return {
        "packageVersion": __version__,
        "modulePath": str(Path(__file__).resolve()),
        "startupRoot": startup_root,
        "selectedRoot": str(root_selection.get("selectedRoot") or inventory.root),
        "requestedRoot": str(root_selection.get("requestedRoot") or ""),
        "routerMode": bool(root_selection.get("routerMode")),
        "serveCommand": mcp_read_projection_serve_command(inventory),
        "recovery": (
            "if MCP output disagrees with current CLI/source posture, restart or reconfigure the MCP server from the reported "
            "module/root provenance, or use direct CLI/source reads as authority"
        ),
    }


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "adapter-no-authority",
            "adapter output is helper evidence only and cannot authorize accepted decisions, repair, closeout, archive, commit, lifecycle changes",
        ),
        Finding(
            "info",
            "adapter-no-source-bodies",
            "adapter source records expose paths, roles, counts, and hashes only; source file bodies remain in repo-visible files",
        ),
        Finding(
            "info",
            "adapter-no-mutation",
            "adapter inspection does not create MCP state, generated reports, projection artifacts, snapshots, hooks, config, commits, or filesystem mutations",
        ),
        Finding(
            "info",
            "adapter-recovery",
            "generic CLI and repo files remain usable when MCP tooling is absent, stale, disabled, or never installed",
        ),
    ]


def _source_set_hash(projection: Projection) -> str:
    rows = [(source.path, source.content_hash) for source in projection.sources if source.content_hash is not None]
    return _payload_hash(rows)[:12]


def _record_set_hash(projection: Projection) -> str:
    rows = [
        ("link", record.source, record.line, record.target, record.status, record.resolution_kind)
        for record in projection.links
    ] + [
        ("fan_in", record.target, record.inbound_count, record.status, record.sources)
        for record in projection.fan_in
    ]
    return _payload_hash(rows)[:12]


def _payload_hash(payload: object) -> str:
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _hash_prefix(value: str | None) -> str:
    return value[:12] if value else "none"


def _trim(value: str, limit: int = 140) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _codex_mcp_toml(command: list[str]) -> str:
    rendered_args = ", ".join(json.dumps(arg, ensure_ascii=True) for arg in command[1:])
    return "\n".join(
        [
            f"[mcp_servers.{MCP_READ_PROJECTION_SERVER_NAME}]",
            f"command = {json.dumps(command[0], ensure_ascii=True)}",
            f"args = [{rendered_args}]",
        ]
    )


def _codex_mcp_toml_block(command: list[str]) -> str:
    return "\n".join([CODEX_MCP_BLOCK_START, _codex_mcp_toml(command), CODEX_MCP_BLOCK_END, ""])


def _codex_config_path(config_path: str | Path | None) -> Path:
    if config_path is not None:
        return Path(config_path).expanduser()
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        return Path(userprofile).expanduser() / ".codex" / "config.toml"
    return Path.home() / ".codex" / "config.toml"


def _codex_expected_server(command: list[str]) -> dict[str, object]:
    return {"command": command[0], "args": command[1:]}


def _codex_config_status(
    config_path: Path,
    expected_server: dict[str, object],
) -> tuple[str, bool, str, tuple[str, ...]]:
    if config_path.exists() and not config_path.is_file():
        return "blocked", False, "Codex config path exists but is not a regular file; apply is refused", ()
    if not config_path.exists():
        return "missing", False, "Codex config file is missing; reviewed apply can create it", ()
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        return "unreadable", False, f"Codex config could not be read; apply is refused: {exc}", ()
    try:
        data = tomllib.loads(text or "")
    except tomllib.TOMLDecodeError as exc:
        return "invalid-toml", False, f"Codex config is not valid TOML; apply is refused: {exc}", ()
    servers = data.get("mcp_servers")
    server = servers.get(MCP_READ_PROJECTION_SERVER_NAME) if isinstance(servers, dict) else None
    if server is None:
        return "missing-server", False, "Codex config is readable but the mylittleharness MCP server table is missing", ()
    if not isinstance(server, dict):
        return "conflict", False, "Codex config has a non-table mylittleharness MCP server entry; apply is refused", ()
    command_matches = server.get("command") == expected_server["command"]
    args_matches = server.get("args") == expected_server["args"]
    extra_keys = tuple(sorted(str(key) for key in set(server) - {"command", "args"}))
    if command_matches and args_matches:
        return "mounted", True, "Codex config already mounts the expected rootless mylittleharness MCP server", extra_keys
    if _is_legacy_root_bound_mcp_server(server) and not extra_keys:
        return (
            "legacy-root-bound",
            False,
            "Codex config mounts the legacy root-bound mylittleharness MCP server; reviewed apply can replace it with the rootless router command",
            extra_keys,
        )
    return "conflict", False, "Codex config already has a mylittleharness MCP server table with different command or args; apply is refused", extra_keys


def _codex_merge_mode(status: str) -> str:
    if status == "mounted":
        return "no-op"
    if status in {"missing", "missing-server"}:
        return "append-managed-server-table"
    if status == "legacy-root-bound":
        return "replace-legacy-root-bound-server-table"
    return "refuse-unreviewed-existing-config"


def _apply_codex_mcp_config(config_path: Path, command: list[str], status: str, mounted: bool) -> list[Finding]:
    if mounted:
        return [Finding("info", "adapter-codex-config-apply-unchanged", "MCP server is already mounted; no workstation file was changed")]
    if status not in {"missing", "missing-server", "legacy-root-bound"}:
        return [
            Finding(
                "error",
                "adapter-codex-config-apply-refused",
                f"refused to write Codex config while adoption status is {status}; run --client-config and review the existing config manually",
            )
        ]
    if config_path.exists() and not config_path.is_file():
        return [Finding("error", "adapter-codex-config-apply-refused", "config path exists but is not a regular file")]
    if config_path.parent.exists() and not config_path.parent.is_dir():
        return [Finding("error", "adapter-codex-config-apply-refused", "config parent path exists but is not a directory")]
    try:
        before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        backup_finding = _backup_codex_config(config_path, before) if before else None
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(_merged_codex_config_text(before, command, replace_existing=status == "legacy-root-bound"), encoding="utf-8")
    except OSError as exc:
        return [Finding("error", "adapter-codex-config-apply-refused", f"could not write Codex config: {exc}")]
    after_status, after_mounted, after_reason, _extra = _codex_config_status(config_path, _codex_expected_server(command))
    findings: list[Finding] = []
    if backup_finding is not None:
        findings.append(backup_finding)
    if after_mounted:
        findings.append(
            Finding(
                "info",
                "adapter-codex-config-apply-written",
                f"mounted mylittleharness MCP server in Codex config; post_status={after_status}; {after_reason}",
            )
        )
    else:
        findings.append(
            Finding(
                "error",
                "adapter-codex-config-apply-refused",
                f"Codex config write did not produce a mounted server; post_status={after_status}; {after_reason}",
            )
        )
    return findings


def _backup_codex_config(config_path: Path, text: str) -> Finding:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    backup_path = config_path.with_name(f"{config_path.name}.mylittleharness-backup-{digest}")
    if not backup_path.exists():
        backup_path.write_text(text, encoding="utf-8")
    return Finding(
        "info",
        "adapter-codex-config-backup",
        f"existing Codex config backup present: {backup_path}; backup content was not printed",
    )


def _merged_codex_config_text(before: str, command: list[str], *, replace_existing: bool = False) -> str:
    if replace_existing:
        replaced = _replace_codex_mcp_server_block(before, command)
        if replaced is not None:
            return replaced
    prefix = before.rstrip()
    block = _codex_mcp_toml_block(command).rstrip()
    if not prefix:
        return block + "\n"
    return prefix + "\n\n" + block + "\n"


def _replace_codex_mcp_server_block(before: str, command: list[str]) -> str | None:
    lines = before.splitlines()
    header = f"[mcp_servers.{MCP_READ_PROJECTION_SERVER_NAME}]"
    start = next((index for index, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = index
            break
    block_lines = _codex_mcp_toml(command).splitlines()
    merged = lines[:start] + block_lines + lines[end:]
    text = "\n".join(merged).rstrip()
    return text + "\n"


def _is_legacy_root_bound_mcp_server(server: dict[str, object]) -> bool:
    args = server.get("args")
    if server.get("command") != "mylittleharness" or not isinstance(args, list):
        return False
    legacy_suffix = ["adapter", "--serve", "--target", MCP_READ_PROJECTION_TARGET, "--transport", "stdio"]
    return len(args) == len(legacy_suffix) + 2 and args[0] == "--root" and isinstance(args[1], str) and args[2:] == legacy_suffix


def _codex_config_install_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "adapter-codex-config-no-secrets",
            "reports include only status, expected command/args, hashes, and field names; existing config values are never printed",
        ),
        Finding(
            "info",
            "adapter-codex-config-no-authority",
            "MCP config adoption cannot approve lifecycle movement, repair, archive, roadmap status, staging, commit, push, provider routing, product diffs, or cache truth",
        ),
    ]


def _root_selection_payload(inventory: Inventory, default_root: Path | None, requested_root: str | None) -> dict[str, object]:
    return {
        "defaultRoot": str(default_root) if default_root is not None else "",
        "selectedRoot": str(inventory.root),
        "requestedRoot": requested_root or "",
        "toolArgument": "root",
        "inventoryReloadedPerCall": True,
        "startupRootAvailable": default_root is not None,
        "routerMode": default_root is None,
        "rootKindIsLifecycleCertification": False,
        "writesFiles": False,
        "authorizesLifecycle": False,
    }


def _selection_default_root(inventory: Inventory, default_root: Path | None, requested_root: str | None) -> Path | None:
    if default_root is None and requested_root:
        return None
    return default_root or inventory.root


def _handle_jsonrpc_message(inventory: Inventory | None, message: object, inventory_loader: InventoryLoader) -> dict[str, object] | None:
    if not isinstance(message, dict):
        return _error_response(None, -32600, "Invalid Request")
    request_id = message.get("id")
    method = message.get("method")
    is_request = "id" in message
    if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _error_response(request_id if is_request else None, -32600, "Invalid Request") if is_request else None
    if method == "notifications/initialized":
        return None
    if not is_request:
        return None
    if method == "initialize":
        return _result_response(request_id, _initialize_result())
    if method == "ping":
        return _result_response(request_id, {})
    if method == "tools/list":
        return _result_response(request_id, {"tools": _tool_definitions()})
    if method == "tools/call":
        return _tools_call_response(inventory, request_id, message.get("params"), inventory_loader)
    return _error_response(request_id, -32601, f"Method not found: {method}")


def _initialize_result() -> dict[str, object]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {
            "name": "mylittleharness",
            "title": "MyLittleHarness Read Projection",
            "version": __version__,
            "description": "Dependency-free read-only MCP stdio adapter for MyLittleHarness projection posture.",
        },
        "instructions": (
            "Use the mylittleharness read/projection tools as optional root-aware helper evidence only; "
            "repo-visible files and the generic CLI remain authoritative."
        ),
    }


def _root_input_property() -> dict[str, object]:
    return {
        "type": "string",
        "description": (
            "Optional filesystem path to an MLH-serviced root to read for this call. "
            "Required when the server was launched rootless; legacy root-bound launches may omit it to reload the adapter startup root."
        ),
    }


def _read_projection_input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "root": _root_input_property(),
        },
        "additionalProperties": False,
    }


def _read_source_input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "root": _root_input_property(),
            "path": {
                "type": "string",
                "description": "Required root-relative source path from the current projection.",
            },
            "start": {
                "type": "integer",
                "description": f"1-based starting line. Defaults to 1. Maximum returned lines is {MCP_SOURCE_READ_MAX_LIMIT}.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum source lines to return. Defaults to {MCP_SOURCE_READ_DEFAULT_LIMIT}; max {MCP_SOURCE_READ_MAX_LIMIT}.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }


def _search_input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "root": _root_input_property(),
            "query": {
                "type": "string",
                "description": "Required search text.",
            },
            "mode": {
                "type": "string",
                "description": "Search mode: all, exact, path, or full-text. Defaults to all.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum result rows to return. Defaults to {MCP_SEARCH_DEFAULT_LIMIT}; max {MCP_SEARCH_MAX_LIMIT}.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }


def _related_or_bundle_input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "root": _root_input_property(),
            "path": {
                "type": "string",
                "description": "Required root-relative source path from the current projection.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum related rows per group. Defaults to {MCP_RELATED_DEFAULT_LIMIT}; max {MCP_RELATED_MAX_LIMIT}.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }


def _tool_definitions() -> list[dict[str, object]]:
    return [_read_projection_tool_definition(), _read_source_tool_definition(), _search_tool_definition(), _related_or_bundle_tool_definition()]


def _read_projection_tool_definition() -> dict[str, object]:
    return {
        "name": MCP_READ_PROJECTION_TOOL,
        "title": "MyLittleHarness Read Projection",
        "description": (
            "Return a source-bound, read-only projection summary for a selected MyLittleHarness root without copying source "
            "bodies or approving lifecycle decisions."
        ),
        "inputSchema": _read_projection_input_schema(),
        "outputSchema": {
            "type": "object",
            "properties": {
                "adapter": {"type": "object"},
                "activation": {"type": "object"},
                "root": {"type": "object"},
                "tools": {"type": "array"},
                "runtime": {"type": "object"},
                "rootSelection": {"type": "object"},
                "cachePosture": {"type": "object"},
                "mlhd": {"type": "object"},
                "agentPacket": {"type": "object"},
                "connectReadiness": {"type": "object"},
                "status": {"type": "string"},
                "sources": {"type": "array"},
                "sections": {"type": "array"},
                "boundary": {"type": "object"},
            },
            "required": [
                "adapter",
                "activation",
                "root",
                "tools",
                "runtime",
                "rootSelection",
                "cachePosture",
                "mlhd",
                "agentPacket",
                "connectReadiness",
                "status",
                "sources",
                "sections",
                "boundary",
            ],
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        "execution": {"taskSupport": "forbidden"},
    }


def _read_source_tool_definition() -> dict[str, object]:
    return {
        "name": MCP_READ_SOURCE_TOOL,
        "title": "MyLittleHarness Read Source",
        "description": (
            "Return a bounded source-verified line slice from a root-relative projection source without writing files, "
            "refreshing caches, or approving lifecycle decisions."
        ),
        "inputSchema": _read_source_input_schema(),
        "outputSchema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string"},
                "root": {"type": "object"},
                "source": {"type": "object"},
                "range": {"type": "object"},
                "lines": {"type": "array"},
                "text": {"type": "string"},
                "boundary": {"type": "object"},
            },
            "required": ["tool", "root", "source", "range", "lines", "text", "boundary"],
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        "execution": {"taskSupport": "forbidden"},
    }


def _search_tool_definition() -> dict[str, object]:
    return {
        "name": MCP_SEARCH_TOOL,
        "title": "MyLittleHarness Search",
        "description": (
            "Search current projection sources by exact text, path/reference rows, and current source-verified SQLite FTS "
            "when available, without refreshing generated caches."
        ),
        "inputSchema": _search_input_schema(),
        "outputSchema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string"},
                "root": {"type": "object"},
                "query": {"type": "string"},
                "mode": {"type": "string"},
                "limit": {"type": "integer"},
                "results": {"type": "array"},
                "findings": {"type": "array"},
                "boundary": {"type": "object"},
            },
            "required": ["tool", "root", "query", "mode", "limit", "results", "findings", "boundary"],
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        "execution": {"taskSupport": "forbidden"},
    }


def _related_or_bundle_tool_definition() -> dict[str, object]:
    return {
        "name": MCP_RELATED_OR_BUNDLE_TOOL,
        "title": "MyLittleHarness Related Or Bundle",
        "description": (
            "Return nearby source records, links, fan-in, and relationship graph rows for a root-relative projection source "
            "without copying source bodies or writing files."
        ),
        "inputSchema": _related_or_bundle_input_schema(),
        "outputSchema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string"},
                "root": {"type": "object"},
                "path": {"type": "string"},
                "source": {"type": "object"},
                "outboundLinks": {"type": "array"},
                "inboundLinks": {"type": "array"},
                "fanIn": {"type": "array"},
                "relationshipNodes": {"type": "array"},
                "relationshipEdges": {"type": "array"},
                "bundleSources": {"type": "array"},
                "boundary": {"type": "object"},
            },
            "required": ["tool", "root", "path", "source", "outboundLinks", "inboundLinks", "bundleSources", "boundary"],
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        "execution": {"taskSupport": "forbidden"},
    }


def _tools_call_response(
    inventory: Inventory | None,
    request_id: object,
    params: object,
    inventory_loader: InventoryLoader,
) -> dict[str, object]:
    if not isinstance(params, dict):
        return _error_response(request_id, -32602, "Invalid params: tools/call params must be an object")
    name = params.get("name")
    if name not in MCP_TOOL_NAMES:
        return _error_response(request_id, -32602, f"Unknown tool: {name}")
    arguments = params.get("arguments", {})
    if arguments is None:
        arguments = {}
    target_root, requested_root, error = _selected_root_argument(inventory, arguments, _tool_argument_names(str(name)))
    if error:
        return _tool_error_response(request_id, error)
    try:
        selected_inventory = inventory_loader(target_root)
    except RootLoadError as exc:
        return _tool_error_response(request_id, f"Invalid root: {exc}")

    default_root = inventory.root if inventory is not None else None
    if name == MCP_READ_PROJECTION_TOOL:
        structured, tool_error = (
            mcp_read_projection_payload(
                selected_inventory,
                default_root=default_root,
                requested_root=requested_root,
            ),
            None,
        )
    elif name == MCP_READ_SOURCE_TOOL:
        structured, tool_error = _mcp_read_source_payload(
            selected_inventory,
            arguments,
            default_root=default_root,
            requested_root=requested_root,
        )
    elif name == MCP_SEARCH_TOOL:
        structured, tool_error = _mcp_search_payload(
            selected_inventory,
            arguments,
            default_root=default_root,
            requested_root=requested_root,
        )
    else:
        structured, tool_error = _mcp_related_or_bundle_payload(
            selected_inventory,
            arguments,
            default_root=default_root,
            requested_root=requested_root,
        )
    if tool_error:
        return _tool_error_response(request_id, tool_error)
    return _result_response(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(structured, sort_keys=True, indent=2, ensure_ascii=True)}],
            "structuredContent": structured,
            "isError": False,
        },
    )


def _tool_argument_names(tool_name: str) -> set[str]:
    if tool_name == MCP_READ_PROJECTION_TOOL:
        return {"root"}
    if tool_name == MCP_READ_SOURCE_TOOL:
        return {"root", "path", "start", "limit"}
    if tool_name == MCP_SEARCH_TOOL:
        return {"root", "query", "mode", "limit"}
    if tool_name == MCP_RELATED_OR_BUNDLE_TOOL:
        return {"root", "path", "limit"}
    return {"root"}


def _selected_root_argument(inventory: Inventory | None, arguments: object, allowed_fields: set[str]) -> tuple[Path | str, str | None, str | None]:
    if not isinstance(arguments, dict):
        fallback = inventory.root if inventory is not None else ""
        return fallback, None, "Invalid arguments: MCP tools accept a JSON object."
    unknown = sorted(set(arguments) - allowed_fields)
    if unknown:
        fallback = inventory.root if inventory is not None else ""
        return fallback, None, f"Invalid arguments: unknown field(s): {', '.join(unknown)}."
    requested_root = arguments.get("root")
    if requested_root in (None, ""):
        if inventory is None:
            return "", None, "Invalid arguments: root is required when the MCP adapter is launched without a startup root."
        return inventory.root, None, None
    if not isinstance(requested_root, str):
        fallback = inventory.root if inventory is not None else ""
        return fallback, None, "Invalid arguments: root must be a string path when supplied."
    return requested_root, requested_root, None


def _mcp_read_source_payload(
    inventory: Inventory,
    arguments: dict[str, object],
    *,
    default_root: Path | None,
    requested_root: str | None,
) -> tuple[dict[str, object], str | None]:
    rel_path, error = _source_path_argument(arguments.get("path"))
    if error:
        return {}, error
    start, error = _bounded_int_argument(arguments, "start", 1, MCP_SOURCE_START_MAX)
    if error:
        return {}, error
    limit, error = _bounded_int_argument(arguments, "limit", MCP_SOURCE_READ_DEFAULT_LIMIT, MCP_SOURCE_READ_MAX_LIMIT)
    if error:
        return {}, error

    projection = build_projection(inventory)
    source = projection.source_by_path.get(rel_path)
    if source is None:
        return {}, f"Invalid path: {rel_path} is not an inventory-discovered projection source."
    if not source.readable:
        return {}, f"Invalid path: {rel_path} is not readable in the current projection."

    source_lines = source.content.splitlines()
    selected = source_lines[start - 1 : start - 1 + limit] if start <= len(source_lines) else []
    end_line = start + len(selected) - 1 if selected else start - 1
    root_selection = _root_selection_payload(inventory, default_root, requested_root)
    return {
        "tool": MCP_READ_SOURCE_TOOL,
        "root": _root_payload(inventory),
        "rootSelection": root_selection,
        "source": _source_record_payload(source),
        "range": {
            "start": start,
            "end": end_line,
            "limit": limit,
            "returned": len(selected),
            "lineCount": source.line_count,
        },
        "lines": [{"number": start + offset, "text": line} for offset, line in enumerate(selected)],
        "text": "\n".join(selected),
        "boundary": _mcp_tool_boundary(root_selection, source_bodies_included=True, source_body_mode="bounded-line-slice"),
    }, None


def _mcp_search_payload(
    inventory: Inventory,
    arguments: dict[str, object],
    *,
    default_root: Path | None,
    requested_root: str | None,
) -> tuple[dict[str, object], str | None]:
    query, error = _required_text_argument(arguments.get("query"), "query")
    if error:
        return {}, error
    mode, error = _search_mode_argument(arguments.get("mode", "all"))
    if error:
        return {}, error
    limit, error = _bounded_int_argument(arguments, "limit", MCP_SEARCH_DEFAULT_LIMIT, MCP_SEARCH_MAX_LIMIT)
    if error:
        return {}, error

    projection = build_projection(inventory)
    findings = [
        Finding(
            "info",
            "mcp-search-read-only",
            "MCP search reads current repo-visible sources and current generated index posture only; it does not refresh caches or write files",
        )
    ]
    results: list[dict[str, object]] = []
    if mode in {"all", "exact"}:
        _append_exact_search_results(results, projection, query, limit)
    if mode in {"all", "path"}:
        _append_path_search_results(results, projection, query, limit)
    if mode in {"all", "full-text"}:
        full_text_findings, full_text_results = source_verified_full_text_results(inventory, projection, query, limit)
        findings.extend(full_text_findings)
        for result in full_text_results:
            _append_result(
                results,
                {
                    "kind": "full-text",
                    "source": result.source_path,
                    "line": result.line_start,
                    "lineEnd": result.line_end,
                    "text": result.text,
                    "snippet": _trim(result.text, 240),
                    "sourceHash": _hash_prefix(result.source_hash),
                    "sourceRole": result.source_role,
                    "rank": result.rank,
                    "queryMode": result.query_mode,
                    "verification": "source-verified",
                },
                limit,
            )
    if not results:
        findings.append(Finding("info", "mcp-search-no-matches", "no source-verified MCP search matches found"))

    root_selection = _root_selection_payload(inventory, default_root, requested_root)
    return {
        "tool": MCP_SEARCH_TOOL,
        "root": _root_payload(inventory),
        "rootSelection": root_selection,
        "query": query,
        "mode": mode,
        "limit": limit,
        "results": results,
        "findings": [_finding_payload(finding) for finding in findings],
        "boundary": _mcp_tool_boundary(root_selection, source_bodies_included=True, source_body_mode="matched-line-snippets"),
    }, None


def _mcp_related_or_bundle_payload(
    inventory: Inventory,
    arguments: dict[str, object],
    *,
    default_root: Path | None,
    requested_root: str | None,
) -> tuple[dict[str, object], str | None]:
    rel_path, error = _source_path_argument(arguments.get("path"))
    if error:
        return {}, error
    limit, error = _bounded_int_argument(arguments, "limit", MCP_RELATED_DEFAULT_LIMIT, MCP_RELATED_MAX_LIMIT)
    if error:
        return {}, error

    projection = build_projection(inventory)
    source = projection.source_by_path.get(rel_path)
    if source is None:
        return {}, f"Invalid path: {rel_path} is not an inventory-discovered projection source."

    outbound = [record for record in projection.links if record.source == rel_path][:limit]
    inbound = [record for record in projection.links if record.target == rel_path][:limit]
    fan_in = [record for record in projection.fan_in if record.target == rel_path][:limit]
    relationship_nodes = [
        node
        for node in projection.relationship_nodes
        if node.source == rel_path or node.id == rel_path or node.id.startswith(f"{rel_path}#")
    ][:limit]
    relationship_edges = [
        edge
        for edge in projection.relationship_edges
        if edge.source == rel_path
        or edge.target == rel_path
        or edge.source_path == rel_path
        or edge.source.startswith(f"{rel_path}#")
        or edge.target.startswith(f"{rel_path}#")
    ][:limit]

    bundle_paths = {rel_path}
    bundle_paths.update(record.target for record in outbound if record.target in projection.source_by_path)
    bundle_paths.update(record.source for record in inbound if record.source in projection.source_by_path)
    bundle_paths.update(edge.source_path for edge in relationship_edges if edge.source_path in projection.source_by_path)
    bundle_paths.update(edge.target for edge in relationship_edges if edge.target in projection.source_by_path)
    bundle_sources = [_source_record_payload(projection.source_by_path[path]) for path in sorted(bundle_paths)[:limit]]

    root_selection = _root_selection_payload(inventory, default_root, requested_root)
    return {
        "tool": MCP_RELATED_OR_BUNDLE_TOOL,
        "root": _root_payload(inventory),
        "rootSelection": root_selection,
        "path": rel_path,
        "source": _source_record_payload(source),
        "outboundLinks": [_link_record_payload(record) for record in outbound],
        "inboundLinks": [_link_record_payload(record) for record in inbound],
        "fanIn": [_fan_in_record_payload(record) for record in fan_in],
        "relationshipNodes": [_relationship_node_payload(node) for node in relationship_nodes],
        "relationshipEdges": [_relationship_edge_payload(edge) for edge in relationship_edges],
        "bundleSources": bundle_sources,
        "boundary": _mcp_tool_boundary(root_selection, source_bodies_included=False, source_body_mode="source-records-only"),
    }, None


def _append_exact_search_results(results: list[dict[str, object]], projection: Projection, query: str, limit: int) -> None:
    for source in projection.sources:
        if not source.readable:
            continue
        for line_number, line in enumerate(source.content.splitlines(), start=1):
            if query not in line:
                continue
            if not _append_result(
                results,
                {
                    "kind": "exact",
                    "source": source.path,
                    "line": line_number,
                    "text": line,
                    "snippet": _trim(line, 240),
                    "sourceHash": _hash_prefix(source.content_hash),
                    "sourceRole": source.role,
                    "verification": "source-verified",
                },
                limit,
            ):
                return


def _append_path_search_results(results: list[dict[str, object]], projection: Projection, query: str, limit: int) -> None:
    for source in projection.sources:
        if query not in source.path:
            continue
        if not _append_result(
            results,
            {
                "kind": "path-source",
                "source": source.path,
                "line": 0,
                "sourceHash": _hash_prefix(source.content_hash),
                "sourceRole": source.role,
                "verification": "projection-source",
            },
            limit,
        ):
            return
    for record in projection.links:
        if query not in record.target and query not in record.source:
            continue
        if not _append_result(
            results,
            {
                "kind": "path-reference",
                "source": record.source,
                "line": record.line,
                "target": record.target,
                "status": record.status,
                "resolutionKind": record.resolution_kind,
                "verification": "projection-reference",
            },
            limit,
        ):
            return


def _append_result(results: list[dict[str, object]], result: dict[str, object], limit: int) -> bool:
    if len(results) >= limit:
        return False
    results.append(result)
    return True


def _source_path_argument(value: object) -> tuple[str, str | None]:
    if not isinstance(value, str) or not value.strip():
        return "", "Invalid arguments: path must be a non-empty root-relative string."
    raw = value.strip().strip("`").strip()
    if "\x00" in raw:
        return "", "Invalid arguments: path must not contain NUL characters."
    if re.match(r"^[A-Za-z]:[\\/]", raw) or raw.startswith(("/", "\\")):
        return "", "Invalid arguments: path must be root-relative, not absolute."
    clean = raw.replace("\\", "/").strip("/")
    if "#" in clean:
        return "", "Invalid arguments: path must be a root-relative source path without fragments."
    parts = clean.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return "", "Invalid arguments: path must not contain empty, current-directory, or parent traversal segments."
    return clean, None


def _required_text_argument(value: object, name: str) -> tuple[str, str | None]:
    if not isinstance(value, str) or not value:
        return "", f"Invalid arguments: {name} must be a non-empty string."
    return value, None


def _bounded_int_argument(arguments: dict[str, object], name: str, default: int, max_value: int) -> tuple[int, str | None]:
    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return default, f"Invalid arguments: {name} must be an integer."
    if value < 1:
        return default, f"Invalid arguments: {name} must be at least 1."
    if value > max_value:
        return default, f"Invalid arguments: {name} must be at most {max_value}."
    return value, None


def _search_mode_argument(value: object) -> tuple[str, str | None]:
    if value in (None, ""):
        return "all", None
    if not isinstance(value, str):
        return "", "Invalid arguments: mode must be a string."
    normalized = value.strip().casefold().replace("_", "-")
    if normalized == "fulltext":
        normalized = "full-text"
    if normalized not in {"all", "exact", "path", "full-text"}:
        return "", "Invalid arguments: mode must be one of all, exact, path, or full-text."
    return normalized, None


def _root_payload(inventory: Inventory) -> dict[str, object]:
    return {
        "path": str(inventory.root),
        "kind": inventory.root_kind,
        "classificationScope": "coarse-routing-only",
        "certifiesLifecycleValidity": False,
        "requiresRouteValidation": True,
    }


def _source_record_payload(source: object) -> dict[str, object]:
    return {
        "path": getattr(source, "path"),
        "role": getattr(source, "role"),
        "required": getattr(source, "required"),
        "present": getattr(source, "present"),
        "readable": getattr(source, "readable"),
        "lineCount": getattr(source, "line_count"),
        "byteCount": getattr(source, "byte_count"),
        "headingCount": getattr(source, "heading_count"),
        "linkCount": getattr(source, "link_count"),
        "contentHash": _hash_prefix(getattr(source, "content_hash")),
    }


def _link_record_payload(record: object) -> dict[str, object]:
    return {
        "source": getattr(record, "source"),
        "line": getattr(record, "line"),
        "target": getattr(record, "target"),
        "status": getattr(record, "status"),
        "resolutionKind": getattr(record, "resolution_kind"),
    }


def _fan_in_record_payload(record: object) -> dict[str, object]:
    return {
        "target": getattr(record, "target"),
        "inboundCount": getattr(record, "inbound_count"),
        "status": getattr(record, "status"),
        "sources": list(getattr(record, "sources")),
        "source": getattr(record, "source"),
    }


def _relationship_node_payload(node: object) -> dict[str, object]:
    return {
        "id": getattr(node, "id"),
        "kind": getattr(node, "kind"),
        "source": getattr(node, "source"),
        "title": getattr(node, "title"),
        "status": getattr(node, "status"),
        "route": getattr(node, "route"),
    }


def _relationship_edge_payload(edge: object) -> dict[str, object]:
    return {
        "source": getattr(edge, "source"),
        "target": getattr(edge, "target"),
        "relation": getattr(edge, "relation"),
        "status": getattr(edge, "status"),
        "sourcePath": getattr(edge, "source_path"),
        "line": getattr(edge, "line"),
    }


def _mcp_tool_boundary(
    root_selection: dict[str, object],
    *,
    source_bodies_included: bool,
    source_body_mode: str | None = None,
) -> dict[str, object]:
    mode = source_body_mode or ("source-content" if source_bodies_included else "none")
    return {
        "readOnly": True,
        "sourceBodiesIncluded": source_bodies_included,
        "sourceBodyMode": mode,
        "sourceBodyContract": _source_body_contract(mode),
        "sourceBodiesPersisted": False,
        "writesFiles": False,
        "refreshesGeneratedCache": False,
        "createsAdapterState": False,
        "authorizesLifecycle": False,
        "boundedByArguments": True,
        "rootSelection": root_selection,
    }


def _source_body_contract(mode: str) -> str:
    if mode == "none":
        return "no source bodies or snippets are copied into this payload"
    if mode == "bounded-line-slice":
        return "only the requested bounded source line slice is returned"
    if mode == "matched-line-snippets":
        return "only matched lines or bounded snippets from source-verified search results are returned"
    if mode == "source-records-only":
        return "only source records, links, fan-in, and relationship rows are returned without source bodies"
    return "source body inclusion is bounded by the tool arguments"


def _tool_error_response(request_id: object, text: str) -> dict[str, object]:
    return _result_response(
        request_id,
        {
            "content": [{"type": "text", "text": text}],
            "isError": True,
        },
    )


def _finding_payload(finding: Finding) -> dict[str, object]:
    payload: dict[str, object] = {
        "severity": finding.severity,
        "code": finding.code,
        "message": finding.message,
    }
    if finding.source is not None:
        payload["source"] = finding.source
    if finding.line is not None:
        payload["line"] = finding.line
    return payload


def _result_for(findings: list[Finding]) -> str:
    if any(finding.severity == "error" for finding in findings):
        return "error"
    if any(finding.severity == "warn" for finding in findings):
        return "warn"
    return "ok"


def _result_response(request_id: object, result: dict[str, object]) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: object, code: int, message: str, data: object | None = None) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _write_message(stdout: TextIO, message: dict[str, object]) -> None:
    stdout.write(json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    stdout.flush()
