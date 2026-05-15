from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .inventory import Inventory
from .models import Finding, SessionActiveWorkRecord


CURRENT_FOCUS_BEGIN = "<!-- BEGIN mylittleharness-current-focus v1 -->"
CURRENT_FOCUS_END = "<!-- END mylittleharness-current-focus v1 -->"
MEMORY_ROADMAP_BEGIN = "<!-- BEGIN mylittleharness-memory-routing-roadmap v1 -->"
MEMORY_ROADMAP_END = "<!-- END mylittleharness-memory-routing-roadmap v1 -->"
DEFAULT_ACTIVE_PLAN_REL = "project/implementation-plan.md"
STATE_HISTORY_REFERENCE_LABEL = "Older prose and archived state history are reference context, not lifecycle authority."
SESSION_ACTIVE_WORK_SCHEMA = "mylittleharness.session-active-work.v1"
SESSION_ACTIVE_WORK_DIR_REL = "project/verification/session-active-work"
SESSION_ACTIVE_WORK_STATUSES = {"active", "blocked", "complete", "released", "stale", "expired", "unknown"}
SESSION_ACTIVE_WORK_REQUIRED_SCALARS = ("session_id", "run_id", "agent_id", "status")
SESSION_ACTIVE_WORK_STALE_AFTER = timedelta(hours=4)


def session_active_work_findings(inventory: Inventory, code_prefix: str = "session-active-work") -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "info",
                f"{code_prefix}-non-authority",
                f"session active work diagnostics are live-root only; root kind is {inventory.root_kind}",
                SESSION_ACTIVE_WORK_DIR_REL,
            ),
            *_session_active_work_boundary_findings(code_prefix),
        ]

    records, warnings = _load_session_active_work_records(inventory.root)
    findings: list[Finding] = [*warnings]
    if not records:
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-records",
                f"no session-scoped active work records found at {SESSION_ACTIVE_WORK_DIR_REL}/*.json",
                SESSION_ACTIVE_WORK_DIR_REL,
            )
        )
        findings.extend(_session_active_work_boundary_findings(code_prefix))
        return findings

    now = datetime.now(timezone.utc)
    for record in records:
        posture = _session_active_work_posture(record, now)
        severity = "warn" if posture in {"expired", "stale", "unknown-status"} else "info"
        code = f"{code_prefix}-{posture}" if posture != "record" else f"{code_prefix}-record"
        effective_status = "unknown" if posture == "unknown-status" else posture if posture in {"expired", "stale"} else record.status
        findings.append(
            Finding(
                severity,
                code,
                (
                    f"session_id={record.session_id or '<missing>'}; run_id={record.run_id or '<missing>'}; "
                    f"agent_id={record.agent_id or '<missing>'}; status={effective_status or '<missing>'}; "
                    f"active_plan={record.active_plan or '<none>'}; active_phase={record.active_phase or '<none>'}; "
                    f"execution_slice={record.execution_slice or '<none>'}; read-only session active work evidence only"
                ),
                record.rel_path,
            )
        )
        findings.extend(_session_active_work_metadata_findings(record, code_prefix))
    findings.extend(_session_active_work_boundary_findings(code_prefix))
    return findings


def _load_session_active_work_records(root: Path) -> tuple[list[SessionActiveWorkRecord], list[Finding]]:
    directory = root / SESSION_ACTIVE_WORK_DIR_REL
    if not directory.exists() or not directory.is_dir():
        return [], []
    records: list[SessionActiveWorkRecord] = []
    findings: list[Finding] = []
    for path in sorted(directory.glob("*.json")):
        rel_path = _to_rel_path(root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", "session-active-work-malformed", "session active work record path is not a regular file", rel_path))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(Finding("warn", "session-active-work-malformed", f"session active work record could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", "session-active-work-malformed", "session active work record JSON must be an object", rel_path))
            continue
        records.append(SessionActiveWorkRecord(rel_path=rel_path, data=data))
    return records, findings


def _session_active_work_posture(record: SessionActiveWorkRecord, now: datetime) -> str:
    if record.status not in SESSION_ACTIVE_WORK_STATUSES:
        return "unknown-status"
    if record.status in {"active", "blocked"}:
        expires_at = _parse_utc_timestamp(record.lease_expires_at)
        if expires_at is not None and expires_at <= now:
            return "expired"
        heartbeat_at = _parse_utc_timestamp(record.last_heartbeat_at_utc)
        if heartbeat_at is not None and now - heartbeat_at > SESSION_ACTIVE_WORK_STALE_AFTER:
            return "stale"
    return "record"


def _session_active_work_metadata_findings(record: SessionActiveWorkRecord, code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    if record.data.get("schema") not in (None, SESSION_ACTIVE_WORK_SCHEMA):
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-schema",
                f"session active work schema is {record.data.get('schema')!r}; expected {SESSION_ACTIVE_WORK_SCHEMA}",
                record.rel_path,
            )
        )
    for field in SESSION_ACTIVE_WORK_REQUIRED_SCALARS:
        if not str(record.data.get(field) or "").strip():
            findings.append(Finding("warn", f"{code_prefix}-metadata-missing", f"session active work missing required field {field}", record.rel_path))
    return findings


def _session_active_work_boundary_findings(code_prefix: str) -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            (
                "session active work records provide parallel visibility only; project-state lifecycle stays global authority "
                "and no session record approves closeout, archive, roadmap status, staging, commit, rollback, or release"
            ),
            SESSION_ACTIVE_WORK_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-route",
            (
                f"session active work records live under {SESSION_ACTIVE_WORK_DIR_REL}/*.json as repo-visible coordination evidence; "
                "no daemon, dashboard, queue, cache, adapter state, or provider state is authority"
            ),
            SESSION_ACTIVE_WORK_DIR_REL,
        ),
    ]


def _parse_utc_timestamp(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_rel_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def sync_current_focus_block(text: str) -> str:
    fields = _frontmatter_scalars(text)
    block = _render_current_focus_block(fields)
    replaced = _replace_existing_focus_block(text, block)
    updated = replaced if replaced is not None else _insert_focus_block(text, block)
    return _sync_memory_routing_roadmap_block(updated, fields)


def _render_current_focus_block(fields: dict[str, str]) -> str:
    plan_status = fields.get("plan_status", "")
    active_plan = fields.get("active_plan", "") or DEFAULT_ACTIVE_PLAN_REL
    active_phase = fields.get("active_phase", "")
    phase_status = fields.get("phase_status", "")
    last_archived_plan = fields.get("last_archived_plan", "")
    lines = [CURRENT_FOCUS_BEGIN]
    if plan_status == "active":
        lines.append(f"Current focus: active implementation plan is open at `{active_plan}`.")
        if active_phase or phase_status:
            lines.append(
                "Continue from "
                f"active_phase `{active_phase or '<not recorded>'}` "
                f"with phase_status `{phase_status or '<not recorded>'}`."
            )
        else:
            lines.append("Continue from project-state lifecycle fields before inferring prose.")
    else:
        lines.append("Current focus: no active implementation plan is open.")
        if last_archived_plan:
            lines.append(f"Last archived plan: `{last_archived_plan}`.")
    lines.append("Project-state lifecycle frontmatter remains the continuation authority.")
    lines.append(STATE_HISTORY_REFERENCE_LABEL)
    lines.append(CURRENT_FOCUS_END)
    return "\n".join(lines) + "\n"


def _replace_existing_focus_block(text: str, block: str) -> str | None:
    begin_index = text.rfind(CURRENT_FOCUS_BEGIN)
    end_index = text.rfind(CURRENT_FOCUS_END)
    if begin_index == -1 or end_index == -1 or end_index <= begin_index:
        return None
    end_after = end_index + len(CURRENT_FOCUS_END)
    if end_after < len(text) and text[end_after : end_after + 2] == "\r\n":
        end_after += 2
    elif end_after < len(text) and text[end_after : end_after + 1] == "\n":
        end_after += 1
    return text[:begin_index] + block + text[end_after:]


def _insert_focus_block(text: str, block: str) -> str:
    lines = text.splitlines(keepends=True)
    heading_index = _heading_index(lines, "Current Focus", level=2)
    if heading_index is not None:
        insert_index = heading_index + 1
        while insert_index < len(lines) and not lines[insert_index].strip():
            insert_index += 1
        section_end = _section_end_index(lines, heading_index, level=2)
        insert_index = _skip_legacy_focus_prelude(lines, insert_index, section_end)
        return "".join(lines[: heading_index + 1] + ["\n", block, "\n"] + lines[insert_index:])

    h1_index = _first_heading_index(lines, level=1)
    if h1_index is not None:
        insert_index = h1_index + 1
        while insert_index < len(lines) and not lines[insert_index].strip():
            insert_index += 1
        section = "## Current Focus\n\n" + block + "\n"
        return "".join(lines[: h1_index + 1] + ["\n", section] + lines[insert_index:])

    separator = "" if text.endswith(("\n", "\r")) else "\n"
    return text + separator + "\n## Current Focus\n\n" + block


def _sync_memory_routing_roadmap_block(text: str, fields: dict[str, str]) -> str:
    block = _render_memory_routing_roadmap_block(fields)
    replaced = _replace_existing_memory_roadmap_block(text, block)
    if replaced is not None:
        return replaced
    return _replace_memory_roadmap_section_body(text, block)


def _render_memory_routing_roadmap_block(fields: dict[str, str]) -> str:
    plan_status = fields.get("plan_status", "")
    active_plan = fields.get("active_plan", "") or DEFAULT_ACTIVE_PLAN_REL
    last_archived_plan = fields.get("last_archived_plan", "")
    lines = [MEMORY_ROADMAP_BEGIN]
    lines.append("Accepted-work sequencing lives in `project/roadmap.md`; use roadmap item metadata for queued, active, done, and archived status.")
    if plan_status == "active":
        lines.append(f"Current active-plan pointer: `{active_plan}`.")
    elif last_archived_plan:
        lines.append(f"Last archived plan pointer: `{last_archived_plan}`.")
    else:
        lines.append("No active-plan pointer is currently open.")
    lines.append("Project-state lifecycle frontmatter remains the continuation authority; roadmap prose here is only a hot pointer.")
    lines.append("Roadmap metadata sequences accepted work but never overrides lifecycle frontmatter.")
    lines.append(MEMORY_ROADMAP_END)
    return "\n".join(lines) + "\n"


def _replace_existing_memory_roadmap_block(text: str, block: str) -> str | None:
    begin_index = text.rfind(MEMORY_ROADMAP_BEGIN)
    end_index = text.rfind(MEMORY_ROADMAP_END)
    if begin_index == -1 or end_index == -1 or end_index <= begin_index:
        return None
    end_after = end_index + len(MEMORY_ROADMAP_END)
    if end_after < len(text) and text[end_after : end_after + 2] == "\r\n":
        end_after += 2
    elif end_after < len(text) and text[end_after : end_after + 1] == "\n":
        end_after += 1
    return text[:begin_index] + block + text[end_after:]


def _replace_memory_roadmap_section_body(text: str, block: str) -> str:
    lines = text.splitlines(keepends=True)
    heading_index = _heading_index(lines, "Memory Routing Roadmap", level=2)
    if heading_index is None:
        return text
    section_end = _section_end_index(lines, heading_index, level=2)
    return "".join(lines[: heading_index + 1] + ["\n", block, "\n"] + lines[section_end:])


def _heading_index(lines: list[str], title: str, level: int) -> int | None:
    marker = "#" * level
    for index, line in enumerate(lines):
        match = re.match(rf"^{re.escape(marker)}\s+(.+?)\s*$", line)
        if match and match.group(1).strip() == title:
            return index
    return None


def _first_heading_index(lines: list[str], level: int) -> int | None:
    marker = "#" * level
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(marker)}\s+.+?\s*$", line):
            return index
    return None


def _section_end_index(lines: list[str], heading_index: int, level: int) -> int:
    for index in range(heading_index + 1, len(lines)):
        match = re.match(r"^(#{1,6})\s+.+?\s*$", lines[index])
        if match and len(match.group(1)) <= level:
            return index
    return len(lines)


def _skip_legacy_focus_prelude(lines: list[str], start_index: int, end_index: int) -> int:
    if start_index >= end_index:
        return start_index
    if not lines[start_index].lstrip().casefold().startswith("current focus:"):
        return start_index
    index = start_index
    while index < end_index and lines[index].strip():
        index += 1
    while index < end_index and not lines[index].strip():
        index += 1
    return index


def _frontmatter_scalars(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", line)
        if match:
            fields[match.group(1)] = _strip_quotes(match.group(2))
    return fields


def _strip_quotes(value: str) -> str:
    raw = value.strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw
