"""Pluggable embedders. Default = deterministic hash (zero deps).

Real options:
- OpenAIEmbedder    : OpenAI / OpenAI-compatible (text-embedding-3-small / -large)
- VoyageEmbedder    : Voyage AI (top of MTEB at small sizes)
- OnnxMiniLMEmbedder: local, free, ~22 MB MiniLM-L6-v2
- HashEmbedder      : default fallback (no install)

Embedder = Callable[[str], list[float]]   (sync; async wrapper if needed)

Pass any of these to ReasoningBank(embedder=...) or SkillSearchIndex.
"""
from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Callable
from typing import Any

Embedder = Callable[[str], list[float]]


# ---- baseline (no deps) ----------------------------------------------------

def hash_embedder(dim: int = 256) -> Embedder:
    """Deterministic bag-of-tokens hash. Cheap, no network, no install."""
    def embed(text: str) -> list[float]:
        vec = [0.0] * dim
        for token in text.lower().split():
            h = hashlib.md5(token.encode()).digest()
            for i, b in enumerate(h):
                vec[(i * 8 + b) % dim] += 1.0
        n = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / n for v in vec]
    return embed


# ---- OpenAI / OpenAI-compatible -------------------------------------------

def openai_embedder(
    model: str = "text-embedding-3-small",
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> Embedder:
    """OpenAI Embeddings API. base_url=... lets you point at OpenRouter, Together, etc."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise ImportError("install forge[openai]") from e
    kwargs: dict[str, Any] = {"api_key": api_key or os.getenv("OPENAI_API_KEY")}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)

    def embed(text: str) -> list[float]:
        if not text.strip():
            return [0.0] * 1536
        resp = client.embeddings.create(model=model, input=text[:8000])
        return list(resp.data[0].embedding)
    return embed


# ---- Voyage AI ------------------------------------------------------------

def voyage_embedder(model: str = "voyage-3-lite", api_key: str | None = None) -> Embedder:
    try:
        import voyageai  # type: ignore
    except ImportError as e:
        raise ImportError("pip install voyageai") from e
    client = voyageai.Client(api_key=api_key or os.getenv("VOYAGE_API_KEY"))

    def embed(text: str) -> list[float]:
        if not text.strip():
            return [0.0] * 512
        return client.embed([text[:16000]], model=model, input_type="document").embeddings[0]
    return embed


# ---- Local ONNX MiniLM ----------------------------------------------------

def onnx_minilm_embedder(model_path: str | None = None) -> Embedder:
    """sentence-transformers/all-MiniLM-L6-v2 via fastembed (lightweight onnxruntime)."""
    try:
        from fastembed import TextEmbedding  # type: ignore
    except ImportError as e:
        raise ImportError("pip install fastembed") from e
    model = TextEmbedding(model_name=model_path or "BAAI/bge-small-en-v1.5")

    def embed(text: str) -> list[float]:
        if not text.strip():
            return [0.0] * 384
        # fastembed returns generator of np arrays
        return list(next(model.embed([text[:8000]])))
    return embed


# ---- factory --------------------------------------------------------------

def make_embedder(kind: str = "hash", **kwargs) -> Embedder:
    """Resolve by name. Useful from config files / YAML."""
    kind = kind.lower()
    if kind == "hash":
        return hash_embedder(**kwargs)
    if kind == "openai":
        return openai_embedder(**kwargs)
    if kind == "voyage":
        return voyage_embedder(**kwargs)
    if kind in {"onnx", "minilm", "fastembed"}:
        return onnx_minilm_embedder(**kwargs)
    raise ValueError(f"unknown embedder {kind!r}")
