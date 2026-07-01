from __future__ import annotations

from argparse import Namespace
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from mylittleharness import cli as cli_module
from mylittleharness.cli import main
from mylittleharness.hooks import HOOK_PRE_TOOL_USE, hook_event_payload
from mylittleharness.inventory import load_inventory
from mylittleharness.writeback import _legal_dry_run_command_problem
from tests.test_cli import (
    _fan_in_gate_writeback_args,
    _write_fan_in_coordination_evidence,
    _write_fan_in_gate_plan,
    make_active_live_root,
    make_operating_root,
    make_product_diff_scope_fixture,
)


class ReleaseLifecycleUxTests(unittest.TestCase):
    def test_next_state_legal_dry_run_uses_argv_semantics(self) -> None:
        safe_command = (
            'mylittleharness --root . writeback --dry-run '
            '--residual-risk "later prose may mention --apply after review"'
        )
        self.assertEqual("", _legal_dry_run_command_problem(safe_command))
        self.assertEqual(
            "",
            _legal_dry_run_command_problem(
                "python -m mylittleharness --root . transition --dry-run --archive-active-plan"
            ),
        )
        self.assertEqual(
            "",
            _legal_dry_run_command_problem("& mylittleharness --root . writeback --dry-run"),
        )
        self.assertEqual(
            "legal-dry-run-command must not include --apply",
            _legal_dry_run_command_problem("mylittleharness --root . writeback --dry-run --apply"),
        )
        self.assertIn(
            "one bounded MLH dry-run command",
            _legal_dry_run_command_problem("mylittleharness --root . writeback --dry-run; git status"),
        )
        self.assertIn(
            "must start with mylittleharness",
            _legal_dry_run_command_problem("echo mylittleharness --root . writeback --dry-run"),
        )
        self.assertIn(
            "must start with mylittleharness",
            _legal_dry_run_command_problem("Write-Output mylittleharness --root . writeback --dry-run"),
        )
        self.assertIn(
            "one bounded MLH dry-run command",
            _legal_dry_run_command_problem("mylittleharness --root . writeback --dry-run $(Set-Content x y)"),
        )

    def test_hook_allows_route_payload_product_root_reference_but_blocks_direct_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, product_root = make_product_diff_scope_fixture(Path(tmp))
            product_ref = (product_root / "src" / "mylittleharness" / "hooks.py").as_posix()
            route_command = (
                "mylittleharness --root . evidence --record --dry-run "
                "--record-id product-root-reference --role coder --actor codex --task task "
                "--assigned-scope scope --runtime local-shell --worktree-id wt "
                "--status succeeded --stop-reason done --attempt-budget 1/1 "
                "--output-ref project/verification/agent-runs/product-root-reference.md "
                f'--residual-risk "legal route payload mentions {product_ref} as evidence context"'
            )
            direct_edit_command = f"Set-Content -LiteralPath {product_ref} '# bypass'"

            route_payload = hook_event_payload(
                load_inventory(root),
                HOOK_PRE_TOOL_USE,
                [],
                json.dumps({"toolName": "shell_command", "command": route_command, "workdir": str(root)}),
            )
            direct_edit_payload = hook_event_payload(
                load_inventory(root),
                HOOK_PRE_TOOL_USE,
                [],
                json.dumps({"toolName": "shell_command", "command": direct_edit_command, "workdir": str(root)}),
            )

            route_codes = {finding["code"] for finding in route_payload["findings"]}
            direct_edit_codes = {finding["code"] for finding in direct_edit_payload["findings"]}
            self.assertFalse(route_payload["block"])
            self.assertIn("hooks-policy-allow-mlh-owner-route-evidence-paths", route_codes)
            self.assertNotIn("hooks-policy-block-product-root-path", route_codes)
            self.assertNotIn("hooks-policy-block-product-root-direct-edit", route_codes)
            self.assertTrue(direct_edit_payload["block"])
            self.assertIn("hooks-policy-block-product-root-path", direct_edit_codes)
            self.assertIn("hooks-policy-block-product-root-direct-edit", direct_edit_codes)

    def test_hook_unresolved_powershell_splat_emits_literal_route_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            command = (
                "$argsList = @('--root', '.', 'writeback', $mode, '--residual-risk', 'none')\n"
                "$mode = '--dry-run'\n"
                "mylittleharness @argsList"
            )

            payload = hook_event_payload(
                load_inventory(root),
                HOOK_PRE_TOOL_USE,
                [],
                json.dumps({"toolName": "shell_command", "command": command, "workdir": str(root)}),
            )

            codes = {finding["code"] for finding in payload["findings"]}
            messages = "\n".join(str(finding["message"]) for finding in payload["findings"])
            self.assertTrue(payload["block"])
            self.assertIn("hooks-policy-block-unresolved-powershell-mlh-splat", codes)
            self.assertIn("visible literal command", messages)
            self.assertIn("mylittleharness --root <root> <route> --dry-run", messages)
            self.assertIn("direct product-source mutation is still refused", messages)
            self.assertIn("hooks-policy-block-mlh-mutation-without-mode", codes)

    def test_fan_in_guidance_creates_missing_records_before_final_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="pending")
            _write_fan_in_gate_plan(root, fan_in_required=True)
            args = _fan_in_gate_writeback_args(root)
            command = [*args[:3], "--dry-run", *args[3:]]

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(command), 0)
            rendered = output.getvalue()

            self.assertIn("Next safe fan-in command sequence", rendered)
            claim_create = rendered.index("claim --dry-run --action create")
            handoff_create = rendered.index("handoff --dry-run --action create")
            handoff_accept = rendered.index("handoff --dry-run --action accept --handoff-id <handoff-id>")
            claim_release = rendered.index("claim --dry-run --action release --claim-id <claim-id>")
            evidence_record = rendered.index("evidence --record --dry-run")
            self.assertLess(claim_create, handoff_create)
            self.assertLess(handoff_create, handoff_accept)
            self.assertLess(handoff_accept, claim_release)
            self.assertLess(claim_release, evidence_record)
            self.assertIn("record or refresh final agent-run evidence after claim release", rendered)

    def test_evidence_record_refuses_self_claimed_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            changed_ref = "src/changed.py"
            record_ref = "project/verification/agent-runs/self-claimed.md"
            (root / "src").mkdir()
            (root / changed_ref).write_text("print('changed')\n", encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "--root",
                            str(root),
                            "evidence",
                            "--record",
                            "--dry-run",
                            "--record-id",
                            "self-claimed",
                            "--role",
                            "coder",
                            "--actor",
                            "codex",
                            "--task",
                            "Record release closeout evidence.",
                            "--assigned-scope",
                            "release-lifecycle-ux",
                            "--runtime",
                            "local-shell",
                            "--worktree-id",
                            "main",
                            "--status",
                            "succeeded",
                            "--stop-reason",
                            "verification-passed",
                            "--attempt-budget",
                            "1/1",
                            "--input-ref",
                            "project/project-state.md",
                            "--output-ref",
                            changed_ref,
                            "--claimed-path",
                            record_ref,
                            "--changed-file",
                            changed_ref,
                            "--command",
                            "python -m unittest tests.test_release_lifecycle_ux",
                            "--verification-ref",
                            "project/project-state.md",
                            "--docs-decision",
                            "not-needed",
                            "--residual-risk",
                            "none",
                        ]
                    ),
                    0,
                )
            rendered = output.getvalue()

            self.assertIn("agent-run-record-refused", rendered)
            self.assertIn("--claimed-path must not point at the record target", rendered)
            self.assertIn("self-referential agent run records become stale immediately", rendered)
            self.assertFalse((root / record_ref).exists())

    def test_fan_in_guidance_uses_execution_slice_when_roadmap_item_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="pending")
            _write_fan_in_gate_plan(root, fan_in_required=True)
            plan_path = root / "project/implementation-plan.md"
            plan_text = plan_path.read_text(encoding="utf-8")
            plan_text = plan_text.replace('execution_slice: "delegated-slice"', 'execution_slice: "route-diagnostics"')
            plan_text = plan_text.replace('primary_roadmap_item: "delegated-slice"', 'primary_roadmap_item: "roadmap-item"')
            plan_path.write_text(plan_text, encoding="utf-8")
            args = _fan_in_gate_writeback_args(root)

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main([*args[:3], "--dry-run", *args[3:]]), 0)
            rendered = output.getvalue()

            self.assertIn("--execution-slice route-diagnostics", rendered)
            self.assertNotIn("--execution-slice roadmap-item", rendered)

    def test_fan_in_guidance_accepts_handoff_before_release_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="pending")
            _write_fan_in_gate_plan(root, fan_in_required=True)
            _write_fan_in_coordination_evidence(root, "delegated-slice")
            claim_path = root / "project/verification/work-claims/claim-1.json"
            handoff_path = root / "project/verification/handoffs/handoff-1.json"
            claim_data = json.loads(claim_path.read_text(encoding="utf-8"))
            handoff_data = json.loads(handoff_path.read_text(encoding="utf-8"))
            claim_data["status"] = "active"
            handoff_data["status"] = "pending"
            claim_path.write_text(json.dumps(claim_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            handoff_path.write_text(json.dumps(handoff_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            args = _fan_in_gate_writeback_args(root)
            command = [*args[:3], "--dry-run", *args[3:]]

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(command), 0)
            rendered = output.getvalue()

            self.assertIn("fan_in_evidence=missing:released-work-claim,accepted-handoff", rendered)
            accept = rendered.index("handoff --dry-run --action accept")
            release = rendered.index("claim --dry-run --action release")
            self.assertLess(accept, release)
            self.assertIn("claim release and final agent-run evidence still required", rendered)
            self.assertIn("final agent-run evidence will be recorded after claim release", rendered)

    def test_transition_phase_complete_preview_projects_active_plan_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="pending")
            _write_fan_in_gate_plan(root, fan_in_required=False)
            args = Namespace(
                worktree_start_state="clean except task diff",
                task_scope="release lifecycle UX",
                docs_decision="not-needed",
                state_writeback="Completed the release lifecycle UX slice",
                verification="Focused regression covered transition projection",
                commit_decision="no commit in test fixture",
                residual_risk="none",
                next_state="explicit-decision-required",
                carry_forward="",
                work_result="",
            )

            preview = cli_module._transition_phase_complete_preview_inventory(load_inventory(root), args)
            plan = preview.active_plan_surface
            self.assertIsNotNone(plan)
            plan_text = plan.content
            self.assertIn('status: "complete"', plan_text)
            self.assertIn('phase_status: "complete"', plan_text)
            self.assertIn("- id: `phase-1-implementation`\n- status: `done`", plan_text)
            self.assertIn('phase_status: "complete"', preview.state.content)


if __name__ == "__main__":
    unittest.main()
