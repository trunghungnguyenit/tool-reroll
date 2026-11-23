"""Bộ cấu hình vùng Shop + 5 điểm click theo TỪNG MÀN HÌNH, và quy đổi khi màn hình đổi.

Mỗi bộ (profile) lưu trong config["monitor_profiles"][khóa màn hình] = {name, monitor, shop_region, slot_centers}; `monitor` là hình
chữ nhật của màn hình lúc lưu (pixel vật lý). Có hình chữ nhật đó thì biết được:
  - màn hình chỉ bị DỊCH chỗ (sắp xếp lại các màn hình): dịch cả bộ theo độ lệch, kết quả chính xác;
  - màn hình khác độ phân giải: ước lượng theo tỉ lệ rồi bắt người dùng xác nhận (giao diện game co giãn theo CHIỀU CAO màn hình
    và neo ở giữa-đáy, nên quy đổi theo tỉ lệ chiều cao quanh điểm giữa-đáy, không theo tỉ lệ chiều rộng).
Tất cả là hàm thuần (không đụng Win32/Qt) để test được."""

import copy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.monitors import Monitor

_RECT_KEYS = ("left", "top", "width", "height")


def make_profile(monitor: "Monitor", region: dict, centers: list) -> dict:
    return {
        "name": monitor.label(),
        "monitor": monitor.rect,
        "shop_region": {k: int(region[k]) for k in _RECT_KEYS},
        "slot_centers": [[int(x), int(y)] for x, y in centers],
    }


def valid_profile(profile) -> bool:
    """Hồ sơ đủ để dùng: có hình chữ nhật màn hình và vùng Shop hợp lệ, điểm click là rỗng hoặc đúng 5 điểm."""
    try:
        mon, reg, pts = profile["monitor"], profile["shop_region"], profile["slot_centers"]
        if not all(isinstance(mon[k], int) and not isinstance(mon[k], bool) for k in _RECT_KEYS):
            return False
        if not all(isinstance(reg[k], int) and not isinstance(reg[k], bool) for k in _RECT_KEYS):
            return False
        if mon["width"] <= 0 or mon["height"] <= 0 or reg["width"] <= 0 or reg["height"] <= 0:
            return False
        if len(pts) not in (0, 5):
            return False
        return all(len(p) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in p) for p in pts)
    except (KeyError, TypeError):
        return False


def translate(region: dict, centers: list, dx: int, dy: int) -> tuple[dict, list]:
    moved = {**region, "left": region["left"] + dx, "top": region["top"] + dy}
    return moved, [[x + dx, y + dy] for x, y in centers]


def rescale(old: dict, new: dict, region: dict, centers: list) -> tuple[dict, list]:
    """Quy đổi từ màn hình `old` sang `new` (hai hình chữ nhật vật lý): co theo chiều cao quanh điểm giữa-đáy. Kết quả bị kẹp
    vào trong màn hình mới để không bao giờ nằm ngoài màn hình."""
    s = new["height"] / old["height"]
    old_cx, old_bottom = old["left"] + old["width"] / 2, old["top"] + old["height"]
    new_cx, new_bottom = new["left"] + new["width"] / 2, new["top"] + new["height"]

    def px(x):
        return new_cx + (x - old_cx) * s

    def py(y):
        return new_bottom - (old_bottom - y) * s

    right = min(round(px(region["left"] + region["width"])), new["left"] + new["width"])
    bottom = min(round(py(region["top"] + region["height"])), new["top"] + new["height"])
    left = max(round(px(region["left"])), new["left"])
    top = max(round(py(region["top"])), new["top"])
    scaled = {"left": left, "top": top, "width": max(1, right - left), "height": max(1, bottom - top)}
    pts = []
    for x, y in centers:
        cx = min(max(round(px(x)), scaled["left"]), scaled["left"] + scaled["width"] - 1)
        cy = min(max(round(py(y)), scaled["top"]), scaled["top"] + scaled["height"] - 1)
        pts.append([cx, cy])
    return scaled, pts


def adapt(profile: dict, monitor: "Monitor") -> tuple[dict, list, str]:
    """Đem bộ đã lưu áp lên `monitor` hiện tại. Trả (vùng, điểm click, cách): 'same' (nguyên), 'moved' (chỉ dịch chỗ) hoặc
    'scaled' (khác kích thước: chỉ là ước lượng)."""
    old, region, centers = profile["monitor"], profile["shop_region"], profile["slot_centers"]
    new = monitor.rect
    if (old["width"], old["height"]) == (new["width"], new["height"]):
        dx, dy = new["left"] - old["left"], new["top"] - old["top"]
        if dx == 0 and dy == 0:
            return dict(region), [list(p) for p in centers], "same"
        moved, pts = translate(region, centers, dx, dy)
        return moved, pts, "moved"
    scaled, pts = rescale(old, new, region, centers)
    return scaled, pts, "scaled"


def nearest(profiles: dict, monitor: "Monitor") -> tuple[str, dict] | None:
    """Bộ đã lưu gần màn hình `monitor` nhất để làm gợi ý: cùng kích thước > cùng tỉ lệ khung hình > cùng thiết bị > gần diện tích."""
    best_key, best = None, None
    ratio = monitor.width / monitor.height
    for key, p in profiles.items():
        if not valid_profile(p):
            continue
        m = p["monitor"]
        score = ((m["width"], m["height"]) != (monitor.width, monitor.height),
                 round(abs(m["width"] / m["height"] - ratio), 2),
                 not key.startswith(monitor.device + "|"),
                 abs(m["width"] * m["height"] - monitor.width * monitor.height))
        if best is None or score < best:
            best_key, best = key, score
    return (best_key, copy.deepcopy(profiles[best_key])) if best_key else None
