import ctypes
from types import SimpleNamespace

import pytest

from core import dpi


class Api:
    """Một API Windows giả: gọi được, cho gán argtypes/restype, trả kết quả cấu hình sẵn hoặc ném lỗi."""

    def __init__(self, name, log, result=None, exc=None):
        self.name, self.log, self.result, self.exc = name, log, result, exc
        self.argtypes = self.restype = None

    def __call__(self, *args):
        self.log.append((self.name, args))
        if self.exc:
            raise self.exc
        return self.result


def install(monkeypatch, ctx=None, shcore=None, aware=None):
    """Mỗi tham số là (result, exc) hoặc None = API không tồn tại (AttributeError)."""
    log = []
    user32 = SimpleNamespace()
    if ctx is not None:
        user32.SetProcessDpiAwarenessContext = Api("ctx", log, *ctx)
    if aware is not None:
        user32.SetProcessDPIAware = Api("aware", log, *aware)
    sh = SimpleNamespace()
    if shcore is not None:
        sh.SetProcessDpiAwareness = Api("shcore", log, *shcore)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32, shcore=sh), raising=False)
    return log


def test_modern_api_success_stops_there(monkeypatch):
    log = install(monkeypatch, ctx=(True, None), shcore=(0, None), aware=(1, None))
    assert dpi.enable_dpi_awareness() is True
    assert [n for n, _ in log] == ["ctx"]
    assert dpi._PER_MONITOR_AWARE_V2 == -4
    assert log[0][1][0].value == ctypes.c_void_p(-4).value  # handle -4 = PER_MONITOR_AWARE_V2 (con trỏ không dấu)


def test_falls_back_to_shcore_when_context_api_refuses(monkeypatch):
    log = install(monkeypatch, ctx=(False, None), shcore=(0, None), aware=(1, None))
    assert dpi.enable_dpi_awareness() is True
    assert [n for n, _ in log] == ["ctx", "shcore"]
    assert log[1][1] == (2,)  # PROCESS_PER_MONITOR_DPI_AWARE


def test_falls_back_when_context_api_missing_on_old_windows(monkeypatch):
    log = install(monkeypatch, ctx=None, shcore=(0, None))
    assert dpi.enable_dpi_awareness() is True
    assert [n for n, _ in log] == ["shcore"]


def test_falls_back_to_legacy_when_shcore_fails(monkeypatch):
    log = install(monkeypatch, ctx=(False, None), shcore=(5, None), aware=(1, None))  # 5 = E_ACCESSDENIED
    assert dpi.enable_dpi_awareness() is True
    assert [n for n, _ in log] == ["ctx", "shcore", "aware"]


def test_oserror_in_each_api_is_swallowed(monkeypatch):
    err = OSError("boom")
    log = install(monkeypatch, ctx=(None, err), shcore=(None, err), aware=(1, None))
    assert dpi.enable_dpi_awareness() is True
    assert [n for n, _ in log] == ["ctx", "shcore", "aware"]


def test_returns_false_when_nothing_works(monkeypatch):
    install(monkeypatch, ctx=(False, None), shcore=(5, None), aware=(0, None))
    assert dpi.enable_dpi_awareness() is False


def test_returns_false_when_no_api_exists(monkeypatch):
    install(monkeypatch)
    assert dpi.enable_dpi_awareness() is False


def test_real_call_does_not_raise_and_returns_bool():
    """Trên Windows thật: không ném lỗi; trả False nếu tiến trình đã DPI-aware từ trước (không đổi lại được)."""
    assert isinstance(dpi.enable_dpi_awareness(), bool)


def test_real_process_is_per_monitor_aware_after_call():
    dpi.enable_dpi_awareness()
    user32 = ctypes.windll.user32
    try:
        get_ctx = user32.GetThreadDpiAwarenessContext
        are_equal = user32.AreDpiAwarenessContextsEqual
    except AttributeError:
        pytest.skip("Windows quá cũ")
    get_ctx.restype = ctypes.c_void_p
    are_equal.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    ctx = get_ctx()
    assert not are_equal(ctx, ctypes.c_void_p(-1))  # không phải UNAWARE
