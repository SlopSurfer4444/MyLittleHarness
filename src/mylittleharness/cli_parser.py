from __future__ import annotations

import argparse

from .adapter import APPROVAL_RELAY_TARGET, MCP_READ_PROJECTION_TARGET
from .meta_feedback import META_FEEDBACK_ROOT_ENV_VAR


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--limit must be an integer >= 1") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("--limit must be >= 1")
    return parsed


def _nonnegative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--quiet-period-seconds must be a number >= 0") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("--quiet-period-seconds must be >= 0")
    return parsed


def _hide_suppressed_top_level_commands(subparsers: argparse._SubParsersAction) -> None:
    subparsers._choices_actions = [action for action in subparsers._choices_actions if action.help != argparse.SUPPRESS]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mylittleharness",
        description="MyLittleHarness repo safety utility. Primary commands: init, check, repair, detach.",
        epilog="Compatibility and advanced diagnostics remain available for recovery and transition.",
    )
    parser.add_argument("--root", default=None, help="Target workflow root. Defaults to the current directory.")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="{init,check,repair,detach,...}")
    init = subparsers.add_parser("init", help="Attach MyLittleHarness to a target repository.")
    init_mode = init.add_mutually_exclusive_group(required=True)
    init_mode.add_argument("--dry-run", action="store_true", help="Report the init proposal without writing files.")
    init_mode.add_argument("--apply", action="store_true", help="Create only allowed missing scaffold/template paths.")
    init.add_argument("--project", help="Project name to use when creating project/project-state.md.")
    check = subparsers.add_parser("check", help="Run read-only status and validation checks without writing files.")
    check_mode = check.add_mutually_exclusive_group()
    check_mode.add_argument("--quick", action="store_true", help="Render a compact routine check report without the full source inventory.")
    check_mode.add_argument("--deep", action="store_true", help="Include links, context, and hygiene diagnostics in the read-only check report.")
    check_mode.add_argument(
        "--focus",
        choices=("validation", "links", "context", "hygiene", "grain", "archive-context", "route-references", "agents", "retention"),
        help="Run one focused read-only diagnostic through check.",
    )
    check.add_argument("--json", action="store_true", help="Emit a structured JSON report.")
    manifest = subparsers.add_parser(
        "manifest",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: inspect the structured route and role manifest for external agents and orchestrators.",
    )
    manifest.add_argument("--inspect", action="store_true", required=True, help="Inspect the route and role manifest without writing files.")
    manifest.add_argument("--json", action="store_true", help="Emit the route and role manifest as structured JSON.")
    migrate = subparsers.add_parser(
        "migrate",
        help="Copy a legacy workflow config to the neutral workflow path.",
        description="Preview or apply legacy .codex/project-workflow.toml migration to .mylittleharness/project-workflow.toml.",
    )
    migrate_mode = migrate.add_mutually_exclusive_group(required=True)
    migrate_mode.add_argument("--dry-run", action="store_true", help="Preview migration without writing files.")
    migrate_mode.add_argument("--apply", action="store_true", help="Copy the legacy workflow manifest to the neutral path.")
    dashboard = subparsers.add_parser(
        "dashboard",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: inspect the read-only local coordination dashboard without starting a runtime.",
    )
    dashboard.add_argument("--inspect", action="store_true", required=True, help="Inspect dashboard data without writing files or starting a server.")
    dashboard.add_argument("--json", action="store_true", help="Emit the dashboard cockpit payload as structured JSON.")
    dashboard.add_argument(
        "--detail",
        choices=("auto", "degraded", "full"),
        default="auto",
        help="Projection detail for dashboard inspect; auto degrades large roots, full opts into complete projection rebuild.",
    )
    mlhd = subparsers.add_parser(
        "mlhd",
        help=argparse.SUPPRESS,
        description="Advanced control plane: explicit root-local mlhd runtime commands.",
    )
    mlhd_actions = mlhd.add_subparsers(dest="mlhd_action", required=True, metavar="{status,doctor,start,stop,run-once,install,uninstall}")
    mlhd_status = mlhd_actions.add_parser("status", help="Inspect disposable mlhd runtime control-plane state without writing files.")
    mlhd_status.add_argument("--json", action="store_true", help="Emit the mlhd control-plane payload as structured JSON.")
    mlhd_doctor = mlhd_actions.add_parser("doctor", help="Inspect mlhd runtime, autostart, and authority boundaries without writing files.")
    mlhd_doctor.add_argument("--json", action="store_true", help="Emit the mlhd control-plane payload as structured JSON.")
    for action in ("start", "stop", "run-once", "install", "uninstall"):
        control = mlhd_actions.add_parser(action, help=f"Preview or apply the explicit mlhd {action} control-plane operation.")
        control_mode = control.add_mutually_exclusive_group(required=True)
        control_mode.add_argument("--dry-run", action="store_true", help="Preview disposable runtime writes without changing files.")
        control_mode.add_argument(
            "--apply",
            action="store_true",
            help="Write explicit disposable runtime control-plane files; run-once may also warm generated projection cache.",
        )
        control.add_argument("--json", action="store_true", help="Emit the mlhd control-plane payload as structured JSON.")
        if action == "run-once":
            control.add_argument(
                "--quiet-period-seconds",
                type=_nonnegative_float,
                default=1.0,
                help="Defer generated projection warm-cache until dirty markers have been quiet for this many seconds.",
            )
    suggest = subparsers.add_parser(
        "suggest",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: report deterministic command intent suggestions as route candidates without running them.",
    )
    suggest_mode = suggest.add_mutually_exclusive_group(required=True)
    suggest_mode.add_argument("--intent", help="Operator action to match against the deterministic command intent registry.")
    suggest_mode.add_argument("--list", action="store_true", help="List the deterministic command intent registry.")
    suggest.add_argument("--limit", type=_positive_int, default=3, help="Maximum suggestions to return for --intent. Defaults to 3.")
    suggest.add_argument("--json", action="store_true", help="Emit machine-readable command suggestions.")
    repair = subparsers.add_parser("repair", help="Preview or apply deterministic workflow contract repair.")
    repair_mode = repair.add_mutually_exclusive_group(required=True)
    repair_mode.add_argument("--dry-run", action="store_true", help="Report the repair proposal without writing files.")
    repair_mode.add_argument("--apply", action="store_true", help="Create only allowed missing repair paths.")
    detach = subparsers.add_parser("detach", help="Preview harness detach posture without writing files.")
    detach_mode = detach.add_mutually_exclusive_group(required=True)
    detach_mode.add_argument("--dry-run", action="store_true", help="Report detach preservation and refusal posture without writing files.")
    detach_mode.add_argument("--apply", action="store_true", help="Create the marker-only detach evidence file in an eligible live operating root.")
    for command in ("status", "validate", "context-budget", "audit-links", "closeout"):
        subparsers.add_parser(command)
    doctor = subparsers.add_parser("doctor")
    doctor.add_argument(
        "--integration",
        choices=("mcp", "vscode", "claude-code", "jetbrains"),
        help="Inspect a read-only client integration smoke profile without writing files.",
    )
    evidence = subparsers.add_parser(
        "evidence",
        help=argparse.SUPPRESS,
        description="Advanced evidence helper: report closeout evidence or explicitly record source-bound agent run evidence.",
    )
    evidence.add_argument("--record", action="store_true", help="Write or preview an explicit agent run evidence record.")
    evidence.add_argument("--receipt-refresh", action="store_true", help="Refresh source_hashes on an existing worker-run receipt JSON file.")
    evidence.add_argument("--retarget-ref", action="store_true", help="Retarget one route-owned evidence provenance ref with a reviewed token.")
    evidence_mode = evidence.add_mutually_exclusive_group()
    evidence_mode.add_argument("--dry-run", action="store_true", help="Preview an agent run evidence record without writing files.")
    evidence_mode.add_argument("--apply", action="store_true", help="Write one explicit agent run evidence record in a live operating root.")
    evidence.add_argument("--target", dest="receipt_target", help="Root-relative evidence target for --receipt-refresh or --retarget-ref.")
    evidence.add_argument("--old-ref", dest="old_ref", help="Existing root-relative provenance ref to replace for --retarget-ref.")
    evidence.add_argument("--new-ref", dest="new_ref", help="Reviewed root-relative provenance ref to write for --retarget-ref.")
    evidence.add_argument("--proposal-token", dest="proposal_token", help="Reviewed proposal token emitted by the matching evidence dry-run.")
    evidence.add_argument("--record-id", dest="record_id", help="Stable record id used as the Markdown filename under project/verification/agent-runs/.")
    evidence.add_argument("--role", dest="agent_role", help="Agent role that produced the work, such as coder, reviewer, or verifier.")
    evidence.add_argument("--actor", help="Human, agent, or tool actor label.")
    evidence.add_argument("--task", help="One-line task summary for the run record.")
    evidence.add_argument("--assigned-scope", dest="assigned_scope", help="Assigned scope or slice this run was responsible for.")
    evidence.add_argument("--runtime", help="Runtime or adapter surface used for the run, such as local-shell, codex, or mlhd.")
    evidence.add_argument("--worktree-id", dest="worktree_id", help="Worktree or checkout identity used by the run.")
    evidence.add_argument("--status", choices=("succeeded", "failed", "blocked", "skipped", "needs-refinement", "needs-human-review"), help="Run outcome status.")
    evidence.add_argument("--stop-reason", dest="stop_reason", help="Why the run stopped.")
    evidence.add_argument("--attempt-budget", dest="attempt_budget", help="Attempt budget posture, such as 1/3 or exhausted.")
    evidence.add_argument("--input-ref", dest="input_refs", action="append", default=[], help="Root-relative input route or source path. May be repeated.")
    evidence.add_argument("--output-ref", dest="output_refs", action="append", default=[], help="Root-relative output evidence or source path. May be repeated.")
    evidence.add_argument("--claimed-path", dest="claimed_paths", action="append", default=[], help="Root-relative path claimed or changed by the run. May be repeated.")
    evidence.add_argument("--changed-file", dest="changed_files", action="append", default=[], help="Root-relative file changed by the run. May be repeated.")
    evidence.add_argument("--command", dest="commands", action="append", default=[], help="Command run or intentionally recorded by the agent. May be repeated.")
    evidence.add_argument("--verification-ref", dest="verification_refs", action="append", default=[], help="Root-relative verification evidence path. May be repeated.")
    evidence.add_argument("--docs-decision", dest="docs_decision", choices=("updated", "not-needed", "uncertain"), help="Docs decision observed by the run.")
    evidence.add_argument("--residual-risk", dest="residual_risk", help="Residual risk summary for the run.")
    evidence.add_argument("--handoff-ref", dest="handoff_refs", action="append", default=[], help="Root-relative handoff packet reference. May be repeated.")
    evidence.add_argument("--claim-ref", dest="claim_refs", action="append", default=[], help="Root-relative work claim reference. May be repeated.")
    evidence.add_argument("--repeated-failure-signature", dest="repeated_failure_signature", help="Optional repeated failure or no-progress loop signature.")
    evidence.add_argument("--provider", help="Optional model/provider provenance.")
    evidence.add_argument("--model-id", dest="model_id", help="Optional model identifier provenance.")
    evidence.add_argument("--tool", dest="tools", action="append", default=[], help="Optional tool metadata. May be repeated.")
    retention = subparsers.add_parser(
        "retention",
        help=argparse.SUPPRESS,
        description="Advanced evidence lifecycle helper: scan, retire, tombstone, or purge obsolete evidence with reviewed receipts.",
    )
    retention_actions = retention.add_subparsers(dest="retention_action", required=True, metavar="{scan,retire,tombstone,purge}")
    retention_scan = retention_actions.add_parser("scan", help="Classify evidence retention candidates without writing files.")
    retention_scan.add_argument("--path", dest="paths", action="append", required=True, help="Root-relative evidence path or directory to classify. May be repeated.")
    retention_scan.add_argument("--policy", choices=("exact-paths", "agent-runs-obsolete"), default="exact-paths", help="Retention policy lens for classification.")
    retention_scan.add_argument("--json", action="store_true", help="Emit a structured retention scan report.")
    for retention_action in ("retire", "tombstone", "purge"):
        retention_command = retention_actions.add_parser(retention_action, help=f"Preview or apply reviewed evidence {retention_action}.")
        retention_mode = retention_command.add_mutually_exclusive_group(required=True)
        retention_mode.add_argument("--dry-run", action="store_true", help=f"Preview evidence {retention_action} without writing files.")
        retention_mode.add_argument("--apply", action="store_true", help=f"Apply reviewed evidence {retention_action} and write a receipt.")
        retention_command.add_argument("--path", dest="paths", action="append", required=True, help="Exact root-relative evidence file path. May be repeated.")
        retention_command.add_argument("--policy", choices=("exact-paths", "agent-runs-obsolete"), default="exact-paths", help="Retention policy lens for classification.")
        retention_command.add_argument("--reason", required=True, help="Reason this evidence is obsolete, retired, or safe to clean.")
        retention_command.add_argument("--receipt-id", dest="receipt_id", help="Stable receipt id used as the JSON filename under project/verification/retention-receipts/.")
        retention_command.add_argument("--json", action="store_true", help="Emit a structured retention route report.")
    claim = subparsers.add_parser(
        "claim",
        help=argparse.SUPPRESS,
        description="Advanced coordination helper: create, release, or inspect repo-visible scoped work claims.",
    )
    claim_mode = claim.add_mutually_exclusive_group(required=True)
    claim_mode.add_argument("--dry-run", action="store_true", help="Preview a work claim create/release without writing files.")
    claim_mode.add_argument("--apply", action="store_true", help="Write or release one repo-visible work claim in an eligible live operating root.")
    claim_mode.add_argument("--status", action="store_true", help="Inspect work claim records without writing files.")
    claim.add_argument("--json", action="store_true", help="Emit a structured JSON report.")
    claim.add_argument("--action", choices=("create", "extend", "release"), default="create", help="Work claim mutation action. Defaults to create.")
    claim.add_argument("--claim-id", dest="claim_id", help="Stable claim id used as the JSON filename under project/verification/work-claims/.")
    claim.add_argument("--claim-kind", dest="claim_kind", help="Claim kind such as read, write, lifecycle, route, path, port, database, or resource.")
    claim.add_argument("--owner-role", dest="owner_role", help="Role that owns the claim, such as coder or verifier.")
    claim.add_argument("--owner-actor", dest="owner_actor", help="Human, agent, or tool actor label.")
    claim.add_argument("--execution-slice", dest="execution_slice", help="Execution slice this claim belongs to.")
    claim.add_argument("--worktree-id", dest="worktree_id", help="Optional isolated worktree id.")
    claim.add_argument("--base-revision", dest="base_revision", help="Optional base revision for fan-in comparison.")
    claim.add_argument("--claimed-route", dest="claimed_routes", action="append", default=[], help="Claimed MLH route id. May be repeated.")
    claim.add_argument("--claimed-path", dest="claimed_paths", action="append", default=[], help="Claimed root-relative path. May be repeated.")
    claim.add_argument("--claimed-resource", dest="claimed_resources", action="append", default=[], help="Claimed resource such as port:3000. May be repeated.")
    claim.add_argument("--lease-expires-at", dest="lease_expires_at", help="Optional ISO UTC timestamp after which an active claim reports stale.")
    claim.add_argument("--ttl", dest="ttl", help="Optional lease duration such as 900s, 30m, 2h, or 1d.")
    claim.add_argument("--release-condition", dest="release_condition", help="Release condition or release note.")
    handoff = subparsers.add_parser(
        "handoff",
        help=argparse.SUPPRESS,
        description="Advanced coordination helper: create repo-visible handoff packets for scoped worker work.",
    )
    handoff_mode = handoff.add_mutually_exclusive_group(required=True)
    handoff_mode.add_argument("--dry-run", action="store_true", help="Preview a handoff packet without writing files.")
    handoff_mode.add_argument("--apply", action="store_true", help="Write one repo-visible handoff packet in an eligible live operating root.")
    handoff_mode.add_argument("--status", action="store_true", help="Inspect handoff packets without writing files.")
    handoff.add_argument("--action", choices=("create", "accept"), default="create", help="Handoff mutation action. Defaults to create.")
    handoff.add_argument("--handoff-id", dest="handoff_id", help="Stable handoff id used as the JSON filename under project/verification/handoffs/.")
    handoff.add_argument("--worker-id", dest="worker_id", help="Worker or actor receiving the handoff.")
    handoff.add_argument("--role-id", dest="role_id", help="Role profile id for the receiver.")
    handoff.add_argument("--execution-slice", dest="execution_slice", help="Execution slice this handoff belongs to.")
    handoff.add_argument("--worktree-id", dest="worktree_id", help="Optional isolated worktree id.")
    handoff.add_argument("--branch", help="Optional worker branch.")
    handoff.add_argument("--base-revision", dest="base_revision", help="Optional base revision.")
    handoff.add_argument("--head-revision", dest="head_revision", help="Optional head revision or patch hash.")
    handoff.add_argument("--allowed-route", dest="allowed_routes", action="append", default=[], help="Allowed MLH route id. May be repeated.")
    handoff.add_argument("--write-scope", dest="write_scope", action="append", default=[], help="Allowed root-relative write-scope path. May be repeated.")
    handoff.add_argument("--stop-condition", dest="stop_conditions", action="append", default=[], help="Stop condition. May be repeated.")
    handoff.add_argument("--context-budget", dest="context_budget", help="Compact handoff context budget.")
    handoff.add_argument("--required-output", dest="required_outputs", action="append", default=[], help="Required output field. May be repeated.")
    handoff.add_argument("--evidence-ref", dest="evidence_refs", action="append", default=[], help="Root-relative evidence reference. May be repeated.")
    handoff.add_argument("--approval-packet-ref", dest="approval_packet_refs", action="append", default=[], help="Root-relative approval packet reference. May be repeated.")
    handoff.add_argument("--claim-ref", dest="claim_refs", action="append", default=[], help="Root-relative work claim reference. May be repeated.")
    handoff.add_argument("--accepted-by", dest="accepted_by", help="Actor accepting an existing handoff packet.")
    handoff.add_argument("--acceptance-note", dest="acceptance_note", help="Optional acceptance note for --action accept.")
    approval_packet = subparsers.add_parser(
        "approval-packet",
        help=argparse.SUPPRESS,
        description="Advanced coordination helper: create repo-visible human-gate approval packets.",
    )
    approval_packet_mode = approval_packet.add_mutually_exclusive_group(required=True)
    approval_packet_mode.add_argument("--dry-run", action="store_true", help="Preview an approval packet without writing files.")
    approval_packet_mode.add_argument("--apply", action="store_true", help="Write one repo-visible approval packet in an eligible live operating root.")
    approval_packet.add_argument("--approval-id", dest="approval_id", help="Stable approval id used as the JSON filename under project/verification/approval-packets/.")
    approval_packet.add_argument("--requester", help="Actor requesting the approval packet.")
    approval_packet.add_argument("--subject", help="Subject of the approval request.")
    approval_packet.add_argument("--requested-decision", dest="requested_decision", help="Decision being requested.")
    approval_packet.add_argument("--gate-class", dest="gate_class", help="Gate class such as lifecycle, authority, product-contract, or release.")
    approval_packet.add_argument("--status", choices=("pending", "approved", "rejected", "needs-review"), default="pending", help="Approval packet status. Defaults to pending.")
    approval_packet.add_argument("--input-ref", dest="input_refs", action="append", default=[], help="Root-relative input reference. May be repeated.")
    approval_packet.add_argument("--human-gate-condition", dest="human_gate_conditions", action="append", default=[], help="Human gate condition. May be repeated.")
    approval_packet.add_argument("--notes", help="Optional approval packet note.")
    review_token = subparsers.add_parser(
        "review-token",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: compute or verify a deterministic fan-in review token without writing files.",
    )
    review_token.add_argument("--operation-id", dest="operation_id", required=True, help="Coordinator operation id bound into the review token.")
    review_token.add_argument("--route", dest="routes", action="append", required=True, help="Route id or route label bound into the token. May be repeated.")
    review_token.add_argument("--claim-ref", dest="claim_refs", action="append", default=[], help="Root-relative work claim reference. May be repeated.")
    review_token.add_argument("--claim-hash", dest="claim_hashes", action="append", default=[], help="Explicit claim digest. May be repeated.")
    review_token.add_argument("--evidence-ref", dest="evidence_refs", action="append", default=[], help="Root-relative evidence reference. May be repeated.")
    review_token.add_argument("--evidence-hash", dest="evidence_hashes", action="append", default=[], help="Explicit evidence digest. May be repeated.")
    review_token.add_argument("--patch-hash", dest="patch_hashes", action="append", default=[], help="Patch or diff digest. May be repeated.")
    review_token.add_argument("--verifier-output", dest="verifier_outputs", action="append", default=[], help="Verifier output string to hash into the token. May be repeated.")
    review_token.add_argument("--human-gate-ref", dest="human_gate_refs", action="append", default=[], help="Root-relative human-gate or approval-packet reference. May be repeated.")
    review_token.add_argument("--human-gate-hash", dest="human_gate_hashes", action="append", default=[], help="Explicit human-gate digest. May be repeated.")
    review_token.add_argument("--expected-token", dest="expected_token", help="Optional token to verify against current repo-visible inputs.")
    subparsers.add_parser(
        "reconcile",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: report route/source/evidence drift and worker-space residue without applying cleanup.",
    )
    intake = subparsers.add_parser(
        "intake",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: route incoming information before it becomes incubation clutter.",
    )
    intake_mode = intake.add_mutually_exclusive_group(required=True)
    intake_mode.add_argument("--dry-run", action="store_true", help="Classify the intake text without writing files.")
    intake_mode.add_argument("--apply", action="store_true", help="Write one explicit new Markdown intake target in a compatible route.")
    intake_text = intake.add_mutually_exclusive_group(required=True)
    intake_text.add_argument("--text", help="Incoming information to classify or write.")
    intake_text.add_argument("--text-file", dest="text_file", help="Read incoming information from a UTF-8 file; use - for stdin.")
    intake.add_argument("--title", help="Optional Markdown title for the applied intake note.")
    intake.add_argument("--status", choices=("pending", "passed", "failed", "partial", "partially-verified", "archived"), help="Explicit status for verification intake frontmatter.")
    intake.add_argument("--related-plan", dest="related_plan", help="Verification metadata related_plan route; use 'current' to bind the active plan.")
    intake.add_argument("--source-member", dest="source_members", action="append", default=[], help="Verification metadata source_members route. May be repeated.")
    intake.add_argument("--target", help="Explicit root-relative Markdown target for --apply.")
    research_import = subparsers.add_parser(
        "research-import",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: import external research output as non-authority project/research provenance.",
    )
    research_import_mode = research_import.add_mutually_exclusive_group(required=True)
    research_import_mode.add_argument("--dry-run", action="store_true", help="Preview imported research artifact creation without writing files.")
    research_import_mode.add_argument("--apply", action="store_true", help="Write one imported research artifact in an eligible live operating root.")
    research_import.add_argument("--title", required=True, help="Research artifact title and default filename slug.")
    research_import_text = research_import.add_mutually_exclusive_group(required=True)
    research_import_text.add_argument("--text", help="External or human-run research output to import; prefer --text-file for multiline decision packets.")
    research_import_text.add_argument("--text-file", dest="text_file", help="Read research output from a UTF-8 file; use - for stdin; preserves multiline decision packets.")
    research_import_text.add_argument("--from-attachment", dest="from_attachment", help="Root-relative project/attachments/**/artifact.md card to open a research handoff from.")
    research_import.add_argument("--target", help="Optional explicit root-relative target under project/research/*.md.")
    research_import.add_argument("--topic", help="Optional frontmatter topic. Defaults to --title.")
    research_import.add_argument("--source", dest="source_label", help="Optional source/provenance label for the imported research.")
    research_import.add_argument("--related-prompt", dest="related_prompt", help="Optional root-relative prompt or framing artifact.")
    attachment_import = subparsers.add_parser(
        "attachment-import",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: copy a binary attachment into project/attachments with sidecar metadata authority.",
    )
    attachment_import_mode = attachment_import.add_mutually_exclusive_group(required=True)
    attachment_import_mode.add_argument("--dry-run", action="store_true", help="Preview attachment copy and metadata sidecar creation without writing files.")
    attachment_import_mode.add_argument("--apply", action="store_true", help="Copy one supported binary attachment and write its metadata sidecar.")
    attachment_import.add_argument("--file", required=True, help="Source PDF/DOCX/XLSX/PNG/JPG/ZIP file to import.")
    attachment_import.add_argument("--kind", required=True, help="Attachment kind slug, such as vendor-proposal.")
    attachment_import.add_argument("--topic", required=True, help="Topic slug for the target attachment directory.")
    attachment_import.add_argument("--title", required=True, help="Human-readable attachment title.")
    attachment_import.add_argument("--received-at", dest="received_at", help="Optional received date as YYYY-MM-DD. Defaults to today.")
    attachment_import.add_argument("--source", dest="source_label", help="Optional provenance label, such as email attachment.")
    attachment_import.add_argument("--related-research", dest="related_research", action="append", default=(), help="Optional project/research/*.md reference; repeatable.")
    discover = subparsers.add_parser(
        "discover",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: write one explicit pre-plan discovery packet as non-authority project/research evidence.",
    )
    discover_mode = discover.add_mutually_exclusive_group(required=True)
    discover_mode.add_argument("--dry-run", action="store_true", help="Preview discovery packet creation without writing files.")
    discover_mode.add_argument("--apply", action="store_true", help="Write one discovery packet in an eligible live operating root.")
    discover.add_argument("--topic", required=True, help="Discovery topic and default filename slug.")
    discover.add_argument("--goal", help="Optional discovery goal. Defaults to --topic.")
    discover.add_argument("--target", help="Optional explicit root-relative target under project/research/*.md.")
    discover.add_argument("--packet-id", dest="packet_id", help="Optional stable packet id. Defaults to the topic slug.")
    discover.add_argument("--quality-status", choices=("sufficient-for-planning", "provisional"), default="provisional", help="Explicit existing research gate quality status.")
    discover.add_argument("--planning-reliance", choices=("allowed", "blocked"), default="blocked", help="Explicit existing research gate planning reliance.")
    discover.add_argument(
        "--discovery-status",
        choices=("draft", "ready-for-plan", "reviewed", "blocked", "contested"),
        default="draft",
        help="Operator-supplied discovery status. draft/blocked/contested require planning reliance blocked.",
    )
    discover.add_argument("--source-ref", dest="source_refs", action="append", default=[], help="Root-relative source evidence reference. May be repeated.")
    discover.add_argument("--source-member", dest="source_members", action="append", default=[], help="Root-relative source member reference. May be repeated.")
    discover.add_argument("--evidence-ref", dest="evidence_refs", action="append", default=[], help="Root-relative supporting evidence reference. May be repeated.")
    discover.add_argument("--selected-option", dest="selected_option", help="Optional operator-supplied selected option.")
    discover.add_argument("--rationale", help="Optional operator-supplied rationale.")
    discover.add_argument("--open-question", dest="open_questions", action="append", default=[], help="Open question to record. May be repeated.")
    discover.add_argument("--stop-condition", dest="stop_conditions", action="append", default=[], help="Planning stop condition to record. May be repeated.")
    research_distill = subparsers.add_parser(
        "research-distill",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: distill one project/research artifact into non-authority source-candidate and gap evidence.",
    )
    research_distill_mode = research_distill.add_mutually_exclusive_group(required=True)
    research_distill_mode.add_argument("--dry-run", action="store_true", help="Preview distilled research artifact creation without writing files.")
    research_distill_mode.add_argument("--apply", action="store_true", help="Write one distilled research artifact in an eligible live operating root.")
    research_distill.add_argument("--source", required=True, help="Root-relative source research artifact under project/research/*.md.")
    research_distill.add_argument("--title", help="Optional distillate title. Defaults to source frontmatter or heading.")
    research_distill.add_argument("--target", help="Optional explicit root-relative target under project/research/*.md.")
    research_distill.add_argument("--topic", help="Optional frontmatter topic. Defaults to the distillate title.")
    research_compare = subparsers.add_parser(
        "research-compare",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: compare imported/distilled research artifacts into one non-authority provenance matrix.",
    )
    research_compare_mode = research_compare.add_mutually_exclusive_group(required=True)
    research_compare_mode.add_argument("--dry-run", action="store_true", help="Preview compared research artifact creation without writing files.")
    research_compare_mode.add_argument("--apply", action="store_true", help="Write one compared research artifact in an eligible live operating root.")
    research_compare.add_argument("--source", dest="sources", action="append", required=True, help="Root-relative imported/distilled research artifact under project/research/*.md. Repeat at least twice.")
    research_compare.add_argument("--title", help="Optional comparison title. Defaults to the first source title.")
    research_compare.add_argument("--target", help="Optional explicit root-relative target under project/research/*.md.")
    research_compare.add_argument("--topic", help="Optional frontmatter topic. Defaults to the comparison title.")
    research_compare.add_argument("--archive-sources", action="store_true", help="After creating the comparison artifact, archive compared sources with updated source metadata in the same apply.")
    research_compare.add_argument("--repair-links", action="store_true", help="With --archive-sources, repair exact root-relative source path references to the derived archive paths.")
    incubate = subparsers.add_parser(
        "incubate",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: create or append explicit future-idea incubation notes.",
    )
    incubate_mode = incubate.add_mutually_exclusive_group(required=True)
    incubate_mode.add_argument("--dry-run", action="store_true", help="Preview the incubation note target without writing files.")
    incubate_mode.add_argument("--apply", action="store_true", help="Create or append the same-topic incubation note in an eligible live operating root.")
    incubate.add_argument("--topic", required=True, help="Plain future-idea topic used to derive the safe note slug.")
    incubate_note = incubate.add_mutually_exclusive_group(required=True)
    incubate_note.add_argument("--note", help="Explicit incubation note text to record.")
    incubate_note.add_argument("--note-file", dest="note_file", help="Read explicit incubation note text from a UTF-8 file; use - for stdin.")
    incubate.add_argument("--fix-candidate", action="store_true", help="Prefix the note with [MLH-Fix-Candidate] if it is not already tagged.")
    incubation_reconcile = subparsers.add_parser(
        "incubation-reconcile",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: classify incubation note lifecycle posture and write bounded reconciliation metadata.",
    )
    incubation_reconcile_mode = incubation_reconcile.add_mutually_exclusive_group(required=True)
    incubation_reconcile_mode.add_argument("--dry-run", action="store_true", help="Preview incubation lifecycle classifications without writing files.")
    incubation_reconcile_mode.add_argument("--apply", action="store_true", help="Write reconciliation metadata to selected incubation notes in an eligible live operating root.")
    incubation_reconcile.add_argument("--source", dest="sources", action="append", default=[], help="Root-relative incubation note to reconcile. May be repeated; defaults to all notes.")
    incubation_reconcile.add_argument("--class", dest="classes", action="append", default=[], help="Limit to one lifecycle class. May be repeated.")
    plan = subparsers.add_parser(
        "plan",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: create or replace a deterministic active implementation-plan scaffold with current-phase-only execution metadata.",
    )
    plan_mode = plan.add_mutually_exclusive_group(required=True)
    plan_mode.add_argument("--dry-run", action="store_true", help="Preview deterministic implementation-plan synthesis without writing files.")
    plan_mode.add_argument("--apply", action="store_true", help="Write the active implementation plan and lifecycle frontmatter in an eligible live operating root.")
    plan.add_argument("--title", help="Implementation plan title to render into frontmatter and the first heading. Required unless --roadmap-item can derive it.")
    plan.add_argument("--objective", help="Concrete objective to render into the generated implementation plan. Required unless --roadmap-item can derive it.")
    plan.add_argument("--task", help="Optional explicit task input to preserve inside the generated plan.")
    plan.add_argument("--update-active", action="store_true", help="Replace the current default active plan when project-state already has plan_status active.")
    plan.add_argument("--roadmap-item", dest="roadmap_item", help="Optional existing roadmap item id to link to the active plan.")
    plan.add_argument("--only-requested-item", action="store_true", help="Limit roadmap sync and slice frontmatter to only --roadmap-item.")
    plan.add_argument("--target-artifact", dest="target_artifacts", action="append", default=[], help="Concrete root-relative target artifact to scope the generated active plan. May be repeated and does not mutate roadmap metadata.")
    plan_cancel = subparsers.add_parser(
        "plan-cancel",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: cancel accidental active-plan activation without closeout or archive authority.",
    )
    plan_cancel_mode = plan_cancel.add_mutually_exclusive_group(required=True)
    plan_cancel_mode.add_argument("--dry-run", action="store_true", help="Preview active-plan activation cancellation without writing files.")
    plan_cancel_mode.add_argument("--apply", action="store_true", help="Clear active-plan lifecycle pointers and remove the active plan route in an eligible live operating root.")
    plan_cancel.add_argument("--roadmap-item", dest="roadmap_item", help="Optional roadmap item to restore to accepted while clearing active related_plan metadata.")
    plan_cancel.add_argument("--keep-plan", action="store_true", help="Keep project/implementation-plan.md while clearing lifecycle activation, for manual review cases.")
    plan_cancel.add_argument("--source-hash", dest="source_hash", help="Full sha256 activation source hash reported by plan-cancel --dry-run; required for apply.")
    writeback = subparsers.add_parser(
        "writeback",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: apply explicit closeout/state writeback and synchronize derived active-plan copies; lifecycle writes do not approve auto-continue.",
    )
    writeback_mode = writeback.add_mutually_exclusive_group(required=True)
    writeback_mode.add_argument("--dry-run", action="store_true", help="Preview closeout/state writeback without writing files.")
    writeback_mode.add_argument("--apply", action="store_true", help="Write the MLH-owned closeout/state writeback block and synchronized derived copies.")
    writeback.add_argument("--worktree-start-state", dest="worktree_start_state", help="Closeout worktree_start_state value to record.")
    writeback.add_argument("--task-scope", dest="task_scope", help="Closeout task_scope value to record.")
    writeback.add_argument("--docs-decision", dest="docs_decision", help="Closeout docs_decision value: updated, not-needed, or uncertain.")
    writeback.add_argument("--state-writeback", dest="state_writeback", help="Closeout state_writeback value to record.")
    writeback.add_argument("--verification", help="Closeout verification value to record.")
    writeback.add_argument("--commit-decision", dest="commit_decision", help="Closeout commit_decision value to record.")
    writeback.add_argument("--residual-risk", dest="residual_risk", help="Optional closeout residual_risk value to record.")
    writeback.add_argument("--next-state", dest="next_state", help="Explicit next/no-next closeout state: no-next-action, human-decision-required, or legal-dry-run-command:<dry-run command>.")
    writeback.add_argument("--carry-forward", dest="carry_forward", help="Optional closeout carry_forward value to record.")
    writeback.add_argument("--work-result", dest="work_result", help="Optional plain-language closeout work_result capsule to record.")
    writeback.add_argument("--active-phase", dest="active_phase", help="Lifecycle active_phase value to write to project-state frontmatter.")
    writeback.add_argument("--phase-status", dest="phase_status", help="Lifecycle phase_status value to write to project-state frontmatter.")
    writeback.add_argument("--last-archived-plan", dest="last_archived_plan", help="Lifecycle last_archived_plan value to write to project-state frontmatter.")
    writeback.add_argument("--product-source-root", dest="product_source_root", help="Structured product_source_root value to write to project-state frontmatter.")
    writeback.add_argument("--archive-active-plan", action="store_true", help="Move the active implementation plan to the canonical archive and close the active lifecycle pointer.")
    writeback.add_argument(
        "--on-archive-collision",
        dest="archive_collision_policy",
        choices=("refuse", "preserve-existing"),
        default="refuse",
        help="Archive target collision policy. Default refuses; preserve-existing keeps the old archive and writes this closeout to a deterministic collision path.",
    )
    writeback.add_argument("--from-active-plan", action="store_true", help="Harvest closeout facts from the active plan Closeout Summary/Facts/Fields section.")
    writeback.add_argument("--compact-only", action="store_true", help="Only preview or apply safe project-state history compaction.")
    writeback.add_argument("--source-hash", dest="source_hash", help="Full sha256 hash reported by compact-only dry-run; required for compact-only apply when compaction would write.")
    writeback.add_argument("--allow-auto-compaction", action="store_true", help="Allow explicit lifecycle writeback to run project-state auto-compaction when the dry-run reports it would cross the size threshold.")
    writeback.add_argument("--roadmap-item", dest="roadmap_item", help="Optional existing roadmap item id to receive selected plan/writeback relationship facts.")
    writeback.add_argument("--roadmap-status", dest="roadmap_status", help="Optional roadmap status to write with --roadmap-item.")
    writeback.add_argument("--archived-plan", dest="archived_plan", help="Archived implementation-plan route to refresh closeout, roadmap, and source-incubation facts after the active lifecycle has already closed.")
    transition = subparsers.add_parser(
        "transition",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: explicitly review and apply a closeout/archive/next-plan transition composed from writeback and plan rails.",
    )
    transition_mode = transition.add_mutually_exclusive_group(required=True)
    transition_mode.add_argument("--dry-run", action="store_true", help="Preview the transition proposal and review token without writing files.")
    transition_mode.add_argument("--apply", action="store_true", help="Apply the reviewed transition only when --review-token matches current repo-visible inputs.")
    transition.add_argument("--review-token", help="Review token printed by the matching transition dry-run; required for --apply.")
    transition.add_argument("--complete-current-phase", action="store_true", help="First write phase_status complete through writeback.")
    transition.add_argument("--archive-active-plan", action="store_true", help="Archive the current active plan through writeback after any phase completion step.")
    transition.add_argument(
        "--on-archive-collision",
        dest="archive_collision_policy",
        choices=("refuse", "preserve-existing"),
        default="refuse",
        help="Archive target collision policy for the delegated archive-active-plan step.",
    )
    transition.add_argument("--allow-auto-compaction", action="store_true", help="Allow writeback steps in this transition to run project-state auto-compaction when the dry-run reports it would cross the size threshold.")
    transition.add_argument("--from-active-plan", action="store_true", help="Harvest archive closeout facts from the active plan.")
    transition.add_argument("--current-roadmap-item", dest="current_roadmap_item", help="Explicit current roadmap item to mark done during archive closeout.")
    transition.add_argument(
        "--current-roadmap-status",
        dest="current_roadmap_status",
        choices=("done", "blocked", "superseded"),
        help="Explicit terminal status for --current-roadmap-item during archive closeout. Defaults to done.",
    )
    transition.add_argument("--next-roadmap-item", dest="next_roadmap_item", help="Explicit roadmap item for the next active implementation plan.")
    transition.add_argument("--next-title", dest="next_title", help="Title for the next active implementation plan. Derived from --next-roadmap-item when omitted and available.")
    transition.add_argument("--next-objective", dest="next_objective", help="Objective for the next active implementation plan. Derived from --next-roadmap-item when omitted and available.")
    transition.add_argument("--next-task", dest="next_task", help="Optional explicit task input for the next active implementation plan. Derived from --next-roadmap-item when omitted and available.")
    transition.add_argument("--only-requested-item", action="store_true", help="Limit next-plan roadmap sync and slice frontmatter to --next-roadmap-item.")
    transition.add_argument("--worktree-start-state", dest="worktree_start_state", help="Archive closeout worktree_start_state value to record.")
    transition.add_argument("--task-scope", dest="task_scope", help="Archive closeout task_scope value to record.")
    transition.add_argument("--docs-decision", dest="docs_decision", help="Archive closeout docs_decision value: updated, not-needed, or uncertain.")
    transition.add_argument("--state-writeback", dest="state_writeback", help="Archive closeout state_writeback value to record.")
    transition.add_argument("--verification", help="Archive closeout verification value to record.")
    transition.add_argument("--commit-decision", dest="commit_decision", help="Archive closeout commit_decision value to record.")
    transition.add_argument("--residual-risk", dest="residual_risk", help="Optional archive closeout residual_risk value to record.")
    transition.add_argument("--next-state", dest="next_state", help="Explicit next/no-next archive closeout state: no-next-action, human-decision-required, or legal-dry-run-command:<dry-run command>.")
    transition.add_argument("--carry-forward", dest="carry_forward", help="Optional archive closeout carry_forward value to record.")
    transition.add_argument("--work-result", dest="work_result", help="Optional plain-language archive closeout work_result capsule to record.")
    memory_hygiene = subparsers.add_parser(
        "memory-hygiene",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: apply explicit research/incubation lifecycle hygiene.",
    )
    memory_hygiene_mode = memory_hygiene.add_mutually_exclusive_group(required=True)
    memory_hygiene_mode.add_argument("--dry-run", action="store_true", help="Preview lifecycle hygiene without writing files.")
    memory_hygiene_mode.add_argument("--apply", action="store_true", help="Write bounded lifecycle metadata, archive movement, and exact link repairs in an eligible live operating root.")
    memory_hygiene.add_argument("--source", help="Root-relative MLH-owned research/incubation Markdown source to update.")
    memory_hygiene.add_argument("--promoted-to", dest="promoted_to", help="Root-relative accepted destination recorded as promoted_to.")
    memory_hygiene.add_argument("--status", help="Lifecycle status to write. Defaults to distilled when --promoted-to is supplied.")
    memory_hygiene.add_argument("--archive-to", dest="archive_to", help="Explicit root-relative archive target under project/archive/reference/research or incubation.")
    memory_hygiene.add_argument("--archive-list-file", dest="archive_list_file", help="Root-relative reviewed path-list file of project/plan-incubation/*.md sources to archive.")
    memory_hygiene.add_argument("--archive-folder", dest="archive_folder", help="Root-relative target folder under project/archive/reference/ for reviewed archive-list movement; index.md is written there.")
    memory_hygiene.add_argument("--repair-links", action="store_true", help="Repair exact root-relative source path references to the archive path.")
    memory_hygiene.add_argument("--scan", action="store_true", help="Read-only relationship hygiene and incubation cleanup advisor scan; valid with --dry-run.")
    memory_hygiene.add_argument("--archive-covered", action="store_true", help="For incubation notes, derive an archive target and require terminal Entry Coverage before archive.")
    memory_hygiene.add_argument("--entry-coverage", dest="entry_coverage", action="append", default=[], help="Terminal Entry Coverage bullet value `<entry-id>: <status> <destination>`; may be repeated.")
    memory_hygiene.add_argument("--rotate-ledger", action="store_true", help="Rotate a project/verification ledger into archive/reference/verification and seed a fresh continuity ledger.")
    memory_hygiene.add_argument("--source-hash", dest="source_hash", help="Full sha256 hash reported by --rotate-ledger dry-run; required for rotation apply.")
    memory_hygiene.add_argument("--reason", help="One-line reason recorded in the fresh verification ledger or archive-list manifest.")
    memory_hygiene.add_argument("--proposal-token", dest="proposal_token", help="Proposal token reported by dry-run scan or archive-list; required for token-bound apply.")
    relationship_drift = subparsers.add_parser(
        "relationship-drift",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: preview or apply roadmap/source-incubation relationship metadata drift repairs.",
    )
    relationship_drift_mode = relationship_drift.add_mutually_exclusive_group(required=True)
    relationship_drift_mode.add_argument("--dry-run", action="store_true", help="Preview relationship graph retarget/detach decisions without writing files.")
    relationship_drift_mode.add_argument("--apply", action="store_true", help="Write bounded relationship metadata repairs in an eligible live operating root.")
    relationship_drift.add_argument("--roadmap-item", dest="roadmap_item", help="Optional roadmap item id to inspect/repair; defaults to all roadmap items.")
    cleanup = subparsers.add_parser(
        "cleanup",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: remove one reviewed temporary route-input artifact without touching lifecycle Markdown.",
    )
    cleanup_mode = cleanup.add_mutually_exclusive_group(required=True)
    cleanup_mode.add_argument("--dry-run", action="store_true", help="Preview temporary artifact cleanup without deleting files.")
    cleanup_mode.add_argument("--apply", action="store_true", help="Delete one reviewed temporary roadmap JSON manifest in an eligible live operating root.")
    cleanup.add_argument("--target", required=True, help="Root-relative target, such as project/verification/roadmap-routing-YYYY-MM-DD-*.json.")
    cleanup.add_argument("--reason", help="Optional one-line cleanup reason recorded in the report.")
    roadmap = subparsers.add_parser(
        "roadmap",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: add, batch-add, batch-update, update, or normalize explicit accepted-work roadmap items.",
    )
    roadmap.add_argument("operation", nargs="?", choices=("normalize",), help="Run a whole-roadmap housekeeping operation, such as normalize.")
    roadmap_mode = roadmap.add_mutually_exclusive_group(required=True)
    roadmap_mode.add_argument("--dry-run", action="store_true", help="Preview roadmap item changes without writing files.")
    roadmap_mode.add_argument("--apply", action="store_true", help="Write one bounded roadmap change in an eligible live operating root.")
    roadmap.add_argument("--action", choices=("add", "add-many", "update", "update-many", "normalize"), help="Roadmap mutation action.")
    roadmap.add_argument("--items-file", dest="items_file", help="Read add-many or update-many roadmap items from a UTF-8 JSON or YAML manifest; use - for stdin.")
    roadmap.add_argument("--item-id", help="Stable roadmap item id to add or update.")
    roadmap.add_argument("--title", help="Roadmap item heading. Required for --action add.")
    roadmap.add_argument("--status", help="Roadmap item status.")
    roadmap.add_argument("--stage", help="Optional scalar stage label for roadmap item reviewability.")
    roadmap.add_argument("--order", type=int, help="Roadmap item ordering value.")
    roadmap.add_argument("--execution-slice", dest="execution_slice", help="Advisory execution slice id for this roadmap item.")
    roadmap.add_argument("--slice-goal", dest="slice_goal", help="One-line advisory goal for the roadmap execution slice.")
    roadmap.add_argument("--slice-member", dest="slice_members", action="append", default=[], help="Roadmap item id covered by the same advisory execution slice. May be repeated.")
    roadmap.add_argument("--slice-dependency", dest="slice_dependencies", action="append", default=[], help="Roadmap item id that the advisory execution slice depends on. May be repeated.")
    roadmap.add_argument("--slice-closeout-boundary", dest="slice_closeout_boundary", help="One-line advisory closeout boundary for the execution slice.")
    roadmap.add_argument("--source-incubation", dest="source_incubation", help="Root-relative source incubation route.")
    roadmap.add_argument("--source-research", dest="source_research", help="Root-relative source research route.")
    roadmap.add_argument("--source-member", dest="source_members", action="append", default=[], help="Root-relative source evidence route covered by this roadmap item. May be repeated.")
    roadmap.add_argument("--related-spec", dest="related_specs", action="append", default=[], help="Root-relative related spec route. May be repeated.")
    roadmap.add_argument("--related-plan", dest="related_plan", help="Root-relative active or archived plan route.")
    roadmap.add_argument("--archived-plan", dest="archived_plan", help="Root-relative archived plan route.")
    roadmap.add_argument("--target-artifact", dest="target_artifacts", action="append", default=[], help="Root-relative expected implementation target artifact. May be repeated.")
    roadmap.add_argument("--verification-summary", dest="verification_summary", help="One-line verification summary.")
    roadmap.add_argument("--docs-decision", dest="docs_decision", help="Docs decision: updated, not-needed, or uncertain.")
    roadmap.add_argument("--carry-forward", dest="carry_forward", help="One-line carry-forward summary.")
    roadmap.add_argument("--clear-field", dest="clear_fields", action="append", default=[], help="First-class roadmap field to clear during --action update. May be repeated.")
    roadmap.add_argument("--field", dest="custom_fields", action="append", default=[], help="Custom scalar roadmap item field as key=value. May be repeated.")
    roadmap.add_argument("--dependency", dest="dependencies", action="append", default=[], help="Existing roadmap item id dependency. May be repeated.")
    roadmap.add_argument("--supersedes", dest="supersedes", action="append", default=[], help="Existing roadmap item id superseded by this item. May be repeated.")
    roadmap.add_argument("--superseded-by", dest="superseded_by", action="append", default=[], help="Existing roadmap item id that supersedes this item. May be repeated.")
    meta_feedback = subparsers.add_parser(
        "meta-feedback",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: collect MLH-Fix-Candidate meta-feedback into central incubation cluster memory.",
    )
    meta_feedback_mode = meta_feedback.add_mutually_exclusive_group(required=True)
    meta_feedback_mode.add_argument("--dry-run", action="store_true", help="Preview meta-feedback intake without writing files.")
    meta_feedback_mode.add_argument("--apply", action="store_true", help="Write one fix-candidate incubation note and managed cluster metadata.")
    meta_feedback.add_argument(
        "--to-root",
        dest="to_root",
        help=(
            "Destination central MyLittleHarness-dev live operating root for the canonical incubation note and "
            f"cluster metadata. Defaults to ${META_FEEDBACK_ROOT_ENV_VAR} when set, otherwise --root."
        ),
    )
    meta_feedback.add_argument("--from-root", dest="from_root", help="Observed source root where the rough edge was noticed. Defaults to --root.")
    meta_feedback.add_argument("--topic", required=True, help="Plain topic used for the incubation note and dedupe key.")
    meta_feedback_note = meta_feedback.add_mutually_exclusive_group(required=True)
    meta_feedback_note.add_argument("--note", help="Explicit meta-feedback note text to record.")
    meta_feedback_note.add_argument("--note-file", dest="note_file", help="Read explicit meta-feedback note text from a UTF-8 file; use - for stdin.")
    meta_feedback.add_argument("--signal-type", dest="signal_type", help="Optional signal type, such as lifecycle-drift or reviewability-gap.")
    meta_feedback.add_argument("--severity", help="Optional severity label for placement context.")
    meta_feedback.add_argument("--hook-event", dest="hook_event", help="Optional hook event name, such as pre-tool-use or post-tool-use.")
    meta_feedback.add_argument("--tool-name", dest="tool_name", help="Optional tool or command surface involved in the hook incident.")
    meta_feedback.add_argument("--blocked-surface", dest="blocked_surface", help="Optional file, route, command, or output surface the hook blocked or warned about.")
    meta_feedback.add_argument("--intended-route", dest="intended_route", help="Optional legal route the operator was trying to use.")
    meta_feedback.add_argument("--legal-route-available", dest="legal_route_available", help="Whether a safe first-class route was available and obvious.")
    meta_feedback.add_argument("--next-safe-command", dest="next_safe_command", help="Optional next safe command the hook should have suggested or preserved.")
    meta_feedback.add_argument("--hook-classification", dest="hook_classification", help="Classification such as safety-correct, overblocked, underblocked, output-suppression, or partial-execution-risk.")
    meta_feedback.add_argument("--false-positive-shape", dest="false_positive_shape", help="Optional shape of a safe action that the hook treated as unsafe.")
    meta_feedback.add_argument("--false-negative-shape", dest="false_negative_shape", help="Optional shape of an unsafe or ambiguous action the hook let through.")
    meta_feedback.add_argument("--output-suppression", dest="output_suppression", help="Optional description of stdout/stderr or report evidence suppressed by the hook.")
    meta_feedback.add_argument("--partial-execution-risk", dest="partial_execution_risk", help="Optional description of whether work may have executed before hook output was stopped.")
    meta_feedback.add_argument("--suggested-policy-change", dest="suggested_policy_change", help="Optional bounded hook or route behavior improvement proposal.")
    meta_feedback.add_argument("--roadmap-item", dest="roadmap_item", help="Compatibility alias for an explicit canonical cluster id; meta-feedback no longer writes roadmap items.")
    meta_feedback.add_argument("--dedupe-to", dest="dedupe_to", help="Append this observation to an existing canonical cluster id instead of the topic slug.")
    meta_feedback.add_argument(
        "--correction-of",
        dest="correction_of",
        help=(
            "Append a correction marker to an existing canonical cluster without increasing occurrence_count. "
            "Use 'latest' or a compact observation/hash id."
        ),
    )
    meta_feedback.add_argument("--order", type=int, help="Compatibility no-op; accepted for old callers but ignored because meta-feedback no longer writes roadmap placement.")
    preflight = subparsers.add_parser(
        "preflight",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: run optional preflight warnings or print an opt-in warning hook template.",
    )
    preflight.add_argument(
        "--template",
        choices=("git-pre-commit",),
        help="Print a warning-only local Git pre-commit hook template to stdout without installing it.",
    )
    preflight.add_argument("--orchestrator-workspace", dest="orchestrator_workspace", help="Read-only disposable workspace preflight for external orchestrator launches.")
    preflight.add_argument("--product-root", dest="product_root", help="Optional configured product source root used by --orchestrator-workspace live-root exclusion checks.")
    hooks = subparsers.add_parser(
        "hooks",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: inspect, install, or run warning-only MyLittleHarness hook shims.",
    )
    hooks_mode = hooks.add_mutually_exclusive_group(required=True)
    hooks_mode.add_argument("--doctor", action="store_true", help="Inspect hook posture and supported events without writing files.")
    hooks_mode.add_argument("--dry-run", action="store_true", help="Preview explicit hook shim installation without writing files.")
    hooks_mode.add_argument("--apply", action="store_true", help="Install the selected warning-only hook shim after dry-run review.")
    hooks_mode.add_argument(
        "--run",
        choices=("git-pre-commit", "agent-status", "session-start", "user-prompt-submit", "pre-tool-use", "post-tool-use", "stop"),
        help="Run one hook event as a foreground read-only adapter.",
    )
    hooks.add_argument("--json", action="store_true", help="Emit a structured hook event payload with --run.")
    hooks.add_argument("--input-file", dest="input_file", help="Read native hook JSON/text input from a UTF-8 file, or '-' for stdin; valid with --run.")
    hooks.add_argument("--hook", choices=("git-pre-commit",), default="git-pre-commit", help="Hook shim to install. Defaults to git-pre-commit.")
    hooks.add_argument("--adapter", action="store_true", help="Manage a native client hook adapter; compatible with dry-run/apply.")
    hooks.add_argument("--client", choices=("codex", "claude-code", "github-copilot"), help="Native hook client to configure with --adapter.")
    hooks.add_argument("--scope", choices=("project",), default="project", help="Native hook adapter scope. Only project scope is implemented.")
    hooks.add_argument("--config-path", dest="config_path", help="Optional root-relative or absolute project-local hook config path for adapter tests; must stay inside --root.")
    hooks.add_argument("--force", action="store_true", help="Replace an existing non-MLH hook only after explicit review.")
    hooks.add_argument("hook_args", nargs=argparse.REMAINDER, help="Optional raw hook arguments after --run.")
    tasks = subparsers.add_parser(
        "tasks",
        help=argparse.SUPPRESS,
        description="Advanced compatibility diagnostic: inspect operator task groups without writing files.",
    )
    tasks_mode = tasks.add_mutually_exclusive_group(required=True)
    tasks_mode.add_argument("--inspect", action="store_true", help="Inspect read-only operator task groups, compatibility posture, boundaries, and gated future lanes.")
    bootstrap = subparsers.add_parser(
        "bootstrap",
        help=argparse.SUPPRESS,
        description="Advanced compatibility diagnostic: inspect bootstrap, publishing, package, and workstation readiness without writing files.",
    )
    bootstrap_mode = bootstrap.add_mutually_exclusive_group(required=True)
    bootstrap_mode.add_argument("--inspect", action="store_true", help="Inspect read-only bootstrap readiness lanes and deferred mutation boundaries.")
    bootstrap_mode.add_argument("--package-smoke", action="store_true", help="Run local package install/import/console-script smoke verification in temporary locations.")
    semantic = subparsers.add_parser(
        "semantic",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: inspect or evaluate semantic retrieval readiness without writing files.",
    )
    semantic_mode = semantic.add_mutually_exclusive_group(required=True)
    semantic_mode.add_argument("--inspect", action="store_true", help="Inspect semantic readiness, search base posture, runtime deferral, and boundaries.")
    semantic_mode.add_argument("--evaluate", action="store_true", help="Run a fixed read-only semantic evaluation over the source-verified SQLite FTS/BM25 index.")
    intelligence = subparsers.add_parser(
        "intelligence",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: report repo intelligence over inventory-discovered surfaces and refresh disposable navigation cache when path/full-text search needs it.",
    )
    intelligence.add_argument("--query", help="Unified recovery query expanded into omitted exact, path, and full-text search modes.")
    intelligence.add_argument("--search", help="Case-sensitive literal text to search in inventory-discovered surface contents.")
    intelligence.add_argument("--path", help="Case-sensitive path fragment to search in inventory-discovered paths and references.")
    intelligence.add_argument("--full-text", help="Optional SQLite FTS/BM25 query over a current source-verified projection index.")
    intelligence.add_argument("--limit", type=_positive_int, default=10, help="Maximum full-text results to show. Defaults to 10.")
    intelligence.add_argument("--focus", choices=("search", "warnings", "projection", "routes"), help="Render a focused intelligence report while keeping the command read-only.")
    projection = subparsers.add_parser(
        "projection",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: build, inspect, delete, or rebuild disposable projection artifacts.",
    )
    projection_mode = projection.add_mutually_exclusive_group(required=True)
    projection_mode.add_argument("--build", action="store_true", help="Write rebuildable projection JSON artifacts inside the owned boundary.")
    projection_mode.add_argument("--inspect", action="store_true", help="Inspect generated projection artifacts without writing files.")
    projection_mode.add_argument("--delete", action="store_true", help="Delete only generated projection artifacts inside the owned boundary.")
    projection_mode.add_argument("--rebuild", action="store_true", help="Delete and rebuild generated projection artifacts inside the owned boundary.")
    projection_mode.add_argument("--warm-cache", action="store_true", help="Run one optional generated-cache watcher tick without installing a daemon.")
    projection.add_argument("--target", choices=("artifacts", "index", "all"), default="artifacts", help="Generated projection target to manage. Defaults to artifacts.")
    projection.add_argument(
        "--quiet-period-seconds",
        type=_nonnegative_float,
        default=0.0,
        help="With --warm-cache, defer refresh until dirty markers have been quiet for this many seconds.",
    )
    snapshot = subparsers.add_parser(
        "snapshot",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: inspect repair snapshots without writing files.",
    )
    snapshot_mode = snapshot.add_mutually_exclusive_group(required=True)
    snapshot_mode.add_argument("--inspect", action="store_true", help="Inspect repair snapshot metadata, copied files, hashes, and rollback posture.")
    adapter = subparsers.add_parser(
        "adapter",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: inspect or serve optional adapter projections without writing files.",
    )
    adapter_mode = adapter.add_mutually_exclusive_group(required=True)
    adapter_mode.add_argument("--inspect", action="store_true", help="Inspect the selected adapter projection without installing or running an adapter.")
    adapter_mode.add_argument("--serve", action="store_true", help="Serve the selected adapter projection as a foreground MCP stdio JSON-RPC server.")
    adapter_mode.add_argument("--client-config", action="store_true", help="Print no-write MCP client configuration for the selected adapter projection.")
    adapter_mode.add_argument("--install-client-config", action="store_true", help="Review or apply an idempotent Codex MCP client config merge.")
    adapter.add_argument(
        "--target",
        choices=(MCP_READ_PROJECTION_TARGET, APPROVAL_RELAY_TARGET),
        default=MCP_READ_PROJECTION_TARGET,
        help="Adapter projection target to inspect. Defaults to mcp-read-projection.",
    )
    adapter.add_argument("--transport", choices=("stdio",), help="Adapter serving transport. Required with --serve; only stdio is supported.")
    adapter.add_argument("--dry-run", action="store_true", help="Preview adapter client config installation without writing workstation files.")
    adapter.add_argument("--apply", action="store_true", help="Apply a reviewed adapter client config installation.")
    adapter.add_argument("--config-path", dest="config_path", help="Override the Codex config path for client-config inspection or install tests.")
    adapter.add_argument("--approval-packet-ref", dest="approval_packet_refs", action="append", default=[], help="Root-relative approval packet JSON reference for approval-relay inspect reports. May be repeated.")
    adapter.add_argument("--relay-channel", dest="relay_channel", default="manual", help="Approval relay channel label. No delivery transport is opened.")
    adapter.add_argument("--relay-recipient", dest="relay_recipient", default="", help="Optional approval relay recipient label. No secrets or delivery state are stored.")
    attach = subparsers.add_parser(
        "attach",
        help=argparse.SUPPRESS,
        description="Compatibility command: preview or apply workflow scaffold attachment.",
    )
    attach_mode = attach.add_mutually_exclusive_group(required=True)
    attach_mode.add_argument("--dry-run", action="store_true", help="Report the attach proposal without writing files.")
    attach_mode.add_argument("--apply", action="store_true", help="Create only allowed missing scaffold/template paths.")
    attach.add_argument("--project", help="Project name to use when creating project/project-state.md.")
    _hide_suppressed_top_level_commands(subparsers)
    return parser
