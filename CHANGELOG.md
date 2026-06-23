# Changelog

All notable changes for MyLittleHarness are recorded here once they are ready for a public release checkpoint.

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
