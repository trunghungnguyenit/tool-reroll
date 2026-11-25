"""Đọc tên tướng bằng OCR (Windows) và so khớp với danh sách tướng cần bắt."""

import asyncio
import re
import threading
import unicodedata
from difflib import SequenceMatcher

import cv2
import numpy as np
from PIL import Image

_ocr_backend = None
_ocr_langs = ("en-US", "vi-VN")


def _detect_backend() -> str:
    """Chọn engine OCR: 'winocr' (OCR của Windows) hoặc 'none' nếu không nạp được."""
    global _ocr_backend
    if _ocr_backend is not None:
        return _ocr_backend
    try:
        import winocr  # noqa: F401

        _ocr_backend = "winocr"
    except ImportError:
        _ocr_backend = "none"
    return _ocr_backend

# --- Khớp tên: so OCR với TOÀN BỘ tên tướng, chỉ mua khi khớp tốt nhất là một mục tiêu ---
DEFAULT_NAME_THRESHOLD = 0.80  # ngưỡng khớp mờ (fuzzy) mặc định
MIN_FUZZY_LEN = 3  # text OCR / tên ngắn hơn mức này chỉ khớp khi bằng đúng tên (chặn mảnh nhiễu "e", "ex")
MIN_TOKEN_LEN = 4  # OCR chỉ là 1 từ của tên nhiều từ (vd "kench" của "tahm kench") phải dài từng này
PHRASE_SCORE = 0.98  # tên đầy đủ nằm trọn (theo từ) trong text OCR, vd "vex 2" (kèm số vàng)
TOKEN_SCORE = 0.90
FRAGMENT_SCORE = 0.85  # text OCR (bị cắt cụt) chỉ nằm trong ĐÚNG MỘT tên trong toàn danh sách, vd "ves" → "graves"
FRAGMENT_MIN_LEN = 3
AMBIGUITY_MARGIN = 0.05  # khớp mờ: tên mục tiêu kém top không quá mức này thì vẫn được mua


# --- Chẩn đoán OCR: lỗi OCR không bị nuốt im lặng nữa mà được ghi lại để scanner báo cho người dùng ---
class OcrUnavailable(RuntimeError):
    """Không có ngôn ngữ/engine OCR nào dùng được."""


_state_lock = threading.Lock()
_installed_langs: list[str] | None = None  # ngôn ngữ OCR Windows đã cài (cache; refresh_ocr_state() để đọc lại)
_ocr_errors: dict[str, int] = {}
_MAX_DISTINCT_ERRORS = 20


def record_ocr_error(message: str) -> None:
    """Ghi 1 lỗi OCR (gộp theo nội dung, đếm số lần)."""
    with _state_lock:
        if message in _ocr_errors or len(_ocr_errors) < _MAX_DISTINCT_ERRORS:
            _ocr_errors[message] = _ocr_errors.get(message, 0) + 1


def drain_ocr_errors() -> dict[str, int]:
    """Lấy và xóa các lỗi OCR đã ghi từ lần gọi trước: {nội dung: số lần}."""
    with _state_lock:
        errors = dict(_ocr_errors)
        _ocr_errors.clear()
    return errors


def refresh_ocr_state() -> None:
    """Quên engine và danh sách ngôn ngữ đã nhớ: nhận được pack OCR vừa cài mà không cần mở lại app."""
    global _ocr_backend, _installed_langs
    with _state_lock:
        _ocr_backend = None
        _installed_langs = None


def installed_ocr_languages() -> list[str]:
    """Các ngôn ngữ OCR Windows đã cài (vd ['en-US']). Rỗng nếu không có winocr hoặc chưa cài pack nào."""
    global _installed_langs
    if _installed_langs is None:
        try:
            import winocr

            tags = [lang.language_tag for lang in winocr.OcrEngine.available_recognizer_languages]
        except Exception as e:  # winocr/winrt không dùng được
            record_ocr_error(f"Không liệt kê được ngôn ngữ OCR: {type(e).__name__}: {e}")
            tags = []
        _installed_langs = tags
    return list(_installed_langs)


def ocr_languages_in_use() -> list[str]:
    """Ngôn ngữ sẽ thử theo thứ tự: ưu tiên en-US/vi-VN nếu đã cài, rồi các biến thể tiếng Anh (en-GB...), rồi bất kỳ."""
    installed = installed_ocr_languages()
    ordered = [lang for lang in _ocr_langs if lang in installed]
    ordered += [lang for lang in installed if lang.lower().startswith("en") and lang not in ordered]
    ordered += [lang for lang in installed if lang not in ordered]
    return ordered


_engines = threading.local()  # mỗi luồng OCR giữ engine Windows OCR riêng: một engine không chạy được hai lần đọc cùng lúc


def _engine(lang: str):
    """Engine Windows OCR của luồng hiện tại cho `lang` (tạo một lần rồi dùng lại). winocr.recognize_pil tạo engine MỚI mỗi lần đọc,
    tốn thêm vài ms cho mỗi ô trong khi tool đọc 5 ô mỗi vòng. None nếu không tạo được (lúc đó dùng đường của winocr)."""
    cache = getattr(_engines, "cache", None)
    if cache is None:
        cache = _engines.cache = {}
    if lang not in cache:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        cache[lang] = OcrEngine.try_create_from_language(Language(lang))
    return cache[lang]


def _drop_engine(lang: str) -> None:
    cache = getattr(_engines, "cache", None)
    if cache:
        cache.pop(lang, None)


async def _recognize(pil: Image.Image, lang: str):
    """Đọc ảnh bằng engine dùng lại của luồng; không có engine/lỗi dựng ảnh thì quay về winocr.recognize_pil (cách cũ, chậm hơn)."""
    import winocr

    try:
        engine = _engine(lang)
        if engine is not None:
            from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
            from winrt.windows.storage.streams import DataWriter

            rgba = pil if pil.mode == "RGBA" else pil.convert("RGBA")
            writer = DataWriter()
            writer.write_bytes(rgba.tobytes())
            bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.RGBA8, rgba.width, rgba.height)
            return await engine.recognize_async(bitmap)
    except Exception:
        _drop_engine(lang)
    return await winocr.recognize_pil(pil, lang)


def _read_winocr(region: np.ndarray) -> str:
    """Đọc chữ từ ảnh bằng Windows OCR, chỉ thử các ngôn ngữ đã cài (thử ngôn ngữ chưa cài chỉ gây lỗi vô ích)."""

    langs = ocr_languages_in_use()
    if not langs:
        raise OcrUnavailable("Windows chưa cài pack ngôn ngữ OCR nào")

    rgb = cv2.cvtColor(region, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    tried: set[str] = set()

    async def run():
        for lang in langs:
            base = lang.split("-")[0].lower()
            if base in tried:
                continue  # en-US không ra chữ thì en-GB cũng không ra: đừng đọc lại cùng ảnh (gấp đôi thời gian đúng lúc thẻ còn hiệu ứng)
            try:
                result = await _recognize(pil, lang)
                text = (result.text or "").strip()
                if text:
                    return text
                tried.add(base)
            except Exception as e:
                _drop_engine(lang)  # engine có thể hỏng: lần sau tạo lại
                record_ocr_error(f"OCR {lang}: {type(e).__name__}: {str(e)[:100]}")
        return ""

    try:
        return asyncio.run(run())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(run())
        finally:
            loop.close()


def normalize_name(text: str) -> str:
    """Chuẩn hóa tên: bỏ dấu, chữ thường, bỏ ký tự đặc biệt — để so sánh OCR dễ hơn."""
    text = text.replace("đ", "d").replace("Đ", "D")  # NFD không tách được đ/Đ
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_name_region(slot_frame: np.ndarray) -> np.ndarray:
    """Cắt dải tên tướng ở đáy thẻ (TFT hiển thị tên dưới cùng) và phóng to cho OCR."""
    h, w = slot_frame.shape[:2]
    y0 = int(h * 0.72)
    y1 = int(h * 0.96)
    roi = slot_frame[y0:y1, int(w * 0.05) : int(w * 0.95)]
    if roi.size == 0:
        return slot_frame

    return cv2.resize(roi, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)


def read_name_from_slot(slot_frame: np.ndarray) -> str:
    """OCR đọc tên tướng từ 1 ô shop, trả về chuỗi text ('' nếu không đọc được; nguyên nhân lỗi vào drain_ocr_errors)."""
    if _detect_backend() == "none":
        record_ocr_error("Không có engine OCR (cài winocr)")
        return ""

    region = extract_name_region(slot_frame)
    try:
        return _read_winocr(region)
    except Exception as e:
        record_ocr_error(f"{type(e).__name__}: {str(e)[:120]}")
        return ""


class NameMatcher:
    """
    So text OCR với danh sách tên tướng và quyết định có phải một MỤC TIÊU không.

    Khác cách cũ (chỉ so với mục tiêu): so với TOÀN BỘ tên tướng (all_names) rồi mới hỏi "khớp tốt nhất có
    phải mục tiêu không". Nhờ đó OCR đọc "Gragas" khớp "Gragas" (không phải mục tiêu) nên không còn bị nhận
    nhầm thành "Graves" chỉ vì giống hơn các mục tiêu còn lại.

    Thứ tự ưu tiên: bằng đúng tên (1.0) > tên đầy đủ nằm trọn trong text (0.98) > text là 1 từ của tên nhiều từ
    (0.90) > mảnh OCR chỉ nằm trong đúng 1 tên (0.85) > khớp mờ >= min_ratio. Mức cao hơn thắng; cùng mức thì
    tên dài hơn (cụ thể hơn) thắng. Mảnh nằm trong nhiều tên thì không đoán (rơi xuống khớp mờ).
    Khớp mờ cận nhau giữa nhiều tên: mua nếu một trong số đó là mục tiêu.
    """

    def __init__(
        self,
        targets: list[str],
        all_names: list[str] | None = None,
        min_ratio: float = DEFAULT_NAME_THRESHOLD,
        aliases: dict[str, list[str]] | None = None,
    ):
        """
        aliases: tên khác của cùng một mục tiêu (vd {"Ngộ Không": ["Wukong"]}) — client game có thể hiện ngôn ngữ
        khác ngôn ngữ danh sách. Khớp alias vẫn trả về tên mục tiêu gốc.
        """
        self.min_ratio = min_ratio
        self._target_of: dict[str, str] = {}  # tên đã chuẩn hóa → tên mục tiêu gốc
        for t in targets:
            n = normalize_name(t)
            if n:
                self._target_of.setdefault(n, t)
        for t, alts in (aliases or {}).items():
            for alt in alts:
                n = normalize_name(alt)
                if n:
                    self._target_of.setdefault(n, t)
        cands: dict[str, None] = {}
        for name in [*(all_names or []), *targets, *(a for alts in (aliases or {}).values() for a in alts)]:
            n = normalize_name(name)
            if n:
                cands.setdefault(n, None)
        self._cands = list(cands)
        self._tokens = {c: c.split() for c in self._cands}

    @staticmethod
    def _clean(ocr_text: str) -> str:
        """Chuẩn hóa chữ OCR và bỏ số vàng đi kèm tên ("vex 2" → "vex")."""
        return " ".join(w for w in normalize_name(ocr_text).split() if not w.isdigit())

    @staticmethod
    def _best_ratio(ocr: str, cand: str) -> float:
        """Độ giống (0-1) giữa chữ OCR đã chuẩn hóa và một tên: lấy cao nhất giữa cả chuỗi và từng từ của nó."""
        best = 0.0
        for text in [ocr] + [w for w in ocr.split() if len(w) >= MIN_FUZZY_LEN and w != ocr]:
            best = max(best, SequenceMatcher(None, cand, text, autojunk=False).ratio())
        return best

    def nearest_target(self, ocr_text: str) -> tuple[str, float] | None:
        """Mục tiêu giống chữ OCR nhất (kể cả dưới ngưỡng) và độ giống — chỉ để ghi Nhật ký 'suýt khớp', không dùng để mua."""
        ocr = self._clean(ocr_text)
        if len(ocr) < MIN_FUZZY_LEN:
            return None
        best: tuple[str, float] | None = None
        for key, target in self._target_of.items():
            score = self._best_ratio(ocr, key)
            if best is None or score > best[1]:
                best = (target, score)
        return best

    def explain(self, ocr_text: str, limit: int = 3) -> list[tuple[float, str, bool]]:
        """`limit` tên giống chữ OCR nhất trong TOÀN BỘ danh sách: [(độ giống, tên, có phải mục tiêu)] — bằng chứng cho Nhật ký
        để biết lần mua đó dựa trên chữ gì và có tên nào khác gần giống không (nguy cơ mua nhầm)."""
        ocr = self._clean(ocr_text)
        if len(ocr) < MIN_FUZZY_LEN:
            return []
        scored = sorted(((self._best_ratio(ocr, c), c) for c in self._cands if len(c) >= MIN_FUZZY_LEN), reverse=True)
        return [(s, self._target_of.get(c) or c, c in self._target_of) for s, c in scored[:limit]]

    def match(self, ocr_text: str) -> tuple[str, float] | None:
        """Trả (tên_mục_tiêu, điểm) nếu OCR là một mục tiêu, ngược lại None."""
        ocr = self._clean(ocr_text)
        if not ocr:
            return None

        rule = self._rule_hits(ocr)
        if rule:
            top = max(rule, key=lambda h: (h[0], len(h[1])))
            target = self._target_of.get(top[1])
            return (target, top[0]) if target else None  # khớp cấu trúc: top quyết định, không xét mơ hồ

        fuzzy = self._fuzzy_hits(ocr)
        if not fuzzy:
            return None
        fuzzy.sort(key=lambda h: (h[0], len(h[1])), reverse=True)
        best_score = fuzzy[0][0]
        for score, cand in fuzzy:  # top hoặc tên kém top không quá AMBIGUITY_MARGIN, ưu tiên theo thứ tự
            if score < best_score - AMBIGUITY_MARGIN:
                break
            target = self._target_of.get(cand)
            if target:
                return target, score
        return None

    def _rule_hits(self, ocr: str) -> list[tuple[float, str]]:
        padded = f" {ocr} "
        hits = []
        for cand in self._cands:
            if cand == ocr:
                hits.append((1.0, cand))
            elif f" {cand} " in padded:
                hits.append((PHRASE_SCORE, cand))
            elif len(ocr) >= MIN_TOKEN_LEN and len(self._tokens[cand]) > 1 and ocr in self._tokens[cand]:
                hits.append((TOKEN_SCORE, cand))
        if not hits and len(ocr) >= FRAGMENT_MIN_LEN:
            containing = [c for c in self._cands if ocr in c]
            if len(containing) == 1:  # duy nhất 1 tướng chứa mảnh này → nhận diện được an toàn
                hits.append((FRAGMENT_SCORE, containing[0]))
        return hits

    def _fuzzy_hits(self, ocr: str) -> list[tuple[float, str]]:
        if len(ocr) < MIN_FUZZY_LEN:
            return []
        texts = [ocr] + [w for w in ocr.split() if len(w) >= MIN_FUZZY_LEN and w != ocr]
        best: dict[str, float] = {}
        sm = SequenceMatcher(None, autojunk=False)
        for text in texts:
            sm.set_seq2(text)  # seq2 được cache nên đổi seq1 (tên) rất rẻ
            for cand in self._cands:
                if len(cand) < MIN_FUZZY_LEN:
                    continue
                sm.set_seq1(cand)
                if sm.real_quick_ratio() < self.min_ratio or sm.quick_ratio() < self.min_ratio:
                    continue
                score = sm.ratio()
                if score >= self.min_ratio and score > best.get(cand, 0.0):
                    best[cand] = score
        return [(s, c) for c, s in best.items()]
