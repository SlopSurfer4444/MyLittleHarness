# MyLittleHarness 1.0.0

## Summary

MyLittleHarness `1.0.0` is the first public GitHub source release for the repo-visible workflow safety utility built around one direct model: `MyLittleHarness -> target repository`.

It is ready for public GitHub use and local validation from source or from GitHub's source archives. Package-index publication, signed binary artifacts, global workstation adoption, and hosted services remain future distribution work rather than hidden assumptions in this release.

## What This Release Is

- A local Python CLI for initializing, checking, repairing, and safely navigating MLH target repositories.
- A repository authority pattern built from ordinary files: `AGENTS.md`, `.mylittleharness/project-workflow.toml`, `project/project-state.md`, optional roadmap/evidence files, and explicit dry-run/apply routes.
- A stdlib-first package with no required runtime dependencies, Apache-2.0 licensing metadata, Python `>=3.11`, and the `mylittleharness` console script.
- A bounded public source-release baseline before package-index publication or installer work.

## What It Can Do Now

- Attach a neutral MLH workflow layer to a target repository with `init --dry-run` and `init --apply`.
- Inspect target posture with `check`, including lifecycle, docs, routing, generated-cache, relationship, and product-boundary diagnostics, plus compact summary-only output for quick operator decisions.
- Preview and apply bounded repair classes for known MLH-owned scaffolding and metadata routes.
- Migrate legacy `.codex/project-workflow.toml` manifests to the neutral `.mylittleharness/project-workflow.toml` path.
- Mark a target repository as detached through the explicit `detach` marker route.
- Verify package install/import/console-script behavior with `bootstrap --package-smoke`.
- Provide optional read-only navigation through dashboards, suggestions, intelligence search, adapter reports, and generated projections.
- Provide tighter hook guidance for real Codex/tool payloads, prompt/delegation boundaries, route-owned checkpointing, and exact publication pushes.

## What It Does Not Claim

- No package-index publication has happened.
- No signed or uploaded binary artifact is approved by this release.
- No global installation, PATH/profile edit, user-config mutation, workstation adoption, or standalone `bootstrap --apply` behavior is part of the release contract.
- No generated cache, hook, MCP adapter, CI output, dry-run report, or helper can approve lifecycle, archive, roadmap, Git, release, provider, or product-diff decisions.

## Local Verification Checklist

- Confirm package metadata and runtime version both report `1.0.0`.
- Run product tests from the source checkout with bytecode disabled.
- Build wheel and sdist artifacts into a temporary directory outside the product root.
- Install the freshly built wheel into a new temporary virtual environment with no dependency resolution surprises.
- Run the installed console script against a fresh target repository through the README quick-start path.
- Record verification facts in the serviced operating root.
- Create exact local Git savepoints for the product source and operating-root evidence.

## Still Not Included

- Publishing to a package index.
- Uploading signed binary artifacts.
- Running a wider public announcement campaign.
- Installing globally or mutating workstation/user configuration.
