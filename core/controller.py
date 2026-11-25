"""Điều phối của app, KHÔNG phụ thuộc giao diện (không import Tk/Qt): trạng thái chọn tướng, cấu hình, kiểm tra điều kiện
chạy, chuẩn bị nền (OCR + tải ảnh), tạo/dừng scanner, preview, ghi cấu hình. Giao diện chỉ gọi các phương thức ở đây và nhận
sự kiện qua `notify(event, **data)`.

Quy ước luồng: mọi phương thức công khai gọi từ luồng giao diện. Việc ở luồng nền (tải danh sách tướng, chuẩn bị, chụp preview,
callback của scanner) quay về luồng giao diện bằng `post(fn)` do giao diện cung cấp (Qt: signal; test: gọi ngay)."""

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from core import config as _config
from core import license as license_check
from core import monitors as monitors_mod
from core import profiles as profiles_mod
from core.build_info import app_version
from core.champion_details import find_detail, get_details
from core.champions import (
    PORTRAIT_WORKERS,
    alias_groups,
    aliases_for_targets,
    available_seasons,
    download_template,
    is_selected,
    load_all_champions,
    load_champion_cache,
    matches_query,
    merge_champions,
    normalize_locale,
    reference_names,
    run_parallel,
    save_champion_cache,
    save_custom_template,
    selection_keys,
    template_path,
    visible_champions,
)
from core.config import (
    NUMERIC_LIMITS,
    load_config_with_notes,
    migrate_coordinates,
    normalize_custom_templates,
    parse_int_in_range,
    save_config,
    to_stored_template_path,
)
from core.hotkey import DEFAULT_HOTKEY, register_roll_hotkey, register_toggle_hotkey
from core.logging_setup import logger
from core.monitors import Monitor, monitor_for_region
from core.name_matcher import DEFAULT_NAME_THRESHOLD
from core.ocr_check import OCR_BLOCK, OCR_IMAGE_ONLY, OcrStatus, check_ocr, start_decision
from core.preview import PreviewResult, build_shop_preview
from core.scanner import ShopScanner, build_templates, find_points_outside_region, format_loop_speed

SPEED_IDLE_TEXT = "Thực tế: sẽ đo khi đang quét (không thể nhanh hơn thời gian chụp màn hình)"

# Các bước người dùng cần làm trước khi chạy: khóa này cũng là tên "trang" mà giao diện nhảy tới khi thiếu.
STEP_CHAMPIONS = "champions"
STEP_REGION = "region"
STEP_CLICKS = "clicks"
STEP_SETTINGS = "settings"
STEP_OCR = "ocr"

TONE_OK, TONE_FAIL, TONE_WARN, TONE_MUTED = "ok", "fail", "warn", "muted"


@dataclass(frozen=True)
class Requirement:
    """Một điều kiện để chạy. `ok` False thì giao diện hiện `text` và dẫn tới `step`."""

    key: str
    ok: bool
    text: str
    step: str
    blocking: bool = True  # False = chỉ cảnh báo (vd OCR chưa kiểm tra), vẫn chạy được


STATE_NONE, STATE_OK, STATE_PENDING = "none", "ok", "pending"
SOURCE_GAME, SOURCE_REGION, SOURCE_PRIMARY = "game", "region", "primary"
_SOURCE_NOTE = {SOURCE_GAME: "tự nhận theo cửa sổ game", SOURCE_REGION: "game chưa chạy: dùng màn hình đã cấu hình gần nhất",
                SOURCE_PRIMARY: "game chưa chạy: dùng màn hình chính"}


@dataclass(frozen=True)
class MonitorStatus:
    """Màn hình đang dùng và tình trạng bộ vùng Shop + điểm click của nó.

    state: 'ok' (có bộ đã xác nhận cho màn hình này), 'pending' (chưa có: có gợi ý quy đổi từ bộ khác, chờ người dùng xác nhận,
    chưa cho chạy), 'none' (chưa cấu hình gì). suggestion = {shop_region, slot_centers, from_name} khi pending."""

    state: str
    monitor: Monitor | None
    source: str
    text: str
    suggestion: dict | None = None


_ERROR_MARKS = ("không bắt đầu được", "không hoạt động", "không chụp được", "bị kẹt", "gặp vấn đề", "lỗi tải", "lỗi khi", "lỗi tạo")
_WARN_MARKS = ("bỏ click", "không click", "không có mạng", "không liên lạc", "lỗi mạng", "chưa có danh sách", "chưa xác nhận")


def classify_log(text: str) -> str:
    """Mức của một dòng Nhật ký: 'error' (đỏ), 'warn' (cam) hay 'info'. Để thanh Nhật ký đang đóng vẫn báo được có lỗi mà không cần
    mở ra; không đổi nội dung dòng nên các nơi gọi log() giữ nguyên."""
    t = text.lower()
    body = t.split("] ", 1)[1] if t.startswith("[") and "] " in t else t
    if "hồi phục" in body or "đọc lại được" in body:  # báo đã khắc phục: không phải lỗi dù có nhắc tới lỗi cũ
        return "info"
    if body.startswith(("⚠", "lỗi")) or any(m in body for m in _ERROR_MARKS):
        return "error"
    if body.startswith("cảnh báo") or any(m in body for m in _WARN_MARKS):
        return "warn"
    return "info"


def _immediate(fn: Callable[[], None]) -> None:
    fn()


class AppController:
    def __init__(self, notify: Callable[..., None], post: Callable[[Callable[[], None]], None] = _immediate,
                 keyboard=None, scanner_factory=ShopScanner):
        self._notify = notify
        self._post = post
        self._keyboard = keyboard
        self._scanner_factory = scanner_factory

        self.config, self.config_notes = load_config_with_notes()
        needs_save = self.config.get("coords_version") != _config.COORDS_VERSION
        self.coords_reset = migrate_coordinates(self.config)
        if needs_save:
            save_config(self.config)

        self.all_entries: list[dict] = []
        self.champions: list[dict] = []
        self._selected: set[str] = set()  # tên chuẩn của tướng đang tick (khi đã tải danh sách)
        self._saved_selection: list[str] = list(self.config.get("selected_champions", []))  # dùng khi offline
        self.query = ""
        self.cost_filter: set[int] = set()  # rỗng = mọi cost
        self.only_selected = False
        self.seasons: set[int] = set(self.config.get("season_filter", []))  # bộ lọc mùa; rỗng = tất cả các mùa

        self.detect_image = bool(self.config.get("detect_by_image", True))
        self.detect_name = bool(self.config.get("detect_by_name", True))
        self.threshold = float(self.config.get("match_threshold", 0.72))
        self.name_threshold = float(self.config.get("name_match_threshold", DEFAULT_NAME_THRESHOLD))
        self.interval_text = str(self.config.get("scan_interval_ms", 3))
        self.manual_names = str(self.config.get("manual_names", ""))

        self.scanner: ShopScanner | None = None
        self.hotkey = self.config.get("hotkey_toggle") or DEFAULT_HOTKEY
        self.roll_key = str(self.config.get("roll_key", "d")).strip()
        self._roll_handle = None
        self.preparing = False
        self.loading_champions = False
        self._portraits_running = False
        self._portraits_again = False  # danh sách được bổ sung khi luồng tải ảnh đang chạy: quét lại phần còn thiếu
        self._portraits_lock = threading.Lock()
        self.details: dict[str, dict] | None = None  # chi tiết tướng (chỉ số, kỹ năng, hệ) khi đã tải; None = chưa có
        self.details_offline = False  # đang dùng bản chi tiết đã lưu vì không tải mới được
        self.details_error = ""  # lý do lần tải gần nhất thất bại (rỗng nếu không lỗi)
        self.loading_details = False
        self.closing = False
        self.ocr_status: OcrStatus | None = None
        self.ocr_summary = ""
        self.last_speed: str | None = None
        self._preview_seq = 0
        self._preview_inflight = 0
        self.monitor_status: MonitorStatus | None = None
        self._logged_monitor: tuple | None = None  # (khóa, trạng thái) đã ghi Nhật ký, để không lặp lại mỗi lần kiểm tra

    # ------------------------------------------------------------------ tiện ích
    def notify(self, event: str, **data):
        try:
            self._notify(event, **data)
        except Exception:  # lỗi giao diện không được làm hỏng luồng điều phối
            logger.exception("Lỗi khi xử lý sự kiện giao diện %r", event)

    def log(self, msg: str):
        logger.info(msg)
        self.notify("log", text=f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", level=classify_log(msg))

    def set_status(self, text: str):
        self.notify("status", text=text)

    def _post_safe(self, fn):
        """Từ thread nền: về luồng giao diện; cửa sổ đã đóng thì bỏ qua."""
        if self.closing:
            return
        try:
            self._post(fn)
        except RuntimeError:
            pass

    def start_up(self):
        """Gọi một lần sau khi giao diện dựng xong: ghi phiên bản, báo config đã xử lý, tải tướng, ảnh preview, phím tắt."""
        self.log(f"Phiên bản: {app_version()}")
        if self.config_notes:
            for line in self.config_notes:
                self.log(line)
            self.notify("dialog", level="warning", title="Cấu hình đã được xử lý khi mở",
                        text="\n".join(self.config_notes))
        if self.coords_reset:
            msg = ("Cấu hình cũ có thể lưu sai hệ tọa độ (scale màn hình). Đã xóa vùng Shop và điểm click — "
                   "hãy chọn lại.")
            self.log(msg)
            self.notify("dialog", level="info", title="Cấu hình lại vùng Shop",
                        text=msg + "\n\n1. 'Chọn vùng Shop'\n2. 'Đặt điểm click (5 ô)'")
        self.register_hotkey()
        self.register_roll_key()
        self.load_champions_async()
        self.refresh_monitor(preview=False)
        self.request_preview(capture_live=False)

    # ------------------------------------------------------------------ vùng Shop / điểm click
    def region_text(self) -> str:
        r = self.config.get("shop_region")
        c = self.config.get("slot_centers", [])
        if r:
            return f"Shop: ({r['left']}, {r['top']}) {r['width']}x{r['height']} | Click: {len(c)}/5 ô"
        return "Chưa cấu hình shop"

    def set_region(self, region: dict):
        """Lưu vùng Shop vừa chọn. Vùng thuộc màn hình khác với bộ đang dùng thì điểm click cũ (của màn hình kia) bị bỏ."""
        mon = monitor_for_region(monitors_mod.list_monitors(), region)
        previous = self.config.get("active_monitor", "")
        self.config["shop_region"] = region
        if mon is not None and previous and previous != mon.key:
            self.config["slot_centers"] = []
        self._store_profile(mon)
        save_config(self.config)
        self.log(f"Đã lưu vùng shop: {region['left']},{region['top']} {region['width']}x{region['height']}"
                 + (f" ({mon.label()})" if mon else ""))
        self._mark_active(mon)
        self.notify("config_changed")
        self.request_preview(capture_live=True)

    def set_click_points(self, centers: list[tuple[int, int]]):
        self.config["slot_centers"] = [list(c) for c in centers]
        region = self.config.get("shop_region")
        self._store_profile(monitor_for_region(monitors_mod.list_monitors(), region) if region else None)
        save_config(self.config)
        self.log(f"Đã lưu 5 điểm click: {centers}")
        self._mark_active(monitor_for_region(monitors_mod.list_monitors(), region) if region else None)
        self.notify("config_changed")
        self.request_preview(capture_live=True)

    def point_inside_region(self, x: int, y: int) -> bool:
        region = self.config.get("shop_region")
        return bool(region) and not find_points_outside_region(region, [(x, y)])

    # ------------------------------------------------------------------ màn hình và bộ cấu hình theo màn hình
    def _store_profile(self, mon: Monitor | None):
        """Ghi vùng Shop + điểm click hiện tại thành bộ của màn hình `mon` và đánh dấu đó là bộ đang dùng."""
        region = self.config.get("shop_region")
        if mon is None or not region:
            return
        centers = self.config.get("slot_centers") or []
        self.config["monitor_profiles"][mon.key] = profiles_mod.make_profile(mon, region, centers if len(centers) == 5 else [])
        self.config["active_monitor"] = mon.key

    def _mark_active(self, mon: Monitor | None):
        """Người dùng vừa tự chọn/xác nhận vùng Shop ở màn hình `mon`: màn hình đó thành màn hình đang dùng (không dò lại game)."""
        if mon is None:
            return
        ready = len(self.config.get("slot_centers") or []) == 5
        text = f"{mon.label()} — bộ vùng Shop vừa lưu" + ("" if ready else " — chưa đặt 5 điểm click")
        self.monitor_status = MonitorStatus(STATE_OK, mon, SOURCE_REGION, text)
        self._logged_monitor = (mon.key, STATE_OK)
        self.notify("monitor_changed")

    def _target_monitor(self, mons: list[Monitor]) -> tuple[Monitor, str]:
        """Màn hình cần dùng: chứa cửa sổ game; game chưa chạy thì màn hình đã cấu hình gần nhất (nhận lại theo tên thiết bị + độ
        phân giải nên vẫn đúng khi các màn hình bị sắp xếp lại), rồi màn hình chứa vùng Shop; không có thì màn hình chính."""
        names = _config.game_process_set(self.config.get("game_process_names"))
        found = monitors_mod.game_monitor(names, mons)
        if found is not None:
            return found, SOURCE_GAME
        active = self.config.get("active_monitor")
        by_key = next((m for m in mons if m.key == active), None) if active else None
        if by_key is not None:
            return by_key, SOURCE_REGION
        region = self.config.get("shop_region")
        by_region = monitor_for_region(mons, region) if region else None
        if by_region is not None:
            return by_region, SOURCE_REGION
        return next((m for m in mons if m.primary), mons[0]), SOURCE_PRIMARY

    def _adopt_legacy_region(self, mons: list[Monitor]):
        """Config có vùng Shop nhưng chưa có bộ nào theo màn hình (cấu hình từ bản trước): gắn nó với màn hình chứa vùng."""
        region = self.config.get("shop_region")
        if self.config["monitor_profiles"] or not region:
            return
        mon = monitor_for_region(mons, region)
        if mon is not None:
            self._store_profile(mon)
            save_config(self.config)

    def refresh_monitor(self, preview: bool = True) -> MonitorStatus:
        """Nhận lại màn hình đang dùng (theo cửa sổ game) và áp đúng bộ vùng Shop + điểm click đã lưu cho nó.
        Màn hình chưa có bộ: tạo gợi ý quy đổi nhưng KHÔNG dùng; phải được người dùng xác nhận (accept_suggestion) mới chạy."""
        mons = monitors_mod.list_monitors()
        if not mons:
            status = MonitorStatus(STATE_NONE, None, "", "Không đọc được danh sách màn hình.")
            self.monitor_status = status
            self.notify("monitor_changed")
            return status
        self._adopt_legacy_region(mons)
        mon, source = self._target_monitor(mons)
        profiles = self.config["monitor_profiles"]
        profile = profiles.get(mon.key)
        switched = False
        if profile is not None:
            region, centers, how = profiles_mod.adapt(profile, mon)
            if how == "moved":  # chỉ sắp xếp lại màn hình: tọa độ dịch theo, chính xác
                profiles[mon.key] = profiles_mod.make_profile(mon, region, centers)
                self.log(f"{mon.label()} đã đổi vị trí trên desktop: dời vùng Shop và điểm click theo.")
            switched = (self.config.get("shop_region") != region or self.config.get("slot_centers") != centers
                        or self.config.get("active_monitor") != mon.key)
            if switched or how == "moved":
                self.config["shop_region"], self.config["slot_centers"] = region, centers
                self.config["active_monitor"] = mon.key
                save_config(self.config)
            ready = len(centers) == 5
            text = f"{mon.label()} — {_SOURCE_NOTE[source]}" + ("" if ready else " — chưa đặt 5 điểm click")
            status = MonitorStatus(STATE_OK, mon, source, text)
        else:
            near = profiles_mod.nearest(profiles, mon)
            if near is None:
                status = MonitorStatus(STATE_NONE, mon, source, f"{mon.label()} — chưa cấu hình vùng Shop")
            else:
                key, prof = near
                region, centers, _ = profiles_mod.adapt(prof, mon)
                from_name = prof.get("name") or key
                status = MonitorStatus(
                    STATE_PENDING, mon, source,
                    f"{mon.label()} chưa có vùng Shop đã xác nhận. Gợi ý quy đổi từ {from_name}: bấm 'Xem và xác nhận gợi ý' "
                    "hoặc chọn lại vùng Shop.",
                    {"shop_region": region, "slot_centers": centers, "from_name": from_name})
        self.monitor_status = status
        tag = (mon.key, status.state)
        if tag != self._logged_monitor:
            self._logged_monitor = tag
            self.log(f"Màn hình đang dùng: {status.text}" if status.state != STATE_PENDING else status.text)
        self.notify("monitor_changed")
        if switched and preview:
            self.request_preview(capture_live=True)
        return status

    @property
    def monitor_pending(self) -> bool:
        return self.monitor_status is not None and self.monitor_status.state == STATE_PENDING

    def accept_suggestion(self) -> bool:
        """Người dùng xác nhận gợi ý quy đổi cho màn hình hiện tại: dùng và lưu thành bộ của màn hình đó."""
        st = self.monitor_status
        if st is None or st.state != STATE_PENDING or not st.suggestion or st.monitor is None:
            return False
        self.config["shop_region"] = dict(st.suggestion["shop_region"])
        self.config["slot_centers"] = [list(p) for p in st.suggestion["slot_centers"]]
        self._store_profile(st.monitor)
        save_config(self.config)
        self.log(f"Đã dùng vùng Shop quy đổi cho {st.monitor.label()}.")
        self._mark_active(st.monitor)
        self.notify("config_changed")
        self.request_preview(capture_live=True)
        return True

    def view_plan(self) -> dict | None:
        """Dữ liệu để vẽ overlay 'Xem trên màn hình': vùng Shop + điểm click của màn hình đang dùng (hoặc gợi ý chờ xác nhận).
        None nếu chưa có vùng Shop nào để xem."""
        st = self.refresh_monitor()
        if st.state == STATE_PENDING and st.suggestion:
            return {"region": st.suggestion["shop_region"], "centers": st.suggestion["slot_centers"], "monitor": st.monitor,
                    "confirm": True}
        region = self.config.get("shop_region")
        if not region:
            return None
        centers = self.config.get("slot_centers") or []
        return {"region": region, "centers": [tuple(c) for c in centers], "monitor": st.monitor, "confirm": False}

    # ------------------------------------------------------------------ danh sách tướng
    def load_champions_async(self):
        if self.loading_champions:
            return
        self.loading_champions = True
        self.set_status("Đang tải danh sách tướng...")
        threading.Thread(target=self._fetch_champions, daemon=True).start()

    def reload_champions(self):
        """Nút 'Tải lại danh sách': đã có danh sách thì không làm gì (tải lại sẽ đặt lại ô tick)."""
        if self.champions:
            self.log("Danh sách tướng đã tải rồi.")
            return
        if self.loading_champions:
            return
        self.log("Đang thử tải lại danh sách tướng...")
        self.load_champions_async()

    def _fetch_champions(self):
        """Luồng nền: nạp tướng của mọi mùa (xem champions.load_all_champions). Mỗi bước có dữ liệu mới thì đưa về luồng giao diện."""
        locale = normalize_locale(self.config.get("champion_locale"))

        def update(entries):
            try:
                save_champion_cache(entries)  # tên + alias cho OCR khi offline
            except OSError as e:
                logger.warning("Không ghi được champions_cache.json: %s", e)
            self._post_safe(lambda: self.populate_champions(entries, final=False))

        def progress(done, total):
            self._post_safe(lambda: self.set_status(f"Đang tải thêm các mùa cũ ({done}/{total} bản)..."))

        try:
            report = load_all_champions(locale, update, should_stop=lambda: self.closing, on_progress=progress)
        except Exception as e:
            msg = f"Lỗi tải tướng: {e}"
            self._post_safe(lambda: self._champions_failed(msg))
            return
        self._post_safe(lambda: self._champions_loaded(report))

    def _champions_loaded(self, report):
        """Cả đợt nạp đã xong (hoặc dừng vì offline): mở khóa nút Tải lại và báo kết quả."""
        self.loading_champions = False
        n = len(self.champions)
        if report.offline:
            self.set_status(f"Không có mạng — dùng danh sách đã lưu ({n} tướng)")
            self.log("Không liên lạc được Data Dragon: đang dùng danh sách tướng đã lưu ở lần trước.")
        else:
            seasons = len(available_seasons(self.champions))
            self.set_status(f"Đã tải {n} tướng của {seasons} mùa")
            if report.versions_new:
                self.log(f"Đã tải danh sách tướng: {n} tướng, {seasons} mùa ({report.versions_new} bản patch mới quét).")
        if report.failed:
            self.log(f"{len(report.failed)}/{report.versions_total} bản patch lỗi mạng — lần mở sau sẽ thử lại.")
        self.notify("champions_changed")

    def _champions_failed(self, msg: str):
        self.loading_champions = False
        self.set_status(msg)
        self.log(f"{msg} — bấm 'Tải lại danh sách' để thử lại; tướng đã chọn vẫn được giữ.")
        self.notify("champions_changed")

    def populate_champions(self, entries: list[dict], final: bool = True):
        """Nhận các mục Data Dragon; gộp thành thẻ (mỗi tên một thẻ, mọi mùa) và khôi phục tướng đã chọn. Gọi nhiều lần được (danh sách
        bổ sung dần các mùa cũ): lần sau giữ nguyên lựa chọn hiện tại. final=True: đây là lần cuối, mở khóa nút Tải lại."""
        if self.champions:
            self._saved_selection = self.selected_names()  # giữ lựa chọn người dùng vừa tick giữa hai lần nạp
        if final:
            self.loading_champions = False
        self.all_entries = entries
        self.champions = merge_champions(entries)
        keys = selection_keys(self._saved_selection)
        self._selected = {c["name"] for c in self.champions if is_selected(c, keys)}
        known = set(available_seasons(self.champions))
        if self.seasons and not self.seasons & known:  # mùa đã lưu không còn trong dữ liệu: hiện tất cả
            self.seasons = set()
        else:
            self.seasons &= known
        self.set_status(f"Đã tải {len(self.champions)} tướng ({len(known)} mùa)")
        self.notify("champions_changed")
        self.notify("selection_changed")
        self.fetch_portraits_async()

    def visible(self) -> list[dict]:
        """Tướng theo bộ lọc mùa (chưa áp tìm kiếm/cost)."""
        return visible_champions(self.champions, self.seasons)

    def filtered(self) -> list[dict]:
        """Danh sách hiển thị: ĐANG TÌM KIẾM thì tìm trong MỌI mùa (bỏ qua bộ lọc mùa; khớp tên hoặc tên ngôn ngữ kia, không phân biệt
        dấu/hoa thường/dấu nháy), không thì theo bộ lọc mùa. Cost và 'chỉ đã chọn' luôn áp dụng."""
        searching = self.is_searching()
        out = []
        for c in (self.champions if searching else self.visible()):
            if searching and not matches_query(c, self.query):
                continue
            if self.cost_filter and c["tier"] not in self.cost_filter:
                continue
            if self.only_selected and c["name"] not in self._selected:
                continue
            out.append(c)
        return out

    def is_searching(self) -> bool:
        return bool(self.query.strip())

    def set_query(self, text: str):
        self.query = text
        self.notify("filter_changed")

    def toggle_cost(self, tier: int, on: bool):
        (self.cost_filter.add if on else self.cost_filter.discard)(tier)
        self.notify("filter_changed")

    def set_only_selected(self, on: bool):
        self.only_selected = bool(on)
        self.notify("filter_changed")

    def seasons_available(self) -> list[int]:
        return available_seasons(self.champions)

    def toggle_season(self, season: int, on: bool):
        """Bật/tắt một mùa trong bộ lọc. Bỏ mùa cuối cùng thì trở về Tất cả."""
        (self.seasons.add if on else self.seasons.discard)(season)
        self._save_seasons()

    def clear_seasons(self):
        """Nút Tất cả: bỏ bộ lọc mùa."""
        self.seasons = set()
        self._save_seasons()

    def _save_seasons(self):
        self.config["season_filter"] = sorted(self.seasons, reverse=True)
        save_config(self.config)
        self.notify("filter_changed")

    def costs_available(self) -> list[int]:
        return sorted({c["tier"] for c in (self.champions if self.is_searching() else self.visible())})

    def is_selected(self, name: str) -> bool:
        return name in self._selected

    def set_selected(self, name: str, on: bool):
        (self._selected.add if on else self._selected.discard)(name)
        if not self.champions:  # chưa tải được danh sách (offline): selected_names() đọc lựa chọn đã lưu, nên cập nhật cả nó
            self._saved_selection = [n for n in self._saved_selection if n != name] + ([name] if on else [])
        self.notify("selection_changed")

    def clear_selected(self):
        """Bỏ chọn MỌI tướng đang tick (kể cả mùa đang ẩn). Tên gõ tay không bị đụng tới."""
        self._selected.clear()
        self._saved_selection = []
        self.notify("selection_changed")

    def select_all_visible(self):
        """Tick mọi tướng đang hiển thị theo bộ lọc hiện tại (tướng mùa cũ đang ẩn không bị đụng tới)."""
        self._selected.update(c["name"] for c in self.filtered())
        self.notify("selection_changed")

    def deselect_all_visible(self):
        self._selected.difference_update(c["name"] for c in self.filtered())
        self.notify("selection_changed")

    def selected_names(self) -> list[str]:
        """Tướng đang tick. Chưa tải được danh sách (offline) thì dùng lựa chọn đã lưu, không để trống rồi ghi đè mất."""
        if not self.champions:
            return list(self._saved_selection)
        return [c["name"] for c in self.champions if c["name"] in self._selected]

    def parsed_manual_names(self) -> list[str]:
        parts = self.manual_names.replace("\n", ",").split(",")
        return [p.strip() for p in parts if p.strip()]

    def target_names(self) -> list[str]:
        names = list(self.selected_names())
        for n in self.parsed_manual_names():
            if n not in names:
                names.append(n)
        return names

    def portrait_path(self, champ: dict) -> Path | None:
        """File ảnh chân dung đã tải của tướng (None nếu chưa có)."""
        path = template_path(champ["name"], champ["image_url"])
        return path if path.exists() else None

    def fetch_portraits_async(self):
        """Tải ngầm ảnh chân dung còn thiếu của MỌI thẻ (từng ảnh một, mùa mới nhất trước, báo portrait_ready mỗi khi xong). Ảnh lưu ở
        data/templates/ nên lần sau không tải lại. Danh sách có thể được bổ sung (thêm mùa cũ) khi đang tải: gọi lại lúc luồng đang chạy
        chỉ đặt cờ, luồng đó quét lại phần còn thiếu trước khi thoát (không để lọt thẻ mới giữa lúc nó sắp kết thúc)."""
        with self._portraits_lock:
            if self._portraits_running:
                self._portraits_again = True
                return
            if not any(self.portrait_path(c) is None for c in self.champions):
                return
            self._portraits_running = True
            self._portraits_again = False

        def work():
            tried: set[str] = set()
            released = False
            try:
                while not self.closing:
                    todo = [c for c in sorted(self.champions, key=lambda c: -(c.get("set") or 0))
                            if c["name"] not in tried and self.portrait_path(c) is None]
                    if not todo:
                        with self._portraits_lock:
                            if self._portraits_again:
                                self._portraits_again = False
                                continue
                            self._portraits_running = False
                            released = True
                        return
                    tried.update(c["name"] for c in todo)

                    def fetch(c):
                        if download_template(c["name"], c["image_url"]):
                            self._post_safe(lambda n=c["name"]: self.notify("portrait_ready", name=n))

                    # Song song (tải lần lượt 237 ảnh mất gần 3 phút); mùa mới nhất nằm đầu danh sách nên được tải trước.
                    run_parallel(todo, fetch, PORTRAIT_WORKERS, should_stop=lambda: self.closing)
            finally:
                if not released:
                    with self._portraits_lock:
                        self._portraits_running = False

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ chi tiết tướng
    def request_details(self, force: bool = False):
        """Bắt đầu tải chi tiết tướng ở luồng nền (chỉ làm một lần: đã có dữ liệu hoặc đang tải thì bỏ qua; force=True để thử lại sau
        lỗi). Xong thì báo sự kiện details_changed; giao diện đọc kết quả bằng detail_for()/details_state()."""
        if self.loading_details or (self.details is not None and not force):
            return
        self.loading_details = True
        self.details_error = ""
        locale = normalize_locale(self.config.get("champion_locale"))

        def work():
            try:
                result = get_details(locale)
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                self._post_safe(lambda: self._details_failed(msg))
                return
            self._post_safe(lambda: self._details_loaded(result))

        threading.Thread(target=work, daemon=True).start()
        self.notify("details_changed")

    def _details_loaded(self, result):
        self.loading_details = False
        self.details = result.champions
        self.details_offline = result.offline
        self.details_error = ""
        if result.offline:
            self.log("Không tải được chi tiết tướng mới: đang dùng bản đã lưu ở lần trước.")
        self.notify("details_changed")

    def _details_failed(self, msg: str):
        self.loading_details = False
        self.details_error = msg
        self.log(f"Không tải được chi tiết tướng: {msg}")
        self.notify("details_changed")

    def details_state(self) -> str:
        """'ready' (đã có dữ liệu), 'loading' (đang tải), 'error' (tải lỗi, chưa có gì) hoặc 'idle' (chưa yêu cầu)."""
        if self.details is not None:
            return "ready"
        if self.loading_details:
            return "loading"
        return "error" if self.details_error else "idle"

    def detail_for(self, champ: dict) -> dict | None:
        """Chi tiết của một thẻ tướng; None nếu chưa tải xong hoặc nguồn không có tướng này (vd mùa cũ/sự kiện)."""
        return find_detail(self.details, champ)

    def upload_template(self, name: str, src_path: str):
        """Lưu ảnh upload cho một tướng. Ném ValueError/OSError nếu file không dùng được (giao diện báo)."""
        dest = save_custom_template(src_path, name)
        custom = self.config.setdefault("custom_templates", {})
        custom[name] = to_stored_template_path(dest)
        save_config(self.config)
        self.log(f"Đã upload ảnh cho {name}")

    def reference(self) -> tuple[list[str] | None, list[list[str]]]:
        """Toàn bộ tên tướng (cả hai ngôn ngữ) và nhóm alias để so OCR; lấy từ cache khi offline."""
        if self.all_entries:
            return reference_names(self.all_entries), alias_groups(self.all_entries)
        cached = load_champion_cache()
        return (cached[0], cached[1]) if cached else (None, [])

    # ------------------------------------------------------------------ điều kiện chạy
    def interval_value(self) -> int | None:
        lo, hi = (int(x) for x in NUMERIC_LIMITS["scan_interval_ms"])
        return parse_int_in_range(self.interval_text, lo, hi)

    def requirements(self) -> list[Requirement]:
        """Danh sách điều kiện chạy (đủ hay thiếu), theo thứ tự người dùng nên làm. Không có hộp thoại, không tác dụng phụ."""
        reqs: list[Requirement] = []
        n = len(self.target_names())
        reqs.append(Requirement("champions", n > 0, f"{n} tướng đang chọn" if n else "Chưa chọn tướng nào",
                                STEP_CHAMPIONS))
        reqs.append(Requirement("mode", self.detect_image or self.detect_name,
                                "Chế độ bắt: " + " + ".join(m for m, on in (("ảnh", self.detect_image),
                                                                            ("tên", self.detect_name)) if on)
                                if (self.detect_image or self.detect_name) else "Bật ít nhất 1 chế độ: ảnh hoặc tên",
                                STEP_CHAMPIONS))
        region = self.config.get("shop_region")
        if self.monitor_pending:
            # Bộ đã lưu thuộc màn hình khác nên chưa dùng được: chỉ hiện việc cần làm (xác nhận gợi ý hoặc chọn lại), không hiện
            # "chưa chọn vùng / 0/5 điểm" gây hiểu nhầm.
            reqs.append(Requirement("monitor", False, "Chưa xác nhận vùng Shop cho màn hình này", STEP_REGION))
        else:
            reqs.append(Requirement("region", bool(region), "Đã chọn vùng Shop" if region else "Chưa chọn vùng Shop",
                                    STEP_REGION))
            centers = self.config.get("slot_centers", [])
            if region and len(centers) == 5:
                outside = find_points_outside_region(region, centers)
                if outside:
                    reqs.append(Requirement("clicks", False,
                                            f"Điểm click ô {', '.join(map(str, outside))} nằm ngoài vùng Shop", STEP_CLICKS))
                else:
                    reqs.append(Requirement("clicks", True, "Đã đặt 5 điểm click", STEP_CLICKS))
            else:
                reqs.append(Requirement("clicks", False, f"Mới đặt {len(centers)}/5 điểm click", STEP_CLICKS))
        lo, hi = (int(x) for x in NUMERIC_LIMITS["scan_interval_ms"])
        ok_interval = self.interval_value() is not None
        reqs.append(Requirement("interval", ok_interval,
                                "Chu kỳ quét hợp lệ" if ok_interval else
                                f"Chu kỳ quét phải là số nguyên từ {lo} đến {hi} ms (đang là {self.interval_text!r})",
                                STEP_SETTINGS))
        if self.detect_name:
            if self.ocr_status is None:
                reqs.append(Requirement("ocr", True, "OCR: sẽ tự kiểm tra khi bắt đầu", STEP_OCR, blocking=False))
            elif self.ocr_status.ok:
                reqs.append(Requirement("ocr", True, f"OCR: {self.ocr_status.summary}", STEP_OCR))
            else:
                reqs.append(Requirement("ocr", False, f"OCR không hoạt động: {self.ocr_status.detail}", STEP_OCR,
                                        blocking=not self.detect_image))
        return reqs

    def first_missing(self) -> Requirement | None:
        return next((r for r in self.requirements() if not r.ok and r.blocking), None)

    def ready(self) -> bool:
        return self.first_missing() is None

    def changed(self):
        """Giao diện báo một cài đặt vừa đổi (chế độ, ngưỡng, chu kỳ, tên gõ tay): tính lại điều kiện chạy ngay."""
        self.notify("readiness_changed")

    def _validate_start(self) -> dict | None:
        try:
            license_check.require_active()
        except license_check.LicenseError as e:
            self.log(f"Không bắt đầu được: {e}")
            self.notify("dialog", level="error", title="Cần Key xác thực", text=str(e))
            return None
        self.refresh_monitor()  # game có thể vừa được chuyển sang màn hình khác từ lần kiểm tra trước
        missing = self.first_missing()
        if missing is not None:
            self.notify("blocked", requirement=missing)
            return None
        names = self.target_names()
        region = self.config["shop_region"]
        centers = self.config["slot_centers"]
        if self.detect_name and self.name_threshold < 0.75:
            self.log("Cảnh báo: Độ khớp tên < 75% — dễ mua nhầm tướng có tên gần giống; nên để từ 80% trở lên")
        all_names, groups = self.reference()
        if self.detect_name and not all_names:
            self.log("Cảnh báo: chưa có danh sách tên tướng đầy đủ (offline, chưa có cache) — chỉ so với tướng đã "
                     "chọn nên dễ nhận nhầm tướng khác. Bấm 'Tải lại danh sách' khi có mạng.")
        if self.detect_image and self.threshold > 0.75:
            self.log("Cảnh báo: Độ khớp ảnh > 75% — ảnh Data Dragon khó khớp in-game, nên hạ ~0.60–0.70")
        if not self.detect_image and self.detect_name:
            self.log("Gợi ý: Bật thêm 'Bắt theo ảnh' để mua chính xác hơn")
        return {
            "names": names,
            "selected": self.selected_names(),
            "manual_names": self.manual_names.strip(),
            "detect_image": self.detect_image,
            "detect_name": self.detect_name,
            "region": region,
            "centers": [tuple(c) for c in centers],
            "threshold": self.threshold,
            "name_threshold": self.name_threshold,
            "interval_ms": self.interval_value(),
            "all_names": all_names,
            "aliases": aliases_for_targets(names, groups),
        }

    # ------------------------------------------------------------------ bắt đầu / dừng
    @property
    def running(self) -> bool:
        return bool(self.scanner and self.scanner.is_running)

    def toggle(self):
        """Nút Bắt đầu/Dừng hoặc phím tắt."""
        if self.preparing:
            return
        if self.running:
            self.stop()
            return
        self.start()

    def stop(self):
        if self.scanner:
            self.scanner.stop()
        self.scanner = None
        self.last_speed_shown()
        self.set_status("Đã dừng")
        self.notify("running_changed", running=False)

    # ------------------------------------------------------------------ giấy phép
    def license_summary(self) -> dict:
        """Thông tin giấy phép để hiện ở mục Nâng cao: ok, key_id, giờ kích hoạt, lý do nếu không hợp lệ (không có chuỗi Key)."""
        status = license_check.check_installed()
        activated = ""
        if status.activated_at:
            activated = datetime.fromtimestamp(status.activated_at).strftime("%Y-%m-%d %H:%M")
        return {
            "ok": status.ok,
            "key_id": status.info.key_id if status.info else "",
            "activated": activated,
            "reason": status.reason,
        }

    def last_speed_shown(self):
        self.notify("speed", text=f"Lần quét trước: {self.last_speed}" if self.last_speed else SPEED_IDLE_TEXT)

    def start(self):
        plan = self._validate_start()
        if plan is None:
            return
        jobs = []
        if plan["detect_image"]:
            jobs = [(c["name"], c["image_url"]) for c in self.champions if c["name"] in plan["names"]]
        if not jobs and not plan["detect_name"]:
            self.notify("ocr", text="OCR: không dùng (chỉ bắt theo ảnh)", tone=TONE_MUTED)
            self._finish_start(plan, {}, None)
            return
        self.preparing = True
        self.notify("preparing", on=True)
        self.set_status("Đang kiểm tra OCR..." if plan["detect_name"] else f"Đang tải ảnh tướng (0/{len(jobs)})...")
        threading.Thread(target=self._prepare_background, args=(plan, jobs), daemon=True).start()

    def _prepare_background(self, plan: dict, jobs: list[tuple[str, str]]):
        ocr: OcrStatus | None = None
        if plan["detect_name"]:
            try:
                extra = ("vi-VN",) if normalize_locale(self.config.get("champion_locale")).startswith("vi") else ()
                ocr = check_ocr(wanted_extra=extra)
            except Exception as e:
                ocr = OcrStatus(False, "none", detail=f"Không kiểm tra được OCR: {type(e).__name__}: {e}")
        paths: dict[str, Path] = {}
        failure = ""
        try:
            for i, (name, url) in enumerate(jobs, 1):
                if self.closing:
                    return
                path = download_template(name, url)
                if path:
                    paths[name] = path
                self._post_safe(lambda i=i: self.set_status(f"Đang tải ảnh tướng ({i}/{len(jobs)})..."))
        except Exception as e:
            failure = f"{type(e).__name__}: {e}"
        self._post_safe(lambda: self._templates_ready(plan, paths, failure, ocr))

    def _templates_ready(self, plan, paths, failure, ocr):
        self.preparing = False
        if self.closing:
            return
        self.notify("preparing", on=False)
        if failure:
            self.log(f"Lỗi khi tải ảnh tướng: {failure}")
        self._finish_start(plan, paths, ocr)

    def _apply_ocr_status(self, ocr: OcrStatus):
        self.ocr_status = ocr
        self.ocr_summary = ocr.summary if ocr.ok else ""
        if ocr.ok:
            self.notify("ocr", text=f"OCR: {ocr.summary} ✓", tone=TONE_OK)
            self.log(f"OCR: {ocr.summary}")
        else:
            self.notify("ocr", text=f"OCR: {ocr.summary}", tone=TONE_FAIL)
            self.log(f"⚠ OCR không hoạt động: {ocr.detail}")
        for hint in ocr.hints:
            self.log(f"Gợi ý OCR: {hint}")
        self.notify("readiness_changed")

    def _finish_start(self, plan: dict, paths: dict[str, Path], ocr: OcrStatus | None = None):
        names = plan["names"]
        detect_image, detect_name = plan["detect_image"], plan["detect_name"]
        templates = {}
        if detect_image:
            custom = normalize_custom_templates(self.config.get("custom_templates", {}))
            self.config["custom_templates"] = custom
            templates = build_templates(names, custom, paths, log=self.log)
            if not templates:
                if not detect_name:
                    self.notify("dialog", level="error", title="Lỗi",
                                text="Không tải được ảnh tướng. Bật 'Bắt theo tên' hoặc upload ảnh.")
                    self.set_status("Sẵn sàng")
                    return
                self.log("Không có ảnh — chỉ dùng bắt theo tên")

        use_name = detect_name
        if detect_name and ocr is not None:
            self._apply_ocr_status(ocr)
            decision = start_decision(ocr, detect_name, image_ready=bool(detect_image and templates))
            if decision == OCR_IMAGE_ONLY:
                use_name = False
                self.log("Tắt 'Bắt theo tên' trong lần chạy này, chỉ bắt theo ảnh.")
                self.notify("dialog", level="warning", title="OCR không hoạt động",
                            text="OCR không hoạt động nên lần chạy này chỉ bắt theo ảnh.\n\n" + ocr.problem_text())
            elif decision == OCR_BLOCK:
                self.notify("dialog", level="error", title="OCR không hoạt động",
                            text="Không thể bắt theo tên vì OCR không hoạt động, và không có ảnh mẫu để bắt theo ảnh.\n\n"
                                 + ocr.problem_text()
                                 + "\n\nCó thể bật 'Bắt theo ảnh' (và chọn tướng có ảnh) để dùng tạm.")
                self.set_status("OCR không hoạt động — chưa bắt đầu")
                return

        self.config["selected_champions"] = plan["selected"]
        self.config["manual_names"] = plan["manual_names"]
        self.config["detect_by_image"] = detect_image
        self.config["detect_by_name"] = detect_name
        self.config["match_threshold"] = plan["threshold"]
        self.config["name_match_threshold"] = plan["name_threshold"]
        self.config["scan_interval_ms"] = plan["interval_ms"]
        save_config(self.config)

        def ui(fn):
            return lambda *a: self._post_safe(lambda: fn(*a))

        scanner = self._scanner_factory(
            shop_region=plan["region"],
            slot_centers=plan["centers"],
            templates=templates,
            target_names=names,
            threshold=plan["threshold"],
            name_threshold=plan["name_threshold"],
            detect_by_image=detect_image,
            detect_by_name=use_name,
            scan_interval_ms=plan["interval_ms"],
            name_scan_interval_ms=self.config.get("name_scan_interval_ms", 50),
            buy_cooldown_ms=self.config.get("buy_cooldown_ms", 90),
            buy_delay_ms=self.config.get("buy_delay_ms", 0),
            card_same_corr=self.config.get("card_same_corr", 0.80),
            require_game_foreground=self.config.get("require_game_foreground", True),
            game_process_names=self.config.get("game_process_names"),
            all_names=plan["all_names"],
            target_aliases=plan["aliases"],
            on_match=lambda name, slot, score, method: self._post_safe(
                lambda: self.log(f"✓ Mua {name} ở ô {slot} ({method} {score:.0%})")),
            on_status=ui(self.set_status),
            on_error=lambda msg, fatal: self._post_safe(lambda: self._scanner_error(msg, fatal)),
            on_log=ui(self.log),
            on_ocr_health=ui(self._ocr_health),
            on_stats=ui(self._stats),
            capture_backend=self.config.get("capture_backend", "auto"),
            verbose_log=self.config.get("verbose_log", True),
            learn_portraits=True,  # nhớ ảnh thẻ lần đầu OCR đọc đúng → lần sau nhận ra bằng ảnh, không chờ OCR
            portraits_dir=_config.PORTRAITS_DIR,
            async_ocr=True,  # OCR ở luồng riêng: vòng quét không bị chặn khi roll nhanh
        )
        modes = []
        if detect_image and templates:
            modes.append("ảnh")
        if use_name:
            modes.append("tên")
        self.log(f"Sẵn sàng bắt {len(names)} tướng [{', '.join(modes)}]: {', '.join(names)}")

        scanner.start()
        if not scanner.is_running:
            scanner.close()
            return
        self.scanner = scanner
        self.last_speed = None
        self.notify("speed", text="Thực tế: đang đo...")
        self.notify("running_changed", running=True)
        self.log("Bắt đầu quét — bạn chỉ cần roll (D) trong game!")

    def _stats(self, snap: dict):
        if not self.running:
            return  # callback đến muộn sau khi dừng
        self.last_speed = format_loop_speed(snap["avg_ms"], snap["max_ms"])
        self.notify("speed", text=f"Thực tế: {self.last_speed}")

    def _ocr_health(self, ok: bool):
        if ok:
            self.notify("ocr", text=f"OCR: {self.ocr_summary} ✓", tone=TONE_OK)
        else:
            self.notify("ocr", text="OCR: có vấn đề (không đọc được chữ hoặc bị kẹt) — xem Nhật ký", tone=TONE_WARN)

    def _scanner_error(self, msg: str, fatal: bool):
        self.log(f"⚠ {msg}")
        if not fatal:
            return
        if self.scanner is not None and not self.scanner.is_running:
            self.scanner = None
            self.last_speed_shown()
            self.notify("running_changed", running=False)
        self.set_status(msg)

    # ------------------------------------------------------------------ preview
    def request_preview(self, capture_live: bool = True):
        """Chụp (hoặc đọc ảnh đã lưu) ở thread nền. Chỉ kết quả của yêu cầu MỚI NHẤT được hiển thị."""
        region = self.config.get("shop_region")
        if not region:
            return
        centers = self.config.get("slot_centers", [])
        slot_centers = centers if len(centers) == 5 else None
        self._preview_seq += 1
        seq = self._preview_seq
        self._preview_inflight += 1
        self.notify("preview_busy", busy=True)

        def work():
            try:
                result = build_shop_preview(region, slot_centers, capture_live=capture_live)
            except Exception as e:
                result = PreviewResult(None, False, f"Lỗi tạo preview: {type(e).__name__}: {e}")
            self._post_safe(lambda: self._preview_ready(seq, result))

        threading.Thread(target=work, daemon=True).start()

    def refresh_preview(self) -> bool:
        """Nút 'Làm mới ảnh'. Trả False nếu chưa có vùng Shop."""
        if not self.config.get("shop_region"):
            return False
        self.log("Đang chụp lại vùng shop...")
        self.request_preview(capture_live=True)
        return True

    def _preview_ready(self, seq: int, result: PreviewResult):
        self._preview_inflight = max(0, self._preview_inflight - 1)
        if self._preview_inflight == 0:
            self.notify("preview_busy", busy=False)
        if seq != self._preview_seq or self.closing:
            return
        note, tone = result.note, TONE_MUTED
        if result.image is None and note:
            tone = TONE_FAIL
        elif result.image is not None and not result.live and note:
            tone = TONE_WARN
        if result.captured_at and result.image is not None:
            stamp = result.captured_at.strftime("%H:%M:%S" if result.live else "%H:%M %d/%m")
            note = (f"Chụp lúc {stamp}. " if result.live else f"({stamp}) ") + note
        self.notify("preview", image=result.image, note=note.strip(), tone=tone)
        if note and (result.image is None or not result.live):
            self.log(f"Preview: {result.note}")

    # ------------------------------------------------------------------ phím tắt / đóng
    def hotkey_text(self) -> str:
        return f"Phím bật/tắt: {self.hotkey.upper()}"

    def toggle_text(self, running: bool) -> str:
        return f"⏹ DỪNG ({self.hotkey.upper()})" if running else f"▶ BẮT ĐẦU ({self.hotkey.upper()})"

    def register_hotkey(self):
        if self._keyboard is None:
            return
        effective, lines = register_toggle_hotkey(self._keyboard.add_hotkey, self.hotkey,
                                                  lambda: self._post_safe(self.toggle))
        for line in lines:
            self.log(line)
        if effective and effective != self.hotkey:
            self.hotkey = effective
        self.notify("hotkey_changed")

    def _on_roll_pressed(self):
        """Gọi từ luồng của thư viện phím: báo scanner quét dày NGAY (không qua luồng giao diện để khỏi trễ)."""
        scanner = self.scanner
        if scanner is not None:
            scanner.notify_roll()

    def register_roll_key(self):
        """Đăng ký (lại) phím roll theo self.roll_key; gỡ phím cũ nếu có."""
        if self._keyboard is None:
            return
        if self._roll_handle is not None:
            try:
                self._keyboard.remove_hotkey(self._roll_handle)
            except Exception:
                pass
            self._roll_handle = None
        self._roll_handle, lines = register_roll_hotkey(
            self._keyboard.add_hotkey, self.roll_key, self._on_roll_pressed, toggle_key=self.hotkey
        )
        for line in lines:
            self.log(line)

    def set_roll_key(self, text: str):
        """Giao diện đổi phím roll (rỗng = tắt). Lưu vào config và đăng ký lại ngay."""
        self.roll_key = (text or "").strip()
        self.config["roll_key"] = self.roll_key
        save_config(self.config)
        if not self.roll_key:
            self.log("Đã tắt đồng bộ phím roll.")
        self.register_roll_key()
        self.notify("config_changed")

    def close(self):
        self.closing = True
        if self.scanner:
            self.scanner.stop()
        if self._keyboard is not None:
            try:
                self._keyboard.unhook_all()
            except Exception:
                pass
