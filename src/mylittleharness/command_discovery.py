from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .models import Finding


RAILS_NOT_COGNITION_BOUNDARY = (
    "rails-not-cognition boundary: MLH reports route, validation, scaffold, provenance, comparison, "
    "retrieval, and evidence candidates only; source files and explicit operator or human-reviewed "
    "lifecycle decisions remain authority."
)
CYRILLIC_INTENT_TERMS: tuple[tuple[str, str], ...] = (
    ("исследован", " research "),
    ("ресерч", " research "),
    ("ресёрч", " research "),
    ("промпт", " prompt "),
    ("подсказ", " prompt "),
    ("пакет", " packet "),
    ("глубок", " deep "),
    ("дип", " deep "),
    ("чатбот", " chatbot "),
    ("чат-бот", " chatbot "),
    ("человеческ", " human "),
    ("ревью", " review "),
    ("провер", " review "),
)
RETIRED_COMMAND_SURFACES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "mirror-product-files",
        ("mirror product files", "mirror product", "mirror files", "mirror rail", "mirror command", "mirror dry run", "mirror apply"),
        (
            "the cross-repository parity copy rail is retired; MyLittleHarness now operates directly "
            "against the explicit target repository, so start with `mylittleharness --root <root> check` "
            "or an accepted roadmap item instead of resurrecting mirror commands"
        ),
    ),
)


@dataclass(frozen=True)
class CommandIntent:
    intent_id: str
    summary: str
    aliases: tuple[str, ...]
    first_safe_command: str
    follow_up_commands: tuple[str, ...]
    root_posture: str
    boundary: str


COMMAND_INTENTS: tuple[CommandIntent, ...] = (
    CommandIntent(
        "start-pass",
        "Inspect current root posture through the dashboard-first navigation packet, authority cards, and next safe command before choosing a mutating rail.",
        (
            "start",
            "status",
            "check",
            "validate",
            "what next",
            "current posture",
            "root posture",
            "fuzzy mlh task",
            "where do i begin",
        ),
        "mylittleharness --root <root> dashboard --inspect",
        (
            "mylittleharness --root <root> intelligence --query \"<task-or-route-question>\"",
            "mylittleharness --root <root> adapter --client-config --target mcp-read-projection",
            "mylittleharness --root <root> check",
        ),
        "any readable MLH root",
        "read-only report only; authority cards are navigation guidance and do not repair, write files, close out, archive, stage, commit, or change lifecycle state",
    ),
    CommandIntent(
        "operator-audit-loop",
        "Run a broad read-only audit loop before choosing a fix, lifecycle route, or fix-candidate capture.",
        (
            "audit",
            "autonomous audit",
            "autonomous-audit",
            "autonomous swim",
            "free swim",
            "operator audit",
            "product steward",
            "product-steward",
            "broad audit",
            "drift audit",
            "route audit",
            "operator friction",
            "workflow friction audit",
        ),
        "mylittleharness --root <root> check",
        (
            "mylittleharness --root <root> intelligence --query \"<audit-topic-or-route-question>\"",
            "mylittleharness --root <root> check --focus hygiene",
            "mylittleharness --root <root> memory-hygiene --dry-run --scan",
            "mylittleharness --root <mlh-dev-root> meta-feedback --dry-run --from-root <observed-root> --topic \"<topic>\" --note \"<note>\"",
        ),
        "readable MLH root; use direct source reads for evidence, and use meta-feedback only for concrete MLH rough edges",
        "audit loop is read-only until an explicit dry-run/apply rail is chosen; it cannot repair, capture vague ideas, approve lifecycle movement, archive, roadmap promotion, staging, commit, push, or product mutation",
    ),
    CommandIntent(
        "product-local-test-command",
        "Surface the bounded local product-source test command without inventing a pytest/package fallback.",
        (
            "run product tests",
            "product tests",
            "local product tests",
            "test command",
            "safe test command",
            "verification command",
            "product verification command",
            "full test suite",
            "run tests",
            "unittest",
            "pytest unavailable",
            "uv run pytest",
            "build editable fails",
            "build_editable",
        ),
        "python -m unittest discover -s tests",
        (
            "python -m unittest tests.test_memory_hygiene tests.test_cli tests.test_package_metadata",
            "python -m mylittleharness check",
            "git diff --check",
        ),
        "MyLittleHarness product source checkout or another MLH source tree with a repo-visible tests/ directory",
        "local test commands are verification evidence only; suggest does not install dependencies, choose pytest, approve release, closeout, archive, roadmap movement, staging, commit, push, or lifecycle decisions",
    ),
    CommandIntent(
        "repair-preview",
        "Preview deterministic workflow contract repair before any apply.",
        ("repair", "fix missing scaffold", "contract repair", "repair before apply", "validation error"),
        "mylittleharness --root <root> repair --dry-run",
        ("mylittleharness --root <root> repair --apply",),
        "live operating root after check reports a repairable validation issue",
        "dry-run is advisory; apply remains explicit and bounded to deterministic repair classes",
    ),
    CommandIntent(
        "open-active-plan",
        "Open a deterministic active implementation plan from explicit or roadmap-derived title/objective/task input.",
        ("open plan", "create plan", "next plan", "implementation plan", "roadmap item", "plan apply"),
        "mylittleharness --root <root> plan --dry-run --roadmap-item <id> [--title \"<title>\"] [--objective \"<objective>\"]",
        ("mylittleharness --root <root> plan --apply --roadmap-item <id> [--title \"<title>\"] [--objective \"<objective>\"]",),
        "live operating root with no conflicting active plan unless --update-active is explicit",
        "plan output creates execution scaffolding only; it cannot approve closeout, archive, commit, rollback, or future mutations",
    ),
    CommandIntent(
        "scoped-interrupt-work",
        "Open or close a bounded hotfix/interrupt plan while preserving explicit return-to-roadmap and roadmap-status boundaries.",
        (
            "scoped interrupt",
            "scoped hotfix",
            "urgent bounded fix",
            "non-roadmap hotfix",
            "phase reopen",
            "quality fix",
            "scoped quality fix",
            "return to roadmap",
            "interrupt closeout",
        ),
        "mylittleharness --root <root> plan --dry-run --title \"Scoped hotfix: <title>\" --objective \"<bounded objective>\" --task \"<scope/evidence/return-to-roadmap>\"",
        (
            "mylittleharness --root <root> plan --apply --title \"Scoped hotfix: <title>\" --objective \"<bounded objective>\" --task \"<scope/evidence/return-to-roadmap>\"",
            "mylittleharness --root <root> writeback --dry-run --phase-status complete --docs-decision uncertain",
            "mylittleharness --root <root> writeback --dry-run --archive-active-plan --from-active-plan --docs-decision <updated|not-needed> --state-writeback \"<text>\" --verification \"<text>\" --commit-decision \"<text>\"",
        ),
        "live operating root with an urgent bounded fix whose scope and return-to-roadmap posture are explicit",
        "scoped interrupt plans still require dry-run/apply, verification, docs_decision, closeout/archive review, and explicit roadmap item/status fields before any roadmap status movement",
    ),
    CommandIntent(
        "advance-active-phase",
        "Advance an already open plan to the next explicit phase.",
        ("advance phase", "next phase", "phase pending", "phase complete", "active phase"),
        "mylittleharness --root <root> writeback --dry-run --active-phase <next-phase> --phase-status pending",
        ("mylittleharness --root <root> writeback --apply --active-phase <next-phase> --phase-status pending",),
        "live operating root with an active plan and explicit operator decision to continue",
        "phase advancement does not approve archive, roadmap done-status, next-plan opening, staging, commit, or push",
    ),
    CommandIntent(
        "closeout-fields",
        "Assemble closeout evidence and record explicit closeout facts.",
        ("closeout", "record closeout", "docs decision", "state transfer", "work result", "commit decision"),
        "mylittleharness --root <root> closeout",
        (
            "mylittleharness --root <root> writeback --dry-run --docs-decision <updated|not-needed|uncertain> --state-writeback \"<text>\" --verification \"<text>\" --commit-decision \"<text>\"",
            "mylittleharness --root <root> writeback --apply --docs-decision <updated|not-needed|uncertain> --state-writeback \"<text>\" --verification \"<text>\" --commit-decision \"<text>\"",
        ),
        "live operating root; product/source verification remains separate evidence",
        "closeout and writeback facts are lifecycle authority only after explicit apply; reports do not stage, commit, archive, or open next work",
    ),
    CommandIntent(
        "phase-closeout-handoff",
        "Split a completed phase handoff from archive closeout replacement so lifecycle pointers and closeout facts stay on their owning rails.",
        (
            "phase closeout handoff",
            "phase evidence handoff",
            "phase closeout writeback",
            "writeback mode handoff",
            "closeout archive sequence",
            "ready for closeout handoff",
            "archive closeout replacement",
        ),
        "mylittleharness --root <root> writeback --dry-run --phase-status complete --docs-decision uncertain",
        (
            "mylittleharness --root <root> writeback --apply --phase-status complete --docs-decision uncertain",
            "mylittleharness --root <root> writeback --dry-run --archive-active-plan --roadmap-item <id> --roadmap-status done --docs-decision <updated|not-needed> --state-writeback \"<text>\" --verification \"<text>\" --commit-decision \"<text>\"",
            "mylittleharness --root <root> writeback --apply --archive-active-plan --roadmap-item <id> --roadmap-status done --docs-decision <updated|not-needed> --state-writeback \"<text>\" --verification \"<text>\" --commit-decision \"<text>\"",
        ),
        "live operating root with a verified active phase that is ready for explicit closeout/archive review",
        "phase handoff keeps the active plan open; archive-active-plan owns lifecycle close pointers, so do not pass explicit --active-phase or --last-archived-plan to the archive command",
    ),
    CommandIntent(
        "archive-active-plan",
        "Archive a completed active plan through the bounded lifecycle write rail.",
        ("archive", "archive plan", "archive active plan", "completed plan", "mark roadmap done", "roadmap done"),
        "mylittleharness --root <root> writeback --dry-run --archive-active-plan --phase-status complete --from-active-plan --roadmap-item <id> --roadmap-status done",
        ("mylittleharness --root <root> writeback --apply --archive-active-plan --phase-status complete --from-active-plan --roadmap-item <id> --roadmap-status done",),
        "live operating root whose project-state phase_status is complete, or whose same reviewed writeback request supplies --phase-status complete",
        "archive-active-plan refuses uncompleted lifecycle state unless the same writeback request explicitly supplies --phase-status complete; it does not stage, commit, push, repair, or open the next plan",
    ),
    CommandIntent(
        "cancel-accidental-plan-activation",
        "Cancel an accidental active-plan activation without pretending it is closeout or archive.",
        ("cancel plan", "rollback activation", "accidental plan", "undo plan apply", "remove active plan", "plan cancel"),
        "mylittleharness --root <root> plan-cancel --dry-run --roadmap-item <id>",
        ("mylittleharness --root <root> plan-cancel --apply --roadmap-item <id> --source-hash <sha256-from-dry-run>",),
        "live operating root with plan_status active after an activation that should be cancelled rather than closed out",
        "plan-cancel only clears active lifecycle pointers, removes or keeps the active plan by explicit flag, and can restore one roadmap item to accepted; it cannot approve closeout, archive, repair, staging, commit, rollback of source edits, or next-plan opening",
    ),
    CommandIntent(
        "reviewed-transition",
        "Review a composed phase-completion/archive/next-plan transition with a token.",
        ("transition", "close archive next", "review token", "archive and open next", "complete current phase"),
        "mylittleharness --root <root> transition --dry-run --complete-current-phase --archive-active-plan --current-roadmap-item <id> --current-roadmap-status done [--next-roadmap-item <id>]",
        ("mylittleharness --root <root> transition --apply --review-token <token> <same reviewed flags>",),
        "live operating root with an explicit lifecycle transition request",
        "transition apply requires the matching dry-run token and delegates only to bounded writeback/plan rails",
    ),
    CommandIntent(
        "inspect-context-surface-budget",
        "Inspect primary instruction-surface size warnings without state compaction.",
        (
            "readme large warning",
            "README large warning",
            "primary instruction surface",
            "instruction surface large",
            "context surface large",
            "rule context surface large",
            "explain readme warning",
        ),
        "mylittleharness --root <root> check --focus context",
        ("mylittleharness --root <root> context-budget",),
        "live operating root after check reports rule-context-surface-large for README.md, AGENTS.md, or another primary instruction surface",
        "context inspection is read-only; it does not compact project-state, edit README, repair, close out, archive, stage, commit, or change lifecycle state",
    ),
    CommandIntent(
        "compact-project-state",
        "Compact oversized project-state history through the whole-state compaction rail.",
        ("compact", "compact state", "state too large", "project state oversized", "compact-only"),
        "mylittleharness --root <root> writeback --dry-run --compact-only",
        ("mylittleharness --root <root> writeback --apply --compact-only --source-hash <sha256-from-dry-run>",),
        "live operating root after check reports oversized project/project-state.md",
        "compact-only scans the whole state and source-hash guards apply; it cannot approve repair, closeout, archive, roadmap changes, staging, commit, or push",
    ),
    CommandIntent(
        "memory-hygiene-cleanup-review",
        "Review memory-hygiene scan output, cleanup candidate ids, archive targets, link repairs, and per-source archive commands before any apply.",
        (
            "memory hygiene",
            "memory-hygiene",
            "memory hygiene scan",
            "memory hygiene batch",
            "memory hygiene batch preview",
            "bulk archive token",
            "cleanup advisor",
            "archive candidate",
            "entry coverage",
            "status only covered incubation",
        ),
        "mylittleharness --root <root> memory-hygiene --dry-run --scan",
        (
            "mylittleharness --root <root> memory-hygiene --apply --scan --proposal-token <mhb-token-from-dry-run-scan>",
            "mylittleharness --root <root> memory-hygiene --dry-run --source <project/plan-incubation/file.md> --status <implemented|archived|rejected|superseded> --archive-to <project/archive/reference/incubation/file.md> --repair-links",
            "mylittleharness --root <root> memory-hygiene --apply --source <project/plan-incubation/file.md> --status <implemented|archived|rejected|superseded> --archive-to <project/archive/reference/incubation/file.md> --repair-links",
        ),
        "live operating root after memory-hygiene scan reports cleanup candidates, blockers, or ambiguous incubation notes",
        "scan is read-only and may emit proposal ids/tokens; token-bound batch apply and per-source apply remain explicit, with no implicit bulk archive, roadmap mutation, closeout, staging, commit, or next-plan opening",
    ),
    CommandIntent(
        "verification-ledger-rotation",
        "Rotate a long-running verification ledger into archive/reference and seed a fresh continuity ledger.",
        (
            "verification ledger",
            "verification ledger rotation",
            "rotate ledger",
            "ledger rotation",
            "autonomous swim ledger",
            "fresh continuity ledger",
            "archive verification history",
        ),
        "mylittleharness --root <root> memory-hygiene --dry-run --rotate-ledger --source project/verification/autonomous-mlh-swim-ledger.md",
        (
            "mylittleharness --root <root> memory-hygiene --apply --rotate-ledger --source project/verification/autonomous-mlh-swim-ledger.md --source-hash <sha256-from-dry-run>",
            "mylittleharness --root <root> check",
        ),
        "live operating root with a regular Markdown ledger under project/verification/",
        "ledger rotation writes only the reviewed active ledger and deterministic archive/reference verification target; it cannot approve closeout, roadmap promotion, unrelated archive cleanup, staging, commit, push, rollback, or next-plan opening",
    ),
    CommandIntent(
        "metadata-status-review",
        "Inspect route metadata status, malformed fields, stale paths, and human-gated amendment posture.",
        (
            "metadata status",
            "route metadata status",
            "metadata-status",
            "status value",
            "route status value",
            "route-metadata",
            "metadata blocker",
        ),
        "mylittleharness --root <root> check --focus validation",
        (
            "mylittleharness --root <root> check --focus route-references",
            "mylittleharness --root <root> suggest --intent \"route reference recovery\"",
            "mylittleharness --root <root> plan --dry-run --roadmap-item <id>",
        ),
        "live operating root after check reports route-metadata-* or lifecycle status diagnostics",
        "metadata-status review is advisory; status changes require an explicit owning dry-run/apply route or human-authored edit and cannot approve lifecycle movement",
    ),
    CommandIntent(
        "docs-decision-closeout",
        "Resolve docs_decision evidence before confident closeout wording.",
        (
            "docs decision",
            "docs_decision",
            "docs-decision",
            "docs decision closeout",
            "uncertain docs decision",
            "docs closeout",
        ),
        "mylittleharness --root <root> closeout",
        (
            "mylittleharness --root <root> writeback --dry-run --docs-decision <updated|not-needed|uncertain> --state-writeback \"<text>\" --verification \"<text>\" --commit-decision \"<text>\"",
            "mylittleharness --root <root> writeback --apply --docs-decision <updated|not-needed|uncertain> --state-writeback \"<text>\" --verification \"<text>\" --commit-decision \"<text>\"",
        ),
        "live operating root with docs impact or closeout evidence to record",
        "docs_decision becomes closeout authority only through explicit writeback; uncertain keeps closeout wording provisional and does not approve archive or commit",
    ),
    CommandIntent(
        "report-blocker-handoff",
        "Stop and surface the next read-only diagnostic when blocker, unsafe root, missing source, or uncertain authority is reported.",
        (
            "blocker",
            "report blocker",
            "blocked report",
            "unsafe root",
            "failed verification",
            "missing source",
            "uncertain authority",
            "failed check",
        ),
        "mylittleharness --root <root> check",
        (
            "mylittleharness --root <root> suggest --intent \"<operator-action>\"",
            "mylittleharness --root <root> check --focus validation",
            "mylittleharness --root <root> check --focus route-references",
        ),
        "any readable MLH root after a report names blockers, refusal, missing source, unsafe root, or uncertain authority",
        "blocker handoff is read-only triage; stop before apply, closeout, archive, roadmap mutation, staging, commit, or push until the owning dry-run is explicit",
    ),
    CommandIntent(
        "capture-meta-feedback",
        "Capture an MLH rough edge as a source-bound fix candidate.",
        ("meta feedback", "fix candidate", "rough edge", "agent friction", "route discovery", "mlh debt"),
        "mylittleharness --root <mlh-dev-root> meta-feedback --dry-run --from-root <observed-root> --topic \"<topic>\" --note \"<note>\"",
        ("mylittleharness --root <mlh-dev-root> meta-feedback --apply --from-root <observed-root> --topic \"<topic>\" --note \"<note>\"",),
        "central MLH operating root for product debt; observed root is provenance only",
        "meta-feedback records operating memory only; roadmap promotion stays an explicit roadmap command and cannot approve release removal, lifecycle movement, archive, staging, commit, or next-plan opening",
    ),
    CommandIntent(
        "docs-route-recovery",
        "Review missing docs/spec route references before restoring, retargeting, or classifying documentation.",
        (
            "docs route recovery",
            "docs spec recovery",
            "docs specs recovery",
            "recover docs spec",
            "recover docs specs",
            "docs spec missing",
            "docs specs missing",
            "missing docs spec",
            "missing docs specs",
            "missing docs route",
            "docs specs missing intelligence warning",
            "missing docs specs intelligence warning",
            "docs specs missing link",
            "docs specs fan in",
            "docs specs backlink",
            "research prompt packets missing",
            "research prompt packets docs spec",
            "restore docs spec",
            "retarget docs spec",
            "missing product docs route",
        ),
            "mylittleharness --root <root> intelligence --query \"<missing-docs-route>\" --focus warnings",
        (
            "mylittleharness --root <root> audit-links",
            "mylittleharness --root <root> check --focus links",
            "mylittleharness --root <mlh-dev-root> meta-feedback --dry-run --from-root <observed-root> --topic \"<topic>\" --note \"<note>\"",
        ),
        "live operating root with missing docs/spec, backlink, fan-in, or intelligence warning evidence",
        "docs route recovery is read-only triage; restore, retarget, delete, or docs mutation decisions require explicit source review and cannot be inferred by suggest, promote roadmap state, move lifecycle, archive, stage, commit, or open a plan",
    ),
    CommandIntent(
        "research-route-recovery",
        "Review missing project/research provenance references before restoring, retargeting, or classifying research.",
        (
            "research route recovery",
            "research provenance recovery",
            "research provenance warning",
            "missing research route",
            "missing research provenance",
            "missing project research",
            "project research missing",
            "recover missing project research",
            "recover research distillate",
            "research distillate missing",
            "source research missing",
            "project research missing link",
        ),
        "mylittleharness --root <root> intelligence --query \"<missing-research-route>\" --focus warnings",
        (
            "mylittleharness --root <root> audit-links",
            "mylittleharness --root <root> check --focus links",
            "mylittleharness --root <root> memory-hygiene --dry-run --scan",
            "mylittleharness --root <root> research-import --dry-run --title \"<title>\" --text-file <reviewed-source.md> --target <project/research/file.md>",
            "mylittleharness --root <mlh-dev-root> meta-feedback --dry-run --from-root <observed-root> --topic \"<topic>\" --note \"<note>\"",
        ),
        "live operating root with missing project/research, source_research, distillate, or research provenance warning evidence",
        "research route recovery is read-only triage; restore, import, retarget, or classify research only after explicit source review and cannot be inferred by suggest, promote authority, move lifecycle, archive, stage, commit, or open a plan",
    ),
    CommandIntent(
        "recover-deep-research-rubric",
        "Recover a missing Deep Research comparison rubric through explicit research import and distill rails.",
        (
            "deep research rubric recovery",
            "deep research rubric missing",
            "rubric recovery",
            "rubric route gap",
            "harness deep research comparison rubric",
            "comparison rubric missing",
            "prompt rubric reference",
        ),
        "mylittleharness --root <root> check",
        (
            "mylittleharness --root <root> memory-hygiene --dry-run --scan",
            "mylittleharness --root <root> research-import --dry-run --title \"Deep Research Comparison Rubric\" --text-file <reviewed-rubric.md> --target project/research/harness-deep-research-comparison-rubric.md",
            "mylittleharness --root <root> research-distill --dry-run --source project/research/harness-deep-research-comparison-rubric.md",
        ),
        "live operating root with Deep Research rubric cues and no current research/reference rubric artifact",
        "recovery suggestions are read-only until explicit research-import or research-distill apply; they cannot import legacy files automatically, promote authority, move lifecycle state, archive, stage, commit, or open a plan",
    ),
    CommandIntent(
        "research-human-review-gate",
        "Pause implementation when a roadmap item declares human-review research markers.",
        (
            "deep research prompt",
            "research prompt",
            "needs deep research",
            "needs_deep_research",
            "requires reflection",
            "requires_reflection",
            "needs human review",
            "needs_human_review",
            "human review blocker",
            "prompt deep research",
            "deep research chatbot",
            "chatbot deep research prompt",
            "give me deep research prompts",
            "default deep research prompts",
            "дай промпты для глубокого исследования",
            "дай промпты на дип ресерч",
            "сделай промпт для дип ресерча",
            "сделай промпт на дип ресерч",
            "промпт для дип ресерча",
            "product access path",
            "product access",
        ),
        "mylittleharness --root <root> check",
        (
            "Draft the external Deep Research request manually outside MyLittleHarness",
            "mylittleharness --root <root> research-import --dry-run --title \"<title>\" --text-file <file>",
            "mylittleharness --root <root> research-distill --dry-run --source <project/research/file.md>",
            "mylittleharness --root <root> roadmap --dry-run --action update --item-id <id> --status blocked --carry-forward \"<review-needed>\"",
        ),
        "live operating root when research/reflection markers are present; prompt composition is external/manual",
        "MyLittleHarness does not draft Deep Research prompts, does not call an external model, import research, approve implementation, move lifecycle state, archive, stage, commit, or mutate roadmap status",
    ),
    CommandIntent(
        "recover-roadmap-source-incubation",
        "Recover or retarget missing roadmap source-incubation evidence before opening a roadmap-backed plan.",
        (
            "roadmap source incubation missing",
            "source incubation missing",
            "relationship writeback refused",
            "recover source incubation",
            "roadmap evidence missing",
            "missing roadmap source note",
        ),
        "mylittleharness --root <root> memory-hygiene --dry-run --scan",
        (
            "mylittleharness --root <root> incubate --dry-run --topic \"<topic>\" --note \"<note>\"",
            "mylittleharness --root <root> roadmap --dry-run --action update --item-id <id> --source-incubation <route>",
            "mylittleharness --root <root> plan --dry-run --roadmap-item <id>",
        ),
        "live operating root with accepted/active roadmap items that reference missing source_incubation evidence",
        "recovery advice is read-only until an explicit incubate or roadmap apply; it cannot approve plan opening, lifecycle movement, archive, staging, commit, or repair",
    ),
    CommandIntent(
        "route-reference-recovery",
        "Inspect missing route-reference classes and choose bounded recovery review commands.",
        (
            "route reference recovery",
            "route-reference recovery",
            "route reference recovery suggestions",
            "missing route references",
            "route references missing",
            "route-reference inventory recovery",
            "route reference next safe command",
        ),
        "mylittleharness --root <root> check --focus route-references",
        (
            "mylittleharness --root <root> check --focus archive-context",
            'mylittleharness --root <root> suggest --intent "roadmap source incubation missing"',
            "mylittleharness --root <root> projection --inspect --target all",
        ),
        "live operating root after route-reference inventory reports missing, stale, historical, or generated-cache references",
        "route-reference recovery advice is read-only until an explicit owning dry-run/apply rail is reviewed; it cannot repair, recreate archives, retarget metadata, change docs_decision, move lifecycle state, stage, commit, or open a plan",
    ),
    CommandIntent(
        "agent-navigation-reflex",
        "Use the budgeted agent-navigation reflex for fuzzy route, impact, lifecycle, or product-source questions.",
        (
            "agent navigation",
            "navigation reflex",
            "chutye reflex",
            "repo intelligence default",
            "MCP rg navigation",
            "route discovery reflex",
            "safe agent navigation",
            "event driven self check",
            "chat output policy",
        ),
        "mylittleharness --root <root> dashboard --inspect",
        (
            "mylittleharness --root <root> hooks --run session-start --json",
            "mylittleharness --root <root> hooks --run user-prompt-submit --json --input-file -",
            "mylittleharness --root <root> hooks --run pre-tool-use --json --input-file -",
            "mylittleharness --root <root> intelligence --query \"<topic-or-route-question>\"",
            "mylittleharness --root <root> intelligence --focus routes",
            "mylittleharness --root <root> adapter --client-config --target mcp-read-projection",
            "mylittleharness --root <root> suggest --intent \"<operator-action>\"",
        ),
        "readable MLH root; start with check when lifecycle posture is unknown, then verify exact paths or symbols with rg/direct file reads",
        "navigation reflexes are read-only budget guidance; they cannot replace source verification, approve lifecycle movement, archive, repair, stage, commit, or create hidden runtime state",
    ),
    CommandIntent(
        "inspect-mcp-read-projection-adapter",
        "Inspect the MCP read-projection adapter runtime and generated-input posture without starting a server.",
        (
            "inspect projection adapter",
            "inspect projection adapter runtime",
            "projection adapter runtime",
            "projection adapter provenance",
            "inspect adapter runtime",
            "adapter runtime provenance",
            "mcp read projection adapter",
            "mcp-read-projection adapter",
            "inspect mcp read projection",
            "read projection adapter inspect",
            "mcp projection runtime",
        ),
        "mylittleharness --root <root> adapter --inspect --target mcp-read-projection",
        (
            "mylittleharness --root <root> adapter --client-config --target mcp-read-projection",
            "mylittleharness --root <root> projection --inspect --target all",
        ),
        "readable MLH root when the operator needs adapter runtime/source/root provenance or generated-input posture",
        "adapter inspection is read-only helper evidence; it does not start MCP serving, refresh generated caches, install tooling, write config, approve lifecycle movement, archive, staging, commit, or repair",
    ),
    CommandIntent(
        "projection-cache-refresh",
        "Inspect or rebuild disposable projection artifacts and the SQLite index when navigation cache diagnostics are stale or dirty.",
        (
            "projection cache",
            "projection cache stale",
            "projection cache dirty",
            "generated projection cache",
            "projection artifact stale",
            "projection artifact dirty",
            "projection index stale",
            "projection index dirty",
            "sqlite projection index stale",
            "navigation cache refresh",
            "projection rebuild",
            "rebuild projection cache",
            "rebuild recommended",
            "warm cache",
        ),
        "mylittleharness --root <root> projection --inspect --target all",
        (
            "mylittleharness --root <root> projection --rebuild --target all",
            "mylittleharness --root <root> intelligence --focus search --query \"<topic>\"",
        ),
        "readable MLH root with missing, stale, dirty, corrupt, or degraded generated projection cache diagnostics",
        "projection cache commands affect only rebuildable generated output under .mylittleharness/generated/projection; repo-visible source files remain authority and cache refresh cannot approve repair, lifecycle movement, archive, roadmap changes, staging, commit, or product mutation",
    ),
    CommandIntent(
        "route-incoming-information",
        "Classify incoming text before writing operating memory.",
        ("intake", "route text", "incoming information", "docs impact", "research import", "decision record"),
        "mylittleharness --root <root> intake --dry-run --text \"<text>\"",
        ("mylittleharness --root <root> intake --apply --text \"<text>\" --target <route/file.md>",),
        "live operating root with explicit target for apply",
        "intake classification is advisory; apply writes one explicit route target and cannot promote roadmap, closeout, archive, commit, or repair",
    ),
    CommandIntent(
        "verification-evidence-record",
        "Preview a durable verification evidence note without direct route-file writes.",
        (
            "verification evidence",
            "durable proof",
            "durable proof record",
            "verification record",
            "proof evidence",
            "project verification note",
            "record verification artifact",
            "write verification evidence",
        ),
        "mylittleharness --root <root> intake --dry-run --text-file - --target project/verification/<evidence-id>.md",
        (
            "mylittleharness --root <root> intake --apply --text-file - --target project/verification/<evidence-id>.md",
            "mylittleharness --root <root> evidence --record --dry-run --record-id <id> --role verifier --status succeeded --task \"<task>\"",
        ),
        "live operating root when reusable verification proof is worth a repo-visible artifact",
        "verification evidence routes are evidence only; intake/evidence reports cannot approve closeout, archive, roadmap status, staging, commit, push, or lifecycle movement",
    ),
    CommandIntent(
        "incubate-future-idea",
        "Create or append a same-topic future-idea note.",
        ("incubate", "future idea", "follow-up note", "plan incubation", "note-file"),
        "mylittleharness --root <root> incubate --dry-run --topic \"<topic>\" --note \"<note>\"",
        ("mylittleharness --root <root> incubate --apply --topic \"<topic>\" --note \"<note>\"",),
        "live operating root",
        "incubation is operating memory only; it cannot approve roadmap promotion, plan opening, closeout, archive, staging, commit, or push",
    ),
    CommandIntent(
        "roadmap-acceptance-readiness",
        "Inspect roadmap acceptance readiness, blockers, stale evidence, and next safe commands before opening or promoting work.",
        (
            "roadmap readiness",
            "acceptance readiness",
            "readiness matrix",
            "roadmap blockers",
            "stale roadmap evidence",
            "next safe roadmap command",
            "what can be accepted",
        ),
        "mylittleharness --root <root> check",
        (
            "mylittleharness --root <root> roadmap --dry-run --action update --item-id <id> [fields]",
            "mylittleharness --root <root> plan --dry-run --roadmap-item <id>",
            "mylittleharness --root <root> suggest --intent \"metadata status\"",
        ),
        "live operating root with readable project/roadmap.md",
        "readiness output is advisory only; it cannot promote roadmap items, open plans, approve lifecycle movement, archive, stage, commit, or repair",
    ),
    CommandIntent(
        "update-roadmap-item",
        "Add or update one accepted-work roadmap item.",
        ("roadmap", "accepted work", "queue item", "roadmap update", "roadmap add"),
        "mylittleharness --root <root> roadmap --dry-run --action update --item-id <id> [fields]",
        ("mylittleharness --root <root> roadmap --apply --action update --item-id <id> [fields]",),
        "live operating root with readable project/roadmap.md",
        "roadmap output is sequencing evidence only; it cannot approve closeout, archive, commit, rollback, repair, or lifecycle decisions",
    ),
    CommandIntent(
        "record-agent-evidence",
        "Record one source-bound agent run evidence file after explicit review.",
        ("agent evidence", "record evidence", "agent run", "agent-run", "run evidence", "record agent run evidence", "verification record", "proof record"),
        "mylittleharness --root <root> evidence --record --dry-run --record-id <id> --role <role> --actor <actor> --task \"<task>\" --status <status> --stop-reason \"<reason>\" --attempt-budget <budget> --input-ref <rel> --output-ref <rel> --claimed-path <rel> --command \"<command>\"",
        ("mylittleharness --root <root> evidence --record --apply <same reviewed fields>",),
        "live operating root with explicit source-bound refs",
        "agent run evidence is proof input only; it cannot approve lifecycle transitions, archive, roadmap status, staging, commit, rollback, or next-plan opening",
    ),
    CommandIntent(
        "create-work-claim",
        "Create one repo-visible scoped work claim before starting potentially overlapping work.",
        (
            "create work claim",
            "work claim create",
            "claim before editing",
            "claim write scope",
            "claim path",
            "claim route",
            "claim resource",
            "reserve path",
            "reserve route",
            "coordinate write",
        ),
        "mylittleharness --root <root> claim --dry-run --action create --claim-id <id> --claim-kind <write|lifecycle|path|resource> --owner-role <role> --owner-actor <actor> --execution-slice <slice> --claimed-path <rel>",
        (
            "mylittleharness --root <root> claim --apply --action create <same reviewed fields>",
            "mylittleharness --root <root> check --focus agents",
            "mylittleharness --root <root> claim --status",
        ),
        "live operating root where scoped work coordination is useful before overlapping edits or fan-in",
        "work claims are coordination evidence only; create/release applies cannot approve fan-in, lifecycle transitions, archive, roadmap status, staging, commit, push, or release",
    ),
    CommandIntent(
        "work-claim-review",
        "Inspect or release repo-visible work claims after stale-claim, missing-run-evidence, or worker-residue findings.",
        (
            "work claim",
            "work-claim",
            "claim status",
            "claim cleanup",
            "stale claim",
            "release claim",
            "missing run evidence",
            "no progress residue",
            "worker residue",
            "abandoned worktree",
            "overlapping claims",
        ),
        "mylittleharness --root <root> check --focus agents",
        (
            "mylittleharness --root <root> claim --status",
            "mylittleharness --root <root> evidence --record --dry-run --record-id <id> --role <role> --actor <actor> --task \"<task>\" --status <status> --stop-reason \"<reason>\" --attempt-budget <budget> --input-ref <rel> --output-ref <rel> --claimed-path <rel> --command \"<command>\"",
            "mylittleharness --root <root> claim --dry-run --action release --claim-id <id> --release-condition \"<reviewed-condition>\"",
            "mylittleharness --root <root> claim --apply --action release --claim-id <id> --release-condition \"<reviewed-condition>\"",
        ),
        "live operating root with repo-visible work claim records or reconcile findings about claims/residue",
        "claim cleanup remains report-only until explicit claim release apply; it cannot delete worker outputs, approve fan-in, archive, move lifecycle state, stage, commit, or release product changes",
    ),
    CommandIntent(
        "create-handoff-packet",
        "Create one repo-visible worker handoff packet for scoped delegated work.",
        (
            "handoff packet",
            "create handoff packet",
            "worker handoff",
            "handoff to worker",
            "agent handoff packet",
            "scoped worker packet",
            "worker packet",
            "handoff evidence packet",
        ),
        "mylittleharness --root <root> handoff --dry-run --handoff-id <id> --worker-id <actor> --role-id <role> --execution-slice <slice> --allowed-route <route-id> --write-scope <rel> --stop-condition \"<condition>\" --required-output <field>",
        (
            "mylittleharness --root <root> handoff --apply <same reviewed fields>",
            "mylittleharness --root <root> review-token --operation-id <id> --route <route-id> --claim-ref <project/verification/work-claims/id.json> --evidence-ref <project/verification/agent-runs/id.md>",
            "mylittleharness --root <root> check --focus agents",
        ),
        "live operating root with an explicit worker, role, route, and write scope to hand off",
        "handoff packets are coordination evidence only; they do not spawn workers, grant apply authority, approve fan-in, move lifecycle state, archive, stage, commit, push, or release",
    ),
    CommandIntent(
        "approval-packet-review",
        "Review or create repo-visible human-gate approval packets without treating packet status as authority.",
        (
            "approval packet",
            "approval-packet",
            "pending approval",
            "pending approval packet",
            "approval packet pending review",
            "stale approval packet",
            "human gate packet",
            "approval relay",
        ),
        "mylittleharness --root <root> check --focus agents",
        (
            "mylittleharness --root <root> approval-packet --dry-run --approval-id <id> --requester <actor> --subject \"<subject>\" --requested-decision \"<decision>\" --gate-class <class> --input-ref <rel> --human-gate-condition \"<condition>\"",
            "mylittleharness --root <root> adapter --inspect --target approval-relay --approval-packet-ref <project/verification/approval-packets/id.json>",
        ),
        "live operating root with human-gate approval evidence to inspect or create",
        "approval packets are append-only human-gate evidence; supersede an existing packet with a new id plus the prior packet as --input-ref, and never treat packet status as lifecycle, archive, roadmap, Git, release, or relay-delivery approval",
    ),
    CommandIntent(
        "command-discovery",
        "Inspect this deterministic command intent registry.",
        ("suggest", "intent", "command discovery", "which command", "safe command", "command index"),
        "mylittleharness --root <root> suggest --intent \"<operator-action>\"",
        ("mylittleharness --root <root> suggest --list", "mylittleharness --root <root> suggest --intent \"<operator-action>\" --json"),
        "any readable MLH root",
        "suggest is read-only and never executes the commands it reports",
    ),
)


def command_intent_registry() -> tuple[CommandIntent, ...]:
    return COMMAND_INTENTS


def command_suggestions_for_intent(intent: str, limit: int = 3) -> tuple[CommandIntent, ...]:
    normalized = _normalize(intent)
    if not normalized:
        return ()
    if retired_command_surface_for_intent(intent):
        return ()

    scored: list[tuple[int, int, CommandIntent]] = []
    query_tokens = set(normalized.split())
    docs_route_recovery_context = _docs_route_recovery_context(normalized)
    research_route_recovery_context = _research_route_recovery_context(normalized)
    coordination_packet_context = _coordination_packet_context(normalized)
    for index, command_intent in enumerate(COMMAND_INTENTS):
        if docs_route_recovery_context and _docs_route_context_excludes_intent(normalized, command_intent.intent_id):
            continue
        if research_route_recovery_context and _research_route_context_excludes_intent(normalized, command_intent.intent_id):
            continue
        if coordination_packet_context and _coordination_context_excludes_intent(command_intent.intent_id):
            continue
        aliases = tuple(_normalize(alias) for alias in command_intent.aliases)
        searchable = " ".join((command_intent.intent_id.replace("-", " "), command_intent.summary, *aliases))
        searchable_normalized = _normalize(searchable)
        score = 0
        if normalized == _normalize(command_intent.intent_id):
            score += 100
        if normalized in aliases:
            score += 80
        score += sum(40 for alias in aliases if alias and alias in normalized)
        score += sum(25 for alias in aliases if alias and normalized in alias)
        score += len(query_tokens & set(searchable_normalized.split())) * 5
        if score:
            scored.append((score, -index, command_intent))

    scored.sort(reverse=True)
    if scored and scored[0][0] >= 80:
        minimum_score = max(25, scored[0][0] // 4)
        scored = [item for item in scored if item[0] >= minimum_score]
    return tuple(item[2] for item in scored[:limit])


def command_suggestion_findings(
    suggestions: tuple[CommandIntent, ...],
    *,
    intent: str | None,
    list_all: bool,
) -> list[Finding]:
    findings: list[Finding] = []
    retired = retired_command_surface_for_intent(intent or "")
    if retired:
        findings.append(
            Finding(
                "warn",
                "command-suggest-retired-surface",
                retired,
                route_id="unclassified",
            )
        )
        return findings
    if not suggestions:
        findings.append(
            Finding(
                "warn",
                "command-suggest-no-match",
                f"no deterministic command intent matched {intent!r}; use suggest --list or start with `mylittleharness --root <root> check`",
                route_id="unclassified",
            )
        )
    for suggestion in suggestions:
        code = "command-suggest-registry-entry" if list_all else "command-suggest-match"
        findings.append(
            Finding(
                "info",
                code,
                (
                    f"{suggestion.intent_id}: first_safe_command={suggestion.first_safe_command}; "
                    f"follow_up_commands={list(suggestion.follow_up_commands)}; "
                    f"root_posture={suggestion.root_posture}; boundary={suggestion.boundary}"
                ),
                route_id="unclassified",
            )
        )
    return findings


def retired_command_surface_for_intent(intent: str) -> str:
    normalized = _normalize(intent)
    if not normalized:
        return ""
    for surface_id, aliases, message in RETIRED_COMMAND_SURFACES:
        if surface_id.replace("-", " ") in normalized or any(alias in normalized for alias in aliases):
            return message
    return ""


def command_suggestion_boundary_findings() -> list[Finding]:
    return [
        rails_not_cognition_boundary_finding(),
        Finding(
            "info",
            "command-suggest-read-only",
            "suggest reports deterministic command advice only; deterministic command-route candidates only; it does not execute suggested commands, provide product advice, write files, approve repair, approve lifecycle movement, archive, stage, commit, push, or mutate workstation state",
            route_id="unclassified",
        )
    ]


def rails_not_cognition_boundary_finding(source: str | None = None, route_id: str | None = "unclassified") -> Finding:
    return Finding(
        "info",
        "rails-not-cognition-boundary",
        RAILS_NOT_COGNITION_BOUNDARY,
        source,
        route_id=route_id,
    )


def command_suggestions_to_dict(suggestions: tuple[CommandIntent, ...]) -> list[dict[str, object]]:
    return [asdict(suggestion) for suggestion in suggestions]


def _normalize(value: str) -> str:
    lowered = str(value or "").casefold().replace("_", " ").replace("-", " ")
    for source, replacement in CYRILLIC_INTENT_TERMS:
        lowered = lowered.replace(source, replacement)
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _docs_route_recovery_context(normalized: str) -> bool:
    docs_route_terms = ("docs specs", "docs spec", "stable spec", "product docs", "docs route")
    recovery_terms = (
        "missing",
        "recover",
        "recovery",
        "restore",
        "retarget",
        "warning",
        "fan in",
        "backlink",
        "link",
        "audit",
        "intelligence",
    )
    return any(term in normalized for term in docs_route_terms) and any(term in normalized for term in recovery_terms)


def _research_route_recovery_context(normalized: str) -> bool:
    research_route_terms = (
        "project research",
        "source research",
        "research route",
        "research provenance",
        "research distillate",
        "research artifact",
    )
    recovery_terms = (
        "missing",
        "recover",
        "recovery",
        "restore",
        "retarget",
        "warning",
        "link",
        "audit",
        "intelligence",
        "provenance",
    )
    return any(term in normalized for term in research_route_terms) and any(term in normalized for term in recovery_terms)


def _docs_route_context_excludes_intent(normalized: str, intent_id: str) -> bool:
    if intent_id in {"research-human-review-gate", "recover-deep-research-rubric"}:
        deep_research_specific = (
            "deep research",
            "needs deep research",
            "requires reflection",
            "needs human review",
            "human review",
            "rubric",
            "prompt composition",
            "draft prompt",
        )
        return not any(term in normalized for term in deep_research_specific)
    if intent_id == "recover-roadmap-source-incubation":
        roadmap_specific = ("roadmap", "source incubation", "source note", "relationship writeback")
        return not any(term in normalized for term in roadmap_specific)
    return False


def _research_route_context_excludes_intent(normalized: str, intent_id: str) -> bool:
    if intent_id == "docs-route-recovery":
        docs_specific = ("docs spec", "docs specs", "stable spec", "product docs", "docs route")
        return not any(term in normalized for term in docs_specific)
    if intent_id in {"research-human-review-gate", "recover-deep-research-rubric"}:
        deep_research_specific = (
            "deep research",
            "needs deep research",
            "requires reflection",
            "needs human review",
            "human review",
            "rubric",
            "prompt composition",
            "draft prompt",
        )
        return not any(term in normalized for term in deep_research_specific)
    if intent_id == "recover-roadmap-source-incubation":
        roadmap_specific = ("roadmap", "source incubation", "source note", "relationship writeback")
        return not any(term in normalized for term in roadmap_specific)
    return False


def _coordination_packet_context(normalized: str) -> bool:
    coordination_terms = (
        "handoff packet",
        "worker handoff",
        "handoff to worker",
        "agent handoff",
        "worker packet",
        "work claim create",
        "create work claim",
        "claim before",
        "claim write",
        "claim path",
        "claim route",
        "claim resource",
    )
    return any(term in normalized for term in coordination_terms)


def _coordination_context_excludes_intent(intent_id: str) -> bool:
    return intent_id in {
        "advance-active-phase",
        "archive-active-plan",
        "open-active-plan",
        "phase-closeout-handoff",
        "reviewed-transition",
    }
