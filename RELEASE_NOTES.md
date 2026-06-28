# MyLittleHarness 1.0.2

## Summary

MyLittleHarness `1.0.2` is a public GitHub source release for the repo-visible workflow safety utility built around one direct model: `MyLittleHarness -> target repository`.

It refreshes the post-1.0.1 source baseline with lifecycle checkpoint hardening, product-source write-scope guidance, verification retarget/staging fixes, route public-neutrality diagnostics, and safer retention/source-member validation. Package-index publication, signed binary artifacts, global workstation adoption, and hosted services remain future distribution work rather than hidden assumptions in this release.

## What This Release Is

- A local Python CLI for initializing, checking, repairing, and safely navigating MLH target repositories.
- A repository authority pattern built from ordinary files: `AGENTS.md`, `.mylittleharness/project-workflow.toml`, `project/project-state.md`, optional roadmap/evidence files, and explicit dry-run/apply routes.
- A stdlib-first package with no required runtime dependencies, Apache-2.0 licensing metadata, Python `>=3.11`, and the `mylittleharness` console script.
- A bounded public source-release baseline before package-index publication or installer work.
- A source release archive attached to GitHub Releases for operators who want a direct zip asset in addition to GitHub's generated source archives.

## What Changed Since 1.0.1

- Active-plan and roadmap checkpoint guidance now respects phase write scope, product-source scope, and terminal closeout boundaries more consistently.
- Hook allow/deny predicates cover reviewed verification staging, standalone verification retarget staging/commits, retained verification retarget sources, staged diff bundles, archive references, and state/roadmap writeback checkpoints.
- Retention fan-in, route public-neutrality diagnostics, source-member destination validation, roadmap batch sibling validation, and `mlhd run-once` timeout handoff behavior are safer and easier to inspect.
- Product docs and version-sensitive package tests now identify `1.0.2` as the current source-release baseline.

## What It Does Not Claim

- No package-index publication has happened.
- No signed or uploaded binary artifact is approved by this release.
- No global installation, PATH/profile edit, user-config mutation, workstation adoption, or standalone `bootstrap --apply` behavior is part of the release contract.
- No generated cache, hook, MCP adapter, CI output, dry-run report, or helper can approve lifecycle, archive, roadmap, Git, release, provider, or product-diff decisions.

## Local Verification Checklist

- Confirm package metadata and runtime version both report `1.0.2`.
- Run product tests from the source checkout with bytecode disabled.
- Build wheel and sdist artifacts into a temporary directory outside the product root.
- Install the freshly built wheel into a new temporary virtual environment with no dependency resolution surprises.
- Run the installed console script against a fresh target repository through the README quick-start path.
- Confirm GitHub Actions `Tests` passes for the pushed release commit.
- Record verification facts in the serviced operating root.
- Create exact local Git savepoints for the product source and operating-root evidence.

## Still Not Included

- Publishing to a package index.
- Uploading signed binary artifacts.
- Running a wider public announcement campaign.
- Installing globally or mutating workstation/user configuration.
