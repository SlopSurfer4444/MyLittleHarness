from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.atomic_files import FileTransactionError
from mylittleharness.cli import main
from mylittleharness.projection_artifacts import (
    ARTIFACT_DIR_REL,
    ARTIFACT_DIRTY_MARKER_NAME,
    ARTIFACT_NAMES,
    ARTIFACT_SCHEMA_VERSION,
    CACHE_OPERATION_MARKER_NAME,
    INDEX_DIRTY_MARKER_NAME,
)
from mylittleharness.projection_index import INDEX_REL_PATH
from tests.test_cli import make_root, snapshot_tree, snapshot_tree_bytes


class ProjectionArtifactTests(unittest.TestCase):
    def test_projection_build_writes_expected_artifacts_without_source_bodies_or_lifecycle_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--build"])

            self.assertEqual(code, 0)
            artifact_dir = root / ARTIFACT_DIR_REL
            for name in ARTIFACT_NAMES:
                self.assertTrue((artifact_dir / name).is_file(), name)

            manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
            sources = json.loads((artifact_dir / "sources.json").read_text(encoding="utf-8"))
            relationships = json.loads((artifact_dir / "relationships.json").read_text(encoding="utf-8"))
            self.assertEqual(2, ARTIFACT_SCHEMA_VERSION)
            self.assertEqual(2, manifest["schema_version"])
            self.assertEqual(".mylittleharness/generated/projection", manifest["storage_boundary"])
            self.assertIn("project/project-state.md", {row["path"] for row in sources["sources"]})
            self.assertIn("nodes", relationships["relationships"])
            self.assertIn("edges", relationships["relationships"])
            self.assertIn("repo-visible relationship metadata remains authoritative", relationships["relationships"]["authority"])
            self.assertEqual(set(ARTIFACT_NAMES) - {"manifest.json"}, set(manifest["payload_hashes"]))
            self.assertEqual(64, len(manifest["source_set_hash"]))
            self.assertEqual(64, len(manifest["record_set_hash"]))
            self.assertFalse(manifest["query_capabilities"]["exact_text_search"]["artifact_backed"])
            self.assertTrue(manifest["query_capabilities"]["path_reference_search"]["artifact_backed"])
            self.assertFalse(manifest["query_capabilities"]["path_reference_search"]["stores_source_bodies"])

            combined = "\n".join((artifact_dir / name).read_text(encoding="utf-8") for name in ARTIFACT_NAMES)
            self.assertNotIn("See `.agents/docmap.yaml`", combined)
            self.assertNotIn("plan_status", combined)
            self.assertNotIn("active_plan", combined)
            self.assertIn("projection-artifact-build", output.getvalue())
            self.assertIn("projection-artifact-atomic-refresh", output.getvalue())

    def test_projection_artifact_refresh_failure_keeps_old_good_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build"]), 0)
            manifest_path = root / ARTIFACT_DIR_REL / "manifest.json"
            before = manifest_path.read_text(encoding="utf-8")
            (root / "README.md").write_text("# Changed\nSee `.agents/docmap.yaml`.\n", encoding="utf-8")

            output = io.StringIO()
            with patch("mylittleharness.projection_artifacts.apply_file_transaction", side_effect=FileTransactionError("boom")), redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--build"])

            self.assertEqual(code, 0)
            self.assertEqual(before, manifest_path.read_text(encoding="utf-8"))
            self.assertIn("projection-artifact-refresh-degraded", output.getvalue())
            self.assertIn("old-good artifacts", output.getvalue())

    def test_projection_inspect_reports_missing_artifacts_as_rebuildable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--inspect"])

            self.assertEqual(code, 0)
            rendered = output.getvalue()
            self.assertIn("projection-artifact-missing", rendered)
            self.assertNotIn("[ERROR]", rendered)

    def test_projection_inspect_reports_stale_incomplete_corrupt_schema_and_root_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build"]), 0)

            (root / "README.md").write_text("# Changed\n", encoding="utf-8")
            (root / ARTIFACT_DIR_REL / "links.json").unlink()
            (root / ARTIFACT_DIR_REL / "fan-in.json").write_text("{not json", encoding="utf-8")
            manifest_path = root / ARTIFACT_DIR_REL / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema_version"] = 999
            manifest["root"] = str(root / "elsewhere")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--inspect"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("projection-artifact-stale", rendered)
            self.assertIn("projection-artifact-incomplete", rendered)
            self.assertIn("projection-artifact-corrupt", rendered)
            self.assertIn("projection-artifact-schema", rendered)
            self.assertIn("projection-artifact-root-mismatch", rendered)
            self.assertIn("next_safe_command=mylittleharness --root <root> projection --rebuild --target all", rendered)

    def test_projection_inspect_reports_v2_integrity_unexpected_v1_and_malformed_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build"]), 0)

            artifact_dir = root / ARTIFACT_DIR_REL
            (artifact_dir / "extra.json").write_text("{}", encoding="utf-8")
            sources_path = artifact_dir / "sources.json"
            sources = json.loads(sources_path.read_text(encoding="utf-8"))
            sources["sources"][0]["path"] = "tampered.md"
            sources_path.write_text(json.dumps(sources), encoding="utf-8")
            summary_path = artifact_dir / "summary.json"
            summary_path.write_text(json.dumps({"schema_version": 2, "summary": []}), encoding="utf-8")
            manifest_path = artifact_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema_version"] = 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--inspect"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("projection-artifact-unexpected", rendered)
            self.assertIn("projection-artifact-schema", rendered)
            self.assertIn("stale v1 projection artifacts", rendered)
            self.assertIn("projection-artifact-malformed", rendered)
            self.assertIn("projection-artifact-hash", rendered)
            self.assertIn("next_safe_command=mylittleharness --root <root> projection --rebuild --target all", rendered)

    def test_projection_delete_and_rebuild_are_idempotent_and_bound_to_projection_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            sibling = root / ".mylittleharness/generated/keep.txt"
            sibling.parent.mkdir(parents=True)
            sibling.write_text("not projection output\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build"]), 0)
                self.assertEqual(main(["--root", str(root), "projection", "--delete"]), 0)
                self.assertEqual(main(["--root", str(root), "projection", "--delete"]), 0)
                self.assertEqual(main(["--root", str(root), "projection", "--rebuild"]), 0)

            self.assertTrue(sibling.is_file())
            artifact_dir = root / ARTIFACT_DIR_REL
            for name in ARTIFACT_NAMES:
                self.assertTrue((artifact_dir / name).is_file(), name)

    def test_projection_delete_refuses_directory_shaped_expected_artifact_without_partial_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build"]), 0)

            artifact_dir = root / ARTIFACT_DIR_REL
            (artifact_dir / "manifest.json").unlink()
            malformed_artifact = artifact_dir / "manifest.json"
            malformed_artifact.mkdir()
            (malformed_artifact / "nested.txt").write_text("not a generated JSON artifact\n", encoding="utf-8")
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--delete"])

            rendered = output.getvalue()
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("projection-artifact-delete-refused", rendered)
            self.assertIn("directory-shaped generated artifact path", rendered)
            self.assertTrue((artifact_dir / "sources.json").is_file())

    def test_projection_build_refuses_boundary_path_conflict_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            (root / ".mylittleharness").write_text("not a directory\n", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--build"])

            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("projection-artifact-boundary", output.getvalue())

    def test_projection_command_requires_explicit_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "projection"])
            self.assertEqual(raised.exception.code, 2)

    def test_projection_artifacts_do_not_authorize_attach_or_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build"]), 0)
            manifest_path = root / ARTIFACT_DIR_REL / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["pretend_authority"] = "repair approved"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            attach_output = io.StringIO()
            with redirect_stdout(attach_output):
                attach_code = main(["--root", str(root), "attach", "--apply", "--project", "Sample"])
            repair_output = io.StringIO()
            with redirect_stdout(repair_output):
                repair_code = main(["--root", str(root), "repair", "--apply"])

            self.assertEqual(attach_code, 2)
            self.assertEqual(repair_code, 2)
            self.assertIn("product-source compatibility fixture", attach_output.getvalue())
            self.assertIn("product-source compatibility fixture", repair_output.getvalue())

    def test_path_query_parity_auto_refreshes_stale_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build"]), 0)

            current_output = io.StringIO()
            with redirect_stdout(current_output):
                current_code = main(["--root", str(root), "intelligence", "--focus", "search", "--path", ".agents/docmap.yaml"])
            current_rendered = current_output.getvalue()
            self.assertEqual(current_code, 0)
            self.assertIn("projection-artifact-query-current", current_rendered)
            self.assertIn("artifact source matches=1", current_rendered)
            self.assertIn("reference matches=2", current_rendered)

            (root / "README.md").write_text("# Changed\nSee `.agents/docmap.yaml`.\n", encoding="utf-8")
            stale_output = io.StringIO()
            with redirect_stdout(stale_output):
                stale_code = main(["--root", str(root), "intelligence", "--focus", "search", "--path", ".agents/docmap.yaml"])
            stale_rendered = stale_output.getvalue()
            self.assertEqual(stale_code, 0)
            self.assertIn("navigation-cache-artifacts-refresh", stale_rendered)
            self.assertIn("projection-artifact-query-current", stale_rendered)
            self.assertNotIn("projection-artifact-query-skipped", stale_rendered)

    def test_exact_text_search_reports_source_only_projection_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--focus", "search", "--search", "MyLittleHarness"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("projection-exact-search-source-only", rendered)
            self.assertIn("search-match", rendered)
            self.assertFalse((root / ARTIFACT_DIR_REL).exists())

    def test_projection_warm_cache_target_all_refreshes_disposable_cache_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before_authority = {
                rel_path: content
                for rel_path, content in snapshot_tree_bytes(root).items()
                if rel_path != ".mylittleharness" and not rel_path.startswith(".mylittleharness/")
            }

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--warm-cache", "--target", "all"])

            after_authority = {
                rel_path: content
                for rel_path, content in snapshot_tree_bytes(root).items()
                if rel_path != ".mylittleharness" and not rel_path.startswith(".mylittleharness/")
            }
            rendered = output.getvalue()
            artifact_dir = root / ARTIFACT_DIR_REL
            self.assertEqual(code, 0)
            self.assertEqual(before_authority, after_authority)
            for name in ARTIFACT_NAMES:
                self.assertTrue((artifact_dir / name).is_file(), name)
            self.assertTrue((root / INDEX_REL_PATH).is_file())
            self.assertIn("projection --warm-cache --target all", rendered)
            self.assertIn("projection-artifact-warm-cache", rendered)
            self.assertIn("projection-index-warm-cache", rendered)
            self.assertIn("cannot affect lifecycle authority", rendered)

    def test_dashboard_projection_pulse_reports_dirty_and_operation_markers_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            projection_dir = root / ARTIFACT_DIR_REL
            projection_dir.mkdir(parents=True)
            dirty_payload = {
                "schema_version": 1,
                "marker_kind": "mylittleharness-projection-cache-dirty",
                "command": "plan --apply",
                "dirty_since_utc": "2026-05-12T01:02:03Z",
                "changed_paths": ["project/implementation-plan.md"],
                "authority": "repo-visible source files remain authoritative",
            }
            (projection_dir / ARTIFACT_DIRTY_MARKER_NAME).write_text(json.dumps(dirty_payload), encoding="utf-8")
            (projection_dir / INDEX_DIRTY_MARKER_NAME).write_text(json.dumps(dirty_payload), encoding="utf-8")
            before = snapshot_tree(root)

            warmable_output = io.StringIO()
            with redirect_stdout(warmable_output):
                self.assertEqual(main(["--root", str(root), "dashboard", "--inspect", "--json"]), 0)

            self.assertEqual(before, snapshot_tree(root))
            warmable_payload = json.loads(warmable_output.getvalue())
            pulse = warmable_payload["mlhd"]["projection_pulse"]
            self.assertEqual("mylittleharness.projection-pulse.v1", pulse["schema"])
            self.assertEqual("warmable", pulse["status"])
            self.assertTrue(pulse["dirty"])
            self.assertEqual("2026-05-12T01:02:03Z", pulse["dirty_since_utc"])
            self.assertEqual(2, pulse["dirty_marker_count"])
            self.assertEqual("mylittleharness --root <root> mlhd run-once --apply", pulse["owner_command"])
            self.assertEqual("mylittleharness --root <root> projection --warm-cache --target all", pulse["warm_cache_command"])
            self.assertEqual("mylittleharness --root <root> projection --warm-cache --target all", pulse["manual_recovery_command"])
            self.assertIn("lifecycle routes remain authoritative", pulse["authority"])

            operation_payload = {
                "schema_version": 1,
                "marker_kind": "mylittleharness-projection-cache-operation",
                "operation": "projection-index-build",
                "created_at_utc": "2026-05-12T02:03:04Z",
                "authority": "repo-visible source files remain authoritative",
            }
            (projection_dir / CACHE_OPERATION_MARKER_NAME).write_text(json.dumps(operation_payload), encoding="utf-8")
            operation_before = snapshot_tree(root)

            updating_output = io.StringIO()
            with redirect_stdout(updating_output):
                self.assertEqual(main(["--root", str(root), "dashboard", "--inspect", "--json"]), 0)

            self.assertEqual(operation_before, snapshot_tree(root))
            updating_pulse = json.loads(updating_output.getvalue())["mlhd"]["projection_pulse"]
            self.assertEqual("updating-or-interrupted", updating_pulse["status"])
            self.assertEqual("projection-index-build", updating_pulse["operation"])
            self.assertEqual("2026-05-12T02:03:04Z", updating_pulse["operation_created_at_utc"])


if __name__ == "__main__":
    unittest.main()
