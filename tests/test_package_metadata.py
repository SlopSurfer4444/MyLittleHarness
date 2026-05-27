from __future__ import annotations

import ast
import os
import sys
import tempfile
import tomllib
import unittest
import zipfile
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "build_backend"))

from mylittleharness import __version__
from mylittleharness.agent_roles import role_manifest as agent_role_manifest
from mylittleharness.agent_roles import role_profile_for_id, roles_with_apply_authority
from mylittleharness.command_discovery import command_intent_registry, command_suggestions_for_intent
from mylittleharness.inventory import EXPECTED_SPEC_NAMES
from mylittleharness.routes import route_manifest, route_protocol_for_id
import mylittleharness_build


EXTERNAL_AUDIT_SAFETY_FAILURE_COVERAGE_MATRIX = {
    "malformed claim mutation records": {
        "tests/test_cli.py": (
            "test_claim_release_and_extend_refuse_malformed_existing_claim_without_writing",
            "test_claim_status_and_agents_check_warn_on_malformed_work_claim_metadata",
        ),
    },
    "concurrent claims": {
        "tests/test_cli.py": (
            "test_claim_apply_refuses_concurrent_overlapping_create_while_mutation_lock_is_held",
        ),
    },
    "attach late failures": {
        "tests/test_cli.py": (
            "test_attach_apply_does_not_run_codex_hook_adapter_by_default_after_scaffold_writes",
            "test_attach_apply_reports_recovery_when_projection_build_fails_after_scaffold_writes",
        ),
    },
    "transition partial failures": {
        "tests/test_cli.py": (
            "test_transition_apply_reports_partial_recovery_when_next_plan_delegate_fails_after_archive",
            "test_transition_apply_reports_partial_recovery_when_next_roadmap_delegate_fails_after_next_plan",
        ),
    },
    "transaction confinement": {
        "tests/test_cli.py": (
            "test_phase_owned_file_transaction_calls_pass_explicit_root",
            "test_file_transaction_refuses_parent_traversal_outside_explicit_root_before_writes",
            "test_file_transaction_refuses_symlink_parent_inside_explicit_root_before_writes",
        ),
        "tests/test_projection_artifacts.py": (
            "test_projection_build_refuses_boundary_path_conflict_without_partial_writes",
        ),
    },
    "generated-cache command wording": {
        "tests/test_cli.py": (
            "test_dashboard_json_includes_agent_packet_cache_posture_and_lifecycle_provenance",
            "test_adapter_mcp_payload_exposes_cache_posture_without_refresh_authority",
        ),
        "tests/test_projection_artifacts.py": (
            "test_projection_warm_cache_target_all_refreshes_disposable_cache_only",
        ),
    },
    "root classification": {
        "tests/test_cli.py": (
            "test_malformed_partial_workflow_core_state_is_not_classified_as_live_root",
            "test_adapter_reports_root_classification_as_coarse_boundary",
        ),
    },
    "adapter source-body boundaries": {
        "tests/test_cli.py": (
            "test_adapter_serve_mcp_stdio_lifecycle_tool_call_and_no_writes",
            "test_adapter_serve_mcp_stdio_source_search_and_related_tools_are_bounded_read_only",
            "test_adapter_serve_mcp_stdio_read_source_rejects_path_escape_without_writes",
        ),
    },
}


class PackageMetadataTests(unittest.TestCase):
    def test_package_metadata_matches_runtime_contract(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = pyproject["project"]

        self.assertEqual("mylittleharness", project["name"])
        self.assertEqual(__version__, project["version"])
        self.assertEqual("1.0.0", __version__)
        self.assertEqual([], project["dependencies"])
        self.assertEqual({"text": "Apache-2.0"}, project["license"])
        self.assertIn("License :: OSI Approved :: Apache Software License", project["classifiers"])
        self.assertEqual({"mylittleharness": "mylittleharness.cli:main"}, project["scripts"])

    def test_external_audit_safety_failure_coverage_matrix_points_to_regressions(self) -> None:
        expected_classes = {
            "malformed claim mutation records",
            "concurrent claims",
            "attach late failures",
            "transition partial failures",
            "transaction confinement",
            "generated-cache command wording",
            "root classification",
            "adapter source-body boundaries",
        }
        self.assertEqual(expected_classes, set(EXTERNAL_AUDIT_SAFETY_FAILURE_COVERAGE_MATRIX))

        test_names_by_file: dict[str, set[str]] = {}
        for rel_path in {
            path
            for file_map in EXTERNAL_AUDIT_SAFETY_FAILURE_COVERAGE_MATRIX.values()
            for path in file_map
        }:
            tree = ast.parse((ROOT / rel_path).read_text(encoding="utf-8"), filename=rel_path)
            test_names_by_file[rel_path] = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
            }

        missing = []
        for risk_class, file_map in EXTERNAL_AUDIT_SAFETY_FAILURE_COVERAGE_MATRIX.items():
            for rel_path, expected_tests in file_map.items():
                for test_name in expected_tests:
                    if test_name not in test_names_by_file[rel_path]:
                        missing.append(f"{risk_class}: {rel_path}::{test_name}")

        self.assertEqual([], missing)

    def test_stdlib_build_backend_stays_self_contained(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual([], pyproject["build-system"]["requires"])
        self.assertEqual("mylittleharness_build", pyproject["build-system"]["build-backend"])
        self.assertEqual(["build_backend"], pyproject["build-system"]["backend-path"])
        self.assertTrue((ROOT / "build_backend/mylittleharness_build.py").is_file())
        docmap = (ROOT / ".agents/docmap.yaml").read_text(encoding="utf-8")
        self.assertIn('"build_backend/mylittleharness_build.py"', docmap)
        self.assertNotIn('"../build_backend/mylittleharness_build.py"', docmap)

    def test_dependency_gate_keeps_candidate_libraries_out_of_package_metadata(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = pyproject["project"]
        build_system = pyproject["build-system"]
        gate = pyproject["tool"]["mylittleharness"]["dependency-gate"]

        declared_packages = set(project["dependencies"])
        declared_packages.update(build_system["requires"])
        gated_candidates = {"marko", "patch-ng", "portalocker", "msgspec"}

        self.assertEqual(set(), declared_packages)
        self.assertTrue(gated_candidates.isdisjoint(declared_packages))
        self.assertEqual("stdlib-first", gate["default_policy"])
        self.assertEqual("approval-packet-required", gate["external_dependency_additions"])
        self.assertEqual(
            ["package-smoke", "license-supply-chain-review", "no-telemetry", "rollback-plan"],
            gate["required_evidence"],
        )
        self.assertEqual(["marko", "patch-ng", "portalocker", "msgspec"], gate["future_spikes"])

    def test_dependency_gate_policy_docs_require_review_before_adoption(self) -> None:
        metadata = (ROOT / "docs/specs/metadata-routing-and-evidence.md").read_text(encoding="utf-8")
        capability = (ROOT / "project/specs/workflow/workflow-capability-roadmap-spec.md").read_text(
            encoding="utf-8"
        )

        for doc in (metadata, capability):
            for expected in (
                "stdlib-first dependency gate",
                "approval packet",
                "package smoke",
                "license/supply-chain review",
                "no telemetry",
                "rollback plan",
                "Marko, patch-ng, portalocker, and msgspec remain future gated spikes only",
                "no dependency adoption by default",
            ):
                self.assertIn(expected, doc)

    def test_authority_context_tiers_and_approval_packet_policy_are_documented(self) -> None:
        authority = (ROOT / "docs/specs/authority-and-memory.md").read_text(encoding="utf-8")
        context_budget = (ROOT / "docs/specs/context-and-ceremony-budget.md").read_text(encoding="utf-8")
        metadata = (ROOT / "docs/specs/metadata-routing-and-evidence.md").read_text(encoding="utf-8")
        artifact_model = (ROOT / "project/specs/workflow/workflow-artifact-model-spec.md").read_text(
            encoding="utf-8"
        )

        for expected in (
            "Hot Authority",
            "On-Demand Routes",
            "Generated Projections",
            "Archive/Evidence",
            "default recovery surface",
            "read when the current question needs their lane",
            "rebuildable navigation caches",
            "cold source-bound evidence recovered by pointer",
            "Source-Bound Memory Capsules",
            "source-bound memory capsule",
            "stale_or_unknown",
            "failed-attempt budget",
            "next safe command",
            "source refs",
            "not a hidden memory runtime",
            "Provider compaction items",
        ):
            self.assertIn(expected, authority)

        for expected in (
            "Long-session compaction should produce a source-bound memory capsule",
            "failed-attempt budget",
            "next safe command",
            "source refs",
            "stale_or_unknown",
            "provider compaction, prompt caching, retrieval, SQLite/projection indexes",
            "source-bound memory capsules include source refs, stale_or_unknown markers, failed-attempt budget, next safe command",
            "CLI command discovery follows the same progressive-disclosure budget",
            "Top-level `mylittleharness --help` should foreground only the primary operator commands",
            "internal suppression sentinels such as `==SUPPRESS==` must never render as top-level help rows",
            "top-level CLI help hides advanced command rows without suppression sentinels",
        ):
            self.assertIn(expected, context_budget)

        for expected in (
            "Approval-packet gate classes",
            "`lifecycle-authority-mutation`",
            "`write-scope-expansion`",
            "`dependency-package-supply-chain`",
            "`destructive-archive-vcs-rollback`",
            "`external-service-secrets-network`",
            "`fan-in-merge-review-token`",
            "`repeated-verifier-failure-or-uncertain-evidence`",
            "allowed command/network/auth scopes",
            "review-token hash",
            "Packet status is evidence",
        ):
            self.assertIn(expected, metadata)

        for expected in (
            "Approval packets are required for risky operations",
            "Gate classes include lifecycle authority mutation",
            "write-scope expansion",
            "dependency/package/supply-chain change",
            "external service/secrets/network use",
            "repeated verifier failure or uncertain evidence",
            "The packet is cold evidence",
            "not implementation proof or lifecycle authority",
        ):
            self.assertIn(expected, artifact_model)

    def test_wheel_includes_stable_spec_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wheel_name = mylittleharness_build.build_wheel(tmp)
            with zipfile.ZipFile(Path(tmp) / wheel_name) as wheel:
                names = set(wheel.namelist())

        self.assertIn("mylittleharness/templates/operating-root/AGENTS.md", names)
        self.assertIn("mylittleharness/agent_roles.py", names)
        self.assertIn("mylittleharness/command_discovery.py", names)
        self.assertIn("mylittleharness/templates/workflow/workflow-artifact-model-spec.md", names)
        self.assertIn("mylittleharness/templates/workflow/workflow-plan-synthesis-spec.md", names)

    def test_build_backend_rejects_path_shaped_metadata_before_outputs(self) -> None:
        original_project_metadata = mylittleharness_build._project_metadata
        try:
            mylittleharness_build._project_metadata = lambda: {"name": "../escape", "version": "1.0.0"}
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)
                with self.assertRaisesRegex(ValueError, "path separators"):
                    mylittleharness_build.build_wheel(str(output))
                self.assertEqual([], list(output.iterdir()))

            mylittleharness_build._project_metadata = lambda: {"name": "mylittleharness", "version": "../escape"}
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)
                with self.assertRaisesRegex(ValueError, "path"):
                    mylittleharness_build.prepare_metadata_for_build_wheel(str(output))
                self.assertEqual([], list(output.iterdir()))
        finally:
            mylittleharness_build._project_metadata = original_project_metadata

    def test_build_backend_refuses_symlinked_package_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "product"
            package = root / "src/mylittleharness"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
            (root / "pyproject.toml").write_text(
                "[project]\n"
                'name = "mylittleharness"\n'
                'version = "1.0.0"\n',
                encoding="utf-8",
            )
            outside = Path(tmp) / "outside.py"
            outside.write_text("secret = True\n", encoding="utf-8")
            link = package / "symlinked_secret.py"
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"file symlinks are unavailable: {exc}")

            original_root = mylittleharness_build.ROOT
            try:
                mylittleharness_build.ROOT = root
                with tempfile.TemporaryDirectory() as wheel_tmp:
                    with self.assertRaisesRegex(ValueError, "symlinked package source member"):
                        mylittleharness_build.build_wheel(wheel_tmp)
            finally:
                mylittleharness_build.ROOT = original_root

    def test_stable_spec_templates_are_review_required_bootstrap_stubs(self) -> None:
        template_dir = ROOT / "src/mylittleharness/templates/workflow"
        for name in EXPECTED_SPEC_NAMES:
            with self.subTest(name=name):
                text = (template_dir / name).read_text(encoding="utf-8")
                self.assertIn("intentionally minimal bootstrap stub", text)
                self.assertIn("review-required", text)

        operating_root = (ROOT / "docs/specs/operating-root.md").read_text(encoding="utf-8")
        self.assertIn("Packaged stable spec templates are intentionally minimal bootstrap stubs", operating_root)
        self.assertIn("repair output marks created specs review-required", operating_root)

    def test_wheel_metadata_keeps_local_install_entrypoint_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wheel_name = mylittleharness_build.build_wheel(tmp)
            self.assertEqual("mylittleharness-1.0.0-py3-none-any.whl", wheel_name)
            with zipfile.ZipFile(Path(tmp) / wheel_name) as wheel:
                names = set(wheel.namelist())
                metadata = wheel.read("mylittleharness-1.0.0.dist-info/METADATA").decode("utf-8")
                entry_points = wheel.read("mylittleharness-1.0.0.dist-info/entry_points.txt").decode("utf-8")
                license_text = wheel.read("mylittleharness-1.0.0.dist-info/LICENSE").decode("utf-8")

        self.assertIn("Name: mylittleharness\n", metadata)
        self.assertIn("Version: 1.0.0\n", metadata)
        self.assertIn("License: Apache-2.0\n", metadata)
        self.assertIn("Classifier: License :: OSI Approved :: Apache Software License\n", metadata)
        self.assertIn("mylittleharness-1.0.0.dist-info/LICENSE", names)
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0, January 2004", license_text)
        self.assertIn("[console_scripts]\n", entry_points)
        self.assertIn("mylittleharness = mylittleharness.cli:main\n", entry_points)

    def test_public_package_metadata_keeps_agent_neutral_golden_path(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = pyproject["project"]
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        command_surface = (ROOT / "docs/reference/command-surface.md").read_text(encoding="utf-8")
        security = (ROOT / "docs/security.md").read_text(encoding="utf-8")
        template = (ROOT / "src/mylittleharness/templates/operating-root/AGENTS.md").read_text(
            encoding="utf-8"
        )
        package_surface = "\n".join(
            [
                project["name"],
                project["description"],
                project["readme"],
                "\n".join(project["scripts"].keys()),
                "\n".join(project["scripts"].values()),
            ]
        )

        self.assertIn("mylittleharness", package_surface)
        self.assertIn("mylittleharness.cli:main", package_surface)
        self.assertNotIn("Codex", package_surface)
        self.assertNotIn(".codex", package_surface)
        for doc in (readme, docs_readme, security):
            self.assertIn(
                "Public GitHub golden path: source, docs, tests, package metadata, and CI evidence.",
                doc,
            )
            self.assertIn("operating memory belongs in target repositories", doc)
        for doc in (readme, docs_readme, command_surface, security, template):
            self.assertIn(".mylittleharness/project-workflow.toml", doc)
            self.assertIn(
                "`.codex/project-workflow.toml` is legacy/client-adapter compatibility",
                doc,
            )
        self.assertIn("The default command story is agent-neutral", command_surface)
        self.assertIn("Core operation is agent-neutral", template)

    def test_release_readiness_docs_keep_publication_optional(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        boundary = (ROOT / "docs/specs/product-boundary.md").read_text(encoding="utf-8")
        operating_root = (ROOT / "docs/specs/operating-root.md").read_text(encoding="utf-8")

        self.assertIn("The local release checklist is:", readme)
        for expected in (
            "package metadata and runtime version agree on `1.0.0`",
            "`bootstrap --package-smoke` passes from temporary source/build/install locations outside the product source checkout",
            "Wheel, build, and install artifacts are verification outputs only",
            "rejects standalone `bootstrap --apply`",
        ):
            self.assertIn(expected, readme)
        for expected in (
            "documentation-and-verification based",
            "Package-index publication, signed artifact release, global installation",
        ):
            self.assertIn(expected, docs_readme)
        for expected in (
            "not by publication",
            "ephemeral verification artifacts",
            "not required for release-candidate correctness",
        ):
            self.assertIn(expected, boundary)
        for expected in (
            "rejects symlinked package members and path-shaped package metadata before build/install",
            "creates the virtual environment without system site packages",
            "requires the installed console script to exist",
            "Routine `check` reports PATH-discovered console scripts as static workstation context only",
        ):
            self.assertIn(expected, operating_root)

    def test_removed_root_transition_terms_stay_out_of_product_files(self) -> None:
        terms = ("switch" + "-over", "switch" + "over", "switch" + " over")
        pattern = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)
        roots = (
            ROOT / ".agents",
            ROOT / "docs",
            ROOT / "project",
            ROOT / "src",
            ROOT / "tests",
        )
        files = [ROOT / "AGENTS.md", ROOT / "README.md", ROOT / "pyproject.toml"]
        for root in roots:
            files.extend(path for path in root.rglob("*") if path.is_file())
        offenders = []
        for path in files:
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], offenders)

    def test_first_run_docs_keep_small_operator_path_primary(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs/architecture/product-architecture.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")

        for expected in (
            "## First-Run Operator Path",
            "python -m mylittleharness --root $ProductRoot bootstrap --package-smoke",
            "python -m mylittleharness --root $TargetRoot init --dry-run",
            "python -m mylittleharness --root $TargetRoot check",
            "python -m mylittleharness --root $TargetRoot migrate --dry-run",
            "python -m mylittleharness --root $TargetRoot repair --dry-run",
            "python -m mylittleharness --root $TargetRoot detach --dry-run",
            "Apply modes stay explicit and target-bound",
            "they are not required first-contact steps",
        ):
            self.assertIn(expected, readme)
        for forbidden in (
            "python -m mylittleharness --root $ProductRoot init --dry-run",
            "python -m mylittleharness --root $ProductRoot repair --dry-run",
            "python -m mylittleharness --root $ProductRoot detach --dry-run",
        ):
            self.assertNotIn(forbidden, readme)
        for expected in (
            "The first-run operator path is deliberately shorter than the full diagnostic surface",
            "then point `--root` at the target repository",
            "not prerequisites for first-run correctness",
        ):
            self.assertIn(expected, docs_readme)
        for expected in (
            "The first-run path is source checkout first",
            "target-repository `init` / `check` / `repair` / `detach`",
            "not prerequisites for first-contact correctness",
        ):
            self.assertIn(expected, architecture)
        for expected in (
            "The first-run operator path starts from source-checkout usage",
            "then points `--root` at the target repository",
            "`init --dry-run`, `check`, optional legacy-manifest `migrate --dry-run`, `repair --dry-run`, and `detach --dry-run`",
        ):
            self.assertIn(expected, cli_spec)

    def test_portable_start_pass_contract_has_no_skill_dependency(self) -> None:
        template = (ROOT / "src/mylittleharness/templates/operating-root/AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs/architecture/product-architecture.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")

        for expected in (
            "Any file-reading, shell-capable agent can operate",
            "installed skills, IDE rules, MCP clients, hooks, and CI are optional convenience layers only",
            "Start by reading this `AGENTS.md`, `.mylittleharness/project-workflow.toml`, and `project/project-state.md`",
            "use `.codex/project-workflow.toml` only as the legacy fallback manifest when the neutral manifest is absent",
            'Read `project/implementation-plan.md` only when `project/project-state.md` or the manifest says `plan_status = "active"`',
            'When `plan_status = "active"`, prefer first-class `active_phase` and `phase_status` values',
            "Use MLH lifecycle routes instead of ad hoc memory pockets",
            "Use the optional docs routing file when present as a routing aid",
            "Run `mylittleharness --root <this-repo> check` before mutating repair work",
            "Agent behavior defaults: think before editing; prefer the simplest bounded fix",
        ):
            self.assertIn(expected, template)
        for expected in (
            "Any file-reading, shell-capable agent can use MyLittleHarness from repo-visible files plus CLI reports",
            "Start with `AGENTS.md`, `.mylittleharness/project-workflow.toml`, and `project/project-state.md`",
            "use `.codex/project-workflow.toml` only as the legacy fallback manifest when the neutral manifest is absent",
            "`project/implementation-plan.md` only when `plan_status = \"active\"`",
            "`active_phase` and `phase_status`",
            "`status`/`check` report a compact lifecycle route table for live roots",
            "`project/roadmap.md` sequencing route",
            "decision/do-not-revisit records",
            "ADR records",
            "`intelligence --focus routes` prints the same read-only route table",
            "start with `dashboard --inspect` or `dashboard --inspect --json` as the cockpit packet",
            "`adapter --client-config --target mcp-read-projection`",
            "`rg` or direct file reads for exact verification",
            "Codex skills, IDE-native rules, MCP clients, shell aliases, preflight wrappers, hooks, and CI may wrap this flow",
        ):
            self.assertIn(expected, readme)
        for expected in (
            "The operating-root start pass is portable across agents that can read files and run shell commands",
            "Route discovery is part of the visible lifecycle routing contract",
            "optional roadmap",
            "decision/do-not-revisit",
            "ADR",
            "`project/roadmap.md` is an optional live-root sequencing surface",
            "Product-source fixtures do not emit live route-table rows",
            "do not require Codex skills, IDE-native skills, MCP clients, hooks, CI, or workstation adoption",
        ):
            self.assertIn(expected, docs_readme)
        self.assertIn("No skill, IDE rule, MCP client, hook, CI job, or workstation adoption step is part of the correctness path", architecture)
        self.assertIn("The no-skill start pass is part of the CLI contract", cli_spec)
        self.assertIn("no `docs-impact`, `guide`, or `orient` command is required for v1", cli_spec)

    def test_docs_decision_contract_is_portable(self) -> None:
        template = (ROOT / "src/mylittleharness/templates/operating-root/AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs/architecture/product-architecture.md").read_text(encoding="utf-8")
        authority = (ROOT / "docs/specs/authority-and-memory.md").read_text(encoding="utf-8")
        metadata = (ROOT / "docs/specs/metadata-routing-and-evidence.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")

        for doc in (template, readme, docs_readme, architecture, metadata, cli_spec):
            self.assertIn("updated", doc)
            self.assertIn("not-needed", doc)
            self.assertIn("uncertain", doc)
        for doc in (readme, docs_readme, metadata, cli_spec):
            self.assertIn(
                "behavior, CLI usage, configuration, setup, contract meaning, permissions, output shape, UX/copy, terminology, rollout, migration",
                doc,
            )
            self.assertIn("`audit-links`", doc)
            self.assertIn("`check`", doc)
        self.assertIn("no Codex skill or generated docs-impact report is required for v1", readme)
        self.assertIn("A Codex skill, generated docs-impact report, IDE rule, MCP client, hook, or CI result may help route attention", metadata)
        self.assertIn("it cannot be required for the decision and cannot store the only copy of the decision", metadata)
        self.assertIn("marked closeout writeback block in `project/project-state.md`", metadata)
        self.assertIn("exact active-plan closeout bullets inside explicit Docs Decision, State Transfer, or closeout summary/facts/fields sections", metadata)
        self.assertIn("schema examples, roadmap fields, and closeout checklist items are not derived closeout copies", metadata)
        self.assertIn("`writeback --apply` synchronizes requested derived copies", docs_readme)
        self.assertIn("Optional `--roadmap-item` sync uses only same-request closeout facts", docs_readme)
        self.assertIn("`plan_id`, `active_plan`, and `archived_plan`", docs_readme)
        self.assertIn("carry, replace, or refuse", docs_readme)
        self.assertIn("Partial closeout updates may carry existing facts only when the recorded identity matches", metadata)
        self.assertIn("plan-identity carry/replace/refusal guardrail", cli_spec)
        self.assertIn("Lifecycle `phase_status = complete` becomes `done` in the phase body", docs_readme)
        self.assertIn("Archive-active-plan refuses uncompleted lifecycle state", cli_spec)
        self.assertIn("same reviewed writeback request supplies `--phase-status complete`", cli_spec)
        self.assertIn("synchronized completed `status`/`phase_status` derived copies", docs_readme)
        self.assertIn("ready-for-closeout boundary", metadata)
        self.assertIn("post-writeback plus compact-only operating-memory compaction", docs_readme)
        self.assertIn("`writeback --dry-run|--apply --compact-only`", docs_readme)
        self.assertIn("State compaction selection scans the whole `project/project-state.md`", docs_readme)
        self.assertIn("default 250-line or 25,000-character threshold", metadata)
        self.assertIn("compact-only apply requires the matching `--source-hash`", authority)
        self.assertIn("Working-memory compaction has three explicit route shapes", metadata)
        self.assertIn("provider-owned memory, a daemon, or next-plan opening", metadata)
        self.assertIn("identity-bound archived-plan closeout refresh", authority)
        self.assertIn("existing HEAD trailers may be parsed with read-only `git interpret-trailers --parse`", metadata)
        self.assertIn("Parsed existing HEAD trailers are historical context only", metadata)
        self.assertIn("`writeback --dry-run|--apply --archived-plan <project/archive/plans/...>`", cli_spec)
        self.assertIn("compacted Archived Completed History lines are evidence", metadata)

    def test_entry_docs_distinguish_evidence_report_from_record_rail(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        state = (ROOT / "project/project-state.md").read_text(encoding="utf-8")

        for doc in (readme, docs_readme, state):
            self.assertIn("evidence --record", doc)
        self.assertIn("bare `evidence`, `evidence --record`", readme)
        self.assertIn("Bare `evidence` is a terminal-only read-only report", state)
        self.assertIn("Agent Run Evidence", state)
        self.assertIn("--focus search|warnings|projection|routes", state)
        self.assertIn("bare `evidence`, and `closeout` are CLI reports", docs_readme)
        self.assertIn("is an explicit source-bound record rail", docs_readme)

    def test_optional_adapter_docs_reject_skill_owned_memory(self) -> None:
        adapter = (ROOT / "docs/specs/adapter-boundary.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for expected in (
            "Optional wrappers such as Codex skills, IDE rules, shell aliases, preflight wrappers, MCP clients, hooks, CI jobs, and future adapter packs",
            "must not become the first-run path, docs-decision path, repair path, verification path, closeout path",
            "skill-only correctness and skill-owned memory are rejected",
        ):
            self.assertIn(expected, adapter)
        self.assertIn("must not store the only copy of accepted decisions, current focus, docs decisions, repair approval, verification, or closeout evidence", readme)

    def test_v2_architecture_foundation_docs_reject_swarm_runtime(self) -> None:
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        authority = (ROOT / "docs/specs/authority-and-memory.md").read_text(encoding="utf-8")
        metadata = (ROOT / "docs/specs/metadata-routing-and-evidence.md").read_text(encoding="utf-8")
        adapter = (ROOT / "docs/specs/adapter-boundary.md").read_text(encoding="utf-8")
        artifact_model = (ROOT / "project/specs/workflow/workflow-artifact-model-spec.md").read_text(encoding="utf-8")
        closeout = (ROOT / "project/specs/workflow/workflow-verification-and-closeout-spec.md").read_text(encoding="utf-8")
        capability = (ROOT / "project/specs/workflow/workflow-capability-roadmap-spec.md").read_text(encoding="utf-8")

        for expected in (
            "V2 Architecture Direction",
            "deterministic State around the target repository",
            "Route manifests and structured findings come before role profiles",
            "`manifest --inspect --json`",
            "`role_manifest`",
            "Product docs should continue rejecting `swarm run` as the first v2 command",
            "`parallelism_class`",
            "`claim_scope`",
            "`fan_in_gate`",
            "`worker_space_boundary`",
            "`fan_in_output_required`",
        ):
            self.assertIn(expected, docs_readme)
        for expected in (
            "V2 Agent Governance Foundation",
            "route manifest and structured findings",
            "role profiles describe allowed reads",
            "No role profile carries direct apply authority",
            "handoff packets and work claims",
            "review tokens and approval packets",
            "not imply `swarm run`, hidden queues, provider credentials, model gateway behavior",
        ):
            self.assertIn(expected, authority)
        for expected in (
            "V2 Governance Metadata",
            "`gate_class`",
            "`provider`",
            "`model_id`",
            "Reconcile output is proposal metadata only",
            "must not silently edit accepted specs to match implementation",
        ):
            self.assertIn(expected, metadata)
        for expected in (
            "V2 External Orchestrator Boundary",
            "`manifest --inspect --json` exposes `route_manifest` and advisory `role_manifest`",
            "provider/model/tool routing is policy metadata before it is runtime ownership",
            "optional relay adapters may transport approval packets only after core packets and review tokens exist",
            "`parallelism_class`",
            "`orchestration_role`",
            "`fan_in_output_required`",
            "Do not add a hidden swarm runtime",
        ):
            self.assertIn(expected, adapter)
        self.assertIn("Route and role manifests are protocol views", artifact_model)
        self.assertIn("without spawning workers or granting direct apply authority", artifact_model)
        self.assertIn("manifest fields are verification inputs rather than runtime proof", closeout)
        self.assertIn("route manifest orchestration fields and role manifest coordination fields", capability)

    def test_multi_agent_coordination_direction_keeps_adapters_subordinate(self) -> None:
        authority = (ROOT / "docs/specs/authority-and-memory.md").read_text(encoding="utf-8")
        metadata = (ROOT / "docs/specs/metadata-routing-and-evidence.md").read_text(encoding="utf-8")
        adapter = (ROOT / "docs/specs/adapter-boundary.md").read_text(encoding="utf-8")
        layer_model = (ROOT / "docs/architecture/layer-model.md").read_text(encoding="utf-8")

        for expected in (
            "coordination-first",
            "repo-visible routes stay the durable authority",
            "claims, agent-run records, handoff packets, and session-scoped active work",
            "hooks are sensors, blockers, and context injectors",
            "dashboard and `mlhd` runtime surfaces are cockpit projections",
            "dispatcher cannot start work until a handoff packet, active claim, and evidence path exist",
        ):
            self.assertIn(expected, authority)
        for expected in (
            "project/verification/work-claims/*.json",
            "project/verification/agent-runs/*.md",
            "project/verification/handoffs/*.json",
            "project/verification/session-work/*.json",
            "runtime cache is disposable",
            "claims, runs, handoffs, and session state are coordination evidence",
        ):
            self.assertIn(expected, metadata)
        for expected in (
            "Hooks are sensors, blockers, and context injectors",
            "Read-only dashboards are cockpit projections",
            "`mlhd` is an optional runtime cache and notification/process helper",
            "Dispatchers and launchers are last-mile adapters",
        ):
            self.assertIn(expected, adapter)
        self.assertIn("Coordination substrate", layer_model)
        self.assertIn("claims, runs, handoffs, session work, worktree coordination, and route receipts", layer_model)
        self.assertIn("dashboard, daemon, hook, dispatcher, MCP, or A2A adapter", layer_model)

    def test_mlhd_daemon_boundary_is_contract_only_before_control_plane(self) -> None:
        generated_state = (ROOT / "docs/specs/generated-state-and-projections.md").read_text(encoding="utf-8")
        sqlite_spec = (ROOT / "docs/specs/generated-state-search-and-sqlite.md").read_text(encoding="utf-8")
        adapter = (ROOT / "docs/specs/adapter-boundary.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")

        for expected in (
            "mlhd.projection_pulse",
            "projection --warm-cache --target all",
            "cannot become cache freshness or lifecycle authority",
            "mlhd daemon contract is optional and disabled by default",
            "runtime storage stays under `.mylittleharness/runtime/mlhd/`",
            "The implemented `mlhd` control plane exposes `status`, `doctor`, `start`, `stop`, `run-once`, `install`, and `uninstall`",
            "`mlhd install --apply` writes a deterministic root-local `autostart.json` manifest",
            "`mlhd start --apply` launches a local polling worker that repeatedly runs that generated freshness tick without creating a filesystem watcher or lifecycle authority",
            "No daemon process, listener, scheduler, filesystem watcher, OS/user autostart entry, or supervision process is created by attach, repair, dashboard, check, hooks, MCP, projection, or `mlhd` control-plane commands",
            "Daemon process autostart or supervision beyond the root-local manifest requires a later reviewed dry-run/apply rail",
            "No hidden control plane",
        ):
            self.assertIn(expected, generated_state)
        for expected in (
            "must not auto-run it from a read-only adapter",
            "preserves old-good projection artifacts and SQLite indexes when a publish fails",
            "No hidden control plane, scheduler, queue, or daemon.",
        ):
            self.assertIn(expected, sqlite_spec)
        for expected in (
            "## Implemented mlhd Runtime Cockpit Slice",
            "`mlhd` is represented as optional runtime cockpit posture under `.mylittleharness/runtime/mlhd`",
            "The mlhd daemon contract is optional and disabled by default",
            "runtime storage stays under `.mylittleharness/runtime/mlhd/`",
            "the autostart manifest is readiness evidence, not worker supervision",
            "OS startup registration, or lifecycle approval",
            "If a later slice introduces a daemon process, OS/user autostart entry, supervision process, or serve rail beyond the root-local manifest",
            "Any future serve rail must be explicit, local-only by default",
            "Durable mutations stay delegated to MLH CLI rails with dry-run/apply semantics",
            "cannot approve repair, closeout, archive, roadmap status, staging, commit, push, rollback, release, dispatcher work, or daemon truth",
        ):
            self.assertIn(expected, adapter)
        for expected in (
            "No init/attach/repair mutation of product fixtures, fallback roots, active plans, archives, user config, PATH, hooks, adapters, MCP, GitHub, generated projections, caches, logs, reports, local databases, package archives, or workflow execution surfaces.",
            "No background daemon, scheduler, queue, or dashboard.",
            "`mlhd status` is the read-only local control-plane inspection surface",
            "`mlhd start`, `mlhd stop`, `mlhd run-once`, `mlhd install`, and `mlhd uninstall` require exactly one of `--dry-run` or `--apply`",
            "No daemon process, listener, scheduler, or OS/user autostart entry is created by attach, repair, dashboard, check, hooks, MCP, projection, or mlhd commands",
            "The implemented `mlhd install/uninstall` rail manages only a root-local `.mylittleharness/runtime/mlhd/autostart.json` manifest",
            "daemon process autostart or supervision still requires a later reviewed dry-run/apply rail",
        ):
            self.assertIn(expected, cli_spec)

    def test_route_manifest_protocol_shape_is_package_stable(self) -> None:
        manifest = {row["route_id"]: row for row in route_manifest()}

        self.assertIn("state", manifest)
        self.assertIn("active-plan", manifest)
        self.assertIn("agent-runs", manifest)
        self.assertIn("work-claims", manifest)
        self.assertIn("generated-cache", manifest)
        state = manifest["state"]
        self.assertEqual("project/project-state.md", state["target"])
        for key in (
            "authority",
            "start_path",
            "mutability",
            "human_gate",
            "gate_class",
            "human_gate_reason",
            "allowed_decisions",
            "advisory",
            "parallelism_class",
            "authority_lane",
            "exclusive_owner",
            "claim_scope",
            "claim_required",
            "merge_policy",
            "fan_in_gate",
            "max_parallelism_hint",
            "stale_claim_policy",
            "conflict_policy",
        ):
            self.assertIn(key, state)
        self.assertEqual("lifecycle", state["gate_class"])
        self.assertEqual("sequential_only", state["parallelism_class"])
        self.assertEqual("coordinator", state["exclusive_owner"])
        self.assertEqual(["route", "lifecycle"], state["claim_scope"])
        self.assertIn("writeback", state["allowed_decisions"])
        protocol = route_protocol_for_id("generated-cache")
        self.assertEqual("generated-rebuildable", protocol["mutability"])
        self.assertEqual("safe_parallel", protocol["parallelism_class"])
        self.assertEqual("generated_cache", protocol["authority_lane"])
        self.assertFalse(protocol["claim_required"])
        self.assertFalse(protocol["human_gate"]["required"])
        agent_runs = manifest["agent-runs"]
        self.assertEqual("project/verification/agent-runs/*.md", agent_runs["target"])
        self.assertEqual("evidence", agent_runs["gate_class"])
        self.assertEqual("safe_parallel", agent_runs["parallelism_class"])
        self.assertIn("execution_slice", agent_runs["claim_scope"])
        self.assertIn("record", agent_runs["allowed_decisions"])
        self.assertTrue(agent_runs["advisory"])
        work_claims = manifest["work-claims"]
        self.assertEqual("project/verification/work-claims/*.json", work_claims["target"])
        self.assertEqual("evidence", work_claims["gate_class"])
        self.assertEqual("safe_parallel", work_claims["parallelism_class"])
        self.assertEqual("verification", work_claims["authority_lane"])
        self.assertIn("create", work_claims["allowed_decisions"])
        self.assertTrue(work_claims["advisory"])

    def test_agent_role_manifest_protocol_shape_is_package_stable(self) -> None:
        roles = {row["role_id"]: row for row in agent_role_manifest()}

        for role_id in (
            "intake-clerk",
            "researcher",
            "specifier",
            "planner",
            "coder",
            "reviewer",
            "verifier",
            "devops-sandbox-operator",
            "reconciler",
            "archivist",
            "governor",
        ):
            self.assertIn(role_id, roles)
        self.assertEqual((), roles_with_apply_authority())
        self.assertEqual("coder", role_profile_for_id("coder").role_id)
        self.assertIsNone(role_profile_for_id("missing"))

        coder = roles["coder"]
        for key in (
            "purpose",
            "default_inputs",
            "context_packet_requirements",
            "required_outputs",
            "output_packet_requirements",
            "permissions",
            "human_gates",
            "forbidden_actions",
            "stop_conditions",
            "orchestration_role",
            "may_spawn_workers",
            "worker_space_boundary",
            "isolation_contract",
            "fan_in_output_required",
            "coordination_budget",
            "apply_authority",
            "advisory",
        ):
            self.assertIn(key, coder)
        self.assertFalse(coder["apply_authority"])
        self.assertEqual("worker", coder["orchestration_role"])
        self.assertFalse(coder["may_spawn_workers"])
        self.assertIn("changed_paths", coder["fan_in_output_required"])
        self.assertIn("overlapping claims", " ".join(coder["isolation_contract"]))
        self.assertIn("changed_paths", coder["output_packet_requirements"])
        self.assertIn("change lifecycle state", coder["forbidden_actions"])
        governor = roles["governor"]
        self.assertEqual("coordinator", governor["orchestration_role"])
        self.assertFalse(governor["may_spawn_workers"])
        self.assertIn("review_token_status", governor["fan_in_output_required"])

        permission = next(row for row in coder["permissions"] if row["route_id"] == "verification")
        for key in (
            "read",
            "propose",
            "apply",
            "requires_human_gate",
            "gate_class",
            "mutability",
            "allowed_decisions",
            "human_gate",
            "advisory",
        ):
            self.assertIn(key, permission)
        self.assertTrue(permission["read"])
        self.assertTrue(permission["propose"])
        self.assertFalse(permission["apply"])
        self.assertIsInstance(permission["human_gate"]["allowed_decisions"], list)
        self.assertTrue(any(row["human_gate"]["required"] for row in roles["planner"]["permissions"]))

    def test_command_discovery_registry_shape_is_package_stable(self) -> None:
        registry = {entry.intent_id: entry for entry in command_intent_registry()}

        for intent_id in (
            "start-pass",
            "operator-audit-loop",
            "repair-preview",
            "open-active-plan",
            "archive-active-plan",
            "research-human-review-gate",
            "docs-route-recovery",
            "research-route-recovery",
            "projection-cache-refresh",
            "record-agent-evidence",
            "create-work-claim",
            "work-claim-review",
            "create-handoff-packet",
            "approval-packet-review",
            "command-discovery",
        ):
            self.assertIn(intent_id, registry)
            self.assertIn("mylittleharness --root <root>", registry[intent_id].first_safe_command)
            self.assertTrue(registry[intent_id].boundary)

        archive = command_suggestions_for_intent("archive active plan", limit=1)[0]
        self.assertEqual("archive-active-plan", archive.intent_id)
        self.assertIn("writeback --dry-run --archive-active-plan", archive.first_safe_command)
        self.assertIn("--phase-status complete", archive.first_safe_command)
        self.assertIn("does not stage, commit, push", archive.boundary)

        audit = command_suggestions_for_intent("autonomous audit free swim", limit=1)[0]
        self.assertEqual("operator-audit-loop", audit.intent_id)
        self.assertIn("check", audit.first_safe_command)
        self.assertIn('intelligence --query "<audit-topic-or-route-question>"', " ".join(audit.follow_up_commands))
        self.assertIn('meta-feedback --dry-run --from-root <observed-root> --topic "<topic>" --note "<note>"', " ".join(audit.follow_up_commands))
        self.assertIn("audit loop is read-only", audit.boundary)

        navigation = command_suggestions_for_intent("agent navigation route discovery reflex", limit=1)[0]
        self.assertEqual("agent-navigation-reflex", navigation.intent_id)
        self.assertIn("dashboard --inspect", navigation.first_safe_command)
        self.assertIn('intelligence --query "<topic-or-route-question>"', " ".join(navigation.follow_up_commands))
        self.assertIn("adapter --client-config --target mcp-read-projection", " ".join(navigation.follow_up_commands))
        self.assertIn("rg/direct file reads", navigation.root_posture)

        claim_review = command_suggestions_for_intent("stale claim cleanup missing run evidence", limit=1)[0]
        self.assertEqual("work-claim-review", claim_review.intent_id)
        self.assertIn("check --focus agents", claim_review.first_safe_command)
        self.assertIn("claim --status", " ".join(claim_review.follow_up_commands))
        self.assertIn('evidence --record --dry-run', " ".join(claim_review.follow_up_commands))
        self.assertIn('--task "<task>"', " ".join(claim_review.follow_up_commands))
        self.assertIn('--release-condition "<reviewed-condition>"', " ".join(claim_review.follow_up_commands))
        self.assertIn("claim cleanup remains report-only", claim_review.boundary)

        claim_suggestions = command_suggestions_for_intent("stale claim cleanup missing run evidence", limit=3)
        self.assertNotIn("recover-roadmap-source-incubation", {suggestion.intent_id for suggestion in claim_suggestions})

        claim_create = command_suggestions_for_intent("create work claim before editing source", limit=1)[0]
        self.assertEqual("create-work-claim", claim_create.intent_id)
        self.assertIn("claim --dry-run --action create", claim_create.first_safe_command)
        self.assertIn("claim --apply --action create", " ".join(claim_create.follow_up_commands))
        self.assertIn("coordination evidence only", claim_create.boundary)

        handoff_create = command_suggestions_for_intent("create handoff packet for worker", limit=3)
        self.assertEqual("create-handoff-packet", handoff_create[0].intent_id)
        self.assertIn("handoff --dry-run", handoff_create[0].first_safe_command)
        self.assertIn("handoff packets are coordination evidence only", handoff_create[0].boundary)
        self.assertNotIn("phase-closeout-handoff", {suggestion.intent_id for suggestion in handoff_create})
        self.assertNotIn("open-active-plan", {suggestion.intent_id for suggestion in handoff_create})

        approval_review = command_suggestions_for_intent("approval packet pending review", limit=1)[0]
        self.assertEqual("approval-packet-review", approval_review.intent_id)
        self.assertIn("check --focus agents", approval_review.first_safe_command)
        self.assertIn("approval-packet --dry-run", " ".join(approval_review.follow_up_commands))
        self.assertIn('--subject "<subject>"', " ".join(approval_review.follow_up_commands))
        self.assertIn('--human-gate-condition "<condition>"', " ".join(approval_review.follow_up_commands))
        self.assertIn("append-only human-gate evidence", approval_review.boundary)
        self.assertIn("prior packet as --input-ref", approval_review.boundary)

        approval_suggestions = command_suggestions_for_intent("approval packet pending review", limit=3)
        self.assertEqual(("approval-packet-review",), tuple(suggestion.intent_id for suggestion in approval_suggestions))

        recovery = command_suggestions_for_intent("roadmap source incubation missing", limit=1)[0]
        self.assertEqual("recover-roadmap-source-incubation", recovery.intent_id)
        self.assertIn("memory-hygiene --dry-run --scan", recovery.first_safe_command)
        self.assertIn("incubate --dry-run", " ".join(recovery.follow_up_commands))

        context_warning = command_suggestions_for_intent("explain README large warning", limit=1)[0]
        self.assertEqual("inspect-context-surface-budget", context_warning.intent_id)
        self.assertIn("check --focus context", context_warning.first_safe_command)
        self.assertNotIn("writeback --dry-run --compact-only", context_warning.first_safe_command)

        research_gate = command_suggestions_for_intent("requires_reflection deep research prompt", limit=1)[0]
        self.assertEqual("research-human-review-gate", research_gate.intent_id)
        self.assertIn("check", research_gate.first_safe_command)
        self.assertIn("Draft the external Deep Research request manually outside MyLittleHarness", " ".join(research_gate.follow_up_commands))
        self.assertIn("research-import --dry-run", " ".join(research_gate.follow_up_commands))
        self.assertIn("research-distill --dry-run", " ".join(research_gate.follow_up_commands))

        rubric_recovery = command_suggestions_for_intent("deep research rubric recovery", limit=1)[0]
        self.assertEqual("recover-deep-research-rubric", rubric_recovery.intent_id)
        self.assertIn("check", rubric_recovery.first_safe_command)
        self.assertIn("memory-hygiene --dry-run --scan", " ".join(rubric_recovery.follow_up_commands))
        self.assertIn("research-import --dry-run", " ".join(rubric_recovery.follow_up_commands))

        docs_recovery = command_suggestions_for_intent(
            "recover docs/specs/research-prompt-packets.md missing intelligence warning",
            limit=3,
        )
        self.assertEqual("docs-route-recovery", docs_recovery[0].intent_id)
        self.assertIn("intelligence --query", docs_recovery[0].first_safe_command)
        self.assertNotIn(
            "research-human-review-gate",
            {suggestion.intent_id for suggestion in docs_recovery},
        )
        self.assertNotIn(
            "recover-deep-research-rubric",
            {suggestion.intent_id for suggestion in docs_recovery},
        )
        self.assertNotIn(
            "recover-roadmap-source-incubation",
            {suggestion.intent_id for suggestion in docs_recovery},
        )
        self.assertNotIn("route-incoming-information", {suggestion.intent_id for suggestion in docs_recovery})
        self.assertNotIn("repair-preview", {suggestion.intent_id for suggestion in docs_recovery})

        research_recovery = command_suggestions_for_intent(
            "recover missing project/research/2026-05-07-agent-coding-plan-reliability-distillate.md provenance warning",
            limit=3,
        )
        self.assertEqual("research-route-recovery", research_recovery[0].intent_id)
        self.assertIn("intelligence --query", research_recovery[0].first_safe_command)
        self.assertIn("research-import --dry-run", " ".join(research_recovery[0].follow_up_commands))
        self.assertNotIn("docs-route-recovery", {suggestion.intent_id for suggestion in research_recovery})
        self.assertNotIn("research-human-review-gate", {suggestion.intent_id for suggestion in research_recovery})
        self.assertNotIn("recover-deep-research-rubric", {suggestion.intent_id for suggestion in research_recovery})
        self.assertNotIn("recover-roadmap-source-incubation", {suggestion.intent_id for suggestion in research_recovery})

        projection_cache = command_suggestions_for_intent("projection cache stale rebuild recommended", limit=3)
        self.assertEqual("projection-cache-refresh", projection_cache[0].intent_id)
        self.assertIn("projection --inspect --target all", projection_cache[0].first_safe_command)
        self.assertIn("projection --rebuild --target all", " ".join(projection_cache[0].follow_up_commands))
        self.assertNotIn("metadata-status-review", {suggestion.intent_id for suggestion in projection_cache})
        self.assertNotIn("roadmap-acceptance-readiness", {suggestion.intent_id for suggestion in projection_cache})

        self.assertEqual((), command_suggestions_for_intent("mirror product files across retired boundary", limit=3))

    def test_default_mcp_agent_tooling_docs_are_optional_and_read_only(self) -> None:
        template = (ROOT / "src/mylittleharness/templates/operating-root/AGENTS.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")
        projection_spec = (ROOT / "docs/specs/generated-state-and-projections.md").read_text(encoding="utf-8")

        self.assertLessEqual(len(template.splitlines()), 20)
        for doc in (template, docs_readme, cli_spec, projection_spec):
            self.assertIn("mylittleharness.read_projection", doc)
            self.assertIn("repo-visible files", doc)
        for expected in (
            "`adapter --client-config`",
            "no-write default-active MCP client configuration",
            "adapter inspection/client-config/stdio serving",
        ):
            self.assertIn(expected, docs_readme)
        for expected in (
            "`adapter --client-config --target mcp-read-projection`",
            "default-active agent tooling",
            "does not write user config",
            "Missing adapter mode, unknown target, or `--transport` with `--client-config` remain argparse usage failures",
        ):
            self.assertIn(expected, cli_spec)
        for expected in (
            "`adapter --client-config --target mcp-read-projection`",
            "without writing user config",
            "agents should use it as an optional read/projection helper before or alongside CLI/file reads",
            "cannot approve lifecycle decisions",
        ):
            self.assertIn(expected, projection_spec)
        for expected in (
            "optional string `root` tool argument",
            "reloads the selected MLH-serviced root inventory",
            "non-string `root` values",
        ):
            self.assertIn(expected, cli_spec)
        for expected in (
            "optional per-call `root` selection",
            "switching inspection between MLH-serviced roots",
            "reloads the selected root inventory in memory for each call",
        ):
            self.assertIn(expected, projection_spec)
        self.assertNotIn("accepts only an empty-object tool argument shape", cli_spec)

    def test_codex_hooks_docs_keep_explicit_adapter_outside_correctness_path(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")
        product_boundary = (ROOT / "docs/specs/product-boundary.md").read_text(encoding="utf-8")

        for doc in (readme, docs_readme):
            self.assertIn("create `.codex` by default", doc)
            self.assertIn("hooks adapter --client codex --dry-run|--apply --scope project", doc)
        for doc in (readme, docs_readme, cli_spec, product_boundary):
            self.assertIn("Codex native hooks", doc)
            self.assertIn("optional non-authoritative sensors", doc)
        for doc in (readme, docs_readme, cli_spec):
            self.assertIn("not correctness prerequisites", doc)
        self.assertIn("Successful `init --apply`/`attach --apply` creates the neutral `.mylittleharness/project-workflow.toml` manifest", readme)
        self.assertIn("Successful `init --apply` and compatibility `attach --apply` create the neutral `.mylittleharness/project-workflow.toml` manifest", docs_readme)
        self.assertIn("init --apply` and compatibility `attach --apply` do not write project-local Codex native hooks by default", cli_spec)
        self.assertIn("Those hooks are optional non-authoritative sensors, not correctness prerequisites", cli_spec)
        self.assertIn("cannot approve lifecycle, archive, roadmap, Git, release, provider, or product-diff decisions", cli_spec)
        self.assertIn("Fresh init/attach does not install the project-local Codex hook adapter by default", product_boundary)
        self.assertIn("not correctness prerequisites", product_boundary)
        self.assertNotIn("keep those project-local Codex native hooks current by default", cli_spec)
        self.assertNotIn("attach/init apply keeps the Codex hook adapter current by default", product_boundary)

    def test_rule_context_drift_docs_keep_check_compact(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")

        for expected in (
            "primary instruction-surface size warnings",
            "Deeper section-size detail remains in advanced `context-budget` and `doctor` diagnostics",
            "`check --deep` adds links, context, hygiene, and report-only grain diagnostics",
            "Grain diagnostics inspect active-plan slice size",
            "`intelligence --focus routes`",
            "link/docmap/stale-root/rule-context/remainder drift",
        ):
            self.assertIn(expected, readme)
        self.assertIn("check --focus validation|links|context|hygiene|grain", docs_readme)
        self.assertIn("archived-plan calibration samples", docs_readme)
        self.assertIn("deeper section-size details remain advanced diagnostics", docs_readme)
        self.assertIn("read-only route metadata warnings", docs_readme)
        for expected in (
            "primary instruction-surface size warnings",
            "product docs and stable specs remain covered by advanced `context-budget` detail",
            "`doctor` stays summary-oriented",
            "Grain diagnostics inspect active-plan frontmatter",
        ):
            self.assertIn(expected, cli_spec)

    def test_cli_spec_classifies_command_surface(self) -> None:
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")
        for expected in (
            "## Command Classification",
            "| Public operator utility | `init`, `check`, `migrate`, `repair`, `detach` |",
            "| Hidden compatibility diagnostics | `status`, `validate`, `audit-links`, `context-budget`, `doctor` |",
            "| Advanced and recovery diagnostics | `suggest --intent`, `intelligence`, `manifest --inspect`, `projection`, `snapshot`, `adapter`, `preflight` |",
            "| Closeout and reporting | `evidence`, `evidence --record --dry-run`, `evidence --record --apply`, `closeout` |",
            "| Closeout/state writeback | `writeback --dry-run`, `writeback --apply` |",
            "| Incubation write rail | `incubate --dry-run`, `incubate --apply` |",
            "| Plan synthesis write rail | `plan --dry-run`, `plan --apply` |",
            "| Memory lifecycle hygiene rail | `memory-hygiene --dry-run`, `memory-hygiene --apply` |",
            "| Roadmap item write rail | `roadmap --dry-run`, `roadmap --apply` |",
            "| Dev and release verification | `bootstrap --package-smoke`, `bootstrap --inspect` |",
            "| Deprecation candidates kept for compatibility | `tasks --inspect`, `semantic --inspect`, `semantic --evaluate`, `bootstrap --inspect` |",
            "`check --deep` is read-only",
            "optional `project/roadmap.md` sequencing",
            "`check --focus validation|links|context|hygiene|grain` is read-only",
            "`migrate --dry-run` is no-write",
            "`migrate --apply` is the explicit legacy-to-neutral workflow manifest migration rail",
            "`suggest --intent \"<operator-action>\"`",
            "command intent suggestions are advisory",
            "manual external prompt drafting outside MyLittleHarness",
            "research-distill`",
            "manifest --inspect --json",
            "role_manifest",
            "required outputs, context/output packet requirements, gate classes, and human gates",
            "product-source target artifact references",
            "product-target-artifact",
            "report-only grain diagnostics",
            "`intelligence --focus routes` renders compact source inventory plus `Boundary` and `Lifecycle Routes` only",
            "auto-compaction posture",
            "post-writeback operating-memory compaction",
            "compact-only state-history compaction",
            "safe whole-state history compaction",
            "project/archive/reference/project-state-history-YYYY-MM-DD",
            "explicit ready-for-closeout `writeback --apply --phase-status complete`",
            "`--product-source-root <path>`",
            "`writeback --dry-run --compact-only`",
            "`incubate --dry-run --topic \"<topic>\" --note \"<note>\"`",
            "`incubate --apply --topic \"<topic>\" --note \"<note>\"`",
            "`--note-file <path>`",
            "`--note-file -`",
            "`--fix-candidate`",
            "`plan --dry-run --title \"<title>\" --objective \"<objective>\"`",
            "`plan --apply --title \"<title>\" --objective \"<objective>\"`",
            "--roadmap-item <id>",
            "--execution-slice",
            "--slice-member",
            "primary_roadmap_item",
            "covered_roadmap_items",
            "target_artifacts",
            "closeout_boundary",
            "plan-synthesis-bundle-rationale",
            "plan-synthesis-target-artifact-pressure",
            "plan-docs-write-scope-impact",
            "Plan Synthesis Notes",
            "target_artifact_pressure",
            "phase_pressure",
            "execution-policy posture",
            "auto_continue",
            "stop_conditions",
            "current-phase-only execution",
            "memory-hygiene --dry-run --source <rel>",
            "`memory-hygiene --apply`",
            "memory-hygiene --dry-run --scan",
            "`--archive-covered --entry-coverage <entry-id: status destination>`",
            "roadmap --dry-run --action add --item-id <id>",
            "`roadmap --apply`",
            "intake --dry-run",
            "`intake --apply`",
            "reciprocal source-incubation",
            "non-owning `related_incubation`",
            "relationship frontmatter block recovery",
            "coverage-aware incubation auto-archive",
            "Route metadata diagnostics are read-only validation",
            "route-specific allowed status hints",
            "shared target-artifact ownership resolver",
            "product-source-artifact",
            "valid parsed Entry Coverage ids",
            "route-metadata-frontmatter",
            "cold memory routes",
            "archived plans under `project/archive/plans/*.md`",
            "archived reference material under `project/archive/reference/**/*.md`",
        ):
            self.assertIn(expected, cli_spec)

        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("cold archived-plan/reference retrieval", pyproject["project"]["description"])
        self.assertIn("route metadata", pyproject["project"]["description"])
        self.assertIn("roadmap routes", pyproject["project"]["description"])
        self.assertIn("hidden intake route advisor", pyproject["project"]["description"])
        self.assertIn("hidden incubate same-topic note rail", pyproject["project"]["description"])
        self.assertIn("hidden deterministic plan synthesis rail", pyproject["project"]["description"])
        self.assertIn("roadmap slice frontmatter", pyproject["project"]["description"])
        self.assertIn("bounded plan-synthesis rationale", pyproject["project"]["description"])
        self.assertIn("target-artifact pressure reporting", pyproject["project"]["description"])
        self.assertIn("docs write-scope impact reporting", pyproject["project"]["description"])
        self.assertIn("current-phase-only execution metadata", pyproject["project"]["description"])
        self.assertIn("explicit ready-for-closeout boundary", pyproject["project"]["description"])
        self.assertIn("explicit auto_continue stop-condition diagnostics", pyproject["project"]["description"])
        self.assertIn("hidden memory lifecycle hygiene rail", pyproject["project"]["description"])
        self.assertIn("hidden bounded roadmap item mutation rail", pyproject["project"]["description"])
        self.assertIn("advisory execution-slice fields", pyproject["project"]["description"])
        self.assertIn("relationship hygiene scan diagnostics", pyproject["project"]["description"])
        self.assertIn("product-target artifact status", pyproject["project"]["description"])
        self.assertIn("coverage-aware incubation auto-archive", pyproject["project"]["description"])
        self.assertIn("text audit and entry coverage suggestions", pyproject["project"]["description"])
        self.assertIn("reciprocal source-incubation metadata", pyproject["project"]["description"])
        self.assertIn("non-owning source-incubation reuse provenance", pyproject["project"]["description"])
        self.assertIn("relationship frontmatter block recovery", pyproject["project"]["description"])
        self.assertIn("hidden plan/writeback roadmap relationship sync", pyproject["project"]["description"])
        self.assertIn("project-state closeout authority fallback", pyproject["project"]["description"])
        self.assertIn("product_source_root writeback", pyproject["project"]["description"])
        self.assertIn("fix-candidate tagging", pyproject["project"]["description"])
        self.assertIn("archive-covered Entry Coverage transactions", pyproject["project"]["description"])
        self.assertIn("plan-identity carry/replace guardrail", pyproject["project"]["description"])
        self.assertIn("post-writeback and compact-only whole-state compaction", pyproject["project"]["description"])
        self.assertIn("optional proof/evidence and agent run evidence route records", pyproject["project"]["description"])
        self.assertIn("report-only grain diagnostics and archived-plan calibration samples", pyproject["project"]["description"])
        self.assertIn("hidden deterministic command intent suggestions", pyproject["project"]["description"])

    def test_phase_execution_policy_docs_are_current_phase_only(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")
        authority = (ROOT / "docs/specs/authority-and-memory.md").read_text(encoding="utf-8")
        metadata = (ROOT / "docs/specs/metadata-routing-and-evidence.md").read_text(encoding="utf-8")
        plan_synthesis = (ROOT / "project/specs/workflow/workflow-plan-synthesis-spec.md").read_text(encoding="utf-8")
        rollout = (ROOT / "project/specs/workflow/workflow-rollout-slices-spec.md").read_text(encoding="utf-8")
        closeout = (ROOT / "project/specs/workflow/workflow-verification-and-closeout-spec.md").read_text(encoding="utf-8")
        plan_synthesis_template = (ROOT / "src/mylittleharness/templates/workflow/workflow-plan-synthesis-spec.md").read_text(encoding="utf-8")
        rollout_template = (ROOT / "src/mylittleharness/templates/workflow/workflow-rollout-slices-spec.md").read_text(encoding="utf-8")
        closeout_template = (ROOT / "src/mylittleharness/templates/workflow/workflow-verification-and-closeout-spec.md").read_text(encoding="utf-8")

        for doc in (readme, docs_readme, authority, metadata, plan_synthesis, rollout, plan_synthesis_template, rollout_template):
            self.assertIn("current-phase-only", doc)
            self.assertIn("auto_continue", doc)
            self.assertIn("stop_conditions", doc)
        for doc in (docs_readme, metadata, closeout):
            self.assertIn("stop-condition", doc)
            self.assertIn("verification", doc)
            self.assertIn("write scope", doc)
            self.assertIn("closeout", doc)
        self.assertIn("active-plan-auto-continue", readme)
        self.assertIn("writeback-phase-execution-boundary", metadata)
        self.assertIn("writeback --apply --active-phase <next-phase> --phase-status pending", metadata)
        self.assertIn("writeback --active-phase <next-phase> --phase-status pending", closeout_template)
        self.assertIn("verification success alone does not authorize the next phase", rollout_template)
        self.assertIn("Closeout preparation remains an explicit boundary", closeout_template)
        self.assertIn("repo-visible verification command discovery", docs_readme)
        self.assertIn("plan-verification-gate-unresolved", cli_spec)
        self.assertIn("active-plan-verification-gate-toolchain-mismatch", metadata)
        self.assertIn("UNRESOLVED", plan_synthesis_template)
        self.assertIn("toolchain-mismatched verification gates", closeout_template)
        self.assertIn("Phase Outline", plan_synthesis_template)
        self.assertIn("one-shot rationale", plan_synthesis_template)
        self.assertIn("under-decomposed", rollout_template)

    def test_operating_root_agents_template_stays_compact_while_routing_is_cli_visible(self) -> None:
        template = (ROOT / "src/mylittleharness/templates/operating-root/AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        authority = (ROOT / "docs/specs/authority-and-memory.md").read_text(encoding="utf-8")
        artifact_model = (ROOT / "project/specs/workflow/workflow-artifact-model-spec.md").read_text(encoding="utf-8")
        capability_roadmap = (ROOT / "project/specs/workflow/workflow-capability-roadmap-spec.md").read_text(encoding="utf-8")

        self.assertLessEqual(len(template.splitlines()), 20)
        self.assertIn("Use MLH lifecycle routes instead of ad hoc memory pockets", template)
        self.assertIn("meta-feedback capture is opt-in, not a default start-pass requirement", template)
        self.assertNotIn("agent-operability micro-friction", template)
        self.assertNotIn("meta-feedback", readme)
        self.assertNotIn("MYLITTLEHARNESS_META_FEEDBACK_ROOT", readme)
        self.assertNotIn("future-optional", template)
        for expected in (
            "`status`, `check`, and `intelligence --focus routes`",
            "without growing `AGENTS.md` into a dense manual",
            "roadmap",
            "decision/do-not-revisit records",
            "ADR records",
            "optional `project/verification/*.md` proof/evidence records",
            "Product-source fixtures must not present that table as live memory",
            "Read-only route metadata validation is also live-root-only",
        ):
            self.assertIn(expected, authority)
        self.assertIn("CLI route-table output is a compact discovery view over this artifact model", artifact_model)
        self.assertIn("durable proof/evidence records are closeout assembly inputs only", artifact_model)
        self.assertIn("optional accepted-work sequencing lives at `project/roadmap.md`", template)
        self.assertIn("optional sequencing authority for accepted work", capability_roadmap)
        self.assertIn("accepted relationship vocabulary", capability_roadmap)
        self.assertIn("`related_incubation`", capability_roadmap)
        self.assertIn("relationship frontmatter block recovery", capability_roadmap)
        self.assertIn("project/archive/reference/incubation/**", capability_roadmap)
        self.assertIn("Coverage-aware incubation auto-archive is allowed only", capability_roadmap)
        self.assertIn("Entry Coverage", capability_roadmap)
        self.assertIn("Route output is advisory only", readme)
        self.assertIn("optional `project/verification/*.md` proof/evidence records", readme)
        self.assertIn("decision, ADR, and roadmap routes", (ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_route_metadata_diagnostics_docs_are_read_only(self) -> None:
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        metadata = (ROOT / "docs/specs/metadata-routing-and-evidence.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")

        for doc in (docs_readme, metadata, cli_spec):
            self.assertIn("route-metadata", doc)
        self.assertIn("implemented read-only route metadata diagnostic path", metadata)
        self.assertIn("does not repair metadata", metadata)
        self.assertIn("relationship frontmatter block recovery happens only", metadata)
        self.assertIn("intentionally excluded from repair proposals", cli_spec)

    def test_spec_lifecycle_posture_docs_keep_reconcile_read_only(self) -> None:
        metadata = (ROOT / "docs/specs/metadata-routing-and-evidence.md").read_text(encoding="utf-8")
        authority = (ROOT / "docs/specs/authority-and-memory.md").read_text(encoding="utf-8")
        artifact_model = (ROOT / "project/specs/workflow/workflow-artifact-model-spec.md").read_text(
            encoding="utf-8"
        )
        capability = (ROOT / "project/specs/workflow/workflow-capability-roadmap-spec.md").read_text(
            encoding="utf-8"
        )

        for doc in (metadata, authority, artifact_model, capability):
            self.assertIn("spec_status", doc)
            self.assertIn("implementation_posture", doc)
            self.assertIn("target-only", doc)
        for expected in (
            "`docs_decision` stays a closeout-local decision",
            "spec-posture-missing",
            "spec-synced-without-verification",
            "spec-target-only-has-implementation-evidence",
            "spec-drift-detected-without-carry-forward",
            "spec-superseded-without-target",
            "must not be deleted merely because code has not caught up",
        ):
            self.assertIn(expected, metadata)
        self.assertIn("Spec posture findings", authority)
        self.assertIn("`target-only` preserves an accepted target contract", artifact_model)
        self.assertIn("cannot remove target specs, force implementation sync, approve deletion, or change roadmap status", capability)

    def test_verification_ledger_rotation_docs_are_bounded(self) -> None:
        metadata = (ROOT / "docs/specs/metadata-routing-and-evidence.md").read_text(encoding="utf-8")
        for expected in (
            "memory-hygiene --dry-run|--apply --rotate-ledger",
            "project/archive/reference/verification/",
            "full sha256 `--source-hash`",
            "fresh active continuity ledger",
            "archived evidence remains historical rather than active continuation state",
            "cannot approve closeout, roadmap promotion, unrelated archive cleanup, staging, commit, push, rollback, dependency adoption, or next-plan opening",
        ):
            self.assertIn(expected, metadata)

    def test_memory_hygiene_batch_apply_token_docs_are_bounded(self) -> None:
        metadata = (ROOT / "docs/specs/metadata-routing-and-evidence.md").read_text(encoding="utf-8")
        for expected in (
            "memory-hygiene --apply --scan --proposal-token <mhb-token>",
            "source hashes, archive targets, exact link-repair file hashes",
            "refuses before writes unless the token matches the exact current candidate set",
            "cannot infer promotion meaning, perform fuzzy link repair, approve archive decisions",
        ):
            self.assertIn(expected, metadata)


if __name__ == "__main__":
    unittest.main()
