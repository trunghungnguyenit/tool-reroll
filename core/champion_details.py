"""Chi tiết tướng TFT: chỉ số, kỹ năng, hệ (tộc/ngành) và vai trò, lấy từ CommunityDragon (bản sao dữ liệu client của Riot).

Data Dragon (core/champions.py) chỉ có tên, cost và ảnh nên không đủ. CommunityDragon có thêm chỉ số và kỹ năng, nhưng có hai giới hạn
phải nói rõ với người dùng: (1) KHÔNG có đồ gợi ý cho từng tướng; (2) mô tả kỹ năng của mùa mới thường thiếu con số vì Riot không công bố
công thức tính. Chỗ thiếu hiện `[?]` thay vì bịa số, và mục tướng đánh dấu `complete=False`.

Mỗi lần mở app tải lại tối đa một lần/ngày (file ~24 MB nhưng nén gzip, vài giây); kết quả rút gọn lưu ở data/ (~vài trăm KB) nên các lần
sau và khi offline đọc ngay từ đó."""

import html
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from core import config as _config
from core.champions import search_key
from core.config import ensure_dirs

CDRAGON_URL = "https://raw.communitydragon.org/latest/cdragon/tft/{locale}.json"
FALLBACK_LOCALE = "en_US"  # ngôn ngữ chưa có file thì dùng tiếng Anh
DETAILS_SCHEMA = 2  # tăng khi đổi cách làm sạch mô tả: bản đã lưu theo cách cũ bị bỏ và tải lại (2: bỏ {{...}}, @biến dài)
MAX_AGE = timedelta(hours=24)
MISSING = "[?]"  # con số mô tả kỹ năng mà dữ liệu Riot không có

STAT_KEYS = ("hp", "damage", "armor", "magicResist", "attackSpeed", "range", "initialMana", "mana", "critChance")

# Biểu tượng chỉ số trong mô tả kỹ năng (%i:scaleAP% ...) → nhãn chữ. Biểu tượng lạ thì bỏ.
_ICON_LABELS = {
    "scaleAP": "AP", "scaleAD": "AD", "scaleHealth": "Máu", "scaleArmor": "Giáp", "scaleMR": "Kháng phép",
    "scaleAS": "Tốc đánh", "scaleCrit": "Chí mạng", "scaleCritMult": "ST chí mạng", "scaleRange": "Tầm đánh",
    "scaleSouls": "Linh hồn", "TFTBaseAD": "AD gốc",
}

_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]*>")
_ICON_GROUP_RE = re.compile(r"(?:%i:\w+%)+")
_ICON_RE = re.compile(r"%i:(\w+)%")
_PLACEHOLDER_RE = re.compile(r"@([^@\s]{1,200})@")  # có biến dài kiểu @TFTUnitProperty.:TFT15_..._FullPotential_...@
_STRING_REF_RE = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
_REF_RE = re.compile(r"([A-Za-z0-9_.]+)(?:\*(-?\d+(?:\.\d+)?))?")


def _fmt_number(x: float) -> str:
    text = f"{round(float(x), 2):.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _variable_table(variables) -> dict[str, list]:
    table: dict[str, list] = {}
    for v in variables or []:
        if isinstance(v, dict) and isinstance(v.get("name"), str) and isinstance(v.get("value"), list):
            table[v["name"].lower()] = v["value"]
    return table


def _resolve(ref: str, table: dict[str, list]) -> str | None:
    """`Tên` hoặc `Tên*100` → giá trị theo sao (1/2/3 sao, nối bằng ' / '); None nếu không tính được từ dữ liệu."""
    m = _REF_RE.fullmatch(ref)
    values = table.get(m.group(1).lower()) if m else None
    if not values:
        return None
    mult = float(m.group(2)) if m.group(2) else 1.0
    stars = values[1:4] if len(values) >= 4 else values  # chỉ số 0 và 5+ là chỗ đệm; 1..3 là 1/2/3 sao
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in stars):
        return None
    shown = [_fmt_number(x * mult) for x in stars]
    return shown[0] if len(set(shown)) == 1 else " / ".join(shown)


def clean_description(desc, variables=None) -> tuple[str, bool]:
    """Mô tả kỹ năng thô của Riot → chữ thường đọc được. Trả (văn bản, đủ_số): đủ_số=False nếu còn con số chưa tính được (hiện `[?]`).

    Bỏ thẻ định dạng (<br> thành xuống dòng), đổi biểu tượng chỉ số (%i:scaleAP%) thành chữ (AP), điền @Biến@ bằng giá trị 1/2/3 sao khi
    dữ liệu có, còn lại là `[?]`."""
    if not isinstance(desc, str) or not desc.strip():
        return "", True
    text = _TAG_RE.sub("", _BR_RE.sub("\n", desc))
    text = html.unescape(text).replace("\xa0", " ").replace("\\n", "\n")  # một số mô tả có chuỗi '\n' dạng chữ chứ không phải xuống dòng

    def icons(m):
        labels = [_ICON_LABELS[n] for n in _ICON_RE.findall(m.group(0)) if n in _ICON_LABELS]
        return "+".join(dict.fromkeys(labels))

    text = _ICON_GROUP_RE.sub(icons, text)
    text = re.sub(r"\(\s*\)", "", text)
    table = _variable_table(variables)
    complete = True

    def string_ref(m):
        """{{Tên_chuỗi}}: tham chiếu sang một chuỗi khác của game mà dữ liệu không kèm theo. Từ khóa (TFT_Keyword_*) chỉ là dòng chú
        giải nên bỏ; còn lại (vd cả đoạn mô tả một chiêu) là phần nội dung bị thiếu."""
        nonlocal complete
        if m.group(1).startswith("TFT_Keyword_"):
            return ""
        complete = False
        return MISSING

    text = _STRING_REF_RE.sub(string_ref, text)

    def fill(m):
        nonlocal complete
        value = _resolve(m.group(1), table)
        if value is None:
            complete = False
            return MISSING
        return value

    text = _PLACEHOLDER_RE.sub(fill, text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, complete


# ---------------------------------------------------------------------------------------------------------------
# Rút gọn dữ liệu thô: mỗi tên tướng một mục, lấy từ mùa mới nhất có tướng đó.
# ---------------------------------------------------------------------------------------------------------------
def _entry(champ: dict, set_no: int) -> dict | None:
    name = champ.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    ability = champ.get("ability") if isinstance(champ.get("ability"), dict) else {}
    desc, complete = clean_description(ability.get("desc"), ability.get("variables"))
    raw_stats = champ.get("stats") if isinstance(champ.get("stats"), dict) else {}
    stats = {k: raw_stats[k] for k in STAT_KEYS if isinstance(raw_stats.get(k), (int, float)) and not isinstance(raw_stats.get(k), bool)}
    traits = [t.strip() for t in (champ.get("traits") or []) if isinstance(t, str) and t.strip()]
    role = champ.get("role") if isinstance(champ.get("role"), str) else ""
    cost = champ.get("cost") if isinstance(champ.get("cost"), int) else None
    return {"name": name.strip(), "set": set_no, "cost": cost, "role": role, "traits": traits, "stats": stats,
            "ability": {"name": (ability.get("name") or "").strip() if isinstance(ability.get("name"), str) else "",
                        "desc": desc, "complete": complete}}


def _richness(e: dict) -> tuple[bool, bool]:
    return bool(e["ability"]["desc"]), bool(e["traits"])


def parse_catalog(raw: dict) -> dict[str, dict]:
    """File CommunityDragon → {search_key(tên): mục}. Cùng tên ở nhiều mùa thì lấy mùa mới nhất; trùng tên trong một mùa (quái, bản
    biến thể) thì lấy mục đầy đủ hơn (có kỹ năng và hệ)."""
    out: dict[str, dict] = {}
    sets = raw.get("sets") if isinstance(raw, dict) else None
    if not isinstance(sets, dict):
        raise ValueError("dữ liệu CommunityDragon không có mục 'sets'")
    for key, data in sets.items():
        try:
            set_no = int(key)
        except (TypeError, ValueError):
            continue
        for champ in (data.get("champions") if isinstance(data, dict) else None) or []:
            e = _entry(champ, set_no) if isinstance(champ, dict) else None
            if e is None:
                continue
            k = search_key(e["name"])
            old = out.get(k)
            if old is None or set_no > old["set"] or (set_no == old["set"] and _richness(e) > _richness(old)):
                out[k] = e
    return out


# ---------------------------------------------------------------------------------------------------------------
# Tải + lưu đệm
# ---------------------------------------------------------------------------------------------------------------
def cache_path(locale: str):
    return _config.DATA_DIR / f"champion_details_{locale}.json"


def _valid_cache(data) -> bool:
    try:
        if data["schema"] != DETAILS_SCHEMA or not isinstance(data["champions"], dict) or not data["champions"]:
            return False
        datetime.fromisoformat(data["saved_at"])
        return all(isinstance(e["name"], str) and isinstance(e["stats"], dict) and isinstance(e["traits"], list)
                   and isinstance(e["ability"]["desc"], str) for e in data["champions"].values())
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def load_cache(locale: str) -> tuple[dict[str, dict], datetime] | None:
    """(các mục, giờ lưu) của file đệm; None nếu chưa có hoặc hỏng (hỏng thì tải lại)."""
    try:
        data = json.loads(cache_path(locale).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return (data["champions"], datetime.fromisoformat(data["saved_at"])) if _valid_cache(data) else None


def save_cache(locale: str, champions: dict[str, dict], now: datetime) -> None:
    ensure_dirs()
    path = cache_path(locale)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"schema": DETAILS_SCHEMA, "saved_at": now.isoformat(timespec="seconds"), "champions": champions},
                              ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # ghi dở không để lại file hỏng


def fetch_catalog(locale: str, timeout: int = 90) -> dict[str, dict]:
    """Tải và rút gọn dữ liệu của `locale`; HTTP 404 (chưa có ngôn ngữ đó) thì dùng tiếng Anh. Ném lỗi mạng/định dạng cho nơi gọi."""
    resp = requests.get(CDRAGON_URL.format(locale=locale.lower()), timeout=timeout)
    if resp.status_code == 404 and locale != FALLBACK_LOCALE:
        resp = requests.get(CDRAGON_URL.format(locale=FALLBACK_LOCALE.lower()), timeout=timeout)
    resp.raise_for_status()
    return parse_catalog(resp.json())


@dataclass
class Details:
    champions: dict[str, dict]
    offline: bool = False  # không tải mới được: đang dùng bản đã lưu (có thể cũ)


def get_details(locale: str, now: datetime | None = None, force: bool = False) -> Details:
    """Dữ liệu chi tiết: bản đã lưu còn mới (dưới MAX_AGE) thì dùng ngay; không thì tải lại. Tải lỗi mà còn bản cũ thì dùng bản cũ
    (offline=True); không có gì cả thì ném lỗi mạng."""
    now = now or datetime.now()
    cached = load_cache(locale)
    if cached and not force and now - cached[1] < MAX_AGE:
        return Details(cached[0])
    try:
        champions = fetch_catalog(locale)
        if not champions:
            raise ValueError("dữ liệu chi tiết trống")
        save_cache(locale, champions, now)
        return Details(champions)
    except (requests.RequestException, ValueError, OSError):
        if cached:
            return Details(cached[0], offline=True)
        raise


def find_detail(champions: dict[str, dict] | None, card: dict) -> dict | None:
    """Mục chi tiết của một thẻ tướng (khớp theo tên rồi tên ngôn ngữ kia); None nếu không có (vd mùa cũ/sự kiện)."""
    if not champions:
        return None
    for name in (card.get("name"), card.get("alt_name")):
        if name and (found := champions.get(search_key(name))):
            return found
    return None


# ---------------------------------------------------------------------------------------------------------------
# Chữ hiển thị
# ---------------------------------------------------------------------------------------------------------------
_ROLE_RE = re.compile(r"(AD|AP|H)?(Tank|Fighter|Caster|Carry|Reaper|Specialist)")
_ROLE_DAMAGE = {"AD": "vật lý", "AP": "phép", "H": "hỗn hợp"}


def role_label(role: str) -> str:
    """Vai trò thô của Riot ('ADFighter', 'APReaper'...) → tiếng Việt, vd 'Đấu sĩ (vật lý)'. 'Reaper' là kiểu sát thủ lao vào
    (Zed, Talon, Rengar, Akali...); 'Caster'/'Carry' vật lý là xạ thủ, phép là pháp sư. Không nhận ra thì giữ nguyên chữ gốc."""
    m = _ROLE_RE.search(role or "")
    if not m:
        return role or ""
    dmg, kind = m.groups()
    if kind in ("Caster", "Carry"):
        label = {"AD": "Xạ thủ", "AP": "Pháp sư"}.get(dmg or "", "Chủ lực")
    else:
        label = {"Tank": "Đỡ đòn", "Fighter": "Đấu sĩ", "Reaper": "Sát thủ", "Specialist": "Chuyên biệt"}[kind]
    return f"{label} ({_ROLE_DAMAGE[dmg]})" if dmg else label



def stat_rows(entry: dict) -> list[tuple[str, str]]:
    """Chỉ số cơ bản (tướng 1 sao) thành các cặp (nhãn, giá trị) để hiện; bỏ chỉ số không có trong dữ liệu."""
    s = entry.get("stats") or {}
    rows: list[tuple[str, str]] = []

    def add(label, key, fmt):
        if key in s:
            rows.append((label, fmt(s[key])))

    add("Máu", "hp", _fmt_number)
    add("Sát thương", "damage", _fmt_number)
    add("Giáp", "armor", _fmt_number)
    add("Kháng phép", "magicResist", _fmt_number)
    add("Tốc đánh", "attackSpeed", _fmt_number)
    add("Tầm đánh", "range", lambda v: f"{_fmt_number(v)} ô")
    if "mana" in s:
        rows.append(("Năng lượng", f"{_fmt_number(s.get('initialMana', 0))} / {_fmt_number(s['mana'])}"))
    add("Chí mạng", "critChance", lambda v: f"{_fmt_number(v * 100)}%")
    return rows
