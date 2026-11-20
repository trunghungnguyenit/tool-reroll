"""Giấy phép offline: Key ký số gắn máy, hạn nhập 24h, dùng một lần, lưu DPAPI, chép sang máy khác không chạy."""

import base64
import time

import pytest
from nacl.signing import SigningKey, VerifyKey

from core import license as lic

pytestmark = pytest.mark.real_license

REAL_MACHINE_HASH = lic.machine_hash  # hàm thật, giữ lại trước khi fixture thay bằng máy giả
REAL_PUBLIC_KEY_B64 = lic.PUBLIC_KEY_B64

MACHINE_A = bytes(range(16))
MACHINE_B = bytes(range(16, 32))
NOW = 1_800_000_000.0  # mốc cố định (đã sau ngày build nên không vướng kiểm tra đồng hồ)


@pytest.fixture
def seller():
    return SigningKey.generate()


@pytest.fixture
def env(tmp_path, monkeypatch, seller):
    """Máy A với giấy phép trong thư mục tạm, khóa công khai của người bán thử."""
    monkeypatch.setattr(lic, "APP_DIR", tmp_path)
    monkeypatch.setattr(lic, "LICENSE_PATH", tmp_path / "license.dat")
    monkeypatch.setattr(lic, "USED_PATH", tmp_path / "used_keys.dat")
    monkeypatch.setattr(lic, "PUBLIC_KEY_B64", base64.b64encode(bytes(seller.verify_key)).decode())
    state = {"machine": MACHINE_A}
    monkeypatch.setattr(lic, "machine_hash", lambda: state["machine"])
    monkeypatch.setattr(lic.build_info, "build_time", lambda: None)
    return state


def key_for(seller, machine=MACHINE_A, now=NOW, ttl=lic.KEY_TTL_S):
    return lic.issue_key(seller, lic.format_machine_code(machine), now=now, ttl_s=ttl)


class TestMachineCode:
    def test_roundtrip_and_format(self):
        code = lic.format_machine_code(MACHINE_A)
        assert code.count("-") == 7 and all(len(g) == 4 for g in code.split("-"))
        assert lic.parse_machine_code(code) == MACHINE_A

    def test_tolerates_case_spaces_and_missing_dashes(self):
        code = lic.format_machine_code(MACHINE_A)
        assert lic.parse_machine_code("  " + code.lower().replace("-", " ") + "\n") == MACHINE_A

    def test_typo_is_caught_by_checksum(self):
        code = lic.format_machine_code(MACHINE_A)
        bad = ("B" if code[0] != "B" else "C") + code[1:]
        with pytest.raises(lic.LicenseError, match="Mã máy không đúng"):
            lic.parse_machine_code(bad)

    def test_garbage_is_rejected_not_crashing(self):
        for text in ("", "!!!", "ABC", "1111-1111"):
            with pytest.raises(lic.LicenseError):
                lic.parse_machine_code(text)

    def test_real_machine_hash_is_stable_and_16_bytes(self):
        a, b = REAL_MACHINE_HASH(), REAL_MACHINE_HASH()
        assert a == b and len(a) == 16
        assert lic.parse_machine_code(lic.format_machine_code(a)) == a


class TestVerifyKey:
    def test_valid_key(self, env, seller):
        info = lic.verify_key(key_for(seller), MACHINE_A)
        assert info.machine == MACHINE_A and info.expires_at - info.issued_at == lic.KEY_TTL_S and len(info.key_id) == 16

    def test_key_is_pasteable_in_any_layout(self, env, seller):
        text = key_for(seller)
        mangled = "  " + text.lower().replace("-", "\n") + "  "
        assert lic.verify_key(mangled, MACHINE_A).key_id == lic.verify_key(text, MACHINE_A).key_id

    def test_other_machine_is_rejected(self, env, seller):
        with pytest.raises(lic.LicenseError, match="máy khác"):
            lic.verify_key(key_for(seller, machine=MACHINE_B), MACHINE_A)

    def test_key_from_another_seller_is_rejected(self, env):
        forged = key_for(SigningKey.generate())
        with pytest.raises(lic.LicenseError, match="sai chữ ký"):
            lic.verify_key(forged, MACHINE_A)

    def test_any_changed_character_breaks_the_key(self, env, seller):
        text = key_for(seller).replace("-", "")
        for pos in (0, 10, 60, len(text) - 6):  # phần mã máy, thời gian, chữ ký
            ch = "A" if text[pos] != "A" else "B"
            with pytest.raises(lic.LicenseError):
                lic.verify_key(text[:pos] + ch + text[pos + 1:], MACHINE_A)

    def test_extending_expiry_invalidates_signature(self, env, seller):
        """Sửa hạn nhập trong phần được ký để kéo dài 24h phải hỏng chữ ký."""
        raw = bytearray(lic._unb32(key_for(seller)))
        raw[21:25] = (int(NOW) + 10 * 365 * 86400).to_bytes(4, "big")  # trường expires_at
        with pytest.raises(lic.LicenseError, match="sai chữ ký"):
            lic.verify_key(lic._b32(bytes(raw)), MACHINE_A)

    def test_key_with_other_format_version_is_rejected(self, env, seller):
        """Key ký đúng nhưng thuộc phiên bản định dạng khác (bản app cũ/mới) phải báo rõ, không đoán nghĩa các trường."""
        payload = lic._PAYLOAD.pack(lic.KEY_VERSION + 1, MACHINE_A, int(NOW), int(NOW) + 86400, b"\x01" * 8)
        text = lic._b32(payload + seller.sign(payload).signature)
        with pytest.raises(lic.LicenseError, match="phiên bản khác"):
            lic.verify_key(text, MACHINE_A)

    def test_wrong_length_and_garbage(self, env, seller):
        for text in ("", "ABCD", key_for(seller)[:-9], key_for(seller) + "AAAA", "!!!! ????"):
            with pytest.raises(lic.LicenseError):
                lic.verify_key(text, MACHINE_A)

    def test_each_key_has_unique_id(self, env, seller):
        ids = {lic.verify_key(key_for(seller), MACHINE_A).key_id for _ in range(20)}
        assert len(ids) == 20


class TestWindow:
    def info(self, seller, now=NOW, ttl=lic.KEY_TTL_S):
        return lic.verify_key(key_for(seller, now=now, ttl=ttl), MACHINE_A)

    def test_inside_and_boundary(self, env, seller):
        info = self.info(seller)
        lic.check_window(info, NOW)
        lic.check_window(info, NOW + lic.KEY_TTL_S)  # đúng giây cuối vẫn được

    def test_expires_after_24h_even_if_never_used(self, env, seller):
        with pytest.raises(lic.LicenseError, match="hết hạn.*24 giờ"):
            lic.check_window(self.info(seller), NOW + lic.KEY_TTL_S + 1)

    def test_short_ttl_is_reported_in_hours(self, env, seller):
        with pytest.raises(lic.LicenseError, match="6 giờ"):
            lic.check_window(self.info(seller, ttl=6 * 3600), NOW + 6 * 3600 + 5)

    def test_clock_before_issue_time(self, env, seller):
        with pytest.raises(lic.LicenseError, match="sớm hơn lúc cấp"):
            lic.check_window(self.info(seller), NOW - lic.CLOCK_SKEW_S - 60)
        lic.check_window(self.info(seller), NOW - lic.CLOCK_SKEW_S + 60)  # lệch nhẹ giữa hai máy thì chấp nhận

    def test_clock_rolled_back_before_build_date(self, env, seller, monkeypatch):
        from datetime import datetime

        monkeypatch.setattr(lic.build_info, "build_time", lambda: datetime.fromtimestamp(NOW + 3 * 86400))
        info = self.info(seller, now=NOW + 3 * 86400)
        lic.check_window(info, NOW + 3 * 86400)
        monkeypatch.setattr(lic.build_info, "build_time", lambda: datetime.fromtimestamp(NOW + 10 * 86400))
        with pytest.raises(lic.LicenseError, match="sớm hơn ngày tạo bản"):
            lic.check_window(info, NOW + 3 * 86400)


class TestActivate:
    def test_activate_then_installed_ok(self, env, seller):
        assert lic.check_installed().missing
        info = lic.activate(key_for(seller), now=NOW)
        status = lic.check_installed()
        assert status.ok and status.info.key_id == info.key_id
        lic.require_active()  # không ném

    def test_not_activated_means_require_active_raises(self, env):
        with pytest.raises(lic.LicenseError, match="Chưa kích hoạt"):
            lic.require_active()

    def test_expired_key_cannot_activate_and_leaves_nothing(self, env, seller):
        with pytest.raises(lic.LicenseError, match="hết hạn"):
            lic.activate(key_for(seller), now=NOW + lic.KEY_TTL_S + 60)
        assert not lic.LICENSE_PATH.exists() and not lic.USED_PATH.exists()

    def test_key_for_other_machine_cannot_activate(self, env, seller):
        with pytest.raises(lic.LicenseError, match="máy khác"):
            lic.activate(key_for(seller, machine=MACHINE_B), now=NOW)
        assert lic.check_installed().missing

    def test_key_is_single_use_even_after_license_is_deleted(self, env, seller):
        key = key_for(seller)
        lic.activate(key, now=NOW)
        lic.LICENSE_PATH.unlink()  # ví dụ người dùng xóa giấy phép để 'làm lại'
        with pytest.raises(lic.LicenseError, match="đã được dùng"):
            lic.activate(key, now=NOW + 60)
        lic.activate(key_for(seller, now=NOW + 120), now=NOW + 120)  # Key mới thì được

    def test_license_survives_after_key_window_closed(self, env, seller, monkeypatch):
        """Hạn 24h chỉ là hạn NHẬP Key: kích hoạt rồi thì dùng lâu dài, không phụ thuộc đồng hồ."""
        lic.activate(key_for(seller), now=NOW)
        monkeypatch.setattr(time, "time", lambda: NOW + 400 * 86400)
        assert lic.check_installed().ok

    def test_copied_license_does_not_work_on_another_machine(self, env, seller):
        """Chép nguyên file giấy phép (và cả exe) sang máy khác: mã máy khác nên không hợp lệ."""
        lic.activate(key_for(seller), now=NOW)
        env["machine"] = MACHINE_B
        status = lic.check_installed()
        assert not status.ok and not status.missing and "máy khác" in status.reason
        with pytest.raises(lic.LicenseError):
            lic.require_active()

    def test_dpapi_blob_from_elsewhere_is_unreadable(self, env, seller):
        lic.activate(key_for(seller), now=NOW)
        lic.LICENSE_PATH.write_bytes(lic.LICENSE_PATH.read_bytes()[:-8] + b"XXXXXXXX")  # như blob của máy khác/bị sửa
        status = lic.check_installed()
        assert not status.ok and "không dùng được trên máy này" in status.reason

    def test_plain_json_license_is_not_accepted(self, env, seller):
        """Tự viết file giấy phép dạng chữ thường (không qua DPAPI) không có tác dụng."""
        lic.LICENSE_PATH.write_text('{"key": "%s"}' % key_for(seller), encoding="utf-8")
        assert not lic.check_installed().ok

    def test_forged_license_with_other_sellers_key_is_rejected(self, env):
        evil = SigningKey.generate()
        lic._write_protected(lic.LICENSE_PATH, {"key": key_for(evil)})
        status = lic.check_installed()
        assert not status.ok and "sai chữ ký" in status.reason

    def test_unwritable_location_gives_actionable_message(self, env, seller, monkeypatch):
        def boom(path, obj):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(lic, "_write_protected", boom)
        with pytest.raises(lic.LicenseError, match="quyền Admin"):
            lic.activate(key_for(seller), now=NOW)

    def test_failure_to_record_used_id_still_keeps_license(self, env, seller, monkeypatch):
        real = lic._write_protected

        def only_license(path, obj):
            if path == lic.USED_PATH:
                raise OSError("đĩa đầy")
            return real(path, obj)

        monkeypatch.setattr(lic, "_write_protected", only_license)
        lic.activate(key_for(seller), now=NOW)
        assert lic.check_installed().ok


class TestDpapi:
    def test_roundtrip_and_ciphertext_differs(self):
        data = b'{"key": "abc"}' * 10
        blob = lic._dpapi(data, protect=True)
        assert blob != data and data not in blob
        assert lic._dpapi(blob, protect=False) == data

    def test_tampered_blob_is_rejected(self):
        blob = bytearray(lic._dpapi(b"hello world", protect=True))
        blob[-3] ^= 0xFF
        with pytest.raises(OSError):
            lic._dpapi(bytes(blob), protect=False)


class TestPublicKey:
    def test_embedded_public_key_is_a_valid_ed25519_key(self):
        assert len(base64.b64decode(REAL_PUBLIC_KEY_B64)) == 32
        VerifyKey(base64.b64decode(REAL_PUBLIC_KEY_B64))

    def test_no_private_key_material_in_module(self):
        """Khóa riêng không được nằm trong mã nguồn đóng gói vào exe."""
        import inspect

        src = inspect.getsource(lic)
        assert "private" not in src.lower().replace("khóa riêng", "")


def test_private_key_can_never_be_committed():
    """Khóa riêng (và sổ cấp Key) có thể nằm trong thư mục dự án, nhưng không được nằm trong git, kể cả khi `git add .`."""
    import shutil
    import subprocess
    from pathlib import Path

    if shutil.which("git") is None:
        pytest.skip("không có git")
    root = Path(__file__).resolve().parent.parent
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=root, capture_output=True,
                               text=True, encoding="utf-8").stdout.splitlines()
    leaked = [f for f in tracked + untracked if f.endswith(".key") or Path(f).name == "issued.csv"]
    assert not leaked, f"file bí mật sẽ bị commit: {leaked}"


def test_installed_status_reports_activation_time(env, seller):
    lic.activate(key_for(seller), now=NOW)
    status = lic.check_installed()
    assert status.ok and status.activated_at == int(NOW)


def test_activation_time_missing_or_wrong_type_is_none_not_an_error(env, seller):
    key = key_for(seller)
    for bad in (None, "hôm qua", 1.5):
        lic._write_protected(lic.LICENSE_PATH, {"key": lic._canonical(key), "activated_at": bad})
        status = lic.check_installed()
        assert status.ok and status.activated_at is None
