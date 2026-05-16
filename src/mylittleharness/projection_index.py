from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import __version__
from .inventory import Inventory
from .models import Finding
from .projection import Projection, ProjectionSourceRecord, build_projection
from .projection_artifacts import (
    ARTIFACT_DIR_REL,
    INDEX_DIRTY_MARKER_NAME,
    PROJECTION_REBUILD_NEXT_SAFE_COMMAND,
    artifact_dir,
    clear_projection_cache_dirty_marker,
    clear_projection_cache_operation_marker,
    projection_cache_dirty_changed_paths,
    projection_cache_operation_marker_findings,
    projection_cache_dirty_marker_findings,
    projection_cache_dirty_quiet_period_pending,
    write_projection_cache_operation_marker,
)


INDEX_SCHEMA_VERSION = 1
INDEX_NAME = "search-index.sqlite3"
INDEX_REL_PATH = f"{ARTIFACT_DIR_REL}/{INDEX_NAME}"
INDEX_SIDECAR_NAMES = (
    INDEX_NAME,
    f"{INDEX_NAME}-journal",
    f"{INDEX_NAME}-shm",
    f"{INDEX_NAME}-wal",
    INDEX_DIRTY_MARKER_NAME,
)
INDEX_PUBLISH_SIDECAR_NAMES = (
    f"{INDEX_NAME}-journal",
    f"{INDEX_NAME}-shm",
    f"{INDEX_NAME}-wal",
)
INDEX_REPLACE_ATTEMPTS = 8
INDEX_REPLACE_RETRY_SECONDS = 0.025


class IncrementalIndexFallback(RuntimeError):
    pass


@dataclass(frozen=True)
class IndexShape:
    source_rows: tuple[dict[str, Any], ...]
    fts_rows: tuple[dict[str, Any], ...]
    path_rows: tuple[dict[str, Any], ...]
    source_set_hash: str
    record_set_hash: str


@dataclass(frozen=True)
class FullTextQuery:
    expression: str
    mode: str


@dataclass(frozen=True)
class FullTextSearchResult:
    source_path: str
    line_start: int
    line_end: int
    source_hash: str
    source_role: str
    source_type: str
    text: str
    provenance: str
    rank: float
    query_mode: str


def build_projection_index(inventory: Inventory) -> list[Finding]:
    findings = _boundary_preflight(inventory.root, create=True)
    if _has_errors(findings):
        return findings
    if not _fts5_is_available():
        delete_projection_index(inventory)
        return [
            Finding("info", "projection-index-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            Finding("warn", "projection-index-fts5-unavailable", "SQLite FTS5 is unavailable; direct source reads remain authoritative"),
        ]

    operation_findings = write_projection_cache_operation_marker(inventory.root, "projection-index-build")
    tmp_path = _temporary_index_path(inventory.root)
    try:
        projection = build_projection(inventory)
        shape = _index_shape(projection)
        path = index_path(inventory.root)
        with closing(sqlite3.connect(tmp_path)) as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            _create_schema(connection)
            _write_metadata(connection, inventory, projection, shape)
            _write_source_rows(connection, shape.source_rows)
            _write_fts_rows(connection, shape.fts_rows)
            _write_path_rows(connection, shape.path_rows)
            connection.commit()
        _delete_index_publish_sidecars(inventory.root)
        _replace_index_with_retry(tmp_path, path)
        clear_projection_cache_dirty_marker(inventory.root, INDEX_DIRTY_MARKER_NAME)
    except sqlite3.Error as exc:
        _delete_temporary_index_paths(inventory.root, tmp_path.name)
        return [
            Finding("info", "projection-index-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            Finding(
                "warn",
                "projection-index-build-failed",
                f"SQLite index build failed before publishing a partial index; old-good index, if present, remains advisory: {exc}",
                INDEX_REL_PATH,
            ),
        ]
    except OSError as exc:
        _delete_temporary_index_paths(inventory.root, tmp_path.name)
        return [
            Finding("info", "projection-index-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            Finding(
                "warn",
                "projection-index-build-failed",
                f"SQLite index publish failed before completing refresh; old-good index, if present, remains advisory: {exc}",
                INDEX_REL_PATH,
            ),
        ]
    finally:
        _delete_temporary_index_paths(inventory.root, tmp_path.name)
        clear_projection_cache_operation_marker(inventory.root)

    return [
        *operation_findings,
        Finding("info", "projection-index-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
        Finding(
            "info",
            "projection-index-atomic-refresh",
            "built SQLite index in a temporary file and published it only after commit; readers keep old-good index on failed refresh",
            INDEX_REL_PATH,
        ),
        Finding("info", "projection-index-build", f"wrote disposable SQLite FTS/BM25 index: {INDEX_REL_PATH}", INDEX_REL_PATH),
        Finding(
            "info",
            "projection-index-records",
            (
                f"sources={len(shape.source_rows)}; indexed_rows={len(shape.fts_rows)}; "
                f"path_rows={len(shape.path_rows)}; source_set_hash={shape.source_set_hash[:12]}; "
                f"record_set_hash={shape.record_set_hash[:12]}"
            ),
            INDEX_REL_PATH,
        ),
    ]


def inspect_projection_index(inventory: Inventory, projection: Projection | None = None) -> list[Finding]:
    projection = projection or build_projection(inventory)
    findings = _boundary_preflight(inventory.root, create=False)
    if _has_errors(findings):
        return findings

    findings.append(Finding("info", "projection-index-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL))
    findings.extend(projection_cache_operation_marker_findings(inventory.root))
    findings.extend(_unexpected_index_sidecar_findings(inventory.root))
    findings.extend(
        projection_cache_dirty_marker_findings(
            inventory.root,
            INDEX_DIRTY_MARKER_NAME,
            "projection-index-dirty",
            f"SQLite projection index was marked dirty by a mutating workflow command; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
        )
    )
    if not _fts5_is_available():
        findings.append(Finding("warn", "projection-index-fts5-unavailable", "SQLite FTS5 is unavailable; full-text retrieval is skipped"))

    path = index_path(inventory.root)
    if not path.exists():
        findings.append(
            Finding(
                "info",
                "projection-index-missing",
                "SQLite projection index is missing; direct source reads and in-memory projection remain authoritative",
                INDEX_REL_PATH,
            )
        )
        return findings
    if not path.is_file():
        findings.append(Finding("warn", "projection-index-malformed", "SQLite projection index path is not a file", INDEX_REL_PATH))
        return findings

    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            findings.extend(_integrity_findings(connection))
            tables = _table_names(connection)
            findings.extend(_schema_findings(connection, tables))
            if _has_index_shape(tables):
                metadata = _metadata(connection)
                findings.extend(_metadata_findings(inventory, projection, metadata))
                findings.extend(_metadata_row_hash_findings(connection, metadata))
                findings.extend(_source_stale_findings(connection, projection))
                findings.extend(_count_findings(connection, projection, metadata))
    except sqlite3.DatabaseError as exc:
        findings.append(
            Finding(
                "warn",
                "projection-index-corrupt",
                f"SQLite projection index is unreadable; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}: {exc}",
                INDEX_REL_PATH,
            )
        )
    except OSError as exc:
        findings.append(
            Finding(
                "warn",
                "projection-index-corrupt",
                f"SQLite projection index could not be opened; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}: {exc}",
                INDEX_REL_PATH,
            )
        )

    if not any(finding.severity == "warn" for finding in findings):
        findings.append(Finding("info", "projection-index-current", "SQLite projection index matches current source hashes and record counts", INDEX_REL_PATH))
    return findings


def delete_projection_index(inventory: Inventory) -> list[Finding]:
    findings = _boundary_preflight(inventory.root, create=False)
    if _has_errors(findings):
        return findings

    operation_findings = write_projection_cache_operation_marker(inventory.root, "projection-index-delete")
    try:
        deleted, skipped = _delete_known_index_paths(inventory.root)
    finally:
        clear_projection_cache_operation_marker(inventory.root)
    skipped_findings = [
        Finding(
            "warn",
            "projection-index-delete-skipped",
            f"directory-shaped SQLite index sidecar was preserved without recursive delete: {rel_path}",
            rel_path,
        )
        for rel_path in skipped
    ]
    if deleted:
        return [
            *operation_findings,
            Finding("info", "projection-index-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            Finding("info", "projection-index-delete", f"deleted {len(deleted)} SQLite index-owned paths", INDEX_REL_PATH),
            *skipped_findings,
        ]
    return [
        *operation_findings,
        Finding("info", "projection-index-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
        Finding("info", "projection-index-delete", f"SQLite projection index is already absent: {INDEX_REL_PATH}", INDEX_REL_PATH),
        *skipped_findings,
    ]


def rebuild_projection_index(inventory: Inventory) -> list[Finding]:
    findings = _boundary_preflight(inventory.root, create=False)
    if _has_errors(findings):
        return findings
    return [
        Finding(
            "info",
            "projection-index-rebuild",
            "rebuild uses the same old-good publish path as build; stale indexes are replaced only after a complete SQLite database is ready",
            INDEX_REL_PATH,
        ),
        *build_projection_index(inventory),
    ]


def warm_projection_index(
    inventory: Inventory,
    projection: Projection | None = None,
    quiet_period_seconds: float = 0.0,
) -> list[Finding]:
    try:
        projection = projection or build_projection(inventory)
        inspect_findings = inspect_projection_index(inventory, projection)
    except Exception as exc:
        return [
            Finding(
                "warn",
                "projection-index-warm-cache-degraded",
                f"optional SQLite warm-cache watcher inspect failed; direct source reads remain authoritative: {exc}",
                INDEX_REL_PATH,
            )
        ]

    blocking = _warm_cache_blocking_findings(inspect_findings)
    if not blocking:
        return [
            Finding(
                "info",
                "projection-index-warm-cache-current",
                "optional SQLite warm-cache watcher tick left the current source-verified index unchanged",
                INDEX_REL_PATH,
            )
        ]

    reason = blocking[0]
    if reason.code == "projection-index-dirty":
        pending, quiet_until_utc = projection_cache_dirty_quiet_period_pending(
            inventory.root,
            (INDEX_DIRTY_MARKER_NAME,),
            quiet_period_seconds,
        )
        if pending:
            return [
                Finding(
                    "info",
                    "projection-index-warm-cache-deferred",
                    (
                        "optional SQLite warm-cache daemon pulse deferred until dirty markers are quiet; "
                        f"quiet_period_seconds={quiet_period_seconds:g}; quiet_until_utc={quiet_until_utc}; "
                        "repo-visible source files remain authoritative"
                    ),
                    reason.source or INDEX_REL_PATH,
                    reason.line,
                )
            ]

    refresh_findings = _incremental_or_rebuild_projection_index(inventory, projection, reason, inspect_findings)
    refresh_findings = _validated_warm_cache_refresh_findings(inventory, refresh_findings)
    findings = [
        Finding(
            "info",
            "projection-index-warm-cache",
            (
                f"optional SQLite warm-cache daemon pulse refreshed generated index because {reason.code}; "
                f"daemon pulse watcher writes only {INDEX_REL_PATH} and cannot affect lifecycle authority"
            ),
            reason.source or INDEX_REL_PATH,
            reason.line,
        ),
        *refresh_findings,
    ]
    if any(finding.severity in {"warn", "error"} for finding in refresh_findings):
        findings.append(
            Finding(
                "info",
                "projection-index-warm-cache-degraded",
                "optional SQLite warm-cache daemon pulse degraded; direct source reads and in-memory projection remain authoritative",
                INDEX_REL_PATH,
            )
        )
    return findings


def _validated_warm_cache_refresh_findings(inventory: Inventory, refresh_findings: list[Finding]) -> list[Finding]:
    if any(finding.severity in {"warn", "error"} for finding in refresh_findings):
        return refresh_findings

    validation = _post_refresh_blocking_findings(inventory)
    if validation is None:
        return refresh_findings
    if not validation:
        return refresh_findings

    reason = validation[0]
    rebuild_findings = rebuild_projection_index(inventory)
    retry_validation = _post_refresh_blocking_findings(inventory)
    if retry_validation is None or not retry_validation:
        return [
            *refresh_findings,
            Finding(
                "info",
                "projection-index-warm-cache-validation-rebuild",
                (
                    f"post-refresh validation still saw {reason.code}; "
                    "ran one source-bound full rebuild to leave the disposable index current"
                ),
                reason.source or INDEX_REL_PATH,
                reason.line,
            ),
            *rebuild_findings,
        ]
    return [
        *refresh_findings,
        Finding(
            "warn",
            "projection-index-warm-cache-validation-degraded",
            (
                f"post-refresh validation still reports {retry_validation[0].code}; "
                "direct source reads and in-memory projection remain authoritative"
            ),
            retry_validation[0].source or INDEX_REL_PATH,
            retry_validation[0].line,
        ),
    ]


def _post_refresh_blocking_findings(inventory: Inventory) -> list[Finding] | None:
    try:
        return _warm_cache_blocking_findings(inspect_projection_index(inventory))
    except Exception:
        return None


def _incremental_or_rebuild_projection_index(
    inventory: Inventory,
    projection: Projection,
    reason: Finding,
    inspect_findings: list[Finding],
) -> list[Finding]:
    changed_paths = projection_cache_dirty_changed_paths(inventory.root, (INDEX_DIRTY_MARKER_NAME,))
    has_corrupt_or_malformed = any(
        finding.severity == "error"
        or finding.code
        in {
            "projection-index-corrupt",
            "projection-index-integrity",
            "projection-index-malformed",
            "projection-index-root-mismatch",
            "projection-index-schema",
        }
        for finding in inspect_findings
    )
    can_try_incremental = (
        changed_paths
        and reason.code in {"projection-index-dirty", "projection-index-hash", "projection-index-stale", "projection-index-count"}
        and index_path(inventory.root).is_file()
        and not has_corrupt_or_malformed
    )
    if can_try_incremental:
        incremental = incremental_projection_index(inventory, projection, changed_paths)
        needs_full_rebuild = any(
            finding.severity in {"warn", "error"}
            or finding.code in {"projection-index-incremental-fallback", "projection-index-incremental-skipped"}
            for finding in incremental
        )
        if not needs_full_rebuild:
            return incremental
        return [
            *incremental,
            Finding(
                "info",
                "projection-index-full-rebuild-fallback",
                "incremental SQLite refresh was not source-hash clean; falling back to the old-good full rebuild path",
                INDEX_REL_PATH,
            ),
            *rebuild_projection_index(inventory),
        ]

    try:
        return [
            Finding(
                "info",
                "projection-index-full-rebuild-fallback",
                (
                    f"full SQLite rebuild selected because {reason.code}; "
                    "missing, corrupt, unscoped, or markerless stale index state is recovered from source files"
                ),
                reason.source or INDEX_REL_PATH,
                reason.line,
            ),
            *rebuild_projection_index(inventory),
        ]
    except Exception as exc:
        return [
            Finding(
                "warn",
                "projection-index-warm-cache-degraded",
                (
                    f"optional SQLite warm-cache watcher refresh failed after {reason.code}; "
                    f"direct source reads remain authoritative: {exc}"
                ),
                reason.source or INDEX_REL_PATH,
                reason.line,
            )
        ]


def incremental_projection_index(
    inventory: Inventory,
    projection: Projection,
    changed_paths: tuple[str, ...],
) -> list[Finding]:
    changed = tuple(sorted({path for path in changed_paths if path}))
    if not changed:
        return [
            Finding(
                "warn",
                "projection-index-incremental-skipped",
                "incremental SQLite refresh skipped because dirty markers did not name source paths; full rebuild fallback is required",
                INDEX_REL_PATH,
            )
        ]
    findings = _boundary_preflight(inventory.root, create=True)
    if _has_errors(findings):
        return findings
    path = index_path(inventory.root)
    if not path.is_file():
        return [
            Finding(
                "warn",
                "projection-index-incremental-skipped",
                "incremental SQLite refresh skipped because no old-good index is available; full rebuild fallback is required",
                INDEX_REL_PATH,
            )
        ]

    operation_findings = write_projection_cache_operation_marker(inventory.root, "projection-index-incremental-refresh")
    tmp_path = _temporary_index_path(inventory.root)
    changed_set = set(changed)
    try:
        shape = _index_shape(projection)
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as source, closing(sqlite3.connect(tmp_path)) as destination:
            source.backup(destination)
            destination.commit()
        with closing(sqlite3.connect(tmp_path)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            preflight_findings = _connection_shape_findings(connection, inventory, projection, validate_current_hashes=False)
            if any(finding.severity in {"warn", "error"} for finding in preflight_findings):
                raise IncrementalIndexFallback(_finding_summary(preflight_findings[0]))

            _delete_rows_for_changed_paths(connection, changed)
            _replace_metadata(connection, inventory, projection, shape)
            _write_source_rows(connection, tuple(row for row in shape.source_rows if row["path"] in changed_set))
            _write_fts_rows_autoids(connection, tuple(row for row in shape.fts_rows if row["source_path"] in changed_set))
            _write_path_rows_autoids(connection, tuple(row for row in shape.path_rows if row["source_path"] in changed_set))
            connection.commit()

            validation_findings = _connection_shape_findings(connection, inventory, projection, validate_current_hashes=True)
            if any(finding.severity in {"warn", "error"} for finding in validation_findings):
                raise IncrementalIndexFallback(_finding_summary(validation_findings[0]))

        _delete_index_publish_sidecars(inventory.root)
        _replace_index_with_retry(tmp_path, path)
        clear_projection_cache_dirty_marker(inventory.root, INDEX_DIRTY_MARKER_NAME)
    except IncrementalIndexFallback as exc:
        _delete_temporary_index_paths(inventory.root, tmp_path.name)
        return [
            *operation_findings,
            Finding("info", "projection-index-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            Finding(
                "info",
                "projection-index-incremental-fallback",
                f"incremental SQLite refresh could not be source-hash reconciled; full rebuild fallback is required: {exc}",
                INDEX_REL_PATH,
            ),
        ]
    except (sqlite3.Error, OSError) as exc:
        _delete_temporary_index_paths(inventory.root, tmp_path.name)
        return [
            *operation_findings,
            Finding("info", "projection-index-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            Finding(
                "info",
                "projection-index-incremental-fallback",
                f"incremental SQLite refresh failed before publish; old-good index remains advisory and full rebuild fallback is required: {exc}",
                INDEX_REL_PATH,
            ),
        ]
    finally:
        _delete_temporary_index_paths(inventory.root, tmp_path.name)
        clear_projection_cache_operation_marker(inventory.root)

    replaced_sources = len([row for row in shape.source_rows if row["path"] in changed_set])
    replaced_fts_rows = len([row for row in shape.fts_rows if row["source_path"] in changed_set])
    replaced_path_rows = len([row for row in shape.path_rows if row["source_path"] in changed_set])
    return [
        *operation_findings,
        Finding("info", "projection-index-boundary", f"owned generated-output boundary: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
        Finding(
            "info",
            "projection-index-incremental-refresh",
            (
                f"incrementally refreshed SQLite rows for changed_paths={len(changed)}; "
                f"sources={replaced_sources}; indexed_rows={replaced_fts_rows}; path_rows={replaced_path_rows}; "
                f"source_set_hash={shape.source_set_hash[:12]}; record_set_hash={shape.record_set_hash[:12]}"
            ),
            INDEX_REL_PATH,
        ),
        Finding(
            "info",
            "projection-index-incremental-boundary",
            "incremental SQLite refresh mutates only the disposable generated index and falls back to full rebuild when hash reconciliation fails",
            INDEX_REL_PATH,
        ),
    ]


def source_verified_full_text_results(
    inventory: Inventory,
    projection: Projection,
    full_text: str | None,
    limit: int,
) -> tuple[list[Finding], tuple[FullTextSearchResult, ...]]:
    if full_text in (None, ""):
        return [], ()

    inspect_findings = inspect_projection_index(inventory, projection)
    blocking = [
        finding
        for finding in inspect_findings
        if finding.severity in {"warn", "error"} or finding.code == "projection-index-missing"
    ]
    if blocking:
        finding = blocking[0]
        return [
            Finding(
                "info",
                "projection-index-query-skipped",
                f"full-text search skipped for {full_text!r}: {finding.code}; direct exact/path search remains authoritative",
                finding.source or INDEX_REL_PATH,
                finding.line,
            )
        ], ()

    fts_query = _fts_query(full_text)
    if fts_query is None:
        return [Finding("info", "full-text-no-matches", "full-text query has no indexable terms", INDEX_REL_PATH)], ()

    source_by_path = projection.source_by_path
    findings: list[Finding] = [
        Finding(
            "info",
            "projection-index-query-current",
            f"full-text search uses current source-verified SQLite FTS/BM25 index for {full_text!r}; query_mode={fts_query.mode}",
            INDEX_REL_PATH,
        )
    ]
    results: list[FullTextSearchResult] = []
    try:
        with closing(sqlite3.connect(f"file:{index_path(inventory.root)}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT source_path, line_start, line_end, source_hash, source_role, source_type,
                       indexed_text, provenance, bm25(fts_rows) AS rank
                FROM fts_rows
                WHERE fts_rows MATCH ?
                ORDER BY rank, source_path, line_start
                LIMIT ?
                """,
                (fts_query.expression, limit),
            ).fetchall()
    except sqlite3.Error as exc:
        return [
            Finding(
                "info",
                "projection-index-query-skipped",
                f"full-text search skipped for {full_text!r}: SQLite query failed; direct exact/path search remains authoritative: {exc}",
                INDEX_REL_PATH,
            )
        ], ()

    for row in rows:
        source = source_by_path.get(str(row["source_path"]))
        if not _row_is_source_verified(source, int(row["line_start"]), str(row["source_hash"]), str(row["indexed_text"])):
            findings.append(
                Finding(
                    "info",
                    "projection-index-result-skipped",
                    f"unverified full-text result skipped: {row['source_path']}:{row['line_start']}",
                    str(row["source_path"]),
                    int(row["line_start"]),
                )
            )
            continue
        results.append(
            FullTextSearchResult(
                source_path=str(row["source_path"]),
                line_start=int(row["line_start"]),
                line_end=int(row["line_end"]),
                source_hash=str(row["source_hash"]),
                source_role=str(row["source_role"]),
                source_type=str(row["source_type"]),
                text=str(row["indexed_text"]),
                provenance=str(row["provenance"]),
                rank=float(row["rank"]),
                query_mode=fts_query.mode,
            )
        )

    if not results:
        findings.append(Finding("info", "full-text-no-matches", "no source-verified full-text matches found", INDEX_REL_PATH))
    return findings, tuple(results)


def full_text_search_findings(inventory: Inventory, projection: Projection, full_text: str | None, limit: int) -> list[Finding]:
    findings, results = source_verified_full_text_results(inventory, projection, full_text, limit)
    for result in results:
        findings.append(
            Finding(
                "info",
                "full-text-match",
                (
                    f"full-text match for {full_text!r}: rank={result.rank:.6f}; "
                    f"line_range={result.line_start}-{result.line_end}; source_hash={result.source_hash[:12]}; "
                    f"query_mode={result.query_mode}; verification=source-verified; {_trim_line(result.text)}"
                ),
                result.source_path,
                result.line_start,
            )
        )
    return findings


def index_path(root: Path) -> Path:
    return artifact_dir(root) / INDEX_NAME


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE source_records (
          path TEXT PRIMARY KEY,
          role TEXT NOT NULL,
          required INTEGER NOT NULL,
          present INTEGER NOT NULL,
          readable INTEGER NOT NULL,
          line_count INTEGER NOT NULL,
          byte_count INTEGER NOT NULL,
          heading_count INTEGER NOT NULL,
          link_count INTEGER NOT NULL,
          content_hash TEXT,
          read_error TEXT
        );
        CREATE TABLE index_rows (
          row_id INTEGER PRIMARY KEY,
          source_path TEXT NOT NULL,
          line_start INTEGER NOT NULL,
          line_end INTEGER NOT NULL,
          source_hash TEXT,
          source_role TEXT NOT NULL,
          source_type TEXT NOT NULL,
          indexed_text TEXT NOT NULL,
          provenance TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE fts_rows USING fts5(
          source_path UNINDEXED,
          line_start UNINDEXED,
          line_end UNINDEXED,
          source_hash UNINDEXED,
          source_role UNINDEXED,
          source_type UNINDEXED,
          indexed_text,
          provenance UNINDEXED
        );
        CREATE TABLE path_rows (
          row_id INTEGER PRIMARY KEY,
          row_kind TEXT NOT NULL,
          source_path TEXT NOT NULL,
          line_number INTEGER NOT NULL,
          target_path TEXT NOT NULL,
          status TEXT NOT NULL,
          resolution_kind TEXT NOT NULL,
          indexed_text TEXT NOT NULL,
          provenance TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE path_fts USING fts5(
          row_kind UNINDEXED,
          source_path UNINDEXED,
          line_number UNINDEXED,
          target_path UNINDEXED,
          status UNINDEXED,
          resolution_kind UNINDEXED,
          indexed_text,
          provenance UNINDEXED
        );
        """
    )


def _write_metadata(connection: sqlite3.Connection, inventory: Inventory, projection: Projection, shape: IndexShape) -> None:
    rows = {
        "schema_version": str(INDEX_SCHEMA_VERSION),
        "product_version": __version__,
        "index_kind": "mylittleharness-sqlite-fts-bm25-projection",
        "root": str(inventory.root),
        "root_kind": inventory.root_kind,
        "storage_boundary": ARTIFACT_DIR_REL,
        "source_set_hash": shape.source_set_hash,
        "record_set_hash": shape.record_set_hash,
        "source_count": str(projection.summary.source_count),
        "readable_source_count": str(projection.summary.readable_source_count),
        "indexed_row_count": str(len(shape.fts_rows)),
        "path_row_count": str(len(shape.path_rows)),
        "fts5_available": "true",
        "bm25_available": "true",
        "query_capabilities": json.dumps(
            {
                "full_text_search": {
                    "available": True,
                    "source_verified": True,
                    "rank": "bm25",
                    "generated_cache": True,
                },
                "exact_text_search": {
                    "source": "direct-files-and-in-memory-projection",
                    "case_sensitive": True,
                },
                "path_reference_search": {
                    "source": "direct-files-json-artifact-parity-and-sqlite-path-index",
                    "case_sensitive": True,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        "boundary_note": "repo-visible source files are authoritative; this SQLite index is disposable, rebuildable, and advisory generated output",
    }
    connection.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", sorted(rows.items()))


def _write_source_rows(connection: sqlite3.Connection, rows: tuple[dict[str, Any], ...]) -> None:
    connection.executemany(
        """
        INSERT INTO source_records(
          path, role, required, present, readable, line_count, byte_count,
          heading_count, link_count, content_hash, read_error
        )
        VALUES (:path, :role, :required, :present, :readable, :line_count, :byte_count,
                :heading_count, :link_count, :content_hash, :read_error)
        """,
        rows,
    )


def _write_fts_rows(connection: sqlite3.Connection, rows: tuple[dict[str, Any], ...]) -> None:
    connection.executemany(
        """
        INSERT INTO index_rows(
          row_id, source_path, line_start, line_end, source_hash, source_role,
          source_type, indexed_text, provenance
        )
        VALUES (:row_id, :source_path, :line_start, :line_end, :source_hash,
                :source_role, :source_type, :indexed_text, :provenance)
        """,
        rows,
    )
    connection.executemany(
        """
        INSERT INTO fts_rows(rowid, source_path, line_start, line_end, source_hash,
                             source_role, source_type, indexed_text, provenance)
        VALUES (:row_id, :source_path, :line_start, :line_end, :source_hash,
                :source_role, :source_type, :indexed_text, :provenance)
        """,
        rows,
    )


def _write_path_rows(connection: sqlite3.Connection, rows: tuple[dict[str, Any], ...]) -> None:
    connection.executemany(
        """
        INSERT INTO path_rows(
          row_id, row_kind, source_path, line_number, target_path, status,
          resolution_kind, indexed_text, provenance
        )
        VALUES (:row_id, :row_kind, :source_path, :line_number, :target_path,
                :status, :resolution_kind, :indexed_text, :provenance)
        """,
        rows,
    )
    connection.executemany(
        """
        INSERT INTO path_fts(rowid, row_kind, source_path, line_number, target_path,
                             status, resolution_kind, indexed_text, provenance)
        VALUES (:row_id, :row_kind, :source_path, :line_number, :target_path,
                :status, :resolution_kind, :indexed_text, :provenance)
        """,
        rows,
    )


def _write_fts_rows_autoids(connection: sqlite3.Connection, rows: tuple[dict[str, Any], ...]) -> None:
    connection.executemany(
        """
        INSERT INTO index_rows(
          source_path, line_start, line_end, source_hash, source_role,
          source_type, indexed_text, provenance
        )
        VALUES (:source_path, :line_start, :line_end, :source_hash,
                :source_role, :source_type, :indexed_text, :provenance)
        """,
        rows,
    )
    connection.executemany(
        """
        INSERT INTO fts_rows(source_path, line_start, line_end, source_hash,
                             source_role, source_type, indexed_text, provenance)
        VALUES (:source_path, :line_start, :line_end, :source_hash,
                :source_role, :source_type, :indexed_text, :provenance)
        """,
        rows,
    )


def _write_path_rows_autoids(connection: sqlite3.Connection, rows: tuple[dict[str, Any], ...]) -> None:
    connection.executemany(
        """
        INSERT INTO path_rows(
          row_kind, source_path, line_number, target_path, status,
          resolution_kind, indexed_text, provenance
        )
        VALUES (:row_kind, :source_path, :line_number, :target_path,
                :status, :resolution_kind, :indexed_text, :provenance)
        """,
        rows,
    )
    connection.executemany(
        """
        INSERT INTO path_fts(row_kind, source_path, line_number, target_path,
                             status, resolution_kind, indexed_text, provenance)
        VALUES (:row_kind, :source_path, :line_number, :target_path,
                :status, :resolution_kind, :indexed_text, :provenance)
        """,
        rows,
    )


def _replace_metadata(connection: sqlite3.Connection, inventory: Inventory, projection: Projection, shape: IndexShape) -> None:
    connection.execute("DELETE FROM metadata")
    _write_metadata(connection, inventory, projection, shape)


def _delete_rows_for_changed_paths(connection: sqlite3.Connection, changed_paths: tuple[str, ...]) -> None:
    placeholders = ",".join("?" for _ in changed_paths)
    parameters = tuple(changed_paths)
    connection.execute(f"DELETE FROM source_records WHERE path IN ({placeholders})", parameters)
    connection.execute(f"DELETE FROM index_rows WHERE source_path IN ({placeholders})", parameters)
    connection.execute(f"DELETE FROM fts_rows WHERE source_path IN ({placeholders})", parameters)
    connection.execute(f"DELETE FROM path_rows WHERE source_path IN ({placeholders})", parameters)
    connection.execute(f"DELETE FROM path_fts WHERE source_path IN ({placeholders})", parameters)


def _index_shape(projection: Projection) -> IndexShape:
    source_rows = tuple(_source_row(source) for source in projection.sources)
    fts_rows = tuple(_fts_rows(projection.sources))
    path_rows = tuple(_path_rows(projection))
    source_set_hash = _payload_hash(
        sorted(
            [
                {"path": row["path"], "content_hash": row["content_hash"]}
                for row in source_rows
                if row["content_hash"] is not None
            ],
            key=_payload_sort_key,
        )
    )
    record_set_hash = _payload_hash(
        sorted(
            [
                {
                    "source_path": row["source_path"],
                    "line_start": row["line_start"],
                    "line_end": row["line_end"],
                    "source_hash": row["source_hash"],
                    "text_hash": _text_hash(row["indexed_text"]),
                }
                for row in fts_rows
            ]
            + [
                {
                    "row_kind": row["row_kind"],
                    "source_path": row["source_path"],
                    "line_number": row["line_number"],
                    "target_path": row["target_path"],
                    "status": row["status"],
                    "resolution_kind": row["resolution_kind"],
                    "text_hash": _text_hash(row["indexed_text"]),
                }
                for row in path_rows
            ],
            key=_payload_sort_key,
        )
    )
    return IndexShape(
        source_rows=source_rows,
        fts_rows=fts_rows,
        path_rows=path_rows,
        source_set_hash=source_set_hash,
        record_set_hash=record_set_hash,
    )


def _source_row(source: ProjectionSourceRecord) -> dict[str, Any]:
    return {
        "path": source.path,
        "role": source.role,
        "required": int(source.required),
        "present": int(source.present),
        "readable": int(source.readable),
        "line_count": source.line_count,
        "byte_count": source.byte_count,
        "heading_count": source.heading_count,
        "link_count": source.link_count,
        "content_hash": source.content_hash,
        "read_error": source.read_error,
    }


def _fts_rows(sources: tuple[ProjectionSourceRecord, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    row_id = 1
    for source in sources:
        if not source.readable or source.content_hash is None:
            continue
        for line_number, line in enumerate(source.content.splitlines(), start=1):
            if line == "":
                continue
            rows.append(
                {
                    "row_id": row_id,
                    "source_path": source.path,
                    "line_start": line_number,
                    "line_end": line_number,
                    "source_hash": source.content_hash,
                    "source_role": source.role,
                    "source_type": "inventory-surface",
                    "indexed_text": line,
                    "provenance": f"{source.path}:{line_number}",
                }
            )
            row_id += 1
    return rows


def _path_rows(projection: Projection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    row_id = 1
    for source in projection.sources:
        rows.append(
            {
                "row_id": row_id,
                "row_kind": "source",
                "source_path": source.path,
                "line_number": 0,
                "target_path": source.path,
                "status": "present" if source.present else "missing",
                "resolution_kind": "inventory-source",
                "indexed_text": source.path,
                "provenance": source.path,
            }
        )
        row_id += 1
    for record in projection.links:
        rows.append(
            {
                "row_id": row_id,
                "row_kind": "reference",
                "source_path": record.source,
                "line_number": record.line,
                "target_path": record.target,
                "status": record.status,
                "resolution_kind": record.resolution_kind,
                "indexed_text": f"{record.source} {record.target}",
                "provenance": f"{record.source}:{record.line}->{record.target}",
            }
        )
        row_id += 1
    for edge in projection.relationship_edges:
        rows.append(
            {
                "row_id": row_id,
                "row_kind": "relationship",
                "source_path": edge.source_path,
                "line_number": edge.line or 0,
                "target_path": edge.target,
                "status": edge.status,
                "resolution_kind": edge.relation,
                "indexed_text": f"{edge.source} {edge.relation} {edge.target}",
                "provenance": f"{edge.source_path}:{edge.line or 0}->{edge.target}",
            }
        )
        row_id += 1
    return rows


def _integrity_findings(connection: sqlite3.Connection) -> list[Finding]:
    try:
        rows = connection.execute("PRAGMA quick_check").fetchall()
    except sqlite3.DatabaseError as exc:
        return [
            Finding(
                "warn",
                "projection-index-corrupt",
                f"SQLite quick_check failed; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}: {exc}",
                INDEX_REL_PATH,
            )
        ]
    if rows and str(rows[0][0]).lower() == "ok":
        return []
    rendered = ", ".join(str(row[0]) for row in rows[:3]) if rows else "no result"
    return [Finding("warn", "projection-index-integrity", f"SQLite quick_check did not return ok: {rendered}", INDEX_REL_PATH)]


def _schema_findings(connection: sqlite3.Connection, tables: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    expected_tables = {"metadata", "source_records", "index_rows", "fts_rows", "path_rows", "path_fts"}
    for name in sorted(expected_tables - tables):
        findings.append(Finding("warn", "projection-index-malformed", f"expected SQLite index table is missing: {name}", INDEX_REL_PATH))

    expected_columns = {
        "metadata": {"key", "value"},
        "source_records": {"path", "role", "required", "present", "readable", "line_count", "byte_count", "heading_count", "link_count", "content_hash", "read_error"},
        "index_rows": {"row_id", "source_path", "line_start", "line_end", "source_hash", "source_role", "source_type", "indexed_text", "provenance"},
        "fts_rows": {"source_path", "line_start", "line_end", "source_hash", "source_role", "source_type", "indexed_text", "provenance"},
        "path_rows": {"row_id", "row_kind", "source_path", "line_number", "target_path", "status", "resolution_kind", "indexed_text", "provenance"},
        "path_fts": {"row_kind", "source_path", "line_number", "target_path", "status", "resolution_kind", "indexed_text", "provenance"},
    }
    for table, columns in expected_columns.items():
        if table not in tables:
            continue
        present = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        missing = columns - present
        if missing:
            findings.append(
                Finding("warn", "projection-index-malformed", f"{table} is missing expected columns: {', '.join(sorted(missing))}", INDEX_REL_PATH)
            )
    return findings


def _metadata_findings(inventory: Inventory, projection: Projection, metadata: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    if metadata.get("schema_version") != str(INDEX_SCHEMA_VERSION):
        findings.append(
            Finding(
                "warn",
                "projection-index-schema",
                f"unsupported SQLite index schema {metadata.get('schema_version')!r}; expected {INDEX_SCHEMA_VERSION}",
                INDEX_REL_PATH,
            )
        )
    if metadata.get("root") and _normalize_path_text(metadata["root"]) != _normalize_path_text(str(inventory.root)):
        findings.append(
            Finding(
                "warn",
                "projection-index-root-mismatch",
                f"index root {metadata['root']} does not match current root {inventory.root}",
                INDEX_REL_PATH,
            )
        )
    shape = _index_shape(projection)
    if metadata.get("source_set_hash") and metadata.get("source_set_hash") != shape.source_set_hash:
        findings.append(
            Finding(
                "warn",
                "projection-index-hash",
                f"source-set hash does not match current source files; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                INDEX_REL_PATH,
            )
        )
    if metadata.get("record_set_hash") and metadata.get("record_set_hash") != shape.record_set_hash:
        findings.append(
            Finding(
                "warn",
                "projection-index-hash",
                f"record-set hash does not match current indexed source rows; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                INDEX_REL_PATH,
            )
        )
    return findings


def _metadata_identity_findings(inventory: Inventory, metadata: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    if metadata.get("schema_version") != str(INDEX_SCHEMA_VERSION):
        findings.append(
            Finding(
                "warn",
                "projection-index-schema",
                f"unsupported SQLite index schema {metadata.get('schema_version')!r}; expected {INDEX_SCHEMA_VERSION}",
                INDEX_REL_PATH,
            )
        )
    if metadata.get("root") and _normalize_path_text(metadata["root"]) != _normalize_path_text(str(inventory.root)):
        findings.append(
            Finding(
                "warn",
                "projection-index-root-mismatch",
                f"index root {metadata['root']} does not match current root {inventory.root}",
                INDEX_REL_PATH,
            )
        )
    return findings


def _metadata_row_hash_findings(connection: sqlite3.Connection, metadata: dict[str, str]) -> list[Finding]:
    try:
        source_set_hash = _source_set_hash_from_connection(connection)
        record_set_hash = _record_set_hash_from_connection(connection)
    except sqlite3.DatabaseError as exc:
        return [Finding("warn", "projection-index-malformed", f"SQLite index row hashes could not be read: {exc}", INDEX_REL_PATH)]

    findings: list[Finding] = []
    if metadata.get("source_set_hash") and metadata.get("source_set_hash") != source_set_hash:
        findings.append(
            Finding(
                "warn",
                "projection-index-hash",
                f"stored source-set hash does not match SQLite source_records rows; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                INDEX_REL_PATH,
            )
        )
    if metadata.get("record_set_hash") and metadata.get("record_set_hash") != record_set_hash:
        findings.append(
            Finding(
                "warn",
                "projection-index-hash",
                f"stored record-set hash does not match SQLite index/path rows; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                INDEX_REL_PATH,
            )
        )
    return findings


def _connection_shape_findings(
    connection: sqlite3.Connection,
    inventory: Inventory,
    projection: Projection,
    *,
    validate_current_hashes: bool,
) -> list[Finding]:
    findings = _integrity_findings(connection)
    tables = _table_names(connection)
    findings.extend(_schema_findings(connection, tables))
    if not _has_index_shape(tables):
        return findings

    metadata = _metadata(connection)
    findings.extend(_metadata_identity_findings(inventory, metadata))
    findings.extend(_metadata_row_hash_findings(connection, metadata))
    if validate_current_hashes:
        findings.extend(_metadata_findings(inventory, projection, metadata))
        findings.extend(_source_stale_findings(connection, projection))
        findings.extend(_count_findings(connection, projection, metadata))
    return findings


def _source_set_hash_from_connection(connection: sqlite3.Connection) -> str:
    rows = connection.execute("SELECT path, content_hash FROM source_records WHERE content_hash IS NOT NULL").fetchall()
    payload = sorted(
        [
            {"path": str(row["path"]), "content_hash": str(row["content_hash"])}
            for row in rows
            if row["content_hash"] is not None
        ],
        key=_payload_sort_key,
    )
    return _payload_hash(payload)


def _record_set_hash_from_connection(connection: sqlite3.Connection) -> str:
    fts_rows = connection.execute(
        "SELECT source_path, line_start, line_end, source_hash, indexed_text FROM index_rows"
    ).fetchall()
    path_rows = connection.execute(
        "SELECT row_kind, source_path, line_number, target_path, status, resolution_kind, indexed_text FROM path_rows"
    ).fetchall()
    payload = sorted(
        [
            {
                "source_path": str(row["source_path"]),
                "line_start": int(row["line_start"]),
                "line_end": int(row["line_end"]),
                "source_hash": str(row["source_hash"] or ""),
                "text_hash": _text_hash(str(row["indexed_text"])),
            }
            for row in fts_rows
        ]
        + [
            {
                "row_kind": str(row["row_kind"]),
                "source_path": str(row["source_path"]),
                "line_number": int(row["line_number"]),
                "target_path": str(row["target_path"]),
                "status": str(row["status"]),
                "resolution_kind": str(row["resolution_kind"]),
                "text_hash": _text_hash(str(row["indexed_text"])),
            }
            for row in path_rows
        ],
        key=_payload_sort_key,
    )
    return _payload_hash(payload)


def _source_stale_findings(connection: sqlite3.Connection, projection: Projection) -> list[Finding]:
    findings: list[Finding] = []
    try:
        rows = connection.execute("SELECT path, content_hash FROM source_records WHERE content_hash IS NOT NULL ORDER BY path").fetchall()
    except sqlite3.DatabaseError as exc:
        return [Finding("warn", "projection-index-malformed", f"source_records cannot be read: {exc}", INDEX_REL_PATH)]

    stored_hashes = {str(row["path"]): row["content_hash"] for row in rows}
    current_hashes = {source.path: source.content_hash for source in projection.sources if source.content_hash is not None}
    changed = [path for path, current_hash in sorted(current_hashes.items()) if stored_hashes.get(path) != current_hash]
    removed = [path for path in sorted(stored_hashes) if path not in current_hashes]
    if changed or removed:
        sample = ", ".join((changed + removed)[:5])
        findings.append(
            Finding(
                "warn",
                "projection-index-stale",
                f"indexed source hashes differ from current files; sample={sample}; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                INDEX_REL_PATH,
            )
        )
    return findings


def _count_findings(connection: sqlite3.Connection, projection: Projection, metadata: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    shape = _index_shape(projection)
    source_count = _safe_count(connection, "source_records")
    index_count = _safe_count(connection, "index_rows")
    fts_count = _safe_count(connection, "fts_rows")
    path_count = _safe_count(connection, "path_rows")
    path_fts_count = _safe_count(connection, "path_fts")
    if source_count is None or index_count is None or fts_count is None or path_count is None or path_fts_count is None:
        findings.append(Finding("warn", "projection-index-malformed", "SQLite index row counts could not be read", INDEX_REL_PATH))
        return findings
    if source_count != projection.summary.source_count or _metadata_int(metadata, "source_count") != projection.summary.source_count:
        findings.append(
            Finding(
                "warn",
                "projection-index-count",
                f"source count differs from current projection; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                INDEX_REL_PATH,
            )
        )
    if index_count != len(shape.fts_rows) or fts_count != len(shape.fts_rows) or _metadata_int(metadata, "indexed_row_count") != len(shape.fts_rows):
        findings.append(
            Finding(
                "warn",
                "projection-index-count",
                f"indexed row count differs from current projection; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                INDEX_REL_PATH,
            )
        )
    if index_count != fts_count:
        findings.append(
            Finding(
                "warn",
                "projection-index-count",
                f"index_rows and fts_rows counts differ; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                INDEX_REL_PATH,
            )
        )
    if path_count != len(shape.path_rows) or path_fts_count != len(shape.path_rows) or _metadata_int(metadata, "path_row_count") != len(shape.path_rows):
        findings.append(
            Finding(
                "warn",
                "projection-index-count",
                f"path row count differs from current projection; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                INDEX_REL_PATH,
            )
        )
    if path_count != path_fts_count:
        findings.append(
            Finding(
                "warn",
                "projection-index-count",
                f"path_rows and path_fts counts differ; rebuild recommended; {PROJECTION_REBUILD_NEXT_SAFE_COMMAND}",
                INDEX_REL_PATH,
            )
        )
    return findings


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        return {str(row["key"]): str(row["value"]) for row in connection.execute("SELECT key, value FROM metadata").fetchall()}
    except sqlite3.DatabaseError:
        return {}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    try:
        return {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
        }
    except sqlite3.DatabaseError:
        return set()


def _has_index_shape(tables: set[str]) -> bool:
    return {"metadata", "source_records", "index_rows", "fts_rows", "path_rows", "path_fts"}.issubset(tables)


def _warm_cache_blocking_findings(findings: list[Finding]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.severity in {"warn", "error"} or finding.code == "projection-index-missing"
    ]


def _safe_count(connection: sqlite3.Connection, table: str) -> int | None:
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except (sqlite3.DatabaseError, TypeError, IndexError):
        return None


def _metadata_int(metadata: dict[str, str], key: str) -> int | None:
    try:
        return int(metadata.get(key, ""))
    except ValueError:
        return None


def _unexpected_index_sidecar_findings(root: Path) -> list[Finding]:
    projection_dir = artifact_dir(root)
    if not projection_dir.exists() or not projection_dir.is_dir():
        return []
    expected = set(INDEX_SIDECAR_NAMES)
    findings: list[Finding] = []
    for child in sorted(projection_dir.iterdir(), key=lambda item: item.name.lower()):
        if child.name.startswith(INDEX_NAME) and child.name not in expected:
            findings.append(
                Finding(
                    "warn",
                    "projection-index-unexpected-sidecar",
                    f"unexpected SQLite index sidecar inside owned boundary: {child.name}",
                    child.relative_to(root).as_posix(),
                )
            )
    return findings


def _delete_known_index_paths(root: Path) -> tuple[list[str], list[str]]:
    projection_dir = artifact_dir(root)
    if not projection_dir.exists():
        return [], []
    deleted: list[str] = []
    skipped: list[str] = []
    for name in INDEX_SIDECAR_NAMES:
        path = projection_dir / name
        if not path.exists():
            continue
        if not _is_under_artifact_dir(root, path):
            continue
        if path.is_dir() and not path.is_symlink():
            skipped.append(path.relative_to(root).as_posix())
            continue
        path.unlink()
        deleted.append(path.relative_to(root).as_posix())
    return deleted, skipped


def _delete_index_publish_sidecars(root: Path) -> None:
    projection_dir = artifact_dir(root)
    if not projection_dir.exists():
        return
    for name in INDEX_PUBLISH_SIDECAR_NAMES:
        path = projection_dir / name
        if not path.exists() or not _is_under_artifact_dir(root, path):
            continue
        if path.is_dir() and not path.is_symlink():
            continue
        path.unlink()


def _temporary_index_path(root: Path) -> Path:
    return artifact_dir(root) / f".{INDEX_NAME}.{uuid4().hex}.tmp"


def _replace_index_with_retry(tmp_path: Path, path: Path) -> None:
    last_error: OSError | None = None
    for attempt in range(INDEX_REPLACE_ATTEMPTS):
        try:
            tmp_path.replace(path)
            return
        except OSError as exc:
            last_error = exc
            if attempt == INDEX_REPLACE_ATTEMPTS - 1:
                break
            time.sleep(INDEX_REPLACE_RETRY_SECONDS * (attempt + 1))
    if last_error is not None:
        raise last_error


def _delete_temporary_index_paths(root: Path, tmp_name: str) -> None:
    projection_dir = artifact_dir(root)
    if not projection_dir.exists():
        return
    for path in projection_dir.glob(f"{tmp_name}*"):
        if not _is_under_artifact_dir(root, path):
            continue
        if path.is_dir() and not path.is_symlink():
            continue
        try:
            path.unlink()
        except OSError:
            pass


def _boundary_preflight(root: Path, create: bool) -> list[Finding]:
    findings: list[Finding] = []
    root_resolved = root.resolve()
    current = root
    for part in ARTIFACT_DIR_REL.split("/"):
        current = current / part
        rel_path = current.relative_to(root).as_posix()
        if current.exists():
            if current.is_symlink():
                findings.append(Finding("error", "projection-index-boundary", f"refused symlink in projection index boundary: {rel_path}", rel_path))
                return findings
            if not current.is_dir():
                findings.append(Finding("error", "projection-index-boundary", f"projection index boundary path is not a directory: {rel_path}", rel_path))
                return findings
            continue
        if create:
            current.mkdir()

    projection_dir = artifact_dir(root)
    if projection_dir.exists():
        try:
            projection_dir.resolve().relative_to(root_resolved)
        except ValueError:
            findings.append(Finding("error", "projection-index-boundary", f"projection index boundary escapes target root: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL))
    return findings


def _is_under_artifact_dir(root: Path, path: Path) -> bool:
    boundary = artifact_dir(root).resolve()
    try:
        path.resolve().relative_to(boundary)
        return True
    except ValueError:
        return False


def _fts5_is_available() -> bool:
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(value)")
        return True
    except sqlite3.Error:
        return False


def _fts_query(text: str) -> FullTextQuery | None:
    terms = re.findall(r"[A-Za-z0-9_]+", text)
    if not terms:
        return None
    if _has_explicit_fts_syntax(text, terms) or len(terms) == 1:
        return FullTextQuery(" ".join(terms), "fts5-bm25")
    return FullTextQuery(" OR ".join(_dedupe_terms(terms)), "fts5-bm25-relaxed-or")


def _has_explicit_fts_syntax(text: str, terms: list[str]) -> bool:
    if any(marker in text for marker in ('"', "(", ")", ":", "*")):
        return True
    return any(term in {"AND", "OR", "NOT", "NEAR"} for term in terms)


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(term)
    return deduped


def _row_is_source_verified(source: ProjectionSourceRecord | None, line_number: int, source_hash: str, indexed_text: str) -> bool:
    if source is None or source.content_hash != source_hash or not source.readable:
        return False
    lines = source.content.splitlines()
    if line_number < 1 or line_number > len(lines):
        return False
    return lines[line_number - 1] == indexed_text


def _payload_hash(payload: Any) -> str:
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _payload_sort_key(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _finding_summary(finding: Finding) -> str:
    source = f" ({finding.source})" if finding.source else ""
    return f"{finding.code}{source}: {finding.message}"


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _normalize_path_text(value: str) -> str:
    return value.replace("/", "\\").rstrip("\\").casefold()


def _trim_line(line: str, limit: int = 140) -> str:
    compact = re.sub(r"\s+", " ", line.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _has_errors(findings: list[Finding]) -> bool:
    return any(finding.severity == "error" for finding in findings)
