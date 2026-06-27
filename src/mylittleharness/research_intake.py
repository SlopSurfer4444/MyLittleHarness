from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from .atomic_files import AtomicFileWrite, apply_file_transaction
from .evidence import lifecycle_mutation_provenance_findings
from .inventory import Inventory
from .models import Finding
from .parsing import parse_frontmatter
from .reporting import RouteWriteEvidence, route_write_findings
from .root_boundary import source_path_boundary_violation
from .routes import route_destination_problem
from .research_distill import (
    DISCOVERY_PACKET_SCHEMA,
    DISCOVERY_PACKET_SOURCE_TYPE,
    PLANNING_RELIANCE_ALLOWED,
    PLANNING_RELIANCE_BLOCKED,
    QUALITY_STATUS_PROVISIONAL,
    QUALITY_STATUS_SUFFICIENT,
)


RESEARCH_DIR_REL = "project/research"
RESEARCH_IMPORT_SOURCE = "research-import cli"
DISCOVERY_PACKET_SOURCE = "discover cli"
NON_AUTHORITY_NOTE = (
    "imported research is durable provenance and synthesis input; it cannot approve lifecycle, specs, plans, archive, "
    "roadmap status, staging, commit, or next-plan opening."
)
DISCOVERY_PACKET_NON_AUTHORITY_NOTE = (
    "discovery packet is source-bound pre-plan evidence; it cannot approve lifecycle, open plans, update roadmap "
    "status, archive, stage, commit, call providers, or decide planning readiness unless its explicit gate fields allow it."
)
DISCOVERY_PACKET_READY_STATUS = "ready-for-plan"
DISCOVERY_PACKET_DEFAULT_STATUS = "draft"
DISCOVERY_PACKET_BLOCKED_STATUSES = {"blocked", "contested", "draft"}
DISCOVERY_PACKET_STATUSES = {DISCOVERY_PACKET_READY_STATUS, *DISCOVERY_PACKET_BLOCKED_STATUSES}
RESEARCH_ROUTE_STATUSES = {"imported", "distilled", "compared", "research-ready", "ready-for-implementation", "accepted"}
_DISCOVERY_PACKET_QUALITY_STATUSES = {QUALITY_STATUS_SUFFICIENT, QUALITY_STATUS_PROVISIONAL}
_DISCOVERY_PACKET_PLANNING_RELIANCE = {PLANNING_RELIANCE_ALLOWED, PLANNING_RELIANCE_BLOCKED}
DECISION_PACKET_FIELDS = (
    "confirmed_fixes",
    "new_slice_candidates",
    "scope_expansions",
    "blocked_followups",
    "safe_to_continue_existing_sequence",
)
DECISION_PACKET_FORK_FIELDS = (
    "new_slice_candidates",
    "scope_expansions",
    "blocked_followups",
)
DECISION_PACKET_SAFE_FIELD = "safe_to_continue_existing_sequence"
DECISION_PACKET_CUES = (
    "decision packet",
    "safe_to_continue_existing_sequence",
    "new_slice_candidates",
    "scope_expansions",
    "blocked_followups",
)
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
class ResearchImportRequest:
    title: str
    text: str
    text_source: str = "--text"
    target: str = ""
    topic: str = ""
    source_label: str = ""
    related_prompt: str = ""
    input_path: str = ""
    source_attachment: str = ""
    source_members: tuple[str, ...] = ()
    adopt_existing: bool = False


@dataclass(frozen=True)
class ResearchImportTarget:
    title: str
    text: str
    text_source: str
    rel_path: str
    path: Path
    topic: str
    source_label: str
    related_prompt: str
    input_path: str
    source_attachment: str
    source_members: tuple[str, ...]
    imported_text_hash: str
    adopt_existing: bool = False


@dataclass(frozen=True)
class DiscoveryPacketRequest:
    topic: str
    goal: str = ""
    target: str = ""
    packet_id: str = ""
    quality_status: str = QUALITY_STATUS_PROVISIONAL
    planning_reliance: str = PLANNING_RELIANCE_BLOCKED
    discovery_status: str = DISCOVERY_PACKET_DEFAULT_STATUS
    source_refs: tuple[str, ...] = ()
    source_members: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    selected_option: str = ""
    rationale: str = ""
    open_questions: tuple[str, ...] = ()
    stop_conditions: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoveryPacketTarget:
    topic: str
    goal: str
    rel_path: str
    path: Path
    packet_id: str
    quality_status: str
    planning_reliance: str
    discovery_status: str
    source_refs: tuple[str, ...]
    source_members: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    selected_option: str
    rationale: str
    open_questions: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    missing_refs: tuple[str, ...]
    source_ref_errors: tuple[str, ...]
    source_hashes: tuple[str, ...]


def make_research_import_request(
    title: str | None,
    text: str | None,
    *,
    text_source: str = "--text",
    target: str | None = None,
    topic: str | None = None,
    source_label: str | None = None,
    related_prompt: str | None = None,
    input_path: str | None = None,
    source_attachment: str | None = None,
    source_members: Sequence[str] | None = None,
    adopt_existing: bool = False,
) -> ResearchImportRequest:
    return ResearchImportRequest(
        title=_normalized_note(title),
        text=str(text or "").strip(),
        text_source=_normalized_note(text_source) or "--text",
        target=_normalize_rel(target),
        topic=_normalized_note(topic),
        source_label=_normalized_note(source_label),
        related_prompt=_normalize_rel(related_prompt),
        input_path=_normalized_note(input_path),
        source_attachment=_normalize_rel(source_attachment),
        source_members=_normalize_rel_sequence(source_members),
        adopt_existing=adopt_existing,
    )


def make_discovery_packet_request(
    topic: str | None,
    *,
    goal: str | None = None,
    target: str | None = None,
    packet_id: str | None = None,
    quality_status: str | None = None,
    planning_reliance: str | None = None,
    discovery_status: str | None = None,
    source_refs: Sequence[str] | None = None,
    source_members: Sequence[str] | None = None,
    evidence_refs: Sequence[str] | None = None,
    selected_option: str | None = None,
    rationale: str | None = None,
    open_questions: Sequence[str] | None = None,
    stop_conditions: Sequence[str] | None = None,
) -> DiscoveryPacketRequest:
    normalized_topic = _normalized_note(topic)
    return DiscoveryPacketRequest(
        topic=normalized_topic,
        goal=_normalized_note(goal) or normalized_topic,
        target=_normalize_rel(target),
        packet_id=_normalized_note(packet_id) or _safe_slug(normalized_topic),
        quality_status=_normalized_note(quality_status) or QUALITY_STATUS_PROVISIONAL,
        planning_reliance=_normalized_note(planning_reliance) or PLANNING_RELIANCE_BLOCKED,
        discovery_status=_normalized_note(discovery_status) or DISCOVERY_PACKET_DEFAULT_STATUS,
        source_refs=_normalize_rel_sequence(source_refs),
        source_members=_normalize_rel_sequence(source_members),
        evidence_refs=_normalize_rel_sequence(evidence_refs),
        selected_option=_normalized_note(selected_option),
        rationale=_normalized_note(rationale),
        open_questions=_normalized_note_sequence(open_questions),
        stop_conditions=_normalized_note_sequence(stop_conditions),
    )


def discovery_packet_dry_run_findings(inventory: Inventory, request: DiscoveryPacketRequest) -> list[Finding]:
    target = _discovery_packet_target(inventory, request)
    findings = [
        Finding("info", "discover-dry-run", "discovery packet proposal only; no files were written"),
        _root_posture_finding(inventory, "discover"),
        *lifecycle_mutation_provenance_findings(inventory, "discover-lifecycle-provenance"),
    ]
    errors = _discovery_packet_preflight_errors(inventory, request, target)
    if target:
        findings.extend(_discovery_target_findings(target, apply=False))
    if target and not errors:
        rendered, render_findings = _render_discovery_packet(inventory.root, target)
        findings.extend(render_findings)
        findings.extend(route_write_findings("discover-route-write", (_route_write(inventory.root, target.rel_path, rendered),), apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "discover-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing the discovery packet",
            )
        )
        return findings
    findings.extend(_discovery_boundary_findings())
    findings.append(
        Finding(
            "info",
            "discover-validation-posture",
            "apply would write one explicit discovery packet in a live operating root; dry-run writes no files",
            target.rel_path if target else RESEARCH_DIR_REL,
        )
    )
    return findings


def discovery_packet_apply_findings(inventory: Inventory, request: DiscoveryPacketRequest) -> list[Finding]:
    target = _discovery_packet_target(inventory, request)
    errors = _discovery_packet_preflight_errors(inventory, request, target)
    if errors:
        return errors
    assert target is not None

    rendered, render_findings = _render_discovery_packet(inventory.root, target)
    write_evidence = _route_write(inventory.root, target.rel_path, rendered)
    tmp_path = target.path.with_name(f".{target.path.name}.discover.tmp")
    backup_path = target.path.with_name(f".{target.path.name}.discover.backup")
    try:
        cleanup_warnings = apply_file_transaction(
            (AtomicFileWrite(target.path, tmp_path, rendered, backup_path),),
            root=inventory.root,
        )
    except OSError as exc:
        return [Finding("error", "discover-refused", f"discover apply failed before all target writes completed: {exc}", target.rel_path)]

    findings = [
        Finding("info", "discover-apply", "discovery packet apply started"),
        _root_posture_finding(inventory, "discover"),
        *lifecycle_mutation_provenance_findings(inventory, "discover-lifecycle-provenance"),
        *_discovery_target_findings(target, apply=True),
        *render_findings,
        Finding("info", "discover-written", "created discovery packet artifact", target.rel_path),
        *route_write_findings("discover-route-write", (write_evidence,), apply=True),
        *_discovery_boundary_findings(),
        Finding(
            "info",
            "discover-validation-posture",
            "run check after apply to verify discovery packet quality gates and roadmap readiness; packet evidence remains non-authority until consumed by explicit lifecycle rails",
            target.rel_path,
        ),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "discover-backup-cleanup", warning, target.rel_path))
    return findings


def research_import_dry_run_findings(inventory: Inventory, request: ResearchImportRequest) -> list[Finding]:
    target = _research_import_target(inventory, request)
    findings = [
        Finding("info", "research-import-dry-run", "research import proposal only; no files were written"),
        _root_posture_finding(inventory),
        *lifecycle_mutation_provenance_findings(inventory, "research-import-lifecycle-provenance"),
    ]
    errors = _research_import_preflight_errors(inventory, request, target)
    if target:
        findings.extend(_target_findings(target, apply=False))
    if target and not errors:
        if target.adopt_existing:
            rendered, render_findings, already_adopted = _render_research_adoption(inventory.root, target)
            findings.extend(render_findings)
            if not already_adopted:
                findings.extend(
                    route_write_findings(
                        "research-import-adopt-existing-route-write",
                        (_route_write(inventory.root, target.rel_path, rendered),),
                        apply=False,
                    )
                )
        else:
            rendered, render_findings = _render_research_import(inventory.root, target)
            findings.extend(render_findings)
            findings.extend(route_write_findings("research-import-route-write", (_route_write(inventory.root, target.rel_path, rendered),), apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "research-import-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before importing research",
            )
        )
        return findings
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "research-import-validation-posture",
            "apply would write one imported research artifact in a live operating root; dry-run writes no files",
            target.rel_path if target else RESEARCH_DIR_REL,
        )
    )
    return findings


def research_import_apply_findings(inventory: Inventory, request: ResearchImportRequest) -> list[Finding]:
    target = _research_import_target(inventory, request)
    errors = _research_import_preflight_errors(inventory, request, target)
    if errors:
        return errors
    assert target is not None

    if target.adopt_existing:
        rendered, render_findings, already_adopted = _render_research_adoption(inventory.root, target)
        if already_adopted:
            return [
                Finding("info", "research-import-apply", "research import apply started"),
                _root_posture_finding(inventory),
                *lifecycle_mutation_provenance_findings(inventory, "research-import-lifecycle-provenance"),
                *_target_findings(target, apply=True),
                *render_findings,
                *_boundary_findings(),
                Finding(
                    "info",
                    "research-import-validation-posture",
                    "existing research artifact already has valid route-visible frontmatter; no file write was needed",
                    target.rel_path,
                ),
            ]
        write_evidence = _route_write(inventory.root, target.rel_path, rendered)
        tmp_path = target.path.with_name(f".{target.path.name}.research-adopt.tmp")
        backup_path = target.path.with_name(f".{target.path.name}.research-adopt.backup")
        try:
            cleanup_warnings = apply_file_transaction(
                (AtomicFileWrite(target.path, tmp_path, rendered, backup_path),),
                root=inventory.root,
            )
        except OSError as exc:
            return [Finding("error", "research-import-refused", f"research adoption apply failed before all target writes completed: {exc}", target.rel_path)]

        findings = [
            Finding("info", "research-import-apply", "research import apply started"),
            _root_posture_finding(inventory),
            *lifecycle_mutation_provenance_findings(inventory, "research-import-lifecycle-provenance"),
            *_target_findings(target, apply=True),
            *render_findings,
            Finding("info", "research-import-adopt-existing-written", "adopted existing research artifact", target.rel_path),
            *route_write_findings("research-import-adopt-existing-route-write", (write_evidence,), apply=True),
            *_boundary_findings(),
            Finding(
                "info",
                "research-import-validation-posture",
                "run check after apply to verify the adopted research artifact is route-visible; adopted research remains non-authority until promoted",
                target.rel_path,
            ),
        ]
        for warning in cleanup_warnings:
            findings.append(Finding("warn", "research-import-backup-cleanup", warning, target.rel_path))
        return findings

    rendered, render_findings = _render_research_import(inventory.root, target)
    write_evidence = _route_write(inventory.root, target.rel_path, rendered)
    tmp_path = target.path.with_name(f".{target.path.name}.research-import.tmp")
    backup_path = target.path.with_name(f".{target.path.name}.research-import.backup")
    try:
        cleanup_warnings = apply_file_transaction(
            (AtomicFileWrite(target.path, tmp_path, rendered, backup_path),),
            root=inventory.root,
        )
    except OSError as exc:
        return [Finding("error", "research-import-refused", f"research import apply failed before all target writes completed: {exc}", target.rel_path)]

    findings = [
        Finding("info", "research-import-apply", "research import apply started"),
        _root_posture_finding(inventory),
        *lifecycle_mutation_provenance_findings(inventory, "research-import-lifecycle-provenance"),
        *_target_findings(target, apply=True),
        *render_findings,
        Finding("info", "research-import-written", "created imported research artifact", target.rel_path),
        *route_write_findings("research-import-route-write", (write_evidence,), apply=True),
        *_boundary_findings(),
        Finding(
            "info",
            "research-import-validation-posture",
            "run check after apply to verify the live operating root remains healthy; imported research remains non-authority until promoted",
            target.rel_path,
        ),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "research-import-backup-cleanup", warning, target.rel_path))
    return findings


def _research_import_target(inventory: Inventory, request: ResearchImportRequest) -> ResearchImportTarget | None:
    rel_path = request.target or _default_research_rel(request.title)
    if not rel_path:
        return None
    text = request.text or _attachment_research_stub(request)
    imported_text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
    return ResearchImportTarget(
        title=request.title or _title_from_research_rel(rel_path),
        text=text,
        text_source=request.text_source,
        rel_path=rel_path,
        path=inventory.root / rel_path,
        topic=request.topic or request.title or _title_from_research_rel(rel_path),
        source_label=request.source_label,
        related_prompt=request.related_prompt,
        input_path=request.input_path,
        source_attachment=request.source_attachment,
        source_members=request.source_members,
        imported_text_hash=imported_text_hash,
        adopt_existing=request.adopt_existing,
    )


def _discovery_packet_target(inventory: Inventory, request: DiscoveryPacketRequest) -> DiscoveryPacketTarget | None:
    rel_path = request.target or _default_discovery_packet_rel(request.topic)
    if not rel_path:
        return None
    refs = (*request.source_refs, *request.source_members, *request.evidence_refs)
    missing_refs, source_ref_errors, source_hashes = _discovery_ref_inventory(inventory.root, refs)
    return DiscoveryPacketTarget(
        topic=request.topic,
        goal=request.goal or request.topic,
        rel_path=rel_path,
        path=inventory.root / rel_path,
        packet_id=request.packet_id or _safe_slug(request.topic),
        quality_status=request.quality_status,
        planning_reliance=request.planning_reliance,
        discovery_status=request.discovery_status,
        source_refs=request.source_refs,
        source_members=request.source_members,
        evidence_refs=request.evidence_refs,
        selected_option=request.selected_option,
        rationale=request.rationale,
        open_questions=request.open_questions,
        stop_conditions=request.stop_conditions,
        missing_refs=missing_refs,
        source_ref_errors=source_ref_errors,
        source_hashes=source_hashes,
    )


def _research_import_preflight_errors(
    inventory: Inventory,
    request: ResearchImportRequest,
    target: ResearchImportTarget | None,
) -> list[Finding]:
    errors: list[Finding] = []
    if request.adopt_existing and not request.target:
        errors.append(Finding("error", "research-import-refused", "--adopt-existing requires an explicit --target under project/research/*.md"))
    if request.adopt_existing and (request.text or request.source_attachment):
        errors.append(
            Finding(
                "error",
                "research-import-refused",
                "--adopt-existing cannot be combined with --text, --text-file, or --from-attachment",
                request.target or RESEARCH_DIR_REL,
            )
        )
    if not request.adopt_existing and not request.title:
        errors.append(Finding("error", "research-import-refused", "--title is required and cannot be empty or whitespace-only"))
    elif target is None and request.adopt_existing:
        errors.append(Finding("error", "research-import-refused", "--adopt-existing requires a safe root-relative --target"))
    elif target is None:
        errors.append(Finding("error", "research-import-refused", "--title does not produce a safe non-empty ASCII target slug"))
    if not request.adopt_existing and not request.text and not request.source_attachment:
        errors.append(Finding("error", "research-import-refused", "research text or --from-attachment is required and cannot be empty"))
    if request.target and _root_relative_path_conflict(request.target):
        errors.append(Finding("error", "research-import-refused", f"target {_root_relative_path_conflict(request.target)}", request.target))
    if request.related_prompt and _root_relative_path_conflict(request.related_prompt):
        errors.append(Finding("error", "research-import-refused", f"related prompt {_root_relative_path_conflict(request.related_prompt)}", request.related_prompt))
    errors.extend(_research_import_source_member_errors(request.source_members))
    if request.source_attachment:
        errors.extend(_source_attachment_preflight_errors(inventory, request.source_attachment))

    if inventory.root_kind == "product_source_fixture":
        errors.append(
            Finding(
                "error",
                "research-import-refused",
                "target is a product-source compatibility fixture; research-import --apply is refused",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(
            Finding(
                "error",
                "research-import-refused",
                "target is fallback/archive or generated-output evidence; research-import --apply is refused",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "research-import-refused", f"target root kind is {inventory.root_kind}; research import requires a live operating root"))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "research-import-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "research-import-refused", "project-state.md frontmatter is required for research import apply", state.rel_path))
    elif state.frontmatter.errors:
        errors.append(Finding("error", "research-import-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "research-import-refused", "project-state.md is not a regular file", state.rel_path))
    elif state.path.is_symlink():
        errors.append(Finding("error", "research-import-refused", "project-state.md is a symlink", state.rel_path))

    research_dir = inventory.root / RESEARCH_DIR_REL
    if _path_escapes_root(inventory.root, research_dir):
        errors.append(Finding("error", "research-import-refused", "research directory path escapes the target root", RESEARCH_DIR_REL))
    for parent in _parents_between(inventory.root, research_dir):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "research-import-refused", f"research directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "research-import-refused", f"research directory contains a non-directory segment: {rel}", rel))

    if target:
        if not target.rel_path.startswith(f"{RESEARCH_DIR_REL}/") or not target.rel_path.endswith(".md"):
            errors.append(Finding("error", "research-import-refused", f"target must be under {RESEARCH_DIR_REL}/*.md", target.rel_path))
        if _path_escapes_root(inventory.root, target.path):
            errors.append(Finding("error", "research-import-refused", "target research path escapes the target root", target.rel_path))
        elif target.path.exists():
            if target.path.is_symlink():
                errors.append(Finding("error", "research-import-refused", "target research artifact is a symlink; overwrite is refused", target.rel_path))
            elif not target.path.is_file():
                errors.append(Finding("error", "research-import-refused", "target research artifact path exists but is not a regular file", target.rel_path))
            elif target.adopt_existing:
                errors.extend(_research_adoption_preflight_errors(target))
            else:
                errors.append(Finding("error", "research-import-refused", "target research artifact already exists; choose a new --target", target.rel_path))
        elif target.adopt_existing:
            errors.append(Finding("error", "research-import-refused", "target research artifact must already exist for --adopt-existing", target.rel_path))
    return errors


def _research_import_source_member_errors(source_members: tuple[str, ...]) -> list[Finding]:
    errors: list[Finding] = []
    for source_member in source_members:
        if _root_relative_path_conflict(source_member):
            errors.append(Finding("error", "research-import-refused", f"source member {_root_relative_path_conflict(source_member)}", source_member))
            continue
        destination_problem = route_destination_problem("source_members", source_member, owner_route_id="research")
        if destination_problem:
            errors.append(Finding("error", "research-import-refused", f"--source-member {destination_problem}", source_member))
    return errors


def _research_adoption_preflight_errors(target: ResearchImportTarget) -> list[Finding]:
    try:
        text = target.path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [Finding("error", "research-import-refused", f"target research artifact is not valid UTF-8 text: {exc}", target.rel_path)]
    except OSError as exc:
        return [Finding("error", "research-import-refused", f"target research artifact is unreadable: {exc}", target.rel_path)]
    frontmatter = parse_frontmatter(text)
    if frontmatter.errors:
        return [
            Finding(
                "error",
                "research-import-refused",
                "target research artifact frontmatter is malformed; repair or review it before adoption",
                target.rel_path,
            )
        ]
    if frontmatter.has_frontmatter:
        status = str(frontmatter.data.get("status") or "").strip().casefold()
        if status not in RESEARCH_ROUTE_STATUSES:
            return [
                Finding(
                    "error",
                    "research-import-refused",
                    "target research artifact already has frontmatter but no recognized research status; repair manually before adoption",
                    target.rel_path,
                )
            ]
        existing_members = tuple(_frontmatter_string_values(frontmatter.data.get("source_members")))
        errors = _research_import_source_member_errors(tuple(_dedupe((*existing_members, *target.source_members))))
        if errors:
            return errors
    return []


def _source_attachment_preflight_errors(inventory: Inventory, rel_path: str) -> list[Finding]:
    errors: list[Finding] = []
    conflict = _root_relative_path_conflict(rel_path)
    if conflict:
        return [Finding("error", "research-import-refused", f"source attachment {conflict}", rel_path)]
    if not rel_path.startswith("project/attachments/") or not rel_path.endswith("/artifact.md"):
        errors.append(Finding("error", "research-import-refused", "source attachment must point to project/attachments/**/artifact.md", rel_path))
    path = inventory.root / rel_path
    if _path_escapes_root(inventory.root, path):
        errors.append(Finding("error", "research-import-refused", "source attachment path escapes the target root", rel_path))
        return errors
    if not path.exists():
        errors.append(Finding("error", "research-import-refused", "source attachment metadata card is missing", rel_path))
        return errors
    if path.is_symlink():
        errors.append(Finding("error", "research-import-refused", "source attachment metadata card is a symlink", rel_path))
        return errors
    if not path.is_file():
        errors.append(Finding("error", "research-import-refused", "source attachment metadata card is not a regular file", rel_path))
        return errors
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding("error", "research-import-refused", f"source attachment metadata card is unreadable: {exc}", rel_path)]
    frontmatter = parse_frontmatter(text)
    if not frontmatter.has_frontmatter:
        errors.append(Finding("error", "research-import-refused", "source attachment metadata card requires frontmatter", rel_path))
        return errors
    if frontmatter.errors:
        errors.append(Finding("error", "research-import-refused", "source attachment metadata card frontmatter is malformed", rel_path))
        return errors
    if frontmatter.data.get("type") != "attachment":
        errors.append(Finding("error", "research-import-refused", 'source attachment card type must be "attachment"', rel_path))
    if frontmatter.data.get("status") != "imported":
        errors.append(Finding("error", "research-import-refused", 'source attachment card status must be "imported"', rel_path))
    source_file = str(frontmatter.data.get("source_file") or "")
    if not source_file or _root_relative_path_conflict(source_file):
        errors.append(Finding("error", "research-import-refused", "source attachment card source_file must be a safe card-relative file name", rel_path))
        return errors
    binary_path = path.parent / source_file
    if _path_escapes_root(path.parent, binary_path):
        errors.append(Finding("error", "research-import-refused", "source attachment card source_file escapes its attachment directory", rel_path))
        return errors
    if not binary_path.exists():
        errors.append(Finding("error", "research-import-refused", f"source attachment binary is missing: {source_file}", rel_path))
    elif binary_path.is_symlink():
        errors.append(Finding("error", "research-import-refused", f"source attachment binary is a symlink: {source_file}", rel_path))
    elif not binary_path.is_file():
        errors.append(Finding("error", "research-import-refused", f"source attachment binary is not a regular file: {source_file}", rel_path))
    return errors


def _discovery_packet_preflight_errors(
    inventory: Inventory,
    request: DiscoveryPacketRequest,
    target: DiscoveryPacketTarget | None,
) -> list[Finding]:
    errors: list[Finding] = []
    if not request.topic:
        errors.append(Finding("error", "discover-refused", "--topic is required and cannot be empty or whitespace-only"))
    elif target is None:
        errors.append(Finding("error", "discover-refused", "--topic does not produce a safe non-empty ASCII target slug"))
    if request.target and _root_relative_path_conflict(request.target):
        errors.append(Finding("error", "discover-refused", f"target {_root_relative_path_conflict(request.target)}", request.target))
    for label, refs in (
        ("source-ref", request.source_refs),
        ("source-member", request.source_members),
        ("evidence-ref", request.evidence_refs),
    ):
        for ref in refs:
            if _root_relative_path_conflict(ref):
                errors.append(Finding("error", "discover-refused", f"{label} {_root_relative_path_conflict(ref)}", ref))
    if not any((request.source_refs, request.source_members, request.evidence_refs)):
        errors.append(
            Finding(
                "error",
                "discover-refused",
                "at least one --source-ref, --source-member, or --evidence-ref is required so the packet stays source-bound",
            )
        )
    if request.quality_status not in _DISCOVERY_PACKET_QUALITY_STATUSES:
        errors.append(
            Finding(
                "error",
                "discover-refused",
                f"--quality-status must be {QUALITY_STATUS_SUFFICIENT} or {QUALITY_STATUS_PROVISIONAL}",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    if request.planning_reliance not in _DISCOVERY_PACKET_PLANNING_RELIANCE:
        errors.append(
            Finding(
                "error",
                "discover-refused",
                f"--planning-reliance must be {PLANNING_RELIANCE_ALLOWED} or {PLANNING_RELIANCE_BLOCKED}",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    if request.discovery_status not in DISCOVERY_PACKET_STATUSES:
        errors.append(
            Finding(
                "error",
                "discover-refused",
                "--discovery-status must be ready-for-plan, blocked, contested, or draft",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    if request.discovery_status in DISCOVERY_PACKET_BLOCKED_STATUSES and request.planning_reliance == PLANNING_RELIANCE_ALLOWED:
        errors.append(
            Finding(
                "error",
                "discover-refused",
                f"discovery_status={request.discovery_status} must use planning_reliance={PLANNING_RELIANCE_BLOCKED}",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    if target and target.source_ref_errors:
        for error in target.source_ref_errors:
            errors.append(Finding("error", "discover-refused", f"unsafe source/evidence ref: {error}", target.rel_path))
    if (
        target
        and target.missing_refs
        and target.quality_status == QUALITY_STATUS_SUFFICIENT
        and target.planning_reliance == PLANNING_RELIANCE_ALLOWED
    ):
        errors.append(
            Finding(
                "error",
                "discover-refused",
                "allowed discovery packets require existing source/evidence refs; missing: " + ", ".join(target.missing_refs),
                target.rel_path,
            )
        )

    if inventory.root_kind == "product_source_fixture":
        errors.append(
            Finding(
                "error",
                "discover-refused",
                "target is a product-source compatibility fixture; discover --apply is refused",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(
            Finding(
                "error",
                "discover-refused",
                "target is fallback/archive or generated-output evidence; discover --apply is refused",
                target.rel_path if target else RESEARCH_DIR_REL,
            )
        )
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "discover-refused", f"target root kind is {inventory.root_kind}; discover requires a live operating root"))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "discover-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "discover-refused", "project-state.md frontmatter is required for discover apply", state.rel_path))
    elif state.frontmatter.errors:
        errors.append(Finding("error", "discover-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "discover-refused", "project-state.md is not a regular file", state.rel_path))
    elif state.path.is_symlink():
        errors.append(Finding("error", "discover-refused", "project-state.md is a symlink", state.rel_path))

    research_dir = inventory.root / RESEARCH_DIR_REL
    if _path_escapes_root(inventory.root, research_dir):
        errors.append(Finding("error", "discover-refused", "research directory path escapes the target root", RESEARCH_DIR_REL))
    for parent in _parents_between(inventory.root, research_dir):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "discover-refused", f"research directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "discover-refused", f"research directory contains a non-directory segment: {rel}", rel))

    if target:
        if not target.rel_path.startswith(f"{RESEARCH_DIR_REL}/") or not target.rel_path.endswith(".md"):
            errors.append(Finding("error", "discover-refused", f"target must be under {RESEARCH_DIR_REL}/*.md", target.rel_path))
        if _path_escapes_root(inventory.root, target.path):
            errors.append(Finding("error", "discover-refused", "target discovery packet path escapes the target root", target.rel_path))
        elif target.path.exists():
            if target.path.is_symlink():
                errors.append(Finding("error", "discover-refused", "target discovery packet is a symlink; overwrite is refused", target.rel_path))
            elif not target.path.is_file():
                errors.append(Finding("error", "discover-refused", "target discovery packet path exists but is not a regular file", target.rel_path))
            else:
                errors.append(Finding("error", "discover-refused", "target discovery packet already exists; choose a new --target", target.rel_path))
    return errors


def _render_research_import(root: Path, target: ResearchImportTarget) -> tuple[str, list[Finding]]:
    today = date.today().isoformat()
    source_hashes = _source_hash_entries(root, target)
    frontmatter: list[str] = [
        "---",
        'status: "imported"',
        f'topic: "{_yaml_double_quoted_value(target.topic)}"',
        f'title: "{_yaml_double_quoted_value(target.title)}"',
        f'created: "{today}"',
        f'last_reviewed: "{today}"',
        f'derived_from: "{_yaml_double_quoted_value(target.source_label or target.text_source)}"',
        "related_artifacts:",
    ]
    if target.related_prompt:
        frontmatter.append(f'  - "{_yaml_double_quoted_value(target.related_prompt)}"')
    else:
        frontmatter.append('  - "none"')
    frontmatter.extend(
        (
            *_optional_yaml_list_lines("source_members", target.source_members),
            *_yaml_source_attachments_lines(target),
            "source_hashes:",
            *(f'  - "{_yaml_double_quoted_value(entry)}"' for entry in source_hashes),
            "---",
        )
    )

    lines = [
        *frontmatter,
        f"# {target.title}",
        "",
        NON_AUTHORITY_NOTE,
        "",
        "## Provenance",
        "",
        f"- Import rail: `{RESEARCH_IMPORT_SOURCE}`",
        f"- Input source: `{target.text_source}`",
        f"- Source label: `{target.source_label or 'not supplied'}`",
        f"- Imported text sha256: `{target.imported_text_hash}`",
        f"- Related prompt: `{target.related_prompt or 'not supplied'}`",
        f"- Source attachment: `{target.source_attachment or 'not supplied'}`",
        *_markdown_ref_lines("source_members", target.source_members),
        "",
        "## Source Hashes",
        "",
    ]
    lines.extend(f"- `{entry}`" for entry in source_hashes)
    lines.extend(_decision_packet_render_lines(target))
    lines.extend(
        [
            "",
            "## Imported Research",
            "",
            target.text.rstrip(),
            "",
            "## Boundaries",
            "",
            "- This artifact records imported research/provenance only.",
            "- It does not promote findings to stable specs, open or close plans, archive plans, update roadmap status, stage files, or commit.",
            "- Promotion into specs, plans, or project state requires a later explicit lifecycle command or human-reviewed edit.",
            "",
        ]
    )
    findings = [
        Finding("info", "research-import-source-hash", f"imported text sha256={target.imported_text_hash[:12]}", target.rel_path),
        Finding("info", "research-import-non-authority", NON_AUTHORITY_NOTE, target.rel_path),
        *_decision_packet_findings(target),
    ]
    return "\n".join(lines), findings


def _render_research_adoption(root: Path, target: ResearchImportTarget) -> tuple[str, list[Finding], bool]:
    text = target.path.read_text(encoding="utf-8")
    pre_adoption_hash = hashlib.sha256(target.path.read_bytes()).hexdigest()
    frontmatter = parse_frontmatter(text)
    findings = [
        Finding("info", "research-import-adopt-existing-source-hash", f"pre-adoption file sha256={pre_adoption_hash[:12]}", target.rel_path),
        Finding("info", "research-import-non-authority", NON_AUTHORITY_NOTE, target.rel_path),
    ]
    if frontmatter.has_frontmatter:
        repaired = _adopt_existing_text_with_source_members(text, frontmatter, target.source_members)
        if repaired != text:
            findings.append(
                Finding(
                    "info",
                    "research-import-adopt-existing-source-members-repaired",
                    "would add explicit source_members metadata to existing route-visible research artifact",
                    target.rel_path,
                )
            )
            return repaired, findings, False
        findings.append(
            Finding(
                "info",
                "research-import-adopt-existing-already-route-visible",
                "existing research artifact already has valid route-visible frontmatter; no file write is needed",
                target.rel_path,
            )
        )
        return text, findings, True

    today = date.today().isoformat()
    source_hashes = (f"pre_adoption_file sha256={pre_adoption_hash}",)
    metadata = [
        "---",
        'status: "imported"',
        f'topic: "{_yaml_double_quoted_value(target.topic)}"',
        f'title: "{_yaml_double_quoted_value(target.title)}"',
        f'created: "{today}"',
        f'last_reviewed: "{today}"',
        'derived_from: "existing project/research artifact"',
        'adoption_mode: "existing-target"',
        "related_artifacts:",
    ]
    if target.related_prompt:
        metadata.append(f'  - "{_yaml_double_quoted_value(target.related_prompt)}"')
    else:
        metadata.append('  - "none"')
    metadata.extend(
        (
            *_optional_yaml_list_lines("source_members", target.source_members),
            "source_attachments: []",
            "source_hashes:",
            *(f'  - "{_yaml_double_quoted_value(entry)}"' for entry in source_hashes),
            "---",
        )
    )
    findings.append(
        Finding(
            "info",
            "research-import-adopt-existing-metadata",
            "would prepend route-visible research frontmatter while preserving the existing body",
            target.rel_path,
        )
    )
    return "\n".join(metadata) + "\n" + text, findings, False


def _render_discovery_packet(root: Path, target: DiscoveryPacketTarget) -> tuple[str, list[Finding]]:
    today = date.today().isoformat()
    gate_issues = _discovery_quality_gate_issues(target)
    frontmatter: list[str] = [
        "---",
        f'schema: "{DISCOVERY_PACKET_SCHEMA}"',
        f'source_type: "{DISCOVERY_PACKET_SOURCE_TYPE}"',
        'status: "research-ready"',
        f'topic: "{_yaml_double_quoted_value(target.topic)}"',
        f'title: "{_yaml_double_quoted_value(target.topic)} Discovery Packet"',
        f'packet_id: "{_yaml_double_quoted_value(target.packet_id)}"',
        f'created: "{today}"',
        f'last_reviewed: "{today}"',
        f'discovery_status: "{_yaml_double_quoted_value(target.discovery_status)}"',
        f'quality_status: "{_yaml_double_quoted_value(target.quality_status)}"',
        f'planning_reliance: "{_yaml_double_quoted_value(target.planning_reliance)}"',
        *_yaml_list_lines("source_refs", target.source_refs),
        *_yaml_list_lines("source_members", target.source_members),
        *_yaml_list_lines("evidence_refs", target.evidence_refs),
        *_yaml_list_lines("source_hashes", target.source_hashes),
    ]
    if gate_issues:
        frontmatter.extend(_yaml_list_lines("quality_gate_issues", gate_issues))
    frontmatter.extend(
        [
            "roles:",
            "  repo_researcher:",
            '    status: "operator-supplied"',
            "    evidence_refs:",
            *_yaml_indented_list_lines((*target.source_refs, *target.source_members), indent="      "),
            "  plan_reviewer:",
            f'    status: "{_yaml_double_quoted_value(target.discovery_status)}"',
            "recommendation:",
            f'  selected_option: "{_yaml_double_quoted_value(target.selected_option or "not supplied")}"',
            f'  rationale: "{_yaml_double_quoted_value(target.rationale or "not supplied")}"',
            "---",
        ]
    )

    lines = [
        *frontmatter,
        f"# {target.topic} Discovery Packet",
        "",
        DISCOVERY_PACKET_NON_AUTHORITY_NOTE,
        "",
        "## Goal",
        "",
        f"- Topic: {target.topic}",
        f"- Goal: {target.goal or target.topic}",
        "",
        "## Source Evidence",
        "",
        *_markdown_ref_lines("source_refs", target.source_refs),
        *_markdown_ref_lines("source_members", target.source_members),
        *_markdown_ref_lines("evidence_refs", target.evidence_refs),
        "",
        "## Source Hashes",
        "",
    ]
    lines.extend(f"- `{entry}`" for entry in target.source_hashes)
    if not target.source_hashes:
        lines.append("- No existing source refs were hashable at write time.")
    lines.extend(
        [
            "",
            "## Readiness Gate",
            "",
            f"- Discovery status: `{target.discovery_status}`",
            f"- Quality status: `{target.quality_status}`",
            f"- Planning reliance: `{target.planning_reliance}`",
        ]
    )
    if gate_issues:
        lines.extend(f"- Gate issue: {issue}" for issue in gate_issues)
    else:
        lines.append("- Gate issue: none recorded by operator input.")
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- Selected option: {target.selected_option or 'not supplied'}",
            f"- Rationale: {target.rationale or 'not supplied'}",
            "",
            "## Open Questions",
            "",
            *_markdown_list_or_none(target.open_questions),
            "",
            "## Stop Conditions",
            "",
            *_markdown_list_or_none(target.stop_conditions),
            "",
            "## Boundaries",
            "",
            "- This artifact records pre-plan discovery evidence only.",
            "- It does not run research, call providers, synthesize hidden judgment, open a plan, close a phase, archive plans, update roadmap status, stage files, or commit.",
            "- Planning may rely on it only when explicit quality_status and planning_reliance fields satisfy the existing research gate vocabulary.",
            "",
        ]
    )
    findings = [
        Finding("info", "discover-source-hash", f"source/evidence hashes={len(target.source_hashes)}", target.rel_path),
        Finding(
            "info",
            "discover-quality-gate",
            f"discovery_status={target.discovery_status}; quality_status={target.quality_status}; planning_reliance={target.planning_reliance}",
            target.rel_path,
        ),
        Finding("info", "discover-non-authority", DISCOVERY_PACKET_NON_AUTHORITY_NOTE, target.rel_path),
    ]
    if target.missing_refs:
        findings.append(
            Finding(
                "warn",
                "discover-source-ref-missing",
                "discovery packet records missing source/evidence refs: " + ", ".join(target.missing_refs),
                target.rel_path,
            )
        )
    for entry in target.source_hashes:
        findings.append(Finding("info", "discover-source-ref", entry, target.rel_path))
    return "\n".join(lines), findings


def _source_hash_entries(root: Path, target: ResearchImportTarget) -> tuple[str, ...]:
    entries = [f"imported_text sha256={target.imported_text_hash}"]
    for source_member in target.source_members:
        path = root / source_member
        if path.is_file():
            entries.append(_source_ref_hash(root, source_member))
    if target.source_attachment:
        attachment_path = root / target.source_attachment
        if attachment_path.is_file():
            entries.append(_source_ref_hash(root, target.source_attachment))
        binary_rel = _attachment_binary_rel(root, target.source_attachment)
        if binary_rel:
            entries.append(_source_ref_hash(root, binary_rel))
    input_path = Path(target.input_path).expanduser() if target.input_path and target.input_path != "-" else None
    if input_path:
        try:
            resolved = input_path.resolve()
            rel = resolved.relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            return tuple(entries)
        if resolved.is_file():
            try:
                entries.append(f"{rel} sha256={hashlib.sha256(resolved.read_bytes()).hexdigest()}")
            except OSError:
                entries.append(f"{rel} unreadable")
    return tuple(entries)


def _adopt_existing_text_with_source_members(text: str, frontmatter: object, source_members: tuple[str, ...]) -> str:
    if not source_members:
        return text
    existing = dict(getattr(frontmatter, "data", {}) or {})
    existing_members = tuple(_frontmatter_string_values(existing.get("source_members")))
    merged_members = tuple(_dedupe((*existing_members, *source_members)))
    if merged_members == existing_members:
        return text
    existing["source_members"] = list(merged_members)
    order = list(existing)
    if "source_members" not in order:
        order.append("source_members")
    updated_frontmatter = "\n".join(("---", *_yaml_frontmatter_lines(existing, order), "---"))
    body_lines = text.splitlines()[getattr(frontmatter, "body_start_line", 1) - 1 :]
    body = "\n".join(body_lines)
    if body and text.endswith("\n"):
        body += "\n"
    return f"{updated_frontmatter}\n{body}" if body else f"{updated_frontmatter}\n"


def _frontmatter_string_values(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()]


def _yaml_frontmatter_lines(metadata: dict[str, object], order: Sequence[str]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for key in (*order, *tuple(metadata)):
        if key in seen or key not in metadata:
            continue
        seen.add(key)
        value = metadata[key]
        if isinstance(value, (list, tuple)):
            values = tuple(str(item).strip() for item in value if str(item).strip())
            if not values:
                continue
            lines.append(f"{key}:")
            lines.extend(f'  - "{_yaml_double_quoted_value(item)}"' for item in values)
        elif value not in (None, ""):
            lines.append(f'{key}: "{_yaml_double_quoted_value(value)}"')
    return lines


def _attachment_binary_rel(root: Path, rel_path: str) -> str:
    card_path = root / rel_path
    try:
        frontmatter = parse_frontmatter(card_path.read_text(encoding="utf-8"))
    except OSError:
        return ""
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return ""
    source_file = _normalize_rel(frontmatter.data.get("source_file"))
    if not source_file or _root_relative_path_conflict(source_file):
        return ""
    binary_path = card_path.parent / source_file
    if _path_escapes_root(card_path.parent, binary_path) or not binary_path.is_file():
        return ""
    try:
        return binary_path.relative_to(root).as_posix()
    except ValueError:
        return ""


def _source_ref_hash(root: Path, rel_path: str) -> str:
    path = root / rel_path
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return f"{rel_path} unreadable"
    return f"{rel_path} sha256={digest}"


def _discovery_ref_inventory(root: Path, refs: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    missing_refs: list[str] = []
    source_ref_errors: list[str] = []
    source_hashes: list[str] = []
    for ref in refs:
        if not ref or _root_relative_path_conflict(ref):
            continue
        path = root / ref
        violation = source_path_boundary_violation(root, path, label="discovery source/evidence ref")
        if violation is not None:
            source_ref_errors.append(f"{ref}: {violation.message}")
            continue
        if not path.exists():
            missing_refs.append(ref)
            continue
        if not path.is_file():
            source_ref_errors.append(f"{ref}: discovery source/evidence ref is not a regular file")
            continue
        source_hashes.append(_source_ref_hash(root, ref))
    return tuple(_dedupe(missing_refs)), tuple(_dedupe(source_ref_errors)), tuple(_dedupe(source_hashes))


def _target_findings(target: ResearchImportTarget, apply: bool) -> list[Finding]:
    verb = "target research artifact" if apply else "would target research artifact"
    findings = [
        Finding("info", "research-import-title", f"normalized title: {target.title}", target.rel_path),
        Finding("info", "research-import-target", f"{verb}: {target.rel_path}", target.rel_path),
    ]
    if target.source_attachment:
        findings.append(Finding("info", "research-import-source-attachment", f"source attachment: {target.source_attachment}", target.rel_path))
    return findings


def _discovery_target_findings(target: DiscoveryPacketTarget, apply: bool) -> list[Finding]:
    verb = "target discovery packet" if apply else "would target discovery packet"
    return [
        Finding("info", "discover-topic", f"normalized topic: {target.topic}", target.rel_path),
        Finding("info", "discover-target", f"{verb}: {target.rel_path}", target.rel_path),
    ]


def _decision_packet_findings(target: ResearchImportTarget) -> list[Finding]:
    if not _looks_like_decision_packet(target.text):
        return []
    fields = {field: _decision_packet_field_value(target.text, field) for field in DECISION_PACKET_FIELDS}
    present = tuple(field for field, value in fields.items() if value is not None)
    missing = tuple(field for field, value in fields.items() if value is None)
    safe_value = fields[DECISION_PACKET_SAFE_FIELD] or ""
    fork_fields = tuple(field for field in DECISION_PACKET_FORK_FIELDS if not _decision_packet_value_is_falsey(fields[field] or ""))
    has_gate_signal = _decision_packet_value_is_true(safe_value) or bool(fork_fields)
    line_count = len(target.text.splitlines()) or 1
    field_summary = ", ".join(f"{field}={'present' if fields[field] is not None else 'missing'}" for field in DECISION_PACKET_FIELDS)
    findings = [
        Finding(
            "info",
            "research-import-decision-packet-field-check",
            f"decision packet field check: lines={line_count}; {field_summary}",
            target.rel_path,
        )
    ]
    for field in DECISION_PACKET_FIELDS:
        value = fields[field]
        if value is None:
            detail = "missing"
        elif value:
            detail = f"present value={_compact_field_value(value)}"
        else:
            detail = "present with empty inline value"
        findings.append(Finding("info", "research-import-decision-packet-field", f"Field {field} -> {detail}", target.rel_path))
    if target.text_source == "--text" and line_count > 1:
        findings.append(
            Finding(
                "info",
                "research-import-decision-packet-text-source",
                "decision packet was supplied through --text; for shell-sensitive multiline packets prefer --text-file - or a reviewed file",
                target.rel_path,
            )
        )
    if has_gate_signal:
        signal = f"{DECISION_PACKET_SAFE_FIELD}: true" if _decision_packet_value_is_true(safe_value) else f"fork fields: {', '.join(fork_fields)}"
        findings.append(Finding("info", "research-import-decision-packet-gate-signal", f"parse-visible decision packet gate signal detected: {signal}", target.rel_path))
    else:
        detail = ", ".join(missing) if missing else "present fields have empty/falsey values"
        findings.append(
            Finding(
                "warn",
                "research-import-decision-packet-incomplete",
                f"decision packet lacks a parse-visible safe-to-continue true value or non-empty fork fields; missing/empty detail: {detail}",
                target.rel_path,
            )
        )
    return findings


def _decision_packet_render_lines(target: ResearchImportTarget) -> list[str]:
    if not _looks_like_decision_packet(target.text):
        return []
    fields = {field: _decision_packet_field_value(target.text, field) for field in DECISION_PACKET_FIELDS}
    safe_value = fields[DECISION_PACKET_SAFE_FIELD] or ""
    fork_fields = tuple(field for field in DECISION_PACKET_FORK_FIELDS if not _decision_packet_value_is_falsey(fields[field] or ""))
    if _decision_packet_value_is_true(safe_value):
        signal = f"{DECISION_PACKET_SAFE_FIELD} true"
    elif fork_fields:
        signal = f"fork fields present: {', '.join(fork_fields)}"
    else:
        signal = "missing safe-to-continue true value or non-empty fork fields"
    lines = [
        "",
        "## Decision Packet Field Check",
        "",
        f"- Imported payload line count: {len(target.text.splitlines()) or 1}",
        f"- Parse-visible gate signal: {signal}",
    ]
    for field in DECISION_PACKET_FIELDS:
        value = fields[field]
        if value is None:
            detail = "missing"
        elif value:
            detail = f"present, value summary `{_compact_field_value(value)}`"
        else:
            detail = "present with empty inline value"
        lines.append(f"- Field {field} -> {detail}")
    return lines


def _looks_like_decision_packet(text: str) -> bool:
    lowered = text.casefold()
    return any(cue in lowered for cue in DECISION_PACKET_CUES) or any(_decision_packet_field_value(text, field) is not None for field in DECISION_PACKET_FIELDS)


def _decision_packet_field_value(text: str, field: str) -> str | None:
    field_names = "|".join(re.escape(name) for name in DECISION_PACKET_FIELDS)
    field_line = re.compile(rf"^\s*(?:[-*]\s*)?`?{re.escape(field)}`?\s*[:=]\s*(.*?)\s*$", re.IGNORECASE)
    any_field_line = re.compile(rf"^\s*(?:[-*]\s*)?`?(?:{field_names})`?\s*[:=]", re.IGNORECASE)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = field_line.match(line)
        if not match:
            continue
        inline_value = match.group(1).strip().strip("`\"'")
        if inline_value:
            return inline_value
        block_lines: list[str] = []
        for next_line in lines[index + 1 :]:
            stripped = next_line.strip()
            if not stripped:
                if block_lines:
                    break
                continue
            if any_field_line.match(next_line) or stripped.startswith("#"):
                break
            block_lines.append(stripped)
        return "\n".join(block_lines)
    return None


def _decision_packet_value_is_true(value: str) -> bool:
    return value.strip().casefold().replace("_", "-") in {"1", "true", "yes", "safe", "continue", "safe-to-continue"}


def _decision_packet_value_is_falsey(value: str) -> bool:
    normalized = value.strip().casefold().replace("_", "-")
    return normalized in {"", "0", "false", "no", "none", "not-needed", "not needed", "[]"}


def _compact_field_value(value: str) -> str:
    compact = " ".join(value.split())
    if len(compact) > 80:
        return f"{compact[:77]}..."
    return compact


def _root_posture_finding(inventory: Inventory, prefix: str = "research-import") -> Finding:
    return Finding("info", f"{prefix}-root-posture", f"root kind: {inventory.root_kind}")


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "research-import-boundary",
            "research-import writes only one project/research/<safe-title>.md artifact in eligible live operating roots; it does not execute models, repair, archive, stage, commit, or mutate product-source fixtures",
        ),
        Finding(
            "info",
            "research-import-authority",
            "imported research is non-authority until promoted into accepted specs, plans, decisions, or state",
        ),
    ]


def _discovery_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "discover-boundary",
            "discover writes only one project/research/<safe-topic>-discovery-packet.md artifact in eligible live operating roots; it does not execute providers, repair, archive, stage, commit, or mutate product-source fixtures",
        ),
        Finding(
            "info",
            "discover-authority",
            "discovery packets are source-bound evidence only; roadmap/plan consumption remains gated by explicit quality_status and planning_reliance fields",
        ),
    ]


def _route_write(root: Path, rel_path: str, after_text: str) -> RouteWriteEvidence:
    target = root / rel_path
    before_text = target.read_text(encoding="utf-8") if target.is_file() else None
    return RouteWriteEvidence(rel_path, before_text, after_text)


def _default_research_rel(title: str) -> str:
    slug = _safe_slug(title)
    if not slug or slug in _RESERVED_SLUGS:
        return ""
    return f"{RESEARCH_DIR_REL}/{date.today().isoformat()}-{slug}.md"


def _title_from_research_rel(rel_path: str) -> str:
    stem = Path(rel_path).stem
    dated = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)
    words = [word for word in re.split(r"[-_]+", dated) if word]
    return " ".join(word.capitalize() for word in words) or "Adopted Research"


def _default_discovery_packet_rel(topic: str) -> str:
    slug = _safe_slug(topic)
    if not slug or slug in _RESERVED_SLUGS:
        return ""
    if not slug.endswith("discovery-packet"):
        slug = f"{slug}-discovery-packet"
    return f"{RESEARCH_DIR_REL}/{date.today().isoformat()}-{slug}.md"


def _safe_slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _normalize_rel(value: str | None) -> str:
    return str(value or "").strip().replace("\\", "/")


def _normalize_rel_sequence(values: Sequence[str] | None) -> tuple[str, ...]:
    return tuple(_dedupe(_normalize_rel(value) for value in (values or ()) if _normalize_rel(value)))


def _normalized_note(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _normalized_note_sequence(values: Sequence[str] | None) -> tuple[str, ...]:
    return tuple(_dedupe(_normalized_note(value) for value in (values or ()) if _normalized_note(value)))


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


def _discovery_quality_gate_issues(target: DiscoveryPacketTarget) -> tuple[str, ...]:
    issues: list[str] = []
    if target.quality_status != QUALITY_STATUS_SUFFICIENT or target.planning_reliance != PLANNING_RELIANCE_ALLOWED:
        issues.append(
            f"operator marked packet {target.quality_status}/{target.planning_reliance}; planning must remain blocked until explicit ready review"
        )
    if target.discovery_status not in DISCOVERY_PACKET_STATUSES:
        issues.append(f"discovery_status={target.discovery_status} is not recognized")
    elif target.discovery_status in DISCOVERY_PACKET_BLOCKED_STATUSES:
        issues.append(f"discovery_status={target.discovery_status} is not ready for planning")
    if target.source_ref_errors:
        issues.append("unsafe referenced evidence: " + ", ".join(target.source_ref_errors))
    if target.missing_refs:
        issues.append("missing referenced evidence: " + ", ".join(target.missing_refs))
    return tuple(_dedupe(issues))


def _yaml_list_lines(key: str, values: tuple[str, ...]) -> list[str]:
    if not values:
        return [f"{key}:", '  - "none"']
    return [f"{key}:", *(f'  - "{_yaml_double_quoted_value(value)}"' for value in values)]


def _optional_yaml_list_lines(key: str, values: tuple[str, ...]) -> list[str]:
    if not values:
        return []
    return [f"{key}:", *(f'  - "{_yaml_double_quoted_value(value)}"' for value in values)]


def _yaml_source_attachments_lines(target: ResearchImportTarget) -> list[str]:
    if not target.source_attachment:
        return ["source_attachments: []"]
    return ["source_attachments:", f'  - "{_yaml_double_quoted_value(target.source_attachment)}"']


def _yaml_indented_list_lines(values: tuple[str, ...], *, indent: str) -> list[str]:
    if not values:
        return [f'{indent}- "none"']
    return [f'{indent}- "{_yaml_double_quoted_value(value)}"' for value in values]


def _markdown_ref_lines(label: str, values: tuple[str, ...]) -> list[str]:
    if not values:
        return [f"- {label}: none supplied"]
    return [f"- {label}: `{value}`" for value in values]


def _markdown_list_or_none(values: tuple[str, ...]) -> list[str]:
    if not values:
        return ["- none supplied"]
    return [f"- {value}" for value in values]


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _yaml_double_quoted_value(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _attachment_research_stub(request: ResearchImportRequest) -> str:
    if not request.source_attachment:
        return ""
    return "\n".join(
        [
            "Attachment research handoff.",
            "",
            f"Source attachment metadata card: {request.source_attachment}",
            "",
            "Review the binary source evidence and sidecar metadata before recording findings here.",
            "Attachment import/reference alone cannot approve purchase, commit, roadmap status, plans, archive, staging, or lifecycle decisions.",
        ]
    )


__all__ = [
    "DISCOVERY_PACKET_DEFAULT_STATUS",
    "DISCOVERY_PACKET_NON_AUTHORITY_NOTE",
    "DISCOVERY_PACKET_READY_STATUS",
    "DiscoveryPacketRequest",
    "DiscoveryPacketTarget",
    "ResearchImportRequest",
    "ResearchImportTarget",
    "discovery_packet_apply_findings",
    "discovery_packet_dry_run_findings",
    "make_discovery_packet_request",
    "make_research_import_request",
    "research_import_apply_findings",
    "research_import_dry_run_findings",
]
