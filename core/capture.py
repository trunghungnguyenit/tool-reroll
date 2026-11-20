"""Chụp vùng shop bằng DXGI Desktop Duplication (thư viện dxcam) thay cho mss.

Vì sao: mss (GDI BitBlt) mất ~10–12 ms mỗi lần chụp BẤT KỂ vùng lớn hay nhỏ (chụp 8x8 vẫn ~8 ms). DXGI lấy khung đang có trên
GPU trong ~1 ms. Mỗi lần mua còn phải chụp thêm một lần để xác nhận thẻ chưa đổi, nên đây là khoản tiết kiệm lớn nhất.

An toàn: DXGI có thể không dùng được (game fullscreen độc quyền cho khung đen, vùng trải qua nhiều màn hình, driver lỗi). Vì vậy:
  - lúc mở, so khung DXGI với ảnh mss của cùng vùng; không khớp (hoặc đen) thì KHÔNG dùng DXGI;
  - lúc chạy, cứ vài giây lại đối chiếu với mss; lệch liên tiếp thì ném CaptureMismatch để scanner quay về mss.
Mọi nhánh lỗi đều trả về lý do bằng tiếng Việt để ghi vào Nhật ký."""

import importlib
import time

import numpy as np

CHECK_EVERY_S = 3.0  # đối chiếu định kỳ khung DXGI với mss
MISMATCH_LIMIT = 2  # số lần đối chiếu lệch liên tiếp thì bỏ DXGI
SAME_MAX_DIFF = 12.0  # chênh lệch điểm ảnh trung bình (thang 0-255) vẫn coi là cùng một khung
VERIFY_SAMPLES = 4  # lúc mở: thử tối đa từng này lần (màn hình có thể đang đổi giữa hai lần chụp)
VERIFY_GAP_S = 0.025
MAX_DEVICES = 4
MAX_OUTPUTS = 8


class CaptureMismatch(Exception):
    """Khung DXGI không đáng tin (khác mss, đen, hoặc không có)."""


def mean_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    """Chênh lệch điểm ảnh trung bình 0-255 giữa hai khung (khác kích thước = lệch hoàn toàn)."""
    if a.shape != b.shape or a.size == 0:
        return 255.0
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def _is_black(frame: np.ndarray) -> bool:
    return frame.size == 0 or float(frame.mean()) < 1.0


class DxgiSource:
    name = "DXGI"

    def __init__(self, camera, local_region: tuple[int, int, int, int], reference_grab, clock=time.monotonic):
        self._cam = camera
        self._region = local_region  # (trái, trên, phải, dưới) so với góc màn hình chứa vùng shop
        self._reference = reference_grab  # () -> khung BGR của cùng vùng bằng mss
        self._clock = clock
        self._next_check = clock() + CHECK_EVERY_S
        self._bad = 0

    def grab(self) -> np.ndarray:
        """Khung mới nhất (BGR, h x w x 3). Không có khung mới thì trả khung gần nhất (màn hình đứng yên)."""
        frame = self._cam.grab(region=self._region, new_frame_only=False)
        if frame is None:
            raise CaptureMismatch("DXGI không trả về khung nào")
        now = self._clock()
        if now >= self._next_check:
            self._next_check = now + CHECK_EVERY_S
            ref = self._reference()
            if mean_abs_diff(frame, ref) > SAME_MAX_DIFF or (_is_black(frame) and not _is_black(ref)):
                self._bad += 1
                if self._bad >= MISMATCH_LIMIT:
                    raise CaptureMismatch("khung DXGI lệch so với ảnh chụp mss khi đang chạy")
            else:
                self._bad = 0
        return frame

    def close(self):
        try:
            self._cam.release()
        except Exception:
            pass


def _desktop_rect(camera) -> tuple[int, int, int, int] | None:
    """Hình chữ nhật của màn hình mà camera này chụp, theo tọa độ desktop ảo (đọc từ thuộc tính nội bộ của dxcam)."""
    try:
        c = camera._output.desc.DesktopCoordinates
        return int(c.left), int(c.top), int(c.right), int(c.bottom)
    except Exception:
        return None


def _contains(rect: tuple[int, int, int, int], region: dict) -> bool:
    left, top, right, bottom = rect
    return (
        region["left"] >= left and region["top"] >= top
        and region["left"] + region["width"] <= right and region["top"] + region["height"] <= bottom
    )


def _verify(source: DxgiSource, reference_grab, sleep=time.sleep) -> str | None:
    """None nếu khung DXGI khớp mss (thử vài lần); ngược lại là lý do không dùng DXGI."""
    best = 255.0
    black = False
    for i in range(VERIFY_SAMPLES):
        try:
            frame = source.grab()
        except CaptureMismatch as e:
            return str(e)
        ref = reference_grab()
        black = _is_black(frame) and not _is_black(ref)
        best = min(best, mean_abs_diff(frame, ref))
        if best <= SAME_MAX_DIFF and not black:
            return None
        if i + 1 < VERIFY_SAMPLES:
            sleep(VERIFY_GAP_S)
    if black:
        return "DXGI trả khung đen (thường do game ở chế độ fullscreen độc quyền; hãy dùng borderless)"
    return f"khung DXGI khác ảnh chụp mss (chênh {best:.1f}/255)"


def open_dxgi(region: dict, reference_grab, dxcam_module=None, sleep=time.sleep) -> tuple[DxgiSource | None, str]:
    """
    Mở DXGI cho `region` (pixel vật lý, tọa độ desktop ảo). Trả (nguồn, mô tả) hoặc (None, lý do không dùng được).
    Phải gọi (và dùng, và đóng) trong CÙNG MỘT luồng: DXGI/COM gắn với luồng tạo ra nó.
    """
    try:
        dx = dxcam_module or importlib.import_module("dxcam")
    except Exception as e:
        return None, f"không nạp được thư viện dxcam ({type(e).__name__})"

    camera = None
    rect = None
    try:
        for device in range(MAX_DEVICES):
            created_any = False
            for output in range(MAX_OUTPUTS):
                try:
                    cam = dx.create(device_idx=device, output_idx=output, output_color="BGR")
                except Exception:
                    break  # hết output của adapter này
                created_any = True
                r = _desktop_rect(cam)
                if r is not None and _contains(r, region):
                    camera, rect = cam, r
                    break
                try:
                    cam.release()
                except Exception:
                    pass
            if camera is not None or not created_any:
                break
    except Exception as e:
        return None, f"lỗi khi dò màn hình DXGI ({type(e).__name__}: {str(e)[:60]})"

    if camera is None:
        return None, "không có màn hình DXGI nào chứa trọn vùng Shop (vùng nằm giữa nhiều màn hình?)"

    local = (region["left"] - rect[0], region["top"] - rect[1],
             region["left"] - rect[0] + region["width"], region["top"] - rect[1] + region["height"])
    source = DxgiSource(camera, local, reference_grab)
    try:
        why = _verify(source, reference_grab, sleep)
    except Exception as e:
        why = f"{type(e).__name__}: {str(e)[:60]}"
    if why is not None:
        source.close()
        return None, why
    return source, "DXGI"
