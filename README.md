# MyLittleHarness

**Repo-visible workflow safety for AI-assisted development.**

MyLittleHarness turns a repository into the place where AI-assisted work can safely continue. It gives humans and coding agents the same durable answers: what is active, what is allowed to change, what was verified, what is still only a proposal, and what should happen next.

The point is simple: stop making the chat thread carry the project memory.

MLH keeps the operating truth beside the code, in files the next agent can read, diff, verify, and commit. That means less archaeology, fewer accidental shortcuts, clearer handoffs, and a much higher chance that a simple task can grow into a careful multi-step implementation without turning into mystery state.

It stays intentionally small: a local Python CLI plus repo templates and optional helpers. It is not an agent framework, orchestrator, coding assistant, CI replacement, issue tracker, vector-memory product, or hidden control plane.

## The Problem

AI coding sessions are powerful, but long work usually breaks around coordination:

- the real plan is trapped in yesterday's chat
- the next agent cannot tell which files are authority and which are notes
- generated reports start sounding like approval
- repair commands become too broad because the legal route is unclear
- verification gets mentioned in prose but not preserved as evidence
- "done" means different things to the human, the agent, and Git
- a new session spends its best thinking re-learning the same context

That is why agent throughput often collapses exactly when a task becomes valuable: the work needs continuity, but the memory is not in the repository.

## What Changes With MLH

With MyLittleHarness, the repo starts answering operational questions directly.

| Without MLH | With MLH |
| --- | --- |
| "What were we doing?" lives in chat history. | Current focus lives in repo-visible state. |
| The agent guesses whether a plan is active. | Active plan and phase are explicit. |
| Dry-run output can look like permission. | Route output stays advisory until applied. |
| Verification is easy to lose. | Proof and residual risk are written back. |
| Broad cleanup feels tempting. | Mutating routes are previewed before apply. |
| The next session starts cold. | A file-reading agent can restart from the repo. |

The practical effect is not magic autonomy. It is better ground under the agent's feet. MLH lets the human say a higher-level goal while the agent has enough local structure to research, plan, implement, verify, close out, and hand off without inventing its own lifecycle.

## The Core Idea

MyLittleHarness services a target repository: the repo where work is happening. The product source checkout is only where the tool itself is developed or run.

Public GitHub golden path: source, docs, tests, package metadata, and CI evidence.
Product source carries reusable product truth; operating memory belongs in target repositories.

Accepted state lives in ordinary repo-visible files. Commands can inspect, propose, preview, and apply, but the repository remains the shared surface that humans, agents, hooks, tests, and Git can all inspect. The evidence rail is explicit: `evidence --record` creates source-bound records, while bare `evidence`, `evidence --record`, and `closeout` reports are not approval by themselves.

## What MLH Leaves In A Repo

After MLH is attached to a target root, the repo gets a compact operating layer:

- `AGENTS.md`: a short contract any file-reading, shell-capable agent can follow.
- `.mylittleharness/project-workflow.toml`: the neutral lifecycle manifest.
- `project/project-state.md`: current operating state and continuation facts.
- optional `project/roadmap.md` sequencing for accepted work.
- optional `project/verification/*.md` proof/evidence records.
- generated projection/context files under `.mylittleharness/generated/`.

Generated projections make inspection faster. They do not become authority. If cache and source disagree, source wins.

Successful `init --apply`/`attach --apply` creates the neutral `.mylittleharness/project-workflow.toml` manifest and keeps `.codex/project-workflow.toml` only as the legacy fallback manifest when needed. `.codex/project-workflow.toml` is legacy/client-adapter compatibility, not the core product path.

## Why Agents Get Better

MLH does not make an agent smarter by adding secret state. It removes ambiguity the agent would otherwise spend tokens and risk on.

- It tells the agent where to start.
- It separates proposal, dry-run, apply, verification, and closeout.
- It gives old work a durable home instead of making every chat a memory silo.
- It makes unsafe shortcuts visible before they become repo damage.
- It lets future sessions inherit decisions without trusting private traces.
- It turns "please continue" into a bounded continuation problem instead of a reconstruction problem.

That is the productivity lift: the agent can spend more effort on the actual code and less on guessing the workflow.

## Trust Boundaries

MyLittleHarness is a local repository tool.

- Core CLI behavior does not need model calls or provider credentials.
- There is no hidden daemon by default.
- Generated cache is disposable.
- Optional helpers cannot approve lifecycle, archive, roadmap, Git, release, provider, or product-diff decisions.
- Project-local hooks, MCP projection helpers, dashboards, and warmed caches are signal surfaces until a route writes accepted state.
- Optional wrappers must not store the only copy of accepted decisions, current focus, docs decisions, repair approval, verification, or closeout evidence.

Route output is advisory only until it is applied. Lifecycle approval still comes from explicit dry-run/apply routes, repo-visible writeback, human review where required, and local Git decisions made outside MLH.

For frequent Codex work, project-local Codex native hooks are recommended early-warning sensors. Install them with `hooks adapter --client codex --dry-run|--apply --scope project` after the first successful check. They surface route context and unsafe shortcuts at tool time, but they remain optional non-authoritative sensors and not correctness prerequisites. Codex native hooks stay optional non-authoritative sensors outside the correctness path.

## Quick Start From Source

Run MLH from the product checkout and point `--root` at the repository you want MLH to service.

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

The package metadata declares Python `>=3.11`, license `Apache-2.0`, version `1.0.1`, no required runtime dependencies, and the `mylittleharness` console script.

## First-Run Operator Path

The first run should prove two things: the source checkout can execute, and the target repository can be inspected without surprise writes.

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

Apply modes stay explicit and target-bound. Commands such as `init --apply`, `migrate --apply`, `repair --apply`, and `detach --apply` are available when the dry-run route is reviewed, but they are not required first-contact steps. If `repair --dry-run` reports target-bound changes needed for a fresh root, run `repair --apply` after review and rerun `check` or `check --quick` before treating first contact as clean.

## Agent And Operator Details

Most people do not need to operate the lifecycle fields directly. They exist so agents and tools can tell the difference between accepted state, provisional state, and evidence.

Any file-reading, shell-capable agent can use MyLittleHarness from repo-visible files plus CLI reports. Start with `AGENTS.md`, `.mylittleharness/project-workflow.toml`, and `project/project-state.md`; use `.codex/project-workflow.toml` only as the legacy fallback manifest when the neutral manifest is absent. Read `project/implementation-plan.md` only when `plan_status = "active"`; when it is active, `active_phase` and `phase_status` are the first-class continuation facts.

`status`/`check` report a compact lifecycle route table for live roots. The `project/roadmap.md` sequencing route, decision/do-not-revisit records, and ADR records preserve durable intent. `intelligence --focus routes` prints the same read-only route table, and agents can start with `dashboard --inspect` or `dashboard --inspect --json` as the cockpit packet when they need a broader snapshot. `adapter --client-config --target mcp-read-projection` exposes read-only projection wiring. `rg` or direct file reads for exact verification remain the final source path.

`status`, `check`, and `intelligence --focus routes` give compact route discovery without growing `AGENTS.md` into a dense manual. Codex skills, IDE-native rules, MCP clients, shell aliases, preflight wrappers, hooks, and CI may wrap this flow, but they are not the correctness path.

Active plans carry `current-phase-only`, `auto_continue`, and `stop_conditions` so phase movement stays explicit. The `active-plan-auto-continue` route vocabulary exists to make that boundary visible, not to make verification success automatically advance work.

MLH also records docs impact during closeout so user-facing changes do not silently drift away from docs. The agent-facing values are `updated`, `not-needed`, and `uncertain`; impact includes behavior, CLI usage, configuration, setup, contract meaning, permissions, output shape, UX/copy, terminology, rollout, migration, or similar user-facing docs meaning. `audit-links` and `check` can route attention, but no Codex skill or generated docs-impact report is required for v1.

## Diagnostics

Routine `check` stays compact. It reports primary instruction-surface size warnings and root-level lifecycle findings first.

Deeper section-size detail remains in advanced `context-budget` and `doctor` diagnostics. `check --deep` adds links, context, hygiene, and report-only grain diagnostics when the current task needs that detail. Grain diagnostics inspect active-plan slice size. Look at link/docmap/stale-root/rule-context/remainder drift only when the task calls for it.

## Optional Integrations

Optional helpers reduce repeated reading. They do not move authority out of the repository.

- `dashboard --inspect` gives a broad root packet.
- `mlhd` can keep local projection cache warm.
- MCP projection tools expose read-only navigation data.
- Project-local Codex hooks can surface pre-tool and post-tool context.
- CI may run `check` or tests.

## Local Release Posture

The current product posture is a public GitHub source release at `1.0.1`. The release confidence claim is documentation-and-verification based; package-index publication, signed binary artifacts, global workstation adoption, and hosted services remain separate future distribution steps.

See `CHANGELOG.md` and `RELEASE_NOTES.md` for the `1.0.1` release summary, verification expectations, and owner-approval boundary.

The local release checklist is:

- package metadata and runtime version agree on `1.0.1`
- `bootstrap --package-smoke` passes from temporary source/build/install locations outside the product source checkout
- Wheel, build, and install artifacts are verification outputs only
- `bootstrap` rejects standalone `bootstrap --apply`
- owner approval is still required before package-index publication, signed binary artifact release, global installation, artifact upload, hosted-service launch, or future public release announcement

## Development

From the product checkout:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -m mylittleharness --root . check --quick
```

Use focused tests for bounded edits, then broader verification when the touched surface has wider behavior. Keep package, build, and install artifacts out of the product source tree unless a verified packaging route creates temporary outputs outside the checkout.

## Docs Map

- `CHANGELOG.md`: public release change history.
- `RELEASE_NOTES.md`: `1.0.1` release notes and owner-approval boundary.
- `docs/README.md`: product documentation index and release posture.
- `docs/security.md`: local trust and security boundaries.
- `docs/reference/command-surface.md`: command overview.
- `docs/specs/`: product behavior, lifecycle, and boundary specs.
- `project/specs/workflow/`: workflow capability and artifact model specs.

## Status

MyLittleHarness is best described as a repo-visible workflow safety utility for solo-first AI-assisted development. It is for people who want AI agents to work in longer arcs without losing the plot, overstating approval, or hiding the evidence that makes the next step safe.
