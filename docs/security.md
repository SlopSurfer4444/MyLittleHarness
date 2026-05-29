# Security and Runtime Boundaries

MyLittleHarness is a repo-native safety layer. Its core security posture is that
repo-visible files remain authority and every durable mutation is explicit,
bounded, and reviewable.

## What MLH Will Never Do By Default

MLH core will not:

- commit, stage, push, publish, or create releases;
- delete product source or treat generated cache as authority;
- approve lifecycle movement from diagnostics, dashboard output, hooks, MCP
  output, daemon state, or provider output;
- require a daemon, dashboard, MCP client, IDE plugin, hook, CI job, or cloud
  service for correctness;
- require Codex or any named client adapter as the core correctness path;
- store provider credentials or send repository data to a model provider by
  itself;
- make `--dry-run` write durable repo authority;
- make `--apply` write outside the command's declared bounded path set.

## Authority Model

The authority stack is:

1. repo-visible operating files such as `project/project-state.md`,
   `project/implementation-plan.md`, `project/roadmap.md`, specs, evidence, and
   archives;
2. explicit CLI dry-run/apply routes that write those files;
3. generated projection, dashboard, hook, MCP, and runtime helper output as
   advisory context only.

If an advisory surface disagrees with repo-visible route files, trust the route
files and rerun a source-bound check.

## Atomicity and Concurrency Boundary

MLH uses bounded file transactions, path-boundary checks, snapshots for selected
existing-content repairs, and explicit dry-run/apply rails to reduce partial
writes. These are local safety guardrails, not a distributed transaction system:
atomic writes are not crash-proof multi-process transactions. A process crash,
filesystem behavior, antivirus interference, or competing operator can still
leave review work to do.

Concurrency safety stays repo-visible and procedural. Use work claims, handoff
packets, review tokens, route receipts, and final source checks to coordinate
parallel work; do not treat file replacement, hook output, dashboard output,
daemon state, generated cache, or JSON reports as a lock manager or fan-in
approval.

## Session Helpers

MLH can expose local helpers around the core workflow:

- hooks can inject compact context or block deterministic unsafe shortcuts;
- `adapter --serve --transport stdio` can expose read-only MCP tools;
- `dashboard --inspect` can render a cockpit packet;
- `mlhd run-once` or an explicitly started `mlhd` helper can refresh generated
  context and runtime posture.

These are session/runtime convenience layers. They may report current/stale
cache posture, suggest next safe commands, or make agent navigation cheaper.
They cannot approve repair, closeout, archive, roadmap status, staging, commit,
push, rollback, release, provider routing, dispatcher choices, daemon truth, or
cache truth.

## MCP Boundary

The implemented MCP server is a local stdio helper for read-first navigation.
It exposes source-bound projection, bounded source reads, search, and related
context. It does not install an SDK, open an HTTP server, refresh caches from
inside the adapter, write files, or expose a generic shell passthrough.

`adapter --client-config --target mcp-read-projection` is a read/propose-only
config generator. It can print generic MCP, VS Code, Claude Code, and JetBrains
AI Assistant profile snippets, but printing the snippets writes no client files,
starts no server, opens no network listener, enables no provider routing,
enables no mutating MCP tools by default, and exposes no shell passthrough.

`doctor --integration mcp|vscode|claude-code|jetbrains` is also read-only. It
smokes the local MCP stdio handler in-process and reports install path, root
classification, manifest posture, client config pointers, hook posture, cache
posture, and next safe commands, but it does not install hooks, write client
config, refresh cache, mutate lifecycle files, touch Git state, start a daemon,
or approve provider routing.

Mutating MCP tools are not part of the default product surface. Any future
mutating MCP tool needs a separate scoped plan, disabled-by-default posture,
write metadata, dry-run artifact, and explicit human apply gate.

## Runtime Cache Boundary

Runtime and generated cache paths are disposable:

```text
.mylittleharness/generated/projection/
.mylittleharness/generated/context-memory/
.mylittleharness/runtime/mlhd/
```

Deleting those paths must not change what the repository treats as active,
accepted, verified, blocked, closeable, archived, or ready for review.

`mlhd` apply modes may write runtime markers and generated cache under the
declared MLH-owned paths. They cannot write lifecycle, roadmap, archive, Git,
release, provider, or product-source authority.

## Hook Boundary

Hooks are foreground sensors and client adapters. They may warn, inject context,
or return a client-specific deterministic block for unsafe shortcuts. They must
not silently repair files, install hidden services, archive plans, commit
changes, or become the only condition for correctness.

Fresh `init --apply` and compatibility `attach --apply` install or refresh the
project-local Codex native hook adapter by default. They do not trust hooks in
Codex, write user-global client configuration, install MCP, or configure other
native clients. Codex, Claude Code, GitHub Copilot, VS Code, MCP, and other
adapters remain advisory helpers; their output remains advisory even when a user
installs them through a reviewed adapter command.

## Release Readiness Notes

The product source declares Apache-2.0 licensing in `LICENSE` and package
metadata. Public redistribution still needs CI evidence for the stdlib test
suite. Publishing to PyPI, TestPyPI, or another package index is a separate
release operation, not part of local correctness.

Public GitHub golden path: source, docs, tests, package metadata, and CI evidence.
The product checkout should show reusable product truth; operating memory belongs in target repositories.
`.mylittleharness/project-workflow.toml` is the neutral workflow manifest for target operating roots, and `.codex/project-workflow.toml` is legacy/client-adapter compatibility, not the core product path.
