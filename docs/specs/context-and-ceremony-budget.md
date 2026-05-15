# Context And Ceremony Budget Spec

## Purpose

This spec defines how MyLittleHarness keeps context loading and workflow ceremony small enough for solo-first work while preserving authority, safety, and recovery.

The harness should help an agent start cheaply, load details just in time, and escalate only when risk justifies more structure.

## Authority

The operating root owns current focus, active plan status, research intake, and closeout evidence for the repository MyLittleHarness is servicing. Product docs define reusable rules and gates. Generated summaries, search results, metadata, adapters, and background task state are support surfaces only.

For the portable clean-room posture, the target repository owns active memory and research, while the product repository owns reusable docs/source. Legacy reference material is opened only for a named blocker. MyLittleHarness must remain a direct product for an explicit target repository.

The canonical start pass should be driven by explicit repo-visible files, not broad historical context or adapter memory.

## Non-Authority

The following must not become authority for task scope or completion:

- raw context dumps
- old chat transcripts by themselves
- generated summaries without source pointers
- search rankings
- semantic retrieval guesses
- background-agent state
- browser, IDE, MCP, plugin, hook, GitHub, or CI state
- ceremony checklists without observed verification evidence

More context is not more authority. More process is not completion.

## Current Contract

Start passes should be cheap. Load the canonical project state first, then the active plan only when plan status or the user request makes it relevant. Load problem reports, product docs, specs, and source files just in time.

Before mutation, the agent needs one planning gate that names the intended edits, reason, validation, assumptions, and boundaries. Small ad hoc tasks may proceed directly when the scope is narrow, the blast radius is low, and no durable multi-session state is needed.

Escalate to a full implementation plan when work is multi-session, high-risk, cross-root, contract-changing, hard to validate, or likely to require closeout evidence.

Every rendered report includes an adaptive ceremony capsule in `Work Result`: the expected operator cost, the safety guarantee preserved by the current command, and the next safe command or route-discovery step. The capsule is advisory and must point toward dry-run/apply rails without approving lifecycle movement, archive, staging, commit, or push. `suggest` reports must keep command candidates distinct from required follow-up: the next safe command may tell an operator to choose a matching `first_safe_command`, while "what remains" must still say those command routes are advisory and approve no apply or lifecycle action by themselves. Read-only advisor modes embedded in mutating command families, such as `memory-hygiene --dry-run --scan`, must use read-only scan wording instead of generic preview/apply wording; they may point at explicit per-source dry-runs and emit covered-candidate proposal ids/tokens, but must not advertise a matching scan apply. Read-only reports with warnings must keep the no-write guarantee read-only rather than implying the report has a matching apply continuation. No-op previews must avoid empty apply guidance when diagnostics say no repair, compaction, archive, or generated-cache refresh is needed for the current posture. Refused dry-run previews, including meta-feedback destination refusals, must say the preview was refused before a reliable apply target existed and must not present candidate/cluster details as reliable completion. Structured JSON reports also expose finding-derived `next_safe_routes` so bench-style checks can evaluate whether diagnostics provide a concrete first dry-run route without treating that route as approval.

When a plan phase reaches `phase_status = complete`, the handoff must be recoverable from repo-visible phase evidence instead of chat memory. The minimum phase evidence capsule is the current-plan closeout/writeback identity plus `docs_decision`, `state_writeback`, `verification`, and `work_result`; `docs_decision = uncertain` is allowed for a provisional same-plan phase handoff, but it cannot support confident final closeout. `work_result` check labels accept the canonical `How it was checked:` plus semantic aliases such as `How checked:` and `Verification:`; unrelated mentions of verification elsewhere in the capsule do not count as a check label. A phase-only `writeback` may replace stale closeout facts with same-request provisional phase evidence when advancing to the next pending phase, but that still does not approve archive, roadmap done-status, staging, commit, push, or next-plan opening.

Context budgets should favor:

- source-set discipline over broad archaeology
- repo impact maps over full repo scans
- compact summaries over pasted raw intake
- named exclusions for old fallback context
- short durable state writeback when focus or plan phase changes
- independent review only when risk justifies it

Sub-agents and background work are optional bounded helpers. They require explicit user authorization and must return compact results to the main context.

The implemented live operating-memory hygiene threshold is intentionally narrow: after explicit live-root writeback or plan state writes, and through explicit `writeback --dry-run|--apply --compact-only`, `project/project-state.md` above 250 lines or 25,000 characters may be compacted by moving older history sections into `project/archive/reference/` while preserving current focus, memory routing roadmap, repository role map, short notes, the latest relevant update, closeout writeback facts, and an archive pointer. Compact-only dry-run reports the current project-state sha256, and compact-only apply requires the matching `--source-hash` when compaction would write so reviewed bytes cannot silently drift between preview and apply. Read-only context-budget measurements for product docs, specs, or reports remain advisory and do not write files; size alone is warning pressure only for primary instruction surfaces such as guardrails, manifest, state, README, docmap, or an active plan.

Working-memory compaction stays repo-visible across routes. Project-state history uses the source-hash guarded compact-only rail, verification ledgers use `memory-hygiene --rotate-ledger` with source-hash guarded archive continuity ledgers, and memory-hygiene cleanup candidates remain scan proposals until a per-source dry-run/apply or later reviewed proposal-token rail is used. These routes do not create provider memory, hidden databases, daemons, closeout authority, roadmap movement, Git authority, or dependency adoption.

The agent-navigation reflex is budgeted and trigger-based. For fuzzy route discovery, impact checks, lifecycle posture questions, unclear source ownership, or product-source boundary questions, agents should start with `dashboard --inspect` or `dashboard --inspect --json` for the compact cockpit/agent packet, then use `intelligence --query "<topic>"` or `intelligence --focus routes`, optional rootless MCP projection helpers, and `suggest --intent "<operator-action>"` before choosing a dry-run/apply rail. Exact filename, symbol, or literal text lookup stays on direct `rg` or file reads. The reflex is read-only navigation guidance: it does not create a daemon, store memory, refresh generated caches from an adapter, replace source verification, approve lifecycle movement, or require extra chat ceremony once the next safe command is clear.

Native hook first-contact uses the same cheap-start posture. `hooks --run session-start` and `hooks --run session-start --json` may surface the dashboard agent packet, next legal dry-run candidate, MCP adoption posture, and projection/SQLite cache posture to a client at session start. `hooks --doctor` reports this command separately from the optional Git pre-commit shim because Git hook installation does not make a native client call session-start. That is a context shortcut, not an authority shortcut: the hook must not install client config, start a listener, refresh generated cache, skip canonical route reads when exact authority is needed, approve auto-continuation, or decide lifecycle, Git, dispatcher, provider, product-diff, archive, staging, commit, push, or release actions.

Local product-source test discovery is part of that low-ceremony route guidance: `suggest --intent "run product tests"` may surface `python -m unittest discover -s tests`, focused unittest gates, product `check`, and `git diff --check` when those commands are visible in the repo. It remains advisory verification guidance and does not install pytest, infer package-manager fallbacks, approve release, or satisfy lifecycle closeout by itself.

## Future Product Gates

Before implementing context or ceremony tooling, a later scoped plan must define:

- start-pass profiles for read-only, ad hoc, plan, and closeout work
- impact-map format and routing rules
- context budget warnings and thresholds
- ceremony escalation criteria
- summary shape for long sessions
- background task status and recovery boundaries
- verification anchors for plan, integration, and closeout blocks
- tests or smoke scenarios for small tasks, plan tasks, and closeout

Measured thresholds should come after qualitative guidance proves useful.

## Validation Expectations

A valid implementation should prove that:

- small ad hoc tasks avoid unnecessary planning ceremony
- mutating work still has a clear pre-write boundary
- active plans are loaded only when relevant
- unrelated historical context is excluded by default
- generated summaries point back to source files or explicit observations
- background work cannot become hidden authority
- closeout cannot be declared without observed verification or explicit verified skip

Validation may include smoke scenarios for read-only explanation, small mutation, multi-session planning, and closeout.

## Explicit Non-Goals

- No new always-on router, scheduler, daemon, dashboard, or control plane.
- No required background agents.
- No broad token-budget enforcement beyond the narrow 250-line or 25,000-character live state compaction threshold behind explicit writeback/plan write paths or compact-only writeback.
- No broad import of old research or archives.
- No ceremony checklist that substitutes for verification.
- No automatic thread renaming or user-global configuration changes.
- No implementation of tooling from this spec without a later scoped plan.
