from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.inventory import load_inventory
from mylittleharness.research_intake import (
    discovery_packet_apply_findings,
    discovery_packet_dry_run_findings,
    make_discovery_packet_request,
    make_research_import_request,
    research_import_apply_findings,
    research_import_dry_run_findings,
)
from mylittleharness.research_distill import research_distill_quality_problem


class ResearchIntakeTests(unittest.TestCase):
    def test_dry_run_reports_target_hash_and_non_authority_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            request = make_research_import_request(
                "Deep Research Import",
                "Verdict: preserve source boundaries.",
                source_label="external deep research",
                related_prompt="project/research/prompt-packet.md",
            )

            findings = research_import_dry_run_findings(load_inventory(root), request)

            self.assertEqual(before, snapshot_tree(root))
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-import-dry-run", rendered)
            self.assertIn(f"project/research/{date.today().isoformat()}-deep-research-import.md", rendered)
            self.assertIn("imported text sha256=", rendered)
            self.assertIn("imported research is durable provenance", rendered)
            self.assertFalse((root / "project/research").exists())

    def test_apply_writes_one_imported_research_artifact_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            request = make_research_import_request(
                "Deep Research Import",
                "## Findings\n\nThe result is evidence, not authority.",
                text_source="--text-file project/raw/deep-research.md",
                target="project/research/deep-research-import.md",
                topic="Deep Research",
                source_label="manual Google Docs export",
                related_prompt="project/research/prompt-packet.md",
            )

            findings = research_import_apply_findings(load_inventory(root), request)

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-import-written", rendered)
            self.assertIn("research-import-route-write", rendered)
            after = snapshot_tree(root)
            changed = [rel for rel in after if before.get(rel) != after.get(rel)]
            self.assertEqual(["project/research/deep-research-import.md"], changed)

            text = (root / "project/research/deep-research-import.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"))
            self.assertIn('status: "imported"', text)
            self.assertIn('topic: "Deep Research"', text)
            self.assertIn('derived_from: "manual Google Docs export"', text)
            self.assertIn('  - "project/research/prompt-packet.md"', text)
            self.assertIn("imported_text sha256=", text)
            self.assertNotIn("superseded_by:", text)
            self.assertIn("The result is evidence, not authority.", text)
            self.assertIn("It does not promote findings to stable specs", text)

    def test_apply_writes_source_members_and_hashes_for_research_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source_rel = "project/plan-incubation/source-note.md"
            source_path = root / source_rel
            source_path.parent.mkdir(parents=True)
            source_path.write_text("# Source\n\nReviewed source note.\n", encoding="utf-8")

            findings = research_import_apply_findings(
                load_inventory(root),
                make_research_import_request(
                    "Source Bound Import",
                    "Imported synthesis.",
                    target="project/research/source-bound-import.md",
                    source_members=(source_rel,),
                ),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-import-written", rendered)
            text = (root / "project/research/source-bound-import.md").read_text(encoding="utf-8")
            self.assertIn("source_members:\n", text)
            self.assertIn(f'  - "{source_rel}"', text)
            self.assertIn(f"- source_members: `{source_rel}`", text)
            self.assertIn(f"{source_rel} sha256=", text)

    def test_apply_from_attachment_writes_research_handoff_with_attachment_source_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            attachment_rel = "project/attachments/vendor-proposals/2026-06-02-mts-internet/artifact.md"
            attachment_dir = root / "project/attachments/vendor-proposals/2026-06-02-mts-internet"
            attachment_dir.mkdir(parents=True)
            (attachment_dir / "original.pdf").write_text("%PDF\nproposal\n", encoding="utf-8")
            (root / attachment_rel).write_text(
                "---\n"
                'type: "attachment"\n'
                'kind: "vendor-proposal"\n'
                'status: "imported"\n'
                'title: "MTS internet commercial proposal"\n'
                'source_file: "original.pdf"\n'
                'mime_type: "application/pdf"\n'
                'sha256: "placeholder"\n'
                "size_bytes: 14\n"
                'received_at: "2026-06-02"\n'
                'source: "email attachment"\n'
                'authority: "binary is source evidence; this md card is metadata authority"\n'
                "---\n"
                "# Attachment\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)

            findings = research_import_apply_findings(
                load_inventory(root),
                make_research_import_request(
                    "MTS Proposal Review",
                    "",
                    text_source=f"--from-attachment {attachment_rel}",
                    target="project/research/mts-proposal-review.md",
                    source_attachment=attachment_rel,
                ),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-import-written", rendered)
            self.assertIn("research-import-source-attachment", rendered)
            after = snapshot_tree(root)
            changed = [rel for rel in after if before.get(rel) != after.get(rel)]
            self.assertEqual(["project/research/mts-proposal-review.md"], changed)
            text = (root / "project/research/mts-proposal-review.md").read_text(encoding="utf-8")
            self.assertIn("source_attachments:", text)
            self.assertIn(f'  - "{attachment_rel}"', text)
            self.assertIn(f"- Source attachment: `{attachment_rel}`", text)
            self.assertIn(f"{attachment_rel} sha256=", text)
            self.assertIn("project/attachments/vendor-proposals/2026-06-02-mts-internet/original.pdf sha256=", text)
            self.assertIn("Review the binary source evidence and sidecar metadata", text)

    def test_apply_refuses_product_fixture_unsafe_target_and_existing_file_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            product_root = make_product_root(Path(tmp) / "product")
            before = snapshot_tree(product_root)
            findings = research_import_apply_findings(
                load_inventory(product_root),
                make_research_import_request("Import", "Research text."),
            )
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(product_root))
            self.assertIn("product-source compatibility fixture", rendered)

        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            findings = research_import_apply_findings(
                load_inventory(root),
                make_research_import_request("Import", "Research text.", target="project/plan-incubation/import.md"),
            )
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("target must be under project/research/*.md", rendered)

        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            existing = root / "project/research/import.md"
            existing.parent.mkdir(parents=True)
            existing.write_text("existing\n", encoding="utf-8")
            before = snapshot_tree(root)
            findings = research_import_apply_findings(
                load_inventory(root),
                make_research_import_request("Import", "Research text.", target="project/research/import.md"),
            )
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("target research artifact already exists", rendered)

    def test_adopt_existing_dry_run_reports_target_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            target = root / "project/research/plain.md"
            target.parent.mkdir(parents=True)
            target.write_text("# Plain\n\nExisting research body.\n", encoding="utf-8")
            before = snapshot_tree(root)

            findings = research_import_dry_run_findings(
                load_inventory(root),
                make_research_import_request(
                    None,
                    None,
                    target="project/research/plain.md",
                    adopt_existing=True,
                ),
            )

            self.assertEqual(before, snapshot_tree(root))
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-import-dry-run", rendered)
            self.assertIn("research-import-adopt-existing-source-hash", rendered)
            self.assertIn("research-import-adopt-existing-metadata", rendered)
            self.assertIn("research-import-adopt-existing-route-write", rendered)

    def test_adopt_existing_apply_prepends_frontmatter_and_preserves_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            target = root / "project/research/plain.md"
            target.parent.mkdir(parents=True)
            body = "# Plain\n\nExisting research body.\n"
            target.write_text(body, encoding="utf-8")
            before = snapshot_tree(root)

            findings = research_import_apply_findings(
                load_inventory(root),
                make_research_import_request(
                    None,
                    None,
                    target="project/research/plain.md",
                    adopt_existing=True,
                ),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-import-adopt-existing-written", rendered)
            self.assertIn("research-import-adopt-existing-route-write", rendered)
            after = snapshot_tree(root)
            changed = [rel for rel in after if before.get(rel) != after.get(rel)]
            self.assertEqual(["project/research/plain.md"], changed)
            text = target.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"))
            self.assertIn('status: "imported"', text)
            self.assertIn('adoption_mode: "existing-target"', text)
            self.assertIn('derived_from: "existing project/research artifact"', text)
            self.assertIn("pre_adoption_file sha256=", text)
            self.assertTrue(text.endswith(body))

    def test_adopt_existing_is_idempotent_for_valid_research_frontmatter(self) -> None:
        cases = (
            ("imported.md", "imported"),
            ("ready.md", "ready-for-implementation"),
            ("accepted.md", "accepted"),
        )
        for name, status in cases:
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as tmp:
                    root = make_live_root(Path(tmp))
                    target = root / "project/research" / name
                    target.parent.mkdir(parents=True)
                    target.write_text(f"---\nstatus: \"{status}\"\n---\n# Imported\n", encoding="utf-8")
                    before = snapshot_tree(root)

                    findings = research_import_apply_findings(
                        load_inventory(root),
                        make_research_import_request(
                            None,
                            None,
                            target=f"project/research/{name}",
                            adopt_existing=True,
                        ),
                    )

                    rendered = "\n".join(finding.render() for finding in findings)
                    self.assertEqual(before, snapshot_tree(root))
                    self.assertIn("research-import-adopt-existing-already-route-visible", rendered)
                    self.assertNotIn("research-import-adopt-existing-route-write", rendered)

    def test_adopt_existing_repairs_missing_source_members_when_explicit_refs_are_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source_rel = "project/verification/source-evidence.md"
            source_path = root / source_rel
            source_path.parent.mkdir(parents=True)
            source_path.write_text("# Evidence\n", encoding="utf-8")
            target = root / "project/research/imported.md"
            target.parent.mkdir(parents=True)
            body = "# Imported\n\nExisting route-visible body.\n"
            target.write_text("---\nstatus: \"imported\"\ntitle: \"Imported\"\n---\n" + body, encoding="utf-8")
            before = snapshot_tree(root)

            findings = research_import_apply_findings(
                load_inventory(root),
                make_research_import_request(
                    None,
                    None,
                    target="project/research/imported.md",
                    adopt_existing=True,
                    source_members=(source_rel,),
                ),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-import-adopt-existing-source-members-repaired", rendered)
            self.assertIn("research-import-adopt-existing-route-write", rendered)
            changed = [rel for rel, text in snapshot_tree(root).items() if before.get(rel) != text]
            self.assertEqual(["project/research/imported.md"], changed)
            text = target.read_text(encoding="utf-8")
            self.assertIn("source_members:\n", text)
            self.assertIn(f'  - "{source_rel}"', text)
            self.assertTrue(text.endswith(body))

    def test_adopt_existing_is_noop_when_source_members_are_already_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source_rel = "project/verification/source-evidence.md"
            source_path = root / source_rel
            source_path.parent.mkdir(parents=True)
            source_path.write_text("# Evidence\n", encoding="utf-8")
            target = root / "project/research/imported.md"
            target.parent.mkdir(parents=True)
            target.write_text(
                "---\n"
                'status: "imported"\n'
                'title: "Imported"\n'
                "source_members:\n"
                f'  - "{source_rel}"\n'
                "---\n"
                "# Imported\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)

            findings = research_import_apply_findings(
                load_inventory(root),
                make_research_import_request(
                    None,
                    None,
                    target="project/research/imported.md",
                    adopt_existing=True,
                    source_members=(source_rel,),
                ),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("research-import-adopt-existing-already-route-visible", rendered)
            self.assertNotIn("research-import-adopt-existing-source-members-repaired", rendered)
            self.assertNotIn("research-import-adopt-existing-route-write", rendered)

    def test_adopt_existing_refuses_malformed_or_nonresearch_frontmatter_without_writes(self) -> None:
        cases = (
            ("bad.md", "---\nstatus: \"imported\"\n- dangling\n---\n# Bad\n", "frontmatter is malformed"),
            ("wrong.md", "---\nstatus: \"triaged\"\n---\n# Wrong\n", "no recognized research status"),
        )
        for name, text, expected in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as tmp:
                    root = make_live_root(Path(tmp))
                    target = root / "project/research" / name
                    target.parent.mkdir(parents=True)
                    target.write_text(text, encoding="utf-8")
                    before = snapshot_tree(root)

                    findings = research_import_apply_findings(
                        load_inventory(root),
                        make_research_import_request(
                            None,
                            None,
                            target=f"project/research/{name}",
                            adopt_existing=True,
                        ),
                    )

                    rendered = "\n".join(finding.render() for finding in findings)
                    self.assertEqual(before, snapshot_tree(root))
                    self.assertIn(expected, rendered)

    def test_discovery_packet_dry_run_reports_source_bound_packet_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = root / "project/research/repo-review.md"
            evidence = root / "project/verification/readiness.md"
            source.parent.mkdir(parents=True)
            evidence.parent.mkdir(parents=True)
            source.write_text("# Repo Review\n\n- Discovery evidence is source-bound.\n", encoding="utf-8")
            evidence.write_text("# Readiness\n\n- Verification remains pending.\n", encoding="utf-8")
            before = snapshot_tree(root)
            request = make_discovery_packet_request(
                "Plan Readiness",
                source_refs=("project/research/repo-review.md",),
                evidence_refs=("project/verification/readiness.md",),
                open_questions=("Which source gaps remain?",),
            )

            findings = discovery_packet_dry_run_findings(load_inventory(root), request)

            self.assertEqual(before, snapshot_tree(root))
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("discover-dry-run", rendered)
            self.assertIn(f"project/research/{date.today().isoformat()}-plan-readiness-discovery-packet.md", rendered)
            self.assertIn("discover-quality-gate", rendered)
            self.assertIn("planning_reliance=blocked", rendered)
            self.assertIn("discover-route-write", rendered)
            self.assertFalse((root / f"project/research/{date.today().isoformat()}-plan-readiness-discovery-packet.md").exists())

    def test_discovery_packet_apply_writes_ready_packet_when_gates_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = root / "project/research/repo-review.md"
            source.parent.mkdir(parents=True)
            source.write_text("# Repo Review\n\n- Discovery evidence is source-bound.\n", encoding="utf-8")
            before = snapshot_tree(root)
            request = make_discovery_packet_request(
                "Plan Readiness",
                goal="Decide whether the next plan can consume the reviewed repo evidence.",
                target="project/research/plan-readiness-discovery-packet.md",
                quality_status="sufficient-for-planning",
                planning_reliance="allowed",
                discovery_status="ready-for-plan",
                source_refs=("project/research/repo-review.md",),
                selected_option="Open the bounded implementation plan.",
                rationale="All source refs are present and reviewed.",
            )

            findings = discovery_packet_apply_findings(load_inventory(root), request)

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("discover-written", rendered)
            self.assertIn("discover-route-write", rendered)
            after = snapshot_tree(root)
            changed = [rel for rel in after if before.get(rel) != after.get(rel)]
            self.assertEqual(["project/research/plan-readiness-discovery-packet.md"], changed)
            text = (root / "project/research/plan-readiness-discovery-packet.md").read_text(encoding="utf-8")
            self.assertIn('schema: "mylittleharness.discovery-packet.v1"', text)
            self.assertIn('source_type: "pre-plan-discovery-packet"', text)
            self.assertIn('quality_status: "sufficient-for-planning"', text)
            self.assertIn('planning_reliance: "allowed"', text)
            self.assertIn('  - "project/research/repo-review.md"', text)
            self.assertIn("discovery packet is source-bound pre-plan evidence", text)
            self.assertIn("It does not run research, call providers", text)
            self.assertEqual("", research_distill_quality_problem("project/research/plan-readiness-discovery-packet.md", text))

    def test_discovery_packet_refuses_unbound_or_misaligned_ready_packets_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            findings = discovery_packet_apply_findings(
                load_inventory(root),
                make_discovery_packet_request(
                    "Draft Packet",
                    quality_status="sufficient-for-planning",
                    planning_reliance="allowed",
                    discovery_status="draft",
                    source_refs=("project/research/missing.md",),
                ),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("discovery_status=draft", rendered)
            self.assertIn("planning_reliance=blocked", rendered)
            self.assertIn("allowed discovery packets require existing source/evidence refs", rendered)

        with tempfile.TemporaryDirectory() as tmp:
            product_root = make_product_root(Path(tmp) / "product")
            source = product_root / "project/research/repo-review.md"
            source.parent.mkdir(parents=True)
            source.write_text("# Source\n", encoding="utf-8")
            before = snapshot_tree(product_root)
            findings = discovery_packet_apply_findings(
                load_inventory(product_root),
                make_discovery_packet_request("Product Fixture Packet", source_refs=("project/research/repo-review.md",)),
            )
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(product_root))
            self.assertIn("product-source compatibility fixture", rendered)

    def test_discovery_packet_refuses_unsafe_and_unknown_ready_evidence_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = root / "project/research/repo-review.md"
            link = root / "project/research/repo-review-link.md"
            source.parent.mkdir(parents=True)
            source.write_text("# Repo Review\n\n- Discovery evidence is source-bound.\n", encoding="utf-8")
            try:
                link.symlink_to(source)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlinks are unavailable in this environment: {exc}")
            before = snapshot_tree(root)

            findings = discovery_packet_apply_findings(
                load_inventory(root),
                make_discovery_packet_request(
                    "Unsafe Packet",
                    quality_status="sufficient-for-planning",
                    planning_reliance="allowed",
                    discovery_status="ready-for-plan",
                    source_refs=("project/research/repo-review-link.md",),
                ),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("unsafe source/evidence ref", rendered)
            self.assertIn("crosses symlink inside root", rendered)
            self.assertIn("discover-refused", rendered)

        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = root / "project/research/repo-review.md"
            source.parent.mkdir(parents=True)
            source.write_text("# Repo Review\n\n- Discovery evidence is source-bound.\n", encoding="utf-8")
            before = snapshot_tree(root)

            findings = discovery_packet_apply_findings(
                load_inventory(root),
                make_discovery_packet_request(
                    "Unknown Status Packet",
                    quality_status="sufficient-for-planning",
                    planning_reliance="allowed",
                    discovery_status="triaged",
                    source_refs=("project/research/repo-review.md",),
                ),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("--discovery-status must be ready-for-plan, blocked, contested, or draft", rendered)
            self.assertIn("discover-refused", rendered)


def make_live_root(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".codex").mkdir()
    (root / "project").mkdir()
    (root / ".codex/project-workflow.toml").write_text(
        'workflow = "workflow-core"\n'
        "version = 1\n\n"
        "[memory]\n"
        'state_file = "project/project-state.md"\n'
        'plan_file = "project/implementation-plan.md"\n',
        encoding="utf-8",
    )
    (root / "project/project-state.md").write_text(
        "---\n"
        'project: "Sample"\n'
        'workflow: "workflow-core"\n'
        'operating_mode: "plan"\n'
        'plan_status: "none"\n'
        'active_plan: ""\n'
        "---\n"
        "# Sample\n",
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("# Contract\n", encoding="utf-8")
    return root


def make_product_root(root: Path) -> Path:
    make_live_root(root)
    state = root / "project/project-state.md"
    state.write_text(state.read_text(encoding="utf-8").replace('workflow: "workflow-core"\n', 'workflow: "workflow-core"\nroot_role: "product-source"\n'), encoding="utf-8")
    return root


def snapshot_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


if __name__ == "__main__":
    unittest.main()
