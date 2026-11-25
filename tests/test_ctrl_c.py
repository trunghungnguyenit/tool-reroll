"""Ctrl+C trong terminal phải đóng app sạch, không in traceback KeyboardInterrupt rồi chạy tiếp."""

import signal
import types

import pytest

from ui.app import install_ctrl_c_quit


@pytest.fixture
def restore_sigint():
    previous = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, previous)


def test_sigint_closes_the_window_instead_of_raising_keyboard_interrupt(qapp, restore_sigint):
    closed = []
    tick = install_ctrl_c_quit(types.SimpleNamespace(close=lambda: closed.append(1)))
    try:
        signal.raise_signal(signal.SIGINT)  # không được ném KeyboardInterrupt
        assert closed == [1]
    finally:
        tick.stop()


def test_a_timer_keeps_the_event_loop_waking_python_for_signals(qapp, restore_sigint):
    tick = install_ctrl_c_quit(types.SimpleNamespace(close=lambda: None))
    try:
        assert tick.isActive() and 0 < tick.interval() <= 500
    finally:
        tick.stop()
