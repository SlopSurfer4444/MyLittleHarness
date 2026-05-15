# Workflow Plan Synthesis and Distillation Spec

> Product fixture note: This spec is retained as a product compatibility fixture for CLI/tests. Live workflow authority, plans, research, and memory remain in the target repository; legacy reference material is opened only for a named blocker.

## Purpose

This spec defines how the workflow should synthesize an active plan from repo-native artifacts without broad markdown ingestion or chat-memory drift.
Planning may inspect nearby helper surfaces when they define the same boundary, but artifact authority still follows the canonical workflow model.

It exists to:
- keep the planning start pass cheap
- make artifact discovery explicit and inspectable
- separate artifact ranking from artifact distillation
- keep planning authoritative without turning it into a hidden runtime

This spec does not define implementation commands, runtime orchestration, or UI behavior.

## MyLittleHarness Core v0 Planning Posture

In the MyLittleHarness source repository, MyLittleHarness is the target system while `workflow` and `workflow-core` remain compatibility vocabulary. Planning must keep that distinction visible when naming source sets, conflicts, and excluded work.

Core v0 planning is file-first:
- start from repo-visible artifacts, not chat memory
- use `project/project-state.md` as the only mutable project memory surface
- read `project/implementation-plan.md` only when `plan_status = "active"` or the user explicitly asks about the plan, phase, or closeout
- open future reusable product plans in the operating project root with the product checkout named as the target root; do not open, continue, or close operational plans inside the product source tree
- keep package-source mirrors, skills, hooks, MCP, adapters, generated views, and candidate tooling subordinate unless a scoped plan promotes them
- keep non-git operation valid; absence of `git status` evidence is a closeout fact, not a reason to invent repository history

## Authoritative Inputs

- `project/specs/workflow/workflow-artifact-model-spec.md`
- `project/project-state.md`
- `project/implementation-plan.md` when `plan_status = "active"` or when the user explicitly asks about the plan, phase, or closeout
- stable specs, decision docs, research artifacts, verdicts, and bounded incubation artifacts that are relevant to the current topic
- relevant helper surfaces only when they explicitly define or constrain the same topic boundary

## Start Pass

The default MyLittleHarness start pass is:

1. Read `project/project-state.md`.
2. Read the repository artifact map when it is present and referenced by state.
3. Read `.agents/docmap.yaml` when routing, docs, projection, or start-path behavior is in scope.
4. Read the active same-topic incubation surface when state names it.
5. Read `project/implementation-plan.md` only when it is active or explicitly requested.
6. Collect directly referenced artifacts from state, the artifact map, docmap, incubation, or the active plan.
7. Add same-topic stable specs and decision docs that define the current contract boundary.
8. Add directly referenced or same-topic research artifacts when they contain decision-grade findings or unresolved tradeoff evidence.
9. Add recent verification evidence or verdicts only when they validate the same topic or block the next step.
10. Treat chat residue as the lowest-trust source.

The planner must not start with a broad scan of every markdown file in the repository.

When reusable product work targets the product source checkout, planning still recovers operating context from the operating project root. Inspect the product checkout as source/test/product-doc evidence for the target change, not as the source of working memory. Any workflow-shaped files retained in the product checkout are product compatibility fixtures unless a later explicit root-boundary plan says otherwise.

When incubation artifacts enter planning intake, same-topic inputs follow `merge-before-create`: reuse or merge the current topic artifact before opening another temporary note unless the topic boundary is clearly different. A user request to record or incubate a new idea is enough to create or update the canonical same-topic note under `project/plan-incubation/*.md`; it should not fall back to `project-state` carry-forward bullets merely because no current topic note exists yet.

If `plan_status = "active"` and the user asks to implement, continue, realize, or close the plan, treat the active canonical plan as the default workstream after the start pass. Ask for a different workstream only when `project-state` and the active plan still conflict after both are read.

For plan work or material replans, the output must name the source set and intentional exclusions when those exclusions affect direction or confidence. Exclusions are especially important for enhancement-ledger items such as evidence IDs, quality gates, Context Ledger / Synapti, skills, MCP, hooks, candidate tooling, package/attach rebuilds, and operational lifecycle decision.

## Artifact Discovery Rules

### Hard inclusion rules

Include an artifact when at least one condition is true:

- it is directly referenced from `project-state`
- it is directly referenced from the active plan
- it is a stable spec or decision doc for the same topic
- it is the current research artifact for the same topic
- it contains the current verification verdict for the same topic
- the user explicitly names it

### Hard exclusion rules

Do not include an artifact by default when:

- it is historical but unrelated to the active topic
- it is an unreferenced temporary note
- it is an unreferenced research import with no current contract or planning relevance
- it only duplicates information already present in a stronger artifact
- it is large narrative history with no current contract or execution value

## Ranking Model

The workflow may use lightweight ranking, but it must obey hard precedence from the artifact model.

Soft ranking signals:
- direct reference from `project-state`
- direct reference from the active plan
- same-topic match
- canonical class strength
- freshness when comparing same-class artifacts
- explicit validation status

Ranking must remain explainable. The current workflow does not require a numerical scoring engine.

## Routing And Linking Intake Boundary

Planning or helper-assisted routing should stay cheap-first, explainable, and conservative.

Reliable signals:
- direct reference from `project-state` or the active plan
- explicit repo-path or wiki-link references
- stable topic, alias, or other inspectable identity markers from frontmatter
- path, namespace, or artifact-lane membership

Weak signals:
- keyword overlap
- semantic similarity
- recency
- author intent inferred from prose

Rules:
- weak signals may rank or suggest candidates, but they must not authorize auto-match on their own
- allowed output shapes are `inventory list`, `link-gap report`, `candidate backlink suggestions`, `short action list`, and `proposed diff`
- auto-match is allowed only for strictly deterministic topology with predefined namespaces, destinations, or other explicit routing rules
- when routing hits missing identity, lane, or status signals, conflicting metadata, too many plausible matches, or likely duplicate or overlinked topics, it should stop and return candidate guidance instead of mutating
- orphaned notes, reverse-engineering residue, and other hard-to-place material belong to operator-invoked audit or maintenance passes rather than daily intake

## Archive Relevance Rule

Archived plans and older rationale should be opt-in by relevance, not always-on planning input.

Include archived material only when at least one condition is true:
- the current topic or module clearly matches the archived topic
- a stable spec or `project-state` explicitly references the archive artifact
- the planner is trying to recover rationale for a still-open tradeoff

Do not include archived material by default just because it exists. Historical plans are useful evidence, but they should not pull the planner back into stale assumptions.

## Distillation Contract

Artifact distillation is a separate step from discovery.

The distillation output should be compact and should extract only the fields needed to shape the active plan:

- `problem_statement`
- `current_commitments`
- `constraints`
- `deliverables_or_phase_candidates`
- `dependencies`
- `acceptance_or_validation_hypotheses`
- `open_questions`
- `rejected_directions`
- `source_set`

Distillation should not reproduce full markdown documents. It should produce plan inputs.

Research distillation is a validation rail, not a synthesis authority. A distilled research artifact should record `quality_status`, `planning_reliance`, gate-question coverage, source-bound claims, and confidence/uncertainty notes. Shallow distilled artifacts that lack those fields or sections remain provisional and must not be treated as enough `source_research` evidence for roadmap-backed plan opening.

## Signal-Driven Capture Rules

Planning and synthesis should create or refresh provisional notes only when durable signals justify that capture.

Durable signals include:
- constraints
- repeated conclusions
- rejected directions
- dependencies
- durable choice points

The workflow must not treat incubation as exhaustive brainstorm transcript storage.

When refreshing an existing incubation artifact, prefer reshaping the current topic note over append-only chronology.

Cheap merge/split test:
- merge when the new signal keeps the same problem statement, mostly the same evidence set, and the same likely promotion target or next fate
- split when the new signal would force one note to carry unrelated problem statements, unrelated promotion targets, or conflicting next fates that are no longer inspectable in one compact surface

Every provisional synthesis artifact should leave the pass with an explicit next inspectable fate:
- `merge`
- `promote`
- `retire`
- `archive`

## Research-First Handoff Rule

A bounded active plan may open only after one of these is true:

- an inspectable research or spec-synthesis artifact defines enough contract boundary to support execution
- an explicit limited-confidence decision records the missing evidence, why bounded execution is still cheaper than more research, and what must be rechecked later

Narrative pressure, chat urgency, or a desire to "just start" are not enough by themselves to open a bounded active plan.

## Bridge Thresholds And Minimum Handoff Fields

The workflow should make bridge readiness inspectable before opening or materially refreshing a bounded plan.

Recommended bridge postures:
- `incubation-only`
- `research-ready`
- `plan-candidate`
- `limited-confidence` when the bounded exception is used

Threshold rules:
- keep a topic `incubation-only` when the current note is still merging same-topic signal, surfacing contradictions, or shaping promotion targets more than distilling decision-grade findings
- promote to `research-ready` only when the topic already has a stable problem statement, durable signals, clear source linkage, and explicit implications or rejected directions that justify a durable research artifact
- treat a research or spec-synthesis artifact as a `plan-candidate` only when it carries enough contract boundary that a bounded plan can open without hidden chat-memory fill-in
- use `limited-confidence` only when the artifact explicitly records what evidence is still missing, why bounded execution is cheaper than more research, and what must be rechecked later

Minimum handoff fields for a `plan-candidate` artifact:
- `problem_statement` and current catalyst or why-now trigger
- evidence class and provenance, including the strongest source linkage that supports the boundary
- explicit boundary or implications for the bounded work, including named non-goals where they are needed to stop widening
- rejected directions, unresolved contradictions, or both when they still constrain the work
- make-or-break assumptions plus the decision thresholds that separate proceed from stop or reframe
- invalidation or recheck posture: what observation, threshold miss, or contradiction would force more research, reframing, or carry-forward
- the next bounded deliverable, or the explicit reason the handoff stops at limited-confidence instead of opening a full plan

Plan-open rule:
- do not open a bounded plan unless the intake artifact is already inspectable as a `plan-candidate` or an explicit limited-confidence decision
- when the handoff uses limited confidence, the accepted plan should preserve the missing-evidence note and the recheck condition instead of silently normalizing it away
- after a plan-candidate has opened a bounded active plan, stable spec changes must come from that accepted plan or a later scoped replan, not from the research artifact alone

## Manifest Governance Plan Inputs

When a roadmap item promotes orchestration or HR-agent research into manifest governance, plan synthesis should keep the result as protocol/report data only. Generated plans may name route/role manifest fields, work claims, review tokens, approval packets, route receipts, worker-space boundaries, and fan-in evidence as scoped artifacts to inspect or test, but they must also preserve the boundary that the coordinator retains lifecycle authority and worker packets are evidence only.

This manifest-governance lane does not implement an HR-agent, hidden daemon, model gateway, provider auto-selection, worker lifecycle write, automatic fan-in, staging, commit, push, archive approval, roadmap status change, or next-plan opening. If later implementation needs any runtime behavior, that work needs a later accepted slice with its own write scope, dry-run/apply rail, and verification gate.

## Accepted Plan Boundary

An active implementation plan should be created or materially refreshed when one or more conditions are true:

- the work is likely to span multiple sessions
- there are stage dependencies between deliverables
- multiple artifacts must land in a defined order
- validation is non-trivial enough that ad hoc execution would hide risk
- the next steps need explicit phase boundaries or closeout gates

Stay `ad_hoc` when:
- the outcome fits in one bounded session
- the diff is narrow
- rollback is cheap
- there is a direct verification oracle
- a durable plan would add more noise than clarity

## Active Plan Requirements

An accepted active plan should keep the existing repo template shape:

- `Goal`
- `Scope`
- `Non-goals`
- `Constraints`
- `Phases`
- `Current phase`
- `Validation`
- `Open questions`

For workflow-level plan quality, the plan should also make these surfaces explicit when relevant:

- `Source set`
- `Distilled inputs`
- `Verification blocks`
- `Promotion candidates`

These can be embedded into phase or validation sections; they do not require a second plan file.

When an active plan opens from a roadmap item that belongs to a roadmap execution slice, the plan frontmatter is the executable one-slice contract. It should preserve `primary_roadmap_item`, `covered_roadmap_items`, `domain_context`, `target_artifacts`, `execution_policy`, `auto_continue`, `stop_conditions`, and `closeout_boundary` as derived plan metadata. `plan --roadmap-item` may treat only `accepted` or `active` roadmap items as current plan-opening inputs; proposed, deferred, rejected, done, superseded, blocked, missing-status, or historical roadmap facts must refuse or hard-warn before active-plan, project-state lifecycle, roadmap relationship, or source-incubation relationship write previews are emitted. If the roadmap item has no explicit `target_artifacts`, plan synthesis may recover source/test/docs target hints from source-incubation `affected_routes` while keeping lifecycle-only routes as context. For accepted or active roadmap items, stale `slice_closeout_boundary` wording that still says no implementation plan, no archive, no lifecycle movement, or provisional pre-implementation attachment should be normalized into a non-authority safety note and reported before the generated plan is relied on for closeout boundaries. The default generated contract is current-phase-only with `auto_continue = false`; any future auto-continuation must be explicit and covered by stop conditions rather than inferred from verification success. `project/project-state.md` should keep only lifecycle pointers such as `active_plan`, `active_phase`, and `phase_status`, not roadmap slice membership or target artifact lists.

When a roadmap-backed plan is sourced from a meta-feedback incubation cluster, source excerpt selection should prefer the actual tagged `[MLH-Fix-Candidate]` entry over provenance or cluster boilerplate, preserve the full cleaned representative observation, and carry route/owner hints such as `affected_routes` and `expected_owner_command` into the generated task context. If that richer source excerpt has route hints, is not recovery-only evidence, and the roadmap item is not part of a grouped execution slice, it may become the plan `domain_context` and derived objective instead of a shorter roadmap `slice_goal`. Recovery-only source notes and grouped accepted slices should preserve roadmap `slice_goal` or `carry_forward` as the leading plan objective/task context.

When roadmap slice metadata is available, plan synthesis should make bundle/split decisions inspectable without making them authoritative. Dry-run/apply reports may include bundle rationale, split boundary, target-artifact pressure, and phase pressure; generated plans may mirror those values under `Plan Synthesis Notes`. Target-artifact pressure is a report-only sizing signal, not a calibrated threshold or hard gate, and the synthesis report cannot approve lifecycle movement, closeout, archive, repair, commit, rollback, or future mutation.

Generated roadmap-backed plans should use those signals to write either a `Phase Outline` with concrete phase sections or an explicit one-shot rationale. A phase outline is expected when multiple target artifacts, verification summaries, related specs, docs update decisions, or grouped roadmap items create execution pressure; a one-shot rationale is expected only when artifact and verification pressure are low and the plan records when to stop before scope expansion. When a source implementation phase uses target test artifacts for verification, those adjacent regression tests should be named in that phase's write scope rather than left as implicit verification-only ownership. When roadmap metadata records `docs_decision = updated`, plan synthesis should surface `plan-docs-write-scope-impact` and place docs/spec/package metadata targets in the docs phase write scope; if exact docs targets are absent, the generated scope must say exact docs/spec/package metadata files must be declared before mutation. Directory-level docs/spec hints such as `docs/specs` are not exact docs targets and must become that explicit-scope placeholder rather than a broad write scope. Missing roadmap `related_specs` targets must be reported during `check` and `plan --roadmap-item` preview/opening before those stale paths become generated plan read context or docs/write scope; the warning should point operators at retarget/removal or provisional `docs_decision='uncertain'` instead of implying a new stable spec should be invented.

Generated `verification_gates` should be evidence-backed by target test artifacts or repo-visible command discovery from package scripts, Makefile/just/task files, CI workflow commands, documented commands, or roadmap verification summaries. When that evidence is weak or absent, the gate should stay `UNRESOLVED` instead of falling back to a universal toolchain command. Broad pytest/full-suite gates over source-only target artifacts should surface adjacent regression-test ownership as a warning until the tests are named or the gate is narrowed.

Read-only grain diagnostics may later inspect generated plans for missing slice metadata, missing target artifacts, vague write scope, generic or unresolved verification gates, toolchain-mismatched verification gates, adjacent regression-test ownership gaps, under-decomposed single-phase plans, over-atomic slices, giant brittle slices, and unsafe auto-continuation posture. Those diagnostics are calibration inputs for future planning behavior only; they do not rewrite plans, split slices, or promote numeric thresholds into refusal gates.

## One-Plan Rule

- Exactly one accepted active plan should govern one work item at a time.
- Execution may not start from an incubation note alone.
- Same-topic incubation inputs should be merged into the current synthesis surface before a new temporary note is created.
- Planning helpers may draft a plan, but they must not create hidden parallel plan files.
- If a new direction supersedes the active plan, the existing plan must be updated or archived explicitly rather than abandoned in place.

## Reusable Procedure Routing

When planning discovers that a repeated procedure is needed, it should route that need to a reusable procedural surface rather than bloating memory or the active plan.

Preferred destinations:
- repeated planning checklist -> reusable skill or checklist
- repeated verification checklist -> reusable skill or checklist
- one-off execution ordering -> active plan
- durable behavioral rule -> stable spec or `project-state`

The planner should not solve repetition by copying the same procedure into every plan.

## Planning Safety Boundary

Planning remains read-oriented by default.

Allowed during planning:
- read repo artifacts
- search and distill
- inspect read-only runtime evidence
- draft or update the canonical active plan when planning itself is the task

Not allowed during planning by default:
- silent execution of implementation steps
- mutation of stable specs as a side effect of brainstorming
- spawning extra hidden memory artifacts
- treating an incubation note as an accepted execution contract
- opening a bounded active plan from narrative pressure when no inspectable synthesis or explicit limited-confidence decision exists

If planning reveals that a stable spec is wrong or incomplete, the planner must surface the conflict explicitly before execution continues.

## Fresh-Context Review Preparation

Fresh-context review is a useful pattern, but it is not the default planning path.

Default rule:
- planning may recommend an independent review pass for risky integration or closeout work
- the recommendation should stay explicit and bounded
- the review can usually operate on the main worktree unless independence or isolation clearly matters

Later-extension rule:
- a separate worktree or isolated reviewer flow is allowed only for risky integration blocks or independent review before merge
- worktree-heavy review remains opt-in, not the default execution model

## Plan vs Execution Boundary

The plan should describe:
- outcome boundaries
- phase ordering
- validation strategy
- escalation conditions

The plan should not become:
- a command transcript
- a scratch notebook of every idea considered
- a hidden execution log
- a duplicate of stable contract specs

Execution belongs in repo changes, bounded verification evidence, and concise writeback.

## Anti-Patterns

The workflow must avoid:

- broad markdown ingestion before reading `project-state`
- using chat memory as stronger evidence than repo artifacts
- copying canonical specs into temporary notes instead of linking them
- creating new plan files just to preserve thought traces
- letting a plan absorb every design decision that should have been promoted into a stable spec
