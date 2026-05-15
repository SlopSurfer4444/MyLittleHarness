from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from .atomic_files import AtomicFileDelete, AtomicFileWrite, FileTransactionError, apply_file_transaction
from .command_discovery import rails_not_cognition_boundary_finding
from .inventory import Inventory, target_artifact_ownerships
from .lifecycle_focus import sync_current_focus_block
from .memory_hygiene import (
    ROADMAP_CURRENT_POSTURE_FIELD,
    RelationshipUpdatePlan,
    relationship_update_plan,
    sync_roadmap_current_posture_section,
)
from .models import Finding
from .parsing import parse_frontmatter
from .roadmap import (
    ACCEPTED_BOUNDARY_NORMALIZATION_PREFIX,
    ROADMAP_REL,
    RELATED_INCUBATION_FIELD,
    TERMINAL_RELATED_PLAN_RETARGET_FIELD,
    RoadmapPlan,
    RoadmapSliceContract,
    RoadmapSynthesisReport,
    make_roadmap_request,
    roadmap_item_fields,
    roadmap_item_deliverable_class,
    roadmap_item_title,
    roadmap_batch_slice_gate_findings,
    roadmap_plan_scope_blockers,
    roadmap_plan_deliverable_class_blockers,
    roadmap_plan_deliverable_class_next_safe_command,
    roadmap_plan_scope_next_safe_command,
    roadmap_plans_for_requests,
    roadmap_slice_contract_for_item,
    roadmap_compacted_dependency_archive_evidence_findings,
    roadmap_human_review_gate_findings,
    roadmap_related_specs_evidence_findings,
    roadmap_source_incubation_evidence_findings,
    roadmap_synthesis_report_for_item,
    roadmap_text_with_terminal_related_plan_retargets,
)
from .reporting import RouteWriteEvidence, route_write_findings
from .route_reference_guards import route_reference_transaction_guard_findings
from .writeback import state_compaction_apply_findings, state_compaction_dry_run_findings


DEFAULT_PLAN_REL = "project/implementation-plan.md"
DEFAULT_ACTIVE_PHASE = "phase-1-implementation"
DEFAULT_PHASE_STATUS = "pending"
DEFAULT_DOCS_DECISION = "uncertain"
DEFAULT_EXECUTION_POLICY = "current-phase-only"
DEFAULT_CLOSEOUT_BOUNDARY = "explicit-closeout-required"
DEFAULT_AUTO_CONTINUE = False
PLAN_ELIGIBLE_ROADMAP_STATUSES = {"accepted", "active"}
DEFAULT_STOP_CONDITIONS = (
    "auto_continue is absent, false, malformed, or not attached to the current active phase/plan contract",
    "expected verification failed, was skipped without rationale, or lacks a deterministic success signal",
    "docs, API, lifecycle authority, root classification, or write-scope impact is uncertain",
    "the next phase would edit outside the current write scope or cross into a different execution slice",
    "source reality invalidates a future phase contract, discovers a new dependency/schema shape, or needs destructive/sensitive action",
    "the last implementation phase is complete; the next state is explicit closeout preparation, not archive or next-slice opening",
)
DOCS_WRITE_SCOPE_PLACEHOLDER = "declare exact docs/spec/package metadata files before docs_decision=updated mutation"


@dataclass(frozen=True)
class PlanRequest:
    title: str
    objective: str
    task: str
    update_active: bool = False
    roadmap_item: str = ""
    only_requested_item: bool = False


@dataclass(frozen=True)
class PlanCancelRequest:
    roadmap_item: str = ""
    keep_plan: bool = False
    source_hash: str = ""


@dataclass(frozen=True)
class PlanInputResolution:
    request: PlanRequest
    derived_fields: tuple[str, ...] = ()
    candidate_title: str = ""
    candidate_objective: str = ""
    candidate_task: str = ""
    source_excerpt: str = ""


@dataclass(frozen=True)
class GeneratedPlanPhase:
    phase_id: str
    status: str
    objective: str
    dependencies: tuple[str, ...]
    write_scope: tuple[str, ...]
    read_context: tuple[str, ...]
    invariants: str
    implementation_contract: str
    verification_gates: str
    docs_decision_rule: str
    state_transfer: str
    refusal_or_escalation: str


@dataclass(frozen=True)
class VerificationGateProfile:
    status: str
    command: str
    source: str
    reason: str


def make_plan_request(
    title: str | None,
    objective: str | None,
    task: str | None,
    update_active: bool = False,
    roadmap_item: str | None = None,
    only_requested_item: bool = False,
) -> PlanRequest:
    return PlanRequest(
        title=_normalized_text(title),
        objective=_normalized_note(objective),
        task=_normalized_note(task),
        update_active=update_active,
        roadmap_item=_normalized_item_id(roadmap_item),
        only_requested_item=only_requested_item,
    )


def make_plan_cancel_request(roadmap_item: str | None = None, keep_plan: bool = False, source_hash: str | None = None) -> PlanCancelRequest:
    return PlanCancelRequest(
        roadmap_item=_normalized_item_id(roadmap_item),
        keep_plan=bool(keep_plan),
        source_hash=str(source_hash or "").strip().casefold(),
    )


def resolve_plan_request_from_roadmap(inventory: Inventory, request: PlanRequest) -> PlanInputResolution:
    if not request.roadmap_item:
        return PlanInputResolution(request)
    fields = roadmap_item_fields(inventory, request.roadmap_item)
    if not fields:
        return PlanInputResolution(request)

    source_excerpt = _roadmap_source_excerpt(inventory, fields)
    candidate_title = _roadmap_candidate_title(inventory, request.roadmap_item)
    candidate_objective = _roadmap_candidate_objective(request.roadmap_item, fields, source_excerpt)
    candidate_task = _roadmap_candidate_task(inventory, request.roadmap_item, fields, source_excerpt)
    derived_fields: list[str] = []
    resolved = request
    if not resolved.title and candidate_title:
        resolved = replace(resolved, title=candidate_title)
        derived_fields.append("title")
    if not resolved.objective and candidate_objective:
        resolved = replace(resolved, objective=candidate_objective)
        derived_fields.append("objective")
    if not resolved.task and candidate_task:
        resolved = replace(resolved, task=candidate_task)
        derived_fields.append("task")
    return PlanInputResolution(
        resolved,
        tuple(derived_fields),
        candidate_title=candidate_title,
        candidate_objective=candidate_objective,
        candidate_task=candidate_task,
        source_excerpt=source_excerpt,
    )


def render_implementation_plan(
    request: PlanRequest,
    *,
    today: date | None = None,
    source_incubation: str = "",
    slice_contract: RoadmapSliceContract | None = None,
    synthesis_report: RoadmapSynthesisReport | None = None,
    verification_profile: VerificationGateProfile | None = None,
) -> str:
    current_date = (today or date.today()).isoformat()
    title = request.title or "Implementation Plan"
    objective = request.objective or "Define and verify the requested implementation work."
    plan_id = f"{current_date}-{_safe_slug(title) or 'implementation-plan'}"
    phases = _generated_phases(slice_contract, synthesis_report, verification_profile)
    active_phase = phases[0].phase_id if phases else DEFAULT_ACTIVE_PHASE
    scaffold_noun = _plan_scaffold_noun(slice_contract)
    relationship_frontmatter = _slice_frontmatter(request, slice_contract, source_incubation)
    task_section = ""
    if request.task:
        task_section = f"\n## Explicit Task Input\n\n{request.task.rstrip()}\n"
    slice_section = _slice_contract_section(slice_contract)
    synthesis_section = _plan_synthesis_section(synthesis_report, slice_contract, verification_profile)
    roadmap_authority_input = "- `project/roadmap.md`\n" if request.roadmap_item else ""

    return (
        "---\n"
        f'plan_id: "{_yaml_double_quoted_value(plan_id)}"\n'
        f'title: "{_yaml_double_quoted_value(title)}"\n'
        'status: "pending"\n'
        f'active_phase: "{_yaml_double_quoted_value(active_phase)}"\n'
        f'phase_status: "{DEFAULT_PHASE_STATUS}"\n'
        f'docs_decision: "{DEFAULT_DOCS_DECISION}"\n'
        f"{_execution_policy_frontmatter(slice_contract)}"
        f"{relationship_frontmatter}"
        f'created: "{current_date}"\n'
        f'updated: "{current_date}"\n'
        "---\n"
        f"# {title}\n\n"
        "## Objective\n\n"
        f"{objective.rstrip()}\n"
        f"{task_section}"
        f"{slice_section}"
        f"{synthesis_section}"
        "\n## Authority Inputs\n\n"
        "- `AGENTS.md`\n"
        "- `.codex/project-workflow.toml`\n"
        "- `project/project-state.md`\n"
        f"{roadmap_authority_input}"
        "- `project/specs/workflow/workflow-plan-synthesis-spec.md`\n"
        "- `project/specs/workflow/workflow-rollout-slices-spec.md`\n"
        "- `project/specs/workflow/workflow-verification-and-closeout-spec.md`\n"
        "- Explicit task input supplied to `mylittleharness plan`\n"
        "\n## Non-goals\n\n"
        "- No hidden memory, background planner, external service, model call, or dependency install.\n"
        "- No autonomous repair, archive, closeout, commit, rollback, or lifecycle approval.\n"
        "- No broad refactor outside the accepted write scope for this plan.\n"
        "\n## Invariants\n\n"
        "- Repo-visible files remain authority; command output is advisory until written.\n"
        "- Recovery stays non-destructive and reviewable.\n"
        "- Product-source fixtures and archive roots are not live operating memory.\n"
        "- Docs decision must be recorded as `updated`, `not-needed`, or `uncertain` before confident closeout.\n"
        "\n## Execution Policy\n\n"
        f"- execution_policy: `{slice_contract.execution_policy if slice_contract and slice_contract.execution_policy else DEFAULT_EXECUTION_POLICY}`\n"
        f"- auto_continue: `{str(DEFAULT_AUTO_CONTINUE).lower()}`\n"
        f"- default continuation: execute only `{active_phase}`, record repo-visible evidence/state, then stop.\n"
        f"{_stop_conditions_body()}"
        "\n## File Ownership\n\n"
        "- Write scope: declare exact files before editing them.\n"
        "- Read context: inspect adjacent source, tests, docs, and workflow authority before widening scope.\n"
        "- Off-limits: generated caches, workstation state, package artifacts, and unrelated user changes.\n"
        "\n## Phases\n\n"
        f"{_phase_sections_from_phases(phases)}"
        "\n## Verification Strategy\n\n"
        "- Run the narrowest deterministic tests that cover changed behavior.\n"
        "- Run `mylittleharness --root <this-repo> check` before confident closeout.\n"
        "- Treat failed verification as a blocker or residual risk, not as permission to widen scope silently.\n"
        "\n## Docs Decision\n\n"
        f"- docs_decision: {DEFAULT_DOCS_DECISION}\n"
        "- Record `updated`, `not-needed`, or `uncertain` with evidence before closeout.\n"
        "\n## State Transfer\n\n"
        "- Update `project/project-state.md` lifecycle fields through an explicit writeback path or equivalent scoped mutation.\n"
        "- Record a concise plain-language work result capsule for meaningful mutating or lifecycle work.\n"
        "- Keep active-plan copies as derived execution metadata; project-state remains lifecycle authority.\n"
        "\n## Refusal Conditions\n\n"
        "- Refuse unsafe roots, malformed authority files, active-plan conflicts, path escapes, symlink targets, or ambiguous lifecycle state.\n"
        "- Refuse task input that asks for destructive VCS recovery, broad restoration, or cleanup outside the declared scope.\n"
        "\n## Closeout Checklist\n\n"
        "- worktree_start_state: record clean/dirty starting posture and preserve unrelated changes.\n"
        "- task_scope: summarize the completed product or workflow behavior.\n"
        "- docs_decision: record `updated`, `not-needed`, or `uncertain`.\n"
        "- state_writeback: describe lifecycle/state updates performed.\n"
        "- verification: list commands run and observed outcomes.\n"
        "- commit_decision: follow the repository policy.\n"
        "- residual_risk: record known gaps.\n"
        "- carry_forward: record bounded follow-up items.\n"
        "- work_result: record what changed, what became better, how it was checked, and what remains in plain language.\n"
        "\n## Decision Log\n\n"
        f"- {current_date}: Created deterministic {scaffold_noun} scaffold with `mylittleharness plan`.\n"
    )


def _plan_scaffold_noun(slice_contract: RoadmapSliceContract | None) -> str:
    if _is_non_implementation_contract(slice_contract):
        return f"{_contract_deliverable_class_for_text(slice_contract)} active-work"
    return "implementation-plan"


def _contract_work_class(slice_contract: RoadmapSliceContract | None) -> str:
    raw = str(getattr(slice_contract, "work_class", "") or "").strip().casefold().replace("-", "_")
    if raw == "non_implementation":
        return "non_implementation"
    deliverable_class = _contract_deliverable_class(slice_contract)
    if deliverable_class in {"audit", "cleanup", "diagnostic", "evidence", "fan-in-review", "proposal", "research"}:
        return "non_implementation"
    return "implementation"


def _contract_deliverable_class(slice_contract: RoadmapSliceContract | None) -> str:
    raw = str(getattr(slice_contract, "deliverable_class", "") or "").strip().casefold().replace("_", "-")
    return raw or "implementation"


def _contract_deliverable_class_for_frontmatter(slice_contract: RoadmapSliceContract | None) -> str:
    deliverable_class = _contract_deliverable_class(slice_contract)
    if deliverable_class == "fan-in-review":
        return "fan_in_review"
    return deliverable_class


def _contract_deliverable_class_for_text(slice_contract: RoadmapSliceContract | None) -> str:
    return _contract_deliverable_class(slice_contract).replace("-", " ")


def _contract_implementation_allowed(slice_contract: RoadmapSliceContract | None) -> bool:
    if slice_contract is None:
        return True
    return bool(getattr(slice_contract, "implementation_allowed", _contract_work_class(slice_contract) == "implementation"))


def _contract_promotion_required(slice_contract: RoadmapSliceContract | None) -> bool:
    if slice_contract is None:
        return False
    return bool(getattr(slice_contract, "promotion_required", _contract_work_class(slice_contract) == "non_implementation"))


def _is_non_implementation_contract(slice_contract: RoadmapSliceContract | None) -> bool:
    return _contract_work_class(slice_contract) == "non_implementation" and not _contract_implementation_allowed(slice_contract)


def _slice_frontmatter(
    request: PlanRequest,
    slice_contract: RoadmapSliceContract | None,
    source_incubation: str,
) -> str:
    lines: list[str] = []
    if slice_contract:
        if slice_contract.execution_slice:
            lines.append(f'execution_slice: "{_yaml_double_quoted_value(slice_contract.execution_slice)}"\n')
        lines.append(f'primary_roadmap_item: "{_yaml_double_quoted_value(slice_contract.primary_roadmap_item)}"\n')
        lines.append(_yaml_frontmatter_list("covered_roadmap_items", slice_contract.covered_roadmap_items))
        lines.append(f'domain_context: "{_yaml_double_quoted_value(slice_contract.domain_context)}"\n')
        lines.append(_yaml_frontmatter_list("target_artifacts", slice_contract.target_artifacts))
        lines.append(f'work_class: "{_yaml_double_quoted_value(_contract_work_class(slice_contract))}"\n')
        lines.append(f'deliverable_class: "{_yaml_double_quoted_value(_contract_deliverable_class_for_frontmatter(slice_contract))}"\n')
        lines.append(f"implementation_allowed: {str(_contract_implementation_allowed(slice_contract)).lower()}\n")
        lines.append(f"promotion_required: {str(_contract_promotion_required(slice_contract)).lower()}\n")
        lines.append(f'related_roadmap_item: "{_yaml_double_quoted_value(slice_contract.primary_roadmap_item)}"\n')
        if slice_contract.source_incubation:
            lines.append(f'source_incubation: "{_yaml_double_quoted_value(slice_contract.source_incubation)}"\n')
        if slice_contract.related_incubation:
            lines.append(f'related_incubation: "{_yaml_double_quoted_value(slice_contract.related_incubation)}"\n')
        if slice_contract.source_research:
            lines.append(f'source_research: "{_yaml_double_quoted_value(slice_contract.source_research)}"\n')
        if slice_contract.related_specs:
            lines.append(_yaml_frontmatter_list("related_specs", slice_contract.related_specs))
    else:
        if request.roadmap_item:
            lines.append(f'related_roadmap_item: "{_yaml_double_quoted_value(request.roadmap_item)}"\n')
        if source_incubation:
            lines.append(f'source_incubation: "{_yaml_double_quoted_value(source_incubation)}"\n')
    return "".join(lines)


def _execution_policy_frontmatter(slice_contract: RoadmapSliceContract | None) -> str:
    policy = slice_contract.execution_policy if slice_contract and slice_contract.execution_policy else DEFAULT_EXECUTION_POLICY
    closeout_boundary = slice_contract.closeout_boundary if slice_contract and slice_contract.closeout_boundary else DEFAULT_CLOSEOUT_BOUNDARY
    return (
        f'execution_policy: "{_yaml_double_quoted_value(policy)}"\n'
        f"auto_continue: {str(DEFAULT_AUTO_CONTINUE).lower()}\n"
        f"{_yaml_frontmatter_list('stop_conditions', DEFAULT_STOP_CONDITIONS)}"
        f'closeout_boundary: "{_yaml_double_quoted_value(closeout_boundary)}"\n'
    )


def _stop_conditions_body() -> str:
    return "".join(f"- stop_condition: {condition}.\n" for condition in DEFAULT_STOP_CONDITIONS)


def _slice_contract_section(slice_contract: RoadmapSliceContract | None) -> str:
    if slice_contract is None:
        return ""
    covered = ", ".join(f"`{item}`" for item in slice_contract.covered_roadmap_items) or "`<none>`"
    artifacts = ", ".join(f"`{item}`" for item in slice_contract.target_artifacts) or "`[]`"
    return (
        "\n## Slice Contract\n\n"
        f"- primary_roadmap_item: `{slice_contract.primary_roadmap_item}`\n"
        f"- covered_roadmap_items: {covered}\n"
        f"- execution_slice: `{slice_contract.execution_slice or '<none>'}`\n"
        f"- domain_context: `{slice_contract.domain_context}`\n"
        f"- target_artifacts: {artifacts}\n"
        f"- work_class: `{_contract_work_class(slice_contract)}`\n"
        f"- deliverable_class: `{_contract_deliverable_class_for_frontmatter(slice_contract)}`\n"
        f"- implementation_allowed: `{str(_contract_implementation_allowed(slice_contract)).lower()}`\n"
        f"- promotion_required: `{str(_contract_promotion_required(slice_contract)).lower()}`\n"
        f"- execution_policy: `{slice_contract.execution_policy}`\n"
        f"- closeout_boundary: `{slice_contract.closeout_boundary}`\n"
    )


def _plan_synthesis_section(
    report: RoadmapSynthesisReport | None,
    slice_contract: RoadmapSliceContract | None = None,
    verification_profile: VerificationGateProfile | None = None,
) -> str:
    if report is None:
        return ""
    covered = ", ".join(f"`{item}`" for item in report.covered_roadmap_items) or "`<none>`"
    bundle = "\n".join(f"- {signal}" for signal in report.bundle_signals)
    split = "\n".join(f"- {signal}" for signal in report.split_signals)
    phase_note = _phase_outline_note(report, slice_contract, verification_profile)
    return (
        "\n## Plan Synthesis Notes\n\n"
        f"- covered_roadmap_items: {covered}\n"
        f"- target_artifact_pressure: {report.target_artifact_pressure}\n"
        f"- phase_pressure: {report.phase_pressure}\n"
        "\n### Bundle Rationale\n\n"
        f"{bundle}\n"
        "\n### Split Boundary\n\n"
        f"{split}\n"
        f"{phase_note}"
        "\nPlan synthesis notes are advisory sizing evidence only; they cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions, or next-slice movement.\n"
    )


def _phase_outline_note(
    report: RoadmapSynthesisReport,
    slice_contract: RoadmapSliceContract | None = None,
    verification_profile: VerificationGateProfile | None = None,
) -> str:
    if not _is_non_implementation_contract(slice_contract) and _recommended_phase_count_for_report(report) <= 1:
        return (
            "\n### One-Shot Rationale\n\n"
            "- Generated as one explicit current phase because the roadmap slice has low artifact and verification pressure.\n"
            "- If implementation discovers extra write scope, docs/API uncertainty, or missing deterministic verification, stop and update the plan before widening.\n"
        )
    phases = _generated_phases(slice_contract, report, verification_profile)
    lines = ["\n### Phase Outline\n\n"]
    for phase in phases:
        lines.append(f"- `{phase.phase_id}`: {phase.objective}\n")
    return "".join(lines)


def _phase_sections(
    slice_contract: RoadmapSliceContract | None,
    report: RoadmapSynthesisReport | None,
    verification_profile: VerificationGateProfile | None = None,
) -> str:
    return _phase_sections_from_phases(_generated_phases(slice_contract, report, verification_profile))


def _phase_sections_from_phases(phases: tuple[GeneratedPlanPhase, ...]) -> str:
    return "\n".join(_render_phase_section(phase) for phase in phases)


def _generated_phases(
    slice_contract: RoadmapSliceContract | None,
    report: RoadmapSynthesisReport | None,
    verification_profile: VerificationGateProfile | None = None,
) -> tuple[GeneratedPlanPhase, ...]:
    if report is None:
        return (_default_generated_phase(),)
    if _is_non_implementation_contract(slice_contract):
        return _non_implementation_generated_phases(slice_contract, report)

    targets = tuple(report.target_artifacts)
    groups = _artifact_groups(targets)
    read_context = tuple(
        _dedupe_nonempty(
            (
                "AGENTS.md",
                ".codex/project-workflow.toml",
                "project/project-state.md",
                "project/roadmap.md",
                *report.related_specs,
                *report.source_inputs,
            )
        )
    )
    boundary = slice_contract.closeout_boundary if slice_contract else "explicit-closeout-required"
    source_scope = groups["source"] or groups["other"] or groups["docs"] or targets
    test_scope = groups["tests"]
    docs_scope = _docs_impact_scope(report, groups)
    if getattr(report, "docs_update_count", 0) > 0 and docs_scope:
        docs_scope_set = set(docs_scope)
        source_scope = tuple(target for target in source_scope if target not in docs_scope_set)
    all_scope = targets or ("project/implementation-plan.md",)
    phase_1_scope = tuple(_dedupe_nonempty((*source_scope, *test_scope))) if test_scope else source_scope

    phase_1 = GeneratedPlanPhase(
        phase_id=DEFAULT_ACTIVE_PHASE,
        status=DEFAULT_PHASE_STATUS,
        objective="Implement the roadmap-backed behavior inside the declared product/source contract.",
        dependencies=(),
        write_scope=phase_1_scope,
        read_context=read_context,
        invariants=(
            "keep MLH target-repository boundaries, explicit dry-run/apply semantics, and "
            "current-phase-only execution intact"
        ),
        implementation_contract=(
            f"deliver the behavior for `{report.primary_roadmap_item}` without hidden runtime state; "
            "roadmap synthesis remains advisory and cannot approve lifecycle movement"
        ),
        verification_gates=_focused_verification_gate(test_scope, verification_profile),
        docs_decision_rule="keep `docs_decision` as `uncertain` until docs/spec/package impact is proven.",
        state_transfer="record changed contracts, source assumptions, verification evidence, residual risk, carry-forward, and a plain-language work result capsule.",
        refusal_or_escalation="stop before unsafe roots, destructive recovery, hidden infrastructure, unclear ownership, or edits outside this phase write_scope.",
    )

    if _recommended_phase_count_for_report(report) <= 1:
        return (phase_1,)

    phase_2_scope = tuple(_dedupe_nonempty((*test_scope, *docs_scope))) or all_scope
    phase_2 = GeneratedPlanPhase(
        phase_id="phase-2-verification-and-docs",
        status="pending",
        objective=_phase_2_objective(test_scope, docs_scope, verification_profile),
        dependencies=(DEFAULT_ACTIVE_PHASE,),
        write_scope=phase_2_scope,
        read_context=read_context,
        invariants="do not weaken phase-1 verification, roadmap advisory boundaries, or current-phase-only stop conditions.",
        implementation_contract=_phase_2_implementation_contract(test_scope, docs_scope, verification_profile),
        verification_gates=_focused_verification_gate(test_scope, verification_profile),
        docs_decision_rule=_phase_2_docs_decision_rule(docs_scope),
        state_transfer=_phase_2_state_transfer(test_scope, docs_scope, verification_profile),
        refusal_or_escalation="stop if docs/API/lifecycle authority is uncertain or verification cannot provide a deterministic success signal.",
    )

    if _recommended_phase_count_for_report(report) <= 2:
        return (phase_1, phase_2)

    phase_3 = GeneratedPlanPhase(
        phase_id="phase-3-integration-and-state-transfer",
        status="pending",
        objective="Run broader integration checks, mirror/cross-root verification when required, and prepare explicit closeout evidence.",
        dependencies=("phase-2-verification-and-docs",),
        write_scope=("project/implementation-plan.md", "project/project-state.md"),
        read_context=tuple(_dedupe_nonempty((*read_context, *all_scope))),
        invariants=(
            f"closeout boundary remains `{boundary}`; completing implementation does not archive, commit, "
            "mark roadmap done, or open the next slice"
        ),
        implementation_contract="repo-visible state transfer is compact, deterministic, and enough for explicit closeout preparation.",
        verification_gates=(
            "`mylittleharness --root <operating-root> check` exits 0; run broader product or boundary tests when product source changed"
        ),
        docs_decision_rule="final docs_decision must be `updated`, `not-needed`, or `uncertain`; uncertain keeps closeout language provisional.",
        state_transfer="record final verification summary, residual risk, carry-forward, work result capsule, and commit decision without staging or archive authority.",
        refusal_or_escalation="stop before closeout/archive/roadmap done-status/commit unless the user explicitly requests that lifecycle action.",
    )
    return (phase_1, phase_2, phase_3)


def _non_implementation_generated_phases(
    slice_contract: RoadmapSliceContract | None,
    report: RoadmapSynthesisReport,
) -> tuple[GeneratedPlanPhase, ...]:
    deliverable_class = _contract_deliverable_class(slice_contract)
    phase_1_id, phase_2_id, phase_3_id = _non_implementation_phase_ids(deliverable_class)
    output_artifacts = tuple(report.target_artifacts) or (_default_output_artifact_for_deliverable(deliverable_class),)
    read_context = tuple(
        _dedupe_nonempty(
            (
                "AGENTS.md",
                ".codex/project-workflow.toml",
                "project/project-state.md",
                "project/roadmap.md",
                *report.related_specs,
                *report.source_inputs,
            )
        )
    )
    deliverable_text = _contract_deliverable_class_for_text(slice_contract)
    artifact_list = _backticked_values(output_artifacts, "`<declare output artifact>`")
    shared_invariants = (
        "repo-visible output artifacts are authority; product-source mutation, product diff acceptance, "
        "archive, staging, commit, and next-slice opening stay forbidden unless a later implementation plan is explicitly opened"
    )

    phase_1 = GeneratedPlanPhase(
        phase_id=phase_1_id,
        status=DEFAULT_PHASE_STATUS,
        objective=_non_implementation_phase_1_objective(deliverable_class),
        dependencies=(),
        write_scope=output_artifacts,
        read_context=read_context,
        invariants=shared_invariants,
        implementation_contract=(
            f"non-implementation contract: shape the `{deliverable_text}` source set and output artifact(s) "
            f"{artifact_list} without treating product tests or product diff as completion proof"
        ),
        verification_gates=_non_implementation_verification_gate(deliverable_class, output_artifacts),
        docs_decision_rule="keep `docs_decision` as `uncertain` unless the work is proven operating-memory-only, then record `not-needed` with artifact evidence.",
        state_transfer="record source set, output artifact path(s), unresolved questions, and why no product source mutation was accepted.",
        refusal_or_escalation="stop before product-source edits, product diff acceptance/revert/discard, or lifecycle movement outside this non-implementation deliverable.",
    )
    phase_2 = GeneratedPlanPhase(
        phase_id=phase_2_id,
        status="pending",
        objective=_non_implementation_phase_2_objective(deliverable_class),
        dependencies=(phase_1_id,),
        write_scope=output_artifacts,
        read_context=tuple(_dedupe_nonempty((*read_context, *output_artifacts))),
        invariants=shared_invariants,
        implementation_contract=(
            f"complete the `{deliverable_text}` artifact with findings, evidence, disposition, residual risk, "
            "and follow-up slice candidates; do not silently promote it into implementation work"
        ),
        verification_gates=_non_implementation_verification_gate(deliverable_class, output_artifacts),
        docs_decision_rule="record `not-needed` for operating-memory-only deliverables; keep `uncertain` if docs/spec impact remains unresolved.",
        state_transfer="record artifact completeness, disposition summary, residual risk, and explicit non-acceptance of any underlying product diff.",
        refusal_or_escalation="stop if the deliverable needs product mutations, destructive cleanup, broad acceptance, or a new implementation slice.",
    )
    phase_3 = GeneratedPlanPhase(
        phase_id=phase_3_id,
        status="pending",
        objective=_non_implementation_phase_3_objective(deliverable_class),
        dependencies=(phase_2_id,),
        write_scope=("project/implementation-plan.md", "project/project-state.md"),
        read_context=tuple(_dedupe_nonempty((*read_context, *output_artifacts))),
        invariants=shared_invariants,
        implementation_contract="state transfer cites the output artifact as evidence; lifecycle closeout remains explicit and does not accept product diff by implication.",
        verification_gates="`mylittleharness --root <operating-root> check` exits 0 or records bounded warnings; output artifact evidence remains the primary proof.",
        docs_decision_rule="final docs_decision must be `updated`, `not-needed`, or `uncertain`; uncertain keeps closeout language provisional.",
        state_transfer="record final artifact path(s), docs_decision, residual risk, carry-forward, and next safe MLH command without opening the next slice.",
        refusal_or_escalation="stop before archive/roadmap done-status/commit/next-plan opening unless the user explicitly requests that lifecycle action.",
    )
    return (phase_1, phase_2, phase_3)


def _non_implementation_phase_ids(deliverable_class: str) -> tuple[str, str, str]:
    if deliverable_class == "fan-in-review":
        return (
            "phase-1-fan-in-review-scope",
            "phase-2-fan-in-review-disposition",
            "phase-3-fan-in-review-state-transfer",
        )
    phase_key = deliverable_class if deliverable_class in {"audit", "cleanup", "diagnostic", "evidence", "proposal", "research"} else "review"
    phase_2_name = {
        "audit": "findings",
        "cleanup": "disposition",
        "diagnostic": "matrix",
        "evidence": "validation",
        "proposal": "options",
        "research": "synthesis",
        "review": "disposition",
    }[phase_key]
    return (
        f"phase-1-{phase_key}-scope",
        f"phase-2-{phase_key}-{phase_2_name}",
        f"phase-3-{phase_key}-state-transfer",
    )


def _default_output_artifact_for_deliverable(deliverable_class: str) -> str:
    if deliverable_class == "research":
        return "project/research/<research-artifact>.md"
    return "project/verification/<non-implementation-artifact>.md"


def _non_implementation_phase_1_objective(deliverable_class: str) -> str:
    if deliverable_class == "diagnostic":
        return "Inspect the source evidence read-only and define diagnostic questions, cluster axes, and required output artifact fields."
    if deliverable_class == "fan-in-review":
        return "Inspect fan-in inputs read-only and define disposition axes before accepting, splitting, discarding, or deferring any diff."
    if deliverable_class == "audit":
        return "Inventory the audited surfaces, evidence sources, and finding taxonomy without starting implementation work."
    if deliverable_class == "research":
        return "Lock the research question, source set, and synthesis artifact before drawing implementation conclusions."
    if deliverable_class == "proposal":
        return "Shape proposal goals, constraints, options, and decision boundary without mutating product source."
    if deliverable_class == "evidence":
        return "Collect the proof source set and validation criteria before claiming completion."
    if deliverable_class == "cleanup":
        return "Scope cleanup candidates and risk boundaries before deleting, moving, accepting, or rewriting anything."
    return "Scope the non-implementation review deliverable and output artifact before any implementation work."


def _non_implementation_phase_2_objective(deliverable_class: str) -> str:
    if deliverable_class == "diagnostic":
        return "Produce the diagnostic matrix/report with findings, evidence, disposition, residual risk, and next slice candidates."
    if deliverable_class == "fan-in-review":
        return "Produce the fan-in disposition matrix separating accept, split, discard, and defer candidates without mutating product source."
    if deliverable_class == "audit":
        return "Produce findings with severity, evidence, affected route, owner command, and recommended slice split."
    if deliverable_class == "research":
        return "Synthesize source-bound claims, confidence, open questions, and implementation implications."
    if deliverable_class == "proposal":
        return "Write the proposal options, recommended path, rejected alternatives, and promotion boundary."
    if deliverable_class == "evidence":
        return "Validate evidence against the required claim and record any gaps or residual risk."
    if deliverable_class == "cleanup":
        return "Produce cleanup disposition and safe follow-up commands without applying destructive changes."
    return "Produce the non-implementation review artifact with evidence, disposition, residual risk, and follow-up work."


def _non_implementation_phase_3_objective(deliverable_class: str) -> str:
    if deliverable_class == "diagnostic":
        return "Record diagnostic evidence, docs_decision, residual risk, and explicit no-product-diff-acceptance state transfer."
    if deliverable_class == "fan-in-review":
        return "Record fan-in disposition evidence, follow-up slices, and explicit no-product-diff-acceptance state transfer."
    return f"Record {_normalized_text(deliverable_class.replace('-', ' '))} evidence, docs_decision, residual risk, and next safe command."


def _non_implementation_verification_gate(deliverable_class: str, output_artifacts: tuple[str, ...]) -> str:
    artifact_list = _backticked_values(output_artifacts, "`<declare output artifact>`")
    if deliverable_class == "fan-in-review":
        return (
            f"repo-visible `fan_in_review` output artifact exists at {artifact_list}, names source snapshot, "
            "cluster disposition, missing evidence, forbidden shortcuts, owner route, follow-up slice, and explicit "
            "no-product-diff-acceptance fields; product tests are not used as primary proof"
        )
    return (
        f"repo-visible `{deliverable_class.replace('-', '_')}` output artifact exists at {artifact_list}, names its source set and evidence, "
        "and product tests are not used as primary proof"
    )


def _default_generated_phase() -> GeneratedPlanPhase:
    return GeneratedPlanPhase(
        phase_id=DEFAULT_ACTIVE_PHASE,
        status=DEFAULT_PHASE_STATUS,
        objective="Implement the requested change inside the declared write scope.",
        dependencies=(),
        write_scope=("update this section with exact target files before mutation",),
        read_context=("repo-visible authority and relevant local tests/docs",),
        invariants="keep MLH target-repository boundaries and explicit apply/dry-run semantics intact.",
        implementation_contract="deliver the requested behavior without adding hidden runtime state.",
        verification_gates="run targeted tests first, then broader checks appropriate to the changed surface.",
        docs_decision_rule="keep `docs_decision` as `uncertain` until docs impact is proven.",
        state_transfer="record changed contracts, verification evidence, residual risk, carry-forward, and a plain-language work result capsule.",
        refusal_or_escalation="stop before unsafe roots, destructive recovery, hidden infrastructure, or unclear ownership.",
    )


def _phase_2_objective(
    test_scope: tuple[str, ...],
    docs_scope: tuple[str, ...],
    verification_profile: VerificationGateProfile | None,
) -> str:
    verification_subject = _phase_contract_verification_subject(test_scope, verification_profile)
    docs_subject = _phase_contract_docs_subject(docs_scope)
    if docs_subject:
        return f"Prove the behavior with {verification_subject} and {docs_subject}."
    return f"Prove the behavior with {verification_subject} and record docs_decision evidence without widening docs scope."


def _phase_2_implementation_contract(
    test_scope: tuple[str, ...],
    docs_scope: tuple[str, ...],
    verification_profile: VerificationGateProfile | None,
) -> str:
    verification_owner = _phase_contract_verification_owner(test_scope, verification_profile)
    docs_owner = _phase_contract_docs_owner(docs_scope)
    return (
        f"verification ownership stays on {verification_owner}; docs ownership stays on {docs_owner}; "
        "generated phase outline or one-shot rationale must name those concrete owners"
    )


def _phase_2_docs_decision_rule(docs_scope: tuple[str, ...]) -> str:
    base = "record `updated` when specs/templates/docs change"
    if docs_scope:
        return (
            f"{base} in the named docs/spec/package scope; replace any placeholder before mutation; "
            "otherwise record `not-needed` with evidence."
        )
    return f"{base}; when no docs/spec/package files change, record `not-needed` with evidence instead."


def _phase_2_state_transfer(
    test_scope: tuple[str, ...],
    docs_scope: tuple[str, ...],
    verification_profile: VerificationGateProfile | None,
) -> str:
    verification_owner = _phase_contract_verification_owner(test_scope, verification_profile)
    docs_owner = _phase_contract_docs_owner(docs_scope)
    return (
        f"record exact verification owner ({verification_owner}), expected success signal, "
        f"docs_decision evidence tied to {docs_owner}, any remaining generic/unresolved gates, "
        "and a plain-language work result capsule."
    )


def _phase_contract_verification_subject(
    test_scope: tuple[str, ...],
    verification_profile: VerificationGateProfile | None,
) -> str:
    if test_scope:
        return f"focused regression ownership in {_backticked_values(test_scope, 'targeted tests')}"
    if verification_profile and verification_profile.status == "candidate" and verification_profile.command:
        source = "CI workflow" if "CI workflow" in verification_profile.source else "repo-visible verification"
        return f"{source} gate `{verification_profile.command}`"
    if verification_profile and verification_profile.status == "unresolved":
        return "an evidence-backed verification gate before closeout"
    return "a deterministic verification gate before completion"


def _phase_contract_verification_owner(
    test_scope: tuple[str, ...],
    verification_profile: VerificationGateProfile | None,
) -> str:
    if test_scope:
        return _backticked_values(test_scope, "`targeted tests`")
    if verification_profile and verification_profile.status == "candidate" and verification_profile.command:
        return f"`{verification_profile.command}` from {verification_profile.source}"
    if verification_profile and verification_profile.status == "unresolved":
        return "an explicit verification command recorded before closeout"
    return "a deterministic verification command recorded before completion"


def _phase_contract_docs_subject(docs_scope: tuple[str, ...]) -> str:
    if not docs_scope:
        return ""
    concrete_scope = tuple(value for value in docs_scope if value != DOCS_WRITE_SCOPE_PLACEHOLDER)
    if DOCS_WRITE_SCOPE_PLACEHOLDER in docs_scope:
        if concrete_scope:
            return (
                f"update docs/spec/package scope {_backticked_values(concrete_scope, 'the named docs scope')} "
                f"after replacing `{DOCS_WRITE_SCOPE_PLACEHOLDER}`"
            )
        return f"keep docs/spec/package mutation blocked until exact files replace `{DOCS_WRITE_SCOPE_PLACEHOLDER}`"
    return f"update docs/spec/package scope {_backticked_values(docs_scope, 'the named docs scope')}"


def _phase_contract_docs_owner(docs_scope: tuple[str, ...]) -> str:
    if not docs_scope:
        return "`docs_decision` evidence only when no docs/spec/package files change"
    concrete_scope = tuple(value for value in docs_scope if value != DOCS_WRITE_SCOPE_PLACEHOLDER)
    if DOCS_WRITE_SCOPE_PLACEHOLDER in docs_scope:
        if concrete_scope:
            return (
                f"{_backticked_values(concrete_scope, 'the named docs scope')} plus exact files replacing "
                f"`{DOCS_WRITE_SCOPE_PLACEHOLDER}`"
            )
        return f"exact files replacing `{DOCS_WRITE_SCOPE_PLACEHOLDER}`"
    return _backticked_values(docs_scope, "`the named docs scope`")


def _render_phase_section(phase: GeneratedPlanPhase) -> str:
    dependencies = _backticked_values(phase.dependencies, "`<none>`")
    return (
        f"### {phase.phase_id}\n\n"
        f"- id: `{phase.phase_id}`\n"
        f"- status: `{phase.status}`\n"
        f"- objective: {phase.objective}\n"
        f"- dependencies: {dependencies}\n"
        f"- write_scope: {_backticked_values(phase.write_scope, '`<none>`')}\n"
        f"- read_context: {_backticked_values(phase.read_context, '`<none>`')}\n"
        f"- invariants: {phase.invariants}\n"
        f"- implementation_contract: {phase.implementation_contract}\n"
        f"- verification_gates: {phase.verification_gates}\n"
        f"- docs_decision_rule: {phase.docs_decision_rule}\n"
        f"- state_transfer: {phase.state_transfer}\n"
        f"- refusal_or_escalation: {phase.refusal_or_escalation}\n"
    )


def _artifact_groups(targets: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    source: list[str] = []
    tests: list[str] = []
    docs: list[str] = []
    other: list[str] = []
    for target in targets:
        normalized = _normalize_rel(target)
        if normalized.startswith("tests/"):
            tests.append(normalized)
        elif _is_docs_like_target(normalized):
            docs.append(DOCS_WRITE_SCOPE_PLACEHOLDER if _is_broad_docs_scope(normalized) else normalized)
        elif normalized.startswith("src/"):
            source.append(normalized)
        else:
            other.append(normalized)
    return {
        "source": tuple(source),
        "tests": tuple(tests),
        "docs": tuple(docs),
        "other": tuple(other),
    }


def _is_docs_like_target(target: str) -> bool:
    normalized = _normalize_rel(target)
    return (
        normalized.startswith("docs/")
        or normalized.startswith("project/specs/")
        or normalized.startswith("src/mylittleharness/templates/")
        or normalized.endswith(".md")
    )


def _is_broad_docs_scope(target: str) -> bool:
    normalized = _normalize_rel(target).strip("/").casefold()
    if not normalized:
        return False
    for prefix in ("docs", "project/specs", "src/mylittleharness/templates"):
        if normalized == prefix or normalized.startswith(f"{prefix}/"):
            leaf = normalized.rsplit("/", 1)[-1]
            return "." not in leaf
    return False


def _docs_impact_scope(report: RoadmapSynthesisReport, groups: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    docs_scope = list(groups["docs"])
    if getattr(report, "docs_update_count", 0) <= 0:
        return tuple(docs_scope)
    docs_scope.extend(report.related_specs)
    docs_scope.extend(target for target in groups["other"] if _is_package_metadata_target(target))
    if not docs_scope:
        docs_scope.append(DOCS_WRITE_SCOPE_PLACEHOLDER)
    return tuple(_dedupe_nonempty(docs_scope))


def _is_package_metadata_target(target: str) -> bool:
    normalized = _normalize_rel(target).casefold()
    return normalized in {"pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}


def _focused_verification_gate(
    test_scope: tuple[str, ...],
    verification_profile: VerificationGateProfile | None = None,
) -> str:
    if test_scope:
        return (
            "`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src uv run --no-project --with pytest pytest -q "
            f"{' '.join(test_scope)}` exits 0"
        )
    if verification_profile and verification_profile.status == "candidate" and verification_profile.command:
        return (
            f"`{verification_profile.command}` exits 0 "
            f"(repo-visible candidate from {verification_profile.source}; {verification_profile.reason})"
        )
    if verification_profile and verification_profile.status == "unresolved":
        return (
            "UNRESOLVED: no repo-visible verification command was discovered from target artifacts, package scripts, "
            "Makefile/just/task files, CI workflows, docs, prior evidence, or roadmap verification_summary; "
            "agent must record a concrete gate before confident closeout."
        )
    return "`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src uv run --no-project --with pytest pytest -q` exits 0 or a narrower deterministic command is recorded before completion"


def _repo_verification_gate_profile(
    inventory: Inventory,
    request: PlanRequest,
    report: RoadmapSynthesisReport | None,
    slice_contract: RoadmapSliceContract | None,
) -> VerificationGateProfile | None:
    if report is None and slice_contract is None:
        return None
    target_artifacts = tuple(report.target_artifacts if report else slice_contract.target_artifacts if slice_contract else ())
    verification_summary = ""
    if request.roadmap_item:
        verification_summary = _normalized_note(roadmap_item_fields(inventory, request.roadmap_item).get("verification_summary"))
    target_root = _verification_target_root(inventory)
    if command := _command_from_package_scripts(target_root, target_artifacts):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source=f"{_display_repo_source(target_root, inventory)} package scripts",
            reason="agent may add adjacent scripts when the change requires them",
        )
    if command := _command_from_task_files(target_root):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source=f"{_display_repo_source(target_root, inventory)} task file",
            reason="agent should confirm the task covers the changed surface",
        )
    if command := _command_from_ci_workflow(target_root):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source=f"{_display_repo_source(target_root, inventory)} CI workflow",
            reason="local reproduction may need adjustment if the CI command depends on setup steps",
        )
    if command := _command_from_text(verification_summary):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source="roadmap verification_summary",
            reason="verify that this remains task-specific before closeout",
        )
    if command := _command_from_docs(target_root):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source=_display_repo_source(target_root, inventory),
            reason="verify that this repo-documented command covers the changed surface",
        )
    if command := _python_test_command(target_root, target_artifacts):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source=f"{_display_repo_source(target_root, inventory)} Python test layout",
            reason="agent may narrow with specific test paths when available",
        )
    return VerificationGateProfile(
        status="unresolved",
        command="",
        source=_display_repo_source(target_root, inventory),
        reason=(
            "no concrete command was visible; generated plan must stay unresolved until an agent records "
            "an evidence-backed gate"
        ),
    )


def _plan_verification_gate_findings(
    report: RoadmapSynthesisReport | None,
    profile: VerificationGateProfile | None,
    apply: bool,
    *,
    slice_contract: RoadmapSliceContract | None = None,
) -> list[Finding]:
    if report is None:
        return []
    if _is_non_implementation_contract(slice_contract):
        return _plan_non_implementation_gate_findings(report, slice_contract, apply)
    prefix = "" if apply else "would "
    groups = _artifact_groups(tuple(report.target_artifacts))
    test_scope = groups["tests"]
    source_scope = groups["source"] or groups["other"]
    findings: list[Finding] = []
    if test_scope:
        findings.append(
            Finding(
                "info",
                "plan-verification-gate-target-tests",
                f"{prefix}render verification gate from target test artifact(s): {', '.join(test_scope)}",
                DEFAULT_PLAN_REL,
            )
        )
        if source_scope:
            findings.append(
                Finding(
                    "info",
                    "plan-adjacent-verification-ownership",
                    f"{prefix}include adjacent regression-test ownership in phase write_scope: {', '.join(test_scope)}",
                    DEFAULT_PLAN_REL,
                )
            )
        return findings
    if profile is None:
        return []
    if profile.status == "candidate":
        findings.append(
            Finding(
                "info",
                "plan-verification-gate-discovery",
                f"{prefix}render repo-visible verification candidate `{profile.command}` from {profile.source}",
                DEFAULT_PLAN_REL,
            )
        )
        if _profile_needs_adjacent_regression_scope(profile, tuple(report.target_artifacts)):
            findings.append(
                Finding(
                    "warn",
                    "plan-adjacent-verification-ownership",
                    f"{prefix}surface unresolved adjacent regression-test ownership because `{profile.command}` is broader than declared target_artifacts",
                    DEFAULT_PLAN_REL,
                )
            )
        return findings
    findings.append(
        Finding(
            "warn",
            "plan-verification-gate-unresolved",
            f"{prefix}render unresolved verification gate because {profile.reason}",
            DEFAULT_PLAN_REL,
        )
    )
    return findings


def _plan_non_implementation_gate_findings(
    report: RoadmapSynthesisReport,
    slice_contract: RoadmapSliceContract | None,
    apply: bool,
) -> list[Finding]:
    prefix = "" if apply else "would "
    deliverable_class = _contract_deliverable_class_for_frontmatter(slice_contract)
    output_artifacts = tuple(report.target_artifacts) or (_default_output_artifact_for_deliverable(_contract_deliverable_class(slice_contract)),)
    return [
        Finding(
            "info",
            "plan-non-implementation-contract",
            (
                f"{prefix}render work_class=non_implementation, deliverable_class={deliverable_class}, "
                f"implementation_allowed={str(_contract_implementation_allowed(slice_contract)).lower()}, "
                f"promotion_required={str(_contract_promotion_required(slice_contract)).lower()}"
            ),
            DEFAULT_PLAN_REL,
        ),
        Finding(
            "info",
            "plan-output-artifact-gate",
            (
                f"{prefix}render output-artifact verification for {_backticked_values(output_artifacts, '`<declare output artifact>`')}; "
                "product tests are not primary proof for non-implementation work"
            ),
            DEFAULT_PLAN_REL,
        ),
    ]


def _profile_needs_adjacent_regression_scope(
    profile: VerificationGateProfile,
    target_artifacts: tuple[str, ...],
) -> bool:
    command = profile.command.casefold()
    if "pytest" not in command:
        return False
    if any(_normalize_rel(target).casefold().startswith("tests/") for target in target_artifacts):
        return False
    return any(_normalize_rel(target).casefold().startswith("src/") or _normalize_rel(target).casefold().endswith(".py") for target in target_artifacts)


def _verification_target_root(inventory: Inventory) -> Path:
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.frontmatter.has_frontmatter else {}
    for key in ("product_source_root", "projection_root", "operating_root", "canonical_source_evidence_root"):
        raw = str(state_data.get(key) or "").strip()
        if not raw:
            continue
        candidate = Path(raw.replace("\\\\", "\\"))
        if not candidate.is_absolute():
            candidate = inventory.root / candidate
        if candidate.is_dir():
            return candidate
    return inventory.root


def _display_repo_source(target_root: Path, inventory: Inventory) -> str:
    try:
        if target_root.resolve() == inventory.root.resolve():
            return "target root"
    except OSError:
        pass
    return "product_source_root"


def _command_from_text(text: str) -> str:
    for candidate in re.findall(r"`([^`]+)`", text or ""):
        command = _clean_command_candidate(candidate)
        if command:
            return command
    return ""


def _command_from_docs(target_root: Path) -> str:
    for rel_path in ("README.md", "CONTRIBUTING.md", "docs/README.md", "docs/development.md", "docs/testing.md"):
        path = target_root / rel_path
        if not path.is_file():
            continue
        try:
            if command := _command_from_text(path.read_text(encoding="utf-8")):
                return command
        except OSError:
            continue
    return ""


def _command_from_package_scripts(target_root: Path, target_artifacts: tuple[str, ...]) -> str:
    package_json = target_root / "package.json"
    if not package_json.is_file():
        return ""
    try:
        package = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    scripts = package.get("scripts")
    if not isinstance(scripts, dict):
        return ""
    preferred = ("test", "typecheck", "lint", "build", "check")
    if _target_artifacts_look_js(target_artifacts):
        preferred = ("test", "typecheck", "lint", "build", "check")
    for script_name in preferred:
        if isinstance(scripts.get(script_name), str) and scripts[script_name].strip():
            return _package_manager_command(target_root, script_name)
    return ""


def _package_manager_command(target_root: Path, script_name: str) -> str:
    if (target_root / "pnpm-lock.yaml").is_file():
        return f"pnpm run {script_name}"
    if (target_root / "yarn.lock").is_file():
        return f"yarn {script_name}"
    if (target_root / "bun.lockb").is_file() or (target_root / "bun.lock").is_file():
        return f"bun run {script_name}"
    return f"npm run {script_name}"


def _command_from_task_files(target_root: Path) -> str:
    for filename, command_prefix in (
        ("Makefile", "make"),
        ("makefile", "make"),
        ("justfile", "just"),
        ("Justfile", "just"),
        ("Taskfile.yml", "task"),
        ("Taskfile.yaml", "task"),
    ):
        path = target_root / filename
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for target in ("test", "typecheck", "lint", "build", "check"):
            if re.search(rf"(?m)^{re.escape(target)}\s*:", text):
                return f"{command_prefix} {target}"
    return ""


def _command_from_ci_workflow(target_root: Path) -> str:
    workflow_dir = target_root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return ""
    for path in sorted(tuple(workflow_dir.glob("*.yml")) + tuple(workflow_dir.glob("*.yaml"))):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            match = re.search(r"\brun:\s*(.+?)\s*$", line)
            if not match:
                continue
            command = _clean_command_candidate(match.group(1).strip().strip("'\""))
            if command:
                return command
    return ""


def _python_test_command(target_root: Path, target_artifacts: tuple[str, ...]) -> str:
    has_python_layout = (target_root / "pyproject.toml").is_file() and (target_root / "tests").is_dir()
    if not has_python_layout:
        return ""
    if (target_root / "package.json").is_file() and _target_artifacts_look_js(target_artifacts):
        return ""
    return "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src uv run --no-project --with pytest pytest -q"


def _clean_command_candidate(candidate: str) -> str:
    command = re.sub(r"\s+", " ", str(candidate or "").strip())
    if not command or "\n" in command:
        return ""
    lowered = command.casefold()
    command_markers = (
        "pytest",
        "npm ",
        "pnpm ",
        "yarn ",
        "bun ",
        "make ",
        "just ",
        "task ",
        "tox",
        "nox",
        "ruff",
        "mypy",
    )
    intent_markers = ("test", "typecheck", "lint", "build", "check")
    if any(marker in lowered for marker in command_markers) and any(marker in lowered for marker in intent_markers):
        return command
    return ""


def _target_artifacts_look_js(target_artifacts: tuple[str, ...]) -> bool:
    js_suffixes = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
    js_names = ("package.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock")
    js_prefixes = ("apps/", "packages/", "web/", "frontend/")
    for target in target_artifacts:
        normalized = _normalize_rel(target).casefold()
        if normalized.endswith(js_suffixes) or normalized in js_names or normalized.startswith(js_prefixes):
            return True
    return False


def _recommended_phase_count_for_report(report: RoadmapSynthesisReport) -> int:
    return _recommended_phase_count_for_values(
        covered_count=len(report.covered_roadmap_items),
        target_count=len(report.target_artifacts),
        related_spec_count=len(report.related_specs),
        verification_summary_count=report.verification_summary_count,
        docs_update_count=getattr(report, "docs_update_count", 0),
    )


def _recommended_phase_count_for_values(
    *,
    covered_count: int,
    target_count: int,
    related_spec_count: int,
    verification_summary_count: int,
    docs_update_count: int = 0,
) -> int:
    pressure = 0
    if covered_count > 1:
        pressure += 1
    if target_count >= 4:
        pressure += 2
    elif target_count > 1:
        pressure += 1
    if related_spec_count > 1:
        pressure += 1
    if verification_summary_count > 0:
        pressure += 1
    if docs_update_count > 0:
        pressure += 2
    if pressure <= 1:
        return 1
    if pressure <= 2:
        return 2
    return 3


def _backticked_values(values: tuple[str, ...], fallback: str) -> str:
    rendered = ", ".join(f"`{value}`" for value in values if value)
    return rendered or fallback


def _plan_input_resolution_findings(resolution: PlanInputResolution, apply: bool) -> list[Finding]:
    if not resolution.candidate_title and not resolution.candidate_objective and not resolution.candidate_task:
        return []
    prefix = "" if apply else "would "
    findings: list[Finding] = []
    item_id = resolution.request.roadmap_item
    if resolution.derived_fields:
        findings.append(
            Finding(
                "info",
                "plan-roadmap-derived-input",
                f"{prefix}populate missing plan scaffold field candidate(s) from roadmap item {item_id!r}: {', '.join(resolution.derived_fields)}; explicit CLI input remains authoritative",
                DEFAULT_PLAN_REL,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "plan-roadmap-candidate-input",
                f"{prefix}report roadmap-derived plan input candidates for roadmap item {item_id!r}; explicit CLI input remains authoritative",
                DEFAULT_PLAN_REL,
            )
        )
    if resolution.candidate_objective:
        findings.append(
            Finding(
                "info",
                "plan-roadmap-candidate-objective",
                f"candidate objective: {_truncate_text(resolution.candidate_objective, 260)}",
                DEFAULT_PLAN_REL,
            )
        )
    if resolution.candidate_task:
        findings.append(
            Finding(
                "info",
                "plan-roadmap-candidate-task",
                f"candidate task: {_truncate_text(resolution.candidate_task, 360)}",
                DEFAULT_PLAN_REL,
            )
        )
    return findings


def plan_dry_run_findings(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    resolution = resolve_plan_request_from_roadmap(inventory, request)
    request = resolution.request
    findings = [
        Finding("info", "plan-dry-run", "plan proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    eligibility_errors = _plan_current_action_eligibility_errors(inventory, request)
    if eligibility_errors:
        findings.extend(_with_severity(eligibility_errors, "warn"))
        findings.append(Finding("info", "plan-validation-posture", "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing a plan"))
        return findings
    errors = _plan_preflight_errors(inventory, request)
    roadmap_plans, roadmap_errors = _plan_roadmap_plans(inventory, request)
    errors.extend(roadmap_errors)
    source_plans, source_errors = _plan_source_incubation_plans(inventory, request)
    errors.extend(source_errors)
    roadmap_item_ids = _plan_roadmap_item_ids(inventory, request)
    roadmap_evidence_findings = [
        *roadmap_source_incubation_evidence_findings(inventory, roadmap_item_ids),
        *roadmap_related_specs_evidence_findings(inventory, roadmap_item_ids),
        *roadmap_human_review_gate_findings(inventory, roadmap_item_ids),
        *roadmap_batch_slice_gate_findings(inventory, roadmap_item_ids, route="plan", source=DEFAULT_PLAN_REL, apply=False),
        *roadmap_compacted_dependency_archive_evidence_findings(inventory, roadmap_item_ids),
    ]
    findings.append(Finding("info", "plan-target", f"active plan target: {DEFAULT_PLAN_REL}; write preview requires validation to pass", DEFAULT_PLAN_REL))
    findings.append(
        Finding(
            "info",
            "plan-lifecycle",
            "project-state lifecycle target fields: operating_mode, plan_status, active_plan, active_phase, phase_status; write preview requires validation to pass",
            inventory.state.rel_path if inventory.state else "project/project-state.md",
        )
    )
    findings.extend(_plan_input_resolution_findings(resolution, apply=False))
    if roadmap_plans:
        findings.extend(_plan_roadmap_findings(roadmap_plans, apply=False))
        slice_contract = _plan_slice_contract(inventory, request)
        if slice_contract:
            findings.extend(_plan_slice_contract_findings(slice_contract, apply=False))
        if request.only_requested_item:
            findings.append(_plan_only_requested_item_finding(request, apply=False))
        synthesis_report = _plan_synthesis_report(inventory, request, slice_contract)
        if synthesis_report:
            findings.extend(_plan_synthesis_findings(inventory, synthesis_report, apply=False))
            verification_profile = _repo_verification_gate_profile(inventory, request, synthesis_report, slice_contract)
            findings.extend(_plan_verification_gate_findings(synthesis_report, verification_profile, apply=False, slice_contract=slice_contract))
    if source_plans:
        findings.extend(_plan_source_incubation_findings(source_plans, apply=False))
    findings.extend(roadmap_evidence_findings)
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(Finding("info", "plan-validation-posture", "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing a plan"))
        return findings
    projected_state_text = ""
    if inventory.state:
        plan_text = _render_plan_text_for_request(inventory, request)
        lifecycle = _plan_lifecycle_values(_plan_active_phase_from_text(plan_text))
        projected_state_text = sync_current_focus_block(_update_frontmatter_scalars(inventory.state.content, lifecycle))
        route_writes = _plan_route_write_evidence(inventory, plan_text, projected_state_text, roadmap_plans, source_plans)
        findings.extend(route_write_findings("plan-route-write", route_writes, apply=False))
        findings.extend(route_reference_transaction_guard_findings(inventory, route_writes, apply=False))
    findings.extend(_boundary_findings())
    findings.append(Finding("info", "plan-docs-decision", f"generated plan frontmatter starts with docs_decision={DEFAULT_DOCS_DECISION!r}", DEFAULT_PLAN_REL))
    findings.append(
        Finding(
            "info",
            "plan-execution-policy",
            "generated plan defaults to current-phase-only execution with auto_continue=false and repo-visible stop_conditions",
            DEFAULT_PLAN_REL,
        )
    )
    if inventory.state:
        findings.extend(state_compaction_dry_run_findings(inventory, projected_state_text))
    findings.append(Finding("info", "plan-validation-posture", "apply would write only the active plan, project-state lifecycle frontmatter, and safe state-history compaction in an eligible live operating root"))
    return findings


def plan_apply_findings(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    resolution = resolve_plan_request_from_roadmap(inventory, request)
    request = resolution.request
    errors = _plan_current_action_eligibility_errors(inventory, request)
    if errors:
        return errors
    errors = _plan_preflight_errors(inventory, request)
    roadmap_plans, roadmap_errors = _plan_roadmap_plans(inventory, request)
    errors.extend(roadmap_errors)
    source_plans, source_errors = _plan_source_incubation_plans(inventory, request)
    errors.extend(source_errors)
    roadmap_item_ids = _plan_roadmap_item_ids(inventory, request)
    roadmap_evidence_findings = [
        *roadmap_source_incubation_evidence_findings(inventory, roadmap_item_ids),
        *roadmap_related_specs_evidence_findings(inventory, roadmap_item_ids),
        *roadmap_human_review_gate_findings(inventory, roadmap_item_ids),
        *roadmap_batch_slice_gate_findings(inventory, roadmap_item_ids, route="plan", source=DEFAULT_PLAN_REL, apply=True),
        *roadmap_compacted_dependency_archive_evidence_findings(inventory, roadmap_item_ids),
    ]
    if errors:
        return [
            *roadmap_evidence_findings,
            *errors,
        ]

    state = inventory.state
    assert state is not None
    plan_path = inventory.root / DEFAULT_PLAN_REL
    source_incubation = _roadmap_source_incubation(inventory, request.roadmap_item)
    slice_contract = _plan_slice_contract(inventory, request)
    synthesis_report = _plan_synthesis_report(inventory, request, slice_contract)
    verification_profile = _repo_verification_gate_profile(inventory, request, synthesis_report, slice_contract)
    plan_text = render_implementation_plan(
        request,
        source_incubation=source_incubation,
        slice_contract=slice_contract,
        synthesis_report=synthesis_report,
        verification_profile=verification_profile,
    )
    lifecycle = _plan_lifecycle_values(_plan_active_phase_from_text(plan_text))
    state_text = sync_current_focus_block(_update_frontmatter_scalars(state.content, lifecycle))
    plan_tmp = plan_path.with_name(f".{plan_path.name}.plan.tmp")
    state_tmp = state.path.with_name(f".{state.path.name}.plan.tmp")
    plan_backup = plan_path.with_name(f".{plan_path.name}.plan.backup")
    state_backup = state.path.with_name(f".{state.path.name}.plan.backup")
    roadmap_target_path = roadmap_plans[-1].target_path if roadmap_plans else None
    roadmap_tmp = (
        roadmap_target_path.with_name(f".{roadmap_target_path.name}.plan.tmp")
        if roadmap_target_path and _plan_roadmap_has_changes(roadmap_plans)
        else None
    )
    roadmap_backup = roadmap_target_path.with_name(f".{roadmap_target_path.name}.plan.backup") if roadmap_target_path else None
    source_plan_tmps = tuple(
        (_plan_source_incubation_tmp(plan), _plan_source_incubation_backup(plan), plan)
        for plan in source_plans
        if plan.current_text != plan.updated_text
    )
    for candidate, label in (
        (plan_tmp, "temporary plan write path"),
        (state_tmp, "temporary state write path"),
        (plan_backup, "temporary plan backup path"),
        (state_backup, "temporary state backup path"),
        (roadmap_tmp, "temporary roadmap write path"),
        (roadmap_backup if roadmap_tmp else None, "temporary roadmap backup path"),
    ):
        if candidate and candidate.exists():
            return [Finding("error", "plan-refused", f"{label} already exists: {candidate.relative_to(inventory.root).as_posix()}")]
    for source_tmp, source_backup, _plan in source_plan_tmps:
        for candidate, label in (
            (source_tmp, "temporary source-incubation relationship write path"),
            (source_backup, "temporary source-incubation relationship backup path"),
        ):
            if candidate and candidate.exists():
                return [Finding("error", "plan-refused", f"{label} already exists: {candidate.relative_to(inventory.root).as_posix()}")]

    existed = plan_path.exists()
    operations: list[AtomicFileWrite] = [
        AtomicFileWrite(plan_path, plan_tmp, plan_text, plan_backup),
        AtomicFileWrite(state.path, state_tmp, state_text, state_backup),
    ]
    if roadmap_tmp and roadmap_target_path and roadmap_backup and roadmap_plans:
        operations.append(AtomicFileWrite(roadmap_target_path, roadmap_tmp, roadmap_plans[-1].updated_text, roadmap_backup))
    for source_tmp, source_backup, source_plan in source_plan_tmps:
        operations.append(AtomicFileWrite(source_plan.target_path, source_tmp, source_plan.updated_text, source_backup))
    route_writes = _plan_route_write_evidence(
        inventory,
        plan_text,
        state_text,
        roadmap_plans,
        source_plans,
    )
    guard_findings = route_reference_transaction_guard_findings(inventory, route_writes, apply=True)
    if any(finding.severity == "error" for finding in guard_findings):
        return [
            *guard_findings,
            Finding(
                "info",
                "plan-validation-posture",
                "plan apply refused before writing files; review unresolved required route references, then rerun dry-run",
                DEFAULT_PLAN_REL,
            ),
        ]
    route_write_evidence = route_write_findings("plan-route-write", route_writes, apply=True)
    try:
        cleanup_warnings = apply_file_transaction(operations)
    except FileTransactionError as exc:
        return [Finding("error", "plan-refused", f"plan apply failed before all target writes completed: {exc}", DEFAULT_PLAN_REL)]

    action = "updated existing active plan" if existed else "created active plan"
    findings = [
        Finding("info", "plan-apply", "plan apply started"),
        _root_posture_finding(inventory),
        Finding("info", "plan-written", action, DEFAULT_PLAN_REL),
        Finding("info", "plan-lifecycle-updated", "updated project-state lifecycle frontmatter: operating_mode, plan_status, active_plan, active_phase, phase_status", state.rel_path),
        Finding("info", "plan-current-focus-updated", "updated project-state Current Focus managed block from lifecycle frontmatter", state.rel_path),
        *route_write_evidence,
        *guard_findings,
        Finding("info", "plan-docs-decision", f"generated plan frontmatter starts with docs_decision={DEFAULT_DOCS_DECISION!r}", DEFAULT_PLAN_REL),
        Finding(
            "info",
            "plan-execution-policy",
            "generated plan defaults to current-phase-only execution with auto_continue=false and repo-visible stop_conditions",
            DEFAULT_PLAN_REL,
        ),
        *_boundary_findings(),
        Finding("info", "plan-validation-posture", "run check after apply to verify lifecycle state, active-plan validation, and compact operating memory posture"),
    ]
    findings.extend(_plan_input_resolution_findings(resolution, apply=True))
    findings.extend(roadmap_evidence_findings)
    if roadmap_plans:
        findings.extend(_plan_roadmap_findings(roadmap_plans, apply=True))
    if source_plans:
        findings.extend(_plan_source_incubation_findings(source_plans, apply=True))
    if slice_contract:
        findings.extend(_plan_slice_contract_findings(slice_contract, apply=True))
    if request.only_requested_item:
        findings.append(_plan_only_requested_item_finding(request, apply=True))
    if synthesis_report:
        findings.extend(_plan_synthesis_findings(inventory, synthesis_report, apply=True))
        findings.extend(_plan_verification_gate_findings(synthesis_report, verification_profile, apply=True, slice_contract=slice_contract))
    if request.roadmap_item:
        findings.append(
            Finding(
                "info",
                "plan-relationship-frontmatter",
                "active plan frontmatter records related_roadmap_item, source_incubation or related_incubation provenance, and slice metadata when the roadmap item provides it",
                DEFAULT_PLAN_REL,
            )
        )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "plan-backup-cleanup", warning, DEFAULT_PLAN_REL))
    findings.extend(state_compaction_apply_findings(inventory, state.path.read_text(encoding="utf-8")))
    return findings


def plan_cancel_dry_run_findings(inventory: Inventory, request: PlanCancelRequest) -> list[Finding]:
    findings = [
        Finding("info", "plan-cancel-dry-run", "plan activation cancel/rollback proposal only; no files were written"),
        _root_posture_finding(inventory),
        Finding(
            "info",
            "plan-cancel-boundary",
            "plan-cancel can clear accidental activation and optionally restore one roadmap item to accepted; it cannot close out, archive, repair, stage, commit, or open the next plan",
            DEFAULT_PLAN_REL,
        ),
    ]
    errors = _plan_cancel_preflight_errors(inventory, request, apply=False)
    roadmap_plans, roadmap_errors = _plan_cancel_roadmap_plans(inventory, request)
    source_plans, source_errors = _plan_cancel_source_incubation_plans(inventory)
    errors.extend(roadmap_errors)
    errors.extend(source_errors)
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(Finding("info", "plan-cancel-validation-posture", "dry-run refused before apply; fix refusal reasons and rerun plan-cancel --dry-run"))
        return findings
    source_hash = _plan_cancel_activation_source_hash(inventory, roadmap_plans, source_plans)
    route_writes = _plan_cancel_route_writes(inventory, request, roadmap_plans, source_plans)
    findings.extend(route_write_findings("plan-cancel-route-write", route_writes, apply=False))
    findings.extend(
        route_reference_transaction_guard_findings(
            inventory,
            tuple(write for write in route_writes if write.after_text is not None),
            apply=False,
        )
    )
    findings.append(
        Finding(
            "info",
            "plan-cancel-source-hash",
            f"current activation source sha256: {source_hash}; after review, apply with --source-hash {source_hash}",
            DEFAULT_PLAN_REL,
        )
    )
    if roadmap_plans:
        findings.append(Finding("info", "plan-cancel-roadmap-restore", f"would restore roadmap item {request.roadmap_item!r} to accepted and clear active related_plan metadata", ROADMAP_REL))
    if source_plans:
        source_list = ", ".join(plan.source_rel for plan in source_plans)
        findings.append(Finding("info", "plan-cancel-source-incubation-detach", f"would clear active related_plan metadata from source incubation: {source_list}"))
    findings.append(Finding("info", "plan-cancel-validation-posture", "apply would perform a bounded activation cancellation with route-write evidence"))
    return findings


def plan_cancel_apply_findings(inventory: Inventory, request: PlanCancelRequest) -> list[Finding]:
    errors = _plan_cancel_preflight_errors(inventory, request, apply=True)
    roadmap_plans, roadmap_errors = _plan_cancel_roadmap_plans(inventory, request)
    source_plans, source_errors = _plan_cancel_source_incubation_plans(inventory)
    errors.extend(roadmap_errors)
    errors.extend(source_errors)
    if errors:
        return errors
    current_source_hash = _plan_cancel_activation_source_hash(inventory, roadmap_plans, source_plans)
    errors.extend(_plan_cancel_source_hash_errors(request, current_source_hash))
    if errors:
        return errors

    state = inventory.state
    assert state is not None
    plan_path = inventory.root / DEFAULT_PLAN_REL
    state_text = _plan_cancel_state_text(state.content)
    route_writes = _plan_cancel_route_writes(inventory, request, roadmap_plans, source_plans)
    guard_findings = route_reference_transaction_guard_findings(
        inventory,
        tuple(write for write in route_writes if write.after_text is not None),
        apply=True,
    )
    if any(finding.severity == "error" for finding in guard_findings):
        return [
            *guard_findings,
            Finding("info", "plan-cancel-validation-posture", "plan-cancel apply refused before writing files; review unresolved required route references"),
        ]

    operations = [
        AtomicFileWrite(
            state.path,
            state.path.with_name(f".{state.path.name}.plan-cancel.tmp"),
            state_text,
            state.path.with_name(f".{state.path.name}.plan-cancel.backup"),
        )
    ]
    if not request.keep_plan and plan_path.exists():
        operations.append(AtomicFileDelete(plan_path, plan_path.with_name(f".{plan_path.name}.plan-cancel.backup")))
    if roadmap_plans and roadmap_plans[-1].current_text != roadmap_plans[-1].updated_text:
        roadmap_path = roadmap_plans[-1].target_path
        operations.append(
            AtomicFileWrite(
                roadmap_path,
                roadmap_path.with_name(f".{roadmap_path.name}.plan-cancel.tmp"),
                roadmap_plans[-1].updated_text,
                roadmap_path.with_name(f".{roadmap_path.name}.plan-cancel.backup"),
            )
        )
    for source_plan in source_plans:
        if source_plan.current_text == source_plan.updated_text:
            continue
        operations.append(
            AtomicFileWrite(
                source_plan.target_path,
                source_plan.target_path.with_name(f".{source_plan.target_path.name}.plan-cancel.tmp"),
                source_plan.updated_text,
                source_plan.target_path.with_name(f".{source_plan.target_path.name}.plan-cancel.backup"),
            )
        )
    try:
        cleanup_warnings = apply_file_transaction(operations)
    except FileTransactionError as exc:
        return [Finding("error", "plan-cancel-refused", f"plan-cancel apply failed before all target writes completed: {exc}", DEFAULT_PLAN_REL)]

    findings = [
        Finding("info", "plan-cancel-apply", "plan activation cancel/rollback apply started"),
        _root_posture_finding(inventory),
        Finding("info", "plan-cancel-lifecycle-updated", "cleared project-state active plan pointer and set plan_status to none", state.rel_path),
        *route_write_findings("plan-cancel-route-write", route_writes, apply=True),
        *guard_findings,
        Finding(
            "info",
            "plan-cancel-boundary",
            "plan-cancel performed no closeout, archive, repair, staging, commit, rollback of product files, or next-plan opening",
            DEFAULT_PLAN_REL,
        ),
        Finding("info", "plan-cancel-validation-posture", "run check after apply to verify lifecycle state and route references"),
    ]
    if roadmap_plans:
        findings.append(Finding("info", "plan-cancel-roadmap-restore", f"restored roadmap item {request.roadmap_item!r} to accepted and cleared active related_plan metadata", ROADMAP_REL))
    if source_plans:
        source_list = ", ".join(plan.source_rel for plan in source_plans)
        findings.append(Finding("info", "plan-cancel-source-incubation-detach", f"cleared active related_plan metadata from source incubation: {source_list}"))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "plan-cancel-backup-cleanup", warning, DEFAULT_PLAN_REL))
    return findings


def _render_plan_text_for_request(inventory: Inventory, request: PlanRequest) -> str:
    source_incubation = _roadmap_source_incubation(inventory, request.roadmap_item)
    slice_contract = _plan_slice_contract(inventory, request)
    synthesis_report = _plan_synthesis_report(inventory, request, slice_contract)
    verification_profile = _repo_verification_gate_profile(inventory, request, synthesis_report, slice_contract)
    return render_implementation_plan(
        request,
        source_incubation=source_incubation,
        slice_contract=slice_contract,
        synthesis_report=synthesis_report,
        verification_profile=verification_profile,
    )


def _plan_cancel_preflight_errors(inventory: Inventory, request: PlanCancelRequest, *, apply: bool) -> list[Finding]:
    errors: list[Finding] = []
    if request.source_hash and not apply:
        errors.append(Finding("error", "plan-cancel-refused", "--source-hash is apply-only; dry-run reports the current activation source hash", DEFAULT_PLAN_REL))
    if request.source_hash and not re.fullmatch(r"[0-9a-f]{64}", request.source_hash):
        errors.append(Finding("error", "plan-cancel-refused", "--source-hash must be a full lowercase sha256 hex digest from plan-cancel dry-run", DEFAULT_PLAN_REL))
    if inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "plan-cancel-refused", f"target root kind is {inventory.root_kind}; plan-cancel requires a live operating root"))
    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "plan-cancel-refused", "project-state.md is missing", "project/project-state.md"))
        return errors
    if not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "plan-cancel-refused", "project-state.md frontmatter is required", state.rel_path))
    if state.frontmatter.errors:
        errors.append(Finding("error", "plan-cancel-refused", "project-state.md frontmatter is malformed", state.rel_path))
    if not state.path.is_file():
        errors.append(Finding("error", "plan-cancel-refused", "project-state.md is not a regular file", state.rel_path))
    if state.path.is_symlink():
        errors.append(Finding("error", "plan-cancel-refused", "project-state.md is a symlink", state.rel_path))
    data = state.frontmatter.data
    if str(data.get("plan_status") or "").strip().casefold() != "active":
        errors.append(Finding("error", "plan-cancel-refused", "plan_status is not active; there is no active activation to cancel", state.rel_path))
    phase_status = str(data.get("phase_status") or "").strip().casefold()
    if phase_status and phase_status != "pending":
        errors.append(
            Finding(
                "error",
                "plan-cancel-refused",
                f"phase_status is {phase_status!r}; simple activation cancel is allowed only for pending plans before implementation evidence exists",
                state.rel_path,
            )
        )
    active_plan = _normalize_rel(str(data.get("active_plan") or DEFAULT_PLAN_REL))
    if active_plan and active_plan != DEFAULT_PLAN_REL:
        errors.append(Finding("error", "plan-cancel-refused", f"active_plan must be {DEFAULT_PLAN_REL} for this bounded rail; got {active_plan}", state.rel_path))
    plan_path = inventory.root / DEFAULT_PLAN_REL
    if plan_path.exists():
        if plan_path.is_symlink():
            errors.append(Finding("error", "plan-cancel-refused", "active plan path is a symlink", DEFAULT_PLAN_REL))
        elif not plan_path.is_file():
            errors.append(Finding("error", "plan-cancel-refused", "active plan path exists but is not a regular file", DEFAULT_PLAN_REL))
    elif not request.keep_plan:
        errors.append(Finding("error", "plan-cancel-refused", "active plan file is missing; use writeback/repair review instead of deleting an absent route", DEFAULT_PLAN_REL))
    errors.extend(_plan_cancel_evidence_errors(inventory))
    return errors


def _plan_cancel_roadmap_plans(inventory: Inventory, request: PlanCancelRequest) -> tuple[tuple[RoadmapPlan, ...], list[Finding]]:
    if not request.roadmap_item:
        return (), []
    roadmap_request = make_roadmap_request(
        "update",
        request.roadmap_item,
        status="accepted",
        clear_fields=["related_plan"],
    )
    return roadmap_plans_for_requests(inventory, (roadmap_request,))


def _plan_cancel_source_incubation_plans(inventory: Inventory) -> tuple[tuple[RelationshipUpdatePlan, ...], list[Finding]]:
    active_plan = inventory.active_plan_surface
    if active_plan is None or not active_plan.exists or not active_plan.frontmatter.has_frontmatter or active_plan.frontmatter.errors:
        return (), []
    plans: list[RelationshipUpdatePlan] = []
    errors: list[Finding] = []
    for source_rel in _active_plan_source_incubation_rels(active_plan.frontmatter.data):
        source_path = inventory.root / source_rel
        if not source_path.is_file() or source_path.is_symlink():
            continue
        try:
            source_text = source_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _frontmatter_scalar_value(source_text, "related_plan") != DEFAULT_PLAN_REL:
            continue
        plan, plan_errors = relationship_update_plan(
            inventory,
            source_rel,
            {},
            clear_fields=("related_plan",),
        )
        errors.extend(plan_errors)
        if plan is not None:
            plans.append(plan)
    return tuple(plans), errors


def _plan_cancel_route_writes(
    inventory: Inventory,
    request: PlanCancelRequest,
    roadmap_plans: tuple[RoadmapPlan, ...],
    source_plans: tuple[RelationshipUpdatePlan, ...],
) -> tuple[RouteWriteEvidence, ...]:
    state = inventory.state
    assert state is not None
    writes = [
        RouteWriteEvidence(state.rel_path, state.content, _plan_cancel_state_text(state.content)),
    ]
    plan_path = inventory.root / DEFAULT_PLAN_REL
    if not request.keep_plan and plan_path.is_file():
        writes.append(RouteWriteEvidence(DEFAULT_PLAN_REL, plan_path.read_text(encoding="utf-8"), None))
    if roadmap_plans:
        plan = roadmap_plans[-1]
        writes.append(RouteWriteEvidence(plan.target_rel, plan.current_text, plan.updated_text))
    writes.extend(RouteWriteEvidence(plan.target_rel, plan.current_text, plan.updated_text) for plan in source_plans)
    return tuple(writes)


def _plan_cancel_source_hash_errors(request: PlanCancelRequest, current_source_hash: str) -> list[Finding]:
    if not request.source_hash:
        return [
            Finding(
                "error",
                "plan-cancel-refused",
                f"--source-hash is required for plan-cancel apply; rerun dry-run and retry with --source-hash {current_source_hash}",
                DEFAULT_PLAN_REL,
            )
        ]
    if request.source_hash != current_source_hash:
        return [
            Finding(
                "error",
                "plan-cancel-refused",
                f"activation source hash changed after review; expected {request.source_hash}, current {current_source_hash}; rerun dry-run before apply",
                DEFAULT_PLAN_REL,
            )
        ]
    return []


def _plan_cancel_activation_source_hash(
    inventory: Inventory,
    roadmap_plans: tuple[RoadmapPlan, ...],
    source_plans: tuple[RelationshipUpdatePlan, ...],
) -> str:
    entries: list[tuple[str, str]] = []
    if inventory.state:
        entries.append((inventory.state.rel_path, inventory.state.content))
    plan_path = inventory.root / DEFAULT_PLAN_REL
    plan_text = plan_path.read_text(encoding="utf-8") if plan_path.is_file() else ""
    entries.append((DEFAULT_PLAN_REL, plan_text))
    if roadmap_plans:
        entries.append((roadmap_plans[-1].target_rel, roadmap_plans[-1].current_text))
    entries.extend((plan.source_rel, plan.current_text) for plan in source_plans)
    digest = hashlib.sha256()
    for rel_path, text in entries:
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _plan_cancel_evidence_errors(inventory: Inventory) -> list[Finding]:
    state_data = inventory.state.frontmatter.data if inventory.state else {}
    execution_slice = _normalized_item_id(str(state_data.get("execution_slice") or ""))
    errors: list[Finding] = []
    errors.extend(_plan_cancel_session_active_work_errors(inventory))
    errors.extend(_plan_cancel_work_claim_errors(inventory, execution_slice))
    errors.extend(_plan_cancel_agent_run_errors(inventory))
    errors.extend(_plan_cancel_verification_evidence_errors(inventory))
    return errors


def _plan_cancel_session_active_work_errors(inventory: Inventory) -> list[Finding]:
    records_dir = inventory.root / "project/verification/session-active-work"
    if not records_dir.is_dir():
        return []
    errors: list[Finding] = []
    for path in sorted(records_dir.glob("*.json")):
        rel_path = _normalize_rel(_path_relative_to_root(inventory.root, path))
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(data, dict):
            continue
        status = str(data.get("status") or "").strip().casefold()
        active_plan = _normalize_rel(str(data.get("active_plan") or ""))
        if status in {"active", "blocked"} and active_plan == DEFAULT_PLAN_REL:
            errors.append(
                Finding(
                    "error",
                    "plan-cancel-refused",
                    f"session active work evidence references {DEFAULT_PLAN_REL}; simple cancel requires a reviewed recovery path",
                    rel_path,
                )
            )
    return errors


def _plan_cancel_work_claim_errors(inventory: Inventory, execution_slice: str) -> list[Finding]:
    records_dir = inventory.root / "project/verification/work-claims"
    if not records_dir.is_dir():
        return []
    errors: list[Finding] = []
    for path in sorted(records_dir.glob("*.json")):
        rel_path = _normalize_rel(_path_relative_to_root(inventory.root, path))
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(data, dict):
            continue
        status = str(data.get("status") or "").strip().casefold()
        if status != "active":
            continue
        claim_slice = _normalized_item_id(str(data.get("execution_slice") or ""))
        refs = _plan_cancel_flat_refs(data.get("claimed_routes"), data.get("claimed_paths"), data.get("claimed_resources"))
        if DEFAULT_PLAN_REL in refs or (execution_slice and claim_slice == execution_slice):
            errors.append(
                Finding(
                    "error",
                    "plan-cancel-refused",
                    "active work claim evidence overlaps the active activation; release or recover the claim before simple cancel",
                    rel_path,
                )
            )
    return errors


def _plan_cancel_agent_run_errors(inventory: Inventory) -> list[Finding]:
    records_dir = inventory.root / "project/verification/agent-runs"
    if not records_dir.is_dir():
        return []
    plan_path = inventory.root / DEFAULT_PLAN_REL
    plan_hash = _sha256_text(plan_path.read_text(encoding="utf-8")) if plan_path.is_file() else ""
    errors: list[Finding] = []
    for path in sorted(records_dir.glob("*.md")):
        rel_path = _normalize_rel(_path_relative_to_root(inventory.root, path))
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        data = parse_frontmatter(text).data
        source_hashes = tuple(str(item) for item in _field_list(data.get("source_hashes")))
        matching_plan_hash = bool(plan_hash and any(DEFAULT_PLAN_REL in item and plan_hash in item for item in source_hashes))
        refs = _plan_cancel_flat_refs(
            data.get("input_refs"),
            data.get("output_refs"),
            data.get("changed_files"),
            data.get("verification_refs"),
        )
        if matching_plan_hash or DEFAULT_PLAN_REL in refs:
            errors.append(
                Finding(
                    "error",
                    "plan-cancel-refused",
                    "agent-run evidence references the active activation; simple cancel requires reviewed recovery instead of deleting the plan route",
                    rel_path,
                )
            )
    return errors


def _plan_cancel_verification_evidence_errors(inventory: Inventory) -> list[Finding]:
    verification_dir = inventory.root / "project/verification"
    if not verification_dir.is_dir():
        return []
    errors: list[Finding] = []
    for path in sorted(verification_dir.glob("*.md")):
        rel_path = _normalize_rel(_path_relative_to_root(inventory.root, path))
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        data = parse_frontmatter(text).data
        refs = _plan_cancel_flat_refs(
            data.get("source_plan"),
            data.get("active_plan"),
            data.get("related_plan"),
            data.get("input_refs"),
            data.get("verification_refs"),
        )
        if DEFAULT_PLAN_REL in refs:
            errors.append(
                Finding(
                    "error",
                    "plan-cancel-refused",
                    "verification evidence references the active activation; simple cancel requires reviewed recovery instead of deleting the plan route",
                    rel_path,
                )
            )
    return errors


def _plan_cancel_flat_refs(*values: object) -> set[str]:
    refs: set[str] = set()
    for value in values:
        for item in _field_list(value):
            normalized = _normalize_rel(item.split(" sha256=", 1)[0])
            if normalized:
                refs.add(normalized)
    return refs


def _path_relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plan_cancel_state_text(text: str) -> str:
    updates = {
        "plan_status": "none",
        "active_plan": "",
        "active_phase": "",
        "phase_status": "",
    }
    return sync_current_focus_block(_update_frontmatter_scalars(text, updates))


def _plan_lifecycle_values(active_phase: str | None = None) -> dict[str, str]:
    return {
        "operating_mode": "plan",
        "plan_status": "active",
        "active_plan": DEFAULT_PLAN_REL,
        "active_phase": _normalized_note(active_phase) or DEFAULT_ACTIVE_PHASE,
        "phase_status": DEFAULT_PHASE_STATUS,
    }


def _plan_active_phase_from_text(plan_text: str) -> str:
    match = re.search(r'^active_phase:\s*"([^"]+)"\s*$', plan_text, flags=re.MULTILINE)
    return _normalized_note(match.group(1)) if match else DEFAULT_ACTIVE_PHASE


def _plan_route_write_evidence(
    inventory: Inventory,
    plan_text: str,
    state_text: str,
    roadmap_plans: tuple[RoadmapPlan, ...],
    source_plans: tuple[RelationshipUpdatePlan, ...],
) -> tuple[RouteWriteEvidence, ...]:
    writes = [
        RouteWriteEvidence(DEFAULT_PLAN_REL, _existing_plan_text(inventory), plan_text),
    ]
    if inventory.state:
        writes.append(RouteWriteEvidence(inventory.state.rel_path, inventory.state.content, state_text))
    if roadmap_plans:
        writes.append(RouteWriteEvidence(roadmap_plans[-1].target_rel, roadmap_plans[0].current_text, roadmap_plans[-1].updated_text))
    writes.extend(
        RouteWriteEvidence(plan.target_rel, plan.current_text, plan.updated_text)
        for plan in source_plans
    )
    return tuple(writes)


def _existing_plan_text(inventory: Inventory) -> str | None:
    plan = inventory.active_plan_surface
    if plan and plan.exists:
        return plan.content
    path = inventory.root / DEFAULT_PLAN_REL
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _plan_preflight_errors(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    errors: list[Finding] = []
    if not request.title:
        errors.append(Finding("error", "plan-refused", "--title is required when it cannot be derived from --roadmap-item"))
    if not request.objective:
        errors.append(Finding("error", "plan-refused", "--objective is required when it cannot be derived from --roadmap-item"))
    dangerous = _dangerous_input_reason(" ".join(part for part in (request.title, request.objective, request.task) if part))
    if dangerous:
        errors.append(Finding("error", "plan-refused", dangerous))
    if request.only_requested_item and not request.roadmap_item:
        errors.append(Finding("error", "plan-refused", "--only-requested-item requires --roadmap-item"))
    if request.roadmap_item:
        next_safe_command = roadmap_plan_scope_next_safe_command(request.roadmap_item)
        for blocker in roadmap_plan_scope_blockers(inventory, request.roadmap_item):
            errors.append(
                Finding(
                    "error",
                    "plan-target-artifacts-refused",
                    f"{blocker}; next_safe_command={next_safe_command}",
                    ROADMAP_REL,
                )
            )
        promotion_next_safe_command = roadmap_plan_deliverable_class_next_safe_command(request.roadmap_item)
        for blocker in roadmap_plan_deliverable_class_blockers(inventory, request.roadmap_item):
            errors.append(
                Finding(
                    "error",
                    "plan-deliverable-class-refused",
                    f"{blocker}; next_safe_command={promotion_next_safe_command}",
                    ROADMAP_REL,
                )
            )

    if inventory.root_kind == "product_source_fixture":
        errors.append(Finding("error", "plan-refused", "target is a product-source compatibility fixture; plan --apply is refused", DEFAULT_PLAN_REL))
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(Finding("error", "plan-refused", "target is fallback/archive or generated-output evidence; plan --apply is refused", DEFAULT_PLAN_REL))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "plan-refused", f"target root kind is {inventory.root_kind}; plan requires a live operating root"))

    manifest_plan = str(inventory.manifest.get("memory", {}).get("plan_file", DEFAULT_PLAN_REL)) if isinstance(inventory.manifest, dict) else DEFAULT_PLAN_REL
    if _normalize_rel(manifest_plan) != DEFAULT_PLAN_REL:
        errors.append(Finding("error", "plan-refused", f"non-default manifest plan_file is refused for plan apply: {manifest_plan}", inventory.manifest_surface.rel_path if inventory.manifest_surface else None))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "plan-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "plan-refused", "project-state.md frontmatter is required for plan apply", state.rel_path))
    elif state.frontmatter.errors:
        errors.append(Finding("error", "plan-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "plan-refused", "project-state.md is not a regular file", state.rel_path))
    elif state.path.is_symlink():
        errors.append(Finding("error", "plan-refused", "project-state.md is a symlink", state.rel_path))

    plan_path = inventory.root / DEFAULT_PLAN_REL
    if _path_escapes_root(inventory.root, plan_path):
        errors.append(Finding("error", "plan-refused", "active plan path escapes the target root", DEFAULT_PLAN_REL))
    for parent in _parents_between(inventory.root, plan_path.parent):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "plan-refused", f"active plan directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "plan-refused", f"active plan directory contains a non-directory segment: {rel}", rel))
    if plan_path.exists():
        if plan_path.is_symlink():
            errors.append(Finding("error", "plan-refused", "active plan target is a symlink", DEFAULT_PLAN_REL))
        elif not plan_path.is_file():
            errors.append(Finding("error", "plan-refused", "active plan target exists but is not a regular file", DEFAULT_PLAN_REL))

    if state and state.exists and state.frontmatter.has_frontmatter:
        data = state.frontmatter.data
        plan_status = str(data.get("plan_status") or "")
        active_plan = str(data.get("active_plan") or "")
        if plan_status == "active":
            if _normalize_rel(active_plan) != DEFAULT_PLAN_REL:
                errors.append(Finding("error", "plan-refused", f"active_plan must be {DEFAULT_PLAN_REL} for plan update; got {active_plan or '<empty>'}", state.rel_path))
            if not request.update_active:
                errors.append(Finding("error", "plan-refused", "an active implementation plan already exists; pass --update-active to replace the active plan scaffold", state.rel_path))
            elif not plan_path.exists():
                errors.append(Finding("error", "plan-refused", "active plan update requested but the active plan file is missing", DEFAULT_PLAN_REL))
        elif plan_status not in {"", "none"}:
            errors.append(Finding("error", "plan-refused", f"plan_status is {plan_status!r}; expected active or none before plan apply", state.rel_path))
        elif active_plan:
            errors.append(Finding("error", "plan-refused", "active_plan is set while plan_status is not active", state.rel_path))
        elif plan_path.exists():
            errors.append(Finding("error", "plan-refused", "stale implementation plan exists while plan_status is not active", DEFAULT_PLAN_REL))
        elif request.update_active:
            errors.append(Finding("error", "plan-refused", "--update-active requires plan_status active and an existing active plan", state.rel_path))
    return errors


def _plan_current_action_eligibility_errors(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    if not request.roadmap_item:
        return []
    errors: list[Finding] = []
    for item_id in _plan_roadmap_item_ids(inventory, request):
        fields = roadmap_item_fields(inventory, item_id)
        if not fields:
            continue
        status = str(fields.get("status") or "").strip().casefold()
        if status in PLAN_ELIGIBLE_ROADMAP_STATUSES:
            continue
        display_status = status or "<missing>"
        errors.append(
            Finding(
                "error",
                "plan-roadmap-status-refused",
                (
                    f"roadmap item {item_id!r} has status {display_status!r}; plan --roadmap-item opens only "
                    "accepted or active items. Historical, deferred, rejected, done, superseded, blocked, "
                    "or proposed roadmap facts are not current legal next actions; update the roadmap item "
                    "to accepted through an explicit reviewed roadmap dry-run/apply before opening a plan."
                ),
                ROADMAP_REL,
            )
        )
    return errors


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "plan-root-posture", f"root kind: {inventory.root_kind}")


def _boundary_findings() -> list[Finding]:
    return [
        rails_not_cognition_boundary_finding(DEFAULT_PLAN_REL),
        Finding(
            "info",
            "plan-boundary",
            "plan apply writes only project/implementation-plan.md plus selected project-state lifecycle frontmatter and the Current Focus managed block in eligible live operating roots",
        ),
        Finding(
            "info",
            "plan-authority",
            "generated plans are repo-visible execution scaffolds; they cannot approve repair, archive, closeout, commit, rollback, or future mutations",
        ),
    ]


def _plan_roadmap_plans(inventory: Inventory, request: PlanRequest) -> tuple[tuple[RoadmapPlan, ...], list[Finding]]:
    if not request.roadmap_item:
        return (), []
    roadmap_requests = tuple(
        make_roadmap_request("update", item_id, related_plan=DEFAULT_PLAN_REL)
        for item_id in _plan_roadmap_item_ids(inventory, request)
    )
    plans, errors = roadmap_plans_for_requests(inventory, roadmap_requests, allowed_missing_paths={DEFAULT_PLAN_REL})
    if errors:
        return plans, errors
    return _plan_roadmap_plans_with_current_posture(plans), []


def _plan_roadmap_plans_with_current_posture(plans: tuple[RoadmapPlan, ...]) -> tuple[RoadmapPlan, ...]:
    if not plans:
        return plans
    last = plans[-1]
    active_item_ids = tuple(_dedupe_nonempty(plan.item_id for plan in plans))
    updated_text, retargeted_item_ids = roadmap_text_with_terminal_related_plan_retargets(
        last.updated_text,
        active_item_ids=active_item_ids,
    )
    changed_fields = last.changed_fields
    if updated_text != last.updated_text:
        changed_fields = tuple(_dedupe_nonempty((*changed_fields, TERMINAL_RELATED_PLAN_RETARGET_FIELD)))

    refreshed_text = sync_roadmap_current_posture_section(updated_text)
    if refreshed_text != updated_text:
        changed_fields = tuple(_dedupe_nonempty((*changed_fields, ROADMAP_CURRENT_POSTURE_FIELD)))
        updated_text = refreshed_text

    if updated_text == last.updated_text and not retargeted_item_ids:
        return plans
    return (
        *plans[:-1],
        replace(
            last,
            updated_text=updated_text,
            changed_fields=changed_fields,
            retargeted_terminal_item_ids=tuple(_dedupe_nonempty((*last.retargeted_terminal_item_ids, *retargeted_item_ids))),
        ),
    )


def _plan_roadmap_item_ids(inventory: Inventory, request: PlanRequest) -> tuple[str, ...]:
    requested = _normalized_item_id(request.roadmap_item)
    if not requested:
        return ()
    if request.only_requested_item:
        return (requested,)
    slice_contract = roadmap_slice_contract_for_item(inventory, requested)
    if slice_contract and requested in {slice_contract.primary_roadmap_item, *slice_contract.covered_roadmap_items}:
        return tuple(_dedupe_nonempty((requested, *slice_contract.covered_roadmap_items)))
    return (requested,)


def _plan_source_incubation_plans(inventory: Inventory, request: PlanRequest) -> tuple[tuple[RelationshipUpdatePlan, ...], list[Finding]]:
    if not request.roadmap_item:
        return (), []
    plans: list[RelationshipUpdatePlan] = []
    errors: list[Finding] = []
    seen_sources: set[str] = set()
    for item_id in _plan_roadmap_item_ids(inventory, request):
        fields = roadmap_item_fields(inventory, item_id)
        source_incubation = _normalize_rel(str(fields.get("source_incubation") or ""))
        if not source_incubation or source_incubation in seen_sources:
            continue
        seen_sources.add(source_incubation)
        plan, plan_errors = relationship_update_plan(
            inventory,
            source_incubation,
            {
                "related_roadmap": ROADMAP_REL,
                "related_roadmap_item": item_id,
                "related_plan": DEFAULT_PLAN_REL,
                "promoted_to": ROADMAP_REL,
            },
        )
        errors.extend(plan_errors)
        if plan is not None:
            plans.append(plan)
    if request.update_active:
        detach_plans, detach_errors = _replaced_active_source_incubation_detach_plans(inventory, seen_sources)
        errors.extend(detach_errors)
        plans.extend(detach_plans)
    return tuple(plans), errors


def _replaced_active_source_incubation_detach_plans(inventory: Inventory, active_sources: set[str]) -> tuple[tuple[RelationshipUpdatePlan, ...], list[Finding]]:
    active_plan = inventory.active_plan_surface
    if active_plan is None or not active_plan.exists or not active_plan.frontmatter.has_frontmatter or active_plan.frontmatter.errors:
        return (), []
    source_rels = _active_plan_source_incubation_rels(active_plan.frontmatter.data)
    plans: list[RelationshipUpdatePlan] = []
    errors: list[Finding] = []
    for source_rel in source_rels:
        if source_rel in active_sources:
            continue
        source_path = inventory.root / source_rel
        try:
            source_text = source_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _frontmatter_scalar_value(source_text, "related_plan") != DEFAULT_PLAN_REL:
            continue
        plan, plan_errors = relationship_update_plan(
            inventory,
            source_rel,
            {},
            clear_fields=("related_plan",),
        )
        errors.extend(plan_errors)
        if plan is not None:
            plans.append(plan)
    return tuple(plans), errors


def _active_plan_source_incubation_rels(data: dict[str, object]) -> tuple[str, ...]:
    return tuple(_dedupe_nonempty((_normalize_rel(str(data.get("source_incubation") or "")),)))


def _plan_source_incubation_tmp(plan: RelationshipUpdatePlan) -> Path:
    return plan.target_path.with_name(f".{plan.target_path.name}.plan-source-incubation.tmp")


def _plan_source_incubation_backup(plan: RelationshipUpdatePlan) -> Path:
    return plan.target_path.with_name(f".{plan.target_path.name}.plan-source-incubation.backup")


def _plan_source_incubation_findings(plans: tuple[RelationshipUpdatePlan, ...], apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    changed_plans = tuple(plan for plan in plans if plan.changed_fields)
    action = "updated" if apply and changed_plans else "checked" if apply else "would update"
    findings = [
        Finding(
            "info",
            "plan-source-incubation-sync",
            f"{action} source incubation relationship metadata for {len(plans)} roadmap source file(s)",
        )
    ]
    if plans:
        findings.append(
            Finding(
                "info",
                "plan-relationship-graph-before",
                "source incubation relationship graph before: " + _relationship_plan_graph(plans, before=True),
            )
        )
        findings.append(
            Finding(
                "info",
                "plan-relationship-graph-after",
                "source incubation relationship graph after: " + _relationship_plan_graph(plans, before=False),
            )
        )
    for plan in changed_plans:
        findings.extend(
            Finding(
                "info",
                "plan-source-incubation-changed-field",
                f"{prefix}change source incubation {plan.source_rel} field: {field}",
                plan.source_rel,
            )
            for field in plan.changed_fields
        )
    if not changed_plans:
        findings.append(Finding("info", "plan-source-incubation-noop", "source incubation relationship metadata already matches the new active plan", plans[0].source_rel if plans else None))
    findings.append(
        Finding(
            "info",
            "plan-source-incubation-boundary",
            "plan source-incubation sync records same-request active-plan ownership only; it cannot approve archive, closeout, roadmap done-status, commit, or future lifecycle movement",
            DEFAULT_PLAN_REL,
        )
    )
    return findings


def _relationship_plan_graph(plans: tuple[RelationshipUpdatePlan, ...], *, before: bool) -> str:
    edges: list[str] = []
    for plan in plans:
        text = plan.current_text if before else plan.updated_text
        related_plan = _frontmatter_scalar_value(text, "related_plan") or "<detached>"
        related_item = _frontmatter_scalar_value(text, "related_roadmap_item") or "<none>"
        edges.append(f"{plan.source_rel} -> related_plan={related_plan}, related_roadmap_item={related_item}")
    return "; ".join(edges) if edges else "<empty>"


def _plan_slice_contract(inventory: Inventory, request: PlanRequest) -> RoadmapSliceContract | None:
    if not request.roadmap_item:
        return None
    contract = roadmap_slice_contract_for_item(inventory, request.roadmap_item)
    fields = roadmap_item_fields(inventory, request.roadmap_item)
    source_excerpt = _roadmap_source_excerpt(inventory, fields)
    domain_context = _roadmap_domain_context(contract.domain_context, source_excerpt, fields) if contract else ""
    if contract is None:
        return None
    target_artifacts = _plan_target_artifacts(fields, source_excerpt, contract.target_artifacts)
    if not request.only_requested_item:
        return replace(contract, domain_context=domain_context, target_artifacts=target_artifacts)
    return RoadmapSliceContract(
        primary_roadmap_item=contract.primary_roadmap_item,
        execution_slice=contract.execution_slice,
        slice_goal=contract.slice_goal,
        covered_roadmap_items=(request.roadmap_item,),
        domain_context=domain_context,
        target_artifacts=target_artifacts,
        execution_policy=contract.execution_policy,
        closeout_boundary=contract.closeout_boundary,
        source_incubation=_normalize_rel(str(fields.get("source_incubation") or "")),
        source_research=_normalize_rel(str(fields.get("source_research") or "")),
        related_specs=tuple(_dedupe_nonempty(_field_list(fields.get("related_specs")))),
        related_incubation=_normalize_rel(str(fields.get(RELATED_INCUBATION_FIELD) or "")),
        work_class=getattr(contract, "work_class", "implementation"),
        deliverable_class=getattr(contract, "deliverable_class", "implementation"),
        implementation_allowed=bool(getattr(contract, "implementation_allowed", True)),
        promotion_required=bool(getattr(contract, "promotion_required", False)),
    )


def _plan_synthesis_report(
    inventory: Inventory,
    request: PlanRequest,
    slice_contract: RoadmapSliceContract | None,
) -> RoadmapSynthesisReport | None:
    if not request.roadmap_item:
        return None
    if not request.only_requested_item:
        report = roadmap_synthesis_report_for_item(inventory, request.roadmap_item)
        if report is None:
            return None
        return _synthesis_report_with_contract_targets(report, slice_contract)
    contract = slice_contract or _plan_slice_contract(inventory, request)
    if contract is None:
        return None
    source_inputs = tuple(_dedupe_nonempty((contract.source_incubation, contract.related_incubation, contract.source_research)))
    item_fields = roadmap_item_fields(inventory, request.roadmap_item)
    verification_summary = _normalized_note(item_fields.get("verification_summary"))
    docs_update_count = 1 if str(item_fields.get("docs_decision") or "").strip().casefold() == "updated" else 0
    verification_summary_count = 1 if verification_summary else 0
    recommended_phase_count = _recommended_phase_count_for_values(
        covered_count=1,
        target_count=len(contract.target_artifacts),
        related_spec_count=len(contract.related_specs),
        verification_summary_count=verification_summary_count,
        docs_update_count=docs_update_count,
    )
    docs_pressure = (
        f" and {docs_update_count} docs update {_plural('decision', docs_update_count)}"
        if docs_update_count
        else ""
    )
    return RoadmapSynthesisReport(
        primary_roadmap_item=request.roadmap_item,
        execution_slice=contract.execution_slice,
        covered_roadmap_items=(request.roadmap_item,),
        domain_contexts=(contract.domain_context,),
        target_artifacts=contract.target_artifacts,
        related_specs=contract.related_specs,
        source_inputs=source_inputs,
        bundle_signals=("only requested roadmap item was selected; roadmap slice siblings are not batched",),
        split_signals=(
            f"only requested roadmap item {request.roadmap_item!r} is included; roadmap slice siblings are excluded from this plan",
            "bundle/split output is advisory and cannot approve lifecycle movement",
        ),
        in_slice_dependencies=(),
        verification_summary_count=verification_summary_count,
        target_artifact_pressure=(
            f"{len(contract.target_artifacts)} target artifacts across 1 roadmap item; "
            "report-only sizing signal, not a hard gate"
        ),
        phase_pressure=(
            f"1 domain context and {verification_summary_count} {_plural('verification summary', verification_summary_count)}"
            f"{docs_pressure}; "
            f"candidate plan outline: {recommended_phase_count} {_plural('phase', recommended_phase_count)} or explicit one-shot rationale"
        ),
        docs_update_count=docs_update_count,
    )


def _synthesis_report_with_contract_targets(
    report: RoadmapSynthesisReport,
    slice_contract: RoadmapSliceContract | None,
) -> RoadmapSynthesisReport:
    if slice_contract is None or not slice_contract.target_artifacts:
        return report
    target_artifacts = tuple(slice_contract.target_artifacts)
    if target_artifacts == tuple(report.target_artifacts):
        return report
    recommended_phase_count = _recommended_phase_count_for_values(
        covered_count=len(report.covered_roadmap_items),
        target_count=len(target_artifacts),
        related_spec_count=len(report.related_specs),
        verification_summary_count=report.verification_summary_count,
        docs_update_count=getattr(report, "docs_update_count", 0),
    )
    docs_update_count = getattr(report, "docs_update_count", 0)
    docs_pressure = (
        f" and {docs_update_count} docs update {_plural('decision', docs_update_count)}"
        if docs_update_count
        else ""
    )
    bundle_signals = tuple(report.bundle_signals)
    if not report.target_artifacts:
        bundle_signals = (
            *bundle_signals,
            f"source route hints supplied {len(target_artifacts)} target_artifacts",
        )
    return replace(
        report,
        target_artifacts=target_artifacts,
        bundle_signals=bundle_signals,
        target_artifact_pressure=(
            f"{len(target_artifacts)} target artifacts across {len(report.covered_roadmap_items)} roadmap items; "
            "report-only sizing signal, not a hard gate"
        ),
        phase_pressure=(
            f"{len(report.domain_contexts)} {_plural('domain context', len(report.domain_contexts))} and "
            f"{report.verification_summary_count} {_plural('verification summary', report.verification_summary_count)}"
            f"{docs_pressure}; "
            f"candidate plan outline: {recommended_phase_count} {_plural('phase', recommended_phase_count)} or explicit one-shot rationale"
        ),
    )


def _roadmap_source_incubation(inventory: Inventory, roadmap_item: str) -> str:
    if not roadmap_item:
        return ""
    fields = roadmap_item_fields(inventory, roadmap_item)
    return _normalize_rel(str(fields.get("source_incubation") or ""))


def _roadmap_incubation_provenance(fields: dict[str, object]) -> str:
    source = _normalize_rel(str(fields.get("source_incubation") or ""))
    if source:
        return source
    return _normalize_rel(str(fields.get(RELATED_INCUBATION_FIELD) or ""))


def _roadmap_candidate_title(inventory: Inventory, roadmap_item: str) -> str:
    return roadmap_item_title(inventory, roadmap_item) or _title_from_item_id(roadmap_item)


def _roadmap_candidate_objective(item_id: str, fields: dict[str, object], source_excerpt: str) -> str:
    recovery_only_source = _source_excerpt_is_recovery_only(source_excerpt)
    values: tuple[object, ...] = (
        source_excerpt if _source_excerpt_should_lead(fields, source_excerpt) else "",
        fields.get("slice_goal"),
        fields.get("carry_forward") if recovery_only_source else "",
        source_excerpt,
        fields.get("verification_summary"),
        fields.get("carry_forward"),
        fields.get("execution_slice"),
    )
    for value in values:
        text = _clean_candidate_text(value)
        if text:
            return text
    normalized_item = _normalized_item_id(item_id)
    if normalized_item:
        return f"Implement roadmap item {normalized_item}."
    return ""


def _roadmap_candidate_task(inventory: Inventory, item_id: str, fields: dict[str, object], source_excerpt: str) -> str:
    item = _normalized_item_id(item_id)
    parts: list[str] = []
    if item:
        parts.append(f"{_roadmap_candidate_task_action(inventory, fields)} roadmap item {item}.")
    source = _normalize_rel(str(fields.get("source_incubation") or ""))
    if source:
        parts.append(f"Source incubation: {source}.")
    else:
        related_source = _normalize_rel(str(fields.get(RELATED_INCUBATION_FIELD) or ""))
        if related_source:
            parts.append(f"Related incubation: {related_source}.")
    context_source = source_excerpt
    if _source_excerpt_is_recovery_only(source_excerpt):
        context_source = fields.get("slice_goal") or fields.get("carry_forward") or source_excerpt
    context = _clean_candidate_text(context_source or fields.get("slice_goal"))
    if context:
        parts.append(f"Context: {context}")
    verification = _clean_candidate_text(fields.get("verification_summary"))
    if verification:
        parts.append(f"Verification context: {verification}")
    docs_decision = _clean_candidate_text(fields.get("docs_decision"))
    if docs_decision:
        parts.append(f"Roadmap docs_decision: {docs_decision}.")
    boundary = _clean_candidate_text(fields.get("slice_closeout_boundary"))
    if boundary:
        parts.append(f"Boundary: {boundary}.")
    return " ".join(parts)


def _roadmap_candidate_task_action(inventory: Inventory, fields: dict[str, object]) -> str:
    deliverable_class = roadmap_item_deliverable_class(inventory, fields)
    if deliverable_class in {"audit", "cleanup", "diagnostic", "evidence", "fan-in-review", "proposal", "research"}:
        return f"Produce {_display_deliverable_class(deliverable_class)} deliverable for"
    return "Implement"


def _display_deliverable_class(deliverable_class: str) -> str:
    return _normalized_text(str(deliverable_class or "non-implementation").replace("-", " "))


def _roadmap_source_excerpt(inventory: Inventory, fields: dict[str, object]) -> str:
    source_rel = _roadmap_incubation_provenance(fields)
    if not source_rel:
        return ""
    source_path = inventory.root / source_rel
    if _path_escapes_root(inventory.root, source_path) or not source_path.is_file():
        return ""
    try:
        text = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    body = _body_without_frontmatter(text)
    paragraphs = _candidate_paragraphs(body)
    tagged = _select_source_excerpt_paragraph(paragraphs, text)
    excerpt = _clean_candidate_text(tagged or (paragraphs[0] if paragraphs else ""))
    if tagged:
        excerpt = _source_excerpt_with_hints(excerpt, text)
    return excerpt


def _select_source_excerpt_paragraph(paragraphs: tuple[str, ...], source_text: str) -> str:
    tagged = tuple(paragraph for paragraph in paragraphs if paragraph.lstrip().startswith("[MLH-Fix-Candidate]"))
    if not tagged:
        tagged = tuple(paragraph for paragraph in paragraphs if "[MLH-Fix-Candidate]" in paragraph)
    if not tagged:
        return ""
    enriched: list[tuple[str, str]] = []
    for paragraph in tagged:
        cleaned = _clean_candidate_text(paragraph)
        enriched.append((paragraph, _source_excerpt_with_hints(cleaned, source_text)))
    for paragraph, excerpt in reversed(enriched):
        if _source_excerpt_has_route_hints(excerpt) and not _source_excerpt_is_recovery_only(excerpt):
            return paragraph
    for paragraph, excerpt in reversed(enriched):
        if _source_excerpt_has_route_hints(excerpt):
            return paragraph
    return tagged[-1]


def _roadmap_domain_context(roadmap_context: str, source_excerpt: str, fields: dict[str, object]) -> str:
    if _source_excerpt_should_lead(fields, source_excerpt):
        return source_excerpt
    return roadmap_context or source_excerpt


def _body_without_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :])
    return text


def _candidate_paragraphs(text: str) -> tuple[str, ...]:
    paragraphs: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return tuple(paragraph for paragraph in (re.sub(r"\s+", " ", item).strip() for item in paragraphs) if paragraph)


def _source_excerpt_with_hints(excerpt: str, source_text: str) -> str:
    hints: list[str] = []
    lower_excerpt = excerpt.casefold()
    for key in ("affected_routes", "expected_owner_command"):
        value = _source_hint_field(source_text, key)
        if value and key not in lower_excerpt:
            hints.append(f"{key}: {value}")
    if not hints:
        return excerpt
    return f"{excerpt} {'; '.join(hints)}"


def _source_hint_field(text: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*-\s*`?{re.escape(key)}`?:\s*(.+?)\s*$", text)
    if not match:
        return ""
    return match.group(1).strip().strip("`").strip()


def _source_excerpt_has_route_hints(value: str) -> bool:
    text = value.casefold()
    return "affected_routes:" in text or "expected_owner_command:" in text


def _source_excerpt_should_lead(fields: dict[str, object], source_excerpt: str) -> bool:
    if not _source_excerpt_has_route_hints(source_excerpt):
        return False
    if _source_excerpt_is_recovery_only(source_excerpt):
        return False
    return not _roadmap_item_has_grouped_slice_members(fields)


def _source_excerpt_is_recovery_only(value: str) -> bool:
    text = value.casefold()
    return any(
        marker in text
        for marker in (
            "recovered missing source-incubation evidence",
            "recovered missing source incubation evidence",
            "recreated missing source-incubation evidence",
            "source-incubation evidence recovery",
            "source incubation recovery",
            "source-note evidence is recovery-only",
            "safe_boundary: evidence recovery only",
        )
    )


def _roadmap_item_has_grouped_slice_members(fields: dict[str, object]) -> bool:
    item_id = _normalized_item_id(fields.get("id"))
    members = tuple(_normalized_item_id(member) for member in _field_list(fields.get("slice_members")))
    members = tuple(member for member in members if member)
    if len(members) > 1:
        return True
    return bool(members and item_id and members[0] != item_id)


def _plan_target_artifacts(
    fields: dict[str, object],
    source_excerpt: str,
    contract_target_artifacts: tuple[str, ...],
) -> tuple[str, ...]:
    explicit = tuple(_dedupe_nonempty(_field_list(fields.get("target_artifacts"))))
    if explicit:
        return explicit
    if contract_target_artifacts:
        return contract_target_artifacts
    return tuple(_dedupe_nonempty(_target_artifacts_from_source_context(source_excerpt)))


def _target_artifacts_from_source_context(value: str) -> tuple[str, ...]:
    hint = _affected_routes_hint(value)
    routes = [route for route in _parse_route_hint_list(hint) if _looks_like_target_artifact_route(route)] if hint else []
    routes.extend(route for route in _explicit_artifact_routes_from_text(value) if _looks_like_target_artifact_route(route))
    return _pruned_target_artifact_routes(tuple(_dedupe_nonempty(routes)))


def _affected_routes_hint(value: str) -> str:
    match = re.search(
        r"(?is)(?:^|\s)affected_routes:\s*(.+?)(?=\s+(?:agent_friction|authority_boundary|command_choreography|drift_risk|expected_owner_command|false_positive_risk|leak_shape|manual_step|repeatability|safe_boundary|severity|signal_type):|$)",
        value,
    )
    return match.group(1).strip() if match else ""


def _parse_route_hint_list(value: str) -> tuple[str, ...]:
    cleaned = value.strip().strip("`")
    if cleaned.startswith("["):
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            normalized = tuple(_normalize_route_hint(item) for item in parsed)
            return tuple(route for route in normalized if route)
    return tuple(route for route in (_normalize_route_hint(part) for part in cleaned.split(",")) if route)


def _normalize_route_hint(value: object) -> str:
    route = str(value or "").strip().strip("`\"'")
    route = route.strip()
    if route.endswith("."):
        route = route[:-1].rstrip()
    return _normalize_rel(route.strip("[] "))


def _explicit_artifact_routes_from_text(value: str) -> tuple[str, ...]:
    text = str(value or "").replace("\\", "/")
    routes: list[str] = []
    group_pattern = re.compile(
        r"(?P<first>(?:src|tests|docs|project/specs)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+)"
        r"(?P<tail>(?:\s*,\s*(?:and\s+)?[A-Za-z0-9_-]+\.[A-Za-z0-9]+)*)",
        flags=re.IGNORECASE,
    )
    for match in group_pattern.finditer(text):
        first = _normalize_route_hint(match.group("first"))
        if first:
            routes.append(first)
        base = first.rsplit("/", 1)[0] if "/" in first else ""
        for sibling in re.findall(r"(?:,|\band\b)\s*(?:and\s+)?([A-Za-z0-9_-]+\.[A-Za-z0-9]+)", match.group("tail")):
            if base and sibling:
                routes.append(_normalize_rel(f"{base}/{sibling}"))
    path_pattern = re.compile(
        r"(?<![A-Za-z0-9_./-])((?:src|tests|docs|project/specs)/[A-Za-z0-9_./*-]+)",
        flags=re.IGNORECASE,
    )
    for match in path_pattern.finditer(text):
        route = _normalize_route_hint(match.group(1))
        if route:
            routes.append(route)
    return tuple(_dedupe_nonempty(routes))


def _pruned_target_artifact_routes(routes: tuple[str, ...]) -> tuple[str, ...]:
    exact = tuple(route for route in routes if not _is_broad_target_artifact_route(route))
    if not exact:
        return routes
    pruned: list[str] = []
    for route in routes:
        if _is_ambiguous_context_route(route):
            continue
        if _is_broad_target_artifact_route(route) and any(_route_is_within_broad_target(exact_route, route) for exact_route in exact):
            continue
        pruned.append(route)
    return tuple(_dedupe_nonempty(pruned))


def _is_ambiguous_context_route(route: str) -> bool:
    return _normalize_rel(route).casefold() in {"docs/tests", "tests/docs"}


def _is_broad_target_artifact_route(route: str) -> bool:
    normalized = _normalize_rel(route).casefold()
    if "*" in normalized:
        return True
    leaf = normalized.rstrip("/").rsplit("/", 1)[-1]
    return "." not in leaf and normalized.startswith(("src/", "tests/", "docs/", "project/specs/"))


def _route_is_within_broad_target(route: str, broad: str) -> bool:
    exact = _normalize_rel(route).casefold()
    broad_norm = _normalize_rel(broad).casefold().rstrip("/")
    if "*" in broad_norm:
        return exact.startswith(broad_norm.split("*", 1)[0])
    return exact.startswith(f"{broad_norm}/")


def _looks_like_target_artifact_route(value: str) -> bool:
    route = _normalize_rel(value)
    lower = route.casefold()
    if not route or "://" in route or lower.startswith("..") or "/../" in lower:
        return False
    if lower.startswith(("src/", "tests/", "docs/", "build_backend/", "packages/", "apps/", "project/specs/")):
        return True
    return lower in {"agents.md", "readme.md", "package.json", "pyproject.toml", "uv.lock", "pytest.ini", "tox.ini"}


def _clean_candidate_text(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).replace("[MLH-Fix-Candidate]", "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _title_from_item_id(value: str) -> str:
    words = [word for word in re.split(r"[^A-Za-z0-9]+", str(value or "")) if word]
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _truncate_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _plan_roadmap_has_changes(plans: tuple[RoadmapPlan, ...]) -> bool:
    return bool(plans) and plans[0].current_text != plans[-1].updated_text


def _plan_roadmap_findings(plans: tuple[RoadmapPlan, ...], apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    changed_plans = tuple(plan for plan in plans if plan.changed_fields)
    item_ids = tuple(plan.item_id for plan in plans)
    target_rel = plans[-1].target_rel
    action = "updated" if apply and changed_plans else "checked" if apply else "would update"
    findings = [
        Finding("info", "plan-roadmap-sync", f"{action} roadmap item(s) {list(item_ids)!r} with active plan relationship", target_rel),
        Finding("info", "plan-roadmap-target", f"{prefix}write roadmap sync target: {target_rel}", target_rel),
    ]
    if changed_plans:
        for item_plan in plans:
            findings.extend(
                Finding(
                    "info",
                    "plan-roadmap-changed-field",
                    f"{prefix}change roadmap item {item_plan.item_id!r} field: {field}",
                    target_rel,
                )
                for field in item_plan.changed_fields
            )
    else:
        findings.append(Finding("info", "plan-roadmap-noop", "roadmap item(s) already record the requested active plan relationship", target_rel))
    retargeted = tuple(_dedupe_nonempty(item_id for plan in plans for item_id in plan.retargeted_terminal_item_ids))
    if retargeted:
        findings.append(
            Finding(
                "info",
                "plan-roadmap-terminal-retarget",
                f"{prefix}retarget terminal roadmap related_plan link(s): {', '.join(retargeted)}",
                target_rel,
            )
        )
    findings.append(
        Finding(
            "info",
            "plan-roadmap-boundary",
            "plan roadmap sync is an optional project/roadmap.md relationship update bounded to the requested item plus covered_roadmap_items from the roadmap slice contract; roadmap output cannot approve closeout, archive, commit, rollback, repair, or lifecycle decisions",
            target_rel,
        )
    )
    return findings


def _plan_only_requested_item_finding(request: PlanRequest, apply: bool) -> Finding:
    prefix = "" if apply else "would "
    return Finding(
        "info",
        "plan-only-requested-item",
        f"{prefix}limit roadmap relationship and active-plan slice frontmatter to requested item {request.roadmap_item!r}",
        DEFAULT_PLAN_REL,
    )


def _plan_slice_contract_findings(contract: RoadmapSliceContract, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding(
            "info",
            "plan-slice-frontmatter",
            (
                f"{prefix}record executable slice frontmatter: primary_roadmap_item={contract.primary_roadmap_item!r}; "
                f"covered_roadmap_items={list(contract.covered_roadmap_items)!r}; execution_policy={contract.execution_policy!r}; "
                f"work_class={_contract_work_class(contract)!r}; deliverable_class={_contract_deliverable_class_for_frontmatter(contract)!r}"
            ),
            DEFAULT_PLAN_REL,
        ),
        Finding(
            "info",
            "plan-slice-boundary",
            "plan slice metadata is derived from repo-visible roadmap fields and cannot approve auto-continue, closeout, archive, commit, rollback, repair, or lifecycle decisions",
            DEFAULT_PLAN_REL,
        ),
    ]
    if contract.related_incubation and not contract.source_incubation:
        findings.append(
            Finding(
                "info",
                "plan-related-incubation-provenance",
                (
                    f"{prefix}record non-owning related_incubation provenance "
                    f"{contract.related_incubation!r} in active-plan metadata without source-note relationship writes"
                ),
                DEFAULT_PLAN_REL,
            )
        )
    if contract.closeout_boundary.startswith(ACCEPTED_BOUNDARY_NORMALIZATION_PREFIX):
        findings.append(
            Finding(
                "info",
                "plan-accepted-closeout-boundary-normalized",
                (
                    f"{prefix}normalize accepted roadmap closeout_boundary from stale no-plan/no-archive wording; "
                    "the active plan may open, while closeout, archive, and lifecycle movement still require explicit review"
                ),
                DEFAULT_PLAN_REL,
            )
        )
    return findings


def _plan_synthesis_findings(inventory: Inventory, report: RoadmapSynthesisReport, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding(
            "info",
            "plan-synthesis-bundle-rationale",
            f"{prefix}report bundle signals for {len(report.covered_roadmap_items)} roadmap items: {'; '.join(report.bundle_signals)}",
            DEFAULT_PLAN_REL,
        ),
        Finding(
            "info",
            "plan-synthesis-split-boundary",
            f"{prefix}report split boundary: {'; '.join(report.split_signals)}",
            DEFAULT_PLAN_REL,
        ),
        Finding(
            "info",
            "plan-synthesis-target-artifact-pressure",
            f"{prefix}report target artifact pressure: {report.target_artifact_pressure}",
            DEFAULT_PLAN_REL,
        ),
        Finding(
            "info",
            "plan-synthesis-phase-pressure",
            f"{prefix}report phase pressure: {report.phase_pressure}",
            DEFAULT_PLAN_REL,
        ),
        Finding(
            "info",
            "plan-synthesis-boundary",
            "plan synthesis rationale is advisory evidence only and cannot approve lifecycle movement or closeout",
            DEFAULT_PLAN_REL,
        ),
    ]
    findings.extend(_target_artifact_ownership_findings(inventory, report.target_artifacts, prefix, "plan-target-artifact-ownership", DEFAULT_PLAN_REL))
    docs_update_count = getattr(report, "docs_update_count", 0)
    if docs_update_count > 0:
        docs_scope = _docs_impact_scope(report, _artifact_groups(tuple(report.target_artifacts)))
        missing_exact_scope = DOCS_WRITE_SCOPE_PLACEHOLDER in docs_scope
        findings.append(
            Finding(
                "warn" if missing_exact_scope else "info",
                "plan-docs-write-scope-impact",
                (
                    f"{prefix}surface docs/spec write-scope impact for {docs_update_count} "
                    f"roadmap docs_decision=updated {_plural('item', docs_update_count)}: "
                    f"{', '.join(docs_scope)}"
                ),
                DEFAULT_PLAN_REL,
            )
        )
    return findings


def _target_artifact_ownership_findings(
    inventory: Inventory,
    artifacts: tuple[str, ...],
    prefix: str,
    code: str,
    source: str,
) -> list[Finding]:
    records = target_artifact_ownerships(inventory, artifacts)
    if not records:
        return []
    summary = "; ".join(f"{record.artifact}->{record.ownership} ({record.intended_root})" for record in records)
    guidance = "; ".join(sorted({record.guidance for record in records}))
    return [
        Finding(
            "info",
            code,
            f"{prefix}classify target artifact ownership: {summary}; guidance: {guidance}",
            source,
        )
    ]


def _dangerous_input_reason(value: str) -> str | None:
    normalized = re.sub(r"\s+", " ", value.casefold())
    dangerous_markers = (
        ("git reset --hard", "task input asks for destructive VCS recovery"),
        ("git checkout --", "task input asks for broad VCS restoration"),
        ("git restore .", "task input asks for broad VCS restoration"),
        ("git restore -- .", "task input asks for broad VCS restoration"),
        ("git clean -fd", "task input asks for destructive cleanup"),
        ("git clean -xdf", "task input asks for destructive cleanup"),
        ("rm -rf", "task input asks for destructive cleanup"),
        ("remove-item -recurse", "task input asks for destructive cleanup"),
        ("rmdir /s", "task input asks for destructive cleanup"),
        ("del /s", "task input asks for destructive cleanup"),
    )
    for marker, reason in dangerous_markers:
        if marker in normalized:
            return reason
    return None


def _update_frontmatter_scalars(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return text

    seen: set[str] = set()
    for index in range(1, closing_index):
        match = re.match(r"^([A-Za-z0-9_-]+):(.*?)(\r?\n)?$", lines[index])
        if not match:
            continue
        key = match.group(1)
        if key not in updates:
            continue
        newline = match.group(3) or ("\n" if lines[index].endswith("\n") else "")
        lines[index] = f'{key}: "{_yaml_double_quoted_value(updates[key])}"{newline}'
        seen.add(key)

    missing = [key for key in updates if key not in seen]
    if missing:
        insert_lines = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"\n' for key in missing]
        lines[closing_index:closing_index] = insert_lines
    return "".join(lines)


def _frontmatter_scalar_value(text: str, key: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return ""
        match = re.match(rf"^{re.escape(key)}:\s*(.*?)\s*$", line)
        if match:
            value = _strip_frontmatter_quotes(match.group(1).strip())
            if value:
                return value
            return _frontmatter_scalar_continuation_value(lines[index + 1 :])
    return ""


def _frontmatter_scalar_continuation_value(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if stripped == "---" or re.match(r"^[A-Za-z0-9_-]+:", line):
            return ""
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            return _strip_frontmatter_quotes(stripped[2:].strip())
        if line.startswith((" ", "\t")):
            return _strip_frontmatter_quotes(stripped)
        return ""
    return ""


def _strip_frontmatter_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.replace('\\"', '"').replace("\\\\", "\\")


def _path_escapes_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _parents_between(root: Path, path: Path) -> list[Path]:
    parents: list[Path] = []
    current = path
    root_resolved = root.resolve()
    while True:
        try:
            current.resolve().relative_to(root_resolved)
        except ValueError:
            break
        if current.resolve() == root_resolved:
            break
        parents.append(current)
        current = current.parent
    return list(reversed(parents))


def _normalize_rel(value: str) -> str:
    return value.replace("\\", "/").strip("/")


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _normalized_note(value: object) -> str:
    return str(value or "").strip()


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _field_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    normalized = str(value or "").strip()
    return [normalized] if normalized else []


def _yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _yaml_frontmatter_list(key: str, values: tuple[str, ...]) -> str:
    if not values:
        return f"{key}: []\n"
    rendered = [f"{key}:\n"]
    rendered.extend(f'  - "{_yaml_double_quoted_value(value)}"\n' for value in values)
    return "".join(rendered)


def _dedupe_nonempty(values) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _plural(label: str, count: int) -> str:
    return label if count == 1 else f"{label}s"


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]
