"""Chụp màn hình vùng shop và tạo ảnh xem trước có đánh dấu điểm click.

Thiết kế: đĩa chỉ giữ ảnh chụp SẠCH (không viền, không chấm). Viền và chấm đỏ được vẽ lên mỗi lần hiển thị theo điểm click
HIỆN TẠI. Trước đây ảnh đã vẽ chấm được lưu rồi đọc lại làm ảnh dự phòng, nên chấm cũ không bao giờ biến mất (đổi điểm
click mà chụp lỗi thì ảnh có cả hai bộ chấm) và chấm bị vẽ chồng lên chính nó. Ghi file nguyên tử, vì hai thread ghi
đồng thời từng cho người đọc thấy ảnh ghi dở (đo thật: 77/600 lần đọc)."""

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import cv2
import mss
import numpy as np
from PIL import Image, ImageDraw

from core import config as _config

_write_lock = threading.Lock()
_REPLACE_TRIES = 12  # trên Windows os.replace báo PermissionError nếu luồng khác đang mở file đích để đọc
_REPLACE_WAIT_S = 0.01


def _replace_with_retry(src, dst) -> None:
    """os.replace có thử lại: người đọc giữ file rất ngắn (vài ms) nên chờ chút là thay được."""
    for attempt in range(_REPLACE_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_TRIES - 1:
                raise
            time.sleep(_REPLACE_WAIT_S * (attempt + 1))


def capture_shop_region(region: dict) -> np.ndarray | None:
    """Chụp ảnh màn hình đúng vùng shop đã cấu hình (left, top, width, height)."""
    try:
        with mss.MSS() as sct:
            shot = sct.grab(
                {
                    "left": region["left"],
                    "top": region["top"],
                    "width": region["width"],
                    "height": region["height"],
                }
            )
            return np.array(shot)[:, :, :3]
    except Exception:
        return None


def save_capture(frame: np.ndarray) -> None:
    """Ghi ảnh chụp sạch ra đĩa nguyên tử (file tạm riêng cho từng thread rồi thay thế). Xóa ảnh preview kiểu cũ."""
    ok, buf = cv2.imencode(".png", frame)
    if not ok:
        raise OSError("không mã hóa được ảnh chụp")
    _config.ensure_dirs()
    path = _config.SHOP_CAPTURE_PATH
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        buf.tofile(str(tmp))
        with _write_lock:  # os.replace tự nguyên tử; khóa chỉ để thứ tự ghi rõ ràng
            _replace_with_retry(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    # Ảnh preview kiểu cũ đã vẽ sẵn chấm (và là ảnh chụp màn hình): bỏ đi để không ai đọc nhầm.
    _config.LEGACY_SHOP_PREVIEW_PATH.unlink(missing_ok=True)


def _read_bytes_with_retry(path) -> np.ndarray:
    """Đọc file; PermissionError tạm thời (đúng lúc file đang được thay thế) thì thử lại vài lần. Thiếu file → ném ngay."""
    for attempt in range(_REPLACE_TRIES):
        try:
            return np.fromfile(str(path), dtype=np.uint8)
        except PermissionError:
            if attempt == _REPLACE_TRIES - 1:
                raise
            time.sleep(_REPLACE_WAIT_S * (attempt + 1))
    raise AssertionError("không tới được đây")


def load_capture() -> tuple[np.ndarray, datetime] | None:
    """Đọc ảnh chụp sạch đã lưu và thời điểm chụp; None nếu chưa có hoặc không đọc được."""
    path = _config.SHOP_CAPTURE_PATH
    try:
        data = _read_bytes_with_retry(path)
        if data.size == 0:  # file rỗng: cv2.imdecode ném cv2.error thay vì trả None
            return None
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        stamp = datetime.fromtimestamp(path.stat().st_mtime)
    except (OSError, ValueError, cv2.error):
        return None
    return (frame, stamp) if frame is not None else None


def annotate_preview(frame: np.ndarray, region: dict | None, slot_centers: list | None) -> Image.Image:
    """Ảnh hiển thị = ảnh chụp sạch + viền xanh + chấm đỏ đánh số tại 5 điểm click. Không đụng tới `frame`."""
    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)

    w, h = pil.size
    draw.rectangle([0, 0, w - 1, h - 1], outline="#22c55e", width=2)

    if slot_centers and region:
        left, top = region["left"], region["top"]
        r = max(4, min(w, h) // 25)
        for i, center in enumerate(slot_centers):
            rx, ry = center[0] - left, center[1] - top
            if not (0 <= rx < w and 0 <= ry < h):
                continue  # điểm nằm ngoài ảnh: không vẽ (đã có cảnh báo riêng khi bắt đầu quét)
            draw.ellipse([rx - r, ry - r, rx + r, ry + r], fill="#ef4444", outline="#ffffff", width=1)
            draw.text((rx + r + 2, ry - r - 2), str(i + 1), fill="#fbbf24")
    return pil


@dataclass
class PreviewResult:
    image: Image.Image | None  # None: không có ảnh nào để hiển thị
    live: bool  # True: vừa chụp xong; False: ảnh đã lưu lần trước
    note: str = ""  # giải thích cho người dùng (rỗng nếu không cần)
    captured_at: datetime | None = None


def build_shop_preview(region: dict, slot_centers: list | None = None, capture_live: bool = True) -> PreviewResult:
    """
    capture_live=True: chụp mới, lưu ảnh sạch, hiển thị. Chụp lỗi thì hiện ảnh sạch lần trước (vẽ lại chấm theo điểm
    click hiện tại) kèm ghi chú. capture_live=False (lúc mở app): chỉ hiển thị ảnh đã lưu nếu còn khớp kích thước vùng.
    """
    frame = capture_shop_region(region) if capture_live else None
    if frame is not None:
        note = ""
        try:
            save_capture(frame)
        except OSError as e:  # lưu lỗi vẫn hiển thị được ảnh vừa chụp
            note = f"Không lưu được ảnh ra đĩa ({type(e).__name__})."
        return PreviewResult(annotate_preview(frame, region, slot_centers), True, note, datetime.now())

    saved = load_capture()
    if saved is None:
        why = "Không chụp được màn hình và chưa có ảnh nào được lưu." if capture_live else ""
        return PreviewResult(None, False, why)
    old, stamp = saved
    if old.shape[:2] != (region["height"], region["width"]):  # ảnh của vùng shop khác (đã chọn lại vùng)
        why = "Không chụp được màn hình; ảnh đã lưu thuộc vùng Shop khác nên không hiển thị." if capture_live else ""
        return PreviewResult(None, False, why)
    note = "Không chụp được màn hình — đang hiện ảnh lần trước." if capture_live else "Ảnh chụp lần trước."
    return PreviewResult(annotate_preview(old, region, slot_centers), False, note, stamp)
