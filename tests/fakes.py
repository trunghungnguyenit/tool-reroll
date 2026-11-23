"""Bản giả dùng chung cho test điều phối/giao diện (không phụ thuộc Tk hay Qt)."""

import core.ocr_check as oc
from core.champions import LoadReport


class FakeScanner:
    instances: list = []

    def __init__(self, **kw):
        self.kw = kw
        self.is_running = False
        type(self).instances.append(self)

    def start(self):
        self.is_running = True

    def stop(self):
        self.is_running = False

    def close(self):
        pass

    def notify_roll(self):
        self.rolls = getattr(self, "rolls", 0) + 1


def plan(**over):
    base = {
        "names": ["Vex"], "selected": [], "manual_names": "Vex", "detect_image": False, "detect_name": True,
        "region": {"left": 0, "top": 0, "width": 1000, "height": 200},
        "centers": [(40 + i * 190, 150) for i in range(5)],
        "threshold": 0.72, "name_threshold": 0.8, "interval_ms": 5, "all_names": ["Vex", "Zed"], "aliases": {},
    }
    base.update(over)
    return base


def champ(name, set_no=18, tier=1, alt=""):
    cid = f"Maps/Shipping/Map22/Sets/TFTSet{set_no}/Shop/TFT{set_no}_{name.replace(' ', '')}"
    return {"id": cid, "name": name, "alt_name": alt or name, "tier": tier, "set": set_no,
            "image_url": f"http://x/img/tft-champion/TFT{set_no}_{name.replace(' ', '')}.png"}


ENTRIES = [champ("Vex", tier=1), champ("Zed", tier=2), champ("Graves", tier=1), champ("Sivir", 17, tier=1),
           champ("Ahri", tier=4), champ("Jinx", tier=5)]

OK_OCR = oc.OcrStatus(True, "winocr", ["en-US"])
BAD_OCR = oc.OcrStatus(False, "winocr", [], detail="Thiếu pack ngôn ngữ", hints=["Add-WindowsCapability demo"])


def fake_loader(entries, report=None, fail=None):
    """Thay core.champions.load_all_champions: không mạng; gọi on_update(entries) rồi trả báo cáo (hoặc ném `fail`)."""

    def loader(locale, on_update, should_stop=lambda: False, on_progress=None):
        if fail is not None:
            raise fail
        on_update(entries)
        return report or LoadReport(versions_total=1, versions_new=1)

    return loader


def detail_entry(name, set_no=18, cost=1, role="ADFighter", traits=("Đấu Sĩ", "Thợ Săn"), complete=True, desc="Gây sát thương lên mục tiêu."):
    return {"name": name, "set": set_no, "cost": cost, "role": role, "traits": list(traits),
            "stats": {"hp": 650.0, "damage": 40.0, "armor": 35.0, "magicResist": 35.0, "attackSpeed": 0.75, "range": 1.0,
                      "initialMana": 0.0, "mana": 40.0, "critChance": 0.25},
            "ability": {"name": f"Chiêu của {name}", "desc": desc, "complete": complete}}


# Chi tiết giả khớp ENTRIES: Vex đủ số, Zed thiếu số trong mô tả, các tướng khác không có (như tướng mùa cũ).
DETAILS = {"vex": detail_entry("Vex", role="APCaster", traits=("Mê Hoặc",)),
           "zed": detail_entry("Zed", role="ADReaper", complete=False, desc="Gây [?] sát thương.")}


def fake_details(catalog=None, offline=False, fail=None, calls=None):
    """Thay core.controller.get_details: không mạng. `calls` (nếu có) ghi lại locale mỗi lần được gọi."""
    from core.champion_details import Details

    def get(locale, *a, **k):
        if calls is not None:
            calls.append(locale)
        if fail is not None:
            raise fail
        return Details(DETAILS if catalog is None else catalog, offline=offline)

    return get
