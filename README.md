# MyLittleHarness

**Repo-visible workflow safety for AI-assisted development.**

MyLittleHarness gives a target repository a small operating layer that a human or coding agent can trust after the chat is gone. It makes the repo answer the questions that usually get lost between sessions: what is active, what can be changed, what was verified, and what still needs a real decision.

It stays intentionally small: a Python CLI and repo templates that make the repository carry the operating truth. It is not an agent framework, orchestrator, coding assistant, task runner, CI replacement, issue tracker, vector-memory product, or hidden control plane.

## Why Use It

AI-assisted work usually fails around the code, not inside the code:

- the current plan lives in a chat thread
- the next agent cannot tell what is active
- generated reports start looking official
- caches quietly become "truth"
- nobody knows what counts as done
- repair actions are too broad
- closeout evidence disappears after the session

MyLittleHarness makes those handoffs less fragile. A file-reading, shell-capable agent can restart from the repo itself, and a human still controls what becomes true.

## What It Does

MyLittleHarness works on a target repository: the repo you want it to service. The product source checkout is only the place you run or develop the tool.

Public GitHub golden path: source, docs, tests, package metadata, and CI evidence.
Product source carries reusable product truth; operating memory belongs in target repositories.

In practice, MyLittleHarness gives you:

- `init` to create the repo-visible operating files for a target repository.
- `check` to report lifecycle, contract, context, routing, and hygiene findings.
- `migrate` to preview or apply compatibility updates for older roots.
- `repair` to preview or apply bounded repair actions through explicit routes.
- `detach` to preview or apply removal of the operating scaffold.
- `status`, `check`, and `intelligence --focus routes` to discover legal routes without growing `AGENTS.md` into a dense manual.
- `evidence --record` as an explicit source-bound record rail; bare `evidence`, `evidence --record`, and `closeout` reports are not approval by themselves.

Route output is advisory only until it is applied. Lifecycle approval still comes from explicit dry-run/apply routes, repo-visible writeback, human review where required, and local Git decisions made outside MLH.

## Quick Start From Source

Use the source checkout to run MLH. Point `--root` at the repository you want MLH to service.

```powershell
cd <mylittleharness-source>
$env:PYTHONPATH = "src"

python -m mylittleharness --root <target-repo> init --dry-run
python -m mylittleharness --root <target-repo> init --apply --project "My Project"
python -m mylittleharness --root <target-repo> check
python -m mylittleharness --root <target-repo> repair --dry-run
```

After installation, the console script is equivalent:

```powershell
mylittleharness --root <target-repo> check
```

The package metadata declares Python `>=3.11`, license `Apache-2.0`, version `1.0.0`, no required runtime dependencies, and the `mylittleharness` console script.

## What First Run Adds

Successful `init --apply`/`attach --apply` creates the neutral `.mylittleharness/project-workflow.toml` manifest and keeps `.codex/project-workflow.toml` only as the legacy fallback manifest when needed.
`.codex/project-workflow.toml` is legacy/client-adapter compatibility, not the core product path.

A target root typically receives a small operating scaffold:

- `AGENTS.md`: compact operator contract for any file-reading, shell-capable agent.
- `.mylittleharness/project-workflow.toml`: neutral lifecycle manifest.
- `project/project-state.md`: current repo-visible operating state.
- optional `project/roadmap.md` sequencing route for accepted work.
- optional `project/verification/*.md` proof/evidence records.
- generated projection/context files under `.mylittleharness/generated/`.

Generated projections accelerate inspection. They do not become authority. If generated cache and source files disagree, source files win and cache can be rebuilt.

## First-Run Operator Path

The first-run path is deliberately short: prove the product checkout can run, then point lifecycle commands at the target repository.

```powershell
$ProductRoot = "<mylittleharness-source>"
$TargetRoot = "<target-repository>"
$env:PYTHONPATH = "src"

python -m mylittleharness --root "$ProductRoot" bootstrap --package-smoke
python -m mylittleharness --root "$TargetRoot" init --dry-run
python -m mylittleharness --root "$TargetRoot" check
python -m mylittleharness --root "$TargetRoot" migrate --dry-run
python -m mylittleharness --root "$TargetRoot" repair --dry-run
python -m mylittleharness --root "$TargetRoot" detach --dry-run
```

Apply modes stay explicit and target-bound. Commands such as `init --apply`, `migrate --apply`, `repair --apply`, and `detach --apply` are available when the dry-run route is reviewed, but they are not required first-contact steps.

## Portable Agent Start Pass

Any file-reading, shell-capable agent can use MyLittleHarness from repo-visible files plus CLI reports.

Start with `AGENTS.md`, `.mylittleharness/project-workflow.toml`, and `project/project-state.md`; use `.codex/project-workflow.toml` only as the legacy fallback manifest when the neutral manifest is absent.

Read `project/implementation-plan.md` only when `plan_status = "active"`. When active, prefer first-class `active_phase` and `phase_status` values over prose inference.

Useful first reads:

- `status`/`check` report a compact lifecycle route table for live roots.
- `project/roadmap.md` sequencing route tracks accepted work when present.
- decision/do-not-revisit records and ADR records preserve durable choices.
- `intelligence --focus routes` prints the same read-only route table.
- start with `dashboard --inspect` or `dashboard --inspect --json` as the cockpit packet when you need a broader root snapshot.
- `adapter --client-config --target mcp-read-projection` prints read-only MCP client wiring.
- `rg` or direct file reads for exact verification remain the final inspection path.

Codex skills, IDE-native rules, MCP clients, shell aliases, preflight wrappers, hooks, and CI may wrap this flow. They are convenience layers, not correctness layers.

## Lifecycle Model

The operating root is the repository being serviced. Repo-visible files remain authoritative. Command output is useful evidence only after accepted state is written back through the appropriate route.

The normal operator loop is:

1. Read the operator contract and state files.
2. Run `check` before mutating repair work.
3. Preview mutating lifecycle actions with `--dry-run`.
4. Apply only the reviewed route with `--apply`.
5. Record verification, docs decision, state transfer, and residual risk in repo-visible state.
6. Use Git for local savepoints when the user or workflow calls for them.

Active plans carry `current-phase-only`, `auto_continue`, and `stop_conditions` so phase movement stays explicit. The `active-plan-auto-continue` route vocabulary exists to make that boundary visible, not to make verification success automatically advance work.

## Trust Boundaries

MyLittleHarness is a local repository tool.

- Core CLI behavior does not need model calls or provider credentials.
- There is no hidden daemon by default.
- Generated cache is disposable.
- Optional helpers cannot approve lifecycle, archive, roadmap, Git, release, provider, or product-diff decisions.
- Project-local hooks, MCP projection helpers, and dashboards are read or signal surfaces until a route writes accepted state.
- Optional wrappers must not store the only copy of accepted decisions, current focus, docs decisions, repair approval, verification, or closeout evidence.

The important promise is not that MLH decides for you. It narrows the path, shows the next reviewed command, and leaves evidence where the next operator can inspect it.

For frequent Codex work, project-local Codex native hooks are recommended early-warning sensors. Install them with `hooks adapter --client codex --dry-run|--apply --scope project` after the first successful check. They surface route context and unsafe shortcuts at tool time, but they remain optional non-authoritative sensors and not correctness prerequisites. Codex native hooks stay optional non-authoritative sensors outside the correctness path.

## Docs Decision

Closeout records a `docs_decision` as `updated`, `not-needed`, or `uncertain`.

Use `updated` when the change alters behavior, CLI usage, configuration, setup, contract meaning, permissions, output shape, UX/copy, terminology, rollout, migration, or other user-facing docs meaning. Use `not-needed` when the change is internal and docs are unaffected. Use `uncertain` only for provisional handoff.

`audit-links` and `check` can route attention, but no Codex skill or generated docs-impact report is required for v1.

## Diagnostics

Routine `check` stays compact. It reports primary instruction-surface size warnings and root-level lifecycle findings first.

Deeper section-size detail remains in advanced `context-budget` and `doctor` diagnostics. `check --deep` adds links, context, hygiene, and report-only grain diagnostics. Grain diagnostics inspect active-plan slice size.

For route review, use `status`, `check`, or `intelligence --focus routes`. For broader drift review, look at link/docmap/stale-root/rule-context/remainder drift only when the current task calls for it.

## Optional Integrations

Optional helpers are there to reduce repeated reading, not to move authority out of the repository.

- `dashboard --inspect` gives a broad root packet.
- `mlhd` can keep local projection cache warm.
- MCP projection tools expose read-only navigation data.
- Project-local Codex hooks can surface pre-tool and post-tool context.
- CI may run `check` or tests.

All of these are wrappers around repo-visible state and CLI reports.

## Local Release Posture

The current product posture is a local `1.0.0` release candidate. The release confidence claim is documentation-and-verification based, not a public publication claim.

The local release checklist is:

- package metadata and runtime version agree on `1.0.0`
- `bootstrap --package-smoke` passes from temporary source/build/install locations outside the product source checkout
- Wheel, build, and install artifacts are verification outputs only
- `bootstrap` rejects standalone `bootstrap --apply`
- owner approval is still required before package-index publication, signed artifact release, global installation, push, tag, artifact upload, or public release announcement

## Development

From the product checkout:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -m mylittleharness --root . check --quick
```

Use focused tests for bounded edits, then broader verification when the touched surface has wider behavior. Keep package, build, and install artifacts out of the product source tree unless a verified packaging route creates temporary outputs outside the checkout.

## Docs Map

- `docs/README.md`: product documentation index and release posture.
- `docs/security.md`: local trust and security boundaries.
- `docs/reference/command-surface.md`: command overview.
- `docs/specs/`: product behavior, lifecycle, and boundary specs.
- `project/specs/workflow/`: workflow capability and artifact model specs.

## Status

MyLittleHarness is best described as a repo-visible workflow safety utility for solo-first AI-assisted development. Use it when the repository needs to remember current focus, lifecycle gates, verification, docs decisions, and closeout evidence in a form the next human or agent can inspect without relying on chat history.
