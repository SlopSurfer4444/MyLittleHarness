from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory, Surface
from .models import Finding
from .root_boundary import PRODUCT_SOURCE_FIXTURE, source_path_boundary_violation


CONTEXT_MEMORY_SCHEMA = "mylittleharness.source-bound-context-memory-capsule.v1"
CONTEXT_MEMORY_DIR_REL = ".mylittleharness/" + "generated/context-memory"
CONTEXT_MEMORY_LATEST_FILE_NAME = "latest.json"
CONTEXT_MEMORY_HISTORY_DIR_NAME = "capsules"
CONTEXT_MEMORY_LATEST_REL = f"{CONTEXT_MEMORY_DIR_REL}/{CONTEXT_MEMORY_LATEST_FILE_NAME}"
PROJECT_ROUTE_PREFIX = "project/"
DOCS_ROUTE_PREFIX = "docs/"
STATE_ROUTE_REL = PROJECT_ROUTE_PREFIX + "project-state.md"
ROADMAP_ROUTE_REL = PROJECT_ROUTE_PREFIX + "roadmap.md"
PLAN_ROUTE_REL = PROJECT_ROUTE_PREFIX + "implementation-plan.md"
WORKFLOW_MANIFEST_REL = ".codex/" + "project-workflow.toml"

CORE_SOURCE_REFS = (
    "AGENTS.md",
    WORKFLOW_MANIFEST_REL,
    STATE_ROUTE_REL,
    ROADMAP_ROUTE_REL,
)


def context_memory_capsule_payload(inventory: Inventory) -> dict[str, object]:
    payload = _read_latest_capsule(inventory.root)
    status = _capsule_freshness_status(inventory, payload)
    return {
        "schema": CONTEXT_MEMORY_SCHEMA,
        "status": status["status"],
        "capsule_rel_path": CONTEXT_MEMORY_LATEST_REL,
        "capsule_id": str(payload.get("capsule_id") or ""),
        "created_at_utc": str(payload.get("created_at_utc") or ""),
        "trigger": str(payload.get("trigger") or ""),
        "source_ref_count": len(payload.get("source_refs") or []) if isinstance(payload.get("source_refs"), list) else 0,
        "stale_or_unknown": status["stale_or_unknown"],
        "next_safe_command": _capsule_refresh_command(inventory),
        "authority": "source-bound context memory is generated non-authority context; source files and lifecycle routes remain truth",
    }


def context_memory_capsule_findings(inventory: Inventory, code_prefix: str = "context-memory") -> list[Finding]:
    payload = context_memory_capsule_payload(inventory)
    status = str(payload["status"])
    severity = "info" if status in {"current", "missing"} else "warn"
    stale = payload["stale_or_unknown"]
    stale_examples = ", ".join(str(value) for value in stale[:3]) if isinstance(stale, list) else ""
    if not stale_examples:
        stale_examples = "none"
    return [
        Finding(
            severity,
            f"{code_prefix}-capsule",
            (
                f"source-bound capsule status={status}; capsule={CONTEXT_MEMORY_LATEST_REL}; "
                f"source_refs={payload['source_ref_count']}; stale_or_unknown={stale_examples}; "
                f"refresh_command={payload['next_safe_command']}"
            ),
            CONTEXT_MEMORY_LATEST_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-authority-boundary",
            (
                "context-memory capsules are generated from repo-visible sources and cannot approve lifecycle, roadmap, "
                "archive, repair, Git, provider, dispatcher, release, or source truth"
            ),
            CONTEXT_MEMORY_LATEST_REL,
        ),
    ]


def context_memory_hook_context(inventory: Inventory) -> str:
    payload = context_memory_capsule_payload(inventory)
    stale = payload.get("stale_or_unknown")
    stale_count = len(stale) if isinstance(stale, list) else 0
    return (
        f"- context_memory: status={payload['status']}; capsule={payload['capsule_rel_path']}; "
        f"source_refs={payload['source_ref_count']}; stale_or_unknown={stale_count}; "
        f"next_safe={payload['next_safe_command']}"
    )


def refresh_context_memory_capsule(
    inventory: Inventory,
    *,
    trigger: str,
    now: str | None = None,
) -> tuple[list[Finding], dict[str, object]]:
    now = now or _utc_now()
    capsule = build_context_memory_capsule(inventory, trigger=trigger, now=now)
    rendered = json.dumps(capsule, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    capsule_id = str(capsule["capsule_id"])
    latest_path = inventory.root / CONTEXT_MEMORY_LATEST_REL
    history_path = inventory.root / CONTEXT_MEMORY_DIR_REL / CONTEXT_MEMORY_HISTORY_DIR_NAME / f"{capsule_id}.json"
    try:
        cleanup_warnings = apply_file_transaction(
            [_atomic_write(latest_path, rendered), _atomic_write(history_path, rendered)],
            root=inventory.root,
        )
    except FileTransactionError as exc:
        capsule["status"] = "write-refused"
        return [
            Finding(
                "error",
                "context-memory-boundary",
                f"refused generated context-memory capsule write outside the target-root boundary: {exc}",
                CONTEXT_MEMORY_LATEST_REL,
            )
        ], capsule
    findings = [
        Finding(
            "info",
            "context-memory-capsule-refreshed",
            (
                f"wrote source-bound generated context capsule {CONTEXT_MEMORY_LATEST_REL}; "
                f"capsule_id={capsule_id}; source_refs={len(capsule['source_refs'])}; trigger={trigger}"
            ),
            CONTEXT_MEMORY_LATEST_REL,
        ),
        Finding(
            "info",
            "context-memory-capsule-history",
            (
                f"kept old-good capsule history under {CONTEXT_MEMORY_DIR_REL}/{CONTEXT_MEMORY_HISTORY_DIR_NAME}/; "
                "generated context remains replayable from source refs"
            ),
            CONTEXT_MEMORY_LATEST_REL,
        ),
        Finding(
            "info",
            "context-memory-capsule-boundary",
            (
                "context-memory capsule refresh cannot approve lifecycle movement, roadmap status, archive, closeout, "
                "repair, staging, commit, push, release, provider routing, dispatcher choices, or source truth"
            ),
            CONTEXT_MEMORY_LATEST_REL,
        ),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "context-memory-cleanup-warning", warning, CONTEXT_MEMORY_LATEST_REL))
    return findings, capsule


def build_context_memory_capsule(inventory: Inventory, *, trigger: str, now: str | None = None) -> dict[str, object]:
    now = now or _utc_now()
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    plan = inventory.active_plan_surface if inventory.active_plan_surface and inventory.active_plan_surface.exists else None
    plan_data = plan.frontmatter.data if plan and plan.frontmatter.has_frontmatter else {}
    source_refs = _source_ref_rows(inventory)
    capsule: dict[str, object] = {
        "schema": CONTEXT_MEMORY_SCHEMA,
        "capsule_id": "",
        "created_at_utc": now,
        "trigger": trigger,
        "status": "current",
        "lifecycle": {
            "plan_status": str(state_data.get("plan_status") or ""),
            "active_plan": str(state_data.get("active_plan") or ""),
            "active_phase": str(state_data.get("active_phase") or ""),
            "phase_status": str(state_data.get("phase_status") or ""),
            "last_archived_plan": str(state_data.get("last_archived_plan") or ""),
        },
        "active_plan": {
            "plan_id": str(plan_data.get("plan_id") or ""),
            "title": str(plan_data.get("title") or ""),
            "status": str(plan_data.get("status") or ""),
            "docs_decision": str(plan_data.get("docs_decision") or state_data.get("docs_decision") or "unknown"),
            "execution_policy": str(plan_data.get("execution_policy") or ""),
            "primary_roadmap_item": str(plan_data.get("primary_roadmap_item") or plan_data.get("related_roadmap_item") or ""),
            "closeout_boundary": str(plan_data.get("closeout_boundary") or ""),
        },
        "next_safe_command": _next_safe_command(state_data),
        "stale_or_unknown_markers": _unknown_source_markers(source_refs),
        "source_refs": source_refs,
        "source_hash_algorithm": "sha256",
        "authority": (
            "generated source-bound context only; repo-visible source files, project-state, roadmap, active plans, "
            "verification, and explicit dry-run/apply rails remain authority"
        ),
        "cannot_approve": [
            "lifecycle movement",
            "roadmap status",
            "archive",
            "closeout",
            "repair",
            "staging",
            "commit",
            "push",
            "release",
            "provider routing",
            "dispatcher choices",
            "source truth",
        ],
    }
    capsule["capsule_id"] = _capsule_id(capsule)
    return capsule


def _source_ref_rows(inventory: Inventory) -> list[dict[str, object]]:
    rels = list(CORE_SOURCE_REFS)
    if inventory.state and inventory.state.exists:
        active_plan = str(inventory.state.frontmatter.data.get("active_plan") or "").strip()
        if active_plan:
            rels.append(active_plan.replace("\\", "/"))
    if inventory.active_plan_surface and inventory.active_plan_surface.exists:
        rels.append(inventory.active_plan_surface.rel_path)
        plan_data = inventory.active_plan_surface.frontmatter.data
        for key in ("source_incubation", "source_research"):
            value = str(plan_data.get(key) or "").strip()
            if value:
                rels.append(value.replace("\\", "/"))
        values = plan_data.get("related_specs")
        if isinstance(values, list):
            rels.extend(
                str(value).replace("\\", "/")
                for value in values
                if str(value or "").startswith((PROJECT_ROUTE_PREFIX, DOCS_ROUTE_PREFIX))
            )
    deduped = []
    seen: set[str] = set()
    for rel in rels:
        normalized = _normalize_rel(rel)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return [_source_ref_row(inventory, rel) for rel in deduped]


def _source_ref_row(inventory: Inventory, rel: str) -> dict[str, object]:
    conflict = _source_ref_conflict(rel)
    if conflict:
        return {"rel_path": rel, "status": "unsafe", "error": conflict, "sha256": "", "line_count": 0}
    surface = inventory.surface_by_rel.get(rel)
    path = inventory.root / rel
    boundary_violation = source_path_boundary_violation(inventory.root, path, label="context-memory source ref")
    if boundary_violation is not None:
        return {"rel_path": rel, "status": "unsafe", "error": boundary_violation.message, "sha256": "", "line_count": 0}
    if surface is not None and surface.exists and not surface.read_error:
        return _surface_ref_row(surface)
    if path.is_file() and not path.is_symlink():
        try:
            raw = path.read_bytes()
        except OSError as exc:
            return {"rel_path": rel, "status": "unreadable", "error": str(exc), "sha256": "", "line_count": 0}
        text = raw.decode("utf-8", errors="replace")
        return {
            "rel_path": rel,
            "status": "present",
            "role": surface.role if surface else "source-ref",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "line_count": len(text.splitlines()),
        }
    return {"rel_path": rel, "status": "missing", "sha256": "", "line_count": 0}


def _surface_ref_row(surface: Surface) -> dict[str, object]:
    return {
        "rel_path": surface.rel_path,
        "status": "present",
        "role": surface.role,
        "memory_route": surface.memory_route,
        "sha256": hashlib.sha256(surface.content.encode("utf-8", errors="replace")).hexdigest(),
        "line_count": surface.line_count,
    }


def _capsule_freshness_status(inventory: Inventory, payload: dict[str, object]) -> dict[str, object]:
    if not payload:
        return {"status": "missing", "stale_or_unknown": []}
    stale: list[str] = []
    refs = payload.get("source_refs")
    if not isinstance(refs, list):
        return {"status": "stale", "stale_or_unknown": ["source_refs missing"]}
    for ref in refs:
        if not isinstance(ref, dict):
            stale.append("malformed source ref")
            continue
        rel = str(ref.get("rel_path") or "")
        recorded_hash = str(ref.get("sha256") or "")
        current = _source_ref_row(inventory, rel)
        current_hash = str(current.get("sha256") or "")
        current_status = str(current.get("status") or "")
        if current_status != str(ref.get("status") or "") or current_hash != recorded_hash:
            stale.append(rel or "<missing-rel>")
    return {"status": "current" if not stale else "stale", "stale_or_unknown": stale}


def _read_latest_capsule(root: Path) -> dict[str, object]:
    path = root / CONTEXT_MEMORY_LATEST_REL
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"schema": CONTEXT_MEMORY_SCHEMA, "status": "unreadable"}
    if not isinstance(payload, dict):
        return {}
    return payload


def _unknown_source_markers(source_refs: list[dict[str, object]]) -> list[str]:
    return [str(ref.get("rel_path") or "") for ref in source_refs if str(ref.get("status") or "") != "present"]


def _next_safe_command(state_data: dict[str, object]) -> str:
    if str(state_data.get("plan_status") or "").casefold() == "active":
        return "mylittleharness --root <root> check"
    return "mylittleharness --root <root> dashboard --inspect --json"


def _capsule_refresh_command(inventory: Inventory) -> str:
    if inventory.root_kind == PRODUCT_SOURCE_FIXTURE:
        return "mylittleharness --root <root> check"
    return "mylittleharness --root <root> mlhd run-once --apply"


def _capsule_id(capsule: dict[str, object]) -> str:
    payload = dict(capsule)
    payload["capsule_id"] = ""
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()[:16]
    timestamp = str(capsule.get("created_at_utc") or "").replace(":", "").replace("-", "").replace("+", "z")
    timestamp = timestamp.replace(".", "")[:15] or "unknown-time"
    return f"{timestamp}-{digest}"


def _atomic_write(target: Path, text: str) -> AtomicFileWrite:
    return AtomicFileWrite(
        target_path=target,
        tmp_path=target.with_name(f".{target.name}.context-memory.tmp"),
        backup_path=target.with_name(f".{target.name}.context-memory.backup"),
        text=text,
    )


def _normalize_rel(value: str) -> str:
    rel = str(value or "").strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.rstrip("/")


def _source_ref_conflict(rel: str) -> str:
    if not rel:
        return "empty source ref"
    if rel.startswith(("/", "//")) or re.match(r"^[A-Za-z]:/", rel):
        return f"source ref is not root-relative: {rel}"
    if "\n" in rel or "\r" in rel or ":" in rel:
        return f"source ref contains unsafe path syntax: {rel}"
    if any(part == ".." for part in rel.split("/")):
        return f"source ref contains parent traversal: {rel}"
    return ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
