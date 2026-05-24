from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .inventory import Inventory
from .models import Finding
from .context_memory import (
    CONTEXT_MEMORY_DIR_REL,
    context_memory_capsule_findings,
    context_memory_capsule_payload,
    refresh_context_memory_capsule,
)
from .projection_artifacts import (
    ARTIFACT_DIR_REL,
    ARTIFACT_DIRTY_MARKER_NAME,
    CACHE_DIRTY_MARKER_NAMES,
    CACHE_OPERATION_MARKER_NAME,
    INDEX_DIRTY_MARKER_NAME,
    artifact_dir,
    projection_cache_dirty_changed_paths,
    projection_cache_dirty_quiet_period_pending,
    warm_projection_artifacts,
)
from .projection_index import warm_projection_index


MLHD_RUNTIME_SCHEMA = "mylittleharness.mlhd-runtime.v1"
MLHD_CONTROL_SCHEMA = "mylittleharness.mlhd-control-plane.v1"
MLHD_RUNTIME_DIR_REL = ".mylittleharness/runtime/mlhd"
MLHD_PID_FILE_NAME = "pid.json"
MLHD_LOCK_FILE_NAME = "lock.json"
MLHD_HEARTBEAT_FILE_NAME = "heartbeat.json"
MLHD_STATE_FILE_NAME = "state.json"
MLHD_EVENTS_FILE_NAME = "events.jsonl"
MLHD_LAST_RUN_ONCE_FILE_NAME = "last-run-once.json"
MLHD_PROJECTION_REFRESH_FILE_NAME = "projection-refresh.json"
MLHD_AUTOSTART_SCHEMA = "mylittleharness.mlhd-autostart.v1"
MLHD_AUTOSTART_FILE_NAME = "autostart.json"
MLHD_PROJECTION_QUIET_PERIOD_SECONDS = 1.0
MLHD_WORKER_INTERVAL_SECONDS = 2.0
_MLHD_WORKER_LOOP_CODE = "\n".join(
    [
        "import json, os, subprocess, sys, time",
        "from pathlib import Path",
        "root = Path(sys.argv[1])",
        "interval_seconds = float(sys.argv[2])",
        "quiet_period_seconds = sys.argv[3]",
        "runtime_dir = root / '.mylittleharness' / 'runtime' / 'mlhd'",
        "pid_path = runtime_dir / 'pid.json'",
        "lock_path = runtime_dir / 'lock.json'",
        "for _ in range(50):",
        "    if lock_path.exists() and pid_path.exists():",
        "        break",
        "    time.sleep(0.1)",
        "else:",
        "    sys.exit(0)",
        "runner = [sys.executable, '-m', 'mylittleharness', '--root', str(root), 'mlhd', 'run-once', '--apply', '--quiet-period-seconds', quiet_period_seconds]",
        "while True:",
        "    if not lock_path.exists() or not pid_path.exists():",
        "        break",
        "    subprocess.run(runner, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)",
        "    time.sleep(interval_seconds)",
    ]
)


def mlhd_control_sections(
    inventory: Inventory,
    action: str,
    *,
    dry_run: bool = False,
    apply: bool = False,
    quiet_period_seconds: float = MLHD_PROJECTION_QUIET_PERIOD_SECONDS,
) -> list[tuple[str, list[Finding]]]:
    findings = mlhd_control_findings(
        inventory,
        action,
        dry_run=dry_run,
        apply=apply,
        quiet_period_seconds=quiet_period_seconds,
    )
    return [("mlhd Control Plane", findings), ("Boundary", mlhd_control_boundary_findings())]


def mlhd_control_payload(
    inventory: Inventory,
    action: str,
    *,
    dry_run: bool = False,
    apply: bool = False,
    quiet_period_seconds: float = MLHD_PROJECTION_QUIET_PERIOD_SECONDS,
) -> dict[str, object]:
    state = inspect_mlhd_control_state(inventory)
    autostart_payload = _mlhd_autostart_manifest()
    return {
        "schema": MLHD_CONTROL_SCHEMA,
        "action": action,
        "mode": "apply" if apply else "dry-run" if dry_run else "status",
        "root": str(inventory.root),
        "runtime_dir": MLHD_RUNTIME_DIR_REL,
        "runtime_cache_status": state["runtime_cache_status"],
        "control_status": state["control_status"],
        "pid": state["pid"],
        "pid_status": state["pid_status"],
        "pid_file": f"{MLHD_RUNTIME_DIR_REL}/{MLHD_PID_FILE_NAME}",
        "lock_file": f"{MLHD_RUNTIME_DIR_REL}/{MLHD_LOCK_FILE_NAME}",
        "heartbeat_file": f"{MLHD_RUNTIME_DIR_REL}/{MLHD_HEARTBEAT_FILE_NAME}",
        "state_file": f"{MLHD_RUNTIME_DIR_REL}/{MLHD_STATE_FILE_NAME}",
        "events_file": f"{MLHD_RUNTIME_DIR_REL}/{MLHD_EVENTS_FILE_NAME}",
        "autostart_file": f"{MLHD_RUNTIME_DIR_REL}/{MLHD_AUTOSTART_FILE_NAME}",
        "autostart_status": state["autostart_status"],
        "network_listener_started": False,
        "autostart_installed": state["autostart_installed"],
        "autostart_manifest": autostart_payload,
        "background_worker_started": state["control_status"] == "running",
        "worker_interval_seconds": MLHD_WORKER_INTERVAL_SECONDS,
        "filesystem_watcher_started": False,
        "generated_projection_cache_may_refresh": action in {"start", "run-once"},
        "projection_quiet_period_seconds": quiet_period_seconds,
        "projection_pulse": projection_pulse_payload(inventory, quiet_period_seconds=quiet_period_seconds),
        "context_memory": context_memory_capsule_payload(inventory),
        "approves_lifecycle": False,
        "stores_provider_credentials": False,
        "durable_mutations_delegate_to_cli": True,
    }


def mlhd_control_findings(
    inventory: Inventory,
    action: str,
    *,
    dry_run: bool = False,
    apply: bool = False,
    quiet_period_seconds: float = MLHD_PROJECTION_QUIET_PERIOD_SECONDS,
) -> list[Finding]:
    if action == "status":
        return _mlhd_status_findings(inventory)
    if action == "doctor":
        return _mlhd_doctor_findings(inventory)
    if dry_run:
        return _mlhd_dry_run_findings(inventory, action, quiet_period_seconds=quiet_period_seconds)
    if apply:
        return _mlhd_apply_findings(inventory, action, quiet_period_seconds=quiet_period_seconds)
    return [
        Finding(
            "error",
            "mlhd-control-mode-required",
            f"mlhd {action} mutates disposable runtime state and requires --dry-run or --apply",
            MLHD_RUNTIME_DIR_REL,
        )
    ]


def mlhd_control_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "mlhd-control-runtime-boundary",
            (
                "mlhd control-plane writes are limited to disposable runtime markers and optional generated projection "
                "warm-cache/source-bound context capsule output; repo-visible lifecycle, roadmap, source, archive, Git, "
                "provider, and release authority stay unchanged"
            ),
            MLHD_RUNTIME_DIR_REL,
        ),
        Finding(
            "info",
            "mlhd-control-no-hidden-runtime",
            (
                "mlhd start opens no network listener and creates no filesystem watcher; it starts one local polling "
                "worker for disposable projection cache ticks, while install writes only a root-local autostart manifest"
            ),
            MLHD_RUNTIME_DIR_REL,
        ),
        Finding(
            "info",
            "mlhd-projection-cache-boundary",
            "mlhd start/run-once may refresh only the disposable generated projection cache after dirty markers are quiet",
            ARTIFACT_DIR_REL,
        ),
        Finding(
            "info",
            "mlhd-context-memory-boundary",
            "mlhd run-once may refresh generated source-bound context capsules, but capsules stay non-authority and replayable from source refs",
            CONTEXT_MEMORY_DIR_REL,
        ),
    ]


def inspect_mlhd_control_state(inventory: Inventory) -> dict[str, object]:
    root = inventory.root
    runtime_dir = root / MLHD_RUNTIME_DIR_REL
    runtime_status = _runtime_cache_status(runtime_dir)
    pid_payload = _read_runtime_json(root, MLHD_PID_FILE_NAME)
    lock_payload = _read_runtime_json(root, MLHD_LOCK_FILE_NAME)
    heartbeat_payload = _read_runtime_json(root, MLHD_HEARTBEAT_FILE_NAME)
    state_payload = _read_runtime_json(root, MLHD_STATE_FILE_NAME)
    autostart_payload = _read_runtime_json(root, MLHD_AUTOSTART_FILE_NAME)
    refresh_payload = _read_runtime_json(root, MLHD_PROJECTION_REFRESH_FILE_NAME)
    pid = _payload_pid(pid_payload)
    pid_status = "absent"
    if pid:
        pid_status = "alive" if _pid_is_alive(pid) else "stale"
    if runtime_status == "invalid":
        control_status = "invalid"
    elif pid_status == "alive" and lock_payload:
        control_status = "running"
    elif pid_status == "stale":
        control_status = "stale"
    elif state_payload.get("status") == "stopped":
        control_status = "stopped"
    elif state_payload.get("last_action") == "run-once":
        control_status = "idle"
    elif runtime_status == "present":
        control_status = "idle"
    else:
        control_status = "absent"
    autostart_status = _autostart_status(runtime_status, autostart_payload)
    return {
        "runtime_cache_status": runtime_status,
        "runtime_dir": MLHD_RUNTIME_DIR_REL,
        "control_status": control_status,
        "pid": pid,
        "pid_status": pid_status,
        "has_lock": bool(lock_payload),
        "autostart_installed": autostart_status == "installed",
        "autostart_status": autostart_status,
        "last_action": str(state_payload.get("last_action") or heartbeat_payload.get("action") or ""),
        "heartbeat_at_utc": str(heartbeat_payload.get("heartbeat_at_utc") or ""),
        "projection_refresh_status": str(refresh_payload.get("status") or ""),
        "last_successful_refresh_utc": str(refresh_payload.get("last_successful_refresh_utc") or ""),
        "last_failed_refresh_utc": str(refresh_payload.get("last_failed_refresh_utc") or ""),
        "projection_stale_reason": str(refresh_payload.get("stale_reason") or ""),
    }


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
        if posture["autostart_installed"]:
            findings.append(
                Finding(
                    "info",
                    f"{code_prefix}-autostart-installed",
                    (
                        "root-local mlhd autostart manifest is installed; it is disposable runtime evidence only "
                        "and does not register an OS startup entry"
                    ),
                    str(posture["autostart_file"]),
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
                "info" if pulse["status"] in {"idle", "warmable", "cooling-down"} else "warn",
                f"{code_prefix}-projection-pulse",
                (
                    f"projection pulse status={pulse['status']}; dirty_since={pulse['dirty_since_utc'] or '<none>'}; "
                    f"last_operation={pulse['operation'] or '<none>'}; "
                    f"last_refresh={pulse['last_refresh_status'] or '<none>'}; optional warm-cache ticks cannot write lifecycle authority"
                ),
                ARTIFACT_DIR_REL,
            ),
        ]
    )
    findings.extend(context_memory_capsule_findings(inventory, f"{code_prefix}-context-memory"))
    return findings


def mlhd_runtime_payload(inventory: Inventory) -> dict[str, object]:
    runtime_dir = inventory.root / MLHD_RUNTIME_DIR_REL
    status = _runtime_cache_status(runtime_dir)
    cache_files = _runtime_cache_files(inventory.root, runtime_dir) if status == "present" else []
    state = inspect_mlhd_control_state(inventory)
    return {
        "schema": MLHD_RUNTIME_SCHEMA,
        "runtime_dir": MLHD_RUNTIME_DIR_REL,
        "runtime_cache_status": status,
        "runtime_dir_exists": runtime_dir.exists(),
        "cache_file_count": len(cache_files),
        "cache_file_examples": cache_files[:10],
        "autostart_file": f"{MLHD_RUNTIME_DIR_REL}/{MLHD_AUTOSTART_FILE_NAME}",
        "autostart_installed": state["autostart_installed"],
        "autostart_status": state["autostart_status"],
        "disposable_cache": True,
        "network_listener_started": False,
        "default_bind_host": "127.0.0.1",
        "durable_mutations_delegate_to_cli": True,
        "stores_provider_credentials": False,
        "approves_lifecycle": False,
        "projection_pulse": projection_pulse_payload(inventory, quiet_period_seconds=MLHD_PROJECTION_QUIET_PERIOD_SECONDS),
        "context_memory": context_memory_capsule_payload(inventory),
    }


def projection_pulse_payload(
    inventory: Inventory,
    *,
    quiet_period_seconds: float = MLHD_PROJECTION_QUIET_PERIOD_SECONDS,
) -> dict[str, object]:
    dirty_payloads = [_read_json_marker(inventory.root, ARTIFACT_DIRTY_MARKER_NAME), _read_json_marker(inventory.root, INDEX_DIRTY_MARKER_NAME)]
    dirty_payloads = [payload for payload in dirty_payloads if payload]
    operation_payload = _read_json_marker(inventory.root, CACHE_OPERATION_MARKER_NAME)
    dirty_since_values = [str(payload.get("dirty_since_utc") or "") for payload in dirty_payloads if isinstance(payload, dict)]
    changed_paths = projection_cache_dirty_changed_paths(inventory.root)
    quiet_pending, quiet_until_utc = projection_cache_dirty_quiet_period_pending(
        inventory.root,
        CACHE_DIRTY_MARKER_NAMES,
        quiet_period_seconds,
    )
    refresh_payload = _read_runtime_json(inventory.root, MLHD_PROJECTION_REFRESH_FILE_NAME)
    status = (
        "updating-or-interrupted"
        if operation_payload
        else "cooling-down"
        if dirty_payloads and quiet_pending
        else "warmable"
        if dirty_payloads
        else "idle"
    )
    return {
        "schema": "mylittleharness.projection-pulse.v1",
        "status": status,
        "dirty": bool(dirty_payloads),
        "dirty_since_utc": sorted(value for value in dirty_since_values if value)[:1][0] if any(dirty_since_values) else "",
        "dirty_marker_count": len(dirty_payloads),
        "changed_path_count": len(changed_paths),
        "changed_path_examples": list(changed_paths[:10]),
        "quiet_period_seconds": quiet_period_seconds,
        "quiet_period_elapsed": bool(dirty_payloads) and not quiet_pending and not operation_payload,
        "quiet_until_utc": quiet_until_utc,
        "operation": str(operation_payload.get("operation") or "") if isinstance(operation_payload, dict) else "",
        "operation_created_at_utc": str(operation_payload.get("created_at_utc") or "") if isinstance(operation_payload, dict) else "",
        "last_refresh_status": str(refresh_payload.get("status") or ""),
        "last_successful_refresh_utc": str(refresh_payload.get("last_successful_refresh_utc") or ""),
        "last_failed_refresh_utc": str(refresh_payload.get("last_failed_refresh_utc") or ""),
        "stale_reason": str(refresh_payload.get("stale_reason") or ""),
        "owner_command": "mylittleharness --root <root> mlhd run-once --apply",
        "warm_cache_command": "mylittleharness --root <root> projection --warm-cache --target all",
        "manual_recovery_command": "mylittleharness --root <root> projection --warm-cache --target all",
        "next_safe_command": "mylittleharness --root <root> mlhd run-once --dry-run",
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


def _mlhd_status_findings(inventory: Inventory) -> list[Finding]:
    state = inspect_mlhd_control_state(inventory)
    findings = [
        Finding(
            "info" if state["control_status"] != "invalid" else "warn",
            "mlhd-status",
            (
                f"control_status={state['control_status']}; runtime_cache_status={state['runtime_cache_status']}; "
                f"pid_status={state['pid_status']}; pid={state['pid'] or '<none>'}; "
                f"autostart_status={state['autostart_status']}; "
                f"heartbeat_at_utc={state['heartbeat_at_utc'] or '<none>'}; "
                f"projection_refresh_status={state['projection_refresh_status'] or '<none>'}; "
                f"last_success={state['last_successful_refresh_utc'] or '<none>'}; "
                f"last_failure={state['last_failed_refresh_utc'] or '<none>'}; "
                f"stale_reason={state['projection_stale_reason'] or '<none>'}"
            ),
            MLHD_RUNTIME_DIR_REL,
        )
    ]
    if state["pid_status"] == "stale":
        findings.append(
            Finding(
                "warn",
                "mlhd-stale-pid",
                "stale pid file detected; `mlhd start --apply` or `mlhd stop --apply` can recover disposable runtime markers",
                f"{MLHD_RUNTIME_DIR_REL}/{MLHD_PID_FILE_NAME}",
            )
        )
    return findings


def _mlhd_doctor_findings(inventory: Inventory) -> list[Finding]:
    state = inspect_mlhd_control_state(inventory)
    severity = "warn" if state["runtime_cache_status"] == "invalid" else "info"
    findings = [
        Finding(
            severity,
            "mlhd-doctor",
            (
                f"runtime_cache_status={state['runtime_cache_status']}; control_status={state['control_status']}; "
                f"autostart_status={state['autostart_status']}; pid_status={state['pid_status']}; "
                f"projection_refresh_status={state['projection_refresh_status'] or '<none>'}; "
                f"last_success={state['last_successful_refresh_utc'] or '<none>'}; "
                f"last_failure={state['last_failed_refresh_utc'] or '<none>'}; "
                "daemon fallback is clean when runtime cache is absent"
            ),
            MLHD_RUNTIME_DIR_REL,
        ),
        Finding(
            "info",
            "mlhd-doctor-autostart",
            (
                "autostart install state is stored as a root-local manifest with <root> command templates; "
                "moving the repository does not require rewriting the manifest"
            ),
            f"{MLHD_RUNTIME_DIR_REL}/{MLHD_AUTOSTART_FILE_NAME}",
        ),
        Finding(
            "info",
            "mlhd-doctor-authority-boundary",
            (
                "doctor is read-only and cannot approve lifecycle movement, roadmap status, archive, Git, release, "
                "provider routing, or generated cache truth"
            ),
            MLHD_RUNTIME_DIR_REL,
        ),
    ]
    if state["autostart_status"] == "absent":
        findings.append(
            Finding(
                "info",
                "mlhd-doctor-autostart-absent",
                "`mlhd install --dry-run` previews the root-local autostart manifest without writing files",
                f"{MLHD_RUNTIME_DIR_REL}/{MLHD_AUTOSTART_FILE_NAME}",
            )
        )
    elif state["autostart_status"] != "installed":
        findings.append(
            Finding(
                "warn",
                "mlhd-doctor-autostart-invalid",
                "autostart manifest is present but not recognized; `mlhd uninstall --apply` can clear the root-local marker",
                f"{MLHD_RUNTIME_DIR_REL}/{MLHD_AUTOSTART_FILE_NAME}",
            )
        )
    return findings


def _mlhd_dry_run_findings(
    inventory: Inventory,
    action: str,
    *,
    quiet_period_seconds: float = MLHD_PROJECTION_QUIET_PERIOD_SECONDS,
) -> list[Finding]:
    state = inspect_mlhd_control_state(inventory)
    if state["runtime_cache_status"] == "invalid":
        return [_invalid_runtime_finding(action)]
    targets = ", ".join(_action_targets(action))
    findings = [
        Finding(
            "info",
            f"mlhd-{action}-dry-run",
            f"would update disposable mlhd runtime target(s): {targets}; no files were written",
            MLHD_RUNTIME_DIR_REL,
        )
    ]
    if action == "run-once":
        findings.extend(_mlhd_projection_autorefresh_preview_findings(inventory, quiet_period_seconds))
    if action == "install":
        findings.append(
            Finding(
                "info",
                "mlhd-install-root-move-preview",
                "would write a deterministic root-local autostart manifest using <root> placeholders, not an absolute root path",
                f"{MLHD_RUNTIME_DIR_REL}/{MLHD_AUTOSTART_FILE_NAME}",
            )
        )
    if action == "start" and state["pid_status"] == "stale":
        findings.append(
            Finding(
                "info",
                "mlhd-start-stale-pid-recovery-preview",
                "would remove stale pid/lock markers before writing fresh start state",
                f"{MLHD_RUNTIME_DIR_REL}/{MLHD_PID_FILE_NAME}",
            )
        )
    if action == "start":
        findings.append(
            Finding(
                "info",
                "mlhd-start-worker-preview",
                (
                    "would launch one local background polling worker for mlhd run-once projection refresh ticks; "
                    f"interval_seconds={MLHD_WORKER_INTERVAL_SECONDS:g}; no listener, watcher, OS autostart entry, or lifecycle authority"
                ),
                MLHD_RUNTIME_DIR_REL,
            )
        )
    return findings


def _mlhd_apply_findings(
    inventory: Inventory,
    action: str,
    *,
    quiet_period_seconds: float = MLHD_PROJECTION_QUIET_PERIOD_SECONDS,
) -> list[Finding]:
    runtime_dir = inventory.root / MLHD_RUNTIME_DIR_REL
    if _runtime_cache_status(runtime_dir) == "invalid":
        return [_invalid_runtime_finding(action)]
    if action == "start":
        return _apply_mlhd_start(inventory, quiet_period_seconds=quiet_period_seconds)
    if action == "stop":
        return _apply_mlhd_stop(inventory)
    if action == "run-once":
        return _apply_mlhd_run_once(inventory, quiet_period_seconds=quiet_period_seconds)
    if action == "install":
        return _apply_mlhd_install(inventory)
    if action == "uninstall":
        return _apply_mlhd_uninstall(inventory)
    return [Finding("error", "mlhd-control-action-unknown", f"unknown mlhd action: {action}", MLHD_RUNTIME_DIR_REL)]


def _spawn_mlhd_worker(root: Path, *, quiet_period_seconds: float) -> subprocess.Popen:
    env = dict(os.environ)
    package_src = Path(__file__).resolve().parents[1]
    existing_pythonpath = env.get("PYTHONPATH", "")
    pythonpath_parts = [str(package_src)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    kwargs: dict[str, object] = {
        "cwd": str(root.parent),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        if creationflags:
            kwargs["creationflags"] = creationflags
    return subprocess.Popen(_mlhd_worker_command(root, quiet_period_seconds=quiet_period_seconds), **kwargs)


def _mlhd_worker_command(root: Path, *, quiet_period_seconds: float) -> list[str]:
    return [
        sys.executable,
        "-c",
        _MLHD_WORKER_LOOP_CODE,
        str(root),
        f"{MLHD_WORKER_INTERVAL_SECONDS:g}",
        f"{quiet_period_seconds:g}",
    ]


def _mlhd_worker_command_template(*, quiet_period_seconds: float) -> list[str]:
    return [
        "<python>",
        "-c",
        "<mlhd-background-projection-refresh-loop>",
        "<root>",
        f"{MLHD_WORKER_INTERVAL_SECONDS:g}",
        f"{quiet_period_seconds:g}",
    ]


def _apply_mlhd_start(
    inventory: Inventory,
    *,
    quiet_period_seconds: float = MLHD_PROJECTION_QUIET_PERIOD_SECONDS,
) -> list[Finding]:
    state = inspect_mlhd_control_state(inventory)
    runtime_dir = _ensure_runtime_dir(inventory.root)
    findings: list[Finding] = []
    if state["control_status"] == "running" and state["pid_status"] == "alive":
        return [
            Finding(
                "info",
                "mlhd-start-already-running",
                (
                    f"mlhd background worker is already running; pid={state['pid']}; "
                    "no new worker, listener, watcher, autostart entry, lifecycle mutation, or source mutation was created"
                ),
                MLHD_RUNTIME_DIR_REL,
            )
        ]
    if state["pid_status"] == "stale":
        _remove_runtime_file(inventory.root, MLHD_PID_FILE_NAME)
        _remove_runtime_file(inventory.root, MLHD_LOCK_FILE_NAME)
        findings.append(
            Finding(
                "info",
                "mlhd-start-stale-pid-recovered",
                "removed stale pid/lock markers before writing fresh explicit start state",
                f"{MLHD_RUNTIME_DIR_REL}/{MLHD_PID_FILE_NAME}",
            )
        )
    try:
        worker = _spawn_mlhd_worker(inventory.root, quiet_period_seconds=quiet_period_seconds)
    except OSError as exc:
        return [
            *findings,
            Finding(
                "error",
                "mlhd-start-worker-spawn-failed",
                f"failed to launch local mlhd projection refresh worker; disposable runtime state remains authoritative only as evidence: {exc}",
                MLHD_RUNTIME_DIR_REL,
            ),
        ]
    now = _utc_now()
    pid = int(worker.pid)
    worker_command_template = _mlhd_worker_command_template(quiet_period_seconds=quiet_period_seconds)
    _write_runtime_json(
        inventory.root,
        MLHD_PID_FILE_NAME,
        {
            "schema": MLHD_CONTROL_SCHEMA,
            "pid": pid,
            "started_at_utc": now,
            "kind": "background-worker",
            "worker_interval_seconds": MLHD_WORKER_INTERVAL_SECONDS,
            "projection_quiet_period_seconds": quiet_period_seconds,
            "command_template": worker_command_template,
        },
    )
    _write_runtime_json(
        inventory.root,
        MLHD_LOCK_FILE_NAME,
        {
            "schema": MLHD_CONTROL_SCHEMA,
            "pid": pid,
            "locked_at_utc": now,
            "root": str(inventory.root),
            "kind": "background-worker-lock",
        },
    )
    _write_runtime_json(inventory.root, MLHD_HEARTBEAT_FILE_NAME, _heartbeat_payload("start", "running", pid, now))
    state_payload = _state_payload("running", "start", pid, now)
    state_payload["worker_interval_seconds"] = MLHD_WORKER_INTERVAL_SECONDS
    state_payload["projection_quiet_period_seconds"] = quiet_period_seconds
    state_payload["worker_command_template"] = worker_command_template
    _write_runtime_json(inventory.root, MLHD_STATE_FILE_NAME, state_payload)
    _append_event(runtime_dir, "start", "running", pid, now)
    findings.append(
        Finding(
            "info",
            "mlhd-start-apply",
            (
                "launched one local background polling worker and wrote root-local pid, lock, heartbeat, state, and event log files under "
                ".mylittleharness/runtime/mlhd; the worker runs mlhd run-once projection refresh ticks without starting a listener, "
                "filesystem watcher, autostart entry, lifecycle mutation, or source mutation"
            ),
            MLHD_RUNTIME_DIR_REL,
        )
    )
    return findings


def _apply_mlhd_stop(inventory: Inventory) -> list[Finding]:
    runtime_dir = _ensure_runtime_dir(inventory.root)
    now = _utc_now()
    previous = inspect_mlhd_control_state(inventory)
    _remove_runtime_file(inventory.root, MLHD_PID_FILE_NAME)
    _remove_runtime_file(inventory.root, MLHD_LOCK_FILE_NAME)
    _write_runtime_json(inventory.root, MLHD_HEARTBEAT_FILE_NAME, _heartbeat_payload("stop", "stopped", 0, now))
    _write_runtime_json(inventory.root, MLHD_STATE_FILE_NAME, _state_payload("stopped", "stop", 0, now))
    _append_event(runtime_dir, "stop", "stopped", 0, now)
    return [
        Finding(
            "info",
            "mlhd-stop-apply",
            (
                f"cleared disposable pid/lock markers and wrote stopped heartbeat/state; previous_status={previous['control_status']}; "
                "repo-visible lifecycle and source files were not changed"
            ),
            MLHD_RUNTIME_DIR_REL,
        )
    ]


def _apply_mlhd_run_once(
    inventory: Inventory,
    *,
    quiet_period_seconds: float = MLHD_PROJECTION_QUIET_PERIOD_SECONDS,
) -> list[Finding]:
    runtime_dir = _ensure_runtime_dir(inventory.root)
    now = _utc_now()
    pid = os.getpid()
    projection_findings = _mlhd_projection_autorefresh_apply_findings(inventory, quiet_period_seconds)
    refresh_status = _projection_autorefresh_status(projection_findings)
    context_memory_findings, context_memory_payload = refresh_context_memory_capsule(inventory, trigger="mlhd-run-once", now=now)
    _write_projection_refresh_state(inventory.root, refresh_status, projection_findings, now)
    run_once_payload = _state_payload("idle", "run-once", pid, now)
    run_once_payload["projection_refresh_status"] = refresh_status
    run_once_payload["context_memory_status"] = str(context_memory_payload.get("status") or "current")
    run_once_payload["context_memory_capsule_id"] = str(context_memory_payload.get("capsule_id") or "")
    run_once_payload["quiet_period_seconds"] = quiet_period_seconds
    _write_runtime_json(inventory.root, MLHD_LAST_RUN_ONCE_FILE_NAME, run_once_payload)
    _write_runtime_json(inventory.root, MLHD_HEARTBEAT_FILE_NAME, _heartbeat_payload("run-once", "idle", pid, now))
    _write_runtime_json(inventory.root, MLHD_STATE_FILE_NAME, _state_payload("idle", "run-once", pid, now))
    _append_event(runtime_dir, "run-once", "idle", pid, now)
    return [
        Finding(
            "info",
            "mlhd-run-once-apply",
            (
                "ran one foreground mlhd control-plane tick and wrote heartbeat/state/event evidence under the disposable "
                "runtime directory; optional projection warm-cache and source-bound context capsule stayed inside generated "
                "cache/context boundaries; no watcher, listener, autostart entry, lifecycle mutation, or source mutation was created"
            ),
            MLHD_RUNTIME_DIR_REL,
        ),
        *projection_findings,
        *context_memory_findings,
    ]


def _apply_mlhd_install(inventory: Inventory) -> list[Finding]:
    _ensure_runtime_dir(inventory.root)
    existing = _read_runtime_json(inventory.root, MLHD_AUTOSTART_FILE_NAME)
    manifest = _mlhd_autostart_manifest()
    if existing != manifest:
        _write_runtime_json(inventory.root, MLHD_AUTOSTART_FILE_NAME, manifest)
    return [
        Finding(
            "info",
            "mlhd-install-apply",
            (
                "installed deterministic root-local mlhd autostart manifest under disposable runtime state; "
                "no OS startup entry, listener, watcher, lifecycle mutation, source mutation, Git mutation, or provider state was created"
            ),
            f"{MLHD_RUNTIME_DIR_REL}/{MLHD_AUTOSTART_FILE_NAME}",
        ),
        Finding(
            "info",
            "mlhd-install-root-move-ready",
            "manifest uses <root> command templates and is reusable after the repository directory is moved",
            f"{MLHD_RUNTIME_DIR_REL}/{MLHD_AUTOSTART_FILE_NAME}",
        ),
    ]


def _apply_mlhd_uninstall(inventory: Inventory) -> list[Finding]:
    existed = bool(_read_runtime_json(inventory.root, MLHD_AUTOSTART_FILE_NAME))
    _remove_runtime_file(inventory.root, MLHD_AUTOSTART_FILE_NAME)
    return [
        Finding(
            "info",
            "mlhd-uninstall-apply",
            (
                f"removed root-local mlhd autostart manifest if present; was_installed={str(existed).lower()}; "
                "runtime cache remains disposable and repo-visible lifecycle authority was not changed"
            ),
            f"{MLHD_RUNTIME_DIR_REL}/{MLHD_AUTOSTART_FILE_NAME}",
        )
    ]


def _mlhd_projection_autorefresh_preview_findings(inventory: Inventory, quiet_period_seconds: float) -> list[Finding]:
    pulse = projection_pulse_payload(inventory, quiet_period_seconds=quiet_period_seconds)
    status = str(pulse["status"])
    if status == "updating-or-interrupted":
        message = (
            "would defer projection warm-cache because a generated cache operation marker is present; "
            "old-good cache remains the only advisory cache input"
        )
    elif status == "cooling-down":
        message = (
            "would defer projection warm-cache until dirty markers are quiet; "
            f"quiet_period_seconds={quiet_period_seconds:g}; quiet_until_utc={pulse['quiet_until_utc']}"
        )
    elif status == "warmable":
        message = (
            "would run one projection warm-cache pulse for dirty generated-cache markers; "
            f"changed_paths={pulse['changed_path_count']}; generated cache only"
        )
    else:
        message = "would run one projection warm-cache pulse; no dirty marker currently requires refresh"
    return [Finding("info", "mlhd-projection-autorefresh-preview", message, ARTIFACT_DIR_REL)]


def _mlhd_projection_autorefresh_apply_findings(inventory: Inventory, quiet_period_seconds: float) -> list[Finding]:
    pulse = projection_pulse_payload(inventory, quiet_period_seconds=quiet_period_seconds)
    if pulse["status"] == "updating-or-interrupted":
        return [
            Finding(
                "info",
                "mlhd-projection-autorefresh-deferred",
                (
                    "mlhd run-once deferred projection warm-cache because a generated cache operation marker is present; "
                    "old-good cache remains advisory and source files remain authoritative"
                ),
                ARTIFACT_DIR_REL,
            )
        ]

    refresh_findings = warm_projection_artifacts(inventory, quiet_period_seconds=quiet_period_seconds) + warm_projection_index(
        inventory,
        quiet_period_seconds=quiet_period_seconds,
    )
    status = _projection_autorefresh_status(refresh_findings)
    severity = "warn" if status == "degraded" else "info"
    return [
        Finding(
            severity,
            f"mlhd-projection-autorefresh-{status}",
            (
                f"mlhd run-once projection pulse status={status}; "
                f"quiet_period_seconds={quiet_period_seconds:g}; generated cache only; "
                "lifecycle, roadmap, source, archive, Git, provider, and release authority remain unchanged"
            ),
            ARTIFACT_DIR_REL,
        ),
        *refresh_findings,
    ]


def _projection_autorefresh_status(findings: list[Finding]) -> str:
    codes = {finding.code for finding in findings}
    if any(finding.severity in {"warn", "error"} for finding in findings):
        return "degraded"
    if "mlhd-projection-autorefresh-deferred" in codes or any(str(code).endswith("-warm-cache-deferred") for code in codes):
        return "deferred"
    if "projection-artifact-warm-cache" in codes or "projection-index-warm-cache" in codes:
        return "refreshed"
    return "current"


def _write_projection_refresh_state(root: Path, status: str, findings: list[Finding], now: str) -> None:
    previous = _read_runtime_json(root, MLHD_PROJECTION_REFRESH_FILE_NAME)
    finding_codes = [finding.code for finding in findings]
    stale_reason = _projection_refresh_stale_reason(findings)
    payload = {
        "schema": MLHD_CONTROL_SCHEMA,
        "status": status,
        "updated_at_utc": now,
        "last_successful_refresh_utc": previous.get("last_successful_refresh_utc", ""),
        "last_failed_refresh_utc": previous.get("last_failed_refresh_utc", ""),
        "stale_reason": stale_reason,
        "finding_codes": finding_codes,
        "authority": "disposable mlhd runtime ledger only; generated projection cache is advisory and source files remain authoritative",
    }
    if status in {"current", "refreshed"}:
        payload["last_successful_refresh_utc"] = now
    if status == "degraded":
        payload["last_failed_refresh_utc"] = now
    _write_runtime_json(root, MLHD_PROJECTION_REFRESH_FILE_NAME, payload)


def _projection_refresh_stale_reason(findings: list[Finding]) -> str:
    for finding in findings:
        if finding.severity in {"warn", "error"}:
            return finding.code
    for finding in findings:
        if finding.code in {
            "projection-artifact-dirty",
            "projection-index-dirty",
            "projection-artifact-missing",
            "projection-index-missing",
        }:
            return finding.code
    return "none"


def _invalid_runtime_finding(action: str) -> Finding:
    return Finding(
        "error",
        f"mlhd-{action}-runtime-invalid",
        "mlhd runtime path is a symlink or non-directory; refusing to write disposable control-plane state",
        MLHD_RUNTIME_DIR_REL,
    )


def _action_targets(action: str) -> tuple[str, ...]:
    if action == "start":
        names = (MLHD_PID_FILE_NAME, MLHD_LOCK_FILE_NAME, MLHD_HEARTBEAT_FILE_NAME, MLHD_STATE_FILE_NAME, MLHD_EVENTS_FILE_NAME)
    elif action == "stop":
        names = (MLHD_PID_FILE_NAME, MLHD_LOCK_FILE_NAME, MLHD_HEARTBEAT_FILE_NAME, MLHD_STATE_FILE_NAME, MLHD_EVENTS_FILE_NAME)
    elif action == "install":
        names = (MLHD_AUTOSTART_FILE_NAME,)
    elif action == "uninstall":
        names = (MLHD_AUTOSTART_FILE_NAME,)
    elif action == "run-once":
        names = (
            MLHD_LAST_RUN_ONCE_FILE_NAME,
            MLHD_PROJECTION_REFRESH_FILE_NAME,
            MLHD_HEARTBEAT_FILE_NAME,
            MLHD_STATE_FILE_NAME,
            MLHD_EVENTS_FILE_NAME,
        )
    else:
        names = ()
    targets = tuple(f"{MLHD_RUNTIME_DIR_REL}/{name}" for name in names)
    if action == "run-once":
        return (*targets, f"optional {ARTIFACT_DIR_REL}", f"optional {CONTEXT_MEMORY_DIR_REL}")
    return targets


def _mlhd_autostart_manifest() -> dict[str, object]:
    return {
        "schema": MLHD_AUTOSTART_SCHEMA,
        "kind": "root-local-autostart-manifest",
        "root_strategy": "invocation-root-placeholder",
        "root": "<root>",
        "command_template": ["mylittleharness", "--root", "<root>", "mlhd", "start", "--apply"],
        "tick_command_template": ["mylittleharness", "--root", "<root>", "mlhd", "run-once", "--apply"],
        "doctor_command_template": ["mylittleharness", "--root", "<root>", "mlhd", "doctor"],
        "uninstall_command_template": ["mylittleharness", "--root", "<root>", "mlhd", "uninstall", "--apply"],
        "runtime_dir": MLHD_RUNTIME_DIR_REL,
        "worker_interval_seconds": MLHD_WORKER_INTERVAL_SECONDS,
        "os_autostart_entry_created": False,
        "network_listener_started": False,
        "filesystem_watcher_started": False,
        "stores_provider_credentials": False,
        "approves_lifecycle": False,
        "authority": "disposable runtime manifest only; repo-visible route files remain authority",
    }


def _autostart_status(runtime_status: str, payload: dict[str, object]) -> str:
    if runtime_status == "invalid":
        return "invalid-runtime"
    if not payload:
        return "absent"
    if payload.get("schema") == MLHD_AUTOSTART_SCHEMA and payload.get("root") == "<root>":
        return "installed"
    return "invalid"


def _ensure_runtime_dir(root: Path) -> Path:
    runtime_dir = root / MLHD_RUNTIME_DIR_REL
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def _write_runtime_json(root: Path, name: str, payload: dict[str, object]) -> None:
    path = root / MLHD_RUNTIME_DIR_REL / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _append_event(runtime_dir: Path, event: str, status: str, pid: int, now: str) -> None:
    payload = {"schema": MLHD_CONTROL_SCHEMA, "event": event, "status": status, "pid": pid, "created_at_utc": now}
    with (runtime_dir / MLHD_EVENTS_FILE_NAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _remove_runtime_file(root: Path, name: str) -> None:
    path = root / MLHD_RUNTIME_DIR_REL / name
    if path.is_file() and not path.is_symlink():
        path.unlink()


def _read_runtime_json(root: Path, name: str) -> dict[str, object]:
    return _read_json_file(root / MLHD_RUNTIME_DIR_REL / name)


def _read_json_file(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _payload_pid(payload: dict[str, object]) -> int:
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        return 0
    return pid if pid > 0 else 0


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_pid_is_alive(pid: int) -> bool:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False
    process_query_limited_information = 0x1000
    still_active = 259
    handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return int(exit_code.value) == still_active
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _heartbeat_payload(action: str, status: str, pid: int, now: str) -> dict[str, object]:
    return {"schema": MLHD_CONTROL_SCHEMA, "action": action, "status": status, "pid": pid, "heartbeat_at_utc": now}


def _state_payload(status: str, action: str, pid: int, now: str) -> dict[str, object]:
    return {
        "schema": MLHD_CONTROL_SCHEMA,
        "status": status,
        "last_action": action,
        "pid": pid,
        "updated_at_utc": now,
        "runtime_dir": MLHD_RUNTIME_DIR_REL,
        "authority": "disposable runtime state only; repo-visible route files remain authority",
    }


def _read_json_marker(root: Path, name: str) -> dict[str, object]:
    path = artifact_dir(root) / name
    return _read_json_file(path)
