"""Giấy phép offline: Key ký số gắn với đúng một máy, chỉ nhập được trong 24 giờ, kích hoạt xong dùng lâu dài trên máy đó.

Luồng: exe hiện MÃ MÁY → người dùng gửi cho người bán → người bán chạy công cụ cấp Key (giữ KHÓA RIÊNG, nằm ngoài repo và
không bao giờ đóng vào exe) → người dùng dán Key. Exe chỉ có KHÓA CÔNG KHAI nên chỉ kiểm tra được chữ ký, không tự tạo Key được.

Key = chữ ký Ed25519 của {phiên bản, mã máy, lúc cấp, hạn nhập, key_id}. Hạn nhập nằm trong phần được ký nên sửa là hỏng chữ ký.
Kích hoạt xong, giấy phép lưu ở %PROGRAMDATA% bằng DPAPI (gắn với máy): chép file đó hay chép riêng exe sang máy khác đều vô dụng.
Mỗi key_id đã dùng được ghi lại nên không nhập lại cùng một Key.

Giới hạn (đã chấp nhận): offline thì giờ máy là nguồn thời gian duy nhất; không thu hồi được Key đã cấp; người sửa được chính exe
thì bỏ qua được mọi kiểm tra ở đây."""

import base64
import ctypes
import hashlib
import json
import os
import secrets
import struct
import time
import zlib
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from core import build_info

# Khóa công khai Ed25519 (base64) của người bán. Khóa riêng KHÔNG nằm trong dự án này.
PUBLIC_KEY_B64 = "JeGfdXOdgN7807ZEbVeRVw+RMvwAQA5qX4k+W/qfG9Q="

KEY_VERSION = 1
KEY_TTL_S = 24 * 3600  # Key chỉ nhập được trong khoảng này kể từ lúc cấp, kể cả khi chưa ai kích hoạt
CLOCK_SKEW_S = 600  # giờ máy người dùng được phép chậm hơn máy người bán chừng này
BUILD_SKEW_S = 24 * 3600  # giờ máy sớm hơn ngày đóng gói exe quá mức này là bất thường (đã chỉnh lùi đồng hồ)

_PAYLOAD = struct.Struct(">B16sII8s")  # phiên bản, mã máy, lúc cấp, hạn nhập, key_id
_SIG_LEN = 64
_SALT = b"TFTAutoBuy/license/v1"

APP_DIR = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "TFT_Auto_Buy"  # không phụ thuộc tài khoản Windows (chạy Admin)
LICENSE_PATH = APP_DIR / "license.dat"
USED_PATH = APP_DIR / "used_keys.dat"


class LicenseError(Exception):
    """Lỗi giấy phép; nội dung là câu tiếng Việt hiển thị thẳng cho người dùng."""


@dataclass(frozen=True)
class KeyInfo:
    machine: bytes
    issued_at: int
    expires_at: int
    key_id: str


@dataclass(frozen=True)
class Status:
    ok: bool
    reason: str = ""
    missing: bool = False  # chưa từng kích hoạt (khác với giấy phép có nhưng hỏng/không hợp lệ)
    info: KeyInfo | None = None


# ------------------------------------------------------------------ mã hóa văn bản
def _b32(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii").rstrip("=")


def _group(text: str, size: int) -> str:
    return "-".join(text[i:i + size] for i in range(0, len(text), size))


def _unb32(text: str) -> bytes:
    clean = "".join(ch for ch in str(text).upper() if not ch.isspace() and ch != "-")
    try:
        return base64.b32decode(clean + "=" * (-len(clean) % 8))
    except (ValueError, UnicodeError):
        raise LicenseError("Có ký tự không hợp lệ. Hãy dán nguyên văn, không gõ tay.") from None


def _canonical(text: str) -> str:
    return "".join(ch for ch in str(text).upper() if not ch.isspace() and ch != "-")


# ------------------------------------------------------------------ mã máy
def _machine_guid() -> str:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except OSError:
        raise LicenseError("Không đọc được định danh của máy này nên không tạo được Mã máy.") from None


def _volume_serial() -> int:
    serial = wintypes.DWORD(0)
    root = os.environ.get("SystemDrive", "C:") + "\\"
    ok = ctypes.windll.kernel32.GetVolumeInformationW(root, None, 0, ctypes.byref(serial), None, None, None, 0)
    return int(serial.value) if ok else 0


def machine_hash() -> bytes:
    """16 byte định danh máy: băm MachineGuid + số serial ổ hệ thống (đổi ổ hay cài lại Windows thì phải xin Key mới)."""
    raw = _SALT + b"|" + _machine_guid().encode("utf-8") + b"|" + str(_volume_serial()).encode("ascii")
    return hashlib.sha256(raw).digest()[:16]


def format_machine_code(machine: bytes) -> str:
    """Mã máy hiển thị cho người dùng: 16 byte + 4 byte kiểm tra (bắt lỗi chép sai), dạng XXXX-XXXX-..."""
    return _group(_b32(machine + struct.pack(">I", zlib.crc32(machine))), 4)


def parse_machine_code(text: str) -> bytes:
    raw = _unb32(text)
    if len(raw) != 20 or struct.pack(">I", zlib.crc32(raw[:16])) != raw[16:]:
        raise LicenseError("Mã máy không đúng (chép thiếu hoặc sai ký tự).")
    return raw[:16]


def machine_code() -> str:
    return format_machine_code(machine_hash())


# ------------------------------------------------------------------ cấp và kiểm tra Key
def public_key_bytes() -> bytes:
    if not PUBLIC_KEY_B64:
        raise LicenseError("Bản này chưa được cấu hình khóa công khai (lỗi đóng gói).")
    return base64.b64decode(PUBLIC_KEY_B64)


def issue_key(signing_key: SigningKey, machine_code_text: str, now: float | None = None, ttl_s: int = KEY_TTL_S) -> str:
    """Dành cho công cụ của người bán (cần khóa riêng): tạo Key cho đúng một Mã máy."""
    machine = parse_machine_code(machine_code_text)
    issued = int(time.time() if now is None else now)
    payload = _PAYLOAD.pack(KEY_VERSION, machine, issued, issued + int(ttl_s), secrets.token_bytes(8))
    return _group(_b32(payload + signing_key.sign(payload).signature), 8)


def verify_key(key_text: str, machine: bytes, public_key: bytes | None = None) -> KeyInfo:
    """Kiểm tra định dạng, chữ ký và mã máy (KHÔNG kiểm tra thời gian: xem check_window)."""
    raw = _unb32(key_text)
    if len(raw) != _PAYLOAD.size + _SIG_LEN:
        raise LicenseError("Key không đúng định dạng (thiếu hoặc thừa ký tự). Hãy dán nguyên văn Key đã nhận.")
    payload, signature = raw[:_PAYLOAD.size], raw[_PAYLOAD.size:]
    try:
        VerifyKey(public_key if public_key is not None else public_key_bytes()).verify(payload, signature)
    except BadSignatureError:
        raise LicenseError("Key không hợp lệ (sai chữ ký). Hãy dán lại nguyên văn Key đã nhận.") from None
    version, key_machine, issued, expires, key_id = _PAYLOAD.unpack(payload)
    if version != KEY_VERSION:
        raise LicenseError("Key thuộc phiên bản khác, không dùng được với bản này.")
    if not secrets.compare_digest(key_machine, machine):
        raise LicenseError("Key này được cấp cho máy khác, không dùng được trên máy này.")
    return KeyInfo(machine=key_machine, issued_at=issued, expires_at=expires, key_id=key_id.hex())


def check_window(info: KeyInfo, now: float) -> None:
    """Key còn trong hạn nhập không? Hạn tính từ lúc cấp nên Key hết hạn kể cả khi chưa từng được dùng."""
    if now > info.expires_at:
        hours = (info.expires_at - info.issued_at) / 3600
        raise LicenseError(f"Key đã hết hạn (chỉ có hiệu lực {hours:g} giờ kể từ lúc cấp). Hãy xin Key mới.")
    if now < info.issued_at - CLOCK_SKEW_S:
        raise LicenseError("Giờ trên máy sớm hơn lúc cấp Key. Hãy chỉnh lại ngày giờ Windows rồi thử lại.")
    built = build_info.build_time()
    if built is not None and now < built.timestamp() - BUILD_SKEW_S:
        raise LicenseError("Ngày giờ trên máy sớm hơn ngày tạo bản này. Hãy chỉnh lại ngày giờ Windows rồi thử lại.")


# ------------------------------------------------------------------ DPAPI (gắn dữ liệu với máy)
_UI_FORBIDDEN = 0x1
_LOCAL_MACHINE = 0x4


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_BLOB_P = ctypes.POINTER(_Blob)
_crypt32.CryptProtectData.argtypes = [_BLOB_P, wintypes.LPCWSTR, _BLOB_P, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, _BLOB_P]
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [_BLOB_P, ctypes.c_void_p, _BLOB_P, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, _BLOB_P]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p


def _blob_of(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.c_void_p)), buf  # buf phải còn sống tới khi gọi xong


def _dpapi(data: bytes, protect: bool) -> bytes:
    src, keep_src = _blob_of(data)
    entropy, keep_entropy = _blob_of(_SALT)
    out = _Blob()
    if protect:
        ok = _crypt32.CryptProtectData(ctypes.byref(src), "TFT_Auto_Buy", ctypes.byref(entropy), None, None,
                                       _UI_FORBIDDEN | _LOCAL_MACHINE, ctypes.byref(out))
    else:
        ok = _crypt32.CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(entropy), None, None,
                                         _UI_FORBIDDEN, ctypes.byref(out))
    del keep_src, keep_entropy
    if not ok:
        raise OSError(ctypes.get_last_error(), "DPAPI")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32.LocalFree(out.pbData)


def _write_protected(path: Path, obj: dict) -> None:
    blob = _dpapi(json.dumps(obj).encode("utf-8"), protect=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, path)


def _read_protected(path: Path) -> dict:
    obj = json.loads(_dpapi(path.read_bytes(), protect=False))
    if not isinstance(obj, dict):
        raise ValueError("định dạng không đúng")
    return obj


# ------------------------------------------------------------------ kích hoạt và kiểm tra giấy phép đã lưu
def _used_ids() -> set[str]:
    try:
        ids = _read_protected(USED_PATH).get("ids", [])
        return {str(i) for i in ids}
    except (OSError, ValueError):
        return set()


def activate(key_text: str, now: float | None = None, public_key: bytes | None = None) -> KeyInfo:
    """Kích hoạt bằng Key (trong hạn, đúng máy, chưa dùng) và lưu giấy phép. Lỗi thì ném LicenseError (tiếng Việt)."""
    info = verify_key(key_text, machine_hash(), public_key)
    used = _used_ids()
    if info.key_id in used:
        raise LicenseError("Key này đã được dùng rồi. Mỗi Key chỉ dùng một lần; hãy xin Key mới nếu cần.")
    check_window(info, time.time() if now is None else now)
    try:
        _write_protected(LICENSE_PATH, {"key": _canonical(key_text), "activated_at": int(time.time() if now is None else now)})
    except OSError as e:
        raise LicenseError(f"Không ghi được giấy phép vào {LICENSE_PATH.parent} ({e.strerror or type(e).__name__}). "
                           "Hãy chạy bằng quyền Admin.") from None
    try:
        _write_protected(USED_PATH, {"ids": sorted(used | {info.key_id})})
    except OSError:
        pass  # giấy phép đã lưu; chỉ mất việc chặn nhập lại cùng Key
    return info


def check_installed(public_key: bytes | None = None) -> Status:
    """Giấy phép đã lưu có hợp lệ trên máy này không (chữ ký + mã máy; không xét hạn nhập vì đã kích hoạt rồi)."""
    try:
        data = _read_protected(LICENSE_PATH)
    except FileNotFoundError:
        return Status(False, "Chưa kích hoạt.", missing=True)
    except (OSError, ValueError):
        return Status(False, "Giấy phép không dùng được trên máy này (có thể bị sao chép từ máy khác hoặc đã hỏng). "
                             "Hãy kích hoạt lại bằng Key mới.")
    try:
        info = verify_key(str(data.get("key", "")), machine_hash(), public_key)
    except LicenseError as e:
        return Status(False, f"Giấy phép không hợp lệ: {e}")
    return Status(True, info=info)


def require_active() -> None:
    """Gọi ở những bước quan trọng (khởi động, bấm Bắt đầu, bật quét): ném LicenseError nếu chưa/không còn hợp lệ."""
    status = check_installed()
    if not status.ok:
        raise LicenseError(status.reason)
