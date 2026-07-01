from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: int = 60) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> RateLimitResult:
        now = monotonic()
        events = self._events[key]
        self._prune(events, now)
        if len(events) >= self.limit:
            retry_after = int(self.window_seconds - (now - events[0])) + 1
            return RateLimitResult(allowed=False, retry_after_seconds=max(1, retry_after))
        events.append(now)
        return RateLimitResult(allowed=True, retry_after_seconds=0)

    def clear(self, key: str | None = None) -> None:
        if key is None:
            self._events.clear()
            return
        self._events.pop(key, None)

    reset = clear

    def _prune(self, events: deque[float], now: float) -> None:
        while events and now - events[0] >= self.window_seconds:
            events.popleft()
