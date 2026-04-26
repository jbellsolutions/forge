"""Backward-compatibility regression tests for the recursion proposer's
optional `intel_context` parameter.

The contract is:
1. `intel_context=None` (or omitted) → byte-identical user prompt to
   pre-extension behavior. No call site that worked before should break.
2. `intel_context="..."` → INTEL_PREAMBLE prepended, with the AutoAgent
   regularizer paragraph included verbatim. The signals are framed as
   "informational only" — never as license to overfit.
3. `recurse_once(..., intel_context=...)` threads the context through to
   `propose_with_llm` unchanged.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from forge.kernel.types import AssistantTurn, Message
from forge.providers.base import Provider
from forge.providers.mock import MockProvider
from forge.providers import load_profile
from forge.recursion.llm_proposer import (
    INTEL_PREAMBLE,
    PROGRAM_DIRECTIVE,
    default_prompt,
    propose_with_llm,
)


# ---------------------------------------------------------------------------
# A capture provider that records every (messages, kwargs) the loop sends.
# ---------------------------------------------------------------------------

class CaptureProvider(Provider):
    def __init__(self) -> None:
        self.profile = load_profile("mock")
        self.calls: list[dict] = []
        self.next_text = "[]"

    async def generate(self, messages, tools=None, max_tokens=2048, **kw):
        self.calls.append({"messages": [m for m in messages], "max_tokens": max_tokens})
        return AssistantTurn(text=self.next_text, tool_calls=[],
                             usage={"input_tokens": 1, "output_tokens": 1})


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def _user_prompt(provider: CaptureProvider) -> str:
    msgs = provider.calls[-1]["messages"]
    user = next(m for m in msgs if m.role == "user")
    return user.content if isinstance(user.content, str) else ""


def test_no_intel_context_prompt_is_byte_identical_to_baseline(tmp_path: Path) -> None:
    """Backward-compat regression: passing intel_context=None must produce
    the exact same user prompt the proposer used before this extension."""
    traces = tmp_path / "traces"
    traces.mkdir()

    # Baseline: what the prompt looks like without intel.
    from forge.recursion.proposer import TraceAnalyzer
    symptoms = TraceAnalyzer(traces).symptoms()
    baseline_prompt = default_prompt(PROGRAM_DIRECTIVE, symptoms)

    p1 = CaptureProvider()
    asyncio.run(propose_with_llm(p1, traces))  # no intel
    assert _user_prompt(p1) == baseline_prompt

    # Explicit None → also identical.
    p2 = CaptureProvider()
    asyncio.run(propose_with_llm(p2, traces, intel_context=None))
    assert _user_prompt(p2) == baseline_prompt


def test_intel_context_is_prepended_with_regularizer(tmp_path: Path) -> None:
    traces = tmp_path / "traces"
    traces.mkdir()

    intel = "Anthropic shipped Sonnet 4.5; OpenAI launched GPT-5 with tool use."
    p = CaptureProvider()
    asyncio.run(propose_with_llm(p, traces, intel_context=intel))
    prompt = _user_prompt(p)

    # The intel header must appear and contain the user-supplied text.
    assert "## Recent industry signals" in prompt
    assert "Anthropic shipped Sonnet 4.5" in prompt
    assert "OpenAI launched GPT-5" in prompt

    # The regularizer paragraph must appear in the intel preamble.
    assert "regularizer above STILL APPLIES" in prompt
    assert "vanished from the context" in prompt

    # The directive (with its own regularizer) must STILL appear after.
    assert "Forge Self-Modification Directive" in prompt
    assert "FIXED ADAPTER BOUNDARY" in prompt

    # Order: intel preamble comes BEFORE the directive (so the directive
    # has the last word on what's allowed).
    intel_idx = prompt.index("Recent industry signals")
    directive_idx = prompt.index("Forge Self-Modification Directive")
    assert intel_idx < directive_idx


def test_intel_preamble_template_renders_cleanly() -> None:
    rendered = INTEL_PREAMBLE.format(context="line 1\nline 2")
    assert "line 1" in rendered and "line 2" in rendered
    assert "{context}" not in rendered


def test_recurse_once_threads_intel_through(tmp_path: Path) -> None:
    """The driver should pass `intel_context` to `propose_with_llm`.
    If it doesn't, the captured prompt won't contain the intel marker."""
    from forge.recursion.loop import recurse_once

    p = CaptureProvider()
    p.next_text = "[]"  # no diffs → loop short-circuits cleanly

    home = tmp_path / "home"
    home.mkdir()

    def score_fn(_: Path) -> float:
        return 0.0

    asyncio.run(recurse_once(
        home, p, score_fn,
        intel_context="REGRESSION_MARKER_42",
    ))
    assert "REGRESSION_MARKER_42" in _user_prompt(p)
    assert "Recent industry signals" in _user_prompt(p)


def test_recurse_once_default_no_intel(tmp_path: Path) -> None:
    """No intel kwarg → no intel preamble in the prompt."""
    from forge.recursion.loop import recurse_once
    p = CaptureProvider()
    p.next_text = "[]"
    home = tmp_path / "home"; home.mkdir()
    asyncio.run(recurse_once(home, p, lambda _: 0.0))
    assert "Recent industry signals" not in _user_prompt(p)
