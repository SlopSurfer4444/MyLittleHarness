from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .context_memory import context_memory_hook_context
from .dashboard import dashboard_agent_packet, dashboard_payload, mlhd_freshness_payload
from .inventory import Inventory, load_inventory
from .models import Finding
from .parsing import parse_frontmatter
from .preflight import preflight_sections
from .reporting import command_action_report_dict
from .routes import classify_memory_route
from .root_boundary import LIVE_OPERATING_ROOT, PRODUCT_SOURCE_FIXTURE, product_source_operator_lane_summary
from .safe_commands import mlh_command, safe_double_quoted, safe_intent_text, shell_arg


HOOK_PRE_COMMIT = "git-pre-commit"
HOOK_AGENT_STATUS = "agent-status"
HOOK_SESSION_START = "session-start"
HOOK_USER_PROMPT_SUBMIT = "user-prompt-submit"
HOOK_PRE_TOOL_USE = "pre-tool-use"
HOOK_POST_TOOL_USE = "post-tool-use"
HOOK_STOP = "stop"
CODEX_CLIENT = "codex"
CLAUDE_CODE_CLIENT = "claude-code"
GITHUB_COPILOT_CLIENT = "github-copilot"
NATIVE_HOOK_CLIENTS = (CODEX_CLIENT, CLAUDE_CODE_CLIENT, GITHUB_COPILOT_CLIENT)
CODEX_HOOK_ADAPTER_SCHEMA = "mylittleharness.codex-hook-adapter.v1"
HOOK_POLICY_SCHEMA = "mylittleharness.hook-policy.v1"
CODEX_HOOKS_REL_PATH = ".codex/hooks.json"
CODEX_HOOK_SCRIPT_REL_PATH = ".codex/hooks/mylittleharness_session_start.py"
CLAUDE_CODE_HOOKS_REL_PATH = ".claude/settings.json"
CLAUDE_CODE_HOOK_SCRIPT_REL_PATH = ".claude/hooks/mylittleharness_hook.py"
GITHUB_COPILOT_HOOKS_REL_PATH = ".github/hooks/mylittleharness.json"
GITHUB_COPILOT_HOOK_SCRIPT_REL_PATH = ".github/hooks/mylittleharness_hook.py"
CODEX_HOOK_EVENTS = {
    HOOK_SESSION_START: "SessionStart",
    HOOK_USER_PROMPT_SUBMIT: "UserPromptSubmit",
    HOOK_PRE_TOOL_USE: "PreToolUse",
    HOOK_POST_TOOL_USE: "PostToolUse",
    HOOK_STOP: "Stop",
}
GITHUB_COPILOT_HOOK_EVENTS = {
    HOOK_SESSION_START: "sessionStart",
    HOOK_USER_PROMPT_SUBMIT: "userPromptSubmitted",
    HOOK_PRE_TOOL_USE: "preToolUse",
    HOOK_POST_TOOL_USE: "postToolUse",
    HOOK_STOP: "agentStop",
}
CODEX_SESSION_START_EVENT = CODEX_HOOK_EVENTS[HOOK_SESSION_START]
CODEX_HOOK_MATCHERS = {
    HOOK_SESSION_START: "startup|resume|clear",
    HOOK_USER_PROMPT_SUBMIT: "*",
    HOOK_PRE_TOOL_USE: "*",
    HOOK_POST_TOOL_USE: "*",
    HOOK_STOP: "*",
}
CODEX_HOOK_STATUS_MESSAGES = {
    HOOK_SESSION_START: "Loading MLH dashboard context",
    HOOK_USER_PROMPT_SUBMIT: "Checking MLH route context",
    HOOK_PRE_TOOL_USE: "Checking MLH shortcut rails",
    HOOK_POST_TOOL_USE: "Recording MLH tool-use posture",
    HOOK_STOP: "Checking MLH lifecycle tail",
}
INSTALLABLE_HOOKS = (HOOK_PRE_COMMIT,)
CODEX_NATIVE_HOOKS = (HOOK_SESSION_START, HOOK_USER_PROMPT_SUBMIT, HOOK_PRE_TOOL_USE, HOOK_POST_TOOL_USE, HOOK_STOP)
NATIVE_ADAPTER_HOOKS = CODEX_NATIVE_HOOKS
RUNNABLE_HOOKS = (HOOK_PRE_COMMIT, HOOK_AGENT_STATUS, *CODEX_NATIVE_HOOKS)
FIRST_CONTACT_HOOKS = (HOOK_SESSION_START, HOOK_USER_PROMPT_SUBMIT)
TOOL_USE_HOOKS = (HOOK_PRE_TOOL_USE, HOOK_POST_TOOL_USE)
FAST_COMMAND_OUTPUT_HOOKS = (HOOK_USER_PROMPT_SUBMIT, HOOK_PRE_TOOL_USE, HOOK_POST_TOOL_USE, HOOK_STOP)
BOUNDED_MLH_READ_TOOL_SUFFIXES = (
    "mylittleharness_read_projection",
    "mylittleharness_read_source",
    "mylittleharness_related_or_bundle",
    "mylittleharness_search",
)
READ_ONLY_SOURCE_DISCOVERY_COMMANDS = {
    "cat",
    "dir",
    "rg",
    "ripgrep",
    "select-string",
    "findstr",
    "gc",
    "get-childitem",
    "get-content",
    "get-item",
    "ls",
    "more",
    "resolve-path",
    "test-path",
    "type",
}
READ_ONLY_SOURCE_DISCOVERY_PREFIX_TOKENS = {
    "&",
    "=",
    "catch",
    "do",
    "else",
    "elseif",
    "finally",
    "for",
    "foreach",
    "if",
    "in",
    "try",
    "where",
    "where-object",
    "while",
}
READ_ONLY_PRODUCT_SOURCE_SMOKE_COMMANDS = {"dashboard", "task-session"}
READ_ONLY_PRODUCT_SOURCE_INSPECTION_COMMANDS = {
    "audit-links",
    "check",
    "context-budget",
    "dashboard",
    "doctor",
    "manifest",
    "preflight",
    "status",
    "validate",
}
READ_ONLY_MLH_REPORT_COMMAND_OPTIONS = {
    "roadmap": {"--list"},
}
READ_ONLY_MLH_REPORT_ALLOWED_OPTIONS = {
    "roadmap": {"--list", "--json", "--root", "--config", "--config-path"},
}
READ_ONLY_MLH_REPORT_PIPELINE_VALUE_OPTIONS = {
    "select-object": {"-expandproperty", "-first", "-last", "-property", "-skip"},
}
READ_ONLY_MLH_REPORT_PIPELINE_FLAG_OPTIONS = {
    "select-object": {"-unique"},
}
READ_ONLY_MLH_REPORT_PIPELINE_COMMANDS = {
    "convertfrom-json",
    "py",
    "python",
    "python.exe",
    "select-object",
}
READ_ONLY_PRODUCT_SOURCE_INSPECTION_FORBIDDEN_TOKENS = {
    "--apply",
    "--build",
    "--delete",
    "--install-client-config",
    "--rebuild",
    "--record",
    "--serve",
    "--warm-cache",
}
PRODUCT_SOURCE_ROOT_MUTATING_MLH_TOKENS = READ_ONLY_PRODUCT_SOURCE_INSPECTION_FORBIDDEN_TOKENS
READ_ONLY_PRODUCT_SOURCE_SMOKE_FORBIDDEN_MARKERS = (
    "--apply",
    "--build",
    "--delete",
    "--install-client-config",
    "--rebuild",
    "--serve",
    "--warm-cache",
    "check_call(",
    "check_output(",
    "os.system(",
    "popen(",
    "start-job",
    "start-process",
    "subprocess.",
)
READ_ONLY_SUBAGENT_DELEGATION_TOOLS = (
    "create_thread",
    "fork_thread",
    "handoff_thread",
    "send_message_to_thread",
    "spawn_agent",
    "subagent",
    "delegate_agent",
)
READ_ONLY_SUBAGENT_DELEGATION_MARKERS = (
    "read-only",
    "read only",
    "readonly",
    "no writes",
    "without writing",
    "do not write",
    "do not mutate",
    "evidence/navigation",
    "read/navigation",
    "read navigation",
    "navigation refs",
    "inspect",
    "research",
    "analyze",
)
LOCAL_VCS_DELEGATION_PURPOSE_MARKERS = (
    "audit",
    "checkpoint",
    "checkpointing",
    "commitize",
    "commitization",
    "coordinate",
    "coordination",
    "local vcs",
    "vcs checkpoint",
    "vcs finalization",
)
LOCAL_VCS_DELEGATION_BOUNDARY_MARKERS = (
    "reviewed",
    "exact",
    "narrow",
    "route boundary",
    "route boundaries",
    "mlh route",
    "mlh routes",
    "local-only",
    "local only",
    "no push",
    "do not push",
    "without push",
    "without pushing",
)
SAFE_DELEGATION_ROUTE_CONTEXT_MARKERS = (
    "agents.md",
    ".codex/project-workflow.toml",
    "project/project-state.md",
    "project/roadmap.md",
    "product-source",
    "product source",
    "product_source_root",
    "lifecycle",
    "checkpoint",
    "dashboard/check",
    "dashboard",
    "check",
    "dry-run/apply",
    "dry-run",
    "dry run",
    "mlh route",
    "mlh routes",
    "legal route",
    "legal mlh",
    "repo-visible",
    "route authority",
    "route-authority",
    "route-visible",
    "local contract",
    "local savepoint",
    "local savepoints",
    "savepoint",
    "main/local",
    "exact staging",
)
SAFE_DELEGATION_BOUNDARY_MARKERS = (
    "do not push",
    "no push",
    "without push",
    "do not release",
    "no release",
    "without release",
    "do not bypass",
    "do not weaken",
    "preserve",
    "legal",
    "reviewed",
    "dry-run",
    "dry run",
    "preflight",
)
SUBAGENT_DELEGATION_FORBIDDEN_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"\bmy(?:littleharness)?\b[^\n\r;]*\s--apply\b|"
    r"\b(?:writeback|roadmap|plan|transition|repair|memory-hygiene|meta-feedback|projection)\b[^\n\r;]*\s--apply\b|"
    r"\barchive-active-plan\b|"
    r"\bmark\s+(?:roadmap\s+)?done\b|"
    r"\bgit\s+(?:add|stage|commit|push|reset|checkout|clean|restore|rm|mv)\b|"
    r"\bapply_patch\b|"
    r"\b(?:set-content|add-content|out-file|new-item|remove-item|move-item|copy-item)\b|"
    r"\b(?:start|launch)\s+(?:worker|daemon|provider)\b|"
    r"\bmlhd\s+run-once\s+--apply\b"
    r")"
)
SUBAGENT_DELEGATION_LOCAL_VCS_RE = re.compile(r"(?i)\bgit\s+(?:add|stage|commit)\b")
SUBAGENT_DELEGATION_NEGATED_GUARDRAIL_RE = re.compile(
    r"(?i)\b(?:do\s+not|don't|must\s+not|should\s+not|never|no|without)\s+"
    r"(?:(?:run|use|execute|call|invoke)\s+)?"
    r"(?:"
    r"my(?:littleharness)?\b[^\n\r;]*\s--apply\b|"
    r"(?:writeback|roadmap|plan|transition|repair|memory-hygiene|meta-feedback|projection)\b[^\n\r;]*\s--apply\b|"
    r"archive-active-plan\b|"
    r"mark\s+(?:roadmap\s+)?done\b|"
    r"bypass(?:\s+[-\w]+){0,3}\b|"
    r"git\s+(?:add|stage|commit|push|reset|checkout|clean|restore|rm|mv)\b|"
    r"apply_patch\b|"
    r"(?:set-content|add-content|out-file|new-item|remove-item|move-item|copy-item)\b|"
    r"(?:skip\s+dry-run|skip\s+review|skip\s+check)\b|"
    r"(?:start|launch|serve|run)\s+(?:worker|provider|daemon|runtime|launcher)\b|"
    r"mlhd\s+run-once\s+--apply\b"
    r")"
)
SUBAGENT_DELEGATION_NEGATED_BYPASS_TAIL_RE = re.compile(
    r"(?i)\b(?:do\s+not|don't|must\s+not|should\s+not|never|no|without)\b"
    r"(?:(?!\b(?:then|after|afterward|now|immediately)\b)[^\n\r.;]){0,180}"
    r"(?:,|\bor\b)\s+bypass(?:\s+[-\w]+){0,3}\b"
)
SUBAGENT_DELEGATION_NEGATED_EXTERNAL_RE = re.compile(
    r"(?i)\b(?:do\s+not|don't|no|without)\s+"
    r"(?:"
    r"(?:push(?:ing)?|release|releasing|publish(?:ing)?|provider(?:\s+routing)?|daemon|runtime|launcher)"
    r"(?:\s*(?:/|,|and|or)\s*"
    r"(?:push(?:ing)?|release|releasing|publish(?:ing)?|provider(?:\s+routing)?|daemon|runtime|launcher)"
    r")*"
    r")\b"
)
SUBAGENT_DELEGATION_NEGATED_CLASSIFICATION_RE = re.compile(
    r"(?i)\b(?:is|are|was|were|be|being)?\s*not\s+"
    r"(?:a|an|the)?\s*"
    r"(?:(?!\b(?:then|after|afterward|now|immediately)\b)[^\n\r.;]){0,220}"
    r"(?:"
    r"bypass(?:\s+request)?|"
    r"push(?:\s+request)?|"
    r"release(?:\s+request)?|"
    r"provider(?:\s+(?:launch|routing|request))?|"
    r"daemon(?:\s+(?:launch|request))?|"
    r"runtime(?:\s+(?:launch|request))?|"
    r"launcher(?:\s+(?:config|request))?|"
    r"mutation(?:\s+request)?|"
    r"source-write(?:\s+request)?|"
    r"shell\s+mutation|"
    r"lifecycle\s+edit|"
    r"product\s+edit|"
    r"apply_patch|"
    r"git\s+(?:add|stage|commit|push|reset|checkout|clean|restore|rm|mv)"
    r")\b"
)
SUBAGENT_DELEGATION_PROTECTIVE_POLICY_BOUNDARY_RE = re.compile(
    r"(?i)\b(?:keep|continue|preserve|retain|still|should|must|will|need\s+to|needs\s+to)\s+"
    r"(?:(?:real|unsafe|direct|broad|protected|explicit)\s+){0,4}"
    r"(?:blocking|block|blocked|refusing|refuse|preventing|prevent|disallowing|disallow|denying|deny)\b"
    r"(?:(?!\b(?:then|after|afterward|now|immediately)\b)[^\n\r.;]){0,240}"
    r"(?:"
    r"bypass|"
    r"push|"
    r"release|"
    r"provider|"
    r"daemon|"
    r"runtime|"
    r"launcher|"
    r"--force|"
    r"--mirror|"
    r"--delete|"
    r"--amend|"
    r"--all|"
    r"--no-verify|"
    r"apply_patch|"
    r"set-content|add-content|out-file|new-item|remove-item|move-item|copy-item|"
    r"git\s+(?:add|stage|commit|push|reset|checkout|clean|restore|rm|mv)"
    r")\b"
)
SUBAGENT_DELEGATION_UNSAFE_EXTERNAL_RE = re.compile(
    r"(?i)(?:"
    r"\bgit\s+(?:push|reset|checkout|clean|restore|rm|mv)\b|"
    r"\b(?:--force|-f|--mirror|--delete|--amend|--all|--no-verify)\b|"
    r"\b(?:bypass|skip\s+dry-run|skip\s+review|skip\s+check)\b|"
    r"\b(?:start|launch|serve|run)\s+(?:provider|daemon|runtime|launcher)\b|"
    r"\b(?:provider\s+routing|daemon\s+launch|runtime\s+launch|launcher\s+config)\b|"
    r"\b(?:set-content|add-content|out-file|new-item|remove-item|move-item|copy-item|apply_patch)\b"
    r")"
)
SUBAGENT_DELEGATION_DIRECT_MUTATION_RE = re.compile(
    r"(?i)\b(?:then|after(?:\s+inspection)?|afterward|now|immediately)\b[^\n\r;]*"
    r"(?:"
    r"\bmy(?:littleharness)?\b[^\n\r;]*\s--apply\b|"
    r"\b(?:writeback|roadmap|plan|transition|repair|memory-hygiene|meta-feedback|projection)\b[^\n\r;]*\s--apply\b|"
    r"\bgit\s+(?:add|stage|commit|push|reset|checkout|clean|restore|rm|mv)\b|"
    r"\bapply_patch\b|"
    r"\b(?:start|launch|serve|run)\s+(?:provider|daemon|runtime|launcher)\b"
    r")"
)
READ_ONLY_GIT_INSPECTION_COMMANDS = {
    "cat-file",
    "check-ignore",
    "diff",
    "for-each-ref",
    "grep",
    "log",
    "ls-files",
    "rev-parse",
    "show",
    "show-ref",
    "status",
}
READ_ONLY_GIT_REF_INSPECTION_COMMANDS = {"branch", "tag"}
GIT_MUTATION_COMMANDS = {"add", "stage", "commit", "push", "reset", "checkout", "clean", "restore", "rm", "mv"}
GIT_OPTIONS_WITH_VALUES = {
    "-C",
    "-c",
    "--config-env",
    "--exec-path",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}
MLH_OWNER_ROUTE_REVIEW_COMMANDS = {
    "approval-packet",
    "claim",
    "cleanup",
    "handoff",
    "intake",
    "incubate",
    "incubation-reconcile",
    "memory-hygiene",
    "meta-feedback",
    "plan",
    "projection",
    "repair",
    "research-import",
    "retention",
    "roadmap",
    "suggest",
    "task-session",
    "transition",
    "writeback",
}
WRITING_COMMAND_TOKENS = (
    ">",
    ">>",
    "set-content",
    "add-content",
    "out-file",
    "new-item",
    "remove-item",
    "move-item",
    "copy-item",
    "del ",
    "erase ",
    "rm ",
    "mv ",
    "cp ",
)
WRITING_COMMAND_NAMES = {
    "ac",
    "add-content",
    "copy",
    "copy-item",
    "cp",
    "cpi",
    "del",
    "erase",
    "mi",
    "move-item",
    "mv",
    "new",
    "new-item",
    "ni",
    "out-file",
    "remove-item",
    "ri",
    "rm",
    "sc",
    "set-content",
    "tee",
    "tee-object",
}
SHELL_COMMAND_SEPARATORS = {";", "&", "&&", "||", "|", "{", "}", "then", "do", "else", "elseif"}
SINGLE_TARGET_WRITING_COMMAND_NAMES = WRITING_COMMAND_NAMES - {"copy", "copy-item", "cp", "cpi", "mi", "move-item", "mv"}
PAIRED_TARGET_WRITING_COMMAND_NAMES = {"copy", "copy-item", "cp", "cpi", "mi", "move-item", "mv"}
WRITING_COMMAND_PATH_OPTIONS = {"-path", "-literalpath", "-filepath", "-destination"}
WRITING_COMMAND_NON_TARGET_OPTIONS_WITH_VALUES = {
    "-encoding",
    "-filter",
    "-include",
    "-inputobject",
    "-itemtype",
    "-name",
    "-type",
    "-value",
}
MLH_MUTATION_COMMANDS = (
    "mylittleharness",
    "python -m mylittleharness",
    "py -m mylittleharness",
)
LIFECYCLE_MARKDOWN_PREFIXES = (
    "project/plan-incubation/",
    "project/operator-prompts/",
    "project/research/",
    "project/verification/",
    "project/decisions/",
    "project/adrs/",
    "project/specs/",
    "project/roadmap",
    "project/archive/",
)
ACTIVE_PLAN_ROUTE_PATH = "project/implementation-plan.md"
LIFECYCLE_AUTHORITY_PATHS = (
    "project/project-state.md",
    ACTIVE_PLAN_ROUTE_PATH,
    "project/roadmap.md",
)
TEMPORARY_ROADMAP_MANIFEST_RE = re.compile(r"^project/verification/roadmap-routing-\d{4}-\d{2}-\d{2}-[a-z0-9._-]+\.json$")
ROUTE_WRITEBACK_MARKERS = (
    "<!-- BEGIN mylittleharness-closeout-writeback v1 -->",
    "<!-- BEGIN mylittleharness-phase-writeback v1 -->",
)
ROUTE_PRODUCED_LIFECYCLE_PHASE_STATUSES = {"complete", "blocked", "deferred", "abandoned", "skipped"}
EDITABLE_ROUTE_PATCH_IDS = (
    "adrs",
    "archive",
    "decisions",
    "incubation",
    "operator-prompts",
    "research",
    "stable-specs",
    "verification",
)
ACTIVE_PLAN_SPEC_DOC_PREFIXES = ("docs/specs/", "project/specs/")
GENERATED_CACHE_PREFIXES = (".mylittleharness/generated/",)
NONROUTE_PROJECT_MARKDOWN_EXEMPT_PREFIXES = (
    "project/cache/",
    "project/generated/",
    "project/private/",
    "project/scratch/",
    "project/secrets/",
    "project/temp/",
    "project/tmp/",
)
CODE_WRITE_PREFIXES = ("src/", "tests/")
GIT_WRITE_COMMANDS = (
    " git add ",
    " git stage ",
    " git commit ",
    "git add ",
    "git stage ",
    "git commit ",
)
PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"'`]+"
    r"|(?<![A-Za-z0-9_.:/-])/(?:[A-Za-z0-9_.-]+/)+[^\s\"'`]+"
    r"|(?:^|[\s\"'`])((?:\.?[\\/])?(?:project|src|tests|docs|\.mylittleharness)[\\/][^\s\"'`]+)"
)
POWERSHELL_HERE_STRING_RE = re.compile(r"@(['\"])\r?\n.*?\r?\n\1@", re.DOTALL)
POSIX_HEREDOC_START_RE = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
POWERSHELL_SPLAT_INVOCATION_RE = re.compile(
    r"(?:^|[;\r\n|])\s*(?:\$[A-Za-z_][A-Za-z0-9_]*\s*=\s*)?(?:&\s*)?"
    r"(?P<exe>(?:my" + "littleharness(?:\\.exe)?)|(?:(?:python|py)(?:\\.exe)?\\s+-m\\s+my" + "littleharness))"
    r"\s+@(?P<var>[A-Za-z_][A-Za-z0-9_]*)(?:\s+(?:\d+|\*)?>&\d+)?(?=\s*(?:$|[;\r\n|]))",
    re.IGNORECASE | re.DOTALL,
)
POWERSHELL_ARRAY_ASSIGNMENT_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)\s*=\s*@\((.*?)\)\s*;?", re.DOTALL)
POWERSHELL_SCALAR_ASSIGNMENT_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(['\"])(.*?)\2\s*;?", re.DOTALL)
POWERSHELL_HOOK_SIMULATION_COMMAND_FIELD_RE = re.compile(
    r"\bcommand\s*=\s*(?:\$([A-Za-z_][A-Za-z0-9_]*)|(['\"])(.*?)\2)",
    re.IGNORECASE | re.DOTALL,
)
POWERSHELL_HOOK_SIMULATION_EXECUTION_RE = re.compile(
    r"(?i)(?:^|[;\|\s])(?:iex|invoke-expression|start-process)\b|(?:^|[;\|\s])&\s*(?:\$|['\"]|\w)"
)
POST_CLOSEOUT_COMMIT_MESSAGE_OPTIONS = {"-m", "--message", "-F", "--file"}
POST_CLOSEOUT_COMMIT_DISALLOWED_OPTIONS = {
    "-a",
    "--all",
    "--amend",
    "--interactive",
    "--patch",
    "--no-verify",
    "-p",
}
POST_CLOSEOUT_STAGE_BROAD_PATHS = {".", "./", "*", ":/", ":/."}
GIT_STAGE_EXACT_PATHSPEC_OPTIONS = {"-f", "--force", "-n", "--dry-run"}
GIT_INDEX_SPLIT_RESTORE_ALLOWED_OPTIONS = {"--staged", "-S", "--quiet", "-q"}
GIT_INDEX_SPLIT_RESET_ALLOWED_OPTIONS = {"--quiet", "-q"}
GIT_INDEX_SPLIT_RESET_ALLOWED_REFS = {"head"}
POST_CLOSEOUT_STAGE_DISALLOWED_PREFIXES = (
    ".git/",
    ".mylittleharness/generated/",
    ".mylittleharness/runtime/",
    "node_modules/",
    "dist/",
    "build/",
)
NEIGHBOR_EXACT_STAGE_DISALLOWED_PREFIXES = POST_CLOSEOUT_STAGE_DISALLOWED_PREFIXES + (
    ".pytest_cache/",
    ".symphony/",
    ".venv/",
    "__pycache__/",
    "codex-py-",
    "data/derived/",
    "data/exports/",
    "data/private/",
    "data/raw/",
    "project/cache/",
    "project/generated/",
    "project/private/",
    "project/scratch/",
    "project/temp/",
    "project/tmp/",
    "pytest-cache-files-",
    "tmp-pytest-",
)
NEIGHBOR_PROJECT_EVIDENCE_EXACT_ALLOWED_PREFIXES = (
    "project/archive/",
    "project/research/",
    "project/verification/",
)
NEIGHBOR_PROJECT_EVIDENCE_EXACT_INCUBATION_PREFIX = "project/plan-incubation/"
NEIGHBOR_PROJECT_EVIDENCE_EXACT_CORE_PATHS = {
    "project/implementation-plan.md",
    "project/project-state.md",
    "project/roadmap.md",
}
NEIGHBOR_BOOTSTRAP_EXACT_PATHS = {
    ".codex/hooks.json",
    ".codex/hooks/mylittleharness_session_start.py",
    ".codex/project-workflow.toml",
    ".gitignore",
    ".mylittleharness/project-workflow.toml",
    "agents.md",
    "project/project-state.md",
    "project/roadmap.md",
    "readme.md",
}
NEIGHBOR_BOOTSTRAP_ALLOWED_PREFIXES = (
    "project/research/",
    "project/specs/workflow/",
)


@dataclass(frozen=True)
class HookInstallRequest:
    hook_id: str
    force: bool = False


@dataclass(frozen=True)
class CodexHookAdapterRequest:
    client: str = CODEX_CLIENT
    scope: str = "project"
    config_path: str = ""


@dataclass(frozen=True)
class HookToolIntent:
    command: str
    paths: list[str]
    write_command: str
    write_target_paths: list[str]
    payload: dict[str, object]


@dataclass(frozen=True)
class ReviewedLocalVcsCheckpoint:
    root: Path | None = None
    paths: frozenset[str] = field(default_factory=frozenset)
    mode: str = ""
    blocked_reason: str = ""
    visible_workdir: bool = False


def make_hook_install_request(args) -> HookInstallRequest:
    return HookInstallRequest(hook_id=args.hook, force=bool(getattr(args, "force", False)))


def make_codex_hook_adapter_request(args) -> CodexHookAdapterRequest:
    return CodexHookAdapterRequest(
        client=getattr(args, "client", None) or CODEX_CLIENT,
        scope=getattr(args, "scope", None) or "project",
        config_path=getattr(args, "config_path", None) or "",
    )


def hooks_doctor_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    return [
        ("Summary", _hooks_summary_findings(inventory)),
        ("Install Targets", _hook_install_target_findings(inventory, HookInstallRequest(HOOK_PRE_COMMIT))),
        ("Codex Native Adapter", _codex_hook_adapter_target_findings(inventory, CodexHookAdapterRequest())),
        (
            "Native Client Adapters",
            [
                finding
                for client in (CLAUDE_CODE_CLIENT, GITHUB_COPILOT_CLIENT)
                for finding in _codex_hook_adapter_target_findings(inventory, CodexHookAdapterRequest(client=client))
            ],
        ),
        ("First Contact Adoption", _hook_first_contact_adoption_findings(inventory)),
        ("Runnable Events", _hook_event_findings()),
        ("Boundary", _hook_boundary_findings()),
    ]


def hook_install_dry_run_findings(inventory: Inventory, request: HookInstallRequest) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "hooks-install-dry-run",
            f"hook install preview only; hook_id={request.hook_id}; no files, Git config, lifecycle state, caches, or generated reports were written",
        )
    ]
    findings.extend(_hook_install_target_findings(inventory, request))
    errors = _hook_install_errors(inventory, request)
    if errors:
        findings.extend(errors)
    else:
        target = _hook_target(inventory.root, request.hook_id)
        findings.append(
            Finding(
                "info",
                "hooks-install-plan",
                f"would install warning-only {request.hook_id} shim at {_rel_path(inventory.root, target)}",
                _rel_path(inventory.root, target),
            )
        )
    findings.extend(_hook_boundary_findings())
    return findings


def hook_install_apply_findings(inventory: Inventory, request: HookInstallRequest) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "hooks-install-apply",
            f"explicit hook install apply started; hook_id={request.hook_id}; this route writes only the selected hook shim",
        )
    ]
    errors = _hook_install_errors(inventory, request)
    if errors:
        findings.extend(errors)
        findings.extend(_hook_boundary_findings())
        return findings

    target = _hook_target(inventory.root, request.hook_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    before = target.read_text(encoding="utf-8") if target.exists() else None
    content = render_hook_shim(inventory.root, request.hook_id)
    target.write_text(content, encoding="utf-8")
    if before == content:
        findings.append(Finding("info", "hooks-install-unchanged", f"hook shim already current at {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    else:
        findings.append(Finding("info", "hooks-install-written", f"installed warning-only hook shim at {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    findings.extend(_hook_boundary_findings())
    return findings


def codex_hook_adapter_dry_run_findings(inventory: Inventory, request: CodexHookAdapterRequest) -> list[Finding]:
    prefix = _hook_adapter_code_prefix(request)
    label = _native_hook_client_label(request.client)
    policy = _hook_policy_identity()
    findings = [
        Finding(
            "info",
            f"{prefix}-dry-run",
            (
                f"{label} native hook adapter preview only; client={request.client}; scope={request.scope}; "
                "no hook config, scripts, user config, lifecycle state, caches, generated reports, or Git state were written"
            ),
        )
    ]
    findings.extend(_codex_hook_adapter_target_findings(inventory, request))
    errors = _codex_hook_adapter_errors(inventory, request)
    if errors:
        findings.extend(errors)
    else:
        config_path = _native_hooks_config_path(inventory.root, request)
        script_path = _native_hook_script_path(inventory.root, request)
        status = _codex_hook_adapter_status(inventory.root, request)
        findings.append(
            Finding(
                "info",
                f"{prefix}-plan",
                (
                    f"would ensure {label} native hook adapter events={','.join(NATIVE_ADAPTER_HOOKS)}; status={status}; "
                    f"config={_rel_path(inventory.root, config_path)}; script={_rel_path(inventory.root, script_path)}; "
                    f"policy_hash={policy['sourceHash']}"
                ),
                _rel_path(inventory.root, config_path),
            )
        )
    findings.extend(_hook_boundary_findings())
    return findings


def codex_hook_adapter_validation_findings(
    inventory: Inventory,
    request: CodexHookAdapterRequest,
    *,
    require_live_root: bool = True,
) -> list[Finding]:
    return _codex_hook_adapter_errors(inventory, request, require_live_root=require_live_root)


def codex_hook_adapter_adoption_payload(inventory: Inventory, request: CodexHookAdapterRequest | None = None) -> dict[str, object]:
    request = request or CodexHookAdapterRequest()
    config_path = _native_hooks_config_path(inventory.root, request)
    script_path = _native_hook_script_path(inventory.root, request)
    policy = _hook_policy_identity()
    dry_run_command = _hook_adapter_review_command(request, "--dry-run")
    apply_command = _hook_adapter_review_command(request, "--apply")
    return {
        "schema": CODEX_HOOK_ADAPTER_SCHEMA,
        "client": request.client,
        "scope": request.scope,
        "status": _codex_hook_adapter_status(inventory.root, request),
        "configPath": _rel_path(inventory.root, config_path),
        "scriptPath": _rel_path(inventory.root, script_path),
        "events": [_native_hook_event_name(request.client, hook_id) for hook_id in NATIVE_ADAPTER_HOOKS],
        "policy": policy,
        "dryRunCommand": dry_run_command,
        "dryRunAction": command_action_report_dict(
            dry_run_command,
            source_code="codex-hook-adapter-adoption",
            source_field="dryRunCommand",
            action_role="hook-adapter-dry-run",
        ),
        "applyCommand": apply_command,
        "applyAction": command_action_report_dict(
            apply_command,
            source_code="codex-hook-adapter-adoption",
            source_field="applyCommand",
            action_role="hook-adapter-apply",
        ),
        "includedInCodexMcpInstall": True,
        "includedInAttachApply": False,
        "includedInDefaultInitAttach": False,
        "boundary": {
            "writesRepoFilesOnApplyOnly": True,
            "writesUserConfig": False,
            "startsRuntime": False,
            "authorizesLifecycle": False,
            "correctnessPrerequisite": False,
            "eventsAreSensors": True,
        },
    }


def codex_hook_adapter_apply_findings(inventory: Inventory, request: CodexHookAdapterRequest) -> list[Finding]:
    prefix = _hook_adapter_code_prefix(request)
    label = _native_hook_client_label(request.client)
    findings = [
        Finding(
            "info",
            f"{prefix}-apply",
            (
                f"explicit {label} native hook adapter apply started; client={request.client}; scope={request.scope}; "
                "this route writes only the reviewed project-local hook config and helper script"
            ),
        )
    ]
    errors = _codex_hook_adapter_errors(inventory, request)
    if errors:
        findings.extend(errors)
        findings.extend(_hook_boundary_findings())
        return findings

    config_path = _native_hooks_config_path(inventory.root, request)
    script_path = _native_hook_script_path(inventory.root, request)
    before_config = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    before_script = script_path.read_text(encoding="utf-8") if script_path.exists() else None
    config_text = render_native_hooks_json(inventory.root, request)
    script_text = render_native_hook_script(request.client)

    try:
        cleanup_warnings = apply_file_transaction(
            (
                AtomicFileWrite(
                    config_path,
                    config_path.with_name(f".{config_path.name}.tmp"),
                    config_text,
                    config_path.with_name(f".{config_path.name}.bak"),
                ),
                AtomicFileWrite(
                    script_path,
                    script_path.with_name(f".{script_path.name}.tmp"),
                    script_text,
                    script_path.with_name(f".{script_path.name}.bak"),
                ),
            ),
            root=inventory.root,
        )
    except (OSError, FileTransactionError) as exc:
        findings.append(
            Finding(
                "error",
                f"{prefix}-apply-refused",
                f"{label} native hook adapter apply failed before all target writes completed: {exc}",
                _rel_path(inventory.root, config_path),
            )
        )
        findings.extend(_hook_boundary_findings())
        return findings

    if before_config == config_text and before_script == script_text:
        findings.append(
            Finding(
                "info",
                f"{prefix}-apply-unchanged",
                f"{label} native hook adapter already current at {_rel_path(inventory.root, config_path)}",
                _rel_path(inventory.root, config_path),
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                f"{prefix}-apply-written",
                (
                    f"installed {label} native hook adapter at {_rel_path(inventory.root, config_path)} "
                    f"with helper {_rel_path(inventory.root, script_path)}"
                ),
                _rel_path(inventory.root, config_path),
            )
        )
    findings.extend(_hook_boundary_findings())
    for warning in cleanup_warnings:
        findings.append(Finding("warn", f"{prefix}-backup-cleanup", warning, _rel_path(inventory.root, config_path)))
    return findings


def hook_run_sections(inventory: Inventory, hook_id: str, hook_args: list[str], hook_input_text: str = "") -> list[tuple[str, list[Finding]]]:
    event_findings = [
        Finding("info", "hooks-run-event", f"hook event: {hook_id}; arg_count={len(_clean_hook_args(hook_args))}"),
        Finding("info", "hooks-run-root", f"root kind: {inventory.root_kind}; root={inventory.root}"),
        Finding(
            "info",
            "hooks-run-adapter",
            "hook run is a foreground sensor/context adapter; it reads repo-visible files and emits advisory findings only",
        ),
    ]
    if hook_id not in RUNNABLE_HOOKS:
        event_findings.append(Finding("error", "hooks-run-unknown", f"unsupported hook event: {hook_id}"))
    if hook_id == HOOK_AGENT_STATUS:
        event_findings.append(
            Finding(
                "info",
                "hooks-run-agent-status",
                "agent-status hook currently reports root posture only; repo-visible claims, runs, handoffs, and project-state remain authority",
            )
        )
        return [("Event", event_findings), ("Boundary", _hook_boundary_findings())]
    if hook_id == HOOK_PRE_COMMIT:
        return [
            ("Event", event_findings),
            ("Git Pre-Commit Advisory", _git_pre_commit_findings(inventory, hook_args)),
            ("Boundary", _hook_boundary_findings()),
        ]
    if hook_id in FIRST_CONTACT_HOOKS:
        return [
            ("Event", event_findings),
            ("First Contact Context", _first_contact_context_findings(inventory, hook_id)),
            ("Native Hook Policy", _native_hook_policy_findings(inventory, hook_id, hook_input_text)),
            ("Boundary", _hook_boundary_findings()),
        ]
    if hook_id in TOOL_USE_HOOKS or hook_id == HOOK_STOP:
        return [
            ("Event", event_findings),
            ("Native Hook Policy", _native_hook_policy_findings(inventory, hook_id, hook_input_text)),
            ("Boundary", _hook_boundary_findings()),
        ]
    return [("Event", event_findings), *preflight_sections(inventory), ("Boundary", _hook_boundary_findings())]


def hook_event_payload(inventory: Inventory, hook_id: str, hook_args: list[str], hook_input_text: str = "") -> dict[str, object]:
    sections = hook_run_sections(inventory, hook_id, hook_args, hook_input_text)
    findings = [finding for _section, section_findings in sections for finding in section_findings]
    dashboard = dashboard_payload(inventory) if hook_id in FIRST_CONTACT_HOOKS else {}
    agent_packet = dashboard.get("agentPacket") if isinstance(dashboard.get("agentPacket"), dict) else dashboard_agent_packet(inventory)
    cache_posture = dashboard.get("cachePosture") if isinstance(dashboard.get("cachePosture"), dict) else {}
    connect_readiness = dashboard.get("connectReadiness") if isinstance(dashboard.get("connectReadiness"), dict) else {}
    if not connect_readiness and isinstance(agent_packet.get("connectReadiness"), dict):
        connect_readiness = agent_packet["connectReadiness"]
    mlhd = dashboard.get("mlhd") if isinstance(dashboard.get("mlhd"), dict) else mlhd_freshness_payload(inventory)
    accelerator_adoption = (
        agent_packet.get("acceleratorAdoption") if isinstance(agent_packet.get("acceleratorAdoption"), dict) else dashboard.get("acceleratorAdoption")
    )
    if not isinstance(accelerator_adoption, dict):
        accelerator_adoption = {}
    lifecycle = agent_packet.get("lifecycle") if isinstance(agent_packet.get("lifecycle"), dict) else {}
    blocked = _hook_blocked(findings)
    status = "block" if blocked else _hook_status(findings)
    status_message = _hook_status_message(hook_id, lifecycle, cache_posture)
    policy = _hook_policy_identity()
    additional_context = (
        _hook_additional_context(agent_packet, cache_posture, accelerator_adoption, connect_readiness, mlhd)
        if hook_id in FIRST_CONTACT_HOOKS
        else _hook_event_context(inventory, hook_id)
    )
    command_actions = _hook_command_actions(agent_packet, connect_readiness, accelerator_adoption)
    system_message = _hook_system_message(findings)
    codex_specific_output = _codex_hook_specific_output(hook_id, additional_context, blocked, system_message)
    return {
        "schema": "mylittleharness.hook-event.v1",
        "event": hook_id,
        "status": status,
        "policy_mode": "block" if blocked else "warn",
        "policy": policy,
        "status_message": status_message,
        "system_message": system_message,
        "additional_context": additional_context,
        "continue": not blocked,
        "systemMessage": system_message,
        "hookSpecificOutput": codex_specific_output,
        "block": blocked,
        "arg_count": len(_clean_hook_args(hook_args)),
        "hook_input": _hook_input_summary(hook_input_text),
        "root": {"path": str(inventory.root), "kind": inventory.root_kind},
        "agentPacket": agent_packet,
        "cachePosture": cache_posture,
        "connectReadiness": connect_readiness,
        "mlhd": mlhd,
        "acceleratorAdoption": accelerator_adoption,
        "commandActions": command_actions,
        "findings": [finding.to_dict() for finding in findings],
        "client_hints": {
            "codex": {
                "continue": not blocked,
                "statusMessage": status_message,
                "systemMessage": system_message,
                "hookSpecificOutput": codex_specific_output,
            }
        },
        "boundary": _hook_payload_boundary(),
    }


def codex_hook_command_output(inventory: Inventory, hook_id: str, hook_input_text: str = "") -> dict[str, object]:
    if hook_id in FAST_COMMAND_OUTPUT_HOOKS:
        return _codex_hook_command_output_fast(inventory, hook_id, hook_input_text)

    payload = hook_event_payload(inventory, hook_id, [], hook_input_text)
    codex_hints = payload.get("client_hints")
    codex_output = codex_hints.get(CODEX_CLIENT) if isinstance(codex_hints, dict) else {}
    if not isinstance(codex_output, dict):
        codex_output = {}
    system_message = codex_output.get("systemMessage")
    hook_specific = codex_output.get("hookSpecificOutput")
    blocked = bool(payload.get("block"))

    if hook_id == HOOK_PRE_TOOL_USE:
        result: dict[str, object] = {}
        if isinstance(system_message, str) and system_message:
            result["systemMessage"] = system_message
        if isinstance(hook_specific, dict):
            result["hookSpecificOutput"] = hook_specific
        return result

    if hook_id == HOOK_USER_PROMPT_SUBMIT and blocked:
        reason = system_message if isinstance(system_message, str) and system_message else "MyLittleHarness blocked this prompt by deterministic policy."
        result = {"decision": "block", "reason": reason}
        if isinstance(hook_specific, dict):
            result["hookSpecificOutput"] = hook_specific
        return result

    if hook_id == HOOK_STOP:
        if blocked:
            reason = system_message if isinstance(system_message, str) and system_message else "MyLittleHarness blocked this stop event by deterministic policy."
            return {"decision": "block", "reason": reason}
        return {}

    result = {"continue": bool(codex_output.get("continue", True))}
    if isinstance(system_message, str) and system_message:
        result["systemMessage"] = system_message
    if isinstance(hook_specific, dict):
        result["hookSpecificOutput"] = hook_specific
    return result


def _codex_hook_command_output_fast(inventory: Inventory, hook_id: str, hook_input_text: str = "") -> dict[str, object]:
    findings = _native_hook_policy_findings(inventory, hook_id, hook_input_text)
    blocked = _hook_blocked(findings)
    system_message = _hook_system_message(findings)
    hook_specific = _codex_hook_specific_output(hook_id, _hook_event_context(inventory, hook_id), blocked, system_message)

    if hook_id == HOOK_PRE_TOOL_USE:
        result: dict[str, object] = {}
        if isinstance(system_message, str) and system_message:
            result["systemMessage"] = system_message
        if hook_specific:
            result["hookSpecificOutput"] = hook_specific
        return result

    if hook_id == HOOK_USER_PROMPT_SUBMIT and blocked:
        reason = system_message if isinstance(system_message, str) and system_message else "MyLittleHarness blocked this prompt by deterministic policy."
        return {"decision": "block", "reason": reason}

    if hook_id == HOOK_STOP:
        if blocked:
            reason = system_message if isinstance(system_message, str) and system_message else "MyLittleHarness blocked this stop event by deterministic policy."
            return {"decision": "block", "reason": reason}
        return {}

    result: dict[str, object] = {"continue": not blocked}
    if isinstance(system_message, str) and system_message:
        result["systemMessage"] = system_message
    if hook_specific:
        result["hookSpecificOutput"] = hook_specific
    return result


def codex_session_start_command_output(inventory: Inventory) -> dict[str, object]:
    return codex_hook_command_output(inventory, HOOK_SESSION_START)


def hook_client_command_output(inventory: Inventory, hook_id: str, client: str, hook_input_text: str = "") -> dict[str, object]:
    if client in {CODEX_CLIENT, CLAUDE_CODE_CLIENT}:
        return codex_hook_command_output(inventory, hook_id, hook_input_text)
    if client != GITHUB_COPILOT_CLIENT:
        return hook_client_failure_output(client, hook_id, f"unsupported native hook client={client}")

    payload = hook_event_payload(inventory, hook_id, [], hook_input_text)
    blocked = bool(payload.get("block"))
    system_message = payload.get("system_message")
    reason = system_message if isinstance(system_message, str) and system_message else "MyLittleHarness blocked this deterministic shortcut attempt."
    additional_context = payload.get("additional_context")

    if hook_id == HOOK_PRE_TOOL_USE and blocked:
        return {"permissionDecision": "deny", "permissionDecisionReason": reason}
    if hook_id == HOOK_SESSION_START and isinstance(additional_context, str) and additional_context:
        return {"additionalContext": additional_context}
    if hook_id == HOOK_STOP and blocked:
        return {"decision": "block", "reason": reason}
    return {}


def hook_client_failure_output(client: str, hook_id: str, message: str) -> dict[str, object]:
    if client == GITHUB_COPILOT_CLIENT:
        if hook_id == HOOK_SESSION_START:
            return {"additionalContext": f"MyLittleHarness hook failed open: {message}"}
        return {}
    event_name = CODEX_HOOK_EVENTS.get(hook_id, CODEX_SESSION_START_EVENT)
    return {
        "continue": True,
        "systemMessage": f"MLH hook failed: {message}",
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": "MyLittleHarness context unavailable; run `mylittleharness --root <root> check` before lifecycle-sensitive work.",
        },
    }


def render_codex_hooks_json(root: Path, request: CodexHookAdapterRequest | None = None) -> str:
    request = request or CodexHookAdapterRequest()
    config_path = _codex_hooks_config_path(root, request)
    existing = _read_codex_hooks_config(config_path)
    merged = _merge_codex_native_hooks(existing)
    return json.dumps(merged, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def render_native_hooks_json(root: Path, request: CodexHookAdapterRequest | None = None) -> str:
    request = request or CodexHookAdapterRequest()
    if request.client == CODEX_CLIENT:
        return render_codex_hooks_json(root, request)
    config_path = _native_hooks_config_path(root, request)
    existing = _read_native_hooks_config(config_path, request.client)
    if request.client == CLAUDE_CODE_CLIENT:
        merged = _merge_claude_code_native_hooks(existing)
    elif request.client == GITHUB_COPILOT_CLIENT:
        merged = _merge_github_copilot_native_hooks(existing)
    else:
        raise ValueError(f"unsupported native hook client={request.client}")
    return json.dumps(merged, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def render_codex_session_start_script() -> str:
    import_root_literal = repr(str(_module_import_root()))
    policy = _hook_policy_identity()
    return "\n".join(
        [
            "# Generated by MyLittleHarness. Do not edit by hand unless replacing the hook adapter.",
            f"# Hook policy schema: {policy['schema']}",
            f"# Hook policy source: {policy['source']}",
            f"# Hook policy hash: {policy['sourceHash']}",
            "from __future__ import annotations",
            "",
            "import os",
            "import sys",
            "from pathlib import Path",
            "",
            f"MLH_IMPORT_ROOT = {import_root_literal}",
            f"MLH_HOOK_POLICY_SCHEMA = {policy['schema']!r}",
            f"MLH_HOOK_POLICY_SOURCE = {policy['source']!r}",
            f"MLH_HOOK_POLICY_HASH = {policy['sourceHash']!r}",
            "if MLH_IMPORT_ROOT and MLH_IMPORT_ROOT not in sys.path:",
            "    sys.path.insert(0, MLH_IMPORT_ROOT)",
            "",
            "import json",
            "",
            "from mylittleharness.hooks import CODEX_HOOK_EVENTS, CODEX_SESSION_START_EVENT, HOOK_SESSION_START, HOOK_STOP, codex_hook_command_output, codex_session_start_command_output",
            "from mylittleharness.inventory import load_inventory",
            "",
            "",
            "def _operating_root() -> Path:",
            "    return Path(__file__).resolve().parents[2]",
            "",
            "",
            "if __name__ == \"__main__\":",
            "    root = _operating_root()",
            "    hook_event = os.environ.get(\"MLH_HOOK_EVENT\") or HOOK_SESSION_START",
            "    hook_input = sys.stdin.read()",
            "    try:",
            "        if hook_event == HOOK_SESSION_START and not hook_input:",
            "            payload = codex_session_start_command_output(load_inventory(root))",
            "        else:",
            "            payload = codex_hook_command_output(load_inventory(root), hook_event, hook_input)",
            "    except Exception as exc:",
            "        if hook_event == HOOK_STOP:",
            "            payload = {}",
            "        else:",
            "            payload = {",
            "                \"continue\": True,",
            "                \"systemMessage\": f\"MLH hook failed: {exc}\",",
            "                \"hookSpecificOutput\": {",
            "                    \"hookEventName\": CODEX_HOOK_EVENTS.get(hook_event, CODEX_SESSION_START_EVENT),",
            "                    \"additionalContext\": \"MyLittleHarness first-contact context unavailable; run `mylittleharness --root <root> check` before lifecycle-sensitive work.\",",
            "                },",
            "            }",
            "    json.dump(payload, sys.stdout, ensure_ascii=True)",
            "    sys.stdout.write(\"\\n\")",
            "    raise SystemExit(0)",
        ]
    ) + "\n"


def render_native_hook_script(client: str) -> str:
    if client == CODEX_CLIENT:
        return render_codex_session_start_script()
    import_root_literal = repr(str(_module_import_root()))
    client_literal = repr(client)
    policy = _hook_policy_identity()
    return "\n".join(
        [
            "# Generated by MyLittleHarness. Do not edit by hand unless replacing the hook adapter.",
            f"# Hook policy schema: {policy['schema']}",
            f"# Hook policy source: {policy['source']}",
            f"# Hook policy hash: {policy['sourceHash']}",
            "from __future__ import annotations",
            "",
            "import os",
            "import sys",
            "from pathlib import Path",
            "",
            f"MLH_IMPORT_ROOT = {import_root_literal}",
            f"MLH_HOOK_POLICY_SCHEMA = {policy['schema']!r}",
            f"MLH_HOOK_POLICY_SOURCE = {policy['source']!r}",
            f"MLH_HOOK_POLICY_HASH = {policy['sourceHash']!r}",
            "if MLH_IMPORT_ROOT and MLH_IMPORT_ROOT not in sys.path:",
            "    sys.path.insert(0, MLH_IMPORT_ROOT)",
            "",
            "import json",
            "",
            "from mylittleharness.hooks import HOOK_SESSION_START, hook_client_command_output, hook_client_failure_output",
            "from mylittleharness.inventory import load_inventory",
            "",
            f"MLH_HOOK_CLIENT = {client_literal}",
            "",
            "",
            "def _operating_root() -> Path:",
            "    cwd = Path.cwd().resolve()",
            "    for candidate in (cwd, *cwd.parents):",
            "        if (candidate / 'project' / 'project-state.md').is_file():",
            "            return candidate",
            "    return Path(__file__).resolve().parents[2]",
            "",
            "",
            "if __name__ == \"__main__\":",
            "    root = _operating_root()",
            "    hook_event = os.environ.get(\"MLH_HOOK_EVENT\") or HOOK_SESSION_START",
            "    hook_input = sys.stdin.read()",
            "    try:",
            "        payload = hook_client_command_output(load_inventory(root), hook_event, MLH_HOOK_CLIENT, hook_input)",
            "    except Exception as exc:",
            "        payload = hook_client_failure_output(MLH_HOOK_CLIENT, hook_event, str(exc))",
            "    json.dump(payload, sys.stdout, ensure_ascii=True)",
            "    sys.stdout.write(\"\\n\")",
            "    raise SystemExit(0)",
        ]
    ) + "\n"


def render_hook_shim(root: Path, hook_id: str) -> str:
    if hook_id != HOOK_PRE_COMMIT:
        raise ValueError(f"unsupported installable hook: {hook_id}")
    root_literal = shlex.quote(str(root.resolve()))
    import_root_literal = shlex.quote(str(_module_import_root()))
    return "\n".join(
        [
            "#!/bin/sh",
            "# MyLittleHarness warning-only hook shim.",
            "# Installed only by explicit `mylittleharness hooks --apply`; never by init/attach.",
            "# This shim does not approve lifecycle, archive, roadmap, staging, commit, push, or release.",
            f"MLH_ROOT={root_literal}",
            f"MLH_PYTHONPATH={import_root_literal}",
            "",
            "run_mlh() {",
            "    if command -v mylittleharness >/dev/null 2>&1; then",
            "        mylittleharness \"$@\"",
            "        return $?",
            "    fi",
            "    if command -v python >/dev/null 2>&1; then",
            "        PYTHONPATH=\"$MLH_PYTHONPATH\" python -m mylittleharness \"$@\"",
            "        return $?",
            "    fi",
            "    if command -v py >/dev/null 2>&1; then",
            "        PYTHONPATH=\"$MLH_PYTHONPATH\" py -m mylittleharness \"$@\"",
            "        return $?",
            "    fi",
            "    return 127",
            "}",
            "",
            'run_mlh --root "$MLH_ROOT" hooks --run git-pre-commit -- "$@"',
            "MLH_STATUS=$?",
            "if [ \"$MLH_STATUS\" -eq 127 ]; then",
            "    printf '%s\\n' 'warning: mylittleharness is not available via console script or Python module; skipping advisory hook.' >&2",
            "elif [ \"$MLH_STATUS\" -ne 0 ]; then",
            "    printf '%s\\n' 'warning: mylittleharness hook did not complete; this shim remains warning-only.' >&2",
            "fi",
            "",
            "exit 0",
        ]
    ) + "\n"


def _hooks_summary_findings(inventory: Inventory) -> list[Finding]:
    return [
        Finding("info", "hooks-doctor-root", f"root kind: {inventory.root_kind}; root={inventory.root}"),
        Finding(
            "info",
            "hooks-doctor-posture",
            "hooks doctor is read-only; install requires explicit hooks --dry-run followed by hooks --apply",
        ),
        Finding(
            "info",
            "hooks-doctor-first-contact",
            "first-contact context is a runnable native-client event (`hooks --run session-start --json`); activation uses `hooks adapter --client <client> --dry-run|--apply --scope project`; Git pre-commit is only a warning shim",
        ),
    ]


def _codex_hook_adapter_target_findings(inventory: Inventory, request: CodexHookAdapterRequest) -> list[Finding]:
    config_path = _native_hooks_config_path(inventory.root, request)
    script_path = _native_hook_script_path(inventory.root, request)
    status = _codex_hook_adapter_status(inventory.root, request)
    prefix = _hook_adapter_code_prefix(request)
    label = _native_hook_client_label(request.client)
    event_names = _native_hook_event_names(request.client)
    policy = _hook_policy_identity()
    findings = [
        Finding("info", f"{prefix}-target", f"client={request.client}; scope={request.scope}; config={_rel_path(inventory.root, config_path)}", _rel_path(inventory.root, config_path)),
        Finding("info", f"{prefix}-script", f"helper script target={_rel_path(inventory.root, script_path)}", _rel_path(inventory.root, script_path)),
        Finding("info", f"{prefix}-status", f"{label} hook adapter status={status}; project-local hooks require a trusted project and may need client hook review or a new session", _rel_path(inventory.root, config_path)),
        Finding(
            "info",
            f"{prefix}-policy",
            (
                f"{label} hook policy source={policy['source']}; policy_hash={policy['sourceHash']}; "
                f"refresh_dry_run={_hook_adapter_review_command(request, '--dry-run')}; "
                f"refresh_apply={_hook_adapter_review_command(request, '--apply')}"
            ),
            _rel_path(inventory.root, script_path),
        ),
        Finding(
            "info",
            f"{prefix}-event",
            f"{label} native events: {', '.join(event_names)}; hook stdout provides client-valid JSON for context, warning, or deterministic denial",
            _rel_path(inventory.root, config_path),
        ),
    ]
    if status == "needs-update":
        findings.append(
            Finding(
                "warn",
                f"{prefix}-refresh-needed",
                (
                    f"{label} native hook adapter is not current for policy_hash={policy['sourceHash']}; "
                    f"next_safe_command={_hook_adapter_review_command(request, '--dry-run')} then "
                    f"{_hook_adapter_review_command(request, '--apply')}"
                ),
                _rel_path(inventory.root, script_path),
            )
        )
    return findings


def _hook_install_target_findings(inventory: Inventory, request: HookInstallRequest) -> list[Finding]:
    if request.hook_id not in INSTALLABLE_HOOKS:
        return [Finding("warn", "hooks-install-unsupported", f"hook_id={request.hook_id} is runnable but not installable by the current product surface")]
    target = _hook_target(inventory.root, request.hook_id)
    git_dir = inventory.root / ".git"
    findings = [
        Finding("info", "hooks-target", f"hook_id={request.hook_id}; target={_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)),
        Finding("info", "hooks-root-kind", f"root kind: {inventory.root_kind}"),
    ]
    if git_dir.exists() and git_dir.is_dir():
        findings.append(Finding("info", "hooks-git-dir", "local .git directory is present; hook install target can be evaluated", ".git"))
    else:
        findings.append(Finding("warn", "hooks-git-dir-missing", "local .git directory is absent; hook install apply would be refused", ".git"))
    if target.is_symlink():
        findings.append(Finding("warn", "hooks-target-symlink", f"hook target is a symlink and apply would be refused: {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    elif target.exists():
        findings.append(Finding("info", "hooks-target-existing", f"hook target already exists: {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    else:
        findings.append(Finding("info", "hooks-target-missing", f"hook target is absent: {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    findings.append(
        Finding(
            "info",
            "hooks-target-runtime-fallback",
            "installed Git shim tries the mylittleharness console script first, then falls back to `python -m mylittleharness` with the install-time package import root",
        )
    )
    return findings


def _hook_first_contact_adoption_findings(inventory: Inventory) -> list[Finding]:
    state_ref = "project/project-state.md" if inventory.state and inventory.state.exists else None
    return [
        Finding(
            "info",
            "hooks-first-contact-command",
            f"native first-contact command: mylittleharness --root {shlex.quote(str(inventory.root))} hooks --run session-start --json",
            state_ref,
        ),
        Finding(
            "info",
            "hooks-first-contact-codex-adapter",
            "Native client activation is project-local and explicit: mylittleharness --root <root> hooks adapter --client codex|claude-code|github-copilot --dry-run --scope project, then --apply after review",
            ".codex/hooks.json",
        ),
        Finding(
            "info",
            "hooks-first-contact-dashboard-first",
            "session-start emits the dashboard agent packet, projection/SQLite posture, MCP adoption posture, and rg-verification reminder before agent navigation",
            state_ref,
        ),
        Finding(
            "info",
            "hooks-first-contact-native-client-boundary",
            "MLH installs Codex, Claude Code, and GitHub Copilot native hook configuration only through the explicit project-local adapter dry-run/apply rail",
        ),
    ]


def _hook_event_findings() -> list[Finding]:
    return [
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_PRE_COMMIT}; emits a fast advisory report and remains warning-only"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_AGENT_STATUS}; reports root posture without writing files"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_SESSION_START}; emits first-contact context without writing files"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_USER_PROMPT_SUBMIT}; emits dashboard-first context for prompt routing"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_PRE_TOOL_USE}; warns or blocks deterministic shortcut attempts before tool execution"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_POST_TOOL_USE}; reports post-tool shortcut posture without writing files"),
        Finding("info", "hooks-event", f"runnable hook event: {HOOK_STOP}; warns about dangling lifecycle tails before final response"),
    ]


def _git_pre_commit_findings(inventory: Inventory, hook_args: list[str]) -> list[Finding]:
    cleaned_args = _clean_hook_args(hook_args)
    arg_summary = ", ".join(cleaned_args) if cleaned_args else "none"
    return [
        Finding(
            "info",
            "hooks-git-pre-commit-fast-path",
            (
                "git-pre-commit uses a bounded warning-only path; it does not run full preflight, "
                "scan the whole dirty tree, mutate files, stage, commit, push, or approve lifecycle movement"
            ),
        ),
        Finding(
            "info",
            "hooks-git-pre-commit-root",
            f"root kind: {inventory.root_kind}; root={inventory.root}",
        ),
        Finding(
            "info",
            "hooks-git-pre-commit-args",
            f"git hook args: {arg_summary}",
        ),
        Finding(
            "info",
            "hooks-git-pre-commit-next",
            "run explicit MLH check or dashboard commands outside the Git hook when deeper diagnostics are needed",
        ),
    ]


def _hook_install_errors(inventory: Inventory, request: HookInstallRequest) -> list[Finding]:
    findings: list[Finding] = []
    if request.hook_id not in INSTALLABLE_HOOKS:
        findings.append(Finding("error", "hooks-install-refused", f"unsupported installable hook_id={request.hook_id}"))
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "error",
                "hooks-install-refused",
                f"hook install apply requires a live operating root; got root_kind={inventory.root_kind}; product fixtures and archive roots remain non-authority",
            )
        )
    git_dir = inventory.root / ".git"
    if not git_dir.exists() or not git_dir.is_dir():
        findings.append(Finding("error", "hooks-install-refused", "hook install apply requires an existing local .git directory", ".git"))
    target = _hook_target(inventory.root, request.hook_id)
    if not _is_within_root(inventory.root, target):
        findings.append(Finding("error", "hooks-install-refused", f"hook target escapes root: {target}", _rel_path(inventory.root, target)))
    findings.extend(_unsafe_parent_directory_findings(inventory.root, target, "hooks-install-refused"))
    if target.is_symlink():
        findings.append(Finding("error", "hooks-install-refused", f"hook target is a symlink: {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    elif target.exists() and not target.is_file():
        findings.append(Finding("error", "hooks-install-refused", f"hook target is not a regular file: {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    if target.exists() and not target.is_symlink() and not request.force and target.read_text(encoding="utf-8", errors="replace") != render_hook_shim(inventory.root, request.hook_id):
        findings.append(Finding("error", "hooks-install-refused", f"hook target already exists; rerun with --force after reviewing {_rel_path(inventory.root, target)}", _rel_path(inventory.root, target)))
    return findings


def _codex_hook_adapter_errors(inventory: Inventory, request: CodexHookAdapterRequest, *, require_live_root: bool = True) -> list[Finding]:
    findings: list[Finding] = []
    prefix = _hook_adapter_code_prefix(request)
    label = _native_hook_client_label(request.client)
    if request.client not in NATIVE_HOOK_CLIENTS:
        findings.append(Finding("error", f"{prefix}-refused", f"unsupported native hook client={request.client}; supported clients={','.join(NATIVE_HOOK_CLIENTS)}"))
        return findings
    if request.scope != "project":
        findings.append(Finding("error", f"{prefix}-refused", f"unsupported {label} hook adapter scope={request.scope}; only project scope is implemented"))
        return findings
    if require_live_root and inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "error",
                f"{prefix}-refused",
                f"{label} project hook adapter apply requires a live operating root; got root_kind={inventory.root_kind}; product fixtures and archive roots remain non-authority",
            )
        )
    config_path = _native_hooks_config_path(inventory.root, request)
    script_path = _native_hook_script_path(inventory.root, request)
    for path in (config_path, script_path):
        findings.extend(_unsafe_parent_directory_findings(inventory.root, path, f"{prefix}-refused"))
    for path in (config_path, script_path):
        if not _is_within_root(inventory.root, path):
            findings.append(Finding("error", f"{prefix}-refused", f"{label} hook target escapes root: {path}", _rel_path(inventory.root, path)))
        if path.is_symlink() or (path.exists() and not path.is_file()):
            findings.append(Finding("error", f"{prefix}-refused", f"{label} hook target is not a regular file: {_rel_path(inventory.root, path)}", _rel_path(inventory.root, path)))
    if config_path.exists() and config_path.is_file() and not config_path.is_symlink():
        try:
            _read_native_hooks_config(config_path, request.client)
        except ValueError as exc:
            findings.append(Finding("error", f"{prefix}-refused", str(exc), _rel_path(inventory.root, config_path)))
    return findings


def _hook_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "hooks-boundary",
            "hooks are sensors, blockers, or context injectors only; they are optional and not correctness prerequisites; hook output cannot approve lifecycle movement, closeout, archive, roadmap status, staging, commit, push, rollback, release, product-diff acceptance, dispatcher work, provider routing, or next-plan opening",
        ),
        Finding(
            "info",
            "hooks-runtime-boundary",
            "hooks create no daemon, listener, dashboard server, queue, cache authority, provider gateway, hidden worker, or lifecycle runtime",
        ),
    ]


def _first_contact_context_findings(inventory: Inventory, hook_id: str) -> list[Finding]:
    payload = dashboard_payload(inventory)
    agent_packet = payload["agentPacket"]
    cache_posture = payload["cachePosture"]
    accelerator_adoption = payload["acceleratorAdoption"]
    assert isinstance(agent_packet, dict)
    assert isinstance(cache_posture, dict)
    assert isinstance(accelerator_adoption, dict)
    lifecycle = agent_packet.get("lifecycle", {})
    components = cache_posture.get("components", {})
    mcp = accelerator_adoption.get("mcp", {})
    assert isinstance(mcp, dict)
    artifacts = _component_status(components, "artifacts")
    sqlite_index = _component_status(components, "sqlite_index")
    return [
        Finding(
            "info",
            "hooks-first-contact-context",
            (
                f"{hook_id} emits a bounded dashboard-backed agent packet for first contact; "
                f"plan_status={_payload_value(lifecycle, 'plan_status')}; "
                f"{_lifecycle_phase_summary(lifecycle)}; "
                "use --json for the structured hook event payload"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
        Finding(
            "info" if artifacts == "current" and sqlite_index == "current" else "warn",
            "hooks-first-contact-cache-posture",
            (
                f"projection cache posture for first contact: artifacts={artifacts}; sqlite_index={sqlite_index}; "
                "hook output reports stale/degraded cache but does not refresh it or make cache truth"
            ),
            ".mylittleharness/generated/projection",
        ),
        Finding(
            "info",
            "hooks-first-contact-accelerator-adoption",
            (
                f"MCP adoption status for first contact: {str(mcp.get('status') or 'unknown')}; "
                f"mounted={str(mcp.get('mounted') is True).lower()}; dashboard_packet=available; "
                "config_merge=idempotent-explicit; rg_verification=required"
            ),
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        ),
        Finding(
            "info",
            "hooks-first-contact-boundary",
            "first-contact hook context cannot approve lifecycle, Git, dispatcher, provider, product-diff, cache, archive, roadmap, staging, commit, push, or release decisions",
        ),
    ]


def _hook_status(findings: list[Finding]) -> str:
    if any(finding.severity == "error" for finding in findings):
        return "error"
    if any(finding.severity == "warn" for finding in findings):
        return "warn"
    return "ok"


def _hook_status_message(hook_id: str, lifecycle: object, cache_posture: object) -> str:
    if hook_id not in FIRST_CONTACT_HOOKS:
        return f"MLH hook {hook_id}: advisory context only"
    components = cache_posture.get("components", {}) if isinstance(cache_posture, dict) else {}
    lifecycle_data = lifecycle if isinstance(lifecycle, dict) else {}
    return (
        "MLH first contact: "
        f"plan_status={_payload_value(lifecycle_data, 'plan_status')}; "
        f"{_lifecycle_phase_summary(lifecycle_data)}; "
        f"artifacts={_component_status(components, 'artifacts')}; "
        f"sqlite={_component_status(components, 'sqlite_index')}"
    )


def _hook_system_message(findings: list[Finding]) -> str | None:
    sample = next((finding for finding in findings if finding.severity in {"error", "warn"}), None)
    return sample.message if sample else None


def _hook_blocked(findings: list[Finding]) -> bool:
    return any(finding.severity == "error" and finding.code.startswith("hooks-policy-block-") for finding in findings)


def _codex_hook_specific_output(hook_id: str, additional_context: str, blocked: bool, system_message: str | None) -> dict[str, object]:
    output: dict[str, object] = {
        "hookEventName": CODEX_HOOK_EVENTS.get(hook_id, hook_id),
        "additionalContext": additional_context,
    }
    if blocked:
        reason = system_message or "MyLittleHarness blocked this deterministic shortcut attempt."
        if hook_id == HOOK_PRE_TOOL_USE:
            output.pop("additionalContext", None)
            output["permissionDecision"] = "deny"
            output["permissionDecisionReason"] = reason
    return output


def _hook_event_context(inventory: Inventory, hook_id: str) -> str:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    plan_status = _payload_value(state, "plan_status")
    policy = _hook_policy_identity()
    return "\n".join(
        [
            f"MyLittleHarness hook context for {hook_id}:",
            f"- lifecycle: plan_status={plan_status}; {_lifecycle_phase_summary(state)}",
            f"- hook_policy: schema={policy['schema']}; source_hash={policy['sourceHash']}; import_root={policy['importRoot']}",
            context_memory_hook_context(inventory),
            "- first-pass navigation: dashboard packet, MCP read/search/bundle when mounted, projection warm-cache if stale, then rg or bounded source reads for exact verification.",
            "- policy: deterministic unsafe shortcuts may be blocked; ambiguous cases are advisory warnings.",
            "- boundary: hook output cannot approve lifecycle, archive, roadmap, staging, commit, push, release, provider routing, daemon state, or cache truth.",
        ]
    )


def _hook_input_summary(hook_input_text: str) -> dict[str, object]:
    stripped = hook_input_text.strip()
    parsed: object = None
    if stripped:
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
    return {
        "provided": bool(stripped),
        "bytes": len(hook_input_text.encode("utf-8", errors="replace")),
        "json": isinstance(parsed, dict),
    }


def _native_hook_policy_findings(inventory: Inventory, hook_id: str, hook_input_text: str) -> list[Finding]:
    if hook_id == HOOK_USER_PROMPT_SUBMIT:
        return _user_prompt_policy_findings(inventory, hook_input_text)
    if hook_id == HOOK_PRE_TOOL_USE:
        return _pre_tool_policy_findings(inventory, hook_input_text)
    if hook_id == HOOK_POST_TOOL_USE:
        return _post_tool_policy_findings(inventory, hook_input_text)
    if hook_id == HOOK_STOP:
        return _stop_policy_findings(inventory)
    return [
        Finding(
            "info",
            "hooks-policy-context",
            f"{hook_id} has no blocking policy beyond dashboard-first context injection",
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        )
    ]


def _user_prompt_policy_findings(inventory: Inventory, hook_input_text: str) -> list[Finding]:
    text = _hook_input_search_text(hook_input_text)
    findings = [
        Finding(
            "info",
            "hooks-policy-user-prompt-submit",
            "user-prompt-submit injects dashboard-first navigation, cache posture, MCP adoption, and rg verification reminders before route-sensitive work",
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        )
    ]
    if _looks_like_descriptive_route_navigation_prompt(text):
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-descriptive-route-navigation-prompt",
                (
                    "prompt appears to describe lifecycle/checkpoint route context for navigation or review; "
                    "descriptive handoff text is not treated as a mutation shortcut, while explicit bypass, "
                    "write, Git, release, or provider instructions remain guarded by pre-tool checks"
                ),
                "project/project-state.md" if inventory.state and inventory.state.exists else None,
            )
        )
    elif _looks_like_shortcut_prompt(text):
        findings.append(
            Finding(
                "warn",
                "hooks-policy-block-shortcut-prompt",
                "prompt appears to ask for shortcut-prone lifecycle work; use dashboard, active plan, check, and explicit dry-run/apply rails before mutation",
                "project/project-state.md" if inventory.state and inventory.state.exists else None,
            )
        )
    return findings


def _pre_tool_policy_findings(inventory: Inventory, hook_input_text: str) -> list[Finding]:
    data = _hook_input_data(hook_input_text)
    text = _hook_input_search_text(hook_input_text)
    intent = _hook_tool_intent(data, text, inventory=inventory)
    command_data = intent.payload
    paths = intent.paths
    command = intent.command
    write_command = intent.write_command
    lowered = command.casefold()
    findings = [
        Finding(
            "info",
            "hooks-policy-pre-tool-use",
            "pre-tool-use inspects declared tool intent and blocks deterministic MLH shortcut attempts before tool execution",
        )
    ]
    allow_read_only_product_source_smoke = _is_read_only_product_source_smoke_command(inventory, command)
    allow_read_only_product_source_test = _is_read_only_product_source_test_command(inventory, command_data, command, paths)
    allow_read_only_product_source_inspection = _is_read_only_product_source_inspection_command(inventory, command_data, command)
    allow_read_only_product_source_vcs_inspection = _is_read_only_product_source_vcs_inspection_command(
        inventory, command, paths
    )
    allow_read_only_hook_simulation = _is_read_only_hook_diagnostic_simulation_command(command)
    block_unsafe_hook_simulation_payload = _has_unsafe_hook_diagnostic_simulation_payload(command)
    delegation_prompt_text = _delegation_prompt_text(data, text)
    allow_read_only_subagent_delegation = _is_read_only_subagent_delegation_request(data, text)
    allow_reviewed_local_vcs_delegation = _is_reviewed_local_vcs_delegation_request(data, text)
    allow_delegation_prompt_context = _is_delegation_prompt_context_request(data, text)
    allow_apply_patch_intent = bool(_hook_apply_patch_target_paths(command_data))
    allow_read_only_mlh_report = _is_read_only_mlh_report_command(command)
    allow_read_only_source_paths = (
        _is_read_only_source_discovery_command(command)
        or _is_read_only_shell_wrapper_command(command)
        or _is_read_only_git_inspection_command(command)
        or _is_read_only_mlh_inspection_command(command)
        or allow_read_only_mlh_report
        or allow_read_only_hook_simulation
        or _is_bounded_mlh_read_tool_request(data)
        or allow_read_only_product_source_smoke
        or allow_read_only_product_source_test
        or allow_read_only_product_source_inspection
        or allow_read_only_product_source_vcs_inspection
        or allow_read_only_subagent_delegation
        or allow_reviewed_local_vcs_delegation
        or (allow_delegation_prompt_context and _is_subagent_delegation_only_request(data))
    )
    allow_read_only_roadmap_path = _is_read_only_roadmap_direct_read_command(command, paths)
    allow_research_import_related_prompt = _is_research_import_related_prompt_provenance_command(command)
    allow_mlh_owner_route_paths = (
        (_is_mlh_owner_route_review_command(command) and not _is_subagent_delegation_tool_request(data))
        or allow_research_import_related_prompt
    )
    allow_existing_route_patch = _is_existing_route_markdown_patch_request(inventory, command_data)
    allow_active_plan_spec_doc_patch = _is_active_plan_spec_doc_patch_request(inventory, command_data)
    allow_post_closeout_lifecycle_route_stage = _is_post_closeout_lifecycle_route_stage_command(inventory, command, paths)
    allow_route_produced_lifecycle_route_stage = _is_route_produced_lifecycle_route_stage_command(inventory, command)
    allow_post_closeout_local_vcs_stage = (
        _is_post_closeout_local_vcs_stage_command(inventory, command)
        and not _hook_command_workdir_outside_root(inventory, command_data)
    )
    allow_post_closeout_local_vcs_commit = _is_post_closeout_local_vcs_commit_command(inventory, command)
    post_closeout_lifecycle_vcs_finalization_paths = _post_closeout_lifecycle_vcs_finalization_paths(inventory, command)
    allow_route_produced_lifecycle_commit = _is_route_produced_lifecycle_commit_command(inventory, command)
    allow_product_source_vcs_stage = _is_product_source_vcs_stage_command(inventory, command_data, command)
    allow_product_source_vcs_commit = _is_product_source_vcs_commit_command(inventory, command_data, command)
    allow_product_source_release_publication_push = _is_product_source_release_publication_push_command(
        inventory, command_data, command
    )
    block_product_source_vcs_push_before_phase_complete = (
        _active_plan_blocks_product_source_vcs_push(inventory)
        and (
            _is_product_source_vcs_push_candidate(inventory, command_data, command)
            or _is_product_source_fixture_vcs_push_candidate(inventory, command_data, command)
        )
    )
    allow_product_source_vcs_push = (
        allow_product_source_release_publication_push
        or _is_product_source_vcs_push_command(inventory, command_data, command)
        or _is_product_source_fixture_vcs_push_command(inventory, command_data, command)
    )
    block_product_source_publication_push_unsafe = (
        _is_product_source_fixture_vcs_push_context(inventory, command_data, command)
        and not allow_product_source_vcs_push
        and not block_product_source_vcs_push_before_phase_complete
    )
    block_product_source_publication_push_hidden_workdir = _is_product_source_publication_push_hidden_workdir(
        inventory, command_data, command
    )
    allow_product_source_vcs_finalization = _is_product_source_vcs_finalization_sequence(inventory, command_data, command)
    allow_product_source_vcs_command = (
        allow_product_source_vcs_stage
        or allow_product_source_vcs_commit
        or allow_product_source_vcs_push
        or allow_product_source_vcs_finalization
    )
    reviewed_local_vcs_checkpoint = _reviewed_local_vcs_checkpoint(inventory, command_data, command)
    allow_reviewed_local_vcs_checkpoint = bool(reviewed_local_vcs_checkpoint.paths)
    reviewed_local_vcs_index_split = _reviewed_post_closeout_index_split(inventory, command_data, command)
    allow_post_closeout_index_split = bool(reviewed_local_vcs_index_split.paths)
    allow_mlh_owner_route_git_literals = allow_mlh_owner_route_paths and not _git_subcommand(command)
    delegation_prompt_shortcut = (
        _is_subagent_delegation_tool_request(data)
        and _subagent_delegation_forbidden_shortcut(delegation_prompt_text)
    )
    delegation_wrapper_shortcut_text = _delegation_direct_command_text(data)
    delegation_wrapper_unallowed_shortcut = (
        _is_subagent_delegation_tool_request(data)
        and not allow_product_source_vcs_command
        and not allow_read_only_source_paths
        and not allow_mlh_owner_route_paths
        and bool(delegation_wrapper_shortcut_text)
        and _subagent_delegation_forbidden_shortcut(delegation_wrapper_shortcut_text)
    )
    allow_delegation_prompt_path_context = (
        allow_delegation_prompt_context
        and not delegation_wrapper_unallowed_shortcut
    )
    mutation_check_command = (
        _scrub_negated_subagent_delegation_guardrails(command)
        if _is_subagent_delegation_tool_request(data)
        else command
    )
    mutation_check_lowered = mutation_check_command.casefold()
    if _active_plan_roadmap_policy_relevant(inventory, command, paths):
        findings.append(
            Finding(
                "info",
                "hooks-policy-active-plan-roadmap-intake-matrix",
                (
                    "active plan is open: allow read-only lifecycle inspection and first-class MLH dry-run/apply "
                    "route review; capture new candidates through meta-feedback/incubation now; defer accepted "
                    "roadmap status/order/dependency/next-item promotion until plan_status=none or explicit "
                    "active-plan coverage; next_safe_candidate=mylittleharness --root <root> meta-feedback "
                    "--dry-run ...; next_safe_after_close=mylittleharness --root <root> roadmap --dry-run ..."
                ),
                "project/" + "implementation-plan.md",
            )
        )
    for finding in _path_policy_findings(
        inventory,
        paths,
        allow_read_only_source_paths=allow_read_only_source_paths,
        allow_read_only_roadmap_path=allow_read_only_roadmap_path,
        allow_mlh_owner_route_paths=allow_mlh_owner_route_paths,
        allow_existing_route_patch=allow_existing_route_patch,
        allow_active_plan_spec_doc_patch=allow_active_plan_spec_doc_patch,
        allow_post_closeout_lifecycle_route_stage=(allow_post_closeout_lifecycle_route_stage or allow_route_produced_lifecycle_route_stage),
        allow_post_closeout_local_vcs_stage=allow_post_closeout_local_vcs_stage,
        allow_post_closeout_lifecycle_vcs_finalization_paths=post_closeout_lifecycle_vcs_finalization_paths,
        allow_delegation_prompt_context=allow_delegation_prompt_path_context,
        allow_product_source_vcs_command=allow_product_source_vcs_command,
        reviewed_local_vcs_checkpoint_root=reviewed_local_vcs_checkpoint.root or reviewed_local_vcs_index_split.root,
        reviewed_local_vcs_checkpoint_paths=(
            set(reviewed_local_vcs_checkpoint.paths) | set(reviewed_local_vcs_index_split.paths)
        ),
    ):
        findings.append(finding)
    if _is_product_source_root_mlh_mutation_command(inventory, command_data, command):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-product-root-mlh-mutation",
                (
                    "blocked mutating MLH command targeting the configured product_source_root from an "
                    "operating-root hook context; run read-only inspection here, and perform product-source "
                    "mutation only through an explicit owning workflow"
                ),
                paths[0] if paths else None,
            )
        )
    if _looks_like_opaque_shell_payload(command):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-opaque-shell-command",
                (
                    "blocked opaque shell payload such as PowerShell -EncodedCommand; use a visible reviewed "
                    "command or a first-class MLH dry-run route instead"
                ),
            )
        )
    if block_unsafe_hook_simulation_payload:
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-unsafe-hook-simulation-payload",
                (
                    "blocked PowerShell hook diagnostic wrapper because the simulated command payload is "
                    "executable, mutating, or not a recognized read-only diagnostic; keep hook simulations as inert "
                    "read-only data or run the direct read-only command"
                ),
                paths[0] if paths else None,
            )
        )
    if _looks_like_generated_cache_write(paths, write_command):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-generated-cache-write",
                "blocked deterministic generated-cache write; use `mylittleharness --root <root> projection --warm-cache --target all` or rebuild rails instead",
                ".mylittleharness/generated",
            )
        )
    if (
        _looks_like_lifecycle_markdown_write(paths, write_command)
        and not allow_existing_route_patch
        and not allow_active_plan_spec_doc_patch
        and not allow_post_closeout_lifecycle_route_stage
        and not allow_route_produced_lifecycle_route_stage
    ):
        route_path = paths[0] if paths else "project"
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-lifecycle-markdown-shortcut",
                (
                    "blocked direct lifecycle Markdown write without MLH route/frontmatter evidence; "
                    f"next_safe_command={_hook_lifecycle_markdown_shortcut_next_safe_command(inventory, route_path, write_command)}"
                ),
                route_path,
            )
        )
    temporary_manifest = _temporary_roadmap_manifest_path(paths)
    if temporary_manifest and _looks_like_write_command(write_command) and not allow_mlh_owner_route_paths:
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-temporary-roadmap-manifest-shortcut",
                (
                    "blocked direct temporary roadmap manifest deletion; use the bounded cleanup dry-run/apply route instead; "
                    f"next_safe_command={mlh_command('cleanup', '--dry-run', '--target', temporary_manifest)}"
                ),
                temporary_manifest,
            )
        )
    if allow_existing_route_patch:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-existing-route-markdown-patch",
                "allowed bounded apply_patch update of existing frontmatter-bearing route Markdown; authority paths, create/delete, and malformed route files remain blocked",
                paths[0] if paths else None,
            )
        )
    if allow_active_plan_spec_doc_patch:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-active-plan-spec-doc-route-patch",
                (
                    "allowed bounded apply_patch update of active-phase write_scope docs/spec route file(s); "
                    "frontmatter-bearing existing files only, with lifecycle authority paths and create/delete still blocked"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_mlh_owner_route_paths:
        owner_route_evidence_path = _first_mlh_owner_route_evidence_path(inventory, paths)
        if _powershell_mlh_splat_policy_command(command):
            findings.append(
                Finding(
                    "info",
                    "hooks-policy-allow-powershell-mlh-owner-route-splat",
                    (
                        "recognized simple PowerShell argv/splat composition that resolves to a first-class MLH "
                        "owner-route dry-run/apply command; direct lifecycle or product-source writes remain blocked"
                    ),
                    owner_route_evidence_path or None,
                )
            )
        if owner_route_evidence_path:
            findings.append(
                Finding(
                    "info",
                    "hooks-policy-allow-mlh-owner-route-evidence-paths",
                    (
                        "allowed MLH owner-route dry-run/apply input/source/evidence refs as route context; "
                        "the MLH route still validates refs, and direct lifecycle or product-source writes remain blocked"
                    ),
                    owner_route_evidence_path,
                )
            )
    if allow_post_closeout_lifecycle_route_stage:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-post-closeout-lifecycle-route-staging",
                (
                    "allowed exact Git staging of existing MLH lifecycle route files after plan_status=none; "
                    "this is VCS reviewability only and does not approve route content, closeout, commit, push, "
                    "roadmap movement, or future lifecycle decisions"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_route_produced_lifecycle_route_stage:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-route-produced-lifecycle-route-staging",
                (
                    "allowed exact Git staging of existing MLH lifecycle route files for a reviewed active plan-open "
                    "package or active-phase route writeback evidence; broad add, generated/runtime caches, "
                    "partial lifecycle staging, commit, push, roadmap movement, and future lifecycle decisions remain unapproved; "
                    "review bundles may append only git status and staged diff summary/check commands in the same operating root; "
                    "if Git ignore rules hide a route-created artifact, use git add -f -- <exact-route-artifact> for that artifact only"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_post_closeout_local_vcs_stage and not allow_post_closeout_lifecycle_route_stage:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-post-closeout-local-vcs-staging",
                (
                    "allowed exact local VCS staging of reviewed existing files or route-owned tombstones after plan_status=none; "
                    "directories, wildcards, generated/runtime caches, broad add, commit, push, reset, clean, "
                    "and amend remain outside this allowance"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_post_closeout_local_vcs_commit:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-post-closeout-local-vcs-commit",
                (
                    "allowed narrow local VCS commit command after plan_status=none; this assumes an explicit "
                    "operator request and prior staged-diff review, and does not approve push, amend, reset, "
                    "clean, release, archive, or future lifecycle movement"
                ),
            )
        )
    if allow_post_closeout_index_split:
        split_root = reviewed_local_vcs_index_split.root
        split_root_text = str(split_root.resolve()) if split_root else "unknown"
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-post-closeout-index-split",
                (
                    "allowed exact index-only checkpoint split for already staged post-closeout lifecycle/evidence "
                    f"files in the actual command workdir/root ({split_root_text}); working-tree content remains untouched; "
                    "broad pathspecs, wildcards, directories, ref-changing reset/restore forms, worktree restore, "
                    "push, release, provider routing, and lifecycle authority remain blocked"
                ),
                paths[0] if paths else None,
            )
        )
    if post_closeout_lifecycle_vcs_finalization_paths:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-post-closeout-lifecycle-vcs-finalization",
                (
                    "allowed narrow post-closeout local VCS finalization for a prior reviewed staged "
                    "lifecycle/evidence diff; this permits only VCS finalization and does not approve "
                    "lifecycle content, archive, push, release, roadmap movement, or authority decisions"
                ),
            )
        )
    if allow_product_source_vcs_stage:
        stage_context = (
            "within active-plan target_artifacts"
            if _has_active_plan(inventory)
            else "after plan_status=none"
        )
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-product-source-vcs-staging",
                (
                    "allowed exact Git staging from the configured product_source_root workdir "
                    f"{stage_context}; "
                    "review bundles may append only git status and staged diff summary/check commands in the same product root; "
                    "operating-root lifecycle files, broad add, wildcards, directories, commit, push, reset, and clean "
                    "remain outside this allowance"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_product_source_vcs_commit:
        commit_context = (
            "within active-plan target_artifacts"
            if _has_active_plan(inventory)
            else "after plan_status=none"
        )
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-product-source-vcs-commit",
                (
                    "allowed narrow product-source VCS commit from the configured product_source_root workdir "
                    f"{commit_context}; this assumes prior exact staging and staged-diff review, while "
                    "amend, commit-all, push, reset, clean, release, and future lifecycle decisions remain unapproved"
                ),
            )
        )
    if allow_product_source_vcs_push:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-product-source-vcs-push",
                (
                    "allowed ordinary non-force Git push from the configured product_source_root or product-source root after "
                    "plan_status=none or active phase_status=complete; force, mirror, delete, broad refspec, "
                    "operating-root lifecycle mutation, release, and future lifecycle decisions remain unapproved"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_product_source_release_publication_push:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-product-source-release-publication-push",
                (
                    "allowed exact owner-intent release publication push from the configured product_source_root: "
                    "remote=origin, branch target=refs/heads/main, tag target=local release-candidate tag, clean "
                    "product worktree, and tag commit matches main; force, mirror, delete, wildcard, broad refspec, "
                    "package-index upload, tag movement, lifecycle mutation, and future release decisions remain blocked"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_reviewed_local_vcs_checkpoint:
        checkpoint_next_safe = _reviewed_local_vcs_checkpoint_next_safe_command(reviewed_local_vcs_checkpoint)
        checkpoint_root = reviewed_local_vcs_checkpoint.root
        checkpoint_root_text = str(checkpoint_root.resolve()) if checkpoint_root else "unknown"
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-reviewed-local-vcs-checkpoint",
                (
                    "allowed exact reviewed local-only VCS checkpoint operation for route-produced lifecycle/evidence "
                    f"files in the actual command workdir/root ({checkpoint_root_text}), including deferred research/archive route packages, "
                    "memory-hygiene/archive-reference-package and post-closeout lifecycle route packages, "
                    "delegated neighbor-root exact eligible file sets, project evidence/reference routes, "
                    "and initial scaffold packages, "
                    "meta-feedback/incubation blocker notes, "
                    "route-owned decision artifacts, and reviewed decision-backed verification evidence packages; "
                    "stage ordinary source/test files separately by exact path, then stage route-produced "
                    "lifecycle/evidence/archive artifacts separately by exact path; if Git ignore rules hide a "
                    "route-created artifact, use git add -f -- <exact-route-artifact> for that artifact only; "
                    "broad staging, unrelated dirty work, push, release, provider routing, reset, clean, and authority "
                    "decisions remain blocked; "
                    f"next_safe_review={checkpoint_next_safe}"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_route_produced_lifecycle_commit:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-route-produced-lifecycle-commit",
                (
                    "allowed narrow local VCS commit command for a coherent staged lifecycle route set backed by "
                    "a reviewed active plan-open package or active-phase-complete writeback evidence; " + "gi" + "t commit -F" + " is treated as a message-file option, "
                    "while lowercase -f, amend, push, reset, clean, and generated/runtime cache commits remain blocked"
                ),
            )
        )
    if allow_product_source_vcs_finalization:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-product-source-vcs-finalization-sequence",
                (
                    "allowed exact product-source VCS finalization sequence after plan_status=none; "
                    "the sequence may only stage exact reviewed product files, run cached diff check, and "
                    "commit with an explicit message file, while push, amend, reset, clean, broad add, "
                    "release, and lifecycle decisions remain unapproved"
                ),
            )
        )
    if allow_research_import_related_prompt:
        related_prompt = _research_import_related_prompt_path(command)
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-research-import-related-prompt-provenance",
                "allowed research-import related-prompt as read-only provenance; the referenced lifecycle Markdown is not treated as a mutation target",
                related_prompt or None,
            )
        )
    if allow_read_only_source_paths and any(_is_lifecycle_route_path(path) for path in paths):
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-read-only-lifecycle-inspection",
                "allowed read-only lifecycle inspection; route files remain authority and this hook output cannot approve mutation or lifecycle movement",
                paths[0] if paths else None,
            )
        )
    if allow_read_only_mlh_report:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-read-only-mlh-report",
                "allowed read-only MLH report/list command; this hook output remains advisory and cannot approve route mutation",
            )
        )
    if allow_read_only_hook_simulation:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-read-only-hook-diagnostic-simulation",
                (
                    "allowed PowerShell hook diagnostic wrapper because the simulated command payload is inert "
                    "read-only data for a pre/post tool-use hook run; executable payloads and lifecycle mutation "
                    "intent remain blocked"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_read_only_product_source_smoke and any(_is_under_configured_product_root(inventory, path) for path in paths):
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-read-only-product-source-smoke",
                (
                    "allowed read-only Python smoke importing configured product_source_root for MLH inspect JSON; "
                    "writes, apply/rebuild/cache/runtime launch, lifecycle mutation, and Git mutation remain blocked"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_read_only_product_source_test:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-read-only-product-source-test",
                (
                    "allowed read-only stdlib unittest command for configured product_source_root; "
                    "verification output is advisory and does not approve lifecycle, staging, commit, push, or product mutation"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_read_only_product_source_inspection and any(_is_under_configured_product_root(inventory, path) for path in paths):
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-read-only-product-source-inspection",
                (
                    "allowed read-only MLH inspection of configured product_source_root; report output is advisory "
                    "and writes, apply/build/rebuild/cache/server actions, lifecycle mutation, and Git mutation remain blocked"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_read_only_product_source_vcs_inspection:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-read-only-product-source-vcs-inspection",
                (
                    "allowed read-only Git inspection of configured product_source_root from an operating-root "
                    "context; branch/tag creation, deletion, force/update options, writes, staging, commit, push, "
                    "reset, clean, release, and lifecycle decisions remain blocked"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_read_only_subagent_delegation:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-read-only-subagent-delegation",
                (
                    "allowed source-explicit read-only subagent delegation prompt; lifecycle apply/archive, "
                    "roadmap mutation, Git mutation, provider/daemon launch, cache truth, and source writes remain blocked"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_reviewed_local_vcs_delegation:
        findings.append(
            Finding(
                "warn",
                "hooks-policy-warn-reviewed-local-vcs-delegation",
                (
                    "allowed project-thread delegation to coordinate reviewed local-only VCS checkpointing; actual "
                    "shell/file operations remain guarded, and broad staging, push/release/provider routing, "
                    "daemon/runtime launch, direct authority edits, and bypass wording remain blocked"
                ),
                paths[0] if paths else None,
            )
        )
    if allow_delegation_prompt_path_context and not allow_read_only_subagent_delegation and not allow_reviewed_local_vcs_delegation:
        findings.append(
            Finding(
                "info",
                "hooks-policy-allow-delegation-prompt-context",
                (
                    "allowed delegation/thread prompt context to name protected routes or product roots without "
                    "treating them as current-tool mutation targets; actual shell/editor/file operations, embedded "
                    "executable payloads, lifecycle apply/archive, Git mutation, push, release, and authority "
                    "decisions remain guarded"
                ),
                paths[0] if paths else None,
            )
        )
    if (
        _is_subagent_delegation_tool_request(data)
        and (delegation_wrapper_unallowed_shortcut or (delegation_prompt_shortcut and not allow_delegation_prompt_context))
        and not allow_reviewed_local_vcs_delegation
    ):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-subagent-delegation-shortcut",
                (
                    "blocked subagent delegation prompt because it contains lifecycle apply, archive, Git, "
                    "provider/daemon launch, or source-write shortcut markers; keep delegation read-only and evidence/navigation only"
                ),
                paths[0] if paths else None,
            )
        )
    nonroute_markdown = _nonroute_project_markdown_write_path(paths, write_command)
    if nonroute_markdown:
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-nonroute-project-markdown-write",
                (
                    "blocked project Markdown write outside an MLH-visible route; use intake or an owned route such as "
                    "project/adrs, project/decisions, project/research, project/plan-incubation, project/operator-prompts, or project/verification "
                    "for durable knowledge; next_safe_command=mylittleharness --root <root> intake --dry-run --text-file -"
                ),
                nonroute_markdown,
            )
        )
    code_write_paths = _hook_code_write_paths(inventory, paths, write_command)
    if code_write_paths:
        allowed_scope = [
            _hook_plan_path_display(inventory, path)
            for path in code_write_paths
            if _is_active_plan_target_artifact(inventory, path)
        ]
        out_of_scope = [path for path in code_write_paths if not _is_active_plan_target_artifact(inventory, path)]
        blocked_scope = [_hook_plan_path_display(inventory, path) for path in out_of_scope]
        scope_message = _hook_scope_diagnostic_message(allowed_scope, blocked_scope)
        if len(code_write_paths) > 1:
            findings.append(
                Finding(
                    "info",
                    "hooks-policy-code-write-scope-diagnostic",
                    (
                        "source/test write scope diagnostic: "
                        f"{scope_message}; next_safe_command=mylittleharness --root <root> check"
                    ),
                    blocked_scope[0] if blocked_scope else (allowed_scope[0] if allowed_scope else None),
                )
            )
        if not _has_active_plan(inventory):
            findings.append(
                Finding(
                    "error",
                    "hooks-policy-block-code-write-without-plan",
                    (
                        "tool request appears to write source/test code while no active implementation plan is open; "
                        f"{scope_message}; next_safe_command=mylittleharness --root <root> plan --dry-run --roadmap-item <id>"
                    ),
                    blocked_scope[0] if blocked_scope else (allowed_scope[0] if allowed_scope else None),
                )
            )
        elif out_of_scope:
            findings.append(
                Finding(
                    "error",
                    "hooks-policy-block-code-write-outside-plan-scope",
                    (
                        "blocked source/test write outside the active plan target_artifacts; "
                        f"{scope_message}; next_safe_command=mylittleharness --root <root> roadmap --dry-run "
                        "--action update --item-id <id> --target-artifact <rel-path>"
                    ),
                    blocked_scope[0] if blocked_scope else out_of_scope[0],
                )
            )
    if (
        _looks_like_unsafe_mlh_mutation(mutation_check_lowered)
        and not _has_explicit_mlh_review_mode(mutation_check_lowered)
        and not _is_read_only_mlh_report_command(mutation_check_command)
    ):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-mlh-mutation-without-mode",
                "blocked MLH mutating command without explicit dry-run/apply or a recognized read-only/cache route",
            )
        )
    if _looks_like_next_plan_apply(mutation_check_lowered) and _has_active_plan(inventory):
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-next-plan-while-active",
                "blocked opening a new active plan while the current plan is still active; close, cancel, or explicitly update the active plan first",
                "project/implementation-plan.md",
            )
        )
    if block_product_source_vcs_push_before_phase_complete:
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-product-source-vcs-push-before-phase-complete",
                (
                    "blocked ordinary product-source main publication push while the active plan phase is not complete; "
                    "finish verification and record phase_status=complete first, then rerun the exact product-root "
                    "publication command; next_safe_command=mylittleharness --root <root> writeback --dry-run "
                    "--phase-status complete --docs-decision <updated|not-needed|uncertain>"
                ),
                "project/implementation-plan.md",
            )
        )
    if block_product_source_publication_push_unsafe:
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-product-source-vcs-push-unsafe",
                (
                    "blocked product-source publication push because the command is not an ordinary non-force "
                    "main publication push; use the literal product-root command `git push origin main` after "
                    "review, or a reviewed release-publication route for tag pushes; force, mirror, delete, "
                    "wildcard, broad refspec, tag-only, all-branch, and non-main publication pushes remain guarded"
                ),
            )
        )
    if block_product_source_publication_push_hidden_workdir:
        product_root = _configured_product_source_root_path(inventory)
        explicit_command = (
            f"`git -C {shell_arg(str(product_root))} push origin main`"
            if product_root is not None
            else "`git -C <product_source_root> push origin main`"
        )
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-product-source-vcs-push-hidden-workdir",
                (
                    "blocked likely product-source main publication because the hook cannot see a product-source "
                    "workdir or command-level root switch; rerun the publication with an explicit visible root "
                    f"switch: {explicit_command}. Generic staging/commit guidance does not apply to this "
                    "publication form"
                ),
            )
        )
    if (
        _looks_like_git_stage_or_commit(mutation_check_lowered)
        and not allow_apply_patch_intent
        and not allow_post_closeout_lifecycle_route_stage
        and not allow_route_produced_lifecycle_route_stage
        and not allow_post_closeout_local_vcs_stage
        and not allow_post_closeout_local_vcs_commit
        and not allow_post_closeout_index_split
        and not allow_route_produced_lifecycle_commit
        and not allow_product_source_vcs_command
        and not allow_mlh_owner_route_git_literals
        and not allow_read_only_source_paths
        and not allow_reviewed_local_vcs_checkpoint
        and not allow_reviewed_local_vcs_delegation
        and not block_product_source_vcs_push_before_phase_complete
        and not block_product_source_publication_push_unsafe
        and not block_product_source_publication_push_hidden_workdir
    ):
        next_safe = _git_mutation_next_safe_command(inventory, command_data, command)
        if reviewed_local_vcs_checkpoint.blocked_reason:
            checkpoint_root = reviewed_local_vcs_checkpoint.root
            checkpoint_root_text = str(checkpoint_root.resolve()) if checkpoint_root else "<actual-root>"
            checkpoint_git_prefix = "git -C " + shell_arg(checkpoint_root_text) if checkpoint_root else "git -C <actual-root>"
            git_message = (
                "blocked reviewed local VCS checkpoint because "
                f"{reviewed_local_vcs_checkpoint.blocked_reason}; only exact existing MLH route/evidence files "
                "or exact eligible target files "
                "in the actual command workdir/root are allowed, and hook output cannot approve push, release, "
                "reset, clean, broad add, or authority decisions; "
                f"actual_command_root={checkpoint_root_text}; "
                "safe_pattern=stage ordinary source/test files first by exact path, then stage route-produced "
                "lifecycle/evidence/archive artifacts separately by exact path; if Git ignore rules hide a "
                f"route-created artifact, use {checkpoint_git_prefix} add -f -- <exact-route-artifact> for that artifact only "
                "(generic_template: git -C <actual-root> add -f -- <exact-route-artifact>); "
                f"(template: {checkpoint_git_prefix} add -f -- <exact-route-artifact-if-ignored>); "
                f"next_safe_command={checkpoint_git_prefix} add -- <exact-route-files>; "
                f"{checkpoint_git_prefix} diff --cached --check; {checkpoint_git_prefix} commit -F <message-file>"
            )
        else:
            split_step_hint = (
                " split any message-file creation from the final narrow local VCS command;"
                if _has_shell_command_separator(command)
                else ""
            )
            git_message = (
                "blocked Git mutation while an active plan is open; complete explicit lifecycle closeout "
                f"or stage the coherent route-produced lifecycle set;{split_step_hint} next_safe_command={next_safe}"
                if _has_active_plan(inventory)
                else (
                    "blocked broad Git mutation after closeout; only exact staging of reviewed existing files or "
                    "narrow local commit commands are allowed, and hook output cannot approve push, reset, clean, "
                    f"amend, wildcard, directory, or broad add;{split_step_hint} next_safe_command={next_safe}"
                )
            )
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-git-before-lifecycle-closeout",
                git_message,
                "project/implementation-plan.md",
            )
        )
    product_root_direct_path = (
        ""
        if allow_delegation_prompt_context or allow_product_source_vcs_command
        else _product_root_direct_edit_path(inventory, paths, write_command)
    )
    if product_root_direct_path:
        next_safe = _hook_product_root_write_next_safe_command(inventory, product_root_direct_path)
        findings.append(
            Finding(
                "error",
                "hooks-policy-block-product-root-direct-edit",
                (
                    "blocked direct product-source edit from a serviced operating-root hook context; "
                    "declare the product path in active-plan target_artifacts before writing; "
                    f"next_safe_command={next_safe}"
                ),
                product_root_direct_path,
            )
        )
    if len(findings) == 1:
        findings.append(Finding("info", "hooks-policy-pre-tool-use-clear", "no deterministic shortcut block matched this tool request"))
    return findings


def _post_tool_policy_findings(inventory: Inventory, hook_input_text: str) -> list[Finding]:
    data = _hook_input_data(hook_input_text)
    text = _hook_input_search_text(hook_input_text)
    paths = _hook_tool_intent(data, text, inventory=inventory).paths
    findings = [
        Finding(
            "info",
            "hooks-policy-post-tool-use",
            "post-tool-use reports shortcut posture after tool execution; it cannot repair or approve the result",
        )
    ]
    findings.extend(_path_policy_findings(inventory, paths, warn_only=True))
    if len(findings) == 1:
        findings.append(Finding("info", "hooks-policy-post-tool-use-clear", "no deterministic post-tool warning matched this tool result"))
    return findings


def _stop_policy_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "hooks-policy-stop",
            "stop checks for dangling active lifecycle posture before the agent finalizes; hook output remains advisory",
            "project/project-state.md" if inventory.state and inventory.state.exists else None,
        )
    ]
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    if str(state.get("plan_status") or "").casefold() == "active":
        findings.append(
            Finding(
                "warn",
                "hooks-policy-stop-active-plan-open",
                (
                    f"active plan remains open at {_payload_value(state, 'active_plan')}; "
                    "record phase writeback/verification before confident final closeout wording"
                ),
                _payload_value(state, "active_plan"),
            )
        )
    return findings


def _hook_additional_context(
    agent_packet: object,
    cache_posture: object,
    accelerator_adoption: object,
    connect_readiness: object,
    mlhd: object,
) -> str:
    if not isinstance(agent_packet, dict):
        return ""
    lifecycle = agent_packet.get("lifecycle", {})
    next_legal = agent_packet.get("nextLegalDryRun", {})
    recommended = agent_packet.get("recommendedCommands", [])
    components = cache_posture.get("components", {}) if isinstance(cache_posture, dict) else {}
    adoption = accelerator_adoption if isinstance(accelerator_adoption, dict) else {}
    mcp = adoption.get("mcp", {}) if isinstance(adoption.get("mcp"), dict) else {}
    readiness = connect_readiness if isinstance(connect_readiness, dict) else {}
    docs = readiness.get("docs", {}) if isinstance(readiness.get("docs"), dict) else {}
    writeback = readiness.get("writeback", {}) if isinstance(readiness.get("writeback"), dict) else {}
    mlhd_refresh = _command_action_context(adoption.get("mlhdRefreshAction")) if adoption.get("mlhdRefreshAction") else "<refused for product-source roots>"
    readiness_next_safe = _command_action_context(readiness.get("nextSafeAction"))
    authority_summary = agent_packet.get("authoritySummary") if isinstance(agent_packet.get("authoritySummary"), str) else ""
    if not authority_summary:
        authority_summary = _authority_cards_context(agent_packet.get("authorityCards") or readiness.get("authorityCards"))
    mlhd_payload = mlhd if isinstance(mlhd, dict) else {}
    context_memory_payload = agent_packet.get("contextMemory") if isinstance(agent_packet.get("contextMemory"), dict) else {}
    return "\n".join(
        [
            "MyLittleHarness first-contact context:",
            f"- lifecycle: plan_status={_payload_value(lifecycle, 'plan_status')}; active_plan={_payload_value(lifecycle, 'active_plan')}; {_lifecycle_phase_summary(lifecycle)}",
            f"- cache: artifacts={_component_status(components, 'artifacts')}; sqlite_index={_component_status(components, 'sqlite_index')}",
            f"- mlhd: control_status={_payload_value(mlhd_payload, 'control_status')}; runtime_cache={_payload_value(mlhd_payload, 'runtime_cache_status')}; dirty_count={_payload_value(mlhd_payload, 'dirty_count')}; last_tick={_payload_value(mlhd_payload, 'last_tick_utc')}; last_failure={_payload_value(mlhd_payload, 'last_failed_refresh_utc')}",
            f"- context memory: status={_payload_value(context_memory_payload, 'status')}; capsule={_payload_value(context_memory_payload, 'capsule_rel_path')}; source_refs={_payload_value(context_memory_payload, 'source_ref_count')}",
            f"- connect readiness: writeback_required={str(writeback.get('requiredWhenPlanStatusActive') is True).lower()}; docs_decision={_payload_value(docs, 'docsDecision')}; docmap={_payload_value(docs, 'docmapStatus')}; next_safe_action={readiness_next_safe}",
            f"- authority cards: {authority_summary or 'unavailable'}; dashboard/check/hooks/cache/search output remains non-authority.",
            "- cache command boundary: read-only hook payload displays recovery commands only; hooks do not execute generated-cache refreshes.",
            f"- accelerators: dashboard_packet=available; mcp={_payload_value(mcp, 'status')}; mounted={str(mcp.get('mounted') is True).lower()}; mlhd_refresh_action={mlhd_refresh}; rg_verification=required",
            "- mcp coverage: read_projection=current posture; read_source=bounded source slices; search=source-verified exact/path/full-text; related_or_bundle=links/fan-in/relationship bundle",
            f"- next legal dry-run: {_payload_value(next_legal, 'command')}",
            f"- recommended first-pass commands: {', '.join(str(command) for command in recommended[:4])}",
            "- exact verification: use `rg` or `mylittleharness.read_source` before source edits or closeout claims.",
            "- boundary: this hook is advisory context only and approves no lifecycle, Git, dispatcher, provider, product-diff, cache, archive, staging, commit, push, or release action.",
        ]
    )


def _hook_command_actions(
    agent_packet: object,
    connect_readiness: object,
    accelerator_adoption: object,
) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    if isinstance(agent_packet, dict):
        recommended = agent_packet.get("recommendedCommandActions")
        if isinstance(recommended, list):
            actions.extend(action for action in recommended if isinstance(action, dict))
    if isinstance(connect_readiness, dict):
        for key in ("nextSafeAction", "recoveryAction"):
            action = connect_readiness.get(key)
            if isinstance(action, dict):
                actions.append(action)
        cache = connect_readiness.get("cache")
        if isinstance(cache, dict):
            for key in ("selfHealAction", "manualRecoveryAction"):
                action = cache.get(key)
                if isinstance(action, dict):
                    actions.append(action)
        writeback = connect_readiness.get("writeback")
        if isinstance(writeback, dict):
            action = writeback.get("dryRunAction")
            if isinstance(action, dict):
                actions.append(action)
    if isinstance(accelerator_adoption, dict):
        for key in ("firstContactHookAction", "codexHookAdapterAction", "mlhdRefreshAction", "projectionWarmCacheAction"):
            action = accelerator_adoption.get(key)
            if isinstance(action, dict) and action:
                actions.append(action)
    return actions


def _command_action_context(action: object) -> str:
    if not isinstance(action, dict) or not action.get("command"):
        return "<none>"
    return (
        f"action_class={action.get('action_class', '<unknown>')}; "
        f"write_class={action.get('write_class', '<unknown>')}; "
        f"requires_explicit_command={str(action.get('requires_explicit_command') is True).lower()}"
    )


def _authority_cards_context(cards: object) -> str:
    if not isinstance(cards, list):
        return ""
    parts: list[str] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        card_id = str(card.get("id") or "")
        refs = card.get("authorityRefs")
        if card_id and isinstance(refs, list) and refs:
            parts.append(f"{card_id}={'+'.join(str(ref) for ref in refs[:2])}")
    return "; ".join(parts)


def _hook_payload_boundary() -> dict[str, object]:
    return {
        "readOnly": True,
        "writesFiles": False,
        "installsHook": False,
        "startsListener": False,
        "startsDaemon": False,
        "refreshesGeneratedCache": False,
        "createsAdapterState": False,
        "authorizesLifecycle": False,
        "authorizesGit": False,
        "authorizesDispatcher": False,
        "authorizesProvider": False,
        "authorizesProductDiff": False,
        "authorizesCacheTruth": False,
    }


def _hook_input_data(hook_input_text: str) -> dict[str, object]:
    if not hook_input_text.strip():
        return {}
    try:
        value = json.loads(hook_input_text)
    except json.JSONDecodeError:
        return {"raw": hook_input_text}
    if not isinstance(value, dict):
        return {"raw": value}
    decoded = _decode_hook_embedded_payloads(value)
    return decoded if isinstance(decoded, dict) else value


def _decode_hook_embedded_payloads(value: object, *, key: str = "", depth: int = 0) -> object:
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {
            str(item_key): _decode_hook_embedded_payloads(item, key=str(item_key), depth=depth + 1)
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_decode_hook_embedded_payloads(item, key=key, depth=depth + 1) for item in value]
    if not isinstance(value, str):
        return value
    if key.casefold() not in {
        "arguments",
        "parameters",
        "params",
        "tool_input",
        "input",
        "tool_call",
        "toolcall",
        "request",
        "payload",
        "data",
    }:
        return value
    parsed = _parse_hook_embedded_json(value)
    if parsed is None:
        return value
    return _decode_hook_embedded_payloads(parsed, key=key, depth=depth + 1)


def _parse_hook_embedded_json(value: str) -> object | None:
    stripped = str(value or "").strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _hook_input_search_text(hook_input_text: str) -> str:
    data = _hook_input_data(hook_input_text)
    return _stringify_jsonish(data) if data else hook_input_text


def _stringify_jsonish(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_stringify_jsonish(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_stringify_jsonish(item) for item in value)
    return str(value or "")


def _hook_input_command(data: dict[str, object], fallback_text: str) -> str:
    candidates = (
        data.get("command"),
        data.get("shell_command"),
        data.get("cmd"),
        data.get("args"),
        data.get("arguments"),
        data.get("input"),
        data.get("tool_input"),
        data.get("parameters"),
        data.get("params"),
        data.get("function"),
        data.get("tool_uses"),
        data.get("toolUse"),
        data.get("tool_calls"),
        data.get("calls"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
        if isinstance(candidate, dict):
            nested = _hook_input_command(candidate, "")
            if nested:
                return nested
        if isinstance(candidate, list) and candidate:
            nested_values: list[str] = []
            scalar_values: list[str] = []
            for item in candidate:
                if isinstance(item, dict):
                    nested = _hook_input_command(item, "")
                    if nested:
                        nested_values.append(nested)
                elif isinstance(item, list):
                    nested = _hook_input_command({"args": item}, "")
                    if nested:
                        nested_values.append(nested)
                elif str(item or "").strip():
                    scalar_values.append(str(item))
            if nested_values:
                return " ".join(nested_values)
            if scalar_values:
                return " ".join(scalar_values)
    return fallback_text


def _hook_command_payload(data: dict[str, object]) -> dict[str, object]:
    payloads = _hook_direct_command_payloads(data)
    if not payloads:
        return data
    if len(payloads) == 1:
        return payloads[0]
    return _combined_hook_command_payload(payloads)


def _hook_direct_command_payloads(value: object, context: dict[str, object] | None = None) -> list[dict[str, object]]:
    context = context or {}
    if isinstance(value, list):
        payloads: list[dict[str, object]] = []
        for item in value:
            payloads.extend(_hook_direct_command_payloads(item, context))
        return payloads
    if not isinstance(value, dict):
        return []
    local_context = _merge_hook_payload_context(context, _hook_payload_context(value))
    if _hook_payload_has_direct_command(value):
        return [_merge_hook_payload_context(local_context, value)]
    payloads: list[dict[str, object]] = []
    for key in (
        "arguments",
        "parameters",
        "params",
        "function",
        "tool_input",
        "input",
        "tool_uses",
        "toolUse",
        "tool_calls",
        "tool_call",
        "toolCall",
        "calls",
        "request",
        "payload",
        "data",
        "target",
        "project",
        "body",
        "message",
        "messages",
    ):
        item = value.get(key)
        if isinstance(item, (dict, list)):
            payloads.extend(_hook_direct_command_payloads(item, local_context))
    return payloads


def _hook_payload_has_direct_command(payload: dict[str, object]) -> bool:
    for key in ("command", "shell_command", "cmd", "args"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(str(item or "").strip() for item in value):
            return True
    for key in ("input", "patch", "tool_input", "arguments"):
        value = payload.get(key)
        if isinstance(value, str) and "*** Begin Patch" in value:
            return True
    return False


def _hook_payload_context(payload: dict[str, object]) -> dict[str, object]:
    context: dict[str, object] = {}
    for key in (
        "toolName",
        "tool_name",
        "tool",
        "recipient_name",
        "name",
        "cwd",
        "workdir",
        "working_directory",
        "workingDirectory",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            context[key] = value
    return context


def _merge_hook_payload_context(context: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    if not context:
        return dict(payload)
    merged = dict(payload)
    for key, value in context.items():
        merged.setdefault(key, value)
    return merged


def _combined_hook_command_payload(payloads: list[dict[str, object]]) -> dict[str, object]:
    commands = _dedupe_nonempty([_hook_input_command(payload, "") for payload in payloads])
    combined: dict[str, object] = {"command": "; ".join(commands)}
    common_workdir = _common_hook_workdir(payloads)
    if common_workdir:
        combined["workdir"] = common_workdir
    return combined


def _common_hook_workdir(payloads: list[dict[str, object]]) -> str:
    workdirs = [_hook_workdir_value(payload) for payload in payloads]
    if not workdirs or any(not workdir for workdir in workdirs):
        return ""
    normalized = {_normalize_hook_path(workdir).casefold() for workdir in workdirs}
    return workdirs[0] if len(normalized) == 1 else ""


def _hook_tool_intent(data: dict[str, object], text: str, *, inventory: Inventory | None = None) -> HookToolIntent:
    command_payload = _hook_command_payload(data)
    payload_text = text if command_payload is data else _stringify_jsonish(command_payload)
    command = _hook_input_command(command_payload, payload_text)
    write_target_paths = _hook_write_target_paths(command_payload, command, inventory=inventory)
    paths = _hook_input_paths(
        command_payload,
        payload_text,
        command=command,
        write_target_paths=write_target_paths,
        inventory=inventory,
    )
    return HookToolIntent(
        command=command,
        paths=paths,
        write_command=_hook_write_command(command_payload, command),
        write_target_paths=write_target_paths,
        payload=command_payload,
    )


def _hook_write_command(data: dict[str, object], command: str) -> str:
    if _hook_apply_patch_target_paths(data):
        return f"{command}\n; set-content"
    return command


def _hook_input_paths(
    data: dict[str, object],
    text: str,
    *,
    command: str | None = None,
    write_target_paths: list[str] | None = None,
    inventory: Inventory | None = None,
) -> list[str]:
    apply_patch_targets = _hook_apply_patch_target_paths(data)
    if apply_patch_targets:
        return _dedupe_normalized_hook_paths(apply_patch_targets)
    explicit_write_targets = (
        write_target_paths if write_target_paths is not None else _hook_write_target_paths(data, command or _hook_input_command(data, text))
    )
    if explicit_write_targets:
        return _dedupe_normalized_hook_paths(explicit_write_targets)

    paths: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).casefold() in {"path", "file", "filename", "target", "cwd", "workdir", "command", "shell_command"}:
                    collect(item)
                elif isinstance(item, (dict, list)):
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, str):
            paths.extend(_extract_paths(_command_without_shell_literal_payloads(value)))

    collect(data)
    paths.extend(_extract_paths(_command_without_shell_literal_payloads(text)))
    if inventory is not None and command:
        paths = _filter_git_navigation_paths(inventory, data, command, paths)
    return _dedupe_normalized_hook_paths(paths)


def _filter_git_navigation_paths(
    inventory: Inventory,
    data: dict[str, object],
    command: str,
    paths: list[str],
) -> list[str]:
    navigation_tokens = _git_navigation_path_tokens(data, command)
    if not navigation_tokens:
        return paths
    normalized_tokens = {_normalize_hook_path(token).casefold() for token in navigation_tokens if str(token or "").strip()}
    resolved_tokens = {
        resolved
        for token in navigation_tokens
        if (resolved := _resolve_path_token_from_base(token, inventory.root)) is not None
    }
    filtered: list[str] = []
    for path in paths:
        if _normalize_hook_path(path).casefold() in normalized_tokens:
            continue
        resolved_path = _resolve_path_token_from_base(path, inventory.root)
        if resolved_path is not None and any(_same_resolved_path(resolved_path, resolved) for resolved in resolved_tokens):
            continue
        filtered.append(path)
    return filtered


def _git_navigation_path_tokens(data: dict[str, object], command: str) -> list[str]:
    subcommand, tokens, raw_tokens, subcommand_index = _git_command_context_tokens(command)
    if not subcommand or subcommand_index < 0:
        return []
    values: list[str] = []
    workdir = _hook_workdir_value(data)
    if workdir:
        values.append(_path_argument_value(str(workdir)) or str(workdir).strip())
    git_index = -1
    for index, token in enumerate(tokens[:subcommand_index]):
        if _is_git_executable_token(token):
            git_index = index
            break
    if git_index < 0:
        return values
    index = git_index + 1
    while index < subcommand_index:
        raw_clean = _clean_git_option_raw_token(raw_tokens[index])
        if raw_clean == "-C" and index + 1 < subcommand_index:
            values.append(_path_argument_value(raw_tokens[index + 1]) or _clean_hook_path_token(raw_tokens[index + 1]))
            index += 2
            continue
        if raw_clean.startswith("-C") and len(raw_clean) > 2:
            values.append(raw_clean[2:])
        index += 1
    return [value for value in values if value]


def _hook_write_target_paths(data: dict[str, object], command: str, *, inventory: Inventory | None = None) -> list[str]:
    apply_patch_targets = _hook_apply_patch_target_paths(data)
    if apply_patch_targets:
        return _dedupe_normalized_hook_paths(apply_patch_targets)
    targets = _shell_write_target_paths(command)
    if inventory is not None:
        return _dedupe_normalized_hook_paths(_workdir_scoped_write_targets(inventory, data, targets))
    targets.extend(_workdir_relative_write_targets(data, targets))
    return _dedupe_normalized_hook_paths(targets)


def _shell_write_target_paths(command: str, *, depth: int = 0) -> list[str]:
    if depth > 2:
        return []
    tokens = _shell_tokens(command)
    targets: list[str] = []
    targets.extend(_git_output_target_paths(tokens))
    targets.extend(_runtime_code_write_target_paths(command))
    expect_command = True
    index = 0
    while index < len(tokens):
        raw = str(tokens[index] or "").strip()
        clean = _clean_shell_command_token(raw)
        inline_redirect_target = _inline_redirection_target(raw)
        if inline_redirect_target:
            targets.append(inline_redirect_target)
            index += 1
            continue
        if _is_shell_redirection_token(raw, clean):
            if index + 1 < len(tokens):
                target = _path_argument_value(tokens[index + 1])
                if target:
                    targets.append(target)
            index += 2
            continue
        if not clean:
            if _is_shell_command_separator(raw, clean):
                expect_command = True
            index += 1
            continue
        if expect_command and clean in WRITING_COMMAND_NAMES:
            command_targets, next_index = _write_command_target_paths(tokens, index)
            targets.extend(command_targets)
            index = next_index
            expect_command = False
            continue
        if _is_shell_command_separator(raw, clean):
            expect_command = True
            index += 1
            continue
        expect_command = False
        if raw.endswith(";"):
            expect_command = True
        index += 1
    for nested in _nested_shell_commands_from_tokens(tokens):
        targets.extend(_shell_write_target_paths(nested, depth=depth + 1))
    return targets


def _workdir_relative_write_targets(data: dict[str, object], targets: list[str]) -> list[str]:
    workdir = _hook_workdir_value(data)
    if not workdir:
        return []
    workdir_rel = _path_argument_value(workdir) or str(workdir or "").strip()
    if not workdir_rel:
        return []
    normalized_workdir = _normalize_hook_path(workdir_rel).rstrip("/")
    if not normalized_workdir or re.match(r"^[a-z]:/", normalized_workdir):
        return []
    resolved: list[str] = []
    for target in targets:
        normalized = _normalize_hook_path(target)
        if (
            normalized
            and not re.match(r"^[a-z]:/", normalized)
            and not normalized.startswith("/")
            and not normalized.startswith(("../", "./", "project/", "src/", "tests/", "docs/", ".mylittleharness/"))
        ):
            resolved.append(f"{normalized_workdir}/{normalized}")
    return resolved


def _workdir_scoped_write_targets(inventory: Inventory, data: dict[str, object], targets: list[str]) -> list[str]:
    if not targets:
        return []
    workdir = _hook_command_workdir_path(inventory, data) or inventory.root
    scoped: list[str] = []
    for target in targets:
        candidate = _resolve_hook_path_from_root(inventory, target, base_root=workdir)
        if candidate is None:
            scoped.append(target)
            continue
        try:
            scoped.append(candidate.relative_to(inventory.root.resolve()).as_posix())
        except (OSError, RuntimeError, ValueError):
            scoped.append(candidate.as_posix())
    return scoped


def _hook_workdir_value(data: dict[str, object]) -> str:
    for key in ("cwd", "workdir", "working_directory", "workingDirectory"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for value in data.values():
        if isinstance(value, dict):
            nested = _hook_workdir_value(value)
            if nested:
                return nested
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    nested = _hook_workdir_value(item)
                    if nested:
                        return nested
    return ""


def _write_command_target_paths(tokens: list[str], command_index: int) -> tuple[list[str], int]:
    command = _clean_shell_command_token(tokens[command_index])
    max_positional = 2 if command in PAIRED_TARGET_WRITING_COMMAND_NAMES else 1
    single_target = command in SINGLE_TARGET_WRITING_COMMAND_NAMES
    targets: list[str] = []
    positional_count = 0
    index = command_index + 1
    while index < len(tokens):
        raw = str(tokens[index] or "").strip()
        clean = _clean_token(raw)
        if _is_shell_command_separator(raw, clean):
            break
        if _is_shell_redirection_token(raw, clean):
            break
        option_value = _write_path_option_value(raw, clean)
        if option_value:
            targets.append(option_value)
            if single_target:
                return targets, index + 1
            index += 1
            continue
        if clean in WRITING_COMMAND_PATH_OPTIONS and index + 1 < len(tokens):
            target = _path_argument_value(tokens[index + 1])
            if target:
                targets.append(target)
            if single_target:
                return targets, index + 2
            index += 2
            continue
        if clean in WRITING_COMMAND_NON_TARGET_OPTIONS_WITH_VALUES:
            index += 2
            continue
        if clean.startswith("-"):
            index += 1
            continue
        target = _path_argument_value(raw)
        if target:
            targets.append(target)
            positional_count += 1
            if single_target or positional_count >= max_positional:
                return targets, index + 1
        index += 1
    return targets, index


def _write_path_option_value(raw: str, clean: str) -> str:
    for option in WRITING_COMMAND_PATH_OPTIONS:
        for separator in ("=", ":"):
            prefix = f"{option}{separator}"
            if clean.startswith(prefix):
                value = raw.split(separator, 1)[1]
                return _path_argument_value(value)
    return ""


def _inline_redirection_target(raw: str) -> str:
    stripped = str(raw or "").strip(" \t\r\n\"'`")
    if _is_shell_fd_duplication_redirection(stripped):
        return ""
    match = re.match(r"^(?:\d+|\*)?(>>?)(.+)$", stripped)
    if match:
        return _path_argument_value(match.group(2))
    return ""


def _path_argument_value(token: str) -> str:
    value = str(token or "").strip(" \t\r\n\"'`")
    if not value:
        return ""
    normalized = value.replace("\\", "/")
    if re.match(r"^[A-Za-z]:[\\/]", value) or normalized.startswith(
        ("/", "../", "./", "project/", "src/", "tests/", "docs/", ".mylittleharness/")
    ):
        return value
    if re.match(r"^[A-Za-z0-9_.-]+\.(?:md|py|json|toml|ya?ml|txt)$", normalized):
        return value
    extracted = _extract_paths(value)
    return extracted[0] if extracted else ""


def _git_output_target_paths(tokens: list[str]) -> list[str]:
    targets: list[str] = []
    for index, token in enumerate(tokens):
        clean = _clean_shell_command_token(token)
        if clean == "--output" and index + 1 < len(tokens):
            target = _path_argument_value(tokens[index + 1])
            if target:
                targets.append(target)
        elif clean.startswith("--output="):
            target = _path_argument_value(str(token).split("=", 1)[1])
            if target:
                targets.append(target)
    return targets


def _runtime_code_write_target_paths(command: str) -> list[str]:
    if not _runtime_code_payload_looks_like_write(command):
        return []
    return _extract_paths(command)


def _runtime_code_payload_looks_like_write(command: str) -> bool:
    lowered = str(command or "").casefold()
    if not re.search(r"\b(?:python|python\.exe|py|py\.exe|node|node\.exe)\b", lowered):
        return False
    if not any(marker in lowered for marker in ("write_text(", "write_bytes(", "open(", "writefilesync", "appendfilesync", "createwritestream")):
        return False
    if "open(" in lowered and not re.search(r"open\([^)]*,\s*['\"][wa+x]", lowered):
        return False
    return bool(_extract_paths(command))


def _nested_shell_commands_from_tokens(tokens: list[str]) -> list[str]:
    nested: list[str] = []
    index = 0
    while index < len(tokens):
        raw = str(tokens[index] or "")
        clean = _clean_shell_command_token(raw)
        name = Path(clean).name
        if name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            payload, next_index = _powershell_payload(tokens, index + 1)
            if payload:
                nested.append(payload)
            index = next_index
            continue
        if name in {"cmd", "cmd.exe"}:
            payload, next_index = _shell_payload_after_option(tokens, index + 1, {"/c", "/k"})
            if payload:
                nested.append(payload)
            index = next_index
            continue
        if name in {"sh", "bash", "zsh", "fish"}:
            payload, next_index = _shell_payload_after_option(tokens, index + 1, {"-c"})
            if payload:
                nested.append(payload)
            index = next_index
            continue
        if clean == "eval" and index + 1 < len(tokens):
            nested.append(_strip_shell_payload_token(" ".join(tokens[index + 1 :])))
            break
        index += 1
    return nested


def _powershell_payload(tokens: list[str], start: int) -> tuple[str, int]:
    index = start
    while index < len(tokens):
        clean = _clean_token(tokens[index])
        if clean in {"-encodedcommand", "-enc", "-e"}:
            return "<MLH_ENCODED_COMMAND>", index + 2
        if clean in {"-command", "-c"} and index + 1 < len(tokens):
            return _strip_shell_payload_token(tokens[index + 1]), index + 2
        index += 1
    return "", index


def _shell_payload_after_option(tokens: list[str], start: int, options: set[str]) -> tuple[str, int]:
    index = start
    while index < len(tokens):
        clean = _clean_token(tokens[index])
        if clean in options and index + 1 < len(tokens):
            return _strip_shell_payload_token(" ".join(tokens[index + 1 :])), len(tokens)
        index += 1
    return "", index


def _strip_shell_payload_token(value: object) -> str:
    return str(value or "").strip(" \t\r\n\"'")


def _dedupe_normalized_hook_paths(paths: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for path in paths:
        clean = _normalize_hook_path(path)
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)
    return normalized


def _hook_apply_patch_target_paths(data: dict[str, object]) -> list[str]:
    patch_text = _hook_apply_patch_text(data)
    if not patch_text:
        return []
    targets: list[str] = []
    for line in patch_text.splitlines():
        for marker in ("*** Update File: ", "*** Add File: ", "*** Delete File: ", "*** Move to: "):
            if line.startswith(marker):
                target = line[len(marker) :].strip()
                if target:
                    targets.append(target)
    return targets


def _is_existing_route_markdown_patch_request(inventory: Inventory, data: dict[str, object]) -> bool:
    operations = _hook_apply_patch_target_operations(data)
    if not operations:
        return False
    if any(operation != "update" for operation, _path in operations):
        return False
    paths = [path for _operation, path in operations]
    return bool(paths) and all(_is_editable_route_patch_path(inventory, path) for path in paths)


def _is_active_plan_spec_doc_patch_request(inventory: Inventory, data: dict[str, object]) -> bool:
    operations = _hook_apply_patch_target_operations(data)
    if not operations:
        return False
    if any(operation != "update" for operation, _path in operations):
        return False
    paths = [path for _operation, path in operations]
    return bool(paths) and all(_is_active_plan_spec_doc_patch_path(inventory, path) for path in paths)


def _hook_apply_patch_target_operations(data: dict[str, object]) -> list[tuple[str, str]]:
    patch_text = _hook_apply_patch_text(data)
    if not patch_text:
        return []
    operations: list[tuple[str, str]] = []
    markers = (
        ("update", "*** Update File: "),
        ("add", "*** Add File: "),
        ("delete", "*** Delete File: "),
        ("move", "*** Move to: "),
    )
    for line in patch_text.splitlines():
        for operation, marker in markers:
            if line.startswith(marker):
                target = line[len(marker) :].strip()
                if target:
                    operations.append((operation, target))
    return operations


def _is_editable_route_patch_path(inventory: Inventory, path: str) -> bool:
    rel = _hook_route_rel_path(inventory, path)
    if not rel or _is_lifecycle_authority_path(rel):
        return False
    if classify_memory_route(rel).route_id not in EDITABLE_ROUTE_PATCH_IDS:
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        frontmatter = parse_frontmatter(route_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    return frontmatter.has_frontmatter and not frontmatter.errors


def _is_active_plan_spec_doc_patch_path(inventory: Inventory, path: str) -> bool:
    rel = _hook_route_rel_path(inventory, path)
    if not rel or _is_lifecycle_authority_path(rel):
        return False
    normalized = _normalize_hook_path(rel).casefold()
    if not any(normalized.startswith(prefix) for prefix in ACTIVE_PLAN_SPEC_DOC_PREFIXES):
        return False
    if not _active_phase_write_scope_allows_path(inventory, normalized):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        frontmatter = parse_frontmatter(route_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    return frontmatter.has_frontmatter and not frontmatter.errors


def _hook_route_rel_path(inventory: Inventory, path: str) -> str:
    normalized = _normalize_hook_path(path)
    candidate = _resolve_hook_path_from_root(inventory, path)
    if candidate is not None:
        try:
            return candidate.relative_to(inventory.root.resolve()).as_posix()
        except (OSError, RuntimeError, ValueError):
            return "" if _path_escapes_root(path) else normalized
    try:
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            return candidate.resolve().relative_to(inventory.root.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return ""
    return normalized


def _hook_route_file_path(inventory: Inventory, path: str) -> Path | None:
    rel = _hook_route_rel_path(inventory, path)
    if not rel:
        return None
    try:
        route_path = (inventory.root / rel).resolve()
        route_path.relative_to(inventory.root.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return route_path


def _hook_apply_patch_text(data: dict[str, object]) -> str:
    candidates = (
        data.get("input"),
        data.get("patch"),
        data.get("tool_input"),
        data.get("parameters"),
        data.get("arguments"),
        data.get("command"),
        data.get("shell_command"),
        data.get("cmd"),
        data.get("raw"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and "*** Begin Patch" in candidate:
            return candidate
        if isinstance(candidate, dict):
            nested = _hook_apply_patch_text(candidate)
            if nested:
                return nested
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, str) and "*** Begin Patch" in item:
                    return item
                if isinstance(item, dict):
                    nested = _hook_apply_patch_text(item)
                    if nested:
                        return nested
    return ""


def _extract_paths(text: str) -> list[str]:
    matches: list[str] = []
    for match in PATH_RE.finditer(text or ""):
        value = match.group(0).strip(" \t\r\n\"'`") or (match.group(1) or "").strip(" \t\r\n\"'`")
        if value:
            matches.append(value)
    return matches


def _clean_hook_path_token(path: str) -> str:
    return str(path or "").strip().strip(" \t\r\n\"'`([{").rstrip(".,;:)]}")


def _normalize_hook_path(path: str) -> str:
    rel = _clean_hook_path_token(path).replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def _resolve_hook_path_from_root(inventory: Inventory, path: str, *, base_root: Path | None = None) -> Path | None:
    raw = _clean_hook_path_token(path)
    if not raw:
        return None
    try:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (base_root or inventory.root) / candidate
        return candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _path_escapes_root(path: str) -> bool:
    return _normalize_hook_path(path).startswith("../")


def _path_resolves_under_base_root(inventory: Inventory, path: str, base_root: Path) -> bool:
    target = _resolve_hook_path_from_root(inventory, path, base_root=base_root)
    if target is None:
        return False
    try:
        target.relative_to(base_root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _path_policy_findings(
    inventory: Inventory,
    paths: list[str],
    *,
    warn_only: bool = False,
    allow_read_only_source_paths: bool = False,
    allow_read_only_roadmap_path: bool = False,
    allow_mlh_owner_route_paths: bool = False,
    allow_existing_route_patch: bool = False,
    allow_active_plan_spec_doc_patch: bool = False,
    allow_post_closeout_lifecycle_route_stage: bool = False,
    allow_post_closeout_local_vcs_stage: bool = False,
    allow_post_closeout_lifecycle_vcs_finalization_paths: set[str] | None = None,
    allow_delegation_prompt_context: bool = False,
    allow_product_source_vcs_command: bool = False,
    reviewed_local_vcs_checkpoint_root: Path | None = None,
    reviewed_local_vcs_checkpoint_paths: set[str] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    severity = "warn" if warn_only else "error"
    finalization_paths = allow_post_closeout_lifecycle_vcs_finalization_paths or set()
    checkpoint_paths = reviewed_local_vcs_checkpoint_paths or set()
    for rel in paths:
        if _is_generated_cache_path(rel):
            recovery_command = _generated_cache_recovery_command(inventory)
            findings.append(
                Finding(
                    severity,
                    "hooks-policy-block-generated-cache-path",
                    (
                        "tool request touches generated projection/cache paths; cache remains disposable and should be "
                        f"refreshed through projection rails; next_safe_command={recovery_command}"
                    ),
                    rel,
                )
            )
        route_rel_display = _hook_route_rel_path(inventory, rel) or _normalize_hook_path(rel)
        route_rel = route_rel_display.casefold()
        if route_rel in finalization_paths:
            continue
        if route_rel in checkpoint_paths:
            continue
        if (
            checkpoint_paths
            and reviewed_local_vcs_checkpoint_root is not None
            and _path_resolves_under_base_root(inventory, rel, reviewed_local_vcs_checkpoint_root)
        ):
            continue
        if allow_delegation_prompt_context and _is_delegation_prompt_context_path(inventory, rel):
            continue
        if (allow_read_only_source_paths or allow_mlh_owner_route_paths) and _is_lifecycle_route_path(route_rel_display):
            continue
        if allow_read_only_roadmap_path and _is_roadmap_path(route_rel_display):
            continue
        if allow_existing_route_patch and _is_editable_route_patch_path(inventory, rel):
            continue
        if allow_active_plan_spec_doc_patch and _is_active_plan_spec_doc_patch_path(inventory, rel):
            continue
        if allow_post_closeout_lifecycle_route_stage and _is_post_closeout_lifecycle_route_stage_path(inventory, rel):
            continue
        if allow_post_closeout_local_vcs_stage and (
            _is_exact_post_closeout_stage_file(inventory, rel)
            or _is_post_closeout_source_incubation_tombstone_path(inventory, rel)
            or _is_reviewed_meta_feedback_checkpoint_stage_file(inventory, rel)
        ):
            continue
        if _is_under_configured_product_root(inventory, rel):
            if allow_product_source_vcs_command:
                continue
            if allow_read_only_source_paths or allow_mlh_owner_route_paths:
                continue
            if _is_active_plan_product_artifact(inventory, rel):
                findings.append(
                    Finding(
                        "info",
                        "hooks-policy-allow-active-plan-product-source-artifact",
                        product_source_operator_lane_summary(),
                        rel,
                    )
                )
                continue
            next_safe = _hook_product_root_write_next_safe_command(inventory, rel)
            findings.append(
                Finding(
                    severity,
                    "hooks-policy-block-product-root-path",
                    (
                        "tool request names the configured product source root from an operating-root context; "
                        "keep product edits deliberate and bounded by active-plan target_artifacts; "
                        f"next_safe_command={next_safe}"
                    ),
                    rel,
                )
            )
            continue
        if _is_lifecycle_authority_path(route_rel_display):
            findings.append(
                Finding(
                    severity,
                    "hooks-policy-block-lifecycle-authority-path",
                    (
                        "tool request touches lifecycle authority paths; use explicit MLH dry-run/apply routes "
                        f"and record docs_decision/verification as required; next_safe_command={_hook_route_next_safe_command(inventory, rel)}"
                    ),
                    route_rel_display,
                )
            )
        elif _is_lifecycle_markdown_path(route_rel_display):
            next_safe = _hook_lifecycle_markdown_path_next_safe_command(inventory, route_rel_display)
            findings.append(
                Finding(
                    severity,
                    "hooks-policy-block-lifecycle-markdown-path",
                    (
                        "tool request touches lifecycle Markdown routes; required frontmatter and owning route evidence "
                        f"must stay intact; next_safe_command={next_safe}"
                    ),
                    route_rel_display,
                )
            )
    return findings


def _first_mlh_owner_route_evidence_path(inventory: Inventory, paths: list[str]) -> str:
    for rel in paths:
        if (
            _is_lifecycle_route_path(rel)
            or _is_under_configured_product_root(inventory, rel)
            or _is_code_path(rel)
        ):
            return rel
    return ""


def _is_bounded_mlh_read_tool_request(data: dict[str, object]) -> bool:
    for lowered in _hook_tool_names(data):
        if lowered.endswith(BOUNDED_MLH_READ_TOOL_SUFFIXES):
            return True
    return False


def _hook_tool_name(data: dict[str, object]) -> str:
    names = _hook_tool_names(data)
    return names[0] if names else ""


def _hook_tool_names(data: dict[str, object]) -> list[str]:
    names: list[str] = []
    wrapper_keys = {
        "tool_uses",
        "tooluse",
        "tool_calls",
        "toolcalls",
        "tool_call",
        "toolcall",
        "call",
        "calls",
        "function",
        "arguments",
        "parameters",
        "params",
        "tool_input",
        "input",
        "request",
        "payload",
        "data",
        "target",
        "project",
        "body",
        "message",
        "messages",
    }

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for key in ("toolName", "tool_name", "tool", "recipient_name", "name"):
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    names.append(item.strip().casefold())
            for key, item in value.items():
                if str(key).casefold() in wrapper_keys and isinstance(item, (dict, list)):
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(data)
    return _dedupe_nonempty(names)


def _is_subagent_delegation_tool_request(data: dict[str, object]) -> bool:
    return any(
        tool_name.endswith(marker) or marker in tool_name
        for tool_name in _hook_tool_names(data)
        for marker in READ_ONLY_SUBAGENT_DELEGATION_TOOLS
    )


def _is_subagent_delegation_only_request(data: dict[str, object]) -> bool:
    names = _hook_tool_names(data)
    if not names:
        return False
    has_delegation = False
    for tool_name in names:
        is_delegation = any(tool_name.endswith(marker) or marker in tool_name for marker in READ_ONLY_SUBAGENT_DELEGATION_TOOLS)
        has_delegation = has_delegation or is_delegation
        if not is_delegation:
            return False
    return has_delegation


def _subagent_delegation_forbidden_shortcut(text: str) -> bool:
    raw = str(text or "")
    if _is_reviewed_local_vcs_delegation_prompt(raw):
        scrubbed = SUBAGENT_DELEGATION_LOCAL_VCS_RE.sub(" ", raw)
        scrubbed = _scrub_negated_subagent_delegation_guardrails(scrubbed)
    else:
        scrubbed = _scrub_negated_subagent_delegation_guardrails(raw)
    if _is_safe_route_delegation_coordination_prompt(raw, scrubbed):
        return False
    return bool(SUBAGENT_DELEGATION_FORBIDDEN_RE.search(scrubbed) or SUBAGENT_DELEGATION_UNSAFE_EXTERNAL_RE.search(scrubbed))


def _scrub_negated_subagent_delegation_guardrails(text: str) -> str:
    scrubbed = SUBAGENT_DELEGATION_NEGATED_GUARDRAIL_RE.sub(" ", str(text or ""))
    scrubbed = SUBAGENT_DELEGATION_NEGATED_BYPASS_TAIL_RE.sub(" ", scrubbed)
    scrubbed = SUBAGENT_DELEGATION_NEGATED_EXTERNAL_RE.sub(" ", scrubbed)
    scrubbed = SUBAGENT_DELEGATION_NEGATED_CLASSIFICATION_RE.sub(" ", scrubbed)
    return SUBAGENT_DELEGATION_PROTECTIVE_POLICY_BOUNDARY_RE.sub(" ", scrubbed)


def _is_safe_route_delegation_coordination_prompt(raw: str, scrubbed: str) -> bool:
    lowered = str(raw or "").casefold()
    scrubbed_lowered = str(scrubbed or "").casefold()
    if SUBAGENT_DELEGATION_UNSAFE_EXTERNAL_RE.search(scrubbed):
        return False
    if SUBAGENT_DELEGATION_DIRECT_MUTATION_RE.search(scrubbed):
        return False
    if "--apply" in scrubbed_lowered and not any(
        marker in lowered for marker in ("dry-run", "dry run", "reviewed", "legal mlh", "mlh route", "mlh routes")
    ):
        return False
    context_hits = sum(1 for marker in SAFE_DELEGATION_ROUTE_CONTEXT_MARKERS if marker in lowered)
    boundary_hits = sum(1 for marker in SAFE_DELEGATION_BOUNDARY_MARKERS if marker in lowered)
    if context_hits < 2 or boundary_hits < 2:
        return False
    return any(marker in lowered for marker in ("create_thread", "handoff", "thread", "worker", "agent", "delegation"))


def _delegation_prompt_text(data: dict[str, object], fallback_text: str) -> str:
    prompt_parts: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered_key = str(key).casefold()
                if lowered_key in {"input", "prompt", "message", "body", "content", "task", "instructions"} and isinstance(item, str):
                    prompt_parts.append(item)
                elif isinstance(item, (dict, list)):
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(data)
    return "\n".join(part for part in prompt_parts if part.strip()) or str(fallback_text or "")


def _delegation_direct_command_text(data: dict[str, object]) -> str:
    if not _is_subagent_delegation_tool_request(data):
        return ""
    commands = [
        _hook_input_command(payload, "")
        for payload in _hook_direct_command_payloads(data)
    ]
    return "\n".join(command for command in commands if command.strip())


def _is_typed_route_delegation_intent(data: dict[str, object], text: str) -> bool:
    if not _is_subagent_delegation_tool_request(data):
        return False
    raw = _delegation_prompt_text(data, text)
    lowered = raw.casefold()
    scrubbed = _scrub_negated_subagent_delegation_guardrails(raw)
    if SUBAGENT_DELEGATION_UNSAFE_EXTERNAL_RE.search(scrubbed):
        return False
    if SUBAGENT_DELEGATION_DIRECT_MUTATION_RE.search(scrubbed):
        return False
    if re.search(
        r"(?i)\b(?:run|execute|call|invoke|perform|do)\b[^\n\r.;]*"
        r"(?:\bgit\s+(?:add|stage|commit|push|reset|checkout|clean|restore|rm|mv)\b|"
        r"\b(?:writeback|roadmap|plan|transition|repair|memory-hygiene|meta-feedback|projection)\b[^\n\r.;]*\s--apply\b)",
        scrubbed,
    ):
        return False
    context_hits = sum(1 for marker in SAFE_DELEGATION_ROUTE_CONTEXT_MARKERS if marker in lowered)
    boundary_hits = sum(1 for marker in SAFE_DELEGATION_BOUNDARY_MARKERS if marker in lowered)
    if context_hits < 3 or boundary_hits < 2:
        return False
    return any(marker in lowered for marker in ("thread", "delegation", "handoff", "worker", "agent", "subagent"))


def _is_reviewed_local_vcs_delegation_prompt(text: str) -> bool:
    raw = str(text or "")
    lowered = raw.casefold()
    if not SUBAGENT_DELEGATION_LOCAL_VCS_RE.search(raw):
        return False
    if not any(marker in lowered for marker in LOCAL_VCS_DELEGATION_PURPOSE_MARKERS):
        return False
    boundary_hits = sum(1 for marker in LOCAL_VCS_DELEGATION_BOUNDARY_MARKERS if marker in lowered)
    if boundary_hits < 3:
        return False
    return any(marker in lowered for marker in ("local-only", "local only", "no push", "do not push", "without push", "without pushing"))


def _is_reviewed_local_vcs_delegation_request(data: dict[str, object], text: str) -> bool:
    return (
        _is_subagent_delegation_tool_request(data)
        and _is_reviewed_local_vcs_delegation_prompt(text)
        and not _subagent_delegation_forbidden_shortcut(text)
    )


def _is_read_only_subagent_delegation_request(data: dict[str, object], text: str) -> bool:
    if not _is_subagent_delegation_tool_request(data):
        return False
    lowered = str(text or "").casefold()
    if _subagent_delegation_forbidden_shortcut(lowered):
        return False
    return any(marker in lowered for marker in READ_ONLY_SUBAGENT_DELEGATION_MARKERS)


def _is_delegation_prompt_context_request(data: dict[str, object], text: str) -> bool:
    if not _is_subagent_delegation_tool_request(data):
        return False
    prompt_text = _delegation_prompt_text(data, text)
    scrubbed = _scrub_negated_subagent_delegation_guardrails(prompt_text)
    if _subagent_delegation_prompt_direct_mutation_request(prompt_text, scrubbed):
        return False
    if _is_typed_route_delegation_intent(data, text):
        return True
    return True


def _subagent_delegation_prompt_direct_mutation_request(raw: str, scrubbed: str) -> bool:
    clean = str(scrubbed or raw or "").strip()
    if SUBAGENT_DELEGATION_DIRECT_MUTATION_RE.search(clean):
        return True
    protected_command = (
        r"(?:"
        r"\bgit\s+(?:add|stage|commit|push|reset|checkout|clean|restore|rm|mv)\b|"
        r"\bmy(?:littleharness)?\b[^\n\r;]*\s--apply\b|"
        r"\b(?:writeback|roadmap|plan|transition|repair|memory-hygiene|meta-feedback|projection)\b[^\n\r;]*\s--apply\b|"
        r"\bmlhd\s+run-once\s+--apply\b|"
        r"\bapply_patch\b|"
        r"\b(?:set-content|add-content|out-file|new-item|remove-item|move-item|copy-item)\b|"
        r"\b(?:start|launch|serve|run)\s+(?:provider|daemon|runtime|launcher)\b"
        r")"
    )
    if re.search(r"(?i)(?:^|[\n\r.;]\s*)(?:please\s+)?(?:run|execute|call|invoke|perform|do|use)\b[^\n\r;]*" + protected_command, clean):
        return True
    return bool(re.match(r"(?i)^(?:please\s+)?" + protected_command, clean))


def _mlh_policy_command(command: str) -> str:
    return _powershell_mlh_splat_policy_command(command) or command


def _powershell_mlh_splat_policy_command(command: str, *, depth: int = 0) -> str:
    if depth > 2:
        return ""
    stripped = _command_without_shell_literal_payloads(command or "").strip()
    expanded = _direct_powershell_mlh_splat_policy_command(stripped)
    if expanded:
        return expanded
    for nested in _nested_shell_commands_from_tokens(_shell_tokens(stripped)):
        expanded = _powershell_mlh_splat_policy_command(nested, depth=depth + 1)
        if expanded:
            return expanded
    return ""


def _has_unresolved_mlh_splat_invocation(command: str) -> bool:
    return _powershell_mlh_splat_invocation_present(command) and not _powershell_mlh_splat_policy_command(command)


def _powershell_mlh_splat_invocation_present(command: str, *, depth: int = 0) -> bool:
    if depth > 2:
        return False
    stripped = _command_without_shell_literal_payloads(command or "").strip()
    if POWERSHELL_SPLAT_INVOCATION_RE.search(stripped):
        return True
    return any(
        _powershell_mlh_splat_invocation_present(nested, depth=depth + 1)
        for nested in _nested_shell_commands_from_tokens(_shell_tokens(stripped))
    )


def _direct_powershell_mlh_splat_policy_command(command: str) -> str:
    match = POWERSHELL_SPLAT_INVOCATION_RE.search(command or "")
    if not match:
        return ""
    prefix = command[: match.start()]
    scalars, arrays, remainder = _powershell_literal_assignments(prefix)
    if remainder.strip(" \t\r\n;"):
        return ""
    args = arrays.get(str(match.group("var") or "").casefold())
    if args is None:
        return ""
    executable = str(match.group("exe") or "").strip()
    executable_tokens = (
        ["python", "-m", "my" + "littleharness"]
        if re.match(r"^(?:python|py)(?:\.exe)?\s+-m\s+my" + "littleharness$", executable, re.IGNORECASE)
        else ["my" + "littleharness"]
    )
    return subprocess.list2cmdline(executable_tokens + args)


def _powershell_literal_assignments(prefix: str) -> tuple[dict[str, str], dict[str, list[str]], str]:
    scalars: dict[str, str] = {}
    arrays: dict[str, list[str]] = {}
    remainder = prefix or ""
    while True:
        stripped = remainder.lstrip(" \t\r\n;")
        if not stripped:
            return scalars, arrays, ""
        scalar = POWERSHELL_SCALAR_ASSIGNMENT_RE.match(stripped)
        if scalar:
            quote = scalar.group(2)
            value = scalar.group(3)
            if not _powershell_literal_is_static(value, quote):
                return scalars, arrays, stripped
            scalars[str(scalar.group(1)).casefold()] = value
            remainder = stripped[scalar.end() :]
            continue
        array = POWERSHELL_ARRAY_ASSIGNMENT_RE.match(stripped)
        if array:
            parsed = _parse_powershell_literal_array(array.group(2), scalars)
            if parsed is None:
                return scalars, arrays, stripped
            arrays[str(array.group(1)).casefold()] = parsed
            remainder = stripped[array.end() :]
            continue
        return scalars, arrays, stripped


def _parse_powershell_literal_array(body: str, scalars: dict[str, str]) -> list[str] | None:
    items: list[str] = []
    index = 0
    while index < len(body):
        while index < len(body) and body[index] in " \t\r\n,":
            index += 1
        if index >= len(body):
            break
        char = body[index]
        if char in {"'", '"'}:
            quote = char
            index += 1
            value_parts: list[str] = []
            while index < len(body):
                current = body[index]
                if current == quote:
                    if index + 1 < len(body) and body[index + 1] == quote:
                        value_parts.append(quote)
                        index += 2
                        continue
                    break
                value_parts.append(current)
                index += 1
            else:
                return None
            value = "".join(value_parts)
            if not _powershell_literal_is_static(value, quote):
                return None
            items.append(value)
            index += 1
        elif char == "$":
            match = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)", body[index:])
            if not match:
                return None
            name = match.group(1).casefold()
            if name not in scalars:
                return None
            items.append(scalars[name])
            index += len(match.group(0))
        else:
            return None
        while index < len(body) and body[index] in " \t\r\n":
            index += 1
        if index < len(body) and body[index] == ",":
            index += 1
            continue
        if index < len(body) and body[index] not in " \t\r\n":
            return None
    return items


def _powershell_literal_is_static(value: str, quote: str) -> bool:
    if "`" in value or "$(" in value:
        return False
    return not (quote == '"' and "$" in value)


def _is_mlh_owner_route_review_command(command: str) -> bool:
    policy_command = _mlh_policy_command(command)
    lowered = policy_command.casefold()
    tokens = _mlh_command_token_set(policy_command)
    subcommand = _mlh_cli_subcommand(lowered)
    if subcommand == "suggest":
        return (
            not _looks_like_write_command(command)
            and (
                "--intent" in tokens
                or any(token.startswith("--intent=") for token in tokens)
                or _has_mlh_review_mode_token(policy_command)
            )
        )
    if subcommand == "evidence":
        return not _looks_like_write_command(command) and (
            bool(tokens.intersection({"--help", "-h"}))
            or
            _is_mlh_evidence_record_route_command(policy_command)
            or _is_mlh_evidence_receipt_refresh_route_command(policy_command)
            or _is_mlh_evidence_fixture_update_route_command(policy_command)
        )
    if subcommand == "retention" and "scan" in tokens:
        return not _looks_like_write_command(command)
    return (
        subcommand in MLH_OWNER_ROUTE_REVIEW_COMMANDS
        and not _looks_like_write_command(command)
        and _has_mlh_review_mode_token(policy_command)
    )


def _mlh_command_token_set(command: str) -> set[str]:
    return {_clean_token(token) for token in _shell_tokens(command)}


def _has_mlh_review_mode_token(command: str) -> bool:
    return bool(_mlh_command_token_set(command).intersection({"--dry-run", "--apply", "--help", "-h"}))


def _has_mlh_option_value(command: str, option: str) -> bool:
    expected = option.casefold()
    tokens = _shell_tokens(command)
    for index, token in enumerate(tokens):
        clean = _clean_token(token)
        if clean == expected:
            return index + 1 < len(tokens) and bool(_clean_token(tokens[index + 1])) and not _clean_token(tokens[index + 1]).startswith("-")
        if clean.startswith(expected + "="):
            return bool(clean.split("=", 1)[1])
    return False


def _is_mlh_evidence_record_route_command(command: str) -> bool:
    lowered = command.casefold()
    tokens = _mlh_command_token_set(command)
    return (
        _mlh_cli_subcommand(lowered) == "evidence"
        and not _looks_like_write_command(command)
        and "--record" in tokens
        and (_has_mlh_option_value(command, "--record-id") or tokens.intersection({"--help", "-h"}))
        and _has_mlh_review_mode_token(command)
    )


def _is_mlh_evidence_receipt_refresh_route_command(command: str) -> bool:
    lowered = command.casefold()
    tokens = _mlh_command_token_set(command)
    return (
        _mlh_cli_subcommand(lowered) == "evidence"
        and not _looks_like_write_command(command)
        and "--receipt-refresh" in tokens
        and (_has_mlh_option_value(command, "--target") or tokens.intersection({"--help", "-h"}))
        and _has_mlh_review_mode_token(command)
    )


def _is_mlh_evidence_fixture_update_route_command(command: str) -> bool:
    lowered = command.casefold()
    tokens = _mlh_command_token_set(command)
    return (
        _mlh_cli_subcommand(lowered) == "evidence"
        and not _looks_like_write_command(command)
        and "--fixture-update" in tokens
        and (_has_mlh_option_value(command, "--target") or tokens.intersection({"--help", "-h"}))
        and _has_mlh_review_mode_token(command)
    )


def _is_research_import_related_prompt_provenance_command(command: str) -> bool:
    policy_command = _mlh_policy_command(command)
    related_prompt = _research_import_related_prompt_path(policy_command)
    if not related_prompt:
        return False
    return (
        _mlh_cli_subcommand(policy_command.casefold()) == "research-import"
        and _has_mlh_review_mode_token(policy_command)
        and not _looks_like_write_command(command)
    )


def _research_import_related_prompt_path(command: str) -> str:
    if _mlh_cli_subcommand(command.casefold()) != "research-import":
        return ""
    tokens = _shell_tokens(command)
    for index, token in enumerate(tokens):
        clean = _clean_token(token)
        if clean == "--related-prompt" and index + 1 < len(tokens):
            return _clean_token(tokens[index + 1])
        if clean.startswith("--related-prompt="):
            return clean.partition("=")[2].strip()
    return ""


def _is_read_only_source_discovery_command(command: str) -> bool:
    if _looks_like_write_command(command):
        return False
    tokens = _shell_tokens(command)
    for index, token in enumerate(tokens):
        clean = _clean_shell_command_token(token)
        if not clean or clean.startswith("-"):
            continue
        if clean not in READ_ONLY_SOURCE_DISCOVERY_COMMANDS:
            continue
        return _has_read_only_discovery_prefix(tokens[:index])
    return False


def _is_read_only_shell_wrapper_command(command: str) -> bool:
    if _looks_like_write_command(command):
        return False
    nested_commands = [
        nested
        for nested in _nested_shell_commands_from_tokens(_shell_tokens(command))
        if nested and nested != "<MLH_ENCODED_COMMAND>"
    ]
    if not nested_commands:
        return False
    return all(
        _is_read_only_source_discovery_command(nested)
        or _is_read_only_git_inspection_command(nested)
        or _is_read_only_mlh_inspection_command(nested)
        for nested in nested_commands
    )


def _is_read_only_hook_diagnostic_simulation_command(command: str) -> bool:
    payload_commands = _hook_diagnostic_simulation_payload_commands(command)
    return bool(payload_commands) and not _has_unsafe_hook_diagnostic_simulation_payload(command)


def _has_unsafe_hook_diagnostic_simulation_payload(command: str) -> bool:
    payload_commands = _hook_diagnostic_simulation_payload_commands(command)
    if not payload_commands:
        return False
    if _looks_like_write_command(command):
        return True
    if POWERSHELL_HOOK_SIMULATION_EXECUTION_RE.search(_command_without_shell_literal_payloads(command or "")):
        return True
    return any(not _is_read_only_hook_diagnostic_payload_command(payload) for payload in payload_commands)


def _hook_diagnostic_simulation_payload_commands(command: str) -> list[str]:
    if not _is_mlh_hook_diagnostic_run_command(command):
        return []
    scalars, _arrays, _remainder = _powershell_literal_assignments(_command_prefix_before_first_mlh_invocation(command))
    payload_commands: list[str] = []
    for match in POWERSHELL_HOOK_SIMULATION_COMMAND_FIELD_RE.finditer(command or ""):
        variable = str(match.group(1) or "").casefold()
        literal = str(match.group(3) or "")
        if variable:
            candidate = scalars.get(variable, "")
            if candidate:
                payload_commands.append(candidate)
        elif literal:
            payload_commands.append(literal)
    return _dedupe_nonempty(payload_commands)


def _command_prefix_before_first_mlh_invocation(command: str) -> str:
    text = command or ""
    pattern = re.compile(
        r"\b(?:my" + r"littleharness|python\s+-m\s+my" + r"littleharness|py\s+-m\s+my" + r"littleharness)\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        if not _is_inside_powershell_quoted_literal(text, match.start()):
            return text[: match.start()]
    return text


def _is_inside_powershell_quoted_literal(text: str, index: int) -> bool:
    quote = ""
    cursor = 0
    while cursor < min(index, len(text)):
        current = text[cursor]
        if quote:
            if current == quote:
                if cursor + 1 < index and text[cursor + 1] == quote:
                    cursor += 2
                    continue
                quote = ""
        elif current in {"'", '"'}:
            quote = current
        cursor += 1
    return bool(quote)


def _is_mlh_hook_diagnostic_run_command(command: str) -> bool:
    policy_command = _mlh_policy_command(command)
    if _mlh_cli_subcommand(policy_command) != "hooks":
        return False
    tokens = [_clean_token(token) for token in _shell_tokens(policy_command)]
    for index, token in enumerate(tokens):
        if token == "--run" and index + 1 < len(tokens):
            return tokens[index + 1] in {HOOK_PRE_TOOL_USE, HOOK_POST_TOOL_USE}
        if token.startswith("--run="):
            return token.partition("=")[2] in {HOOK_PRE_TOOL_USE, HOOK_POST_TOOL_USE}
    return False


def _is_read_only_hook_diagnostic_payload_command(command: str) -> bool:
    if _looks_like_write_command(command) or _looks_like_git_stage_or_commit(command.casefold()):
        return False
    return (
        _is_read_only_source_discovery_command(command)
        or _is_read_only_git_inspection_command(command)
        or _is_read_only_mlh_inspection_command(command)
        or _is_read_only_mlh_report_command(command)
    )


def _has_read_only_discovery_prefix(tokens: list[str]) -> bool:
    for token in tokens:
        clean = _clean_token(token)
        if not clean:
            continue
        if clean in READ_ONLY_SOURCE_DISCOVERY_PREFIX_TOKENS:
            continue
        if clean.startswith("$") or _is_hook_pathish_token(clean):
            continue
        return False
    return True


def _is_hook_pathish_token(token: str) -> bool:
    clean = _normalize_hook_path(token).casefold()
    if re.match(r"^[a-z]:/", clean):
        return True
    return clean.startswith(("project/", "src/", "tests/", "docs/", ".mylittleharness/"))


def _is_read_only_git_inspection_command(command: str) -> bool:
    if _looks_like_write_command(command):
        return False
    subcommand = _git_subcommand(command)
    if subcommand in READ_ONLY_GIT_INSPECTION_COMMANDS:
        return True
    if subcommand in READ_ONLY_GIT_REF_INSPECTION_COMMANDS:
        return _is_read_only_git_ref_inspection_command(command)
    return False


def _is_read_only_git_ref_inspection_command(command: str) -> bool:
    subcommand, tokens, subcommand_index = _git_command_context(command)
    if subcommand_index < 0:
        return False
    args = [_clean_token(token) for token in tokens[subcommand_index + 1 :] if _clean_token(token)]
    if not args:
        return True
    if subcommand == "branch":
        return _git_ref_inspection_args_are_read_only(
            args,
            forbidden_exact={
                "-c",
                "-C",
                "-d",
                "-D",
                "-f",
                "-m",
                "-M",
                "--copy",
                "--create-reflog",
                "--delete",
                "--edit-description",
                "--force",
                "--move",
                "--no-track",
                "--recurse-submodules",
                "--set-upstream-to",
                "--track",
                "--unset-upstream",
            },
            value_options={"--abbrev", "--color", "--contains", "--format", "--merged", "--no-merged", "--points-at", "--sort"},
            list_options={"--list", "-l"},
            flag_options={"--all", "--column", "--ignore-case", "--no-abbrev", "--no-column", "--remotes", "--show-current", "--verbose", "-a", "-r", "-v", "-vv"},
            combined_flag_re=r"^-[arv]+$",
        )
    if subcommand == "tag":
        return _git_ref_inspection_args_are_read_only(
            args,
            forbidden_exact={
                "-a",
                "-d",
                "-f",
                "-F",
                "-m",
                "-s",
                "-u",
                "--annotate",
                "--delete",
                "--file",
                "--force",
                "--local-user",
                "--message",
                "--sign",
            },
            value_options={"--color", "--contains", "--format", "--merged", "--no-merged", "--points-at", "--sort"},
            list_options={"--list", "-l"},
            flag_options={"--ignore-case", "-n"},
            combined_flag_re=r"^-n\d*$",
        )
    return False


def _git_ref_inspection_args_are_read_only(
    args: list[str],
    *,
    forbidden_exact: set[str],
    value_options: set[str],
    list_options: set[str],
    flag_options: set[str],
    combined_flag_re: str,
) -> bool:
    allow_patterns = False
    expecting_value = False
    for arg in args:
        if not arg:
            continue
        if expecting_value:
            expecting_value = False
            continue
        if arg == "--":
            allow_patterns = True
            continue
        option_name = arg.split("=", 1)[0]
        if arg in forbidden_exact or option_name in forbidden_exact:
            return False
        if option_name in list_options:
            allow_patterns = True
            continue
        if option_name in value_options:
            if "=" not in arg:
                expecting_value = True
            continue
        if arg in flag_options or re.match(combined_flag_re, arg):
            continue
        if arg.startswith("-"):
            return False
        if not allow_patterns:
            return False
    return not expecting_value


def _is_read_only_product_source_vcs_inspection_command(inventory: Inventory, command: str, paths: list[str]) -> bool:
    return _is_read_only_git_inspection_command(command) and any(
        _is_under_configured_product_root(inventory, path) for path in paths
    )


def _is_read_only_mlh_inspection_command(command: str) -> bool:
    if _looks_like_write_command(command) or _looks_like_git_stage_or_commit(command.casefold()):
        return False
    if _has_unresolved_mlh_splat_invocation(command):
        return False
    policy_command = _mlh_policy_command(command)
    tokens = _mlh_command_token_set(policy_command)
    if tokens.intersection(READ_ONLY_PRODUCT_SOURCE_INSPECTION_FORBIDDEN_TOKENS):
        return False
    subcommands = _mlh_cli_subcommands(policy_command)
    return bool(subcommands) and all(
        subcommand in READ_ONLY_PRODUCT_SOURCE_INSPECTION_COMMANDS for subcommand in subcommands
    )


def _is_read_only_mlh_report_command(command: str) -> bool:
    if _looks_like_write_command(command) or _looks_like_git_stage_or_commit(command.casefold()):
        return False
    if _has_unresolved_mlh_splat_invocation(command):
        return False
    policy_command = _mlh_policy_command(_strip_read_only_mlh_report_pipeline(command))
    subcommands = _mlh_cli_subcommands(policy_command)
    if not subcommands:
        return False
    return all(_is_read_only_mlh_report_subcommand(policy_command, subcommand) for subcommand in subcommands)


def _is_read_only_mlh_report_subcommand(command: str, subcommand: str) -> bool:
    subcommand = str(subcommand or "").casefold()
    required = READ_ONLY_MLH_REPORT_COMMAND_OPTIONS.get(subcommand)
    allowed_options = READ_ONLY_MLH_REPORT_ALLOWED_OPTIONS.get(subcommand)
    if not required or not allowed_options:
        return False
    tokens = _mlh_command_token_set(command)
    if not tokens.intersection(required):
        return False
    if tokens.intersection(READ_ONLY_PRODUCT_SOURCE_INSPECTION_FORBIDDEN_TOKENS):
        return False
    if tokens.intersection({"--action", "--apply", "--dry-run", "--items-file", "--item-id"}):
        return False
    args = _mlh_subcommand_argument_tokens(command, subcommand)
    return _mlh_report_args_are_read_only(args, allowed_options)


def _strip_read_only_mlh_report_pipeline(command: str) -> str:
    command = _strip_read_only_mlh_report_powershell_suffix(command)
    tokens = _shell_tokens(command)
    if "|" not in tokens:
        return command
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token == "|":
            segments.append([])
            continue
        segments[-1].append(token)
    if len(segments) < 2 or not segments[0] or any(not segment for segment in segments[1:]):
        return command
    first_segment = _strip_read_only_mlh_report_assignment_prefix(segments[0])
    if not first_segment:
        return command
    if not all(_is_read_only_mlh_report_pipeline_segment(segment) for segment in segments[1:]):
        return command
    return " ".join(first_segment)


def _strip_read_only_mlh_report_assignment_prefix(tokens: list[str]) -> list[str]:
    if len(tokens) >= 3 and _clean_token(tokens[0]).startswith("$") and _clean_token(tokens[1]) == "=":
        return tokens[2:]
    return tokens


def _strip_read_only_mlh_report_powershell_suffix(command: str) -> str:
    if ";" not in command:
        return command
    head, suffix = command.split(";", 1)
    lowered_suffix = suffix.casefold()
    if not any(marker in lowered_suffix for marker in ("$j.", "$json.", "$summary", "$roadmap", "convertto-json", "select-object")):
        return command
    unsafe_suffix_markers = (
        "mylittleharness",
        "git ",
        "set-content",
        "add-content",
        "out-file",
        "tee-object",
        "remove-item",
        "move-item",
        "copy-item",
        "new-item",
        "apply_patch",
        ">",
    )
    if any(marker in lowered_suffix for marker in unsafe_suffix_markers):
        return command
    return head.strip()


def _is_read_only_mlh_report_pipeline_segment(tokens: list[str]) -> bool:
    command_name = _clean_token(tokens[0]).casefold()
    if command_name not in READ_ONLY_MLH_REPORT_PIPELINE_COMMANDS:
        return False
    if command_name == "convertfrom-json":
        return len(tokens) == 1
    if command_name in {"py", "python", "python.exe"}:
        return _is_read_only_python_filter_pipeline_segment(tokens)
    value_options = READ_ONLY_MLH_REPORT_PIPELINE_VALUE_OPTIONS.get(command_name, set())
    flag_options = READ_ONLY_MLH_REPORT_PIPELINE_FLAG_OPTIONS.get(command_name, set())
    index = 1
    while index < len(tokens):
        token = _clean_token(tokens[index]).casefold()
        if not token:
            index += 1
            continue
        if token in value_options:
            if index + 1 >= len(tokens):
                return False
            value = _clean_token(tokens[index + 1])
            if not value or value.startswith("-"):
                return False
            index += 2
            continue
        if token in flag_options:
            index += 1
            continue
        if token.startswith("-"):
            return False
        index += 1
    return True


def _is_read_only_python_filter_pipeline_segment(tokens: list[str]) -> bool:
    if len(tokens) != 3 or _clean_token(tokens[1]) != "-c":
        return False
    lowered = str(tokens[2] or "").casefold()
    forbidden = (
        "add-content",
        "apply_patch",
        "check_call",
        "check_output",
        "eval(",
        "exec(",
        "git ",
        "mylittleharness",
        "open(",
        "os.",
        "pathlib",
        "popen",
        "remove-item",
        "set-content",
        "shutil",
        "subprocess",
        "sys.path",
        "tee-object",
        "unlink(",
        "write(",
        "write_text",
    )
    return not any(marker in lowered for marker in forbidden)


def _mlh_subcommand_argument_tokens(command: str, subcommand: str) -> list[str]:
    tokens = _shell_tokens(_mlh_policy_command(command))
    for index, token in enumerate(tokens):
        if not _is_mlh_executable_token(token) and not (
            _is_python_executable_token(token)
            and index + 2 < len(tokens)
            and _clean_token(tokens[index + 1]) == "-m"
            and _clean_token(tokens[index + 2]) == "my" + "littleharness"
        ):
            continue
        start = index + (3 if _is_python_executable_token(token) else 1)
        cursor = start
        while cursor < len(tokens):
            clean = _clean_token(tokens[cursor])
            if clean in {"--root", "--config", "--config-path"}:
                cursor += 2
                continue
            if clean.startswith(("--root=", "--config=", "--config-path=")):
                cursor += 1
                continue
            if clean.startswith("-"):
                cursor += 1
                continue
            if clean == subcommand:
                return [_clean_token(item) for item in tokens[cursor + 1 :] if _clean_token(item)]
            break
    return []


def _mlh_report_args_are_read_only(args: list[str], allowed_options: set[str]) -> bool:
    index = 0
    while index < len(args):
        token = args[index]
        option_name = token.split("=", 1)[0]
        if option_name not in allowed_options:
            return False
        if option_name in {"--root", "--config", "--config-path"} and "=" not in token:
            index += 2
            continue
        index += 1
    return True


def _is_read_only_product_source_smoke_command(inventory: Inventory, command: str) -> bool:
    if _configured_product_source_root_path(inventory) is None:
        return False
    if _looks_like_write_command(command):
        return False
    lowered = command.casefold()
    if not _command_has_python_executable(command):
        return False
    if any(marker in lowered for marker in READ_ONLY_PRODUCT_SOURCE_SMOKE_FORBIDDEN_MARKERS):
        return False
    if _is_python_mlh_module_inspect_command(command):
        return True
    return any(_python_inline_payload_is_read_only_mlh_inspect(payload) for payload in _python_inline_payloads(command))


def _is_read_only_product_source_test_command(
    inventory: Inventory,
    data: dict[str, object],
    command: str,
    paths: list[str],
) -> bool:
    product_root = _configured_product_source_root_path(inventory)
    if product_root is None:
        return False
    if _looks_like_write_command(command):
        return False
    if not _command_has_python_executable(command):
        return False
    tokens = [_clean_shell_command_token(token) for token in _shell_tokens(command)]
    if "-m" not in tokens or "unittest" not in tokens:
        return False
    lowered = command.casefold()
    if any(marker in lowered for marker in READ_ONLY_PRODUCT_SOURCE_SMOKE_FORBIDDEN_MARKERS):
        return False
    workdir = _hook_command_workdir_path(inventory, data)
    if workdir is not None:
        try:
            workdir.resolve().relative_to(product_root.resolve())
            return True
        except (OSError, RuntimeError, ValueError):
            pass
    if any(_is_under_configured_product_root(inventory, path) for path in paths):
        return True
    return _pythonpath_mentions_product_source_root(product_root, command)


def _pythonpath_mentions_product_source_root(product_root: Path, command: str) -> bool:
    try:
        product_src = (product_root / "src").resolve()
        product_root_resolved = product_root.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    normalized = command.replace("\\\\", "\\").replace("/", "\\").casefold()
    product_src_text = str(product_src).replace("/", "\\").casefold()
    product_root_text = str(product_root_resolved).replace("/", "\\").casefold()
    return product_src_text in normalized or product_root_text in normalized


def _is_read_only_product_source_inspection_command(inventory: Inventory, data: dict[str, object], command: str) -> bool:
    product_root = _configured_product_source_root_path(inventory)
    if product_root is None:
        return False
    if _looks_like_write_command(command):
        return False
    policy_command = _mlh_policy_command(command)
    if _has_unresolved_mlh_splat_invocation(command):
        return False
    subcommand = _mlh_cli_subcommand(policy_command.casefold())
    if subcommand not in READ_ONLY_PRODUCT_SOURCE_INSPECTION_COMMANDS:
        return False
    tokens = _mlh_command_token_set(policy_command)
    if tokens.intersection(READ_ONLY_PRODUCT_SOURCE_INSPECTION_FORBIDDEN_TOKENS):
        return False
    selected_root = _mlh_root_option_resolved_path(inventory, policy_command)
    if selected_root is None:
        selected_root = _hook_command_workdir_path(inventory, data)
    return selected_root is not None and _same_resolved_path(selected_root, product_root)


def _is_product_source_root_mlh_mutation_command(inventory: Inventory, data: dict[str, object], command: str) -> bool:
    product_root = _configured_product_source_root_path(inventory)
    if product_root is None:
        return False
    policy_command = _mlh_policy_command(command)
    if _has_unresolved_mlh_splat_invocation(command):
        return False
    if not _mlh_cli_subcommand(policy_command.casefold()):
        return False
    selected_root = _mlh_root_option_resolved_path(inventory, policy_command)
    if selected_root is None:
        selected_root = _hook_command_workdir_path(inventory, data)
    if selected_root is None or not _same_resolved_path(selected_root, product_root):
        return False
    return bool(_mlh_command_token_set(policy_command).intersection(PRODUCT_SOURCE_ROOT_MUTATING_MLH_TOKENS))


def _mlh_root_option_resolved_path(inventory: Inventory, command: str) -> Path | None:
    tokens = _shell_tokens(_mlh_policy_command(command))
    for index, token in enumerate(tokens):
        clean = _clean_token(token)
        if clean == "--root" and index + 1 < len(tokens):
            return _resolve_path_token_from_base(tokens[index + 1], inventory.root)
        if clean.startswith("--root="):
            raw = str(token).split("=", 1)[1]
            return _resolve_path_token_from_base(raw, inventory.root)
    return None


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except (OSError, RuntimeError, ValueError):
        return False


def _command_has_python_executable(command: str) -> bool:
    return any(_is_python_executable_token(token) for token in _shell_tokens(command))


def _is_python_mlh_module_inspect_command(command: str) -> bool:
    subcommand = _mlh_cli_subcommand(command.casefold())
    if subcommand not in READ_ONLY_PRODUCT_SOURCE_SMOKE_COMMANDS:
        return False
    return "--inspect" in _mlh_command_token_set(command)


def _python_inline_payloads(command: str) -> list[str]:
    payloads: list[str] = []
    tokens = _shell_tokens(command)
    for index, token in enumerate(tokens):
        if not _is_python_executable_token(token):
            continue
        cursor = index + 1
        while cursor < len(tokens):
            clean = _clean_token(tokens[cursor])
            if clean in {"-c", "-command"}:
                if cursor + 1 < len(tokens):
                    payloads.append(_strip_shell_payload_token(tokens[cursor + 1]))
                break
            if clean == "-m":
                break
            cursor += 1
    return payloads


def _python_inline_payload_is_read_only_mlh_inspect(payload: str) -> bool:
    lowered = str(payload or "").casefold()
    if any(marker in lowered for marker in READ_ONLY_PRODUCT_SOURCE_SMOKE_FORBIDDEN_MARKERS):
        return False
    if "my" + "littleharness" not in lowered or "main(" not in lowered:
        return False
    if "--inspect" not in lowered:
        return False
    return any(f"'{name}'" in lowered or f'"{name}"' in lowered for name in READ_ONLY_PRODUCT_SOURCE_SMOKE_COMMANDS)


def _is_post_closeout_lifecycle_route_stage_command(inventory: Inventory, command: str, paths: list[str]) -> bool:
    if _has_active_plan(inventory):
        return False
    if _git_subcommand(command) not in {"add", "stage"}:
        return False
    if not paths:
        return False
    pathspecs = [] if _has_shell_command_separator(command) else _git_stage_pathspecs(command)
    normalized = _normalized_route_produced_lifecycle_paths(inventory, pathspecs or paths)
    has_top_level_verification = any(
        _is_top_level_verification_checkpoint_path(_hook_route_rel_path(inventory, path) or path)
        for path in (pathspecs or paths)
    )
    if not _has_shell_command_separator(command) and _coherent_post_closeout_roadmap_promotion_finalization_paths(
        inventory, pathspecs
    ):
        return True
    if not _has_shell_command_separator(command) and _coherent_post_closeout_lifecycle_route_checkpoint_paths(
        inventory, pathspecs, allow_without_roadmap=True
    ):
        return True
    if has_top_level_verification:
        return False
    if all(_is_tracked_existing_lifecycle_route_file(inventory, path) for path in paths):
        return True
    if any(_is_meta_feedback_incubation_route_path(path) for path in normalized):
        return bool(
            _coherent_roadmap_promotion_checkpoint_paths(inventory, pathspecs)
            or _coherent_meta_feedback_checkpoint_paths(inventory, normalized)
        )
    if all(_is_existing_lifecycle_route_file(inventory, path) for path in paths):
        return True
    if _has_shell_command_separator(command):
        return False
    return bool(
        _coherent_post_closeout_roadmap_promotion_finalization_paths(inventory, pathspecs) or
        _coherent_post_closeout_lifecycle_route_checkpoint_paths(
            inventory,
            pathspecs,
            allow_without_roadmap=True,
        )
    )


def _is_post_closeout_lifecycle_route_stage_path(inventory: Inventory, path: str) -> bool:
    return (
        _is_existing_lifecycle_route_file(inventory, path)
        or _is_post_closeout_active_plan_tombstone_path(inventory, path)
        or _is_post_closeout_source_incubation_tombstone_path(inventory, path)
    )


def _is_route_produced_lifecycle_route_stage_command(inventory: Inventory, command: str) -> bool:
    if _has_shell_command_separator(command):
        return _is_route_produced_lifecycle_route_stage_review_bundle(inventory, command)
    subcommand, _tokens, _index = _git_command_context(command)
    if subcommand not in {"add", "stage"}:
        return False
    pathspecs = _git_stage_pathspecs(command)
    if _coherent_roadmap_promotion_checkpoint_paths(inventory, pathspecs):
        return True
    if _coherent_active_plan_open_checkpoint_paths(inventory, pathspecs):
        return True
    if _coherent_active_plan_phase_transition_checkpoint_paths(inventory, pathspecs):
        return True
    if not _active_plan_ready_for_route_produced_lifecycle_git(inventory):
        return False
    return bool(_coherent_route_produced_lifecycle_stage_paths(inventory, pathspecs))


def _is_route_produced_lifecycle_route_stage_review_bundle(inventory: Inventory, command: str) -> bool:
    segments = _shell_command_segments(command)
    if len(segments) < 2 or _git_subcommand(segments[0]) not in {"add", "stage"}:
        return False
    try:
        current_root = inventory.root.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    for segment in segments:
        segment_root = _git_effective_workdir_path(inventory, {}, segment)
        if segment_root is None:
            return False
        try:
            if segment_root.resolve() != current_root:
                return False
        except (OSError, RuntimeError, ValueError):
            return False
    pathspecs = _git_stage_pathspecs(segments[0])
    if not pathspecs:
        return False
    coherent = bool(_coherent_roadmap_promotion_checkpoint_paths(inventory, pathspecs))
    if not coherent:
        coherent = bool(_coherent_active_plan_open_checkpoint_paths(inventory, pathspecs))
    if not coherent:
        coherent = bool(_coherent_active_plan_phase_transition_checkpoint_paths(inventory, pathspecs))
    if not coherent and _active_plan_ready_for_route_produced_lifecycle_git(inventory):
        coherent = bool(_coherent_route_produced_lifecycle_stage_paths(inventory, pathspecs))
    if not coherent:
        return False
    return all(_is_reviewed_local_vcs_checkpoint_review_segment(segment) for segment in segments[1:])


def _is_product_source_vcs_stage_command(inventory: Inventory, data: dict[str, object], command: str) -> bool:
    if len(_shell_command_segments(command)) > 1:
        return _is_product_source_vcs_stage_review_bundle(inventory, data, command)
    return _is_product_source_vcs_stage_segment(inventory, data, command)


def _is_product_source_vcs_stage_segment(inventory: Inventory, data: dict[str, object], command: str) -> bool:
    base_root, product_root = _product_source_vcs_roots(inventory, data, command)
    if base_root is None or product_root is None:
        return False
    subcommand, _tokens, _index = _git_command_context(command)
    if subcommand not in {"add", "stage"}:
        return False
    pathspecs = _git_stage_pathspecs(command)
    if not pathspecs:
        return False
    if _has_active_plan(inventory):
        return all(
            _is_exact_active_plan_product_source_stage_file(
                inventory,
                pathspec,
                base_root=base_root,
                boundary_root=product_root,
            )
            for pathspec in pathspecs
        )
    return all(
        _is_exact_post_closeout_stage_file(
            inventory,
            pathspec,
            base_root=base_root,
            boundary_root=product_root,
        )
        for pathspec in pathspecs
    )


def _is_product_source_vcs_stage_review_bundle(inventory: Inventory, data: dict[str, object], command: str) -> bool:
    segments = _shell_command_segments(command)
    if len(segments) < 2 or not _is_product_source_vcs_stage_segment(inventory, data, segments[0]):
        return False
    base_root, product_root = _product_source_vcs_roots(inventory, data, segments[0])
    if base_root is None or product_root is None:
        return False
    for segment in segments[1:]:
        if not _is_reviewed_local_vcs_checkpoint_review_segment(segment):
            return False
        segment_base_root, segment_product_root = _product_source_vcs_roots(inventory, data, segment)
        if segment_base_root is None or segment_product_root is None:
            return False
        try:
            if (
                segment_base_root.resolve() != base_root.resolve()
                or segment_product_root.resolve() != product_root.resolve()
            ):
                return False
        except (OSError, RuntimeError, ValueError):
            return False
    return True


def _is_exact_active_plan_product_source_stage_file(
    inventory: Inventory,
    pathspec: str,
    *,
    base_root: Path,
    boundary_root: Path,
) -> bool:
    if not _is_exact_post_closeout_stage_file(
        inventory,
        pathspec,
        base_root=base_root,
        boundary_root=boundary_root,
    ):
        return False
    try:
        candidate = Path(_clean_hook_path_token(pathspec)).expanduser()
        if not candidate.is_absolute():
            candidate = base_root / candidate
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return _is_active_plan_product_artifact(inventory, str(resolved))


def _is_product_source_vcs_commit_command(inventory: Inventory, data: dict[str, object], command: str) -> bool:
    base_root, product_root = _product_source_vcs_roots(inventory, data, command)
    if base_root is None or product_root is None:
        return False
    if not _is_narrow_local_vcs_commit_command(command):
        return False
    if _has_active_plan(inventory):
        return _active_plan_product_source_staged_paths_are_target_artifacts(inventory, product_root)
    return True


def _active_plan_product_source_staged_paths_are_target_artifacts(
    inventory: Inventory,
    product_root: Path,
) -> bool:
    staged_paths = _git_staged_paths_for_root(product_root)
    if not staged_paths:
        return False
    for staged_path in staged_paths:
        if any(char in staged_path for char in "*?[]") or staged_path.startswith(":"):
            return False
        try:
            candidate = (product_root / staged_path).resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        if not _is_active_plan_product_artifact(inventory, str(candidate)):
            return False
    return True


def _is_product_source_vcs_push_command(inventory: Inventory, data: dict[str, object], command: str) -> bool:
    if _active_plan_blocks_product_source_vcs_push(inventory):
        return False
    return _is_product_source_vcs_push_candidate(inventory, data, command)


def _is_product_source_fixture_vcs_push_command(inventory: Inventory, data: dict[str, object], command: str) -> bool:
    if _active_plan_blocks_product_source_vcs_push(inventory):
        return False
    return _is_product_source_fixture_vcs_push_candidate(inventory, data, command)


def _is_product_source_vcs_push_candidate(inventory: Inventory, data: dict[str, object], command: str) -> bool:
    if _has_shell_command_separator(command):
        return False
    base_root, product_root = _product_source_vcs_roots(inventory, data, command)
    if base_root is None or product_root is None:
        return False
    subcommand, tokens, subcommand_index = _git_command_context(command)
    if subcommand != "push" or subcommand_index < 0:
        return False
    operands = _product_source_push_operands(tokens[subcommand_index + 1 :])
    if operands is None:
        return False
    if _is_exact_release_publication_refspecs(operands):
        return False
    if any(
        clean.startswith("+")
        or (":" in clean and not _ordinary_product_source_push_refspec_targets_main(clean))
        or _looks_like_product_source_tag_push_ref(clean)
        or any(char in clean for char in "*?[]")
        for clean in operands
    ):
        return False
    return _is_ordinary_product_source_main_push_operands(operands)


def _is_product_source_fixture_vcs_push_candidate(
    inventory: Inventory, data: dict[str, object], command: str
) -> bool:
    if not _is_product_source_fixture_vcs_push_context(inventory, data, command):
        return False
    subcommand, tokens, subcommand_index = _git_command_context(command)
    if subcommand != "push" or subcommand_index < 0:
        return False
    operands = _product_source_push_operands(tokens[subcommand_index + 1 :])
    if operands is None:
        return False
    if _is_exact_release_publication_refspecs(operands):
        return False
    if any(
        clean.startswith("+")
        or (":" in clean and not _ordinary_product_source_push_refspec_targets_main(clean))
        or _looks_like_product_source_tag_push_ref(clean)
        or any(char in clean for char in "*?[]")
        for clean in operands
    ):
        return False
    return _is_ordinary_product_source_main_push_operands(operands)


def _is_product_source_publication_push_hidden_workdir(
    inventory: Inventory, data: dict[str, object], command: str
) -> bool:
    if _active_plan_blocks_product_source_vcs_push(inventory) or _has_shell_command_separator(command):
        return False
    product_root = _configured_product_source_root_path(inventory)
    if product_root is None:
        return False
    workdir = _git_effective_workdir_path(inventory, data, command)
    if workdir is not None:
        try:
            workdir.relative_to(product_root)
            return False
        except (OSError, RuntimeError, ValueError):
            pass
    subcommand, tokens, subcommand_index = _git_command_context(command)
    if subcommand != "push" or subcommand_index < 0:
        return False
    operands = _product_source_push_operands(tokens[subcommand_index + 1 :])
    if operands is None:
        return False
    return _is_ordinary_product_source_main_push_operands(operands)


def _is_product_source_fixture_vcs_push_context(
    inventory: Inventory, data: dict[str, object], command: str
) -> bool:
    if inventory.root_kind != PRODUCT_SOURCE_FIXTURE or _has_shell_command_separator(command):
        return False
    workdir = _git_effective_workdir_path(inventory, data, command)
    if workdir is None:
        return False
    try:
        workdir.relative_to(inventory.root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    subcommand, _tokens, subcommand_index = _git_command_context(command)
    return subcommand == "push" and subcommand_index >= 0


def _is_product_source_release_publication_push_command(
    inventory: Inventory, data: dict[str, object], command: str
) -> bool:
    if _active_plan_blocks_product_source_vcs_push(inventory) or _has_shell_command_separator(command):
        return False
    base_root, product_root = _product_source_vcs_roots(inventory, data, command)
    if base_root is None or product_root is None:
        return False
    subcommand, tokens, subcommand_index = _git_command_context(command)
    if subcommand != "push" or subcommand_index < 0:
        return False
    operands = _product_source_push_operands(tokens[subcommand_index + 1 :], allow_dry_run=True)
    if operands is None or not _is_exact_release_publication_refspecs(operands):
        return False
    tag_name = _release_publication_tag_name(operands[2])
    if not tag_name:
        return False
    return (
        _product_source_release_publication_intent_present(inventory, command, tag_name, product_root)
        and _product_source_release_publication_ready(product_root, tag_name, operands[1])
    )


def _product_source_push_operands(tokens: list[str], *, allow_dry_run: bool = False) -> list[str] | None:
    operands: list[str] = []
    for token in tokens:
        clean = _clean_token(token)
        if not clean:
            continue
        if _is_shell_command_separator(token, clean):
            return None
        if clean == "--":
            continue
        if allow_dry_run and clean == "--dry-run":
            continue
        if clean in {"-u", "--set-upstream"} and not allow_dry_run:
            continue
        if clean.startswith("--force") or clean in {"-f", "--mirror", "--delete", "--all", "--tags", "--prune"}:
            return None
        if clean.startswith("-") and not clean.startswith("--") and "f" in clean[1:]:
            return None
        if clean.startswith("-"):
            return None
        if clean.startswith("+") or any(char in clean for char in "*?[]"):
            return None
        operands.append(clean)
    return operands


def _is_exact_release_publication_refspecs(operands: list[str]) -> bool:
    return (
        len(operands) == 3
        and operands[0] == "origin"
        and _release_publication_branch_targets_main(operands[1])
        and bool(_release_publication_tag_name(operands[2]))
    )


def _is_ordinary_product_source_main_push_operands(operands: list[str]) -> bool:
    if not operands:
        return True
    if len(operands) == 1:
        return operands[0] in {"origin", "main", "refs/heads/main"} or _ordinary_product_source_push_refspec_targets_main(
            operands[0]
        )
    if len(operands) != 2 or operands[0] != "origin":
        return False
    branch = operands[1]
    return branch in {"main", "refs/heads/main"} or _ordinary_product_source_push_refspec_targets_main(branch)


def _ordinary_product_source_push_refspec_targets_main(refspec: str) -> bool:
    source, target = _split_exact_refspec(refspec)
    return source in {"HEAD", "head", "main", "refs/heads/main"} and target == "refs/heads/main"


def _release_publication_branch_targets_main(refspec: str) -> bool:
    source, target = _split_exact_refspec(refspec)
    if source not in {"main", "refs/heads/main"} and not source.startswith("refs/tags/"):
        return False
    return target in {"", "refs/heads/main"}


def _release_publication_tag_name(refspec: str) -> str:
    source, target = _split_exact_refspec(refspec)
    if not source.startswith("refs/tags/"):
        return ""
    if target and target != source:
        return ""
    tag_name = source.removeprefix("refs/tags/")
    if not re.match(r"^v\d+\.\d+\.\d+(?:-rc\d+)?$", tag_name):
        return ""
    return tag_name


def _split_exact_refspec(refspec: str) -> tuple[str, str]:
    clean = _normalize_hook_path(_clean_token(refspec))
    if clean.startswith(":") or clean.endswith(":") or clean.count(":") > 1:
        return "", ""
    if ":" not in clean:
        return clean, ""
    source, target = clean.split(":", 1)
    return source, target


def _product_source_release_publication_intent_present(
    inventory: Inventory, command: str, tag_name: str, product_root: Path | None
) -> bool:
    lowered_command = str(command or "").casefold()
    if "push" not in lowered_command or tag_name.casefold() not in lowered_command:
        return False
    state = inventory.state
    if not state or not state.exists or not state.path:
        return _product_source_release_docs_name_tag(product_root, tag_name)
    try:
        state_text = state.path.read_text(encoding="utf-8").casefold()
    except (OSError, UnicodeDecodeError):
        state_text = ""
    has_release_context = "release" in state_text or "publication" in state_text
    has_owner_context = (
        "owner approval" in state_text
        or "owner-approved" in state_text
        or "explicit owner intent" in state_text
        or "release-publication" in state_text
    )
    return (has_release_context and has_owner_context) or _product_source_release_docs_name_tag(
        product_root, tag_name
    )


def _product_source_release_docs_name_tag(product_root: Path | None, tag_name: str) -> bool:
    if product_root is None or not tag_name:
        return False
    tag_variants = {tag_name.casefold(), tag_name.removeprefix("v").casefold()}
    for filename in ("RELEASE_NOTES.md", "CHANGELOG.md"):
        path = product_root / filename
        try:
            text = path.read_text(encoding="utf-8").casefold()
        except (OSError, UnicodeDecodeError):
            return False
        if not any(variant in text for variant in tag_variants):
            return False
    return True


def _product_source_release_publication_ready(product_root: Path, tag_name: str, branch_refspec: str) -> bool:
    if not _git_worktree_clean_for_root(product_root) or not _git_remote_exists_for_root(product_root, "origin"):
        return False
    tag_commit = _git_ref_commit_for_root(product_root, f"refs/tags/{tag_name}^{{commit}}")
    if not tag_commit:
        return False
    branch_source, _branch_target = _split_exact_refspec(branch_refspec)
    if branch_source in {"main", "refs/heads/main"}:
        branch_commit = _git_ref_commit_for_root(product_root, "refs/heads/main")
    elif branch_source == f"refs/tags/{tag_name}":
        branch_commit = tag_commit
    else:
        return False
    return bool(branch_commit) and branch_commit == tag_commit


def _git_worktree_clean_for_root(root: Path) -> bool:
    result = _run_git_for_root(root, "status", "--porcelain=v1")
    return result is not None and result.returncode == 0 and not result.stdout.strip()


def _git_remote_exists_for_root(root: Path, remote: str) -> bool:
    result = _run_git_for_root(root, "remote", "get-url", remote)
    return result is not None and result.returncode == 0 and bool(result.stdout.strip())


def _git_ref_commit_for_root(root: Path, ref: str) -> str:
    result = _run_git_for_root(root, "rev-parse", "--verify", ref)
    if result is None or result.returncode != 0:
        return ""
    return result.stdout.strip()


def _run_git_for_root(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _is_product_source_vcs_finalization_sequence(inventory: Inventory, data: dict[str, object], command: str) -> bool:
    if _has_active_plan(inventory):
        return False
    segments = _simple_shell_sequence_segments(command)
    if len(segments) not in {2, 3}:
        return False
    start = 0
    if len(segments) == 3:
        if not _is_product_source_vcs_stage_command(inventory, data, segments[0]):
            return False
        start = 1
    return (
        _is_product_source_cached_diff_check_command(inventory, data, segments[start])
        and _is_product_source_vcs_commit_command(inventory, data, segments[start + 1])
    )


def _simple_shell_sequence_segments(command: str) -> list[str]:
    if "\n" in command or "&&" in command or "||" in command or "|" in command:
        return []
    segments = [segment.strip() for segment in str(command or "").split(";")]
    if any(not segment for segment in segments):
        return []
    return segments


def _is_product_source_cached_diff_check_command(
    inventory: Inventory, data: dict[str, object], command: str
) -> bool:
    base_root, product_root = _product_source_vcs_roots(inventory, data, command)
    if base_root is None or product_root is None:
        return False
    subcommand, tokens, subcommand_index = _git_command_context(command)
    if subcommand != "diff" or subcommand_index < 0:
        return False
    args = [_clean_token(token) for token in tokens[subcommand_index + 1 :] if _clean_token(token)]
    if not args:
        return False
    return set(args) == {"--cached", "--check"}


def _looks_like_product_source_tag_push_ref(ref: str) -> bool:
    clean = _normalize_hook_path(ref).casefold()
    if clean.startswith(("refs/tags/", "tags/")):
        return True
    return bool(re.match(r"^v?\d+\.\d+(?:\.\d+)?(?:[-+][a-z0-9._-]+)?$", clean))


def _product_source_vcs_roots(
    inventory: Inventory, data: dict[str, object], command: str
) -> tuple[Path | None, Path | None]:
    product_root = _configured_product_source_root_path(inventory)
    if product_root is None:
        return None, None
    workdir = _git_effective_workdir_path(inventory, data, command)
    if workdir is None:
        return None, None
    try:
        workdir.relative_to(product_root)
    except (OSError, RuntimeError, ValueError):
        return None, None
    try:
        workdir.relative_to(inventory.root.resolve())
        return None, None
    except ValueError:
        pass
    except (OSError, RuntimeError):
        return None, None
    try:
        product_root.relative_to(inventory.root.resolve())
        return None, None
    except ValueError:
        return workdir, product_root
    except (OSError, RuntimeError):
        return None, None


def _configured_product_source_root_path(inventory: Inventory) -> Path | None:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    product_root = str(state.get("product_source_root") or "").strip()
    if not product_root:
        return None
    try:
        candidate = Path(product_root).expanduser()
        if not candidate.is_absolute():
            candidate = inventory.root / candidate
        return candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _hook_command_workdir_path(inventory: Inventory, data: dict[str, object]) -> Path | None:
    raw_value = str(_hook_workdir_value(data) or "").strip()
    if not raw_value:
        return None
    value = _path_argument_value(raw_value) or raw_value
    try:
        candidate = Path(_clean_hook_path_token(value)).expanduser()
        if not candidate.is_absolute():
            candidate = inventory.root / candidate
        return candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _hook_command_workdir_outside_root(inventory: Inventory, data: dict[str, object]) -> bool:
    workdir = _hook_command_workdir_path(inventory, data)
    if workdir is None:
        return False
    try:
        workdir.relative_to(inventory.root.resolve())
        return False
    except ValueError:
        return True
    except (OSError, RuntimeError):
        return False


def _is_post_closeout_local_vcs_stage_command(inventory: Inventory, command: str) -> bool:
    if _has_active_plan(inventory) or _has_shell_command_separator(command):
        return False
    subcommand, _tokens, _index = _git_command_context(command)
    if subcommand not in {"add", "stage"}:
        return False
    pathspecs = _git_stage_pathspecs(command)
    if not pathspecs:
        return False
    if _coherent_post_closeout_roadmap_promotion_finalization_paths(inventory, pathspecs):
        return True
    normalized = {_normalize_hook_path(_hook_route_rel_path(inventory, pathspec) or pathspec).casefold() for pathspec in pathspecs}
    if any(_is_top_level_verification_checkpoint_path(path) for path in normalized):
        if _coherent_post_closeout_lifecycle_vcs_stage_paths(inventory, pathspecs):
            return True
        return all(_is_reviewed_top_level_verification_checkpoint_file(inventory, path) for path in normalized)
    if any(_is_meta_feedback_incubation_route_path(path) for path in normalized):
        return bool(
            _coherent_archived_source_incubation_tombstone_stage_paths(inventory, pathspecs)
            or _coherent_meta_feedback_checkpoint_paths(inventory, normalized)
        )
    return all(_is_exact_post_closeout_stage_file(inventory, pathspec) for pathspec in pathspecs)


def _is_post_closeout_local_vcs_commit_command(inventory: Inventory, command: str) -> bool:
    if _has_active_plan(inventory):
        return False
    if not _is_narrow_local_vcs_commit_command(command):
        return False
    staged_paths = _git_staged_paths(inventory)
    staged = {_normalize_hook_path(path).casefold() for path in staged_paths}
    if not staged:
        return True
    if any(_is_checkpoint_sensitive_staged_path(inventory, path) for path in staged):
        return bool(
            _coherent_reviewed_local_vcs_checkpoint_paths(
                inventory,
                staged_paths,
                prefer_staged_content=True,
            )
            or _coherent_post_closeout_mixed_vcs_finalization_paths(
                inventory,
                staged_paths,
                prefer_staged_state=True,
            )
            or _coherent_post_closeout_standalone_verification_checkpoint_commit_paths(
                inventory,
                staged_paths,
            )
        )
    return True


def _coherent_post_closeout_standalone_verification_checkpoint_commit_paths(
    inventory: Inventory, paths: tuple[str, ...]
) -> set[str]:
    if not paths:
        return set()
    normalized = tuple(
        _normalize_hook_path(_hook_route_rel_path(inventory, path) or path).casefold()
        for path in paths
    )
    if not all(_is_top_level_verification_checkpoint_path(path) for path in normalized):
        return set()
    if not all(
        _is_reviewed_staged_top_level_verification_checkpoint_file(inventory, path)
        for path in normalized
    ):
        return set()
    return set(normalized)


def _post_closeout_lifecycle_vcs_finalization_paths(inventory: Inventory, command: str) -> set[str]:
    if not _is_post_closeout_local_vcs_commit_command(inventory, command):
        return set()
    return _coherent_post_closeout_mixed_vcs_finalization_paths(
        inventory,
        _git_staged_paths(inventory),
        prefer_staged_state=True,
    )


def _is_checkpoint_sensitive_staged_path(inventory: Inventory, path: str) -> bool:
    rel = _normalize_hook_path(_hook_route_rel_path(inventory, path) or path).casefold()
    if not rel:
        return False
    return (
        rel == "project/project-state.md"
        or rel == "project/roadmap.md"
        or rel == ACTIVE_PLAN_ROUTE_PATH
        or rel.startswith("project/archive/plans/")
        or _is_agent_run_evidence_route_path(rel)
        or _is_worker_run_receipt_route_path(rel)
        or _is_retention_receipt_route_path(rel)
        or _is_checkpoint_decision_route_path(rel)
        or _is_verification_checkpoint_route_path(rel)
        or _is_top_level_verification_checkpoint_path(rel)
        or _is_meta_feedback_incubation_route_path(rel)
        or _is_existing_lifecycle_route_file(inventory, rel)
    )


def _coherent_post_closeout_lifecycle_vcs_stage_paths(
    inventory: Inventory, paths: list[str] | tuple[str, ...]
) -> set[str]:
    direct = _coherent_post_closeout_lifecycle_vcs_finalization_paths(inventory, paths)
    if direct:
        return direct
    staged_paths = _git_staged_paths(inventory)
    if not staged_paths:
        return set()
    normalized_current = _normalized_route_produced_lifecycle_paths(inventory, paths)
    if not normalized_current:
        return set()
    combined = _coherent_post_closeout_lifecycle_vcs_finalization_paths(inventory, tuple(staged_paths) + tuple(paths))
    return combined if combined and normalized_current <= combined else set()


def _post_closeout_lifecycle_state_authority(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
    *,
    prefer_staged_state: bool = False,
) -> tuple[dict[str, object], str]:
    state_rel = "project/" + "project-state.md"
    normalized = {_normalize_hook_path(path).casefold() for path in paths}
    if prefer_staged_state and state_rel in normalized:
        staged_text = _git_staged_file_text_for_root(inventory.root, state_rel)
        if staged_text is not None:
            try:
                frontmatter = parse_frontmatter(staged_text)
            except ValueError:
                return {}, ""
            return frontmatter.data, staged_text
    state = inventory.state
    if not state or not state.exists:
        return {}, ""
    return state.frontmatter.data, state.content


def _coherent_archived_source_incubation_tombstone_stage_paths(
    inventory: Inventory, paths: list[str] | tuple[str, ...]
) -> set[str]:
    tombstones: set[str] = set()
    explicit_archive_references: set[str] = set()
    for path in paths:
        rel = _hook_route_rel_path(inventory, path)
        clean = _normalize_hook_path(rel).casefold() if rel else ""
        if not clean:
            return set()
        if _is_post_closeout_source_incubation_tombstone_path(inventory, clean):
            tombstones.add(clean)
            continue
        if _is_reviewed_memory_hygiene_archive_reference_file(inventory, clean):
            explicit_archive_references.add(clean)
            continue
        return set()
    if not tombstones:
        return set()
    archive_references = _source_incubation_archive_references_for_tombstones(inventory, tombstones)
    archive_references.update(explicit_archive_references)
    if not archive_references:
        return set()
    if not all(
        _has_archive_reference_for_incubation_source(inventory, source_path, archive_references)
        for source_path in tombstones
    ):
        return set()
    if any(
        not any(
            _has_archive_reference_for_incubation_source(inventory, source_path, {archive_reference})
            for source_path in tombstones
        )
        for archive_reference in explicit_archive_references
    ):
        return set()
    return tombstones | explicit_archive_references


def _source_incubation_archive_references_for_tombstones(inventory: Inventory, source_paths: set[str]) -> set[str]:
    references: set[str] = set()
    for path in _git_staged_paths(inventory):
        clean = _normalize_hook_path(path).casefold()
        if _is_reviewed_memory_hygiene_archive_reference_file(inventory, clean):
            references.add(clean)
    archive_dir = inventory.root / "project" / "archive" / "reference" / "incubation"
    for candidate in archive_dir.glob("*.md"):
        try:
            clean = _normalize_hook_path(candidate.relative_to(inventory.root).as_posix()).casefold()
        except ValueError:
            continue
        if _is_reviewed_memory_hygiene_archive_reference_file(inventory, clean):
            references.add(clean)
    return {
        reference
        for reference in references
        if any(_has_archive_reference_for_incubation_source(inventory, source_path, {reference}) for source_path in source_paths)
    }


def _reviewed_local_vcs_checkpoint(inventory: Inventory, data: dict[str, object], command: str) -> ReviewedLocalVcsCheckpoint:
    if len(_shell_command_segments(command)) > 1:
        bundled = _reviewed_local_vcs_checkpoint_review_bundle(inventory, data, command)
        return bundled if bundled.paths or bundled.blocked_reason else ReviewedLocalVcsCheckpoint()
    subcommand = _git_subcommand(command)
    if subcommand not in {"add", "stage", "commit"}:
        return ReviewedLocalVcsCheckpoint()
    target_inventory, root_reason = _neighbor_mlh_root_inventory(inventory, data, command)
    if target_inventory is None:
        return ReviewedLocalVcsCheckpoint(blocked_reason=root_reason) if root_reason else ReviewedLocalVcsCheckpoint()
    visible_workdir = _checkpoint_uses_visible_workdir(inventory, data, target_inventory.root)
    if subcommand in {"add", "stage"}:
        pathspecs = _git_stage_pathspecs(command)
        if not pathspecs:
            return ReviewedLocalVcsCheckpoint(
                root=target_inventory.root,
                blocked_reason=(
                    "no exact pathspecs were supplied; "
                    + _reviewed_local_vcs_checkpoint_rejection_reason(target_inventory, (), "pathspecs")
                ),
            )
        paths = _coherent_reviewed_local_vcs_checkpoint_paths(target_inventory, pathspecs)
        if not paths:
            paths = _coherent_delegated_neighbor_exact_file_checkpoint_paths(target_inventory, pathspecs)
        if not paths:
            return ReviewedLocalVcsCheckpoint(
                root=target_inventory.root,
                blocked_reason=_reviewed_local_vcs_checkpoint_rejection_reason(target_inventory, pathspecs, "pathspecs"),
            )
        return ReviewedLocalVcsCheckpoint(
            root=target_inventory.root,
            paths=frozenset(paths),
            mode="staging",
            visible_workdir=visible_workdir,
        )
    if not _is_narrow_local_vcs_commit_command(command):
        return ReviewedLocalVcsCheckpoint(
            root=target_inventory.root,
            blocked_reason="commit command is not a narrow local commit with a reviewed message option",
        )
    staged = _git_staged_paths_for_root(target_inventory.root)
    paths = _coherent_reviewed_local_vcs_checkpoint_paths(target_inventory, staged, prefer_staged_content=True)
    if not paths:
        paths = _coherent_delegated_neighbor_exact_file_checkpoint_paths(target_inventory, staged)
    if not paths:
        return ReviewedLocalVcsCheckpoint(
            root=target_inventory.root,
            blocked_reason=_reviewed_local_vcs_checkpoint_rejection_reason(target_inventory, staged, "staged files"),
        )
    return ReviewedLocalVcsCheckpoint(
        root=target_inventory.root,
        paths=frozenset(paths),
        mode="commit",
        visible_workdir=visible_workdir,
    )


def _reviewed_local_vcs_checkpoint_review_bundle(
    inventory: Inventory,
    data: dict[str, object],
    command: str,
) -> ReviewedLocalVcsCheckpoint:
    segments = _shell_command_segments(command)
    if len(segments) < 2 or _git_subcommand(segments[0]) not in {"add", "stage"}:
        return ReviewedLocalVcsCheckpoint()
    target_inventory, root_reason = _neighbor_mlh_root_inventory(inventory, data, segments[0])
    if target_inventory is None:
        return ReviewedLocalVcsCheckpoint(blocked_reason=root_reason) if root_reason else ReviewedLocalVcsCheckpoint()
    pathspecs = _git_stage_pathspecs(segments[0])
    if not pathspecs:
        return ReviewedLocalVcsCheckpoint(
            root=target_inventory.root,
            blocked_reason=(
                "no exact pathspecs were supplied; "
                + _reviewed_local_vcs_checkpoint_rejection_reason(target_inventory, (), "pathspecs")
            ),
        )
    paths = _coherent_reviewed_local_vcs_checkpoint_paths(target_inventory, pathspecs)
    if not paths:
        paths = _coherent_delegated_neighbor_exact_file_checkpoint_paths(target_inventory, pathspecs)
    if not paths:
        return ReviewedLocalVcsCheckpoint(
            root=target_inventory.root,
            blocked_reason=_reviewed_local_vcs_checkpoint_rejection_reason(target_inventory, pathspecs, "pathspecs"),
        )
    for segment in segments[1:]:
        if not _is_reviewed_local_vcs_checkpoint_review_segment(segment):
            return ReviewedLocalVcsCheckpoint(
                root=target_inventory.root,
                blocked_reason=(
                    f"actual command workdir/root is {target_inventory.root.resolve()}; "
                    "split any message-file creation from the final narrow local VCS command; "
                    "checkpoint convenience bundle may contain only exact git add/stage followed by "
                    "read-only git status and staged diff summary/check review commands"
                ),
            )
        segment_root, segment_reason = _neighbor_mlh_root_inventory(inventory, data, segment)
        if segment_root is None:
            return ReviewedLocalVcsCheckpoint(blocked_reason=segment_reason) if segment_reason else ReviewedLocalVcsCheckpoint()
        try:
            if segment_root.root.resolve() != target_inventory.root.resolve():
                return ReviewedLocalVcsCheckpoint(
                    root=target_inventory.root,
                    blocked_reason="checkpoint convenience bundle mixed different actual command roots",
                )
        except (OSError, RuntimeError, ValueError):
            return ReviewedLocalVcsCheckpoint(
                root=target_inventory.root,
                blocked_reason="checkpoint convenience bundle root could not be resolved",
            )
    return ReviewedLocalVcsCheckpoint(
        root=target_inventory.root,
        paths=frozenset(paths),
        mode="staging-review-bundle",
        visible_workdir=_checkpoint_uses_visible_workdir(inventory, data, target_inventory.root),
    )


def _reviewed_post_closeout_index_split(
    inventory: Inventory,
    data: dict[str, object],
    command: str,
) -> ReviewedLocalVcsCheckpoint:
    if len(_shell_command_segments(command)) > 1:
        return ReviewedLocalVcsCheckpoint()
    pathspecs = _git_index_split_pathspecs(command)
    if not pathspecs:
        return ReviewedLocalVcsCheckpoint()
    target_inventory, root_reason = _index_split_target_inventory(inventory, data, command)
    if target_inventory is None:
        return ReviewedLocalVcsCheckpoint(blocked_reason=root_reason) if root_reason else ReviewedLocalVcsCheckpoint()
    staged_paths = _git_staged_paths_for_root(target_inventory.root)
    split_paths = _coherent_post_closeout_index_split_paths(target_inventory, pathspecs, staged_paths)
    if not split_paths:
        return ReviewedLocalVcsCheckpoint(
            root=target_inventory.root,
            blocked_reason=_reviewed_local_vcs_checkpoint_rejection_reason(target_inventory, pathspecs, "index split pathspecs"),
        )
    return ReviewedLocalVcsCheckpoint(
        root=target_inventory.root,
        paths=frozenset(split_paths),
        mode="index-split",
        visible_workdir=_checkpoint_uses_visible_workdir(inventory, data, target_inventory.root),
    )


def _index_split_target_inventory(
    inventory: Inventory,
    data: dict[str, object],
    command: str,
) -> tuple[Inventory | None, str]:
    actual_root = _git_effective_workdir_path(inventory, data, command)
    if actual_root is None:
        return None, "actual command workdir/root is ambiguous because git work-tree/git-dir options were used"
    try:
        actual_root_resolved = actual_root.resolve()
        current_root = inventory.root.resolve()
    except (OSError, RuntimeError, ValueError):
        return None, "actual command workdir/root could not be resolved"
    if actual_root_resolved == current_root:
        return inventory, ""
    try:
        actual_root_resolved.relative_to(current_root)
        return None, "actual command workdir must be the operating root for index-only checkpoint split"
    except ValueError:
        pass
    except (OSError, RuntimeError):
        return None, "actual command workdir/root could not be compared with the current root"
    product_root = _configured_product_source_root_path(inventory)
    if product_root is not None:
        try:
            product_root_resolved = product_root.resolve()
            if actual_root_resolved == product_root_resolved:
                return None, ""
            actual_root_resolved.relative_to(product_root_resolved)
            return None, ""
        except ValueError:
            pass
        except (OSError, RuntimeError):
            return None, "actual command workdir/root could not be compared with the configured product source root"
    try:
        target_inventory = load_inventory(actual_root_resolved)
    except Exception:
        return None, "actual command workdir/root is not a readable MLH root"
    if target_inventory.root_kind != LIVE_OPERATING_ROOT:
        return None, f"actual command workdir/root is not a live MLH operating root (root_kind={target_inventory.root_kind})"
    return target_inventory, ""


def _coherent_post_closeout_index_split_paths(
    inventory: Inventory,
    pathspecs: list[str] | tuple[str, ...],
    staged_paths: list[str] | tuple[str, ...],
) -> set[str]:
    if _has_active_plan(inventory):
        return set()
    state = inventory.state
    if not state or not state.exists:
        return set()
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip().casefold() != "none":
        return set()
    if str(state_data.get("phase_status") or "").strip().casefold() != "complete":
        return set()
    staged = _normalized_exact_staged_paths(inventory, staged_paths)
    selected = _normalized_exact_index_split_pathspecs(inventory, pathspecs, staged)
    if not staged or not selected:
        return set()
    if not any(_is_checkpoint_sensitive_staged_path(inventory, path) for path in staged):
        return set()
    if selected == set(staged) and _coherent_checkpoint_path_set(inventory, selected):
        return selected
    if _coherent_checkpoint_path_set(inventory, staged):
        return set()
    remaining = tuple(path for path in staged if path not in selected)
    if _coherent_checkpoint_path_set(inventory, selected) or _coherent_checkpoint_path_set(inventory, remaining):
        return selected
    return set()


def _normalized_exact_staged_paths(inventory: Inventory, paths: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for path in paths:
        clean = _normalize_hook_path(_hook_route_rel_path(inventory, path) or path).casefold()
        if clean:
            normalized.append(clean)
    return tuple(normalized)


def _normalized_exact_index_split_pathspecs(
    inventory: Inventory,
    pathspecs: list[str] | tuple[str, ...],
    staged_paths: list[str] | tuple[str, ...],
) -> set[str]:
    staged = set(staged_paths)
    normalized: set[str] = set()
    for pathspec in pathspecs:
        clean = _normalize_hook_path(_hook_route_rel_path(inventory, pathspec) or pathspec).casefold()
        if not clean:
            return set()
        if clean in POST_CLOSEOUT_STAGE_BROAD_PATHS:
            return set()
        if any(char in clean for char in "*?[]"):
            return set()
        if clean.startswith(":") or any(clean.startswith(prefix) for prefix in POST_CLOSEOUT_STAGE_DISALLOWED_PREFIXES):
            return set()
        if clean not in staged:
            return set()
        normalized.add(clean)
    return normalized


def _coherent_checkpoint_path_set(inventory: Inventory, paths: set[str] | tuple[str, ...]) -> set[str]:
    if not paths:
        return set()
    ordered = tuple(paths)
    return (
        _coherent_reviewed_local_vcs_checkpoint_paths(inventory, ordered)
        or _coherent_post_closeout_mixed_vcs_finalization_paths(inventory, ordered)
    )


def _git_index_split_pathspecs(command: str) -> list[str]:
    if _has_shell_command_separator(command):
        return []
    subcommand, tokens, raw_tokens, subcommand_index = _git_command_context_tokens(command)
    if subcommand == "restore":
        return _git_restore_index_split_pathspecs(tokens, raw_tokens, subcommand_index)
    if subcommand == "reset":
        return _git_reset_index_split_pathspecs(tokens, raw_tokens, subcommand_index)
    return []


def _git_restore_index_split_pathspecs(tokens: list[str], raw_tokens: list[str], subcommand_index: int) -> list[str]:
    if subcommand_index < 0:
        return []
    has_staged = False
    saw_separator = False
    pathspecs: list[str] = []
    for token, raw_token in zip(tokens[subcommand_index + 1 :], raw_tokens[subcommand_index + 1 :]):
        clean = _clean_token(token)
        option = _clean_git_commit_option_token(raw_token)
        if not clean:
            continue
        if _is_shell_command_separator(raw_token, clean):
            return []
        if clean == "--":
            saw_separator = True
            continue
        if not saw_separator:
            if option == "--staged" or clean == "-S":
                has_staged = True
                continue
            if option in GIT_INDEX_SPLIT_RESTORE_ALLOWED_OPTIONS:
                continue
            return []
        pathspec = _clean_hook_path_token(str(raw_token))
        if pathspec:
            pathspecs.append(pathspec)
    return pathspecs if has_staged and saw_separator and pathspecs else []


def _git_reset_index_split_pathspecs(tokens: list[str], raw_tokens: list[str], subcommand_index: int) -> list[str]:
    if subcommand_index < 0:
        return []
    saw_separator = False
    saw_ref = False
    pathspecs: list[str] = []
    for token, raw_token in zip(tokens[subcommand_index + 1 :], raw_tokens[subcommand_index + 1 :]):
        clean = _clean_token(token)
        option = _clean_git_commit_option_token(raw_token)
        if not clean:
            continue
        if _is_shell_command_separator(raw_token, clean):
            return []
        if clean == "--":
            saw_separator = True
            continue
        if not saw_separator:
            if option in GIT_INDEX_SPLIT_RESET_ALLOWED_OPTIONS:
                continue
            if clean in GIT_INDEX_SPLIT_RESET_ALLOWED_REFS and not saw_ref:
                saw_ref = True
                continue
            return []
        pathspec = _clean_hook_path_token(str(raw_token))
        if pathspec:
            pathspecs.append(pathspec)
    return pathspecs if saw_separator and pathspecs else []


def _is_reviewed_local_vcs_checkpoint_review_segment(command: str) -> bool:
    if not _is_read_only_git_inspection_command(command):
        return False
    subcommand, tokens, subcommand_index = _git_command_context(command)
    if subcommand == "status":
        return True
    if subcommand != "diff" or subcommand_index < 0:
        return False
    args = {_clean_token(token) for token in tokens[subcommand_index + 1 :] if _clean_token(token)}
    staged_summary_args = {"--check", "--name-status", "--name-only"}
    return "--cached" in args and bool(args & staged_summary_args)


def _checkpoint_uses_visible_workdir(inventory: Inventory, data: dict[str, object], target_root: Path) -> bool:
    workdir = _hook_command_workdir_path(inventory, data)
    if workdir is None:
        return False
    try:
        return workdir.resolve() == target_root.resolve()
    except (OSError, RuntimeError, ValueError):
        return False


def _neighbor_mlh_root_inventory(inventory: Inventory, data: dict[str, object], command: str) -> tuple[Inventory | None, str]:
    actual_root = _git_effective_workdir_path(inventory, data, command)
    if actual_root is None:
        return None, "actual command workdir/root is ambiguous because git work-tree/git-dir options were used"
    try:
        actual_root_resolved = actual_root.resolve()
        current_root = inventory.root.resolve()
    except (OSError, RuntimeError, ValueError):
        return None, "actual command workdir/root could not be resolved"
    if actual_root_resolved == current_root:
        return None, ""
    try:
        actual_root_resolved.relative_to(current_root)
        return None, ""
    except ValueError:
        pass
    except (OSError, RuntimeError):
        return None, "actual command workdir/root could not be compared with the current root"
    product_root = _configured_product_source_root_path(inventory)
    if product_root is not None:
        try:
            product_root_resolved = product_root.resolve()
            if actual_root_resolved == product_root_resolved:
                return None, ""
            actual_root_resolved.relative_to(product_root_resolved)
            return None, ""
        except ValueError:
            pass
        except (OSError, RuntimeError):
            return None, "actual command workdir/root could not be compared with the configured product source root"
    try:
        target_inventory = load_inventory(actual_root_resolved)
    except Exception:
        return None, "actual command workdir/root is not a readable MLH root"
    if target_inventory.root_kind != LIVE_OPERATING_ROOT:
        return None, f"actual command workdir/root is not a live MLH operating root (root_kind={target_inventory.root_kind})"
    return target_inventory, ""


def _git_effective_workdir_path(inventory: Inventory, data: dict[str, object], command: str) -> Path | None:
    workdir = _hook_command_workdir_path(inventory, data) or inventory.root.resolve()
    _subcommand, tokens, raw_tokens, subcommand_index = _git_command_context_tokens(command)
    if subcommand_index < 0:
        return workdir
    git_index = -1
    for index, token in enumerate(tokens[:subcommand_index]):
        if _is_git_executable_token(token):
            git_index = index
            break
    if git_index < 0:
        return workdir
    index = git_index + 1
    while index < subcommand_index:
        clean = tokens[index]
        raw_clean = _clean_git_option_raw_token(raw_tokens[index])
        if raw_clean == "-C":
            if index + 1 >= subcommand_index:
                return None
            workdir = _resolve_path_token_from_base(raw_tokens[index + 1], workdir)
            if workdir is None:
                return None
            index += 2
            continue
        if raw_clean.startswith("-C") and len(raw_clean) > 2:
            workdir = _resolve_path_token_from_base(raw_clean[2:], workdir)
            if workdir is None:
                return None
            index += 1
            continue
        if clean in {"--work-tree", "--git-dir"} or clean.startswith(("--work-tree=", "--git-dir=")):
            return None
        if clean in GIT_OPTIONS_WITH_VALUES:
            index += 2
            continue
        if any(clean.startswith(option + "=") for option in GIT_OPTIONS_WITH_VALUES if option.startswith("--")):
            index += 1
            continue
        index += 1
    try:
        return workdir.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _clean_git_option_raw_token(token: str) -> str:
    return str(token or "").strip(' \t\r\n"\'`{}[](),;')


def _resolve_path_token_from_base(token: str, base: Path) -> Path | None:
    value = _path_argument_value(token) or _clean_hook_path_token(token)
    if not value:
        return None
    try:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        return candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _is_route_produced_lifecycle_commit_command(inventory: Inventory, command: str) -> bool:
    if not _is_narrow_local_vcs_commit_command(command):
        return False
    staged_paths = _git_staged_paths(inventory)
    if _coherent_active_plan_open_checkpoint_paths(inventory, staged_paths):
        return True
    if _coherent_active_plan_phase_transition_checkpoint_paths(
        inventory,
        staged_paths,
        prefer_staged_content=True,
    ):
        return True
    if not _active_plan_ready_for_route_produced_lifecycle_git(inventory):
        return False
    return _coherent_route_produced_lifecycle_paths(inventory, staged_paths)


def _is_narrow_local_vcs_commit_command(command: str) -> bool:
    if _has_shell_command_separator(command):
        return False
    subcommand, tokens, raw_tokens, subcommand_index = _git_command_context_tokens(command)
    if subcommand != "commit" or subcommand_index < 0:
        return False
    args = tokens[subcommand_index + 1 :]
    raw_args = raw_tokens[subcommand_index + 1 :]
    if not args:
        return False
    has_message = False
    index = 0
    while index < len(args):
        token = _clean_token(args[index])
        option_token = _clean_git_commit_option_token(raw_args[index])
        if not token:
            index += 1
            continue
        if token == "--":
            return False
        if option_token in POST_CLOSEOUT_COMMIT_DISALLOWED_OPTIONS:
            return False
        if any(
            option_token.startswith(option + "=")
            for option in POST_CLOSEOUT_COMMIT_DISALLOWED_OPTIONS
            if option.startswith("--")
        ):
            return False
        if option_token in POST_CLOSEOUT_COMMIT_MESSAGE_OPTIONS:
            if index + 1 >= len(args) or not _clean_token(args[index + 1]):
                return False
            has_message = True
            index += 2
            continue
        if any(
            option_token.startswith(option + "=")
            for option in POST_CLOSEOUT_COMMIT_MESSAGE_OPTIONS
            if option.startswith("--")
        ):
            has_message = True
            index += 1
            continue
        if option_token.startswith("-m") and len(option_token) > 2:
            has_message = True
            index += 1
            continue
        if option_token.startswith("-F") and len(option_token) > 2:
            has_message = True
            index += 1
            continue
        return False
    return has_message


def _active_plan_ready_for_route_produced_lifecycle_git(inventory: Inventory) -> bool:
    if not _has_active_plan(inventory):
        return False
    state = inventory.state
    if not state or not state.exists:
        return False
    phase_status = str(state.frontmatter.data.get("phase_status") or "").strip().casefold()
    if phase_status not in ROUTE_PRODUCED_LIFECYCLE_PHASE_STATUSES:
        return False
    return any(marker in state.content for marker in ROUTE_WRITEBACK_MARKERS)


def _coherent_route_produced_lifecycle_paths(inventory: Inventory, paths: list[str] | tuple[str, ...]) -> bool:
    normalized = _normalized_route_produced_lifecycle_paths(inventory, paths)
    if not normalized:
        return False
    state_rel = "project/" + "project-state.md"
    roadmap_rel = "project/" + "roadmap.md"
    active_plan_rel = _active_plan_rel_path(inventory)
    last_archive_rel = _last_archived_plan_rel_path(inventory)
    allowed = {state_rel, roadmap_rel}
    if active_plan_rel:
        allowed.add(active_plan_rel)
    if last_archive_rel:
        allowed.add(last_archive_rel)
        allowed.update(
            path
            for path in normalized
            if _is_reviewed_post_closeout_source_incubation_file(inventory, path, last_archive_rel)
        )
    allowed.update(path for path in normalized if path.startswith("project/archive/plans/"))
    allowed.update(path for path in normalized if _is_reviewed_meta_feedback_checkpoint_stage_file(inventory, path))
    if any(path not in allowed for path in normalized):
        return False
    if state_rel not in normalized:
        return False
    companion_paths = normalized - {state_rel}
    if not companion_paths:
        return False
    archive_paths = {path for path in normalized if path.startswith("project/archive/plans/")}
    if archive_paths and roadmap_rel not in normalized:
        return False
    if last_archive_rel and (roadmap_rel in normalized or archive_paths) and last_archive_rel not in normalized:
        return False
    return True


def _coherent_active_plan_open_checkpoint_paths(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
) -> set[str]:
    if not _has_active_plan(inventory):
        return set()
    state = inventory.state
    if not state or not state.exists:
        return set()
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip().casefold() != "active":
        return set()
    phase_status = str(state_data.get("phase_status") or "").strip().casefold()
    if not _active_plan_phase_transition_checkpoint_status_allows(phase_status):
        return set()
    active_plan_rel = _active_plan_rel_path(inventory)
    if not active_plan_rel:
        return set()
    normalized = _normalized_route_produced_lifecycle_paths(inventory, paths)
    if not normalized:
        return set()
    state_rel = "project/" + "project-state.md"
    roadmap_rel = "project/" + "roadmap.md"
    required = {state_rel, roadmap_rel, active_plan_rel}
    if not required <= normalized:
        return set()
    plan_data = _active_plan_open_checkpoint_frontmatter(inventory, active_plan_rel)
    if plan_data is None:
        return set()
    if not _active_plan_open_checkpoint_matches_state(state_data, plan_data, active_plan_rel):
        return set()
    source_note_paths = normalized - required
    allowed_source_notes = {
        path
        for path in source_note_paths
        if _is_active_plan_open_checkpoint_source_note(inventory, path, active_plan_rel, plan_data)
    }
    if source_note_paths != allowed_source_notes:
        return set()
    if not _roadmap_mentions_active_plan_open_checkpoint(inventory, active_plan_rel, allowed_source_notes):
        return set()
    return normalized


def _coherent_active_plan_phase_transition_checkpoint_paths(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
    *,
    prefer_staged_content: bool = False,
) -> set[str]:
    if not _has_active_plan(inventory):
        return set()
    state_rel = "project/" + "project-state.md"
    state_text = _route_file_text_for_checkpoint(
        inventory,
        state_rel,
        prefer_staged_content=prefer_staged_content,
    )
    if state_text is None:
        return set()
    try:
        state_frontmatter = parse_frontmatter(state_text)
    except ValueError:
        return set()
    if not state_frontmatter.has_frontmatter or state_frontmatter.errors:
        return set()
    state_data = state_frontmatter.data
    if str(state_data.get("plan_status") or "").strip().casefold() != "active":
        return set()
    phase_status = str(state_data.get("phase_status") or "").strip().casefold()
    if not _active_plan_phase_transition_checkpoint_status_allows(phase_status):
        return set()
    active_plan_rel = _normalize_hook_path(str(state_data.get("active_plan") or "")).casefold()
    if not active_plan_rel:
        return set()
    normalized = _normalized_route_produced_lifecycle_paths(inventory, paths)
    if normalized != {state_rel, active_plan_rel}:
        return set()
    if not _state_has_current_phase_transition_writeback(state_text, state_data):
        return set()
    plan_data = _active_plan_open_checkpoint_frontmatter(
        inventory,
        active_plan_rel,
        prefer_staged_content=prefer_staged_content,
    )
    if plan_data is None:
        return set()
    if not _active_plan_open_checkpoint_matches_state(state_data, plan_data, active_plan_rel):
        return set()
    return normalized


def _state_has_current_phase_transition_writeback(state_text: str, state_data: dict[str, object]) -> bool:
    active_phase = str(state_data.get("active_phase") or "").strip().casefold()
    phase_status = str(state_data.get("phase_status") or "").strip().casefold()
    if not active_phase or not _active_plan_phase_transition_checkpoint_status_allows(phase_status):
        return False
    blocks = _route_writeback_blocks(state_text)
    if not blocks:
        return False
    latest = blocks[-1].casefold()
    return (
        "state_writeback" in latest
        and "active_phase" in latest
        and active_phase in latest
        and "phase_status" in latest
        and phase_status in latest
    )


def _active_plan_phase_transition_checkpoint_status_allows(phase_status: str) -> bool:
    return phase_status in {"active", "in_progress", "pending"}


def _route_writeback_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for marker in ROUTE_WRITEBACK_MARKERS:
        end_marker = marker.replace("BEGIN", "END", 1)
        start = 0
        while True:
            index = text.find(marker, start)
            if index < 0:
                break
            end = text.find(end_marker, index + len(marker))
            if end < 0:
                break
            blocks.append(text[index : end + len(end_marker)])
            start = end + len(end_marker)
    return sorted(blocks, key=text.find)


def _active_plan_open_checkpoint_frontmatter(
    inventory: Inventory,
    active_plan_rel: str,
    *,
    prefer_staged_content: bool = False,
) -> dict[str, object] | None:
    text = _route_file_text_for_checkpoint(
        inventory,
        active_plan_rel,
        prefer_staged_content=prefer_staged_content,
    )
    if text is None:
        return None
    try:
        frontmatter = parse_frontmatter(text)
    except ValueError:
        return None
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return None
    return frontmatter.data


def _active_plan_open_checkpoint_matches_state(
    state_data: dict[str, object],
    plan_data: dict[str, object],
    active_plan_rel: str,
) -> bool:
    plan_status = str(plan_data.get("status") or "").strip().casefold()
    phase_status = str(plan_data.get("phase_status") or "").strip().casefold()
    active_phase = str(plan_data.get("active_phase") or "").strip()
    plan_id = str(plan_data.get("plan_id") or "").strip()
    state_plan = _normalize_hook_path(str(state_data.get("active_plan") or "")).casefold()
    state_phase = str(state_data.get("active_phase") or "").strip()
    state_phase_status = str(state_data.get("phase_status") or "").strip().casefold()
    expected_plan_status = "pending" if phase_status == "pending" else "active"
    if state_plan and state_plan != _normalize_hook_path(active_plan_rel).casefold():
        return False
    return bool(
        plan_id
        and active_phase
        and active_phase == state_phase
        and plan_status == expected_plan_status
        and _active_plan_phase_transition_checkpoint_status_allows(phase_status)
        and phase_status == state_phase_status
    )


def _active_plan_open_checkpoint_roadmap_items(plan_data: dict[str, object]) -> set[str]:
    items = {
        str(plan_data.get("primary_roadmap_item") or "").strip(),
        str(plan_data.get("related_roadmap_item") or "").strip(),
    }
    covered = plan_data.get("covered_roadmap_items")
    if isinstance(covered, list):
        items.update(str(item or "").strip() for item in covered)
    elif covered:
        items.add(str(covered).strip())
    return {item for item in items if item}


def _is_active_plan_open_checkpoint_source_note(
    inventory: Inventory,
    path: str,
    active_plan_rel: str,
    plan_data: dict[str, object],
) -> bool:
    if not _is_meta_feedback_incubation_route_path(path):
        return False
    data = _reviewed_mlh_incubation_file_frontmatter(inventory, path)
    if data is None:
        return False
    related_plan = _normalize_hook_path(str(data.get("related_plan") or "")).casefold()
    if related_plan != _normalize_hook_path(active_plan_rel).casefold():
        return False
    related_item = str(data.get("related_roadmap_item") or "").strip()
    covered_items = _active_plan_open_checkpoint_roadmap_items(plan_data)
    if related_item and related_item in covered_items:
        return True
    source_incubation = _normalize_hook_path(str(plan_data.get("source_incubation") or "")).casefold()
    return bool(source_incubation and source_incubation == _normalize_hook_path(path).casefold())


def _roadmap_mentions_active_plan_open_checkpoint(
    inventory: Inventory,
    active_plan_rel: str,
    source_note_paths: set[str],
) -> bool:
    text = _route_file_text_for_checkpoint(inventory, "project/roadmap.md")
    if text is None:
        return False
    lowered = text.casefold()
    if _normalize_hook_path(active_plan_rel).casefold() not in lowered:
        return False
    return all(_normalize_hook_path(path).casefold() in lowered for path in source_note_paths)


def _coherent_post_closeout_lifecycle_vcs_finalization_paths(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
    *,
    prefer_staged_state: bool = False,
) -> set[str]:
    if _has_active_plan(inventory):
        return set()
    state_data, state_content = _post_closeout_lifecycle_state_authority(
        inventory,
        paths,
        prefer_staged_state=prefer_staged_state,
    )
    if not state_data:
        return set()
    if str(state_data.get("plan_status") or "").strip().casefold() != "none":
        return set()
    if str(state_data.get("phase_status") or "").strip().casefold() != "complete":
        return set()
    if not any(marker in state_content for marker in ROUTE_WRITEBACK_MARKERS):
        return set()
    normalized = _normalized_route_produced_lifecycle_paths(inventory, paths)
    if not normalized:
        return set()
    state_rel = "project/" + "project-state.md"
    roadmap_rel = "project/" + "roadmap.md"
    last_archive_rel = _last_archived_plan_rel_path_from_data(state_data)
    if not last_archive_rel:
        return set()
    archive_paths = {path for path in normalized if _is_deferred_archive_plan_route_path(path)}
    evidence_paths = {
        path
        for path in normalized
        if _is_verification_checkpoint_route_path(path) or _is_top_level_verification_checkpoint_path(path)
    }
    allowed = {state_rel, roadmap_rel, *archive_paths, *evidence_paths}
    if any(path not in allowed for path in normalized):
        return set()
    if state_rel not in normalized or last_archive_rel not in archive_paths or not evidence_paths:
        return set()
    if not all(_is_reviewed_post_closeout_archive_plan_file(inventory, path) for path in archive_paths):
        return set()
    if not all(_is_reviewed_lifecycle_finalization_evidence_file(inventory, path) for path in evidence_paths):
        return set()
    return normalized


def _coherent_post_closeout_mixed_vcs_finalization_paths(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
    *,
    prefer_staged_state: bool = False,
) -> set[str]:
    lifecycle_paths = _coherent_post_closeout_lifecycle_vcs_finalization_paths(
        inventory,
        paths,
        prefer_staged_state=prefer_staged_state,
    )
    if lifecycle_paths:
        return lifecycle_paths

    route_candidates: list[str] = []
    ordinary_candidates: list[str] = []
    for path in paths:
        if _is_existing_lifecycle_route_file(inventory, path):
            route_candidates.append(path)
        else:
            ordinary_candidates.append(path)
    if not route_candidates or not ordinary_candidates:
        return set()

    lifecycle_paths = _coherent_post_closeout_lifecycle_vcs_finalization_paths(
        inventory,
        route_candidates,
        prefer_staged_state=prefer_staged_state,
    )
    if not lifecycle_paths:
        return set()

    allowed_targets = _post_closeout_archived_plan_target_artifacts(inventory, lifecycle_paths)
    if not allowed_targets:
        return set()

    ordinary_paths: set[str] = set()
    for path in ordinary_candidates:
        if not _is_exact_post_closeout_stage_file(inventory, path):
            return set()
        normalized = _normalize_plan_artifact_candidate(inventory, path)
        if not normalized or normalized not in allowed_targets:
            return set()
        ordinary_paths.add(normalized)
    return lifecycle_paths | ordinary_paths


def _coherent_post_closeout_roadmap_promotion_finalization_paths(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
    *,
    prefer_staged_content: bool = False,
) -> set[str]:
    normalized = _normalized_post_closeout_lifecycle_route_checkpoint_paths(inventory, paths)
    if not normalized:
        return set()
    roadmap_rel = "project/" + "roadmap.md"
    if roadmap_rel not in normalized:
        return set()
    last_archive_rel = _last_archived_plan_rel_path(inventory)
    if not last_archive_rel:
        return set()
    promoted_incubation_paths: set[str] = set()
    for path in normalized:
        if not _is_meta_feedback_incubation_route_path(path) or not _is_existing_lifecycle_route_file(inventory, path):
            continue
        if _is_reviewed_post_closeout_source_incubation_file(inventory, path, last_archive_rel):
            continue
        data = _reviewed_mlh_incubation_file_frontmatter(
            inventory,
            path,
            prefer_staged_content=prefer_staged_content,
        )
        if data is None or _incubation_frontmatter_declares_archive_plan_relationship(data):
            return set()
        promoted_incubation_paths.add(path)
    if not promoted_incubation_paths:
        return set()
    promotion_subset = promoted_incubation_paths | {roadmap_rel}
    if not _coherent_roadmap_promotion_checkpoint_paths(
        inventory,
        tuple(sorted(promotion_subset)),
        prefer_staged_content=prefer_staged_content,
    ):
        return set()
    lifecycle_subset = normalized - promoted_incubation_paths
    if not _coherent_post_closeout_lifecycle_route_checkpoint_paths(
        inventory,
        tuple(sorted(lifecycle_subset)),
    ):
        if not _coherent_unlocked_prior_roadmap_package_paths(
            inventory,
            normalized,
            promoted_incubation_paths,
            last_archive_rel,
        ):
            return set()
    return normalized


def _coherent_unlocked_prior_roadmap_package_paths(
    inventory: Inventory,
    normalized: set[str],
    promoted_incubation_paths: set[str],
    last_archive_rel: str,
) -> set[str]:
    state_rel = "project/" + "project-state.md"
    roadmap_rel = "project/" + "roadmap.md"
    current_closeout_subset = {state_rel, last_archive_rel}
    if ACTIVE_PLAN_ROUTE_PATH in normalized:
        current_closeout_subset.add(ACTIVE_PLAN_ROUTE_PATH)
    if not current_closeout_subset <= normalized:
        return set()
    if not _coherent_post_closeout_lifecycle_route_checkpoint_paths(
        inventory,
        tuple(sorted(current_closeout_subset)),
        allow_without_roadmap=True,
    ):
        return set()

    prior_subset = normalized - current_closeout_subset - promoted_incubation_paths
    if roadmap_rel not in prior_subset:
        return set()
    prior_extra = prior_subset - {roadmap_rel}
    prior_archive_paths = {
        path for path in prior_extra if path != last_archive_rel and _is_deferred_archive_plan_route_path(path)
    }
    if not prior_archive_paths:
        return set()
    if not all(
        _is_reviewed_post_closeout_archive_plan_file(inventory, path)
        and _roadmap_references_archived_plan(inventory, path)
        for path in prior_archive_paths
    ):
        return set()

    source_archive_paths = {
        path
        for path in prior_extra
        if _is_memory_hygiene_archive_reference_path(path)
        and any(_is_reviewed_post_closeout_source_incubation_file(inventory, path, archive) for archive in prior_archive_paths)
    }
    allowed = {roadmap_rel, *prior_archive_paths, *source_archive_paths}
    for path in sorted(prior_extra - allowed):
        if _is_post_closeout_source_incubation_tombstone_path(inventory, path, source_archive_paths):
            allowed.add(path)
            continue
        if _is_reviewed_lifecycle_finalization_evidence_for_archive(inventory, path, prior_archive_paths):
            allowed.add(path)
            continue
        return set()
    return normalized if prior_subset <= allowed else set()


def _is_reviewed_lifecycle_finalization_evidence_for_archive(
    inventory: Inventory,
    path: str,
    archive_paths: set[str],
) -> bool:
    if not _is_reviewed_lifecycle_finalization_evidence_file(inventory, path):
        return False
    text = _route_file_text_for_checkpoint(inventory, path)
    if text is None:
        return False
    return any(archive in text for archive in archive_paths)


def _post_closeout_archived_plan_target_artifacts(inventory: Inventory, paths: set[str]) -> set[str]:
    targets: set[str] = set()
    for path in paths:
        if not _is_deferred_archive_plan_route_path(path):
            continue
        route_path = _hook_route_file_path(inventory, path)
        if route_path is None:
            continue
        try:
            frontmatter = parse_frontmatter(route_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        artifacts = frontmatter.data.get("target_artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            normalized = _normalize_hook_path(str(artifact or "")).casefold().rstrip("/")
            if normalized:
                targets.add(normalized)
    return targets


def _is_reviewed_lifecycle_finalization_evidence_file(inventory: Inventory, path: str) -> bool:
    if _is_verification_checkpoint_route_path(path):
        return _is_reviewed_verification_checkpoint_file(inventory, path)
    if _is_top_level_verification_checkpoint_path(path):
        return _is_reviewed_top_level_verification_checkpoint_file(inventory, path)
    return False


def _coherent_reviewed_local_vcs_checkpoint_paths(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
    *,
    prefer_staged_content: bool = False,
) -> set[str]:
    if _active_plan_ready_for_route_produced_lifecycle_git(inventory) and _coherent_route_produced_lifecycle_paths(inventory, paths):
        return _normalized_route_produced_lifecycle_paths(inventory, paths)
    active_plan_open_paths = _coherent_active_plan_open_checkpoint_paths(inventory, paths)
    if active_plan_open_paths:
        return active_plan_open_paths
    active_plan_phase_transition_paths = _coherent_active_plan_phase_transition_checkpoint_paths(inventory, paths)
    if active_plan_phase_transition_paths:
        return active_plan_phase_transition_paths
    roadmap_promotion_paths = _coherent_roadmap_promotion_checkpoint_paths(
        inventory,
        paths,
        prefer_staged_content=prefer_staged_content,
    )
    if roadmap_promotion_paths:
        return roadmap_promotion_paths
    if _looks_like_roadmap_promotion_checkpoint_paths(inventory, paths):
        return set()
    roadmap_promotion_finalization_paths = _coherent_post_closeout_roadmap_promotion_finalization_paths(
        inventory,
        paths,
        prefer_staged_content=prefer_staged_content,
    )
    if roadmap_promotion_finalization_paths:
        return roadmap_promotion_finalization_paths
    post_closeout_route_paths = _coherent_post_closeout_lifecycle_route_checkpoint_paths(inventory, paths)
    if not post_closeout_route_paths:
        post_closeout_route_paths = _coherent_minimal_post_closeout_lifecycle_route_checkpoint_paths_without_roadmap(
            inventory,
            paths,
        )
    if post_closeout_route_paths:
        return post_closeout_route_paths
    staged_lifecycle_paths = _coherent_lifecycle_stage_paths_with_existing_index(inventory, paths)
    if staged_lifecycle_paths:
        return staged_lifecycle_paths
    post_closeout_paths = _coherent_post_closeout_lifecycle_vcs_finalization_paths(inventory, paths)
    if post_closeout_paths:
        return post_closeout_paths
    archived_source_tombstone_paths = _coherent_archived_source_incubation_tombstone_stage_paths(inventory, paths)
    if archived_source_tombstone_paths:
        return archived_source_tombstone_paths
    archive_reference_checkpoint_paths = _coherent_memory_hygiene_archive_reference_checkpoint_paths(
        inventory,
        paths,
        prefer_staged_content=prefer_staged_content,
    )
    if archive_reference_checkpoint_paths:
        return archive_reference_checkpoint_paths
    memory_hygiene_paths = _coherent_memory_hygiene_checkpoint_paths(
        inventory,
        paths,
        prefer_staged_content=prefer_staged_content,
    )
    if memory_hygiene_paths:
        return memory_hygiene_paths
    normalized = _normalized_route_produced_lifecycle_paths(inventory, paths)
    if not normalized:
        return set()
    approval_packet_paths = {path for path in normalized if _verification_checkpoint_path_class(path) == "approval-packets"}
    if approval_packet_paths and normalized == approval_packet_paths:
        return normalized if all(_is_reviewed_pending_approval_packet_file(inventory, path) for path in approval_packet_paths) else set()
    decision_artifact_paths = {path for path in normalized if _is_checkpoint_decision_route_path(path)}
    if decision_artifact_paths and normalized == decision_artifact_paths:
        return (
            normalized
            if all(_is_reviewed_decision_checkpoint_artifact_file(inventory, path) for path in decision_artifact_paths)
            else set()
        )
    agent_run_paths = {path for path in normalized if _is_agent_run_evidence_route_path(path)}
    if agent_run_paths and normalized == agent_run_paths:
        return normalized if all(_is_reviewed_agent_run_evidence_file(inventory, path) for path in agent_run_paths) else set()
    receipt_paths = {path for path in normalized if _is_worker_run_receipt_route_path(path)}
    if receipt_paths:
        allowed = set(receipt_paths)
        for path in receipt_paths:
            receipt_allowed = _reviewed_worker_run_receipt_checkpoint_refs(inventory, path)
            if not receipt_allowed:
                return set()
            allowed.update(receipt_allowed)
        return normalized if normalized <= allowed else set()
    retention_receipt_paths = {path for path in normalized if _is_retention_receipt_route_path(path)}
    if retention_receipt_paths:
        allowed = set(retention_receipt_paths)
        for path in retention_receipt_paths:
            receipt_allowed = _reviewed_retention_receipt_checkpoint_refs(inventory, path)
            if not receipt_allowed:
                return set()
            allowed.update(receipt_allowed)
        return normalized if normalized <= allowed else set()
    verification_package_paths = _coherent_verification_decision_checkpoint_paths(inventory, normalized)
    if verification_package_paths:
        return verification_package_paths
    route_imported_research_paths = _coherent_route_imported_research_checkpoint_paths(inventory, normalized)
    if route_imported_research_paths:
        return route_imported_research_paths
    deferred_package_paths = _coherent_deferred_route_package_checkpoint_paths(inventory, normalized)
    if deferred_package_paths:
        return deferred_package_paths
    archive_plan_paths = _coherent_standalone_archive_plan_checkpoint_paths(inventory, normalized)
    if archive_plan_paths:
        return archive_plan_paths
    meta_feedback_paths = _coherent_meta_feedback_checkpoint_paths(inventory, normalized)
    if meta_feedback_paths:
        return meta_feedback_paths
    return set()


def _coherent_minimal_post_closeout_lifecycle_route_checkpoint_paths_without_roadmap(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
) -> set[str]:
    post_closeout_route_paths = _coherent_post_closeout_lifecycle_route_checkpoint_paths(
        inventory,
        paths,
        allow_without_roadmap=True,
    )
    if not post_closeout_route_paths:
        return set()
    state_rel = "project/" + "project-state.md"
    last_archive_rel = _last_archived_plan_rel_path(inventory)
    if not last_archive_rel:
        return set()
    required = {state_rel, last_archive_rel}
    optional = {ACTIVE_PLAN_ROUTE_PATH}
    return post_closeout_route_paths if required <= post_closeout_route_paths <= required | optional else set()


def _coherent_delegated_neighbor_exact_file_checkpoint_paths(
    inventory: Inventory, paths: list[str] | tuple[str, ...]
) -> set[str]:
    normalized = _normalized_delegated_neighbor_exact_file_paths(inventory, paths)
    if not normalized:
        return set()
    bootstrap_paths = _coherent_delegated_neighbor_bootstrap_checkpoint_paths(inventory, normalized)
    if bootstrap_paths:
        return bootstrap_paths
    project_paths = _coherent_delegated_neighbor_project_evidence_checkpoint_paths(inventory, normalized)
    if project_paths:
        return project_paths
    if any(_is_lifecycle_route_path(path) or path.startswith("project/") for path in normalized):
        return set()
    return normalized


def _coherent_delegated_neighbor_project_evidence_checkpoint_paths(inventory: Inventory, paths: set[str]) -> set[str]:
    project_paths = {path for path in paths if path.startswith("project/")}
    if not project_paths:
        return set()
    if project_paths != paths:
        return set()
    if project_paths & NEIGHBOR_PROJECT_EVIDENCE_EXACT_CORE_PATHS:
        return set()
    if not all(_delegated_neighbor_project_evidence_path_allowed(path) for path in project_paths):
        return set()
    decision_artifact_paths = {path for path in project_paths if _is_checkpoint_decision_route_path(path)}
    if decision_artifact_paths and not all(
        _is_reviewed_decision_checkpoint_artifact_file(inventory, path) for path in decision_artifact_paths
    ):
        return set()
    approval_packet_paths = {
        path for path in project_paths if _verification_checkpoint_path_class(path) == "approval-packets"
    }
    if approval_packet_paths and not all(
        _is_reviewed_pending_approval_packet_file(inventory, path) for path in approval_packet_paths
    ):
        return set()
    archive_plan_paths = {path for path in project_paths if _is_deferred_archive_plan_route_path(path)}
    if archive_plan_paths and archive_plan_paths == project_paths:
        if not all(_is_reviewed_standalone_archive_plan_checkpoint_file(inventory, path) for path in archive_plan_paths):
            return set()
    incubation_paths = {
        path
        for path in project_paths
        if path.startswith(NEIGHBOR_PROJECT_EVIDENCE_EXACT_INCUBATION_PREFIX)
    }
    if incubation_paths and incubation_paths == project_paths:
        return set()
    return project_paths


def _delegated_neighbor_project_evidence_path_allowed(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    if any(rel.startswith(prefix) for prefix in NEIGHBOR_PROJECT_EVIDENCE_EXACT_ALLOWED_PREFIXES):
        return True
    return rel.startswith(NEIGHBOR_PROJECT_EVIDENCE_EXACT_INCUBATION_PREFIX)


def _coherent_delegated_neighbor_bootstrap_checkpoint_paths(inventory: Inventory, paths: set[str]) -> set[str]:
    if not paths:
        return set()
    required = {"agents.md", "readme.md", "project/project-state.md"}
    if not required <= paths:
        return set()
    if not any(path in paths for path in (".codex/project-workflow.toml", ".mylittleharness/project-workflow.toml")):
        return set()
    for path in paths:
        if path in NEIGHBOR_BOOTSTRAP_EXACT_PATHS:
            continue
        if any(path.startswith(prefix) for prefix in NEIGHBOR_BOOTSTRAP_ALLOWED_PREFIXES):
            continue
        return set()
    state_path = _hook_route_file_path(inventory, "project/project-state.md")
    if state_path is None:
        return set()
    try:
        frontmatter = parse_frontmatter(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return set()
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return set()
    data = frontmatter.data
    return paths if str(data.get("plan_status") or "").strip().casefold() == "none" else set()


def _normalized_delegated_neighbor_exact_file_paths(
    inventory: Inventory, paths: list[str] | tuple[str, ...]
) -> set[str]:
    normalized: set[str] = set()
    for path in paths:
        rel = _hook_route_rel_path(inventory, path)
        clean = _normalize_hook_path(rel) if rel else ""
        clean_key = clean.casefold()
        if not clean_key or _delegated_neighbor_exact_path_blocked(clean_key):
            return set()
        route_path = _hook_route_file_path(inventory, clean)
        if route_path is None:
            return set()
        try:
            if not route_path.is_file() or route_path.is_symlink():
                return set()
        except (OSError, RuntimeError):
            return set()
        normalized.add(clean_key)
    return normalized


def _delegated_neighbor_exact_path_blocked(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    if rel in POST_CLOSEOUT_STAGE_BROAD_PATHS:
        return True
    if any(char in rel for char in "*?[]"):
        return True
    if rel.startswith(":"):
        return True
    return any(rel.startswith(prefix) for prefix in NEIGHBOR_EXACT_STAGE_DISALLOWED_PREFIXES)


def _coherent_post_closeout_lifecycle_route_checkpoint_paths(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
    *,
    allow_without_roadmap: bool = False,
) -> set[str]:
    if _has_active_plan(inventory):
        return set()
    state = inventory.state
    if not state or not state.exists:
        return set()
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip().casefold() != "none":
        return set()
    if str(state_data.get("phase_status") or "").strip().casefold() != "complete":
        return set()
    if not any(marker in state.content for marker in ROUTE_WRITEBACK_MARKERS):
        return set()
    normalized = _normalized_post_closeout_lifecycle_route_checkpoint_paths(inventory, paths)
    if not normalized:
        return set()
    state_rel = "project/" + "project-state.md"
    roadmap_rel = "project/" + "roadmap.md"
    last_archive_rel = _last_archived_plan_rel_path(inventory)
    if not last_archive_rel or not _is_deferred_archive_plan_route_path(last_archive_rel):
        return set()
    has_roadmap = roadmap_rel in normalized
    if not has_roadmap and not allow_without_roadmap:
        return set()
    required = {state_rel, last_archive_rel}
    if has_roadmap:
        required.add(roadmap_rel)
    optional = {ACTIVE_PLAN_ROUTE_PATH}
    if not required <= normalized:
        return set()
    extra = normalized - required - optional
    reviewed_source_archives = {
        path
        for path in extra
        if _is_memory_hygiene_archive_reference_path(path)
        and _is_reviewed_post_closeout_source_incubation_file(inventory, path, last_archive_rel)
    }
    if extra and not all(
        _is_reviewed_post_closeout_lifecycle_package_extra(
            inventory,
            path,
            last_archive_rel,
            reviewed_source_archives,
        )
        for path in extra
    ):
        return set()
    if ACTIVE_PLAN_ROUTE_PATH in normalized and not _is_post_closeout_active_plan_tombstone_path(
        inventory, ACTIVE_PLAN_ROUTE_PATH
    ):
        return set()
    if not _is_reviewed_post_closeout_archive_plan_file(inventory, last_archive_rel):
        return set()
    if has_roadmap and not _roadmap_references_archived_plan(inventory, last_archive_rel):
        return set()
    return normalized


def _is_reviewed_post_closeout_lifecycle_package_extra(
    inventory: Inventory,
    path: str,
    last_archive_rel: str,
    reviewed_source_archives: set[str],
) -> bool:
    return (
        _is_reviewed_post_closeout_source_incubation_file(inventory, path, last_archive_rel)
        or _is_post_closeout_source_incubation_tombstone_path(inventory, path, reviewed_source_archives)
        or _is_reviewed_post_closeout_meta_feedback_extra_file(inventory, path)
        or _is_reviewed_post_closeout_top_level_verification_extra_file(inventory, path, reviewed_source_archives)
        or _is_reviewed_lifecycle_finalization_evidence_file(inventory, path)
    )


def _is_reviewed_post_closeout_meta_feedback_extra_file(inventory: Inventory, path: str) -> bool:
    if not _is_reviewed_meta_feedback_checkpoint_stage_file(inventory, path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        frontmatter = parse_frontmatter(route_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    data = frontmatter.data
    return not any(str(data.get(field) or "").strip() for field in ("archived_plan", "implemented_by"))


def _is_reviewed_post_closeout_top_level_verification_extra_file(
    inventory: Inventory,
    path: str,
    reviewed_source_archives: set[str],
) -> bool:
    if not reviewed_source_archives or not _is_top_level_verification_checkpoint_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink() or route_path.suffix.casefold() != ".md":
            return False
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    data = frontmatter.data
    if _route_frontmatter_grants_checkpoint_authority(data):
        return False
    if str(data.get("route") or "").strip().casefold() != "verification":
        return False
    source_members = data.get("source_members")
    if not isinstance(source_members, list):
        return False
    normalized_members = {
        _hook_route_rel_path(inventory, str(member or "")).casefold()
        for member in source_members
        if str(member or "").strip()
    }
    if not normalized_members:
        return False
    if not normalized_members.intersection(reviewed_source_archives):
        return False
    if not all(
        member in reviewed_source_archives or _is_reviewed_memory_hygiene_archive_reference_file(inventory, member)
        for member in normalized_members
    ):
        return False
    if _route_evidence_text_has_release_authorizing_claim(text):
        return False
    return _route_evidence_text_has_non_authority_boundary(text) or _route_evidence_text_has_safe_release_boundary(text)


def _coherent_route_produced_lifecycle_stage_paths(
    inventory: Inventory, paths: list[str] | tuple[str, ...]
) -> set[str]:
    direct = _coherent_route_produced_lifecycle_paths(inventory, paths)
    if direct:
        return _normalized_route_produced_lifecycle_paths(inventory, paths)
    meta_feedback = _coherent_meta_feedback_checkpoint_paths(
        inventory,
        _normalized_route_produced_lifecycle_paths(inventory, paths),
    )
    if meta_feedback:
        return meta_feedback
    return _coherent_lifecycle_stage_paths_with_existing_index(
        inventory,
        paths,
        allow_without_roadmap=True,
    )


def _coherent_lifecycle_stage_paths_with_existing_index(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
    *,
    allow_without_roadmap: bool = False,
) -> set[str]:
    if not paths:
        return set()
    normalized_route = _normalized_route_produced_lifecycle_paths(inventory, paths)
    normalized_post_closeout = _normalized_post_closeout_lifecycle_route_checkpoint_paths(inventory, paths)
    normalized_current = normalized_route or normalized_post_closeout
    if not normalized_current:
        return set()
    staged_paths = _git_staged_paths(inventory)
    if not staged_paths:
        return set()
    combined_paths = tuple(staged_paths) + tuple(paths)
    if _active_plan_ready_for_route_produced_lifecycle_git(inventory) and _coherent_route_produced_lifecycle_paths(
        inventory, combined_paths
    ):
        combined = _normalized_route_produced_lifecycle_paths(inventory, combined_paths)
        return combined if normalized_current <= combined else set()
    active_plan_open_paths = _coherent_active_plan_open_checkpoint_paths(inventory, combined_paths)
    if active_plan_open_paths and normalized_current <= active_plan_open_paths:
        return active_plan_open_paths
    combined = _coherent_post_closeout_lifecycle_route_checkpoint_paths(
        inventory,
        combined_paths,
        allow_without_roadmap=allow_without_roadmap,
    )
    if combined and normalized_current <= combined:
        return combined
    return set()


def _coherent_verification_decision_checkpoint_paths(inventory: Inventory, paths: set[str]) -> set[str]:
    if _has_active_plan(inventory):
        return set()
    state = inventory.state
    if not state or not state.exists:
        return set()
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip().casefold() != "none":
        return set()
    if str(state_data.get("phase_status") or "").strip().casefold() != "complete":
        return set()
    decision_paths = {path for path in paths if _is_checkpoint_decision_route_path(path)}
    verification_paths = {path for path in paths if _is_verification_checkpoint_route_path(path)}
    if not decision_paths or not verification_paths or paths != decision_paths | verification_paths:
        return set()
    if not all(_is_reviewed_verification_decision_file(inventory, path, verification_paths) for path in decision_paths):
        return set()
    if not all(_is_reviewed_decision_backed_verification_checkpoint_file(inventory, path) for path in verification_paths):
        return set()
    return paths


def _coherent_deferred_route_package_checkpoint_paths(inventory: Inventory, paths: set[str]) -> set[str]:
    if _has_active_plan(inventory):
        return set()
    state = inventory.state
    if not state or not state.exists:
        return set()
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip().casefold() != "none":
        return set()
    if str(state_data.get("phase_status") or "").strip().casefold() != "complete":
        return set()
    research_paths = {path for path in paths if _is_deferred_research_route_path(path)}
    archive_paths = {path for path in paths if _is_deferred_archive_plan_route_path(path)}
    if not research_paths or not archive_paths or paths != research_paths | archive_paths:
        return set()
    if not all(_is_reviewed_deferred_research_route_file(inventory, path) for path in research_paths):
        return set()
    archive_sources: set[str] = set()
    for path in archive_paths:
        source_research = _reviewed_deferred_archive_plan_source_research(inventory, path)
        if not source_research:
            return set()
        archive_sources.add(source_research)
    if not archive_sources <= research_paths:
        return set()
    return paths


def _coherent_standalone_archive_plan_checkpoint_paths(inventory: Inventory, paths: set[str]) -> set[str]:
    if _has_active_plan(inventory):
        return set()
    state = inventory.state
    if not state or not state.exists:
        return set()
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip().casefold() != "none":
        return set()
    if str(state_data.get("phase_status") or "").strip().casefold() != "complete":
        return set()
    archive_paths = {path for path in paths if _is_deferred_archive_plan_route_path(path)}
    if not archive_paths or paths != archive_paths:
        return set()
    if not all(_is_reviewed_standalone_archive_plan_checkpoint_file(inventory, path) for path in archive_paths):
        return set()
    return paths


def _coherent_route_imported_research_checkpoint_paths(inventory: Inventory, paths: set[str]) -> set[str]:
    if _has_active_plan(inventory):
        return set()
    state = inventory.state
    if not state or not state.exists:
        return set()
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip().casefold() != "none":
        return set()
    if str(state_data.get("phase_status") or "").strip().casefold() != "complete":
        return set()
    research_paths = {path for path in paths if _is_deferred_research_route_path(path)}
    if not research_paths or paths != research_paths:
        return set()
    if not all(_is_reviewed_deferred_research_route_file(inventory, path) for path in research_paths):
        return set()
    return paths


def _coherent_roadmap_promotion_checkpoint_paths(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
    *,
    prefer_staged_content: bool = False,
) -> set[str]:
    state = inventory.state
    if not state or not state.exists:
        return set()
    if not _roadmap_promotion_checkpoint_posture_allows(inventory):
        return set()
    normalized = _normalized_route_produced_lifecycle_paths(inventory, paths)
    if not normalized:
        return set()
    roadmap_rel = "project/" + "roadmap.md"
    incubation_paths = {path for path in normalized if _is_meta_feedback_incubation_route_path(path)}
    if roadmap_rel not in normalized or not incubation_paths or normalized != incubation_paths | {roadmap_rel}:
        return set()
    if not all(
        _is_reviewed_roadmap_promoted_incubation_file(
            inventory,
            path,
            prefer_staged_content=prefer_staged_content,
        )
        for path in incubation_paths
    ):
        return set()
    return normalized


def _looks_like_roadmap_promotion_checkpoint_paths(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
) -> bool:
    normalized = _normalized_route_produced_lifecycle_paths(inventory, paths)
    if not normalized:
        return False
    roadmap_rel = "project/" + "roadmap.md"
    incubation_paths = {path for path in normalized if _is_meta_feedback_incubation_route_path(path)}
    return roadmap_rel in normalized and bool(incubation_paths) and normalized == incubation_paths | {roadmap_rel}


def _roadmap_promotion_checkpoint_posture_allows(inventory: Inventory) -> bool:
    state = inventory.state
    if not state or not state.exists:
        return False
    plan_status = str(state.frontmatter.data.get("plan_status") or "").strip().casefold()
    if plan_status == "none":
        return True
    if plan_status == "active":
        return _active_plan_ready_for_route_produced_lifecycle_git(inventory)
    return False


def _coherent_memory_hygiene_checkpoint_paths(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
    *,
    prefer_staged_content: bool = False,
) -> set[str]:
    if not _memory_hygiene_checkpoint_posture_allows(inventory):
        return set()
    normalized = _normalized_memory_hygiene_checkpoint_paths(inventory, paths)
    if not normalized:
        return set()
    archive_reference_paths = {
        path for path in normalized if _is_memory_hygiene_archive_reference_path(path)
    }
    operator_prompt_paths = {
        path for path in normalized if _is_memory_hygiene_operator_prompt_path(path)
    }
    if operator_prompt_paths:
        if archive_reference_paths:
            return set()
        incubation_paths = {path for path in normalized if _is_meta_feedback_incubation_route_path(path)}
        if not incubation_paths or normalized != operator_prompt_paths | incubation_paths:
            return set()
        missing_incubation_paths = {
            path
            for path in incubation_paths
            if not _memory_hygiene_checkpoint_file_exists(inventory, path)
        }
        if missing_incubation_paths != incubation_paths:
            return set()
        if not all(
            _is_reviewed_memory_hygiene_operator_prompt_file(inventory, path)
            for path in operator_prompt_paths
        ):
            return set()
        if any(
            not _has_operator_prompt_for_incubation_source(inventory, source_path, operator_prompt_paths)
            for source_path in incubation_paths
        ):
            return set()
        return normalized
    if not archive_reference_paths:
        return set()
    anchor_paths = {
        path
        for path in normalized
        if _is_deferred_archive_plan_route_path(path)
        or _is_deferred_research_route_path(path)
        or _is_memory_hygiene_verification_route_path(path)
    }
    if not anchor_paths:
        return set()
    incubation_paths = {path for path in normalized if _is_meta_feedback_incubation_route_path(path)}
    missing_incubation_paths = {
        path
        for path in incubation_paths
        if not _memory_hygiene_checkpoint_file_exists(inventory, path)
    }
    if any(
        not _has_archive_reference_for_incubation_source(inventory, source_path, archive_reference_paths)
        for source_path in missing_incubation_paths
    ):
        return set()
    existing_incubation_paths = incubation_paths - missing_incubation_paths
    if not all(
        _is_reviewed_memory_hygiene_incubation_file(inventory, path)
        for path in existing_incubation_paths
    ):
        return set()
    if not all(
        _is_reviewed_memory_hygiene_archive_reference_file(
            inventory,
            path,
            prefer_staged_content=prefer_staged_content,
        )
        for path in archive_reference_paths
    ):
        return set()
    archive_plan_paths = {path for path in normalized if _is_deferred_archive_plan_route_path(path)}
    if not all(
        _is_reviewed_memory_hygiene_archive_plan_file(inventory, path)
        for path in archive_plan_paths
    ):
        return set()
    research_paths = {path for path in normalized if _is_deferred_research_route_path(path)}
    if not all(
        _is_reviewed_deferred_research_route_file(inventory, path)
        for path in research_paths
    ):
        return set()
    verification_paths = {path for path in normalized if _is_memory_hygiene_verification_route_path(path)}
    if not all(
        _is_reviewed_memory_hygiene_verification_route_file(inventory, path)
        for path in verification_paths
    ):
        return set()
    return normalized


def _coherent_memory_hygiene_archive_reference_checkpoint_paths(
    inventory: Inventory,
    paths: list[str] | tuple[str, ...],
    *,
    prefer_staged_content: bool = False,
) -> set[str]:
    if not _memory_hygiene_checkpoint_posture_allows(inventory):
        return set()
    normalized = _normalized_memory_hygiene_checkpoint_paths(inventory, paths)
    if not normalized:
        return set()
    if not all(_is_memory_hygiene_archive_reference_path(path) for path in normalized):
        return set()
    if not all(
        _is_reviewed_memory_hygiene_archive_reference_file(
            inventory,
            path,
            prefer_staged_content=prefer_staged_content,
        )
        for path in normalized
    ):
        return set()
    return normalized


def _memory_hygiene_checkpoint_posture_allows(inventory: Inventory) -> bool:
    if _has_active_plan(inventory):
        return False
    state = inventory.state
    if not state or not state.exists:
        return False
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip().casefold() != "none":
        return False
    if str(state_data.get("phase_status") or "").strip().casefold() != "complete":
        return False
    return any(marker in state.content for marker in ROUTE_WRITEBACK_MARKERS)


def _normalized_memory_hygiene_checkpoint_paths(
    inventory: Inventory, paths: list[str] | tuple[str, ...]
) -> set[str]:
    normalized: set[str] = set()
    for path in paths:
        rel = _hook_route_rel_path(inventory, path)
        if not rel:
            return set()
        clean = _normalize_hook_path(rel).casefold()
        if clean in POST_CLOSEOUT_STAGE_BROAD_PATHS:
            return set()
        if any(char in clean for char in "*?[]"):
            return set()
        if clean.startswith(POST_CLOSEOUT_STAGE_DISALLOWED_PREFIXES):
            return set()
        if not _is_memory_hygiene_checkpoint_route_path(clean):
            return set()
        if not _memory_hygiene_checkpoint_file_exists(inventory, clean) and not _is_meta_feedback_incubation_route_path(clean):
            return set()
        normalized.add(clean)
    return normalized


def _memory_hygiene_checkpoint_file_exists(inventory: Inventory, path: str) -> bool:
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        return route_path.is_file() and not route_path.is_symlink()
    except (OSError, RuntimeError):
        return False


def _is_memory_hygiene_checkpoint_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return (
        _is_meta_feedback_incubation_route_path(rel)
        or _is_memory_hygiene_archive_reference_path(rel)
        or _is_deferred_archive_plan_route_path(rel)
        or _is_deferred_research_route_path(rel)
        or _is_memory_hygiene_verification_route_path(rel)
        or _is_memory_hygiene_operator_prompt_path(rel)
    )


def _is_memory_hygiene_archive_reference_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.startswith("project/archive/reference/incubation/") and rel.endswith(".md")


def _is_source_incubation_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return _is_meta_feedback_incubation_route_path(rel) or _is_memory_hygiene_archive_reference_path(rel)


def _is_memory_hygiene_verification_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.startswith("project/verification/") and rel.endswith((".md", ".json"))


def _is_memory_hygiene_operator_prompt_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    suffix = rel.removeprefix("project/operator-prompts/")
    return rel.startswith("project/operator-prompts/") and rel.endswith(".md") and "/" not in suffix


def _has_archive_reference_for_incubation_source(
    inventory: Inventory, source_path: str, archive_reference_paths: set[str]
) -> bool:
    source_rel = _normalize_hook_path(source_path).casefold()
    source_stem = Path(source_rel).stem.casefold()
    for archive_path in archive_reference_paths:
        route_path = _hook_route_file_path(inventory, archive_path)
        if route_path is None:
            continue
        try:
            text = route_path.read_text(encoding="utf-8")
            frontmatter = parse_frontmatter(text)
        except (OSError, UnicodeDecodeError):
            continue
        data = frontmatter.data if frontmatter.has_frontmatter and not frontmatter.errors else {}
        candidate_refs = {
            str(data.get("source_incubation") or ""),
            str(data.get("related_incubation") or ""),
            str(data.get("source_note") or ""),
            str(data.get("source") or ""),
        }
        normalized_refs = {_hook_route_rel_path(inventory, ref).casefold() for ref in candidate_refs if ref}
        if source_rel in normalized_refs:
            return True
        archive_stem = Path(archive_path).stem.casefold()
        if archive_stem == source_stem or archive_stem.endswith("-" + source_stem):
            return True
        if source_rel in text.casefold():
            return True
    return False


def _has_operator_prompt_for_incubation_source(
    inventory: Inventory, source_path: str, operator_prompt_paths: set[str]
) -> bool:
    source_rel = _normalize_hook_path(source_path).casefold()
    for operator_prompt_path in operator_prompt_paths:
        route_path = _hook_route_file_path(inventory, operator_prompt_path)
        if route_path is None:
            continue
        try:
            text = route_path.read_text(encoding="utf-8")
            frontmatter = parse_frontmatter(text)
        except (OSError, UnicodeDecodeError):
            continue
        data = frontmatter.data if frontmatter.has_frontmatter and not frontmatter.errors else {}
        candidate = _hook_route_rel_path(inventory, str(data.get("source_route") or "")).casefold()
        if candidate == source_rel:
            return True
    return False


def _is_reviewed_memory_hygiene_operator_prompt_file(inventory: Inventory, path: str) -> bool:
    if not _is_memory_hygiene_operator_prompt_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    data = frontmatter.data
    source_route = _hook_route_rel_path(inventory, str(data.get("source_route") or "")).casefold()
    authority = str(data.get("authority") or "").casefold()
    source_sha = str(data.get("source_sha256") or "").strip().casefold()
    proposal_token = str(data.get("proposal_token") or "").strip().casefold()
    return (
        str(data.get("schema") or "").strip() == "mylittleharness.prompt-artifact.v1"
        and str(data.get("status") or "").strip().casefold() == "active"
        and str(data.get("artifact_type") or "").strip().casefold() == "operator-prompt"
        and str(data.get("moved_by") or "").strip().casefold() == "memory-hygiene --move-non-incubation-prompt"
        and _is_meta_feedback_incubation_route_path(source_route)
        and re.fullmatch(r"[0-9a-f]{64}", source_sha) is not None
        and re.fullmatch(r"mhp-[0-9a-f]{16}", proposal_token) is not None
        and "does not approve" in authority
        and "lifecycle" in authority
        and "staging" in authority
        and "commit" in authority
    )


def _is_reviewed_memory_hygiene_archive_reference_file(
    inventory: Inventory,
    path: str,
    *,
    prefer_staged_content: bool = False,
) -> bool:
    if not _is_memory_hygiene_archive_reference_path(path):
        return False
    text = _route_file_text_for_checkpoint(inventory, path, prefer_staged_content=prefer_staged_content)
    if text is None:
        return False
    try:
        frontmatter = parse_frontmatter(text)
    except (TypeError, ValueError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    data = frontmatter.data
    source = str(data.get("source") or "").strip().casefold()
    status = str(data.get("status") or "").strip().casefold()
    archived_to = _hook_route_rel_path(inventory, str(data.get("archived_to") or "")).casefold()
    body = "\n".join(text.splitlines()[max(frontmatter.body_start_line - 1, 0) :]).casefold()
    has_route_refs = any(str(data.get(key) or "").strip() for key in ("related_plan", "archived_plan", "implemented_by"))
    has_entry_coverage = _has_archive_covered_entry_coverage(body)
    return (
        source == "mylittleharness incubation route"
        and status in {"implemented", "archived", "superseded", "rejected", "deferred"}
        and (not archived_to or archived_to == _normalize_hook_path(path).casefold())
        and (has_route_refs or has_entry_coverage)
        and "non-authority" in body
    )


def _has_archive_covered_entry_coverage(body: str) -> bool:
    content = str(body or "").casefold()
    if "## entry coverage" not in content:
        return False
    return bool(
        re.search(
            r"(?m)^-\s*`[^`\n]+`:\s*`(?:implemented|archived|superseded|rejected|deferred)`\s+"
            r"project/archive/plans/[^ \n]+\.md\b",
            content,
        )
    )


def _is_reviewed_memory_hygiene_incubation_file(inventory: Inventory, path: str) -> bool:
    if not _is_meta_feedback_incubation_route_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    data = frontmatter.data
    source = str(data.get("source") or "").strip().casefold()
    content = text.casefold()
    status = str(data.get("status") or "").strip().casefold()
    has_reconciliation_metadata = any(
        str(data.get(key) or "").strip()
        for key in ("lifecycle_status", "resolution", "last_reconciled", "resolved_by")
    )
    has_meta_feedback_evidence = (
        "mylittleharness-meta-feedback-cluster v1" in content
        or "meta-feedback intake fields" in content
        or "signal_type:" in content
    )
    return (
        source == "mylittleharness incubation route"
        and status in {"incubating", "implemented", "archived", "deferred", "rejected"}
        and (has_reconciliation_metadata or has_meta_feedback_evidence)
        and "non-authority" in content
        and has_meta_feedback_evidence
        and "lifecycle" in content
        and ("staging" in content or "commit" in content or "git" in content)
    )


def _is_reviewed_memory_hygiene_archive_plan_file(inventory: Inventory, path: str) -> bool:
    if not _is_deferred_archive_plan_route_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink() or route_path.suffix.casefold() != ".md":
            return False
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    data = frontmatter.data
    if str(data.get("status") or "").strip().casefold() != "complete":
        return False
    if str(data.get("phase_status") or "").strip().casefold() != "complete":
        return False
    if not str(data.get("plan_id") or "").strip() or not str(data.get("docs_decision") or "").strip():
        return False
    content = text.casefold()
    return (
        ("mylittleharness-closeout-writeback v1" in content or "commit_decision" in content or "residual_risk" in content)
        and ("cannot approve" in content or "does not approve" in content or "no lifecycle" in content or "no automatic" in content)
        and ("staging" in content or "commit" in content or "git" in content)
    )


def _is_reviewed_memory_hygiene_verification_route_file(inventory: Inventory, path: str) -> bool:
    if _verification_checkpoint_path_class(path):
        return _is_reviewed_verification_checkpoint_file(inventory, path)
    if not _is_memory_hygiene_verification_route_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        if route_path.suffix.casefold() == ".json":
            data = json.loads(route_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or _route_evidence_grants_authority(data):
                return False
            encoded = json.dumps(data, ensure_ascii=False, sort_keys=True).casefold()
            return bool(str(data.get("schema") or "").strip()) and _route_evidence_text_has_non_authority_boundary(encoded)
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if route_path.suffix.casefold() != ".md":
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    content = text.casefold()
    return _route_evidence_text_has_non_authority_boundary(content)


def _coherent_meta_feedback_checkpoint_paths(inventory: Inventory, paths: set[str]) -> set[str]:
    if not _lifecycle_posture_allows_meta_feedback_checkpoint_stage(inventory):
        return set()
    if not paths or any(not _is_meta_feedback_incubation_route_path(path) for path in paths):
        return set()
    if not all(_is_reviewed_meta_feedback_incubation_file(inventory, path) for path in paths):
        return set()
    return paths


def _is_checkpoint_decision_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.startswith("project/decisions/") and rel.endswith(".md")


def _is_verification_checkpoint_route_path(path: str) -> bool:
    return bool(_verification_checkpoint_path_class(path))


def _verification_checkpoint_path_class(path: str) -> str:
    rel = _normalize_hook_path(path).casefold()
    if _is_agent_run_evidence_route_path(rel):
        return "agent-runs"
    prefixes = {
        "project/verification/handoffs/": "handoffs",
        "project/verification/approval-packets/": "approval-packets",
        "project/verification/work-claims/": "work-claims",
        "project/verification/task-sessions/": "task-sessions",
        "project/verification/queue-runner-fixtures/": "queue-runner-fixtures",
    }
    for prefix, route_class in prefixes.items():
        if rel.startswith(prefix) and not rel.endswith("/"):
            return route_class
    return ""


def _is_reviewed_verification_decision_file(
    inventory: Inventory,
    path: str,
    verification_paths: set[str],
) -> bool:
    if not _is_checkpoint_decision_route_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    content = "\n".join(text.splitlines()[max(frontmatter.body_start_line - 1, 0) :]).casefold()
    route_classes = {
        route_class
        for route_class in (_verification_checkpoint_path_class(path) for path in verification_paths)
        if route_class
    }
    if not route_classes or any(route_class not in content for route_class in route_classes):
        return False
    has_checkpoint_scope = "checkpoint" in content and ("evidence-only" in content or "evidence only" in content)
    has_non_authority_boundary = (
        ("cannot approve" in content or "do not approve" in content or "do not grant" in content or "no lifecycle" in content)
        and "lifecycle" in content
        and ("git" in content or "stage" in content or "staging" in content or "commit" in content)
    )
    return has_checkpoint_scope and has_non_authority_boundary


def _is_reviewed_verification_checkpoint_file(inventory: Inventory, path: str) -> bool:
    route_class = _verification_checkpoint_path_class(path)
    if not route_class:
        return False
    if route_class == "agent-runs":
        return _is_reviewed_agent_run_evidence_file(inventory, path)
    if route_class == "approval-packets":
        return _is_reviewed_pending_approval_packet_file(inventory, path)
    if route_class == "queue-runner-fixtures":
        return _is_reviewed_queue_runner_fixture_file(inventory, path)
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink() or route_path.suffix.casefold() != ".json":
            return False
        data = json.loads(route_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    expected = {
        "handoffs": ("mylittleharness.handoff-packet.v1", "handoff-packet"),
        "work-claims": ("mylittleharness.work-claim.v1", "work-claim"),
        "task-sessions": ("mylittleharness.task-session.receipt.v1", "task-session-receipt"),
    }.get(route_class)
    if expected is None:
        return False
    schema, record_type = expected
    if str(data.get("schema") or "").strip() != schema:
        return False
    if str(data.get("record_type") or "").strip() != record_type:
        return False
    if _route_evidence_grants_authority(data):
        return False
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True).casefold()
    return _route_evidence_text_has_non_authority_boundary(encoded)


def _is_reviewed_pending_approval_packet_file(inventory: Inventory, path: str) -> bool:
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink() or route_path.suffix.casefold() != ".json":
            return False
        data = json.loads(route_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    if str(data.get("schema") or "").strip() != "mylittleharness.approval-packet.v1":
        return False
    if str(data.get("record_type") or "").strip() != "approval-packet":
        return False
    if str(data.get("status") or "").strip().casefold() != "pending":
        return False
    if not isinstance(data.get("human_gate_conditions"), list) or not data.get("human_gate_conditions"):
        return False
    if _route_evidence_grants_authority(data):
        return False
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True).casefold()
    return _route_evidence_text_has_non_authority_boundary(encoded)


def _is_reviewed_decision_checkpoint_artifact_file(inventory: Inventory, path: str) -> bool:
    if not _is_checkpoint_decision_route_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink() or route_path.suffix.casefold() != ".md":
            return False
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    if _route_frontmatter_grants_checkpoint_authority(frontmatter.data):
        return False
    content = text.casefold()
    route_value = str(frontmatter.data.get("route") or frontmatter.data.get("classification") or "").strip().casefold()
    source_value = str(frontmatter.data.get("source") or "").strip().casefold()
    has_route_ownership = route_value == "decisions" and (
        "intake_source" in frontmatter.data or "intake" in source_value or "mylittleharness" in source_value
    )
    has_checkpoint_or_prep_scope = (
        "decision-prep" in content
        or "design evidence" in content
        or "local savepoint" in content
        or "local checkpoint" in content
        or "local-only" in content
    )
    has_non_authority_boundary = (
        ("does not approve" in content or "cannot approve" in content or "do not approve" in content)
        and "lifecycle" in content
        and ("git" in content or "staging" in content or "commit" in content)
    )
    fabricates_approval = (
        "safe_to_continue_existing_sequence: true" in content
        or "owner approved" in content
        or "approved for lifecycle" in content
        or "approved for roadmap" in content
    )
    return has_route_ownership and has_checkpoint_or_prep_scope and has_non_authority_boundary and not fabricates_approval


def _is_reviewed_decision_backed_verification_checkpoint_file(inventory: Inventory, path: str) -> bool:
    if _is_reviewed_verification_checkpoint_file(inventory, path):
        return True
    if _verification_checkpoint_path_class(path) != "queue-runner-fixtures":
        return False
    return _is_decision_backed_queue_runner_fixture_file(inventory, path)


def _is_reviewed_queue_runner_fixture_file(inventory: Inventory, path: str) -> bool:
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        text = route_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    content = text.casefold()
    if not content.strip():
        return False
    has_safety_boundary = "no secrets" in content and "raw provider payload" in content
    has_explicit_proof = "queue runner" in content and "proof" in content
    has_scoped_write_smoke = (
        "smoke fixture" in content
        and "live scoped writer" in content
        and "applied write" in content
    )
    return has_safety_boundary and (has_explicit_proof or has_scoped_write_smoke)


def _is_decision_backed_queue_runner_fixture_file(inventory: Inventory, path: str) -> bool:
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        text = route_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    content = text.casefold()
    if not content.strip():
        return False
    return "queue runner" in content and "proof" in content


def _is_reviewed_post_closeout_archive_plan_file(inventory: Inventory, path: str) -> bool:
    if not _is_deferred_archive_plan_route_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink() or route_path.suffix.casefold() != ".md":
            return False
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    data = frontmatter.data
    if str(data.get("status") or "").strip().casefold() != "complete":
        return False
    if str(data.get("phase_status") or "").strip().casefold() != "complete":
        return False
    content = text.casefold()
    return (
        "mylittleharness-closeout-writeback v1" in content
        and "docs_decision" in content
        and "commit_decision" in content
        and "residual_risk" in content
    )


def _is_reviewed_standalone_archive_plan_checkpoint_file(inventory: Inventory, path: str) -> bool:
    if not _is_reviewed_post_closeout_archive_plan_file(inventory, path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return False
    plan_id = str(frontmatter.data.get("plan_id") or "").strip()
    if not plan_id or plan_id != Path(path).stem:
        return False
    archive_rel = _normalize_hook_path(path).casefold()
    content = text.casefold()
    archive_ref_markers = (
        f"archived_plan: {archive_rel}",
        f"archived_plan: `{archive_rel}`",
        f'archived_plan: "{archive_rel}"',
    )
    return "work_result" in content and any(marker in content for marker in archive_ref_markers)


def _roadmap_references_archived_plan(inventory: Inventory, archive_rel: str) -> bool:
    route_path = _hook_route_file_path(inventory, "project/" + "roadmap.md")
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        content = route_path.read_text(encoding="utf-8").casefold()
    except (OSError, UnicodeDecodeError):
        return False
    return _normalize_hook_path(archive_rel).casefold() in content


def _route_evidence_grants_authority(value: object) -> bool:
    authority_keys = {
        "archive",
        "approves_lifecycle",
        "closeout",
        "external_runtime_approves_lifecycle",
        "fan_in",
        "git",
        "lifecycle",
        "private_trace_authoritative",
        "private_traces_authoritative",
        "provider_routing",
        "provider_routing_authority",
        "release",
        "roadmap",
        "route_proposal",
        "staging",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.strip().casefold() in authority_keys and item is True:
                return True
            if _route_evidence_grants_authority(item):
                return True
    elif isinstance(value, list):
        return any(_route_evidence_grants_authority(item) for item in value)
    return False


def _route_evidence_text_has_non_authority_boundary(text: str) -> bool:
    content = text.casefold()
    return (
        (
            "cannot approve" in content
            or "does not approve" in content
            or "does not prove" in content
            or "do not approve" in content
            or "do not grant" in content
            or "cannot" in content
        )
        and ("lifecycle" in content or "roadmap" in content)
        and ("git" in content or "stage" in content or "staging" in content or "commit" in content)
    )


def _route_evidence_text_has_safe_release_boundary(text: str) -> bool:
    if _route_evidence_text_has_release_authorizing_claim(text):
        return False
    content = text.casefold()
    return (
        "no push" in content
        or "approval before" in content
        or "owner gate" in content
    ) and any(term in content for term in ("push", "tag", "publish", "artifact upload", "release claim"))


def _route_evidence_text_has_release_authorizing_claim(text: str) -> bool:
    content = text.casefold()
    release_term = r"(?:push|tag|publish|artifact upload|release claim)"
    if not re.search(rf"\b{release_term}\b", content):
        return False
    if re.search(
        r"\b(?:owner decision|owner gate|owner approval|approval packet|release decision)\s+"
        r"(?:has\s+)?"
        r"(?:approves|approved|authorizes|authorized|grants|granted|allows|allowed|permits|permitted|clears|cleared|greenlights|greenlit)\b",
        content,
    ):
        return True
    if re.search(
        rf"\b(?:approves|authorizes|grants|allows|permits|clears|greenlights)\b[^\n.]*\b{release_term}\b",
        content,
    ):
        return True
    if re.search(
        rf"\b(?:approved|authorized|granted|allowed|permitted|cleared|greenlit) for\b[^\n.]*\b{release_term}\b",
        content,
    ):
        return not re.search(
            r"\b(?:not|never|no)\s+(?:approved|authorized|granted|allowed|permitted|cleared|greenlit) for\b",
            content,
        )
    if re.search(
        rf"\b{release_term}\b\s+"
        r"(?:is|are|was|were|has\s+been|have\s+been)\s+"
        r"(?!(?:not|never|no)\b)"
        r"(?:approved|authorized|granted|allowed|permitted|cleared|greenlit)\s+"
        r"(?:by|via|from)\s+"
        r"(?:owner decision|owner gate|owner approval|approval packet|release decision)\b",
        content,
    ):
        return True
    return False


def _is_meta_feedback_incubation_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.startswith("project/plan-incubation/") and rel.endswith(".md")


def _is_reviewed_meta_feedback_incubation_file(inventory: Inventory, path: str) -> bool:
    if not _is_meta_feedback_incubation_route_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    data = frontmatter.data
    source = str(data.get("source") or "").strip().casefold()
    body = "\n".join(text.splitlines()[max(frontmatter.body_start_line - 1, 0) :])
    content = body.casefold()
    has_route_provenance = source == "mylittleharness incubation route" or "source: mylittleharness incubation route" in content
    has_meta_feedback_cluster = "mylittleharness-meta-feedback-cluster v1" in content
    has_fix_candidate = "[mlh-fix-candidate" in content
    has_hook_blocker_scope = ("hook" in content or "route" in content) and any(
        marker in content
        for marker in (
            "overblock",
            "blocked_surface",
            "blocked progress",
            "blocked by codex",
            "false_positive_shape",
        )
    )
    has_boundary = (
        "safe_boundary" in content
        or "authority_boundary" in content
        or (("cannot approve" in content or "no approval" in content) and "lifecycle" in content)
    )
    has_minimal_route_guardrail = any(
        marker in content
        for marker in (
            "preserving blocks",
            "while preserving",
            "direct lifecycle markdown edits",
            "broad staging remains blocked",
            "direct lifecycle",
        )
    )
    has_route_created_rough_edge_evidence = (
        ("route-created" in content or "mlh-created" in content or "mylittleharness incubation route" in content)
        and ("rough-edge" in content or "fix-candidate" in content)
        and ("blocked" in content or "overblock" in content)
    )
    return (
        has_route_provenance
        and has_fix_candidate
        and has_hook_blocker_scope
        and ((has_meta_feedback_cluster and has_boundary) or has_minimal_route_guardrail or has_route_created_rough_edge_evidence)
    )


def _is_reviewed_meta_feedback_checkpoint_stage_file(inventory: Inventory, path: str) -> bool:
    if not _lifecycle_posture_allows_meta_feedback_checkpoint_stage(inventory):
        return False
    return _is_reviewed_meta_feedback_incubation_file(inventory, path)


def _lifecycle_posture_allows_meta_feedback_checkpoint_stage(inventory: Inventory) -> bool:
    state = inventory.state
    if not state or not state.exists:
        return False
    state_data = state.frontmatter.data
    phase_status = str(state_data.get("phase_status") or "").strip().casefold()
    plan_status = str(state_data.get("plan_status") or "").strip().casefold()
    if plan_status == "none":
        return phase_status == "complete"
    if plan_status == "active" and _has_active_plan(inventory):
        return phase_status in ROUTE_PRODUCED_LIFECYCLE_PHASE_STATUSES and any(
            marker in state.content for marker in ROUTE_WRITEBACK_MARKERS
        )
    return False


def _is_reviewed_roadmap_promoted_incubation_file(
    inventory: Inventory,
    path: str,
    *,
    prefer_staged_content: bool = False,
) -> bool:
    data = _reviewed_mlh_incubation_file_frontmatter(
        inventory,
        path,
        prefer_staged_content=prefer_staged_content,
    )
    if data is None:
        return False
    if _incubation_frontmatter_confirms_roadmap_promotion(data):
        return True
    return _roadmap_item_references_promoted_incubation(
        inventory,
        path,
        prefer_staged_content=prefer_staged_content,
    )


def _reviewed_mlh_incubation_file_frontmatter(
    inventory: Inventory,
    path: str,
    *,
    prefer_staged_content: bool = False,
) -> dict[str, object] | None:
    if not _is_source_incubation_route_path(path):
        return None
    text = _route_file_text_for_checkpoint(
        inventory,
        path,
        prefer_staged_content=prefer_staged_content,
    )
    if text is None:
        return None
    try:
        frontmatter = parse_frontmatter(text)
    except ValueError:
        return None
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return None
    data = frontmatter.data
    source = str(data.get("source") or "").strip().casefold()
    if source != "mylittleharness incubation route":
        return None
    return data


def _incubation_frontmatter_confirms_roadmap_promotion(data: dict[str, object]) -> bool:
    related_roadmap = _normalize_hook_path(str(data.get("related_roadmap") or "")).casefold()
    related_item = str(data.get("related_roadmap_item") or "").strip()
    promoted_to = _normalize_hook_path(str(data.get("promoted_to") or "")).casefold()
    return (
        related_roadmap == "project/roadmap.md"
        and bool(related_item)
        and promoted_to == "project/roadmap.md"
    )


def _roadmap_item_references_promoted_incubation(
    inventory: Inventory,
    path: str,
    *,
    prefer_staged_content: bool = False,
) -> bool:
    text = _route_file_text_for_checkpoint(
        inventory,
        "project/roadmap.md",
        prefer_staged_content=prefer_staged_content,
    )
    if text is None:
        return False
    try:
        from .roadmap import _field_list, _field_scalar, _parse_roadmap_items_for_sync
    except ImportError:
        return False
    parse_result = _parse_roadmap_items_for_sync(text)
    (_start, _end, items), errors = parse_result
    if errors:
        return False
    target = _normalize_hook_path(path).casefold()
    for item in items.values():
        fields = item.fields
        status = _field_scalar(fields, "status").strip().casefold()
        if status not in {"accepted", "active", "done"}:
            continue
        refs = {
            _normalize_hook_path(_field_scalar(fields, "source_incubation")).casefold(),
            _normalize_hook_path(_field_scalar(fields, "related_incubation")).casefold(),
        }
        refs.update(_normalize_hook_path(value).casefold() for value in _field_list(fields, "source_members"))
        refs.discard("")
        if target in refs:
            return True
    return False


def _route_file_text_for_checkpoint(
    inventory: Inventory,
    path: str,
    *,
    prefer_staged_content: bool = False,
) -> str | None:
    clean = _normalize_hook_path(path)
    if prefer_staged_content:
        return _git_staged_file_text_for_root(inventory.root, clean)
    route_path = _hook_route_file_path(inventory, clean)
    if route_path is None:
        return None
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return None
        return route_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _is_reviewed_post_closeout_source_incubation_file(inventory: Inventory, path: str, archive_rel: str) -> bool:
    if not _is_reviewed_roadmap_promoted_incubation_file(inventory, path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    body = "\n".join(text.splitlines()[max(frontmatter.body_start_line - 1, 0) :]).casefold()
    if "mylittleharness-meta-feedback-cluster v1" not in body:
        return False
    if "[mlh-fix-candidate" not in body:
        return False
    has_boundary = (
        "safe_boundary" in body
        or "authority_boundary" in body
        or "non-authority" in body
        or "cannot approve" in body
    )
    if not has_boundary:
        return False
    data = frontmatter.data
    expected_archive = _normalize_hook_path(archive_rel).casefold()
    if _is_reviewed_post_closeout_source_incubation_retarget(data, expected_archive):
        return True
    relationship_fields = ("related_plan", "archived_plan", "implemented_by")
    if any(_normalize_hook_path(str(data.get(field) or "")).casefold() != expected_archive for field in relationship_fields):
        return False
    docs_decision = str(data.get("docs_decision") or "").strip().casefold()
    verification_summary = str(data.get("verification_summary") or "").strip()
    return docs_decision in {"updated", "not-needed", "uncertain"} and bool(verification_summary)


def _is_reviewed_post_closeout_source_incubation_retarget(data: dict[str, object], expected_archive: str) -> bool:
    related_plan = _normalize_hook_path(str(data.get("related_plan") or "")).casefold()
    if related_plan != expected_archive:
        return False
    for field in ("archived_plan", "implemented_by"):
        value = _normalize_hook_path(str(data.get(field) or "")).casefold()
        if value and value != expected_archive:
            return False
    return True


def _incubation_frontmatter_declares_archive_plan_relationship(data: dict[str, object]) -> bool:
    for field in ("archived_plan", "implemented_by"):
        if _normalize_hook_path(str(data.get(field) or "")).casefold():
            return True
    related_plan = _normalize_hook_path(str(data.get("related_plan") or "")).casefold()
    return related_plan.startswith("project/archive/plans/")


def _reviewed_local_vcs_checkpoint_rejection_reason(inventory: Inventory, paths: list[str] | tuple[str, ...], label: str) -> str:
    shapes = (
        "active-route-closeout,post-closeout-finalization,agent-run-evidence-only,"
        "post-closeout-route-package,worker-run-receipt-refs,retention-receipt-refs,verification/decision-evidence-package,"
        "deferred-research/archive-package,memory-hygiene/archive-reference-package,"
        "roadmap-promotion-package,post-closeout-source-incubation-relationship-package,"
        "meta-feedback/incubation-blocker-notes,route-owned-decision-artifacts,delegated-neighbor-exact-files,"
        "delegated-neighbor-bootstrap-scaffold"
    )
    normalized = _normalized_route_produced_lifecycle_paths(inventory, paths)
    if not normalized:
        normalized = _normalized_post_closeout_lifecycle_route_checkpoint_paths(inventory, paths)
    if not normalized:
        return (
            f"the {label} include missing, broad, wildcard, directory, generated/runtime, non-MLH-route, "
            "or unreviewed active-plan tombstone "
            f"files in the actual command root; considered_shapes={shapes}; next_safe=split exact route files, "
            "rerun a checkpoint dry-run or evidence/meta-feedback blocker packet, then retry exact local-only staging"
        )
    classes = _reviewed_local_vcs_checkpoint_path_classes(normalized)
    return (
        f"the {label} are not a coherent reviewed lifecycle/evidence route set in the actual command root; "
        f"path_classes={classes}; considered_shapes={shapes}; next_safe=split the checkpoint group, include "
        "required route anchors/receipt refs, or record a checkpoint dry-run or evidence/meta-feedback blocker packet"
    )


def _reviewed_local_vcs_checkpoint_path_classes(paths: set[str]) -> str:
    classes: list[str] = []
    if any(path == "project/project-state.md" for path in paths):
        classes.append("state")
    if any(path == "project/roadmap.md" for path in paths):
        classes.append("roadmap")
    if any(path.startswith("project/archive/plans/") for path in paths):
        classes.append("archive-plans")
    if any(_is_agent_run_evidence_route_path(path) for path in paths):
        classes.append("agent-run-evidence")
    if any(_is_worker_run_receipt_route_path(path) for path in paths):
        classes.append("worker-run-receipts")
    if any(_is_retention_receipt_route_path(path) for path in paths):
        classes.append("retention-receipts")
    if any(_is_checkpoint_decision_route_path(path) for path in paths):
        classes.append("decisions")
    verification_classes = sorted(
        {
            route_class
            for route_class in (_verification_checkpoint_path_class(path) for path in paths)
            if route_class
        }
    )
    classes.extend(verification_classes)
    if any(_is_deferred_research_route_path(path) for path in paths):
        classes.append("research")
    if any(_is_memory_hygiene_archive_reference_path(path) for path in paths):
        classes.append("archive-reference")
    if any(_is_meta_feedback_incubation_route_path(path) for path in paths):
        classes.append("incubation")
    if len(classes) == 0:
        classes.append("other-route")
    return ",".join(classes)


def _is_deferred_research_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.startswith("project/research/") and rel.endswith(".md")


def _is_deferred_archive_plan_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.startswith("project/archive/plans/") and rel.endswith(".md")


def _is_reviewed_deferred_research_route_file(inventory: Inventory, path: str) -> bool:
    if not _is_deferred_research_route_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    data = frontmatter.data
    status = str(data.get("status") or "").strip().casefold()
    title = str(data.get("title") or "").strip()
    derived_from = str(data.get("derived_from") or "").strip().casefold()
    content = "\n".join(text.splitlines()[max(frontmatter.body_start_line - 1, 0) :]).casefold()
    return (
        status == "imported"
        and bool(title)
        and ("research-import" in derived_from or "research-import" in content)
        and "cannot approve" in content
        and "lifecycle" in content
        and ("staging" in content or "commit" in content or "vcs" in content)
    )


def _reviewed_deferred_archive_plan_source_research(inventory: Inventory, path: str) -> str:
    if not _is_deferred_archive_plan_route_path(path):
        return ""
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return ""
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return ""
        text = route_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError):
        return ""
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return ""
    data = frontmatter.data
    if str(data.get("status") or "").strip().casefold() != "complete":
        return ""
    if str(data.get("phase_status") or "").strip().casefold() != "complete":
        return ""
    if not str(data.get("plan_id") or "").strip():
        return ""
    source_research = _hook_route_rel_path(inventory, str(data.get("source_research") or "")).casefold()
    if not _is_deferred_research_route_path(source_research):
        return ""
    content = "\n".join(text.splitlines()[max(frontmatter.body_start_line - 1, 0) :]).casefold()
    if "cannot approve" not in content or "lifecycle" not in content:
        return ""
    return source_research


def _is_reviewed_agent_run_evidence_file(inventory: Inventory, path: str) -> bool:
    if not _is_agent_run_evidence_route_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return False
        frontmatter = parse_frontmatter(route_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    data = frontmatter.data
    return (
        str(data.get("schema") or "").strip() == "mylittleharness.agent-run.v1"
        and str(data.get("record_type") or "").strip() == "agent-run"
        and bool(str(data.get("status") or "").strip())
    )


def _is_worker_run_receipt_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.startswith("project/verification/worker-run-receipts/") and rel.endswith(".json")


def _reviewed_worker_run_receipt_checkpoint_refs(inventory: Inventory, path: str) -> set[str]:
    if not _is_worker_run_receipt_route_path(path):
        return set()
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return set()
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return set()
        data = json.loads(route_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    if str(data.get("schema") or "").strip() != "mylittleharness.worker-run-receipt.v1":
        return set()
    if str(data.get("record_type") or "").strip() != "worker-run-receipt":
        return set()
    non_authority = str(data.get("non_authority") or "").casefold()
    if "cannot approve" not in non_authority or "lifecycle" not in non_authority or "git" not in non_authority:
        return set()
    if data.get("private_trace_authoritative") is True:
        return set()
    event_history = data.get("event_history")
    if isinstance(event_history, dict) and event_history.get("approves_lifecycle") is True:
        return set()
    private_traces = data.get("private_traces")
    if isinstance(private_traces, dict) and private_traces.get("private_traces_authoritative") is True:
        return set()
    allowed = {_hook_route_rel_path(inventory, path).casefold()}
    for field in ("event_stream_refs", "event_history_refs", "verification_refs"):
        value = data.get(field)
        if not isinstance(value, list):
            continue
        for item in value:
            rel = _hook_route_rel_path(inventory, str(item or "")).casefold()
            if rel.startswith("project/verification/") and _is_existing_lifecycle_route_file(inventory, rel):
                allowed.add(rel)
    return allowed


def _is_retention_receipt_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.startswith("project/verification/retention-receipts/") and rel.endswith(".json")


def _reviewed_retention_receipt_checkpoint_refs(inventory: Inventory, path: str) -> set[str]:
    if not _is_retention_receipt_route_path(path):
        return set()
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return set()
    try:
        if not route_path.is_file() or route_path.is_symlink():
            return set()
        data = json.loads(route_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    if str(data.get("schema") or "").strip() != "mylittleharness.retention-receipt.v1":
        return set()
    if str(data.get("record_type") or "").strip() != "retention-receipt":
        return set()
    if str(data.get("action") or "").strip() not in {"retire", "tombstone", "purge"}:
        return set()
    non_authority = str(data.get("non_authority") or "").casefold()
    if "cannot approve" not in non_authority or "lifecycle" not in non_authority or "git" not in non_authority:
        return set()
    allowed = {_hook_route_rel_path(inventory, path).casefold()}
    for field in ("target_paths", "tombstone_paths", "purge_paths"):
        value = data.get(field)
        if not isinstance(value, list):
            continue
        for item in value:
            rel = _hook_route_rel_path(inventory, str(item or "")).casefold()
            if rel.startswith("project/verification/") and _is_existing_lifecycle_route_file(inventory, rel):
                allowed.add(rel)
    summary = _hook_route_rel_path(inventory, str(data.get("retirement_summary") or "")).casefold()
    if summary == "project/verification/agent-run-retirement-summary.md" and _is_existing_lifecycle_route_file(inventory, summary):
        allowed.add(summary)
    return allowed


def _normalized_route_produced_lifecycle_paths(inventory: Inventory, paths: list[str] | tuple[str, ...]) -> set[str]:
    normalized: set[str] = set()
    for path in paths:
        rel = _hook_route_rel_path(inventory, path)
        if not rel or not _is_existing_lifecycle_route_file(inventory, rel):
            return set()
        clean = _normalize_hook_path(rel).casefold()
        if clean in POST_CLOSEOUT_STAGE_BROAD_PATHS:
            return set()
        if any(char in clean for char in "*?[]"):
            return set()
        if clean.startswith(POST_CLOSEOUT_STAGE_DISALLOWED_PREFIXES):
            return set()
        normalized.add(clean)
    return normalized


def _normalized_post_closeout_lifecycle_route_checkpoint_paths(
    inventory: Inventory, paths: list[str] | tuple[str, ...]
) -> set[str]:
    normalized: set[str] = set()
    for path in paths:
        rel = _hook_route_rel_path(inventory, path)
        clean = _normalize_hook_path(rel).casefold() if rel else ""
        if not clean:
            return set()
        if clean in POST_CLOSEOUT_STAGE_BROAD_PATHS:
            return set()
        if any(char in clean for char in "*?[]"):
            return set()
        if clean.startswith(POST_CLOSEOUT_STAGE_DISALLOWED_PREFIXES):
            return set()
        if _is_existing_lifecycle_route_file(inventory, rel):
            normalized.add(clean)
            continue
        if _is_post_closeout_active_plan_tombstone_path(inventory, clean):
            normalized.add(clean)
            continue
        if _is_post_closeout_source_incubation_tombstone_path(inventory, clean):
            normalized.add(clean)
            continue
        return set()
    return normalized


def _is_post_closeout_active_plan_tombstone_path(inventory: Inventory, path: str) -> bool:
    rel = _hook_route_rel_path(inventory, path)
    clean = _normalize_hook_path(rel).casefold() if rel else ""
    if clean != ACTIVE_PLAN_ROUTE_PATH:
        return False
    if _has_active_plan(inventory):
        return False
    state = inventory.state
    if not state or not state.exists:
        return False
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip().casefold() != "none":
        return False
    if str(state_data.get("phase_status") or "").strip().casefold() != "complete":
        return False
    if _is_existing_lifecycle_route_file(inventory, clean):
        return False
    return _git_reports_deleted_path_for_root(inventory.root, clean)


def _is_post_closeout_source_incubation_tombstone_path(
    inventory: Inventory, path: str, archive_reference_paths: set[str] | None = None
) -> bool:
    rel = _hook_route_rel_path(inventory, path)
    clean = _normalize_hook_path(rel).casefold() if rel else ""
    if not _is_meta_feedback_incubation_route_path(clean):
        return False
    if _is_existing_lifecycle_route_file(inventory, clean):
        return False
    if not _git_reports_deleted_path_for_root(inventory.root, clean):
        return False
    if archive_reference_paths is None:
        return True
    return _has_archive_reference_for_incubation_source(inventory, clean, archive_reference_paths)


def _active_plan_rel_path(inventory: Inventory) -> str:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return _normalize_hook_path(str(state.get("active_plan") or "")).casefold()


def _last_archived_plan_rel_path(inventory: Inventory) -> str:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return _last_archived_plan_rel_path_from_data(state)


def _last_archived_plan_rel_path_from_data(data: dict[str, object]) -> str:
    return _normalize_hook_path(str(data.get("last_archived_plan") or "")).casefold()


def _git_staged_paths(inventory: Inventory) -> tuple[str, ...]:
    return _git_staged_paths_for_root(inventory.root)


def _git_staged_paths_for_root(root: Path) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--name-only"],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if result.returncode != 0:
        return ()
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _git_staged_file_text_for_root(root: Path, rel_path: str) -> str | None:
    clean = _normalize_hook_path(rel_path).casefold()
    if not clean or any(char in clean for char in "*?[]"):
        return None
    result = _run_git_for_root(root, "show", f":{clean}")
    if result is None or result.returncode != 0:
        return None
    return result.stdout


def _git_reports_deleted_path_for_root(root: Path, rel_path: str) -> bool:
    clean = _normalize_hook_path(rel_path).casefold()
    if not clean or any(char in clean for char in "*?[]"):
        return False
    try:
        status_result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--", clean],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        status_result = None
    if status_result is not None and status_result.returncode == 0:
        for line in status_result.stdout.splitlines():
            if "D" in line[:2]:
                return True
    try:
        diff_result = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--name-status", "--", clean],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if diff_result.returncode != 0:
        return False
    return any(line.split(maxsplit=1)[0] == "D" for line in diff_result.stdout.splitlines() if line.strip())


def _git_stage_pathspecs(command: str) -> list[str]:
    subcommand, tokens, raw_tokens, subcommand_index = _git_command_context_tokens(command)
    if subcommand not in {"add", "stage"} or subcommand_index < 0:
        return []
    pathspecs: list[str] = []
    option_mode = True
    for token, raw_token in zip(tokens[subcommand_index + 1 :], raw_tokens[subcommand_index + 1 :]):
        clean = _clean_token(token)
        if not clean:
            continue
        if _is_shell_command_separator(raw_token, clean):
            return []
        if clean == "--":
            option_mode = False
            continue
        if option_mode and clean.startswith("-"):
            if clean in GIT_STAGE_EXACT_PATHSPEC_OPTIONS:
                continue
            return []
        if clean in POST_CLOSEOUT_STAGE_BROAD_PATHS:
            pathspecs.append(clean)
            continue
        pathspec = _clean_hook_path_token(str(raw_token))
        if pathspec:
            pathspecs.append(pathspec)
    return pathspecs


def _is_exact_post_closeout_stage_file(
    inventory: Inventory,
    pathspec: str,
    *,
    base_root: Path | None = None,
    boundary_root: Path | None = None,
) -> bool:
    clean = _clean_hook_path_token(pathspec)
    if not clean:
        return False
    rel = _normalize_hook_path(clean).casefold()
    if rel in POST_CLOSEOUT_STAGE_BROAD_PATHS:
        return False
    if any(char in rel for char in "*?[]"):
        return False
    if rel.startswith(":") or any(rel.startswith(prefix) for prefix in POST_CLOSEOUT_STAGE_DISALLOWED_PREFIXES):
        return False
    if _is_top_level_verification_checkpoint_path(rel):
        return _is_reviewed_top_level_verification_checkpoint_file(inventory, rel)
    raw = clean
    try:
        unresolved_target = Path(raw).expanduser()
        if not unresolved_target.is_absolute():
            unresolved_target = (base_root or inventory.root) / unresolved_target
        if unresolved_target.is_symlink():
            return False
        target = unresolved_target.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    boundary = boundary_root or inventory.root
    try:
        target.relative_to(boundary.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    try:
        return target.is_file() and not target.is_symlink()
    except (OSError, RuntimeError):
        return False


def _is_top_level_verification_checkpoint_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    if not rel.startswith("project/verification/") or not rel.endswith(".md"):
        return False
    return "/" not in rel.removeprefix("project/verification/")


def _is_reviewed_top_level_verification_checkpoint_file(inventory: Inventory, path: str) -> bool:
    if not _is_top_level_verification_checkpoint_path(path):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        if not route_path.is_file() or route_path.is_symlink() or route_path.suffix.casefold() != ".md":
            return False
        text = route_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return _is_reviewed_top_level_verification_checkpoint_text(inventory, path, text)


def _is_reviewed_staged_top_level_verification_checkpoint_file(inventory: Inventory, path: str) -> bool:
    if not _is_top_level_verification_checkpoint_path(path):
        return False
    text = _git_staged_file_text_for_root(inventory.root, path)
    if text is None:
        return False
    return _is_reviewed_top_level_verification_checkpoint_text(inventory, path, text)


def _is_reviewed_top_level_verification_checkpoint_text(
    inventory: Inventory, path: str, text: str
) -> bool:
    if not _is_top_level_verification_checkpoint_path(path):
        return False
    try:
        frontmatter = parse_frontmatter(text)
    except (TypeError, ValueError):
        return False
    if not frontmatter.has_frontmatter or frontmatter.errors:
        return False
    data = frontmatter.data
    if _route_frontmatter_grants_checkpoint_authority(data):
        return False
    if _route_evidence_text_has_release_authorizing_claim(text):
        return False
    if _verification_checkpoint_has_unreviewed_incubation_source_member(inventory, data):
        return False
    if _route_evidence_text_has_safe_release_boundary(text):
        if str(data.get("route") or "").strip().casefold() != "verification":
            return False
        return _verification_checkpoint_has_only_reviewed_archive_source_members(inventory, data)
    return _route_evidence_text_has_non_authority_boundary(text)


def _verification_checkpoint_has_only_reviewed_archive_source_members(
    inventory: Inventory, data: dict[str, object]
) -> bool:
    source_members = data.get("source_members")
    if not isinstance(source_members, list):
        return False
    normalized_members = [
        _hook_route_rel_path(inventory, str(member or "")).casefold()
        for member in source_members
        if str(member or "").strip()
    ]
    if not normalized_members:
        return False
    return all(_is_reviewed_memory_hygiene_archive_reference_file(inventory, member) for member in normalized_members)


def _verification_checkpoint_has_unreviewed_incubation_source_member(
    inventory: Inventory, data: dict[str, object]
) -> bool:
    source_members = data.get("source_members")
    if not isinstance(source_members, list):
        return "source_members" in data
    for member in source_members:
        if not isinstance(member, str) or not member.strip():
            return True
        raw = member.strip()
        if _source_member_route_token_is_malformed(raw):
            return True
        clean = _hook_route_rel_path(inventory, raw).casefold()
        if not clean:
            return True
        if _is_meta_feedback_incubation_route_path(clean):
            return True
        if _is_memory_hygiene_archive_reference_path(clean) and not _is_reviewed_memory_hygiene_archive_reference_file(
            inventory, clean
        ):
            return True
    return False


def _source_member_route_token_is_malformed(raw: str) -> bool:
    normalized = _normalize_hook_path(raw).casefold()
    if normalized.startswith(("{", "[")):
        return True
    first_segment = normalized.split("/", 1)[0]
    return ":" in first_segment


def _route_frontmatter_grants_checkpoint_authority(data: dict[str, object]) -> bool:
    authority_keys = {
        "archive",
        "authority",
        "closeout",
        "commit",
        "git",
        "lifecycle",
        "provider_routing",
        "release",
        "roadmap",
        "staging",
    }
    for key, value in data.items():
        if str(key or "").strip().casefold() not in authority_keys and not str(key or "").strip().casefold().startswith("approves_"):
            continue
        if value is False:
            continue
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()
        if not _route_evidence_text_has_non_authority_boundary(encoded):
            return True
    return False


def _has_shell_command_separator(command: str) -> bool:
    for token in _shell_tokens(command):
        clean = _clean_token(token)
        if _is_shell_command_separator(token, clean):
            return True
    return False


def _shell_command_segments(command: str) -> list[str]:
    segments: list[str] = []
    for line in str(command or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        current: list[str] = []
        for token in _shell_tokens(line):
            clean = _clean_token(token)
            if _is_shell_command_separator(token, clean):
                stripped = str(token or "").strip()
                if stripped.endswith(";") and stripped.strip(" ;"):
                    current.append(stripped.rstrip(";"))
                if current:
                    segments.append(" ".join(current))
                    current = []
                continue
            current.append(token)
        if current:
            segments.append(" ".join(current))
    return [segment for segment in segments if segment.strip()]


def _git_subcommand(command: str) -> str:
    return _git_command_context(command)[0]


def _git_command_context(command: str) -> tuple[str, list[str], int]:
    subcommand, tokens, _raw_tokens, subcommand_index = _git_command_context_tokens(command)
    return subcommand, tokens, subcommand_index


def _git_command_context_tokens(command: str) -> tuple[str, list[str], list[str], int]:
    token_pairs = [(raw, _clean_token(raw)) for raw in _shell_tokens(command)]
    token_pairs = [(raw, clean) for raw, clean in token_pairs if clean]
    raw_tokens = [raw for raw, _clean in token_pairs]
    tokens = [clean for _raw, clean in token_pairs]
    for index, token in enumerate(tokens):
        if not _is_git_executable_token(token):
            continue
        subcommand_index = _git_subcommand_index_after_options(tokens, index + 1)
        if subcommand_index >= 0:
            return tokens[subcommand_index], tokens, raw_tokens, subcommand_index
    return "", tokens, raw_tokens, -1


def _clean_git_commit_option_token(token: str) -> str:
    clean = str(token or "").strip(" \t\r\n\"'`{}[](),;")
    if clean.startswith("--"):
        return clean.casefold()
    return clean


def _git_subcommand_after_options(tokens: list[str], start: int) -> str:
    index = _git_subcommand_index_after_options(tokens, start)
    return tokens[index] if index >= 0 else ""


def _git_subcommand_index_after_options(tokens: list[str], start: int) -> int:
    index = start
    while index < len(tokens):
        token = tokens[index]
        if not token:
            index += 1
            continue
        if token == "-c":
            index += 2
            continue
        if token in GIT_OPTIONS_WITH_VALUES:
            index += 2
            continue
        if any(token.startswith(option + "=") for option in GIT_OPTIONS_WITH_VALUES if option.startswith("--")):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return index
    return -1


def _is_git_executable_token(token: str) -> bool:
    clean = _clean_token(token)
    return clean in {"git", "git.exe"} or Path(clean).name in {"git", "git.exe"}


def _is_read_only_roadmap_direct_read_command(command: str, paths: list[str]) -> bool:
    if _looks_like_write_command(command):
        return False
    tokens = _shell_tokens(command)
    command_token = ""
    for token in tokens:
        clean = _clean_token(token)
        if not clean or clean.startswith("-"):
            continue
        command_token = clean
        break
    if command_token != "get-content":
        return False
    return bool(paths) and all(_is_roadmap_path(path) for path in paths)


def _active_plan_roadmap_policy_relevant(inventory: Inventory, command: str, paths: list[str]) -> bool:
    if not _has_active_plan(inventory):
        return False
    lowered = command.casefold()
    subcommand = _mlh_cli_subcommand(lowered)
    if subcommand in {"roadmap", "meta-feedback", "incubate", "plan", "writeback", "transition"}:
        return True
    if any(_is_roadmap_path(path) for path in paths):
        return True
    return "roadmap" in lowered or "active plan" in lowered or "active-plan" in lowered


def _looks_like_shortcut_prompt(text: str) -> bool:
    lowered = _scrub_negated_subagent_delegation_guardrails(str(text or "")).casefold()
    shortcut_terms = (
        "without plan",
        "skip check",
        "skip dry-run",
        "no frontmatter",
        "archive anyway",
        "mark done",
        "bypass",
        "shortcut",
        "шорткат",
        "без плана",
        "без проверки",
    )
    return any(term in lowered for term in shortcut_terms)


def _looks_like_descriptive_route_navigation_prompt(text: str) -> bool:
    lowered = str(text or "").casefold()
    context_markers = (
        "handoff",
        "read/navigation",
        "navigation refs",
        "context only",
        "read-only",
        "review",
        "inspect",
        "blocker evidence",
        "checkpoint symptoms",
        "route context",
    )
    route_markers = (
        "lifecycle",
        "checkpoint",
        "route-produced",
        "dry-run/apply",
        "project/project-state.md",
        "project/implementation-plan.md",
        "project/roadmap.md",
    )
    boundary_markers = (
        "do not",
        "must not",
        "should not",
        "no push",
        "no release",
        "without push",
        "without release",
        "remain blocked",
        "stays blocked",
        "stop before",
    )
    return (
        any(marker in lowered for marker in context_markers)
        and any(marker in lowered for marker in route_markers)
        and any(marker in lowered for marker in boundary_markers)
    )


def _looks_like_generated_cache_write(paths: list[str], command: str) -> bool:
    return any(_is_generated_cache_path(path) for path in paths) and _looks_like_write_command(command)


def _looks_like_lifecycle_markdown_write(paths: list[str], command: str) -> bool:
    return any(_is_lifecycle_route_path(path) for path in paths) and _looks_like_write_command(command) and "mylittleharness" not in command.casefold()


def _nonroute_project_markdown_write_path(paths: list[str], command: str) -> str:
    if not _looks_like_write_command(command):
        return ""
    for path in paths:
        if _is_nonroute_project_markdown_path(path):
            return path
    return ""


def _product_root_direct_edit_path(inventory: Inventory, paths: list[str], command: str) -> str:
    if not _looks_like_write_command(command):
        return ""
    for path in paths:
        if _is_under_configured_product_root(inventory, path) and not _is_active_plan_product_artifact(inventory, path):
            return path
    return ""


def _hook_code_write_paths(inventory: Inventory, paths: list[str], command: str) -> list[str]:
    if not _looks_like_write_command(command):
        return []
    code_paths: list[str] = []
    for path in paths:
        product_rel = _product_relative_path(inventory, path)
        if _is_code_path(path) or (product_rel and _is_code_path(product_rel)):
            code_paths.append(path)
    return code_paths


def _hook_plan_path_display(inventory: Inventory, path: str) -> str:
    product_rel = _product_relative_path(inventory, path)
    if product_rel:
        return _normalize_hook_path(product_rel)
    normalized = _normalize_plan_artifact_candidate(inventory, path)
    return normalized or _normalize_hook_path(path)


def _hook_scope_diagnostic_message(allowed_scope: list[str], blocked_scope: list[str]) -> str:
    allowed = ", ".join(_dedupe_nonempty(allowed_scope)) or "none"
    blocked = ", ".join(_dedupe_nonempty(blocked_scope)) or "none"
    return f"allowed_paths={allowed}; blocked_paths={blocked}"


def _hook_lifecycle_markdown_shortcut_next_safe_command(inventory: Inventory, path: str, command: str) -> str:
    rel = _hook_route_rel_path(inventory, path) or _normalize_hook_path(path)
    if _looks_like_incubation_prompt_move_shortcut(inventory, rel, command):
        return mlh_command(
            "memory-hygiene",
            "--dry-run",
            "--move-non-incubation-prompt",
            "--source",
            rel,
            "--target",
            _operator_prompt_target_for_source(rel),
        )
    prompt_move_source = _incubation_prompt_move_source_from_command(inventory, command)
    if prompt_move_source is not None:
        return mlh_command(
            "memory-hygiene",
            "--dry-run",
            "--move-non-incubation-prompt",
            "--source",
            prompt_move_source,
            "--target",
            _operator_prompt_target_for_source(prompt_move_source),
        )
    if _looks_like_incubation_archive_maintenance_shortcut(rel, command):
        return mlh_command(
            "memory-hygiene",
            "--dry-run",
            "--archive-list-file",
            "<project/verification/reviewed-archive-list.txt>",
            "--archive-folder",
            "project/archive/reference/<reviewed-folder>",
            "--reason",
            '"<reason>"',
            "--repair-links",
        )
    return _hook_route_next_safe_command(inventory, path)


def _hook_lifecycle_markdown_path_next_safe_command(inventory: Inventory, path: str) -> str:
    rel = _hook_route_rel_path(inventory, path) or _normalize_hook_path(path)
    if _is_reviewed_meta_feedback_incubation_file(inventory, rel):
        return _hook_lifecycle_evidence_package_split_step_next_safe_command()
    if _looks_like_incubation_prompt_source(inventory, rel):
        return mlh_command(
            "memory-hygiene",
            "--dry-run",
            "--move-non-incubation-prompt",
            "--source",
            rel,
            "--target",
            _operator_prompt_target_for_source(rel),
        )
    return _hook_route_next_safe_command(inventory, path)


def _hook_lifecycle_evidence_package_split_step_next_safe_command() -> str:
    return (
        "stage one route-produced incubation note at a time, then stage lifecycle/evidence/archive artifacts "
        "as separate exact groups: git -C <actual-root> add -- <one-incubation-note>; "
        "git -C <actual-root> add -- project/project-state.md project/roadmap.md "
        "<work-claim-ref> <handoff-ref>; git -C <actual-root> add -f -- <ignored-route-artifact>; "
        "git -C <actual-root> diff --cached --check; git -C <actual-root> commit -F <message-file>"
    )


def _incubation_prompt_move_source_from_command(inventory: Inventory, command: str) -> str | None:
    normalized_command = command.casefold()
    if not any(marker in normalized_command for marker in ("move-item", "mv ", "copy-item", "cp ")):
        return None
    for candidate in _extract_paths(command):
        rel = _hook_route_rel_path(inventory, candidate) or _normalize_hook_path(candidate)
        if _looks_like_incubation_prompt_move_shortcut(inventory, rel, command):
            return rel
    return None


def _looks_like_incubation_archive_maintenance_shortcut(rel: str, command: str) -> bool:
    if not rel.startswith("project/plan-incubation/"):
        return False
    normalized = command.casefold()
    return any(marker in normalized for marker in ("remove-item", "move-item", "rm ", "mv ", "del ", "archive"))


def _looks_like_incubation_prompt_move_shortcut(inventory: Inventory, rel: str, command: str) -> bool:
    if not rel.startswith("project/plan-incubation/") or not rel.endswith(".md"):
        return False
    normalized_command = command.casefold()
    if not any(marker in normalized_command for marker in ("move-item", "mv ", "copy-item", "cp ")):
        return False
    return _looks_like_incubation_prompt_source(inventory, rel)


def _looks_like_incubation_prompt_source(inventory: Inventory, rel: str) -> bool:
    if not rel.startswith("project/plan-incubation/") or not rel.endswith(".md"):
        return False
    path = _hook_route_file_path(inventory, rel)
    if path is None:
        return _operator_prompt_source_name_signal(rel)
    try:
        if not path.is_file() or path.is_symlink():
            return False
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _operator_prompt_source_name_signal(rel)
    return _operator_prompt_source_name_signal(rel) or _operator_prompt_text_signal(text)


def _operator_prompt_source_name_signal(rel: str) -> bool:
    name = Path(rel).name.casefold()
    return any(marker in name for marker in ("prompt", "handoff", "launch", "operator"))


def _operator_prompt_text_signal(text: str) -> bool:
    normalized = text[:4000].casefold()
    return any(
        marker in normalized
        for marker in (
            "codex_delegation",
            "continuation packet",
            "start in the saved",
            "do not restart",
            "follow the packet",
        )
    )


def _operator_prompt_target_for_source(rel: str) -> str:
    stem = Path(rel).stem.casefold()
    slug = re.sub(r"[^a-z0-9._-]+", "-", stem).strip(".-") or "operator-prompt"
    return f"project/operator-prompts/{slug}.md"


def _hook_route_next_safe_command(inventory: Inventory, path: str) -> str:
    rel = _hook_route_rel_path(inventory, path) or _normalize_hook_path(path)
    route_id = classify_memory_route(rel).route_id
    topic = _route_topic_from_path(rel)
    if _is_worker_run_receipt_route_path(rel):
        return mlh_command("evidence", "--receipt-refresh", "--dry-run", "--target", rel)
    if _is_agent_run_evidence_route_path(rel):
        record_id = _route_topic_from_path(rel) or "<record-id>"
        return mlh_command(
            "evidence",
            "--record",
            "--dry-run",
            "--record-id",
            record_id,
            "--role",
            "<role>",
            "--actor",
            "<actor>",
            "--task",
            "<task>",
            "--assigned-scope",
            "<scope>",
            "--runtime",
            "<runtime>",
            "--worktree-id",
            "<worktree-id>",
            "--status",
            "succeeded",
            "--stop-reason",
            "<reason>",
            "--attempt-budget",
            "<n/n>",
            "--docs-decision",
            "<docs-decision>",
            "--residual-risk",
            "<risk>",
        )
    if _verification_checkpoint_path_class(rel) == "queue-runner-fixtures":
        return mlh_command("evidence", "--fixture-update", "--dry-run", "--target", rel, "--text-file", "-")
    if _is_roadmap_path(rel) or route_id == "roadmap":
        return mlh_command("roadmap", "--dry-run", "--action", "update", "--item-id", "<id>")
    if route_id == "state":
        return mlh_command("writeback", "--dry-run", "--phase-status", "<phase-status>", "--docs-decision", "<docs-decision>")
    if route_id == "active-plan":
        return mlh_command("plan", "--dry-run", "--roadmap-item", "<id>")
    if route_id == "incubation":
        return mlh_command("incubate", "--dry-run", "--topic", safe_double_quoted(topic, placeholder="<topic>"), "--note-file", "-")
    if route_id == "operator-prompts":
        return mlh_command(
            "memory-hygiene",
            "--dry-run",
            "--move-non-incubation-prompt",
            "--source",
            "project/plan-incubation/<file>.md",
            "--target",
            rel,
        )
    if route_id == "research":
        return mlh_command("research-import", "--dry-run", "--title", '"<title>"', "--topic", safe_double_quoted(topic, placeholder="<topic>"), "--text-file", "-")
    if _is_temporary_roadmap_manifest_path(rel):
        return mlh_command("cleanup", "--dry-run", "--target", rel)
    if route_id in {"adrs", "decisions", "product-docs"}:
        return mlh_command("intake", "--dry-run", "--text-file", "-", "--target", rel)
    if route_id == "verification":
        return mlh_command("intake", "--dry-run", "--text-file", "-", "--target", rel)
    if route_id == "stable-specs":
        return mlh_command("check", "--focus", "route-references")
    if route_id == "archive":
        return mlh_command("memory-hygiene", "--dry-run", "--scan")
    return mlh_command("suggest", "--intent", safe_double_quoted(f"route owner for {safe_intent_text(rel or path, placeholder='<path>')}"))


def _git_mutation_next_safe_command(inventory: Inventory, data: dict[str, object], command: str) -> str:
    if _active_plan_ready_for_route_produced_lifecycle_git(inventory):
        paths = _route_produced_lifecycle_suggested_stage_paths(inventory, _git_stage_pathspecs(command))
        if paths:
            return "gi" + "t add -- " + " ".join(shell_arg(path) for path in paths)
    split_next_safe = _post_closeout_checkpoint_split_next_safe_command(inventory, data, command)
    if split_next_safe:
        return split_next_safe
    actual_root_next_safe = _actual_root_vcs_next_safe_command(inventory, data, command)
    if actual_root_next_safe:
        return actual_root_next_safe
    product_source_next_safe = _product_source_vcs_next_safe_command(inventory, data, command)
    if product_source_next_safe:
        return product_source_next_safe
    if _has_active_plan(inventory):
        return mlh_command("writeback", "--dry-run", "--phase-status", "complete", "--docs-decision", "<docs-decision>")
    return "gi" + "t add -- <exact-reviewed-files>; " + "gi" + "t diff --cached --check; " + "gi" + "t commit -F <message-file>"


def _post_closeout_checkpoint_split_next_safe_command(inventory: Inventory, data: dict[str, object], command: str) -> str:
    if _has_active_plan(inventory) or _git_subcommand(command) != "commit":
        return ""
    target_inventory, _root_reason = _index_split_target_inventory(inventory, data, command)
    if target_inventory is None:
        return ""
    staged_paths = _git_staged_paths_for_root(target_inventory.root)
    staged = _normalized_exact_staged_paths(target_inventory, staged_paths)
    if not staged or _coherent_checkpoint_path_set(target_inventory, staged):
        return ""
    split_paths = _post_closeout_checkpoint_split_candidate_paths(target_inventory, staged)
    if not split_paths:
        return ""
    visible_workdir = _checkpoint_uses_visible_workdir(inventory, data, target_inventory.root)
    git_prefix = "gi" + "t" if visible_workdir else "gi" + "t -C " + shell_arg(str(target_inventory.root))
    split_args = " ".join(shell_arg(path) for path in split_paths)
    classes = _reviewed_local_vcs_checkpoint_path_classes(set(staged))
    return (
        f"detected_checkpoint_classes={classes}; "
        "next_safe_command=split exact checkpoint classes with index-only unstage while the working tree is preserved: "
        f"{git_prefix} restore --staged -- {split_args}; "
        f"{git_prefix} diff --cached --check; "
        f"{git_prefix} commit -F <message-file>; "
        f"{git_prefix} add -- {split_args}; "
        f"{git_prefix} diff --cached --check; "
        f"{git_prefix} commit -F <message-file>"
    )


def _post_closeout_checkpoint_split_candidate_paths(inventory: Inventory, staged: tuple[str, ...]) -> tuple[str, ...]:
    candidate_groups = [
        tuple(path for path in staged if _is_meta_feedback_incubation_route_path(path)),
        tuple(
            path
            for path in staged
            if _is_worker_run_receipt_route_path(path) or _is_retention_receipt_route_path(path)
        ),
        tuple(path for path in staged if _is_checkpoint_decision_route_path(path) or _is_verification_checkpoint_route_path(path)),
    ]
    for group in candidate_groups:
        if not group:
            continue
        split = set(group)
        remaining = tuple(path for path in staged if path not in split)
        if _coherent_checkpoint_path_set(inventory, split) or _coherent_checkpoint_path_set(inventory, remaining):
            return group
    return ()


def _actual_root_vcs_next_safe_command(inventory: Inventory, data: dict[str, object], command: str) -> str:
    actual_root = _git_effective_workdir_path(inventory, data, command)
    if actual_root is None:
        return ""
    try:
        current_root = inventory.root.resolve()
        actual_root = actual_root.resolve()
    except (OSError, RuntimeError, ValueError):
        return ""
    if actual_root == current_root:
        return ""
    product_root = _configured_product_source_root_path(inventory)
    if product_root is not None:
        try:
            actual_root.relative_to(product_root.resolve())
            return ""
        except ValueError:
            pass
        except (OSError, RuntimeError):
            return ""
    return _local_vcs_checkpoint_next_safe_for_root(actual_root)


def _local_vcs_checkpoint_next_safe_for_root(root: Path) -> str:
    git_prefix = "gi" + "t -C " + shell_arg(str(root))
    return (
        f"{git_prefix} add -- <exact-route-files>; "
        f"{git_prefix} add -f -- <exact-route-artifact-if-ignored>; "
        f"{git_prefix} diff --cached --check; "
        f"{git_prefix} commit -F <message-file>"
    )


def _reviewed_local_vcs_checkpoint_next_safe_command(checkpoint: ReviewedLocalVcsCheckpoint) -> str:
    if checkpoint.root is None:
        return "gi" + "t diff --cached --check; " + "gi" + "t commit -F <message-file>"
    git_prefix = "gi" + "t" if checkpoint.visible_workdir else "gi" + "t -C " + shell_arg(str(checkpoint.root))
    if checkpoint.mode == "commit":
        return f"{git_prefix} commit -F <message-file>"
    if checkpoint.mode == "staging-review-bundle":
        return (
            f"{git_prefix} status --short; "
            f"{git_prefix} diff --cached --check; "
            f"{git_prefix} add -f -- <ignored-route-artifact-if-needed>; "
            f"{git_prefix} diff --cached --check; "
            f"{git_prefix} commit -F <message-file>"
        )
    return (
        f"{git_prefix} diff --cached --check; "
        f"{git_prefix} add -f -- <ignored-route-artifact-if-needed>; "
        f"{git_prefix} diff --cached --check; "
        f"{git_prefix} commit -F <message-file>"
    )


def _product_source_vcs_next_safe_command(inventory: Inventory, data: dict[str, object], command: str) -> str:
    product_root = _configured_product_source_root_path(inventory)
    if product_root is None:
        return ""
    subcommand = _git_subcommand(command)
    if subcommand not in {"add", "stage", "commit"}:
        return ""
    if subcommand == "commit" and _product_source_vcs_roots(inventory, data, command)[1] is None:
        return ""
    git_prefix = _product_source_vcs_command_prefix(inventory, data, product_root)
    if subcommand in {"add", "stage"}:
        exact_predicate = (
            _is_exact_active_plan_product_source_stage_file
            if _has_active_plan(inventory)
            else _is_exact_post_closeout_stage_file
        )
        pathspecs = [
            _product_source_tracked_pathspec(product_root, pathspec) or pathspec
            for pathspec in _git_stage_pathspecs(command)
            if exact_predicate(
                inventory,
                pathspec,
                base_root=product_root,
                boundary_root=product_root,
            )
        ]
        if not pathspecs and _has_active_plan(inventory):
            pathspecs = list(_active_plan_product_source_target_pathspecs(inventory, product_root))
        stage_target = " ".join(shell_arg(pathspec) for pathspec in pathspecs) or "<exact-reviewed-product-files>"
        return (
            f"{git_prefix} add -- {stage_target}; "
            f"{git_prefix} status --short; "
            f"{git_prefix} diff --cached --check; "
            f"{git_prefix} commit -F <message-file>"
        )
    return f"{git_prefix} diff --cached --check; {git_prefix} commit -F <message-file>"


def _active_plan_product_source_target_pathspecs(inventory: Inventory, product_root: Path) -> tuple[str, ...]:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return ()
    artifacts = plan.frontmatter.data.get("target_artifacts")
    if not isinstance(artifacts, list):
        return ()
    targets: list[str] = []
    for artifact in artifacts:
        rel = _normalize_hook_path(str(artifact or "")).strip()
        if not rel or rel.startswith(":") or any(char in rel for char in "*?[]"):
            continue
        try:
            candidate = (product_root / rel).resolve()
            candidate.relative_to(product_root.resolve())
        except (OSError, RuntimeError, ValueError):
            continue
        if not candidate.is_file() or candidate.is_symlink():
            continue
        if not _is_active_plan_target_artifact(inventory, str(candidate)):
            continue
        targets.append(_product_source_tracked_pathspec(product_root, rel) or rel)
    return tuple(_dedupe_nonempty(targets))


def _product_source_vcs_command_prefix(inventory: Inventory, data: dict[str, object], product_root: Path) -> str:
    actual_root = _hook_command_workdir_path(inventory, data)
    try:
        if actual_root is not None and actual_root.resolve() == product_root.resolve():
            return "gi" + "t"
    except (OSError, RuntimeError, ValueError):
        pass
    return "gi" + "t -C " + shell_arg(str(product_root))


def _product_source_tracked_pathspec(product_root: Path, pathspec: str) -> str:
    clean = _clean_token(pathspec)
    if not clean or any(char in clean for char in "*?[]") or clean.startswith(":"):
        return ""
    normalized = _normalize_hook_path(clean)
    result = _run_git_for_root(product_root, "ls-files", "--", normalized)
    if result is None or result.returncode != 0:
        return ""
    matches = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(matches) != 1:
        return ""
    return matches[0]


def _route_produced_lifecycle_suggested_stage_paths(inventory: Inventory, candidates: list[str] | tuple[str, ...]) -> list[str]:
    state_rel = "project/" + "project-state.md"
    roadmap_rel = "project/" + "roadmap.md"
    archive_prefix = "project/" + "archive/plans/"
    active_plan_rel = _active_plan_rel_path(inventory)
    last_archive_rel = _last_archived_plan_rel_path(inventory)
    candidate_rels = {_hook_route_rel_path(inventory, path).casefold() for path in candidates if path}
    archive_rels = {path for path in candidate_rels if path.startswith(archive_prefix)}
    if last_archive_rel:
        archive_rels.add(last_archive_rel)
    paths = [state_rel]
    if archive_rels:
        paths.append(roadmap_rel)
        paths.extend(sorted(archive_rels))
    elif active_plan_rel:
        paths.append(active_plan_rel)
    return [path for path in _dedupe_nonempty(paths) if _is_existing_lifecycle_route_file(inventory, path)]


def _hook_product_root_write_next_safe_command(inventory: Inventory, path: str) -> str:
    if not _has_active_plan(inventory):
        return mlh_command("plan", "--dry-run", "--roadmap-item", "<id>")
    product_rel = _product_relative_path(inventory, path)
    target = _normalize_hook_path(product_rel) if product_rel else "<rel-path>"
    return mlh_command(
        "roadmap",
        "--dry-run",
        "--action",
        "update",
        "--item-id",
        "<id>",
        "--target-artifact",
        target or "<rel-path>",
    )


def _generated_cache_recovery_command(inventory: Inventory) -> str:
    if inventory.root_kind == PRODUCT_SOURCE_FIXTURE:
        return "mylittleharness --root <root> projection --warm-cache --target all"
    return "mylittleharness --root <root> mlhd run-once --apply"


def _route_topic_from_path(path: str) -> str:
    stem = Path(_normalize_hook_path(path)).stem.strip()
    return stem or "<topic>"


def _dedupe_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _looks_like_write_command(command: str) -> bool:
    if _looks_like_opaque_shell_payload(command) or _runtime_code_payload_looks_like_write(command):
        return True
    expect_command = True
    tokens = _shell_tokens(command)
    if _git_output_target_paths(tokens):
        return True
    for nested in _nested_shell_commands_from_tokens(tokens):
        if nested == "<MLH_ENCODED_COMMAND>" or _looks_like_write_command(nested):
            return True
    for token in tokens:
        raw = str(token or "").strip()
        clean = _clean_shell_command_token(raw)
        if _is_shell_redirection_token(raw, clean):
            return True
        if not clean:
            if _is_shell_command_separator(raw, clean):
                expect_command = True
            continue
        if expect_command and clean in WRITING_COMMAND_NAMES:
            return True
        if _is_shell_command_separator(raw, clean):
            expect_command = True
            continue
        expect_command = False
        if raw.endswith(";"):
            expect_command = True
    return False


def _is_shell_redirection_token(raw: str, clean: str) -> bool:
    stripped = raw.strip(" \t\r\n\"'`")
    if _is_shell_fd_duplication_redirection(stripped):
        return False
    return (
        clean in {">", ">>"}
        or stripped in {">", ">>"}
        or bool(re.match(r"^(?:\d+|\*)?>>?", stripped))
    )


def _is_shell_fd_duplication_redirection(value: str) -> bool:
    stripped = str(value or "").strip(" \t\r\n\"'`").rstrip(";")
    return bool(re.match(r"^(?:\d+|\*)?>&\d+$", stripped))


def _is_shell_command_separator(raw: str, clean: str) -> bool:
    stripped = raw.strip(" \t\r\n\"'`")
    return clean in SHELL_COMMAND_SEPARATORS or stripped in SHELL_COMMAND_SEPARATORS or stripped.endswith(";")


def _looks_like_git_stage_or_commit(lowered_command: str) -> bool:
    lowered_command = _command_without_shell_literal_payloads(lowered_command).casefold()
    padded = f" {lowered_command} "
    return any(token in padded for token in GIT_WRITE_COMMANDS) or _git_subcommand(lowered_command) in GIT_MUTATION_COMMANDS


def _looks_like_opaque_shell_payload(command: str) -> bool:
    tokens = _shell_tokens(command)
    return any(nested == "<MLH_ENCODED_COMMAND>" for nested in _nested_shell_commands_from_tokens(tokens))


def _looks_like_next_plan_apply(lowered_command: str) -> bool:
    policy_command = _mlh_policy_command(lowered_command)
    padded = f" {policy_command} "
    if " --update-active" in padded:
        return False
    return _mlh_cli_subcommand(policy_command) == "plan" and " --apply" in padded


def _looks_like_unsafe_mlh_mutation(lowered_command: str) -> bool:
    if _has_unresolved_mlh_splat_invocation(lowered_command):
        return True
    policy_command = _mlh_policy_command(lowered_command)
    subcommand = _mlh_cli_subcommand(policy_command)
    if not subcommand:
        return False
    padded = f" {policy_command} "
    if subcommand == "adapter":
        return " --install-client-config " in padded
    return subcommand in {
        "repair",
        "plan",
        "writeback",
        "transition",
        "roadmap",
        "meta-feedback",
        "projection",
        "memory-hygiene",
        "hooks",
        "cleanup",
    }


def _mlh_cli_subcommand(command: str) -> str:
    subcommands = _mlh_cli_subcommands(command)
    return subcommands[0] if subcommands else ""


def _mlh_cli_subcommands(command: str) -> tuple[str, ...]:
    tokens = _shell_tokens(_mlh_policy_command(command))
    subcommands: list[str] = []
    for index, token in enumerate(tokens):
        if _is_mlh_executable_token(token):
            subcommand = _next_mlh_subcommand(tokens, index + 1)
            if subcommand:
                subcommands.append(subcommand)
        if _is_python_executable_token(token) and index + 2 < len(tokens):
            if _clean_token(tokens[index + 1]) == "-m" and _clean_token(tokens[index + 2]) == "my" + "littleharness":
                subcommand = _next_mlh_subcommand(tokens, index + 3)
                if subcommand:
                    subcommands.append(subcommand)
    return tuple(subcommands)


def _shell_tokens(command: str) -> list[str]:
    command = _command_without_shell_literal_payloads(command or "")
    try:
        return shlex.split(command or "", posix=False)
    except ValueError:
        return str(command or "").split()


def _command_without_shell_literal_payloads(command: str) -> str:
    text = _command_without_powershell_here_string_payloads(command or "")
    return _command_without_posix_heredoc_payloads(text)


def _command_without_powershell_here_string_payloads(command: str) -> str:
    lines = str(command or "").splitlines(keepends=True)
    if not lines:
        return ""
    result: list[str] = []
    pending_quote = ""
    for line in lines:
        if pending_quote:
            stripped = line.lstrip()
            closing = pending_quote + "@"
            if stripped.startswith(closing):
                result.append(" <MLH_STDIN_PAYLOAD> " + stripped[len(closing) :])
                pending_quote = ""
            continue
        match = re.search(r"@(['\"])\s*$", line)
        if match:
            result.append(line[: match.start()] + " <MLH_STDIN_PAYLOAD> ")
            pending_quote = match.group(1)
            continue
        result.append(line)
    return "".join(result)


def _command_without_posix_heredoc_payloads(command: str) -> str:
    lines = str(command or "").splitlines(keepends=True)
    if not lines:
        return ""
    result: list[str] = []
    pending_delimiter = ""
    for line in lines:
        if pending_delimiter:
            if line.strip() == pending_delimiter:
                pending_delimiter = ""
            continue
        result.append(line)
        match = POSIX_HEREDOC_START_RE.search(line)
        if match:
            pending_delimiter = match.group(1)
    return "".join(result)


def _next_mlh_subcommand(tokens: list[str], start: int) -> str:
    options_with_values = {"--root", "--config", "--config-path"}
    index = start
    while index < len(tokens):
        token = _clean_token(tokens[index])
        if not token:
            index += 1
            continue
        if token in options_with_values:
            index += 2
            continue
        if token.startswith("--root=") or token.startswith("--config=") or token.startswith("--config-path="):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return ""


def _is_mlh_executable_token(token: str) -> bool:
    clean = _clean_token(token)
    if clean in {"my" + "littleharness", "my" + "littleharness.exe"}:
        return True
    return Path(clean).name in {"my" + "littleharness", "my" + "littleharness.exe"}


def _is_python_executable_token(token: str) -> bool:
    clean = _clean_token(token)
    name = Path(clean).name
    return name in {"python", "python.exe", "py", "py.exe"}


def _clean_token(token: str) -> str:
    return str(token or "").strip(" \t\r\n\"'`{}[](),;").casefold()


def _clean_shell_command_token(token: str) -> str:
    clean = _clean_token(token)
    while clean.startswith(("@(", "$(")):
        clean = clean[2:].strip(" \t\r\n\"'`{}[](),;")
    return clean


def _has_explicit_mlh_review_mode(lowered_command: str) -> bool:
    policy_command = _mlh_policy_command(lowered_command)
    if _has_unresolved_mlh_splat_invocation(lowered_command):
        return False
    padded = f" {policy_command} "
    if _has_mlh_review_mode_token(policy_command):
        return True
    if " mylittleharness" in padded and " projection " in padded:
        return any(
            term in padded
            for term in (
                " --inspect",
                " --warm-cache",
                " --rebuild",
                " --build",
                " --delete",
            )
        )
    if " mylittleharness" in padded and " hooks " in padded:
        return " --doctor" in padded or " hooks doctor " in padded or " --run " in padded
    return False


def _is_generated_cache_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return any(rel.startswith(prefix) for prefix in GENERATED_CACHE_PREFIXES)


def _is_code_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.endswith(".py") and any(rel.startswith(prefix) for prefix in CODE_WRITE_PREFIXES)


def _has_active_plan(inventory: Inventory) -> bool:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return str(state.get("plan_status") or "").strip().casefold() == "active" and bool(str(state.get("active_plan") or "").strip())


def _active_plan_blocks_product_source_vcs_push(inventory: Inventory) -> bool:
    if not _has_active_plan(inventory):
        return False
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return str(state.get("phase_status") or "").strip().casefold() != "complete"


def _is_lifecycle_authority_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel in LIFECYCLE_AUTHORITY_PATHS


def _is_lifecycle_markdown_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel.endswith(".md") and any(rel.startswith(prefix) for prefix in LIFECYCLE_MARKDOWN_PREFIXES)


def _is_agent_run_evidence_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    agent_run_prefix = "/".join(("project", "verification", "agent-runs")) + "/"
    return rel.startswith(agent_run_prefix) and rel.endswith(".md")


def _is_lifecycle_route_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold().rstrip("/")
    if _is_lifecycle_authority_path(rel) or _is_lifecycle_markdown_path(rel):
        return True
    for prefix in LIFECYCLE_MARKDOWN_PREFIXES:
        route = prefix.rstrip("/")
        if prefix.endswith("/") and (rel == route or rel.startswith(prefix)):
            return True
        if not prefix.endswith("/") and (rel == route or rel.startswith(route + "/")):
            return True
    return False


def _is_temporary_roadmap_manifest_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return bool(TEMPORARY_ROADMAP_MANIFEST_RE.match(rel))


def _temporary_roadmap_manifest_path(paths: list[str]) -> str:
    for path in paths:
        rel = _normalize_hook_path(path)
        if _is_temporary_roadmap_manifest_path(rel):
            return rel
    return ""


def _is_existing_lifecycle_route_file(inventory: Inventory, path: str) -> bool:
    rel = _hook_route_rel_path(inventory, path)
    if not rel or not _is_lifecycle_route_path(rel):
        return False
    route_path = _hook_route_file_path(inventory, path)
    if route_path is None:
        return False
    try:
        return route_path.is_file() and not route_path.is_symlink()
    except (OSError, RuntimeError):
        return False


def _is_tracked_existing_lifecycle_route_file(inventory: Inventory, path: str) -> bool:
    rel = _hook_route_rel_path(inventory, path)
    if not rel or any(char in rel for char in "*?[]") or rel.startswith(":"):
        return False
    if not _is_existing_lifecycle_route_file(inventory, rel):
        return False
    result = _run_git_for_root(inventory.root, "ls-files", "--", rel)
    if result is None or result.returncode != 0:
        return False
    expected = _normalize_hook_path(rel).casefold()
    return any(_normalize_hook_path(line.strip()).casefold() == expected for line in result.stdout.splitlines())


def _is_roadmap_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    return rel == "project/" + "roadmap.md"


def _is_nonroute_project_markdown_path(path: str) -> bool:
    rel = _normalize_hook_path(path).casefold()
    if not rel.startswith("project/") or not rel.endswith(".md"):
        return False
    if any(rel.startswith(prefix) for prefix in NONROUTE_PROJECT_MARKDOWN_EXEMPT_PREFIXES):
        return False
    return classify_memory_route(rel).route_id == "unclassified"


def _is_under_configured_product_root(inventory: Inventory, path: str) -> bool:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    product_root = str(state.get("product_source_root") or "").strip()
    if not product_root:
        return False
    try:
        candidate = _resolve_hook_path_from_root(inventory, path)
        if candidate is None:
            return False
        candidate.relative_to(Path(product_root).expanduser().resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _is_delegation_prompt_context_path(inventory: Inventory, path: str) -> bool:
    normalized = _normalize_hook_path(path).casefold()
    if _is_lifecycle_route_path(path) or _is_under_configured_product_root(inventory, path):
        return True
    return normalized in {
        "agents.md",
        ".codex/project-workflow.toml",
        ".mylittleharness/project-workflow.toml",
        "readme.md",
    }


def _is_active_plan_product_artifact(inventory: Inventory, path: str) -> bool:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return False
    rel = _product_relative_path(inventory, path)
    if not rel:
        return False
    artifacts = plan.frontmatter.data.get("target_artifacts")
    if not isinstance(artifacts, list):
        return False
    normalized = _normalize_hook_path(rel).casefold()
    for artifact in artifacts:
        candidate = _normalize_hook_path(str(artifact or "")).casefold()
        if candidate and normalized == candidate:
            return _active_phase_write_scope_product_artifact_allows_path(inventory, normalized)
    return False


def _active_phase_write_scope_product_artifact_allows_path(inventory: Inventory, product_rel: str) -> bool:
    scope = _active_phase_write_scope_paths(inventory)
    if not scope:
        return True
    normalized = _normalize_hook_path(product_rel).casefold()
    return any(normalized == item.rstrip("/") for item in scope if item.rstrip("/"))


def _is_active_plan_target_artifact(inventory: Inventory, path: str) -> bool:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return False
    artifacts = plan.frontmatter.data.get("target_artifacts")
    if not isinstance(artifacts, list):
        return False
    normalized = _normalize_plan_artifact_candidate(inventory, path)
    if not normalized:
        return False
    for artifact in artifacts:
        candidate = _normalize_hook_path(str(artifact or "")).casefold()
        prefix = candidate.rstrip("/")
        if prefix and (normalized == prefix or normalized.startswith(f"{prefix}/")):
            return True
    return False


def _active_phase_write_scope_allows_path(inventory: Inventory, rel: str) -> bool:
    scope = _active_phase_write_scope_paths(inventory)
    normalized = _normalize_hook_path(rel).casefold()
    return bool(scope) and any(
        normalized == item.rstrip("/") or normalized.startswith(f"{item.rstrip('/')}/")
        for item in scope
        if item.rstrip("/")
    )


def _active_phase_write_scope_paths(inventory: Inventory) -> set[str]:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return set()
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    active_phase = str(state_data.get("active_phase") or plan.frontmatter.data.get("active_phase") or "").strip()
    block = _active_phase_block_text(plan.content, active_phase)
    if not block:
        return set()
    paths: set[str] = set()
    for line in block.splitlines():
        match = re.match(r"^\s*[-*]\s*write_scope\s*:\s*(.+?)\s*$", line, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1)
        extracted = re.findall(r"`([^`]+)`", value)
        for item in extracted or re.split(r"\s*,\s*", value):
            normalized = _normalize_hook_path(item.strip().strip("`'\"")).casefold()
            if normalized and normalized != "<none>":
                paths.add(normalized)
    return paths


def _active_phase_block_text(text: str, active_phase: str) -> str:
    if not active_phase:
        return ""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^\s*###\s+(.+?)\s*$", line)
        if not match:
            continue
        next_index = len(lines)
        for candidate in range(index + 1, len(lines)):
            if re.match(r"^\s*###\s+", lines[candidate]):
                next_index = candidate
                break
        block = "\n".join(lines[index:next_index])
        title = _normalize_phase_identifier(match.group(1))
        if title == _normalize_phase_identifier(active_phase) or re.search(
            rf"^\s*[-*]\s*id\s*:\s*`?{re.escape(active_phase)}`?\s*$",
            block,
            flags=re.MULTILINE,
        ):
            return block
    return ""


def _normalize_phase_identifier(value: str) -> str:
    return _normalize_hook_path(value.strip().strip("`")).casefold().replace(" ", "-")


def _normalize_plan_artifact_candidate(inventory: Inventory, path: str) -> str:
    rel = _product_relative_path(inventory, path)
    if rel:
        return _normalize_hook_path(rel).casefold()
    try:
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            return candidate.resolve().relative_to(inventory.root.resolve()).as_posix().casefold()
    except (OSError, RuntimeError, ValueError):
        return ""
    return _normalize_hook_path(path).casefold()


def _product_relative_path(inventory: Inventory, path: str) -> str:
    state = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    product_root = str(state.get("product_source_root") or "").strip()
    if not product_root:
        return ""
    try:
        candidate = _resolve_hook_path_from_root(inventory, path)
        if candidate is None:
            return ""
        return candidate.relative_to(Path(product_root).expanduser().resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return ""


def _codex_hooks_config_path(root: Path, request: CodexHookAdapterRequest) -> Path:
    return _native_hooks_config_path(root, request)


def _native_hooks_config_path(root: Path, request: CodexHookAdapterRequest) -> Path:
    if request.config_path:
        candidate = Path(str(request.config_path).replace("\\", "/")).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        return candidate
    if request.scope == "project":
        return root / _native_hooks_config_rel_path(request.client)
    return root / ".mylittleharness" / f"unsupported-{request.client}-hooks.json"


def _codex_hook_script_path(root: Path, request: CodexHookAdapterRequest) -> Path:
    return _native_hook_script_path(root, request)


def _native_hook_script_path(root: Path, request: CodexHookAdapterRequest) -> Path:
    if request.scope == "project":
        return root / _native_hook_script_rel_path(request.client)
    return root / ".mylittleharness" / f"unsupported-{request.client}-hook.py"


def _codex_hook_adapter_status(root: Path, request: CodexHookAdapterRequest) -> str:
    config_path = _native_hooks_config_path(root, request)
    script_path = _native_hook_script_path(root, request)
    try:
        config_current = config_path.is_file() and not config_path.is_symlink() and config_path.read_text(encoding="utf-8") == render_native_hooks_json(root, request)
    except (OSError, ValueError):
        config_current = False
    try:
        script_current = script_path.is_file() and not script_path.is_symlink() and script_path.read_text(encoding="utf-8") == render_native_hook_script(request.client)
    except OSError:
        script_current = False
    if config_current and script_current:
        return "mounted"
    if not config_path.exists() and not script_path.exists():
        return "missing"
    return "needs-update"


def _read_codex_hooks_config(config_path: Path) -> dict[str, object]:
    return _read_native_hooks_config(config_path, CODEX_CLIENT)


def _read_native_hooks_config(config_path: Path, client: str) -> dict[str, object]:
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{_native_hook_client_label(client)} hooks config is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"{_native_hook_client_label(client)} hooks config could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{_native_hook_client_label(client)} hooks config root must be a JSON object")
    hooks = payload.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{_native_hook_client_label(client)} hooks config `hooks` field must be a JSON object")
    if client == GITHUB_COPILOT_CLIENT and "version" in payload and payload.get("version") != 1:
        raise ValueError("GitHub Copilot hooks config `version` must be 1 when present")
    for event_name in _native_hook_event_names(client):
        event_hooks = hooks.get(event_name, [])
        if not isinstance(event_hooks, list):
            raise ValueError(f"{_native_hook_client_label(client)} hooks config `hooks.{event_name}` field must be a JSON array")
    return payload


def _merge_codex_native_hooks(existing: dict[str, object]) -> dict[str, object]:
    merged = json.loads(json.dumps(existing))
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        merged["hooks"] = hooks
    for hook_id in CODEX_NATIVE_HOOKS:
        codex_event = CODEX_HOOK_EVENTS[hook_id]
        existing_groups = hooks.get(codex_event, [])
        if not isinstance(existing_groups, list):
            existing_groups = []
        filtered_groups = [group for group in existing_groups if not _is_mlh_codex_hook_group(group)]
        filtered_groups.append(_codex_hook_group(hook_id))
        hooks[codex_event] = filtered_groups
    return merged


def _merge_claude_code_native_hooks(existing: dict[str, object]) -> dict[str, object]:
    merged = json.loads(json.dumps(existing))
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        merged["hooks"] = hooks
    for hook_id in NATIVE_ADAPTER_HOOKS:
        event_name = CODEX_HOOK_EVENTS[hook_id]
        existing_groups = hooks.get(event_name, [])
        if not isinstance(existing_groups, list):
            existing_groups = []
        filtered_groups = [group for group in existing_groups if not _is_mlh_native_hook_group(group, CLAUDE_CODE_HOOK_SCRIPT_REL_PATH)]
        filtered_groups.append(_claude_code_hook_group(hook_id))
        hooks[event_name] = filtered_groups
    return merged


def _merge_github_copilot_native_hooks(existing: dict[str, object]) -> dict[str, object]:
    merged = json.loads(json.dumps(existing))
    merged["version"] = 1
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        merged["hooks"] = hooks
    for hook_id in NATIVE_ADAPTER_HOOKS:
        event_name = GITHUB_COPILOT_HOOK_EVENTS[hook_id]
        existing_entries = hooks.get(event_name, [])
        if not isinstance(existing_entries, list):
            existing_entries = []
        filtered_entries = [entry for entry in existing_entries if not _is_mlh_github_copilot_hook_entry(entry)]
        filtered_entries.append(_github_copilot_hook_entry(hook_id))
        hooks[event_name] = filtered_entries
    return merged


def _codex_hook_group(hook_id: str) -> dict[str, object]:
    return {
        "matcher": CODEX_HOOK_MATCHERS[hook_id],
        "hooks": [
            {
                "type": "command",
                "command": _codex_hook_command(hook_id),
                "timeout": 30,
                "statusMessage": CODEX_HOOK_STATUS_MESSAGES[hook_id],
            }
        ],
    }


def _claude_code_hook_group(hook_id: str) -> dict[str, object]:
    group: dict[str, object] = {
        "hooks": [
            {
                "type": "command",
                "command": _native_hook_command(CLAUDE_CODE_CLIENT, hook_id),
                "timeout": 30,
                "statusMessage": CODEX_HOOK_STATUS_MESSAGES[hook_id],
            }
        ],
    }
    if hook_id not in {HOOK_USER_PROMPT_SUBMIT, HOOK_STOP}:
        group["matcher"] = CODEX_HOOK_MATCHERS[hook_id]
    return group


def _github_copilot_hook_entry(hook_id: str) -> dict[str, object]:
    return {
        "type": "command",
        "command": _native_hook_command(GITHUB_COPILOT_CLIENT, hook_id),
        "timeoutSec": 30,
    }


def _codex_hook_command(hook_id: str) -> str:
    return _native_hook_command(CODEX_CLIENT, hook_id)


def _native_hook_command(client: str, hook_id: str) -> str:
    if client == CODEX_CLIENT:
        script_rel = CODEX_HOOK_SCRIPT_REL_PATH
    else:
        script_rel = _native_hook_script_rel_path(client)
    parts_literal = _py_literal(tuple(script_rel.split("/")))
    script_label = "MLH Codex hook script" if client == CODEX_CLIENT else f"MLH {client} hook script"
    return (
        "python -c \"from pathlib import Path; import os; import runpy; "
        "p=Path.cwd().resolve(); roots=(p, *p.parents); "
        f"parts={parts_literal}; "
        "script=next((r.joinpath(*parts) for r in roots if r.joinpath(*parts).is_file()), None); "
        f"assert script is not None, {_py_literal(script_label + ' not found from cwd')}; "
        f"os.environ['MLH_HOOK_EVENT']={_py_literal(hook_id)}; "
        "runpy.run_path(str(script), run_name='__main__')\""
    )


def _is_mlh_codex_hook_group(group: object) -> bool:
    return _is_mlh_native_hook_group(group, CODEX_HOOK_SCRIPT_REL_PATH)


def _is_mlh_native_hook_group(group: object, script_rel_path: str) -> bool:
    if not isinstance(group, dict):
        return False
    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        return False
    for handler in handlers:
        if not isinstance(handler, dict):
            continue
        command = str(handler.get("command") or "")
        if Path(script_rel_path).name in command:
            return True
    return False


def _is_mlh_github_copilot_hook_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    command = str(entry.get("command") or "")
    return Path(GITHUB_COPILOT_HOOK_SCRIPT_REL_PATH).name in command


def _native_hooks_config_rel_path(client: str) -> str:
    if client == CLAUDE_CODE_CLIENT:
        return CLAUDE_CODE_HOOKS_REL_PATH
    if client == GITHUB_COPILOT_CLIENT:
        return GITHUB_COPILOT_HOOKS_REL_PATH
    return CODEX_HOOKS_REL_PATH


def _native_hook_script_rel_path(client: str) -> str:
    if client == CLAUDE_CODE_CLIENT:
        return CLAUDE_CODE_HOOK_SCRIPT_REL_PATH
    if client == GITHUB_COPILOT_CLIENT:
        return GITHUB_COPILOT_HOOK_SCRIPT_REL_PATH
    return CODEX_HOOK_SCRIPT_REL_PATH


def _native_hook_event_names(client: str) -> list[str]:
    if client == GITHUB_COPILOT_CLIENT:
        return [GITHUB_COPILOT_HOOK_EVENTS[hook_id] for hook_id in NATIVE_ADAPTER_HOOKS]
    return [CODEX_HOOK_EVENTS[hook_id] for hook_id in NATIVE_ADAPTER_HOOKS]


def _native_hook_event_name(client: str, hook_id: str) -> str:
    if client == GITHUB_COPILOT_CLIENT:
        return GITHUB_COPILOT_HOOK_EVENTS[hook_id]
    return CODEX_HOOK_EVENTS[hook_id]


def _native_hook_client_label(client: str) -> str:
    if client == CLAUDE_CODE_CLIENT:
        return "Claude Code"
    if client == GITHUB_COPILOT_CLIENT:
        return "GitHub Copilot"
    if client == CODEX_CLIENT:
        return "Codex"
    return client


def _hook_adapter_code_prefix(request: CodexHookAdapterRequest) -> str:
    return "hooks-codex-adapter" if request.client == CODEX_CLIENT else "hooks-native-adapter"


def _unsafe_parent_directory_findings(root: Path, path: Path, code: str) -> list[Finding]:
    findings: list[Finding] = []
    current = path.parent
    while True:
        if not _is_within_root(root, current):
            break
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            findings.append(Finding("error", code, f"hook target parent is not a safe directory: {_rel_path(root, current)}", _rel_path(root, current)))
            break
        if current == root:
            break
        current = current.parent
    return findings


def _py_literal(value: object) -> str:
    return repr(value)


def _hook_policy_identity() -> dict[str, str]:
    source = Path(__file__).resolve()
    return {
        "schema": HOOK_POLICY_SCHEMA,
        "source": source.as_posix(),
        "sourceHash": _hook_policy_source_hash(source),
        "importRoot": _module_import_root().as_posix(),
    }


def _hook_policy_source_hash(source: Path) -> str:
    try:
        return hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    except OSError:
        return "unavailable"


def _hook_adapter_review_command(request: CodexHookAdapterRequest, mode: str) -> str:
    parts = ["hooks", "adapter", "--client", request.client, mode, "--scope", request.scope]
    if request.config_path:
        parts.extend(["--config-path", request.config_path])
    return mlh_command(*parts)


def _component_status(components: object, key: str) -> str:
    if not isinstance(components, dict):
        return "unknown"
    value = components.get(key)
    if not isinstance(value, dict):
        return "unknown"
    return str(value.get("status") or "unknown")


def _payload_value(payload: object, key: str) -> str:
    if not isinstance(payload, dict):
        return "<none>"
    value = payload.get(key)
    return str(value) if value not in (None, "") else "<none>"


def _lifecycle_phase_summary(payload: object) -> str:
    if not isinstance(payload, dict):
        return "active_phase=<none>; phase_status=<none>"
    plan_status = str(payload.get("plan_status") or "").strip().casefold()
    active_plan = str(payload.get("active_plan") or "").strip()
    active_phase = str(payload.get("active_phase") or "").strip()
    phase_status = str(payload.get("phase_status") or "").strip()
    last_completed_phase = str(payload.get("last_completed_phase") or "").strip()
    last_phase_status = str(payload.get("last_phase_status") or "").strip()
    if plan_status == "active" or active_plan:
        return f"active_phase={active_phase or '<none>'}; phase_status={phase_status or '<none>'}"
    if last_completed_phase or last_phase_status:
        return f"last_completed_phase={last_completed_phase or '<none>'}; last_phase_status={last_phase_status or '<none>'}"
    if active_phase or phase_status:
        return f"last_completed_phase={active_phase or '<none>'}; last_phase_status={phase_status or '<none>'}"
    return "active_phase=<none>; phase_status=<none>"


def _hook_target(root: Path, hook_id: str) -> Path:
    if hook_id != HOOK_PRE_COMMIT:
        return root / ".mylittleharness" / "hooks" / hook_id
    return root / ".git" / "hooks" / "pre-commit"


def _clean_hook_args(args: list[str]) -> list[str]:
    return args[1:] if args[:1] == ["--"] else args


def _is_within_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _rel_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _module_import_root() -> Path:
    return Path(__file__).resolve().parents[1]
