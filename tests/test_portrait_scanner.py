"""Scanner dùng ảnh thẻ tự học: học khi OCR vừa mua đúng, nhận ra bằng ảnh ở các lần sau (không chờ OCR), tự xóa mẫu bị nhầm."""

import time

import pytest

import core.scanner as sc
from tests.helpers import CENTERS, make_shop

CARD_COLS = [(i * 200, (i + 1) * 200) for i in range(5)]  # = cách chia đều của REGION giả (rộng 1000)


def wait_until(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def learner(make_scanner, tmp_path, monkeypatch):
    """Scanner bắt theo tên có bật ảnh tự học; OCR giả đọc rỗng (nhánh ảnh phải tự đứng được)."""
    monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: "")
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
    return factory


def ocr_buy(s, shop, slot=0, name="Vex", score=1.0):
    """Mô phỏng: OCR vừa đọc đúng `name` ở ô `slot` và tool click mua."""
    s._grab_shop = lambda: shop
    s._buy_batch([(slot, name, score, "tên", s._slice_slots(shop)[slot])], {})


class TestLearning:
    def test_ocr_buy_learns_the_card(self, learner, clicks):
        s = learner()
        ocr_buy(s, make_shop(s, [11, 2, 3, 4, 5]))
        assert clicks == [CENTERS[0]]
        assert s._portraits.count("Vex") == 1 and s.stats["learned"] == 1
        assert any("Đã học ảnh thẻ Vex" in m for m in learner.logs)

    def test_second_sighting_of_the_same_card_adds_no_sample_and_no_log(self, learner, clicks):
        s = learner()
        shop = make_shop(s, [11, 2, 3, 4, 5])
        ocr_buy(s, shop)
        before = len(learner.logs)
        s._locked.clear()
        ocr_buy(s, shop)
        assert s._portraits.count("Vex") == 1 and not any("Đã học" in m for m in learner.logs[before:])

    @pytest.mark.parametrize("score", [0.97, 0.85])
    def test_fuzzy_name_match_is_never_learned(self, learner, clicks, monkeypatch, score):
        monkeypatch.setattr(sc, "read_name_from_slot", lambda frame: "Vex")  # đọc lại lần 2 ra đúng → vẫn click
        s = learner()
        ocr_buy(s, make_shop(s, [11, 2, 3, 4, 5]), score=score)
        assert clicks == [CENTERS[0]] and s._portraits.count("Vex") == 0

    def test_card_that_was_still_changing_is_not_learned(self, learner, clicks):
        s = learner(card_same_corr=0.2)  # cho phép click dù thẻ đã khác một phần
        read = make_shop(s, [11, 2, 3, 4, 5])
        now = make_shop(s, [12, 2, 3, 4, 5])  # lúc click thẻ đã khác lúc đọc
        s._grab_shop = lambda: now
        corr_before = sc._card_correlation(sc._slot_signature(s._slice_slots(read)[0]), sc._slot_signature(s._slice_slots(now)[0]))
        assert corr_before < sc.LEARN_MIN_CORR
        s._buy_batch([(0, "Vex", 1.0, "tên", s._slice_slots(read)[0])], {})
        assert s._portraits.count("Vex") == 0

    def test_nothing_is_learned_before_the_real_card_columns_are_known(self, learner, clicks):
        s = learner()
        s._card_cols = None
        ocr_buy(s, make_shop(s, [11, 2, 3, 4, 5]))
        assert clicks and s._portraits.count("Vex") == 0

    def test_off_by_default(self, make_scanner):
        assert make_scanner()._portraits is None

    def test_needs_name_detection_to_learn(self, make_scanner):
        assert make_scanner(learn_portraits=True, detect_by_name=False, detect_by_image=True, templates={"x": __import__("numpy").zeros((64, 64, 3), "uint8")})._portraits is None

    def test_samples_survive_a_restart(self, learner, clicks):
        s = learner()
        ocr_buy(s, make_shop(s, [11, 2, 3, 4, 5]))
        assert s._portraits.flush(3)  # file được ghi ở luồng nền
        again = learner()
        assert again._portraits.count("Vex") == 1


class TestRecognizingByImage:
    def teach(self, learner, clicks, **kw):
        s = learner(**kw)
        ocr_buy(s, make_shop(s, [11, 2, 3, 4, 5]))
        clicks.clear()
        s._locked.clear()
        s._pending_verify.clear()
        return s

    def test_learned_card_in_another_slot_is_bought_without_any_ocr(self, learner, clicks, monkeypatch):
        s = self.teach(learner, clicks)
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: pytest.fail("không được chờ OCR"))
        s._ocr_pool = None
        s.detect_by_name = False  # chỉ nhánh ảnh chạy
        shop = make_shop(s, [1, 2, 3, 11, 5])  # Vex hiện ở ô 4
        s._grab_shop = lambda: shop
        s._scan_once({})
        assert clicks == [CENTERS[3]] and s.stats["learned_hits"] >= 1

    def test_evidence_and_latency_lines_name_the_image_method(self, learner, clicks):
        s = self.teach(learner, clicks)
        s.detect_by_name = False
        shop = make_shop(s, [1, 2, 3, 11, 5])
        s._grab_shop = lambda: shop
        s._scan_once({})
        assert any("bằng chứng ô 4: so ảnh mẫu → Vex" in m for m in learner.logs)

    def test_unlearned_or_other_cards_do_not_trigger(self, learner, clicks):
        s = self.teach(learner, clicks)
        s.detect_by_name = False
        shop = make_shop(s, [1, 2, 3, 4, 5])
        s._grab_shop = lambda: shop
        s._scan_once({})
        assert clicks == []

    def test_only_current_targets_are_matched(self, learner, clicks):
        s = self.teach(learner, clicks)
        other = learner(target_names=["Zed"])  # thư mục ảnh học có Vex nhưng mục tiêu bây giờ chỉ là Zed
        other.detect_by_name = False
        shop = make_shop(other, [1, 2, 3, 11, 5])
        other._grab_shop = lambda: shop
        other._scan_once({})
        assert clicks == [] and s._portraits.count("Vex") == 1

    def test_locked_slot_is_not_bought_again(self, learner, clicks):
        s = self.teach(learner, clicks)
        s.detect_by_name = False
        shop = make_shop(s, [1, 2, 3, 11, 5])
        s._grab_shop = lambda: shop
        s._scan_once({})
        s._scan_once({})
        assert clicks == [CENTERS[3]]

    def test_not_used_before_card_columns_are_known(self, learner, clicks):
        s = self.teach(learner, clicks)
        s.detect_by_name = False
        s._card_cols = None
        shop = make_shop(s, [1, 2, 3, 11, 5])
        s._grab_shop = lambda: shop
        s._scan_once({})
        assert clicks == []

    def test_a_card_that_changed_before_the_click_is_still_dropped(self, learner, clicks):
        """Ảnh chỉ thay OCR ở khâu nhận diện: khâu xác nhận 'thẻ vẫn còn' trước khi click vẫn như cũ."""
        s = self.teach(learner, clicks)
        analyzed = make_shop(s, [1, 2, 3, 11, 5])
        s._grab_shop = lambda: make_shop(s, [1, 2, 3, 99, 5])
        s._buy_batch([(3, "Vex", 0.99, "ảnh", s._slice_slots(analyzed)[3])], {})
        assert clicks == []


class TestConflicts:
    def test_card_read_as_another_champion_drops_the_wrong_sample(self, learner, clicks):
        s = learner()
        shop = make_shop(s, [11, 2, 3, 4, 5])
        ocr_buy(s, shop, name="Zed")  # nhầm: thẻ 11 bị học thành Zed
        assert s._portraits.count("Zed") == 1
        s._locked.clear()
        ocr_buy(s, shop, name="Vex")  # lần sau OCR đọc đúng thẻ đó là Vex
        assert s._portraits.count("Zed") == 0 and s._portraits.count("Vex") == 0  # mẫu sai bị xóa, không học chồng lên
        assert s.stats["learned_conflicts"] == 1 and any("Đã xóa 1 ảnh tự học của Zed" in m for m in learner.logs)

    def test_image_buy_is_double_checked_by_ocr_and_a_wrong_sample_is_forgotten(self, learner, clicks, monkeypatch):
        s = learner()
        shop = make_shop(s, [11, 2, 3, 4, 5])
        ocr_buy(s, shop, name="Zed")  # Zed bị học nhầm từ thẻ 11
        s._locked.clear()
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "Vex")  # thật ra thẻ này là Vex
        s._grab_shop = lambda: shop
        s._buy_batch([(0, "Zed", 0.99, "ảnh", s._slice_slots(shop)[0])], {})
        assert wait_until(lambda: s.stats["learned_conflicts"] == 1)
        assert s._portraits.count("Zed") == 0 and any("vừa mua Zed ô 1 bằng ảnh nhưng OCR đọc thẻ đó là Vex" in m for m in learner.logs)

    def test_correct_image_buy_is_confirmed_and_kept(self, learner, clicks, monkeypatch):
        s = learner()
        shop = make_shop(s, [11, 2, 3, 4, 5])
        ocr_buy(s, shop, name="Vex")
        s._locked.clear()
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: "Vex")
        s._buy_batch([(0, "Vex", 0.99, "ảnh", s._slice_slots(shop)[0])], {})
        assert wait_until(lambda: s.stats["learned_verified"] == 1)
        assert s._portraits.count("Vex") == 1 and s.stats["learned_conflicts"] == 0

    @pytest.mark.parametrize("garbled", ["", "Ve", "xq 3"])
    def test_unreadable_second_opinion_changes_nothing(self, learner, clicks, monkeypatch, garbled):
        s = learner()
        shop = make_shop(s, [11, 2, 3, 4, 5])
        ocr_buy(s, shop, name="Vex")
        s._locked.clear()
        monkeypatch.setattr(sc, "read_name_from_slot", lambda f: garbled)
        s._buy_batch([(0, "Vex", 0.99, "ảnh", s._slice_slots(shop)[0])], {})
        time.sleep(0.1)
        assert s._portraits.count("Vex") == 1 and s.stats["learned_conflicts"] == 0

    def test_failures_while_learning_never_break_buying(self, learner, clicks, monkeypatch):
        s = learner()
        monkeypatch.setattr(s._portraits, "learn", lambda *a: (_ for _ in ()).throw(RuntimeError("đĩa lỗi")))
        ocr_buy(s, make_shop(s, [11, 2, 3, 4, 5]))
        assert clicks == [CENTERS[0]]


def test_summary_line_reports_learning(learner, clicks):
    s = learner()
    ocr_buy(s, make_shop(s, [11, 2, 3, 4, 5]))
    s._log_loop_summary()
    assert any(m.startswith("Ảnh thẻ tự học: 1 mẫu mới") for m in learner.logs)
