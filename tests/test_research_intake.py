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
    make_research_import_request,
    research_import_apply_findings,
    research_import_dry_run_findings,
)


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
