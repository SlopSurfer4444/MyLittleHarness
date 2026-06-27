# MyLittleHarness External Audit Prep

Prepared: 2026-05-24

Durable source-grounded preparation artifact for an external independent audit of a MyLittleHarness product repository checkout.

This file is meant for a future ChatGPT Pro Agent without access to the chat that produced it.

## Scope Rules

- Audit only the product repository checkout.
- Do not inventory or analyze private development or operating roots, local workspace repos, runtime caches, generated local state, or sibling repositories.
- Product-file references to an operating root/dev root are product-model context only; do not follow those paths.
- Exclude meta-feedback as a standalone audit topic. Do not audit the meta-feedback route, capture flow, env routing, tests, docs, prompts, or developer-local feedback workflow as separate audit blocks. Incidental references may be noted only as excluded context.
- This artifact maps audit surfaces and questions; it is not a correctness verdict.

## Short System Map

MyLittleHarness is a Python CLI package and repo-native safety layer for AI-assisted software work. The product model is `MyLittleHarness product source -> target repository`. The product source contains reusable code, tests, product docs, package metadata, templates, and compatibility fixtures. A target repository is where live operating memory, project state, implementation plans, evidence, repair snapshots, and generated navigation caches may exist.

Core promises visible in `README.md`, `docs/architecture/product-architecture.md`, `docs/specs/*.md`, and source/tests:

- Repo-visible files are authority.
- CLI reports, generated projections, dashboards, hooks, MCP output, and semantic/search caches are advisory unless an explicit apply route writes repo-visible files.
- Mutating work is explicit, bounded, and generally guarded by dry-run/apply rails.
- Product-source fixtures are not live workflow memory.
- Repair snapshots are safety evidence and manual rollback aids, not approval to repair, rollback, close out, archive, or commit.
- Optional adapters, hooks, daemons, dashboard, dispatcher, and MCP surfaces must not own lifecycle authority.
- Top-level operator surface foregrounds `init`, `check`, `repair`, and `detach`; advanced/compatibility commands remain available by command-specific help.

Main layers:

- Contracts/docs: `AGENTS.md`, `README.md`, `docs/**`, `.agents/docmap.yaml`, `.mylittleharness/project-workflow.toml`, `project/project-state.md`, `project/specs/workflow/**`.
- CLI/parser/dispatch: `src/mylittleharness/cli.py`, `cli_parser.py`, `__main__.py`.
- Inventory/routing/validation: `inventory.py`, `routes.py`, `checks.py`, `product_hygiene_checks.py`, `route_reference_guards.py`, `lifecycle_metadata.py`.
- Lifecycle/write rails: `planning.py`, `writeback.py`, `roadmap.py`, `memory_hygiene.py`, `incubate.py`, `research_*`, `relationship_drift.py`.
- Evidence/coordination: `evidence.py`, `closeout.py`, `claims.py`, `handoff.py`, `approval_packets.py`, `review_tokens.py`, `reconcile.py`, `agent_roles.py`, `vcs.py`.
- Advisory/generated/adapters: `projection.py`, `projection_artifacts.py`, `projection_index.py`, `semantic.py`, `adapter.py`, `dashboard.py`, `daemon.py`, `hooks.py`, `preflight.py`, `command_discovery.py`, `tasks.py`, `bootstrap.py`.
- Foundation utilities: `atomic_files.py`, `models.py`, `parsing.py`, `reporting.py`, `context_memory.py`, `evidence_cues.py`, `grain.py`.
- Package/templates: `pyproject.toml`, `build_backend/mylittleharness_build.py`, `src/mylittleharness/templates/**`.
- Tests: `tests/test_cli.py` plus focused suites for inventory, projection, memory hygiene, packaging, planning, research, relationship drift, VCS, parser/parsing, and lifecycle focus.

## External Audit Priorities

P0 safety and authority boundaries:

- Product/target root boundary and root classification.
- File-first authority and memory model.
- CLI parser/dispatch and hidden write surfaces.
- Dry-run/apply mutation rails for init/attach/repair/detach/lifecycle/writeback.
- Repair snapshots, rollback, atomic writes, idempotency.
- Generated projection/search/adapters non-authority boundary.
- Evidence/coordination artifacts and review-token gates.
- Package/bootstrap/dependency gate.

P1 lifecycle, routing, and traceability:

- Inventory, route metadata, docmap, link/reference/drift diagnostics.
- Planning/writeback/closeout/docs_decision lifecycle.
- Roadmap and relationship drift.
- Research/intake/incubation/memory hygiene, excluding meta-feedback.
- Adapter, hook, dashboard, daemon, and external orchestrator boundaries.
- Documentation/spec traceability and test topology.

P2 readiness and future-risk areas:

- Command discovery, task map, reporting language, ceremony budget.
- Template/fixture parity.
- Semantic search readiness and future provider/dependency gates.
- Security, prompt-injection, secrets, path, and supply-chain boundaries.
- Deferred/non-goal governance.

## Audit Blocks

Each block gives: title; why it exists; files/modules/docs/tests; visible promises or invariants; audit questions; evidence commands/artifacts; requested auditor result format.

### 1. Product Source vs Target Operating Root Boundary

- Why: MLH safety depends on never treating product source fixtures as live operating memory.
- Surfaces: `AGENTS.md`; `README.md`; `.agents/docmap.yaml`; `.mylittleharness/project-workflow.toml`; `project/project-state.md`; `docs/specs/product-boundary.md`; `docs/specs/operating-root.md`; `inventory.py`; `product_hygiene_checks.py`; `bootstrap.py`; `tests/test_inventory.py`; `tests/test_package_metadata.py`; `tests/test_cli.py`.
- Invariants: product source holds reusable code/docs/tests/package metadata/templates/compat fixtures only; live memory belongs to explicit target roots; product-source fixtures refuse unsafe mutation; product root should not hold active plans, archives, research corpora, reports, caches, local DBs, repair snapshots, package artifacts, or generated validation artifacts.
- Questions: Can root classification be spoofed by partial fixtures, symlinks, malformed state, or stale docmap? Do all mutating commands refuse product-source fixtures? Are product hygiene warnings complete and non-destructive?
- Evidence: `status`; `check`; `bootstrap --inspect`; `manifest --inspect --json`; temp-root refusal scenarios; `python -m unittest tests.test_inventory tests.test_package_metadata`.
- Result: severity table with scenario, command, expected/observed behavior, source refs, reproduction, and boundary-confidence rating.

### 2. File-First Authority and Memory Model

- Why: MLH's central contract is that repo-visible files are authority and generated/advisory outputs are not.
- Surfaces: `docs/specs/authority-and-memory.md`; `metadata-routing-and-evidence.md`; `context-and-ceremony-budget.md`; `routes.py`; `lifecycle_metadata.py`; `context_memory.py`; `checks.py`; `inventory.py`; `tests/test_inventory.py`; `tests/test_cli.py`; `tests/test_lifecycle_focus.py`.
- Invariants: `project/project-state.md` is durable current memory in live roots; `project/implementation-plan.md` matters only when `plan_status = active`; generated/adaptor/report outputs cannot approve lifecycle decisions; route metadata assists routing but cannot replace meaningful Markdown.
- Questions: Are route authority levels enforced in code? Can generated output be mistaken for authority? Are active phase and docs_decision validations consistent? Are fallback/prose-state paths safe?
- Evidence: `manifest --inspect --json`; `validate`; `context-budget`; source review of `routes.py`, `checks.py`, `inventory.py`; focused tests.
- Result: route authority matrix with source of truth, mutability, writer, refusal conditions, tests, and authority-leak risks.

### 3. CLI Command Surface, Parser, and Dispatch

- Why: Parser/dispatch consistency is the front door for safety rails.
- Surfaces: `README.md`; `docs/specs/attach-repair-status-cli.md`; `cli.py`; `cli_parser.py`; `__main__.py`; `tasks.py`; `command_discovery.py`; `tests/test_cli.py`; `tests/test_cli_parser.py`; `tests/test_package_metadata.py`.
- Invariants: top-level help foregrounds `init`, `check`, `repair`, `detach`; advanced commands remain available; mutating commands require explicit rails; warnings/errors/exit codes distinguish advisory findings from refusal.
- Questions: Do parser constraints match dispatch constraints? Are hidden writes possible without dry-run/apply? Do compatibility commands preserve primary command boundaries? Does JSON output preserve non-authority wording?
- Evidence: `python -m mylittleharness --help`; `tasks --inspect`; `manifest --inspect --json`; parser/dispatch source walk; `python -m unittest tests.test_cli_parser tests.test_cli`.
- Result: command inventory table with visibility, read/write class, dry-run/apply requirement, root eligibility, exit-code contract, tests, gaps.

### 4. Init/Attach/Repair/Detach Rails

- Why: These are the main target-root entry/recovery/disable rails.
- Surfaces: `README.md`; `docs/specs/attach-repair-status-cli.md`; `operating-root.md`; `product-boundary.md`; `cli.py`; `cli_parser.py`; `checks.py`; `inventory.py`; `templates/**`; `tests/test_cli.py`; `tests/test_inventory.py`.
- Invariants: dry-run writes nothing; init/attach apply are create-only for eligible live roots; repair apply is bounded and fail-closed; detach apply only creates a marker in eligible live roots and preserves authority files/generated projection.
- Questions: Are write plans root-confined? Are create-only guarantees real with partial files, path conflicts, and symlinks? Is dry-run faithful to apply? Does detach ever imply cleanup or authority removal?
- Evidence: temp roots for live/product/fallback/generated/ambiguous/symlink cases; `init --dry-run`; `repair --dry-run`; `detach --dry-run`; targeted tests.
- Result: scenario matrix with before tree, command, expected writes, actual writes, exit code, source/test refs.

### 5. Repair Snapshot, Rollback, and Atomic Writes

- Why: Existing-content repair must be recoverable and path-safe.
- Surfaces: `docs/specs/operating-root.md`; `attach-repair-status-cli.md`; `metadata-routing-and-evidence.md`; `atomic_files.py`; `checks.py`; `cli.py`; `reporting.py`; `tests/test_cli.py`; `tests/test_memory_hygiene.py`.
- Invariants: snapshots live under `.mylittleharness/snapshots/repair/` in explicit live roots; snapshots are evidence, not approval; atomic file transactions validate unique target/backup/tmp paths and attempt rollback on failure; product-source fixtures refuse snapshots.
- Questions: Are snapshots sufficient for manual recovery? Can paths escape root confinement? Does rollback restore previous content after partial failure? Is wording clear that snapshots do not approve rollback/cleanup?
- Evidence: `repair --dry-run`; `repair --apply`; `snapshot --inspect`; failure injection around `apply_file_transaction`; tests.
- Result: failure-mode table with trigger, expected protection, observed protection, residual manual recovery, tests/gaps.

### 6. Inventory, Route Metadata, Docmap, Link, and Drift Diagnostics

- Why: Agents need source-grounded navigation and drift detection without diagnostics becoming authority.
- Surfaces: `.agents/docmap.yaml`; `docs/specs/metadata-routing-and-evidence.md`; `authority-and-memory.md`; `inventory.py`; `checks.py`; `routes.py`; `route_reference_guards.py`; `relationship_drift.py`; `tests/test_inventory.py`; `tests/test_relationship_drift.py`; `tests/test_cli.py`.
- Invariants: docmap is advisory routing metadata; route metadata must validate; `audit-links` includes product docs; drift diagnostics report inconsistencies and do not mutate without explicit routes.
- Questions: Are docmap rules specific enough? Are broken/stale route refs detected across state/plans/roadmap/research/incubation/archive/docs? Are warnings actionable and non-authorizing?
- Evidence: `audit-links`; `check --focus route-references`; `relationship-drift --dry-run`; inventory and relationship tests.
- Result: diagnostic coverage map by ref type, source pattern, command coverage, false-positive/false-negative risk.

### 7. Generated Projection, SQLite, Search, and Semantic Surfaces

- Why: Generated projections and SQLite FTS accelerate navigation but must stay rebuildable and non-authoritative.
- Surfaces: `docs/specs/generated-state-and-projections.md`; `generated-state-search-and-sqlite.md`; `projection.py`; `projection_artifacts.py`; `projection_index.py`; `semantic.py`; `adapter.py`; `command_discovery.py`; `tests/test_projection*.py`; `tests/test_cli.py`.
- Invariants: owned generated path is `.mylittleharness/generated/projection/`; JSON artifacts exclude source bodies; SQLite can store indexed source text only as generated cache; stale/corrupt/root-mismatched/FTS-unavailable modes degrade safely; semantic inspect/evaluate do not call providers or create vector stores.
- Questions: Are source hashes/root identity enough? Can artifacts leak source bodies or authority fields? Are refreshes scoped to owned paths? Does search preserve source verification?
- Evidence: `projection --inspect --target all`; `projection --build --target all`; `intelligence --query authority`; `semantic --inspect`; `semantic --evaluate`; projection/index tests.
- Result: cache-safety report per artifact with stored data class, freshness check, deletion/rebuild story, authority leakage risk.

### 8. MCP Adapter, Approval Relay, Dashboard, Hooks, Preflight, and Daemon Boundary

- Why: Optional accelerators help agents but must not own correctness or lifecycle authority.
- Surfaces: `docs/specs/adapter-boundary.md`; `mcp-ecosystem-adoption-gate.md`; `adapter.py`; `dashboard.py`; `hooks.py`; `preflight.py`; `daemon.py`; `approval_packets.py`; `tests/test_cli.py`; `tests/test_package_metadata.py`.
- Invariants: MCP read projection is optional/read-only/source-bound; adapter config rails are explicit; hooks/preflight are warnings/readiness surfaces; `mlhd` runtime cache is disposable and disabled unless explicitly run.
- Questions: Can adapter outputs include source bodies contrary to contract? Are rootless/root-selected MCP modes safe? Can hooks/preflight become hidden approval? Are daemon actions gated and scoped?
- Evidence: `adapter --inspect --target mcp-read-projection`; `adapter --client-config --target mcp-read-projection`; `preflight`; `hooks doctor`; `dashboard --inspect`; `mlhd status`; tests.
- Result: adapter boundary table with exposed data, possible writes, authority wording, root-selection risks, tests/gaps.

### 9. Lifecycle Planning, Active Phase, Transition, and Plan Cancel

- Why: MLH supports bounded active plans and phase transitions without making plans mandatory.
- Surfaces: `docs/specs/context-and-ceremony-budget.md`; `authority-and-memory.md`; `project/specs/workflow/workflow-plan-synthesis-spec.md`; `planning.py`; `lifecycle_focus.py`; `writeback.py`; `cli.py`; `tests/test_planning.py`; `tests/test_lifecycle_focus.py`; `tests/test_cli.py`.
- Invariants: implementation plan is read only when active or requested; `active_phase` and `phase_status` are first-class; plans require docs_decision handling and current-phase evidence discipline; cancel/transition use explicit rails.
- Questions: Do state and plan frontmatter stay synchronized? Can prose override first-class metadata? Are transition/cancel protected from accidental archive/lifecycle changes? Is docs_decision enforced before confident closeout?
- Evidence: temp-root `plan --dry-run`; `transition --dry-run`; `plan-cancel --dry-run`; planning/lifecycle tests.
- Result: lifecycle-state transition graph with inputs, writes, refusals, and evidence requirements.

### 10. Writeback, Closeout, Docs Decision, Archive, and VCS Evidence

- Why: Closeout/writeback record durable results while Git actions remain manual/advisory.
- Surfaces: `docs/specs/context-and-ceremony-budget.md`; `metadata-routing-and-evidence.md`; `project/specs/workflow/workflow-verification-and-closeout-spec.md`; `writeback.py`; `closeout.py`; `evidence_cues.py`; `vcs.py`; `reporting.py`; `tests/test_cli.py`; `tests/test_planning.py`; `tests/test_vcs.py`.
- Invariants: `docs_decision` is `updated`, `not-needed`, or `uncertain`; `uncertain` keeps closeout provisional; `closeout` is read-only and may suggest Git trailers only; `writeback` is explicit lifecycle write rail; generated evidence manifests are rejected as default durable history.
- Questions: Are closeout fields source-bound? Are generic/fabricated evidence cues rejected? Are docs_decision values synchronized without clobbering content? Do archive operations preserve identity/source hash/lifecycle posture? Do dirty/non-git worktrees affect trailer suggestions safely?
- Evidence: `evidence`; `closeout`; `writeback --dry-run`; VCS and writeback tests.
- Result: closeout safety checklist with pass/fail/uncertain, source refs, and reproduction for false acceptance.

### 11. Roadmap, Relationship Graph, Accepted Work, and Drift

- Why: Roadmap is optional sequencing between incubation and one active plan; relationship metadata supports traceability.
- Surfaces: `docs/specs/metadata-routing-and-evidence.md`; `roadmap.py`; `roadmap_semantics.py`; `relationship_drift.py`; `routes.py`; `writeback.py`; `tests/test_cli.py`; `tests/test_relationship_drift.py`; `tests/test_memory_hygiene.py`.
- Invariants: roadmap is sequencing advisory unless explicit route/action gives authority; dependency/supersession/subsumed links should be inspectable; drift should be visible before confident closeout.
- Questions: Are roadmap status changes evidence-gated? Are relationships validated both ways? Can metadata drift without detection? Are roadmap writebacks atomic/root-confined?
- Evidence: `roadmap normalize --dry-run`; `relationship-drift --dry-run`; roadmap/writeback/memory-hygiene tests.
- Result: relationship matrix with node type, edge type, writer, validator, drift detector, repair/writeback path, gaps.

### 12. Research, Intake, Incubation, and Memory Hygiene

- Why: MLH separates raw intake, research, incubation, promotion, archival coverage, and cleanup from authoritative state.
- Surfaces: `docs/specs/authority-and-memory.md`; `metadata-routing-and-evidence.md`; `research_intake.py`; `research_distill.py`; `research_compare.py`; `research_recovery.py`; `incubate.py`; `memory_hygiene.py`; `tests/test_research_*.py`; `tests/test_memory_hygiene.py`; `tests/test_cli.py`.
- Invariants: intake/research/incubation remain non-authority until promoted; memory hygiene archives/repairs links/scans only through explicit rails; product-source fixtures refuse live memory mutation; source hashes/archive coverage guard loss of current authority.
- Questions: Do import/distill/compare preserve provenance and uncertainty? Are promotion/archive steps explicit and reversible enough? Can hygiene over-archive current authority or miss uncovered refs?
- Evidence: temp-root `intake --dry-run`; `research-import --dry-run`; `research-distill --dry-run`; `research-compare --dry-run`; `incubate --dry-run`; `memory-hygiene --dry-run`; focused tests.
- Result: provenance/promotion report with source lane, target lane, authority before/after, source hash, archive/link behavior, risk.

### 13. Evidence Records, Work Claims, Handoffs, Approval Packets, Review Tokens, and Reconcile

- Why: Coordination primitives support multi-agent/staged work without becoming automatic approval.
- Surfaces: `docs/specs/authority-and-memory.md`; `metadata-routing-and-evidence.md`; `evidence.py`; `claims.py`; `handoff.py`; `approval_packets.py`; `review_tokens.py`; `reconcile.py`; `agent_roles.py`; `tests/test_cli.py`; `tests/test_package_metadata.py`.
- Invariants: agent-run evidence is source-bound; work claims are scoped/leased repo-visible JSON; handoffs/approval packets/review tokens/reconcile do not approve lifecycle by themselves; role profiles are advisory.
- Questions: Are claims race-safe enough? Are stale/expired/overlapping claims detected? Are token hashes/receipts replay-resistant? Do role profiles accidentally encode authority?
- Evidence: `evidence --record --dry-run`; `claim --dry-run`; `handoff --dry-run`; `approval-packet --dry-run`; `review-token`; `reconcile`; tests.
- Result: coordination security review with artifact, trust boundary, replay/staleness risk, concurrency risk, authority wording, tests/gaps.

### 14. Role Manifest, Route Protocols, Dispatcher, and Multi-Agent Governance

- Why: MLH describes roles, route protocols, human gates, and dispatcher contracts as advisory governance.
- Surfaces: `docs/specs/authority-and-memory.md`; `adapter-boundary.md`; `agent_roles.py`; `routes.py`; `command_discovery.py`; `adapter.py`; `tests/test_package_metadata.py`; `tests/test_cli.py`.
- Invariants: role profiles do not approve lifecycle; dispatcher launch requires repo-visible handoff, compatible claim, and planned evidence path; human gates are route-specific; fan-in authority stays with coordinator/human gate.
- Questions: Do permissions map to route mutability and human gates? Are allowed decisions consistent across JSON/docs/code? Can dispatcher proceed without required refs? Are forbidden actions visible enough?
- Evidence: `manifest --inspect --json`; source review of `agent_roles.py`/`routes.py`; tests.
- Result: role/route governance matrix with permissions, gates, output packets, forbidden actions, tests/gaps.

### 15. Reporting, Diagnostics, Evidence Cues, and Operator Language

- Why: CLI reports are the main UX and must not imply authority they do not have.
- Surfaces: `docs/specs/context-and-ceremony-budget.md`; `attach-repair-status-cli.md`; `reporting.py`; `evidence_cues.py`; `checks.py`; `tasks.py`; `command_discovery.py`; `tests/test_cli.py`; `tests/test_package_metadata.py`.
- Invariants: reports are advisory unless apply writes files; wording must not approve closeout/archive/commit/repair/rollback/lifecycle; `check` can return success with warnings but fails on validation errors; task map is orientation.
- Questions: Are severities consistent? Does any wording encourage unsafe shortcuts? Are JSON/text outputs equivalent? Are warnings vs errors chosen correctly?
- Evidence: `check`; `tasks --inspect`; `evidence`; `closeout`; reporting tests.
- Result: wording-risk table with command/report section, phrase, risk, recommendation, source refs.

### 16. Package Metadata, Build Backend, Bootstrap, and Dependency Gate

- Why: MLH is a local Python package with stdlib-first dependency posture.
- Surfaces: `pyproject.toml`; `build_backend/mylittleharness_build.py`; `uv.lock`; `README.md`; `docs/README.md`; `docs/specs/product-boundary.md`; `bootstrap.py`; `templates/**`; `tests/test_package_metadata.py`; `tests/test_cli.py`.
- Invariants: package name/version `mylittleharness`/`1.0.1`; runtime dependencies empty; stdlib build backend; console script `mylittleharness = mylittleharness.cli:main`; bootstrap inspect/package-smoke cannot publish, mutate PATH/user config, or write product-root artifacts.
- Questions: Does wheel include required modules/templates and exclude cache/debris? Is dependency gate enforced by tests or docs only? Does package smoke run outside product checkout and without network assumptions? Are metadata/docs/tests consistent?
- Evidence: `bootstrap --inspect`; `bootstrap --package-smoke`; direct PEP 517 backend review; package metadata tests.
- Result: packaging report with metadata consistency, wheel contents, template inclusion, smoke behavior, dependency policy, risks.

### 17. Templates and Compatibility Fixtures

- Why: MLH ships operating-root/workflow templates and product-root compatibility fixtures.
- Surfaces: `src/mylittleharness/templates/operating-root/AGENTS.md`; `src/mylittleharness/templates/workflow/*.md`; `project/specs/workflow/*.md`; `.mylittleharness/project-workflow.toml`; `project/project-state.md`; `AGENTS.md`; template/package/inventory/CLI tests.
- Invariants: product fixtures are not live memory; stable workflow spec templates can be restored create-only in eligible live roots; template content should align with product contracts where mirrored; operating-root template must teach safe rails.
- Questions: Do packaged templates drift from fixtures/specs? Are generated scaffolds minimal and complete? Can restore overwrite user edits? Does template wording overclaim authority?
- Evidence: compare template files to fixtures; temp-root `repair --dry-run`; package/inventory tests.
- Result: template parity table with template, counterpart, intended drift status, restore behavior, tests/gaps.

### 18. Test Strategy and Coverage Topology

- Why: Broad behavioral tests exist, especially `tests/test_cli.py`, but safety-critical coverage should be mapped.
- Surfaces: all `tests/*.py`, especially `test_cli.py`, `test_inventory.py`, `test_memory_hygiene.py`, `test_package_metadata.py`, `test_projection*.py`, `test_planning.py`, `test_research_*.py`, `test_relationship_drift.py`, `test_vcs.py`, `test_cli_parser.py`, `test_parsing.py`, `test_lifecycle_focus.py`.
- Invariants: tests cover CLI behavior, product/source boundary, projection cache, memory hygiene, packaging, planning, research, relationship drift, VCS probes, parsing, lifecycle focus; many tests are fixture/output-based.
- Questions: Which safety promises have direct tests vs docs-only? Are tests overcoupled to wording while missing behavior? Are symlink, Windows path, permission, concurrency, stale-cache, and partial-write cases covered? Should `test_cli.py` be split for auditability?
- Evidence: `python -m unittest discover -s tests`; `rg -n "def test_" tests`; command-to-test coverage mapping.
- Result: coverage matrix with product promise, source module, docs refs, tests, untested edge cases, recommended new tests.

### 19. Documentation and Spec Traceability

- Why: Product contracts are doc-heavy and must trace to source/tests.
- Surfaces: `README.md`; `AGENTS.md`; `docs/README.md`; `docs/architecture/*.md`; `docs/specs/*.md`; `.agents/docmap.yaml`; `project/project-state.md`; `project/specs/workflow/*.md`; docs/package/inventory/CLI tests.
- Invariants: docs are product contracts, not operating memory; docmap is routing metadata; current vs future/non-goal surfaces must be separated; product-source fixture notes should be consistent.
- Questions: Do docs mention unsupported commands/flags? Do source/tests implement documented refusals? Are future/deferred surfaces clearly separated? Are product-source notes consistent across AGENTS/README/docs/docmap/state?
- Evidence: `audit-links`; `tasks --inspect`; `manifest --inspect --json`; `rg` over docs/source/tests for commands and invariant phrases.
- Result: traceability ledger with promise, docs refs, source refs, test refs, status, drift/gap.

### 20. Security, Prompt-Injection, Path, Secrets, and Supply Chain

- Why: MLH operates in AI-assisted repos and touches files, caches, MCP, hooks, subprocess/package smoke, and reports.
- Surfaces: `docs/specs/adapter-boundary.md`; `mcp-ecosystem-adoption-gate.md`; `product-boundary.md`; `generated-state-and-projections.md`; `pyproject.toml`; build backend; `adapter.py`; `hooks.py`; `preflight.py`; `projection_index.py`; `atomic_files.py`; `bootstrap.py`; package/projection/CLI tests.
- Invariants: no runtime dependencies by default; adapters cannot approve lifecycle; generated caches are disposable; provider/embedding runtimes are deferred/gated; bootstrap/publishing/workstation mutation is rejected or read-only.
- Questions: Are reads/writes path-confined and symlink-safe on Windows and cross-platform? Could repo text/prompt-like content influence reports into unsafe commands? Does SQLite FTS cache sensitive source text in a clearly disposable place? Are external commands/PATH discovery/hook shims free of unintended execution? Is dependency policy enforceable before future deps?
- Evidence: static review for `subprocess`, path writes, config writes, JSON-RPC, SQLite, environment/PATH handling; security edge-case tests.
- Result: threat model with assets, trust boundaries, attack scenarios, current controls, missing controls, severity, and recommended tests.

## Ready Prompts for ChatGPT Pro Agent

### Prompt 0: Scope and Reading Protocol

```text
You are performing an independent source-grounded audit of the MyLittleHarness product repository only.

Repository root: <product-repo-root>

Hard scope rules:
- Do not inspect or analyze private development roots, local workspace repos, runtime cache, generated local state, or neighboring repositories.
- If product files mention an operating root/dev root, treat that only as product-model context and do not follow the path.
- Exclude meta-feedback as a standalone audit topic. Do not audit the meta-feedback route, capture flow, env routing, tests, docs, prompts, or developer-local feedback workflow.
- Do not fix code, commit, stage, or mutate product behavior during audit unless explicitly asked in a separate task.

Start by reading AGENTS.md, README.md, docs/README.md, docs/architecture/*.md, docs/specs/*.md, .agents/docmap.yaml, .mylittleharness/project-workflow.toml, project/project-state.md, pyproject.toml, and docs/external-audit-prep.md.

For every finding, cite repo-relative files and line numbers where possible. Distinguish code behavior, test behavior, docs promises, and inferred risk. Do not treat CLI report output, generated projection output, MCP output, hooks, dashboard, or daemon state as authority.
```

### Prompt 1: P0 Safety Boundary Audit

```text
Audit these P0 blocks from docs/external-audit-prep.md: 1, 2, 3, 4, 5, 7, 13, and 16.

Produce:
- Executive risk summary.
- Findings ordered by severity.
- For each finding: invariant violated or at risk, exact source refs, minimal reproduction command or test sketch, expected vs observed behavior, and recommended verification.
- A "verified without finding" section for important invariants checked and supported.
- A "not audited / needs follow-up" section.

Do not include meta-feedback as an audit block.
```

### Prompt 2: P1 Lifecycle, Routing, and Documentation Audit

```text
Audit these P1 blocks from docs/external-audit-prep.md: 6, 8, 9, 10, 11, 12, 14, and 19.

Produce:
- Route/lifecycle traceability map from docs promises to source modules and tests.
- Findings ordered by severity.
- For each finding: affected route/command, source refs, docs refs, test refs, reproduction or missing-test sketch, and recommended audit follow-up.
- Explicit separation of advisory-output issues from authority/mutation issues.

Do not include meta-feedback as an audit block.
```

### Prompt 3: P2 Readiness, UX, Coverage, and Security Audit

```text
Audit these P2 blocks from docs/external-audit-prep.md: 15, 17, 18, and 20.

Produce:
- Product readiness assessment with risks and confidence levels.
- Wording/diagnostic risks where reports could be mistaken for approval.
- Template/fixture parity findings.
- Coverage matrix and missing edge-case tests.
- Threat model with assets, trust boundaries, attack scenarios, current controls, and missing controls.

Do not include meta-feedback as an audit block.
```

### Prompt 4: Single-Block Deep Dive

```text
Perform a deep source-grounded audit of this MyLittleHarness audit block:

<paste one block from docs/external-audit-prep.md>

Repository root: <product-repo-root>

Use only product repository files. Do not inspect operating-root/dev-root/workspace/cache/sibling repositories. Exclude meta-feedback as a standalone topic.

Required output:
1. Block summary.
2. Product promises/invariants found in docs/source/tests.
3. Source map with exact files and line refs.
4. Test coverage map.
5. Findings ordered by severity.
6. Missing tests or weak evidence.
7. Suggested verification commands.
8. Residual risk and confidence rating.
```

### Prompt 5: Final Audit Synthesis

```text
Synthesize completed MyLittleHarness audit-block reports.

Required output:
- Top risks across all blocks, ordered by severity.
- Cross-block inconsistencies.
- Safety-boundary confidence for product/target boundary, authority model, dry-run/apply rails, generated non-authority, adapters, lifecycle writeback, and packaging.
- Missing tests prioritized by risk.
- Documentation drift ledger.
- Recommended next audit or remediation sequence.
- Explicit excluded-scope note: meta-feedback was not audited as a standalone topic.

Do not invent findings not supported by source refs or prior block reports.
```

## How To Use The Prompts

1. Run Prompt 0 first to lock scope and source protocol.
2. Run Prompt 1 before broader work; record P0 findings before P1.
3. Run Prompt 2 for lifecycle, routing, and docs traceability.
4. Run Prompt 3 for readiness, UX/reporting, template parity, coverage, and security.
5. Use Prompt 4 for any block with high severity or shallow coverage.
6. Run Prompt 5 only after block reports exist; it should synthesize, not rediscover from scratch.

Suggested external auditor output filenames:

- `external-audit-p0-safety-boundaries.md`
- `external-audit-p1-lifecycle-routing-docs.md`
- `external-audit-p2-readiness-security.md`
- `external-audit-deep-dive-<block-slug>.md`
- `external-audit-final-synthesis.md`

## Preparation Evidence: What Was Studied

Source files and surfaces reviewed for this prep:

- Root/product instructions: `AGENTS.md`, `README.md`, `.agents/docmap.yaml`, `.mylittleharness/project-workflow.toml`, `project/project-state.md`.
- Architecture docs: `docs/README.md`, `docs/architecture/product-architecture.md`, `docs/architecture/layer-model.md`, `docs/architecture/clean-room-carry-forward.md`.
- Specs: `docs/specs/product-boundary.md`, `docs/specs/operating-root.md`, `docs/specs/authority-and-memory.md`, `docs/specs/generated-state-and-projections.md`, `docs/specs/generated-state-search-and-sqlite.md`, `docs/specs/context-and-ceremony-budget.md`, `docs/specs/mcp-ecosystem-adoption-gate.md`, `docs/specs/attach-repair-status-cli.md`, `docs/specs/metadata-routing-and-evidence.md`, `docs/specs/adapter-boundary.md`.
- Workflow compatibility fixtures: `project/specs/workflow/*.md`.
- Package metadata/build: `pyproject.toml`, `build_backend/mylittleharness_build.py`, `uv.lock`.
- Source tree: CLI/parser/dispatch; routes/roles; inventory/checks; planning/writeback/roadmap; research/incubation/memory hygiene; evidence/claims/handoffs/approval/review/reconcile; projection/index/semantic; adapter/dashboard/daemon/hooks/preflight; bootstrap/tasks/command discovery; atomic/parsing/reporting utilities.
- Templates: `src/mylittleharness/templates/operating-root/AGENTS.md`, `src/mylittleharness/templates/workflow/*.md`.
- Tests: `tests/test_cli.py`, `tests/test_inventory.py`, `tests/test_memory_hygiene.py`, `tests/test_package_metadata.py`, `tests/test_projection.py`, `tests/test_projection_artifacts.py`, `tests/test_projection_index.py`, `tests/test_planning.py`, `tests/test_research_intake.py`, `tests/test_research_distill.py`, `tests/test_research_compare.py`, `tests/test_relationship_drift.py`, `tests/test_vcs.py`, `tests/test_cli_parser.py`, `tests/test_parsing.py`, `tests/test_lifecycle_focus.py`.

Read-only CLI reports sampled from the product root:

- `python -m mylittleharness --root . --help`
- `python -m mylittleharness --root . manifest --inspect --json`
- `python -m mylittleharness --root . status`
- `python -m mylittleharness --root . check`
- `python -m mylittleharness --root . tasks --inspect`
- `python -m mylittleharness --root . bootstrap --inspect`

Additional source search used `rg` over product docs/source/tests, excluding meta-feedback as a standalone audit topic.

## Less-Studied or Intentionally Excluded Areas

- Meta-feedback is intentionally excluded as a standalone audit direction by scope.
- Neighboring repositories, dev roots, workspace repos, runtime caches, generated local state, and sibling repos were not inspected.
- The largest files (`checks.py`, `writeback.py`, `roadmap.py`, `tests/test_cli.py`) were mapped broadly, not exhaustively line-by-line.
- Dynamic package smoke and full test-suite execution were not part of this prep artifact creation; external audit should run them.
- Security content here is a surface map, not a completed threat model.
- Generated projection/SQLite contents were treated as rebuildable/advisory surfaces, not durable evidence.

## Docs Decision

- docs_decision: updated
- Rationale: this request produced a new product-doc audit-prep artifact only; no source code, tests, workflow state, commits, or product behavior were changed.
