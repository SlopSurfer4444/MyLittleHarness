# Changelog

All notable changes for MyLittleHarness are recorded here once they are ready for a public release checkpoint.

## 1.0.2 - Lifecycle Checkpoint Hardening - 2026-06-28

This release publishes the accumulated post-1.0.1 lifecycle and hook guardrail fixes that were proven locally before publication. It remains a GitHub source release; package-index publication, signed binary artifacts, global installation, PATH/profile mutation, hosted service behavior, and workstation adoption are still outside this release.

### Added

- Command discovery support for route-facing operator intent.
- Explicit terminal active-plan closeout routing for plan completion handoff.
- Checkpoint provenance support for roadmap promotion and mixed post-closeout promotion savepoints.

### Changed

- Active-plan checkpoint guidance now respects phase write scope and product-source target scope.
- Roadmap and plan synthesis validation now handles multi-value phase write scopes, batch sibling refs, and update-active target materialization more consistently.
- Route public-neutrality gates and `mlhd run-once` timeout handoff diagnostics are surfaced more directly.

### Fixed

- Hook checkpoint classification for standalone verification retarget staging/commits, reviewed verification staging, retained verification retarget sources, staged diff review bundles, archive reference checkpoints, active writeback checkpoints, and state/roadmap checkpoint commits.
- Product-source staging guidance for active plans, product checkpoints, no-automatic retained lifecycle source boundaries, and operating-root commit scope.
- Retention fan-in safety and source member destination validation before route writes.

### Verification Expectations

- `pyproject.toml` and `mylittleharness.__version__` both report `1.0.2`.
- Product tests run with bytecode disabled from the source checkout.
- GitHub Actions `Tests` passes on the pushed `main` release commit before the GitHub release is treated as green.
- The GitHub release includes the standard source archive plus an attached `mylittleharness-1.0.2-source.zip` asset.

## 1.0.1 - Source Release Refresh - 2026-06-27

This release publishes the post-1.0.0 operator-lane hardening that was already verified locally, including checkpoint hook classifier fixes and owner-decision route discoverability polish. It remains a GitHub source release; package-index publication, signed binary artifacts, global installation, PATH/profile mutation, hosted service behavior, and workstation adoption are still outside this release.

### Added

- Explicit `approval-decision` route support for recording reviewed owner decisions from approval-packet evidence.
- Top-level help discoverability for the owner-decision route without treating the route as approval authority.
- Product docs and command-surface references for the owner-decision workflow.

### Fixed

- Hook checkpoint classification for archived plans, neighbor closeout routes, route-imported research, approval-packet refs, no-roadmap post-archive staging, and terminal active-plan closeout lanes.
- GitHub Actions portability failure around staged project-state hook tests on macOS and Windows path forms.
- A release-readiness docs contract drift in `docs/README.md`.

### Verification Expectations

- `pyproject.toml` and `mylittleharness.__version__` both report `1.0.1`.
- Product tests run with bytecode disabled from the source checkout.
- GitHub Actions `Tests` passes on the pushed `main` release commit before the GitHub release is treated as green.
- The GitHub release includes the standard source archive plus an attached `mylittleharness-1.0.1-source.zip` asset.

## 1.0.0 - First Public GitHub Release - 2026-06-23

This release publishes MyLittleHarness as a public GitHub source release for local use and review. It does not claim package-index publication, signed binary artifacts, global installation, PATH/profile mutation, hosted service behavior, or workstation adoption.

### Added

- Small visible CLI front door: `init`, `check`, `migrate`, `repair`, and `detach`.
- Neutral target-root workflow manifest support through `.mylittleharness/project-workflow.toml`, with `.codex/project-workflow.toml` retained as legacy/client-adapter compatibility.
- Explicit local package verification through `bootstrap --package-smoke`, using temporary source, build, and install locations outside the product source checkout.
- Read-only adoption readiness evidence through `bootstrap --inspect`.
- Route-owned lifecycle commands for planning, writeback, transition, roadmap synchronization, memory hygiene, retention, evidence, and meta-feedback.
- Read-only navigation and recovery surfaces including `dashboard --inspect`, `intelligence`, `adapter`, `suggest`, `audit-links`, `doctor`, `preflight`, `projection`, and `semantic`.
- Optional generated projection/cache and MCP adapter helpers that remain advisory and rebuildable.

### Changed

- Product posture is documented as the direct `MyLittleHarness -> target repository` model.
- Operating memory, verification records, active plans, archives, and generated output are kept in target operating roots rather than in the reusable product source.
- Docs and package metadata treat `1.0.0` as the package version for the first public GitHub source-release baseline.
- Quick checks can expose compact summary-only diagnostics for operator-facing decisions.
- Hook guidance is more precise around real Codex/tool payloads, prompt/delegation boundaries, route-owned checkpointing, exact staging, and explicit publication pushes.

### Verification Expectations

- `pyproject.toml` and `mylittleharness.__version__` both report `1.0.0`.
- Product tests run with bytecode disabled from the source checkout.
- Package smoke builds and installs from temporary locations outside the product source checkout.
- A fresh target repository can follow the README quick-start path with explicit dry-run/apply boundaries.
- Product and operating roots are clean after exact local savepoints, except for intentionally disclosed unrelated local work.

### Not Included

- Package-index publication.
- Signed binary artifact release.
- Global public announcement campaign.
- Global installation, PATH/profile edits, or user-config mutation.
- Standalone `bootstrap --apply` or mutating workstation adoption.
