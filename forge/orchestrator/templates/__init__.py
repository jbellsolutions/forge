"""Project scaffold templates — applied locally by `forge sync pull-and-apply`
when a `start_project` PendingAction is approved.

Each template is a dict {filename: content} keyed off `template_name`.
The local apply step writes them under `examples/<project_name>/`.
"""
from __future__ import annotations

from . import operator, research, sdr, custom


TEMPLATES = {
    "operator": operator.FILES,
    "research": research.FILES,
    "sdr":      sdr.FILES,
    "custom":   custom.FILES,
}


def render(template: str, project_name: str, description: str = "") -> dict[str, str]:
    """Return a {relpath: content} dict with template placeholders filled."""
    if template not in TEMPLATES:
        raise ValueError(f"unknown template: {template!r}")
    files = TEMPLATES[template]
    out: dict[str, str] = {}
    for relpath, body in files.items():
        out[relpath.format(name=project_name)] = body.format(
            name=project_name, description=description or f"forge project {project_name}",
        )
    return out
