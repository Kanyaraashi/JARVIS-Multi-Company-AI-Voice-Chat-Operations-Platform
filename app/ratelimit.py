"""A small in-memory rate limiter (sliding window).

It lives inside one API process. That is right for one container. If you ever run
several copies of the API, move the counters to Redis.
"""
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self, env_name: str, default: int, window_seconds: int = 60):
        self.env_name = env_name
        self.default = default
        self.window = window_seconds
        self.clock = time.monotonic
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        try:
            return int(os.getenv(self.env_name, self.default))
        except ValueError:
            return self.default

    def _trim(self, key: str, now: float) -> deque:
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if not hits:
            self._hits.pop(key, None)
        return hits

    def hit(self, key: str) -> None:
        with self._lock:
            now = self.clock()
            if len(self._hits) > 10000:  # never grow without limit
                for k in list(self._hits):
                    self._trim(k, now)
            self._hits[key].append(now)

    def retry_after(self, key: str) -> int:
        """0 if the key is allowed, otherwise the seconds until it is allowed again."""
        with self._lock:
            now = self.clock()
            hits = self._trim(key, now)
            if len(hits) < self.limit:
                return 0
            oldest_that_counts = hits[len(hits) - self.limit]
            return max(1, int(oldest_that_counts + self.window - now) + 1)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Requests per minute for one API key, and wrong-key attempts per minute for one address.
request_limiter = RateLimiter("RATE_LIMIT_PER_MINUTE", 120)
failure_limiter = RateLimiter("AUTH_FAIL_PER_MINUTE", 10)


def reject(seconds: int) -> None:
    raise HTTPException(
        status_code=429,
        detail=f"Too many requests. Try again in {seconds} seconds.",
        headers={"Retry-After": str(seconds)},
    )


def reset_all() -> None:
    request_limiter.reset()
    failure_limiter.reset()
