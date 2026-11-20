from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable
from math import ceil
from threading import Lock
from time import monotonic

from fastapi import HTTPException


class RateLimiter:
    """Bound work per key within one process without trusting client headers."""

    def __init__(self, max_attempts: int, window_seconds: int, *, max_keys: int = 4096) -> None:
        if min(max_attempts, window_seconds, max_keys) < 1:
            raise ValueError("Rate limit parameters must be positive.")
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._windows: OrderedDict[Hashable, tuple[float, int]] = OrderedDict()
        self._lock = Lock()

    def check(self, key: Hashable, *, detail: str) -> None:
        with self._lock:
            now = monotonic()
            while self._windows and next(iter(self._windows.values()))[0] <= now:
                self._windows.popitem(last=False)

            window = self._windows.get(key)
            if window is None and len(self._windows) < self.max_keys:
                self._windows[key] = (now + self.window_seconds, 1)
                return
            if window is not None and window[1] < self.max_attempts:
                self._windows[key] = (window[0], window[1] + 1)
                return

            expires = window[0] if window is not None else next(iter(self._windows.values()))[0]
            retry_after = max(1, ceil(expires - now))
        raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(retry_after)})

    def reset(self, key: Hashable) -> None:
        with self._lock:
            self._windows.pop(key, None)
