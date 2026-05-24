from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .atomic_files import AtomicFileWrite, apply_file_transaction
from .evidence import lifecycle_mutation_provenance_findings
from .inventory import Inventory
from .models import Finding
from .reporting import RouteWriteEvidence, route_write_findings


RESEARCH_DIR_REL = "project/research"
RESEARCH_IMPORT_SOURCE = "research-import cli"
NON_AUTHORITY_NOTE = (
    "imported research is durable provenance and synthesis input; it cannot approve lifecycle, specs, plans, archive, "
    "roadmap status, staging, commit, or next-plan opening."
)
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
    imported_text_hash: str


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
    )


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

    rendered, render_findings = _render_research_import(inventory.root, target)
    write_evidence = _route_write(inventory.root, target.rel_path, rendered)
    tmp_path = target.path.with_name(f".{target.path.name}.research-import.tmp")
    backup_path = target.path.with_name(f".{target.path.name}.research-import.backup")
    try:
        cleanup_warnings = apply_file_transaction((AtomicFileWrite(target.path, tmp_path, rendered, backup_path),))
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
    return ResearchImportTarget(
        title=request.title,
        text=request.text,
        text_source=request.text_source,
        rel_path=rel_path,
        path=inventory.root / rel_path,
        topic=request.topic or request.title,
        source_label=request.source_label,
        related_prompt=request.related_prompt,
        input_path=request.input_path,
        imported_text_hash=hashlib.sha256(request.text.encode("utf-8")).hexdigest(),
    )


def _research_import_preflight_errors(
    inventory: Inventory,
    request: ResearchImportRequest,
    target: ResearchImportTarget | None,
) -> list[Finding]:
    errors: list[Finding] = []
    if not request.title:
        errors.append(Finding("error", "research-import-refused", "--title is required and cannot be empty or whitespace-only"))
    elif target is None:
        errors.append(Finding("error", "research-import-refused", "--title does not produce a safe non-empty ASCII target slug"))
    if not request.text:
        errors.append(Finding("error", "research-import-refused", "research text is required and cannot be empty or whitespace-only"))
    if request.target and _root_relative_path_conflict(request.target):
        errors.append(Finding("error", "research-import-refused", f"target {_root_relative_path_conflict(request.target)}", request.target))
    if request.related_prompt and _root_relative_path_conflict(request.related_prompt):
        errors.append(Finding("error", "research-import-refused", f"related prompt {_root_relative_path_conflict(request.related_prompt)}", request.related_prompt))

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
            else:
                errors.append(Finding("error", "research-import-refused", "target research artifact already exists; choose a new --target", target.rel_path))
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


def _source_hash_entries(root: Path, target: ResearchImportTarget) -> tuple[str, ...]:
    entries = [f"imported_text sha256={target.imported_text_hash}"]
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


def _target_findings(target: ResearchImportTarget, apply: bool) -> list[Finding]:
    verb = "target research artifact" if apply else "would target research artifact"
    return [
        Finding("info", "research-import-title", f"normalized title: {target.title}", target.rel_path),
        Finding("info", "research-import-target", f"{verb}: {target.rel_path}", target.rel_path),
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


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "research-import-root-posture", f"root kind: {inventory.root_kind}")


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


def _route_write(root: Path, rel_path: str, after_text: str) -> RouteWriteEvidence:
    target = root / rel_path
    before_text = target.read_text(encoding="utf-8") if target.is_file() else None
    return RouteWriteEvidence(rel_path, before_text, after_text)


def _default_research_rel(title: str) -> str:
    slug = _safe_slug(title)
    if not slug or slug in _RESERVED_SLUGS:
        return ""
    return f"{RESEARCH_DIR_REL}/{date.today().isoformat()}-{slug}.md"


def _safe_slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


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
    "ResearchImportRequest",
    "ResearchImportTarget",
    "make_research_import_request",
    "research_import_apply_findings",
    "research_import_dry_run_findings",
]
