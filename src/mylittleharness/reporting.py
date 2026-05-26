from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .models import Finding
from .routes import classify_memory_route, route_protocol_for_id


def emit_text(text: str, stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    payload = f"{text}\n"
    try:
        target.write(payload)
        target.flush()
    except UnicodeEncodeError:
        encoding = getattr(target, "encoding", None) or "ascii"
        fallback, fallback_encoding = _encoding_safe_payload(payload, encoding)
        buffer = getattr(target, "buffer", None)
        if buffer is not None:
            buffer.write(fallback)
            buffer.flush()
            return
        target.write(fallback.decode(fallback_encoding))
        target.flush()


def _encoding_safe_payload(text: str, encoding: str) -> tuple[bytes, str]:
    try:
        return text.encode(encoding, errors="backslashreplace"), encoding
    except LookupError:
        return text.encode("ascii", errors="backslashreplace"), "ascii"


@dataclass(frozen=True)
class RouteWriteEvidence:
    rel_path: str
    before_text: str | None
    after_text: str | None


@dataclass(frozen=True)
class WorkResultCapsule:
    outcome: str
    work_kind: str
    what_done: str
    ceremony: str = ""
    next_safe_command: str = ""
    changed: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    improved: str = ""
    checked: str = ""
    remains: tuple[str, ...] = ()


@dataclass(frozen=True)
class NextSafeRoute:
    command: str
    source_code: str
    severity: str
    source: str | None
    apply_after: str
    authority_boundary: str
    docs_decision: str


READ_ONLY_REPORT_COMMANDS = {
    "adapter",
    "audit-links",
    "bootstrap",
    "check",
    "claim",
    "closeout",
    "context-budget",
    "doctor",
    "evidence",
    "intelligence",
    "manifest",
    "preflight",
    "reconcile",
    "review-token",
    "semantic",
    "snapshot",
    "status",
    "suggest",
    "tasks",
    "validate",
}
MUTATING_REPORT_COMMANDS = {
    "attach",
    "detach",
    "incubate",
    "init",
    "intake",
    "memory-hygiene",
    "meta-feedback",
    "plan",
    "plan-cancel",
    "projection",
    "research-compare",
    "research-distill",
    "research-import",
    "repair",
    "roadmap",
    "transition",
    "writeback",
}
CHANGE_CODE_MARKERS = (
    "applied",
    "archived",
    "changed",
    "compacted",
    "copied",
    "created",
    "deleted",
    "moved",
    "removed",
    "retarget",
    "synchronized",
    "updated",
    "written",
)
ADD_CODE_MARKERS = ("created", "written", "wrote")
REMOVE_CODE_MARKERS = ("archived", "deleted", "removed")
NOOP_CODE_MARKERS = ("noop", "no-op", "unchanged")
MESSAGE_OPERATION_WORDS = {
    "applied": ("applied", "apply"),
    "archived": ("archived", "archive"),
    "changed": ("changed", "change"),
    "compacted": ("compacted", "compact"),
    "copied": ("copied", "copy"),
    "created": ("created", "create"),
    "deleted": ("deleted", "delete"),
    "moved": ("moved", "move"),
    "removed": ("removed", "remove"),
    "retarget": ("retarget", "retargeted"),
    "synchronized": ("synchronized", "synchronize"),
    "updated": ("updated", "update"),
    "written": ("written", "write"),
    "wrote": ("wrote", "write"),
}


def route_write_findings(code: str, writes: tuple[RouteWriteEvidence, ...], apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings: list[Finding] = []
    for write in writes:
        if write.before_text == write.after_text:
            continue
        operation = _route_write_operation(write, apply)
        findings.append(
            Finding(
                "info",
                code,
                (
                    f"{prefix}{operation} route {write.rel_path}; "
                    f"before_hash={_route_text_hash(write.before_text)}; after_hash={_route_text_hash(write.after_text)}; "
                    f"before_bytes={_route_text_size(write.before_text)}; after_bytes={_route_text_size(write.after_text)}; "
                    "source-bound write evidence is independent of Git tracking"
                ),
                write.rel_path,
            )
        )
    return findings


def _route_write_operation(write: RouteWriteEvidence, apply: bool) -> str:
    if write.before_text is None and write.after_text is not None:
        return "created" if apply else "create"
    if write.before_text is not None and write.after_text is None:
        return "deleted" if apply else "delete"
    return "wrote" if apply else "write"


def _route_text_hash(text: str | None) -> str:
    if text is None:
        return "missing"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _route_text_size(text: str | None) -> str:
    if text is None:
        return "missing"
    return str(len(text.encode("utf-8")))


def render_report(command: str, root: Path, result: str, sources: list[str], findings: list[Finding], suggestions: list[str]) -> str:
    lines: list[str] = [f"MyLittleHarness {command}", ""]
    lines.extend(["Root", f"- {root}", ""])
    lines.extend(["Result", f"- status: {result}", ""])
    lines.extend(_render_work_result_section(command, result, findings, suggestions))
    lines.append("Sources")
    if sources:
        lines.extend(f"- {source}" for source in sources)
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Findings")
    if findings:
        lines.extend(f"- {finding.render()}" for finding in findings)
    else:
        lines.append("- [INFO] none: no findings")
    lines.append("")
    lines.append("Suggestions")
    if suggestions:
        lines.extend(f"- {suggestion}" for suggestion in suggestions)
    else:
        lines.append("- No suggestions.")
    return "\n".join(lines)


def render_intelligence_report(
    root: Path,
    result: str,
    sources: list[str],
    sections: list[tuple[str, list[Finding]]],
    suggestions: list[str],
    compact_sources: bool = False,
) -> str:
    lines: list[str] = ["MyLittleHarness intelligence", ""]
    lines.extend(["Root", f"- {root}", ""])
    lines.extend(["Result", f"- status: {result}", ""])
    flat_findings = [finding for _section_name, findings in sections for finding in findings]
    lines.extend(_render_work_result_section("intelligence", result, flat_findings, suggestions))
    lines.append("Sources")
    if compact_sources and sources:
        lines.append(f"- {len(sources)} inventory sources discovered; rerun without --focus for the full source list")
    elif sources:
        lines.extend(f"- {source}" for source in sources)
    else:
        lines.append("- none")
    lines.append("")
    for section_name, findings in sections:
        lines.append(section_name)
        if findings:
            lines.extend(f"- {finding.render()}" for finding in findings)
        else:
            lines.append("- [INFO] none: no findings")
        lines.append("")
    lines.append("Suggestions")
    if suggestions:
        lines.extend(f"- {suggestion}" for suggestion in suggestions)
    else:
        lines.append("- No suggestions.")
    return "\n".join(lines)


def render_sectioned_report(
    command: str,
    root: Path,
    result: str,
    sources: list[str],
    sections: list[tuple[str, list[Finding]]],
    suggestions: list[str],
) -> str:
    lines: list[str] = [f"MyLittleHarness {command}", ""]
    lines.extend(["Root", f"- {root}", ""])
    lines.extend(["Result", f"- status: {result}", ""])
    flat_findings = [finding for _section_name, findings in sections for finding in findings]
    lines.extend(_render_work_result_section(command, result, flat_findings, suggestions))
    lines.append("Sources")
    if sources:
        lines.extend(f"- {source}" for source in sources)
    else:
        lines.append("- none")
    lines.append("")
    for section_name, findings in sections:
        lines.append(section_name)
        if findings:
            lines.extend(f"- {finding.render()}" for finding in findings)
        else:
            lines.append("- [INFO] none: no findings")
        lines.append("")
    lines.append("Suggestions")
    if suggestions:
        lines.extend(f"- {suggestion}" for suggestion in suggestions)
    else:
        lines.append("- No suggestions.")
    return "\n".join(lines)


def render_json_report(
    command: str,
    root: Path,
    result: str,
    sources: list[str],
    findings: list[Finding],
    suggestions: list[str],
    sections: list[tuple[str, list[Finding]]] | None = None,
    route_manifest: tuple[dict[str, object], ...] | None = None,
) -> str:
    payload: dict[str, object] = {
        "schema_version": "mylittleharness.report.v1",
        "command": command,
        "root": str(root),
        "result": {"status": result, "advisory": True},
        "work_result": work_result_to_report_dict(work_result_capsule_for_report(command, result, findings, suggestions)),
        "next_safe_routes": [next_safe_route_to_report_dict(route) for route in next_safe_routes_for_report(findings)],
        "boundary": {
            "reports_advisory": True,
            "repo_visible_files_authoritative": True,
            "apply_rails_required_for_mutation": True,
            "json_output_approves_lifecycle": False,
        },
        "sources": sources,
        "findings": [finding_to_report_dict(finding) for finding in findings],
        "suggestions": suggestions,
    }
    if sections is not None:
        payload["sections"] = [
            {
                "name": section_name,
                "findings": [finding_to_report_dict(finding) for finding in section_findings],
            }
            for section_name, section_findings in sections
        ]
    if route_manifest is not None:
        payload["route_manifest"] = list(route_manifest)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)


def next_safe_route_to_report_dict(route: NextSafeRoute) -> dict[str, object]:
    return {
        "command": route.command,
        "source_code": route.source_code,
        "severity": route.severity,
        "source": route.source,
        "apply_after": route.apply_after,
        "authority_boundary": route.authority_boundary,
        "docs_decision": route.docs_decision,
    }


def work_result_to_report_dict(capsule: WorkResultCapsule) -> dict[str, object]:
    return {
        "outcome": capsule.outcome,
        "work_kind": capsule.work_kind,
        "what_done": _plain_text(capsule.what_done),
        "ceremony": _plain_text(capsule.ceremony),
        "next_safe_command": _plain_text(capsule.next_safe_command),
        "changed": [_plain_text(item) for item in capsule.changed],
        "added": [_plain_text(item) for item in capsule.added],
        "removed": [_plain_text(item) for item in capsule.removed],
        "improved": _plain_text(capsule.improved),
        "checked": _plain_text(capsule.checked),
        "remains": [_plain_text(item) for item in capsule.remains],
    }


def finding_to_report_dict(finding: Finding) -> dict[str, object]:
    data = finding.to_dict()
    route_id = str(data.get("route_id") or _route_id_for_source(finding.source))
    protocol = route_protocol_for_id(route_id)
    human_gate = protocol["human_gate"]
    data.update(
        {
            "route_id": route_id,
            "mutability": protocol["mutability"],
            "requires_human_gate": bool(data.get("requires_human_gate")) or bool(human_gate["required"]),
            "gate_class": data.get("gate_class") or protocol["gate_class"],
            "human_gate_reason": data.get("human_gate_reason") or protocol["human_gate_reason"],
            "allowed_decisions": data.get("allowed_decisions") or protocol["allowed_decisions"],
            "advisory": bool(data.get("advisory", True)),
            "human_gate": {
                "required": bool(data.get("requires_human_gate")) or bool(human_gate["required"]),
                "gate_class": data.get("gate_class") or protocol["gate_class"],
                "reason": data.get("human_gate_reason") or protocol["human_gate_reason"],
                "allowed_decisions": data.get("allowed_decisions") or protocol["allowed_decisions"],
            },
        }
    )
    return data


def _render_work_result_section(command: str, result: str, findings: list[Finding], suggestions: list[str]) -> list[str]:
    capsule = work_result_capsule_for_report(command, result, findings, suggestions)
    return [*render_work_result_capsule(capsule), ""]


def _route_id_for_source(source: str | None) -> str:
    if not source:
        return "unclassified"
    return classify_memory_route(str(source)).route_id


def work_result_capsule_for_report(
    command: str,
    result: str,
    findings: list[Finding],
    suggestions: list[str],
) -> WorkResultCapsule:
    base_command = _base_command(command)
    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warn"]
    apply = _is_apply_report(command, findings)
    scan_read_only = _is_memory_hygiene_scan_report(command, findings) and not apply
    preview = _is_preview_report(command, findings) and not scan_read_only
    refused_preview = preview and _is_refused_preview_report(base_command, findings)
    noop = _is_noop_report(command, findings) and not _has_change_evidence(findings)
    projection_inspect = _is_projection_inspect_report(command)
    read_only = ((base_command in READ_ONLY_REPORT_COMMANDS or projection_inspect) and not apply and not preview) or scan_read_only

    nonblocking_compaction_hygiene = _nonblocking_compaction_hygiene_after_lifecycle_apply(
        base_command,
        apply,
        findings,
        warnings,
    )
    nonblocking_incubation_archive_hygiene = _nonblocking_incubation_archive_hygiene_after_lifecycle_apply(
        base_command,
        apply,
        findings,
        warnings,
    )
    nonblocking_warning_hygiene = (
        nonblocking_compaction_hygiene
        or nonblocking_incubation_archive_hygiene
    )
    blocking_warnings = warnings and not nonblocking_warning_hygiene
    actionable_warnings = [] if nonblocking_warning_hygiene else warnings

    if errors:
        outcome = "refused" if apply or base_command in MUTATING_REPORT_COMMANDS else "blocked"
    elif refused_preview:
        outcome = "refused"
    elif blocking_warnings:
        outcome = "partial"
    elif noop:
        outcome = "no changes needed"
    else:
        outcome = "completed"

    changes: tuple[str, ...]
    additions: tuple[str, ...]
    removals: tuple[str, ...]
    if scan_read_only:
        changes = (
            "No repository files were changed; scan findings are advisory and any mutation requires a separate explicit source dry-run/apply path.",
        )
        additions = ()
        removals = ()
    elif refused_preview:
        changes = (
            "No repository files were changed; the dry-run refused before previewing a reliable apply target.",
        )
        additions = ()
        removals = ()
    elif noop and preview:
        changes = (
            "No repository files were changed; the preview found no apply target for the current posture.",
        )
        additions = ()
        removals = ()
    elif read_only:
        changes = (
            "No repository files were changed; this read-only report is advisory and any mutation requires a separate explicit route.",
        )
        additions = ()
        removals = ()
    elif preview:
        changes = ("No repository files were changed; this report is advisory until an explicit apply path writes files.",)
        additions = ()
        removals = ()
    elif noop:
        changes = ("MLH found the requested posture already matched the repository state.",)
        additions = ()
        removals = ()
    else:
        changes = _finding_messages(findings, CHANGE_CODE_MARKERS)
        additions = _finding_messages(findings, ADD_CODE_MARKERS)
        removals = _finding_messages(findings, REMOVE_CODE_MARKERS)
        if not changes:
            changes = ("No file-level changes were reported by this command.",)

    return WorkResultCapsule(
        outcome=outcome,
        work_kind="verification" if projection_inspect else _work_kind_for_command(base_command),
        what_done=_what_done(command, suggestions),
        ceremony=_ceremony_budget_for_report(base_command, preview, apply, read_only, errors, actionable_warnings, scan_read_only, noop, refused_preview),
        next_safe_command=_next_safe_command_for_report(base_command, preview, apply, read_only, findings, errors, actionable_warnings, scan_read_only, noop, refused_preview),
        changed=changes,
        added=additions,
        removed=removals,
        improved=_improvement_for_report(base_command, preview or read_only, bool(changes and not preview and not read_only)),
        checked=_checked_summary(result, findings),
        remains=_remaining_items(
            base_command,
            preview,
            apply,
            read_only,
            findings,
            warnings,
            errors,
            suggestions,
            nonblocking_compaction_hygiene,
            nonblocking_incubation_archive_hygiene,
            scan_read_only,
            noop,
            refused_preview,
        ),
    )


def work_result_capsule_from_closeout_values(values: dict[str, str]) -> WorkResultCapsule | None:
    if not any(_plain_text(values.get(field, "")) for field in values):
        return None
    docs_decision = _plain_text(values.get("docs_decision", ""))
    verification = _plain_text(values.get("verification", ""))
    required_missing = [
        field
        for field in ("docs_decision", "state_writeback", "verification", "commit_decision")
        if not _plain_text(values.get(field, ""))
    ]
    outcome = "partial" if docs_decision == "uncertain" or required_missing else "completed"
    changed: list[str] = []
    if state_writeback := _plain_text(values.get("state_writeback", "")):
        changed.append(state_writeback)
    if docs_decision:
        changed.append(f"Docs decision recorded as {docs_decision}.")
    remains: list[str] = []
    if risk := _plain_text(values.get("residual_risk", "")):
        remains.append(risk)
    if carry := _plain_text(values.get("carry_forward", "")):
        remains.append(carry)
    if commit := _plain_text(values.get("commit_decision", "")):
        remains.append(commit)
    if docs_decision == "uncertain":
        remains.append("Docs impact remains uncertain, so closeout wording must stay provisional.")
    if required_missing:
        remains.append(f"Missing closeout field(s): {', '.join(required_missing)}.")
    if not remains:
        remains.append("No required follow-up was recorded in the closeout facts.")

    return WorkResultCapsule(
        outcome=outcome,
        work_kind="lifecycle",
        what_done=_plain_text(values.get("task_scope", "")) or "Recorded MLH closeout and lifecycle handoff facts.",
        ceremony="cost=closeout assembly; guarantee=repo-visible facts only after explicit writeback apply",
        next_safe_command="run `mylittleharness --root <root> check` before archive, commit, or next-plan decisions",
        changed=tuple(changed) or ("Closeout facts were recorded for the active work.",),
        improved="The next operator can recover the task result from repo-visible closeout facts instead of reconstructing it from a transcript.",
        checked=verification or "Verification was not recorded in the closeout facts.",
        remains=tuple(remains),
    )


def render_work_result_capsule(capsule: WorkResultCapsule) -> list[str]:
    lines = ["Work Result", f"- Result: {capsule.outcome}"]
    if capsule.what_done:
        lines.append(f"- What was done: {_plain_text(capsule.what_done)}")
    if capsule.ceremony:
        lines.append(f"- Ceremony: {_plain_text(capsule.ceremony)}")
    if capsule.next_safe_command:
        lines.append(f"- Next safe command: {_plain_text(capsule.next_safe_command)}")
    if capsule.changed:
        lines.append(f"- What changed: {_joined_items(capsule.changed)}")
    if capsule.added:
        lines.append(f"- What was added: {_joined_items(capsule.added)}")
    if capsule.removed:
        lines.append(f"- What was removed: {_joined_items(capsule.removed)}")
    if capsule.improved:
        lines.append(f"- What became better: {_plain_text(capsule.improved)}")
    if capsule.checked:
        lines.append(f"- How it was checked: {_plain_text(capsule.checked)}")
    if capsule.remains:
        lines.append(f"- What remains: {_joined_items(capsule.remains)}")
    return lines


def render_work_result_capsule_line(capsule: WorkResultCapsule) -> str:
    parts = [f"Result: {capsule.outcome}"]
    if capsule.what_done:
        parts.append(f"What was done: {_plain_text(capsule.what_done)}")
    if capsule.ceremony:
        parts.append(f"Ceremony: {_plain_text(capsule.ceremony)}")
    if capsule.next_safe_command:
        parts.append(f"Next safe command: {_plain_text(capsule.next_safe_command)}")
    if capsule.changed:
        parts.append(f"What changed: {_joined_items(capsule.changed, limit=2)}")
    if capsule.added:
        parts.append(f"What was added: {_joined_items(capsule.added, limit=2)}")
    if capsule.removed:
        parts.append(f"What was removed: {_joined_items(capsule.removed, limit=2)}")
    if capsule.improved:
        parts.append(f"What became better: {_plain_text(capsule.improved)}")
    if capsule.checked:
        parts.append(f"How it was checked: {_plain_text(capsule.checked)}")
    if capsule.remains:
        parts.append(f"What remains: {_joined_items(capsule.remains, limit=3)}")
    return "; ".join(parts)


def _base_command(command: str) -> str:
    return str(command or "").split(maxsplit=1)[0]


def _is_preview_report(command: str, findings: list[Finding]) -> bool:
    lowered = str(command or "").casefold()
    return "--dry-run" in lowered or any(finding.code.endswith("-dry-run") for finding in findings)


def _is_apply_report(command: str, findings: list[Finding]) -> bool:
    lowered = str(command or "").casefold()
    return "--apply" in lowered or any(finding.code.endswith("-apply") for finding in findings)


def _is_projection_inspect_report(command: str) -> bool:
    lowered = str(command or "").casefold()
    return lowered.startswith("projection --inspect")


def _is_memory_hygiene_scan_report(command: str, findings: list[Finding]) -> bool:
    lowered = str(command or "").casefold()
    if _base_command(command) != "memory-hygiene":
        return False
    return "--scan" in lowered or any(finding.code == "memory-hygiene-scan" for finding in findings)


def _is_noop_report(command: str, findings: list[Finding]) -> bool:
    for finding in findings:
        if _finding_is_noop(finding):
            return True
    base_command = _base_command(command)
    if base_command == "repair":
        return any(
            finding.code == "repair-proposal" and "no missing scaffold" in str(finding.message or "").casefold()
            for finding in findings
        )
    if base_command == "writeback":
        has_compact_only = any(finding.code == "writeback-compact-only" for finding in findings)
        compaction_skipped = any(
            finding.code == "state-auto-compaction-posture" and "skipped" in str(finding.message or "").casefold()
            for finding in findings
        )
        return has_compact_only and compaction_skipped
    return False


def _is_refused_preview_report(command: str, findings: list[Finding]) -> bool:
    if not any("dry-run" in str(finding.code or "") for finding in findings):
        return False
    return any(
        str(finding.code or "").endswith("-refused")
        or "dry-run refused before" in str(finding.message or "")
        for finding in findings
        if finding.severity in {"warn", "error", "info"}
    )


def _finding_is_noop(finding: Finding) -> bool:
    code = str(finding.code or "").casefold()
    message = str(finding.message or "").casefold()
    if any(code.endswith(marker) for marker in NOOP_CODE_MARKERS):
        return True
    return message.startswith("no-op") or "true no-op" in message


def _has_change_evidence(findings: list[Finding]) -> bool:
    for finding in findings:
        if finding.severity == "error" or _finding_is_noop(finding):
            continue
        if _finding_matches_work_markers(finding, CHANGE_CODE_MARKERS):
            return True
    return False


def _ceremony_budget_for_report(
    command: str,
    preview: bool,
    apply: bool,
    read_only: bool,
    errors: list[Finding],
    warnings: list[Finding],
    scan_read_only: bool = False,
    noop: bool = False,
    refused_preview: bool = False,
) -> str:
    if errors:
        if preview:
            return "cost=bounded preview refusal; guarantee=no repository writes before a reviewed matching apply"
        if read_only:
            return "cost=bounded read-only refusal; guarantee=no repository files were changed and repo-visible files remain authoritative"
        if apply:
            return "cost=bounded apply refusal; guarantee=no apply writes after blocking errors"
        return "cost=bounded refusal; guarantee=no apply writes after blocking errors"
    if warnings:
        if refused_preview:
            return "cost=bounded preview refusal; guarantee=no repository writes and no apply path until a clean dry-run is reviewed"
        if scan_read_only:
            return "cost=review scan warnings; guarantee=read-only scan with no repository writes or apply path implied by the scan itself"
        if read_only:
            return "cost=review warning findings; guarantee=read-only advisory output with repo-visible files still authoritative"
        return "cost=review warning findings; guarantee=repo-visible authority is unchanged until an explicit apply succeeds"
    if noop and preview:
        return "cost=low; guarantee=no repository writes and no matching apply is needed for the current posture"
    if scan_read_only:
        return "cost=low; guarantee=read-only scan; explicit source dry-run is required before any memory-hygiene apply"
    if preview:
        return "cost=review pass; guarantee=no repository writes and a bounded apply path"
    if read_only:
        return "cost=low; guarantee=read-only advisory output with repo-visible files still authoritative"
    if apply:
        return "cost=explicit apply; guarantee=bounded route writes only, with VCS and future lifecycle decisions still manual"
    if command in MUTATING_REPORT_COMMANDS:
        return "cost=explicit command; guarantee=bounded command-owned writes only"
    return "cost=low; guarantee=advisory terminal output"


def _next_safe_command_for_report(
    command: str,
    preview: bool,
    apply: bool,
    read_only: bool,
    findings: list[Finding],
    errors: list[Finding],
    warnings: list[Finding],
    scan_read_only: bool = False,
    noop: bool = False,
    refused_preview: bool = False,
) -> str:
    first_actionable_route = _first_next_safe_route(findings, severities={"warn", "error"})
    if errors:
        if read_only and first_actionable_route:
            return f"review the blocking finding, then run its reported next_safe_command: `{first_actionable_route.command}`"
        if preview:
            return "resolve the error findings, then rerun the dry-run before any apply"
        if read_only:
            return "resolve the error findings, then rerun the read-only command or run `mylittleharness --root <root> suggest --intent \"<operator-action>\"` if the route is unclear"
        if apply:
            return "resolve the error findings, rerun the matching dry-run, and apply only after review"
        return "resolve the error findings, then rerun the command after review"
    if warnings:
        if refused_preview:
            return "resolve the refusal findings, then rerun the dry-run before any apply"
        if read_only and command == "projection":
            return "rebuild generated cache only with `mylittleharness --root <root> projection --rebuild --target all` after reviewing stale or missing cache findings"
        if read_only and first_actionable_route:
            return f"run the first reported next_safe_command after review: `{first_actionable_route.command}`"
        if scan_read_only:
            return "review scan warnings; choose an explicit cleanup dry-run only when a finding reports one"
        return "review warnings; if the route is unclear, run `mylittleharness --root <root> suggest --intent \"<operator-action>\"`"
    if noop:
        if preview and command == "repair":
            return "no repair apply is needed for the reported classes; rerun check or a narrower repair dry-run after new diagnostics"
        if preview and command == "writeback":
            return "no compact-only apply is needed while project-state stays below the compaction threshold"
        return "no apply is needed for the reported current posture"
    if scan_read_only:
        if any(finding.code == "incubation-cleanup-batch-preview" for finding in findings):
            token = _memory_hygiene_batch_token_from_findings(findings)
            token_part = f" --proposal-token {token}" if token else " --proposal-token <mhb-token>"
            return f"review reported candidate ids, source hashes, archive targets, and link repairs, then run `memory-hygiene --apply --scan{token_part}` while the proposal is current"
        return "choose an explicit `memory-hygiene --dry-run --source ...` only if the scan reports a cleanup candidate"
    if preview:
        if command == "transition":
            token = _review_token_from_findings(findings)
            token_part = f" --review-token {token}" if token else " --review-token <token>"
            return f"rerun the matching `transition --apply{token_part}` with the same reviewed flags"
        return "rerun the same reviewed command with `--apply` after confirming the preview"
    if read_only and command == "suggest":
        return "choose the matching reported first_safe_command; run an apply command only after reviewing its matching dry-run"
    if read_only and command == "projection":
        if any(finding.code in {"projection-artifact-current", "projection-index-current"} for finding in findings):
            return "no projection rebuild is needed for the reported current cache posture"
        return "rebuild generated cache only with `mylittleharness --root <root> projection --rebuild --target all` after reviewing stale or missing cache findings"
    if read_only and command in {"closeout", "evidence"}:
        return "record chosen closeout facts with `mylittleharness --root <root> writeback --dry-run ...`"
    if read_only:
        return "choose the smallest matching dry-run, or run `mylittleharness --root <root> suggest --intent \"<operator-action>\"`"
    if apply or command in MUTATING_REPORT_COMMANDS:
        return "run `mylittleharness --root <root> check` before closeout, archive, commit, or next-plan decisions"
    return "run `mylittleharness --root <root> check` before relying on the result"


def next_safe_routes_for_report(findings: list[Finding]) -> tuple[NextSafeRoute, ...]:
    routes: list[NextSafeRoute] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        for command in _next_safe_commands_from_message(finding.message):
            key = (finding.code, command)
            if key in seen:
                continue
            seen.add(key)
            routes.append(
                NextSafeRoute(
                    command=command,
                    source_code=finding.code,
                    severity=finding.severity,
                    source=finding.source,
                    apply_after=_apply_after_command(command),
                    authority_boundary=(
                        "advisory route candidate only; review the reported finding and matching dry-run before any apply, "
                        "and do not treat it as closeout, archive, roadmap, staging, commit, rollback, or lifecycle approval"
                    ),
                    docs_decision="not affected",
                )
            )
    return tuple(routes)


def _first_next_safe_route(findings: list[Finding], severities: set[str] | None = None) -> NextSafeRoute | None:
    for route in next_safe_routes_for_report(findings):
        if severities is None or route.severity in severities:
            return route
    return None


_NEXT_SAFE_COMMAND_RE = re.compile(r"\bnext_safe_command=([^;\n]+)")
_NEXT_SAFE_COMMAND_PROSE_RE = re.compile(r"\bnext safe command:\s*(?:[^`\n]*?)`([^`\n]+)`", re.IGNORECASE)


def _next_safe_commands_from_message(message: str) -> tuple[str, ...]:
    commands: list[str] = []
    for match in _NEXT_SAFE_COMMAND_RE.finditer(str(message or "")):
        command = _plain_text(match.group(1)).strip()
        if command:
            commands.append(command)
    for match in _NEXT_SAFE_COMMAND_PROSE_RE.finditer(str(message or "")):
        command = _plain_text(match.group(1)).strip()
        if command:
            commands.append(command)
    return tuple(commands)


def _apply_after_command(command: str) -> str:
    if "--dry-run" in command:
        apply_command = command.replace("--dry-run", "--apply", 1)
        if "writeback --apply --compact-only" in apply_command and "--source-hash" not in apply_command:
            apply_command += " --source-hash <sha256-from-dry-run>"
        return apply_command
    return ""


def _review_token_from_findings(findings: list[Finding]) -> str:
    for finding in findings:
        if finding.code.endswith("review-token"):
            marker = "review token:"
            message = str(finding.message or "")
            index = message.casefold().find(marker)
            if index >= 0:
                return message[index + len(marker) :].strip().split()[0]
    return ""


def _memory_hygiene_batch_token_from_findings(findings: list[Finding]) -> str:
    for finding in findings:
        if finding.code != "incubation-cleanup-batch-preview":
            continue
        match = re.search(r"batch_review_token=(mhb-[0-9a-f]{16})", finding.message)
        if match:
            return match.group(1)
    return ""


def _nonblocking_compaction_hygiene_after_lifecycle_apply(
    command: str,
    apply: bool,
    findings: list[Finding],
    warnings: list[Finding],
) -> bool:
    if not apply or command not in {"transition", "writeback"} or not warnings:
        return False
    if any(finding.severity == "error" for finding in findings):
        return False
    if any(finding.code == "writeback-compact-only" for finding in findings):
        return False
    if any(
        warning.code != "state-auto-compaction-posture" or "auto-compaction refused" not in warning.message
        for warning in warnings
    ):
        return False
    lifecycle_write_codes = {
        "writeback-active-plan-archived",
        "writeback-state-updated",
        "writeback-lifecycle-updated",
    }
    return any(finding.code in lifecycle_write_codes and finding.severity == "info" for finding in findings)


def _nonblocking_incubation_archive_hygiene_after_lifecycle_apply(
    command: str,
    apply: bool,
    findings: list[Finding],
    warnings: list[Finding],
) -> bool:
    if not apply or command not in {"transition", "writeback"} or not warnings:
        return False
    if any(finding.severity == "error" for finding in findings):
        return False
    if any(warning.code != "writeback-incubation-archive-blocked" for warning in warnings):
        return False
    lifecycle_write_codes = {
        "writeback-active-plan-archived",
        "writeback-state-updated",
        "writeback-lifecycle-updated",
    }
    return any(finding.code in lifecycle_write_codes and finding.severity == "info" for finding in findings)


def _work_kind_for_command(command: str) -> str:
    if command in {
        "adapter",
        "audit-links",
        "bootstrap",
        "check",
        "claim",
        "context-budget",
        "doctor",
        "evidence",
        "intelligence",
        "manifest",
        "preflight",
        "reconcile",
        "review-token",
        "semantic",
        "snapshot",
        "status",
        "suggest",
        "tasks",
        "validate",
    }:
        return "verification"
    if command in {"approval-packet", "handoff"}:
        return "coordination"
    if command in {"plan", "roadmap", "incubate", "intake", "meta-feedback"}:
        return "planning"
    if command in {"writeback", "transition", "closeout"}:
        return "lifecycle"
    if command in {"repair", "memory-hygiene", "detach", "projection", "init", "attach"}:
        return "hygiene"
    return "task"


def _what_done(command: str, suggestions: list[str]) -> str:
    if suggestions:
        return _plain_text(suggestions[0])
    return f"Ran `{command}` and rendered the result."


def _finding_messages(findings: list[Finding], markers: tuple[str, ...], limit: int = 3) -> tuple[str, ...]:
    messages: list[str] = []
    seen: set[str] = set()
    for finding in findings:
        if finding.severity == "error":
            continue
        if not _finding_matches_work_markers(finding, markers):
            continue
        message = _plain_text(finding.message, limit=180)
        if message and message not in seen:
            messages.append(message)
            seen.add(message)
        if len(messages) >= limit:
            break
    return tuple(messages)


def _finding_matches_work_markers(finding: Finding, markers: tuple[str, ...]) -> bool:
    code_tokens = str(finding.code or "").casefold().replace("_", "-").split("-")
    if any(marker in code_tokens for marker in markers):
        return True
    message = " ".join(str(finding.message or "").casefold().strip().split())
    if message.startswith("would "):
        message = message[len("would ") :]
    first_word = message.split(maxsplit=1)[0].rstrip(":;,.") if message else ""
    return any(first_word in MESSAGE_OPERATION_WORDS.get(marker, ()) for marker in markers)


def _improvement_for_report(command: str, read_only_or_preview: bool, changed: bool) -> str:
    if read_only_or_preview:
        return "The command makes the current repository posture easier to judge before any mutating action."
    if command in {"writeback", "transition", "closeout"}:
        return "The next operator can resume from explicit lifecycle facts instead of chat memory."
    if command in {"plan", "roadmap", "incubate", "intake", "meta-feedback"}:
        return "The next planning step is recoverable from repo-visible routes."
    if changed:
        return "The report states the practical outcome before the detailed diagnostic log."
    return "The command clarified the task result without adding hidden state."


def _checked_summary(result: str, findings: list[Finding]) -> str:
    errors = sum(1 for finding in findings if finding.severity == "error")
    warnings = sum(1 for finding in findings if finding.severity == "warn")
    return f"MLH rendered report status `{result}` from {len(findings)} finding(s): {errors} error(s), {warnings} warning(s)."


def _remaining_items(
    command: str,
    preview: bool,
    apply: bool,
    read_only: bool,
    findings: list[Finding],
    warnings: list[Finding],
    errors: list[Finding],
    suggestions: list[str],
    nonblocking_compaction_hygiene: bool = False,
    nonblocking_incubation_archive_hygiene: bool = False,
    scan_read_only: bool = False,
    noop: bool = False,
    refused_preview: bool = False,
) -> tuple[str, ...]:
    if errors:
        if suggestions:
            return tuple(_plain_text(item) for item in suggestions[:2])
        if preview:
            return ("Resolve the error findings, then rerun the dry-run before any apply.",)
        if read_only:
            return ("Resolve the error findings, then rerun the read-only command; no apply is implied.",)
        if apply:
            return ("Resolve the error findings, rerun the matching dry-run, and apply only after review.",)
        return ("Resolve the error findings, then rerun the command after review.",)
    if warnings:
        if nonblocking_compaction_hygiene:
            return (
                "Operating-memory compaction remains a separate hygiene follow-up; the lifecycle writes above already landed. Restore missing state section boundaries or contract guidance, then preview/apply `writeback --compact-only`; this does not approve manual trimming, staging, commit, archive, rollback, or next-plan opening.",
            )
        if nonblocking_incubation_archive_hygiene:
            return (
                "Source-incubation auto-archive remains a separate operating-memory hygiene follow-up; the lifecycle writes above already landed. Keep shared or mixed incubation notes active until coverage is explicit, then use a bounded memory-hygiene or writeback route after review; this does not approve manual archive cleanup, staging, commit, rollback, or additional next-plan movement.",
            )
        if refused_preview:
            if suggestions:
                return tuple(_plain_text(item) for item in suggestions[:2])
            return ("Resolve the refusal findings, then rerun the dry-run; no apply is available from this report.",)
        if read_only:
            if command == "intelligence" and suggestions:
                return tuple(_plain_text(item) for item in suggestions[:2])
            return (
                "Review warning findings before relying on this read-only report; choose a separate explicit route before any mutation.",
            )
        if suggestions:
            return tuple(_plain_text(item) for item in suggestions[:2])
        return ("Review warning findings before relying on this result.",)
    if noop:
        if preview and command == "repair":
            return ("No repairable target was reported; do not run repair apply unless a later check reports a repairable diagnostic.",)
        if preview and command == "writeback":
            return ("Whole-state compaction was skipped for the current state size; no compact-only apply is needed now.",)
        return ("No apply follow-up is needed for the reported current posture.",)
    if scan_read_only:
        if any(finding.code == "incubation-cleanup-batch-preview" for finding in findings):
            return (
                "Cleanup candidates remain advisory until the reviewed token-bound scan apply succeeds; stale source or link hashes require a fresh dry-run scan.",
            )
        return (
            "Scan findings are advisory; no memory-hygiene apply is available without an explicit source/archive dry-run chosen from reported candidates.",
        )
    if preview:
        return ("Review the preview target and boundary before running the matching explicit apply command.",)
    if read_only and command == "suggest":
        return (
            "Suggested command routes remain advisory; choose one only when it matches operator intent and root posture, and no lifecycle, archive, staging, commit, push, or apply action is approved by this report.",
        )
    if read_only:
        return ("No required follow-up was reported.",)
    if apply or command in MUTATING_REPORT_COMMANDS:
        return (_remaining_manual_decisions(command, findings),)
    return ("No required follow-up was reported.",)


def _remaining_manual_decisions(command: str, findings: list[Finding]) -> str:
    archived_active_plan = any(finding.code == "writeback-active-plan-archived" for finding in findings)
    opened_next_plan = command == "transition" and any(
        finding.code == "transition-step" and "opening next active plan" in finding.message
        for finding in findings
    )
    if command == "transition":
        if archived_active_plan and opened_next_plan:
            return "Stage, commit, push, and any future lifecycle decisions remain manual unless explicitly requested."
        if archived_active_plan:
            return "Stage, commit, push, and next-plan decisions remain manual unless explicitly requested."
        if opened_next_plan:
            return "Stage, commit, push, archive, and any future lifecycle decisions remain manual unless explicitly requested."
    if command == "writeback" and archived_active_plan:
        return "Stage, commit, push, and next-plan decisions remain manual unless explicitly requested."
    return "Stage, commit, push, archive, and next-plan decisions remain manual unless explicitly requested."


def _joined_items(items: tuple[str, ...] | list[str], limit: int = 3) -> str:
    normalized = [_plain_text(item) for item in items if _plain_text(item)]
    if not normalized:
        return ""
    selected = normalized[:limit]
    if len(normalized) > limit:
        selected.append(f"+{len(normalized) - limit} more")
    return "; ".join(selected)


def _plain_text(value: object, limit: int = 260) -> str:
    compact = " ".join(str(value or "").strip().split())
    if len(compact) > limit:
        return compact[: limit - 3].rstrip() + "..."
    return compact
