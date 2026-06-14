---
spec_status: "accepted"
implementation_posture: "partially-verified"
---
# Generated State And Projections Spec

## Purpose

This spec defines the product boundary for generated views, caches, indexes, reports, and SQLite-backed projections.

Generated state is allowed when it increases leverage without absorbing authority. It is a speedup and diagnostic substrate, not a durable evidence store.

## Core Rule

Generated state is build-to-delete.

Every generated view, cache, index, report, or local database must be:

- rebuildable from repo-visible source files
- safely deletable
- subordinate to Markdown/YAML/file authority
- inspectable enough to trust
- source-bound or hash-bound where practical
- scoped to an explicit lifecycle and storage location
- fail-open to repo files
- current, explicitly dirty, or safely rebuildable before first-contact navigation treats it as trusted context

## Allowed Projection Content

Generated projections may contain:

- repo maps and AST-lite inventories
- backlinks and link graphs
- stale-link and stale-docmap checks
- exact search and optional FTS/BM25 search
- optional semantic readiness inspection and bounded no-runtime evaluation before any semantic search runtime
- context-budget analytics
- ceremony-budget analytics
- verification telemetry
- generated report indexes
- hashes, paths, or provenance fields that bind rows back to source files

## Forbidden Projection Authority

Generated state must not hold the only copy of:

- accepted decisions
- current focus
- `plan_status`
- active plan identity
- stable workflow authority
- carry-forward fates
- durable closeout evidence
- queues, schedules, hidden state machines, or issue-board truth

If deleting a projection changes what the harness believes, the projection is too authoritative.

## SQLite Boundary

SQLite is a first-class future projection/cache/index substrate, not canonical memory.

SQLite may accelerate search, backlinks, stale checks, context analytics, verification telemetry, and report discovery. It must remain disposable and rebuildable from repo files.

The implemented v0.16 SQLite search index is the first SQLite slice. It is scoped to:

- database path `.mylittleharness/generated/projection/search-index.sqlite3`
- explicit `projection --target index|all` lifecycle management
- source hashing, source-set hash, record-set hash, and row-count diagnostics
- line-level FTS5 rows bound to source path, line range, source hash, source role/type, indexed text, and provenance
- source-verified `intelligence --focus search --full-text TEXT [--limit N]`, plus `intelligence --query TEXT` expansion into omitted exact/path/full-text recovery modes, with relaxed OR behavior for plain multi-term recovery queries and explicit mode for uppercase FTS operators or control markers
- compact read-only `check` projection-cache posture for current, missing, stale, degraded, or unavailable generated inputs
- structured projection-cache posture payloads that report JSON artifacts and SQLite index status, source refs, next safe refresh commands, and bounded recovery commands such as `mylittleharness --root <root> mlhd run-once --apply` and `mylittleharness --root <root> projection --warm-cache --target all` without refreshing from read-only adapters
- automatic refresh for missing or stale path/reference artifacts and SQLite full-text indexes when `intelligence --path`, `--full-text`, or `--query` needs navigation cache
- stale, dirty, corrupt, or degraded generated-cache diagnostics include `next_safe_command=mylittleharness --root <root> projection --rebuild --target all`, which rebuilds only disposable generated output and cannot approve source, lifecycle, archive, roadmap, staging, or commit decisions
- existing projection artifacts and SQLite indexes are marked dirty after MLH lifecycle writes that change routed Markdown or lifecycle metadata, while missing cache remains a rebuildable degraded posture rather than hidden failure
- fail-open behavior when cache refresh is refused, degraded, corrupt, root/schema mismatched, or FTS5 is unavailable

The implemented semantic precursors are `semantic --inspect` and `semantic --evaluate`. They are no-write and terminal-only. `semantic --inspect` checks the current in-memory projection, projection artifact posture, SQLite FTS/BM25 index posture, deferred runtime posture, and report-only evaluation expectations before any embedding runtime or generated semantic index exists. `semantic --evaluate` runs fixed built-in evaluation queries against the current source-verified SQLite FTS/BM25 index when available, reports source paths, line numbers, query mode, rank, and source hash provenance for matches, and degrades to source-backed recovery findings when the index is missing, stale, corrupt, malformed, root-mismatched, or FTS5-unavailable. Neither command creates `.mylittleharness/generated/semantic/`, vector stores, embedding files, provider config, model downloads, reports, caches, or databases.

## Initial Product Priority

The first likely product surfaces, in order of payoff, are:

1. stale-pointer, link, and docmap consistency reports
2. repo-map, backlink, and search projection
3. context-budget and artifact-fan-in analytics
4. verification telemetry and circuit-breaker analysis
5. optional semantic readiness inspection and bounded no-runtime evaluation, then semantic retrieval only after exact/path/full-text search is reliable

The intelligence slice is report-first and source-verified. It exposes terminal-only repo-map, backlink, exact/path search, and fan-in summaries derived from an in-memory projection rebuilt from inventory-discovered repo surfaces plus cold memory routes on every run. Inventory-discovered live surfaces include nested coordination evidence under `project/verification/agent-runs/*.md`, `project/verification/handoffs/*.json`, `project/verification/handoffs/*.md`, `project/verification/work-claims/*.json`, `project/verification/approval-packets/*.json`, and Symphony queue snapshots under `project/symphony/queue/*.json`, so worker-written handoffs and dependent queue items are discoverable without waiting for generated cache. Cold memory routes are archived plans under `project/archive/plans/*.md` and archived reference material under `project/archive/reference/**/*.md`, including archived research, decisions, ADRs, and verification records; they are not startup authority, but they are included in recovery search and relationship projection when present. Exact-only and no-query invocations do not need generated cache writes. Path/reference and full-text navigation may refresh disposable projection artifacts or the SQLite index inside the owned generated-output boundary when missing or stale. The projection includes source records, link/backlink records, fan-in records, relationship graph records, source hashes when readable, and summary counts. For live operating roots, product-source target artifact references use a `product-target` link or relationship status so generated navigation does not require clean product files to live inside the serviced operating root. Those records are source-bound by path and line where available, but the in-memory projection and generated cache are not authority.

Attachment cards under `project/attachments/**/artifact.md` participate in the same source-verified projection. The projection may report the card path, attachment kind/status/title, adjacent original binary path, `sha256`, `size_bytes`, `mime_type`, provenance refs, and relationship refs such as `attachment_refs`, `source_attachments`, `related_attachments`, and `related_research`; it must not copy binary bodies or treat generated attachment rows as evidence authority. The sidecar card remains the metadata authority and the original binary remains source evidence.

## Owned Projection Artifact Boundary

The first owned persistent generated-output boundary is:

`.mylittleharness/generated/projection/`

This boundary may contain only rebuildable JSON projection artifacts and the SQLite search index:

- `manifest.json`
- `sources.json`
- `source-hashes.json`
- `links.json`
- `backlinks.json`
- `fan-in.json`
- `relationships.json`
- `summary.json`
- `search-index.sqlite3`
- known same-basename SQLite sidecars while SQLite is active

These artifacts are built from the in-memory projection and remain disposable, rebuildable, source-bound, subordinate, and safe to delete. They may contain paths, roles, counts, link/backlink records, fan-in records, relationship graph nodes and edges derived from repo-visible relationship metadata, source hashes, root identity, schema version, manifest payload hashes, source-set hash, record-set hash, query capability metadata, and projection summary counts. They must not copy source file bodies or hold accepted decisions, current focus, plan status, active plan identity, durable closeout evidence, repair approval, archive actions, commit actions, or lifecycle authority.

The SQLite index may store indexed source text as generated cache content. Lifecycle terms may appear there only because they appeared in repo-visible source text; SQLite schema and metadata must not create generated lifecycle authority fields.

The `projection --build|--inspect|--delete|--rebuild|--warm-cache [--target artifacts|index|all]` CLI surface owns this boundary. `projection --inspect --target ...` is read-only advisory output and must render read-only Work Result wording; it does not build, refresh, delete, or authorize generated cache. `projection --build`, `projection --rebuild`, and `projection --delete` are the bounded generated-output write/delete paths, and their Work Result summaries must name the selected mode rather than borrowing a delete-only or generic projection summary. `projection --warm-cache --target artifacts|index|all` is a single foreground watcher tick: it may refresh missing, dirty, stale, corrupt, or unavailable generated cache inside this boundary, installs no daemon, and records no lifecycle truth. Projection writers create a temporary `cache-operation.json` marker inside the generated boundary while artifacts or the SQLite index are being deleted or written; read-only inspect/check/dashboard/adapter surfaces report that marker as an `updating` posture with a rerun hint instead of treating a transient missing file as durable cache state. Artifact refresh publishes all JSON payloads through a rollback-capable file transaction, and SQLite refresh builds in a temporary database before replacing the old index; if refresh fails before a complete publish, old-good artifacts or the old-good index remain the only generated input. Dirty markers record the invalidating command, changed paths, and `dirty_since_utc` so read-only pulse surfaces can distinguish idle, warmable, and updating/interrupted cache posture. MLH lifecycle write paths that mutate routed Markdown or lifecycle metadata must invalidate any existing projection artifacts and SQLite search index by writing those dirty markers, or leave missing cache in an explicit rebuildable posture. Successful `init --apply` and compatibility `attach --apply` also run the equivalent generated setup for `--target all` after attach authority files are in place, so first-run intelligence can use current projection artifacts and a source-verified SQLite index when FTS5 is available. `--target artifacts` manages schema v2 JSON artifacts, including `relationships.json`, refuses directory-shaped expected JSON artifact paths during delete, and does not recursively remove malformed artifact directories. `--target index` manages only `search-index.sqlite3` plus known same-basename SQLite sidecars and reports directory-shaped sidecars as preserved skips. `--target all` manages both. Inspect reports missing, updating, stale, dirty, corrupt, stale v1, schema/root/count/hash mismatch, malformed payloads or tables, unexpected boundary/index files, incomplete states, unsupported FTS5, and failed SQLite integrity checks. Reports fail open to direct repo files and the in-memory projection when generated output is missing, in progress, or unusable.

Successful MLH apply routes that mutate routed Markdown or lifecycle metadata must also refresh an existing generated source-bound context-memory capsule from a freshly reloaded inventory. The capsule refresh writes only `.mylittleharness/generated/context-memory/`, does not bootstrap that generated boundary on roots that have not opted into capsules yet, keeps source files and lifecycle routes authoritative, and reports a warning rather than converting generated-cache failure into lifecycle truth when reload or publish fails. Recovery and first capsule creation remain the explicit `mylittleharness --root <root> mlhd run-once --apply` rail.

Structured cache posture emitted by `check`, `dashboard`, hooks, and the MCP adapter must keep that same ownership line. It may expose `self_healable_by_command=true`, `self_heal_command=mylittleharness --root <root> mlhd run-once --apply`, `manual_recovery_command=mylittleharness --root <root> projection --warm-cache --target all`, `displayed_commands_only=true`, `read_only_surfaces_execute_refresh=false`, `navigation_surfaces_may_refresh_generated_cache=true`, `generated_cache_mutation_boundary=.mylittleharness/generated/projection`, and `manual_recovery_write_class=disposable-generated-cache-only`. Its `command_boundary` object must classify `selfHealCommand` as an explicit apply command that writes disposable runtime evidence plus optional generated cache, classify `manualRecoveryCommand` as an explicit generated-cache-only command, and classify `navigationCacheRefresh` as an explicit `intelligence --query|--path|--full-text` navigation action that may refresh only disposable generated projection cache without `--apply`. These command-boundary entries must say read-only surfaces do not invoke refresh and cannot approve lifecycle, archive, roadmap, staging, commit, push, release, source-truth, or cache-truth decisions. `recommended_refresh_commands` are display/forward suggestions only; machine consumers should prefer `recommended_refresh_actions` when they need command write-class metadata. They must not silently rebuild cache, treat current cache as lifecycle truth, or hide stale/missing/degraded posture from first-contact users.

The mlhd daemon contract is optional and disabled by default; runtime storage stays under `.mylittleharness/runtime/mlhd/` and remains disposable adapter data. The implemented `mlhd` control plane exposes `status`, `doctor`, `start`, `stop`, `run-once`, `install`, and `uninstall` as explicit foreground commands: status, doctor, and dry-run modes are read-only, while apply modes write only pid, lock, heartbeat, state, event, projection-refresh, last-run-once, and root-local autostart manifest markers under the runtime boundary. `run-once --apply` may also invoke the explicit projection warm-cache rail after dirty markers have remained past the configured quiet period; that refresh stays inside `.mylittleharness/generated/projection/`, preserves old-good JSON artifacts and SQLite indexes on failure, and records only disposable runtime pulse evidence. The same tick refreshes the source-bound context-memory capsule inside `.mylittleharness/generated/context-memory/`, and `mlhd start --apply` launches a local polling worker that repeatedly runs that generated freshness tick without creating a filesystem watcher or lifecycle authority. `mlhd install --apply` writes a deterministic root-local `autostart.json` manifest with `<root>` command templates, and `mlhd uninstall --apply` removes that manifest. No daemon process, listener, scheduler, filesystem watcher, OS/user autostart entry, or supervision process is created by attach, repair, dashboard, check, hooks, MCP, projection, or `mlhd` control-plane commands. Daemon process autostart or supervision beyond the root-local manifest requires a later reviewed dry-run/apply rail, and foreground daemon ticks must not make generated cache freshness, lifecycle movement, archive status, roadmap status, Git state, release posture, or provider routing authoritative.

Freshness surfacing follows the same generated-state boundary. Dashboard, check, MCP read_projection, and hook payloads may expose `mlhd` control status, runtime-cache status, pid status, last tick/action, projection dirty counts, last refresh/success/failure timestamps, and a next safe command alongside `connectReadiness` and `agentPacket` posture. Those fields are derived from repo-visible routes plus disposable runtime/projection markers; they are navigation cues only and cannot turn a current cache into lifecycle truth.

`detach --dry-run` and marker-only `detach --apply` preserve `.mylittleharness/generated/projection/` when present and propose no cleanup, deletion, rebuild, archive, or projection apply action. Generated projections remain disposable speedups whose presence cannot authorize detach, repair, closeout, archive, commit, lifecycle decisions.

Path/reference artifact rows may be compared with the current in-memory projection during focused path search. Exact text search remains source-only and includes cold memory route bodies directly when they exist. `intelligence --query TEXT` is a convenience expansion over the same exact/path/full-text modes: it fills omitted exact text, path/reference, and full-text query values with `TEXT`, while explicit mode-specific flags keep their own values. When path/reference or full-text modes need generated cache, `intelligence` inspects the current artifacts/index, refreshes missing or stale cache inside `.mylittleharness/generated/projection/` when the boundary is safe, and reports degraded posture if refresh is refused or unavailable. Full-text search uses the SQLite FTS/BM25 index only when the index is current and each result is verified against current source files, including cold archived source files. Plain multi-term full-text input is relaxed into an OR query over indexable terms for recovery search, while explicit uppercase FTS operators such as `AND`, `OR`, `NOT`, or `NEAR`, quoted input, and other FTS control markers keep explicit query mode.

Bare `check` includes a compact `Projection Cache` section that inspects generated artifact and SQLite index freshness without writing or refreshing anything, plus a structured `projection-cache-posture` finding for clients that need machine-readable component status and refresh commands. Missing, stale, dirty, corrupt, root-mismatched, or unsupported generated inputs are reported as navigation posture; direct repo files, repo-visible files, and the in-memory projection remain authoritative, and query-time `intelligence` refresh remains the bounded write path when navigation actually needs generated cache. `dashboard --inspect` and its structured payload may include an `mlhd.projection_pulse` object derived only from dirty markers and operation markers; the pulse can recommend `projection --warm-cache --target all` and distinguish idle, warmable, and updating/interrupted posture, but it is disposable cockpit guidance and cannot become cache freshness or lifecycle authority. Dashboard detail defaults to `auto`: small roots may include the complete in-memory projection, while large roots return a bounded degraded cockpit with inventory counts, a truncated source sample, quick cache posture, `connectReadiness`, `agentPacket`, `mlhd` freshness, and explicit full-projection guidance without calling the full projection builder. `dashboard --inspect --detail degraded` is always bounded, and `dashboard --inspect --detail full` is the explicit opt-in for complete source/link/fan-in projection counts. Degraded dashboard counts that depend on link/fan-in traversal are skipped or reported as degraded summary fields, not as cache truth. The read-only MCP adapter follows the same boundary: `adapter --inspect --target mcp-read-projection`, `adapter --client-config --target mcp-read-projection`, and foreground stdio serving report source records, generated-input posture, structured `cachePosture`, default-active rootless client configuration, optional per-call `root` selection, and helper metadata without writing user config, creating adapter state, installing scaffold, creating lifecycle debris, or refreshing caches. Rootless MCP serving has no startup authority root; each tool call selects a root or fails read-only. `mylittleharness.search` reloads the selected root inventory into an in-memory projection for exact and path matches on every call, returns structured `cachePosture`, and reports when generated artifacts or the SQLite full-text index are stale or missing; exact/path MCP search still sees fresh repo-visible writes, while full-text may skip until `mlhd run-once --apply` or `projection --warm-cache --target all` refreshes disposable cache. The Codex first-contact hook adapter is a separate project-local rail: `hooks adapter --client codex --dry-run|--apply --scope project` may register `SessionStart` in `.codex/hooks.json`, and that hook forwards the same dashboard/cache/MCP posture through a Codex-specific minimal SessionStart stdout envelope derived from `hooks --run session-start --json` without refreshing cache or approving lifecycle. First-contact MCP/dashboard/hooks/SQLite consumers must prove current cache, expose a dirty/missing/stale/degraded posture, or point to the bounded rebuild/warm-cache rail before presenting generated context as usable acceleration. The first-contact accelerator packet must also say that exact source verification remains required with `rg` or bounded file reads after any MCP, dashboard, hook, SQLite, or generated-cache shortcut. When an MCP client exposes `mylittleharness.read_projection`, agents should use it as an optional read/projection helper before or alongside CLI/file reads for route discovery, relationship lookup, projection context, impact checks, and switching inspection between MLH-serviced roots. The tool reloads the selected root inventory in memory for each call, accepts `detail=auto|full|degraded`, omits source bodies, and keeps generated projection artifacts and SQLite indexes optional; its output remains advisory and cannot approve lifecycle decisions. `detail=auto` may fail soft on large roots by returning a bounded degraded packet with source count/size hints, a truncated source sample, cache posture, `mlhd`/connect-readiness posture, and explicit next-safe refresh commands without rebuilding the full projection. `detail=full` remains the explicit complete in-memory projection request, and `detail=degraded` is an always-bounded summary. Degraded MCP output must not hide that full projection was skipped, must include a `fullProjectionRequest` hint for `detail=full`, and must point back to direct source reads or generated-cache refresh rails for exact verification.

Semantic readiness and no-runtime evaluation may report this projection/search base, but semantic retrieval matches are not implemented. `semantic --evaluate` uses fixed product probes only and does not accept arbitrary semantic query text. Any future semantic output location must be introduced by a later scoped plan with an explicit storage boundary, rebuild/delete behavior, stale/corrupt diagnostics, offline degraded behavior, and source verification.

## Non-Goals

- No generated truth.
- No generated evidence database or generated closeout authority.
- No hidden control plane.
- No mandatory database for recovery.
- No persistent exact-text index in the schema v2 JSON artifact slice.
- No semantic retrieval runtime, arbitrary semantic query surface, embedding store, vector store, provider-backed search, or generated semantic output in the readiness/evaluation slices.
- No auto-repair from projection results without an explicit mutation plan.
- No product-root generated debris outside `.mylittleharness/generated/projection/` unless a later product plan deliberately owns another output location.
