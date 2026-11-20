"""Bật DPI-aware cho tiến trình — để tọa độ Tk (kéo chọn vùng, đặt điểm click), mss (chụp màn hình)
và SetCursorPos (click) đều là pixel vật lý. Không có bước này, ở scale 125%/150% Tk báo tọa độ ảo
(vd 1536x864) trong khi mss/click dùng pixel thật (1920x1080) → vùng shop và điểm click lệch."""

import ctypes

_PER_MONITOR_AWARE_V2 = -4


def enable_dpi_awareness() -> bool:
    """
    Gọi 1 lần ngay khi khởi động, TRƯỚC khi tạo cửa sổ Tk (và trước khi mss chụp lần đầu).
    Trả True nếu đặt thành công; False nếu không đặt được (vd đã được đặt từ trước bởi manifest).
    """
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(_PER_MONITOR_AWARE_V2)):
            return True
    except (AttributeError, OSError):  # Windows cũ không có API này
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:  # 0 = S_OK
            return True
    except (AttributeError, OSError):
        pass
    try:
        return bool(user32.SetProcessDPIAware())
    except (AttributeError, OSError):
        return False
