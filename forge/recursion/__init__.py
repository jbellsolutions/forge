"""Recursive self-modification — propose, apply, score, keep-or-rollback."""
from .llm_proposer import (
    PROGRAM_DIRECTIVE, ResultsLedger, parse_diffs, propose_with_llm,
)
from .proposer import HarnessDiff, TraceAnalyzer, apply, fork, keep_or_rollback, propose

__all__ = [
    "HarnessDiff", "TraceAnalyzer",
    "apply", "fork", "keep_or_rollback", "propose",
    "PROGRAM_DIRECTIVE", "ResultsLedger", "parse_diffs", "propose_with_llm",
]
