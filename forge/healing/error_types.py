"""5-class ErrorType taxonomy. Lifted from social-sdr/scripts/self_heal.py."""
from __future__ import annotations

import re
from enum import Enum


class ErrorType(str, Enum):
    TRANSIENT = "transient"          # network blip, rate limit, retry will work
    ENVIRONMENTAL = "environmental"  # missing binary, env var, port — wait for human
    DATA = "data"                    # malformed input/output — skip and log
    LOGIC = "logic"                  # bug in agent reasoning — flag for review
    RESOURCE = "resource"            # OOM, disk full, quota exceeded — back off hard


# Regex hints tuned from real failure traces.
_PATTERNS: list[tuple[ErrorType, list[re.Pattern]]] = [
    (ErrorType.TRANSIENT, [
        re.compile(r"timeout|timed out|connection reset|ECONNRESET|EAI_AGAIN", re.I),
        re.compile(r"rate.?limit|429|too many requests", re.I),
        re.compile(r"503|502|504|gateway", re.I),
    ]),
    (ErrorType.ENVIRONMENTAL, [
        re.compile(r"command not found|binary not found|FileNotFoundError|No such file", re.I),
        re.compile(r"permission denied|EACCES", re.I),
        re.compile(r"missing.*api.?key|unauthorized.*401", re.I),
    ]),
    (ErrorType.DATA, [
        re.compile(r"json.?decode|invalid.*json|malformed|ValidationError", re.I),
        re.compile(r"expected .* got|UnicodeDecode", re.I),
    ]),
    (ErrorType.RESOURCE, [
        re.compile(r"out of memory|OOM|disk full|ENOSPC|quota.?exceeded", re.I),
    ]),
]


def classify(message: str) -> ErrorType:
    """Best-effort classify a free-text error message."""
    if not message:
        return ErrorType.LOGIC
    for et, patterns in _PATTERNS:
        for p in patterns:
            if p.search(message):
                return et
    return ErrorType.LOGIC


# Per-class retry policy: (max_retries, base_delay_seconds, multiplier)
RETRY_POLICY: dict[ErrorType, tuple[int, float, float]] = {
    ErrorType.TRANSIENT:     (5, 1.0, 2.0),
    ErrorType.ENVIRONMENTAL: (0, 0.0, 1.0),  # don't retry — needs human
    ErrorType.DATA:          (1, 0.0, 1.0),  # try once more, then give up
    ErrorType.LOGIC:         (0, 0.0, 1.0),
    ErrorType.RESOURCE:      (2, 30.0, 2.0),
}
