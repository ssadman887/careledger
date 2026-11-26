"""Login throttling: count failed sign-ins per account and per client IP in a fixed window.

* Up to `login_max_failures_per_account` failures for one login name, and
  `login_max_failures_per_ip` from one address, within `login_window_seconds`; beyond that the
  login endpoint answers 429 with Retry-After, before checking the password (so a locked
  account cannot be probed). A successful sign-in clears the account counter.
* Counters live in Redis (shared by every API worker; keys expire with the window). If Redis is
  unreachable the limiter falls back to process memory and logs a warning, so authentication
  never fails just because the cache is down.
* Counters are independent of the database transaction: a failed login rolls back its request
  but still counts.
"""

import threading
import time
from dataclasses import dataclass
from typing import Protocol

import redis
import structlog

from app.core.config import get_settings

log = structlog.get_logger(__name__)


class Counter(Protocol):
    def hit(self, key: str, window: int) -> int: ...
    def get(self, key: str) -> tuple[int, int]: ...  # (count, seconds until reset)
    def clear(self, key: str) -> None: ...


class MemoryCounter:
    def __init__(self) -> None:
        self._data: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def _live(self, key: str) -> tuple[int, float] | None:
        entry = self._data.get(key)
        if entry and entry[1] <= time.monotonic():
            del self._data[key]
            return None
        return entry

    def hit(self, key: str, window: int) -> int:
        with self._lock:
            entry = self._live(key)
            count, expires = entry if entry else (0, time.monotonic() + window)
            self._data[key] = (count + 1, expires)
            return count + 1

    def get(self, key: str) -> tuple[int, int]:
        with self._lock:
            entry = self._live(key)
            if not entry:
                return 0, 0
            return entry[0], max(1, int(entry[1] - time.monotonic()))

    def clear(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._data.clear()


class RedisCounter:
    def __init__(self, url: str) -> None:
        self._redis = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)

    def hit(self, key: str, window: int) -> int:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window, nx=True)
        count, _ = pipe.execute()
        return int(count)

    def get(self, key: str) -> tuple[int, int]:
        pipe = self._redis.pipeline()
        pipe.get(key)
        pipe.ttl(key)
        value, ttl = pipe.execute()
        return (int(value) if value else 0), max(int(ttl), 0)

    def clear(self, key: str) -> None:
        self._redis.delete(key)


class FallbackCounter:
    """Redis when available, memory otherwise (re-tries Redis after a cool-down)."""

    RETRY_SECONDS = 30

    def __init__(self, primary: Counter, fallback: MemoryCounter) -> None:
        self.primary, self.fallback = primary, fallback
        self._down_until = 0.0

    def _use_primary(self) -> bool:
        return time.monotonic() >= self._down_until

    def _primary_failed(self, exc: redis.RedisError) -> None:
        log.warning("rate_limit_redis_unavailable", error=str(exc))
        self._down_until = time.monotonic() + self.RETRY_SECONDS

    def hit(self, key: str, window: int) -> int:
        if self._use_primary():
            try:
                return self.primary.hit(key, window)
            except redis.RedisError as exc:
                self._primary_failed(exc)
        return self.fallback.hit(key, window)

    def get(self, key: str) -> tuple[int, int]:
        if self._use_primary():
            try:
                return self.primary.get(key)
            except redis.RedisError as exc:
                self._primary_failed(exc)
        return self.fallback.get(key)

    def clear(self, key: str) -> None:
        if self._use_primary():
            try:
                self.primary.clear(key)
                return
            except redis.RedisError as exc:
                self._primary_failed(exc)
        self.fallback.clear(key)


@dataclass(frozen=True)
class Blocked:
    retry_after: int


class LoginLimiter:
    def __init__(self, counter: Counter, *, per_account: int, per_ip: int, window: int) -> None:
        self.counter = counter
        self.per_account, self.per_ip, self.window = per_account, per_ip, window

    @staticmethod
    def _keys(login: str, ip: str) -> tuple[str, str]:
        return f"rl:login:acct:{login.strip().lower()}", f"rl:login:ip:{ip}"

    def check(self, login: str, ip: str) -> Blocked | None:
        acct, addr = self._keys(login, ip)
        for key, limit in ((acct, self.per_account), (addr, self.per_ip)):
            count, ttl = self.counter.get(key)
            if count >= limit:
                return Blocked(retry_after=ttl or self.window)
        return None

    def failed(self, login: str, ip: str) -> None:
        for key in self._keys(login, ip):
            self.counter.hit(key, self.window)

    def succeeded(self, login: str, ip: str) -> None:
        self.counter.clear(self._keys(login, ip)[0])


_memory = MemoryCounter()
_limiter: LoginLimiter | None = None


def login_limiter() -> LoginLimiter:
    global _limiter
    if _limiter is None:
        s = get_settings()
        counter: Counter = (
            _memory
            if s.rate_limit_backend == "memory"
            else FallbackCounter(RedisCounter(s.redis_url), _memory)
        )
        _limiter = LoginLimiter(
            counter,
            per_account=s.login_max_failures_per_account,
            per_ip=s.login_max_failures_per_ip,
            window=s.login_window_seconds,
        )
    return _limiter


def reset_memory_counters() -> None:
    """Tests: forget all in-memory counters."""
    _memory.reset()
