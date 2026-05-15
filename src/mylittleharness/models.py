from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    source: str | None = None
    line: int | None = None
    route_id: str | None = None
    mutates: bool = False
    requires_human_gate: bool = False
    gate_class: str = ""
    human_gate_reason: str = ""
    allowed_decisions: tuple[str, ...] = ()
    advisory: bool = True

    def render(self) -> str:
        location = ""
        if self.source:
            location = self.source
            if self.line:
                location = f"{location}:{self.line}"
            location = f" ({location})"
        return f"[{self.severity.upper()}] {self.code}: {self.message}{location}"

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "line": self.line,
            "route_id": self.route_id,
            "mutates": self.mutates,
            "requires_human_gate": self.requires_human_gate,
            "gate_class": self.gate_class,
            "human_gate_reason": self.human_gate_reason,
            "allowed_decisions": list(self.allowed_decisions),
            "advisory": self.advisory,
        }


@dataclass(frozen=True)
class SessionActiveWorkRecord:
    rel_path: str
    data: dict[str, object]

    @property
    def session_id(self) -> str:
        return str(self.data.get("session_id") or "")

    @property
    def run_id(self) -> str:
        return str(self.data.get("run_id") or "")

    @property
    def agent_id(self) -> str:
        return str(self.data.get("agent_id") or "")

    @property
    def status(self) -> str:
        return str(self.data.get("status") or "")

    @property
    def active_plan(self) -> str:
        return str(self.data.get("active_plan") or "")

    @property
    def active_phase(self) -> str:
        return str(self.data.get("active_phase") or "")

    @property
    def execution_slice(self) -> str:
        return str(self.data.get("execution_slice") or "")

    @property
    def last_heartbeat_at_utc(self) -> str:
        return str(self.data.get("last_heartbeat_at_utc") or "")

    @property
    def lease_expires_at(self) -> str:
        return str(self.data.get("lease_expires_at") or "")
