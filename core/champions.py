"""Tải danh sách tướng TFT và ảnh mẫu từ Riot Data Dragon."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import cv2
import numpy as np
import requests

from core import config as _config
from core.config import DEFAULT_LOCALE, TEMPLATES_DIR, ensure_dirs, normalize_locale
from core.name_matcher import normalize_name

DDRAGON_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_TFT_CHAMP = "https://ddragon.leagueoflegends.com/cdn/{version}/data/{locale}/tft-champion.json"
DDRAGON_IMG = "https://ddragon.leagueoflegends.com/cdn/{version}/img/tft-champion/{filename}"

# TFTSetTutorial, TFTSetEvent5YR... không có số ngay sau 'TFTSet' → không phải mùa
_SET_RE = re.compile(r"/Sets/TFTSet(\d+)/")


def _latest_version() -> str:
    """Lấy phiên bản patch mới nhất từ Data Dragon."""
    resp = requests.get(DDRAGON_VERSIONS, timeout=15)
    resp.raise_for_status()
    versions = resp.json()
    for v in versions:
        if re.match(r"^\d+\.\d+\.\d+$", v):
            return v
    return versions[0]


def other_locale(locale: str) -> str:
    """Ngôn ngữ còn lại dùng làm alias khi khớp OCR (client game có thể khác ngôn ngữ danh sách)."""
    return "en_US" if locale != "en_US" else "vi_VN"


def _fetch_locale(version: str, locale: str) -> dict:
    resp = requests.get(DDRAGON_TFT_CHAMP.format(version=version, locale=locale), timeout=20)
    resp.raise_for_status()
    return resp.json()["data"]


def set_of(champ_id: str) -> int | None:
    """Số mùa (vd 18) lấy từ id Data Dragon; None cho tutorial/sự kiện/không rõ."""
    m = _SET_RE.search(champ_id)
    return int(m.group(1)) if m else None


def fetch_champion_list(locale: str = DEFAULT_LOCALE) -> list[dict]:
    """
    Tải TOÀN BỘ mục tướng từ Data Dragon (mọi mùa, tutorial, sự kiện) theo ngôn ngữ `locale`, kèm tên ở ngôn ngữ
    còn lại (`alt_name`, rỗng nếu không tải được). Dùng playable_champions() để lấy danh sách hiển thị.
    Mỗi mục: id, name (đã strip), alt_name, tier, set (int|None), image_url.
    """
    locale = normalize_locale(locale)
    version = _latest_version()
    data = _fetch_locale(version, locale)
    try:
        alt = _fetch_locale(version, other_locale(locale))
    except (requests.RequestException, ValueError, KeyError):
        alt = {}  # không có alias vẫn dùng được, chỉ mất khả năng khớp tên ngôn ngữ kia

    entries = []
    for champ_id, info in data.items():
        name = (info.get("name") or "").strip()
        tier = info.get("tier")
        if not name or tier is None:
            continue
        alt_name = ((alt.get(champ_id) or {}).get("name") or "").strip()
        entries.append(
            {
                "id": champ_id,
                "name": name,
                "alt_name": "" if alt_name == name else alt_name,
                "tier": tier,
                "set": set_of(champ_id),
                "image_url": DDRAGON_IMG.format(version=version, filename=info["image"]["full"]),
            }
        )
    return entries


def playable_champions(entries: list[dict]) -> list[dict]:
    """
    Tướng chọn được: chỉ các mục thuộc một mùa (bỏ tutorial/sự kiện). Cùng tên ở nhiều mùa thì giữ bản của mùa
    mới nhất (đúng nghệ thuật cho ảnh mẫu). Sắp theo (tier, tên).
    """
    best: dict[str, dict] = {}
    for e in entries:
        if e.get("set") is None:
            continue
        key = e["name"].strip().casefold()
        if key not in best or e["set"] > best[key]["set"]:
            best[key] = e
    return sorted(best.values(), key=lambda c: (c["tier"], c["name"]))


def latest_set(champions: list[dict]) -> int | None:
    """Mùa mới nhất có trong danh sách (None nếu rỗng)."""
    sets = [c["set"] for c in champions if c.get("set") is not None]
    return max(sets) if sets else None


def visible_champions(champions: list[dict], show_old: bool) -> list[dict]:
    """Danh sách hiển thị: chỉ mùa mới nhất, hoặc mọi mùa nếu show_old."""
    if show_old:
        return list(champions)
    latest = latest_set(champions)
    return [c for c in champions if c["set"] == latest]


def selection_keys(saved_names: list[str]) -> set[str]:
    """Tên đã lưu trong config → khóa chuẩn hóa để khôi phục lựa chọn (bỏ dấu cách thừa, dấu, hoa/thường)."""
    return {normalize_name(s) for s in saved_names if isinstance(s, str) and normalize_name(s)}


def is_selected(champion: dict, keys: set[str]) -> bool:
    """Tướng có nằm trong lựa chọn đã lưu không — khớp theo tên hiển thị hoặc tên ngôn ngữ kia."""
    if normalize_name(champion["name"]) in keys:
        return True
    alt = champion.get("alt_name") or ""
    return bool(alt) and normalize_name(alt) in keys


def reference_names(entries: list[dict]) -> list[str]:
    """Mọi tên tướng (cả hai ngôn ngữ, mọi mùa) để so OCR — nhiều tên hơn thì càng ít nhận nhầm."""
    names = set()
    for e in entries:
        for n in (e.get("name"), e.get("alt_name")):
            if n and n.strip():
                names.add(n.strip())
    return sorted(names)


def alias_groups(entries: list[dict]) -> list[list[str]]:
    """Các cặp [tên ngôn ngữ danh sách, tên ngôn ngữ kia] của cùng một tướng."""
    seen, groups = set(), []
    for e in entries:
        name, alt = e["name"].strip(), (e.get("alt_name") or "").strip()
        if alt and alt != name and (name, alt) not in seen:
            seen.add((name, alt))
            groups.append([name, alt])
    return groups


def aliases_for_targets(targets: list[str], groups: list[list[str]]) -> dict[str, list[str]]:
    """Với mỗi tên mục tiêu, các tên khác của cùng tướng (ngôn ngữ kia) — không có alias thì không có khóa."""
    index: dict[str, list[str]] = {}
    for group in groups:
        for name in group:
            index.setdefault(normalize_name(name), []).extend(n for n in group if n != name)
    result = {}
    for t in targets:
        found = list(dict.fromkeys(index.get(normalize_name(t), [])))
        if found:
            result[t] = found
    return result


CHAMPION_CACHE_NAME = "champions_cache.json"


def save_champion_cache(entries: list[dict]) -> None:
    """Lưu mọi tên tướng và cặp alias để lần sau offline vẫn so khớp OCR đủ tên (ghi nguyên tử)."""
    ensure_dirs()
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "names": reference_names(entries),
        "groups": alias_groups(entries),
    }
    path = _config.DATA_DIR / CHAMPION_CACHE_NAME
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_champion_cache() -> tuple[list[str], list[list[str]]] | None:
    """Đọc (tên, nhóm alias) đã cache; None nếu chưa có hoặc file hỏng."""
    try:
        data = json.loads((_config.DATA_DIR / CHAMPION_CACHE_NAME).read_text(encoding="utf-8-sig"))
        raw_names, raw_groups = data["names"], data.get("groups", [])
        if not isinstance(raw_names, list) or not isinstance(raw_groups, list):  # chuỗi sẽ bị duyệt từng ký tự
            return None
        names = [n for n in raw_names if isinstance(n, str) and n.strip()]
        groups = [[n for n in g if isinstance(n, str) and n.strip()] for g in raw_groups if isinstance(g, list)]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return (names, [g for g in groups if len(g) >= 2]) if names else None


def safe_filename(name: str) -> str:
    """Tên tướng → tên file an toàn trên Windows (bỏ ký tự cấm, khoảng trắng/dấu chấm ở hai đầu)."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return safe or "champion"


def template_path(name: str, url: str) -> Path:
    """Đường dẫn file ảnh portrait đã/sẽ tải của một tướng (tên kèm tên ảnh gốc nên mỗi mùa một file)."""
    image_stem = safe_filename(Path(urlparse(url).path).stem)
    return TEMPLATES_DIR / f"{safe_filename(name)}__{image_stem}.png"


def download_template(name: str, url: str) -> Path | None:
    """
    Tải ảnh portrait tướng về data/templates/, bỏ qua nếu đã có. Tên file kèm tên ảnh gốc của Data Dragon
    (vd 'Aatrox__TFT18_Aatrox.png') nên mỗi mùa có ảnh riêng, không dùng nhầm ảnh mùa cũ đã cache.
    """
    ensure_dirs()
    path = template_path(name, url)
    if path.exists():
        return path
    tmp = path.with_name(path.name + ".part")
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        tmp.write_bytes(resp.content)
        os.replace(tmp, path)  # ghi dở (ngắt giữa chừng) không để lại file hỏng bị coi là "đã có"
        return path
    except (requests.RequestException, OSError):
        tmp.unlink(missing_ok=True)
        return None


def load_template_image(path: Path) -> np.ndarray | None:
    """Đọc file ảnh tướng từ ổ đĩa thành mảng OpenCV (đọc qua numpy nên đường dẫn có dấu vẫn chạy)."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def save_custom_template(src_path: str, name: str) -> Path:
    """
    Lưu ảnh upload cho tướng `name` thành data/templates/custom_<tên>.png.
    Kiểm tra đọc được ảnh và chuyển sang PNG thật (nguồn có thể là jpg/webp). Ném ValueError nếu không đọc được.
    """
    img = load_template_image(Path(src_path))
    if img is None:
        raise ValueError("Không đọc được file ảnh (hỏng hoặc không phải ảnh).")
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Không chuyển được ảnh sang PNG.")
    ensure_dirs()
    dest = TEMPLATES_DIR / f"custom_{safe_filename(name)}.png"
    tmp = dest.with_name(dest.name + ".part")
    buf.tofile(str(tmp))
    os.replace(tmp, dest)
    return dest


def prepare_shop_template(full_img: np.ndarray, size: int = 64) -> np.ndarray:
    """Cắt vuông giữa ảnh tướng và resize về size×size để so khớp trong shop."""
    h, w = full_img.shape[:2]
    side = min(h, w)
    y0 = (h - side) // 2
    x0 = (w - side) // 2
    cropped = full_img[y0 : y0 + side, x0 : x0 + side]
    return cv2.resize(cropped, (size, size), interpolation=cv2.INTER_AREA)
