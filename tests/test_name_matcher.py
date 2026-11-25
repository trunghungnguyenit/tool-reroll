import itertools

import pytest

from core.name_matcher import (
    DEFAULT_NAME_THRESHOLD,
    NameMatcher,
    normalize_name,
)

# Mẫu tên thật (gồm đúng các cặp từng bị nhận nhầm). Test thuộc tính bên dưới chạy trên mọi cặp.
ALL_NAMES = [
    "Vi", "Viktor", "Viego", "Sivir", "Anivia", "Vex", "T-Hex", "Zed", "Zeri", "Zoe",
    "Graves", "Gragas", "Draven", "Garen", "Gwen", "Gnar", "Jinx", "Jhin", "Jax", "Janna", "Jayce",
    "Kai'Sa", "Maokai", "Mordekaiser", "Akali", "Kalista", "Lee Sin", "Nidalee", "Singed",
    "Lucian", "Senna", "Lucian & Senna", "Kobuko", "Yuumi", "Kobuko & Yuumi",
    "Tryndamere", "Tahm Kench", "Twisted Fate", "Rek'Sai", "Lux", "Ashe", "Shen", "Alistar",
    "Ivern", "Riven", "Ahri", "Taric", "Ekko", "Neeko", "Poppy", "Sylas", "Amumu", "Rammus",
    "Ngộ Không", "Hố Đen Tí Hon", "Sỏi",
]


def matched(ocr, targets, ratio=0.65, all_names=None, aliases=None):
    result = NameMatcher(targets, all_names, ratio, aliases).match(ocr)
    return result[0] if result else None


class TestPerfectOcrNeverBuysAnotherChampion:
    def test_every_pair_in_sample(self):
        """OCR đọc ĐÚNG tên tướng A thì không bao giờ mua khi bạn chọn tướng B khác A."""
        wrong = []
        for target, shop in itertools.permutations(ALL_NAMES, 2):
            if normalize_name(target) == normalize_name(shop):
                continue
            matcher = NameMatcher([target], ALL_NAMES, DEFAULT_NAME_THRESHOLD)
            for text in (shop, f"{shop} 3"):  # kèm số vàng
                if matcher.match(text):
                    wrong.append((text, target))
        assert wrong == []

    @pytest.mark.parametrize("threshold", [0.5, 0.65, 0.75, 0.9])
    def test_independent_of_threshold(self, threshold):
        """Trước đây 113 cặp bị nhận nhầm ở 0.65 và 20 cặp ở mọi ngưỡng; giờ phải là 0 ở mọi ngưỡng."""
        for target, shop in itertools.permutations(ALL_NAMES, 2):
            if normalize_name(target) != normalize_name(shop):
                assert NameMatcher([target], ALL_NAMES, threshold).match(shop) is None, (shop, target)

    @pytest.mark.parametrize(
        "shop,target",
        [
            ("Gragas", "Graves"),
            ("Draven", "Graves"),
            ("T-Hex", "Vex"),
            ("Viktor", "Vi"),  # lựa chọn mới: Vi không còn mua Viktor
            ("Viego", "Vi"),
            ("Sivir", "Vi"),
            ("Anivia", "Vi"),
            ("Kai'Sa", "Maokai"),
            ("Kai'Sa", "Mordekaiser"),
            ("Lee Sin", "Nidalee"),
            ("Lee Sin", "Singed"),
            ("Jhin", "Jinx"),
            ("Ashe", "Shen"),
            ("Alistar", "Kalista"),
            ("Ivern", "Riven"),
        ],
    )
    def test_reported_collisions(self, shop, target):
        assert matched(shop, [target], 0.65, ALL_NAMES) is None


class TestTargetsAreStillBought:
    @pytest.mark.parametrize(
        "ocr,target",
        [
            ("Vex", "Vex"),
            ("vex 2", "Vex"),  # kèm số vàng
            ("Vi", "Vi"),
            ("Graves", "Graves"),
            ("Tryndamere", "Tryndamere"),
            ("Tryndamere 4", "Tryndamere"),
            ("Kai'Sa", "Kai'Sa"),
            ("Lee Sin", "Lee Sin"),
            ("Tahm Kench", "Tahm Kench"),
            ("Kench", "Tahm Kench"),  # chỉ đọc được nửa sau của tên nhiều từ
            ("Graaves", "Graves"),  # sai 1 ký tự
            ("Tryndamer", "Tryndamere"),  # thiếu ký tự cuối
            ("Ngô Không", "Ngộ Không"),  # sai dấu
            ("Ngộ Không", "Ngộ Không"),
        ],
    )
    def test_matches(self, ocr, target):
        assert matched(ocr, [target], DEFAULT_NAME_THRESHOLD, ALL_NAMES) == target

    def test_truncated_fragment_unique_in_whole_list(self):
        """'ves' chỉ nằm trong 'Graves' (không nhập nhằng) nên nhận diện được; vẫn an toàn nhờ so với cả danh sách."""
        assert matched("ves", ["Graves"], 0.8, ALL_NAMES) == "Graves"
        assert matched("Tryndame 2", ["Tryndamere"], 0.8, ALL_NAMES) == "Tryndamere"
        assert matched("ves 3", ["Graves"], 0.8, ALL_NAMES) == "Graves"  # số vàng đi kèm mảnh bị cắt

    def test_fragment_shared_by_several_names_is_not_guessed(self):
        """'ven' nằm trong Draven và Riven → không đoán."""
        assert matched("ven", ["Riven"], 0.8, ALL_NAMES) is None
        assert matched("ven", ["Draven"], 0.8, ALL_NAMES) is None

    def test_returns_original_target_string(self):
        """Trả đúng chuỗi mục tiêu người dùng chọn (kể cả khoảng trắng thừa từ Data Dragon)."""
        assert matched("Tryndamere", ["Tryndamere "], 0.8, ALL_NAMES) == "Tryndamere "

    def test_target_missing_from_reference_list_still_works(self):
        """Tên gõ tay không có trong danh sách đầy đủ vẫn được bắt."""
        assert matched("Yasuo 2", ["Yasuo"], 0.8, ALL_NAMES) == "Yasuo"


class TestAmbiguity:
    def test_exact_non_target_beats_similar_target(self):
        assert matched("Gragas", ["Graves"], 0.65, ALL_NAMES) is None
        assert matched("Gragas 2", ["Graves"], 0.65, ALL_NAMES) is None

    def test_fuzzy_tie_buys_if_one_of_them_is_target(self):
        """Lựa chọn của người dùng: 'Gravas' ngang điểm với Graves và Gragas, mà Graves là mục tiêu → mua."""
        assert matched("Gravas", ["Graves"], 0.75, ALL_NAMES) == "Graves"

    def test_fuzzy_tie_does_not_depend_on_list_order(self):
        """Tên không phải mục tiêu đứng TRƯỚC trong danh sách vẫn không được chặn mục tiêu ngang điểm."""
        for names in (["Gragas", "Graves"], ["Graves", "Gragas"], ["Draven", "Gragas", "Graves"]):
            assert matched("Gravas", ["Graves"], 0.75, names) == "Graves", names

    def test_fuzzy_clear_winner_non_target_is_not_bought(self):
        """'Gragaz' rõ ràng gần Gragas hơn Graves → không mua."""
        assert matched("Gragaz", ["Graves"], 0.75, ALL_NAMES) is None

    def test_longer_specific_name_wins_over_component(self):
        """Thẻ 'Lucian & Senna' không bị coi là 'Senna' hay 'Lucian' riêng lẻ."""
        assert matched("Lucian & Senna", ["Senna"], 0.8, ALL_NAMES) is None
        assert matched("Lucian & Senna", ["Lucian"], 0.8, ALL_NAMES) is None
        assert matched("Lucian & Senna", ["Lucian & Senna"], 0.8, ALL_NAMES) == "Lucian & Senna"
        assert matched("Senna", ["Lucian & Senna"], 0.8, ALL_NAMES) is None  # đọc thấy 'Senna' = tướng Senna


class TestNoise:
    @pytest.mark.parametrize("ocr", ["e", "ex", "x", "ve", "3", "", "  ", "12", "?!"])
    def test_noise_fragments_do_not_match(self, ocr):
        assert matched(ocr, ["Vex"], 0.65, ALL_NAMES) is None
        assert matched(ocr, ["Vex"], 0.65) is None  # kể cả không có danh sách đầy đủ

    @pytest.mark.parametrize(
        "ocr,target,expected",
        [
            ("mer", "Tryndamere", "Tryndamere"),  # 'mer' chỉ nằm trong Tryndamere → nhận diện được
            ("dam", "Tryndamere", "Tryndamere"),
            ("rav", "Graves", None),  # nằm trong Graves và Draven → không đoán
            ("ave", "Graves", None),
            ("kai", "Kai'Sa", None),  # nằm trong Kai'Sa, Maokai, Mordekaiser → không đoán
            ("kai", "Maokai", None),
        ],
    )
    def test_three_letter_fragment_needs_to_be_unique_in_whole_list(self, ocr, target, expected):
        """Mảnh 3 ký tự chỉ được nhận khi nằm trong đúng 1 tên của toàn danh sách (vì thế mới an toàn)."""
        assert matched(ocr, [target], 0.8, ALL_NAMES) == expected

    def test_unrelated_text_does_not_match(self):
        assert matched("Katarina", ["Vex", "Graves"], 0.65, ALL_NAMES) is None


class TestAliases:
    """Client game có thể hiện ngôn ngữ khác ngôn ngữ danh sách: chọn 'Ngộ Không' vẫn mua khi thẻ ghi 'Wukong'."""

    ALIASES = {"Ngộ Không": ["Wukong"]}
    NAMES = [*ALL_NAMES, "Wukong"]

    def test_target_matches_its_alias_and_returns_original_target_name(self):
        m = NameMatcher(["Ngộ Không"], self.NAMES, 0.8, self.ALIASES)
        assert m.match("Wukong")[0] == "Ngộ Không"
        assert m.match("Wukong 4")[0] == "Ngộ Không"
        assert m.match("Ngo Khong")[0] == "Ngộ Không"  # tên gốc vẫn khớp
        assert m.match("Wukonq")[0] == "Ngộ Không"  # sai 1 ký tự (khớp mờ)

    def test_without_alias_other_language_does_not_match(self):
        assert NameMatcher(["Ngộ Không"], self.NAMES, 0.8).match("Wukong") is None

    def test_alias_does_not_open_new_collisions(self):
        m = NameMatcher(["Ngộ Không"], self.NAMES, 0.8, self.ALIASES)
        for other in ALL_NAMES:
            if normalize_name(other) not in ("ngo khong",):
                assert m.match(other) is None, other

    def test_alias_of_one_target_does_not_buy_another_champion(self):
        m = NameMatcher(["Vex"], self.NAMES, 0.8, {"Vex": ["Vexx Alias"]})
        assert m.match("Zed") is None and m.match("T-Hex") is None



class TestWithoutReferenceList:
    """Không có danh sách đầy đủ (offline, chưa cache) → chỉ so với mục tiêu: vẫn dùng được, kém an toàn."""

    def test_basic_matching_still_works(self):
        assert matched("Vex 2", ["Vex"]) == "Vex"
        assert matched("Graaves", ["Graves"]) == "Graves"
        assert matched("Kench", ["Tahm Kench"]) == "Tahm Kench"

    def test_short_target_no_longer_matches_longer_names(self):
        """Đổi so với trước: 'Viktor' không còn khớp mục tiêu 'Vi' (không cần danh sách đầy đủ cũng vậy)."""
        assert matched("Viktor", ["Vi"]) is None


class TestNormalize:
    def test_strips_accents_and_symbols(self):
        assert normalize_name("  Bel'Veth!! ") == "bel veth"
        assert normalize_name("Sói Hắc Ám") == "soi hac am"

    def test_d_with_stroke(self):
        """Đ/đ không tách dấu được bằng NFD nên phải đổi riêng."""
        assert normalize_name("Hố Đen Tí Hon") == "ho den ti hon"
        assert normalize_name("đ") == "d"


def test_default_threshold_is_safe():
    assert DEFAULT_NAME_THRESHOLD >= 0.80


import numpy as np  # noqa: E402

from core import name_matcher as nm  # noqa: E402


@pytest.fixture
def clean_errors():
    nm.drain_ocr_errors()
    yield
    nm.drain_ocr_errors()
    nm.refresh_ocr_state()


FRAME = np.zeros((60, 120, 3), np.uint8)


class TestOcrErrorRecording:
    def test_exception_is_recorded_not_swallowed(self, monkeypatch, clean_errors):
        monkeypatch.setattr(nm, "_detect_backend", lambda: "winocr")

        def boom(region):
            raise RuntimeError("engine chết")

        monkeypatch.setattr(nm, "_read_winocr", boom)
        assert nm.read_name_from_slot(FRAME) == ""
        assert nm.drain_ocr_errors() == {"RuntimeError: engine chết": 1}

    def test_no_engine_is_recorded(self, monkeypatch, clean_errors):
        monkeypatch.setattr(nm, "_detect_backend", lambda: "none")
        assert nm.read_name_from_slot(FRAME) == ""
        assert any("Không có engine OCR" in m for m in nm.drain_ocr_errors())

    def test_same_error_is_counted_not_duplicated(self, clean_errors):
        for _ in range(5):
            nm.record_ocr_error("cùng một lỗi")
        assert nm.drain_ocr_errors() == {"cùng một lỗi": 5}

    def test_drain_empties_the_log(self, clean_errors):
        nm.record_ocr_error("x")
        nm.drain_ocr_errors()
        assert nm.drain_ocr_errors() == {}

    def test_number_of_distinct_errors_is_capped(self, clean_errors):
        for i in range(100):
            nm.record_ocr_error(f"lỗi {i}")
        assert len(nm.drain_ocr_errors()) == 20

    def test_successful_read_records_nothing(self, monkeypatch, clean_errors):
        monkeypatch.setattr(nm, "_detect_backend", lambda: "winocr")
        monkeypatch.setattr(nm, "_read_winocr", lambda region: "Vex 3")
        assert nm.read_name_from_slot(FRAME) == "Vex 3"
        assert nm.drain_ocr_errors() == {}

    def test_winocr_without_any_language_pack_raises_unavailable(self, monkeypatch, clean_errors):
        monkeypatch.setattr(nm, "installed_ocr_languages", lambda: [])
        with pytest.raises(nm.OcrUnavailable):
            nm._read_winocr(FRAME)


class _Result:
    def __init__(self, text):
        self.text = text


class TestOcrSpeedPath:
    """Giảm thời gian mỗi lần đọc: không đọc lại cùng ảnh bằng en-GB khi en-US đã không ra chữ, và dùng lại engine Windows OCR
    của luồng thay vì tạo engine mới cho mỗi ô."""

    def run(self, monkeypatch, installed, answers):
        calls = []

        async def fake(pil, lang):
            calls.append(lang)
            return _Result(answers.get(lang, ""))

        monkeypatch.setattr(nm, "installed_ocr_languages", lambda: list(installed))
        monkeypatch.setattr(nm, "_recognize", fake)
        return nm._read_winocr(FRAME), calls

    def test_empty_en_us_does_not_retry_en_gb(self, monkeypatch):
        text, calls = self.run(monkeypatch, ["en-US", "en-GB"], {})
        assert text == "" and calls == ["en-US"]

    def test_empty_en_us_still_tries_a_different_language(self, monkeypatch):
        text, calls = self.run(monkeypatch, ["en-US", "vi-VN", "en-GB"], {"vi-VN": "Ngộ Không"})
        assert text == "Ngộ Không" and calls == ["en-US", "vi-VN"]

    def test_text_from_first_language_stops_immediately(self, monkeypatch):
        text, calls = self.run(monkeypatch, ["en-US", "vi-VN"], {"en-US": "Vex"})
        assert text == "Vex" and calls == ["en-US"]

    def test_engine_is_cached_per_thread(self, monkeypatch):
        import threading

        monkeypatch.setattr(nm, "_engines", threading.local())
        nm._engines.cache = {"en-US": "engine-của-luồng-này"}
        assert nm._engine("en-US") == "engine-của-luồng-này"
        seen = []
        t = threading.Thread(target=lambda: seen.append(getattr(nm._engines, "cache", None)))
        t.start()
        t.join()
        assert seen == [None]  # luồng khác không dùng chung engine (một engine không chạy được hai lần đọc cùng lúc)

    def test_drop_engine_forgets_only_that_language(self, monkeypatch):
        import threading

        monkeypatch.setattr(nm, "_engines", threading.local())
        nm._engines.cache = {"en-US": 1, "vi-VN": 2}
        nm._drop_engine("en-US")
        assert nm._engines.cache == {"vi-VN": 2}
        nm._drop_engine("xx")  # không có thì không lỗi

    def test_falls_back_to_winocr_when_the_cached_engine_path_fails(self, monkeypatch):
        import asyncio
        import sys
        import types

        fake_winocr = types.ModuleType("winocr")

        async def recognize_pil(pil, lang):
            return _Result("từ winocr")

        fake_winocr.recognize_pil = recognize_pil
        monkeypatch.setitem(sys.modules, "winocr", fake_winocr)

        def broken(lang):
            raise RuntimeError("không tạo được engine")

        monkeypatch.setattr(nm, "_engine", broken)
        out = asyncio.run(nm._recognize(nm.Image.new("RGB", (8, 8)), "en-US"))
        assert out.text == "từ winocr"

    def test_failed_read_drops_the_engine_and_is_recorded(self, monkeypatch, clean_errors):
        dropped = []

        async def boom(pil, lang):
            raise OSError("Another RecognizeAsync operation is already running!")

        monkeypatch.setattr(nm, "installed_ocr_languages", lambda: ["en-US"])
        monkeypatch.setattr(nm, "_recognize", boom)
        monkeypatch.setattr(nm, "_drop_engine", dropped.append)
        assert nm._read_winocr(FRAME) == ""
        assert dropped == ["en-US"]
        assert any("Another RecognizeAsync" in m for m in nm.drain_ocr_errors())


class TestOcrLanguagesInUse:
    def use(self, monkeypatch, installed):
        monkeypatch.setattr(nm, "installed_ocr_languages", lambda: list(installed))
        return nm.ocr_languages_in_use()

    def test_preferred_languages_first_and_only_if_installed(self, monkeypatch):
        assert self.use(monkeypatch, ["vi-VN", "en-US"]) == ["en-US", "vi-VN"]
        assert self.use(monkeypatch, ["en-US"]) == ["en-US"]  # vi-VN chưa cài thì không thử (tránh lỗi vô ích)

    def test_english_variant_is_used_when_en_us_missing(self, monkeypatch):
        assert self.use(monkeypatch, ["ja-JP", "en-GB"]) == ["en-GB", "ja-JP"]

    def test_any_installed_language_is_last_resort(self, monkeypatch):
        assert self.use(monkeypatch, ["ja-JP"]) == ["ja-JP"]

    def test_none_installed(self, monkeypatch):
        assert self.use(monkeypatch, []) == []

    def test_refresh_clears_cached_state(self, monkeypatch):
        nm._installed_langs = ["en-US"]
        nm._ocr_backend = "winocr"
        nm.refresh_ocr_state()
        assert nm._installed_langs is None and nm._ocr_backend is None


class TestExplainAndNearest:
    """Hai hàm chỉ để ghi Nhật ký (bằng chứng mua, 'gần khớp'); không ảnh hưởng quyết định mua."""

    def test_nearest_target_ignores_the_threshold(self):
        m = NameMatcher(["Yunara", "Vex"], ALL_NAMES, 0.9)
        assert m.match("Yunarr") is None  # dưới ngưỡng 0.9
        target, score = m.nearest_target("Yunarr")
        assert target == "Yunara" and 0.8 < score < 0.9

    def test_nearest_target_returns_original_target_name_for_aliases(self):
        m = NameMatcher(["Ngộ Không"], None, 0.8, {"Ngộ Không": ["Wukong"]})
        assert m.nearest_target("Wukonq")[0] == "Ngộ Không"

    def test_nearest_target_of_noise_is_none_or_low(self):
        m = NameMatcher(["Yunara"], ALL_NAMES, 0.8)
        assert m.nearest_target("") is None and m.nearest_target("ab") is None
        assert m.nearest_target("zzzzzz")[1] < 0.4

    def test_explain_ranks_the_whole_list_and_marks_targets(self):
        m = NameMatcher(["Graves"], ALL_NAMES, 0.8)
        top = m.explain("Gragas")
        assert [name for _s, name, _t in top][0].lower() == "gragas" and top[0][2] is False  # khớp nhất là tướng KHÔNG phải mục tiêu
        assert any(name == "Graves" and is_target for _s, name, is_target in top)
        assert top == sorted(top, key=lambda r: r[0], reverse=True) and len(top) == 3

    def test_explain_of_empty_text_is_empty(self):
        assert NameMatcher(["Vex"], ALL_NAMES, 0.8).explain("  12 ") == []

    def test_match_is_unchanged_by_the_new_helpers(self):
        m = NameMatcher(["Graves"], ALL_NAMES, 0.8)
        assert m.match("Gragas") is None and m.match("Graves 2") == ("Graves", 1.0)
