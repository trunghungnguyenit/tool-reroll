"""Tìm vị trí 5 thẻ tướng ngay trong khung chụp vùng Shop.

Vì sao có file này: tool chia vùng Shop thành 5 cột bằng nhau rồi OCR dải tên từng cột. Nếu vùng người dùng kéo rộng hơn 5 thẻ (hay
gặp: gồm cả nút Buy XP/Reroll bên trái) thì mỗi cột chứa nửa thẻ này dính nửa thẻ kia: tên bị cắt ("uko 31 Rek'SÉ" thay vì
"Rek'Sai") nên tướng ở ô đó không bao giờ được mua. Giữa hai thẻ luôn có một khe phẳng (nền shop, vài chục cột pixel cùng màu), còn
thẻ có ảnh tướng và chữ; nhìn khe đó là tìm được ranh giới thật của từng thẻ, không phụ thuộc vùng người dùng chọn.

Hàm thuần (không đụng màn hình/Win32) để test được bằng ảnh giả."""

import cv2
import numpy as np

SLOT_COUNT = 5
# Chỉ xét dải giữa theo chiều cao (ảnh tướng + chữ đặc điểm), bỏ dải tên phía dưới (có đoạn nền trơn dễ nhầm với khe). Thử lần lượt
# từng dải: vùng Shop thừa thanh vàng/cấp phía trên thì thẻ nằm thấp hơn và dải đầu sẽ dính giao diện không phải thẻ.
BANDS = ((0.30, 0.80), (0.45, 0.80), (0.55, 0.80))
FLAT_STD = 3.0  # cột 'phẳng' (khe giữa hai thẻ): độ lệch chuẩn độ sáng dọc cột nhỏ hơn mức này
MIN_GAP_PX = 5  # khe thật phải có từng này cột phẳng liên tiếp; ngắn hơn là vùng tối trong chính thẻ
MIN_CARD_PX = 40
WIDTH_TOL = 0.12  # 5 thẻ rộng bằng nhau (lệch tối đa 12% so với trung vị)
PITCH_TOL = 0.08  # khoảng cách giữa các thẻ đều (lệch tối đa 8%)
CLICK_TOL = 0.10  # điểm click được phép lệch ra ngoài mép thẻ tối đa chừng này × bề rộng thẻ
PAD_PX = 4  # nới mỗi thẻ ra hai bên chừng này: dải nhìn thấy có thể hẹp hơn thẻ thật vài pixel, đừng làm cụt chữ đầu/cuối của tên


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Các đoạn liên tiếp mask=True dưới dạng [bắt đầu, kết thúc) ."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2])]


def _card_runs(frame: np.ndarray, band_range: tuple[float, float] = BANDS[0]) -> list[tuple[int, int]]:
    """Các đoạn cột nằm giữa hai khe phẳng (mỗi đoạn là một thẻ hoặc một khối giao diện khác)."""
    h = frame.shape[0]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    band = gray[int(h * band_range[0]) : int(h * band_range[1])].astype(np.float32)
    if band.size == 0:
        return []
    flat = band.std(axis=0) < FLAT_STD
    gap = np.zeros_like(flat)
    for a, b in _runs(flat):
        if b - a >= MIN_GAP_PX:
            gap[a:b] = True
    return [(a, b) for a, b in _runs(~gap) if b - a >= MIN_CARD_PX]


def _regular(window: list[tuple[int, int]]) -> bool:
    widths = np.array([b - a for a, b in window], dtype=float)
    starts = np.array([a for a, _ in window], dtype=float)
    pitches = np.diff(starts)
    mw, mp = float(np.median(widths)), float(np.median(pitches))
    return bool(
        np.all(np.abs(widths - mw) <= WIDTH_TOL * mw) and mp > 0 and np.all(np.abs(pitches - mp) <= PITCH_TOL * mp)
    )


def find_card_columns(
    frame: np.ndarray | None, click_xs: list[int] | None = None, count: int = SLOT_COUNT
) -> list[tuple[int, int]] | None:
    """Cột [x0, x1) của `count` thẻ trong `frame` (BGR, cắt đúng vùng Shop), hoặc None nếu không chắc.

    `click_xs`: hoành độ 5 điểm click so với mép trái khung — dùng để chọn đúng 5 thẻ khi vùng còn thừa một khối giống thẻ (nút Buy
    XP/Reroll bên trái); mỗi điểm phải nằm trong thẻ tương ứng. Không có `click_xs` mà có nhiều cách chọn thì trả None (không đoán).
    Trả None khi chưa đủ 5 thẻ rõ ràng (shop đang trống/đang hiện hiệu ứng): gọi lại ở khung sau."""
    if frame is None or frame.ndim < 2 or frame.shape[0] < 40 or frame.shape[1] < MIN_CARD_PX * count:
        return None
    for band_range in BANDS:
        runs = _card_runs(frame, band_range)
        valid = []
        for i in range(len(runs) - count + 1):
            window = runs[i : i + count]
            if not _regular(window):
                continue
            if click_xs is not None and len(click_xs) == count:
                tol = CLICK_TOL * (window[0][1] - window[0][0])
                if not all(a - tol <= x < b + tol for x, (a, b) in zip(click_xs, window)):
                    continue
            valid.append(window)
        if len(valid) == 1:
            width = frame.shape[1]
            return [(max(0, a - PAD_PX), min(width, b + PAD_PX)) for a, b in valid[0]]
    return None
