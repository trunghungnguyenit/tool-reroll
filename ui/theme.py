"""Bảng màu (token) sáng/tối và stylesheet Qt. Mọi màu trong giao diện đi qua đây nên hai chế độ luôn đồng bộ."""

from dataclasses import dataclass

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

FONT_FAMILY = "Segoe UI"


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    muted: str
    accent: str
    accent_line: str  # accent dùng cho viền/tiêu điểm (sáng hơn ở chế độ tối để đủ tương phản với nền)
    accent_text: str
    accent_soft: str
    ok: str
    warn: str
    fail: str
    log_bg: str
    # màu theo cost của tướng (1..5 gold), dùng cho dải màu trên thẻ và chip lọc
    cost: tuple[str, str, str, str, str]


LIGHT = Palette(
    name="light", bg="#f3f4f6", surface="#ffffff", surface2="#f9fafb", border="#d1d5db", text="#111827", muted="#4b5563",
    accent="#2563eb", accent_line="#2563eb", accent_text="#ffffff", accent_soft="#dbeafe", ok="#15803d", warn="#b45309", fail="#b91c1c",
    log_bg="#ffffff", cost=("#6b7280", "#15803d", "#2563eb", "#9333ea", "#b45309"),
)
DARK = Palette(
    name="dark", bg="#111827", surface="#1f2937", surface2="#273244", border="#3b4658", text="#f3f4f6", muted="#9ca3af",
    accent="#2563eb", accent_line="#60a5fa", accent_text="#ffffff", accent_soft="#1e3a5f", ok="#4ade80", warn="#fbbf24", fail="#f87171",
    log_bg="#0b1220", cost=("#9ca3af", "#4ade80", "#60a5fa", "#c084fc", "#fbbf24"),
)

TONES = {"ok": "ok", "fail": "fail", "warn": "warn", "muted": "muted"}


def tone_color(p: Palette, tone: str) -> str:
    return getattr(p, TONES.get(tone, "muted"))


def is_dark_system() -> bool:
    """Windows đang ở chế độ tối? (Qt 6.5+ báo qua styleHints)."""
    from PySide6.QtCore import Qt

    app = QApplication.instance()
    return bool(app) and app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def pick(mode: str = "auto") -> Palette:
    """mode: 'auto' theo Windows, 'light' hoặc 'dark'."""
    if mode == "dark":
        return DARK
    if mode == "light":
        return LIGHT
    return DARK if is_dark_system() else LIGHT


def qcolor(value: str, alpha: int = 255) -> QColor:
    c = QColor(value)
    c.setAlpha(alpha)
    return c


def stylesheet(p: Palette) -> str:
    return f"""
* {{ font-family: "{FONT_FAMILY}"; font-size: 10pt; color: {p.text}; }}
QMainWindow, QWidget#root {{ background: {p.bg}; }}
QWidget {{ background: transparent; }}
QToolTip {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border}; padding: 4px; }}

QFrame#topbar {{ background: {p.surface}; border-bottom: 1px solid {p.border}; }}
QLabel#title {{ font-size: 14pt; font-weight: 700; }}
QLabel[muted="true"] {{ color: {p.muted}; }}
QLabel#heading {{ font-weight: 700; font-size: 10.5pt; }}

QFrame[card="true"] {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; }}
QFrame[card="true"][attention="true"] {{ border: 2px solid {p.accent_line}; }}

QLabel[chip="true"] {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 12px; padding: 3px 10px; }}
QLabel[chip="true"][tone="ok"] {{ color: {p.ok}; border-color: {p.ok}; }}
QLabel[chip="true"][tone="warn"] {{ color: {p.warn}; border-color: {p.warn}; }}
QLabel[chip="true"][tone="fail"] {{ color: {p.fail}; border-color: {p.fail}; }}

QPushButton {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 7px 14px; min-height: 22px; }}
QPushButton:hover {{ background: {p.surface2}; border-color: {p.accent_line}; }}
QPushButton:pressed {{ background: {p.accent_soft}; }}
QPushButton:disabled {{ color: {p.muted}; background: {p.surface2}; border-color: {p.border}; }}
QPushButton:focus {{ border: 2px solid {p.accent_line}; }}
QPushButton[primary="true"] {{ background: {p.accent}; color: {p.accent_text}; border: 1px solid {p.accent_line}; font-weight: 700; }}
QPushButton[primary="true"]:hover {{ background: {p.accent}; border-color: {p.text}; }}
QPushButton[primary="true"]:disabled {{ background: {p.border}; color: {p.muted}; }}
QPushButton[running="true"] {{ background: {p.fail}; border-color: {p.fail}; color: #ffffff; }}
QPushButton[running="true"]:hover {{ background: {p.fail}; border-color: {p.text}; }}
QPushButton[blocked="true"] {{ background: {p.surface}; color: {p.text}; border: 2px dashed {p.warn}; }}

QToolButton[filter="true"] {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px; padding: 5px 12px; min-height: 20px; }}
QToolButton[filter="true"]:hover {{ border-color: {p.accent_line}; }}
QToolButton[filter="true"]:checked {{ background: {p.accent_soft}; border: 1px solid {p.accent_line}; font-weight: 600; }}
QToolButton[filter="true"]:focus {{ border: 2px solid {p.accent_line}; }}
QToolButton[section="true"] {{ border: none; font-weight: 700; padding: 4px 2px; }}

QLineEdit, QPlainTextEdit, QSpinBox {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 6px 8px;
    selection-background-color: {p.accent}; selection-color: {p.accent_text}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{ border: 2px solid {p.accent_line}; }}
QPlainTextEdit#log {{ background: {p.log_bg}; font-family: Consolas; font-size: 9pt; border-radius: 8px; }}

QListView {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 8px; outline: 0; }}
QListView:focus {{ border: 2px solid {p.accent_line}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 38px; height: 20px; border-radius: 10px; background: {p.border}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; }}
QCheckBox::indicator:focus {{ border: 2px solid {p.accent_line}; }}

QSlider::groove:horizontal {{ height: 6px; background: {p.border}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {p.accent}; width: 18px; height: 18px; margin: -6px 0; border-radius: 9px; }}

QTabBar::tab {{ background: {p.surface}; border: 1px solid {p.border}; padding: 12px 8px; min-width: 90px; }}
QTabBar::tab:selected {{ background: {p.accent_soft}; color: {p.text}; font-weight: 700; border-bottom: 3px solid {p.accent_line}; }}


QPushButton[row="true"] {{ background: transparent; border: none; border-radius: 6px; text-align: left; padding: 6px 8px; font-weight: 400; }}
QPushButton[row="true"]:hover {{ background: {p.surface2}; }}
QPushButton[row="true"][state="ok"] {{ color: {p.ok}; }}
QPushButton[row="true"][state="fail"] {{ color: {p.fail}; font-weight: 600; }}
QPushButton[row="true"][state="warn"] {{ color: {p.warn}; }}
QPushButton[step="true"] {{ text-align: left; padding: 10px 12px; font-weight: 600; }}
QLabel#preview {{ background: {p.surface2}; border: 1px dashed {p.border}; border-radius: 8px; }}
QComboBox {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 5px 8px; }}

QScrollBar:vertical {{ background: transparent; width: 12px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QSplitter::handle {{ background: {p.border}; width: 1px; }}
QScrollArea {{ border: none; }}
"""
