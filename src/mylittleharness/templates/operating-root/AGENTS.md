# MyLittleHarness Operator Contract
## Operating Root
- Treat this repository as the target operating root that MyLittleHarness services.
- Repo-visible files remain authoritative; command output is advisory until changes are written here.
- Any file-reading, shell-capable agent can operate from this contract, repo-visible files, and MyLittleHarness CLI reports; installed skills, IDE rules, MCP clients, hooks, and CI are optional convenience layers only.
- Start by reading this `AGENTS.md`, `.mylittleharness/project-workflow.toml`, and `project/project-state.md`; use `.codex/project-workflow.toml` only as the legacy fallback manifest when the neutral manifest is absent.
- Core operation is agent-neutral: `.mylittleharness/project-workflow.toml` is the neutral workflow manifest, and `.codex/project-workflow.toml` is legacy/client-adapter compatibility rather than a required correctness path.
- Read `project/implementation-plan.md` only when `project/project-state.md` or the manifest says `plan_status = "active"` or the user explicitly asks about the plan, phase, or closeout.
- When `plan_status = "active"`, prefer first-class `active_phase` and `phase_status` values from `project/project-state.md` over prose inference for continuation.
- Use MLH lifecycle routes instead of ad hoc memory pockets; incubation notes live under `project/plan-incubation/*.md`, and optional accepted-work sequencing lives at `project/roadmap.md`.
- When `check` reports oversized `project/project-state.md`, do not manually trim only the newest note; preview/apply `writeback --compact-only` so MLH scans the whole state and archives older/non-current history while preserving current authority.
- Agent navigation reflex: for fuzzy route discovery, impact, lifecycle, or product-source questions, start with `dashboard --inspect` or `dashboard --inspect --json` for source refs, the agent packet, cache posture, and the next legal dry-run candidate, then use `intelligence --query`, `intelligence --focus routes`, optional `mylittleharness.read_projection`, and `suggest --intent`; exact lookup stays on `rg` or direct file reads. These are source/lifecycle read-only aids before scoped mutation; search-oriented intelligence may refresh only disposable generated projection cache under `.mylittleharness/generated/projection`, never approval to apply or accept product diff.
- Use the optional docs routing file when present as a routing aid for product docs and impact checks; it is not authority by itself.
- Run `mylittleharness --root <this-repo> check` before mutating repair work, and run `mylittleharness --root <this-repo> repair --dry-run` before `repair --apply`.
- For user-facing changes, record a `docs_decision` of `updated`, `not-needed`, or `uncertain` before confident closeout; `uncertain` means closeout language must stay provisional.
- Do not treat repair output as approval for closeout, archive, commit, rollback, or lifecycle decisions.
- Chat output: keep routine narration compact; ask only blocking questions; use short factual updates for long work, blockers, risky choices, or required user decisions; keep final responses compact and self-contained.
- Agent behavior defaults: think before editing; prefer the simplest bounded fix; touch only task-relevant files while preserving unrelated dirty worktree changes; make changes checkable, verify, and record durable results in repo-visible memory; meta-feedback capture is opt-in, not a default start-pass requirement.
- The product model is `MyLittleHarness -> target repository`; do not add another runtime layer.
