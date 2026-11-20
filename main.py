"""
TFT Auto Buy — điểm vào.
Chạy: python main.py (cần quyền Admin để dùng phím tắt toàn cục).
Giao diện nằm trong ui/, điều phối trong core/controller.py.
"""

import sys

if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:  # kiểm tra đóng gói, không mở giao diện, không cần khóa một-bản-chạy
        from core.selftest import run_selftest

        sys.exit(run_selftest())
    from ui.app import run_app

    sys.exit(run_app())
