"""Генерация самодостаточного HTML-отчёта по результатам поиска.

Отчёт — один HTML-файл, который можно переслать кому угодно: получатель
открывает его в браузере и видит карточки с фото, ценами, размерами и ссылками
на POIZON. Стили встроены; фото по умолчанию грузятся с CDN сайта (быстро, файл
лёгкий), но их можно «вшить» в файл через embed_images для полной автономности.

Отчёты складываются в `result/<бренд>-<размер>-<дата>/index.html`.
"""

from __future__ import annotations

import base64
import html
import math
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from .sizechart import (
    CM,
    EU,
    MM,
    RU,
    UK,
    US_MEN,
    US_WOMEN,
    normalize_scale,
    resolve_query_scale,
)

ROOT = Path(__file__).resolve().parent.parent
RESULT_DIR = ROOT / "result"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_SITE_URL = "https://www.thepoizon.ru"

#: Домены, с которых разрешено скачивать фото для автономного отчёта.
#: Результаты для отчёта присылает браузер, поэтому без этого списка сервер
#: скачал бы что угодно — в том числе `file://` с локального диска.
_IMAGE_HOSTS = ("thepoizon.ru", "poizon.com", "dewu.com", "dewucdn.com")
#: Схемы, по которым фото скачиваются в отчёт. Только https: ответ по
#: открытому http мог бы подменить кто угодно на пути запроса.
_IMAGE_SCHEMES = ("https",)
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_DATA_IMAGE_RE = re.compile(
    r"^data:image/[a-z0-9.+-]+;base64,[a-z0-9+/]+=*$", re.IGNORECASE
)
#: Числовые поля результата: в отчёт они приходят из JSON браузера.
_NUMERIC_FIELDS = ("price", "converted_eu", "converted_cm", "converted_foot")


def _num(value: str) -> str:
    """42.5 → «42,5» для человекочитаемого вывода."""
    if value in (None, ""):
        return ""
    text = f"{float(value):g}" if _is_number(value) else str(value)
    return text.replace(".", ",")


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _money(match: dict) -> str:
    if match.get("price_text"):
        return match["price_text"]
    price = match.get("price")
    if price is None:
        return "—"
    return f"{price:,.0f} ₽".replace(",", " ")


def _thumb(url: str, size: int = 360) -> str:
    """CDN-ссылка на превью нужного размера (Aliyun OSS)."""
    if not url or "x-oss-process" in url or url.endswith(".svg"):
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}x-oss-process=image/resize,s_{size}/format,webp"


def _poizon_label(match: dict) -> str:
    sizes = match.get("sizes") or {}
    parts = [f"{scale} {value}" for scale, value in sizes.items()]
    return " / ".join(parts) or (
        f"{match.get('size', '')} {match.get('matched_scale', '')}".strip()
    )


def _is_web_url(url: str) -> bool:
    return urlsplit(url).scheme.lower() in ("http", "https")


def _is_image_host(url: str) -> bool:
    """Картинка лежит на CDN сайта и берётся по https — только такие качаем."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:  # кривой адрес (например, «http://[x»)
        return False
    if parts.scheme.lower() not in _IMAGE_SCHEMES:
        return False
    return any(host == d or host.endswith("." + d) for d in _IMAGE_HOSTS)


class _AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Редирект — только на разрешённый CDN; список проверяется на каждом шаге.

    Иначе стандартный обработчик urllib увёл бы запрос с CDN куда угодно
    (localhost, адреса локальной сети), а ответ image/* попал бы в отчёт.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_image_host(newurl):
            return None  # urllib превратит это в HTTPError — картинки не будет
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_image(request: urllib.request.Request, timeout: float):
    """Открывает URL картинки; редиректы проходят через список разрешённых."""
    opener = urllib.request.build_opener(_AllowlistRedirectHandler)
    return opener.open(request, timeout=timeout)


def _safe_link(url: Any) -> str:
    """Ссылка на товар: только http(s) или путь сайта, иначе «#».

    Отбрасывает `javascript:` и прочие схемы, которые иначе исполнились бы
    при клике по карточке.
    """
    url = str(url or "").strip()
    if url.startswith("/") and not url.startswith("//"):
        return _SITE_URL + url
    return url if _is_web_url(url) else "#"


def _clean(match: Any) -> dict:
    """Приводит строку результата к ожидаемым типам.

    Отчёт строится из присланного браузером JSON: число может прийти строкой,
    а мусорное значение не должно ронять рендер всего отчёта.
    """
    match = dict(match) if isinstance(match, dict) else {}
    for key in _NUMERIC_FIELDS:
        value = match.get(key)
        try:
            number = float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            number = None
        match[key] = number if number is not None and math.isfinite(number) else None
    if not isinstance(match.get("sizes"), dict):
        match["sizes"] = {}
    return match


def _fetch_data_uri(url: str) -> Optional[str]:
    """Скачивает картинку с CDN сайта и кодирует в data: URI."""
    if not _is_image_host(url):
        return None
    try:
        req = urllib.request.Request(_thumb(url, 360), headers={"User-Agent": _UA})
        with _open_image(req, timeout=20) as resp:
            raw = resp.read(_MAX_IMAGE_BYTES + 1)
            ctype = resp.headers.get_content_type()
    except Exception:  # noqa: BLE001 — картинка не критична для отчёта
        return None
    if len(raw) > _MAX_IMAGE_BYTES or not ctype.startswith("image/"):
        return None
    return f"data:{ctype};base64,{base64.b64encode(raw).decode('ascii')}"


def slugify(text: str) -> str:
    """«New Balance» → «new-balance» для имени папки."""
    import unicodedata

    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "poizon"


# ------------------------------------------------------------------ рендер

_STYLE = """
:root{--paper:#F5F1E6;--ink:#20221F;--ink-soft:#5B5C54;--green:#2F6B4F;
--green-soft:#DCE7DE;--ochre:#B9782E;--ochre-soft:#F1E1C8;--brick:#A2402F;
--line:#CFC7AE;--card:#FCFAF3;}
*{box-sizing:border-box;}
body{margin:0;background:var(--paper);color:var(--ink);padding:0 0 60px;
font-family:'Segoe UI',system-ui,-apple-system,sans-serif;line-height:1.5;}
.wrap{max-width:1080px;margin:0 auto;padding:0 22px;}
header{padding:40px 22px 20px;max-width:1080px;margin:0 auto;}
.eyebrow{font-family:'Consolas',monospace;font-size:12px;letter-spacing:.14em;
text-transform:uppercase;color:var(--green);margin-bottom:10px;}
h1{font-size:30px;letter-spacing:-.02em;margin:0 0 8px;}
h1 span{color:var(--ochre);}
.meta{color:var(--ink-soft);font-size:14.5px;margin:0;}
.meta b{color:var(--ink);}
.summary{background:var(--card);border:1px solid var(--line);
border-left:4px solid var(--green);padding:12px 18px;margin:18px 0 6px;font-size:14px;}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:18px 0 14px;}
.toolbar label{font-size:13.5px;color:var(--ink-soft);}
.toolbar select,.toolbar input{padding:6px 10px;border:1px solid var(--line);
background:#fff;font-family:inherit;font-size:14px;}
.toolbar .count{margin-left:auto;font-family:'Consolas',monospace;font-size:12px;color:var(--ink-soft);}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(232px,1fr));gap:14px;}
.card{background:var(--card);border:1px solid var(--line);display:flex;flex-direction:column;}
.imgbox{aspect-ratio:1;background:#fff;border-bottom:1px solid var(--line);
display:flex;align-items:center;justify-content:center;overflow:hidden;}
.imgbox img{max-width:100%;max-height:100%;object-fit:contain;}
.imgbox .noimg{font-size:44px;opacity:.35;}
.body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:8px;flex:1;}
.title{font-size:13.5px;line-height:1.35;max-height:2.7em;overflow:hidden;
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;}
.chips{display:flex;flex-wrap:wrap;gap:5px;}
.chip{font-family:'Consolas',monospace;font-size:11px;padding:2px 8px;
border:1px solid var(--line);background:#EDE7D6;color:var(--ink-soft);}
.chip.size{background:var(--green-soft);color:var(--green);font-weight:600;}
.chip.fit{background:var(--ochre-soft);color:var(--ochre);}
.chip.approx{background:#F7E8E4;color:var(--brick);}
.price-row{display:flex;justify-content:space-between;align-items:baseline;margin-top:auto;}
.price{font-family:'Consolas',monospace;font-weight:700;font-size:18px;}
.delivery{font-size:11.5px;color:var(--ink-soft);}
.card a.open{text-align:center;font-weight:600;font-size:13px;padding:8px 4px;
border:1px solid var(--line);text-decoration:none;color:var(--ink);}
.card a.open:hover{border-color:var(--green);color:var(--green);}
footer{max-width:1080px;margin:30px auto 0;padding:16px 22px;color:var(--ink-soft);
font-size:12.5px;border-top:1px solid var(--line);}
""".strip()


def build_report_html(matches: list[dict], meta: dict) -> str:
    """Собирает полный HTML-документ отчёта."""
    esc = html.escape
    matches = [_clean(m) for m in matches]
    brand = str(meta.get("brand") or "—")
    generated = meta.get("generated_at") or time.strftime("%d.%m.%Y %H:%M")

    prices = [m["price"] for m in matches if m.get("price") is not None]
    price_line = ""
    if prices:
        lo = f"{min(prices):,.0f}".replace(",", " ")
        hi = f"{max(prices):,.0f}".replace(",", " ")
        price_line = f" · цены от <b>{lo} ₽</b> до <b>{hi} ₽</b>"

    eus = sorted({m.get("converted_eu") for m in matches if m.get("converted_eu")})
    eu_line = ", ".join(f"EU {_num(e)}" for e in eus) if eus else ""

    size_input = meta.get("size_input") or ""
    scale = str(meta.get("scale") or "").upper()
    if scale in ("CM", "СМ") and size_input:
        req = f"длина стопы <b>{esc(str(size_input))} см</b>"
    elif size_input:
        req = f"размер <b>{esc(str(size_input))} {esc(scale)}</b>"
    else:
        req = ""
    gender = "женская сетка" if meta.get("gender") == "women" else "мужская сетка"

    cards = "\n".join(_render_card(m, esc) for m in matches)
    tip = str(next((m.get("size_tip") for m in matches if m.get("size_tip")), ""))
    approx = any(not m.get("exact_conversion", True) for m in matches)

    notes = []
    if eu_line:
        notes.append(f"Запрошено: {req} → {eu_line}")
    if approx:
        notes.append("«≈» — перевод размера приблизительный, сверьте по ссылке.")
    if tip:
        notes.append(f"Посадка (совет сайта): {esc(tip)}")

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>POIZON · {esc(brand)} · подбор по размеру</title>
<style>{_STYLE}</style>
</head>
<body>
<header>
  <div class="eyebrow">POIZON · отчёт парсера</div>
  <h1>{esc(brand)} — <span>ваш размер в наличии</span></h1>
  <p class="meta">Найдено моделей: <b>{len(matches)}</b>{price_line}<br>
  {req}{(' · ' + eu_line) if eu_line else ''} · {gender}</p>
  <div class="summary">{'<br>'.join(notes) if notes else 'Подходящие модели в наличии на POIZON.'}</div>
</header>
<main class="wrap">
  <div class="toolbar">
    <label>Сортировка:
      <select onchange="sortCards(this.value)">
        <option value="priceAsc">сначала дешевле</option>
        <option value="priceDesc">сначала дороже</option>
      </select>
    </label>
    <input type="text" placeholder="фильтр по названию…" oninput="filterCards(this.value)">
    <span class="count" id="count"></span>
  </div>
  <div class="cards" id="cards">
{cards}
  </div>
</main>
<footer>
  Отчёт сформирован парсером POIZON · {esc(generated)} ·
  цены и наличие актуальны на момент подбора.
</footer>
<script>
const grid = document.getElementById('cards');
const cards = Array.from(grid.children);
const count = document.getElementById('count');
function refresh(){{count.textContent = 'показано ' +
  cards.filter(c => c.style.display !== 'none').length + ' из ' + cards.length;}}
function sortCards(mode){{
  const arr = cards.slice().sort((a,b)=>{{
    const pa = +a.dataset.price || 1e12, pb = +b.dataset.price || 1e12;
    return mode === 'priceDesc' ? pb - pa : pa - pb;
  }});
  arr.forEach(c => grid.appendChild(c));
}}
function filterCards(q){{
  q = q.toLowerCase();
  cards.forEach(c => c.style.display =
    c.dataset.title.toLowerCase().includes(q) ? '' : 'none');
  refresh();
}}
refresh();
</script>
</body>
</html>"""


def _render_card(match: dict, esc) -> str:
    title = esc(str(match.get("title") or ""))
    url = esc(_safe_link(match.get("url")))
    price = match.get("price")
    price_attr = f"{price:.0f}" if price is not None else ""
    label = esc(_poizon_label(match))
    delivery = esc(str(match.get("delivery") or ""))
    image = str(match.get("image") or "")

    if _DATA_IMAGE_RE.match(image):
        img_src = esc(image)
    elif _is_web_url(image):
        img_src = esc(_thumb(image))
    else:
        img_src = ""
    img_html = (
        f'<img src="{img_src}" loading="lazy" alt="">' if img_src
        else '<div class="noimg">👟</div>'
    )

    chips = [f'<span class="chip size">{label}</span>']
    foot = match.get("converted_foot")
    cm = match.get("converted_cm")
    if foot is not None:
        chips.append(f'<span class="chip">стопа {_num(foot)} см</span>')
    if cm is not None and (
        foot is None or abs(float(foot) - float(cm)) > 0.05
    ):
        cm_label = "CM/JP" if foot is not None else "CM"
        chips.append(f'<span class="chip">{cm_label} {_num(cm)} см</span>')
    if not match.get("exact_conversion", True):
        chips.append('<span class="chip approx">≈ перевод</span>')

    return f"""    <article class="card" data-price="{price_attr}" data-title="{title}">
      <div class="imgbox">{img_html}</div>
      <div class="body">
        <div class="title">{title}</div>
        <div class="chips">{''.join(chips)}</div>
        <div class="price-row">
          <span class="price">{esc(str(_money(match)))}</span>
          <span class="delivery">{delivery}</span>
        </div>
        <a class="open" href="{url}" target="_blank" rel="noopener">Открыть на POIZON ↗</a>
      </div>
    </article>"""


def write_report(
    matches: list[dict],
    meta: dict,
    base_dir: Path | str = RESULT_DIR,
    embed_images: bool = False,
) -> Path:
    """Пишет отчёт в result/<бренд>-<размер>-<дата>/index.html.

    Каждый вызов получает свою папку: если за ту же секунду уже есть отчёт
    с тем же брендом и размером, к имени добавляется -2, -3… Возвращает путь
    к папке отчёта.
    """
    if embed_images:
        matches = _with_embedded_images(matches)

    brand_slug = slugify(meta.get("brand") or "poizon")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = "-".join(p for p in (brand_slug, _size_slug(meta), stamp) if p)

    out_dir = _unique_dir(Path(base_dir), name)
    meta = dict(meta)
    meta.setdefault("generated_at", time.strftime("%d.%m.%Y %H:%M"))
    (out_dir / "index.html").write_text(
        build_report_html(matches, meta), encoding="utf-8"
    )
    return out_dir


#: Шкалы, которые узнаём в начале строки размера («EU 43», «US W 7»).
_KNOWN_SCALES = (EU, RU, UK, US_MEN, US_WOMEN, CM, MM)
#: Шкала в начале строки размера: буквы до первой цифры.
_SIZE_PREFIX_RE = re.compile(r"^\s*([^\W\d_][^\d]*?)\s*(?=\d)")


def _slug_part(text: str, limit: int) -> str:
    """Только [0-9a-z-]: значения приходят из запроса и идут в имя папки."""
    return re.sub(r"[^0-9a-z]+", "-", str(text).lower()).strip("-")[:limit].strip("-")


def _size_slug(meta: dict) -> str:
    """Размер со шкалой для имени папки: «26-5cm», «eu-42», «us-m-9».

    Длина стопы (и запрос без шкалы) — число с «cm», как раньше; остальные
    шкалы — префиксом, чтобы EU 42 не выглядел как «42cm». Шкалу, уже
    написанную в размере («EU 43»), не повторяем: она же и главнее
    выбранной — то же правило, что у поиска (resolve_query_scale).
    """
    # Размер приходит из запроса: обрезаем до разумной длины, чтобы разбор
    # префикса не тратил квадратичное время на мегабайты пробелов.
    raw = str(meta.get("size_input") or "").strip()[:32]
    written = None
    match = _SIZE_PREFIX_RE.match(raw)
    if match and normalize_scale(match.group(1)) in _KNOWN_SCALES:
        written = match.group(1)
        raw = raw[match.end():]
    scale = resolve_query_scale(written, meta.get("scale"), default=CM)
    unit = {CM: "cm", MM: "mm"}.get(scale)
    number = _slug_part(raw, 16)
    if unit:
        # «26,5 cm» → «26-5cm», а не «26-5-cmcm».
        number = re.sub(rf"-?{unit}$", "", number)
    if not number:
        return ""
    if unit:
        return f"{number}{unit}"
    prefix = _slug_part(scale or "", 12)
    return f"{prefix}-{number}" if prefix else number


def _unique_dir(base_dir: Path, name: str) -> Path:
    """Создаёт новую папку `name` (или `name-2`, `name-3`…) и возвращает её.

    mkdir без exist_ok атомарен: два одновременных отчёта не попадут в одну
    папку и не перезапишут index.html друг друга.
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = base_dir / name
    number = 1
    while True:
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            number += 1
            candidate = base_dir / f"{name}-{number}"


def _with_embedded_images(matches: list[dict]) -> list[dict]:
    """Заменяет URL картинок на data: URI (полностью автономный файл)."""
    out = []
    for match in matches:
        image = match.get("image")
        if isinstance(image, str) and image and not image.startswith("data:"):
            data = _fetch_data_uri(image)
            if data:
                match = {**match, "image": data}
        out.append(match)
    return out
