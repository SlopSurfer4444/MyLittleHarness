from __future__ import annotations

import json
import hashlib
import time
from dataclasses import asdict
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory
from .models import Finding
from .projection import Projection, build_projection


ARTIFACT_SCHEMA_VERSION = 2
ARTIFACT_DIR_REL = ".mylittleharness/generated/projection"
ARTIFACT_NAMES = (
    "manifest.json",
    "sources.json",
    "source-hashes.json",
    "links.json",
    "backlinks.json",
    "fan-in.json",
    "relationships.json",
    "summary.json",
)
KNOWN_NON_JSON_PROJECTION_NAMES = (
    "search-index.sqlite3",
    "search-index.sqlite3-journal",
    "search-index.sqlite3-shm",
    "search-index.sqlite3-wal",
)
ARTIFACT_DIRTY_MARKER_NAME = "artifacts.dirty.json"
INDEX_DIRTY_MARKER_NAME = "index.dirty.json"
CACHE_DIRTY_MARKER_NAMES = (ARTIFACT_DIRTY_MARKER_NAME, INDEX_DIRTY_MARKER_NAME)
CACHE_OPERATION_MARKER_NAME = "cache-operation.json"
DIRTY_MARKER_SCHEMA_VERSION = 1
OPERATION_MARKER_SCHEMA_VERSION = 1
JSON_REPLACE_ATTEMPTS = 6
JSON_REPLACE_RETRY_SECONDS = 0.01
PAYLOAD_HASH_ARTIFACT_NAMES = tuple(name for name in ARTIFACT_NAMES if name != "manifest.json")
SOURCE_SET_ARTIFACT_NAMES = ("sources.json", "source-hashes.json")
RECORD_SET_ARTIFACT_NAMES = ("links.json", "backlinks.json", "fan-in.json", "relationships.json", "summary.json")
PROJECTION_REBUILD_NEXT_SAFE_COMMAND = "next_safe_command=mylittleharness --root <root> projection --rebuild --target all"


def build_projection_artifacts(inventory: Inventory) -> list[Finding]:
    findings = _boundary_preflight(inventory.root, create=True)
    if _has_errors(findings):
        return findings

    projection_dir = artifact_dir(inventory.root)
    operation_findings = write_projection_cache_operation_marker(inventory.root, "projection-artifacts-build")
    cleanup_warnings: tuple[str, ...] = ()
    try:
        projection = build_projection(inventory)
        payloads = artifact_payloads(inventory, projection)
        cleanup_warnings = _write_json_payloads_transactionally(projection_dir, payloads)
        clear_projection_cache_dirty_marker(inventory.root, ARTIFACT_DIRTY_MARKER_NAME)
    except (OSError, FileTransactionError) as exc:
        return [
            *operation_findings,
            Finding("info", "projection-artifact-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            Finding(
                "warn",
                "projection-artifact-refresh-degraded",
                (
                    "projection artifact refresh failed before publishing a partial cache; "
                    f"old-good artifacts, if present, remain the only generated artifact input: {exc}; "
                    f"{PROJECTION_REBUILD_NEXT_SAFE_COMMAND}"
                ),
                ARTIFACT_DIR_REL,
            ),
        ]
    finally:
        clear_projection_cache_operation_marker(inventory.root)

    result = [
        *operation_findings,
        Finding("info", "projection-artifact-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
        Finding(
            "info",
            "projection-artifact-atomic-refresh",
            "published projection artifacts through a rollback-capable file transaction; readers keep old-good cache on failed refresh",
            ARTIFACT_DIR_REL,
        ),
        Finding("info", "projection-artifact-build", f"wrote {len(ARTIFACT_NAMES)} rebuildable projection artifacts"),
        Finding(
            "info",
            "projection-artifact-records",
            (
                f"sources={projection.summary.source_count}; links={projection.summary.link_record_count}; "
                f"fan_in={projection.summary.fan_in_record_count}; relationships={projection.summary.relationship_edge_count}; "
                f"hashes={projection.summary.hashed_source_count}"
            ),
        ),
    ]
    for warning in cleanup_warnings:
        result.append(Finding("warn", "projection-artifact-backup-cleanup", warning, ARTIFACT_DIR_REL))
    return result


def rebuild_projection_artifacts(inventory: Inventory) -> list[Finding]:
    findings = _boundary_preflight(inventory.root, create=True)
    if _has_errors(findings):
        return findings
    return [
        Finding(
            "info",
            "projection-artifact-rebuild",
            "rebuild uses the same old-good transactional publish path as build; stale artifacts are replaced only after a complete payload is ready",
            ARTIFACT_DIR_REL,
        ),
        *build_projection_artifacts(inventory),
    ]


def delete_projection_artifacts(inventory: Inventory) -> list[Finding]:
    findings = _boundary_preflight(inventory.root, create=False)
    if _has_errors(findings):
        return findings

    projection_dir = artifact_dir(inventory.root)
    if not projection_dir.exists():
        return [
            Finding(
                "info",
                "projection-artifact-delete",
                f"owned projection artifact boundary is already absent: {ARTIFACT_DIR_REL}",
                ARTIFACT_DIR_REL,
            )
        ]

    deleted: list[str] = []
    blocked: list[Finding] = []
    for name in (*ARTIFACT_NAMES, ARTIFACT_DIRTY_MARKER_NAME):
        child = projection_dir / name
        if not child.exists():
            continue
        rel_child = child.relative_to(inventory.root).as_posix()
        if not _is_under_artifact_dir(inventory.root, child):
            blocked.append(
                Finding(
                    "error",
                    "projection-artifact-boundary",
                    f"refused to delete path outside owned projection boundary: {rel_child}",
                    rel_child,
                )
            )
        if child.is_dir() and not child.is_symlink():
            blocked.append(
                Finding(
                    "error",
                    "projection-artifact-delete-refused",
                    f"refused to recursively delete directory-shaped generated artifact path: {rel_child}",
                    rel_child,
                )
            )
    if blocked:
        return [
            Finding("info", "projection-artifact-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            *blocked,
        ]

    operation_findings = write_projection_cache_operation_marker(inventory.root, "projection-artifacts-delete")
    try:
        for name in (*ARTIFACT_NAMES, ARTIFACT_DIRTY_MARKER_NAME):
            child = projection_dir / name
            if not child.exists():
                continue
            rel_child = child.relative_to(inventory.root).as_posix()
            if child.is_dir() and not child.is_symlink():
                continue
            else:
                child.unlink()
            deleted.append(rel_child)
    finally:
        clear_projection_cache_operation_marker(inventory.root)

    return [
        *operation_findings,
        Finding("info", "projection-artifact-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
        Finding("info", "projection-artifact-delete", f"deleted {len(deleted)} generated artifact paths from the owned boundary"),
    ]


def inspect_projection_artifacts(inventory: Inventory, projection: Projection | None = None) -> list[Finding]:
    projection = projection or build_projection(inventory)
    findings = _boundary_preflight(inventory.root, create=False)
    if _has_errors(findings):
        return findings

    projection_dir = artifact_dir(inventory.root)
    findings.append(Finding("info", "projection-artifact-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL))
    findings.extend(projection_cache_operation_marker_findings(inventory.root))
    if not projection_dir.exists():
        findings.append(
            Finding(
                "info",
                "projection-artifact-missing",
                "projection artifacts are missing; direct source reads and in-memory projection remain authoritative",
                ARTIFACT_DIR_REL,
            )
        )
        return findings

    payloads: dict[str, Any] = {}
    findings.extend(_unexpected_artifact_findings(inventory.root))
    findings.extend(
        projection_cache_dirty_marker_findings(
            inventory.root,
            ARTIFACT_DIRTY_MARKER_NAME,
            "projection-artifact-dirty",
            f"generated projection artifacts were marked dirty by a mutating workflow command; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
        )
    )
    missing = [name for name in ARTIFACT_NAMES if not (projection_dir / name).is_file()]
    for name in missing:
        findings.append(
            Finding(
                "warn",
                "projection-artifact-incomplete",
                f"expected generated artifact is missing and can be rebuilt: {name}",
                f"{ARTIFACT_DIR_REL}/{name}",
            )
        )

    for name in ARTIFACT_NAMES:
        path = projection_dir / name
        if not path.exists() or not path.is_file():
            continue
        try:
            payloads[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, JSONDecodeError) as exc:
            findings.append(
                Finding(
                    "warn",
                    "projection-artifact-corrupt",
                    f"{name} is unreadable as JSON; direct source reads remain authoritative: {exc}",
                    f"{ARTIFACT_DIR_REL}/{name}",
                )
            )

    findings.extend(_payload_shape_findings(payloads))

    manifest = payloads.get("manifest.json")
    if isinstance(manifest, dict):
        schema_version = manifest.get("schema_version")
        if schema_version != ARTIFACT_SCHEMA_VERSION:
            if schema_version == 1:
                message = "stale v1 projection artifacts can be rebuilt to schema 2"
            else:
                message = f"unsupported projection artifact schema {schema_version!r}; expected {ARTIFACT_SCHEMA_VERSION}"
            findings.append(
                Finding(
                    "warn",
                    "projection-artifact-schema",
                    message,
                    f"{ARTIFACT_DIR_REL}/manifest.json",
                )
            )
        artifact_root = manifest.get("root")
        if artifact_root and _normalize_path_text(str(artifact_root)) != _normalize_path_text(str(inventory.root)):
            findings.append(
                Finding(
                    "warn",
                    "projection-artifact-root-mismatch",
                    f"artifact root {artifact_root} does not match current root {inventory.root}",
                    f"{ARTIFACT_DIR_REL}/manifest.json",
                )
            )
    elif "manifest.json" in payloads:
        findings.append(
            Finding(
                "warn",
                "projection-artifact-corrupt",
                "manifest.json payload is not a JSON object; direct source reads remain authoritative",
                f"{ARTIFACT_DIR_REL}/manifest.json",
            )
        )

    findings.extend(_integrity_findings(payloads))
    findings.extend(_stale_findings(projection, payloads))
    if not any(finding.severity == "warn" for finding in findings):
        findings.append(Finding("info", "projection-artifact-current", "generated projection artifacts match current source hashes and record counts"))
    return findings


def mark_projection_cache_dirty(inventory: Inventory, changed_paths: Iterable[str], command: str) -> list[Finding]:
    paths = tuple(sorted({_dirty_source_rel_path(path) for path in changed_paths if _dirty_source_rel_path(path)}))
    if not paths:
        return []

    projection_dir = artifact_dir(inventory.root)
    if not projection_dir.exists():
        return []
    preflight = _boundary_preflight(inventory.root, create=False)
    boundary_errors = [finding for finding in preflight if finding.severity == "error"]
    if boundary_errors:
        reason = boundary_errors[0]
        return [
            Finding(
                "warn",
                "projection-cache-dirty-skipped",
                f"generated projection cache dirty marker skipped because {reason.code}; source files remain authoritative",
                reason.source or ARTIFACT_DIR_REL,
                reason.line,
            )
        ]

    payload = _dirty_marker_payload(command, paths)
    written: list[str] = []
    warnings: list[Finding] = []
    for marker_name in CACHE_DIRTY_MARKER_NAMES:
        marker_rel = f"{ARTIFACT_DIR_REL}/{marker_name}"
        marker_path = projection_dir / marker_name
        if marker_path.exists() and (marker_path.is_symlink() or marker_path.is_dir()):
            warnings.append(
                Finding(
                    "warn",
                    "projection-cache-dirty-skipped",
                    f"generated projection cache dirty marker path is not a regular file: {marker_rel}",
                    marker_rel,
                )
            )
            continue
        try:
            _write_json(marker_path, payload)
        except OSError as exc:
            if marker_path.exists() and not marker_path.is_symlink() and marker_path.is_file():
                written.append(marker_rel)
                continue
            warnings.append(
                Finding(
                    "warn",
                    "projection-cache-dirty-skipped",
                    f"failed to write generated projection cache dirty marker {marker_rel}: {exc}",
                    marker_rel,
                )
            )
            continue
        written.append(marker_rel)

    if not written:
        return warnings
    return [
        Finding(
            "info",
            "projection-cache-dirty",
            (
                f"marked disposable generated projection cache dirty after {command}; "
                f"changed_paths={len(paths)}; markers={', '.join(written)}"
            ),
            ARTIFACT_DIR_REL,
        ),
        *warnings,
    ]


def projection_cache_dirty_marker_findings(root: Path, marker_name: str, code: str, message: str) -> list[Finding]:
    marker_path = artifact_dir(root) / marker_name
    marker_rel = f"{ARTIFACT_DIR_REL}/{marker_name}"
    if not marker_path.exists():
        return []
    if marker_path.is_file() and not marker_path.is_symlink():
        return [Finding("warn", code, message, marker_rel)]
    return [
        Finding(
            "warn",
            code,
            f"generated projection cache dirty marker is malformed and can be deleted or rebuilt: {marker_rel}",
            marker_rel,
        )
    ]


def projection_cache_posture_payload(
    artifact_findings: list[Finding],
    index_findings: list[Finding],
) -> dict[str, object]:
    artifact = _cache_component_posture(
        "artifacts",
        artifact_findings,
        current_code="projection-artifact-current",
        missing_code="projection-artifact-missing",
    )
    index = _cache_component_posture(
        "sqlite_index",
        index_findings,
        current_code="projection-index-current",
        missing_code="projection-index-missing",
    )
    return {
        "schema": "mylittleharness.projection-cache-posture.v1",
        "read_only": True,
        "authority": "repo-visible source files and in-memory projection remain authoritative",
        "refreshable_by_adapter": False,
        "self_heal_command": "mylittleharness --root <root> projection --warm-cache --target all",
        "self_healable_by_command": True,
        "refresh_policy": "missing, dirty, stale, corrupt, or malformed generated cache can be warmed or rebuilt explicitly without creating lifecycle authority",
        "components": {
            "artifacts": artifact,
            "sqlite_index": index,
        },
        "source_refs": [
            ARTIFACT_DIR_REL,
            f"{ARTIFACT_DIR_REL}/manifest.json",
            f"{ARTIFACT_DIR_REL}/search-index.sqlite3",
            f"{ARTIFACT_DIR_REL}/{ARTIFACT_DIRTY_MARKER_NAME}",
            f"{ARTIFACT_DIR_REL}/{INDEX_DIRTY_MARKER_NAME}",
            f"{ARTIFACT_DIR_REL}/{CACHE_OPERATION_MARKER_NAME}",
        ],
        "recommended_refresh_commands": _cache_refresh_commands(artifact, index),
    }


def projection_cache_operation_marker_findings(root: Path) -> list[Finding]:
    marker_path = artifact_dir(root) / CACHE_OPERATION_MARKER_NAME
    marker_rel = f"{ARTIFACT_DIR_REL}/{CACHE_OPERATION_MARKER_NAME}"
    if not marker_path.exists():
        return []
    if not marker_path.is_file() or marker_path.is_symlink():
        return [
            Finding(
                "warn",
                "projection-cache-operation-in-progress",
                f"generated projection cache operation marker is malformed; serialize projection writers/readers and inspect {marker_rel}",
                marker_rel,
            )
        ]
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        return [
            Finding(
                "warn",
                "projection-cache-operation-in-progress",
                f"generated projection cache operation marker is unreadable; rerun after any projection command completes: {exc}",
                marker_rel,
            )
        ]
    operation = str(payload.get("operation") or "unknown")
    created_at = str(payload.get("created_at_utc") or "unknown")
    return [
        Finding(
            "warn",
            "projection-cache-operation-in-progress",
            (
                f"generated projection cache write may be in progress or interrupted: operation={operation}; "
                f"created_at_utc={created_at}; rerun the read-only command after the projection write completes; "
                f"{PROJECTION_REBUILD_NEXT_SAFE_COMMAND}"
            ),
            marker_rel,
        )
    ]


def write_projection_cache_operation_marker(root: Path, operation: str) -> list[Finding]:
    projection_dir = artifact_dir(root)
    marker_path = projection_dir / CACHE_OPERATION_MARKER_NAME
    marker_rel = f"{ARTIFACT_DIR_REL}/{CACHE_OPERATION_MARKER_NAME}"
    payload = {
        "schema_version": OPERATION_MARKER_SCHEMA_VERSION,
        "marker_kind": "mylittleharness-projection-cache-operation",
        "operation": operation,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "authority": "repo-visible source files remain authoritative; this marker only identifies an in-progress disposable generated-cache write",
    }
    try:
        _write_json(marker_path, payload)
    except OSError as exc:
        return [
            Finding(
                "warn",
                "projection-cache-operation-marker-skipped",
                f"failed to write generated projection cache operation marker {marker_rel}: {exc}",
                marker_rel,
            )
        ]
    return []


def clear_projection_cache_dirty_marker(root: Path, marker_name: str) -> None:
    marker_path = artifact_dir(root) / marker_name
    if marker_path.exists() and marker_path.is_file() and not marker_path.is_symlink():
        try:
            marker_path.unlink()
        except OSError:
            pass


def clear_projection_cache_operation_marker(root: Path) -> None:
    marker_path = artifact_dir(root) / CACHE_OPERATION_MARKER_NAME
    if marker_path.exists() and marker_path.is_file() and not marker_path.is_symlink():
        try:
            marker_path.unlink()
        except OSError:
            pass


def projection_artifact_path_query_findings(inventory: Inventory, projection: Projection, path_text: str | None) -> list[Finding]:
    if path_text in (None, ""):
        return []

    inspect_findings = inspect_projection_artifacts(inventory, projection)
    blocking = [
        finding
        for finding in inspect_findings
        if finding.severity in {"warn", "error"} or finding.code in {"projection-artifact-missing"}
    ]
    if blocking:
        finding = blocking[0]
        return [
            Finding(
                "info",
                "projection-artifact-query-skipped",
                (
                    f"path/reference artifact parity skipped for {path_text!r}: {finding.code}; "
                    "direct in-memory path search remains authoritative"
                ),
                finding.source or ARTIFACT_DIR_REL,
                finding.line,
            )
        ]

    try:
        payloads = _load_existing_payloads(inventory.root)
    except (OSError, JSONDecodeError) as exc:
        return [
            Finding(
                "info",
                "projection-artifact-query-skipped",
                f"path/reference artifact parity skipped for {path_text!r}: artifact payload reload failed; {exc}",
                ARTIFACT_DIR_REL,
            )
        ]
    artifact_rows = _artifact_path_reference_rows(payloads)
    if artifact_rows is None:
        return [
            Finding(
                "info",
                "projection-artifact-query-skipped",
                f"path/reference artifact parity skipped for {path_text!r}: malformed path/reference artifact rows",
                ARTIFACT_DIR_REL,
            )
        ]

    artifact_paths, artifact_refs = artifact_rows
    current_paths = frozenset(source.path for source in projection.sources)
    current_refs = frozenset(
        (record.source, record.line, record.target, record.status, record.resolution_kind)
        for record in projection.links
    )
    if artifact_paths != current_paths or artifact_refs != current_refs:
        return [
            Finding(
                "info",
                "projection-artifact-query-skipped",
                f"path/reference artifact parity skipped for {path_text!r}: artifact rows differ from current in-memory projection",
                ARTIFACT_DIR_REL,
            )
        ]

    source_matches = len([path for path in artifact_paths if path_text in path])
    reference_matches = len([row for row in artifact_refs if path_text in row[2]])
    return [
        Finding(
            "info",
            "projection-artifact-query-current",
            (
                f"path/reference artifact rows match current in-memory projection for {path_text!r}; "
                f"artifact source matches={source_matches}; reference matches={reference_matches}"
            ),
            ARTIFACT_DIR_REL,
        )
    ]


def artifact_dir(root: Path) -> Path:
    return root / ARTIFACT_DIR_REL


def artifact_payloads(inventory: Inventory, projection: Projection) -> dict[str, Any]:
    sources = [
        {
            "path": source.path,
            "role": source.role,
            "required": source.required,
            "present": source.present,
            "line_count": source.line_count,
            "byte_count": source.byte_count,
            "heading_count": source.heading_count,
            "link_count": source.link_count,
            "content_hash": source.content_hash,
            "read_error": source.read_error,
        }
        for source in projection.sources
    ]
    links = [
        {
            "source": record.source,
            "line": record.line,
            "target": record.target,
            "status": record.status,
            "resolution_kind": record.resolution_kind,
        }
        for record in projection.links
    ]
    backlinks = [
        {
            "target": record.target,
            "source": record.source,
            "line": record.line,
            "status": record.status,
            "resolution_kind": record.resolution_kind,
        }
        for record in sorted(projection.links, key=lambda item: (item.target, item.source, item.line))
    ]
    fan_in = [
        {
            "target": record.target,
            "inbound_count": record.inbound_count,
            "status": record.status,
            "sources": list(record.sources),
            "source": record.source,
        }
        for record in projection.fan_in
    ]
    source_hashes = [
        {"path": source.path, "content_hash": source.content_hash}
        for source in projection.sources
        if source.content_hash is not None
    ]
    relationships = {
        "nodes": [
            {
                "id": node.id,
                "kind": node.kind,
                "source": node.source,
                "title": node.title,
                "status": node.status,
                "route": node.route,
            }
            for node in projection.relationship_nodes
        ],
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "relation": edge.relation,
                "status": edge.status,
                "source_path": edge.source_path,
                "line": edge.line,
            }
            for edge in projection.relationship_edges
        ],
        "authority": "repo-visible relationship metadata remains authoritative; this graph is a disposable navigation projection",
    }
    summary = asdict(projection.summary)
    payloads = {
        "sources.json": {"schema_version": ARTIFACT_SCHEMA_VERSION, "sources": sources},
        "source-hashes.json": {"schema_version": ARTIFACT_SCHEMA_VERSION, "source_hashes": source_hashes},
        "links.json": {"schema_version": ARTIFACT_SCHEMA_VERSION, "links": links},
        "backlinks.json": {"schema_version": ARTIFACT_SCHEMA_VERSION, "backlinks": backlinks},
        "fan-in.json": {"schema_version": ARTIFACT_SCHEMA_VERSION, "fan_in": fan_in},
        "relationships.json": {"schema_version": ARTIFACT_SCHEMA_VERSION, "relationships": relationships},
        "summary.json": {"schema_version": ARTIFACT_SCHEMA_VERSION, "summary": summary},
    }
    payload_hashes = {name: _payload_hash(payloads[name]) for name in PAYLOAD_HASH_ARTIFACT_NAMES}
    manifest = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_kind": "mylittleharness-projection",
        "root": str(inventory.root),
        "root_kind": inventory.root_kind,
        "storage_boundary": ARTIFACT_DIR_REL,
        "artifacts": list(ARTIFACT_NAMES),
        "authority": "repo-visible files remain authoritative; generated artifacts are disposable and rebuildable",
        "payload_hashes": payload_hashes,
        "source_set_hash": _combined_hash(payload_hashes, SOURCE_SET_ARTIFACT_NAMES),
        "record_set_hash": _combined_hash(payload_hashes, RECORD_SET_ARTIFACT_NAMES),
        "query_capabilities": {
            "exact_text_search": {
                "artifact_backed": False,
                "case_sensitive": True,
                "source": "direct-files-and-in-memory-projection",
                "stores_source_bodies": False,
            },
            "path_reference_search": {
                "artifact_backed": True,
                "case_sensitive": True,
                "sources": ["sources.json", "links.json", "backlinks.json"],
                "stores_source_bodies": False,
            },
        },
        "summary": summary,
    }
    return {"manifest.json": manifest, **payloads}


def _unexpected_artifact_findings(root: Path) -> list[Finding]:
    projection_dir = artifact_dir(root)
    expected = set(ARTIFACT_NAMES) | set(KNOWN_NON_JSON_PROJECTION_NAMES) | set(CACHE_DIRTY_MARKER_NAMES) | {CACHE_OPERATION_MARKER_NAME}
    findings: list[Finding] = []
    for child in sorted(projection_dir.iterdir(), key=lambda item: item.name.lower()):
        if child.name in expected:
            continue
        rel_child = child.relative_to(root).as_posix()
        findings.append(
            Finding(
                "warn",
                "projection-artifact-unexpected",
                f"unexpected projection artifact path inside owned boundary: {rel_child}",
                rel_child,
            )
        )
    return findings


def _payload_shape_findings(payloads: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    expected_collections: dict[str, tuple[str, type]] = {
        "sources.json": ("sources", list),
        "source-hashes.json": ("source_hashes", list),
        "links.json": ("links", list),
        "backlinks.json": ("backlinks", list),
        "fan-in.json": ("fan_in", list),
        "relationships.json": ("relationships", dict),
        "summary.json": ("summary", dict),
    }
    for name, payload in sorted(payloads.items()):
        if not isinstance(payload, dict):
            findings.append(
                Finding(
                    "warn",
                    "projection-artifact-malformed",
                    f"{name} payload is not a JSON object; direct source reads remain authoritative",
                    f"{ARTIFACT_DIR_REL}/{name}",
                )
            )
            continue
        schema_version = payload.get("schema_version")
        if schema_version not in (None, ARTIFACT_SCHEMA_VERSION):
            message = (
                f"{name} is a stale v1 projection artifact; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}"
                if schema_version == 1
                else f"{name} has unsupported schema {schema_version!r}; expected {ARTIFACT_SCHEMA_VERSION}"
            )
            findings.append(Finding("warn", "projection-artifact-schema", message, f"{ARTIFACT_DIR_REL}/{name}"))
        if name == "manifest.json":
            required = {
                "artifacts": list,
                "payload_hashes": dict,
                "query_capabilities": dict,
                "record_set_hash": str,
                "source_set_hash": str,
                "summary": dict,
            }
            for key, expected_type in required.items():
                if not isinstance(payload.get(key), expected_type):
                    findings.append(
                        Finding(
                            "warn",
                            "projection-artifact-malformed",
                            f"manifest.json field {key!r} is missing or malformed; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                            f"{ARTIFACT_DIR_REL}/manifest.json",
                        )
                    )
            continue
        key_and_type = expected_collections.get(name)
        if key_and_type is None:
            continue
        key, expected_type = key_and_type
        if not isinstance(payload.get(key), expected_type):
            findings.append(
                Finding(
                    "warn",
                    "projection-artifact-malformed",
                    f"{name} field {key!r} is missing or malformed; direct source reads remain authoritative",
                    f"{ARTIFACT_DIR_REL}/{name}",
                )
            )
    return findings


def _integrity_findings(payloads: dict[str, Any]) -> list[Finding]:
    manifest = payloads.get("manifest.json")
    if not isinstance(manifest, dict):
        return []
    payload_hashes = manifest.get("payload_hashes")
    if not isinstance(payload_hashes, dict):
        return []

    findings: list[Finding] = []
    current_hashes: dict[str, str] = {}
    for name in PAYLOAD_HASH_ARTIFACT_NAMES:
        payload = payloads.get(name)
        if payload is None:
            continue
        current_hashes[name] = _payload_hash(payload)
        if payload_hashes.get(name) != current_hashes[name]:
            findings.append(
                Finding(
                    "warn",
                    "projection-artifact-hash",
                    f"{name} payload hash does not match manifest integrity metadata; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                    f"{ARTIFACT_DIR_REL}/{name}",
                )
            )

    expected_source_set = _combined_hash(current_hashes, SOURCE_SET_ARTIFACT_NAMES)
    if isinstance(manifest.get("source_set_hash"), str) and manifest.get("source_set_hash") != expected_source_set:
        findings.append(
            Finding(
                "warn",
                "projection-artifact-hash",
                f"source-set hash does not match current artifact payload hashes; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                f"{ARTIFACT_DIR_REL}/manifest.json",
            )
        )
    expected_record_set = _combined_hash(current_hashes, RECORD_SET_ARTIFACT_NAMES)
    if isinstance(manifest.get("record_set_hash"), str) and manifest.get("record_set_hash") != expected_record_set:
        findings.append(
            Finding(
                "warn",
                "projection-artifact-hash",
                f"record-set hash does not match current artifact payload hashes; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                f"{ARTIFACT_DIR_REL}/manifest.json",
            )
        )
    return findings


def _load_existing_payloads(root: Path) -> dict[str, Any]:
    projection_dir = artifact_dir(root)
    payloads: dict[str, Any] = {}
    for name in ARTIFACT_NAMES:
        path = projection_dir / name
        if path.is_file():
            payloads[name] = json.loads(path.read_text(encoding="utf-8"))
    return payloads


def _artifact_path_reference_rows(payloads: dict[str, Any]) -> tuple[frozenset[str], frozenset[tuple[str, int, str, str, str]]] | None:
    sources_payload = payloads.get("sources.json")
    links_payload = payloads.get("links.json")
    if not isinstance(sources_payload, dict) or not isinstance(links_payload, dict):
        return None
    sources = sources_payload.get("sources")
    links = links_payload.get("links")
    if not isinstance(sources, list) or not isinstance(links, list):
        return None

    artifact_paths: set[str] = set()
    for row in sources:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            return None
        artifact_paths.add(row["path"])

    artifact_refs: set[tuple[str, int, str, str, str]] = set()
    for row in links:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("source"), str)
            or not isinstance(row.get("line"), int)
            or not isinstance(row.get("target"), str)
            or not isinstance(row.get("status"), str)
            or not isinstance(row.get("resolution_kind"), str)
        ):
            return None
        artifact_refs.add((row["source"], row["line"], row["target"], row["status"], row["resolution_kind"]))
    return frozenset(artifact_paths), frozenset(artifact_refs)


def _stale_findings(projection: Projection, payloads: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    source_hashes_payload = payloads.get("source-hashes.json")
    if isinstance(source_hashes_payload, dict):
        stored_rows = source_hashes_payload.get("source_hashes")
        if isinstance(stored_rows, list):
            stored_hashes = {
                str(row.get("path")): row.get("content_hash")
                for row in stored_rows
                if isinstance(row, dict) and row.get("path") is not None
            }
            current_hashes = {source.path: source.content_hash for source in projection.sources if source.content_hash is not None}
            changed = [
                path
                for path, current_hash in sorted(current_hashes.items())
                if stored_hashes.get(path) != current_hash
            ]
            removed = [path for path in sorted(stored_hashes) if path not in current_hashes]
            if changed or removed:
                sample = ", ".join((changed + removed)[:5])
                findings.append(
                    Finding(
                        "warn",
                        "projection-artifact-stale",
                        f"generated source hashes differ from current files; sample={sample}; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                    )
                )

    summary_payload = payloads.get("summary.json")
    if isinstance(summary_payload, dict) and isinstance(summary_payload.get("summary"), dict):
        stored_summary = summary_payload["summary"]
        expected = asdict(projection.summary)
        mismatches = [
            key
            for key in (
                "source_count",
                "present_source_count",
                "readable_source_count",
                "hashed_source_count",
                "missing_required_count",
                "link_record_count",
                "fan_in_record_count",
                "relationship_node_count",
                "relationship_edge_count",
            )
            if stored_summary.get(key) != expected[key]
        ]
        if mismatches:
            findings.append(
                Finding(
                    "warn",
                    "projection-artifact-stale",
                    f"generated summary counts differ from current projection: {', '.join(mismatches)}; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                    f"{ARTIFACT_DIR_REL}/summary.json",
                )
            )
    return findings


def _boundary_preflight(root: Path, create: bool) -> list[Finding]:
    findings: list[Finding] = []
    root_resolved = root.resolve()
    current = root
    for part in ARTIFACT_DIR_REL.split("/"):
        current = current / part
        rel_path = current.relative_to(root).as_posix()
        if current.exists():
            if current.is_symlink():
                findings.append(Finding("error", "projection-artifact-boundary", f"refused symlink in projection artifact boundary: {rel_path}", rel_path))
                return findings
            if not current.is_dir():
                findings.append(Finding("error", "projection-artifact-boundary", f"projection artifact boundary path is not a directory: {rel_path}", rel_path))
                return findings
            continue
        if create:
            current.mkdir()

    projection_dir = artifact_dir(root)
    try:
        projection_dir.resolve().relative_to(root_resolved)
    except ValueError:
        findings.append(
            Finding(
                "error",
                "projection-artifact-boundary",
                f"projection artifact boundary escapes target root: {ARTIFACT_DIR_REL}",
                ARTIFACT_DIR_REL,
            )
        )
    return findings


def _is_under_artifact_dir(root: Path, path: Path) -> bool:
    boundary = artifact_dir(root).resolve()
    try:
        path.resolve().relative_to(boundary)
        return True
    except ValueError:
        return False


def _write_json(path: Path, payload: Any) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp_path.write_text(rendered, encoding="utf-8")
        _replace_with_retry(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _replace_with_retry(source: Path, target: Path) -> None:
    last_error: OSError | None = None
    delay = JSON_REPLACE_RETRY_SECONDS
    for attempt in range(JSON_REPLACE_ATTEMPTS):
        try:
            source.replace(target)
            return
        except OSError as exc:
            last_error = exc
            if attempt == JSON_REPLACE_ATTEMPTS - 1:
                break
            time.sleep(delay)
            delay *= 2
    if last_error is not None:
        raise last_error


def _write_json_payloads_transactionally(projection_dir: Path, payloads: dict[str, Any]) -> tuple[str, ...]:
    nonce = uuid4().hex
    operations = []
    for name in ARTIFACT_NAMES:
        path = projection_dir / name
        operations.append(
            AtomicFileWrite(
                path,
                path.with_name(f".{name}.{nonce}.tmp"),
                _json_text(payloads[name]),
                path.with_name(f".{name}.{nonce}.bak"),
            )
        )
    return apply_file_transaction(operations)


def _json_text(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _dirty_marker_payload(command: str, paths: tuple[str, ...]) -> dict[str, Any]:
    return {
        "schema_version": DIRTY_MARKER_SCHEMA_VERSION,
        "marker_kind": "mylittleharness-projection-cache-dirty",
        "command": command,
        "dirty_since_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "changed_paths": list(paths),
        "authority": "repo-visible source files remain authoritative; this marker only invalidates disposable generated navigation cache",
    }


def _dirty_source_rel_path(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip().strip("/")
    if not normalized or "\n" in normalized or ":" in normalized:
        return ""
    if normalized == ARTIFACT_DIR_REL or normalized.startswith(f"{ARTIFACT_DIR_REL}/"):
        return ""
    return normalized


def _payload_hash(payload: Any) -> str:
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _combined_hash(payload_hashes: dict[str, str], names: tuple[str, ...]) -> str:
    rows = [(name, payload_hashes.get(name, "")) for name in names]
    return _payload_hash(rows)


def _normalize_path_text(value: str) -> str:
    return value.replace("/", "\\").rstrip("\\").casefold()


def _has_errors(findings: list[Finding]) -> bool:
    return any(finding.severity == "error" for finding in findings)


def _cache_component_posture(
    component: str,
    findings: list[Finding],
    *,
    current_code: str,
    missing_code: str,
) -> dict[str, object]:
    codes = [finding.code for finding in findings]
    degraded = [
        finding
        for finding in findings
        if finding.severity in {"warn", "error"} or finding.code == missing_code
    ]
    if current_code in codes and not degraded:
        status = "current"
    elif "projection-cache-operation-in-progress" in codes:
        status = "updating-or-interrupted"
    elif missing_code in codes:
        status = "missing"
    elif any(finding.severity == "error" for finding in degraded):
        status = "error"
    elif degraded:
        status = "stale-or-degraded"
    else:
        status = "current"
    sample = degraded[:3] if degraded else [finding for finding in findings if finding.code == current_code][:1]
    return {
        "component": component,
        "status": status,
        "stale_reason": sample[0].code if sample else "none",
        "finding_codes": _unique_codes(codes),
        "sample_findings": [
            {
                "severity": finding.severity,
                "code": finding.code,
                "message": finding.message,
                **({"source": finding.source} if finding.source else {}),
            }
            for finding in sample
        ],
    }


def _cache_refresh_commands(artifact: dict[str, object], index: dict[str, object]) -> list[str]:
    commands: list[str] = []
    artifact_status = str(artifact.get("status") or "")
    index_status = str(index.get("status") or "")
    if artifact_status != "current" and index_status != "current":
        commands.append("mylittleharness --root <root> projection --rebuild --target all")
    elif artifact_status != "current":
        commands.append("mylittleharness --root <root> projection --rebuild --target artifacts")
    elif index_status != "current":
        commands.append("mylittleharness --root <root> projection --rebuild --target index")
    commands.append("mylittleharness --root <root> projection --inspect --target all")
    return commands


def _unique_codes(codes: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        unique.append(code)
    return unique
