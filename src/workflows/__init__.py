"""Deterministic orchestration for LLM coding agents.

Models do the judgment; this package does the protocol. Nothing here calls a
model: prompt composition, validation, gates, routing, and run records are
deterministic code (see docs/decisions/0001-llm-for-judgment-code-for-protocol.md).
"""

from __future__ import annotations

__version__ = "0.0.0"

__all__ = ["__version__"]
