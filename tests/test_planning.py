from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.inventory import load_inventory
from mylittleharness.planning import make_plan_request, plan_dry_run_findings, render_implementation_plan
from mylittleharness.roadmap import RoadmapSliceContract, RoadmapSynthesisReport


class PlanningTests(unittest.TestCase):
    def test_renderer_emits_required_frontmatter_and_sections(self) -> None:
        request = make_plan_request(
            "Plan Synthesis Rail",
            "Create deterministic implementation plans for live roots.",
            "Preserve explicit task input.",
        )
        rendered = render_implementation_plan(request, today=date(2026, 5, 1))

        for expected in (
            'plan_id: "2026-05-01-plan-synthesis-rail"',
            'title: "Plan Synthesis Rail"',
            'status: "pending"',
            'active_phase: "phase-1-implementation"',
            'phase_status: "pending"',
            'docs_decision: "uncertain"',
            'execution_policy: "current-phase-only"',
            "auto_continue: false",
            "stop_conditions:",
            'closeout_boundary: "explicit-closeout-required"',
            "# Plan Synthesis Rail",
            "## Objective",
            "## Explicit Task Input",
            "## Authority Inputs",
            "## Non-goals",
            "## Invariants",
            "## Execution Policy",
            "## File Ownership",
            "## Phases",
            "## Verification Strategy",
            "## Docs Decision",
            "## State Transfer",
            "## Refusal Conditions",
            "## Closeout Checklist",
            "## Decision Log",
        ):
            self.assertIn(expected, rendered)

    def test_renderer_defaults_docs_decision_to_uncertain(self) -> None:
        rendered = render_implementation_plan(
            make_plan_request("Docs Decision", "Track docs posture.", None),
            today=date(2026, 5, 1),
        )

        self.assertIn('docs_decision: "uncertain"', rendered)
        self.assertIn("- docs_decision: uncertain", rendered)

    def test_renderer_defaults_to_current_phase_only_execution_policy(self) -> None:
        rendered = render_implementation_plan(
            make_plan_request("Phase Policy", "Make phase continuation explicit.", None),
            today=date(2026, 5, 1),
        )

        self.assertIn('execution_policy: "current-phase-only"', rendered)
        self.assertIn("auto_continue: false", rendered)
        self.assertIn("stop_conditions:", rendered)
        self.assertIn("default continuation: execute only `phase-1-implementation`", rendered)
        self.assertIn("verification failed", rendered)
        self.assertIn("write scope", rendered)
        self.assertIn("explicit closeout preparation", rendered)

    def test_renderer_defaults_do_not_contain_destructive_rollback_commands(self) -> None:
        rendered = render_implementation_plan(
            make_plan_request("Safe Recovery", "Keep recovery bounded.", None),
            today=date(2026, 5, 1),
        ).casefold()

        for forbidden in (
            "git reset --hard",
            "git checkout --",
            "git restore .",
            "git clean -fd",
            "rm -rf",
            "remove-item -recurse",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_renderer_decomposes_roadmap_plan_when_artifact_pressure_exists(self) -> None:
        request = make_plan_request(
            "Generated Plan Phase Synthesis",
            "Create meaningful generated plan phases.",
            "Use roadmap metadata.",
            roadmap_item="generated-plan-phase-synthesis",
        )
        contract = RoadmapSliceContract(
            primary_roadmap_item="generated-plan-phase-synthesis",
            execution_slice="generated-plan-phase-synthesis",
            slice_goal="Synthesize meaningful phases.",
            covered_roadmap_items=("generated-plan-phase-synthesis",),
            domain_context="Synthesize meaningful phases.",
            target_artifacts=(
                "src/mylittleharness/planning.py",
                "src/mylittleharness/grain.py",
                "tests/test_planning.py",
                "tests/test_cli.py",
                "project/specs/workflow/workflow-plan-synthesis-spec.md",
                "src/mylittleharness/templates/workflow/workflow-plan-synthesis-spec.md",
            ),
            execution_policy="current-phase-only",
            closeout_boundary="explicit implementation plan closeout only",
            source_incubation="project/plan-incubation/generated-plan-phase-synthesis-gap.md",
            source_research="project/research/2026-05-02-plan-roadmap-hygiene-cross-distillate.md",
            related_specs=("project/specs/workflow/workflow-plan-synthesis-spec.md",),
        )
        report = RoadmapSynthesisReport(
            primary_roadmap_item="generated-plan-phase-synthesis",
            execution_slice="generated-plan-phase-synthesis",
            covered_roadmap_items=("generated-plan-phase-synthesis",),
            domain_contexts=("Synthesize meaningful phases.",),
            target_artifacts=contract.target_artifacts,
            related_specs=contract.related_specs,
            source_inputs=(contract.source_incubation, contract.source_research),
            bundle_signals=("no shared slice signals beyond the requested roadmap item",),
            split_signals=("bundle/split output is advisory and cannot approve lifecycle movement",),
            in_slice_dependencies=(),
            verification_summary_count=1,
            target_artifact_pressure="6 target artifacts across 1 roadmap item; report-only sizing signal, not a hard gate",
            phase_pressure="1 domain context and 1 verification summary; candidate plan outline: 3 phases or explicit one-shot rationale",
        )

        rendered = render_implementation_plan(request, today=date(2026, 5, 1), slice_contract=contract, synthesis_report=report)

        self.assertIn("### Phase Outline", rendered)
        self.assertIn("### phase-1-implementation", rendered)
        self.assertIn("### phase-2-verification-and-docs", rendered)
        self.assertIn("### phase-3-integration-and-state-transfer", rendered)
        self.assertIn(
            "- write_scope: `src/mylittleharness/planning.py`, `src/mylittleharness/grain.py`, `tests/test_planning.py`, `tests/test_cli.py`",
            rendered,
        )
        self.assertIn("python -m unittest tests.test_planning tests.test_cli", rendered)
        self.assertIn("current-phase-only execution", rendered)
        self.assertNotIn("Generated as one explicit current phase", rendered)

    def test_renderer_carries_discovery_packet_source_member_as_read_context_only(self) -> None:
        request = make_plan_request(
            "Discovery Packet Read Context",
            "Use discovery packet evidence without promoting it to plan authority.",
            None,
            roadmap_item="discovery-packet-read-context",
        )
        packet_rel = "project/research/allowed-discovery-packet.md"
        contract = RoadmapSliceContract(
            primary_roadmap_item="discovery-packet-read-context",
            execution_slice="discovery-packet-read-context",
            slice_goal="Carry source member evidence as read context.",
            covered_roadmap_items=("discovery-packet-read-context",),
            domain_context="Carry source member evidence as read context.",
            target_artifacts=("src/mylittleharness/planning.py", "tests/test_planning.py"),
            execution_policy="current-phase-only",
            closeout_boundary="explicit closeout/writeback only",
            source_incubation="",
            source_research="",
            related_specs=(),
            source_members=(packet_rel,),
        )
        report = RoadmapSynthesisReport(
            primary_roadmap_item="discovery-packet-read-context",
            execution_slice="discovery-packet-read-context",
            covered_roadmap_items=("discovery-packet-read-context",),
            domain_contexts=("Carry source member evidence as read context.",),
            target_artifacts=contract.target_artifacts,
            related_specs=(),
            source_inputs=contract.source_members,
            bundle_signals=("shared source inputs: project/research/allowed-discovery-packet.md",),
            split_signals=("bundle/split output is advisory and cannot approve lifecycle movement",),
            in_slice_dependencies=(),
            verification_summary_count=1,
            target_artifact_pressure="2 target artifacts across 1 roadmap item; report-only sizing signal, not a hard gate",
            phase_pressure="1 domain context and 1 verification summary; candidate plan outline: 3 phases or explicit one-shot rationale",
        )

        rendered = render_implementation_plan(request, today=date(2026, 5, 1), slice_contract=contract, synthesis_report=report)

        self.assertIn(f"`{packet_rel}`", rendered)
        self.assertIn("- read_context:", rendered)
        self.assertNotIn("source_members:", rendered)

    def test_plan_dry_run_refuses_ready_discovery_packet_without_source_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            packet_rel = "project/research/hashless-discovery-packet.md"
            packet_path = root / packet_rel
            packet_path.parent.mkdir(parents=True, exist_ok=True)
            packet_path.write_text(
                "---\n"
                'schema: "mylittleharness.discovery-packet.v1"\n'
                'status: "research-ready"\n'
                'discovery_status: "ready-for-plan"\n'
                'quality_status: "sufficient-for-planning"\n'
                'planning_reliance: "allowed"\n'
                "source_refs:\n"
                '  - "project/research/repo-research.md"\n'
                "---\n"
                "# Hashless Discovery Packet\n",
                encoding="utf-8",
            )
            (root / "project/roadmap.md").write_text(
                "# Roadmap\n\n"
                "## Items\n\n"
                "### Hashless Discovery Packet Plan\n\n"
                "- `id`: `hashless-discovery-packet-plan`\n"
                "- `status`: `accepted`\n"
                "- `order`: `10`\n"
                "- `execution_slice`: `hashless-discovery-packet-plan`\n"
                f"- `source_research`: `{packet_rel}`\n"
                "- `target_artifacts`: `[\"src/mylittleharness/planning.py\", \"tests/test_planning.py\"]`\n"
                "- `verification_summary`: `Discovery packet source hashes must gate plan opening.`\n",
                encoding="utf-8",
            )

            findings = plan_dry_run_findings(
                load_inventory(root),
                make_plan_request(None, None, None, roadmap_item="hashless-discovery-packet-plan"),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertFalse((root / "project/implementation-plan.md").exists())
            self.assertIn("plan-roadmap-source-evidence-refused", rendered)
            self.assertIn("research quality gate blocks planning", rendered)
            self.assertIn("requires source_hashes for source/evidence refs", rendered)

    def test_plan_dry_run_anchors_shared_source_excerpt_to_requested_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source_rel = "project/plan-incubation/thread-sweep-addendum.md"
            source_path = root / source_rel
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(
                "---\n"
                'topic: "thread sweep addendum"\n'
                "---\n"
                "# Thread Sweep\n\n"
                "[MLH-Fix-Candidate] Shared addendum packet for multiple candidates.\n\n"
                "Classification intent before roadmap promotion:\n\n"
                "- A1 Plan Synthesis Can Bind Neighboring Candidate Context: anchor to candidate ids and source lines.\n"
                "- A2 Roadmap Relationship Vocabulary Is Too Opaque: explain legal relationship fields.\n",
                encoding="utf-8",
            )
            (root / "project/roadmap.md").write_text(
                "# Roadmap\n\n"
                "## Items\n\n"
                "### Addendum A1\n\n"
                "- `id`: `operator-friction-a01-plan-synthesis-source-anchoring`\n"
                "- `status`: `accepted`\n"
                "- `order`: `10`\n"
                "- `execution_slice`: `operator-friction-a01-plan-synthesis-source-anchoring`\n"
                "- `slice_goal`: `Anchor plan synthesis to candidate ids.`\n"
                "- `slice_members`: `[\"operator-friction-a01-plan-synthesis-source-anchoring\"]`\n"
                "- `dependencies`: `[]`\n"
                f"- `source_incubation`: `{source_rel}`\n"
                "- `target_artifacts`: `[\"project/project-state.md\"]`\n"
                "- `verification_summary`: `Dry-run should not bind neighboring candidate prose.`\n"
                "- `candidate_numbers`: `A1`\n",
                encoding="utf-8",
            )

            findings = plan_dry_run_findings(
                load_inventory(root),
                make_plan_request(
                    None,
                    None,
                    None,
                    roadmap_item="operator-friction-a01-plan-synthesis-source-anchoring",
                    only_requested_item=True,
                ),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("candidate task:", rendered)
            self.assertIn("A1 Plan Synthesis Can Bind Neighboring Candidate Context", rendered)
            self.assertIn(f"source_anchor: {source_rel}:", rendered)
            self.assertNotIn("A2 Roadmap Relationship Vocabulary Is Too Opaque", rendered)

    def test_renderer_includes_docs_scope_when_docs_decision_will_be_updated(self) -> None:
        request = make_plan_request(
            "Docs Scope",
            "Make docs impact executable.",
            None,
            roadmap_item="docs-scope",
            only_requested_item=True,
        )
        contract = RoadmapSliceContract(
            primary_roadmap_item="docs-scope",
            execution_slice="docs-scope",
            slice_goal="Update plan synthesis docs impact.",
            covered_roadmap_items=("docs-scope",),
            domain_context="Update plan synthesis docs impact.",
            target_artifacts=("src/mylittleharness/planning.py",),
            execution_policy="current-phase-only",
            closeout_boundary="explicit closeout/writeback only",
            source_incubation="",
            source_research="",
            related_specs=("project/specs/workflow/workflow-plan-synthesis-spec.md",),
        )
        report = RoadmapSynthesisReport(
            primary_roadmap_item="docs-scope",
            execution_slice="docs-scope",
            covered_roadmap_items=("docs-scope",),
            domain_contexts=("Update plan synthesis docs impact.",),
            target_artifacts=contract.target_artifacts,
            related_specs=contract.related_specs,
            source_inputs=(),
            bundle_signals=("only requested roadmap item was selected; roadmap slice siblings are not batched",),
            split_signals=("bundle/split output is advisory and cannot approve lifecycle movement",),
            in_slice_dependencies=(),
            verification_summary_count=0,
            target_artifact_pressure="1 target artifact across 1 roadmap item; report-only sizing signal, not a hard gate",
            phase_pressure="1 domain context and 0 verification summaries and 1 docs update decision; candidate plan outline: 2 phases or explicit one-shot rationale",
            docs_update_count=1,
        )

        rendered = render_implementation_plan(request, today=date(2026, 5, 1), slice_contract=contract, synthesis_report=report)

        self.assertIn("### phase-2-verification-and-docs", rendered)
        self.assertIn("- write_scope: `project/specs/workflow/workflow-plan-synthesis-spec.md`", rendered)
        self.assertIn("record `updated` when specs/templates/docs change", rendered)

    def test_renderer_records_one_shot_rationale_for_low_pressure_roadmap_plan(self) -> None:
        request = make_plan_request(
            "Tiny Plan",
            "Create a small roadmap-backed plan.",
            None,
            roadmap_item="tiny-plan",
            only_requested_item=True,
        )
        contract = RoadmapSliceContract(
            primary_roadmap_item="tiny-plan",
            execution_slice="tiny-plan",
            slice_goal="Touch one product source file.",
            covered_roadmap_items=("tiny-plan",),
            domain_context="Touch one product source file.",
            target_artifacts=("src/mylittleharness/planning.py",),
            execution_policy="current-phase-only",
            closeout_boundary="explicit closeout/writeback only",
            source_incubation="",
            source_research="",
            related_specs=(),
        )
        report = RoadmapSynthesisReport(
            primary_roadmap_item="tiny-plan",
            execution_slice="tiny-plan",
            covered_roadmap_items=("tiny-plan",),
            domain_contexts=("Touch one product source file.",),
            target_artifacts=contract.target_artifacts,
            related_specs=(),
            source_inputs=(),
            bundle_signals=("only requested roadmap item was selected; roadmap slice siblings are not batched",),
            split_signals=("bundle/split output is advisory and cannot approve lifecycle movement",),
            in_slice_dependencies=(),
            verification_summary_count=0,
            target_artifact_pressure="1 target artifact across 1 roadmap item; report-only sizing signal, not a hard gate",
            phase_pressure="1 domain context and 0 verification summaries; candidate plan outline: 1 phase or explicit one-shot rationale",
        )

        rendered = render_implementation_plan(request, today=date(2026, 5, 1), slice_contract=contract, synthesis_report=report)

        self.assertIn("### One-Shot Rationale", rendered)
        self.assertIn("Generated as one explicit current phase", rendered)
        self.assertIn("### phase-1-implementation", rendered)
        self.assertNotIn("### phase-2-verification-and-docs", rendered)

    def test_renderer_quotes_test_targets_in_verification_gate(self) -> None:
        request = make_plan_request(
            "Quoted Test Gate",
            "Render safe verification command text.",
            None,
            roadmap_item="quoted-test-gate",
        )
        contract = RoadmapSliceContract(
            primary_roadmap_item="quoted-test-gate",
            execution_slice="quoted-test-gate",
            slice_goal="Quote test target paths.",
            covered_roadmap_items=("quoted-test-gate",),
            domain_context="Quote test target paths.",
            target_artifacts=("src/mylittleharness/planning.py", "tests/test command.py"),
            execution_policy="current-phase-only",
            closeout_boundary="explicit closeout/writeback only",
            source_incubation="",
            source_research="",
            related_specs=(),
        )
        report = RoadmapSynthesisReport(
            primary_roadmap_item="quoted-test-gate",
            execution_slice="quoted-test-gate",
            covered_roadmap_items=("quoted-test-gate",),
            domain_contexts=("Quote test target paths.",),
            target_artifacts=contract.target_artifacts,
            related_specs=(),
            source_inputs=(),
            bundle_signals=("only requested roadmap item was selected; roadmap slice siblings are not batched",),
            split_signals=("bundle/split output is advisory and cannot approve lifecycle movement",),
            in_slice_dependencies=(),
            verification_summary_count=0,
            target_artifact_pressure="2 target artifacts across 1 roadmap item; report-only sizing signal, not a hard gate",
            phase_pressure="1 domain context and 0 verification summaries; candidate plan outline: 2 phases or explicit one-shot rationale",
        )

        rendered = render_implementation_plan(request, today=date(2026, 5, 1), slice_contract=contract, synthesis_report=report)

        self.assertIn("python -m unittest discover -s tests", rendered)
        self.assertNotIn("pytest", rendered)


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


if __name__ == "__main__":
    unittest.main()
