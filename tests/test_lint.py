"""Chốt chặn chống mã chết / lỗi lặt vặt tái phát: chạy ruff trên toàn dự án (cấu hình ở ruff.toml: chỉ bắt lỗi thật như
import thừa, biến thừa, tên biến mơ hồ, bare except; KHÔNG ép giới hạn độ dài dòng hay phong cách). Tự bỏ qua nếu chưa cài ruff
(pip install -r requirements-dev.txt)."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None, reason="chưa cài ruff (pip install -r requirements-dev.txt)"
)


def ruff(*args, cwd=ROOT):
    return subprocess.run(
        [sys.executable, "-m", "ruff", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120
    )


def check_source(tmp_path, source: str):
    """Chạy đúng cấu hình của dự án trên một file mẫu nằm ngoài dự án."""
    f = tmp_path / "sample.py"
    f.write_text(source, encoding="utf-8")
    return ruff("check", str(f), "--config", str(ROOT / "ruff.toml"), "--no-cache", "--output-format", "concise", cwd=tmp_path)


def test_whole_project_is_lint_clean():
    r = ruff("check", ".", "--no-cache", "--output-format", "concise")
    assert r.returncode == 0, "ruff phát hiện vấn đề:\n" + r.stdout + r.stderr


class TestConfigActuallyCatchesDeadCode:
    """Chứng minh bộ lọc có tác dụng (nếu không, test trên có thể xanh vì cấu hình quá lỏng)."""

    def test_unused_import(self, tmp_path):
        r = check_source(tmp_path, "import os\n\nVALUE = 1\n")
        assert r.returncode != 0 and "F401" in r.stdout

    def test_unused_local_variable(self, tmp_path):
        r = check_source(tmp_path, "def f():\n    unused = 1\n    return 2\n")
        assert r.returncode != 0 and "F841" in r.stdout

    def test_undefined_name(self, tmp_path):
        r = check_source(tmp_path, "def f():\n    return missing_name\n")
        assert r.returncode != 0 and "F821" in r.stdout

    def test_ambiguous_variable_name(self, tmp_path):
        r = check_source(tmp_path, "items = [1]\nvalues = [l for l in items]\n")
        assert r.returncode != 0 and "E741" in r.stdout

    def test_bare_except(self, tmp_path):
        r = check_source(tmp_path, "try:\n    pass\nexcept:\n    pass\n")
        assert r.returncode != 0 and "E722" in r.stdout

    def test_comparison_with_a_literal_by_identity(self, tmp_path):
        r = check_source(tmp_path, "def f(x):\n    return x is 5\n")
        assert r.returncode != 0 and "F632" in r.stdout

    def test_import_not_at_top(self, tmp_path):
        r = check_source(tmp_path, "VALUE = 1\nimport os\n\nprint(os, VALUE)\n")
        assert r.returncode != 0 and "E402" in r.stdout

    def test_trailing_whitespace(self, tmp_path):
        r = check_source(tmp_path, "VALUE = 1   \n")
        assert r.returncode != 0 and "W291" in r.stdout


class TestConfigDoesNotEnforceStyle:
    """Quyết định của người dùng: không ép giới hạn độ dài dòng và phong cách; chỉ bắt lỗi thật."""

    def test_long_lines_are_allowed(self, tmp_path):
        long_message = "x" * 300
        r = check_source(tmp_path, f"MESSAGE = {long_message!r}\n")
        assert r.returncode == 0, r.stdout

    def test_try_except_pass_is_allowed(self, tmp_path):
        r = check_source(tmp_path, "def f():\n    try:\n        return 1\n    except ValueError:\n        pass\n")
        assert r.returncode == 0, r.stdout

    def test_clean_code_passes(self, tmp_path):
        r = check_source(tmp_path, "import os\n\nprint(os.name)\n")
        assert r.returncode == 0, r.stdout


def test_dev_requirements_list_ruff():
    lines = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    assert any(line.strip().lower().startswith("ruff") for line in lines)


def test_config_excludes_tool_and_build_folders():
    text = (ROOT / "ruff.toml").read_text(encoding="utf-8")
    assert all(name in text for name in (".claude", "build", "dist"))
