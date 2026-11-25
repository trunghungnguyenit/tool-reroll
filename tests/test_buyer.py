import ctypes
import ctypes.wintypes
import threading
import time

import pytest

from core import buyer


class FakeUser32:
    """Ghi lại thứ tự gọi API chuột; con trỏ 'đang ở' (px, py) trước khi click."""

    def __init__(self, pos=(100, 200), get_ok=True):
        self.pos = pos
        self.get_ok = get_ok
        self.calls = []

    def GetCursorPos(self, ref):
        self.calls.append(("get",))
        if not self.get_ok:
            return 0
        ref._obj.x, ref._obj.y = self.pos
        return 1

    # desktop ảo giả lập: hai màn hình 1920x1080 cạnh nhau, màn hình trái nằm ở x âm
    VIRTUAL = {76: -1920, 77: 0, 78: 3840, 79: 1080}

    def GetSystemMetrics(self, index):
        return self.VIRTUAL[index]

    def SetCursorPos(self, x, y):
        self.calls.append(("set", x, y))
        return 1

    def mouse_event(self, flags, dx, dy, data, extra):
        self.calls.append(("mouse", flags))
        if flags & buyer.MOUSEEVENTF_MOVE:
            self.moves = getattr(self, "moves", []) + [(dx, dy)]


MOVE = buyer.MOUSEEVENTF_MOVE | buyer.MOUSEEVENTF_ABSOLUTE | buyer.MOUSEEVENTF_VIRTUALDESK


@pytest.fixture
def fake(monkeypatch):
    f = FakeUser32()
    monkeypatch.setattr(buyer, "user32", f)
    monkeypatch.setattr(buyer.time, "sleep", lambda s: f.calls.append(("sleep", s)))
    return f


def test_click_moves_clicks_then_restores_cursor_in_order(fake):
    buyer.click(640, 480)
    assert fake.calls == [
        ("get",),
        ("set", 640, 480),
        ("mouse", MOVE),  # sự kiện di chuyển thật để game thấy chuột tới nơi
        ("sleep", buyer._MOVE_SETTLE_S),  # cho game ≥ 1 khung hình trước khi nhấn
        ("mouse", buyer.MOUSEEVENTF_LEFTDOWN),
        ("sleep", buyer._HOLD_S),  # giữ nút ≥ 1 khung hình
        ("mouse", buyer.MOUSEEVENTF_LEFTUP),
        ("sleep", buyer._RESTORE_DELAY_S),
        ("set", 100, 200),
    ]


def test_click_gives_the_game_at_least_one_frame_between_move_down_and_up():
    frame_60fps = 1 / 60
    assert buyer._MOVE_SETTLE_S >= frame_60fps and buyer._HOLD_S >= frame_60fps


def test_move_event_uses_normalized_virtual_desktop_coordinates(fake):
    buyer.click(-1920, 0, restore_cursor=False)  # góc trên-trái của desktop ảo
    buyer.click(1919, 1079, restore_cursor=False)  # góc dưới-phải
    buyer.click(0, 540, restore_cursor=False)  # mép giữa hai màn hình
    assert fake.moves == [(0, 0), (65535, 65535), (round(1920 * 65535 / 3839), round(540 * 65535 / 1079))]


def test_click_still_presses_when_move_event_cannot_be_sent(fake):
    fake.VIRTUAL = {76: 0, 77: 0, 78: 0, 79: 0}  # không đọc được kích thước desktop ảo
    buyer.click(640, 480, restore_cursor=False)
    assert ("mouse", buyer.MOUSEEVENTF_LEFTDOWN) in fake.calls and ("mouse", buyer.MOUSEEVENTF_LEFTUP) in fake.calls
    assert not hasattr(fake, "moves")


def test_button_is_released_even_if_hold_is_interrupted(fake, monkeypatch):
    def boom(s):
        if s == buyer._HOLD_S:
            raise KeyboardInterrupt
    monkeypatch.setattr(buyer.time, "sleep", boom)
    with pytest.raises(KeyboardInterrupt):
        buyer.click(1, 2, restore_cursor=False)
    assert fake.calls[-1] == ("mouse", buyer.MOUSEEVENTF_LEFTUP)


def test_click_waits_before_restoring_so_click_does_not_land_on_old_spot(fake):
    buyer.click(1, 2)
    kinds = [c[0] for c in fake.calls]
    assert kinds.index("sleep") > kinds.index("mouse") and kinds.index("sleep") < len(kinds) - 1
    assert buyer._RESTORE_DELAY_S > 0
    assert fake.calls[-3:] == [("mouse", buyer.MOUSEEVENTF_LEFTUP), ("sleep", buyer._RESTORE_DELAY_S), ("set", 100, 200)]


def test_click_without_restore_never_reads_or_resets_cursor(fake):
    buyer.click(640, 480, restore_cursor=False)
    assert [c for c in fake.calls if c[0] in ("get", "set")] == [("set", 640, 480)]
    assert [c for c in fake.calls if c[0] == "mouse"] == [
        ("mouse", MOVE), ("mouse", buyer.MOUSEEVENTF_LEFTDOWN), ("mouse", buyer.MOUSEEVENTF_LEFTUP),
    ]


def test_click_when_cursor_position_unreadable_still_clicks_and_skips_restore(monkeypatch):
    f = FakeUser32(get_ok=False)
    monkeypatch.setattr(buyer, "user32", f)
    monkeypatch.setattr(buyer.time, "sleep", lambda s: f.calls.append(("sleep", s)))
    buyer.click(10, 20)
    assert ("set", 10, 20) in f.calls and ("mouse", buyer.MOUSEEVENTF_LEFTUP) in f.calls
    assert [c for c in f.calls if c[0] == "set"] == [("set", 10, 20)]  # không trả chuột về một chỗ rác
    assert f.calls[-1] == ("mouse", buyer.MOUSEEVENTF_LEFTUP)  # không có gì để trả nên không chờ trả chuột sau cú nhả


def test_click_restores_negative_coordinates_from_secondary_monitor(monkeypatch):
    f = FakeUser32(pos=(-1500, -20))
    monkeypatch.setattr(buyer, "user32", f)
    monkeypatch.setattr(buyer.time, "sleep", lambda s: None)
    buyer.click(5, 5)
    assert f.calls[-1] == ("set", -1500, -20)  # c_long có dấu


class TestClickWorker:
    """Luồng click riêng: không chặn luồng gọi, click cả loạt liên tiếp, trả chuột MỘT lần."""

    @pytest.fixture
    def worker(self, monkeypatch):
        f = FakeUser32()
        monkeypatch.setattr(buyer, "user32", f)
        monkeypatch.setattr(buyer, "_RESTORE_DELAY_S", 0.03)
        return buyer.ClickWorker(), f

    def kinds(self, f):
        return [c[0] for c in f.calls]

    def test_single_point_is_clicked_then_cursor_restored(self, worker):
        w, f = worker
        w.submit((640, 480))
        assert w.wait_idle(2)
        assert f.calls == [("get",), ("set", 640, 480), ("mouse", MOVE), ("mouse", buyer.MOUSEEVENTF_LEFTDOWN),
                           ("mouse", buyer.MOUSEEVENTF_LEFTUP), ("set", 100, 200)]

    def test_submit_never_blocks_the_caller(self, worker):
        w, f = worker
        t0 = time.perf_counter()
        w.submit((1, 1))
        assert (time.perf_counter() - t0) < 0.02  # còn rất xa 30 ms chờ trả chuột
        assert w.wait_idle(2)

    def test_batch_clicks_all_points_then_restores_exactly_once(self, worker):
        w, f = worker
        for pt in ((10, 10), (20, 20), (30, 30)):
            w.submit(pt)
        assert w.wait_idle(2)
        sets = [c for c in f.calls if c[0] == "set"]
        assert sets[:3] == [("set", 10, 10), ("set", 20, 20), ("set", 30, 30)] and sets[3] == ("set", 100, 200)
        assert self.kinds(f).count("get") == 1 and w.clicks_done == 3
        assert f.calls[-1] == ("set", 100, 200)  # trả chuột là việc CUỐI CÙNG

    def test_late_point_after_restore_starts_a_new_batch(self, worker):
        w, f = worker
        w.submit((10, 10))
        assert w.wait_idle(2)
        w.submit((20, 20))
        assert w.wait_idle(2)
        assert self.kinds(f).count("get") == 2 and w.clicks_done == 2

    def test_point_arriving_during_restore_wait_is_clicked_without_restoring_in_between(self, worker):
        w, f = worker
        w.submit((10, 10))
        time.sleep(0.01)  # trong khoảng chờ 30 ms
        w.submit((20, 20))
        assert w.wait_idle(2)
        sets = [c for c in f.calls if c[0] == "set"]
        assert sets == [("set", 10, 10), ("set", 20, 20), ("set", 100, 200)]

    def test_restore_disabled(self, monkeypatch):
        f = FakeUser32()
        monkeypatch.setattr(buyer, "user32", f)
        w = buyer.ClickWorker(restore_cursor=False)
        w.submit((5, 6))
        assert w.wait_idle(2)
        assert "get" not in self.kinds(f) and [c for c in f.calls if c[0] == "set"] == [("set", 5, 6)]

    def test_unreadable_cursor_still_clicks(self, monkeypatch):
        f = FakeUser32(get_ok=False)
        monkeypatch.setattr(buyer, "user32", f)
        w = buyer.ClickWorker()
        w.submit((5, 6))
        assert w.wait_idle(2)
        assert ("mouse", buyer.MOUSEEVENTF_LEFTUP) in f.calls and [c for c in f.calls if c[0] == "set"] == [("set", 5, 6)]

    def test_failure_is_survived_and_next_click_works(self, monkeypatch):
        f = FakeUser32()
        boom = {"on": True}
        orig = f.mouse_event

        def flaky(*a):
            if boom["on"]:
                raise OSError("API lỗi")
            return orig(*a)

        f.mouse_event = flaky
        monkeypatch.setattr(buyer, "user32", f)
        w = buyer.ClickWorker()
        w.submit((1, 1))
        assert w.wait_idle(2)  # không treo dù lỗi
        boom["on"] = False
        w.submit((2, 2))
        assert w.wait_idle(2) and ("set", 2, 2) in f.calls

    def test_wait_idle_times_out_when_work_is_stuck(self, monkeypatch):
        gate = threading.Event()
        f = FakeUser32()
        orig = f.mouse_event
        f.mouse_event = lambda *a: (gate.wait(2), orig(*a))[1]
        monkeypatch.setattr(buyer, "user32", f)
        w = buyer.ClickWorker()
        w.submit((1, 1))
        assert w.wait_idle(0.05) is False
        gate.set()
        assert w.wait_idle(2)

    def test_module_level_buy_slot_async_goes_through_the_worker(self, monkeypatch):
        f = FakeUser32()
        monkeypatch.setattr(buyer, "user32", f)
        monkeypatch.setattr(buyer, "_worker", buyer.ClickWorker())
        buyer.buy_slot_async((321, 654))
        assert buyer._worker.wait_idle(2)
        assert ("set", 321, 654) in f.calls


def test_point_struct_layout_matches_windows_point():
    assert ctypes.sizeof(buyer._POINT) == 8
    p = buyer._POINT(-3, 7)
    assert (p.x, p.y) == (-3, 7)


class _RealMouseOnlyFakeButtons:
    """Chuột THẬT cho GetCursorPos/SetCursorPos (chứng minh khôi phục con trỏ chạy trên Windows thật);
    mouse_event bị chặn nên không có cú click nào xảy ra."""

    def __init__(self, real):
        self._real = real
        self.mouse_events = []

    def __getattr__(self, name):
        return getattr(self._real, name)

    def mouse_event(self, *args):
        self.mouse_events.append(args[0])


def test_real_windows_cursor_is_restored_after_click(monkeypatch):
    real = ctypes.windll.user32
    start = buyer._POINT()
    if not real.GetCursorPos(ctypes.byref(start)):
        pytest.skip("không đọc được vị trí chuột (phiên khóa/không có desktop)")
    proxy = _RealMouseOnlyFakeButtons(real)
    monkeypatch.setattr(buyer, "user32", proxy)
    clip = ctypes.wintypes.RECT()
    real.GetClipCursor(ctypes.byref(clip))  # một số ứng dụng giới hạn vùng di chuyển của chuột (ClipCursor)
    candidates = [(start.x + dx, start.y + dy) for dx, dy in ((40, 40), (-40, -40), (40, -40), (-40, 40))]
    target = next((c for c in candidates if clip.left <= c[0] < clip.right and clip.top <= c[1] < clip.bottom), None)
    if target is None:
        pytest.skip("vùng di chuyển của chuột đang bị giới hạn quá nhỏ")
    seen_after_move = []
    real_set = real.SetCursorPos

    def spy(x, y):
        r = real_set(x, y)
        cur = buyer._POINT()
        real.GetCursorPos(ctypes.byref(cur))
        seen_after_move.append((cur.x, cur.y))
        return r

    proxy.SetCursorPos = spy
    try:
        buyer.click(*target)
    finally:
        real_set(start.x, start.y)  # dù test hỏng cũng trả chuột về cho người dùng
    assert proxy.mouse_events == [buyer._MOVE_FLAGS, buyer.MOUSEEVENTF_LEFTDOWN, buyer.MOUSEEVENTF_LEFTUP]
    assert seen_after_move[0] == target
    assert seen_after_move[-1] == (start.x, start.y)
