import numpy as np
import pytest

from core import name_matcher as nm
from core import ocr_check as oc


@pytest.fixture(autouse=True)
def clean_ocr_state():
    nm.drain_ocr_errors()
    yield
    nm.drain_ocr_errors()
    nm.refresh_ocr_state()


def fake_environment(monkeypatch, backend="winocr", installed=("en-US",), reads=None):
    """Giả lập môi trường OCR: engine, ngôn ngữ đã cài, và kết quả đọc (hàm hoặc chuỗi cố định)."""
    monkeypatch.setattr(nm, "_detect_backend", lambda: backend)
    monkeypatch.setattr(nm, "installed_ocr_languages", lambda: list(installed))
    if reads is None:
        reads = lambda frame: f"{oc.SAMPLE_TEXT} 3"  # noqa: E731
    elif isinstance(reads, str):
        text = reads
        reads = lambda frame: text  # noqa: E731
    monkeypatch.setattr(nm, "read_name_from_slot", reads)


class TestCheckOcr:
    def test_ok_when_engine_language_and_selftest_pass(self, monkeypatch):
        fake_environment(monkeypatch)
        s = oc.check_ocr()
        assert s.ok and s.backend == "winocr" and s.languages == ["en-US"]
        assert s.summary == "Windows OCR (en-US)" and s.hints == []

    def test_no_engine(self, monkeypatch):
        fake_environment(monkeypatch, backend="none")
        s = oc.check_ocr()
        assert not s.ok and "engine" in s.detail.lower()
        assert any("pip install winocr" in h for h in s.hints)
        assert s.summary.startswith("lỗi")

    def test_no_language_pack_installed_gives_install_command(self, monkeypatch):
        fake_environment(monkeypatch, installed=())
        s = oc.check_ocr()
        assert not s.ok and "pack ngôn ngữ" in s.detail
        assert any('Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"' in h for h in s.hints)

    def test_missing_optional_language_is_a_hint_not_a_failure(self, monkeypatch):
        fake_environment(monkeypatch)
        s = oc.check_ocr(wanted_extra=("vi-VN",))
        assert s.ok
        assert any('Language.OCR~~~vi-VN~0.0.1.0' in h for h in s.hints)
        assert not any("en-US" in h for h in s.hints)  # en-US đã có

    def test_no_hint_when_wanted_language_is_installed(self, monkeypatch):
        fake_environment(monkeypatch, installed=("en-US", "vi-VN"))
        s = oc.check_ocr(wanted_extra=("vi-VN",))
        assert s.ok and s.hints == []
        assert s.languages == ["en-US", "vi-VN"]

    def test_selftest_failure_reports_what_was_read(self, monkeypatch):
        fake_environment(monkeypatch, reads="")
        s = oc.check_ocr()
        assert not s.ok and "đọc được chữ mẫu" in s.detail and "''" in s.detail
        assert any("app.log" in h for h in s.hints)

    def test_selftest_failure_includes_recorded_ocr_errors(self, monkeypatch):
        def broken(frame):
            nm.record_ocr_error("RuntimeError: engine hỏng")
            return ""

        fake_environment(monkeypatch, reads=broken)
        s = oc.check_ocr()
        assert not s.ok and "RuntimeError: engine hỏng" in s.detail

    def test_garbled_read_fails_but_close_read_passes(self, monkeypatch):
        fake_environment(monkeypatch, reads="Xyzzy")
        assert not oc.check_ocr().ok
        fake_environment(monkeypatch, reads="Tryndamre 3")  # sai 1 ký tự vẫn coi là đọc được
        assert oc.check_ocr().ok

    def test_stale_errors_are_cleared_before_checking(self, monkeypatch):
        nm.record_ocr_error("lỗi cũ từ lần chạy trước")
        fake_environment(monkeypatch)
        oc.check_ocr()
        assert nm.drain_ocr_errors() == {}

    def test_picks_up_newly_installed_pack_without_restart(self, monkeypatch):
        state = {"installed": ()}
        fake_environment(monkeypatch)
        monkeypatch.setattr(nm, "installed_ocr_languages", lambda: list(state["installed"]))
        assert not oc.check_ocr().ok
        state["installed"] = ("en-US",)
        assert oc.check_ocr().ok

    def test_real_ocr_on_this_machine(self):
        """Kiểm tra thật (không giả lập): bỏ qua nếu máy không có engine OCR."""
        nm.refresh_ocr_state()
        if nm._detect_backend() == "none":
            pytest.skip("máy không có engine OCR")
        status = oc.check_ocr()
        if not status.ok and "pack ngôn ngữ" in status.detail:
            pytest.skip("máy chưa cài pack OCR nào")
        assert status.ok, status.detail


class TestStatusText:
    def test_problem_text_lists_detail_and_hints(self):
        s = oc.OcrStatus(False, "none", detail="Không có engine OCR.", hints=["Chạy A", "Chạy B"])
        assert s.problem_text() == "Không có engine OCR.\n• Chạy A\n• Chạy B"

    def test_summary_variants(self):
        assert oc.OcrStatus(True, "rapidocr", []).summary == "RapidOCR"
        assert oc.OcrStatus(True, "winocr", ["en-US", "vi-VN"]).summary == "Windows OCR (en-US, vi-VN)"
        assert oc.OcrStatus(False, "none", detail="x").summary == "lỗi — x"

    def test_capability_command(self):
        assert oc.capability_command("vi-VN") == 'Add-WindowsCapability -Online -Name "Language.OCR~~~vi-VN~0.0.1.0"'


class TestRenderedSample:
    @pytest.mark.parametrize("size", [18, 22, 28])
    @pytest.mark.parametrize("text", ["Tryndamere", "Vex", "Aurelion Sol"])
    def test_text_sits_inside_the_band_that_ocr_crops(self, text, size):
        """Chữ vẽ lệch ra ngoài dải cắt thì OCR đọc rỗng và phép thử báo hỏng oan (từng xảy ra khi lệch 4 px)."""
        img = oc.render_sample(text, size)
        h = img.shape[0]
        rows = np.where((img.max(axis=2) > 120).any(axis=1))[0]  # các dòng có điểm sáng (chữ)
        assert rows.size
        assert rows.min() >= int(h * 0.72) and rows.max() <= int(h * 0.96)

    def test_sample_card_has_expected_size(self):
        assert oc.render_sample().shape[:2] == (oc.CARD_SIZE[1], oc.CARD_SIZE[0])


class TestStartDecision:
    BAD = oc.OcrStatus(False, "winocr", detail="x")
    GOOD = oc.OcrStatus(True, "winocr", ["en-US"])

    @pytest.mark.parametrize("image_ready", [False, True])
    def test_healthy_ocr_runs(self, image_ready):
        assert oc.start_decision(self.GOOD, True, image_ready) == oc.OCR_RUN

    def test_broken_ocr_with_name_only_blocks(self):
        assert oc.start_decision(self.BAD, True, image_ready=False) == oc.OCR_BLOCK

    def test_broken_ocr_with_usable_images_falls_back_to_images(self):
        assert oc.start_decision(self.BAD, True, image_ready=True) == oc.OCR_IMAGE_ONLY

    @pytest.mark.parametrize("image_ready", [False, True])
    def test_name_mode_off_never_blocks_even_if_ocr_is_broken(self, image_ready):
        assert oc.start_decision(self.BAD, False, image_ready) == oc.OCR_RUN

    def test_no_check_result_runs(self):
        assert oc.start_decision(None, True, False) == oc.OCR_RUN


def test_check_ocr_re_reads_installed_languages_every_time(monkeypatch):
    """Cài pack OCR xong chỉ cần bấm BẮT ĐẦU lại, không phải mở lại app."""
    calls = []
    fake_environment(monkeypatch)
    monkeypatch.setattr(nm, "refresh_ocr_state", lambda: calls.append("refresh"))
    oc.check_ocr()
    oc.check_ocr()
    assert calls == ["refresh", "refresh"]
