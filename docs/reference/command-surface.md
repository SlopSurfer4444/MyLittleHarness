# Command Surface Reference

This reference summarizes the product-facing MyLittleHarness command surface.
It is a user-facing map, not a replacement for command-specific help or the
route contracts in `docs/specs/`.

## Default Surface

| Command | Class | Writes | Apply required | Typical root | Authority risk |
| --- | --- | --- | --- | --- | --- |
| `init` | attach | yes | yes | target repository | high: creates operating scaffold |
| `check` | diagnostic | no | no | any readable MLH root | low: advisory report |
| `migrate` | manifest migration | yes | yes | live operating root with legacy manifest | medium: exact copy, legacy preserved |
| `repair` | repair | yes | yes | live operating root | high: bounded repair only |
| `detach` | detach marker | yes | yes | live operating root | medium: marker-only disable posture |

The top-level help intentionally foregrounds the small operator surface first.
The default command story is agent-neutral: run from the product source, point
`--root` at a target repository, create the neutral
`.mylittleharness/project-workflow.toml` manifest, and keep the rule simple:
`.codex/project-workflow.toml` is legacy/client-adapter compatibility, limited
to legacy migration or explicit client-adapter context.
`migrate` is a public migration utility for legacy roots: dry-run writes
nothing, apply copies `.codex/project-workflow.toml` to
`.mylittleharness/project-workflow.toml`, preserves the legacy file, and
refuses missing legacy files, divergent neutral manifests, symlinked targets,
and root escapes. Use `--dry-run` before every mutating default command.

## Recovery and Lifecycle Commands

| Command | Class | Writes | Apply required | Boundary |
| --- | --- | --- | --- | --- |
| `plan` | active-plan scaffold | yes | yes | writes the active plan and selected lifecycle frontmatter only |
| `writeback` | lifecycle/closeout writeback | yes | yes | records explicit lifecycle, closeout, and optional roadmap facts |
| `transition` | reviewed lifecycle composition | yes | yes plus review token | composes phase completion, archive, and next-plan opening only when reviewed |
| `roadmap` | accepted-work sequencing | yes | yes | writes `project/roadmap.md` and explicit relationship metadata |
| `memory-hygiene` | research/incubation cleanup | yes | yes | bounded route cleanup, archive coverage, and link repair |
| `attachment-import` | incoming binary artifact route | yes | yes | copies one reviewed binary into `project/attachments/**` and writes a sidecar metadata card |
| `research-import` | research provenance | yes | yes | writes one non-authority research artifact |
| `research-distill` | research distillate | yes | yes | writes reviewed synthesis with quality and planning gates |
| `research-compare` | research comparison | yes | yes | writes reviewed comparison and optional source cleanup |
| `evidence --receipt-refresh` | evidence maintenance | yes | yes plus proposal token | refreshes `source_hashes` only for an existing worker-run receipt JSON |
| `evidence --retarget-ref` | evidence maintenance | yes | yes plus proposal token | retargets scoped provenance refs in existing route-owned evidence |
| `incubate` | future idea/fix-candidate capture | yes | yes | writes non-authority incubation notes |
| `intake` | incoming information route | yes | yes | writes one explicit target when reviewed |

These commands are advanced by design. Their output can guide an operator, but
only an explicit apply route writes repo-visible authority.
For protected incubation cleanup, `memory-hygiene --dry-run --archive-list-file
<project/verification/reviewed-list.txt> --archive-folder
project/archive/reference/<reviewed-folder>` validates an explicit reviewed
`project/plan-incubation/*.md` path list, reports an `mha-*` proposal token,
and previews the archive copies, source removals, `index.md` manifest, and
optional exact link repairs. The matching `--apply` requires that token and
refuses current/canonical sources, live consumers, path escapes, target
collisions, and nonconforming prompt-like files that need a separate
normalization route.
Protected worker-run receipt JSON maintenance uses
`evidence --receipt-refresh --dry-run --target
project/verification/worker-run-receipts/<id>.json`; the matching apply
requires the reported proposal token and updates only `source_hashes`.
It refuses path escapes, symlinks, malformed or unknown JSON, stale tokens,
unsafe source refs, and authority overclaims, and it cannot approve lifecycle,
fan-in, provider routing, staging, commits, archives, worker launch, or
target-repo acceptance.
Protected evidence provenance retargeting uses
`evidence --retarget-ref --dry-run --target <route-owned-evidence>
--old-ref <root-relative-ref> --new-ref <existing-root-relative-ref>`.
The matching apply requires the reported proposal token and updates only scoped
provenance ref fields in existing agent-run Markdown, handoff JSON,
work-claim JSON, or worker-run receipt JSON. Agent-run and worker-run receipt
targets refresh `source_hashes` after retargeting. It refuses path escapes,
symlinks, missing new refs, malformed records, stale tokens, and authority
overclaims, and it cannot approve lifecycle, archive, roadmap status,
provider routing, staging, commits, or acceptance.
`attachment-import` is the route for incoming PDFs, DOCX, XLSX, images, and
ZIPs. It writes the original binary beside `artifact.md`; the binary remains
source evidence, and the Markdown card is the metadata authority for hash,
provenance, related research, docs decision, and lifecycle boundaries.

## Read-Only Helpers

| Command | Class | Writes | Boundary |
| --- | --- | --- | --- |
| `status` / `validate` | compatibility diagnostics | no | advisory reports |
| `dashboard --inspect` | cockpit projection | no | starts no server and approves no mutation |
| `intelligence` | source-verified navigation | may refresh disposable cache | path/full-text/query modes may refresh only `.mylittleharness/generated/projection/` |
| `manifest --inspect` | route/role protocol report | no | advisory orchestration metadata |
| `closeout` | closeout cue report | no | may suggest trailers, never stages or commits |
| bare `evidence` | evidence cue report | no | report only |
| `suggest --intent "<context pack>"` | adoption/navigation hints | no | pointer-only bootstrap and Deep Research import guidance |
| `preflight` | terminal warning feed | no | does not install hooks or CI |
| `hooks --doctor` / `hooks --run` | hook posture or foreground event | no | advisory/contextual unless a deterministic client block is returned |
| `adapter --inspect` | adapter report | no | source-bound projection posture |
| `bootstrap --inspect` | package/workstation readiness | no | no install or workstation mutation |
| `tasks --inspect` | task map | no | orientation only |

Some navigation commands can report stale generated projection cache and suggest
refresh commands. That suggestion is not cache truth or lifecycle approval.

`check --json` and `dashboard --inspect --json` include a top-level `summary`
object with schema `mylittleharness.compact-report-summary.v1`. The summary is
a compact advisory index for automation: status, work-result outcome, severity
counts, section summaries, timeout/skipped/not-checked buckets, nonblocking and
known-environment warning classification, next-safe-route count, command-action
count, and explicit authority flags. It keeps warnings visible, does not change
exit codes, and cannot approve lifecycle movement, archive, roadmap status, Git
state, release, provider routing, or cache truth.

## Machine-Readable Audit Surface

`manifest --inspect --json` includes a `command_surface` array with schema
`mylittleharness.command-surface.v1`. Each row names the command family, the
visible commands, `read_write_class`, `apply_requirement`, `root_eligibility`,
`write_path_posture`, and `authority_risk`. The same data is rendered as
`command-surface-entry` findings in text reports, so auditors can inspect the
read/write/apply/root/write-path posture without scraping prose tables.

Current command-surface rows are:

| Surface id | Read/write class | Apply posture | Root posture | Write-path posture |
| --- | --- | --- | --- | --- |
| `read-only-status-navigation` | read-only report | no `--apply` path for this posture | any readable MLH root matching command posture | writes no repo files, generated caches, package artifacts, hooks, Git state, user config, or workstation state |
| `read-mostly-generated-cache-navigation` | read-mostly report with disposable cache refresh | no `--apply`; path/full-text navigation may refresh disposable cache | any readable MLH root matching intelligence posture | writes no repo source, lifecycle, package, hook, Git, user config, workstation, or runtime state; may refresh only `.mylittleharness/generated/projection/` |
| `explicit-dry-run-apply-rails` | explicit preview then write | dry-run is preview; apply is explicit and command-owned | eligible live operating roots or explicit command roots | writes only reviewed route files, scaffold files, generated cache paths, or local config targets |
| `direct-generated-cache-maintenance` | direct disposable generated-cache mutation | no matching dry-run/apply rail is implied | readable MLH roots with projection cache support | writes only disposable projection cache files or markers under `.mylittleharness/generated/projection/` |
| `product-package-smoke` | product verification | no `--apply`; verification mode only | MyLittleHarness product source checkout | copies to a temporary workspace outside the product root and leaves no product-root build/dist/egg-info artifacts |
| `optional-runtime-helper` | optional runtime cache | runtime mutations require dry-run/apply; status is read-only | local MLH root with runtime cache boundary | writes only root-local disposable mlhd runtime/cache/autostart artifacts or generated projection refresh output |

The command-surface manifest is protocol/report data only. It can help review
automation and release readiness, but it cannot approve lifecycle movement,
archive, roadmap status, staging, commit, push, release, rollback, provider
routing, or future mutations.

When the intent asks for a context pack or adoption handoff, `suggest --intent`
adds bootstrap pointers for any file-reading, shell-capable agent: read the
operator contract, neutral or legacy workflow manifest, project state, roadmap,
and active plan only when active; then use `check`, `dashboard --inspect`,
`adapter --client-config --target mcp-read-projection`, and exact `rg` or
bounded source reads. For Deep Research adoption, it points at reviewed
`research-import` and `research-distill` dry-run/apply rails after human review
of external output. It does not copy authority bodies, call external models,
create public repos, publish, mutate lifecycle, stage, commit, push, release, or
approve provider routing.

## Optional Runtime and Client Config

| Command | Class | Writes | Apply required | Boundary |
| --- | --- | --- | --- | --- |
| `adapter --client-config` | client config preview | no | no | reports MCP mount/config posture |
| `adapter --install-client-config` | client config merge | yes | yes | writes only reviewed managed client config |
| `adapter --serve --transport stdio` | foreground MCP helper | no repo writes | no | local stdio server, read-only tools only |
| `mlhd status` / `mlhd doctor` | runtime posture | no | no | inspects disposable runtime cache |
| `mlhd run-once` | generated context refresh | yes | yes | writes only disposable runtime/generated cache |
| `mlhd start` / `mlhd stop` | local runtime control | yes | yes | writes runtime markers; no lifecycle authority |
| `mlhd install` / `mlhd uninstall` | root-local autostart manifest | yes | yes | writes/removes local runtime manifest only |

`mlhd` is an optional runtime helper. It is not a hidden control plane, provider
gateway, source of lifecycle truth, or release authority.

Client adapters are optional helper setup, not first-run scaffold. Fresh
`init --apply` and compatibility `attach --apply` create the neutral workflow
manifest and project state without installing `.codex`, Claude Code, GitHub
Copilot, VS Code, MCP, or other client configuration. Project-local native
hooks stay behind explicit `hooks adapter --client <client> --dry-run|--apply
--scope project` review.

`adapter --client-config --target mcp-read-projection` prints a no-write JSON
payload with schema `mylittleharness.mcp-client-configs.v1`, read/propose-only
defaults, read-only tool authority metadata, and copy-or-review profiles for
generic MCP, VS Code, Claude Code, and JetBrains AI Assistant. The profiles use
the same local stdio command and mirror the client-owned config shapes: generic
MCP and JetBrains use `mcpServers`, VS Code uses `servers` in `mcp.json`, and
Claude Code can use project `.mcp.json` with `mcpServers`. Printing these
profiles does not write client files, start the server, enable mutating tools,
enable provider routing, open a network listener, or expose shell passthrough.
The Codex `adapter --install-client-config --dry-run|--apply` rail remains a
separate reviewed workstation mutation path.

## Release-Blocking Product Decisions

- Apache-2.0 is declared in `LICENSE` and package metadata for public
  redistribution posture.
- Package-index publication, signed artifacts, global installation, PATH/profile
  edits, and workstation adoption are separate release decisions.
- Mutating MCP tools, native IDE plugins, provider gateways, and autonomous
  commit/push behavior require later scoped plans.
