# Product And Operating Boundary Spec

## Purpose

This spec defines how the MyLittleHarness product repository stays separate from the repositories it inspects or attaches to.

The shipped product serves one explicit target repository at a time.

Retired cross-repository parity-copy workflows are not part of the product CLI surface; workspace cleanup belongs to separately reviewed operating work, not reusable product commands.

Live operating-root validation compares command-shaped references in selected operating product-doc copies and docmap surfaces with the configured `product_source_root` CLI command surface. When the operating copy still names a retired command that the product source no longer exposes, `check` reports `product-doc-copy-retired-command-drift` as read-only evidence and does not auto-copy docs, install tools, restore retired commands, or approve repair, lifecycle movement, archive, staging, or commit.

## Portable Root Roles

- Product repository: reusable product source, tests, product README/operator orientation, product docs under `docs/...`, and minimal compatibility fixtures for CLI/tests.
- Target repository: the explicitly targeted repository MyLittleHarness inspects or attaches to; it owns its own plans, project state, research, navigation/routing surfaces, closeout evidence, and other task memory.
- Legacy reference material: old context opened only for a named blocker with a narrow lookup.
- Generated-output boundary: rebuildable artifacts, reports, caches, or indexes that remain disposable and subordinate to source files.
- Repair snapshot boundary: target-bound safety evidence under `.mylittleharness/snapshots/repair/` inside an explicit live operating root.
- Explicit target root: the root supplied by the operator to a CLI command.
- Ambiguous target: a target whose role cannot be proven from metadata, path, and product contract.
- Shared coordination root: an explicit live operating root named by `MLH_COORDINATION_ROOT` for agents editing separate worktrees. It is a routing hint for repo-visible coordination records, not hidden state, an access-control boundary, or lifecycle authority.

## Product Repository Responsibilities

The product source checkout holds:

- reusable product source
- tests
- stdlib package build backend
- product README and operator orientation
- product docs under `docs/...`
- minimal compatibility fixtures for CLI/tests when needed
- package metadata for the reusable stdlib package and console script

The product repository is for MyLittleHarness source, docs, tests, fixtures, and package metadata.

## Forbidden Product-Root Content

The product source checkout must not hold:

- active working memory
- implementation plans
- research/history/raw intake
- archived plans
- workflow execution state
- runtime debris
- generated validation artifacts
- repair snapshots
- logs, caches, local databases, package archives, pycache, or temporary outputs
- build directories, wheels, or egg-info from local package smoke checks
- hidden workflow schedulers, queues, dashboards, or control planes

## Fixture Boundary

The product tree may retain workflow-shaped fixtures under:

- `.codex/...`
- `.agents/...`
- `project/project-state.md`
- `project/specs/workflow/...`

These files are product compatibility fixtures for CLI/tests. They are not the home for new product architecture docs and are not operating memory.

Clean reusable architecture and specs belong under `docs/...`.

## Apply Boundary

The product source checkout is never the target for live workflow mutation. `init --apply`, compatibility `attach --apply`, `repair --apply`, and `detach --apply` must refuse product-source compatibility fixtures with exit code `2`; `init --dry-run`, `detach --dry-run`, compatibility `attach --dry-run`, and `repair --dry-run` remain report-only for product-source fixtures.

A live operating root may be attached only when the operator supplies it explicitly and it is not classified as product source, legacy reference material, generated output, adapter state, cache, log, local database, package archive, user config, PATH, hook, MCP, browser, IDE, GitHub, CI, or workflow execution surface.

The attach apply scope is create-only for authority files and may create eager scaffold directories and absent `.mylittleharness/project-workflow.toml` plus `project/project-state.md` from explicit templates, with `--project <name>` required for state creation. After successful attach, it may build disposable schema v2 JSON projection artifacts and `.mylittleharness/generated/projection/search-index.sqlite3` in the explicitly targeted live root. It must not create active implementation plans, archives, research intake, generated validation artifacts, logs, caches, local databases outside the owned projection boundary, or workflow execution residue in the product source tree.

Repair apply must stay narrower than validation: only deterministic proposals with allowed paths and post-repair validation can mutate files. The implemented repair apply scope can snapshot-protect and prepend missing `project/project-state.md` frontmatter for default-path prose operating state, creates missing scaffold directories, creates an absent required `.agents/docmap.yaml` through the create-only `docmap-create` class, creates absent required stable workflow spec fixtures through the create-only `stable-spec-create` class, and performs only the snapshot-protected `.agents/docmap.yaml` route repair for existing docmaps. Existing-content repair requires the repair snapshot contract under `.mylittleharness/snapshots/repair/`, a no-write dry-run snapshot plan, target-bound path checks, manual retention, and manual rollback instructions before any overwrite or normalization can be implemented. `snapshot --inspect` is report-only and may surface product-source snapshot debris, malformed metadata, missing copied bytes, hash/path drift, current-target posture, planned state frontmatter keys, and manual rollback text; it does not make snapshots acceptable product-root content and does not authorize rollback, cleanup, repair, closeout, archive, commit, or lifecycle decision. The implemented snapshot-plan classes are state frontmatter repair and `.agents/docmap.yaml` route repair, which report target files, preview snapshot paths, metadata fields, refusal or skip posture, manual rollback posture, and validation commands; apply creates the real snapshot before prepending state frontmatter or adding missing docmap route entries. Stable spec repair is create-only and uses packaged templates, so it creates no repair snapshot and never rewrites existing spec files.

Worktree coordination keeps source edits and coordination writes in different roles. When `MLH_COORDINATION_ROOT` is set, it must resolve to a live operating root before it is treated as the shared coordination root for claims, run evidence, handoffs, or session records. Product-source fixtures, archive roots, generated-output roots, and ambiguous roots must be refused as shared coordination authority. The edit worktree remains the source-edit target; coordination records may name both `coordination_root` and `edit_worktree_root` as evidence, but those fields cannot create worktrees, clean worktrees, write claims or runs, approve lifecycle movement, stage, commit, push, rollback, release, or open the next plan.

Completion-gate product diff proof is a boundary diagnostic for live operating roots that configure `product_source_root`. The proof compares product-source dirty paths with the active plan's `target_artifacts` and active phase `write_scope`, then reports `clean`, `within-scope`, `out-of-scope`, `disclosed-out-of-scope`, `unavailable`, or `blocked`. `out-of-scope` product diffs block lifecycle acceptance unless same-request closeout fields explicitly leave every out-of-scope path unaccepted through residual risk, carry-forward, or work-result wording. `disclosed-out-of-scope` is still not acceptance of those paths; it only proves the closeout packet did not silently absorb unrelated product edits. Read-only check warnings, packet rows, and product diff status do not revert, split, stage, commit, archive, move lifecycle state, or turn the product source checkout into a live operating root.

External orchestrator workspace preflight keeps provider setup outside MLH authority. `preflight --orchestrator-workspace <path>` is read-only evidence for a candidate disposable worker root. The candidate must be distinct from the live coordination root and the configured product source root, including nested paths inside either root. The report may surface shell, Git, and MLH check commands plus completion-policy warnings for external orchestrators or trackers, but it creates no clone, wrapper, shell, issue, provider state, claim, lifecycle write, commit, cleanup, or worker launch. Passing this preflight cannot approve source edits, roadmap status, lifecycle movement, closeout, archive, staging, commit, push, release, or external orchestrator completion claims.

Multi-agent security diagnostics keep the same root boundary. `check` may report threat-model posture for hooks, dashboards, `mlhd`, dispatchers, adapters, prompt-injection inputs, and secret-leakage risks, but the report is read-only and cannot make the product source checkout a live coordination root. Product-source fixtures, archive roots, generated-output roots, adapter state, caches, logs, local databases, hook targets, MCP servers, dashboards, daemons, and dispatcher processes remain outside product-root operating authority unless a later scoped product plan explicitly creates a bounded reusable implementation.

`detach --dry-run` reports product-source fixture preservation without proposing product-root operating mutation. It writes no marker, metadata toggle, cleanup report, generated output, snapshot, Git state, hook, CI file, package artifact, or workstation state. It treats `.mylittleharness/generated/projection/` as disposable but preserved and previews the live-root marker target. `detach --apply` is marker-only for eligible live operating roots and must not create `.mylittleharness/detach/disabled.json` in the product source checkout.

## Local Versus Reusable

Absolute local paths are operator evidence. They are not public product law and must not be hardcoded into shipped product behavior.

Reusable MyLittleHarness currently supports local-only `bootstrap --package-smoke` verification of the existing stdlib package and `mylittleharness` console script through the stdlib build backend under `build_backend/`, with build artifacts kept outside the product source checkout. It also supports `bootstrap --inspect` as a read-only hidden-help readiness report that separates package smoke, rejected standalone bootstrap apply, publishing, package artifact policy, PATH/user-config mutation, and workstation adoption without performing them. `bootstrap --inspect` may report interpreter context, product package metadata when available, console-script declaration, and PATH discovery for `mylittleharness`, but it does not execute discovered tools or mutate workstation state.

Mutating workstation adoption remains outside generic bootstrap. The implemented user-global exception is the adapter-owned Codex MCP config adoption rail: `adapter --client-config --target mcp-read-projection` is no-write, and `adapter --install-client-config --target mcp-read-projection --dry-run|--apply` may write only the reviewed Codex config target with an idempotent managed server table, backup-before-append behavior, conflict refusal, and no existing-value or secret echo. The implemented project-local exception is the Codex native hook adapter rail: `hooks adapter --client codex --dry-run|--apply --scope project` may write only `.codex/hooks.json` and `.codex/hooks/mylittleharness_session_start.py` in an eligible live operating root. Fresh init/attach leaves project-local Codex hook files unchanged by default, while Codex Trust remains client-owned and user-global Codex config remains explicit. Codex native hooks remain optional non-authoritative sensors and not correctness prerequisites. Those rails prepare optional client helpers; they do not mutate product-root operating memory, start an MCP server, start a listener, create PATH/profile state, approve lifecycle movement, or replace source/`rg` verification. Configurable roots, publishing, broader workstation adoption, root hygiene validation expansion, generated-output boundary expansion, and any future adoption apply behavior still require later scoped product plans with command ownership outside a generic bootstrap apply lane.

## Readiness Boundary

The product source checkout is release-ready only when reusable source, tests, package metadata, product docs, and compatibility fixtures are coherent and the checkout contains no operating memory or runtime debris. Operating evidence for a source release belongs in the operating root, including observed verification, docs decisions, state writeback, residual risk, carry-forward, and commit decisions.

The current `1.0.1` source-release checklist is satisfied by repo-visible source and verification, not by publication. It requires coherent `README.md`, `AGENTS.md`, `docs/...`, `pyproject.toml`, `build_backend/`, `src/mylittleharness/`, `tests/`, compatibility fixtures, package/runtime version agreement, bytecode-disabled tests, read-only health gates, product hygiene, and `bootstrap --package-smoke` from temporary locations outside the product source checkout. Wheel, build, install, and virtual-environment outputs are ephemeral verification artifacts unless a later publication plan accepts a durable artifact and signing policy. Package-index upload, credentials, signing, global installation, PATH/profile/user-config mutation, and mutating workstation adoption are not required for source-release correctness. Standalone `bootstrap --apply` is rejected, and workstation mutation remains outside the product surface.

Optional power-ups must not blur the product/operating boundary. Semantic runtimes, evidence manifests, quality gates, adapters, hooks, CI, publishing helpers, broad workstation adoption helpers, repair expansion, rollback automation, and snapshot cleanup require scoped product contracts before implementation. The implemented Codex MCP client-config rail and project-local Codex hook adapter rail are bounded helper contracts; project-local Codex hook files are not part of the default init/attach scaffold, and user-global config stays outside it. Those contracts must keep files authoritative, define generated-output or helper-state boundaries, name dependency and degraded/offline behavior, and state that helper output cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions.

Future dashboard, daemon, runtime cockpit, dispatcher, MCP/A2A, provider, or hook expansion must keep unsafe defaults disabled: no background server, network listener, provider gateway, credential store, hook installation, worker launch, or runtime cache mutation may appear as a side effect of `check`, `status`, `manifest`, docs inspection, or product-source validation.

## Operating Root Boundary

Creating product docs does not move operation into the product source checkout.

The target shape remains one product serving one explicit target repository.

Workstation mutation is outside the current product surface. Any future adoption behavior requires a later explicit plan that proves:

- start-pass recovery
- product docs and compatibility fixture disposition
- state/memory placement
- validation and hygiene checks
- rollback or recovery posture
- closeout evidence

Until such a plan exists, recover active context from the operating project root and use the product source checkout only as product source/docs/tests/fixtures.
