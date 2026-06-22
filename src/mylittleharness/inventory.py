from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .parsing import Frontmatter, Heading, LinkRef, extract_headings, extract_path_refs, parse_frontmatter
from .root_boundary import (
    AMBIGUOUS_ROOT,
    FALLBACK_OR_ARCHIVE,
    LIVE_OPERATING_ROOT,
    PRODUCT_SOURCE_FIXTURE,
    same_resolved_path,
    source_path_boundary_violation,
)
from .routes import classify_memory_route


EXPECTED_SPEC_NAMES = (
    "workflow-artifact-model-spec.md",
    "workflow-plan-synthesis-spec.md",
    "workflow-verification-and-closeout-spec.md",
    "workflow-rollout-slices-spec.md",
    "workflow-capability-roadmap-spec.md",
)
WORKFLOW_MANIFEST_REL = ".mylittleharness/project-workflow.toml"
LEGACY_WORKFLOW_MANIFEST_REL = ".codex/project-workflow.toml"
WORKFLOW_MANIFEST_CANDIDATE_RELS = (WORKFLOW_MANIFEST_REL, LEGACY_WORKFLOW_MANIFEST_REL)


class RootLoadError(Exception):
    pass


@dataclass
class SectionSpan:
    title: str
    line: int
    length: int


@dataclass
class Surface:
    root: Path
    rel_path: str
    role: str
    required: bool
    path: Path
    exists: bool
    content: str = ""
    read_error: str | None = None
    frontmatter: Frontmatter = field(default_factory=Frontmatter.empty)
    headings: list[Heading] = field(default_factory=list)
    links: list[LinkRef] = field(default_factory=list)
    memory_route: str = ""
    memory_route_target: str = ""
    memory_route_authority: str = ""

    @property
    def line_count(self) -> int:
        if not self.content:
            return 0
        return len(self.content.splitlines())

    @property
    def char_count(self) -> int:
        return len(self.content)

    @property
    def byte_count(self) -> int:
        return len(self.content.encode("utf-8", errors="replace"))

    def largest_sections(self, limit: int = 3) -> list[SectionSpan]:
        if not self.headings:
            return []
        line_count = self.line_count
        spans: list[SectionSpan] = []
        for index, heading in enumerate(self.headings):
            next_line = line_count + 1
            for candidate in self.headings[index + 1 :]:
                if candidate.level <= heading.level:
                    next_line = candidate.line
                    break
            spans.append(SectionSpan(heading.title, heading.line, max(0, next_line - heading.line)))
        spans.sort(key=lambda item: (-item.length, item.line, item.title))
        return spans[:limit]


@dataclass
class Inventory:
    root: Path
    root_kind: str
    surfaces: list[Surface]
    manifest: dict[str, Any]
    manifest_errors: list[str]
    manifest_warnings: list[str]
    surface_by_rel: dict[str, Surface]
    state: Surface | None
    manifest_surface: Surface | None
    manifest_candidate_surfaces: tuple[Surface, ...]
    active_plan_surface: Surface | None

    @property
    def present_surfaces(self) -> list[Surface]:
        return [surface for surface in self.surfaces if surface.exists]

    def sources_for_report(self) -> list[str]:
        rows = []
        for surface in sorted(self.surfaces, key=lambda item: item.rel_path):
            presence = "present" if surface.exists else "missing"
            requirement = "required" if surface.required else "optional"
            rows.append(f"{surface.rel_path} [{surface.role}; {requirement}; {presence}]")
        return rows


@dataclass(frozen=True)
class TargetArtifactOwnership:
    artifact: str
    ownership: str
    intended_root: str
    guidance: str


PRODUCT_SOURCE_TARGET_PREFIXES = ("build_backend/", "docs/", "src/", "tests/")
PRODUCT_SOURCE_TARGET_NAMES = {"AGENTS.md", "README.md", "pyproject.toml", "uv.lock"}
OPERATING_MEMORY_TARGET_PREFIXES = (".agents/", ".codex/", "project/")
OPERATING_MEMORY_TARGET_NAMES = {WORKFLOW_MANIFEST_REL}
GENERATED_CACHE_TARGET_PREFIXES = (".mylittleharness/generated/",)
ARCHIVE_EVIDENCE_TARGET_PREFIXES = ("project/archive/",)


def target_artifact_ownerships(inventory: Inventory, artifacts: tuple[str, ...] | list[str]) -> tuple[TargetArtifactOwnership, ...]:
    return tuple(target_artifact_ownership(inventory, artifact) for artifact in artifacts if str(artifact or "").strip())


def target_artifact_ownership(inventory: Inventory, artifact: str) -> TargetArtifactOwnership:
    rel = _normalize_target_artifact(artifact)
    if not rel:
        return TargetArtifactOwnership(artifact=artifact, ownership="unknown", intended_root="unknown", guidance="empty target artifact")
    if rel.startswith(ARCHIVE_EVIDENCE_TARGET_PREFIXES):
        return TargetArtifactOwnership(rel, "archive-evidence", "operating-root", "historical evidence route; not a live product write target")
    if rel.startswith(GENERATED_CACHE_TARGET_PREFIXES):
        return TargetArtifactOwnership(rel, "generated-cache", "generated-output", "disposable generated cache; source files remain authority")
    if rel in OPERATING_MEMORY_TARGET_NAMES or rel.startswith(OPERATING_MEMORY_TARGET_PREFIXES):
        return TargetArtifactOwnership(rel, "operating-memory-route", "operating-root", "MLH operating memory route owned by the serviced root")
    if _is_product_source_target_artifact(rel):
        if inventory.root_kind == "product_source_fixture":
            return TargetArtifactOwnership(rel, "product-compat-fixture", "product-source-fixture", "product fixture target; not live operating memory")
        product_root = _configured_product_source_root(inventory)
        if inventory.root_kind == "live_operating_root" and product_root:
            return TargetArtifactOwnership(
                rel,
                "product-source-artifact",
                f"product_source_root={product_root}",
                "edit in configured product_source_root; no automatic mirror or product mutation is implied",
            )
        return TargetArtifactOwnership(
            rel,
            "unknown",
            "product-source-uncertain",
            "source-like target but product_source_root is not configured; keep closeout wording provisional",
        )
    return TargetArtifactOwnership(rel, "unknown", "unknown", "no ownership rule matched; inspect the route before mutation")


def _normalize_target_artifact(value: str) -> str:
    rel = str(value or "").strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.strip("/")


def _is_product_source_target_artifact(rel: str) -> bool:
    return rel in PRODUCT_SOURCE_TARGET_NAMES or any(rel.startswith(prefix) for prefix in PRODUCT_SOURCE_TARGET_PREFIXES)


def _configured_product_source_root(inventory: Inventory) -> str:
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    value = str(data.get("product_source_root") or data.get("projection_root") or "").strip()
    if not value:
        return ""
    try:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = inventory.root / path
        return str(path.resolve())
    except (OSError, RuntimeError):
        return value


def load_inventory(root: Path | str) -> Inventory:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise RootLoadError(f"target root does not exist: {root_path}")
    if not root_path.is_dir():
        raise RootLoadError(f"target root is not a directory: {root_path}")

    surfaces: dict[str, Surface] = {}

    def add(rel_path: str, role: str, required: bool) -> Surface:
        normalized = rel_path.replace("\\", "/")
        if normalized in surfaces:
            existing = surfaces[normalized]
            existing.required = existing.required or required
            if existing.role == "optional":
                existing.role = role
                route = classify_memory_route(existing.rel_path, existing.role)
                existing.memory_route = route.route_id
                existing.memory_route_target = route.target
                existing.memory_route_authority = route.authority
            return existing
        path = root_path / normalized
        surface = _read_surface(root_path, normalized, role, required, path)
        surfaces[normalized] = surface
        return surface

    manifest_candidates = tuple(add(rel_path, "manifest", False) for rel_path in WORKFLOW_MANIFEST_CANDIDATE_RELS)
    manifest_surface = _select_manifest_surface(manifest_candidates)
    manifest_surface.required = True
    manifest, manifest_errors = _parse_manifest(manifest_surface)
    manifest_warnings = _manifest_resolution_warnings(manifest_candidates, manifest_surface)
    state_rel = manifest.get("memory", {}).get("state_file", "project/project-state.md") if manifest else "project/project-state.md"
    plan_rel = manifest.get("memory", {}).get("plan_file", "project/implementation-plan.md") if manifest else "project/implementation-plan.md"

    state = add(state_rel, "project-state", True)
    root_kind = _classify_root_kind(root_path, manifest, state)
    readme = add("README.md", "orientation", root_kind != "live_operating_root")
    agents = add("AGENTS.md", "operator-contract", True)

    docmap_required = _docmap_is_required(readme, agents, state, manifest_surface)
    if root_kind == "live_operating_root" and _docmap_mode_is_lazy(manifest):
        docmap_required = False
    if docmap_required or (root_path / ".agents/docmap.yaml").exists():
        add(".agents/docmap.yaml", "docmap", docmap_required)
    if (root_path / ".mylittleharness/detach/disabled.json").exists():
        add(".mylittleharness/detach/disabled.json", "detach-marker", False)

    plan_status = state.frontmatter.data.get("plan_status") if state and state.exists else None
    active_plan_rel = state.frontmatter.data.get("active_plan") or plan_rel
    active_plan_surface: Surface | None = None
    if plan_status == "active" or (root_path / active_plan_rel).exists():
        active_plan_surface = add(active_plan_rel, "active-plan", plan_status == "active")

    if (root_path / "project/roadmap.md").exists():
        add("project/roadmap.md", "roadmap", False)

    for name in EXPECTED_SPEC_NAMES:
        add(f"project/specs/workflow/{name}", "stable-spec", True)

    _add_optional_glob(root_path, surfaces, "project/specs/**/*.md", "stable-spec")
    _add_optional_glob(root_path, surfaces, "docs/**/*.md", "product-doc")
    _add_optional_glob(root_path, surfaces, "project/adrs/*.md", "adr")
    _add_optional_glob(root_path, surfaces, "project/decisions/*.md", "decision")
    _add_optional_glob(root_path, surfaces, "project/plan-incubation/*.md", "incubation")
    _add_optional_glob(root_path, surfaces, "project/operator-prompts/*.md", "operator-prompt")
    _add_optional_glob(root_path, surfaces, "project/drafts/*.md", "draft")
    _add_optional_glob(root_path, surfaces, "project/research/*.md", "research")
    _add_optional_glob(root_path, surfaces, "project/attachments/**/artifact.md", "attachment")
    _add_optional_glob(root_path, surfaces, "project/verification/*.md", "verification")
    _add_optional_glob(root_path, surfaces, "project/verification/agent-runs/*.md", "agent-run")
    _add_optional_glob(root_path, surfaces, "project/verification/handoffs/*.md", "handoff-note")
    _add_optional_glob(root_path, surfaces, "project/verification/handoffs/*.json", "handoff")
    _add_optional_glob(root_path, surfaces, "project/verification/work-claims/*.json", "work-claim")
    _add_optional_glob(root_path, surfaces, "project/verification/approval-packets/*.json", "approval-packet")
    _add_optional_glob(root_path, surfaces, "project/symphony/queue/*.json", "symphony-queue")
    _add_optional_glob(root_path, surfaces, "specs/workflow/*.md", "package-mirror")

    ordered = sorted(surfaces.values(), key=lambda item: item.rel_path)
    return Inventory(
        root=root_path,
        root_kind=root_kind,
        surfaces=ordered,
        manifest=manifest,
        manifest_errors=manifest_errors,
        manifest_warnings=manifest_warnings,
        surface_by_rel={surface.rel_path: surface for surface in ordered},
        state=surfaces.get(state_rel.replace("\\", "/")),
        manifest_surface=manifest_surface,
        manifest_candidate_surfaces=manifest_candidates,
        active_plan_surface=active_plan_surface,
    )


def _select_manifest_surface(candidates: tuple[Surface, ...]) -> Surface:
    for surface in candidates:
        if surface.exists:
            return surface
    return candidates[0]


def _manifest_resolution_warnings(candidates: tuple[Surface, ...], selected: Surface) -> list[str]:
    warnings: list[str] = []
    by_rel = {surface.rel_path: surface for surface in candidates}
    neutral = by_rel.get(WORKFLOW_MANIFEST_REL)
    legacy = by_rel.get(LEGACY_WORKFLOW_MANIFEST_REL)
    if not neutral or not legacy or not neutral.exists or not legacy.exists:
        return warnings
    if selected.rel_path != WORKFLOW_MANIFEST_REL:
        return warnings
    if neutral.read_error or legacy.read_error:
        warnings.append(
            (
                f"both {WORKFLOW_MANIFEST_REL} and {LEGACY_WORKFLOW_MANIFEST_REL} are present; "
                "using the neutral manifest, but one candidate could not be read cleanly"
            )
        )
    elif neutral.content != legacy.content:
        warnings.append(
            (
                f"both {WORKFLOW_MANIFEST_REL} and {LEGACY_WORKFLOW_MANIFEST_REL} are present and differ; "
                f"using {WORKFLOW_MANIFEST_REL}"
            )
        )
    return warnings


def _read_surface(root: Path, rel_path: str, role: str, required: bool, path: Path) -> Surface:
    boundary_violation = source_path_boundary_violation(root, path, label=f"{role} source")
    if boundary_violation is not None:
        return Surface(
            root=root,
            rel_path=rel_path,
            role=role,
            required=required,
            path=path,
            exists=path.exists() or path.is_symlink(),
            read_error=boundary_violation.message,
        )
    if not path.exists():
        return Surface(root=root, rel_path=rel_path, role=role, required=required, path=path, exists=False)
    try:
        content = path.read_text(encoding="utf-8")
        read_error = None
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8", errors="replace")
        read_error = "decoded with replacement characters"
    except OSError as exc:
        return Surface(root=root, rel_path=rel_path, role=role, required=required, path=path, exists=True, read_error=str(exc))
    frontmatter = parse_frontmatter(content) if path.suffix.lower() == ".md" else Frontmatter.empty()
    if rel_path == "project/project-state.md" and not frontmatter.has_frontmatter:
        frontmatter = _parse_project_state_assignments(content)
    headings = extract_headings(content) if path.suffix.lower() == ".md" else []
    links = extract_path_refs(content)
    route = classify_memory_route(rel_path, role)
    return Surface(
        root=root,
        rel_path=rel_path,
        role=role,
        required=required,
        path=path,
        exists=True,
        content=content,
        read_error=read_error,
        frontmatter=frontmatter,
        headings=headings,
        links=links,
        memory_route=route.route_id,
        memory_route_target=route.target,
        memory_route_authority=route.authority,
    )


def _parse_manifest(surface: Surface) -> tuple[dict[str, Any], list[str]]:
    if not surface.exists or not surface.content:
        return {}, []
    try:
        return tomllib.loads(surface.content), []
    except tomllib.TOMLDecodeError as exc:
        return {}, [f"{surface.rel_path}: {exc}"]


def _docmap_is_required(*surfaces: Surface) -> bool:
    return any(surface.exists and ".agents/docmap.yaml" in surface.content for surface in surfaces)


STATE_ASSIGNMENT_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")
STATE_ASSIGNMENT_KEYS = {
    "project",
    "workflow",
    "workflow_version",
    "root_role",
    "fixture_status",
    "operating_mode",
    "plan_status",
    "active_plan",
    "active_phase",
    "phase_status",
    "last_archived_plan",
    "operating_root",
    "canonical_source_evidence_root",
    "product_source_root",
    "projection_root",
    "projection_status",
    "historical_fallback_root",
}
LIVE_ROOT_CLASSIFICATION_KEYS = {
    "project",
    "workflow",
    "operating_mode",
    "plan_status",
    "active_plan",
    "active_phase",
    "phase_status",
}


def _parse_project_state_assignments(text: str) -> Frontmatter:
    data: dict[str, object] = {}
    for line in text.splitlines():
        match = STATE_ASSIGNMENT_RE.match(line.strip())
        if not match:
            continue
        key = match.group(1)
        if key not in STATE_ASSIGNMENT_KEYS:
            continue
        data[key] = _parse_assignment_scalar(match.group(2).strip())
    return Frontmatter(has_frontmatter=False, data=data)


def _parse_assignment_scalar(raw_value: str) -> object:
    value = raw_value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def _classify_root_kind(root: Path, manifest: dict[str, Any], state: Surface) -> str:
    data = state.frontmatter.data if state and state.exists else {}
    if (
        data.get("root_role") == "product-source"
        or data.get("fixture_status") == "product-compatibility-fixture"
        or _same_path_value(data.get("product_source_root"), root)
    ):
        return PRODUCT_SOURCE_FIXTURE

    role = str(data.get("root_role") or "").casefold()
    fixture_status = str(data.get("fixture_status") or "").casefold()
    if role in {"fallback", "historical-fallback", "archive", "archive-only", "generated-output"}:
        return FALLBACK_OR_ARCHIVE
    if any(marker in fixture_status for marker in ("fallback", "archive", "generated-output")):
        return FALLBACK_OR_ARCHIVE
    if _same_path_value(data.get("historical_fallback_root"), root):
        return FALLBACK_OR_ARCHIVE

    if manifest.get("workflow") == "workflow-core" and _state_can_classify_live_root(state):
        return LIVE_OPERATING_ROOT
    return AMBIGUOUS_ROOT


def _state_can_classify_live_root(state: Surface | None) -> bool:
    if state is None or not state.exists:
        return False
    frontmatter = state.frontmatter
    if frontmatter.has_frontmatter and frontmatter.errors:
        return False
    return any(key in frontmatter.data for key in LIVE_ROOT_CLASSIFICATION_KEYS)


def _docmap_mode_is_lazy(manifest: dict[str, Any]) -> bool:
    policy = manifest.get("policy", {}) if isinstance(manifest, dict) else {}
    return policy.get("docmap_mode") == "lazy"


def _same_path_value(value: object, expected: Path) -> bool:
    if not value:
        return False
    normalized = str(value).replace("\\\\", "\\")
    try:
        candidate = Path(normalized).expanduser()
        if not candidate.is_absolute():
            candidate = expected / candidate
        return same_resolved_path(candidate, expected)
    except (OSError, RuntimeError):
        return normalized.replace("/", "\\").rstrip("\\").casefold() == str(expected).replace("/", "\\").rstrip("\\").casefold()


def _add_optional_glob(root: Path, surfaces: dict[str, Surface], pattern: str, role: str) -> None:
    for path in sorted(root.glob(pattern)):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root).as_posix()
        if rel_path in surfaces:
            continue
        surfaces[rel_path] = _read_surface(root, rel_path, role, False, path)
