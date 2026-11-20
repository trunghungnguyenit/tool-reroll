"""Đăng ký phím tắt bật/tắt quét. Tách riêng để phân biệt 'phím cấu hình sai' (sửa tay config) với 'không đủ quyền'
— trước đây mọi lỗi đều bị báo nhầm thành 'chạy bằng quyền Admin'."""

DEFAULT_HOTKEY = "f8"


def register_toggle_hotkey(add_hotkey, requested: str, callback, default: str = DEFAULT_HOTKEY) -> tuple[str | None, list[str]]:
    """
    Đăng ký phím `requested`; không hợp lệ (thư viện keyboard ném ValueError) thì thử `default`.
    Lỗi khác (thường là thiếu quyền) thì dừng ngay vì đổi phím cũng vô ích.
    Trả (phím đã đăng ký hoặc None, các dòng cần ghi vào Nhật ký).
    """
    lines: list[str] = []
    for candidate in dict.fromkeys([requested, default]):
        try:
            add_hotkey(candidate, callback, suppress=False)
        except ValueError as e:
            reason = str(e.args[0]) if e.args else str(e)
            lines.append(f"Phím tắt {candidate!r} không hợp lệ ({reason[:80]}).")
            continue
        except Exception as e:
            lines.append(
                f"Không đăng ký được phím tắt {candidate!r} ({type(e).__name__}) — thử chạy app bằng quyền Admin."
            )
            return None, lines
        if candidate != requested:
            lines.append(f"Dùng phím tắt mặc định {candidate!r} thay cho {requested!r}.")
        return candidate, lines
    lines.append("Không có phím tắt nào dùng được; bấm nút BẮT ĐẦU để chạy.")
    return None, lines


def register_roll_hotkey(add_hotkey, key: str, callback, toggle_key: str | None = None) -> tuple[object | None, list[str]]:
    """
    Đăng ký phím roll của game để app quét dày ngay khi bạn roll. KHÔNG chặn phím (game vẫn nhận).
    Trả (tay cầm để gỡ phím sau này hoặc None, các dòng cần ghi vào Nhật ký). Phím rỗng = tắt tính năng (không báo gì).
    """
    key = (key or "").strip()
    if not key:
        return None, []
    if toggle_key and key.lower() == toggle_key.lower():
        return None, [f"Phím roll {key!r} trùng phím bật/tắt — bỏ qua đồng bộ phím roll."]
    try:
        handle = add_hotkey(key, callback, suppress=False)
    except ValueError as e:
        reason = str(e.args[0]) if e.args else str(e)
        return None, [f"Phím roll {key!r} không hợp lệ ({reason[:80]}) — bỏ qua đồng bộ phím roll."]
    except Exception as e:
        return None, [f"Không đăng ký được phím roll {key!r} ({type(e).__name__}) — thử chạy app bằng quyền Admin."]
    return handle, [f"Đồng bộ phím roll: {key.upper()} (quét dày ngay khi bạn roll)."]
