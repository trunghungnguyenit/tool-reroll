"""Chốt chặn tĩnh: mss.mss() đã deprecated từ mss 10.2.0 ("will be removed in a future release"). Quét bằng AST nên
không bị lừa bởi chú thích hay chuỗi, và chạy được cả trên máy không có màn hình."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# test_warning_filter.py CỐ Ý gọi mss.mss() để chứng minh bộ lọc trong pytest.ini biến cảnh báo thành lỗi.
_INTENTIONAL = {"test_warning_filter.py"}
SOURCES = [
    ROOT / "main.py",
    *sorted((ROOT / "core").glob("*.py")),
    *sorted((ROOT / "ui").glob("*.py")),
    *(p for p in sorted((ROOT / "tests").glob("*.py")) if p.name not in _INTENTIONAL),
]


def mss_attribute_uses(tree: ast.AST):
    """Các nút `mss.<tên>` (Attribute trên Name 'mss'): trả (dòng, tên)."""
    return [
        (node.lineno, node.attr)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "mss"
    ]


def deprecated_uses(tree: ast.AST):
    found = [(line, "mss.mss") for line, attr in mss_attribute_uses(tree) if attr == "mss"]
    for node in ast.walk(tree):  # from mss import mss
        if isinstance(node, ast.ImportFrom) and node.module == "mss":
            found += [(node.lineno, "from mss import mss") for a in node.names if a.name == "mss"]
    return found


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_deprecated_mss_factory(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assert deprecated_uses(tree) == [], f"{path.name} còn dùng mss.mss() — đổi thành mss.MSS()"


@pytest.mark.parametrize("name", ["scanner.py", "preview.py"])
def test_screen_capture_modules_use_mss_class(name):
    """Hai nơi chụp màn hình phải dùng mss.MSS (không chỉ là 'không dùng mss.mss')."""
    tree = ast.parse((ROOT / "core" / name).read_text(encoding="utf-8"))
    assert "MSS" in {attr for _, attr in mss_attribute_uses(tree)}


class TestScannerItself:
    """Đảm bảo bộ quét chính nó bắt được vi phạm (không phải test rỗng)."""

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("import mss\nsct = mss.mss()", 1),
            ("import mss\nwith mss.mss() as s: pass", 1),
            ("from mss import mss\n", 1),
            ("import mss\nsct = mss.MSS()", 0),
            ('import mss\n# mss.mss() chỉ là chú thích\nx = "mss.mss()"', 0),
        ],
    )
    def test_detection(self, code, expected):
        assert len(deprecated_uses(ast.parse(code))) == expected
