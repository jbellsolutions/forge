"""OpenTelemetry exporter — optional.

Wraps the existing Telemetry hook subscriptions with real OTel spans:
  - one span per session (session_id)
  - child spans per tool call
  - attributes: agent, tool name, input/output tokens, cost, error class

Stays inert if `opentelemetry-api` is not installed; falls back to plain
Telemetry. Safe to import in any environment.
"""
from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Any

from ..kernel.hooks import HookBus, HookContext

log = logging.getLogger("forge.otel")


def _try_import_otel():
    try:
        from opentelemetry import trace  # type: ignore
        from opentelemetry.sdk.resources import Resource  # type: ignore
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore
        from opentelemetry.sdk.trace.export import (  # type: ignore
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        return trace, Resource, TracerProvider, BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        return None


class OTelExporter:
    """OTel hook listener. If OTel isn't installed, becomes a no-op shim."""

    def __init__(
        self,
        service_name: str = "forge",
        *,
        exporter: Any = None,
        endpoint: str | None = None,
    ) -> None:
        self.enabled = False
        self._tracer = None
        self._sessions: dict[str, Any] = {}   # session_id -> span context manager
        self._tool_spans: dict[str, Any] = {}  # tool_call_id -> span

        otel = _try_import_otel()
        if not otel:
            log.info("opentelemetry not installed; OTelExporter is a no-op")
            return

        trace, Resource, TracerProvider, BatchSpanProcessor, ConsoleSpanExporter = otel
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))

        if exporter is None:
            if endpoint:
                try:
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore
                        OTLPSpanExporter,
                    )
                    exporter = OTLPSpanExporter(endpoint=endpoint)
                except ImportError:
                    log.warning("OTLP exporter not installed; falling back to console")
                    exporter = ConsoleSpanExporter()
            else:
                exporter = ConsoleSpanExporter()

        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        self._tracer = trace.get_tracer("forge")
        self.enabled = True

    def attach(self, hooks: HookBus) -> None:
        if not self.enabled:
            return

        @hooks.on_session_start
        def _start(ctx: HookContext) -> None:
            span = self._tracer.start_span(
                f"session:{ctx.agent_name}",
                attributes={"forge.session_id": ctx.session_id, "forge.agent": ctx.agent_name},
            )
            self._sessions[ctx.session_id] = span

        @hooks.on_pre_tool
        def _pre(ctx: HookContext) -> None:
            if not ctx.tool_call:
                return
            span = self._tracer.start_span(
                f"tool:{ctx.tool_call.name}",
                attributes={
                    "forge.tool": ctx.tool_call.name,
                    "forge.session_id": ctx.session_id,
                    "forge.verdict_pre": ctx.verdict.value,
                },
            )
            self._tool_spans[ctx.tool_call.id] = span

        @hooks.on_post_tool
        def _post(ctx: HookContext) -> None:
            if not ctx.tool_call:
                return
            span = self._tool_spans.pop(ctx.tool_call.id, None)
            if span is None:
                return
            tr = ctx.tool_result
            span.set_attribute("forge.is_error", bool(tr and tr.is_error))
            span.set_attribute("forge.verdict_post", ctx.verdict.value)
            if ctx.notes:
                span.set_attribute("forge.notes", "; ".join(ctx.notes))
            if tr and tr.is_error:
                span.set_status(_status_error(tr.content))
            span.end()

        @hooks.on_session_end
        def _end(ctx: HookContext) -> None:
            span = self._sessions.pop(ctx.session_id, None)
            if span is None:
                return
            usage = ctx.extra.get("usage", {}) or {}
            span.set_attribute("forge.input_tokens", usage.get("input_tokens", 0))
            span.set_attribute("forge.output_tokens", usage.get("output_tokens", 0))
            span.end()


def _status_error(message: str):
    try:
        from opentelemetry.trace import Status, StatusCode  # type: ignore
        return Status(StatusCode.ERROR, description=message[:200])
    except ImportError:
        return None
