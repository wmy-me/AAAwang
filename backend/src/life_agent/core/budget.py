"""Shared, pre-reserved execution budget for one durable Run."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Lock


class BudgetExceededError(RuntimeError):
    """Raised when a new model or remote call cannot be reserved."""


@dataclass(frozen=True)
class BudgetLimits:
    model_requests: int = 10
    delegations: int = 4
    mcp_attempts: int = 4
    remote_calls: int = 8
    wall_clock_seconds: float = 180.0


@dataclass
class RunBudget:
    """Mutable budget shared by the coordinator and all delegated branches."""

    limits: BudgetLimits = field(default_factory=BudgetLimits)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    model_requests: int = 0
    delegations: int = 0
    mcp_attempts: int = 0
    remote_calls: int = 0
    termination_reason: str | None = None
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, object] | None) -> "RunBudget":
        """Restore server-persisted counters when a claimed Run is retried."""
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("limits"), dict):
            return cls()
        try:
            raw = snapshot["limits"]
            limits = BudgetLimits(**{field: raw[field] for field in BudgetLimits.__dataclass_fields__})
            started = datetime.fromisoformat(str(snapshot["started_at"]))
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            return cls(
                limits=limits, started_at=started,
                model_requests=max(0, int(snapshot.get("model_requests", 0))),
                delegations=max(0, int(snapshot.get("delegations", 0))),
                mcp_attempts=max(0, int(snapshot.get("mcp_attempts", 0))),
                remote_calls=max(0, int(snapshot.get("remote_calls", 0))),
            )
        except (KeyError, TypeError, ValueError):
            return cls()

    def reserve(self, kind: str) -> None:
        """Atomically reserve one attempt before starting external work."""
        with self._lock:
            if self.termination_reason is not None:
                raise BudgetExceededError(self.termination_reason)
            if self._expired():
                self.termination_reason = "timeout"
                raise BudgetExceededError("timeout")
            if kind == "model":
                if self.model_requests >= self.limits.model_requests:
                    self.termination_reason = "model_budget_exhausted"
                    raise BudgetExceededError(self.termination_reason)
                self.model_requests += 1
            elif kind == "delegation":
                if self.delegations >= self.limits.delegations:
                    self.termination_reason = "delegation_budget_exhausted"
                    raise BudgetExceededError(self.termination_reason)
                self.delegations += 1
            elif kind == "mcp":
                if self.mcp_attempts >= self.limits.mcp_attempts:
                    self.termination_reason = "mcp_budget_exhausted"
                    raise BudgetExceededError(self.termination_reason)
                if self.remote_calls >= self.limits.remote_calls:
                    self.termination_reason = "remote_budget_exhausted"
                    raise BudgetExceededError(self.termination_reason)
                self.mcp_attempts += 1
                self.remote_calls += 1
            elif kind == "discovery":
                if self.remote_calls >= self.limits.remote_calls:
                    self.termination_reason = "remote_budget_exhausted"
                    raise BudgetExceededError(self.termination_reason)
                self.remote_calls += 1
            else:
                raise ValueError(f"unsupported budget reservation: {kind}")

    def stop(self, reason: str) -> None:
        with self._lock:
            if not reason.strip():
                raise ValueError("termination reason cannot be empty")
            self.termination_reason = reason

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "limits": {
                    "model_requests": self.limits.model_requests,
                    "delegations": self.limits.delegations,
                    "mcp_attempts": self.limits.mcp_attempts,
                    "remote_calls": self.limits.remote_calls,
                    "wall_clock_seconds": self.limits.wall_clock_seconds,
                },
                "model_requests": self.model_requests,
                "delegations": self.delegations,
                "mcp_attempts": self.mcp_attempts,
                "remote_calls": self.remote_calls,
                "termination_reason": self.termination_reason,
                "started_at": self.started_at.isoformat(),
            }

    def _expired(self) -> bool:
        return datetime.now(UTC) >= self.started_at + timedelta(
            seconds=self.limits.wall_clock_seconds
        )
