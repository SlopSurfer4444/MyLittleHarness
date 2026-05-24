# Adapter Boundary Spec

## Purpose

This spec defines how MyLittleHarness treats optional integrations such as skills, plugins, MCP, browser tools, IDEs, Git/GitHub/CI, hooks, issue trackers, and task runners.

Adapters can help.
Adapters cannot own correctness.

## Adapter Rules

All adapters must:

- fail open to repo files
- keep accepted decisions in file-visible authority surfaces
- avoid adapter-only memory
- avoid hidden mutation
- expose failures clearly
- remain optional for recovery
- preserve the product/operating root boundary

No adapter may become the only way to recover current focus, plan status, accepted decisions, stable rules, or closeout evidence.

Optional wrappers such as Codex skills, IDE rules, shell aliases, preflight wrappers, MCP clients, hooks, CI jobs, and future adapter packs may derive prompts or ergonomics from the repo-visible contract. They must not become the first-run path, docs-decision path, repair path, verification path, closeout path, or the only location for accepted decisions.

When an MCP client exposes `mylittleharness.read_projection`, `mylittleharness.search`, `mylittleharness.read_source`, or `mylittleharness.related_or_bundle`, agents may use those tools as the projection leg of the agent-navigation reflex before or alongside CLI/file reads for route discovery, relationship lookup, source snippets, and impact checks. That use is optional and read-only. It cannot replace direct source verification, refresh generated caches from the adapter, create adapter-owned memory, or decide the lifecycle rail.

The Codex MCP adoption rail is explicit helper setup, not hidden workflow state. `adapter --client-config --target mcp-read-projection` reports the default-active rootless/router-style client configuration, current mount posture, no-secret boundary, first-pass commands, and idempotent merge metadata without writing. `adapter --install-client-config --target mcp-read-projection --dry-run|--apply` is the only implemented client-config mutation: dry-run previews the managed block, and apply may write only the reviewed Codex config target with an idempotent managed server table, an existing-file backup, replacement of the legacy MLH root-bound server table when it exactly matches the old managed shape, refusal on unmanaged conflicts or unreadable/invalid config, and no config-value or secret echo. Installing the client config may make the MCP helper available to future client sessions, but it cannot replace `check`, direct `rg`/file verification, or MLH dry-run/apply lifecycle rails.

## V2 External Orchestrator Boundary

The v2 architecture treats external orchestrators, model providers, MCP servers, generated indexes, and notification relays as embassies around MLH's deterministic State. They may inspect route law, receive role packets, produce patches, record run evidence, transport approval packets, or help humans review work. They must not become lifecycle authority.

The first v2-compatible adapter contract is read/projection and report legibility:

- external clients can ask for route, role, gate, evidence, and generated-map posture;
- `manifest --inspect --json` exposes `route_manifest` and advisory `role_manifest` data for orchestrator packet setup;
- route entries expose advisory orchestration fields such as `parallelism_class`, `authority_lane`, `claim_scope`, `merge_policy`, `fan_in_gate`, and `max_parallelism_hint`, with lifecycle routes remaining `sequential_only` and coordinator-owned;
- role entries expose advisory coordination fields such as `orchestration_role`, `may_spawn_workers`, `worker_space_boundary`, `isolation_contract`, `fan_in_output_required`, and `coordination_budget`, with worker spawning false by default;
- route/role manifests are advisory until an MLH apply rail writes repo-visible authority;
- provider/model/tool routing is policy metadata before it is runtime ownership;
- optional relay adapters may transport approval packets only after core packets and review tokens exist;
- relay, provider, model, MCP, or generated-index state cannot approve closeout, archive, repair, roadmap movement, commit, push, release, or lifecycle transitions.

Do not add a hidden swarm runtime, background daemon, provider credential store, webhook tunnel, workstation install, or autonomous worker supervisor as part of v2 foundation. Future orchestration remains an external client of MLH until route manifests, role profiles, run evidence, claims, review tokens, and reconcile diagnostics are reliable.

The multi-agent adapter ladder stays subordinate to repo-visible coordination records:

- Hooks are sensors, blockers, and context injectors. They may warn about stale claims, missing handoffs, unsafe paths, or out-of-scope writes, but they do not approve repair, closeout, archive, roadmap movement, staging, commit, push, or release.
- Read-only dashboards are cockpit projections. They may summarize project-state, roadmap, claims, agent-run records, handoffs, worktrees, checks, and alerts, but the route files remain truth.
- `mlhd` is an optional runtime cache and notification/process helper. It may stream logs, watch processes, refresh projections, and notify humans, but deleting its cache must not change what the repository treats as active, accepted, verified, blocked, or closeable.
- Dispatchers and launchers are last-mile adapters. They must create or reference a repo-visible handoff, active claim, and evidence path before starting work, and they cannot grant lifecycle authority to the worker they launch.

## Adapter Groups

| Adapter group | Product role | Boundary |
| --- | --- | --- |
| Skills and plugins | Behavior projection and reusable procedures | Repo-native rules remain stronger than agent-specific skill state; skill-only correctness and skill-owned memory are rejected |
| MCP | Read/projection adapter | No mandatory correctness or unique memory; the implemented stdio slice is explicit, foreground-only, dependency-free, and read-only |
| Browser | Verification or inspection helper | Browser state is not authority |
| IDE | Convenience projection | IDE state is not recovery state |
| Git, GitHub, CI, issues | Collaboration, distribution, and evidence helpers | Core recovery remains non-git-safe and file-first; read-only VCS posture probes are advisory inputs only |
| Hooks | Advisory reminders or visible preflight checks | No hidden repair, auto-commit, auto-archive, or correctness dependency |
| Task runners | Reproducible command ergonomics | Not required for workflow recovery |
| Agent-specific projections | Final-stage convenience adapters | Generic repo and CLI contract must remain stable without them |

## Hook Subdoctrine

Hooks are the strictest adapter lane.
They may remind, warn, or run visible preflight checks.
They must not silently mutate files, repair workflow state, commit changes, archive plans, or become a hidden condition for correctness.

The implemented `preflight` command is a terminal-only warning feed that wrapper scripts may consume explicitly. `preflight --template git-pre-commit` prints a local Git pre-commit wrapper template to stdout, but it does not install that wrapper. The implemented `hooks` command is the explicit hook ergonomics rail: `hooks --doctor` and `hooks --dry-run` are read-only, `hooks --apply --hook git-pre-commit` may write only the selected warning-only shim under `.git/hooks/` in a live operating root, and `hooks --run <event>` is a foreground sensor/context adapter. None of these modes blocks correctness by itself, writes reports, mutates Git config, installs CI/GitHub workflows, or becomes lifecycle authority.

`hooks --run session-start`, `user-prompt-submit`, `pre-tool-use`, `post-tool-use`, and `stop` are implemented native-client foreground hook events. The terminal report emits bounded dashboard-backed context and deterministic shortcut posture; `hooks --run <event> --json` emits the structured `mylittleharness.hook-event.v1` payload for CLI diagnostics and adapter projection. That payload includes status text, optional system message, bounded additional context, the dashboard agent packet when relevant, projection/SQLite cache posture, accelerator adoption posture, connect/readiness action-packet posture, mlhd freshness posture, client hints, findings, and explicit no-authority booleans. Native client helpers must adapt that full payload to the client's stricter hook stdout schema before returning it to the client, and frequent Codex command-output events use a policy-only fast path instead of rebuilding the dashboard packet. The Codex project helper registers `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, and `Stop` in `.codex/hooks.json` through `.codex/hooks/mylittleharness_session_start.py`: SessionStart emits top-level `continue`, optional `systemMessage`, and `hookSpecificOutput.additionalContext`; PreToolUse may emit `permissionDecision=deny` for deterministic shortcut blocks; non-blocking PostToolUse/UserPromptSubmit events stay advisory/contextual; Stop emits no hook stdout for advisory warnings and uses only the Stop-specific block envelope for any future deterministic stop block. The accelerator posture reports dashboard-packet availability, MCP mount status (`mounted`, `missing`, `missing-server`, `legacy-root-bound`, or conflict/degraded posture), the native first-contact hook command, the projection warm-cache command, and the requirement to verify exact source with `rg` or bounded file reads after any accelerator path. It may report missing, dirty, stale, or degraded generated artifacts and SQLite indexes and name the next safe projection command, but it must not rebuild or warm the cache from inside the hook.

PreToolUse route blockers classify concrete mutation targets before treating path-looking payload text as route contact. `apply_patch` targets come from file operation headers, and recognized shell writes use command targets such as PowerShell `-Path`/`-LiteralPath`/`-FilePath`, paired move/copy operands, or shell redirection targets. Lifecycle route strings or product-source strings embedded inside code, tests, examples, or command content are inert data unless the actual write target is that lifecycle route or an out-of-scope product path. When a write target cannot be classified, the hook keeps the older conservative path scan so ambiguous direct writes still fail toward explicit MLH routes.

The first-contact hook event does not install native client config, install Git hooks, start a daemon or listener, create adapter state, choose providers, dispatch workers, accept product diffs, approve lifecycle movement, archive plans, move roadmap status, stage, commit, push, or release. Native clients may render the hook's status or inject its additional context, but repo-visible files and explicit MLH dry-run/apply rails remain authority.

## Product Gates

An adapter requires a later scoped plan before implementation.
That plan must define:

- adapter purpose and owner
- input/output shape
- fail-open behavior
- no-authority guarantee
- mutation boundary
- validation method
- docs impact
- tests or equivalent evidence

## Implemented MCP Read Projection Slice

`adapter --inspect --target mcp-read-projection` is the first implemented adapter report.
`adapter --serve --target mcp-read-projection --transport stdio` is the first real adapter integration and is rootless/router-style when launched without `--root`.
It is an explicit foreground MCP stdio JSON-RPC tools server over the same read projection, not an installed service, SDK-backed runtime, HTTP server, network integration, or background daemon.
`adapter --client-config --target mcp-read-projection` is the no-write adoption report for clients that can mount a foreground stdio MCP server.
`adapter --install-client-config --target mcp-read-projection --dry-run|--apply` is the explicit Codex client-config merge rail described in the adapter boundary above.
`suggest --intent "inspect projection adapter runtime"` routes operators to the read-only inspect rail before projection-cache rebuild advice, so runtime/source/root provenance questions do not depend on remembering the exact adapter target id.

The inspect report and stdio tool payloads expose:

- adapter id, purpose, owner, input root, output shape, and no-runtime posture
- adapter runtime provenance: package version, adapter module path, router-mode posture, MCP server startup root when one exists, selected root, requested root, and the serve command that can be used to restart/reconfigure the helper
- in-memory projection summary, source-set hash, record-set hash, link counts, and fan-in counts
- source paths, roles, required/present/readable posture, counts, and hash prefixes without copying source bodies
- bounded source line slices only when `mylittleharness.read_source` is explicitly called with a root-relative source path, 1-based start line, and line limit
- source-verified search rows from direct exact text search, projection path/reference search, and a current SQLite FTS/BM25 index when available
- nearby route/source bundles for a root-relative projection source, including outbound links, inbound links, fan-in rows, relationship graph rows, and adjacent source records without source bodies
- optional generated artifact and SQLite index posture as degraded input when missing, stale, corrupt, or unavailable
- structured `cachePosture` with component statuses, source refs, recommended `projection --inspect` or `projection --rebuild` commands, and a bounded `projection --warm-cache --target all` self-heal command when supported; adapters expose this posture read-only and never refresh caches themselves
- structured `adoption` metadata for client-config setup, including config path, mounted/conflict status, expected managed server id, idempotent merge posture, first-pass commands, and no-secret boundary
- no-authority and no-mutation reminders

The stdio server supports only `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`.
It exposes four read-only tools: `mylittleharness.read_projection`, `mylittleharness.read_source`, `mylittleharness.search`, and `mylittleharness.related_or_bundle`.
Each tool accepts optional per-call `root` selection and reloads that root inventory for the call.
`read_projection` returns summary posture without source bodies. Its structured payload also carries the compact `agentPacket`, `connectReadiness`, and `mlhd` freshness objects, and the sectioned report includes an `Agent Action Packet` section so MCP consumers see the same next-safe-command posture as dashboard and hooks.
`read_source` returns only the requested bounded source slice and never stores it.
`search` accepts `query`, optional `mode` (`all`, `exact`, `path`, or `full-text`), and `limit`; it never refreshes generated caches from inside the adapter.
`related_or_bundle` accepts a root-relative projection source path and returns graph/link/source metadata only.
It reads newline-delimited JSON-RPC from stdin, writes only JSON-RPC messages to stdout, exits cleanly on EOF, and keeps generated projection files and SQLite indexes optional degraded inputs.

Both modes fail open to repo files and the current in-memory projection when generated projection files are missing or stale.
Generated-input warnings must point operators at `projection --inspect`/`projection --rebuild` for the selected root, and when MCP output disagrees with current CLI posture they must route operators to restart/reconfigure the MCP server or fall back to direct CLI/source reads rather than treating the long-lived MCP process as authority.
They return `0` for readable roots with info or warning findings; root-load failures remain exit `2`; missing required adapter modes, missing `--transport stdio` for serving, or unknown targets remain argparse usage failures.

They must not install an MCP SDK, create an HTTP or network server, create adapter state, write generated reports, refresh generated caches, mutate files, approve repair, approve closeout, archive, commit, change target roots outside explicit per-call selection, store accepted decisions, or become the only recovery path.

The client-config install rail is narrower than a general workstation-adoption feature. It writes no project files, creates no MCP runtime, starts no server, stores no credentials, and does not inspect or print existing user config values. The expected managed server command is rootless: `mylittleharness adapter --serve --target mcp-read-projection --transport stdio`. It refuses instead of merging across an unmanaged/conflicting `mylittleharness` server table, but it may replace the legacy root-bound MLH server table when command/args exactly match the old managed shape. A successful apply only prepares the client to launch the same foreground stdio command later; the next session still must use repo-visible state, check/dashboard posture, MCP/search helpers when available, and direct source verification.

## Implemented Approval Relay Adapter Slice

`adapter --inspect --target approval-relay --approval-packet-ref <project/verification/approval-packets/id.json>` is the first approval relay adapter report.
It compiles a serializable relay preview from repo-visible approval packet JSON records, optional relay channel labels, and optional recipient labels.
The command is a terminal-only inspection rail: it does not deliver messages, open webhooks, read credentials, store secrets, create adapter state, install daemons, or write files.

The approval relay report exposes:

- adapter id, purpose, owner, input root, and no-runtime posture
- each approval packet ref, approval id, status, gate class, and packet hash
- a serializable relay payload hash with `delivery_attempted=false`
- boundary findings that approved packet status and relay delivery cannot authorize lifecycle, archive, repair, roadmap movement, staging, commit, push, release, or next-plan opening

`adapter --client-config --target approval-relay` prints a no-write command template and boundary payload for external clients that want to invoke the same terminal report.
`adapter --serve` remains supported only for `mcp-read-projection`; approval relay deliberately has no foreground server mode.

The relay slice fails open to the repo-visible approval packets. Missing, malformed, absolute, traversal, or non-approval-packet refs are warnings in the adapter report, not hidden recovery state or lifecycle blockers.

## Implemented Preflight Warning Slice

`preflight` is the first optional warning/preflight slice.
It is a terminal-only read-only report plus a stdout-only local hook template, not an installed hook, CI job, or GitHub integration.

It reports:

- advisory summary and root kind
- validation, link audit, context budget, and product-hygiene counts plus warning/error samples
- closeout readiness cues assembled from the existing read-only closeout report, including VCS posture cues when available
- no-authority, no-hook-installation, and no-mutation reminders

`preflight --template git-pre-commit` prints a deterministic POSIX wrapper that sets `MLH_ROOT` to the resolved target root with shell-safe quoting, checks for `mylittleharness`, runs `mylittleharness --root "$MLH_ROOT" preflight`, warns when tooling is unavailable or preflight does not complete, and exits `0`.

The command returns `0` after a successful report even when findings include warnings or errors.
Root-load failures and parser usage failures remain exit `2`.

It must not install hooks, create CI/GitHub workflows, use network calls, write generated preflight reports, block by itself, repair files, archive, commit, change target roots, create lifecycle state, or store accepted decisions.

`preflight --orchestrator-workspace <path>` is a read-only workspace-preflight variant for external launchers. It reports whether the proposed disposable worker workspace is outside the live operating root and configured product source root, whether local Git/MyLittleHarness tooling is discoverable, and which first safe shell commands an orchestrator should run for repo-visible MLH posture. It must not create the workspace, clone repositories, mutate Git, install dependencies, start workers, approve Linear/Symphony issue-board state, or convert an orchestrator status into MLH closeout.

## Implemented Hook Shim And Doctor Slice

`hooks --doctor` inspects hook posture without writing files. It reports the root kind, supported runnable hook events, the local `.git/hooks/pre-commit` target posture when present, the PATH/Python-module fallback posture for the installable Git shim, the `hooks --run session-start --json` native first-contact command, and no-authority boundaries.

`hooks --dry-run --hook git-pre-commit` previews the explicit install target without creating directories or files. `hooks --apply --hook git-pre-commit` is the only implemented hook-install mutation. It is allowed only in a live operating root with an existing local `.git` directory, refuses product-source fixtures and archive roots, refuses unsafe or non-regular targets, and refuses to replace an existing non-MLH hook unless the operator supplies `--force` after review.

The installed shim is warning-only. It tries the `mylittleharness` console script first, then falls back to `python -m mylittleharness` or `py -m mylittleharness` with the install-time package import root, invokes `hooks --run git-pre-commit -- "$@"`, warns if the command is unavailable or fails to complete, and exits `0`. `hooks --run git-pre-commit` delegates to the same read-only preflight report; `hooks --run agent-status` reports root posture only until a later accepted slice defines richer agent lifecycle inputs.

`hooks --run session-start` is the first richer agent lifecycle input. It reuses the read-only dashboard agent packet, cache posture, and accelerator-adoption posture as a compact first-contact context packet, and its JSON form is safe for Codex, Claude Code, VS Code, Windsurf, Cline, or other native hook adapters to translate later. It remains a foreground command: no project, user, or plugin hook configuration is written by this event, and Git pre-commit installation is not a native session-start install.

Hook outputs may warn, block inside a local tool by convention, or inject context into a visible operator flow, but they cannot approve repair, closeout, archive, lifecycle movement, roadmap status, staging, commit, push, rollback, release, next-plan opening, product-diff acceptance, provider routing, worker spawning, dispatcher decisions, cache truth, or daemon truth. Hook installation creates no hidden runtime, cache authority, provider gateway, dashboard, queue, or accepted decision store.

## Implemented Multi-Agent Security Threat Model Slice

`check` now includes read-only multi-agent security posture findings under the validation report. The findings do not create a new adapter, daemon, dashboard, hook, provider gateway, worker process, network listener, or runtime cache mutation. They make the accepted threat model visible before later runtime expansion:

- claims, agent-run evidence, handoff packets, and session active-work records remain the repo-visible coordination authority;
- hooks stay explicit opt-in sensors, blockers, or context injectors and cannot approve dispatcher or daemon truth;
- dashboards are projection/cockpit context only, with route files and lifecycle writeback facts remaining truth;
- `mlhd` runtime cache, local process observations, logs, and notifications are disposable;
- dispatchers cannot start work without a repo-visible handoff packet, compatible active claim, and planned agent-run evidence path;
- MCP/A2A/relay/provider adapters remain transport or projection helpers by default and must not store secrets, choose providers, open background servers, or approve lifecycle movement;
- repo text, hook args, dashboard inputs, adapter payloads, and logs are untrusted context until reconciled against route manifests, write scope, allowed routes, claims, handoffs, and explicit evidence.

Security-sensitive adapter output should name root-relative refs, hashes, and bounded summaries instead of copying environment variables, credentials, provider payloads, log bodies, or source bodies into runtime state.

## Implemented Read-Only Dashboard Prototype Slice

`dashboard --inspect` is a terminal-only local cockpit over repo-visible coordination inputs. It renders project-state lifecycle posture, roadmap queue/counts, work-claim records, agent-run records, handoff packets, session active-work records, worktree diagnostics, check posture, lifecycle provenance, projection cache posture, connect/readiness posture, mlhd freshness posture, and an in-memory projection summary. `dashboard --inspect --json` exposes the same posture as a structured `mylittleharness.dashboard.v1` payload for read-only tooling, including source refs, an `agentPacket` with the portable first-pass command order, a `nextLegalDryRun` route candidate, a `cachePosture` object that mirrors the adapter/check cache boundary, `acceleratorAdoption` metadata for first-contact clients, a top-level `connectReadiness` object, and a top-level `mlhd` freshness object. The agent packet may include the same connect/readiness action packet so hook and client adapters can consume one compact first-contact shape.

The dashboard starts no server, daemon, watcher, dispatcher, worker, hook install, network listener, or cache refresh. Optional generated projection artifacts and any future runtime cache are degraded inputs only; the command rebuilds its current view from source files and in-memory projection data when they are absent or stale.

The dashboard accelerator-adoption payload is a visible cue, not a gate. It can report that the dashboard packet is available, MCP config is mounted/missing/conflicting, cache can be self-healed through `projection --warm-cache --target all`, and `rg` verification is required. `check` may surface the same posture as an informational finding so a missing or conflicting MCP mount is actionable without turning optional client setup into a repository warning or lifecycle blocker.

The connect/readiness packet is also a visible cue, not a gate. It may summarize hooks, MCP, projection/SQLite cache status, docmap/docs_decision posture, docs role metadata, active plan/phase, next legal preview, state-write requirement, recovery-target counts, mlhd control/cache/pid/refresh freshness, and recovery command for dashboard/check/doctor/scaffold/hook consumers. It must keep a no-authority boundary and cannot approve durable state movement, source changes, VCS actions, release actions, provider routing, or cache truth.

Dashboard stale/conflict signals are findings only. They may highlight expired session leases, worktree-root mismatches, malformed or overlapping coordination records, missing optional runtime data, next legal dry-run candidates, or other warnings, but they cannot approve lifecycle movement, archive, roadmap status changes, staging, commit, push, rollback, release, dispatcher work, product-diff acceptance, cache truth, provider output, or daemon truth.

The dashboard has no mutation buttons. Source route files, project-state lifecycle fields, work claims, agent-run evidence, handoff packets, session records, and explicit writeback facts remain the authority.

## Implemented mlhd Runtime Cockpit Slice

`mlhd` is represented as optional runtime cockpit posture under `.mylittleharness/runtime/mlhd`. The implemented slice exposes that posture through read-only dashboard, check, MCP, and hook surfaces: runtime cache present/absent state, control status, pid status, last tick/action, projection dirty counts, last refresh/success/failure timestamps, bounded cache file examples, local-only default posture, and durable-mutation boundaries.

The implemented `mlhd` control plane keeps `status`, `doctor`, `start`, `stop`, `run-once`, `install`, and `uninstall` as explicit local CLI actions. `status`, `doctor`, and all dry-run modes are read-only; apply modes may write disposable pid, lock, heartbeat, state, event, projection-refresh, last-run-once, and autostart manifest markers under `.mylittleharness/runtime/mlhd/`. `run-once --apply` may also invoke the explicit projection warm-cache rail after a quiet period and publish only disposable generated cache inside `.mylittleharness/generated/projection/`. `install --apply` writes a deterministic root-local `autostart.json` manifest with `<root>` command templates so moved repositories do not need manifest rewrites; `uninstall --apply` removes that manifest. A start marker is process observation, and the autostart manifest is readiness evidence, not worker supervision, provider routing, cache freshness authority, OS startup registration, or lifecycle approval; stale pid recovery is limited to removing stale runtime markers before writing fresh local state.

The mlhd daemon contract is optional and disabled by default. If a later slice introduces a daemon process, OS/user autostart entry, supervision process, or serve rail beyond the root-local manifest, runtime storage stays under `.mylittleharness/runtime/mlhd/`, remains safe to delete, and cannot carry provider credentials, source bodies, lifecycle decisions, roadmap decisions, archive status, Git state, or release state. Any such expansion requires a separate reviewed dry-run/apply rail with explicit local-only defaults and rollback posture.

The runtime cache is disposable adapter data. Deleting `.mylittleharness/runtime/mlhd` must not change what the repository treats as active, accepted, verified, blocked, closeable, archived, or ready for review. The dashboard continues from project-state, roadmap, claims, agent-run records, handoffs, session active-work records, worktree diagnostics, and source-backed projection data when the cache is absent. The runtime payload may include a projection pulse derived from dirty markers, operation markers, and the last projection-refresh ledger, but that pulse is guidance for warm-cache commands only; it cannot become cache freshness authority by itself.

This slice starts no server, daemon process, WebSocket listener, worker, dispatcher, provider gateway, hook install, or network listener. Any future serve rail must be explicit, local-only by default, and conservative around credentials and log bodies.

Durable mutations stay delegated to MLH CLI rails with dry-run/apply semantics. Runtime cache, projection-refresh ledgers, logs, notifications, process observations, attach/watch state, generated cache refreshes, and WebSocket events cannot approve repair, closeout, archive, roadmap status, staging, commit, push, rollback, release, dispatcher work, or daemon truth.

## Implemented Dispatcher Agent Launcher Slice

The implemented dispatcher slice is a launcher-readiness adapter, not a background worker supervisor. The advisory role manifest now includes a `dispatcher` profile whose `may_spawn_workers` value is true only behind the explicit handoff, active-claim, and evidence-path preconditions. That role profile does not grant apply authority, lifecycle authority, queue authority, provider ownership, fan-in approval, or Git authority.

`handoff --status` now reports dispatcher readiness from repo-visible records. It refuses readiness when no handoff packet exists, when claim refs are missing or incompatible, when active claims are stale or outside the handoff scope, when evidence refs are unsafe or outside `project/verification/agent-runs/*.md`, or when an existing evidence file is not a readable agent-run record. A safe missing agent-run file is treated as a planned evidence path for the external launcher to fill through the explicit `evidence --record` rail after work runs.

The status report also renders worktree coordination diagnostics with dispatcher-specific codes. `MLH_COORDINATION_ROOT` remains only a routing hint to a live coordination root; claim and run records may name coordination/edit roots as evidence, but the dispatcher report does not create or clean worktrees.

This slice starts no worker process, daemon, queue, provider gateway, hook install, network listener, or runtime cache mutation. External launch tooling may consume the readiness signal, but repo-visible handoffs, claims, and agent-run evidence remain the coordination authority, and lifecycle movement, archive, roadmap status, staging, commit, push, rollback, release, and fan-in approval stay on explicit MLH rails.

## Explicit Rejects

- Mandatory adapter correctness.
- Issue-board authority.
- CI-only completion truth.
- VCS status as archive, commit, repair, lifecycle authority.
- Hidden hook repair.
- Preflight-only correctness or hidden blocking policy.
- Browser, IDE, MCP, GitHub, or plugin state as accepted decision storage.
- Adapter-specific source of truth that cannot be recovered from files.
