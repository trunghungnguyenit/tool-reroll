"""Chi tiết tướng (core.champion_details): làm sạch mô tả kỹ năng, rút gọn dữ liệu CommunityDragon, lưu đệm/offline, chữ hiển thị."""

import json
from datetime import datetime, timedelta

import pytest
import requests

import core.champion_details as cd


# ----------------------------------------------------------------------------- mô tả kỹ năng
class TestCleanDescription:
    def test_none_or_blank_is_empty_and_complete(self):
        assert cd.clean_description(None) == ("", True)
        assert cd.clean_description("   ") == ("", True)
        assert cd.clean_description(123) == ("", True)

    def test_tags_line_breaks_and_entities(self):
        text, ok = cd.clean_description("<b>Nội tại:</b> hồi máu<br><br>Kích hoạt:&nbsp;gây <magicDamage>sát thương</magicDamage> &amp; choáng")
        assert text == "Nội tại: hồi máu\n\nKích hoạt: gây sát thương & choáng" and ok

    def test_literal_backslash_n_becomes_a_line_break(self):
        assert cd.clean_description(r"Một\n \nHai")[0] == "Một\n\nHai"

    def test_stat_icons_become_words_and_unknown_icons_vanish(self):
        text, _ = cd.clean_description("gây %i:scaleAD%%i:scaleAP% sát thương, %i:set14AmpIcon% và (%i:scaleArmor%)")
        assert text == "gây AD+AP sát thương, và (Giáp)"

    def test_empty_parentheses_left_by_an_unknown_icon_are_dropped(self):
        assert cd.clean_description("tăng (%i:khongBiet%) nữa")[0] == "tăng nữa"

    def test_variables_fill_per_star_values(self):
        variables = [{"name": "Damage", "value": [0, 100, 150, 225, 400, 0, 0]}]
        text, ok = cd.clean_description("Gây @Damage@ sát thương", variables)
        assert text == "Gây 100 / 150 / 225 sát thương" and ok

    def test_same_value_for_every_star_is_shown_once(self):
        variables = [{"name": "Duration", "value": [3, 3, 3, 3, 3, 3, 3]}]
        assert cd.clean_description("trong @Duration@ giây", variables)[0] == "trong 3 giây"

    def test_multiplier_and_float_noise(self):
        variables = [{"name": "Ratio", "value": [0, 0.25, 0.35, 0.4, 0, 0, 0]}, {"name": "ADDamage", "value": [3.3, 120.0, 180.0, 285.0, 485.0, 3.3, 3.3]}]
        text, _ = cd.clean_description("giảm @Ratio*100@% và @ADDamage@", variables)
        assert text == "giảm 25 / 35 / 40% và 120 / 180 / 285"

    def test_variable_lookup_ignores_case(self):
        assert cd.clean_description("@damage@", [{"name": "Damage", "value": [0, 1, 2, 3]}])[0] == "1 / 2 / 3"

    def test_unknown_placeholder_shows_marker_and_flags_incomplete(self):
        text, ok = cd.clean_description("Gây @ModifiedDamage@ sát thương", [{"name": "Other", "value": [1, 2, 3, 4]}])
        assert text == f"Gây {cd.MISSING} sát thương" and not ok

    def test_non_numeric_variable_is_treated_as_missing(self):
        text, ok = cd.clean_description("@Bad@", [{"name": "Bad", "value": [0, "x", None, 3]}])
        assert text == cd.MISSING and not ok

    def test_malformed_variables_do_not_crash(self):
        text, ok = cd.clean_description("@A@", [None, {"name": 5}, {"name": "A"}, {"name": "A", "value": "nope"}])
        assert text == cd.MISSING and not ok

    def test_keyword_references_are_dropped_silently(self):
        text, ok = cd.clean_description("Gây Tê Tái 30% trong 2 giây.<br><br>{{TFT_Keyword_Chill}}")
        assert text == "Gây Tê Tái 30% trong 2 giây." and ok and "{{" not in text

    def test_other_string_references_are_missing_content(self):
        text, ok = cd.clean_description("Chomp: {{Spell_TFT13_LieutenantSpell3_Tooltip}}")
        assert text == f"Chomp: {cd.MISSING}" and not ok

    def test_very_long_variable_names_are_still_recognised(self):
        name = "TFTUnitProperty.:TFT15_BattleAcademia_Katarina_FullPotential_TextualData"
        text, ok = cd.clean_description(f"Potential: @{name}@ xong")
        assert text == f"Potential: {cd.MISSING} xong" and not ok and "@" not in text

    def test_whitespace_is_tidied(self):
        assert cd.clean_description("a   b \n \n \n\n c")[0] == "a b\n\nc"


# ----------------------------------------------------------------------------- rút gọn dữ liệu thô
def raw_champ(name, cost=1, role=None, traits=("Hệ A",), desc="Mô tả", variables=None, **stats):
    return {"name": name, "cost": cost, "role": role, "traits": list(traits),
            "stats": {"hp": 600.0, "damage": 50.0, "armor": 30.0, "magicResist": 30.0, "attackSpeed": 0.7, "range": 1.0,
                      "initialMana": 10.0, "mana": 60, "critChance": 0.25, **stats},
            "ability": {"name": f"Chiêu {name}", "desc": desc, "variables": variables or []}}


def raw_catalog(**sets):
    return {"sets": {k.removeprefix("s"): {"champions": v} for k, v in sets.items()}, "items": [], "setData": []}


class TestParseCatalog:
    def test_newest_season_wins_per_name(self):
        cat = cd.parse_catalog(raw_catalog(s7=[raw_champ("Zed", cost=3)], s17=[raw_champ("Zed", cost=5)], s13=[raw_champ("Zed", cost=4)]))
        assert len(cat) == 1 and cat["zed"]["set"] == 17 and cat["zed"]["cost"] == 5

    def test_same_season_duplicates_prefer_the_complete_entry(self):
        bare = raw_champ("Sói", desc="", traits=())
        full = raw_champ("Sói", desc="Có kỹ năng", traits=("Quái",))
        for order in ([bare, full], [full, bare]):
            cat = cd.parse_catalog(raw_catalog(s18=order))
            assert cat["soi"]["traits"] == ["Quái"] and cat["soi"]["ability"]["desc"] == "Có kỹ năng"

    def test_key_ignores_accents_case_and_quotes(self):
        cat = cd.parse_catalog(raw_catalog(s16=[raw_champ("Kha'Zix"), raw_champ("Ngộ Không")]))
        assert set(cat) == {"khazix", "ngokhong"}

    def test_entry_fields(self):
        cat = cd.parse_catalog(raw_catalog(s16=[raw_champ("Jinx", cost=2, role="ADCaster", traits=("Siêu Thú", " ", "Thách Đấu"))]))
        e = cat["jinx"]
        assert (e["name"], e["set"], e["cost"], e["role"], e["traits"]) == ("Jinx", 16, 2, "ADCaster", ["Siêu Thú", "Thách Đấu"])
        assert e["stats"]["hp"] == 600.0 and e["ability"] == {"name": "Chiêu Jinx", "desc": "Mô tả", "complete": True}

    def test_missing_or_broken_fields_do_not_crash(self):
        broken = {"name": "Lạ", "cost": "3", "role": 5, "traits": None, "stats": {"hp": "x", "range": True, "damage": 40},
                  "ability": {"name": None, "desc": None, "variables": None}}
        cat = cd.parse_catalog(raw_catalog(s16=[broken, {"name": ""}, {"nope": 1}, "rác", {"name": "Tối giản"}]))
        assert cat["la"]["stats"] == {"damage": 40} and cat["la"]["cost"] is None and cat["la"]["role"] == "" and cat["la"]["traits"] == []
        assert cat["la"]["ability"] == {"name": "", "desc": "", "complete": True}
        assert "toigian" in cat and len(cat) == 2

    def test_incomplete_description_is_flagged(self):
        cat = cd.parse_catalog(raw_catalog(s18=[raw_champ("Cóc", desc="Gây @CalcX@ sát thương")]))
        assert cat["coc"]["ability"]["complete"] is False and cd.MISSING in cat["coc"]["ability"]["desc"]

    def test_non_numeric_season_keys_are_skipped(self):
        raw = {"sets": {"abc": {"champions": [raw_champ("A")]}, "5": {"champions": [raw_champ("B")]}}}
        assert set(cd.parse_catalog(raw)) == {"b"}

    @pytest.mark.parametrize("raw", [{}, {"sets": []}, [], None])
    def test_unexpected_shape_raises(self, raw):
        with pytest.raises(ValueError):
            cd.parse_catalog(raw)


# ----------------------------------------------------------------------------- lưu đệm và tải
NOW = datetime(2026, 11, 23, 12, 0, 0)
SAMPLE = cd.parse_catalog(raw_catalog(s18=[raw_champ("Jinx", role="ADCaster")]))


@pytest.fixture
def fetch(monkeypatch):
    calls = []

    def fake(locale, timeout=90):
        calls.append(locale)
        return SAMPLE

    monkeypatch.setattr(cd, "fetch_catalog", fake)
    return calls


class TestCache:
    def test_roundtrip(self, data_dir):
        cd.save_cache("vi_VN", SAMPLE, NOW)
        champions, saved = cd.load_cache("vi_VN")
        assert champions == SAMPLE and saved == NOW
        assert not list(data_dir.glob("*.tmp"))

    def test_missing_corrupt_or_wrong_schema_is_none(self, data_dir):
        assert cd.load_cache("vi_VN") is None
        data_dir.mkdir(parents=True, exist_ok=True)
        path = cd.cache_path("vi_VN")
        for bad in ("không phải json", "[]", json.dumps({"schema": 99, "saved_at": NOW.isoformat(), "champions": SAMPLE}),
                    json.dumps({"schema": cd.DETAILS_SCHEMA, "saved_at": "hôm qua", "champions": SAMPLE}),
                    json.dumps({"schema": cd.DETAILS_SCHEMA, "saved_at": NOW.isoformat(), "champions": {}}),
                    json.dumps({"schema": cd.DETAILS_SCHEMA, "saved_at": NOW.isoformat(), "champions": {"x": {"name": "x"}}})):
            path.write_text(bad, encoding="utf-8")
            assert cd.load_cache("vi_VN") is None, bad

    def test_each_locale_has_its_own_file(self, data_dir):
        cd.save_cache("vi_VN", SAMPLE, NOW)
        assert cd.load_cache("en_US") is None


class TestGetDetails:
    def test_fresh_cache_is_used_without_network(self, data_dir, fetch):
        cd.save_cache("vi_VN", SAMPLE, NOW)
        result = cd.get_details("vi_VN", now=NOW + timedelta(hours=23))
        assert result.champions == SAMPLE and not result.offline and fetch == []

    def test_stale_cache_is_refreshed_and_saved(self, data_dir, fetch):
        old = {"cu": {**SAMPLE["jinx"], "name": "Cũ"}}
        cd.save_cache("vi_VN", old, NOW)
        later = NOW + cd.MAX_AGE + timedelta(minutes=1)
        result = cd.get_details("vi_VN", now=later)
        assert result.champions == SAMPLE and fetch == ["vi_VN"]
        assert cd.load_cache("vi_VN") == (SAMPLE, later)

    def test_force_refreshes_a_fresh_cache(self, data_dir, fetch):
        cd.save_cache("vi_VN", SAMPLE, NOW)
        cd.get_details("vi_VN", now=NOW, force=True)
        assert fetch == ["vi_VN"]

    def test_first_run_downloads_and_saves(self, data_dir, fetch):
        assert cd.get_details("vi_VN", now=NOW).champions == SAMPLE
        assert cd.load_cache("vi_VN")[0] == SAMPLE

    @pytest.mark.parametrize("error", [requests.ConnectionError("offline"), ValueError("hỏng"), OSError("đĩa đầy")])
    def test_offline_with_old_cache_falls_back_to_it(self, data_dir, monkeypatch, error):
        cd.save_cache("vi_VN", SAMPLE, NOW)
        monkeypatch.setattr(cd, "fetch_catalog", lambda *a, **k: (_ for _ in ()).throw(error))
        result = cd.get_details("vi_VN", now=NOW + timedelta(days=30))
        assert result.champions == SAMPLE and result.offline

    def test_offline_without_cache_raises(self, data_dir, monkeypatch):
        monkeypatch.setattr(cd, "fetch_catalog", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("offline")))
        with pytest.raises(requests.ConnectionError):
            cd.get_details("vi_VN", now=NOW)

    def test_empty_download_is_an_error_not_a_cache(self, data_dir, monkeypatch):
        monkeypatch.setattr(cd, "fetch_catalog", lambda *a, **k: {})
        with pytest.raises(ValueError):
            cd.get_details("vi_VN", now=NOW)
        assert cd.load_cache("vi_VN") is None


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data = status, data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._data


class TestFetchCatalog:
    RAW = raw_catalog(s18=[raw_champ("Jinx")])

    def test_requests_lowercase_locale_url_and_parses(self, monkeypatch):
        urls = []
        monkeypatch.setattr(cd.requests, "get", lambda url, timeout: urls.append(url) or FakeResp(200, self.RAW))
        assert "jinx" in cd.fetch_catalog("vi_VN")
        assert urls == ["https://raw.communitydragon.org/latest/cdragon/tft/vi_vn.json"]

    def test_missing_locale_falls_back_to_english(self, monkeypatch):
        urls = []

        def fake(url, timeout):
            urls.append(url)
            return FakeResp(404) if "fr_fr" in url else FakeResp(200, self.RAW)

        monkeypatch.setattr(cd.requests, "get", fake)
        assert "jinx" in cd.fetch_catalog("fr_FR")
        assert urls[-1].endswith("/en_us.json") and len(urls) == 2

    def test_server_error_raises(self, monkeypatch):
        monkeypatch.setattr(cd.requests, "get", lambda url, timeout: FakeResp(500))
        with pytest.raises(requests.HTTPError):
            cd.fetch_catalog("vi_VN")


# ----------------------------------------------------------------------------- tra cứu và chữ hiển thị
class TestFindDetail:
    CATALOG = cd.parse_catalog(raw_catalog(s18=[raw_champ("Kha'Zix"), raw_champ("Ngộ Không")]))

    def test_matches_by_name_ignoring_accents_and_quotes(self):
        assert cd.find_detail(self.CATALOG, {"name": "Khazix"})["name"] == "Kha'Zix"

    def test_falls_back_to_the_other_language_name(self):
        assert cd.find_detail(self.CATALOG, {"name": "Wukong", "alt_name": "Ngộ Không"})["name"] == "Ngộ Không"

    def test_unknown_or_no_data(self):
        assert cd.find_detail(self.CATALOG, {"name": "Không có", "alt_name": ""}) is None
        assert cd.find_detail(None, {"name": "Kha'Zix"}) is None
        assert cd.find_detail({}, {"name": "Kha'Zix"}) is None


class TestRoleLabel:
    @pytest.mark.parametrize("role,expected", [
        ("ADFighter", "Đấu sĩ (vật lý)"), ("APFighter", "Đấu sĩ (phép)"), ("ADReaper", "Sát thủ (vật lý)"),
        ("APReaper", "Sát thủ (phép)"), ("ADTank", "Đỡ đòn (vật lý)"), ("APTank", "Đỡ đòn (phép)"),
        ("ADCaster", "Xạ thủ (vật lý)"), ("ADCarry", "Xạ thủ (vật lý)"), ("APCaster", "Pháp sư (phép)"),
        ("APCasterHighMana", "Pháp sư (phép)"), ("APCarry", "Pháp sư (phép)"), ("ADSpecialist", "Chuyên biệt (vật lý)"),
        ("HCaster", "Chủ lực (hỗn hợp)"), ("TutorialADCarry", "Xạ thủ (vật lý)"), ("ADCarryCrit", "Xạ thủ (vật lý)"),
    ])
    def test_known_roles(self, role, expected):
        assert cd.role_label(role) == expected

    def test_unknown_or_empty_keeps_the_raw_text(self):
        assert cd.role_label("Lạ") == "Lạ" and cd.role_label("") == "" and cd.role_label(None) == ""


class TestStatRows:
    def test_full_stats_in_display_order(self):
        e = {"stats": {"hp": 650.0, "damage": 40.0, "armor": 35.0, "magicResist": 35.0, "attackSpeed": 0.7500000119, "range": 1.0,
                       "initialMana": 0.0, "mana": 40.0, "critChance": 0.25}}
        assert cd.stat_rows(e) == [("Máu", "650"), ("Sát thương", "40"), ("Giáp", "35"), ("Kháng phép", "35"), ("Tốc đánh", "0.75"),
                                   ("Tầm đánh", "1 ô"), ("Năng lượng", "0 / 40"), ("Chí mạng", "25%")]

    def test_missing_stats_are_skipped(self):
        assert cd.stat_rows({"stats": {"hp": 500.0, "range": 4.0}}) == [("Máu", "500"), ("Tầm đánh", "4 ô")]
        assert cd.stat_rows({}) == []

    def test_mana_without_initial_mana(self):
        assert cd.stat_rows({"stats": {"mana": 80}}) == [("Năng lượng", "0 / 80")]
