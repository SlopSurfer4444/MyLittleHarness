from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .atomic_files import AtomicFileWrite, apply_file_transaction
from .command_discovery import rails_not_cognition_boundary_finding
from .inventory import Inventory
from .models import Finding
from .parsing import extract_path_refs, parse_frontmatter
from .reporting import RouteWriteEvidence, route_write_findings
from .root_boundary import source_path_boundary_violation


RESEARCH_DIR_REL = "project/research"
RESEARCH_DISTILL_SOURCE = "research-distill cli"
NON_AUTHORITY_NOTE = (
    "distilled research is a non-authority distillate of source-candidate, gap, provenance, and route-reference "
    "signals; it cannot perform autonomous synthesis or approve lifecycle, specs, plans, archive, roadmap status, "
    "staging, commit, or next-plan opening."
)
QUALITY_STATUS_SUFFICIENT = "sufficient-for-planning"
QUALITY_STATUS_PROVISIONAL = "provisional"
PLANNING_RELIANCE_ALLOWED = "allowed"
PLANNING_RELIANCE_BLOCKED = "blocked"
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
_ROUTE_PREFIXES = ("project/", "src/", "tests/", "docs/", ".agents/", ".codex/", "README.md", "AGENTS.md")


@dataclass(frozen=True)
class ResearchDistillRequest:
    source: str
    title: str = ""
    target: str = ""
    topic: str = ""


@dataclass(frozen=True)
class ResearchDistillQuality:
    quality_status: str
    planning_reliance: str
    gate_coverage: tuple[str, ...]
    source_bound_claims: tuple[str, ...]
    confidence_notes: tuple[str, ...]
    quality_gate_issues: tuple[str, ...]


@dataclass(frozen=True)
class ResearchDistillExtraction:
    accepted_candidates: tuple[str, ...]
    unresolved_gaps: tuple[str, ...]
    source_links: tuple[str, ...]
    route_proposals: tuple[str, ...]
    quality: ResearchDistillQuality


@dataclass(frozen=True)
class ResearchDistillTarget:
    source_rel: str
    source_path: Path
    source_text: str
    source_hash: str
    source_read_error: str
    title: str
    topic: str
    rel_path: str
    path: Path
    extraction: ResearchDistillExtraction


def make_research_distill_request(
    source: str | None,
    *,
    title: str | None = None,
    target: str | None = None,
    topic: str | None = None,
) -> ResearchDistillRequest:
    return ResearchDistillRequest(
        source=_normalize_rel(source),
        title=_normalized_note(title),
        target=_normalize_rel(target),
        topic=_normalized_note(topic),
    )


def research_distill_dry_run_findings(inventory: Inventory, request: ResearchDistillRequest) -> list[Finding]:
    target = _research_distill_target(inventory, request)
    findings = [
        Finding("info", "research-distill-dry-run", "research distill proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    errors = _research_distill_preflight_errors(inventory, request, target)
    if target:
        findings.extend(_target_findings(target, apply=False))
    if target and not errors:
        if target.source_text and not target.source_read_error:
            rendered, render_findings = _render_research_distill(inventory.root, target)
            findings.extend(render_findings)
            findings.extend(route_write_findings("research-distill-route-write", (_route_write(inventory.root, target.rel_path, rendered),), apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "research-distill-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before distilling research",
            )
        )
        return findings
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "research-distill-validation-posture",
            "apply would write one distilled research artifact in a live operating root; dry-run writes no files",
            target.rel_path if target else RESEARCH_DIR_REL,
        )
    )
    return findings


def research_distill_apply_findings(inventory: Inventory, request: ResearchDistillRequest) -> list[Finding]:
    target = _research_distill_target(inventory, request)
    errors = _research_distill_preflight_errors(inventory, request, target)
    if errors:
        return errors
    assert target is not None

    rendered, render_findings = _render_research_distill(inventory.root, target)
    write_evidence = _route_write(inventory.root, target.rel_path, rendered)
    tmp_path = target.path.with_name(f".{target.path.name}.research-distill.tmp")
    backup_path = target.path.with_name(f".{target.path.name}.research-distill.backup")
    try:
        cleanup_warnings = apply_file_transaction(
            (AtomicFileWrite(target.path, tmp_path, rendered, backup_path),),
            root=inventory.root,
        )
    except OSError as exc:
        return [Finding("error", "research-distill-refused", f"research distill apply failed before all target writes completed: {exc}", target.rel_path)]

    findings = [
        Finding("info", "research-distill-apply", "research distill apply started"),
        _root_posture_finding(inventory),
        *_target_findings(target, apply=True),
        *render_findings,
        Finding("info", "research-distill-written", "created distilled research artifact", target.rel_path),
        *route_write_findings("research-distill-route-write", (write_evidence,), apply=True),
        *_boundary_findings(),
        Finding(
            "info",
            "research-distill-validation-posture",
            "run check after apply to verify the live operating root remains healthy; distilled research remains non-authority until promoted",
            target.rel_path,
        ),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "research-distill-backup-cleanup", warning, target.rel_path))
    return findings


def _research_distill_target(inventory: Inventory, request: ResearchDistillRequest) -> ResearchDistillTarget | None:
    source_rel = request.source
    source_path = inventory.root / source_rel if source_rel else inventory.root
    source_text = ""
    source_hash = ""
    source_read_error = ""
    source_conflict = _root_relative_path_conflict(source_rel) if source_rel else "missing source"
    boundary_violation = None if source_conflict else source_path_boundary_violation(inventory.root, source_path, label="research distill source")
    if boundary_violation is not None:
        source_read_error = boundary_violation.message
    elif not source_conflict:
        source_text, source_hash, source_read_error = _source_snapshot(source_path)
    title = request.title or _title_from_source(source_text, source_rel)
    rel_path = request.target or _default_distill_rel(title)
    if not rel_path:
        return None
    extraction = distill_research_text(source_rel, source_text) if source_text and not source_read_error else _empty_extraction(source_rel)
    return ResearchDistillTarget(
        source_rel=source_rel,
        source_path=source_path,
        source_text=source_text,
        source_hash=source_hash,
        source_read_error=source_read_error,
        title=title,
        topic=request.topic or title,
        rel_path=rel_path,
        path=inventory.root / rel_path,
        extraction=extraction,
    )


def distill_research_text(source_rel: str, text: str) -> ResearchDistillExtraction:
    accepted_candidates, unresolved_gaps = _distilled_items(text)
    source_links = _source_links(source_rel, text)
    route_proposals = _route_proposals(text, (*accepted_candidates, *unresolved_gaps))
    quality = assess_research_distill_quality(
        source_rel,
        text,
        accepted_candidates=accepted_candidates,
        unresolved_gaps=unresolved_gaps,
        source_links=source_links,
    )
    return ResearchDistillExtraction(
        accepted_candidates=_bounded_items(accepted_candidates),
        unresolved_gaps=_bounded_items(unresolved_gaps),
        source_links=_bounded_items(source_links, limit=30),
        route_proposals=_bounded_items(route_proposals, limit=30),
        quality=quality,
    )


def assess_research_distill_quality(
    source_rel: str,
    text: str,
    *,
    accepted_candidates: tuple[str, ...] | None = None,
    unresolved_gaps: tuple[str, ...] | None = None,
    source_links: tuple[str, ...] | None = None,
) -> ResearchDistillQuality:
    if accepted_candidates is None or unresolved_gaps is None:
        accepted_candidates, unresolved_gaps = _distilled_items(text)
    if source_links is None:
        source_links = _source_links(source_rel, text)

    gate_coverage = _bounded_items(_gate_coverage_items(text), limit=12)
    source_bound_claims = _bounded_items(_source_bound_claim_items(text), limit=20)
    confidence_notes = _bounded_items((*_confidence_items(text), *unresolved_gaps), limit=20)
    issues: list[str] = []
    if not gate_coverage:
        issues.append("missing gate-question coverage matrix")
    if not source_bound_claims:
        issues.append("missing source-bound claim bullets")
    if not confidence_notes:
        issues.append("missing contradiction, uncertainty, or confidence notes")
    if not source_links:
        issues.append("missing source provenance links")

    quality_status = QUALITY_STATUS_PROVISIONAL if issues else QUALITY_STATUS_SUFFICIENT
    planning_reliance = PLANNING_RELIANCE_BLOCKED if issues else PLANNING_RELIANCE_ALLOWED
    return ResearchDistillQuality(
        quality_status=quality_status,
        planning_reliance=planning_reliance,
        gate_coverage=gate_coverage,
        source_bound_claims=source_bound_claims,
        confidence_notes=confidence_notes,
        quality_gate_issues=tuple(issues),
    )


def research_distill_quality_problem(source_rel: str, text: str) -> str:
    frontmatter = parse_frontmatter(text)
    status = ""
    source_type = ""
    quality_status = ""
    planning_reliance = ""
    issues: tuple[str, ...] = ()
    if frontmatter.has_frontmatter:
        status = _normalized_note(frontmatter.data.get("status")).lower()
        source_type = _normalized_note(frontmatter.data.get("source_type")).lower()
        quality_status = _normalized_note(frontmatter.data.get("quality_status")).lower()
        planning_reliance = _normalized_note(frontmatter.data.get("planning_reliance")).lower()
        issues = tuple(_frontmatter_values(frontmatter.data.get("quality_gate_issues")))

    is_distillate = status == "distilled" or "research-distill" in source_type or bool(quality_status or planning_reliance)
    if not is_distillate:
        return ""
    if quality_status == QUALITY_STATUS_SUFFICIENT and planning_reliance == PLANNING_RELIANCE_ALLOWED:
        return ""
    if quality_status == QUALITY_STATUS_PROVISIONAL or planning_reliance == PLANNING_RELIANCE_BLOCKED:
        issue_text = "; ".join(issues) if issues else "quality gate is provisional"
        return f"{quality_status or QUALITY_STATUS_PROVISIONAL}/{planning_reliance or PLANNING_RELIANCE_BLOCKED}: {issue_text}"

    quality = assess_research_distill_quality(source_rel, text)
    if quality.planning_reliance != PLANNING_RELIANCE_ALLOWED:
        return f"{quality.quality_status}/{quality.planning_reliance}: {'; '.join(quality.quality_gate_issues)}"
    return ""


def _research_distill_preflight_errors(
    inventory: Inventory,
    request: ResearchDistillRequest,
    target: ResearchDistillTarget | None,
) -> list[Finding]:
    errors: list[Finding] = []
    if not request.source:
        errors.append(Finding("error", "research-distill-refused", "--source is required and must point to project/research/*.md"))
    elif _root_relative_path_conflict(request.source):
        errors.append(Finding("error", "research-distill-refused", f"source {_root_relative_path_conflict(request.source)}", request.source))
    elif not request.source.startswith(f"{RESEARCH_DIR_REL}/") or not request.source.endswith(".md"):
        errors.append(Finding("error", "research-distill-refused", f"source must be under {RESEARCH_DIR_REL}/*.md", request.source))
    if request.target and _root_relative_path_conflict(request.target):
        errors.append(Finding("error", "research-distill-refused", f"target {_root_relative_path_conflict(request.target)}", request.target))

    if inventory.root_kind == "product_source_fixture":
        errors.append(
            Finding(
                "error",
                "research-distill-refused",
                "target is a product-source compatibility fixture; research-distill --apply is refused",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(
            Finding(
                "error",
                "research-distill-refused",
                "target is fallback/archive or generated-output evidence; research-distill --apply is refused",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "research-distill-refused", f"target root kind is {inventory.root_kind}; research distill requires a live operating root"))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "research-distill-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "research-distill-refused", "project-state.md frontmatter is required for research distill apply", state.rel_path))
    elif state.frontmatter.errors:
        errors.append(Finding("error", "research-distill-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "research-distill-refused", "project-state.md is not a regular file", state.rel_path))
    elif state.path.is_symlink():
        errors.append(Finding("error", "research-distill-refused", "project-state.md is a symlink", state.rel_path))

    research_dir = inventory.root / RESEARCH_DIR_REL
    if _path_escapes_root(inventory.root, research_dir):
        errors.append(Finding("error", "research-distill-refused", "research directory path escapes the target root", RESEARCH_DIR_REL))
    for parent in _parents_between(inventory.root, research_dir):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "research-distill-refused", f"research directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "research-distill-refused", f"research directory contains a non-directory segment: {rel}", rel))

    if target:
        if _path_escapes_root(inventory.root, target.source_path):
            errors.append(Finding("error", "research-distill-refused", "source research path escapes the target root", target.source_rel))
        elif target.source_path.exists():
            if target.source_path.is_symlink():
                errors.append(Finding("error", "research-distill-refused", "source research artifact is a symlink", target.source_rel))
            elif not target.source_path.is_file():
                errors.append(Finding("error", "research-distill-refused", "source research artifact path exists but is not a regular file", target.source_rel))
            elif target.source_read_error:
                errors.append(Finding("error", "research-distill-refused", target.source_read_error, target.source_rel))
        elif request.source:
            errors.append(Finding("error", "research-distill-refused", "source research artifact does not exist", target.source_rel))

        if not target.rel_path.startswith(f"{RESEARCH_DIR_REL}/") or not target.rel_path.endswith(".md"):
            errors.append(Finding("error", "research-distill-refused", f"target must be under {RESEARCH_DIR_REL}/*.md", target.rel_path))
        if target.rel_path == target.source_rel:
            errors.append(Finding("error", "research-distill-refused", "target must be distinct from source research artifact", target.rel_path))
        if _path_escapes_root(inventory.root, target.path):
            errors.append(Finding("error", "research-distill-refused", "target research path escapes the target root", target.rel_path))
        elif target.path.exists():
            if target.path.is_symlink():
                errors.append(Finding("error", "research-distill-refused", "target research artifact is a symlink; overwrite is refused", target.rel_path))
            elif not target.path.is_file():
                errors.append(Finding("error", "research-distill-refused", "target research artifact path exists but is not a regular file", target.rel_path))
            else:
                errors.append(Finding("error", "research-distill-refused", "target research artifact already exists; choose a new --target", target.rel_path))
    return errors


def _render_research_distill(root: Path, target: ResearchDistillTarget) -> tuple[str, list[Finding]]:
    today = date.today().isoformat()
    frontmatter = [
        "---",
        'status: "distilled"',
        f'topic: "{_yaml_double_quoted_value(target.topic)}"',
        f'title: "{_yaml_double_quoted_value(target.title)}"',
        f'created: "{today}"',
        f'last_reviewed: "{today}"',
        f'derived_from: "{_yaml_double_quoted_value(target.source_rel)}"',
        f'source_type: "{RESEARCH_DISTILL_SOURCE}"',
        'authority: "non-authoritative distillate; source-candidate signals only"',
        f'quality_status: "{target.extraction.quality.quality_status}"',
        f'planning_reliance: "{target.extraction.quality.planning_reliance}"',
        "quality_gate_issues:",
        *_yaml_list_lines(target.extraction.quality.quality_gate_issues or ("none",), indent="  "),
        "source_hashes:",
        f'  - "{_yaml_double_quoted_value(f"{target.source_rel} sha256={target.source_hash}")}"',
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
        f"- Distill rail: `{RESEARCH_DISTILL_SOURCE}`",
        f"- Source artifact: `{target.source_rel}`",
        f"- Source sha256: `{target.source_hash}`",
        "",
        "## Quality Gate",
        "",
        f"- Quality status: `{target.extraction.quality.quality_status}`",
        f"- Planning reliance: `{target.extraction.quality.planning_reliance}`",
        "- MLH validates explicit coverage/provenance shape only; humans and agents remain responsible for qualitative synthesis.",
        "",
        "### Gate Coverage",
        "",
        *_bullet_or_none(target.extraction.quality.gate_coverage, "missing; downstream planning reliance is blocked until reviewed coverage is supplied."),
        "",
        "### Source-Bound Claims",
        "",
        *_bullet_or_none(target.extraction.quality.source_bound_claims, "missing; record claims tied to source evidence before promotion."),
        "",
        "### Confidence And Uncertainty",
        "",
        *_bullet_or_none(target.extraction.quality.confidence_notes, "missing; record confidence, contradictions, or unresolved gaps before promotion."),
        "",
        "## Accepted Candidates",
        "",
        "- Label meaning: extracted from source language; not accepted or prioritized by MLH.",
        *_bullet_or_none(target.extraction.accepted_candidates, "none detected; review source manually before promotion."),
        "",
        "## Unresolved Gaps",
        "",
        *_bullet_or_none(target.extraction.unresolved_gaps, "none detected; review source manually before promotion."),
        "",
        "## Source Links",
        "",
        *_bullet_or_none(target.extraction.source_links, "none detected beyond the source artifact."),
        "",
        "## Route Proposals",
        "",
        *_bullet_or_none(target.extraction.route_proposals, "none detected; promotion targets must be chosen explicitly later."),
        "",
        "## Boundaries",
        "",
        "- This artifact records a deterministic distillation of one research source.",
        "- It reports source-candidate signals only and does not decide research meaning, priority, or acceptance.",
        "- It does not promote candidates to specs, incubation, roadmap, plans, project state, archive, staging, or commit.",
        "- Promotion requires a later explicit lifecycle command or human-reviewed edit.",
        "",
    ]
    findings = [
        Finding("info", "research-distill-source-hash", f"{target.source_rel} sha256={target.source_hash[:12]}", target.rel_path),
        Finding(
            "info",
            "research-distill-extraction",
            (
                f"accepted_candidates={len(target.extraction.accepted_candidates)}; "
                f"unresolved_gaps={len(target.extraction.unresolved_gaps)}; "
                f"source_links={len(target.extraction.source_links)}; "
                f"route_proposals={len(target.extraction.route_proposals)}"
            ),
            target.rel_path,
        ),
        Finding(
            "warn" if target.extraction.quality.planning_reliance == PLANNING_RELIANCE_BLOCKED else "info",
            "research-distill-quality-gate",
            (
                f"quality_status={target.extraction.quality.quality_status}; "
                f"planning_reliance={target.extraction.quality.planning_reliance}; "
                f"gate_coverage={len(target.extraction.quality.gate_coverage)}; "
                f"source_bound_claims={len(target.extraction.quality.source_bound_claims)}; "
                f"confidence_notes={len(target.extraction.quality.confidence_notes)}; "
                f"issues={len(target.extraction.quality.quality_gate_issues)}"
            ),
            target.rel_path,
        ),
        Finding("info", "research-distill-non-authority", NON_AUTHORITY_NOTE, target.rel_path),
    ]
    return "\n".join(lines), findings


def _distilled_items(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    candidates: list[str] = []
    gaps: list[str] = []
    heading = ""
    for raw_line in text.splitlines():
        heading_match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", raw_line)
        if heading_match:
            heading = heading_match.group(1).strip().lower()
            continue
        item = _markdown_item(raw_line)
        if not item:
            continue
        lower_item = item.lower()
        is_candidate = _candidate_section(heading) or _candidate_hint(lower_item)
        is_gap = _gap_section(heading) or _gap_hint(lower_item)
        if is_candidate and not _gap_section(heading):
            candidates.append(item)
        elif is_gap:
            gaps.append(item)
    return _dedupe(candidates), _dedupe(gaps)


def _source_links(source_rel: str, text: str) -> tuple[str, ...]:
    links = [source_rel] if source_rel else []
    frontmatter = parse_frontmatter(text)
    if frontmatter.has_frontmatter:
        for key in ("derived_from", "source", "source_research", "related_prompt"):
            links.extend(_frontmatter_values(frontmatter.data.get(key)))
        for key in ("related_artifacts", "source_hashes"):
            links.extend(_frontmatter_values(frontmatter.data.get(key)))
    links.extend(ref.target for ref in extract_path_refs(text))
    return _dedupe(_clean_ref(value) for value in links if _clean_ref(value))


def _route_proposals(text: str, items: tuple[str, ...]) -> tuple[str, ...]:
    refs = [ref.target for ref in extract_path_refs(text)]
    for item in items:
        refs.extend(ref.target for ref in extract_path_refs(item))
    return _dedupe(_clean_ref(ref) for ref in refs if _is_route_ref(_clean_ref(ref)))


def _gate_coverage_items(text: str) -> tuple[str, ...]:
    return _dedupe(
        (
            *_items_from_sections(text, _gate_coverage_section),
            *_items_with_hint(text, ("gate:", "roadmap gate:", "coverage:", "covered gate:")),
        )
    )


def _source_bound_claim_items(text: str) -> tuple[str, ...]:
    return _dedupe(
        (
            *_items_from_sections(text, _source_bound_claim_section),
            *_items_with_hint(text, ("source:", "evidence:", "claim:", "finding:", "according to")),
        )
    )


def _confidence_items(text: str) -> tuple[str, ...]:
    return _dedupe(
        (
            *_items_from_sections(text, _confidence_section),
            *_items_with_hint(text, ("confidence:", "uncertainty:", "contradiction:", "contradicts", "tradeoff:", "confidence is")),
        )
    )


def _items_from_sections(text: str, predicate) -> tuple[str, ...]:
    items: list[str] = []
    heading = ""
    for raw_line in text.splitlines():
        heading_match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", raw_line)
        if heading_match:
            heading = heading_match.group(1).strip().lower()
            continue
        item = _markdown_item(raw_line)
        if item and predicate(heading):
            items.append(item)
    return tuple(items)


def _items_with_hint(text: str, hints: tuple[str, ...]) -> tuple[str, ...]:
    items = []
    for raw_line in text.splitlines():
        item = _markdown_item(raw_line)
        if item and any(hint in item.lower() for hint in hints):
            items.append(item)
    return tuple(items)


def _frontmatter_values(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip() and str(item).strip() != "none"]
    text = str(value).strip()
    return [] if not text or text == "none" else [text]


def _target_findings(target: ResearchDistillTarget, apply: bool) -> list[Finding]:
    verb = "target distillate artifact" if apply else "would target distillate artifact"
    return [
        Finding("info", "research-distill-source", f"source research artifact: {target.source_rel}", target.source_rel),
        Finding("info", "research-distill-title", f"normalized title: {target.title}", target.rel_path),
        Finding("info", "research-distill-target", f"{verb}: {target.rel_path}", target.rel_path),
    ]


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "research-distill-root-posture", f"root kind: {inventory.root_kind}")


def _boundary_findings() -> list[Finding]:
    return [
        rails_not_cognition_boundary_finding(RESEARCH_DIR_REL),
        Finding(
            "info",
            "research-distill-boundary",
            "research-distill writes only one project/research/<safe-title>-distillate.md artifact in eligible live operating roots; it does not execute models, decide research meaning, repair, archive, stage, commit, or mutate product-source fixtures",
        ),
        Finding(
            "info",
            "research-distill-authority",
            "distilled research is non-authority until promoted into accepted specs, incubation, plans, decisions, or state",
        ),
    ]


def _route_write(root: Path, rel_path: str, after_text: str) -> RouteWriteEvidence:
    target = root / rel_path
    before_text = target.read_text(encoding="utf-8") if target.is_file() else None
    return RouteWriteEvidence(rel_path, before_text, after_text)


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
            return title if title.lower().endswith("distillate") else f"{title} Distillate"
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            title = _normalized_note(match.group(1))
            return title if title.lower().endswith("distillate") else f"{title} Distillate"
    stem = Path(source_rel).stem if source_rel else "research"
    return _normalized_note(stem.replace("-", " ").title()) or "Research Distillate"


def _default_distill_rel(title: str) -> str:
    slug = _safe_slug(title)
    if not slug or slug in _RESERVED_SLUGS:
        return ""
    suffix = "" if slug.endswith("distillate") else "-distillate"
    return f"{RESEARCH_DIR_REL}/{date.today().isoformat()}-{slug}{suffix}.md"


def _safe_slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _markdown_item(line: str) -> str:
    match = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$", line)
    if not match:
        return ""
    return _normalized_note(match.group(1))


def _candidate_section(heading: str) -> bool:
    return any(
        marker in heading
        for marker in (
            "accepted candidate",
            "candidate",
            "recommend",
            "improvement",
            "roadmap pressure",
            "recommended next",
            "minimal first implementation",
            "core decision",
        )
    )


def _candidate_hint(lower_item: str) -> bool:
    return any(
        marker in lower_item
        for marker in (
            "[mlh-fix-candidate]",
            "candidate owner:",
            "candidate route",
            "should ",
            "recommended next",
            "recommend ",
            "add ",
            "promote ",
            "route proposal",
        )
    )


def _gap_section(heading: str) -> bool:
    return any(marker in heading for marker in ("open question", "research needed", "unresolved", "gap", "risk", "unknown", "verification question"))


def _gap_hint(lower_item: str) -> bool:
    return any(marker in lower_item for marker in ("unresolved", "unknown", "open question", "needs research", "missing ", "gap", "risk:", "blocked"))


def _gate_coverage_section(heading: str) -> bool:
    return any(marker in heading for marker in ("gate coverage", "gate question", "roadmap gate", "acceptance gate", "coverage matrix", "question coverage"))


def _source_bound_claim_section(heading: str) -> bool:
    return any(marker in heading for marker in ("source-bound", "source bound", "evidence", "claim", "finding", "findings", "answer"))


def _confidence_section(heading: str) -> bool:
    return any(marker in heading for marker in ("confidence", "uncertainty", "contradiction", "limitation", "caveat", "gap", "risk"))


def _bounded_items(items: tuple[str, ...] | list[str], limit: int = 20, max_chars: int = 260) -> tuple[str, ...]:
    bounded = []
    for item in items:
        clean = _normalized_note(item)
        if not clean:
            continue
        bounded.append(clean if len(clean) <= max_chars else f"{clean[: max_chars - 3].rstrip()}...")
        if len(bounded) >= limit:
            break
    return tuple(bounded)


def _bullet_or_none(items: tuple[str, ...], fallback: str) -> list[str]:
    values = items or (fallback,)
    return [f"- {item}" for item in values]


def _empty_extraction(source_rel: str) -> ResearchDistillExtraction:
    quality = ResearchDistillQuality(
        quality_status=QUALITY_STATUS_PROVISIONAL,
        planning_reliance=PLANNING_RELIANCE_BLOCKED,
        gate_coverage=(),
        source_bound_claims=(),
        confidence_notes=(),
        quality_gate_issues=(
            "missing gate-question coverage matrix",
            "missing source-bound claim bullets",
            "missing contradiction, uncertainty, or confidence notes",
        ),
    )
    return ResearchDistillExtraction((), (), (source_rel,) if source_rel else (), (), quality)


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


def _clean_ref(value: str) -> str:
    return str(value).strip().strip("`\"'").rstrip(".,;)")


def _is_route_ref(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return normalized.startswith(_ROUTE_PREFIXES)


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


def _yaml_list_lines(values: tuple[str, ...], *, indent: str = "") -> list[str]:
    return [f'{indent}- "{_yaml_double_quoted_value(value)}"' for value in values]


__all__ = [
    "ResearchDistillExtraction",
    "ResearchDistillQuality",
    "ResearchDistillRequest",
    "ResearchDistillTarget",
    "assess_research_distill_quality",
    "distill_research_text",
    "make_research_distill_request",
    "research_distill_quality_problem",
    "research_distill_apply_findings",
    "research_distill_dry_run_findings",
]
