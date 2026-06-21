# Changelog

All notable changes for MyLittleHarness are recorded here once they are ready for a release-candidate checkpoint.

## 1.0.0-rc1 - Public Release Candidate - 2026-06-21

This checkpoint publishes MyLittleHarness as a `1.0.0` release candidate for public GitHub review. It does not declare a final stable release, package-index publication, global installation flow, PATH/profile mutation, or workstation adoption.

### Added

- Small visible CLI front door: `init`, `check`, `migrate`, `repair`, and `detach`.
- Neutral target-root workflow manifest support through `.mylittleharness/project-workflow.toml`, with `.codex/project-workflow.toml` retained as legacy/client-adapter compatibility.
- Explicit local package verification through `bootstrap --package-smoke`, using temporary source, build, and install locations outside the product source checkout.
- Read-only adoption readiness evidence through `bootstrap --inspect`.
- Route-owned lifecycle commands for planning, writeback, transition, roadmap synchronization, memory hygiene, retention, evidence, and meta-feedback.
- Read-only navigation and recovery surfaces including `dashboard --inspect`, `intelligence`, `adapter`, `suggest`, `audit-links`, `doctor`, `preflight`, `projection`, and `semantic`.
- Optional generated projection/cache and MCP adapter helpers that remain advisory and rebuildable.

### Changed

- Product posture is now documented as the direct `MyLittleHarness -> target repository` model.
- Operating memory, verification records, active plans, archives, and generated output are kept in target operating roots rather than in the reusable product source.
- Docs and package metadata now treat `1.0.0` as the package version for the first GitHub release-candidate baseline.

### Verification Expectations

- `pyproject.toml` and `mylittleharness.__version__` both report `1.0.0`.
- Product tests run with bytecode disabled from the source checkout.
- Package smoke builds and installs from temporary locations outside the product source checkout.
- A fresh target repository can follow the README quick-start path with explicit dry-run/apply boundaries.
- Product and operating roots are clean after exact local savepoints.

### Not Included

- Package-index publication.
- Final stable release claim.
- Signed artifact release.
- Global public announcement campaign.
- Global installation, PATH/profile edits, or user-config mutation.
- Standalone `bootstrap --apply` or mutating workstation adoption.
