# MyLittleHarness Product Architecture

## Thesis

MyLittleHarness is a passive, deterministic, repo-native safety layer for AI-assisted development.

The product is not an active orchestrator, hidden runtime, dashboard, scheduler, CI substitute, agent router, or workflow bureaucracy engine. Its job is to make a target repository easier to inspect, attach, check, repair, and later detach without taking authority away from repo-visible files and the human operator.

The default product story is deliberately small:

`MyLittleHarness -> target repository`

The visible utility should feel like a repo handle, not a command cockpit. The target top-level CLI is `init`, `check`, `repair`, and `detach`. Current implementation provides primary `init`, `check`, no-write `detach --dry-run`, and marker-only `detach --apply`, while keeping `attach`, `status`, `validate`, and advanced diagnostic commands as compatibility or progressive-disclosure surfaces with command-specific help.

The current productization milestone is a local 1.0.0 release candidate at package version `1.0.0`. It validates the product boundary and verification baseline without declaring package-index publication, global installation, mutating workstation adoption, or standalone workstation mutation as part of the shipped runtime model.

The supported distribution posture is deliberately local before publication. Source-checkout usage relies on the checked-out `src` tree; package verification relies on `bootstrap --package-smoke`, which installs from a temporary source copy into a temporary virtual environment with no network indexes and checks package metadata, import/version, and the console script. Adoption readiness relies on `bootstrap --inspect` as a read-only report over interpreter context, product package metadata when available, console-script declaration, PATH discovery, and future-gate decisions. Wheel or install artifacts are verification outputs only when created outside the product root; they do not become accepted truth, lifecycle authority, workstation adoption, or a required operating layer.

The first-run path is source checkout first, package-smoke when the operator wants package evidence, and target-repository `init` / `check` / `repair` / `detach` after that. `bootstrap --inspect`, publishing, global install, workstation adoption, semantic/provider setup, MCP clients, hooks, and CI are progressive-disclosure or future-contract surfaces, not prerequisites for first-contact correctness.

The default operating-root start pass is file and shell based: read `AGENTS.md`, `.mylittleharness/project-workflow.toml`, `project/project-state.md`, and the active plan only when `plan_status = "active"` or the operator asks about plan/phase/closeout; use legacy `.codex/project-workflow.toml` only as a fallback manifest when the neutral manifest is absent; use `active_phase` and `phase_status` as the structured continuation pointers when present; use `check` before mutation; use `.agents/docmap.yaml`, `audit-links`, and relevant specs as docs-routing inputs when user-facing meaning changes. Meta-feedback is an opt-in capture rail, not a default start-pass requirement. No skill, IDE rule, MCP client, hook, CI job, or workstation adoption step is part of the correctness path.

The formula is:

Files hold authority; metadata routes; Git records durable history; generated projections accelerate; diagnostics warn; adapters assist; mutation stays explicit and fail-closed.

## Design Axioms

- Authority before automation: automation may suggest, summarize, validate, report, or project, but accepted decisions live in repo-visible artifacts.
- Rails, not cognition: MLH may route, store, validate, warn, and preserve provenance for agent or human work, but it must not perform the substantive research, synthesis, planning judgment, or prompt authorship that belongs to the active agent/human operator.
- Repo-native recovery: the harness must remain understandable without installed skills, hooks, MCP clients, GitHub, browser state, IDE state, CI, SQLite, or hidden runtimes.
- Portable docs decisions: behavior, CLI, config, setup, contract, permissions, output shape, UX/copy, terminology, rollout, migration, or other user-facing changes require an explicit `docs_decision` of `updated`, `not-needed`, or `uncertain`; `uncertain` prevents confident closeout wording. The MLH-owned closeout writeback block in `project/project-state.md` is the current closeout fact authority, while active-plan frontmatter/body copies and project-state hot pointers are derived diagnostics synchronized by `writeback --apply`; optional roadmap sync records only same-request writeback facts plus plan relationships.
- Git-native evidence first: when a repository uses Git, durable closeout history should prefer commit metadata such as trailers over generated evidence files.
- Markdown plus metadata, not metadata alone: human-readable Markdown carries meaning; YAML/JSON routing helps tools navigate it.
- Progressive disclosure: first-contact docs and future top-level help should show only the small repo utility shape, with diagnostics available behind advanced modes or compatibility commands.
- Generated state is build-to-delete: generated views are rebuildable, disposable, subordinate speedups and cannot hold unique authority.
- Read-only helpers fail open: diagnostics may degrade to partial findings so recovery remains possible.
- Mutations fail closed: attach, repair, detach, or future apply paths must refuse ambiguous authority, unsafe paths, unsupported roots, or generated-only evidence before writing.
- Adapters fail open: integrations may help with speed and ergonomics, but correctness must remain recoverable from files and generic CLI reports.
- Solo leverage beats platform symmetry: borrow larger-system patterns only when they improve trust, recovery, or speed for a solo developer.
- Compatibility is a bridge, not identity: existing workflow-core vocabulary and current commands may remain during migration, but they do not define the long-term product front door.

## Core Invariants

- Product docs live under `docs/...` in the product source tree.
- Operating workflow memory does not live in the product source tree.
- MyLittleHarness serves an explicit target repository directly.
- Compatibility fixture files under `.mylittleharness/`, `.agents/`, and `project/` are subordinate fixtures for CLI/tests; legacy `.codex/` manifests remain target-root fallback/migration compatibility only.
- Product docs may name target CLI and roadmap surfaces, but docs alone do not implement unshipped commands.
- Generated views, databases, caches, reports, helper logs, and adapter state cannot be the only copy of accepted decisions, active focus, plan status, carry-forward fates, or workflow authority.
- Repair snapshots can preserve pre-repair bytes and metadata for inspection, but they cannot approve repair, closeout, archive, commit, lifecycle decisions.
- Hooks, issue trackers, GitHub, CI, MCP clients, browser state, IDE state, and task runners cannot become mandatory correctness.
- Persistent generated evidence manifests are rejected as the default durable history path; reintroducing them requires a later explicit plan that proves Git-native history cannot satisfy the need.

## Visible CLI Model

The target visible CLI is:

- `init`: attach MyLittleHarness to an explicit target repository. Current implementation routes through the same bounded dry-run/apply behavior as compatibility `attach`.
- `check`: summarize orientation and validation without writing. Current implementation composes `status` plus `validate`; deeper diagnostics remain explicit advanced commands.
- `repair`: preview or apply one bounded repair class at a time. This remains explicit, dry-run/apply based, snapshot-protected when rewriting existing content, and fail-closed.
- `detach`: preview harness disconnect posture and create marker-only disabled evidence with no surprise deletion. Current `detach --dry-run` reports root posture, preservation, marker target, generated projection posture, manual recovery notes, and boundary reminders without writing; `detach --apply` creates only `.mylittleharness/detach/disabled.json` in eligible live operating roots.

`sync` is not a primary command. Disposable projection refresh, search, semantic readiness, adapter projection, and report assembly stay advanced unless a later slice proves that a visible refresh command reduces ceremony.

Existing commands such as `doctor`, `preflight`, `context-budget`, `audit-links`, `intelligence`, `projection`, `semantic`, `evidence`, `closeout`, `writeback`, `snapshot`, `adapter`, `bootstrap`, and `tasks` may remain implemented. They should be documented and exposed as advanced diagnostics, compatibility surfaces, explicit writeback, or transition tools rather than the product front door. `intelligence --query` is the recovery-search convenience over existing exact/path/full-text source-verified modes and may refresh disposable navigation cache inside `.mylittleharness/generated/projection/`, `repair` includes create-only AGENTS and stable spec fixture restoration, `plan --roadmap-item` / `writeback --roadmap-item` are hidden explicit roadmap relationship sync points, `writeback --apply` is the hidden explicit closeout/state/product-source metadata synchronization path for live operating roots, `incubate --fix-candidate` standardizes MLH debt capture, `memory-hygiene --archive-covered` combines terminal Entry Coverage with bounded incubation archive movement, `writeback --compact-only` is the hidden bounded state-history compaction path, `bootstrap --package-smoke` is explicit local package verification from temporary locations outside the product root, and `bootstrap --inspect` is the no-write adoption readiness report. Top-level help foregrounds only `init`, `check`, `repair`, and `detach`; advanced and compatibility commands keep command-specific help and normal report stdout. `tasks --inspect`, `bootstrap --inspect`, and `bootstrap --package-smoke` remain transition/deprecation candidates because they preserve power-up-era cockpit language.

Compatibility preservation must not ossify overload. New primary commands should be introduced with compatibility tests for old commands and exit semantics. Deprecation starts in docs and help before normal stdout warnings or removals.

## Evidence And Generated Output

Durable evidence should follow the repository's durable history.

For Git repositories, closeout evidence should prefer commit metadata such as Git trailers. Read-only `evidence` and `closeout` helpers may assemble candidate fields or suggested trailer lines, but they must not stage, commit, archive, repair, decide task scope, or approve lifecycle transitions.

For non-git roots, the fallback is repo-visible Markdown closeout fields, explicit operator summaries, and source-linked verification notes. The fallback is not a generated evidence database.

Generated outputs remain speedups:

- `.mylittleharness/generated/projection/` is the only accepted generated-output boundary.
- Projection JSON, the generated relationship graph, and SQLite FTS/BM25 indexes remain disposable, rebuildable, source-bound, stale-checked, and non-authoritative.
- Semantic readiness/evaluation may report over the existing source-verified search base, but generated semantic output, embeddings, vector stores, provider config, and model downloads remain unimplemented.
- No generated validation reports, evidence databases, quality-gate state, adapter memory, or hidden stores become product authority.

## Product Capability Gates

Future MyLittleHarness product work should be selected by low-ceremony operator value and safety, not by old power-up sequencing.

Recommended roadmap order:

1. Advanced diagnostics cleanup: continue reducing command-sprawl documentation after hiding `tasks` and `bootstrap` from first-contact help.
2. Mutation and rule analyzer hardening: audit fail-closed apply behavior and add lightweight rule/context drift signals only where they reduce operator risk.
3. Future detach expansion only if a later contract proves value beyond the current marker-only disabled evidence.
4. Stronger evidence helpers only if the current read-only Git trailer suggestions prove insufficient without adding generated evidence authority.

Rejected default directions:

- durable generated evidence manifests as the default evidence history
- automatic rollback, broad `repair-all`, or autonomous repair loops
- MCP or adapter mutation tools
- hook/CI installation as required correctness
- semantic/vector-first expansion before source-first search and CLI clarity
- standalone `bootstrap --apply`, publishing, mutating workstation adoption, or standalone workstation mutation as product surfaces

Scoped future capabilities may still ship when their contract names source of truth, generated-output or adapter boundary, dependency decision, degraded/offline behavior, rebuild/delete or disable story, verification method, and non-authority wording.

## Product Readiness Contract

A product-ready MyLittleHarness release candidate requires a coherent small operator story, clean root separation, verified compatibility behavior, and operating-root closeout evidence. The required product surfaces are the product README and operator contract, reusable docs under `docs/...`, package metadata, source modules, tests, and minimal compatibility fixtures. The 1.0.0 release-candidate baseline is the small visible CLI, stdlib package posture, package-smoke verification, explicit fail-closed repair and detach mutation boundaries, source-verified intelligence/evidence helpers, optional read-only MCP projection access, disposable source-bound projections, and deferred optional power-ups with scoped acceptance rules.

The product source checkout must stay free of active operating memory, plans, research intake, archives, generated validation reports, logs, caches, package debris, local databases, pycache, and repair snapshots.

The dependency baseline is a stdlib core. Any optional dependency, provider, runtime, package extra, publishing helper, or mutating workstation helper requires a product policy that names the install path, fallback mode, provenance checks, and cleanup or non-adoption posture. The accepted workstation adoption surface is read-only readiness evidence through `bootstrap --inspect`. Publication, global install, PATH/profile edits, and user-config mutation are outside the current release-candidate contract. Standalone `bootstrap --apply` and standalone workstation mutation are rejected as product surfaces.

Release evidence must include tests, smoke matrices, docs audits, product-root apply refusals, relevant package/adapter/semantic/hook/bootstrap/repair checks, hygiene scans, and operating-root closeout fields. Generated projections, semantic matches, evidence manifests, quality summaries, adapters, hooks, CI, VCS state, package artifacts, and repair snapshots are evidence inputs only; they cannot authorize mutation, closeout, archive, commit, rollback, lifecycle decisions.

## Explicit Non-Goals

- Hidden control plane, daemon, queue, dashboard, scheduler, or swarm.
- Second mutable memory tree.
- No SQLite or generated truth as canonical memory.
- Generated evidence manifests as the default durable evidence path.
- Semantic matches as mutation, repair, closeout, archive, commit, lifecycle authority.
- Mandatory adapters or hook-only correctness.
- Issue-board or CI state as project authority.
- Product-root contamination with plans, research, archives, logs, caches, generated reports, local databases, or runtime residue.
- Wholesale adoption of external candidate systems.
- Operational boundary changes from docs alone.
- Any extra operating layer, supervisor, evidence authority, or product runtime between MyLittleHarness and the target repository.
