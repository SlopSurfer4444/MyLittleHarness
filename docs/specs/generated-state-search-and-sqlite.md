# Generated State Search And SQLite Spec

## Purpose

This spec extends the generated-state contract for persistent search, backlinks, repo maps, indexes, telemetry, and SQLite-backed projections.

Generated projections may improve speed and review quality. They must remain rebuildable, disposable, and subordinate to repo-visible files. They are not durable evidence history.

## Authority

Files hold authority. Product contracts live under `docs/...` in the product repository. Active memory and plans live in the target repository. Legacy reference material is opened only for a named blocker.

Generated search indexes, backlink graphs, repo maps, reports, and SQLite databases may point to authority. They do not own authority.

Every generated row, record, edge, or search result should be bound back to source files through paths, hashes, mtimes, Git object IDs, or equivalent provenance where practical.

## Non-Authority

Generated state must not hold the only copy of:

- accepted decisions
- current focus
- `plan_status`
- active plan identity
- stable workflow rules
- carry-forward fates
- root identity status
- durable closeout evidence
- repair approval
- queues, schedules, hidden runtime state, or issue-board truth

If deleting a projection changes what the harness believes, the projection is too authoritative.

## Current Contract

Generated state is build-to-delete.

Search, backlinks, repo maps, link checks, stale-doc reports, context analytics, ceremony analytics, verification telemetry, and SQLite projections are future product capabilities. They may be persistent enough to reduce latency, but they must remain recoverable from source files.

The intelligence slice implements terminal reports over inventory-discovered surfaces. It rebuilds an in-memory projection from `Inventory` on every run and may derive repo-map rows, backlink references, exact text matches, path/reference matches, fan-in summaries, relationship graph records, source hashes, source coverage, and record counts from that projection. Successful `init --apply` and compatibility `attach --apply` build schema v2 JSON artifacts plus the SQLite FTS/BM25 search index under `.mylittleharness/generated/projection/` as first-run disposable generated output, and the separate `projection` command remains the manual refresh/recovery surface. Later `intelligence --path`, `--full-text`, or `--query` runs may refresh missing or stale disposable cache inside that same boundary before reporting current source-verified navigation results. These generated outputs are not telemetry stores, evidence databases, closeout history, or canonical memory.

The exact/path search baseline is case-sensitive and path-bound. Exact text search reads direct source content through the in-memory projection and does not need generated cache writes. Focused path search can compare valid artifact path/reference rows with the current in-memory projection, and full-text search can use a current source-verified SQLite index; when those generated inputs are missing or stale, `intelligence` may rebuild them inside `.mylittleharness/generated/projection/`. Generated JSON artifacts do not answer text queries because they do not store source bodies. `intelligence --query TEXT` expands a single recovery query into any omitted exact text, path/reference, and full-text modes without changing those source-verification rules; explicit mode-specific flags keep their own values. Results include source paths and line numbers when available so operators can inspect repo-visible files directly.

`intelligence --query` is the default read-only navigation rail for fuzzy agent questions about routes, impact, lifecycle posture, product-source ownership, and source-discovery starting points. It may refresh disposable projection cache inputs when path or full-text modes need them, but the result is still a source-bound candidate list. Exact symbol, filename, and literal text questions should continue to use direct `rg` or bounded file reads, and any mutation must still move through the owning MLH dry-run/apply command or a scoped source edit.

The MCP read/projection adapter exposes the same source-verification posture without taking ownership of generated state. `mylittleharness.search` may report exact direct-source matches, projection path/reference matches, and current SQLite FTS/BM25 matches when the index already passes read-only inspection, but the adapter does not refresh missing, dirty, stale, malformed, or corrupt generated caches. `mylittleharness.read_source` returns only a bounded source line slice selected by root-relative path, start line, and limit. `mylittleharness.related_or_bundle` returns nearby projection metadata and graph/link rows without source bodies. These adapter tools are navigation helpers only; deleting generated cache still cannot change lifecycle truth, and cache refresh remains owned by explicit `projection` or `intelligence` paths.

First-contact consumers that use MCP, dashboard JSON, hooks, or SQLite search must surface cache freshness and recovery explicitly. Structured cache posture may include `self_healable_by_command=true` and `self_heal_command=mylittleharness --root <root> projection --warm-cache --target all`; clients can show that foreground command, but they must not auto-run it from a read-only adapter or hide stale/missing/degraded cache posture behind a successful search response.

Read-only projection paths may fail open to direct file reads when an index is missing, stale, corrupt, or unavailable. Mutating paths must fail safe if a projection is the only evidence for a write decision.

SQLite is an optional projection/cache/index substrate. It may accelerate FTS/BM25 search, backlinks, repo maps, stale checks, telemetry, and report discovery. It must not become canonical memory.

Persistent projections should support incremental refresh by source hash, mtime, Git object identity, or content hash where practical, plus a full rebuild path for trust recovery.

The current persistent projection slice includes two targets. `--target artifacts` supports full JSON build, inspect, delete, rebuild, and optional warm-cache behavior. Schema v2 artifacts include manifest payload hashes, source-set hash, record-set hash, query capability metadata, and `relationships.json` lifecycle relationship graph rows derived from repo-visible relationship metadata. `--target index` supports build, inspect, delete, rebuild, and optional warm-cache behavior for `.mylittleharness/generated/projection/search-index.sqlite3`; `--target all` is the attach-time setup model. Projection writers publish a temporary generated-boundary operation marker while deleting or writing cache files, so concurrent `check`, `projection --inspect`, or intelligence reads can report an updating/rerun posture instead of a misleading durable missing/stale cache state. `projection --warm-cache --target artifacts|index|all` is a single foreground watcher tick that may refresh missing, dirty, stale, corrupt, or unavailable generated cache state inside `.mylittleharness/generated/projection/`; it installs no daemon, records no lifecycle truth, and degrades to direct source reads when refresh fails. The SQLite schema includes metadata, source records, row records, and FTS5 rows for line-level BM25 retrieval. Metadata records schema/product version, root identity, source-set hash, record-set hash, counts, query capabilities, and advisory generated-output posture. Rows bind back to source path, source hash, source role/type, line range, indexed text, and provenance. Source-verified full-text search reports the effective query mode: plain multi-term input relaxes to an OR query over indexable terms for recovery search, while explicit uppercase FTS operators such as `AND`, `OR`, `NOT`, or `NEAR`, quoted input, and other FTS control markers keep explicit query mode. SQLite may store source text as generated cache content, but schema and metadata must not create lifecycle authority fields. Missing, stale, updating, damaged, or FTS5-unavailable generated output degrades to direct file reads if refresh cannot produce current cache. A first-contact accelerator path may prefer a current SQLite index for speed, but it still ends with source-backed `rg`/file verification before any conclusion or mutation.

`semantic --inspect` and `semantic --evaluate` are the implemented semantic precursors. `semantic --inspect` reports the current in-memory projection, projection artifact posture, SQLite FTS/BM25 index posture, deferred runtime posture, and evaluation expectations for future semantic retrieval. `semantic --evaluate` runs fixed built-in evaluation cases against the current source-verified SQLite FTS/BM25 index when available, including broad semantic terms, stale/degraded wording, lifecycle-risk terms, and a negative no-match probe. It reports source path, line number, query mode, rank, and source hash provenance for verified matches, and degrades to source-backed recovery findings when the index is missing, stale, corrupt, malformed, root-mismatched, or FTS5-unavailable. It is not semantic search: it has no arbitrary query input, embedding runtime, provider integration, generated semantic index, vector store, report file, or model dependency.

## Future Product Gates

Before expanding beyond the v0.16 exact/path/full-text slice, a later scoped plan must define:

- generated-output location and cleanup boundary
- projection ownership and lifecycle
- rebuild command or API
- delete/recover behavior
- incremental refresh strategy
- provenance fields and source binding
- stale/corrupt index diagnostics
- schema ownership for any new SQLite tables or generated stores
- exact/path search behavior before semantic retrieval
- tests for rebuild, deletion, stale data, corrupt data, and fail-open reads

Semantic retrieval requires a later gate after exact/path/full-text search, source-bound projections, readiness inspection, and evaluation expectations are reliable.

## Validation Expectations

A valid implementation should prove that:

- all generated outputs can be deleted without losing authority
- full rebuild restores the projection from repo files
- stale projections are detected or clearly degraded
- optional warm-cache watcher ticks can be absent, fail, or encounter damaged cache state without blocking check, repair, init, direct file fallback, or lifecycle truth
- read paths can fall back to direct files
- write decisions do not rely only on projection data
- SQLite rows point back to source files and full-text results are source-verified
- product-root generated debris is not created outside an owned output boundary

Validation should include both fast incremental refresh and full rebuild scenarios once implementation exists.

## Explicit Non-Goals

- No semantic search implementation beyond readiness inspection and bounded no-runtime evaluation.
- No backlink graph, repo-map database, telemetry store, or generated report artifact beyond the v0.16 search index.
- No embedding runtime, vector store, provider-backed retrieval, generated semantic index, model download, arbitrary semantic query surface, or semantic generated-output boundary in the readiness/evaluation slices.
- No persistent exact-text artifact search because source bodies are not copied into projection artifacts.
- No projection-based authority.
- No generated evidence database or generated closeout authority.
- No hidden control plane, scheduler, queue, or daemon.
- No auto-repair from generated reports.
- No generated output inside the product source checkout outside `.mylittleharness/generated/projection/` without a later product plan owning its location.
