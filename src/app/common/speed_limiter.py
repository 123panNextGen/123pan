"""基于令牌桶算法的速度限制器。

用于限制下载/上传速度，支持动态调整速率。
"""

import threading
import time
from typing import Optional


class SpeedLimiter:
    """令牌桶速度限制器，线程安全。

    以 KB/s 为单位控制传输速率。
    当 limit=0 时表示不限制速度。
    """

    def __init__(self, limit_kbps: int = 0):
        """初始化限速器。

        Args:
            limit_kbps: 速度限制（KB/s），0 表示不限制。
        """
        self._limit_kbps = limit_kbps  # KB/s
        self._lock = threading.Lock()
        self._last_refill = time.monotonic()
        self._update_max_tokens()
        # 初始令牌设为最大容量，允许立即开始传输
        self._tokens: float = self._max_tokens if limit_kbps > 0 else float("inf")

    @property
    def limit_kbps(self) -> int:
        return self._limit_kbps

    def set_limit(self, limit_kbps: int):
        """动态调整速度限制。

        Args:
            limit_kbps: 新的速度限制（KB/s），0 表示不限制。
        """
        with self._lock:
            self._limit_kbps = max(0, limit_kbps)
            self._update_max_tokens()
            # 重置令牌，避免旧速率下的令牌累积
            self._tokens = min(self._tokens, self._max_tokens)

    def _update_max_tokens(self):
        """根据当前限制更新最大令牌数。"""
        if self._limit_kbps > 0:
            # 容量为 2 秒的量
            self._max_tokens = float(self._limit_kbps) * 2.0
        else:
            self._max_tokens = float("inf")

    def _refill(self):
        """补充令牌。"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        if self._limit_kbps > 0 and elapsed > 0:
            self._tokens += elapsed * float(self._limit_kbps)
            if self._tokens > self._max_tokens:
                self._tokens = self._max_tokens

    def consume(self, bytes_count: int) -> float:
        """消费指定字节数，返回需等待的秒数。

        当不限制速度（limit=0）时，立即返回 0。

        Args:
            bytes_count: 要消费的字节数。

        Returns:
            需要等待的秒数（可能为 0 或小数）。
        """
        if self._limit_kbps <= 0:
            return 0.0

        kb = bytes_count / 1024.0
        with self._lock:
            self._refill()
            if self._tokens >= kb:
                self._tokens -= kb
                return 0.0
            else:
                # 需要等待的时间
                deficit = kb - self._tokens
                wait = deficit / float(self._limit_kbps)
                self._tokens = 0.0
                return wait

    def limit(self):
        """上下文管理器方式使用限速器。每次迭代调用此方法。

        用法:
            for chunk in stream:
                limiter.limit()
                process(chunk)
        """
        pass


class ThrottledFileWrapper:
    """带速度限制的可读文件包装器。

    包装一个二进制文件对象，在每次 read 时应用速度限制。
    """

    def __init__(self, fileobj, limiter: Optional[SpeedLimiter] = None):
        self._fileobj = fileobj
        self._limiter = limiter

    def read(self, size: int = -1) -> bytes:
        data = self._fileobj.read(size)
        if data and self._limiter:
            wait = self._limiter.consume(len(data))
            if wait > 0:
                time.sleep(wait)
        return data

    def __getattr__(self, name):
        return getattr(self._fileobj, name)
