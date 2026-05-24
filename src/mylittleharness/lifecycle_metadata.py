from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .inventory import Surface


LIFECYCLE_MARKDOWN_FRONTMATTER_REQUIRED_ROUTES = frozenset(
    {
        "adrs",
        "archive",
        "decisions",
        "incubation",
        "research",
        "roadmap",
        "stable-specs",
        "verification",
    }
)
LIFECYCLE_MARKDOWN_FRONTMATTER_OPTIONAL_NAMES = frozenset({"readme.md"})
LIFECYCLE_MARKDOWN_REPAIR_SOURCE = "MyLittleHarness lifecycle frontmatter repair"
DEPRECATED_LIFECYCLE_MARKDOWN_SOURCE_VALUES = {
    "incubate cli": "MyLittleHarness incubation route",
    "mylittleharness repair --apply": LIFECYCLE_MARKDOWN_REPAIR_SOURCE,
}


@dataclass(frozen=True)
class LifecycleMarkdownFrontmatterPlan:
    rel_path: str
    route_id: str
    fields: dict[str, str]
    current_text: str
    updated_text: str
    operation: str = "prepend"


def lifecycle_markdown_requires_frontmatter(surface: Surface) -> bool:
    if surface.path.suffix.lower() != ".md":
        return False
    if surface.path.name.lower() in LIFECYCLE_MARKDOWN_FRONTMATTER_OPTIONAL_NAMES:
        return False
    return surface.memory_route in LIFECYCLE_MARKDOWN_FRONTMATTER_REQUIRED_ROUTES


def lifecycle_markdown_frontmatter_plan(
    surface: Surface,
    *,
    today: date | None = None,
) -> LifecycleMarkdownFrontmatterPlan:
    fields = lifecycle_markdown_frontmatter_fields(surface, today=today)
    updated_text = lifecycle_markdown_text_with_frontmatter(surface.content, fields)
    return LifecycleMarkdownFrontmatterPlan(
        rel_path=surface.rel_path,
        route_id=surface.memory_route,
        fields=fields,
        current_text=surface.content,
        updated_text=updated_text,
    )


def lifecycle_markdown_frontmatter_fields(surface: Surface, *, today: date | None = None) -> dict[str, str]:
    return lifecycle_markdown_frontmatter_fields_for_route(surface.memory_route, _surface_title(surface), today=today)


def lifecycle_markdown_source_provenance_plan(surface: Surface) -> LifecycleMarkdownFrontmatterPlan | None:
    if not lifecycle_markdown_requires_frontmatter(surface):
        return None
    if not surface.frontmatter.has_frontmatter or surface.frontmatter.errors:
        return None
    source = str(surface.frontmatter.data.get("source") or "").strip()
    replacement = lifecycle_markdown_source_replacement(source)
    if not replacement:
        return None
    updated_text = _replace_lifecycle_source_provenance(surface.content, source, replacement)
    if updated_text == surface.content:
        return None
    return LifecycleMarkdownFrontmatterPlan(
        rel_path=surface.rel_path,
        route_id=surface.memory_route,
        fields={"source": replacement},
        current_text=surface.content,
        updated_text=updated_text,
        operation="normalize-source-provenance",
    )


def lifecycle_markdown_source_replacement(source: str) -> str:
    return DEPRECATED_LIFECYCLE_MARKDOWN_SOURCE_VALUES.get(source.strip().casefold(), "")


def lifecycle_markdown_frontmatter_fields_for_route(
    route_id: str,
    title: str,
    *,
    today: date | None = None,
) -> dict[str, str]:
    current_date = (today or date.today()).isoformat()
    title = _clean_scalar(title)
    fields: dict[str, str] = {}

    if route_id == "incubation":
        fields.update({"topic": title, "status": "incubating"})
    elif route_id == "research":
        fields.update({"title": title, "status": "imported"})
    elif route_id == "verification":
        fields.update({"title": title, "status": "pending"})
    elif route_id in {"adrs", "decisions"}:
        fields.update({"title": title, "status": "draft"})
    elif route_id == "roadmap":
        fields.update({"title": title, "status": "active"})
    elif route_id == "stable-specs":
        fields.update({"title": title, "spec_status": "draft", "implementation_posture": "target-only"})
    elif route_id == "archive":
        fields.update({"title": title, "status": "archived"})
    else:
        fields.update({"title": title, "status": "pending"})

    fields.update(
        {
            "created": current_date,
            "updated": current_date,
            "source": LIFECYCLE_MARKDOWN_REPAIR_SOURCE,
            "authority": _route_authority_note(route_id),
        }
    )
    return fields


def lifecycle_markdown_text_with_frontmatter(text: str, fields: dict[str, str]) -> str:
    return render_lifecycle_frontmatter(fields) + text.lstrip("\n")


def render_lifecycle_frontmatter(fields: dict[str, str]) -> str:
    body = "".join(f'{key}: "{_yaml_double_quoted_value(value)}"\n' for key, value in fields.items())
    return f"---\n{body}---\n"


def _surface_title(surface: Surface) -> str:
    for heading in surface.headings:
        if heading.level == 1 and heading.title.strip():
            return _clean_scalar(heading.title)
    stem = surface.path.stem.replace("-", " ").replace("_", " ").strip()
    return _clean_scalar(stem.title() if stem else surface.rel_path)


def _clean_scalar(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or "Untitled"


def _route_authority_note(route_id: str) -> str:
    if route_id in {"adrs", "decisions"}:
        return "draft until explicitly accepted"
    if route_id == "stable-specs":
        return "draft spec metadata restored by repair"
    if route_id == "verification":
        return "evidence pending explicit verification review"
    if route_id == "roadmap":
        return "sequencing surface; item status remains authoritative per entry"
    if route_id == "archive":
        return "historical reference only"
    return "non-authority until promoted"


def _yaml_double_quoted_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _replace_lifecycle_source_provenance(text: str, old: str, new: str) -> str:
    lines = text.splitlines(keepends=True)
    if len(lines) >= 2 and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                break
            if re.match(r"^\s*source\s*:", lines[index]):
                newline = "\n" if lines[index].endswith("\n") else ""
                lines[index] = f'source: "{_yaml_double_quoted_value(new)}"{newline}'
                break
    updated = "".join(lines)
    return re.sub(
        rf"(?m)^(\s*-\s*Source:\s*){re.escape(old)}(\s*)$",
        lambda match: f"{match.group(1)}{new}{match.group(2)}",
        updated,
    )
