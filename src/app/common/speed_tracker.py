import time
from collections import deque


class SpeedTracker:
    """滑动窗口速度计算器。

    worker 线程调 record()（deque.append，原子操作，无锁）。
    UI 线程调 flush() 消费队列，再读 speed()/eta()。
    """

    WINDOW_SECONDS = 60.0

    def __init__(self):
        # worker 线程写入，UI 线程 flush 消费
        self._pending: deque[tuple[float, int]] = deque(maxlen=50000)
        # flush 后的滑动窗口（仅 UI 线程访问）
        self._samples: deque[tuple[float, int]] = deque()
        self._last_speed = 0.0

    def record(self, cumulative_bytes: int) -> None:
        """worker 线程调用，零开销。"""
        self._pending.append((time.monotonic(), cumulative_bytes))

    def flush(self) -> None:
        """UI 线程调用，将 pending 数据消费到滑动窗口并计算速度。"""
        while self._pending:
            try:
                sample = self._pending.popleft()
            except IndexError:
                break
            self._samples.append(sample)

        now = time.monotonic()
        cutoff = now - self.WINDOW_SECONDS
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

        if len(self._samples) < 2:
            self._last_speed = 0.0
            return

        oldest = self._samples[0]
        newest = self._samples[-1]
        dt = newest[0] - oldest[0]
        if dt < 1.0:
            return  # 数据跨度不足 1s，保持上次速度
        self._last_speed = (newest[1] - oldest[1]) / dt

    def speed(self) -> float:
        return self._last_speed

    def eta(self, remaining_bytes: int) -> float:
        if self._last_speed <= 0 or remaining_bytes <= 0:
            return -1.0
        return remaining_bytes / self._last_speed

    def reset(self) -> None:
        self._pending.clear()
        self._samples.clear()
        self._last_speed = 0.0
