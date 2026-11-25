"""Tự tìm vị trí 5 thẻ trong khung chụp vùng Shop (core/cards.py) và cách scanner dùng nó để cắt ô.

Khung giả mô phỏng ảnh thật đo từ client TFT: nền shop phẳng (21), thẻ rộng ~189 px cách nhau 202 px (khe ~13 px), bên trái có khối
nút Buy XP/Reroll giống một thẻ, phía trên là thanh vàng/cấp."""

import numpy as np
import pytest

import core.scanner as sc
from core.cards import PAD_PX, find_card_columns

H, W = 215, 1235
CARD_X = [221 + 202 * i for i in range(5)]
CARD_W = 189
BG = 21


def textured(h, w, seed):
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (max(2, h // 8), max(2, w // 8), 3), dtype=np.uint8)
    import cv2

    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


def shop_frame(cards=(0, 1, 2, 3, 4), panel=True, hud=True, width=W, left=0):
    """Khung vùng Shop giả; `left` là hoành độ (trong khung 1235 px) của mép trái vùng được cắt."""
    f = np.full((H, 1235, 3), BG, np.uint8)
    if hud:
        f[0:55, 220:1000] = textured(55, 780, 99)  # thanh vàng/cấp phía trên thẻ
    if panel:
        f[65:205, 17:206] = textured(140, 189, 98)  # nút Buy XP / Reroll
    for i in cards:
        f[65:205, CARD_X[i] : CARD_X[i] + CARD_W] = textured(140, CARD_W, i)
    return f[:, left : left + width]


CLICKS = [x + 95 for x in CARD_X]  # tâm thẻ, theo hệ tọa độ khung 1235 px


class TestFindCardColumns:
    def test_finds_exact_five_cards_with_click_points_even_when_the_panel_is_in_the_frame(self):
        cols = find_card_columns(shop_frame(), CLICKS)
        assert cols is not None and len(cols) == 5
        for (a, b), x in zip(cols, CARD_X):
            assert abs(a - (x - PAD_PX)) <= 2 and abs(b - (x + CARD_W + PAD_PX)) <= 2

    def test_panel_next_to_the_cards_is_ambiguous_without_click_points(self):
        """Khối nút Buy XP/Reroll trông như một thẻ: 6 khối đều nhau thì có 2 cách chọn 5 → không đoán."""
        assert find_card_columns(shop_frame()) is None

    def test_without_the_panel_click_points_are_not_needed(self):
        cols = find_card_columns(shop_frame(panel=False))
        assert cols is not None and len(cols) == 5

    def test_click_point_outside_its_card_rejects_that_choice(self):
        bad = list(CLICKS)
        bad[0] = 50  # trên nút Buy XP, không phải thẻ 1
        assert find_card_columns(shop_frame(), bad) is None

    def test_slightly_off_center_clicks_still_pick_the_right_cards(self):
        sloppy = [x + d for x, d in zip(CLICKS, (-60, 40, -30, 70, -50))]  # vẫn nằm trong thẻ
        assert find_card_columns(shop_frame(), sloppy) is not None

    def test_not_enough_cards_returns_none(self):
        assert find_card_columns(shop_frame(cards=(0, 1, 3, 4), panel=False)) is None  # ô 3 đã mua/trống

    def test_no_gaps_at_all_returns_none(self):
        assert find_card_columns(textured(H, W, 5)) is None

    def test_blank_or_tiny_frames_return_none(self):
        assert find_card_columns(np.full((H, W, 3), BG, np.uint8)) is None
        assert find_card_columns(np.zeros((10, 10, 3), np.uint8)) is None
        assert find_card_columns(None) is None

    def test_irregular_blocks_are_not_taken_for_cards(self):
        f = np.full((H, W, 3), BG, np.uint8)
        for x, w in ((20, 100), (160, 300), (500, 60), (600, 220), (850, 150)):
            f[65:205, x : x + w] = textured(140, w, x)
        assert find_card_columns(f) is None

    def test_works_when_the_region_is_cut_tighter_than_the_cards(self):
        cols = find_card_columns(shop_frame(width=1000, left=215), [x - 215 for x in CLICKS])
        assert cols is not None
        assert cols[0][0] <= 6 + PAD_PX and cols[-1][1] <= 1000

    def test_region_with_extra_rows_above_the_cards_still_works(self):
        f = np.vstack([textured(60, 1235, 7), shop_frame()])  # thêm 60 hàng giao diện phía trên
        assert find_card_columns(f, CLICKS) is not None

    def test_columns_stay_inside_the_frame(self):
        cols = find_card_columns(shop_frame(width=1000, left=215), [x - 215 for x in CLICKS])
        assert all(0 <= a < b <= 1000 for a, b in cols)


@pytest.fixture
def region_scanner(make_scanner):
    """Scanner có vùng Shop 1235 px lệch như của người dùng: gồm cả khối nút bên trái, 5 điểm click trong 5 thẻ."""
    region = {"left": 225, "top": 864, "width": W, "height": H}
    centers = [(225 + x, 1000) for x in CLICKS]
    s = make_scanner(shop_region=region, slot_centers=centers)
    s._running = True
    return s


class TestScannerUsesDetectedCards:
    def test_before_detection_slots_are_equal_columns(self, region_scanner):
        slots = region_scanner._slice_slots(shop_frame())
        assert [x.shape[1] for x in slots] == [W * (i + 1) // 5 - W * i // 5 for i in range(5)]

    def test_detection_makes_slots_follow_the_real_cards(self, region_scanner):
        s = region_scanner
        frame = shop_frame()
        s._detect_cards(frame)
        assert s._card_cols is not None
        slots = s._slice_slots(frame)
        assert [x.shape[1] for x in slots] == [b - a for a, b in s._card_cols]
        assert all(abs(x.shape[1] - (CARD_W + 2 * PAD_PX)) <= 3 for x in slots)

    def test_each_slot_holds_exactly_its_own_card(self, region_scanner):
        """Vì sao có tính năng: chia đều thì ô 2 chứa nửa thẻ 1 + nửa thẻ 2 (tên bị cắt: "uko 31 Rek'SÉ"); cắt theo thẻ thật thì ô i
        chứa đúng thẻ i và không lẫn điểm ảnh nào của thẻ bên cạnh."""
        s = region_scanner
        frame = shop_frame()
        s._detect_cards(frame)
        top = 65 - int(H * s._card_top_ratio)  # hàng đầu của thẻ trong ô (ô đã bỏ thanh trên)
        for i, slot in enumerate(s._slice_slots(frame)):
            off = CARD_X[i] - s._card_cols[i][0]
            assert np.array_equal(slot[top : top + 140, off : off + CARD_W], textured(140, CARD_W, i))
            assert (slot[top : top + 140, :off] == BG).all() and (slot[top : top + 140, off + CARD_W :] == BG).all()

    def test_detection_is_logged_once_and_retries_are_throttled(self, region_scanner):
        s = region_scanner
        logs = []
        s.on_log = logs.append
        clock = {"t": 100.0}
        s._now = lambda: clock["t"]
        blank = np.full((H, W, 3), BG, np.uint8)
        s._detect_cards(blank)
        assert s._card_cols is None and logs == []
        s._detect_cards(shop_frame())  # chưa tới lúc thử lại
        assert s._card_cols is None
        clock["t"] += 0.6
        s._detect_cards(shop_frame())
        assert s._card_cols is not None
        assert len(logs) == 1 and "5 thẻ" in logs[0] and "x" in logs[0]
        assert "tự cắt theo từng thẻ thật" in logs[0]  # vùng 1235 px nhưng 5 thẻ chỉ ~1000 px

    def test_no_note_when_region_already_matches_the_cards(self, make_scanner):
        s = make_scanner(shop_region={"left": 446, "top": 864, "width": 1000, "height": H}, slot_centers=[(446 + 100 + 202 * i, 1000) for i in range(5)])
        logs = []
        s.on_log = logs.append
        s._detect_cards(shop_frame(width=1000, left=221 - 4))
        assert s._card_cols is not None and len(logs) == 1 and "tự cắt theo từng thẻ thật" not in logs[0]

    def test_new_geometry_resets_trackers_so_old_signatures_are_not_compared(self, region_scanner):
        s = region_scanner
        s._slot_sigs = [np.zeros(4)] * 5
        s._locked = {0: np.zeros(4)}
        s._pending_verify = [{"slot": 0}]
        s._prev_frame = np.zeros((2, 2, 3), np.uint8)
        s._detect_cards(shop_frame())
        assert s._slot_sigs == [None] * 5 and s._locked == {} and s._pending_verify == [] and s._prev_frame is None

    def test_detection_stops_once_successful(self, region_scanner, monkeypatch):
        s = region_scanner
        s._detect_cards(shop_frame())
        calls = []
        monkeypatch.setattr(sc, "find_card_columns", lambda *a, **k: calls.append(1))
        s._scan_once({})  # _card_cols đã có: không gọi lại
        assert calls == []

    def test_scan_once_detects_on_the_first_frame_that_shows_all_five_cards(self, region_scanner):
        s = region_scanner
        s._grab_shop = lambda: shop_frame()
        s._scan_once({})
        assert s._card_cols is not None

    def test_detector_crash_never_breaks_the_scan(self, region_scanner, monkeypatch):
        s = region_scanner

        def boom(*a, **k):
            raise ValueError("lỗi bất ngờ")

        monkeypatch.setattr(sc, "find_card_columns", boom)
        s._detect_cards(shop_frame())
        assert s._card_cols is None
        assert len(s._slice_slots(shop_frame())) == 5

    def test_stale_columns_wider_than_the_frame_fall_back_to_equal_split(self, region_scanner):
        s = region_scanner
        s._card_cols = [(0, 100), (100, 200), (200, 300), (300, 400), (400, 5000)]
        slots = s._slice_slots(shop_frame())
        assert sum(x.shape[1] for x in slots) == W

    def test_environment_warning_about_equal_split_is_dropped_once_cards_are_known(self, region_scanner, monkeypatch):
        s = region_scanner
        seen = []
        monkeypatch.setattr(sc, "collect_environment", lambda names, region, centers=None: seen.append(centers) or [])
        s.on_log = lambda m: None
        s._log_environment()
        s._detect_cards(shop_frame())
        s._log_environment()
        assert seen[0] == s.slot_centers and seen[1] is None
