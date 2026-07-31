"""The flows.

A flow is a named composition of gates, model calls and checkpoints
operating on one contract — a script with a run directory, never a chat
thread. Flows never talk to each other; a program coordinates them, and
envelopes are the only interface.

Shared anatomy lives in `base`, the review ladder in `ladder` and `review`,
and each flow is a module that composes them.
"""

from __future__ import annotations

from workflows.flows.base import FlowContext, FlowError, Profile
from workflows.flows.ladder import Escalation

FLOWS = ("implement", "fanout", "assure", "adjudicate", "benchmark")

__all__ = ["Escalation", "FLOWS", "FlowContext", "FlowError", "Profile"]
