from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryRoute:
    route_id: str
    target: str
    purpose: str
    start_path: str
    authority: str


@dataclass(frozen=True)
class IntakeRouteAdvice:
    route_id: str
    target: str
    confidence: str
    reason: str
    next_action: str
    apply_allowed: bool


@dataclass(frozen=True)
class RouteOrchestrationPolicy:
    parallelism_class: str
    authority_lane: str
    exclusive_owner: str
    claim_scope: tuple[str, ...]
    claim_required: bool
    merge_policy: str
    fan_in_gate: tuple[str, ...]
    max_parallelism_hint: str
    stale_claim_policy: str
    conflict_policy: str


LIVE_LIFECYCLE_ROUTES: tuple[MemoryRoute, ...] = (
    MemoryRoute(
        "state",
        "project/project-state.md",
        "durable project memory, current focus, lifecycle pointers, and closeout writeback authority",
        "always",
        "authority",
    ),
    MemoryRoute(
        "active-plan",
        "project/implementation-plan.md",
        "bounded execution plan when plan_status is active",
        "when active",
        "authority",
    ),
    MemoryRoute(
        "roadmap",
        "project/roadmap.md",
        "optional sequencing surface for accepted work between incubation and one active implementation plan",
        "when planning/sequencing",
        "sequencing advisory",
    ),
    MemoryRoute(
        "incubation",
        "project/plan-incubation/*.md",
        "temporary same-topic synthesis before research, spec, or plan promotion",
        "by task",
        "non-authority until promoted",
    ),
    MemoryRoute(
        "research",
        "project/research/*.md",
        "durable research findings and distilled external evidence",
        "by task",
        "non-authority until promoted",
    ),
    MemoryRoute(
        "stable-specs",
        "project/specs/**/*.md",
        "stable workflow contracts and routing rules",
        "by route",
        "authority",
    ),
    MemoryRoute(
        "decisions",
        "project/decisions/*.md",
        "accepted rationale and do-not-revisit records",
        "by task",
        "authority when accepted",
    ),
    MemoryRoute(
        "adrs",
        "project/adrs/*.md",
        "material architecture decision records",
        "explicit need",
        "authority when accepted",
    ),
    MemoryRoute(
        "verification",
        "active-plan verification block; project/verification/*.md",
        "default verification evidence surface plus optional durable proof/evidence records",
        "at verification or closeout",
        "evidence",
    ),
    MemoryRoute(
        "agent-runs",
        "project/verification/agent-runs/*.md",
        "source-bound durable agent run evidence records",
        "at explicit run evidence record",
        "evidence",
    ),
    MemoryRoute(
        "work-claims",
        "project/verification/work-claims/*.json",
        "repo-visible scoped work and fan-in coordination evidence",
        "at explicit work claim record",
        "evidence",
    ),
    MemoryRoute(
        "closeout-writeback",
        "project/project-state.md MLH closeout writeback block",
        "current closeout fact authority; explicit closeout active-plan copies are derived metadata",
        "at closeout",
        "authority",
    ),
    MemoryRoute(
        "archive",
        "project/archive/plans/*.md; project/archive/reference/**",
        "historical plans and reference material, not default execution authority",
        "explicit need",
        "reference",
    ),
    MemoryRoute(
        "docs-routing",
        ".agents/docmap.yaml",
        "optional docs routing aid for product docs and impact checks; not authority by itself",
        "by task",
        "advisory",
    ),
)

SUPPORT_ROUTES: tuple[MemoryRoute, ...] = (
    MemoryRoute(
        "operating-guardrails",
        "AGENTS.md; .mylittleharness/project-workflow.toml; .codex/project-workflow.toml",
        "operator contract and workflow manifest",
        "always",
        "authority",
    ),
    MemoryRoute(
        "orientation",
        "README.md",
        "human orientation surface",
        "by task",
        "advisory",
    ),
    MemoryRoute(
        "product-docs",
        "docs/**/*.md",
        "reusable product documentation and product contracts",
        "by task",
        "authority for product behavior",
    ),
    MemoryRoute(
        "generated-cache",
        ".mylittleharness/generated/**",
        "rebuildable navigation and search cache",
        "never authority",
        "generated advisory",
    ),
    MemoryRoute(
        "package-mirror",
        "specs/workflow/*.md",
        "package-source mirror material",
        "by task",
        "derived",
    ),
    MemoryRoute(
        "unclassified",
        "<unknown>",
        "repo-visible surface without a known memory route",
        "explicit inspection",
        "unknown",
    ),
)

ROUTE_REGISTRY: tuple[MemoryRoute, ...] = LIVE_LIFECYCLE_ROUTES + SUPPORT_ROUTES
ROUTE_BY_ID = {route.route_id: route for route in ROUTE_REGISTRY}

EXACT_DOC_TARGET_PREFIXES = ("docs/", "project/specs/", "src/mylittleharness/templates/")


def normalize_route_path(value: str) -> str:
    rel = str(value or "").strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.strip("/")


def is_exact_doc_target(value: str) -> bool:
    rel = normalize_route_path(value).casefold()
    if not rel or ".." in rel.split("/"):
        return False
    if rel.endswith("/"):
        return False
    return rel.endswith(".md") and any(rel.startswith(prefix) for prefix in EXACT_DOC_TARGET_PREFIXES)


def existing_doc_target_candidates(root: Path, value: str, *, limit: int = 4) -> tuple[str, ...]:
    rel = normalize_route_path(value)
    if not rel or not is_exact_doc_target(rel) or not root.is_dir():
        return ()
    exact = root / rel
    if exact.is_file() and not exact.is_symlink():
        return (rel,)

    candidates: list[str] = []
    for candidate in _known_doc_target_alternates(rel):
        _append_existing_doc_candidate(root, candidate, candidates)

    leaf = Path(rel).name
    try:
        matches = sorted(root.rglob(leaf), key=lambda path: _doc_candidate_sort_key(root, path))
    except OSError:
        matches = []
    for candidate in matches:
        if candidate.is_file() and not candidate.is_symlink():
            try:
                candidate_rel = candidate.relative_to(root).as_posix()
            except ValueError:
                continue
            _append_existing_doc_candidate(root, candidate_rel, candidates)
        if len(candidates) >= limit:
            break
    return tuple(candidates[:limit])


def doc_target_exists(root: Path, value: str) -> bool:
    rel = normalize_route_path(value)
    if not rel:
        return False
    candidate = root / rel
    return candidate.is_file() and not candidate.is_symlink()


def _known_doc_target_alternates(rel: str) -> tuple[str, ...]:
    normalized = normalize_route_path(rel)
    alternates: list[str] = []
    if normalized.startswith("docs/specs/"):
        tail = normalized.removeprefix("docs/specs/")
        alternates.append(f"project/specs/{tail}")
        alternates.append(f"src/mylittleharness/templates/{tail}")
    elif normalized.startswith("project/specs/"):
        tail = normalized.removeprefix("project/specs/")
        alternates.append(f"docs/specs/{tail}")
        alternates.append(f"src/mylittleharness/templates/{tail}")
    elif normalized.startswith("src/mylittleharness/templates/"):
        tail = normalized.removeprefix("src/mylittleharness/templates/")
        alternates.append(f"project/specs/{tail}")
        alternates.append(f"docs/specs/{tail}")
    return tuple(alternates)


def _append_existing_doc_candidate(root: Path, rel: str, candidates: list[str]) -> None:
    rel = normalize_route_path(rel)
    if not rel or rel in candidates:
        return
    path = root / rel
    if path.is_file() and not path.is_symlink():
        candidates.append(rel)


def _doc_candidate_sort_key(root: Path, path: Path) -> tuple[int, str]:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()
    priority = 2
    if rel.startswith("project/specs/"):
        priority = 0
    elif rel.startswith("src/mylittleharness/templates/"):
        priority = 1
    elif rel.startswith("docs/"):
        priority = 2
    return (priority, rel)

INTAKE_ROUTE_ALLOWED_TARGETS = {
    "adrs",
    "archive",
    "decisions",
    "incubation",
    "product-docs",
    "research",
    "verification",
}
INTAKE_ROUTE_DEFAULT_STATUS = {
    "adrs": "draft",
    "archive": "archived",
    "decisions": "draft",
    "incubation": "incubating",
    "product-docs": "draft",
    "research": "imported",
    "verification": "partial",
}
INTAKE_TARGET_GUIDED_CUES = {
    "verification": (
        "verification",
        "evidence",
        "proof",
        "audit",
        "decision packet",
        "safe to continue",
        "safe_to_continue",
        "replay",
        "pytest",
        "tests",
        "smoke",
        "validation",
    ),
}
INTAKE_ROUTE_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "adrs",
        (
            "adr:",
            "adr ",
            "architecture decision record",
            "architecture decision",
            "architecture markdown",
            "architecture route",
            "target architecture",
        ),
    ),
    (
        "decisions",
        (
            "decision:",
            "decision record",
            "decided:",
            "do-not-revisit",
            "do not revisit",
            "we decided",
            "accepted decision",
        ),
    ),
    ("verification", ("verification:", "verified:", "pytest", "tests passed", "smoke passed", "validation passed", "evidence:")),
    ("product-docs", ("docs impact:", "doc impact:", "documentation:", "readme", "docs update", "documentation update")),
    ("archive", ("archive reference:", "archived reference", "historical reference", "legacy reference", "for reference only")),
    ("research", ("research import:", "research:", "distillate:", "source notes", "imported research", "raw import")),
    (
        "incubation",
        (
            "future idea:",
            "idea:",
            "feature idea",
            "future feature",
            "future product idea",
            "product idea",
            "follow-up:",
            "follow up:",
            "later:",
            "todo:",
            "proposal:",
            "candidate:",
        ),
    ),
)
FUTURE_FEATURE_INTAKE_CUES = ("feature idea", "future feature", "future product idea", "product idea")
DEEP_RESEARCH_PROMPT_COMPOSITION_INTAKE_CUES = ("deep research prompt", "research prompt", "prompt composition")
AMBIGUOUS_INTAKE = IntakeRouteAdvice(
    route_id="ambiguous",
    target="<manual-route-required>",
    confidence="none",
    reason="no single route cue dominated the input",
    next_action="classify the input explicitly before writing operating memory",
    apply_allowed=False,
)

ROLE_TO_ROUTE_ID = {
    "active-plan": "active-plan",
    "adr": "adrs",
    "decision": "decisions",
    "docmap": "docs-routing",
    "incubation": "incubation",
    "manifest": "operating-guardrails",
    "operator-contract": "operating-guardrails",
    "orientation": "orientation",
    "package-mirror": "package-mirror",
    "product-doc": "product-docs",
    "project-state": "state",
    "roadmap": "roadmap",
    "research": "research",
    "stable-spec": "stable-specs",
    "verification": "verification",
}

_ROUTE_MUTABILITY = {
    "active-plan": "lifecycle-apply-rail",
    "adrs": "human-reviewed-authority",
    "archive": "archive-apply-rail",
    "agent-runs": "evidence-record-apply-rail",
    "work-claims": "claim-apply-rail",
    "closeout-writeback": "lifecycle-apply-rail",
    "decisions": "human-reviewed-authority",
    "docs-routing": "advisory-file",
    "generated-cache": "generated-rebuildable",
    "incubation": "intake-or-incubate-apply-rail",
    "operating-guardrails": "human-reviewed-authority",
    "product-docs": "human-reviewed-product-contract",
    "research": "research-or-hygiene-apply-rail",
    "roadmap": "roadmap-apply-rail",
    "stable-specs": "human-reviewed-authority",
    "state": "lifecycle-apply-rail",
    "verification": "evidence-route",
}

_ROUTE_GATE_CLASS = {
    "active-plan": "lifecycle",
    "adrs": "authority",
    "archive": "archive",
    "agent-runs": "evidence",
    "work-claims": "evidence",
    "closeout-writeback": "lifecycle",
    "decisions": "authority",
    "operating-guardrails": "authority",
    "product-docs": "product-contract",
    "roadmap": "planning",
    "stable-specs": "authority",
    "state": "lifecycle",
}

_ROUTE_ALLOWED_DECISIONS = {
    "active-plan": ("plan", "writeback", "transition"),
    "adrs": ("accept", "supersede", "archive"),
    "archive": ("archive", "restore-reference"),
    "agent-runs": ("record", "inspect"),
    "work-claims": ("create", "release", "inspect"),
    "closeout-writeback": ("writeback", "transition"),
    "decisions": ("accept", "supersede", "archive"),
    "operating-guardrails": ("repair", "manual-review"),
    "product-docs": ("update", "not-needed", "uncertain"),
    "roadmap": ("add", "update", "mark-active", "mark-done"),
    "stable-specs": ("update", "supersede", "reject"),
    "state": ("writeback", "compact", "transition"),
}

_LIFECYCLE_ORCHESTRATION = RouteOrchestrationPolicy(
    parallelism_class="sequential_only",
    authority_lane="lifecycle",
    exclusive_owner="coordinator",
    claim_scope=("route", "lifecycle"),
    claim_required=True,
    merge_policy="pessimistic_lock",
    fan_in_gate=("review_token", "deterministic_verifier", "human_gate_when_required"),
    max_parallelism_hint="1",
    stale_claim_policy="coordinator_review",
    conflict_policy="refuse",
)
_AUTHORITY_ORCHESTRATION = RouteOrchestrationPolicy(
    parallelism_class="human_gated",
    authority_lane="product_source",
    exclusive_owner="coordinator_or_human_reviewer",
    claim_scope=("path", "route"),
    claim_required=True,
    merge_policy="reviewed_fan_in",
    fan_in_gate=("evidence_packet", "review_token", "human_gate"),
    max_parallelism_hint="1",
    stale_claim_policy="manual_release",
    conflict_policy="human_gate",
)
_EVIDENCE_ORCHESTRATION = RouteOrchestrationPolicy(
    parallelism_class="safe_parallel",
    authority_lane="verification",
    exclusive_owner="assigned_verifier",
    claim_scope=("path", "execution_slice"),
    claim_required=True,
    merge_policy="reviewed_fan_in",
    fan_in_gate=("evidence_packet", "deterministic_verifier"),
    max_parallelism_hint="2-3",
    stale_claim_policy="coordinator_review",
    conflict_policy="queue_or_refuse",
)
_SYNTHESIS_ORCHESTRATION = RouteOrchestrationPolicy(
    parallelism_class="safe_parallel",
    authority_lane="research",
    exclusive_owner="assigned_researcher",
    claim_scope=("topic", "path"),
    claim_required=True,
    merge_policy="reviewed_fan_in",
    fan_in_gate=("source_bound_summary", "coordinator_review"),
    max_parallelism_hint="3-6",
    stale_claim_policy="manual_release",
    conflict_policy="queue_or_refuse",
)
_GENERATED_ORCHESTRATION = RouteOrchestrationPolicy(
    parallelism_class="safe_parallel",
    authority_lane="generated_cache",
    exclusive_owner="generated_cache_builder",
    claim_scope=("generated_cache",),
    claim_required=False,
    merge_policy="rebuildable_no_merge",
    fan_in_gate=("deterministic_rebuild", "source_files_remain_authority"),
    max_parallelism_hint="read_only_unbounded_with_budget",
    stale_claim_policy="discard_and_rebuild",
    conflict_policy="regenerate",
)
_DEFAULT_ORCHESTRATION = RouteOrchestrationPolicy(
    parallelism_class="risky_parallel",
    authority_lane="product_source",
    exclusive_owner="coordinator_review",
    claim_scope=("path",),
    claim_required=True,
    merge_policy="reviewed_fan_in",
    fan_in_gate=("evidence_packet", "review_token"),
    max_parallelism_hint="2-3",
    stale_claim_policy="coordinator_review",
    conflict_policy="human_gate",
)
_ROUTE_ORCHESTRATION = {
    "active-plan": _LIFECYCLE_ORCHESTRATION,
    "closeout-writeback": _LIFECYCLE_ORCHESTRATION,
    "roadmap": _LIFECYCLE_ORCHESTRATION,
    "state": _LIFECYCLE_ORCHESTRATION,
    "adrs": _AUTHORITY_ORCHESTRATION,
    "decisions": _AUTHORITY_ORCHESTRATION,
    "operating-guardrails": _AUTHORITY_ORCHESTRATION,
    "product-docs": _AUTHORITY_ORCHESTRATION,
    "stable-specs": _AUTHORITY_ORCHESTRATION,
    "verification": _EVIDENCE_ORCHESTRATION,
    "agent-runs": _EVIDENCE_ORCHESTRATION,
    "work-claims": _EVIDENCE_ORCHESTRATION,
    "incubation": _SYNTHESIS_ORCHESTRATION,
    "research": _SYNTHESIS_ORCHESTRATION,
    "archive": RouteOrchestrationPolicy(
        parallelism_class="sequential_only",
        authority_lane="archive",
        exclusive_owner="archivist_or_coordinator",
        claim_scope=("archive_route", "source_route"),
        claim_required=True,
        merge_policy="pessimistic_lock",
        fan_in_gate=("coverage_evidence", "review_token"),
        max_parallelism_hint="1",
        stale_claim_policy="coordinator_review",
        conflict_policy="refuse",
    ),
    "docs-routing": RouteOrchestrationPolicy(
        parallelism_class="risky_parallel",
        authority_lane="adapter",
        exclusive_owner="docs_router",
        claim_scope=("path", "doc_route"),
        claim_required=True,
        merge_policy="reviewed_fan_in",
        fan_in_gate=("doc_impact_evidence", "coordinator_review"),
        max_parallelism_hint="2-3",
        stale_claim_policy="manual_release",
        conflict_policy="human_gate",
    ),
    "generated-cache": _GENERATED_ORCHESTRATION,
    "orientation": RouteOrchestrationPolicy(
        parallelism_class="human_gated",
        authority_lane="product_source",
        exclusive_owner="human_reviewer",
        claim_scope=("path",),
        claim_required=True,
        merge_policy="reviewed_fan_in",
        fan_in_gate=("docs_decision", "review_token"),
        max_parallelism_hint="1",
        stale_claim_policy="manual_release",
        conflict_policy="human_gate",
    ),
    "package-mirror": RouteOrchestrationPolicy(
        parallelism_class="risky_parallel",
        authority_lane="product_source",
        exclusive_owner="package_maintainer",
        claim_scope=("path", "mirror_group"),
        claim_required=True,
        merge_policy="reviewed_fan_in",
        fan_in_gate=("mirror_parity_evidence", "deterministic_verifier"),
        max_parallelism_hint="2-3",
        stale_claim_policy="coordinator_review",
        conflict_policy="queue_or_refuse",
    ),
    "unclassified": _DEFAULT_ORCHESTRATION,
}


def lifecycle_route_rows() -> tuple[tuple[str, str, str], ...]:
    return tuple((route.route_id, route.target, route.purpose) for route in LIVE_LIFECYCLE_ROUTES)


def route_orchestration_for_id(route_id: str | None) -> dict[str, object]:
    normalized = route_id if route_id in ROUTE_BY_ID else "unclassified"
    policy = _ROUTE_ORCHESTRATION.get(normalized, _DEFAULT_ORCHESTRATION)
    return {
        "parallelism_class": policy.parallelism_class,
        "authority_lane": policy.authority_lane,
        "exclusive_owner": policy.exclusive_owner,
        "claim_scope": list(policy.claim_scope),
        "claim_required": policy.claim_required,
        "merge_policy": policy.merge_policy,
        "fan_in_gate": list(policy.fan_in_gate),
        "max_parallelism_hint": policy.max_parallelism_hint,
        "stale_claim_policy": policy.stale_claim_policy,
        "conflict_policy": policy.conflict_policy,
    }


def route_protocol_for_id(route_id: str | None) -> dict[str, object]:
    normalized = route_id if route_id in ROUTE_BY_ID else "unclassified"
    gate_class = _ROUTE_GATE_CLASS.get(normalized, "none" if normalized != "unclassified" else "unknown")
    allowed_decisions = _ROUTE_ALLOWED_DECISIONS.get(normalized, ())
    requires_gate = bool(allowed_decisions)
    reason = (
        f"route {normalized} changes require an explicit reviewed decision or apply rail"
        if requires_gate
        else "route is read-only, advisory, generated, or does not carry authority by itself"
    )
    orchestration = route_orchestration_for_id(normalized)
    return {
        "route_id": normalized,
        "mutability": _ROUTE_MUTABILITY.get(normalized, "unknown"),
        "human_gate": {
            "required": requires_gate,
            "gate_class": gate_class,
            "reason": reason,
            "allowed_decisions": list(allowed_decisions),
        },
        "gate_class": gate_class,
        "human_gate_reason": reason,
        "allowed_decisions": list(allowed_decisions),
        "advisory": normalized not in {"state", "active-plan", "stable-specs", "closeout-writeback"},
        **orchestration,
    }


def route_manifest() -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for route in ROUTE_REGISTRY:
        protocol = route_protocol_for_id(route.route_id)
        orchestration = route_orchestration_for_id(route.route_id)
        rows.append(
            {
                "route_id": route.route_id,
                "target": route.target,
                "purpose": route.purpose,
                "start_path": route.start_path,
                "authority": route.authority,
                "mutability": protocol["mutability"],
                "human_gate": protocol["human_gate"],
                "gate_class": protocol["gate_class"],
                "human_gate_reason": protocol["human_gate_reason"],
                "allowed_decisions": protocol["allowed_decisions"],
                "advisory": protocol["advisory"],
                **orchestration,
            }
        )
    return tuple(rows)


def classify_intake_text(text: str) -> IntakeRouteAdvice:
    normalized = _normalized_intake_text(text)
    if not normalized:
        return AMBIGUOUS_INTAKE

    future_prompt_advice = _future_manual_deep_research_request_incubation_advice(normalized)
    if future_prompt_advice:
        return future_prompt_advice

    matches: list[tuple[int, int, str, tuple[str, ...]]] = []
    for index, (route_id, cues) in enumerate(INTAKE_ROUTE_CUES):
        matched = tuple(cue for cue in cues if cue in normalized)
        if matched:
            matches.append((len(matched), index, route_id, matched))

    if not matches:
        return AMBIGUOUS_INTAKE

    matches.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    top_count, _top_index, route_id, top_cues = matches[0]
    if len(matches) > 1 and matches[1][0] == top_count:
        return IntakeRouteAdvice(
            route_id="ambiguous",
            target="<manual-route-required>",
            confidence="none",
            reason=f"multiple route cues matched: {route_id}, {matches[1][2]}",
            next_action="choose the destination route explicitly before applying intake",
            apply_allowed=False,
        )

    route = ROUTE_BY_ID[route_id]
    confidence = "high" if top_count > 1 or any(cue.endswith(":") for cue in top_cues) else "medium"
    return IntakeRouteAdvice(
        route_id=route_id,
        target=route.target,
        confidence=confidence,
        reason=f"matched cue(s): {', '.join(top_cues)}",
        next_action=_intake_next_action(route_id),
        apply_allowed=True,
    )


def classify_intake_text_for_target(text: str, target: str) -> IntakeRouteAdvice:
    advice = classify_intake_text(text)
    if advice.apply_allowed or not target:
        return advice
    route_id = classify_memory_route(target).route_id
    if route_id not in INTAKE_ROUTE_ALLOWED_TARGETS:
        return advice
    normalized = _normalized_intake_text(text)
    matched = tuple(cue for cue in INTAKE_TARGET_GUIDED_CUES.get(route_id, ()) if cue in normalized)
    if not matched:
        return advice
    route = ROUTE_BY_ID[route_id]
    return IntakeRouteAdvice(
        route_id=route_id,
        target=route.target,
        confidence="medium",
        reason=f"target route {route_id!r} matched weak cue(s): {', '.join(matched)}",
        next_action=_intake_next_action(route_id),
        apply_allowed=True,
    )


def _future_manual_deep_research_request_incubation_advice(normalized: str) -> IntakeRouteAdvice | None:
    future_matches = tuple(cue for cue in FUTURE_FEATURE_INTAKE_CUES if cue in normalized)
    prompt_matches = tuple(cue for cue in DEEP_RESEARCH_PROMPT_COMPOSITION_INTAKE_CUES if cue in normalized)
    if not future_matches or not prompt_matches:
        return None
    route = ROUTE_BY_ID["incubation"]
    matched = ", ".join((*future_matches, *prompt_matches))
    return IntakeRouteAdvice(
        route_id="incubation",
        target=route.target,
        confidence="high",
        reason=f"matched future feature/Deep Research prompt-composition incubation cue(s): {matched}",
        next_action=_intake_next_action("incubation"),
        apply_allowed=True,
    )


def intake_target_matches_route(route_id: str, rel_path: str) -> bool:
    if route_id not in INTAKE_ROUTE_ALLOWED_TARGETS:
        return False
    return classify_memory_route(rel_path).route_id == route_id


def classify_memory_route(rel_path: str, role: str = "") -> MemoryRoute:
    normalized = rel_path.replace("\\", "/").strip("/")
    lowered = normalized.casefold()

    role_route_id = ROLE_TO_ROUTE_ID.get(role)
    if role_route_id:
        return ROUTE_BY_ID[role_route_id]

    exact = {
        ".agents/docmap.yaml": "docs-routing",
        ".mylittleharness/project-workflow.toml": "operating-guardrails",
        ".codex/project-workflow.toml": "operating-guardrails",
        "agents.md": "operating-guardrails",
        "readme.md": "orientation",
        "project/implementation-plan.md": "active-plan",
        "project/project-state.md": "state",
        "project/roadmap.md": "roadmap",
    }
    route_id = exact.get(lowered)
    if route_id:
        return ROUTE_BY_ID[route_id]

    prefixes = (
        ("docs/", "product-docs"),
        ("project/adrs/", "adrs"),
        ("project/archive/", "archive"),
        ("project/decisions/", "decisions"),
        ("project/plan-incubation/", "incubation"),
        ("project/research/", "research"),
        ("project/verification/agent-runs/", "agent-runs"),
        ("project/verification/work-claims/", "work-claims"),
        ("project/specs/", "stable-specs"),
        ("project/verification/", "verification"),
        ("specs/workflow/", "package-mirror"),
        (".mylittleharness/generated/", "generated-cache"),
    )
    for prefix, prefix_route_id in prefixes:
        if lowered.startswith(prefix):
            return ROUTE_BY_ID[prefix_route_id]
    return ROUTE_BY_ID["unclassified"]


def _normalized_intake_text(text: str) -> str:
    lowered = str(text or "").casefold()
    lowered = lowered.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", lowered).strip()


def _intake_next_action(route_id: str) -> str:
    actions = {
        "adrs": "draft a reviewed ADR under project/adrs/; intake never marks an architecture decision accepted by itself",
        "archive": "write under project/archive/reference/** only for explicit historical reference material",
        "decisions": "draft a reviewed decision record under project/decisions/; intake never marks rationale accepted by itself",
        "incubation": "use project/plan-incubation/*.md for future ideas that are not yet accepted work; safest write rail: `mylittleharness --root <root> incubate --dry-run --topic \"<topic>\" --note \"<note>\"` before the matching apply",
        "product-docs": "route docs impact to the relevant docs/**/*.md product contract or README surface",
        "research": "write imported or distilled research under project/research/*.md before promotion",
        "verification": "write durable proof under project/verification/*.md only when reusable evidence is worth the ceremony",
    }
    return actions.get(route_id, AMBIGUOUS_INTAKE.next_action)
