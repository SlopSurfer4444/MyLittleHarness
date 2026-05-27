from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.checks import (
    check_drift_findings,
    audit_link_findings,
    context_budget_findings,
    product_hygiene_findings,
    rule_context_findings,
    status_findings,
    validation_findings,
)
from mylittleharness.inventory import EXPECTED_SPEC_NAMES, load_inventory


class InventoryTests(unittest.TestCase):
    def test_missing_optional_surfaces_do_not_create_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            inventory = load_inventory(root)
            errors = [finding for finding in validation_findings(inventory) if finding.severity == "error"]
            self.assertEqual(errors, [])

    def test_inventory_classifies_present_memory_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "project/specs/workflow/workflow-memory-routing-spec.md").write_text("# Memory Routing\n", encoding="utf-8")
            (root / "project/plan-incubation").mkdir()
            (root / "project/plan-incubation/memory-routing.md").write_text("# Incubation\n", encoding="utf-8")
            (root / "project/research").mkdir()
            (root / "project/research/memory-routing.md").write_text("# Research\n", encoding="utf-8")
            (root / "project/roadmap.md").write_text("# Roadmap\n", encoding="utf-8")

            inventory = load_inventory(root)

            self.assertEqual("operating-guardrails", inventory.surface_by_rel["AGENTS.md"].memory_route)
            self.assertEqual("state", inventory.surface_by_rel["project/project-state.md"].memory_route)
            self.assertEqual("roadmap", inventory.surface_by_rel["project/roadmap.md"].memory_route)
            self.assertEqual("stable-specs", inventory.surface_by_rel["project/specs/workflow/workflow-memory-routing-spec.md"].memory_route)
            self.assertEqual("incubation", inventory.surface_by_rel["project/plan-incubation/memory-routing.md"].memory_route)
            self.assertEqual("research", inventory.surface_by_rel["project/research/memory-routing.md"].memory_route)

    def test_inventory_discovers_decision_adr_and_verification_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_route_metadata_live_root(Path(tmp))
            (root / "project/decisions").mkdir()
            (root / "project/adrs").mkdir()
            (root / "project/verification").mkdir()
            (root / "project/decisions/no-parallel-memory.md").write_text('---\nstatus: "accepted"\n---\n# Decision\n', encoding="utf-8")
            (root / "project/adrs/0001-routing.md").write_text('---\nstatus: "accepted"\n---\n# ADR\n', encoding="utf-8")
            (root / "project/verification/route-metadata.md").write_text('---\nstatus: "passed"\n---\n# Verification\n', encoding="utf-8")

            inventory = load_inventory(root)

            self.assertEqual("decisions", inventory.surface_by_rel["project/decisions/no-parallel-memory.md"].memory_route)
            self.assertEqual("adrs", inventory.surface_by_rel["project/adrs/0001-routing.md"].memory_route)
            self.assertEqual("verification", inventory.surface_by_rel["project/verification/route-metadata.md"].memory_route)

    def test_roadmap_route_metadata_validation_accepts_route_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_route_metadata_live_root(Path(tmp))
            (root / "project/plan-incubation").mkdir()
            (root / "project/archive/plans").mkdir(parents=True)
            (root / "project/decisions").mkdir()
            (root / "project/verification").mkdir()
            (root / "project/archive/plans/2026-05-02-old-plan.md").write_text("# Old Plan\n", encoding="utf-8")
            (root / "project/verification/proof.md").write_text(
                '---\nstatus: "passed"\n---\n# Proof\n',
                encoding="utf-8",
            )
            (root / "project/plan-incubation/roadmap.md").write_text(
                '---\nstatus: "incubating"\npromoted_to: "project/roadmap.md"\n---\n# Incubation\n',
                encoding="utf-8",
            )
            (root / "project/roadmap.md").write_text(
                "---\n"
                'status: "deferred"\n'
                'source_incubation: "project/plan-incubation/roadmap.md"\n'
                'related_roadmap: "project/roadmap.md"\n'
                'source_roadmap: "project/roadmap.md"\n'
                'archived_plan: "project/archive/plans/2026-05-02-old-plan.md"\n'
                'related_verification: "project/verification/proof.md"\n'
                "---\n"
                "# Roadmap\n",
                encoding="utf-8",
            )
            (root / "project/decisions/current.md").write_text('---\nstatus: "accepted"\n---\n# Current\n', encoding="utf-8")
            (root / "project/decisions/bad-roadmap-link.md").write_text(
                '---\nstatus: "accepted"\nrelated_roadmap: "project/decisions/current.md"\n---\n# Bad\n',
                encoding="utf-8",
            )

            inventory = load_inventory(root)
            warnings = [finding for finding in validation_findings(inventory) if finding.code.startswith("route-metadata-")]

            self.assertEqual("roadmap", inventory.surface_by_rel["project/roadmap.md"].memory_route)
            self.assertFalse(
                any(
                    finding.source == "project/roadmap.md"
                    and finding.code in {"route-metadata-status", "route-metadata-destination", "route-metadata-missing-target"}
                    for finding in warnings
                )
            )
            self.assertFalse(
                any(
                    finding.source == "project/plan-incubation/roadmap.md"
                    and finding.code == "route-metadata-destination"
                    for finding in warnings
                )
            )
            self.assertTrue(
                any(
                    finding.source == "project/decisions/bad-roadmap-link.md"
                    and finding.code == "route-metadata-destination"
                    and "related_roadmap must point to a roadmap route" in finding.message
                    for finding in warnings
                )
            )

    def test_route_metadata_validation_reports_advisory_warnings_for_live_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_route_metadata_live_root(Path(tmp))
            (root / "project/research").mkdir()
            (root / "project/plan-incubation").mkdir()
            (root / "project/adrs").mkdir()
            (root / "project/decisions").mkdir()
            (root / "project/archive/reference/research").mkdir(parents=True)
            (root / "project/archive/reference/research/raw.md").write_text("# Archived Raw\n", encoding="utf-8")
            (root / "project/plan-incubation/idea.md").write_text(
                '---\nstatus: "incubating"\narchived_to: "project/archive/reference/research/raw.md"\n---\n# Idea\n',
                encoding="utf-8",
            )
            (root / "project/research/old.md").write_text(
                '---\nstatus: "archived"\narchived_to: "project/archive/reference/research/raw.md"\n---\n# Old\n',
                encoding="utf-8",
            )
            (root / "project/research/label.md").write_text(
                '---\nstatus: "research-ready"\nsupersedes: "2026-04-30 snapshot in this file"\n---\n# Label\n',
                encoding="utf-8",
            )
            (root / "project/research/bad.md").write_text(
                "---\n"
                'status: "teleported"\n'
                'promoted_to: "project/archive/reference/research/raw.md"\n'
                'archived_to: "project/research/archive.md"\n'
                'related_research: "../outside.md"\n'
                'source_incubation: ["project/plan-incubation/missing.md"]\n'
                "---\n"
                "# Bad\n",
                encoding="utf-8",
            )
            (root / "project/decisions/current.md").write_text(
                '---\nstatus: "accepted"\nrelated_research: "project/research/old.md"\n---\n# Current\n',
                encoding="utf-8",
            )
            (root / "project/specs/workflow/workflow-memory-routing-spec.md").write_text(
                '---\nstatus: "accepted"\nsource_incubation: "project/plan-incubation/idea.md"\n---\n# Spec\n',
                encoding="utf-8",
            )
            (root / "project/decisions/malformed.md").write_text(
                "---\nstatus:\n  nested: no\n---\n# Malformed\n",
                encoding="utf-8",
            )
            (root / "project/adrs/bad.md").write_text(
                '---\nstatus: "accepted"\nrelated_adr: "project/decisions/current.md"\n---\n# ADR\n',
                encoding="utf-8",
            )

            inventory = load_inventory(root)
            warnings = [finding for finding in validation_findings(inventory) if finding.code.startswith("route-metadata-")]
            codes = [finding.code for finding in warnings]

            self.assertIn("route-metadata-status", codes)
            self.assertIn("route-metadata-destination", codes)
            self.assertIn("route-metadata-path", codes)
            self.assertIn("route-metadata-missing-target", codes)
            self.assertIn("route-metadata-stale-reference", codes)
            self.assertIn("route-metadata-frontmatter", codes)
            self.assertIn("route-metadata-authority", codes)
            self.assertTrue(
                any(
                    finding.source == "project/adrs/bad.md"
                    and finding.code == "route-metadata-destination"
                    and "related_adr must point to an ADR route" in finding.message
                    for finding in warnings
                )
            )
            self.assertFalse(
                any(
                    finding.source == "project/research/label.md"
                    and finding.code in {"route-metadata-missing-target", "route-metadata-destination"}
                    for finding in warnings
                )
            )
            self.assertFalse(
                any(
                    finding.source == "project/specs/workflow/workflow-memory-routing-spec.md"
                    and finding.code == "route-metadata-stale-reference"
                    for finding in warnings
                )
            )
            self.assertTrue(all(finding.severity in {"warn", "info"} for finding in warnings))

    def test_route_metadata_validation_is_live_root_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "project/research").mkdir()
            (root / "project/research/bad.md").write_text(
                '---\nstatus: "teleported"\narchived_to: "../outside.md"\n---\n# Bad\n',
                encoding="utf-8",
            )

            inventory = load_inventory(root)
            codes = [finding.code for finding in validation_findings(inventory)]

            self.assertNotIn("route-metadata-status", codes)
            self.assertNotIn("route-metadata-path", codes)

    def test_status_reports_product_root_posture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            inventory = load_inventory(root)
            codes = [finding.code for finding in status_findings(inventory)]
            for expected in (
                "product-name",
                "target-root-role",
                "fixture-status",
                "operating-root",
                "product-root",
                "fallback-root",
            ):
                self.assertIn(expected, codes)

    def test_product_posture_reports_wrong_product_name_and_root_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                f'---\nproject: "workflow-core"\nroot_role: "operating-root"\nfixture_status: "live-workflow"\nworkflow: "workflow-core"\noperating_mode: "ad_hoc"\nplan_status: "none"\nactive_plan: ""\noperating_root: "{root}"\nproduct_source_root: "{root.parent / "Elsewhere"}"\nhistorical_fallback_root: "{root}"\n---\n# State\n',
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            errors = [finding.code for finding in validation_findings(inventory) if finding.severity == "error"]
            self.assertIn("product-posture-product-name", errors)
            self.assertIn("product-posture-root-role", errors)
            self.assertIn("product-posture-fixture-status", errors)
            self.assertIn("product-posture-product-root", errors)
            self.assertIn("product-posture-operating-root", errors)
            self.assertIn("product-posture-fallback-root", errors)

    def test_product_posture_rejects_active_plan_in_product_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            inventory = load_inventory(root)
            errors = [finding.code for finding in validation_findings(inventory) if finding.severity == "error"]
            self.assertIn("product-posture-active-plan", errors)

    def test_active_plan_is_required_when_state_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            (root / "project/implementation-plan.md").unlink()
            inventory = load_inventory(root)
            errors = [finding.code for finding in validation_findings(inventory) if finding.severity == "error"]
            self.assertIn("active-plan-missing", errors)

    def test_active_phase_fields_are_required_when_state_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                .replace('active_phase: "Phase 1"\n', "")
                .replace('phase_status: "in_progress"\n', ""),
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            warnings = [finding.code for finding in validation_findings(inventory) if finding.severity == "warn"]
            self.assertIn("active-phase-field", warnings)
            self.assertIn("phase-status-field", warnings)

    def test_complete_active_plan_warns_on_uncertain_docs_decision_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(state.read_text(encoding="utf-8").replace('phase_status: "in_progress"', 'phase_status: "complete"'), encoding="utf-8")
            (root / "project/implementation-plan.md").write_text(
                '---\ntitle: "Plan"\ndocs_decision: "uncertain"\n---\n# Plan\n\n- docs_decision: updated\n',
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            warnings = [finding.code for finding in validation_findings(inventory) if finding.severity == "warn"]
            self.assertIn("active-plan-docs-decision-uncertain", warnings)

    def test_complete_active_plan_warns_on_pending_phase_body_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                .replace('active_phase: "Phase 1"', 'active_phase: "phase-2-verify"')
                .replace('phase_status: "in_progress"', 'phase_status: "complete"'),
                encoding="utf-8",
            )
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Phase 1: Setup\n\n"
                "- id: `phase-1-setup`\n"
                "- status: `pending`\n\n"
                "## Phase 2: Verify\n\n"
                "- id: `phase-2-verify`\n"
                "- status: `in_progress`\n",
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            warnings = [finding.code for finding in validation_findings(inventory) if finding.severity == "warn"]
            self.assertIn("active-plan-phase-body-drift", warnings)

    def test_complete_closeout_active_plan_reports_ready_for_closeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8").replace('phase_status: "in_progress"', 'phase_status: "complete"')
                + "\n## MLH Closeout Writeback\n\n"
                "<!-- BEGIN mylittleharness-closeout-writeback v1 -->\n"
                "- active_plan: project/implementation-plan.md\n"
                "- docs_decision: updated\n"
                "- state_writeback: complete\n"
                "- verification: targeted suite passed\n"
                "- commit_decision: manual policy\n"
                "<!-- END mylittleharness-closeout-writeback v1 -->\n",
                encoding="utf-8",
            )
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Phase 1\n\n"
                "- status: `done`\n",
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            infos = [finding.code for finding in validation_findings(inventory) if finding.severity == "info"]
            self.assertIn("active-plan-ready-for-closeout", infos)

    def test_active_plan_warns_on_invalid_docs_decision_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            (root / "project/implementation-plan.md").write_text(
                '---\ntitle: "Plan"\ndocs_decision: "maybe"\n---\n# Plan\n',
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            warnings = [finding.code for finding in validation_findings(inventory) if finding.severity == "warn"]
            self.assertIn("active-plan-docs-decision-value", warnings)

    def test_generated_active_plan_shape_warns_when_expected_sections_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            (root / "project/implementation-plan.md").write_text(
                '---\nplan_id: "2026-05-01-generated"\nstatus: "in_progress"\ndocs_decision: "uncertain"\n---\n# Generated\n\n## Objective\n\nDo work.\n',
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            warnings = [finding.code for finding in validation_findings(inventory) if finding.severity == "warn"]
            self.assertIn("active-plan-generated-shape", warnings)

    def test_mirror_drift_is_reported_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True, mirrors=True)
            (root / "specs/workflow" / EXPECTED_SPEC_NAMES[0]).write_text("# drift\n", encoding="utf-8")
            inventory = load_inventory(root)
            errors = [finding.code for finding in validation_findings(inventory) if finding.severity == "error"]
            self.assertIn("mirror-drift", errors)

    def test_inactive_plan_route_is_not_required_in_docmap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            inventory = load_inventory(root)
            warnings = [finding.code for finding in audit_link_findings(inventory) if finding.severity == "warn"]
            self.assertNotIn("candidate-docmap-gap", warnings)

    def test_active_plan_route_is_required_in_docmap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            inventory = load_inventory(root)
            warnings = [finding.code for finding in audit_link_findings(inventory) if finding.severity == "warn"]
            self.assertIn("candidate-docmap-gap", warnings)

    def test_product_doc_links_resolve_relative_to_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "docs/architecture").mkdir(parents=True)
            (root / "docs/README.md").write_text("Read `architecture/product-architecture.md`.\n", encoding="utf-8")
            (root / "docs/architecture/product-architecture.md").write_text("# Product\n", encoding="utf-8")
            inventory = load_inventory(root)
            warnings = [
                finding
                for finding in audit_link_findings(inventory)
                if finding.severity == "warn" and finding.code in {"missing-link", "unresolved-link"}
            ]
            self.assertEqual(warnings, [])

    def test_product_root_relative_links_include_build_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "build_backend").mkdir()
            (root / "build_backend/mylittleharness_build.py").write_text("# backend\n", encoding="utf-8")
            (root / "docs/specs").mkdir(parents=True)
            (root / "docs/specs/package.md").write_text(
                "Package smoke requires `build_backend/mylittleharness_build.py`.\n",
                encoding="utf-8",
            )

            inventory = load_inventory(root)
            warnings = [
                finding
                for finding in audit_link_findings(inventory)
                if finding.severity == "warn" and "build_backend/mylittleharness_build.py" in finding.message
            ]

            self.assertEqual(warnings, [])

    def test_audit_links_ignores_known_text_only_slash_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "docs/specs").mkdir(parents=True)
            (root / "docs/specs/labels.md").write_text(
                "Log labels include `docs/API`, `docs/spec/package`, `docs/tests`, "
                "`tests/docs`, `tests/docs/components`, `tests/checks`, "
                "and `tests/product verification`.\n",
                encoding="utf-8",
            )

            inventory = load_inventory(root)
            rendered = "\n".join(finding.message for finding in audit_link_findings(inventory) if finding.severity == "warn")

            self.assertNotIn("docs/API", rendered)
            self.assertNotIn("docs/spec/package", rendered)
            self.assertNotIn("docs/tests", rendered)
            self.assertNotIn("tests/docs", rendered)
            self.assertNotIn("tests/docs/components", rendered)
            self.assertNotIn("tests/checks", rendered)
            self.assertNotIn("tests/product verification", rendered)

    def test_audit_links_reports_product_docmap_gaps_and_stale_root_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "docs").mkdir(parents=True)
            archive_root = root.parent / "legacy-root"
            (root / "docs/README.md").write_text(
                f"{archive_root} is current source.\n{root} is the operating root.\n",
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text("[project]\nname = \"mylittleharness\"\n", encoding="utf-8")
            (root / "src/mylittleharness").mkdir(parents=True)
            (root / "tests").mkdir()
            inventory = load_inventory(root)
            warnings = [finding.code for finding in audit_link_findings(inventory) if finding.severity == "warn"]
            self.assertIn("candidate-docmap-gap", warnings)
            self.assertIn("stale-fallback-root-reference", warnings)
            self.assertIn("stale-product-root-role", warnings)

    def test_audit_links_treats_product_source_lifecycle_route_examples_as_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "docs").mkdir(parents=True)
            (root / "docs/README.md").write_text(
                "See `project/roadmap.md`, `project/decisions/no-revisit.md`, "
                "`project/adrs/0001-routing.md`, and `project/verification/closeout.md` "
                "in serviced operating roots.\n",
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            findings = audit_link_findings(inventory)
            warnings = [
                finding
                for finding in findings
                if finding.severity == "warn" and finding.code in {"missing-link", "unresolved-link"}
            ]
            self.assertEqual(warnings, [])
            optional_messages = "\n".join(finding.message for finding in findings if finding.code == "optional-link-missing")
            self.assertIn("roadmap route examples belong in serviced live operating roots", optional_messages)
            self.assertIn("ADR route examples belong in serviced live operating roots", optional_messages)
            self.assertIn("decision route examples belong in serviced live operating roots", optional_messages)
            self.assertIn("verification route examples belong in serviced live operating roots", optional_messages)

    def test_context_budget_keeps_product_docs_and_specs_measurement_informational(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "docs/specs").mkdir(parents=True)
            (root / "docs/specs/large-product-doc.md").write_text("# Product Doc\n" + ("detail\n" * 600), encoding="utf-8")
            (root / "project/specs/workflow/workflow-artifact-model-spec.md").write_text(
                "# Stable Spec\n" + ("rule\n" * 600),
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            findings = context_budget_findings(inventory)
            warnings = [finding for finding in findings if finding.severity == "warn"]
            self.assertEqual(warnings, [])
            measured_sources = {finding.source for finding in findings if finding.code == "file-budget"}
            self.assertIn("docs/specs/large-product-doc.md", measured_sources)
            self.assertIn("project/specs/workflow/workflow-artifact-model-spec.md", measured_sources)

    def test_check_drift_reports_only_docmap_and_root_pointer_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "docs").mkdir(parents=True)
            archive_root = root.parent / "legacy-root"
            (root / "docs/README.md").write_text(
                f"{archive_root} is current source.\n"
                f"{root} is the operating root.\n"
                "`missing-local.md` is missing.\n",
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text("[project]\nname = \"mylittleharness\"\n", encoding="utf-8")
            (root / "src/mylittleharness").mkdir(parents=True)
            (root / "tests").mkdir()
            inventory = load_inventory(root)
            codes = [finding.code for finding in check_drift_findings(inventory)]
            self.assertIn("candidate-docmap-gap", codes)
            self.assertIn("stale-fallback-root-reference", codes)
            self.assertIn("stale-product-root-role", codes)
            self.assertNotIn("missing-link", codes)

    def test_check_drift_reports_remainder_contradiction_for_explicit_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                + "\n## Delivered\n\n- Completed `detach --apply` as marker-only disable.\n"
                + "\n## Future Backlog\n\n- Future contract still lists `detach --apply` as unimplemented.\n",
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            findings = check_drift_findings(inventory)
            warnings = [finding for finding in findings if finding.severity == "warn"]
            self.assertEqual(["remainder-drift"], [finding.code for finding in warnings])
            self.assertIn("project/project-state.md", warnings[0].source or "")

    def test_check_drift_allows_clean_remainder_with_distinct_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                + "\n## Delivered\n\n- Completed `detach --apply` as marker-only disable.\n"
                + "\n## Future Backlog\n\n- Future contract still lists `semantic --inspect` policy work.\n",
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            codes = [finding.code for finding in check_drift_findings(inventory)]
            self.assertIn("check-drift-ok", codes)
            self.assertNotIn("remainder-drift", codes)

    def test_check_drift_ignores_historical_release_remainder_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                + "\n## Delivered\n\n- Completed `closeout` Git evidence suggestions.\n"
                + "\n## Historical Release Notes\n\n- Future backlog in a prior release mentioned `closeout`.\n",
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            codes = [finding.code for finding in check_drift_findings(inventory)]
            self.assertIn("check-drift-ok", codes)
            self.assertNotIn("remainder-drift", codes)

    def test_check_drift_does_not_guess_ambiguous_prose_remainder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                + "\n## Delivered\n\n- Completed semantic provider policy design research.\n"
                + "\n## Future Backlog\n\n- Future semantic provider policy implementation remains open.\n",
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            codes = [finding.code for finding in check_drift_findings(inventory)]
            self.assertIn("check-drift-ok", codes)
            self.assertNotIn("remainder-drift", codes)

    def test_rule_context_reports_large_primary_instruction_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "AGENTS.md").write_text("# AGENTS\n" + ("Instruction line.\n" * 501), encoding="utf-8")
            inventory = load_inventory(root)
            findings = rule_context_findings(inventory)
            warnings = [finding for finding in findings if finding.severity == "warn"]
            self.assertEqual(["rule-context-surface-large"], [finding.code for finding in warnings])
            self.assertEqual("AGENTS.md", warnings[0].source)

    def test_check_drift_excludes_large_product_docs_and_stable_specs_from_rule_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "docs").mkdir()
            (root / "docs/large.md").write_text("# Large Doc\n" + ("Details.\n" * 501), encoding="utf-8")
            (root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]).write_text(
                "# Large Stable Spec\n" + ("Details.\n" * 501),
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            codes = [finding.code for finding in check_drift_findings(inventory)]
            self.assertIn("check-drift-ok", codes)
            self.assertNotIn("rule-context-surface-large", codes)

    def test_product_hygiene_allows_clean_product_fixture_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            inventory = load_inventory(root)
            findings = product_hygiene_findings(inventory)
            warning_codes = [finding.code for finding in findings if finding.severity == "warn"]
            self.assertEqual(warning_codes, [])
            self.assertIn("product-hygiene-ok", [finding.code for finding in findings])

    def test_product_hygiene_reports_operational_surfaces_and_debris(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "project/roadmap.md").write_text("# Roadmap\n", encoding="utf-8")
            (root / "project/research").mkdir()
            (root / "project/research/raw.md").write_text("# Raw\n", encoding="utf-8")
            (root / "project/incubator").mkdir()
            (root / "project/incubator/idea.md").write_text("# Idea\n", encoding="utf-8")
            (root / "project/archive/plans").mkdir(parents=True)
            (root / "project/archive/plans/old.md").write_text("# Old\n", encoding="utf-8")
            (root / "project/adrs").mkdir()
            (root / "project/adrs/0001-runtime-layer.md").write_text("# ADR\n", encoding="utf-8")
            (root / "project/decisions").mkdir()
            (root / "project/decisions/no-revisit.md").write_text("# Decision\n", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "debug.log").write_text("debug\n", encoding="utf-8")
            (root / "local.sqlite").write_text("", encoding="utf-8")
            (root / "dist").mkdir()
            (root / "reports").mkdir()
            (root / "validation-artifacts").mkdir()
            (root / "generated-validation").mkdir()
            (root / "validation-report-2026-04-25.md").write_text("# Generated\n", encoding="utf-8")
            (root / "scratch.pyc").write_text("", encoding="utf-8")

            inventory = load_inventory(root)
            findings = [finding for finding in product_hygiene_findings(inventory) if finding.severity == "warn"]
            codes = [finding.code for finding in findings]
            sources = {finding.source for finding in findings}

            self.assertIn("forbidden-product-surface", codes)
            self.assertIn("product-debris", codes)
            self.assertIn("project/roadmap.md", sources)
            self.assertIn("project/research", sources)
            self.assertIn("project/incubator", sources)
            self.assertIn("project/archive", sources)
            self.assertIn("project/adrs", sources)
            self.assertIn("project/decisions", sources)
            self.assertIn("__pycache__", sources)
            self.assertIn("debug.log", sources)
            self.assertIn("local.sqlite", sources)
            self.assertIn("dist", sources)
            self.assertIn("reports", sources)
            self.assertIn("validation-artifacts", sources)
            self.assertIn("generated-validation", sources)
            self.assertIn("validation-report-2026-04-25.md", sources)
            self.assertIn("scratch.pyc", sources)


def make_minimal_root(root: Path, active: bool, docmap: bool, mirrors: bool = False) -> Path:
    (root / ".mylittleharness").mkdir(parents=True)
    (root / "project/specs/workflow").mkdir(parents=True)
    (root / ".mylittleharness/project-workflow.toml").write_text(
        'workflow = "workflow-core"\n\n[memory]\nstate_file = "project/project-state.md"\nplan_file = "project/implementation-plan.md"\n',
        encoding="utf-8",
    )
    plan_status = "active" if active else "none"
    active_plan = "project/implementation-plan.md" if active else ""
    phase_fields = 'active_phase: "Phase 1"\nphase_status: "in_progress"\n' if active else ""
    (root / "project/project-state.md").write_text(
        f'---\nproject: "MyLittleHarness"\nroot_role: "product-source"\nfixture_status: "product-compatibility-fixture"\nworkflow: "workflow-core"\noperating_mode: "plan"\nplan_status: "{plan_status}"\nactive_plan: "{active_plan}"\n{phase_fields}operating_root: "{root.parent / "operator-root"}"\nproduct_source_root: "{root}"\nhistorical_fallback_root: "{root.parent / "legacy-root"}"\n---\n# State\n\nNo active implementation plan is open in this product tree.\nThis product tree stores fixture metadata only.\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text("# README\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    if docmap:
        (root / ".agents").mkdir(parents=True)
        (root / ".agents/docmap.yaml").write_text(
            'version: 2\nrepo_summary:\n  product_docs_entrypoints:\n    - "README.md"\n    - "AGENTS.md"\n    - ".mylittleharness/project-workflow.toml"\n    - "project/project-state.md"\n    - "project/specs/workflow/"\n',
            encoding="utf-8",
        )
    if active:
        (root / "project/implementation-plan.md").write_text("# Plan\n", encoding="utf-8")
    for name in EXPECTED_SPEC_NAMES:
        content = f"# {name}\n"
        (root / "project/specs/workflow" / name).write_text(content, encoding="utf-8")
        if mirrors:
            (root / "specs/workflow").mkdir(parents=True, exist_ok=True)
            (root / "specs/workflow" / name).write_text(content, encoding="utf-8")
    return root


def make_route_metadata_live_root(root: Path) -> Path:
    make_minimal_root(root, active=False, docmap=True)
    (root / "project/project-state.md").write_text(
        '---\nproject: "Sample"\nworkflow: "workflow-core"\noperating_mode: "ad_hoc"\nplan_status: "none"\nactive_plan: ""\n---\n# State\n',
        encoding="utf-8",
    )
    return root


if __name__ == "__main__":
    unittest.main()
