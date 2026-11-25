import json

import pytest

import core.config as config


def test_roundtrip_and_no_temp_left(data_dir):
    config.save_config({**config.DEFAULT_CONFIG, "manual_names": "Vex, Jinx"})
    loaded, notes = config.load_config_with_notes()
    assert loaded["manual_names"] == "Vex, Jinx"
    assert notes == []
    assert not config.CONFIG_PATH.with_name("config.json.tmp").exists()


def test_second_save_keeps_previous_as_bak(data_dir):
    config.save_config({"manual_names": "A"})
    config.save_config({"manual_names": "B"})
    bak = json.loads(config.CONFIG_PATH.with_name("config.json.bak").read_text(encoding="utf-8"))
    assert bak["manual_names"] == "A"
    assert config.load_config_with_notes()[0]["manual_names"] == "B"


def test_corrupt_config_restored_from_bak(data_dir):
    config.save_config({"manual_names": "A"})
    config.save_config({"manual_names": "B"})
    config.CONFIG_PATH.write_text('{"manual_names": "tr', encoding="utf-8")  # bị cắt cụt giữa chừng

    loaded, notes = config.load_config_with_notes()

    assert loaded["manual_names"] == "A"  # lần lưu trước đó
    assert any("khôi phục" in n for n in notes)
    assert config.CONFIG_PATH.with_name("config.json.bad").exists()
    assert json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))["manual_names"] == "A"  # đã ghi lại file tốt


def test_corrupt_config_without_bak_uses_defaults(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    config.CONFIG_PATH.write_text("not json at all", encoding="utf-8")

    loaded, notes = config.load_config_with_notes()

    assert loaded == config.DEFAULT_CONFIG
    assert any("mặc định" in n for n in notes)
    assert config.CONFIG_PATH.with_name("config.json.bad").exists()


def test_config_that_is_not_an_object_counts_as_corrupt(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    config.CONFIG_PATH.write_text("[1, 2, 3]", encoding="utf-8")
    loaded, notes = config.load_config_with_notes()
    assert loaded == config.DEFAULT_CONFIG and notes


def test_corrupt_file_never_overwrites_good_bak(data_dir):
    config.save_config({"manual_names": "A"})
    config.save_config({"manual_names": "B"})  # bak = A
    config.CONFIG_PATH.write_text("garbage", encoding="utf-8")
    config.save_config({"manual_names": "C"})
    bak = json.loads(config.CONFIG_PATH.with_name("config.json.bak").read_text(encoding="utf-8"))
    assert bak["manual_names"] == "A"


def test_unserializable_config_leaves_existing_file_untouched(data_dir):
    config.save_config({"manual_names": "A"})
    before = config.CONFIG_PATH.read_text(encoding="utf-8")
    with pytest.raises(TypeError):
        config.save_config({"bad": object()})
    assert config.CONFIG_PATH.read_text(encoding="utf-8") == before
    assert not config.CONFIG_PATH.with_name("config.json.tmp").exists()


def test_failure_while_replacing_leaves_original_intact(data_dir, monkeypatch):
    """Ngắt đúng lúc thay file: config.json cũ phải còn nguyên, không bị ghi dở."""
    config.save_config({"manual_names": "A"})
    before = config.CONFIG_PATH.read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("ngắt giữa chừng")

    monkeypatch.setattr(config.os, "replace", boom)
    with pytest.raises(OSError):
        config.save_config({"manual_names": "B"})
    assert config.CONFIG_PATH.read_text(encoding="utf-8") == before


def test_defaults_are_not_shared_between_loads(data_dir):
    first = config.load_config_with_notes()[0]
    first["selected_champions"].append("Vex")
    first["custom_templates"]["Vex"] = "x"
    assert config.DEFAULT_CONFIG["selected_champions"] == []
    assert config.load_config_with_notes()[0]["custom_templates"] == {}


class TestMigrateCoordinates:
    def test_old_config_loses_coordinates(self):
        cfg = {"shop_region": {"left": 1, "top": 2, "width": 3, "height": 4}, "slot_centers": [(1, 1)] * 5}
        assert config.migrate_coordinates(cfg) is True
        assert cfg["shop_region"] is None and cfg["slot_centers"] == []
        assert cfg["coords_version"] == config.COORDS_VERSION

    def test_current_version_untouched(self):
        cfg = {"coords_version": config.COORDS_VERSION, "shop_region": {"left": 1}, "slot_centers": [(1, 1)]}
        assert config.migrate_coordinates(cfg) is False
        assert cfg["shop_region"] == {"left": 1}

    def test_fresh_config_has_nothing_to_report(self):
        cfg = {"shop_region": None, "slot_centers": []}
        assert config.migrate_coordinates(cfg) is False
        assert cfg["coords_version"] == config.COORDS_VERSION

    def test_default_config_must_not_carry_version(self):
        """Nếu DEFAULT_CONFIG có coords_version, config cũ sẽ được gộp thành 'đã đúng' và không bao giờ migrate."""
        assert "coords_version" not in config.DEFAULT_CONFIG


class TestTemplatePaths:
    def test_relative_path_resolves_inside_data(self, data_dir):
        config.ensure_dirs()
        f = config.TEMPLATES_DIR / "custom_Vex.png"
        f.write_bytes(b"x")
        assert config.resolve_template_path("templates/custom_Vex.png") == f

    def test_stale_absolute_path_falls_back_to_same_name_in_templates(self, data_dir):
        config.ensure_dirs()
        f = config.TEMPLATES_DIR / "custom_Aatrox.png"
        f.write_bytes(b"x")
        stale = r"C:\Users\Admin\Desktop\tool_reroll\data\templates\custom_Aatrox.png"
        assert config.resolve_template_path(stale) == f

    def test_missing_returns_none(self, data_dir):
        config.ensure_dirs()
        assert config.resolve_template_path(r"C:\Users\Admin\x\custom_Nope.png") is None

    def test_normalize_converts_found_and_keeps_unfound(self, data_dir):
        config.ensure_dirs()
        (config.TEMPLATES_DIR / "custom_A.png").write_bytes(b"x")
        result = config.normalize_custom_templates(
            {"A": r"C:\old\custom_A.png", "B": r"C:\old\custom_B.png"}
        )
        assert result == {"A": "templates/custom_A.png", "B": r"C:\old\custom_B.png"}


def test_default_name_threshold_is_safe_and_saved_value_is_kept(data_dir):
    assert config.DEFAULT_CONFIG["name_match_threshold"] >= 0.80
    config.save_config({"name_match_threshold": 0.7524})  # giá trị người dùng đã chọn không bị nâng ngầm
    assert config.load_config_with_notes()[0]["name_match_threshold"] == 0.7524
    assert config.load_config_with_notes()[0]["match_threshold"] == config.DEFAULT_CONFIG["match_threshold"]


def test_new_keys_have_defaults(data_dir):
    cfg = config.load_config_with_notes()[0]
    assert cfg["champion_locale"] == "vi_VN" and cfg["season_filter"] == [] and "show_old_sets" not in cfg


def test_normalize_custom_templates_strips_champion_name_keys(data_dir):
    """Tên tướng từ Data Dragon từng có dấu cách thừa ('Tryndamere ') nên khóa cũ trong config phải được dọn."""
    config.ensure_dirs()
    (config.TEMPLATES_DIR / "custom_Tryndamere.png").write_bytes(b"x")
    result = config.normalize_custom_templates({"Tryndamere ": "templates/custom_Tryndamere.png"})
    assert result == {"Tryndamere": "templates/custom_Tryndamere.png"}


import copy  # noqa: E402


def fresh():
    return copy.deepcopy(config.DEFAULT_CONFIG)


class TestBom:
    """File sửa bằng Notepad kiểu 'UTF-8 with BOM' từng bị coi là hỏng và đổi tên .bad."""

    def write_bom(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xef\xbb\xbf" + json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def test_config_with_bom_loads_without_being_treated_as_corrupt(self, data_dir):
        self.write_bom(config.CONFIG_PATH, {**fresh(), "manual_names": "SỬA TAY"})
        cfg, notes = config.load_config_with_notes()
        assert cfg["manual_names"] == "SỬA TAY" and notes == []
        assert not config.CONFIG_PATH.with_name("config.json.bad").exists()

    def test_bak_with_bom_is_usable_for_recovery(self, data_dir):
        self.write_bom(config.CONFIG_PATH.with_name("config.json.bak"), {**fresh(), "manual_names": "TỪ BAK"})
        config.CONFIG_PATH.write_text("{hỏng", encoding="utf-8")
        cfg, notes = config.load_config_with_notes()
        assert cfg["manual_names"] == "TỪ BAK" and any("khôi phục" in n for n in notes)

    def test_save_never_writes_a_bom(self, data_dir):
        config.save_config({**fresh(), "manual_names": "x"})
        assert not config.CONFIG_PATH.read_bytes().startswith(b"\xef\xbb\xbf")


class TestSanitizeLeavesValidConfigAlone:
    def test_defaults_are_untouched(self):
        cfg = fresh()
        assert config.sanitize_config(cfg) == [] and cfg == config.DEFAULT_CONFIG

    def test_users_real_style_values_are_untouched(self):
        cfg = {**fresh(), "name_match_threshold": 0.7524038461538461, "scan_interval_ms": 0,
               "selected_champions": ["Mel ", "Tryndamere "], "match_threshold": 0.5,
               "shop_region": {"left": 303, "top": 293, "width": 974, "height": 241},
               "slot_centers": [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]],
               "custom_templates": {"Aatrox": "templates/custom_Aatrox.png"}, "unknown_key": {"x": [1]}}
        before = copy.deepcopy(cfg)
        assert config.sanitize_config(cfg) == [] and cfg == before

    def test_champion_names_keep_their_whitespace(self):
        """Tên 'Mel ' (dấu cách thừa từ Data Dragon cũ) được chuẩn hóa lúc so khớp; không cần, và không nên, báo."""
        cfg = {**fresh(), "selected_champions": ["Mel "]}
        assert config.sanitize_config(cfg) == [] and cfg["selected_champions"] == ["Mel "]

    def test_unknown_keys_survive(self):
        cfg = {**fresh(), "my_note": "giữ lại", "nested": {"a": 1}}
        config.sanitize_config(cfg)
        assert cfg["my_note"] == "giữ lại" and cfg["nested"] == {"a": 1}

    def test_is_idempotent(self):
        cfg = {**fresh(), "scan_interval_ms": "5", "game_process_names": "x.exe", "match_threshold": 9}
        first = config.sanitize_config(cfg)
        assert first and config.sanitize_config(cfg) == []

    def test_limits_cover_real_keys_and_defaults_are_inside_them(self):
        for key, (lo, hi) in config.NUMERIC_LIMITS.items():
            assert key in config.DEFAULT_CONFIG and lo <= config.DEFAULT_CONFIG[key] <= hi, key


class TestSanitizeFixesWrongValues:
    def run(self, **overrides):
        cfg = {**fresh(), **overrides}
        notes = config.sanitize_config(cfg)
        return cfg, notes

    # --- danh sách chuỗi (lỗi gốc: chuỗi → tập ký tự → không bao giờ click)
    def test_process_name_as_plain_string_becomes_a_one_item_list(self):
        cfg, notes = self.run(game_process_names="League of Legends.exe")
        assert cfg["game_process_names"] == ["League of Legends.exe"]
        assert len(notes) == 1 and "game_process_names" in notes[0]

    def test_process_names_are_stripped(self):
        cfg, notes = self.run(game_process_names=["League of Legends.exe "])
        assert cfg["game_process_names"] == ["League of Legends.exe"] and notes

    @pytest.mark.parametrize("bad", [[], [""], [5, None], 5, None, {"a": 1}])
    def test_unusable_process_names_fall_back_to_default(self, bad):
        cfg, notes = self.run(game_process_names=bad)
        assert cfg["game_process_names"] == ["League of Legends.exe"] and notes

    def test_selected_champions_drops_junk_but_keeps_good_names(self):
        cfg, notes = self.run(selected_champions=["Vex", 5, "", None, "Zed"])
        assert cfg["selected_champions"] == ["Vex", "Zed"] and "bỏ 3" in notes[0]

    def test_selected_champions_string_becomes_list(self):
        assert self.run(selected_champions="Vex")[0]["selected_champions"] == ["Vex"]

    # --- số: ép kiểu rõ ý, kẹp biên, mặc định khi không đoán được
    @pytest.mark.parametrize(
        "raw,expected",
        [("5", 5), (" 7 ", 7), (5.0, 5), (5.7, 6), ("5.0", 5)],
    )
    def test_int_values_are_coerced(self, raw, expected):
        cfg, _ = self.run(scan_interval_ms=raw)
        assert cfg["scan_interval_ms"] == expected and type(cfg["scan_interval_ms"]) is int

    @pytest.mark.parametrize("raw,expected", [("0.8", 0.8), ("0,8", 0.8), (1, 0.95), (".7", 0.7)])
    def test_float_values_accept_vietnamese_decimal_comma_and_strings(self, raw, expected):
        cfg, _ = self.run(name_match_threshold=raw)
        assert cfg["name_match_threshold"] == expected

    @pytest.mark.parametrize(
        "key,raw,expected",
        [
            ("name_match_threshold", 0.3, 0.5),
            ("match_threshold", 7, 0.95),
            ("card_same_corr", 0.1, 0.5),
            ("scan_interval_ms", -5, 0),
            ("scan_interval_ms", 5000, 100),
            ("buy_cooldown_ms", -1, 0),
            ("buy_delay_ms", 10**6, 2000),
            ("name_scan_interval_ms", "99999", 2000),
        ],
    )
    def test_out_of_range_numbers_are_clamped_to_the_nearest_edge(self, key, raw, expected):
        cfg, notes = self.run(**{key: raw})
        assert cfg[key] == expected and any(key in n and "kẹp" in n for n in notes)

    @pytest.mark.parametrize("raw", ["fast", "", None, [1], {"a": 1}, True, float("nan"), float("inf"), "nan"])
    def test_unparseable_numbers_fall_back_to_default(self, raw):
        cfg, notes = self.run(scan_interval_ms=raw, match_threshold=raw)
        assert cfg["scan_interval_ms"] == config.DEFAULT_CONFIG["scan_interval_ms"]
        assert cfg["match_threshold"] == config.DEFAULT_CONFIG["match_threshold"] and len(notes) == 2

    # --- bool. Dùng khóa có mặc định NGƯỢC với giá trị mong đợi, nếu không từ không được hiểu vẫn "đúng" nhờ mặc định.
    @pytest.mark.parametrize("raw", ["true", "True", "YES", " on ", "1", 1, 1.0, "có", "co"])
    def test_true_words_are_understood(self, raw, monkeypatch):
        monkeypatch.setitem(config.DEFAULT_CONFIG, "detect_by_image", False)  # mặc định False → True chỉ đến từ việc hiểu đúng
        assert self.run(detect_by_image=raw)[0]["detect_by_image"] is True

    @pytest.mark.parametrize("raw", ["false", "False", "NO", " off ", "0", 0, 0.0, "không", "khong"])
    def test_false_words_are_understood(self, raw):
        assert config.DEFAULT_CONFIG["require_game_foreground"] is True  # mặc định True → False chỉ đến từ việc hiểu đúng
        assert self.run(require_game_foreground=raw)[0]["require_game_foreground"] is False

    @pytest.mark.parametrize("raw", ["maybe", 2, None, [], "", 0.5])
    def test_unknown_bool_falls_back_to_default(self, raw, monkeypatch):
        monkeypatch.setitem(config.DEFAULT_CONFIG, "detect_by_image", False)
        cfg, notes = self.run(detect_by_image=raw)
        assert cfg["detect_by_image"] is False and notes

    # --- chuỗi, ngôn ngữ, phím
    def test_hotkey_whitespace_is_trimmed_and_noted(self):
        cfg, notes = self.run(hotkey_toggle=" f8 ")
        assert cfg["hotkey_toggle"] == "f8" and notes

    @pytest.mark.parametrize("raw", ["", "   ", 5, None])
    def test_unusable_hotkey_falls_back(self, raw):
        assert self.run(hotkey_toggle=raw)[0]["hotkey_toggle"] == "f8"

    @pytest.mark.parametrize("raw", ["vietnamese", "vi-VN", "viVN", "../x", 5, None, ""])
    def test_bad_locale_falls_back(self, raw):
        cfg, notes = self.run(champion_locale=raw)
        assert cfg["champion_locale"] == "vi_VN" and notes

    def test_good_locale_is_kept(self):
        assert self.run(champion_locale="en_US") == ({**fresh(), "champion_locale": "en_US"}, [])

    def test_manual_names_must_be_a_string(self):
        assert self.run(manual_names=5)[0]["manual_names"] == ""

    # --- cấu trúc
    def test_custom_templates_drops_bad_entries(self):
        cfg, notes = self.run(custom_templates={"A": "x.png", "B": 3, 7: "y"})
        assert cfg["custom_templates"] == {"A": "x.png"} and "bỏ 2" in notes[0]

    def test_custom_templates_not_a_dict(self):
        assert self.run(custom_templates=["a"])[0]["custom_templates"] == {}

    @pytest.mark.parametrize(
        "region",
        [{"left": 1, "top": 2}, {"left": 1, "top": 2, "width": 0, "height": 5}, {"left": "x", "top": 2, "width": 3, "height": 4},
         "1,2,3,4", [1, 2, 3, 4], 5, {"left": 1, "top": 2, "width": -3, "height": 4}],
    )
    def test_invalid_shop_region_is_dropped_with_instruction(self, region):
        cfg, notes = self.run(shop_region=region)
        assert cfg["shop_region"] is None and "chọn lại" in notes[0]

    def test_shop_region_numbers_are_coerced(self):
        cfg, _ = self.run(shop_region={"left": "10", "top": 20.0, "width": "300", "height": 100})
        assert cfg["shop_region"] == {"left": 10, "top": 20, "width": 300, "height": 100}

    def test_negative_region_origin_is_fine(self):
        """Màn hình phụ nằm bên trái màn chính có tọa độ âm."""
        cfg, notes = self.run(shop_region={"left": -1500, "top": -20, "width": 900, "height": 120})
        assert notes == [] and cfg["shop_region"]["left"] == -1500

    @pytest.mark.parametrize(
        "pts",
        [[[1, 2], [3, 4]], "x", [[1, 2]] * 6, [[1], [2], [3], [4], [5]], [[1, "a"]] * 5, [5] * 5, 7],
    )
    def test_invalid_click_points_are_dropped_with_instruction(self, pts):
        cfg, notes = self.run(slot_centers=pts)
        assert cfg["slot_centers"] == [] and "đặt lại" in notes[0]

    def test_click_points_are_coerced_to_int_pairs(self):
        cfg, notes = self.run(slot_centers=[("1", 2.0)] + [[3, 4]] * 4)
        assert cfg["slot_centers"][0] == [1, 2] and notes == []

    def test_empty_click_points_mean_not_set(self):
        assert self.run(slot_centers=[]) == ({**fresh(), "slot_centers": []}, [])

    # --- bộ lọc mùa
    def test_season_filter_default_is_all_seasons(self):
        cfg, notes = self.run()
        assert cfg["season_filter"] == [] and notes == []

    def test_valid_season_filter_is_untouched(self):
        cfg, notes = self.run(season_filter=[18, 7])
        assert cfg["season_filter"] == [18, 7] and notes == []

    def test_season_filter_is_cleaned_and_noted(self):
        cfg, notes = self.run(season_filter=["17", 18, "x", -1, 0, True, 18])
        assert cfg["season_filter"] == [18, 17] and "season_filter" in notes[0]

    @pytest.mark.parametrize("raw,expected", [(18, [18]), ("18", [18]), (("17", 18), [18, 17])])
    def test_single_value_or_tuple_becomes_a_list(self, raw, expected):
        assert self.run(season_filter=raw)[0]["season_filter"] == expected

    @pytest.mark.parametrize("junk", [None, {"a": 1}, {"x"}])
    def test_season_filter_of_the_wrong_type_uses_the_default(self, junk):
        cfg, notes = self.run(season_filter=junk)
        assert cfg["season_filter"] == [] and "season_filter" in notes[0]

    def test_old_show_old_sets_key_is_ignored_and_kept_as_an_unknown_key(self):
        cfg, notes = self.run(show_old_sets=True)
        assert cfg["show_old_sets"] is True and notes == [] and cfg["season_filter"] == []

    # --- bộ cấu hình theo màn hình
    PROFILE = {"name": "Màn hình 1", "monitor": {"left": 0, "top": 0, "width": 1920, "height": 1080},
               "shop_region": {"left": 360, "top": 900, "width": 1200, "height": 160},
               "slot_centers": [[450 + i * 230, 1000] for i in range(5)]}

    def test_no_profiles_by_default(self):
        cfg, notes = self.run()
        assert cfg["monitor_profiles"] == {} and cfg["active_monitor"] == "" and notes == []

    def test_valid_profiles_are_kept_untouched(self):
        profiles = {"a|1920x1080": self.PROFILE, "b|2560x1440": {**self.PROFILE, "slot_centers": []}}
        cfg, notes = self.run(monitor_profiles=profiles, active_monitor="a|1920x1080")
        assert cfg["monitor_profiles"] == profiles and cfg["active_monitor"] == "a|1920x1080" and notes == []

    def test_negative_coordinates_in_a_profile_are_fine(self):
        left_monitor = {**self.PROFILE, "monitor": {"left": -1920, "top": 0, "width": 1920, "height": 1080},
                        "shop_region": {"left": -1560, "top": 900, "width": 1200, "height": 160}}
        cfg, notes = self.run(monitor_profiles={"x|1920x1080": left_monitor})
        assert notes == [] and cfg["monitor_profiles"]["x|1920x1080"]["shop_region"]["left"] == -1560

    def test_broken_profiles_are_dropped_and_good_ones_kept(self):
        broken = {**self.PROFILE, "slot_centers": [[1, 2]]}  # 1 điểm: không phải 0 hoặc 5
        cfg, notes = self.run(monitor_profiles={"ok|1": self.PROFILE, "bad|1": broken, "junk|1": "x", 7: self.PROFILE})
        assert list(cfg["monitor_profiles"]) == ["ok|1"] and "bỏ 3 bộ" in notes[0] and "chọn lại" in notes[0]

    @pytest.mark.parametrize("junk", [None, [], "x", 5, ["a"]])
    def test_profiles_not_a_dict_use_the_default(self, junk):
        cfg, notes = self.run(monitor_profiles=junk)
        assert cfg["monitor_profiles"] == {} and "monitor_profiles" in notes[0]

    @pytest.mark.parametrize("junk", [None, 5, ["a"], {"a": 1}])
    def test_active_monitor_must_be_a_string(self, junk):
        cfg, notes = self.run(active_monitor=junk)
        assert cfg["active_monitor"] == "" and "active_monitor" in notes[0]


class TestLoadEndToEnd:
    def hand_edited(self, **overrides):
        return {**fresh(), "coords_version": config.COORDS_VERSION, **overrides}

    def test_hand_edited_file_is_repaired_and_reported(self, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        config.CONFIG_PATH.write_text(
            json.dumps(self.hand_edited(game_process_names="League of Legends.exe", scan_interval_ms="5",
                                        name_match_threshold="0,3")),
            encoding="utf-8",
        )
        cfg, notes = config.load_config_with_notes()
        assert cfg["game_process_names"] == ["League of Legends.exe"] and cfg["scan_interval_ms"] == 5
        assert cfg["name_match_threshold"] == 0.5
        assert len(notes) == 3 and all(n.startswith("Cấu hình '") for n in notes)

    def test_after_a_save_the_file_is_clean_and_no_longer_reports(self, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        config.CONFIG_PATH.write_text(json.dumps(self.hand_edited(scan_interval_ms="5")), encoding="utf-8")
        cfg, notes = config.load_config_with_notes()
        assert notes
        config.save_config(cfg)
        assert config.load_config_with_notes()[1] == []

    def test_recovered_bak_is_sanitized_too(self, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        config.CONFIG_PATH.with_name("config.json.bak").write_text(
            json.dumps(self.hand_edited(game_process_names="x.exe")), encoding="utf-8"
        )
        config.CONFIG_PATH.write_text("{hỏng", encoding="utf-8")
        cfg, notes = config.load_config_with_notes()
        assert cfg["game_process_names"] == ["x.exe"] and any("game_process_names" in n for n in notes)

    def test_missing_file_and_fresh_install_report_nothing(self, data_dir):
        assert config.load_config_with_notes()[1] == []


class TestParseIntInRange:
    @pytest.mark.parametrize("text,expected", [("5", 5), (" 5 ", 5), ("0", 0), ("100", 100), ("5.0", 5), ("007", 7)])
    def test_valid(self, text, expected):
        assert config.parse_int_in_range(text, 0, 100) == expected

    @pytest.mark.parametrize("text", ["", "   ", "abc", "5.5", "-1", "101", "1e9", "nan", "inf", "5 ms", None, 5, "0x10", "--3"])
    def test_invalid_returns_none_instead_of_guessing(self, text):
        assert config.parse_int_in_range(text, 0, 100) is None

    def test_respects_custom_bounds(self):
        assert config.parse_int_in_range("5", 10, 20) is None and config.parse_int_in_range("15", 10, 20) == 15


def test_locale_helpers_are_shared_with_champions():
    from core import champions

    assert champions.normalize_locale is config.normalize_locale


class TestRollKeyConfig:
    def test_default(self):
        assert config.DEFAULT_CONFIG["roll_key"] == "d"

    def test_non_string_falls_back_to_default(self):
        cfg = {**config.DEFAULT_CONFIG, "roll_key": 5}
        notes = config.sanitize_config(cfg)
        assert cfg["roll_key"] == "d" and any("roll_key" in n for n in notes)

    def test_whitespace_is_stripped_and_reported(self):
        cfg = {**config.DEFAULT_CONFIG, "roll_key": " r "}
        notes = config.sanitize_config(cfg)
        assert cfg["roll_key"] == "r" and any("roll_key" in n and "thừa khoảng trắng" in n for n in notes)

    def test_empty_string_is_allowed_to_disable(self):
        cfg = {**config.DEFAULT_CONFIG, "roll_key": ""}
        assert config.sanitize_config(cfg) == [] and cfg["roll_key"] == ""


class TestGameProcessSet:
    def test_known_game_processes_are_always_included(self):
        names = config.game_process_set(["League of Legends.exe"])  # config cũ chỉ lưu tên cũ
        assert {"league of legends.exe", "tftclient-win64-shipping.exe"} <= names

    def test_user_names_are_added_and_lowercased(self):
        assert "mygame.exe" in config.game_process_set(["MyGame.EXE"])

    @pytest.mark.parametrize("raw", [None, [], ()])
    def test_empty_config_still_recognises_the_game(self, raw):
        assert config.game_process_set(raw) == frozenset({"league of legends.exe", "tftclient-win64-shipping.exe"})
