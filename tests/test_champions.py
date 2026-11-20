import cv2
import numpy as np
import pytest
import requests

import core.champions as champions
from tests.helpers import make_card


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Tryndamere ", "Tryndamere"),  # Data Dragon có tên thừa khoảng trắng cuối
        ("Bel'Veth", "Bel'Veth"),
        ("a/b:c", "a_b_c"),
        ("  ..x.. ", "x"),
        ("", "champion"),
        ("..", "champion"),
    ],
)
def test_safe_filename(name, expected):
    assert champions.safe_filename(name) == expected


def write_image(path, ext=".jpg", seed=1):
    ok, buf = cv2.imencode(ext, make_card(seed))
    assert ok
    buf.tofile(str(path))
    return path


def test_save_custom_template_converts_to_real_png(data_dir, tmp_path):
    src = write_image(tmp_path / "portrait.jpg", ".jpg")
    dest = champions.save_custom_template(str(src), "Tryndamere ")
    assert dest.name == "custom_Tryndamere.png"
    assert dest.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert champions.load_template_image(dest) is not None


def test_save_custom_template_rejects_non_image(data_dir, tmp_path):
    bad = tmp_path / "notes.png"
    bad.write_text("đây không phải ảnh", encoding="utf-8")
    with pytest.raises(ValueError):
        champions.save_custom_template(str(bad), "Vex")
    assert not list((data_dir / "templates").glob("custom_*"))


def test_save_custom_template_rejects_missing_and_empty_file(data_dir, tmp_path):
    with pytest.raises(ValueError):
        champions.save_custom_template(str(tmp_path / "nope.png"), "Vex")
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    with pytest.raises(ValueError):
        champions.save_custom_template(str(empty), "Vex")


def test_load_template_image_handles_non_ascii_path(tmp_path):
    folder = tmp_path / "Nguyễn Văn Á"
    folder.mkdir()
    img_path = write_image(folder / "tướng.png", ".png")
    img = champions.load_template_image(img_path)
    assert img is not None and img.shape[2] == 3


class FakeResponse:
    def __init__(self, content=b"", error=None, json_data=None):
        self.content, self._error, self._json = content, error, json_data

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._json


def test_download_template_writes_once_and_caches(data_dir, monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse(b"PNGDATA")

    monkeypatch.setattr(champions.requests, "get", fake_get)
    first = champions.download_template("Vex", "http://x/img/tft-champion/TFT18_Vex.png")
    second = champions.download_template("Vex", "http://x/img/tft-champion/TFT18_Vex.png")
    assert first == second and first.read_bytes() == b"PNGDATA"
    assert first.name == "Vex__TFT18_Vex.png"
    assert len(calls) == 1  # lần 2 dùng cache
    assert not list((data_dir / "templates").glob("*.part"))


def test_download_template_failure_returns_none_and_leaves_no_file(data_dir, monkeypatch):
    def fake_get(url, timeout):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(champions.requests, "get", fake_get)
    assert champions.download_template("Vex", "http://x/vex.png") is None
    assert not list((data_dir / "templates").glob("*"))


def test_prepare_shop_template_is_square_crop():
    img = np.zeros((100, 160, 3), dtype=np.uint8)
    assert champions.prepare_shop_template(img, size=64).shape == (64, 64, 3)



def entry(cid, name, tier=1, alt="", set_no="auto"):
    """Mục Data Dragon giả. cid dạng 'Maps/Shipping/Map22/Sets/TFTSet18/Shop/TFT18_Vex'."""
    return {
        "id": cid,
        "name": name,
        "alt_name": alt,
        "tier": tier,
        "set": champions.set_of(cid) if set_no == "auto" else set_no,
        "image_url": f"http://x/img/tft-champion/{cid.split('/')[-1]}.png",
    }


def sid(set_name, unit):
    return f"Maps/Shipping/Map22/Sets/{set_name}/Shop/{unit}"


ENTRIES = [
    entry(sid("TFTSet18", "TFT18_Graves"), "Graves", 1, "Graves"),
    entry(sid("TFTSet17", "TFT17_Graves"), "Graves ", 1),  # cùng tên (thừa dấu cách) ở mùa cũ
    entry(sid("TFTSet18", "TFT18_Wukong"), "Ngộ Không", 4, "Wukong"),
    entry(sid("TFTSet17", "TFT17_Zed"), "Zed", 2),  # chỉ có ở mùa cũ
    entry(sid("TFTSetTutorial", "TFTTutorial_Darius"), "Darius", 2),
    entry(sid("TFTSetEvent5YR", "TFTEvent5YR_Galio"), "Galio", 4),
]


class TestSetParsing:
    @pytest.mark.parametrize(
        "cid,expected",
        [
            (sid("TFTSet18", "TFT18_Vex"), 18),
            (sid("TFTSet5", "x"), 5),
            (sid("TFTSetTutorial", "TFTTutorial_Darius"), None),
            (sid("TFTSetEvent5YR", "TFTEvent5YR_Galio"), None),
            ("TFT_Champion_Vex", None),
        ],
    )
    def test_set_of(self, cid, expected):
        assert champions.set_of(cid) == expected


class TestPlayableAndVisible:
    def test_tutorial_and_event_entries_are_dropped(self):
        names = {c["name"].strip() for c in champions.playable_champions(ENTRIES)}
        assert "Darius" not in names and "Galio" not in names

    def test_same_name_across_sets_keeps_newest_set_and_ignores_trailing_space(self):
        graves = [c for c in champions.playable_champions(ENTRIES) if c["name"].strip() == "Graves"]
        assert len(graves) == 1
        assert graves[0]["set"] == 18 and graves[0]["image_url"].endswith("TFT18_Graves.png")

    def test_result_is_sorted_by_tier_then_name(self):
        champs = champions.playable_champions(ENTRIES)
        assert [(c["tier"], c["name"]) for c in champs] == sorted((c["tier"], c["name"]) for c in champs)

    def test_latest_set_and_visibility(self):
        champs = champions.playable_champions(ENTRIES)
        assert champions.latest_set(champs) == 18
        assert {c["name"] for c in champions.visible_champions(champs, show_old=False)} == {"Graves", "Ngộ Không"}
        assert {c["name"] for c in champions.visible_champions(champs, show_old=True)} == {"Graves", "Ngộ Không", "Zed"}

    def test_empty_input(self):
        assert champions.playable_champions([]) == []
        assert champions.latest_set([]) is None
        assert champions.visible_champions([], show_old=False) == []


class TestAliases:
    def test_reference_names_cover_both_languages_and_every_set(self):
        assert champions.reference_names(ENTRIES) == sorted(
            ["Graves", "Ngộ Không", "Wukong", "Zed", "Darius", "Galio"]
        )

    def test_alias_groups_only_for_entries_with_alt_name(self):
        assert champions.alias_groups(ENTRIES) == [["Ngộ Không", "Wukong"]]

    def test_aliases_for_targets_work_in_either_direction_and_ignore_accents_and_spaces(self):
        groups = [["Ngộ Không", "Wukong"]]
        assert champions.aliases_for_targets(["Ngộ Không"], groups) == {"Ngộ Không": ["Wukong"]}
        assert champions.aliases_for_targets(["Wukong"], groups) == {"Wukong": ["Ngộ Không"]}
        assert champions.aliases_for_targets(["ngo khong "], groups) == {"ngo khong ": ["Wukong"]}
        assert champions.aliases_for_targets(["Vex"], groups) == {}


class TestSelectionRestore:
    CHAMPS = champions.playable_champions(
        [
            entry(sid("TFTSet18", "a"), "Graves", 1),
            entry(sid("TFTSet18", "b"), "Ngộ Không", 4, "Wukong"),
            entry(sid("TFTSet18", "c"), "Vex", 2),
        ]
    )

    def ticked(self, saved):
        keys = champions.selection_keys(saved)
        return sorted(c["name"] for c in self.CHAMPS if champions.is_selected(c, keys))

    def test_exact_names(self):
        assert self.ticked(["Vex", "Graves"]) == ["Graves", "Vex"]

    def test_saved_name_with_trailing_space_still_ticks(self):
        """Config cũ lưu 'Graves ' (Data Dragon từng trả tên thừa dấu cách) vẫn khôi phục đúng."""
        assert self.ticked(["Graves "]) == ["Graves"]

    def test_saved_in_other_language_ticks_same_champion(self):
        """Đổi ngôn ngữ danh sách (hoặc chọn 'Wukong') vẫn tick 'Ngộ Không'."""
        assert self.ticked(["Wukong"]) == ["Ngộ Không"]

    def test_case_and_accents_are_ignored(self):
        assert self.ticked(["ngo khong", "VEX"]) == ["Ngộ Không", "Vex"]

    def test_unknown_and_junk_are_ignored(self):
        assert self.ticked(["Yasuo", "", "   ", None, 5]) == []
        assert champions.selection_keys([]) == set()

    def test_does_not_tick_by_substring(self):
        assert self.ticked(["Grave"]) == []


class TestLocale:
    @pytest.mark.parametrize("value,expected", [("en_US", "en_US"), ("vi_VN", "vi_VN"), ("xx", "vi_VN"), (None, "vi_VN"), ("../x", "vi_VN"), ("vi_vn", "vi_VN")])
    def test_normalize_locale(self, value, expected):
        assert champions.normalize_locale(value) == expected

    def test_other_locale(self):
        assert champions.other_locale("vi_VN") == "en_US"
        assert champions.other_locale("en_US") == "vi_VN"


class FakeDdragon:
    """Giả requests.get cho versions.json và tft-champion.json của hai ngôn ngữ."""

    def __init__(self, fail_locale=None):
        self.urls, self.fail_locale = [], fail_locale
        base = {
            sid("TFTSet18", "TFT18_Wukong"): ("Wukong", "Ngộ Không", 4),
            sid("TFTSet17", "TFT17_Wukong"): ("Wukong ", "Ngộ Không ", 4),
            sid("TFTSetTutorial", "TFTTutorial_Darius"): ("Darius", "Darius", 2),
            sid("TFTSet18", "TFT18_NoTier"): ("Hidden", "Hidden", None),
        }
        self.data = {
            "en_US": {k: {"name": v[0], "tier": v[2], "image": {"full": k.split("/")[-1] + ".png"}} for k, v in base.items()},
            "vi_VN": {k: {"name": v[1], "tier": v[2], "image": {"full": k.split("/")[-1] + ".png"}} for k, v in base.items()},
        }

    def __call__(self, url, timeout):
        self.urls.append(url)
        if url.endswith("versions.json"):
            return FakeResponse(json_data=["16.23.1", "16.22.1", "lolpatch_3.7"])
        locale = url.split("/data/")[1].split("/")[0]
        if locale == self.fail_locale:
            raise requests.ConnectionError("down")
        return FakeResponse(json_data={"data": self.data[locale]})


class TestFetch:
    def test_fetches_both_locales_and_fills_entries(self, monkeypatch):
        fake = FakeDdragon()
        monkeypatch.setattr(champions.requests, "get", fake)
        entries = champions.fetch_champion_list("vi_VN")
        assert any("/vi_VN/" in u for u in fake.urls) and any("/en_US/" in u for u in fake.urls)
        wk = {e["id"].split("/")[-1]: e for e in entries}["TFT18_Wukong"]
        assert wk["name"] == "Ngộ Không" and wk["alt_name"] == "Wukong" and wk["set"] == 18 and wk["tier"] == 4
        assert wk["image_url"].endswith("/16.23.1/img/tft-champion/TFT18_Wukong.png")

    def test_names_are_stripped_and_untiered_entries_skipped(self, monkeypatch):
        monkeypatch.setattr(champions.requests, "get", FakeDdragon())
        names = [e["name"] for e in champions.fetch_champion_list("vi_VN")]
        assert "Ngộ Không " not in names and "Hidden" not in names

    def test_same_name_in_both_locales_has_no_alias(self, monkeypatch):
        monkeypatch.setattr(champions.requests, "get", FakeDdragon())
        darius = [e for e in champions.fetch_champion_list("vi_VN") if e["name"] == "Darius"][0]
        assert darius["alt_name"] == ""

    def test_alt_locale_failure_still_returns_list_without_aliases(self, monkeypatch):
        monkeypatch.setattr(champions.requests, "get", FakeDdragon(fail_locale="en_US"))
        entries = champions.fetch_champion_list("vi_VN")
        assert entries and all(e["alt_name"] == "" for e in entries)

    def test_main_locale_failure_raises(self, monkeypatch):
        monkeypatch.setattr(champions.requests, "get", FakeDdragon(fail_locale="vi_VN"))
        with pytest.raises(requests.ConnectionError):
            champions.fetch_champion_list("vi_VN")

    def test_invalid_locale_falls_back_to_default_without_calling_odd_urls(self, monkeypatch):
        fake = FakeDdragon()
        monkeypatch.setattr(champions.requests, "get", fake)
        champions.fetch_champion_list("../../evil")
        assert all("evil" not in u for u in fake.urls)

    def test_end_to_end_pipeline_shows_only_newest_set(self, monkeypatch):
        monkeypatch.setattr(champions.requests, "get", FakeDdragon())
        champs = champions.playable_champions(champions.fetch_champion_list("vi_VN"))
        assert [c["name"] for c in champs] == ["Ngộ Không"] and champs[0]["set"] == 18


class TestTemplateCacheNaming:
    def test_different_set_art_gets_different_cache_file(self, data_dir, monkeypatch):
        monkeypatch.setattr(champions.requests, "get", lambda url, timeout: FakeResponse(b"X" + url.encode()))
        old = champions.download_template("Aatrox", "http://x/img/tft-champion/TFT17_Aatrox.png")
        new = champions.download_template("Aatrox", "http://x/img/tft-champion/TFT18_Aatrox.png")
        assert old != new and old.read_bytes() != new.read_bytes()

    def test_trailing_space_in_name_does_not_change_file_name(self, data_dir, monkeypatch):
        monkeypatch.setattr(champions.requests, "get", lambda url, timeout: FakeResponse(b"X"))
        a = champions.download_template("Graves ", "http://x/img/tft-champion/TFT18_Graves.png")
        b = champions.download_template("Graves", "http://x/img/tft-champion/TFT18_Graves.png")
        assert a == b


class TestChampionCache:
    def test_roundtrip_has_names_and_alias_groups(self, data_dir):
        champions.save_champion_cache(ENTRIES)
        names, groups = champions.load_champion_cache()
        assert names == ["Darius", "Galio", "Graves", "Ngộ Không", "Wukong", "Zed"]
        assert groups == [["Ngộ Không", "Wukong"]]
        assert not list(data_dir.glob("*.tmp"))

    def test_missing_cache_returns_none(self, data_dir):
        assert champions.load_champion_cache() is None

    @pytest.mark.parametrize(
        "content",
        ["", "{not json", "[]", '{"names": "Vex"}', '{"names": []}', '{"x": 1}', '{"names": ["Vex"], "groups": "ab"}'],
    )
    def test_corrupt_or_empty_cache_returns_none(self, data_dir, content):
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / champions.CHAMPION_CACHE_NAME).write_text(content, encoding="utf-8")
        assert champions.load_champion_cache() is None

    def test_old_cache_without_groups_still_loads(self, data_dir):
        """Bản cache cũ (chỉ có names) vẫn đọc được, không có alias."""
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / champions.CHAMPION_CACHE_NAME).write_text('{"names": ["Vex", "Zed"]}', encoding="utf-8")
        assert champions.load_champion_cache() == (["Vex", "Zed"], [])

    def test_malformed_groups_are_dropped(self, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / champions.CHAMPION_CACHE_NAME).write_text(
            '{"names": ["Vex"], "groups": [["A", "B"], ["solo"], "str", [1, 2], ["C", "D", "E"]]}', encoding="utf-8"
        )
        assert champions.load_champion_cache() == (["Vex"], [["A", "B"], ["C", "D", "E"]])

    def test_cache_with_bom_is_readable(self, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        content = "﻿" + '{"names": ["Vex"]}'  # file lưu từ Notepad kiểu UTF-8 with BOM
        (data_dir / champions.CHAMPION_CACHE_NAME).write_bytes(content.encode("utf-8"))
        assert champions.load_champion_cache() == (["Vex"], [])

    def test_failed_write_keeps_previous_cache(self, data_dir, monkeypatch):
        champions.save_champion_cache(ENTRIES)

        def boom(src, dst):
            raise OSError("đĩa đầy")

        monkeypatch.setattr(champions.os, "replace", boom)
        with pytest.raises(OSError):
            champions.save_champion_cache([entry(sid("TFTSet18", "TFT18_Zed"), "Zed")])
        assert champions.load_champion_cache()[0][0] == "Darius"
