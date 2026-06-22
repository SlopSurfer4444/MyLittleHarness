from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory
from .memory_hygiene import RelationshipUpdatePlan, relationship_update_plan
from .models import Finding
from .parsing import extract_path_refs, parse_frontmatter
from .reporting import RouteWriteEvidence, route_write_findings
from .roadmap import (
    DEFAULT_PLAN_REL,
    ROADMAP_REL,
    RoadmapItem,
    _field_list,
    _field_scalar,
    _parse_roadmap_items_for_sync,
    _render_item_block,
    active_plan_roadmap_item_ids,
)
from .route_reference_guards import route_reference_transaction_guard_findings


TERMINAL_STATUSES = {"done", "rejected", "superseded"}
LIVE_PLAN_STATUSES = {"accepted", "active"}
ROADMAP_PATH_SCALAR_FIELDS = (
    "source_incubation",
    "related_incubation",
    "source_research",
    "related_plan",
    "archived_plan",
)
ROADMAP_PATH_LIST_FIELDS = ("source_members", "related_specs")
ROADMAP_ITEM_LIST_FIELDS = ("slice_members", "slice_dependencies", "dependencies", "supersedes", "superseded_by")
FREE_TEXT_ROUTE_FIELDS = ("verification_summary", "carry_forward")
SOURCE_PATH_FIELDS = ("related_roadmap", "promoted_to", "related_plan", "archived_plan", "implemented_by", "archived_to")
INCUBATION_ROUTE_PREFIXES = ("project/plan-incubation/", "project/archive/reference/incubation/")
RELATIONSHIP_BOUNDARY = (
    "relationship-drift writes only relationship metadata; it does not approve closeout, archive, "
    "roadmap promotion, lifecycle movement, staging, commit, push, rollback, or next-plan opening"
)


@dataclass(frozen=True)
class RelationshipDriftRequest:
    roadmap_item: str = ""


@dataclass(frozen=True)
class RelationshipDriftDecision:
    kind: str
    owner: str
    field: str
    before: str
    after: str
    source: str
    line: int | None = None


@dataclass(frozen=True)
class RelationshipDriftImpact:
    owner: str
    field: str
    target: str
    reason: str
    source: str
    line: int | None = None


@dataclass(frozen=True)
class RelationshipDriftPlan:
    roadmap_path: Path
    current_roadmap_text: str
    updated_roadmap_text: str
    source_plans: tuple[RelationshipUpdatePlan, ...]
    decisions: tuple[RelationshipDriftDecision, ...]
    impacts: tuple[RelationshipDriftImpact, ...]
    before_graph: tuple[str, ...]
    after_graph: tuple[str, ...]


def make_relationship_drift_request(roadmap_item: str | None = None) -> RelationshipDriftRequest:
    return RelationshipDriftRequest(roadmap_item=_normalized_item_id(roadmap_item))


def relationship_drift_dry_run_findings(inventory: Inventory, request: RelationshipDriftRequest) -> list[Finding]:
    findings = [
        Finding("info", "relationship-drift-dry-run", "relationship drift proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    plan, errors = _relationship_drift_plan(inventory, request)
    findings.append(Finding("info", "relationship-drift-target", f"would target roadmap: {ROADMAP_REL}", ROADMAP_REL))
    if request.roadmap_item:
        findings.append(
            Finding(
                "info",
                "relationship-drift-scope",
                f"limited to roadmap item {request.roadmap_item!r}",
                ROADMAP_REL,
            )
        )
    else:
        findings.append(Finding("info", "relationship-drift-scope", "scanning all roadmap items", ROADMAP_REL))

    if plan:
        findings.extend(_graph_findings(plan))
        findings.extend(_decision_findings(plan, apply=False))
        findings.extend(_impact_findings(plan.impacts, apply=False))
        findings.extend(_route_write_findings(plan, apply=False))
        if not _plan_has_changes(plan) and not plan.impacts:
            findings.append(Finding("info", "relationship-drift-noop", "relationship graph already has no planned metadata changes"))

    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "relationship-drift-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing relationship metadata",
                ROADMAP_REL,
            )
        )
        return findings

    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "relationship-drift-validation-posture",
            "apply would write only project/roadmap.md and owned source-incubation relationship metadata in an eligible live operating root; dry-run writes no files",
            ROADMAP_REL,
        )
    )
    return findings


def relationship_drift_apply_findings(inventory: Inventory, request: RelationshipDriftRequest) -> list[Finding]:
    plan, errors = _relationship_drift_plan(inventory, request)
    if errors:
        return errors
    assert plan is not None

    if plan.impacts:
        return [
            Finding("info", "relationship-drift-apply", "relationship drift apply started"),
            _root_posture_finding(inventory),
            *_graph_findings(plan),
            *_decision_findings(plan, apply=True),
            *_impact_findings(plan.impacts, apply=True),
            *_boundary_findings(),
            Finding(
                "info",
                "relationship-drift-validation-posture",
                "relationship-drift apply refused before writing files; resolve missing-route impact and rerun dry-run",
                ROADMAP_REL,
            ),
        ]

    route_writes = _route_write_evidence(plan)
    guard_findings = route_reference_transaction_guard_findings(inventory, route_writes, apply=True)
    if any(finding.severity == "error" for finding in guard_findings):
        return [
            *guard_findings,
            Finding(
                "info",
                "relationship-drift-validation-posture",
                "relationship-drift apply refused before writing files; review unresolved required route references, then rerun dry-run",
                ROADMAP_REL,
            ),
        ]

    if not route_writes:
        return [
            Finding("info", "relationship-drift-apply", "relationship drift apply started"),
            _root_posture_finding(inventory),
            Finding("info", "relationship-drift-noop", "relationship graph already matched the requested metadata posture"),
            *_graph_findings(plan),
            *guard_findings,
            *_boundary_findings(),
        ]

    operations, operation_errors = _atomic_write_operations(inventory, route_writes)
    if operation_errors:
        return operation_errors

    try:
        cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
    except FileTransactionError as exc:
        return [Finding("error", "relationship-drift-refused", f"relationship drift apply failed before all target writes completed: {exc}", ROADMAP_REL)]

    findings = [
        Finding("info", "relationship-drift-apply", "relationship drift apply started"),
        _root_posture_finding(inventory),
        Finding(
            "info",
            "relationship-drift-written",
            "updated roadmap/source-incubation relationship metadata without lifecycle movement",
            ROADMAP_REL,
        ),
        *_graph_findings(plan),
        *_decision_findings(plan, apply=True),
        *route_write_findings("relationship-drift-route-write", route_writes, apply=True),
        *guard_findings,
        *_boundary_findings(),
        Finding(
            "info",
            "relationship-drift-validation-posture",
            "run check after apply to verify the live operating root remains healthy; relationship drift output is not lifecycle approval",
            ROADMAP_REL,
        ),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "relationship-drift-backup-cleanup", warning, ROADMAP_REL))
    return findings


def _relationship_drift_plan(
    inventory: Inventory,
    request: RelationshipDriftRequest,
) -> tuple[RelationshipDriftPlan | None, list[Finding]]:
    errors = _context_errors(inventory)
    roadmap_path = inventory.root / ROADMAP_REL
    errors.extend(_roadmap_target_errors(inventory, roadmap_path))
    if errors:
        return None, errors

    try:
        roadmap_text = roadmap_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("error", "relationship-drift-refused", f"roadmap could not be read: {exc}", ROADMAP_REL)]

    parse_result = _parse_roadmap_items_for_sync(roadmap_text)
    if parse_result[1]:
        return None, parse_result[1]
    _items_start, _items_end, items = parse_result[0]
    selected, selection_errors = _selected_items(items, request)
    if selection_errors:
        return None, selection_errors

    active_ids = set(active_plan_roadmap_item_ids(inventory))
    before_graph = _graph_rows(selected)
    updated_items: dict[str, RoadmapItem] = {}
    decisions: list[RelationshipDriftDecision] = []
    impacts: list[RelationshipDriftImpact] = []
    source_updates: dict[str, dict[str, str]] = {}
    source_clears: dict[str, set[str]] = {}

    for item_id, item in selected:
        fields = dict(item.fields)
        fields, item_decisions = _roadmap_fields_with_relationship_repairs(item_id, item, fields, active_ids, inventory)
        decisions.extend(item_decisions)
        updated_item = RoadmapItem(title=item.title, fields=fields, start=item.start, end=item.end, style=item.style)
        updated_items[item_id] = updated_item
        impacts.extend(_roadmap_path_impacts(inventory, item_id, updated_item, items))
        impacts.extend(_roadmap_item_reference_impacts(item_id, updated_item, items))

        for source_rel in _source_relationship_routes(updated_item):
            _collect_source_relationship_update(
                inventory,
                item_id,
                updated_item,
                active_ids,
                source_rel,
                source_updates,
                source_clears,
                impacts,
            )

    updated_roadmap_text = _roadmap_text_with_items(roadmap_text, updated_items)
    source_plans: list[RelationshipUpdatePlan] = []
    for source_rel in sorted(source_updates):
        updates = source_updates[source_rel]
        clear_fields = tuple(sorted(source_clears.get(source_rel, set())))
        if not _source_needs_relationship_update(inventory, source_rel, updates, clear_fields):
            continue
        source_plan, source_errors = relationship_update_plan(
            inventory,
            source_rel,
            updates,
            clear_fields=clear_fields,
        )
        if source_errors:
            impacts.extend(
                RelationshipDriftImpact(
                    owner=source_rel,
                    field="source_relationship",
                    target=source_rel,
                    reason=finding.message,
                    source=finding.source or source_rel,
                    line=finding.line,
                )
                for finding in source_errors
            )
            continue
        assert source_plan is not None
        source_plans.append(source_plan)
        impacts.extend(_source_frontmatter_path_impacts(inventory, source_plan))
        decisions.extend(_source_relationship_decisions(source_plan))

    after_selected = tuple((item_id, updated_items.get(item_id, item)) for item_id, item in selected)
    return (
        RelationshipDriftPlan(
            roadmap_path=roadmap_path,
            current_roadmap_text=roadmap_text,
            updated_roadmap_text=updated_roadmap_text,
            source_plans=tuple(source_plans),
            decisions=tuple(decisions),
            impacts=tuple(_dedupe_impacts(impacts)),
            before_graph=before_graph,
            after_graph=_graph_rows(after_selected),
        ),
        [],
    )


def _roadmap_fields_with_relationship_repairs(
    item_id: str,
    item: RoadmapItem,
    fields: dict[str, object],
    active_ids: set[str],
    inventory: Inventory,
) -> tuple[dict[str, object], tuple[RelationshipDriftDecision, ...]]:
    decisions: list[RelationshipDriftDecision] = []
    status = _normalized_status(_field_scalar(fields, "status"))
    related_plan = _normalize_rel(_field_scalar(fields, "related_plan"))
    archived_plan = _normalize_rel(_field_scalar(fields, "archived_plan"))
    owned_by_active_plan = item_id in active_ids

    if owned_by_active_plan and status in LIVE_PLAN_STATUSES and related_plan != DEFAULT_PLAN_REL:
        fields, decision = _set_roadmap_field(item_id, item, fields, "related_plan", DEFAULT_PLAN_REL, "retarget")
        decisions.append(decision)
        related_plan = DEFAULT_PLAN_REL

    if status in TERMINAL_STATUSES and archived_plan and related_plan != archived_plan:
        if not _route_path_problem(inventory, archived_plan):
            fields, decision = _set_roadmap_field(item_id, item, fields, "related_plan", archived_plan, "retarget")
            decisions.append(decision)
            related_plan = archived_plan

    if related_plan == DEFAULT_PLAN_REL and not owned_by_active_plan:
        if archived_plan and not _route_path_problem(inventory, archived_plan):
            fields, decision = _set_roadmap_field(item_id, item, fields, "related_plan", archived_plan, "retarget")
            decisions.append(decision)
        elif status not in LIVE_PLAN_STATUSES:
            fields, decision = _set_roadmap_field(item_id, item, fields, "related_plan", "", "detach")
            decisions.append(decision)
    return fields, tuple(decisions)


def _collect_source_relationship_update(
    inventory: Inventory,
    item_id: str,
    item: RoadmapItem,
    active_ids: set[str],
    source_rel: str,
    source_updates: dict[str, dict[str, str]],
    source_clears: dict[str, set[str]],
    impacts: list[RelationshipDriftImpact],
) -> None:
    source_rel = _normalize_rel(source_rel)
    if not source_rel or not _source_relationship_route_allowed(source_rel):
        return
    problem = _route_path_problem(inventory, source_rel)
    if problem:
        impacts.append(
            RelationshipDriftImpact(
                owner=item_id,
                field="source_relationship",
                target=source_rel,
                reason=problem,
                source=ROADMAP_REL,
                line=item.start + 1,
            )
        )
        return

    updates = {
        "related_roadmap": ROADMAP_REL,
        "related_roadmap_item": item_id,
        "promoted_to": ROADMAP_REL,
    }
    clear_fields: set[str] = set()
    status = _normalized_status(_field_scalar(item.fields, "status"))
    archived_plan = _normalize_rel(_field_scalar(item.fields, "archived_plan"))
    if item_id in active_ids and status in LIVE_PLAN_STATUSES:
        updates["related_plan"] = DEFAULT_PLAN_REL
    elif status == "done" and archived_plan and not _route_path_problem(inventory, archived_plan):
        updates["related_plan"] = archived_plan
        updates["archived_plan"] = archived_plan
        updates["implemented_by"] = archived_plan
    elif _frontmatter_scalar(inventory.root / source_rel, "related_plan") == DEFAULT_PLAN_REL:
        clear_fields.add("related_plan")

    _merge_source_relationship_update(source_rel, updates, clear_fields, source_updates, source_clears, impacts)


def _merge_source_relationship_update(
    source_rel: str,
    updates: dict[str, str],
    clear_fields: set[str],
    source_updates: dict[str, dict[str, str]],
    source_clears: dict[str, set[str]],
    impacts: list[RelationshipDriftImpact],
) -> None:
    target_updates = source_updates.setdefault(source_rel, {})
    target_clears = source_clears.setdefault(source_rel, set())
    for key, value in updates.items():
        existing = target_updates.get(key)
        if existing and existing != value:
            impacts.append(
                RelationshipDriftImpact(
                    owner=source_rel,
                    field=key,
                    target=value,
                    reason=f"conflicts with another planned value {existing!r}",
                    source=source_rel,
                )
            )
            continue
        target_updates[key] = value
        target_clears.discard(key)
    for key in clear_fields:
        if key in target_updates:
            impacts.append(
                RelationshipDriftImpact(
                    owner=source_rel,
                    field=key,
                    target="",
                    reason=f"conflicts with planned value {target_updates[key]!r}",
                    source=source_rel,
                )
            )
            continue
        target_clears.add(key)


def _selected_items(
    items: dict[str, RoadmapItem],
    request: RelationshipDriftRequest,
) -> tuple[tuple[tuple[str, RoadmapItem], ...], list[Finding]]:
    if request.roadmap_item:
        item = items.get(request.roadmap_item)
        if item is None:
            return (), [Finding("error", "relationship-drift-refused", f"roadmap item not found: {request.roadmap_item}", ROADMAP_REL)]
        return ((request.roadmap_item, item),), []
    return tuple(sorted(items.items(), key=lambda row: (row[1].start, row[0]))), []


def _roadmap_text_with_items(text: str, updated_items: dict[str, RoadmapItem]) -> str:
    if not updated_items:
        return text
    lines = text.splitlines(keepends=True)
    for item in sorted(updated_items.values(), key=lambda candidate: candidate.start, reverse=True):
        lines[item.start : item.end] = [_render_item_block(item.title, item.fields)]
    return "".join(lines)


def _route_write_evidence(plan: RelationshipDriftPlan) -> tuple[RouteWriteEvidence, ...]:
    writes: list[RouteWriteEvidence] = []
    if plan.current_roadmap_text != plan.updated_roadmap_text:
        writes.append(RouteWriteEvidence(ROADMAP_REL, plan.current_roadmap_text, plan.updated_roadmap_text))
    for source_plan in plan.source_plans:
        if source_plan.current_text != source_plan.updated_text:
            writes.append(RouteWriteEvidence(source_plan.target_rel, source_plan.current_text, source_plan.updated_text))
    return tuple(writes)


def _route_write_findings(plan: RelationshipDriftPlan, *, apply: bool) -> list[Finding]:
    route_writes = _route_write_evidence(plan)
    findings = route_write_findings("relationship-drift-route-write", route_writes, apply=apply)
    findings.extend(route_reference_transaction_guard_findings(_InventoryForGuard(plan), route_writes, apply=apply))
    return findings


class _InventoryForGuard:
    def __init__(self, plan: RelationshipDriftPlan) -> None:
        self.root = plan.roadmap_path.parents[1]


def _atomic_write_operations(
    inventory: Inventory,
    route_writes: tuple[RouteWriteEvidence, ...],
) -> tuple[list[AtomicFileWrite], list[Finding]]:
    operations: list[AtomicFileWrite] = []
    for write in route_writes:
        if write.after_text is None:
            continue
        rel_path = _normalize_rel(write.rel_path)
        target_path = inventory.root / rel_path
        tmp_path = target_path.with_name(f".{target_path.name}.relationship-drift.tmp")
        backup_path = target_path.with_name(f".{target_path.name}.relationship-drift.backup")
        for candidate, label in (
            (tmp_path, "temporary relationship write path"),
            (backup_path, "temporary relationship backup path"),
        ):
            if candidate.exists():
                return [], [
                    Finding(
                        "error",
                        "relationship-drift-refused",
                        f"{label} already exists: {candidate.relative_to(inventory.root).as_posix()}",
                        rel_path,
                    )
                ]
        operations.append(AtomicFileWrite(target_path, tmp_path, write.after_text, backup_path))
    return operations, []


def _source_needs_relationship_update(
    inventory: Inventory,
    source_rel: str,
    updates: dict[str, str],
    clear_fields: tuple[str, ...],
) -> bool:
    source_path = inventory.root / source_rel
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError:
        return True
    for key, value in updates.items():
        if _frontmatter_value(text, key) != value:
            return True
    for key in clear_fields:
        if _frontmatter_value(text, key):
            return True
    return False


def _source_relationship_decisions(plan: RelationshipUpdatePlan) -> tuple[RelationshipDriftDecision, ...]:
    decisions: list[RelationshipDriftDecision] = []
    for field in plan.changed_fields:
        decisions.append(
            RelationshipDriftDecision(
                kind="source-metadata",
                owner=plan.source_rel,
                field=field,
                before=_frontmatter_value(plan.current_text, field),
                after=_frontmatter_value(plan.updated_text, field),
                source=plan.target_rel,
            )
        )
    return tuple(decisions)


def _roadmap_path_impacts(
    inventory: Inventory,
    item_id: str,
    item: RoadmapItem,
    items: dict[str, RoadmapItem],
) -> tuple[RelationshipDriftImpact, ...]:
    impacts: list[RelationshipDriftImpact] = []
    for field in ROADMAP_PATH_SCALAR_FIELDS:
        target = _normalize_rel(_field_scalar(item.fields, field))
        problem = _route_path_problem(inventory, target)
        if problem:
            impacts.append(RelationshipDriftImpact(item_id, field, target, problem, ROADMAP_REL, item.start + 1))
    for field in ROADMAP_PATH_LIST_FIELDS:
        for target in _field_list(item.fields, field):
            target = _normalize_rel(target)
            problem = _route_path_problem(inventory, target)
            if problem:
                impacts.append(RelationshipDriftImpact(item_id, field, target, problem, ROADMAP_REL, item.start + 1))
    for field in FREE_TEXT_ROUTE_FIELDS:
        for target in _free_text_route_refs(_field_scalar(item.fields, field)):
            problem = _route_path_problem(inventory, target)
            if problem:
                impacts.append(RelationshipDriftImpact(item_id, field, target, problem, ROADMAP_REL, item.start + 1))
    return tuple(impacts)


def _roadmap_item_reference_impacts(
    item_id: str,
    item: RoadmapItem,
    items: dict[str, RoadmapItem],
) -> tuple[RelationshipDriftImpact, ...]:
    impacts: list[RelationshipDriftImpact] = []
    for field in ROADMAP_ITEM_LIST_FIELDS:
        for target in _field_list(item.fields, field):
            normalized = _normalized_item_id(target)
            if normalized and normalized not in items:
                impacts.append(
                    RelationshipDriftImpact(
                        owner=item_id,
                        field=field,
                        target=normalized,
                        reason="missing roadmap item",
                        source=ROADMAP_REL,
                        line=item.start + 1,
                    )
                )
    return tuple(impacts)


def _source_frontmatter_path_impacts(
    inventory: Inventory,
    plan: RelationshipUpdatePlan,
) -> tuple[RelationshipDriftImpact, ...]:
    frontmatter = parse_frontmatter(plan.updated_text)
    impacts: list[RelationshipDriftImpact] = []
    for field in SOURCE_PATH_FIELDS:
        for target in _frontmatter_values(frontmatter.data.get(field)):
            problem = _route_path_problem(inventory, target)
            if problem:
                impacts.append(RelationshipDriftImpact(plan.source_rel, field, target, problem, plan.target_rel))
    return tuple(impacts)


def _free_text_route_refs(value: str) -> tuple[str, ...]:
    refs = []
    for ref in extract_path_refs(value):
        target = _normalize_rel(ref.target)
        if _should_validate_route_target(target):
            refs.append(target)
    return tuple(dict.fromkeys(refs))


def _source_relationship_routes(item: RoadmapItem) -> tuple[str, ...]:
    rels: list[str] = []
    for field in ("source_incubation", "related_incubation"):
        rel = _normalize_rel(_field_scalar(item.fields, field))
        if rel:
            rels.append(rel)
    return tuple(rel for rel in dict.fromkeys(rels) if _source_relationship_route_allowed(rel))


def _set_roadmap_field(
    item_id: str,
    item: RoadmapItem,
    fields: dict[str, object],
    field: str,
    value: str,
    kind: str,
) -> tuple[dict[str, object], RelationshipDriftDecision]:
    before = _field_scalar(fields, field)
    updated = dict(fields)
    updated[field] = value
    return (
        updated,
        RelationshipDriftDecision(
            kind=kind,
            owner=item_id,
            field=field,
            before=before,
            after=value,
            source=ROADMAP_REL,
            line=item.start + 1,
        ),
    )


def _graph_findings(plan: RelationshipDriftPlan) -> list[Finding]:
    return [
        Finding("info", "relationship-drift-graph-before", _format_graph(plan.before_graph), ROADMAP_REL),
        Finding("info", "relationship-drift-graph-after", _format_graph(plan.after_graph), ROADMAP_REL),
    ]


def _decision_findings(plan: RelationshipDriftPlan, *, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    return [
        Finding(
            "info",
            f"relationship-drift-{decision.kind}",
            f"{prefix}{decision.kind} {decision.owner}.{decision.field}: {decision.before or '<empty>'} -> {decision.after or '<empty>'}",
            decision.source,
            decision.line,
        )
        for decision in plan.decisions
        if decision.before != decision.after
    ]


def _impact_findings(impacts: tuple[RelationshipDriftImpact, ...], *, apply: bool) -> list[Finding]:
    severity = "error" if apply else "warn"
    prefix = "refuse apply" if apply else "would block apply"
    return [
        Finding(
            severity,
            "relationship-drift-missing-route-impact",
            f"{prefix}: {impact.owner}.{impact.field} -> {impact.target or '<empty>'}: {impact.reason}; {RELATIONSHIP_BOUNDARY}",
            impact.source,
            impact.line,
        )
        for impact in impacts
    ]


def _graph_rows(items: tuple[tuple[str, RoadmapItem], ...]) -> tuple[str, ...]:
    rows: list[str] = []
    for item_id, item in items:
        fields = item.fields
        row = (
            f"{item_id}: status={_field_scalar(fields, 'status') or '<empty>'}; "
            f"source_incubation={_field_scalar(fields, 'source_incubation') or '<empty>'}; "
            f"source_members={_format_tuple(_field_list(fields, 'source_members'))}; "
            f"related_plan={_field_scalar(fields, 'related_plan') or '<empty>'}; "
            f"archived_plan={_field_scalar(fields, 'archived_plan') or '<empty>'}; "
            f"slice_members={_format_tuple(_field_list(fields, 'slice_members'))}"
        )
        rows.append(row)
    return tuple(rows)


def _format_graph(rows: tuple[str, ...]) -> str:
    if not rows:
        return "relationship graph is empty"
    limit = 8
    selected = list(rows[:limit])
    if len(rows) > limit:
        selected.append(f"+{len(rows) - limit} more")
    return " | ".join(selected)


def _format_tuple(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(values) + "]" if values else "[]"


def _plan_has_changes(plan: RelationshipDriftPlan) -> bool:
    return bool(_route_write_evidence(plan))


def _context_errors(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "error",
                "relationship-drift-refused",
                f"target root kind is {inventory.root_kind}; relationship-drift requires a live operating root",
            )
        ]
    return []


def _roadmap_target_errors(inventory: Inventory, target_path: Path) -> list[Finding]:
    if _path_escapes_root(inventory.root, target_path):
        return [Finding("error", "relationship-drift-refused", "roadmap path escapes the target root", ROADMAP_REL)]
    if not target_path.exists():
        return [Finding("error", "relationship-drift-refused", "project/roadmap.md is required", ROADMAP_REL)]
    if target_path.is_symlink():
        return [Finding("error", "relationship-drift-refused", "project/roadmap.md is a symlink", ROADMAP_REL)]
    if not target_path.is_file():
        return [Finding("error", "relationship-drift-refused", "project/roadmap.md is not a regular file", ROADMAP_REL)]
    return []


def _route_path_problem(inventory: Inventory, target: str) -> str:
    target = _normalize_rel(target)
    if not target or not _should_validate_route_target(target):
        return ""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target) or target.startswith("mailto:"):
        return ""
    if "*" in target or "{" in target:
        return "route target must be concrete, not a pattern"
    if _is_absolute_path(target):
        try:
            target = Path(target).expanduser().resolve().relative_to(inventory.root.resolve()).as_posix()
        except (OSError, RuntimeError, ValueError):
            return "outside the target root"
    if _rel_has_absolute_or_parent_parts(target):
        return "not a safe root-relative route"
    path = inventory.root / target
    if _path_escapes_root(inventory.root, path):
        return "outside the target root"
    if not path.exists():
        return "missing"
    if path.is_symlink():
        return "a symlink"
    if not path.is_file():
        return "not a regular file"
    return ""


def _should_validate_route_target(target: str) -> bool:
    normalized = _normalize_rel(target)
    return (
        normalized in {"README.md", "AGENTS.md"}
        or normalized.startswith((".agents/", ".codex/", "docs/", "project/"))
        or _is_absolute_path(normalized)
    )


def _source_relationship_route_allowed(rel_path: str) -> bool:
    normalized = _normalize_rel(rel_path)
    return normalized.endswith(".md") and any(normalized.startswith(prefix) for prefix in INCUBATION_ROUTE_PREFIXES)


def _frontmatter_scalar(path: Path, key: str) -> str:
    try:
        return _frontmatter_value(path.read_text(encoding="utf-8"), key)
    except OSError:
        return ""


def _frontmatter_value(text: str, key: str) -> str:
    frontmatter = parse_frontmatter(text)
    value = frontmatter.data.get(key)
    values = _frontmatter_values(value)
    return values[0] if values else ""


def _frontmatter_values(value: object) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, str):
        return (_normalize_rel(value),)
    if isinstance(value, (list, tuple, set)):
        return tuple(_normalize_rel(item) for item in value if _normalize_rel(item))
    return (_normalize_rel(value),)


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "relationship-drift-root-posture", f"root kind: {inventory.root_kind}")


def _boundary_findings() -> list[Finding]:
    return [
        Finding("info", "relationship-drift-boundary", RELATIONSHIP_BOUNDARY, ROADMAP_REL),
        Finding(
            "info",
            "relationship-drift-authority",
            "relationship graph output is hygiene evidence only; repo-visible source files and explicit lifecycle rails remain authority",
            ROADMAP_REL,
        ),
    ]


def _dedupe_impacts(impacts: list[RelationshipDriftImpact]) -> tuple[RelationshipDriftImpact, ...]:
    seen: set[tuple[str, str, str, str, str, int | None]] = set()
    deduped: list[RelationshipDriftImpact] = []
    for impact in impacts:
        key = (impact.owner, impact.field, impact.target, impact.reason, impact.source, impact.line)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(impact)
    return tuple(deduped)


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]


def _normalized_status(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _normalize_rel(value: object) -> str:
    normalized = str(value or "").strip().strip("`\"'").strip("<>").replace("\\", "/")
    normalized = normalized.split("#", 1)[0]
    return re.sub(r"/+", "/", normalized).strip().rstrip(".,;:)]")


def _rel_has_absolute_or_parent_parts(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith("/") or _is_absolute_path(rel_path):
        return True
    parts = [part for part in rel_path.split("/") if part]
    return any(part in {"", ".", ".."} for part in parts)


def _is_absolute_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or Path(value).is_absolute()


def _path_escapes_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return False
    except (OSError, RuntimeError, ValueError):
        return True
