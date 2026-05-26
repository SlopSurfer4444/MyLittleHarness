from __future__ import annotations

from .inventory import Inventory
from .models import Finding


def tasks_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    return [
        ("Summary", _summary_findings(inventory)),
        ("Operator Tasks", _operator_task_findings()),
        ("Compatibility", _compatibility_findings()),
        ("Boundary", _boundary_findings()),
        ("Future Power-Ups", _future_power_up_findings()),
    ]


def _summary_findings(inventory: Inventory) -> list[Finding]:
    return [
        Finding("info", "tasks-summary", "operator task map for the existing MyLittleHarness CLI surface"),
        Finding("info", "tasks-root-kind", f"root kind: {inventory.root_kind}"),
        Finding("info", "tasks-report", "tasks --inspect is terminal-only and read-only"),
    ]


def _operator_task_findings() -> list[Finding]:
    return [
        Finding("info", "tasks-orient", "orient: status; tasks --inspect"),
        Finding("info", "tasks-verify", "verify: validate; context-budget; audit-links; doctor; preflight; optional warning wrapper template: preflight --template git-pre-commit"),
        Finding(
            "info",
            "tasks-search-inspect",
            "search/inspect: intelligence; semantic --inspect; semantic --evaluate; adapter --inspect --target mcp-read-projection; snapshot --inspect; projection --inspect",
        ),
        Finding("info", "tasks-evidence-closeout", "evidence/closeout: evidence; closeout"),
        Finding("info", "tasks-generated-projection", "generated projection: projection --inspect|--warm-cache|--build|--delete|--rebuild"),
        Finding("info", "tasks-bootstrap-readiness", "package/bootstrap readiness: bootstrap --inspect; bootstrap --package-smoke"),
        Finding("info", "tasks-attach-repair", "attach/repair: attach --dry-run|--apply; repair --dry-run|--apply"),
    ]


def _compatibility_findings() -> list[Finding]:
    return [
        Finding("info", "tasks-compatibility", "existing commands, flags, exit codes, and parser usage failures remain unchanged"),
        Finding("info", "tasks-console-script", "package console script remains mylittleharness = mylittleharness.cli:main"),
        Finding("info", "tasks-package-smoke", "package smoke is explicit verification through bootstrap --package-smoke, while bootstrap --inspect is a read-only readiness report"),
    ]


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "tasks-read-only",
            "tasks --inspect writes no files, generated reports, projection artifacts, caches, config, hooks, snapshots, package artifacts, or adapter state",
        ),
        Finding(
            "info",
            "tasks-no-authority",
            "tasks --inspect cannot approve correctness, repair, closeout, archive, commit, lifecycle decisions, or future power-ups",
        ),
        Finding("info", "tasks-no-alias", "tasks --inspect is a task map and does not hide aliases, remove commands, or change defaults"),
    ]


def _future_power_up_findings() -> list[Finding]:
    return [
        Finding("info", "tasks-future-evidence", "future lane: evidence manifest and closeout hardening remain gated"),
        Finding("info", "tasks-future-semantic", "future lane: real semantic retrieval remains gated behind source verification beyond bounded no-runtime evaluation"),
        Finding("info", "tasks-future-adapters", "future lane: additional adapters, hook/CI integrations, publishing, and repair expansion remain gated; standalone bootstrap apply is rejected"),
    ]
