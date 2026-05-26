from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .command_discovery import rails_not_cognition_boundary_finding
from .incubate import INCUBATION_DIR_REL, incubate_apply_findings, incubate_dry_run_findings, make_incubate_request
from .inventory import Inventory, load_inventory
from .models import Finding
from .reporting import RouteWriteEvidence, route_write_findings


RELEASE_BOUNDARY = "no automatic release removal, lifecycle movement, closeout, archive, staging, commit, or next-plan opening"
CENTRAL_META_FEEDBACK_PROJECT = "MyLittleHarness-dev"
META_FEEDBACK_ROOT_ENV_VAR = "MYLITTLEHARNESS_META_FEEDBACK_ROOT"
META_FEEDBACK_ENABLE_ENV_VAR = "MYLITTLEHARNESS_META_FEEDBACK_ENABLE"
META_FEEDBACK_CI_ENABLE_ENV_VAR = "MYLITTLEHARNESS_META_FEEDBACK_ENABLE_CI"
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
AGENT_OPERABILITY_SIGNAL_TYPES = {"agent-operability", "agent-operability-micro-friction"}
AGENT_OPERABILITY_OWNER_COMMANDS = "meta-feedback, check, writeback, and the route-specific owner command"
AGENT_OPERABILITY_FRICTION_SCOPE = (
    "command ergonomics, route discovery, dry-run/apply wording, docs_decision pressure, and state-transfer hesitation "
    "when they obscure lifecycle authority, required evidence, recovery, root boundaries, or reviewability"
)
CONTRACT_DRIFT_SIGNAL_TYPES = {"lifecycle-contract-drift", "coverage-contract-drift", "authority-contract-drift"}
CONTRACT_DRIFT_OWNER_COMMANDS = "meta-feedback, plan, roadmap, check, and the route-specific owner command"
CONTRACT_DRIFT_SCOPE = (
    "coverage markers, related-plan facts, and active phase target or write scope that disagree about "
    "which owner route may accept the work"
)
CONTRACT_DRIFT_FIELDS = (
    ("claimed_contract", "claimed contract"),
    ("effective_owner", "effective owner"),
    ("drift_surface", "drift surface"),
    ("drift_consequence", "drift consequence"),
)
HOOK_INCIDENT_SIGNAL_TYPES = {"hook-incident", "hook-analysis", "agent-operability-hook-analysis"}
HOOK_INCIDENT_OWNER_COMMANDS = "hooks, meta-feedback, and the route-specific owner command"
HOOK_INCIDENT_FIELDS = (
    ("hook_event", "hook event"),
    ("tool_name", "tool name"),
    ("blocked_surface", "blocked surface"),
    ("intended_route", "intended route"),
    ("legal_route_available", "legal route available"),
    ("next_safe_command", "next safe command"),
    ("hook_classification", "hook classification"),
    ("false_positive_shape", "false positive shape"),
    ("false_negative_shape", "false negative shape"),
    ("output_suppression", "output suppression"),
    ("partial_execution_risk", "partial execution risk"),
    ("suggested_policy_change", "suggested policy change"),
)
CLUSTER_BEGIN = "<!-- BEGIN mylittleharness-meta-feedback-cluster v1 -->"
CLUSTER_END = "<!-- END mylittleharness-meta-feedback-cluster v1 -->"
UNSPECIFIED_ROUTE = "unspecified"
KNOWN_OWNER_COMMANDS = (
    "adapter",
    "approval-packet",
    "claim",
    "check",
    "evidence",
    "incubate",
    "memory-hygiene",
    "meta-feedback",
    "repair",
    "roadmap",
    "transition",
    "writeback",
)
STOP_WORDS = {
    "about",
    "after",
    "again",
    "agent",
    "apply",
    "between",
    "candidate",
    "command",
    "could",
    "during",
    "feedback",
    "future",
    "manual",
    "meta",
    "needs",
    "operator",
    "report",
    "roadmap",
    "route",
    "should",
    "state",
    "through",
    "without",
    "would",
}


@dataclass(frozen=True)
class MetaFeedbackRequest:
    topic: str
    note: str
    note_source: str
    from_root: str
    signal_type: str
    severity: str
    roadmap_item: str
    order: int | None
    dedupe_to: str
    correction_of: str
    capture_mode: str
    requested_root: str
    destination_root: str
    destination_source: str
    env_destination_root: str
    to_root: str
    hook_event: str
    tool_name: str
    blocked_surface: str
    intended_route: str
    legal_route_available: str
    next_safe_command: str
    hook_classification: str
    false_positive_shape: str
    false_negative_shape: str
    output_suppression: str
    partial_execution_risk: str
    suggested_policy_change: str


@dataclass(frozen=True)
class ClusterRecord:
    canonical_id: str
    source_rel: str
    friction_signature: str
    signal_type: str
    expected_owner_command: str
    affected_routes: tuple[str, ...]
    problem_tokens: tuple[str, ...]


@dataclass(frozen=True)
class ClusterObservation:
    canonical_id: str
    source_rel: str
    friction_signature: str
    latest_observation_hash: str
    previous_observation_hash: str
    signal_type: str
    expected_owner_command: str
    affected_routes: tuple[str, ...]
    problem_tokens: tuple[str, ...]
    representative_example: str
    observed_roots: tuple[str, ...]
    duplicate_topics: tuple[str, ...]
    occurrence_count: int
    occurrence_count_delta: int
    correction_count: int
    correction_of: str
    recurrence_score: int
    first_seen: str
    exact_matches: tuple[ClusterRecord, ...]
    candidate_matches: tuple[ClusterRecord, ...]
    matched_by: str


def meta_feedback_env_destination_root(environ: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    if _env_truthy(env.get("GITHUB_ACTIONS")) and not _env_truthy(env.get(META_FEEDBACK_CI_ENABLE_ENV_VAR)):
        return None
    return env.get(META_FEEDBACK_ROOT_ENV_VAR)


def meta_feedback_cli_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    explicit_enable = _env_truthy(env.get(META_FEEDBACK_ENABLE_ENV_VAR))
    root_opt_in = bool(str(env.get(META_FEEDBACK_ROOT_ENV_VAR) or "").strip())
    ci_enable = _env_truthy(env.get(META_FEEDBACK_CI_ENABLE_ENV_VAR))
    if _env_truthy(env.get("GITHUB_ACTIONS")):
        return explicit_enable or ci_enable
    return explicit_enable or root_opt_in


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in TRUTHY_ENV_VALUES


def make_meta_feedback_request(
    topic: str | None,
    note: str | None,
    note_source: str = "--note",
    from_root: str | None = None,
    signal_type: str | None = None,
    severity: str | None = None,
    roadmap_item: str | None = None,
    order: int | None = None,
    dedupe_to: str | None = None,
    correction_of: str | None = None,
    capture_mode: str | None = None,
    requested_root: str | None = None,
    destination_root: str | None = None,
    destination_source: str | None = None,
    env_destination_root: str | None = None,
    to_root: str | None = None,
    hook_event: str | None = None,
    tool_name: str | None = None,
    blocked_surface: str | None = None,
    intended_route: str | None = None,
    legal_route_available: str | None = None,
    next_safe_command: str | None = None,
    hook_classification: str | None = None,
    false_positive_shape: str | None = None,
    false_negative_shape: str | None = None,
    output_suppression: str | None = None,
    partial_execution_risk: str | None = None,
    suggested_policy_change: str | None = None,
) -> MetaFeedbackRequest:
    normalized_topic = _normalized_text(topic)
    normalized_note = str(note or "").strip()
    note_signal_type = _structured_line_field(normalized_note, "signal_type")
    note_severity = _structured_line_field(normalized_note, "severity")
    item_id = _normalized_item_id(roadmap_item) or _safe_slug(normalized_topic)
    return MetaFeedbackRequest(
        topic=normalized_topic,
        note=normalized_note,
        note_source=note_source,
        from_root=_normalized_pathish(from_root),
        signal_type=_normalized_text(signal_type) or _normalized_text(note_signal_type) or "meta-feedback",
        severity=_normalized_text(severity) or _normalized_text(note_severity) or "medium",
        roadmap_item=item_id,
        order=order,
        dedupe_to=_normalized_item_id(dedupe_to),
        correction_of=_normalized_text(correction_of).casefold(),
        capture_mode=_normalized_text(capture_mode),
        requested_root=_normalized_pathish(requested_root),
        destination_root=_normalized_pathish(destination_root),
        destination_source=_normalized_text(destination_source),
        env_destination_root=_normalized_pathish(env_destination_root),
        to_root=_normalized_pathish(to_root),
        hook_event=_normalized_text(hook_event) or _structured_line_field(normalized_note, "hook_event"),
        tool_name=_normalized_text(tool_name) or _structured_line_field(normalized_note, "tool_name"),
        blocked_surface=_normalized_text(blocked_surface) or _structured_line_field(normalized_note, "blocked_surface"),
        intended_route=_normalized_text(intended_route) or _structured_line_field(normalized_note, "intended_route"),
        legal_route_available=_normalized_text(legal_route_available) or _structured_line_field(normalized_note, "legal_route_available"),
        next_safe_command=_normalized_text(next_safe_command) or _structured_line_field(normalized_note, "next_safe_command"),
        hook_classification=_normalized_text(hook_classification) or _structured_line_field(normalized_note, "hook_classification"),
        false_positive_shape=_normalized_text(false_positive_shape) or _structured_line_field(normalized_note, "false_positive_shape"),
        false_negative_shape=_normalized_text(false_negative_shape) or _structured_line_field(normalized_note, "false_negative_shape"),
        output_suppression=_normalized_text(output_suppression) or _structured_line_field(normalized_note, "output_suppression"),
        partial_execution_risk=_normalized_text(partial_execution_risk) or _structured_line_field(normalized_note, "partial_execution_risk"),
        suggested_policy_change=_normalized_text(suggested_policy_change) or _structured_line_field(normalized_note, "suggested_policy_change"),
    )


def meta_feedback_dry_run_findings(inventory: Inventory, request: MetaFeedbackRequest) -> list[Finding]:
    findings = [
        Finding("info", "meta-feedback-dry-run", "meta-feedback proposal only; no files were written"),
        _destination_root_finding(inventory),
        _root_posture_finding(inventory),
        _source_root_finding(request),
    ]
    errors = _request_errors(inventory, request)
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "meta-feedback-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before collecting meta-feedback",
            )
        )
        return findings

    observation = _cluster_observation(inventory, request)
    correction_errors = _correction_errors(inventory, request, observation)
    if correction_errors:
        findings.extend(_with_severity(correction_errors, "warn"))
        findings.append(
            Finding(
                "info",
                "meta-feedback-validation-posture",
                "dry-run refused before apply; fix correction target, then rerun dry-run before collecting meta-feedback",
            )
        )
        return findings
    incubate_request = make_incubate_request(_canonical_topic(request, observation), _note_body(request, observation), request.note_source, fix_candidate=True)
    findings.extend(incubate_dry_run_findings(inventory, incubate_request))
    findings.extend(_cluster_findings(observation, apply=False))
    findings.extend(_cluster_route_write_findings(inventory, observation, apply=False))
    findings.append(_dedupe_finding(inventory, observation, apply=False))
    findings.extend(_agent_operability_findings(request, apply=False))
    findings.extend(_contract_drift_findings(request, apply=False))
    findings.extend(_hook_incident_findings(request, apply=False))
    findings.extend(_roadmap_detached_findings(request, apply=False))
    findings.extend(_boundary_findings(apply=False))
    findings.append(
        Finding(
            "info",
            "meta-feedback-validation-posture",
            "apply would write one incubation note plus canonical cluster metadata only; roadmap promotion requires an explicit roadmap --dry-run/--apply command",
        )
    )
    return findings


def meta_feedback_apply_findings(inventory: Inventory, request: MetaFeedbackRequest) -> list[Finding]:
    errors = _request_errors(inventory, request)
    if errors:
        return errors

    observation = _cluster_observation(inventory, request)
    correction_errors = _correction_errors(inventory, request, observation)
    if correction_errors:
        return correction_errors
    incubate_request = make_incubate_request(_canonical_topic(request, observation), _note_body(request, observation), request.note_source, fix_candidate=True)
    findings = [
        Finding("info", "meta-feedback-apply", "meta-feedback apply started"),
        _destination_root_finding(inventory),
        _root_posture_finding(inventory),
        _source_root_finding(request),
    ]
    incubate_findings = incubate_apply_findings(inventory, incubate_request)
    findings.extend(incubate_findings)
    if any(finding.severity == "error" for finding in incubate_findings):
        findings.append(Finding("info", "meta-feedback-validation-posture", "cluster metadata write skipped because incubation write was refused"))
        return findings

    refreshed = load_inventory(inventory.root)
    cluster_findings = _cluster_apply_findings(refreshed, observation)
    findings.extend(_cluster_findings(observation, apply=True))
    findings.extend(cluster_findings)
    if any(finding.severity == "error" for finding in cluster_findings):
        findings.append(Finding("info", "meta-feedback-validation-posture", "meta-feedback intake stopped after cluster metadata write was refused"))
        return findings

    findings.append(_dedupe_finding(inventory, observation, apply=True))
    findings.extend(_agent_operability_findings(request, apply=True))
    findings.extend(_contract_drift_findings(request, apply=True))
    findings.extend(_hook_incident_findings(request, apply=True))
    findings.extend(_roadmap_detached_findings(request, apply=True))
    findings.extend(_boundary_findings(apply=True))
    findings.append(
        Finding(
            "info",
            "meta-feedback-validation-posture",
            "run check after apply; collected meta-feedback is operating memory, not roadmap sequencing or lifecycle approval",
        )
    )
    return findings


def is_central_meta_feedback_inventory(inventory: Inventory) -> bool:
    data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return inventory.root_kind == "live_operating_root" and data.get("project") == CENTRAL_META_FEEDBACK_PROJECT


def _request_errors(inventory: Inventory, request: MetaFeedbackRequest) -> list[Finding]:
    errors: list[Finding] = []
    if not is_central_meta_feedback_inventory(inventory):
        errors.append(
            Finding(
                "error",
                "meta-feedback-central-root-refused",
                (
                    f"destination must be the central {CENTRAL_META_FEEDBACK_PROJECT} live operating root; "
                    f"use --to-root <{CENTRAL_META_FEEDBACK_PROJECT}> or {META_FEEDBACK_ROOT_ENV_VAR}; "
                    "the observed source root is provenance only and must not receive canonical MLH product debt"
                ),
            )
        )
    if inventory.root_kind == "product_source_fixture":
        errors.append(Finding("error", "meta-feedback-refused", "target is a product-source compatibility fixture; meta-feedback apply is refused"))
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(Finding("error", "meta-feedback-refused", "target is fallback/archive or generated-output evidence; meta-feedback apply is refused"))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "meta-feedback-refused", f"target root kind is {inventory.root_kind}; meta-feedback requires a live operating root"))
    if not request.topic:
        errors.append(Finding("error", "meta-feedback-refused", "--topic is required and cannot be empty"))
    if not request.note:
        errors.append(Finding("error", "meta-feedback-refused", "--note is required and cannot be empty"))
    if not request.from_root:
        errors.append(Finding("error", "meta-feedback-refused", "--from-root is required and cannot be empty"))
    elif _rel_has_parent_parts(request.from_root):
        errors.append(Finding("error", "meta-feedback-refused", "--from-root must not contain parent path segments"))
    if not request.roadmap_item or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", request.roadmap_item):
        errors.append(Finding("error", "meta-feedback-refused", "--roadmap-item/topic must produce a lowercase ASCII id using letters, numbers, and hyphens"))
    if request.dedupe_to:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", request.dedupe_to):
            errors.append(Finding("error", "meta-feedback-refused", "--dedupe-to must be a lowercase ASCII id using letters, numbers, and hyphens"))
        elif not _canonical_target_exists(inventory, request.dedupe_to):
            errors.append(
                Finding(
                    "error",
                    "meta-feedback-refused",
                    "--dedupe-to must name an existing canonical incubation note",
                    f"{INCUBATION_DIR_REL}/{request.dedupe_to}.md",
                )
            )
    if request.correction_of and not re.fullmatch(r"(latest|[a-z0-9][a-z0-9_.:-]{0,79})", request.correction_of):
        errors.append(Finding("error", "meta-feedback-refused", "--correction-of must be 'latest' or a compact observation/hash id without whitespace"))
    if request.order is not None and request.order < 0:
        errors.append(Finding("error", "meta-feedback-refused", "--order must be a non-negative integer"))
    return errors


def _correction_errors(inventory: Inventory, request: MetaFeedbackRequest, observation: ClusterObservation) -> list[Finding]:
    if not request.correction_of:
        return []
    path = inventory.root / observation.source_rel
    if not path.is_file() or path.is_symlink():
        return [
            Finding(
                "error",
                "meta-feedback-correction-refused",
                "--correction-of requires an existing canonical incubation note; create the original observation first or use --dedupe-to <canonical-id>",
                observation.source_rel,
            )
        ]
    if request.correction_of == "latest" and not observation.previous_observation_hash:
        return [
            Finding(
                "error",
                "meta-feedback-correction-refused",
                "--correction-of latest requires existing cluster metadata with latest_observation_hash",
                observation.source_rel,
            )
        ]
    return []


def _note_body(request: MetaFeedbackRequest, observation: ClusterObservation) -> str:
    agent_operability_fields = ""
    if _is_agent_operability_signal(request):
        agent_operability_fields = (
            f"- agent_friction: {AGENT_OPERABILITY_FRICTION_SCOPE} are valid capture subjects\n"
        )
    correction_fields = ""
    if observation.correction_of:
        correction_fields = (
            f"- correction_of: {observation.correction_of}\n"
            f"- occurrence_count_delta: {observation.occurrence_count_delta}\n"
            "- correction_boundary: correction marker only; historical entries remain append-only evidence.\n"
        )
    contract_drift_fields = _contract_drift_note_fields(request)
    hook_incident_fields = _hook_incident_note_fields(request)
    return (
        f"{request.note}\n\n"
        "Meta-feedback intake fields:\n"
        f"- signal_type: {request.signal_type}\n"
        f"- severity: {request.severity}\n"
        f"- observed_root: {request.from_root}\n"
        f"- capture_mode: {request.capture_mode or 'unspecified'}\n"
        f"- requested_root: {request.requested_root or '<unspecified>'}\n"
        f"- destination_root: {request.destination_root or '<unspecified>'}\n"
        f"- destination_source: {request.destination_source or '<unspecified>'}\n"
        f"- to_root_arg: {request.to_root or '<none>'}\n"
        f"- env_destination_root: {request.env_destination_root or '<none>'}\n"
        f"- note_source: {request.note_source}\n"
        "- dry_run_apply_pairing: not enforced by meta-feedback; rerun a matching dry-run before apply when review evidence matters.\n"
        f"- dedupe_key: {observation.canonical_id}\n"
        f"- canonical_id: {observation.canonical_id}\n"
        f"- duplicate_topic: {request.topic}\n"
        f"- friction_signature: {observation.friction_signature}\n"
        f"- occurrence_count: {observation.occurrence_count}\n"
        f"{correction_fields}"
        f"- recurrence_score: {observation.recurrence_score}\n"
        f"- affected_routes: {_json_list(observation.affected_routes)}\n"
        f"- latest_observation_hash: {observation.latest_observation_hash}\n"
        f"- expected_owner_command: {_expected_owner_command(request)}\n"
        f"{agent_operability_fields}"
        f"{contract_drift_fields}"
        f"{hook_incident_fields}"
        "- authority_boundary: operating-memory capture only; roadmap promotion requires explicit roadmap review; "
        f"{RELEASE_BOUNDARY}.\n"
    )


def _source_incubation_rel(canonical_id: str) -> str:
    return f"{INCUBATION_DIR_REL}/{canonical_id}.md"


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "meta-feedback-root-posture", f"destination root kind: {inventory.root_kind}")


def _destination_root_finding(inventory: Inventory) -> Finding:
    return Finding("info", "meta-feedback-destination-root", f"destination root: {inventory.root}")


def _source_root_finding(request: MetaFeedbackRequest) -> Finding:
    return Finding("info", "meta-feedback-source-root", f"observed source root: {request.from_root}")


def _boundary_findings(*, apply: bool) -> list[Finding]:
    verb = "writes" if apply else "would write"
    return [
        rails_not_cognition_boundary_finding(INCUBATION_DIR_REL),
        Finding(
            "info",
            "meta-feedback-boundary",
            f"meta-feedback {verb} only the destination root's project/plan-incubation/<safe-topic>.md and managed cluster metadata in eligible live operating roots",
        ),
        Finding(
            "info",
            "meta-feedback-authority",
            "meta-feedback output cannot approve repair, closeout, archive, lifecycle movement, next-plan opening, release removal, staging, commit, or push",
        ),
    ]


def _roadmap_detached_findings(request: MetaFeedbackRequest, *, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding(
            "info",
            "meta-feedback-roadmap-detached",
            (
                f"{prefix}leave project/roadmap.md unchanged; meta-feedback no longer creates or updates accepted roadmap items. "
                "Promote mature clusters through an explicit roadmap --dry-run/--apply command after review."
            ),
            "project/roadmap.md",
        )
    ]
    if request.order is not None:
        findings.append(
            Finding(
                "info",
                "meta-feedback-roadmap-order-ignored",
                "--order is ignored because meta-feedback does not write roadmap placement",
                "project/roadmap.md",
            )
        )
    return findings


def _agent_operability_findings(request: MetaFeedbackRequest, *, apply: bool) -> list[Finding]:
    if not _is_agent_operability_signal(request):
        return []
    prefix = "" if apply else "would "
    return [
        Finding(
            "info",
            "meta-feedback-agent-operability-signal",
            (
                f"{prefix}treat agent-operability micro-friction as a first-class MLH feedback signal; "
                f"owner commands: {AGENT_OPERABILITY_OWNER_COMMANDS}"
            ),
        ),
        Finding(
            "info",
            "meta-feedback-agent-operability-boundary",
            (
                f"{prefix}capture {AGENT_OPERABILITY_FRICTION_SCOPE} as operating memory only; "
                f"{RELEASE_BOUNDARY}"
            ),
        ),
    ]


def _contract_drift_findings(request: MetaFeedbackRequest, *, apply: bool) -> list[Finding]:
    if not _has_contract_drift_profile(request):
        return []
    prefix = "" if apply else "would "
    return [
        Finding(
            "info",
            "meta-feedback-contract-drift-profile",
            (
                f"{prefix}capture lifecycle contract drift as a first-class MLH feedback signal; "
                f"owner commands: {_expected_owner_command(request)}"
            ),
        ),
        Finding(
            "info",
            "meta-feedback-contract-drift-boundary",
            (
                f"{prefix}record {CONTRACT_DRIFT_SCOPE} as operating memory without widening write scope "
                f"or accepting roadmap coverage; {RELEASE_BOUNDARY}"
            ),
        ),
    ]


def _hook_incident_findings(request: MetaFeedbackRequest, *, apply: bool) -> list[Finding]:
    if not _has_hook_incident_profile(request):
        return []
    prefix = "" if apply else "would "
    return [
        Finding(
            "info",
            "meta-feedback-hook-incident-profile",
            (
                f"{prefix}capture hook behavior as a first-class MLH feedback signal; "
                f"owner commands: {_expected_owner_command(request)}"
            ),
        ),
        Finding(
            "info",
            "meta-feedback-hook-incident-boundary",
            (
                f"{prefix}record whether the hook was safety-correct, overblocked, underblocked, suppressed output, "
                f"missed the next safe command, or risked partial execution; {RELEASE_BOUNDARY}"
            ),
        ),
    ]


def _dedupe_finding(inventory: Inventory, observation: ClusterObservation, *, apply: bool) -> Finding:
    existing = (inventory.root / observation.source_rel).is_file()
    prefix = "" if apply else "would "
    if existing:
        return Finding(
            "info",
            "meta-feedback-dedupe",
            (
                f"{prefix}append to existing canonical incubation cluster {observation.canonical_id!r}; "
                "no new canonical note path is needed; use --dedupe-to <canonical-id> when an intentional "
                "near-duplicate should append here"
            ),
            observation.source_rel,
        )
    return Finding("info", "meta-feedback-dedupe", f"{prefix}create new canonical incubation cluster {observation.canonical_id!r}; no exact duplicate id was found", observation.source_rel)


def _cluster_observation(inventory: Inventory, request: MetaFeedbackRequest) -> ClusterObservation:
    signal_type = request.signal_type.casefold().replace("_", "-")
    expected_owner_command = _expected_owner_command(request)
    affected_routes = _affected_routes(request)
    problem_tokens = _problem_tokens(_observation_problem_text(request))
    friction_signature = _friction_signature(inventory, signal_type, expected_owner_command, affected_routes, problem_tokens)
    latest_hash = sha256(_normalized_observation_text(request).encode("utf-8")).hexdigest()[:16]
    records = _cluster_records(inventory)
    exact_matches = tuple(record for record in records if record.friction_signature == friction_signature)
    candidate_matches = tuple(
        record
        for record in records
        if record.friction_signature != friction_signature and _cluster_record_looks_related(record, signal_type, expected_owner_command, affected_routes, problem_tokens)
    )
    if request.dedupe_to:
        canonical_id = request.dedupe_to
        matched_by = "explicit --dedupe-to"
    elif exact_matches:
        canonical_id = exact_matches[0].canonical_id
        matched_by = "exact friction_signature"
    else:
        canonical_id = request.roadmap_item
        matched_by = "new canonical candidate"
    source_rel = _source_incubation_rel(canonical_id)
    metadata = _existing_cluster_metadata(inventory.root / source_rel)
    today = date.today().isoformat()
    previous_hash = _metadata_scalar(metadata, "latest_observation_hash")
    correction_of = previous_hash if request.correction_of == "latest" else request.correction_of
    occurrence_delta = 0 if request.correction_of else 1
    occurrence_count = _existing_occurrence_count(metadata, inventory.root / source_rel) + occurrence_delta
    correction_count = _existing_correction_count(metadata) + (1 if request.correction_of else 0)
    observed_roots = tuple(_dedupe_nonempty((*_metadata_list(metadata, "observed_roots"), request.from_root)))
    duplicate_topics = tuple(_dedupe_nonempty((*_metadata_list(metadata, "duplicate_topics"), request.topic)))
    first_seen = _metadata_scalar(metadata, "first_seen") or today
    recurrence_score = _recurrence_score(
        occurrence_count=occurrence_count,
        severity=request.severity,
        observed_roots=observed_roots,
        affected_routes=affected_routes,
        agent_operability=_is_agent_operability_signal(request),
    )
    return ClusterObservation(
        canonical_id=canonical_id,
        source_rel=source_rel,
        friction_signature=friction_signature,
        latest_observation_hash=latest_hash,
        previous_observation_hash=previous_hash,
        signal_type=signal_type,
        expected_owner_command=expected_owner_command,
        affected_routes=affected_routes,
        problem_tokens=problem_tokens,
        representative_example=_single_line_goal(request.topic, request.note),
        observed_roots=observed_roots,
        duplicate_topics=duplicate_topics,
        occurrence_count=occurrence_count,
        occurrence_count_delta=occurrence_delta,
        correction_count=correction_count,
        correction_of=correction_of,
        recurrence_score=recurrence_score,
        first_seen=first_seen,
        exact_matches=exact_matches,
        candidate_matches=candidate_matches,
        matched_by=matched_by,
    )


def _cluster_findings(observation: ClusterObservation, *, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding(
            "info",
            "meta-feedback-cluster-signature",
            (
                f"{prefix}record friction_signature={observation.friction_signature}; "
                f"canonical_id={observation.canonical_id}; affected_routes={_json_list(observation.affected_routes)}"
            ),
            observation.source_rel,
        ),
        Finding(
            "info",
            "meta-feedback-cluster-table",
            (
                f"{prefix}cluster action: matched_by={observation.matched_by}; "
                f"occurrence_count={observation.occurrence_count}; recurrence_score={observation.recurrence_score}; "
                f"source={observation.source_rel}"
            ),
            observation.source_rel,
        ),
    ]
    if observation.exact_matches:
        findings.append(
            Finding(
                "info",
                "meta-feedback-cluster-exact-match",
                f"{prefix}append to canonical cluster(s) from exact signature: {_record_ids(observation.exact_matches)}",
                observation.source_rel,
            )
        )
    if observation.matched_by == "explicit --dedupe-to":
        findings.append(
            Finding(
                "info",
                "meta-feedback-cluster-explicit-dedupe",
                f"{prefix}append observation to requested canonical cluster {observation.canonical_id!r}",
                observation.source_rel,
            )
        )
    if observation.candidate_matches:
        findings.append(
            Finding(
                "info",
                "meta-feedback-cluster-candidate-match",
                (
                    f"{prefix}report related cluster candidate(s): {_record_ids(observation.candidate_matches)}; "
                    "use --dedupe-to <canonical_id> to intentionally append near-duplicates to an existing canonical note"
                ),
                observation.source_rel,
            )
        )
    if observation.correction_of:
        findings.append(
            Finding(
                "info",
                "meta-feedback-correction-marker",
                (
                    f"{prefix}record correction_of={observation.correction_of}; "
                    f"previous_latest_observation_hash={observation.previous_observation_hash or '<missing>'}; "
                    f"new_latest_observation_hash={observation.latest_observation_hash}; "
                    f"occurrence_count_delta={observation.occurrence_count_delta}; "
                    f"correction_count={observation.correction_count}"
                ),
                observation.source_rel,
            )
        )
    findings.append(
        Finding(
            "info",
            "meta-feedback-cluster-boundary",
            f"{prefix}update only canonical incubation cluster metadata; roadmap promotion remains explicit; {RELEASE_BOUNDARY}",
            observation.source_rel,
        )
    )
    return findings


def _cluster_apply_findings(inventory: Inventory, observation: ClusterObservation) -> list[Finding]:
    path = inventory.root / observation.source_rel
    if not path.is_file() or path.is_symlink():
        return [Finding("error", "meta-feedback-cluster-refused", "canonical incubation note is missing or unsafe after incubation apply", observation.source_rel)]
    try:
        current_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding("error", "meta-feedback-cluster-refused", f"canonical incubation note could not be read: {exc}", observation.source_rel)]
    updated_text = _text_with_cluster_metadata(current_text, observation)
    write_findings = _cluster_route_write_findings_from_text(observation.source_rel, current_text, updated_text, apply=True)
    if current_text == updated_text:
        return [
            Finding("info", "meta-feedback-cluster-noop", "canonical cluster metadata already matches the observation", observation.source_rel),
            *write_findings,
        ]
    tmp_path = path.with_name(f".{path.name}.meta-feedback-cluster.tmp")
    backup_path = path.with_name(f".{path.name}.meta-feedback-cluster.backup")
    if tmp_path.exists() or backup_path.exists():
        return [Finding("error", "meta-feedback-cluster-refused", "temporary cluster write or backup path already exists", observation.source_rel)]
    try:
        cleanup_warnings = apply_file_transaction((AtomicFileWrite(path, tmp_path, updated_text, backup_path),))
    except FileTransactionError as exc:
        return [Finding("error", "meta-feedback-cluster-refused", f"cluster metadata write failed before all writes completed: {exc}", observation.source_rel)]
    findings = [
        Finding("info", "meta-feedback-cluster-written", "updated canonical meta-feedback cluster metadata", observation.source_rel),
        *write_findings,
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "meta-feedback-cluster-backup-cleanup", warning, observation.source_rel))
    return findings


def _cluster_route_write_findings(inventory: Inventory, observation: ClusterObservation, *, apply: bool) -> list[Finding]:
    path = inventory.root / observation.source_rel
    try:
        current_text = path.read_text(encoding="utf-8")
    except OSError:
        current_text = ""
    updated_text = _text_with_cluster_metadata(current_text or _new_cluster_placeholder_text(observation), observation)
    return _cluster_route_write_findings_from_text(observation.source_rel, current_text, updated_text, apply=apply)


def _cluster_route_write_findings_from_text(source_rel: str, current_text: str, updated_text: str, *, apply: bool) -> list[Finding]:
    return route_write_findings("meta-feedback-cluster-route-write", (RouteWriteEvidence(source_rel, current_text, updated_text),), apply=apply)


def _text_with_cluster_metadata(text: str, observation: ClusterObservation) -> str:
    block = _cluster_section(observation)
    if CLUSTER_BEGIN in text and CLUSTER_END in text:
        start = text.index(CLUSTER_BEGIN)
        end = text.index(CLUSTER_END, start) + len(CLUSTER_END)
        return text[:start] + _cluster_block(observation) + text[end:]
    marker = "\n## Entries\n"
    if marker in text:
        return text.replace(marker, "\n" + block + marker, 1)
    return text.rstrip() + "\n\n" + block


def _cluster_section(observation: ClusterObservation) -> str:
    return "## Meta-feedback Cluster\n\n" + _cluster_block(observation) + "\n\n"


def _cluster_block(observation: ClusterObservation) -> str:
    today = date.today().isoformat()
    return (
        f"{CLUSTER_BEGIN}\n"
        f"- `canonical_id`: `{_safe_backtick_value(observation.canonical_id)}`\n"
        f"- `friction_signature`: `{observation.friction_signature}`\n"
        f"- `signal_type`: `{_safe_backtick_value(observation.signal_type)}`\n"
        f"- `expected_owner_command`: `{_safe_backtick_value(observation.expected_owner_command)}`\n"
        f"- `occurrence_count`: `{observation.occurrence_count}`\n"
        f"- `first_seen`: `{observation.first_seen}`\n"
        f"- `last_seen`: `{today}`\n"
        f"- `observed_roots`: `{_json_list(observation.observed_roots)}`\n"
        f"- `affected_routes`: `{_json_list(observation.affected_routes)}`\n"
        f"- `duplicate_topics`: `{_json_list(observation.duplicate_topics)}`\n"
        f"{_correction_metadata_lines(observation)}"
        f"- `recurrence_score`: `{observation.recurrence_score}`\n"
        f"- `representative_examples`: `{_json_list((observation.representative_example,))}`\n"
        f"- `latest_observation_hash`: `{observation.latest_observation_hash}`\n"
        f"{CLUSTER_END}"
    )


def _cluster_records(inventory: Inventory) -> tuple[ClusterRecord, ...]:
    root = inventory.root / INCUBATION_DIR_REL
    if not root.is_dir():
        return ()
    records: list[ClusterRecord] = []
    for path in sorted(root.glob("*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        metadata = _cluster_metadata_from_text(text)
        canonical_id = _metadata_scalar(metadata, "canonical_id") or path.stem
        signature = _metadata_scalar(metadata, "friction_signature") or _line_field(text, "friction_signature")
        if not signature:
            continue
        signal_type = _metadata_scalar(metadata, "signal_type") or _line_field(text, "signal_type")
        owner = _metadata_scalar(metadata, "expected_owner_command") or _line_field(text, "expected_owner_command")
        affected_routes = tuple(_metadata_list(metadata, "affected_routes")) or tuple(_list_line_field(text, "affected_routes")) or (UNSPECIFIED_ROUTE,)
        duplicate_topics = tuple(_metadata_list(metadata, "duplicate_topics"))
        problem_tokens = _problem_tokens(" ".join((*duplicate_topics, _representative_text(metadata), text[:1200])))
        records.append(
            ClusterRecord(
                canonical_id=_normalized_item_id(canonical_id),
                source_rel=f"{INCUBATION_DIR_REL}/{path.name}",
                friction_signature=signature,
                signal_type=signal_type.casefold().replace("_", "-"),
                expected_owner_command=owner,
                affected_routes=affected_routes,
                problem_tokens=problem_tokens,
            )
        )
    return tuple(records)


def _existing_cluster_metadata(path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        return _cluster_metadata_from_text(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _cluster_metadata_from_text(text: str) -> dict[str, object]:
    if CLUSTER_BEGIN not in text or CLUSTER_END not in text:
        return {}
    start = text.index(CLUSTER_BEGIN) + len(CLUSTER_BEGIN)
    end = text.index(CLUSTER_END, start)
    metadata: dict[str, object] = {}
    for line in text[start:end].splitlines():
        match = re.match(r"^\s*-\s+`([^`]+)`:\s+`(.*?)`\s*$", line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2)
        if raw.startswith("[") and raw.endswith("]"):
            metadata[key] = _parse_json_list(raw)
        else:
            metadata[key] = raw
    return metadata


def _existing_occurrence_count(metadata: dict[str, object], path) -> int:
    value = _metadata_scalar(metadata, "occurrence_count")
    if value:
        try:
            return max(int(value), 0)
        except ValueError:
            return 0
    if not path.is_file() or path.is_symlink():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return text.count("Meta-feedback intake fields:")


def _existing_correction_count(metadata: dict[str, object]) -> int:
    value = _metadata_scalar(metadata, "correction_count")
    if value:
        try:
            return max(int(value), 0)
        except ValueError:
            return 0
    return 0


def _canonical_target_exists(inventory: Inventory, canonical_id: str) -> bool:
    return (inventory.root / _source_incubation_rel(canonical_id)).is_file()


def _canonical_topic(request: MetaFeedbackRequest, observation: ClusterObservation) -> str:
    if (
        observation.canonical_id == request.roadmap_item
        and not request.dedupe_to
        and _safe_slug(request.topic) == observation.canonical_id
    ):
        return request.topic
    return _title_from_topic(observation.canonical_id)


def _affected_routes(request: MetaFeedbackRequest) -> tuple[str, ...]:
    haystack = "\n".join((request.topic, request.note, request.blocked_surface, request.intended_route, request.next_safe_command))
    structured_routes = _structured_list_field(request.note, "affected_routes")
    if structured_routes:
        return tuple(_dedupe_nonempty(structured_routes))
    routes: list[str] = []
    for match in re.finditer(r"(?<![A-Za-z0-9_.-])((?:project|docs|src|tests|\.codex|\.agents)/[A-Za-z0-9_./-]+)", haystack):
        routes.append(match.group(1).strip("./"))
    lowered = haystack.casefold()
    for command in KNOWN_OWNER_COMMANDS:
        if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(command)}(?![A-Za-z0-9_-])", lowered):
            routes.append(command)
    deduped = tuple(_dedupe_nonempty(routes))
    return deduped or (UNSPECIFIED_ROUTE,)


def _problem_tokens(text: str) -> tuple[str, ...]:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").casefold()
    words = re.findall(r"[a-z0-9]{4,}", ascii_text)
    tokens = [word for word in words if word not in STOP_WORDS]
    return tuple(sorted(set(tokens))[:16])


def _friction_signature(
    inventory: Inventory,
    signal_type: str,
    expected_owner_command: str,
    affected_routes: tuple[str, ...],
    problem_tokens: tuple[str, ...],
) -> str:
    material = "|".join(
        (
            inventory.root_kind,
            signal_type,
            expected_owner_command,
            ",".join(sorted(affected_routes)),
            ",".join(problem_tokens[:12]),
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()[:16]


def _normalized_observation_text(request: MetaFeedbackRequest) -> str:
    return "|".join(
        (
            request.topic,
            request.note,
            request.from_root,
            request.signal_type,
            request.severity,
            request.correction_of,
            _contract_drift_profile_text(request),
            _hook_incident_profile_text(request),
        )
    )


def _cluster_record_looks_related(
    record: ClusterRecord,
    signal_type: str,
    expected_owner_command: str,
    affected_routes: tuple[str, ...],
    problem_tokens: tuple[str, ...],
) -> bool:
    if record.signal_type != signal_type or record.expected_owner_command != expected_owner_command:
        return False
    route_overlap = set(record.affected_routes) & set(affected_routes) - {UNSPECIFIED_ROUTE}
    token_overlap = set(record.problem_tokens) & set(problem_tokens)
    return bool(route_overlap) or len(token_overlap) >= 2


def _recurrence_score(
    *,
    occurrence_count: int,
    severity: str,
    observed_roots: tuple[str, ...],
    affected_routes: tuple[str, ...],
    agent_operability: bool,
) -> int:
    severity_score = {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(severity.casefold(), 2)
    route_count = len([route for route in affected_routes if route != UNSPECIFIED_ROUTE])
    score = occurrence_count * 2 + severity_score + min(len(observed_roots), 3) + min(route_count, 3)
    if agent_operability:
        score += 2
    return score


def _new_cluster_placeholder_text(observation: ClusterObservation) -> str:
    return f"# {_title_from_topic(observation.canonical_id)}\n\n## Entries\n"


def _metadata_scalar(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    if value in (None, "", [], ()):
        return ""
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return str(value).strip()


def _metadata_list(metadata: dict[str, object], key: str) -> tuple[str, ...]:
    value = metadata.get(key)
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, str):
        return tuple(_parse_json_list(value) if value.startswith("[") else [value])
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _line_field(text: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*-\s*{re.escape(key)}:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def _list_line_field(text: str, key: str) -> tuple[str, ...]:
    raw = _line_field(text, key)
    if not raw:
        return ()
    if raw.startswith("[") and raw.endswith("]"):
        return tuple(_parse_json_list(raw))
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _parse_json_list(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _representative_text(metadata: dict[str, object]) -> str:
    values = _metadata_list(metadata, "representative_examples")
    return " ".join(values)


def _record_ids(records: tuple[ClusterRecord, ...]) -> str:
    return ", ".join(_dedupe_nonempty(record.canonical_id for record in records))


def _json_list(values: tuple[str, ...] | list[str]) -> str:
    return json.dumps(list(values), ensure_ascii=True)


def _correction_metadata_lines(observation: ClusterObservation) -> str:
    if observation.correction_count <= 0:
        return ""
    latest = observation.correction_of or ""
    return (
        f"- `correction_count`: `{observation.correction_count}`\n"
        f"- `latest_correction_of`: `{_safe_backtick_value(latest)}`\n"
    )


def _safe_backtick_value(value: str) -> str:
    return str(value).replace("`", "'")


def _title_from_topic(topic: str) -> str:
    words = re.split(r"[\s_-]+", topic.strip())
    return " ".join(word[:1].upper() + word[1:] for word in words if word) or "Meta Feedback Candidate"


def _single_line_goal(topic: str, note: str) -> str:
    paragraph: list[str] = []
    for raw_line in note.splitlines():
        line = raw_line.strip()
        if not line:
            if paragraph:
                break
            continue
        paragraph.append(line)
    goal = " ".join(paragraph) or topic
    return _roadmap_scalar_text(goal).rstrip(".")


def _roadmap_scalar_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("`", "'").strip())


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _normalized_pathish(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _is_agent_operability_signal(request: MetaFeedbackRequest) -> bool:
    signal_type = request.signal_type.casefold().replace("_", "-")
    return signal_type in AGENT_OPERABILITY_SIGNAL_TYPES or signal_type in HOOK_INCIDENT_SIGNAL_TYPES


def _expected_owner_command(request: MetaFeedbackRequest) -> str:
    note_owner = _structured_line_field(request.note, "expected_owner_command")
    if note_owner:
        return note_owner
    if _is_contract_drift_signal(request):
        return CONTRACT_DRIFT_OWNER_COMMANDS
    if _is_hook_incident_signal(request):
        if request.intended_route:
            return f"hooks, {request.intended_route}, and meta-feedback"
        return HOOK_INCIDENT_OWNER_COMMANDS
    if _is_agent_operability_signal(request):
        return AGENT_OPERABILITY_OWNER_COMMANDS
    return "meta-feedback"


def _is_hook_incident_signal(request: MetaFeedbackRequest) -> bool:
    return request.signal_type.casefold().replace("_", "-") in HOOK_INCIDENT_SIGNAL_TYPES


def _is_contract_drift_signal(request: MetaFeedbackRequest) -> bool:
    return request.signal_type.casefold().replace("_", "-") in CONTRACT_DRIFT_SIGNAL_TYPES


def _has_contract_drift_profile(request: MetaFeedbackRequest) -> bool:
    return _is_contract_drift_signal(request) or any(_contract_drift_value(request, field_name) for field_name, _label in CONTRACT_DRIFT_FIELDS)


def _contract_drift_note_fields(request: MetaFeedbackRequest) -> str:
    if not _has_contract_drift_profile(request):
        return ""
    lines = ["- contract_drift_profile: captured\n"]
    for field_name, _label in CONTRACT_DRIFT_FIELDS:
        value = _contract_drift_value(request, field_name)
        lines.append(f"- {field_name}: {value or '<unspecified>'}\n")
    lines.append(
        "- contract_drift_boundary: capture claimed coverage against effective owner scope without widening write scope or accepting roadmap coverage.\n"
    )
    return "".join(lines)


def _contract_drift_profile_text(request: MetaFeedbackRequest) -> str:
    return "|".join(_contract_drift_value(request, field_name) for field_name, _label in CONTRACT_DRIFT_FIELDS)


def _contract_drift_value(request: MetaFeedbackRequest, field_name: str) -> str:
    return _structured_line_field(request.note, field_name)


def _has_hook_incident_profile(request: MetaFeedbackRequest) -> bool:
    return _is_hook_incident_signal(request) or any(_hook_incident_value(request, field_name) for field_name, _label in HOOK_INCIDENT_FIELDS)


def _hook_incident_note_fields(request: MetaFeedbackRequest) -> str:
    if not _has_hook_incident_profile(request):
        return ""
    lines = ["- hook_incident_profile: captured\n"]
    for field_name, label in HOOK_INCIDENT_FIELDS:
        value = _hook_incident_value(request, field_name)
        lines.append(f"- {field_name}: {value or '<unspecified>'}\n")
    lines.append(
        "- hook_analysis_boundary: classify hook behavior without treating hook output as lifecycle approval or weakening safety gates.\n"
    )
    return "".join(lines)


def _hook_incident_profile_text(request: MetaFeedbackRequest) -> str:
    return "|".join(_hook_incident_value(request, field_name) for field_name, _label in HOOK_INCIDENT_FIELDS)


def _observation_problem_text(request: MetaFeedbackRequest) -> str:
    return "\n".join((request.note, _contract_drift_profile_text(request), _hook_incident_profile_text(request)))


def _hook_incident_value(request: MetaFeedbackRequest, field_name: str) -> str:
    return str(getattr(request, field_name, "") or "").strip()


def _structured_line_field(text: str, key: str) -> str:
    match = re.search(rf"(?im)^\s*(?:-\s*)?`?{re.escape(key)}`?\s*:\s*(.+?)\s*$", text)
    if not match:
        return ""
    value = match.group(1).strip()
    if value.startswith("`") and value.endswith("`") and value.count("`") == 2:
        return value[1:-1].strip()
    return value


def _structured_list_field(text: str, key: str) -> tuple[str, ...]:
    raw = _structured_line_field(text, key)
    if not raw:
        return ()
    if raw.startswith("[") and raw.endswith("]"):
        return tuple(_parse_json_list(raw))
    return tuple(item.strip().strip("`") for item in re.split(r"[,;]", raw) if item.strip().strip("`"))


def _safe_slug(topic: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _dedupe_nonempty(values) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _rel_has_parent_parts(value: str) -> bool:
    parts = [part for part in value.replace("\\", "/").split("/") if part]
    return any(part == ".." for part in parts)


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]
