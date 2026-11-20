import subprocess
import sys
import threading
import time
from concurrent.futures import CancelledError
from pathlib import Path

import pytest

from core.ocr_pool import OcrPool

ROOT = str(Path(__file__).resolve().parent.parent)


@pytest.fixture
def pool():
    p = OcrPool(3)
    yield p
    p.shutdown()


class TestBasics:
    def test_returns_results_and_passes_arguments(self, pool):
        assert pool.submit(lambda a, b: a + b, 2, 3).result(2) == 5

    def test_exception_travels_through_the_future(self, pool):
        def boom():
            raise ValueError("hỏng")

        with pytest.raises(ValueError, match="hỏng"):
            pool.submit(boom).result(2)

    def test_worker_survives_a_failing_task(self, pool):
        def boom():
            raise RuntimeError("x")

        pool.submit(boom)
        assert pool.submit(lambda: "vẫn chạy").result(2) == "vẫn chạy"

    def test_even_baseexception_is_captured_so_the_waiter_never_hangs(self, pool):
        def exits():
            raise SystemExit(3)

        fut = pool.submit(exits)
        with pytest.raises(SystemExit):
            fut.result(2)
        assert pool.submit(lambda: 1).result(2) == 1

    def test_workers_really_run_in_parallel(self):
        """5 việc cùng chờ một rào chắn 5 bên: chỉ qua được nếu thật sự có 5 luồng chạy đồng thời."""
        p = OcrPool(5)
        try:
            barrier = threading.Barrier(5, timeout=3)
            futures = [p.submit(barrier.wait) for _ in range(5)]
            arrival_order = sorted(f.result(5) for f in futures)  # Barrier.wait trả về chỉ số đến duy nhất
            assert arrival_order == [0, 1, 2, 3, 4]
        finally:
            p.shutdown()

    def test_too_few_workers_would_deadlock_the_same_barrier(self):
        """Đối chứng: 3 luồng cho rào chắn 5 bên thì không bao giờ đủ (đây là lý do OCR_WORKERS = số ô)."""
        p = OcrPool(3)
        try:
            barrier = threading.Barrier(5, timeout=0.5)
            futures = [p.submit(barrier.wait) for _ in range(5)]
            with pytest.raises(threading.BrokenBarrierError):
                futures[0].result(3)
        finally:
            p.shutdown()

    def test_threads_are_daemon_and_named(self, pool):
        assert len(pool.threads) == 3 and all(t.daemon for t in pool.threads)
        assert all(t.name.startswith("OCR-") for t in pool.threads)


class TestShutdown:
    def test_pending_work_is_cancelled(self):
        p = OcrPool(1)
        release = threading.Event()
        running = p.submit(release.wait, 5)
        time.sleep(0.05)
        waiting = [p.submit(lambda: 1) for _ in range(3)]
        p.shutdown()
        assert all(f.cancelled() for f in waiting)
        with pytest.raises(CancelledError):
            waiting[0].result(1)
        release.set()
        assert running.result(2) is True  # việc đang chạy vẫn được kết thúc bình thường

    def test_submit_after_shutdown_is_refused(self):
        p = OcrPool(1)
        p.shutdown()
        with pytest.raises(RuntimeError):
            p.submit(lambda: 1)

    def test_shutdown_is_idempotent_and_does_not_wait_for_a_stuck_worker(self):
        p = OcrPool(2)
        block = threading.Event()
        p.submit(block.wait, 30)
        time.sleep(0.05)
        t0 = time.time()
        p.shutdown()
        p.shutdown()
        assert time.time() - t0 < 0.5
        block.set()

    def test_idle_threads_exit_after_shutdown(self):
        p = OcrPool(3)
        p.shutdown()
        for t in p.threads:
            t.join(2)
        assert not any(t.is_alive() for t in p.threads)


STUCK_POOL = """
import sys, threading
sys.path.insert(0, {root!r})
from core.ocr_pool import OcrPool
pool = OcrPool(2)
pool.submit(threading.Event().wait)   # một lần OCR treo vĩnh viễn
pool.shutdown()
print("main xong", flush=True)
"""

STUCK_EXECUTOR = """
import threading
from concurrent.futures import ThreadPoolExecutor
pool = ThreadPoolExecutor(2)
pool.submit(threading.Event().wait)
pool.shutdown(wait=False, cancel_futures=True)
print("main xong", flush=True)
"""


class TestProcessExit:
    """Lý do tồn tại của OcrPool: một lần OCR treo không được làm tiến trình kẹt lúc thoát."""

    def test_process_exits_even_though_an_ocr_call_never_returns(self):
        r = subprocess.run([sys.executable, "-I", "-c", STUCK_POOL.format(root=ROOT)], capture_output=True, text=True, timeout=15)
        assert r.returncode == 0 and "main xong" in r.stdout

    def test_contrast_threadpoolexecutor_would_hang_the_exit(self):
        """Đối chứng: cùng tình huống với ThreadPoolExecutor làm tiến trình không thoát (đây là lỗi tránh được)."""
        with pytest.raises(subprocess.TimeoutExpired):
            subprocess.run([sys.executable, "-I", "-c", STUCK_EXECUTOR], capture_output=True, text=True, timeout=2.5)
