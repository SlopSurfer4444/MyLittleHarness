from __future__ import annotations

import glob
import hashlib
import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from .inventory import Inventory, Surface
from .parsing import Frontmatter, extract_headings, extract_path_refs, parse_frontmatter
from .root_boundary import source_path_boundary_violation
from .routes import classify_memory_route


ROOT_RELATIVE_LINK_PREFIXES = (
    ".mylittleharness/",
    ".agents/",
    ".codex/",
    "docs/",
    "project/",
    "specs/",
    "src/",
    "tests/",
)
ROOT_RELATIVE_LINK_NAMES = {"README.md", "AGENTS.md", "pyproject.toml"}
PRODUCT_TARGET_ARTIFACT_PREFIXES = (
    "build_backend/",
    "docs/",
    "src/",
    "tests/",
)
PRODUCT_TARGET_ARTIFACT_NAMES = {"AGENTS.md", "README.md", "pyproject.toml"}
HISTORICAL_LINK_CONTEXT_PREFIXES = (
    ".mylittleharness/generated/",
    "project/archive/",
    "project/verification/",
)
FRONTMATTER_RELATIONSHIP_FIELDS = {
    "archived_plan",
    "archived_to",
    "covered_roadmap_items",
    "implemented_by",
    "merged_from",
    "merged_into",
    "primary_roadmap_item",
    "promoted_to",
    "rejected_by",
    "related_adr",
    "related_adrs",
    "related_decision",
    "related_decisions",
    "related_doc",
    "related_docs",
    "related_incubation",
    "related_plan",
    "related_roadmap",
    "related_roadmap_item",
    "related_research",
    "related_spec",
    "related_specs",
    "related_verification",
    "source_incubation",
    "source_research",
    "source_roadmap",
    "split_from",
    "split_to",
    "superseded_by",
    "supersedes",
    "target_artifacts",
}
ROADMAP_RELATIONSHIP_FIELDS = {
    "source_research",
    "source_incubation",
    "related_specs",
    "related_plan",
    "archived_plan",
    "target_artifacts",
}
ROADMAP_ITEM_RELATIONSHIP_FIELDS = {
    "dependencies",
    "slice_members",
    "slice_dependencies",
    "supersedes",
    "superseded_by",
}
COLD_MEMORY_GLOBS = (
    ("project/archive/plans/*.md", "archived-plan"),
    ("project/archive/reference/**/*.md", "archive-reference"),
)


@dataclass(frozen=True)
class ProjectionSourceRecord:
    path: str
    role: str
    required: bool
    present: bool
    line_count: int
    byte_count: int
    heading_count: int
    link_count: int
    content_hash: str | None
    read_error: str | None = None
    content: str = field(default="", repr=False, compare=False)

    @property
    def readable(self) -> bool:
        return self.present and self.read_error is None


@dataclass(frozen=True)
class ProjectionLinkRecord:
    source: str
    line: int
    target: str
    status: str
    resolution_kind: str


@dataclass(frozen=True)
class ProjectionFanInRecord:
    target: str
    inbound_count: int
    status: str
    sources: tuple[str, ...]
    source: str | None = None


@dataclass(frozen=True)
class ProjectionRelationshipNode:
    id: str
    kind: str
    source: str
    title: str
    status: str
    route: str


@dataclass(frozen=True)
class ProjectionRelationshipEdge:
    source: str
    target: str
    relation: str
    status: str
    source_path: str
    line: int | None = None


@dataclass(frozen=True)
class ProjectionSummary:
    rebuild_status: str
    storage_boundary: str
    source_count: int
    present_source_count: int
    readable_source_count: int
    hashed_source_count: int
    missing_required_count: int
    link_record_count: int
    fan_in_record_count: int
    relationship_node_count: int
    relationship_edge_count: int


@dataclass(frozen=True)
class Projection:
    sources: tuple[ProjectionSourceRecord, ...]
    links: tuple[ProjectionLinkRecord, ...]
    fan_in: tuple[ProjectionFanInRecord, ...]
    relationship_nodes: tuple[ProjectionRelationshipNode, ...]
    relationship_edges: tuple[ProjectionRelationshipEdge, ...]
    summary: ProjectionSummary

    @property
    def source_by_path(self) -> dict[str, ProjectionSourceRecord]:
        return {source.path: source for source in self.sources}


class LinkResolution:
    def __init__(self, kind: str, exists: bool = False) -> None:
        self.kind = kind
        self.exists = exists


def build_projection(inventory: Inventory) -> Projection:
    projection_surfaces = tuple(_projection_surfaces(inventory))
    projection_surface_by_rel = {surface.rel_path: surface for surface in projection_surfaces}
    sources = tuple(_source_record(surface) for surface in projection_surfaces)
    links = tuple(_local_link_records(inventory, projection_surfaces))
    fan_in = tuple(_fan_in_records(projection_surface_by_rel, links))
    relationship_nodes, relationship_edges = _relationship_graph_records(inventory, projection_surfaces, projection_surface_by_rel)
    readable_count = len([source for source in sources if source.readable])
    hashed_count = len([source for source in sources if source.content_hash is not None])
    summary = ProjectionSummary(
        rebuild_status="rebuilt-from-inventory",
        storage_boundary="none",
        source_count=len(sources),
        present_source_count=len([source for source in sources if source.present]),
        readable_source_count=readable_count,
        hashed_source_count=hashed_count,
        missing_required_count=len([source for source in sources if source.required and not source.present]),
        link_record_count=len(links),
        fan_in_record_count=len(fan_in),
        relationship_node_count=len(relationship_nodes),
        relationship_edge_count=len(relationship_edges),
    )
    return Projection(
        sources=sources,
        links=links,
        fan_in=fan_in,
        relationship_nodes=tuple(relationship_nodes),
        relationship_edges=tuple(relationship_edges),
        summary=summary,
    )


def projection_summary_to_dict(projection: Projection) -> dict[str, object]:
    summary = projection.summary
    return {
        "rebuild_status": summary.rebuild_status,
        "storage_boundary": summary.storage_boundary,
        "source_count": summary.source_count,
        "present_source_count": summary.present_source_count,
        "readable_source_count": summary.readable_source_count,
        "hashed_source_count": summary.hashed_source_count,
        "missing_required_count": summary.missing_required_count,
        "link_record_count": summary.link_record_count,
        "fan_in_record_count": summary.fan_in_record_count,
        "relationship_node_count": summary.relationship_node_count,
        "relationship_edge_count": summary.relationship_edge_count,
    }


def _projection_surfaces(inventory: Inventory) -> list[Surface]:
    surfaces: list[Surface] = []
    seen: set[str] = set()
    for surface in inventory.surfaces:
        surfaces.append(surface)
        seen.add(surface.rel_path)
    for surface in _cold_memory_surfaces(inventory):
        if surface.rel_path in seen:
            continue
        surfaces.append(surface)
        seen.add(surface.rel_path)
    return sorted(surfaces, key=lambda item: item.rel_path)


def _cold_memory_surfaces(inventory: Inventory) -> list[Surface]:
    surfaces: list[Surface] = []
    root = inventory.root
    for pattern, role in COLD_MEMORY_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                rel_path = path.relative_to(root).as_posix()
            except ValueError:
                continue
            surfaces.append(_read_projection_surface(root, rel_path, role, path))
    return surfaces


def _read_projection_surface(root: Path, rel_path: str, role: str, path: Path) -> Surface:
    boundary_violation = source_path_boundary_violation(root, path, label=f"{role} source")
    if boundary_violation is not None:
        route = classify_memory_route(rel_path, role)
        return Surface(
            root=root,
            rel_path=rel_path,
            role=role,
            required=False,
            path=path,
            exists=path.exists() or path.is_symlink(),
            read_error=boundary_violation.message,
            memory_route=route.route_id,
            memory_route_target=route.target,
            memory_route_authority=route.authority,
        )
    try:
        content = path.read_text(encoding="utf-8")
        read_error = None
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8", errors="replace")
        read_error = "decoded with replacement characters"
    except OSError as exc:
        route = classify_memory_route(rel_path, role)
        return Surface(
            root=root,
            rel_path=rel_path,
            role=role,
            required=False,
            path=path,
            exists=True,
            read_error=str(exc),
            memory_route=route.route_id,
            memory_route_target=route.target,
            memory_route_authority=route.authority,
        )
    frontmatter = parse_frontmatter(content) if path.suffix.lower() == ".md" else Frontmatter.empty()
    route = classify_memory_route(rel_path, role)
    return Surface(
        root=root,
        rel_path=rel_path,
        role=role,
        required=False,
        path=path,
        exists=True,
        content=content,
        read_error=read_error,
        frontmatter=frontmatter,
        headings=extract_headings(content) if path.suffix.lower() == ".md" else [],
        links=extract_path_refs(content),
        memory_route=route.route_id,
        memory_route_target=route.target,
        memory_route_authority=route.authority,
    )


def resolve_link(root: Path, target: str, source_rel: str | None = None) -> LinkResolution:
    clean = target.strip().strip("<>").strip()
    if not clean:
        return LinkResolution("unresolved", False)
    if clean.startswith("#"):
        return LinkResolution("anchor", True)
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", clean) or clean.startswith("mailto:"):
        return LinkResolution("external", True)
    path_part = clean.split("#", 1)[0]
    if not path_part:
        return LinkResolution("anchor", True)
    base = _link_base(root, path_part, source_rel)
    if any(char in path_part for char in "*?[]{}<>"):
        patterns = _expand_brace_pattern(path_part)
        exists = False
        for pattern in patterns:
            candidate = Path(pattern) if _is_absolute_path(pattern) else base / pattern
            if _path_escapes_root(root, candidate):
                return LinkResolution("unsafe", False)
            resolved_pattern = str(candidate)
            if glob.glob(resolved_pattern):
                exists = True
                break
            if "{" in pattern or "}" in pattern:
                continue
            if Path(resolved_pattern).exists():
                exists = True
                break
        return LinkResolution("pattern", exists)
    if _is_absolute_path(path_part):
        candidate = Path(path_part)
    else:
        candidate = base / path_part
    if _path_escapes_root(root, candidate):
        return LinkResolution("unsafe", False)
    return LinkResolution("local", candidate.exists())


def normalized_link_path(target: str) -> str:
    clean = target.strip().strip("<>").strip()
    if not clean or clean.startswith("#"):
        return ""
    path_part = clean.split("#", 1)[0]
    return re.sub(r"/+", "/", path_part.replace("\\", "/"))


def optional_missing_link_reason(inventory: Inventory, target: str) -> str | None:
    rel = normalized_link_path(target)
    if not rel:
        return None
    root_rel = _root_relative_link_path(inventory, rel)
    if root_rel is not None:
        rel = root_rel

    if inventory.root_kind == "live_operating_root":
        if rel == ".agents/docmap.yaml" and inventory.manifest.get("policy", {}).get("docmap_mode") == "lazy":
            return "docmap is lazy for this live operating root"
        if rel == "README.md":
            return "root README.md is optional for live operating roots"
        if rel == "project/roadmap.md":
            return "project/roadmap.md is an optional live-root roadmap route"
        if rel.startswith(("docs/", "architecture/", "specs/")) and _configured_product_root_contains(inventory, rel):
            return "configured product source root contains this product documentation link; product docs are not required inside the live operating root"

    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    operating_root = normalized_link_path(str(state_data.get("operating_root") or state_data.get("canonical_source_evidence_root") or ""))
    fallback_root = normalized_link_path(str(state_data.get("historical_fallback_root") or ""))
    if operating_root and rel.casefold() == operating_root.rstrip("/").casefold():
        return "configured operating root is external local evidence, not a required in-tree product surface"
    if fallback_root and rel.casefold() == fallback_root.rstrip("/").casefold():
        return "configured fallback/archive root is opt-in local evidence, not a required product surface"
    if operating_root and rel.casefold().startswith(operating_root.rstrip("/").casefold() + "/"):
        rel = rel[len(operating_root.rstrip("/")) + 1 :]

    plan_status = state_data.get("plan_status")
    manifest_plan = "project/implementation-plan.md"
    if inventory.manifest:
        manifest_plan = inventory.manifest.get("memory", {}).get("plan_file", manifest_plan)
    if rel == str(manifest_plan).replace("\\", "/") and plan_status != "active":
        return "the implementation plan is a lazy surface when plan_status is not active"

    if rel == ".mylittleharness/detach/disabled.json":
        return "detach marker is created only when detach is active and may be absent"
    if rel == ".mylittleharness/generated/projection" or rel.startswith(".mylittleharness/generated/projection/"):
        return "generated projection artifacts are disposable navigation output and may be rebuilt when needed"
    if rel in {"project/verification/agent-runs", "project/verification/approval-packets", "project/verification/work-claims"}:
        return "optional evidence directories are created only when those records exist"
    if rel.startswith(("project/verification/agent-runs/", "project/verification/approval-packets/", "project/verification/work-claims/")):
        return "optional evidence records are created only when an agent run, approval packet, or work claim exists"
    if rel in {"project/archive/reference/research", "project/archive/reference/research/"}:
        return "archived research reference directory is optional until research is archived"
    if rel.startswith("project/archive/reference/project-state-history-") and rel.endswith(".md"):
        return "project-state history archive names in docs are examples until compaction creates a concrete file"
    if rel.startswith(".harness/"):
        return "legacy harness sketch paths in research are historical context, not required MLH scaffold"
    if rel in {"files/.agents/docmap.yaml", "files/project/project-state.md"}:
        return "snapshot copied-file paths are relative to a repair snapshot directory, not the repo root"
    if rel == "project/plan-incubation" or rel.startswith("project/plan-incubation/"):
        return "plan incubation surfaces are optional and only exist when a lane is open"

    fixture_root = (
        state_data.get("projection_status") == "candidate-projection"
        or state_data.get("root_role") == "product-source"
        or state_data.get("fixture_status") == "product-compatibility-fixture"
    )
    if fixture_root:
        if (rel == "project/research" or rel.startswith("project/research/")) and rel != "project/research/README.md":
            return "source-root research artifacts are intentionally excluded from this product compatibility fixture"
        if rel == "research/README.md":
            return "the root package-source research mirror is intentionally excluded from this product compatibility fixture"
        if rel.startswith("project/archive/"):
            return "legacy archives are intentionally excluded from this product compatibility fixture"
        if rel == "specs/workflow" or rel.startswith("specs/workflow/"):
            return "root package-source spec mirrors are intentionally excluded from this product source tree"
    return None


def _configured_product_root_contains(inventory: Inventory, rel: str) -> bool:
    product_root = _configured_product_root(inventory)
    if not product_root:
        return False
    base = Path(product_root)
    candidates = [base / rel]
    if rel.startswith(("architecture/", "specs/")):
        candidates.append(base / "docs" / rel)
    return any(candidate.exists() for candidate in candidates)


def _source_record(surface: Surface) -> ProjectionSourceRecord:
    content_hash = None
    if surface.exists and surface.read_error is None:
        content_hash = hashlib.sha256(surface.content.encode("utf-8", errors="replace")).hexdigest()
    return ProjectionSourceRecord(
        path=surface.rel_path,
        role=surface.role,
        required=surface.required,
        present=surface.exists,
        line_count=surface.line_count,
        byte_count=surface.byte_count,
        heading_count=len(surface.headings),
        link_count=len(surface.links),
        content_hash=content_hash,
        read_error=surface.read_error,
        content=surface.content if surface.exists else "",
    )


def _local_link_records(inventory: Inventory, surfaces: tuple[Surface, ...]) -> list[ProjectionLinkRecord]:
    records: list[ProjectionLinkRecord] = []
    seen: set[tuple[str, str, int]] = set()
    for surface in surfaces:
        if not surface.exists:
            continue
        if surface.role == "package-mirror":
            continue
        for link in surface.links:
            key = (surface.rel_path, link.target, link.line)
            if key in seen:
                continue
            seen.add(key)
            resolution = resolve_link(inventory.root, link.target, surface.rel_path)
            if resolution.kind in {"external", "anchor"}:
                continue
            target = normalized_link_path(link.target)
            generated_cache_reason = generated_cache_target_reason(inventory, link.target)
            product_target_reason = product_target_artifact_reason(inventory, surface, link.target, link.line)
            historical_context_reason = historical_link_context_reason(surface, link.target, link.line)
            if resolution.kind == "unresolved":
                status = "unresolved"
            elif resolution.kind == "unsafe":
                status = "unsafe"
            elif generated_cache_reason:
                status = "generated-cache"
            elif resolution.kind == "pattern":
                if resolution.exists:
                    status = "pattern-present"
                elif product_target_reason:
                    status = "product-target"
                elif historical_context_reason:
                    status = "historical-context"
                else:
                    status = "pattern-missing"
            elif product_target_reason:
                status = "product-target"
            elif resolution.exists:
                status = "present"
            elif optional_missing_link_reason(inventory, link.target):
                status = "missing-optional"
            elif historical_context_reason:
                status = "historical-context"
            else:
                status = "missing"
            records.append(ProjectionLinkRecord(surface.rel_path, link.line, target or link.target, status, resolution.kind))
    return sorted(records, key=lambda record: (record.source, record.line, record.target))


def _fan_in_records(surface_by_rel: dict[str, Surface], records: tuple[ProjectionLinkRecord, ...]) -> list[ProjectionFanInRecord]:
    inbound: dict[str, list[ProjectionLinkRecord]] = {}
    for record in records:
        inbound.setdefault(record.target, []).append(record)

    fan_in: list[ProjectionFanInRecord] = []
    for target, target_records in sorted(inbound.items(), key=lambda item: (-len(item[1]), item[0])):
        statuses = {record.status for record in target_records}
        if "unsafe" in statuses:
            status = "unsafe"
        elif "missing" in statuses or "unresolved" in statuses:
            status = "missing"
        elif "missing-optional" in statuses or "pattern-missing" in statuses:
            status = "missing-optional"
        elif "generated-cache" in statuses:
            status = "generated-cache"
        elif "product-target" in statuses:
            status = "product-target"
        elif "historical-context" in statuses:
            status = "historical-context"
        else:
            status = "present"
        fan_in.append(
            ProjectionFanInRecord(
                target=target,
                inbound_count=len(target_records),
                status=status,
                sources=tuple(_unique_sorted(record.source for record in target_records)),
                source=target if target in surface_by_rel else None,
            )
        )
    return fan_in


def _relationship_graph_records(
    inventory: Inventory,
    surfaces: tuple[Surface, ...],
    surface_by_rel: dict[str, Surface],
) -> tuple[list[ProjectionRelationshipNode], list[ProjectionRelationshipEdge]]:
    roadmap_items = _roadmap_items(inventory)
    item_ids = set(roadmap_items)
    nodes: dict[str, ProjectionRelationshipNode] = {}
    edges: set[ProjectionRelationshipEdge] = set()

    for surface in surfaces:
        if not surface.exists:
            continue
        if surface.role == "package-mirror":
            continue
        node = ProjectionRelationshipNode(
            id=surface.rel_path,
            kind=surface.memory_route or surface.role,
            source=surface.rel_path,
            title=_surface_title(surface),
            status=_surface_status(surface),
            route=surface.memory_route,
        )
        nodes[node.id] = node
        key_lines = _frontmatter_key_lines(surface.content)
        for field in sorted(FRONTMATTER_RELATIONSHIP_FIELDS):
            for target in _relationship_values(surface.frontmatter.data.get(field)):
                edge = _relationship_edge(
                    surface.rel_path,
                    target,
                    field,
                    surface.rel_path,
                    key_lines.get(field),
                    inventory,
                    surface_by_rel,
                    item_ids,
                )
                if edge:
                    edges.add(edge)

    for item_id, item in sorted(roadmap_items.items()):
        node_id = _roadmap_item_node_id(item_id)
        nodes[node_id] = ProjectionRelationshipNode(
            id=node_id,
            kind="roadmap-item",
            source="project/roadmap.md",
            title=str(item.get("title") or item_id),
            status=str(item.get("status") or ""),
            route="roadmap",
        )
        for field in sorted(ROADMAP_RELATIONSHIP_FIELDS):
            for target in _relationship_values(item.get(field)):
                edge = _relationship_edge(
                    node_id,
                    target,
                    field,
                    "project/roadmap.md",
                    None,
                    inventory,
                    surface_by_rel,
                    item_ids,
                )
                if edge:
                    edges.add(edge)
        for field in sorted(ROADMAP_ITEM_RELATIONSHIP_FIELDS):
            for target_item in _relationship_values(item.get(field)):
                if not target_item:
                    continue
                status = "present" if target_item in item_ids else "missing"
                edges.add(
                    ProjectionRelationshipEdge(
                        source=node_id,
                        target=_roadmap_item_node_id(target_item),
                        relation=field,
                        status=status,
                        source_path="project/roadmap.md",
                    )
                )

    return (
        sorted(nodes.values(), key=lambda node: (node.kind, node.id)),
        sorted(edges, key=lambda edge: (edge.source, edge.relation, edge.target, edge.source_path, edge.line or 0)),
    )


def _roadmap_item_node_id(item_id: str) -> str:
    return f"project/roadmap.md#{item_id}"


def _relationship_edge(
    source: str,
    target: str,
    relation: str,
    source_path: str,
    line: int | None,
    inventory: Inventory,
    surface_by_rel: dict[str, Surface],
    roadmap_item_ids: set[str],
) -> ProjectionRelationshipEdge | None:
    normalized = _normalized_relationship_target(target, relation)
    if not normalized:
        return None
    status = _relationship_target_status(inventory, surface_by_rel, normalized, roadmap_item_ids, relation)
    return ProjectionRelationshipEdge(
        source=source,
        target=normalized,
        relation=relation,
        status=status,
        source_path=source_path,
        line=line,
    )


def _normalized_relationship_target(target: str, relation: str) -> str:
    clean = str(target or "").strip().strip("`").strip()
    if not clean:
        return ""
    if relation in {"covered_roadmap_items", "primary_roadmap_item", "related_roadmap_item"}:
        return _roadmap_item_node_id(clean)
    return normalized_link_path(clean) or clean


def _relationship_target_status(
    inventory: Inventory,
    surface_by_rel: dict[str, Surface],
    target: str,
    roadmap_item_ids: set[str],
    relation: str = "",
) -> str:
    if target.startswith("project/roadmap.md#"):
        item_id = target.split("#", 1)[1]
        return "present" if item_id in roadmap_item_ids else "missing"
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target) or target.startswith("mailto:"):
        return "external"
    if _is_absolute_path(target):
        rel_target = _root_relative_link_path(inventory, target)
        if rel_target is not None:
            target = rel_target
        else:
            return "unsafe"
    if relation == "target_artifacts" and _is_product_target_artifact_rel(target):
        return "product-target"
    if generated_cache_target_reason(inventory, target):
        return "generated-cache"
    if target in surface_by_rel:
        return "present" if surface_by_rel[target].exists else "missing"
    if _path_escapes_root(inventory.root, inventory.root / target):
        return "unsafe"
    if (inventory.root / target).exists():
        return "present"
    return "missing"


def product_target_artifact_reason(inventory: Inventory, surface: Surface, target: str, line: int | None) -> str | None:
    rel = normalized_link_path(target)
    if not rel:
        return None
    root_rel = _root_relative_link_path(inventory, rel)
    if root_rel is not None:
        rel = root_rel

    if inventory.root_kind != "live_operating_root" or not _is_product_target_artifact_rel(rel):
        return None
    product_root = _configured_product_root(inventory)
    if not (
        _line_has_product_target_context(surface, line)
        or (
            product_root
            and _configured_product_root_contains(inventory, rel)
            and _line_has_product_source_prose_context(surface, line)
        )
    ):
        return None

    if product_root:
        return (
            f"{rel} is product-source target metadata or product-source evidence; "
            f"product files are not required inside this live operating root; "
            f"configured product source root: {product_root}"
        )
    return f"{rel} is product-source target metadata or product-source evidence; product files are not required inside this live operating root"


def generated_cache_target_reason(inventory: Inventory, target: str) -> str | None:
    rel = normalized_link_path(target)
    if not rel:
        return None
    root_rel = _root_relative_link_path(inventory, rel)
    if root_rel is not None:
        rel = root_rel
    if rel == ".mylittleharness/generated/projection" or rel.startswith(".mylittleharness/generated/projection/"):
        return f"{rel} is disposable generated projection cache; source files remain authoritative"
    return None


def historical_link_context_reason(surface: Surface, target: str, line: int | None) -> str | None:
    rel = normalized_link_path(target)
    if not rel:
        return None
    if surface.rel_path.startswith(HISTORICAL_LINK_CONTEXT_PREFIXES):
        return "reference appears in verification, archive, or generated navigation history; it is not a current link repair target unless current authority depends on it"
    if _is_retired_research_prompt_packet_context(surface, rel, line):
        return "reference appears in retired research-prompt packet/rubric context; treat as historical route evidence unless current product source restores the command/spec"
    if _is_research_archive_inventory_context(surface, rel, line):
        return "reference appears in a research audit inventory of missing roadmap-referenced archive files; review archive-context or roadmap diagnostics before any restore or retarget action"
    if _is_research_claim_example_context(surface, rel, line):
        return "reference appears in an illustrative research claim payload, not as current repo link repair evidence"
    if _is_research_non_gate_partial_input_context(surface, rel, line):
        return "reference is described as older partial research input, not the gate-closing source for the current distillate"
    return None


def _is_retired_research_prompt_packet_context(surface: Surface, rel: str, line: int | None) -> bool:
    if line is None or line < 1:
        return False
    if rel != "docs/specs/research-prompt-packets.md":
        return False
    if not surface.rel_path.startswith("project/research/"):
        return False
    lines = surface.content.splitlines()
    start = max(0, line - 4)
    end = min(len(lines), line + 2)
    window = "\n".join(lines[start:end]).casefold()
    return any(marker in window for marker in ("research-prompt", "prompt packet", "prompt packets", "default packets"))


def _is_research_archive_inventory_context(surface: Surface, rel: str, line: int | None) -> bool:
    if line is None or line < 1:
        return False
    if not surface.rel_path.startswith("project/research/"):
        return False
    if not rel.startswith("project/archive/plans/"):
        return False
    heading = _nearest_heading_title(surface, line).casefold()
    return "missing roadmap-referenced archive files" in heading


def _is_research_claim_example_context(surface: Surface, rel: str, line: int | None) -> bool:
    if line is None or line < 1:
        return False
    if not surface.rel_path.startswith("project/research/"):
        return False
    if not rel.startswith(("src/", "tests/", "docs/", "build_backend/")):
        return False
    text = _line_text(surface, line).casefold()
    return ("'agent'" in text or '"agent"' in text) and ("'claim'" in text or '"claim"' in text)


def _is_research_non_gate_partial_input_context(surface: Surface, rel: str, line: int | None) -> bool:
    if line is None or line < 1:
        return False
    if not surface.rel_path.startswith("project/research/"):
        return False
    if not rel.startswith("project/research/"):
        return False
    text = _line_text(surface, line).casefold()
    return "older" in text and "partial input only" in text and "not the gate-closing source" in text


def _is_product_target_artifact_rel(rel: str) -> bool:
    normalized = normalized_link_path(rel).strip("/")
    if normalized in PRODUCT_TARGET_ARTIFACT_NAMES:
        return True
    return any(normalized.startswith(prefix) for prefix in PRODUCT_TARGET_ARTIFACT_PREFIXES)


def _line_has_product_target_context(surface: Surface, line: int | None) -> bool:
    if line is None or line < 1:
        return False
    lines = surface.content.splitlines()
    if line > len(lines):
        return False
    current = lines[line - 1].casefold()
    if any(marker in current for marker in ("target_artifacts", "target artifact", "target-artifact")):
        return True
    return _frontmatter_key_for_line(lines, line) == "target_artifacts"


def _line_has_product_source_prose_context(surface: Surface, line: int | None) -> bool:
    text = _line_text(surface, line).casefold()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            "product source",
            "product-source",
            "product root",
            "product-root",
            "product-only",
            "product full suite",
            "clean product",
            "product tests",
            "product focused",
        )
    )


def _line_text(surface: Surface, line: int | None) -> str:
    if line is None or line < 1:
        return ""
    lines = surface.content.splitlines()
    if line > len(lines):
        return ""
    return lines[line - 1]


def _nearest_heading_title(surface: Surface, line: int) -> str:
    title = ""
    for heading in surface.headings:
        if heading.line > line:
            break
        title = heading.title
    return title


def _frontmatter_key_for_line(lines: list[str], line: int) -> str:
    if not lines or lines[0].strip() != "---":
        return ""
    key = ""
    for index, raw_line in enumerate(lines[1:], start=2):
        stripped = raw_line.strip()
        if stripped == "---":
            break
        if index > line:
            break
        match = re.match(r"^([A-Za-z0-9_-]+):", raw_line)
        if match:
            key = match.group(1)
    return key


def _configured_product_root(inventory: Inventory) -> str:
    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    return str(state_data.get("product_source_root") or state_data.get("projection_root") or "").strip()


def _relationship_values(value: object) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = ast.literal_eval(stripped)
            except (SyntaxError, ValueError):
                parsed = ()
            if isinstance(parsed, list):
                return tuple(str(item).strip() for item in parsed if str(item).strip())
        return (stripped,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),)


def _surface_title(surface: Surface) -> str:
    for key in ("title", "topic", "project", "id"):
        value = surface.frontmatter.data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for heading in surface.headings:
        if heading.level == 1 and heading.title.strip():
            return heading.title.strip()
    return Path(surface.rel_path).stem


def _surface_status(surface: Surface) -> str:
    value = surface.frontmatter.data.get("status")
    return str(value or "").strip()


def _frontmatter_key_lines(text: str) -> dict[str, int]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    key_lines: dict[str, int] = {}
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            break
        match = re.match(r"^([A-Za-z0-9_-]+):", line)
        if match:
            key_lines.setdefault(match.group(1), index)
    return key_lines


def _roadmap_items(inventory: Inventory) -> dict[str, dict[str, object]]:
    surface = inventory.surface_by_rel.get("project/roadmap.md")
    if not surface or not surface.exists:
        return {}
    lines = surface.content.splitlines()
    items: dict[str, dict[str, object]] = {}
    current: dict[str, object] = {}
    current_title = ""
    in_items = False
    for line in lines:
        if re.match(r"^##\s+Items\s*$", line.strip()):
            in_items = True
            continue
        if in_items and re.match(r"^##\s+\S", line.strip()):
            break
        if not in_items:
            continue
        heading = re.match(r"^###\s+(.+?)\s*$", line.strip())
        if heading:
            _store_roadmap_item(items, current_title, current)
            current = {}
            current_title = heading.group(1).strip()
            continue
        match = re.match(r"^-\s+`([A-Za-z0-9_-]+)`:\s*(.*?)\s*$", line.strip())
        if not match:
            continue
        key = match.group(1)
        raw = match.group(2).strip()
        if raw.startswith("`") and raw.endswith("`"):
            raw = raw[1:-1]
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
                parsed = []
            current[key] = parsed if isinstance(parsed, list) else []
        else:
            current[key] = raw
    _store_roadmap_item(items, current_title, current)
    return items


def _store_roadmap_item(items: dict[str, dict[str, object]], title: str, fields: dict[str, object]) -> None:
    item_id = fields.get("id")
    if not isinstance(item_id, str) or not item_id:
        return
    row = dict(fields)
    row["title"] = title
    items[item_id] = row


def _link_base(root: Path, path_part: str, source_rel: str | None) -> Path:
    normalized = normalized_link_path(path_part)
    if source_rel and source_rel.startswith("docs/") and normalized.startswith(("architecture/", "specs/")):
        return root / Path(source_rel).parent
    if not source_rel or _is_repo_root_relative_link(normalized):
        return root
    source_parent = Path(source_rel).parent
    if str(source_parent) in ("", "."):
        return root
    return root / source_parent


def _is_repo_root_relative_link(normalized: str) -> bool:
    if normalized in ROOT_RELATIVE_LINK_NAMES:
        return True
    return any(normalized.startswith(prefix) for prefix in ROOT_RELATIVE_LINK_PREFIXES)


def _expand_brace_pattern(value: str) -> list[str]:
    match = re.search(r"\{([^{}]+)\}", value)
    if not match:
        return [value]
    prefix = value[: match.start()]
    suffix = value[match.end() :]
    return [prefix + option + suffix for option in match.group(1).split(",")]


def _is_absolute_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or Path(value).is_absolute()


def _root_relative_link_path(inventory: Inventory, rel: str) -> str | None:
    if not _is_absolute_path(rel):
        return None
    root = normalized_link_path(str(inventory.root)).rstrip("/")
    if rel.casefold() == root.casefold():
        return ""
    prefix = root + "/"
    if rel.casefold().startswith(prefix.casefold()):
        return rel[len(prefix) :]
    return None


def _path_escapes_root(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return False
    except (OSError, RuntimeError, ValueError):
        return True


def _unique_sorted(values) -> list[str]:
    return sorted(set(values))
