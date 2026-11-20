"""Fixture dùng chung: cô lập thư mục data/, giả lập mss / click / foreground để test không đụng máy thật."""

import os

# Qt chạy không cần màn hình (offscreen) và dùng font của Windows để chữ thật sự vẽ ra khi chụp ảnh giao diện.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import pytest  # noqa: E402

import core.champions as champions  # noqa: E402
import core.config as config  # noqa: E402
import core.license as license_mod  # noqa: E402
import core.scanner as sc  # noqa: E402
from tests.helpers import CENTERS, REGION  # noqa: E402


@pytest.fixture(autouse=True)
def _license_active(request, monkeypatch):
    """Máy test không có Key thật: coi như đã kích hoạt, trừ test đánh dấu @pytest.mark.real_license (kiểm tra chính giấy phép)."""
    if request.node.get_closest_marker("real_license") is None:
        monkeypatch.setattr(license_mod, "require_active", lambda: None)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Trỏ mọi đường dẫn data/ vào thư mục tạm."""
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "TEMPLATES_DIR", data / "templates")
    monkeypatch.setattr(config, "CONFIG_PATH", data / "config.json")
    monkeypatch.setattr(config, "SHOP_CAPTURE_PATH", data / "shop_capture.png")
    monkeypatch.setattr(config, "LEGACY_SHOP_PREVIEW_PATH", data / "shop_preview.png")
    monkeypatch.setattr(champions, "TEMPLATES_DIR", data / "templates")
    return data


class FakeMss:
    def __init__(self):
        self.closed = False

    def grab(self, monitor):
        raise RuntimeError("test phải tự thay _grab_shop")

    def close(self):
        self.closed = True


@pytest.fixture
def clicks(monkeypatch):
    """Danh sách các lần click mua (đã chặn click thật)."""
    recorded = []
    monkeypatch.setattr(sc, "buy_slot_async", lambda center: recorded.append(center))
    return recorded


@pytest.fixture
def foreground(monkeypatch):
    """Điều khiển trạng thái 'game đang ở foreground': foreground['value'] = True/False."""
    state = {"value": True}
    monkeypatch.setattr(sc, "is_game_foreground", lambda names: state["value"])
    return state


@pytest.fixture
def make_scanner(monkeypatch, clicks, foreground):
    """Tạo ShopScanner với mss giả; mặc định bật bắt theo tên (cần ít nhất 1 chế độ để start())."""
    monkeypatch.setattr(sc.mss, "MSS", lambda: FakeMss())

    def factory(**overrides):
        kwargs = dict(
            shop_region=REGION,
            slot_centers=CENTERS,
            templates={},
            target_names=["Vex"],
            detect_by_image=False,
            detect_by_name=True,
            scan_interval_ms=0,
        )
        kwargs.update(overrides)
        return sc.ShopScanner(**kwargs)

    return factory
