from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Frontmatter:
    has_frontmatter: bool = False
    data: dict[str, object] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    body_start_line: int = 1

    @classmethod
    def empty(cls) -> "Frontmatter":
        return cls()


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line: int


@dataclass(frozen=True)
class LinkRef:
    target: str
    line: int
    source: str


KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
QUOTED_RE = re.compile(r"['\"]([^'\"]+)['\"]")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
PATH_WITH_PROSE_SUFFIX_RE = re.compile(
    r"^((?:[A-Za-z]:[\\/]|\.{1,2}[\\/]|\.mylittleharness/|\.agents/|\.codex/|docs/|project/|specs/|src/|tests/|[A-Za-z0-9_.-]+/)"
    r"[^\s`'\"<>]+?\.(?:md|yaml|yml|toml|py|txt|json|zip|docx|pdf))(?:\s+.+)$",
    re.IGNORECASE,
)


def parse_frontmatter(text: str) -> Frontmatter:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return Frontmatter.empty()

    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return Frontmatter(True, {}, ["frontmatter opening marker has no closing marker"], len(lines) + 1)

    data: dict[str, object] = {}
    errors: list[str] = []
    current_key: str | None = None
    for index, line in enumerate(lines[1:closing_index], start=2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_key is None:
                errors.append(f"line {index}: list item has no key")
                continue
            current_value = data.setdefault(current_key, [])
            if not isinstance(current_value, list):
                errors.append(f"line {index}: list item follows scalar key {current_key}")
                continue
            current_value.append(_parse_scalar(stripped[2:].strip()))
            continue
        if line.startswith((" ", "\t")):
            errors.append(f"line {index}: nested YAML is not supported by the tolerant parser")
            continue
        match = KEY_RE.match(line)
        if not match:
            errors.append(f"line {index}: expected top-level key: value")
            current_key = None
            continue
        key = match.group(1)
        raw_value = match.group(2).strip()
        if raw_value == "":
            data[key] = []
        else:
            data[key] = _parse_scalar(raw_value)
        current_key = key

    return Frontmatter(True, data, errors, closing_index + 2)


def parse_frontmatter_top_level_scalars(text: str) -> Frontmatter:
    """Read only top-level scalar frontmatter keys without interpreting nested YAML."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return Frontmatter.empty()

    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return Frontmatter(True, {}, ["frontmatter opening marker has no closing marker"], len(lines) + 1)

    data: dict[str, object] = {}
    for line in lines[1:closing_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("- ") or line.startswith((" ", "\t")):
            continue
        match = KEY_RE.match(line)
        if not match:
            continue
        key = match.group(1)
        raw_value = match.group(2).strip()
        data[key] = _parse_scalar(raw_value) if raw_value else ""

    return Frontmatter(True, data, [], closing_index + 2)


def extract_headings(text: str) -> list[Heading]:
    headings: list[Heading] = []
    for index, line in enumerate(text.splitlines(), start=1):
        match = HEADING_RE.match(line)
        if match:
            headings.append(Heading(len(match.group(1)), match.group(2).strip(), index))
    return headings


def extract_path_refs(text: str) -> list[LinkRef]:
    refs: list[LinkRef] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        refs.extend(_refs_from_regex(line, line_number, MARKDOWN_LINK_RE, "markdown-link"))
        refs.extend(_refs_from_regex(line, line_number, BACKTICK_RE, "backtick-path"))
        refs.extend(_refs_from_regex(line, line_number, QUOTED_RE, "quoted-path"))
    deduped: list[LinkRef] = []
    seen: set[tuple[str, int, str]] = set()
    for ref in refs:
        key = (ref.target, ref.line, ref.source)
        if key not in seen:
            deduped.append(ref)
            seen.add(key)
    return deduped


def _refs_from_regex(line: str, line_number: int, regex: re.Pattern[str], source: str) -> list[LinkRef]:
    refs = []
    for match in regex.finditer(line):
        target = match.group(1).strip()
        normalized_target = _path_ref_target(target)
        if normalized_target:
            refs.append(LinkRef(normalized_target, line_number, source))
    return refs


def _path_ref_target(value: str) -> str:
    value = value.strip()
    if _looks_like_path_ref(value):
        suffix_match = PATH_WITH_PROSE_SUFFIX_RE.match(value.replace("\\", "/"))
        if suffix_match:
            return suffix_match.group(1)
        if re.search(r"\s", value):
            return ""
        return value
    return ""


def _looks_like_path_ref(value: str) -> bool:
    value = value.strip()
    if not value or value.startswith("#"):
        return False
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value) or value.startswith("mailto:"):
        return True
    normalized = value.replace("\\", "/")
    if re.search(r"\s", value) and not (
        re.match(r"^[A-Za-z]:[\\/]", value)
        or normalized.startswith(("./", "../", ".agents/", ".codex/", "project/", "specs/", "src/", "tests/"))
    ):
        return False
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return True
    if value.startswith(("./", "../", ".\\", "..\\")):
        return True
    if normalized in {"README.md", "AGENTS.md"}:
        return True
    if normalized.startswith((".agents/", ".codex/", "project/", "specs/", "src/", "tests/")):
        return True
    if "/" in normalized and any(part in normalized for part in (".md", ".yaml", ".yml", ".toml", ".py", ".txt", ".json", ".zip", ".docx", ".pdf", "*")):
        return True
    return False


def _parse_scalar(raw_value: str) -> object:
    value = raw_value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value == '""':
        return ""
    return value
