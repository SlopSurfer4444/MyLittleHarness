# MyLittleHarness Operator Contract

## Repo-Local Posture

- Treat this directory as the MyLittleHarness product repository: source, tests, docs, package metadata, and compatibility fixtures.
- Recover active task context from the repository named by the current task before non-trivial product work.
- MyLittleHarness attaches to and inspects an explicit target repository supplied by the operator or CLI command.
- Treat `workflow-core` as a compatibility label in fixture manifests and operator wording only. It is not the architectural baseline for MyLittleHarness.
- Keep `.mylittleharness/project-workflow.toml`, `.agents/docmap.yaml`, `project/project-state.md`, and `project/specs/workflow/**` as product compatibility fixtures only while the CLI/tests need a workflow-shaped target root.
- Treat legacy `.codex/project-workflow.toml` as target-root fallback/migration compatibility only, not the product fixture path.
- Do not change PATH, user config, installed skills, package archives, attach/install distribution, MCP, hooks, runtime helpers, or workstation state from this product tree.
- Do not create or import active implementation plans, archived plans, research/history/raw intake, archive-under-study material, candidate source packs, old migration evidence, package zips, broad research corpus, runtime debris, reports, logs, caches, generated validation artifacts, local databases, or pycache into this product tree.

## Start Pass

For non-trivial product work in this directory:

1. Recover task context from the repository named by the current request.
2. Read this `README.md` and `AGENTS.md`.
3. Read the relevant `src/`, `tests/`, and product docs for the product change.
4. Read `.agents/docmap.yaml`, `.mylittleharness/project-workflow.toml`, `project/project-state.md`, or `project/specs/workflow/*.md` only when changing CLI validation behavior or compatibility fixtures; read legacy `.codex/project-workflow.toml` only when changing legacy fallback or migration behavior.
5. When validating operating-root navigation behavior, prefer the shipped dashboard agent packet, intelligence query, and MCP read-projection paths before scattered manual route walking; keep `rg` for exact verification.

There should be no active `project/implementation-plan.md` in this repository.

## Fixture Boundary

- `project/project-state.md` is a product compatibility fixture, not writable operating memory.
- Keep `.agents/docmap.yaml` conservative and limited to product entrypoints plus compatibility fixtures.
- Keep stable workflow fixture rules under `project/specs/workflow/**` only while the CLI/tests need them.
- Do not write active task memory, plans, research, or archive history into this product repository.

<!-- BEGIN workflow-core v1 -->
## Workflow Core Compatibility

- This compatibility block is a fixture contract for CLI/tests, not permission to store live workflow memory here.
- First recover operating context from the task's explicit operating root or target root; read `project/project-state.md` here only as fixture data.
- Keep the start pass cheap: read the implementation plan file only when `plan_status = "active"` or when the user explicitly asks about plan, phase, or closeout.
- Do not create `project/implementation-plan.md` here. Current product-development plans live in the task repository; shipped MyLittleHarness attaches directly to a target repository.
- Keep `project/project-state.md` as fixture metadata only.
- Keep stable fixture docs under `project/specs/workflow/**`.
- Run docs routing only for mutating tasks with docs, contract, setup, rollout, terminology, or other user-visible impact.
- Do not perform operational lifecycle decision from this product tree without a separate explicit decision or plan.
- On closeout, use manual commit policy and record skipped commit decisions when this directory is not a git worktree.
- If the compatibility fixture contract is missing or broken, report that it needs repair from the operating project root instead of silently installing or adopting workstation tooling.
<!-- END workflow-core v1 -->
