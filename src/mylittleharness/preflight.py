from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from .checks import (
    audit_link_findings,
    context_budget_findings,
    flatten_sections,
    product_hygiene_findings,
    validation_findings,
)
from .closeout import closeout_sections
from .inventory import Inventory
from .models import Finding
from .safe_commands import shell_arg


def render_git_pre_commit_template(root: Path) -> str:
    root_literal = shlex.quote(str(root.resolve()))
    return "\n".join(
        [
            "#!/bin/sh",
            "# MyLittleHarness advisory preflight hook template.",
            "# Install manually only when an operator wants local warning output.",
            "# This wrapper never blocks commits and never mutates files, Git config, or workflow state.",
            f"MLH_ROOT={root_literal}",
            "",
            "if ! command -v mylittleharness >/dev/null 2>&1; then",
            "    printf '%s\\n' 'warning: mylittleharness is not available; skipping advisory preflight.' >&2",
            "    exit 0",
            "fi",
            "",
            'if ! mylittleharness --root "$MLH_ROOT" preflight; then',
            "    printf '%s\\n' 'warning: mylittleharness preflight did not complete; this hook remains warning-only.' >&2",
            "fi",
            "",
            "exit 0",
        ]
    )


def preflight_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    checks = _check_findings(inventory)
    closeout = _closeout_readiness_findings(inventory)
    return [
        ("Summary", _summary_findings(inventory, checks + closeout)),
        ("Checks", checks),
        ("Closeout Readiness", closeout),
        ("Boundary", _boundary_findings()),
    ]


def orchestrator_workspace_preflight_sections(
    inventory: Inventory,
    workspace: str,
    product_root: str = "",
) -> list[tuple[str, list[Finding]]]:
    workspace_path = Path(workspace).expanduser()
    product_path = Path(product_root).expanduser() if product_root else _configured_product_root(inventory)
    findings = [
        Finding(
            "info",
            "orchestrator-preflight-boundary",
            "external orchestrator workspace preflight is read-only; it creates no clone, shell, Linear issue, provider state, lifecycle write, claim, commit, or cleanup",
        ),
        Finding("info", "orchestrator-preflight-root", f"coordination root: {inventory.root}; root_kind={inventory.root_kind}"),
        Finding("info", "orchestrator-preflight-workspace", f"candidate disposable workspace: {workspace_path}"),
    ]
    findings.extend(_workspace_exclusion_findings(inventory.root, workspace_path, product_path))
    shape_findings = _workspace_shape_findings(workspace_path)
    findings.extend(shape_findings)
    if any(finding.severity == "warn" for finding in shape_findings):
        findings.append(
            Finding(
                "warn",
                "orchestrator-preflight-refused",
                "workspace command hints are withheld until the candidate workspace is a normal directory",
                str(workspace_path),
            )
        )
    else:
        findings.extend(_tool_findings())
        findings.extend(_orchestrator_command_findings(workspace_path))
    return [
        ("Orchestrator Workspace", findings),
        (
            "Boundary",
            [
                Finding(
                    "info",
                    "orchestrator-preflight-no-authority",
                    "passing this preflight cannot approve worker launch, lifecycle movement, roadmap status, source edits, staging, commit, push, release, or Linear/Symphony completion claims",
                )
            ],
        ),
    ]


def _summary_findings(inventory: Inventory, findings: list[Finding]) -> list[Finding]:
    errors = sum(1 for finding in findings if finding.severity == "error")
    warnings = sum(1 for finding in findings if finding.severity == "warn")
    status = "error" if errors else "warn" if warnings else "ok"
    return [
        Finding(
            "info",
            "preflight-boundary",
            "terminal-only optional preflight report; no files, hooks, CI config, GitHub state, generated reports, caches, repairs, commits, archives, or lifecycle state are written",
        ),
        Finding("info", "preflight-root-kind", f"root kind: {inventory.root_kind}"),
        Finding(
            "info",
            "preflight-result",
            f"advisory result: status={status}; errors={errors}; warnings={warnings}; local closeout remains valid without hooks, CI, GitHub, network, or adapter state",
        ),
    ]


def _check_findings(inventory: Inventory) -> list[Finding]:
    groups = [
        ("validate", validation_findings(inventory)),
        ("audit-links", audit_link_findings(inventory)),
        ("context-budget", context_budget_findings(inventory)),
        ("product-hygiene", product_hygiene_findings(inventory)),
    ]
    findings: list[Finding] = []
    for label, group_findings in groups:
        findings.append(_group_summary(label, group_findings))
        findings.extend(_group_samples(label, group_findings))
    return findings


def _closeout_readiness_findings(inventory: Inventory) -> list[Finding]:
    sections = closeout_sections(inventory)
    closeout_findings = flatten_sections(sections)
    findings = [
        _group_summary("closeout", closeout_findings),
        Finding(
            "info",
            "preflight-closeout-source",
            "closeout readiness is assembled from the read-only closeout report, including target-bound VCS posture cues when Git is available",
        ),
    ]
    for finding in closeout_findings:
        if finding.code in {
            "closeout-worktree-start-state",
            "closeout-task-scope",
            "closeout-commit-input",
            "closeout-quality-gate",
        }:
            findings.append(
                Finding(
                    finding.severity,
                    "preflight-closeout-cue",
                    f"{finding.code}: {finding.message}",
                    finding.source,
                    finding.line,
                )
            )
    return findings


def _group_summary(label: str, findings: list[Finding]) -> Finding:
    errors = sum(1 for finding in findings if finding.severity == "error")
    warnings = sum(1 for finding in findings if finding.severity == "warn")
    severity = "error" if errors else "warn" if warnings else "info"
    return Finding(severity, f"preflight-{label}", f"{label} findings: {errors} errors, {warnings} warnings")


def _group_samples(label: str, findings: list[Finding], limit: int = 3) -> list[Finding]:
    samples = [finding for finding in findings if finding.severity in {"error", "warn"}][:limit]
    return [
        Finding(
            finding.severity,
            "preflight-check-sample",
            f"{label} {finding.severity} {finding.code}: {finding.message}",
            finding.source,
            finding.line,
        )
        for finding in samples
    ]


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "preflight-no-authority",
            "preflight output is advisory evidence only and cannot approve correctness, repair, closeout, archive, commit, lifecycle decisions",
        ),
        Finding(
            "info",
            "preflight-no-hooks",
            "preflight is suitable for manual or future hook/CI consumption, but this command does not install hooks, add CI/GitHub workflows, block by itself, or require network access",
        ),
        Finding(
            "info",
            "preflight-no-mutation",
            "preflight does not format, repair, write reports, create generated artifacts, stage files, commit, archive, change target roots, or mutate workflow state",
        ),
    ]


def _workspace_exclusion_findings(root: Path, workspace: Path, product_root: Path | None) -> list[Finding]:
    findings: list[Finding] = []
    resolved_workspace = _safe_resolve(workspace)
    resolved_root = _safe_resolve(root)
    if resolved_workspace == resolved_root:
        findings.append(Finding("warn", "orchestrator-preflight-live-root", "candidate workspace is the live coordination root; use a disposable clone/worktree outside the live root", str(workspace)))
    elif _is_within(resolved_workspace, resolved_root):
        findings.append(Finding("warn", "orchestrator-preflight-live-root", "candidate workspace is inside the live coordination root; avoid live-root nested worker debris", str(workspace)))
    if product_root:
        resolved_product = _safe_resolve(product_root)
        if resolved_workspace == resolved_product:
            findings.append(Finding("warn", "orchestrator-preflight-product-root", "candidate workspace is the configured product source root; use a disposable clone/worktree instead", str(workspace)))
        elif _is_within(resolved_workspace, resolved_product):
            findings.append(Finding("warn", "orchestrator-preflight-product-root", "candidate workspace is inside the configured product source root; avoid live-root nested worker debris", str(workspace)))
    if not findings:
        findings.append(Finding("info", "orchestrator-preflight-live-root-excluded", "candidate workspace is distinct from the live coordination root and configured product source root", str(workspace)))
    return findings


def _workspace_shape_findings(workspace: Path) -> list[Finding]:
    if workspace.exists() and workspace.is_symlink():
        return [Finding("warn", "orchestrator-preflight-workspace-shape", "candidate workspace is a symlink; choose a normal disposable directory", str(workspace))]
    if workspace.exists() and not workspace.is_dir():
        return [Finding("warn", "orchestrator-preflight-workspace-shape", "candidate workspace exists but is not a directory", str(workspace))]
    if not workspace.exists():
        return [Finding("info", "orchestrator-preflight-workspace-shape", "candidate workspace does not exist yet; create it through the external orchestrator setup, not this read-only preflight", str(workspace))]
    examples = [path.name for path in sorted(workspace.iterdir(), key=lambda item: item.name.lower())[:5]]
    return [Finding("info", "orchestrator-preflight-workspace-shape", f"candidate workspace exists; sample_entries={', '.join(examples) or 'empty'}", str(workspace))]


def _tool_findings() -> list[Finding]:
    findings = []
    for tool in ("git", "mylittleharness"):
        path = shutil.which(tool)
        severity = "info" if path else "warn"
        findings.append(Finding(severity, "orchestrator-preflight-tool", f"{tool}={'available at ' + path if path else 'not found on PATH'}"))
    return findings


def _orchestrator_command_findings(workspace: Path) -> list[Finding]:
    root_literal = shell_arg(str(workspace))
    return [
        Finding("info", "orchestrator-preflight-command", f"shell preflight: cd {root_literal}"),
        Finding("info", "orchestrator-preflight-command", "git preflight: git status --short --branch"),
        Finding("info", "orchestrator-preflight-command", "MLH preflight after scaffold/clone: mylittleharness --root <disposable-root> check"),
        Finding("info", "orchestrator-preflight-completion-policy", "external orchestrator completion claims must cite repo-visible handoff/claim/agent-run evidence; Linear/Symphony status alone is not MLH closeout"),
    ]


def _configured_product_root(inventory: Inventory) -> Path | None:
    data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    value = str(data.get("product_source_root") or data.get("projection_root") or "").strip()
    return Path(value).expanduser() if value else None


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
