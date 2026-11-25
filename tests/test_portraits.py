"""Ảnh thẻ tự học (core/portraits.py): học một lần, nhận ra ở ô khác, không nhầm tướng khác, lưu/nạp từ đĩa."""

import json

import cv2
import numpy as np
import pytest

from core.portraits import MATCH_MIN, MAX_SAMPLES, PortraitLibrary, canon, zone_geometry


def card(seed, w=197, h=177):
    """Ô thẻ giả (BGR): ảnh nhiễu mượt theo seed, có chi tiết để so khớp (cùng seed → cùng thẻ)."""
    small = np.random.default_rng(seed).integers(0, 255, (9, 6, 3), dtype=np.uint8)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


def shifted(img, dx):
    return cv2.warpAffine(img, np.float32([[1, 0, dx], [0, 1, 0]]), (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)


GEOM = zone_geometry(card(1))


class TestMatching:
    def test_learns_once_and_recognizes_the_same_card_in_another_slot(self):
        lib = PortraitLibrary()
        assert lib.learn("Rakan", canon(card(7)), GEOM) is True
        got = lib.match(canon(card(7)), GEOM)
        assert got is not None and got[0] == "Rakan" and got[1] > 0.99

    def test_other_champions_are_not_confused(self):
        lib = PortraitLibrary()
        lib.learn("Rakan", canon(card(7)), GEOM)
        for seed in (1, 2, 3, 4, 5, 6, 8, 9, 10):
            assert lib.match(canon(card(seed)), GEOM) is None, seed

    def test_picks_the_right_one_among_several(self):
        lib = PortraitLibrary()
        for i, name in enumerate(["Akali", "Yorick", "Camille", "Rek'Sai"]):
            lib.learn(name, canon(card(100 + i)), GEOM)
        assert lib.match(canon(card(102)), GEOM)[0] == "Camille"
        assert lib.match(canon(card(103)), GEOM)[0] == "Rek'Sai"

    def test_tolerates_a_few_pixels_of_misalignment(self):
        lib = PortraitLibrary()
        lib.learn("Rakan", canon(card(7)), GEOM)
        for dx in (-6, -3, 3, 6):
            got = lib.match(canon(shifted(card(7), dx)), GEOM)
            assert got is not None and got[0] == "Rakan", dx

    def test_tolerates_fading_in_brightness(self):
        lib = PortraitLibrary()
        lib.learn("Rakan", canon(card(7)), GEOM)
        faded = np.clip(card(7).astype(np.float32) * 0.5 + 10, 0, 255).astype(np.uint8)
        assert lib.match(canon(faded), GEOM) is not None

    def test_names_filter_limits_to_current_targets(self):
        lib = PortraitLibrary()
        lib.learn("Rakan", canon(card(7)), GEOM)
        assert lib.match(canon(card(7)), GEOM, {"Akali"}) is None
        assert lib.match(canon(card(7)), GEOM, {"Rakan"}) is not None

    def test_ambiguous_when_two_champions_have_the_same_look(self):
        lib = PortraitLibrary()
        lib.learn("A", canon(card(7)), GEOM)
        lib.learn("B", canon(card(7)), GEOM)  # cùng ảnh gán cho hai tên: không đoán
        assert lib.match(canon(card(7)), GEOM) is None

    def test_empty_library_matches_nothing(self):
        assert PortraitLibrary().match(canon(card(7)), GEOM) is None and not PortraitLibrary()

    def test_threshold_is_in_the_measured_gap(self):
        assert 0.5 < MATCH_MIN < 0.95  # khác tướng ≤ 0,45; cùng tướng ≥ 0,94 (đo trên ảnh thật)


class TestLearning:
    def test_same_card_is_not_added_twice(self):
        lib = PortraitLibrary()
        assert lib.learn("Rakan", canon(card(7)), GEOM) is True
        assert lib.learn("Rakan", canon(card(7)), GEOM) is False
        assert lib.count("Rakan") == 1

    def test_a_different_look_of_the_same_champion_is_added_up_to_the_cap(self):
        lib = PortraitLibrary()
        added = [lib.learn("Rakan", canon(card(seed)), GEOM) for seed in range(20, 30)]
        assert sum(added) == MAX_SAMPLES and lib.count("Rakan") == MAX_SAMPLES

    def test_forget_removes_every_sample_of_that_champion_only(self):
        lib = PortraitLibrary()
        lib.learn("Rakan", canon(card(7)), GEOM)
        lib.learn("Akali", canon(card(8)), GEOM)
        assert lib.forget("Rakan") == 1 and lib.names() == ["Akali"]
        assert lib.forget("Rakan") == 0

    def test_samples_from_another_slot_size_are_ignored(self):
        lib = PortraitLibrary()
        lib.learn("Rakan", canon(card(7)), GEOM)
        big = (GEOM[0] * 2, GEOM[1] * 2)
        assert lib.match(canon(card(7)), big) is None
        assert lib.count("Rakan", big) == 0 and lib.count("Rakan", GEOM) == 1

    def test_small_size_jitter_between_detections_is_fine(self):
        lib = PortraitLibrary()
        lib.learn("Rakan", canon(card(7)), GEOM)
        assert lib.match(canon(card(7)), (GEOM[0] + 4, GEOM[1] - 2)) is not None


class TestPersistence:
    def test_reload_from_disk_keeps_names_and_matches(self, tmp_path):
        a = PortraitLibrary(tmp_path)
        a.learn("Rek'Sai", canon(card(11)), GEOM)
        a.learn("Akali", canon(card(12)), GEOM)
        b = PortraitLibrary(tmp_path)
        assert b.names() == ["Akali", "Rek'Sai"]
        assert b.match(canon(card(11)), GEOM)[0] == "Rek'Sai"

    def test_forget_removes_files_and_survives_reload(self, tmp_path):
        a = PortraitLibrary(tmp_path)
        a.learn("Akali", canon(card(12)), GEOM)
        assert list(tmp_path.glob("p*.png"))
        a.forget("Akali")
        assert not list(tmp_path.glob("p*.png")) and PortraitLibrary(tmp_path).names() == []

    def test_new_files_do_not_overwrite_old_ones_after_reload(self, tmp_path):
        a = PortraitLibrary(tmp_path)
        a.learn("Akali", canon(card(12)), GEOM)
        b = PortraitLibrary(tmp_path)
        b.learn("Yorick", canon(card(13)), GEOM)
        assert len(list(tmp_path.glob("p*.png"))) == 2
        assert PortraitLibrary(tmp_path).names() == ["Akali", "Yorick"]

    def test_missing_corrupt_or_hostile_index_is_ignored(self, tmp_path):
        assert PortraitLibrary(tmp_path).names() == []
        (tmp_path / "index.json").write_text("{không phải json", encoding="utf-8")
        assert PortraitLibrary(tmp_path).names() == []
        (tmp_path / "index.json").write_text(json.dumps([{"name": "X", "geometry": [1, 2], "file": "../x.png"}, 5, {"name": 1}]), encoding="utf-8")
        assert PortraitLibrary(tmp_path).names() == []

    def test_sample_file_that_is_missing_or_wrong_size_is_skipped(self, tmp_path):
        a = PortraitLibrary(tmp_path)
        a.learn("Akali", canon(card(12)), GEOM)
        a.learn("Yorick", canon(card(13)), GEOM)
        files = sorted(tmp_path.glob("p*.png"))
        files[0].unlink()
        cv2.imwrite(str(files[1]), np.zeros((5, 5), np.uint8))
        assert PortraitLibrary(tmp_path).names() == []

    def test_unwritable_folder_never_raises(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        lib = PortraitLibrary(blocker / "sub")  # không tạo được thư mục
        assert lib.learn("Akali", canon(card(12)), GEOM) is True
        assert lib.match(canon(card(12)), GEOM) is not None


@pytest.mark.parametrize("h", [120, 177, 300])
def test_canon_has_fixed_size_for_any_slot_height(h):
    assert canon(card(1, 197, h)).shape == (54, 96)
