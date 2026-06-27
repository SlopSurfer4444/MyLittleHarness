from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.cli import main
from mylittleharness.projection_artifacts import ARTIFACT_DIR_REL, INDEX_DIRTY_MARKER_NAME
from mylittleharness.projection_index import INDEX_NAME, INDEX_REL_PATH, INDEX_SCHEMA_VERSION
from tests.test_cli import make_operating_root, make_root


class ProjectionIndexTests(unittest.TestCase):
    def test_projection_index_build_writes_schema_metadata_and_source_bound_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--build", "--target", "index"])

            self.assertEqual(code, 0)
            self.assertIn("projection-index-build", output.getvalue())
            index_path = root / INDEX_REL_PATH
            self.assertTrue(index_path.is_file())
            with closing(sqlite3.connect(index_path)) as connection:
                metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                    ).fetchall()
                }
                source_count = connection.execute("SELECT COUNT(*) FROM source_records").fetchone()[0]
                path_count = connection.execute("SELECT COUNT(*) FROM path_rows").fetchone()[0]
                path_fts_count = connection.execute("SELECT COUNT(*) FROM path_fts").fetchone()[0]
                row = connection.execute(
                    "SELECT source_path, line_start, line_end, source_hash, source_role, source_type, indexed_text, provenance FROM index_rows ORDER BY row_id LIMIT 1"
                ).fetchone()
                path_row = connection.execute(
                    "SELECT row_kind, source_path, line_number, target_path, indexed_text, provenance FROM path_rows ORDER BY row_id LIMIT 1"
                ).fetchone()

            self.assertEqual(str(INDEX_SCHEMA_VERSION), metadata["schema_version"])
            self.assertEqual("1.0.1", metadata["product_version"])
            self.assertEqual(".mylittleharness/generated/projection", metadata["storage_boundary"])
            self.assertEqual("true", metadata["fts5_available"])
            self.assertEqual("true", metadata["bm25_available"])
            self.assertEqual("mylittleharness-sqlite-fts-bm25-projection", metadata["index_kind"])
            self.assertIn("projection-index-atomic-refresh", output.getvalue())
            self.assertTrue({"path_rows", "path_fts"}.issubset(table_names))
            self.assertGreater(source_count, 0)
            self.assertGreater(path_count, 0)
            self.assertEqual(path_count, path_fts_count)
            self.assertEqual(str(path_count), metadata["path_row_count"])
            self.assertIsNotNone(row)
            self.assertEqual(row[1], row[2])
            self.assertEqual("inventory-surface", row[5])
            self.assertIn(f"{row[0]}:{row[1]}", row[7])
            self.assertIsNotNone(path_row)
            self.assertEqual("source", path_row[0])
            self.assertEqual(path_row[1], path_row[3])
            self.assertEqual(path_row[1], path_row[4])
            self.assertEqual(path_row[1], path_row[5])
            metadata_text = json.dumps(metadata, sort_keys=True)
            for forbidden in ("plan_status", "active_plan", "repair approved", "closeout", "commit"):
                self.assertNotIn(forbidden, metadata_text)

    def test_projection_target_default_artifacts_and_all_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build"]), 0)
            self.assertTrue((root / ARTIFACT_DIR_REL / "manifest.json").is_file())
            self.assertFalse((root / INDEX_REL_PATH).exists())

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "all"]), 0)
            self.assertTrue((root / ARTIFACT_DIR_REL / "manifest.json").is_file())
            self.assertTrue((root / INDEX_REL_PATH).is_file())

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--delete", "--target", "artifacts"]), 0)
            self.assertFalse((root / ARTIFACT_DIR_REL / "manifest.json").exists())
            self.assertTrue((root / INDEX_REL_PATH).is_file())

    def test_projection_index_inspect_reports_drift_and_malformed_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)

            index_path = root / INDEX_REL_PATH
            with closing(sqlite3.connect(index_path)) as connection:
                connection.execute("UPDATE metadata SET value = ? WHERE key = 'schema_version'", ("999",))
                connection.execute("UPDATE metadata SET value = ? WHERE key = 'root'", (str(root / "elsewhere"),))
                connection.execute("UPDATE metadata SET value = ? WHERE key = 'indexed_row_count'", ("999999",))
                connection.execute("DELETE FROM index_rows WHERE row_id = (SELECT MIN(row_id) FROM index_rows)")
                connection.commit()
            (root / "README.md").write_text("# Changed\nMyLittleHarness changed.\n", encoding="utf-8")
            (root / ARTIFACT_DIR_REL / f"{INDEX_NAME}.extra").write_text("unexpected\n", encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--inspect", "--target", "index"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("projection-index-schema", rendered)
            self.assertIn("projection-index-root-mismatch", rendered)
            self.assertIn("projection-index-hash", rendered)
            self.assertIn("projection-index-stale", rendered)
            self.assertIn("projection-index-count", rendered)
            self.assertIn("projection-index-unexpected-sidecar", rendered)
            self.assertIn("next_safe_command=mylittleharness --root <root> projection --rebuild --target all", rendered)

    def test_projection_index_inspect_reports_missing_path_navigation_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)

            index_path = root / INDEX_REL_PATH
            with closing(sqlite3.connect(index_path)) as connection:
                connection.execute("DROP TABLE path_fts")
                connection.execute("DROP TABLE path_rows")
                connection.commit()

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--inspect", "--target", "index"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("expected SQLite index table is missing: path_fts", rendered)
            self.assertIn("expected SQLite index table is missing: path_rows", rendered)

    def test_projection_index_inspect_rejects_symlinked_index_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp) / "root", active=False, mirrors=False)
            outside = Path(tmp) / "outside.sqlite3"
            outside.write_text("not authoritative\n", encoding="utf-8")
            index_path = root / INDEX_REL_PATH
            index_path.parent.mkdir(parents=True)
            try:
                os.symlink(outside, index_path)
            except OSError as exc:
                self.skipTest(f"file symlinks are unavailable: {exc}")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--inspect", "--target", "index"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("projection-index-boundary", rendered)
            self.assertIn("symlink", rendered)
            self.assertNotIn("projection-index-current", rendered)

    def test_projection_index_inspect_reports_missing_required_metadata_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)

            with closing(sqlite3.connect(root / INDEX_REL_PATH)) as connection:
                connection.execute("DELETE FROM metadata WHERE key IN ('root', 'record_set_hash', 'query_capabilities')")
                connection.commit()

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--inspect", "--target", "index"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("projection-index-malformed", rendered)
            self.assertIn("SQLite index metadata is missing required key(s)", rendered)
            self.assertNotIn("projection-index-current", rendered)

    def test_projection_index_inspect_reports_corrupt_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            index_path = root / INDEX_REL_PATH
            index_path.parent.mkdir(parents=True)
            index_path.write_text("not sqlite\n", encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--inspect", "--target", "index"])

            self.assertEqual(code, 0)
            self.assertIn("projection-index-corrupt", output.getvalue())

    def test_projection_index_delete_removes_only_index_owned_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "all"]), 0)
            known_sidecar = root / ARTIFACT_DIR_REL / f"{INDEX_NAME}-wal"
            unexpected_sidecar = root / ARTIFACT_DIR_REL / f"{INDEX_NAME}.extra"
            known_sidecar.write_text("known\n", encoding="utf-8")
            unexpected_sidecar.write_text("unexpected\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--delete", "--target", "index"]), 0)

            self.assertFalse((root / INDEX_REL_PATH).exists())
            self.assertFalse(known_sidecar.exists())
            self.assertTrue(unexpected_sidecar.is_file())
            self.assertTrue((root / ARTIFACT_DIR_REL / "manifest.json").is_file())

    def test_projection_index_delete_reports_directory_sidecar_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)
            directory_sidecar = root / ARTIFACT_DIR_REL / f"{INDEX_NAME}-wal"
            directory_sidecar.mkdir()
            (directory_sidecar / "keep.txt").write_text("preserved\n", encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--delete", "--target", "index"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertFalse((root / INDEX_REL_PATH).exists())
            self.assertTrue(directory_sidecar.is_dir())
            self.assertIn("projection-index-delete-skipped", rendered)
            self.assertIn("directory-shaped SQLite index sidecar", rendered)

    def test_projection_index_refresh_failure_keeps_old_good_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)
            index_path = root / INDEX_REL_PATH
            before_bytes = index_path.read_bytes()
            (root / "README.md").write_text("# Changed\nMyLittleHarness changed after old-good index.\n", encoding="utf-8")

            output = io.StringIO()
            with patch("mylittleharness.projection_index._write_fts_rows", side_effect=sqlite3.Error("boom")), redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--build", "--target", "index"])

            self.assertEqual(code, 0)
            self.assertEqual(before_bytes, index_path.read_bytes())
            self.assertIn("projection-index-build-failed", output.getvalue())
            self.assertIn("old-good index", output.getvalue())

    def test_projection_index_publish_failure_keeps_old_good_index_and_dirty_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)
            index_path = root / INDEX_REL_PATH
            dirty_path = root / ARTIFACT_DIR_REL / INDEX_DIRTY_MARKER_NAME
            dirty_path.write_text('{"marker_kind":"mylittleharness-projection-cache-dirty"}\n', encoding="utf-8")
            before_bytes = index_path.read_bytes()
            (root / "README.md").write_text("# Changed\nMyLittleHarness changed before publish failure.\n", encoding="utf-8")

            output = io.StringIO()
            with patch.object(Path, "replace", side_effect=OSError("publish boom")), redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--build", "--target", "index"])

            self.assertEqual(code, 0)
            self.assertEqual(before_bytes, index_path.read_bytes())
            self.assertTrue(dirty_path.is_file())
            self.assertIn("projection-index-build-failed", output.getvalue())
            self.assertIn("old-good index", output.getvalue())

    def test_full_text_search_auto_refreshes_source_verified_index_and_exact_search_survives_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            missing_output = io.StringIO()
            with redirect_stdout(missing_output):
                missing_code = main(["--root", str(root), "intelligence", "--focus", "search", "--full-text", "MyLittleHarness"])
            self.assertEqual(missing_code, 0)
            missing_rendered = missing_output.getvalue()
            self.assertIn("navigation-cache-index-refresh", missing_rendered)
            self.assertIn("projection-index-query-current", missing_rendered)
            self.assertIn("full-text-match", missing_rendered)

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)
            current_output = io.StringIO()
            with redirect_stdout(current_output):
                current_code = main(["--root", str(root), "intelligence", "--focus", "search", "--full-text", "MyLittleHarness", "--limit", "5"])
            current_rendered = current_output.getvalue()
            self.assertEqual(current_code, 0)
            self.assertIn("projection-index-query-current", current_rendered)
            self.assertIn("full-text-match", current_rendered)
            self.assertIn("verification=source-verified", current_rendered)

            (root / "README.md").write_text("# Changed\nMyLittleHarness changed.\n", encoding="utf-8")
            stale_output = io.StringIO()
            with redirect_stdout(stale_output):
                stale_code = main(["--root", str(root), "intelligence", "--focus", "search", "--full-text", "MyLittleHarness"])
            self.assertEqual(stale_code, 0)
            stale_rendered = stale_output.getvalue()
            self.assertIn("navigation-cache-index-refresh", stale_rendered)
            self.assertIn("projection-index-query-current", stale_rendered)
            self.assertNotIn("projection-index-query-skipped", stale_rendered)

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--delete", "--target", "index"]), 0)
            exact_output = io.StringIO()
            with redirect_stdout(exact_output):
                exact_code = main(["--root", str(root), "intelligence", "--focus", "search", "--search", "MyLittleHarness"])
            self.assertEqual(exact_code, 0)
            self.assertIn("projection-exact-search-source-only", exact_output.getvalue())
            self.assertIn("search-match", exact_output.getvalue())

    def test_unified_query_uses_current_source_verified_index_and_path_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--focus", "search", "--query", ".agents/docmap.yaml", "--limit", "5"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("intelligence-query-expansion", rendered)
            self.assertIn("projection-index-query-current", rendered)
            self.assertIn("full-text-match", rendered)
            self.assertIn("verification=source-verified", rendered)
            self.assertIn("search-match", rendered)
            self.assertIn("search-path-match", rendered)
            self.assertIn("search-path-reference", rendered)

    def test_unified_query_auto_refreshes_missing_or_stale_index_while_keeping_exact_and_path_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            missing_output = io.StringIO()
            with redirect_stdout(missing_output):
                missing_code = main(["--root", str(root), "intelligence", "--focus", "search", "--query", ".agents/docmap.yaml"])
            missing_rendered = missing_output.getvalue()
            self.assertEqual(missing_code, 0)
            self.assertIn("navigation-cache-index-refresh", missing_rendered)
            self.assertIn("projection-index-query-current", missing_rendered)
            self.assertIn("search-match", missing_rendered)
            self.assertIn("search-path-reference", missing_rendered)

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)
            (root / "README.md").write_text("# Changed\nSee `.agents/docmap.yaml` after stale index.\n", encoding="utf-8")
            stale_output = io.StringIO()
            with redirect_stdout(stale_output):
                stale_code = main(["--root", str(root), "intelligence", "--focus", "search", "--query", ".agents/docmap.yaml"])
            stale_rendered = stale_output.getvalue()
            self.assertEqual(stale_code, 0)
            self.assertIn("navigation-cache-index-refresh", stale_rendered)
            self.assertIn("projection-index-query-current", stale_rendered)
            self.assertIn("search-match", stale_rendered)
            self.assertIn("search-path-reference", stale_rendered)

    def test_unified_query_finds_source_verified_cold_memory_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            archived_plan = root / "project/archive/plans/2026-05-03-cold-retrieval.md"
            archived_plan.write_text(
                "---\n"
                'status: "complete"\n'
                'related_verification: "project/archive/reference/verification/2026-05-03-cold-proof.md"\n'
                "---\n"
                "# Cold Retrieval\n\n"
                "ColdMemoryNeedle archived plan proof.\n",
                encoding="utf-8",
            )
            proof_path = root / "project/archive/reference/verification/2026-05-03-cold-proof.md"
            proof_path.parent.mkdir(parents=True, exist_ok=True)
            proof_path.write_text("# Cold Proof\n\nColdMemoryNeedle verification record.\n", encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--focus", "search", "--query", "ColdMemoryNeedle", "--limit", "5"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("navigation-cache-index-refresh", rendered)
            self.assertIn("projection-index-query-current", rendered)
            self.assertIn("projection-exact-search-source-only", rendered)
            self.assertIn("full-text-match", rendered)
            self.assertIn("search-match", rendered)
            self.assertIn("verification=source-verified", rendered)
            self.assertIn("project/archive/plans/2026-05-03-cold-retrieval.md", rendered)
            self.assertIn("project/archive/reference/verification/2026-05-03-cold-proof.md", rendered)

    def test_full_text_plain_multi_term_query_relaxes_to_or_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            (root / "README.md").write_text("# Readme\nZebraTerm lives in the readme.\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# Agents\nYakTerm lives in the agent contract.\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)

            relaxed_output = io.StringIO()
            with redirect_stdout(relaxed_output):
                relaxed_code = main(["--root", str(root), "intelligence", "--focus", "search", "--full-text", "ZebraTerm YakTerm", "--limit", "5"])
            relaxed_rendered = relaxed_output.getvalue()
            self.assertEqual(relaxed_code, 0)
            self.assertIn("query_mode=fts5-bm25-relaxed-or", relaxed_rendered)
            self.assertIn("README.md", relaxed_rendered)
            self.assertIn("AGENTS.md", relaxed_rendered)
            self.assertNotIn("full-text-no-matches", relaxed_rendered)

            explicit_output = io.StringIO()
            with redirect_stdout(explicit_output):
                explicit_code = main(["--root", str(root), "intelligence", "--focus", "search", "--full-text", "ZebraTerm OR YakTerm", "--limit", "5"])
            self.assertEqual(explicit_code, 0)
            self.assertIn("query_mode=fts5-bm25", explicit_output.getvalue())

    def test_full_text_limit_requires_positive_integer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "intelligence", "--focus", "search", "--full-text", "MyLittleHarness", "--limit", "0"])
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("--limit must be >= 1", output.getvalue())

    def test_unsupported_fts5_degrades_without_index_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with patch("mylittleharness.projection_index._fts5_is_available", return_value=False), redirect_stdout(output):
                code = main(["--root", str(root), "projection", "--build", "--target", "index"])

            self.assertEqual(code, 0)
            self.assertIn("projection-index-fts5-unavailable", output.getvalue())
            self.assertFalse((root / INDEX_REL_PATH).exists())

    def test_projection_index_does_not_authorize_attach_or_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)
            with closing(sqlite3.connect(root / INDEX_REL_PATH)) as connection:
                connection.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES ('pretend_authority', 'repair approved')")
                connection.commit()

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


if __name__ == "__main__":
    unittest.main()
