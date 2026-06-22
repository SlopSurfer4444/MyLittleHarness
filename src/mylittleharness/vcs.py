from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .inventory import Inventory, RootLoadError, Surface, load_inventory
from .models import Finding
from .parsing import parse_frontmatter
from .root_boundary import windows_path_reference_reason


GIT_TIMEOUT_SECONDS = 5
CHANGED_SAMPLE_LIMIT = 10
TRAILER_SAMPLE_LIMIT = 10
COORDINATION_ROOT_ENV_VAR = "MLH_COORDINATION_ROOT"
UNSAFE_COORDINATION_ROOT_REFERENCE_REASONS = {
    "Windows drive-relative path",
    "Windows alternate data stream path",
    "reserved Windows device basename",
}
PRODUCT_COMPATIBILITY_FIXTURE_SCOPES = {
    ".agents/docmap.yaml",
    ".codex/project-workflow.toml",
    ".mylittleharness/project-workflow.toml",
    "project/project-state.md",
}


@dataclass(frozen=True)
class VcsChangedPath:
    status: str
    path: str


@dataclass(frozen=True)
class VcsPosture:
    root: Path
    git_available: bool
    is_worktree: bool
    state: str
    top_level: str | None = None
    changed_count: int = 0
    changed_samples: tuple[VcsChangedPath, ...] = ()
    detail: str | None = None
    changed_paths: tuple[VcsChangedPath, ...] = ()


@dataclass(frozen=True)
class VcsTrailer:
    key: str
    value: str


@dataclass(frozen=True)
class VcsTrailerParseResult:
    root: Path
    git_available: bool
    parsed: bool
    trailers: tuple[VcsTrailer, ...] = ()
    detail: str | None = None


def worktree_coordination_findings(
    inventory: Inventory,
    *,
    environ: dict[str, str] | None = None,
    code_prefix: str = "worktree-coordination",
) -> list[Finding]:
    env = os.environ if environ is None else environ
    raw_coordination_root = str(env.get(COORDINATION_ROOT_ENV_VAR) or "").strip()
    findings: list[Finding] = [
        Finding(
            "info",
            f"{code_prefix}-edit-root",
            f"edit root: {inventory.root}; root_kind={inventory.root_kind}; coordination writes remain separate from edit-worktree source edits",
        )
    ]
    if not raw_coordination_root:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-unset",
                f"{COORDINATION_ROOT_ENV_VAR} is not set; this root is treated as the coordination root for local checks only",
            )
        )
        findings.extend(_worktree_coordination_record_findings(inventory, code_prefix))
        findings.extend(_worktree_coordination_boundary_findings(code_prefix))
        return findings

    coordination_root, problem = _resolve_coordination_root(raw_coordination_root, inventory.root)
    if problem:
        findings.append(Finding("warn", f"{code_prefix}-root-invalid", problem, COORDINATION_ROOT_ENV_VAR))
        findings.extend(_worktree_coordination_record_findings(inventory, code_prefix))
        findings.extend(_worktree_coordination_boundary_findings(code_prefix))
        return findings

    try:
        coordination_inventory = load_inventory(coordination_root)
    except RootLoadError as exc:
        findings.append(Finding("warn", f"{code_prefix}-root-invalid", f"{COORDINATION_ROOT_ENV_VAR} could not be loaded as an MLH root: {exc}", COORDINATION_ROOT_ENV_VAR))
        findings.extend(_worktree_coordination_record_findings(inventory, code_prefix))
        findings.extend(_worktree_coordination_boundary_findings(code_prefix))
        return findings

    severity = "info" if coordination_inventory.root_kind == "live_operating_root" else "warn"
    code = f"{code_prefix}-root-ok" if coordination_inventory.root_kind == "live_operating_root" else f"{code_prefix}-root-refused"
    message = (
        f"{COORDINATION_ROOT_ENV_VAR}={coordination_inventory.root}; root_kind={coordination_inventory.root_kind}; "
        "coordination evidence writes must target this root, while source edits stay in the edit worktree"
    )
    if coordination_inventory.root_kind != "live_operating_root":
        message = (
            f"{COORDINATION_ROOT_ENV_VAR} must resolve to a live operating root; got root_kind={coordination_inventory.root_kind}; "
            "refusing product-source or archive roots as shared coordination authority"
        )
    findings.append(Finding(severity, code, message, COORDINATION_ROOT_ENV_VAR))

    if _same_resolved_path(coordination_inventory.root, inventory.root):
        findings.append(Finding("info", f"{code_prefix}-same-root", "target root and coordination root are the same live coordination root"))
    else:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-split-root",
                f"target root {inventory.root} is the edit/inspection root; shared coordination root is {coordination_inventory.root}",
            )
        )

    findings.extend(_worktree_coordination_git_findings(inventory.root, code_prefix, "edit"))
    if not _same_resolved_path(coordination_inventory.root, inventory.root):
        findings.extend(_worktree_coordination_git_findings(coordination_inventory.root, code_prefix, "coordination"))
    findings.extend(_worktree_coordination_record_findings(inventory, code_prefix))
    findings.extend(_worktree_coordination_boundary_findings(code_prefix))
    return findings


def dispatcher_worktree_coordination_findings(
    inventory: Inventory,
    *,
    environ: dict[str, str] | None = None,
    code_prefix: str = "dispatcher-worktree-coordination",
) -> list[Finding]:
    findings = [
        Finding(
            "info",
            f"{code_prefix}-launcher-boundary",
            (
                "dispatcher launch readiness respects MLH_COORDINATION_ROOT as an explicit routing hint; "
                "it does not create worktrees, write coordination records, start workers, or promote runtime state to authority"
            ),
        )
    ]
    findings.extend(worktree_coordination_findings(inventory, environ=environ, code_prefix=code_prefix))
    return findings


GitRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
GIT_OUTPUT_ENCODING = "utf-8"


def probe_vcs(root: Path, runner: GitRunner | None = None) -> VcsPosture:
    root = root.expanduser().resolve()
    rev_parse = _run_git(root, ("rev-parse", "--is-inside-work-tree"), runner)
    if isinstance(rev_parse, str):
        return VcsPosture(root=root, git_available=False, is_worktree=False, state="unknown", detail=rev_parse)
    if rev_parse.returncode != 0:
        return VcsPosture(
            root=root,
            git_available=True,
            is_worktree=False,
            state="non-git",
            detail=_first_output_line(rev_parse) or f"git exited {rev_parse.returncode}",
        )
    if (rev_parse.stdout or "").strip().casefold() != "true":
        detail = _first_output_line(rev_parse) or "not inside a Git worktree"
        return VcsPosture(root=root, git_available=True, is_worktree=False, state="non-git", detail=detail)

    top_level = _git_top_level(root, runner)
    status = _run_git(root, ("status", "--untracked-files=all", "--porcelain=v1"), runner)
    if isinstance(status, str):
        return VcsPosture(root=root, git_available=False, is_worktree=True, state="unknown", top_level=top_level, detail=status)
    if status.returncode != 0:
        return VcsPosture(
            root=root,
            git_available=True,
            is_worktree=True,
            state="unknown",
            top_level=top_level,
            detail=_first_output_line(status) or f"git status exited {status.returncode}",
        )

    if status.stdout is None:
        return VcsPosture(
            root=root,
            git_available=True,
            is_worktree=True,
            state="unknown",
            top_level=top_level,
            detail=_first_output_line(status) or "git status produced no stdout",
        )

    entries = _parse_porcelain(status.stdout)
    state = "dirty" if entries else "clean"
    return VcsPosture(
        root=root,
        git_available=True,
        is_worktree=True,
        state=state,
        top_level=top_level,
        changed_count=len(entries),
        changed_samples=tuple(entries[:CHANGED_SAMPLE_LIMIT]),
        changed_paths=tuple(entries),
    )


def product_diff_write_scope_findings(
    inventory: Inventory,
    closeout_values: dict[str, str] | None = None,
    *,
    completion_reason: str = "",
    apply: bool = False,
    code_prefix: str = "product-diff",
    preflight: bool = False,
    include_success: bool = False,
) -> list[Finding]:
    scope = _product_diff_scope(inventory)
    if scope is None:
        return []

    source = scope["source"]
    problem = scope.get("problem", "")
    if problem:
        problem_severity = str(scope.get("problem_severity") or "info")
        if problem_severity == "error":
            severity = "error" if apply or preflight else "warn"
            return [
                Finding(
                    severity,
                    f"{code_prefix}-product-diff-write-scope-blocked",
                    problem,
                    source,
                )
            ]
        if preflight or not completion_reason:
            return []
        return [Finding("info", f"{code_prefix}-product-diff-write-scope-skipped", problem, source)]

    out_of_scope = scope["out_of_scope"]
    dirty_paths = scope["dirty_paths"]
    allowed_paths = scope["allowed_paths"]
    if not dirty_paths:
        if include_success and not preflight:
            return [
                Finding(
                    "info",
                    f"{code_prefix}-product-diff-write-scope",
                    "product dirty diff is clean; no active-plan write-scope comparison was needed",
                    source,
                )
            ]
        return []

    if not out_of_scope:
        if include_success or completion_reason:
            allowed_sample = _sample_text(allowed_paths)
            return [
                Finding(
                    "info",
                    f"{code_prefix}-product-diff-write-scope",
                    (
                        f"product dirty diff is within active plan target_artifacts/write_scope; "
                        f"dirty_paths={_sample_text(dirty_paths)}; allowed_scope={allowed_sample}"
                    ),
                    source,
                )
            ]
        return []

    values = closeout_values or {}
    disclosed = _closeout_disclaims_out_of_scope_product_diff(values, out_of_scope)
    sample = _sample_text(out_of_scope)
    exact = _exact_path_list(out_of_scope)
    out_of_scope_fingerprint = str(scope.get("out_of_scope_fingerprint") or "")
    dirty_set_fingerprint = str(scope.get("dirty_set_fingerprint") or "")
    fingerprint_detail = (
        f"out_of_scope_fingerprint={out_of_scope_fingerprint}; dirty_set_fingerprint={dirty_set_fingerprint}; exact out_of_scope_paths={exact}"
    )
    allowed_sample = _sample_text(allowed_paths)
    completion = completion_reason or "active plan read-only posture"
    if completion_reason and not disclosed:
        finding = Finding(
            "error" if apply or preflight else "warn",
            f"{code_prefix}-product-diff-write-scope-blocked",
            (
                f"{completion} would accept out-of-scope product dirty diff path(s): {sample}; "
                f"{fingerprint_detail}; "
                f"allowed active plan target_artifacts/write_scope: {allowed_sample}. "
                "Record residual risk/carry-forward that explicitly leaves these paths unaccepted, "
                "or narrow the actual product diff before closeout; rerun dry-run if the fingerprint changes before apply."
            ),
            source,
        )
        return [finding]

    if preflight:
        return []
    if completion_reason and disclosed:
        return [
            Finding(
                "info",
                f"{code_prefix}-product-diff-write-scope-disclosed",
                (
                    f"{completion} sees out-of-scope product dirty diff path(s): {sample}; "
                    f"{fingerprint_detail}; "
                    "closeout evidence explicitly leaves those paths unaccepted, so this route does not silently accept them"
                ),
                source,
            )
        ]
    return [
        Finding(
            "warn",
            f"{code_prefix}-product-diff-write-scope",
            (
                f"actual product dirty diff exceeds active plan target_artifacts/write_scope: {sample}; "
                f"{fingerprint_detail}; "
                f"allowed_scope={allowed_sample}; read-only diagnostics do not accept, split, discard, or revert these changes"
            ),
            source,
        )
    ]


def product_diff_scope_proof(inventory: Inventory, closeout_values: dict[str, str] | None = None) -> dict[str, object] | None:
    scope = _product_diff_scope(inventory)
    if scope is None:
        return None

    proof = dict(scope)
    problem = str(proof.get("problem") or "")
    if problem:
        severity = str(proof.get("problem_severity") or "info")
        proof["status"] = "blocked" if severity == "error" else "unavailable"
        return proof

    dirty_paths = tuple(str(path) for path in proof.get("dirty_paths", ()) if str(path))
    out_of_scope = tuple(str(path) for path in proof.get("out_of_scope", ()) if str(path))
    if not dirty_paths:
        proof["status"] = "clean"
    elif out_of_scope:
        disclosed = _closeout_disclaims_out_of_scope_product_diff(closeout_values or {}, out_of_scope)
        proof["status"] = "disclosed-out-of-scope" if disclosed else "out-of-scope"
        proof["disclosed"] = disclosed
    else:
        proof["status"] = "within-scope"
    proof["dirty_paths"] = dirty_paths
    proof["out_of_scope"] = out_of_scope
    proof["allowed_paths"] = tuple(str(path) for path in proof.get("allowed_paths", ()) if str(path))
    proof["dirty_set_fingerprint"] = _path_set_fingerprint(dirty_paths)
    proof["out_of_scope_fingerprint"] = _path_set_fingerprint(out_of_scope)
    return proof


def parse_head_commit_trailers(root: Path) -> VcsTrailerParseResult:
    root = root.expanduser().resolve()
    message = _run_git(root, ("log", "-1", "--format=%B"), runner=None)
    if isinstance(message, str):
        return VcsTrailerParseResult(root=root, git_available=False, parsed=False, detail=message)
    if message.returncode != 0:
        return VcsTrailerParseResult(
            root=root,
            git_available=True,
            parsed=False,
            detail=_first_output_line(message) or f"git log exited {message.returncode}",
        )

    parsed = _run_git_with_input(root, ("interpret-trailers", "--parse"), message.stdout)
    if isinstance(parsed, str):
        return VcsTrailerParseResult(root=root, git_available=False, parsed=False, detail=parsed)
    if parsed.returncode != 0:
        return VcsTrailerParseResult(
            root=root,
            git_available=True,
            parsed=False,
            detail=_first_output_line(parsed) or f"git interpret-trailers exited {parsed.returncode}",
        )
    return VcsTrailerParseResult(
        root=root,
        git_available=True,
        parsed=True,
        trailers=tuple(_parse_trailer_lines(parsed.stdout)[:TRAILER_SAMPLE_LIMIT]),
    )


def _product_diff_scope(inventory: Inventory) -> dict[str, object] | None:
    if inventory.root_kind != "live_operating_root":
        return None
    plan = inventory.active_plan_surface
    state = inventory.state
    if not plan or not plan.exists or not state or not state.exists:
        return None
    product_root, problem, problem_severity = _configured_product_source_root(inventory)
    source = plan.rel_path
    if product_root is None:
        return {"source": source, "problem": problem, "problem_severity": problem_severity}

    allowed_paths, scope_errors = _active_plan_product_scope(plan)
    if scope_errors:
        return {
            "source": source,
            "problem": f"active plan product scope contains invalid path(s): {_sample_text(scope_errors)}",
            "problem_severity": "error",
        }
    if not allowed_paths:
        return None

    posture = probe_vcs(product_root)
    if not posture.git_available or not posture.is_worktree or posture.state not in {"dirty", "clean"}:
        detail = posture.detail or posture.state or "unknown"
        return {"source": source, "problem": f"product dirty diff unavailable for scope comparison: {detail}", "problem_severity": "info"}
    entries = posture.changed_paths or posture.changed_samples
    dirty_paths = _changed_product_paths(entries)
    out_of_scope = tuple(path for path in dirty_paths if not _path_is_in_scope(path, allowed_paths))
    return {
        "source": source,
        "dirty_paths": dirty_paths,
        "out_of_scope": out_of_scope,
        "allowed_paths": allowed_paths,
        "dirty_set_fingerprint": _path_set_fingerprint(dirty_paths),
        "out_of_scope_fingerprint": _path_set_fingerprint(out_of_scope),
    }


def _configured_product_source_root(inventory: Inventory) -> tuple[Path | None, str, str]:
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    raw = str(data.get("product_source_root") or data.get("projection_root") or "").strip()
    if not raw:
        return None, "product_source_root is not configured; product dirty diff scope comparison skipped", "info"
    try:
        path = Path(raw.replace("\\\\", "\\")).expanduser()
        if not path.is_absolute():
            path = inventory.root / path
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        return None, f"product_source_root could not be resolved for dirty diff scope comparison: {exc}", "info"
    if not resolved.exists() or not resolved.is_dir():
        return None, f"product_source_root does not exist as a directory for dirty diff scope comparison: {resolved}", "info"
    if _same_resolved_path(resolved, inventory.root):
        return (
            None,
            "configured product_source_root resolves to the live operating root; product dirty diff scope comparison is refused",
            "error",
        )
    return resolved, "", "info"


def _active_plan_product_scope_paths(plan: Surface) -> tuple[str, ...]:
    paths, _errors = _active_plan_product_scope(plan)
    return paths


def _active_plan_product_scope(plan: Surface) -> tuple[tuple[str, ...], tuple[str, ...]]:
    values: list[str] = []
    if plan.frontmatter.has_frontmatter:
        values.extend(_scope_list_values(plan.frontmatter.data.get("target_artifacts")))
    for text in _plan_write_scope_values(plan.content):
        values.extend(_scope_list_values(text))
    normalized: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    for value in values:
        invalid_reason = _invalid_product_scope_reason(value)
        if invalid_reason:
            errors.append(f"{value}: {invalid_reason}")
            continue
        path = _normalize_product_rel(value)
        if not path or not _looks_like_product_scope(path) or path in seen:
            continue
        normalized.append(path)
        seen.add(path)
    return tuple(normalized), tuple(errors)


def _plan_write_scope_values(text: str) -> tuple[str, ...]:
    values: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s*[-*]\s*write_scope\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
        if match:
            values.append(match.group(1))
    return tuple(values)


def _scope_list_values(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [_strip_scope_token(item) for item in value if _strip_scope_token(item)]
    text = _strip_scope_token(value)
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [_strip_scope_token(part) for part in text.split(",") if _strip_scope_token(part)]


def _strip_scope_token(value: object) -> str:
    text = str(value or "").strip()
    while text.startswith(("-", "*")):
        text = text[1:].strip()
    for wrapper in ("`", '"', "'"):
        if text.startswith(wrapper) and text.endswith(wrapper) and len(text) >= 2:
            text = text[1:-1].strip()
    text = text.strip("`\"'").strip()
    return text


def _normalize_product_rel(value: str) -> str:
    path = _strip_scope_token(value).replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.strip("/")


def _invalid_product_scope_reason(value: str) -> str:
    raw = _strip_scope_token(value)
    path = raw.replace("\\", "/")
    if not path:
        return ""
    if path.startswith("/"):
        return "leading slash would make product scope absolute or root-ambiguous"
    if re.match(r"^[A-Za-z]:", path):
        return "drive-qualified path is outside active-plan product-relative scope"
    while path.startswith("./"):
        path = path[2:]
    parts = [part for part in path.split("/") if part]
    if any(part == ".." for part in parts):
        return "parent traversal is outside active-plan product-relative scope"
    return ""


def _looks_like_product_scope(path: str) -> bool:
    if not path:
        return False
    if path in PRODUCT_COMPATIBILITY_FIXTURE_SCOPES:
        return True
    operating_prefixes = (".agents/", ".codex/", ".mylittleharness/")
    if path.startswith(operating_prefixes):
        return False
    if path.startswith("project/"):
        # Product-source compatibility fixtures can carry workflow specs under
        # project/specs/, but other project/ routes remain operating memory.
        return path.startswith("project/specs/")
    return True


def _changed_product_paths(entries: Sequence[VcsChangedPath]) -> tuple[str, ...]:
    paths: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        for path in _changed_path_candidates(entry.path):
            normalized = _normalize_product_rel(path)
            if normalized and normalized not in seen:
                paths.append(normalized)
                seen.add(normalized)
    return tuple(paths)


def _changed_path_candidates(path: str) -> tuple[str, ...]:
    if " -> " not in path:
        return (path,)
    old, new = path.split(" -> ", 1)
    return (old.strip(), new.strip())


def _path_is_in_scope(path: str, allowed_paths: tuple[str, ...]) -> bool:
    for allowed in allowed_paths:
        prefix = allowed.rstrip("/")
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    return False


def _closeout_disclaims_out_of_scope_product_diff(values: dict[str, str], out_of_scope: Sequence[str] = ()) -> bool:
    text = " ".join(
        str(values.get(field) or "")
        for field in (
            "worktree_start_state",
            "state_writeback",
            "residual_risk",
            "carry_forward",
            "work_result",
        )
    ).casefold()
    normalized_text = text.replace("\\", "/")
    normalized_out_of_scope = tuple(
        _normalize_product_rel(path).casefold()
        for path in out_of_scope
        if _normalize_product_rel(path)
    )
    scope_markers = (
        "out-of-scope",
        "out of scope",
        "outside scope",
        "unrelated",
        "pre-existing",
        "preexisting",
        "broader dirty",
        "broader product",
        "existing dirty",
    )
    unaccepted_markers = (
        "unaccepted",
        "not accepted",
        "not accept",
        "not part",
        "excluded",
        "outside this",
        "remains",
        "not owned",
        "not covered",
    )
    mentions_scope = any(marker in text for marker in scope_markers)
    leaves_unaccepted = any(marker in text for marker in unaccepted_markers)
    mentions_paths = all(path in normalized_text for path in normalized_out_of_scope)
    return mentions_scope and leaves_unaccepted and mentions_paths


def _sample_text(values: Sequence[str], limit: int = CHANGED_SAMPLE_LIMIT) -> str:
    items = tuple(str(value) for value in values if str(value))
    if not items:
        return "<none>"
    sample = ", ".join(items[:limit])
    if len(items) > limit:
        sample += f", +{len(items) - limit} more"
    return sample


def _path_set_fingerprint(values: Sequence[str]) -> str:
    normalized = tuple(sorted(_normalize_product_rel(value) for value in values if _normalize_product_rel(value)))
    payload = "\n".join(normalized).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _exact_path_list(values: Sequence[str]) -> str:
    normalized = tuple(_normalize_product_rel(value) for value in values if _normalize_product_rel(value))
    return _sample_text(normalized, limit=max(CHANGED_SAMPLE_LIMIT, len(normalized)))


def _git_top_level(root: Path, runner: GitRunner | None) -> str | None:
    result = _run_git(root, ("rev-parse", "--show-toplevel"), runner)
    if isinstance(result, str) or result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    if not value:
        return None
    try:
        return str(Path(value).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        return value


def _run_git(root: Path, args: Sequence[str], runner: GitRunner | None) -> subprocess.CompletedProcess[str] | str:
    git = _git_executable()
    if git is None:
        return "git executable unavailable: git"
    command = (git, "-c", "core.quotePath=false", "-C", str(root), *args)
    try:
        if runner:
            return runner(command)
        return subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            encoding=GIT_OUTPUT_ENCODING,
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        return f"git executable unavailable: {exc}"
    except subprocess.TimeoutExpired:
        return f"git command timed out after {GIT_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return f"git command failed: {exc}"


def _run_git_with_input(root: Path, args: Sequence[str], stdin: str) -> subprocess.CompletedProcess[str] | str:
    git = _git_executable()
    if git is None:
        return "git executable unavailable: git"
    command = (git, "-c", "core.quotePath=false", "-C", str(root), *args)
    try:
        return subprocess.run(
            list(command),
            input=stdin,
            check=False,
            capture_output=True,
            text=True,
            encoding=GIT_OUTPUT_ENCODING,
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        return f"git executable unavailable: {exc}"
    except subprocess.TimeoutExpired:
        return f"git command timed out after {GIT_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return f"git command failed: {exc}"


def _first_output_line(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stderr or result.stdout or "").strip()
    return output.splitlines()[0] if output else ""


def _parse_porcelain(text: str | None) -> list[VcsChangedPath]:
    entries: list[VcsChangedPath] = []
    for raw_line in (text or "").splitlines():
        if not raw_line:
            continue
        status = raw_line[:2].strip() or "??"
        path = _decode_git_path(raw_line[3:].strip() if len(raw_line) > 3 else raw_line.strip())
        entries.append(VcsChangedPath(status=status, path=path))
    return entries


def _git_executable() -> str | None:
    return shutil.which("git")


def _decode_git_path(path: str) -> str:
    if len(path) < 2 or not path.startswith('"') or not path.endswith('"'):
        return path
    body = path[1:-1]
    output = bytearray()
    escape_map = {
        "a": b"\a",
        "b": b"\b",
        "f": b"\f",
        "n": b"\n",
        "r": b"\r",
        "t": b"\t",
        "v": b"\v",
        "\\": b"\\",
        '"': b'"',
    }
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            next_char = body[index + 1]
            octal = body[index + 1 : index + 4]
            if len(octal) == 3 and all(ch in "01234567" for ch in octal):
                output.append(int(octal, 8))
                index += 4
                continue
            mapped = escape_map.get(next_char)
            if mapped is not None:
                output.extend(mapped)
                index += 2
                continue
            output.extend(next_char.encode("utf-8", errors="replace"))
            index += 2
            continue
        output.extend(char.encode("utf-8", errors="replace"))
        index += 1
    return output.decode("utf-8", errors="replace")


def _parse_trailer_lines(text: str) -> list[VcsTrailer]:
    trailers: list[VcsTrailer] = []
    for raw_line in text.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip()
        value = " ".join(value.split())
        if key and value:
            trailers.append(VcsTrailer(key=key, value=value))
    return trailers


def _resolve_coordination_root(value: str, root: Path) -> tuple[Path, str]:
    raw = value.strip()
    if not raw:
        return root, f"{COORDINATION_ROOT_ENV_VAR} is empty"
    conflict = _coordination_root_reference_conflict(raw)
    if conflict:
        return root, f"{COORDINATION_ROOT_ENV_VAR} must not use {conflict}: {raw!r}"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        return root, f"{COORDINATION_ROOT_ENV_VAR} must be an absolute path, got {raw!r}"
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        return root, f"{COORDINATION_ROOT_ENV_VAR} could not be resolved: {exc}"
    if not resolved.exists():
        return resolved, f"{COORDINATION_ROOT_ENV_VAR} does not exist: {resolved}"
    if not resolved.is_dir():
        return resolved, f"{COORDINATION_ROOT_ENV_VAR} is not a directory: {resolved}"
    return resolved, ""


def _worktree_coordination_git_findings(root: Path, code_prefix: str, role: str) -> list[Finding]:
    posture = probe_vcs(root)
    if not posture.git_available:
        return [Finding("info", f"{code_prefix}-{role}-git", f"{role} root Git posture unavailable: {posture.detail or 'unknown'}")]
    if not posture.is_worktree:
        return [Finding("info", f"{code_prefix}-{role}-git", f"{role} root is not a Git worktree: {posture.detail or posture.state}")]
    detail = f"state={posture.state}; top_level={posture.top_level or '<unknown>'}; changed_count={posture.changed_count}"
    return [Finding("info", f"{code_prefix}-{role}-git", f"{role} root Git worktree detected; {detail}")]


def _worktree_coordination_record_findings(inventory: Inventory, code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_worktree_coordination_claim_record_findings(inventory, code_prefix))
    findings.extend(_worktree_coordination_agent_run_record_findings(inventory, code_prefix))
    if not findings:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-record-roots",
                "no claim or agent-run records with coordination_root/edit_worktree_root pairs were found",
                "project/verification",
            )
        )
    return findings


def _worktree_coordination_claim_record_findings(inventory: Inventory, code_prefix: str) -> list[Finding]:
    directory = inventory.root / "project/verification/work-claims"
    if not directory.exists() or not directory.is_dir():
        return []
    findings: list[Finding] = []
    for path in sorted(directory.glob("*.json")):
        rel_path = _rel_path(inventory.root, path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        findings.extend(
            _worktree_coordination_record_root_pair_findings(
                code_prefix,
                rel_path,
                "work claim",
                str(data.get("claim_id") or path.stem),
                str(data.get("coordination_root") or ""),
                str(data.get("edit_worktree_root") or ""),
            )
        )
    return findings


def _worktree_coordination_agent_run_record_findings(inventory: Inventory, code_prefix: str) -> list[Finding]:
    from .evidence import agent_run_retired_records

    directory = inventory.root / "project/verification/agent-runs"
    if not directory.exists() or not directory.is_dir():
        return []
    retired_records, retirement_findings = agent_run_retired_records(inventory.root, code_prefix)
    findings: list[Finding] = [*retirement_findings]
    for path in sorted(directory.glob("*.md")):
        rel_path = _rel_path(inventory.root, path)
        if rel_path in retired_records:
            continue
        try:
            frontmatter = parse_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        data = frontmatter.data
        findings.extend(
            _worktree_coordination_record_root_pair_findings(
                code_prefix,
                rel_path,
                "agent run",
                str(data.get("record_id") or path.stem),
                str(data.get("coordination_root") or ""),
                str(data.get("edit_worktree_root") or ""),
            )
        )
    return findings


def _worktree_coordination_record_root_pair_findings(
    code_prefix: str,
    rel_path: str,
    record_kind: str,
    record_id: str,
    coordination_root: str,
    edit_worktree_root: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for label, value in (("coordination_root", coordination_root), ("edit_worktree_root", edit_worktree_root)):
        conflict = _coordination_root_reference_conflict(value)
        if conflict:
            findings.append(
                Finding(
                    "warn",
                    f"{code_prefix}-record-root-unsafe",
                    f"{record_kind} {record_id} names unsafe {label}: {conflict}",
                    rel_path,
                )
            )
    if not coordination_root and not edit_worktree_root:
        return findings
    if coordination_root and edit_worktree_root:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-record-root-pair",
                (
                    f"{record_kind} {record_id} names coordination_root={coordination_root} "
                    f"and edit_worktree_root={edit_worktree_root}; record remains coordination evidence only"
                ),
                rel_path,
            )
        )
        return findings
    missing = "edit_worktree_root" if coordination_root else "coordination_root"
    findings.append(
        Finding(
            "warn",
            f"{code_prefix}-record-root-pair-missing",
            f"{record_kind} {record_id} names only one coordination/edit root; missing {missing}",
            rel_path,
        )
    )
    return findings


def _coordination_root_reference_conflict(value: object) -> str:
    reason = windows_path_reference_reason(value, allow_uri=False, allow_rooted=True)
    return reason if reason in UNSAFE_COORDINATION_ROOT_REFERENCE_REASONS else ""


def _worktree_coordination_boundary_findings(code_prefix: str) -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            (
                "worktree coordination root diagnostics are read-only; they do not create worktrees, clean worktrees, "
                "write claims, write run records, stage, commit, push, or approve lifecycle movement"
            ),
        ),
        Finding(
            "info",
            f"{code_prefix}-authority",
            (
                "repo-visible files in the live coordination root remain authority; MLH_COORDINATION_ROOT is a routing hint, "
                "not hidden state or an access-control boundary"
            ),
        ),
    ]


def _same_resolved_path(first: Path, second: Path) -> bool:
    try:
        return first.resolve() == second.resolve()
    except (OSError, RuntimeError):
        return first == second


def _rel_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
