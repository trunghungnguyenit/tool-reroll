"""Đường mua nhanh và chính xác: di chuột trước lúc xác nhận, xác nhận bằng đúng tướng (không bằng độ giống khung), OCR im khi đang roll,
bớt đọc lại sau khi mua bằng ảnh, và ghi file ảnh học ở luồng nền."""

import time

import cv2
import numpy as np
import pytest

import core.buyer as buyer
import core.scanner as sc
from core.portraits import PortraitLibrary, canon, zone_geometry
from tests.helpers import CENTERS, make_card, make_shop

CARD_COLS = [(i * 200, (i + 1) * 200) for i in range(5)]


def wait_until(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


# --------------------------------------------------------------------------- buyer: di chuột trước
class Recorder:
    """user32 giả ghi lại (thời điểm, việc) để kiểm tra thứ tự và khoảng cách thời gian giữa các việc."""

    def __init__(self):
        self.events = []
        self.pos = (5, 5)

    def _log(self, *what):
        self.events.append((time.perf_counter(), *what))

    def GetCursorPos(self, ref):
        ref._obj.x, ref._obj.y = self.pos
        return 1

    def SetCursorPos(self, x, y):
        self.pos = (x, y)
        self._log("set", x, y)
        return 1

    def GetSystemMetrics(self, n):
        return {76: 0, 77: 0, 78: 1920, 79: 1080}[n]

    def mouse_event(self, flags, dx, dy, data, extra):
        self._log("mouse", flags)

    def kinds(self):
        return [e[1:] for e in self.events]


@pytest.fixture
def worker(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(buyer, "user32", rec)
    return buyer.ClickWorker(), rec


class TestPreMove:
    def test_click_right_after_premove_does_not_move_or_settle_again(self, worker):
        w, rec = worker
        w.premove((300, 200))
        time.sleep(0.05)  # lúc đó tool đang chụp xác nhận: quá _MOVE_SETTLE_S
        t0 = time.perf_counter()
        w.submit((300, 200))
        assert w.wait_idle(2)
        moves = [e for e in rec.kinds() if e[0] == "set"]
        assert moves == [("set", 300, 200), ("set", 5, 5)]  # một lần tới ô, một lần trả chuột; không di chuyển lần hai
        down = next(e for e in rec.events if e[1:] == ("mouse", buyer.MOUSEEVENTF_LEFTDOWN))
        assert down[0] - t0 < buyer._MOVE_SETTLE_S / 2  # nhấn gần như ngay, không còn chờ 20 ms

    def test_click_soon_after_premove_only_waits_for_the_rest_of_the_settle_time(self, worker):
        w, rec = worker
        w.premove((300, 200))
        time.sleep(0.005)
        t0 = time.perf_counter()
        w.submit((300, 200))
        assert w.wait_idle(2)
        down = next(e for e in rec.events if e[1:] == ("mouse", buyer.MOUSEEVENTF_LEFTDOWN))
        waited = down[0] - t0
        assert waited < buyer._MOVE_SETTLE_S  # ít hơn một lần chờ đầy đủ
        assert waited >= buyer._MOVE_SETTLE_S - 0.012  # nhưng game vẫn có đủ thời gian thấy chuột tới nơi

    def test_premove_that_is_never_followed_by_a_click_restores_the_cursor(self, worker):
        w, rec = worker
        t0 = time.perf_counter()
        w.premove((300, 200))
        assert w.wait_idle(2)
        assert rec.pos == (5, 5) and time.perf_counter() - t0 >= buyer._PREMOVE_WAIT_S * 0.9
        assert not any(e[0] == "mouse" and e[1] == buyer.MOUSEEVENTF_LEFTDOWN for e in rec.kinds())  # không nhấn gì

    def test_click_on_a_different_point_does_a_full_move(self, worker):
        w, rec = worker
        w.premove((300, 200))
        time.sleep(0.05)
        w.submit((700, 200))  # xác nhận chọn ô khác với ô đoán trước
        assert w.wait_idle(2)
        assert ("set", 700, 200) in rec.kinds() and rec.kinds().index(("set", 700, 200)) < rec.kinds().index(("mouse", buyer.MOUSEEVENTF_LEFTDOWN))
        assert ("mouse", buyer.MOUSEEVENTF_LEFTUP) in rec.kinds()

    def test_stale_premove_is_not_trusted(self, worker, monkeypatch):
        w, rec = worker
        monkeypatch.setattr(buyer, "_PREMOVE_VALID_S", 0.0)
        w.premove((300, 200))
        time.sleep(0.02)
        w.submit((300, 200))
        assert w.wait_idle(2)
        assert [e for e in rec.kinds() if e[0] == "set"].count(("set", 300, 200)) == 2  # di chuyển lại như bình thường

    def test_batch_of_two_clicks_after_premove_restores_once(self, worker):
        w, rec = worker
        w.premove((300, 200))
        time.sleep(0.04)
        w.submit((300, 200))
        w.submit((500, 200))
        assert w.wait_idle(3)
        assert [e for e in rec.kinds() if e == ("set", 5, 5)] == [("set", 5, 5)]
        assert w.clicks_done == 2  # di chuột trước không tính là click

    def test_pending_counter_covers_premoves(self, worker):
        w, rec = worker
        w.premove((1, 1))
        assert w.wait_idle(2) and w._pending == 0

    def test_module_level_premove_goes_through_the_worker(self, monkeypatch):
        rec = Recorder()
        monkeypatch.setattr(buyer, "user32", rec)
        monkeypatch.setattr(buyer, "_worker", buyer.ClickWorker())
        buyer.premove_async((42, 43))
        assert buyer._worker.wait_idle(2)
        assert ("set", 42, 43) in rec.kinds()


# --------------------------------------------------------------------------- scanner
@pytest.fixture
def learner(make_scanner, tmp_path, monkeypatch):
    reads = []
    monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: reads.append(1) or "")
    logs = []

    def factory(**kw):
        kw.setdefault("learn_portraits", True)
        kw.setdefault("portraits_dir", tmp_path / "portraits")
        kw.setdefault("target_names", ["Vex", "Zed"])
        kw.setdefault("require_game_foreground", False)
        kw.setdefault("on_log", logs.append)
        s = make_scanner(**kw)
        s._running = True
        s._card_cols = list(CARD_COLS)
        return s

    factory.logs = logs
    factory.reads = reads
    return factory


def teach(s, seeds_by_name):
    for name, seed in seeds_by_name.items():
        shop = make_shop(s, [seed, 2, 3, 4, 5])
        s._maybe_learn(name, 1.0, 1.0, s._slice_slots(shop)[0])


def shift(shop, dx):
    return cv2.warpAffine(shop, np.float32([[1, 0, dx], [0, 1, 0]]), (shop.shape[1], shop.shape[0]), borderMode=cv2.BORDER_REPLICATE)


class TestPreMoveInScanner:
    def test_first_live_slot_is_premoved_before_the_verification_capture(self, learner, clicks, premoves):
        s = learner()
        shop = make_shop(s, [1, 2, 3, 4, 5])
        order = []
        premoves.clear()
        s._grab_shop = lambda: order.append("grab") or shop
        original = sc.premove_async
        sc.premove_async = lambda c: (order.append("premove"), original(c))
        try:
            s._buy_batch([(2, "Vex", 1.0, "tên", s._slice_slots(shop)[2]), (4, "Vex", 1.0, "tên", s._slice_slots(shop)[4])], {})
        finally:
            sc.premove_async = original
        assert order == ["premove", "grab"] and premoves == [CENTERS[2]]
        assert clicks == [CENTERS[2], CENTERS[4]]

    def test_no_premove_when_the_click_is_blocked(self, learner, clicks, premoves, foreground):
        s = learner(require_game_foreground=True)
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        foreground["value"] = False
        premoves.clear()
        s._buy_batch([(0, "Vex", 1.0, "tên", s._slice_slots(shop)[0])], {})
        assert premoves == [] and clicks == []

    def test_no_premove_for_candidates_dropped_by_cooldown(self, learner, clicks, premoves):
        s = learner()
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        premoves.clear()
        s._buy_batch([(0, "Vex", 1.0, "tên", s._slice_slots(shop)[0])], {(0, "Vex"): time.perf_counter()})
        assert premoves == []


class TestIdentityVerification:
    def teach_and_candidate(self, learner):
        s = learner()
        teach(s, {"Vex": 11})
        s._locked.clear()
        analyzed = make_shop(s, [1, 2, 3, 11, 5])
        return s, analyzed

    def test_card_still_animating_but_still_that_champion_is_bought(self, learner, clicks):
        """Log thật: 'độ giống 0.66/0.71/0.76 < 0.80' bỏ oan thẻ đang chạy hiệu ứng. Ảnh vẫn là tướng đó thì phải mua."""
        s, analyzed = self.teach_and_candidate(learner)
        moving = shift(analyzed, 4)  # khung sau ~30 ms: thẻ nhích vài pixel
        corr = sc._card_correlation(sc._slot_signature(s._slice_slots(analyzed)[3]), sc._slot_signature(s._slice_slots(moving)[3]))
        s._grab_shop = lambda: moving
        s.card_same_corr = min(0.99, corr + 0.02)  # khung nhích làm độ giống thấp hơn ngưỡng
        s._buy_batch([(3, "Vex", 0.99, "ảnh", s._slice_slots(analyzed)[3])], {})
        assert clicks == [CENTERS[3]] and s.stats["identity_verified"] == 1

    def test_shop_rolled_to_another_champion_is_still_dropped(self, learner, clicks):
        s, analyzed = self.teach_and_candidate(learner)
        s._grab_shop = lambda: make_shop(s, [1, 2, 3, 99, 5])
        s._buy_batch([(3, "Vex", 0.99, "ảnh", s._slice_slots(analyzed)[3])], {})
        assert clicks == [] and s.stats["identity_verified"] == 0
        assert any("thẻ đã đổi giữa lúc nhận diện và xác nhận" in m for m in learner.logs)

    def test_name_matches_never_use_the_image_shortcut(self, learner, clicks):
        s, analyzed = self.teach_and_candidate(learner)
        s._grab_shop = lambda: shift(analyzed, 4)
        s.card_same_corr = 0.999
        s._buy_batch([(3, "Vex", 1.0, "tên", s._slice_slots(analyzed)[3])], {})
        assert clicks == []  # OCR đọc ở khung cũ: vẫn phải giống khung mới như trước

    def test_without_learned_samples_the_old_rule_applies(self, learner, clicks):
        s = learner()
        analyzed = make_shop(s, [1, 2, 3, 11, 5])
        s._grab_shop = lambda: make_shop(s, [1, 2, 3, 99, 5])
        s._buy_batch([(3, "Vex", 0.99, "ảnh", s._slice_slots(analyzed)[3])], {})
        assert clicks == []

    def test_unknown_geometry_or_crash_is_treated_as_not_verified(self, learner):
        s = learner()
        teach(s, {"Vex": 11})
        s._card_cols = None
        assert s._still_that_champion("Vex", make_shop(s, [11, 2, 3, 4, 5])[:, :200]) is False
        s._card_cols = list(CARD_COLS)
        assert s._still_that_champion("Vex", None) is False


class TestQuietOcrWhileRolling:
    def make(self, learner):
        s = learner()
        teach(s, {"Vex": 11, "Zed": 12})
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._geometry = zone_geometry(s._slice_slots(shop)[0])
        return s

    def test_no_sweep_while_cards_were_changing_a_moment_ago(self, learner):
        s = self.make(learner)
        s._last_idle_ocr = 0.0
        s._last_change = [100.0, 99.0, 98.0, 97.0, 96.0]
        assert s._ocr_due_slots(100.0 + sc.RELAXED_SETTLED_S - 0.05, set()) == []
        assert s._ocr_due_slots(100.0 + sc.RELAXED_SETTLED_S + 0.05, set()) == [0, 1, 2, 3, 4]

    def test_sweep_runs_for_a_static_shop(self, learner):
        s = self.make(learner)
        s._last_change = [1.0] * 5
        s._last_idle_ocr = 100.0
        assert s._ocr_due_slots(100.0 + sc.RELAXED_OCR_S + 0.1, set()) == [0, 1, 2, 3, 4]

    def test_continuous_rolling_never_triggers_ocr(self, learner, clicks):
        s = self.make(learner)
        s.async_ocr = False
        s._ocr_pool = None
        learner.reads.clear()
        s._last_idle_ocr = 0.0  # lưới an toàn đã tới hạn, nhưng thẻ đổi liên tục
        for seeds in ([1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [13, 14, 15, 16, 17], [1, 2, 3, 11, 5]):
            shop = make_shop(s, seeds)
            s._grab_shop = lambda shop=shop: shop
            s._scan_once({})
        assert learner.reads == [] and clicks == [CENTERS[3]]


class TestShadowTrust:
    def test_stops_reading_back_after_enough_confirmations(self, learner, clicks, monkeypatch):
        calls = []
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: calls.append(1) or "Vex")
        s = learner()
        shop = make_shop(s, [11, 2, 3, 4, 5])
        slot = s._slice_slots(shop)[0]
        for i in range(sc.SHADOW_TRUST + 3):
            s._shadow_check(0, "Vex", slot)
            assert wait_until(lambda i=i: len(calls) >= min(i + 1, sc.SHADOW_TRUST) and s._shadow_ok["Vex"] >= min(i + 1, sc.SHADOW_TRUST))
        time.sleep(0.05)
        assert len(calls) == sc.SHADOW_TRUST and s._shadow_ok["Vex"] == sc.SHADOW_TRUST

    def test_other_champions_are_still_checked(self, learner, monkeypatch):
        s = learner()
        s._shadow_ok["Vex"] = sc.SHADOW_TRUST
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "Zed")
        shop = make_shop(s, [11, 2, 3, 4, 5])
        s._shadow_check(0, "Zed", s._slice_slots(shop)[0])
        assert wait_until(lambda: s._shadow_ok["Zed"] == 1)

    def test_a_conflict_resets_the_trust(self, learner, monkeypatch):
        s = learner()
        shop = make_shop(s, [11, 2, 3, 4, 5])
        teach(s, {"Zed": 11})
        s._shadow_ok["Zed"] = sc.SHADOW_TRUST - 1
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "Vex")  # thật ra thẻ này là Vex
        s._shadow_check(0, "Zed", s._slice_slots(shop)[0])
        assert wait_until(lambda: s.stats["learned_conflicts"] == 1)
        assert s._shadow_ok["Zed"] == 0 and s._portraits.count("Zed") == 0


# --------------------------------------------------------------------------- ghi file ảnh học ở luồng nền
class TestBackgroundWrites:
    def test_learning_never_waits_for_the_disk(self, tmp_path, monkeypatch):
        slow = {"calls": 0}
        real = cv2.imwrite

        def slow_imwrite(path, img, *a):
            slow["calls"] += 1
            time.sleep(0.3)  # ổ đĩa/Windows Defender đang quét
            return real(path, img, *a)

        monkeypatch.setattr(cv2, "imwrite", slow_imwrite)
        lib = PortraitLibrary(tmp_path, background=True)
        geom = zone_geometry(make_card(1, (200, 164)))
        t0 = time.perf_counter()
        assert lib.learn("Vex", canon(make_card(7, (200, 164))), geom) is True
        assert time.perf_counter() - t0 < 0.1  # luồng gọi không chờ lần ghi 300 ms
        assert lib.match(canon(make_card(7, (200, 164))), geom) is not None  # nhưng mẫu dùng được ngay trong bộ nhớ
        assert lib.flush(3) and slow["calls"] == 1
        assert PortraitLibrary(tmp_path).names() == ["Vex"]

    def test_forget_is_also_written_in_the_background(self, tmp_path):
        lib = PortraitLibrary(tmp_path, background=True)
        geom = zone_geometry(make_card(1, (200, 164)))
        lib.learn("Vex", canon(make_card(7, (200, 164))), geom)
        assert lib.flush(3) and list(tmp_path.glob("p*.png"))
        assert lib.forget("Vex") == 1
        assert lib.flush(3) and not list(tmp_path.glob("p*.png")) and PortraitLibrary(tmp_path).names() == []

    def test_flush_is_a_noop_when_synchronous(self, tmp_path):
        assert PortraitLibrary(tmp_path).flush() is True

    def test_flush_times_out_instead_of_hanging(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cv2, "imwrite", lambda *a: time.sleep(1.0))
        lib = PortraitLibrary(tmp_path, background=True)
        lib.learn("Vex", canon(make_card(7, (200, 164))), zone_geometry(make_card(1, (200, 164))))
        assert lib.flush(0.05) is False
        assert lib.flush(3) is True

    def test_an_io_error_in_the_writer_never_raises_or_kills_the_thread(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cv2, "imwrite", lambda *a: (_ for _ in ()).throw(OSError("đĩa đầy")))
        lib = PortraitLibrary(tmp_path, background=True)
        geom = zone_geometry(make_card(1, (200, 164)))
        assert lib.learn("Vex", canon(make_card(7, (200, 164))), geom) is True
        assert lib.flush(2) is True
        assert lib.learn("Zed", canon(make_card(8, (200, 164))), geom) is True
        assert lib.flush(2) is True

    def test_scanner_close_flushes_pending_writes(self, learner, clicks):
        s = learner()
        shop = make_shop(s, [11, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s._buy_batch([(0, "Vex", 1.0, "tên", s._slice_slots(shop)[0])], {})
        s.close()
        assert PortraitLibrary(s._portraits.folder).names() == ["Vex"]

    def test_scanner_uses_background_writes(self, learner):
        assert learner()._portraits._background is True
