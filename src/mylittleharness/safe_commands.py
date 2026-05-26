from __future__ import annotations

import re
import shlex


SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SHELL_META_RE = re.compile(r"[\r\n;&|`$<>]")


def shell_arg(value: object, *, placeholder_ok: bool = True) -> str:
    text = str(value or "").strip()
    if not text:
        return "''"
    if placeholder_ok and _placeholder_token(text):
        return text
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text
    if SAFE_TOKEN_RE.fullmatch(text):
        return text
    return shlex.quote(text)


def mlh_command(*parts: object, root: object = "<root>") -> str:
    return " ".join(shell_arg(part) for part in ("mylittleharness", "--root", root, *parts) if str(part or "").strip())


def safe_item_id(value: object, *, placeholder: str = "<id>") -> str:
    text = str(value or "").strip()
    return text if SAFE_ID_RE.fullmatch(text) else placeholder


def safe_double_quoted(value: object, *, placeholder: str = "<value>") -> str:
    text = str(value or "").strip()
    if not text or SHELL_META_RE.search(text):
        text = placeholder
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def safe_intent_text(value: object, *, placeholder: str = "<operator-action>") -> str:
    text = str(value or "").strip()
    if not text or SHELL_META_RE.search(text):
        return placeholder
    return re.sub(r"\s+", " ", text)


def is_single_safe_command(command: object) -> bool:
    text = str(command or "").strip()
    if not text:
        return False
    if re.search(r"[\r\n;`]|&&|\|\||(?<!:)[<>]|\$\(|\|", text):
        return False
    return True


def _placeholder_token(value: str) -> bool:
    return (value.startswith("<") and value.endswith(">")) or (value.startswith("[") and value.endswith("]"))
