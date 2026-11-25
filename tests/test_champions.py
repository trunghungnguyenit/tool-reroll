import threading
import time
import types
from pathlib import Path

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
    Path(path).write_bytes(buf.tobytes())  # không dùng tofile: cần FILE* của CRT, hết chỗ khi cả bộ test chạy chung một tiến trình
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


class TestRunParallel:
    def test_runs_every_item_exactly_once_with_several_threads(self):
        lock = threading.Lock()
        seen, active, peak = [], 0, 0

        def fn(item):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
                seen.append(item)

        champions.run_parallel(list(range(20)), fn, workers=4)
        assert sorted(seen) == list(range(20))
        assert 1 < peak <= 4  # song song nhưng không vượt số luồng cho phép

    def test_takes_items_in_list_order(self):
        order = []
        champions.run_parallel(list(range(10)), order.append, workers=1)
        assert order == list(range(10))

    def test_an_exception_does_not_stop_the_other_items(self):
        done = []

        def fn(item):
            if item == 3:
                raise OSError("boom")
            done.append(item)

        champions.run_parallel(list(range(8)), fn, workers=3)
        assert sorted(done) == [0, 1, 2, 4, 5, 6, 7]

    def test_should_stop_ends_early(self):
        done = []
        champions.run_parallel(list(range(50)), done.append, workers=2, should_stop=lambda: len(done) >= 5)
        assert 5 <= len(done) < 50

    def test_empty_list_returns_immediately(self):
        champions.run_parallel([], lambda item: pytest.fail("không được gọi"))


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


class TestMergeChampions:
    """Mỗi TÊN một thẻ; thẻ ghi mọi mùa tướng có mặt; tutorial/sự kiện cũng được giữ (hiện ở Tất cả, không có mùa)."""

    def test_same_name_across_sets_is_one_card_with_all_its_seasons(self):
        graves = [c for c in champions.merge_champions(ENTRIES) if c["name"] == "Graves"]
        assert len(graves) == 1 and graves[0]["sets"] == [18, 17] and graves[0]["set"] == 18

    def test_card_takes_cost_and_art_from_the_newest_season(self):
        entries = [entry(sid("TFTSet16", "TFT16_Zed"), "Zed", 3), entry(sid("TFTSet18", "TFT18_Zed"), "Zed", 2)]
        (zed,) = champions.merge_champions(entries)
        assert zed["tier"] == 2 and zed["image_url"].endswith("TFT18_Zed.png")

    def test_trailing_space_and_case_do_not_split_a_champion(self):
        cards = champions.merge_champions([entry(sid("TFTSet18", "a"), "Graves"), entry(sid("TFTSet17", "b"), "graves ")])
        assert len(cards) == 1 and cards[0]["sets"] == [18, 17]

    def test_event_spelling_of_the_same_name_is_merged(self):
        """Bản sự kiện viết 'RekSai'/'Khazix' còn bản mùa viết "Rek'Sai"/"Kha'Zix": cùng một thẻ."""
        cards = champions.merge_champions([
            entry(sid("TFTSet18", "TFT18_RekSai"), "Rek'Sai", 1),
            entry(sid("TFTSetEvent5YR", "TFTEvent5YR_RekSai"), "RekSai", 1, set_no=None),
        ])
        assert [c["name"] for c in cards] == ["Rek'Sai"] and cards[0]["sets"] == [18]

    def test_champion_only_in_tutorial_has_no_season(self):
        darius = [c for c in champions.merge_champions(ENTRIES) if c["name"] == "Darius"]
        assert len(darius) == 1 and darius[0]["sets"] == [] and darius[0]["set"] is None

    def test_champions_only_in_tutorial_or_event_are_kept(self):
        names = {c["name"] for c in champions.merge_champions(ENTRIES)}
        assert {"Darius", "Galio"} <= names

    def test_a_set_entry_wins_over_a_tutorial_entry_of_the_same_name(self):
        entries = [entry(sid("TFTSetTutorial", "TFTTutorial_Zed"), "Zed", 2, set_no=None), entry(sid("TFTSet17", "TFT17_Zed"), "Zed", 2)]
        (zed,) = champions.merge_champions(entries)
        assert zed["sets"] == [17] and zed["image_url"].endswith("TFT17_Zed.png")

    def test_alt_name_is_kept_from_any_entry_that_has_it(self):
        entries = [entry(sid("TFTSet18", "a"), "Ngộ Không", 4), entry(sid("TFTSet17", "b"), "Ngộ Không", 4, "Wukong")]
        (card,) = champions.merge_champions(entries)
        assert card["alt_name"] == "Wukong"

    def test_result_is_sorted_by_tier_then_name(self):
        cards = champions.merge_champions(ENTRIES)
        assert [(c["tier"], c["name"]) for c in cards] == sorted((c["tier"], c["name"]) for c in cards)

    def test_entries_without_a_name_are_ignored_and_input_is_not_mutated(self):
        entries = [entry(sid("TFTSet18", "a"), "  ", 1), entry(sid("TFTSet18", "b"), "Vex", 1)]
        before = [dict(e) for e in entries]
        assert [c["name"] for c in champions.merge_champions(entries)] == ["Vex"]
        assert entries == before

    def test_empty_input(self):
        assert champions.merge_champions([]) == []
        assert champions.available_seasons([]) == [] and champions.visible_champions([], set()) == []


class TestSeasons:
    CARDS = champions.merge_champions(ENTRIES)

    def names(self, seasons):
        return {c["name"] for c in champions.visible_champions(self.CARDS, set(seasons))}

    def test_all_seasons_is_the_default_and_includes_event_only_champions(self):
        assert self.names(set()) == {"Graves", "Ngộ Không", "Zed", "Darius", "Galio"}

    def test_one_season(self):
        assert self.names({17}) == {"Graves", "Zed"} and self.names({18}) == {"Graves", "Ngộ Không"}

    def test_several_seasons_are_a_union(self):
        assert self.names({17, 18}) == {"Graves", "Ngộ Không", "Zed"}

    def test_event_only_champions_hide_once_a_season_is_chosen(self):
        assert not self.names({18}) & {"Darius", "Galio"}

    def test_unknown_season_shows_nothing(self):
        assert self.names({3}) == set()

    def test_available_seasons_newest_first(self):
        assert champions.available_seasons(self.CARDS) == [18, 17]

    def test_labels_are_compact(self):
        card = lambda sets: {"sets": sets}  # noqa: E731
        assert champions.season_label(card([18])) == "M18"
        assert champions.season_label(card([18, 17])) == "M18 · M17"
        assert champions.season_label(card([18, 17, 16, 15])) == "M18 · M17 +2"
        assert champions.season_label(card([])) == "Sự kiện"
        assert champions.season_tooltip(card([18, 15])) == "mùa 18, 15" and "tutorial" in champions.season_tooltip(card([]))


class TestSearch:
    CARDS = champions.merge_champions([
        entry(sid("TFTSet18", "k"), "Kha'Zix", 3, "Khazix"), entry(sid("TFTSet17", "n"), "Ngộ Không", 4, "Wukong"),
        entry(sid("TFTSet16", "c"), "Cát Tường", 2, "Fortune"), entry(sid("TFTSet15", "v"), "Vi", 3), entry(sid("TFTSet15", "w"), "Viego", 5),
        entry(sid("TFTSet15", "t"), "Twisted Fate", 2),
    ])

    def found(self, query):
        return sorted(c["name"] for c in self.CARDS if champions.matches_query(c, query))

    def test_ignores_apostrophes_spaces_case_and_accents(self):
        assert self.found("khazix") == ["Kha'Zix"] and self.found("KHA ZIX") == ["Kha'Zix"] and self.found("kha'zix") == ["Kha'Zix"]
        assert self.found("ngo khong") == ["Ngộ Không"] and self.found("NGỘ") == ["Ngộ Không"]
        assert self.found("twistedfate") == ["Twisted Fate"] and self.found("twisted  fate") == ["Twisted Fate"]

    def test_matches_the_other_language_name(self):
        assert self.found("wukong") == ["Ngộ Không"] and self.found("fortune") == ["Cát Tường"]

    def test_matches_any_substring_not_just_the_start(self):
        assert self.found("ie") == ["Viego"] and self.found("vi") == ["Vi", "Viego"]
        assert "Kha'Zix" in self.found("zix") and "Cát Tường" in self.found("tuong")

    def test_one_character_finds_every_card_containing_it(self):
        assert self.found("a") == ["Cát Tường", "Kha'Zix", "Twisted Fate"]

    def test_empty_or_symbol_only_query_matches_everything(self):
        assert len(self.found("")) == len(self.CARDS) == len(self.found("   ")) == len(self.found("'-'"))

    def test_no_match(self):
        assert self.found("zzz") == []

    def test_works_on_a_card_without_precomputed_keys(self):
        assert champions.matches_query({"name": "Kha'Zix", "alt_name": ""}, "khazix")


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
    CHAMPS = champions.merge_champions(
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
    """Giả requests.get cho versions.json và tft-champion.json (hai ngôn ngữ) của nhiều patch.

    patches: {version: {id: (tên en, tên vi, tier)}}. missing: các patch trả HTTP 403 (không có dữ liệu). down: các patch lỗi mạng."""

    def __init__(self, patches=None, missing=(), down=(), fail_locale=None, offline=False):
        self.urls, self.fail_locale, self.offline = [], fail_locale, offline
        self.missing, self.down = set(missing), set(down)
        self.patches = patches if patches is not None else {
            "16.23.1": {sid("TFTSet18", "TFT18_Wukong"): ("Wukong", "Ngộ Không", 4),
                        sid("TFTSet18", "TFT18_Zed"): ("Zed", "Zed", 5),
                        sid("TFTSetTutorial", "TFTTutorial_Darius"): ("Darius", "Darius", 2),
                        sid("TFTSet18", "TFT18_NoTier"): ("Hidden", "Hidden", None)},
            "15.24.1": {sid("TFTSet15", "TFT15_Wukong"): ("Wukong ", "Ngộ Không ", 3),
                        sid("TFTSet7", "TFT7_Garen"): ("Garen", "Garen", 1)},
            "14.24.1": {sid("TFTSet12", "TFT12_Ahri"): ("Ahri", "Ahri", 4)},
        }

    def fetched(self, version):
        return [u for u in self.urls if f"/cdn/{version}/" in u]

    def __call__(self, url, timeout):
        self.urls.append(url)
        if self.offline:
            raise requests.ConnectionError("offline")
        if url.endswith("versions.json"):
            return FakeResponse(json_data=[*self.patches, "12.23.1", "lolpatch_3.7"])
        version = url.split("/cdn/")[1].split("/")[0]
        locale = url.split("/data/")[1].split("/")[0]
        if version in self.down or locale == self.fail_locale:
            raise requests.ConnectionError("down")
        if version in self.missing or version not in self.patches:
            return FakeResponse(error=requests.HTTPError("403", response=types.SimpleNamespace(status_code=403)))
        index = 0 if locale == "en_US" else 1
        data = {k: {"name": v[index], "tier": v[2], "image": {"full": k.split("/")[-1] + ".png"}}
                for k, v in self.patches[version].items()}
        return FakeResponse(json_data={"data": data})


@pytest.fixture
def ddragon(monkeypatch):
    def install(**kw):
        fake = FakeDdragon(**kw)
        monkeypatch.setattr(champions.requests, "get", fake)
        return fake

    return install


class TestVersions:
    def test_only_tft_capable_patches_newest_first(self, ddragon):
        ddragon(patches={"14.24.1": {}, "16.23.1": {}, "13.2.1": {}})
        assert champions.tft_versions() == ["16.23.1", "14.24.1", "13.2.1"]  # bỏ 12.23.1 (HTTP 403) và 'lolpatch_3.7'

    def test_numeric_not_text_ordering(self, ddragon):
        ddragon(patches={"15.9.1": {}, "15.10.1": {}, "15.2.1": {}})
        assert champions.tft_versions() == ["15.10.1", "15.9.1", "15.2.1"]


class TestFetchVersion:
    def test_fetches_both_locales_and_fills_each_name(self, ddragon):
        fake = ddragon()
        data = champions.fetch_version("16.23.1")
        assert any("/vi_VN/" in u for u in fake.urls) and any("/en_US/" in u for u in fake.urls)
        wk = data[sid("TFTSet18", "TFT18_Wukong")]
        assert wk["names"] == {"vi_VN": "Ngộ Không", "en_US": "Wukong"} and wk["set"] == 18 and wk["tier"] == 4
        assert wk["image"] == "TFT18_Wukong.png"

    def test_names_are_stripped_and_untiered_entries_skipped(self, ddragon):
        ddragon()
        data = champions.fetch_version("15.24.1")
        assert data[sid("TFTSet15", "TFT15_Wukong")]["names"] == {"vi_VN": "Ngộ Không", "en_US": "Wukong"}
        assert sid("TFTSet18", "TFT18_NoTier") not in champions.fetch_version("16.23.1")

    def test_tutorial_entries_have_no_season(self, ddragon):
        ddragon()
        assert champions.fetch_version("16.23.1")[sid("TFTSetTutorial", "TFTTutorial_Darius")]["set"] is None

    def test_http_403_means_the_patch_has_no_data(self, ddragon):
        ddragon(missing={"14.24.1"})
        assert champions.fetch_version("14.24.1") == {}

    def test_other_http_errors_raise(self, monkeypatch):
        monkeypatch.setattr(champions.requests, "get", lambda url, timeout: FakeResponse(
            error=requests.HTTPError("500", response=types.SimpleNamespace(status_code=500))))
        with pytest.raises(requests.HTTPError):
            champions.fetch_version("16.23.1")

    @pytest.mark.parametrize("locale", ["vi_VN", "en_US"])
    def test_one_locale_failing_raises_instead_of_recording_half_a_patch(self, ddragon, locale):
        ddragon(fail_locale=locale)
        with pytest.raises(requests.ConnectionError):
            champions.fetch_version("16.23.1")


class TestCatalog:
    def test_newer_patch_wins_whatever_the_merge_order(self):
        old = {"A": {"names": {"vi_VN": "Cũ", "en_US": "Old"}, "tier": 1, "set": 15, "image": "old.png"}}
        new = {"A": {"names": {"vi_VN": "Mới", "en_US": "New"}, "tier": 2, "set": 15, "image": "new.png"}}
        for order in ((("15.2.1", old), ("16.1.1", new)), (("16.1.1", new), ("15.2.1", old))):
            cat = champions.new_catalog()
            for v, d in order:
                champions.merge_version(cat, v, d)
            assert cat["champions"]["A"]["image"] == "new.png" and cat["champions"]["A"]["version"] == "16.1.1"
            assert sorted(cat["versions"]) == ["15.2.1", "16.1.1"]

    def test_older_patch_only_adds_champions_the_newer_one_lacks(self):
        cat = champions.new_catalog()
        champions.merge_version(cat, "16.1.1", {"A": {"names": {"vi_VN": "a", "en_US": "a"}, "tier": 1, "set": 18, "image": "a.png"}})
        champions.merge_version(cat, "14.1.1", {"B": {"names": {"vi_VN": "b", "en_US": "b"}, "tier": 1, "set": 12, "image": "b.png"}})
        assert set(cat["champions"]) == {"A", "B"} and cat["champions"]["B"]["version"] == "14.1.1"

    def test_entries_use_the_locale_and_the_patch_each_champion_was_found_in(self):
        cat = champions.new_catalog()
        champions.merge_version(cat, "14.24.1", {"X": {"names": {"vi_VN": "Ngộ Không", "en_US": "Wukong"}, "tier": 4, "set": 12, "image": "x.png"}})
        (vi,) = champions.catalog_entries(cat, "vi_VN")
        (en,) = champions.catalog_entries(cat, "en_US")
        assert (vi["name"], vi["alt_name"]) == ("Ngộ Không", "Wukong") and (en["name"], en["alt_name"]) == ("Wukong", "Ngộ Không")
        assert vi["image_url"].endswith("/cdn/14.24.1/img/tft-champion/x.png") and vi["set"] == 12

    def test_same_name_in_both_languages_has_no_alias(self):
        cat = champions.new_catalog()
        champions.merge_version(cat, "16.1.1", {"X": {"names": {"vi_VN": "Zed", "en_US": "Zed"}, "tier": 4, "set": 18, "image": "x.png"}})
        assert champions.catalog_entries(cat, "vi_VN")[0]["alt_name"] == ""

    def test_invalid_locale_falls_back_to_default(self):
        cat = champions.new_catalog()
        champions.merge_version(cat, "16.1.1", {"X": {"names": {"vi_VN": "Ngộ Không", "en_US": "Wukong"}, "tier": 4, "set": 18, "image": "x.png"}})
        assert champions.catalog_entries(cat, "../../evil")[0]["name"] == "Ngộ Không"

    def sample(self):
        cat = champions.new_catalog()
        champions.merge_version(cat, "16.1.1", {"A": {"names": {"vi_VN": "a", "en_US": "A"}, "tier": 1, "set": 18, "image": "a.png"}})
        return cat

    def test_roundtrip(self, data_dir):
        champions.save_catalog(self.sample())
        loaded = champions.load_catalog()
        assert loaded["champions"] == self.sample()["champions"] and loaded["versions"] == ["16.1.1"]
        assert not list(data_dir.glob("*.tmp"))

    def test_missing_catalog(self, data_dir):
        assert champions.load_catalog() is None

    @pytest.mark.parametrize("content", ["", "{", "[]", "null", '{"schema": 1}', '{"schema": 99, "versions": [], "champions": {"a": 1}}',
                                         '{"schema": 1, "versions": [], "champions": {}}',
                                         '{"schema": 1, "versions": ["x"], "champions": {"a": {}}}',
                                         '{"schema": 1, "versions": [], "champions": {"a": {"names": {"vi_VN": 1, "en_US": "a"}, "tier": 1, "set": 1, "image": "i", "version": "1.2.3"}}}',
                                         '{"schema": 1, "versions": [], "champions": {"a": {"names": {"vi_VN": "a", "en_US": "a"}, "tier": "1", "set": 1, "image": "i", "version": "1.2.3"}}}'])
    def test_corrupt_or_invalid_catalog_returns_none(self, data_dir, content):
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / champions.CATALOG_NAME).write_text(content, encoding="utf-8")
        assert champions.load_catalog() is None

    def test_catalog_with_bom_is_readable(self, data_dir):
        champions.save_catalog(self.sample())
        path = data_dir / champions.CATALOG_NAME
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        assert champions.load_catalog() is not None

    def test_failed_write_keeps_the_previous_catalog(self, data_dir, monkeypatch):
        champions.save_catalog(self.sample())
        monkeypatch.setattr(champions.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("khóa")))
        with pytest.raises(OSError):
            champions.save_catalog({**self.sample(), "versions": ["9.9.9"]})
        assert champions.load_catalog()["versions"] == ["16.1.1"]


class Loader:
    """Chạy load_all_champions và ghi lại các lần on_update / on_progress."""

    def __init__(self, locale="vi_VN", **kw):
        self.updates, self.progress = [], []
        self.report = champions.load_all_champions(locale, lambda e: self.updates.append(e), on_progress=lambda d, n: self.progress.append((d, n)), **kw)

    def names(self, i=-1):
        return sorted({e["name"] for e in self.updates[i]})


class TestLoadAllChampions:
    def test_first_run_scans_every_patch_and_reports_progressively(self, data_dir, ddragon):
        fake = ddragon()
        run = Loader()
        assert run.report.versions_total == 3 and run.report.versions_new == 3 and not run.report.failed and not run.report.offline
        assert len(run.updates) == 2  # sau patch mới nhất, rồi sau khi quét xong các patch cũ
        assert "Garen" not in run.names(0) and "Ahri" not in run.names(0)  # lúc đầu mới có mùa của patch mới nhất
        assert {"Ahri", "Garen", "Ngộ Không", "Zed", "Darius"} <= set(run.names(-1))  # cuối cùng đủ mọi mùa, kể cả tutorial
        assert run.progress[-1] == (2, 2) and all(fake.fetched(v) for v in ("16.23.1", "15.24.1", "14.24.1"))
        assert not any("12.23.1" in u or "evil" in u for u in fake.urls)

    def test_both_locales_are_fetched_for_every_patch(self, data_dir, ddragon):
        fake = ddragon()
        Loader()
        for v in ("16.23.1", "15.24.1", "14.24.1"):
            assert len([u for u in fake.fetched(v) if "/vi_VN/" in u]) == 1 and len([u for u in fake.fetched(v) if "/en_US/" in u]) == 1

    def test_every_season_comes_through_to_cards(self, data_dir, ddragon):
        ddragon()
        cards = champions.merge_champions(Loader().updates[-1])
        assert champions.available_seasons(cards) == [18, 15, 12, 7]
        wk = [c for c in cards if c["name"] == "Ngộ Không"][0]
        assert wk["sets"] == [18, 15] and wk["alt_name"] == "Wukong" and wk["tier"] == 4  # cost/ảnh của mùa mới nhất

    def test_second_run_uses_the_cache_and_downloads_nothing_new(self, data_dir, ddragon):
        ddragon()
        Loader()
        fake = ddragon()
        run = Loader()
        assert run.report.versions_new == 0 and fake.urls == [fake.urls[0]] and fake.urls[0].endswith("versions.json")
        assert len(run.updates) == 1 and "Ahri" in run.names()

    def test_a_new_patch_downloads_only_that_patch(self, data_dir, ddragon):
        ddragon()
        Loader()
        patches = {"16.24.1": {sid("TFTSet18", "TFT18_Zed"): ("Zed", "Zed", 3)}, **FakeDdragon().patches}
        fake = ddragon(patches=patches)
        run = Loader()
        assert run.report.versions_new == 1 and fake.fetched("16.24.1") and not fake.fetched("15.24.1")
        zed = [e for e in run.updates[-1] if e["id"].endswith("TFT18_Zed")][0]
        assert zed["tier"] == 3 and "/16.24.1/" in zed["image_url"]  # patch mới ghi đè bản cũ

    def test_cached_list_is_shown_first_even_when_offline(self, data_dir, ddragon):
        ddragon()
        Loader()
        ddragon(offline=True)
        run = Loader()
        assert run.report.offline and len(run.updates) == 1 and "Ahri" in run.names()

    def test_offline_without_cache_raises(self, data_dir, ddragon):
        ddragon(offline=True)
        with pytest.raises(requests.ConnectionError):
            Loader()

    def test_failure_of_the_newest_patch_with_cache_falls_back_to_cache(self, data_dir, ddragon):
        ddragon()
        Loader()
        patches = {"16.24.1": {}, **FakeDdragon().patches}
        ddragon(patches=patches, down={"16.24.1"})
        run = Loader()
        assert run.report.offline and "Ahri" in run.names()

    def test_old_patch_network_failure_is_reported_and_retried_next_time(self, data_dir, ddragon):
        ddragon(down={"15.24.1"})
        run = Loader()
        assert run.report.failed == ["15.24.1"] and "Garen" not in run.names() and "Ahri" in run.names()
        fake = ddragon()
        again = Loader()
        assert again.report.versions_new == 1 and fake.fetched("15.24.1") and not fake.fetched("14.24.1") and "Garen" in again.names()

    def test_patch_with_no_data_is_recorded_so_it_is_not_requested_again(self, data_dir, ddragon):
        ddragon(missing={"14.24.1"})
        Loader()
        fake = ddragon(missing={"14.24.1"})
        Loader()
        assert not fake.fetched("14.24.1") and "14.24.1" in champions.load_catalog()["versions"]

    def test_stop_request_ends_the_scan_without_losing_what_is_loaded(self, data_dir, ddragon):
        ddragon()
        stop, updates = {"now": False}, []

        def on_update(entries):
            updates.append(entries)
            stop["now"] = True  # người dùng đóng app ngay sau khi có patch mới nhất

        report = champions.load_all_champions("vi_VN", on_update, should_stop=lambda: stop["now"])
        assert len(updates) == 1 and report.versions_new == 1 and "Ahri" not in {e["name"] for e in updates[0]}
        assert champions.load_catalog()["versions"] == ["16.23.1"]

    def test_invalid_locale_does_not_reach_odd_urls(self, data_dir, ddragon):
        fake = ddragon()
        Loader("../../evil")
        assert all("evil" not in u for u in fake.urls)

    def test_en_us_locale_shows_english_names_first(self, data_dir, ddragon):
        ddragon()
        run = Loader("en_US")
        wk = [e for e in run.updates[-1] if e["id"].endswith("TFT18_Wukong")][0]
        assert (wk["name"], wk["alt_name"]) == ("Wukong", "Ngộ Không")

    def test_corrupt_catalog_is_rebuilt_from_the_network(self, data_dir, ddragon):
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / champions.CATALOG_NAME).write_text("{hỏng", encoding="utf-8")
        ddragon()
        run = Loader()
        assert run.report.versions_new == 3 and "Ahri" in run.names()

    def test_reference_names_cover_every_season_and_both_languages(self, data_dir, ddragon):
        ddragon()
        names = champions.reference_names(Loader().updates[-1])
        assert {"Ngộ Không", "Wukong", "Garen", "Ahri", "Darius"} <= set(names)

    def test_catalog_is_saved_incrementally_during_a_long_scan(self, data_dir, ddragon, monkeypatch):
        many = {f"15.{i}.1": {sid("TFTSet15", f"TFT15_C{i}"): (f"C{i}", f"C{i}", 1)} for i in range(1, 26)}
        ddragon(patches={"16.1.1": {sid("TFTSet18", "TFT18_X"): ("X", "X", 1)}, **many})
        saves = []
        real = champions.save_catalog
        monkeypatch.setattr(champions, "save_catalog", lambda cat: (saves.append(len(cat["versions"])), real(cat))[1])
        Loader()
        assert len(saves) >= 4 and saves[-1] == 26


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
