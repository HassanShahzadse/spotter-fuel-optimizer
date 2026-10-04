"""Counts external API calls made during a request (cache hits are not counted)."""

from __future__ import annotations

import contextlib
from collections import Counter
from contextvars import ContextVar

_calls: ContextVar[Counter | None] = ContextVar("external_api_calls", default=None)


def record_external_call(kind: str) -> None:
    counter = _calls.get()
    if counter is not None:
        counter[kind] += 1


@contextlib.contextmanager
def count_external_calls():
    counter: Counter = Counter()
    token = _calls.set(counter)
    try:
        yield counter
    finally:
        _calls.reset(token)
