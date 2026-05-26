from __future__ import annotations

import hashlib
import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness import atomic_files
from mylittleharness.cli import main
from mylittleharness.parsing import parse_frontmatter


class MemoryHygieneTests(unittest.TestCase):
    def test_dry_run_reports_exact_lifecycle_plan_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            make_research_source(root)
            (root / "project/plan-incubation/lane.md").write_text(
                "See `project/research/raw-import.md` and [raw](../research/raw-import.md).\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--dry-run",
                        "--source",
                        "project/research/raw-import.md",
                        "--promoted-to",
                        "project/specs/workflow/workflow-memory-routing-spec.md",
                        "--archive-to",
                        "project/archive/reference/research/2026-05-01-raw-import/raw-import.md",
                        "--repair-links",
                    ]
                )

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("MyLittleHarness memory-hygiene --dry-run", rendered)
            self.assertIn("memory-hygiene-dry-run", rendered)
            self.assertIn("would update lifecycle frontmatter", rendered)
            self.assertIn("would archive source", rendered)
            self.assertIn("would repair exact links", rendered)
            self.assertIn("cannot approve closeout, archive, commit, rollback, or lifecycle decisions", rendered)

    def test_apply_updates_frontmatter_archives_source_and_repairs_exact_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_research_source(root)
            lane = root / "project/plan-incubation/lane.md"
            lane.write_text(
                "Promoted from `project/research/raw-import.md`.\n"
                "Relative link stays untouched: [raw](../research/raw-import.md).\n",
                encoding="utf-8",
            )
            archive_rel = "project/archive/reference/research/2026-05-01-raw-import/raw-import.md"
            output = io.StringIO()

            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--apply",
                        "--source",
                        "project/research/raw-import.md",
                        "--promoted-to",
                        "project/specs/workflow/workflow-memory-routing-spec.md",
                        "--archive-to",
                        archive_rel,
                        "--repair-links",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertFalse(source.exists())
            archived = root / archive_rel
            self.assertTrue(archived.is_file())
            archived_text = archived.read_text(encoding="utf-8")
            self.assertIn('status: "distilled"', archived_text)
            self.assertIn('promoted_to: "project/specs/workflow/workflow-memory-routing-spec.md"', archived_text)
            self.assertIn(f'archived_to: "{archive_rel}"', archived_text)
            self.assertIn("# Raw Import", archived_text)
            self.assertIn(f"`{archive_rel}`", lane.read_text(encoding="utf-8"))
            self.assertIn("../research/raw-import.md", lane.read_text(encoding="utf-8"))
            self.assertIn("memory-hygiene-archived", output.getvalue())
            self.assertIn("memory-hygiene-link-repaired", output.getvalue())

    def test_apply_refuses_product_fixture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_product_fixture_root(Path(tmp))
            make_research_source(root)
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--apply",
                        "--source",
                        "project/research/raw-import.md",
                        "--promoted-to",
                        "project/specs/workflow/workflow-memory-routing-spec.md",
                    ]
                )

            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("memory-hygiene-refused", output.getvalue())
            self.assertIn("product-source compatibility fixture", output.getvalue())

    def test_rotate_ledger_dry_run_and_apply_seed_fresh_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            for spec_name in (
                "workflow-artifact-model-spec.md",
                "workflow-capability-roadmap-spec.md",
                "workflow-plan-synthesis-spec.md",
                "workflow-rollout-slices-spec.md",
                "workflow-verification-and-closeout-spec.md",
            ):
                (root / f"project/specs/workflow/{spec_name}").write_text(
                    "---\n"
                    'spec_status: "draft"\n'
                    'implementation_posture: "target-only"\n'
                    "---\n"
                    f"# {spec_name}\n",
                    encoding="utf-8",
                )
            ledger_rel = "project/verification/autonomous-mlh-swim-ledger.md"
            source_text = "# Autonomous MLH Swim Ledger\n\nOld verification history.\n"
            ledger = root / ledger_rel
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(source_text, encoding="utf-8")
            source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            archive_rel = f"project/archive/reference/verification/{date.today().isoformat()}-autonomous-mlh-swim-ledger.md"
            before = snapshot_tree(root)

            dry_output = io.StringIO()
            with redirect_stdout(dry_output):
                dry_code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--dry-run",
                        "--rotate-ledger",
                        "--source",
                        ledger_rel,
                        "--reason",
                        "test rotation",
                    ]
                )

            rendered = dry_output.getvalue()
            self.assertEqual(dry_code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("verification-ledger-rotate-dry-run", rendered)
            self.assertIn(source_hash, rendered)
            self.assertIn(archive_rel, rendered)
            self.assertIn(f"--source-hash {source_hash}", rendered)

            apply_output = io.StringIO()
            with redirect_stdout(apply_output):
                apply_code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--apply",
                        "--rotate-ledger",
                        "--source",
                        ledger_rel,
                        "--source-hash",
                        source_hash,
                        "--reason",
                        "test rotation",
                    ]
                )

            self.assertEqual(apply_code, 0)
            self.assertEqual((root / archive_rel).read_text(encoding="utf-8"), source_text)
            fresh_text = ledger.read_text(encoding="utf-8")
            self.assertIn("mylittleharness-verification-ledger-continuity", fresh_text)
            self.assertIn(f"Previous ledger archive: `{archive_rel}`", fresh_text)
            self.assertIn(f"Previous ledger sha256: `{source_hash}`", fresh_text)
            self.assertIn("Reason: test rotation", fresh_text)
            self.assertIn("verification-ledger-archived", apply_output.getvalue())
            self.assertIn("verification-ledger-seeded", apply_output.getvalue())

            check_output = io.StringIO()
            with redirect_stdout(check_output):
                check_code = main(["--root", str(root), "check"])
            self.assertEqual(check_code, 0)
            check_rendered = check_output.getvalue()
            self.assertIn("check-verification-ledger-active", check_rendered)
            self.assertIn("fresh active verification ledger with continuity pointer", check_rendered)
            self.assertIn("check-verification-ledger-archive", check_rendered)
            self.assertIn("historical, not active continuation state", check_rendered)

    def test_rotate_ledger_apply_refuses_stale_source_hash_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            ledger_rel = "project/verification/autonomous-mlh-swim-ledger.md"
            original_text = "# Ledger\n\nOriginal history.\n"
            ledger = root / ledger_rel
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(original_text, encoding="utf-8")
            stale_hash = hashlib.sha256(original_text.encode("utf-8")).hexdigest()
            changed_text = "# Ledger\n\nChanged after review.\n"
            ledger.write_text(changed_text, encoding="utf-8")
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--apply",
                        "--rotate-ledger",
                        "--source",
                        ledger_rel,
                        "--source-hash",
                        stale_hash,
                    ]
                )

            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / f"project/archive/reference/verification/{date.today().isoformat()}-autonomous-mlh-swim-ledger.md").exists())
            self.assertIn("source hash changed after review", output.getvalue())

    def test_rotate_ledger_apply_refuses_product_fixture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_product_fixture_root(Path(tmp))
            ledger_rel = "project/verification/autonomous-mlh-swim-ledger.md"
            source_text = "# Ledger\n\nFixture history.\n"
            ledger = root / ledger_rel
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(source_text, encoding="utf-8")
            source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--apply",
                        "--rotate-ledger",
                        "--source",
                        ledger_rel,
                        "--source-hash",
                        source_hash,
                    ]
                )

            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("verification-ledger-rotate-refused", output.getvalue())
            self.assertIn("product-source compatibility fixture", output.getvalue())

    def test_apply_refuses_archive_conflict_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_research_source(root)
            archive_rel = "project/archive/reference/research/2026-05-01-raw-import/raw-import.md"
            archive = root / archive_rel
            archive.parent.mkdir(parents=True)
            archive.write_text("existing archive\n", encoding="utf-8")
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--apply",
                        "--source",
                        "project/research/raw-import.md",
                        "--promoted-to",
                        "project/specs/workflow/workflow-memory-routing-spec.md",
                        "--archive-to",
                        archive_rel,
                    ]
                )

            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertTrue(source.is_file())
            self.assertIn("archive target already exists", output.getvalue())

    def test_apply_rolls_back_archive_and_source_when_link_repair_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_research_source(root)
            lane = root / "project/plan-incubation/lane.md"
            lane.write_text("Promoted from `project/research/raw-import.md`.\n", encoding="utf-8")
            archive_rel = "project/archive/reference/research/2026-05-01-raw-import/raw-import.md"
            before = snapshot_tree(root)

            output = io.StringIO()
            failing_replace = fail_once_when_replace_targets(lane)
            with patch("mylittleharness.atomic_files._replace_path", side_effect=failing_replace), redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--apply",
                        "--source",
                        "project/research/raw-import.md",
                        "--promoted-to",
                        "project/specs/workflow/workflow-memory-routing-spec.md",
                        "--archive-to",
                        archive_rel,
                        "--repair-links",
                    ]
                )

            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertTrue(source.exists())
            self.assertFalse((root / archive_rel).exists())
            self.assertIn("rolled back completed target writes", output.getvalue())

    def test_scan_reports_relationship_findings_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_incubation_source(root)
            archived_plan = "project/archive/plans/2026-05-01-relation-test.md"
            (root / archived_plan).parent.mkdir(parents=True)
            (root / archived_plan).write_text("# Archived Plan\n", encoding="utf-8")
            write_relationship_roadmap(
                root,
                source.relative_to(root).as_posix(),
                status="done",
                archived_plan=archived_plan,
                verification_summary="focused verification passed",
                docs_decision="updated",
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "memory-hygiene", "--dry-run", "--scan"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("relationship-missing-reciprocal", rendered)
            self.assertIn("relationship-auto-archive-candidate", rendered)
            self.assertIn("incubation-cleanup-archive-candidate", rendered)
            self.assertIn("incubation-cleanup-link-repair-candidate", rendered)
            self.assertIn("incubation-cleanup-advisor-summary", rendered)
            self.assertIn("relationship-scan-read-only", rendered)
            self.assertIn("cli-text-audit-summary", rendered)

    def test_scan_proposal_token_applies_current_cleanup_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            archive_plan_dir = root / "project/archive/plans"
            archive_plan_dir.mkdir(parents=True, exist_ok=True)
            item_blocks = []
            source_rels = []
            archive_rels = []
            for index in range(2):
                item_id = f"covered-{index}"
                source_rel = f"project/plan-incubation/covered-{index}.md"
                archive_rel = f"project/archive/reference/incubation/{date.today().isoformat()}-covered-{index}.md"
                archive_plan_rel = f"project/archive/plans/covered-{index}.md"
                source_rels.append(source_rel)
                archive_rels.append(archive_rel)
                (root / source_rel).write_text(
                    "---\n"
                    f'topic: "Covered {index}"\n'
                    'status: "incubating"\n'
                    'related_roadmap: "project/roadmap.md"\n'
                    f'related_roadmap_item: "{item_id}"\n'
                    "---\n"
                    f"# Covered {index}\n\n"
                    "## Entries\n\n"
                    "### 2026-05-01\n\n"
                    "Covered work.\n",
                    encoding="utf-8",
                )
                (root / archive_plan_rel).write_text(f"# Covered {index}\n", encoding="utf-8")
                item_blocks.append(
                    f"### Covered {index}\n\n"
                    f"- `id`: `{item_id}`\n"
                    "- `status`: `done`\n"
                    f"- `source_incubation`: `{source_rel}`\n"
                    f"- `archived_plan`: `{archive_plan_rel}`\n"
                    "- `verification_summary`: `covered`\n"
                    "- `docs_decision`: `not-needed`\n"
                )
            (root / "project/roadmap.md").write_text(
                "---\n"
                'id: "memory-routing-roadmap"\n'
                "---\n"
                "# Roadmap\n\n"
                "## Items\n\n"
                + "\n".join(item_blocks),
                encoding="utf-8",
            )
            verification = root / "project/verification/cleanup-links.md"
            verification.parent.mkdir(parents=True, exist_ok=True)
            verification.write_text(
                f"Covered source refs: `{source_rels[0]}` and `{source_rels[1]}`.\n",
                encoding="utf-8",
            )

            dry_output = io.StringIO()
            before = snapshot_tree(root)
            with redirect_stdout(dry_output):
                dry_code = main(["--root", str(root), "memory-hygiene", "--dry-run", "--scan"])
            dry_rendered = dry_output.getvalue()
            self.assertEqual(dry_code, 0)
            self.assertEqual(before, snapshot_tree(root))
            token_match = re.search(r"batch_review_token=(mhb-[a-f0-9]{16})", dry_rendered)
            self.assertIsNotNone(token_match)
            token = token_match.group(1)

            apply_output = io.StringIO()
            with redirect_stdout(apply_output):
                apply_code = main(["--root", str(root), "memory-hygiene", "--apply", "--scan", "--proposal-token", token])

            rendered = apply_output.getvalue()
            self.assertEqual(apply_code, 0)
            for source_rel, archive_rel in zip(source_rels, archive_rels):
                self.assertFalse((root / source_rel).exists())
                archived_text = (root / archive_rel).read_text(encoding="utf-8")
                self.assertIn('status: "implemented"', archived_text)
                self.assertIn(f'archived_to: "{archive_rel}"', archived_text)
            verification_text = verification.read_text(encoding="utf-8")
            roadmap_text = (root / "project/roadmap.md").read_text(encoding="utf-8")
            for source_rel, archive_rel in zip(source_rels, archive_rels):
                self.assertNotIn(source_rel, verification_text)
                self.assertNotIn(source_rel, roadmap_text)
                self.assertIn(archive_rel, verification_text)
                self.assertIn(archive_rel, roadmap_text)
            self.assertIn("memory-hygiene-batch-token-accepted", rendered)
            self.assertIn("memory-hygiene-batch-candidate-applied", rendered)
            self.assertIn("memory-hygiene-link-repaired", rendered)

    def test_scan_proposal_token_refuses_stale_link_hash_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_incubation_source(root)
            source_rel = source.relative_to(root).as_posix()
            archive_plan = "project/archive/plans/covered.md"
            (root / archive_plan).parent.mkdir(parents=True, exist_ok=True)
            (root / archive_plan).write_text("# Covered\n", encoding="utf-8")
            write_relationship_roadmap(
                root,
                source_rel,
                status="done",
                archived_plan=archive_plan,
                verification_summary="covered",
                docs_decision="updated",
            )
            link_file = root / "project/verification/cleanup-links.md"
            link_file.parent.mkdir(parents=True, exist_ok=True)
            link_file.write_text(f"Covered source ref: `{source_rel}`.\n", encoding="utf-8")

            dry_output = io.StringIO()
            with redirect_stdout(dry_output):
                dry_code = main(["--root", str(root), "memory-hygiene", "--dry-run", "--scan"])
            self.assertEqual(dry_code, 0)
            token_match = re.search(r"batch_review_token=(mhb-[a-f0-9]{16})", dry_output.getvalue())
            self.assertIsNotNone(token_match)
            token = token_match.group(1)

            link_file.write_text(f"Covered source ref changed after review: `{source_rel}`.\n", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "memory-hygiene", "--apply", "--scan", "--proposal-token", token])

            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertTrue(source.exists())
            self.assertFalse((root / f"project/archive/reference/incubation/{date.today().isoformat()}-idea.md").exists())
            self.assertIn("proposal token mismatch or stale scan", output.getvalue())

    def test_scan_treats_reconstructed_archive_uncertain_docs_as_historical_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_incubation_source(root)
            archived_plan = "project/archive/plans/2026-05-01-relation-test.md"
            archive_path = root / archived_plan
            archive_path.parent.mkdir(parents=True)
            archive_path.write_text(
                "---\n"
                'plan_id: "relation-test"\n'
                'status: "complete"\n'
                'docs_decision: "uncertain"\n'
                'reconstruction_status: "reconstructed"\n'
                'authority: "reconstructed historical dependency evidence only"\n'
                "---\n"
                "# Relation Test\n\n"
                "This file is a reconstructed historical pointer. "
                "It is not the original implementation plan.\n",
                encoding="utf-8",
            )
            write_relationship_roadmap(
                root,
                source.relative_to(root).as_posix(),
                status="done",
                archived_plan=archived_plan,
                verification_summary="historical verification was reconstructed from roadmap evidence",
                docs_decision="uncertain",
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "memory-hygiene", "--dry-run", "--scan"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("relationship-roadmap-done-reconstructed-docs", rendered)
            self.assertIn("reconstructed historical evidence", rendered)
            self.assertNotIn("relationship-roadmap-done-missing-docs", rendered)

    def test_scan_reports_entry_coverage_and_split_suggestions_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            make_mixed_incubation_source(
                root,
                coverage=(
                    "## Entry Coverage\n\n"
                    "- `2026-05-01`: `implemented` via `project/archive/plans/implemented.md`\n"
                    "- `2026-05-02`: `incubating` still open\n"
                ),
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "memory-hygiene", "--dry-run", "--scan"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("relationship-entry-coverage-needed", rendered)
            self.assertIn("incubation-cleanup-entry-coverage-needed", rendered)
            self.assertIn("entry coverage 2026-05-02 is incubating", rendered)
            self.assertIn("relationship-semantic-split-suggestion", rendered)
            self.assertIn("heuristic no-write suggestion", rendered)

    def test_scan_quotes_cleanup_candidate_source_and_archive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = root / "project/plan-incubation/covered note.md"
            source.write_text(
                "---\n"
                'status: "implemented"\n'
                "---\n"
                "# Covered Note\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "memory-hygiene", "--dry-run", "--scan"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("--source 'project/plan-incubation/covered note.md'", rendered)
            self.assertIn("--archive-to 'project/archive/reference/incubation/2026-05-26-covered note.md'", rendered)

    def test_scan_classifies_keep_active_followups_and_ambiguous_notes_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_incubation_source(
                root,
                body_extra="\n## Follow-up\n\n- [ ] Route the second thread.\n",
            )
            write_relationship_roadmap(root, source.relative_to(root).as_posix(), status="accepted")
            (root / "project/plan-incubation/loose.md").write_text(
                "---\n"
                'topic: "Loose"\n'
                'status: "incubating"\n'
                'created: "2026-05-01"\n'
                "---\n"
                "# Loose\n\n"
                "Unrouted idea.\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "memory-hygiene", "--dry-run", "--scan"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("incubation-cleanup-keep-active", rendered)
            self.assertIn("roadmap item 'relation-test' is accepted", rendered)
            self.assertIn("incubation-cleanup-followup-extraction", rendered)
            self.assertIn("unchecked task list item", rendered)
            self.assertIn("incubation-cleanup-ambiguous", rendered)
            self.assertIn("2 active incubation note(s)", rendered)

    def test_scan_keeps_meta_feedback_candidates_roadmap_detached_without_orphan_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / "project/plan-incubation/meta-feedback-note.md").write_text(
                "---\n"
                'topic: "meta feedback note"\n'
                'status: "incubating"\n'
                'source: "incubate cli"\n'
                "---\n"
                "# meta feedback note\n\n"
                "## Meta-feedback Cluster\n\n"
                "<!-- BEGIN mylittleharness-meta-feedback-cluster v1 -->\n"
                "- `canonical_id`: `meta-feedback-note`\n"
                "- `signal_type`: `operator-friction`\n"
                "<!-- END mylittleharness-meta-feedback-cluster v1 -->\n"
                "\n"
                "## Entries\n\n"
                "### 2026-05-01\n\n"
                "[MLH-Fix-Candidate]\n\n"
                "manual_step: keep this roadmap-detached until explicit promotion.\n\n"
                "### 2026-05-02\n\n"
                "[MLH-Fix-Candidate]\n\n"
                "manual_step: append another observation without forcing archive cleanup ceremony yet.\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "memory-hygiene", "--dry-run", "--scan"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("relationship-meta-feedback-candidate", rendered)
            self.assertIn("meta-feedback candidate is roadmap-detached operating memory", rendered)
            self.assertIn("incubation-cleanup-keep-active", rendered)
            self.assertIn("1 keep-active", rendered)
            self.assertNotIn("relationship-orphan-incubation", rendered)
            self.assertNotIn("relationship-entry-coverage-needed", rendered)
            self.assertNotIn("relationship-semantic-split-suggestion", rendered)
            self.assertNotIn("incubation-cleanup-ambiguous", rendered)

    def test_scan_warns_and_keeps_active_incubation_with_stale_implementation_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_incubation_source(
                root,
                frontmatter_extra=(
                    'archived_plan: "project/archive/plans/covered.md"\n'
                    'implemented_by: "project/archive/plans/covered.md"\n'
                ),
            )
            source_rel = source.relative_to(root).as_posix()
            write_relationship_roadmap(
                root,
                source_rel,
                status="accepted",
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "memory-hygiene", "--dry-run", "--scan"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("relationship-active-incubation-stale-implementation-tail", rendered)
            self.assertIn("active incubation status 'incubating' carries stale implementation tail field(s): archived_plan, implemented_by", rendered)
            self.assertIn("incubation-cleanup-keep-active", rendered)
            self.assertIn("cleanup blockers remain", rendered)
            self.assertNotIn("incubation-cleanup-archive-candidate", rendered)

    def test_terminal_entry_coverage_allows_stale_implementation_tail_archive_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_incubation_source(
                root,
                frontmatter_extra=(
                    'archived_plan: "project/archive/plans/covered.md"\n'
                    'implemented_by: "project/archive/plans/covered.md"\n'
                ),
                body_extra=(
                    "\n## Entry Coverage\n\n"
                    "- `2026-05-01`: `implemented` via project/archive/plans/covered.md\n"
                ),
            )
            write_relationship_roadmap(
                root,
                source.relative_to(root).as_posix(),
                status="done",
                archived_plan="project/archive/plans/covered.md",
                verification_summary="terminal coverage passed",
                docs_decision="updated",
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "memory-hygiene", "--dry-run", "--scan"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertNotIn("relationship-active-incubation-stale-implementation-tail", rendered)
            self.assertIn("incubation-cleanup-archive-candidate", rendered)
            self.assertIn("preview safe cleanup", rendered)

    def test_implemented_status_allows_stale_implementation_tail_archive_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_incubation_source(
                root,
                frontmatter_extra=(
                    'archived_plan: "project/archive/plans/covered.md"\n'
                    'implemented_by: "project/archive/plans/covered.md"\n'
                ),
            )
            source.write_text(source.read_text(encoding="utf-8").replace('status: "incubating"', 'status: "implemented"'), encoding="utf-8")
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "memory-hygiene", "--dry-run", "--scan"])

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertNotIn("relationship-active-incubation-stale-implementation-tail", rendered)
            self.assertIn("incubation-cleanup-archive-candidate", rendered)

    def test_intake_apply_writes_unambiguous_explicit_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            target = "project/plan-incubation/route-incoming-notes.md"

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "intake",
                        "--apply",
                        "--text",
                        "Future idea: route incoming notes before they become incubation clutter.",
                        "--title",
                        "Route Incoming Notes",
                        "--target",
                        target,
                    ]
                )

            self.assertEqual(code, 0)
            target_text = (root / target).read_text(encoding="utf-8")
            self.assertIn('title: "Route Incoming Notes"', target_text)
            self.assertIn('status: "incubating"', target_text)
            self.assertIn('route: "incubation"', target_text)
            self.assertIn('intake_source: "--text"', target_text)
            self.assertIn("# Route Incoming Notes", target_text)
            self.assertIn("Future idea: route incoming notes", target_text)
            rendered = output.getvalue()
            self.assertIn("intake-written", rendered)
            self.assertIn("classify input as incubation", rendered)
            self.assertIn("does not approve lifecycle movement", rendered)

    def test_archive_covered_writes_entry_coverage_and_archives_in_one_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_mixed_incubation_source(root)
            archive_rel = f"project/archive/reference/incubation/{date.today().isoformat()}-mixed-idea.md"

            dry_output = io.StringIO()
            before = snapshot_tree(root)
            with redirect_stdout(dry_output):
                dry_code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--dry-run",
                        "--source",
                        "project/plan-incubation/mixed-idea.md",
                        "--archive-covered",
                        "--entry-coverage",
                        "2026-05-01: implemented via project/archive/plans/first.md",
                        "--entry-coverage",
                        "2026-05-02: rejected out of scope",
                        "--repair-links",
                    ]
                )
            self.assertEqual(dry_code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("memory-hygiene-entry-coverage-plan", dry_output.getvalue())
            self.assertIn("memory-hygiene-archive-covered", dry_output.getvalue())

            apply_output = io.StringIO()
            with redirect_stdout(apply_output):
                apply_code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--apply",
                        "--source",
                        "project/plan-incubation/mixed-idea.md",
                        "--archive-covered",
                        "--entry-coverage",
                        "2026-05-01: implemented via project/archive/plans/first.md",
                        "--entry-coverage",
                        "2026-05-02: rejected out of scope",
                        "--repair-links",
                    ]
                )

            self.assertEqual(apply_code, 0)
            self.assertFalse(source.exists())
            archived_text = (root / archive_rel).read_text(encoding="utf-8")
            self.assertIn('status: "archived"', archived_text)
            self.assertIn("## Entry Coverage", archived_text)
            self.assertIn("- `2026-05-01`: `implemented` via project/archive/plans/first.md", archived_text)
            self.assertIn("- `2026-05-02`: `rejected` out of scope", archived_text)
            self.assertIn("memory-hygiene-archived", apply_output.getvalue())

    def test_archive_covered_invalid_entry_coverage_id_reports_valid_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            make_mixed_incubation_source(root)
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--dry-run",
                        "--source",
                        "project/plan-incubation/mixed-idea.md",
                        "--archive-covered",
                        "--entry-coverage",
                        "2026-05-03: implemented via project/archive/plans/missing.md",
                    ]
                )

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("memory-hygiene-refused", rendered)
            self.assertIn("entry coverage references unknown entry '2026-05-03'", rendered)
            self.assertIn("valid entry ids: `2026-05-01`, `2026-05-02`", rendered)
            self.assertIn('--entry-coverage "<entry-id>: implemented via <destination>"', rendered)

    def test_writeback_archives_multi_entry_incubation_when_entry_coverage_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp))
            source = make_mixed_incubation_source(
                root,
                coverage=(
                    "## Entry Coverage\n\n"
                    "- `2026-05-01`: `implemented` via `project/archive/plans/first.md`\n"
                    "- `2026-05-02`: `rejected` out of scope for this project\n"
                ),
            )
            source_rel = source.relative_to(root).as_posix()
            plan_path = root / "project/implementation-plan.md"
            plan_path.write_text(
                plan_path.read_text(encoding="utf-8").replace(
                    'status: "active"\n---',
                    f'status: "active"\nsource_incubation: "{source_rel}"\n---',
                ),
                encoding="utf-8",
            )
            write_relationship_roadmap(root, source_rel, status="active")
            (root / "project/project-state.md").write_text(
                (root / "project/project-state.md").read_text(encoding="utf-8").replace(
                    'phase_status: "in_progress"',
                    'phase_status: "complete"',
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--apply",
                        "--archive-active-plan",
                        "--roadmap-item",
                        "relation-test",
                        "--worktree-start-state",
                        "dirty test fixture",
                        "--task-scope",
                        "covered mixed incubation closeout",
                        "--docs-decision",
                        "updated",
                        "--state-writeback",
                        "archived active plan and covered source incubation",
                        "--verification",
                        "focused tests passed",
                        "--commit-decision",
                        "not staged",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertFalse(source.exists())
            archive_rel = f"project/archive/reference/incubation/{date.today().isoformat()}-mixed-idea.md"
            self.assertTrue((root / archive_rel).is_file())
            archived_text = (root / archive_rel).read_text(encoding="utf-8")
            self.assertIn('status: "implemented"', archived_text)
            self.assertIn("## Entry Coverage", archived_text)
            self.assertIn("writeback-incubation-auto-archive", output.getvalue())

    def test_roadmap_apply_writes_reciprocal_source_incubation_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_incubation_source(root)
            write_empty_roadmap(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "roadmap",
                        "--apply",
                        "--action",
                        "add",
                        "--item-id",
                        "relation-test",
                        "--title",
                        "Relation Test",
                        "--status",
                        "accepted",
                        "--order",
                        "10",
                        "--source-incubation",
                        source.relative_to(root).as_posix(),
                    ]
                )

            self.assertEqual(code, 0)
            source_text = source.read_text(encoding="utf-8")
            self.assertIn('related_roadmap: "project/roadmap.md"', source_text)
            self.assertIn('related_roadmap_item: "relation-test"', source_text)
            self.assertIn('promoted_to: "project/roadmap.md"', source_text)
            self.assertIn("roadmap-relationship-sync", output.getvalue())

    def test_roadmap_apply_replaces_malformed_source_incubation_list_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_incubation_source(
                root,
                frontmatter_extra=(
                    "related_roadmap:\n"
                    '- "project/archive/reference/old-roadmap.md"\n'
                    "related_roadmap_item:\n"
                    '- "old-item"\n'
                ),
            )
            write_empty_roadmap(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "roadmap",
                        "--apply",
                        "--action",
                        "add",
                        "--item-id",
                        "relation-test",
                        "--title",
                        "Relation Test",
                        "--status",
                        "accepted",
                        "--order",
                        "10",
                        "--source-incubation",
                        source.relative_to(root).as_posix(),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertIn("roadmap-relationship-sync", output.getvalue())
            source_text = source.read_text(encoding="utf-8")
            self.assertIn('related_roadmap: "project/roadmap.md"', source_text)
            self.assertIn('related_roadmap_item: "relation-test"', source_text)
            self.assertNotIn('old-roadmap.md"', source_text)
            self.assertEqual([], parse_frontmatter(source_text).errors)

    def test_roadmap_apply_rolls_back_roadmap_when_relationship_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_incubation_source(root)
            write_empty_roadmap(root)
            before = snapshot_tree(root)

            output = io.StringIO()
            failing_replace = fail_once_when_replace_targets(source)
            with patch("mylittleharness.atomic_files._replace_path", side_effect=failing_replace), redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "roadmap",
                        "--apply",
                        "--action",
                        "add",
                        "--item-id",
                        "relation-test",
                        "--title",
                        "Relation Test",
                        "--status",
                        "accepted",
                        "--order",
                        "10",
                        "--source-incubation",
                        source.relative_to(root).as_posix(),
                    ]
                )

            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("rolled back completed target writes", output.getvalue())

    def test_writeback_archives_fully_covered_single_entry_incubation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp))
            source = make_incubation_source(root)
            source_rel = source.relative_to(root).as_posix()
            plan_path = root / "project/implementation-plan.md"
            plan_path.write_text(
                plan_path.read_text(encoding="utf-8").replace(
                    'status: "active"\n---',
                    f'status: "active"\nsource_incubation: "{source_rel}"\n---',
                ),
                encoding="utf-8",
            )
            write_relationship_roadmap(root, source_rel, status="active")
            (root / "project/project-state.md").write_text(
                (root / "project/project-state.md").read_text(encoding="utf-8").replace(
                    'phase_status: "in_progress"',
                    'phase_status: "complete"',
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--apply",
                        "--archive-active-plan",
                        "--roadmap-item",
                        "relation-test",
                        "--worktree-start-state",
                        "dirty test fixture",
                        "--task-scope",
                        "relationship closeout",
                        "--docs-decision",
                        "updated",
                        "--state-writeback",
                        "archived active plan and source incubation",
                        "--verification",
                        "focused tests passed",
                        "--commit-decision",
                        "not staged",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertFalse(source.exists())
            archive_rel = f"project/archive/reference/incubation/{date.today().isoformat()}-idea.md"
            archived_source = root / archive_rel
            self.assertTrue(archived_source.is_file())
            archived_text = archived_source.read_text(encoding="utf-8")
            archived_plan = f"project/archive/plans/{date.today().isoformat()}-plan.md"
            self.assertIn('status: "implemented"', archived_text)
            self.assertIn(f'implemented_by: "{archived_plan}"', archived_text)
            self.assertIn('related_roadmap_item: "relation-test"', archived_text)
            self.assertFalse((root / "project/implementation-plan.md").exists())
            archived_plan_text = (root / archived_plan).read_text(encoding="utf-8")
            self.assertIn(f'source_incubation: "{archive_rel}"', archived_plan_text)
            roadmap_text = (root / "project/roadmap.md").read_text(encoding="utf-8")
            self.assertIn("- `status`: `done`", roadmap_text)
            self.assertIn(f"- `source_incubation`: `{archive_rel}`", roadmap_text)
            self.assertIn(f"- `related_plan`: `{archived_plan}`", roadmap_text)
            self.assertIn(f"- `archived_plan`: `{archived_plan}`", roadmap_text)
            self.assertIn("writeback-incubation-auto-archive", output.getvalue())

    def test_writeback_preserves_existing_archive_collision_with_explicit_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp))
            state_rel = "project/" + "project-state.md"
            plan_rel = "project/" + "implementation-plan.md"
            roadmap_rel = "project/" + "roadmap.md"
            archive_dir = "project/" + "archive/plans"
            (root / state_rel).write_text(
                (root / state_rel).read_text(encoding="utf-8").replace(
                    'phase_status: "in_progress"',
                    'phase_status: "complete"',
                ),
                encoding="utf-8",
            )
            write_relationship_roadmap(root, "", status="active")
            canonical_rel = f"{archive_dir}/{date.today().isoformat()}-plan.md"
            alternate_rel = f"{archive_dir}/{date.today().isoformat()}-plan-collision-2.md"
            canonical = root / canonical_rel
            canonical.parent.mkdir(parents=True, exist_ok=True)
            canonical.write_text("stale archive\n", encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--apply",
                        "--archive-active-plan",
                        "--on-archive-collision",
                        "preserve-existing",
                        "--roadmap-item",
                        "relation-test",
                        "--worktree-start-state",
                        "dirty test fixture",
                        "--task-scope",
                        "archive collision closeout",
                        "--docs-decision",
                        "not-needed",
                        "--state-writeback",
                        "archived active plan with preserved collision target",
                        "--verification",
                        "focused tests passed",
                        "--commit-decision",
                        "not staged",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual("stale archive\n", canonical.read_text(encoding="utf-8"))
            self.assertTrue((root / alternate_rel).is_file())
            self.assertFalse((root / plan_rel).exists())
            state_text = (root / state_rel).read_text(encoding="utf-8")
            roadmap_text = (root / roadmap_rel).read_text(encoding="utf-8")
            self.assertIn(f'last_archived_plan: "{alternate_rel}"', state_text)
            self.assertIn(f"- `related_plan`: `{alternate_rel}`", roadmap_text)
            self.assertIn(f"- `archived_plan`: `{alternate_rel}`", roadmap_text)
            self.assertIn("writeback-archive-collision-preserved", output.getvalue())

    def test_writeback_reuses_same_active_plan_archive_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp))
            state_rel = "project/" + "project-state.md"
            plan_rel = "project/" + "implementation-plan.md"
            roadmap_rel = "project/" + "roadmap.md"
            archive_dir = "project/" + "archive/plans"
            (root / state_rel).write_text(
                (root / state_rel).read_text(encoding="utf-8").replace(
                    'phase_status: "in_progress"',
                    'phase_status: "complete"',
                ),
                encoding="utf-8",
            )
            write_relationship_roadmap(root, "", status="active")
            canonical_rel = f"{archive_dir}/{date.today().isoformat()}-plan.md"
            alternate_rel = f"{archive_dir}/{date.today().isoformat()}-plan-collision-2.md"
            canonical = root / canonical_rel
            canonical.parent.mkdir(parents=True, exist_ok=True)
            canonical.write_text((root / plan_rel).read_text(encoding="utf-8"), encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--apply",
                        "--archive-active-plan",
                        "--roadmap-item",
                        "relation-test",
                        "--worktree-start-state",
                        "dirty test fixture",
                        "--task-scope",
                        "archive idempotency closeout",
                        "--docs-decision",
                        "not-needed",
                        "--state-writeback",
                        "completed closeout after same active plan archive already existed",
                        "--verification",
                        "focused tests passed",
                        "--commit-decision",
                        "not staged",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(canonical.is_file())
            self.assertFalse((root / alternate_rel).exists())
            self.assertFalse((root / plan_rel).exists())
            archived_text = canonical.read_text(encoding="utf-8")
            self.assertIn('status: "complete"', archived_text)
            self.assertIn("- status: `done`", archived_text)
            state_text = (root / state_rel).read_text(encoding="utf-8")
            roadmap_text = (root / roadmap_rel).read_text(encoding="utf-8")
            self.assertIn(f'last_archived_plan: "{canonical_rel}"', state_text)
            self.assertIn(f"- `related_plan`: `{canonical_rel}`", roadmap_text)
            self.assertIn(f"- `archived_plan`: `{canonical_rel}`", roadmap_text)
            rendered = output.getvalue()
            self.assertIn("writeback-archive-existing-target-reused", rendered)
            self.assertNotIn("writeback-archive-collision-preserved", rendered)

    def test_writeback_keeps_mixed_incubation_active_and_reports_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp))
            (root / "project/project-state.md").write_text(
                (root / "project/project-state.md").read_text(encoding="utf-8").replace(
                    'phase_status: "in_progress"',
                    'phase_status: "complete"',
                ),
                encoding="utf-8",
            )
            source = make_incubation_source(
                root,
                frontmatter_extra='open_threads:\n  - "second idea remains open"\n',
                body_extra="\n## Open Questions\n\n- [ ] Decide the second idea.\n",
            )
            source_rel = source.relative_to(root).as_posix()
            write_relationship_roadmap(root, source_rel, status="active")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--apply",
                        "--archive-active-plan",
                        "--roadmap-item",
                        "relation-test",
                        "--worktree-start-state",
                        "dirty test fixture",
                        "--task-scope",
                        "relationship closeout",
                        "--docs-decision",
                        "updated",
                        "--state-writeback",
                        "archived active plan only",
                        "--verification",
                        "focused tests passed",
                        "--commit-decision",
                        "not staged",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(source.is_file())
            source_text = source.read_text(encoding="utf-8")
            self.assertIn('implemented_by: "project/archive/plans/', source_text)
            self.assertNotIn('status: "implemented"', source_text)
            self.assertFalse((root / f"project/archive/reference/incubation/{date.today().isoformat()}-idea.md").exists())
            self.assertIn("writeback-incubation-archive-blocked", output.getvalue())

    def test_writeback_refuses_multiline_closeout_field_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp))
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "writeback", "--apply", "--verification", "line one\nline two"])

            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("--verification is a one-line closeout field", output.getvalue())


def make_live_root(root: Path) -> Path:
    (root / ".codex").mkdir(parents=True)
    (root / "project/specs/workflow").mkdir(parents=True)
    (root / "project/plan-incubation").mkdir(parents=True)
    (root / "project/research").mkdir(parents=True)
    (root / ".codex/project-workflow.toml").write_text(
        'workflow = "workflow-core"\nversion = 1\n\n[memory]\nstate_file = "project/project-state.md"\nplan_file = "project/implementation-plan.md"\n',
        encoding="utf-8",
    )
    (root / "project/project-state.md").write_text(
        '---\nproject: "Sample"\nworkflow: "workflow-core"\noperating_mode: "ad_hoc"\nplan_status: "none"\nactive_plan: ""\n---\n# Sample Project State\n',
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (root / "README.md").write_text("# Sample\n", encoding="utf-8")
    (root / "project/specs/workflow/workflow-memory-routing-spec.md").write_text("# Routing Spec\n", encoding="utf-8")
    workflow_dir = root / "project" / "specs" / "workflow"
    (workflow_dir / "workflow-memory-routing-spec.md").write_text(
        "---\n"
        'spec_status: "draft"\n'
        'implementation_posture: "target-only"\n'
        "---\n"
        "# Routing Spec\n",
        encoding="utf-8",
    )
    return root


def make_active_live_root(root: Path) -> Path:
    make_live_root(root)
    state = root / "project/project-state.md"
    state.write_text(
        state.read_text(encoding="utf-8").replace(
            'operating_mode: "ad_hoc"\nplan_status: "none"\nactive_plan: ""',
            (
                'operating_mode: "plan"\n'
                'plan_status: "active"\n'
                'active_plan: "project/implementation-plan.md"\n'
                'active_phase: "phase-1"\n'
                'phase_status: "in_progress"'
            ),
        ),
        encoding="utf-8",
    )
    (root / "project/implementation-plan.md").write_text(
        "---\n"
        'title: "Plan"\n'
        'status: "active"\n'
        "---\n"
        "# Plan\n\n"
        "## phase-1\n\n"
        "- status: `in_progress`\n",
        encoding="utf-8",
    )
    return root


def make_product_fixture_root(root: Path) -> Path:
    make_live_root(root)
    state = root / "project/project-state.md"
    state.write_text(
        state.read_text(encoding="utf-8").replace(
            'workflow: "workflow-core"\n',
            'root_role: "product-source"\nfixture_status: "product-compatibility-fixture"\nworkflow: "workflow-core"\n',
        ),
        encoding="utf-8",
    )
    return root


def make_research_source(root: Path) -> Path:
    path = root / "project/research/raw-import.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        'status: "imported"\n'
        'topic: "raw import"\n'
        'created: "2026-05-01"\n'
        "---\n"
        "# Raw Import\n\n"
        "Raw imported notes.\n",
        encoding="utf-8",
    )
    return path


def make_incubation_source(root: Path, frontmatter_extra: str = "", body_extra: str = "") -> Path:
    path = root / "project/plan-incubation/idea.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        'topic: "Idea"\n'
        'status: "incubating"\n'
        'created: "2026-05-01"\n'
        f"{frontmatter_extra}"
        "---\n"
        "# Idea\n\n"
        "## Entries\n\n"
        "### 2026-05-01\n\n"
        "Implement one relationship idea.\n"
        f"{body_extra}",
        encoding="utf-8",
    )
    return path


def make_mixed_incubation_source(root: Path, coverage: str = "") -> Path:
    path = root / "project/plan-incubation/mixed-idea.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    coverage_section = f"\n{coverage.rstrip()}\n" if coverage else ""
    path.write_text(
        "---\n"
        'topic: "Mixed Idea"\n'
        'status: "incubating"\n'
        'created: "2026-05-01"\n'
        "---\n"
        "# Mixed Idea\n\n"
        "## Entries\n\n"
        "### 2026-05-01\n\n"
        "Implemented relationship idea.\n\n"
        "### 2026-05-02\n\n"
        "Second idea needs a separate fate.\n"
        f"{coverage_section}",
        encoding="utf-8",
    )
    return path


def write_empty_roadmap(root: Path) -> None:
    (root / "project/roadmap.md").write_text(
        "---\n"
        'id: "memory-routing-roadmap"\n'
        'status: "active"\n'
        "---\n"
        "# Roadmap\n\n"
        "## Items\n\n"
        "### Existing Item\n\n"
        "- `id`: `existing-item`\n"
        "- `status`: `accepted`\n"
        "- `order`: `1`\n"
        "- `dependencies`: `[]`\n"
        "- `source_incubation`: ``\n"
        "- `related_plan`: ``\n"
        "- `archived_plan`: ``\n"
        "- `verification_summary`: ``\n"
        "- `docs_decision`: `uncertain`\n"
        "- `carry_forward`: ``\n"
        "- `supersedes`: `[]`\n"
        "- `superseded_by`: `[]`\n\n",
        encoding="utf-8",
    )


def write_relationship_roadmap(
    root: Path,
    source_incubation: str,
    *,
    status: str,
    archived_plan: str = "",
    verification_summary: str = "",
    docs_decision: str = "uncertain",
) -> None:
    (root / "project/roadmap.md").write_text(
        "---\n"
        'id: "memory-routing-roadmap"\n'
        'status: "active"\n'
        "---\n"
        "# Roadmap\n\n"
        "## Items\n\n"
        "### Relation Test\n\n"
        "- `id`: `relation-test`\n"
        f"- `status`: `{status}`\n"
        "- `order`: `10`\n"
        "- `dependencies`: `[]`\n"
        f"- `source_incubation`: `{source_incubation}`\n"
        "- `related_plan`: `project/implementation-plan.md`\n"
        f"- `archived_plan`: `{archived_plan}`\n"
        f"- `verification_summary`: `{verification_summary}`\n"
        f"- `docs_decision`: `{docs_decision}`\n"
        "- `carry_forward`: ``\n"
        "- `supersedes`: `[]`\n"
        "- `superseded_by`: `[]`\n\n",
        encoding="utf-8",
    )


def snapshot_tree(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel_path = path.relative_to(root).as_posix()
        snapshot[rel_path] = "<dir>" if path.is_dir() else path.read_text(encoding="utf-8")
    return snapshot


def fail_once_when_replace_targets(target_path: Path):
    original_replace = atomic_files._replace_path
    state = {"failed": False}

    def replace(source: Path, target: Path) -> None:
        if not state["failed"] and target == target_path:
            state["failed"] = True
            raise OSError("injected replace failure")
        original_replace(source, target)

    return replace


if __name__ == "__main__":
    unittest.main()
