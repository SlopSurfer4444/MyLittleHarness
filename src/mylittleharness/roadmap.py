from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory, target_artifact_ownerships
from .memory_hygiene import (
    ROADMAP_CURRENT_POSTURE_FIELD,
    RelationshipUpdatePlan,
    relationship_update_plan,
    sync_roadmap_current_posture_section,
)
from .models import Finding
from .reporting import RouteWriteEvidence, route_write_findings
from .research_distill import research_distill_quality_problem
from .route_reference_guards import route_reference_transaction_guard_findings
from .safe_commands import safe_item_id


ROADMAP_REL = "project/roadmap.md"
DEFAULT_PLAN_REL = "project/implementation-plan.md"
ROADMAP_STATUS_VALUES = {"proposed", "accepted", "active", "blocked", "done", "deferred", "rejected", "superseded"}
DOCS_DECISION_VALUES = {"updated", "not-needed", "uncertain"}
TERMINAL_QUEUE_STATUSES = {"done", "rejected", "superseded"}
TERMINAL_RELATED_PLAN_STATUSES = {"blocked", "done", "rejected", "superseded"}
ORDER_NAMESPACE_STATUSES = ("accepted", "proposed")
SOURCE_INCUBATION_EVIDENCE_STATUSES = {"accepted", "active"}
FUTURE_QUEUE_FIELD = "future_execution_slice_queue"
FUTURE_QUEUE_TITLE = "Future Execution Slice Queue"
ARCHIVED_HISTORY_FIELD = "archived_completed_history"
ARCHIVED_HISTORY_TITLE = "Archived Completed History"
COMPACTED_ITEM_REPLAY_FIELD = "compacted_roadmap_item_replay"
TERMINAL_RELATED_PLAN_RETARGET_FIELD = "terminal_related_plan_retarget"
ROADMAP_PHYSICAL_ORDER_FIELD = "roadmap_physical_order"
DETAILED_DONE_TAIL_LIMIT = 4
ACCEPTED_ITEM_ORDER_FIELD = "accepted_item_order"
SOURCE_MEMBERS_FIELD = "source_members"
ACCEPTED_BOUNDARY_NORMALIZATION_PREFIX = (
    "accepted roadmap item is eligible for a bounded active plan through explicit plan/transition/writeback review"
)
ROADMAP_PHYSICAL_ORDER_BUCKETS = {
    "active": 0,
    "accepted": 1,
    "proposed": 2,
    "blocked": 3,
    "deferred": 4,
    "done": 5,
    "superseded": 6,
    "rejected": 7,
}
ITEM_ID_LIST_FIELDS = ("dependencies", "slice_members", "slice_dependencies", "supersedes", "superseded_by")
ARCHIVED_PREREQUISITE_REFERENCE_FIELDS = {"dependencies", "slice_dependencies"}
PATH_LIST_FIELDS = (SOURCE_MEMBERS_FIELD, "related_specs")
ARTIFACT_LIST_FIELDS = ("target_artifacts",)
LIST_FIELDS = (*ITEM_ID_LIST_FIELDS, *PATH_LIST_FIELDS, *ARTIFACT_LIST_FIELDS)
RELATED_INCUBATION_FIELD = "related_incubation"
OPTIONAL_SCALAR_ITEM_FIELDS = {"stage"}
CLEARABLE_FIELDS = (
    "stage",
    "execution_slice",
    "slice_goal",
    "slice_members",
    "slice_dependencies",
    "slice_closeout_boundary",
    "dependencies",
    "source_incubation",
    RELATED_INCUBATION_FIELD,
    "source_research",
    SOURCE_MEMBERS_FIELD,
    "related_specs",
    "related_plan",
    "archived_plan",
    "target_artifacts",
    "verification_summary",
    "docs_decision",
    "carry_forward",
    "supersedes",
    "superseded_by",
)
STANDARD_FIELDS = (
    "id",
    "status",
    "stage",
    "order",
    "execution_slice",
    "slice_goal",
    "slice_members",
    "slice_dependencies",
    "slice_closeout_boundary",
    "dependencies",
    "source_incubation",
    RELATED_INCUBATION_FIELD,
    "source_research",
    SOURCE_MEMBERS_FIELD,
    "related_specs",
    "related_plan",
    "archived_plan",
    "target_artifacts",
    "verification_summary",
    "docs_decision",
    "carry_forward",
    "supersedes",
    "superseded_by",
)
PATH_FIELDS = {"source_incubation", RELATED_INCUBATION_FIELD, "source_research", "related_plan", "archived_plan"}
EMPTY_STRICT_ITEM_FIELDS = {*PATH_FIELDS, SOURCE_MEMBERS_FIELD}
SOURCE_INCUBATION_OWNERSHIP_FIELDS = (
    "related_roadmap_item",
    "related_roadmap",
    "related_plan",
    "promoted_to",
    "implemented_by",
    "archived_plan",
    "archived_to",
)
HUMAN_REVIEW_GATE_FIELDS = (
    "needs_deep_research",
    "requires_deep_research",
    "requires_reflection",
    "needs_reflection",
    "needs_human_review",
    "human_gate_required",
    "research_gate",
)
HUMAN_REVIEW_GATE_TRUTHY = {"1", "true", "yes", "required", "needs-human-review", "human-review", "deep-research", "reflection"}
HUMAN_REVIEW_GATE_FALSEY = {"", "0", "false", "no", "none", "not-needed", "not needed", "resolved"}
HIGH_BLAST_GATE_FIELDS = ("stage", "gate_class", "review_class", "risk_class", "blast_radius", "promotion_gate")
BATCH_AUTHORIZATION_FIELDS = (
    "bundle_authorization",
    "bundle_reviewed",
    "reviewed_bundle",
    "explicit_bundle",
    "human_gate_required",
    "needs_human_review",
)
BATCH_AUTHORIZATION_TRUTHY = {
    "1",
    "true",
    "yes",
    "required",
    "reviewed",
    "approved",
    "authorized",
    "explicit",
    "human-reviewed",
    "human-gate",
}
SLICE_RESULT_GATE_FIELDS = (
    "slice_result_gate",
    "requires_slice_result",
    "requires_result_gate",
)
SLICE_RESULT_GATE_TRUTHY = {
    "1",
    "true",
    "yes",
    "required",
    "decision-packet",
    "result-required",
    "slice-result",
}
SLICE_RESULT_ARTIFACT_FIELDS = (
    "slice_result_artifact",
    "slice_result_artifacts",
    "decision_packet",
    "decision_packets",
)
SLICE_RESULT_SAFE_FIELD = "safe_to_continue_existing_sequence"
SLICE_RESULT_FORK_FIELDS = (
    "new_slice_candidates",
    "scope_expansions",
    "blocked_followups",
    "fork_decision",
    "roadmap_updates_required",
)
IMPLEMENTATION_STAGE_VALUES = {"implementation", "implement", "fix", "bugfix", "feature", "product-implementation"}
NON_IMPLEMENTATION_DELIVERABLE_CLASSES = {
    "audit",
    "cleanup",
    "diagnostic",
    "evidence",
    "fan-in-review",
    "proposal",
    "research",
    "route-hygiene",
}
IMPLEMENTATION_DELIVERABLE_VALUES = {
    "implementation",
    "implement",
    "product-implementation",
    "product",
    "source",
    "source-change",
    "code",
}
NON_IMPLEMENTATION_WORK_VALUES = {
    "audit",
    "cleanup",
    "diagnostic",
    "diagnostics",
    "evidence",
    "fan-in",
    "fan-in-review",
    "non-implementation",
    "nonimplementation",
    "proposal",
    "research",
    "review",
    "route-hygiene",
    "route-hygiene-cleanup",
}
DELIVERABLE_CLASS_FIELDS = ("deliverable_class", "deliverable_type", "work_class")
IMPLEMENTATION_PROMOTION_FIELDS = (
    "promoted_to_implementation",
    "implementation_promoted",
    "product_implementation",
)
IMPLEMENTATION_PROMOTION_TRUTHY = {"1", "true", "yes", "promoted", "implementation", "product-implementation"}
IMPLEMENTATION_ALLOWED_TRUTHY = {"1", "true", "yes", "allowed", "implementation", "product-implementation"}
IMPLEMENTATION_ALLOWED_FALSEY = {"", "0", "false", "no", "none", "blocked", "forbidden", "not-allowed"}
PROMOTION_REQUIRED_TRUTHY = {"1", "true", "yes", "required", "promotion-required"}
PROMOTION_REQUIRED_FALSEY = {"", "0", "false", "no", "none", "not-needed", "not-required"}
IMPLEMENTATION_SCOPE_NEXT_SAFE_TEMPLATE = (
    "mylittleharness --root <root> roadmap --dry-run --action update "
    "--item-id {item_id} --target-artifact <rel-path>"
)
DELIVERABLE_CLASS_PROMOTION_NEXT_SAFE_TEMPLATE = (
    "mylittleharness --root <root> roadmap --dry-run --action update "
    "--item-id {item_id} --field deliverable_class=implementation"
)
ACTIVE_PLAN_OPEN_NEXT_SAFE_COMMAND = (
    "mylittleharness --root <root> check; when the active phase is ready, run "
    "mylittleharness --root <root> writeback --dry-run --phase-status complete "
    "--docs-decision <updated|not-needed|uncertain>"
)
ACTIVE_PLAN_ROADMAP_PROMOTION_FIELDS = {
    "status",
    "stage",
    "order",
    "execution_slice",
    "slice_goal",
    "slice_members",
    "slice_dependencies",
    "slice_closeout_boundary",
    "dependencies",
    "target_artifacts",
    "supersedes",
    "superseded_by",
    ACCEPTED_ITEM_ORDER_FIELD,
}


@dataclass(frozen=True)
class RoadmapRequest:
    action: str
    item_id: str
    title: str
    status: str
    stage: str
    order: int | None
    execution_slice: str
    slice_goal: str
    slice_closeout_boundary: str
    source_incubation: str
    source_research: str
    related_plan: str
    archived_plan: str
    verification_summary: str
    docs_decision: str
    carry_forward: str
    dependencies: tuple[str, ...]
    slice_members: tuple[str, ...]
    slice_dependencies: tuple[str, ...]
    related_specs: tuple[str, ...]
    target_artifacts: tuple[str, ...]
    supersedes: tuple[str, ...]
    superseded_by: tuple[str, ...]
    source_members: tuple[str, ...]
    clear_fields: tuple[str, ...]
    custom_fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class RoadmapItem:
    title: str
    fields: dict[str, object]
    start: int
    end: int
    style: str = "canonical"


@dataclass(frozen=True)
class RoadmapPlan:
    action: str
    item_id: str
    target_rel: str
    target_path: Path
    changed_fields: tuple[str, ...]
    reordered_item_ids: tuple[str, ...]
    compacted_item_ids: tuple[str, ...]
    retargeted_terminal_item_ids: tuple[str, ...]
    current_text: str
    updated_text: str
    target_existed: bool = True
    relationship_plan: RelationshipUpdatePlan | None = None
    related_incubation_source: str = ""
    related_incubation_reason: str = ""
    replayed_item_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoadmapBatchPlan:
    target_rel: str
    target_path: Path
    requests: tuple[RoadmapRequest, ...]
    plans: tuple[RoadmapPlan, ...]
    current_text: str
    updated_text: str
    target_existed: bool = True


@dataclass(frozen=True)
class RoadmapSliceContract:
    primary_roadmap_item: str
    execution_slice: str
    slice_goal: str
    covered_roadmap_items: tuple[str, ...]
    domain_context: str
    target_artifacts: tuple[str, ...]
    execution_policy: str
    closeout_boundary: str
    source_incubation: str
    source_research: str
    related_specs: tuple[str, ...]
    source_members: tuple[str, ...] = ()
    related_incubation: str = ""
    work_class: str = "implementation"
    deliverable_class: str = "implementation"
    implementation_allowed: bool = True
    promotion_required: bool = False


@dataclass(frozen=True)
class RoadmapSynthesisReport:
    primary_roadmap_item: str
    execution_slice: str
    covered_roadmap_items: tuple[str, ...]
    domain_contexts: tuple[str, ...]
    target_artifacts: tuple[str, ...]
    related_specs: tuple[str, ...]
    source_inputs: tuple[str, ...]
    bundle_signals: tuple[str, ...]
    split_signals: tuple[str, ...]
    in_slice_dependencies: tuple[str, ...]
    verification_summary_count: int
    target_artifact_pressure: str
    phase_pressure: str
    docs_update_count: int = 0


def make_roadmap_request(
    action: str | None,
    item_id: str | None,
    title: str | None = None,
    status: str | None = None,
    stage: str | None = None,
    order: int | None = None,
    execution_slice: str | None = None,
    slice_goal: str | None = None,
    slice_closeout_boundary: str | None = None,
    source_incubation: str | None = None,
    source_research: str | None = None,
    related_plan: str | None = None,
    archived_plan: str | None = None,
    verification_summary: str | None = None,
    docs_decision: str | None = None,
    carry_forward: str | None = None,
    dependencies: list[str] | None = None,
    slice_members: list[str] | None = None,
    slice_dependencies: list[str] | None = None,
    related_specs: list[str] | None = None,
    target_artifacts: list[str] | None = None,
    supersedes: list[str] | None = None,
    superseded_by: list[str] | None = None,
    source_members: list[str] | None = None,
    clear_fields: list[str] | None = None,
    custom_fields: list[str] | None = None,
) -> RoadmapRequest:
    return RoadmapRequest(
        action=str(action or "").strip().casefold().replace("_", "-"),
        item_id=_normalized_item_id(item_id),
        title=_normalized_text(title),
        status=_normalized_status(status),
        stage=_normalized_scalar(stage),
        order=order,
        execution_slice=_normalized_item_id(execution_slice),
        slice_goal=_normalized_scalar(slice_goal),
        slice_closeout_boundary=_normalized_scalar(slice_closeout_boundary),
        source_incubation=_normalize_rel(source_incubation),
        source_research=_normalize_rel(source_research),
        related_plan=_normalize_rel(related_plan),
        archived_plan=_normalize_rel(archived_plan),
        verification_summary=_normalized_scalar(verification_summary),
        docs_decision=_normalized_status(docs_decision),
        carry_forward=_normalized_scalar(carry_forward),
        dependencies=tuple(_normalized_item_id(value) for value in dependencies or ()),
        slice_members=tuple(_normalized_item_id(value) for value in slice_members or ()),
        slice_dependencies=tuple(_normalized_item_id(value) for value in slice_dependencies or ()),
        related_specs=tuple(_normalize_rel(value) for value in related_specs or ()),
        target_artifacts=tuple(_normalize_rel(value) for value in target_artifacts or ()),
        supersedes=tuple(_normalized_item_id(value) for value in supersedes or ()),
        superseded_by=tuple(_normalized_item_id(value) for value in superseded_by or ()),
        source_members=tuple(_normalize_rel(value) for value in source_members or ()),
        clear_fields=tuple(_normalized_field_name(value) for value in clear_fields or ()),
        custom_fields=_parse_custom_field_args(custom_fields),
    )


def roadmap_batch_requests_from_manifest(manifest_text: str, source_label: str) -> tuple[tuple[RoadmapRequest, ...], list[Finding]]:
    manifest, errors = _load_roadmap_batch_manifest(manifest_text, source_label)
    if errors:
        return (), errors
    if isinstance(manifest, dict):
        extra_keys = sorted(str(key) for key in manifest if key != "items")
        if extra_keys:
            return (), [
                Finding(
                    "error",
                    "roadmap-batch-refused",
                    f"batch manifest top-level keys must be only 'items'; unexpected: {', '.join(extra_keys)}",
                    source_label,
                )
            ]
        items = manifest.get("items")
    else:
        items = manifest
    if not isinstance(items, list) or not items:
        return (), [Finding("error", "roadmap-batch-refused", "batch manifest must contain a non-empty items list", source_label)]

    requests: list[RoadmapRequest] = []
    errors = []
    for index, item in enumerate(items, start=1):
        request, item_errors = _roadmap_request_from_batch_item(item, index, source_label)
        errors.extend(item_errors)
        if request is not None:
            requests.append(request)
    errors.extend(_batch_duplicate_item_id_errors(tuple(requests), source_label))
    if errors:
        return (), errors
    return tuple(requests), []


def _load_roadmap_batch_manifest(manifest_text: str, source_label: str) -> tuple[object | None, list[Finding]]:
    suffix = "" if source_label == "-" else Path(source_label).suffix.casefold()
    if suffix == ".json":
        return _load_roadmap_batch_json(manifest_text, source_label)
    if suffix in {".yaml", ".yml"}:
        return _load_roadmap_batch_yaml(manifest_text, source_label)

    parsed, errors = _load_roadmap_batch_json(manifest_text, source_label)
    if not errors:
        return parsed, []
    yaml_parsed, yaml_errors = _load_roadmap_batch_yaml(manifest_text, source_label)
    if not yaml_errors:
        return yaml_parsed, []
    return None, [
        Finding(
            "error",
            "roadmap-batch-refused",
            "batch manifest must be valid JSON or the supported simple YAML subset",
            source_label,
        )
    ]


def _load_roadmap_batch_json(manifest_text: str, source_label: str) -> tuple[object | None, list[Finding]]:
    duplicate_keys: list[str] = []

    def no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        obj: dict[str, object] = {}
        seen: set[str] = set()
        for key, value in pairs:
            key_text = str(key)
            if key_text in seen:
                duplicate_keys.append(key_text)
            seen.add(key_text)
            obj[key_text] = value
        return obj

    try:
        parsed = json.loads(manifest_text, object_pairs_hook=no_duplicate_object)
    except json.JSONDecodeError as exc:
        return None, [Finding("error", "roadmap-batch-refused", f"batch JSON manifest is malformed: {exc}", source_label)]
    if duplicate_keys:
        return None, [
            Finding(
                "error",
                "roadmap-batch-refused",
                f"batch JSON manifest contains duplicate field(s): {', '.join(_dedupe_nonempty(duplicate_keys))}",
                source_label,
            )
        ]
    return parsed, []


def _load_roadmap_batch_yaml(manifest_text: str, source_label: str) -> tuple[object | None, list[Finding]]:
    return _load_simple_roadmap_batch_yaml(manifest_text, source_label)


def _load_simple_roadmap_batch_yaml(manifest_text: str, source_label: str) -> tuple[object | None, list[Finding]]:
    raw_lines = manifest_text.splitlines()
    lines = [
        (len(line) - len(line.lstrip(" ")), line.strip())
        for line in raw_lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        return None, [Finding("error", "roadmap-batch-refused", "batch YAML manifest is empty", source_label)]

    root_items: list[dict[str, object]]
    start = 0
    if lines[0][1] == "items:":
        root_items = []
        start = 1
    elif lines[0][1].startswith("items:"):
        value = lines[0][1].split(":", 1)[1].strip()
        parsed_value, value_error = _parse_simple_yaml_scalar(value, source_label)
        if value_error:
            return None, [value_error]
        return {"items": parsed_value}, []
    elif lines[0][1].startswith("- "):
        root_items = []
    else:
        return None, [
            Finding(
                "error",
                "roadmap-batch-refused",
                "batch YAML manifest must start with 'items:' or a top-level item list",
                source_label,
            )
        ]

    index = start
    while index < len(lines):
        indent, stripped = lines[index]
        if not stripped.startswith("- "):
            return None, [Finding("error", "roadmap-batch-refused", f"expected YAML item at line {index + 1}: {stripped}", source_label)]
        item: dict[str, object] = {}
        remainder = stripped[2:].strip()
        if remainder:
            key, value, error = _split_simple_yaml_key_value(remainder, source_label)
            if error:
                return None, [error]
            duplicate_error = _assign_simple_yaml_item_field(item, key, value, index + 1, source_label)
            if duplicate_error:
                return None, [duplicate_error]
        index += 1
        while index < len(lines) and lines[index][0] > indent:
            child_indent, child = lines[index]
            key, value, error = _split_simple_yaml_key_value(child, source_label)
            if error:
                return None, [error]
            if value == "":
                values: list[object] = []
                index += 1
                while index < len(lines) and lines[index][0] > child_indent:
                    list_line = lines[index][1]
                    if not list_line.startswith("- "):
                        return None, [
                            Finding(
                                "error",
                                "roadmap-batch-refused",
                                f"expected YAML list entry under {key!r} at line {index + 1}: {list_line}",
                                source_label,
                            )
                        ]
                    parsed, scalar_error = _parse_simple_yaml_scalar(list_line[2:].strip(), source_label)
                    if scalar_error:
                        return None, [scalar_error]
                    values.append(parsed)
                    index += 1
                duplicate_error = _assign_simple_yaml_item_field(item, key, values, index + 1, source_label)
                if duplicate_error:
                    return None, [duplicate_error]
                continue
            duplicate_error = _assign_simple_yaml_item_field(item, key, value, index + 1, source_label)
            if duplicate_error:
                return None, [duplicate_error]
            index += 1
        root_items.append(item)
    return {"items": root_items}, []


def _assign_simple_yaml_item_field(item: dict[str, object], key: str, value: object, line: int, source_label: str) -> Finding | None:
    normalized = _batch_key(key)
    if normalized in {_batch_key(existing) for existing in item}:
        return Finding(
            "error",
            "roadmap-batch-refused",
            f"duplicate YAML field in batch item near line {line}: {key}",
            source_label,
        )
    item[key] = value
    return None


def _split_simple_yaml_key_value(text: str, source_label: str) -> tuple[str, object, Finding | None]:
    if ":" not in text:
        return "", "", Finding("error", "roadmap-batch-refused", f"expected YAML key/value pair: {text}", source_label)
    key, raw_value = text.split(":", 1)
    key = key.strip()
    if not key:
        return "", "", Finding("error", "roadmap-batch-refused", f"expected non-empty YAML key: {text}", source_label)
    value_text = raw_value.strip()
    if value_text == "":
        return key, "", None
    value, error = _parse_simple_yaml_scalar(value_text, source_label)
    return key, value, error


def _parse_simple_yaml_scalar(text: str, source_label: str) -> tuple[object, Finding | None]:
    if text in {"[]", "{}"} or text.startswith(("[", "{", "\"", "'")):
        try:
            return ast.literal_eval(text), None
        except (SyntaxError, ValueError) as exc:
            return "", Finding("error", "roadmap-batch-refused", f"unsupported YAML scalar {text!r}: {exc}", source_label)
    if re.fullmatch(r"-?\d+", text):
        return int(text), None
    if text.casefold() == "true":
        return True, None
    if text.casefold() == "false":
        return False, None
    if text.casefold() in {"null", "~"}:
        return None, None
    return text, None


def _roadmap_request_from_batch_item(item: object, index: int, source_label: str) -> tuple[RoadmapRequest | None, list[Finding]]:
    if not isinstance(item, dict):
        return None, [Finding("error", "roadmap-batch-refused", f"items[{index}] must be an object", source_label)]
    normalized: dict[str, object] = {}
    duplicate_normalized_keys: list[str] = []
    for key, value in item.items():
        normalized_key = _batch_key(str(key))
        if normalized_key in normalized:
            duplicate_normalized_keys.append(normalized_key)
            continue
        normalized[normalized_key] = value
    if duplicate_normalized_keys:
        return None, [
            Finding(
                "error",
                "roadmap-batch-refused",
                f"items[{index}] has duplicate field(s) after normalization: {', '.join(_dedupe_nonempty(duplicate_normalized_keys))}",
                source_label,
            )
        ]
    alias_errors = _batch_alias_collision_errors(normalized, index, source_label)
    if alias_errors:
        return None, alias_errors
    action = _batch_scalar(normalized.pop("action", "add"))
    if action and str(action).strip().casefold().replace("_", "-") != "add":
        return None, [Finding("error", "roadmap-batch-refused", f"items[{index}].action must be 'add' for add-many", source_label)]

    custom_fields = _batch_custom_fields(normalized.pop("fields", ()), index, source_label)
    custom_field_values, custom_field_errors = _batch_custom_field_values(normalized.pop("custom_fields", ()), index, source_label)
    custom_fields.extend(custom_field_values)
    if "field" in normalized:
        field_values, field_errors = _batch_custom_field_values(normalized.pop("field"), index, source_label)
        custom_fields.extend(field_values)
        custom_field_errors.extend(field_errors)
    if custom_field_errors:
        return None, custom_field_errors

    item_id = normalized.pop("item_id", normalized.pop("id", ""))
    values = {
        "title": normalized.pop("title", ""),
        "status": normalized.pop("status", ""),
        "stage": normalized.pop("stage", ""),
        "order": normalized.pop("order", None),
        "execution_slice": normalized.pop("execution_slice", ""),
        "slice_goal": normalized.pop("slice_goal", ""),
        "slice_closeout_boundary": normalized.pop("slice_closeout_boundary", ""),
        "source_incubation": normalized.pop("source_incubation", ""),
        "source_research": normalized.pop("source_research", ""),
        "related_plan": normalized.pop("related_plan", ""),
        "archived_plan": normalized.pop("archived_plan", ""),
        "verification_summary": normalized.pop("verification_summary", ""),
        "docs_decision": normalized.pop("docs_decision", ""),
        "carry_forward": normalized.pop("carry_forward", ""),
    }
    list_values = {
        "dependencies": _batch_list(normalized.pop("dependencies", normalized.pop("dependency", ()))),
        "slice_members": _batch_list(normalized.pop("slice_members", normalized.pop("slice_member", ()))),
        "slice_dependencies": _batch_list(normalized.pop("slice_dependencies", normalized.pop("slice_dependency", ()))),
        "related_specs": _batch_list(normalized.pop("related_specs", normalized.pop("related_spec", ()))),
        "target_artifacts": _batch_list(normalized.pop("target_artifacts", normalized.pop("target_artifact", ()))),
        "supersedes": _batch_list(normalized.pop("supersedes", ())),
        "superseded_by": _batch_list(normalized.pop("superseded_by", ())),
        "source_members": _batch_list(normalized.pop("source_members", normalized.pop("source_member", ()))),
    }
    if "clear_fields" in normalized or "clear_field" in normalized:
        return None, [Finding("error", "roadmap-batch-refused", f"items[{index}] cannot use clear_fields with add-many", source_label)]
    if normalized:
        unknown = ", ".join(sorted(normalized))
        return None, [Finding("error", "roadmap-batch-refused", f"items[{index}] has unknown field(s): {unknown}", source_label)]

    order_value, order_error = _batch_order(values["order"], index, source_label)
    if order_error:
        return None, [order_error]
    return (
        make_roadmap_request(
            action="add",
            item_id=_batch_scalar(item_id),
            title=_batch_scalar(values["title"]),
            status=_batch_scalar(values["status"]),
            stage=_batch_scalar(values["stage"]),
            order=order_value,
            execution_slice=_batch_scalar(values["execution_slice"]),
            slice_goal=_batch_scalar(values["slice_goal"]),
            slice_closeout_boundary=_batch_scalar(values["slice_closeout_boundary"]),
            source_incubation=_batch_scalar(values["source_incubation"]),
            source_research=_batch_scalar(values["source_research"]),
            related_plan=_batch_scalar(values["related_plan"]),
            archived_plan=_batch_scalar(values["archived_plan"]),
            verification_summary=_batch_scalar(values["verification_summary"]),
            docs_decision=_batch_scalar(values["docs_decision"]),
            carry_forward=_batch_scalar(values["carry_forward"]),
            dependencies=list_values["dependencies"],
            slice_members=list_values["slice_members"],
            slice_dependencies=list_values["slice_dependencies"],
            related_specs=list_values["related_specs"],
            target_artifacts=list_values["target_artifacts"],
            supersedes=list_values["supersedes"],
            superseded_by=list_values["superseded_by"],
            source_members=list_values["source_members"],
            custom_fields=custom_fields,
        ),
        [],
    )


def _batch_alias_collision_errors(normalized: dict[str, object], index: int, source_label: str) -> list[Finding]:
    alias_groups = (
        ("item_id", ("id",)),
        ("dependencies", ("dependency",)),
        ("slice_members", ("slice_member",)),
        ("slice_dependencies", ("slice_dependency",)),
        ("related_specs", ("related_spec",)),
        ("target_artifacts", ("target_artifact",)),
        ("source_members", ("source_member",)),
        ("clear_fields", ("clear_field",)),
        ("custom_fields", ("field",)),
    )
    findings: list[Finding] = []
    for canonical, aliases in alias_groups:
        present = [field for field in (canonical, *aliases) if field in normalized]
        if len(present) > 1:
            findings.append(
                Finding(
                    "error",
                    "roadmap-batch-refused",
                    f"items[{index}] has ambiguous alias fields for {canonical}: {', '.join(present)}",
                    source_label,
                )
            )
    return findings


def _batch_key(value: str) -> str:
    return value.strip().replace("-", "_")


def _batch_scalar(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _batch_list(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return [_batch_scalar(item) for item in value]
    return [_batch_scalar(value)]


def _batch_order(value: object, index: int, source_label: str) -> tuple[int | None, Finding | None]:
    if value in (None, ""):
        return None, None
    if isinstance(value, int) and not isinstance(value, bool):
        return value, None
    text = str(value).strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text), None
    return None, Finding("error", "roadmap-batch-refused", f"items[{index}].order must be an integer", source_label)


def _batch_custom_fields(value: object, index: int, source_label: str) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        return [f"{_batch_key(str(key))}={_batch_scalar(item)}" for key, item in value.items()]
    return _batch_list(value)


def _batch_custom_field_values(value: object, index: int, source_label: str) -> tuple[list[str], list[Finding]]:
    if value in (None, ""):
        return [], []
    if isinstance(value, dict):
        return _batch_custom_fields(value, index, source_label), []
    if isinstance(value, (list, tuple)):
        return [_batch_scalar(item) for item in value], []
    text = _batch_scalar(value)
    return ([text], []) if "=" in text else (
        [],
        [Finding("error", "roadmap-batch-refused", f"items[{index}].custom_fields entries must use key=value", source_label)],
    )


def _batch_duplicate_item_id_errors(requests: tuple[RoadmapRequest, ...], source_label: str) -> list[Finding]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for request in requests:
        if not request.item_id:
            continue
        if request.item_id in seen:
            duplicates.append(request.item_id)
        seen.add(request.item_id)
    return [
        Finding("error", "roadmap-batch-refused", f"batch manifest contains duplicate item id: {item_id}", source_label)
        for item_id in _dedupe_nonempty(duplicates)
    ]


def roadmap_plan_for_request(
    inventory: Inventory,
    request: RoadmapRequest,
    *,
    allowed_missing_paths: set[str] | None = None,
) -> tuple[RoadmapPlan | None, list[Finding]]:
    return _roadmap_plan(inventory, request, allowed_missing_paths=allowed_missing_paths)


def roadmap_plans_for_requests(
    inventory: Inventory,
    requests: tuple[RoadmapRequest, ...],
    *,
    allowed_missing_paths: set[str] | None = None,
) -> tuple[tuple[RoadmapPlan, ...], list[Finding]]:
    batch_plan, errors = _roadmap_batch_plan(inventory, requests, allowed_missing_paths=allowed_missing_paths)
    if errors:
        return (), errors
    if batch_plan is None:
        return (), []
    return batch_plan.plans, []


def roadmap_batch_dry_run_findings(inventory: Inventory, manifest_text: str, source_label: str) -> list[Finding]:
    findings = [
        Finding("info", "roadmap-batch-dry-run", "roadmap batch proposal only; no files were written"),
        _root_posture_finding(inventory),
        Finding("info", "roadmap-target", f"would target roadmap: {ROADMAP_REL}", ROADMAP_REL),
        Finding("info", "roadmap-action", "requested action: add-many", ROADMAP_REL),
        Finding("info", "roadmap-batch-source", f"would read roadmap batch manifest: {source_label}", ROADMAP_REL),
    ]
    requests, manifest_errors = roadmap_batch_requests_from_manifest(manifest_text, source_label)
    if manifest_errors:
        findings.extend(_with_severity(manifest_errors, "warn"))
        findings.append(
            Finding(
                "info",
                "roadmap-validation-posture",
                "batch dry-run refused before apply; fix manifest refusal reasons, then rerun dry-run before writing roadmap changes",
                ROADMAP_REL,
            )
        )
        return findings

    batch_plan, errors = _roadmap_batch_plan(inventory, requests)
    if batch_plan:
        findings.extend(_batch_plan_findings(inventory, batch_plan, apply=False))
        item_ids = tuple(request.item_id for request in requests)
        findings.extend(_roadmap_human_review_gate_findings_from_text(inventory, batch_plan.updated_text, item_ids=item_ids))
        findings.extend(_roadmap_acceptance_readiness_findings_from_text(inventory, batch_plan.updated_text, item_ids=item_ids))
        findings.extend(_batch_route_write_findings(inventory, batch_plan, apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "roadmap-validation-posture",
                "batch dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing roadmap changes",
                ROADMAP_REL,
            )
        )
        return findings
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "roadmap-validation-posture",
            "apply would validate every batch item before writing project/roadmap.md once in an eligible live operating root; dry-run writes no files",
            ROADMAP_REL,
        )
    )
    return findings


def roadmap_batch_apply_findings(
    inventory: Inventory,
    manifest_text: str,
    source_label: str,
    *,
    allowed_missing_paths: set[str] | None = None,
) -> list[Finding]:
    requests, manifest_errors = roadmap_batch_requests_from_manifest(manifest_text, source_label)
    if manifest_errors:
        return manifest_errors

    batch_plan, errors = _roadmap_batch_plan(inventory, requests, allowed_missing_paths=allowed_missing_paths)
    if errors:
        return errors
    assert batch_plan is not None

    if not _batch_plan_has_changes(batch_plan):
        item_ids = ", ".join(request.item_id for request in requests)
        return [
            Finding("info", "roadmap-batch-apply", "roadmap batch apply started"),
            _root_posture_finding(inventory),
            Finding("info", "roadmap-batch-source", f"read roadmap batch manifest: {source_label}", ROADMAP_REL),
            Finding("info", "roadmap-noop", f"roadmap batch already matches requested items: {item_ids}; no file was rewritten", batch_plan.target_rel),
            *_batch_plan_findings(inventory, batch_plan, apply=True),
            *_batch_route_write_findings(inventory, batch_plan, apply=True),
            *_boundary_findings(),
        ]

    operations, tmp_errors = _batch_plan_atomic_operations(inventory, batch_plan)
    if tmp_errors:
        return tmp_errors
    route_writes = _batch_route_write_evidence(batch_plan)
    guard_findings = route_reference_transaction_guard_findings(inventory, route_writes, apply=True)
    if any(finding.severity == "error" for finding in guard_findings):
        return [
            *guard_findings,
            Finding(
                "info",
                "roadmap-validation-posture",
                "roadmap batch apply refused before writing files; review unresolved required route references, then rerun dry-run",
                batch_plan.target_rel,
            ),
        ]
    try:
        cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
    except FileTransactionError as exc:
        return [Finding("error", "roadmap-refused", f"roadmap batch apply failed before all target writes completed: {exc}", batch_plan.target_rel)]

    item_ids = ", ".join(request.item_id for request in requests)
    findings = [
        Finding("info", "roadmap-batch-apply", "roadmap batch apply started"),
        _root_posture_finding(inventory),
        Finding("info", "roadmap-batch-source", f"read roadmap batch manifest: {source_label}", ROADMAP_REL),
        Finding("info", "roadmap-batch-written", f"updated roadmap items with one batch write: {item_ids}", batch_plan.target_rel),
        *_batch_plan_findings(inventory, batch_plan, apply=True),
        *route_write_findings("roadmap-route-write", route_writes, apply=True),
        *guard_findings,
        *_boundary_findings(),
        Finding("info", "roadmap-validation-posture", "run check after apply to verify the live operating root remains healthy; roadmap output is not lifecycle approval", batch_plan.target_rel),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "roadmap-backup-cleanup", warning, batch_plan.target_rel))
    return findings


def roadmap_item_fields(inventory: Inventory, item_id: str) -> dict[str, object]:
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return {}
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return {}
    _items_start, _items_end, items = parse_result[0]
    item = items.get(_normalized_item_id(item_id))
    return dict(item.fields) if item else {}


def roadmap_item_title(inventory: Inventory, item_id: str) -> str:
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return ""
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return ""
    _items_start, _items_end, items = parse_result[0]
    item = items.get(_normalized_item_id(item_id))
    return str(item.title).strip() if item else ""


def roadmap_compacted_item_archived_plan(inventory: Inventory, item_id: str) -> str:
    target_path = inventory.root / ROADMAP_REL
    normalized_item_id = _normalized_item_id(item_id)
    if not target_path.is_file() or not normalized_item_id:
        return ""
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return ""
    _items_start, _items_end, items = parse_result[0]
    if normalized_item_id in items:
        return ""
    return _archived_history_item_plan_map(text).get(normalized_item_id, "")


def roadmap_plan_scope_blockers(
    inventory: Inventory,
    item_id: str,
    fields: dict[str, object] | None = None,
) -> tuple[str, ...]:
    normalized_item_id = _normalized_item_id(item_id)
    if not normalized_item_id:
        return ()
    item_fields = fields if fields is not None else roadmap_item_fields(inventory, normalized_item_id)
    if not item_fields:
        return ()
    status = _normalized_status(item_fields.get("status"))
    if status not in {"accepted", "active"}:
        return ()
    if _field_list(item_fields, "target_artifacts"):
        return ()
    primary_source_rels = (
        _field_scalar(item_fields, "source_incubation"),
        _field_scalar(item_fields, "source_research"),
        *_field_list(item_fields, SOURCE_MEMBERS_FIELD),
    )
    if _field_scalar(item_fields, RELATED_INCUBATION_FIELD) and not any(_normalize_rel(rel) for rel in primary_source_rels):
        return ()
    source_text = _roadmap_scope_source_text(inventory, item_fields)
    if _source_scope_is_recovery_only(source_text):
        return ()
    if _target_artifact_routes_from_scope_text(source_text):
        return ()
    reason = _implementation_scope_reason(item_fields, source_text)
    if not reason:
        return ()
    return (
        f"{reason} has no concrete target_artifacts; update the roadmap item with "
        "--target-artifact <rel-path> before plan opening",
    )


def roadmap_plan_scope_next_safe_command(item_id: str) -> str:
    return IMPLEMENTATION_SCOPE_NEXT_SAFE_TEMPLATE.format(item_id=safe_item_id(_normalized_item_id(item_id), placeholder="<item-id>"))


def roadmap_plan_deliverable_class_blockers(
    inventory: Inventory,
    item_id: str,
    fields: dict[str, object] | None = None,
) -> tuple[str, ...]:
    normalized_item_id = _normalized_item_id(item_id)
    if not normalized_item_id:
        return ()
    item_fields = fields if fields is not None else roadmap_item_fields(inventory, normalized_item_id)
    if not item_fields:
        return ()
    status = _normalized_status(item_fields.get("status"))
    if status not in {"accepted", "active"}:
        return ()
    deliverable_class = roadmap_item_deliverable_class(inventory, item_fields)
    if deliverable_class not in NON_IMPLEMENTATION_DELIVERABLE_CLASSES:
        return ()
    if roadmap_item_explicitly_promotes_implementation(item_fields):
        return ()

    explicit_targets = tuple(_dedupe_nonempty(_field_list(item_fields, "target_artifacts")))
    source_hint_targets = tuple(_target_artifact_routes_from_scope_text(_roadmap_scope_source_text(inventory, item_fields)))
    candidate_targets = explicit_targets or source_hint_targets
    product_targets = tuple(target for target in candidate_targets if _looks_like_product_implementation_route(target))
    if not product_targets:
        return ()
    summarized_targets = _summarize_values(product_targets)
    return (
        (
            f"roadmap item {normalized_item_id!r} has {deliverable_class} deliverable intent but product "
            f"implementation target_artifacts or route hints ({summarized_targets}); retarget the work to "
            "audit/proposal/evidence artifacts or explicitly promote the roadmap metadata before opening a "
            "product implementation plan"
        ),
    )


def roadmap_plan_deliverable_class_next_safe_command(item_id: str) -> str:
    return DELIVERABLE_CLASS_PROMOTION_NEXT_SAFE_TEMPLATE.format(item_id=safe_item_id(_normalized_item_id(item_id), placeholder="<item-id>"))


def roadmap_slice_result_gate_blockers(
    inventory: Inventory,
    item_id: str,
    fields: dict[str, object] | None = None,
) -> tuple[str, ...]:
    normalized_item_id = _normalized_item_id(item_id)
    if not normalized_item_id:
        return ()
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return ()
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return ()
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return ()
    _items_start, _items_end, items = parse_result[0]
    item = items.get(normalized_item_id)
    if item is None:
        return ()
    if fields is not None:
        item = replace(item, fields=fields)
    return _roadmap_slice_result_gate_blockers(inventory, normalized_item_id, item, items)


def roadmap_slice_result_gate_next_safe_command(item_id: str) -> str:
    normalized = safe_item_id(_normalized_item_id(item_id), placeholder="<item-id>")
    return (
        "review the upstream decision packet, then run "
        f"`mylittleharness --root <root> roadmap --dry-run --action update --item-id {normalized}`"
    )


def roadmap_item_deliverable_class(inventory: Inventory, fields: dict[str, object]) -> str:
    explicit = _explicit_deliverable_class(fields)
    if explicit:
        return explicit
    stage = _normalized_status(_field_scalar(fields, "stage"))
    if stage in IMPLEMENTATION_STAGE_VALUES:
        return "implementation"
    stage_class = _text_signals_deliverable_class(stage, source="stage")
    if stage_class:
        return stage_class
    text_fields = " ".join(
        _field_scalar(fields, key)
        for key in ("slice_closeout_boundary", "slice_goal", "verification_summary", "carry_forward")
        if _field_scalar(fields, key)
    )
    direct_class = _text_signals_deliverable_class(text_fields, source="roadmap")
    if direct_class:
        return direct_class
    return ""


def roadmap_item_work_class(inventory: Inventory, fields: dict[str, object], deliverable_class: str | None = None) -> str:
    explicit = _normalized_status(_field_scalar(fields, "work_class"))
    if explicit in IMPLEMENTATION_DELIVERABLE_VALUES:
        return "implementation"
    if explicit in NON_IMPLEMENTATION_WORK_VALUES or explicit in NON_IMPLEMENTATION_DELIVERABLE_CLASSES:
        return "non_implementation"
    normalized_deliverable = _normalized_status(deliverable_class or roadmap_item_deliverable_class(inventory, fields))
    if normalized_deliverable in NON_IMPLEMENTATION_DELIVERABLE_CLASSES:
        return "non_implementation"
    return "implementation"


def roadmap_item_implementation_allowed(fields: dict[str, object], deliverable_class: str | None = None) -> bool:
    raw = _field_scalar(fields, "implementation_allowed")
    explicit = _normalized_status(raw)
    if raw:
        if explicit in IMPLEMENTATION_ALLOWED_TRUTHY:
            return True
        if explicit in IMPLEMENTATION_ALLOWED_FALSEY:
            return False
    if roadmap_item_explicitly_promotes_implementation(fields):
        return True
    return _normalized_status(deliverable_class) not in NON_IMPLEMENTATION_DELIVERABLE_CLASSES


def roadmap_item_promotion_required(fields: dict[str, object], work_class: str | None = None) -> bool:
    raw = _field_scalar(fields, "promotion_required")
    explicit = _normalized_status(raw)
    if raw:
        if explicit in PROMOTION_REQUIRED_TRUTHY:
            return True
        if explicit in PROMOTION_REQUIRED_FALSEY:
            return False
    return str(work_class or "").strip().casefold() == "non_implementation"


def roadmap_item_explicitly_promotes_implementation(fields: dict[str, object]) -> bool:
    explicit = _explicit_deliverable_class(fields)
    if explicit == "implementation":
        return True
    stage = _normalized_status(_field_scalar(fields, "stage"))
    if stage in IMPLEMENTATION_STAGE_VALUES:
        return True
    for field in IMPLEMENTATION_PROMOTION_FIELDS:
        value = _normalized_status(_field_scalar(fields, field))
        if value in IMPLEMENTATION_PROMOTION_TRUTHY:
            return True
    return False


def roadmap_items_for_diagnostics(inventory: Inventory) -> tuple[dict[str, RoadmapItem], list[Finding]]:
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return {}, []
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, [Finding("warn", "roadmap-diagnostics-read", f"project/roadmap.md could not be read: {exc}", ROADMAP_REL)]
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return {}, parse_result[1]
    _items_start, _items_end, items = parse_result[0]
    return dict(items), []


def roadmap_source_incubation_consumers(
    inventory: Inventory,
    source_rel: str,
    *,
    live_only: bool = False,
) -> tuple[str, ...]:
    source_rel = _normalize_rel(source_rel)
    if not source_rel:
        return ()
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return ()
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return ()
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return ()
    _items_start, _items_end, items = parse_result[0]
    consumers: list[str] = []
    for item_id, item in items.items():
        if _normalize_rel(_field_scalar(item.fields, "source_incubation")) != source_rel:
            continue
        status = _field_scalar(item.fields, "status").strip().casefold()
        if live_only and status in TERMINAL_QUEUE_STATUSES:
            continue
        consumers.append(item_id)
    return tuple(consumers)


def roadmap_source_incubation_evidence_findings(
    inventory: Inventory,
    item_ids: tuple[str, ...] = (),
    *,
    apply: bool = False,
    block_apply: bool = False,
    source: str = ROADMAP_REL,
) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []

    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return []
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return []

    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return []
    _items_start, _items_end, items = parse_result[0]

    requested_ids = {_normalized_item_id(item_id) for item_id in item_ids if _normalized_item_id(item_id)}
    findings: list[Finding] = []
    for item_id, item in sorted(items.items(), key=lambda row: (row[1].start, row[0])):
        status = _normalized_status(item.fields.get("status"))
        if requested_ids:
            if item_id not in requested_ids:
                continue
        elif status not in SOURCE_INCUBATION_EVIDENCE_STATUSES:
            continue

        findings.extend(
            _roadmap_source_evidence_findings_for_item(
                inventory,
                item_id,
                item,
                severity="error" if apply and block_apply else "warn",
                source=source,
            )
        )
    if findings:
        findings.append(
            Finding(
                "info",
                "roadmap-source-incubation-boundary",
                "roadmap source evidence diagnostics are read-only and cannot create notes, repair relationships, open plans, archive, stage, commit, or approve lifecycle movement",
                source,
            )
        )
    return findings


def roadmap_source_evidence_blockers(
    inventory: Inventory,
    item_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if inventory.root_kind != "live_operating_root":
        return ()

    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return ()
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return ()

    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return ()
    _items_start, _items_end, items = parse_result[0]

    requested_ids = {_normalized_item_id(item_id) for item_id in item_ids if _normalized_item_id(item_id)}
    blockers: list[str] = []
    for item_id, item in sorted(items.items(), key=lambda row: (row[1].start, row[0])):
        if requested_ids and item_id not in requested_ids:
            continue
        status = _normalized_status(item.fields.get("status"))
        if not requested_ids and status not in SOURCE_INCUBATION_EVIDENCE_STATUSES:
            continue
        for field, rel_path in _roadmap_source_evidence_refs(item.fields):
            problem = _roadmap_source_evidence_problem(inventory, field, rel_path)
            if problem:
                blockers.append(f"roadmap item {item_id!r} {field} evidence {problem}: {rel_path}")
    return tuple(_dedupe_nonempty(blockers))


def roadmap_related_specs_evidence_findings(
    inventory: Inventory,
    item_ids: tuple[str, ...] = (),
) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []

    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return []
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return []

    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return []
    _items_start, _items_end, items = parse_result[0]

    requested_ids = {_normalized_item_id(item_id) for item_id in item_ids if _normalized_item_id(item_id)}
    findings: list[Finding] = []
    for item_id, item in sorted(items.items(), key=lambda row: (row[1].start, row[0])):
        status = _normalized_status(item.fields.get("status"))
        if requested_ids:
            if item_id not in requested_ids:
                continue
        elif status not in SOURCE_INCUBATION_EVIDENCE_STATUSES:
            continue

        for related_spec in _field_list(item.fields, "related_specs"):
            related_spec = _normalize_rel(related_spec)
            if not related_spec:
                continue
            spec_path = inventory.root / related_spec
            if (
                _rel_has_absolute_or_parent_parts(related_spec)
                or _path_escapes_root(inventory.root, spec_path)
                or not spec_path.is_file()
                or spec_path.is_symlink()
            ):
                findings.append(
                    Finding(
                        "warn",
                        "roadmap-related-spec-missing",
                        (
                            f"roadmap item {item_id!r} related_specs target is missing: {related_spec}; "
                            "retarget the item to an existing stable spec, remove the stale related_specs entry, "
                            "or keep docs_decision='uncertain' before relying on roadmap-derived plan docs/write scope"
                        ),
                        ROADMAP_REL,
                        item.start + 1,
                    )
                )
    if findings:
        findings.append(
            Finding(
                "info",
                "roadmap-related-spec-boundary",
                "roadmap related-spec diagnostics are read-only and cannot create specs, retarget roadmap items, change docs_decision, open plans, archive, stage, commit, or approve lifecycle movement",
                ROADMAP_REL,
            )
        )
    return findings


def roadmap_human_review_gate_findings(
    inventory: Inventory,
    item_ids: tuple[str, ...] = (),
) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []

    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return []
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return []

    return _roadmap_human_review_gate_findings_from_text(inventory, text, item_ids=item_ids)


def roadmap_batch_slice_gate_findings(
    inventory: Inventory,
    item_ids: tuple[str, ...],
    *,
    route: str,
    source: str,
    apply: bool = False,
    block_apply: bool = False,
) -> list[Finding]:
    ids = tuple(_dedupe_nonempty(_normalized_item_id(item_id) for item_id in item_ids))
    if inventory.root_kind != "live_operating_root" or len(ids) <= 1:
        return []

    markers = _roadmap_batch_authorization_markers(inventory, ids)
    prefix = "" if apply else "would "
    if markers:
        return [
            Finding(
                "info",
                f"{route}-batch-slice-authorized",
                (
                    f"{prefix}cover multiple roadmap items {list(ids)!r}; explicit reviewed bundle/human-gate "
                    f"marker(s) are present: {', '.join(markers)}"
                ),
                source,
            )
        ]
    accepted_ids = _accepted_batch_item_ids(inventory, ids)
    grouped_markers = _roadmap_grouped_slice_boundary_markers(inventory, ids)
    should_block = apply and block_apply and len(accepted_ids) > 1
    severity = "error" if should_block else "warn"
    verb = "blocked" if severity == "error" else f"{prefix}cover"
    ids_for_message = accepted_ids if severity == "error" else ids
    message = (
        f"{verb} multiple roadmap items {list(ids_for_message)!r} through one {route} route without explicit "
        "reviewed bundle or human-gate evidence; use --only-requested-item for one-slice plan work, "
        "or record bundle_authorization/reviewed_bundle/human_gate_required before intentional batching"
    )
    if grouped_markers:
        message += (
            f"; grouped slice boundary marker(s) present: {', '.join(grouped_markers)} "
            "but those markers are advisory only and do not authorize multi-slice plan apply"
        )
    return [
        Finding(
            severity,
            f"{route}-batch-slice-gate",
            message,
            source,
        )
    ]


def _accepted_batch_item_ids(inventory: Inventory, item_ids: tuple[str, ...]) -> tuple[str, ...]:
    accepted: list[str] = []
    for item_id in item_ids:
        fields = roadmap_item_fields(inventory, item_id)
        if _normalized_status(fields.get("status")) == "accepted":
            accepted.append(item_id)
    return tuple(_dedupe_nonempty(accepted))


def _roadmap_human_review_gate_findings_from_text(
    inventory: Inventory,
    text: str,
    *,
    item_ids: tuple[str, ...] = (),
) -> list[Finding]:
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return []
    _items_start, _items_end, items = parse_result[0]

    requested_ids = {_normalized_item_id(item_id) for item_id in item_ids if _normalized_item_id(item_id)}
    findings: list[Finding] = []
    for item_id, item in sorted(items.items(), key=lambda row: (row[1].start, row[0])):
        status = _normalized_status(item.fields.get("status"))
        if requested_ids:
            if item_id not in requested_ids:
                continue
        elif status not in SOURCE_INCUBATION_EVIDENCE_STATUSES:
            continue

        markers = tuple(field for field in HUMAN_REVIEW_GATE_FIELDS if _human_review_gate_enabled(item.fields.get(field)))
        if markers:
            findings.append(
                Finding(
                    "warn",
                    "roadmap-research-human-gate",
                    (
                        f"roadmap item {item_id!r} declares needs-human-review research marker(s): {', '.join(markers)}; "
                        "pause autonomous implementation, draft the external research request manually outside MyLittleHarness, "
                        "then `research-import`/`research-distill` or an explicit roadmap update before opening or continuing implementation"
                    ),
                    ROADMAP_REL,
                    item.start + 1,
                )
            )
        high_blast_marker = _roadmap_high_blast_gate_marker(item.fields)
        if high_blast_marker:
            findings.append(
                Finding(
                    "warn",
                    "roadmap-high-blast-human-gate",
                    (
                        f"roadmap item {item_id!r} declares high-blast promotion marker {high_blast_marker}; "
                        "pause autonomous promotion or implementation until explicit human acceptance is repo-visible"
                    ),
                    ROADMAP_REL,
                    item.start + 1,
                )
            )
    if findings:
        findings.append(
            Finding(
                "info",
                "roadmap-research-human-gate-boundary",
                "research/high-blast human-gate diagnostics are read-only and cannot call a model, import research, block via hidden state, move lifecycle, archive, stage, commit, or mutate roadmap status",
                ROADMAP_REL,
            )
        )
    return findings


def roadmap_compacted_dependency_archive_evidence_findings(
    inventory: Inventory,
    item_ids: tuple[str, ...] = (),
) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []

    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return []
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return []

    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return []
    _items_start, _items_end, items = parse_result[0]
    archived_history = _archived_history_item_plan_map(text)

    requested_ids = {_normalized_item_id(item_id) for item_id in item_ids if _normalized_item_id(item_id)}
    findings: list[Finding] = []
    for item_id, item in sorted(items.items(), key=lambda row: (row[1].start, row[0])):
        status = _normalized_status(item.fields.get("status"))
        if requested_ids:
            if item_id not in requested_ids:
                continue
        elif status not in SOURCE_INCUBATION_EVIDENCE_STATUSES:
            continue

        dependencies = tuple(
            _dedupe_nonempty(
                (
                    *(_normalized_item_id(value) for value in _field_list(item.fields, "dependencies")),
                    *(_normalized_item_id(value) for value in _field_list(item.fields, "slice_dependencies")),
                )
            )
        )
        for dependency in dependencies:
            if not dependency or dependency in items:
                continue
            archived_plan = archived_history.get(dependency)
            if not archived_plan:
                findings.append(
                    Finding(
                        "warn",
                        "roadmap-compacted-dependency-evidence-missing",
                        (
                            f"roadmap item {item_id!r} depends on {dependency!r}, but no live item or "
                            "Archived Completed History archived-plan evidence was found; recover the source/archive "
                            "evidence or retarget the dependency before relying on roadmap-derived plan input"
                        ),
                        ROADMAP_REL,
                        item.start + 1,
                    )
                )
                continue
            problem = _archived_plan_evidence_problem(inventory, archived_plan)
            if problem:
                findings.append(
                    Finding(
                        "warn",
                        "roadmap-compacted-dependency-archive-missing",
                        (
                            f"roadmap item {item_id!r} depends on compacted done item {dependency!r}, but archived-plan "
                            f"evidence target is {problem}: {archived_plan}; recover the archived plan evidence, retarget "
                            "Archived Completed History, or run `mylittleharness --root <root> memory-hygiene --dry-run --scan` "
                            "before relying on roadmap-derived plan input"
                        ),
                        ROADMAP_REL,
                        item.start + 1,
                    )
                )
    if findings:
        findings.append(
            Finding(
                "info",
                "roadmap-compacted-dependency-boundary",
                "roadmap compacted-dependency evidence diagnostics are read-only and cannot create archive files, repair relationships, open plans, archive, stage, commit, or approve lifecycle movement",
                ROADMAP_REL,
            )
        )
    return findings


def roadmap_done_docs_archive_evidence_findings(
    inventory: Inventory,
    item_ids: tuple[str, ...] = (),
) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []

    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return []
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return []

    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return []
    _items_start, _items_end, items = parse_result[0]

    requested_ids = {_normalized_item_id(item_id) for item_id in item_ids if _normalized_item_id(item_id)}
    findings: list[Finding] = []
    for item_id, item in sorted(items.items(), key=lambda row: (row[1].start, row[0])):
        status = _normalized_status(item.fields.get("status"))
        if requested_ids:
            if item_id not in requested_ids:
                continue
        elif status != "done":
            continue
        if status != "done":
            continue

        docs_decision = _normalized_status(item.fields.get("docs_decision"))
        if docs_decision != "uncertain":
            continue

        evidence_gaps = _done_item_archive_evidence_gaps(inventory, item.fields)
        if not evidence_gaps:
            continue
        findings.append(
            Finding(
                "warn",
                "roadmap-done-docs-archive-evidence-gap",
                (
                    f"done roadmap item {item_id!r} has docs_decision='uncertain' while archive closeout evidence is "
                    f"incomplete: {'; '.join(evidence_gaps)}; run `mylittleharness --root <root> check --focus archive-context`, "
                    "then restore the archive file, retarget archived_plan/related_plan through roadmap or writeback after review, "
                    "or keep closeout language provisional"
                ),
                ROADMAP_REL,
                item.start + 1,
            )
        )
    if findings:
        findings.append(
            Finding(
                "info",
                "roadmap-done-docs-archive-evidence-boundary",
                (
                    "roadmap done docs/archive evidence diagnostics are read-only; they cannot infer a final docs_decision, "
                    "recreate archives, retarget roadmap items, close out, archive, stage, commit, or approve lifecycle movement"
                ),
                ROADMAP_REL,
            )
        )
    return findings


def roadmap_acceptance_readiness_findings(
    inventory: Inventory,
    item_ids: tuple[str, ...] = (),
) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []

    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return []
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding("warn", "roadmap-readiness-read", f"project/roadmap.md could not be read for readiness diagnostics: {exc}", ROADMAP_REL)]
    return _roadmap_acceptance_readiness_findings_from_text(inventory, text, item_ids=item_ids)


def active_plan_roadmap_item_ids(inventory: Inventory) -> tuple[str, ...]:
    state = inventory.state
    if state is None or not state.exists or not state.frontmatter.has_frontmatter or state.frontmatter.errors:
        return ()
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip() != "active":
        return ()
    if _normalize_rel(state_data.get("active_plan")) != DEFAULT_PLAN_REL:
        return ()
    plan = inventory.active_plan_surface
    if plan is None or not plan.exists or plan.path.is_symlink() or not plan.path.is_file():
        return ()
    if not plan.frontmatter.has_frontmatter or plan.frontmatter.errors:
        return ()

    plan_data = plan.frontmatter.data
    return tuple(
        _dedupe_nonempty(
            (
                _normalized_item_id(plan_data.get("primary_roadmap_item")),
                _normalized_item_id(plan_data.get("related_roadmap_item")),
                *(_normalized_item_id(value) for value in _frontmatter_list_values(plan_data.get("covered_roadmap_items"))),
            )
        )
    )


def roadmap_text_with_terminal_related_plan_retargets(
    text: str,
    *,
    active_item_ids: tuple[str, ...] = (),
) -> tuple[str, tuple[str, ...]]:
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return text, ()
    _items_start, _items_end, items = parse_result[0]
    active_ids = {_normalized_item_id(item_id) for item_id in active_item_ids if _normalized_item_id(item_id)}
    edits: list[tuple[int, int, str, str]] = []
    lines = text.splitlines(keepends=True)
    for item_id, item in sorted(items.items(), key=lambda row: row[1].start, reverse=True):
        if not _terminal_stale_active_plan_item(item_id, item, active_ids):
            continue
        fields = dict(item.fields)
        archived_plan = _terminal_related_plan_retarget_value(fields)
        fields["related_plan"] = archived_plan
        if item.style == "legacy":
            replacement = _render_updated_legacy_item_block(lines[item.start : item.end], ("related_plan",), fields)
        else:
            replacement = _render_item_block(item.title, fields)
        edits.append((item.start, item.end, replacement, item_id))

    if not edits:
        return text, ()

    for start, end, replacement, _item_id in edits:
        lines[start:end] = [replacement]
    retargeted = tuple(reversed([item_id for _start, _end, _replacement, item_id in edits]))
    return "".join(lines), retargeted


def roadmap_terminal_related_plan_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return []
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding("warn", "roadmap-terminal-related-plan-read", f"project/roadmap.md could not be read for terminal related_plan diagnostics: {exc}", ROADMAP_REL)]
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return []
    _items_start, _items_end, items = parse_result[0]
    active_ids = set(active_plan_roadmap_item_ids(inventory))
    findings: list[Finding] = []
    for item_id, item in sorted(items.items(), key=lambda row: (row[1].start, row[0])):
        if not _terminal_stale_active_plan_item(item_id, item, active_ids):
            continue
        archived_plan = _terminal_related_plan_retarget_value(item.fields)
        action = f"retarget to archived_plan {archived_plan!r}" if archived_plan else "clear related_plan"
        status = _normalized_status(item.fields.get("status"))
        findings.append(
            Finding(
                "warn",
                "roadmap-terminal-stale-active-plan-link",
                (
                    f"terminal roadmap item {item_id!r} has status {status!r} and related_plan pointing at "
                    f"{DEFAULT_PLAN_REL}; {action} before reusing the active implementation-plan route"
                ),
                ROADMAP_REL,
                item.start + 1,
            )
        )
    return findings


def roadmap_order_namespace_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return []
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding("warn", "roadmap-order-namespace-read", f"project/roadmap.md could not be read for order namespace diagnostics: {exc}", ROADMAP_REL)]
    return _roadmap_order_namespace_findings_from_text(text)


def roadmap_slice_contract_for_item(inventory: Inventory, item_id: str) -> RoadmapSliceContract | None:
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return None
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return None
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return None
    _items_start, _items_end, items = parse_result[0]
    normalized_item_id = _normalized_item_id(item_id)
    primary = items.get(normalized_item_id)
    if primary is None:
        return None

    primary_fields = primary.fields
    execution_slice = _normalized_item_id(primary_fields.get("execution_slice"))
    covered = _covered_item_ids(items, normalized_item_id, primary)
    covered_items = [items[item] for item in covered if item in items]
    slice_goal = _field_scalar(primary_fields, "slice_goal")
    closeout_boundary = _accepted_slice_closeout_boundary(
        primary_fields,
        _field_scalar(primary_fields, "slice_closeout_boundary") or "explicit-closeout-required",
    )
    domain_context = slice_goal or execution_slice or primary.title or normalized_item_id
    deliverable_class = roadmap_item_deliverable_class(inventory, primary_fields) or "implementation"
    work_class = roadmap_item_work_class(inventory, primary_fields, deliverable_class)
    return RoadmapSliceContract(
        primary_roadmap_item=normalized_item_id,
        execution_slice=execution_slice,
        slice_goal=slice_goal,
        covered_roadmap_items=covered,
        domain_context=domain_context,
        target_artifacts=tuple(_dedupe_nonempty(_values_from_items(covered_items, "target_artifacts"))),
        execution_policy="current-phase-only",
        closeout_boundary=closeout_boundary,
        source_incubation=_first_value_from_items([primary], "source_incubation"),
        source_research=_first_value_from_items(covered_items or [primary], "source_research"),
        related_specs=tuple(_dedupe_nonempty(_values_from_items(covered_items or [primary], "related_specs"))),
        source_members=tuple(_dedupe_nonempty(_values_from_items(covered_items or [primary], SOURCE_MEMBERS_FIELD))),
        related_incubation=_first_value_from_items([primary], RELATED_INCUBATION_FIELD),
        work_class=work_class,
        deliverable_class=deliverable_class,
        implementation_allowed=roadmap_item_implementation_allowed(primary_fields, deliverable_class),
        promotion_required=roadmap_item_promotion_required(primary_fields, work_class),
    )


def _accepted_slice_closeout_boundary(fields: dict[str, object], closeout_boundary: str) -> str:
    boundary = closeout_boundary.strip()
    if _normalized_status(fields.get("status")) not in {"accepted", "active"}:
        return boundary
    normalized = re.sub(r"\s+", " ", boundary.casefold())
    stale_markers = (
        "no implementation plan",
        "no active implementation plan",
        "no plan opening",
        "no archive",
        "no lifecycle movement",
        "must attach member links",
        "before implementation",
        "provisional cluster placeholder",
    )
    if not any(marker in normalized for marker in stale_markers):
        return boundary
    return (
        f"{ACCEPTED_BOUNDARY_NORMALIZATION_PREFIX}; original non-authority safety note: "
        f"{boundary}"
    )


def roadmap_synthesis_report_for_item(inventory: Inventory, item_id: str) -> RoadmapSynthesisReport | None:
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return None
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return None
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return None
    _items_start, _items_end, items = parse_result[0]
    normalized_item_id = _normalized_item_id(item_id)
    primary = items.get(normalized_item_id)
    if primary is None:
        return None

    covered = _covered_item_ids(items, normalized_item_id, primary)
    covered_items = [(roadmap_item_id, items[roadmap_item_id]) for roadmap_item_id in covered if roadmap_item_id in items]
    execution_slice = _normalized_item_id(primary.fields.get("execution_slice"))
    target_artifacts = tuple(_dedupe_nonempty(_values_from_items([item for _, item in covered_items], "target_artifacts")))
    related_specs = tuple(_dedupe_nonempty(_values_from_items([item for _, item in covered_items], "related_specs")))
    source_inputs = tuple(
        _dedupe_nonempty(
            [
                *_values_from_items([item for _, item in covered_items], "source_incubation"),
                *_values_from_items([item for _, item in covered_items], RELATED_INCUBATION_FIELD),
                *_values_from_items([item for _, item in covered_items], "source_research"),
                *_values_from_items([item for _, item in covered_items], SOURCE_MEMBERS_FIELD),
            ]
        )
    )
    domain_contexts = tuple(_dedupe_nonempty(_domain_context_for_item(roadmap_item_id, item) for roadmap_item_id, item in covered_items))
    shared_specs = _shared_values([item for _, item in covered_items], "related_specs")
    shared_targets = _shared_values([item for _, item in covered_items], "target_artifacts")
    shared_research = _shared_values([item for _, item in covered_items], "source_research")
    shared_source_members = _shared_values([item for _, item in covered_items], SOURCE_MEMBERS_FIELD)
    shared_incubation = _shared_values([item for _, item in covered_items], "source_incubation")
    shared_related_incubation = _shared_values([item for _, item in covered_items], RELATED_INCUBATION_FIELD)
    shared_sources = shared_research + tuple(
        value
        for value in (*shared_incubation, *shared_related_incubation, *shared_source_members)
        if value not in shared_research
    )
    in_slice_dependencies = _in_slice_dependencies(covered_items, set(covered))
    external_dependencies = _external_dependencies(covered_items, set(covered))
    compacted_dependency_evidence = _compacted_dependency_evidence(
        external_dependencies,
        _archived_history_item_plan_map(text),
    )

    bundle_signals: list[str] = []
    if execution_slice and len(covered) > 1:
        bundle_signals.append(f"shared execution_slice {execution_slice!r} covers {len(covered)} roadmap items")
    if shared_specs:
        bundle_signals.append(f"shared related_specs: {_summarize_values(shared_specs)}")
    if shared_targets:
        bundle_signals.append(f"shared target_artifacts: {len(shared_targets)} shared")
    if shared_sources:
        bundle_signals.append(f"shared source inputs: {_summarize_values(shared_sources)}")
    if in_slice_dependencies:
        bundle_signals.append(f"in-slice dependencies: {_summarize_values(in_slice_dependencies)}")
    if not bundle_signals:
        bundle_signals.append("no shared slice signals beyond the requested roadmap item")

    split_signals: list[str] = []
    if execution_slice:
        split_signals.append(f"items outside execution_slice {execution_slice!r} are excluded from this plan")
    else:
        split_signals.append("no execution_slice is recorded; synthesis is scoped to the requested roadmap item")
    if external_dependencies:
        split_signals.append(f"external dependencies remain outside the slice: {_summarize_values(external_dependencies)}")
    if compacted_dependency_evidence:
        split_signals.append(f"compacted dependency evidence: {_summarize_values(compacted_dependency_evidence)}")
    split_signals.append("bundle/split output is advisory and cannot approve lifecycle movement")

    verification_summary_count = sum(1 for _, item in covered_items if _field_scalar(item.fields, "verification_summary"))
    docs_update_count = sum(1 for _, item in covered_items if _normalized_status(item.fields.get("docs_decision")) == "updated")
    recommended_phase_count = _recommended_phase_count(
        covered_count=len(covered),
        target_count=len(target_artifacts),
        related_spec_count=len(related_specs),
        verification_summary_count=verification_summary_count,
        docs_update_count=docs_update_count,
    )
    docs_pressure = (
        f" and {docs_update_count} docs update {_plural('decision', docs_update_count)}"
        if docs_update_count
        else ""
    )
    return RoadmapSynthesisReport(
        primary_roadmap_item=normalized_item_id,
        execution_slice=execution_slice,
        covered_roadmap_items=covered,
        domain_contexts=domain_contexts,
        target_artifacts=target_artifacts,
        related_specs=related_specs,
        source_inputs=source_inputs,
        bundle_signals=tuple(bundle_signals),
        split_signals=tuple(split_signals),
        in_slice_dependencies=tuple(in_slice_dependencies),
        verification_summary_count=verification_summary_count,
        target_artifact_pressure=(
            f"{len(target_artifacts)} target artifacts across {len(covered)} roadmap items; "
            "report-only sizing signal, not a hard gate"
        ),
        phase_pressure=(
            f"{len(domain_contexts)} {_plural('domain context', len(domain_contexts))} and "
            f"{verification_summary_count} {_plural('verification summary', verification_summary_count)}"
            f"{docs_pressure}; "
            f"candidate plan outline: {recommended_phase_count} {_plural('phase', recommended_phase_count)} or explicit one-shot rationale"
        ),
        docs_update_count=docs_update_count,
    )


def roadmap_dry_run_findings(inventory: Inventory, request: RoadmapRequest) -> list[Finding]:
    findings = [
        Finding("info", "roadmap-dry-run", "roadmap proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    plan, errors = _roadmap_plan(inventory, request)
    findings.append(Finding("info", "roadmap-target", f"would target roadmap: {ROADMAP_REL}", ROADMAP_REL))
    findings.append(Finding("info", "roadmap-action", f"requested action: {request.action or '<empty>'}; item_id: {request.item_id or '<empty>'}", ROADMAP_REL))
    if plan:
        findings.extend(_plan_findings(inventory, plan, apply=False))
        findings.extend(_roadmap_human_review_gate_findings_from_text(inventory, plan.updated_text, item_ids=(request.item_id,)))
        findings.extend(_roadmap_acceptance_readiness_findings_from_text(inventory, plan.updated_text, item_ids=(request.item_id,)))
        findings.extend(_route_write_findings(inventory, plan, apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "roadmap-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing roadmap changes",
                ROADMAP_REL,
            )
        )
        return findings
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "roadmap-validation-posture",
            "apply would write only project/roadmap.md in an eligible live operating root; dry-run writes no files",
            ROADMAP_REL,
        )
    )
    return findings


def roadmap_apply_findings(
    inventory: Inventory,
    request: RoadmapRequest,
    *,
    allowed_missing_paths: set[str] | None = None,
) -> list[Finding]:
    plan, errors = _roadmap_plan(inventory, request, allowed_missing_paths=allowed_missing_paths)
    if errors:
        return errors
    assert plan is not None

    if not _plan_has_changes(plan):
        return [
            Finding("info", "roadmap-apply", "roadmap apply started"),
            _root_posture_finding(inventory),
            Finding("info", "roadmap-noop", "roadmap item already matches requested fields; no file was rewritten", plan.target_rel),
            *_plan_findings(inventory, plan, apply=True),
            *_roadmap_human_review_gate_findings_from_text(inventory, plan.updated_text, item_ids=(request.item_id,)),
            *_roadmap_acceptance_readiness_findings_from_text(inventory, plan.updated_text, item_ids=(request.item_id,)),
            *_route_write_findings(inventory, plan, apply=True),
            *_boundary_findings(),
        ]

    target_write_needed = (not plan.target_existed) or plan.current_text != plan.updated_text
    tmp_path = plan.target_path.with_name(f".{plan.target_path.name}.roadmap.tmp") if target_write_needed else None
    backup_path = plan.target_path.with_name(f".{plan.target_path.name}.roadmap.backup") if tmp_path else None
    relationship_tmp = _relationship_tmp_path(plan.relationship_plan)
    relationship_backup = _relationship_backup_path(plan.relationship_plan) if relationship_tmp else None
    for candidate, label in (
        (tmp_path, "temporary roadmap write path"),
        (backup_path, "temporary roadmap backup path"),
        (relationship_tmp, "temporary relationship write path"),
        (relationship_backup, "temporary relationship backup path"),
    ):
        if candidate and candidate.exists():
            return [Finding("error", "roadmap-refused", f"{label} already exists: {candidate.relative_to(inventory.root).as_posix()}")]

    operations: list[AtomicFileWrite] = []
    if tmp_path and backup_path:
        operations.append(AtomicFileWrite(plan.target_path, tmp_path, plan.updated_text, backup_path))
    if relationship_tmp and relationship_backup and plan.relationship_plan:
        operations.append(AtomicFileWrite(plan.relationship_plan.target_path, relationship_tmp, plan.relationship_plan.updated_text, relationship_backup))
    route_writes = _route_write_evidence(plan)
    guard_findings = route_reference_transaction_guard_findings(inventory, route_writes, apply=True)
    if any(finding.severity == "error" for finding in guard_findings):
        return [
            *guard_findings,
            Finding(
                "info",
                "roadmap-validation-posture",
                "roadmap apply refused before writing files; review unresolved required route references, then rerun dry-run",
                plan.target_rel,
            ),
        ]
    try:
        cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
    except FileTransactionError as exc:
        return [Finding("error", "roadmap-refused", f"roadmap apply failed before all target writes completed: {exc}", plan.target_rel)]

    findings = [
        Finding("info", "roadmap-apply", "roadmap apply started"),
        _root_posture_finding(inventory),
        Finding("info", "roadmap-written", f"updated roadmap item {plan.item_id!r} with action {plan.action!r}", plan.target_rel),
        *_plan_findings(inventory, plan, apply=True),
        *_roadmap_human_review_gate_findings_from_text(inventory, plan.updated_text, item_ids=(request.item_id,)),
        *_roadmap_acceptance_readiness_findings_from_text(inventory, plan.updated_text, item_ids=(request.item_id,)),
        *route_write_findings("roadmap-route-write", route_writes, apply=True),
        *guard_findings,
        *_boundary_findings(),
        Finding("info", "roadmap-validation-posture", "run check after apply to verify the live operating root remains healthy; roadmap output is not lifecycle approval", plan.target_rel),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "roadmap-backup-cleanup", warning, plan.target_rel))
    return findings


def roadmap_normalize_dry_run_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "roadmap-normalize-dry-run", "roadmap normalize proposal only; no files were written"),
        _root_posture_finding(inventory),
        Finding("info", "roadmap-target", f"would target roadmap: {ROADMAP_REL}", ROADMAP_REL),
        Finding("info", "roadmap-action", "requested operation: normalize", ROADMAP_REL),
    ]
    plan, errors = _roadmap_normalize_plan(inventory)
    if plan:
        findings.extend(_plan_findings(inventory, plan, apply=False))
        findings.extend(_route_write_findings(inventory, plan, apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "roadmap-validation-posture",
                "normalize dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing roadmap order changes",
                ROADMAP_REL,
            )
        )
        return findings
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "roadmap-validation-posture",
            "apply would write only project/roadmap.md in an eligible live operating root; dry-run writes no files",
            ROADMAP_REL,
        )
    )
    return findings


def roadmap_normalize_apply_findings(inventory: Inventory) -> list[Finding]:
    plan, errors = _roadmap_normalize_plan(inventory)
    if errors:
        return errors
    assert plan is not None

    if not _plan_has_changes(plan):
        return [
            Finding("info", "roadmap-normalize-apply", "roadmap normalize apply started"),
            _root_posture_finding(inventory),
            Finding("info", "roadmap-noop", "roadmap item blocks already match normalized physical order; no file was rewritten", plan.target_rel),
            *_plan_findings(inventory, plan, apply=True),
            *_route_write_findings(inventory, plan, apply=True),
            *_boundary_findings(),
        ]

    tmp_path = plan.target_path.with_name(f".{plan.target_path.name}.roadmap-normalize.tmp")
    backup_path = plan.target_path.with_name(f".{plan.target_path.name}.roadmap-normalize.backup")
    for candidate, label in (
        (tmp_path, "temporary roadmap normalize write path"),
        (backup_path, "temporary roadmap normalize backup path"),
    ):
        if candidate.exists():
            return [Finding("error", "roadmap-refused", f"{label} already exists: {candidate.relative_to(inventory.root).as_posix()}")]

    try:
        route_writes = _route_write_evidence(plan)
        guard_findings = route_reference_transaction_guard_findings(inventory, route_writes, apply=True)
        if any(finding.severity == "error" for finding in guard_findings):
            return [
                *guard_findings,
                Finding(
                    "info",
                    "roadmap-validation-posture",
                    "roadmap normalize apply refused before writing files; review unresolved required route references, then rerun dry-run",
                    plan.target_rel,
                ),
            ]
        cleanup_warnings = apply_file_transaction(
            [AtomicFileWrite(plan.target_path, tmp_path, plan.updated_text, backup_path)],
            root=inventory.root,
        )
    except FileTransactionError as exc:
        return [Finding("error", "roadmap-refused", f"roadmap normalize apply failed before target write completed: {exc}", plan.target_rel)]

    findings = [
        Finding("info", "roadmap-normalize-apply", "roadmap normalize apply started"),
        _root_posture_finding(inventory),
        Finding("info", "roadmap-normalize-written", "normalized roadmap physical item block order", plan.target_rel),
        *_plan_findings(inventory, plan, apply=True),
        *route_write_findings("roadmap-route-write", route_writes, apply=True),
        *guard_findings,
        *_boundary_findings(),
        Finding("info", "roadmap-validation-posture", "run check after apply to verify the live operating root remains healthy; roadmap output is not lifecycle approval", plan.target_rel),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "roadmap-backup-cleanup", warning, plan.target_rel))
    return findings


def _roadmap_normalize_plan(inventory: Inventory) -> tuple[RoadmapPlan | None, list[Finding]]:
    errors: list[Finding] = []
    errors.extend(_roadmap_context_errors(inventory))
    target_path = inventory.root / ROADMAP_REL
    errors.extend(_roadmap_target_errors(inventory, target_path))
    if errors:
        return None, errors

    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("error", "roadmap-refused", f"roadmap could not be read: {exc}", ROADMAP_REL)]

    return _roadmap_normalize_plan_from_text(inventory, target_path, text)


def _roadmap_normalize_plan_from_text(
    inventory: Inventory,
    target_path: Path,
    text: str,
) -> tuple[RoadmapPlan | None, list[Finding]]:
    parse_result = _parse_roadmap_items(text)
    if parse_result[1]:
        return None, parse_result[1]
    items_start, _items_end, _items = parse_result[0]

    changed_fields: tuple[str, ...] = ()
    updated_text, reordered_item_ids = _normalize_physical_item_block_order(text)
    if reordered_item_ids:
        changed_fields = (*changed_fields, ROADMAP_PHYSICAL_ORDER_FIELD)

    refreshed_text = _refresh_future_execution_slice_queue(updated_text)
    if refreshed_text != updated_text:
        changed_fields = (*changed_fields, FUTURE_QUEUE_FIELD)
        updated_text = refreshed_text

    refreshed_text, compacted_item_ids = _refresh_archived_completed_history(updated_text)
    if refreshed_text != updated_text:
        changed_fields = (*changed_fields, ARCHIVED_HISTORY_FIELD)
        updated_text = refreshed_text

    refreshed_text, retargeted_terminal_item_ids = roadmap_text_with_terminal_related_plan_retargets(
        updated_text,
        active_item_ids=active_plan_roadmap_item_ids(inventory),
    )
    if refreshed_text != updated_text:
        changed_fields = (*changed_fields, TERMINAL_RELATED_PLAN_RETARGET_FIELD)
        updated_text = refreshed_text

    refreshed_text = sync_roadmap_current_posture_section(updated_text)
    if refreshed_text != updated_text:
        changed_fields = (*changed_fields, ROADMAP_CURRENT_POSTURE_FIELD)
        updated_text = refreshed_text

    post_write_errors = _canonical_roadmap_post_write_errors(updated_text, items_start)
    if post_write_errors:
        return None, post_write_errors

    return (
        RoadmapPlan(
            action="normalize",
            item_id="<all>",
            target_rel=ROADMAP_REL,
            target_path=target_path,
            changed_fields=tuple(_dedupe_nonempty(changed_fields)),
            reordered_item_ids=reordered_item_ids,
            compacted_item_ids=compacted_item_ids,
            retargeted_terminal_item_ids=retargeted_terminal_item_ids,
            current_text=text,
            updated_text=updated_text,
        ),
        [],
    )


def _roadmap_batch_plan(
    inventory: Inventory,
    requests: tuple[RoadmapRequest, ...],
    *,
    allowed_missing_paths: set[str] | None = None,
) -> tuple[RoadmapBatchPlan | None, list[Finding]]:
    if not requests:
        return None, []

    errors: list[Finding] = []
    for request in requests:
        errors.extend(_request_errors(inventory, request))
    target_path = inventory.root / ROADMAP_REL
    allow_missing_roadmap = all(request.action == "add" for request in requests)
    errors.extend(_roadmap_target_errors(inventory, target_path, allow_missing=allow_missing_roadmap))
    if errors:
        return None, errors

    target_existed = target_path.exists()
    if target_existed:
        try:
            original_text = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            return None, [Finding("error", "roadmap-refused", f"roadmap could not be read: {exc}", ROADMAP_REL)]
    else:
        original_text = _empty_roadmap_text()

    plans: list[RoadmapPlan] = []
    current_text = original_text
    current_target_existed = target_existed
    for request in requests:
        plan, request_errors = _roadmap_plan_from_text(
            inventory,
            request,
            target_path,
            current_text,
            allowed_missing_paths=allowed_missing_paths or set(),
            allow_empty_items=not current_target_existed and request.action == "add",
            target_existed=current_target_existed,
        )
        if request_errors:
            return None, request_errors
        assert plan is not None
        plans.append(plan)
        current_text = plan.updated_text
        current_target_existed = True

    duplicate_relationship_errors = _batch_relationship_target_errors(tuple(plans))
    if duplicate_relationship_errors:
        return None, duplicate_relationship_errors
    return (
        RoadmapBatchPlan(
            target_rel=ROADMAP_REL,
            target_path=target_path,
            requests=requests,
            plans=tuple(plans),
            current_text=original_text,
            updated_text=current_text,
            target_existed=target_existed,
        ),
        [],
    )


def _roadmap_plan(
    inventory: Inventory,
    request: RoadmapRequest,
    *,
    allowed_missing_paths: set[str] | None = None,
) -> tuple[RoadmapPlan | None, list[Finding]]:
    errors: list[Finding] = []
    errors.extend(_request_errors(inventory, request))
    target_path = inventory.root / ROADMAP_REL
    allow_missing_roadmap = request.action == "add"
    errors.extend(_roadmap_target_errors(inventory, target_path, allow_missing=allow_missing_roadmap))
    if errors:
        return None, errors

    target_existed = target_path.exists()
    if target_existed:
        try:
            text = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            return None, [Finding("error", "roadmap-refused", f"roadmap could not be read: {exc}", ROADMAP_REL)]
    else:
        text = _empty_roadmap_text()

    return _roadmap_plan_from_text(
        inventory,
        request,
        target_path,
        text,
        allowed_missing_paths=allowed_missing_paths or set(),
        allow_empty_items=not target_existed and request.action == "add",
        target_existed=target_existed,
    )


def _roadmap_plan_from_text(
    inventory: Inventory,
    request: RoadmapRequest,
    target_path: Path,
    text: str,
    *,
    allowed_missing_paths: set[str],
    allow_empty_items: bool = False,
    target_existed: bool = True,
) -> tuple[RoadmapPlan | None, list[Finding]]:
    parse_result = _parse_roadmap_items_for_sync(text, allow_empty_items=allow_empty_items)
    if parse_result[1]:
        return None, parse_result[1]
    items_start, items_end, items = parse_result[0]
    existing = items.get(request.item_id)
    archived_history = _archived_history_item_plan_map(text)
    replay_archived_plan = ""
    if request.action == "add" and existing:
        return None, [Finding("error", "roadmap-refused", f"roadmap item id already exists: {request.item_id}", ROADMAP_REL)]
    if request.action == "update" and not existing:
        replay_archived_plan = archived_history.get(request.item_id, "")
        if not replay_archived_plan:
            return None, [Finding("error", "roadmap-refused", f"roadmap item id does not exist: {request.item_id}", ROADMAP_REL)]
        if request.status and request.status not in {"accepted", "active"}:
            return None, [
                Finding(
                    "error",
                    "roadmap-refused",
                    "compacted roadmap item replay requires --status accepted or active; omit --status to default accepted",
                    ROADMAP_REL,
                )
            ]
        problem = _archived_plan_evidence_problem(inventory, replay_archived_plan)
        if problem:
            return None, [
                Finding(
                    "error",
                    "roadmap-refused",
                    f"compacted roadmap item {request.item_id!r} archived-plan evidence is {problem}: {replay_archived_plan}",
                    ROADMAP_REL,
                )
            ]

    errors: list[Finding] = []
    errors.extend(_relationship_errors(inventory, request, set(items), archived_history, allowed_missing_paths or set()))
    if errors:
        return None, errors
    relationship_plan = None
    related_incubation_source = ""
    related_incubation_reason = ""
    source_incubation_field: str | None = request.source_incubation if request.source_incubation else None
    related_incubation_field: str | None = "" if request.source_incubation else None
    if request.source_incubation:
        source_missing_but_allowed = (
            _normalize_rel(request.source_incubation) in allowed_missing_paths
            and not (inventory.root / request.source_incubation).exists()
        )
        related_incubation_reason = _reused_source_incubation_reason(inventory, request.source_incubation, request.item_id)
        if related_incubation_reason:
            related_incubation_source = request.source_incubation
            related_incubation_field = related_incubation_source
            source_incubation_field = ""
        elif source_missing_but_allowed:
            relationship_plan = None
        else:
            relationship_plan, relationship_errors = relationship_update_plan(
                inventory,
                request.source_incubation,
                {
                    "related_roadmap": ROADMAP_REL,
                    "related_roadmap_item": request.item_id,
                    "promoted_to": ROADMAP_REL,
                },
            )
            if relationship_errors:
                return None, relationship_errors
            relationship_plan = _relationship_plan_without_queued_active_plan_leak(inventory, request, relationship_plan)

    lines = text.splitlines(keepends=True)
    replayed_item_ids: tuple[str, ...] = ()
    if request.action == "add":
        if items_start < 0:
            return None, [
                Finding(
                    "error",
                    "roadmap-refused",
                    "legacy top-level roadmap sections support update only; add requires a canonical ## Items section",
                    ROADMAP_REL,
                )
            ]
        fields = _new_item_fields(
            request,
            source_incubation=source_incubation_field,
            related_incubation=related_incubation_source,
        )
        block = _render_item_block(request.title, fields)
        insert_at = items_end
        if insert_at > 0 and lines[insert_at - 1].strip():
            block = "\n" + block
        updated_lines = [*lines[:insert_at], block, *lines[insert_at:]]
        changed_fields = tuple(_rendered_item_field_keys(fields))
        updated_text = "".join(updated_lines)
    elif replay_archived_plan:
        fields = _compacted_replay_item_fields(
            request,
            items,
            replay_archived_plan,
            source_incubation=source_incubation_field,
            related_incubation=related_incubation_field or "",
        )
        block = _render_item_block(_compacted_replay_title(inventory, request, replay_archived_plan), fields)
        insert_at = items_end
        if insert_at > 0 and lines[insert_at - 1].strip():
            block = "\n" + block
        updated_lines = [*lines[:insert_at], block, *lines[insert_at:]]
        changed_fields = tuple(_dedupe_nonempty((COMPACTED_ITEM_REPLAY_FIELD, *_rendered_item_field_keys(fields))))
        updated_text = "".join(updated_lines)
        replayed_item_ids = (request.item_id,)
    else:
        assert existing is not None
        fields = _updated_item_fields(
            existing.fields,
            request,
            source_incubation=source_incubation_field,
            related_incubation=related_incubation_field,
        )
        changed_fields = tuple(
            field
            for field in _item_field_keys_for_comparison(existing.fields, fields)
            if existing.fields.get(field, _empty_field_value(field)) != fields.get(field, _empty_field_value(field))
        )
        if changed_fields:
            changed_fields = tuple(_dedupe_nonempty((*changed_fields, *_empty_strict_fields_present(existing.fields))))
        if changed_fields:
            block = (
                _render_updated_legacy_item_block(lines[existing.start : existing.end], changed_fields, fields)
                if existing.style == "legacy"
                else _render_item_block(existing.title, fields)
            )
            updated_text = "".join([*lines[: existing.start], block, *lines[existing.end :]])
        else:
            updated_text = text

    updated_text, reordered_item_ids = _order_accepted_item_blocks(updated_text)
    if reordered_item_ids:
        changed_fields = (*changed_fields, ACCEPTED_ITEM_ORDER_FIELD)

    refreshed_text = _refresh_future_execution_slice_queue(updated_text)
    if refreshed_text != updated_text:
        changed_fields = (*changed_fields, FUTURE_QUEUE_FIELD)
        updated_text = refreshed_text

    refreshed_text, compacted_item_ids = _refresh_archived_completed_history(updated_text)
    if refreshed_text != updated_text:
        changed_fields = (*changed_fields, ARCHIVED_HISTORY_FIELD)
        updated_text = refreshed_text

    if replayed_item_ids:
        refreshed_text = _without_archived_history_entries(updated_text, replayed_item_ids)
        if refreshed_text != updated_text:
            changed_fields = (*changed_fields, ARCHIVED_HISTORY_FIELD)
            updated_text = refreshed_text

    refreshed_text, retargeted_terminal_item_ids = roadmap_text_with_terminal_related_plan_retargets(
        updated_text,
        active_item_ids=active_plan_roadmap_item_ids(inventory),
    )
    if refreshed_text != updated_text:
        changed_fields = (*changed_fields, TERMINAL_RELATED_PLAN_RETARGET_FIELD)
        updated_text = refreshed_text

    refreshed_text = sync_roadmap_current_posture_section(updated_text)
    if refreshed_text != updated_text:
        changed_fields = (*changed_fields, ROADMAP_CURRENT_POSTURE_FIELD)
        updated_text = refreshed_text

    post_write_errors = _canonical_roadmap_post_write_errors(updated_text, items_start)
    if post_write_errors:
        return None, post_write_errors
    policy_errors = _active_plan_roadmap_mutation_policy_findings(inventory, request, changed_fields)

    plan = RoadmapPlan(
        action=request.action,
        item_id=request.item_id,
        target_rel=ROADMAP_REL,
        target_path=target_path,
        changed_fields=changed_fields,
        reordered_item_ids=reordered_item_ids,
        compacted_item_ids=compacted_item_ids,
        retargeted_terminal_item_ids=retargeted_terminal_item_ids,
        current_text=text,
        updated_text=updated_text,
        target_existed=target_existed,
        relationship_plan=relationship_plan,
        related_incubation_source=related_incubation_source,
        related_incubation_reason=related_incubation_reason,
        replayed_item_ids=replayed_item_ids,
    )
    return plan, policy_errors


def _request_errors(inventory: Inventory, request: RoadmapRequest) -> list[Finding]:
    errors: list[Finding] = []
    errors.extend(_roadmap_context_errors(inventory))
    if request.action not in {"add", "update"}:
        errors.append(Finding("error", "roadmap-refused", "--action must be one of: add, update"))
    if not request.item_id or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", request.item_id):
        errors.append(Finding("error", "roadmap-refused", "--item-id must be a lowercase ASCII id using letters, numbers, and hyphens only"))
    if request.action == "add":
        if not request.title:
            errors.append(Finding("error", "roadmap-refused", "--title is required for --action add"))
        if not request.status:
            errors.append(Finding("error", "roadmap-refused", "--status is required for --action add"))
        if request.order is None:
            errors.append(Finding("error", "roadmap-refused", "--order is required for --action add"))
    if request.status and request.status not in ROADMAP_STATUS_VALUES:
        errors.append(Finding("error", "roadmap-refused", f"--status must be one of: {', '.join(sorted(ROADMAP_STATUS_VALUES))}"))
    if request.docs_decision and request.docs_decision not in DOCS_DECISION_VALUES:
        errors.append(Finding("error", "roadmap-refused", f"--docs-decision must be one of: {', '.join(sorted(DOCS_DECISION_VALUES))}"))
    if request.order is not None and request.order < 0:
        errors.append(Finding("error", "roadmap-refused", "--order must be a non-negative integer"))
    if request.execution_slice and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", request.execution_slice):
        errors.append(Finding("error", "roadmap-refused", "--execution-slice must be a lowercase ASCII id using letters, numbers, and hyphens only"))
    for field, value in _scalar_request_fields(request).items():
        if "\n" in value or "\r" in value or "`" in value:
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} must be a single line without backticks", ROADMAP_REL))
    errors.extend(_clear_field_errors(request))
    errors.extend(_custom_field_errors(request.custom_fields))
    for field, values in _item_id_list_request_fields(request).items():
        if len(values) != len(set(values)):
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} contains duplicate item ids", ROADMAP_REL))
        for value in values:
            if not value or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} values must be lowercase ASCII item ids", ROADMAP_REL))
            if value == request.item_id and field != "slice_members":
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} cannot point at the target item itself: {value}", ROADMAP_REL))
    for field, values in _path_list_request_fields(request).items():
        if len(values) != len(set(values)):
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} contains duplicate paths", ROADMAP_REL))
        for value in values:
            if "\n" in value or "\r" in value or "`" in value:
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} values must be single-line paths without backticks", ROADMAP_REL))
    for field, values in _artifact_list_request_fields(request).items():
        if len(values) != len(set(values)):
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} contains duplicate paths", ROADMAP_REL))
        for value in values:
            if "\n" in value or "\r" in value or "`" in value:
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} values must be single-line paths without backticks", ROADMAP_REL))
            if _rel_has_absolute_or_parent_parts(value):
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} values must be root-relative paths without parent segments", ROADMAP_REL))
    return errors


def _active_plan_roadmap_mutation_policy_findings(
    inventory: Inventory,
    request: RoadmapRequest,
    changed_fields: tuple[str, ...],
) -> list[Finding]:
    if not _inventory_has_active_plan(inventory):
        return []
    active_ids = set(active_plan_roadmap_item_ids(inventory))
    if not active_ids or request.item_id in active_ids:
        return []
    direct_fields = tuple(
        field
        for field in changed_fields
        if field
        and field
        in ACTIVE_PLAN_ROADMAP_PROMOTION_FIELDS
    )
    if not direct_fields:
        return []
    active_label = ", ".join(sorted(active_ids))
    changed_label = ", ".join(direct_fields)
    return [
        Finding(
            "error",
            "roadmap-active-plan-intake-policy",
            (
                f"active plan is open for roadmap item(s): {active_label}; requested roadmap {request.action} "
                f"would change item {request.item_id!r} outside active-plan coverage (changed_fields={changed_label}). "
                "Capture candidate evidence through meta-feedback/incubation now, or wait until plan_status=none before "
                "accepted roadmap status/order/dependency/next-item promotion; "
                f"next_safe_command={_active_plan_roadmap_mutation_next_safe_command(request)}"
            ),
            ROADMAP_REL,
        )
    ]


def _active_plan_roadmap_mutation_next_safe_command(request: RoadmapRequest) -> str:
    if request.action == "add":
        after_close = (
            "mylittleharness --root <root> roadmap --dry-run --action add "
            f"--item-id {request.item_id} --title <title> --status <status> --order <order>"
        )
    else:
        after_close = (
            "mylittleharness --root <root> roadmap --dry-run --action update "
            f"--item-id {request.item_id} [reviewed fields]"
        )
    return f"mylittleharness --root <root> meta-feedback --dry-run ...; after plan_status=none run {after_close}"


def _inventory_has_active_plan(inventory: Inventory) -> bool:
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return str(state_data.get("plan_status") or "").strip().casefold() == "active"


def _roadmap_context_errors(inventory: Inventory) -> list[Finding]:
    errors: list[Finding] = []
    if inventory.root_kind == "product_source_fixture":
        errors.append(Finding("error", "roadmap-refused", "target is a product-source compatibility fixture; roadmap --apply is refused", ROADMAP_REL))
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(Finding("error", "roadmap-refused", "target is fallback/archive or generated-output evidence; roadmap --apply is refused", ROADMAP_REL))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "roadmap-refused", f"target root kind is {inventory.root_kind}; roadmap requires a live operating root", ROADMAP_REL))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "roadmap-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "roadmap-refused", "project-state.md frontmatter is required for roadmap apply", state.rel_path))
    elif state.frontmatter.errors:
        errors.append(Finding("error", "roadmap-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "roadmap-refused", "project-state.md is not a regular file", state.rel_path))
    elif state.path.is_symlink():
        errors.append(Finding("error", "roadmap-refused", "project-state.md is a symlink", state.rel_path))
    return errors


def _roadmap_target_errors(inventory: Inventory, target_path: Path, *, allow_missing: bool = False) -> list[Finding]:
    errors: list[Finding] = []
    if _path_escapes_root(inventory.root, target_path):
        errors.append(Finding("error", "roadmap-refused", "roadmap path escapes the target root", ROADMAP_REL))
        return errors
    for parent in _parents_between(inventory.root, target_path.parent):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "roadmap-refused", f"roadmap path contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "roadmap-refused", f"roadmap path contains a non-directory segment: {rel}", rel))
    if not target_path.exists():
        if allow_missing:
            return errors
        errors.append(Finding("error", "roadmap-refused", "project/roadmap.md is missing", ROADMAP_REL))
    elif target_path.is_symlink():
        errors.append(Finding("error", "roadmap-refused", "project/roadmap.md is a symlink", ROADMAP_REL))
    elif not target_path.is_file():
        errors.append(Finding("error", "roadmap-refused", "project/roadmap.md is not a regular file", ROADMAP_REL))
    return errors


def _parse_roadmap_items(text: str, *, allow_empty_items: bool = False) -> tuple[tuple[int, int, dict[str, RoadmapItem]], list[Finding]]:
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        closing_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                closing_index = index
                break
        if closing_index is None:
            return (0, 0, {}), [Finding("error", "roadmap-refused", "project/roadmap.md frontmatter is malformed", ROADMAP_REL)]

    items_heading = None
    for index, line in enumerate(lines):
        if re.match(r"^##\s+Items\s*$", line.strip()):
            items_heading = index
            break
    if items_heading is None:
        return (0, 0, {}), [Finding("error", "roadmap-refused", "project/roadmap.md must contain a ## Items section", ROADMAP_REL)]

    items_end = len(lines)
    for index in range(items_heading + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[index].strip()):
            items_end = index
            break

    block_starts = [index for index in range(items_heading + 1, items_end) if re.match(r"^###\s+.+\s*$", lines[index].strip())]
    if not block_starts:
        if allow_empty_items:
            return (items_heading + 1, items_end, {}), []
        return (0, 0, {}), [Finding("error", "roadmap-refused", "project/roadmap.md ## Items section has no managed item blocks", ROADMAP_REL)]

    items: dict[str, RoadmapItem] = {}
    errors: list[Finding] = []
    for position, start in enumerate(block_starts):
        end = block_starts[position + 1] if position + 1 < len(block_starts) else items_end
        title = re.sub(r"^###\s+", "", lines[start].strip()).strip()
        fields = _parse_item_fields(lines[start:end])
        item_id = fields.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(Finding("error", "roadmap-refused", f"roadmap item block lacks an id field: {title}", ROADMAP_REL, start + 1))
            continue
        if item_id in items:
            errors.append(Finding("error", "roadmap-refused", f"duplicate roadmap item id: {item_id}", ROADMAP_REL, start + 1))
            continue
        items[item_id] = RoadmapItem(title=title, fields=fields, start=start, end=end)
    if errors:
        return (0, 0, {}), errors
    return (items_heading + 1, items_end, items), []


def _parse_roadmap_items_for_sync(text: str, *, allow_empty_items: bool = False) -> tuple[tuple[int, int, dict[str, RoadmapItem]], list[Finding]]:
    parse_result = _parse_roadmap_items(text, allow_empty_items=allow_empty_items)
    if not parse_result[1]:
        return parse_result
    if allow_empty_items:
        return parse_result
    findings = parse_result[1]
    if len(findings) != 1 or "must contain a ## Items section" not in findings[0].message:
        return parse_result

    legacy_result = _parse_legacy_roadmap_items(text)
    if legacy_result[1] or not legacy_result[0][2]:
        return parse_result
    return legacy_result


def _canonical_roadmap_post_write_errors(text: str, items_start: int) -> list[Finding]:
    if items_start < 0:
        return []
    parse_result = _parse_roadmap_items(text)
    if not parse_result[1]:
        return []
    return [
        Finding(
            finding.severity,
            finding.code,
            f"roadmap post-write validation failed: {finding.message}",
            finding.source,
            finding.line,
        )
        for finding in parse_result[1]
    ]


def _parse_legacy_roadmap_items(text: str) -> tuple[tuple[int, int, dict[str, RoadmapItem]], list[Finding]]:
    lines = text.splitlines(keepends=True)
    content_start = 0
    if lines and lines[0].strip() == "---":
        closing_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                closing_index = index
                break
        if closing_index is None:
            return (0, 0, {}), [Finding("error", "roadmap-refused", "project/roadmap.md frontmatter is malformed", ROADMAP_REL)]
        content_start = closing_index + 1

    h2_starts = [index for index in range(content_start, len(lines)) if re.match(r"^##\s+\S", lines[index].strip())]
    block_starts = [index for index in h2_starts if _legacy_item_heading_match(lines[index])]
    if not block_starts:
        return (0, 0, {}), []

    items: dict[str, RoadmapItem] = {}
    errors: list[Finding] = []
    for start in block_starts:
        end = next((next_start for next_start in h2_starts if next_start > start), len(lines))
        heading_match = _legacy_item_heading_match(lines[start])
        assert heading_match is not None
        heading_id = _normalized_item_id(heading_match.group("id"))
        title = re.sub(r"^##\s+", "", lines[start].strip()).strip()
        fields = _parse_legacy_item_fields(lines[start:end])
        item_id = _normalized_item_id(fields.get("id") or heading_id)
        if not item_id:
            errors.append(Finding("error", "roadmap-refused", f"legacy roadmap section lacks an id field: {title}", ROADMAP_REL, start + 1))
            continue
        if item_id in items:
            errors.append(Finding("error", "roadmap-refused", f"duplicate roadmap item id: {item_id}", ROADMAP_REL, start + 1))
            continue
        fields["id"] = item_id
        items[item_id] = RoadmapItem(title=title, fields=fields, start=start, end=end, style="legacy")
    if errors:
        return (0, 0, {}), errors
    return (-1, len(lines), items), []


def _legacy_item_heading_match(line: str) -> re.Match[str] | None:
    return re.match(r"^##\s+(?P<id>RM-[A-Za-z0-9][A-Za-z0-9-]*)\b.*$", line.strip(), re.IGNORECASE)


def _refresh_future_execution_slice_queue(text: str) -> str:
    lines = text.splitlines(keepends=True)
    bounds = _h2_section_bounds(lines, FUTURE_QUEUE_TITLE)
    if bounds is None:
        return text

    parse_result = _parse_roadmap_items(text)
    if parse_result[1]:
        return text
    _items_start, _items_end, items = parse_result[0]

    start, end = bounds
    newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
    accepted = _future_queue_status_items(items, "accepted")
    proposed = _future_queue_status_items(items, "proposed")
    replacement = [lines[start], *_future_queue_body_lines(accepted, proposed, newline)]
    updated_text = "".join([*lines[:start], *replacement, *lines[end:]])
    return text if updated_text == text else updated_text


def _refresh_archived_completed_history(text: str) -> tuple[str, tuple[str, ...]]:
    parse_result = _parse_roadmap_items(text)
    if parse_result[1]:
        return text, ()
    items_start, _items_end, items = parse_result[0]
    done_items = [
        (item_id, item)
        for item_id, item in sorted(items.items(), key=lambda row: (row[1].start, row[0]))
        if _normalized_status(item.fields.get("status")) == "done"
    ]
    excess = len(done_items) - DETAILED_DONE_TAIL_LIMIT
    if excess <= 0:
        return text, ()

    to_compact: list[tuple[str, RoadmapItem]] = []
    for item_id, item in done_items:
        if excess <= 0:
            break
        if not _roadmap_item_has_compaction_evidence(item):
            continue
        to_compact.append((item_id, item))
        excess -= 1
    if not to_compact:
        return text, ()

    lines = text.splitlines(keepends=True)
    compacted_ids = tuple(item_id for item_id, _item in to_compact)
    remove_ranges = tuple((item.start, item.end) for _item_id, item in to_compact)
    kept_lines = [line for index, line in enumerate(lines) if not any(start <= index < end for start, end in remove_ranges)]
    kept_lines, history_entries = _sync_compacted_history_entries(kept_lines, to_compact)
    if history_entries:
        kept_lines = _with_archived_history_entries(
            kept_lines,
            history_entries,
            fallback_insert_at=_items_section_end_index(kept_lines, fallback_insert_at=items_start),
        )
    return "".join(kept_lines), compacted_ids


def _roadmap_item_has_compaction_evidence(item: RoadmapItem) -> bool:
    archived_plan = _field_scalar(item.fields, "archived_plan")
    docs_decision = _field_scalar(item.fields, "docs_decision")
    return (
        archived_plan.startswith("project/archive/plans/")
        and bool(_field_scalar(item.fields, "verification_summary"))
        and docs_decision in {"updated", "not-needed"}
    )


def _sync_compacted_history_entries(lines: list[str], items: list[tuple[str, RoadmapItem]]) -> tuple[list[str], list[str]]:
    lines = list(lines)
    bounds = _h2_section_bounds(lines, ARCHIVED_HISTORY_TITLE)
    expected = {
        item_id: _field_scalar(item.fields, "archived_plan")
        for item_id, item in items
        if _field_scalar(item.fields, "archived_plan")
    }
    if bounds:
        start, end = bounds
        for index in range(start + 1, end):
            match = _compacted_history_entry_match(lines[index])
            if not match:
                continue
            item_id = _normalized_item_id(match.group(1))
            archived_plan = expected.get(item_id)
            if not archived_plan or _normalize_rel(match.group(2)) == archived_plan:
                continue
            lines[index] = _compacted_history_entry_line(item_id, archived_plan, _line_newline(lines[index]))
    existing_history = "".join(lines[bounds[0] + 1 : bounds[1]]) if bounds else ""
    entries: list[str] = []
    for item_id, item in items:
        if f"`{item_id}`" in existing_history:
            continue
        archived_plan = _field_scalar(item.fields, "archived_plan")
        entries.append(_compacted_history_entry_line(item_id, archived_plan))
    return lines, entries


def _compacted_history_entry_match(line: str) -> re.Match[str] | None:
    return re.match(r"-\s+Compacted done roadmap item `([^`]+)`:\s+archived plan `([^`]+)`\.", line.strip())


def _compacted_history_entry_line(item_id: str, archived_plan: str, newline: str = "\n") -> str:
    return f"- Compacted done roadmap item `{item_id}`: archived plan `{archived_plan}`.{newline}"


def _line_newline(line: str) -> str:
    return "\r\n" if line.endswith("\r\n") else "\n"


def _archived_history_item_plan_map(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for match in re.finditer(r"-\s+Compacted done roadmap item `([^`]+)`:\s+archived plan `([^`]+)`\.", text):
        item_id = _normalized_item_id(match.group(1))
        archived_plan = _normalize_rel(match.group(2))
        if item_id and archived_plan:
            entries[item_id] = archived_plan
    return entries


def _without_archived_history_entries(text: str, item_ids: tuple[str, ...]) -> str:
    normalized_item_ids = {_normalized_item_id(item_id) for item_id in item_ids if _normalized_item_id(item_id)}
    if not normalized_item_ids:
        return text
    lines = text.splitlines(keepends=True)
    updated_lines: list[str] = []
    for line in lines:
        match = _compacted_history_entry_match(line)
        if match and _normalized_item_id(match.group(1)) in normalized_item_ids:
            continue
        updated_lines.append(line)
    return "".join(updated_lines)


def _archived_plan_evidence_problem(inventory: Inventory, archived_plan: str) -> str:
    if _rel_has_absolute_or_parent_parts(archived_plan):
        return "not a safe root-relative path"
    path = inventory.root / archived_plan
    if _path_escapes_root(inventory.root, path):
        return "outside the target root"
    if not path.exists():
        return "missing"
    if path.is_symlink():
        return "a symlink"
    if not path.is_file():
        return "not a regular file"
    return ""


def _done_item_archive_evidence_gaps(inventory: Inventory, fields: dict[str, object]) -> tuple[str, ...]:
    gaps: list[str] = []
    archived_plan = _normalize_rel(_field_scalar(fields, "archived_plan"))
    related_plan = _normalize_rel(_field_scalar(fields, "related_plan"))

    if not archived_plan:
        gaps.append("archived_plan metadata is empty")
    else:
        problem = _archived_plan_evidence_problem(inventory, archived_plan)
        if problem:
            gaps.append(f"archived_plan target is {problem}: {archived_plan}")

    if related_plan.startswith("project/archive/plans/") and related_plan != archived_plan:
        problem = _archived_plan_evidence_problem(inventory, related_plan)
        if problem:
            gaps.append(f"related_plan archive target is {problem}: {related_plan}")

    return tuple(_dedupe_nonempty(gaps))


def _compacted_dependency_evidence(dependencies: list[str], archived_history: dict[str, str]) -> list[str]:
    return _dedupe_nonempty(
        f"{dependency} -> {archived_history[dependency]}"
        for dependency in dependencies
        if dependency in archived_history
    )


def _with_archived_history_entries(lines: list[str], entries: list[str], *, fallback_insert_at: int) -> list[str]:
    bounds = _h2_section_bounds(lines, ARCHIVED_HISTORY_TITLE)
    if bounds is None:
        section = [
            "## Archived Completed History\n",
            "\n",
            "Detailed done roadmap item blocks compacted out of the live tail remain available through archived plans.\n",
            "\n",
            *entries,
            "\n",
        ]
        insert_at = max(0, min(fallback_insert_at, len(lines)))
        if insert_at > 0 and lines[insert_at - 1].strip():
            section.insert(0, "\n")
        return [*lines[:insert_at], *section, *lines[insert_at:]]

    _start, end = bounds
    insertion = [*entries]
    if end > 0 and lines[end - 1].strip():
        insertion.insert(0, "\n")
    insertion.append("\n")
    return [*lines[:end], *insertion, *lines[end:]]


def _items_section_end_index(lines: list[str], *, fallback_insert_at: int) -> int:
    bounds = _h2_section_bounds(lines, "Items")
    if bounds is None:
        return max(0, min(fallback_insert_at, len(lines)))
    return bounds[1]


def _h2_section_bounds(lines: list[str], title: str) -> tuple[int, int] | None:
    start = None
    title_pattern = re.compile(rf"^##\s+{re.escape(title)}\s*$")
    for index, line in enumerate(lines):
        if title_pattern.match(line.strip()):
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[index].strip()):
            end = index
            break
    return start, end


def _future_queue_bullet_item_ids(line: str) -> tuple[str, ...]:
    if not re.match(r"^\s*-\s+", line):
        return ()
    match = re.search(r"\bItems:\s*(.+)$", line)
    if not match:
        return ()
    return tuple(_dedupe_nonempty(_normalized_item_id(value) for value in re.findall(r"`([^`]+)`", match.group(1))))


def _future_queue_status_items(items: dict[str, RoadmapItem], status: str) -> tuple[tuple[str, RoadmapItem], ...]:
    normalized_status = _normalized_status(status)
    matching = [
        (item_id, item)
        for item_id, item in items.items()
        if _normalized_status(item.fields.get("status")) == normalized_status
    ]
    return tuple(sorted(matching, key=lambda row: (_order_sort_key(row[1]), row[1].start, row[0])))


def _future_queue_body_lines(
    accepted: tuple[tuple[str, RoadmapItem], ...],
    proposed: tuple[tuple[str, RoadmapItem], ...],
    newline: str,
) -> list[str]:
    lines = [newline]
    if accepted:
        lines.append(f"{_future_queue_span_sentence('current accepted tail', accepted)}{newline}")
        lines.append(newline)
        lines.append(f"Accepted execution slice order:{newline}")
        lines.extend(_future_queue_item_lines(accepted, newline))
    else:
        lines.append(
            "No future execution slice is currently queued in this roadmap. Completed or retired slice history lives in archived plans and in terminal item metadata below."
            f"{newline}"
        )

    if proposed:
        lines.append(newline)
        lines.append(f"{_future_queue_span_sentence('proposed later tail', proposed)} Proposed execution slices are not queued until accepted.{newline}")
        lines.append(newline)
        lines.append(f"Proposed execution slice order:{newline}")
        lines.extend(_future_queue_item_lines(proposed, newline))

    lines.append(newline)
    lines.append(
        "Open the next slice only through an explicit plan request or accepted roadmap update. Incubation notes remain possible inputs, not queued work by themselves."
        f"{newline}"
    )
    lines.append(newline)
    return lines


def _future_queue_span_sentence(label: str, rows: tuple[tuple[str, RoadmapItem], ...]) -> str:
    first_id, first_item = rows[0]
    last_id, last_item = rows[-1]
    if len(rows) == 1:
        return f"The {label} contains `{first_id}` at order `{_future_queue_order_text(first_item)}`."
    return (
        f"The {label} starts at `{first_id}` at order `{_future_queue_order_text(first_item)}` "
        f"and currently runs through `{last_id}` at order `{_future_queue_order_text(last_item)}`."
    )


def _future_queue_item_lines(rows: tuple[tuple[str, RoadmapItem], ...], newline: str) -> list[str]:
    rendered: list[str] = []
    for execution_slice, slice_rows in _future_queue_slice_groups(rows):
        if len(slice_rows) > 1:
            order_range = _future_queue_order_range_text(slice_rows)
            detail = _future_queue_slice_detail(slice_rows)
            item_refs = ", ".join(f"`{item_id}`" for item_id, _item in slice_rows)
            suffix_parts = [part for part in (detail, f"Items: {item_refs}") if part]
            suffix = f" - {'; '.join(suffix_parts)}" if suffix_parts else ""
            rendered.append(f"- orders `{order_range}`: `{execution_slice}` ({len(slice_rows)} items){suffix}{newline}")
            continue
        item_id, item = slice_rows[0]
        execution_slice = _normalized_item_id(item.fields.get("execution_slice")) or item_id
        detail = _future_queue_detail(item)
        suffix = f" - {detail}" if detail else ""
        rendered.append(f"- order `{_future_queue_order_text(item)}`: `{item_id}` (`{execution_slice}`){suffix}{newline}")
    return rendered


def _future_queue_slice_groups(rows: tuple[tuple[str, RoadmapItem], ...]) -> tuple[tuple[str, tuple[tuple[str, RoadmapItem], ...]], ...]:
    grouped: dict[str, list[tuple[str, RoadmapItem]]] = {}
    for item_id, item in rows:
        execution_slice = _normalized_item_id(item.fields.get("execution_slice")) or item_id
        grouped.setdefault(execution_slice, []).append((item_id, item))
    return tuple((execution_slice, tuple(slice_rows)) for execution_slice, slice_rows in grouped.items())


def _future_queue_order_range_text(rows: tuple[tuple[str, RoadmapItem], ...]) -> str:
    first_order = _future_queue_order_text(rows[0][1])
    last_order = _future_queue_order_text(rows[-1][1])
    return first_order if first_order == last_order else f"{first_order}-{last_order}"


def _future_queue_slice_detail(rows: tuple[tuple[str, RoadmapItem], ...]) -> str:
    details = _dedupe_nonempty(_future_queue_detail(item) for _item_id, item in rows)
    if not details:
        return ""
    return details[0] if len(details) == 1 else f"{len(details)} distinct slice notes"


def _future_queue_order_text(item: RoadmapItem) -> str:
    value = item.fields.get("order")
    if value in (None, ""):
        return "unspecified"
    return str(value).strip() or "unspecified"


def _future_queue_detail(item: RoadmapItem) -> str:
    detail = _field_scalar(item.fields, "slice_goal") or _field_scalar(item.fields, "carry_forward") or item.title
    return re.sub(r"\s+", " ", detail.replace("`", "'").strip()).rstrip(".")


def _order_accepted_item_blocks(text: str) -> tuple[str, tuple[str, ...]]:
    parse_result = _parse_roadmap_items(text)
    if parse_result[1]:
        return text, ()
    _items_start, _items_end, items = parse_result[0]
    item_entries = sorted(items.items(), key=lambda row: (row[1].start, row[0]))
    accepted_entries = [
        (item_id, item)
        for item_id, item in item_entries
        if _normalized_status(item.fields.get("status")) == "accepted"
    ]
    if len(accepted_entries) < 2:
        return text, ()

    ordered_entries = sorted(accepted_entries, key=lambda row: (_order_sort_key(row[1]), row[1].start, row[0]))
    original_ids = tuple(item_id for item_id, _item in accepted_entries)
    ordered_ids = tuple(item_id for item_id, _item in ordered_entries)
    if original_ids == ordered_ids:
        return text, ()

    lines = text.splitlines(keepends=True)
    rebuilt: list[str] = []
    cursor = 0
    ordered_index = 0
    for _item_id, item in item_entries:
        rebuilt.extend(lines[cursor : item.start])
        if _normalized_status(item.fields.get("status")) == "accepted":
            _ordered_item_id, ordered_item = ordered_entries[ordered_index]
            rebuilt.extend(lines[ordered_item.start : ordered_item.end])
            ordered_index += 1
        else:
            rebuilt.extend(lines[item.start : item.end])
        cursor = item.end
    rebuilt.extend(lines[cursor:])
    moved_ids = tuple(item_id for index, item_id in enumerate(ordered_ids) if original_ids[index] != item_id)
    return "".join(rebuilt), moved_ids


def _normalize_physical_item_block_order(text: str) -> tuple[str, tuple[str, ...]]:
    parse_result = _parse_roadmap_items(text)
    if parse_result[1]:
        return text, ()
    _items_start, _items_end, items = parse_result[0]
    item_entries = sorted(items.items(), key=lambda row: (row[1].start, row[0]))
    if len(item_entries) < 2:
        return text, ()

    ordered_entries = sorted(item_entries, key=_physical_order_sort_key)
    original_ids = tuple(item_id for item_id, _item in item_entries)
    ordered_ids = tuple(item_id for item_id, _item in ordered_entries)
    if original_ids == ordered_ids:
        return text, ()

    lines = text.splitlines(keepends=True)
    rebuilt: list[str] = []
    cursor = 0
    for _item_id, item in ordered_entries:
        if cursor == 0:
            rebuilt.extend(lines[: item_entries[0][1].start])
        rebuilt.extend(lines[item.start : item.end])
        cursor = item.end
    rebuilt.extend(lines[item_entries[-1][1].end :])
    moved_ids = tuple(item_id for index, item_id in enumerate(ordered_ids) if original_ids[index] != item_id)
    return "".join(rebuilt), moved_ids


def _physical_order_sort_key(row: tuple[str, RoadmapItem]) -> tuple[int, tuple[int, int | str], int, str]:
    item_id, item = row
    status = _normalized_status(item.fields.get("status"))
    bucket = ROADMAP_PHYSICAL_ORDER_BUCKETS.get(status, 8)
    sortable_by_order = status in {"active", "accepted", "proposed", "blocked", "deferred"}
    order_key = _order_sort_key(item) if sortable_by_order else (0, item.start)
    return (bucket, order_key, item.start, item_id)


def _order_sort_key(item: RoadmapItem) -> tuple[int, int | str]:
    order = item.fields.get("order")
    if isinstance(order, int):
        return (0, order)
    try:
        return (0, int(str(order).strip()))
    except ValueError:
        return (1, str(order or ""))


def _covered_item_ids(items: dict[str, RoadmapItem], normalized_item_id: str, primary: RoadmapItem) -> tuple[str, ...]:
    primary_fields = primary.fields
    execution_slice = _normalized_item_id(primary_fields.get("execution_slice"))
    explicit_members = tuple(_normalized_item_id(value) for value in _field_list(primary_fields, "slice_members"))
    if explicit_members:
        members = tuple(member for member in explicit_members if member in items)
        if not members:
            members = (normalized_item_id,)
    elif execution_slice:
        members = tuple(
            roadmap_item_id
            for roadmap_item_id, roadmap_item in sorted(items.items(), key=lambda row: (row[1].start, row[0]))
            if _normalized_item_id(roadmap_item.fields.get("execution_slice")) == execution_slice
        )
    else:
        members = (normalized_item_id,)
    return tuple(_dedupe_nonempty((normalized_item_id, *members)))


def _parse_item_fields(lines: list[str]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for line in lines:
        match = re.match(r"^-\s+`([A-Za-z0-9_-]+)`:\s*(.*?)\s*$", line.strip())
        if not match:
            continue
        key = match.group(1)
        raw = match.group(2).strip()
        if raw.startswith("`") and raw.endswith("`"):
            raw = raw[1:-1]
        if key in LIST_FIELDS:
            fields[key] = _parse_list_value(raw)
        elif key == "order":
            try:
                fields[key] = int(raw)
            except ValueError:
                fields[key] = raw
        else:
            fields[key] = raw
    for key in LIST_FIELDS:
        fields.setdefault(key, [])
    return fields


def _parse_legacy_item_fields(lines: list[str]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", line.strip())
        if not match:
            continue
        key = match.group(1)
        raw = match.group(2).strip()
        if key in LIST_FIELDS:
            fields[key] = _parse_legacy_list_field(lines, index, raw)
        elif key == "order":
            try:
                fields[key] = int(_strip_quotes(raw))
            except ValueError:
                fields[key] = _strip_quotes(raw)
        else:
            fields[key] = _strip_quotes(raw)
    for key in LIST_FIELDS:
        fields.setdefault(key, [])
    return fields


def _parse_legacy_list_field(lines: list[str], index: int, raw: str) -> list[str]:
    if raw:
        parsed = _parse_list_value(raw)
        if parsed:
            return parsed
        scalar = _strip_quotes(raw)
        return [scalar] if scalar and scalar != "[]" else []
    values: list[str] = []
    for line in lines[index + 1 :]:
        match = re.match(r"^\s*-\s+(.+?)\s*$", line)
        if not match:
            break
        values.append(_strip_quotes(match.group(1).strip()))
    return values


def _parse_list_value(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _new_item_fields(
    request: RoadmapRequest,
    *,
    source_incubation: str | None = None,
    related_incubation: str = "",
) -> dict[str, object]:
    return {
        "id": request.item_id,
        "status": request.status,
        "stage": request.stage,
        "order": request.order if request.order is not None else 0,
        "execution_slice": request.execution_slice,
        "slice_goal": request.slice_goal,
        "slice_members": list(request.slice_members),
        "slice_dependencies": list(request.slice_dependencies),
        "slice_closeout_boundary": request.slice_closeout_boundary,
        "dependencies": list(request.dependencies),
        "source_incubation": request.source_incubation if source_incubation is None else source_incubation,
        RELATED_INCUBATION_FIELD: related_incubation,
        "source_research": request.source_research,
        SOURCE_MEMBERS_FIELD: list(request.source_members),
        "related_specs": list(request.related_specs),
        "related_plan": request.related_plan,
        "archived_plan": request.archived_plan,
        "target_artifacts": list(request.target_artifacts),
        "verification_summary": request.verification_summary,
        "docs_decision": request.docs_decision,
        "carry_forward": request.carry_forward,
        "supersedes": list(request.supersedes),
        "superseded_by": list(request.superseded_by),
        **dict(request.custom_fields),
    }


def _updated_item_fields(
    current: dict[str, object],
    request: RoadmapRequest,
    *,
    source_incubation: str | None = None,
    related_incubation: str | None = None,
) -> dict[str, object]:
    fields = dict(current)
    for key in STANDARD_FIELDS:
        fields.setdefault(key, _empty_field_value(key))
    fields["id"] = request.item_id
    if request.status:
        fields["status"] = request.status
    if request.stage:
        fields["stage"] = request.stage
    if request.order is not None:
        fields["order"] = request.order
    for key, value in _scalar_request_fields(request).items():
        if key in {"status", "order"} or not value:
            continue
        fields[key] = value
    if source_incubation is not None:
        fields["source_incubation"] = source_incubation
    if related_incubation is not None:
        fields[RELATED_INCUBATION_FIELD] = related_incubation
    if request.docs_decision:
        fields["docs_decision"] = request.docs_decision
    for key, values in _list_request_fields(request).items():
        if values:
            fields[key] = list(values)
    for key in request.clear_fields:
        fields[key] = _empty_field_value(key)
    for key, value in request.custom_fields:
        fields[key] = value
    return fields


def _compacted_replay_item_fields(
    request: RoadmapRequest,
    items: dict[str, RoadmapItem],
    archived_plan: str,
    *,
    source_incubation: str | None = None,
    related_incubation: str = "",
) -> dict[str, object]:
    replay_status = request.status or "accepted"
    replay_order = request.order if request.order is not None else _next_roadmap_order(items, replay_status)
    replay_custom_fields = (
        ("lifecycle_replay", "compacted-roadmap-history"),
        ("replay_source", archived_plan),
        *request.custom_fields,
    )
    replay_request = replace(
        request,
        status=replay_status,
        order=replay_order,
        execution_slice=request.execution_slice or request.item_id,
        slice_goal=request.slice_goal or f"Replay compacted roadmap item {request.item_id} from archived history.",
        slice_members=request.slice_members or (request.item_id,),
        slice_closeout_boundary=request.slice_closeout_boundary or "explicit closeout/writeback only",
        related_plan=request.related_plan,
        archived_plan=request.archived_plan or archived_plan,
        verification_summary=request.verification_summary
        or f"Replayed from Archived Completed History evidence: {archived_plan}.",
        docs_decision=request.docs_decision or "uncertain",
        carry_forward=request.carry_forward or "Review archived plan evidence before executing the replayed slice.",
        custom_fields=replay_custom_fields,
    )
    return _new_item_fields(
        replay_request,
        source_incubation=source_incubation,
        related_incubation=related_incubation,
    )


def _compacted_replay_title(inventory: Inventory, request: RoadmapRequest, archived_plan: str) -> str:
    if request.title:
        return request.title
    path = inventory.root / archived_plan
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return _title_from_item_id(request.item_id)
    frontmatter_match = re.search(r"(?m)^title:\s*['\"]?(.+?)['\"]?\s*$", text)
    if frontmatter_match:
        title = frontmatter_match.group(1).strip().strip("'\"")
        if title:
            return title
    heading_match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    if heading_match:
        title = heading_match.group(1).strip()
        if title:
            return title
    return _title_from_item_id(request.item_id)


def _title_from_item_id(item_id: str) -> str:
    return " ".join(part.capitalize() for part in item_id.split("-") if part) or "Roadmap Item"


def _next_roadmap_order(items: dict[str, RoadmapItem], status: str) -> int:
    matching_orders: list[int] = []
    normalized_status = _normalized_status(status)
    for item in items.values():
        if _normalized_status(item.fields.get("status")) != normalized_status:
            continue
        order = item.fields.get("order")
        if isinstance(order, int):
            matching_orders.append(order)
            continue
        try:
            matching_orders.append(int(str(order or "0")))
        except ValueError:
            continue
    return (max(matching_orders) + 10) if matching_orders else 10


def _render_item_block(title: str, fields: dict[str, object]) -> str:
    lines = [f"### {title}\n", "\n"]
    for key in _rendered_item_field_keys(fields):
        value = fields.get(key, _empty_field_value(key))
        if not _should_render_item_field(key, value):
            continue
        if key in LIST_FIELDS:
            rendered = json.dumps(list(value) if isinstance(value, list) else [], ensure_ascii=True)
        elif key == "order":
            rendered = str(value if value not in (None, "") else 0)
        else:
            rendered = str(value or "")
        lines.append(f"- `{key}`: `{rendered}`\n")
    lines.append("\n")
    return "".join(lines)


def _empty_roadmap_text() -> str:
    return (
        "---\n"
        'id: "memory-routing-roadmap"\n'
        'status: "active"\n'
        "---\n"
        "# Roadmap\n\n"
        "## Item Schema\n\n"
        "- `id`: stable item identifier.\n"
        "- `status`: known roadmap status.\n\n"
        "## Items\n\n"
    )


def _should_render_item_field(field: str, value: object) -> bool:
    if (
        field in EMPTY_STRICT_ITEM_FIELDS
        or field in OPTIONAL_SCALAR_ITEM_FIELDS
        or field not in STANDARD_FIELDS
    ) and not _field_value_present(value):
        return False
    return True


def _rendered_item_field_keys(fields: dict[str, object]) -> tuple[str, ...]:
    return tuple(
        key
        for key in _item_field_keys_for_render(fields)
        if _should_render_item_field(key, fields.get(key, _empty_field_value(key)))
    )


def _item_field_keys_for_render(fields: dict[str, object]) -> tuple[str, ...]:
    return tuple(_dedupe_nonempty((*STANDARD_FIELDS, *_custom_item_field_keys(fields))))


def _item_field_keys_for_comparison(current: dict[str, object], updated: dict[str, object]) -> tuple[str, ...]:
    return tuple(_dedupe_nonempty((*STANDARD_FIELDS, *_custom_item_field_keys(current), *_custom_item_field_keys(updated))))


def _custom_item_field_keys(fields: dict[str, object]) -> tuple[str, ...]:
    return tuple(key for key in fields if key not in STANDARD_FIELDS)


def _empty_strict_fields_present(fields: dict[str, object]) -> tuple[str, ...]:
    return tuple(field for field in EMPTY_STRICT_ITEM_FIELDS if field in fields and not _field_value_present(fields.get(field)))


def _field_value_present(value: object) -> bool:
    if value in (None, "", [], ()):
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_field_value_present(item) for item in value)
    return bool(str(value).strip())


def _render_updated_legacy_item_block(block_lines: list[str], changed_fields: tuple[str, ...], fields: dict[str, object]) -> str:
    updated_lines = list(block_lines)
    newline = "\r\n" if any(line.endswith("\r\n") for line in block_lines) else "\n"
    for field in changed_fields:
        replacement = _render_legacy_field(field, fields.get(field, _empty_field_value(field)), newline)
        spans = _legacy_field_spans(updated_lines)
        span = spans.get(field)
        if span:
            start, end = span
            updated_lines[start:end] = replacement
            continue
        insert_at = _legacy_field_insert_index(updated_lines)
        updated_lines[insert_at:insert_at] = replacement
    return "".join(updated_lines)


def _legacy_field_spans(lines: list[str]) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    index = 0
    while index < len(lines):
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", lines[index].strip())
        if not match:
            index += 1
            continue
        key = match.group(1)
        end = index + 1
        while end < len(lines) and re.match(r"^\s*-\s+.+\s*$", lines[end]):
            end += 1
        spans[key] = (index, end)
        index = end
    return spans


def _legacy_field_insert_index(lines: list[str]) -> int:
    index = len(lines)
    while index > 0 and not lines[index - 1].strip():
        index -= 1
    return index


def _render_legacy_field(field: str, value: object, newline: str) -> list[str]:
    if field in LIST_FIELDS:
        values = _field_value_list(value)
        if not values:
            return [f"{field}: []{newline}"]
        return [f"{field}:{newline}", *(f'  - "{_legacy_quoted_value(item)}"{newline}' for item in values)]
    if field == "order":
        rendered = str(value if value not in (None, "") else 0)
        return [f"{field}: {rendered}{newline}"]
    return [f'{field}: "{_legacy_quoted_value(str(value or ""))}"{newline}']


def _field_value_list(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        parsed = _parse_list_value(value) if value.startswith("[") and value.endswith("]") else [value]
        return [str(item) for item in parsed if str(item).strip()]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _legacy_quoted_value(value: object) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _reused_source_incubation_reason(inventory: Inventory, source_rel: str, item_id: str) -> str:
    source_path = inventory.root / source_rel
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError:
        return ""

    related_item = _normalized_item_id(_frontmatter_scalar(text, "related_roadmap_item"))
    if related_item:
        if related_item == item_id:
            return ""
        return f"source incubation already records related_roadmap_item {related_item!r}"

    related_plan = _normalize_rel(_frontmatter_scalar(text, "related_plan"))
    if related_plan == DEFAULT_PLAN_REL and _roadmap_item_owned_by_active_plan(inventory, item_id):
        return ""
    if related_plan:
        return f"source incubation already records related_plan {related_plan!r}"

    for field in SOURCE_INCUBATION_OWNERSHIP_FIELDS:
        if field in {"related_roadmap_item", "related_plan"}:
            continue
        value = _frontmatter_scalar(text, field)
        if value:
            return f"source incubation already records {field} {value!r}"
    return ""


def _relationship_errors(
    inventory: Inventory,
    request: RoadmapRequest,
    item_ids: set[str],
    archived_history: dict[str, str],
    allowed_missing_paths: set[str],
) -> list[Finding]:
    errors: list[Finding] = []
    for field, value in _scalar_request_fields(request).items():
        if field not in PATH_FIELDS or not value:
            continue
        errors.extend(_path_relationship_errors(inventory, field, value, allowed_missing_paths))
    for field, values in _path_list_request_fields(request).items():
        for value in values:
            errors.extend(_path_relationship_errors(inventory, field, value, allowed_missing_paths))
    for field, values in _item_id_list_request_fields(request).items():
        allowed_item_ids = set(item_ids)
        if field == "slice_members":
            allowed_item_ids.add(request.item_id)
        for value in values:
            if value not in allowed_item_ids:
                if field in ARCHIVED_PREREQUISITE_REFERENCE_FIELDS:
                    archived_plan = archived_history.get(value)
                    if archived_plan:
                        problem = _archived_plan_evidence_problem(inventory, archived_plan)
                        if problem:
                            errors.append(
                                Finding(
                                    "error",
                                    "roadmap-refused",
                                    (
                                        f"--{field.replace('_', '-')} archived dependency evidence for {value!r} "
                                        f"is {problem}: {archived_plan}"
                                    ),
                                    ROADMAP_REL,
                                )
                            )
                        continue
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} target item id is missing: {value}", ROADMAP_REL))
    return errors


def _archived_prerequisite_reference_findings(
    inventory: Inventory,
    plan: RoadmapPlan,
    prefix: str,
) -> list[Finding]:
    parse_result = _parse_roadmap_items_for_sync(plan.updated_text)
    if parse_result[1]:
        return []
    _items_start, _items_end, items = parse_result[0]
    item = items.get(plan.item_id)
    if item is None:
        return []

    archived_history = _archived_history_item_plan_map(plan.updated_text)
    refs: list[str] = []
    for field in ARCHIVED_PREREQUISITE_REFERENCE_FIELDS:
        for value in _field_list(item.fields, field):
            dependency = _normalized_item_id(value)
            if not dependency or dependency in items:
                continue
            archived_plan = archived_history.get(dependency)
            if not archived_plan:
                continue
            problem = _archived_plan_evidence_problem(inventory, archived_plan)
            suffix = f" ({problem})" if problem else ""
            refs.append(f"{field} {dependency} -> {archived_plan}{suffix}")
    refs = _dedupe_nonempty(refs)
    if not refs:
        return []
    return [
        Finding(
            "info",
            "roadmap-archived-prerequisite-reference",
            (
                f"{prefix}keep archived prerequisite reference(s) via Archived Completed History: "
                f"{'; '.join(refs)}; this does not recreate archives, reopen roadmap items, "
                "or approve lifecycle movement"
            ),
            plan.target_rel,
        )
    ]


def _path_relationship_errors(
    inventory: Inventory,
    field: str,
    rel_path: str,
    allowed_missing_paths: set[str],
) -> list[Finding]:
    errors: list[Finding] = []
    if _rel_has_absolute_or_parent_parts(rel_path):
        return [Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} must be a root-relative path without parent segments", ROADMAP_REL)]
    if not rel_path.endswith(".md"):
        errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} must point to a Markdown route", rel_path))
    if not _route_destination_allowed(field, rel_path):
        errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} points at an incompatible route: {rel_path}", rel_path))
    path = inventory.root / rel_path
    if _path_escapes_root(inventory.root, path):
        errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} path escapes the target root", rel_path))
        return errors
    for parent in _parents_between(inventory.root, path.parent):
        parent_rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} path contains a symlink segment: {parent_rel}", parent_rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} path contains a non-directory segment: {parent_rel}", parent_rel))
    if not path.exists():
        if _normalize_rel(rel_path) not in allowed_missing_paths:
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} target is missing: {rel_path}", rel_path))
    elif path.is_symlink():
        errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} target is a symlink", rel_path))
    elif not path.is_file():
        errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} target is not a regular file", rel_path))
    return errors


def _route_destination_allowed(field: str, rel_path: str) -> bool:
    if field == "source_incubation":
        return rel_path.startswith("project/plan-incubation/") or rel_path.startswith("project/archive/reference/incubation/")
    if field == RELATED_INCUBATION_FIELD:
        return rel_path.startswith("project/plan-incubation/") or rel_path.startswith("project/archive/reference/incubation/")
    if field == "source_research":
        return rel_path.startswith("project/research/") or rel_path.startswith("project/archive/reference/research/")
    if field == SOURCE_MEMBERS_FIELD:
        return rel_path.startswith(
            (
                "project/plan-incubation/",
                "project/archive/reference/incubation/",
                "project/research/",
                "project/archive/reference/research/",
                "project/verification/",
            )
        )
    if field == "related_specs":
        return rel_path.startswith("project/specs/") or rel_path.startswith("docs/specs/")
    if field in {"related_plan", "archived_plan"}:
        return rel_path == "project/implementation-plan.md" or rel_path.startswith("project/archive/plans/")
    return True


def _batch_plan_findings(inventory: Inventory, batch_plan: RoadmapBatchPlan, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings: list[Finding] = [
        Finding(
            "info",
            "roadmap-batch-plan",
            f"{prefix}process {len(batch_plan.requests)} roadmap item(s) through one add-many batch",
            batch_plan.target_rel,
        )
    ]
    for position, plan in enumerate(batch_plan.plans, start=1):
        findings.append(
            Finding(
                "info",
                "roadmap-batch-item",
                f"{prefix}create item {position}: {plan.item_id}",
                batch_plan.target_rel,
            )
        )
        findings.extend(_plan_findings(inventory, plan, apply))
    return findings


def _plan_findings(inventory: Inventory, plan: RoadmapPlan, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    plan_message = (
        f"{prefix}normalize roadmap item block order"
        if plan.action == "normalize"
        else f"{prefix}{plan.action} roadmap item: {plan.item_id}"
    )
    findings = [
        Finding("info", "roadmap-plan", plan_message, plan.target_rel),
        Finding("info", "roadmap-target-file", f"{prefix}write boundary: {plan.target_rel}", plan.target_rel),
    ]
    if not plan.target_existed:
        findings.append(
            Finding(
                "info",
                "roadmap-bootstrap",
                f"{prefix}bootstrap missing optional roadmap route before applying the item mutation",
                plan.target_rel,
            )
        )
    if plan.changed_fields:
        findings.extend(
            Finding("info", "roadmap-changed-field", f"{prefix}change field: {field}", plan.target_rel)
            for field in plan.changed_fields
        )
    else:
        message = "no roadmap fields would change" if not apply else "no roadmap fields changed"
        findings.append(Finding("info", "roadmap-noop", message, plan.target_rel))
    if plan.compacted_item_ids:
        findings.append(
            Finding(
                "info",
                "roadmap-live-tail-compaction",
                f"{prefix}compact done roadmap item block(s): {', '.join(plan.compacted_item_ids)}",
                plan.target_rel,
            )
        )
    if plan.replayed_item_ids:
        findings.append(
            Finding(
                "info",
                "roadmap-compacted-item-replay",
                f"{prefix}restore compacted roadmap item block(s) from Archived Completed History: {', '.join(plan.replayed_item_ids)}",
                plan.target_rel,
            )
        )
    if plan.retargeted_terminal_item_ids:
        findings.append(
            Finding(
                "info",
                "roadmap-terminal-related-plan-retarget",
                f"{prefix}retarget terminal roadmap related_plan link(s): {', '.join(plan.retargeted_terminal_item_ids)}",
                plan.target_rel,
            )
        )
    findings.extend(_archived_prerequisite_reference_findings(inventory, plan, prefix))
    target_artifacts = _roadmap_item_target_artifacts(plan.updated_text, plan.item_id)
    findings.extend(_target_artifact_ownership_findings(inventory, target_artifacts, prefix, "roadmap-target-artifact-ownership", plan.target_rel))
    if plan.reordered_item_ids:
        if plan.action == "normalize":
            findings.append(
                Finding(
                    "info",
                    "roadmap-physical-order-normalization",
                    f"{prefix}normalize roadmap item block order: {', '.join(plan.reordered_item_ids)}",
                    plan.target_rel,
                )
            )
        else:
            findings.append(
                Finding(
                    "info",
                    "roadmap-order-aware-insertion",
                    f"{prefix}order accepted roadmap item block(s): {', '.join(plan.reordered_item_ids)}",
                    plan.target_rel,
                )
            )
    findings.extend(_roadmap_order_namespace_findings_from_text(plan.updated_text))
    if plan.related_incubation_source:
        findings.append(
            Finding(
                "info",
                "roadmap-related-incubation-source",
                (
                    f"{prefix}record reused source incubation as non-owning "
                    f"{RELATED_INCUBATION_FIELD}: {plan.related_incubation_source}; "
                    f"{plan.related_incubation_reason}; relationship metadata is left unchanged"
                ),
                plan.related_incubation_source,
            )
        )
    if plan.relationship_plan:
        findings.extend(_relationship_plan_findings(plan.relationship_plan, apply))
    return findings


def _roadmap_item_target_artifacts(text: str, item_id: str) -> tuple[str, ...]:
    if item_id == "<all>":
        return ()
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return ()
    _items_start, _items_end, items = parse_result[0]
    item = items.get(_normalized_item_id(item_id))
    if item is None:
        return ()
    return tuple(_field_list(item.fields, "target_artifacts"))


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
    return [Finding("info", code, f"{prefix}classify target artifact ownership: {summary}; guidance: {guidance}", source)]


def _route_write_evidence(plan: RoadmapPlan) -> tuple[RouteWriteEvidence, ...]:
    before_text = plan.current_text if plan.target_existed else None
    writes = [RouteWriteEvidence(plan.target_rel, before_text, plan.updated_text)]
    if plan.relationship_plan:
        writes.append(RouteWriteEvidence(plan.relationship_plan.target_rel, plan.relationship_plan.current_text, plan.relationship_plan.updated_text))
    return tuple(writes)


def _route_write_findings(inventory: Inventory, plan: RoadmapPlan, apply: bool) -> list[Finding]:
    writes = _route_write_evidence(plan)
    return [
        *route_write_findings("roadmap-route-write", writes, apply=apply),
        *route_reference_transaction_guard_findings(inventory, writes, apply=apply),
    ]


def _batch_route_write_evidence(batch_plan: RoadmapBatchPlan) -> tuple[RouteWriteEvidence, ...]:
    before_text = batch_plan.current_text if batch_plan.target_existed else None
    writes = [RouteWriteEvidence(batch_plan.target_rel, before_text, batch_plan.updated_text)]
    for relationship_plan in _batch_relationship_plans(batch_plan):
        writes.append(RouteWriteEvidence(relationship_plan.target_rel, relationship_plan.current_text, relationship_plan.updated_text))
    return tuple(writes)


def _batch_route_write_findings(inventory: Inventory, batch_plan: RoadmapBatchPlan, apply: bool) -> list[Finding]:
    writes = _batch_route_write_evidence(batch_plan)
    return [
        *route_write_findings("roadmap-route-write", writes, apply=apply),
        *route_reference_transaction_guard_findings(inventory, writes, apply=apply),
    ]


def _relationship_plan_findings(plan: RelationshipUpdatePlan, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding("info", "roadmap-relationship-sync", f"{prefix}sync source incubation relationship metadata", plan.source_rel),
        Finding("info", "roadmap-relationship-target", f"{prefix}write relationship target: {plan.target_rel}", plan.target_rel),
    ]
    if plan.changed_fields:
        findings.extend(
            Finding("info", "roadmap-relationship-changed-field", f"{prefix}change source incubation field: {field}", plan.source_rel)
            for field in plan.changed_fields
        )
    else:
        findings.append(Finding("info", "roadmap-relationship-noop", "source incubation relationship metadata already matches requested roadmap item", plan.source_rel))
    return findings


def _roadmap_order_namespace_findings_from_text(text: str) -> list[Finding]:
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return []
    _items_start, _items_end, items = parse_result[0]
    findings: list[Finding] = []
    for status in ORDER_NAMESPACE_STATUSES:
        rows = tuple(
            sorted(
                (
                    (item_id, item)
                    for item_id, item in items.items()
                    if _normalized_status(item.fields.get("status")) == status
                ),
                key=lambda row: (_order_sort_key(row[1]), row[1].start, row[0]),
            )
        )
        if not rows:
            continue
        findings.append(
            Finding(
                "info",
                "roadmap-order-namespace",
                (
                    f"status-scoped order namespace {status!r} {_order_namespace_span_text(rows)}; "
                    "duplicate order values are checked only inside this status namespace"
                ),
                ROADMAP_REL,
                rows[0][1].start + 1,
            )
        )
        for order, duplicates in _duplicate_order_groups(rows):
            findings.append(
                Finding(
                    "warn",
                    "roadmap-order-namespace-duplicate",
                    (
                        f"status-scoped order namespace {status!r} reuses order {order!r} "
                        f"for roadmap items: {', '.join(item_id for item_id, _item in duplicates)}"
                    ),
                    ROADMAP_REL,
                    duplicates[1][1].start + 1,
                )
            )
    return findings


def _roadmap_acceptance_readiness_findings_from_text(
    inventory: Inventory,
    text: str,
    *,
    item_ids: tuple[str, ...] = (),
) -> list[Finding]:
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return []
    _items_start, _items_end, items = parse_result[0]
    requested_ids = {_normalized_item_id(item_id) for item_id in item_ids if _normalized_item_id(item_id)}
    archived_history = _archived_history_item_plan_map(text)
    active_ids = set(active_plan_roadmap_item_ids(inventory))
    findings: list[Finding] = []
    for item_id, item in sorted(items.items(), key=lambda row: (_order_sort_key(row[1]), row[1].start, row[0])):
        status = _normalized_status(item.fields.get("status"))
        if requested_ids:
            if item_id not in requested_ids:
                continue
        elif status not in {"accepted", "active", "proposed", "blocked"}:
            continue
        blockers = _roadmap_readiness_blockers(inventory, item_id, item, items, archived_history, active_ids)
        readiness, next_safe_command = _roadmap_readiness_state(status, item_id, blockers, active_ids)
        execution_slice = _normalized_item_id(item.fields.get("execution_slice")) or item_id
        blocker_text = "; ".join(blockers) if blockers else "none"
        findings.append(
            Finding(
                "info",
                "roadmap-acceptance-readiness",
                (
                    f"item={item_id!r}; slice={execution_slice!r}; status={status or 'unspecified'!r}; "
                    f"readiness={readiness!r}; blockers={blocker_text}; next_safe_command={next_safe_command}"
                ),
                ROADMAP_REL,
                item.start + 1,
            )
        )
    if findings:
        findings.append(
            Finding(
                "info",
                "roadmap-acceptance-readiness-boundary",
                "roadmap acceptance readiness is a read-only matrix of blockers, stale evidence, and next safe commands; it cannot promote roadmap items, open plans, approve lifecycle movement, archive, stage, commit, or repair",
                ROADMAP_REL,
            )
        )
    return findings


def _roadmap_readiness_blockers(
    inventory: Inventory,
    item_id: str,
    item: RoadmapItem,
    items: dict[str, RoadmapItem],
    archived_history: dict[str, str],
    active_ids: set[str],
) -> tuple[str, ...]:
    fields = item.fields
    status = _normalized_status(fields.get("status"))
    blockers: list[str] = []
    if status == "proposed":
        blockers.append("status is proposed; accept explicitly before plan opening")
    elif status == "blocked":
        blockers.append("status is blocked; resolve carry_forward or blocker evidence before plan opening")
    elif status and status not in {"accepted", "active"}:
        blockers.append(f"status is {status}; not queued for acceptance")

    if status == "active" and active_ids and item_id not in active_ids:
        blockers.append("roadmap item is active but the current active plan does not cover it")
    if status == "accepted" and active_ids and item_id not in active_ids:
        blockers.append(
            "current active plan is open for other roadmap item(s); finish or archive that plan before opening the next roadmap item"
        )
    blockers.extend(roadmap_plan_scope_blockers(inventory, item_id, fields))
    blockers.extend(_roadmap_slice_result_gate_blockers(inventory, item_id, item, items))

    source_fields = ("source_incubation", RELATED_INCUBATION_FIELD, "source_research")
    source_member_rels = tuple(_normalize_rel(value) for value in _field_list(fields, SOURCE_MEMBERS_FIELD))
    if status in {"accepted", "active"} and not any(_field_scalar(fields, field) for field in source_fields) and not source_member_rels:
        blockers.append("missing source_incubation, related_incubation, source_research, or source_members evidence")
    for field in source_fields:
        source_rel = _normalize_rel(_field_scalar(fields, field))
        if not source_rel:
            continue
        problem = _roadmap_readiness_path_problem(inventory, source_rel)
        if problem:
            blockers.append(f"{field} evidence is {problem}: {source_rel}")
            continue
        quality_problem = _roadmap_readiness_research_quality_problem(inventory, source_rel)
        if quality_problem:
            blockers.append(f"{field} research quality gate blocks planning: {quality_problem}: {source_rel}")
    for source_rel in source_member_rels:
        if not source_rel:
            continue
        problem = _roadmap_readiness_path_problem(inventory, source_rel)
        if problem:
            blockers.append(f"{SOURCE_MEMBERS_FIELD} evidence is {problem}: {source_rel}")
            continue
        quality_problem = _roadmap_readiness_research_quality_problem(inventory, source_rel)
        if quality_problem:
            blockers.append(f"{SOURCE_MEMBERS_FIELD} research quality gate blocks planning: {quality_problem}: {source_rel}")

    markers = tuple(field for field in HUMAN_REVIEW_GATE_FIELDS if _human_review_gate_enabled(fields.get(field)))
    if markers:
        blockers.append(f"human review marker(s): {', '.join(markers)}")
    high_blast_marker = _roadmap_high_blast_gate_marker(fields)
    if high_blast_marker:
        blockers.append(f"high-blast human gate marker: {high_blast_marker}")

    dependencies = tuple(
        _dedupe_nonempty(
            (
                *(_normalized_item_id(value) for value in _field_list(fields, "dependencies")),
                *(_normalized_item_id(value) for value in _field_list(fields, "slice_dependencies")),
            )
        )
    )
    for dependency in dependencies:
        if not dependency or dependency in items:
            continue
        archived_plan = archived_history.get(dependency)
        if not archived_plan:
            blockers.append(f"missing live or archived dependency evidence: {dependency}")
            continue
        problem = _archived_plan_evidence_problem(inventory, archived_plan)
        if problem:
            blockers.append(f"dependency evidence for {dependency} is {problem}: {archived_plan}")

    related_plan = _normalize_rel(_field_scalar(fields, "related_plan"))
    if status in {"accepted", "active"} and related_plan == DEFAULT_PLAN_REL and item_id not in active_ids:
        blockers.append(f"related_plan points at {DEFAULT_PLAN_REL} but the active plan does not cover this item")

    return tuple(_dedupe_nonempty(blockers))


def _roadmap_slice_result_gate_blockers(
    inventory: Inventory,
    item_id: str,
    item: RoadmapItem,
    items: dict[str, RoadmapItem],
) -> tuple[str, ...]:
    fields = item.fields
    dependencies = tuple(
        _dedupe_nonempty(
            (
                *(_normalized_item_id(value) for value in _field_list(fields, "dependencies")),
                *(_normalized_item_id(value) for value in _field_list(fields, "slice_dependencies")),
            )
        )
    )
    if not dependencies:
        return ()
    covered = set(_covered_item_ids(items, item_id, item))
    blockers: list[str] = []
    for dependency in dependencies:
        dependency_item = items.get(dependency)
        if dependency_item is None or dependency in covered:
            continue
        dependency_fields = dependency_item.fields
        if not _slice_result_gate_enabled(dependency_fields):
            continue
        dependency_status = _normalized_status(dependency_fields.get("status"))
        if dependency_status != "done":
            blockers.append(
                f"slice result gate dependency {dependency!r} has status {dependency_status or '<missing>'!r}; "
                f"finish that upstream slice and record a decision packet with {SLICE_RESULT_SAFE_FIELD}: true "
                "or explicit fork fields before opening this downstream plan"
            )
            continue
        blockers.extend(
            _slice_result_decision_packet_blockers(
                inventory,
                downstream_item_id=item_id,
                dependency_item_id=dependency,
                dependency_fields=dependency_fields,
            )
        )
    return tuple(_dedupe_nonempty(blockers))


def _slice_result_decision_packet_blockers(
    inventory: Inventory,
    *,
    downstream_item_id: str,
    dependency_item_id: str,
    dependency_fields: dict[str, object],
) -> tuple[str, ...]:
    artifact_rels = _slice_result_artifact_rels(dependency_fields)
    if not artifact_rels:
        return (
            f"slice result gate dependency {dependency_item_id!r} has no decision packet artifact; "
            "record slice_result_artifact or a project/verification target_artifact before opening "
            f"downstream item {downstream_item_id!r}",
        )

    missing_or_incomplete: list[str] = []
    for artifact_rel in artifact_rels:
        problem = _roadmap_readiness_path_problem(inventory, artifact_rel)
        if problem:
            missing_or_incomplete.append(f"{artifact_rel} is {problem}")
            continue
        try:
            artifact_text = (inventory.root / artifact_rel).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            missing_or_incomplete.append(f"{artifact_rel} is unreadable: {exc}")
            continue
        decision, detail = _slice_result_packet_decision(artifact_text)
        if decision == "safe":
            return ()
        if decision == "fork":
            return (
                f"slice result gate dependency {dependency_item_id!r} decision packet {artifact_rel} records {detail}; "
                "update/add the required roadmap slice(s) or mark the downstream item blocked before opening "
                f"{downstream_item_id!r}",
            )
        missing_or_incomplete.append(f"{artifact_rel} lacks {SLICE_RESULT_SAFE_FIELD}: true or explicit fork fields")

    detail = "; ".join(missing_or_incomplete) if missing_or_incomplete else "no usable decision packet was found"
    return (
        f"slice result gate dependency {dependency_item_id!r} blocks downstream item {downstream_item_id!r}: {detail}",
    )


def _slice_result_gate_enabled(fields: dict[str, object]) -> bool:
    for field in SLICE_RESULT_GATE_FIELDS:
        value = fields.get(field)
        if value in (None, [], ()):
            continue
        normalized = str(value or "").strip().casefold().replace("_", "-")
        if normalized in HUMAN_REVIEW_GATE_FALSEY:
            continue
        if normalized in SLICE_RESULT_GATE_TRUTHY:
            return True
    return False


def _slice_result_artifact_rels(fields: dict[str, object]) -> tuple[str, ...]:
    explicit = tuple(
        _normalize_rel(value)
        for field in SLICE_RESULT_ARTIFACT_FIELDS
        for value in _field_list(fields, field)
    )
    if explicit:
        return tuple(_dedupe_nonempty(explicit))
    targets = tuple(_normalize_rel(value) for value in _field_list(fields, "target_artifacts"))
    decision_targets = tuple(
        target
        for target in targets
        if target.startswith("project/verification/") or target.startswith("project/research/")
    )
    return tuple(_dedupe_nonempty(decision_targets or targets))


def _slice_result_packet_decision(text: str) -> tuple[str, str]:
    safe_value = _slice_result_packet_field_value(text, SLICE_RESULT_SAFE_FIELD)
    if _decision_value_is_true(safe_value):
        return "safe", f"{SLICE_RESULT_SAFE_FIELD}: true"
    if safe_value and not _decision_value_is_falsey(safe_value):
        return "fork", f"{SLICE_RESULT_SAFE_FIELD}: {safe_value}"
    for field in SLICE_RESULT_FORK_FIELDS:
        value = _slice_result_packet_field_value(text, field)
        if value and not _decision_value_is_falsey(value):
            return "fork", f"{field}: {value}"
    return "missing", ""


def _slice_result_packet_field_value(text: str, field: str) -> str:
    match = re.search(rf"(?im)^\s*(?:[-*]\s*)?`?{re.escape(field)}`?\s*[:=]\s*(.*?)\s*$", text)
    if not match:
        return ""
    return match.group(1).strip().strip("`\"'")


def _decision_value_is_true(value: str) -> bool:
    return value.strip().casefold().replace("_", "-") in {"1", "true", "yes", "safe", "continue", "safe-to-continue"}


def _decision_value_is_falsey(value: str) -> bool:
    normalized = value.strip().casefold().replace("_", "-")
    return normalized in {"", "0", "false", "no", "none", "not-needed", "not needed", "[]"}


def _roadmap_readiness_path_problem(inventory: Inventory, rel_path: str) -> str:
    if _rel_has_absolute_or_parent_parts(rel_path):
        return "not a safe root-relative path"
    path = inventory.root / rel_path
    if _path_escapes_root(inventory.root, path):
        return "outside the target root"
    if not path.exists():
        return "missing"
    if path.is_symlink():
        return "a symlink"
    if not path.is_file():
        return "not a regular file"
    return ""


def _roadmap_readiness_research_quality_problem(inventory: Inventory, rel_path: str) -> str:
    normalized = _normalize_rel(rel_path)
    if not normalized.startswith("project/research/") or not normalized.endswith(".md"):
        return ""
    path = inventory.root / normalized
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return f"unreadable research artifact: {exc}"
    return research_distill_quality_problem(normalized, text)


def _roadmap_readiness_state(
    status: str,
    item_id: str,
    blockers: tuple[str, ...],
    active_ids: set[str],
) -> tuple[str, str]:
    if status == "active":
        if item_id in active_ids:
            return "active-plan-open", "mylittleharness --root <root> check"
        return "active-roadmap-drift", "mylittleharness --root <root> check"
    if status == "accepted":
        if blockers:
            if any("current active plan is open" in blocker for blocker in blockers):
                return "blocked-active-plan-open", ACTIVE_PLAN_OPEN_NEXT_SAFE_COMMAND
            if any("slice result gate" in blocker for blocker in blockers):
                return "blocked-before-plan", roadmap_slice_result_gate_next_safe_command(item_id)
            if any("target_artifacts" in blocker for blocker in blockers):
                return "blocked-before-plan", roadmap_plan_scope_next_safe_command(item_id)
            return "blocked-before-plan", "mylittleharness --root <root> check"
        return "ready-to-plan", f"mylittleharness --root <root> plan --dry-run --roadmap-item {safe_item_id(item_id, placeholder='<item-id>')}"
    if status == "proposed":
        return "proposal-only", f"mylittleharness --root <root> roadmap --dry-run --action update --item-id {safe_item_id(item_id, placeholder='<item-id>')} --status accepted"
    if status == "blocked":
        return "blocked", f"mylittleharness --root <root> roadmap --dry-run --action update --item-id {safe_item_id(item_id, placeholder='<item-id>')}"
    return "not-queued", "mylittleharness --root <root> check"


def _order_namespace_span_text(rows: tuple[tuple[str, RoadmapItem], ...]) -> str:
    first_id, first_item = rows[0]
    if len(rows) == 1:
        return f"contains `{first_id}` at order `{_future_queue_order_text(first_item)}`"
    last_id, last_item = rows[-1]
    return (
        f"starts at `{first_id}` at order `{_future_queue_order_text(first_item)}` "
        f"and runs through `{last_id}` at order `{_future_queue_order_text(last_item)}`"
    )


def _duplicate_order_groups(rows: tuple[tuple[str, RoadmapItem], ...]) -> tuple[tuple[str, tuple[tuple[str, RoadmapItem], ...]], ...]:
    buckets: dict[str, list[tuple[str, RoadmapItem]]] = {}
    for item_id, item in rows:
        order = _explicit_order_text(item)
        if not order:
            continue
        buckets.setdefault(order, []).append((item_id, item))
    return tuple(
        (order, tuple(duplicates))
        for order, duplicates in sorted(buckets.items(), key=lambda row: _order_text_sort_key(row[0]))
        if len(duplicates) > 1
    )


def _explicit_order_text(item: RoadmapItem) -> str:
    value = item.fields.get("order")
    if value in (None, ""):
        return ""
    return str(value).strip()


def _order_text_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _relationship_plan_without_queued_active_plan_leak(
    inventory: Inventory,
    request: RoadmapRequest,
    plan: RelationshipUpdatePlan | None,
) -> RelationshipUpdatePlan | None:
    if plan is None:
        return None
    if request.related_plan == DEFAULT_PLAN_REL or _roadmap_item_owned_by_active_plan(inventory, request.item_id):
        return plan
    if not _source_text_is_fix_candidate(plan.current_text):
        return plan
    if _frontmatter_scalar(plan.current_text, "related_plan") != DEFAULT_PLAN_REL:
        return plan

    updated_text, changed = _text_with_empty_frontmatter_scalar(plan.updated_text, "related_plan")
    if not changed:
        return plan
    changed_fields = tuple(_dedupe_nonempty((*plan.changed_fields, "related_plan")))
    return replace(plan, updated_text=updated_text, changed_fields=changed_fields)


def _terminal_stale_active_plan_item(item_id: str, item: RoadmapItem, active_item_ids: set[str]) -> bool:
    status = _normalized_status(item.fields.get("status"))
    if status not in TERMINAL_RELATED_PLAN_STATUSES:
        return False
    if _normalized_item_id(item_id) in active_item_ids:
        return False
    return _normalize_rel(_field_scalar(item.fields, "related_plan")) == DEFAULT_PLAN_REL


def _terminal_related_plan_retarget_value(fields: dict[str, object]) -> str:
    archived_plan = _normalize_rel(_field_scalar(fields, "archived_plan"))
    if archived_plan.startswith("project/archive/plans/") and archived_plan != DEFAULT_PLAN_REL:
        return archived_plan
    return ""


def _roadmap_item_owned_by_active_plan(inventory: Inventory, item_id: str) -> bool:
    return _normalized_item_id(item_id) in set(active_plan_roadmap_item_ids(inventory))


def _source_text_is_fix_candidate(text: str) -> bool:
    return "[MLH-Fix-Candidate]" in text


def _frontmatter_scalar(text: str, key: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            return ""
        match = re.match(rf"^{re.escape(key)}:\s*(.*?)\s*$", line)
        if match:
            return _strip_quotes(match.group(1).strip())
    return ""


def _text_with_empty_frontmatter_scalar(text: str, key: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text, False
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return text, False
        match = re.match(rf"^({re.escape(key)}):(.*?)(\r?\n)?$", line)
        if not match:
            continue
        newline = match.group(3) or ("\n" if line.endswith("\n") else "")
        lines[index] = f'{key}: ""{newline}'
        return "".join(lines), True
    return text, False


def _relationship_tmp_path(plan: RelationshipUpdatePlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.roadmap-relationship.tmp")


def _relationship_backup_path(plan: RelationshipUpdatePlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.roadmap-relationship.backup")


def _batch_relationship_plans(batch_plan: RoadmapBatchPlan) -> tuple[RelationshipUpdatePlan, ...]:
    plans: list[RelationshipUpdatePlan] = []
    for plan in batch_plan.plans:
        if plan.relationship_plan is None:
            continue
        plans.append(plan.relationship_plan)
    return tuple(plans)


def _batch_relationship_target_errors(plans: tuple[RoadmapPlan, ...]) -> list[Finding]:
    seen: set[str] = set()
    errors: list[Finding] = []
    for plan in plans:
        relationship_plan = plan.relationship_plan
        if relationship_plan is None:
            continue
        if relationship_plan.target_rel in seen:
            errors.append(
                Finding(
                    "error",
                    "roadmap-refused",
                    f"batch would write relationship target more than once: {relationship_plan.target_rel}",
                    relationship_plan.target_rel,
                )
            )
        seen.add(relationship_plan.target_rel)
    return errors


def _batch_plan_has_changes(batch_plan: RoadmapBatchPlan) -> bool:
    if not batch_plan.target_existed or batch_plan.current_text != batch_plan.updated_text:
        return True
    return any(plan.current_text != plan.updated_text for plan in _batch_relationship_plans(batch_plan))


def _batch_plan_atomic_operations(
    inventory: Inventory,
    batch_plan: RoadmapBatchPlan,
) -> tuple[list[AtomicFileWrite], list[Finding]]:
    operations: list[AtomicFileWrite] = []
    roadmap_write_needed = (not batch_plan.target_existed) or batch_plan.current_text != batch_plan.updated_text
    tmp_path = batch_plan.target_path.with_name(f".{batch_plan.target_path.name}.roadmap-batch.tmp") if roadmap_write_needed else None
    backup_path = batch_plan.target_path.with_name(f".{batch_plan.target_path.name}.roadmap-batch.backup") if tmp_path else None
    if tmp_path and backup_path:
        operations.append(AtomicFileWrite(batch_plan.target_path, tmp_path, batch_plan.updated_text, backup_path))

    for relationship_plan in _batch_relationship_plans(batch_plan):
        relationship_tmp = _relationship_tmp_path(relationship_plan)
        relationship_backup = _relationship_backup_path(relationship_plan) if relationship_tmp else None
        if relationship_tmp and relationship_backup:
            operations.append(AtomicFileWrite(relationship_plan.target_path, relationship_tmp, relationship_plan.updated_text, relationship_backup))

    for operation, label in (
        (operation, _batch_operation_label(operation.target_path, batch_plan.target_path))
        for operation in operations
    ):
        if operation.tmp_path.exists():
            return [], [
                Finding(
                    "error",
                    "roadmap-refused",
                    f"temporary {label} write path already exists: {operation.tmp_path.relative_to(inventory.root).as_posix()}",
                    batch_plan.target_rel,
                )
            ]
        if operation.backup_path.exists():
            return [], [
                Finding(
                    "error",
                    "roadmap-refused",
                    f"temporary {label} backup path already exists: {operation.backup_path.relative_to(inventory.root).as_posix()}",
                    batch_plan.target_rel,
                )
            ]
    return operations, []


def _batch_operation_label(target_path: Path, roadmap_path: Path) -> str:
    return "roadmap batch" if target_path == roadmap_path else "relationship"


def _plan_has_changes(plan: RoadmapPlan) -> bool:
    return not plan.target_existed or plan.current_text != plan.updated_text or (
        plan.relationship_plan is not None and plan.relationship_plan.current_text != plan.relationship_plan.updated_text
    )


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "roadmap-boundary",
            "roadmap writes only project/roadmap.md and explicitly owned roadmap relationship metadata in eligible live operating roots; it does not repair, archive, stage, commit, or mutate product-source fixtures",
        ),
        Finding(
            "info",
            "roadmap-authority",
            "roadmap output is sequencing evidence only; it cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions, or future mutations",
        ),
    ]


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "roadmap-root-posture", f"root kind: {inventory.root_kind}")


def _scalar_request_fields(request: RoadmapRequest) -> dict[str, str]:
    return {
        "status": request.status,
        "stage": request.stage,
        "execution_slice": request.execution_slice,
        "slice_goal": request.slice_goal,
        "slice_closeout_boundary": request.slice_closeout_boundary,
        "source_incubation": request.source_incubation,
        "source_research": request.source_research,
        "related_plan": request.related_plan,
        "archived_plan": request.archived_plan,
        "verification_summary": request.verification_summary,
        "docs_decision": request.docs_decision,
        "carry_forward": request.carry_forward,
    }


def _parse_custom_field_args(values: list[str] | None) -> tuple[tuple[str, str], ...]:
    fields: list[tuple[str, str]] = []
    for raw_value in values or ():
        raw = str(raw_value or "")
        if "=" not in raw:
            fields.append(("", raw.strip()))
            continue
        key, value = raw.split("=", 1)
        fields.append((_normalized_custom_field_key(key), _normalized_scalar(value)))
    return tuple(fields)


def _custom_field_errors(fields: tuple[tuple[str, str], ...]) -> list[Finding]:
    errors: list[Finding] = []
    seen: set[str] = set()
    for key, value in fields:
        if not key:
            errors.append(Finding("error", "roadmap-refused", "--field must use key=value with a non-empty field name", ROADMAP_REL))
            continue
        if key in seen:
            errors.append(Finding("error", "roadmap-refused", f"--field repeats custom field: {key}", ROADMAP_REL))
        seen.add(key)
        if key in STANDARD_FIELDS:
            errors.append(Finding("error", "roadmap-refused", f"--field cannot target first-class roadmap field {key!r}; use the dedicated flag", ROADMAP_REL))
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", key):
            errors.append(Finding("error", "roadmap-refused", "--field names must be lowercase ASCII names using letters, numbers, hyphens, or underscores", ROADMAP_REL))
        if "\n" in value or "\r" in value or "`" in value:
            errors.append(Finding("error", "roadmap-refused", f"--field {key!r} value must be a single line without backticks", ROADMAP_REL))
    return errors


def _clear_field_errors(request: RoadmapRequest) -> list[Finding]:
    errors: list[Finding] = []
    seen: set[str] = set()
    for field in request.clear_fields:
        if field in seen:
            errors.append(Finding("error", "roadmap-refused", f"--clear-field repeats field: {field}", ROADMAP_REL))
            continue
        seen.add(field)
        if field not in CLEARABLE_FIELDS:
            errors.append(
                Finding(
                    "error",
                    "roadmap-refused",
                    f"--clear-field must name one of: {', '.join(CLEARABLE_FIELDS)}",
                    ROADMAP_REL,
                )
            )
            continue
        if request.action == "add":
            errors.append(Finding("error", "roadmap-refused", "--clear-field is only valid with --action update", ROADMAP_REL))
        if _request_field_present(request, field):
            errors.append(
                Finding(
                    "error",
                    "roadmap-refused",
                    f"--clear-field {field} cannot be combined with a new value for the same field",
                    ROADMAP_REL,
                )
            )
    return errors


def _request_field_present(request: RoadmapRequest, field: str) -> bool:
    if field == "order":
        return request.order is not None
    scalar_fields = _scalar_request_fields(request)
    if field in scalar_fields:
        return bool(scalar_fields[field])
    list_fields = _list_request_fields(request)
    if field in list_fields:
        return bool(list_fields[field])
    return False


def _normalized_custom_field_key(value: object) -> str:
    return str(value or "").strip().casefold().replace(" ", "-")


def _normalized_field_name(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def _list_request_fields(request: RoadmapRequest) -> dict[str, tuple[str, ...]]:
    fields: dict[str, tuple[str, ...]] = {}
    fields.update(_item_id_list_request_fields(request))
    fields.update(_path_list_request_fields(request))
    fields.update(_artifact_list_request_fields(request))
    return fields


def _item_id_list_request_fields(request: RoadmapRequest) -> dict[str, tuple[str, ...]]:
    return {
        "dependencies": request.dependencies,
        "slice_members": request.slice_members,
        "slice_dependencies": request.slice_dependencies,
        "supersedes": request.supersedes,
        "superseded_by": request.superseded_by,
    }


def _path_list_request_fields(request: RoadmapRequest) -> dict[str, tuple[str, ...]]:
    return {
        SOURCE_MEMBERS_FIELD: request.source_members,
        "related_specs": request.related_specs,
    }


def _artifact_list_request_fields(request: RoadmapRequest) -> dict[str, tuple[str, ...]]:
    return {
        "target_artifacts": request.target_artifacts,
    }


def _field_scalar(fields: dict[str, object], key: str) -> str:
    value = fields.get(key)
    if value in (None, "", [], ()):
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            text = str(item).strip()
            if text:
                return text
        return ""
    return str(value).strip()


def _field_list(fields: dict[str, object], key: str) -> tuple[str, ...]:
    value = fields.get(key)
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        parsed = _parse_list_value(value) if value.startswith("[") and value.endswith("]") else [value]
        return tuple(str(item).strip() for item in parsed if str(item).strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),)


def _roadmap_source_evidence_findings_for_item(
    inventory: Inventory,
    item_id: str,
    item: RoadmapItem,
    *,
    severity: str,
    source: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for field, rel_path in _roadmap_source_evidence_refs(item.fields):
        problem = _roadmap_source_evidence_problem(inventory, field, rel_path)
        if not problem:
            continue
        findings.append(
            Finding(
                severity,
                _roadmap_source_evidence_problem_code(field, problem),
                (
                    f"roadmap item {item_id!r} {field} evidence {problem}: {rel_path}; "
                    f"{_roadmap_source_evidence_recovery_hint(field)} before relying on roadmap-derived plan input"
                ),
                source,
                item.start + 1,
            )
        )
    return findings


def _roadmap_source_evidence_refs(fields: dict[str, object]) -> tuple[tuple[str, str], ...]:
    refs: list[tuple[str, str]] = []
    source_incubation = _normalize_rel(_field_scalar(fields, "source_incubation"))
    if source_incubation:
        refs.append(("source_incubation", source_incubation))
    source_research = _normalize_rel(_field_scalar(fields, "source_research"))
    if source_research:
        refs.append(("source_research", source_research))
    for source_member in _field_list(fields, SOURCE_MEMBERS_FIELD):
        normalized = _normalize_rel(source_member)
        if normalized:
            refs.append((SOURCE_MEMBERS_FIELD, normalized))
    return tuple(refs)


def _roadmap_source_evidence_problem(inventory: Inventory, field: str, rel_path: str) -> str:
    problem = _roadmap_readiness_path_problem(inventory, rel_path)
    if problem:
        return f"target is {problem}"
    if field == "source_incubation":
        return ""
    quality_problem = _roadmap_readiness_research_quality_problem(inventory, rel_path)
    if quality_problem:
        return f"research quality gate blocks planning: {quality_problem}"
    return ""


def _roadmap_source_evidence_problem_code(field: str, problem: str) -> str:
    normalized_field = field.replace("_", "-")
    if "research quality gate blocks planning" in problem:
        return f"roadmap-{normalized_field}-quality-gate"
    if field == "source_incubation":
        return "roadmap-source-incubation-missing"
    return f"roadmap-{normalized_field}-missing"


def _roadmap_source_evidence_recovery_hint(field: str) -> str:
    if field == "source_incubation":
        return (
            "recover or recreate the incubation note, retarget the item to an existing incubation/archive note, "
            "or run `mylittleharness --root <root> memory-hygiene --dry-run --scan`"
        )
    if field == "source_research":
        return (
            "restore or regenerate the research artifact, retarget source_research, or update the research quality "
            "frontmatter through an explicit reviewed route"
        )
    return (
        "restore or retarget source_members evidence, or update discovery packet quality_status/planning_reliance "
        "through an explicit reviewed route"
    )


def _roadmap_scope_source_text(inventory: Inventory, fields: dict[str, object]) -> str:
    rels = _dedupe_nonempty(
        (
            _normalize_rel(_field_scalar(fields, "source_incubation")),
            _normalize_rel(_field_scalar(fields, RELATED_INCUBATION_FIELD)),
            _normalize_rel(_field_scalar(fields, "source_research")),
            *(_normalize_rel(value) for value in _field_list(fields, SOURCE_MEMBERS_FIELD)),
        )
    )
    chunks: list[str] = []
    for rel in rels:
        if not rel or _roadmap_readiness_path_problem(inventory, rel):
            continue
        path = inventory.root / rel
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
    return "\n\n".join(chunks)


def _implementation_scope_reason(fields: dict[str, object], source_text: str) -> str:
    stage = _normalized_status(_field_scalar(fields, "stage"))
    combined = "\n".join(
        (
            _field_scalar(fields, "slice_goal"),
            _field_scalar(fields, "verification_summary"),
            _field_scalar(fields, "carry_forward"),
            source_text,
        )
    )
    folded = combined.casefold()
    if stage in IMPLEMENTATION_STAGE_VALUES:
        return "accepted implementation roadmap item"
    if "[mlh-fix-candidate]" in folded or "meta-feedback" in folded:
        return "accepted meta-feedback implementation candidate"
    if "future implementation" in folded or "expected_owner_command:" in folded:
        return "accepted implementation roadmap item"
    return ""


def _explicit_deliverable_class(fields: dict[str, object]) -> str:
    for field in DELIVERABLE_CLASS_FIELDS:
        value = _normalized_status(_field_scalar(fields, field))
        if not value:
            continue
        if value in IMPLEMENTATION_DELIVERABLE_VALUES:
            return "implementation"
        if value in NON_IMPLEMENTATION_DELIVERABLE_CLASSES:
            return value
        if value in {"diagnostics", "diagnostic-report", "diagnostic-matrix"}:
            return "diagnostic"
        if value in {"research-only", "research-report", "research-synthesis"}:
            return "research"
        if value in {"cleanup-only", "cleanup-review"}:
            return "cleanup"
        if value in {"review", "fan-in", "fan-in-diagnostic", "fan-in-review-diagnostic"}:
            return "fan-in-review"
        if value in {"proof", "verification", "verification-evidence"}:
            return "evidence"
        if value in {"proposal-only", "proposed"}:
            return "proposal"
        if value in {"audit-only", "audit-proposal", "audit-and-proposal"}:
            return "audit"
        if value in {"route-cleanup", "route-hygiene-cleanup", "lifecycle-hygiene", "lifecycle-route-hygiene"}:
            return "route-hygiene"
    return ""


def _text_signals_deliverable_class(value: str, *, source: str) -> str:
    text = str(value or "").strip().casefold().replace("_", "-")
    if not text:
        return ""
    if source == "stage":
        if "route-hygiene" in text or "route hygiene" in text or "lifecycle-hygiene" in text or "lifecycle hygiene" in text:
            return "route-hygiene"
        if "diagnostic" in text or "diagnostics" in text:
            return "diagnostic"
        if "research" in text:
            return "research"
        if "cleanup" in text:
            return "cleanup"
        if "fan-in" in text and "review" in text:
            return "fan-in-review"
        if "audit" in text:
            return "audit"
        if "proposal" in text or "propose" in text:
            return "proposal"
        if "evidence" in text or "proof" in text or "verification" in text:
            return "evidence"
        return ""
    if re.search(r"\bdiagnostic[- ]only\b|\bdiagnostic\s+only\b|\bdiagnostic\s+matrix\b|\bdiagnostic\s+report\b", text):
        return "diagnostic"
    if re.search(r"\broute[- ]hygiene\b|\blifecycle[- ]hygiene\b|\broute[- ]cleanup\b", text):
        return "route-hygiene"
    if re.search(r"\bresearch[- ]only\b|\bresearch\s+only\b|\bresearch\s+synthesis\b|\bresearch\s+report\b", text):
        return "research"
    if re.search(r"\bcleanup[- ]only\b|\bcleanup\s+only\b|\bcleanup\s+review\b", text):
        return "cleanup"
    if re.search(r"\bfan[- ]in\s+review\b|\bfan[- ]in\s+diagnostic\b", text):
        return "fan-in-review"
    if re.search(r"\baudit(?:\s+and\s+proposal)?\s+only\b", text):
        return "audit"
    if re.search(r"\baudit[- ]only\b", text):
        return "audit"
    if re.search(r"^\s*audit\b", text):
        return "audit"
    if re.search(r"\baudit evidence\b", text):
        return "audit"
    if re.search(r"\bproposal[- ]only\b|\bproposal\s+only\b", text):
        return "proposal"
    if re.search(r"\bevidence[- ]only\b|\bevidence\s+only\b|\bproof[- ]only\b|\bproof\s+only\b", text):
        return "evidence"
    if re.search(r"\bverification evidence\b|\bdurable proof\b", text):
        return "evidence"
    return ""


def _looks_like_product_implementation_route(value: str) -> bool:
    route = _normalize_rel(value).casefold()
    if not route:
        return False
    if route.startswith(("src/", "tests/", "apps/", "packages/", "build_backend/")):
        return True
    return route in {"pyproject.toml", "uv.lock", "package.json", "pytest.ini", "tox.ini"}


def _source_scope_is_recovery_only(value: str) -> bool:
    text = str(value or "").casefold()
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


def _target_artifact_routes_from_scope_text(value: str) -> tuple[str, ...]:
    routes: list[str] = []
    hint = _affected_routes_hint(value)
    if hint:
        routes.extend(_parse_route_hint_list(hint))
    routes.extend(_explicit_target_routes_from_text(value))
    return tuple(route for route in _dedupe_nonempty(routes) if _looks_like_target_artifact_route(route))


def _affected_routes_hint(value: str) -> str:
    match = re.search(
        r"(?is)(?:^|\s)affected_routes:\s*(.+?)(?=\s+(?:agent_friction|authority_boundary|command_choreography|drift_risk|expected_owner_command|false_positive_risk|leak_shape|manual_step|repeatability|safe_boundary|severity|signal_type):|$)",
        str(value or ""),
    )
    return match.group(1).strip() if match else ""


def _parse_route_hint_list(value: str) -> tuple[str, ...]:
    cleaned = str(value or "").strip().strip("`")
    if cleaned.startswith("["):
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return tuple(_normalize_route_hint(item) for item in parsed if _normalize_route_hint(item))
    return tuple(route for route in (_normalize_route_hint(part) for part in cleaned.split(",")) if route)


def _normalize_route_hint(value: object) -> str:
    route = str(value or "").strip().strip("`\"'")
    if route.endswith("."):
        route = route[:-1].rstrip()
    return _normalize_rel(route.strip("[] "))


def _explicit_target_routes_from_text(value: str) -> tuple[str, ...]:
    text = str(value or "").replace("\\", "/")
    routes: list[str] = []
    path_pattern = re.compile(
        r"(?<![A-Za-z0-9_./-])((?:src|tests|docs|project/specs|build_backend|packages|apps)/[A-Za-z0-9_./*-]+)",
        flags=re.IGNORECASE,
    )
    for match in path_pattern.finditer(text):
        route = _normalize_route_hint(match.group(1))
        if route:
            routes.append(route)
    return tuple(_dedupe_nonempty(routes))


def _looks_like_target_artifact_route(value: str) -> bool:
    route = _normalize_rel(value)
    lower = route.casefold()
    if not route or "://" in route or lower.startswith("..") or "/../" in lower:
        return False
    if lower.startswith(("src/", "tests/", "docs/", "build_backend/", "packages/", "apps/", "project/specs/")):
        return True
    return lower in {"agents.md", "readme.md", "package.json", "pyproject.toml", "uv.lock", "pytest.ini", "tox.ini"}


def _human_review_gate_enabled(value: object) -> bool:
    if value in (None, [], ()):
        return False
    if isinstance(value, (list, tuple)):
        return any(_human_review_gate_enabled(item) for item in value)
    normalized = str(value or "").strip().casefold().replace("_", "-")
    if normalized in HUMAN_REVIEW_GATE_FALSEY:
        return False
    return normalized in HUMAN_REVIEW_GATE_TRUTHY


def _roadmap_high_blast_gate_marker(fields: dict[str, object]) -> str:
    for field in HIGH_BLAST_GATE_FIELDS:
        marker = _high_blast_marker_text(field, fields.get(field))
        if marker:
            return marker
    return ""


def _high_blast_marker_text(field: str, value: object) -> str:
    if value in (None, [], ()):
        return ""
    if isinstance(value, (list, tuple, set)):
        for item in value:
            marker = _high_blast_marker_text(field, item)
            if marker:
                return marker
        return ""
    normalized = str(value or "").strip().casefold().replace("_", "-")
    compact = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if not compact:
        return ""
    if "high-blast" in compact:
        return f"{field}={compact}"
    if "fan-in" in compact and "high" in compact:
        return f"{field}={compact}"
    if field == "blast_radius" and compact in {"high", "large", "wide"}:
        return f"{field}={compact}"
    return ""


def _roadmap_batch_authorization_markers(inventory: Inventory, item_ids: tuple[str, ...]) -> tuple[str, ...]:
    markers: list[str] = []
    for item_id in item_ids:
        fields = roadmap_item_fields(inventory, item_id)
        if not fields:
            continue
        for field in BATCH_AUTHORIZATION_FIELDS:
            if _batch_authorization_enabled(fields.get(field)):
                markers.append(f"{item_id}:{field}")
        high_blast_marker = _roadmap_high_blast_gate_marker(fields)
        if high_blast_marker:
            markers.append(f"{item_id}:{high_blast_marker}")
    return tuple(_dedupe_nonempty(markers))


def _roadmap_grouped_slice_boundary_markers(inventory: Inventory, item_ids: tuple[str, ...]) -> tuple[str, ...]:
    markers: list[str] = []
    for item_id in item_ids:
        fields = roadmap_item_fields(inventory, item_id)
        if not fields:
            continue
        boundary = str(fields.get("slice_closeout_boundary") or "").strip().casefold()
        if any(marker in boundary for marker in ("grouped", "bundle", "batch")):
            markers.append(f"{item_id}:slice_closeout_boundary")
    return tuple(_dedupe_nonempty(markers))


def _batch_authorization_enabled(value: object) -> bool:
    if value in (None, [], ()):
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_batch_authorization_enabled(item) for item in value)
    normalized = str(value or "").strip().casefold().replace("_", "-")
    if normalized in HUMAN_REVIEW_GATE_FALSEY:
        return False
    return normalized in BATCH_AUTHORIZATION_TRUTHY


def _values_from_items(items: list[RoadmapItem], key: str) -> list[str]:
    values: list[str] = []
    for item in items:
        values.extend(_field_list(item.fields, key))
    return values


def _first_value_from_items(items: list[RoadmapItem], key: str) -> str:
    for item in items:
        value = _field_scalar(item.fields, key)
        if value:
            return value
    return ""


def _shared_values(items: list[RoadmapItem], key: str) -> tuple[str, ...]:
    if len(items) < 2:
        return ()
    value_sets = [set(_field_list(item.fields, key)) for item in items]
    if not value_sets:
        return ()
    shared = set.intersection(*value_sets)
    return tuple(value for value in _dedupe_nonempty(_values_from_items(items, key)) if value in shared)


def _in_slice_dependencies(items: list[tuple[str, RoadmapItem]], covered: set[str]) -> list[str]:
    edges: list[str] = []
    for roadmap_item_id, item in items:
        for dependency in _field_list(item.fields, "dependencies"):
            if dependency in covered:
                edges.append(f"{roadmap_item_id} -> {dependency}")
    return _dedupe_nonempty(edges)


def _external_dependencies(items: list[tuple[str, RoadmapItem]], covered: set[str]) -> list[str]:
    dependencies: list[str] = []
    for _roadmap_item_id, item in items:
        for dependency in _field_list(item.fields, "dependencies"):
            if dependency not in covered:
                dependencies.append(dependency)
    return _dedupe_nonempty(dependencies)


def _domain_context_for_item(item_id: str, item: RoadmapItem) -> str:
    return _field_scalar(item.fields, "slice_goal") or _normalized_item_id(item.fields.get("execution_slice")) or item.title or item_id


def _summarize_values(values: tuple[str, ...] | list[str], limit: int = 3) -> str:
    compact = [str(value) for value in values if str(value)]
    if len(compact) <= limit:
        return ", ".join(compact)
    return ", ".join(compact[:limit]) + f", +{len(compact) - limit} more"


def _plural(label: str, count: int) -> str:
    return label if count == 1 else f"{label}s"


def _recommended_phase_count(
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


def _empty_field_value(field: str) -> object:
    if field in LIST_FIELDS:
        return []
    if field == "order":
        return 0
    return ""


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _normalized_status(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _normalized_scalar(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _normalize_rel(value: object) -> str:
    return str(value or "").replace("\\", "/").strip()


def _frontmatter_list_values(value: object) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _strip_quotes(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _rel_has_absolute_or_parent_parts(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith("/") or re.match(r"^[A-Za-z]:", rel_path):
        return True
    parts = [part for part in rel_path.split("/") if part]
    return any(part in {".", ".."} for part in parts)


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


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]
