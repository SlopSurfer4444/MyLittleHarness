---
spec_status: "accepted"
implementation_posture: "partially-verified"
---
# Workflow Artifact Model and Authority Spec

> Product fixture note: This spec is retained as a product compatibility fixture for CLI/tests. Live workflow authority, plans, research, and memory remain in the target repository; legacy reference material is opened only for a named blocker.

## Purpose

This spec defines the canonical artifact model for the repo-native workflow contract.
The repository should be treated as markdown-first and repo-native: workflow canon lives in inspectable artifacts that can be carried with the repo itself.

It exists to:
- separate durable memory, stable contracts, execution plans, temporary synthesis, verification evidence, and archive history
- prevent `project-state`, active plans, stable specs, and incubation notes from collapsing into one noisy markdown layer
- define how artifacts gain authority, how they conflict, and how they are promoted or retired

This spec does not introduce a control plane, scheduler, daemon, or hidden storage layer.
This framing does not create a second authority model: durable authority still comes from repo-native artifacts, not from nearby helper surfaces.

## MyLittleHarness Core v0 Posture

In the MyLittleHarness source repository, MyLittleHarness is the target system. The terms `workflow` and `workflow-core` may remain as compatibility, package, manifest, or operator-contract vocabulary, but they do not make the old compatibility harness the architectural baseline.

Core v0 consists of the small repo-native contract that keeps agent work recoverable from files:
- repo-native authority in inspectable artifacts
- one mutable project memory surface at `project/project-state.md`
- explicit artifact roles for state, specs, research, incubation, active plans, archives, package-source/projection mirrors, and raw intake
- research-before-plan handoff for durable architecture work
- lazy one-plan execution through `project/implementation-plan.md`
- verification and closeout evidence before completion
- conservative docs routing through `.agents/docmap.yaml`
- helper and projection demotion unless a later lane promotes a surface explicitly
- operation that remains valid when the repository is not a git worktree

Core v0 does not include operational lifecycle decision, package/archive regeneration, evidence IDs, quality gates, candidate tooling, hidden hooks, MCP, daemons, schedulers, dashboards, mandatory adapters, or a second mutable memory tree. Those ideas stay deferred enhancement or projection lanes unless a future plan promotes them through their gates.

## Target And Product Boundary

The target repository owns active MyLittleHarness work. Working plans, `project-state`, research intake, incubation, navigation, workflow execution, and closeout evidence live there while the harness is carrying the work. Legacy reference material is opened only for a named blocker.

The product repository may contain product source, tests, README/product docs, and minimal product compatibility fixtures when the CLI/tests still need a local workflow-shaped root. Those fixtures are not live task memory and do not make the product repository a workflow execution root.

Rules:
- future reusable product implementation plans open in the operating project root and name the product checkout as the target root
- the product checkout must not hold active working memory, implementation plans, research/history/raw intake, archived plans, workflow execution state, runtime debris, or legacy workflow residue
- compatibility fixtures retained in the product checkout must be explicitly fixture/product-compatibility surfaces, not operating state
- product-source hygiene includes keeping temporary files, logs, caches, package archives, generated validation artifacts, local databases, pycache, and other runtime outputs out of the product tree unless a later product feature deliberately owns them

## Repository-Native Path Model

The current repo-native layout is the canonical current surface:

- `project/project-state.md` for durable project memory and the current canonical map
- `project/implementation-plan.md` for the active implementation plan when `plan_status = "active"`
- `project/specs/workflow/*.md` for stable workflow contracts
- `project/plan-incubation/*.md` for temporary synthesis artifacts
- `project/research/*.md` for imported deep-research findings and distilled external evidence
- `project/archive/plans/*.md` for archived implementation plans
- `project/archive/reference/**` for historical reference specs, verdicts, and acceptance materials

The current workflow does not require a parallel `.workflow/` tree. The existing `project/` structure remains the canonical home for workflow artifacts in this repository.
Attach/install/repair should eagerly scaffold the canonical directory layout for these surfaces, including `project/specs/workflow`, `project/research`, `project/plan-incubation`, and `project/archive/{plans,reference}`.
Lazy creation remains file-level, not directory-level: `project/implementation-plan.md` and `.agents/docmap.yaml` may stay absent until the relevant workflow path is actually used.
Adjacent helper surfaces may coexist around that structure, but they do not outrank the canonical artifact model defined here.
The contract must remain understandable without installed skills, hooks, MCP servers, Git, GitHub, browser state, IDE state, or external services.

CLI route-table output is a compact discovery view over this artifact model. `status`, `check`, and `intelligence --focus routes` may name the live-root routes for state, active plans, incubation, research, stable specs, verification through the active-plan block and optional `project/verification/*.md` proof/evidence records, closeout/writeback, archive, and docs routing, but the output is advisory only. It does not replace these repo-visible artifacts and does not authorize mutation, repair, closeout, archive, commit, or lifecycle decisions.

Route and role manifests are protocol views over the same artifact model, not a new authority layer. `route_manifest` may expose orchestration fields such as `parallelism_class`, `authority_lane`, `exclusive_owner`, `claim_scope`, `claim_required`, `merge_policy`, `fan_in_gate`, `max_parallelism_hint`, `stale_claim_policy`, and `conflict_policy`; lifecycle routes remain sequential and coordinator-owned. `role_manifest` may expose coordination fields such as `orchestration_role`, `may_spawn_workers`, `worker_space_boundary`, `isolation_contract`, `fan_in_output_required`, `work_claim_required`, `work_claim_contract`, `route_receipt_contract`, `fan_in_authority`, `runtime_boundary`, and `coordination_budget`; these fields describe packet and fan-in expectations without spawning workers or granting direct apply authority.

### Route Frontmatter And Projection Discovery

MLH-owned lifecycle Markdown route files are expected to carry frontmatter when they are created, imported, refreshed, or appended through MLH writers. This applies to research, incubation, roadmap, decision, ADR, verification, agent-run evidence, and stable-spec route writes when those routes are present. Legacy files without frontmatter are recoverable source files, but `check` should warn on routed lifecycle Markdown that has no frontmatter or malformed frontmatter so the owning route can rewrite or normalize the file before future writes depend on it. The selected repair rail for missing route frontmatter is snapshot-protected `lifecycle-markdown-frontmatter-repair`; it prepends conservative route metadata only, preserves bodies, and cannot infer truth, move lifecycle state, update docmap entries, approve generated cache, or close out work.

`.agents/docmap.yaml` names route classes, entrypoints, docs-impact routing, and authority boundaries. It is not a registry of every file under known route directories. A new frontmatter-bearing research, incubation, verification, decision, ADR, or roadmap artifact becomes discoverable through inventory, route-reference checks, projection rebuilds, and source-bound searches without editing the docmap. Change the docmap only when route shape, directory ownership, entrypoint behavior, or authority/routing semantics change.

Generated projection artifacts, relationship graphs, dashboard pulses, MCP read projections, and SQLite indexes rebuild from repo-visible route files and their frontmatter/body content. When a lifecycle write changes routed Markdown or lifecycle metadata and generated cache exists, the write path must mark that cache dirty or rebuild/warm it through the bounded projection rail. First-contact navigation may use generated acceleration only after it sees current cache, or after it reports dirty/missing/stale/degraded cache with the next safe `projection --rebuild --target all` or `projection --warm-cache --target all` route.

The first-contact hook event is another generated/projection consumer, not a new artifact authority class. `hooks --run session-start --json` may package lifecycle posture, dashboard agent packet data, route refs, and projection/SQLite cache posture into `mylittleharness.hook-event.v1` for a native client. The hook payload is derived context and must remain rebuildable from repo-visible sources plus current inspection; it cannot become the only record of active focus, docs decisions, phase evidence, archive state, roadmap status, product-diff acceptance, Git state, dispatcher readiness, provider selection, or cache truth.

Repo-visible coordination artifacts may live under `project/verification/**` when they are useful fan-in evidence. Work claims belong under `project/verification/work-claims/*.json`, handoff packets under `project/verification/handoffs/*.json`, route receipts under `project/verification/route-receipts/*.json`, and approval packets under `project/verification/approval-packets/*.json`. These records coordinate scoped work, handoff context, route-write evidence, human-gate evidence, and overlap checks, but they remain evidence routes: they do not create a hidden queue, grant worker lifecycle authority, approve archive, mutate roadmap status, stage, commit, push, or release. Review tokens are deterministic report outputs that bind current route and role manifest fingerprints, active-plan identity, claims, evidence, patch, verifier, and human-gate inputs for fan-in review; matching tokens are still guards, not authority. In this contract, work claims and review tokens are evidence, not authority. The coordinator retains lifecycle authority; worker packets are evidence only, and route receipts are protocol/report data only.

Approval relay adapters may read these approval packets and render serializable transport previews, but the relay payload is adapter evidence only. Relay output must not copy packet bodies into hidden adapter state, store secrets, attempt delivery by default, install daemons, create queues, or treat approved packet status as lifecycle, archive, roadmap, Git, or release authority.

Approval packets are required for risky operations that cross a human gate. Gate classes include lifecycle authority mutation, write-scope expansion, dependency/package/supply-chain change, destructive archive/VCS/rollback action, external service/secrets/network use, fan-in/merge/review-token conservation, and repeated verifier failure or uncertain evidence. The packet should identify the requester or actor/session, subject, requested decision, gate and risk class, validity window, target artifacts, planned writes and boundaries, allowed command/network/auth scopes, blast radius, source/dry-run/verifier refs, patch or base/head identity, review-token hash when available, docs/lifecycle impact, stop or reopen conditions, human decision, approver and decision timestamp, fallback or rejection reason, and residual risk. The packet is cold evidence that a bounded risky decision was requested or recorded; it is not implementation proof or lifecycle authority.

Reconcile reports are terminal diagnostics over these repo-visible artifacts. They may read active-plan references, route/spec/source paths, agent-run source hashes, work claims, approval packets, and worker-space residue to classify current posture, but they do not create a durable database, hidden queue, worker cleanup rail, or amendment authority. Human-gated proposals from reconcile output are review prompts only until a later explicit lifecycle or cleanup command owns the mutation.

## Attention Tiers

Authority and attention are related but not identical.

Preferred attention tiers:
- `always-read`
  - `project/project-state.md`
- `topic-mandatory`
  - the active plan when `plan_status = "active"` or when the user explicitly asks about the plan, phase, or closeout
  - same-topic stable specs or decision docs
  - the active same-topic incubation or active-reference artifact when the task is about that topic
- `task-conditional`
  - research artifacts, verification artifacts, helper surfaces, prompt guides, and package-source mirrors
  - these are read only when the task explicitly needs their lane, evidence, or projection behavior
- `historical-only`
  - archived plans and historical reference materials unless current state, current specs, or the current topic explicitly pull them in

The workflow should stay cheap-first by reading only what the current task needs from the highest available authority tier.

## Repo Navigation Maintenance

This repository also maintains a small navigation set so the cheap start pass stays linear instead of depending on chat memory.

Current navigation set:
- `project/project-state.md`
- same-topic research evidence under `project/research/*.md`
- `.agents/docmap.yaml`
- `project/plan-incubation/mylittleharness.md`
- `project/implementation-plan.md` only when active or explicitly requested
- same-topic stable specs under `project/specs/workflow/**`

Rules:
- read the navigation set before substantial work, then expand only into same-topic canon, active-reference, or historical surfaces that the task actually needs
- keep the navigation set aligned when current pointers, authority tiers, routing surfaces, or reboot posture change
- update `project/project-state.md` for current pointers and durable active commitments
- update the hierarchy map when artifact classes, attention tiers, or current-fate rules change
- update `.agents/docmap.yaml` when entrypoint, route-class ownership, directory shape, docs-impact routing, or authority-boundary knowledge changes; do not edit it merely because a new file appeared under an existing frontmatter-bearing route
- update the active incubation surface when the reboot posture, next lane, or dependency spine changes
- update stable specs when the rule itself changes, not only the current repo pointers
- do not churn the navigation set when nothing meaningful changed; the maintenance discipline is anti-drift, not ceremony

## Source-Repo Package Mirrors and Projections

Some repositories that host the workflow source package may also contain package-source or projection surfaces outside `project/**`, for example:
- `specs/**`
- `templates/**`
- `research/**` in historical or package-mirror layouts
- `codex-home/skills/**`

Rules:
- in the source repository, these surfaces are package-source or projection material, not live repo-local canon
- when a matching live artifact exists under `project/**`, the `project/**` artifact wins for current authority
- package mirrors may be read for attach/install/template or skill-projection tasks, but they do not create a second canon
- if identical mirror copies exist, the duplication should be treated as packaging/projection scaffolding, not as competing authority
- repo entrypoint docs such as `README.md` may explain this boundary, but stable workflow contract still lives under `project/**`
- changing a live spec requires resyncing its matching package-source mirror when the repository intentionally keeps mirror parity
- templates, skills, attach scripts, package archives, MCP surfaces, hooks, and generated views remain subordinate projections unless a later scoped lane promotes them explicitly

## Artifact Classes

### Durable project memory

Canonical surface:
- `project/project-state.md`

Purpose:
- index the active workstream
- point to canonical docs
- carry durable commitments, risks, and next-step cues that should survive chat turnover

Allowed content:
- active focus
- canonical paths
- durable decisions that affect future work selection
- short writebacks for meaningful progress

Not allowed:
- long narrative history
- command transcripts
- duplicate copies of stable specs
- phase-by-phase execution choreography

`project-state` is an index plus active commitments, not a second implementation plan.

### Stable specs

Canonical surface:
- `project/specs/**/*.md`

Purpose:
- define the authoritative contract for boundaries, behavior, acceptance, or workflow rules

Allowed content:
- normative rules
- contract boundaries
- acceptance expectations
- explicit authoritative inputs

Not allowed:
- transient brainstorming
- current-session scratch reasoning
- low-level execution logs

Stable specs are the winning source for contract-level questions unless a later decision doc explicitly supersedes them.

Plan-facing stable specs may carry explicit lifecycle posture without making metadata stronger than the body. `spec_status` names the spec document lifecycle (`draft`, `accepted`, `superseded`, or `archived`) while `implementation_posture` names implementation evidence (`not-applicable`, `target-only`, `in-progress`, `partially-verified`, `synced`, `drift-detected`, `deprecated-compat`, or `retired`). These fields stay separate from `docs_decision`, which remains a closeout-local decision. `target-only` preserves an accepted target contract even when implementation has not caught up; deletion, supersession, deprecation, retirement, or sync claims require human-gated evidence and cannot be inferred from read-only diagnostics.

### Research artifacts

Canonical surface:
- `project/research/*.md`

Purpose:
- capture imported or repo-native deep-research findings that are more durable than incubation notes but are not yet stable contract or active execution

Allowed content:
- distilled findings and evidence classes
- external approach summaries and tradeoff comparisons
- explicit implications for spec, plan, or horizon
- clear source linkage back to the repo artifacts that framed the research

Not allowed:
- raw transcript dumps as the primary artifact
- authoritative contract rules that should live in a stable spec
- execution sequencing that belongs in an active plan

Rules:
- MLH-owned research writes must carry or normalize frontmatter with:
  - `status`
  - `topic`
  - `created`
  - `last_reviewed`
  - `derived_from`
  - `related_artifacts`
  - `superseded_by`
- when a repo wants routing or linking support, the minimum artifact contract should still be satisfiable from repo-native identity, explicit lane or type, and lifecycle status; existing signals such as `topic`, directory membership, and `status` may satisfy this without introducing a mandatory new `id` field everywhere
- routing-oriented synthesis should prefer explicit aliases, repo-path links, and lane membership over inferred semantic grouping
- helper-facing derivative views may expose `inventory list`, `link-gap report`, `candidate backlink suggestions`, `short action list`, or `proposed diff`, but those views remain read-only and do not become a mutation contract by themselves
- research artifacts may shape planning and future specs, but they do not override current canon until promoted explicitly
- research artifacts should make their promotion or handoff posture inspectable rather than relying on narrative implication

### Decision docs

Canonical surface:
- future `project/decisions/*.md` or `project/adrs/*.md` when justified

Purpose:
- capture durable architectural tradeoffs that should outlive a single plan

Use a decision doc when:
- the repo must remember why a tradeoff was chosen
- the tradeoff may later conflict with a new plan draft
- the result is durable enough that hiding it in `project-state` would make that file too dense

The current workflow does not require a decision-doc tree for every topic. Introduce it only for decisions that are broader than one active plan and narrower than global project memory.

### Active plans

Canonical surface:
- `project/implementation-plan.md`

Purpose:
- describe the current execution contract for a bounded active work item

Allowed content:
- goal, scope, constraints, phases, current phase, validation, open questions
- execution ordering
- explicit verification blocks
- source set and distilled inputs when needed

Not allowed:
- broad permanent memory
- authoritative feature contract that should live in a stable spec
- archival history for completed work

An active plan is the current execution surface, not the durable source of truth for every future task.

### Temporary incubation artifacts

Canonical surface:
- `project/plan-incubation/*.md`

Purpose:
- hold unresolved synthesis, option comparisons, and temporary structure that outgrows short state bullets but is not yet a stable spec or active plan

Rules:
- temporary synthesis participates in the staged lifecycle `incubation -> research -> bounded plan decision -> carry-forward/closeout`
- one active incubation artifact per topic
- the artifact should preserve a stable topic identity; if new same-topic signal arrives, merge into the current artifact before creating another temporary note
- contradictions between same-topic temporary artifacts or between a temporary artifact and stronger canon must stay visible until resolved
- capture into incubation should be signal-driven; durable signals include constraints, repeated conclusions, rejected directions, dependencies, and durable choice points
- the artifact must be referenced from `project-state` or the active plan if it is still active
- MLH-owned incubation writes must create or normalize frontmatter with:
  - `status`
  - `topic`
  - `created`
  - `last_reviewed`
  - `references`
  - `promotion_target`
  - `superseded_by`
- provisional synthesis artifacts must not remain fate-less; their next inspectable outcome should be `merge`, `promote`, `retire`, or `archive`

Recommended compact shape:
- keep incubation artifacts short, decision-oriented, and easy to fold forward
- prefer compact headings such as `Goal Of Exploration`, `Current Decision Or Tension`, `Constraints And Evidence`, `Options Or Contradictions`, `Decision Boundary`, and `Next Inspectable Fate`
- merge new same-topic signals into those sections instead of appending chat chronology or transcript-like residue
- mark alternatives, contradictions, superseded ideas, and promotion targets inline where the reader can see the current topic shape without rereading the whole note
- split the note only when one markdown surface would otherwise mix unrelated problem statements, unrelated promotion targets, or unrelated next fates

Not allowed:
- acting as a shadow spec
- acting as an untracked second plan
- duplicating durable content that already lives in specs or memory

### Bridge promotion and handoff postures

Purpose:
- make the boundary between temporary incubation, durable research, and bounded plan-open explicit without creating a separate always-on bridge artifact class

Rules:
- bridge labels such as `incubation-only`, `research-ready`, `plan-candidate`, and `limited-confidence` are handoff postures, not a mandatory repo-wide frontmatter enum
- the workflow should record the current bridge posture in the relevant synthesis surface when that posture affects promotion, plan-open, or carry-forward decisions
- promotion posture is determined by evidence and boundary clarity, not by chat urgency, artifact age, or operator appetite to "just start"

`incubation-only` posture:
- keep the topic in incubation when the note still exists mainly to shape the problem, merge same-topic signal, surface contradictions, or name candidate promotion targets
- this posture is still valid when durable signals exist, but the topic lacks enough evidence shape, rejection discipline, or promotion clarity to justify a durable research memo
- same-topic refreshes should continue to follow `merge-before-create`

`research-ready` posture:
- a topic is ready to promote from incubation into durable research when the problem statement, durable signals, source linkage, and promotion direction are already inspectable enough to survive beyond one planning pass
- the promoted research artifact should preserve explicit implications, unresolved contradictions or rejected directions, and the boundary to neighboring lanes such as architecture, horizon, or tooling work
- research-ready promotion should remain compact and should not silently become an execution contract

`plan-candidate` posture:
- a research or spec-synthesis artifact becomes a plan candidate only when it defines enough boundary for a bounded active plan to open without depending on hidden chat memory
- minimum plan-candidate evidence includes the current problem and catalyst, the evidence class or provenance that supports the boundary, rejected or unresolved directions, make-or-break assumptions or thresholds, invalidation or recheck posture, and the next bounded deliverable or non-goals
- plan-candidate status authorizes bounded planning intake; it does not by itself authorize broad execution outside the accepted plan boundary

`limited-confidence` posture:
- if bounded planning is still cheaper than more research while some handoff evidence remains incomplete, the workflow may record an explicit limited-confidence plan candidate
- the missing evidence, why execution is still cheaper, and what must be rechecked later must stay inspectable in the handoff artifact or accepted plan
- limited-confidence posture is a bounded exception, not a shortcut around research discipline

### Reusable procedural surfaces

Canonical surface:
- reusable skills, checklists, or narrow helper procedures when they exist

Purpose:
- hold repeatable procedures that should not live in `project-state`
- keep multi-step operating playbooks out of stable contract docs unless they are themselves the contract

Examples:
- a repeatable planning checklist
- a repeatable verification checklist
- a narrow helper contract for distillation formatting

Rule:
- if a note is valuable because it describes a repeated procedure, its long-term home is a reusable procedural surface, not `project-state` and not an incubation note

### Verification artifacts

Canonical surface:
- active-plan verification block
- optional `project/verification/*.md` durable proof/evidence records

Purpose:
- capture verification evidence when the evidence is too important or too large to leave implicit

Default rule:
- keep verification inside the active plan unless the change is medium/high-risk, externally visible, policy-changing, or audit-heavy
- durable proof/evidence records are closeout assembly inputs only; they do not approve lifecycle changes or replace explicit closeout fields

### Historical archive

Canonical surface:
- `project/archive/plans/*.md`
- `project/archive/reference/**`

Purpose:
- preserve rationale and evidence after closeout

Archive is historical context, not default execution authority.

## Authority Rules

Authority depends on the kind of claim being evaluated.

### Current focus and canonical pointers

Winning surface:
- `project/project-state.md`

Examples:
- which workstream is active
- which plan is active
- which stable docs are the current canonical outputs

### Contract and architectural boundaries

Winning surface:
- stable specs
- decision docs if a later decision explicitly supersedes an older spec

Examples:
- workflow boundaries
- acceptance behavior
- allowed vs disallowed automation

### Research findings and imported evidence

Winning surface:
- `project/research/*.md`

Examples:
- which external approaches were compared
- which findings or uncertainties were distilled from a research pass
- what implications were recorded for future spec or plan work

Research artifacts can challenge or refine current direction, but they do not override stable specs until promotion or decision makes that change explicit.

### Current execution sequencing

Winning surface:
- active implementation plan

Examples:
- current phase
- next deliverables
- what validation belongs to the current execution block

### Verified completion evidence

Winning surface:
- verification artifact or explicit verified verdict

Examples:
- acceptance passed
- a block is validated
- a closeout gate was met

### Historical rationale

Winning surface:
- archived plans and older verdicts

Examples:
- why a past direction was abandoned
- how an older plan was structured

Historical artifacts may inform current work, but they do not override current state, current specs, or the active plan.

## Conflict Resolution

When artifacts conflict, use these rules:

1. `project-state` wins for active focus and canonical pointers.
2. Stable specs win over research artifacts, incubation notes, and chat residue on contract questions.
3. Research artifacts may refine or challenge current direction, but they do not override a stable spec until promotion or decision makes that change explicit.
4. A later decision doc may supersede an older stable spec when that supersession is explicit.
5. The active plan wins only for current execution sequence, not for durable contract meaning.
6. Archived plans are rationale only when they conflict with a current spec or current plan.
7. Incubation notes never override a stable spec or decision doc.
8. Chat residue never outranks repo artifacts on disk.

If a planner or operator finds a conflict that changes execution direction, the conflict must be surfaced explicitly in planning or verification output. It must not be silently smoothed over.

## Promotion Rules

Promote by repeated value and artifact fit, not by age alone.

- repeated project-wide convention or persistent working rule -> `project/project-state.md`
- durable architectural tradeoff with alternatives -> decision doc
- stable workflow or feature contract -> stable spec
- bounded imported research findings with reusable decision value -> research artifact
- execution sequence for one active work item -> active plan
- medium/high-risk verification evidence or audit trail -> verification artifact or verdict
- reusable checklist or repeatable procedure -> skill, checklist, or other reusable procedural surface

Do not promote a note into `project-state` just because it was mentioned twice if the real destination is a stable spec or repeatable checklist.

## Retirement and Archival Rules

- if an incubation artifact has been absorbed into a stable spec or active plan, mark it promoted and retire it from active use
- if an incubation artifact is no longer referenced, no longer active, and no longer shaping future work, mark it stale and archive or otherwise retire it explicitly
- unresolved, deferred, or needs-more-research directions should point to an explicit carry-forward destination instead of fading out by silence
- when many incubation notes have ambiguous fate, `incubation-reconcile --dry-run` may classify them from repo-visible roadmap, archive, promotion, supersession, and follow-up evidence; reviewed apply may write only diagnostic reconciliation metadata such as `lifecycle_status`, `resolution`, `resolved_by`, `superseded_by`, and `last_reconciled`
- do not silently delete temporary reasoning that still carries unique design signal
- archive entries should point to the winner artifact when one exists, or to the named carry-forward destination when promotion did not happen

The current workflow prefers explicit retirement over background cleanup.

## Lifecycle Status Vocabulary

The workflow should use explicit status language for temporary and transitional artifacts.

Preferred vocabulary:
- `draft`
- `accepted`
- `synced`
- `partially_verified`
- `drift_detected`
- `incubating`
- `active-reference`
- `promoted`
- `stale`
- `archived`
- `superseded`

Rules:
- `draft` means the artifact is recorded input or synthesis, not accepted authority
- `accepted` means the artifact may feed a plan or stable route through explicit lifecycle commands, not that implementation is done
- `synced` means the route's declared source and evidence match the latest recorded inspection
- `partially_verified` means some evidence exists but verification is incomplete or intentionally scoped
- `drift_detected` means route metadata, implementation, or evidence disagree and need explicit amendment or carry-forward
- `incubating` means the artifact is still shaping an unsettled direction
- `active-reference` means the artifact is temporary but still actively feeding planning
- `promoted` means its durable output now lives elsewhere
- `stale` means it is no longer current but still may retain rationale
- `archived` means it has left active circulation
- `superseded` means a newer artifact replaced it explicitly
- status changes are human-gated amendments; read-only reports may name the current state and next safe command but cannot promote, archive, verify, or synchronize an artifact by inference
- temporary artifacts should not linger indefinitely in `incubating` or `active-reference`; each provisional note should eventually resolve through `merge`, `promote`, `retire`, or `archive`
- reconciliation lifecycle classes such as `active-roadmap-source`, `archived-covered`, `promoted-compacted`, `orphan-needs-triage`, `duplicate-or-superseded`, and `still-live-followup` are diagnostic fate labels; by themselves they do not promote, retire, archive, or verify an incubation artifact

For stable specs, `spec_status` is the spec lifecycle and `implementation_posture` is the implementation/evidence relation. Read-only reconcile diagnostics may report `spec-posture-missing`, `spec-synced-without-verification`, `spec-target-only-has-implementation-evidence`, `spec-drift-detected-without-carry-forward`, or `spec-superseded-without-target`, but those findings only name review work. They do not rewrite accepted specs to match code, delete target-only specs, approve supersession, archive plans, or move lifecycle state.

This vocabulary is most important for routed lifecycle surfaces that need recovery and projection support. Durable specs and `project-state` remain canonical through their bodies and first-class lifecycle fields, but MLH-owned route writers should still write or preserve explicit frontmatter whenever they mutate Markdown in a route that uses metadata for checks, relationships, projections, or handoff.

## Anti-Patterns

The workflow must avoid:

- treating `project-state` as a narrative project diary
- storing feature contracts only inside `implementation-plan.md`
- storing imported deep research only as chat transcript or prompt residue
- keeping multiple active incubation files on the same topic without supersession
- using archive artifacts as default authority for current execution
- copying stable rules into temporary notes instead of linking to canonical docs
- introducing new hidden memory layers instead of improving the repo-native markdown surfaces
