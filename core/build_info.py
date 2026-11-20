"""Phiên bản và thông tin bản build.

Phiên bản dạng 1.0.0.N nằm trong file VERSION (gốc dự án). Mỗi lần đóng gói, TFT_Auto_Buy.spec gọi `prepare_version`: so băm
mã nguồn với lần build trước (file .version_hash); code đã đổi thì số cuối N tăng 1, không đổi thì giữ nguyên. Ba số đầu do
người làm tự sửa trong VERSION khi muốn đổi bản lớn/nhỏ.

Spec cũng sinh core/_build_stamp.py (phiên bản + ngày giờ build + mã commit). Chạy từ mã nguồn thì không có file này nên đọc
thẳng VERSION và ghi 'dev'. Exe đóng gói từ bản cũ (trước khi có phiên bản) không có số phiên bản nào, cũng là dấu hiệu nhận ra
exe cũ."""

import hashlib
import importlib
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

STAMP_MODULE = "core._build_stamp"
ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = "VERSION"
HASH_FILE = ".version_hash"
FIRST_VERSION = "1.0.0.1"
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")

# Phần nào của dự án làm thay đổi exe: mã nguồn app, điểm vào, cách đóng gói và thư viện. Test, tài liệu, file sinh lúc
# build (_build_stamp.py) KHÔNG tính, nếu không số phiên bản sẽ tăng mỗi lần build.
_HASHED_GLOBS = ("core/*.py", "ui/*.py", "main.py", "TFT_Auto_Buy.spec", "requirements.txt")
_HASH_EXCLUDE = {"_build_stamp.py"}


def _load_stamp() -> tuple[str, str, str] | None:
    """(giờ build, mã commit, phiên bản) từ file stamp; phiên bản là '' với stamp cũ chưa có."""
    try:
        stamp = importlib.import_module(STAMP_MODULE)
        return str(stamp.BUILD_TIME), str(stamp.GIT_COMMIT), str(getattr(stamp, "VERSION", ""))
    except (ImportError, AttributeError):
        return None


def build_time() -> datetime | None:
    """Giờ (địa phương) đóng gói exe; None khi chạy từ mã nguồn hoặc stamp hỏng."""
    stamp = _load_stamp()
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp[0], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def read_version(root: Path = ROOT) -> str | None:
    """Nội dung hợp lệ của file VERSION, hoặc None nếu chưa có file. File sai định dạng thì ném ValueError."""
    path = root / VERSION_FILE
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not _VERSION_RE.match(text):
        raise ValueError(f"{VERSION_FILE} phải có dạng 1.0.0.1 (4 số cách nhau bằng dấu chấm), hiện là {text!r}")
    return text


def bump_version(version: str) -> str:
    """Tăng số cuối: 1.0.0.9 -> 1.0.0.10."""
    head, _, last = version.rpartition(".")
    return f"{head}.{int(last) + 1}"


def source_hash(root: Path = ROOT) -> str:
    """Băm các file làm đổi exe. Không phụ thuộc kiểu xuống dòng (CRLF/LF) hay thứ tự duyệt thư mục."""
    files = sorted({p for pattern in _HASHED_GLOBS for p in root.glob(pattern) if p.is_file() and p.name not in _HASH_EXCLUDE})
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def prepare_version(root: Path = ROOT) -> str:
    """Gọi ngay trước khi đóng gói: tăng phiên bản nếu mã nguồn đã đổi so với lần build trước, ghi lại, trả về phiên bản.

    Lần build đầu tiên (chưa có băm cũ) giữ nguyên phiên bản hiện tại và chỉ ghi lại băm."""
    version = read_version(root) or FIRST_VERSION
    current = source_hash(root)
    hash_path = root / HASH_FILE
    previous = hash_path.read_text(encoding="utf-8").strip() if hash_path.exists() else None
    if previous is not None and previous != current:
        version = bump_version(version)
    (root / VERSION_FILE).write_text(version + "\n", encoding="utf-8")
    hash_path.write_text(current + "\n", encoding="utf-8")
    return version


def app_version() -> str:
    """Số phiên bản hiển thị cho người dùng (dòng đầu Nhật ký), vd '1.0.0.1'."""
    stamp = _load_stamp()
    if stamp and stamp[2]:
        return stamp[2]
    if getattr(sys, "frozen", False):
        return "không rõ (exe đóng gói từ bản cũ)"
    try:
        version = read_version(ROOT)
    except (OSError, ValueError):
        version = None
    return f"{version} (dev)" if version else "dev"


def describe() -> str:
    """Mô tả đầy đủ để truy vết (báo cáo --selftest), vd '1.0.0.1, build 2026-11-19 16:40 (45ffbdc, có thay đổi chưa commit)'."""
    stamp = _load_stamp()
    if stamp:
        when, commit, version = stamp
        prefix = f"{version}, " if version else ""
        if not commit:
            return f"{prefix}build {when}"
        if commit.endswith("+"):
            return f"{prefix}build {when} ({commit[:-1]}, có thay đổi chưa commit)"
        return f"{prefix}build {when} ({commit})"
    if getattr(sys, "frozen", False):
        return "exe không có thông tin build (đóng gói từ bản cũ)"
    return "dev (chạy từ mã nguồn)"


def git_commit(root: Path) -> str:
    """Mã commit ngắn của HEAD, thêm '+' nếu còn thay đổi chưa commit; '' nếu không có git."""
    def run(*args):
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=15, encoding="utf-8")

    try:
        head = run("rev-parse", "--short", "HEAD")
        if head.returncode != 0 or not head.stdout.strip():
            return ""
        dirty = run("status", "--porcelain", "--untracked-files=no").stdout.strip()
        return head.stdout.strip() + ("+" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return ""


def write_build_stamp(path: Path, now: datetime, commit: str, version: str = "") -> None:
    """Sinh file stamp. Được gọi từ TFT_Auto_Buy.spec ngay trước khi PyInstaller phân tích mã."""
    path.write_text(
        '"""Sinh tự động bởi TFT_Auto_Buy.spec khi đóng gói — đừng sửa tay, không commit."""\n\n'
        f"VERSION = {version!r}\n"
        f"BUILD_TIME = {now.strftime('%Y-%m-%d %H:%M')!r}\n"
        f"GIT_COMMIT = {commit!r}\n",
        encoding="utf-8",
    )
