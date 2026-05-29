from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.inventory import load_inventory
from mylittleharness.research_distill import (
    distill_research_text,
    make_research_distill_request,
    research_distill_apply_findings,
    research_distill_dry_run_findings,
    research_distill_quality_problem,
)


SAMPLE_RESEARCH = """---
status: "imported"
title: "Deep Research Import"
derived_from: "project/research/raw-google-doc.md"
related_artifacts:
  - "project/research/prompt-packet.md"
---
# Deep Research Import

## Candidate MLH Improvements

- [MLH-Fix-Candidate] Add exact provenance checks to `project/plan-incubation/provenance-gap.md`.
- Candidate route: `src/mylittleharness/checks.py`

## Open Questions

- How should `project/roadmap.md` mark unresolved research gaps?
- Risk: source confidence is still unknown.

## Recommended Next Move

- Promote only after explicit review through `project/roadmap.md`.
"""

QUALITY_RESEARCH = """---
status: "imported"
title: "Deep Research Import"
derived_from: "project/research/raw-google-doc.md"
---
# Deep Research Import

## Gate Coverage

- Gate: roadmap acceptance requires source-bound claims, contradiction notes, and explicit confidence before planning.

## Source-Bound Claims

- Claim: The source says shallow distillates hide whether roadmap questions were answered.

## Confidence And Uncertainty

- Confidence: medium because the source names the failure mode directly.
- Uncertainty: exact linter wording remains implementation-owned.

## Candidate MLH Improvements

- Add a research distill quality gate to `src/mylittleharness/research_distill.py`.
"""

DISCOVERY_PACKET = """---
schema: "mylittleharness.discovery-packet.v1"
status: "research-ready"
discovery_status: "ready-for-plan"
quality_status: "sufficient-for-planning"
planning_reliance: "allowed"
source_refs:
  - "project/research/repo-research.md"
source_members:
  - "project/research/risk-review.md"
roles:
  repo_researcher:
    status: "complete"
    evidence_refs:
      - "project/research/repo-research.md"
---
# Discovery Packet

## Gate Coverage

- Gate: roadmap and plan synthesis require source-bound claims, uncertainty, and explicit planning reliance.

## Source-Bound Claims

- Claim: The repo research identifies discovery packets as evidence records under `project/research/*.md`.

## Confidence And Uncertainty

- Confidence: high because the packet names the MLH routes and source evidence.
- Uncertainty: future writer commands remain optional and out of this profile.
"""

MISALIGNED_DISCOVERY_PACKET = """---
schema: "mylittleharness.discovery-packet.v1"
status: "research-ready"
discovery_status: "draft"
quality_status: "sufficient-for-planning"
planning_reliance: "allowed"
---
# Draft Discovery Packet

## Gate Coverage

- Gate: draft packets must not be treated as ready planning evidence.

## Source-Bound Claims

- Claim: This packet is still draft.

## Confidence And Uncertainty

- Uncertainty: draft status remains unresolved.
"""

MISSING_GATE_DISCOVERY_PACKET = """---
schema: "mylittleharness.discovery-packet.v1"
status: "research-ready"
discovery_status: "ready-for-plan"
---
# Discovery Packet
"""

PROVISIONAL_DISCOVERY_PACKET = """---
schema: "mylittleharness.discovery-packet.v1"
status: "research-ready"
discovery_status: "blocked"
quality_status: "provisional"
planning_reliance: "blocked"
quality_gate_issues:
  - "source review is incomplete"
---
# Blocked Discovery Packet
"""


class ResearchDistillTests(unittest.TestCase):
    def test_distill_extracts_candidates_gaps_source_links_and_route_proposals(self) -> None:
        extraction = distill_research_text("project/research/deep-research-import.md", SAMPLE_RESEARCH)

        self.assertTrue(any("Add exact provenance checks" in item for item in extraction.accepted_candidates))
        self.assertTrue(any("source confidence is still unknown" in item for item in extraction.unresolved_gaps))
        self.assertIn("project/research/deep-research-import.md", extraction.source_links)
        self.assertIn("project/research/raw-google-doc.md", extraction.source_links)
        self.assertIn("project/research/prompt-packet.md", extraction.source_links)
        self.assertIn("project/plan-incubation/provenance-gap.md", extraction.route_proposals)
        self.assertIn("src/mylittleharness/checks.py", extraction.route_proposals)
        self.assertIn("project/roadmap.md", extraction.route_proposals)
        self.assertEqual("provisional", extraction.quality.quality_status)
        self.assertEqual("blocked", extraction.quality.planning_reliance)
        self.assertIn("missing gate-question coverage matrix", extraction.quality.quality_gate_issues)

    def test_distill_quality_allows_reviewed_gate_coverage_shape(self) -> None:
        extraction = distill_research_text("project/research/deep-research-import.md", QUALITY_RESEARCH)

        self.assertEqual("sufficient-for-planning", extraction.quality.quality_status)
        self.assertEqual("allowed", extraction.quality.planning_reliance)
        self.assertTrue(extraction.quality.gate_coverage)
        self.assertTrue(extraction.quality.source_bound_claims)
        self.assertTrue(extraction.quality.confidence_notes)

    def test_discovery_packet_profile_uses_existing_quality_gate_vocabulary(self) -> None:
        extraction = distill_research_text("project/research/discovery-packet.md", DISCOVERY_PACKET)

        self.assertEqual("sufficient-for-planning", extraction.quality.quality_status)
        self.assertEqual("allowed", extraction.quality.planning_reliance)
        self.assertIn("project/research/repo-research.md", extraction.source_links)
        self.assertIn("project/research/risk-review.md", extraction.source_links)
        self.assertEqual("", research_distill_quality_problem("project/research/discovery-packet.md", DISCOVERY_PACKET))

    def test_discovery_packet_profile_blocks_missing_or_misaligned_gate(self) -> None:
        misaligned = research_distill_quality_problem("project/research/draft-discovery-packet.md", MISALIGNED_DISCOVERY_PACKET)
        missing = research_distill_quality_problem("project/research/missing-gate-discovery-packet.md", MISSING_GATE_DISCOVERY_PACKET)

        self.assertIn("discovery_status=draft", misaligned)
        self.assertIn("planning_reliance=blocked", misaligned)
        self.assertIn("discovery packet requires quality_status and planning_reliance", missing)

    def test_discovery_packet_profile_preserves_provisional_blocker_issue(self) -> None:
        problem = research_distill_quality_problem("project/research/blocked-discovery-packet.md", PROVISIONAL_DISCOVERY_PACKET)

        self.assertIn("provisional/blocked", problem)
        self.assertIn("source review is incomplete", problem)

    def test_dry_run_reports_distillate_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = write_source(root)
            before = snapshot_tree(root)
            request = make_research_distill_request(str(source.relative_to(root)).replace("\\", "/"))

            findings = research_distill_dry_run_findings(load_inventory(root), request)

            self.assertEqual(before, snapshot_tree(root))
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-distill-dry-run", rendered)
            self.assertIn("research-distill-source-hash", rendered)
            self.assertIn("research-distill-extraction", rendered)
            self.assertIn("research-distill-quality-gate", rendered)
            self.assertIn("accepted_candidates=", rendered)
            self.assertIn("route_proposals=", rendered)
            self.assertFalse((root / "project/research/deep-research-import-distillate.md").exists())

    def test_apply_writes_one_distilled_research_artifact_with_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = write_source(root)
            before = snapshot_tree(root)
            request = make_research_distill_request(
                str(source.relative_to(root)).replace("\\", "/"),
                target="project/research/deep-research-import-distillate.md",
                topic="Deep Research",
            )

            findings = research_distill_apply_findings(load_inventory(root), request)

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-distill-written", rendered)
            self.assertIn("research-distill-route-write", rendered)
            after = snapshot_tree(root)
            changed = [rel for rel in after if before.get(rel) != after.get(rel)]
            self.assertEqual(["project/research/deep-research-import-distillate.md"], changed)

            text = (root / "project/research/deep-research-import-distillate.md").read_text(encoding="utf-8")
            self.assertIn('status: "distilled"', text)
            self.assertIn('derived_from: "project/research/deep-research-import.md"', text)
            self.assertIn('quality_status: "provisional"', text)
            self.assertIn('planning_reliance: "blocked"', text)
            self.assertIn("## Quality Gate", text)
            self.assertIn("missing gate-question coverage matrix", text)
            self.assertIn("## Accepted Candidates", text)
            self.assertIn("Add exact provenance checks", text)
            self.assertIn("## Unresolved Gaps", text)
            self.assertIn("source confidence is still unknown", text)
            self.assertIn("## Route Proposals", text)
            self.assertIn("project/roadmap.md", text)
            self.assertIn("Promotion requires a later explicit lifecycle command", text)
            self.assertIn("provisional/blocked", research_distill_quality_problem("project/research/deep-research-import-distillate.md", text))

    def test_quality_problem_is_empty_for_sufficient_distillate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = write_source(root, text=QUALITY_RESEARCH)
            request = make_research_distill_request(
                str(source.relative_to(root)).replace("\\", "/"),
                target="project/research/deep-research-import-distillate.md",
            )

            research_distill_apply_findings(load_inventory(root), request)

            text = (root / "project/research/deep-research-import-distillate.md").read_text(encoding="utf-8")
            self.assertIn('quality_status: "sufficient-for-planning"', text)
            self.assertIn('planning_reliance: "allowed"', text)
            self.assertEqual("", research_distill_quality_problem("project/research/deep-research-import-distillate.md", text))

    def test_apply_refuses_product_fixture_unsafe_source_and_existing_target_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            product_root = make_product_root(Path(tmp) / "product")
            source = write_source(product_root)
            before = snapshot_tree(product_root)
            findings = research_distill_apply_findings(
                load_inventory(product_root),
                make_research_distill_request(str(source.relative_to(product_root)).replace("\\", "/")),
            )
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(product_root))
            self.assertIn("product-source compatibility fixture", rendered)

        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            findings = research_distill_apply_findings(
                load_inventory(root),
                make_research_distill_request("project/plan-incubation/source.md", target="project/research/out.md"),
            )
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("source must be under project/research/*.md", rendered)

        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = write_source(root)
            existing = root / "project/research/out.md"
            existing.write_text("existing\n", encoding="utf-8")
            before = snapshot_tree(root)
            findings = research_distill_apply_findings(
                load_inventory(root),
                make_research_distill_request(str(source.relative_to(root)).replace("\\", "/"), target="project/research/out.md"),
            )
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("target research artifact already exists", rendered)


def write_source(root: Path, text: str = SAMPLE_RESEARCH) -> Path:
    source = root / "project/research/deep-research-import.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    return source


def make_live_root(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".codex").mkdir()
    (root / "project").mkdir()
    (root / "project/research").mkdir()
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
