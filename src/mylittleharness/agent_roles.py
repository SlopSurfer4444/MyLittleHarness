from __future__ import annotations

from dataclasses import dataclass

from .routes import ROUTE_BY_ID, route_protocol_for_id


@dataclass(frozen=True)
class RolePermission:
    route_id: str
    read: bool = False
    propose: bool = False
    apply: bool = False
    requires_human_gate: bool = False

    def to_manifest(self) -> dict[str, object]:
        protocol = route_protocol_for_id(self.route_id)
        route_gate = dict(protocol["human_gate"])
        requires_gate = self.requires_human_gate or bool((self.propose or self.apply) and route_gate["required"])
        human_gate = {
            **route_gate,
            "required": requires_gate,
        }
        return {
            "route_id": str(protocol["route_id"]),
            "read": self.read,
            "propose": self.propose,
            "apply": self.apply,
            "requires_human_gate": requires_gate,
            "route_requires_human_gate": bool(route_gate["required"]),
            "gate_class": str(protocol["gate_class"]),
            "mutability": str(protocol["mutability"]),
            "allowed_decisions": list(protocol["allowed_decisions"]),
            "human_gate": human_gate,
            "advisory": True,
        }


@dataclass(frozen=True)
class RoleProfile:
    role_id: str
    title: str
    purpose: str
    default_inputs: tuple[str, ...]
    context_packet_requirements: tuple[str, ...]
    required_outputs: tuple[str, ...]
    output_packet_requirements: tuple[str, ...]
    permissions: tuple[RolePermission, ...]
    forbidden_actions: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    orchestration_role: str = "specialist"
    may_spawn_workers: bool = False
    worker_space_boundary: str = "assigned root and declared write scope only"
    isolation_contract: tuple[str, ...] = ()
    fan_in_output_required: tuple[str, ...] = ()
    work_claim_required: bool = False
    work_claim_contract: tuple[str, ...] = ()
    route_receipt_contract: tuple[str, ...] = ()
    fan_in_authority: str = "coordinator retains lifecycle authority; worker packets are evidence only"
    runtime_boundary: str = "protocol/report data only; no worker lifecycle writes, hidden daemons, or model calls"
    coordination_budget: str = "single assigned packet; no hidden retry loop"

    def to_manifest(self) -> dict[str, object]:
        permission_rows = tuple(permission.to_manifest() for permission in self.permissions)
        human_gates = tuple(
            {
                "route_id": permission["route_id"],
                "gate_class": permission["gate_class"],
                "reason": permission["human_gate"]["reason"],
                "allowed_decisions": permission["human_gate"]["allowed_decisions"],
            }
            for permission in permission_rows
            if permission["human_gate"]["required"]
        )
        return {
            "role_id": self.role_id,
            "title": self.title,
            "purpose": self.purpose,
            "default_inputs": list(self.default_inputs),
            "context_packet_requirements": list(self.context_packet_requirements),
            "required_outputs": list(self.required_outputs),
            "output_packet_requirements": list(self.output_packet_requirements),
            "permissions": list(permission_rows),
            "human_gates": list(human_gates),
            "forbidden_actions": list(self.forbidden_actions),
            "stop_conditions": list(self.stop_conditions),
            "orchestration_role": self.orchestration_role,
            "may_spawn_workers": self.may_spawn_workers,
            "worker_space_boundary": self.worker_space_boundary,
            "isolation_contract": list(self.isolation_contract),
            "fan_in_output_required": list(self.fan_in_output_required),
            "work_claim_required": self.work_claim_required,
            "work_claim_contract": list(self.work_claim_contract or COMMON_WORK_CLAIM_CONTRACT),
            "route_receipt_contract": list(self.route_receipt_contract or COMMON_ROUTE_RECEIPT_CONTRACT),
            "fan_in_authority": self.fan_in_authority,
            "runtime_boundary": self.runtime_boundary,
            "coordination_budget": self.coordination_budget,
            "authority_boundary": COMMON_ROLE_AUTHORITY_BOUNDARY,
            "apply_authority": any(permission.apply for permission in self.permissions),
            "advisory": True,
        }


COMMON_CONTEXT_PACKET = (
    "role_id",
    "task",
    "input_refs",
    "allowed_routes",
    "stop_conditions",
)
COMMON_OUTPUT_PACKET = (
    "status",
    "output_refs",
    "evidence",
    "residual_risk",
)
COMMON_FORBIDDEN_ACTIONS = (
    "approve lifecycle transitions",
    "archive plans",
    "stage, commit, push, or release",
    "bypass explicit dry-run/apply rails",
    "store hidden memory as authority",
)
COMMON_STOP_CONDITIONS = (
    "route authority is ambiguous",
    "requested write is outside the assigned scope",
    "verification is missing or failed",
    "human gate is required but no reviewed decision is present",
)
COMMON_ISOLATION_CONTRACT = (
    "operate only in the assigned root or isolated worker space",
    "respect declared allowed routes and write scope",
    "stop on overlapping claims, stale base revision, missing isolation, or merge conflict",
)
COMMON_FAN_IN_OUTPUT = (
    "changed_paths_or_output_refs",
    "commands_or_method",
    "deterministic_verification",
    "residual_risk",
)
COMMON_WORK_CLAIM_CONTRACT = (
    "claim_id",
    "run_id",
    "role_id",
    "owned_paths",
    "read_only_paths",
    "expires_at",
    "release_condition",
)
COMMON_ROUTE_RECEIPT_CONTRACT = (
    "route_receipt",
    "route_id",
    "decision",
    "dry_run_ref",
    "apply_ref_or_refusal",
    "source_hashes",
    "review_token_status",
    "boundary_statement",
)
COMMON_ROLE_AUTHORITY_BOUNDARY = (
    "role profiles describe permission, context, and output packet shape only; they do not encode domain reasoning "
    "authority or approve lifecycle decisions"
)
DISPATCHER_LAUNCH_REQUIRED_REFS = (
    "repo-visible handoff packet",
    "compatible active work claim",
    "planned or recorded agent-run evidence path",
)
DISPATCHER_LAUNCH_BOUNDARY = (
    "dispatcher launch is optional adapter work: it may start external worker work only after matching repo-visible "
    "handoff, claim, and evidence refs exist, and it cannot approve lifecycle, archive, Git, release, or fan-in decisions"
)


def _permissions(*rows: tuple[str, ...]) -> tuple[RolePermission, ...]:
    permissions: list[RolePermission] = []
    for row in rows:
        if not row or row[0] not in ROUTE_BY_ID:
            raise ValueError(f"unknown role permission route: {row[0] if row else '<missing>'}")
        actions = set(row[1:])
        permissions.append(
            RolePermission(
                row[0],
                read="read" in actions,
                propose="propose" in actions,
                apply="apply" in actions,
                requires_human_gate="gate" in actions,
            )
        )
    return tuple(permissions)


ROLE_PROFILES: tuple[RoleProfile, ...] = (
    RoleProfile(
        role_id="intake-clerk",
        title="Intake Clerk",
        purpose="Classify incoming information before it becomes operating-memory clutter.",
        default_inputs=("user_text", "route_manifest", "project_state"),
        context_packet_requirements=COMMON_CONTEXT_PACKET,
        required_outputs=("route_advice", "target_route_or_refusal", "source_text_summary"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("target_route",),
        permissions=_permissions(
            ("state", "read"),
            ("roadmap", "read"),
            ("incubation", "read", "propose"),
            ("research", "read", "propose"),
            ("verification", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS
        + (
            "accept specs",
            "open implementation plans",
            "mark roadmap items done",
        ),
        stop_conditions=COMMON_STOP_CONDITIONS + ("input matches multiple destination routes",),
        isolation_contract=COMMON_ISOLATION_CONTRACT,
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("target_route",),
    ),
    RoleProfile(
        role_id="researcher",
        title="Researcher",
        purpose="Gather and compress source-bound knowledge without making findings authoritative.",
        default_inputs=("intake_refs", "archive_refs", "source_refs"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("source_policy",),
        required_outputs=("research_distillate", "source_refs", "limits_and_uncertainties"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("citations",),
        permissions=_permissions(
            ("archive", "read"),
            ("incubation", "read"),
            ("research", "read", "propose"),
            ("product-docs", "read"),
            ("stable-specs", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("make research findings authoritative",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("source provenance cannot be preserved",),
        orchestration_role="read_only_worker",
        worker_space_boundary="read-only source/research packet; no lifecycle writes",
        isolation_contract=COMMON_ISOLATION_CONTRACT + ("preserve source provenance before fan-in",),
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("citations", "limits_and_uncertainties"),
        work_claim_required=True,
    ),
    RoleProfile(
        role_id="specifier",
        title="Specifier",
        purpose="Draft candidate contracts and amendments from accepted evidence for review.",
        default_inputs=("research_refs", "incubation_refs", "existing_specs", "decisions"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("contract_status",),
        required_outputs=("draft_spec_delta", "affected_contracts", "open_questions"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("contract_refs",),
        permissions=_permissions(
            ("research", "read"),
            ("incubation", "read"),
            ("stable-specs", "read", "propose"),
            ("decisions", "read", "propose"),
            ("adrs", "read", "propose"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("silently change accepted contracts",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("accepted contract status is unclear",),
        worker_space_boundary="draft contract packet only until reviewed by coordinator or human",
        isolation_contract=COMMON_ISOLATION_CONTRACT + ("do not rewrite accepted specs during parallel drafting",),
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("contract_refs", "open_questions"),
    ),
    RoleProfile(
        role_id="planner",
        title="Planner",
        purpose="Convert accepted intent into a bounded implementation-plan scaffold proposal.",
        default_inputs=("roadmap_item", "project_state", "related_specs", "product_target_context"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("execution_slice",),
        required_outputs=("plan_scaffold", "write_scope", "verification_gates", "stop_conditions"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("active_plan_ref",),
        permissions=_permissions(
            ("state", "read"),
            ("roadmap", "read", "propose"),
            ("active-plan", "read", "propose"),
            ("stable-specs", "read"),
            ("product-docs", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS
        + (
            "edit product code",
            "approve closeout",
        ),
        stop_conditions=COMMON_STOP_CONDITIONS + ("requested slice cannot be bounded",),
        orchestration_role="coordinator",
        worker_space_boundary="main operating root plan proposal lane; one active plan at a time",
        isolation_contract=COMMON_ISOLATION_CONTRACT + ("plan one execution slice without spawning workers",),
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("active_plan_ref", "write_scope"),
        coordination_budget="one active implementation plan; fan-in requires repo-visible evidence before lifecycle writeback",
    ),
    RoleProfile(
        role_id="coder",
        title="Coder",
        purpose="Implement bounded source changes inside the declared write scope.",
        default_inputs=("active_plan", "target_artifacts", "adjacent_tests", "related_specs"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("write_scope",),
        required_outputs=("patch_summary", "changed_paths", "test_plan", "residual_risk"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("changed_paths",),
        permissions=_permissions(
            ("active-plan", "read"),
            ("stable-specs", "read"),
            ("product-docs", "read", "propose"),
            ("unclassified", "read", "propose"),
            ("verification", "read", "propose"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS
        + (
            "change lifecycle state",
            "spawn workers without an explicit handoff contract",
            "rewrite accepted specs as part of implementation",
        ),
        stop_conditions=COMMON_STOP_CONDITIONS + ("source reality invalidates the active write scope",),
        orchestration_role="worker",
        worker_space_boundary="assigned source write scope or isolated worker space only; no shared lifecycle authority",
        isolation_contract=COMMON_ISOLATION_CONTRACT
        + (
            "hold an explicit handoff or claim before parallel source edits",
            "return patch evidence instead of writing lifecycle routes",
        ),
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("changed_paths", "cleanup_status"),
        work_claim_required=True,
    ),
    RoleProfile(
        role_id="reviewer",
        title="Reviewer",
        purpose="Identify defects, scope drift, and missing proof without approving release alone.",
        default_inputs=("patch", "active_plan", "spec_refs", "test_results"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("review_scope",),
        required_outputs=("findings", "severity", "requested_changes", "test_gaps"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("review_findings",),
        permissions=_permissions(
            ("active-plan", "read"),
            ("stable-specs", "read"),
            ("product-docs", "read"),
            ("verification", "read", "propose"),
            ("unclassified", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("approve release alone",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("patch scope cannot be matched to the plan",),
        orchestration_role="read_only_worker",
        worker_space_boundary="review packet only; may not fan in or approve lifecycle",
        isolation_contract=COMMON_ISOLATION_CONTRACT + ("review from source refs and supplied diff only",),
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("review_findings",),
        work_claim_required=True,
    ),
    RoleProfile(
        role_id="verifier",
        title="Verifier",
        purpose="Prove behavior with deterministic commands and source-bound evidence.",
        default_inputs=("active_plan", "commands", "changed_paths"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("verification_gate",),
        required_outputs=("command_results", "verdict", "skips", "evidence_refs"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("commands", "verdict"),
        permissions=_permissions(
            ("active-plan", "read"),
            ("stable-specs", "read"),
            ("verification", "read", "propose"),
            ("unclassified", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("change scope or product promises",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("deterministic success signal is missing",),
        orchestration_role="worker",
        worker_space_boundary="verification lane only; may record evidence proposals but not lifecycle decisions",
        isolation_contract=COMMON_ISOLATION_CONTRACT + ("commands must be deterministic and named before fan-in",),
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("commands", "verdict"),
        work_claim_required=True,
    ),
    RoleProfile(
        role_id="devops-sandbox-operator",
        title="DevOps/Sandbox Operator",
        purpose="Run approved commands and isolate tools while preserving host and secret boundaries.",
        default_inputs=("active_plan", "command_policy", "environment_contract"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("command_allowlist",),
        required_outputs=("command_results", "artifacts", "environment_notes"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("commands", "artifacts"),
        permissions=_permissions(
            ("active-plan", "read"),
            ("operating-guardrails", "read"),
            ("verification", "read", "propose"),
            ("generated-cache", "read", "propose"),
            ("unclassified", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS
        + (
            "expose secrets",
            "mutate workstation state without an adoption contract",
            "decide architecture",
        ),
        stop_conditions=COMMON_STOP_CONDITIONS + ("command requires destructive or sensitive host access",),
        orchestration_role="worker",
        worker_space_boundary="approved command sandbox only; no workstation adoption or secret ownership",
        isolation_contract=COMMON_ISOLATION_CONTRACT + ("name environment, ports, databases, and cleanup before use",),
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("artifacts", "environment_notes", "cleanup_status"),
        work_claim_required=True,
    ),
    RoleProfile(
        role_id="reconciler",
        title="Reconciler",
        purpose="Compare intended contracts with observed code and evidence, then propose drift-handling candidates.",
        default_inputs=("spec_refs", "code_refs", "evidence_refs", "diff"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("drift_basis",),
        required_outputs=("drift_record", "classification", "proposal", "affected_authority"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("drift_refs",),
        permissions=_permissions(
            ("stable-specs", "read", "propose"),
            ("decisions", "read", "propose"),
            ("incubation", "read", "propose"),
            ("verification", "read"),
            ("unclassified", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("silently normalize authority to implementation",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("contract and implementation cannot be compared from source refs",),
        orchestration_role="coordinator",
        worker_space_boundary="drift proposal lane only; no accepted truth rewrite during fan-in",
        isolation_contract=COMMON_ISOLATION_CONTRACT + ("classify drift before proposing any mutation",),
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("drift_refs", "classification"),
    ),
    RoleProfile(
        role_id="archivist",
        title="Archivist",
        purpose="Move cold memory out of active lanes while keeping provenance recoverable.",
        default_inputs=("terminal_artifacts", "source_links", "coverage_evidence"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("archive_boundary",),
        required_outputs=("archive_plan", "link_repairs", "provenance_summary"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("archive_refs",),
        permissions=_permissions(
            ("state", "read"),
            ("active-plan", "read"),
            ("archive", "read", "propose"),
            ("incubation", "read", "propose"),
            ("research", "read", "propose"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("delete unresolved provenance",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("entry coverage is incomplete",),
        orchestration_role="coordinator",
        worker_space_boundary="archive proposal lane; one archive transaction at a time",
        isolation_contract=COMMON_ISOLATION_CONTRACT + ("coverage evidence must exist before archive fan-in",),
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("archive_refs", "provenance_summary"),
        coordination_budget="single archive transaction; unresolved coverage stays active",
    ),
    RoleProfile(
        role_id="governor",
        title="Governor",
        purpose="Represent deterministic MLH state-machine law and bounded apply rails.",
        default_inputs=("reviewed_request", "repo_visible_state", "route_protocol", "review_token"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("review_token", "source_hashes"),
        required_outputs=("dry_run_report", "apply_report_or_refusal", "route_write_evidence"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("review_token_status",),
        permissions=_permissions(
            ("state", "read", "propose"),
            ("active-plan", "read", "propose"),
            ("roadmap", "read", "propose"),
            ("closeout-writeback", "read", "propose"),
            ("archive", "read", "propose"),
            ("stable-specs", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS
        + (
            "hallucinate route writes",
            "bypass review tokens",
            "depend on hidden memory",
        ),
        stop_conditions=COMMON_STOP_CONDITIONS + ("review token or source hash has drifted",),
        orchestration_role="coordinator",
        worker_space_boundary="main operating root lifecycle coordinator only",
        isolation_contract=COMMON_ISOLATION_CONTRACT
        + (
            "one reviewed dry-run/apply transition at a time",
            "workers return evidence packets rather than lifecycle writes",
        ),
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("review_token_status", "route_write_evidence"),
        fan_in_authority="governor/coordinator retains lifecycle authority; route receipts and review tokens are evidence only",
        runtime_boundary="protocol/report data only; no worker lifecycle writes, hidden daemons, model calls, or provider gateway",
        coordination_budget="single lifecycle coordinator; fan-in requires evidence packet and matching review token",
    ),
    RoleProfile(
        role_id="dispatcher",
        title="Dispatcher",
        purpose="Prepare optional worker launch from repo-visible handoff, claim, and evidence records.",
        default_inputs=("handoff_packet", "work_claim", "agent_run_evidence_path", "worktree_coordination_root"),
        context_packet_requirements=COMMON_CONTEXT_PACKET
        + (
            "handoff_ref",
            "claim_ref",
            "agent_run_evidence_ref",
            "worktree_coordination_root",
        ),
        required_outputs=("launch_refusal_or_command_packet", "handoff_ref", "claim_ref", "evidence_ref", "boundary_statement"),
        output_packet_requirements=COMMON_OUTPUT_PACKET
        + (
            "handoff_ref",
            "claim_ref",
            "evidence_ref",
            "launch_boundary",
        ),
        permissions=_permissions(
            ("active-plan", "read"),
            ("verification", "read"),
            ("stable-specs", "read"),
            ("product-docs", "read"),
            ("unclassified", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS
        + (
            "start work without a repo-visible handoff packet, compatible active claim, and planned evidence path",
            "store queue, daemon, provider, or runtime cache state as authority",
            "grant fan-in or lifecycle authority to launched workers",
        ),
        stop_conditions=COMMON_STOP_CONDITIONS
        + (
            "handoff packet is missing or malformed",
            "claim is missing, stale, released, conflicted, or outside the handoff scope",
            "agent-run evidence path is missing from the handoff packet or outside the agent-run evidence route",
        ),
        orchestration_role="dispatcher",
        may_spawn_workers=True,
        worker_space_boundary="external worker launch only after handoff, active claim, and planned evidence path are repo-visible",
        isolation_contract=COMMON_ISOLATION_CONTRACT
        + (
            "dispatcher launch readiness is derived from repo-visible packet refs only",
            "runtime queue/cache state is disposable and cannot replace handoff, claim, or evidence refs",
        ),
        fan_in_output_required=COMMON_FAN_IN_OUTPUT + ("handoff_ref", "claim_ref", "evidence_ref", "launch_boundary"),
        work_claim_required=True,
        work_claim_contract=COMMON_WORK_CLAIM_CONTRACT + ("coordination_root", "edit_worktree_root"),
        fan_in_authority="dispatcher launch packets are evidence only; coordinator/governor retains lifecycle and fan-in authority",
        runtime_boundary=DISPATCHER_LAUNCH_BOUNDARY,
        coordination_budget="one reviewed handoff at a time; no hidden queue authority or autonomous retry loop",
    ),
)
ROLE_PROFILE_BY_ID = {profile.role_id: profile for profile in ROLE_PROFILES}


def role_manifest() -> tuple[dict[str, object], ...]:
    return tuple(profile.to_manifest() for profile in ROLE_PROFILES)


def role_profile_for_id(role_id: str) -> RoleProfile | None:
    return ROLE_PROFILE_BY_ID.get(role_id)


def roles_with_apply_authority() -> tuple[str, ...]:
    return tuple(profile.role_id for profile in ROLE_PROFILES if any(permission.apply for permission in profile.permissions))


def dispatcher_launch_contract() -> dict[str, object]:
    return {
        "required_refs": list(DISPATCHER_LAUNCH_REQUIRED_REFS),
        "authority_boundary": DISPATCHER_LAUNCH_BOUNDARY,
        "advisory": True,
    }
