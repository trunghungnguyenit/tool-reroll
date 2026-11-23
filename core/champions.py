"""Tải danh sách tướng TFT (mọi mùa, hai ngôn ngữ) và ảnh mẫu từ Riot Data Dragon."""

import json
import os
import queue
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import cv2
import numpy as np
import requests

from core import config as _config
from core.config import TEMPLATES_DIR, ensure_dirs, normalize_locale
from core.logging_setup import logger
from core.name_matcher import normalize_name

DDRAGON_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_TFT_CHAMP = "https://ddragon.leagueoflegends.com/cdn/{version}/data/{locale}/tft-champion.json"
DDRAGON_IMG = "https://ddragon.leagueoflegends.com/cdn/{version}/img/tft-champion/{filename}"

LOCALES = ("vi_VN", "en_US")  # hai ngôn ngữ luôn tải: tên hiển thị + tên ngôn ngữ kia (alias khớp OCR và tìm kiếm)
# Data Dragon chỉ có dữ liệu tướng TFT từ patch 13.x (các bản cũ hơn trả HTTP 403). Mùa cũ nằm ở các patch cũ chứ không có
# trong patch mới nhất, nên phải quét từng patch rồi gộp lại (xem load_all_champions).
MIN_TFT_MAJOR = 13
FETCH_WORKERS = 8
# Số ảnh chân dung tải cùng lúc. Mỗi ảnh ~200 KB và tốn ~0,7 s chờ mạng, nên tải lần lượt 237 ảnh mất gần 3 phút; 8 luồng còn ~30 giây.
PORTRAIT_WORKERS = 8
CATALOG_NAME = "champions_catalog.json"
CATALOG_SCHEMA = 1

# TFTSetTutorial, TFTSetEvent5YR... không có số ngay sau 'TFTSet' → không phải mùa
_SET_RE = re.compile(r"/Sets/TFTSet(\d+)/")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def tft_versions() -> list[str]:
    """Các patch có dữ liệu TFT (từ MIN_TFT_MAJOR), mới nhất trước."""
    resp = requests.get(DDRAGON_VERSIONS, timeout=15)
    resp.raise_for_status()
    found = [v for v in resp.json() if isinstance(v, str) and _VERSION_RE.match(v)]
    return sorted((v for v in found if version_key(v)[0] >= MIN_TFT_MAJOR), key=version_key, reverse=True)


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


def fetch_version(version: str) -> dict[str, dict]:
    """Mọi mục tướng của MỘT patch ở cả hai ngôn ngữ: {id: {names: {locale: tên}, tier, set, image}}. Bỏ mục không có tên hoặc cost.
    Một ngôn ngữ lỗi thì ném lỗi (không ghi nhận nửa vời). HTTP 403/404 = patch không có dữ liệu → {}."""
    try:
        per = {loc: _fetch_locale(version, loc) for loc in LOCALES}
    except requests.HTTPError as e:
        if getattr(e.response, "status_code", None) in (403, 404):
            return {}
        raise
    out: dict[str, dict] = {}
    for champ_id in per[LOCALES[1]].keys() | per[LOCALES[0]].keys():
        infos = [per[loc].get(champ_id) or {} for loc in LOCALES]
        base = next((i for i in infos if i.get("image")), None)
        tier = next((i["tier"] for i in infos if i.get("tier") is not None), None)
        names = {loc: (info.get("name") or "").strip() for loc, info in zip(LOCALES, infos)}
        if base is None or tier is None or not any(names.values()):
            continue
        out[champ_id] = {"names": names, "tier": tier, "set": set_of(champ_id), "image": base["image"]["full"]}
    return out


# ---------------------------------------------------------------------------------------------------------------
# Catalog: mọi tướng của mọi patch đã quét, gộp theo id (bản patch MỚI NHẤT chứa id đó thắng), lưu ở data/ để lần sau chỉ phải
# tải patch mới và dùng được cả khi offline.
# ---------------------------------------------------------------------------------------------------------------
def new_catalog() -> dict:
    return {"schema": CATALOG_SCHEMA, "versions": [], "champions": {}}


def merge_version(catalog: dict, version: str, data: dict[str, dict]) -> None:
    """Gộp dữ liệu một patch vào catalog và ghi nhận patch đó đã quét. Thứ tự gộp không quan trọng: mục của patch mới hơn luôn thắng."""
    for champ_id, info in data.items():
        old = catalog["champions"].get(champ_id)
        if old is None or version_key(version) >= version_key(old["version"]):
            catalog["champions"][champ_id] = {**info, "version": version}
    if version not in catalog["versions"]:
        catalog["versions"].append(version)


def catalog_entries(catalog: dict, locale: str) -> list[dict]:
    """Catalog → danh sách mục (mỗi id một mục): id, name (theo `locale`), alt_name (ngôn ngữ kia, rỗng nếu giống), tier, set, image_url."""
    locale = normalize_locale(locale)
    other = other_locale(locale)
    entries = []
    for champ_id, c in catalog["champions"].items():
        name = c["names"].get(locale) or c["names"].get(other) or ""
        alt = c["names"].get(other) or ""
        entries.append({
            "id": champ_id,
            "name": name,
            "alt_name": "" if alt == name else alt,
            "tier": c["tier"],
            "set": c["set"],
            "image_url": DDRAGON_IMG.format(version=c["version"], filename=c["image"]),
        })
    return entries


def _valid_catalog(data) -> bool:
    try:
        if data["schema"] != CATALOG_SCHEMA or not isinstance(data["versions"], list):
            return False
        if not all(isinstance(v, str) and _VERSION_RE.match(v) for v in data["versions"]):
            return False
        for cid, c in data["champions"].items():
            names = c["names"]
            ok = (isinstance(cid, str) and isinstance(c["image"], str) and isinstance(c["tier"], int)
                  and (c["set"] is None or isinstance(c["set"], int)) and isinstance(c["version"], str)
                  and _VERSION_RE.match(c["version"]) and all(isinstance(names[loc], str) for loc in LOCALES))
            if not ok:
                return False
    except (KeyError, TypeError, AttributeError):
        return False
    return True


def load_catalog() -> dict | None:
    """Catalog đã lưu; None nếu chưa có hoặc hỏng (hỏng thì quét lại từ đầu)."""
    try:
        data = json.loads((_config.DATA_DIR / CATALOG_NAME).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if _valid_catalog(data) and data["champions"] else None


def save_catalog(catalog: dict) -> None:
    ensure_dirs()
    path = _config.DATA_DIR / CATALOG_NAME
    tmp = path.with_name(path.name + ".tmp")
    stamp = datetime.now().isoformat(timespec="seconds")
    tmp.write_text(json.dumps({**catalog, "saved_at": stamp}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class LoadReport:
    versions_total: int = 0  # số patch có dữ liệu TFT
    versions_new: int = 0  # số patch vừa quét thêm lần này
    failed: list[str] = field(default_factory=list)  # patch lỗi mạng (lần mở sau thử lại)
    offline: bool = False  # không liên lạc được Data Dragon: đang dùng catalog đã lưu


_SAVE_EVERY = 10


def _scan_parallel(versions: list[str], should_stop) -> queue.Queue:
    """Tải các patch song song bằng luồng daemon (không chặn thoát app khi mạng treo). Kết quả (version, data|None, lỗi) vào hàng đợi."""
    work: queue.Queue = queue.Queue()
    results: queue.Queue = queue.Queue()
    for v in versions:
        work.put(v)

    def worker():
        while not should_stop():
            try:
                v = work.get_nowait()
            except queue.Empty:
                return
            try:
                results.put((v, fetch_version(v), None))
            except (requests.RequestException, ValueError, KeyError) as e:
                results.put((v, None, e))

    for _ in range(min(FETCH_WORKERS, len(versions))):
        threading.Thread(target=worker, daemon=True).start()
    return results


def load_all_champions(locale: str, on_update, should_stop=lambda: False, on_progress=None) -> LoadReport:
    """
    Nạp tướng của MỌI mùa có trong Data Dragon, ở cả hai ngôn ngữ. Trình tự (mỗi bước gọi on_update(entries) để giao diện hiện sớm):
      1. catalog đã lưu (nếu có) → hiện ngay, dùng được cả khi offline;
      2. patch mới nhất (một request mỗi ngôn ngữ) → có ngay các mùa gần đây;
      3. các patch cũ chưa quét, song song → bổ sung các mùa cũ; kết quả được lưu lại nên lần sau chỉ tải patch mới.
    Không có catalog mà cũng không tải được patch mới nhất thì ném lỗi mạng. on_progress(đã_xong, tổng) trong bước 3.
    """
    locale = normalize_locale(locale)
    catalog = load_catalog()
    cached = catalog is not None
    if cached:
        on_update(catalog_entries(catalog, locale))
    catalog = catalog or new_catalog()
    report = LoadReport()
    try:
        versions = tft_versions()
        report.versions_total = len(versions)
        done = set(catalog["versions"])
        todo = [v for v in versions if v not in done]
        if versions and versions[0] in todo:
            merge_version(catalog, versions[0], fetch_version(versions[0]))
            todo.remove(versions[0])
            report.versions_new += 1
            save_catalog(catalog)
            on_update(catalog_entries(catalog, locale))
    except (requests.RequestException, ValueError, KeyError, IndexError):
        if not cached:
            raise
        report.offline = True
        return report

    if todo and not should_stop():
        results = _scan_parallel(todo, should_stop)
        finished = 0
        while finished < len(todo) and not should_stop():
            try:
                version, data, error = results.get(timeout=0.2)
            except queue.Empty:
                continue
            finished += 1
            if error is not None:
                report.failed.append(version)
            else:
                merge_version(catalog, version, data)
                report.versions_new += 1
                if report.versions_new % _SAVE_EVERY == 0:
                    save_catalog(catalog)
            if on_progress:
                on_progress(finished, len(todo))
        if report.versions_new:
            save_catalog(catalog)
            on_update(catalog_entries(catalog, locale))
    return report


# ---------------------------------------------------------------------------------------------------------------
# Từ các mục (mỗi id một mục) sang danh sách THẺ (mỗi tên một thẻ), bộ lọc mùa và tìm kiếm.
# ---------------------------------------------------------------------------------------------------------------
def search_key(text: str) -> str:
    """Khóa so sánh khi gộp/tìm: bỏ dấu, hoa/thường, dấu nháy và khoảng trắng ("Kha'Zix" = "khazix" = "Kha Zix")."""
    return normalize_name(text or "").replace(" ", "")


def merge_champions(entries: list[dict]) -> list[dict]:
    """
    Gộp các mục thành thẻ, MỖI TÊN MỘT THẺ: cùng một tướng ở nhiều mùa (và tên viết hơi khác như 'RekSai'/'Rek'Sai' ở bản sự kiện)
    chỉ hiện một lần. Thẻ lấy dữ liệu (cost, ảnh) từ mùa mới nhất của tướng đó; `sets` là mọi mùa tướng có mặt (mới nhất trước),
    rỗng nếu chỉ có ở tutorial/sự kiện. `search` là khóa tìm kiếm (tên, tên ngôn ngữ kia). Sắp theo (tier, tên).
    """
    groups: dict[str, list[dict]] = {}
    for e in entries:
        name = (e.get("name") or "").strip()
        if name:
            groups.setdefault(search_key(name) or name.casefold(), []).append(e)
    cards = []
    for group in groups.values():
        in_sets = [e for e in group if e.get("set") is not None]
        best = max(in_sets, key=lambda e: e["set"]) if in_sets else group[0]
        sets = sorted({e["set"] for e in in_sets}, reverse=True)
        alt = (best.get("alt_name") or next((e["alt_name"] for e in group if e.get("alt_name")), "")).strip()
        name = best["name"].strip()
        cards.append({**best, "name": name, "alt_name": alt, "set": sets[0] if sets else None, "sets": sets,
                      "search": (search_key(name), search_key(alt))})
    return sorted(cards, key=lambda c: (c["tier"], c["name"]))


def latest_set(champions: list[dict]) -> int | None:
    """Mùa mới nhất có trong danh sách (None nếu rỗng)."""
    sets = [c["set"] for c in champions if c.get("set") is not None]
    return max(sets) if sets else None


def available_seasons(champions: list[dict]) -> list[int]:
    """Mọi mùa có tướng, mới nhất trước (để dựng danh sách chọn mùa)."""
    return sorted({s for c in champions for s in c.get("sets", ())}, reverse=True)


def visible_champions(champions: list[dict], seasons: set[int]) -> list[dict]:
    """Theo bộ lọc mùa: `seasons` rỗng = tất cả (kể cả tướng chỉ có ở tutorial/sự kiện); ngược lại tướng có mặt ở ít nhất một mùa đã chọn."""
    if not seasons:
        return list(champions)
    return [c for c in champions if seasons.intersection(c.get("sets", ()))]


def matches_query(champion: dict, query: str) -> bool:
    """Tên (hoặc tên ngôn ngữ kia) có chứa chuỗi gõ không — bỏ qua hoa/thường, dấu, dấu nháy, khoảng trắng. Chuỗi gõ trống = khớp hết."""
    key = search_key(query)
    if not key:
        return True
    own, alt = champion.get("search") or (search_key(champion["name"]), search_key(champion.get("alt_name", "")))
    return key in own or key in alt


def season_label(champion: dict, shown: int = 2) -> str:
    """Nhãn mùa gọn trên thẻ: 'M18 · M17 +2'; tướng chỉ có ở tutorial/sự kiện là 'Sự kiện'."""
    sets = champion.get("sets") or []
    if not sets:
        return "Sự kiện"
    label = " · ".join(f"M{s}" for s in sets[:shown])
    return label + (f" +{len(sets) - shown}" if len(sets) > shown else "")


def season_tooltip(champion: dict) -> str:
    sets = champion.get("sets") or []
    return "mùa " + ", ".join(str(s) for s in sets) if sets else "không thuộc mùa nào (tutorial/sự kiện)"


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


def run_parallel(items: list, fn, workers: int = PORTRAIT_WORKERS, should_stop=lambda: False) -> None:
    """Chạy fn(phần_tử) cho từng phần tử bằng tối đa `workers` luồng, lấy theo thứ tự danh sách (phần tử đầu được bắt đầu trước,
    nên danh sách xếp theo độ ưu tiên thì cái quan trọng được tải trước). Chỉ về khi hết việc hoặc should_stop() thành True (các
    việc đang chạy dở vẫn làm nốt). fn ném lỗi thì ghi log và đi tiếp phần tử khác, không làm chết cả đợt. Luồng daemon để mạng treo
    không chặn thoát app."""
    if not items:
        return
    work: queue.Queue = queue.Queue()
    for item in items:
        work.put(item)

    def worker():
        while not should_stop():
            try:
                item = work.get_nowait()
            except queue.Empty:
                return
            try:
                fn(item)
            except Exception:
                logger.exception("Lỗi khi xử lý %r", item)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, min(workers, len(items))))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def load_template_image(path: Path) -> np.ndarray | None:
    """Đọc file ảnh tướng từ ổ đĩa thành mảng OpenCV (đọc qua numpy nên đường dẫn có dấu vẫn chạy)."""
    try:
        data = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)  # không dùng np.fromfile: nó cần FILE* của CRT (tối đa 512 luồng)
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
    tmp.write_bytes(buf.tobytes())
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
