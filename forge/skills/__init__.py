"""L5 self-improvement — skills with autosynth + eval gate + search."""
from .autosynth import SynthResult, autosynth, default_proposer
from .eval_gate import (
    CONFIDENCE_MARGIN,
    MIN_SAMPLES,
    EvalReport,
    evaluate,
    promote_if_passing,
)
from .search import SkillHit, SkillSearchIndex
from .skill import SkillRun, SkillStore

__all__ = [
    "CONFIDENCE_MARGIN", "MIN_SAMPLES",
    "EvalReport", "evaluate", "promote_if_passing",
    "SkillHit", "SkillSearchIndex",
    "SkillRun", "SkillStore",
    "SynthResult", "autosynth", "default_proposer",
]
