from __future__ import annotations

import ast
import difflib
import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from importlib import resources
from pathlib import Path

from . import __version__
from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .attachments import attachment_validation_findings
from .dashboard import connect_readiness_findings, dashboard_check_findings
from .daemon import mlhd_runtime_findings
from .approval_packets import APPROVAL_PACKET_SCHEMA, APPROVAL_PACKETS_DIR_REL, APPROVAL_STATUSES
from .claims import (
    WORK_CLAIM_COMPLETION_POLICY_AUTHORITY_FIELDS,
    WORK_CLAIM_COMPLETION_POLICY_SCHEMA,
    WORK_CLAIM_SCHEMA,
    WORK_CLAIMS_DIR_REL,
    WORK_CLAIM_STATUSES,
)
from .context_memory import context_memory_capsule_findings
from .evidence import (
    AGENT_RUNS_DIR_REL,
    AGENT_RUN_DOCS_DECISIONS,
    AGENT_RUN_REQUIRED_LISTS,
    AGENT_RUN_REQUIRED_SCALARS,
    AGENT_RUN_SCHEMA,
    AGENT_RUN_STATUSES,
    agent_run_retired_records,
    agent_run_record_template_finding,
    lifecycle_mutation_provenance_findings,
    worker_run_receipt_findings,
)
from .handoff import HANDOFF_PACKET_SCHEMA, HANDOFF_PACKETS_DIR_REL, HANDOFF_PACKET_STATUSES, HANDOFF_WORKER_FORBIDDEN_ROUTES
from .inventory import (
    EXPECTED_SPEC_NAMES,
    Inventory,
    LEGACY_WORKFLOW_MANIFEST_REL,
    LinkRef,
    Surface,
    WORKFLOW_MANIFEST_REL,
    load_inventory,
    target_artifact_ownerships,
)
from .lifecycle_metadata import (
    LifecycleMarkdownFrontmatterPlan,
    lifecycle_markdown_frontmatter_fields_for_route,
    lifecycle_markdown_frontmatter_plan,
    lifecycle_markdown_requires_frontmatter,
    lifecycle_markdown_source_provenance_plan,
    lifecycle_markdown_text_with_frontmatter,
)
from .lifecycle_focus import CURRENT_FOCUS_BEGIN, CURRENT_FOCUS_END, MEMORY_ROADMAP_BEGIN, MEMORY_ROADMAP_END
from .models import Finding
from .memory_hygiene import (
    ARCHIVE_VERIFICATION_DIR_REL,
    VERIFICATION_DIR_REL,
    VERIFICATION_LEDGER_CONTINUITY_MARKER,
    relationship_hygiene_scan_findings,
)
from .meta_feedback import CENTRAL_META_FEEDBACK_PROJECT, META_FEEDBACK_ROOT_ENV_VAR, meta_feedback_env_destination_root
from .parsing import extract_path_refs, parse_frontmatter
from .product_hygiene_checks import product_hygiene_findings
from .roadmap import (
    ROADMAP_REL,
    active_plan_roadmap_item_ids,
    roadmap_acceptance_readiness_findings,
    roadmap_archived_history_stale_tail_findings,
    roadmap_batch_slice_gate_findings,
    roadmap_items_for_diagnostics,
    roadmap_order_namespace_findings,
    roadmap_compacted_dependency_archive_evidence_findings,
    roadmap_done_docs_archive_evidence_findings,
    roadmap_human_review_gate_findings,
    roadmap_related_specs_evidence_findings,
    roadmap_source_incubation_evidence_findings,
    roadmap_terminal_related_plan_findings,
)
from .roadmap_semantics import roadmap_item_is_terminal_history_stub
from .projection import Projection, ProjectionLinkRecord, build_projection, historical_link_context_reason, product_target_artifact_reason
from .projection_artifacts import (
    ARTIFACT_DIR_REL,
    PROJECTION_REBUILD_NEXT_SAFE_COMMAND,
    build_projection_artifacts,
    inspect_projection_artifacts,
    projection_cache_posture_payload,
    projection_artifact_path_query_findings,
    rebuild_projection_artifacts,
)
from .projection_index import INDEX_REL_PATH, build_projection_index, full_text_search_findings, inspect_projection_index, warm_projection_index
from .reporting import RouteWriteEvidence, route_write_findings
from .root_boundary import (
    PRODUCT_SOURCE_FIXTURE,
    record_id_conflict,
    root_relative_path_conflict,
    source_path_boundary_violation,
    windows_path_reference_reason,
)
from .safe_commands import shell_arg
from .research_recovery import (
    deep_research_rubric_recovery_findings,
    deep_research_rubric_recovery_target_label,
)
from .routes import (
    CHANGED_ROUTE_METADATA_PROFILES,
    INTAKE_ROUTE_ALLOWED_TARGETS,
    INTAKE_ROUTE_DEFAULT_STATUS,
    IntakeRouteAdvice,
    ROUTE_BY_ID,
    classify_intake_text,
    classify_intake_text_for_target,
    classify_memory_route,
    doc_target_exists,
    existing_doc_target_candidates,
    is_exact_doc_target,
    intake_target_matches_route,
    lifecycle_route_rows,
    normalize_route_path,
    route_destination_matches,
    route_destination_policy_for_field,
    route_id_is_known,
)
from .writeback import (
    CLOSEOUT_WRITEBACK_FIELDS,
    NEXT_STATE_EXPLICIT_DECISION_REQUIRED,
    NEXT_STATE_LEGACY_HUMAN_DECISION_REQUIRED,
    STATE_COMPACTION_CHAR_THRESHOLD,
    WRITEBACK_BEGIN,
    WRITEBACK_END,
    active_plan_body_facts,
    active_plan_completed_phase_handoff_findings,
    active_plan_phase_body_status_fact,
    active_plan_preceding_phase_body_status_facts,
    acceptance_evidence_findings,
    canonical_phase_body_status,
    closeout_values_are_complete,
    completion_gate_packet_findings,
    state_writeback_facts,
    state_writeback_identity_matches_current_plan,
)
from .vcs import probe_vcs, product_diff_write_scope_findings


LARGE_FILE_LINES = 500
VERY_LARGE_FILE_LINES = 1500
LARGE_FILE_CHARS = STATE_COMPACTION_CHAR_THRESHOLD
VERY_LARGE_FILE_CHARS = 75_000
LARGE_AGGREGATE_LINES = 2500
LARGE_AGGREGATE_CHARS = 125_000
SEARCH_RESULT_LIMIT = 20
FAN_IN_RESULT_LIMIT = 20
CURRENT_PHASE_ONLY_POLICY = "current-phase-only"
NONROUTE_PROJECT_MARKDOWN_EXEMPT_PREFIXES = (
    "project/cache/",
    "project/generated/",
    "project/private/",
    "project/scratch/",
    "project/secrets/",
    "project/temp/",
    "project/tmp/",
)
BUG_HUNT_LEDGER_REL = "project/verification/continuous-bug-hunt-ledger.md"
BUG_HUNT_COVERAGE_REL = "project/verification/bug-hunt-roadmap-coverage.md"
BUG_HUNT_DISPOSITION_STATUSES = {"fixed", "delegated", "rejected-with-reason", "still-open"}
BUG_HUNT_ROADMAP_OWNER_STATUSES = {"accepted", "active", "done"}
ACCEPTED_HANDOFF_LEGACY_ROUTE_ALIASES = {
    "check": "verification",
    "evidence": "agent-runs",
}
COMMAND_SURFACE_SENTINEL_COMMANDS = ("transition", "roadmap", "meta-feedback")
COMMAND_SURFACE_PROBE_TIMEOUT_SECONDS = 5
RETIRED_COMMAND_DOC_SURFACES = ("mirror", "research-prompt")
TEMPORARY_ROADMAP_MANIFEST_RE = re.compile(r"^project/verification/roadmap-routing-\d{4}-\d{2}-\d{2}-[a-z0-9._-]+\.json$")
COMMAND_SURFACE_SCHEMA_VERSION = "mylittleharness.command-surface.v1"
COMMAND_SURFACE_ROWS: tuple[dict[str, object], ...] = (
    {
        "schema_version": COMMAND_SURFACE_SCHEMA_VERSION,
        "surface_id": "read-only-status-navigation",
        "commands": (
            "check",
            "check --deep",
            "check --focus <area>",
            "status",
            "validate",
            "audit-links",
            "context-budget",
            "doctor",
            "dashboard --inspect",
            "manifest --inspect",
            "suggest --intent",
            "projection --inspect",
            "snapshot --inspect",
            "preflight",
            "hooks --run",
            "hooks --doctor",
            "adapter --inspect",
            "adapter --serve --target mcp-read-projection --transport stdio",
            "adapter --client-config",
            "claim --status",
            "handoff --status",
            "reconcile",
            "closeout",
            "evidence",
            "review-token",
            "semantic --inspect",
            "semantic --evaluate",
            "tasks --inspect",
        ),
        "read_write_class": "read-only-report",
        "apply_requirement": "no --apply path for this report posture; any later mutation requires a separate reviewed dry-run/apply rail",
        "root_eligibility": "any readable MLH root matching the command-specific root posture",
        "write_path_posture": "writes no repo files, generated caches, package artifacts, hooks, Git state, user config, or workstation state",
        "authority_risk": "advisory navigation/report data only and not authority; cannot approve lifecycle, archive, roadmap status, staging, commit, push, release, or provider routing",
    },
    {
        "schema_version": COMMAND_SURFACE_SCHEMA_VERSION,
        "surface_id": "read-mostly-generated-cache-navigation",
        "commands": ("intelligence",),
        "read_write_class": "read-mostly-report-with-disposable-cache-refresh",
        "apply_requirement": "no --apply path for this report posture; path/full-text search may refresh disposable generated projection cache without implying lifecycle apply",
        "root_eligibility": "any readable MLH root matching the intelligence root posture",
        "write_path_posture": "writes no repo source files, lifecycle routes, package artifacts, hooks, Git state, user config, workstation state, or runtime state; search-oriented navigation may refresh only disposable generated projection cache under .mylittleharness/generated/projection",
        "authority_risk": "source/lifecycle report data and refreshed generated navigation cache are advisory only; neither can approve lifecycle, archive, roadmap status, staging, commit, push, release, or provider routing",
    },
    {
        "schema_version": COMMAND_SURFACE_SCHEMA_VERSION,
        "surface_id": "explicit-dry-run-apply-rails",
        "commands": (
            "init --dry-run|--apply",
            "attach --dry-run|--apply",
            "detach --dry-run|--apply",
            "repair --dry-run|--apply",
            "migrate --dry-run|--apply",
            "plan --dry-run|--apply",
            "plan-cancel --dry-run|--apply",
            "writeback --dry-run|--apply",
            "transition --dry-run|--apply",
            "roadmap --dry-run|--apply",
            "memory-hygiene --dry-run|--apply",
            "relationship-drift --dry-run|--apply",
            "incubate --dry-run|--apply",
            "incubation-reconcile --dry-run|--apply",
            "intake --dry-run|--apply",
            "attachment-import --dry-run|--apply",
            "research-import --dry-run|--apply",
            "research-distill --dry-run|--apply",
            "research-compare --dry-run|--apply",
            "discover --dry-run|--apply",
            "evidence --record --dry-run|--apply",
            "cleanup --dry-run|--apply",
            "claim --dry-run|--apply",
            "handoff --dry-run|--apply",
            "approval-packet --dry-run|--apply",
            "meta-feedback --dry-run|--apply",
            "hooks adapter --dry-run|--apply",
            "adapter --install-client-config --dry-run|--apply",
        ),
        "read_write_class": "explicit-preview-then-write",
        "apply_requirement": "dry-run is the reviewable preview; apply is explicit and command-owned, with source-hash or review-token guards where required",
        "root_eligibility": "eligible live operating roots or explicitly supported command roots; product-source fixtures and archive roots are refused where unsafe",
        "write_path_posture": "writes only command-owned route files, scaffold files, generated cache paths, or local config targets named by the reviewed rail",
        "authority_risk": "apply writes evidence/state but still is not future authority and cannot approve future lifecycle decisions, archive, staging, commit, push, release, rollback, or provider routing",
    },
    {
        "schema_version": COMMAND_SURFACE_SCHEMA_VERSION,
        "surface_id": "direct-generated-cache-maintenance",
        "commands": ("projection --build|--rebuild|--delete|--warm-cache",),
        "read_write_class": "direct-disposable-generated-cache-mutation",
        "apply_requirement": "no matching dry-run/apply lifecycle rail is implied; the explicit projection command mutates only disposable generated cache state",
        "root_eligibility": "readable MLH roots with projection cache support; product source and live operating roots keep source files authoritative",
        "write_path_posture": "writes only disposable generated projection cache files or cache markers under .mylittleharness/generated/projection",
        "authority_risk": "generated-cache maintenance cannot approve lifecycle, archive, roadmap status, repair, staging, commit, push, release, rollback, provider routing, or source truth",
    },
    {
        "schema_version": COMMAND_SURFACE_SCHEMA_VERSION,
        "surface_id": "product-package-smoke",
        "commands": ("bootstrap --inspect", "bootstrap --package-smoke"),
        "read_write_class": "product-verification",
        "apply_requirement": "does not use --apply; package smoke is an explicit verification mode, not a lifecycle mutation rail",
        "root_eligibility": "MyLittleHarness product source checkout for package smoke; readable root for bootstrap inspection",
        "write_path_posture": "package smoke copies source to a temporary workspace outside the product root, creates an isolated venv without system site packages, and leaves no product-root build/dist/egg-info artifacts",
        "authority_risk": "package/build success is verification evidence only and not authority; it does not publish, install globally, change PATH, write user config, add CI, stage, commit, push, release, or choose a license",
    },
    {
        "schema_version": COMMAND_SURFACE_SCHEMA_VERSION,
        "surface_id": "optional-runtime-helper",
        "commands": (
            "mlhd status",
            "mlhd doctor",
            "mlhd run-once --dry-run|--apply",
            "mlhd start --dry-run|--apply",
            "mlhd stop --dry-run|--apply",
            "mlhd install --dry-run|--apply",
            "mlhd uninstall --dry-run|--apply",
        ),
        "read_write_class": "optional-runtime-cache",
        "apply_requirement": "runtime mutations require explicit dry-run/apply; status remains read-only",
        "root_eligibility": "local MLH root with optional runtime cache boundary",
        "write_path_posture": "writes only root-local disposable mlhd runtime/cache/autostart artifacts or generated projection refresh output",
        "authority_risk": "no hidden daemon authority or provider gateway; runtime helpers cannot approve lifecycle movement, source truth, archive, Git, release, dispatcher work, or cache truth",
    },
)
PRODUCT_DOC_COPY_DRIFT_SURFACES = (
    "README.md",
    "docs/README.md",
    "docs/specs/attach-repair-status-cli.md",
    ".agents/docmap.yaml",
)
COORDINATION_EVIDENCE_RECORD_KINDS = ("agent-run", "worker-run-receipt", "work-claim", "handoff", "approval-packet")
COORDINATION_RECORD_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
COORDINATION_SOURCE_HASH_RE = re.compile(r"^(.+?)\s+(?:sha256=([a-fA-F0-9]{64})|(missing)|(unreadable)|(invalid-path))$")
COORDINATION_SOURCE_HASH_REQUIRED_PREFIXES = (".agents/", ".codex/", "docs/", "src/", "tests/")
COORDINATION_SOURCE_HASH_REQUIRED_FILES = {"AGENTS.md", "README.md", "pyproject.toml"}
SYMPHONY_QUEUE_DIR_REL = "project/symphony/queue"
SYMPHONY_QUEUE_SCHEMA = "mlh.symphony.queue-item.v1"


@dataclass(frozen=True)
class CleanupRequest:
    target: str
    reason: str = ""


def make_cleanup_request(target: str, reason: str | None = None) -> CleanupRequest:
    return CleanupRequest(target=str(target or ""), reason=str(reason or ""))


def cleanup_dry_run_findings(inventory: Inventory, request: CleanupRequest) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "cleanup-dry-run",
            "cleanup preview only; no files, lifecycle routes, archives, Git state, caches, or generated reports were changed",
            request.target or None,
        )
    ]
    target = _cleanup_target_review(inventory, request)
    findings.extend(target.findings)
    if target.errors:
        findings.extend(_cleanup_boundary_findings())
        return findings
    if not target.path.exists():
        findings.append(
            Finding(
                "info",
                "cleanup-target-missing",
                f"temporary roadmap manifest is already absent; no apply target exists: {target.rel_path}",
                target.rel_path,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "cleanup-plan",
                f"would delete exact obsolete temporary roadmap manifest: {target.rel_path}",
                target.rel_path,
            )
        )
    findings.extend(_cleanup_boundary_findings())
    return findings


def cleanup_apply_findings(inventory: Inventory, request: CleanupRequest) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "cleanup-apply",
            "cleanup apply started; this route may delete only one reviewed temporary roadmap JSON manifest",
            request.target or None,
        )
    ]
    target = _cleanup_target_review(inventory, request)
    findings.extend(target.findings)
    if target.errors:
        findings.extend(_cleanup_boundary_findings())
        return findings
    if not target.path.exists():
        findings.append(
            Finding(
                "info",
                "cleanup-target-missing",
                f"temporary roadmap manifest is already absent; no file was deleted: {target.rel_path}",
                target.rel_path,
            )
        )
        findings.extend(_cleanup_boundary_findings())
        return findings
    try:
        target.path.unlink()
    except OSError as exc:
        findings.append(Finding("error", "cleanup-delete-failed", f"could not delete temporary roadmap manifest: {exc}", target.rel_path))
        findings.extend(_cleanup_boundary_findings())
        return findings
    findings.append(Finding("info", "cleanup-deleted", f"deleted obsolete temporary roadmap manifest: {target.rel_path}", target.rel_path))
    findings.extend(_cleanup_boundary_findings())
    return findings


@dataclass(frozen=True)
class _CleanupTargetReview:
    rel_path: str
    path: Path
    findings: list[Finding]
    errors: bool


def _cleanup_target_review(inventory: Inventory, request: CleanupRequest) -> _CleanupTargetReview:
    rel_path, path, findings = _cleanup_target_shape_findings(inventory, request.target)
    if any(finding.severity == "error" for finding in findings):
        return _CleanupTargetReview(rel_path, path, findings, True)
    findings.extend(_cleanup_existing_target_findings(path, rel_path, inventory.root))
    return _CleanupTargetReview(rel_path, path, findings, any(finding.severity == "error" for finding in findings))


def _cleanup_target_shape_findings(inventory: Inventory, target: str) -> tuple[str, Path, list[Finding]]:
    raw = str(target or "").strip().replace("\\", "/")
    rel_path = raw.strip("/")
    path = inventory.root / rel_path
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "error",
                "cleanup-refused",
                f"cleanup is available only in live operating roots; root kind is {inventory.root_kind}",
                rel_path or None,
            )
        )
    if not raw:
        findings.append(Finding("error", "cleanup-refused", "cleanup requires --target <project/verification/roadmap-routing-*.json>"))
    if Path(raw).is_absolute() or re.match(r"^[a-zA-Z]:/", raw):
        findings.append(Finding("error", "cleanup-refused", "cleanup target must be root-relative, not absolute", raw))
    if raw.startswith("../") or "/../" in raw or raw == "..":
        findings.append(Finding("error", "cleanup-refused", "cleanup target must not contain parent traversal", raw))
    if rel_path and not TEMPORARY_ROADMAP_MANIFEST_RE.match(rel_path.casefold()):
        findings.append(
            Finding(
                "error",
                "cleanup-refused",
                "cleanup target must match project/verification/roadmap-routing-YYYY-MM-DD-*.json",
                rel_path,
            )
        )
    try:
        root_resolved = inventory.root.resolve(strict=True)
        path.resolve(strict=False).relative_to(root_resolved)
    except (OSError, ValueError):
        findings.append(Finding("error", "cleanup-refused", "cleanup target must resolve inside the operating root", rel_path or raw))
    symlink_rel = _cleanup_symlink_segment(inventory.root, rel_path)
    if symlink_rel:
        findings.append(Finding("error", "cleanup-refused", f"cleanup target crosses a symlink segment: {symlink_rel}", symlink_rel))
    if not any(finding.severity == "error" for finding in findings):
        findings.append(
            Finding(
                "info",
                "cleanup-target",
                f"target is a bounded temporary roadmap manifest candidate: {rel_path}",
                rel_path,
            )
        )
    return rel_path, path, findings


def _cleanup_existing_target_findings(path: Path, rel_path: str, root: Path) -> list[Finding]:
    if not path.exists():
        return []
    findings: list[Finding] = []
    if not path.is_file() or path.is_symlink():
        findings.append(Finding("error", "cleanup-refused", "cleanup target must be a regular non-symlink file", rel_path))
        return findings
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        findings.append(Finding("error", "cleanup-refused", f"cleanup target must be readable JSON: {exc}", rel_path))
        return findings
    if not isinstance(payload, (dict, list)):
        findings.append(Finding("error", "cleanup-refused", "cleanup target JSON must be an object or array manifest", rel_path))
    tracking = _cleanup_git_tracking_status(root, rel_path)
    if tracking == "tracked":
        findings.append(Finding("error", "cleanup-refused", "cleanup refuses to delete a Git-tracked file", rel_path))
    elif tracking == "untracked":
        findings.append(Finding("info", "cleanup-target-untracked", "target is not tracked by Git in this root", rel_path))
    else:
        findings.append(Finding("info", "cleanup-target-git-unknown", "Git tracking status unavailable; cleanup remains bounded by exact path and JSON shape", rel_path))
    return findings


def _cleanup_symlink_segment(root: Path, rel_path: str) -> str:
    if not rel_path:
        return ""
    current = root
    parts: list[str] = []
    for part in Path(rel_path).parts:
        parts.append(part)
        current = current / part
        if current.exists() and current.is_symlink():
            return "/".join(parts)
    return ""


def _cleanup_git_tracking_status(root: Path, rel_path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", rel_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=COMMAND_SURFACE_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode == 0:
        return "tracked"
    if result.returncode == 1:
        return "untracked"
    return "unknown"


def _cleanup_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "cleanup-boundary",
            (
                "cleanup owns only exact temporary roadmap JSON manifest removal under project/verification; "
                "it cannot delete lifecycle Markdown, archive evidence, repair metadata, mark roadmap done, stage, commit, push, or weaken hooks"
            ),
            "project/verification",
        )
    ]


def coordination_evidence_identity_findings(
    inventory: Inventory,
    code_prefix: str = "coordination-evidence",
    record_kinds: tuple[str, ...] = COORDINATION_EVIDENCE_RECORD_KINDS,
) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            f"{code_prefix}-read-only",
            "coordination evidence identity diagnostics are read-only; they write no records, locks, lifecycle state, generated caches, or Git state",
            "project/verification",
        )
    ]
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-non-authority",
                f"coordination evidence identity scan is live-root only; root kind is {inventory.root_kind}",
                inventory.state.rel_path if inventory.state and inventory.state.exists else None,
            )
        )
        findings.extend(_coordination_evidence_boundary_findings(code_prefix))
        return findings

    requested = set(record_kinds)
    if "work-claim" in requested:
        findings.extend(_coordination_work_claim_identity_findings(inventory.root, code_prefix))
    if "handoff" in requested:
        findings.extend(_coordination_handoff_identity_findings(inventory.root, code_prefix))
    if "approval-packet" in requested:
        findings.extend(_coordination_approval_packet_identity_findings(inventory.root, code_prefix))
    if "agent-run" in requested:
        findings.extend(_coordination_agent_run_identity_findings(inventory.root, code_prefix))
    if "worker-run-receipt" in requested:
        findings.extend(worker_run_receipt_findings(inventory, f"{code_prefix}-worker-run-receipt"))

    if not any(finding.severity == "warn" for finding in findings):
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-clean",
                f"coordination record identity scan found no malformed filenames, route ids, approval refs, accepted-handoff provenance, or source-hash coverage gaps for {', '.join(record_kinds)}",
                "project/verification",
            )
        )
    findings.extend(_coordination_evidence_boundary_findings(code_prefix))
    return findings


def _coordination_work_claim_identity_findings(root: Path, code_prefix: str) -> list[Finding]:
    records, findings = _coordination_json_records(
        root,
        WORK_CLAIMS_DIR_REL,
        label="work-claim",
        id_field="claim_id",
        schema=WORK_CLAIM_SCHEMA,
        record_type="work-claim",
        code_prefix=code_prefix,
    )
    if not records:
        return findings
    for rel_path, data in records:
        status = str(data.get("status") or "").strip()
        if status and status not in WORK_CLAIM_STATUSES:
            findings.append(Finding("warn", f"{code_prefix}-work-claim-status-unknown", f"work claim status is unsupported: {status}", rel_path))
        for route_id in _coordination_string_list(data.get("claimed_routes")):
            if not route_id_is_known(route_id):
                findings.append(Finding("warn", f"{code_prefix}-work-claim-route-unknown", f"work claim claimed_routes contains unknown route id: {route_id}", rel_path))
        for rel in _coordination_string_list(data.get("claimed_paths")):
            findings.extend(_coordination_ref_shape_findings(root, rel, rel_path, code_prefix, "work-claim-claimed-path", require_existing=False))
        lease = str(data.get("lease_expires_at") or "").strip()
        if lease and _coordination_parse_utc_timestamp(lease) is None:
            findings.append(Finding("warn", f"{code_prefix}-work-claim-provenance", "work claim lease_expires_at is not a valid UTC timestamp", rel_path))
        completion_policy = data.get("completion_policy")
        if isinstance(completion_policy, dict):
            if completion_policy.get("schema") != WORK_CLAIM_COMPLETION_POLICY_SCHEMA:
                findings.append(
                    Finding(
                        "warn",
                        f"{code_prefix}-work-claim-completion-policy-schema",
                        f"work claim completion_policy schema should be {WORK_CLAIM_COMPLETION_POLICY_SCHEMA}",
                        rel_path,
                    )
                )
            for field in WORK_CLAIM_COMPLETION_POLICY_AUTHORITY_FIELDS:
                if _coordination_truthy(completion_policy.get(field)):
                    findings.append(
                        Finding(
                            "warn",
                            f"{code_prefix}-work-claim-completion-policy-authority",
                            f"work claim completion_policy {field} must remain false; external completion claims are evidence only",
                            rel_path,
                        )
                    )
            findings.append(
                Finding(
                    "info",
                    f"{code_prefix}-work-claim-completion-policy",
                    "work claim completion_policy is repo-visible evidence only and cannot approve lifecycle, roadmap done-state, archive, or Git",
                    rel_path,
                )
            )
        elif completion_policy not in (None, ""):
            findings.append(Finding("warn", f"{code_prefix}-work-claim-completion-policy-schema", "work claim completion_policy must be an object when present", rel_path))
        completion_evidence = data.get("completion_evidence")
        if isinstance(completion_evidence, dict):
            findings.extend(
                _coordination_ref_list_findings(
                    root,
                    completion_evidence.get("repo_visible_refs"),
                    rel_path,
                    code_prefix,
                    "work-claim-completion-evidence-ref",
                    require_existing=False,
                )
            )
            if _coordination_truthy(completion_evidence.get("external_tracker_status_authoritative")):
                findings.append(
                    Finding(
                        "warn",
                        f"{code_prefix}-work-claim-completion-policy-authority",
                        "work claim completion_evidence external_tracker_status_authoritative must remain false",
                        rel_path,
                    )
                )
        elif completion_evidence not in (None, ""):
            findings.append(Finding("warn", f"{code_prefix}-work-claim-completion-policy-schema", "work claim completion_evidence must be an object when present", rel_path))
    return findings


def _coordination_handoff_identity_findings(root: Path, code_prefix: str) -> list[Finding]:
    records, findings = _coordination_json_records(
        root,
        HANDOFF_PACKETS_DIR_REL,
        label="handoff",
        id_field="handoff_id",
        schema=HANDOFF_PACKET_SCHEMA,
        record_type="handoff-packet",
        code_prefix=code_prefix,
    )
    findings.extend(_coordination_handoff_note_findings(root, code_prefix))
    if not records:
        return findings
    for rel_path, data in records:
        status = str(data.get("status") or "").strip()
        if status and status not in HANDOFF_PACKET_STATUSES:
            findings.append(Finding("warn", f"{code_prefix}-handoff-status-unknown", f"handoff status is unsupported: {status}", rel_path))
        for route_id in _coordination_string_list(data.get("allowed_routes")):
            if not route_id_is_known(route_id):
                legacy_target = _accepted_handoff_legacy_route_alias(route_id, data)
                if legacy_target:
                    findings.append(
                        Finding(
                            "info",
                            f"{code_prefix}-handoff-route-legacy-alias",
                            (
                                f"accepted handoff allowed_routes contains legacy command alias {route_id}; "
                                f"treated as historical alias for route id {legacy_target} in read-only diagnostics only"
                            ),
                            rel_path,
                        )
                    )
                else:
                    findings.append(Finding("warn", f"{code_prefix}-handoff-route-unknown", f"handoff allowed_routes contains unknown route id: {route_id}", rel_path))
            if route_id in HANDOFF_WORKER_FORBIDDEN_ROUTES:
                findings.append(Finding("warn", f"{code_prefix}-handoff-route-forbidden", f"existing handoff packet allows lifecycle-authority route: {route_id}", rel_path))
        if status == "accepted":
            if not str(data.get("accepted_by") or "").strip():
                findings.append(Finding("warn", f"{code_prefix}-handoff-accepted-provenance", "accepted handoff packet is missing accepted_by", rel_path))
            accepted_at = str(data.get("accepted_at_utc") or "").strip()
            if not accepted_at:
                findings.append(Finding("warn", f"{code_prefix}-handoff-accepted-provenance", "accepted handoff packet is missing accepted_at_utc", rel_path))
            elif _coordination_parse_utc_timestamp(accepted_at) is None:
                findings.append(Finding("warn", f"{code_prefix}-handoff-accepted-provenance", "accepted handoff packet accepted_at_utc is not a valid UTC timestamp", rel_path))
        findings.extend(_coordination_ref_list_findings(root, data.get("evidence_refs"), rel_path, code_prefix, "handoff-evidence-ref", require_existing=True))
        findings.extend(_coordination_ref_list_findings(root, data.get("approval_packet_refs"), rel_path, code_prefix, "handoff-approval-packet-ref", require_existing=True))
        findings.extend(_coordination_ref_list_findings(root, data.get("claim_refs"), rel_path, code_prefix, "handoff-work-claim-ref", require_existing=True))
    return findings


def _accepted_handoff_legacy_route_alias(route_id: str, data: dict[str, object]) -> str | None:
    if str(data.get("status") or "").strip() != "accepted":
        return None
    normalized = str(route_id or "").strip()
    target = ACCEPTED_HANDOFF_LEGACY_ROUTE_ALIASES.get(normalized)
    if target is None:
        return None
    evidence_refs = _coordination_string_list(data.get("evidence_refs"))
    if normalized == "check":
        if not any(ref == "project/verification" or ref.startswith("project/verification/") for ref in evidence_refs):
            return None
    elif normalized == "evidence":
        if not any(ref.startswith("project/verification/agent-runs/") for ref in evidence_refs):
            return None
    else:
        return None
    return target


def _coordination_handoff_note_findings(root: Path, code_prefix: str) -> list[Finding]:
    directory = root / HANDOFF_PACKETS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return []
    findings: list[Finding] = []
    for path in sorted(directory.glob("*.md")):
        rel_path = _coordination_to_rel_path(root, path)
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-handoff-note-template",
                (
                    "handoff Markdown notes are discoverable evidence only; canonical dispatcher handoff packets are JSON "
                    "records scaffolded with `mylittleharness --root <root> handoff --dry-run --action create ...`"
                ),
                rel_path,
            )
        )
    return findings


def _coordination_approval_packet_identity_findings(root: Path, code_prefix: str) -> list[Finding]:
    records, findings = _coordination_json_records(
        root,
        APPROVAL_PACKETS_DIR_REL,
        label="approval-packet",
        id_field="approval_id",
        schema=APPROVAL_PACKET_SCHEMA,
        record_type="approval-packet",
        code_prefix=code_prefix,
    )
    if not records:
        return findings
    for rel_path, data in records:
        for field in ("requester", "subject", "requested_decision", "gate_class"):
            if not str(data.get(field) or "").strip():
                findings.append(Finding("warn", f"{code_prefix}-approval-packet-malformed", f"approval packet {field} is required", rel_path))
        status = str(data.get("status") or "").strip()
        if not status:
            findings.append(Finding("warn", f"{code_prefix}-approval-packet-malformed", "approval packet status is required", rel_path))
        elif status not in APPROVAL_STATUSES:
            findings.append(Finding("warn", f"{code_prefix}-approval-packet-status-unknown", f"approval packet status is unsupported: {status}", rel_path))
        elif status == "approved":
            findings.append(Finding("info", f"{code_prefix}-approval-packet-authority-boundary", "approval packet status=approved remains append-only evidence and cannot approve lifecycle by itself", rel_path))
        for field in ("input_refs", "human_gate_conditions"):
            value = data.get(field)
            if value not in (None, "") and not isinstance(value, list):
                findings.append(Finding("warn", f"{code_prefix}-approval-packet-malformed", f"approval packet {field} must be a list of strings", rel_path))
            if not _coordination_string_list(value):
                findings.append(Finding("warn", f"{code_prefix}-approval-packet-malformed", f"approval packet {field} must contain at least one value", rel_path))
        findings.extend(_coordination_ref_list_findings(root, data.get("input_refs"), rel_path, code_prefix, "approval-packet-input-ref", require_existing=True))
    return findings


def _coordination_agent_run_identity_findings(root: Path, code_prefix: str) -> list[Finding]:
    directory = root / AGENT_RUNS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return []
    retired_records, retirement_findings = agent_run_retired_records(root, code_prefix)
    findings: list[Finding] = [*retirement_findings]
    for path in sorted(directory.glob("*.md")):
        rel_path = _coordination_to_rel_path(root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code_prefix}-agent-run-malformed", "agent run record path is not a regular file", rel_path))
            continue
        if rel_path in retired_records:
            continue
        try:
            frontmatter = parse_frontmatter(path.read_text(encoding="utf-8"))
        except OSError as exc:
            findings.append(Finding("warn", f"{code_prefix}-agent-run-malformed", f"agent run record could not be read: {exc}", rel_path))
            continue
        data = frontmatter.data
        if not frontmatter.has_frontmatter:
            findings.append(Finding("warn", f"{code_prefix}-agent-run-malformed", "agent run record is missing frontmatter", rel_path))
            findings.append(agent_run_record_template_finding(rel_path, code_prefix))
            continue
        for error in frontmatter.errors:
            findings.append(Finding("warn", f"{code_prefix}-agent-run-malformed", error, rel_path))
        for field in AGENT_RUN_REQUIRED_SCALARS:
            value = data.get(field)
            if not isinstance(value, str) or not value.strip():
                findings.append(Finding("warn", f"{code_prefix}-agent-run-malformed", f"agent run record missing required field: {field}", rel_path))
        if data.get("schema") != AGENT_RUN_SCHEMA:
            findings.append(Finding("warn", f"{code_prefix}-agent-run-malformed", f"agent run record schema should be {AGENT_RUN_SCHEMA}", rel_path))
        if data.get("record_type") != "agent-run":
            findings.append(Finding("warn", f"{code_prefix}-agent-run-malformed", "agent run record record_type should be agent-run", rel_path))
        record_id = str(data.get("record_id") or "").strip()
        findings.extend(_coordination_record_id_findings(record_id, Path(rel_path).stem, rel_path, code_prefix, "agent-run", "record_id"))
        status = str(data.get("status") or "").strip()
        if status and status not in AGENT_RUN_STATUSES:
            findings.append(Finding("warn", f"{code_prefix}-agent-run-status-unknown", f"agent run record status is unsupported: {status}", rel_path))
        docs_decision = str(data.get("docs_decision") or "").strip()
        if docs_decision and docs_decision not in AGENT_RUN_DOCS_DECISIONS:
            findings.append(Finding("warn", f"{code_prefix}-agent-run-docs-decision-unknown", f"agent run record docs_decision is unsupported: {docs_decision}", rel_path))
        for field in AGENT_RUN_REQUIRED_LISTS:
            if not _coordination_string_list(data.get(field)):
                findings.append(Finding("warn", f"{code_prefix}-agent-run-malformed", f"agent run record missing required list field: {field}", rel_path))
        source_refs = _coordination_agent_run_source_refs(data)
        source_hash_refs = _coordination_source_hash_refs(data.get("source_hashes"), rel_path, code_prefix)
        findings.extend(source_hash_refs[1])
        for source_ref in sorted(source_refs - source_hash_refs[0]):
            findings.append(Finding("warn", f"{code_prefix}-agent-run-source-hash-missing", f"agent run record source_hashes does not bind source ref: {source_ref}", rel_path))
    return findings


def _coordination_json_records(
    root: Path,
    directory_rel: str,
    *,
    label: str,
    id_field: str,
    schema: str,
    record_type: str,
    code_prefix: str,
) -> tuple[list[tuple[str, dict[str, object]]], list[Finding]]:
    directory = root / directory_rel
    if not directory.exists() or not directory.is_dir():
        return [], []
    records: list[tuple[str, dict[str, object]]] = []
    findings: list[Finding] = []
    for path in sorted(directory.glob("*.json")):
        rel_path = _coordination_to_rel_path(root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code_prefix}-{label}-malformed", f"{label} record path is not a regular file", rel_path))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", f"{code_prefix}-{label}-malformed", f"{label} record could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", f"{code_prefix}-{label}-malformed", f"{label} record JSON root must be an object", rel_path))
            continue
        if data.get("schema") != schema:
            findings.append(Finding("warn", f"{code_prefix}-{label}-malformed", f"{label} schema should be {schema}", rel_path))
        if data.get("record_type") != record_type:
            findings.append(Finding("warn", f"{code_prefix}-{label}-malformed", f"{label} record_type should be {record_type}", rel_path))
        record_id = str(data.get(id_field) or "").strip()
        findings.extend(_coordination_record_id_findings(record_id, path.stem, rel_path, code_prefix, label, id_field))
        created_at = str(data.get("created_at_utc") or "").strip()
        if created_at and _coordination_parse_utc_timestamp(created_at) is None:
            findings.append(Finding("warn", f"{code_prefix}-{label}-provenance", f"{label} created_at_utc is not a valid UTC timestamp", rel_path))
        records.append((rel_path, data))
    return records, findings


def _coordination_record_id_findings(record_id: str, filename_stem: str, rel_path: str, code_prefix: str, label: str, id_field: str) -> list[Finding]:
    findings: list[Finding] = []
    if not record_id:
        findings.append(Finding("warn", f"{code_prefix}-{label}-id-missing", f"{label} {id_field} is required", rel_path))
        return findings
    if not COORDINATION_RECORD_ID_RE.match(record_id):
        findings.append(Finding("warn", f"{code_prefix}-{label}-id-malformed", f"{label} {id_field} may contain only letters, digits, dot, underscore, or dash", rel_path))
    elif record_id_conflict(record_id):
        findings.append(Finding("warn", f"{code_prefix}-{label}-id-malformed", f"{label} {id_field} {record_id_conflict(record_id)}", rel_path))
    if filename_stem != record_id:
        findings.append(Finding("warn", f"{code_prefix}-{label}-id-mismatch", f"{label} filename stem {filename_stem} does not match {id_field} {record_id}", rel_path))
    return findings


def _coordination_ref_list_findings(root: Path, value: object, rel_path: str, code_prefix: str, label: str, *, require_existing: bool) -> list[Finding]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        return [Finding("warn", f"{code_prefix}-{label}-malformed", f"{label} must be a list of strings", rel_path)]
    findings: list[Finding] = []
    for ref in _coordination_string_list(value):
        findings.extend(_coordination_ref_shape_findings(root, ref, rel_path, code_prefix, label, require_existing=require_existing))
    return findings


def _coordination_ref_shape_findings(root: Path, ref: str, rel_path: str, code_prefix: str, label: str, *, require_existing: bool) -> list[Finding]:
    normalized = _coordination_normalize_ref(ref)
    findings: list[Finding] = []
    conflict = root_relative_path_conflict(normalized)
    if conflict:
        return [Finding("warn", f"{code_prefix}-{label}-invalid", f"{label} {conflict}: {normalized}", rel_path)]
    target = root / normalized
    boundary_violation = source_path_boundary_violation(root, target, label=label)
    if boundary_violation is not None:
        return [Finding("warn", f"{code_prefix}-{label}-invalid", boundary_violation.message, rel_path)]
    if require_existing:
        if not target.exists():
            findings.append(Finding("warn", f"{code_prefix}-{label}-missing", f"{label} is missing: {normalized}", rel_path))
        elif target.is_symlink() or not target.is_file():
            findings.append(Finding("warn", f"{code_prefix}-{label}-invalid", f"{label} is not a regular file: {normalized}", rel_path))
    return findings


def _coordination_agent_run_source_refs(data: dict[str, object]) -> set[str]:
    refs: set[str] = set()
    for field in ("claimed_paths", "changed_files"):
        refs.update(_coordination_string_list(data.get(field)))
    normalized_refs = {_coordination_normalize_ref(ref) for ref in refs if _coordination_normalize_ref(ref)}
    return {ref for ref in normalized_refs if _coordination_source_hash_required(ref)}


def _coordination_source_hash_required(rel_path: str) -> bool:
    return rel_path in COORDINATION_SOURCE_HASH_REQUIRED_FILES or rel_path.startswith(COORDINATION_SOURCE_HASH_REQUIRED_PREFIXES)


def _coordination_source_hash_refs(value: object, rel_path: str, code_prefix: str) -> tuple[set[str], list[Finding]]:
    refs: set[str] = set()
    findings: list[Finding] = []
    if value not in (None, "") and not isinstance(value, list):
        findings.append(Finding("warn", f"{code_prefix}-agent-run-source-hash-malformed", "agent run source_hashes must be a list of strings", rel_path))
    for entry in _coordination_string_list(value):
        match = COORDINATION_SOURCE_HASH_RE.match(entry.strip())
        if not match:
            findings.append(Finding("warn", f"{code_prefix}-agent-run-source-hash-malformed", f"malformed source_hashes entry: {entry}", rel_path))
            continue
        source_ref = _coordination_normalize_ref(match.group(1))
        refs.add(source_ref)
        conflict = root_relative_path_conflict(source_ref)
        if conflict:
            findings.append(Finding("warn", f"{code_prefix}-agent-run-source-hash-malformed", f"source_hashes path {conflict}: {source_ref}", rel_path))
    return refs, findings


def _coordination_string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _coordination_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, list):
        return any(_coordination_truthy(item) for item in value)
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "required", "enabled", "on"}


def _coordination_normalize_ref(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lstrip("./")


def _coordination_parse_utc_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coordination_to_rel_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _coordination_evidence_boundary_findings(code_prefix: str) -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-authority-boundary",
            "coordination evidence can block clean posture, dispatcher launch confidence, or fan-in review, but it cannot approve lifecycle, archive, roadmap status, staging, commit, push, release, or worker cleanup",
            "project/verification",
        )
    ]
DEFAULT_PLAN_REL = "project/implementation-plan.md"
PHASE_WRITEBACK_BEGIN = "<!-- BEGIN mylittleharness-phase-writeback v1 -->"
PHASE_WRITEBACK_END = "<!-- END mylittleharness-phase-writeback v1 -->"
AUTO_CONTINUE_STOP_COVERAGE = (
    ("verification", ("verification", "deterministic success", "success signal")),
    ("authority", ("docs", "api", "lifecycle authority", "root classification")),
    ("write_scope", ("write scope", "write-scope", "execution slice")),
    ("source_reality", ("source reality", "future phase", "dependency", "schema")),
    ("sensitive_action", ("destructive", "sensitive")),
    ("closeout_boundary", ("closeout", "archive", "next-slice", "next slice")),
)

EXPECTED_PRODUCT_NAME = "MyLittleHarness"
EXPECTED_PRODUCT_ROOT_ROLE = "product-source"
EXPECTED_PRODUCT_FIXTURE_STATUS = "product-compatibility-fixture"
ROOT_RELATIVE_LINK_PREFIXES = (
    ".mylittleharness/",
    ".agents/",
    ".codex/",
    "docs/",
    "project/",
    "specs/",
    "src/",
    "tests/",
    "build_backend/",
)
ROOT_RELATIVE_LINK_NAMES = {"README.md", "AGENTS.md", "pyproject.toml"}
SNAPSHOT_REPAIR_ROOT_REL = ".mylittleharness/snapshots/repair"
SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_DRY_RUN_TIMESTAMP = "00000000T000000Z"
DOCMAP_REPAIR_CLASS = "docmap-route-repair"
DOCMAP_CREATE_CLASS = "docmap-create"
DOCMAP_REPAIR_TARGET_REL = ".agents/docmap.yaml"
DOCMAP_REPAIR_TARGET_SLUG = "agents-docmap-yaml"
DOCMAP_REPAIR_COPY_REL = "files/.agents/docmap.yaml"
LIFECYCLE_MARKDOWN_FRONTMATTER_REPAIR_CLASS = "lifecycle-markdown-frontmatter-repair"
LIFECYCLE_SOURCE_PROVENANCE_REPAIR_CLASS = "lifecycle-source-provenance-repair"
SPEC_POSTURE_FRONTMATTER_REPAIR_CLASS = "spec-posture-frontmatter-repair"
STABLE_SPEC_CREATE_CLASS = "stable-spec-create"
STABLE_SPEC_ROOT_REL = "project/specs/workflow"
STABLE_SPEC_TEMPLATE_PACKAGE = "mylittleharness"
STABLE_SPEC_TEMPLATE_REL = ("templates", "workflow")
AGENTS_CONTRACT_CREATE_CLASS = "agents-contract-create"
AGENTS_CONTRACT_TARGET_REL = "AGENTS.md"
AGENTS_CONTRACT_TEMPLATE_REL = ("templates", "operating-root", "AGENTS.md")
STATE_FRONTMATTER_REPAIR_CLASS = "state-frontmatter-repair"
STATE_FRONTMATTER_TARGET_REL = "project/project-state.md"
STATE_FRONTMATTER_TARGET_SLUG = "project-project-state-md"
STATE_FRONTMATTER_COPY_REL = "files/project/project-state.md"
STATE_FRONTMATTER_OPTIONAL_KEYS = (
    "active_phase",
    "phase_status",
    "last_archived_plan",
    "operating_root",
    "canonical_source_evidence_root",
    "product_source_root",
    "projection_root",
    "projection_status",
    "historical_fallback_root",
)
SNAPSHOT_METADATA_FIELDS = (
    "schema_version",
    "created_at_utc",
    "tool_name",
    "tool_version",
    "command",
    "root_kind",
    "repair_class",
    "target_root",
    "snapshot_root",
    "target_paths",
    "copied_files",
    "pre_repair_hashes",
    "planned_post_repair_paths",
    "source_diagnostics",
    "planned_route_entries",
    "retention",
    "rollback_instructions",
    "authority_note",
)
CHECK_DRIFT_CODES = {
    "candidate-docmap-gap",
    "stale-fallback-root-reference",
    "stale-product-root-role",
    "stale-operating-root-role",
}
RULE_CONTEXT_PRIMARY_SURFACES = (
    "AGENTS.md",
    "README.md",
    ".agents/docmap.yaml",
    WORKFLOW_MANIFEST_REL,
    LEGACY_WORKFLOW_MANIFEST_REL,
    "project/project-state.md",
)
REMAINDER_DRIFT_SURFACE_ROLES = {
    "active-plan",
    "incubation",
    "project-state",
    "research",
}
DELIVERED_CONTEXT_MARKERS = (
    "completed",
    "current implementation",
    "delivered",
    "implemented",
    "now accepts",
    "now creates",
    "now reports",
    "shipped",
    "substantially narrowed",
)
REMAINDER_CONTEXT_MARKERS = (
    "backlog",
    "candidate",
    "deferred",
    "future",
    "not yet implemented",
    "open",
    "planned",
    "remainder",
    "remaining",
    "still open",
    "todo",
)
HISTORICAL_CONTEXT_MARKERS = (
    "archive",
    "archived",
    "changelog",
    "historical",
    "history",
    "old lane",
    "past release",
    "prior release",
    "release history",
    "superseded",
)
PHASE_STATUS_VALUES = {
    "pending",
    "active",
    "in_progress",
    "blocked",
    "complete",
    "skipped",
    "paused",
}
PHASE_BODY_TERMINAL_STATUS_VALUES = {"complete", "done", "skipped"}
DOCS_DECISION_VALUES = {"updated", "not-needed", "uncertain"}
INCOMPLETE_EVIDENCE_VALUES = {"", "pending", "uncertain", "unknown", "tbd", "todo"}
SPEC_STATUS_VALUES = ("draft", "accepted", "superseded", "archived")
SPEC_IMPLEMENTATION_POSTURE_VALUES = (
    "not-applicable",
    "target-only",
    "in-progress",
    "partially-verified",
    "synced",
    "drift-detected",
    "deprecated-compat",
    "retired",
)
SPEC_LIFECYCLE_FIELDS = ("spec_status", "implementation_posture")
SPEC_POSTURE_REPAIR_DEFAULTS = {
    "spec_status": "draft",
    "implementation_posture": "target-only",
}
SPEC_IMPLEMENTATION_EVIDENCE_FIELDS = (
    "implemented_by",
    "verification_refs",
    "related_verification",
    "closeout_evidence",
    "implementation_evidence",
)
SPEC_CARRY_FORWARD_FIELDS = (
    "carry_forward",
    "related_plan",
    "related_roadmap",
    "related_decision",
    "related_adr",
    "amendment_plan",
    "replan_route",
    "drift_record",
    "superseded_by",
)
SPEC_SUPERSESSION_TARGET_FIELDS = (
    "superseded_by",
    "replacement",
    "replacement_route",
    "retirement_path",
    "deprecation_path",
    "archived_to",
)
ROUTE_METADATA_VALIDATED_ROUTES = {"adrs", "attachments", "decisions", "incubation", "research", "roadmap", "stable-specs", "verification"}
ROUTE_METADATA_STATUS_VALUES = {
    "accepted",
    "active",
    "archived",
    "blocked",
    "complete",
    "compared",
    "deferred",
    "distilled",
    "done",
    "draft",
    "failed",
    "implemented",
    "imported",
    "incubating",
    "in_progress",
    "in-progress",
    "partial",
    "partially-verified",
    "partially_verified",
    "passed",
    "paused",
    "pending",
    "proposed",
    "promoted",
    "rejected",
    "research-ready",
    "skipped",
    "stale",
    "synced",
    "drift-detected",
    "drift_detected",
    "superseded",
}
ROUTE_METADATA_STATUS_HINTS_BY_ROUTE = {
    "adrs": ("draft", "accepted", "superseded", "archived"),
    "attachments": ("imported", "archived", "stale"),
    "decisions": ("draft", "accepted", "superseded", "archived"),
    "incubation": ("incubating", "implemented", "rejected", "superseded", "archived", "stale"),
    "research": ("imported", "distilled", "compared", "research-ready", "accepted", "superseded", "archived", "stale"),
    "roadmap": ("proposed", "accepted", "active", "blocked", "done", "deferred", "rejected", "superseded"),
    "stable-specs": ("draft", "accepted", "synced", "stale", "superseded", "archived"),
    "verification": ("pending", "passed", "failed", "partial", "partially-verified", "archived"),
}
ROUTE_METADATA_LIFECYCLE_STATES = {
    "draft": (
        "intake recorded but not accepted as implementation truth",
        "mylittleharness --root <root> intake --dry-run --text \"<text>\"",
    ),
    "accepted": (
        "explicitly accepted for planning or route ownership, but not implemented by that fact alone",
        "mylittleharness --root <root> plan --dry-run --roadmap-item <id>",
    ),
    "synced": (
        "declared source and evidence are aligned as of the latest recorded check",
        "mylittleharness --root <root> check",
    ),
    "partially_verified": (
        "some evidence exists, but deterministic verification is incomplete",
        "mylittleharness --root <root> evidence",
    ),
    "stale": (
        "recorded source or evidence may lag current repo-visible authority",
        "mylittleharness --root <root> check --deep",
    ),
    "drift_detected": (
        "repo-visible authority disagrees with recorded route metadata or evidence",
        "mylittleharness --root <root> suggest --intent reconcile drift",
    ),
    "superseded": (
        "route has been replaced and should point at superseding authority before reuse",
        "mylittleharness --root <root> check",
    ),
    "archived": (
        "route is historical evidence only unless explicitly reopened through a lifecycle command",
        "mylittleharness --root <root> check",
    ),
}
ROUTE_METADATA_SCALAR_PATH_FIELDS = {"archived_to", "promoted_to"}
ROUTE_METADATA_FLEXIBLE_PATH_FIELDS = {
    "attachment_refs",
    "related_adr",
    "related_adrs",
    "related_attachments",
    "related_decision",
    "related_decisions",
    "related_doc",
    "related_docs",
    "related_incubation",
    "related_plan",
    "related_roadmap",
    "related_research",
    "related_spec",
    "related_specs",
    "related_verification",
    "archived_plan",
    "source_attachments",
    "source_incubation",
    "source_members",
    "source_roadmap",
    "source_research",
    "implemented_by",
    "merged_from",
    "merged_into",
    "rejected_by",
    "split_from",
    "split_to",
    "superseded_by",
    "supersedes",
}
ROUTE_METADATA_PROMOTION_TARGET_ROUTES = {
    "active-plan",
    "adrs",
    "decisions",
    "operating-guardrails",
    "product-docs",
    "roadmap",
    "stable-specs",
    "state",
    "verification",
}
ARCHIVE_CONTEXT_ARCHIVE_DIR_REL = "project/archive/plans"
ARCHIVE_CONTEXT_SOURCE_FIELDS = ("source_incubation", "related_incubation", "source_research", "related_research")
ARCHIVE_CONTEXT_ARCHIVED_SOURCE_PREFIXES = (
    ("project/plan-incubation/", "project/archive/reference/incubation/"),
    ("project/research/", "project/archive/reference/research/"),
)
ROUTE_REFERENCE_SCAN_EXTRA_GLOBS = (
    "project/archive/plans/*.md",
    "project/archive/reference/**/*.md",
    ".mylittleharness/generated/projection/**/*.json",
)
ROUTE_REFERENCE_METADATA_FIELDS = frozenset(
    {
        "active_plan",
        "last_archived_plan",
        "dependencies",
        "slice_dependencies",
        "target_artifacts",
        "covered_roadmap_items",
        *ROUTE_METADATA_SCALAR_PATH_FIELDS,
        *ROUTE_METADATA_FLEXIBLE_PATH_FIELDS,
    }
)
ROUTE_REFERENCE_ACCEPTED_STATUSES = {"active", "accepted", "in_progress", "in-progress", "pending"}
ROUTE_REFERENCE_TERMINAL_STATUSES = {"done", "complete", "implemented", "archived", "superseded", "rejected"}
ROUTE_REFERENCE_WARN_CLASSES = {"required-lifecycle-evidence", "accepted-work-evidence", "stale-metadata"}
ROUTE_REFERENCE_TEXT_REF_RE = re.compile(
    r"(?<![\w:/.-])"
    r"((?:\.mylittleharness|\.agents|\.codex|docs|project|specs|src|tests)/[A-Za-z0-9_./{}*\-]+"
    r"|README\.md|AGENTS\.md|pyproject\.toml)"
    r"(?![\w/.-])"
)
ROUTE_REFERENCE_TEXT_ONLY_LABELS = {
    "docs/api",
    "docs/spec/package",
    "docs/tests",
    "tests/check",
    "tests/checks",
    "tests/docs",
}
ROUTE_REFERENCE_OPTIONAL_EVIDENCE_ROUTES = {
    "project/verification/agent-runs",
    "project/verification/approval-packets",
    "project/verification/work-claims",
}
PRODUCT_DOC_EVIDENCE_POSTURE_PATH_MARKERS = (
    "verification",
    "verified",
    "evidence",
    "runbook",
    "smoke",
    "handoff",
    "approval",
    "audit",
)
PRODUCT_DOC_EVIDENCE_POSTURE_TEXT_MARKERS = (
    "verification",
    "verification evidence",
    "evidence",
    "runbook",
    "smoke check",
    "handoff",
    "approval",
    "audit",
)
ROUTE_REFERENCE_SAMPLE_LIMIT = 12
ARCHIVE_CONTEXT_RECONSTRUCTED_MARKERS = (
    "reconstructed",
    "recovered from roadmap",
    "recreated from roadmap",
    "restored from roadmap",
    "recovered note",
    "source evidence was recovered",
)
ARCHIVE_CONTEXT_SUSPECT_MARKERS = (
    "suspect-incomplete",
    "proceeded from compact roadmap",
    "compact roadmap title/carry_forward only",
    "source notes were missing",
    "missing source notes",
    "incomplete input context",
)
ARCHIVE_CONTEXT_DIAGNOSTIC_MARKERS = (
    "archive context completeness audit",
    "archive-context-completeness-audit",
    "context-completeness audit",
    "diagnostic/reporting only",
    "bounded recovery actions",
    "accepted roadmap source_incubation evidence can be absent without a targeted check",
    "missing accepted-item source_incubation evidence",
    "suggest a bounded recovery route",
)
ARCHIVE_CONTEXT_SAMPLE_LIMIT = 12
ARCHIVE_CONTEXT_CAUSE_SAMPLE_LIMIT = 5
LIFECYCLE_ROUTE_ROWS = lifecycle_route_rows()


@dataclass(frozen=True)
class IntakeRequest:
    text: str
    text_source: str
    title: str
    target: str
    status: str = ""
    related_plan: str = ""
    source_members: tuple[str, ...] = ()


INTAKE_VERIFICATION_STATUS_VALUES = ("pending", "passed", "failed", "partial", "partially-verified", "archived")
INTAKE_DECISION_PACKET_FIELDS = (
    "confirmed_fixes",
    "new_slice_candidates",
    "scope_expansions",
    "blocked_followups",
    "safe_to_continue_existing_sequence",
)


@dataclass(frozen=True)
class ArchiveContextRouteRef:
    owner: str
    field: str
    status: str
    source: str
    line: int | None = None


@dataclass(frozen=True)
class RouteReferenceRecord:
    target: str
    source: str
    line: int | None
    owner: str
    field: str
    owner_status: str = ""
    context: str = ""


@dataclass(frozen=True)
class RouteReferenceRecoveryGuidance:
    action: str
    next_safe_command: str
    boundary: str


@dataclass(frozen=True)
class SpecPostureFrontmatterPlan:
    rel_path: str
    route_id: str
    fields: dict[str, str]
    current_text: str
    updated_text: str


def make_intake_request(
    text: str | None,
    text_source: str,
    title: str | None,
    target: str | None,
    status: str | None = None,
    related_plan: str | None = None,
    source_members: tuple[str, ...] | list[str] | None = None,
) -> IntakeRequest:
    return IntakeRequest(
        text=str(text or ""),
        text_source=str(text_source or "").strip() or "intake input",
        title=str(title or "").strip(),
        target=_normalized_intake_target(target),
        status=str(status or "").strip(),
        related_plan=_normalized_intake_metadata_path(related_plan),
        source_members=_normalized_intake_metadata_paths(source_members or ()),
    )


def intake_dry_run_findings(inventory: Inventory, request: IntakeRequest) -> list[Finding]:
    findings = [
        Finding("info", "intake-dry-run", "intake route proposal only; no files were written"),
        Finding("info", "intake-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    advice = _intake_request_advice(request)
    errors = _intake_request_errors(inventory, request, apply=False, advice=advice)
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.extend(_intake_incubation_fallback_findings(request, advice))
        findings.append(Finding("info", "intake-validation-posture", "dry-run refused before apply; classify the input and rerun dry-run before writing intake"))
        return findings

    findings.extend(_intake_advice_findings(advice, request, prefix="would "))
    if request.target:
        findings.extend(_intake_target_preview_findings(request, advice))
    findings.extend(_intake_incubation_fallback_findings(request, advice))
    findings.extend(_intake_boundary_findings())
    findings.append(
        Finding(
            "info",
            "intake-validation-posture",
            "apply would write one explicit new Markdown target in a compatible route; dry-run writes no files",
            request.target or None,
        )
    )
    return findings


def intake_apply_findings(inventory: Inventory, request: IntakeRequest) -> list[Finding]:
    advice = _intake_request_advice(request)
    errors = _intake_request_errors(inventory, request, apply=True, advice=advice)
    if errors:
        return errors

    target_path = inventory.root / request.target
    document = _intake_document_text(inventory, request, advice)
    operation = AtomicFileWrite(
        target_path=target_path,
        tmp_path=target_path.with_name(f".{target_path.name}.intake.tmp"),
        text=document,
        backup_path=target_path.with_name(f".{target_path.name}.intake.backup"),
    )
    try:
        cleanup_warnings = apply_file_transaction([operation], root=inventory.root)
    except FileTransactionError as exc:
        return [Finding("error", "intake-refused", f"intake apply failed before the target write completed: {exc}", request.target)]

    findings = [
        Finding("info", "intake-apply", "intake apply started"),
        Finding("info", "intake-root-posture", f"root kind: {inventory.root_kind}"),
        Finding("info", "intake-written", f"wrote routed intake note to {request.target}", request.target),
    ]
    findings.extend(_intake_advice_findings(advice, request, prefix=""))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "intake-backup-cleanup", warning, request.target))
    findings.extend(_intake_boundary_findings())
    findings.append(
        Finding(
            "info",
            "intake-validation-posture",
            "run check after apply to verify the live operating root remains healthy; intake output is not lifecycle approval",
            request.target,
        )
    )
    return findings


def status_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    state = inventory.state
    data = state.frontmatter.data if state else {}
    findings.append(Finding("info", "root-kind", f"root kind: {inventory.root_kind}"))
    findings.extend(_product_posture_status_findings(inventory))
    findings.extend(_meta_feedback_destination_status_findings(inventory))
    findings.extend(lifecycle_route_findings(inventory))
    findings.extend(lifecycle_summary_findings(inventory))
    for key in (
        "project",
        "root_role",
        "fixture_status",
        "operating_mode",
        "plan_status",
        "active_plan",
        "active_phase",
        "phase_status",
        "operating_root",
        "product_source_root",
        "projection_status",
    ):
        value = data.get(key)
        if value not in (None, ""):
            findings.append(Finding("info", "state-field", f"{key}: {value}", state.rel_path if state else None))

    if inventory.active_plan_surface and inventory.active_plan_surface.exists:
        findings.append(
            Finding(
                "info",
                "active-plan",
                f"active plan present: {inventory.active_plan_surface.rel_path}",
                inventory.active_plan_surface.rel_path,
            )
        )
    else:
        findings.append(Finding("info", "active-plan", "no active plan file is required by current state"))

    required_total = len([surface for surface in inventory.surfaces if surface.required])
    required_present = len([surface for surface in inventory.surfaces if surface.required and surface.exists])
    optional_present = len([surface for surface in inventory.surfaces if not surface.required and surface.exists])
    findings.append(
        Finding(
            "info",
            "surface-inventory",
            f"required surfaces present: {required_present}/{required_total}; optional surfaces present: {optional_present}",
        )
    )

    source_root = data.get("operating_root") or data.get("canonical_source_evidence_root")
    product_root = data.get("product_source_root") or data.get("projection_root")
    if source_root:
        findings.append(Finding("info", "operating-root", f"operating root: {source_root}", state.rel_path if state else None))
    if product_root:
        findings.append(Finding("info", "product-root", f"product source root: {product_root}", state.rel_path if state else None))
    marker = inventory.surface_by_rel.get(DETACH_MARKER_REL_PATH)
    if marker and marker.exists:
        findings.extend(_detach_marker_status_findings(inventory, marker))
    return findings


def _meta_feedback_destination_status_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    if not meta_feedback_env_destination_root():
        return []
    data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    project = data.get("project")
    if project == CENTRAL_META_FEEDBACK_PROJECT:
        return [
            Finding(
                "info",
                "meta-feedback-central-destination",
                (
                    f"this root is the central {CENTRAL_META_FEEDBACK_PROJECT} destination for canonical "
                    "MLH-Fix-Candidate incubation notes and cluster metadata; observed roots remain provenance"
                ),
                inventory.state.rel_path if inventory.state else None,
            )
        ]
    return [
        Finding(
            "info",
            "meta-feedback-central-destination",
            (
                f"canonical MLH product-debt meta-feedback should route to the central {CENTRAL_META_FEEDBACK_PROJECT} "
                f"live operating root with --to-root or {META_FEEDBACK_ROOT_ENV_VAR}; this local live root is provenance only"
            ),
            inventory.state.rel_path if inventory.state else None,
        )
    ]


def lifecycle_summary_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    plan_status = str(data.get("plan_status") or "")
    active_phase = str(data.get("active_phase") or "")
    phase_status = str(data.get("phase_status") or "")
    active_plan = str(data.get("active_plan") or "project/implementation-plan.md")
    source = state.rel_path if state else None
    if plan_status == "active":
        phase_label = f"; active_phase: {active_phase}" if active_phase else ""
        if phase_status == "complete":
            return [
                Finding(
                    "info",
                    "lifecycle-summary",
                    (
                        f"active plan phase is complete{phase_label}; implementation work is not pending and the active plan is ready for explicit closeout/writeback; "
                        "phase completion alone does not approve auto-continue, archive, roadmap done-status, next-slice opening, or commit"
                    ),
                    source,
                )
            ]
        if phase_status in {"active", "in_progress"}:
            return [
                Finding(
                    "info",
                    "lifecycle-summary",
                    (
                        f"active plan is in progress{phase_label}; current-phase-only default continues from "
                        "project-state active_phase and stops after repo-visible state/evidence unless explicit auto_continue is safe"
                    ),
                    source,
                )
            ]
        if phase_status in {"blocked", "paused"}:
            return [
                Finding(
                    "warn",
                    "lifecycle-summary",
                    f"active plan is {phase_status}{phase_label}; resolve the blocker or update lifecycle state before continuing",
                    source,
                )
            ]
        if phase_status == "skipped":
            return [
                Finding(
                    "info",
                    "lifecycle-summary",
                    f"active plan phase is skipped{phase_label}; next action is explicit lifecycle writeback or archive decision",
                    source,
                )
            ]
        return [
            Finding(
                "info",
                "lifecycle-summary",
                (
                    f"active plan is open at {active_plan}; phase_status is {phase_status or 'not recorded'}; "
                    "current-phase-only default requires an explicit lifecycle decision before any next phase"
                ),
                source,
            )
        ]
    if plan_status in {"", "none"}:
        return [Finding("info", "lifecycle-summary", "no active implementation plan is open", source)]
    return [
        Finding(
            "warn",
            "lifecycle-summary",
            f"plan_status is {plan_status!r}; expected active or none for normal continuation",
            source,
        )
    ]


def _validation_status_scope_findings(inventory: Inventory) -> list[Finding]:
    findings = [finding for finding in lifecycle_summary_findings(inventory) if finding.severity in {"error", "warn"}]
    marker = inventory.surface_by_rel.get(DETACH_MARKER_REL_PATH)
    if marker and marker.exists:
        findings.extend(finding for finding in _detach_marker_status_findings(inventory, marker) if finding.severity in {"error", "warn"})
    return findings


def lifecycle_route_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    findings = [
        Finding(
            "info",
            "lifecycle-route-table",
            (
                "canonical lifecycle route table for live operating roots; "
                "advisory only and cannot approve mutation, repair, closeout, archive, commit, or lifecycle decisions"
            ),
        )
    ]
    findings.extend(
        Finding("info", "lifecycle-route", f"{name}: {target}; {purpose}")
        for name, target, purpose in LIFECYCLE_ROUTE_ROWS
    )
    return findings


def memory_route_inventory_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []

    surfaces = [surface for surface in inventory.present_surfaces if surface.memory_route]
    if not surfaces:
        return [Finding("info", "memory-route-inventory", "no present repo-visible surfaces were classified")]

    route_counts: dict[str, list[Surface]] = {}
    for surface in surfaces:
        route_counts.setdefault(surface.memory_route, []).append(surface)

    findings = [
        Finding(
            "info",
            "memory-route-inventory",
            f"classified {len(surfaces)} present repo-visible surface(s) into {len(route_counts)} memory route(s)",
        )
    ]
    for route_id in _ordered_route_ids(route_counts):
        route = ROUTE_BY_ID.get(route_id)
        route_surfaces = sorted(route_counts[route_id], key=lambda item: item.rel_path)
        examples = ", ".join(surface.rel_path for surface in route_surfaces[:3])
        if len(route_surfaces) > 3:
            examples += f", +{len(route_surfaces) - 3} more"
        target = route.target if route else "<unknown>"
        findings.append(
            Finding(
                "info",
                "memory-route",
                f"{route_id}: {len(route_surfaces)} surface(s); target: {target}; examples: {examples}",
            )
        )

    for surface in sorted(surfaces, key=lambda item: item.rel_path):
        route = ROUTE_BY_ID.get(surface.memory_route)
        purpose = route.purpose if route else "unknown route"
        findings.append(
            Finding(
                "info",
                "memory-route-surface",
                f"{surface.rel_path} -> {surface.memory_route}; {purpose}",
                surface.rel_path,
            )
        )
    return findings


def _ordered_route_ids(route_counts: dict[str, list[Surface]]) -> list[str]:
    registry_order = {route_id: index for index, route_id in enumerate(ROUTE_BY_ID)}
    return sorted(route_counts, key=lambda route_id: (registry_order.get(route_id, len(registry_order)), route_id))


def _nonroute_project_markdown_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    project_root = inventory.root / "project"
    if not project_root.is_dir():
        return []

    findings: list[Finding] = []
    for path in sorted(project_root.rglob("*.md")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(inventory.root).as_posix()
        if _is_nonroute_project_markdown_exempt(rel_path):
            continue
        if classify_memory_route(rel_path).route_id != "unclassified":
            continue
        findings.append(
            Finding(
                "warn",
                "nonroute-project-markdown-blind-spot",
                (
                    f"{rel_path} is project Markdown outside the MLH-visible route inventory; route durable knowledge "
                    "through intake or an owned project/adrs, project/decisions, project/research, project/plan-incubation, "
                    "or project/verification lane"
                ),
                rel_path,
            )
        )
    return findings


def _is_nonroute_project_markdown_exempt(rel_path: str) -> bool:
    normalized = str(rel_path or "").replace("\\", "/").casefold()
    return any(normalized.startswith(prefix) for prefix in NONROUTE_PROJECT_MARKDOWN_EXEMPT_PREFIXES)


def symphony_queue_dependency_findings(inventory: Inventory, code_prefix: str = "symphony-queue") -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    directory = inventory.root / SYMPHONY_QUEUE_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return []

    records: list[tuple[str, dict[str, object]]] = []
    findings: list[Finding] = [
        Finding(
            "info",
            f"{code_prefix}-read-only",
            (
                "Symphony queue dependency diagnostics are read-only; queue JSON files remain repo-visible "
                "coordination evidence and this report writes no dispatcher, lifecycle, generated cache, or Git state"
            ),
            SYMPHONY_QUEUE_DIR_REL,
        )
    ]
    for path in sorted(directory.glob("*.json")):
        rel_path = _coordination_to_rel_path(inventory.root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code_prefix}-item-malformed", "queue item path is not a regular file", rel_path))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", f"{code_prefix}-item-malformed", f"queue item could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", f"{code_prefix}-item-malformed", "queue item JSON root must be an object", rel_path))
            continue
        schema = str(data.get("schema") or "").strip()
        if schema and schema != SYMPHONY_QUEUE_SCHEMA:
            findings.append(Finding("info", f"{code_prefix}-schema-advisory", f"queue item schema is external/advisory for MLH diagnostics: {schema}", rel_path))
        records.append((rel_path, data))

    current_by_key = _symphony_queue_current_item_index(records)
    for rel_path, data in records:
        for dependency in _symphony_queue_blocked_by_items(data.get("blocked_by")):
            current = _symphony_queue_resolve_dependency(inventory.root, current_by_key, dependency)
            dependency_label = _symphony_queue_dependency_label(dependency)
            snapshot_state = str(dependency.get("state") or "").strip()
            if current is None:
                findings.append(
                    Finding(
                        "warn",
                        f"{code_prefix}-blocked-by-unresolved",
                        f"blocked_by dependency {dependency_label} could not be resolved to a current queue item; embedded state remains advisory only",
                        rel_path,
                    )
                )
                continue
            current_rel, current_data = current
            current_state = str(current_data.get("state") or "").strip()
            if snapshot_state and current_state and snapshot_state.casefold() != current_state.casefold():
                findings.append(
                    Finding(
                        "warn",
                        f"{code_prefix}-blocked-by-stale-state",
                        (
                            f"blocked_by dependency {dependency_label} embeds state {snapshot_state}, but authoritative current "
                            f"queue state is {current_state} from {current_rel}; resolve current dependency state before blocking"
                        ),
                        rel_path,
                    )
                )
            elif current_state:
                findings.append(
                    Finding(
                        "info",
                        f"{code_prefix}-blocked-by-current",
                        f"blocked_by dependency {dependency_label} resolves to current queue state {current_state} from {current_rel}",
                        rel_path,
                    )
                )
    findings.append(
        Finding(
            "info",
            f"{code_prefix}-blocked-by-advisory-boundary",
            (
                "blocked_by state snapshots are advisory; dependent agents must resolve current dependency state from "
                "project/symphony/queue/*.json before concluding Todo, Done, or Blocked"
            ),
            SYMPHONY_QUEUE_DIR_REL,
        )
    )
    return findings


def _symphony_queue_current_item_index(records: list[tuple[str, dict[str, object]]]) -> dict[str, tuple[str, dict[str, object]]]:
    current_by_key: dict[str, tuple[str, dict[str, object]]] = {}
    for rel_path, data in records:
        for value in (
            rel_path,
            Path(rel_path).stem,
            data.get("id"),
            data.get("identifier"),
            data.get("queue_item_id"),
            data.get("item_id"),
        ):
            key = _symphony_queue_key(value)
            if key:
                current_by_key.setdefault(key, (rel_path, data))
    return current_by_key


def _symphony_queue_blocked_by_items(value: object) -> tuple[dict[str, object], ...]:
    if isinstance(value, list):
        blockers: list[dict[str, object]] = []
        for item in value:
            if isinstance(item, dict):
                blockers.append(dict(item))
            elif str(item).strip():
                blockers.append({"id": str(item).strip()})
        return tuple(blockers)
    if isinstance(value, dict):
        return (dict(value),)
    if isinstance(value, str) and value.strip():
        return ({"id": value.strip()},)
    return ()


def _symphony_queue_resolve_dependency(
    root: Path,
    current_by_key: dict[str, tuple[str, dict[str, object]]],
    dependency: dict[str, object],
) -> tuple[str, dict[str, object]] | None:
    for field in ("id", "identifier", "queue_item_id", "item_id", "path", "ref", "url"):
        value = dependency.get(field)
        key = _symphony_queue_key(value)
        if key and key in current_by_key:
            return current_by_key[key]
        rel = _symphony_queue_ref_to_rel(root, value)
        if rel and rel in current_by_key:
            return current_by_key[rel]
    return None


def _symphony_queue_ref_to_rel(root: Path, value: object) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return ""
    if "://" in text:
        return ""
    while text.startswith("./"):
        text = text[2:]
    conflict = root_relative_path_conflict(text)
    if conflict:
        return ""
    path = Path(text)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root.resolve()).as_posix().casefold()
        except (OSError, RuntimeError, ValueError):
            return ""
    return text.strip("/").casefold()


def _symphony_queue_key(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/").casefold()


def _symphony_queue_dependency_label(dependency: dict[str, object]) -> str:
    for field in ("id", "identifier", "queue_item_id", "item_id", "path", "ref", "url"):
        value = str(dependency.get(field) or "").strip()
        if value:
            return f"{field}={value}"
    return "<unlabeled>"


def validation_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_required_surface_findings(inventory))
    findings.extend(_manifest_findings(inventory))
    findings.extend(_state_findings(inventory))
    findings.extend(_validation_status_scope_findings(inventory))
    findings.extend(_incubation_contract_findings(inventory))
    findings.extend(_product_posture_findings(inventory))
    findings.extend(_active_plan_findings(inventory))
    findings.extend(_spec_findings(inventory))
    findings.extend(_spec_lifecycle_posture_findings(inventory))
    findings.extend(_frontmatter_findings(inventory))
    findings.extend(_route_metadata_findings(inventory))
    findings.extend(_changed_route_metadata_findings(inventory))
    findings.extend(attachment_validation_findings(inventory))
    findings.extend(_nonroute_project_markdown_findings(inventory))
    findings.extend(roadmap_order_namespace_findings(inventory))
    findings.extend(roadmap_terminal_related_plan_findings(inventory))
    findings.extend(roadmap_archived_history_stale_tail_findings(inventory))
    findings.extend(roadmap_source_incubation_evidence_findings(inventory))
    findings.extend(roadmap_related_specs_evidence_findings(inventory))
    findings.extend(roadmap_human_review_gate_findings(inventory))
    findings.extend(
        roadmap_batch_slice_gate_findings(
            inventory,
            active_plan_roadmap_item_ids(inventory),
            route="check",
            source="project/implementation-plan.md",
        )
    )
    findings.extend(deep_research_rubric_recovery_findings(inventory))
    findings.extend(roadmap_compacted_dependency_archive_evidence_findings(inventory))
    findings.extend(roadmap_done_docs_archive_evidence_findings(inventory))
    findings.extend(roadmap_acceptance_readiness_findings(inventory))
    findings.extend(_target_artifact_ownership_findings(inventory))
    findings.extend(_verification_ledger_status_findings(inventory))
    findings.extend(_bug_hunt_traceability_findings(inventory))
    findings.extend(_working_memory_compaction_rail_findings(inventory))
    findings.extend(multi_agent_security_findings(inventory))
    findings.extend(symphony_queue_dependency_findings(inventory, "check-symphony-queue"))
    findings.extend(connect_readiness_findings(inventory, "check-connect-readiness"))
    findings.extend(mlhd_runtime_findings(inventory, "check-mlhd"))
    findings.extend(dashboard_check_findings(inventory))
    findings.extend(lifecycle_mutation_provenance_findings(inventory, "check-lifecycle-provenance"))
    findings.extend(_docmap_findings(inventory))
    findings.extend(_mirror_findings(inventory))
    return findings


def multi_agent_security_findings(
    inventory: Inventory, code_prefix: str = "check-multi-agent-security"
) -> list[Finding]:
    state_source = inventory.state.rel_path if inventory.state and inventory.state.exists else None
    findings = [
        Finding(
            "info",
            f"{code_prefix}-root-posture",
            (
                f"root kind: {inventory.root_kind}; multi-agent security diagnostics are read-only threat-model posture "
                "and cannot promote a product fixture, archive root, generated output, adapter, hook, daemon, or dashboard into authority"
            ),
            state_source,
        ),
        Finding(
            "info",
            f"{code_prefix}-authority",
            (
                "claims, agent-run evidence, handoff packets, and session active-work records are the repo-visible "
                "coordination authority; hooks, dashboards, daemons, adapters, provider state, logs, and caches remain advisory"
            ),
            "project/verification",
        ),
        Finding(
            "info",
            f"{code_prefix}-hooks",
            (
                "hooks are explicit opt-in sensors/blockers/context injectors; hook output cannot approve repair, closeout, "
                "archive, roadmap status, staging, commit, push, rollback, release, dispatcher decisions, or daemon truth"
            ),
        ),
        Finding(
            "info",
            f"{code_prefix}-dashboard",
            (
                "dashboard output is projection/cockpit context only; route files, project-state lifecycle fields, claims, "
                "runs, handoffs, and explicit writeback facts remain truth"
            ),
            ".mylittleharness/generated/projection",
        ),
        Finding(
            "info",
            f"{code_prefix}-runtime-cache",
            (
                "mlhd runtime cache, process observations, local logs, and notifications are disposable; deleting them must "
                "not change what is active, accepted, verified, blocked, closeable, or archived"
            ),
            ".mylittleharness",
        ),
        Finding(
            "info",
            f"{code_prefix}-dispatcher-gate",
            (
                "a dispatcher cannot start work without a repo-visible handoff packet, compatible active claim, and planned "
                "agent-run evidence path; model/provider/tool routing cannot bypass those records"
            ),
            "project/verification",
        ),
        Finding(
            "info",
            f"{code_prefix}-adapter-boundary",
            (
                "MCP/A2A/relay/provider adapters are transport or projection helpers by default; they must not store secrets, "
                "open a background server, choose providers, or approve lifecycle movement without an explicit future route"
            ),
        ),
        Finding(
            "info",
            f"{code_prefix}-prompt-injection",
            (
                "repo text, hook arguments, dashboard inputs, adapter payloads, and logs are untrusted context until reconciled "
                "against route manifests, write scope, allowed routes, claims, handoffs, and explicit evidence"
            ),
        ),
        Finding(
            "info",
            f"{code_prefix}-path-secret-leakage",
            (
                "security-sensitive output should name root-relative refs, hashes, and bounded summaries instead of copying "
                "environment variables, credentials, provider payloads, log bodies, or source bodies into runtime state"
            ),
            "project/verification",
        ),
        Finding(
            "info",
            f"{code_prefix}-unsafe-defaults-disabled",
            (
                "check starts no dashboard, daemon, dispatcher, provider gateway, A2A server, network listener, hook install, "
                "worker process, or runtime cache mutation; risky runtime expansion stays behind later explicit dry-run/apply rails"
            ),
        ),
    ]
    return findings


def _working_memory_compaction_rail_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    return [
        Finding(
            "info",
            "check-working-memory-compaction-rails",
            (
                "working-memory compaction is explicit and source-bound: project-state uses "
                "writeback --dry-run --compact-only followed by writeback --apply --compact-only --source-hash <sha256>; "
                "verification ledgers use memory-hygiene --dry-run --rotate-ledger followed by --apply --rotate-ledger --source-hash <sha256>; "
                "memory-hygiene candidates stay read-only at --dry-run --scan until a per-source dry-run/apply or later token-bound rail is reviewed; "
                "no hidden memory database, provider memory, daemon, closeout approval, archive approval, staging, commit, push, dependency adoption, or next-plan opening is implied"
            ),
            "project/project-state.md",
        )
    ]


def _verification_ledger_status_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    active_dir = inventory.root / VERIFICATION_DIR_REL
    archive_dir = inventory.root / ARCHIVE_VERIFICATION_DIR_REL
    active_ledgers = _regular_markdown_files(active_dir)
    archived_ledgers = _regular_markdown_files(archive_dir, recursive=True)
    if not active_ledgers and not archived_ledgers:
        return []
    findings = [
        Finding(
            "info",
            "check-verification-ledger-status",
            (
                f"verification ledger posture: active={len(active_ledgers)} under {VERIFICATION_DIR_REL}; "
                f"archived={len(archived_ledgers)} under {ARCHIVE_VERIFICATION_DIR_REL}"
            ),
        )
    ]
    for path in active_ledgers:
        rel_path = path.relative_to(inventory.root).as_posix()
        text = _read_text_best_effort(path)
        if VERIFICATION_LEDGER_CONTINUITY_MARKER in text:
            findings.append(
                Finding(
                    "info",
                    "check-verification-ledger-active",
                    f"fresh active verification ledger with continuity pointer: {rel_path}",
                    rel_path,
                )
            )
        else:
            findings.append(
                Finding("info", "check-verification-ledger-active", f"active verification ledger: {rel_path}", rel_path)
            )
    if archived_ledgers:
        examples = ", ".join(path.relative_to(inventory.root).as_posix() for path in archived_ledgers[:3])
        if len(archived_ledgers) > 3:
            examples += f", +{len(archived_ledgers) - 3} more"
        findings.append(
            Finding(
                "info",
                "check-verification-ledger-archive",
                (
                    f"archived verification ledger evidence is historical, not active continuation state: "
                    f"{len(archived_ledgers)} file(s); examples: {examples}"
                ),
                ARCHIVE_VERIFICATION_DIR_REL,
            )
        )
    return findings


def _bug_hunt_traceability_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    ledger = inventory.surface_by_rel.get(BUG_HUNT_LEDGER_REL)
    if not ledger or not ledger.exists:
        return []

    ledger_ids = _bug_hunt_ledger_id_lines(ledger)
    if not ledger_ids:
        return [
            Finding(
                "info",
                "bug-hunt-traceability-empty",
                f"{BUG_HUNT_LEDGER_REL} has no numeric BH headings to trace",
                BUG_HUNT_LEDGER_REL,
            )
        ]

    coverage_records, findings = _bug_hunt_coverage_records(inventory)
    roadmap_records, roadmap_findings = _bug_hunt_roadmap_records(inventory)
    findings.extend(roadmap_findings)

    covered_ids = set(coverage_records) | set(roadmap_records)
    missing_ids = sorted(set(ledger_ids) - covered_ids)
    stale_ids = sorted(covered_ids - set(ledger_ids))

    if missing_ids:
        first_missing = missing_ids[0]
        findings.append(
            Finding(
                "warn",
                "bug-hunt-traceability-gap",
                (
                    f"{len(missing_ids)} numeric bug-hunt ledger id(s) have no fixed/delegated/rejected "
                    f"coverage row or accepted/active/done roadmap bh_ids owner: {_summarize_bh_ids(missing_ids)}"
                ),
                BUG_HUNT_LEDGER_REL,
                ledger_ids.get(first_missing),
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "bug-hunt-traceability-complete",
                (
                    f"bug-hunt traceability covers {len(ledger_ids)} numeric ledger id(s): "
                    f"coverage_matrix={len(coverage_records)}; roadmap_bh_ids={len(roadmap_records)}"
                ),
                BUG_HUNT_LEDGER_REL,
            )
        )

    if stale_ids:
        stale_source, stale_line = _bug_hunt_first_record_location((coverage_records, roadmap_records), stale_ids[0])
        findings.append(
            Finding(
                "warn",
                "bug-hunt-traceability-stale-reference",
                f"bug-hunt coverage references id(s) not present as numeric ledger headings: {_summarize_bh_ids(stale_ids)}",
                stale_source or BUG_HUNT_LEDGER_REL,
                stale_line,
            )
        )
    return findings


def _bug_hunt_ledger_id_lines(surface: Surface) -> dict[str, int]:
    ids: dict[str, int] = {}
    for line_number, line in enumerate(surface.content.splitlines(), start=1):
        match = re.match(r"^###\s+(BH-\d{8}-\d{3})\b", line.strip())
        if match:
            ids.setdefault(match.group(1), line_number)
    return ids


def _bug_hunt_coverage_records(inventory: Inventory) -> tuple[dict[str, list[tuple[str, int | None]]], list[Finding]]:
    coverage = inventory.surface_by_rel.get(BUG_HUNT_COVERAGE_REL)
    if not coverage or not coverage.exists:
        return {}, [
            Finding(
                "warn",
                "bug-hunt-traceability-coverage-missing",
                f"{BUG_HUNT_COVERAGE_REL} is absent; current ledger ids must be covered by roadmap bh_ids",
                BUG_HUNT_COVERAGE_REL,
            )
        ]

    records: dict[str, list[tuple[str, int | None]]] = {}
    findings: list[Finding] = []
    for line_number, line in enumerate(coverage.content.splitlines(), start=1):
        match = re.match(r"^\|\s*(BH-\d{8}-\d{3})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
        if not match:
            continue
        bh_id = match.group(1)
        status = match.group(2).strip().casefold()
        owner = match.group(3).strip()
        if status not in BUG_HUNT_DISPOSITION_STATUSES:
            findings.append(
                Finding(
                    "warn",
                    "bug-hunt-traceability-invalid-disposition",
                    (
                        f"{bh_id} has unsupported bug-hunt coverage status {status!r}; "
                        f"expected one of {sorted(BUG_HUNT_DISPOSITION_STATUSES)}"
                    ),
                    BUG_HUNT_COVERAGE_REL,
                    line_number,
                )
            )
            continue
        if not owner:
            findings.append(
                Finding(
                    "warn",
                    "bug-hunt-traceability-empty-owner",
                    f"{bh_id} has no owner/disposition in the bug-hunt coverage matrix",
                    BUG_HUNT_COVERAGE_REL,
                    line_number,
                )
            )
            continue
        records.setdefault(bh_id, []).append((BUG_HUNT_COVERAGE_REL, line_number))
    return records, findings


def _bug_hunt_roadmap_records(inventory: Inventory) -> tuple[dict[str, list[tuple[str, int | None]]], list[Finding]]:
    records: dict[str, list[tuple[str, int | None]]] = {}
    roadmap_items, parse_findings = roadmap_items_for_diagnostics(inventory)
    if parse_findings:
        return records, [
            Finding(
                "warn",
                "bug-hunt-traceability-roadmap-unreadable",
                "roadmap bh_ids traceability could not be checked because project/roadmap.md has parse findings",
                ROADMAP_REL,
            )
        ]

    for _item_id, item in sorted(roadmap_items.items(), key=lambda row: (row[1].start, row[0])):
        status = str(item.fields.get("status") or "").strip().casefold()
        if status not in BUG_HUNT_ROADMAP_OWNER_STATUSES:
            continue
        for bh_id in _bug_hunt_ids_from_text(str(item.fields.get("bh_ids") or "")):
            records.setdefault(bh_id, []).append((ROADMAP_REL, item.start + 1))
    return records, []


def _bug_hunt_ids_from_text(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"BH-\d{8}-\d{3}", text or "")))


def _bug_hunt_first_record_location(
    record_maps: tuple[dict[str, list[tuple[str, int | None]]], ...],
    bh_id: str,
) -> tuple[str | None, int | None]:
    for record_map in record_maps:
        for source, line in record_map.get(bh_id, []):
            return source, line
    return None, None


def _summarize_bh_ids(ids: list[str]) -> str:
    if len(ids) <= 8:
        return ", ".join(ids)
    return ", ".join(ids[:8]) + f", +{len(ids) - 8} more"


def _regular_markdown_files(path: Path, *, recursive: bool = False) -> list[Path]:
    if not path.is_dir() or path.is_symlink():
        return []
    iterator = path.rglob("*.md") if recursive else path.glob("*.md")
    return sorted(candidate for candidate in iterator if candidate.is_file() and not candidate.is_symlink())


def _read_text_best_effort(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _target_artifact_ownership_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    findings: list[Finding] = []
    if inventory.active_plan_surface and inventory.active_plan_surface.exists:
        artifacts = _target_artifact_values(inventory.active_plan_surface.frontmatter.data.get("target_artifacts"))
        findings.extend(
            _target_artifact_ownership_summary_findings(
                inventory,
                artifacts,
                "check-target-artifact-ownership",
                inventory.active_plan_surface.rel_path,
                "active plan",
            )
        )
    roadmap_items, parse_findings = roadmap_items_for_diagnostics(inventory)
    findings.extend(parse_findings)
    for item_id, item in sorted(roadmap_items.items()):
        status = str(item.fields.get("status") or "").strip().casefold()
        if status not in {"active", "accepted", "proposed"}:
            continue
        artifacts = _target_artifact_values(item.fields.get("target_artifacts"))
        findings.extend(
            _target_artifact_ownership_summary_findings(
                inventory,
                artifacts,
                "check-target-artifact-ownership",
                ROADMAP_REL,
                f"roadmap item {item_id}",
                line=item.start + 1,
            )
        )
    return findings


def _target_artifact_ownership_summary_findings(
    inventory: Inventory,
    artifacts: tuple[str, ...],
    code: str,
    source: str,
    label: str,
    *,
    line: int | None = None,
) -> list[Finding]:
    records = target_artifact_ownerships(inventory, artifacts)
    if not records:
        return []
    summary = "; ".join(f"{record.artifact}->{record.ownership} ({record.intended_root})" for record in records)
    guidance = "; ".join(sorted({record.guidance for record in records}))
    findings = [Finding("info", code, f"{label} target artifact ownership: {summary}; guidance: {guidance}", source, line)]
    findings.extend(_target_artifact_doc_target_findings(inventory, artifacts, source, label, line=line))
    return findings


def _target_artifact_doc_target_findings(
    inventory: Inventory,
    artifacts: tuple[str, ...],
    source: str,
    label: str,
    *,
    line: int | None = None,
) -> list[Finding]:
    target_root = _active_plan_target_root(inventory)
    missing: list[str] = []
    candidates: list[str] = []
    for artifact in artifacts:
        rel = normalize_route_path(artifact)
        if not is_exact_doc_target(rel) or doc_target_exists(target_root, rel):
            continue
        missing.append(rel)
        suggested = existing_doc_target_candidates(target_root, rel)
        if suggested:
            candidates.append(f"{rel} -> {', '.join(suggested)}")
    if not missing:
        return []
    candidate_text = "; ".join(candidates) if candidates else "<none found>"
    return [
        Finding(
            "warn",
            "check-doc-target-missing",
            (
                f"{label} names missing exact docs target(s) in product/source root {target_root}: "
                f"{', '.join(missing)}; candidates: {candidate_text}; "
                "retarget to an existing docs/spec/template file or keep docs_decision='uncertain' before docs mutation"
            ),
            source,
            line,
        )
    ]


def _target_artifact_values(value: object) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item or "").strip())
    return (str(value).strip(),) if str(value).strip() else ()


def _incubation_contract_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    findings: list[Finding] = []
    legacy_path = inventory.root / "project/incubator"
    if legacy_path.exists():
        findings.append(
            Finding(
                "warn",
                "incubation-legacy-path",
                "project/incubator is a legacy or ambiguous idea surface; use canonical project/plan-incubation/*.md for incubation notes",
                "project/incubator",
            )
        )
    agents = inventory.surface_by_rel.get("AGENTS.md")
    if agents and agents.exists and "project/plan-incubation" not in agents.content:
        findings.append(
            Finding(
                "warn",
                "agents-incubation-contract-missing",
                "AGENTS.md does not name the canonical incubation surface; idea-incubation requests should create or update project/plan-incubation/*.md instead of project-state carry-forward bullets",
                "AGENTS.md",
            )
        )
    return findings


def check_drift_findings(inventory: Inventory) -> list[Finding]:
    findings = [finding for finding in audit_link_findings(inventory) if finding.code in CHECK_DRIFT_CODES]
    findings.extend(rule_context_findings(inventory, include_ok=False))
    findings.extend(remainder_drift_findings(inventory, include_ok=False))
    if findings:
        return findings
    return [Finding("info", "check-drift-ok", "no check-level docmap, root-pointer, rule/context, or remainder drift was found")]


def projection_cache_status_findings(inventory: Inventory) -> list[Finding]:
    projection = build_projection(inventory)
    artifact_findings = inspect_projection_artifacts(inventory, projection)
    index_findings = inspect_projection_index(inventory, projection)
    artifact_status, artifact_reason = _projection_cache_status(
        artifact_findings,
        current_code="projection-artifact-current",
        missing_code="projection-artifact-missing",
    )
    index_status, index_reason = _projection_cache_status(
        index_findings,
        current_code="projection-index-current",
        missing_code="projection-index-missing",
    )
    reason = _projection_cache_reason_label(artifact_reason, index_reason)
    posture = projection_cache_posture_payload(
        artifact_findings,
        index_findings,
        runtime_refresh_allowed=inventory.root_kind != PRODUCT_SOURCE_FIXTURE,
    )
    refresh_commands = ", ".join(str(command) for command in posture.get("recommended_refresh_commands", [])[:2])
    return [
        Finding(
            "info",
            "projection-cache-status",
            (
                f"disposable generated projection cache: artifacts={artifact_status}; sqlite_index={index_status}; "
                f"detail={reason}; source files and the in-memory projection remain authoritative"
            ),
            ARTIFACT_DIR_REL,
        ),
        Finding(
            "info",
            "projection-cache-posture",
            (
                f"structured disposable cache posture: artifacts={artifact_status}; sqlite_index={index_status}; "
                f"detail={reason}; refresh_by_adapter=false; next_safe={refresh_commands}"
            ),
            ARTIFACT_DIR_REL,
        ),
        Finding(
            "info",
            "projection-cache-read-only",
            (
                "check inspects disposable projection freshness without refreshing generated artifacts or SQLite indexes; "
                "intelligence path/full-text navigation may refresh the disposable cache when a query needs it"
            ),
            ARTIFACT_DIR_REL,
        ),
    ]


def _projection_cache_status(findings: list[Finding], current_code: str, missing_code: str) -> tuple[str, str]:
    codes = [finding.code for finding in findings]
    if any(code.endswith("fts5-unavailable") for code in codes):
        return "unavailable", _projection_cache_sample(codes)
    if "projection-cache-operation-in-progress" in codes:
        return "updating", "projection-cache-operation-in-progress"
    if missing_code in codes:
        return "missing", missing_code
    if any(
        code.endswith(suffix)
        for code in codes
        for suffix in ("stale", "dirty", "hash", "count", "schema", "root-mismatch")
    ):
        return "stale", _projection_cache_sample(codes)
    if current_code in codes:
        return "current", current_code
    if any(finding.severity in {"warn", "error"} for finding in findings):
        return "degraded", _projection_cache_sample(codes)
    return "current", _projection_cache_sample(codes)


def _projection_cache_sample(codes: list[str]) -> str:
    selected: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code.endswith("boundary") or code in seen:
            continue
        seen.add(code)
        selected.append(code)
    return ",".join(selected[:3]) if selected else "no-detail"


def _projection_cache_reason_label(artifact_reason: str, index_reason: str) -> str:
    if artifact_reason == index_reason:
        return artifact_reason
    return f"artifacts:{artifact_reason}; index:{index_reason}"


def diagnostic_drift_findings(inventory: Inventory) -> list[Finding]:
    findings = audit_link_findings(inventory)
    findings.extend(rule_context_findings(inventory, include_ok=False))
    findings.extend(remainder_drift_findings(inventory, include_ok=False))
    return findings


def rule_context_findings(inventory: Inventory, include_ok: bool = True) -> list[Finding]:
    findings: list[Finding] = []
    rel_paths = list(RULE_CONTEXT_PRIMARY_SURFACES)
    if inventory.active_plan_surface and inventory.active_plan_surface.rel_path not in rel_paths:
        rel_paths.append(inventory.active_plan_surface.rel_path)
    large_live_state = False

    for rel_path in rel_paths:
        surface = inventory.surface_by_rel.get(rel_path)
        if not surface or not surface.exists:
            continue
        label = _budget_label(surface.line_count, surface.char_count)
        if label not in {"large", "very-large"}:
            continue
        findings.append(
            Finding(
                "warn",
                "rule-context-surface-large",
                _large_rule_context_message(inventory, surface, label),
                surface.rel_path,
            )
        )
        if inventory.root_kind == "live_operating_root" and surface.rel_path == "project/project-state.md":
            large_live_state = True

    if large_live_state:
        findings.extend(_state_compaction_contract_findings(inventory))
        findings.extend(_agents_compaction_contract_findings(inventory))
    if findings or not include_ok:
        return findings
    return [Finding("info", "rule-context-ok", "primary instruction surfaces are within check-level size thresholds")]


def _large_rule_context_message(inventory: Inventory, surface: Surface, label: str) -> str:
    message = (
        f"{surface.rel_path}: primary instruction surface is {surface.line_count} lines, "
        f"{surface.char_count} chars, label={label}; use context-budget for section detail"
    )
    if inventory.root_kind == "live_operating_root" and surface.rel_path == "project/project-state.md":
        message += (
            "; preview/apply whole-state history compaction with writeback --dry-run --compact-only, "
            "then writeback --apply --compact-only --source-hash <sha256-from-dry-run> after review; "
            "next_safe_command=mylittleharness --root <root> writeback --dry-run --compact-only"
        )
    return message


def _state_compaction_contract_findings(inventory: Inventory) -> list[Finding]:
    state = inventory.state
    if not state or not state.exists:
        return []
    required_keep_sections = ("Current Focus", "Repository Role Map")
    missing = [title for title in required_keep_sections if f"## {title}" not in state.content]
    if not missing:
        return []
    missing_text = ", ".join(missing)
    return [
        Finding(
            "warn",
            "state-compaction-section-boundary-missing",
            (
                f"project/project-state.md is oversized but lacks compact-only keep section(s): {missing_text}; "
                "compact-only would refuse until current state section boundaries are restored, and this remains "
                "operating-memory hygiene separate from lifecycle closeout, staging, commit, archive, rollback, or next-plan opening"
            ),
            state.rel_path,
        )
    ]


def _agents_compaction_contract_findings(inventory: Inventory) -> list[Finding]:
    agents = inventory.surface_by_rel.get("AGENTS.md")
    if not agents or not agents.exists or _agents_has_compaction_contract(agents.content):
        return []
    return [
        Finding(
            "warn",
            "agents-compaction-contract-missing",
            (
                "AGENTS.md does not include compact-only project-state hygiene guidance; refreshed operating-root contracts should tell agents "
                "to preview/apply writeback --compact-only instead of manually trimming only the newest note"
            ),
            "AGENTS.md",
        )
    ]


def _agents_has_compaction_contract(content: str) -> bool:
    normalized = content.casefold()
    return (
        "writeback --compact-only" in normalized
        and "project/project-state.md" in normalized
        and ("manual" in normalized or "manually" in normalized)
        and ("trim" in normalized or "compact" in normalized)
    )


def remainder_drift_findings(inventory: Inventory, include_ok: bool = True) -> list[Finding]:
    delivered: dict[str, tuple[Surface, int]] = {}
    remainder: list[tuple[str, Surface, int]] = []
    findings: list[Finding] = []

    for surface in inventory.present_surfaces:
        if surface.role not in REMAINDER_DRIFT_SURFACE_ROLES or surface.role == "package-mirror":
            continue
        lines = surface.content.splitlines()
        for line_number, line in enumerate(lines, start=1):
            context = _remainder_drift_context(surface, line_number, line)
            if context == "historical":
                continue
            tokens = _explicit_remainder_tokens(line)
            if not tokens:
                continue
            if context == "delivered":
                for token in tokens:
                    delivered.setdefault(token, (surface, line_number))
            elif context == "remainder":
                for token in tokens:
                    remainder.append((token, surface, line_number))

    seen: set[tuple[str, str, int]] = set()
    for token, surface, line_number in remainder:
        if token not in delivered:
            continue
        key = (token, surface.rel_path, line_number)
        if key in seen:
            continue
        seen.add(key)
        delivered_surface, delivered_line = delivered[token]
        findings.append(
            Finding(
                "warn",
                "remainder-drift",
                (
                    f"`{token}` is described as delivered/current at "
                    f"{delivered_surface.rel_path}:{delivered_line} but still appears in future/backlog wording"
                ),
                surface.rel_path,
                line_number,
            )
        )

    if findings or not include_ok:
        return findings
    return [Finding("info", "remainder-drift-ok", "no explicit delivered-vs-remainder token contradictions were found")]


def context_budget_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    start_surfaces = _start_path_surfaces(inventory)
    total_lines = 0
    total_chars = 0
    warning_lines = 0
    warning_chars = 0

    for surface in start_surfaces:
        if not surface.exists:
            continue
        lines = surface.line_count
        chars = surface.char_count
        total_lines += lines
        total_chars += chars
        if _context_budget_surface_can_warn(surface):
            warning_lines += lines
            warning_chars += chars
        token_estimate = max(1, chars // 4) if chars else 0
        label = _budget_label(lines, chars)
        severity = "warn" if label in {"large", "very-large"} and _context_budget_surface_can_warn(surface) else "info"
        findings.append(
            Finding(
                severity,
                "file-budget",
                f"{surface.rel_path}: {lines} lines, {chars} chars, {surface.byte_count} bytes, ~{token_estimate} tokens, label={label}",
                surface.rel_path,
            )
        )
        for heading in surface.largest_sections(limit=3):
            findings.append(
                Finding(
                    "info",
                    "section-budget",
                    f"{surface.rel_path}:{heading.line} section '{heading.title}' spans {heading.length} lines",
                    surface.rel_path,
                    heading.line,
                )
            )

    aggregate_label = "large" if total_lines > LARGE_AGGREGATE_LINES or total_chars > LARGE_AGGREGATE_CHARS else "normal"
    warning_aggregate_label = (
        "large" if warning_lines > LARGE_AGGREGATE_LINES or warning_chars > LARGE_AGGREGATE_CHARS else "normal"
    )
    severity = "warn" if warning_aggregate_label == "large" else "info"
    findings.insert(
        0,
        Finding(
            severity,
            "start-set-budget",
            f"start-path aggregate: {total_lines} lines, {total_chars} chars, ~{max(1, total_chars // 4) if total_chars else 0} tokens, label={aggregate_label}",
        ),
    )
    findings.extend(context_memory_capsule_findings(inventory, "context-budget-context-memory"))
    return findings


def _context_budget_surface_can_warn(surface: Surface) -> bool:
    return surface.role not in {"product-doc", "stable-spec", "package-mirror"}


def audit_link_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    skipped_external = 0
    skipped_mirrors = 0
    seen: set[tuple[str, str, int]] = set()
    for surface in inventory.present_surfaces:
        if surface.role == "package-mirror":
            skipped_mirrors += 1
            continue
        for link in surface.links:
            key = (surface.rel_path, link.target, link.line)
            if key in seen:
                continue
            seen.add(key)
            if link.source != "markdown-link" and _route_reference_is_text_only_label(_normalized_link_path(link.target)):
                continue
            resolution = resolve_link(inventory.root, link.target, surface.rel_path)
            if resolution.kind == "external":
                skipped_external += 1
                continue
            if resolution.kind == "anchor":
                continue
            if resolution.kind == "unresolved":
                findings.append(
                    Finding("warn", "unresolved-link", f"{link.target} could not be resolved as a local path", surface.rel_path, link.line)
                )
                continue
            if resolution.kind == "pattern":
                if not resolution.exists:
                    product_target_reason = product_target_artifact_reason(inventory, surface, link.target, link.line)
                    if product_target_reason:
                        findings.append(
                            Finding(
                                "info",
                                "product-target-artifact",
                                f"{link.target} is not present in the operating root; {product_target_reason}",
                                surface.rel_path,
                                link.line,
                            )
                        )
                        continue
                    historical_context_reason = historical_link_context_reason(surface, link.target, link.line)
                    if historical_context_reason:
                        findings.append(
                            Finding(
                                "info",
                                "historical-link-context",
                                f"{link.target} is not present; {historical_context_reason}",
                                surface.rel_path,
                                link.line,
                            )
                        )
                        continue
                    findings.append(
                        Finding(
                            "info",
                            "optional-pattern-missing",
                            f"{link.target} did not match an existing local path; treating as optional pattern",
                            surface.rel_path,
                            link.line,
                        )
                    )
                continue
            if not resolution.exists:
                product_target_reason = product_target_artifact_reason(inventory, surface, link.target, link.line)
                if product_target_reason:
                    findings.append(
                        Finding(
                            "info",
                            "product-target-artifact",
                            f"{link.target} is not present in the operating root; {product_target_reason}",
                            surface.rel_path,
                            link.line,
                        )
                    )
                    continue
                historical_context_reason = historical_link_context_reason(surface, link.target, link.line)
                if historical_context_reason:
                    findings.append(
                        Finding(
                            "info",
                            "historical-link-context",
                            f"{link.target} is not present; {historical_context_reason}",
                            surface.rel_path,
                            link.line,
                        )
                    )
                    continue
                optional_reason = _optional_missing_link_reason(inventory, link.target)
                if optional_reason:
                    findings.append(
                        Finding(
                            "info",
                            "optional-link-missing",
                            f"{link.target} is not present; {optional_reason}",
                            surface.rel_path,
                            link.line,
                        )
                    )
                    continue
                findings.append(
                    Finding(
                        "warn",
                        "missing-link",
                        f"{link.target} does not resolve to an existing local path",
                        surface.rel_path,
                        link.line,
                    )
                )
    if skipped_external:
        findings.append(Finding("info", "external-links-skipped", f"skipped {skipped_external} external URL links"))
    if skipped_mirrors:
        findings.append(Finding("info", "package-mirrors-skipped", f"skipped duplicate link audit for {skipped_mirrors} package-source mirror files"))
    findings.extend(_product_doc_frontmatter_audit_findings(inventory))
    findings.extend(_docmap_gap_findings(inventory))
    findings.extend(_stale_root_pointer_findings(inventory))
    if not findings:
        findings.append(Finding("info", "links-ok", "no missing local links were found"))
    return findings


def intelligence_sections(
    inventory: Inventory,
    search_text: str | None = None,
    path_text: str | None = None,
    full_text: str | None = None,
    limit: int = 10,
    query_text: str | None = None,
    *,
    focus: str | None = None,
) -> list[tuple[str, list[Finding]]]:
    stage_full_text = _stage_unified_query_full_text(inventory, focus, full_text, query_text)
    search_text, path_text, full_text, query_expansion = _expanded_intelligence_queries(
        search_text,
        path_text,
        full_text,
        query_text,
        stage_full_text=stage_full_text,
    )
    if focus == "search":
        if full_text is None:
            sections = [("Search", _search_findings_from_inventory(inventory, search_text, path_text, query_expansion))]
        else:
            projection = build_projection(inventory)
            sections = [("Search", _search_findings(inventory, projection, search_text, path_text, full_text, limit, query_expansion))]
    else:
        projection = build_projection(inventory)
        if focus == "projection":
            sections = [
                ("Boundary", _intelligence_boundary_findings(inventory, search_text, path_text, full_text)),
                ("Projection", _projection_findings(inventory, projection)),
            ]
        elif focus == "warnings":
            sections = [
                ("Drift", diagnostic_drift_findings(inventory)),
                ("Recovery Routes", deep_research_rubric_recovery_findings(inventory, include_present=True)),
                ("Repo Map", _repo_map_findings(projection)),
                ("Backlinks", _backlink_findings(projection.links)),
                ("Fan-In", _fan_in_findings(inventory, projection)),
                ("Projection", _projection_findings(inventory, projection)),
            ]
            if search_text is not None or path_text is not None or full_text is not None or query_expansion is not None:
                sections.append(("Search", _search_findings(inventory, projection, search_text, path_text, full_text, limit, query_expansion)))
        else:
            sections = [
                ("Boundary", _intelligence_boundary_findings(inventory, search_text, path_text, full_text)),
                ("Drift", diagnostic_drift_findings(inventory)),
                ("Recovery Routes", deep_research_rubric_recovery_findings(inventory, include_present=True)),
                ("Repo Map", _repo_map_findings(projection)),
                ("Backlinks", _backlink_findings(projection.links)),
                ("Search", _search_findings(inventory, projection, search_text, path_text, full_text, limit, query_expansion)),
                ("Fan-In", _fan_in_findings(inventory, projection)),
                ("Projection", _projection_findings(inventory, projection)),
            ]
    normalized_sections = [
        (section_name, [_normalize_intelligence_finding(inventory, finding) for finding in findings])
        for section_name, findings in sections
    ]
    return [("Summary", _intelligence_summary_findings(inventory, normalized_sections, search_text, path_text, full_text))] + normalized_sections


def _stage_unified_query_full_text(inventory: Inventory, focus: str | None, full_text: str | None, query_text: str | None) -> bool:
    if query_text in (None, "") or full_text not in (None, ""):
        return False
    return _intelligence_query_corpus_is_large(inventory)


def _intelligence_query_corpus_is_large(inventory: Inventory) -> bool:
    total_lines = sum(surface.line_count for surface in inventory.present_surfaces)
    total_chars = sum(surface.char_count for surface in inventory.present_surfaces)
    return total_lines > LARGE_AGGREGATE_LINES or total_chars > LARGE_AGGREGATE_CHARS


def intelligence_route_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    boundary = [
        Finding("info", "intelligence-routes-read-only", "intelligence --focus routes reports lifecycle routing without writing files"),
        Finding(
            "info",
            "intelligence-routes-boundary",
            (
                "route output is advisory and cannot approve mutation, repair, closeout, archive, commit, "
                "or lifecycle decisions"
            ),
        ),
        Finding("info", "intelligence-routes-root-kind", f"root kind: {inventory.root_kind}"),
    ]
    if inventory.root_kind != "live_operating_root":
        boundary.append(
            Finding(
                "info",
                "route-table-scope",
                "lifecycle route table is reported only for live operating roots; product-source fixtures remain product/fixture context",
            )
        )
    sections = [("Boundary", boundary), ("Lifecycle Routes", lifecycle_route_findings(inventory))]
    discovered = memory_route_inventory_findings(inventory)
    if discovered:
        sections.append(("Discovered Routes", discovered))
    return sections


def flatten_sections(sections: list[tuple[str, list[Finding]]]) -> list[Finding]:
    return [finding for _, findings in sections for finding in findings]


def _expanded_intelligence_queries(
    search_text: str | None,
    path_text: str | None,
    full_text: str | None,
    query_text: str | None,
    *,
    stage_full_text: bool = False,
) -> tuple[str | None, str | None, str | None, Finding | None]:
    if query_text in (None, ""):
        return search_text, path_text, full_text, None

    filled: list[str] = []
    staged: list[str] = []
    if search_text is None:
        search_text = query_text
        filled.append("exact text")
    if path_text is None:
        path_text = query_text
        filled.append("path")
    if full_text is None:
        if stage_full_text:
            staged.append("full text")
        else:
            full_text = query_text
            filled.append("full text")

    filled_label = ", ".join(filled) if filled else "none"
    staged_label = f"; staged modes: {', '.join(staged)} (use --full-text TEXT to include them)" if staged else ""
    return (
        search_text,
        path_text,
        full_text,
        Finding(
            "info",
            "intelligence-query-expansion",
            f"unified query expanded into omitted modes: {filled_label}{staged_label}; explicit mode flags keep their own values",
        ),
    )


def _intelligence_boundary_findings(
    inventory: Inventory,
    search_text: str | None,
    path_text: str | None,
    full_text: str | None,
) -> list[Finding]:
    present_count = len(inventory.present_surfaces)
    cache_posture = (
        f"path/full-text navigation may refresh disposable generated projection cache inside {ARTIFACT_DIR_REL}"
        if path_text not in (None, "") or full_text not in (None, "")
        else "no generated projection cache refresh is needed for this invocation"
    )
    return [
        Finding("info", "intelligence-boundary", f"terminal-only report; {cache_posture}; lifecycle authority files, hooks, adapters, snapshots, repairs, archives, and commits are not written"),
        Finding("info", "intelligence-root-kind", f"root kind: {inventory.root_kind}"),
        Finding("info", "intelligence-corpus", f"inventory corpus: {present_count}/{len(inventory.surfaces)} discovered surfaces present"),
        Finding("info", "intelligence-search-mode", f"case-sensitive exact/path matching plus optional source-verified full-text; active queries: {_intelligence_query_label(search_text, path_text, full_text)}"),
    ]


def _intelligence_summary_findings(
    inventory: Inventory,
    sections: list[tuple[str, list[Finding]]],
    search_text: str | None,
    path_text: str | None,
    full_text: str | None,
) -> list[Finding]:
    findings = flatten_sections(sections)
    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warn"]
    result = "error" if errors else "warn" if warnings else "ok"
    present_count = len(inventory.present_surfaces)
    summary = [
        Finding(
            "info",
            "intelligence-summary",
            (
                f"root kind: {inventory.root_kind}; status: {result}; corpus: {present_count}/{len(inventory.surfaces)}; "
                f"actionable warnings: {len(warnings)}; errors: {len(errors)}; active queries: {_intelligence_query_label(search_text, path_text, full_text)}"
            ),
        )
    ]
    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    for key in ("operating_mode", "plan_status", "active_plan", "active_phase", "phase_status"):
        value = state_data.get(key)
        if value not in (None, ""):
            summary.append(Finding("info", "intelligence-state", f"{key}: {value}", state.rel_path if state else None))
    summary.append(Finding("info", "intelligence-recovery-targets", f"top recovery targets: {_intelligence_recovery_targets(inventory)}"))
    return summary


def _intelligence_query_label(search_text: str | None, path_text: str | None, full_text: str | None = None) -> str:
    query_parts = []
    if search_text not in (None, ""):
        query_parts.append("exact text")
    if path_text not in (None, ""):
        query_parts.append("path")
    if full_text not in (None, ""):
        query_parts.append("full text")
    return ", ".join(query_parts) if query_parts else "none"


def _intelligence_recovery_targets(inventory: Inventory) -> str:
    targets: list[str] = []
    rubric_target = deep_research_rubric_recovery_target_label(inventory)
    if rubric_target:
        targets.append(rubric_target)
    for rel_path in (
        inventory.state.rel_path if inventory.state else "",
        inventory.active_plan_surface.rel_path if inventory.active_plan_surface else "",
        "README.md",
        "docs/README.md",
        "docs/specs/attach-repair-status-cli.md",
        "docs/specs/generated-state-and-projections.md",
    ):
        if rel_path and rel_path in inventory.surface_by_rel and inventory.surface_by_rel[rel_path].exists and rel_path not in targets:
            targets.append(rel_path)
    return ", ".join(targets[:5]) if targets else "none"


def _remainder_drift_context(surface: Surface, line_number: int, line: str) -> str:
    heading = _heading_for_line(surface, line_number)
    heading_text = heading.casefold()
    line_text = line.casefold()
    line_start = re.sub(r"^[\s>*#\-0-9.)]+", "", line_text).strip()
    text = f"{heading_text} {line_text}"
    if any(marker in text for marker in HISTORICAL_CONTEXT_MARKERS):
        return "historical"
    if (
        any(marker in heading_text for marker in REMAINDER_CONTEXT_MARKERS)
        or any(line_start.startswith(marker) for marker in REMAINDER_CONTEXT_MARKERS)
        or "listed as future" in line_text
        or "still listed" in line_text
        or "still lists" in line_text
        or "remains open" in line_text
    ):
        return "remainder"
    if any(marker in heading_text for marker in DELIVERED_CONTEXT_MARKERS) or any(
        line_start.startswith(marker) for marker in DELIVERED_CONTEXT_MARKERS
    ):
        return "delivered"
    return "neutral"


def _heading_for_line(surface: Surface, line_number: int) -> str:
    current = ""
    for heading in surface.headings:
        if heading.line > line_number:
            break
        current = heading.title
    return current


def _explicit_remainder_tokens(line: str) -> set[str]:
    tokens: set[str] = set()
    for match in re.finditer(r"`([^`\n]{2,100})`", line):
        token = _normalize_remainder_token(match.group(1))
        if _is_remainder_capability_token(token):
            tokens.add(token)
    for match in re.finditer(r'"([^"\n]{2,100})"', line):
        token = _normalize_remainder_token(match.group(1))
        if _is_remainder_capability_token(token):
            tokens.add(token)
    return tokens


def _normalize_remainder_token(token: str) -> str:
    normalized = token.strip().strip(".,;:()[]{}").replace("\\", "/").casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _is_remainder_capability_token(token: str) -> bool:
    if not token or len(token) > 80:
        return False
    if "/" in token or token.endswith((".md", ".toml", ".yaml", ".json", ".py")):
        return False
    if not re.search(r"[a-z]", token):
        return False
    return (
        "--" in token
        or token
        in {
            "adapter",
            "adapters",
            "attach",
            "audit-links",
            "bootstrap",
            "check",
            "closeout",
            "context-budget",
            "detach",
            "doctor",
            "evidence",
            "init",
            "intelligence",
            "preflight",
            "projection",
            "repair",
            "semantic",
            "snapshot",
            "status",
            "tasks",
            "validate",
        }
    )


def _normalize_intelligence_finding(inventory: Inventory, finding: Finding) -> Finding:
    if finding.severity != "warn" or not _intelligence_warning_is_informational(inventory, finding):
        return finding
    return Finding(
        "info",
        finding.code,
        f"{finding.message}; informational in intelligence recovery view",
        finding.source,
        finding.line,
    )


def _intelligence_warning_is_informational(inventory: Inventory, finding: Finding) -> bool:
    text = f"{finding.message} {finding.source or ''}".replace("\\", "/")
    text_lower = text.lower()
    if "%userprofile%" in text_lower or ".codex/config.toml" in text_lower:
        return True
    if "__pycache__" in text_lower or "validation-report" in text_lower:
        return True
    if inventory.root_kind != "live_operating_root":
        return False
    target = _target_from_finding(finding)
    if target.startswith(("src/", "tests/", "research/", "specs/", "templates/", "codex-home/")):
        return True
    if re.search(r"project/(research|archive|verification)/.*\d{4}-\d{2}-\d{2}", target):
        return True
    return False


def _target_from_finding(finding: Finding) -> str:
    message = finding.message.replace("\\", "/")
    if finding.code in {"missing-link", "unresolved-link"}:
        return message.split(" ", 1)[0]
    if finding.code == "backlink-reference" and " -> " in message:
        return message.split(" -> ", 1)[1].split(";", 1)[0]
    if finding.code == "fan-in-target":
        return message.split(":", 1)[0]
    return message


def _repo_map_findings(projection: Projection) -> list[Finding]:
    findings: list[Finding] = []
    for source in projection.sources:
        presence = "present" if source.present else "missing"
        requirement = "required" if source.required else "optional"
        message = (
            f"{source.path}: role={source.role}; {requirement}; {presence}; "
            f"lines={source.line_count}; bytes={source.byte_count}; headings={source.heading_count}; "
            f"links={source.link_count}; hash={_display_hash(source.content_hash)}"
        )
        severity = "warn" if source.required and not source.present else "info"
        findings.append(Finding(severity, "repo-map-surface", message, source.path))
        if source.read_error:
            findings.append(Finding("warn", "repo-map-read-error", f"{source.path}: {source.read_error}", source.path))
    return findings


def _backlink_findings(records: tuple[ProjectionLinkRecord, ...]) -> list[Finding]:
    if not records:
        return [Finding("info", "backlink-empty", "no repo-local path references were found")]
    findings: list[Finding] = []
    for record in records:
        severity = "warn" if record.status in {"missing", "unresolved"} else "info"
        findings.append(
            Finding(
                severity,
                "backlink-reference",
                f"{record.source}:{record.line} -> {record.target}; status={record.status}",
                record.source,
                record.line,
            )
        )
    return findings


def _search_findings(
    inventory: Inventory,
    projection: Projection,
    search_text: str | None,
    path_text: str | None,
    full_text: str | None,
    limit: int,
    query_expansion: Finding | None = None,
) -> list[Finding]:
    if search_text == "":
        search_text = None
    if path_text == "":
        path_text = None
    if full_text == "":
        full_text = None
    if search_text is None and path_text is None and full_text is None:
        return [Finding("info", "search-ready", "no query provided; use --query TEXT, --search TEXT, --path TEXT, and/or --full-text TEXT for inventory search")]

    notes: list[Finding] = []
    if query_expansion is not None:
        notes.append(query_expansion)
    if search_text:
        notes.append(
            Finding(
                "info",
                "projection-exact-search-source-only",
                "exact text search reads direct source content through the in-memory projection; projection artifacts do not store source bodies",
            )
        )
    notes.extend(_navigation_cache_maintenance_findings(inventory, projection, path_text, full_text))
    notes.extend(projection_artifact_path_query_findings(inventory, projection, path_text))
    notes.extend(full_text_search_findings(inventory, projection, full_text, limit))

    findings: list[Finding] = []
    truncated = False

    def add(finding: Finding) -> None:
        nonlocal truncated
        if len(findings) >= SEARCH_RESULT_LIMIT:
            truncated = True
            return
        findings.append(finding)

    if path_text:
        for source in projection.sources:
            if path_text in source.path:
                add(
                    Finding(
                        "info",
                        "search-path-match",
                        f"path match for {path_text!r}: projection source {source.path}",
                        source.path,
                    )
                )
        for record in projection.links:
            if path_text in record.target:
                add(
                    Finding(
                        "info",
                        "search-path-reference",
                        f"path reference match for {path_text!r}: {record.target}; status={record.status}",
                        record.source,
                        record.line,
                    )
                )

    if search_text:
        for source in projection.sources:
            if not source.present:
                continue
            for line_number, line in enumerate(source.content.splitlines(), start=1):
                if search_text in line:
                    add(
                        Finding(
                            "info",
                            "search-match",
                            f"text match for {search_text!r}: {_trim_line(line)}",
                            source.path,
                            line_number,
                        )
                    )

    if not findings:
        if search_text is None and path_text is None:
            return notes
        return notes + [Finding("info", "search-no-matches", "no case-sensitive inventory matches found")]
    if truncated:
        findings.append(Finding("info", "search-truncated", f"showing first {SEARCH_RESULT_LIMIT} deterministic matches"))
    return notes + findings


def _search_findings_from_inventory(
    inventory: Inventory,
    search_text: str | None,
    path_text: str | None,
    query_expansion: Finding | None = None,
) -> list[Finding]:
    if search_text == "":
        search_text = None
    if path_text == "":
        path_text = None
    if search_text is None and path_text is None:
        return [Finding("info", "search-ready", "no query provided; use --query TEXT, --search TEXT, --path TEXT, and/or --full-text TEXT for inventory search")]

    notes: list[Finding] = []
    if query_expansion is not None:
        notes.append(query_expansion)
    if search_text:
        notes.append(
            Finding(
                "info",
                "projection-exact-search-source-only",
                "exact text search reads direct source content through the in-memory inventory; projection artifacts do not store source bodies",
            )
        )

    findings: list[Finding] = []
    truncated = False

    def add(finding: Finding) -> None:
        nonlocal truncated
        if len(findings) >= SEARCH_RESULT_LIMIT:
            truncated = True
            return
        findings.append(finding)

    if path_text:
        for surface in inventory.surfaces:
            if path_text in surface.rel_path:
                add(
                    Finding(
                        "info",
                        "search-path-match",
                        f"path match for {path_text!r}: inventory source {surface.rel_path}",
                        surface.rel_path,
                    )
                )
        for surface in inventory.present_surfaces:
            for link in surface.links:
                if path_text in link.target:
                    add(
                        Finding(
                            "info",
                            "search-path-reference",
                            f"path reference match for {path_text!r}: {link.target}; status=source-only",
                            link.source,
                            link.line,
                        )
                    )

    if search_text:
        for surface in inventory.present_surfaces:
            for line_number, line in enumerate(surface.content.splitlines(), start=1):
                if search_text in line:
                    add(
                        Finding(
                            "info",
                            "search-match",
                            f"text match for {search_text!r}: {_trim_line(line)}",
                            surface.rel_path,
                            line_number,
                        )
                    )

    if not findings:
        return notes + [Finding("info", "search-no-matches", "no case-sensitive inventory matches found")]
    if truncated:
        findings.append(Finding("info", "search-truncated", f"showing first {SEARCH_RESULT_LIMIT} deterministic matches"))
    return notes + findings


def _navigation_cache_maintenance_findings(
    inventory: Inventory,
    projection: Projection,
    path_text: str | None,
    full_text: str | None,
) -> list[Finding]:
    findings: list[Finding] = []
    if path_text not in (None, ""):
        findings.extend(_ensure_projection_artifacts_for_navigation(inventory, projection))
    if full_text not in (None, ""):
        findings.extend(_ensure_projection_index_for_navigation(inventory, projection))
    return findings


def _ensure_projection_artifacts_for_navigation(inventory: Inventory, projection: Projection) -> list[Finding]:
    inspect_findings = inspect_projection_artifacts(inventory, projection)
    blocking = _projection_cache_blocking_findings(inspect_findings, {"projection-artifact-missing"})
    if not blocking:
        return [
            Finding(
                "info",
                "navigation-cache-artifacts-current",
                "projection artifacts are current for path/reference navigation",
                ARTIFACT_DIR_REL,
            )
        ]
    reason = blocking[0]
    refresh = rebuild_projection_artifacts(inventory)
    findings = [
        Finding(
            "info",
            "navigation-cache-artifacts-refresh",
            f"refreshed disposable projection artifacts for path/reference navigation because {reason.code}",
            reason.source or ARTIFACT_DIR_REL,
            reason.line,
        )
    ]
    findings.extend(refresh)
    if any(finding.severity in {"warn", "error"} for finding in refresh):
        findings.append(
            Finding(
                "info",
                "navigation-cache-artifacts-degraded",
                "projection artifact refresh degraded; direct in-memory path search remains authoritative",
                ARTIFACT_DIR_REL,
            )
        )
    return findings


def _ensure_projection_index_for_navigation(inventory: Inventory, projection: Projection) -> list[Finding]:
    inspect_findings = inspect_projection_index(inventory, projection)
    blocking = _projection_cache_blocking_findings(inspect_findings, {"projection-index-missing"})
    if not blocking:
        return [
            Finding(
                "info",
                "navigation-cache-index-current",
                "SQLite FTS/BM25 projection index is current for full-text navigation",
                INDEX_REL_PATH,
            )
        ]
    reason = blocking[0]
    refresh = warm_projection_index(inventory, projection)
    findings = [
        Finding(
            "info",
            "navigation-cache-index-refresh",
            f"refreshed disposable SQLite FTS/BM25 projection index for full-text navigation because {reason.code}",
            reason.source or INDEX_REL_PATH,
            reason.line,
        )
    ]
    findings.extend(refresh)
    if any(finding.severity in {"warn", "error"} for finding in refresh):
        findings.append(
            Finding(
                "info",
                "navigation-cache-index-degraded",
                "SQLite projection index refresh degraded; direct exact/path search remains authoritative",
                INDEX_REL_PATH,
            )
        )
    return findings


def _projection_cache_blocking_findings(findings: list[Finding], missing_codes: set[str]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.severity in {"warn", "error"} or finding.code in missing_codes
    ]


def _fan_in_findings(inventory: Inventory, projection: Projection) -> list[Finding]:
    if not projection.links:
        return [Finding("info", "fan-in-empty", "no repo-local references are available for fan-in analysis")]

    findings: list[Finding] = []
    rows = projection.fan_in[:FAN_IN_RESULT_LIMIT]
    for row in rows:
        severity = "warn" if row.status == "missing" else "info"
        sources = ", ".join(row.sources[:5])
        findings.append(
            Finding(
                severity,
                "fan-in-target",
                f"{row.target}: inbound={row.inbound_count}; status={row.status}; sources={sources}",
                row.source,
            )
        )
    if len(projection.fan_in) > FAN_IN_RESULT_LIMIT:
        findings.append(Finding("info", "fan-in-truncated", f"showing top {FAN_IN_RESULT_LIMIT} referenced paths by inbound count"))

    budget_warnings = [finding for finding in context_budget_findings(inventory) if finding.severity == "warn"]
    if budget_warnings:
        findings.append(Finding("info", "fan-in-context-pressure", f"context-budget warning count: {len(budget_warnings)}"))
    else:
        findings.append(Finding("info", "fan-in-context-pressure", "context-budget has no warning-level pressure signals"))
    return findings


def _projection_findings(inventory: Inventory, projection: Projection) -> list[Finding]:
    summary = projection.summary
    findings = [
        Finding(
            "info",
            "projection-rebuild",
            f"{summary.rebuild_status}; in-memory storage boundary={summary.storage_boundary}; artifact boundary={ARTIFACT_DIR_REL}",
        ),
        Finding(
            "info",
            "projection-authority",
            "repo-visible files remain authoritative; generated artifacts are disposable and never approve repairs, closeout, commits, or lifecycle decisions",
        ),
        Finding(
            "info",
            "projection-source-coverage",
            (
                f"sources={summary.present_source_count}/{summary.source_count} present; "
                f"hashed={summary.hashed_source_count}/{summary.readable_source_count} readable; "
                f"missing_required={summary.missing_required_count}"
            ),
        ),
        Finding(
            "info",
            "projection-record-counts",
            (
                f"source_records={summary.source_count}; link_records={summary.link_record_count}; "
                f"fan_in_records={summary.fan_in_record_count}; relationship_nodes={summary.relationship_node_count}; "
                f"relationship_edges={summary.relationship_edge_count}"
            ),
        ),
    ]
    provenance = _projection_provenance(projection)
    if provenance:
        findings.append(Finding("info", "projection-provenance", f"source hashes: {provenance}"))
    findings.extend(inspect_projection_artifacts(inventory, projection))
    findings.extend(inspect_projection_index(inventory, projection))
    for source in projection.sources:
        if source.required and not source.present:
            findings.append(Finding("warn", "projection-source-missing", f"missing required projection source: {source.path}", source.path))
        if source.read_error:
            findings.append(Finding("warn", "projection-source-read-error", f"{source.path}: {source.read_error}", source.path))
    return findings


def _projection_provenance(projection: Projection, limit: int = 5) -> str:
    rows = [
        f"{source.path}@{_display_hash(source.content_hash)}"
        for source in projection.sources
        if source.content_hash is not None
    ]
    return ", ".join(rows[:limit])


def _display_hash(value: str | None) -> str:
    return value[:12] if value else "none"


def _trim_line(line: str, limit: int = 140) -> str:
    compact = re.sub(r"\s+", " ", line.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _unique_sorted(values) -> list[str]:
    return sorted(set(values))


INTEGRATION_DOCTOR_PROFILE_KEYS = {
    "mcp": "genericMcp",
    "vscode": "vsCode",
    "claude-code": "claudeCode",
    "jetbrains": "jetBrains",
}

INTEGRATION_DOCTOR_NATIVE_HOOK_CLIENTS = {
    "mcp": "",
    "vscode": "",
    "claude-code": "claude-code",
    "jetbrains": "",
}


def doctor_findings(root: Path, inventory: Inventory, integration: str | None = None) -> list[Finding]:
    if integration:
        return integration_doctor_findings(root, inventory, integration)

    hygiene = product_hygiene_findings(inventory)
    hygiene_warnings = [finding for finding in hygiene if finding.severity in {"warn", "error"}]
    relationship_hygiene = relationship_hygiene_scan_findings(inventory)
    relationship_warnings = [finding for finding in relationship_hygiene if finding.severity in {"warn", "error"}]
    findings: list[Finding] = [
        Finding("info", "python", f"python: {sys.version.split()[0]}"),
        Finding("info", "root", f"root exists: {root}"),
    ]
    findings.extend(_git_findings(root))
    findings.extend(hygiene)
    findings.extend(relationship_hygiene)
    findings.extend(connect_readiness_findings(inventory, "doctor-connect-readiness"))
    validation = validation_findings(inventory)
    link_warnings = [finding for finding in audit_link_findings(inventory) if finding.severity in {"warn", "error"}]
    context_warnings = [finding for finding in context_budget_findings(inventory) if finding.severity in {"warn", "error"}]
    error_count = len([finding for finding in validation if finding.severity == "error"])
    warning_count = len([finding for finding in validation if finding.severity == "warn"])
    findings.append(
        Finding(
            "error" if error_count else "warn" if warning_count else "info",
            "validate-summary",
            f"validate findings: {error_count} errors, {warning_count} warnings",
        )
    )
    findings.append(
        Finding(
            "warn" if hygiene_warnings else "info",
            "product-hygiene-summary",
            f"product hygiene warnings/errors: {len(hygiene_warnings)}",
        )
    )
    findings.append(
        Finding(
            "warn" if relationship_warnings else "info",
            "relationship-hygiene-summary",
            f"relationship hygiene warnings/errors: {len(relationship_warnings)}",
        )
    )
    findings.append(
        Finding(
            "warn" if link_warnings else "info",
            "audit-links-summary",
            f"audit-links warnings/errors: {len(link_warnings)}",
        )
    )
    findings.append(
        Finding(
            "warn" if context_warnings else "info",
            "context-budget-summary",
            f"context-budget warnings/errors: {len(context_warnings)}",
        )
    )
    return findings


def integration_doctor_findings(root: Path, inventory: Inventory, integration: str) -> list[Finding]:
    if integration not in INTEGRATION_DOCTOR_PROFILE_KEYS:
        return [
            Finding(
                "error",
                "doctor-integration-unknown",
                f"unknown integration={integration}; expected one of {', '.join(INTEGRATION_DOCTOR_PROFILE_KEYS)}",
            )
        ]
    findings = [
        Finding(
            "info",
            "doctor-integration-read-only",
            (
                f"integration={integration}; read-only diagnostic; no config, hook, cache, lifecycle, Git, "
                "adapter, or provider state writes are performed"
            ),
        ),
        _integration_install_path_finding(),
        Finding(
            "info",
            "doctor-integration-root-kind",
            f"root kind: {inventory.root_kind}; classification is routing posture, not lifecycle validity proof",
        ),
        _integration_manifest_finding(inventory),
    ]
    findings.extend(_integration_mcp_startup_findings(inventory))
    findings.extend(_integration_client_config_findings(inventory, integration))
    findings.extend(_integration_hook_findings(inventory, integration))
    findings.append(_integration_cache_finding(inventory))
    findings.append(
        Finding(
            "info",
            "doctor-integration-authority-boundary",
            (
                "repo-visible files remain authoritative; doctor/check/hooks/adapter/cache outputs are advisory "
                "and cannot approve lifecycle, archive, roadmap status, staging, commit, push, release, "
                "provider routing, or cache truth"
            ),
        )
    )
    return findings


def _integration_install_path_finding() -> Finding:
    console_script = shutil.which("mylittleharness") or "<not-found>"
    return Finding(
        "info",
        "doctor-integration-install-path",
        f"python={sys.executable}; console_script={console_script}; package_version={__version__}; module={Path(__file__).resolve()}",
    )


def _integration_manifest_finding(inventory: Inventory) -> Finding:
    neutral = inventory.surface_by_rel.get(WORKFLOW_MANIFEST_REL)
    legacy = inventory.surface_by_rel.get(LEGACY_WORKFLOW_MANIFEST_REL)
    selected = inventory.manifest_surface.rel_path if inventory.manifest_surface else "<none>"
    return Finding(
        "info",
        "doctor-integration-neutral-manifest",
        (
            f"selected_manifest={selected}; neutral_manifest={_surface_state(neutral)}; "
            f"legacy_manifest={_surface_state(legacy)}; "
            f"next_safe_command={_display_command(['mylittleharness', '--root', str(inventory.root), 'migrate', '--dry-run'])}"
        ),
        WORKFLOW_MANIFEST_REL,
    )


def _integration_mcp_startup_findings(inventory: Inventory) -> list[Finding]:
    from .adapter import (
        MCP_PROTOCOL_VERSION,
        MCP_READ_PROJECTION_RESOURCE_URI,
        MCP_TOOL_NAMES,
        serve_mcp_read_projection,
    )

    request_lines = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "doctor", "version": __version__}},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
    ]
    stdin = io.StringIO("\n".join(json.dumps(line, sort_keys=True, ensure_ascii=True) for line in request_lines) + "\n")
    stdout = io.StringIO()
    try:
        exit_code = serve_mcp_read_projection(inventory, stdin, stdout)
        responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    except Exception as exc:  # pragma: no cover - defensive diagnostic path
        return [Finding("warn", "doctor-integration-mcp-startup-smoke", f"stdio smoke failed before response validation: {exc}")]

    by_id = {response.get("id"): response for response in responses if isinstance(response, dict)}
    initialize = by_id.get(1, {}).get("result", {})
    tools_result = by_id.get(2, {}).get("result", {})
    resources_result = by_id.get(3, {}).get("result", {})
    protocol = initialize.get("protocolVersion") if isinstance(initialize, dict) else ""
    tools = _response_tool_names(tools_result)
    resources = _response_resource_uris(resources_result)
    missing_tools = [tool for tool in MCP_TOOL_NAMES if tool not in tools]
    resource_present = MCP_READ_PROJECTION_RESOURCE_URI in resources
    errors = [response.get("error") for response in responses if isinstance(response, dict) and response.get("error")]
    ok = exit_code == 0 and not errors and protocol == MCP_PROTOCOL_VERSION and not missing_tools and resource_present
    detail = (
        f"stdio smoke {'ok' if ok else 'degraded'}; protocolVersion={protocol or '<missing>'}; "
        f"tools={','.join(tools) or '<none>'}; resource={MCP_READ_PROJECTION_RESOURCE_URI if resource_present else '<missing>'}; "
        f"exit_code={exit_code}"
    )
    if errors:
        detail += f"; errors={len(errors)}"
    if missing_tools:
        detail += f"; missing_tools={','.join(missing_tools)}"
    return [Finding("info" if ok else "warn", "doctor-integration-mcp-startup-smoke", detail)]


def _integration_client_config_findings(inventory: Inventory, integration: str) -> list[Finding]:
    from .adapter import MCP_CLIENT_CONFIGS_SCHEMA, MCP_READ_PROJECTION_TARGET, mcp_read_projection_client_config, mcp_read_projection_serve_command

    config = mcp_read_projection_client_config(inventory)
    profile_key = INTEGRATION_DOCTOR_PROFILE_KEYS[integration]
    profiles = config.get("clientConfigs", {})
    profile = profiles.get(profile_key, {}) if isinstance(profiles, dict) else {}
    command = mcp_read_projection_serve_command(inventory)
    return [
        Finding(
            "info",
            "doctor-integration-client-config",
            (
                f"schema={config.get('schema', MCP_CLIENT_CONFIGS_SCHEMA)}; profile={profile_key}; "
                f"configKey={profile.get('configKey', '<unknown>')}; configSurface={profile.get('configSurface', '<unknown>')}; "
                f"reference={profile.get('reference', '<unknown>')}; "
                f"next_safe_command={_display_command(['mylittleharness', '--root', str(inventory.root), 'adapter', '--client-config', '--target', MCP_READ_PROJECTION_TARGET])}"
            ),
        ),
        Finding(
            "info",
            "doctor-integration-client-command",
            f"server={config.get('serverName', 'mylittleharness')}; command={_display_command(command)}; transport=stdio; read_only=true",
        ),
    ]


def _integration_hook_findings(inventory: Inventory, integration: str) -> list[Finding]:
    from .hooks import hooks_doctor_sections

    hook_findings = flatten_sections(hooks_doctor_sections(inventory))
    status_codes = [finding.code for finding in hook_findings if finding.code.endswith("-status")][:4]
    native_client = INTEGRATION_DOCTOR_NATIVE_HOOK_CLIENTS[integration]
    if native_client:
        posture = (
            f"native_hook_client={native_client}; inspect with "
            f"{_display_command(['mylittleharness', '--root', str(inventory.root), 'hooks', 'adapter', '--client', native_client, '--dry-run', '--scope', 'project'])}"
        )
    else:
        posture = "native_hook_client=<none>; no native hook adapter is implied by this MCP profile"
    status_summary = ",".join(status_codes) if status_codes else "<none>"
    return [
        Finding(
            "info",
            "doctor-integration-hook-posture",
            (
                f"{posture}; hooks --doctor remains read-only; sampled_status_codes={status_summary}; "
                f"next_safe_command={_display_command(['mylittleharness', '--root', str(inventory.root), 'hooks', '--doctor'])}"
            ),
        )
    ]


def _integration_cache_finding(inventory: Inventory) -> Finding:
    projection = build_projection(inventory)
    artifact_findings = inspect_projection_artifacts(inventory, projection)
    index_findings = inspect_projection_index(inventory, projection)
    posture = projection_cache_posture_payload(
        artifact_findings,
        index_findings,
        runtime_refresh_allowed=inventory.root_kind != PRODUCT_SOURCE_FIXTURE,
    )
    components = posture.get("components", {})
    artifact_status = _component_status(components, "artifacts")
    index_status = _component_status(components, "sqlite_index")
    commands = posture.get("recommended_refresh_commands", [])
    command_text = ", ".join(str(command) for command in commands) if isinstance(commands, list) else str(commands)
    return Finding(
        "info",
        "doctor-integration-cache-posture",
        (
            f"schema={posture.get('schema')}; artifacts={artifact_status}; sqlite_index={index_status}; "
            f"refresh_by_adapter=false; adapter_executes_refresh=false; recommended_commands={command_text}"
        ),
        ARTIFACT_DIR_REL,
    )


def _surface_state(surface: Surface | None) -> str:
    if surface is None or not surface.exists:
        return "missing"
    if surface.read_error:
        return "unreadable"
    return "present"


def _display_command(command: list[str]) -> str:
    return " ".join(shell_arg(part) for part in command)


def _response_tool_names(result: object) -> list[str]:
    if not isinstance(result, dict):
        return []
    tools = result.get("tools")
    if not isinstance(tools, list):
        return []
    return [str(tool.get("name")) for tool in tools if isinstance(tool, dict) and tool.get("name")]


def _response_resource_uris(result: object) -> list[str]:
    if not isinstance(result, dict):
        return []
    resources = result.get("resources")
    if not isinstance(resources, list):
        return []
    return [str(resource.get("uri")) for resource in resources if isinstance(resource, dict) and resource.get("uri")]


def _component_status(components: object, key: str) -> str:
    if not isinstance(components, dict):
        return "<unknown>"
    component = components.get(key)
    if not isinstance(component, dict):
        return "<unknown>"
    return str(component.get("status") or "<unknown>")


WORKFLOW_ATTACH_DIRECTORIES = (
    ".agents",
    "project/specs/workflow",
    "project/research",
    "project/plan-incubation",
    "project/decisions",
    "project/adrs",
    "project/verification",
    "project/verification/agent-runs",
    "project/verification/approval-packets",
    "project/verification/handoffs",
    "project/verification/session-active-work",
    "project/verification/work-claims",
    "project/archive/plans",
    "project/archive/reference",
)

DETACH_PRESERVED_AUTHORITY_PATHS = (
    WORKFLOW_MANIFEST_REL,
    LEGACY_WORKFLOW_MANIFEST_REL,
    "project/project-state.md",
    ".agents/docmap.yaml",
    "project/specs/workflow/",
    "project/archive/",
    "project/research/",
    ".mylittleharness/snapshots/repair/",
)
DETACH_MARKER_DIR_REL = ".mylittleharness/detach"
DETACH_MARKER_REL_PATH = f"{DETACH_MARKER_DIR_REL}/disabled.json"
DETACH_MARKER_SCHEMA_VERSION = 1
DETACH_MARKER_MANUAL_RECOVERY = f"manual recovery only: remove {DETACH_MARKER_REL_PATH} to clear the marker; preserved repo-visible authority files remain the source of truth"
DETACH_MARKER_NON_AUTHORITY = "detach marker is informational evidence only and cannot approve cleanup, repair, closeout, archive, commit, rollback, lifecycle decisions, or future mutations"


def detach_dry_run_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    return [
        ("Root Posture", _detach_root_posture_findings(inventory)),
        ("Preservation", _detach_preservation_findings(inventory)),
        ("Marker", _detach_marker_preview_findings(inventory)),
        ("Generated Projection", _detach_generated_projection_findings(inventory)),
        ("Manual Recovery", _detach_recovery_findings()),
        ("Boundary", _detach_boundary_findings(inventory)),
    ]


def detach_apply_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    return [
        ("Root Posture", _detach_apply_root_findings(inventory)),
        ("Preservation", _detach_preservation_findings(inventory)),
        ("Marker", _detach_marker_apply_findings(inventory)),
        ("Generated Projection", _detach_generated_projection_findings(inventory)),
        ("Manual Recovery", _detach_apply_recovery_findings()),
        ("Boundary", _detach_apply_boundary_findings(inventory)),
    ]


def _detach_root_posture_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-dry-run", "detach preview only; no files, reports, caches, generated outputs, snapshots, Git state, config, hooks, or package artifacts are written"),
        Finding("info", "detach-root-kind", f"root kind: {inventory.root_kind}"),
    ]
    if _is_product_source_inventory(inventory):
        findings.extend(
            [
                Finding(
                    "info",
                    "detach-root-posture",
                    "product-source compatibility fixture: detach reports fixture preservation only; future detach apply would be refused",
                    inventory.state.rel_path if inventory.state else None,
                ),
                Finding(
                    "warn",
                    "detach-refused",
                    "product-source compatibility fixture: detach dry-run is a refused preview with no safe matching apply path for this root",
                    inventory.state.rel_path if inventory.state else None,
                ),
            ]
        )
    elif _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "detach-refused",
                "target is fallback/archive or generated-output evidence; future detach apply would be refused before mutation",
                inventory.state.rel_path if inventory.state else None,
            )
        )
    elif inventory.root_kind == "live_operating_root":
        findings.append(Finding("info", "detach-root-posture", "live operating root: detach dry-run reports preservation and future-apply refusal posture only"))
    else:
        findings.append(Finding("warn", "detach-refused", "target role is ambiguous; future detach apply would be refused before mutation"))

    manifest = inventory.manifest_surface
    if manifest is None or not manifest.exists:
        findings.append(Finding("warn", "detach-refused", "workflow manifest is missing; future detach apply would be refused", _selected_manifest_rel(inventory)))
    elif manifest.read_error:
        findings.append(Finding("warn", "detach-refused", f"workflow manifest is unreadable: {manifest.read_error}", manifest.rel_path))
    for error in inventory.manifest_errors:
        findings.append(Finding("warn", "detach-refused", f"workflow manifest is malformed: {error}", manifest.rel_path if manifest else _selected_manifest_rel(inventory)))

    state = inventory.state
    if state is None or not state.exists:
        findings.append(Finding("warn", "detach-refused", "project state is missing; future detach apply would be refused", "project/project-state.md"))
    elif state.read_error:
        findings.append(Finding("warn", "detach-refused", f"project state is unreadable: {state.read_error}", state.rel_path))

    memory = inventory.manifest.get("memory", {}) if inventory.manifest else {}
    state_file = str(memory.get("state_file", "project/project-state.md")).replace("\\", "/")
    plan_file = str(memory.get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
    if state_file != "project/project-state.md":
        findings.append(Finding("warn", "detach-refused", f"non-default state_file is preserved and future detach apply is refused: {state_file}", manifest.rel_path if manifest else None))
    if plan_file != "project/implementation-plan.md":
        findings.append(Finding("warn", "detach-refused", f"non-default plan_file is preserved and future detach apply is refused: {plan_file}", manifest.rel_path if manifest else None))
    return findings


def _detach_apply_root_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-apply", "detach apply is marker-only; it never deletes, rewrites, archives, repairs, cleans, commits, or mutates Git/config/hooks/CI/package/workstation state"),
        Finding("info", "detach-root-kind", f"root kind: {inventory.root_kind}"),
    ]
    findings.extend(_detach_apply_refusal_findings(inventory))
    return findings


def _detach_preservation_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-preservation-policy", "preservation beats cleanup; repo-visible authority remains inspectable"),
        Finding("info", "detach-disable-candidate", "no disable marker, metadata toggle, rewritten file, removed path, archive move, or cleanup candidate is selected in this dry-run"),
    ]
    for rel_path in DETACH_PRESERVED_AUTHORITY_PATHS:
        path = inventory.root / rel_path.rstrip("/")
        status = "present" if path.exists() else "absent"
        findings.append(Finding("info", "detach-preserve", f"preserve {status} path: {rel_path}", rel_path.rstrip("/")))
    return findings


def _detach_marker_preview_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-marker-target", f"marker-only apply target: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH),
        Finding("info", "detach-marker-preview", "detach --dry-run creates no marker; detach --apply may create this file only in an eligible live operating root", DETACH_MARKER_REL_PATH),
        Finding("info", "detach-marker-authority", DETACH_MARKER_NON_AUTHORITY, DETACH_MARKER_REL_PATH),
    ]
    marker = inventory.surface_by_rel.get(DETACH_MARKER_REL_PATH)
    if marker and marker.exists:
        findings.extend(_detach_marker_status_findings(inventory, marker))
    return findings


def _detach_marker_apply_findings(inventory: Inventory) -> list[Finding]:
    findings = [Finding("info", "detach-marker-target", f"marker-only apply target: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH)]
    preflight_errors = _detach_apply_refusal_findings(inventory) + _detach_apply_path_conflict_findings(inventory)
    if preflight_errors:
        findings.extend(preflight_errors)
        return findings

    target = inventory.root / DETACH_MARKER_REL_PATH
    if target.exists():
        marker_error = _detach_marker_validation_error(inventory, target)
        if marker_error:
            findings.append(marker_error)
        else:
            findings.append(Finding("info", "detach-marker-unchanged", f"valid detach marker already exists and was left unchanged: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH))
            findings.append(Finding("info", "detach-marker-authority", DETACH_MARKER_NON_AUTHORITY, DETACH_MARKER_REL_PATH))
        return findings

    payload = _detach_marker_payload(inventory, _current_marker_timestamp())
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        findings.append(Finding("error", "detach-marker-refused", f"failed to create detach marker before apply completed: {exc}", DETACH_MARKER_REL_PATH))
        return findings

    findings.extend(
        [
            Finding("info", "detach-marker-created", f"created marker-only detach evidence: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH),
            Finding("info", "detach-marker-status", "status: disabled", DETACH_MARKER_REL_PATH),
            Finding("info", "detach-marker-recovery", DETACH_MARKER_MANUAL_RECOVERY, DETACH_MARKER_REL_PATH),
            Finding("info", "detach-marker-authority", DETACH_MARKER_NON_AUTHORITY, DETACH_MARKER_REL_PATH),
        ]
    )
    return findings


def _detach_generated_projection_findings(inventory: Inventory) -> list[Finding]:
    projection_path = inventory.root / ARTIFACT_DIR_REL
    if projection_path.exists() and (projection_path.is_symlink() or not projection_path.is_dir()):
        return [
            Finding("warn", "detach-boundary-conflict", f"generated projection boundary is not a directory: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            Finding("info", "detach-generated-projection", "generated projection cleanup is not proposed by detach dry-run"),
        ]
    if projection_path.exists():
        return [
            Finding("info", "detach-generated-projection", f"disposable generated projection boundary is present and preserved: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            Finding("info", "detach-generated-projection-authority", "generated projections remain build-to-delete speedups and cannot approve detach, repair, closeout, archive, commit, lifecycle decisions"),
        ]
    return [
        Finding("info", "detach-generated-projection", f"disposable generated projection boundary is absent and no cleanup is proposed: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
        Finding("info", "detach-generated-projection-authority", "generated projections remain build-to-delete speedups and are preserved when present"),
    ]


def _detach_recovery_findings() -> list[Finding]:
    return [
        Finding("info", "detach-recovery", "no detach mutation occurred; recovery starts from preserved repo-visible files and normal source control or operator backups"),
        Finding("info", "detach-apply-marker-only", "detach --apply creates or reuses only the marker file in eligible live operating roots; preserved authority files remain the source of truth"),
        Finding("info", "detach-disable-terminology", "disable is explanatory terminology for a possible future effect, not a CLI command or alias in this slice"),
    ]


def _detach_apply_recovery_findings() -> list[Finding]:
    return [
        Finding("info", "detach-recovery", DETACH_MARKER_MANUAL_RECOVERY, DETACH_MARKER_REL_PATH),
        Finding("info", "detach-apply-marker-only", "detach --apply creates or reuses only the marker file; preserved authority files, generated projections, archives, research, and repair snapshots are not changed"),
        Finding("info", "detach-disable-terminology", "disable is explanatory terminology for the marker effect, not a CLI command or alias"),
    ]


def migrate_dry_run_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "migrate-dry-run", "migrate proposal only; no files were written"),
        Finding(
            "info",
            "migrate-boundary",
            (
                f"migrate copies {LEGACY_WORKFLOW_MANIFEST_REL} to {WORKFLOW_MANIFEST_REL}; "
                "legacy manifest deletion remains a separate manual or future gated action"
            ),
            WORKFLOW_MANIFEST_REL,
        ),
    ]
    errors = _manifest_migrate_preflight_errors(inventory)
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        return findings
    plan = _manifest_migrate_write_plan(inventory)
    if plan.before_text == plan.after_text:
        findings.append(Finding("info", "migrate-unchanged", f"neutral manifest already matches legacy manifest: {WORKFLOW_MANIFEST_REL}", WORKFLOW_MANIFEST_REL))
    else:
        findings.append(Finding("info", "migrate-plan", f"would copy legacy workflow manifest to neutral manifest: {LEGACY_WORKFLOW_MANIFEST_REL} -> {WORKFLOW_MANIFEST_REL}", WORKFLOW_MANIFEST_REL))
        findings.extend(route_write_findings("migrate-route-write", (plan,), apply=False))
    findings.append(Finding("info", "migrate-legacy-preserved", f"legacy manifest is preserved: {LEGACY_WORKFLOW_MANIFEST_REL}", LEGACY_WORKFLOW_MANIFEST_REL))
    return findings


def migrate_apply_findings(inventory: Inventory) -> list[Finding]:
    findings = [Finding("info", "migrate-apply", "manifest migration apply started")]
    errors = _manifest_migrate_preflight_errors(inventory)
    if errors:
        findings.extend(errors)
        return findings
    plan = _manifest_migrate_write_plan(inventory)
    if plan.before_text == plan.after_text:
        findings.append(Finding("info", "migrate-unchanged", f"neutral manifest already matches legacy manifest: {WORKFLOW_MANIFEST_REL}", WORKFLOW_MANIFEST_REL))
        findings.append(Finding("info", "migrate-legacy-preserved", f"legacy manifest is preserved: {LEGACY_WORKFLOW_MANIFEST_REL}", LEGACY_WORKFLOW_MANIFEST_REL))
        return findings
    target = inventory.root / WORKFLOW_MANIFEST_REL
    try:
        cleanup_warnings = apply_file_transaction(
            (
                AtomicFileWrite(
                    target,
                    target.with_name(f".{target.name}.migrate.tmp"),
                    plan.after_text or "",
                    target.with_name(f".{target.name}.migrate.backup"),
                ),
            ),
            root=inventory.root,
        )
    except (OSError, FileTransactionError) as exc:
        findings.append(Finding("error", "migrate-refused", f"failed to write neutral workflow manifest before apply completed: {exc}", WORKFLOW_MANIFEST_REL))
        return findings
    findings.append(Finding("info", "migrate-copied", f"copied exact legacy workflow manifest to neutral manifest: {LEGACY_WORKFLOW_MANIFEST_REL} -> {WORKFLOW_MANIFEST_REL}", WORKFLOW_MANIFEST_REL))
    findings.extend(route_write_findings("migrate-route-write", (plan,), apply=True))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "migrate-cleanup-warning", warning, WORKFLOW_MANIFEST_REL))
    findings.append(Finding("info", "migrate-legacy-preserved", f"legacy manifest is preserved: {LEGACY_WORKFLOW_MANIFEST_REL}", LEGACY_WORKFLOW_MANIFEST_REL))
    return findings


def _manifest_migrate_preflight_errors(inventory: Inventory) -> list[Finding]:
    errors: list[Finding] = []
    if _is_product_source_inventory(inventory):
        errors.append(Finding("error", "migrate-refused", "target is a product-source compatibility fixture; migrate --apply is refused", inventory.state.rel_path if inventory.state else None))
    elif _is_fallback_or_archive_inventory(inventory):
        errors.append(Finding("error", "migrate-refused", "target is fallback/archive or generated-output evidence; migrate --apply is refused", inventory.state.rel_path if inventory.state else None))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "migrate-refused", f"target root kind is {inventory.root_kind}; migrate requires an explicit live operating root"))
    if inventory.root.is_symlink():
        errors.append(Finding("error", "migrate-refused", f"target root is a symlink: {inventory.root}"))

    legacy_path = inventory.root / LEGACY_WORKFLOW_MANIFEST_REL
    neutral_path = inventory.root / WORKFLOW_MANIFEST_REL
    errors.extend(_manifest_migrate_path_conflicts(inventory.root, LEGACY_WORKFLOW_MANIFEST_REL, must_exist=True, label="legacy manifest"))
    errors.extend(_manifest_migrate_path_conflicts(inventory.root, WORKFLOW_MANIFEST_REL, must_exist=False, label="neutral manifest"))

    legacy = inventory.surface_by_rel.get(LEGACY_WORKFLOW_MANIFEST_REL)
    neutral = inventory.surface_by_rel.get(WORKFLOW_MANIFEST_REL)
    if legacy is None or not legacy.exists:
        errors.append(Finding("error", "migrate-refused", f"legacy workflow manifest is missing: {LEGACY_WORKFLOW_MANIFEST_REL}", LEGACY_WORKFLOW_MANIFEST_REL))
    elif legacy.read_error:
        errors.append(Finding("error", "migrate-refused", f"legacy workflow manifest is unreadable: {legacy.read_error}", LEGACY_WORKFLOW_MANIFEST_REL))
    for error in inventory.manifest_errors:
        if inventory.manifest_surface and inventory.manifest_surface.rel_path == LEGACY_WORKFLOW_MANIFEST_REL:
            errors.append(Finding("error", "migrate-refused", f"legacy workflow manifest is malformed: {error}", LEGACY_WORKFLOW_MANIFEST_REL))
    if neutral and neutral.exists and neutral.read_error:
        errors.append(Finding("error", "migrate-refused", f"neutral workflow manifest is unreadable: {neutral.read_error}", WORKFLOW_MANIFEST_REL))

    if legacy_path.is_file() and neutral_path.is_file():
        try:
            legacy_text = legacy_path.read_bytes().decode("utf-8")
            neutral_text = neutral_path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(Finding("error", "migrate-refused", f"workflow manifest bytes are not valid UTF-8: {exc}", WORKFLOW_MANIFEST_REL))
        except OSError as exc:
            errors.append(Finding("error", "migrate-refused", f"could not compare workflow manifests: {exc}", WORKFLOW_MANIFEST_REL))
        else:
            if legacy_text != neutral_text:
                errors.append(Finding("error", "migrate-refused", f"neutral workflow manifest already exists and differs from legacy manifest: {WORKFLOW_MANIFEST_REL}", WORKFLOW_MANIFEST_REL))
    return errors


def _manifest_migrate_path_conflicts(root: Path, rel_path: str, *, must_exist: bool, label: str) -> list[Finding]:
    findings: list[Finding] = []
    target = root / rel_path
    for candidate in _root_relative_path_chain(root, rel_path):
        candidate_rel = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            findings.append(Finding("error", "migrate-refused", f"{label} path contains a symlink segment: {candidate_rel}", candidate_rel))
            return findings
        if candidate != target and candidate.exists() and not candidate.is_dir():
            findings.append(Finding("error", "migrate-refused", f"{label} path contains a non-directory segment: {candidate_rel}", candidate_rel))
            return findings
    if not _path_stays_within_root(root, target):
        findings.append(Finding("error", "migrate-refused", f"{label} path would escape the target root: {rel_path}", rel_path))
    elif must_exist and not target.exists():
        findings.append(Finding("error", "migrate-refused", f"{label} is missing: {rel_path}", rel_path))
    elif target.exists() and not target.is_file():
        findings.append(Finding("error", "migrate-refused", f"{label} path is not a regular file: {rel_path}", rel_path))
    return findings


def _manifest_migrate_write_plan(inventory: Inventory) -> RouteWriteEvidence:
    target = inventory.root / WORKFLOW_MANIFEST_REL
    legacy_text = (inventory.root / LEGACY_WORKFLOW_MANIFEST_REL).read_bytes().decode("utf-8")
    neutral_text = target.read_bytes().decode("utf-8") if target.exists() else None
    return RouteWriteEvidence(WORKFLOW_MANIFEST_REL, neutral_text, legacy_text)


def _detach_boundary_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-read-only", "detach --dry-run writes no files, reports, caches, generated outputs, snapshots, Git state, config, hooks, CI files, package artifacts, or workstation state"),
        Finding("info", "detach-no-authority", "detach dry-run output cannot approve cleanup, repair, closeout, archive, commit, lifecycle decisions, or future mutations"),
    ]
    findings.extend(_detach_path_conflict_findings(inventory))
    return findings


def _detach_apply_boundary_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-apply-boundary", f"detach --apply may create only {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH),
        Finding("info", "detach-no-authority", DETACH_MARKER_NON_AUTHORITY, DETACH_MARKER_REL_PATH),
    ]
    findings.extend(_detach_apply_path_conflict_findings(inventory))
    return findings


def _detach_path_conflict_findings(inventory: Inventory, severity: str = "warn") -> list[Finding]:
    checks = {
        ".codex": "dir",
        ".codex/project-workflow.toml": "file",
        ".mylittleharness/project-workflow.toml": "file",
        "project": "dir",
        "project/project-state.md": "file",
        ".agents": "dir",
        ".agents/docmap.yaml": "file",
        "project/specs/workflow": "dir",
        "project/archive": "dir",
        "project/research": "dir",
        ".mylittleharness": "dir",
        ".mylittleharness/generated": "dir",
        ARTIFACT_DIR_REL: "dir",
        ".mylittleharness/snapshots/repair": "dir",
    }
    findings: list[Finding] = []
    for rel_path, expected_kind in checks.items():
        path = inventory.root / rel_path
        if path.is_symlink():
            findings.append(Finding(severity, "detach-boundary-conflict", f"path contains a symlink and is preserved without mutation: {rel_path}", rel_path))
            continue
        if not path.exists():
            continue
        if expected_kind == "dir" and not path.is_dir():
            findings.append(Finding(severity, "detach-boundary-conflict", f"expected directory path is not a directory and is preserved without mutation: {rel_path}", rel_path))
        if expected_kind == "file" and not path.is_file():
            findings.append(Finding(severity, "detach-boundary-conflict", f"expected file path is not a file and is preserved without mutation: {rel_path}", rel_path))
    return findings


def _detach_apply_path_conflict_findings(inventory: Inventory) -> list[Finding]:
    findings = _detach_path_conflict_findings(inventory, severity="error")
    marker_conflict = _detach_marker_target_conflict(inventory.root)
    if marker_conflict:
        findings.append(marker_conflict)
    return findings


def _detach_apply_refusal_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    if _is_product_source_inventory(inventory):
        findings.append(Finding("error", "detach-refused", "target is a product-source compatibility fixture; detach --apply is refused before mutation", inventory.state.rel_path if inventory.state else None))
    elif _is_fallback_or_archive_inventory(inventory):
        findings.append(Finding("error", "detach-refused", "target is fallback/archive or generated-output evidence; detach --apply is refused before mutation", inventory.state.rel_path if inventory.state else None))
    elif inventory.root_kind != "live_operating_root":
        findings.append(Finding("error", "detach-refused", f"target root kind is {inventory.root_kind}; detach --apply requires an explicit live operating root"))

    manifest = inventory.manifest_surface
    if manifest is None or not manifest.exists:
        findings.append(Finding("error", "detach-refused", "workflow manifest is missing; detach --apply is refused", _selected_manifest_rel(inventory)))
    elif manifest.read_error:
        findings.append(Finding("error", "detach-refused", f"workflow manifest is unreadable: {manifest.read_error}", manifest.rel_path))
    for error in inventory.manifest_errors:
        findings.append(Finding("error", "detach-refused", f"workflow manifest is malformed: {error}", manifest.rel_path if manifest else _selected_manifest_rel(inventory)))
    if inventory.manifest and inventory.manifest.get("workflow") != "workflow-core":
        findings.append(Finding("error", "detach-refused", "detach --apply requires manifest workflow = workflow-core", manifest.rel_path if manifest else _selected_manifest_rel(inventory)))

    state = inventory.state
    if state is None or not state.exists:
        findings.append(Finding("error", "detach-refused", "project state is missing; detach --apply is refused", "project/project-state.md"))
    elif state.read_error:
        findings.append(Finding("error", "detach-refused", f"project state is unreadable: {state.read_error}", state.rel_path))

    memory = inventory.manifest.get("memory", {}) if inventory.manifest else {}
    state_file = str(memory.get("state_file", "project/project-state.md")).replace("\\", "/")
    plan_file = str(memory.get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
    if state_file != "project/project-state.md":
        findings.append(Finding("error", "detach-refused", f"non-default state_file is preserved and detach --apply is refused: {state_file}", manifest.rel_path if manifest else None))
    if plan_file != "project/implementation-plan.md":
        findings.append(Finding("error", "detach-refused", f"non-default plan_file is preserved and detach --apply is refused: {plan_file}", manifest.rel_path if manifest else None))
    return findings


def _detach_marker_target_conflict(root: Path) -> Finding | None:
    target = root / DETACH_MARKER_REL_PATH
    for candidate in _root_relative_path_chain(root, DETACH_MARKER_REL_PATH):
        candidate_rel = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            return Finding("error", "detach-marker-refused", f"marker path contains a symlink segment: {candidate_rel}", candidate_rel)
        if candidate != target and candidate.exists() and not candidate.is_dir():
            return Finding("error", "detach-marker-refused", f"marker path contains a non-directory segment: {candidate_rel}", candidate_rel)
    if target.exists() and not target.is_file():
        return Finding("error", "detach-marker-refused", f"marker path is not a regular file: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH)
    if not _path_stays_within_root(root, target):
        return Finding("error", "detach-marker-refused", f"marker path would escape the target root: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH)
    return None


def _detach_marker_status_findings(inventory: Inventory, marker: Surface) -> list[Finding]:
    if marker.read_error:
        return [Finding("warn", "detach-marker-invalid", f"detach marker could not be read: {marker.read_error}", marker.rel_path)]
    marker_error = _detach_marker_validation_error(inventory, marker.path)
    if marker_error:
        return [Finding("warn", "detach-marker-invalid", marker_error.message, marker.rel_path)]
    return [
        Finding("info", "detach-marker-present", f"detach marker present: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH),
        Finding("info", "detach-marker-status", "status: disabled", DETACH_MARKER_REL_PATH),
        Finding("info", "detach-marker-authority", DETACH_MARKER_NON_AUTHORITY, DETACH_MARKER_REL_PATH),
    ]


def _detach_marker_validation_error(inventory: Inventory, path: Path) -> Finding | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Finding("error", "detach-marker-refused", f"existing detach marker is unreadable or invalid JSON: {exc}", DETACH_MARKER_REL_PATH)
    if not isinstance(payload, dict):
        return Finding("error", "detach-marker-refused", "existing detach marker payload must be a JSON object", DETACH_MARKER_REL_PATH)
    expected_values = {
        "schema_version": DETACH_MARKER_SCHEMA_VERSION,
        "status": "disabled",
        "command": "detach --apply",
        "marker_path": DETACH_MARKER_REL_PATH,
        "manual_recovery": DETACH_MARKER_MANUAL_RECOVERY,
        "non_authority": DETACH_MARKER_NON_AUTHORITY,
    }
    for key, expected in expected_values.items():
        if payload.get(key) != expected:
            return Finding("error", "detach-marker-refused", f"existing detach marker has unexpected {key}: {payload.get(key)!r}", DETACH_MARKER_REL_PATH)
    if not isinstance(payload.get("created_at_utc"), str) or not payload.get("created_at_utc"):
        return Finding("error", "detach-marker-refused", "existing detach marker is missing created_at_utc", DETACH_MARKER_REL_PATH)
    if not _same_path_value(payload.get("root"), inventory.root):
        return Finding("error", "detach-marker-refused", f"existing detach marker root does not match target root: {payload.get('root')!r}", DETACH_MARKER_REL_PATH)
    if payload.get("preserved_authority_paths") != list(DETACH_PRESERVED_AUTHORITY_PATHS):
        return Finding("error", "detach-marker-refused", "existing detach marker preserved_authority_paths do not match the current contract", DETACH_MARKER_REL_PATH)
    return None


def _detach_marker_payload(inventory: Inventory, timestamp: str) -> dict[str, object]:
    return {
        "schema_version": DETACH_MARKER_SCHEMA_VERSION,
        "status": "disabled",
        "command": "detach --apply",
        "root": str(inventory.root),
        "marker_path": DETACH_MARKER_REL_PATH,
        "created_at_utc": timestamp,
        "preserved_authority_paths": list(DETACH_PRESERVED_AUTHORITY_PATHS),
        "manual_recovery": DETACH_MARKER_MANUAL_RECOVERY,
        "non_authority": DETACH_MARKER_NON_AUTHORITY,
    }


def _current_marker_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def attach_dry_run_findings(inventory: Inventory, project_name: str | None = None) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "dry-run", "attach proposal only; no files or directories were written"),
        Finding("info", "mutation-guard", "use attach --apply for explicit create-only scaffold writes"),
    ]
    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "info",
                "attach-scope",
                "target is a product-source compatibility fixture; operating-root scaffold expansion is intentionally not proposed",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        findings.append(
            Finding(
                "info",
                "attach-proposal",
                "no-op: keep product source clean and attach live operating roots from an explicit operating root",
            )
        )
        return findings

    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "attach-refused",
                "target is fallback/archive or generated-output evidence; attach --apply would be refused before mutation",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings

    normalized_project = _normalize_project_name(project_name)
    if _is_attach_already_attached_live_root(inventory, normalized_project):
        findings.extend(_attach_already_attached_dry_run_findings(inventory))
        findings.extend(connect_readiness_findings(inventory, "attach-connect-readiness"))
        return findings

    state_path = inventory.root / ATTACH_STATE_REL_PATH
    if not state_path.exists() and normalized_project is None:
        findings.append(
            Finding(
                "warn",
                "attach-project-required",
                "--project <name> would be required because project/project-state.md would be created",
                ATTACH_STATE_REL_PATH,
            )
        )

    preflight_errors = _attach_apply_preflight_errors(inventory, normalized_project)
    if preflight_errors:
        findings.extend(
            Finding(
                "warn",
                error.code,
                f"attach --apply would be refused before mutation: {error.message}",
                error.source,
                error.line,
            )
            for error in preflight_errors
        )
        return findings

    findings.append(
        Finding(
            "info",
            "attach-codex-hooks-autoadoption",
            "default init/attach apply would create or refresh project-local Codex native hooks; Codex Trust and user-global client config remain client-owned",
            ".codex/hooks.json",
        )
    )

    missing_dirs = [rel_path for rel_path in WORKFLOW_ATTACH_DIRECTORIES if not (inventory.root / rel_path).exists()]
    if missing_dirs:
        for rel_path in missing_dirs:
            findings.append(Finding("warn", "attach-proposal", f"would create scaffold directory: {rel_path}", rel_path))
    else:
        findings.append(Finding("info", "attach-proposal", "all eager scaffold directories are already present"))

    for surface in inventory.surfaces:
        if surface.required and not surface.exists:
            findings.append(Finding("warn", "attach-proposal", f"would require file content for missing surface: {surface.rel_path}", surface.rel_path))

    if not any(finding.code == "attach-proposal" and finding.severity == "warn" for finding in findings):
        findings.append(Finding("info", "attach-proposal", "no missing required surfaces were found"))
    findings.extend(connect_readiness_findings(inventory, "attach-connect-readiness"))
    return findings


ATTACH_MANIFEST_REL_PATH = WORKFLOW_MANIFEST_REL
ATTACH_STATE_REL_PATH = "project/project-state.md"
ATTACH_RECOVERY_CHECK_COMMAND = "next_safe_command=mylittleharness --root <root> check"
ATTACH_CODEX_HOOKS_RECOVERY_COMMAND = (
    "next_safe_command=mylittleharness --root <root> hooks adapter --client codex --apply --scope project"
)


def attach_apply_findings(inventory: Inventory, project_name: str | None) -> list[Finding]:
    if _is_product_source_inventory(inventory):
        return [
            Finding(
                "error",
                "attach-refused",
                "target is a product-source compatibility fixture; attach --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        ]
    if _is_fallback_or_archive_inventory(inventory):
        return [
            Finding(
                "error",
                "attach-refused",
                "target is fallback/archive or generated-output evidence; attach --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        ]

    normalized_project = _normalize_project_name(project_name)
    if _is_attach_already_attached_live_root(inventory, normalized_project):
        return _attach_already_attached_apply_findings(inventory)

    state_path = inventory.root / ATTACH_STATE_REL_PATH
    if not state_path.exists() and normalized_project is None:
        return [
            Finding(
                "error",
                "attach-project-required",
                "--project <name> is required because project/project-state.md would be created",
                ATTACH_STATE_REL_PATH,
            )
        ]

    errors = _attach_apply_preflight_errors(inventory, normalized_project)
    errors.extend(_attach_generated_projection_preflight_errors(inventory))
    if errors:
        return errors

    findings: list[Finding] = [Finding("info", "attach-apply", "create-only attach apply started")]
    created_paths: list[str] = []
    existing_paths: list[str] = []

    for rel_path in WORKFLOW_ATTACH_DIRECTORIES:
        path = inventory.root / rel_path
        if path.exists():
            existing_paths.append(rel_path)
            continue
        path.mkdir(parents=True, exist_ok=False)
        created_paths.append(rel_path)

    templates = _attach_apply_templates(normalized_project, inventory)
    for rel_path, content in templates.items():
        path = inventory.root / rel_path
        if path.exists():
            existing_paths.append(rel_path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        created_paths.append(rel_path)

    for rel_path in created_paths:
        findings.append(Finding("info", "attach-created", f"created create-only attach path: {rel_path}", rel_path))
    for rel_path in existing_paths:
        findings.append(Finding("info", "attach-existing", f"preserved existing attach path without changes: {rel_path}", rel_path))
    if not created_paths:
        findings.append(Finding("info", "attach-unchanged", "no file or directory changes were needed"))
    findings.append(
        Finding(
            "info",
            "attach-apply-boundary",
            "attach --apply wrote eager scaffold directories, absent manifest/state templates, project-local Codex native hooks, and attach-time disposable generated projection output; Codex Trust and user-global client config remain client-owned, and hooks are not correctness prerequisites",
        )
    )
    refreshed_inventory = load_inventory(inventory.root)
    hook_findings = _attach_codex_hooks_default_apply_findings(refreshed_inventory, after_scaffold_write=True)
    findings.extend(hook_findings)
    if any(finding.severity == "error" for finding in hook_findings):
        findings.extend(connect_readiness_findings(load_inventory(inventory.root), "attach-connect-readiness"))
        return findings
    findings.extend(_attach_generated_projection_findings(refreshed_inventory, after_scaffold_write=True))
    findings.extend(connect_readiness_findings(load_inventory(inventory.root), "attach-connect-readiness"))
    return findings


def _attach_codex_hooks_default_apply_findings(inventory: Inventory, *, after_scaffold_write: bool = False) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "attach-codex-hooks-autoadoption",
            "attach/init apply keeps the project-local Codex native hook adapter current by default; Codex Trust and user-global client config remain client-owned",
            ".codex/hooks.json",
        )
    ]
    try:
        from . import hooks as hooks_module

        hook_findings = hooks_module.codex_hook_adapter_apply_findings(inventory, hooks_module.CodexHookAdapterRequest())
    except Exception as exc:
        findings.append(
            _attach_post_step_exception_finding(
                "codex-hooks",
                "project-local Codex native hook adapter setup",
                exc,
                ".codex/hooks.json",
            )
        )
        if after_scaffold_write:
            findings.append(
                _attach_post_scaffold_recovery_finding(
                    "attach-codex-hooks-recovery",
                    "project-local Codex native hook adapter setup",
                    ATTACH_CODEX_HOOKS_RECOVERY_COMMAND,
                    ".codex/hooks.json",
                    severity="error",
                )
            )
        return findings

    findings.extend(hook_findings)
    if after_scaffold_write and any(finding.severity == "error" for finding in hook_findings):
        findings.append(
            _attach_post_scaffold_recovery_finding(
                "attach-codex-hooks-recovery",
                "project-local Codex native hook adapter setup",
                ATTACH_CODEX_HOOKS_RECOVERY_COMMAND,
                ".codex/hooks.json",
                severity="error",
            )
        )
    return findings


def _attach_generated_projection_findings(inventory: Inventory, *, after_scaffold_write: bool = False) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "attach-generated-projection-boundary",
            f"attach-time generated projection boundary: {ARTIFACT_DIR_REL}",
            ARTIFACT_DIR_REL,
        )
    ]
    try:
        artifact_findings = build_projection_artifacts(inventory)
    except Exception as exc:
        findings.append(
            _attach_post_step_exception_finding(
                "generated-projection",
                "attach-time generated projection artifact build",
                exc,
                ARTIFACT_DIR_REL,
            )
        )
        if after_scaffold_write:
            findings.append(
                _attach_post_scaffold_recovery_finding(
                    "attach-generated-projection-recovery",
                    "generated projection setup",
                    PROJECTION_REBUILD_NEXT_SAFE_COMMAND,
                    ARTIFACT_DIR_REL,
                    severity="error",
                )
            )
        return findings
    try:
        index_findings = build_projection_index(inventory)
    except Exception as exc:
        findings.extend(artifact_findings)
        findings.append(
            _attach_post_step_exception_finding(
                "generated-projection",
                "attach-time SQLite projection index build",
                exc,
                INDEX_REL_PATH,
            )
        )
        if after_scaffold_write:
            findings.append(
                _attach_post_scaffold_recovery_finding(
                    "attach-generated-projection-recovery",
                    "generated projection setup",
                    PROJECTION_REBUILD_NEXT_SAFE_COMMAND,
                    INDEX_REL_PATH,
                    severity="error",
                )
            )
        return findings
    build_findings = artifact_findings + index_findings
    if any(finding.severity == "error" for finding in build_findings):
        findings.append(
            Finding(
                "error",
                "attach-generated-projection-refused",
                "attach-time generated projection setup was refused by the owned boundary preflight",
                ARTIFACT_DIR_REL,
            )
        )
        if after_scaffold_write:
            findings.append(
                _attach_post_scaffold_recovery_finding(
                    "attach-generated-projection-recovery",
                    "generated projection setup",
                    PROJECTION_REBUILD_NEXT_SAFE_COMMAND,
                    ARTIFACT_DIR_REL,
                    severity="error",
                )
            )
    elif any(finding.code in {"projection-index-fts5-unavailable", "projection-index-build-failed"} for finding in index_findings):
        findings.append(
            Finding(
                "warn",
                "attach-generated-projection-unavailable",
                f"SQLite FTS/BM25 index was unavailable; JSON projection artifacts were built and no current index is required: {INDEX_REL_PATH}",
                INDEX_REL_PATH,
            )
        )
        if after_scaffold_write and any(finding.code == "projection-index-build-failed" for finding in index_findings):
            findings.append(
                _attach_post_scaffold_recovery_finding(
                    "attach-generated-projection-recovery",
                    "SQLite projection index build",
                    PROJECTION_REBUILD_NEXT_SAFE_COMMAND,
                    INDEX_REL_PATH,
                    severity="warn",
                )
            )
    elif after_scaffold_write and any(finding.code == "projection-artifact-refresh-degraded" for finding in artifact_findings):
        findings.append(
            _attach_post_scaffold_recovery_finding(
                "attach-generated-projection-recovery",
                "projection artifact build",
                PROJECTION_REBUILD_NEXT_SAFE_COMMAND,
                ARTIFACT_DIR_REL,
                severity="warn",
            )
        )
    elif any(finding.code == "projection-index-build" for finding in index_findings):
        findings.append(
            Finding(
                "info",
                "attach-generated-projection-build",
                f"built schema v2 JSON projection artifacts and SQLite FTS/BM25 index: {INDEX_REL_PATH}",
                INDEX_REL_PATH,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "attach-generated-projection-skipped",
                "attach-time generated projection setup completed without a SQLite build finding",
                ARTIFACT_DIR_REL,
            )
        )
    findings.extend(build_findings)
    return findings


def _attach_generated_projection_preflight_errors(inventory: Inventory) -> list[Finding]:
    errors: list[Finding] = []
    root_resolved = inventory.root.resolve()
    current = inventory.root
    for part in ARTIFACT_DIR_REL.split("/"):
        current = current / part
        rel_path = current.relative_to(inventory.root).as_posix()
        if current.is_symlink():
            errors.append(
                Finding(
                    "error",
                    "attach-generated-projection-refused",
                    f"cannot create attach-time generated projection because a symlink segment exists: {rel_path}",
                    rel_path,
                )
            )
            return errors
        if current.exists() and not current.is_dir():
            errors.append(
                Finding(
                    "error",
                    "attach-generated-projection-refused",
                    f"cannot create attach-time generated projection because a non-directory segment exists: {rel_path}",
                    rel_path,
                )
            )
            return errors

    projection_dir = inventory.root / ARTIFACT_DIR_REL
    if projection_dir.exists():
        try:
            projection_dir.resolve().relative_to(root_resolved)
        except ValueError:
            errors.append(
                Finding(
                    "error",
                    "attach-generated-projection-refused",
                    f"attach-time generated projection boundary escapes target root: {ARTIFACT_DIR_REL}",
                    ARTIFACT_DIR_REL,
                )
            )
    return errors


def _attach_already_attached_dry_run_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "attach-already-attached",
            "already-attached live operating root: workflow manifest and project-state authority are readable; first-run templates and generated projection setup are skipped",
            ATTACH_STATE_REL_PATH,
        ),
        Finding("info", "attach-existing", f"existing workflow manifest authority: {_selected_manifest_rel(inventory)}", _selected_manifest_rel(inventory)),
        Finding("info", "attach-existing", f"existing project-state authority: {ATTACH_STATE_REL_PATH}", ATTACH_STATE_REL_PATH),
        Finding(
            "info",
            "attach-codex-hooks-autoadoption",
            "default init/attach apply would create or refresh project-local Codex native hooks; Codex Trust and user-global client config remain client-owned",
            ".codex/hooks.json",
        ),
    ]
    missing_dirs = [rel_path for rel_path in WORKFLOW_ATTACH_DIRECTORIES if not (inventory.root / rel_path).exists()]
    if missing_dirs:
        for rel_path in missing_dirs:
            findings.append(Finding("warn", "attach-proposal", f"would create missing advertised scaffold directory: {rel_path}", rel_path))
    else:
        findings.append(Finding("info", "attach-proposal", "all advertised scaffold directories are already present"))
    findings.append(Finding("info", "attach-proposal", "root is already attached; attach --apply may create only missing advertised scaffold directories"))
    return findings


def _attach_already_attached_apply_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "attach-already-attached",
            "already-attached live operating root; attach --apply preserved authority files and ensured advertised scaffold directories",
            ATTACH_STATE_REL_PATH,
        ),
        Finding("info", "attach-existing", f"preserved workflow manifest authority: {_selected_manifest_rel(inventory)}", _selected_manifest_rel(inventory)),
        Finding("info", "attach-existing", f"preserved project-state authority: {ATTACH_STATE_REL_PATH}", ATTACH_STATE_REL_PATH),
    ]

    created_paths: list[str] = []
    existing_paths: list[str] = []
    for rel_path in WORKFLOW_ATTACH_DIRECTORIES:
        path = inventory.root / rel_path
        if path.exists():
            existing_paths.append(rel_path)
            continue
        path.mkdir(parents=True, exist_ok=False)
        created_paths.append(rel_path)

    for rel_path in created_paths:
        findings.append(Finding("info", "attach-created", f"created missing advertised scaffold directory: {rel_path}", rel_path))
    for rel_path in existing_paths:
        findings.append(Finding("info", "attach-scaffold-existing", f"preserved advertised scaffold directory without changes: {rel_path}", rel_path))
    if not created_paths:
        findings.append(Finding("info", "attach-scaffold-unchanged", "all advertised scaffold directories were already present"))
    findings.append(
        Finding(
            "info",
            "attach-apply-boundary",
            "already-attached apply skips create-only authority templates and generated projection writes, but may create missing advertised scaffold directories and refresh project-local Codex native hooks; Codex Trust and user-global client config remain client-owned",
        )
    )
    refreshed_inventory = load_inventory(inventory.root)
    hook_findings = _attach_codex_hooks_default_apply_findings(refreshed_inventory, after_scaffold_write=False)
    findings.extend(hook_findings)
    if any(finding.severity == "error" for finding in hook_findings):
        findings.extend(connect_readiness_findings(load_inventory(inventory.root), "attach-connect-readiness"))
        return findings
    findings.extend(connect_readiness_findings(load_inventory(inventory.root), "attach-connect-readiness"))
    return findings


def _attach_post_step_exception_finding(step_code: str, step_label: str, exc: Exception, source: str) -> Finding:
    return Finding(
        "error",
        f"attach-{step_code}-failed-after-scaffold",
        (
            f"partial attach apply: scaffold writes may already be durable, but {step_label} failed after preflight "
            f"with {type(exc).__name__}: {exc}"
        ),
        source,
    )


def _attach_post_scaffold_recovery_finding(
    code: str,
    step_label: str,
    recovery_command: str,
    source: str,
    *,
    severity: str,
) -> Finding:
    return Finding(
        severity,
        code,
        (
            f"partial attach recovery: repo-visible scaffold and authority files remain authoritative even though {step_label} "
            f"did not complete cleanly; verify current posture with {ATTACH_RECOVERY_CHECK_COMMAND}; then rerun {recovery_command} "
            "after fixing the reported cause"
        ),
        source,
    )


def _is_attach_already_attached_live_root(inventory: Inventory, project_name: str | None) -> bool:
    if not _has_default_attach_authority(inventory):
        return False
    if _attach_apply_preflight_errors(inventory, project_name, allow_existing_template_content=True):
        return False
    if _attach_generated_projection_preflight_errors(inventory):
        return False
    return True


def _has_default_attach_authority(inventory: Inventory) -> bool:
    if inventory.root_kind != "live_operating_root":
        return False

    manifest = inventory.manifest_surface
    if manifest is None or not manifest.exists or manifest.read_error or inventory.manifest_errors:
        return False
    if inventory.manifest.get("workflow") != "workflow-core":
        return False

    memory = inventory.manifest.get("memory", {}) if isinstance(inventory.manifest, dict) else {}
    state_file = str(memory.get("state_file", ATTACH_STATE_REL_PATH)).replace("\\", "/")
    plan_file = str(memory.get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
    if state_file != ATTACH_STATE_REL_PATH or plan_file != "project/implementation-plan.md":
        return False

    state = inventory.surface_by_rel.get(ATTACH_STATE_REL_PATH)
    if state is None or not state.exists or state.read_error or state.frontmatter.errors:
        return False
    if state.frontmatter.has_frontmatter:
        data = state.frontmatter.data
        required = ("project", "workflow", "operating_mode", "plan_status")
        return all(data.get(key) for key in required) and data.get("workflow") == "workflow-core"
    return _has_read_only_state_assignments(state)


def _attach_existing_authority_preflight_errors(inventory: Inventory) -> list[Finding]:
    errors: list[Finding] = []
    manifest = inventory.manifest_surface
    if manifest and manifest.exists:
        if manifest.read_error:
            errors.append(Finding("error", "attach-refused", f"workflow manifest is unreadable: {manifest.read_error}", manifest.rel_path))
        for error in inventory.manifest_errors:
            errors.append(Finding("error", "attach-refused", f"workflow manifest is malformed: {error}", manifest.rel_path))
        if inventory.manifest and inventory.manifest.get("workflow") != "workflow-core":
            errors.append(Finding("error", "attach-refused", "attach requires manifest workflow = workflow-core when a workflow manifest already exists", manifest.rel_path))
        memory = inventory.manifest.get("memory", {}) if inventory.manifest else {}
        state_file = str(memory.get("state_file", ATTACH_STATE_REL_PATH)).replace("\\", "/")
        plan_file = str(memory.get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
        if state_file != ATTACH_STATE_REL_PATH:
            errors.append(Finding("error", "attach-refused", f"non-default state_file is preserved and attach is refused: {state_file}", manifest.rel_path))
        if plan_file != "project/implementation-plan.md":
            errors.append(Finding("error", "attach-refused", f"non-default plan_file is preserved and attach is refused: {plan_file}", manifest.rel_path))

    state = inventory.state
    if state and state.exists:
        if state.read_error:
            errors.append(Finding("error", "attach-refused", f"project state is unreadable: {state.read_error}", state.rel_path))
        for error in state.frontmatter.errors:
            errors.append(Finding("error", "attach-refused", f"project state frontmatter is malformed: {error}", state.rel_path))
    return errors


def _attach_detach_marker_preflight_errors(inventory: Inventory) -> list[Finding]:
    marker = inventory.surface_by_rel.get(DETACH_MARKER_REL_PATH)
    if marker and marker.exists:
        return [
            Finding(
                "error",
                "attach-refused",
                f"target has a detach disabled marker; remove {DETACH_MARKER_REL_PATH} manually before init/attach mutation",
                DETACH_MARKER_REL_PATH,
            )
        ]
    return []


def _attach_apply_preflight_errors(inventory: Inventory, project_name: str | None, *, allow_existing_template_content: bool = False) -> list[Finding]:
    errors: list[Finding] = []
    errors.extend(_attach_existing_authority_preflight_errors(inventory))
    errors.extend(_attach_detach_marker_preflight_errors(inventory))
    seen_directory_segments: set[str] = set()
    for rel_path in WORKFLOW_ATTACH_DIRECTORIES:
        for candidate in _root_relative_path_chain(inventory.root, rel_path):
            candidate_rel = candidate.relative_to(inventory.root).as_posix()
            if candidate_rel in seen_directory_segments:
                continue
            seen_directory_segments.add(candidate_rel)
            if candidate.is_symlink():
                errors.append(
                    Finding(
                        "error",
                        "attach-target-conflict",
                        f"cannot create scaffold directory because a symlink segment exists: {candidate_rel}",
                        candidate_rel,
                    )
                )
            elif candidate.exists() and not candidate.is_dir():
                errors.append(
                    Finding(
                        "error",
                        "attach-target-conflict",
                        f"cannot create scaffold directory because a non-directory already exists: {candidate_rel}",
                        candidate_rel,
                    )
                )

    templates = _attach_apply_templates(project_name, inventory)
    for rel_path, content in templates.items():
        chain = _root_relative_path_chain(inventory.root, rel_path)
        for candidate in chain[:-1]:
            candidate_rel = candidate.relative_to(inventory.root).as_posix()
            if candidate_rel in seen_directory_segments:
                continue
            seen_directory_segments.add(candidate_rel)
            if candidate.is_symlink():
                errors.append(
                    Finding(
                        "error",
                        "attach-target-conflict",
                        f"cannot create template file because a symlink segment exists: {candidate_rel}",
                        candidate_rel,
                    )
                )
            elif candidate.exists() and not candidate.is_dir():
                errors.append(
                    Finding(
                        "error",
                        "attach-target-conflict",
                        f"cannot create template file because a parent path is not a directory: {candidate_rel}",
                        candidate_rel,
                    )
                )
        path = inventory.root / rel_path
        if path.is_symlink():
            errors.append(
                Finding(
                    "error",
                    "attach-target-conflict",
                    f"cannot create template file because a symlink exists: {rel_path}",
                    rel_path,
                )
            )
            continue
        if path.exists() and not path.is_file():
            errors.append(
                Finding(
                    "error",
                    "attach-target-conflict",
                    f"cannot create template file because a non-file already exists: {rel_path}",
                    rel_path,
                )
            )
            continue
        if path.exists() and allow_existing_template_content:
            continue
        if path.exists():
            try:
                existing_content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(
                    Finding(
                        "error",
                        "attach-target-conflict",
                        f"cannot compare existing template file before attach: {rel_path}: {exc}",
                        rel_path,
                    )
                )
                continue
            if existing_content == content:
                continue
            errors.append(
                Finding(
                    "error",
                    "attach-target-conflict",
                    f"existing file differs from the create-only attach template; refusing to overwrite: {rel_path}",
                    rel_path,
                )
            )
    return errors


def _attach_apply_templates(project_name: str | None, inventory: Inventory) -> dict[str, str]:
    project = project_name
    state = inventory.state
    if project is None and state and state.exists:
        existing_project = state.frontmatter.data.get("project")
        if isinstance(existing_project, str) and existing_project.strip():
            project = existing_project.strip()
    templates = {ATTACH_MANIFEST_REL_PATH: _workflow_manifest_template()}
    if project is not None:
        templates[ATTACH_STATE_REL_PATH] = _project_state_template(project)
    return templates


def _workflow_manifest_template() -> str:
    return (
        'workflow = "workflow-core"\n'
        "version = 1\n"
        "\n"
        "[memory]\n"
        'state_file = "project/project-state.md"\n'
        'plan_file = "project/implementation-plan.md"\n'
        'archive_dir = "project/archive/plans"\n'
        "\n"
        "[policy]\n"
        'closeout_commit = "manual"\n'
    )


def _project_state_template(project_name: str) -> str:
    quoted_project = _frontmatter_quote(project_name)
    heading = project_name.replace("\r", " ").replace("\n", " ").strip()
    return (
        "---\n"
        f"project: {quoted_project}\n"
        'workflow: "workflow-core"\n'
        'operating_mode: "ad_hoc"\n'
        'plan_status: "none"\n'
        'active_plan: ""\n'
        'last_archived_plan: ""\n'
        "---\n"
        f"# {heading} Project State\n"
        "\n"
        "## Current Focus\n"
        "\n"
        "No active implementation plan.\n"
        "\n"
        "## Notes\n"
        "\n"
        "Attached by MyLittleHarness. Add durable project memory here as work proceeds.\n"
    )


def _normalize_project_name(project_name: str | None) -> str | None:
    if project_name is None:
        return None
    normalized = project_name.strip()
    if not normalized or "\r" in normalized or "\n" in normalized:
        return None
    return normalized


def _frontmatter_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def repair_dry_run_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "dry-run", "repair proposal only; no files or directories were written"),
        Finding(
            "info",
            "mutation-guard",
            "use repair --apply only for deterministic scaffold, create-only AGENTS.md, create-only docmap, create-only stable spec restoration, snapshot-protected docmap route repairs, snapshot-protected lifecycle markdown frontmatter repair, snapshot-protected lifecycle source-provenance repair, snapshot-protected spec posture frontmatter repair, or snapshot-protected state frontmatter repair",
        ),
    ]
    validation = validation_findings(inventory)
    actionable = [
        finding
        for finding in validation
        if finding.severity in {"error", "warn"} and not _is_route_metadata_advisory(finding)
    ]
    findings.extend(_state_frontmatter_plan_findings(inventory, validation))
    findings.extend(_lifecycle_markdown_frontmatter_plan_findings(inventory, validation))
    findings.extend(_lifecycle_source_provenance_plan_findings(inventory))
    findings.extend(_spec_posture_frontmatter_plan_findings(inventory, validation))
    findings.extend(_agents_contract_create_plan_findings(inventory, validation))
    findings.extend(_docmap_snapshot_plan_findings(inventory, validation))
    findings.extend(_docmap_create_plan_findings(inventory, validation))
    findings.extend(_stable_spec_create_plan_findings(inventory, validation))

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "info",
                "repair-scope",
                "target is a product-source compatibility fixture; repair proposals are constrained to report-only review",
                inventory.state.rel_path if inventory.state else None,
            )
        )

    if not _is_product_source_inventory(inventory) and _has_repair_apply_authority(inventory):
        missing_dirs = _repair_missing_scaffold_directories(inventory)
        for rel_path in missing_dirs:
            findings.append(Finding("warn", "repair-proposal", f"would create missing scaffold directory: {rel_path}", rel_path))
        if not missing_dirs:
            findings.append(Finding("info", "repair-proposal", "no missing scaffold directories were found"))
    elif not _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "info",
                "repair-scope",
                "repair apply would require an existing readable workflow-core manifest and project state",
            )
        )

    if not actionable:
        if not any(finding.code == "repair-proposal" for finding in findings):
            findings.append(Finding("info", "repair-proposal", "no validation errors or warnings require a repair proposal"))
        return findings

    for finding in actionable:
        findings.append(_repair_proposal_for(finding))
    return findings


def repair_apply_findings(inventory: Inventory) -> list[Finding]:
    validation = validation_findings(inventory)
    non_default_state_refusal = _non_default_state_path_apply_refusal(inventory)
    if non_default_state_refusal:
        return [non_default_state_refusal]
    if _state_prose_fallback_diagnostic(validation) is not None:
        errors = _state_frontmatter_apply_preflight_errors(inventory, validation)
        if errors:
            return errors
        findings, changed = _state_frontmatter_apply_findings(inventory, validation)
        if any(finding.severity == "error" for finding in findings):
            return findings
        findings.extend(_post_repair_validation_findings(inventory))
        if changed:
            findings.append(
                Finding(
                    "info",
                    "state-frontmatter-rerun",
                    "state frontmatter repair completed first; review validation and rerun repair --apply for any remaining scaffold or docmap repair classes",
                    STATE_FRONTMATTER_TARGET_REL,
                )
            )
        return findings

    errors = _repair_apply_authority_errors(inventory)
    if not errors:
        errors.extend(_repair_apply_lifecycle_preflight_errors(validation))
    if not errors:
        errors.extend(_lifecycle_markdown_frontmatter_apply_preflight_errors(inventory, validation))
    if not errors:
        errors.extend(_lifecycle_source_provenance_apply_preflight_errors(inventory))
    if not errors:
        errors.extend(_spec_posture_frontmatter_apply_preflight_errors(inventory, validation))
    if not errors:
        errors.extend(_repair_apply_preflight_errors(inventory))
    if not errors:
        errors.extend(_agents_contract_create_apply_preflight_errors(inventory, validation))
    if not errors:
        errors.extend(_docmap_create_apply_preflight_errors(inventory, validation))
    if not errors:
        errors.extend(_docmap_snapshot_apply_preflight_errors(inventory, validation))
    if not errors:
        errors.extend(_stable_spec_create_apply_preflight_errors(inventory, validation))
    if errors:
        return errors

    lifecycle_frontmatter_findings, lifecycle_frontmatter_changed = _lifecycle_markdown_frontmatter_apply_findings(inventory, validation)
    if any(finding.severity == "error" for finding in lifecycle_frontmatter_findings):
        return lifecycle_frontmatter_findings
    if lifecycle_frontmatter_changed:
        lifecycle_frontmatter_findings.extend(_post_repair_validation_findings(inventory))
        lifecycle_frontmatter_findings.append(
            Finding(
                "info",
                "lifecycle-frontmatter-rerun",
                "lifecycle markdown frontmatter repair completed first; review validation and rerun repair --apply for any remaining scaffold, docmap, or stable spec repair classes",
            )
        )
        return lifecycle_frontmatter_findings

    lifecycle_source_findings, lifecycle_source_changed = _lifecycle_source_provenance_apply_findings(inventory)
    if any(finding.severity == "error" for finding in lifecycle_source_findings):
        return lifecycle_source_findings
    if lifecycle_source_changed:
        lifecycle_source_findings.extend(_post_repair_validation_findings(inventory))
        lifecycle_source_findings.append(
            Finding(
                "info",
                "lifecycle-source-provenance-rerun",
                "lifecycle source-provenance repair completed first; review validation and rerun repair --apply for any remaining scaffold, docmap, or stable spec repair classes",
            )
        )
        return lifecycle_source_findings

    spec_posture_findings, spec_posture_changed = _spec_posture_frontmatter_apply_findings(inventory, validation)
    if any(finding.severity == "error" for finding in spec_posture_findings):
        return spec_posture_findings
    if spec_posture_changed:
        spec_posture_findings.extend(_post_repair_validation_findings(inventory))
        spec_posture_findings.append(
            Finding(
                "info",
                "spec-posture-frontmatter-rerun",
                "spec posture frontmatter repair completed first; review validation and rerun repair --apply for any remaining scaffold, docmap, or stable spec repair classes",
            )
        )
        return spec_posture_findings

    findings: list[Finding] = [Finding("info", "repair-apply", "bounded repair apply started")]
    created_paths: list[str] = []
    existing_paths: list[str] = []
    docmap_route_changed = False
    docmap_created = False
    stable_specs_created = False
    agents_contract_created = False

    agents_contract_findings, agents_contract_created = _agents_contract_create_apply_findings(inventory, validation)
    findings.extend(agents_contract_findings)
    if any(finding.severity == "error" for finding in agents_contract_findings):
        return findings
    docmap_findings, docmap_route_changed = _docmap_snapshot_apply_findings(inventory, validation)
    findings.extend(docmap_findings)
    if any(finding.severity == "error" for finding in docmap_findings):
        return findings
    docmap_create_findings, docmap_created = _docmap_create_apply_findings(inventory, validation)
    findings.extend(docmap_create_findings)
    if any(finding.severity == "error" for finding in docmap_create_findings):
        return findings
    stable_spec_findings, stable_specs_created = _stable_spec_create_apply_findings(inventory, validation)
    findings.extend(stable_spec_findings)
    if any(finding.severity == "error" for finding in stable_spec_findings):
        return findings

    for rel_path in WORKFLOW_ATTACH_DIRECTORIES:
        path = inventory.root / rel_path
        if path.exists():
            existing_paths.append(rel_path)
            continue
        path.mkdir(parents=True, exist_ok=False)
        created_paths.append(rel_path)

    for rel_path in created_paths:
        findings.append(Finding("info", "repair-created", f"created create-only repair path: {rel_path}", rel_path))
    for rel_path in existing_paths:
        findings.append(Finding("info", "repair-existing", f"preserved existing repair path without changes: {rel_path}", rel_path))
    if not created_paths and not docmap_route_changed and not docmap_created and not stable_specs_created and not agents_contract_created:
        findings.append(Finding("info", "repair-unchanged", "no file or directory changes were needed"))
    findings.append(
        Finding(
            "info",
            "repair-apply-boundary",
            "repair --apply wrote only absent eager scaffold directories, selected create-only AGENTS.md creation, selected create-only docmap creation, selected create-only stable spec restoration, selected snapshot-protected lifecycle markdown frontmatter repair, selected snapshot-protected spec posture frontmatter repair, and selected snapshot-protected docmap route repair classes",
        )
    )

    findings.extend(_post_repair_validation_findings(inventory))
    return findings


def _post_repair_validation_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    refreshed = load_inventory(inventory.root)
    validation = validation_findings(refreshed)
    audit = audit_link_findings(refreshed)
    validation_errors = [finding for finding in validation if finding.severity == "error"]
    validation_warnings = [finding for finding in validation if finding.severity == "warn"]
    audit_warnings = [finding for finding in audit if finding.severity == "warn"]
    findings.append(
        Finding(
            "info",
            "repair-validation",
            f"post-repair validation findings: {len(validation_errors)} errors, {len(validation_warnings)} warnings",
        )
    )
    for finding in validation_errors:
        findings.append(
            Finding(
                "error",
                "repair-validation-error",
                f"post-repair validation still reports {finding.code}: {finding.message}",
                finding.source,
                finding.line,
            )
        )
    for finding in validation_warnings:
        findings.append(
            Finding(
                "warn",
                "repair-validation-warning",
                f"post-repair validation still reports {finding.code}: {finding.message}",
                finding.source,
                finding.line,
            )
        )
    findings.append(
        Finding(
            "info",
            "repair-audit-links",
            f"post-repair audit-link findings: {len(audit_warnings)} warnings",
        )
    )
    for finding in audit_warnings:
        findings.append(
            Finding(
                "warn",
                "repair-audit-link-warning",
                f"post-repair audit-links still reports {finding.code}: {finding.message}",
                finding.source,
                finding.line,
            )
        )
    return findings


def snapshot_inspect_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "snapshot-inspect-boundary",
            (
                f"inspecting repair snapshots under {SNAPSHOT_REPAIR_ROOT_REL}/; terminal-only read-only report; "
                "no rollback, cleanup, repair, archive, commit, or lifecycle mutation is implied"
            ),
        ),
        Finding(
            "info",
            "snapshot-authority",
            "repair snapshots are safety evidence only and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
        ),
    ]
    findings.extend(_snapshot_inspect_root_posture_findings(inventory))

    boundary_conflict = _snapshot_inspect_boundary_conflict(inventory.root)
    if boundary_conflict:
        findings.append(boundary_conflict)
        return findings

    snapshot_root = inventory.root / SNAPSHOT_REPAIR_ROOT_REL
    if not snapshot_root.exists():
        findings.append(
            Finding(
                "info",
                "snapshot-inspect-empty",
                f"no repair snapshot directory found: {SNAPSHOT_REPAIR_ROOT_REL}/",
                SNAPSHOT_REPAIR_ROOT_REL,
            )
        )
        return findings

    snapshot_dirs: list[Path] = []
    for child in sorted(snapshot_root.iterdir(), key=lambda item: item.name):
        rel_path = child.relative_to(inventory.root).as_posix()
        if child.is_symlink():
            findings.append(Finding("warn", "snapshot-inspect-boundary-conflict", f"snapshot entry is a symlink: {rel_path}", rel_path))
            continue
        if not child.is_dir():
            findings.append(Finding("warn", "snapshot-inspect-malformed", f"snapshot entry is not a directory: {rel_path}", rel_path))
            continue
        snapshot_dirs.append(child)

    if not snapshot_dirs:
        findings.append(
            Finding(
                "info",
                "snapshot-inspect-empty",
                f"repair snapshot directory contains no snapshot directories: {SNAPSHOT_REPAIR_ROOT_REL}/",
                SNAPSHOT_REPAIR_ROOT_REL,
            )
        )
        return findings

    for snapshot_dir in snapshot_dirs:
        findings.extend(_inspect_repair_snapshot(inventory, snapshot_dir))
    return findings


def _repair_apply_authority_errors(inventory: Inventory) -> list[Finding]:
    if _is_product_source_inventory(inventory):
        return [
            Finding(
                "error",
                "repair-refused",
                "target is a product-source compatibility fixture; repair --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        ]
    if _is_fallback_or_archive_inventory(inventory):
        return [
            Finding(
                "error",
                "repair-refused",
                "target is fallback/archive evidence; repair --apply is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        ]
    state = inventory.state
    if state and state.frontmatter.has_frontmatter and state.frontmatter.errors:
        return [
            Finding(
                "error",
                "state-frontmatter-refused",
                "project-state.md frontmatter is malformed; repair --apply refuses lifecycle mutation until state frontmatter is fixed manually",
                state.rel_path,
            )
        ]
    if not _has_repair_apply_authority(inventory):
        return [
            Finding(
                "error",
                "repair-refused",
                "repair --apply requires an existing readable workflow-core manifest and project state",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        ]
    return []


def _non_default_state_path_apply_refusal(inventory: Inventory) -> Finding | None:
    if not inventory.manifest:
        return None
    manifest_state = str(inventory.manifest.get("memory", {}).get("state_file", STATE_FRONTMATTER_TARGET_REL)).replace("\\", "/")
    if manifest_state == STATE_FRONTMATTER_TARGET_REL:
        return None
    return Finding(
        "error",
        "state-frontmatter-refused",
        f"repair --apply is limited to {STATE_FRONTMATTER_TARGET_REL} state authority; manifest state_file is {manifest_state}",
        inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
    )


def _has_repair_apply_authority(inventory: Inventory) -> bool:
    manifest = inventory.manifest_surface
    state = inventory.state
    if not manifest or not manifest.exists or inventory.manifest_errors:
        return False
    if not state or not state.exists or not state.frontmatter.has_frontmatter:
        return False
    if inventory.manifest.get("workflow") != "workflow-core":
        return False
    if state.frontmatter.data.get("workflow") != "workflow-core":
        return False
    return True


def _repair_apply_lifecycle_preflight_errors(validation: list[Finding]) -> list[Finding]:
    refused_codes = {
        "state-frontmatter",
        "state-frontmatter-field",
        "active-plan-field",
        "active-plan-missing",
        "active-plan-manifest",
        "frontmatter-parse",
    }
    for finding in validation:
        if finding.code in refused_codes:
            return [
                Finding(
                    "error",
                    "state-frontmatter-refused",
                    f"repair --apply refuses lifecycle-sensitive state diagnostic {finding.code}: {finding.message}",
                    finding.source,
                    finding.line,
                )
            ]
    return []


def _repair_apply_preflight_errors(inventory: Inventory) -> list[Finding]:
    errors: list[Finding] = []
    seen: set[str] = set()
    for rel_path in WORKFLOW_ATTACH_DIRECTORIES:
        for candidate in _root_relative_path_chain(inventory.root, rel_path):
            candidate_rel = candidate.relative_to(inventory.root).as_posix()
            if candidate_rel in seen:
                continue
            seen.add(candidate_rel)
            if not candidate.exists():
                continue
            if candidate.is_symlink() or not candidate.is_dir():
                errors.append(
                    Finding(
                        "error",
                        "repair-target-conflict",
                        f"cannot create scaffold directory because a non-directory or symlink exists: {candidate_rel}",
                        candidate_rel,
                    )
                )
    return errors


def _root_relative_path_chain(root: Path, rel_path: str) -> list[Path]:
    current = root
    paths: list[Path] = []
    for part in Path(rel_path).parts:
        current = current / part
        paths.append(current)
    return paths


def _repair_missing_scaffold_directories(inventory: Inventory) -> list[str]:
    return [rel_path for rel_path in WORKFLOW_ATTACH_DIRECTORIES if not (inventory.root / rel_path).exists()]


def _repair_proposal_for(finding: Finding) -> Finding:
    action_by_code = {
        "missing-required-surface": "restore or create the required repo-native surface after confirming root authority",
        "manifest-parse": "fix manifest TOML syntax before relying on manifest-resolved memory paths",
        "manifest-workflow": "review manifest workflow value and align it with workflow-core compatibility if intended",
        "manifest-state-file": "review non-default state_file before repair; do not move memory implicitly",
        "manifest-plan-file": "review non-default plan_file before repair; do not move active plans implicitly",
        "state-frontmatter": "restore project-state.md frontmatter with canonical project, workflow, operating_mode, and plan_status fields",
        "state-frontmatter-field": "add the missing project-state.md frontmatter field after confirming current operating state",
        "active-plan-field": "set active_plan to the manifest plan path when plan_status remains active",
        "active-plan-missing": "restore the active implementation plan or mark plan_status inactive from the operating root",
        "active-plan-manifest": "align active_plan with manifest memory.plan_file after confirming the active plan location",
        "stale-plan-file": "archive, remove, or reactivate the stale plan only through the operating root closeout path",
        "roadmap-terminal-stale-active-plan-link": "run a bounded roadmap, plan, or writeback sync to retarget the terminal roadmap relationship to archived_plan or clear it",
        "roadmap-done-docs-archive-evidence-gap": "run check --focus archive-context, then restore or retarget archived evidence before finalizing docs_decision",
        "missing-stable-spec": "restore the expected workflow spec fixture from product docs or the operating source of truth",
        "frontmatter-parse": "fix malformed markdown frontmatter without changing body authority",
        "spec-posture-missing": "preview bounded spec posture frontmatter repair or amend the spec manually; repair adds only missing spec_status and implementation_posture metadata for plan-facing MLH-owned specs/docs",
        "research-frontmatter": "add lightweight routing frontmatter only if the research artifact remains durable",
        "lifecycle-frontmatter": "add canonical route frontmatter or rewrite the note through its owning MLH lifecycle command",
        "docmap-routing": "update docmap routes after confirming the target files are canonical entrypoints",
        "mirror-drift": "resync mirrors only if package-source mirror parity is still intended",
    }
    action = action_by_code.get(finding.code, "review this diagnostic manually before any repair mutation")
    return Finding(
        "warn",
        "repair-proposal",
        f"{action}; source diagnostic: {finding.code} - {finding.message}",
        finding.source,
        finding.line,
    )


def _is_route_metadata_advisory(finding: Finding) -> bool:
    return finding.code.startswith("route-metadata-")


def _state_frontmatter_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "state-frontmatter-scope",
            f"selected repair class: {STATE_FRONTMATTER_REPAIR_CLASS}; target file: {STATE_FRONTMATTER_TARGET_REL}",
            STATE_FRONTMATTER_TARGET_REL,
        )
    ]

    diagnostic = _state_prose_fallback_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "state-frontmatter-skipped",
                f"no state-prose-fallback diagnostic was found; {STATE_FRONTMATTER_TARGET_REL} frontmatter repair is not needed",
                STATE_FRONTMATTER_TARGET_REL,
            )
        )
        return findings

    refusal = _state_frontmatter_refusal_finding(inventory, validation, severity="warn")
    if refusal:
        findings.append(refusal)
        return findings

    state = inventory.state
    assert state is not None
    target_conflict = _snapshot_target_conflict(inventory.root, STATE_FRONTMATTER_TARGET_REL)
    if target_conflict:
        findings.append(_state_frontmatter_refusal_from(target_conflict, "warn"))
        return findings

    fields = _state_frontmatter_fields(inventory)
    frontmatter_text = _state_frontmatter_text(fields)
    snapshot_dir = _state_frontmatter_snapshot_dir(state.path, frontmatter_text, SNAPSHOT_DRY_RUN_TIMESTAMP)
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        findings.append(_state_frontmatter_refusal_from(boundary_conflict, "warn"))
        return findings

    planned_keys = list(fields)
    metadata_fields = ", ".join([*SNAPSHOT_METADATA_FIELDS, "planned_frontmatter_keys"])
    findings.extend(
        [
            Finding(
                "warn",
                "state-frontmatter-plan",
                f"would prepend deterministic project-state frontmatter because validation reports {diagnostic.code}: {diagnostic.message}",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-keys",
                f"planned frontmatter keys: {', '.join(planned_keys)}",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-snapshot-path",
                f"planned snapshot directory: {snapshot_dir}/; metadata: {snapshot_dir}/snapshot.json; copied file: {snapshot_dir}/{STATE_FRONTMATTER_COPY_REL}",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-metadata",
                f"metadata fields: {metadata_fields}",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-rollback",
                f"manual rollback only: copy {snapshot_dir}/{STATE_FRONTMATTER_COPY_REL} back to {STATE_FRONTMATTER_TARGET_REL}; no rollback command, cleanup, archive, commit, or lifecycle mutation is implied",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-validation",
                "validation method after apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-authority",
                "state frontmatter repair cannot approve closeout, archive, commit, lifecycle decisions, or future repairs",
                STATE_FRONTMATTER_TARGET_REL,
            ),
        ]
    )
    return findings


def _lifecycle_markdown_frontmatter_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "lifecycle-frontmatter-plan-scope",
            f"selected repair class: {LIFECYCLE_MARKDOWN_FRONTMATTER_REPAIR_CLASS}; target route files: lifecycle markdown requiring frontmatter",
        )
    ]

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "lifecycle-frontmatter-plan-refused",
                "target is a product-source compatibility fixture; lifecycle frontmatter repair planning is report-only and snapshot creation is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        )
        return findings
    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "lifecycle-frontmatter-plan-refused",
                "target is fallback/archive or generated-output evidence; lifecycle frontmatter repair planning is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "warn",
                "lifecycle-frontmatter-plan-refused",
                f"target root kind is {inventory.root_kind}; lifecycle frontmatter repair requires an explicit live operating root",
            )
        )
        return findings
    if not _has_repair_apply_authority(inventory):
        findings.append(
            Finding(
                "warn",
                "lifecycle-frontmatter-plan-refused",
                "snapshot-protected lifecycle frontmatter repair would require an existing readable workflow-core manifest and strict project-state frontmatter authority",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        )
        return findings

    candidates = _lifecycle_markdown_frontmatter_candidate_rows(inventory, validation)
    if not candidates:
        findings.append(
            Finding(
                "info",
                "lifecycle-frontmatter-plan-skipped",
                "no lifecycle markdown frontmatter diagnostics require a snapshot plan",
            )
        )
        return findings

    for surface, _diagnostics, _plan in candidates:
        target_conflict = _snapshot_target_conflict(inventory.root, surface.rel_path)
        if target_conflict:
            findings.append(_lifecycle_frontmatter_refusal_from(target_conflict, "warn"))
            return findings
        if surface.read_error:
            findings.append(
                Finding(
                    "warn",
                    "lifecycle-frontmatter-plan-refused",
                    f"target file could not be read as clean UTF-8 before lifecycle frontmatter repair: {surface.read_error}",
                    surface.rel_path,
                )
            )
            return findings
        if surface.frontmatter.errors:
            findings.append(
                Finding(
                    "warn",
                    "lifecycle-frontmatter-plan-refused",
                    "target has malformed frontmatter; repair refuses to guess metadata boundaries",
                    surface.rel_path,
                )
            )
            return findings

    plans = [plan for _surface, _diagnostics, plan in candidates]
    snapshot_dir = _lifecycle_markdown_frontmatter_snapshot_dir(plans, SNAPSHOT_DRY_RUN_TIMESTAMP)
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        findings.append(_lifecycle_frontmatter_refusal_from(boundary_conflict, "warn"))
        return findings

    diagnostics = [diagnostic for _surface, diagnostics, _plan in candidates for diagnostic in diagnostics]
    diagnostic_codes = ", ".join(sorted({finding.code for finding in diagnostics}))
    target_paths = [plan.rel_path for plan in plans]
    metadata_fields = ", ".join([*SNAPSHOT_METADATA_FIELDS, "planned_frontmatter_keys_by_path"])
    findings.extend(
        [
            Finding(
                "warn",
                "lifecycle-frontmatter-plan",
                (
                    f"would prepend canonical route frontmatter to {len(plans)} lifecycle markdown artifact(s); "
                    f"source diagnostics: {diagnostic_codes}"
                ),
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "lifecycle-frontmatter-targets",
                f"planned target files: {_lifecycle_frontmatter_path_summary(target_paths)}",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "lifecycle-frontmatter-snapshot-path",
                f"planned snapshot directory: {snapshot_dir}/; metadata: {snapshot_dir}/snapshot.json; copied files under {snapshot_dir}/files/",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "lifecycle-frontmatter-metadata",
                f"metadata fields: {metadata_fields}",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "lifecycle-frontmatter-rollback",
                f"manual rollback only: copy files from {snapshot_dir}/files/ back to matching repo paths; no rollback command, cleanup, archive, commit, or lifecycle mutation is implied",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "lifecycle-frontmatter-validation",
                "validation method after a future apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "lifecycle-frontmatter-authority",
                "repair-added frontmatter is routing metadata only; it cannot approve closeout, archive, commit, lifecycle decisions, truth selection, or future repairs",
                target_paths[0] if target_paths else None,
            ),
        ]
    )
    for plan in plans:
        findings.append(
            Finding(
                "info",
                "lifecycle-frontmatter-keys",
                f"planned frontmatter keys for {plan.rel_path}: {', '.join(plan.fields)}",
                plan.rel_path,
            )
        )
    findings.extend(_lifecycle_markdown_frontmatter_route_write_findings(plans, apply=False))
    return findings


def _lifecycle_source_provenance_plan_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "lifecycle-source-provenance-plan-scope",
            f"selected repair class: {LIFECYCLE_SOURCE_PROVENANCE_REPAIR_CLASS}; target route files: lifecycle markdown with deprecated transport-level source provenance",
        )
    ]

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "lifecycle-source-provenance-plan-refused",
                "target is a product-source compatibility fixture; lifecycle source-provenance repair planning is report-only and snapshot creation is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        )
        return findings
    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "lifecycle-source-provenance-plan-refused",
                "target is fallback/archive or generated-output evidence; lifecycle source-provenance repair planning is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "warn",
                "lifecycle-source-provenance-plan-refused",
                f"target root kind is {inventory.root_kind}; lifecycle source-provenance repair requires an explicit live operating root",
            )
        )
        return findings
    if not _has_repair_apply_authority(inventory):
        findings.append(
            Finding(
                "warn",
                "lifecycle-source-provenance-plan-refused",
                "snapshot-protected lifecycle source-provenance repair would require an existing readable workflow-core manifest and strict project-state frontmatter authority",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        )
        return findings

    candidates = _lifecycle_source_provenance_candidate_rows(inventory)
    if not candidates:
        findings.append(
            Finding(
                "info",
                "lifecycle-source-provenance-plan-skipped",
                "no deprecated lifecycle source provenance required normalization",
            )
        )
        return findings

    for surface, _plan in candidates:
        target_conflict = _snapshot_target_conflict(inventory.root, surface.rel_path)
        if target_conflict:
            findings.append(_lifecycle_source_provenance_refusal_from(target_conflict, "warn"))
            return findings
        if surface.read_error:
            findings.append(
                Finding(
                    "warn",
                    "lifecycle-source-provenance-plan-refused",
                    f"target file could not be read as clean UTF-8 before lifecycle source-provenance repair: {surface.read_error}",
                    surface.rel_path,
                )
            )
            return findings
        if surface.frontmatter.errors:
            findings.append(
                Finding(
                    "warn",
                    "lifecycle-source-provenance-plan-refused",
                    "target has malformed frontmatter; repair refuses to guess metadata boundaries",
                    surface.rel_path,
                )
            )
            return findings

    plans = [plan for _surface, plan in candidates]
    snapshot_dir = _lifecycle_source_provenance_snapshot_dir(plans, SNAPSHOT_DRY_RUN_TIMESTAMP)
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        findings.append(_lifecycle_source_provenance_refusal_from(boundary_conflict, "warn"))
        return findings

    target_paths = [plan.rel_path for plan in plans]
    metadata_fields = ", ".join([*SNAPSHOT_METADATA_FIELDS, "planned_frontmatter_keys_by_path"])
    findings.extend(
        [
            Finding(
                "warn",
                "lifecycle-source-provenance-plan",
                f"would normalize deprecated route source provenance in {len(plans)} lifecycle markdown artifact(s)",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "lifecycle-source-provenance-targets",
                f"planned target files: {_lifecycle_frontmatter_path_summary(target_paths)}",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "lifecycle-source-provenance-snapshot-path",
                f"planned snapshot directory: {snapshot_dir}/; metadata: {snapshot_dir}/snapshot.json; copied files under {snapshot_dir}/files/",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "lifecycle-source-provenance-metadata",
                f"metadata fields: {metadata_fields}",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "lifecycle-source-provenance-rollback",
                f"manual rollback only: copy files from {snapshot_dir}/files/ back to matching repo paths; no rollback command, cleanup, archive, commit, or lifecycle mutation is implied",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "lifecycle-source-provenance-authority",
                "repair-normalized source provenance is routing metadata only; it cannot approve closeout, archive, commit, lifecycle decisions, truth selection, or future repairs",
                target_paths[0] if target_paths else None,
            ),
        ]
    )
    for plan in plans:
        findings.append(
            Finding(
                "info",
                "lifecycle-source-provenance-value",
                f"planned source provenance for {plan.rel_path}: {plan.fields['source']}",
                plan.rel_path,
            )
        )
    findings.extend(_lifecycle_source_provenance_route_write_findings(plans, apply=False))
    return findings


def _spec_posture_frontmatter_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "spec-posture-frontmatter-plan-scope",
            f"selected repair class: {SPEC_POSTURE_FRONTMATTER_REPAIR_CLASS}; target route files: plan-facing specs and docs/specs contracts missing only spec posture metadata",
        )
    ]

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "spec-posture-frontmatter-plan-refused",
                "target is a product-source compatibility fixture; spec posture frontmatter repair planning is report-only and snapshot creation is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        )
        return findings
    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "spec-posture-frontmatter-plan-refused",
                "target is fallback/archive or generated-output evidence; spec posture frontmatter repair planning is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "warn",
                "spec-posture-frontmatter-plan-refused",
                f"target root kind is {inventory.root_kind}; spec posture frontmatter repair requires an explicit live operating root",
            )
        )
        return findings
    if not _has_repair_apply_authority(inventory):
        findings.append(
            Finding(
                "warn",
                "spec-posture-frontmatter-plan-refused",
                "snapshot-protected spec posture frontmatter repair would require an existing readable workflow-core manifest and strict project-state frontmatter authority",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        )
        return findings

    candidates = _spec_posture_frontmatter_candidate_rows(inventory, validation)
    if not candidates:
        findings.append(
            Finding(
                "info",
                "spec-posture-frontmatter-plan-skipped",
                "no plan-facing spec posture diagnostics require a snapshot plan",
            )
        )
        return findings

    refusal = _spec_posture_frontmatter_candidate_refusal(inventory, candidates, severity="warn")
    if refusal:
        findings.append(refusal)
        return findings

    plans = [plan for _surface, _diagnostics, plan in candidates]
    snapshot_dir = _spec_posture_frontmatter_snapshot_dir(plans, SNAPSHOT_DRY_RUN_TIMESTAMP)
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        findings.append(_spec_posture_frontmatter_refusal_from(boundary_conflict, "warn"))
        return findings

    diagnostics = [diagnostic for _surface, diagnostics, _plan in candidates for diagnostic in diagnostics]
    diagnostic_codes = ", ".join(sorted({finding.code for finding in diagnostics}))
    target_paths = [plan.rel_path for plan in plans]
    metadata_fields = ", ".join([*SNAPSHOT_METADATA_FIELDS, "planned_frontmatter_keys_by_path"])
    findings.extend(
        [
            Finding(
                "warn",
                "spec-posture-frontmatter-plan",
                (
                    f"would add only missing spec posture frontmatter to {len(plans)} plan-facing spec/document contract(s); "
                    f"source diagnostics: {diagnostic_codes}"
                ),
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "spec-posture-frontmatter-targets",
                f"planned target files: {_lifecycle_frontmatter_path_summary(target_paths)}",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "spec-posture-frontmatter-snapshot-path",
                f"planned snapshot directory: {snapshot_dir}/; metadata: {snapshot_dir}/snapshot.json; copied files under {snapshot_dir}/files/",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "spec-posture-frontmatter-metadata",
                f"metadata fields: {metadata_fields}",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "spec-posture-frontmatter-boundary",
                "repair is limited to MLH-owned stable-specs and plan-facing docs/specs contracts; no blanket all-*.md rewrite, lifecycle movement, archive, closeout, staging, or commit is implied",
                target_paths[0] if target_paths else None,
            ),
            Finding(
                "info",
                "spec-posture-frontmatter-validation",
                "validation method after a future apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                target_paths[0] if target_paths else None,
            ),
        ]
    )
    for plan in plans:
        findings.append(
            Finding(
                "info",
                "spec-posture-frontmatter-keys",
                f"planned frontmatter keys for {plan.rel_path}: {', '.join(plan.fields)}",
                plan.rel_path,
            )
        )
    findings.extend(_spec_posture_frontmatter_route_write_findings(plans, apply=False))
    return findings


def _docmap_snapshot_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "snapshot-plan-scope",
            f"selected repair class: {DOCMAP_REPAIR_CLASS}; target file: {DOCMAP_REPAIR_TARGET_REL}",
            DOCMAP_REPAIR_TARGET_REL,
        )
    ]

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "snapshot-plan-refused",
                "target is a product-source compatibility fixture; repair snapshot planning is report-only and snapshot creation is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        )
        return findings
    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "snapshot-plan-refused",
                "target is fallback/archive or generated-output evidence; repair snapshot planning is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "warn",
                "snapshot-plan-refused",
                f"target root kind is {inventory.root_kind}; docmap snapshot planning requires an explicit live operating root",
            )
        )
        return findings
    if not _has_repair_apply_authority(inventory):
        findings.append(
            Finding(
                "warn",
                "snapshot-plan-refused",
                "snapshot-protected repair would require an existing readable workflow-core manifest and strict project-state frontmatter authority",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        )
        return findings

    path_conflict = _snapshot_target_conflict(inventory.root, DOCMAP_REPAIR_TARGET_REL)
    if path_conflict:
        findings.append(path_conflict)
        return findings
    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    if not target.exists():
        findings.append(
            Finding(
                "info",
                "snapshot-plan-skipped",
                f"target file is absent: {DOCMAP_REPAIR_TARGET_REL}; absent docmap remains a create-only/bootstrap question",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings

    route_diagnostics = _docmap_route_diagnostics(inventory, validation)
    if not route_diagnostics:
        findings.append(
            Finding(
                "info",
                "snapshot-plan",
                f"no {DOCMAP_REPAIR_TARGET_REL} route diagnostics require a snapshot plan",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings

    route_entries = _docmap_route_entries_from_diagnostics(route_diagnostics)
    snapshot_dir = _docmap_snapshot_preview_dir(target, route_entries)
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        findings.append(boundary_conflict)
        return findings

    diagnostic_codes = ", ".join(sorted({finding.code for finding in route_diagnostics}))
    route_summary = ", ".join(route_entries) if route_entries else "route entries from listed docmap diagnostics"
    metadata_fields = ", ".join(SNAPSHOT_METADATA_FIELDS)
    findings.extend(
        [
            Finding(
                "warn",
                "snapshot-plan",
                f"would plan snapshot before docmap route repair; target files: {DOCMAP_REPAIR_TARGET_REL}; source diagnostics: {diagnostic_codes}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-path",
                f"planned snapshot directory: {snapshot_dir}/; metadata: {snapshot_dir}/snapshot.json; copied file: {snapshot_dir}/{DOCMAP_REPAIR_COPY_REL}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-metadata",
                f"metadata fields: {metadata_fields}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-route-change",
                f"planned route entries: {route_summary}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-rollback",
                f"manual rollback only: copy {snapshot_dir}/{DOCMAP_REPAIR_COPY_REL} back to {DOCMAP_REPAIR_TARGET_REL}; no rollback command, cleanup, archive, commit, or lifecycle mutation is implied",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-validation",
                "validation method after a future apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-authority",
                "snapshot metadata is safety evidence only and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                DOCMAP_REPAIR_TARGET_REL,
            ),
        ]
    )
    return findings


def _docmap_create_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "docmap-create-scope",
            f"selected repair class: {DOCMAP_CREATE_CLASS}; target file: {DOCMAP_REPAIR_TARGET_REL}",
            DOCMAP_REPAIR_TARGET_REL,
        )
    ]

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "docmap-create-refused",
                "target is a product-source compatibility fixture; docmap creation is report-only and repair --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        )
        return findings
    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "docmap-create-refused",
                "target is fallback/archive or generated-output evidence; docmap creation is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "warn",
                "docmap-create-refused",
                f"target root kind is {inventory.root_kind}; docmap creation requires an explicit live operating root",
            )
        )
        return findings
    if not _has_repair_apply_authority(inventory):
        findings.append(
            Finding(
                "warn",
                "docmap-create-refused",
                "docmap creation would require an existing readable workflow-core manifest and strict project-state frontmatter authority",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        )
        return findings

    conflict = _docmap_create_target_conflict(inventory.root)
    if conflict:
        findings.append(conflict)
        return findings

    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    if target.exists():
        findings.append(
            Finding(
                "info",
                "docmap-create-skipped",
                f"target file already exists: {DOCMAP_REPAIR_TARGET_REL}; docmap creation never rewrites existing content",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings

    diagnostic = _docmap_missing_required_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "docmap-create-skipped",
                f"no missing required {DOCMAP_REPAIR_TARGET_REL} diagnostic was found; lazy or not-required docmaps remain absent",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings

    route_entries = _docmap_create_route_entries(inventory)
    findings.extend(
        [
            Finding(
                "warn",
                "docmap-create-plan",
                f"would create {DOCMAP_REPAIR_TARGET_REL} because validation reports {diagnostic.code}: {diagnostic.message}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "docmap-create-routes",
                f"planned route entries: {', '.join(route_entries)}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "docmap-create-rollback",
                f"manual rollback only: remove {DOCMAP_REPAIR_TARGET_REL}; remove .agents/ only if it is empty and was created by this repair",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "docmap-create-validation",
                "validation method after apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "docmap-create-authority",
                "docmap routing is advisory and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                DOCMAP_REPAIR_TARGET_REL,
            ),
        ]
    )
    return findings


def _agents_contract_create_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "agents-contract-create-scope",
            f"selected repair class: {AGENTS_CONTRACT_CREATE_CLASS}; target file: {AGENTS_CONTRACT_TARGET_REL}",
            AGENTS_CONTRACT_TARGET_REL,
        )
    ]

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "agents-contract-create-refused",
                "target is a product-source compatibility fixture; AGENTS.md creation is report-only and repair --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        )
        return findings
    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "agents-contract-create-refused",
                "target is fallback/archive or generated-output evidence; AGENTS.md creation is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "warn",
                "agents-contract-create-refused",
                f"target root kind is {inventory.root_kind}; AGENTS.md creation requires an explicit live operating root",
            )
        )
        return findings
    if not _has_repair_apply_authority(inventory):
        findings.append(
            Finding(
                "warn",
                "agents-contract-create-refused",
                "AGENTS.md creation would require an existing readable workflow-core manifest and strict project-state frontmatter authority",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        )
        return findings

    conflict = _agents_contract_create_target_conflict(inventory.root)
    if conflict:
        findings.append(conflict)
        return findings

    target = inventory.root / AGENTS_CONTRACT_TARGET_REL
    if target.exists():
        findings.append(
            Finding(
                "info",
                "agents-contract-create-skipped",
                f"target file already exists: {AGENTS_CONTRACT_TARGET_REL}; AGENTS.md creation never rewrites existing content",
                AGENTS_CONTRACT_TARGET_REL,
            )
        )
        return findings

    diagnostic = _agents_contract_missing_required_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "agents-contract-create-skipped",
                f"no missing required {AGENTS_CONTRACT_TARGET_REL} diagnostic was found",
                AGENTS_CONTRACT_TARGET_REL,
            )
        )
        return findings

    _, template_error = _agents_contract_template()
    if template_error:
        findings.append(template_error)
        return findings

    findings.extend(
        [
            Finding(
                "warn",
                "agents-contract-create-plan",
                f"would create {AGENTS_CONTRACT_TARGET_REL} because validation reports {diagnostic.code}: {diagnostic.message}",
                AGENTS_CONTRACT_TARGET_REL,
            ),
            Finding(
                "info",
                "agents-contract-create-rollback",
                f"manual rollback only: remove {AGENTS_CONTRACT_TARGET_REL}; no rollback command, cleanup, archive, commit, or lifecycle mutation is implied",
                AGENTS_CONTRACT_TARGET_REL,
            ),
            Finding(
                "info",
                "agents-contract-create-validation",
                "validation method after apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                AGENTS_CONTRACT_TARGET_REL,
            ),
            Finding(
                "info",
                "agents-contract-create-authority",
                "AGENTS.md is an operator contract surface and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                AGENTS_CONTRACT_TARGET_REL,
            ),
        ]
    )
    return findings


def _agents_contract_create_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    target = inventory.root / AGENTS_CONTRACT_TARGET_REL
    conflict = _agents_contract_create_target_conflict(inventory.root)
    if conflict and (target.exists() or _agents_contract_missing_required_diagnostic(validation) is not None):
        return [Finding("error", conflict.code, conflict.message, conflict.source, conflict.line)]
    if target.exists() or _agents_contract_missing_required_diagnostic(validation) is None:
        return []
    _, template_error = _agents_contract_template()
    if template_error:
        return [Finding("error", template_error.code, template_error.message, template_error.source, template_error.line)]
    return []


def _agents_contract_create_apply_findings(inventory: Inventory, validation: list[Finding]) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "agents-contract-create-scope",
            f"selected repair class: {AGENTS_CONTRACT_CREATE_CLASS}; target file: {AGENTS_CONTRACT_TARGET_REL}",
            AGENTS_CONTRACT_TARGET_REL,
        )
    ]
    target = inventory.root / AGENTS_CONTRACT_TARGET_REL
    if target.exists():
        findings.append(
            Finding(
                "info",
                "agents-contract-create-skipped",
                f"target file already exists: {AGENTS_CONTRACT_TARGET_REL}; AGENTS.md creation never rewrites existing content",
                AGENTS_CONTRACT_TARGET_REL,
            )
        )
        return findings, False

    diagnostic = _agents_contract_missing_required_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "agents-contract-create-skipped",
                f"no missing required {AGENTS_CONTRACT_TARGET_REL} diagnostic was found",
                AGENTS_CONTRACT_TARGET_REL,
            )
        )
        return findings, False

    template, template_error = _agents_contract_template()
    if template_error:
        return [Finding("error", template_error.code, template_error.message, template_error.source, template_error.line)], False

    try:
        target.write_text(template, encoding="utf-8")
    except OSError as exc:
        return [
            Finding(
                "error",
                "agents-contract-create-refused",
                f"create-only AGENTS.md repair failed before target file was completed: {exc}",
                AGENTS_CONTRACT_TARGET_REL,
            )
        ], False

    findings.extend(
        [
            Finding("info", "agents-contract-create-created", f"created create-only repair file: {AGENTS_CONTRACT_TARGET_REL}", AGENTS_CONTRACT_TARGET_REL),
            Finding(
                "info",
                "agents-contract-create-rollback",
                f"manual rollback only: remove {AGENTS_CONTRACT_TARGET_REL}; no rollback command, cleanup, archive, commit, or lifecycle mutation is implied",
                AGENTS_CONTRACT_TARGET_REL,
            ),
            Finding(
                "info",
                "agents-contract-create-authority",
                "AGENTS.md is an operator contract surface and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                AGENTS_CONTRACT_TARGET_REL,
            ),
        ]
    )
    return findings, True


def _agents_contract_missing_required_diagnostic(validation: list[Finding]) -> Finding | None:
    for finding in validation:
        if (
            finding.severity == "error"
            and finding.code == "missing-required-surface"
            and finding.source == AGENTS_CONTRACT_TARGET_REL
        ):
            return finding
    return None


def _agents_contract_create_target_conflict(root: Path) -> Finding | None:
    target_path = root / AGENTS_CONTRACT_TARGET_REL
    if target_path.is_symlink():
        return Finding("warn", "agents-contract-create-refused", f"target path contains a symlink segment: {AGENTS_CONTRACT_TARGET_REL}", AGENTS_CONTRACT_TARGET_REL)
    if target_path.exists() and not target_path.is_file():
        return Finding("warn", "agents-contract-create-refused", f"target path is not a regular file: {AGENTS_CONTRACT_TARGET_REL}", AGENTS_CONTRACT_TARGET_REL)
    try:
        target_path.resolve().relative_to(root.resolve())
    except ValueError:
        return Finding("warn", "agents-contract-create-refused", f"target path would escape the target root: {AGENTS_CONTRACT_TARGET_REL}", AGENTS_CONTRACT_TARGET_REL)
    return None


def _agents_contract_template() -> tuple[str | None, Finding | None]:
    try:
        content = resources.files(STABLE_SPEC_TEMPLATE_PACKAGE).joinpath(*AGENTS_CONTRACT_TEMPLATE_REL).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError) as exc:
        return None, Finding(
            "warn",
            "agents-contract-create-refused",
            f"packaged AGENTS.md template is missing or unreadable: {exc}",
            "/".join(AGENTS_CONTRACT_TEMPLATE_REL),
        )
    return content if content.endswith("\n") else content + "\n", None


def _docmap_create_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    conflict = _docmap_create_target_conflict(inventory.root)
    if conflict and (target.exists() or _docmap_missing_required_diagnostic(validation) is not None):
        return [Finding("error", conflict.code, conflict.message, conflict.source, conflict.line)]
    if target.exists() or _docmap_missing_required_diagnostic(validation) is None:
        return []
    return []


def _docmap_create_apply_findings(inventory: Inventory, validation: list[Finding]) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "docmap-create-scope",
            f"selected repair class: {DOCMAP_CREATE_CLASS}; target file: {DOCMAP_REPAIR_TARGET_REL}",
            DOCMAP_REPAIR_TARGET_REL,
        )
    ]

    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    if target.exists():
        findings.append(
            Finding(
                "info",
                "docmap-create-skipped",
                f"target file already exists: {DOCMAP_REPAIR_TARGET_REL}; docmap creation never rewrites existing content",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings, False

    diagnostic = _docmap_missing_required_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "docmap-create-skipped",
                f"no missing required {DOCMAP_REPAIR_TARGET_REL} diagnostic was found; lazy or not-required docmaps remain absent",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings, False

    parent_created = not target.parent.exists()
    route_entries = _docmap_create_route_entries(inventory)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_docmap_create_content(route_entries), encoding="utf-8")
    except OSError as exc:
        return [
            Finding(
                "error",
                "docmap-create-refused",
                f"create-only docmap repair failed before target file was completed: {exc}",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ], False

    if parent_created:
        findings.append(Finding("info", "docmap-create-parent-created", "created parent directory: .agents", ".agents"))
    findings.extend(
        [
            Finding("info", "docmap-create-created", f"created create-only repair file: {DOCMAP_REPAIR_TARGET_REL}", DOCMAP_REPAIR_TARGET_REL),
            Finding("info", "docmap-create-routes", f"created route entries: {', '.join(route_entries)}", DOCMAP_REPAIR_TARGET_REL),
            Finding(
                "info",
                "docmap-create-rollback",
                f"manual rollback only: remove {DOCMAP_REPAIR_TARGET_REL}; remove .agents/ only if it is empty and was created by this repair",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "docmap-create-authority",
                "docmap routing is advisory and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                DOCMAP_REPAIR_TARGET_REL,
            ),
        ]
    )
    return findings, True


def _docmap_missing_required_diagnostic(validation: list[Finding]) -> Finding | None:
    for finding in validation:
        if (
            finding.severity == "error"
            and finding.code == "missing-required-surface"
            and finding.source == DOCMAP_REPAIR_TARGET_REL
        ):
            return finding
    return None


def _stable_spec_create_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "stable-spec-create-scope",
            f"selected repair class: {STABLE_SPEC_CREATE_CLASS}; target directory: {STABLE_SPEC_ROOT_REL}/",
            STABLE_SPEC_ROOT_REL,
        )
    ]

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "stable-spec-create-refused",
                "target is a product-source compatibility fixture; stable spec creation is report-only and repair --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        )
        return findings
    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "stable-spec-create-refused",
                "target is fallback/archive or generated-output evidence; stable spec creation is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "warn",
                "stable-spec-create-refused",
                f"target root kind is {inventory.root_kind}; stable spec creation requires an explicit live operating root",
            )
        )
        return findings
    if not _has_repair_apply_authority(inventory):
        findings.append(
            Finding(
                "warn",
                "stable-spec-create-refused",
                "stable spec creation would require an existing readable workflow-core manifest and strict project-state frontmatter authority",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        )
        return findings

    missing_names = _missing_stable_spec_names(inventory, validation)
    if not missing_names:
        findings.append(
            Finding(
                "info",
                "stable-spec-create-skipped",
                f"no missing required stable workflow spec diagnostic was found under {STABLE_SPEC_ROOT_REL}/",
                STABLE_SPEC_ROOT_REL,
            )
        )
        return findings

    conflict = _stable_spec_create_target_conflict(inventory.root, missing_names)
    if conflict:
        findings.append(conflict)
        return findings
    _, template_errors = _stable_spec_templates_for(missing_names)
    if template_errors:
        findings.extend(template_errors)
        return findings

    rel_paths = _stable_spec_rel_paths(missing_names)
    findings.extend(
        [
            Finding(
                "warn",
                "stable-spec-create-plan",
                f"would create missing stable workflow specs because validation reports missing-stable-spec: {', '.join(rel_paths)}",
                STABLE_SPEC_ROOT_REL,
            ),
            Finding("info", "stable-spec-create-files", f"planned stable spec files: {', '.join(rel_paths)}", STABLE_SPEC_ROOT_REL),
            Finding(
                "info",
                "stable-spec-create-rollback",
                f"manual rollback only: remove created stable spec files: {', '.join(rel_paths)}; remove {STABLE_SPEC_ROOT_REL}/ only if it is empty and was created by this repair",
                STABLE_SPEC_ROOT_REL,
            ),
            Finding(
                "info",
                "stable-spec-create-validation",
                "validation method after apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                STABLE_SPEC_ROOT_REL,
            ),
            Finding(
                "info",
                "stable-spec-create-authority",
                "stable spec fixtures are repo-visible compatibility surfaces and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                STABLE_SPEC_ROOT_REL,
            ),
            Finding(
                "warn",
                "stable-spec-create-review-required",
                "packaged stable spec templates are intentionally minimal bootstrap stubs; repaired specs require human review before they are treated as complete stable contract depth",
                STABLE_SPEC_ROOT_REL,
            ),
        ]
    )
    return findings


def _stable_spec_create_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    missing_names = _missing_stable_spec_names(inventory, validation)
    if not missing_names:
        return []
    conflict = _stable_spec_create_target_conflict(inventory.root, missing_names)
    if conflict:
        return [Finding("error", conflict.code, conflict.message, conflict.source, conflict.line)]
    _, template_errors = _stable_spec_templates_for(missing_names)
    return [Finding("error", finding.code, finding.message, finding.source, finding.line) for finding in template_errors]


def _stable_spec_create_apply_findings(inventory: Inventory, validation: list[Finding]) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "stable-spec-create-scope",
            f"selected repair class: {STABLE_SPEC_CREATE_CLASS}; target directory: {STABLE_SPEC_ROOT_REL}/",
            STABLE_SPEC_ROOT_REL,
        )
    ]
    missing_names = _missing_stable_spec_names(inventory, validation)
    if not missing_names:
        findings.append(
            Finding(
                "info",
                "stable-spec-create-skipped",
                f"no missing required stable workflow spec diagnostic was found under {STABLE_SPEC_ROOT_REL}/",
                STABLE_SPEC_ROOT_REL,
            )
        )
        return findings, False

    templates, template_errors = _stable_spec_templates_for(missing_names)
    if template_errors:
        return [Finding("error", finding.code, finding.message, finding.source, finding.line) for finding in template_errors], False

    root = inventory.root
    spec_root = root / STABLE_SPEC_ROOT_REL
    parent_created = not spec_root.exists()
    created_rel_paths: list[str] = []
    try:
        spec_root.mkdir(parents=True, exist_ok=True)
        for name in missing_names:
            target = root / STABLE_SPEC_ROOT_REL / name
            if target.exists():
                continue
            target.write_text(templates[name], encoding="utf-8")
            created_rel_paths.append(f"{STABLE_SPEC_ROOT_REL}/{name}")
    except OSError as exc:
        return [
            Finding(
                "error",
                "stable-spec-create-refused",
                f"create-only stable spec repair failed before target files were completed: {exc}",
                STABLE_SPEC_ROOT_REL,
            )
        ], False

    if not created_rel_paths:
        findings.append(
            Finding(
                "info",
                "stable-spec-create-skipped",
                f"stable workflow spec files already existed under {STABLE_SPEC_ROOT_REL}/; stable spec creation never rewrites existing content",
                STABLE_SPEC_ROOT_REL,
            )
        )
        return findings, False

    if parent_created:
        findings.append(Finding("info", "stable-spec-create-created", f"created parent directory: {STABLE_SPEC_ROOT_REL}", STABLE_SPEC_ROOT_REL))
    for rel_path in created_rel_paths:
        findings.append(Finding("info", "stable-spec-create-created", f"created create-only repair file: {rel_path}", rel_path))
    findings.extend(
        [
            Finding("info", "stable-spec-create-files", f"created stable spec files: {', '.join(created_rel_paths)}", STABLE_SPEC_ROOT_REL),
            Finding(
                "info",
                "stable-spec-create-rollback",
                f"manual rollback only: remove created stable spec files: {', '.join(created_rel_paths)}; remove {STABLE_SPEC_ROOT_REL}/ only if it is empty and was created by this repair",
                STABLE_SPEC_ROOT_REL,
            ),
            Finding(
                "info",
                "stable-spec-create-authority",
                "stable spec fixtures are repo-visible compatibility surfaces and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                STABLE_SPEC_ROOT_REL,
            ),
            Finding(
                "warn",
                "stable-spec-create-review-required",
                "packaged stable spec templates are intentionally minimal bootstrap stubs; repaired specs require human review before they are treated as complete stable contract depth",
                STABLE_SPEC_ROOT_REL,
            ),
        ]
    )
    return findings, True


def _missing_stable_spec_names(inventory: Inventory, validation: list[Finding]) -> list[str]:
    expected = set(EXPECTED_SPEC_NAMES)
    names: list[str] = []
    prefix = f"missing expected workflow spec: {STABLE_SPEC_ROOT_REL}/"
    for finding in validation:
        if finding.severity != "error" or finding.code != "missing-stable-spec":
            continue
        if not finding.message.startswith(prefix):
            continue
        name = finding.message[len(prefix) :].strip()
        if name in expected and not (inventory.root / STABLE_SPEC_ROOT_REL / name).exists() and name not in names:
            names.append(name)
    return names


def _stable_spec_rel_paths(names: list[str]) -> list[str]:
    return [f"{STABLE_SPEC_ROOT_REL}/{name}" for name in names]


def _stable_spec_create_target_conflict(root: Path, names: list[str]) -> Finding | None:
    for name in names:
        rel_path = f"{STABLE_SPEC_ROOT_REL}/{name}"
        target_path = root / rel_path
        for candidate in _root_relative_path_chain(root, rel_path):
            candidate_rel = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                return Finding("warn", "stable-spec-create-refused", f"target path contains a symlink segment: {candidate_rel}", candidate_rel)
            if candidate.exists() and candidate != target_path and not candidate.is_dir():
                return Finding("warn", "stable-spec-create-refused", f"target path contains a non-directory segment: {candidate_rel}", candidate_rel)
        if target_path.exists() and not target_path.is_file():
            return Finding("warn", "stable-spec-create-refused", f"target path is not a regular file: {rel_path}", rel_path)
        try:
            target_path.resolve().relative_to(root.resolve())
        except ValueError:
            return Finding("warn", "stable-spec-create-refused", f"target path would escape the target root: {rel_path}", rel_path)
    return None


def _stable_spec_templates_for(names: list[str]) -> tuple[dict[str, str], list[Finding]]:
    templates: dict[str, str] = {}
    errors: list[Finding] = []
    base = resources.files(STABLE_SPEC_TEMPLATE_PACKAGE).joinpath(*STABLE_SPEC_TEMPLATE_REL)
    for name in names:
        try:
            content = base.joinpath(name).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError, UnicodeDecodeError) as exc:
            errors.append(
                Finding(
                    "warn",
                    "stable-spec-create-refused",
                    f"packaged stable spec template is missing or unreadable: {name}: {exc}",
                    f"{'/'.join(STABLE_SPEC_TEMPLATE_REL)}/{name}",
                )
            )
            continue
        templates[name] = _stable_spec_template_with_frontmatter(name, content)
    return templates, errors


def _stable_spec_template_with_frontmatter(name: str, content: str) -> str:
    normalized = content if content.endswith("\n") else content + "\n"
    frontmatter = parse_frontmatter(normalized)
    if frontmatter.has_frontmatter and not frontmatter.errors:
        return normalized
    title = _stable_spec_template_title(name, normalized)
    fields = lifecycle_markdown_frontmatter_fields_for_route("stable-specs", title)
    return lifecycle_markdown_text_with_frontmatter(normalized, fields)


def _stable_spec_template_title(name: str, content: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            title = line.removeprefix("# ").strip()
            if title:
                return title
    return name.removesuffix(".md").replace("-", " ").title()


def _state_prose_fallback_diagnostic(validation: list[Finding]) -> Finding | None:
    for finding in validation:
        if finding.code == "state-prose-fallback" and finding.source == STATE_FRONTMATTER_TARGET_REL:
            return finding
    return None


def _state_frontmatter_refusal_finding(inventory: Inventory, validation: list[Finding], severity: str) -> Finding | None:
    if _is_product_source_inventory(inventory):
        return Finding(
            severity,
            "state-frontmatter-refused",
            "target is a product-source compatibility fixture; state frontmatter repair is report-only and repair --apply is refused",
            inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
        )
    if _is_fallback_or_archive_inventory(inventory):
        return Finding(
            severity,
            "state-frontmatter-refused",
            "target is fallback/archive or generated-output evidence; state frontmatter repair is refused",
            inventory.state.rel_path if inventory.state else None,
        )
    if inventory.root_kind != "live_operating_root":
        return Finding(
            severity,
            "state-frontmatter-refused",
            f"target root kind is {inventory.root_kind}; state frontmatter repair requires an explicit live operating root",
        )

    manifest = inventory.manifest_surface
    if not manifest or not manifest.exists or inventory.manifest_errors:
        return Finding(
            severity,
            "state-frontmatter-refused",
            "state frontmatter repair requires an existing readable workflow-core manifest",
            manifest.rel_path if manifest else ATTACH_MANIFEST_REL_PATH,
        )
    if inventory.manifest.get("workflow") != "workflow-core":
        return Finding(
            severity,
            "state-frontmatter-refused",
            "state frontmatter repair requires manifest workflow = workflow-core",
            manifest.rel_path,
        )
    manifest_state = str(inventory.manifest.get("memory", {}).get("state_file", STATE_FRONTMATTER_TARGET_REL)).replace("\\", "/")
    if manifest_state != STATE_FRONTMATTER_TARGET_REL:
        return Finding(
            severity,
            "state-frontmatter-refused",
            f"state frontmatter repair is limited to {STATE_FRONTMATTER_TARGET_REL}; manifest state_file is {manifest_state}",
            manifest.rel_path,
        )

    state = inventory.state
    if not state or not state.exists:
        return Finding(
            severity,
            "state-frontmatter-refused",
            f"state frontmatter repair requires an existing {STATE_FRONTMATTER_TARGET_REL}",
            STATE_FRONTMATTER_TARGET_REL,
        )
    if state.read_error:
        return Finding(
            severity,
            "state-frontmatter-refused",
            f"state file could not be read as clean UTF-8 before state frontmatter repair: {state.read_error}",
            STATE_FRONTMATTER_TARGET_REL,
        )
    if state.frontmatter.has_frontmatter:
        return Finding(
            severity,
            "state-frontmatter-refused",
            "project-state.md already has frontmatter or malformed frontmatter; this class only prepends missing frontmatter to prose state",
            STATE_FRONTMATTER_TARGET_REL,
        )

    data = state.frontmatter.data
    missing = [key for key in ("operating_mode", "plan_status") if not data.get(key)]
    if missing:
        return Finding(
            severity,
            "state-frontmatter-refused",
            f"state frontmatter repair requires prose assignments for: {', '.join(missing)}",
            STATE_FRONTMATTER_TARGET_REL,
        )

    plan_status = str(data.get("plan_status") or "")
    manifest_plan = str(inventory.manifest.get("memory", {}).get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
    active_plan = str(data.get("active_plan") or "").replace("\\", "/")
    if plan_status == "active":
        if not active_plan:
            return Finding(
                severity,
                "state-frontmatter-refused",
                "state frontmatter repair refuses active plan_status when active_plan is missing",
                STATE_FRONTMATTER_TARGET_REL,
            )
        if active_plan != manifest_plan:
            return Finding(
                severity,
                "state-frontmatter-refused",
                f"state frontmatter repair refuses active_plan mismatch: {active_plan} != {manifest_plan}",
                STATE_FRONTMATTER_TARGET_REL,
            )
        if not inventory.active_plan_surface or not inventory.active_plan_surface.exists:
            return Finding(
                severity,
                "state-frontmatter-refused",
                f"state frontmatter repair refuses missing active plan: {active_plan}",
                active_plan,
            )

    disallowed_codes = {"manifest-parse", "manifest-workflow", "manifest-state-file", "active-plan-field", "active-plan-missing", "active-plan-manifest"}
    for finding in validation:
        if finding.code in disallowed_codes:
            return Finding(
                severity,
                "state-frontmatter-refused",
                f"state frontmatter repair refuses unresolved diagnostic {finding.code}: {finding.message}",
                finding.source,
                finding.line,
            )
    return None


def _state_frontmatter_refusal_from(finding: Finding, severity: str = "error") -> Finding:
    return Finding(severity, "state-frontmatter-refused", finding.message, finding.source, finding.line)


def _state_frontmatter_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    refusal = _state_frontmatter_refusal_finding(inventory, validation, severity="error")
    if refusal:
        return [refusal]
    target_conflict = _snapshot_target_conflict(inventory.root, STATE_FRONTMATTER_TARGET_REL)
    if target_conflict:
        return [_state_frontmatter_refusal_from(target_conflict)]

    state = inventory.state
    assert state is not None
    fields = _state_frontmatter_fields(inventory)
    snapshot_dir = _state_frontmatter_snapshot_dir(state.path, _state_frontmatter_text(fields), _current_snapshot_timestamp())
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        return [_state_frontmatter_refusal_from(boundary_conflict)]
    return []


def _state_frontmatter_apply_findings(inventory: Inventory, validation: list[Finding]) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "state-frontmatter-apply-scope",
            f"selected repair class: {STATE_FRONTMATTER_REPAIR_CLASS}; target file: {STATE_FRONTMATTER_TARGET_REL}",
            STATE_FRONTMATTER_TARGET_REL,
        )
    ]
    diagnostic = _state_prose_fallback_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "state-frontmatter-apply-skipped",
                "no state-prose-fallback diagnostic required state frontmatter repair",
                STATE_FRONTMATTER_TARGET_REL,
            )
        )
        return findings, False

    state = inventory.state
    assert state is not None
    target = state.path
    fields = _state_frontmatter_fields(inventory)
    frontmatter_text = _state_frontmatter_text(fields)
    timestamp = _current_snapshot_timestamp()
    snapshot_dir_rel = _state_frontmatter_snapshot_dir(target, frontmatter_text, timestamp)
    snapshot_dir = inventory.root / snapshot_dir_rel
    copy_rel = f"{snapshot_dir_rel}/{STATE_FRONTMATTER_COPY_REL}"
    copy_path = inventory.root / copy_rel
    metadata_rel = f"{snapshot_dir_rel}/snapshot.json"
    metadata_path = inventory.root / metadata_rel
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir_rel)
    if boundary_conflict:
        return [_state_frontmatter_refusal_from(boundary_conflict)], False

    try:
        pre_repair_bytes = target.read_bytes()
        pre_repair_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [
            Finding(
                "error",
                "state-frontmatter-refused",
                f"state file could not be decoded as UTF-8 before state frontmatter repair: {exc}",
                STATE_FRONTMATTER_TARGET_REL,
            )
        ], False
    except OSError as exc:
        return [
            Finding(
                "error",
                "state-frontmatter-refused",
                f"state file could not be read before state frontmatter repair: {exc}",
                STATE_FRONTMATTER_TARGET_REL,
            )
        ], False

    repaired_bytes = frontmatter_text.encode("utf-8") + pre_repair_bytes
    metadata = _state_frontmatter_snapshot_metadata(
        inventory,
        timestamp,
        snapshot_dir_rel,
        copy_rel,
        list(fields),
        diagnostic,
        pre_repair_bytes,
    )
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=False)
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        copy_path.write_bytes(pre_repair_bytes)
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        target.write_bytes(repaired_bytes)
    except OSError as exc:
        return [
            Finding(
                "error",
                "state-frontmatter-refused",
                f"state frontmatter repair failed before target mutation completed: {exc}",
                STATE_FRONTMATTER_TARGET_REL,
            )
        ], False

    findings.extend(
        [
            Finding("info", "snapshot-created", f"created repair snapshot before state frontmatter mutation: {snapshot_dir_rel}/", STATE_FRONTMATTER_TARGET_REL),
            Finding("info", "snapshot-copied-file", f"copied pre-repair bytes to {copy_rel}", STATE_FRONTMATTER_TARGET_REL),
            Finding("info", "snapshot-metadata-written", f"wrote snapshot metadata: {metadata_rel}", STATE_FRONTMATTER_TARGET_REL),
            Finding("info", "state-frontmatter-updated", f"prepended deterministic frontmatter keys: {', '.join(fields)}", STATE_FRONTMATTER_TARGET_REL),
            Finding(
                "info",
                "state-frontmatter-rollback",
                f"manual rollback only: copy {copy_rel} back to {STATE_FRONTMATTER_TARGET_REL}; then run validate and audit-links",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-authority",
                "snapshot metadata is safety evidence only and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                STATE_FRONTMATTER_TARGET_REL,
            ),
        ]
    )
    return findings, True


def _lifecycle_markdown_frontmatter_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    candidates = _lifecycle_markdown_frontmatter_candidate_rows(inventory, validation)
    if not candidates:
        return []
    for surface, _diagnostics, _plan in candidates:
        target_conflict = _snapshot_target_conflict(inventory.root, surface.rel_path)
        if target_conflict:
            return [_lifecycle_frontmatter_refusal_from(target_conflict)]
        if surface.read_error:
            return [
                Finding(
                    "error",
                    "lifecycle-frontmatter-refused",
                    f"target file could not be read as clean UTF-8 before lifecycle frontmatter repair: {surface.read_error}",
                    surface.rel_path,
                )
            ]
        if surface.frontmatter.errors:
            return [
                Finding(
                    "error",
                    "lifecycle-frontmatter-refused",
                    "target has malformed frontmatter; repair refuses to guess metadata boundaries",
                    surface.rel_path,
                )
            ]
    snapshot_dir = _lifecycle_markdown_frontmatter_snapshot_dir([plan for _surface, _diagnostics, plan in candidates], _current_snapshot_timestamp())
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        return [_lifecycle_frontmatter_refusal_from(boundary_conflict)]
    return []


def _lifecycle_markdown_frontmatter_apply_findings(
    inventory: Inventory,
    validation: list[Finding],
) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "lifecycle-frontmatter-apply-scope",
            f"selected repair class: {LIFECYCLE_MARKDOWN_FRONTMATTER_REPAIR_CLASS}; target route files: lifecycle markdown requiring frontmatter",
        )
    ]
    candidates = _lifecycle_markdown_frontmatter_candidate_rows(inventory, validation)
    if not candidates:
        findings.append(
            Finding(
                "info",
                "lifecycle-frontmatter-apply-skipped",
                "no lifecycle markdown frontmatter diagnostics required snapshot-protected repair",
            )
        )
        return findings, False

    plans = [plan for _surface, _diagnostics, plan in candidates]
    changed_plans = [plan for plan in plans if plan.current_text != plan.updated_text]
    if not changed_plans:
        findings.append(
            Finding(
                "info",
                "lifecycle-frontmatter-apply-skipped",
                "planned lifecycle frontmatter already matched current files; no snapshot or rewrite was needed",
            )
        )
        return findings, False

    timestamp = _current_snapshot_timestamp()
    snapshot_dir_rel = _lifecycle_markdown_frontmatter_snapshot_dir(changed_plans, timestamp)
    snapshot_dir = inventory.root / snapshot_dir_rel
    metadata_rel = f"{snapshot_dir_rel}/snapshot.json"
    diagnostics_by_path = _lifecycle_frontmatter_diagnostics_by_source(validation)
    metadata = _lifecycle_markdown_frontmatter_snapshot_metadata(
        inventory,
        timestamp,
        snapshot_dir_rel,
        changed_plans,
        diagnostics_by_path,
    )
    operations: list[AtomicFileWrite] = []
    for plan in changed_plans:
        target = inventory.root / plan.rel_path
        copy_path = inventory.root / _lifecycle_markdown_frontmatter_copy_rel(snapshot_dir_rel, plan.rel_path)
        operations.append(_lifecycle_frontmatter_atomic_write(copy_path, plan.current_text))
        operations.append(_lifecycle_frontmatter_atomic_write(target, plan.updated_text))
    operations.append(_lifecycle_frontmatter_atomic_write(inventory.root / metadata_rel, json.dumps(metadata, indent=2, sort_keys=True) + "\n"))

    try:
        cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
    except FileTransactionError as exc:
        return [
            Finding(
                "error",
                "lifecycle-frontmatter-refused",
                f"snapshot-protected lifecycle frontmatter repair failed before target mutation completed: {exc}",
                changed_plans[0].rel_path,
            )
        ], False

    findings.append(
        Finding(
            "info",
            "snapshot-created",
            f"created repair snapshot before lifecycle frontmatter mutation: {snapshot_dir_rel}/",
            changed_plans[0].rel_path,
        )
    )
    for plan in changed_plans:
        copy_rel = _lifecycle_markdown_frontmatter_copy_rel(snapshot_dir_rel, plan.rel_path)
        findings.extend(
            [
                Finding("info", "snapshot-copied-file", f"copied pre-repair bytes to {copy_rel}", plan.rel_path),
                Finding(
                    "info",
                    "lifecycle-frontmatter-updated",
                    f"prepended canonical route frontmatter keys: {', '.join(plan.fields)}",
                    plan.rel_path,
                ),
            ]
        )
    findings.extend(_lifecycle_markdown_frontmatter_route_write_findings(changed_plans, apply=True))
    findings.extend(
        [
            Finding("info", "snapshot-metadata-written", f"wrote snapshot metadata: {metadata_rel}", changed_plans[0].rel_path),
            Finding(
                "info",
                "lifecycle-frontmatter-rollback",
                f"manual rollback only: copy files from {snapshot_dir_rel}/files/ back to matching repo paths; then run validate and audit-links",
                changed_plans[0].rel_path,
            ),
            Finding(
                "info",
                "lifecycle-frontmatter-authority",
                "snapshot metadata and repair-added frontmatter are safety/routing evidence only and cannot approve closeout, archive, commit, lifecycle decisions, truth selection, or future repairs",
                changed_plans[0].rel_path,
            ),
        ]
    )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "repair-cleanup-warning", warning, changed_plans[0].rel_path))
    return findings, True


def _lifecycle_source_provenance_apply_preflight_errors(inventory: Inventory) -> list[Finding]:
    candidates = _lifecycle_source_provenance_candidate_rows(inventory)
    if not candidates:
        return []
    for surface, _plan in candidates:
        target_conflict = _snapshot_target_conflict(inventory.root, surface.rel_path)
        if target_conflict:
            return [_lifecycle_source_provenance_refusal_from(target_conflict)]
        if surface.read_error:
            return [
                Finding(
                    "error",
                    "lifecycle-source-provenance-refused",
                    f"target file could not be read as clean UTF-8 before lifecycle source-provenance repair: {surface.read_error}",
                    surface.rel_path,
                )
            ]
        if surface.frontmatter.errors:
            return [
                Finding(
                    "error",
                    "lifecycle-source-provenance-refused",
                    "target has malformed frontmatter; repair refuses to guess metadata boundaries",
                    surface.rel_path,
                )
            ]
    snapshot_dir = _lifecycle_source_provenance_snapshot_dir([plan for _surface, plan in candidates], _current_snapshot_timestamp())
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        return [_lifecycle_source_provenance_refusal_from(boundary_conflict)]
    return []


def _lifecycle_source_provenance_apply_findings(inventory: Inventory) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "lifecycle-source-provenance-apply-scope",
            f"selected repair class: {LIFECYCLE_SOURCE_PROVENANCE_REPAIR_CLASS}; target route files: lifecycle markdown with deprecated transport-level source provenance",
        )
    ]
    candidates = _lifecycle_source_provenance_candidate_rows(inventory)
    if not candidates:
        findings.append(
            Finding(
                "info",
                "lifecycle-source-provenance-apply-skipped",
                "no deprecated lifecycle source provenance required normalization",
            )
        )
        return findings, False

    plans = [plan for _surface, plan in candidates]
    changed_plans = [plan for plan in plans if plan.current_text != plan.updated_text]
    if not changed_plans:
        findings.append(
            Finding(
                "info",
                "lifecycle-source-provenance-apply-skipped",
                "planned lifecycle source provenance already matched current files; no snapshot or rewrite was needed",
            )
        )
        return findings, False

    timestamp = _current_snapshot_timestamp()
    snapshot_dir_rel = _lifecycle_source_provenance_snapshot_dir(changed_plans, timestamp)
    metadata_rel = f"{snapshot_dir_rel}/snapshot.json"
    metadata = _lifecycle_source_provenance_snapshot_metadata(inventory, timestamp, snapshot_dir_rel, changed_plans)
    operations: list[AtomicFileWrite] = []
    for plan in changed_plans:
        target = inventory.root / plan.rel_path
        copy_path = inventory.root / _lifecycle_source_provenance_copy_rel(snapshot_dir_rel, plan.rel_path)
        operations.append(_lifecycle_frontmatter_atomic_write(copy_path, plan.current_text))
        operations.append(_lifecycle_frontmatter_atomic_write(target, plan.updated_text))
    operations.append(_lifecycle_frontmatter_atomic_write(inventory.root / metadata_rel, json.dumps(metadata, indent=2, sort_keys=True) + "\n"))

    try:
        cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
    except FileTransactionError as exc:
        return [
            Finding(
                "error",
                "lifecycle-source-provenance-refused",
                f"snapshot-protected lifecycle source-provenance repair failed before target mutation completed: {exc}",
                changed_plans[0].rel_path,
            )
        ], False

    findings.append(
        Finding(
            "info",
            "snapshot-created",
            f"created repair snapshot before lifecycle source-provenance mutation: {snapshot_dir_rel}/",
            changed_plans[0].rel_path,
        )
    )
    for plan in changed_plans:
        copy_rel = _lifecycle_source_provenance_copy_rel(snapshot_dir_rel, plan.rel_path)
        findings.extend(
            [
                Finding("info", "snapshot-copied-file", f"copied pre-repair bytes to {copy_rel}", plan.rel_path),
                Finding(
                    "info",
                    "lifecycle-source-provenance-updated",
                    f"normalized lifecycle source provenance: {plan.fields['source']}",
                    plan.rel_path,
                ),
            ]
        )
    findings.extend(_lifecycle_source_provenance_route_write_findings(changed_plans, apply=True))
    findings.extend(
        [
            Finding("info", "snapshot-metadata-written", f"wrote snapshot metadata: {metadata_rel}", changed_plans[0].rel_path),
            Finding(
                "info",
                "lifecycle-source-provenance-rollback",
                f"manual rollback only: copy files from {snapshot_dir_rel}/files/ back to matching repo paths; then run validate and audit-links",
                changed_plans[0].rel_path,
            ),
            Finding(
                "info",
                "lifecycle-source-provenance-authority",
                "snapshot metadata and repair-normalized source provenance are safety/routing evidence only and cannot approve closeout, archive, commit, lifecycle decisions, truth selection, or future repairs",
                changed_plans[0].rel_path,
            ),
        ]
    )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "repair-cleanup-warning", warning, changed_plans[0].rel_path))
    return findings, True


def _spec_posture_frontmatter_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    candidates = _spec_posture_frontmatter_candidate_rows(inventory, validation)
    if not candidates:
        return []
    refusal = _spec_posture_frontmatter_candidate_refusal(inventory, candidates, severity="error")
    if refusal:
        return [refusal]
    snapshot_dir = _spec_posture_frontmatter_snapshot_dir([plan for _surface, _diagnostics, plan in candidates], _current_snapshot_timestamp())
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        return [_spec_posture_frontmatter_refusal_from(boundary_conflict)]
    return []


def _spec_posture_frontmatter_apply_findings(
    inventory: Inventory,
    validation: list[Finding],
) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "spec-posture-frontmatter-apply-scope",
            f"selected repair class: {SPEC_POSTURE_FRONTMATTER_REPAIR_CLASS}; target route files: plan-facing specs and docs/specs contracts missing only spec posture metadata",
        )
    ]
    candidates = _spec_posture_frontmatter_candidate_rows(inventory, validation)
    if not candidates:
        findings.append(
            Finding(
                "info",
                "spec-posture-frontmatter-apply-skipped",
                "no plan-facing spec posture diagnostics required snapshot-protected repair",
            )
        )
        return findings, False

    plans = [plan for _surface, _diagnostics, plan in candidates]
    changed_plans = [plan for plan in plans if plan.current_text != plan.updated_text]
    if not changed_plans:
        findings.append(
            Finding(
                "info",
                "spec-posture-frontmatter-apply-skipped",
                "planned spec posture frontmatter already matched current files; no snapshot or rewrite was needed",
            )
        )
        return findings, False

    timestamp = _current_snapshot_timestamp()
    snapshot_dir_rel = _spec_posture_frontmatter_snapshot_dir(changed_plans, timestamp)
    metadata_rel = f"{snapshot_dir_rel}/snapshot.json"
    diagnostics_by_path = _spec_posture_frontmatter_diagnostics_by_source(validation)
    metadata = _spec_posture_frontmatter_snapshot_metadata(
        inventory,
        timestamp,
        snapshot_dir_rel,
        changed_plans,
        diagnostics_by_path,
    )
    operations: list[AtomicFileWrite] = []
    for plan in changed_plans:
        target = inventory.root / plan.rel_path
        copy_path = inventory.root / _lifecycle_markdown_frontmatter_copy_rel(snapshot_dir_rel, plan.rel_path)
        operations.append(_lifecycle_frontmatter_atomic_write(copy_path, plan.current_text))
        operations.append(_lifecycle_frontmatter_atomic_write(target, plan.updated_text))
    operations.append(_lifecycle_frontmatter_atomic_write(inventory.root / metadata_rel, json.dumps(metadata, indent=2, sort_keys=True) + "\n"))

    try:
        cleanup_warnings = apply_file_transaction(operations, root=inventory.root)
    except FileTransactionError as exc:
        return [
            Finding(
                "error",
                "spec-posture-frontmatter-refused",
                f"snapshot-protected spec posture frontmatter repair failed before target mutation completed: {exc}",
                changed_plans[0].rel_path,
            )
        ], False

    findings.append(
        Finding(
            "info",
            "snapshot-created",
            f"created repair snapshot before spec posture frontmatter mutation: {snapshot_dir_rel}/",
            changed_plans[0].rel_path,
        )
    )
    for plan in changed_plans:
        copy_rel = _lifecycle_markdown_frontmatter_copy_rel(snapshot_dir_rel, plan.rel_path)
        findings.extend(
            [
                Finding("info", "snapshot-copied-file", f"copied pre-repair bytes to {copy_rel}", plan.rel_path),
                Finding(
                    "info",
                    "spec-posture-frontmatter-updated",
                    f"added missing spec posture frontmatter keys: {', '.join(plan.fields)}",
                    plan.rel_path,
                ),
            ]
        )
    findings.extend(_spec_posture_frontmatter_route_write_findings(changed_plans, apply=True))
    findings.extend(
        [
            Finding("info", "snapshot-metadata-written", f"wrote snapshot metadata: {metadata_rel}", changed_plans[0].rel_path),
            Finding(
                "info",
                "spec-posture-frontmatter-rollback",
                f"manual rollback only: copy files from {snapshot_dir_rel}/files/ back to matching repo paths; then run validate and audit-links",
                changed_plans[0].rel_path,
            ),
            Finding(
                "info",
                "spec-posture-frontmatter-authority",
                "snapshot metadata and repair-added spec posture frontmatter are metadata evidence only and cannot approve closeout, archive, commit, lifecycle decisions, truth selection, or future repairs",
                changed_plans[0].rel_path,
            ),
        ]
    )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "repair-cleanup-warning", warning, changed_plans[0].rel_path))
    return findings, True


def _docmap_create_target_conflict(root: Path) -> Finding | None:
    target_path = root / DOCMAP_REPAIR_TARGET_REL
    for candidate in _root_relative_path_chain(root, DOCMAP_REPAIR_TARGET_REL):
        candidate_rel = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            return Finding("warn", "docmap-create-refused", f"target path contains a symlink segment: {candidate_rel}", candidate_rel)
        if candidate.exists() and candidate != target_path and not candidate.is_dir():
            return Finding("warn", "docmap-create-refused", f"target path contains a non-directory segment: {candidate_rel}", candidate_rel)
    if target_path.exists() and not target_path.is_file():
        return Finding("warn", "docmap-create-refused", f"target path is not a regular file: {DOCMAP_REPAIR_TARGET_REL}", DOCMAP_REPAIR_TARGET_REL)
    try:
        target_path.resolve().relative_to(root.resolve())
    except ValueError:
        return Finding("warn", "docmap-create-refused", f"target path would escape the target root: {DOCMAP_REPAIR_TARGET_REL}", DOCMAP_REPAIR_TARGET_REL)
    return None


def _docmap_create_route_entries(inventory: Inventory) -> list[str]:
    expected = [
        "README.md",
        "AGENTS.md",
        _selected_manifest_rel(inventory),
        "project/project-state.md",
        "project/specs/workflow/",
    ]
    for rel in ("docs/README.md", "docs/architecture/", "docs/specs/", "pyproject.toml", "src/mylittleharness/", "tests/"):
        if (inventory.root / rel).exists():
            expected.append(rel)
    state = inventory.state
    plan_status = state.frontmatter.data.get("plan_status") if state and state.exists else None
    active_plan = inventory.active_plan_surface
    if plan_status == "active" or (active_plan and active_plan.exists):
        expected.append("project/implementation-plan.md")
    return expected


def _docmap_create_content(route_entries: list[str]) -> str:
    return (
        "version: 2\n"
        "repo_summary:\n"
        "  product_docs_entrypoints:\n"
        + "".join(f'    - "{_yaml_double_quoted_value(entry)}"\n' for entry in route_entries)
    )


def _docmap_route_diagnostics(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    audit = audit_link_findings(inventory)
    candidates = validation + audit
    return [
        finding
        for finding in candidates
        if finding.code in {"docmap-routing", "candidate-docmap-gap"} and finding.source == DOCMAP_REPAIR_TARGET_REL
    ]


def _docmap_route_entries_from_diagnostics(findings: list[Finding]) -> list[str]:
    entries: list[str] = []
    prefixes = ("docmap does not mention ", "candidate route missing from docmap: ")
    for finding in findings:
        for prefix in prefixes:
            if finding.message.startswith(prefix):
                entry = finding.message[len(prefix) :].strip()
                if entry and entry not in entries:
                    entries.append(entry)
                break
    return entries


def _docmap_snapshot_preview_dir(target: Path, route_entries: list[str]) -> str:
    return _docmap_snapshot_dir(target, route_entries, SNAPSHOT_DRY_RUN_TIMESTAMP)


def _docmap_snapshot_dir(target: Path, route_entries: list[str], timestamp: str) -> str:
    content = target.read_text(encoding="utf-8", errors="replace") if target.exists() and target.is_file() else ""
    payload = "\n".join([DOCMAP_REPAIR_CLASS, DOCMAP_REPAIR_TARGET_REL, content, *route_entries])
    hash_prefix = hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{SNAPSHOT_REPAIR_ROOT_REL}/{timestamp}-{DOCMAP_REPAIR_CLASS}-{DOCMAP_REPAIR_TARGET_SLUG}-{hash_prefix}"


def _docmap_snapshot_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    target_conflict = _snapshot_target_conflict(inventory.root, DOCMAP_REPAIR_TARGET_REL)
    if target_conflict:
        return [_error_from_snapshot_refusal(target_conflict)]

    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    if not target.exists():
        return []

    docmap = inventory.surface_by_rel.get(DOCMAP_REPAIR_TARGET_REL)
    if docmap and docmap.read_error:
        return [
            Finding(
                "error",
                "snapshot-apply-refused",
                f"target file could not be read as clean UTF-8 before snapshot-protected repair: {docmap.read_error}",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ]

    route_diagnostics = _docmap_route_diagnostics(inventory, validation)
    if not route_diagnostics:
        return []
    route_entries = _docmap_route_entries_from_diagnostics(route_diagnostics)
    if not route_entries:
        return [
            Finding(
                "error",
                "snapshot-apply-refused",
                "docmap route diagnostics did not produce deterministic route entries",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ]
    snapshot_dir = _docmap_snapshot_dir(target, route_entries, _current_snapshot_timestamp())
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        return [_error_from_snapshot_refusal(boundary_conflict)]
    return []


def _docmap_snapshot_apply_findings(inventory: Inventory, validation: list[Finding]) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "snapshot-apply-scope",
            f"selected repair class: {DOCMAP_REPAIR_CLASS}; target file: {DOCMAP_REPAIR_TARGET_REL}",
            DOCMAP_REPAIR_TARGET_REL,
        )
    ]
    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    if not target.exists():
        findings.append(
            Finding(
                "info",
                "snapshot-apply-skipped",
                f"target file is absent: {DOCMAP_REPAIR_TARGET_REL}; absent docmap remains a create-only/bootstrap question",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings, False

    route_diagnostics = _docmap_route_diagnostics(inventory, validation)
    if not route_diagnostics:
        findings.append(
            Finding(
                "info",
                "snapshot-apply-skipped",
                f"no {DOCMAP_REPAIR_TARGET_REL} route diagnostics require snapshot-protected repair",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings, False

    route_entries = _docmap_route_entries_from_diagnostics(route_diagnostics)
    timestamp = _current_snapshot_timestamp()
    snapshot_dir_rel = _docmap_snapshot_dir(target, route_entries, timestamp)
    snapshot_dir = inventory.root / snapshot_dir_rel
    copy_rel = f"{snapshot_dir_rel}/{DOCMAP_REPAIR_COPY_REL}"
    copy_path = inventory.root / copy_rel
    metadata_rel = f"{snapshot_dir_rel}/snapshot.json"
    metadata_path = inventory.root / metadata_rel

    try:
        pre_repair_bytes = target.read_bytes()
        pre_repair_text = pre_repair_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [
            Finding(
                "error",
                "snapshot-apply-refused",
                f"target file could not be decoded as UTF-8 before snapshot-protected repair: {exc}",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ], False
    except OSError as exc:
        return [
            Finding(
                "error",
                "snapshot-apply-refused",
                f"target file could not be read before snapshot-protected repair: {exc}",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ], False

    repaired_text = _docmap_text_with_route_entries(pre_repair_text, route_entries)
    if repaired_text == pre_repair_text:
        findings.append(
            Finding(
                "info",
                "snapshot-apply-skipped",
                "planned docmap route entries were already present; no snapshot or docmap rewrite was needed",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings, False

    metadata = _docmap_snapshot_metadata(
        inventory,
        timestamp,
        snapshot_dir_rel,
        copy_rel,
        route_entries,
        route_diagnostics,
        pre_repair_bytes,
    )

    try:
        snapshot_dir.mkdir(parents=True, exist_ok=False)
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        copy_path.write_bytes(pre_repair_bytes)
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        target.write_bytes(repaired_text.encode("utf-8"))
    except OSError as exc:
        return [
            Finding(
                "error",
                "snapshot-apply-refused",
                f"snapshot-protected docmap repair failed before target mutation completed: {exc}",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ], False

    route_summary = ", ".join(route_entries)
    findings.extend(
        [
            Finding(
                "info",
                "snapshot-created",
                f"created repair snapshot before docmap mutation: {snapshot_dir_rel}/",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-copied-file",
                f"copied pre-repair bytes to {copy_rel}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-metadata-written",
                f"wrote snapshot metadata: {metadata_rel}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "repair-docmap-updated",
                f"updated docmap route entries: {route_summary}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-rollback",
                f"manual rollback only: copy {copy_rel} back to {DOCMAP_REPAIR_TARGET_REL}; then run validate and audit-links",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-authority",
                "snapshot metadata is safety evidence only and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                DOCMAP_REPAIR_TARGET_REL,
            ),
        ]
    )
    return findings, True


def _lifecycle_markdown_frontmatter_candidate_rows(
    inventory: Inventory,
    validation: list[Finding],
) -> list[tuple[Surface, list[Finding], LifecycleMarkdownFrontmatterPlan]]:
    diagnostics_by_path = _lifecycle_frontmatter_diagnostics_by_source(validation)
    rows: list[tuple[Surface, list[Finding], LifecycleMarkdownFrontmatterPlan]] = []
    for surface in sorted(inventory.present_surfaces, key=lambda item: item.rel_path):
        diagnostics = diagnostics_by_path.get(surface.rel_path)
        if not diagnostics:
            continue
        if surface.frontmatter.has_frontmatter:
            continue
        if not lifecycle_markdown_requires_frontmatter(surface):
            continue
        rows.append((surface, diagnostics, lifecycle_markdown_frontmatter_plan(surface)))
    return rows


def _lifecycle_frontmatter_diagnostics_by_source(validation: list[Finding]) -> dict[str, list[Finding]]:
    diagnostics_by_path: dict[str, list[Finding]] = {}
    for finding in validation:
        if finding.code not in {"research-frontmatter", "lifecycle-frontmatter"} or not finding.source:
            continue
        diagnostics_by_path.setdefault(finding.source, []).append(finding)
    return diagnostics_by_path


def _lifecycle_markdown_frontmatter_snapshot_dir(plans: list[LifecycleMarkdownFrontmatterPlan], timestamp: str) -> str:
    payload_parts: list[bytes] = [LIFECYCLE_MARKDOWN_FRONTMATTER_REPAIR_CLASS.encode("utf-8")]
    for plan in sorted(plans, key=lambda item: item.rel_path):
        payload_parts.extend(
            [
                plan.rel_path.encode("utf-8"),
                plan.route_id.encode("utf-8"),
                "\n".join(plan.fields).encode("utf-8"),
                plan.current_text.encode("utf-8"),
                plan.updated_text.encode("utf-8"),
            ]
        )
    hash_prefix = hashlib.sha256(b"\n".join(payload_parts)).hexdigest()[:12]
    count = len(plans)
    return f"{SNAPSHOT_REPAIR_ROOT_REL}/{timestamp}-{LIFECYCLE_MARKDOWN_FRONTMATTER_REPAIR_CLASS}-{count}-files-{hash_prefix}"


def _lifecycle_markdown_frontmatter_snapshot_metadata(
    inventory: Inventory,
    timestamp: str,
    snapshot_dir_rel: str,
    plans: list[LifecycleMarkdownFrontmatterPlan],
    diagnostics_by_path: dict[str, list[Finding]],
) -> dict[str, object]:
    copied_files = []
    pre_repair_hashes: dict[str, str] = {}
    source_diagnostics: list[dict[str, object]] = []
    planned_keys: dict[str, list[str]] = {}
    target_paths = [plan.rel_path for plan in plans]
    for plan in plans:
        pre_repair_bytes = plan.current_text.encode("utf-8")
        digest = hashlib.sha256(pre_repair_bytes).hexdigest()
        copy_rel = _lifecycle_markdown_frontmatter_copy_rel(snapshot_dir_rel, plan.rel_path)
        copied_files.append(
            {
                "target_path": plan.rel_path,
                "snapshot_path": copy_rel,
                "sha256": digest,
                "byte_count": len(pre_repair_bytes),
            }
        )
        pre_repair_hashes[plan.rel_path] = digest
        planned_keys[plan.rel_path] = list(plan.fields)
        for diagnostic in diagnostics_by_path.get(plan.rel_path, []):
            source_diagnostics.append(
                {
                    "code": diagnostic.code,
                    "message": diagnostic.message,
                    "source": diagnostic.source,
                    "line": diagnostic.line,
                }
            )
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at_utc": timestamp,
        "tool_name": "mylittleharness",
        "tool_version": __version__,
        "command": "repair --apply",
        "root_kind": inventory.root_kind,
        "repair_class": LIFECYCLE_MARKDOWN_FRONTMATTER_REPAIR_CLASS,
        "target_root": str(inventory.root),
        "snapshot_root": snapshot_dir_rel,
        "target_paths": target_paths,
        "copied_files": copied_files,
        "pre_repair_hashes": pre_repair_hashes,
        "planned_post_repair_paths": target_paths,
        "source_diagnostics": source_diagnostics,
        "planned_route_entries": [],
        "planned_frontmatter_keys_by_path": planned_keys,
        "retention": "manual; MyLittleHarness does not silently delete, rotate, compress, move, or hide repair snapshots",
        "rollback_instructions": (
            f"Copy files from {snapshot_dir_rel}/files/ back to matching repo paths, then run "
            "python -m mylittleharness --root <target-root> validate and "
            "python -m mylittleharness --root <target-root> audit-links."
        ),
        "authority_note": (
            "snapshot metadata and repair-added frontmatter are safety/routing evidence only and cannot approve repair, "
            "truth selection, closeout, archive, commit, lifecycle decisions, or future repairs"
        ),
    }


def _lifecycle_markdown_frontmatter_copy_rel(snapshot_dir_rel: str, rel_path: str) -> str:
    return _repair_snapshot_copy_rel(snapshot_dir_rel, rel_path)


def _repair_snapshot_copy_rel(snapshot_dir_rel: str, rel_path: str) -> str:
    digest = hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:16]
    suffix = Path(rel_path).suffix or ".txt"
    return f"{snapshot_dir_rel}/files/by-hash/{digest}{suffix}"


def _lifecycle_frontmatter_atomic_write(path: Path, text: str) -> AtomicFileWrite:
    sidecar_id = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    return AtomicFileWrite(
        path,
        path.with_name(f".mlh-{sidecar_id}.tmp"),
        text,
        path.with_name(f".mlh-{sidecar_id}.backup"),
    )


def _lifecycle_markdown_frontmatter_route_write_findings(
    plans: list[LifecycleMarkdownFrontmatterPlan],
    *,
    apply: bool,
) -> list[Finding]:
    writes = tuple(RouteWriteEvidence(plan.rel_path, plan.current_text, plan.updated_text) for plan in plans)
    return route_write_findings("lifecycle-frontmatter-route-write", writes, apply=apply)


def _lifecycle_frontmatter_refusal_from(finding: Finding, severity: str = "error") -> Finding:
    code = "lifecycle-frontmatter-plan-refused" if severity == "warn" else "lifecycle-frontmatter-refused"
    return Finding(severity, code, finding.message, finding.source, finding.line)


def _lifecycle_source_provenance_candidate_rows(
    inventory: Inventory,
) -> list[tuple[Surface, LifecycleMarkdownFrontmatterPlan]]:
    rows: list[tuple[Surface, LifecycleMarkdownFrontmatterPlan]] = []
    for surface in sorted(inventory.present_surfaces, key=lambda item: item.rel_path):
        if surface.frontmatter.errors:
            continue
        plan = lifecycle_markdown_source_provenance_plan(surface)
        if plan is None:
            continue
        rows.append((surface, plan))
    return rows


def _lifecycle_source_provenance_snapshot_dir(plans: list[LifecycleMarkdownFrontmatterPlan], timestamp: str) -> str:
    payload_parts: list[bytes] = [LIFECYCLE_SOURCE_PROVENANCE_REPAIR_CLASS.encode("utf-8")]
    for plan in sorted(plans, key=lambda item: item.rel_path):
        payload_parts.extend(
            [
                plan.rel_path.encode("utf-8"),
                plan.route_id.encode("utf-8"),
                plan.operation.encode("utf-8"),
                "\n".join(f"{key}={value}" for key, value in sorted(plan.fields.items())).encode("utf-8"),
                plan.current_text.encode("utf-8"),
                plan.updated_text.encode("utf-8"),
            ]
        )
    hash_prefix = hashlib.sha256(b"\n".join(payload_parts)).hexdigest()[:12]
    count = len(plans)
    return f"{SNAPSHOT_REPAIR_ROOT_REL}/{timestamp}-{LIFECYCLE_SOURCE_PROVENANCE_REPAIR_CLASS}-{count}-files-{hash_prefix}"


def _lifecycle_source_provenance_snapshot_metadata(
    inventory: Inventory,
    timestamp: str,
    snapshot_dir_rel: str,
    plans: list[LifecycleMarkdownFrontmatterPlan],
) -> dict[str, object]:
    copied_files = []
    pre_repair_hashes: dict[str, str] = {}
    planned_keys: dict[str, list[str]] = {}
    planned_values: dict[str, dict[str, str]] = {}
    target_paths = [plan.rel_path for plan in plans]
    for plan in plans:
        pre_repair_bytes = plan.current_text.encode("utf-8")
        digest = hashlib.sha256(pre_repair_bytes).hexdigest()
        copy_rel = _lifecycle_source_provenance_copy_rel(snapshot_dir_rel, plan.rel_path)
        copied_files.append(
            {
                "target_path": plan.rel_path,
                "snapshot_path": copy_rel,
                "sha256": digest,
                "byte_count": len(pre_repair_bytes),
            }
        )
        pre_repair_hashes[plan.rel_path] = digest
        planned_keys[plan.rel_path] = list(plan.fields)
        planned_values[plan.rel_path] = dict(plan.fields)
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at_utc": timestamp,
        "tool_name": "mylittleharness",
        "tool_version": __version__,
        "command": "repair --apply",
        "root_kind": inventory.root_kind,
        "repair_class": LIFECYCLE_SOURCE_PROVENANCE_REPAIR_CLASS,
        "target_root": str(inventory.root),
        "snapshot_root": snapshot_dir_rel,
        "target_paths": target_paths,
        "copied_files": copied_files,
        "pre_repair_hashes": pre_repair_hashes,
        "planned_post_repair_paths": target_paths,
        "source_diagnostics": [],
        "planned_route_entries": [],
        "planned_frontmatter_keys_by_path": planned_keys,
        "planned_frontmatter_values_by_path": planned_values,
        "retention": "manual; MyLittleHarness does not silently delete, rotate, compress, move, or hide repair snapshots",
        "rollback_instructions": (
            f"Copy files from {snapshot_dir_rel}/files/ back to matching repo paths, then run "
            "python -m mylittleharness --root <target-root> validate and "
            "python -m mylittleharness --root <target-root> audit-links."
        ),
        "authority_note": (
            "snapshot metadata and repair-normalized source provenance are safety/routing evidence only and cannot approve repair, "
            "truth selection, closeout, archive, commit, lifecycle decisions, or future repairs"
        ),
    }


def _lifecycle_source_provenance_copy_rel(snapshot_dir_rel: str, rel_path: str) -> str:
    return _repair_snapshot_copy_rel(snapshot_dir_rel, rel_path)


def _lifecycle_source_provenance_route_write_findings(
    plans: list[LifecycleMarkdownFrontmatterPlan],
    *,
    apply: bool,
) -> list[Finding]:
    writes = tuple(RouteWriteEvidence(plan.rel_path, plan.current_text, plan.updated_text) for plan in plans)
    return route_write_findings("lifecycle-source-provenance-route-write", writes, apply=apply)


def _lifecycle_source_provenance_refusal_from(finding: Finding, severity: str = "error") -> Finding:
    code = "lifecycle-source-provenance-plan-refused" if severity == "warn" else "lifecycle-source-provenance-refused"
    return Finding(severity, code, finding.message, finding.source, finding.line)


def _lifecycle_frontmatter_path_summary(paths: list[str], limit: int = 8) -> str:
    if len(paths) <= limit:
        return ", ".join(paths)
    return ", ".join(paths[:limit]) + f", +{len(paths) - limit} more"


def _spec_posture_frontmatter_candidate_rows(
    inventory: Inventory,
    validation: list[Finding],
) -> list[tuple[Surface, list[Finding], SpecPostureFrontmatterPlan]]:
    diagnostics_by_path = _spec_posture_frontmatter_diagnostics_by_source(validation)
    rows: list[tuple[Surface, list[Finding], SpecPostureFrontmatterPlan]] = []
    for surface in sorted(inventory.present_surfaces, key=lambda item: item.rel_path):
        diagnostics = diagnostics_by_path.get(surface.rel_path)
        if not diagnostics:
            continue
        if not _is_spec_lifecycle_surface(surface):
            continue
        if surface.frontmatter.errors:
            continue
        if lifecycle_markdown_requires_frontmatter(surface) and not surface.frontmatter.has_frontmatter:
            continue
        fields = _missing_spec_posture_frontmatter_fields(surface)
        if not fields:
            continue
        rows.append((surface, diagnostics, _spec_posture_frontmatter_plan(surface, fields)))
    return rows


def _spec_posture_frontmatter_diagnostics_by_source(validation: list[Finding]) -> dict[str, list[Finding]]:
    diagnostics_by_path: dict[str, list[Finding]] = {}
    for finding in validation:
        if finding.code != "spec-posture-missing" or not finding.source:
            continue
        diagnostics_by_path.setdefault(finding.source, []).append(finding)
    return diagnostics_by_path


def _missing_spec_posture_frontmatter_fields(surface: Surface) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, default in SPEC_POSTURE_REPAIR_DEFAULTS.items():
        if not surface.frontmatter.has_frontmatter or not _frontmatter_value_present(surface.frontmatter.data.get(key)):
            fields[key] = default
    return fields


def _spec_posture_frontmatter_plan(surface: Surface, fields: dict[str, str]) -> SpecPostureFrontmatterPlan:
    updated_text = _spec_posture_frontmatter_text(surface.content, fields)
    return SpecPostureFrontmatterPlan(
        rel_path=surface.rel_path,
        route_id=surface.memory_route,
        fields=fields,
        current_text=surface.content,
        updated_text=updated_text,
    )


def _spec_posture_frontmatter_text(text: str, fields: dict[str, str]) -> str:
    if not fields:
        return text
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return lifecycle_markdown_text_with_frontmatter(text, fields)
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            insert_lines = [f'{key}: "{_yaml_double_quoted_value(value)}"\n' for key, value in fields.items()]
            return "".join([*lines[:index], *insert_lines, *lines[index:]])
    return text


def _spec_posture_frontmatter_candidate_refusal(
    inventory: Inventory,
    candidates: list[tuple[Surface, list[Finding], SpecPostureFrontmatterPlan]],
    *,
    severity: str,
) -> Finding | None:
    for surface, _diagnostics, _plan in candidates:
        target_conflict = _snapshot_target_conflict(inventory.root, surface.rel_path)
        if target_conflict:
            return _spec_posture_frontmatter_refusal_from(target_conflict, severity)
        if surface.read_error:
            return Finding(
                severity,
                "spec-posture-frontmatter-plan-refused" if severity == "warn" else "spec-posture-frontmatter-refused",
                f"target file could not be read as clean UTF-8 before spec posture frontmatter repair: {surface.read_error}",
                surface.rel_path,
            )
        if surface.frontmatter.errors:
            return Finding(
                severity,
                "spec-posture-frontmatter-plan-refused" if severity == "warn" else "spec-posture-frontmatter-refused",
                "target has malformed frontmatter; repair refuses to guess metadata boundaries",
                surface.rel_path,
            )
    return None


def _spec_posture_frontmatter_snapshot_dir(plans: list[SpecPostureFrontmatterPlan], timestamp: str) -> str:
    payload_parts: list[bytes] = [SPEC_POSTURE_FRONTMATTER_REPAIR_CLASS.encode("utf-8")]
    for plan in sorted(plans, key=lambda item: item.rel_path):
        payload_parts.extend(
            [
                plan.rel_path.encode("utf-8"),
                plan.route_id.encode("utf-8"),
                "\n".join(plan.fields).encode("utf-8"),
                plan.current_text.encode("utf-8"),
                plan.updated_text.encode("utf-8"),
            ]
        )
    hash_prefix = hashlib.sha256(b"\n".join(payload_parts)).hexdigest()[:12]
    count = len(plans)
    return f"{SNAPSHOT_REPAIR_ROOT_REL}/{timestamp}-{SPEC_POSTURE_FRONTMATTER_REPAIR_CLASS}-{count}-files-{hash_prefix}"


def _spec_posture_frontmatter_snapshot_metadata(
    inventory: Inventory,
    timestamp: str,
    snapshot_dir_rel: str,
    plans: list[SpecPostureFrontmatterPlan],
    diagnostics_by_path: dict[str, list[Finding]],
) -> dict[str, object]:
    copied_files = []
    pre_repair_hashes: dict[str, str] = {}
    source_diagnostics: list[dict[str, object]] = []
    planned_keys: dict[str, list[str]] = {}
    target_paths = [plan.rel_path for plan in plans]
    for plan in plans:
        pre_repair_bytes = plan.current_text.encode("utf-8")
        digest = hashlib.sha256(pre_repair_bytes).hexdigest()
        copy_rel = _lifecycle_markdown_frontmatter_copy_rel(snapshot_dir_rel, plan.rel_path)
        copied_files.append(
            {
                "target_path": plan.rel_path,
                "snapshot_path": copy_rel,
                "sha256": digest,
                "byte_count": len(pre_repair_bytes),
            }
        )
        pre_repair_hashes[plan.rel_path] = digest
        planned_keys[plan.rel_path] = list(plan.fields)
        for diagnostic in diagnostics_by_path.get(plan.rel_path, []):
            source_diagnostics.append(
                {
                    "code": diagnostic.code,
                    "message": diagnostic.message,
                    "source": diagnostic.source,
                    "line": diagnostic.line,
                }
            )
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at_utc": timestamp,
        "tool_name": "mylittleharness",
        "tool_version": __version__,
        "command": "repair --apply",
        "root_kind": inventory.root_kind,
        "repair_class": SPEC_POSTURE_FRONTMATTER_REPAIR_CLASS,
        "target_root": str(inventory.root),
        "snapshot_root": snapshot_dir_rel,
        "target_paths": target_paths,
        "copied_files": copied_files,
        "pre_repair_hashes": pre_repair_hashes,
        "planned_post_repair_paths": target_paths,
        "source_diagnostics": source_diagnostics,
        "planned_route_entries": [],
        "planned_frontmatter_keys_by_path": planned_keys,
        "retention": "manual; MyLittleHarness does not silently delete, rotate, compress, move, or hide repair snapshots",
        "rollback_instructions": (
            f"Copy files from {snapshot_dir_rel}/files/ back to matching repo paths, then run "
            "python -m mylittleharness --root <target-root> validate and "
            "python -m mylittleharness --root <target-root> audit-links."
        ),
        "authority_note": (
            "snapshot metadata and repair-added spec posture frontmatter are metadata evidence only and cannot approve repair, "
            "truth selection, closeout, archive, commit, lifecycle decisions, or future repairs"
        ),
    }


def _spec_posture_frontmatter_route_write_findings(
    plans: list[SpecPostureFrontmatterPlan],
    *,
    apply: bool,
) -> list[Finding]:
    writes = tuple(RouteWriteEvidence(plan.rel_path, plan.current_text, plan.updated_text) for plan in plans)
    return route_write_findings("spec-posture-frontmatter-route-write", writes, apply=apply)


def _spec_posture_frontmatter_refusal_from(finding: Finding, severity: str = "error") -> Finding:
    code = "spec-posture-frontmatter-plan-refused" if severity == "warn" else "spec-posture-frontmatter-refused"
    return Finding(severity, code, finding.message, finding.source, finding.line)


def _current_snapshot_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _error_from_snapshot_refusal(finding: Finding) -> Finding:
    return Finding("error", "snapshot-apply-refused", finding.message, finding.source, finding.line)


def _docmap_text_with_route_entries(text: str, route_entries: list[str]) -> str:
    missing_entries = [entry for entry in route_entries if entry not in text]
    if not missing_entries:
        return text

    lines = text.splitlines(keepends=True)
    if not lines:
        return _docmap_route_block(missing_entries)

    entry_lines = [f'    - "{_yaml_double_quoted_value(entry)}"\n' for entry in missing_entries]
    product_entry_index = _find_line_index(lines, r"^\s{2}product_docs_entrypoints:\s*$")
    if product_entry_index is not None:
        insert_at = product_entry_index + 1
        while insert_at < len(lines):
            line = lines[insert_at]
            if line.strip() and not line.startswith("    "):
                break
            insert_at += 1
        return "".join(lines[:insert_at] + entry_lines + lines[insert_at:])

    repo_summary_index = _find_line_index(lines, r"^repo_summary:\s*$")
    if repo_summary_index is not None:
        insert_at = repo_summary_index + 1
        block = ["  product_docs_entrypoints:\n"] + entry_lines
        return "".join(lines[:insert_at] + block + lines[insert_at:])

    separator = "" if text.endswith(("\n", "\r")) else "\n"
    return text + separator + "\n" + _docmap_route_block(missing_entries)


def _find_line_index(lines: list[str], pattern: str) -> int | None:
    compiled = re.compile(pattern)
    for index, line in enumerate(lines):
        if compiled.match(line.rstrip("\r\n")):
            return index
    return None


def _docmap_route_block(route_entries: list[str]) -> str:
    entries = "".join(f'    - "{_yaml_double_quoted_value(entry)}"\n' for entry in route_entries)
    return "repo_summary:\n  product_docs_entrypoints:\n" + entries


def _yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _state_frontmatter_fields(inventory: Inventory) -> dict[str, str]:
    state = inventory.state
    data = state.frontmatter.data if state else {}
    plan_status = str(data.get("plan_status") or "")
    manifest_plan = str(inventory.manifest.get("memory", {}).get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
    fields = {
        "project": _state_frontmatter_project_name(inventory),
        "workflow": "workflow-core",
        "operating_mode": str(data.get("operating_mode") or ""),
        "plan_status": plan_status,
        "active_plan": str(data.get("active_plan") or (manifest_plan if plan_status == "active" else "")),
    }
    for key in STATE_FRONTMATTER_OPTIONAL_KEYS:
        value = data.get(key)
        if value not in (None, ""):
            fields[key] = str(value)
    return fields


def _state_frontmatter_project_name(inventory: Inventory) -> str:
    state = inventory.state
    data = state.frontmatter.data if state else {}
    if data.get("project"):
        return str(data["project"])
    if state:
        for heading in state.headings:
            if heading.level != 1:
                continue
            title = heading.title.strip()
            for suffix in (" Project State", " State"):
                if title.endswith(suffix) and len(title) > len(suffix):
                    return title[: -len(suffix)]
            if title:
                return title
    return inventory.root.name


def _state_frontmatter_text(fields: dict[str, str]) -> str:
    body = "".join(f'{key}: "{_yaml_double_quoted_value(value)}"\n' for key, value in fields.items())
    return f"---\n{body}---\n"


def _state_frontmatter_snapshot_dir(target: Path, frontmatter_text: str, timestamp: str) -> str:
    content = target.read_bytes() if target.exists() and target.is_file() else b""
    payload = b"\n".join(
        [
            STATE_FRONTMATTER_REPAIR_CLASS.encode("utf-8"),
            STATE_FRONTMATTER_TARGET_REL.encode("utf-8"),
            frontmatter_text.encode("utf-8"),
            content,
        ]
    )
    hash_prefix = hashlib.sha256(payload).hexdigest()[:12]
    return f"{SNAPSHOT_REPAIR_ROOT_REL}/{timestamp}-{STATE_FRONTMATTER_REPAIR_CLASS}-{STATE_FRONTMATTER_TARGET_SLUG}-{hash_prefix}"


def _state_frontmatter_snapshot_metadata(
    inventory: Inventory,
    timestamp: str,
    snapshot_dir_rel: str,
    copy_rel: str,
    planned_keys: list[str],
    diagnostic: Finding,
    pre_repair_bytes: bytes,
) -> dict[str, object]:
    digest = hashlib.sha256(pre_repair_bytes).hexdigest()
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at_utc": timestamp,
        "tool_name": "mylittleharness",
        "tool_version": __version__,
        "command": "repair --apply",
        "root_kind": inventory.root_kind,
        "repair_class": STATE_FRONTMATTER_REPAIR_CLASS,
        "target_root": str(inventory.root),
        "snapshot_root": snapshot_dir_rel,
        "target_paths": [STATE_FRONTMATTER_TARGET_REL],
        "copied_files": [
            {
                "target_path": STATE_FRONTMATTER_TARGET_REL,
                "snapshot_path": copy_rel,
                "sha256": digest,
                "byte_count": len(pre_repair_bytes),
            }
        ],
        "pre_repair_hashes": {STATE_FRONTMATTER_TARGET_REL: digest},
        "planned_post_repair_paths": [STATE_FRONTMATTER_TARGET_REL],
        "source_diagnostics": [
            {
                "code": diagnostic.code,
                "message": diagnostic.message,
                "source": diagnostic.source,
                "line": diagnostic.line,
            }
        ],
        "planned_route_entries": [],
        "planned_frontmatter_keys": planned_keys,
        "retention": "manual; MyLittleHarness does not silently delete, rotate, compress, move, or hide repair snapshots",
        "rollback_instructions": (
            f"Copy {copy_rel} back to {STATE_FRONTMATTER_TARGET_REL}, then run "
            "python -m mylittleharness --root <target-root> validate and "
            "python -m mylittleharness --root <target-root> audit-links."
        ),
        "authority_note": (
            "snapshot metadata is safety evidence only and cannot approve repair, closeout, archive, commit, "
            "lifecycle decisions, or future repairs"
        ),
    }


def _docmap_snapshot_metadata(
    inventory: Inventory,
    timestamp: str,
    snapshot_dir_rel: str,
    copy_rel: str,
    route_entries: list[str],
    route_diagnostics: list[Finding],
    pre_repair_bytes: bytes,
) -> dict[str, object]:
    digest = hashlib.sha256(pre_repair_bytes).hexdigest()
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at_utc": timestamp,
        "tool_name": "mylittleharness",
        "tool_version": __version__,
        "command": "repair --apply",
        "root_kind": inventory.root_kind,
        "repair_class": DOCMAP_REPAIR_CLASS,
        "target_root": str(inventory.root),
        "snapshot_root": snapshot_dir_rel,
        "target_paths": [DOCMAP_REPAIR_TARGET_REL],
        "copied_files": [
            {
                "target_path": DOCMAP_REPAIR_TARGET_REL,
                "snapshot_path": copy_rel,
                "sha256": digest,
                "byte_count": len(pre_repair_bytes),
            }
        ],
        "pre_repair_hashes": {DOCMAP_REPAIR_TARGET_REL: digest},
        "planned_post_repair_paths": [DOCMAP_REPAIR_TARGET_REL],
        "source_diagnostics": [
            {
                "code": finding.code,
                "message": finding.message,
                "source": finding.source,
                "line": finding.line,
            }
            for finding in route_diagnostics
        ],
        "planned_route_entries": route_entries,
        "retention": "manual; MyLittleHarness does not silently delete, rotate, compress, move, or hide repair snapshots",
        "rollback_instructions": (
            f"Copy {copy_rel} back to {DOCMAP_REPAIR_TARGET_REL}, then run "
            "python -m mylittleharness --root <target-root> validate and "
            "python -m mylittleharness --root <target-root> audit-links."
        ),
        "authority_note": (
            "snapshot metadata is safety evidence only and cannot approve repair, closeout, archive, commit, "
            "lifecycle decisions, or future repairs"
        ),
    }


def _snapshot_inspect_root_posture_findings(inventory: Inventory) -> list[Finding]:
    snapshot_root = inventory.root / SNAPSHOT_REPAIR_ROOT_REL
    if _is_product_source_inventory(inventory):
        if snapshot_root.exists():
            return [
                Finding(
                    "warn",
                    "snapshot-inspect-product-debris",
                    "product-source compatibility fixture contains repair snapshot debris; snapshots belong only in explicit live operating roots",
                    SNAPSHOT_REPAIR_ROOT_REL,
                )
            ]
        return [
            Finding(
                "info",
                "snapshot-inspect-root-posture",
                "product-source compatibility fixture has no repair snapshot debris",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        ]
    if _is_fallback_or_archive_inventory(inventory):
        return [
            Finding(
                "warn",
                "snapshot-inspect-root-posture",
                "target is fallback/archive or generated-output evidence; any snapshots here are historical evidence only, not live repair authority",
                inventory.state.rel_path if inventory.state else None,
            )
        ]
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "warn",
                "snapshot-inspect-root-posture",
                f"target root kind is {inventory.root_kind}; inspection is report-only and cannot establish live repair eligibility",
            )
        ]
    return [
        Finding(
            "info",
            "snapshot-inspect-root-posture",
            "target is a live operating root; inspection remains read-only and does not authorize repair or rollback",
            inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
        )
    ]


def _snapshot_inspect_boundary_conflict(root: Path) -> Finding | None:
    for candidate in _root_relative_path_chain(root, SNAPSHOT_REPAIR_ROOT_REL):
        candidate_rel = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            return Finding(
                "warn",
                "snapshot-inspect-boundary-conflict",
                f"snapshot boundary contains a symlink segment: {candidate_rel}",
                candidate_rel,
            )
        if candidate.exists() and not candidate.is_dir():
            return Finding(
                "warn",
                "snapshot-inspect-boundary-conflict",
                f"snapshot boundary contains a non-directory segment: {candidate_rel}",
                candidate_rel,
            )
    target = root / SNAPSHOT_REPAIR_ROOT_REL
    if not _path_stays_within_root(root, target):
        return Finding(
            "warn",
            "snapshot-inspect-boundary-conflict",
            f"snapshot boundary would escape the target root: {SNAPSHOT_REPAIR_ROOT_REL}",
            SNAPSHOT_REPAIR_ROOT_REL,
        )
    return None


def _inspect_repair_snapshot(inventory: Inventory, snapshot_dir: Path) -> list[Finding]:
    snapshot_rel = snapshot_dir.relative_to(inventory.root).as_posix()
    findings: list[Finding] = [Finding("info", "snapshot-found", f"repair snapshot found: {snapshot_rel}/", snapshot_rel)]
    metadata_path = snapshot_dir / "snapshot.json"
    metadata_rel = metadata_path.relative_to(inventory.root).as_posix()
    if metadata_path.is_symlink():
        findings.append(Finding("warn", "snapshot-metadata-malformed", f"snapshot metadata is a symlink: {metadata_rel}", metadata_rel))
        return findings
    if not metadata_path.exists():
        findings.append(Finding("warn", "snapshot-metadata-missing", f"snapshot metadata is missing: {metadata_rel}", metadata_rel))
        return findings
    if not metadata_path.is_file():
        findings.append(Finding("warn", "snapshot-metadata-malformed", f"snapshot metadata is not a regular file: {metadata_rel}", metadata_rel))
        return findings

    try:
        metadata_text = metadata_path.read_text(encoding="utf-8")
        metadata = json.loads(metadata_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        findings.append(Finding("warn", "snapshot-metadata-malformed", f"snapshot metadata could not be read as JSON: {exc}", metadata_rel))
        return findings

    if not isinstance(metadata, dict):
        findings.append(Finding("warn", "snapshot-metadata-malformed", "snapshot metadata must be a JSON object", metadata_rel))
        return findings

    findings.append(Finding("info", "snapshot-metadata-read", f"snapshot metadata read: {metadata_rel}", metadata_rel))
    findings.extend(_snapshot_metadata_contract_findings(inventory, snapshot_dir, metadata))
    return findings


def _snapshot_metadata_contract_findings(inventory: Inventory, snapshot_dir: Path, metadata: dict[str, object]) -> list[Finding]:
    snapshot_rel = snapshot_dir.relative_to(inventory.root).as_posix()
    findings: list[Finding] = []
    missing_fields = [field for field in SNAPSHOT_METADATA_FIELDS if field not in metadata]
    if missing_fields:
        findings.append(
            Finding(
                "warn",
                "snapshot-metadata-missing-field",
                f"snapshot metadata missing fields: {', '.join(missing_fields)}",
                f"{snapshot_rel}/snapshot.json",
            )
        )

    schema_version = metadata.get("schema_version")
    if schema_version == SNAPSHOT_SCHEMA_VERSION:
        findings.append(Finding("info", "snapshot-schema", f"snapshot schema_version: {SNAPSHOT_SCHEMA_VERSION}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(
            Finding(
                "warn",
                "snapshot-schema",
                f"expected schema_version {SNAPSHOT_SCHEMA_VERSION}, found {schema_version!r}",
                f"{snapshot_rel}/snapshot.json",
            )
        )

    repair_class = metadata.get("repair_class")
    if repair_class in {
        DOCMAP_REPAIR_CLASS,
        STATE_FRONTMATTER_REPAIR_CLASS,
        LIFECYCLE_MARKDOWN_FRONTMATTER_REPAIR_CLASS,
        LIFECYCLE_SOURCE_PROVENANCE_REPAIR_CLASS,
        SPEC_POSTURE_FRONTMATTER_REPAIR_CLASS,
    }:
        findings.append(Finding("info", "snapshot-repair-class", f"repair class: {repair_class}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-repair-class", f"unexpected or missing repair class: {repair_class!r}", f"{snapshot_rel}/snapshot.json"))

    command = metadata.get("command")
    if command == "repair --apply":
        findings.append(Finding("info", "snapshot-command", "snapshot was created by repair --apply", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-command", f"unexpected or missing snapshot command: {command!r}", f"{snapshot_rel}/snapshot.json"))

    target_root = metadata.get("target_root")
    if isinstance(target_root, str) and _same_path_value(target_root, inventory.root):
        findings.append(Finding("info", "snapshot-target-root", f"metadata target_root matches inspected root: {target_root}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(
            Finding(
                "warn",
                "snapshot-target-root",
                f"metadata target_root does not match inspected root: {target_root!r}",
                f"{snapshot_rel}/snapshot.json",
            )
        )

    snapshot_root = metadata.get("snapshot_root")
    if snapshot_root == snapshot_rel:
        findings.append(Finding("info", "snapshot-root", f"metadata snapshot_root matches snapshot directory: {snapshot_rel}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-root", f"metadata snapshot_root does not match snapshot directory: {snapshot_root!r}", f"{snapshot_rel}/snapshot.json"))

    copied_files = metadata.get("copied_files")
    if not isinstance(copied_files, list) or not copied_files:
        findings.append(Finding("warn", "snapshot-copied-file-missing", "snapshot metadata has no copied_files records", f"{snapshot_rel}/snapshot.json"))
    else:
        for index, record in enumerate(copied_files):
            findings.extend(_snapshot_copied_file_findings(inventory, snapshot_dir, metadata, record, index))

    planned_frontmatter_keys = metadata.get("planned_frontmatter_keys")
    if repair_class == STATE_FRONTMATTER_REPAIR_CLASS:
        if isinstance(planned_frontmatter_keys, list) and all(isinstance(key, str) for key in planned_frontmatter_keys):
            findings.append(
                Finding(
                    "info",
                    "snapshot-planned-frontmatter",
                    f"planned frontmatter keys: {', '.join(planned_frontmatter_keys)}",
                    f"{snapshot_rel}/snapshot.json",
                )
            )
        else:
            findings.append(
                Finding(
                    "warn",
                    "snapshot-planned-frontmatter",
                    f"state frontmatter snapshot has malformed planned_frontmatter_keys: {planned_frontmatter_keys!r}",
                    f"{snapshot_rel}/snapshot.json",
                )
            )

    planned_frontmatter_keys_by_path = metadata.get("planned_frontmatter_keys_by_path")
    if repair_class in {
        LIFECYCLE_MARKDOWN_FRONTMATTER_REPAIR_CLASS,
        LIFECYCLE_SOURCE_PROVENANCE_REPAIR_CLASS,
        SPEC_POSTURE_FRONTMATTER_REPAIR_CLASS,
    }:
        if _is_frontmatter_keys_by_path(planned_frontmatter_keys_by_path):
            key_summary = "; ".join(
                f"{path}: {', '.join(keys)}" for path, keys in sorted(planned_frontmatter_keys_by_path.items())
            )
            findings.append(
                Finding(
                    "info",
                    "snapshot-planned-frontmatter",
                    f"planned frontmatter keys by path: {key_summary}",
                    f"{snapshot_rel}/snapshot.json",
                )
            )
        else:
            findings.append(
                Finding(
                    "warn",
                    "snapshot-planned-frontmatter",
                    f"lifecycle frontmatter snapshot has malformed planned_frontmatter_keys_by_path: {planned_frontmatter_keys_by_path!r}",
                    f"{snapshot_rel}/snapshot.json",
                )
            )

    retention = metadata.get("retention")
    if isinstance(retention, str) and "manual" in retention.casefold():
        findings.append(Finding("info", "snapshot-retention", f"retention posture: {retention}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-retention", f"manual retention posture missing or unclear: {retention!r}", f"{snapshot_rel}/snapshot.json"))

    authority_note = metadata.get("authority_note")
    if isinstance(authority_note, str) and "cannot approve" in authority_note.casefold():
        findings.append(Finding("info", "snapshot-authority", "metadata authority note preserves snapshot non-authority", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-authority", "metadata authority note is missing or does not preserve snapshot non-authority", f"{snapshot_rel}/snapshot.json"))

    rollback_instructions = metadata.get("rollback_instructions")
    if isinstance(rollback_instructions, str) and rollback_instructions.strip():
        findings.append(Finding("info", "snapshot-rollback", f"metadata rollback instructions: {rollback_instructions}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-rollback", "metadata rollback instructions are missing", f"{snapshot_rel}/snapshot.json"))
    return findings


def _is_frontmatter_keys_by_path(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return all(
        isinstance(path, str) and isinstance(keys, list) and all(isinstance(key, str) for key in keys)
        for path, keys in value.items()
    )


def _snapshot_copied_file_findings(
    inventory: Inventory,
    snapshot_dir: Path,
    metadata: dict[str, object],
    record: object,
    index: int,
) -> list[Finding]:
    snapshot_rel = snapshot_dir.relative_to(inventory.root).as_posix()
    source = f"{snapshot_rel}/snapshot.json"
    if not isinstance(record, dict):
        return [Finding("warn", "snapshot-copied-file-malformed", f"copied_files[{index}] must be an object", source)]

    target_rel, target_path_finding = _snapshot_metadata_rel_path(inventory.root, record.get("target_path"), "target_path", source)
    snapshot_path_rel, snapshot_path_finding = _snapshot_metadata_rel_path(inventory.root, record.get("snapshot_path"), "snapshot_path", source)
    findings = [finding for finding in (target_path_finding, snapshot_path_finding) if finding]
    if target_rel is None or snapshot_path_rel is None:
        return findings

    copy_path = inventory.root / snapshot_path_rel
    target_path = inventory.root / target_rel
    if not _path_stays_within_root(snapshot_dir, copy_path):
        findings.append(
            Finding(
                "warn",
                "snapshot-path-conflict",
                f"copied file path is not inside this snapshot directory: {snapshot_path_rel}",
                source,
            )
        )
        return findings

    copied_conflict = _snapshot_existing_file_conflict(inventory.root, snapshot_path_rel, "copied file")
    if copied_conflict:
        findings.append(copied_conflict)
        return findings
    target_conflict = _snapshot_existing_file_conflict(inventory.root, target_rel, "target file")
    target_safe = target_conflict is None
    if target_conflict:
        findings.append(target_conflict)

    if not copy_path.exists():
        findings.append(Finding("warn", "snapshot-copied-file-missing", f"copied file is missing: {snapshot_path_rel}", snapshot_path_rel))
        return findings
    if not copy_path.is_file():
        findings.append(Finding("warn", "snapshot-copied-file-malformed", f"copied file is not a regular file: {snapshot_path_rel}", snapshot_path_rel))
        return findings

    try:
        copied_bytes = copy_path.read_bytes()
    except OSError as exc:
        findings.append(Finding("warn", "snapshot-copied-file-malformed", f"copied file could not be read: {exc}", snapshot_path_rel))
        return findings

    digest = hashlib.sha256(copied_bytes).hexdigest()
    expected_sha = record.get("sha256")
    if isinstance(expected_sha, str) and expected_sha == digest:
        findings.append(Finding("info", "snapshot-copied-file-hash", f"copied file sha256 matches metadata: {snapshot_path_rel}", snapshot_path_rel))
    else:
        findings.append(
            Finding(
                "warn",
                "snapshot-copied-file-hash",
                f"copied file sha256 mismatch for {snapshot_path_rel}: metadata={expected_sha!r}, actual={digest}",
                snapshot_path_rel,
            )
        )

    expected_size = record.get("byte_count")
    if isinstance(expected_size, int) and expected_size == len(copied_bytes):
        findings.append(Finding("info", "snapshot-copied-file-size", f"copied file byte_count matches metadata: {len(copied_bytes)}", snapshot_path_rel))
    else:
        findings.append(
            Finding(
                "warn",
                "snapshot-copied-file-size",
                f"copied file byte_count mismatch for {snapshot_path_rel}: metadata={expected_size!r}, actual={len(copied_bytes)}",
                snapshot_path_rel,
            )
        )

    pre_hashes = metadata.get("pre_repair_hashes")
    if isinstance(pre_hashes, dict) and pre_hashes.get(target_rel) not in (None, digest):
        findings.append(
            Finding(
                "warn",
                "snapshot-pre-repair-hash",
                f"pre_repair_hashes[{target_rel}] does not match copied bytes: {pre_hashes.get(target_rel)!r}",
                source,
            )
        )
    elif isinstance(pre_hashes, dict) and pre_hashes.get(target_rel) == digest:
        findings.append(Finding("info", "snapshot-pre-repair-hash", f"pre-repair hash matches copied bytes for {target_rel}", source))

    if target_safe:
        findings.extend(_snapshot_current_target_findings(target_path, target_rel, digest))
    findings.append(
        Finding(
            "info",
            "snapshot-rollback",
            f"manual rollback only: copy {snapshot_path_rel} back to {target_rel}; then run validate and audit-links",
            snapshot_path_rel,
        )
    )
    return findings


def _snapshot_metadata_rel_path(root: Path, value: object, field_name: str, source: str) -> tuple[str | None, Finding | None]:
    if not isinstance(value, str) or not value.strip():
        return None, Finding("warn", "snapshot-path-conflict", f"{field_name} is missing or not a string: {value!r}", source)
    normalized = value.strip().replace("\\", "/")
    if _is_absolute_path(normalized):
        return None, Finding("warn", "snapshot-path-conflict", f"{field_name} must be target-root relative, not absolute: {normalized}", source)
    if any(part == ".." for part in Path(normalized).parts):
        return None, Finding("warn", "snapshot-path-conflict", f"{field_name} must not contain parent traversal: {normalized}", source)
    if not _path_stays_within_root(root, root / normalized):
        return None, Finding("warn", "snapshot-path-conflict", f"{field_name} would escape the target root: {normalized}", source)
    return normalized, None


def _snapshot_existing_file_conflict(root: Path, rel_path: str, label: str) -> Finding | None:
    target = root / rel_path
    for candidate in _root_relative_path_chain(root, rel_path):
        candidate_rel = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            return Finding("warn", "snapshot-path-conflict", f"{label} path contains a symlink segment: {candidate_rel}", candidate_rel)
        if candidate.exists() and candidate != target and not candidate.is_dir():
            return Finding("warn", "snapshot-path-conflict", f"{label} path contains a non-directory segment: {candidate_rel}", candidate_rel)
    if target.exists() and not target.is_file():
        return Finding("warn", "snapshot-path-conflict", f"{label} path is not a regular file: {rel_path}", rel_path)
    return None


def _snapshot_current_target_findings(target_path: Path, target_rel: str, copied_digest: str) -> list[Finding]:
    if not target_path.exists():
        return [Finding("warn", "snapshot-target-missing", f"current target is missing: {target_rel}", target_rel)]
    if not target_path.is_file():
        return [Finding("warn", "snapshot-target-conflict", f"current target is not a regular file: {target_rel}", target_rel)]
    try:
        target_digest = hashlib.sha256(target_path.read_bytes()).hexdigest()
    except OSError as exc:
        return [Finding("warn", "snapshot-target-conflict", f"current target could not be read: {exc}", target_rel)]
    if target_digest == copied_digest:
        return [
            Finding(
                "info",
                "snapshot-target-current",
                f"current target still matches copied pre-repair bytes: {target_rel}",
                target_rel,
            )
        ]
    return [
        Finding(
            "info",
            "snapshot-target-current",
            f"current target differs from copied pre-repair bytes: {target_rel}; snapshot remains rollback evidence only",
            target_rel,
        )
    ]


def _snapshot_target_conflict(root: Path, rel_path: str) -> Finding | None:
    for candidate in _root_relative_path_chain(root, rel_path):
        candidate_rel = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            return Finding("warn", "snapshot-plan-refused", f"target path contains a symlink segment: {candidate_rel}", candidate_rel)
        if candidate.exists() and candidate != root / rel_path and not candidate.is_dir():
            return Finding("warn", "snapshot-plan-refused", f"target path contains a non-directory segment: {candidate_rel}", candidate_rel)
    target = root / rel_path
    if target.exists() and not target.is_file():
        return Finding("warn", "snapshot-plan-refused", f"target path is not a regular file: {rel_path}", rel_path)
    if not _path_stays_within_root(root, target):
        return Finding("warn", "snapshot-plan-refused", f"target path would escape the target root: {rel_path}", rel_path)
    return None


def _snapshot_boundary_conflict(root: Path, snapshot_dir_rel: str) -> Finding | None:
    for rel_path in (SNAPSHOT_REPAIR_ROOT_REL, snapshot_dir_rel):
        for candidate in _root_relative_path_chain(root, rel_path):
            candidate_rel = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                return Finding("warn", "snapshot-plan-refused", f"snapshot boundary contains a symlink segment: {candidate_rel}", candidate_rel)
            if candidate.exists() and not candidate.is_dir():
                return Finding("warn", "snapshot-plan-refused", f"snapshot boundary contains a non-directory segment: {candidate_rel}", candidate_rel)
    target = root / snapshot_dir_rel
    if target.exists():
        return Finding("warn", "snapshot-plan-refused", f"planned snapshot directory already exists: {snapshot_dir_rel}", snapshot_dir_rel)
    if not _path_stays_within_root(root, target):
        return Finding("warn", "snapshot-plan-refused", f"snapshot path would escape the target root: {snapshot_dir_rel}", snapshot_dir_rel)
    return None


def _path_stays_within_root(root: Path, target: Path) -> bool:
    try:
        target.resolve(strict=False).relative_to(root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


class LinkResolution:
    def __init__(self, kind: str, exists: bool = False) -> None:
        self.kind = kind
        self.exists = exists


def resolve_link(root: Path, target: str, source_rel: str | None = None) -> LinkResolution:
    clean = target.strip().strip("<>").strip()
    if not clean:
        return LinkResolution("unresolved", False)
    if clean.startswith("#"):
        return LinkResolution("anchor", True)
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", clean) or clean.startswith("mailto:"):
        return LinkResolution("external", True)
    path_part = clean.split("#", 1)[0]
    if not path_part:
        return LinkResolution("anchor", True)
    unsafe_reason = windows_path_reference_reason(path_part, allow_uri=False, allow_rooted=False)
    if unsafe_reason and unsafe_reason != "Windows drive-absolute path":
        return LinkResolution("unsafe", False)
    base = _link_base(root, path_part, source_rel)
    if any(char in path_part for char in "*?[]{}<>"):
        patterns = _expand_brace_pattern(path_part)
        exists = False
        for pattern in patterns:
            candidate = Path(pattern) if _is_absolute_path(pattern) else base / pattern
            if not _path_stays_within_root(root, candidate):
                return LinkResolution("unsafe", False)
            resolved_pattern = str(candidate)
            if glob.glob(resolved_pattern):
                exists = True
                break
            if "{" in pattern or "}" in pattern:
                continue
            if Path(resolved_pattern).exists():
                exists = True
                break
        return LinkResolution("pattern", exists)
    if _is_absolute_path(path_part):
        candidate = Path(path_part)
    else:
        candidate = base / path_part
    if not _path_stays_within_root(root, candidate):
        return LinkResolution("unsafe", False)
    return LinkResolution("local", candidate.exists())


def _required_surface_findings(inventory: Inventory) -> list[Finding]:
    findings = []
    for surface in inventory.surfaces:
        if surface.required and not surface.exists:
            findings.append(Finding("error", "missing-required-surface", f"missing required surface: {surface.rel_path}", surface.rel_path))
    return findings


def _manifest_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    manifest = inventory.manifest_surface
    if not manifest or not manifest.exists:
        return findings
    neutral = inventory.surface_by_rel.get(WORKFLOW_MANIFEST_REL)
    legacy = inventory.surface_by_rel.get(LEGACY_WORKFLOW_MANIFEST_REL)
    if manifest.rel_path == LEGACY_WORKFLOW_MANIFEST_REL and (neutral is None or not neutral.exists) and legacy and legacy.exists:
        findings.append(
            Finding(
                "info",
                "manifest-migrate-available",
                f"legacy-only workflow manifest selected; optional neutral migration: mylittleharness --root <root> migrate --dry-run",
                LEGACY_WORKFLOW_MANIFEST_REL,
            )
        )
    for warning in inventory.manifest_warnings:
        findings.append(Finding("warn", "manifest-resolution-drift", warning, manifest.rel_path))
    for error in inventory.manifest_errors:
        findings.append(Finding("error", "manifest-parse", error, manifest.rel_path))
    workflow = inventory.manifest.get("workflow") if isinstance(inventory.manifest, dict) else None
    if workflow != "workflow-core":
        findings.append(Finding("warn", "manifest-workflow", "manifest workflow is not workflow-core", manifest.rel_path))
    memory = inventory.manifest.get("memory", {}) if isinstance(inventory.manifest, dict) else {}
    if memory.get("state_file", "project/project-state.md") != "project/project-state.md":
        findings.append(Finding("warn", "manifest-state-file", "manifest state_file differs from project/project-state.md", manifest.rel_path))
    if memory.get("plan_file", "project/implementation-plan.md") != "project/implementation-plan.md":
        findings.append(Finding("warn", "manifest-plan-file", "manifest plan_file differs from project/implementation-plan.md", manifest.rel_path))
    return findings


def _selected_manifest_rel(inventory: Inventory) -> str:
    if inventory.manifest_surface:
        return inventory.manifest_surface.rel_path
    return WORKFLOW_MANIFEST_REL


def _state_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    state = inventory.state
    if not state or not state.exists:
        return findings
    if not state.frontmatter.has_frontmatter:
        if inventory.root_kind == "live_operating_root" and _has_read_only_state_assignments(state):
            findings.append(
                Finding(
                    "info",
                    "state-prose-fallback",
                    "project-state.md has no frontmatter; read-only assignment fallback is used for status and validation only",
                    state.rel_path,
                )
            )
            return findings
        findings.append(Finding("error", "state-frontmatter", "project-state.md is missing frontmatter", state.rel_path))
        return findings
    for key in ("project", "workflow", "operating_mode", "plan_status"):
        if not state.frontmatter.data.get(key):
            findings.append(Finding("error", "state-frontmatter-field", f"project-state.md missing frontmatter key: {key}", state.rel_path))
    if inventory.root_kind == "live_operating_root":
        findings.extend(_live_product_source_root_findings(inventory, state))
        findings.extend(_live_product_command_surface_findings(inventory, state))
        findings.extend(_live_product_doc_copy_drift_findings(inventory, state))
        findings.extend(_stale_phase_writeback_tail_findings(state))
        findings.extend(_state_lifecycle_prose_drift_findings(state))
    return findings


def _stale_phase_writeback_tail_findings(state: Surface) -> list[Finding]:
    plan_status = str(state.frontmatter.data.get("plan_status") or "")
    if plan_status not in {"none", ""}:
        return []

    findings: list[Finding] = []
    lines = state.content.splitlines()
    for start, end in _marker_spans(state.content, PHASE_WRITEBACK_BEGIN, PHASE_WRITEBACK_END):
        active_plan_line = _marked_block_field_line(lines, start, end, "active_plan", DEFAULT_PLAN_REL)
        if active_plan_line is None:
            continue
        findings.append(
            Finding(
                "warn",
                "state-stale-phase-writeback-tail",
                (
                    "project-state frontmatter records plan_status='none' while an older MLH Phase Writeback block "
                    f"still references {DEFAULT_PLAN_REL}; treat that block as historical carry-forward only, and use "
                    "writeback/transition archive or whole-state compaction for any reviewed cleanup; this diagnostic "
                    "does not approve lifecycle movement, archive, repair, staging, or commit"
                ),
                state.rel_path,
                active_plan_line,
            )
        )
    return findings


def _marked_block_field_line(lines: list[str], start: int, end: int, field: str, expected_value: str) -> int | None:
    expected = expected_value.replace("\\", "/").casefold()
    for line_number in range(start + 1, end):
        line = lines[line_number - 1]
        match = re.match(rf"^\s*[-*]\s*`?{re.escape(field)}`?\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
        if not match:
            continue
        value = _normalized_block_field_value(match.group(1))
        if value == expected:
            return line_number
    return None


def _normalized_block_field_value(value: str) -> str:
    raw = _display_path_value(value).strip()
    if raw.startswith("`") and raw.endswith("`") and len(raw) >= 2:
        raw = raw[1:-1].strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1].strip()
    return raw.replace("\\", "/").casefold()


def _state_lifecycle_prose_drift_findings(state: Surface) -> list[Finding]:
    plan_status = str(state.frontmatter.data.get("plan_status") or "")
    if plan_status not in {"active", "none", ""}:
        return []

    findings: list[Finding] = []
    for line_number, line in _current_state_authority_lines(state.content):
        normalized = line.casefold()
        if plan_status == "none" and _line_says_active_plan_is_open(normalized):
            findings.append(
                Finding(
                    "warn",
                    "state-lifecycle-prose-drift",
                    (
                        "project-state frontmatter records plan_status='none' but current prose says an active plan is open; "
                        "rewrite the prose as historical context or preview whole-state history compaction with writeback --dry-run --compact-only"
                    ),
                    state.rel_path,
                    line_number,
                )
            )
        elif plan_status == "active" and _line_says_no_active_plan_is_open(normalized):
            findings.append(
                Finding(
                    "warn",
                    "state-lifecycle-prose-drift",
                    (
                        "project-state frontmatter records plan_status='active' but current prose says no active plan is open; "
                        "rewrite the prose as historical context or refresh managed focus with writeback/plan apply"
                    ),
                    state.rel_path,
                    line_number,
                )
            )
    return findings


def _current_state_authority_lines(text: str) -> list[tuple[int, str]]:
    excluded_spans = _managed_state_spans(text)
    lines = text.splitlines()
    current_section = ""
    results: list[tuple[int, str]] = []
    for index, line in enumerate(lines, start=1):
        if any(start <= index <= end for start, end in excluded_spans):
            continue
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current_section = heading.group(1).strip()
            continue
        if _state_section_is_historical(current_section):
            continue
        if line.strip():
            results.append((index, line))
    return results


def _managed_state_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for begin, end in (
        (CURRENT_FOCUS_BEGIN, CURRENT_FOCUS_END),
        (MEMORY_ROADMAP_BEGIN, MEMORY_ROADMAP_END),
        ("<!-- BEGIN mylittleharness-closeout-writeback v1 -->", "<!-- END mylittleharness-closeout-writeback v1 -->"),
        (PHASE_WRITEBACK_BEGIN, PHASE_WRITEBACK_END),
    ):
        spans.extend(_marker_spans(text, begin, end))
    return spans


def _marker_spans(text: str, begin: str, end: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(text.splitlines(), start=1):
        if line.strip() == begin:
            start = index
            continue
        if line.strip() == end and start is not None:
            spans.append((start, index))
            start = None
    return spans


def _state_section_is_historical(title: str) -> bool:
    normalized = title.casefold()
    return normalized.startswith(
        (
            "ad hoc update",
            "active plan implementation update",
            "active plan validation refresh",
            "archived state history",
            "research update",
            "mlh closeout writeback",
        )
    )


def _line_says_active_plan_is_open(normalized_line: str) -> bool:
    return (
        "active implementation plan is open" in normalized_line
        or "active plan is open" in normalized_line
        or "current active-plan pointer" in normalized_line
    )


def _line_says_no_active_plan_is_open(normalized_line: str) -> bool:
    return (
        "no active implementation plan is open" in normalized_line
        or "no active plan is open" in normalized_line
        or "no active-plan pointer" in normalized_line
    )


def _live_product_source_root_findings(inventory: Inventory, state: Surface) -> list[Finding]:
    resolved, problem = _resolve_live_product_source_root(inventory, state)
    if problem:
        return [problem]
    if not resolved:
        return []
    return [Finding("info", "product-source-root-ok", f"product_source_root exists: {resolved}", state.rel_path)]


def _resolve_live_product_source_root(inventory: Inventory, state: Surface) -> tuple[Path | None, Finding | None]:
    value = state.frontmatter.data.get("product_source_root")
    if not value:
        return None, None
    text = _display_path_value(str(value)).strip()
    try:
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = inventory.root / candidate
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        return None, Finding("warn", "product-source-root-invalid", f"product_source_root could not be resolved: {exc}", state.rel_path)
    try:
        root_resolved = inventory.root.resolve()
    except (OSError, RuntimeError):
        root_resolved = inventory.root
    if not resolved.exists():
        return None, Finding("warn", "product-source-root-missing", f"product_source_root does not exist: {text}", state.rel_path)
    if not resolved.is_dir():
        return None, Finding("warn", "product-source-root-invalid", f"product_source_root is not a directory: {text}", state.rel_path)
    if str(resolved).casefold() == str(root_resolved).casefold():
        return None, Finding("warn", "product-source-root-invalid", "product_source_root points at the operating root", state.rel_path)
    return resolved, None


def _live_product_command_surface_findings(inventory: Inventory, state: Surface) -> list[Finding]:
    product_root, problem = _resolve_live_product_source_root(inventory, state)
    if problem or not product_root:
        return []
    product_commands = _product_source_command_names(product_root)
    expected = [command for command in COMMAND_SURFACE_SENTINEL_COMMANDS if command in product_commands]
    if not expected:
        return []
    console_script = shutil.which("mylittleharness")
    source_fallback_command = _source_pythonpath_fallback_command(product_root)
    console_detail = f"PATH candidate: {console_script}" if console_script else "PATH candidate: not found"
    return [
        Finding(
            "info",
            "installed-cli-command-surface-static",
            (
                f"product_source_root exposes sentinel command(s): {', '.join(expected)}; default check does not execute "
                f"a PATH-discovered mylittleharness console script ({console_detail}); use `{source_fallback_command}` "
                "for source-checkout command access or `bootstrap --package-smoke` for package entrypoint verification after review; "
                "diagnostic only, with no automatic install, mirror, lifecycle movement, closeout, archive, staging, or commit"
            ),
            state.rel_path,
        )
    ]


def command_surface_manifest() -> tuple[dict[str, object], ...]:
    return COMMAND_SURFACE_ROWS


def command_surface_findings() -> list[Finding]:
    findings: list[Finding] = []
    for row in command_surface_manifest():
        findings.append(
            Finding(
                "info",
                "command-surface-entry",
                (
                    f"{row['surface_id']}: commands={list(row['commands'])}; "
                    f"read_write_class={row['read_write_class']}; "
                    f"apply_requirement={row['apply_requirement']}; "
                    f"root_eligibility={row['root_eligibility']}; "
                    f"write_path_posture={row['write_path_posture']}; "
                    f"authority_risk={row['authority_risk']}"
                ),
                route_id="unclassified",
            )
        )
    findings.append(
        Finding(
            "info",
            "command-surface-boundary",
            (
                "command surface report names read/write/apply/root/write-path posture for auditability; "
                "the manifest is protocol/report data only and cannot approve lifecycle movement, archive, "
                "staging, commit, push, release, provider routing, or future mutations"
            ),
            route_id="unclassified",
        )
    )
    return findings


def _product_source_command_names(product_root: Path) -> set[str]:
    cli_path = product_root / "src" / "mylittleharness" / "cli.py"
    try:
        source = cli_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return set()
    try:
        module = ast.parse(source)
    except SyntaxError:
        return set()
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "COMMANDS" for target in node.targets):
            continue
        return _literal_string_collection(node.value)
    return set()


def _source_pythonpath_fallback_command(product_root: Path) -> str:
    return f"PYTHONPATH={shell_arg(product_root / 'src')} python -m mylittleharness --root <root> ..."


def _literal_string_collection(node: ast.AST) -> set[str]:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return set()
    values: set[str] = set()
    for item in node.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            values.add(item.value)
    return values


def _live_product_doc_copy_drift_findings(inventory: Inventory, state: Surface) -> list[Finding]:
    product_root, problem = _resolve_live_product_source_root(inventory, state)
    if problem or not product_root:
        return []
    product_commands = _product_source_command_names(product_root)
    if not product_commands:
        return []

    findings: list[Finding] = []
    for surface in _product_doc_copy_drift_surfaces(inventory):
        for command in RETIRED_COMMAND_DOC_SURFACES:
            if command in product_commands:
                continue
            line_number = _first_command_shaped_reference_line(surface.content, command)
            if line_number is None:
                continue
            findings.append(
                Finding(
                    "warn",
                    "product-doc-copy-retired-command-drift",
                    (
                        f"{surface.rel_path} references retired command `{command}` while product_source_root command surface "
                        f"at {product_root} no longer exposes it; update or retarget the operating-root doc copy after review. "
                        "Diagnostic only: no automatic cross-root copy, install, mirror, repair approval, lifecycle movement, "
                        "archive, staging, or commit is implied."
                    ),
                    surface.rel_path,
                    line_number,
                )
            )
    return findings


def _product_doc_copy_drift_surfaces(inventory: Inventory) -> list[Surface]:
    surfaces: list[Surface] = []
    for rel_path in PRODUCT_DOC_COPY_DRIFT_SURFACES:
        surface = inventory.surface_by_rel.get(rel_path)
        if surface and surface.exists and surface.content:
            surfaces.append(surface)
    return surfaces


def _first_command_shaped_reference_line(content: str, command: str) -> int | None:
    backticked = re.compile(rf"`{re.escape(command)}(?:`|\s+--)")
    quoted_scalar = re.compile(rf"(?<![\w-])['\"]{re.escape(command)}['\"](?![\w-])")
    bare_with_option = re.compile(rf"(?<![\w-]){re.escape(command)}\s+--")
    for line_number, line in enumerate(content.splitlines(), start=1):
        if backticked.search(line) or quoted_scalar.search(line) or bare_with_option.search(line):
            return line_number
    return None


def _console_script_accepts_command(console_script: str, command: str) -> tuple[bool, str]:
    probe_env = {key: value for key, value in os.environ.items() if key.upper() != "PYTHONPATH"}
    try:
        completed = subprocess.run(
            [console_script, command, "--help"],
            capture_output=True,
            text=True,
            timeout=COMMAND_SURFACE_PROBE_TIMEOUT_SECONDS,
            check=False,
            env=probe_env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if completed.returncode == 0:
        return True, ""
    return False, _console_script_probe_error(completed.stdout, completed.stderr)


def _console_script_probe_error(stdout: str, stderr: str) -> str:
    combined = "\n".join(part for part in (stdout, stderr) if part)
    if not re.search(r"\b(Traceback|ImportError|ModuleNotFoundError)\b", combined):
        return ""
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    if not lines:
        return "console script exited before command help could be inspected"
    return lines[-1][:240]


def _has_read_only_state_assignments(state: Surface) -> bool:
    data = state.frontmatter.data
    return bool(data.get("operating_mode") and data.get("plan_status"))


def _product_posture_status_findings(inventory: Inventory) -> list[Finding]:
    state = inventory.state
    if not state or not state.exists:
        return []
    data = state.frontmatter.data
    findings: list[Finding] = []
    product_name = data.get("project")
    root_role = data.get("root_role")
    fixture_status = data.get("fixture_status")
    operating_root = data.get("operating_root") or data.get("canonical_source_evidence_root")
    product_root = data.get("product_source_root") or data.get("projection_root")
    fallback_root = data.get("historical_fallback_root")

    if product_name:
        findings.append(Finding("info", "product-name", f"product name: {product_name}", state.rel_path))
    if root_role:
        findings.append(Finding("info", "target-root-role", f"target root role: {root_role}", state.rel_path))
    if fixture_status:
        findings.append(Finding("info", "fixture-status", f"fixture status: {fixture_status}", state.rel_path))
    if operating_root:
        findings.append(Finding("info", "operating-root", f"operating root: {operating_root}", state.rel_path))
    if product_root:
        findings.append(Finding("info", "product-root", f"product root: {product_root}", state.rel_path))
    if fallback_root:
        findings.append(Finding("info", "fallback-root", f"fallback root: {fallback_root}", state.rel_path))
    return findings


def _product_posture_findings(inventory: Inventory) -> list[Finding]:
    if not _is_mylittleharness_product_context(inventory):
        return []
    state = inventory.state
    if not state or not state.exists:
        return []
    data = state.frontmatter.data
    findings: list[Finding] = []

    required = (
        "project",
        "root_role",
        "fixture_status",
        "operating_root",
        "product_source_root",
        "historical_fallback_root",
    )
    for key in required:
        if data.get(key) in (None, ""):
            findings.append(Finding("error", "product-posture-field", f"product-root posture missing field: {key}", state.rel_path))

    if data.get("project") not in (None, "", EXPECTED_PRODUCT_NAME):
        findings.append(
            Finding(
                "error",
                "product-posture-product-name",
                f"product-root posture names {data.get('project')!r}; expected {EXPECTED_PRODUCT_NAME}",
                state.rel_path,
            )
        )
    if data.get("root_role") not in (None, "", EXPECTED_PRODUCT_ROOT_ROLE):
        findings.append(
            Finding(
                "error",
                "product-posture-root-role",
                f"product-root posture has root_role={data.get('root_role')!r}; expected {EXPECTED_PRODUCT_ROOT_ROLE}",
                state.rel_path,
            )
        )
    if data.get("fixture_status") not in (None, "", EXPECTED_PRODUCT_FIXTURE_STATUS):
        findings.append(
            Finding(
                "error",
                "product-posture-fixture-status",
                f"product-root posture has fixture_status={data.get('fixture_status')!r}; expected {EXPECTED_PRODUCT_FIXTURE_STATUS}",
                state.rel_path,
            )
        )

    operating_root = data.get("operating_root")
    product_root = data.get("product_source_root")
    fallback_root = data.get("historical_fallback_root")
    if product_root and not _same_path_value(product_root, inventory.root):
        findings.append(
            Finding(
                "error",
                "product-posture-product-root",
                f"product_source_root does not match target root: {product_root}",
                state.rel_path,
            )
        )
    if operating_root and _same_path_value(operating_root, inventory.root):
        findings.append(
            Finding(
                "error",
                "product-posture-operating-root",
                "operating_root points at the product source root; operating memory must stay outside the product tree",
                state.rel_path,
            )
        )
    if fallback_root and _same_path_value(fallback_root, inventory.root):
        findings.append(
            Finding(
                "error",
                "product-posture-fallback-root",
                "historical_fallback_root points at the product source root",
                state.rel_path,
            )
        )
    if data.get("plan_status") == "active" or data.get("active_plan") not in (None, "") or (
        inventory.active_plan_surface and inventory.active_plan_surface.exists
    ):
        findings.append(
            Finding(
                "error",
                "product-posture-active-plan",
                "product source root must not contain or own an active implementation plan; use the operating root",
                state.rel_path,
            )
        )
    return findings


def _active_plan_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    state = inventory.state
    data = state.frontmatter.data if state else {}
    status = data.get("plan_status")
    active_plan = data.get("active_plan") or "project/implementation-plan.md"
    plan = inventory.active_plan_surface
    if status == "active":
        if not data.get("active_plan"):
            findings.append(Finding("error", "active-plan-field", "plan_status is active but active_plan is empty", state.rel_path if state else None))
        if not plan or not plan.exists:
            findings.append(Finding("error", "active-plan-missing", f"plan_status is active but {active_plan} is missing", active_plan))
        if not data.get("active_phase"):
            findings.append(
                Finding(
                    "warn",
                    "active-phase-field",
                    "plan_status is active but active_phase is empty; record the current plan phase explicitly; next_safe_command=mylittleharness --root <root> writeback --dry-run --active-phase <phase-id> --phase-status pending",
                    state.rel_path if state else None,
                )
            )
        phase_status = str(data.get("phase_status") or "")
        if not phase_status:
            findings.append(
                Finding(
                    "warn",
                    "phase-status-field",
                    "plan_status is active but phase_status is empty; record one of: active, blocked, complete, in_progress, paused, pending, skipped; next_safe_command=mylittleharness --root <root> writeback --dry-run --phase-status <value>",
                    state.rel_path if state else None,
                )
            )
        elif phase_status not in PHASE_STATUS_VALUES:
            findings.append(
                Finding(
                    "warn",
                    "phase-status-value",
                    f"phase_status is {phase_status!r}; expected one of: active, blocked, complete, in_progress, paused, pending, skipped; next_safe_command=mylittleharness --root <root> writeback --dry-run --phase-status <value>",
                    state.rel_path if state else None,
                )
            )
        if plan and plan.exists:
            findings.extend(_active_plan_roadmap_intake_policy_findings(plan))
            findings.extend(_active_plan_generated_shape_findings(plan))
            findings.extend(_active_plan_verification_gate_findings(inventory, plan, data))
            findings.extend(_active_plan_execution_policy_findings(plan, data))
            findings.extend(_active_plan_completion_policy_findings(inventory, plan, data))
            findings.extend(_active_plan_docs_decision_findings(inventory, plan, data))
            findings.extend(_active_plan_writeback_drift_findings(inventory, plan, data))
            findings.extend(_active_plan_lifecycle_drift_findings(inventory, plan, data))
            findings.extend(_active_plan_phase_evidence_findings(inventory, data))
            findings.extend(product_diff_write_scope_findings(inventory, code_prefix="active-plan"))
            if str(data.get("phase_status") or "") != "complete":
                findings.extend(completion_gate_packet_findings(inventory, code_prefix="active-plan", include_success=True))
            findings.extend(_active_plan_work_result_capsule_findings(inventory, plan, data))
            findings.extend(_active_plan_source_incubation_relationship_findings(inventory, plan))
            findings.extend(_active_plan_covered_roadmap_scope_findings(inventory, plan, data))
            findings.extend(_active_plan_scoped_interrupt_contract_findings(plan))
    elif plan and plan.exists:
        findings.append(Finding("warn", "stale-plan-file", "implementation plan exists while plan_status is not active", plan.rel_path))
    manifest_plan = inventory.manifest.get("memory", {}).get("plan_file") if inventory.manifest else None
    if status == "active" and manifest_plan and str(active_plan).replace("\\", "/") != str(manifest_plan).replace("\\", "/"):
        findings.append(Finding("error", "active-plan-manifest", "active_plan differs from manifest memory.plan_file", state.rel_path if state else None))
    return findings


def _active_plan_roadmap_intake_policy_findings(plan: Surface) -> list[Finding]:
    return [
        Finding(
            "info",
            "active-plan-roadmap-intake-policy-matrix",
            (
                "active plan is open: read-only lifecycle inspection and MLH dry-run/apply route review are safe; "
                "candidate capture belongs in meta-feedback/incubation now; accepted roadmap status/order/dependency/"
                "next-item promotion waits for plan_status=none unless the active plan explicitly covers the roadmap item; "
                "next_safe_candidate=mylittleharness --root <root> meta-feedback --dry-run ...; "
                "next_safe_after_close=mylittleharness --root <root> roadmap --dry-run ..."
            ),
            plan.rel_path,
        )
    ]


def _active_plan_source_incubation_relationship_findings(inventory: Inventory, plan: Surface) -> list[Finding]:
    if not plan.frontmatter.has_frontmatter:
        return []
    source_incubation = _normalize_route_metadata_path(str(plan.frontmatter.data.get("source_incubation") or ""))
    if not source_incubation:
        return []
    source_surface = inventory.surface_by_rel.get(source_incubation)
    if not source_surface or not source_surface.exists or not source_surface.frontmatter.has_frontmatter:
        return []
    related_plan = _normalize_route_metadata_path(str(source_surface.frontmatter.data.get("related_plan") or ""))
    if related_plan == "project/implementation-plan.md":
        return []
    display = related_plan or "<empty>"
    return [
        Finding(
            "warn",
            "active-plan-source-incubation-related-plan-drift",
            (
                f"active plan source_incubation {source_incubation} has related_plan {display!r}; "
                "plan --apply --roadmap-item should sync the source incubation back to project/implementation-plan.md "
                "when opening this active plan"
            ),
            source_incubation,
        )
    ]


def _active_plan_covered_roadmap_scope_findings(
    inventory: Inventory,
    plan: Surface,
    state_data: dict[str, object],
) -> list[Finding]:
    if not plan.frontmatter.has_frontmatter or plan.frontmatter.errors:
        return []
    plan_data = plan.frontmatter.data
    covered = _active_plan_covered_roadmap_item_ids(plan_data)
    if len(covered) <= 1:
        return []
    roadmap_items, parse_findings = roadmap_items_for_diagnostics(inventory)
    if parse_findings or not roadmap_items:
        return []

    plan_targets = set(_dedupe_route_values(tuple(_contract_list(plan_data.get("target_artifacts")))))
    phase_scope = set(_active_plan_current_phase_write_scope(plan, state_data))
    if not plan_targets and not phase_scope:
        return []

    missing_plan_targets: list[str] = []
    missing_phase_scope: list[str] = []
    for item_id in covered:
        item = roadmap_items.get(item_id)
        if not item:
            continue
        targets = _target_artifact_values(item.fields.get("target_artifacts"))
        if not targets:
            continue
        target_keys = tuple(_normalize_route_metadata_path(target).casefold() for target in targets)
        plan_missing = [target for target, key in zip(targets, target_keys) if key and key not in plan_targets]
        scope_missing = [target for target, key in zip(targets, target_keys) if key and key not in phase_scope]
        if plan_missing:
            missing_plan_targets.append(f"{item_id}: {_summarize_contract_values(plan_missing)}")
        if scope_missing:
            missing_phase_scope.append(f"{item_id}: {_summarize_contract_values(scope_missing)}")

    if not missing_plan_targets and not missing_phase_scope:
        return []

    details: list[str] = []
    if missing_plan_targets:
        details.append(f"target_artifacts missing {', '.join(missing_plan_targets[:3])}")
    if missing_phase_scope:
        details.append(f"active-phase write_scope missing {', '.join(missing_phase_scope[:3])}")
    return [
        Finding(
            "warn",
            "active-plan-covered-roadmap-write-scope-contract",
            (
                "active plan covered_roadmap_items claims multiple roadmap items but does not authorize every covered "
                f"item target_artifact in the plan target_artifacts/current-phase write_scope ({'; '.join(details)}); "
                "use --only-requested-item for partial coverage or reopen the plan/roadmap scope before marking bundled items done"
            ),
            plan.rel_path,
        )
    ]


def _active_plan_covered_roadmap_item_ids(plan_data: dict[str, object]) -> tuple[str, ...]:
    values = (
        _contract_text(plan_data.get("primary_roadmap_item")).casefold().replace("_", "-"),
        _contract_text(plan_data.get("related_roadmap_item")).casefold().replace("_", "-"),
        *(_contract_text(value).casefold().replace("_", "-") for value in _contract_list(plan_data.get("covered_roadmap_items"))),
    )
    return tuple(_dedupe_route_values(tuple(value for value in values if value)))


def _active_plan_scoped_interrupt_contract_findings(plan: Surface) -> list[Finding]:
    if not plan.frontmatter.has_frontmatter or plan.frontmatter.errors:
        return []
    plan_data = plan.frontmatter.data
    work_intent = _contract_text(plan_data.get("work_intent")).casefold()
    if work_intent != "scoped_interrupt":
        return []
    policy = _contract_text(plan_data.get("roadmap_status_policy")) or "<empty>"
    severity = "info" if policy == "no-roadmap-status-movement-without-explicit-request" else "warn"
    return [
        Finding(
            severity,
            "active-plan-scoped-interrupt-contract",
            (
                f"active plan declares scoped_interrupt work_intent with roadmap_status_policy {policy!r}; "
                "closeout/archive must preserve explicit evidence, carry_forward/return-to-roadmap posture, "
                "and no roadmap status movement unless the reviewed writeback or transition names it"
            ),
            plan.rel_path,
        )
    ]


def _active_plan_current_phase_write_scope(plan: Surface, state_data: dict[str, object]) -> list[str]:
    active_phase = _contract_text(state_data.get("active_phase") or (plan.frontmatter.data.get("active_phase") if plan.frontmatter.has_frontmatter else ""))
    if active_phase:
        lines = _active_phase_contract_lines(plan, active_phase, "write_scope", "write scope")
    else:
        lines = []
    if not lines:
        lines = _plan_contract_lines(plan, "write_scope", "write scope")
    return _dedupe_route_values(tuple(_contract_route_values_from_lines(lines)))


def _contract_route_values_from_lines(lines: list[tuple[str, int]]) -> list[str]:
    values: list[str] = []
    for text, _line in lines:
        backticked = re.findall(r"`([^`]+)`", text)
        if backticked:
            values.extend(backticked)
        else:
            values.extend(_contract_list(text))
    return values


def _summarize_contract_values(values: list[str]) -> str:
    sample = ", ".join(values[:3])
    if len(values) > 3:
        sample = f"{sample}, +{len(values) - 3} more"
    return sample


def _active_plan_generated_shape_findings(plan: Surface) -> list[Finding]:
    if not plan.frontmatter.has_frontmatter or not plan.frontmatter.data.get("plan_id"):
        return []
    heading_titles = {heading.title for heading in plan.headings}
    required = {
        "Objective",
        "Authority Inputs",
        "Non-goals",
        "Invariants",
        "File Ownership",
        "Phases",
        "Verification Strategy",
        "Docs Decision",
        "State Transfer",
        "Refusal Conditions",
        "Closeout Checklist",
        "Decision Log",
    }
    missing = sorted(required - heading_titles)
    if not missing:
        return []
    return [
        Finding(
            "warn",
            "active-plan-generated-shape",
            f"generated active plan is missing expected sections: {', '.join(missing)}",
            plan.rel_path,
        )
    ]


def _active_plan_verification_gate_findings(
    inventory: Inventory,
    plan: Surface,
    state_data: dict[str, object],
) -> list[Finding]:
    lines = _active_plan_verification_gate_lines(plan, state_data)
    target_artifacts = _contract_list(plan.frontmatter.data.get("target_artifacts") if plan.frontmatter.has_frontmatter else None)
    target_root = _active_plan_target_root(inventory)
    declared_write_scope = [text for text, _line in _plan_contract_lines(plan, "write_scope", "write scope")]
    findings: list[Finding] = []
    if not lines:
        if not _active_plan_has_generated_verification_contract(plan, target_artifacts):
            return []
        findings.append(
            Finding(
                "warn",
                "active-plan-verification-gate-missing",
                "active plan has no verification_gates entries; record repo-visible deterministic success signals before confident execution",
                plan.rel_path,
            )
        )
    else:
        line_text = "\n".join(text for text, _line in lines)
        if _verification_gate_is_unresolved(line_text):
            findings.append(
                Finding(
                    "warn",
                    "active-plan-verification-gate-unresolved",
                    "active plan verification_gates are unresolved; an agent must record an evidence-backed concrete gate before confident closeout",
                    plan.rel_path,
                    lines[0][1],
                )
            )
        if _verification_gate_is_generic(line_text):
            findings.append(
                Finding(
                    "warn",
                    "active-plan-verification-gate-generic",
                    "active plan verification_gates still contain a generic fallback instead of a repo-visible command with a deterministic success signal",
                    plan.rel_path,
                    lines[0][1],
                )
            )
        if mismatch_reason := _verification_gate_toolchain_mismatch(line_text, target_artifacts, target_root):
            findings.append(
                Finding(
                    "warn",
                    "active-plan-verification-gate-toolchain-mismatch",
                    mismatch_reason,
                    plan.rel_path,
                    lines[0][1],
                )
            )
        if ownership_reason := _adjacent_regression_test_ownership_reason(line_text, target_artifacts, declared_write_scope):
            findings.append(
                Finding(
                    "warn",
                    "active-plan-adjacent-verification-ownership",
                    ownership_reason,
                    plan.rel_path,
                    lines[0][1],
                )
            )

    if findings and str(state_data.get("phase_status") or "") == "complete":
        findings.append(
            Finding(
                "warn",
                "active-plan-verification-gate-closeout-blocker",
                "phase_status is complete but verification gates are missing, unresolved, generic, toolchain-mismatched, or missing adjacent regression-test ownership; keep closeout provisional until concrete evidence is recorded",
                plan.rel_path,
            )
        )
    return findings


def _active_plan_has_generated_verification_contract(plan: Surface, target_artifacts: list[str]) -> bool:
    if not plan.frontmatter.has_frontmatter:
        return False
    data = plan.frontmatter.data
    return bool(data.get("plan_id") or data.get("execution_slice") or data.get("primary_roadmap_item") or target_artifacts)


def _active_plan_verification_gate_lines(plan: Surface, state_data: dict[str, object]) -> list[tuple[str, int]]:
    active_phase = _contract_text(
        state_data.get("active_phase") or (plan.frontmatter.data.get("active_phase") if plan.frontmatter.has_frontmatter else "")
    )
    if active_phase:
        lines = _active_phase_contract_lines(plan, active_phase, "verification_gates", "verification gates")
        if lines:
            return lines
    return _plan_contract_lines(plan, "verification_gates", "verification gates")


def _verification_gate_is_unresolved(text: str) -> bool:
    lowered = text.casefold()
    return "unresolved" in lowered or "no repo-visible verification command" in lowered


def _verification_gate_is_generic(text: str) -> bool:
    lowered = text.casefold()
    generic_markers = (
        "run targeted tests first",
        "broader checks appropriate",
        "as appropriate",
        "a narrower deterministic command is recorded",
        "appropriate to the changed surface",
    )
    return any(marker in lowered for marker in generic_markers)


def _verification_gate_toolchain_mismatch(
    text: str,
    target_artifacts: list[str],
    target_root: Path,
) -> str:
    lowered = text.casefold()
    has_python_gate = "pytest" in lowered or "pythonpath=src" in lowered
    has_node_gate = any(marker in lowered for marker in ("npm ", "pnpm ", "yarn ", "bun "))
    js_target = _target_artifacts_look_js(target_artifacts) or ((target_root / "package.json").is_file() and not _target_artifacts_look_python(target_artifacts))
    python_target = _target_artifacts_look_python(target_artifacts) or ((target_root / "pyproject.toml").is_file() and not (target_root / "package.json").is_file())
    if js_target and has_python_gate:
        return (
            "active plan verification_gates look Python/pytest-shaped while target artifacts or product_source_root expose a JavaScript/TypeScript toolchain; "
            "use repo-visible package/task/CI gates or mark the gate unresolved"
        )
    if python_target and has_node_gate and not (target_root / "package.json").is_file():
        return (
            "active plan verification_gates look Node/package-script-shaped while target artifacts expose a Python toolchain; "
            "use repo-visible Python gates or mark the gate unresolved"
        )
    return ""


def _adjacent_regression_test_ownership_reason(
    text: str,
    target_artifacts: list[str],
    write_scope_lines: list[str],
) -> str:
    write_scope_text = "\n".join(write_scope_lines).replace("\\", "/").casefold()
    explicit_tests = _dedupe_route_values(
        (*_test_artifacts_from_values(target_artifacts), *_test_paths_from_verification_gate(text))
    )
    outside_scope = [path for path in explicit_tests if path.casefold() not in write_scope_text]
    if outside_scope:
        sample = ", ".join(outside_scope[:5])
        suffix = f", +{len(outside_scope) - 5} more" if len(outside_scope) > 5 else ""
        return (
            "active plan verification_gates name regression test path(s) outside active-phase write_scope: "
            f"{sample}{suffix}; include adjacent test ownership or record a scoped widening before closeout"
        )
    if _verification_gate_runs_broad_pytest(text) and _has_python_source_target(target_artifacts) and not _test_artifacts_from_values(target_artifacts):
        return (
            "active plan uses broad pytest/full-suite verification while target_artifacts name product/source files but no regression tests; "
            "surface adjacent regression-test ownership or narrow the gate before confident closeout"
        )
    return ""


def _test_artifacts_from_values(values: list[str]) -> tuple[str, ...]:
    tests: list[str] = []
    for value in values:
        normalized = _normalize_route_metadata_path(str(value)).casefold()
        if normalized.startswith("tests/") or normalized == "tests":
            tests.append(normalized)
    return tuple(tests)


def _test_paths_from_verification_gate(text: str) -> tuple[str, ...]:
    normalized = str(text or "").replace("\\", "/")
    paths = re.findall(r"(?<![A-Za-z0-9_./-])(tests/[A-Za-z0-9_./-]+)", normalized, flags=re.IGNORECASE)
    return tuple(_normalize_route_metadata_path(path).casefold() for path in paths)


def _verification_gate_runs_broad_pytest(text: str) -> bool:
    lowered = text.casefold()
    return "pytest" in lowered and not _test_paths_from_verification_gate(text)


def _has_python_source_target(target_artifacts: list[str]) -> bool:
    for target in target_artifacts:
        normalized = _normalize_route_metadata_path(str(target)).casefold()
        if normalized.startswith("src/") or (normalized.endswith(".py") and not normalized.startswith("tests/")):
            return True
    return False


def _dedupe_route_values(values: tuple[str, ...]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_route_metadata_path(str(value)).casefold()
        if normalized and normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def _active_plan_target_root(inventory: Inventory) -> Path:
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


def _target_artifacts_look_js(target_artifacts: list[str]) -> bool:
    js_suffixes = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
    js_names = ("package.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock")
    js_prefixes = ("apps/", "packages/", "web/", "frontend/")
    for target in target_artifacts:
        normalized = _normalize_route_metadata_path(str(target)).casefold()
        if normalized.endswith(js_suffixes) or normalized in js_names or normalized.startswith(js_prefixes):
            return True
    return False


def _target_artifacts_look_python(target_artifacts: list[str]) -> bool:
    for target in target_artifacts:
        normalized = _normalize_route_metadata_path(str(target)).casefold()
        if normalized.endswith(".py") or normalized in {"pyproject.toml", "requirements.txt", "tox.ini", "noxfile.py"}:
            return True
    return False


def _active_plan_execution_policy_findings(plan: Surface, state_data: dict[str, object]) -> list[Finding]:
    active_phase = str(state_data.get("active_phase") or "")
    phase_metadata = _active_phase_contract_metadata(plan, active_phase)
    plan_data = plan.frontmatter.data if plan.frontmatter.has_frontmatter else {}
    policy_raw, policy_line = _contract_entry("execution_policy", phase_metadata, plan_data)
    auto_raw, auto_line = _contract_entry("auto_continue", phase_metadata, plan_data)
    stop_raw, stop_line = _contract_entry("stop_conditions", phase_metadata, plan_data)
    findings: list[Finding] = []

    policy = _contract_text(policy_raw).casefold()
    if not policy:
        findings.append(
            Finding(
                "info",
                "active-plan-execution-policy",
                f"active plan has no execution_policy metadata; {CURRENT_PHASE_ONLY_POLICY} default applies to active_phase {active_phase or '<unset>'}",
                plan.rel_path,
            )
        )
    elif policy == CURRENT_PHASE_ONLY_POLICY:
        findings.append(
            Finding(
                "info",
                "active-plan-execution-policy",
                f"active plan execution_policy is {CURRENT_PHASE_ONLY_POLICY}; continue only active_phase {active_phase or '<unset>'} until explicit lifecycle writeback",
                plan.rel_path,
                policy_line,
            )
        )
    else:
        findings.append(
            Finding(
                "warn",
                "active-plan-execution-policy-value",
                f"active plan execution_policy is {policy_raw!r}; expected {CURRENT_PHASE_ONLY_POLICY!r}; current-phase-only fallback applies",
                plan.rel_path,
                policy_line,
            )
        )

    auto_continue = _contract_bool(auto_raw)
    if auto_raw is None:
        findings.append(
            Finding(
                "info",
                "active-plan-auto-continue-stop",
                "auto_continue metadata is absent; current-phase-only stop applies and no future phase is authorized",
                plan.rel_path,
            )
        )
    elif auto_continue is False:
        findings.append(
            Finding(
                "info",
                "active-plan-auto-continue-stop",
                "auto_continue is false; current-phase-only stop applies and no future phase is authorized by verification success alone",
                plan.rel_path,
                auto_line,
            )
        )
    elif auto_continue is None:
        findings.append(
            Finding(
                "warn",
                "active-plan-auto-continue-value",
                f"auto_continue is {auto_raw!r}; expected true or false, so current-phase-only stop applies",
                plan.rel_path,
                auto_line,
            )
        )
    else:
        stop_conditions = _contract_list(stop_raw)
        if not stop_conditions:
            findings.append(
                Finding(
                    "warn",
                    "active-plan-auto-continue-stop-conditions",
                    "auto_continue is true but no stop_conditions metadata was found; automatic continuation is unsafe",
                    plan.rel_path,
                    stop_line or auto_line,
                )
            )
        else:
            missing = _missing_stop_condition_coverage(stop_conditions)
            if missing:
                findings.append(
                    Finding(
                        "warn",
                        "active-plan-auto-continue-stop-conditions",
                        f"auto_continue is true but stop_conditions miss coverage for: {', '.join(missing)}",
                        plan.rel_path,
                        stop_line or auto_line,
                    )
                )
            else:
                findings.append(
                    Finding(
                        "info",
                        "active-plan-auto-continue-candidate",
                        "auto_continue is explicit and stop_conditions cover verification, authority, write-scope, source-reality, sensitive-action, and closeout boundaries",
                        plan.rel_path,
                        auto_line,
                    )
                )

    if stop_raw in (None, ""):
        findings.append(
            Finding(
                "info",
                "active-plan-stop-conditions",
                "stop_conditions metadata is absent; current-phase-only remains the safe default stop",
                plan.rel_path,
            )
        )
    return findings


def _contract_entry(
    key: str,
    phase_metadata: dict[str, tuple[object, int]],
    plan_data: dict[str, object],
) -> tuple[object | None, int | None]:
    if key in phase_metadata:
        value, line = phase_metadata[key]
        return value, line
    if key in plan_data:
        return plan_data[key], None
    return None, None


def _active_phase_contract_lines(plan: Surface, active_phase: str, *labels: str) -> list[tuple[str, int]]:
    block = _active_phase_block(plan.content, active_phase)
    if block is None:
        return []
    return _contract_lines_in_range(plan.content.splitlines(keepends=True), block[0] + 1, block[1], *labels)


def _plan_contract_lines(plan: Surface, *labels: str) -> list[tuple[str, int]]:
    lines = plan.content.splitlines(keepends=True)
    return _contract_lines_in_range(lines, 0, len(lines), *labels)


def _contract_lines_in_range(lines: list[str], start: int, end: int, *labels: str) -> list[tuple[str, int]]:
    normalized_labels = {_normalize_contract_label(label) for label in labels}
    matches: list[tuple[str, int]] = []
    for index in range(start, end):
        match = re.match(r"^\s*[-*]\s*([^:]+)\s*:\s*(.*?)\s*(?:\r?\n)?$", lines[index])
        if not match:
            continue
        if _normalize_contract_label(match.group(1)) in normalized_labels:
            matches.append((_contract_text(match.group(2)), index + 1))
    return matches


def _normalize_contract_label(value: str) -> str:
    return _contract_text(value).casefold().replace("-", "_").replace(" ", "_")


def _active_phase_contract_metadata(plan: Surface, active_phase: str) -> dict[str, tuple[object, int]]:
    block = _active_phase_block(plan.content, active_phase)
    if block is None:
        return {}
    lines = plan.content.splitlines(keepends=True)
    metadata: dict[str, tuple[object, int]] = {}
    for index in range(block[0] + 1, block[1]):
        match = re.match(
            r"^\s*[-*]\s*(execution_policy|auto_continue|stop_conditions)\s*:\s*(.*?)\s*(?:\r?\n)?$",
            lines[index],
            re.IGNORECASE,
        )
        if not match:
            continue
        key = match.group(1).casefold()
        raw_value = match.group(2).strip()
        if key == "stop_conditions" and raw_value == "":
            metadata[key] = (_phase_list_values(lines, index + 1, block[1]), index + 1)
        else:
            metadata[key] = (_contract_parse_scalar(raw_value), index + 1)
    return metadata


def _active_phase_block(text: str, active_phase: str) -> tuple[int, int] | None:
    target = active_phase.strip()
    if not target:
        return None
    lines = text.splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,6})\s+(.+?)\s*#*\s*(?:\r?\n)?$", line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))
    candidates: list[tuple[int, int]] = []
    for heading_index, (start, level, title) in enumerate(headings):
        end = len(lines)
        for next_start, next_level, _next_title in headings[heading_index + 1 :]:
            if next_level <= level:
                end = next_start
                break
        if _contract_heading_matches(title, target) or _phase_block_has_contract_id(lines, start, end, target):
            candidates.append((start, end))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[1] - item[0], item[0]))


def _contract_heading_matches(title: str, active_phase: str) -> bool:
    normalized_title = _contract_text(title).casefold()
    normalized_phase = active_phase.casefold()
    return normalized_title == normalized_phase or normalized_phase in normalized_title


def _phase_block_has_contract_id(lines: list[str], start: int, end: int, active_phase: str) -> bool:
    for line in lines[start + 1 : end]:
        match = re.match(r"^\s*[-*]\s*id\s*:\s*(.+?)\s*(?:\r?\n)?$", line, re.IGNORECASE)
        if match and _contract_text(match.group(1)) == active_phase:
            return True
    return False


def _phase_list_values(lines: list[str], start: int, end: int) -> list[str]:
    values: list[str] = []
    for index in range(start, end):
        match = re.match(r"^\s+[-*]\s+(.+?)\s*(?:\r?\n)?$", lines[index])
        if not match:
            break
        values.append(_contract_text(match.group(1)))
    return values


def _contract_parse_scalar(raw_value: str) -> object:
    value = _contract_text(raw_value)
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_contract_parse_scalar(part.strip()) for part in inner.split(",")]
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return value


def _contract_text(value: object) -> str:
    text = str(value or "").strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()
    if text.startswith("`") and text.endswith("`") and len(text) >= 2:
        text = text[1:-1].strip()
    return text


def _contract_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = _contract_text(value).casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _contract_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_contract_text(item) for item in value if _contract_text(item)]
    text = _contract_text(value)
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_contract_text(part) for part in inner.split(",") if _contract_text(part)]
    return [text]


def _missing_stop_condition_coverage(stop_conditions: list[str]) -> list[str]:
    normalized = "\n".join(stop_conditions).casefold()
    missing: list[str] = []
    for label, markers in AUTO_CONTINUE_STOP_COVERAGE:
        if not any(marker in normalized for marker in markers):
            missing.append(label)
    return missing


def _active_plan_lifecycle_drift_findings(inventory: Inventory, plan: Surface, state_data: dict[str, object]) -> list[Finding]:
    findings: list[Finding] = []
    phase_status = str(state_data.get("phase_status") or "")
    if not phase_status or phase_status not in PHASE_STATUS_VALUES:
        return findings

    if plan.frontmatter.has_frontmatter:
        plan_status = str(plan.frontmatter.data.get("status") or "")
        if plan_status and plan_status != phase_status and phase_status == "complete" and plan_status == "active":
            findings.append(
                Finding(
                    "warn",
                    "active-plan-lifecycle-drift",
                    (
                        "project-state phase_status is complete but active-plan frontmatter status is active; "
                        "writeback --apply --phase-status complete synchronizes the derived active-plan status copy"
                    ),
                    plan.rel_path,
                )
            )

    active_phase = str(state_data.get("active_phase") or "")
    body_fact = active_plan_phase_body_status_fact(plan, active_phase)
    handoff_body_drift = bool(
        body_fact and phase_status == "pending" and body_fact.value in PHASE_BODY_TERMINAL_STATUS_VALUES
    )
    findings.extend(active_plan_completed_phase_handoff_findings(inventory))
    if body_fact:
        expected_body_status = canonical_phase_body_status(phase_status)
        if body_fact.value != expected_body_status and not handoff_body_drift:
            findings.append(
                Finding(
                    "warn",
                    "active-plan-phase-body-drift",
                    (
                        f"project-state phase_status is {phase_status!r} but active-plan phase block {active_phase!r} "
                        f"body status is {body_fact.value!r}; writeback --apply --phase-status {phase_status} "
                        f"synchronizes that phase block to {expected_body_status!r}"
                    ),
                    body_fact.source,
                    body_fact.line,
                )
            )
    if active_phase and phase_status == "pending":
        active_body_status_line = body_fact.line if body_fact else None
        for prior_fact in active_plan_preceding_phase_body_status_facts(plan, active_phase):
            if _phase_label_matches_active_phase(prior_fact.phase, active_phase):
                continue
            if active_body_status_line is not None and prior_fact.line == active_body_status_line:
                continue
            if prior_fact.value in PHASE_BODY_TERMINAL_STATUS_VALUES:
                continue
            findings.append(
                Finding(
                    "warn",
                    "active-plan-prior-phase-open",
                    (
                        f"project-state active_phase is {active_phase!r} with phase_status 'pending', but earlier active-plan "
                        f"phase block {prior_fact.phase!r} has body status {prior_fact.value!r}; "
                        f"writeback --apply --active-phase {active_phase} --phase-status pending completes the prior current phase "
                        "and advances the next pending phase in one lifecycle writeback"
                    ),
                    prior_fact.source,
                    prior_fact.line,
                )
            )

    closeout_facts = state_writeback_facts(inventory.state)
    closeout_values = {field: fact.value for field, fact in closeout_facts.items()}
    next_state_fact = closeout_facts.get("next_state")
    if next_state_fact and _contract_text(next_state_fact.value).casefold() == NEXT_STATE_LEGACY_HUMAN_DECISION_REQUIRED:
        findings.append(
            Finding(
                "warn",
                "active-plan-next-state-legacy-alias",
                (
                    f"project-state closeout next_state uses legacy {NEXT_STATE_LEGACY_HUMAN_DECISION_REQUIRED}; "
                    f"rerun writeback with {NEXT_STATE_EXPLICIT_DECISION_REQUIRED} before removing alias compatibility"
                ),
                next_state_fact.source,
                next_state_fact.line,
            )
        )
    if (
        state_data.get("plan_status") == "active"
        and phase_status == "complete"
        and closeout_values_are_complete(closeout_values)
        and state_writeback_identity_matches_current_plan(inventory)
    ):
        findings.append(
            Finding(
                "info",
                "active-plan-ready-for-closeout",
                (
                    "project-state phase_status is complete and closeout facts are complete while the active plan is still open; "
                    "this is a ready-for-closeout boundary, and writeback --apply --archive-active-plan is the explicit archive path"
                ),
                plan.rel_path,
            )
        )
    return findings


def _phase_label_matches_active_phase(phase: str, active_phase: str) -> bool:
    return _contract_text(phase).casefold() == _contract_text(active_phase).casefold()


def _active_plan_docs_decision_findings(inventory: Inventory, plan: Surface, state_data: dict[str, object]) -> list[Finding]:
    if not plan.frontmatter.has_frontmatter or "docs_decision" not in plan.frontmatter.data:
        return []
    value = str(plan.frontmatter.data.get("docs_decision") or "")
    if value not in DOCS_DECISION_VALUES:
        return [
            Finding(
                "warn",
                "active-plan-docs-decision-value",
                f"active plan docs_decision is {value!r}; expected one of: not-needed, uncertain, updated",
                plan.rel_path,
            )
        ]
    if value == "uncertain" and str(state_data.get("phase_status") or "") == "complete":
        next_phase = _active_plan_next_phase_id(plan, str(state_data.get("active_phase") or ""))
        if next_phase and _active_plan_has_current_phase_evidence(inventory):
            return [
                Finding(
                    "info",
                    "active-plan-docs-decision-provisional-phase-handoff",
                    (
                        "active plan frontmatter docs_decision is uncertain while phase_status is complete, "
                        "but current-plan phase evidence is present; this is a phase-ready provisional handoff, "
                        "not confident final closeout. next_safe_command=mylittleharness --root <root> "
                        f"writeback --dry-run --active-phase {next_phase} --phase-status pending --docs-decision uncertain. "
                        "Final closeout/archive still requires docs_decision updated/not-needed and an explicit "
                        "writeback/archive route"
                    ),
                    plan.rel_path,
                )
            ]
        return [
            Finding(
                "warn",
                "active-plan-docs-decision-uncertain",
                "active plan frontmatter docs_decision is uncertain while phase_status is complete without a next-phase provisional evidence posture; record updated/not-needed for final closeout or keep closeout language provisional; next_safe_command=mylittleharness --root <root> suggest --intent \"docs decision closeout\"",
                plan.rel_path,
            )
        ]
    return []


def _active_plan_completion_policy_findings(inventory: Inventory, plan: Surface, state_data: dict[str, object]) -> list[Finding]:
    if not plan.frontmatter.has_frontmatter:
        return []
    completion_policy = _contract_text(plan.frontmatter.data.get("completion_policy") or "").casefold()
    if completion_policy != "through-closeout":
        return []
    if str(state_data.get("plan_status") or "") != "active":
        return []
    if str(state_data.get("phase_status") or "") != "complete":
        return []
    active_phase = str(state_data.get("active_phase") or "")
    next_phase = _active_plan_next_phase_id(plan, active_phase)
    if not next_phase:
        return []
    docs_decision = str(plan.frontmatter.data.get("docs_decision") or "").strip()
    docs_arg = f" --docs-decision {docs_decision}" if docs_decision in DOCS_DECISION_VALUES else ""
    command = (
        "mylittleharness --root <root> writeback --dry-run "
        f"--active-phase {next_phase} --phase-status pending{docs_arg}"
    )
    if _active_plan_has_current_phase_evidence(inventory):
        return [
            Finding(
                "info",
                "active-plan-through-closeout-pending-phases",
                (
                    "active plan completion_policy=through-closeout and current phase_status is complete, "
                    f"but pending successor phase {next_phase!r} remains; the plan is not done. "
                    f"next_safe_command={command}; this previews phase advancement only and does not approve "
                    "auto_continue, closeout, archive, roadmap done-status, next-plan opening, staging, or commit"
                ),
                plan.rel_path,
            )
        ]
    return [
        Finding(
            "warn",
            "active-plan-through-closeout-pending-evidence",
            (
                "active plan completion_policy=through-closeout and current phase_status is complete, "
                f"but pending successor phase {next_phase!r} remains without complete repo-visible phase evidence; "
                "record docs_decision, state_writeback, verification, and work_result before continuing. "
                f"After evidence review, next_safe_command={command}"
            ),
            plan.rel_path,
        )
    ]


def _active_plan_has_current_phase_evidence(inventory: Inventory) -> bool:
    facts = state_writeback_facts(inventory.state)
    if not facts or not state_writeback_identity_matches_current_plan(inventory):
        return False
    values = {field: fact.value for field, fact in facts.items()}
    return not _missing_phase_evidence_fields(values)


def _active_plan_next_phase_id(plan: Surface, active_phase: str) -> str:
    active_normalized = _contract_text(active_phase).casefold()
    if not active_normalized:
        return ""
    phase_ids = _active_plan_ordered_phase_ids(plan)
    for index, phase_id in enumerate(phase_ids):
        if _contract_text(phase_id).casefold() == active_normalized:
            if index + 1 < len(phase_ids):
                return phase_ids[index + 1]
            return ""
    return ""


def _active_plan_ordered_phase_ids(plan: Surface) -> list[str]:
    lines = plan.content.splitlines()
    in_phases = False
    phase_ids: list[str] = []
    current_heading = ""
    for line in lines:
        if line.startswith("## "):
            in_phases = _contract_text(line.lstrip("# ")).casefold() == "phases"
            current_heading = ""
            continue
        if not in_phases:
            continue
        heading_match = re.match(r"^###\s+(.+?)\s*$", line)
        if heading_match:
            current_heading = _contract_text(heading_match.group(1))
            if current_heading and current_heading not in phase_ids:
                phase_ids.append(current_heading)
            continue
        id_match = re.match(r"^-\s*id:\s*`?([^`\n]+?)`?\s*$", line)
        if id_match:
            phase_id = _contract_text(id_match.group(1))
            if not phase_id:
                continue
            if current_heading and phase_ids and phase_ids[-1] == current_heading:
                phase_ids[-1] = phase_id
            elif phase_id not in phase_ids:
                phase_ids.append(phase_id)
    return phase_ids


def _active_plan_writeback_drift_findings(inventory: Inventory, plan: Surface, state_data: dict[str, object]) -> list[Finding]:
    if str(state_data.get("phase_status") or "") != "complete":
        return []
    facts = state_writeback_facts(inventory.state)
    if not facts:
        return []
    if not state_writeback_identity_matches_current_plan(inventory):
        return []
    findings: list[Finding] = []
    if plan.frontmatter.has_frontmatter:
        for field, fact in facts.items():
            plan_value = plan.frontmatter.data.get(field)
            if plan_value in (None, ""):
                continue
            if str(plan_value) != fact.value:
                findings.append(
                    Finding(
                        "warn",
                        "active-plan-writeback-drift",
                        (
                            f"active plan frontmatter {field} is {plan_value!r} but project-state MLH closeout "
                            f"writeback records {fact.value!r}; writeback --apply synchronizes derived active-plan copies"
                        ),
                        plan.rel_path,
                    )
                )
    body_facts = active_plan_body_facts(plan)
    for field, fact in facts.items():
        body_fact = body_facts.get(field)
        if body_fact and body_fact.value != fact.value:
            findings.append(
                Finding(
                    "warn",
                    "active-plan-writeback-drift",
                    (
                        f"active plan body {field} is {body_fact.value!r} but project-state MLH closeout "
                        f"writeback records {fact.value!r}; writeback --apply synchronizes derived active-plan copies"
                    ),
                    body_fact.source,
                    body_fact.line,
                )
            )
    if findings and closeout_values_are_complete({field: fact.value for field, fact in facts.items()}):
        findings.append(
            Finding(
                "info",
                "active-plan-writeback-drift-rail",
                (
                    "matching project-state closeout authority is complete; preview the atomic closeout/archive rail with "
                    "`mylittleharness --root <root> writeback --dry-run --archive-active-plan`, which carries those facts "
                    "into the archived plan copy and retargets closeout identity before any apply. Use non-archive "
                    "writeback only when the plan should stay active; this report does not approve archive, roadmap done-status, "
                    "staging, commit, rollback, or next-plan opening"
                ),
                plan.rel_path,
            )
        )
    return findings


def _active_plan_work_result_capsule_findings(inventory: Inventory, plan: Surface, state_data: dict[str, object]) -> list[Finding]:
    if str(state_data.get("phase_status") or "") != "complete":
        return []
    facts = state_writeback_facts(inventory.state)
    if not facts:
        return []
    if not state_writeback_identity_matches_current_plan(inventory):
        return []
    closeout_values = {field: fact.value for field, fact in facts.items()}
    if not closeout_values_are_complete(closeout_values):
        return []

    fact = facts.get("work_result")
    if fact is None:
        return [
            Finding(
                "warn",
                "active-plan-work-result-capsule-missing",
                (
                    "phase_status is complete and closeout facts are complete, but project-state MLH closeout "
                    "writeback has no plain-language work_result capsule; rerun writeback with closeout facts or "
                    "--work-result so the handoff explains what changed, what became better, how it was checked, and what remains"
                ),
                inventory.state.rel_path if inventory.state else "project/project-state.md",
            )
        ]

    normalized = fact.value.casefold()
    has_result = "result:" in normalized
    has_change = _work_result_contains_any_label(normalized, ("what changed:", "what was done:"))
    has_check = _work_result_contains_any_label(
        normalized,
        (
            "how it was checked:",
            "how checked:",
            "checked by:",
            "verification:",
        ),
    )
    has_remaining = _work_result_contains_any_label(normalized, ("what remains:", "no required follow-up"))
    if not (has_result and has_change and has_check and has_remaining):
        return [
            Finding(
                "warn",
                "active-plan-work-result-capsule-thin",
                (
                    "project-state MLH closeout writeback has work_result, but it does not read like a complete "
                    "plain-language capsule; include Result, What changed or What was done, How it was checked "
                    "(or How checked/Verification), and What remains"
                ),
                fact.source,
                fact.line,
            )
        ]

    return [
        Finding(
            "info",
            "active-plan-work-result-capsule",
            "project-state MLH closeout writeback records a plain-language work_result capsule for this completed phase",
            fact.source,
            fact.line,
        )
    ]


def _work_result_contains_any_label(normalized_text: str, labels: tuple[str, ...]) -> bool:
    return any(label in normalized_text for label in labels)


def _active_plan_phase_evidence_findings(inventory: Inventory, state_data: dict[str, object]) -> list[Finding]:
    if str(state_data.get("phase_status") or "") != "complete":
        return []

    source = inventory.state.rel_path if inventory.state else "project/project-state.md"
    facts = state_writeback_facts(inventory.state)
    if not facts:
        return [
            Finding(
                "warn",
                "active-plan-phase-evidence-missing",
                (
                    "project-state phase_status is complete, but no repo-visible phase evidence is attached to the "
                    "current active plan; record at least docs_decision, state_writeback, verification, and work_result "
                    "with `mylittleharness --root <root> writeback --dry-run --phase-status complete --docs-decision "
                    "uncertain --state-writeback \"<phase evidence>\" --verification \"<command/result>\" --work-result "
                    "\"<plain-language capsule>\"`; docs_decision uncertain is allowed for provisional phase handoff "
                    "but not confident final closeout"
                ),
                source,
            )
        ]

    if not state_writeback_identity_matches_current_plan(inventory):
        first_fact = next(iter(facts.values()))
        return [
            Finding(
                "warn",
                "active-plan-phase-evidence-stale",
                (
                    "project-state phase_status is complete, but the recorded closeout/phase evidence does not match "
                    "the current active plan identity; record same-request phase evidence before relying on closeout, "
                    "archive, roadmap done-status, or next-plan movement"
                ),
                first_fact.source,
                first_fact.line,
            )
        ]

    values = {field: fact.value for field, fact in facts.items()}
    missing = _missing_phase_evidence_fields(values)
    if missing:
        first_fact = next(iter(facts.values()))
        return [
            Finding(
                "warn",
                "active-plan-phase-evidence-thin",
                (
                    "project-state phase_status is complete, but phase evidence is missing structural field(s): "
                    f"{', '.join(missing)}; record a provisional handoff with docs_decision uncertain plus "
                    "state_writeback, verification, and work_result, or record updated/not-needed docs_decision "
                    "when preparing confident final closeout"
                ),
                first_fact.source,
                first_fact.line,
            )
        ]

    verification_fact = facts.get("verification")
    findings = [
        Finding(
            "info",
            "active-plan-phase-evidence",
            "project-state phase_status is complete with repo-visible phase evidence for docs_decision, state_writeback, verification, and work_result",
            verification_fact.source if verification_fact else source,
            verification_fact.line if verification_fact else None,
        )
    ]
    findings.extend(
        acceptance_evidence_findings(
            inventory,
            values,
            completion_reason="completed active-plan phase",
            apply=False,
            code_prefix="active-plan",
            include_success=True,
        )
    )
    findings.extend(
        completion_gate_packet_findings(
            inventory,
            values,
            completion_reason="completed active-plan phase",
            code_prefix="active-plan",
            include_success=True,
        )
    )
    return findings


def _missing_phase_evidence_fields(values: dict[str, str]) -> tuple[str, ...]:
    missing: list[str] = []
    docs_decision = str(values.get("docs_decision") or "").strip().casefold()
    if docs_decision not in DOCS_DECISION_VALUES:
        missing.append("docs_decision")
    for field in ("state_writeback", "verification", "work_result"):
        if not _phase_evidence_value_is_present(values.get(field, "")):
            missing.append(field)
    return tuple(missing)


def _phase_evidence_value_is_present(value: object) -> bool:
    normalized = re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".").casefold()
    return normalized not in INCOMPLETE_EVIDENCE_VALUES


def _spec_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    existing = {surface.path.name for surface in inventory.surfaces if surface.role == "stable-spec" and surface.exists}
    for name in EXPECTED_SPEC_NAMES:
        if name not in existing:
            findings.append(Finding("error", "missing-stable-spec", f"missing expected workflow spec: project/specs/workflow/{name}"))
    return findings


def _spec_lifecycle_posture_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []

    plan_facing_specs = _plan_facing_spec_paths(inventory)
    findings: list[Finding] = []
    for surface in inventory.present_surfaces:
        if not _is_spec_lifecycle_surface(surface):
            continue
        if surface.frontmatter.errors:
            continue

        has_lifecycle_fields = any(key in surface.frontmatter.data for key in SPEC_LIFECYCLE_FIELDS)
        posture_required = surface.rel_path in plan_facing_specs or has_lifecycle_fields
        if not posture_required:
            continue

        if not surface.frontmatter.has_frontmatter:
            findings.append(_spec_posture_missing_finding(surface, "frontmatter", None))
            continue

        spec_status, status_findings = _spec_lifecycle_field_value(
            surface,
            "spec_status",
            SPEC_STATUS_VALUES,
            "spec-status-value",
        )
        implementation_posture, posture_findings = _spec_lifecycle_field_value(
            surface,
            "implementation_posture",
            SPEC_IMPLEMENTATION_POSTURE_VALUES,
            "spec-implementation-posture-value",
        )
        findings.extend(status_findings)
        findings.extend(posture_findings)
        if not spec_status or not implementation_posture:
            continue

        findings.append(
            Finding(
                "info",
                "spec-posture-state",
                (
                    f"{surface.rel_path} spec_status='{spec_status}' and "
                    f"implementation_posture='{implementation_posture}' are tracked separately; "
                    "docs_decision remains closeout-local"
                ),
                surface.rel_path,
            )
        )

        if implementation_posture == "synced" and not _spec_has_any_field_value(surface, SPEC_IMPLEMENTATION_EVIDENCE_FIELDS):
            findings.append(
                Finding(
                    "warn",
                    "spec-synced-without-verification",
                    (
                        f"{surface.rel_path} implementation_posture='synced' has no verification_refs, "
                        "related_verification, implemented_by, closeout_evidence, or implementation_evidence; "
                        "reconcile is read-only and cannot infer implementation approval"
                    ),
                    surface.rel_path,
                    _frontmatter_key_line(surface, "implementation_posture"),
                    route_id=surface.memory_route,
                    requires_human_gate=True,
                    gate_class="authority",
                    human_gate_reason="sync claims require source-bound verification or closeout evidence",
                    allowed_decisions=("add-verification", "mark-partial", "amend-spec"),
                )
            )

        if implementation_posture == "target-only":
            if _spec_has_any_field_value(surface, SPEC_IMPLEMENTATION_EVIDENCE_FIELDS):
                findings.append(
                    Finding(
                        "warn",
                        "spec-target-only-has-implementation-evidence",
                        (
                            f"{surface.rel_path} implementation_posture='target-only' but implementation evidence "
                            "fields are present; reconcile should propose posture review without rewriting the spec"
                        ),
                        surface.rel_path,
                        _frontmatter_key_line(surface, "implementation_posture"),
                        route_id=surface.memory_route,
                        requires_human_gate=True,
                        gate_class="authority",
                        human_gate_reason="target-only specs with evidence need explicit posture review",
                        allowed_decisions=("keep-target-only", "mark-in-progress", "mark-partially-verified", "mark-synced"),
                    )
                )
            elif spec_status == "accepted":
                findings.append(
                    Finding(
                        "info",
                        "spec-target-only-preserved",
                        (
                            f"{surface.rel_path} is accepted target-only spec authority; do not delete it solely "
                            "because implementation evidence is absent"
                        ),
                        surface.rel_path,
                        _frontmatter_key_line(surface, "implementation_posture"),
                        route_id=surface.memory_route,
                        requires_human_gate=True,
                        gate_class="authority",
                        human_gate_reason="spec deletion, supersession, or retirement requires explicit human-gated lifecycle action",
                        allowed_decisions=("keep-target-only", "supersede", "archive", "implement"),
                    )
                )

        if implementation_posture == "drift-detected" and not _spec_has_any_field_value(surface, SPEC_CARRY_FORWARD_FIELDS):
            findings.append(
                Finding(
                    "warn",
                    "spec-drift-detected-without-carry-forward",
                    (
                        f"{surface.rel_path} implementation_posture='drift-detected' has no carry_forward, "
                        "related plan/roadmap/decision/ADR, amendment plan, replan route, drift record, or supersession target"
                    ),
                    surface.rel_path,
                    _frontmatter_key_line(surface, "implementation_posture"),
                    route_id=surface.memory_route,
                    requires_human_gate=True,
                    gate_class="authority",
                    human_gate_reason="drift resolution requires explicit amendment, replan, or carry-forward evidence",
                    allowed_decisions=("record-carry-forward", "amend-spec", "replan", "supersede"),
                )
            )

        if (
            spec_status == "superseded" or implementation_posture in {"deprecated-compat", "retired"}
        ) and not _spec_has_any_field_value(surface, SPEC_SUPERSESSION_TARGET_FIELDS):
            findings.append(
                Finding(
                    "warn",
                    "spec-superseded-without-target",
                    (
                        f"{surface.rel_path} records spec_status='{spec_status}' and "
                        f"implementation_posture='{implementation_posture}' without superseded_by, replacement, "
                        "retirement_path, deprecation_path, or archived_to; supersession, deprecation, "
                        "and retirement require a named replacement or retirement path"
                    ),
                    surface.rel_path,
                    _frontmatter_key_line(surface, "spec_status") or _frontmatter_key_line(surface, "implementation_posture"),
                    route_id=surface.memory_route,
                    requires_human_gate=True,
                    gate_class="authority",
                    human_gate_reason="supersession, deprecation, and retirement require a named replacement or retirement path",
                    allowed_decisions=("add-replacement", "add-retirement-path", "archive", "amend-spec"),
                )
            )

    if findings:
        findings.append(
            Finding(
                "info",
                "spec-reconcile-authority",
                (
                    "spec lifecycle posture diagnostics are read-only reconcile cues; they cannot rewrite specs, "
                    "delete target-only contracts, approve supersession, archive, closeout, staging, commit, or lifecycle movement"
                ),
            )
        )
    return findings


def _is_spec_lifecycle_surface(surface: Surface) -> bool:
    return surface.memory_route == "stable-specs" or (
        surface.memory_route == "product-docs" and surface.rel_path.startswith("docs/specs/")
    )


def _plan_facing_spec_paths(inventory: Inventory) -> set[str]:
    paths: set[str] = set()
    plan = inventory.active_plan_surface
    if plan and plan.exists and not plan.frontmatter.errors:
        paths.update(_string_values(plan.frontmatter.data.get("related_specs")))

    roadmap_items, parse_findings = roadmap_items_for_diagnostics(inventory)
    if not parse_findings:
        for item in roadmap_items.values():
            status = str(item.fields.get("status") or "").strip().casefold()
            if status in ROUTE_REFERENCE_ACCEPTED_STATUSES:
                paths.update(_string_values(item.fields.get("related_specs")))
    return {path.replace("\\", "/").strip().strip("/") for path in paths if _route_metadata_value_is_path_like(path)}


def _spec_lifecycle_field_value(
    surface: Surface,
    key: str,
    allowed_values: tuple[str, ...],
    invalid_code: str,
) -> tuple[str, list[Finding]]:
    value = surface.frontmatter.data.get(key)
    line = _frontmatter_key_line(surface, key)
    if value in (None, ""):
        return "", [_spec_posture_missing_finding(surface, key, line)]
    if not isinstance(value, str) or not value.strip():
        return "", [
            Finding(
                "warn",
                "spec-posture-field",
                f"{surface.rel_path} {key} must be a non-empty scalar string",
                surface.rel_path,
                line,
            )
        ]

    normalized = _normalize_spec_lifecycle_value(value)
    if normalized not in allowed_values:
        return "", [
            Finding(
                "warn",
                invalid_code,
                (
                    f"{surface.rel_path} {key} is {value!r}; allowed values: "
                    f"{', '.join(allowed_values)}; advisory only, no lifecycle approval"
                ),
                surface.rel_path,
                line,
                route_id=surface.memory_route,
                allowed_decisions=allowed_values,
            )
        ]
    return normalized, []


def _spec_posture_missing_finding(surface: Surface, field: str, line: int | None) -> Finding:
    return Finding(
        "warn",
        "spec-posture-missing",
        (
            f"{surface.rel_path} is plan-facing or spec-posture opted-in but lacks explicit {field}; "
            "expected separate spec_status and implementation_posture metadata"
        ),
        surface.rel_path,
        line,
        route_id=surface.memory_route,
        requires_human_gate=True,
        gate_class="authority",
        human_gate_reason="spec posture metadata changes are human-reviewed spec amendments",
        allowed_decisions=("add-spec-status", "add-implementation-posture", "record-target-only"),
    )


def _normalize_spec_lifecycle_value(value: str) -> str:
    return value.strip().casefold().replace("_", "-")


def _spec_has_any_field_value(surface: Surface, fields: tuple[str, ...]) -> bool:
    return any(_frontmatter_value_present(surface.frontmatter.data.get(field)) for field in fields)


def _frontmatter_value_present(value: object) -> bool:
    if value in (None, ""):
        return False
    if isinstance(value, list):
        return any(_frontmatter_value_present(item) for item in value)
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str) and item.strip())
    return ()


def _frontmatter_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    for surface in inventory.present_surfaces:
        for error in surface.frontmatter.errors:
            severity = (
                "error"
                if surface.rel_path == "project/project-state.md"
                or (inventory.root_kind == "live_operating_root" and lifecycle_markdown_requires_frontmatter(surface))
                else "warn"
            )
            findings.append(Finding(severity, "frontmatter-parse", error, surface.rel_path))
        if inventory.root_kind != "live_operating_root":
            continue
        if not lifecycle_markdown_requires_frontmatter(surface) or surface.frontmatter.has_frontmatter:
            continue
        if surface.memory_route == "research":
            findings.append(Finding("error", "research-frontmatter", "research artifact has no frontmatter", surface.rel_path))
        else:
            findings.append(
                Finding(
                    "error",
                    "lifecycle-frontmatter",
                    (
                        f"{surface.memory_route or surface.role} lifecycle markdown artifact has no frontmatter; "
                        "new files should be written through the owning MLH route so route metadata is explicit and "
                        "generated projection/SQLite cache can be marked dirty or rebuilt"
                    ),
                    surface.rel_path,
                    route_id=surface.memory_route,
                )
            )
    return findings


def _lifecycle_markdown_requires_frontmatter(surface: Surface) -> bool:
    return lifecycle_markdown_requires_frontmatter(surface)


def archive_context_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "info",
                "archive-context-skipped-root-kind",
                "archive context audit runs only for live operating roots and remains read-only",
            )
        ]

    archive_dir = inventory.root / ARCHIVE_CONTEXT_ARCHIVE_DIR_REL
    archive_dir_violation = source_path_boundary_violation(inventory.root, archive_dir, label="archive context archive directory")
    if archive_dir_violation is not None:
        return [
            Finding(
                "warn",
                "archive-context-archive-dir",
                archive_dir_violation.message,
                ARCHIVE_CONTEXT_ARCHIVE_DIR_REL,
            )
        ]
    if archive_dir.exists() and not archive_dir.is_dir():
        return [
            Finding(
                "warn",
                "archive-context-archive-dir",
                f"{ARCHIVE_CONTEXT_ARCHIVE_DIR_REL} exists but is not a directory; archive context coverage cannot be scanned",
                ARCHIVE_CONTEXT_ARCHIVE_DIR_REL,
            )
        ]

    roadmap_items, parse_findings = roadmap_items_for_diagnostics(inventory)
    findings: list[Finding] = [*parse_findings]
    findings.extend(roadmap_terminal_related_plan_findings(inventory))
    roadmap_surface = inventory.surface_by_rel.get(ROADMAP_REL)
    roadmap_text = roadmap_surface.content if roadmap_surface and roadmap_surface.exists else ""

    archive_ref_records_by_route: dict[str, list[ArchiveContextRouteRef]] = {}
    done_without_archive: list[str] = []
    terminal_stub_without_archive: list[str] = []
    terminal_stub_prose_refs: dict[str, tuple[str, ...]] = {}
    for item_id, item in sorted(roadmap_items.items(), key=lambda row: (row[1].start, row[0])):
        status = str(item.fields.get("status") or "").strip().casefold()
        archived_plan = _archive_context_normalize_rel(item.fields.get("archived_plan"))
        related_plan = _archive_context_normalize_rel(item.fields.get("related_plan"))
        if archived_plan:
            _archive_context_record_route_ref(archive_ref_records_by_route, archived_plan, item_id, "archived_plan", status, ROADMAP_REL, item.start + 1)
        if related_plan.startswith(f"{ARCHIVE_CONTEXT_ARCHIVE_DIR_REL}/"):
            _archive_context_record_route_ref(archive_ref_records_by_route, related_plan, item_id, "related_plan", status, ROADMAP_REL, item.start + 1)
        if status == "done" and not archived_plan:
            if _archive_context_is_terminal_history_stub_item(item):
                terminal_stub_without_archive.append(item_id)
            else:
                done_without_archive.append(item_id)

    for archive_ref in _archive_context_archive_refs_from_text(roadmap_text):
        if archive_ref in archive_ref_records_by_route:
            continue
        lines = _archive_context_reference_lines(roadmap_text, archive_ref)
        terminal_item_ids = _archive_context_terminal_stub_item_ids_for_lines(roadmap_items, lines)
        if terminal_item_ids:
            terminal_stub_prose_refs[archive_ref] = terminal_item_ids
            continue
        _archive_context_record_route_ref(
            archive_ref_records_by_route,
            archive_ref,
            "roadmap-prose",
            "prose",
            "",
            ROADMAP_REL,
            lines[0] if lines else None,
        )

    present_archive_paths = _archive_context_present_archive_paths(archive_dir)
    present_archives = {path.relative_to(inventory.root).as_posix(): path for path in present_archive_paths}
    archive_refs_by_route = {rel: {record.owner for record in records} for rel, records in archive_ref_records_by_route.items()}
    referenced_routes = set(archive_refs_by_route)
    missing_routes = sorted(rel for rel in referenced_routes if rel not in present_archives and _archive_context_safe_rel(rel))
    unreferenced_routes = sorted(rel for rel in present_archives if rel not in referenced_routes)

    findings.append(
        Finding(
            "info",
            "archive-context-summary",
            (
                f"archive context scan: {len(present_archives)} present archived plan file(s), "
                f"{len(referenced_routes)} roadmap archived-plan route reference(s), "
                f"{len(missing_routes)} missing referenced archive target(s), "
                f"{len(unreferenced_routes)} present unreferenced archive file(s); diagnostic only"
            ),
            ARCHIVE_CONTEXT_ARCHIVE_DIR_REL,
        )
    )
    if done_without_archive:
        findings.append(
            Finding(
                "warn",
                "archive-context-done-missing-archived-plan",
                (
                    f"{len(done_without_archive)} done roadmap item(s) lack archived_plan metadata: "
                    f"{_archive_context_sample(done_without_archive)}; bounded recovery action: refresh the item through writeback/roadmap after review"
                ),
                ROADMAP_REL,
            )
        )
    if terminal_stub_without_archive or terminal_stub_prose_refs:
        details: list[str] = []
        if terminal_stub_without_archive:
            details.append(f"items_without_archived_plan={_archive_context_sample(terminal_stub_without_archive)}")
        if terminal_stub_prose_refs:
            route_details = [
                f"{route} via {_archive_context_sample(item_ids)}"
                for route, item_ids in sorted(terminal_stub_prose_refs.items())
            ]
            details.append(f"prose_archive_refs={_archive_context_sample(route_details)}")
        findings.append(
            Finding(
                "info",
                "archive-context-terminal-history-stub",
                (
                    "done roadmap item(s) declare terminal historical relationship stubs where original archive content is unrecoverable; "
                    f"{'; '.join(details)}; bounded recovery action: keep as relationship evidence unless a current lifecycle decision needs a reviewed roadmap retarget or archive restoration"
                ),
                ROADMAP_REL,
            )
        )
    if missing_routes:
        findings.append(
            Finding(
                "warn",
                "archive-context-missing-archive-targets",
                (
                    f"{len(missing_routes)} roadmap archived-plan reference(s) are missing on disk: "
                    f"{_archive_context_sample(missing_routes)}; bounded recovery action: restore the archive file or retarget archived_plan after review"
                ),
                ROADMAP_REL,
            )
        )
        findings.extend(_archive_context_missing_root_cause_findings(inventory, missing_routes, archive_ref_records_by_route, roadmap_items))
    if unreferenced_routes:
        findings.append(
            Finding(
                "info",
                "archive-context-unreferenced-archive",
                (
                    f"{len(unreferenced_routes)} present archived plan file(s) are not referenced by roadmap route metadata or prose: "
                    f"{_archive_context_sample(unreferenced_routes)}"
                ),
                ARCHIVE_CONTEXT_ARCHIVE_DIR_REL,
            )
        )

    classification_counts: dict[str, int] = {}
    closeout_capsule_counts: dict[str, int] = {}
    closeout_capsule_examples: dict[str, list[str]] = {}
    for archive_rel, archive_path in sorted(present_archives.items()):
        classification, source_refs, missing_sources = _archive_context_classification(
            inventory,
            archive_rel,
            archive_path,
            roadmap_items,
            archive_refs_by_route.get(archive_rel, set()),
        )
        capsule_status = _archive_context_closeout_evidence_capsule_status(archive_path)
        closeout_capsule_counts[capsule_status] = closeout_capsule_counts.get(capsule_status, 0) + 1
        closeout_capsule_examples.setdefault(capsule_status, []).append(archive_rel)
        report_classification = classification
        if classification == "stale-source-reference" and archive_rel not in referenced_routes:
            report_classification = "stale-unreferenced-source-reference"
        classification_counts[report_classification] = classification_counts.get(report_classification, 0) + 1
        severity = "warn" if report_classification in {"stale-source-reference", "suspect-incomplete", "unreadable"} else "info"
        detail = f"classification={report_classification}"
        if source_refs:
            detail += f"; source_refs={_archive_context_sample(source_refs)}"
        if missing_sources:
            detail += f"; missing_sources={_archive_context_sample(missing_sources)}"
        detail += f"; recovery_action={_archive_context_recovery_action(report_classification)}"
        findings.append(Finding(severity, f"archive-context-{report_classification}", detail, archive_rel))

    if classification_counts:
        summary = ", ".join(f"{key}={classification_counts[key]}" for key in sorted(classification_counts))
        findings.append(Finding("info", "archive-context-classification-summary", f"present archived plan classifications: {summary}", ARCHIVE_CONTEXT_ARCHIVE_DIR_REL))
    if closeout_capsule_counts:
        summary = ", ".join(f"{key}={closeout_capsule_counts[key]}" for key in sorted(closeout_capsule_counts))
        findings.append(
            Finding(
                "info",
                "archive-context-closeout-evidence-capsule-summary",
                (
                    f"archived plan closeout evidence capsule posture: {summary}; "
                    "new writeback --archive-active-plan materializes the MLH closeout writeback capsule, "
                    "and historical archives are not backfilled automatically"
                ),
                ARCHIVE_CONTEXT_ARCHIVE_DIR_REL,
            )
        )
        incomplete_rels = [
            rel
            for status in ("missing", "partial", "unreadable")
            for rel in closeout_capsule_examples.get(status, [])
        ]
        if incomplete_rels:
            details = ", ".join(
                f"{status}={_archive_context_sample(closeout_capsule_examples.get(status, []))}"
                for status in ("missing", "partial", "unreadable")
                if closeout_capsule_examples.get(status)
            )
            findings.append(
                Finding(
                    "info",
                    "archive-context-closeout-evidence-capsule-missing",
                    (
                        f"{len(incomplete_rels)} archived plan file(s) lack a complete closeout evidence capsule: "
                        f"{details}; diagnostic only; review schema and route ownership before any historical backfill"
                    ),
                    ARCHIVE_CONTEXT_ARCHIVE_DIR_REL,
                )
            )
    findings.append(
        Finding(
            "info",
            "archive-context-boundary",
            "archive context audit is read-only evidence; it cannot approve repair, lifecycle movement, closeout, archive, roadmap promotion, staging, commit, rollback, or next-plan opening",
        )
    )
    return findings


def _archive_context_present_archive_paths(archive_dir: Path) -> list[Path]:
    if not archive_dir.is_dir():
        return []
    return sorted(path for path in archive_dir.glob("*.md") if path.is_file() and not path.is_symlink())


def _archive_context_archive_refs_from_text(text: str) -> tuple[str, ...]:
    refs = re.findall(r"project/archive/plans/[A-Za-z0-9_.\/-]+\.md", text)
    return tuple(sorted(set(ref.replace("\\", "/") for ref in refs)))


def _archive_context_reference_lines(text: str, rel_path: str) -> tuple[int, ...]:
    lines: list[int] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if rel_path in line.replace("\\", "/"):
            lines.append(index)
    return tuple(lines)


def _archive_context_terminal_stub_item_ids_for_lines(
    roadmap_items: dict[str, object],
    lines: tuple[int, ...],
) -> tuple[str, ...]:
    if not lines:
        return ()
    item_ids: set[str] = set()
    for line in lines:
        matching = [
            item_id
            for item_id, item in roadmap_items.items()
            if getattr(item, "start", -1) + 1 <= line <= getattr(item, "end", -1)
        ]
        if not matching:
            return ()
        terminal_matches = [
            item_id
            for item_id in matching
            if _archive_context_is_terminal_history_stub_item(roadmap_items[item_id])
        ]
        if len(terminal_matches) != len(matching):
            return ()
        item_ids.update(terminal_matches)
    return tuple(sorted(item_ids))


def _archive_context_is_terminal_history_stub_item(item: object) -> bool:
    return roadmap_item_is_terminal_history_stub(item)


def _archive_context_record_route_ref(
    records_by_route: dict[str, list[ArchiveContextRouteRef]],
    rel_path: str,
    owner: str,
    field: str,
    status: str,
    source: str,
    line: int | None,
) -> None:
    if not rel_path or not _archive_context_safe_rel(rel_path):
        return
    records_by_route.setdefault(rel_path, []).append(
        ArchiveContextRouteRef(
            owner=owner,
            field=field,
            status=status,
            source=source,
            line=line,
        )
    )


def _archive_context_missing_root_cause_findings(
    inventory: Inventory,
    missing_routes: list[str],
    records_by_route: dict[str, list[ArchiveContextRouteRef]],
    roadmap_items: dict[str, object],
) -> list[Finding]:
    cause_routes: dict[str, list[str]] = {}
    for route in missing_routes:
        cause = _archive_context_missing_root_cause(records_by_route.get(route, ()))
        cause_routes.setdefault(cause, []).append(route)
    if not cause_routes:
        return []

    findings: list[Finding] = []
    summary = ", ".join(f"{cause}={len(cause_routes[cause])}" for cause in sorted(cause_routes))
    findings.append(
        Finding(
            "info",
            "archive-context-missing-root-cause-summary",
            f"missing archive target root-cause classes: {summary}; route traces point at the last known repo-visible references, not proof of deletion",
            ROADMAP_REL,
        )
    )
    for cause in sorted(cause_routes):
        routes = cause_routes[cause]
        severity = "info" if cause == "compacted-history-prose" else "warn"
        samples = _archive_context_missing_cause_sample(inventory, routes, records_by_route, roadmap_items)
        findings.append(
            Finding(
                severity,
                f"archive-context-missing-cause-{cause}",
                (
                    f"{len(routes)} missing archive target(s) classified as {cause}: {samples}; "
                    f"bounded recovery action: {_archive_context_missing_cause_recovery_action(cause)}"
                ),
                ROADMAP_REL,
            )
        )
    return findings


def _archive_context_missing_root_cause(records: tuple[ArchiveContextRouteRef, ...] | list[ArchiveContextRouteRef]) -> str:
    fields = {record.field for record in records}
    statuses = {record.status for record in records if record.status}
    if "archived_plan" in fields:
        if "done" in statuses:
            return "metadata-archived-plan"
        return "metadata-nonterminal-archived-plan"
    if "related_plan" in fields:
        return "metadata-related-plan"
    if records and all(record.field == "prose" for record in records):
        return "compacted-history-prose"
    return "unknown"


def _archive_context_missing_cause_sample(
    inventory: Inventory,
    routes: list[str],
    records_by_route: dict[str, list[ArchiveContextRouteRef]],
    roadmap_items: dict[str, object],
) -> str:
    samples = [
        _archive_context_missing_route_detail(inventory, route, records_by_route.get(route, ()), roadmap_items)
        for route in sorted(routes)[:ARCHIVE_CONTEXT_CAUSE_SAMPLE_LIMIT]
    ]
    if len(routes) > ARCHIVE_CONTEXT_CAUSE_SAMPLE_LIMIT:
        samples.append(f"... +{len(routes) - ARCHIVE_CONTEXT_CAUSE_SAMPLE_LIMIT} more")
    return "; ".join(samples) or "<none>"


def _archive_context_missing_route_detail(
    inventory: Inventory,
    route: str,
    records: tuple[ArchiveContextRouteRef, ...] | list[ArchiveContextRouteRef],
    roadmap_items: dict[str, object],
) -> str:
    trace = _archive_context_route_trace(records)
    source_refs = _archive_context_missing_route_source_refs(records, roadmap_items)
    source_state = _archive_context_source_evidence_state(inventory, source_refs)
    return f"{route} [reference_trace={trace}; source_evidence={source_state}]"


def _archive_context_route_trace(records: tuple[ArchiveContextRouteRef, ...] | list[ArchiveContextRouteRef]) -> str:
    if not records:
        return "<none>"
    trace_parts = []
    for record in records[:ARCHIVE_CONTEXT_CAUSE_SAMPLE_LIMIT]:
        location = record.source
        if record.line:
            location += f":{record.line}"
        trace_parts.append(f"{record.owner}.{record.field}@{location}")
    if len(records) > ARCHIVE_CONTEXT_CAUSE_SAMPLE_LIMIT:
        trace_parts.append(f"... +{len(records) - ARCHIVE_CONTEXT_CAUSE_SAMPLE_LIMIT} more")
    return ",".join(trace_parts)


def _archive_context_missing_route_source_refs(
    records: tuple[ArchiveContextRouteRef, ...] | list[ArchiveContextRouteRef],
    roadmap_items: dict[str, object],
) -> tuple[str, ...]:
    source_refs: set[str] = set()
    for record in records:
        item = roadmap_items.get(record.owner)
        fields = getattr(item, "fields", {}) if item else {}
        source_refs.update(_archive_context_source_refs(fields))
    return tuple(sorted(rel for rel in source_refs if _archive_context_safe_rel(rel)))


def _archive_context_source_evidence_state(inventory: Inventory, source_refs: tuple[str, ...]) -> str:
    if not source_refs:
        return "none"
    _expanded_refs, missing, archived_replacements = _archive_context_resolve_source_refs(inventory, source_refs)
    if not missing:
        if archived_replacements:
            return f"archived-reference:{_archive_context_sample(archived_replacements)}"
        return "present"
    if len(missing) == len(source_refs):
        return f"missing:{_archive_context_sample(missing)}"
    return f"partial-missing:{_archive_context_sample(missing)}"


def _archive_context_missing_cause_recovery_action(cause: str) -> str:
    if cause == "metadata-archived-plan":
        return "restore the physical archive file or retarget archived_plan/related_plan through roadmap or writeback after reviewing the traced item"
    if cause == "metadata-nonterminal-archived-plan":
        return "review why a nonterminal roadmap item points at archived evidence, then clear or retarget metadata through roadmap"
    if cause == "metadata-related-plan":
        return "retarget the archive-shaped related_plan to a present archived_plan or clear the stale terminal relationship after review"
    if cause == "compacted-history-prose":
        return "treat as historical compacted prose unless current closeout depends on the missing file; restore only after evidence review"
    return "inspect the traced reference and choose restore, retarget, or provisional closeout wording manually"


def _archive_context_closeout_evidence_capsule_status(archive_path: Path) -> str:
    try:
        archive_text = archive_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "unreadable"
    fields = _archive_context_closeout_evidence_capsule_fields(archive_text)
    if not fields:
        return "missing"
    if closeout_values_are_complete(fields):
        return "complete"
    return "partial"


def _archive_context_closeout_evidence_capsule_fields(text: str) -> dict[str, str]:
    lines = text.splitlines()
    ranges: list[tuple[int, int]] = []
    begin: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == WRITEBACK_BEGIN:
            begin = index
            continue
        if line.strip() == WRITEBACK_END and begin is not None:
            ranges.append((begin, index))
            begin = None
    if not ranges:
        return {}
    start, end = ranges[-1]
    allowed = set(CLOSEOUT_WRITEBACK_FIELDS)
    fields: dict[str, str] = {}
    for line in lines[start + 1 : end]:
        match = re.match(r"^\s*[-*]\s+`?([A-Za-z0-9_-]+)`?\s*:\s*(.*?)\s*$", line)
        if not match:
            continue
        field = match.group(1).replace("-", "_")
        value = match.group(2).strip().strip("`\"'")
        if field in allowed and value:
            fields[field] = value
    return fields


def _archive_context_classification(
    inventory: Inventory,
    archive_rel: str,
    archive_path: Path,
    roadmap_items: dict[str, object],
    referencing_item_ids: set[str],
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    try:
        archive_text = archive_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "unreadable", (), ()

    frontmatter = parse_frontmatter(archive_text)
    source_refs = set(_archive_context_source_refs(frontmatter.data))
    for item_id in referencing_item_ids:
        item = roadmap_items.get(item_id)
        fields = getattr(item, "fields", {}) if item else {}
        source_refs.update(_archive_context_source_refs(fields))
    source_refs = {rel for rel in source_refs if _archive_context_safe_rel(rel)}
    expanded_source_refs, missing_sources, archived_replacements = _archive_context_resolve_source_refs(inventory, tuple(sorted(source_refs)))
    existing_source_texts = []
    for rel in sorted(expanded_source_refs):
        path = inventory.root / rel
        boundary_violation = source_path_boundary_violation(inventory.root, path, label="archive context source ref")
        if boundary_violation is not None or not path.is_file() or path.is_symlink():
            continue
        try:
            existing_source_texts.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
    scan_text = "\n".join([archive_text, *existing_source_texts]).casefold()
    diagnostic_about_suspect = _archive_context_has_marker(scan_text, ARCHIVE_CONTEXT_DIAGNOSTIC_MARKERS)
    if diagnostic_about_suspect and _archive_context_has_marker(scan_text, ARCHIVE_CONTEXT_SUSPECT_MARKERS):
        return "diagnostic-about-suspect", tuple(sorted(source_refs)), missing_sources
    if _archive_context_has_marker(scan_text, ARCHIVE_CONTEXT_SUSPECT_MARKERS):
        return "suspect-incomplete", expanded_source_refs, missing_sources
    if missing_sources:
        return "stale-source-reference", expanded_source_refs, missing_sources
    if _archive_context_has_marker(scan_text, ARCHIVE_CONTEXT_RECONSTRUCTED_MARKERS):
        return "reconstructed", expanded_source_refs, missing_sources
    if archived_replacements:
        return "archived-source-reference", expanded_source_refs, ()
    if expanded_source_refs:
        return "complete", expanded_source_refs, missing_sources
    return "direct-task-no-source-contract", (), ()


def _archive_context_source_refs(data: dict[str, object]) -> tuple[str, ...]:
    values: list[str] = []
    for field in ARCHIVE_CONTEXT_SOURCE_FIELDS:
        values.extend(_archive_context_path_values(data.get(field)))
    return tuple(_archive_context_normalize_rel(value) for value in values if _archive_context_normalize_rel(value))


def _archive_context_path_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        normalized = _archive_context_normalize_rel(value)
        return (normalized,) if normalized.startswith("project/") else ()
    if isinstance(value, list):
        values = []
        for item in value:
            normalized = _archive_context_normalize_rel(item)
            if normalized.startswith("project/"):
                values.append(normalized)
        return tuple(values)
    return ()


def _archive_context_resolve_source_refs(
    inventory: Inventory,
    source_refs: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    expanded_refs = set(source_refs)
    missing: list[str] = []
    archived_replacements: list[str] = []
    for rel in sorted(source_refs):
        path = inventory.root / rel
        boundary_violation = source_path_boundary_violation(inventory.root, path, label="archive context source ref")
        if boundary_violation is None and path.is_file() and not path.is_symlink():
            continue
        replacements = _archive_context_archived_source_replacements(inventory, rel)
        if replacements:
            expanded_refs.update(replacements)
            archived_replacements.extend(replacements)
        else:
            missing.append(rel)
    return tuple(sorted(expanded_refs)), tuple(sorted(missing)), tuple(sorted(set(archived_replacements)))


def _archive_context_archived_source_replacements(inventory: Inventory, rel_path: str) -> tuple[str, ...]:
    for live_prefix, archive_prefix in ARCHIVE_CONTEXT_ARCHIVED_SOURCE_PREFIXES:
        if not rel_path.startswith(live_prefix):
            continue
        source_name = Path(rel_path).name
        archive_dir = inventory.root / archive_prefix
        boundary_violation = source_path_boundary_violation(inventory.root, archive_dir, label="archive context archived-source directory")
        if boundary_violation is not None or not archive_dir.is_dir():
            return ()
        matches = []
        for candidate in sorted(path for path in archive_dir.glob("*.md") if path.is_file() and not path.is_symlink()):
            if candidate.name == source_name or candidate.name.endswith(f"-{source_name}"):
                matches.append(candidate.relative_to(inventory.root).as_posix())
        return tuple(matches)
    return ()


def _archive_context_normalize_rel(value: object) -> str:
    if value in (None, ""):
        return ""
    normalized = str(value).strip().strip("`\"'").replace("\\", "/")
    return normalized.strip()


def _archive_context_safe_rel(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith(("/", "\\")):
        return False
    path = Path(rel_path)
    return not path.is_absolute() and ".." not in path.parts


def _archive_context_has_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _archive_context_sample(values: list[str] | tuple[str, ...] | set[str]) -> str:
    ordered = sorted(values)
    sample = ", ".join(ordered[:ARCHIVE_CONTEXT_SAMPLE_LIMIT])
    if len(ordered) > ARCHIVE_CONTEXT_SAMPLE_LIMIT:
        sample += f", ... +{len(ordered) - ARCHIVE_CONTEXT_SAMPLE_LIMIT} more"
    return sample or "<none>"


def _archive_context_recovery_action(classification: str) -> str:
    if classification == "suspect-incomplete":
        return "re-review implementation against recovered source context before relying on the archive"
    if classification == "stale-source-reference":
        return "restore or retarget the missing source route before treating the archive context as complete"
    if classification == "stale-unreferenced-source-reference":
        return "preserve as historical context; restore or retarget only if current roadmap or lifecycle authority depends on this archive"
    if classification == "archived-source-reference":
        return "use the archived source reference as context; retarget stale live-source metadata only through reviewed route rails"
    if classification == "reconstructed":
        return "treat as reviewable reconstructed context and re-review only when behavior seems narrower than source intent"
    if classification == "diagnostic-about-suspect":
        return "use as diagnostic evidence for prior archive-context gaps, not as a suspect implementation by itself"
    if classification == "unreadable":
        return "repair file readability before context audit can classify it"
    return "no automatic action"


def route_reference_inventory_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "info",
                "route-reference-skipped-root-kind",
                "route-reference inventory runs only for live operating roots and remains read-only",
            )
        ]

    records = _route_reference_records(inventory)
    known_sources = {surface.rel_path for surface in inventory.present_surfaces}
    extra_boundary_findings = _route_reference_extra_route_boundary_findings(inventory, known_sources)
    counts = {
        "present": 0,
        "present_product_source": 0,
        "external_non_file": 0,
        "optional_pattern": 0,
        "missing": 0,
        "unsafe": 0,
    }
    missing_records: dict[str, list[RouteReferenceRecord]] = {}
    unsafe_records: dict[str, list[RouteReferenceRecord]] = {}
    for record in records:
        target_state, normalized_target = _route_reference_target_state(inventory, record)
        if target_state == "skip":
            continue
        if target_state in counts:
            counts[target_state] += 1
        if target_state == "missing":
            missing_records.setdefault(normalized_target, []).append(record)
        elif target_state == "unsafe":
            unsafe_records.setdefault(normalized_target, []).append(record)

    findings = [
        Finding(
            "info",
            "route-reference-inventory-summary",
            (
                f"route-reference inventory: {len(records)} reference(s) scanned, "
                f"present={counts['present']}, present_product_source={counts['present_product_source']}, "
                f"missing={counts['missing']}, unsafe={counts['unsafe']}, "
                f"external_non_file={counts['external_non_file']}, optional_pattern={counts['optional_pattern']}; diagnostic only"
            ),
        )
    ]
    findings.extend(extra_boundary_findings)
    for target, target_records in sorted(unsafe_records.items()):
        unsafe_class = _route_reference_unsafe_class(target_records)
        if unsafe_class == "unsafe-historical-context":
            severity = "info"
            message = (
                f"{target} is an unsafe path-like reference in historical/generated context; "
                f"references={_route_reference_record_sample(target_records)}; "
                "bounded recovery action: leave it as historical evidence unless current authority depends on it; "
                "current docs or metadata should use reviewed root-relative routes"
            )
        else:
            severity = "warn"
            message = (
                f"{target} is not a safe root-relative route reference; "
                f"references={_route_reference_record_sample(target_records)}; "
                "bounded recovery action: replace with a reviewed root-relative route or leave it external by design"
            )
        findings.append(
            Finding(
                severity,
                f"route-reference-{unsafe_class}",
                message,
                target_records[0].source,
                target_records[0].line,
            )
        )

    if missing_records:
        class_counts: dict[str, int] = {}
        classified_targets: list[tuple[str, str, list[RouteReferenceRecord]]] = []
        for target, target_records in sorted(missing_records.items()):
            classification = _route_reference_missing_class(inventory, target, target_records)
            class_counts[classification] = class_counts.get(classification, 0) + 1
            classified_targets.append((classification, target, target_records))
        summary = ", ".join(f"{key}={class_counts[key]}" for key in sorted(class_counts))
        severity = "warn" if any(key in ROUTE_REFERENCE_WARN_CLASSES for key in class_counts) else "info"
        findings.append(
            Finding(
                severity,
                "route-reference-missing-summary",
                f"missing route-reference classes: {summary}; route traces identify references, not proof of deletion",
            )
        )
        for classification, target, target_records in classified_targets:
            severity = "warn" if classification in ROUTE_REFERENCE_WARN_CLASSES else "info"
            findings.append(
                Finding(
                    severity,
                    f"route-reference-missing-{classification}",
                    (
                        f"{target} is missing; class={classification}{_route_reference_classification_detail(inventory, classification, target)}; "
                        f"references={_route_reference_record_sample(target_records)}; "
                        f"bounded recovery action: {_route_reference_recovery_action(classification, target_records)}; "
                        f"next safe command: `{_route_reference_next_safe_command(classification, target_records)}`; "
                        f"boundary: {_route_reference_recovery_boundary(classification, target_records)}"
                    ),
                    target_records[0].source,
                    target_records[0].line,
                )
            )
    else:
        findings.append(Finding("info", "route-reference-missing-summary", "no missing route references were found"))

    findings.extend(_route_metadata_findings(inventory))
    findings.append(
        Finding(
            "info",
            "route-reference-boundary",
            (
                "route-reference inventory is read-only evidence; it cannot approve repair, archive recreation, "
                "deletion, lifecycle movement, plan opening, staging, commit, rollback, or repair apply"
            ),
        )
    )
    return findings


def _route_reference_classification_detail(inventory: Inventory, classification: str, target: str) -> str:
    if classification == "archived-source-reference":
        replacements = _archive_context_archived_source_replacements(inventory, target)
        if replacements:
            return f"; archived_replacements={_archive_context_sample(replacements)}"
    return ""


def _route_reference_records(inventory: Inventory) -> list[RouteReferenceRecord]:
    records: list[RouteReferenceRecord] = []
    for surface in inventory.present_surfaces:
        if surface.role == "package-mirror":
            continue
        records.extend(_route_reference_surface_records(surface.rel_path, surface.content, surface.memory_route, surface.links))

    roadmap_items, _ = roadmap_items_for_diagnostics(inventory)
    for item_id, item in sorted(roadmap_items.items(), key=lambda row: (row[1].start, row[0])):
        fields = getattr(item, "fields", {})
        status = str(fields.get("status") or "").strip().casefold()
        for field in sorted(ROUTE_REFERENCE_METADATA_FIELDS):
            for target in _route_reference_path_values(fields.get(field)):
                records.append(
                    RouteReferenceRecord(
                        target=target,
                        source=ROADMAP_REL,
                        line=getattr(item, "start", 0) + 1,
                        owner=item_id,
                        field=field,
                        owner_status=status,
                        context="roadmap-item",
                    )
                )

    known_sources = {surface.rel_path for surface in inventory.present_surfaces}
    for rel_path, text, route_id in _route_reference_extra_route_texts(inventory, known_sources):
        records.extend(_route_reference_surface_records(rel_path, text, route_id, extract_path_refs(text)))

    return _route_reference_deduped(records)


def _route_reference_surface_records(
    rel_path: str,
    text: str,
    route_id: str,
    links: list[LinkRef],
) -> list[RouteReferenceRecord]:
    frontmatter = parse_frontmatter(text) if rel_path.endswith(".md") else None
    status = ""
    records: list[RouteReferenceRecord] = []
    if frontmatter and frontmatter.has_frontmatter:
        status = str(frontmatter.data.get("status") or "").strip().casefold()
        for field in sorted(ROUTE_REFERENCE_METADATA_FIELDS):
            for target in _route_reference_path_values(frontmatter.data.get(field)):
                records.append(
                    RouteReferenceRecord(
                        target=target,
                        source=rel_path,
                        line=_frontmatter_key_line_from_text(text, field),
                        owner=rel_path,
                        field=field,
                        owner_status=status,
                        context=route_id,
                    )
                )

    for target, line, source_kind in _route_reference_text_refs(text, links):
        context = route_id
        field = source_kind
        record_status = "" if rel_path == ROADMAP_REL else status
        if rel_path == ROADMAP_REL and _route_reference_line_is_compacted_history(text, line):
            context = "compacted-history"
            field = "compacted-history-prose"
        elif rel_path.startswith(".mylittleharness/generated/"):
            context = "generated-cache"
        records.append(
            RouteReferenceRecord(
                target=target,
                source=rel_path,
                line=line,
                owner=rel_path,
                field=field,
                owner_status=record_status,
                context=context,
            )
        )
    return records


def _route_reference_extra_route_texts(inventory: Inventory, known_sources: set[str]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for pattern in ROUTE_REFERENCE_SCAN_EXTRA_GLOBS:
        for path in sorted(inventory.root.glob(pattern)):
            rel_path = path.relative_to(inventory.root).as_posix()
            if rel_path in known_sources:
                continue
            if _route_reference_extra_route_skip_finding(inventory, path, rel_path) is not None:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            rows.append((rel_path, text, classify_memory_route(rel_path).route_id))
    return rows


def _route_reference_extra_route_boundary_findings(inventory: Inventory, known_sources: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for pattern in ROUTE_REFERENCE_SCAN_EXTRA_GLOBS:
        for path in sorted(inventory.root.glob(pattern)):
            rel_path = path.relative_to(inventory.root).as_posix()
            if rel_path in known_sources:
                continue
            finding = _route_reference_extra_route_skip_finding(inventory, path, rel_path)
            if finding is not None:
                findings.append(finding)
    return findings


def _route_reference_extra_route_skip_finding(inventory: Inventory, path: Path, rel_path: str) -> Finding | None:
    boundary_violation = source_path_boundary_violation(inventory.root, path, label="route-reference extra source")
    if boundary_violation is not None:
        return Finding(
            "warn",
            "route-reference-extra-source-boundary",
            f"skipped route-reference extra source outside the target-root boundary: {boundary_violation.message}",
            rel_path,
        )
    if path.is_symlink() or not path.is_file():
        return Finding(
            "warn",
            "route-reference-extra-source-boundary",
            "skipped route-reference extra source because it is not a regular in-root file",
            rel_path,
        )
    return None


def _route_reference_text_refs(text: str, links: list[LinkRef]) -> list[tuple[str, int, str]]:
    refs: list[tuple[str, int, str]] = []
    for link in links:
        refs.append((link.target, link.line, link.source))
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in ROUTE_REFERENCE_TEXT_REF_RE.finditer(line):
            refs.append((match.group(1), line_number, "text-path"))

    deduped: list[tuple[str, int, str]] = []
    seen: set[tuple[str, int, str]] = set()
    for target, line, source_kind in refs:
        normalized = _route_reference_normalize_target(target)
        if not normalized or not _route_reference_value_is_path_like(normalized):
            continue
        if _route_reference_text_ref_is_prose_label(normalized, source_kind):
            continue
        key = (normalized, line, source_kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((normalized, line, source_kind))
    return deduped


def _route_reference_path_values(value: object) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(value, str):
        values.append(value)
    elif isinstance(value, list):
        values.extend(str(item) for item in value if item not in (None, ""))
    else:
        return ()
    return tuple(
        normalized
        for item in values
        if (normalized := _route_reference_normalize_target(item)) and _route_reference_value_is_path_like(normalized)
    )


def _route_reference_is_text_only_label(value: str) -> bool:
    normalized = value.casefold()
    return any(normalized == label or normalized.startswith(f"{label}/") for label in ROUTE_REFERENCE_TEXT_ONLY_LABELS)


def _route_reference_text_ref_is_prose_label(value: str, source_kind: str) -> bool:
    if source_kind == "markdown-link":
        return False
    if _route_reference_is_text_only_label(value):
        return True
    return bool(re.search(r"\s", value)) and not _is_absolute_path(value)


def _route_reference_value_is_path_like(value: str) -> bool:
    return (
        _route_metadata_value_is_path_like(value)
        or value in ROOT_RELATIVE_LINK_NAMES
        or any(value.startswith(prefix) for prefix in ROOT_RELATIVE_LINK_PREFIXES)
    )


def _route_reference_normalize_target(value: object) -> str:
    if value in (None, ""):
        return ""
    normalized = str(value).strip().strip("`\"'").strip("<>").replace("\\", "/")
    if normalized.startswith("[") and normalized.endswith("]"):
        return ""
    normalized = normalized.split("#", 1)[0]
    return re.sub(r"/+", "/", normalized).strip().rstrip(".,;:)]")


def _route_reference_deduped(records: list[RouteReferenceRecord]) -> list[RouteReferenceRecord]:
    deduped: list[RouteReferenceRecord] = []
    seen: set[tuple[str, str, int | None, str, str, str]] = set()
    for record in records:
        normalized = _route_reference_normalize_target(record.target)
        key = (normalized, record.source, record.line, record.owner, record.field, record.context)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            RouteReferenceRecord(
                target=normalized,
                source=record.source,
                line=record.line,
                owner=record.owner,
                field=record.field,
                owner_status=record.owner_status,
                context=record.context,
            )
        )
    return deduped


def _route_reference_target_state(inventory: Inventory, record: RouteReferenceRecord) -> tuple[str, str]:
    target = _route_reference_normalize_target(record.target)
    if not target:
        return "skip", ""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target) or target.startswith("mailto:"):
        return "external_non_file", target
    rel_path = _route_reference_root_relative_target(inventory, target)
    if rel_path is None:
        return ("unsafe", target) if _is_absolute_path(target) else ("external_non_file", target)
    if not rel_path:
        return "skip", target
    if _route_metadata_path_is_unsafe(rel_path) or root_relative_path_conflict(rel_path):
        return "unsafe", rel_path
    if _route_reference_has_glob(rel_path):
        return ("present", rel_path) if _route_reference_pattern_exists(inventory, rel_path) else ("optional_pattern", rel_path)
    target_path = inventory.root / rel_path
    if target_path.exists():
        boundary_violation = source_path_boundary_violation(inventory.root, target_path, label="route-reference target")
        if boundary_violation is not None or target_path.is_symlink() or not target_path.is_file():
            return "unsafe", rel_path
        return "present", rel_path
    product_root = _route_reference_product_source_root(inventory)
    if product_root and _route_reference_is_product_target(record, rel_path) and (product_root / rel_path).exists():
        return "present_product_source", rel_path
    return "missing", rel_path


def _route_reference_root_relative_target(inventory: Inventory, target: str) -> str | None:
    if _is_absolute_path(target):
        try:
            rel_path = Path(_display_path_value(target)).expanduser().resolve().relative_to(inventory.root.resolve()).as_posix()
            return "" if rel_path == "." else rel_path
        except (OSError, RuntimeError, ValueError):
            return None
    return target[2:] if target.startswith("./") else target


def _route_reference_product_source_root(inventory: Inventory) -> Path | None:
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    value = data.get("product_source_root")
    if not value:
        return None
    try:
        path = Path(_display_path_value(str(value))).expanduser()
        if not path.is_absolute():
            path = inventory.root / path
        return path.resolve()
    except (OSError, RuntimeError):
        return None


def _route_reference_is_product_target(record: RouteReferenceRecord, rel_path: str) -> bool:
    if record.field == "target_artifacts":
        return True
    return rel_path == "pyproject.toml" or rel_path.startswith(("src/", "tests/"))


def _route_reference_has_glob(rel_path: str) -> bool:
    return "*" in rel_path or "{" in rel_path


def _route_reference_pattern_exists(inventory: Inventory, rel_path: str) -> bool:
    patterns = _expand_brace_pattern(rel_path)
    for pattern in patterns:
        if any(inventory.root.glob(pattern)):
            return True
        product_root = _route_reference_product_source_root(inventory)
        if product_root and any(product_root.glob(pattern)):
            return True
    return False


def _route_reference_missing_class(inventory: Inventory, target: str, records: list[RouteReferenceRecord]) -> str:
    if target.startswith(".mylittleharness/generated/") or all(record.source.startswith(".mylittleharness/generated/") for record in records):
        return "generated-disposable-cache"
    if target == DEFAULT_PLAN_REL and not _route_reference_default_plan_is_required(inventory, records):
        return "inactive-active-plan"
    if target in ROUTE_REFERENCE_OPTIONAL_EVIDENCE_ROUTES and not _route_reference_has_live_work_reference(records):
        return "optional-evidence-route"
    if _archive_context_archived_source_replacements(inventory, target) and not _route_reference_has_live_work_reference(records):
        return "archived-source-reference"
    if any(record.context == "compacted-history" or record.field == "compacted-history-prose" for record in records):
        return "compacted-history"
    if any(_route_reference_is_required_lifecycle_reference(inventory, record) for record in records):
        return "required-lifecycle-evidence"
    if _route_reference_has_live_work_reference(records):
        return "accepted-work-evidence"
    if any(record.source.startswith("project/archive/") or record.owner_status in ROUTE_REFERENCE_TERMINAL_STATUSES for record in records):
        return "optional-historical-context"
    if any(record.field in ROUTE_REFERENCE_METADATA_FIELDS for record in records):
        return "stale-metadata"
    return "optional-historical-context"


def _route_reference_default_plan_is_required(inventory: Inventory, records: list[RouteReferenceRecord]) -> bool:
    return any(_route_reference_is_required_lifecycle_reference(inventory, record) for record in records)


def _route_reference_unsafe_class(records: list[RouteReferenceRecord]) -> str:
    if records and all(_route_reference_is_historical_or_generated_context(record) for record in records):
        return "unsafe-historical-context"
    return "unsafe-target"


def _route_reference_is_historical_or_generated_context(record: RouteReferenceRecord) -> bool:
    return record.source.startswith((".mylittleharness/generated/", "project/archive/", "project/verification/"))


def _route_reference_has_live_work_reference(records: list[RouteReferenceRecord]) -> bool:
    return any(
        record.owner_status in ROUTE_REFERENCE_ACCEPTED_STATUSES
        and not _route_reference_is_historical_or_generated_context(record)
        for record in records
    )


def _route_reference_is_required_lifecycle_reference(inventory: Inventory, record: RouteReferenceRecord) -> bool:
    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    if record.source == "project/project-state.md" and record.field == "active_plan":
        return str(state_data.get("plan_status") or "").strip().casefold() == "active"
    if record.source == "project/project-state.md" and record.field == "last_archived_plan":
        return True
    if record.field == "archived_plan" and record.owner_status in {"done", "complete"}:
        return True
    return False


def _route_reference_record_sample(records: list[RouteReferenceRecord]) -> str:
    parts = []
    for record in records[:ROUTE_REFERENCE_SAMPLE_LIMIT]:
        location = record.source
        if record.line:
            location += f":{record.line}"
        owner = record.owner if record.owner != record.source else "surface"
        field = record.field or "path"
        status = f",status={record.owner_status}" if record.owner_status else ""
        parts.append(f"{owner}.{field}@{location}{status}")
    if len(records) > ROUTE_REFERENCE_SAMPLE_LIMIT:
        parts.append(f"... +{len(records) - ROUTE_REFERENCE_SAMPLE_LIMIT} more")
    return ",".join(parts) or "<none>"


def _route_reference_recovery_guidance(
    classification: str,
    records: list[RouteReferenceRecord],
) -> RouteReferenceRecoveryGuidance:
    if classification == "required-lifecycle-evidence":
        if any(record.field == "active_plan" for record in records):
            return RouteReferenceRecoveryGuidance(
                action="restore the active plan route or retarget lifecycle state through writeback after review",
                next_safe_command='mylittleharness --root <root> suggest --intent "phase closeout handoff"',
                boundary="escalate when lifecycle authority is unclear; do not clear active_plan, archive, or repair automatically",
            )
        return RouteReferenceRecoveryGuidance(
            action="restore the required archive/evidence route or retarget lifecycle metadata through writeback/roadmap after review",
            next_safe_command="mylittleharness --root <root> check --focus archive-context",
            boundary="keep docs_decision provisional when required archive evidence is incomplete; no automatic archive recreation",
        )
    if classification == "accepted-work-evidence":
        if any(record.field == "source_incubation" for record in records):
            next_safe_command = 'mylittleharness --root <root> suggest --intent "roadmap source incubation missing"'
        else:
            next_safe_command = "mylittleharness --root <root> roadmap --dry-run --action update --item-id <id> [reviewed fields]"
        return RouteReferenceRecoveryGuidance(
            action="restore source/evidence or keep accepted work and docs_decision provisional before plan opening or closeout",
            next_safe_command=next_safe_command,
            boundary="no automatic target creation, roadmap mutation, plan opening, closeout, or archive movement",
        )
    if classification == "stale-metadata":
        if any(record.source == ROADMAP_REL or record.context == "roadmap-item" for record in records):
            next_safe_command = "mylittleharness --root <root> roadmap --dry-run --action update --item-id <id> [reviewed fields]"
        elif any(record.source == "project/project-state.md" for record in records):
            next_safe_command = "mylittleharness --root <root> writeback --dry-run [reviewed lifecycle fields]"
        else:
            next_safe_command = "mylittleharness --root <root> memory-hygiene --dry-run --scan"
        return RouteReferenceRecoveryGuidance(
            action="retarget or clear stale route metadata through the owning route command after review",
            next_safe_command=next_safe_command,
            boundary="metadata cleanup only after dry-run review; no semantic promotion or lifecycle approval",
        )
    if classification == "compacted-history":
        return RouteReferenceRecoveryGuidance(
            action="treat as compacted historical prose unless current closeout depends on the missing target",
            next_safe_command="mylittleharness --root <root> check --focus archive-context",
            boundary="historical prose cannot prove deletion or approve archive reconstruction",
        )
    if classification == "inactive-active-plan":
        return RouteReferenceRecoveryGuidance(
            action="treat the default active-plan route as lazy until project-state opens or names an active plan",
            next_safe_command="mylittleharness --root <root> check --focus agents",
            boundary="inactive plan-file mentions do not create an active-plan requirement or approve plan opening",
        )
    if classification == "archived-source-reference":
        return RouteReferenceRecoveryGuidance(
            action="use the matching archived source reference as context and retarget stale live-source metadata only after review",
            next_safe_command="mylittleharness --root <root> check --focus archive-context",
            boundary="archived source context is evidence only; no automatic source restoration, archive movement, or lifecycle approval",
        )
    if classification == "optional-evidence-route":
        return RouteReferenceRecoveryGuidance(
            action="treat the optional evidence directory as absent until an owning evidence rail writes records",
            next_safe_command="mylittleharness --root <root> check --focus agents",
            boundary="optional evidence routes do not require empty directory creation or approve worker fanout",
        )
    if classification == "generated-disposable-cache":
        return RouteReferenceRecoveryGuidance(
            action="ignore for lifecycle authority, or inspect/rebuild the disposable projection cache only through generated-cache rails",
            next_safe_command="mylittleharness --root <root> projection --inspect --target all",
            boundary="generated cache refs are disposable navigation output, not source truth or recovery authority",
        )
    return RouteReferenceRecoveryGuidance(
        action="inspect only when this historical or optional context is needed for a current decision",
        next_safe_command="mylittleharness --root <root> check --focus archive-context",
        boundary="optional historical context stays advisory; no repair, archive, or lifecycle movement is implied",
    )


def _route_reference_recovery_action(classification: str, records: list[RouteReferenceRecord]) -> str:
    return _route_reference_recovery_guidance(classification, records).action


def _route_reference_next_safe_command(classification: str, records: list[RouteReferenceRecord]) -> str:
    return _route_reference_recovery_guidance(classification, records).next_safe_command


def _route_reference_recovery_boundary(classification: str, records: list[RouteReferenceRecord]) -> str:
    return _route_reference_recovery_guidance(classification, records).boundary


def _frontmatter_key_line_from_text(text: str, key: str) -> int | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return None
        if line.split(":", 1)[0].strip() == key:
            return index
    return None


def _route_reference_line_is_compacted_history(text: str, line_number: int) -> bool:
    current_heading = ""
    for line in text.splitlines()[:line_number]:
        if line.startswith("## "):
            current_heading = line.strip("# ").strip().casefold()
    return current_heading == "archived completed history"


def _route_metadata_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []

    findings: list[Finding] = []
    for surface in inventory.present_surfaces:
        if surface.memory_route not in ROUTE_METADATA_VALIDATED_ROUTES or surface.path.suffix.lower() != ".md":
            continue
        if surface.frontmatter.errors:
            for error in surface.frontmatter.errors:
                findings.append(
                    Finding(
                        "warn",
                        "route-metadata-frontmatter",
                        f"route metadata frontmatter is malformed: {error}",
                        surface.rel_path,
                    )
                )
            continue
        if not surface.frontmatter.has_frontmatter:
            continue

        findings.extend(_route_metadata_status_findings(surface))
        for key, value in surface.frontmatter.data.items():
            if not _is_route_metadata_path_field(key):
                continue
            values, field_findings = _route_metadata_path_values(surface, key, value)
            findings.extend(field_findings)
            for rel_path in values:
                findings.extend(_route_metadata_path_findings(inventory, surface, key, rel_path))

    if findings:
        findings.append(
            Finding(
                "info",
                "route-metadata-authority",
                "route metadata diagnostics are advisory only and cannot approve mutation, repair, archive, closeout, commit, rollback, or lifecycle decisions",
            )
        )
    return findings


def _changed_route_metadata_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    if not _root_has_local_git_metadata(inventory.root):
        return []

    posture = probe_vcs(inventory.root)
    if not posture.git_available or not posture.is_worktree or posture.state != "dirty":
        return []

    changed_route_paths = _changed_route_metadata_paths(posture.changed_paths or posture.changed_samples)
    if not changed_route_paths:
        return []

    findings: list[Finding] = []
    for rel_path in changed_route_paths:
        surface = inventory.surface_by_rel.get(rel_path)
        route_id = surface.memory_route if surface else classify_memory_route(rel_path).route_id
        profile = CHANGED_ROUTE_METADATA_PROFILES.get(route_id)
        if profile is None:
            continue
        if not surface or not surface.exists or surface.path.suffix.lower() != ".md":
            continue

        line = 1
        if surface.frontmatter.errors:
            for error in surface.frontmatter.errors:
                findings.append(
                    Finding(
                        "warn",
                        "route-metadata-changed-frontmatter",
                        (
                            f"{surface.rel_path} changed {route_id} route has malformed frontmatter: {error}; "
                            "route recovery metadata remains advisory only"
                        ),
                        surface.rel_path,
                        line,
                        route_id=route_id,
                    )
                )
            findings.append(_changed_route_metadata_boundary_finding(surface, route_id))
            continue

        if not surface.frontmatter.has_frontmatter:
            findings.append(
                Finding(
                    "warn",
                    "route-metadata-changed-frontmatter",
                    (
                        f"{surface.rel_path} changed {route_id} route is missing route frontmatter; "
                        "future agents may lose status, provenance, and recovery hints; advisory only"
                    ),
                    surface.rel_path,
                    line,
                    route_id=route_id,
                )
            )
            findings.append(_changed_route_metadata_boundary_finding(surface, route_id))
            continue

        data = surface.frontmatter.data
        status_field = _changed_route_status_field(data, profile.route_status_fields)
        if not status_field:
            field_hint = " or ".join(profile.route_status_fields)
            findings.append(
                Finding(
                    "warn",
                    "route-metadata-changed-route-status",
                    (
                        f"{surface.rel_path} changed {route_id} route is missing route status metadata "
                        f"({field_hint}); advisory only, no lifecycle approval"
                    ),
                    surface.rel_path,
                    None,
                    route_id=route_id,
                    allowed_decisions=profile.route_status_fields,
                )
            )

        for field in profile.recovery_fields:
            if _frontmatter_value_present(data.get(field)):
                continue
            findings.append(
                Finding(
                    "warn",
                    f"route-metadata-changed-{field.replace('_', '-')}",
                    (
                        f"{surface.rel_path} changed {route_id} route is missing recovery metadata field "
                        f"{field}; later agents may need manual graph reconstruction; advisory only"
                    ),
                    surface.rel_path,
                    None,
                    route_id=route_id,
                )
            )
        findings.append(_changed_route_metadata_boundary_finding(surface, route_id))

    if findings:
        findings.append(
            Finding(
                "info",
                "route-metadata-changed-authority",
                (
                    "changed route metadata diagnostics improve recovery/reviewability only; they cannot approve "
                    "closeout, archive, roadmap movement, staging, commit, rollback, repair, or lifecycle decisions"
                ),
            )
        )
    return findings


def _root_has_local_git_metadata(root: Path) -> bool:
    return (root / ".git").exists()


def _changed_route_metadata_paths(entries: tuple[object, ...]) -> tuple[str, ...]:
    paths: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        status = str(getattr(entry, "status", "") or "").upper()
        if status == "D":
            continue
        for raw_path in _changed_route_path_candidates(str(getattr(entry, "path", "") or "")):
            rel_path = _normalize_route_metadata_path(raw_path).strip("/")
            if not rel_path.endswith(".md"):
                continue
            if CHANGED_ROUTE_METADATA_PROFILES.get(classify_memory_route(rel_path).route_id) is None:
                continue
            if rel_path not in seen:
                paths.append(rel_path)
                seen.add(rel_path)
    return tuple(paths)


def _changed_route_path_candidates(path: str) -> tuple[str, ...]:
    if " -> " not in path:
        return (path,)
    old, new = path.split(" -> ", 1)
    return (old.strip(), new.strip())


def _changed_route_status_field(data: dict[str, object], fields: tuple[str, ...]) -> str:
    for field in fields:
        if _frontmatter_value_present(data.get(field)):
            return field
    return ""


def _changed_route_metadata_boundary_finding(surface: Surface, route_id: str) -> Finding:
    route = ROUTE_BY_ID.get(route_id)
    authority = route.authority if route else "unknown"
    return Finding(
        "info",
        "route-metadata-changed-boundary",
        (
            f"{surface.rel_path} changed route class={route_id}; lifecycle_boundary={authority}; "
            "route metadata is a recovery hint, not approval"
        ),
        surface.rel_path,
        route_id=route_id,
        advisory=True,
    )


def _route_metadata_status_findings(surface: Surface) -> list[Finding]:
    if "status" not in surface.frontmatter.data:
        return []
    value = surface.frontmatter.data.get("status")
    allowed_values = _route_metadata_allowed_status_values(surface)
    if not isinstance(value, str) or not value.strip():
        return [
            Finding(
                "warn",
                "route-metadata-field",
                f"{surface.rel_path} status must be a non-empty scalar string",
                surface.rel_path,
                _frontmatter_key_line(surface, "status"),
            )
        ]
    normalized = value.strip().casefold()
    if normalized not in ROUTE_METADATA_STATUS_VALUES or normalized not in allowed_values:
        allowed_hint = ", ".join(allowed_values)
        return [
            Finding(
                "warn",
                "route-metadata-status",
                (
                    f"{surface.rel_path} status is {value!r}; expected a route-specific status for route "
                    f"{surface.memory_route!r}; route-specific allowed statuses: {allowed_hint}; "
                    "next_safe_command=mylittleharness --root <root> suggest --intent \"metadata status\"; "
                    "advisory only, no lifecycle approval"
                ),
                surface.rel_path,
                _frontmatter_key_line(surface, "status"),
                route_id=surface.memory_route,
                allowed_decisions=allowed_values,
            )
        ]
    lifecycle_state = _route_metadata_lifecycle_state(normalized)
    if not lifecycle_state:
        return []
    posture, next_safe_command = ROUTE_METADATA_LIFECYCLE_STATES[lifecycle_state]
    return [
        Finding(
            "info",
            "route-metadata-lifecycle-state",
            (
                f"{surface.rel_path} status={value!r}; lifecycle_state={lifecycle_state!r}; "
                f"posture={posture}; next_safe_command={next_safe_command}; "
                "operator_hint=mylittleharness --root <root> suggest --intent \"metadata status\"; "
                "human_gate=explicit amendment required for status changes; no inferred approval"
            ),
            surface.rel_path,
            _frontmatter_key_line(surface, "status"),
            route_id=surface.memory_route,
            requires_human_gate=True,
            gate_class="lifecycle",
            human_gate_reason="route status changes require an explicit reviewed command or human-authored metadata update",
            allowed_decisions=tuple(ROUTE_METADATA_LIFECYCLE_STATES),
        )
    ]


def _route_metadata_allowed_status_values(surface: Surface) -> tuple[str, ...]:
    return ROUTE_METADATA_STATUS_HINTS_BY_ROUTE.get(surface.memory_route, tuple(sorted(ROUTE_METADATA_STATUS_VALUES)))


def _route_metadata_lifecycle_state(status: str) -> str:
    canonical = status.replace("-", "_").casefold()
    if canonical in ROUTE_METADATA_LIFECYCLE_STATES:
        return canonical
    return ""


def _is_route_metadata_path_field(key: str) -> bool:
    return key in ROUTE_METADATA_SCALAR_PATH_FIELDS or key in ROUTE_METADATA_FLEXIBLE_PATH_FIELDS


def _route_metadata_path_values(surface: Surface, key: str, value: object) -> tuple[list[str], list[Finding]]:
    line = _frontmatter_key_line(surface, key)
    if key in ROUTE_METADATA_SCALAR_PATH_FIELDS:
        if not isinstance(value, str) or not value.strip():
            return [], [
                Finding(
                    "warn",
                    "route-metadata-field",
                    f"{surface.rel_path} {key} must be a non-empty scalar root-relative path",
                    surface.rel_path,
                    line,
                )
            ]
        return [_normalize_route_metadata_path(value)], []

    if isinstance(value, str):
        if not value.strip():
            return [], [
                Finding(
                    "warn",
                    "route-metadata-field",
                    f"{surface.rel_path} {key} must not be empty",
                    surface.rel_path,
                    line,
                )
            ]
        normalized = _normalize_route_metadata_path(value)
        if not _route_metadata_value_is_path_like(normalized):
            return [], [_route_metadata_non_path_value_finding(surface, key, value, line)]
        return [normalized], []

    if isinstance(value, list):
        if not value:
            return [], []
        if all(isinstance(item, str) and item.strip() for item in value):
            paths: list[str] = []
            non_path_values: list[str] = []
            for item in value:
                normalized = _normalize_route_metadata_path(item)
                if _route_metadata_value_is_path_like(normalized):
                    paths.append(normalized)
                else:
                    non_path_values.append(item)
            if non_path_values:
                sample = ", ".join(repr(item) for item in non_path_values[:3])
                return paths, [
                    Finding(
                        "warn",
                        "route-metadata-field",
                        f"{surface.rel_path} {key} contains non-path route metadata value(s): {sample}",
                        surface.rel_path,
                        line,
                    )
                ]
            return paths, []

    return [], [
        Finding(
            "warn",
            "route-metadata-field",
            f"{surface.rel_path} {key} must be a non-empty scalar path or non-empty list of scalar paths",
            surface.rel_path,
            line,
        )
    ]


def _route_metadata_non_path_value_finding(surface: Surface, key: str, value: object, line: int | None) -> Finding:
    return Finding(
        "warn",
        "route-metadata-field",
        f"{surface.rel_path} {key} must be a root-relative route path, got non-path value: {value!r}",
        surface.rel_path,
        line,
    )


def _route_metadata_path_findings(inventory: Inventory, surface: Surface, key: str, rel_path: str) -> list[Finding]:
    findings: list[Finding] = []
    line = _frontmatter_key_line(surface, key)
    if _route_metadata_path_is_unsafe(rel_path):
        return [
            Finding(
                "warn",
                "route-metadata-path",
                f"{surface.rel_path} {key} must be a root-relative path without absolute or parent-traversal segments: {rel_path}",
                surface.rel_path,
                line,
            )
        ]

    target = inventory.root / rel_path
    if _route_metadata_path_escapes_root(inventory.root, target):
        return [
            Finding(
                "warn",
                "route-metadata-path",
                f"{surface.rel_path} {key} path escapes the target root: {rel_path}",
                surface.rel_path,
                line,
            )
        ]

    path_conflict = _route_metadata_path_conflict(inventory.root, rel_path, target)
    if path_conflict:
        findings.append(Finding("warn", "route-metadata-path", f"{surface.rel_path} {key} {path_conflict}", surface.rel_path, line))
    elif not target.exists():
        findings.append(
            Finding(
                "warn",
                "route-metadata-missing-target",
                f"{surface.rel_path} {key} target is missing: {rel_path}",
                surface.rel_path,
                line,
            )
        )

    destination = _route_metadata_destination_finding(surface, key, rel_path, line)
    if destination:
        findings.append(destination)
    if target.exists() and not rel_path.startswith("project/archive/"):
        stale = _route_metadata_stale_reference_finding(inventory, surface, key, rel_path, line)
        if stale:
            findings.append(stale)
    return findings


def _route_metadata_destination_finding(surface: Surface, key: str, rel_path: str, line: int | None) -> Finding | None:
    if key == "archived_to":
        if not rel_path.startswith("project/archive/reference/") or not rel_path.endswith(".md"):
            return Finding(
                "warn",
                "route-metadata-destination",
                f"{surface.rel_path} archived_to must point under project/archive/reference/**/*.md: {rel_path}",
                surface.rel_path,
                line,
            )
        return None

    route_id = classify_memory_route(rel_path).route_id
    if key == "promoted_to":
        if rel_path.startswith("project/archive/") or route_id not in ROUTE_METADATA_PROMOTION_TARGET_ROUTES:
            return Finding(
                "warn",
                "route-metadata-destination",
                f"{surface.rel_path} promoted_to must point to an existing non-archive authority or product route: {rel_path}",
                surface.rel_path,
                line,
            )
        return None

    policy = route_destination_policy_for_field(key, owner_route_id=surface.memory_route)
    if policy is None:
        return None
    if route_destination_matches(policy, rel_path):
        return None
    return Finding(
        "warn",
        "route-metadata-destination",
        f"{surface.rel_path} {key} must point to {policy.label}: {rel_path}",
        surface.rel_path,
        line,
    )


def _route_metadata_stale_reference_finding(
    inventory: Inventory,
    surface: Surface,
    key: str,
    rel_path: str,
    line: int | None,
) -> Finding | None:
    if key.startswith("source_"):
        return None
    target_surface = inventory.surface_by_rel.get(rel_path)
    if not target_surface or not target_surface.frontmatter.has_frontmatter:
        return None
    if target_surface.frontmatter.data.get("archived_to") in (None, ""):
        return None
    return Finding(
        "warn",
        "route-metadata-stale-reference",
        f"{surface.rel_path} {key} points at active route {rel_path}, but that target already records archived_to",
        surface.rel_path,
        line,
    )


def _normalize_route_metadata_path(value: str) -> str:
    return re.sub(r"/+", "/", value.strip().strip("<>").strip().replace("\\", "/"))


def _route_metadata_value_is_path_like(value: str) -> bool:
    if not value:
        return False
    return (
        "/" in value
        or "\\" in value
        or value.endswith((".md", ".toml", ".yaml", ".yml", ".json"))
        or value.startswith((".", "~"))
        or _is_absolute_path(value)
    )


def _route_metadata_path_is_unsafe(rel_path: str) -> bool:
    if root_relative_path_conflict(rel_path):
        return True
    if any(separator in rel_path for separator in (";", "|")):
        return True
    return False


def _route_metadata_path_conflict(root: Path, rel_path: str, target: Path) -> str | None:
    for candidate in _root_relative_path_chain(root, rel_path):
        candidate_rel = candidate.relative_to(root).as_posix()
        if not candidate.exists():
            continue
        if candidate.is_symlink():
            return f"path contains a symlink segment: {candidate_rel}"
        if candidate != target and not candidate.is_dir():
            return f"path contains a non-directory segment: {candidate_rel}"
    if target.exists() and not target.is_file():
        return f"target is not a regular file: {rel_path}"
    return None


def _route_metadata_path_escapes_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _frontmatter_key_line(surface: Surface, key: str) -> int | None:
    lines = surface.content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return None
        if re.match(rf"^{re.escape(key)}\s*:", line):
            return index
    return None


def _docmap_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    docmap = inventory.surface_by_rel.get(".agents/docmap.yaml")
    if not docmap or not docmap.exists:
        return findings
    text = docmap.content
    for expected in ("README.md", "AGENTS.md", "project/project-state.md", "project/specs/workflow/"):
        if expected not in text:
            findings.append(Finding("warn", "docmap-routing", f"docmap does not mention {expected}", docmap.rel_path))
    return findings


def _mirror_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    for name in EXPECTED_SPEC_NAMES:
        live = inventory.surface_by_rel.get(f"project/specs/workflow/{name}")
        mirror = inventory.surface_by_rel.get(f"specs/workflow/{name}")
        if live and mirror and live.exists and mirror.exists and live.content != mirror.content:
            diff = "\n".join(
                difflib.unified_diff(
                    live.content.splitlines(),
                    mirror.content.splitlines(),
                    fromfile=live.rel_path,
                    tofile=mirror.rel_path,
                    lineterm="",
                    n=1,
                )
            )
            findings.append(Finding("error", "mirror-drift", f"package-source mirror differs from live spec:\n{diff}", mirror.rel_path))
    return findings


def _product_doc_frontmatter_audit_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    findings: list[Finding] = []
    plan_facing_specs = _plan_facing_spec_paths(inventory)
    for surface in sorted(inventory.present_surfaces, key=lambda item: item.rel_path):
        if surface.role != "product-doc" or surface.path.suffix.lower() != ".md":
            continue
        if surface.frontmatter.has_frontmatter or surface.frontmatter.errors:
            continue
        if surface.rel_path.startswith("docs/specs/") and surface.rel_path in plan_facing_specs:
            continue
        findings.append(
            Finding(
                "info",
                "product-doc-frontmatter-optional",
                (
                    f"{surface.rel_path} product doc has no frontmatter; product docs may use lightweight "
                    "routing frontmatter, while strict spec_status/implementation_posture is reserved for "
                    "plan-facing docs/specs contracts; suggested route class: product-docs"
                ),
                surface.rel_path,
                route_id=surface.memory_route,
            )
        )
        posture_reason = _product_doc_evidence_posture_reason(surface)
        if posture_reason:
            findings.append(
                Finding(
                    "warn",
                    "product-doc-evidence-posture",
                    (
                        f"{surface.rel_path} product doc has no frontmatter and {posture_reason} looks like "
                        "durable verification/evidence; keep it as product documentation with explicit "
                        "product-doc posture metadata, or move durable evidence under project/verification/*.md; "
                        "advisory only, no automatic rewrite or route move"
                    ),
                    surface.rel_path,
                    route_id=surface.memory_route,
                )
            )
    if findings:
        findings.append(
            Finding(
                "info",
                "product-doc-frontmatter-audit-boundary",
                "product-doc frontmatter audit covers current docs/**/*.md only; project/archive/** and project/archive/reference/** remain historical routes and are excluded from blanket docs/spec normalization",
            )
        )
    return findings


def _product_doc_evidence_posture_reason(surface: Surface) -> str:
    rel_text = surface.rel_path.casefold()
    if any(marker in rel_text for marker in PRODUCT_DOC_EVIDENCE_POSTURE_PATH_MARKERS):
        return "its path"
    content_sample = surface.content[:5000].casefold()
    if any(marker in content_sample for marker in PRODUCT_DOC_EVIDENCE_POSTURE_TEXT_MARKERS):
        return "its content"
    return ""


def _docmap_gap_findings(inventory: Inventory) -> list[Finding]:
    docmap = inventory.surface_by_rel.get(".agents/docmap.yaml")
    if not docmap or not docmap.exists:
        return []
    gaps = []
    expected = [
        "README.md",
        "AGENTS.md",
        _selected_manifest_rel(inventory),
        "project/project-state.md",
        "project/specs/workflow/",
    ]
    product_doc_candidates = ("docs/README.md", "docs/architecture/", "docs/specs/")
    cli_candidates = ("pyproject.toml", "src/mylittleharness/", "tests/")
    for rel in product_doc_candidates + cli_candidates:
        if (inventory.root / rel).exists():
            expected.append(rel)
    state = inventory.state
    plan_status = state.frontmatter.data.get("plan_status") if state and state.exists else None
    if plan_status == "active" or (inventory.active_plan_surface and inventory.active_plan_surface.exists):
        expected.append("project/implementation-plan.md")
    for rel in expected:
        if rel not in docmap.content:
            gaps.append(Finding("warn", "candidate-docmap-gap", f"candidate route missing from docmap: {rel}", docmap.rel_path))
    return gaps


def _stale_root_pointer_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    configured_roots = _configured_root_references(inventory)
    for surface in inventory.present_surfaces:
        if surface.role == "package-mirror":
            continue
        lines = surface.content.splitlines()
        for index, line in enumerate(lines, start=1):
            normalized = _display_path_value(line)
            fallback_root = configured_roots.get("fallback")
            product_root = configured_roots.get("product")
            operating_root = configured_roots.get("operating")
            if fallback_root and _line_references_path(normalized, fallback_root) and not _nearby_text_contains(
                lines, index, {"fallback", "archive", "evidence", "historical", "old", "reopened only"}
            ):
                findings.append(
                    Finding(
                        "warn",
                        "stale-fallback-root-reference",
                        "configured fallback/archive root is referenced without fallback/archive context",
                        surface.rel_path,
                        index,
                    )
                )
            if product_root and _line_references_path(normalized, product_root) and _line_claims_operating_role(normalized):
                findings.append(
                    Finding(
                        "warn",
                        "stale-product-root-role",
                        "configured product source root is described with operating-root wording; product roots should remain source/target only",
                        surface.rel_path,
                        index,
                    )
                )
            if operating_root and _line_references_path(normalized, operating_root) and _line_claims_product_role(normalized):
                findings.append(
                    Finding(
                        "warn",
                        "stale-operating-root-role",
                        "configured operating root is described with product-root wording; operating roots should remain operating memory",
                        surface.rel_path,
                        index,
                    )
                )
    return findings


def _configured_root_references(inventory: Inventory) -> dict[str, str]:
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    references = {
        "operating": data.get("operating_root") or data.get("canonical_source_evidence_root"),
        "product": data.get("product_source_root") or data.get("projection_root"),
        "fallback": data.get("historical_fallback_root"),
    }
    return {
        role: _root_reference_text(value, inventory.root)
        for role, value in references.items()
        if value not in (None, "")
    }


def _root_reference_text(value: object, root: Path) -> str:
    text = _display_path_value(str(value)).strip()
    try:
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        return str(candidate.resolve())
    except (OSError, RuntimeError):
        return text


def _line_references_path(line: str, reference: str) -> bool:
    if reference in {"", ".", str(Path("."))}:
        return False
    normalized_line = _display_path_value(line).replace("/", "\\").casefold()
    normalized_reference = _display_path_value(reference).replace("/", "\\").rstrip("\\").casefold()
    return normalized_reference in normalized_line


def _start_path_surfaces(inventory: Inventory) -> list[Surface]:
    preferred = [
        "project/project-state.md",
        "README.md",
        "AGENTS.md",
        ".agents/docmap.yaml",
        _selected_manifest_rel(inventory),
        "docs/README.md",
        "docs/architecture/product-architecture.md",
        "docs/architecture/layer-model.md",
        "docs/architecture/clean-room-carry-forward.md",
        "project/implementation-plan.md",
    ]
    surfaces = [inventory.surface_by_rel[rel] for rel in preferred if rel in inventory.surface_by_rel]
    surfaces.extend(
        surface
        for surface in inventory.surfaces
        if surface.role == "product-doc" and surface.exists and surface not in surfaces
    )
    surfaces.extend(
        surface
        for surface in inventory.surfaces
        if surface.role == "stable-spec" and surface.exists and surface not in surfaces
    )
    return surfaces


def _budget_label(lines: int, chars: int) -> str:
    if lines > VERY_LARGE_FILE_LINES or chars > VERY_LARGE_FILE_CHARS:
        return "very-large"
    if lines > LARGE_FILE_LINES or chars > LARGE_FILE_CHARS:
        return "large"
    return "normal"


def _git_findings(root: Path) -> list[Finding]:
    git = shutil.which("git")
    if not git:
        return [Finding("warn", "git-status", "git executable unavailable: git")]
    try:
        result = subprocess.run(
            [git, "-c", "core.quotePath=false", "-C", str(root), "status", "--untracked-files=all", "--porcelain=v1"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [Finding("warn", "git-status", f"git status unavailable: {exc}")]
    if result.returncode == 0:
        state = "clean" if not (result.stdout or "").strip() else "dirty"
        return [Finding("info", "git-status", f"git worktree detected: {state}")]
    message = (result.stderr or result.stdout or "").strip().splitlines()
    detail = message[0] if message else f"git exited {result.returncode}"
    return [Finding("info", "git-status", f"not a git worktree: {detail}")]


def external_orchestrator_shell_preflight_findings(
    inventory: Inventory,
    workspace: str,
    product_root: str = "",
) -> list[Finding]:
    workspace_path = Path(workspace).expanduser()
    product_path = Path(product_root).expanduser() if product_root else _configured_product_source_root(inventory)
    findings = [
        Finding(
            "info",
            "orchestrator-shell-preflight-profile",
            (
                "profile=generic-external-orchestrator; required=shell, git status, MLH check, MCP/read path; "
                "completion_policy=repo-visible handoff/claim/agent-run evidence before external done claims"
            ),
        ),
        Finding(
            "info",
            "orchestrator-shell-preflight-boundary",
            "capability probes are read-only process checks; they do not create workspaces, start workers, mutate trackers, write lifecycle routes, or approve dispatch",
            str(workspace_path),
        ),
    ]
    findings.extend(_external_orchestrator_live_product_findings(workspace_path, inventory.root, product_path))
    probe_gate_findings = _external_orchestrator_probe_gate_findings(workspace_path)
    findings.extend(probe_gate_findings)
    if not any(finding.severity == "warn" for finding in probe_gate_findings):
        findings.extend(_external_orchestrator_shell_probe_findings(workspace_path))
        findings.extend(_external_orchestrator_git_probe_findings(workspace_path))
        findings.extend(_external_orchestrator_mlh_probe_findings(workspace_path))
        findings.extend(_external_orchestrator_mcp_probe_findings(workspace_path))
    findings.append(
        Finding(
            "info",
            "orchestrator-completion-claim-policy",
            (
                "external orchestrator completion claims require repo-visible handoff, work-claim, and agent-run evidence; "
                "Linear/Symphony status, comments, or runtime memory alone are refused as MLH closeout or done-state proof"
            ),
            WORKSPACE_PREVIEW_SOURCE,
        )
    )
    if any(finding.severity == "warn" for finding in findings):
        findings.append(
            Finding(
                "warn",
                "orchestrator-shell-preflight-refused",
                (
                    "external dispatch is not preflighted until shell/process spawn, git status, MLH check, "
                    "MCP/read posture, and completion policy are all explicitly reviewable"
                ),
                str(workspace_path),
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "orchestrator-shell-preflight-ready",
                "external workspace capability probes passed; this remains readiness evidence only and does not start a worker",
                str(workspace_path),
            )
        )
    return findings


WORKSPACE_PREVIEW_SOURCE = "external-orchestrator-workspace"


def _configured_product_source_root(inventory: Inventory) -> Path | None:
    data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    value = str(data.get("product_source_root") or data.get("projection_root") or "").strip()
    if not value:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = inventory.root / candidate
    return candidate


def _external_orchestrator_live_product_findings(workspace: Path, root: Path, product_root: Path | None) -> list[Finding]:
    findings: list[Finding] = []
    resolved_workspace = _safe_resolve_path(workspace)
    resolved_root = _safe_resolve_path(root)
    if resolved_workspace == resolved_root:
        findings.append(Finding("warn", "orchestrator-shell-preflight-live-root", "candidate workspace is the live coordination root; dispatch requires a disposable root or explicit allowlist", str(workspace)))
    elif _path_is_within(resolved_workspace, resolved_root):
        findings.append(Finding("warn", "orchestrator-shell-preflight-live-root", "candidate workspace is inside the live coordination root; dispatch requires a disposable root or explicit allowlist", str(workspace)))
    if product_root:
        resolved_product = _safe_resolve_path(product_root)
        if resolved_workspace == resolved_product:
            findings.append(Finding("warn", "orchestrator-shell-preflight-product-root", "candidate workspace is the configured product source root; external agents need a disposable product source unless explicitly allowed", str(workspace)))
        elif _path_is_within(resolved_workspace, resolved_product):
            findings.append(Finding("warn", "orchestrator-shell-preflight-product-root", "candidate workspace is inside the configured product source root; external agents need a disposable product source unless explicitly allowed", str(workspace)))
    if not findings:
        findings.append(Finding("info", "orchestrator-shell-preflight-disposable-root", "candidate workspace is separate from the live coordination root and configured product source root", str(workspace)))
    return findings


def _external_orchestrator_shell_probe_findings(workspace: Path) -> list[Finding]:
    if not workspace.exists() or not workspace.is_dir():
        return [Finding("warn", "orchestrator-shell-capability-refused", "shell/process capability was not proven because the candidate workspace is not an existing directory", str(workspace))]
    result, error = _run_external_orchestrator_probe([sys.executable, "-c", "print('mlh-process-spawn-ok')"], workspace)
    if error:
        return [Finding("warn", "orchestrator-shell-capability-refused", f"process spawn failed before dispatch: {error}", str(workspace))]
    assert result is not None
    if result.returncode != 0:
        return [Finding("warn", "orchestrator-shell-capability-refused", f"process spawn exited {result.returncode}: {_probe_output(result)}", str(workspace))]
    return [Finding("info", "orchestrator-shell-capability-ok", f"process spawn succeeded in candidate workspace: {_probe_output(result)}", str(workspace))]


def _external_orchestrator_probe_gate_findings(workspace: Path) -> list[Finding]:
    if workspace.exists() and workspace.is_symlink():
        return [
            Finding(
                "warn",
                "orchestrator-shell-capability-refused",
                "capability probes were skipped because the candidate workspace is a symlink; choose a normal disposable directory",
                str(workspace),
            )
        ]
    return []


def _external_orchestrator_git_probe_findings(workspace: Path) -> list[Finding]:
    if not workspace.exists() or not workspace.is_dir():
        return [Finding("warn", "orchestrator-git-status-refused", "git status was not proven because the candidate workspace is not an existing directory", str(workspace))]
    git_executable, refusal = _external_orchestrator_resolved_executable("git", workspace, "orchestrator-git-status-refused", "git")
    if refusal:
        return [refusal]
    assert git_executable is not None
    result, error = _run_external_orchestrator_probe([git_executable, "status", "--short", "--branch"], workspace)
    if error:
        return [Finding("warn", "orchestrator-git-status-refused", f"git status failed before dispatch: {error}", str(workspace))]
    assert result is not None
    if result.returncode != 0:
        return [Finding("warn", "orchestrator-git-status-refused", f"git status exited {result.returncode}: {_probe_output(result)}", str(workspace))]
    detail = _probe_output(result) or "clean or empty status"
    return [Finding("info", "orchestrator-git-status-ok", f"git status ran in candidate workspace: {detail}", str(workspace))]


def _external_orchestrator_mlh_probe_findings(workspace: Path) -> list[Finding]:
    if not workspace.exists() or not workspace.is_dir():
        return [Finding("warn", "orchestrator-mlh-check-refused", "MLH check was not proven because the candidate workspace is not an existing directory", str(workspace))]
    mlh_executable, refusal = _external_orchestrator_resolved_executable(
        "mylittleharness",
        workspace,
        "orchestrator-mlh-check-refused",
        "mylittleharness",
    )
    if refusal:
        return [refusal]
    assert mlh_executable is not None
    result, error = _run_external_orchestrator_probe([mlh_executable, "--root", str(workspace), "check"], workspace)
    if error:
        return [Finding("warn", "orchestrator-mlh-check-refused", f"mylittleharness check failed before dispatch: {error}", str(workspace))]
    assert result is not None
    if result.returncode != 0:
        return [Finding("warn", "orchestrator-mlh-check-refused", f"mylittleharness check exited {result.returncode}: {_probe_output(result)}", str(workspace))]
    return [Finding("info", "orchestrator-mlh-check-ok", f"mylittleharness check ran in candidate workspace: {_probe_output(result)}", str(workspace))]


def _external_orchestrator_mcp_probe_findings(workspace: Path) -> list[Finding]:
    if not workspace.exists() or not workspace.is_dir():
        return [Finding("warn", "orchestrator-mcp-read-path-refused", "MCP/read path was not proven because the candidate workspace is not an existing directory", str(workspace))]
    mlh_executable, refusal = _external_orchestrator_resolved_executable(
        "mylittleharness",
        workspace,
        "orchestrator-mcp-read-path-refused",
        "mylittleharness",
    )
    if refusal:
        return [refusal]
    assert mlh_executable is not None
    command = [mlh_executable, "--root", str(workspace), "adapter", "--client-config", "--target", "mcp-read-projection"]
    result, error = _run_external_orchestrator_probe(command, workspace)
    if error:
        return [Finding("warn", "orchestrator-mcp-read-path-refused", f"MCP/read adapter probe failed before dispatch: {error}", str(workspace))]
    assert result is not None
    if result.returncode != 0:
        return [Finding("warn", "orchestrator-mcp-read-path-refused", f"MCP/read adapter probe exited {result.returncode}: {_probe_output(result)}", str(workspace))]
    detail = _probe_output(result) or "adapter client-config rendered"
    return [Finding("info", "orchestrator-mcp-read-path-ok", f"MCP/read adapter posture is reviewable: {detail}", str(workspace))]


def _external_orchestrator_resolved_executable(
    name: str,
    workspace: Path,
    refused_code: str,
    label: str,
) -> tuple[str | None, Finding | None]:
    found = shutil.which(name)
    if not found:
        return None, Finding("warn", refused_code, f"{label} executable is not available on PATH", str(workspace))
    executable = Path(found).expanduser()
    if not executable.is_absolute():
        executable = Path.cwd() / executable
    resolved = _safe_resolve_path(executable)
    resolved_workspace = _safe_resolve_path(workspace)
    if resolved == resolved_workspace or _path_is_within(resolved, resolved_workspace):
        return (
            None,
            Finding(
                "warn",
                refused_code,
                f"{label} executable resolves inside the candidate workspace; capability probe is refused: {resolved}",
                str(workspace),
            ),
        )
    return str(resolved), None


def _run_external_orchestrator_probe(command: list[str], cwd: Path) -> tuple[subprocess.CompletedProcess[str] | None, str]:
    try:
        return (
            subprocess.run(
                command,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            ),
            "",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)


def _probe_output(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stdout or result.stderr or "").strip().splitlines()
    if not output:
        return ""
    return output[0][:240]


def _safe_resolve_path(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _path_is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _intake_request_advice(request: IntakeRequest) -> IntakeRouteAdvice:
    return classify_intake_text_for_target(request.text, request.target)


def _intake_request_errors(inventory: Inventory, request: IntakeRequest, apply: bool, advice: IntakeRouteAdvice | None = None) -> list[Finding]:
    errors: list[Finding] = []
    if not request.text.strip():
        errors.append(Finding("error", "intake-refused", "intake text is required"))

    advice = advice or _intake_request_advice(request)
    if request.status:
        status = request.status.casefold()
        if status not in INTAKE_VERIFICATION_STATUS_VALUES:
            errors.append(
                Finding(
                    "error",
                    "intake-refused",
                    f"--status must be one of {', '.join(INTAKE_VERIFICATION_STATUS_VALUES)}",
                    request.target or None,
                )
            )
        elif advice.route_id != "verification":
            errors.append(Finding("error", "intake-refused", "--status is only supported for verification intake targets", request.target or None))
    if request.related_plan and advice.route_id != "verification":
        errors.append(Finding("error", "intake-refused", "--related-plan is only supported for verification intake targets", request.target or None))
    if request.source_members and advice.route_id != "verification":
        errors.append(Finding("error", "intake-refused", "--source-member is only supported for verification intake targets", request.target or None))
    if request.related_plan and request.related_plan != "current":
        conflict = root_relative_path_conflict(request.related_plan)
        if conflict:
            errors.append(Finding("error", "intake-refused", f"--related-plan must be a root-relative route path: {conflict}", request.related_plan))
    for source_member in request.source_members:
        conflict = root_relative_path_conflict(source_member)
        if conflict:
            errors.append(Finding("error", "intake-refused", f"--source-member must be a root-relative route path: {conflict}", source_member))
    if not apply and request.target and not advice.apply_allowed:
        errors.append(Finding("error", "intake-refused", f"input is ambiguous: {advice.reason}", request.target))
    if apply:
        if inventory.root_kind == "product_source_fixture":
            errors.append(Finding("error", "intake-refused", "target is a product-source compatibility fixture; intake --apply is refused", request.target or None))
        elif inventory.root_kind == "fallback_or_archive":
            errors.append(Finding("error", "intake-refused", "target is fallback/archive or generated-output evidence; intake --apply is refused", request.target or None))
        elif inventory.root_kind != "live_operating_root":
            errors.append(Finding("error", "intake-refused", f"target root kind is {inventory.root_kind}; intake --apply requires a live operating root", request.target or None))
        if not request.target:
            errors.append(Finding("error", "intake-refused", "--target is required with --apply"))
        if not advice.apply_allowed:
            errors.append(Finding("error", "intake-refused", f"input is ambiguous: {advice.reason}"))

    if request.target:
        errors.extend(_intake_target_errors(inventory, request.target, advice, apply))
    if apply and errors:
        errors.extend(_intake_incubation_fallback_findings(request, advice))
    return errors


def _intake_target_errors(inventory: Inventory, target: str, advice: IntakeRouteAdvice, apply: bool) -> list[Finding]:
    errors: list[Finding] = []
    if _intake_rel_has_absolute_or_parent_parts(target):
        return [Finding("error", "intake-refused", "--target must be a root-relative path without parent segments", target)]
    if not target.endswith(".md"):
        errors.append(Finding("error", "intake-refused", "--target must be a Markdown file", target))
    route_id = classify_memory_route(target).route_id
    if route_id not in INTAKE_ROUTE_ALLOWED_TARGETS:
        errors.append(
            Finding(
                "error",
                "intake-refused",
                f"--target route {route_id!r} is not an intake destination; use one of {', '.join(sorted(INTAKE_ROUTE_ALLOWED_TARGETS))}",
                target,
            )
        )
    elif advice.apply_allowed and not intake_target_matches_route(advice.route_id, target):
        errors.append(
            Finding(
                "error",
                "intake-refused",
                f"--target route {route_id!r} does not match classified route {advice.route_id!r}",
                target,
            )
        )
    target_path = inventory.root / target
    if _intake_path_escapes_root(inventory.root, target_path):
        errors.append(Finding("error", "intake-refused", "target path escapes the target root", target))
        return errors
    for parent in _intake_parents_between(inventory.root, target_path.parent):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "intake-refused", f"target directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "intake-refused", f"target directory contains a non-directory segment: {rel}", rel))
    if apply and target_path.exists():
        errors.append(Finding("error", "intake-refused", "target already exists; choose a new explicit intake file", target))
    return errors


def _intake_advice_findings(advice: IntakeRouteAdvice, request: IntakeRequest, prefix: str) -> list[Finding]:
    source = request.target or None
    status = _intake_document_status(request, advice)
    explicit_status = "explicit" if request.status else "derived"
    findings = [
        Finding(
            "info",
            "intake-route-advisor",
            f"{prefix}classify input as {advice.route_id}; target route: {advice.target}; confidence: {advice.confidence}; {advice.reason}",
            source,
        ),
        Finding("info", "intake-route-next-action", f"{prefix}{advice.next_action}", source),
    ]
    if advice.route_id == "verification":
        findings.append(
            Finding(
                "info",
                "intake-verification-frontmatter-status",
                f"{prefix}write verification frontmatter status={status!r} ({explicit_status}); decision-packet text is evidence, not status authority",
                source,
            )
        )
    return findings


def _intake_target_preview_findings(request: IntakeRequest, advice: IntakeRouteAdvice) -> list[Finding]:
    route_id = classify_memory_route(request.target).route_id
    compatible = advice.apply_allowed and intake_target_matches_route(advice.route_id, request.target)
    posture = "compatible" if compatible else "not compatible"
    return [
        Finding(
            "info",
            "intake-target",
            f"would target {request.target}; route: {route_id}; classifier compatibility: {posture}",
            request.target,
        )
    ]


def _intake_incubation_fallback_findings(request: IntakeRequest, advice: IntakeRouteAdvice) -> list[Finding]:
    if not _intake_future_incubation_signal(request):
        return []
    compatible = bool(request.target) and advice.apply_allowed and intake_target_matches_route(advice.route_id, request.target)
    if advice.route_id == "incubation" and compatible:
        return []
    target_note = ""
    if request.target and classify_memory_route(request.target).route_id == "archive":
        target_note = " Archive/reference incubation paths are historical references, not the live incubation write target."
    return [
        Finding(
            "info",
            "intake-incubation-fallback",
            (
                "future feature or Deep Research prompt-composition ideas should land in live project/plan-incubation/*.md; "
                "safest fallback command: `mylittleharness --root <root> incubate --dry-run --topic \"<topic>\" --note \"<note>\"` "
                f"before the matching apply.{target_note}"
            ),
            request.target or None,
        )
    ]


def _intake_future_incubation_signal(request: IntakeRequest) -> bool:
    normalized = re.sub(r"\s+", " ", request.text.casefold().replace("_", " ").replace("-", " ")).strip()
    future_signal = any(
        cue in normalized
        for cue in (
            "feature idea",
            "future feature",
            "future idea",
            "future product idea",
            "product idea",
            "not yet accepted",
        )
    )
    prompt_signal = any(cue in normalized for cue in ("deep research prompt", "research prompt", "prompt composition"))
    target = request.target.casefold().replace("\\", "/")
    target_signal = "project/plan-incubation/" in target or "project/archive/reference/incubation/" in target
    return bool((future_signal and (prompt_signal or target_signal)) or (prompt_signal and target_signal))


def _intake_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "intake-boundary",
            "intake dry-run is advisory; intake apply writes only one explicit new Markdown target in an eligible live operating root",
        ),
        Finding(
            "info",
            "intake-authority",
            "intake classification cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions, or roadmap promotion",
        ),
    ]


def _intake_document_text(inventory: Inventory, request: IntakeRequest, advice: IntakeRouteAdvice) -> str:
    title = _intake_title(request)
    status = _intake_document_status(request, advice)
    body = _intake_document_body(request)
    route_metadata = _intake_verification_route_metadata(inventory, request, advice)
    return (
        "---\n"
        f'title: "{_yaml_double_quoted_value(title)}"\n'
        f'status: "{_yaml_double_quoted_value(status)}"\n'
        f'route: "{_yaml_double_quoted_value(advice.route_id)}"\n'
        f"{route_metadata}"
        f'created: "{date.today().isoformat()}"\n'
        f'intake_source: "{_yaml_double_quoted_value(request.text_source)}"\n'
        "---\n"
        f"# {title}\n\n"
        f"{body}\n"
    )


def _intake_document_status(request: IntakeRequest, advice: IntakeRouteAdvice) -> str:
    if request.status:
        return request.status.casefold()
    if advice.route_id != "verification":
        return INTAKE_ROUTE_DEFAULT_STATUS.get(advice.route_id, "draft")
    if _intake_looks_like_decision_packet(request.text):
        return INTAKE_ROUTE_DEFAULT_STATUS.get("verification", "partial")
    normalized = re.sub(r"\s+", " ", request.text.casefold().replace("_", " ").replace("-", " ")).strip()
    if any(cue in normalized for cue in ("failed", "failure", "failing", "tests fail", "pytest fail", "validation failed")):
        return "failed"
    if any(cue in normalized for cue in ("tests passed", "pytest passed", "smoke passed", "validation passed", "verification passed")):
        return "passed"
    return INTAKE_ROUTE_DEFAULT_STATUS.get("verification", "partial")


def _intake_document_body(request: IntakeRequest) -> str:
    body = request.text.strip()
    frontmatter, payload = _split_intake_payload_frontmatter(body)
    if not frontmatter:
        return body
    payload = payload.strip() or "(empty payload body)"
    return (
        "## Intake Payload Frontmatter\n\n"
        "```yaml\n"
        f"{frontmatter.rstrip()}\n"
        "```\n\n"
        "## Intake Payload\n\n"
        f"{payload}"
    )


def _split_intake_payload_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    return "", text


def _intake_looks_like_decision_packet(text: str) -> bool:
    lowered = text.casefold()
    return "decision packet" in lowered or any(field in lowered for field in INTAKE_DECISION_PACKET_FIELDS)


def _intake_title(request: IntakeRequest) -> str:
    if request.title:
        return _clean_intake_title(request.title)
    for line in request.text.splitlines():
        cleaned = _clean_intake_title(re.sub(r"^[A-Za-z][A-Za-z -]{1,30}:\s*", "", line.strip()))
        if cleaned:
            return cleaned
    return "Incoming Information"


def _clean_intake_title(value: str) -> str:
    cleaned = re.sub(r"[`*_#\[\]<>]", "", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80].strip(" .,:;-") or "Incoming Information"


def _intake_verification_route_metadata(inventory: Inventory, request: IntakeRequest, advice: IntakeRouteAdvice) -> str:
    if advice.route_id != "verification":
        return ""
    related_plan = _intake_related_plan_metadata(inventory, request)
    source_members = request.source_members or _intake_active_plan_source_members(inventory)
    lines: list[str] = []
    if related_plan:
        lines.append(f'related_plan: "{_yaml_double_quoted_value(related_plan)}"')
    if source_members:
        lines.append("source_members:")
        for source_member in source_members:
            lines.append(f'  - "{_yaml_double_quoted_value(source_member)}"')
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _intake_related_plan_metadata(inventory: Inventory, request: IntakeRequest) -> str:
    if request.related_plan and request.related_plan != "current":
        return request.related_plan
    if request.related_plan == "current" or _intake_target_is_verification(request.target):
        active_plan = _intake_active_plan_rel(inventory)
        if active_plan:
            return active_plan
    return ""


def _intake_active_plan_rel(inventory: Inventory) -> str:
    state_data = inventory.state.frontmatter.data if inventory.state else {}
    plan_status = str(state_data.get("plan_status") or "").casefold()
    active_plan = _normalized_intake_metadata_path(state_data.get("active_plan"))
    if plan_status == "active":
        active_plan = active_plan or DEFAULT_PLAN_REL
    if active_plan and not root_relative_path_conflict(active_plan):
        return active_plan
    if inventory.active_plan_surface and inventory.active_plan_surface.exists:
        rel_path = _normalized_intake_metadata_path(inventory.active_plan_surface.rel_path)
        if rel_path and not root_relative_path_conflict(rel_path):
            return rel_path
    return ""


def _intake_active_plan_source_members(inventory: Inventory) -> tuple[str, ...]:
    if not inventory.active_plan_surface or not inventory.active_plan_surface.exists:
        return ()
    data = inventory.active_plan_surface.frontmatter.data
    members: list[str] = []
    source_incubation = _normalized_intake_metadata_path(data.get("source_incubation"))
    if source_incubation:
        members.append(source_incubation)
    for source_member in _frontmatter_path_values(data.get("source_members")):
        members.append(source_member)
    return _normalized_intake_metadata_paths(members)


def _frontmatter_path_values(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item or "").strip() for item in value if str(item or "").strip())
    normalized = str(value or "").strip()
    if not normalized:
        return ()
    return (normalized,)


def _intake_target_is_verification(target: str) -> bool:
    return classify_memory_route(target).route_id == "verification" if target else False


def _normalized_intake_target(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _normalized_intake_metadata_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip()


def _normalized_intake_metadata_paths(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        rel_path = _normalized_intake_metadata_path(value)
        if rel_path and rel_path not in seen:
            normalized.append(rel_path)
            seen.add(rel_path)
    return tuple(normalized)


def _intake_rel_has_absolute_or_parent_parts(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith("/") or re.match(r"^[A-Za-z]:", rel_path):
        return True
    parts = [part for part in rel_path.split("/") if part]
    return any(part in {".", ".."} for part in parts)


def _intake_path_escapes_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _intake_parents_between(root: Path, path: Path) -> list[Path]:
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


def _is_product_source_inventory(inventory: Inventory) -> bool:
    return inventory.root_kind == "product_source_fixture"


def _is_fallback_or_archive_inventory(inventory: Inventory) -> bool:
    return inventory.root_kind == "fallback_or_archive"


def _is_mylittleharness_product_context(inventory: Inventory) -> bool:
    if inventory.root_kind == "live_operating_root":
        return False
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    return (
        data.get("project") == EXPECTED_PRODUCT_NAME
        or data.get("root_role") == EXPECTED_PRODUCT_ROOT_ROLE
        or data.get("fixture_status") == EXPECTED_PRODUCT_FIXTURE_STATUS
        or bool(data.get("operating_root") or data.get("product_source_root") or data.get("historical_fallback_root"))
        or _same_path_value(data.get("product_source_root"), inventory.root)
        or _string_contains(inventory, "# MyLittleHarness")
    )


def _string_contains(inventory: Inventory, needle: str) -> bool:
    return any(surface.exists and needle in surface.content for surface in inventory.surfaces)


def _same_path_value(value: object, expected: Path) -> bool:
    if not value:
        return False
    normalized = _display_path_value(str(value))
    try:
        candidate = Path(normalized).expanduser()
        if not candidate.is_absolute():
            candidate = expected / candidate
        candidate = candidate.resolve()
        target = expected.expanduser().resolve()
        return str(candidate).casefold() == str(target).casefold()
    except (OSError, RuntimeError):
        return normalized.replace("/", "\\").rstrip("\\").casefold() == str(expected).replace("/", "\\").rstrip("\\").casefold()


def _display_path_value(value: str) -> str:
    return value.replace("\\\\", "\\")


def _is_absolute_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or Path(value).is_absolute()


def _link_base(root: Path, path_part: str, source_rel: str | None) -> Path:
    normalized = _normalized_link_path(path_part)
    if source_rel and source_rel.startswith("docs/") and normalized.startswith(("architecture/", "specs/")):
        return root / Path(source_rel).parent
    if not source_rel or _is_repo_root_relative_link(normalized):
        return root
    source_parent = Path(source_rel).parent
    if str(source_parent) in ("", "."):
        return root
    return root / source_parent


def _is_repo_root_relative_link(normalized: str) -> bool:
    if normalized in ROOT_RELATIVE_LINK_NAMES:
        return True
    return any(normalized.startswith(prefix) for prefix in ROOT_RELATIVE_LINK_PREFIXES)


def _expand_brace_pattern(value: str) -> list[str]:
    match = re.search(r"\{([^{}]+)\}", value)
    if not match:
        return [value]
    prefix = value[: match.start()]
    suffix = value[match.end() :]
    return [prefix + option + suffix for option in match.group(1).split(",")]


def _optional_missing_link_reason(inventory: Inventory, target: str) -> str | None:
    rel = _normalized_link_path(target)
    if not rel:
        return None
    root_rel = _root_relative_link_path(inventory, rel)
    if root_rel is not None:
        rel = root_rel

    if inventory.root_kind == "live_operating_root":
        if rel == WORKFLOW_MANIFEST_REL and inventory.manifest_surface and inventory.manifest_surface.rel_path == LEGACY_WORKFLOW_MANIFEST_REL:
            return f"{WORKFLOW_MANIFEST_REL} is absent on this legacy live root; {LEGACY_WORKFLOW_MANIFEST_REL} remains the selected fallback manifest"
        if rel == ".agents/docmap.yaml" and inventory.manifest.get("policy", {}).get("docmap_mode") == "lazy":
            return "docmap is lazy for this live operating root"
        if rel == "README.md":
            return "root README.md is optional for live operating roots"
        if rel == "project/roadmap.md":
            return "project/roadmap.md is an optional live-root roadmap route"
        if rel.startswith(("docs/", "architecture/", "specs/")) and _configured_product_root_contains_link(inventory, rel):
            return "configured product source root contains this product documentation link; product docs are not required inside the live operating root"

    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    operating_root = _normalized_link_path(str(state_data.get("operating_root") or state_data.get("canonical_source_evidence_root") or ""))
    fallback_root = _normalized_link_path(str(state_data.get("historical_fallback_root") or ""))
    if operating_root and rel.lower() == operating_root.lower().rstrip("/"):
        return "configured operating root is external local evidence, not a required in-tree product surface"
    if fallback_root and rel.lower() == fallback_root.lower().rstrip("/"):
        return "configured fallback/archive root is opt-in local evidence, not a required product surface"
    if operating_root and rel.lower().startswith(operating_root.lower().rstrip("/") + "/"):
        rel = rel[len(operating_root.rstrip("/")) + 1 :]

    plan_status = state_data.get("plan_status")
    manifest_plan = "project/implementation-plan.md"
    if inventory.manifest:
        manifest_plan = inventory.manifest.get("memory", {}).get("plan_file", manifest_plan)
    if rel == str(manifest_plan).replace("\\", "/") and plan_status != "active":
        return "the implementation plan is a lazy surface when plan_status is not active"

    if rel == DETACH_MARKER_REL_PATH:
        return "detach marker is created only when detach is active and may be absent"
    if rel == ".mylittleharness/generated/projection" or rel.startswith(".mylittleharness/generated/projection/"):
        return "generated projection artifacts are disposable navigation output and may be rebuilt when needed"
    if rel in {"project/verification/agent-runs", "project/verification/approval-packets", "project/verification/work-claims"}:
        return "optional evidence directories are created only when those records exist"
    if rel.startswith(("project/verification/agent-runs/", "project/verification/approval-packets/", "project/verification/work-claims/")):
        return "optional evidence records are created only when an agent run, approval packet, or work claim exists"
    if rel in {"project/archive/reference/research", "project/archive/reference/research/"}:
        return "archived research reference directory is optional until research is archived"
    if rel.startswith("project/archive/reference/project-state-history-") and rel.endswith(".md"):
        return "project-state history archive names in docs are examples until compaction creates a concrete file"
    if rel.startswith(".harness/"):
        return "legacy harness sketch paths in research are historical context, not required MLH scaffold"
    if rel == "project/plan-incubation" or rel.startswith("project/plan-incubation/"):
        return "plan incubation surfaces are optional and only exist when a lane is open"
    if rel in {DOCMAP_REPAIR_COPY_REL, STATE_FRONTMATTER_COPY_REL}:
        return "snapshot copied-file paths are relative to a repair snapshot directory, not the repo root"

    fixture_root = (
        state_data.get("projection_status") == "candidate-projection"
        or state_data.get("root_role") == "product-source"
        or state_data.get("fixture_status") == "product-compatibility-fixture"
    )
    if fixture_root:
        if rel == "project/roadmap.md":
            return "roadmap route examples belong in serviced live operating roots, not this product source fixture"
        if rel == "project/adrs" or rel.startswith("project/adrs/"):
            return "ADR route examples belong in serviced live operating roots, not this product source fixture"
        if rel == "project/decisions" or rel.startswith("project/decisions/"):
            return "decision route examples belong in serviced live operating roots, not this product source fixture"
        if rel == "project/verification" or rel.startswith("project/verification/"):
            return "verification route examples belong in serviced live operating roots, not this product source fixture"
        if (rel == "project/research" or rel.startswith("project/research/")) and rel != "project/research/README.md":
            return "source-root research artifacts are intentionally excluded from this product compatibility fixture"
        if rel == "research/README.md":
            return "the root package-source research mirror is intentionally excluded from this product compatibility fixture"
        if rel.startswith("project/archive/"):
            return "legacy archives are intentionally excluded from this product compatibility fixture"
        if rel == "specs/workflow" or rel.startswith("specs/workflow/"):
            return "root package-source spec mirrors are intentionally excluded from this product source tree"
    return None


def _configured_product_root_contains_link(inventory: Inventory, rel: str) -> bool:
    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    product_root = str(state_data.get("product_source_root") or state_data.get("projection_root") or "").strip()
    if not product_root:
        return False
    base = Path(product_root)
    candidates = [base / rel]
    if rel.startswith(("architecture/", "specs/")):
        candidates.append(base / "docs" / rel)
    return any(candidate.exists() for candidate in candidates)


def _normalized_link_path(target: str) -> str:
    clean = target.strip().strip("<>").strip()
    if not clean or clean.startswith("#"):
        return ""
    path_part = clean.split("#", 1)[0]
    return re.sub(r"/+", "/", path_part.replace("\\", "/"))


def _root_relative_link_path(inventory: Inventory, rel: str) -> str | None:
    if not _is_absolute_path(rel):
        return None
    root = _normalized_link_path(str(inventory.root)).rstrip("/")
    if rel.casefold() == root.casefold():
        return ""
    prefix = root + "/"
    if rel.casefold().startswith(prefix.casefold()):
        return rel[len(prefix) :]
    return None


def _nearby_text_contains(lines: list[str], line_number: int, needles: set[str]) -> bool:
    start = max(0, line_number - 3)
    end = min(len(lines), line_number + 1)
    window = " ".join(lines[start:end]).lower()
    return any(needle in window for needle in needles)


def _line_claims_operating_role(line: str) -> bool:
    lowered = line.lower()
    if any(
        marker in lowered
        for marker in (
            "not an operating",
            "not the operating",
            "not operating",
            "must not",
            "not hold",
            "product source",
            "source tree",
            "fixture metadata",
            "target root",
        )
    ):
        return False
    return any(marker in lowered for marker in ("operating root", "operating/research", "working plans", "active implementation plans", "workflow execution"))


def _line_claims_product_role(line: str) -> bool:
    lowered = line.lower()
    if any(marker in lowered for marker in ("operating root", "operating/research", "research pilot", "plans, state", "operating evidence")):
        return False
    return any(marker in lowered for marker in ("product source root", "product root", "product repository", "fixture metadata"))


def load_for_root(root: Path) -> Inventory:
    return load_inventory(root)
