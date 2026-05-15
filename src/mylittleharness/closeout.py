from __future__ import annotations

import re
from collections.abc import Iterable

from .command_discovery import rails_not_cognition_boundary_finding
from .inventory import Inventory, Surface
from .models import Finding
from .evidence import durable_proof_record_findings, git_context_trailer_values
from .evidence_cues import CLOSEOUT_FIELD_NAMES, closeout_field_cues, cue_findings, find_cues
from .projection_artifacts import inspect_projection_artifacts
from .projection_index import inspect_projection_index
from .vcs import VcsPosture, parse_head_commit_trailers, probe_vcs
from .writeback import (
    WritebackFact,
    current_state_writeback_facts,
    satisfied_post_archive_carry_forward_finding,
    state_writeback_facts,
    state_writeback_identity_matches_current_plan,
)


RESIDUAL_RISK_PATTERNS = (r"\bresidual risks?\b", r"\brisk remains\b", r"\bremaining risk\b")
SKIP_RATIONALE_PATTERNS = (r"skip rationale", r"explicit skip", r"verified skip", r"explicitly skipped", r"skipped because")
CARRY_FORWARD_PATTERNS = (
    r"carry-forward",
    r"deferred",
    r"unresolved",
    r"optional-next",
    r"later-extension",
    r"needs-more-research",
    r"\bopen questions?\b",
)
GIT_EVIDENCE_REQUIRED_TRAILERS = (
    ("worktree_start_state", "MLH-Worktree-Start-State"),
    ("task_scope", "MLH-Task-Scope"),
    ("docs_decision", "MLH-Docs-Decision"),
    ("state_writeback", "MLH-State-Writeback"),
    ("verification", "MLH-Verification"),
    ("commit_decision", "MLH-Commit-Decision"),
)
GIT_EVIDENCE_OPTIONAL_TRAILERS = (
    ("residual_risk", "MLH-Residual-Risk", ("residual risk", "residual risks")),
    ("carry_forward", "MLH-Carry-Forward", ("carry-forward", "carry forward")),
)
GIT_EXISTING_TRAILER_KEYS = frozenset(
    (
        "MLH-Plan",
        "MLH-Phase",
        "MLH-Slice",
        "MLH-Roadmap-Item",
        "MLH-Archived-Plan",
        "MLH-Product-Source-Root",
        *(trailer_name for _field, trailer_name in GIT_EVIDENCE_REQUIRED_TRAILERS),
        *(trailer_name for _field, trailer_name, _labels in GIT_EVIDENCE_OPTIONAL_TRAILERS),
    )
)


def closeout_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    vcs_posture = probe_vcs(inventory.root)
    return [
        ("Summary", _summary_findings(inventory)),
        ("Worktree", _worktree_findings(vcs_posture)),
        ("Closeout Fields", _closeout_field_findings(inventory, vcs_posture)),
        ("Git Evidence", _git_evidence_findings(inventory, vcs_posture)),
        ("Proof Records", durable_proof_record_findings(inventory, "closeout")),
        ("Evidence Cues", _evidence_cue_findings(inventory)),
        ("Quality Gates", _quality_gate_findings(inventory, vcs_posture)),
        ("Projection", _projection_findings(inventory)),
        ("Boundary", _boundary_findings(inventory)),
    ]


def _summary_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "closeout-boundary",
            "terminal-only read-only report; persistent evidence manifest remains deferred; may run target-bound Git rev-parse/status probes plus read-only HEAD trailer parsing but writes no files, report artifacts, caches, databases, hooks, commits, archives, repairs, or lifecycle mutations",
        ),
        Finding("info", "closeout-root-kind", f"root kind: {inventory.root_kind}"),
    ]
    if inventory.root_kind == "product_source_fixture":
        findings.append(
            Finding(
                "info",
                "closeout-non-authority",
                "product source checkout contains compatibility fixtures only; closeout findings do not make it an operating project root",
                inventory.state.rel_path if inventory.state else None,
            )
        )
    findings.extend(_active_plan_findings(inventory))
    findings.extend(_policy_findings(inventory))
    return findings


def _active_plan_findings(inventory: Inventory) -> list[Finding]:
    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    plan_status = str(state_data.get("plan_status") or "")
    configured_plan = str(state_data.get("active_plan") or inventory.manifest.get("memory", {}).get("plan_file", "project/implementation-plan.md"))
    active_plan = inventory.active_plan_surface if inventory.active_plan_surface and inventory.active_plan_surface.exists else None
    if active_plan:
        return [Finding("info", "closeout-active-plan", f"candidate: active plan present: {active_plan.rel_path}", active_plan.rel_path)]
    if plan_status == "active":
        return [Finding("warn", "closeout-active-plan", f"missing: plan_status is active but active plan is not readable: {configured_plan}", state.rel_path if state else configured_plan)]
    return [Finding("info", "closeout-active-plan", "no active plan is required by current state", state.rel_path if state else None)]


def _policy_findings(inventory: Inventory) -> list[Finding]:
    policy = inventory.manifest.get("policy", {}) if isinstance(inventory.manifest, dict) else {}
    closeout_commit = policy.get("closeout_commit")
    if closeout_commit:
        return [
            Finding(
                "info",
                "closeout-policy",
                f"candidate: manifest closeout_commit policy is {closeout_commit}",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else None,
            )
        ]
    return [
        Finding(
            "info",
            "closeout-policy",
            "manifest closeout_commit policy is not configured; operator closeout policy remains required",
            inventory.manifest_surface.rel_path if inventory.manifest_surface else None,
        )
    ]


def _worktree_findings(posture: VcsPosture) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "closeout-vcs-probe",
            "read-only VCS probe uses target-bound Git discovery and porcelain status only; Git trailer parsing is a separate read-only evidence hint",
        )
    ]
    if posture.top_level:
        findings.append(Finding("info", "closeout-vcs-root", f"Git top-level: {posture.top_level}"))
    if not posture.git_available:
        findings.append(Finding("warn", "closeout-vcs-probe", posture.detail or "git executable unavailable"))
        findings.append(
            Finding(
                "info",
                "closeout-worktree-start-state",
                "operator-required: record worktree_start_state from direct observation because Git posture is unknown",
            )
        )
        findings.append(_task_scope_prompt())
        return findings
    if not posture.is_worktree:
        detail = f": {posture.detail}" if posture.detail else ""
        findings.append(Finding("info", "closeout-worktree-start-state", f"candidate: non-git root{detail}"))
        findings.append(_task_scope_prompt())
        return findings
    if posture.state == "clean":
        findings.append(Finding("info", "closeout-worktree-start-state", "candidate: Git worktree clean"))
    elif posture.state == "dirty":
        findings.append(
            Finding(
                "warn",
                "closeout-worktree-start-state",
                f"candidate: Git worktree dirty; changed files={posture.changed_count}; samples={_changed_samples(posture)}",
            )
        )
    else:
        findings.append(
            Finding(
                "warn",
                "closeout-worktree-start-state",
                f"operator-required: Git worktree posture unknown: {posture.detail or 'git status failed'}",
            )
        )
    findings.append(_task_scope_prompt())
    return findings


def _task_scope_prompt() -> Finding:
    return Finding(
        "info",
        "closeout-task-scope",
        "operator-required: classify task_scope from actual work performed; this helper cannot infer whole-worktree authorization",
    )


def _changed_samples(posture: VcsPosture) -> str:
    if not posture.changed_samples:
        return "none"
    return "; ".join(f"{entry.status} {entry.path}" for entry in posture.changed_samples)


def _closeout_field_findings(inventory: Inventory, posture: VcsPosture) -> list[Finding]:
    findings: list[Finding] = []
    active_plan = inventory.active_plan_surface if inventory.active_plan_surface and inventory.active_plan_surface.exists else None
    findings.extend(_stale_state_writeback_identity_findings(inventory))
    facts = _trusted_state_writeback_facts(inventory)
    if not active_plan and not facts:
        findings.append(Finding("info", "closeout-field-scan", "closeout field scan skipped because no active plan is present"))
    else:
        for field in CLOSEOUT_FIELD_NAMES:
            fact = facts.get(field)
            if fact:
                findings.append(_writeback_fact_finding(f"closeout-{field.replace('_', '-')}", f"{field} candidate", fact))
            elif active_plan:
                findings.extend(_field_findings(active_plan, field))
            else:
                findings.append(Finding("warn", f"closeout-{field.replace('_', '-')}", f"missing: concrete closeout field candidate not found: {field}"))
    findings.extend(_commit_input_findings(inventory, posture))
    return findings


def _field_findings(active_plan: Surface, field: str) -> list[Finding]:
    concrete, broad = closeout_field_cues(active_plan, field)
    code = f"closeout-{field.replace('_', '-')}"
    if concrete:
        return cue_findings(code, f"{field} candidate", concrete, limit=2)
    findings = [Finding("warn", code, f"missing: concrete closeout field candidate not found: {field}", active_plan.rel_path)]
    if broad:
        findings.extend(cue_findings(f"{code}-context", f"{field} context", broad, limit=2))
    return findings


def _writeback_fact_finding(code: str, label: str, fact: WritebackFact) -> Finding:
    return Finding(
        "info",
        code,
        f"candidate: {label}: - {fact.field}: {fact.value}; source={fact.source}:{fact.line}",
        fact.source,
        fact.line,
    )


def _commit_input_findings(inventory: Inventory, posture: VcsPosture) -> list[Finding]:
    policy = inventory.manifest.get("policy", {}) if isinstance(inventory.manifest, dict) else {}
    closeout_commit = str(policy.get("closeout_commit") or "unconfigured")
    if closeout_commit == "manual":
        message = "input: policy=manual; helper cannot auto-commit and operator closeout should record a manual or skipped commit decision"
    elif posture.state == "dirty":
        message = "input: dirty Git posture requires task_scope and policy review before any commit decision"
    elif posture.state == "non-git":
        message = "input: non-git root supports commit_decision=skipped with non-git rationale when applicable"
    elif posture.state == "clean":
        message = f"input: clean Git posture plus policy={closeout_commit}; operator still decides from task scope and closeout gates"
    else:
        message = f"input: Git posture unknown plus policy={closeout_commit}; operator must record explicit skip or manual rationale"
    return [Finding("info", "closeout-commit-input", message, inventory.manifest_surface.rel_path if inventory.manifest_surface else None)]


def _git_evidence_findings(inventory: Inventory, posture: VcsPosture) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "closeout-git-evidence-boundary",
            "read-only Git trailer suggestions assemble repo-visible closeout facts only; report does not stage, commit, amend, push, mutate Git config, install hooks, write evidence manifests, or decide lifecycle state",
        )
    ]
    if not posture.git_available:
        findings.append(
            Finding(
                "warn",
                "closeout-git-evidence-fallback",
                "Git posture is unknown; use Markdown closeout fields or an operator summary fallback; no Git trailer suggestions emitted",
            )
        )
        return findings
    if not posture.is_worktree or posture.state == "non-git":
        findings.append(
            Finding(
                "info",
                "closeout-git-evidence-fallback",
                "non-git root; use Markdown closeout fields or an operator summary fallback; no Git trailer suggestions emitted",
            )
        )
        return findings
    if posture.state == "unknown":
        findings.append(
            Finding(
                "warn",
                "closeout-git-evidence-fallback",
                "Git worktree posture is unknown; record explicit closeout rationale manually; no Git trailer suggestions emitted",
            )
        )
        return findings

    findings.extend(_existing_git_trailer_findings(inventory))

    active_plan = inventory.active_plan_surface if inventory.active_plan_surface and inventory.active_plan_surface.exists else None
    facts = _trusted_state_writeback_facts(inventory)
    if not active_plan and not facts:
        findings.append(
            Finding(
                "info",
                "closeout-git-evidence-skipped",
                "active plan is absent; no repo-visible closeout field lines are available for Git trailer suggestions",
            )
        )
        return findings

    trailer_source = active_plan.rel_path if active_plan else (inventory.state.rel_path if inventory.state and inventory.state.exists else None)
    values, missing = _required_trailer_values(inventory, active_plan)
    if missing:
        findings.append(
            Finding(
                "warn",
                "closeout-git-evidence-missing",
                f"missing required closeout field lines for Git trailer suggestions: {', '.join(missing)}",
                trailer_source,
            )
        )
        return findings

    posture_note = "dirty worktree; suggestions remain advisory and require explicit task_scope" if posture.state == "dirty" else "clean worktree; suggestions remain advisory"
    findings.append(Finding("info", "closeout-git-evidence-posture", posture_note))
    for trailer_name, value in git_context_trailer_values(inventory, active_plan, facts):
        findings.append(
            Finding(
                "info",
                "closeout-git-evidence-trailer",
                f"suggestion: {trailer_name}: {value}",
                trailer_source,
            )
        )
    for trailer_name, value in values:
        findings.append(
            Finding(
                "info",
                "closeout-git-evidence-trailer",
                f"suggestion: {trailer_name}: {value}",
                trailer_source,
            )
        )

    for trailer_name, value in _optional_trailer_values(inventory, active_plan):
        findings.append(
            Finding(
                "info",
                "closeout-git-evidence-trailer",
                f"suggestion: {trailer_name}: {value}",
                trailer_source,
            )
        )
    return findings


def _existing_git_trailer_findings(inventory: Inventory) -> list[Finding]:
    source = inventory.state.rel_path if inventory.state and inventory.state.exists else None
    result = parse_head_commit_trailers(inventory.root)
    if not result.parsed:
        detail = f": {result.detail}" if result.detail else ""
        return [
            Finding(
                "info",
                "closeout-git-existing-trailer-fallback",
                f"existing HEAD trailer parse unavailable{detail}; current closeout facts remain repo-visible Markdown/writeback authority",
                source,
            )
        ]

    if not result.trailers:
        return [
            Finding(
                "info",
                "closeout-git-existing-trailer-parse",
                "read-only git interpret-trailers parse found no existing HEAD trailers",
                source,
            )
        ]

    recognized = [trailer for trailer in result.trailers if trailer.key in GIT_EXISTING_TRAILER_KEYS]
    findings = [
        Finding(
            "info",
            "closeout-git-existing-trailer-parse",
            "read-only git interpret-trailers parse treats existing HEAD trailers as historical context only; current lifecycle identity and closeout facts remain authoritative",
            source,
        )
    ]
    if not recognized:
        findings.append(
            Finding(
                "info",
                "closeout-git-existing-trailer-parse",
                f"parsed {len(result.trailers)} existing HEAD trailer(s), with no recognized MLH evidence keys",
                source,
            )
        )
        return findings

    for trailer in recognized:
        findings.append(
            Finding(
                "info",
                "closeout-git-existing-trailer",
                f"existing HEAD trailer: {trailer.key}: {trailer.value}",
                source,
            )
        )
    return findings


def _required_trailer_values(inventory: Inventory, active_plan: Surface | None) -> tuple[list[tuple[str, str]], list[str]]:
    values: list[tuple[str, str]] = []
    missing: list[str] = []
    facts = _trusted_state_writeback_facts(inventory)
    for field, trailer_name in GIT_EVIDENCE_REQUIRED_TRAILERS:
        value = _state_fact_value(facts, field)
        if not value and active_plan and field in {"worktree_start_state", "task_scope"}:
            value = _explicit_line_value(active_plan, ("task_scope", "task scope"))
            if field == "worktree_start_state":
                value = _explicit_line_value(active_plan, ("worktree_start_state", "worktree start state"))
        else:
            value = value or (_closeout_field_trailer_value(active_plan, field) if active_plan else "")
        if value:
            values.append((trailer_name, value))
        else:
            missing.append(field)
    return values, missing


def _closeout_field_trailer_value(active_plan: Surface, field: str) -> str:
    concrete, _ = closeout_field_cues(active_plan, field)
    for cue in concrete:
        value = _cue_value(cue.preview, (field, field.replace("_", " ")))
        if value:
            return value
    return ""


def _optional_trailer_values(inventory: Inventory, active_plan: Surface | None) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    facts = _trusted_state_writeback_facts(inventory)
    for _key, trailer_name, labels in GIT_EVIDENCE_OPTIONAL_TRAILERS:
        value = _state_fact_value(facts, _key) or (_explicit_line_value(active_plan, labels) if active_plan else "")
        if value:
            values.append((trailer_name, value))
    return values


def _state_fact_value(facts: dict[str, WritebackFact], field: str) -> str:
    fact = facts.get(field)
    return _normalize_trailer_value(fact.value) if fact else ""


def _explicit_line_value(surface: Surface, labels: tuple[str, ...]) -> str:
    for line in surface.content.splitlines():
        value = _cue_value(line, labels)
        if value:
            return value
    return ""


def _cue_value(line: str, labels: tuple[str, ...]) -> str:
    compact = re.sub(r"\s+", " ", line.strip())
    for label in labels:
        pattern = rf"^[-*]\s*`?{re.escape(label)}`?\s*:\s*(.+)$"
        match = re.search(pattern, compact, re.IGNORECASE)
        if match:
            return _normalize_trailer_value(match.group(1))
    return ""


def _normalize_trailer_value(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).rstrip(".")


def _evidence_cue_findings(inventory: Inventory) -> list[Finding]:
    active_plan = inventory.active_plan_surface if inventory.active_plan_surface and inventory.active_plan_surface.exists else None
    findings: list[Finding] = []
    facts = _trusted_state_writeback_facts(inventory)
    findings.extend(_line_group_findings(active_plan, "closeout-residual-risk", "residual risk", RESIDUAL_RISK_PATTERNS, facts.get("residual_risk")))
    findings.extend(_line_group_findings(active_plan, "closeout-skip-rationale", "skip rationale", SKIP_RATIONALE_PATTERNS))
    carry_forward_fact = facts.get("carry_forward")
    if carry_forward_fact:
        findings.extend(_line_group_findings(active_plan, "closeout-carry-forward", "carry-forward", CARRY_FORWARD_PATTERNS, carry_forward_fact))
    else:
        historical = satisfied_post_archive_carry_forward_finding(inventory, "closeout-carry-forward")
        findings.extend([historical] if historical else _line_group_findings(active_plan, "closeout-carry-forward", "carry-forward", CARRY_FORWARD_PATTERNS))
    return findings


def _line_group_findings(active_plan: Surface | None, code: str, label: str, patterns: Iterable[str], fact: WritebackFact | None = None) -> list[Finding]:
    if fact:
        return [_writeback_fact_finding(code, f"{label} candidate", fact)]
    if not active_plan:
        return [Finding("info", code, f"{label} scan skipped because no active plan is present")]
    cues = find_cues(active_plan, label.replace(" ", "-"), f"{label} candidate", patterns)
    if not cues:
        return [Finding("warn", code, f"missing: {label} candidate not found in active plan", active_plan.rel_path)]
    return cue_findings(code, f"{label} candidate", cues)


def _quality_gate_findings(inventory: Inventory, posture: VcsPosture) -> list[Finding]:
    active_plan = inventory.active_plan_surface if inventory.active_plan_surface and inventory.active_plan_surface.exists else None
    facts = _trusted_state_writeback_facts(inventory)
    findings = [
        Finding(
            "info",
            "closeout-quality-gate",
            "report-only quality gates assemble readiness cues only; persistent evidence manifest remains deferred and no gate state, evidence manifest, archive action, commit action, repair, or lifecycle mutation is written",
        )
    ]
    if not active_plan and not facts:
        findings.append(Finding("info", "closeout-quality-gate", "active-plan quality scan skipped because no active plan is present"))
    else:
        fact_source = active_plan.rel_path if active_plan else (inventory.state.rel_path if inventory.state and inventory.state.exists else None)
        missing = [
            field
            for field in CLOSEOUT_FIELD_NAMES
            if field not in facts and (not active_plan or not closeout_field_cues(active_plan, field)[0])
        ]
        if missing:
            findings.append(
                Finding(
                    "warn",
                    "closeout-quality-gate",
                    f"missing concrete closeout field evidence: {', '.join(missing)}",
                    fact_source,
                )
            )
        else:
            findings.append(
                Finding(
                    "info",
                    "closeout-quality-gate",
                    "concrete closeout field evidence is present; observed verification and operator decisions remain required",
                    fact_source,
                )
            )
    if posture.state == "dirty":
        findings.append(Finding("warn", "closeout-quality-gate", "dirty worktree cue requires explicit task_scope before any commit decision"))
    elif posture.state == "clean":
        findings.append(Finding("info", "closeout-quality-gate", "clean worktree cue remains advisory until task_scope, docs_decision, state_writeback, verification, and policy are recorded"))
    elif posture.state == "non-git":
        findings.append(Finding("info", "closeout-quality-gate", "non-git cue supports an explicit commit_decision skip rationale when applicable"))
    else:
        findings.append(Finding("info", "closeout-quality-gate", "unknown Git posture cue requires explicit operator closeout rationale"))
    return findings


def _trusted_state_writeback_facts(inventory: Inventory) -> dict[str, WritebackFact]:
    facts = current_state_writeback_facts(inventory)
    if not facts:
        return {}
    if state_writeback_identity_matches_current_plan(inventory):
        return facts
    return {}


def _stale_state_writeback_identity_findings(inventory: Inventory) -> list[Finding]:
    facts = state_writeback_facts(inventory.state)
    if not facts or state_writeback_identity_matches_current_plan(inventory):
        return []
    source = inventory.state.rel_path if inventory.state and inventory.state.exists else None
    return [
        Finding(
            "warn",
            "closeout-state-writeback-stale",
            (
                "ignored project-state closeout writeback candidates because their recorded plan identity does not "
                "match the current active or archived plan; active-plan closeout fields or same-request transition "
                "fields remain the current closeout inputs"
            ),
            source,
        )
    ]


def _projection_findings(inventory: Inventory) -> list[Finding]:
    artifact_findings = inspect_projection_artifacts(inventory)
    index_findings = inspect_projection_index(inventory)
    all_findings = artifact_findings + index_findings
    errors = sum(1 for finding in all_findings if finding.severity == "error")
    warnings = sum(1 for finding in all_findings if finding.severity == "warn")
    status = "error" if errors else "warn" if warnings else "ok"
    severity = "warn" if warnings or errors else "info"
    return [
        Finding(
            severity,
            "closeout-projection",
            f"projection posture from read-only inspect: status={status}; warnings={warnings}; errors={errors}; generated projection output remains advisory",
        )
    ]


def _boundary_findings(inventory: Inventory) -> list[Finding]:
    return [
        rails_not_cognition_boundary_finding("project/implementation-plan.md"),
        Finding(
            "info",
            "closeout-non-authority",
            "closeout candidates guide assembly only; source files, observed verification, manifest policy, and operator decisions remain authority",
        ),
        Finding(
            "info",
            "closeout-no-mutation",
            "report did not stage, commit, archive, repair, change target roots, write state, create generated evidence, or change projection artifacts",
        ),
    ]
