"""Điểm vào của ứng dụng Qt: khóa một-bản-chạy, ghi log, dựng QApplication + cửa sổ chính."""

import sys
import traceback

from core.logging_setup import logger, setup_logging
from core.single_instance import APP_TITLE, acquire_instance_lock, activate_existing_window


def _show_already_running_notice():
    """Không tìm thấy cửa sổ của bản đang chạy (đang treo, hoặc chạy ở phiên khác): giải thích thay vì im lặng."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.information(
            None, APP_TITLE,
            "TFT Auto Buy đang chạy rồi (có thể đang khởi động).\n\n"
            "Nếu không thấy cửa sổ, hãy tắt tiến trình TFT Auto Buy trong Task Manager rồi mở lại.",
        )
        del app
    except Exception:
        pass  # exe không có console: không còn cách báo nào khác


def make_controller(notify, post):
    import keyboard

    from core.controller import AppController

    return AppController(notify, post=post, keyboard=keyboard)


def install_ctrl_c_quit(window):
    """Ctrl+C trong cửa sổ terminal (chạy bằng run.bat / python main.py) phải đóng app sạch (closeEvent → dừng quét, trả phím).
    Mặc định vòng lặp sự kiện Qt chặn tín hiệu, và KeyboardInterrupt nổ ngay trong một slot: PySide chỉ in traceback rồi chạy tiếp
    nên app không tắt (phải bấm nhiều lần). Trả QTimer giữ vòng lặp thỉnh thoảng trả quyền cho Python xử lý tín hiệu; người gọi
    phải giữ tham chiếu tới nó tới khi app thoát."""
    import signal

    from PySide6.QtCore import QTimer

    signal.signal(signal.SIGINT, lambda *_: window.close())
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(200)
    return tick


def _run_gui() -> int:
    from PySide6.QtWidgets import QApplication

    from core.dpi import enable_dpi_awareness
    from ui.license_dialog import ensure_license
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    enable_dpi_awareness()  # Qt đã tự đặt per-monitor; gọi lại vô hại
    if not ensure_license():  # chưa có Key hợp lệ cho máy này thì không dựng cửa sổ chính
        return 0
    window = MainWindow(make_controller)
    window.show()
    keep_alive = install_ctrl_c_quit(window)  # noqa: F841 — giữ QTimer sống tới khi app thoát
    return app.exec()


def _show_error(err: str):
    from PySide6.QtWidgets import QApplication, QMessageBox

    QApplication.instance() or QApplication(sys.argv)
    QMessageBox.critical(None, "TFT Auto Buy — Lỗi", err)


def run_app() -> int:
    """Chỉ cho một bản chạy; bản thứ hai đưa cửa sổ cũ lên trước rồi thoát (mã thoát 0)."""
    if acquire_instance_lock() is None:
        if not activate_existing_window():
            _show_already_running_notice()
        return 0

    setup_logging()  # sau khi giữ khóa: bản thứ hai không đụng vào app.log của bản đang chạy
    try:
        return _run_gui()
    except Exception:
        err = traceback.format_exc()
        logger.critical("Lỗi khởi động/chạy app:\n%s", err)
        try:
            _show_error(err)
        except Exception:
            raise
        return 1
