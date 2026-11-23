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
