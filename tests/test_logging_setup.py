import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

import pytest

from core import config, logging_setup


@pytest.fixture
def clean_logging(tmp_path, monkeypatch):
    """Cô lập logger 'tftbuy' và hai hook lỗi toàn cục; trả về thư mục data tạm."""
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "TEMPLATES_DIR", data / "templates")
    logger = logging_setup.logger
    saved = (list(logger.handlers), logger.level, sys.excepthook, threading.excepthook)
    for h in list(logger.handlers):
        logger.removeHandler(h)
    yield data
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    for h in saved[0]:
        logger.addHandler(h)
    logger.setLevel(saved[1])
    sys.excepthook, threading.excepthook = saved[2], saved[3]


def _flush():
    for h in logging_setup.logger.handlers:
        h.flush()


def test_setup_creates_log_file_with_startup_line(clean_logging):
    assert logging_setup.setup_logging() is True
    _flush()
    text = (clean_logging / "app.log").read_text(encoding="utf-8")
    assert "INFO === TFT Auto Buy khởi động ===" in text


def test_line_format_has_timestamp_and_level(clean_logging):
    logging_setup.setup_logging()
    logging_setup.logger.warning("xin chào đây là cảnh báo")
    _flush()
    line = [ln for ln in (clean_logging / "app.log").read_text(encoding="utf-8").splitlines() if "cảnh báo" in ln][0]
    assert line[4] == "-" and line[10] == " " and " WARNING xin chào" in line


def test_calling_twice_attaches_one_handler_only(clean_logging):
    assert logging_setup.setup_logging() is True
    assert logging_setup.setup_logging() is True
    handlers = [h for h in logging_setup.logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    _flush()
    assert (clean_logging / "app.log").read_text(encoding="utf-8").count("khởi động") == 1


def test_rotation_limits_are_configured(clean_logging):
    logging_setup.setup_logging()
    h = next(h for h in logging_setup.logger.handlers if isinstance(h, RotatingFileHandler))
    assert h.maxBytes == logging_setup.MAX_BYTES and h.backupCount == logging_setup.BACKUP_COUNT
    assert h.encoding == "utf-8"


def test_rotation_really_happens_and_keeps_bounded_backups(clean_logging, monkeypatch):
    monkeypatch.setattr(logging_setup, "MAX_BYTES", 2000)
    logging_setup.setup_logging()
    for i in range(200):
        logging_setup.logger.info("dòng log số %d %s", i, "x" * 50)
    _flush()
    names = sorted(p.name for p in clean_logging.glob("app.log*"))
    assert names == ["app.log", "app.log.1", "app.log.2"]  # BACKUP_COUNT = 2, không phình vô hạn


def test_unwritable_data_dir_returns_false_and_app_continues(clean_logging, monkeypatch):
    def deny():
        raise PermissionError("chỉ đọc")

    monkeypatch.setattr(config, "ensure_dirs", deny)
    before = (sys.excepthook, threading.excepthook)
    assert logging_setup.setup_logging() is False
    assert not logging_setup.logger.handlers
    assert (sys.excepthook, threading.excepthook) == before  # không móc hook khi không có nơi ghi


def test_uncaught_exception_is_logged_and_still_reported_to_default_hook(clean_logging, monkeypatch):
    forwarded = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: forwarded.append(a[0]))
    logging_setup.setup_logging()
    try:
        raise ValueError("lỗi demo chưa bắt")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    _flush()
    text = (clean_logging / "app.log").read_text(encoding="utf-8")
    assert "CRITICAL Lỗi chưa bắt" in text and "ValueError: lỗi demo chưa bắt" in text and "Traceback" in text
    assert forwarded == [ValueError]


def test_exception_in_background_thread_is_logged_with_thread_name(clean_logging):
    logging_setup.setup_logging()

    def work():
        raise RuntimeError("thread hỏng demo")

    t = threading.Thread(target=work, name="luong-quet-demo")
    t.start()
    t.join()
    _flush()
    text = (clean_logging / "app.log").read_text(encoding="utf-8")
    assert "CRITICAL Lỗi chưa bắt trong thread luong-quet-demo" in text and "RuntimeError: thread hỏng demo" in text


def test_thread_hook_handles_missing_thread_object(clean_logging):
    logging_setup.setup_logging()
    args = threading.ExceptHookArgs((RuntimeError, RuntimeError("x"), None, None))
    threading.excepthook(args)
    _flush()
    assert "trong thread ?" in (clean_logging / "app.log").read_text(encoding="utf-8")


def test_logger_level_is_info_so_debug_is_dropped(clean_logging):
    logging_setup.setup_logging()
    assert logging_setup.logger.level == logging.INFO
    logging_setup.logger.debug("chi tiết-vụn-vặt")
    _flush()
    assert "chi tiết-vụn-vặt" not in (clean_logging / "app.log").read_text(encoding="utf-8")
