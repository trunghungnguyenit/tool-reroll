"""Hộp thoại 'Cần Key xác thực': hiện Mã máy để gửi cho người bán, nhận Key dán vào và kích hoạt."""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from core import license as lic
from core.single_instance import APP_TITLE
from ui import theme


class LicenseDialog(QDialog):
    """`activate` nhận chuỗi Key, ném lic.LicenseError (tiếng Việt) nếu không dùng được. Đóng hộp thoại = không kích hoạt."""

    def __init__(self, machine_code: str, activate: Callable[[str], object], notice: str = "", parent=None):
        super().__init__(parent)
        self._activate = activate
        self._palette = theme.pick("auto")
        self.setWindowTitle(APP_TITLE)  # cùng tiêu đề cửa sổ chính để bản chạy thứ hai tìm thấy và đưa lên trước
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        title = QLabel("Cần Key xác thực")
        title.setStyleSheet("font-size: 15pt; font-weight: 600;")
        intro = QLabel("Bản này chỉ chạy khi có Key cấp riêng cho máy của bạn. Làm theo 2 bước:")
        intro.setWordWrap(True)

        step1 = QLabel("1. Gửi Mã máy này cho người bán để nhận Key:")
        self.code_edit = QLineEdit(machine_code)
        self.code_edit.setObjectName("machine_code")
        self.code_edit.setReadOnly(True)
        self.copy_btn = QPushButton("Sao chép")
        self.copy_btn.setObjectName("copy_code")
        self.copy_btn.clicked.connect(self._copy)
        code_row = QHBoxLayout()
        code_row.addWidget(self.code_edit, 1)
        code_row.addWidget(self.copy_btn)

        step2 = QLabel("2. Dán Key nhận được vào ô dưới (Key chỉ có hiệu lực 24 giờ kể từ lúc cấp, dùng một lần):")
        step2.setWordWrap(True)
        self.key_edit = QPlainTextEdit()
        self.key_edit.setObjectName("key_input")
        self.key_edit.setPlaceholderText("Dán Key vào đây")
        self.key_edit.setFixedHeight(84)

        self.status = QLabel(notice)
        self.status.setObjectName("license_status")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {self._palette.fail};")
        self.status.setVisible(bool(notice))

        self.activate_btn = QPushButton("Kích hoạt")
        self.activate_btn.setObjectName("activate")
        self.activate_btn.setDefault(True)
        self.activate_btn.clicked.connect(self._try_activate)
        self.quit_btn = QPushButton("Thoát")
        self.quit_btn.setObjectName("quit")
        self.quit_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.quit_btn)
        buttons.addWidget(self.activate_btn)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        for item in (title, intro, step1):
            layout.addWidget(item)
        layout.addLayout(code_row)
        layout.addWidget(step2)
        layout.addWidget(self.key_edit)
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        self.key_edit.setFocus()

    def _copy(self):
        QApplication.clipboard().setText(self.code_edit.text())
        self.copy_btn.setText("Đã chép ✓")

    def _show_error(self, text: str):
        self.status.setText(text)
        self.status.setVisible(True)

    def _try_activate(self):
        text = self.key_edit.toPlainText().strip()
        if not text:
            self._show_error("Hãy dán Key vào ô phía trên.")
            return
        try:
            self._activate(text)
        except lic.LicenseError as e:
            self._show_error(str(e))
            return
        self.accept()


def ensure_license() -> bool:
    """True nếu máy đã có giấy phép hợp lệ (hoặc vừa kích hoạt xong). False thì app phải thoát."""
    status = lic.check_installed()
    if status.ok:
        return True
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(theme.stylesheet(theme.pick("auto")))
    try:
        code = lic.machine_code()
    except lic.LicenseError as e:
        QMessageBox.critical(None, APP_TITLE, str(e))
        return False
    dialog = LicenseDialog(code, lic.activate, notice="" if status.missing else status.reason)
    return dialog.exec() == QDialog.DialogCode.Accepted
