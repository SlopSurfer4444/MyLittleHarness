# MyLittleHarness

**Repo-native memory and safety rails for AI-assisted software work.**

> Stop making your AI agent remember the project. Let the repository remember.

MyLittleHarness helps AI coding agents understand a repository without depending on chat history, hidden state, or vibes.

It keeps the project's operating truth in visible files: current focus, active plans, roadmap, repair boundaries, verification, closeout evidence, archives, and generated projections.

The goal is simple:

> AI agents should be able to resume work from the repository itself, and humans should still control what becomes true.

---

## Why this exists

AI coding tools are good at producing code.

The hard part is everything around the code:

- the current plan lives in a chat thread
- the next agent cannot tell what is active
- generated reports start looking official
- caches quietly become "truth"
- nobody knows what counts as done
- repair actions are too broad
- closeout evidence disappears after the session

MyLittleHarness gives the repository a durable operating layer so agents can work with clearer rails.

It does **not** make the model magically smarter.

It makes the workspace easier to operate.

- Less context reconstruction.
- Less task-selection ambiguity.
- Less scope creep.
- Faster verification.
- Better resumability.
- Safer autonomous loops.

---

## What it is

MyLittleHarness is a small CLI and file layout that turns a repository into a better workspace for AI-assisted development.

It answers questions like:

- What is the current project state?
- Is there an active plan?
- What should an agent read before acting?
- Which files are authoritative?
- Which files are generated cache?
- What repair is safe to preview?
- What counts as closeout evidence?
- Can another agent resume from the repo alone?

Core idea:

> Files hold authority. Metadata routes. Git records history. Generated projections accelerate. Diagnostics warn. Mutation stays explicit and fail-closed.

---

## What it is not

MyLittleHarness is **not**:

- an AI agent framework
- an orchestrator
- a workflow runner
- a daemon
- a scheduler
- a dashboard
- a CI replacement
- a hidden control plane
- a mandatory MCP, IDE, hook, or CI dependency

Your agent, editor, orchestrator, or shell workflow still decides what to do.

MyLittleHarness defines what the repository is allowed to treat as true.

---

## The short version

Without MyLittleHarness:

```text
agent -> chat memory -> guesses current state -> edits repo -> writes report somewhere
```

With MyLittleHarness:

```text
agent -> repo-visible state -> active plan -> bounded action -> verification -> closeout evidence
```

The repository becomes the handoff surface.

A new agent can enter later and recover the working context without needing the previous chat.

---

## Install / run from source

From a checkout of this repository:

```bash
export PYTHONPATH=src
python -m mylittleharness --root /path/to/target check
```

If installed as a console script:

```bash
mylittleharness --root /path/to/target check
```

MyLittleHarness uses an explicit `--root` so the target repository is always named.

---

## First run

Attach MyLittleHarness to a target repository:

```bash
export PYTHONPATH=src

TargetRoot="/path/to/target"

python -m mylittleharness --root "$TargetRoot" init --dry-run
python -m mylittleharness --root "$TargetRoot" init --apply --project "My Project"
python -m mylittleharness --root "$TargetRoot" check
```

Preview repair posture:

```bash
python -m mylittleharness --root "$TargetRoot" repair --dry-run
```

Preview detach posture:

```bash
python -m mylittleharness --root "$TargetRoot" detach --dry-run
```

Apply modes are intentionally explicit. Prefer dry-run first.

---

## Main commands

### `init`

Creates the MyLittleHarness operating scaffold inside a target repository.

Use it when you want the repo to start carrying its own AI-work state.

```bash
mylittleharness --root /path/to/target init --dry-run
mylittleharness --root /path/to/target init --apply --project "My Project"
```

### `check`

Runs read-only orientation and diagnostics.

Use it as the first command for a new session, new agent, or suspicious repo state.

```bash
mylittleharness --root /path/to/target check
```

### `repair`

Previews or applies bounded repairs.

Repair is not a "fix everything" button. It is designed to stay explicit and narrow.

```bash
mylittleharness --root /path/to/target repair --dry-run
```

### `detach`

Creates a marker-only detach posture without treating generated artifacts as authority.

```bash
mylittleharness --root /path/to/target detach --dry-run
```

Advanced commands exist for recovery and deeper lifecycle work. Start with [`docs/README.md`](docs/README.md), [`docs/specs/attach-repair-status-cli.md`](docs/specs/attach-repair-status-cli.md), and [`docs/specs/metadata-routing-and-evidence.md`](docs/specs/metadata-routing-and-evidence.md) when you need the full command surface.

---

## Product repo vs target repo

MyLittleHarness keeps a strict split:

```text
MyLittleHarness product repo
  reusable source code
  tests
  package metadata
  product docs

target repository
  project state
  active plans
  roadmap
  verification
  closeout evidence
  archives
  generated projections
```

This repository is the product source.

Your application repository is the target.

The target owns its own operating memory.

---

## Generated projections are disposable

MyLittleHarness may create generated projection files under:

```text
.mylittleharness/generated/projection/
```

These files can accelerate navigation, route discovery, backlinks, relationships, and search.

They are **not** authority.

Deleting generated projection output must not change what the repository is allowed to treat as true.

- Generated state is build-to-delete.
- Refreshes preserve old-good artifacts and indexes when a publish fails.
- Reports are diagnostics, not decisions.
- Snapshots are safety evidence, not authority.

---

## Why agents get more efficient

MyLittleHarness improves agent performance by reducing operational ambiguity.

It gives agents durable answers to questions that otherwise burn context and cause mistakes:

```text
What are we doing?
What is active?
What is blocked?
What is accepted?
What is generated?
What can be repaired?
What requires human review?
What counts as evidence?
Where should closeout go?
```

That means an agent can spend more effort on the actual task instead of reconstructing project process from chat history.

The gain is not magic.

It is better workspace geometry.

---

## Safety model

MyLittleHarness is built around a few safety rules:

- authority lives in repo-visible files
- generated files are subordinate
- diagnostics do not approve mutation
- repair should be previewed before apply
- apply commands name the target root
- lifecycle movement is explicit
- verification success does not silently authorize the next phase
- humans keep the final say

Any shell-capable or file-reading agent can use the repo-visible state.

No hidden service is required.

---

## First-Run Operator Path

```bash
python -m mylittleharness --root $ProductRoot bootstrap --package-smoke
python -m mylittleharness --root $TargetRoot init --dry-run
python -m mylittleharness --root $TargetRoot check
python -m mylittleharness --root $TargetRoot repair --dry-run
python -m mylittleharness --root $TargetRoot detach --dry-run
```

Apply modes stay explicit and target-bound after dry-run review. `bootstrap --inspect`, `tasks --inspect`, hooks, CI, MCP clients, semantic providers, global installation, and workstation adoption can help later; they are not required first-contact steps.

Any file-reading, shell-capable agent can use MyLittleHarness from repo-visible files plus CLI reports. Start with `AGENTS.md`, `.codex/project-workflow.toml`, and `project/project-state.md`; read `project/implementation-plan.md` only when `plan_status = "active"` or the user asks about plan, phase, or closeout. When a plan is active, `active_phase` and `phase_status` are first-class continuation pointers. `status`/`check` report a compact lifecycle route table for live roots, and `intelligence --focus routes` prints the same read-only route table for the `project/roadmap.md` sequencing route, decision/do-not-revisit records, ADR records, and optional `project/verification/*.md` proof/evidence records. For fuzzy repo, lifecycle, impact, or product-source navigation, start with `dashboard --inspect` or `dashboard --inspect --json` as the cockpit packet, then use `intelligence --query`, optional `adapter --client-config --target mcp-read-projection`, and `rg` or direct file reads for exact verification. Codex skills, IDE-native rules, MCP clients, shell aliases, preflight wrappers, hooks, and CI may wrap this flow, but no Codex skill or generated docs-impact report is required for v1.

Treat `dashboard --inspect` output as a read-only projection: it starts no daemon, listener, hook, dispatcher, worker, cache refresh, or product mutation; it cannot approve lifecycle movement, repair, archive, staging, commit, push, release, roadmap status, or product-diff acceptance; and any `mlhd` runtime/cache fields are disposable diagnostics only. The JSON payload includes source refs and a `nextLegalDryRun` candidate so an agent can see the next legal preview route, but the dashboard does not approve running or applying that route.

`meta-feedback` is opt-in and is not part of the default start pass. Keep opt-in `meta-feedback` for concrete MLH rough edges after the active task is safe.

---

## Diagnostics And Closeout

Docs decisions use the portable vocabulary `updated`, `not-needed`, or `uncertain`. Consider docs when behavior, CLI usage, configuration, setup, contract meaning, permissions, output shape, UX/copy, terminology, rollout, migration, `audit-links`, or `check` output changes.

bare `evidence`, `evidence --record`, and `closeout` are separate surfaces: bare `evidence` is a terminal-only read-only report, while `evidence --record` is an explicit source-bound record rail. Route output is advisory only, and diagnostics must not store the only copy of accepted decisions, current focus, docs decisions, repair approval, verification, or closeout evidence.

`check` keeps common drift compact: primary instruction-surface size warnings, link/docmap/stale-root/rule-context/remainder drift, route metadata, and lifecycle posture stay in the report. Deeper section-size detail remains in advanced `context-budget` and `doctor` diagnostics. `check --deep` adds links, context, hygiene, and report-only grain diagnostics. Grain diagnostics inspect active-plan slice size. `active-plan-auto-continue`, current-phase-only, `auto_continue`, and `stop_conditions` keep phase movement explicit until a writeback or transition rail changes lifecycle state.

---

## Local Release Checklist

The local release checklist is:

- package metadata and runtime version agree on `1.0.0`
- `bootstrap --package-smoke` passes from temporary source/build/install locations outside the product source checkout
- Wheel, build, and install artifacts are verification outputs only
- the CLI rejects standalone `bootstrap --apply`

---

## Development

This package is intentionally stdlib-first.

Baseline:

- Python `>=3.11`
- no runtime dependencies
- console script: `mylittleharness`

Useful local checks:

```bash
python -m unittest discover -s tests
python -m mylittleharness --root . check
python -m mylittleharness --root . bootstrap --package-smoke
```

---

## Status

MyLittleHarness is currently a local `1.0.0` release-candidate posture.

That means:

- the package version is `1.0.0`
- the repo is structured as reusable product source
- local verification and package-smoke flows exist
- this is not a claim of package-index publication
- this is not a claim of production adoption
- this is not a workstation mutation tool

---

## When to use it

Use MyLittleHarness if:

- you work with AI coding agents across multiple sessions
- you want repo-native handoff instead of chat-only memory
- you need active plans and closeout evidence to survive context resets
- you want generated reports and caches to stay non-authoritative
- you want bounded repair instead of broad autonomous cleanup
- you want humans to stay in control while agents move faster

---

## Mental model

MyLittleHarness is a harness, not a horse.

It does not replace your agent.

It gives the agent something safer to pull against.
