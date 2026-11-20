"""Ghi log ra data/app.log (xoay vòng, giới hạn kích thước). Exe build console=False nên không có nơi nào khác
để xem lỗi: traceback không bắt được, lỗi callback Tk, lỗi thread nền, và mọi dòng Nhật ký đều vào file này."""

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from core import config

LOGGER_NAME = "tftbuy"
MAX_BYTES = 512 * 1024
BACKUP_COUNT = 2

logger = logging.getLogger(LOGGER_NAME)


def setup_logging() -> bool:
    """
    Gắn file handler (gọi lại nhiều lần cũng chỉ gắn 1 lần) và móc các hook lỗi chưa bắt.
    Trả False nếu không mở được file log (vd thư mục chỉ đọc) — app vẫn chạy bình thường, chỉ không có log.
    """
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return True
    try:
        config.ensure_dirs()
        handler = RotatingFileHandler(
            config.DATA_DIR / "app.log", maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    except OSError:
        return False
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    def log_uncaught(exc_type, exc, tb):
        logger.critical("Lỗi chưa bắt", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def log_thread_uncaught(args):
        logger.critical(
            "Lỗi chưa bắt trong thread %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = log_uncaught
    threading.excepthook = log_thread_uncaught
    logger.info("=== TFT Auto Buy khởi động ===")
    return True
