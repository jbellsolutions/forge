# Contributing to forge

Thanks for opening this. forge stays small on purpose; PRs that complicate
the kernel without proving value get pushed back. PRs that close a real gap
land fast.

## Dev setup

```bash
git clone https://github.com/jbellsolutions/forge.git
cd forge
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,anthropic,mcp,openai]"
```

## Running tests

```bash
pytest -q              # 70+ tests, no API keys needed
forge doctor           # environment audit
```

## Code style

- Type hints on every public function.
- `from __future__ import annotations` at the top of every module.
- Lazy-import optional vendor SDKs (`anthropic`, `openai`, `mcp`, `composio`,
  `opentelemetry`) inside the constructor of the class that needs them so
  base install stays pure-Python.
- Public API lives at module re-export level (`forge.kernel`, `forge.swarm`,
  ...) and is mirrored from `forge/__init__.py` `__all__`. Do not break
  symbols listed there without bumping the major version.

## Layer rules

forge has 8 layers (L0 kernel → L7 observability — see README). PRs that
violate layer ordering get rejected:

- L0 may not import from any higher layer.
- L1–L7 may only import from layers below them.
- The hook bus (L0) is the cross-cutting seam; subscribe to it instead of
  reaching across layers.

## Adding a primitive

1. Pick the right layer. New tool → L2. New consensus algo → L4. New skill
   policy → L5. New trace format → L7.
2. Re-export from the layer's `__init__.py` and the top-level `forge/__init__.py`.
3. Add tests under `tests/test_<layer>.py`.
4. Update `CHANGELOG.md` under "Unreleased".
5. If it's user-facing, mention in the README's relevant section.

## Versioning

forge uses [Semantic Versioning](https://semver.org/) starting at v0.1.0:

- `0.x.y` → x = minor (additive), y = patch (fix). Breaking changes allowed
  in minor bumps until 1.0.
- After 1.0, breaking changes require a major bump and a deprecation cycle.

## Releasing (maintainer notes)

```bash
# 1. Bump version in pyproject.toml + forge/__init__.py
# 2. Update CHANGELOG.md
# 3. Commit, tag, push
git commit -am "Release v0.x.y"
git tag v0.x.y
git push origin main --tags

# 4. Build + publish
python -m build
twine upload dist/forge-0.x.y*
```

## Reporting issues

Open at https://github.com/jbellsolutions/forge/issues with:

- forge version (`pip show forge`)
- Python version + OS
- Output of `forge doctor`
- Minimal reproduction
