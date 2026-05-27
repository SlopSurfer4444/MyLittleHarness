---
project: "MyLittleHarness"
root_role: "product-source"
fixture_status: "product-compatibility-fixture"
workflow: "workflow-core"
workflow_version: 1
operating_mode: "ad_hoc"
plan_status: "none"
active_plan: ""
last_archived_plan: ""
operating_root: "../operating-project"
product_source_root: "."
historical_fallback_root: "../archive-evidence"
last_updated: "2026-04-29"
---

# MyLittleHarness Product Compatibility Fixture State

## Fixture Boundary

- This file is product compatibility fixture metadata for the `mylittleharness` CLI/tests.
- It is not live task memory.
- The configured operating project root represents an explicit target repository for CLI/tests.
- The configured fallback root is fixture-only reference material.
- This repository contains the reusable MyLittleHarness product source, docs, tests, and package metadata.
- `workflow-core` remains only a compatibility label for fixture manifest and operator-contract compatibility.
- `plan_status = "none"`.
- No active implementation plan is open in this product tree.
- `last_archived_plan` is intentionally empty because archived plans do not belong in this product source tree.

## Product Surfaces

- `README.md`
- `AGENTS.md`
- `pyproject.toml`
- `src/mylittleharness/*.py`
- `tests/*.py`

## Compatibility Fixtures

- `.mylittleharness/project-workflow.toml`
- `.agents/docmap.yaml`
- `project/project-state.md`
- `project/specs/workflow/*.md`

These fixtures exist so the product can validate and describe a minimal workflow-shaped root. They are not a second workflow root and must not accumulate operational memory.

## Explicitly Excluded

- `project/implementation-plan.md`
- `project/archive/plans/**`
- `project/research/**`
- raw intake
- archive-under-study material
- candidate source packs
- old migration evidence
- package zip files
- build directories, wheel files, or egg-info from package smoke checks
- broad research corpus
- old implementation plans
- runtime helpers
- runtime debris
- installed skills
- generated MCP config, HTTP/network MCP surfaces, or adapter state
- hooks
- PATH or user-config changes
- logs
- reports
- caches
- generated output outside `.mylittleharness/generated/projection/`
- generated semantic output, embedding stores, vector stores, model downloads, or provider config
- repair snapshots under `.mylittleharness/snapshots/repair/`
- local databases
- generated validation artifacts
- pycache
- other runtime debris

## Active Focus

- Keep this directory clean as product source plus minimal compatibility fixtures.
- Use an explicit target repository for context recovery, plans, research, state writeback, and closeout memory.
- Use this directory for source, tests, README/product docs, and bounded fixture updates only.
- Target product CLI direction is the small visible utility `init`, `check`, `repair`, and `detach`. In 1.0.0, `init` is the primary bounded attach route, `check` is the primary read-only status plus validation route, `detach --dry-run` is the primary no-write detach preview, `detach --apply` is a marker-only disable path for eligible live operating roots, `bootstrap --package-smoke` verifies local package install/import/console-script behavior from temporary locations outside the product root, `intelligence --query` expands one recovery query across omitted exact/path/full-text search modes and may refresh disposable generated navigation cache inside `.mylittleharness/generated/projection/`, `adapter` provides optional read-only MCP projection access, `closeout` can suggest read-only Git trailers from explicit closeout fields, `repair` remains explicit with bounded state/docmap/stable-spec classes, and `attach`, `status`, `validate`, and advanced diagnostic commands remain implemented compatibility surfaces. `tasks` and `bootstrap` are hidden from top-level help while command-specific help and inspect/package-smoke reports remain compatible.
- `init --dry-run` and `init --apply --project <name>` route through the same proposal and create-only mutation boundaries as compatibility `attach --dry-run` and `attach --apply --project <name>`, including product-source fixture refusal with exit `2`.
- `check` is a terminal-only read-only report with `Status`, `Validation`, `Agent Run Evidence`, `Work Claims`, `Projection Cache`, `Drift`, and `Boundary` sections. It composes `status`, `validate`, agent run/work-claim diagnostics, projection-cache posture, docmap/root-pointer drift, and explicit delivered-vs-remainder token drift in operating-memory or research surfaces, writes no files, returns `1` when validation has error findings, and otherwise returns `0` even with advisory warning findings.
- `status` reports MyLittleHarness product posture: product name, target root role, fixture status, operating root, product root, fallback root, and fixture boundary posture.
- `status` and `validate` classify roots as product-source fixtures, live operating roots, fallback/archive evidence, or ambiguous targets.
- `validate` reports product-root posture failures with `product-posture-*` finding codes while preserving compatibility-fixture validation; for live operating roots it treats `README.md` as optional, honors lazy `.agents/docmap.yaml`, and uses prose assignment lines in `project-state` only for read-only lifecycle recovery.
- `audit-links` includes product docs under `docs/**`, resolves product-doc relative links from the source document, reports docmap gaps, and treats known lazy, snapshot-internal, or intentionally excluded fixture paths as informational.
- `preflight` is a terminal-only optional warning report with `Summary`, `Checks`, `Closeout Readiness`, and `Boundary` sections. It summarizes `validate`, `audit-links`, `context-budget`, product hygiene, and read-only closeout posture, including VCS posture cues from closeout when Git is available. `preflight --template git-pre-commit` prints a deterministic POSIX local Git pre-commit wrapper to stdout; the wrapper runs `mylittleharness --root "$MLH_ROOT" preflight`, warns on unavailable tooling or unsuccessful completion, and exits `0`. Preflight does not install hooks, add CI/GitHub workflows, write reports, block by itself, repair files, archive, commit, change target roots, or approve lifecycle decisions.
- `tasks --inspect` is a terminal-only read-only operator task map with `Summary`, `Operator Tasks`, `Compatibility`, `Boundary`, and `Future Power-Ups` sections. It is hidden from top-level help as an advanced transition diagnostic, while `tasks --help` and `tasks --inspect` remain supported. It groups existing commands into orient, verify, search/inspect, evidence/closeout, generated projection, package/bootstrap readiness, attach/repair, and optional warning-wrapper template tasks while preserving existing commands, flags, exit behavior, defaults, package console script, and mutation boundaries. It remains a transition/deprecation candidate after primary `init` and `check` exist.
- `bootstrap --inspect` is a terminal-only read-only readiness report with `Summary`, `Package Smoke`, `Bootstrap Apply`, `Publishing`, `Workstation Adoption`, and `Boundary` sections. It is hidden from top-level help as an advanced transition diagnostic, while `bootstrap --help`, `bootstrap --inspect`, and `bootstrap --package-smoke` remain supported. It reports interpreter context, root kind, product package metadata when available, console-script declaration, and PATH discovery for `mylittleharness`; separates local package smoke, rejected standalone bootstrap apply, rejected standalone workstation mutation, publishing automation, package artifact policy, PATH/user-config mutation, and workstation adoption into explicit decision lanes; and treats workstation adoption as no-write readiness evidence only. It installs no dependencies in the product root, builds or publishes no packages, writes no product-root artifacts, executes no discovered console script, mutates no workstation state, switches no roots, approves no lifecycle decisions, and creates no bootstrap authority. It remains a transition/deprecation candidate because bootstrap, publishing and workstation adoption should not be first-contact concepts.
- `semantic --inspect` is a terminal-only read-only readiness report with `Summary`, `Search Base`, `Runtime`, `Evaluation`, and `Boundary` sections. It summarizes the current in-memory projection, generated projection artifact posture, SQLite FTS/BM25 index posture, deferred embedding runtime posture, and future evaluation expectations without accepting semantic queries, installing dependencies, downloading models, calling providers, writing reports, creating vector stores, creating `.mylittleharness/generated/semantic/`, mutating workflow state, repairing files, archiving, committing, switching roots, or approving lifecycle decisions.
- `semantic --evaluate` is a terminal-only read-only bounded evaluation report with `Summary`, `Corpus`, `Evaluation Queries`, `False-Positive Review`, `Source Verification`, `Degraded Modes`, and `Boundary` sections. It uses fixed built-in queries against the current source-verified SQLite FTS/BM25 index when available, reports source path/line/hash provenance for matches, degrades cleanly when the index is missing, stale, corrupt, malformed, root-mismatched, or FTS5-unavailable, and creates no generated semantic output, runtime dependencies, vector stores, reports, repairs, archives, commits, lifecycle decision state, or lifecycle authority.
- Package smoke support is local-only: `pyproject.toml` defines the stdlib package metadata, version `1.0.0`, `dependencies = []`, empty `build-system.requires`, the `build_backend/mylittleharness_build.py` stdlib backend, packaged stable spec templates, and the `mylittleharness` console script. Operators can run from this source checkout with `PYTHONPATH=src`, while `bootstrap --package-smoke` must use temporary source/build/venv locations outside this checkout, verify no-network install/import/console-script behavior, return `1` for smoke failures, and cannot publish packages, change PATH, write user config, install hooks, create bootstrap authority, change target roots, or store package artifacts in the product root.
- `intelligence [--query TEXT] [--search TEXT] [--path TEXT] [--full-text TEXT] [--limit N] [--focus search|warnings|projection|routes]` is a terminal-only advisory aggregate report over inventory-discovered surfaces. It rebuilds an in-memory projection on every run and reports summary, boundary, drift, repo-map, backlinks, search, fan-in, and projection sections by default; drift includes link/docmap/root-pointer checks plus explicit delivered-vs-remainder token contradictions in operating-memory or research surfaces. `--query` fills omitted exact text, path/reference, and full-text modes while explicit mode-specific flags keep their own values. Focused search may refresh missing or stale disposable projection artifacts or SQLite indexes inside `.mylittleharness/generated/projection/`; warning, route, and projection views keep recovery output compact without generated cache refresh. Exact text search reads source content through the in-memory projection; focused path search can compare valid artifact path/reference rows with the current in-memory projection after safe refresh; full-text search uses the SQLite FTS/BM25 index only when it is current and source-verified, relaxes plain multi-term input into OR terms for recovery search, and preserves explicit uppercase FTS operators or control markers.
- Bare `evidence` is a terminal-only read-only report over inventory-discovered workflow surfaces. It reports active-plan/source-set signals, verification anchor candidates or gaps, report-only cue identity, closeout field candidates or gaps, validation sections as verification closeout candidates, residual-risk lines, explicit skip rationale, carry-forward cues, and operator-required closeout reminders. Concrete closeout field candidates require explicit field bullets, exact field headings, or observed result lines; generated manifest language remains context. Bare `evidence` writes no persistent evidence manifests, report files, generated artifacts, caches, databases, adapter state, hooks, mutation proposals, quality-gate state, archive actions, commits, repairs, or plan lifecycle changes. `evidence --record --dry-run|--apply` is the explicit live-root write rail for one source-bound agent run record under `project/verification/agent-runs/*.md`; it remains evidence only and cannot approve closeout, archive, roadmap status, staging, commit, rollback, or lifecycle transitions.
- `closeout` is a terminal-only read-only closeout assembly report. It combines active-plan closeout field candidates, read-only Git evidence suggestions, residual-risk and carry-forward cues, report-only quality/readiness cues, manifest closeout policy, projection inspect posture, and a fail-open target-bound VCS probe into `Summary`, `Worktree`, `Closeout Fields`, `Git Evidence`, `Evidence Cues`, `Quality Gates`, `Projection`, and `Boundary` sections. Clean and dirty Git worktrees may receive advisory trailer suggestions only from explicit closeout fields; non-git or unknown Git posture receives Markdown/operator-summary fallback and no trailers. The command does not decide task scope, approve completion, stage files, commit, archive, repair, change target roots, write lifecycle state, write quality-gate state, write persistent evidence manifests, or create generated evidence.
- `adapter --inspect --target mcp-read-projection` is a terminal-only read-only adapter inspection report. `adapter --serve --target mcp-read-projection --transport stdio` is an explicit foreground dependency-free MCP stdio JSON-RPC tools server for the same read projection. Both expose source paths/roles/counts/hashes and generated-input posture without source bodies, and write no files, adapter state, generated reports, hooks, caches, databases, mutation proposals, archive actions, commits, repairs, lifecycle changes.
- `projection --build|--inspect|--delete|--rebuild [--target artifacts|index|all]` owns only `.mylittleharness/generated/projection/` and manages disposable schema v2 JSON projection artifacts, including `relationships.json`, plus the SQLite FTS/BM25 index. JSON artifacts exclude source bodies and lifecycle authority. The SQLite index may store indexed source text as generated cache content, but schema and metadata must not create lifecycle authority fields. Generated projections are source-bound and rebuildable and cannot approve attach, repair, archive, commit, plan lifecycle changes.
- `snapshot --inspect` is a terminal-only read-only repair snapshot inspection report over `.mylittleharness/snapshots/repair/`. It reports snapshot presence, `snapshot.json` readability, metadata identity, copied-file presence, hash and byte-count consistency, target-root confinement, current-target posture, retention, manual rollback instructions, product-source snapshot debris, fallback/generated/ambiguous root posture, symlink/path conflicts, and snapshot non-authority without writing files, creating snapshots, repairing, rolling back, cleaning up, archiving, committing, switching roots, updating state, or approving closeout.
- `detach --dry-run` is a terminal-only read-only detach preview with `Root Posture`, `Preservation`, `Marker`, `Generated Projection`, `Manual Recovery`, and `Boundary` sections. It returns `0` for readable roots, uses `detach-*` finding codes, preserves repo-visible authority files and `.mylittleharness/generated/projection/` when present, previews `.mylittleharness/detach/disabled.json`, reports product-source fixtures, fallback/archive or generated-output roots, ambiguous roots, missing or unreadable manifest/state surfaces, non-default authority paths, and path conflicts as fail-closed apply inputs, and writes no files, reports, caches, generated outputs, snapshots, Git state, config, hooks, CI files, package artifacts, workstation state, marker, metadata toggle, cleanup action, or lifecycle authority. `detach --apply` creates only `.mylittleharness/detach/disabled.json` in eligible live operating roots, leaves valid existing markers unchanged, refuses unsafe roots or invalid marker/path posture with exit `2`, and cannot approve cleanup, repair, closeout, archive, commit, rollback, lifecycle decisions, or future mutations. `disable` is explanatory terminology only, not a command spelling.
- `doctor` reports read-only product hygiene warnings for operational memory, package/source mirrors, reports, generated validation artifacts, logs, caches, local databases, package archives, and `__pycache__` directories without deleting anything.
- `init --dry-run`, compatibility `attach --dry-run`, and `repair --dry-run` provide report-first proposals only; they do not write files, repair fixtures, archive plans, or change target roots. `repair --dry-run` reports a no-write state-frontmatter snapshot plan when validation reports `state-prose-fallback` for default-path `project/project-state.md`, reports create-only plans for missing required `.agents/docmap.yaml` and missing stable workflow spec fixtures, and reports a no-write `.agents/docmap.yaml` route-repair snapshot plan when route diagnostics exist, naming target files, preview snapshot paths where relevant, metadata fields, copied-file paths, refusal or skip posture, manual rollback posture, and validation commands.
- `init --apply --project <name>` and compatibility `attach --apply --project <name>` refuse product-source compatibility fixtures, create only missing eager scaffold directories plus absent manifest/state templates in an explicitly targeted live operating root, and never overwrite existing file content.
- `repair --apply` refuses product-source compatibility fixtures, fallback/archive evidence, ambiguous roots, non-default state paths, malformed or partial state frontmatter, active-plan mismatches, and path conflicts; in a live operating root with prose project-state assignment fallback, it can snapshot-protect and prepend deterministic frontmatter to `project/project-state.md` before stopping, and in a live operating root with strict project-state frontmatter authority, it creates missing eager scaffold directories, can create an absent required `.agents/docmap.yaml`, can create absent required stable workflow spec fixtures from packaged templates, can perform the selected snapshot-protected `.agents/docmap.yaml` route repair, and runs post-repair validation plus audit-link checks.
- The product snapshot contract reserves `.mylittleharness/snapshots/repair/` inside an explicit live operating root for snapshot-protected existing-content repair. Snapshots are safety evidence with manual retention and manual rollback instructions; they cannot approve repair, rollback, cleanup, closeout, archive, commit, lifecycle decisions. Product-source fixtures refuse snapshot creation, and snapshot directories in this checkout are product debris. The implemented repair classes are snapshot-protected `project/project-state.md` frontmatter prepending for prose state, create-only `.agents/docmap.yaml` creation for missing required docmaps, create-only stable workflow spec fixture restoration, and snapshot-protected `.agents/docmap.yaml` route repair for existing docmaps; manifest normalization, malformed state frontmatter repair, active-plan mutation, archive cleanup, stable-spec rewrites, and lifecycle mutation remain deferred.
- Product readiness requires coherent source, tests, package metadata, product docs, compatibility fixtures, clean product-root hygiene, and operating-root closeout evidence. Optional power-ups such as semantic runtimes, generated evidence manifests, quality gates, adapter packs, hooks/CI, publishing, mutating workstation adoption, repair expansion, rollback automation, and snapshot cleanup require scoped contracts with dependency policy, degraded/offline behavior, verification, and non-authority wording before they become product surfaces. Standalone bootstrap apply is rejected rather than carried as an optional power-up. Generated evidence manifests are rejected as the default durable history path.

## Next Step

- Run the CLI from this checkout with the checkout's `src` directory on `PYTHONPATH`; the package also declares the `mylittleharness` console script for local install or wheel smoke checks performed outside the product root.
- Open any future product implementation plan in the configured operating project root with this directory named as the target root.
- Do not promote standalone bootstrap apply, publishing automation, mutating workstation adoption, Context Ledger / Synapti, persistent evidence manifests, evidence IDs / enforcement quality gates, candidate tooling, package/archive regeneration, package/attach distribution, additional MCP servers, skills/hooks, CI/GitHub workflows, runtime helpers, or other deferred/rejected lanes into this product tree.
