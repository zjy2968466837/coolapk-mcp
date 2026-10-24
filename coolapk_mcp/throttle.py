"""请求节制 — 限速、TTL 缓存、瞬态重试

目标是让客户端表现得像一个克制的人类用户，从源头降低触发风控的概率：
- 相邻 API 请求强制间隔（默认 1.2s，可用 COOLAPK_MIN_INTERVAL 覆盖）
- GET 成功响应按端点 TTL 缓存，重复查询不再打到服务器
- 仅对瞬态错误（超时/连接失败/5xx/429）做指数退避重试
- 验证码类错误不重试，改为负缓存，短期内绕开该端点

设 COOLAPK_NO_CACHE=1 可禁用缓存（调试用）。
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections import OrderedDict


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


MIN_INTERVAL = _env_float("COOLAPK_MIN_INTERVAL", 1.2)
MAX_RETRIES = int(_env_float("COOLAPK_MAX_RETRIES", 2))
CACHE_ENABLED = os.environ.get("COOLAPK_NO_CACHE", "") not in ("1", "true", "True")

# 各端点缓存时长（秒）：内容越稳定 TTL 越长
_TTL_BY_PREFIX: list[tuple[str, float]] = [
    ("/v6/feed/detail", 600),
    ("/v6/feed/replyList", 600),
    ("/v6/feed/hotReplyList", 600),
    ("/v6/user/space", 600),
    ("/v6/user/profile", 600),
    ("/v6/topic/newTagDetail", 600),
    ("/v6/search", 300),
]
_DEFAULT_TTL = 120.0


def ttl_for(path: str) -> float:
    for prefix, ttl in _TTL_BY_PREFIX:
        if path.startswith(prefix):
            return ttl
    return _DEFAULT_TTL


class RateLimiter:
    """全局串行限速：无论并发多少调用，相邻请求间隔不小于 min_interval"""

    def __init__(self, min_interval: float = MIN_INTERVAL):
        self.min_interval = max(0.0, min_interval)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class TTLCache:
    """LRU + TTL 缓存，只存 GET 的成功响应"""

    def __init__(self, maxsize: int = 256):
        self.maxsize = maxsize
        self._store: OrderedDict[str, tuple[float, object]] = OrderedDict()

    def get(self, key: str) -> object | None:
        hit = self._store.get(key)
        if hit is None:
            return None
        expires, value = hit
        if time.monotonic() > expires:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def put(self, key: str, value: object, ttl: float) -> None:
        self._store[key] = (time.monotonic() + ttl, value)
        self._store.move_to_end(key)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)


async def backoff_sleep(attempt: int) -> None:
    """指数退避 + 抖动：0.8s, 1.6s, ..."""
    delay = 0.8 * (2 ** attempt) + random.uniform(0, 0.4)
    await asyncio.sleep(delay)
