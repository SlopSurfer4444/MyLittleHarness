from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .command_discovery import rails_not_cognition_boundary_finding
from .inventory import Inventory, Surface
from .models import Finding
from .evidence_cues import CLOSEOUT_FIELD_NAMES, closeout_field_cues, cue_findings, find_cues
from .parsing import Frontmatter, parse_frontmatter
from .root_boundary import (
    PRODUCT_SOURCE_REF_PREFIX,
    product_source_ref_rel as shared_product_source_ref_rel,
    product_source_ref_target as shared_product_source_ref_target,
    product_source_root_from_state as shared_product_source_root_from_state,
    record_id_conflict,
    root_relative_path_conflict,
    source_path_boundary_violation,
)
from .writeback import (
    WritebackFact,
    acceptance_evidence_findings,
    current_state_writeback_facts,
    satisfied_post_archive_carry_forward_finding,
    state_writeback_facts,
)


ANCHOR_PATTERNS = (
    ("plan", (r"\bplan anchors?\b", r"\bplan\b.*\banchors?\b")),
    ("integration", (r"\bintegration anchors?\b", r"\bintegration\b.*\banchors?\b")),
    ("closeout", (r"\bcloseout anchors?\b", r"\bcloseout\b.*\banchors?\b")),
)

CARRY_FORWARD_PATTERNS = (
    r"carry-forward",
    r"deferred",
    r"unresolved",
    r"optional-next",
    r"later-extension",
    r"needs-more-research",
    r"\bopen questions?\b",
)
GIT_CONTEXT_TRAILERS = (
    ("MLH-Plan", ("plan_id",)),
    ("MLH-Phase", ("active_phase",)),
    ("MLH-Slice", ("execution_slice", "primary_roadmap_item", "related_roadmap_item")),
)
SKIP_RATIONALE_PATTERNS = (
    r"skip rationale",
    r"explicit skip",
    r"verified skip",
    r"explicitly skipped",
    r"skipped because",
)
DURABLE_PROOF_RECORD_PREFIX = "project/verification/"
DURABLE_PROOF_RECORD_LIMIT = 5
AGENT_RUNS_DIR_REL = "project/verification/agent-runs"
AGENT_RUN_RECORD_PREFIX = f"{AGENT_RUNS_DIR_REL}/"
AGENT_RUN_RETIREMENT_SUMMARY_REL = "project/verification/agent-run-retirement-summary.md"
AGENT_RUN_SCHEMA = "mylittleharness.agent-run.v1"
AGENT_RUN_SOURCE_HASH_SUMMARY_THRESHOLD = 8
AGENT_RUN_SOURCE_HASH_SUMMARY_SAMPLE_LIMIT = 4
WORKER_RUN_RECEIPTS_DIR_REL = "project/verification/worker-run-receipts"
WORKER_RUN_RECEIPT_SCHEMA = "mylittleharness.worker-run-receipt.v1"
WORKER_RUN_RECEIPT_REFRESH_TOKEN_PREFIX = "wrr-"
EVIDENCE_REF_RETARGET_TOKEN_PREFIX = "eret-"
QUEUE_RUNNER_FIXTURES_DIR_REL = "project/verification/queue-runner-fixtures"
QUEUE_RUNNER_FIXTURE_UPDATE_TOKEN_PREFIX = "qfix-"
CHECKPOINT_PACKAGE_RECEIPTS_DIR_REL = "project/verification/checkpoint-packages"
CHECKPOINT_PACKAGE_RECEIPT_SCHEMA = "mylittleharness.checkpoint-package-receipt.v1"
RUNTIME_GUARD_PREFLIGHT_RECEIPT_SCHEMA = "mylittleharness.runtime-guard-preflight-receipt.v1"
CHECKPOINT_RESUME_RECEIPT_SCHEMA = "mylittleharness.checkpoint-resume-receipt.v1"
CHILD_AGENT_FANOUT_RECEIPT_SCHEMA = "mylittleharness.child-agent-fanout-receipt.v1"
CAPABILITY_FENCE_DECISION_RECEIPT_SCHEMA = "mylittleharness.capability-fence-decision-receipt.v1"
RUNTIME_BROKER_PROVIDER_RECEIPT_SCHEMA = "mylittleharness.runtime-broker-provider-receipt.v1"
ARTIFACT_LINEAGE_RECEIPT_SCHEMA = "mylittleharness.artifact-lineage-receipt.v1"
WORKER_WORKTREE_SESSION_RECEIPT_SCHEMA = "mylittleharness.worker-worktree-session-receipt.v1"
RUNTIME_STATE_NAMESPACE_ID = "runtime_state_namespace.v1"
COORDINATION_RECORD_DIRS = (
    "project/verification/work-claims",
    "project/verification/handoffs",
    "project/verification/session-active-work",
    WORKER_RUN_RECEIPTS_DIR_REL,
    CHECKPOINT_PACKAGE_RECEIPTS_DIR_REL,
)
EVIDENCE_REF_RETARGET_JSON_TARGET_PREFIXES = (
    "project/verification/handoffs/",
    "project/verification/work-claims/",
    WORKER_RUN_RECEIPTS_DIR_REL + "/",
)
EVIDENCE_REF_RETARGET_AGENT_RUN_FIELDS = (
    "input_refs",
    "output_refs",
    "claimed_paths",
    "changed_files",
    "verification_refs",
    "handoff_refs",
    "claim_refs",
)
EVIDENCE_REF_RETARGET_JSON_REF_KEYS = frozenset(
    {
        "approval_packet_refs",
        "claim_refs",
        "claimed_paths",
        "decision_refs",
        "evidence_refs",
        "included_paths",
        "input_refs",
        "missing_anchor_refs",
        "output_refs",
        "receipt_refs",
        "repo_visible_refs",
        "required_outputs",
        "route_anchor_refs",
        "source_hashes",
        "task_input_refs",
        "verification_refs",
        "write_scope",
    }
)
AGENT_RUN_REQUIRED_SCALARS = (
    "schema",
    "record_type",
    "record_id",
    "role",
    "actor",
    "task",
    "assigned_scope",
    "runtime",
    "worktree_id",
    "status",
    "stop_reason",
    "attempt_budget",
    "docs_decision",
    "residual_risk",
)
AGENT_RUN_REQUIRED_LISTS = ("input_refs", "output_refs", "claimed_paths", "changed_files", "commands", "verification_refs", "source_hashes")
AGENT_RUN_STATUSES = {
    "succeeded",
    "failed",
    "blocked",
    "skipped",
    "needs-refinement",
    "needs-human-review",
}
AGENT_RUN_DOCS_DECISIONS = {"updated", "not-needed", "uncertain"}
CHECKPOINT_PACKAGE_RECEIPT_REQUIRED_SCALARS = (
    "schema",
    "record_type",
    "package_id",
    "target_root",
    "package_class",
    "verdict",
    "non_authority",
    "docs_decision",
    "residual_risk",
)
CHECKPOINT_PACKAGE_RECEIPT_REQUIRED_LISTS = (
    "included_paths",
    "verification_refs",
    "source_hashes",
)
CHECKPOINT_PACKAGE_RECEIPT_PACKAGE_CLASSES = {
    "post-closeout-route-package",
    "deferred-research-archive-package",
    "worker-run-receipt-refs",
    "verification-decision-evidence-package",
    "memory-hygiene-archive-reference-package",
    "meta-feedback-package",
    "agent-run-evidence",
    "initial-scaffold-package",
    "other-reviewed",
    "unknown",
}
CHECKPOINT_PACKAGE_RECEIPT_VERDICTS = {"allowed", "blocked", "unknown"}
CHECKPOINT_PACKAGE_RECEIPT_EXACT_REF_FIELDS = (
    "included_paths",
    "skipped_paths",
)
CHECKPOINT_PACKAGE_RECEIPT_REF_FIELDS = (
    *CHECKPOINT_PACKAGE_RECEIPT_EXACT_REF_FIELDS,
    "verification_refs",
    "evidence_refs",
    "decision_refs",
    "route_anchor_refs",
    "receipt_refs",
    "missing_anchor_refs",
)
CHECKPOINT_PACKAGE_RECEIPT_PROHIBITED_INCLUDED_PREFIXES = (
    ".git/",
    ".mylittleharness/generated/",
    ".mylittleharness/runtime/",
    "project/cache/",
    "project/generated/",
    "project/private/",
    "project/scratch/",
    "project/secrets/",
    "project/temp/",
    "project/tmp/",
)
WORKER_RUN_RECEIPT_REQUIRED_SCALARS = (
    "schema",
    "record_type",
    "receipt_id",
    "launch_id",
    "worker_id",
    "role",
    "target_root",
    "runtime_namespace",
    "worker_status",
    "non_authority",
)
WORKER_RUN_RECEIPT_REQUIRED_LISTS = (
    "task_input_refs",
    "event_stream_refs",
    "output_refs",
    "verification_refs",
    "source_hashes",
)
WORKER_RUN_RECEIPT_WORKER_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "blocked",
    "cancelled",
    "timed-out",
    "skipped",
    "needs-human-review",
}
WORKER_RUN_RECEIPT_RUNTIME_STATUSES = {
    "not-started",
    "starting",
    "running",
    "exited",
    "failed",
    "cancelled",
    "unknown",
}
WORKER_RUN_RECEIPT_WORKFLOW_STATUSES = {
    "queued",
    "ready",
    "in-progress",
    "blocked",
    "succeeded",
    "failed",
    "cancelled",
    "waiting-for-review",
    "unknown",
}
WORKER_RUN_RECEIPT_VERIFICATION_VERDICTS = {
    "not-run",
    "passed",
    "failed",
    "blocked",
    "skipped",
    "inconclusive",
}
WORKER_RUN_RECEIPT_LIFECYCLE_STATUSES = {
    "none",
    "pending",
    "active",
    "in-progress",
    "ready-for-closeout",
    "complete",
    "archived",
    "blocked",
}
WORKER_RUN_RECEIPT_RESEARCH_IMPORT_STATUSES = {
    "not-imported",
    "candidate",
    "imported",
    "distilled",
    "compared",
    "insufficient",
    "uncertain",
}
WORKER_RUN_RECEIPT_FORBIDDEN_WORKER_STATUS_TERMS = {
    "accepted",
    "active",
    "approved",
    "archived",
    "complete",
    "done",
    "passed",
    "roadmap-done",
}
WORKER_RUN_RECEIPT_FALSE_AUTHORITY_FIELDS = (
    "approves_lifecycle",
    "approves_archive",
    "approves_roadmap_status",
    "approves_git",
    "approves_provider_routing",
    "approves_release",
    "lifecycle_accepted",
    "approves_closeout",
    "approves_cleanup",
    "approves_fan_in",
    "approves_launch",
    "approves_worker_launch",
    "approves_route_proposal",
    "approves_target_repo_acceptance",
    "private_trace_authoritative",
    "private_traces_authoritative",
    "sdk_trace_authoritative",
    "trace_approves_lifecycle",
    "event_history_approves_lifecycle",
    "event_stream_approves_lifecycle",
    "launch_approved",
    "launch_authorized",
    "worker_launch_approved",
    "provider_routing_approved",
    "route_proposal_accepted",
    "target_repo_accepted",
    "dirty_worktree_approved",
    "bypass_approved",
    "native_hook_authoritative",
    "provider_proof_authoritative",
    "fallback_hook_proof_authoritative",
    "checkpoint_authoritative",
    "checkpoint_approves_lifecycle",
    "checkpoint_approves_launch",
    "resume_approves_lifecycle",
    "resume_authorized",
    "replay_approves_lifecycle",
    "replay_approves_verification",
    "queue_success_approves_lifecycle",
    "run_completion_approves_lifecycle",
    "backpressure_approves_lifecycle",
    "backpressure_verdict_authoritative",
    "approves_verification",
    "verification_accepted",
    "capability_fence_authoritative",
    "capability_fence_approves_lifecycle",
    "capability_fence_approves_launch",
    "capability_fence_approves_fan_in",
    "capability_fence_approves_verification",
    "capability_fence_approves_provider_routing",
    "tool_authorization_approved",
    "tool_authorization_authoritative",
    "tool_authorization_approves_lifecycle",
    "tool_authorization_approves_launch",
    "tool_authorization_approves_fan_in",
    "tool_authorization_approves_verification",
    "tool_authorization_approves_provider_routing",
    "broker_dispatch_approved",
    "broker_dispatch_authoritative",
    "broker_dispatch_approves_lifecycle",
    "broker_dispatch_approves_launch",
    "broker_dispatch_approves_provider_routing",
    "provider_routing_authoritative",
    "provider_routing_approves_lifecycle",
    "workspace_mount_authoritative",
    "workspace_mount_approves_lifecycle",
    "workspace_mount_approves_target_repo_acceptance",
    "workspace_cleanup_authorized",
    "workspace_cleanup_approved",
    "credential_projection_approved",
    "credential_projection_authoritative",
    "credential_projection_approves_lifecycle",
    "telemetry_authoritative",
    "telemetry_approves_lifecycle",
    "worktree_session_authoritative",
    "worktree_session_approves_lifecycle",
    "worktree_session_approves_launch",
    "worktree_session_approves_cleanup",
    "worktree_session_approves_verification",
    "worktree_session_approves_target_repo_acceptance",
    "terminal_pane_authoritative",
    "terminal_capture_approves_lifecycle",
    "status_dashboard_authoritative",
    "status_dashboard_approves_lifecycle",
    "wait_success_approves_lifecycle",
    "sandbox_authoritative",
    "sandbox_approves_lifecycle",
    "sandbox_approves_launch",
    "merge_success_approves_lifecycle",
    "merge_success_approves_target_repo_acceptance",
    "cleanup_success_approves_lifecycle",
    "cleanup_success_approves_git",
    "artifact_lineage_authoritative",
    "artifact_lineage_approves_lifecycle",
    "artifact_lineage_approves_verification",
    "artifact_lineage_approves_target_repo_acceptance",
    "artifact_acceptance_authorized",
    "artifact_accepted",
    "lineage_verification_approved",
    "lineage_verification_authoritative",
    "lineage_verification_approves_lifecycle",
    "signature_authoritative",
    "signature_approves_lifecycle",
    "hmac_authoritative",
    "hmac_approves_lifecycle",
)
CHECKPOINT_PACKAGE_RECEIPT_FALSE_AUTHORITY_FIELDS = WORKER_RUN_RECEIPT_FALSE_AUTHORITY_FIELDS + (
    "approves_checkpoint",
    "approves_local_checkpoint",
    "approves_staging",
    "approves_commit",
    "staging_approved",
    "staging_authorized",
    "commit_approved",
    "commit_authorized",
    "checkpoint_package_authoritative",
    "checkpoint_package_approves_lifecycle",
    "checkpoint_package_approves_git",
    "checkpoint_package_approves_commit",
    "checkpoint_package_approves_staging",
    "package_checkpoint_approves_lifecycle",
    "package_approves_lifecycle",
    "package_approves_archive",
    "package_approves_commit",
    "package_approves_staging",
    "local_checkpoint_approved",
    "local_checkpoint_authorized",
)
WORKER_RUN_RECEIPT_EVENT_HISTORY_REDACTION_STATUSES = {
    "none",
    "redacted",
    "summarized",
    "private-traces-excluded",
    "not-recorded",
    "unknown",
}
WORKER_RUN_RECEIPT_PRIVATE_TRACE_NON_AUTHORITY_TOKENS = (
    "cannot",
    "does not",
    "not authority",
    "non-authority",
    "non-authoritative",
    "evidence-only",
    "evidence only",
    "excluded",
)
WORKER_RUN_RECEIPT_PRIVATE_TRACE_SOURCE_TOKENS = (
    "private trace",
    "private sdk trace",
    "sdk trace",
    "runtime trace",
    "telemetry",
)
WORKER_RUN_RECEIPT_PRIVATE_TRACE_CONTEXT_KEYS = {
    "raw",
    "raw_payload",
    "raw_provider_payload",
    "raw_request_payload",
    "raw_response_payload",
    "request_payload",
    "response_payload",
    "request_body",
    "response_body",
    "provider_payload",
    "provider_request",
    "provider_response",
    "provider_request_payload",
    "provider_response_payload",
    "sdk_trace",
    "sdk_traces",
    "trace_payload",
    "private_trace_payload",
}
WORKER_RUN_RECEIPT_PRIVATE_TRACE_PAYLOAD_KEYS = {
    "messages",
    "message",
    "tool_calls",
    "input_text",
    "output_text",
    "choices",
    "delta",
    "content",
    "arguments",
    "function_call",
}
WORKER_RUN_RECEIPT_PRIVATE_TRACE_FALSE_KEYS = {
    "raw_payload_persisted",
    "raw_provider_payload_persisted",
    "raw_secret_material_persisted",
    "secret_material_persisted",
    "private_trace_authoritative",
    "private_traces_authoritative",
    "private_persistence_enabled",
    "persist_private_traces",
}
WORKER_RUN_RECEIPT_PRIVATE_TRACE_SENSITIVE_KEYS = {
    "authorization",
    "proxy_authorization",
    "x_api_key",
    "api_key",
    "openai_api_key",
    "azure_openai_api_key",
    "github_token",
    "cookie",
    "set_cookie",
    "secret",
    "access_token",
    "refresh_token",
    "bearer_token",
}
WORKER_RUN_RECEIPT_EVENT_HISTORY_AUTHORITY_VERBS = (
    "approve",
    "approves",
    "approved",
    "accept",
    "accepts",
    "accepted",
    "authorize",
    "authorizes",
    "authorized",
    "mark",
    "marks",
    "marked",
    "move",
    "moves",
    "moved",
)
WORKER_RUN_RECEIPT_EVENT_HISTORY_AUTHORITY_TARGETS = (
    "lifecycle",
    "archive",
    "roadmap",
    "git",
    "provider",
    "verification",
    "release",
    "cleanup",
    "closeout",
    "fan-in",
    "staging",
    "commit",
    "push",
    "launch",
    "worker launch",
    "broker",
    "workspace",
    "credential",
    "telemetry",
    "worktree",
    "terminal",
    "pane",
    "dashboard",
    "wait",
    "sandbox",
    "merge",
    "artifact",
    "artifact lineage",
    "lineage",
    "hash chain",
    "signature",
    "hmac",
    "route proposal",
    "target-repo",
    "target repo",
    "acceptance",
)
WORKER_RUN_RECEIPT_EVENT_HISTORY_NEGATION_TOKENS = (
    "cannot approve",
    "cannot accept",
    "cannot authorize",
    "does not approve",
    "does not accept",
    "does not authorize",
    "must not approve",
    "must not accept",
    "not approve",
    "not accept",
    "not authority",
    "non-authority",
    "non-authoritative",
    "evidence only",
    "evidence-only",
)
WORKER_RUN_RECEIPT_RUNTIME_GUARD_STATUSES = {
    "not-run",
    "passed",
    "failed",
    "blocked",
    "skipped",
    "unknown",
}
WORKER_RUN_RECEIPT_RUNTIME_GUARD_READINESS = {
    "not-ready",
    "ready",
    "blocked",
    "degraded",
    "unknown",
}
WORKER_RUN_RECEIPT_RUNTIME_GUARD_REPLAY_STATUSES = {
    "not-recorded",
    "not-required",
    "replayed",
    "stale",
    "blocked",
    "unknown",
}
WORKER_RUN_RECEIPT_RUNTIME_GUARD_WORKTREE_STATUSES = {
    "clean",
    "dirty-reviewed",
    "dirty-unreviewed",
    "unknown",
}
WORKER_RUN_RECEIPT_RUNTIME_GUARD_HOOK_PROOF_LEVELS = {
    "native",
    "fallback",
    "synthetic",
    "not-recorded",
    "unknown",
}
WORKER_RUN_RECEIPT_RUNTIME_GUARD_PROVIDER_PROOF_LEVELS = {
    "not-configured",
    "env-present",
    "configured",
    "provider-called",
    "not-recorded",
    "unknown",
}
WORKER_RUN_RECEIPT_RUNTIME_GUARD_REF_FIELDS = (
    "dispatch_refs",
    "mailbox_refs",
    "worktree_refs",
    "runtime_readiness_refs",
    "hook_proof_refs",
    "provider_proof_refs",
    "leader_lifecycle_refs",
)
WORKER_RUN_RECEIPT_RUNTIME_GUARD_CONTAINERS = (
    "unsafe_bypass",
    "worktree",
    "hook_proof",
    "provider_proof",
)
WORKER_RUN_RECEIPT_CHECKPOINT_STATUSES = {
    "not-required",
    "created",
    "failed",
    "blocked",
    "not-supported",
    "unknown",
}
WORKER_RUN_RECEIPT_CHECKPOINT_KINDS = {
    "compute",
    "message-snapshot",
    "event-tail",
    "object-snapshot",
    "mixed",
    "none",
    "unknown",
}
WORKER_RUN_RECEIPT_RESUME_STATUSES = {
    "not-required",
    "required",
    "resumed",
    "blocked",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_RESTORE_STRATEGIES = {
    "none",
    "checkpoint-restore",
    "snapshot-tail-replay",
    "event-tail-replay",
    "customer-hydrated",
    "manual",
    "unknown",
}
WORKER_RUN_RECEIPT_CHECKPOINT_FAILURE_STATUSES = {
    "none",
    "in-progress",
    "failed",
    "retrying",
    "exhausted",
    "unknown",
}
WORKER_RUN_RECEIPT_IDEMPOTENCY_POSTURES = {
    "not-recorded",
    "present",
    "reused",
    "collision-detected",
    "unknown",
}
WORKER_RUN_RECEIPT_BACKPRESSURE_MODES = {
    "off",
    "shadow",
    "dry-run",
    "enforced",
    "unknown",
}
WORKER_RUN_RECEIPT_BACKPRESSURE_VERDICTS = {
    "not-checked",
    "allow",
    "throttle",
    "block",
    "fail-open",
    "fail-closed",
    "unknown",
}
WORKER_RUN_RECEIPT_BACKPRESSURE_STALE_POSTURES = {
    "not-stale",
    "stale-fail-open",
    "stale-fail-closed",
    "stale-block",
    "unknown",
}
WORKER_RUN_RECEIPT_BACKPRESSURE_FAILURE_POSTURES = {
    "none",
    "fail-open",
    "fail-closed",
    "block",
    "unknown",
}
WORKER_RUN_RECEIPT_CHECKPOINT_RESUME_REF_FIELDS = (
    "durable_task_run_refs",
    "event_readback_refs",
    "checkpoint_refs",
    "resume_message_refs",
    "replay_refs",
    "backpressure_verdict_refs",
    "snapshot_refs",
)
WORKER_RUN_RECEIPT_CHILD_FANOUT_STATUSES = {
    "planned",
    "launched",
    "running",
    "completed",
    "failed",
    "blocked",
    "skipped",
    "unknown",
}
WORKER_RUN_RECEIPT_CHILD_FANOUT_REF_FIELDS = (
    "coordination_refs",
    "dispatch_refs",
    "mailbox_refs",
    "handoff_refs",
    "work_claim_refs",
    "route_receipt_refs",
    "fan_in_refs",
)
WORKER_RUN_RECEIPT_CHILD_FANOUT_CHILD_REF_FIELDS = (
    "task_refs",
    "prompt_refs",
    "output_refs",
    "event_history_refs",
    "verification_refs",
)
WORKER_RUN_RECEIPT_CHILD_FANOUT_RUNTIME_REF_FIELDS = (
    "runtime_readiness_refs",
    "worktree_refs",
    "hook_proof_refs",
    "provider_proof_refs",
    "bypass_refs",
)
WORKER_RUN_RECEIPT_CAPABILITY_FENCE_STATUSES = {
    "not-evaluated",
    "allow",
    "partial-allow",
    "deny",
    "blocked",
    "requires-approval",
    "unknown",
}
WORKER_RUN_RECEIPT_CAPABILITY_FENCE_APPROVAL_STATES = {
    "not-required",
    "requested",
    "pending",
    "granted",
    "denied",
    "expired",
    "unknown",
}
WORKER_RUN_RECEIPT_CAPABILITY_FENCE_AUDIT_STATUSES = {
    "not-recorded",
    "recorded",
    "verified",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_CAPABILITY_FENCE_REF_FIELDS = (
    "policy_refs",
    "role_profile_refs",
    "tool_manifest_refs",
    "task_session_refs",
    "claim_refs",
    "handoff_refs",
    "runtime_guard_refs",
    "provider_posture_refs",
    "approval_refs",
    "audit_refs",
    "mcp_gateway_refs",
)
WORKER_RUN_RECEIPT_CAPABILITY_FENCE_CAPABILITY_LIST_FIELDS = (
    "requested_capabilities",
    "allowed_capabilities",
    "denied_capabilities",
    "restricted_routes",
    "forbidden_routes",
)
WORKER_RUN_RECEIPT_RUNTIME_BROKER_STATUSES = {
    "not-configured",
    "registering",
    "registered",
    "joined",
    "running",
    "withdrawn",
    "orphaned",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_RUNTIME_PROVIDER_STATUSES = {
    "not-configured",
    "available",
    "default",
    "disabled",
    "withdrawn",
    "degraded",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_BROKER_REGISTRATION_STATUSES = {
    "not-started",
    "started",
    "verified",
    "joined",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_BROKER_SERVER_STATUSES = {
    "not-started",
    "running",
    "stopped",
    "unreachable",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_BROKER_DISPATCH_STATUSES = {
    "not-requested",
    "eligible",
    "dispatched",
    "blocked",
    "withdrawn",
    "orphaned",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_WORKSPACE_ISOLATION_STATUSES = {
    "not-recorded",
    "shared",
    "isolated",
    "clone-per-agent",
    "worktree-per-agent",
    "fallback",
    "unavailable",
    "unknown",
}
WORKER_RUN_RECEIPT_WORKSPACE_CLEANUP_STATUSES = {
    "not-requested",
    "guarded",
    "completed",
    "blocked",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_CREDENTIAL_PROJECTION_STATUSES = {
    "not-requested",
    "scoped",
    "projected",
    "blocked",
    "missing",
    "redacted",
    "unknown",
}
WORKER_RUN_RECEIPT_APPROVAL_MODES = {
    "manual-required",
    "auto-proposed",
    "full-auto-observed",
    "disabled",
    "unknown",
}
WORKER_RUN_RECEIPT_TELEMETRY_STATUSES = {
    "not-recorded",
    "local-only",
    "exported",
    "redacted",
    "disabled",
    "unknown",
}
WORKER_RUN_RECEIPT_RUNTIME_BROKER_PROVIDER_REF_FIELDS = (
    "broker_refs",
    "provider_refs",
    "workspace_refs",
    "mount_refs",
    "path_guard_refs",
    "cleanup_refs",
    "credential_refs",
    "token_refs",
    "approval_refs",
    "resume_refs",
    "telemetry_refs",
    "event_refs",
)
WORKER_RUN_RECEIPT_RUNTIME_BROKER_PROVIDER_CONTAINERS = (
    "broker",
    "provider",
    "workspace",
    "credentials",
    "cleanup",
    "resume",
    "telemetry",
)
WORKER_RUN_RECEIPT_ARTIFACT_LINEAGE_STATUSES = {
    "not-recorded",
    "recorded",
    "verified",
    "failed",
    "partial",
    "unknown",
}
WORKER_RUN_RECEIPT_ARTIFACT_HASH_STATUSES = {
    "not-recorded",
    "recorded",
    "verified",
    "mismatch",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_ARTIFACT_SIGNATURE_STATUSES = {
    "not-required",
    "not-recorded",
    "recorded",
    "verified",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_ARTIFACT_LINEAGE_VERIFICATION_STATUSES = {
    "not-run",
    "passed",
    "failed",
    "blocked",
    "partial",
    "unknown",
}
WORKER_RUN_RECEIPT_ARTIFACT_LINEAGE_REF_FIELDS = (
    "output_refs",
    "input_refs",
    "parent_refs",
    "prompt_refs",
    "verification_refs",
    "signature_refs",
    "lineage_refs",
    "audit_refs",
)
WORKER_RUN_RECEIPT_ARTIFACT_LINEAGE_CONTAINERS = (
    "hash_chain",
    "signature",
    "hmac",
    "producer",
    "verification",
)
WORKER_RUN_RECEIPT_WORKTREE_SESSION_STATUSES = {
    "not-recorded",
    "planned",
    "prepared",
    "launched",
    "running",
    "captured",
    "closed",
    "cleaned-up",
    "failed",
    "blocked",
    "stale",
    "unknown",
}
WORKER_RUN_RECEIPT_WORKTREE_SESSION_WORKTREE_STATUSES = {
    "not-recorded",
    "clean",
    "dirty-reviewed",
    "dirty-unreviewed",
    "missing",
    "removed",
    "unknown",
}
WORKER_RUN_RECEIPT_WORKTREE_SESSION_PROMPT_STATUSES = {
    "not-recorded",
    "rendered",
    "written",
    "injected",
    "consumed",
    "file-only",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_WORKTREE_SESSION_CAPTURE_STATUSES = {
    "not-recorded",
    "captured",
    "partial",
    "failed",
    "stale",
    "unknown",
}
WORKER_RUN_RECEIPT_WORKTREE_SESSION_SANDBOX_STATUSES = {
    "not-recorded",
    "validated",
    "enforced",
    "degraded",
    "bypassed",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_WORKTREE_SESSION_MERGE_CLEANUP_STATUSES = {
    "not-requested",
    "guarded",
    "completed",
    "blocked",
    "failed",
    "unknown",
}
WORKER_RUN_RECEIPT_WORKTREE_SESSION_CONCURRENCY_STATUSES = {
    "not-recorded",
    "bounded",
    "unbounded",
    "waiting",
    "throttled",
    "complete",
    "unknown",
}
WORKER_RUN_RECEIPT_WORKTREE_SESSION_WAIT_STATUSES = {
    "not-required",
    "waiting",
    "completed",
    "timed-out",
    "agent-disappeared",
    "worktree-removed-after-merge",
    "unknown",
}
WORKER_RUN_RECEIPT_WORKTREE_SESSION_REF_FIELDS = (
    "worktree_refs",
    "branch_refs",
    "prompt_refs",
    "prompt_file_refs",
    "status_refs",
    "capture_refs",
    "session_refs",
    "sandbox_refs",
    "merge_refs",
    "cleanup_refs",
    "wait_refs",
    "concurrency_refs",
    "dashboard_refs",
)
WORKER_RUN_RECEIPT_WORKTREE_SESSION_CONTAINERS = (
    "worktree",
    "prompt",
    "session",
    "status_capture",
    "sandbox",
    "merge_cleanup",
    "concurrency",
)
AGENT_RUN_ROUTE_PROPOSAL_FIELDS = ("route_proposals", "recommended_next_routes", "recommended_next_route")
ROUTE_PROPOSAL_FORBIDDEN_TERMS = {
    "--apply",
    "--model",
    "--model-id",
    "--provider",
    "apply",
    "archive",
    "commit",
    "git",
    "launch",
    "model",
    "provider",
    "push",
    "roadmap",
    "stage",
    "staging",
    "worker",
    "writeback",
}
RECORD_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SOURCE_HASH_RE = re.compile(r"^(.+?)\s+(?:sha256=([a-fA-F0-9]{64})|(missing)|(unreadable)|(invalid-path))$")


@dataclass(frozen=True)
class AgentRunRecordRequest:
    record_id: str
    role: str
    actor: str
    task: str
    assigned_scope: str
    runtime: str
    worktree_id: str
    status: str
    stop_reason: str
    attempt_budget: str
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]
    claimed_paths: tuple[str, ...]
    changed_files: tuple[str, ...]
    commands: tuple[str, ...]
    verification_refs: tuple[str, ...]
    docs_decision: str
    residual_risk: str
    handoff_refs: tuple[str, ...]
    claim_refs: tuple[str, ...]
    repeated_failure_signature: str
    provider: str
    model_id: str
    tools: tuple[str, ...]


@dataclass(frozen=True)
class AgentRunRecordRefreshPlan:
    rel_path: str
    current_text: str
    updated_text: str
    source_hashes: tuple[str, ...]
    refreshed_ref_fields: tuple[str, ...]


@dataclass(frozen=True)
class WorkerRunReceiptRefreshRequest:
    target: str
    proposal_token: str


@dataclass(frozen=True)
class WorkerRunReceiptRefreshPlan:
    rel_path: str
    current_text: str
    updated_text: str
    source_hashes: tuple[str, ...]
    current_receipt_hash: str
    proposal_token: str


@dataclass(frozen=True)
class EvidenceRefRetargetRequest:
    target: str
    old_ref: str
    new_ref: str
    proposal_token: str


@dataclass(frozen=True)
class EvidenceRefRetargetPlan:
    rel_path: str
    current_text: str
    updated_text: str
    replacement_count: int
    source_hashes: tuple[str, ...]
    current_target_hash: str
    proposal_token: str
    target_kind: str


@dataclass(frozen=True)
class QueueRunnerFixtureUpdateRequest:
    target: str
    text: str
    text_source: str
    proposal_token: str


@dataclass(frozen=True)
class QueueRunnerFixtureUpdatePlan:
    rel_path: str
    current_text: str
    updated_text: str
    current_target_hash: str
    proposal_token: str


def make_agent_run_record_request(args: object) -> AgentRunRecordRequest:
    return AgentRunRecordRequest(
        record_id=str(getattr(args, "record_id", "") or "").strip(),
        role=str(getattr(args, "agent_role", "") or "").strip(),
        actor=str(getattr(args, "actor", "") or "").strip(),
        task=str(getattr(args, "task", "") or "").strip(),
        assigned_scope=str(getattr(args, "assigned_scope", "") or "").strip(),
        runtime=str(getattr(args, "runtime", "") or "").strip(),
        worktree_id=str(getattr(args, "worktree_id", "") or "").strip(),
        status=str(getattr(args, "status", "") or "").strip(),
        stop_reason=str(getattr(args, "stop_reason", "") or "").strip(),
        attempt_budget=str(getattr(args, "attempt_budget", "") or "").strip(),
        input_refs=_tuple_values(getattr(args, "input_refs", ())),
        output_refs=_tuple_values(getattr(args, "output_refs", ())),
        claimed_paths=_tuple_values(getattr(args, "claimed_paths", ())),
        changed_files=_tuple_values(getattr(args, "changed_files", ())),
        commands=_tuple_values(getattr(args, "commands", ())),
        verification_refs=_tuple_values(getattr(args, "verification_refs", ())),
        docs_decision=str(getattr(args, "docs_decision", "") or "").strip(),
        residual_risk=str(getattr(args, "residual_risk", "") or "").strip(),
        handoff_refs=_tuple_values(getattr(args, "handoff_refs", ())),
        claim_refs=_tuple_values(getattr(args, "claim_refs", ())),
        repeated_failure_signature=str(getattr(args, "repeated_failure_signature", "") or "").strip(),
        provider=str(getattr(args, "provider", "") or "").strip(),
        model_id=str(getattr(args, "model_id", "") or "").strip(),
        tools=_tuple_values(getattr(args, "tools", ())),
    )


def make_worker_run_receipt_refresh_request(args: object) -> WorkerRunReceiptRefreshRequest:
    return WorkerRunReceiptRefreshRequest(
        target=str(getattr(args, "receipt_target", "") or "").replace("\\", "/").strip(),
        proposal_token=str(getattr(args, "proposal_token", "") or "").strip(),
    )


def make_evidence_ref_retarget_request(args: object) -> EvidenceRefRetargetRequest:
    return EvidenceRefRetargetRequest(
        target=str(getattr(args, "receipt_target", "") or "").replace("\\", "/").strip(),
        old_ref=str(getattr(args, "old_ref", "") or "").replace("\\", "/").strip(),
        new_ref=str(getattr(args, "new_ref", "") or "").replace("\\", "/").strip(),
        proposal_token=str(getattr(args, "proposal_token", "") or "").strip(),
    )


def make_queue_runner_fixture_update_request(args: object, text: str, text_source: str) -> QueueRunnerFixtureUpdateRequest:
    return QueueRunnerFixtureUpdateRequest(
        target=str(getattr(args, "receipt_target", "") or "").replace("\\", "/").strip(),
        text=text,
        text_source=text_source,
        proposal_token=str(getattr(args, "proposal_token", "") or "").strip(),
    )


def agent_run_record_dry_run_findings(inventory: Inventory, request: AgentRunRecordRequest) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "agent-run-record-dry-run", "agent run evidence record proposal only; no files were written"),
        Finding("info", "agent-run-record-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _agent_run_request_findings(inventory, request, apply=False)
    findings.extend(request_findings)
    if any(finding.severity in {"warn", "error"} and finding.code == "agent-run-record-refused" for finding in request_findings):
        findings.append(Finding("info", "agent-run-record-validation-posture", "dry-run refused before apply; fix explicit record fields before writing evidence"))
        findings.extend(_agent_run_record_boundary_findings())
        return findings

    target_rel = _agent_run_record_target_rel(request)
    target = inventory.root / target_rel
    if target.exists() and target.is_file():
        refresh_plan, refresh_findings = _agent_run_record_refresh_plan(inventory.root, target_rel, severity="warn", request=request)
        findings.extend(refresh_findings)
        if refresh_plan is None:
            findings.append(Finding("info", "agent-run-record-validation-posture", "dry-run refused before apply; fix the existing agent run evidence record before refreshing source hashes"))
            findings.extend(_agent_run_record_boundary_findings())
            return findings
        findings.extend(_agent_run_record_refresh_route_findings(refresh_plan, apply=False))
        findings.extend(_agent_run_record_boundary_findings())
        return findings

    text, hash_findings = _render_agent_run_record(inventory.root, request)
    findings.extend(hash_findings)
    findings.extend(
        [
            Finding("info", "agent-run-record-target", f"would write agent run record: {target_rel}", target_rel),
            Finding(
                "info",
                "agent-run-record-route-write",
                f"would create route {target_rel}; before_hash=missing; after_hash={_short_hash(text)}; before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; source-bound write evidence is independent of Git tracking",
                target_rel,
            ),
        ]
    )
    findings.extend(_agent_run_record_boundary_findings())
    return findings


def agent_run_record_apply_findings(inventory: Inventory, request: AgentRunRecordRequest) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "agent-run-record-apply", "agent run evidence record apply started"),
        Finding("info", "agent-run-record-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _agent_run_request_findings(inventory, request, apply=True)
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "agent-run-record-validation-posture", "apply refused before writing evidence"))
        findings.extend(_agent_run_record_boundary_findings())
        return findings

    target_rel = _agent_run_record_target_rel(request)
    target = inventory.root / target_rel
    if target.exists() and target.is_file():
        refresh_plan, refresh_findings = _agent_run_record_refresh_plan(inventory.root, target_rel, severity="error", request=request)
        findings.extend(refresh_findings)
        if refresh_plan is None:
            findings.append(Finding("info", "agent-run-record-validation-posture", "apply refused before refreshing evidence"))
            findings.extend(_agent_run_record_boundary_findings())
            return findings
        if refresh_plan.current_text == refresh_plan.updated_text:
            findings.append(Finding("info", "agent-run-record-refresh-current", "agent run evidence record source hashes are already current; no route write was needed", target_rel))
            findings.extend(_agent_run_record_boundary_findings())
            return findings
        tmp_path = target.with_name(f".{target.name}.tmp")
        backup_path = target.with_name(f".{target.name}.bak")
        try:
            cleanup_warnings = apply_file_transaction(
                (AtomicFileWrite(target, tmp_path, refresh_plan.updated_text, backup_path),),
                root=inventory.root,
            )
        except FileTransactionError as exc:
            findings.append(Finding("error", "agent-run-record-refused", f"failed to refresh agent run record before apply completed: {exc}", target_rel))
            findings.extend(_agent_run_record_boundary_findings())
            return findings
        findings.extend(_agent_run_record_refresh_route_findings(refresh_plan, apply=True))
        for warning in cleanup_warnings:
            findings.append(Finding("warn", "agent-run-record-backup-cleanup", warning, target_rel))
        findings.extend(_agent_run_record_boundary_findings())
        return findings

    text, hash_findings = _render_agent_run_record(inventory.root, request)
    findings.extend(hash_findings)
    tmp_path = target.with_name(f".{target.name}.tmp")
    backup_path = target.with_name(f".{target.name}.bak")
    try:
        cleanup_warnings = apply_file_transaction(
            (AtomicFileWrite(target, tmp_path, text, backup_path),),
            root=inventory.root,
        )
    except FileTransactionError as exc:
        findings.append(Finding("error", "agent-run-record-refused", f"failed to write agent run record before apply completed: {exc}", target_rel))
        findings.extend(_agent_run_record_boundary_findings())
        return findings

    findings.extend(
        [
            Finding("info", "agent-run-record-written", f"created agent run evidence record: {target_rel}", target_rel),
            Finding(
                "info",
                "agent-run-record-route-write",
                f"created route {target_rel}; before_hash=missing; after_hash={_short_hash(text)}; before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; source-bound write evidence is independent of Git tracking",
                target_rel,
            ),
        ]
    )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "agent-run-record-backup-cleanup", warning, target_rel))
    findings.extend(_agent_run_record_boundary_findings())
    return findings


def worker_run_receipt_refresh_dry_run_findings(inventory: Inventory, request: WorkerRunReceiptRefreshRequest) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "worker-run-receipt-refresh-dry-run", "worker run receipt source-hash refresh proposal only; no files were written"),
        Finding("info", "worker-run-receipt-refresh-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _worker_run_receipt_refresh_request_findings(inventory, request, severity="warn")
    findings.extend(request_findings)
    if any(finding.severity in {"warn", "error"} for finding in request_findings):
        findings.append(Finding("info", "worker-run-receipt-refresh-validation-posture", "dry-run refused before apply; fix the receipt target before refreshing source_hashes"))
        findings.extend(_worker_run_receipt_refresh_boundary_findings())
        return findings

    plan, plan_findings = _worker_run_receipt_refresh_plan(inventory.root, request.target, severity="warn")
    findings.extend(plan_findings)
    if plan is None:
        findings.append(Finding("info", "worker-run-receipt-refresh-validation-posture", "dry-run refused before apply; fix the existing worker run receipt before refreshing source_hashes"))
        findings.extend(_worker_run_receipt_refresh_boundary_findings())
        return findings

    findings.extend(_worker_run_receipt_refresh_route_findings(plan, apply=False))
    findings.extend(_worker_run_receipt_refresh_boundary_findings())
    return findings


def worker_run_receipt_refresh_apply_findings(inventory: Inventory, request: WorkerRunReceiptRefreshRequest) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "worker-run-receipt-refresh-apply", "worker run receipt source-hash refresh apply started"),
        Finding("info", "worker-run-receipt-refresh-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _worker_run_receipt_refresh_request_findings(inventory, request, severity="error")
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "worker-run-receipt-refresh-validation-posture", "apply refused before refreshing receipt source_hashes"))
        findings.extend(_worker_run_receipt_refresh_boundary_findings())
        return findings

    plan, plan_findings = _worker_run_receipt_refresh_plan(inventory.root, request.target, severity="error")
    findings.extend(plan_findings)
    if plan is None:
        findings.append(Finding("info", "worker-run-receipt-refresh-validation-posture", "apply refused before refreshing receipt source_hashes"))
        findings.extend(_worker_run_receipt_refresh_boundary_findings())
        return findings
    if not request.proposal_token:
        findings.append(
            Finding(
                "error",
                "worker-run-receipt-refresh-refused",
                f"apply requires --proposal-token {plan.proposal_token} from a matching dry-run",
                plan.rel_path,
            )
        )
        findings.extend(_worker_run_receipt_refresh_boundary_findings())
        return findings
    if request.proposal_token != plan.proposal_token:
        findings.append(
            Finding(
                "error",
                "worker-run-receipt-refresh-refused",
                "proposal token mismatch; rerun evidence --receipt-refresh --dry-run because the receipt or its source refs changed",
                plan.rel_path,
            )
        )
        findings.extend(_worker_run_receipt_refresh_boundary_findings())
        return findings
    if plan.current_text == plan.updated_text:
        findings.extend(_worker_run_receipt_refresh_route_findings(plan, apply=True))
        findings.extend(_worker_run_receipt_refresh_boundary_findings())
        return findings

    target = inventory.root / plan.rel_path
    tmp_path = target.with_name(f".{target.name}.tmp")
    backup_path = target.with_name(f".{target.name}.bak")
    try:
        cleanup_warnings = apply_file_transaction(
            (AtomicFileWrite(target, tmp_path, plan.updated_text, backup_path),),
            root=inventory.root,
        )
    except FileTransactionError as exc:
        findings.append(Finding("error", "worker-run-receipt-refresh-refused", f"failed to refresh worker run receipt before apply completed: {exc}", plan.rel_path))
        findings.extend(_worker_run_receipt_refresh_boundary_findings())
        return findings
    findings.extend(_worker_run_receipt_refresh_route_findings(plan, apply=True))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "worker-run-receipt-refresh-backup-cleanup", warning, plan.rel_path))
    findings.extend(_worker_run_receipt_refresh_boundary_findings())
    return findings


def evidence_ref_retarget_dry_run_findings(inventory: Inventory, request: EvidenceRefRetargetRequest) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "evidence-ref-retarget-dry-run", "evidence reference retarget proposal only; no files were written"),
        Finding("info", "evidence-ref-retarget-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _evidence_ref_retarget_request_findings(inventory, request, severity="warn")
    findings.extend(request_findings)
    if any(finding.severity in {"warn", "error"} for finding in request_findings):
        findings.append(Finding("info", "evidence-ref-retarget-validation-posture", "dry-run refused before apply; fix the target and refs before retargeting evidence"))
        findings.extend(_evidence_ref_retarget_boundary_findings())
        return findings

    plan, plan_findings = _evidence_ref_retarget_plan(inventory.root, request, severity="warn")
    findings.extend(plan_findings)
    if plan is None:
        findings.append(Finding("info", "evidence-ref-retarget-validation-posture", "dry-run refused before apply; fix the existing route-owned evidence record before retargeting refs"))
        findings.extend(_evidence_ref_retarget_boundary_findings())
        return findings

    findings.extend(_evidence_ref_retarget_route_findings(plan, request, apply=False))
    findings.extend(_evidence_ref_retarget_boundary_findings())
    return findings


def evidence_ref_retarget_apply_findings(inventory: Inventory, request: EvidenceRefRetargetRequest) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "evidence-ref-retarget-apply", "evidence reference retarget apply started"),
        Finding("info", "evidence-ref-retarget-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _evidence_ref_retarget_request_findings(inventory, request, severity="error")
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "evidence-ref-retarget-validation-posture", "apply refused before retargeting evidence refs"))
        findings.extend(_evidence_ref_retarget_boundary_findings())
        return findings

    plan, plan_findings = _evidence_ref_retarget_plan(inventory.root, request, severity="error")
    findings.extend(plan_findings)
    if plan is None:
        findings.append(Finding("info", "evidence-ref-retarget-validation-posture", "apply refused before retargeting evidence refs"))
        findings.extend(_evidence_ref_retarget_boundary_findings())
        return findings
    if not request.proposal_token:
        findings.append(
            Finding(
                "error",
                "evidence-ref-retarget-refused",
                f"apply requires --proposal-token {plan.proposal_token} from a matching dry-run",
                plan.rel_path,
            )
        )
        findings.extend(_evidence_ref_retarget_boundary_findings())
        return findings
    if request.proposal_token != plan.proposal_token:
        findings.append(
            Finding(
                "error",
                "evidence-ref-retarget-refused",
                "proposal token mismatch; rerun evidence --retarget-ref --dry-run because the target or referenced files changed",
                plan.rel_path,
            )
        )
        findings.extend(_evidence_ref_retarget_boundary_findings())
        return findings
    if plan.current_text == plan.updated_text:
        findings.extend(_evidence_ref_retarget_route_findings(plan, request, apply=True))
        findings.extend(_evidence_ref_retarget_boundary_findings())
        return findings

    target = inventory.root / plan.rel_path
    tmp_path = target.with_name(f".{target.name}.tmp")
    backup_path = target.with_name(f".{target.name}.bak")
    try:
        cleanup_warnings = apply_file_transaction(
            (AtomicFileWrite(target, tmp_path, plan.updated_text, backup_path),),
            root=inventory.root,
        )
    except FileTransactionError as exc:
        findings.append(Finding("error", "evidence-ref-retarget-refused", f"failed to retarget evidence refs before apply completed: {exc}", plan.rel_path))
        findings.extend(_evidence_ref_retarget_boundary_findings())
        return findings
    findings.extend(_evidence_ref_retarget_route_findings(plan, request, apply=True))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "evidence-ref-retarget-backup-cleanup", warning, plan.rel_path))
    findings.extend(_evidence_ref_retarget_boundary_findings())
    return findings


def queue_runner_fixture_update_dry_run_findings(inventory: Inventory, request: QueueRunnerFixtureUpdateRequest) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "queue-runner-fixture-update-dry-run", "queue-runner fixture update proposal only; no files were written"),
        Finding("info", "queue-runner-fixture-update-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _queue_runner_fixture_update_request_findings(inventory, request, severity="warn")
    findings.extend(request_findings)
    if any(finding.severity in {"warn", "error"} for finding in request_findings):
        findings.append(Finding("info", "queue-runner-fixture-update-validation-posture", "dry-run refused before apply; fix the target and reviewed fixture text before updating route-owned evidence"))
        findings.extend(_queue_runner_fixture_update_boundary_findings())
        return findings

    plan, plan_findings = _queue_runner_fixture_update_plan(inventory.root, request, severity="warn")
    findings.extend(plan_findings)
    if plan is None:
        findings.append(Finding("info", "queue-runner-fixture-update-validation-posture", "dry-run refused before apply; fix the existing route-owned queue-runner fixture"))
        findings.extend(_queue_runner_fixture_update_boundary_findings())
        return findings
    findings.extend(_queue_runner_fixture_update_route_findings(plan, apply=False))
    findings.extend(_queue_runner_fixture_update_boundary_findings())
    return findings


def queue_runner_fixture_update_apply_findings(inventory: Inventory, request: QueueRunnerFixtureUpdateRequest) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "queue-runner-fixture-update-apply", "queue-runner fixture update apply started"),
        Finding("info", "queue-runner-fixture-update-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _queue_runner_fixture_update_request_findings(inventory, request, severity="error")
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "queue-runner-fixture-update-validation-posture", "apply refused before updating queue-runner fixture evidence"))
        findings.extend(_queue_runner_fixture_update_boundary_findings())
        return findings

    plan, plan_findings = _queue_runner_fixture_update_plan(inventory.root, request, severity="error")
    findings.extend(plan_findings)
    if plan is None:
        findings.append(Finding("info", "queue-runner-fixture-update-validation-posture", "apply refused before updating queue-runner fixture evidence"))
        findings.extend(_queue_runner_fixture_update_boundary_findings())
        return findings
    if not request.proposal_token:
        findings.append(
            Finding(
                "error",
                "queue-runner-fixture-update-refused",
                f"apply requires --proposal-token {plan.proposal_token} from a matching dry-run",
                plan.rel_path,
            )
        )
        findings.extend(_queue_runner_fixture_update_boundary_findings())
        return findings
    if request.proposal_token != plan.proposal_token:
        findings.append(
            Finding(
                "error",
                "queue-runner-fixture-update-refused",
                "proposal token mismatch; rerun evidence --fixture-update --dry-run because the target fixture or reviewed text changed",
                plan.rel_path,
            )
        )
        findings.extend(_queue_runner_fixture_update_boundary_findings())
        return findings
    if plan.current_text == plan.updated_text:
        findings.extend(_queue_runner_fixture_update_route_findings(plan, apply=True))
        findings.extend(_queue_runner_fixture_update_boundary_findings())
        return findings

    target = inventory.root / plan.rel_path
    tmp_path = target.with_name(f".{target.name}.tmp")
    backup_path = target.with_name(f".{target.name}.bak")
    try:
        cleanup_warnings = apply_file_transaction(
            (AtomicFileWrite(target, tmp_path, plan.updated_text, backup_path),),
            root=inventory.root,
        )
    except FileTransactionError as exc:
        findings.append(Finding("error", "queue-runner-fixture-update-refused", f"failed to update queue-runner fixture before apply completed: {exc}", plan.rel_path))
        findings.extend(_queue_runner_fixture_update_boundary_findings())
        return findings
    findings.extend(_queue_runner_fixture_update_route_findings(plan, apply=True))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "queue-runner-fixture-update-backup-cleanup", warning, plan.rel_path))
    findings.extend(_queue_runner_fixture_update_boundary_findings())
    return findings


def agent_run_record_findings(inventory: Inventory, code_prefix: str = "agent-run") -> list[Finding]:
    code = f"{code_prefix}-record"
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "info",
                code,
                "agent run record scan is live-root only; product fixtures and archive roots remain non-authority context",
                inventory.state.rel_path if inventory.state and inventory.state.exists else None,
            )
        ]

    paths = _agent_run_record_paths(inventory.root)
    if not paths:
        return [
            Finding(
                "info",
                code,
                "no agent run evidence records found at project/verification/agent-runs/*.md; records are optional evidence and absence does not block closeout",
            ),
            *_agent_run_record_boundary_findings(code_prefix),
        ]

    retired_records, retirement_findings = agent_run_retired_records(inventory.root, code_prefix)
    findings: list[Finding] = [*retirement_findings]
    for path in paths:
        rel_path = _to_rel_path(inventory.root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code}-malformed", "agent run record path is not a regular file", rel_path))
            continue
        if rel_path in retired_records:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            findings.append(Finding("warn", f"{code}-malformed", f"agent run record could not be read: {exc}", rel_path))
            continue
        frontmatter = parse_frontmatter(text)
        data = frontmatter.data
        record_id = str(data.get("record_id") or "").strip() or "<missing>"
        role = str(data.get("role") or "").strip() or "<missing>"
        status = str(data.get("status") or "").strip() or "<missing>"
        findings.append(
            Finding(
                "info",
                code,
                f"candidate: agent run record: {rel_path}; record_id={record_id}; role={role}; status={status}; read-only evidence input only",
                rel_path,
            )
        )
        metadata_findings = _agent_run_record_metadata_findings(rel_path, frontmatter, data, code_prefix)
        findings.extend(metadata_findings)
        if any(finding.severity == "warn" for finding in metadata_findings):
            findings.append(agent_run_record_template_finding(rel_path, code_prefix))
        findings.extend(
            _agent_run_source_hash_findings(
                inventory.root,
                rel_path,
                data,
                code_prefix,
                check_freshness=rel_path not in retired_records,
            )
        )
        findings.extend(_agent_run_route_proposal_findings(rel_path, data, code_prefix))

    findings = _summarize_agent_run_source_hash_findings(findings, code_prefix)
    findings.extend(_agent_run_record_boundary_findings(code_prefix))
    return findings


def agent_run_record_template_finding(rel_path: str, code_prefix: str = "agent-run") -> Finding:
    record_id = Path(rel_path).stem or "run-id"
    handoff_ref = f"project/verification/handoffs/{record_id}.md"
    example = (
        "minimal valid agent-run frontmatter example: --- | "
        f"schema: \"{AGENT_RUN_SCHEMA}\" | record_type: \"agent-run\" | record_id: \"{record_id}\" | "
        "role: \"reviewer\" | actor: \"codex\" | task: \"review evidence\" | assigned_scope: \"current slice\" | "
        "runtime: \"local-shell\" | worktree_id: \"main\" | status: \"succeeded\" | "
        "stop_reason: \"verification-passed\" | attempt_budget: \"1/1\" | docs_decision: \"not-needed\" | "
        f"residual_risk: \"none\" | input_refs: [\"project/implementation-plan.md\"] | output_refs: [\"{handoff_ref}\"] | "
        f"claimed_paths: [\"{handoff_ref}\"] | changed_files: [\"{handoff_ref}\"] | "
        f"commands: [\"mylittleharness --root <root> check\"] | verification_refs: [\"{handoff_ref}\"] | "
        f"source_hashes: [\"{handoff_ref} missing\"] | ---; scaffold with "
        "`mylittleharness --root <root> evidence --record --dry-run ...`"
    )
    return Finding("info", f"{code_prefix}-record-template", example, rel_path)


def worker_run_receipt_findings(inventory: Inventory, code_prefix: str = "worker-run-receipt") -> list[Finding]:
    code = f"{code_prefix}-record"
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "info",
                code,
                "worker run receipt scan is live-root only; product fixtures and archive roots remain non-authority context",
                inventory.state.rel_path if inventory.state and inventory.state.exists else None,
            )
        ]

    paths = _worker_run_receipt_paths(inventory.root)
    if not paths:
        return [
            Finding(
                "info",
                code,
                "no worker run receipts found at project/verification/worker-run-receipts/*.json; receipts are optional evidence until a worker launch exists",
            ),
            *_worker_run_receipt_boundary_findings(code_prefix),
        ]

    findings: list[Finding] = []
    for path in paths:
        rel_path = _to_rel_path(inventory.root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code}-malformed", "worker run receipt path is not a regular file", rel_path))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", f"{code}-malformed", f"worker run receipt could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", f"{code}-malformed", "worker run receipt JSON root must be an object", rel_path))
            continue

        receipt_id = str(data.get("receipt_id") or "").strip() or "<missing>"
        launch_id = str(data.get("launch_id") or "").strip() or "<missing>"
        worker_id = str(data.get("worker_id") or "").strip() or "<missing>"
        worker_status = str(data.get("worker_status") or "").strip() or "<missing>"
        findings.append(
            Finding(
                "info",
                code,
                (
                    f"candidate: worker run receipt: {rel_path}; receipt_id={receipt_id}; "
                    f"launch_id={launch_id}; worker_id={worker_id}; worker_status={worker_status}; "
                    "repo-visible evidence input only"
                ),
                rel_path,
            )
        )
        findings.extend(_worker_run_receipt_metadata_findings(inventory.root, rel_path, path.stem, data, code_prefix))
        findings.extend(_worker_run_receipt_source_hash_findings(inventory.root, rel_path, data, code_prefix))

    findings.extend(_worker_run_receipt_boundary_findings(code_prefix))
    return findings


def checkpoint_package_receipt_findings(inventory: Inventory, code_prefix: str = "checkpoint-package-receipt") -> list[Finding]:
    code = f"{code_prefix}-record"
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "info",
                code,
                "checkpoint package receipt scan is live-root only; product fixtures and archive roots remain non-authority context",
                inventory.state.rel_path if inventory.state and inventory.state.exists else None,
            )
        ]

    paths = _checkpoint_package_receipt_paths(inventory.root)
    if not paths:
        return [
            Finding(
                "info",
                code,
                "no checkpoint package receipts found at project/verification/checkpoint-packages/*.json; receipts are optional evidence until a checkpoint package report exists",
            ),
            *_checkpoint_package_receipt_boundary_findings(code_prefix),
        ]

    findings: list[Finding] = []
    for path in paths:
        rel_path = _to_rel_path(inventory.root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code}-malformed", "checkpoint package receipt path is not a regular file", rel_path))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", f"{code}-malformed", f"checkpoint package receipt could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", f"{code}-malformed", "checkpoint package receipt JSON root must be an object", rel_path))
            continue

        package_id = str(data.get("package_id") or "").strip() or "<missing>"
        package_class = str(data.get("package_class") or "").strip() or "<missing>"
        verdict = str(data.get("verdict") or "").strip() or "<missing>"
        findings.append(
            Finding(
                "info",
                code,
                (
                    f"candidate: checkpoint package receipt: {rel_path}; package_id={package_id}; "
                    f"package_class={package_class}; verdict={verdict}; repo-visible checkpoint evidence only"
                ),
                rel_path,
            )
        )
        findings.extend(_checkpoint_package_receipt_metadata_findings(inventory.root, rel_path, path.stem, data, code_prefix))
        findings.extend(_checkpoint_package_receipt_source_hash_findings(inventory.root, rel_path, data, code_prefix))

    findings.extend(_checkpoint_package_receipt_boundary_findings(code_prefix))
    return findings


def lifecycle_mutation_provenance_findings(inventory: Inventory, code_prefix: str = "lifecycle-provenance") -> list[Finding]:
    state = inventory.state
    state_source = state.rel_path if state and state.exists else "project/project-state.md"
    state_data = state.frontmatter.data if state and state.exists else {}
    facts = state_writeback_facts(state)
    records = _agent_run_record_paths(inventory.root) if inventory.root_kind == "live_operating_root" else []
    coordination_records = _coordination_record_paths(inventory.root) if inventory.root_kind == "live_operating_root" else []
    findings = [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "lifecycle mutation provenance is read-only visibility; it cannot repair, rollback, close out, archive, mark roadmap done, stage, commit, push, or approve concurrent work",
            state_source,
        )
    ]
    if facts:
        fact_fields = ", ".join(sorted(facts)[:8])
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-state-writeback",
                f"project-state closeout/writeback facts are present: fields={fact_fields}; source={state_source}",
                state_source,
            )
        )
    plan_status = str(state_data.get("plan_status") or "").strip()
    active_plan = str(state_data.get("active_plan") or "").strip()
    if plan_status == "active" or active_plan:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-active-lifecycle",
                (
                    f"active lifecycle posture visible: plan_status={plan_status or '<none>'}; "
                    f"active_plan={active_plan or '<none>'}; active_phase={state_data.get('active_phase') or '<none>'}; "
                    f"phase_status={state_data.get('phase_status') or '<none>'}"
                ),
                state_source,
            )
        )
    if records:
        examples = ", ".join(_to_rel_path(inventory.root, path) for path in records[:3])
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-agent-run-visibility",
                f"agent-run evidence records available for recent run visibility: count={len(records)}; examples={examples}",
                AGENT_RUNS_DIR_REL,
            )
        )
    elif (plan_status == "active" or facts) and coordination_records:
        examples = ", ".join(_to_rel_path(inventory.root, path) for path in coordination_records[:3])
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-unknown-owner",
                (
                    "lifecycle/writeback posture is present but no agent-run evidence records were found; "
                    f"concurrent coordination records exist at {examples}; inspect project-state, roadmap, handoff, claim, and Git status before assuming ownership"
                ),
                AGENT_RUNS_DIR_REL,
            )
        )
    elif plan_status == "active" or facts:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-agent-run-absent",
                "active lifecycle/writeback posture is visible and no agent-run evidence records were found; no concurrent coordination records were found",
                AGENT_RUNS_DIR_REL,
            )
        )
    else:
        findings.append(Finding("info", f"{code_prefix}-quiet", "no active lifecycle mutation or agent-run evidence was found", state_source))
    return findings


def evidence_findings(inventory: Inventory) -> list[Finding]:
    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    active_plan = inventory.active_plan_surface if inventory.active_plan_surface and inventory.active_plan_surface.exists else None
    findings: list[Finding] = [
        rails_not_cognition_boundary_finding("project/verification"),
        Finding(
            "info",
            "evidence-boundary",
            "terminal-only read-only report; persistent evidence manifest remains deferred and no files, caches, databases, generated artifacts, VCS probes, hooks, adapters, or mutations are written",
        ),
        Finding("info", "evidence-root-kind", f"root kind: {inventory.root_kind}"),
    ]

    if inventory.root_kind == "product_source_fixture":
        findings.append(
            Finding(
                "info",
                "evidence-non-authority",
                "product source checkout contains compatibility fixtures only; evidence findings do not make it an operating project root",
                state.rel_path if state else None,
            )
        )

    findings.extend(_active_plan_findings(inventory, active_plan, state_data))
    findings.extend(durable_proof_record_findings(inventory, "evidence"))
    findings.extend(agent_run_record_findings(inventory, "evidence-agent-run"))
    findings.extend(worker_run_receipt_findings(inventory, "evidence-worker-run-receipt"))
    findings.extend(checkpoint_package_receipt_findings(inventory, "evidence-checkpoint-package-receipt"))
    findings.extend(_source_set_findings(active_plan, inventory))
    findings.extend(_anchor_findings(active_plan, inventory))
    findings.extend(_identity_findings(active_plan))
    findings.extend(_closeout_findings(active_plan, inventory))
    findings.extend(_git_trailer_suggestion_findings(active_plan, inventory))
    findings.extend(_quality_cue_findings(active_plan, inventory))
    findings.extend(_acceptance_evidence_findings(inventory, state_data))
    findings.extend(_operator_required_findings(inventory))
    findings.extend(_line_group_findings(active_plan, "evidence-residual-risk", "residual risk", (r"residual risk", r"residual risks"), inventory))
    findings.extend(_line_group_findings(active_plan, "evidence-skip-rationale", "skip rationale", SKIP_RATIONALE_PATTERNS, inventory))
    findings.extend(_line_group_findings(active_plan, "evidence-carry-forward", "carry-forward", CARRY_FORWARD_PATTERNS, inventory))
    findings.append(
        Finding(
            "info",
            "evidence-non-authority",
            "candidate evidence can guide closeout assembly, but source files, observed verification, and operator decisions remain authority",
        )
    )
    return findings


def git_context_trailer_values(
    inventory: Inventory,
    active_plan: Surface | None,
    facts: dict[str, WritebackFact],
) -> list[tuple[str, str]]:
    plan_data = active_plan.frontmatter.data if active_plan and active_plan.exists else {}
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    values: list[tuple[str, str]] = []
    for trailer_name, keys in GIT_CONTEXT_TRAILERS:
        value = _first_trailer_value(plan_data, state_data, facts, keys)
        if value:
            values.append((trailer_name, value))
    return values


def _first_trailer_value(
    plan_data: dict[str, object],
    state_data: dict[str, object],
    facts: dict[str, WritebackFact],
    keys: tuple[str, ...],
) -> str:
    for key in keys:
        for value in (plan_data.get(key), facts.get(key).value if key in facts else "", state_data.get(key)):
            normalized = _normalize_trailer_value(value)
            if normalized:
                return normalized
    return ""


def _normalize_trailer_value(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _git_trailer_suggestion_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    facts = state_writeback_facts(inventory.state)
    source = active_plan.rel_path if active_plan else (inventory.state.rel_path if inventory.state and inventory.state.exists else None)
    findings = [
        Finding(
            "info",
            "evidence-git-trailer-boundary",
            "paste-ready Git trailer suggestions are report text only; evidence does not run Git, stage, commit, amend, push, mutate Git config, install hooks, or write evidence manifests",
            source,
        )
    ]
    values = git_context_trailer_values(inventory, active_plan, facts)
    if not values:
        findings.append(
            Finding(
                "info",
                "evidence-git-trailer-skipped",
                "no plan, phase, or slice metadata is available for paste-ready Git trailer suggestions",
                source,
            )
        )
        return findings
    for trailer_name, value in values:
        findings.append(Finding("info", "evidence-git-trailer", f"suggestion: {trailer_name}: {value}", source))
    return findings


def durable_proof_record_findings(inventory: Inventory, code_prefix: str) -> list[Finding]:
    code = f"{code_prefix}-proof-record"
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "info",
                code,
                "durable proof/evidence record scan is live-root only; product fixtures and archive roots remain non-authority context",
                inventory.state.rel_path if inventory.state and inventory.state.exists else None,
            )
        ]

    records = _durable_proof_record_surfaces(inventory)
    if not records:
        return [
            Finding(
                "info",
                code,
                (
                    "no durable proof/evidence records found at project/verification/*.md; "
                    "the active-plan verification block remains the default evidence surface and absence does not block closeout"
                ),
            )
        ]

    findings: list[Finding] = []
    for record in records[:DURABLE_PROOF_RECORD_LIMIT]:
        status = _record_status(record)
        title = _record_title(record)
        findings.append(
            Finding(
                "info",
                code,
                (
                    f"candidate: durable proof/evidence record: {record.rel_path}; "
                    f"status={status}; title={title}; read-only closeout assembly input only"
                ),
                record.rel_path,
            )
        )
        if record.frontmatter.errors or status == "unrecorded" or title == "untitled":
            findings.append(
                Finding(
                    "warn",
                    f"{code}-ambiguous",
                    (
                        f"ambiguous durable proof/evidence record metadata: {record.rel_path}; "
                        "record status and heading should be explicit before relying on it for closeout assembly"
                    ),
                    record.rel_path,
                )
            )
    if len(records) > DURABLE_PROOF_RECORD_LIMIT:
        findings.append(
            Finding(
                "info",
                code,
                f"durable proof/evidence record scan truncated at {DURABLE_PROOF_RECORD_LIMIT} of {len(records)} records",
            )
        )
    findings.append(
        Finding(
            "info",
            f"{code}-non-authority",
            "durable proof/evidence records are report inputs only; they do not satisfy closeout fields, approve lifecycle changes, or write evidence manifests",
        )
    )
    return findings


def _durable_proof_record_surfaces(inventory: Inventory) -> list[Surface]:
    return sorted(
        (
            surface
            for surface in inventory.present_surfaces
            if surface.memory_route == "verification"
            and surface.rel_path.startswith(DURABLE_PROOF_RECORD_PREFIX)
            and surface.path.suffix.lower() == ".md"
        ),
        key=lambda surface: surface.rel_path,
    )


def _tuple_values(values: object) -> tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, str):
        values = (values,)
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text:
            cleaned.append(text)
    return tuple(cleaned)


def _agent_run_request_findings(inventory: Inventory, request: AgentRunRecordRequest, *, apply: bool) -> list[Finding]:
    severity = "error" if apply else "warn"
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                severity,
                "agent-run-record-refused",
                f"target root kind is {inventory.root_kind}; evidence --record --apply requires a live operating root",
            )
        )
    if not request.record_id:
        findings.append(Finding("error", "agent-run-record-refused", "--record-id is required"))
    elif not RECORD_ID_RE.match(request.record_id):
        findings.append(Finding("error", "agent-run-record-refused", "--record-id may contain only letters, digits, dot, underscore, or dash"))
    elif record_id_conflict(request.record_id):
        findings.append(Finding("error", "agent-run-record-refused", f"--record-id {record_id_conflict(request.record_id)}"))

    for field, value in (
        ("--role", request.role),
        ("--actor", request.actor),
        ("--task", request.task),
        ("--assigned-scope", request.assigned_scope),
        ("--runtime", request.runtime),
        ("--worktree-id", request.worktree_id),
        ("--status", request.status),
        ("--stop-reason", request.stop_reason),
        ("--attempt-budget", request.attempt_budget),
        ("--docs-decision", request.docs_decision),
        ("--residual-risk", request.residual_risk),
    ):
        if not value:
            findings.append(Finding("error", "agent-run-record-refused", f"{field} is required"))

    if request.status and request.status not in AGENT_RUN_STATUSES:
        findings.append(
            Finding(
                "error",
                "agent-run-record-refused",
                f"--status must be one of {', '.join(sorted(AGENT_RUN_STATUSES))}",
            )
        )

    if request.docs_decision and request.docs_decision not in AGENT_RUN_DOCS_DECISIONS:
        findings.append(
            Finding(
                "error",
                "agent-run-record-refused",
                f"--docs-decision must be one of {', '.join(sorted(AGENT_RUN_DOCS_DECISIONS))}",
            )
        )

    for field, values in (
        ("--input-ref", request.input_refs),
        ("--output-ref", request.output_refs),
        ("--claimed-path", request.claimed_paths),
        ("--changed-file", request.changed_files),
        ("--command", request.commands),
        ("--verification-ref", request.verification_refs),
    ):
        if not values:
            findings.append(Finding("error", "agent-run-record-refused", f"{field} must be supplied at least once"))

    for field, values in (
        ("--input-ref", request.input_refs),
        ("--output-ref", request.output_refs),
        ("--claimed-path", request.claimed_paths),
        ("--changed-file", request.changed_files),
        ("--verification-ref", request.verification_refs),
        ("--handoff-ref", request.handoff_refs),
        ("--claim-ref", request.claim_refs),
    ):
        for value in values:
            if _is_product_source_ref(value):
                findings.extend(_product_source_ref_findings(inventory.root, field, value, severity))
                continue
            product_ref = _product_source_ref_for_absolute_path(inventory.root, value)
            if product_ref:
                findings.append(
                    Finding(
                        "error",
                        "agent-run-record-refused",
                        f"{field} absolute product_source_root path must use canonical {product_ref}",
                        value,
                    )
                )
                continue
            conflict = _root_relative_path_conflict(value)
            if conflict:
                findings.append(Finding("error", "agent-run-record-refused", f"{field} {conflict}", value))

    if request.record_id:
        target_rel = _agent_run_record_target_rel(request)
        target = inventory.root / target_rel
        findings.extend(_agent_run_record_target_findings(inventory.root, target_rel, severity))
        if _has_self_output_ref(request, target_rel):
            findings.append(
                Finding(
                    severity,
                    "agent-run-record-refused",
                    f"--output-ref must not point at the record target {target_rel}; self-referential agent run records become stale immediately",
                    target_rel,
                )
            )
        elif target.exists() and target.is_file():
            findings.append(
                Finding(
                    "info",
                    "agent-run-record-refresh-target",
                    "agent run record already exists; same --record-id will refresh source_hashes and merge supplied input_refs, handoff_refs, and claim_refs on the existing evidence record",
                    target_rel,
                )
            )
    return findings


def _agent_run_record_target_findings(root: Path, target_rel: str, severity: str) -> list[Finding]:
    findings: list[Finding] = []
    conflict = _root_relative_path_conflict(target_rel)
    if conflict:
        return [Finding(severity, "agent-run-record-refused", f"record target {conflict}", target_rel)]
    if not target_rel.startswith(AGENT_RUN_RECORD_PREFIX) or not target_rel.endswith(".md"):
        return [Finding(severity, "agent-run-record-refused", f"record target must be under {AGENT_RUN_RECORD_PREFIX}*.md", target_rel)]
    target = (root / target_rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return [Finding(severity, "agent-run-record-refused", "record target escapes the target root", target_rel)]
    parent = root.resolve()
    rel_parts = Path(target_rel).parts[:-1]
    current = parent
    for part in rel_parts:
        current = current / part
        if current.is_symlink():
            findings.append(Finding(severity, "agent-run-record-refused", f"record target directory contains a symlink segment: {_to_rel_path(root, current)}", target_rel))
            break
        if current.exists() and not current.is_dir():
            findings.append(Finding(severity, "agent-run-record-refused", f"record target directory contains a non-directory segment: {_to_rel_path(root, current)}", target_rel))
            break
    if target.exists() and not target.is_file():
        findings.append(Finding(severity, "agent-run-record-refused", "record target is not a regular file", target_rel))
    return findings


def _render_agent_run_record(root: Path, request: AgentRunRecordRequest) -> tuple[str, list[Finding]]:
    source_hashes, findings = _source_hash_entries(root, request)
    fields: list[tuple[str, object]] = [
        ("schema", AGENT_RUN_SCHEMA),
        ("record_type", "agent-run"),
        ("record_id", request.record_id),
        ("role", request.role),
        ("actor", request.actor),
        ("task", request.task),
        ("assigned_scope", request.assigned_scope),
        ("runtime", request.runtime),
        ("worktree_id", request.worktree_id),
        ("status", request.status),
        ("stop_reason", request.stop_reason),
        ("attempt_budget", request.attempt_budget),
        ("input_refs", request.input_refs),
        ("output_refs", request.output_refs),
        ("claimed_paths", request.claimed_paths),
        ("changed_files", request.changed_files),
        ("commands", request.commands),
        ("verification_refs", request.verification_refs),
        ("docs_decision", request.docs_decision),
        ("residual_risk", request.residual_risk),
        ("handoff_refs", request.handoff_refs),
        ("claim_refs", request.claim_refs),
        ("source_hashes", tuple(source_hashes)),
        ("created_at_utc", _utc_timestamp()),
    ]
    if request.repeated_failure_signature:
        fields.append(("repeated_failure_signature", request.repeated_failure_signature))
    if request.provider:
        fields.append(("provider", request.provider))
    if request.model_id:
        fields.append(("model_id", request.model_id))
    if request.tools:
        fields.append(("tools", request.tools))

    frontmatter = ["---"]
    for key, value in fields:
        frontmatter.extend(_frontmatter_lines(key, value))
    frontmatter.append("---")

    lines = [
        *frontmatter,
        f"# Agent Run Record: {request.record_id}",
        "",
        "This record is source-bound agent work evidence. It cannot approve lifecycle transitions, archive, staging, commit, or next-plan opening.",
        "",
        "## Summary",
        "",
        f"- role: `{request.role}`",
        f"- actor: `{request.actor}`",
        f"- assigned_scope: `{request.assigned_scope}`",
        f"- runtime: `{request.runtime}`",
        f"- worktree_id: `{request.worktree_id}`",
        f"- status: `{request.status}`",
        f"- stop_reason: `{request.stop_reason}`",
        f"- attempt_budget: `{request.attempt_budget}`",
        f"- docs_decision: `{request.docs_decision}`",
        f"- residual_risk: `{request.residual_risk}`",
        "",
        "## Task",
        "",
        request.task,
        "",
        "## Changed Files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in request.changed_files)
    lines.extend(
        [
            "",
            "## Verification",
            "",
        ]
    )
    lines.extend(f"- `{ref}`" for ref in request.verification_refs)
    lines.extend(
        [
            "",
            "## Handoff And Claim Pointers",
            "",
        ]
    )
    if request.handoff_refs or request.claim_refs:
        lines.extend(f"- handoff: `{ref}`" for ref in request.handoff_refs)
        lines.extend(f"- claim: `{ref}`" for ref in request.claim_refs)
    else:
        lines.append("- none recorded")
    lines.extend(
        [
            "",
            "## Commands",
            "",
        ]
    )
    lines.extend(f"- `{command}`" for command in request.commands)
    lines.extend(["", "## Source Hashes", ""])
    lines.extend(f"- `{entry}`" for entry in source_hashes)
    lines.append("")
    return "\n".join(lines), findings


def _frontmatter_lines(key: str, value: object) -> list[str]:
    if isinstance(value, tuple):
        lines = [f"{key}:"]
        lines.extend(f"  - {_quote_yaml(item)}" for item in value)
        return lines
    return [f"{key}: {_quote_yaml(str(value))}"]


def _quote_yaml(value: object) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _source_hash_entries(root: Path, request: AgentRunRecordRequest) -> tuple[list[str], list[Finding]]:
    return _source_hash_entries_for_refs(root, _source_bound_refs(request))


def _source_hash_entries_for_refs(root: Path, rel_paths: Iterable[str], code_prefix: str = "agent-run-record") -> tuple[list[str], list[Finding]]:
    entries: list[str] = []
    findings: list[Finding] = []
    for rel_path in rel_paths:
        product_ref = _product_source_ref_target(root, rel_path)
        if product_ref is not None:
            ref_label, path, conflict = product_ref
            if conflict:
                entries.append(f"{ref_label} invalid-path")
                findings.append(Finding("warn", f"{code_prefix}-source-hash", f"{ref_label} was recorded as invalid-path: {conflict}", ref_label))
                continue
            if not path.exists():
                entries.append(f"{ref_label} missing")
                findings.append(Finding("info", f"{code_prefix}-source-hash", f"{ref_label} recorded as missing product-source evidence", ref_label))
                continue
            if not path.is_file():
                entries.append(f"{ref_label} invalid-path")
                findings.append(Finding("warn", f"{code_prefix}-source-hash", f"{ref_label} is not a regular product-source file and was recorded as invalid-path", ref_label))
                continue
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                entries.append(f"{ref_label} unreadable")
                findings.append(Finding("warn", f"{code_prefix}-source-hash", f"{ref_label} could not be read for hashing: {exc}", ref_label))
                continue
            entries.append(f"{ref_label} sha256={digest}")
            findings.append(Finding("info", f"{code_prefix}-source-hash", f"{ref_label} sha256={digest[:12]}", ref_label))
            continue
        conflict = _root_relative_path_conflict(rel_path)
        if conflict:
            entries.append(f"{rel_path} invalid-path")
            findings.append(Finding("warn", f"{code_prefix}-source-hash", f"{rel_path} was recorded as invalid-path: {conflict}", rel_path))
            continue
        path = root / rel_path
        boundary_violation = source_path_boundary_violation(root, path, label="agent run source hash ref")
        if boundary_violation is not None:
            entries.append(f"{rel_path} invalid-path")
            findings.append(Finding("warn", f"{code_prefix}-source-hash", boundary_violation.message, rel_path))
            continue
        if not path.exists():
            entries.append(f"{rel_path} missing")
            findings.append(Finding("info", f"{code_prefix}-source-hash", f"{rel_path} recorded as missing source", rel_path))
            continue
        if not path.is_file():
            entries.append(f"{rel_path} invalid-path")
            findings.append(Finding("warn", f"{code_prefix}-source-hash", f"{rel_path} is not a regular file and was recorded as invalid-path", rel_path))
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            entries.append(f"{rel_path} unreadable")
            findings.append(Finding("warn", f"{code_prefix}-source-hash", f"{rel_path} could not be read for hashing: {exc}", rel_path))
            continue
        entries.append(f"{rel_path} sha256={digest}")
        findings.append(Finding("info", f"{code_prefix}-source-hash", f"{rel_path} sha256={digest[:12]}", rel_path))
    return entries, findings


def _source_bound_refs(request: AgentRunRecordRequest) -> tuple[str, ...]:
    return _dedupe_source_refs(
        (
            *request.input_refs,
            *request.output_refs,
            *request.claimed_paths,
            *request.changed_files,
            *request.verification_refs,
            *request.handoff_refs,
            *request.claim_refs,
        )
    )


def _record_source_refs(data: dict[str, object]) -> tuple[str, ...]:
    return _dedupe_source_refs(
        (
            *_frontmatter_string_list(data.get("input_refs")),
            *_frontmatter_string_list(data.get("output_refs")),
            *_frontmatter_string_list(data.get("claimed_paths")),
            *_frontmatter_string_list(data.get("changed_files")),
            *_frontmatter_string_list(data.get("verification_refs")),
            *_frontmatter_string_list(data.get("handoff_refs")),
            *_frontmatter_string_list(data.get("claim_refs")),
        )
    )


def _dedupe_source_refs(values: Iterable[str]) -> tuple[str, ...]:
    refs: list[str] = []
    seen: set[str] = set()
    for rel_path in values:
        normalized = rel_path.replace("\\", "/").strip()
        if normalized and normalized not in seen:
            refs.append(normalized)
            seen.add(normalized)
    return tuple(refs)


def _agent_run_record_metadata_findings(
    rel_path: str,
    frontmatter: Frontmatter,
    data: dict[str, object],
    code_prefix: str,
) -> list[Finding]:
    code = f"{code_prefix}-record-malformed"
    findings: list[Finding] = []
    if not frontmatter.has_frontmatter:
        return [Finding("warn", code, "agent run record is missing frontmatter", rel_path)]
    for error in frontmatter.errors:
        findings.append(Finding("warn", code, error, rel_path))
    for field in AGENT_RUN_REQUIRED_SCALARS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            findings.append(Finding("warn", code, f"agent run record missing required field: {field}", rel_path))
    if data.get("schema") != AGENT_RUN_SCHEMA:
        findings.append(Finding("warn", code, f"agent run record schema should be {AGENT_RUN_SCHEMA}", rel_path))
    if data.get("record_type") != "agent-run":
        findings.append(Finding("warn", code, "agent run record record_type should be agent-run", rel_path))
    record_id = str(data.get("record_id") or "").strip()
    if record_id and not RECORD_ID_RE.match(record_id):
        findings.append(Finding("warn", code, "agent run record record_id may contain only letters, digits, dot, underscore, or dash", rel_path))
    elif record_id and record_id_conflict(record_id):
        findings.append(Finding("warn", code, f"agent run record record_id {record_id_conflict(record_id)}", rel_path))
    status = str(data.get("status") or "").strip()
    if status and status not in AGENT_RUN_STATUSES:
        findings.append(Finding("warn", code, f"agent run record status is unsupported: {status}", rel_path))
    docs_decision = str(data.get("docs_decision") or "").strip()
    if docs_decision and docs_decision not in AGENT_RUN_DOCS_DECISIONS:
        findings.append(Finding("warn", code, f"agent run record docs_decision is unsupported: {docs_decision}", rel_path))
    for field in AGENT_RUN_REQUIRED_LISTS:
        values = _frontmatter_string_list(data.get(field))
        if not values:
            findings.append(Finding("warn", code, f"agent run record missing required list field: {field}", rel_path))
    for field in ("input_refs", "output_refs", "claimed_paths", "changed_files", "verification_refs", "handoff_refs", "claim_refs"):
        for value in _frontmatter_string_list(data.get(field)):
            if _is_product_source_ref(value):
                continue
            conflict = _root_relative_path_conflict(value)
            if conflict:
                findings.append(Finding("warn", code, f"agent run record {field} path {conflict}: {value}", rel_path))
    return findings


def _agent_run_source_hash_findings(
    root: Path,
    rel_path: str,
    data: dict[str, object],
    code_prefix: str,
    *,
    check_freshness: bool = True,
) -> list[Finding]:
    code = f"{code_prefix}-record"
    findings: list[Finding] = []
    for entry in _frontmatter_string_list(data.get("source_hashes")):
        match = SOURCE_HASH_RE.match(entry.strip())
        if not match:
            findings.append(Finding("warn", f"{code}-malformed", f"malformed source_hashes entry: {entry}", rel_path))
            continue
        source_rel = match.group(1).strip()
        expected_hash = match.group(2)
        expected_missing = bool(match.group(3))
        expected_unreadable = bool(match.group(4))
        expected_invalid = bool(match.group(5))
        product_ref = _product_source_ref_target(root, source_rel)
        if product_ref is not None:
            ref_label, source_path, conflict = product_ref
            if conflict:
                findings.append(Finding("warn", f"{code}-malformed", f"source hash product-source path {conflict}: {ref_label}", rel_path))
                continue
            if not check_freshness:
                continue
            if expected_missing:
                if source_path.exists():
                    findings.append(Finding("warn", f"{code}-stale", f"source hash recorded missing product-source path now exists: {ref_label}", rel_path))
                continue
            if expected_unreadable or expected_invalid:
                findings.append(Finding("info", f"{code}-hash", f"source hash entry records {ref_label} as degraded product-source evidence", rel_path))
                continue
            if not source_path.exists():
                findings.append(Finding("warn", f"{code}-stale", f"source hash product-source target is now missing: {ref_label}", rel_path))
                continue
            if not source_path.is_file():
                findings.append(Finding("warn", f"{code}-stale", f"source hash product-source target is not a regular file: {ref_label}", rel_path))
                continue
            try:
                digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
            except OSError as exc:
                findings.append(Finding("warn", f"{code}-stale", f"source hash product-source target could not be read: {exc}", rel_path))
                continue
            if expected_hash and digest.lower() != expected_hash.lower():
                findings.append(Finding("warn", f"{code}-stale", f"source hash product-source target changed: {ref_label}", rel_path))
            else:
                findings.append(Finding("info", f"{code}-hash", f"source hash current for {ref_label}: {digest[:12]}", rel_path))
            continue
        conflict = _root_relative_path_conflict(source_rel)
        if conflict:
            findings.append(Finding("warn", f"{code}-malformed", f"source hash path {conflict}: {source_rel}", rel_path))
            continue
        if not check_freshness:
            continue
        source_path = root / source_rel
        boundary_violation = source_path_boundary_violation(root, source_path, label="agent run source hash target")
        if boundary_violation is not None:
            findings.append(Finding("warn", f"{code}-stale", boundary_violation.message, rel_path))
            continue
        if expected_missing:
            if source_path.exists():
                findings.append(Finding("warn", f"{code}-stale", f"source hash recorded missing path now exists: {source_rel}", rel_path))
            continue
        if expected_unreadable or expected_invalid:
            findings.append(Finding("info", f"{code}-hash", f"source hash entry records {source_rel} as degraded evidence", rel_path))
            continue
        if not source_path.exists():
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is now missing: {source_rel}", rel_path))
            continue
        if not source_path.is_file():
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is no longer a regular file: {source_rel}", rel_path))
            continue
        try:
            current_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except OSError as exc:
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is now unreadable: {source_rel}: {exc}", rel_path))
            continue
        if expected_hash and current_hash.lower() != expected_hash.lower():
            findings.append(
                Finding(
                    "warn",
                    f"{code}-stale",
                    f"source hash mismatch for {source_rel}: expected={expected_hash[:12]} current={current_hash[:12]}",
                    rel_path,
                )
            )
        else:
            findings.append(Finding("info", f"{code}-hash", f"source hash current for {source_rel}: {current_hash[:12]}", rel_path))
    return findings


def _summarize_agent_run_source_hash_findings(findings: list[Finding], code_prefix: str) -> list[Finding]:
    code = f"{code_prefix}-record"
    stale_code = f"{code}-stale"
    current_code = f"{code}-hash"
    stale_findings: list[Finding] = []
    current_findings: list[Finding] = []
    summarized: list[Finding] = []
    for finding in findings:
        if finding.code == stale_code:
            stale_findings.append(finding)
        elif finding.code == current_code:
            current_findings.append(finding)
        else:
            summarized.append(finding)

    if len(stale_findings) > AGENT_RUN_SOURCE_HASH_SUMMARY_THRESHOLD:
        summarized.append(_agent_run_source_hash_summary_finding(stale_findings, f"{stale_code}-summary", "info", "stale"))
    else:
        summarized.extend(stale_findings)

    if len(current_findings) > AGENT_RUN_SOURCE_HASH_SUMMARY_THRESHOLD:
        summarized.append(_agent_run_source_hash_summary_finding(current_findings, f"{current_code}-summary", "info", "current"))
    else:
        summarized.extend(current_findings)

    return summarized


def _agent_run_source_hash_summary_finding(findings: list[Finding], code: str, severity: str, posture: str) -> Finding:
    sample_sources = tuple(dict.fromkeys(finding.source for finding in findings if finding.source))[
        :AGENT_RUN_SOURCE_HASH_SUMMARY_SAMPLE_LIMIT
    ]
    sample = ", ".join(sample_sources) if sample_sources else "none"
    return Finding(
        severity,
        code,
        (
            f"historical/high-volume agent-run source-hash posture grouped {len(findings)} {posture} "
            f"finding(s); sample_records={sample}; exact writeback/fan-in freshness gates and small "
            "evidence sets still report individual source-hash findings"
        ),
        AGENT_RUNS_DIR_REL,
    )


def _agent_run_route_proposal_findings(rel_path: str, data: dict[str, object], code_prefix: str) -> list[Finding]:
    proposals: list[str] = []
    for field in AGENT_RUN_ROUTE_PROPOSAL_FIELDS:
        proposals.extend(_frontmatter_string_list(data.get(field)))
    proposals = list(dict.fromkeys(proposal for proposal in proposals if proposal.strip()))
    if not proposals:
        return []

    findings: list[Finding] = []
    for proposal in proposals:
        allowed, reason = _route_proposal_allowed(proposal)
        if allowed:
            findings.append(
                Finding(
                    "info",
                    f"{code_prefix}-route-proposal",
                    f"route proposal is advisory and allowed for operator review only: {proposal}",
                    rel_path,
                )
            )
        else:
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-route-proposal-refused",
                    f"route proposal refused: {proposal}; {reason}",
                    rel_path,
                )
            )
    findings.append(
        Finding(
            "info",
            f"{code_prefix}-route-proposal-boundary",
            "route proposals are packet evidence only; MLH does not execute commands, approve apply/archive/Git/provider/writeback routes, or mutate lifecycle from them",
            rel_path,
        )
    )
    return findings


def _checkpoint_package_receipt_metadata_findings(
    root: Path,
    rel_path: str,
    filename_stem: str,
    data: dict[str, object],
    code_prefix: str,
) -> list[Finding]:
    code = f"{code_prefix}-record-malformed"
    findings: list[Finding] = []
    for field in CHECKPOINT_PACKAGE_RECEIPT_REQUIRED_SCALARS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            findings.append(Finding("warn", code, f"checkpoint package receipt missing required field: {field}", rel_path))
    for field in CHECKPOINT_PACKAGE_RECEIPT_REQUIRED_LISTS:
        if not _frontmatter_string_list(data.get(field)):
            findings.append(Finding("warn", code, f"checkpoint package receipt missing required list field: {field}", rel_path))

    if data.get("schema") != CHECKPOINT_PACKAGE_RECEIPT_SCHEMA:
        findings.append(Finding("warn", code, f"checkpoint package receipt schema should be {CHECKPOINT_PACKAGE_RECEIPT_SCHEMA}", rel_path))
    if data.get("record_type") != "checkpoint-package-receipt":
        findings.append(Finding("warn", code, "checkpoint package receipt record_type should be checkpoint-package-receipt", rel_path))

    package_id = str(data.get("package_id") or "").strip()
    if package_id and not RECORD_ID_RE.match(package_id):
        findings.append(Finding("warn", code, "checkpoint package receipt package_id may contain only letters, digits, dot, underscore, or dash", rel_path))
    elif package_id and record_id_conflict(package_id):
        findings.append(Finding("warn", code, f"checkpoint package receipt package_id {record_id_conflict(package_id)}", rel_path))
    if package_id and package_id != filename_stem:
        findings.append(Finding("warn", code, f"checkpoint package receipt filename stem {filename_stem} does not match package_id {package_id}", rel_path))

    package_class = str(data.get("package_class") or "").strip()
    if package_class and package_class not in CHECKPOINT_PACKAGE_RECEIPT_PACKAGE_CLASSES:
        findings.append(Finding("warn", f"{code_prefix}-package-class", f"checkpoint package receipt package_class must use the checkpoint package namespace: {package_class}", rel_path))

    verdict = str(data.get("verdict") or "").strip()
    if verdict and verdict not in CHECKPOINT_PACKAGE_RECEIPT_VERDICTS:
        findings.append(Finding("warn", f"{code_prefix}-verdict", f"checkpoint package receipt verdict must use the checkpoint package verdict namespace: {verdict}", rel_path))

    docs_decision = str(data.get("docs_decision") or "").strip()
    if docs_decision and docs_decision not in AGENT_RUN_DOCS_DECISIONS:
        findings.append(Finding("warn", f"{code_prefix}-docs-decision", f"checkpoint package receipt docs_decision is unsupported: {docs_decision}", rel_path))

    summary = data.get("summary")
    if summary not in (None, "") and not isinstance(summary, str):
        findings.append(Finding("warn", f"{code_prefix}-authority-boundary", "checkpoint package receipt summary must be a string when present", rel_path))
    elif isinstance(summary, str) and _checkpoint_package_receipt_authority_claim(summary):
        findings.append(Finding("warn", f"{code_prefix}-authority-boundary", "checkpoint package receipt summary must not claim checkpoint package approval, lifecycle, Git, staging, commit, provider, release, or external authority", rel_path))

    findings.extend(_checkpoint_package_receipt_non_authority_findings(rel_path, data, code_prefix))
    for field in CHECKPOINT_PACKAGE_RECEIPT_REF_FIELDS:
        findings.extend(
            _checkpoint_package_receipt_ref_list_findings(
                root,
                rel_path,
                field,
                data.get(field),
                code,
                exact_file=field in CHECKPOINT_PACKAGE_RECEIPT_EXACT_REF_FIELDS,
                require_existing=field == "included_paths",
            )
        )

    classifier = data.get("classifier")
    findings.extend(_checkpoint_package_receipt_container_findings(rel_path, "classifier", classifier, code_prefix))
    if verdict == "allowed":
        hashed_paths = _checkpoint_package_receipt_source_hash_paths(data)
        for included_path in _frontmatter_string_list(data.get("included_paths")):
            if included_path not in hashed_paths:
                findings.append(
                    Finding(
                        "warn",
                        f"{code_prefix}-record-malformed",
                        f"checkpoint package receipt source_hashes must include included path: {included_path}",
                        rel_path,
                    )
                )
    elif verdict == "blocked":
        missing_reasons = _frontmatter_string_list(data.get("missing_reasons"))
        missing_refs = _frontmatter_string_list(data.get("missing_anchor_refs"))
        if not missing_reasons and not missing_refs:
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-record-malformed",
                    "blocked checkpoint package receipt should name missing_anchor_refs or missing_reasons",
                    rel_path,
                )
            )
    return findings


def _checkpoint_package_receipt_non_authority_findings(rel_path: str, data: dict[str, object], code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    label = str(data.get("non_authority") or "").strip().casefold()
    has_source_label = "checkpoint" in label or "package" in label
    has_non_authority = "evidence" in label and any(
        token in label for token in ("only", "non-authority", "non-authoritative", "cannot", "not authority")
    )
    if label and (not has_source_label or not has_non_authority):
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-authority-boundary",
                "checkpoint package receipt non_authority must explicitly label checkpoint/package evidence as evidence-only and non-authoritative",
                rel_path,
            )
        )
    for field in CHECKPOINT_PACKAGE_RECEIPT_FALSE_AUTHORITY_FIELDS:
        if _worker_run_receipt_truthy(data.get(field)):
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-authority-boundary",
                    f"checkpoint package receipt {field} must remain false; checkpoint packages cannot approve lifecycle, Git, staging, commit, release, or provider authority",
                    rel_path,
                )
            )
    authority = data.get("authority")
    if isinstance(authority, dict):
        for field in CHECKPOINT_PACKAGE_RECEIPT_FALSE_AUTHORITY_FIELDS:
            if _worker_run_receipt_truthy(authority.get(field)):
                findings.append(
                    Finding(
                        "warn",
                        f"{code_prefix}-authority-boundary",
                        f"checkpoint package receipt authority.{field} must remain false; checkpoint packages are evidence only",
                        rel_path,
                    )
                )
    elif authority not in (None, ""):
        findings.append(Finding("warn", f"{code_prefix}-authority-boundary", "checkpoint package receipt authority must be an object when present", rel_path))
    return findings


def _checkpoint_package_receipt_container_findings(rel_path: str, label: str, value: object, code_prefix: str) -> list[Finding]:
    if value in (None, ""):
        return []
    if not isinstance(value, dict):
        return [Finding("warn", f"{code_prefix}-record-malformed", f"checkpoint package receipt {label} must be an object when present", rel_path)]
    findings: list[Finding] = []
    for authority_field in CHECKPOINT_PACKAGE_RECEIPT_FALSE_AUTHORITY_FIELDS:
        if _worker_run_receipt_truthy(value.get(authority_field)):
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-authority-boundary",
                    f"checkpoint package receipt {label}.{authority_field} must remain false; checkpoint package classifier data is evidence only",
                    rel_path,
                )
            )
    authority = value.get("authority")
    if isinstance(authority, dict):
        for authority_field in CHECKPOINT_PACKAGE_RECEIPT_FALSE_AUTHORITY_FIELDS:
            if _worker_run_receipt_truthy(authority.get(authority_field)):
                findings.append(
                    Finding(
                        "warn",
                        f"{code_prefix}-authority-boundary",
                        f"checkpoint package receipt {label}.authority.{authority_field} must remain false; checkpoint package classifier data is evidence only",
                        rel_path,
                    )
                )
    elif authority not in (None, ""):
        findings.append(Finding("warn", f"{code_prefix}-authority-boundary", f"checkpoint package receipt {label}.authority must be an object when present", rel_path))
    summary = value.get("summary")
    if isinstance(summary, str) and _checkpoint_package_receipt_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-authority-boundary",
                f"checkpoint package receipt {label}.summary must not claim checkpoint package approval, lifecycle, Git, staging, commit, provider, release, or external authority",
                rel_path,
            )
        )
    return findings


def _checkpoint_package_receipt_ref_list_findings(
    root: Path,
    rel_path: str,
    field: str,
    value: object,
    code: str,
    *,
    exact_file: bool = False,
    require_existing: bool = False,
) -> list[Finding]:
    if value in (None, ""):
        return []
    refs = _frontmatter_string_list(value)
    if not refs:
        return [Finding("warn", code, f"checkpoint package receipt {field} must be a string or list of strings when present", rel_path)]
    findings: list[Finding] = []
    for ref in refs:
        normalized = ref.replace("\\", "/")
        conflict = _root_relative_path_conflict(ref)
        if conflict:
            findings.append(Finding("warn", code, f"checkpoint package receipt {field} path {conflict}: {ref}", rel_path))
            continue
        target = root / ref
        boundary_violation = source_path_boundary_violation(root, target, label=f"checkpoint package receipt {field}")
        if boundary_violation is not None:
            findings.append(Finding("warn", code, boundary_violation.message, rel_path))
            continue
        if not exact_file:
            continue
        if any(char in ref for char in "*?[]"):
            findings.append(Finding("warn", code, f"checkpoint package receipt {field} path must not contain wildcard: {ref}", rel_path))
        if any(normalized.casefold().startswith(prefix) for prefix in CHECKPOINT_PACKAGE_RECEIPT_PROHIBITED_INCLUDED_PREFIXES):
            findings.append(Finding("warn", code, f"checkpoint package receipt {field} path must not target generated, cache, private, secret, temp, runtime, or VCS files: {ref}", rel_path))
        if target.exists():
            if target.is_symlink():
                findings.append(Finding("warn", code, f"checkpoint package receipt {field} path must not be a symlink: {ref}", rel_path))
            elif target.is_dir():
                findings.append(Finding("warn", code, f"checkpoint package receipt {field} path must name exact file, not directory: {ref}", rel_path))
            elif not target.is_file():
                findings.append(Finding("warn", code, f"checkpoint package receipt {field} path must name exact regular file: {ref}", rel_path))
        elif require_existing:
            findings.append(Finding("warn", code, f"checkpoint package receipt {field} target is missing: {ref}", rel_path))
    return findings


def _worker_run_receipt_metadata_findings(
    root: Path,
    rel_path: str,
    filename_stem: str,
    data: dict[str, object],
    code_prefix: str,
) -> list[Finding]:
    code = f"{code_prefix}-record-malformed"
    findings: list[Finding] = []
    for field in WORKER_RUN_RECEIPT_REQUIRED_SCALARS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            findings.append(Finding("warn", code, f"worker run receipt missing required field: {field}", rel_path))
    for field in WORKER_RUN_RECEIPT_REQUIRED_LISTS:
        if not _frontmatter_string_list(data.get(field)):
            findings.append(Finding("warn", code, f"worker run receipt missing required list field: {field}", rel_path))
    if data.get("schema") != WORKER_RUN_RECEIPT_SCHEMA:
        findings.append(Finding("warn", code, f"worker run receipt schema should be {WORKER_RUN_RECEIPT_SCHEMA}", rel_path))
    if data.get("record_type") != "worker-run-receipt":
        findings.append(Finding("warn", code, "worker run receipt record_type should be worker-run-receipt", rel_path))

    receipt_id = str(data.get("receipt_id") or "").strip()
    if receipt_id and not RECORD_ID_RE.match(receipt_id):
        findings.append(Finding("warn", code, "worker run receipt receipt_id may contain only letters, digits, dot, underscore, or dash", rel_path))
    elif receipt_id and record_id_conflict(receipt_id):
        findings.append(Finding("warn", code, f"worker run receipt receipt_id {record_id_conflict(receipt_id)}", rel_path))
    if receipt_id and receipt_id != filename_stem:
        findings.append(Finding("warn", code, f"worker run receipt filename stem {filename_stem} does not match receipt_id {receipt_id}", rel_path))

    runtime_namespace = str(data.get("runtime_namespace") or "").strip()
    if runtime_namespace and runtime_namespace not in {RUNTIME_STATE_NAMESPACE_ID, "mylittleharness.runtime-state-namespace.v1"}:
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-status-namespace",
                f"worker run receipt runtime_namespace should be {RUNTIME_STATE_NAMESPACE_ID}: {runtime_namespace}",
                rel_path,
            )
        )

    findings.extend(_worker_run_receipt_status_namespace_findings(rel_path, data, code_prefix))
    findings.extend(_worker_run_receipt_non_authority_findings(rel_path, data, code_prefix))
    findings.extend(_worker_run_receipt_event_history_findings(rel_path, data, code_prefix))
    findings.extend(_worker_run_receipt_privacy_findings(rel_path, data, code_prefix))
    findings.extend(_worker_run_receipt_runtime_guard_preflight_findings(root, rel_path, data, code_prefix))
    findings.extend(_worker_run_receipt_checkpoint_resume_findings(root, rel_path, data, code_prefix))
    findings.extend(_worker_run_receipt_child_agent_fanout_findings(root, rel_path, data, code_prefix))
    findings.extend(_worker_run_receipt_capability_fence_decision_findings(root, rel_path, data, code_prefix))
    findings.extend(_worker_run_receipt_runtime_broker_provider_findings(root, rel_path, data, code_prefix))
    findings.extend(_worker_run_receipt_worktree_session_findings(root, rel_path, data, code_prefix))
    findings.extend(_worker_run_receipt_artifact_lineage_findings(root, rel_path, data, code_prefix))
    for field in ("task_input_refs", "event_stream_refs", "output_refs", "verification_refs"):
        for value in _frontmatter_string_list(data.get(field)):
            conflict = _root_relative_path_conflict(value)
            if conflict:
                findings.append(Finding("warn", code, f"worker run receipt {field} path {conflict}: {value}", rel_path))
            else:
                target = root / value
                boundary_violation = source_path_boundary_violation(root, target, label=f"worker run receipt {field}")
                if boundary_violation is not None:
                    findings.append(Finding("warn", code, boundary_violation.message, rel_path))
    return findings


def _worker_run_receipt_status_namespace_findings(rel_path: str, data: dict[str, object], code_prefix: str) -> list[Finding]:
    specs = (
        ("worker_status", WORKER_RUN_RECEIPT_WORKER_STATUSES, "worker"),
        ("runtime_status", WORKER_RUN_RECEIPT_RUNTIME_STATUSES, "runtime"),
        ("workflow_status", WORKER_RUN_RECEIPT_WORKFLOW_STATUSES, "workflow"),
        ("verification_verdict", WORKER_RUN_RECEIPT_VERIFICATION_VERDICTS, "verification verdict"),
        ("lifecycle_status", WORKER_RUN_RECEIPT_LIFECYCLE_STATUSES, "MLH lifecycle"),
        ("research_import_status", WORKER_RUN_RECEIPT_RESEARCH_IMPORT_STATUSES, "research import"),
    )
    findings: list[Finding] = []
    for field, allowed, label in specs:
        status = str(data.get(field) or "").strip()
        if status and status not in allowed:
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-status-namespace",
                    f"worker run receipt {field} must use the {label} namespace: {status}",
                    rel_path,
                )
            )
    worker_status = str(data.get("worker_status") or "").strip()
    if worker_status in WORKER_RUN_RECEIPT_FORBIDDEN_WORKER_STATUS_TERMS:
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-status-namespace",
                f"worker run receipt worker_status must not carry lifecycle or verification status: {worker_status}",
                rel_path,
            )
        )
    return findings


def _worker_run_receipt_non_authority_findings(rel_path: str, data: dict[str, object], code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    label = str(data.get("non_authority") or "").strip().casefold()
    if label and (
        "evidence" not in label
        or not any(token in label for token in ("only", "non-authority", "non-authoritative", "cannot", "not authority"))
    ):
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-authority-boundary",
                "worker run receipt non_authority must explicitly label the receipt as evidence-only and non-authoritative",
                rel_path,
            )
        )
    for field in WORKER_RUN_RECEIPT_FALSE_AUTHORITY_FIELDS:
        if _worker_run_receipt_truthy(data.get(field)):
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-authority-boundary",
                    f"worker run receipt {field} must remain false; worker receipts cannot approve lifecycle or external authority",
                    rel_path,
                )
            )
    authority = data.get("authority")
    if isinstance(authority, dict):
        for field in WORKER_RUN_RECEIPT_FALSE_AUTHORITY_FIELDS:
            if _worker_run_receipt_truthy(authority.get(field)):
                findings.append(
                    Finding(
                        "warn",
                        f"{code_prefix}-authority-boundary",
                        f"worker run receipt authority.{field} must remain false; worker receipts are evidence only",
                        rel_path,
                    )
                )
    elif authority not in (None, ""):
        findings.append(Finding("warn", f"{code_prefix}-authority-boundary", "worker run receipt authority must be an object when present", rel_path))
    return findings


def _worker_run_receipt_event_history_findings(rel_path: str, data: dict[str, object], code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    code = f"{code_prefix}-event-history"
    redaction = str(data.get("event_history_redaction") or "").strip()
    if redaction and redaction not in WORKER_RUN_RECEIPT_EVENT_HISTORY_REDACTION_STATUSES:
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt event_history_redaction must use the event history redaction vocabulary: {redaction}",
                rel_path,
            )
        )

    summary = data.get("event_history_summary")
    if summary not in (None, "") and not isinstance(summary, str):
        findings.append(Finding("warn", code, "worker run receipt event_history_summary must be a string when present", rel_path))
    elif isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt event_history_summary must not claim event history approves lifecycle or external authority",
                rel_path,
            )
        )

    private_trace_policy = data.get("private_trace_policy")
    if private_trace_policy not in (None, "") and not isinstance(private_trace_policy, str):
        findings.append(Finding("warn", code, "worker run receipt private_trace_policy must be a string when present", rel_path))
    elif isinstance(private_trace_policy, str) and private_trace_policy.strip():
        if not _worker_run_receipt_private_trace_policy_is_non_authority(private_trace_policy):
            findings.append(
                Finding(
                    "warn",
                    code,
                    "worker run receipt private_trace_policy must explicitly keep private SDK traces non-authoritative and repo-visible evidence authoritative for recovery",
                    rel_path,
                )
            )
        if _worker_run_receipt_private_trace_authority_claim(private_trace_policy):
            findings.append(
                Finding(
                    "warn",
                    code,
                    "worker run receipt private_trace_policy must not treat private SDK traces as authoritative approval evidence",
                    rel_path,
                )
            )

    for field in ("event_history", "private_traces"):
        findings.extend(_worker_run_receipt_event_history_container_findings(rel_path, field, data.get(field), code_prefix))
    return findings


def _worker_run_receipt_event_history_container_findings(
    rel_path: str,
    field: str,
    value: object,
    code_prefix: str,
) -> list[Finding]:
    if value in (None, ""):
        return []
    if not isinstance(value, dict):
        return [Finding("warn", f"{code_prefix}-event-history", f"worker run receipt {field} must be an object when present", rel_path)]
    findings: list[Finding] = []
    for authority_field in WORKER_RUN_RECEIPT_FALSE_AUTHORITY_FIELDS:
        if _worker_run_receipt_truthy(value.get(authority_field)):
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-event-history",
                    f"worker run receipt {field}.{authority_field} must remain false; event histories and private traces are evidence only",
                    rel_path,
                )
            )
    summary = value.get("summary")
    if isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-event-history",
                f"worker run receipt {field}.summary must not claim event history approves lifecycle or external authority",
                rel_path,
            )
        )
    policy = value.get("private_trace_policy")
    if isinstance(policy, str) and policy.strip() and _worker_run_receipt_private_trace_authority_claim(policy):
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-event-history",
                f"worker run receipt {field}.private_trace_policy must not treat private SDK traces as authoritative approval evidence",
                rel_path,
            )
        )
    return findings


def _worker_run_receipt_runtime_guard_preflight_findings(
    root: Path,
    rel_path: str,
    data: dict[str, object],
    code_prefix: str,
) -> list[Finding]:
    value = data.get("runtime_guard_preflight")
    if value in (None, ""):
        return []
    code = f"{code_prefix}-runtime-guard"
    if not isinstance(value, dict):
        return [Finding("warn", code, "worker run receipt runtime_guard_preflight must be an object when present", rel_path)]

    findings: list[Finding] = []
    schema = str(value.get("schema") or "").strip()
    if schema and schema != RUNTIME_GUARD_PREFLIGHT_RECEIPT_SCHEMA:
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt runtime_guard_preflight schema should be {RUNTIME_GUARD_PREFLIGHT_RECEIPT_SCHEMA}: {schema}",
                rel_path,
            )
        )

    label = str(value.get("non_authority") or "").strip().casefold()
    if label and (
        "evidence" not in label
        or not any(token in label for token in ("only", "non-authority", "non-authoritative", "cannot", "not authority"))
    ):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt runtime_guard_preflight non_authority must explicitly label preflight as evidence-only and non-authoritative",
                rel_path,
            )
        )

    status_specs = (
        ("preflight_status", WORKER_RUN_RECEIPT_RUNTIME_GUARD_STATUSES, "runtime guard preflight"),
        ("mission_preconditions_status", WORKER_RUN_RECEIPT_RUNTIME_GUARD_STATUSES, "mission preconditions"),
        ("runtime_readiness", WORKER_RUN_RECEIPT_RUNTIME_GUARD_READINESS, "runtime readiness"),
        ("replay_status", WORKER_RUN_RECEIPT_RUNTIME_GUARD_REPLAY_STATUSES, "replay"),
        ("worktree_status", WORKER_RUN_RECEIPT_RUNTIME_GUARD_WORKTREE_STATUSES, "worktree"),
    )
    for field, allowed, label in status_specs:
        status = str(value.get(field) or "").strip()
        if status and status not in allowed:
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt runtime_guard_preflight {field} must use the {label} namespace: {status}",
                    rel_path,
                )
            )

    summary = value.get("summary")
    if summary not in (None, "") and not isinstance(summary, str):
        findings.append(Finding("warn", code, "worker run receipt runtime_guard_preflight summary must be a string when present", rel_path))
    elif isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt runtime_guard_preflight summary must not claim preflight approves launch, lifecycle, or external authority",
                rel_path,
            )
        )

    findings.extend(_worker_run_receipt_false_authority_container_findings(rel_path, "runtime_guard_preflight", value, code_prefix))
    for field in WORKER_RUN_RECEIPT_RUNTIME_GUARD_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"runtime_guard_preflight.{field}", value.get(field), code))
    for field in WORKER_RUN_RECEIPT_RUNTIME_GUARD_CONTAINERS:
        findings.extend(_worker_run_receipt_runtime_guard_container_findings(root, rel_path, field, value.get(field), code_prefix))
    return findings


def _worker_run_receipt_checkpoint_resume_findings(
    root: Path,
    rel_path: str,
    data: dict[str, object],
    code_prefix: str,
) -> list[Finding]:
    value = data.get("checkpoint_resume")
    if value in (None, ""):
        return []
    code = f"{code_prefix}-checkpoint-resume"
    if not isinstance(value, dict):
        return [Finding("warn", code, "worker run receipt checkpoint_resume must be an object when present", rel_path)]

    findings: list[Finding] = []
    schema = str(value.get("schema") or "").strip()
    if not schema:
        findings.append(Finding("warn", code, "worker run receipt checkpoint_resume missing required field: schema", rel_path))
    elif schema != CHECKPOINT_RESUME_RECEIPT_SCHEMA:
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt checkpoint_resume schema should be {CHECKPOINT_RESUME_RECEIPT_SCHEMA}: {schema}",
                rel_path,
            )
        )

    label = str(value.get("non_authority") or "").strip().casefold()
    if not label or (
        "evidence" not in label
        or not any(token in label for token in ("only", "non-authority", "non-authoritative", "cannot", "not authority"))
    ):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt checkpoint_resume non_authority must explicitly label checkpoint/resume as evidence-only and non-authoritative",
                rel_path,
            )
        )

    status_specs = (
        ("checkpoint_status", WORKER_RUN_RECEIPT_CHECKPOINT_STATUSES, "checkpoint"),
        ("checkpoint_kind", WORKER_RUN_RECEIPT_CHECKPOINT_KINDS, "checkpoint kind"),
        ("resume_status", WORKER_RUN_RECEIPT_RESUME_STATUSES, "resume"),
        ("restore_strategy", WORKER_RUN_RECEIPT_RESTORE_STRATEGIES, "restore strategy"),
        ("replay_status", WORKER_RUN_RECEIPT_RUNTIME_GUARD_REPLAY_STATUSES, "replay"),
        ("checkpoint_failure_status", WORKER_RUN_RECEIPT_CHECKPOINT_FAILURE_STATUSES, "checkpoint failure"),
        ("idempotency_posture", WORKER_RUN_RECEIPT_IDEMPOTENCY_POSTURES, "idempotency"),
        ("backpressure_mode", WORKER_RUN_RECEIPT_BACKPRESSURE_MODES, "backpressure mode"),
        ("backpressure_verdict", WORKER_RUN_RECEIPT_BACKPRESSURE_VERDICTS, "backpressure verdict"),
        ("backpressure_stale_posture", WORKER_RUN_RECEIPT_BACKPRESSURE_STALE_POSTURES, "backpressure stale posture"),
        ("backpressure_failure_posture", WORKER_RUN_RECEIPT_BACKPRESSURE_FAILURE_POSTURES, "backpressure failure posture"),
    )
    for field, allowed, label in status_specs:
        status = str(value.get(field) or "").strip()
        if status and status not in allowed:
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt checkpoint_resume {field} must use the {label} namespace: {status}",
                    rel_path,
                )
            )

    summary = value.get("summary")
    if summary not in (None, "") and not isinstance(summary, str):
        findings.append(Finding("warn", code, "worker run receipt checkpoint_resume summary must be a string when present", rel_path))
    elif isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt checkpoint_resume summary must not claim checkpoint, replay, queue, backpressure, run, lifecycle, or external authority",
                rel_path,
            )
        )

    findings.extend(
        _worker_run_receipt_false_authority_container_findings(
            rel_path,
            "checkpoint_resume",
            value,
            code_prefix,
            evidence_label="checkpoint/resume/backpressure evidence",
        )
    )
    for field in WORKER_RUN_RECEIPT_CHECKPOINT_RESUME_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"checkpoint_resume.{field}", value.get(field), code))
    return findings


def _worker_run_receipt_child_agent_fanout_findings(
    root: Path,
    rel_path: str,
    data: dict[str, object],
    code_prefix: str,
) -> list[Finding]:
    value = data.get("child_agent_fanout")
    if value in (None, ""):
        return []
    code = f"{code_prefix}-child-fanout"
    if not isinstance(value, dict):
        return [Finding("warn", code, "worker run receipt child_agent_fanout must be an object when present", rel_path)]

    findings: list[Finding] = []
    schema = str(value.get("schema") or "").strip()
    if not schema:
        findings.append(Finding("warn", code, "worker run receipt child_agent_fanout missing required field: schema", rel_path))
    elif schema != CHILD_AGENT_FANOUT_RECEIPT_SCHEMA:
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt child_agent_fanout schema should be {CHILD_AGENT_FANOUT_RECEIPT_SCHEMA}: {schema}",
                rel_path,
            )
        )

    for field in ("parent_run_id",):
        if not isinstance(value.get(field), str) or not str(value.get(field) or "").strip():
            findings.append(Finding("warn", code, f"worker run receipt child_agent_fanout missing required field: {field}", rel_path))

    fanout_status = str(value.get("fanout_status") or "").strip()
    if not fanout_status:
        findings.append(Finding("warn", code, "worker run receipt child_agent_fanout missing required field: fanout_status", rel_path))
    elif fanout_status not in WORKER_RUN_RECEIPT_CHILD_FANOUT_STATUSES:
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt child_agent_fanout fanout_status must use the child fanout namespace: {fanout_status}",
                rel_path,
            )
        )

    label = str(value.get("non_authority") or "").strip().casefold()
    if not label or (
        "evidence" not in label
        or not any(token in label for token in ("only", "non-authority", "non-authoritative", "cannot", "not authority"))
    ):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt child_agent_fanout non_authority must explicitly label fanout as evidence-only and non-authoritative",
                rel_path,
            )
        )

    summary = value.get("summary")
    if summary not in (None, "") and not isinstance(summary, str):
        findings.append(Finding("warn", code, "worker run receipt child_agent_fanout summary must be a string when present", rel_path))
    elif isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt child_agent_fanout summary must not claim fanout approves lifecycle or external authority",
                rel_path,
            )
        )

    findings.extend(
        _worker_run_receipt_false_authority_container_findings(
            rel_path,
            "child_agent_fanout",
            value,
            code_prefix,
            evidence_label="child agent fanout evidence",
        )
    )
    for field in WORKER_RUN_RECEIPT_CHILD_FANOUT_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"child_agent_fanout.{field}", value.get(field), code))

    findings.extend(_worker_run_receipt_child_fanout_runtime_posture_findings(root, rel_path, value.get("runtime_posture"), code_prefix))
    findings.extend(_worker_run_receipt_child_fanout_children_findings(root, rel_path, value.get("children"), code_prefix))
    return findings


def _worker_run_receipt_child_fanout_runtime_posture_findings(
    root: Path,
    rel_path: str,
    value: object,
    code_prefix: str,
) -> list[Finding]:
    if value in (None, ""):
        return []
    code = f"{code_prefix}-child-fanout"
    label = "child_agent_fanout.runtime_posture"
    if not isinstance(value, dict):
        return [Finding("warn", code, f"worker run receipt {label} must be an object when present", rel_path)]

    findings = _worker_run_receipt_false_authority_container_findings(
        rel_path,
        label,
        value,
        code_prefix,
        evidence_label="child fanout runtime posture evidence",
    )
    summary = value.get("summary")
    if summary not in (None, "") and not isinstance(summary, str):
        findings.append(Finding("warn", code, f"worker run receipt {label}.summary must be a string when present", rel_path))
    elif isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt {label}.summary must not claim fanout approves lifecycle or external authority",
                rel_path,
            )
        )
    for field in WORKER_RUN_RECEIPT_CHILD_FANOUT_RUNTIME_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"{label}.{field}", value.get(field), code))
    return findings


def _worker_run_receipt_child_fanout_children_findings(
    root: Path,
    rel_path: str,
    value: object,
    code_prefix: str,
) -> list[Finding]:
    code = f"{code_prefix}-child-fanout"
    if not isinstance(value, list):
        return [Finding("warn", code, "worker run receipt child_agent_fanout missing required list field: children", rel_path)]

    findings: list[Finding] = []
    for index, child in enumerate(value):
        label = f"child_agent_fanout.children[{index}]"
        if not isinstance(child, dict):
            findings.append(Finding("warn", code, f"worker run receipt {label} must be an object", rel_path))
            continue
        for field in ("child_id", "role"):
            if not isinstance(child.get(field), str) or not str(child.get(field) or "").strip():
                findings.append(Finding("warn", code, f"worker run receipt {label} missing required field: {field}", rel_path))
        for field in ("agent_type", "provider_type", "model", "target_root", "residual_risk"):
            field_value = child.get(field)
            if field_value not in (None, "") and not isinstance(field_value, str):
                findings.append(Finding("warn", code, f"worker run receipt {label}.{field} must be a string when present", rel_path))

        status_specs = (
            ("worker_status", WORKER_RUN_RECEIPT_WORKER_STATUSES, "worker"),
            ("runtime_status", WORKER_RUN_RECEIPT_RUNTIME_STATUSES, "runtime"),
            ("workflow_status", WORKER_RUN_RECEIPT_WORKFLOW_STATUSES, "workflow"),
            ("verification_verdict", WORKER_RUN_RECEIPT_VERIFICATION_VERDICTS, "verification verdict"),
            ("lifecycle_status", WORKER_RUN_RECEIPT_LIFECYCLE_STATUSES, "MLH lifecycle"),
        )
        for field, allowed, namespace_label in status_specs:
            status = str(child.get(field) or "").strip()
            if status and status not in allowed:
                findings.append(
                    Finding(
                        "warn",
                        code,
                        f"worker run receipt {label}.{field} must use the {namespace_label} namespace: {status}",
                        rel_path,
                    )
                )
        worker_status = str(child.get("worker_status") or "").strip()
        if worker_status in WORKER_RUN_RECEIPT_FORBIDDEN_WORKER_STATUS_TERMS:
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt {label}.worker_status must not carry lifecycle or verification status: {worker_status}",
                    rel_path,
                )
            )

        summary = child.get("summary")
        if summary not in (None, "") and not isinstance(summary, str):
            findings.append(Finding("warn", code, f"worker run receipt {label}.summary must be a string when present", rel_path))
        elif isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt {label}.summary must not claim child worker evidence approves lifecycle or external authority",
                    rel_path,
                )
            )
        residual_risk = child.get("residual_risk")
        if isinstance(residual_risk, str) and _worker_run_receipt_event_history_authority_claim(residual_risk):
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt {label}.residual_risk must not claim child worker evidence approves lifecycle or external authority",
                    rel_path,
                )
            )

        findings.extend(
            _worker_run_receipt_false_authority_container_findings(
                rel_path,
                label,
                child,
                code_prefix,
                evidence_label="child worker evidence",
            )
        )
        for field in WORKER_RUN_RECEIPT_CHILD_FANOUT_CHILD_REF_FIELDS:
            findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"{label}.{field}", child.get(field), code))
    return findings


def _worker_run_receipt_capability_fence_decision_findings(
    root: Path,
    rel_path: str,
    data: dict[str, object],
    code_prefix: str,
) -> list[Finding]:
    value = data.get("capability_fence_decision")
    if value in (None, ""):
        return []
    code = f"{code_prefix}-capability-fence"
    if not isinstance(value, dict):
        return [Finding("warn", code, "worker run receipt capability_fence_decision must be an object when present", rel_path)]

    findings: list[Finding] = []
    schema = str(value.get("schema") or "").strip()
    if not schema:
        findings.append(Finding("warn", code, "worker run receipt capability_fence_decision missing required field: schema", rel_path))
    elif schema != CAPABILITY_FENCE_DECISION_RECEIPT_SCHEMA:
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt capability_fence_decision schema should be {CAPABILITY_FENCE_DECISION_RECEIPT_SCHEMA}: {schema}",
                rel_path,
            )
        )

    for field in ("fence_id", "capability_profile"):
        if not isinstance(value.get(field), str) or not str(value.get(field) or "").strip():
            findings.append(Finding("warn", code, f"worker run receipt capability_fence_decision missing required field: {field}", rel_path))

    fence_status = str(value.get("fence_status") or "").strip()
    if not fence_status:
        findings.append(Finding("warn", code, "worker run receipt capability_fence_decision missing required field: fence_status", rel_path))
    elif fence_status not in WORKER_RUN_RECEIPT_CAPABILITY_FENCE_STATUSES:
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt capability_fence_decision fence_status must use the capability fence namespace: {fence_status}",
                rel_path,
            )
        )

    label = str(value.get("non_authority") or "").strip().casefold()
    if not label or (
        "evidence" not in label
        or not any(token in label for token in ("only", "non-authority", "non-authoritative", "cannot", "not authority"))
    ):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt capability_fence_decision non_authority must explicitly label capability fence as evidence-only and non-authoritative",
                rel_path,
            )
        )

    status_specs = (
        ("approval_state", WORKER_RUN_RECEIPT_CAPABILITY_FENCE_APPROVAL_STATES, "capability fence approval"),
        ("audit_status", WORKER_RUN_RECEIPT_CAPABILITY_FENCE_AUDIT_STATUSES, "capability fence audit"),
    )
    for field, allowed, label in status_specs:
        status = str(value.get(field) or "").strip()
        if status and status not in allowed:
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt capability_fence_decision {field} must use the {label} namespace: {status}",
                    rel_path,
                )
            )

    summary = value.get("summary")
    if summary not in (None, "") and not isinstance(summary, str):
        findings.append(Finding("warn", code, "worker run receipt capability_fence_decision summary must be a string when present", rel_path))
    elif isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt capability_fence_decision summary must not claim tool authorization approves lifecycle or external authority",
                rel_path,
            )
        )

    findings.extend(
        _worker_run_receipt_false_authority_container_findings(
            rel_path,
            "capability_fence_decision",
            value,
            code_prefix,
            evidence_label="capability fence decision evidence",
        )
    )
    for field in WORKER_RUN_RECEIPT_CAPABILITY_FENCE_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"capability_fence_decision.{field}", value.get(field), code))
    for field in WORKER_RUN_RECEIPT_CAPABILITY_FENCE_CAPABILITY_LIST_FIELDS:
        findings.extend(_worker_run_receipt_capability_fence_list_findings(rel_path, field, value.get(field), code))
    return findings


def _worker_run_receipt_capability_fence_list_findings(
    rel_path: str,
    field: str,
    value: object,
    code: str,
) -> list[Finding]:
    if value in (None, ""):
        return []
    entries = _frontmatter_string_list(value)
    if not entries:
        return [Finding("warn", code, f"worker run receipt capability_fence_decision.{field} must be a string or list of strings when present", rel_path)]
    findings: list[Finding] = []
    for entry in entries:
        if _worker_run_receipt_event_history_authority_claim(entry):
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt capability_fence_decision.{field} must not claim capability authorization approves lifecycle or external authority: {entry}",
                    rel_path,
                )
            )
    return findings


def _worker_run_receipt_runtime_broker_provider_findings(
    root: Path,
    rel_path: str,
    data: dict[str, object],
    code_prefix: str,
) -> list[Finding]:
    value = data.get("runtime_broker_provider")
    if value in (None, ""):
        return []
    code = f"{code_prefix}-runtime-broker-provider"
    if not isinstance(value, dict):
        return [Finding("warn", code, "worker run receipt runtime_broker_provider must be an object when present", rel_path)]

    findings: list[Finding] = []
    schema = str(value.get("schema") or "").strip()
    if not schema:
        findings.append(Finding("warn", code, "worker run receipt runtime_broker_provider missing required field: schema", rel_path))
    elif schema != RUNTIME_BROKER_PROVIDER_RECEIPT_SCHEMA:
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt runtime_broker_provider schema should be {RUNTIME_BROKER_PROVIDER_RECEIPT_SCHEMA}: {schema}",
                rel_path,
            )
        )

    for field in ("broker_id", "provider_id"):
        if not isinstance(value.get(field), str) or not str(value.get(field) or "").strip():
            findings.append(Finding("warn", code, f"worker run receipt runtime_broker_provider missing required field: {field}", rel_path))

    label = str(value.get("non_authority") or "").strip().casefold()
    if not label or (
        "evidence" not in label
        or not any(token in label for token in ("only", "non-authority", "non-authoritative", "cannot", "not authority"))
    ):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt runtime_broker_provider non_authority must explicitly label runtime broker/provider as evidence-only and non-authoritative",
                rel_path,
            )
        )

    status_specs = (
        ("broker_status", WORKER_RUN_RECEIPT_RUNTIME_BROKER_STATUSES, "runtime broker"),
        ("provider_status", WORKER_RUN_RECEIPT_RUNTIME_PROVIDER_STATUSES, "runtime provider"),
        ("registration_status", WORKER_RUN_RECEIPT_BROKER_REGISTRATION_STATUSES, "broker registration"),
        ("join_status", WORKER_RUN_RECEIPT_BROKER_REGISTRATION_STATUSES, "broker join"),
        ("server_status", WORKER_RUN_RECEIPT_BROKER_SERVER_STATUSES, "broker server"),
        ("dispatch_status", WORKER_RUN_RECEIPT_BROKER_DISPATCH_STATUSES, "broker dispatch"),
        ("workspace_isolation_status", WORKER_RUN_RECEIPT_WORKSPACE_ISOLATION_STATUSES, "workspace isolation"),
        ("workspace_cleanup_status", WORKER_RUN_RECEIPT_WORKSPACE_CLEANUP_STATUSES, "workspace cleanup"),
        ("credential_projection_status", WORKER_RUN_RECEIPT_CREDENTIAL_PROJECTION_STATUSES, "credential projection"),
        ("approval_mode", WORKER_RUN_RECEIPT_APPROVAL_MODES, "approval mode"),
        ("resume_status", WORKER_RUN_RECEIPT_RESUME_STATUSES, "resume"),
        ("telemetry_status", WORKER_RUN_RECEIPT_TELEMETRY_STATUSES, "telemetry"),
    )
    for field, allowed, label in status_specs:
        status = str(value.get(field) or "").strip()
        if status and status not in allowed:
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt runtime_broker_provider {field} must use the {label} namespace: {status}",
                    rel_path,
                )
            )

    summary = value.get("summary")
    if summary not in (None, "") and not isinstance(summary, str):
        findings.append(Finding("warn", code, "worker run receipt runtime_broker_provider summary must be a string when present", rel_path))
    elif isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt runtime_broker_provider summary must not claim broker/provider evidence approves launch, lifecycle, provider routing, cleanup, credential projection, telemetry, or external authority",
                rel_path,
            )
        )

    findings.extend(
        _worker_run_receipt_false_authority_container_findings(
            rel_path,
            "runtime_broker_provider",
            value,
            code_prefix,
            evidence_label="runtime broker/provider evidence",
        )
    )
    for field in WORKER_RUN_RECEIPT_RUNTIME_BROKER_PROVIDER_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"runtime_broker_provider.{field}", value.get(field), code))
    for field in WORKER_RUN_RECEIPT_RUNTIME_BROKER_PROVIDER_CONTAINERS:
        findings.extend(_worker_run_receipt_runtime_broker_provider_container_findings(root, rel_path, field, value.get(field), code_prefix))
    return findings


def _worker_run_receipt_runtime_broker_provider_container_findings(
    root: Path,
    rel_path: str,
    field: str,
    value: object,
    code_prefix: str,
) -> list[Finding]:
    if value in (None, ""):
        return []
    code = f"{code_prefix}-runtime-broker-provider"
    label = f"runtime_broker_provider.{field}"
    if not isinstance(value, dict):
        return [Finding("warn", code, f"worker run receipt {label} must be an object when present", rel_path)]

    findings = _worker_run_receipt_false_authority_container_findings(
        rel_path,
        label,
        value,
        code_prefix,
        evidence_label="runtime broker/provider evidence",
    )
    summary = value.get("summary")
    if isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt {label}.summary must not claim broker/provider evidence approves launch, lifecycle, provider routing, cleanup, credential projection, telemetry, or external authority",
                rel_path,
            )
        )
    for ref_field in WORKER_RUN_RECEIPT_RUNTIME_BROKER_PROVIDER_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"{label}.{ref_field}", value.get(ref_field), code))
    return findings


def _worker_run_receipt_worktree_session_findings(
    root: Path,
    rel_path: str,
    data: dict[str, object],
    code_prefix: str,
) -> list[Finding]:
    value = data.get("worker_worktree_session")
    if value in (None, ""):
        return []
    code = f"{code_prefix}-worktree-session"
    if not isinstance(value, dict):
        return [Finding("warn", code, "worker run receipt worker_worktree_session must be an object when present", rel_path)]

    findings: list[Finding] = []
    schema = str(value.get("schema") or "").strip()
    if not schema:
        findings.append(Finding("warn", code, "worker run receipt worker_worktree_session missing required field: schema", rel_path))
    elif schema != WORKER_WORKTREE_SESSION_RECEIPT_SCHEMA:
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt worker_worktree_session schema should be {WORKER_WORKTREE_SESSION_RECEIPT_SCHEMA}: {schema}",
                rel_path,
            )
        )

    for field in ("session_id", "worktree_session_status"):
        if not isinstance(value.get(field), str) or not str(value.get(field) or "").strip():
            findings.append(Finding("warn", code, f"worker run receipt worker_worktree_session missing required field: {field}", rel_path))

    label = str(value.get("non_authority") or "").strip().casefold()
    if not label or (
        "worktree" not in label
        or "session" not in label
        or "evidence" not in label
        or not any(token in label for token in ("only", "non-authority", "non-authoritative", "cannot", "not authority"))
    ):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt worker_worktree_session non_authority must explicitly label worktree/session as evidence-only and non-authoritative",
                rel_path,
            )
        )

    status_specs = (
        ("worktree_session_status", WORKER_RUN_RECEIPT_WORKTREE_SESSION_STATUSES, "worktree session"),
        ("worktree_status", WORKER_RUN_RECEIPT_WORKTREE_SESSION_WORKTREE_STATUSES, "worktree"),
        ("prompt_status", WORKER_RUN_RECEIPT_WORKTREE_SESSION_PROMPT_STATUSES, "prompt"),
        ("status_capture_status", WORKER_RUN_RECEIPT_WORKTREE_SESSION_CAPTURE_STATUSES, "status/capture"),
        ("sandbox_status", WORKER_RUN_RECEIPT_WORKTREE_SESSION_SANDBOX_STATUSES, "sandbox"),
        ("merge_cleanup_status", WORKER_RUN_RECEIPT_WORKTREE_SESSION_MERGE_CLEANUP_STATUSES, "merge/cleanup"),
        ("concurrency_status", WORKER_RUN_RECEIPT_WORKTREE_SESSION_CONCURRENCY_STATUSES, "concurrency"),
        ("wait_status", WORKER_RUN_RECEIPT_WORKTREE_SESSION_WAIT_STATUSES, "wait"),
    )
    for field, allowed, status_label in status_specs:
        status = str(value.get(field) or "").strip()
        if status and status not in allowed:
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt worker_worktree_session {field} must use the {status_label} namespace: {status}",
                    rel_path,
                )
            )

    summary = value.get("summary")
    if summary not in (None, "") and not isinstance(summary, str):
        findings.append(Finding("warn", code, "worker run receipt worker_worktree_session summary must be a string when present", rel_path))
    elif isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt worker_worktree_session summary must not claim worktree/session evidence approves lifecycle, launch, cleanup, Git, provider routing, verification, target-repo acceptance, or external authority",
                rel_path,
            )
        )

    findings.extend(
        _worker_run_receipt_false_authority_container_findings(
            rel_path,
            "worker_worktree_session",
            value,
            code_prefix,
            evidence_label="worktree/session evidence",
        )
    )
    for field in WORKER_RUN_RECEIPT_WORKTREE_SESSION_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"worker_worktree_session.{field}", value.get(field), code))
    for field in WORKER_RUN_RECEIPT_WORKTREE_SESSION_CONTAINERS:
        findings.extend(_worker_run_receipt_worktree_session_container_findings(root, rel_path, field, value.get(field), code_prefix))
    return findings


def _worker_run_receipt_worktree_session_container_findings(
    root: Path,
    rel_path: str,
    field: str,
    value: object,
    code_prefix: str,
) -> list[Finding]:
    if value in (None, ""):
        return []
    code = f"{code_prefix}-worktree-session"
    label = f"worker_worktree_session.{field}"
    if not isinstance(value, dict):
        return [Finding("warn", code, f"worker run receipt {label} must be an object when present", rel_path)]

    findings = _worker_run_receipt_false_authority_container_findings(
        rel_path,
        label,
        value,
        code_prefix,
        evidence_label="worktree/session evidence",
    )
    summary = value.get("summary")
    if isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt {label}.summary must not claim worktree/session evidence approves lifecycle, launch, cleanup, Git, provider routing, verification, target-repo acceptance, or external authority",
                rel_path,
            )
        )
    for ref_field in WORKER_RUN_RECEIPT_WORKTREE_SESSION_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"{label}.{ref_field}", value.get(ref_field), code))
    return findings


def _worker_run_receipt_artifact_lineage_findings(
    root: Path,
    rel_path: str,
    data: dict[str, object],
    code_prefix: str,
) -> list[Finding]:
    value = data.get("artifact_lineage")
    if value in (None, ""):
        return []
    code = f"{code_prefix}-artifact-lineage"
    if not isinstance(value, dict):
        return [Finding("warn", code, "worker run receipt artifact_lineage must be an object when present", rel_path)]

    findings: list[Finding] = []
    schema = str(value.get("schema") or "").strip()
    if not schema:
        findings.append(Finding("warn", code, "worker run receipt artifact_lineage missing required field: schema", rel_path))
    elif schema != ARTIFACT_LINEAGE_RECEIPT_SCHEMA:
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt artifact_lineage schema should be {ARTIFACT_LINEAGE_RECEIPT_SCHEMA}: {schema}",
                rel_path,
            )
        )

    for field in ("lineage_id", "lineage_status"):
        if not isinstance(value.get(field), str) or not str(value.get(field) or "").strip():
            findings.append(Finding("warn", code, f"worker run receipt artifact_lineage missing required field: {field}", rel_path))

    label = str(value.get("non_authority") or "").strip().casefold()
    if not label or (
        "lineage" not in label
        or "evidence" not in label
        or not any(token in label for token in ("only", "non-authority", "non-authoritative", "cannot", "not authority"))
    ):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt artifact_lineage non_authority must explicitly label artifact lineage as evidence-only and non-authoritative",
                rel_path,
            )
        )

    status_specs = (
        ("lineage_status", WORKER_RUN_RECEIPT_ARTIFACT_LINEAGE_STATUSES, "artifact lineage"),
        ("content_hash_status", WORKER_RUN_RECEIPT_ARTIFACT_HASH_STATUSES, "artifact content hash"),
        ("parent_hash_status", WORKER_RUN_RECEIPT_ARTIFACT_HASH_STATUSES, "artifact parent hash"),
        ("signature_status", WORKER_RUN_RECEIPT_ARTIFACT_SIGNATURE_STATUSES, "artifact signature"),
        ("hmac_status", WORKER_RUN_RECEIPT_ARTIFACT_SIGNATURE_STATUSES, "artifact hmac"),
        (
            "lineage_verification_status",
            WORKER_RUN_RECEIPT_ARTIFACT_LINEAGE_VERIFICATION_STATUSES,
            "artifact lineage verification",
        ),
    )
    for field, allowed, status_label in status_specs:
        status = str(value.get(field) or "").strip()
        if status and status not in allowed:
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt artifact_lineage {field} must use the {status_label} namespace: {status}",
                    rel_path,
                )
            )

    summary = value.get("summary")
    if summary not in (None, "") and not isinstance(summary, str):
        findings.append(Finding("warn", code, "worker run receipt artifact_lineage summary must be a string when present", rel_path))
    elif isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                "worker run receipt artifact_lineage summary must not claim artifact lineage approves lifecycle, verification, artifact acceptance, or external authority",
                rel_path,
            )
        )

    findings.extend(
        _worker_run_receipt_false_authority_container_findings(
            rel_path,
            "artifact_lineage",
            value,
            code_prefix,
            evidence_label="artifact lineage evidence",
        )
    )
    for field in WORKER_RUN_RECEIPT_ARTIFACT_LINEAGE_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"artifact_lineage.{field}", value.get(field), code))
    for field in WORKER_RUN_RECEIPT_ARTIFACT_LINEAGE_CONTAINERS:
        findings.extend(_worker_run_receipt_artifact_lineage_container_findings(root, rel_path, field, value.get(field), code_prefix))
    return findings


def _worker_run_receipt_artifact_lineage_container_findings(
    root: Path,
    rel_path: str,
    field: str,
    value: object,
    code_prefix: str,
) -> list[Finding]:
    if value in (None, ""):
        return []
    code = f"{code_prefix}-artifact-lineage"
    label = f"artifact_lineage.{field}"
    if not isinstance(value, dict):
        return [Finding("warn", code, f"worker run receipt {label} must be an object when present", rel_path)]

    findings = _worker_run_receipt_false_authority_container_findings(
        rel_path,
        label,
        value,
        code_prefix,
        evidence_label="artifact lineage evidence",
    )
    summary = value.get("summary")
    if isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt {label}.summary must not claim artifact lineage approves lifecycle, verification, artifact acceptance, or external authority",
                rel_path,
            )
        )
    for ref_field in WORKER_RUN_RECEIPT_ARTIFACT_LINEAGE_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"{label}.{ref_field}", value.get(ref_field), code))
    return findings


def _worker_run_receipt_runtime_guard_container_findings(
    root: Path,
    rel_path: str,
    field: str,
    value: object,
    code_prefix: str,
) -> list[Finding]:
    if value in (None, ""):
        return []
    code = f"{code_prefix}-runtime-guard"
    container_label = f"runtime_guard_preflight.{field}"
    if not isinstance(value, dict):
        return [Finding("warn", code, f"worker run receipt {container_label} must be an object when present", rel_path)]

    findings = _worker_run_receipt_false_authority_container_findings(rel_path, container_label, value, code_prefix)
    summary = value.get("summary")
    if isinstance(summary, str) and _worker_run_receipt_event_history_authority_claim(summary):
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt {container_label}.summary must not claim runtime guard evidence approves launch, lifecycle, or external authority",
                rel_path,
            )
        )

    if field == "hook_proof":
        proof_level = str(value.get("proof_level") or "").strip()
        if proof_level and proof_level not in WORKER_RUN_RECEIPT_RUNTIME_GUARD_HOOK_PROOF_LEVELS:
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt {container_label}.proof_level must use the hook proof vocabulary: {proof_level}",
                    rel_path,
                )
            )
        if proof_level in {"fallback", "synthetic", "not-recorded", "unknown"} and isinstance(summary, str) and _worker_run_receipt_native_hook_overclaim(summary):
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt {container_label}.summary must not claim native hook proof when proof_level is {proof_level}",
                    rel_path,
                )
            )
    if field == "provider_proof":
        proof_level = str(value.get("proof_level") or "").strip()
        if proof_level and proof_level not in WORKER_RUN_RECEIPT_RUNTIME_GUARD_PROVIDER_PROOF_LEVELS:
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt {container_label}.proof_level must use the provider proof vocabulary: {proof_level}",
                    rel_path,
                )
            )
        if proof_level != "provider-called" and isinstance(summary, str) and _worker_run_receipt_provider_call_overclaim(summary):
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt {container_label}.summary must not claim provider-call proof when proof_level is {proof_level or 'missing'}",
                    rel_path,
                )
            )

    for ref_field in WORKER_RUN_RECEIPT_RUNTIME_GUARD_REF_FIELDS:
        findings.extend(_worker_run_receipt_ref_list_findings(root, rel_path, f"{container_label}.{ref_field}", value.get(ref_field), code))
    return findings


def _worker_run_receipt_false_authority_container_findings(
    rel_path: str,
    label: str,
    value: dict[str, object],
    code_prefix: str,
    *,
    evidence_label: str = "runtime guard evidence",
) -> list[Finding]:
    findings: list[Finding] = []
    code = f"{code_prefix}-authority-boundary"
    for authority_field in WORKER_RUN_RECEIPT_FALSE_AUTHORITY_FIELDS:
        if _worker_run_receipt_truthy(value.get(authority_field)):
            findings.append(
                Finding(
                    "warn",
                    code,
                    f"worker run receipt {label}.{authority_field} must remain false; {evidence_label} cannot approve launch, lifecycle, or external authority",
                    rel_path,
                )
            )
    authority = value.get("authority")
    if isinstance(authority, dict):
        for authority_field in WORKER_RUN_RECEIPT_FALSE_AUTHORITY_FIELDS:
            if _worker_run_receipt_truthy(authority.get(authority_field)):
                findings.append(
                    Finding(
                        "warn",
                        code,
                        f"worker run receipt {label}.authority.{authority_field} must remain false; {evidence_label} is evidence only",
                        rel_path,
                    )
                )
    elif authority not in (None, ""):
        findings.append(Finding("warn", code, f"worker run receipt {label}.authority must be an object when present", rel_path))
    return findings


def _worker_run_receipt_privacy_findings(rel_path: str, data: dict[str, object], code_prefix: str) -> list[Finding]:
    return _worker_run_receipt_private_trace_findings(
        rel_path,
        "$",
        data,
        f"{code_prefix}-privacy-boundary",
        in_private_context=False,
    )


def _worker_run_receipt_private_trace_findings(
    rel_path: str,
    path: str,
    value: object,
    code: str,
    *,
    in_private_context: bool,
) -> list[Finding]:
    findings: list[Finding] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized_key = _worker_run_receipt_normalized_privacy_key(key)
            child_path = f"{path}.{key}" if path != "$" else f"$.{key}"
            child_in_private_context = in_private_context or normalized_key in WORKER_RUN_RECEIPT_PRIVATE_TRACE_CONTEXT_KEYS
            if normalized_key in WORKER_RUN_RECEIPT_PRIVATE_TRACE_CONTEXT_KEYS:
                findings.append(
                    Finding(
                        "warn",
                        code,
                        f"worker run receipt {child_path} raw/private SDK or provider payload key is forbidden",
                        rel_path,
                    )
                )
            if in_private_context and normalized_key in WORKER_RUN_RECEIPT_PRIVATE_TRACE_PAYLOAD_KEYS:
                findings.append(
                    Finding(
                        "warn",
                        code,
                        f"worker run receipt {child_path} raw chat/tool/provider payload field is forbidden",
                        rel_path,
                    )
                )
            if normalized_key in WORKER_RUN_RECEIPT_PRIVATE_TRACE_FALSE_KEYS and _worker_run_receipt_truthy(child):
                findings.append(
                    Finding(
                        "warn",
                        code,
                        f"worker run receipt {child_path} private trace persistence or authority flag must be false",
                        rel_path,
                    )
                )
            if normalized_key in WORKER_RUN_RECEIPT_PRIVATE_TRACE_SENSITIVE_KEYS and not _worker_run_receipt_redacted_secret_value(child):
                findings.append(
                    Finding(
                        "warn",
                        code,
                        f"worker run receipt {child_path} secret-like field must be absent or explicitly redacted",
                        rel_path,
                    )
                )
            findings.extend(
                _worker_run_receipt_private_trace_findings(
                    rel_path,
                    child_path,
                    child,
                    code,
                    in_private_context=child_in_private_context,
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(
                _worker_run_receipt_private_trace_findings(
                    rel_path,
                    f"{path}[{index}]",
                    child,
                    code,
                    in_private_context=in_private_context,
                )
            )
    elif isinstance(value, str) and _worker_run_receipt_sensitive_string(value):
        findings.append(
            Finding(
                "warn",
                code,
                f"worker run receipt {path} must not contain unredacted secret, header, bearer, or provider credential-shaped values",
                rel_path,
            )
        )
    return findings


def _worker_run_receipt_sensitive_string(value: str) -> bool:
    screened = _worker_run_receipt_scrub_redacted_secret_fragments(value)
    return any(
        re.search(pattern, screened, re.IGNORECASE)
        for pattern in (
            r"\b(?:Authorization|Proxy-Authorization|X-Api-Key|api-key|Cookie|Set-Cookie)\s*:\s*(?:Bearer\s+)?[A-Za-z0-9._~+/=-]{8,}",
            r"\bBearer\s+[A-Za-z0-9._-]{8,}",
            r"\b(?:sk|sk-proj|rk)-[A-Za-z0-9_-]{8,}\b",
            r"\b(?:OPENAI_API_KEY|AZURE_OPENAI_API_KEY|GITHUB_TOKEN)\s*=\s*[A-Za-z0-9._~+/=-]{8,}",
        )
    )


def _worker_run_receipt_scrub_redacted_secret_fragments(value: str) -> str:
    return re.sub(
        r"(?:<\s*redacted\s*>|\[\s*redacted\s*\]|\bredacted(?:[-_][A-Za-z0-9._-]+)?\b|\*{3,})",
        " ",
        value,
        flags=re.IGNORECASE,
    )


def _worker_run_receipt_redacted_secret_value(value: object) -> bool:
    if value in (None, "", False):
        return True
    if isinstance(value, str):
        normalized = " ".join(value.casefold().split())
        if normalized in {"false", "none", "nil", "null", "empty", "not-requested", "not-configured", "omitted", "<omitted>"}:
            return True
        if _worker_run_receipt_sensitive_string(value):
            return False
        if normalized in {"redacted", "<redacted>", "[redacted]", "***"}:
            return True
        if "redacted" not in normalized:
            return False
        scrubbed = _worker_run_receipt_scrub_redacted_secret_fragments(normalized)
        residue_words = re.findall(r"[a-z0-9]+", scrubbed.casefold())
        return all(
            word
            in {
                "api",
                "authorization",
                "azure",
                "bearer",
                "cookie",
                "github",
                "key",
                "openai",
                "proxy",
                "secret",
                "set",
                "token",
                "value",
                "x",
            }
            for word in residue_words
        )
    if isinstance(value, dict):
        for raw_key, child in value.items():
            normalized_key = _worker_run_receipt_normalized_privacy_key(str(raw_key))
            if normalized_key in {"redacted", "omitted"} and _worker_run_receipt_truthy(child):
                return True
    return False


def _worker_run_receipt_normalized_privacy_key(value: str) -> str:
    camel_split = re.sub(r"(?<!^)(?=[A-Z])", "_", value)
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", camel_split).casefold()
    return normalized.strip("_")


def _worker_run_receipt_ref_list_findings(root: Path, rel_path: str, field: str, value: object, code: str) -> list[Finding]:
    if value in (None, ""):
        return []
    refs = _frontmatter_string_list(value)
    if not refs:
        return [Finding("warn", code, f"worker run receipt {field} must be a string or list of strings when present", rel_path)]
    findings: list[Finding] = []
    for ref in refs:
        conflict = _root_relative_path_conflict(ref)
        if conflict:
            findings.append(Finding("warn", code, f"worker run receipt {field} path {conflict}: {ref}", rel_path))
            continue
        target = root / ref
        boundary_violation = source_path_boundary_violation(root, target, label=f"worker run receipt {field}")
        if boundary_violation is not None:
            findings.append(Finding("warn", code, boundary_violation.message, rel_path))
    return findings


def _worker_run_receipt_native_hook_overclaim(value: str) -> bool:
    text = " ".join(value.casefold().split())
    if any(token in text for token in ("no native hook", "not native hook", "without native hook", "native hook proof not")):
        return False
    return "native hook" in text and any(token in text for token in ("proof", "installed", "authorizes", "approves", "ready"))


def _worker_run_receipt_provider_call_overclaim(value: str) -> bool:
    text = " ".join(value.casefold().split())
    if any(token in text for token in ("no provider call", "without provider call", "provider call not", "not called")):
        return False
    return any(token in text for token in ("provider call", "provider-called", "called provider")) or (
        "provider" in text and "routing" in text and any(token in text for token in ("approved", "approves", "authorizes", "ready"))
    )


def _worker_run_receipt_event_history_authority_claim(value: str) -> bool:
    text = " ".join(value.casefold().split())
    if any(token in text for token in WORKER_RUN_RECEIPT_EVENT_HISTORY_NEGATION_TOKENS):
        return False
    return any(verb in text for verb in WORKER_RUN_RECEIPT_EVENT_HISTORY_AUTHORITY_VERBS) and any(
        target in text for target in WORKER_RUN_RECEIPT_EVENT_HISTORY_AUTHORITY_TARGETS
    )


def _worker_run_receipt_private_trace_policy_is_non_authority(value: str) -> bool:
    text = " ".join(value.casefold().split())
    has_trace_source = any(token in text for token in WORKER_RUN_RECEIPT_PRIVATE_TRACE_SOURCE_TOKENS)
    has_non_authority = any(token in text for token in WORKER_RUN_RECEIPT_PRIVATE_TRACE_NON_AUTHORITY_TOKENS)
    has_repo_visible_recovery = "repo-visible" in text or "durable evidence" in text or "evidence only" in text or "evidence-only" in text
    return has_trace_source and has_non_authority and has_repo_visible_recovery


def _worker_run_receipt_private_trace_authority_claim(value: str) -> bool:
    text = " ".join(value.casefold().split())
    if any(token in text for token in WORKER_RUN_RECEIPT_EVENT_HISTORY_NEGATION_TOKENS):
        return False
    has_trace_source = any(token in text for token in WORKER_RUN_RECEIPT_PRIVATE_TRACE_SOURCE_TOKENS)
    has_authority = "authoritative" in text or "authority" in text or "approval" in text or "approve" in text
    return has_trace_source and has_authority


def _checkpoint_package_receipt_authority_claim(value: str) -> bool:
    text = " ".join(value.casefold().split())
    if any(token in text for token in WORKER_RUN_RECEIPT_EVENT_HISTORY_NEGATION_TOKENS):
        return False
    targets = (
        *WORKER_RUN_RECEIPT_EVENT_HISTORY_AUTHORITY_TARGETS,
        "checkpoint",
        "checkpoint package",
        "package",
        "local checkpoint",
        "evidence package",
    )
    return any(verb in text for verb in WORKER_RUN_RECEIPT_EVENT_HISTORY_AUTHORITY_VERBS) and any(target in text for target in targets)


def _checkpoint_package_receipt_source_hash_paths(data: dict[str, object]) -> set[str]:
    paths: set[str] = set()
    for entry in _frontmatter_string_list(data.get("source_hashes")):
        match = SOURCE_HASH_RE.match(entry.strip())
        if match:
            paths.add(match.group(1).strip())
    return paths


def _checkpoint_package_receipt_source_hash_findings(root: Path, rel_path: str, data: dict[str, object], code_prefix: str) -> list[Finding]:
    code = f"{code_prefix}-record"
    findings: list[Finding] = []
    for entry in _frontmatter_string_list(data.get("source_hashes")):
        match = SOURCE_HASH_RE.match(entry.strip())
        if not match:
            findings.append(Finding("warn", f"{code}-malformed", f"malformed source_hashes entry: {entry}", rel_path))
            continue
        source_rel = match.group(1).strip()
        expected_hash = match.group(2)
        expected_missing = bool(match.group(3))
        expected_unreadable = bool(match.group(4))
        expected_invalid = bool(match.group(5))
        conflict = _root_relative_path_conflict(source_rel)
        if conflict:
            findings.append(Finding("warn", f"{code}-malformed", f"source hash path {conflict}: {source_rel}", rel_path))
            continue
        source_path = root / source_rel
        boundary_violation = source_path_boundary_violation(root, source_path, label="checkpoint package receipt source hash target")
        if boundary_violation is not None:
            findings.append(Finding("warn", f"{code}-stale", boundary_violation.message, rel_path))
            continue
        if expected_missing:
            if source_path.exists():
                findings.append(Finding("warn", f"{code}-stale", f"source hash recorded missing path now exists: {source_rel}", rel_path))
            continue
        if expected_unreadable or expected_invalid:
            findings.append(Finding("info", f"{code}-hash", f"source hash entry records {source_rel} as degraded evidence", rel_path))
            continue
        if not source_path.exists():
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is now missing: {source_rel}", rel_path))
            continue
        if not source_path.is_file():
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is no longer a regular file: {source_rel}", rel_path))
            continue
        try:
            current_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except OSError as exc:
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is now unreadable: {source_rel}: {exc}", rel_path))
            continue
        if expected_hash and current_hash.lower() != expected_hash.lower():
            findings.append(
                Finding(
                    "warn",
                    f"{code}-stale",
                    f"source hash mismatch for {source_rel}: expected={expected_hash[:12]} current={current_hash[:12]}",
                    rel_path,
                )
            )
        else:
            findings.append(Finding("info", f"{code}-hash", f"source hash current for {source_rel}: {current_hash[:12]}", rel_path))
    return findings


def _worker_run_receipt_source_hash_findings(root: Path, rel_path: str, data: dict[str, object], code_prefix: str) -> list[Finding]:
    code = f"{code_prefix}-record"
    findings: list[Finding] = []
    for entry in _frontmatter_string_list(data.get("source_hashes")):
        match = SOURCE_HASH_RE.match(entry.strip())
        if not match:
            findings.append(Finding("warn", f"{code}-malformed", f"malformed source_hashes entry: {entry}", rel_path))
            continue
        source_rel = match.group(1).strip()
        expected_hash = match.group(2)
        expected_missing = bool(match.group(3))
        expected_unreadable = bool(match.group(4))
        expected_invalid = bool(match.group(5))
        conflict = _root_relative_path_conflict(source_rel)
        if conflict:
            findings.append(Finding("warn", f"{code}-malformed", f"source hash path {conflict}: {source_rel}", rel_path))
            continue
        source_path = root / source_rel
        boundary_violation = source_path_boundary_violation(root, source_path, label="worker run receipt source hash target")
        if boundary_violation is not None:
            findings.append(Finding("warn", f"{code}-stale", boundary_violation.message, rel_path))
            continue
        if expected_missing:
            if source_path.exists():
                findings.append(Finding("warn", f"{code}-stale", f"source hash recorded missing path now exists: {source_rel}", rel_path))
            continue
        if expected_unreadable or expected_invalid:
            findings.append(Finding("info", f"{code}-hash", f"source hash entry records {source_rel} as degraded evidence", rel_path))
            continue
        if not source_path.exists():
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is now missing: {source_rel}", rel_path))
            continue
        if not source_path.is_file():
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is no longer a regular file: {source_rel}", rel_path))
            continue
        try:
            current_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except OSError as exc:
            findings.append(Finding("warn", f"{code}-stale", f"source hash target is now unreadable: {source_rel}: {exc}", rel_path))
            continue
        if expected_hash and current_hash.lower() != expected_hash.lower():
            findings.append(
                Finding(
                    "warn",
                    f"{code}-stale",
                    f"source hash mismatch for {source_rel}: expected={expected_hash[:12]} current={current_hash[:12]}",
                    rel_path,
                )
            )
        else:
            findings.append(Finding("info", f"{code}-hash", f"source hash current for {source_rel}: {current_hash[:12]}", rel_path))
    return findings


def _worker_run_receipt_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, list):
        return any(_worker_run_receipt_truthy(item) for item in value)
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "required", "enabled", "on", "approved"}


def _checkpoint_package_receipt_boundary_findings(code_prefix: str = "checkpoint-package-receipt") -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "checkpoint package receipts are evidence only; allowed, blocked, or unknown verdicts cannot approve lifecycle, archive, roadmap status, staging, commit, push, release, provider routing, cleanup, or target-repo acceptance",
            CHECKPOINT_PACKAGE_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-route",
            "checkpoint package receipts live under project/verification/checkpoint-packages/*.json and describe exact repo-visible files, skipped paths, verification refs, docs decision, and source hashes without creating Git or lifecycle authority",
            CHECKPOINT_PACKAGE_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-verdict",
            "checkpoint package receipt verdicts are limited to allowed, blocked, or unknown and remain advisory evidence for operator review",
            CHECKPOINT_PACKAGE_RECEIPTS_DIR_REL,
        ),
    ]


def _worker_run_receipt_boundary_findings(code_prefix: str = "worker-run-receipt") -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "worker run receipts are evidence only; worker success, reviewer approval, or SDK traces cannot approve lifecycle, archive, roadmap status, staging, commit, push, release, or provider routing",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-route",
            "worker run receipts live under project/verification/worker-run-receipts/*.json and no hidden runtime, queue, cache, database, adapter state, or provider gateway is created",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-status-namespace",
            "runtime_state_namespace.v1 keeps runtime_status, worker_status, workflow_status, verification_verdict, lifecycle_status, and research_import_status as separate namespaces",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-event-history",
            "event history refs are source-bound evidence; private SDK traces must be redacted, summarized, or excluded and cannot approve lifecycle authority",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-runtime-guard",
            "runtime_guard_preflight is nested source-bound evidence for preflight, worktree, bypass, hook, provider, and readiness posture; it cannot approve launch or lifecycle authority",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-checkpoint-resume",
            "checkpoint_resume is nested source-bound evidence for durable task/run refs, checkpoint/resume posture, replay refs, idempotency, and backpressure; queue success, checkpoint creation, replay success, and backpressure verdicts cannot approve lifecycle authority",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-child-fanout",
            "child_agent_fanout is nested source-bound evidence for parent/child worker coordination; child worker success, fan-in readiness, worktree posture, bypass posture, hook proof, provider proof, and private traces cannot approve lifecycle authority",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-capability-fence",
            "capability_fence_decision is nested source-bound evidence for tool/capability policy decisions; allow, deny, approval, audit, gateway, or policy outcomes cannot approve lifecycle, launch, fan-in, verification acceptance, roadmap status, archive, Git, provider routing, release, cleanup, or target-repo acceptance",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-runtime-broker-provider",
            "runtime_broker_provider is nested source-bound evidence for runtime broker/provider, workspace, credential, resume, cleanup, and telemetry posture; broker dispatch, provider defaulting, workspace mounts, credential projection, resume, cleanup, telemetry export, worker success, or reviewer approval cannot approve lifecycle authority",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-worktree-session",
            "worker_worktree_session is nested source-bound evidence for worktree/session/pane refs, prompt refs, status/capture refs, sandbox posture, bounded concurrency, wait, merge, and cleanup posture; terminal panes, dashboards, wait success, sandbox declarations, merge success, cleanup success, worker success, or reviewer approval cannot approve lifecycle authority",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-artifact-lineage",
            "artifact_lineage is nested source-bound evidence for output/input artifact lineage, producer/prompt/model/cost metadata, hash/signature/HMAC posture, and verification refs; lineage records, signatures, HMAC chains, worker success, reviewer approval, or verifier pass cannot approve lifecycle authority",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
    ]


def _route_proposal_allowed(proposal: str) -> tuple[bool, str]:
    text = proposal.strip()
    if not text:
        return False, "empty proposal"
    try:
        tokens = shlex.split(text, posix=False)
    except ValueError as exc:
        return False, f"proposal could not be tokenized: {exc}"
    normalized = [_strip_quotes(token).casefold() for token in tokens if _strip_quotes(token)]
    if not normalized:
        return False, "empty proposal"
    for term in ROUTE_PROPOSAL_FORBIDDEN_TERMS:
        if term in normalized:
            return False, f"contains forbidden lifecycle/provider/writeback/Git term `{term}`"
    command_tokens = _route_proposal_command_tokens(normalized)
    if not command_tokens:
        return False, "missing MLH command"
    command = command_tokens[0]
    if command == "check":
        return True, ""
    if command == "plan":
        if "--dry-run" in command_tokens and "--apply" not in command_tokens:
            return True, ""
        return False, "plan proposals must include --dry-run and must not include --apply"
    return False, "only check and plan --dry-run route proposals are allowed"


def _route_proposal_command_tokens(tokens: list[str]) -> list[str]:
    remaining = list(tokens)
    if remaining and Path(remaining[0]).name.casefold() in {"mylittleharness", "mylittleharness.exe", "python", "python.exe", "uv", "uv.exe"}:
        remaining = remaining[1:]
    if remaining and remaining[0] == "-m":
        remaining = remaining[2:] if len(remaining) > 1 and remaining[1] == "mylittleharness" else remaining[1:]
    if remaining and remaining[0] in {"mylittleharness", "mylittleharness.exe"}:
        remaining = remaining[1:]
    index = 0
    while index < len(remaining):
        token = remaining[index]
        if token == "--root":
            index += 2
            continue
        if token.startswith("--root="):
            index += 1
            continue
        break
    return remaining[index:]


def _strip_quotes(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text


def _frontmatter_string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _agent_run_record_paths(root: Path) -> list[Path]:
    directory = root / AGENT_RUNS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(directory.glob("*.md"))


def agent_run_retired_records(root: Path, code_prefix: str) -> tuple[set[str], list[Finding]]:
    path = root / AGENT_RUN_RETIREMENT_SUMMARY_REL
    code = f"{code_prefix}-record-retirement"
    if not path.exists():
        return set(), []
    if path.is_symlink() or not path.is_file():
        return set(), [Finding("warn", f"{code}-malformed", "agent run retirement summary is not a regular file", AGENT_RUN_RETIREMENT_SUMMARY_REL)]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return set(), [Finding("warn", f"{code}-malformed", f"agent run retirement summary could not be read: {exc}", AGENT_RUN_RETIREMENT_SUMMARY_REL)]
    frontmatter = parse_frontmatter(text)

    findings: list[Finding] = []
    if not frontmatter.has_frontmatter:
        return set(), [Finding("warn", f"{code}-malformed", "agent run retirement summary is missing frontmatter", AGENT_RUN_RETIREMENT_SUMMARY_REL)]
    for error in frontmatter.errors:
        findings.append(Finding("warn", f"{code}-malformed", error, AGENT_RUN_RETIREMENT_SUMMARY_REL))
    if findings:
        return set(), findings

    entries = _frontmatter_string_list(frontmatter.data.get("retired_agent_run_records"))
    if not entries:
        payload_data, payload_findings = _agent_run_intake_payload_frontmatter_data(text, code)
        findings.extend(payload_findings)
        entries = _frontmatter_string_list(payload_data.get("retired_agent_run_records"))

    retired: set[str] = set()
    for entry in entries:
        rel_path = entry.replace("\\", "/").strip()
        if rel_path.startswith("./"):
            rel_path = rel_path[2:]
        conflict = _root_relative_path_conflict(rel_path)
        if conflict:
            findings.append(Finding("warn", f"{code}-malformed", f"retired agent-run record path {conflict}: {entry}", AGENT_RUN_RETIREMENT_SUMMARY_REL))
            continue
        if not rel_path.startswith(AGENT_RUN_RECORD_PREFIX) or not rel_path.endswith(".md"):
            findings.append(
                Finding(
                    "warn",
                    f"{code}-malformed",
                    f"retired agent-run record must be under {AGENT_RUN_RECORD_PREFIX}*.md: {entry}",
                    AGENT_RUN_RETIREMENT_SUMMARY_REL,
                )
            )
            continue
        retired.add(rel_path)
    if retired:
        findings.append(
            Finding(
                "info",
                f"{code}-summary",
                (
                    f"{len(retired)} exact agent run record(s) retired from active agent-run validation checks by "
                    f"{AGENT_RUN_RETIREMENT_SUMMARY_REL}; malformed retirement entries remain warning-level, "
                    "future unlisted records remain in active validation scope, and no source hashes were refreshed"
                ),
                AGENT_RUN_RETIREMENT_SUMMARY_REL,
            )
        )
    return retired, findings


def _agent_run_intake_payload_frontmatter_data(text: str, code: str) -> tuple[dict[str, object], list[Finding]]:
    marker_index = text.find("## Intake Payload Frontmatter")
    if marker_index < 0:
        return {}, []
    fence_index = text.find("```yaml", marker_index)
    if fence_index < 0:
        return {}, [Finding("warn", f"{code}-malformed", "intake payload frontmatter block is missing a yaml fence", AGENT_RUN_RETIREMENT_SUMMARY_REL)]
    yaml_start = text.find("\n", fence_index)
    if yaml_start < 0:
        return {}, [Finding("warn", f"{code}-malformed", "intake payload frontmatter block is malformed", AGENT_RUN_RETIREMENT_SUMMARY_REL)]
    yaml_end = text.find("```", yaml_start + 1)
    if yaml_end < 0:
        return {}, [Finding("warn", f"{code}-malformed", "intake payload frontmatter block is missing a closing fence", AGENT_RUN_RETIREMENT_SUMMARY_REL)]

    payload = parse_frontmatter(f"---\n{text[yaml_start + 1:yaml_end].strip()}\n---\n")
    findings = [Finding("warn", f"{code}-malformed", error, AGENT_RUN_RETIREMENT_SUMMARY_REL) for error in payload.errors]
    if findings:
        return {}, findings
    return payload.data, []


def _worker_run_receipt_paths(root: Path) -> list[Path]:
    directory = root / WORKER_RUN_RECEIPTS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def _checkpoint_package_receipt_paths(root: Path) -> list[Path]:
    directory = root / CHECKPOINT_PACKAGE_RECEIPTS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def _coordination_record_paths(root: Path) -> list[Path]:
    records: list[Path] = []
    for directory_rel in COORDINATION_RECORD_DIRS:
        directory = root / directory_rel
        if not directory.exists() or not directory.is_dir():
            continue
        records.extend(path for path in directory.iterdir() if path.is_file() and path.suffix == ".json")
    return sorted(records)


def _evidence_ref_retarget_request_findings(
    inventory: Inventory,
    request: EvidenceRefRetargetRequest,
    severity: str,
) -> list[Finding]:
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                severity,
                "evidence-ref-retarget-refused",
                "evidence reference retarget is live-root only; product fixtures and archive roots remain read-only context",
            )
        )
    if not request.target:
        findings.append(Finding(severity, "evidence-ref-retarget-refused", "--target is required for evidence ref retarget"))
    if not request.old_ref:
        findings.append(Finding(severity, "evidence-ref-retarget-refused", "--old-ref is required for evidence ref retarget"))
    if not request.new_ref:
        findings.append(Finding(severity, "evidence-ref-retarget-refused", "--new-ref is required for evidence ref retarget"))
    if not request.target or not request.old_ref or not request.new_ref:
        return findings
    findings.extend(_evidence_ref_retarget_target_findings(inventory.root, request.target, severity))
    findings.extend(_evidence_ref_retarget_ref_findings(inventory.root, request.old_ref, request.new_ref, severity))
    return findings


def _evidence_ref_retarget_target_findings(root: Path, target_rel: str, severity: str) -> list[Finding]:
    findings: list[Finding] = []
    conflict = _root_relative_path_conflict(target_rel)
    if conflict:
        return [Finding(severity, "evidence-ref-retarget-refused", f"target {conflict}", target_rel)]
    target_kind = _evidence_ref_retarget_target_kind(target_rel)
    if target_kind == "":
        return [
            Finding(
                severity,
                "evidence-ref-retarget-refused",
                (
                    f"target must be an existing {AGENT_RUN_RECORD_PREFIX}*.md record "
                    f"or JSON under {', '.join(prefix + '*.json' for prefix in EVIDENCE_REF_RETARGET_JSON_TARGET_PREFIXES)}"
                ),
                target_rel,
            )
        ]
    target = (root / target_rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return [Finding(severity, "evidence-ref-retarget-refused", "target escapes the target root", target_rel)]
    parent = root.resolve()
    for part in Path(target_rel).parts[:-1]:
        parent = parent / part
        if parent.is_symlink():
            findings.append(Finding(severity, "evidence-ref-retarget-refused", f"target directory contains a symlink segment: {_to_rel_path(root, parent)}", target_rel))
            break
        if parent.exists() and not parent.is_dir():
            findings.append(Finding(severity, "evidence-ref-retarget-refused", f"target directory contains a non-directory segment: {_to_rel_path(root, parent)}", target_rel))
            break
    if not target.exists():
        findings.append(Finding(severity, "evidence-ref-retarget-refused", "target does not exist; retarget only maintains existing evidence records", target_rel))
    elif target.is_symlink():
        findings.append(Finding(severity, "evidence-ref-retarget-refused", "target must not be a symlink", target_rel))
    elif not target.is_file():
        findings.append(Finding(severity, "evidence-ref-retarget-refused", "target is not a regular file", target_rel))
    return findings


def _evidence_ref_retarget_ref_findings(root: Path, old_ref: str, new_ref: str, severity: str) -> list[Finding]:
    findings: list[Finding] = []
    for label, rel_path in (("--old-ref", old_ref), ("--new-ref", new_ref)):
        conflict = _root_relative_path_conflict(rel_path)
        if conflict:
            findings.append(Finding(severity, "evidence-ref-retarget-refused", f"{label} {conflict}", rel_path))
    if findings:
        return findings
    if _same_root_relative_path(old_ref, new_ref):
        findings.append(Finding(severity, "evidence-ref-retarget-refused", "--old-ref and --new-ref must point at different root-relative refs", old_ref))
        return findings
    new_path = root / new_ref
    boundary_violation = source_path_boundary_violation(root, new_path, label="new evidence retarget ref")
    if boundary_violation is not None:
        findings.append(Finding(severity, "evidence-ref-retarget-refused", boundary_violation.message, new_ref))
    elif not new_path.exists():
        findings.append(Finding(severity, "evidence-ref-retarget-refused", "--new-ref must exist before retargeting evidence", new_ref))
    elif not new_path.is_file():
        findings.append(Finding(severity, "evidence-ref-retarget-refused", "--new-ref must be a regular file", new_ref))
    return findings


def _evidence_ref_retarget_target_kind(target_rel: str) -> str:
    if target_rel.startswith(AGENT_RUN_RECORD_PREFIX) and target_rel.endswith(".md"):
        return "agent-run"
    if target_rel.endswith(".json") and any(target_rel.startswith(prefix) for prefix in EVIDENCE_REF_RETARGET_JSON_TARGET_PREFIXES):
        return "json"
    return ""


def _evidence_ref_retarget_plan(
    root: Path,
    request: EvidenceRefRetargetRequest,
    severity: str,
) -> tuple[EvidenceRefRetargetPlan | None, list[Finding]]:
    target_kind = _evidence_ref_retarget_target_kind(request.target)
    if target_kind == "agent-run":
        return _agent_run_record_ref_retarget_plan(root, request, severity)
    if target_kind == "json":
        return _json_evidence_ref_retarget_plan(root, request, severity)
    return None, [Finding(severity, "evidence-ref-retarget-refused", "target is outside the evidence ref retarget route scope", request.target)]


def _agent_run_record_ref_retarget_plan(
    root: Path,
    request: EvidenceRefRetargetRequest,
    severity: str,
) -> tuple[EvidenceRefRetargetPlan | None, list[Finding]]:
    target = root / request.target
    try:
        current_text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding(severity, "evidence-ref-retarget-refused", f"agent run record could not be read before evidence ref retarget: {exc}", request.target)]

    frontmatter = parse_frontmatter(current_text)
    data = frontmatter.data
    if not frontmatter.has_frontmatter:
        return None, [Finding(severity, "evidence-ref-retarget-refused", "agent run record is missing frontmatter; retarget refuses to guess metadata boundaries", request.target)]
    if frontmatter.errors:
        return None, [Finding(severity, "evidence-ref-retarget-refused", "agent run record has malformed frontmatter; retarget refuses to guess metadata boundaries", request.target)]
    if data.get("schema") != AGENT_RUN_SCHEMA:
        return None, [Finding(severity, "evidence-ref-retarget-refused", f"agent run record schema should be {AGENT_RUN_SCHEMA}", request.target)]
    if data.get("record_type") != "agent-run":
        return None, [Finding(severity, "evidence-ref-retarget-refused", "agent run record record_type should be agent-run", request.target)]
    record_id = str(data.get("record_id") or "").strip()
    expected_record_id = Path(request.target).stem
    if record_id_conflict(record_id):
        return None, [Finding(severity, "evidence-ref-retarget-refused", f"agent run record_id {record_id!r} is unsafe: {record_id_conflict(record_id)}", request.target)]
    if record_id != expected_record_id:
        return None, [Finding(severity, "evidence-ref-retarget-refused", f"agent run record_id {record_id!r} does not match route target {expected_record_id!r}", request.target)]

    retargeted_text, replacement_count = _retarget_agent_run_record_refs(current_text, data, request.old_ref, request.new_ref)
    source_hashes: tuple[str, ...] = ()
    findings = [
        Finding(
            "info",
            "evidence-ref-retarget-target",
            f"retarget evidence refs in existing agent run record: {request.target}",
            request.target,
        )
    ]
    if replacement_count:
        updated_frontmatter = parse_frontmatter(retargeted_text)
        source_refs_with_self = _record_source_refs(updated_frontmatter.data)
        source_refs = tuple(ref for ref in source_refs_with_self if not _same_root_relative_path(ref, request.target))
        if not source_refs:
            return None, [
                *findings,
                Finding(
                    severity,
                    "evidence-ref-retarget-refused",
                    f"agent run record has no source-bound refs to refresh after excluding its own target {request.target}",
                    request.target,
                ),
            ]
        refreshed_hashes, hash_findings = _source_hash_entries_for_refs(root, source_refs, code_prefix="evidence-ref-retarget")
        source_hashes = tuple(refreshed_hashes)
        findings.extend(hash_findings)
        retargeted_text = _replace_agent_run_source_hashes(retargeted_text, source_hashes)
    current_hash = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
    proposal_token = _evidence_ref_retarget_token(request.target, current_hash, request.old_ref, request.new_ref, retargeted_text, source_hashes)
    return (
        EvidenceRefRetargetPlan(
            rel_path=request.target,
            current_text=current_text,
            updated_text=retargeted_text,
            replacement_count=replacement_count,
            source_hashes=source_hashes,
            current_target_hash=current_hash,
            proposal_token=proposal_token,
            target_kind="agent-run",
        ),
        findings,
    )


def _json_evidence_ref_retarget_plan(
    root: Path,
    request: EvidenceRefRetargetRequest,
    severity: str,
) -> tuple[EvidenceRefRetargetPlan | None, list[Finding]]:
    target = root / request.target
    try:
        current_text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding(severity, "evidence-ref-retarget-refused", f"JSON evidence record could not be read before ref retarget: {exc}", request.target)]
    try:
        payload = json.loads(current_text)
    except json.JSONDecodeError as exc:
        return None, [Finding(severity, "evidence-ref-retarget-refused", f"JSON evidence record is malformed: {exc.msg}", request.target)]
    if not isinstance(payload, dict):
        return None, [Finding(severity, "evidence-ref-retarget-refused", "JSON evidence record must be an object", request.target)]

    findings = [
        Finding(
            "info",
            "evidence-ref-retarget-target",
            f"retarget evidence refs in existing JSON coordination record: {request.target}",
            request.target,
        )
    ]
    findings.extend(_json_evidence_ref_retarget_shape_findings(request.target, payload, severity))
    findings.extend(_json_evidence_ref_retarget_authority_findings(request.target, payload, severity))
    if any(finding.severity in {"warn", "error"} for finding in findings):
        return None, findings

    updated_payload, replacement_count = _retarget_json_ref_values(payload, request.old_ref, request.new_ref)
    source_hashes: tuple[str, ...] = ()
    if replacement_count and request.target.startswith(f"{WORKER_RUN_RECEIPTS_DIR_REL}/"):
        payload_findings = _worker_run_receipt_refresh_payload_findings(root, request.target, updated_payload, severity)
        findings.extend(payload_findings)
        if any(finding.severity in {"warn", "error"} for finding in payload_findings):
            return None, findings
        source_refs, source_ref_findings = _worker_run_receipt_refresh_source_refs(request.target, updated_payload, severity)
        findings.extend(source_ref_findings)
        if any(finding.severity in {"warn", "error"} for finding in source_ref_findings):
            return None, findings
        refreshed_hashes, hash_findings = _source_hash_entries_for_refs(root, source_refs, code_prefix="evidence-ref-retarget")
        findings.extend(hash_findings)
        if any(finding.severity == "warn" for finding in hash_findings):
            findings.append(
                Finding(
                    severity,
                    "evidence-ref-retarget-refused",
                    "source_hash refs must resolve to missing or readable regular files before a protected ref retarget is written",
                    request.target,
                )
            )
            return None, findings
        source_hashes = tuple(refreshed_hashes)
        updated_payload = dict(updated_payload)
        updated_payload["source_hashes"] = list(source_hashes)
    updated_text = current_text if replacement_count == 0 else json.dumps(updated_payload, indent=2) + "\n"
    current_hash = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
    proposal_token = _evidence_ref_retarget_token(request.target, current_hash, request.old_ref, request.new_ref, updated_text, source_hashes)
    return (
        EvidenceRefRetargetPlan(
            rel_path=request.target,
            current_text=current_text,
            updated_text=updated_text,
            replacement_count=replacement_count,
            source_hashes=source_hashes,
            current_target_hash=current_hash,
            proposal_token=proposal_token,
            target_kind="json",
        ),
        findings,
    )


def _json_evidence_ref_retarget_shape_findings(target_rel: str, data: dict[str, object], severity: str) -> list[Finding]:
    expectations: tuple[str, str] | None = None
    if target_rel.startswith("project/verification/handoffs/"):
        expectations = ("mylittleharness.handoff-packet.v1", "handoff-packet")
    elif target_rel.startswith("project/verification/work-claims/"):
        expectations = ("mylittleharness.work-claim.v1", "work-claim")
    elif target_rel.startswith(f"{WORKER_RUN_RECEIPTS_DIR_REL}/"):
        expectations = (WORKER_RUN_RECEIPT_SCHEMA, "worker-run-receipt")
    if expectations is None:
        return []
    expected_schema, expected_record_type = expectations
    findings: list[Finding] = []
    if data.get("schema") != expected_schema:
        findings.append(Finding(severity, "evidence-ref-retarget-refused", f"JSON evidence record schema should be {expected_schema}", target_rel))
    if data.get("record_type") != expected_record_type:
        findings.append(Finding(severity, "evidence-ref-retarget-refused", f"JSON evidence record record_type should be {expected_record_type}", target_rel))
    return findings


def _json_evidence_ref_retarget_authority_findings(target_rel: str, data: object, severity: str) -> list[Finding]:
    findings: list[Finding] = []

    def walk(value: object, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = str(key or "").strip()
                if normalized_key in {
                    "approves_lifecycle",
                    "approves_archive",
                    "approves_commit",
                    "approves_release",
                    "external_tracker_status_authoritative",
                } and _json_truthy(child):
                    dotted = ".".join((*path, normalized_key))
                    findings.append(Finding(severity, "evidence-ref-retarget-refused", f"{dotted} must remain false; evidence ref retarget cannot carry authority overclaims", target_rel))
                walk(child, (*path, normalized_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, path)

    walk(data, ())
    return findings


def _retarget_json_ref_values(value: object, old_ref: str, new_ref: str, active_key: str | None = None) -> tuple[object, int]:
    if isinstance(value, dict):
        changed: dict[str, object] = {}
        count = 0
        for key, child in value.items():
            child_value, child_count = _retarget_json_ref_values(child, old_ref, new_ref, str(key))
            changed[key] = child_value
            count += child_count
        return changed, count
    if isinstance(value, list):
        changed_items: list[object] = []
        count = 0
        for child in value:
            child_value, child_count = _retarget_json_ref_values(child, old_ref, new_ref, active_key)
            changed_items.append(child_value)
            count += child_count
        return changed_items, count
    if isinstance(value, str) and active_key in EVIDENCE_REF_RETARGET_JSON_REF_KEYS:
        retargeted, count = _retarget_ref_string(value, old_ref, new_ref, allow_source_hash=active_key == "source_hashes")
        return retargeted, count
    return value, 0


def _retarget_agent_run_record_refs(text: str, data: dict[str, object], old_ref: str, new_ref: str) -> tuple[str, int]:
    updated_text = text
    replacement_count = 0
    for field in EVIDENCE_REF_RETARGET_AGENT_RUN_FIELDS:
        values = _frontmatter_string_list(data.get(field))
        if not values:
            continue
        new_values: list[str] = []
        changed = False
        for value in values:
            if _same_root_relative_path(value, old_ref):
                new_values.append(new_ref)
                changed = True
                replacement_count += 1
            else:
                new_values.append(value)
        if changed:
            updated_text = _replace_frontmatter_list(updated_text, field, tuple(new_values))
    updated_lines: list[str] = []
    for line in updated_text.splitlines():
        replacement = line
        for template in ("- `{}`", "- handoff: `{}`", "- claim: `{}`"):
            if line == template.format(old_ref):
                replacement = template.format(new_ref)
                replacement_count += 1
                break
        updated_lines.append(replacement)
    updated_text = _join_preserving_trailing_newline(updated_lines, updated_text)
    return updated_text, replacement_count


def _retarget_ref_string(value: str, old_ref: str, new_ref: str, *, allow_source_hash: bool) -> tuple[str, int]:
    normalized = value.replace("\\", "/").strip()
    if _same_root_relative_path(normalized, old_ref):
        return new_ref, 1
    if allow_source_hash:
        match = SOURCE_HASH_RE.match(normalized)
        if match and _same_root_relative_path(match.group(1).strip(), old_ref):
            suffix = normalized[match.end(1) :]
            return f"{new_ref}{suffix}", 1
    return value, 0


def _json_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "1", "authoritative", "approved"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _evidence_ref_retarget_token(target_rel: str, current_hash: str, old_ref: str, new_ref: str, updated_text: str, source_hashes: tuple[str, ...]) -> str:
    payload = "\n".join((target_rel, current_hash, old_ref, new_ref, hashlib.sha256(updated_text.encode("utf-8")).hexdigest(), *source_hashes))
    return f"{EVIDENCE_REF_RETARGET_TOKEN_PREFIX}{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _evidence_ref_retarget_route_findings(plan: EvidenceRefRetargetPlan, request: EvidenceRefRetargetRequest, *, apply: bool) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "evidence-ref-retarget-token",
            (
                f"current target sha256={plan.current_target_hash}; proposal_token={plan.proposal_token}; "
                f"apply with: mylittleharness --root <root> evidence --retarget-ref --apply --target {plan.rel_path} "
                f"--old-ref {request.old_ref} --new-ref {request.new_ref} --proposal-token {plan.proposal_token}"
            ),
            plan.rel_path,
        )
    ]
    if plan.replacement_count == 0 or plan.current_text == plan.updated_text:
        findings.append(
            Finding(
                "info",
                "evidence-ref-retarget-current",
                f"old ref was not present in scoped provenance fields for {plan.rel_path}; no route write is needed",
                plan.rel_path,
            )
        )
        return findings
    before_hash = _short_hash(plan.current_text)
    after_hash = _short_hash(plan.updated_text)
    before_bytes = len(plan.current_text.encode("utf-8"))
    after_bytes = len(plan.updated_text.encode("utf-8"))
    prefix = "retargeted" if apply else "would retarget"
    findings.extend(
        [
            Finding(
                "info",
                "evidence-ref-retargeted" if apply else "evidence-ref-retarget-dry-run",
                f"{prefix} {plan.replacement_count} scoped provenance ref(s) in existing {plan.target_kind} evidence target: {plan.rel_path}",
                plan.rel_path,
            ),
            Finding(
                "info",
                "evidence-ref-retarget-route-write",
                f"{prefix} route {plan.rel_path}; before_hash={before_hash}; after_hash={after_hash}; before_bytes={before_bytes}; after_bytes={after_bytes}; source-bound write evidence is independent of Git tracking",
                plan.rel_path,
            ),
        ]
    )
    if plan.source_hashes:
        findings.append(
            Finding(
                "info",
                "evidence-ref-retarget-source-hashes",
                f"refreshed {len(plan.source_hashes)} source_hash entry/entries after retargeting provenance refs",
                plan.rel_path,
            )
        )
    return findings


def _evidence_ref_retarget_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "evidence-ref-retarget-boundary",
            "evidence ref retarget updates only scoped provenance refs and refreshed source_hashes in existing route-owned evidence; it cannot approve lifecycle, archive, roadmap status, provider routing, staging, commit, or acceptance",
            "project/verification",
        ),
        Finding(
            "info",
            "evidence-ref-retarget-route",
            "evidence ref retarget is limited to existing agent-run Markdown plus handoff, work-claim, and worker-run receipt JSON records; it creates no runtime, queue, database, cache, adapter state, or provider gateway",
            "project/verification",
        ),
    ]


def _queue_runner_fixture_update_request_findings(
    inventory: Inventory,
    request: QueueRunnerFixtureUpdateRequest,
    severity: str,
) -> list[Finding]:
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                severity,
                "queue-runner-fixture-update-refused",
                "queue-runner fixture update is live-root only; product fixtures and archive roots remain read-only context",
            )
        )
    if not request.target:
        findings.append(Finding(severity, "queue-runner-fixture-update-refused", "--target is required for queue-runner fixture update"))
    if not str(request.text or "").strip():
        findings.append(Finding(severity, "queue-runner-fixture-update-refused", "--text or --text-file must provide reviewed fixture content"))
    if not request.target or not str(request.text or "").strip():
        return findings
    findings.extend(_queue_runner_fixture_update_target_findings(inventory.root, request.target, severity))
    findings.extend(_queue_runner_fixture_update_content_findings(request.target, request.text, severity))
    return findings


def _queue_runner_fixture_update_target_findings(root: Path, target_rel: str, severity: str) -> list[Finding]:
    findings: list[Finding] = []
    conflict = _root_relative_path_conflict(target_rel)
    if conflict:
        return [Finding(severity, "queue-runner-fixture-update-refused", f"target {conflict}", target_rel)]
    prefix = f"{QUEUE_RUNNER_FIXTURES_DIR_REL}/"
    if not target_rel.startswith(prefix) or not target_rel.endswith(".txt"):
        return [
            Finding(
                severity,
                "queue-runner-fixture-update-refused",
                f"target must be an existing {QUEUE_RUNNER_FIXTURES_DIR_REL}/*.txt fixture",
                target_rel,
            )
        ]
    target = (root / target_rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return [Finding(severity, "queue-runner-fixture-update-refused", "target escapes the target root", target_rel)]
    parent = root.resolve()
    for part in Path(target_rel).parts[:-1]:
        parent = parent / part
        if parent.is_symlink():
            findings.append(Finding(severity, "queue-runner-fixture-update-refused", f"target directory contains a symlink segment: {_to_rel_path(root, parent)}", target_rel))
            break
        if parent.exists() and not parent.is_dir():
            findings.append(Finding(severity, "queue-runner-fixture-update-refused", f"target directory contains a non-directory segment: {_to_rel_path(root, parent)}", target_rel))
            break
    if not target.exists():
        findings.append(Finding(severity, "queue-runner-fixture-update-refused", "target does not exist; fixture update only maintains existing queue-runner proof files", target_rel))
    elif target.is_symlink():
        findings.append(Finding(severity, "queue-runner-fixture-update-refused", "target must not be a symlink", target_rel))
    elif not target.is_file():
        findings.append(Finding(severity, "queue-runner-fixture-update-refused", "target is not a regular file", target_rel))
    return findings


def _queue_runner_fixture_update_content_findings(target_rel: str, text: str, severity: str) -> list[Finding]:
    findings: list[Finding] = []
    if "\x00" in text:
        findings.append(Finding(severity, "queue-runner-fixture-update-refused", "fixture text must be UTF-8 text without NUL bytes", target_rel))
    content = text.casefold()
    has_safety_boundary = "no secrets" in content and "raw provider payload" in content
    has_explicit_proof = ("queue runner" in content or "queue-runner" in content) and "proof" in content
    has_scoped_write_smoke = "smoke fixture" in content and "live scoped writer" in content and "applied write" in content
    if not has_safety_boundary:
        findings.append(
            Finding(
                severity,
                "queue-runner-fixture-update-refused",
                "fixture text must explicitly state the no-secrets and raw provider payload safety boundary",
                target_rel,
            )
        )
    if not (has_explicit_proof or has_scoped_write_smoke):
        findings.append(
            Finding(
                severity,
                "queue-runner-fixture-update-refused",
                "fixture text must be reviewed queue-runner proof or an accepted live scoped-writer smoke fixture",
                target_rel,
            )
        )
    return findings


def _queue_runner_fixture_update_plan(
    root: Path,
    request: QueueRunnerFixtureUpdateRequest,
    severity: str,
) -> tuple[QueueRunnerFixtureUpdatePlan | None, list[Finding]]:
    target = root / request.target
    try:
        current_text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [Finding(severity, "queue-runner-fixture-update-refused", f"queue-runner fixture could not be read before update: {exc}", request.target)]
    updated_text = request.text.replace("\r\n", "\n").replace("\r", "\n")
    if not updated_text.endswith("\n"):
        updated_text += "\n"
    current_hash = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
    proposal_token = _queue_runner_fixture_update_token(request.target, current_hash, updated_text)
    return (
        QueueRunnerFixtureUpdatePlan(
            rel_path=request.target,
            current_text=current_text,
            updated_text=updated_text,
            current_target_hash=current_hash,
            proposal_token=proposal_token,
        ),
        [
            Finding(
                "info",
                "queue-runner-fixture-update-target",
                f"update existing queue-runner fixture text: {request.target}",
                request.target,
            )
        ],
    )


def _queue_runner_fixture_update_token(target_rel: str, current_hash: str, updated_text: str) -> str:
    payload = "\n".join((target_rel, current_hash, hashlib.sha256(updated_text.encode("utf-8")).hexdigest()))
    return f"{QUEUE_RUNNER_FIXTURE_UPDATE_TOKEN_PREFIX}{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _queue_runner_fixture_update_route_findings(plan: QueueRunnerFixtureUpdatePlan, *, apply: bool) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "queue-runner-fixture-update-token",
            (
                f"current target sha256={plan.current_target_hash}; proposal_token={plan.proposal_token}; "
                f"apply with: mylittleharness --root <root> evidence --fixture-update --apply --target {plan.rel_path} "
                f"--text-file <reviewed-fixture-text-or-stdin> --proposal-token {plan.proposal_token}"
            ),
            plan.rel_path,
        )
    ]
    if plan.current_text == plan.updated_text:
        findings.append(
            Finding(
                "info",
                "queue-runner-fixture-update-current",
                f"queue-runner fixture {plan.rel_path} already matches reviewed text; no route write is needed",
                plan.rel_path,
            )
        )
        return findings
    before_hash = _short_hash(plan.current_text)
    after_hash = _short_hash(plan.updated_text)
    before_bytes = len(plan.current_text.encode("utf-8"))
    after_bytes = len(plan.updated_text.encode("utf-8"))
    prefix = "updated" if apply else "would update"
    findings.extend(
        [
            Finding(
                "info",
                "queue-runner-fixture-updated" if apply else "queue-runner-fixture-update-dry-run",
                f"{prefix} existing queue-runner fixture text: {plan.rel_path}",
                plan.rel_path,
            ),
            Finding(
                "info",
                "queue-runner-fixture-update-route-write",
                f"{prefix} route {plan.rel_path}; before_hash={before_hash}; after_hash={after_hash}; before_bytes={before_bytes}; after_bytes={after_bytes}; source-bound write evidence is independent of Git tracking",
                plan.rel_path,
            ),
        ]
    )
    return findings


def _queue_runner_fixture_update_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "queue-runner-fixture-update-boundary",
            "queue-runner fixture update maintains only one existing route-owned fixture text file; it cannot approve lifecycle, archive, roadmap status, provider routing, staging, commit, or acceptance",
            QUEUE_RUNNER_FIXTURES_DIR_REL,
        ),
        Finding(
            "info",
            "queue-runner-fixture-update-route",
            f"queue-runner fixture update is limited to existing {QUEUE_RUNNER_FIXTURES_DIR_REL}/*.txt proof files and creates no runtime, queue, provider gateway, secret store, raw payload, or hidden state",
            QUEUE_RUNNER_FIXTURES_DIR_REL,
        ),
    ]


def _worker_run_receipt_refresh_request_findings(
    inventory: Inventory,
    request: WorkerRunReceiptRefreshRequest,
    severity: str,
) -> list[Finding]:
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                severity,
                "worker-run-receipt-refresh-refused",
                "worker run receipt refresh is live-root only; product fixtures and archive roots remain read-only context",
            )
        )
    if not request.target:
        findings.append(Finding(severity, "worker-run-receipt-refresh-refused", "--target is required for receipt refresh"))
        return findings
    findings.extend(_worker_run_receipt_refresh_target_findings(inventory.root, request.target, severity))
    return findings


def _worker_run_receipt_refresh_target_findings(root: Path, target_rel: str, severity: str) -> list[Finding]:
    findings: list[Finding] = []
    conflict = _root_relative_path_conflict(target_rel)
    if conflict:
        return [Finding(severity, "worker-run-receipt-refresh-refused", f"receipt target {conflict}", target_rel)]
    if not target_rel.startswith(f"{WORKER_RUN_RECEIPTS_DIR_REL}/") or not target_rel.endswith(".json"):
        return [
            Finding(
                severity,
                "worker-run-receipt-refresh-refused",
                f"receipt target must be under {WORKER_RUN_RECEIPTS_DIR_REL}/*.json",
                target_rel,
            )
        ]
    target = (root / target_rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return [Finding(severity, "worker-run-receipt-refresh-refused", "receipt target escapes the target root", target_rel)]
    parent = root.resolve()
    for part in Path(target_rel).parts[:-1]:
        parent = parent / part
        if parent.is_symlink():
            findings.append(Finding(severity, "worker-run-receipt-refresh-refused", f"receipt target directory contains a symlink segment: {_to_rel_path(root, parent)}", target_rel))
            break
        if parent.exists() and not parent.is_dir():
            findings.append(Finding(severity, "worker-run-receipt-refresh-refused", f"receipt target directory contains a non-directory segment: {_to_rel_path(root, parent)}", target_rel))
            break
    if not target.exists():
        findings.append(Finding(severity, "worker-run-receipt-refresh-refused", "receipt target does not exist; refresh only maintains existing worker run receipts", target_rel))
    elif target.is_symlink():
        findings.append(Finding(severity, "worker-run-receipt-refresh-refused", "receipt target must not be a symlink", target_rel))
    elif not target.is_file():
        findings.append(Finding(severity, "worker-run-receipt-refresh-refused", "receipt target is not a regular file", target_rel))
    return findings


def _worker_run_receipt_refresh_plan(
    root: Path,
    target_rel: str,
    severity: str,
) -> tuple[WorkerRunReceiptRefreshPlan | None, list[Finding]]:
    target = root / target_rel
    try:
        current_text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding(severity, "worker-run-receipt-refresh-refused", f"worker run receipt could not be read before source-hash refresh: {exc}", target_rel)]

    try:
        payload = json.loads(current_text)
    except json.JSONDecodeError as exc:
        return None, [Finding(severity, "worker-run-receipt-refresh-refused", f"worker run receipt JSON is malformed: {exc.msg}", target_rel)]
    if not isinstance(payload, dict):
        return None, [Finding(severity, "worker-run-receipt-refresh-refused", "worker run receipt JSON must be an object", target_rel)]

    findings = [
        Finding(
            "info",
            "worker-run-receipt-refresh-target",
            f"refresh source_hashes for existing worker run receipt: {target_rel}",
            target_rel,
        )
    ]
    payload_findings = _worker_run_receipt_refresh_payload_findings(root, target_rel, payload, severity)
    findings.extend(payload_findings)
    if any(finding.severity in {"warn", "error"} for finding in payload_findings):
        return None, findings

    source_refs, source_ref_findings = _worker_run_receipt_refresh_source_refs(target_rel, payload, severity)
    findings.extend(source_ref_findings)
    if any(finding.severity in {"warn", "error"} for finding in source_ref_findings):
        return None, findings

    source_hashes, hash_findings = _source_hash_entries_for_refs(root, source_refs, code_prefix="worker-run-receipt-refresh")
    findings.extend(hash_findings)
    if any(finding.severity == "warn" for finding in hash_findings):
        findings.append(
            Finding(
                severity,
                "worker-run-receipt-refresh-refused",
                "source_hash refs must resolve to missing or readable regular files before a protected receipt refresh is written",
                target_rel,
            )
        )
        return None, findings

    current_hash = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
    old_source_hashes = tuple(_frontmatter_string_list(payload.get("source_hashes")))
    if old_source_hashes == tuple(source_hashes):
        updated_text = current_text
    else:
        updated_payload = dict(payload)
        updated_payload["source_hashes"] = list(source_hashes)
        updated_text = json.dumps(updated_payload, indent=2) + "\n"
    proposal_token = _worker_run_receipt_refresh_token(target_rel, current_hash, tuple(source_hashes))
    return (
        WorkerRunReceiptRefreshPlan(
            rel_path=target_rel,
            current_text=current_text,
            updated_text=updated_text,
            source_hashes=tuple(source_hashes),
            current_receipt_hash=current_hash,
            proposal_token=proposal_token,
        ),
        findings,
    )


def _worker_run_receipt_refresh_payload_findings(
    root: Path,
    target_rel: str,
    data: dict[str, object],
    severity: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for field in WORKER_RUN_RECEIPT_REQUIRED_SCALARS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            findings.append(Finding(severity, "worker-run-receipt-refresh-refused", f"worker run receipt missing required field: {field}", target_rel))
    for field in WORKER_RUN_RECEIPT_REQUIRED_LISTS:
        if not _frontmatter_string_list(data.get(field)):
            findings.append(Finding(severity, "worker-run-receipt-refresh-refused", f"worker run receipt missing required list field: {field}", target_rel))
    if data.get("schema") != WORKER_RUN_RECEIPT_SCHEMA:
        findings.append(Finding(severity, "worker-run-receipt-refresh-refused", f"worker run receipt schema should be {WORKER_RUN_RECEIPT_SCHEMA}", target_rel))
    if data.get("record_type") != "worker-run-receipt":
        findings.append(Finding(severity, "worker-run-receipt-refresh-refused", "worker run receipt record_type should be worker-run-receipt", target_rel))

    receipt_id = str(data.get("receipt_id") or "").strip()
    expected_receipt_id = Path(target_rel).stem
    if record_id_conflict(receipt_id):
        findings.append(Finding(severity, "worker-run-receipt-refresh-refused", f"worker run receipt receipt_id {receipt_id!r} is unsafe: {record_id_conflict(receipt_id)}", target_rel))
    elif receipt_id and receipt_id != expected_receipt_id:
        findings.append(Finding(severity, "worker-run-receipt-refresh-refused", f"worker run receipt receipt_id {receipt_id!r} does not match route target {expected_receipt_id!r}", target_rel))

    for finding in _worker_run_receipt_non_authority_findings(target_rel, data, "worker-run-receipt-refresh"):
        findings.append(Finding(severity, "worker-run-receipt-refresh-refused", finding.message, target_rel))

    for field in ("task_input_refs", "event_stream_refs", "output_refs", "verification_refs"):
        for value in _frontmatter_string_list(data.get(field)):
            conflict = _root_relative_path_conflict(value)
            if conflict:
                findings.append(Finding(severity, "worker-run-receipt-refresh-refused", f"worker run receipt {field} path {conflict}: {value}", target_rel))
                continue
            boundary_violation = source_path_boundary_violation(root, root / value, label=f"worker run receipt {field}")
            if boundary_violation is not None:
                findings.append(Finding(severity, "worker-run-receipt-refresh-refused", boundary_violation.message, target_rel))
    return findings


def _worker_run_receipt_refresh_source_refs(
    target_rel: str,
    data: dict[str, object],
    severity: str,
) -> tuple[tuple[str, ...], list[Finding]]:
    findings: list[Finding] = []
    refs: list[str] = []
    seen: set[str] = set()
    self_refs: list[str] = []
    for entry in _frontmatter_string_list(data.get("source_hashes")):
        match = SOURCE_HASH_RE.match(entry.strip())
        if not match:
            findings.append(Finding(severity, "worker-run-receipt-refresh-refused", f"malformed source_hashes entry: {entry}", target_rel))
            continue
        source_rel = match.group(1).replace("\\", "/").strip()
        if _same_root_relative_path(source_rel, target_rel):
            self_refs.append(source_rel)
            continue
        conflict = _root_relative_path_conflict(source_rel)
        if conflict:
            findings.append(Finding(severity, "worker-run-receipt-refresh-refused", f"source hash path {conflict}: {source_rel}", target_rel))
            continue
        if any(source_rel.casefold().startswith(prefix) for prefix in CHECKPOINT_PACKAGE_RECEIPT_PROHIBITED_INCLUDED_PREFIXES):
            findings.append(
                Finding(
                    severity,
                    "worker-run-receipt-refresh-refused",
                    f"source hash path must not target generated, cache, private, secret, temp, runtime, or VCS files: {source_rel}",
                    target_rel,
                )
            )
            continue
        key = _root_relative_path_key(source_rel)
        if key not in seen:
            refs.append(source_rel)
            seen.add(key)
    if self_refs:
        findings.append(
            Finding(
                "info",
                "worker-run-receipt-refresh-self-ref-ignored",
                f"ignored self-referential source_hash refs while refreshing: {', '.join(self_refs)}",
                target_rel,
            )
        )
    if not refs and not any(finding.severity in {"warn", "error"} for finding in findings):
        findings.append(
            Finding(
                severity,
                "worker-run-receipt-refresh-refused",
                f"worker run receipt has no source-bound source_hash refs to refresh after excluding its own target {target_rel}",
                target_rel,
            )
        )
    return tuple(refs), findings


def _worker_run_receipt_refresh_token(target_rel: str, current_hash: str, source_hashes: tuple[str, ...]) -> str:
    payload = "\n".join((target_rel, current_hash, *source_hashes))
    return f"{WORKER_RUN_RECEIPT_REFRESH_TOKEN_PREFIX}{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _worker_run_receipt_refresh_route_findings(plan: WorkerRunReceiptRefreshPlan, *, apply: bool) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "worker-run-receipt-refresh-token",
            (
                f"current receipt sha256={plan.current_receipt_hash}; proposal_token={plan.proposal_token}; "
                f"apply with: mylittleharness --root <root> evidence --receipt-refresh --apply --target {plan.rel_path} --proposal-token {plan.proposal_token}"
            ),
            plan.rel_path,
        )
    ]
    if plan.current_text == plan.updated_text:
        findings.append(
            Finding(
                "info",
                "worker-run-receipt-refresh-current",
                "worker run receipt source_hashes are already current; no route write is needed",
                plan.rel_path,
            )
        )
        return findings
    before_hash = _short_hash(plan.current_text)
    after_hash = _short_hash(plan.updated_text)
    before_bytes = len(plan.current_text.encode("utf-8"))
    after_bytes = len(plan.updated_text.encode("utf-8"))
    prefix = "refreshed" if apply else "would refresh"
    findings.extend(
        [
            Finding("info", "worker-run-receipt-refreshed" if apply else "worker-run-receipt-refresh-dry-run", f"{prefix} source_hashes for existing worker run receipt: {plan.rel_path}", plan.rel_path),
            Finding(
                "info",
                "worker-run-receipt-refresh-route-write",
                f"{prefix} route {plan.rel_path}; before_hash={before_hash}; after_hash={after_hash}; before_bytes={before_bytes}; after_bytes={after_bytes}; source-bound write evidence is independent of Git tracking",
                plan.rel_path,
            ),
        ]
    )
    return findings


def _worker_run_receipt_refresh_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "worker-run-receipt-refresh-boundary",
            "worker run receipt refresh updates only existing receipt source_hashes; it cannot approve lifecycle, fan-in, provider routing, credentials, staging, commit, archive, or target acceptance",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
        Finding(
            "info",
            "worker-run-receipt-refresh-route",
            f"worker run receipt refresh is limited to existing {WORKER_RUN_RECEIPTS_DIR_REL}/*.json receipts and creates no runtime, queue, provider gateway, or hidden state",
            WORKER_RUN_RECEIPTS_DIR_REL,
        ),
    ]


def _agent_run_record_target_rel(request: AgentRunRecordRequest) -> str:
    return f"{AGENT_RUN_RECORD_PREFIX}{request.record_id}.md"


def _agent_run_record_refresh_plan(root: Path, target_rel: str, severity: str, *, request: AgentRunRecordRequest | None = None) -> tuple[AgentRunRecordRefreshPlan | None, list[Finding]]:
    target = root / target_rel
    try:
        current_text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding(severity, "agent-run-record-refused", f"existing agent run record could not be read before source-hash refresh: {exc}", target_rel)]

    frontmatter = parse_frontmatter(current_text)
    data = frontmatter.data
    if not frontmatter.has_frontmatter:
        return None, [Finding(severity, "agent-run-record-refused", "existing agent run record is missing frontmatter; source-hash refresh refuses to guess metadata boundaries", target_rel)]
    if frontmatter.errors:
        return None, [Finding(severity, "agent-run-record-refused", "existing agent run record has malformed frontmatter; source-hash refresh refuses to guess metadata boundaries", target_rel)]
    if data.get("schema") != AGENT_RUN_SCHEMA:
        return None, [Finding(severity, "agent-run-record-refused", f"existing agent run record schema should be {AGENT_RUN_SCHEMA}", target_rel)]
    if data.get("record_type") != "agent-run":
        return None, [Finding(severity, "agent-run-record-refused", "existing agent run record record_type should be agent-run", target_rel)]
    record_id = str(data.get("record_id") or "").strip()
    expected_record_id = Path(target_rel).stem
    if record_id_conflict(record_id):
        return None, [Finding(severity, "agent-run-record-refused", f"existing agent run record_id {record_id!r} is unsafe: {record_id_conflict(record_id)}", target_rel)]
    if record_id != expected_record_id:
        return None, [Finding(severity, "agent-run-record-refused", f"existing agent run record_id {record_id!r} does not match route target {expected_record_id!r}", target_rel)]

    source_refs_with_self = _record_source_refs(data)
    source_refs = tuple(ref for ref in source_refs_with_self if not _same_root_relative_path(ref, target_rel))
    self_refs = tuple(ref for ref in source_refs_with_self if _same_root_relative_path(ref, target_rel))
    if not source_refs:
        return None, [
            Finding(
                severity,
                "agent-run-record-refused",
                f"existing agent run record has no source-bound refs to refresh after excluding its own target {target_rel}",
                target_rel,
            )
        ]

    updated_text = current_text
    refreshed_ref_fields: list[str] = []
    if request is not None:
        for field, requested_refs in (
            ("input_refs", request.input_refs),
            ("handoff_refs", request.handoff_refs),
            ("claim_refs", request.claim_refs),
        ):
            clean_requested_refs = tuple(ref.replace("\\", "/").strip() for ref in requested_refs if ref.replace("\\", "/").strip())
            if not clean_requested_refs:
                continue
            existing_refs = _frontmatter_string_list(data.get(field))
            merged_refs = _merge_root_relative_refs(existing_refs, clean_requested_refs)
            source_refs = _merge_root_relative_refs(source_refs, clean_requested_refs)
            if merged_refs != existing_refs:
                updated_text = _replace_frontmatter_list(updated_text, field, merged_refs)
                refreshed_ref_fields.append(field)

    source_hashes, hash_findings = _source_hash_entries_for_refs(root, source_refs)
    updated_text = _replace_agent_run_source_hashes(updated_text, source_hashes)
    plan = AgentRunRecordRefreshPlan(target_rel, current_text, updated_text, tuple(source_hashes), tuple(refreshed_ref_fields))
    ref_phrase = ""
    if refreshed_ref_fields:
        ref_phrase = f" and supplied {', '.join(refreshed_ref_fields)}"
    findings = [
        Finding(
            "info",
            "agent-run-record-refresh-target",
            f"refresh source_hashes{ref_phrase} for existing agent run evidence record: {target_rel}",
            target_rel,
        )
    ]
    if self_refs:
        findings.append(
            Finding(
                "info",
                "agent-run-record-refresh-self-ref-ignored",
                f"ignored self-referential source refs while refreshing source_hashes: {', '.join(self_refs)}",
                target_rel,
            )
        )
    findings.extend(hash_findings)
    return plan, findings


def _agent_run_record_refresh_route_findings(plan: AgentRunRecordRefreshPlan, *, apply: bool) -> list[Finding]:
    refresh_scope = "source_hashes"
    if plan.refreshed_ref_fields:
        refresh_scope = f"source_hashes and supplied {', '.join(plan.refreshed_ref_fields)}"
    if plan.current_text == plan.updated_text:
        return [
            Finding(
                "info",
                "agent-run-record-refresh-current",
                f"agent run evidence record {refresh_scope} are already current; no route write is needed",
                plan.rel_path,
            )
        ]
    before_hash = _short_hash(plan.current_text)
    after_hash = _short_hash(plan.updated_text)
    before_bytes = len(plan.current_text.encode("utf-8"))
    after_bytes = len(plan.updated_text.encode("utf-8"))
    prefix = "refreshed" if apply else "would refresh"
    return [
        Finding("info", "agent-run-record-refreshed" if apply else "agent-run-record-refresh-dry-run", f"{prefix} {refresh_scope} for existing agent run evidence record: {plan.rel_path}", plan.rel_path),
        Finding(
            "info",
            "agent-run-record-route-write",
            f"{prefix} route {plan.rel_path}; before_hash={before_hash}; after_hash={after_hash}; before_bytes={before_bytes}; after_bytes={after_bytes}; source-bound write evidence is independent of Git tracking",
            plan.rel_path,
        ),
    ]


def _merge_root_relative_refs(existing_refs: tuple[str, ...], requested_refs: tuple[str, ...]) -> tuple[str, ...]:
    merged = list(existing_refs)
    for requested_ref in requested_refs:
        clean_ref = requested_ref.replace("\\", "/").strip()
        if not clean_ref:
            continue
        if any(_same_root_relative_path(clean_ref, existing_ref) for existing_ref in merged):
            continue
        merged.append(clean_ref)
    return tuple(merged)


def _replace_agent_run_source_hashes(text: str, source_hashes: Iterable[str]) -> str:
    updated = _replace_frontmatter_list(text, "source_hashes", tuple(source_hashes))
    return _replace_source_hashes_section(updated, tuple(source_hashes))


def _replace_frontmatter_list(text: str, key: str, values: tuple[str, ...]) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return text

    replacement = _frontmatter_lines(key, values)
    key_prefix = f"{key}:"
    start_index = None
    for index in range(1, closing_index):
        if lines[index].startswith(key_prefix):
            start_index = index
            break
    if start_index is None:
        lines = [*lines[:closing_index], *replacement, *lines[closing_index:]]
    else:
        end_index = start_index + 1
        while end_index < closing_index and (lines[end_index].startswith((" ", "\t")) or lines[end_index].lstrip().startswith("- ")):
            end_index += 1
        lines = [*lines[:start_index], *replacement, *lines[end_index:]]
    return _join_preserving_trailing_newline(lines, text)


def _replace_source_hashes_section(text: str, source_hashes: tuple[str, ...]) -> str:
    lines = text.splitlines()
    replacement = ["## Source Hashes", "", *(f"- `{entry}`" for entry in source_hashes), ""]
    start_index = None
    for index, line in enumerate(lines):
        if line.strip().casefold() == "## source hashes":
            start_index = index
            break
    if start_index is None:
        lines = [*lines, "", *replacement]
        return _join_preserving_trailing_newline(lines, text)

    end_index = start_index + 1
    while end_index < len(lines) and not re.match(r"^#{1,6}\s+", lines[end_index]):
        end_index += 1
    lines = [*lines[:start_index], *replacement, *lines[end_index:]]
    return _join_preserving_trailing_newline(lines, text)


def _join_preserving_trailing_newline(lines: list[str], original_text: str) -> str:
    text = "\n".join(lines)
    if original_text.endswith("\n") and not text.endswith("\n"):
        text += "\n"
    return text


def _has_self_output_ref(request: AgentRunRecordRequest, target_rel: str) -> bool:
    return any(_same_root_relative_path(output_ref, target_rel) for output_ref in request.output_refs)


def _same_root_relative_path(left: str, right: str) -> bool:
    return _root_relative_path_key(left) == _root_relative_path_key(right)


def _root_relative_path_key(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.casefold()


def _is_product_source_ref(value: str) -> bool:
    return str(value or "").replace("\\", "/").strip().casefold().startswith(PRODUCT_SOURCE_REF_PREFIX)


def _product_source_ref_rel(value: str) -> str:
    return shared_product_source_ref_rel(value)


def _product_source_root_from_state(root: Path) -> Path | None:
    return shared_product_source_root_from_state(root)


def _product_source_ref_findings(root: Path, field: str, value: str, severity: str) -> list[Finding]:
    target = _product_source_ref_target(root, value)
    if target is None:
        return [Finding(severity, "agent-run-record-refused", f"{field} product-source refs require product_source_root in project/project-state.md", value)]
    ref_label, path, conflict = target
    if conflict:
        return [Finding(severity, "agent-run-record-refused", f"{field} product-source ref {conflict}: {ref_label}", value)]
    try:
        product_root = _product_source_root_from_state(root)
        if product_root is not None:
            path.relative_to(product_root)
    except (OSError, RuntimeError, ValueError):
        return [Finding(severity, "agent-run-record-refused", f"{field} product-source ref escapes configured product_source_root: {ref_label}", value)]
    return []


def _product_source_ref_for_absolute_path(root: Path, value: str) -> str:
    product_root = _product_source_root_from_state(root)
    if product_root is None:
        return ""
    try:
        candidate = Path(str(value or "").strip()).expanduser()
        if not candidate.is_absolute():
            return ""
        rel = candidate.resolve().relative_to(product_root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return ""
    if not rel or rel.startswith("../"):
        return ""
    return f"{PRODUCT_SOURCE_REF_PREFIX}{rel}"


def _product_source_ref_target(root: Path, value: str) -> tuple[str, Path, str] | None:
    target = shared_product_source_ref_target(root, value)
    if target is None:
        return None
    return target.ref_label, target.path, target.conflict


def _agent_run_record_boundary_findings(code_prefix: str = "agent-run-record") -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "agent run records are evidence only; they cannot approve lifecycle transitions, archive, roadmap status, staging, commit, rollback, or next-plan opening",
            AGENT_RUNS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-route",
            "agent run records live under project/verification/agent-runs/*.md and no hidden runtime, queue, database, cache, adapter state, or provider gateway is created",
            AGENT_RUNS_DIR_REL,
        ),
    ]


def _root_relative_path_conflict(rel_path: str) -> str:
    return root_relative_path_conflict(str(rel_path or "").replace("\\", "/").strip())


def _to_rel_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_status(surface: Surface) -> str:
    status = surface.frontmatter.data.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return "unrecorded"


def _record_title(surface: Surface) -> str:
    if surface.headings:
        return surface.headings[0].title
    return "untitled"


def _active_plan_findings(inventory: Inventory, active_plan: Surface | None, state_data: dict[str, object]) -> list[Finding]:
    state = inventory.state
    plan_status = str(state_data.get("plan_status") or "")
    configured_plan = str(state_data.get("active_plan") or inventory.manifest.get("memory", {}).get("plan_file", "project/implementation-plan.md"))
    if active_plan:
        return [
            Finding(
                "info",
                "evidence-active-plan",
                f"candidate: active plan present: {active_plan.rel_path}",
                active_plan.rel_path,
            )
        ]
    if plan_status == "active":
        return [
            Finding(
                "warn",
                "evidence-active-plan",
                f"missing: plan_status is active but active plan is not readable: {configured_plan}",
                state.rel_path if state else configured_plan,
            )
        ]
    return [
        Finding(
            "info",
            "evidence-active-plan",
            "no active plan is required by current state",
            state.rel_path if state else None,
        )
    ]


def _source_set_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    if not active_plan:
        return [
            Finding(
                "info",
                "evidence-source-set",
                "source-set scan skipped because no active plan is present",
            )
        ]
    cues = find_cues(active_plan, "source-set", "source-set candidate", (r"\bsource set\b", r"\bsource_set\b"))
    if not cues:
        return [
            Finding(
                "warn",
                "evidence-source-set",
                "missing: active plan has no source-set candidate",
                active_plan.rel_path,
            )
        ]
    return cue_findings("evidence-source-set", "source-set candidate", cues)


def _anchor_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    if not active_plan:
        return [
            Finding(
                "info",
                "evidence-anchor-missing",
                "anchor scan skipped because no active plan is present",
            )
        ]
    findings: list[Finding] = []
    for anchor_name, patterns in ANCHOR_PATTERNS:
        cues = find_cues(active_plan, f"{anchor_name}-anchor", f"{anchor_name} anchor candidate", patterns)
        if cues:
            findings.extend(cue_findings("evidence-anchor-candidate", f"{anchor_name} anchor candidate", cues, limit=2))
        else:
            findings.append(
                Finding(
                    "warn",
                    "evidence-anchor-missing",
                    f"missing: {anchor_name} anchor candidate not found in active plan",
                    active_plan.rel_path,
                )
            )
    return findings


def _identity_findings(active_plan: Surface | None) -> list[Finding]:
    if not active_plan:
        return [
            Finding(
                "info",
                "evidence-identity",
                "cue identity scan skipped because no active plan is present; persistent evidence manifest remains deferred and no evidence manifest was written",
            )
        ]
    return [
        Finding(
            "info",
            "evidence-identity",
            "report-only cue identity uses kind, source path, line number, normalized preview, and a deterministic hash; persistent evidence manifest remains deferred and no generated report is written",
            active_plan.rel_path,
        )
    ]


def _closeout_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    policy = inventory.manifest.get("policy", {}) if isinstance(inventory.manifest, dict) else {}
    closeout_commit = policy.get("closeout_commit")
    facts = current_state_writeback_facts(inventory)
    if closeout_commit:
        findings.append(
            Finding(
                "info",
                "evidence-closeout-candidate",
                f"candidate: manifest closeout_commit policy is {closeout_commit}",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else None,
            )
        )

    if not active_plan and not facts:
        findings.append(
            Finding(
                "info",
                "evidence-closeout-missing",
                "closeout field scan skipped because no active plan is present",
            )
        )
        return findings

    for field in CLOSEOUT_FIELD_NAMES:
        fact = facts.get(field)
        if fact:
            findings.append(_writeback_fact_finding("evidence-closeout-candidate", f"{field} candidate", fact))
            continue
        if not active_plan:
            findings.append(
                Finding(
                    "warn",
                    "evidence-closeout-missing",
                    f"missing: concrete closeout field candidate not found: {field}",
                )
            )
            continue
        concrete, broad = closeout_field_cues(active_plan, field)
        if concrete:
            findings.extend(cue_findings("evidence-closeout-candidate", f"{field} candidate", concrete, limit=2))
        else:
            findings.append(
                Finding(
                    "warn",
                    "evidence-closeout-missing",
                    f"missing: concrete closeout field candidate not found: {field}",
                    active_plan.rel_path,
                )
            )
            if broad:
                findings.extend(cue_findings("evidence-closeout-context", f"{field} context", broad, limit=2))
    return findings


def _writeback_fact_finding(code: str, label: str, fact: WritebackFact) -> Finding:
    return Finding(
        "info",
        code,
        f"candidate: {label}: - {fact.field}: {fact.value}; source={fact.source}:{fact.line}",
        fact.source,
        fact.line,
    )


def _quality_cue_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    facts = current_state_writeback_facts(inventory)
    if not active_plan and not facts:
        return [
            Finding(
                "info",
                "evidence-quality-cue",
                "quality cue scan skipped because no active plan is present; no quality-gate state was written",
            )
        ]
    missing = [
        field
        for field in CLOSEOUT_FIELD_NAMES
        if field not in facts and (not active_plan or not closeout_field_cues(active_plan, field)[0])
    ]
    fact_source = active_plan.rel_path if active_plan else (inventory.state.rel_path if inventory.state and inventory.state.exists else None)
    if missing:
        return [
            Finding(
                "warn",
                "evidence-quality-cue",
                f"report-only closeout readiness cue: concrete field evidence missing for {', '.join(missing)}; this does not approve or block lifecycle decisions",
                fact_source,
            )
        ]
    return [
        Finding(
            "info",
            "evidence-quality-cue",
            "report-only closeout readiness cue: concrete closeout field evidence is present; operator decisions and observed verification remain required",
            fact_source,
        )
    ]


def _acceptance_evidence_findings(inventory: Inventory, state_data: dict[str, object]) -> list[Finding]:
    if str(state_data.get("phase_status") or "") != "complete":
        return []
    facts = current_state_writeback_facts(inventory)
    values = {field: fact.value for field, fact in facts.items()}
    return acceptance_evidence_findings(
        inventory,
        values,
        completion_reason="completed active-plan phase",
        apply=False,
        code_prefix="evidence",
        include_success=True,
    )


def _operator_required_findings(inventory: Inventory) -> list[Finding]:
    source = inventory.manifest_surface.rel_path if inventory.manifest_surface and inventory.manifest_surface.exists else None
    return [
        Finding(
            "info",
            "evidence-operator-required",
            "operator-required: collect worktree_start_state before closeout; evidence does not run Git or VCS commands",
            source,
        ),
        Finding(
            "info",
            "evidence-operator-required",
            "operator-required: classify task_scope before closeout from the actual work performed",
            source,
        ),
    ]


def _line_group_findings(
    active_plan: Surface | None,
    code: str,
    label: str,
    patterns: Iterable[str],
    inventory: Inventory,
) -> list[Finding]:
    fact_key = "residual_risk" if "residual" in label else "carry_forward" if "carry" in label else ""
    fact = current_state_writeback_facts(inventory).get(fact_key) if fact_key else None
    if fact:
        return [_writeback_fact_finding(code, f"{label} candidate", fact)]
    if fact_key == "carry_forward":
        historical = satisfied_post_archive_carry_forward_finding(inventory, code)
        if historical:
            return [historical]
    if not active_plan:
        return [Finding("info", code, f"{label} scan skipped because no active plan is present")]
    cues = find_cues(active_plan, label.replace(" ", "-"), f"{label} candidate", patterns)
    if not cues:
        return [Finding("warn", code, f"missing: {label} candidate not found in active plan", active_plan.rel_path)]
    return cue_findings(code, f"{label} candidate", cues)
