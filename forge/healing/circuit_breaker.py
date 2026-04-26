"""CircuitBreaker — CLOSED / OPEN / HALF_OPEN. Lifted from social-sdr.

- CLOSED: normal operation; consecutive failures counted
- OPEN: rejecting calls; after `cooldown_seconds`, transitions to HALF_OPEN
- HALF_OPEN: probes at `recovery_throughput`; on success returns to CLOSED, on
  failure returns to OPEN with a fresh cooldown timer
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    name: str
    fail_threshold: int = 3                # consecutive failures to trip
    cooldown_seconds: float = 60 * 60      # 60-min default
    recovery_throughput: float = 0.5       # 50% probe rate in HALF_OPEN

    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float = 0.0
    history: list[tuple[float, str]] = field(default_factory=list)

    def allow(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.opened_at >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                self._record("auto-transition OPEN -> HALF_OPEN")
            else:
                return False
        # HALF_OPEN: probabilistic probe
        return random.random() < self.recovery_throughput

    def record_success(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self._record("probe success: HALF_OPEN -> CLOSED")
            self.state = CircuitState.CLOSED
        self.consecutive_failures = 0

    def record_failure(self, reason: str = "") -> None:
        self.consecutive_failures += 1
        if self.state == CircuitState.HALF_OPEN:
            self._record(f"probe failure ({reason}): HALF_OPEN -> OPEN")
            self.state = CircuitState.OPEN
            self.opened_at = time.time()
            self.consecutive_failures = 0
            return
        if self.consecutive_failures >= self.fail_threshold and self.state == CircuitState.CLOSED:
            self._record(f"trip ({self.consecutive_failures} failures): CLOSED -> OPEN")
            self.state = CircuitState.OPEN
            self.opened_at = time.time()

    def _record(self, msg: str) -> None:
        self.history.append((time.time(), msg))


class CircuitRegistry:
    """One CircuitBreaker per (tool name | provider name)."""

    def __init__(
        self,
        fail_threshold: int = 3,
        cooldown_seconds: float = 60 * 60,
        recovery_throughput: float = 0.5,
    ) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._defaults = (fail_threshold, cooldown_seconds, recovery_throughput)

    def get(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            ft, cd, rt = self._defaults
            self._breakers[name] = CircuitBreaker(
                name=name, fail_threshold=ft, cooldown_seconds=cd, recovery_throughput=rt,
            )
        return self._breakers[name]

    def snapshot(self) -> dict[str, dict]:
        return {
            n: {"state": b.state.value, "failures": b.consecutive_failures, "history_len": len(b.history)}
            for n, b in self._breakers.items()
        }
