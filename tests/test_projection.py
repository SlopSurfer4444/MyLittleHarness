from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.inventory import EXPECTED_SPEC_NAMES, load_inventory
from mylittleharness.projection import build_projection
from tests.test_cli import make_operating_root, make_root, write_sample_roadmap


class ProjectionTests(unittest.TestCase):
    def test_projection_rebuild_is_deterministic_and_hashes_readable_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            first = build_projection(load_inventory(root))
            second = build_projection(load_inventory(root))

            self.assertEqual(first, second)
            self.assertEqual(first.summary.rebuild_status, "rebuilt-from-inventory")
            self.assertEqual(first.summary.storage_boundary, "none")
            self.assertGreater(first.summary.source_count, 0)
            self.assertEqual(first.summary.readable_source_count, first.summary.hashed_source_count)

            state = first.source_by_path["project/project-state.md"]
            self.assertEqual(len(state.content_hash or ""), 64)
            self.assertGreater(state.line_count, 0)
            self.assertGreater(state.link_count, 0)

    def test_projection_records_links_and_fan_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            projection = build_projection(load_inventory(root))

            docmap_links = [record for record in projection.links if record.target == ".agents/docmap.yaml"]
            self.assertEqual(2, len(docmap_links))
            self.assertTrue(all(record.status == "present" for record in docmap_links))

            docmap_fan_in = [record for record in projection.fan_in if record.target == ".agents/docmap.yaml"]
            self.assertEqual(1, len(docmap_fan_in))
            self.assertEqual(2, docmap_fan_in[0].inbound_count)
            self.assertEqual(("AGENTS.md", "README.md"), docmap_fan_in[0].sources)

    def test_projection_marks_absolute_and_traversal_local_links_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp) / "root", active=False, mirrors=False)
            outside = Path(tmp) / "outside.md"
            outside.write_text("# Outside\n", encoding="utf-8")
            outside_link = str(outside).replace("\\", "/")
            (root / "README.md").write_text(
                "# Sample\n\n"
                f"[absolute]({outside_link})\n"
                "[traversal](../outside.md)\n",
                encoding="utf-8",
            )

            projection = build_projection(load_inventory(root))

            statuses = {
                record.target: record.status
                for record in projection.links
                if record.source == "README.md" and record.target in {outside_link, "../outside.md"}
            }
            self.assertEqual({outside_link: "unsafe", "../outside.md": "unsafe"}, statuses)

            fan_in_statuses = {
                record.target: record.status
                for record in projection.fan_in
                if record.target in {outside_link, "../outside.md"}
            }
            self.assertEqual({outside_link: "unsafe", "../outside.md": "unsafe"}, fan_in_statuses)

    def test_projection_records_lifecycle_relationship_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=False)
            write_sample_roadmap(root)
            projection = build_projection(load_inventory(root))

            node_ids = {node.id for node in projection.relationship_nodes}
            self.assertIn("project/roadmap.md", node_ids)
            self.assertIn("project/roadmap.md#minimal-roadmap-mutation-rail", node_ids)

            dependency_edges = [
                edge
                for edge in projection.relationship_edges
                if edge.source == "project/roadmap.md#minimal-roadmap-mutation-rail"
                and edge.relation == "dependencies"
            ]
            self.assertEqual(1, len(dependency_edges))
            self.assertEqual("project/roadmap.md#roadmap-operationalization-rail", dependency_edges[0].target)
            self.assertEqual("present", dependency_edges[0].status)
            slice_member_edges = [
                edge
                for edge in projection.relationship_edges
                if edge.source == "project/roadmap.md#roadmap-operationalization-rail"
                and edge.relation == "slice_members"
            ]
            self.assertEqual(
                {"project/roadmap.md#roadmap-operationalization-rail", "project/roadmap.md#minimal-roadmap-mutation-rail"},
                {edge.target for edge in slice_member_edges},
            )
            self.assertGreater(projection.summary.relationship_node_count, 0)
            self.assertGreater(projection.summary.relationship_edge_count, 0)

    def test_projection_classifies_live_root_product_target_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            (root / "project/implementation-plan.md").write_text(
                "---\n"
                'plan_id: "cross-root"\n'
                "target_artifacts:\n"
                '  - "src/mylittleharness/checks.py"\n'
                '  - "tests/test_cli.py"\n'
                "---\n"
                "# Plan\n\n"
                "## Slice Contract\n\n"
                "- target_artifacts: `src/mylittleharness/projection.py`\n",
                encoding="utf-8",
            )
            (root / "project/roadmap.md").write_text(
                "# Roadmap\n\n"
                "## Items\n\n"
                "### Product Target Diagnostics\n\n"
                "- `id`: `product-target-diagnostics`\n"
                "- `status`: `accepted`\n"
                "- `target_artifacts`: `[\"src/mylittleharness/planning.py\", \"README.md\"]`\n",
                encoding="utf-8",
            )

            projection = build_projection(load_inventory(root))
            product_links = {
                record.target: record.status
                for record in projection.links
                if record.target
                in {
                    "src/mylittleharness/checks.py",
                    "tests/test_cli.py",
                    "src/mylittleharness/projection.py",
                    "src/mylittleharness/planning.py",
                    "README.md",
                }
            }
            self.assertEqual(
                {
                    "src/mylittleharness/checks.py": "product-target",
                    "tests/test_cli.py": "product-target",
                    "src/mylittleharness/projection.py": "product-target",
                    "src/mylittleharness/planning.py": "product-target",
                    "README.md": "product-target",
                },
                product_links,
            )

            target_edges = [
                edge
                for edge in projection.relationship_edges
                if edge.relation == "target_artifacts"
                and edge.target
                in {
                    "src/mylittleharness/checks.py",
                    "tests/test_cli.py",
                    "src/mylittleharness/planning.py",
                    "README.md",
                }
            ]
            self.assertTrue(target_edges)
            self.assertEqual({"product-target"}, {edge.status for edge in target_edges})

    def test_projection_classifies_research_diagnostic_links_as_historical_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            (root / "project/research/archive-audit.md").write_text(
                "# Archive Audit\n\n"
                "## Missing Roadmap-Referenced Archive Files\n\n"
                "- `project/archive/plans/old-missing-plan.md`\n",
                encoding="utf-8",
            )
            (root / "project/research/parallel-claims.md").write_text(
                "# Parallel Claims\n\n"
                "Example payload: {'agent': 'worker-2', 'claim': 'src/auth/login.ts', 'expires': 'timestamp'}.\n",
                encoding="utf-8",
            )
            (root / "project/research/context-tiers.md").write_text(
                "# Context Tiers\n\n"
                "The older `project/research/older-partial-input.md` remains partial input only; "
                "it is not the gate-closing source for this slice.\n",
                encoding="utf-8",
            )

            projection = build_projection(load_inventory(root))
            link_statuses = {
                record.target: record.status
                for record in projection.links
                if record.target
                in {
                    "project/archive/plans/old-missing-plan.md",
                    "src/auth/login.ts",
                    "project/research/older-partial-input.md",
                }
            }

            self.assertEqual(
                {
                    "project/archive/plans/old-missing-plan.md": "historical-context",
                    "src/auth/login.ts": "historical-context",
                    "project/research/older-partial-input.md": "historical-context",
                },
                link_statuses,
            )

    def test_projection_includes_cold_memory_routes_without_start_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            archived_plan = root / "project/archive/plans/2026-05-03-cold-plan.md"
            archived_plan.write_text(
                "---\n"
                'status: "complete"\n'
                'related_research: "project/archive/reference/research/2026-05-03-cold-research.md"\n'
                'related_decision: "project/archive/reference/decisions/2026-05-03-cold-decision.md"\n'
                'related_adr: "project/archive/reference/adrs/0001-cold-adr.md"\n'
                'related_verification: "project/archive/reference/verification/2026-05-03-cold-proof.md"\n'
                "---\n"
                "# Cold Plan\n\n"
                "ColdMemoryNeedle plan evidence.\n",
                encoding="utf-8",
            )
            for rel_path, title in (
                ("project/archive/reference/research/2026-05-03-cold-research.md", "Cold Research"),
                ("project/archive/reference/decisions/2026-05-03-cold-decision.md", "Cold Decision"),
                ("project/archive/reference/adrs/0001-cold-adr.md", "Cold ADR"),
                ("project/archive/reference/verification/2026-05-03-cold-proof.md", "Cold Proof"),
            ):
                path = root / rel_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"# {title}\n\nColdMemoryNeedle {title.lower()}.\n", encoding="utf-8")

            inventory = load_inventory(root)
            self.assertNotIn("project/archive/plans/2026-05-03-cold-plan.md", inventory.surface_by_rel)

            projection = build_projection(inventory)
            for rel_path in (
                "project/archive/plans/2026-05-03-cold-plan.md",
                "project/archive/reference/research/2026-05-03-cold-research.md",
                "project/archive/reference/decisions/2026-05-03-cold-decision.md",
                "project/archive/reference/adrs/0001-cold-adr.md",
                "project/archive/reference/verification/2026-05-03-cold-proof.md",
            ):
                self.assertIn(rel_path, projection.source_by_path)
                self.assertEqual(len(projection.source_by_path[rel_path].content_hash or ""), 64)

            archive_edges = [
                edge
                for edge in projection.relationship_edges
                if edge.source == "project/archive/plans/2026-05-03-cold-plan.md"
            ]
            self.assertEqual({"present"}, {edge.status for edge in archive_edges})
            self.assertIn("project/archive/reference/verification/2026-05-03-cold-proof.md", {edge.target for edge in archive_edges})

    def test_projection_reports_missing_and_unreadable_source_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            missing = root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]
            missing.unlink()
            unreadable = root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[1]
            unreadable.write_bytes(b"# Spec\n\xff\n")

            projection = build_projection(load_inventory(root))
            missing_record = projection.source_by_path[f"project/specs/workflow/{EXPECTED_SPEC_NAMES[0]}"]
            unreadable_record = projection.source_by_path[f"project/specs/workflow/{EXPECTED_SPEC_NAMES[1]}"]

            self.assertFalse(missing_record.present)
            self.assertEqual(1, projection.summary.missing_required_count)
            self.assertEqual("decoded with replacement characters", unreadable_record.read_error)
            self.assertIsNone(unreadable_record.content_hash)


if __name__ == "__main__":
    unittest.main()
