import importlib
import shutil
import subprocess
import sys
import types
from datetime import datetime

import pytest

from core import build_info


def _stamp(monkeypatch, when="2026-11-19 16:40", commit="45ffbdc"):
    mod = types.SimpleNamespace(BUILD_TIME=when, GIT_COMMIT=commit)
    monkeypatch.setattr(build_info.importlib, "import_module", lambda name: mod)


def test_describe_clean_commit(monkeypatch):
    _stamp(monkeypatch)
    assert build_info.describe() == "build 2026-11-19 16:40 (45ffbdc)"


def test_describe_dirty_commit_says_uncommitted_changes(monkeypatch):
    _stamp(monkeypatch, commit="45ffbdc+")
    assert build_info.describe() == "build 2026-11-19 16:40 (45ffbdc, có thay đổi chưa commit)"


def test_describe_without_git_shows_only_time(monkeypatch):
    _stamp(monkeypatch, commit="")
    assert build_info.describe() == "build 2026-11-19 16:40"


def _no_stamp(monkeypatch):
    def boom(name):
        raise ImportError(name)

    monkeypatch.setattr(build_info.importlib, "import_module", boom)


def test_describe_from_source_is_dev(monkeypatch):
    _no_stamp(monkeypatch)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert build_info.describe() == "dev (chạy từ mã nguồn)"


def test_describe_old_frozen_exe_without_stamp(monkeypatch):
    _no_stamp(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert "đóng gói từ bản cũ" in build_info.describe()


def test_stamp_missing_attributes_counts_as_no_stamp(monkeypatch):
    monkeypatch.setattr(build_info.importlib, "import_module", lambda name: types.SimpleNamespace())
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert build_info.describe().startswith("dev")


def test_write_build_stamp_roundtrip(tmp_path):
    path = tmp_path / "_build_stamp.py"
    build_info.write_build_stamp(path, datetime(2026, 11, 19, 16, 40, 59), "abc1234+")
    ns = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
    assert ns["BUILD_TIME"] == "2026-11-19 16:40"
    assert ns["GIT_COMMIT"] == "abc1234+"


def test_write_build_stamp_quotes_are_safe(tmp_path):
    path = tmp_path / "s.py"
    build_info.write_build_stamp(path, datetime(2026, 1, 2, 3, 4), "x'\"y")
    ns = {}
    exec(path.read_text(encoding="utf-8"), ns)
    assert ns["GIT_COMMIT"] == "x'\"y"


def test_real_stamp_file_is_importable_through_describe(tmp_path, monkeypatch):
    pkg = tmp_path / "fakecore"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    build_info.write_build_stamp(pkg / "_build_stamp.py", datetime(2026, 5, 6, 7, 8), "deadbee")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(build_info, "STAMP_MODULE", "fakecore._build_stamp")
    importlib.invalidate_caches()
    assert build_info.describe() == "build 2026-05-06 07:08 (deadbee)"


@pytest.mark.skipif(shutil.which("git") is None, reason="không có git")
class TestGitCommit:
    def _git(self, cwd, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)

    def test_no_repo_returns_empty(self, tmp_path):
        assert build_info.git_commit(tmp_path) == ""

    def test_clean_then_dirty(self, tmp_path):
        self._git(tmp_path, "init", "-q")
        (tmp_path / "a.txt").write_text("1")
        self._git(tmp_path, "add", "a.txt")
        self._git(tmp_path, "commit", "-q", "-m", "x")
        clean = build_info.git_commit(tmp_path)
        assert clean and not clean.endswith("+")
        (tmp_path / "a.txt").write_text("2")
        assert build_info.git_commit(tmp_path) == clean + "+"

    def test_untracked_files_do_not_make_it_dirty(self, tmp_path):
        self._git(tmp_path, "init", "-q")
        (tmp_path / "a.txt").write_text("1")
        self._git(tmp_path, "add", "a.txt")
        self._git(tmp_path, "commit", "-q", "-m", "x")
        (tmp_path / "new.txt").write_text("u")
        assert not build_info.git_commit(tmp_path).endswith("+")

    def test_repo_without_commits_returns_empty(self, tmp_path):
        self._git(tmp_path, "init", "-q")
        assert build_info.git_commit(tmp_path) == ""


def test_git_missing_returns_empty(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(build_info.subprocess, "run", boom)
    assert build_info.git_commit(tmp_path) == ""


# ------------------------------------------------------------------ phiên bản 1.0.0.N
def _project(tmp_path, version=None):
    """Dự án giả có đủ loại file mà băm quan tâm (và vài file không được quan tâm)."""
    (tmp_path / "core").mkdir()
    (tmp_path / "ui").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "core" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "ui" / "w.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("print()\n", encoding="utf-8")
    (tmp_path / "TFT_Auto_Buy.spec").write_text("spec\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("mss==1\n", encoding="utf-8")
    if version:
        (tmp_path / "VERSION").write_text(version + "\n", encoding="utf-8")
    return tmp_path


class TestBumpVersion:
    def test_increments_last_number_only(self):
        assert build_info.bump_version("1.0.0.1") == "1.0.0.2"
        assert build_info.bump_version("2.3.4.9") == "2.3.4.10"  # số chứ không phải chuỗi: 9 -> 10, không phải 90
        assert build_info.bump_version("1.0.0.99") == "1.0.0.100"


class TestReadVersion:
    def test_missing_file_is_none(self, tmp_path):
        assert build_info.read_version(tmp_path) is None

    def test_valid_with_whitespace(self, tmp_path):
        (tmp_path / "VERSION").write_text("  1.2.3.4 \n\n", encoding="utf-8")
        assert build_info.read_version(tmp_path) == "1.2.3.4"

    @pytest.mark.parametrize("bad", ["", "1.0.0", "1.0.0.1.1", "v1.0.0.1", "1.0.0.x", "1,0,0,1"])
    def test_invalid_format_is_rejected_with_message(self, tmp_path, bad):
        (tmp_path / "VERSION").write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError, match="1.0.0.1"):
            build_info.read_version(tmp_path)

    def test_the_real_version_file_is_valid(self):
        assert build_info.read_version() is not None


class TestSourceHash:
    def test_same_content_same_hash(self, tmp_path):
        _project(tmp_path)
        assert build_info.source_hash(tmp_path) == build_info.source_hash(tmp_path)

    @pytest.mark.parametrize("rel", ["core/a.py", "ui/w.py", "main.py", "TFT_Auto_Buy.spec", "requirements.txt"])
    def test_changing_any_packaged_file_changes_hash(self, tmp_path, rel):
        _project(tmp_path)
        before = build_info.source_hash(tmp_path)
        (tmp_path / rel).write_text("khác\n", encoding="utf-8")
        assert build_info.source_hash(tmp_path) != before

    def test_new_module_changes_hash(self, tmp_path):
        _project(tmp_path)
        before = build_info.source_hash(tmp_path)
        (tmp_path / "core" / "b.py").write_text("z = 3\n", encoding="utf-8")
        assert build_info.source_hash(tmp_path) != before

    def test_ignored_files_do_not_change_hash(self, tmp_path):
        """Stamp sinh lúc build, test, tài liệu và cache không làm đổi exe nên không được làm tăng phiên bản."""
        _project(tmp_path)
        before = build_info.source_hash(tmp_path)
        (tmp_path / "core" / "_build_stamp.py").write_text("BUILD_TIME = 'x'\n", encoding="utf-8")
        (tmp_path / "tests" / "test_x.py").write_text("assert 1\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("doc\n", encoding="utf-8")
        (tmp_path / "core" / "__pycache__").mkdir()
        (tmp_path / "core" / "__pycache__" / "a.pyc").write_bytes(b"\0\1")
        (tmp_path / "VERSION").write_text("9.9.9.9\n", encoding="utf-8")
        assert build_info.source_hash(tmp_path) == before

    def test_line_endings_do_not_matter(self, tmp_path):
        _project(tmp_path)
        (tmp_path / "core" / "a.py").write_bytes(b"x = 1\ny = 2\n")
        lf = build_info.source_hash(tmp_path)
        (tmp_path / "core" / "a.py").write_bytes(b"x = 1\r\ny = 2\r\n")
        assert build_info.source_hash(tmp_path) == lf

    def test_renaming_a_file_changes_hash(self, tmp_path):
        _project(tmp_path)
        before = build_info.source_hash(tmp_path)
        (tmp_path / "core" / "a.py").rename(tmp_path / "core" / "c.py")
        assert build_info.source_hash(tmp_path) != before


class TestPrepareVersion:
    def test_first_build_keeps_version_and_records_hash(self, tmp_path):
        _project(tmp_path, "1.0.0.1")
        assert build_info.prepare_version(tmp_path) == "1.0.0.1"
        assert (tmp_path / ".version_hash").read_text().strip() == build_info.source_hash(tmp_path)

    def test_no_version_file_starts_at_first_version(self, tmp_path):
        _project(tmp_path)
        assert build_info.prepare_version(tmp_path) == "1.0.0.1"
        assert (tmp_path / "VERSION").read_text().strip() == "1.0.0.1"

    def test_rebuild_without_changes_keeps_version(self, tmp_path):
        _project(tmp_path, "1.0.0.1")
        build_info.prepare_version(tmp_path)
        assert build_info.prepare_version(tmp_path) == "1.0.0.1"
        assert build_info.prepare_version(tmp_path) == "1.0.0.1"

    def test_code_change_then_build_bumps_once(self, tmp_path):
        _project(tmp_path, "1.0.0.1")
        build_info.prepare_version(tmp_path)
        (tmp_path / "core" / "a.py").write_text("x = 2\n", encoding="utf-8")
        assert build_info.prepare_version(tmp_path) == "1.0.0.2"
        assert (tmp_path / "VERSION").read_text().strip() == "1.0.0.2"
        assert build_info.prepare_version(tmp_path) == "1.0.0.2"  # build lại không đổi code: giữ nguyên

    def test_successive_changes_keep_counting(self, tmp_path):
        _project(tmp_path, "1.0.0.1")
        build_info.prepare_version(tmp_path)
        seen = []
        for i in range(2, 13):
            (tmp_path / "core" / "a.py").write_text(f"x = {i}\n", encoding="utf-8")
            seen.append(build_info.prepare_version(tmp_path))
        assert seen[0] == "1.0.0.2" and seen[-1] == "1.0.0.12"

    def test_manual_major_minor_edit_is_respected(self, tmp_path):
        _project(tmp_path, "1.0.0.5")
        build_info.prepare_version(tmp_path)
        (tmp_path / "VERSION").write_text("1.1.0.0\n", encoding="utf-8")  # người làm tự nâng bản nhỏ
        (tmp_path / "core" / "a.py").write_text("x = 9\n", encoding="utf-8")
        assert build_info.prepare_version(tmp_path) == "1.1.0.1"

    def test_changing_only_tests_or_stamp_does_not_bump(self, tmp_path):
        _project(tmp_path, "1.0.0.1")
        build_info.prepare_version(tmp_path)
        (tmp_path / "tests" / "t.py").write_text("1\n", encoding="utf-8")
        (tmp_path / "core" / "_build_stamp.py").write_text("VERSION = '1.0.0.1'\n", encoding="utf-8")
        assert build_info.prepare_version(tmp_path) == "1.0.0.1"

    def test_invalid_version_file_stops_the_build(self, tmp_path):
        _project(tmp_path, "abc")
        with pytest.raises(ValueError):
            build_info.prepare_version(tmp_path)
        assert not (tmp_path / ".version_hash").exists()  # không ghi dở


class TestAppVersion:
    def _stamp_with(self, monkeypatch, **attrs):
        mod = types.SimpleNamespace(**attrs)
        monkeypatch.setattr(build_info.importlib, "import_module", lambda name: mod)

    def test_from_stamp_shows_only_the_number(self, monkeypatch):
        self._stamp_with(monkeypatch, BUILD_TIME="2026-11-20 08:16", GIT_COMMIT="45ffbdc+", VERSION="1.0.0.7")
        assert build_info.app_version() == "1.0.0.7"  # không kèm ngày giờ hay mã commit

    def test_describe_includes_version_for_tracing(self, monkeypatch):
        self._stamp_with(monkeypatch, BUILD_TIME="2026-11-20 08:16", GIT_COMMIT="45ffbdc", VERSION="1.0.0.7")
        assert build_info.describe() == "1.0.0.7, build 2026-11-20 08:16 (45ffbdc)"

    def test_from_source_reads_version_file_and_says_dev(self, monkeypatch, tmp_path):
        _no_stamp(monkeypatch)
        monkeypatch.delattr(sys, "frozen", raising=False)
        (tmp_path / "VERSION").write_text("1.0.0.3\n", encoding="utf-8")
        monkeypatch.setattr(build_info, "ROOT", tmp_path)
        assert build_info.app_version() == "1.0.0.3 (dev)"

    def test_old_exe_without_version_in_stamp(self, monkeypatch):
        self._stamp_with(monkeypatch, BUILD_TIME="2026-11-19 16:40", GIT_COMMIT="45ffbdc")  # stamp cũ, chưa có VERSION
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert "không rõ" in build_info.app_version()

    def test_frozen_without_stamp(self, monkeypatch):
        _no_stamp(monkeypatch)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert "không rõ" in build_info.app_version()

    def test_broken_version_file_does_not_crash_the_app(self, monkeypatch, tmp_path):
        _no_stamp(monkeypatch)
        monkeypatch.delattr(sys, "frozen", raising=False)
        (tmp_path / "VERSION").write_text("hỏng", encoding="utf-8")
        monkeypatch.setattr(build_info, "ROOT", tmp_path)
        assert build_info.app_version() == "dev"


def test_stamp_with_version_roundtrip(tmp_path):
    path = tmp_path / "_build_stamp.py"
    build_info.write_build_stamp(path, datetime(2026, 11, 20, 8, 16), "abc+", "1.0.0.4")
    ns = {}
    exec(path.read_text(encoding="utf-8"), ns)
    assert ns["VERSION"] == "1.0.0.4" and ns["BUILD_TIME"] == "2026-11-20 08:16"
