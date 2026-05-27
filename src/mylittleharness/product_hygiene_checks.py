from __future__ import annotations

from pathlib import Path

from .inventory import Inventory
from .models import Finding
from .root_boundary import PRODUCT_SOURCE_FIXTURE


PRODUCT_HYGIENE_OPERATIONAL_PREFIXES = {
    "project/implementation-plan.md": "active implementation plans live in the operating root",
    "project/roadmap.md": "roadmaps live in the operating root",
    "project/adrs": "ADR records live in the operating root",
    "project/decisions": "decision and do-not-revisit records live in the operating root",
    "project/archive": "archives and historical memory live in the operating root",
    "project/incubator": "legacy incubator notes must use canonical project/plan-incubation in the operating root",
    "project/plan-incubation": "incubation notes live in the operating root",
    "project/problem-reports": "problem reports and new intake live in the operating root",
    "project/raw-intake": "raw intake lives in the operating root",
    "project/research": "research and raw intake live in the operating root",
    "project/reports": "reports live in the operating root",
    "project/verification": "verification artifacts live in the operating root",
}
PRODUCT_HYGIENE_PACKAGE_PREFIXES = {
    "codex-home": "skill projections are not part of the clean product source tree",
    "research": "root research mirrors are excluded from the product source tree",
    "specs": "root package-source mirrors are excluded from the product source tree",
    "templates": "templates are package-source material, not product source",
}
PRODUCT_HYGIENE_DEBRIS_DIR_NAMES = {
    ".cache",
    ".eggs",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "artifacts",
    "build",
    "cache",
    "dist",
    "generated-validation",
    "htmlcov",
    "logs",
    "reports",
    "tmp",
    "validation-artifacts",
}
PRODUCT_HYGIENE_DEBRIS_FILE_SUFFIXES = {
    ".bak",
    ".db",
    ".egg",
    ".log",
    ".pyc",
    ".pyo",
    ".swo",
    ".swp",
    ".temp",
    ".sqlite",
    ".sqlite3",
    ".tmp",
    ".whl",
    ".zip",
}
PRODUCT_HYGIENE_DEBRIS_FILE_NAMES = {
    ".coverage",
    "coverage.xml",
    "validation-report.md",
}
PRODUCT_HYGIENE_ARCHIVE_SUFFIXES = (
    ".tar",
    ".tar.bz2",
    ".tar.gz",
    ".tar.xz",
    ".tgz",
)


def product_hygiene_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != PRODUCT_SOURCE_FIXTURE:
        return [Finding("info", "product-hygiene-scope", "product hygiene check skipped because root is not marked as product source")]

    findings: list[Finding] = []
    for path, rel_path in _iter_hygiene_paths(inventory.root):
        classification = _classify_product_hygiene_path(path, rel_path)
        if classification is None:
            continue
        code, reason = classification
        if code == "forbidden-product-surface":
            message = f"operational surface must not live in product root: {rel_path}; {reason}"
        else:
            message = f"unexpected product-root debris: {rel_path}; {reason}; report only, no deletion performed"
        findings.append(Finding("warn", code, message, rel_path))

    if not findings:
        findings.append(Finding("info", "product-hygiene-ok", "no product-root debris found"))
    return findings


def _iter_hygiene_paths(root: Path) -> list[tuple[Path, str]]:
    paths: list[tuple[Path, str]] = []
    _collect_hygiene_paths(root, root, paths)
    return paths


def _collect_hygiene_paths(root: Path, current: Path, paths: list[tuple[Path, str]]) -> None:
    try:
        children = sorted(current.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return
    for child in children:
        rel_path = child.relative_to(root).as_posix()
        if rel_path == ".git" or rel_path.startswith(".git/"):
            continue
        paths.append((child, rel_path))
        if child.is_dir() and not child.is_symlink() and _should_descend_for_hygiene(child, rel_path):
            _collect_hygiene_paths(root, child, paths)


def _should_descend_for_hygiene(path: Path, rel_path: str) -> bool:
    return _classify_product_hygiene_path(path, rel_path) is None


def _classify_product_hygiene_path(path: Path, rel_path: str) -> tuple[str, str] | None:
    normalized = rel_path.replace("\\", "/").lower()
    if (
        normalized in {".mylittleharness", ".mylittleharness/project-workflow.toml", ".mylittleharness/generated"}
        or normalized.startswith(".mylittleharness/generated/projection")
    ):
        return None
    if normalized.startswith(".mylittleharness/"):
        return ("product-debris", "generated MyLittleHarness output is allowed only under .mylittleharness/generated/projection")
    for prefix, reason in PRODUCT_HYGIENE_OPERATIONAL_PREFIXES.items():
        prefix_lower = prefix.lower()
        if normalized == prefix_lower or normalized.startswith(prefix_lower.rstrip("/") + "/"):
            return ("forbidden-product-surface", reason)
    for prefix, reason in PRODUCT_HYGIENE_PACKAGE_PREFIXES.items():
        prefix_lower = prefix.lower()
        if normalized == prefix_lower or normalized.startswith(prefix_lower.rstrip("/") + "/"):
            return ("forbidden-product-surface", reason)

    name = path.name.lower()
    if path.is_symlink() and normalized.startswith("src/mylittleharness/"):
        return ("forbidden-product-surface", "package source must not contain symlinked members")
    if path.is_dir() and (name in PRODUCT_HYGIENE_DEBRIS_DIR_NAMES or name.endswith(".egg-info")):
        return ("product-debris", "generated/cache/build/runtime directory is excluded from product source")
    if path.is_file():
        if name in PRODUCT_HYGIENE_DEBRIS_FILE_NAMES:
            return ("product-debris", "generated validation, coverage, or runtime file is excluded from product source")
        if name.startswith("validation-report") and name.endswith(".md"):
            return ("product-debris", "generated validation report is excluded from product source")
        if any(name.endswith(suffix) for suffix in PRODUCT_HYGIENE_DEBRIS_FILE_SUFFIXES):
            return ("product-debris", "log, local database, package archive, or temporary file is excluded from product source")
        if any(name.endswith(suffix) for suffix in PRODUCT_HYGIENE_ARCHIVE_SUFFIXES):
            return ("product-debris", "package archive is excluded from product source")
    return None
