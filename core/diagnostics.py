"""Chẩn đoán môi trường cho Nhật ký: tool/game chạy quyền gì, cửa sổ game ở đâu, vùng Shop có nằm trong cửa sổ game không.

Vì sao: 'click mà game không nhận' hầu như luôn do một trong ba thứ — game chạy quyền Admin còn tool thì không (Windows chặn
chuột/phím giả lập), vùng Shop nằm sai màn hình/cửa sổ, hoặc tool không nhận ra cửa sổ game. Ba thứ này không thấy được từ
bên ngoài nên được ghi thẳng vào Nhật ký lúc bắt đầu quét và mỗi khi tool nghi click không có tác dụng."""

from core import game_window as gw

_REGION_TOLERANCE_PX = 4  # cửa sổ game có viền/bóng: cho lệch chừng này mà vẫn coi là 'nằm trong'
SLOT_COUNT = 5
ALIGN_WARN_FRACTION = 0.25  # điểm click lệch tâm ô chia đều quá chừng này bề rộng ô → vùng Shop không khớp 5 thẻ


def _elevation_text(elevation: str) -> str:
    return {
        gw.ELEV_YES: "quyền Admin",
        gw.ELEV_NO: "quyền thường",
        gw.ELEV_DENIED: "không đọc được quyền (thường là quyền CAO HƠN tool)",
    }.get(elevation, "không rõ quyền")


def region_inside_window(region: dict, rect: tuple[int, int, int, int], tol: int = _REGION_TOLERANCE_PX) -> bool:
    """Vùng Shop (left/top/width/height) nằm trọn trong hình chữ nhật cửa sổ (trái, trên, phải, dưới)?"""
    left, top, right, bottom = rect
    return (
        region["left"] >= left - tol and region["top"] >= top - tol
        and region["left"] + region["width"] <= right + tol and region["top"] + region["height"] <= bottom + tol
    )


def slot_alignment_lines(region: dict | None, centers: list | None) -> list[str]:
    """Vùng Shop có khớp đúng 5 thẻ không? Tool chia ĐỀU vùng thành 5 ô rồi OCR dải tên của từng ô; 5 điểm click là tâm 5 thẻ thật.
    Nếu vùng gồm cả nút Buy XP/Reroll bên trái (hay chừa thừa hai bên) thì tâm ô chia đều lệch xa tâm thẻ: dải tên bị cắt hoặc
    dính tên thẻ bên cạnh → đọc sai/bỏ sót tướng, và có thể click nhầm thẻ. Trả [] nếu khớp (hoặc thiếu dữ liệu để kiểm tra)."""
    if not region or not centers or len(centers) != SLOT_COUNT or region.get("width", 0) <= 0:
        return []
    slot_w = region["width"] / SLOT_COUNT
    offsets = [(cx - region["left"]) - (i + 0.5) * slot_w for i, (cx, _cy) in enumerate(centers)]
    bad = [(i + 1, d) for i, d in enumerate(offsets) if abs(d) > ALIGN_WARN_FRACTION * slot_w]
    if not bad:
        return []
    worst_i, worst = max(bad, key=lambda b: abs(b[1]))
    lines = [
        f"Cảnh báo: vùng Shop KHÔNG khớp 5 thẻ tướng — điểm click ô {worst_i} lệch {worst:+.0f} px so với tâm ô (mỗi ô rộng {slot_w:.0f} px; "
        f"ô lệch: {', '.join(str(i) for i, _ in bad)}). Dải tên bị cắt hoặc dính tên thẻ bên cạnh nên có thể đọc sai/bỏ sót tướng "
        "và click nhầm thẻ. Hãy chọn lại 'Vùng Shop' CHỈ gồm 5 thẻ (từ mép trái thẻ 1 tới mép phải thẻ 5; không gồm nút Buy XP/Reroll "
        "bên trái và thanh vàng/cấp phía trên), rồi đặt lại 5 điểm click."
    ]
    pitch = (centers[-1][0] - centers[0][0]) / (SLOT_COUNT - 1)
    if pitch > 0:
        left = round(centers[0][0] - pitch / 2)
        lines.append(
            f"Gợi ý theo 5 điểm click: mép trái vùng ≈ {left}, rộng ≈ {round(pitch * SLOT_COUNT)} px "
            f"(hiện tại: trái {region['left']}, rộng {region['width']}). Bấm 'Làm mới ảnh' để kiểm tra 5 thẻ nằm đều trong ảnh."
        )
    return lines


def environment_lines(
    game: "gw.GameWindow | None", tool_elevation: str, region: dict | None, centers: list | None = None
) -> list[str]:
    """Các dòng Nhật ký mô tả môi trường. Dòng bắt đầu bằng 'Cảnh báo:' là điều cần xử lý."""
    lines = [f"Chẩn đoán: tool đang chạy {_elevation_text(tool_elevation)}."]
    lines += slot_alignment_lines(region, centers)
    if game is None:
        lines.append(
            "Chẩn đoán: chưa thấy cửa sổ game (League of Legends.exe, TFTClient-Win64-Shipping.exe hoặc lớp RiotWindowClass). Vào game rồi quét tiếp, tool sẽ tự nhận."
        )
        return lines

    left, top, right, bottom = game.rect
    lines.append(
        f"Chẩn đoán: game = {game.process or 'không đọc được tên process'} (lớp {game.cls or '?'}), cửa sổ "
        f"{right - left}×{bottom - top} tại ({left}, {top}), {_elevation_text(game.elevation)}."
    )

    tool_is_admin = tool_elevation == gw.ELEV_YES
    if not tool_is_admin and game.elevation in (gw.ELEV_YES, gw.ELEV_DENIED):
        lines.append(
            "Cảnh báo: game có vẻ chạy quyền cao hơn tool — Windows chặn click và phím giả lập từ app quyền thường tới game. "
            "Hãy tắt tool rồi mở lại bằng chuột phải → Run as administrator."
        )
    elif not tool_is_admin and game.elevation == gw.ELEV_UNKNOWN:
        lines.append(
            "Chẩn đoán: không đọc được quyền của game (có thể Vanguard chặn). Nếu click không ăn, thử chạy tool bằng quyền Administrator."
        )

    if region and not region_inside_window(region, game.rect):
        lines.append(
            f"Cảnh báo: vùng Shop ({region['left']}, {region['top']}, {region['width']}×{region['height']}) KHÔNG nằm trong cửa sổ "
            f"game ({left}, {top}, {right}, {bottom}) — chọn lại vùng Shop và 5 điểm click trên đúng màn hình đang chơi game."
        )
    return lines


def collect_environment(process_names: frozenset[str], region: dict | None, centers: list | None = None) -> list[str]:
    """Đọc Win32 rồi trả các dòng chẩn đoán (environment_lines)."""
    return environment_lines(gw.find_game_window(process_names), gw.tool_elevation(), region, centers)
