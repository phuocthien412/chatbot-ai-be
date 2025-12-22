import time
from collections import deque
from typing import Deque, Dict

class WindowLimiter:
    def __init__(self):
        self._buckets: Dict[str, Deque[float]] = {}

    def allow(self, key: str, max_per_min: int) -> bool:
        now = time.monotonic()
        window = self._buckets.setdefault(key, deque())
        # drop events older than 60s
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= max_per_min:
            return False
        window.append(now)
        return True

ip_limiter = WindowLimiter()
client_limiter = WindowLimiter()
