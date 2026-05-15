# Workflow Verification Anchors and Closeout Spec

> Product fixture note: This spec is retained as a product compatibility fixture for CLI/tests. Live workflow authority, plans, research, and memory remain in the target repository; legacy reference material is opened only for a named blocker.

## Purpose

This spec defines how the workflow should place verification anchors, what evidence each anchor must produce, and how closeout should remain explicit and cheap-first.

It exists to:
- verify by meaningful block, not by raw phase count
- prevent both over-verification and phantom completion
- keep closeout inspectable
- avoid hidden escalation from cheap diagnostics into repair or control-plane behavior

This spec does not require a separate verification runtime or background automation.

## MyLittleHarness Core v0 Verification Posture

MyLittleHarness Core v0 completion is evidence-based and repo-visible. A phase, block, or plan is complete only when the evidence names the changed artifact or concise diff summary, the verification method, the observed result, and residual risk or explicit skip rationale.

Core v0 verification must remain valid without Git, GitHub, MCP, hooks, browser state, IDE state, candidate tooling, or external services. When the repository is not a git worktree, closeout records `commit_decision = skipped` with `non-git repo` or policy rationale instead of inventing commit evidence.

Boundary change from a compatibility-labeled harness to MLH Core is not performed by ordinary contract closeout. A Core v0 plan may produce a readiness checklist, but any actual root-boundary change requires a later explicit decision or plan.

For reusable product work, closeout writes working evidence, state writeback, plan archive, and carry-forward decisions in the operating project root, with the product checkout named only as the target root when source/tests/product docs changed there. Closeout must not create archived plans, research history, or workflow operation residue inside the product source tree.

## Authoritative Inputs

- `project/specs/workflow/workflow-artifact-model-spec.md`
- `project/specs/workflow/workflow-plan-synthesis-spec.md`
- base workflow closeout rules from `.codex/project-workflow.toml` and the active workflow contract

## Verification Block Model

A verification block is a continuous group of phases or steps that still shape one intermediate artifact or one cheap, reversible subproblem.

The anchor belongs after the block when the work now makes a new claim that can be checked against reality.

## Default Anchor Types

### Plan anchor

When:
- after research, option synthesis, and draft plan formation
- before irreversible implementation branching

Checks:
- scope clarity
- conflicts with stable memory or stable specs
- missing constraints
- dependency fan-in
- validation and acceptance shape

Output:
- confirmed plan direction
- explicit conflict list if canonical docs and the draft direction disagree

### Integration anchor

When:
- after an implementation block
- before external integration, interface rollout, or high-cost follow-on work

Checks:
- contract consistency
- tests or equivalent verification evidence
- externally visible behavior
- migration or compatibility risk when relevant
- docs impact when relevant
- when the block claims handoff readiness, whether the evidence is landed stable contract or still only synthesis-ready input
- whether deferred, optional-next, later-extension, open, or needs-more-research lanes remain explicit instead of being silently promoted

Output:
- verified block result
- explicit handoff posture when the block prepares successor rollout
- or explicit repair / revisit branch

### Closeout anchor

When:
- before phase closeout, plan archive, or final delivery

Checks:
- docs decision
- state writeback
- verification completeness or explicit skip
- promotion candidates
- carry-forward decision for unresolved, deferred, open, and needs-more-research lanes
- unresolved risks
- archive or carry-forward decision

Output:
- closeout summary
- explicit commit decision or commit skip reason when applicable

## Anchor Placement Heuristics

Insert a verification anchor when at least one condition is true:

- the next block depends on outputs from more than one prior phase
- a contract, interface, policy, or external behavior boundary has been crossed
- the next work is expensive, long-running, or hard to roll back
- uncertainty has accumulated enough that checking now is cheaper than carrying risk forward
- the workflow is transitioning `design -> execution`, `execution -> integration`, or `integration -> closeout`
- a demoable or user-visible slice has just been completed

## Skip Heuristics

Do not insert a new anchor when both conditions are true:

- neighboring phases still shape the same artifact or the same cheap reversible subproblem
- verification would not change the route, scope, or risk posture of the next step

For low-risk trivial work, the first anchor may be skipped when all of these are true:

- the diff is narrow
- rollback is cheap
- there is a direct oracle
- no interface or policy boundary changed
- the next step does not depend on a multi-phase fan-in

## Evidence Requirements

No block should be treated as complete without local evidence.

Minimum evidence for a verified block:
- changed artifact path or a concise diff summary
- verification method
- observed result
- residual risks or explicit skip rationale

For docs-only work, evidence may be:
- landed spec paths
- explicit consistency review against authoritative inputs
- identified follow-on implementation gates
- explicit statement of whether the block landed stable canon or only prepared handoff inputs
- named carry-forward destinations for any deferred or unresolved lanes

## Handoff Evidence Discipline

A spec-ready synthesis artifact may prove that a contract is ready to land, but it does not prove that stable canon already changed.

If a workflow block claims landed contract, verification should point to normative wording in the stable specs themselves.

If the work stops at synthesis or carry-forward preparation, verification should report that posture explicitly instead of implying rollout completion.

For code work, evidence should prefer deterministic checks such as:
- tests
- smoke runs
- schema or contract validation
- structured command output

Route lifecycle states are verification cues, not completion proof. `draft`, `accepted`, `synced`, `partially_verified`, `stale`, `drift_detected`, `superseded`, and `archived` may help `check` explain posture and next safe commands, but a phase or plan is complete only when closeout evidence records the changed artifact, verification method, observed result, docs decision, residual risk, and explicit lifecycle writeback. Moving a route from stale or drift-detected to synced requires a human-gated amendment path; read-only diagnostics cannot perform that amendment.

For parallel or external-agent work, manifest fields are verification inputs rather than runtime proof. `parallelism_class`, `claim_scope`, `merge_policy`, `fan_in_gate`, role `isolation_contract`, and `fan_in_output_required` should help decide what evidence a worker must return before fan-in. They do not prove that fan-in happened, approve lifecycle writes, or permit direct worker edits to shared lifecycle routes.

Work claims, handoff packets, approval packets, and review tokens are verification and fan-in aids, not completion proof by themselves. A work claim may show route, path, or resource ownership and stale/overlap posture; a handoff packet may show allowed routes, write scope, stop conditions, context budget, required outputs, evidence refs, approval refs, and claim refs; an approval packet may show a human-gate request or decision; a review token may show that the reviewed inputs still match. A phase or plan is complete only when the closeout evidence also records what changed, how it was checked, observed results, docs decision, residual risk, and explicit lifecycle writeback.

Approval relay adapter reports are verification aids only when they prove that approval packet refs are readable and serializable for transport. Their `delivery_attempted=false` preview, packet hashes, channel labels, and recipient labels cannot count as human approval, lifecycle authority, closeout evidence by themselves, or proof that an external recipient acted.

Reconcile and agent-focus diagnostics are verification aids, not repair. `reconcile` and `check --focus agents` may report route, source, and evidence fingerprints; classify posture as `synced`, `partially_verified`, `stale`, `drift_detected`, or `unassessed`; and surface stale claims, stale approval packets, missing run evidence, no-progress residue, abandoned worktree references, and worker-space residue. Their proposals remain human-gated and cannot release claims, delete worker outputs, rewrite authority, archive a plan, change roadmap status, stage, commit, or approve lifecycle movement.

## Verification Modes

The workflow recognizes three verification modes:

- `self-check`
  Use when the same worker can validate a bounded low/medium-risk block with direct evidence.
- `independent review`
  Use when fresh context is likely to catch contract drift, integration risk, or closeout mistakes that the implementation pass may miss.
- `standalone verdict`
  Use when verification evidence needs its own durable artifact because the block is risky, externally visible, or audit-heavy.

The mode should match the risk and the audit need. Do not escalate every change into independent review.

## Separate Verification Artifacts

Keep verification inside the active plan by default.

Create a separate verification artifact only when one or more conditions are true:

- the change is medium/high-risk
- the change affects an external contract, interface, or policy
- the verification trail is too large or too important to bury inside the plan
- a later audit will need a standalone verdict

If a separate verification artifact is not justified, do not create one just for symmetry.

## Phantom Completion Guard

The workflow must not mark a block, phase, or plan as complete unless there is explicit evidence or an explicit verified skip.

That means:
- no silent conversion of intent into completion
- no closeout based only on chat confidence
- no phase-complete status without a checkable artifact result

Hooks or helper scripts may assist, but correctness must not depend on hidden hooks.

The first-contact hook event is verification context only. `hooks --run session-start` and its JSON payload can show the active lifecycle posture, next legal dry-run candidate, and generated projection/SQLite cache posture before an agent starts work, but that output is not proof that a phase is complete, not proof that docs are updated, and not approval for lifecycle movement, archive, roadmap done-status, Git actions, dispatcher work, provider routing, product-diff acceptance, staging, commit, push, or release. Closeout evidence must still name changed artifacts, verification commands, observed results, docs decision, state writeback, residual risk, and commit decision.

## Fresh-Context Review and Worktree Use

Fresh-context review is recommended for:
- risky integration blocks
- externally visible contract or policy changes
- closeout passes where an independent reader is likely to catch unresolved drift

Worktree use is allowed only as an opt-in isolation tool when:
- the review truly benefits from isolation
- the work is risky enough to justify the extra operational cost
- the workflow can keep the path explicit and understandable

The workflow must not make worktree-heavy review the default path. Broad worktree swarms, hidden reviewer daemons, and automatic parallel reviewer orchestration remain out of scope for the current workflow.

## Cheap-First Verification Boundaries

- Cheap read-only context and status checks should happen before expensive verification when they can narrow the next action.
- Failed cheap diagnostics may produce the next recommended action, but they must not silently escalate into broad verification or repair.
- Repair and other mutating recovery remain explicit.
- Verification itself must not become a hidden orchestration layer.

## Closeout Contract

Before closeout, the workflow must surface this summary:

- `worktree_start_state`
- `task_scope`
- `docs_decision`
- `state_writeback`
- `verification`
- `commit_decision`

Closeout ordering remains:

1. collect outcome and smallest useful evidence
2. finish docs decision
3. finish state writeback when required
4. update or archive the active plan if lifecycle changed
5. complete verification or mark it explicitly skipped
6. produce the closeout summary
7. make the commit decision from that summary and policy

If any required closeout gate is incomplete, the plan stays active.

For phase execution, completed verification is evidence, not automatic continuation. A plan may opt into auto-continuation only through explicit active-plan metadata such as `auto_continue = true` plus stop-condition coverage for failed or missing verification, uncertain docs or lifecycle authority, write scope changes, source-reality changes, sensitive or destructive action, and the final closeout boundary. Without that explicit safe contract, the default next action after a verified phase is state writeback or closeout preparation, not the next phase by inference. `writeback --active-phase <next-phase> --phase-status pending` is the explicit same-plan phase-advance rail: it may complete the previously active phase body and move Current Focus to the requested pending phase in one write, but it cannot approve closeout, archive, roadmap done-status, next-plan opening, staging, or commit. `writeback --phase-status complete` records a ready-for-closeout boundary only; active-plan archive, roadmap done-status, source-incubation archive, and next-slice opening require separate explicit requests. A phase-only `docs_decision = uncertain` write with `phase_status = complete` may replace mismatched prior closeout facts with current plan identity and provisional docs posture, but it still cannot carry stale closeout facts or approve archive/roadmap/next-slice movement. During archive close, stale `MLH Phase Writeback` tails that reference the default active-plan route are retired so project-state no longer points at the deleted plan. Existing `project/verification/*.md` artifacts are reported as pre-archive lifecycle snapshots after archive route writes; final post-archive evidence must come from route-write evidence, `check`, or explicitly regenerated verification. When project-state already has complete closeout authority for the active plan, archive close may carry those matching facts, retarget the closeout identity to the archived plan, and write the synchronized archived-plan copy in the same transaction even when the operator did not resupply every closeout field. Writeback refusal output and `suggest --intent "phase closeout handoff"` surface the composed safe sequence for splitting phase evidence handoff from archive closeout replacement: first review `writeback --phase-status complete --docs-decision uncertain`, then review `writeback --archive-active-plan` with complete closeout facts and no explicit `--active-phase` or `--last-archived-plan`. After the active plan has already been archived, `writeback --roadmap-item <id> --archived-plan <project/archive/plans/...>` may refresh same-request closeout facts, the matching roadmap item, and source-incubation relationship metadata for that archived identity without reopening lifecycle state or requiring a readable active plan. When a lifecycle-field writeback would also trigger project-state auto-compaction, apply refuses before writing unless dry-run review is followed by `--allow-auto-compaction` or the operator runs `writeback --compact-only` as a separate maintenance step; phase movement and operating-memory compaction stay separately reviewable decisions.

Read-only check and grain diagnostics may flag missing, generic, unresolved, or toolchain-mismatched verification gates, adjacent regression-test ownership gaps, raw-log-heavy active plans, done roadmap items without archived evidence except explicit terminal historical relationship stubs owned by archive-context evidence, done roadmap items whose `docs_decision` remains `uncertain` while archived evidence is missing, or archived-plan samples with weak closeout facts. These findings are closeout assembly prompts and calibration evidence only; they cannot mark work verified, write closeout state, archive a plan, or change roadmap status.

For MyLittleHarness Core v0 work, closeout must also name carry-forward destinations for deferred enhancement-ledger items, skills/MCP/hooks, package/attach compatibility, rename decisions, and lifecycle mutation. Naming a destination does not promote those lanes into core.

When manifest policy is `manual`, the commit decision is skipped even if the directory later becomes a git worktree. When the root is not a git worktree, `worktree_start_state` should record the failed git status fact rather than pretending the tree was clean.

A read-only closeout helper may assemble these fields, including a fail-open VCS posture probe, but helper output is only an input to operator closeout. It may use project-state closeout writeback facts for candidate fields and Git trailer suggestions only when the recorded plan identity matches the current active or archived plan; mismatched closeout identity is stale evidence and must be ignored in favor of current active-plan or same-request transition facts. When `plan_status = none`, `active_plan` is empty, `last_archived_plan` matches the recorded archived identity, and the matching roadmap item is already `done`, carry-forward text that only says to archive the active plan and mark the roadmap item done is satisfied historical context, not a current closeout candidate, Git trailer suggestion, or next action. Clean, dirty, non-git, Git-missing, and Git-failure findings do not approve archive or commit actions. The helper must not stage, stash, commit, checkout, reset, clean, fetch, pull, push, create worktrees, mutate hooks/config, write state, archive plans, or infer task scope stronger than the operator-recorded work.

## Anti-Patterns

The workflow must avoid:

- verification after every phase by habit
- final closeout with no intermediate integration anchor on risky work
- marking work complete based only on intention or narration
- creating standalone verification docs for every tiny task
- hiding retries, repair loops, or escalation inside verification helpers
