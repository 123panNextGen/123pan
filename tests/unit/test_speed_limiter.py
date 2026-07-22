"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import threading
import time

import pytest

from src.app.common.speed_limiter import SpeedLimiter


class TestSpeedLimiter:
    def test_consume_unlimited(self):
        limiter = SpeedLimiter(limit_kbps=0)
        assert limiter.consume(1024 * 1024) == 0.0
        assert limiter.consume(0) == 0.0

    def test_consume_within_limit(self, mocker):
        limiter = SpeedLimiter(limit_kbps=100)
        # fill tokens completely
        limiter._tokens = limiter._max_tokens
        # 50 KB consumed, should succeed immediately
        wait = limiter.consume(50 * 1024)
        assert wait == 0.0
        assert limiter._tokens == limiter._max_tokens - 50

    def test_consume_exceeds_limit_returns_wait(self, mocker):
        limiter = SpeedLimiter(limit_kbps=100)
        # start with 0 tokens
        limiter._tokens = 0.0
        wait = limiter.consume(50 * 1024)
        assert wait > 0.0
        # wait = deficit / limit = (50 - 0) / 100 = 0.5
        assert wait == pytest.approx(0.5, rel=1e-3)
        assert limiter._tokens == 0.0

    def test_consume_partial_refill(self, mocker):
        limiter = SpeedLimiter(limit_kbps=100)
        limiter._tokens = 10.0  # start with 10 KB
        monkey_time = [0.0]

        def mock_monotonic():
            return monkey_time[0]

        mocker.patch.object(time, "monotonic", mock_monotonic)

        wait = limiter.consume(50 * 1024)
        # deficit = 50 - 10 = 40 KB, wait = 40/100 = 0.4s
        assert wait == pytest.approx(0.4, rel=1e-3)
        assert limiter._tokens == 0.0

    def test_set_limit_during_operation(self):
        limiter = SpeedLimiter(limit_kbps=100)
        limiter._tokens = 200  # more than new max
        limiter.set_limit(50)
        # tokens should be capped to new max (50 * 2 = 100)
        assert limiter._tokens == 100.0
        assert limiter._max_tokens == 100.0

    def test_set_limit_zero_disables(self):
        limiter = SpeedLimiter(limit_kbps=100)
        limiter.set_limit(0)
        assert limiter.limit_kbps == 0
        assert limiter.consume(999999999) == 0.0

    def test_thread_safety(self):
        """Multiple threads can consume without crashing."""
        limiter = SpeedLimiter(limit_kbps=500)
        errors = []
        lock = threading.Lock()

        def worker():
            for _ in range(100):
                try:
                    limiter.consume(64 * 1024)
                except Exception as e:
                    with lock:
                        errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    def test_limit_kbps_property(self):
        limiter = SpeedLimiter(limit_kbps=200)
        assert limiter.limit_kbps == 200
        limiter.set_limit(300)
        assert limiter.limit_kbps == 300

    def test_zero_limit_init(self):
        limiter = SpeedLimiter(limit_kbps=0)
        assert limiter._max_tokens == float("inf")
        assert limiter._tokens == float("inf")
