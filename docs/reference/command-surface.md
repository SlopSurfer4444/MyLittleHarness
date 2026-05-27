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
| `research-import` | research provenance | yes | yes | writes one non-authority research artifact |
| `research-distill` | research distillate | yes | yes | writes reviewed synthesis with quality and planning gates |
| `research-compare` | research comparison | yes | yes | writes reviewed comparison and optional source cleanup |
| `incubate` | future idea/fix-candidate capture | yes | yes | writes non-authority incubation notes |
| `intake` | incoming information route | yes | yes | writes one explicit target when reviewed |

These commands are advanced by design. Their output can guide an operator, but
only an explicit apply route writes repo-visible authority.

## Read-Only Helpers

| Command | Class | Writes | Boundary |
| --- | --- | --- | --- |
| `status` / `validate` | compatibility diagnostics | no | advisory reports |
| `dashboard --inspect` | cockpit projection | no | starts no server and approves no mutation |
| `intelligence` | source-verified navigation | no by default | may use disposable projection inputs for navigation |
| `manifest --inspect` | route/role protocol report | no | advisory orchestration metadata |
| `closeout` | closeout cue report | no | may suggest trailers, never stages or commits |
| bare `evidence` | evidence cue report | no | report only |
| `preflight` | terminal warning feed | no | does not install hooks or CI |
| `hooks --doctor` / `hooks --run` | hook posture or foreground event | no | advisory/contextual unless a deterministic client block is returned |
| `adapter --inspect` | adapter report | no | source-bound projection posture |
| `bootstrap --inspect` | package/workstation readiness | no | no install or workstation mutation |
| `tasks --inspect` | task map | no | orientation only |

Some navigation commands can report stale generated projection cache and suggest
refresh commands. That suggestion is not cache truth or lifecycle approval.

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

## Release-Blocking Product Decisions

- Apache-2.0 is declared in `LICENSE` and package metadata for public
  redistribution posture.
- Package-index publication, signed artifacts, global installation, PATH/profile
  edits, and workstation adoption are separate release decisions.
- Mutating MCP tools, native IDE plugins, provider gateways, and autonomous
  commit/push behavior require later scoped plans.
