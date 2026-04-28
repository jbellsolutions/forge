"""Phase 4 — Spawner max_spawn_depth nesting + depth-budget decay."""
from __future__ import annotations

import pytest

from forge.swarm import (
    DEPTH_BUDGET_DECAY,
    SpawnDepthExceeded,
    Spawner,
)
from forge.tools.registry import ToolRegistry


def _bare_spawner(**kwargs) -> Spawner:
    return Spawner(tools=ToolRegistry(), **kwargs)


def test_spawn_depth_default_zero_refuses_child():
    s = _bare_spawner()
    assert s.max_spawn_depth == 0
    assert s._current_depth == 0
    with pytest.raises(SpawnDepthExceeded):
        s.make_child()


def test_make_child_decrements_depth_and_decays_budget():
    parent = _bare_spawner(max_turns=8, max_spawn_depth=2)
    child = parent.make_child()
    assert child.max_spawn_depth == 1
    assert child._current_depth == 1
    assert child.max_turns == int(8 * DEPTH_BUDGET_DECAY)
    grandchild = child.make_child()
    assert grandchild.max_spawn_depth == 0
    assert grandchild._current_depth == 2
    assert grandchild.max_turns == max(1, int(child.max_turns * DEPTH_BUDGET_DECAY))


def test_three_deep_chain_then_refuses():
    s = _bare_spawner(max_turns=16, max_spawn_depth=3)
    a = s.make_child()
    b = a.make_child()
    c = b.make_child()
    assert c.max_spawn_depth == 0
    assert c._current_depth == 3
    with pytest.raises(SpawnDepthExceeded):
        c.make_child()


def test_max_turns_floor_is_one():
    """A long chain mustn't decay max_turns to zero."""
    s = _bare_spawner(max_turns=2, max_spawn_depth=5)
    cur = s
    for _ in range(5):
        cur = cur.make_child()
        assert cur.max_turns >= 1


def test_shared_tools_and_hooks_propagate():
    tools = ToolRegistry()
    parent = Spawner(tools=tools, max_spawn_depth=1)
    child = parent.make_child()
    assert child.tools is tools
    assert child.hooks is parent.hooks


def test_child_inherits_base_instructions_unless_overridden():
    parent = _bare_spawner(
        base_instructions="custom-parent", max_spawn_depth=2,
    )
    inherited = parent.make_child()
    assert inherited.base_instructions == "custom-parent"
    overridden = parent.make_child(base_instructions="custom-child")
    assert overridden.base_instructions == "custom-child"
