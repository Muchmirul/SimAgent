"""Compatibility shim: the mind trace was promoted to core.journal (P3).

Everything historical keeps importing from here; new code should import
simagent.core.journal directly. Scheduled for deletion with the other legacy
paths at the end of P5's compatibility window.
"""
from .core.journal import (  # noqa: F401
    MAX_RESULT_CHARS,
    MAX_THOUGHT_CHARS,
    TRACE_FILE,
    Journal,
    TraceRecorder,
    diff_vars,
    equation_of_state,
    read_trace,
    replay_vars,
)

__all__ = [
    "MAX_RESULT_CHARS", "MAX_THOUGHT_CHARS", "TRACE_FILE",
    "Journal", "TraceRecorder", "diff_vars", "equation_of_state",
    "read_trace", "replay_vars",
]
