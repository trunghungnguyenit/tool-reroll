"""Bộ lọc trong pytest.ini phải biến cảnh báo deprecated của mss thành lỗi. Test này cố ý KHÔNG có fixture nào tự đặt
bộ lọc cảnh báo, nên chỉ thấy tác dụng của pytest.ini. Cảnh báo được ném trước khi mss tạo gì nên không cần màn hình."""

import warnings

import mss
import pytest


def test_ini_filter_turns_mss_deprecation_into_an_error():
    with pytest.raises(DeprecationWarning, match="mss.mss is deprecated"):
        mss.mss()


def test_ini_filter_does_not_swallow_unrelated_warnings():
    """Chỉ cảnh báo nhắc tới mss mới thành lỗi; cảnh báo deprecated của thư viện khác không bị ảnh hưởng."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warnings.warn("somelib.old is deprecated", DeprecationWarning)
    assert len(caught) == 1
