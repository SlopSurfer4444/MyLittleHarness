from __future__ import annotations

import json
from pathlib import Path

from .inventory import Inventory
from .models import Finding
from .projection_artifacts import (
    ARTIFACT_DIR_REL,
    ARTIFACT_DIRTY_MARKER_NAME,
    CACHE_OPERATION_MARKER_NAME,
    INDEX_DIRTY_MARKER_NAME,
    artifact_dir,
)


MLHD_RUNTIME_SCHEMA = "mylittleharness.mlhd-runtime.v1"
MLHD_RUNTIME_DIR_REL = ".mylittleharness/runtime/mlhd"


def mlhd_runtime_findings(inventory: Inventory, code_prefix: str = "dashboard-mlhd") -> list[Finding]:
    posture = mlhd_runtime_payload(inventory)
    pulse = projection_pulse_payload(inventory)
    runtime_dir_rel = str(posture["runtime_dir"])
    findings = [
        Finding(
            "info",
            f"{code_prefix}-optional-runtime",
            (
                "mlhd runtime is optional cockpit support for live logs, process/session tracking, notifications, "
                "WebSocket updates, projection refresh cues, and attach/watch convenience"
            ),
            runtime_dir_rel,
        )
    ]
    status = posture["runtime_cache_status"]
    if status == "present":
        examples = ", ".join(posture["cache_file_examples"]) or "none"
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
