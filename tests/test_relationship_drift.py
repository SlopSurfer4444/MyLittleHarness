from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.cli import main
from mylittleharness.inventory import EXPECTED_SPEC_NAMES


class RelationshipDriftTests(unittest.TestCase):
    def test_dry_run_then_apply_retargets_done_item_related_plan_to_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source_rel = "project/plan-incubation/closed.md"
            archive_rel = "project/archive/plans/2026-05-10-closed.md"
            write_source(root, source_rel, related_plan="project/implementation-plan.md")
            (root / archive_rel).parent.mkdir(parents=True, exist_ok=True)
            (root / archive_rel).write_text("# Archived Plan\n", encoding="utf-8")
            write_roadmap(
                root,
                related_plan="project/implementation-plan.md",
                archived_plan=archive_rel,
                source_incubation=source_rel,
            )

            before = (root / "project/roadmap.md").read_text(encoding="utf-8")
            dry_code, dry_rendered = run_cli(root, "relationship-drift", "--dry-run", "--roadmap-item", "closed-work")
            self.assertEqual(dry_code, 0)
            self.assertEqual(before, (root / "project/roadmap.md").read_text(encoding="utf-8"))
            self.assertIn("relationship-drift-graph-before", dry_rendered)
            self.assertIn("relationship-drift-graph-after", dry_rendered)
            self.assertIn("would retarget closed-work.related_plan", dry_rendered)
            self.assertIn("does not approve closeout, archive, roadmap promotion", dry_rendered)

            apply_code, apply_rendered = run_cli(root, "relationship-drift", "--apply", "--roadmap-item", "closed-work")
            self.assertEqual(apply_code, 0)
            self.assertIn("relationship-drift-written", apply_rendered)
            roadmap_text = (root / "project/roadmap.md").read_text(encoding="utf-8")
            source_text = (root / source_rel).read_text(encoding="utf-8")
            self.assertIn(f"- `related_plan`: `{archive_rel}`", roadmap_text)
            self.assertIn(f'related_plan: "{archive_rel}"', source_text)
            self.assertIn(f'archived_plan: "{archive_rel}"', source_text)
            self.assertFalse((root / "project/implementation-plan.md.relationship-drift.backup").exists())

    def test_apply_refuses_missing_archived_plan_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source_rel = "project/plan-incubation/closed.md"
            write_source(root, source_rel, related_plan="project/implementation-plan.md")
            write_roadmap(
                root,
                related_plan="project/implementation-plan.md",
                archived_plan="project/archive/plans/missing.md",
                source_incubation=source_rel,
            )
            before = snapshot(root)

            dry_code, dry_rendered = run_cli(root, "relationship-drift", "--dry-run", "--roadmap-item", "closed-work")
            self.assertEqual(dry_code, 0)
            self.assertIn("relationship-drift-missing-route-impact", dry_rendered)
            self.assertIn("would block apply", dry_rendered)

            apply_code, apply_rendered = run_cli(root, "relationship-drift", "--apply", "--roadmap-item", "closed-work")
            self.assertEqual(apply_code, 2)
            self.assertIn("relationship-drift-missing-route-impact", apply_rendered)
            self.assertIn("refuse apply", apply_rendered)
            self.assertEqual(before, snapshot(root))

    def test_apply_adds_reciprocal_source_metadata_for_active_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp), active_item="active-work")
            source_rel = "project/plan-incubation/active.md"
            write_source(root, source_rel)
            write_roadmap(
                root,
                item_id="active-work",
                title="Active Work",
                status="accepted",
                related_plan="",
                archived_plan="",
                source_incubation=source_rel,
            )

            apply_code, apply_rendered = run_cli(root, "relationship-drift", "--apply", "--roadmap-item", "active-work")
            self.assertEqual(apply_code, 0)
            self.assertIn("relationship-drift-source-metadata", apply_rendered)
            roadmap_text = (root / "project/roadmap.md").read_text(encoding="utf-8")
            source_text = (root / source_rel).read_text(encoding="utf-8")
            self.assertIn("- `related_plan`: `project/implementation-plan.md`", roadmap_text)
            self.assertIn('related_roadmap: "project/roadmap.md"', source_text)
            self.assertIn('related_roadmap_item: "active-work"', source_text)
            self.assertIn('related_plan: "project/implementation-plan.md"', source_text)

    def test_apply_does_not_treat_source_members_as_reciprocal_source_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp), active_item="active-work")
            source_rel = "project/plan-incubation/member.md"
            write_source(root, source_rel)
            write_roadmap(
                root,
                item_id="active-work",
                title="Active Work",
                status="accepted",
                related_plan="",
                archived_plan="",
                source_incubation="",
                source_members=(source_rel,),
            )

            apply_code, apply_rendered = run_cli(root, "relationship-drift", "--apply", "--roadmap-item", "active-work")
            self.assertEqual(apply_code, 0)
            self.assertNotIn("relationship-drift-source-metadata", apply_rendered)
            roadmap_text = (root / "project/roadmap.md").read_text(encoding="utf-8")
            source_text = (root / source_rel).read_text(encoding="utf-8")
            self.assertIn("- `related_plan`: `project/implementation-plan.md`", roadmap_text)
            self.assertNotIn("related_roadmap", source_text)
            self.assertNotIn("related_roadmap_item", source_text)
            self.assertNotIn("promoted_to", source_text)
            self.assertNotIn("related_plan", source_text)


def run_cli(root: Path, *args: str) -> tuple[int, str]:
    output = io.StringIO()
    with redirect_stdout(output):
        code = main(["--root", str(root), *args])
    return code, output.getvalue()


def make_live_root(root: Path, *, active_item: str = "") -> Path:
    (root / ".codex").mkdir(parents=True)
    (root / "project/specs/workflow").mkdir(parents=True)
    (root / "project/archive/plans").mkdir(parents=True)
    (root / ".codex/project-workflow.toml").write_text(
        'workflow = "workflow-core"\nversion = 1\n\n[memory]\nstate_file = "project/project-state.md"\nplan_file = "project/implementation-plan.md"\n',
        encoding="utf-8",
    )
    plan_status = "active" if active_item else "none"
    active_plan = "project/implementation-plan.md" if active_item else ""
    (root / "project/project-state.md").write_text(
        "---\n"
        'project: "Sample"\n'
        'workflow: "workflow-core"\n'
        f'operating_mode: "{"plan" if active_item else "ad_hoc"}"\n'
        f'plan_status: "{plan_status}"\n'
        f'active_plan: "{active_plan}"\n'
        "---\n"
        "# Sample Project State\n",
        encoding="utf-8",
    )
    if active_item:
        (root / "project/implementation-plan.md").write_text(
            "---\n"
            'plan_id: "active-plan"\n'
            f'related_roadmap_item: "{active_item}"\n'
            "covered_roadmap_items:\n"
            f'  - "{active_item}"\n'
            "---\n"
            "# Active Plan\n",
            encoding="utf-8",
        )
    (root / "README.md").write_text("# Sample\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    for name in EXPECTED_SPEC_NAMES:
        (root / "project/specs/workflow" / name).write_text(f"# {name}\n", encoding="utf-8")
    return root


def write_source(root: Path, rel_path: str, *, related_plan: str = "") -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    relationship_line = f'related_plan: "{related_plan}"\n' if related_plan else ""
    path.write_text(
        "---\n"
        'status: "accepted"\n'
        f"{relationship_line}"
        "---\n"
        "# Source\n",
        encoding="utf-8",
    )


def write_roadmap(
    root: Path,
    *,
    item_id: str = "closed-work",
    title: str = "Closed Work",
    status: str = "done",
    related_plan: str,
    archived_plan: str,
    source_incubation: str,
    source_members: tuple[str, ...] = (),
) -> None:
    source_members_value = "[" + ", ".join(f'"{member}"' for member in source_members) + "]" if source_members else "[]"
    (root / "project/roadmap.md").write_text(
        "---\n"
        'id: "memory-routing-roadmap"\n'
        'status: "active"\n'
        "---\n"
        "# Roadmap\n\n"
        "## Items\n\n"
        f"### {title}\n\n"
        f"- `id`: `{item_id}`\n"
        f"- `status`: `{status}`\n"
        "- `order`: `1`\n"
        f"- `execution_slice`: `{item_id}`\n"
        "- `slice_goal`: `Exercise relationship drift.`\n"
        f"- `slice_members`: `[\"{item_id}\"]`\n"
        "- `slice_dependencies`: `[]`\n"
        "- `slice_closeout_boundary`: `explicit lifecycle only`\n"
        "- `dependencies`: `[]`\n"
        f"- `source_incubation`: `{source_incubation}`\n"
        "- `source_research`: ``\n"
        f"- `source_members`: `{source_members_value}`\n"
        "- `related_specs`: `[]`\n"
        f"- `related_plan`: `{related_plan}`\n"
        f"- `archived_plan`: `{archived_plan}`\n"
        "- `target_artifacts`: `[]`\n"
        "- `verification_summary`: `Focused relationship drift regression.`\n"
        "- `docs_decision`: `not-needed`\n"
        "- `carry_forward`: `None.`\n"
        "- `supersedes`: `[]`\n"
        "- `superseded_by`: `[]`\n"
        "\n",
        encoding="utf-8",
    )


def snapshot(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rows[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return rows


if __name__ == "__main__":
    unittest.main()
