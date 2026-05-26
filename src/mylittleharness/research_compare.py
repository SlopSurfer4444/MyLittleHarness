from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from .atomic_files import AtomicFileDelete, AtomicFileWrite, FileTransactionError, apply_file_transaction
from .command_discovery import rails_not_cognition_boundary_finding
from .inventory import Inventory
from .models import Finding
from .parsing import extract_path_refs, parse_frontmatter
from .reporting import RouteWriteEvidence, route_write_findings
from .research_distill import distill_research_text
from .root_boundary import source_path_boundary_violation


RESEARCH_DIR_REL = "project/research"
ARCHIVE_RESEARCH_DIR_REL = "project/archive/reference/research"
RESEARCH_COMPARE_SOURCE = "research-compare cli"
NON_AUTHORITY_NOTE = (
    "research comparison is a non-authority provenance/comparison matrix and proposal input; it cannot choose truth, "
    "rank importance, promote findings, approve lifecycle, specs, plans, source-archive decisions, roadmap status, "
    "staging, commit, or next-plan opening."
)
_ALLOWED_SOURCE_STATUSES = {"imported", "distilled"}
_RESERVED_SLUGS = {
    "aux",
    "con",
    "nul",
    "prn",
    "project",
    "research",
    *{f"com{index}" for index in range(1, 10)},
    *{f"lpt{index}" for index in range(1, 10)},
}


@dataclass(frozen=True)
class ResearchCompareRequest:
    sources: tuple[str, ...]
    title: str = ""
    target: str = ""
    topic: str = ""
    archive_sources: bool = False
    repair_links: bool = False


@dataclass(frozen=True)
class ResearchCompareSource:
    rel_path: str
    path: Path
    text: str
    source_hash: str
    read_error: str
    title: str
    status: str
    archive_rel: str = ""
    archive_path: Path | None = None
    archived_text: str = ""


@dataclass(frozen=True)
class ResearchCompareExtraction:
    shared_candidates: tuple[str, ...]
    source_unique_candidates: tuple[str, ...]
    conflicts: tuple[str, ...]
    unresolved_gaps: tuple[str, ...]
    source_links: tuple[str, ...]
    route_proposals: tuple[str, ...]


@dataclass(frozen=True)
class ResearchCompareTarget:
    sources: tuple[ResearchCompareSource, ...]
    title: str
    topic: str
    rel_path: str
    path: Path
    extraction: ResearchCompareExtraction
    link_repairs: tuple[tuple[str, Path, str], ...] = ()


def make_research_compare_request(
    sources: Sequence[str] | None,
    *,
    title: str | None = None,
    target: str | None = None,
    topic: str | None = None,
    archive_sources: bool = False,
    repair_links: bool = False,
) -> ResearchCompareRequest:
    return ResearchCompareRequest(
        sources=tuple(_normalize_rel(source) for source in (sources or ()) if _normalize_rel(source)),
        title=_normalized_note(title),
        target=_normalize_rel(target),
        topic=_normalized_note(topic),
        archive_sources=bool(archive_sources),
        repair_links=bool(repair_links),
    )


def research_compare_dry_run_findings(inventory: Inventory, request: ResearchCompareRequest) -> list[Finding]:
    target = _research_compare_target(inventory, request)
    findings = [
        Finding("info", "research-compare-dry-run", "research compare proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    errors = _research_compare_preflight_errors(inventory, request, target)
    if target:
        findings.extend(_target_findings(target, apply=False))
    if target and not errors:
        if not any(source.read_error for source in target.sources):
            rendered, render_findings = _render_research_compare(inventory.root, target)
            findings.extend(render_findings)
            findings.extend(route_write_findings("research-compare-route-write", _route_write_plan(target, rendered), apply=False))
            findings.extend(_archive_plan_findings(target, apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "research-compare-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before comparing research",
            )
        )
        return findings
    findings.extend(_boundary_findings(_target_archives_sources(target)))
    findings.append(
        Finding(
            "info",
            "research-compare-validation-posture",
            "apply would write one compared research artifact in a live operating root; dry-run writes no files",
            target.rel_path if target else RESEARCH_DIR_REL,
        )
    )
    return findings


def research_compare_apply_findings(inventory: Inventory, request: ResearchCompareRequest) -> list[Finding]:
    target = _research_compare_target(inventory, request)
    errors = _research_compare_preflight_errors(inventory, request, target)
    if errors:
        return errors
    assert target is not None

    rendered, render_findings = _render_research_compare(inventory.root, target)
    write_evidence = _route_write_plan(target, rendered)
    operations = [_atomic_write(target.path, rendered)]
    for source in target.sources:
        if not source.archive_path or not source.archived_text:
            continue
        operations.append(_atomic_write(source.archive_path, source.archived_text))
    for _rel_path, path, text in target.link_repairs:
        operations.append(_atomic_write(path, text))
    for source in target.sources:
        if source.archive_path:
            operations.append(AtomicFileDelete(source.path, _backup_path(source.path)))
    try:
        cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
    except (OSError, FileTransactionError) as exc:
        return [Finding("error", "research-compare-refused", f"research compare apply failed before all target writes completed: {exc}", target.rel_path)]

    findings = [
        Finding("info", "research-compare-apply", "research compare apply started"),
        _root_posture_finding(inventory),
        *_target_findings(target, apply=True),
        *render_findings,
        Finding("info", "research-compare-written", "created compared research artifact", target.rel_path),
        *route_write_findings("research-compare-route-write", write_evidence, apply=True),
        *_archive_plan_findings(target, apply=True),
        *_boundary_findings(_target_archives_sources(target)),
        Finding(
            "info",
            "research-compare-validation-posture",
            "run check after apply to verify the live operating root remains healthy; compared research remains non-authority until promoted",
            target.rel_path,
        ),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "research-compare-backup-cleanup", warning, target.rel_path))
    return findings


def compare_research_texts(sources: Sequence[tuple[str, str]]) -> ResearchCompareExtraction:
    source_rows = tuple((rel, text, distill_research_text(rel, text)) for rel, text in sources)
    candidate_records: list[tuple[str, str]] = []
    gap_records: list[tuple[str, str]] = []
    source_links: list[str] = []
    route_proposals: list[str] = []
    for rel, _text, extraction in source_rows:
        source_links.append(rel)
        source_links.extend(extraction.source_links)
        route_proposals.extend(extraction.route_proposals)
        candidate_records.extend((rel, item) for item in extraction.accepted_candidates)
        gap_records.extend((rel, item) for item in extraction.unresolved_gaps)

    shared_candidates = _shared_candidate_summaries(candidate_records)
    shared_keys = _shared_candidate_keys(candidate_records)
    source_unique_candidates = [
        f"`{rel}`: {item}"
        for rel, item in candidate_records
        if _candidate_match_key(item) not in shared_keys and not any(route in shared_keys for route in _route_refs(item))
    ]
    conflicts = _conflict_summaries(candidate_records, gap_records)
    unresolved_gaps = [f"`{rel}`: {item}" for rel, item in gap_records]
    return ResearchCompareExtraction(
        shared_candidates=_bounded_items(shared_candidates, limit=20),
        source_unique_candidates=_bounded_items(source_unique_candidates, limit=30),
        conflicts=_bounded_items(conflicts, limit=30),
        unresolved_gaps=_bounded_items(unresolved_gaps, limit=30),
        source_links=_bounded_items(_dedupe(source_links), limit=40),
        route_proposals=_bounded_items(_dedupe(route_proposals), limit=40),
    )


def _research_compare_target(inventory: Inventory, request: ResearchCompareRequest) -> ResearchCompareTarget | None:
    source_rels = tuple(request.sources)
    archive_rels = _archive_rels_for_sources(source_rels) if request.archive_sources else {}
    sources = tuple(_research_compare_source(inventory.root, rel, archive_rels.get(rel, "")) for rel in source_rels)
    title = request.title or _default_compare_title(sources)
    rel_path = request.target or _default_compare_rel(title)
    if not rel_path:
        return None
    sources = tuple(_source_with_archived_text(source, rel_path) for source in sources)
    extraction = compare_research_texts(tuple((source.rel_path, source.text) for source in sources if source.text and not source.read_error))
    link_repairs = _planned_link_repairs(inventory, {source.rel_path: source.archive_rel for source in sources if source.archive_rel}) if request.repair_links else ()
    return ResearchCompareTarget(
        sources=sources,
        title=title,
        topic=request.topic or title,
        rel_path=rel_path,
        path=inventory.root / rel_path,
        extraction=extraction,
        link_repairs=link_repairs,
    )


def _research_compare_source(root: Path, rel_path: str, archive_rel: str = "") -> ResearchCompareSource:
    path = root / rel_path
    text = ""
    source_hash = ""
    read_error = ""
    conflict = _root_relative_path_conflict(rel_path)
    boundary_violation = None if conflict else source_path_boundary_violation(root, path, label="research compare source")
    if boundary_violation is not None:
        read_error = boundary_violation.message
    elif not conflict:
        text, source_hash, read_error = _source_snapshot(path)
    frontmatter = parse_frontmatter(text) if text else None
    title = _title_from_source(text, rel_path)
    status = ""
    if frontmatter and frontmatter.has_frontmatter:
        status = _normalized_note(frontmatter.data.get("status")).lower()
    return ResearchCompareSource(
        rel_path=rel_path,
        path=path,
        text=text,
        source_hash=source_hash,
        read_error=read_error,
        title=title,
        status=status,
        archive_rel=archive_rel,
        archive_path=(root / archive_rel) if archive_rel else None,
    )


def _research_compare_preflight_errors(
    inventory: Inventory,
    request: ResearchCompareRequest,
    target: ResearchCompareTarget | None,
) -> list[Finding]:
    errors: list[Finding] = []
    if len(request.sources) < 2:
        errors.append(Finding("error", "research-compare-refused", "--source must be supplied at least twice with distinct project/research/*.md artifacts"))
    duplicate_sources = sorted(source for source in set(request.sources) if request.sources.count(source) > 1)
    for source in duplicate_sources:
        errors.append(Finding("error", "research-compare-refused", "duplicate source research artifact", source))
    for source_rel in request.sources:
        if _root_relative_path_conflict(source_rel):
            errors.append(Finding("error", "research-compare-refused", f"source {_root_relative_path_conflict(source_rel)}", source_rel))
        elif not source_rel.startswith(f"{RESEARCH_DIR_REL}/") or not source_rel.endswith(".md"):
            errors.append(Finding("error", "research-compare-refused", f"source must be under {RESEARCH_DIR_REL}/*.md", source_rel))
    if request.repair_links and not request.archive_sources:
        errors.append(Finding("error", "research-compare-refused", "--repair-links requires --archive-sources"))
    if request.target and _root_relative_path_conflict(request.target):
        errors.append(Finding("error", "research-compare-refused", f"target {_root_relative_path_conflict(request.target)}", request.target))

    if inventory.root_kind == "product_source_fixture":
        errors.append(
            Finding(
                "error",
                "research-compare-refused",
                "target is a product-source compatibility fixture; research-compare --apply is refused",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(
            Finding(
                "error",
                "research-compare-refused",
                "target is fallback/archive or generated-output evidence; research-compare --apply is refused",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "research-compare-refused", f"target root kind is {inventory.root_kind}; research compare requires a live operating root"))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "research-compare-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "research-compare-refused", "project-state.md frontmatter is required for research compare apply", state.rel_path))
    elif state.frontmatter.errors:
        errors.append(Finding("error", "research-compare-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "research-compare-refused", "project-state.md is not a regular file", state.rel_path))
    elif state.path.is_symlink():
        errors.append(Finding("error", "research-compare-refused", "project-state.md is a symlink", state.rel_path))

    research_dir = inventory.root / RESEARCH_DIR_REL
    if _path_escapes_root(inventory.root, research_dir):
        errors.append(Finding("error", "research-compare-refused", "research directory path escapes the target root", RESEARCH_DIR_REL))
    for parent in _parents_between(inventory.root, research_dir):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "research-compare-refused", f"research directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "research-compare-refused", f"research directory contains a non-directory segment: {rel}", rel))

    if target:
        for source in target.sources:
            if _path_escapes_root(inventory.root, source.path):
                errors.append(Finding("error", "research-compare-refused", "source research path escapes the target root", source.rel_path))
            elif source.path.exists():
                if source.path.is_symlink():
                    errors.append(Finding("error", "research-compare-refused", "source research artifact is a symlink", source.rel_path))
                elif not source.path.is_file():
                    errors.append(Finding("error", "research-compare-refused", "source research artifact path exists but is not a regular file", source.rel_path))
                elif source.read_error:
                    errors.append(Finding("error", "research-compare-refused", source.read_error, source.rel_path))
                elif source.status not in _ALLOWED_SOURCE_STATUSES:
                    errors.append(
                        Finding(
                            "error",
                            "research-compare-refused",
                            "source research artifact must have status imported or distilled",
                            source.rel_path,
                        )
                    )
            else:
                errors.append(Finding("error", "research-compare-refused", "source research artifact does not exist", source.rel_path))

            if source.archive_rel:
                errors.extend(_archive_errors(inventory, source.archive_rel, source.archive_path))
                if source.archive_rel == target.rel_path:
                    errors.append(Finding("error", "research-compare-refused", "archive target must be distinct from comparison target", source.archive_rel))

        if not target.rel_path.startswith(f"{RESEARCH_DIR_REL}/") or not target.rel_path.endswith(".md"):
            errors.append(Finding("error", "research-compare-refused", f"target must be under {RESEARCH_DIR_REL}/*.md", target.rel_path))
        if target.rel_path in request.sources:
            errors.append(Finding("error", "research-compare-refused", "target must be distinct from source research artifacts", target.rel_path))
        if _path_escapes_root(inventory.root, target.path):
            errors.append(Finding("error", "research-compare-refused", "target research path escapes the target root", target.rel_path))
        elif target.path.exists():
            if target.path.is_symlink():
                errors.append(Finding("error", "research-compare-refused", "target research artifact is a symlink; overwrite is refused", target.rel_path))
            elif not target.path.is_file():
                errors.append(Finding("error", "research-compare-refused", "target research artifact path exists but is not a regular file", target.rel_path))
            else:
                errors.append(Finding("error", "research-compare-refused", "target research artifact already exists; choose a new --target", target.rel_path))
        archive_rels = [source.archive_rel for source in target.sources if source.archive_rel]
        duplicate_archives = sorted(rel for rel in set(archive_rels) if archive_rels.count(rel) > 1)
        for archive_rel in duplicate_archives:
            errors.append(Finding("error", "research-compare-refused", "duplicate archive target", archive_rel))
    return errors


def _render_research_compare(root: Path, target: ResearchCompareTarget) -> tuple[str, list[Finding]]:
    today = date.today().isoformat()
    frontmatter = [
        "---",
        'status: "compared"',
        f'topic: "{_yaml_double_quoted_value(target.topic)}"',
        f'title: "{_yaml_double_quoted_value(target.title)}"',
        f'created: "{today}"',
        f'last_reviewed: "{today}"',
        f'source_type: "{RESEARCH_COMPARE_SOURCE}"',
        'authority: "non-authoritative comparison; candidate ideas only"',
        "compared_sources:",
        *(f'  - "{_yaml_double_quoted_value(_source_reference_rel(source))}"' for source in target.sources),
        *(
            ["original_sources:", *(f'  - "{_yaml_double_quoted_value(source.rel_path)}"' for source in target.sources)]
            if any(source.archive_rel for source in target.sources)
            else []
        ),
        "source_hashes:",
        *(f'  - "{_yaml_double_quoted_value(f"{source.rel_path} sha256={source.source_hash}")}"' for source in target.sources),
        "---",
    ]
    lines = [
        *frontmatter,
        f"# {target.title}",
        "",
        NON_AUTHORITY_NOTE,
        "",
        "## Source Set",
        "",
        f"- Compare rail: `{RESEARCH_COMPARE_SOURCE}`",
        *_source_set_lines(target.sources),
        "",
        "## Shared Candidates",
        "",
        *_bullet_or_none(target.extraction.shared_candidates, "none detected; compare source-specific candidates manually before promotion."),
        "",
        "## Source-Specific Candidates",
        "",
        *_bullet_or_none(target.extraction.source_unique_candidates, "none detected."),
        "",
        "## Conflicts And Tensions",
        "",
        *_bullet_or_none(target.extraction.conflicts, "none detected by deterministic route/hint comparison."),
        "",
        "## Unresolved Gaps",
        "",
        *_bullet_or_none(target.extraction.unresolved_gaps, "none detected; review sources manually before promotion."),
        "",
        "## Source Links",
        "",
        *_bullet_or_none(target.extraction.source_links, "none detected beyond compared sources."),
        "",
        "## Route Proposals",
        "",
        *_bullet_or_none(target.extraction.route_proposals, "none detected; promotion targets must be chosen explicitly later."),
        "",
        "## Boundaries",
        "",
        "- This artifact records a deterministic comparison of imported/distilled research sources.",
        "- It does not decide which source is true, more important, or accepted; shared/tension rows remain candidate signals only.",
        "- It does not promote candidates to specs, incubation, roadmap, plans, project state, archive, staging, or commit.",
        "- Promotion requires a later explicit lifecycle command or human-reviewed edit.",
        "",
    ]
    findings = [
        *(
            Finding("info", "research-compare-source-hash", f"{source.rel_path} sha256={source.source_hash[:12]}", target.rel_path)
            for source in target.sources
        ),
        Finding(
            "info",
            "research-compare-extraction",
            (
                f"shared_candidates={len(target.extraction.shared_candidates)}; "
                f"source_unique_candidates={len(target.extraction.source_unique_candidates)}; "
                f"conflicts={len(target.extraction.conflicts)}; "
                f"unresolved_gaps={len(target.extraction.unresolved_gaps)}; "
                f"route_proposals={len(target.extraction.route_proposals)}"
            ),
            target.rel_path,
        ),
        Finding("info", "research-compare-non-authority", NON_AUTHORITY_NOTE, target.rel_path),
    ]
    return "\n".join(lines), findings


def _shared_candidate_summaries(candidate_records: list[tuple[str, str]]) -> list[str]:
    by_key: dict[str, list[tuple[str, str]]] = {}
    by_route: dict[str, list[tuple[str, str]]] = {}
    for rel, item in candidate_records:
        by_key.setdefault(_candidate_match_key(item), []).append((rel, item))
        for route in _route_refs(item):
            by_route.setdefault(route, []).append((rel, item))

    shared: list[str] = []
    for rows in by_key.values():
        source_names = _dedupe(rel for rel, _item in rows)
        if len(source_names) > 1:
            shared.append(f"{rows[0][1]} (shared by {', '.join(f'`{source}`' for source in source_names)})")
    for route, rows in by_route.items():
        source_names = _dedupe(rel for rel, _item in rows)
        if len(source_names) > 1:
            shared.append(f"Route `{route}` appears as a shared candidate in {', '.join(f'`{source}`' for source in source_names)}.")
    return list(_dedupe(shared))


def _shared_candidate_keys(candidate_records: list[tuple[str, str]]) -> set[str]:
    keys: set[str] = set()
    by_key: dict[str, set[str]] = {}
    by_route: dict[str, set[str]] = {}
    for rel, item in candidate_records:
        by_key.setdefault(_candidate_match_key(item), set()).add(rel)
        for route in _route_refs(item):
            by_route.setdefault(route, set()).add(rel)
    keys.update(key for key, sources in by_key.items() if len(sources) > 1)
    keys.update(route for route, sources in by_route.items() if len(sources) > 1)
    return keys


def _conflict_summaries(candidate_records: list[tuple[str, str]], gap_records: list[tuple[str, str]]) -> list[str]:
    conflicts: list[str] = []
    candidate_routes: dict[str, set[str]] = {}
    gap_routes: dict[str, set[str]] = {}
    for rel, item in candidate_records:
        if _conflict_hint(item):
            conflicts.append(f"`{rel}` flags a tension: {item}")
        for route in _route_refs(item):
            candidate_routes.setdefault(route, set()).add(rel)
    for rel, item in gap_records:
        if _conflict_hint(item):
            conflicts.append(f"`{rel}` flags a tension: {item}")
        for route in _route_refs(item):
            gap_routes.setdefault(route, set()).add(rel)
    for route, candidate_sources in candidate_routes.items():
        gap_sources = gap_routes.get(route, set())
        if gap_sources:
            conflicts.append(
                f"Route `{route}` is a candidate in {', '.join(f'`{source}`' for source in sorted(candidate_sources))} "
                f"but unresolved/gap-linked in {', '.join(f'`{source}`' for source in sorted(gap_sources))}."
            )
    return list(_dedupe(conflicts))


def _target_findings(target: ResearchCompareTarget, apply: bool) -> list[Finding]:
    verb = "target compared research artifact" if apply else "would target compared research artifact"
    findings = [Finding("info", "research-compare-target", f"{verb}: {target.rel_path}", target.rel_path)]
    findings.extend(Finding("info", "research-compare-source", f"source research artifact: {source.rel_path}", source.rel_path) for source in target.sources)
    findings.append(Finding("info", "research-compare-title", f"normalized title: {target.title}", target.rel_path))
    return findings


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "research-compare-root-posture", f"root kind: {inventory.root_kind}")


def _boundary_findings(archive_sources: bool = False) -> list[Finding]:
    write_boundary = (
        "research-compare writes one project/research/<safe-title>-comparison.md artifact and, with explicit "
        "--archive-sources, writes archive copies before deleting source artifacts plus optional exact link repairs; "
        "it does not execute models, repair unrelated routes, stage, commit, or mutate product-source fixtures"
        if archive_sources
        else "research-compare writes only one project/research/<safe-title>-comparison.md artifact in eligible live operating roots; it does not execute models, repair, archive, stage, commit, or mutate product-source fixtures"
    )
    return [
        rails_not_cognition_boundary_finding(RESEARCH_DIR_REL),
        Finding(
            "info",
            "research-compare-boundary",
            write_boundary,
        ),
        Finding(
            "info",
            "research-compare-authority",
            "compared research is non-authority until promoted into accepted specs, incubation, plans, decisions, or state",
        ),
    ]


def _target_archives_sources(target: ResearchCompareTarget | None) -> bool:
    return bool(target and any(source.archive_rel for source in target.sources))


def _source_set_lines(sources: tuple[ResearchCompareSource, ...]) -> list[str]:
    return [
        (
            f"- Source artifact: `{source.archive_rel}` "
            f"(archived from `{source.rel_path}`; `{source.status or 'unknown'}`; sha256 `{source.source_hash}`)"
            if source.archive_rel
            else f"- Source artifact: `{source.rel_path}` (`{source.status or 'unknown'}`; sha256 `{source.source_hash}`)"
        )
        for source in sources
    ]


def _source_reference_rel(source: ResearchCompareSource) -> str:
    return source.archive_rel or source.rel_path


def _source_with_archived_text(source: ResearchCompareSource, promoted_to: str) -> ResearchCompareSource:
    if not source.archive_rel or not source.text:
        return source
    archived_text = _text_with_frontmatter_scalars(
        source.text,
        {
            "status": "distilled",
            "updated": date.today().isoformat(),
            "promoted_to": promoted_to,
            "archived_to": source.archive_rel,
        },
    )
    return ResearchCompareSource(
        rel_path=source.rel_path,
        path=source.path,
        text=source.text,
        source_hash=source.source_hash,
        read_error=source.read_error,
        title=source.title,
        status=source.status,
        archive_rel=source.archive_rel,
        archive_path=source.archive_path,
        archived_text=archived_text,
    )


def _archive_rels_for_sources(source_rels: tuple[str, ...]) -> dict[str, str]:
    today = date.today().isoformat()
    archive_rels: dict[str, str] = {}
    for source_rel in source_rels:
        source = Path(source_rel)
        slug = _safe_slug(source.stem)
        archive_rels[source_rel] = f"{ARCHIVE_RESEARCH_DIR_REL}/{today}-{slug}/{source.name}"
    return archive_rels


def _archive_errors(inventory: Inventory, archive_rel: str, archive_path: Path | None) -> list[Finding]:
    if not archive_rel or archive_path is None:
        return []
    errors: list[Finding] = []
    if _root_relative_path_conflict(archive_rel):
        errors.append(Finding("error", "research-compare-refused", f"archive target {_root_relative_path_conflict(archive_rel)}", archive_rel))
        return errors
    if not archive_rel.startswith(f"{ARCHIVE_RESEARCH_DIR_REL}/") or not archive_rel.endswith(".md"):
        errors.append(Finding("error", "research-compare-refused", f"archive target must be under {ARCHIVE_RESEARCH_DIR_REL}/", archive_rel))
    if _path_escapes_root(inventory.root, archive_path):
        errors.append(Finding("error", "research-compare-refused", "archive target path escapes the target root", archive_rel))
        return errors
    for parent in _parents_between(inventory.root, archive_path.parent):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "research-compare-refused", f"archive target directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "research-compare-refused", f"archive target directory contains a non-directory segment: {rel}", rel))
    if archive_path.exists():
        errors.append(Finding("error", "research-compare-refused", "archive target already exists", archive_rel))
    return errors


def _archive_plan_findings(target: ResearchCompareTarget, apply: bool) -> list[Finding]:
    archived_sources = tuple(source for source in target.sources if source.archive_rel)
    if not archived_sources:
        return []
    prefix = "" if apply else "would "
    findings: list[Finding] = [
        Finding(
            "info",
            "research-compare-archive-before-removal",
            f"{prefix}write archive copies before deleting {len(archived_sources)} source research artifact(s)",
            target.rel_path,
        )
    ]
    for source in archived_sources:
        findings.append(
            Finding(
                "info",
                "research-compare-source-metadata-plan" if not apply else "research-compare-source-metadata-updated",
                f"{prefix}record status='distilled', promoted_to={target.rel_path}, and archived_to={source.archive_rel}",
                source.archive_rel,
            )
        )
        findings.append(
            Finding(
                "info",
                "research-compare-source-archive-plan" if not apply else "research-compare-source-archived",
                f"{prefix}archive source {source.rel_path} to {source.archive_rel}",
                source.archive_rel,
            )
        )
    if target.link_repairs:
        for rel_path, _path, _text in target.link_repairs:
            findings.append(
                Finding(
                    "info",
                    "research-compare-link-repair-plan" if not apply else "research-compare-link-repaired",
                    f"{prefix}repair exact source-path references in {rel_path}",
                    rel_path,
                )
            )
    else:
        findings.append(
            Finding(
                "info",
                "research-compare-link-repair-plan" if not apply else "research-compare-link-repaired",
                f"{prefix}repair exact source-path references in 0 file(s)",
                target.rel_path,
            )
        )
    findings.append(
        Finding(
            "info",
            "research-compare-unresolved-followups-preserved",
            f"{prefix}preserve unresolved gaps in the non-authority comparison artifact and preserve full source bodies in archive copies",
            target.rel_path,
        )
    )
    return findings


def _planned_link_repairs(inventory: Inventory, replacements: dict[str, str]) -> tuple[tuple[str, Path, str], ...]:
    if not replacements:
        return ()
    repairs: list[tuple[str, Path, str]] = []
    source_rels = set(replacements)
    for path in _iter_lifecycle_markdown_files(inventory.root):
        rel_path = path.relative_to(inventory.root).as_posix()
        if rel_path in source_rels or rel_path.startswith("project/archive/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        updated = text
        for source_rel, archive_rel in replacements.items():
            updated = _replace_exact_route_ref(updated, source_rel, archive_rel)
        if updated != text:
            repairs.append((rel_path, path, updated))
    return tuple(repairs)


def _iter_lifecycle_markdown_files(root: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for rel in ("project/project-state.md", "project/implementation-plan.md", "project/roadmap.md"):
        path = root / rel
        if path.is_file() and not path.is_symlink():
            candidates.append(path)
    for base_rel in ("project/plan-incubation", "project/research", "project/specs", "project/adrs", "project/decisions", "project/verification"):
        base = root / base_rel
        if not base.is_dir() or base.is_symlink():
            continue
        candidates.extend(path for path in base.rglob("*.md") if path.is_file() and not path.is_symlink())
    return tuple(sorted(dict.fromkeys(candidates)))


def _replace_exact_route_ref(text: str, source_rel: str, archive_rel: str) -> str:
    pattern = re.compile(rf"(?<![A-Za-z0-9_./-]){re.escape(source_rel)}(?![A-Za-z0-9_./-])")
    return pattern.sub(archive_rel, text)


def _text_with_frontmatter_scalars(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return _prepend_frontmatter_scalars(text, updates)
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return _prepend_frontmatter_scalars(text, updates)

    seen: set[str] = set()
    index = 1
    while index < closing_index:
        match = re.match(r"^([A-Za-z0-9_-]+):(.*?)(\r?\n)?$", lines[index])
        if not match:
            index += 1
            continue
        key = match.group(1)
        if key not in updates:
            index += 1
            continue
        newline = match.group(3) or ("\n" if lines[index].endswith("\n") else "")
        end = index + 1
        while end < closing_index and _frontmatter_scalar_continuation_line(lines[end]):
            end += 1
        lines[index:end] = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"{newline}']
        closing_index -= end - index - 1
        seen.add(key)
        index += 1

    missing = [key for key in updates if key not in seen]
    if missing:
        lines[closing_index:closing_index] = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"\n' for key in missing]
    return "".join(lines)


def _prepend_frontmatter_scalars(text: str, updates: dict[str, str]) -> str:
    frontmatter = ["---", *(f'{key}: "{_yaml_double_quoted_value(value)}"' for key, value in updates.items()), "---"]
    return "\n".join(frontmatter) + "\n" + text.lstrip("\n")


def _frontmatter_scalar_continuation_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    return line.startswith((" ", "\t")) or stripped.startswith("- ")


def _atomic_write(path: Path, text: str) -> AtomicFileWrite:
    return AtomicFileWrite(path, _tmp_path(path), text, _backup_path(path))


def _tmp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.research-compare.tmp")


def _backup_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.research-compare.backup")


def _route_write(root: Path, rel_path: str, after_text: str) -> RouteWriteEvidence:
    target = root / rel_path
    before_text = target.read_text(encoding="utf-8") if target.is_file() else None
    return RouteWriteEvidence(rel_path, before_text, after_text)


def _route_write_plan(target: ResearchCompareTarget, rendered: str) -> tuple[RouteWriteEvidence, ...]:
    target_before = target.path.read_text(encoding="utf-8") if target.path.is_file() else None
    writes: list[RouteWriteEvidence] = [RouteWriteEvidence(target.rel_path, target_before, rendered)]
    for source in target.sources:
        if source.archive_path and source.archived_text:
            writes.append(RouteWriteEvidence(source.archive_rel, None, source.archived_text))
            writes.append(RouteWriteEvidence(source.rel_path, source.text, None))
    for rel_path, path, text in target.link_repairs:
        before_text = path.read_text(encoding="utf-8") if path.is_file() else None
        writes.append(RouteWriteEvidence(rel_path, before_text, text))
    return tuple(writes)


def _source_snapshot(path: Path) -> tuple[str, str, str]:
    if not path.is_file():
        return "", "", ""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return "", "", f"source research artifact is unreadable: {exc}"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return "", hashlib.sha256(raw).hexdigest(), f"source research artifact must be UTF-8: {exc}"
    return text, hashlib.sha256(raw).hexdigest(), ""


def _title_from_source(text: str, source_rel: str) -> str:
    frontmatter = parse_frontmatter(text) if text else None
    if frontmatter and frontmatter.has_frontmatter:
        title = _normalized_note(frontmatter.data.get("title"))
        if title:
            return title
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return _normalized_note(match.group(1))
    stem = Path(source_rel).stem if source_rel else "research"
    return _normalized_note(stem.replace("-", " ").title()) or "Research"


def _default_compare_title(sources: tuple[ResearchCompareSource, ...]) -> str:
    if not sources:
        return "Research Comparison"
    first = sources[0].title or "Research"
    return first if first.lower().endswith("comparison") else f"{first} Comparison"


def _default_compare_rel(title: str) -> str:
    slug = _safe_slug(title)
    if not slug or slug in _RESERVED_SLUGS:
        return ""
    suffix = "" if slug.endswith("comparison") else "-comparison"
    return f"{RESEARCH_DIR_REL}/{date.today().isoformat()}-{slug}{suffix}.md"


def _candidate_match_key(item: str) -> str:
    routes = _route_refs(item)
    if routes:
        return routes[0]
    return re.sub(r"[^a-z0-9]+", " ", item.lower()).strip()


def _route_refs(text: str) -> tuple[str, ...]:
    return _dedupe(ref.target for ref in extract_path_refs(text) if _is_route_ref(ref.target))


def _is_route_ref(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return normalized.startswith(("project/", "src/", "tests/", "docs/", ".agents/", ".codex/", "README.md", "AGENTS.md"))


def _conflict_hint(item: str) -> bool:
    lower = item.lower()
    return any(marker in lower for marker in ("conflict", "contradict", "disagree", "tension", "tradeoff", "however", " but ", "opposes"))


def _safe_slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _bullet_or_none(items: tuple[str, ...], fallback: str) -> list[str]:
    values = items or (fallback,)
    return [f"- {item}" for item in values]


def _bounded_items(items: tuple[str, ...] | list[str], limit: int = 20, max_chars: int = 300) -> tuple[str, ...]:
    bounded = []
    for item in items:
        clean = _normalized_note(item)
        if not clean:
            continue
        bounded.append(clean if len(clean) <= max_chars else f"{clean[: max_chars - 3].rstrip()}...")
        if len(bounded) >= limit:
            break
    return tuple(bounded)


def _dedupe(values) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _normalized_note(value)
        key = clean.lower()
        if clean and key not in seen:
            result.append(clean)
            seen.add(key)
    return tuple(result)


def _normalize_rel(value: str | None) -> str:
    return str(value or "").strip().replace("\\", "/")


def _normalized_note(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _root_relative_path_conflict(rel_path: str) -> str:
    normalized = _normalize_rel(rel_path)
    if not normalized:
        return ""
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return "must be root-relative, not absolute"
    path = Path(normalized)
    if any(part in {"", ".", ".."} for part in path.parts):
        return "contains empty, current-directory, or parent-directory segments"
    return ""


def _path_escapes_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return False


def _parents_between(root: Path, path: Path) -> tuple[Path, ...]:
    root = root.resolve()
    path = path.resolve()
    parents: list[Path] = []
    current = path
    while current != root and current.parent != current:
        parents.append(current)
        current = current.parent
    return tuple(reversed(parents))


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [
        Finding(
            severity,
            finding.code,
            finding.message,
            finding.source,
            finding.line,
            finding.route_id,
            finding.mutates,
            finding.requires_human_gate,
            finding.gate_class,
            finding.human_gate_reason,
            finding.allowed_decisions,
            finding.advisory,
        )
        for finding in findings
    ]


def _yaml_double_quoted_value(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


__all__ = [
    "ResearchCompareExtraction",
    "ResearchCompareRequest",
    "ResearchCompareSource",
    "ResearchCompareTarget",
    "compare_research_texts",
    "make_research_compare_request",
    "research_compare_apply_findings",
    "research_compare_dry_run_findings",
]
