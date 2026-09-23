"""Веб-сервис подбора event-подрядчиков.

Пользователь выбирает город, дату, формат, характер мероприятия, бюджет
и дополнительные условия. Администратор входит отдельно и добавляет
подрядчиков по одному или файлом CSV.
"""

from __future__ import annotations

import csv
import hashlib
import os
import hmac
import io
import json
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CATALOG = DATA / "contractors.csv"
DB = DATA / "contractors.db"
ADMIN_FILE = DATA / "admin.json"
AI_FILE = DATA / "ai.json"
PAGE = ROOT / "static" / "index.html"
ADMIN_PAGE = ROOT / "static" / "admin.html"
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0" if "PORT" in os.environ else "127.0.0.1")
DEFAULT_ADMIN = "admin"
DEFAULT_PASSWORD = "Astana2026"
SESSION_HOURS = 12
MAX_BODY = 1_000_000
ID_RE = re.compile(r"^[a-z0-9-]{1,40}$")

CITIES = ("Астана", "Алматы", "Шымкент", "Караганда", "Актобе")
FORMATS = ("офлайн", "гибрид", "онлайн")
CATEGORIES = (
    "конференция",
    "форум",
    "банкет",
    "выставка",
    "концерт",
    "тимбилдинг",
    "свадьба",
    "корпоратив",
    "фестиваль",
)
SERVICES = ("площадка", "звук", "свет", "сцена", "кейтеринг", "фото", "видео", "ведущий")
EVENT_LANGS = ("русский", "қазақша", "english")
BUDGETS = (300_000, 500_000, 1_000_000, 1_500_000, 2_500_000, 4_000_000)
GUESTS = (50, 100, 200, 500, 1000)

LABELS = {
    "офлайн": {"ru": "офлайн", "kz": "офлайн", "en": "in person"},
    "гибрид": {"ru": "гибрид", "kz": "гибрид", "en": "hybrid"},
    "онлайн": {"ru": "онлайн", "kz": "онлайн", "en": "online"},
    "конференция": {"ru": "конференция", "kz": "конференция", "en": "conference"},
    "форум": {"ru": "форум", "kz": "форум", "en": "forum"},
    "банкет": {"ru": "банкет", "kz": "банкет", "en": "banquet"},
    "выставка": {"ru": "выставка", "kz": "көрме", "en": "exhibition"},
    "концерт": {"ru": "концерт", "kz": "концерт", "en": "concert"},
    "тимбилдинг": {"ru": "тимбилдинг", "kz": "тимбилдинг", "en": "team building"},
    "свадьба": {"ru": "свадьба", "kz": "той", "en": "wedding"},
    "корпоратив": {"ru": "корпоратив", "kz": "корпоратив", "en": "corporate party"},
    "фестиваль": {"ru": "фестиваль", "kz": "фестиваль", "en": "festival"},
    "площадка": {"ru": "площадка", "kz": "алаң", "en": "venue"},
    "звук": {"ru": "звук", "kz": "дыбыс", "en": "sound"},
    "свет": {"ru": "свет", "kz": "жарық", "en": "light"},
    "сцена": {"ru": "сцена", "kz": "сахна", "en": "stage"},
    "кейтеринг": {"ru": "кейтеринг", "kz": "кейтеринг", "en": "catering"},
    "фото": {"ru": "фото", "kz": "фото", "en": "photo"},
    "видео": {"ru": "видео", "kz": "видео", "en": "video"},
    "ведущий": {"ru": "ведущий", "kz": "жүргізуші", "en": "host"},
    "русский": {"ru": "русский", "kz": "орысша", "en": "Russian"},
    "қазақша": {"ru": "қазақша", "kz": "қазақша", "en": "Kazakh"},
    "english": {"ru": "английский", "kz": "ағылшынша", "en": "English"},
    "Астана": {"ru": "Астана", "kz": "Астана", "en": "Astana"},
    "Алматы": {"ru": "Алматы", "kz": "Алматы", "en": "Almaty"},
    "Шымкент": {"ru": "Шымкент", "kz": "Шымкент", "en": "Shymkent"},
    "Караганда": {"ru": "Караганда", "kz": "Қарағанды", "en": "Karaganda"},
    "Актобе": {"ru": "Актобе", "kz": "Ақтөбе", "en": "Aktobe"},
}

SESSIONS: dict[str, float] = {}


@dataclass(frozen=True)
class Contractor:
    id: str
    name: str
    city: str
    categories: tuple[str, ...]
    formats: tuple[str, ...]
    budget_min: int
    budget_max: int
    available_from: date
    available_to: date
    done_count: int
    capacity: int
    languages: tuple[str, ...]
    services: tuple[str, ...]
    busy_from: date | None = None
    busy_to: date | None = None
    max_hours: int = 0


@dataclass(frozen=True)
class Query:
    city: str
    event_date: date
    event_format: str
    category: str
    budget: int
    services: tuple[str, ...] = ()
    language: str = ""
    guests: int = 0
    duration: int = 0
    lang: str = "ru"


class FieldError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def plain_number(raw: object) -> str:
    text = str("" if raw is None else raw)
    for char in (" ", "\u00a0", "\u202f", "\u2009"):
        text = text.replace(char, "")
    return text.strip()


def split_list(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.replace(",", "|").split("|") if part.strip())


def has(value: str, options: tuple[str, ...]) -> bool:
    folded = value.casefold()
    return folded in {item.casefold() for item in options}


def label_of(token: str, lang: str) -> str:
    return LABELS.get(token, {}).get(lang, token)


def choice(values: tuple[str, ...] | list[str], lang: str) -> list[dict]:
    return [{"value": item, "label": label_of(item, lang)} for item in values]


def connect() -> sqlite3.Connection:
    link = sqlite3.connect(DB)
    link.row_factory = sqlite3.Row
    return link


def hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return digest.hex()


def ensure_admin() -> None:
    if ADMIN_FILE.exists():
        return
    salt = secrets.token_bytes(16)
    payload = {
        "username": DEFAULT_ADMIN,
        "salt": salt.hex(),
        "hash": hash_password(DEFAULT_PASSWORD, salt),
    }
    ADMIN_FILE.write_text(json.dumps(payload), encoding="utf-8")


def admin_record() -> dict:
    return json.loads(ADMIN_FILE.read_text(encoding="utf-8"))


def check_password(username: str, password: str) -> bool:
    record = admin_record()
    if not hmac.compare_digest(username, record["username"]):
        return False
    salt = bytes.fromhex(record["salt"])
    candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, record["hash"])


def change_password(current: str, new_password: str) -> None:
    record = admin_record()
    if not check_password(record["username"], current):
        raise ValueError("Текущий пароль неверный.")
    if len(new_password) < 6:
        raise ValueError("Новый пароль — не короче 6 символов.")
    if current == new_password:
        raise ValueError("Новый пароль совпадает с текущим.")
    salt = secrets.token_bytes(16)
    payload = {
        "username": record["username"],
        "salt": salt.hex(),
        "hash": hash_password(new_password, salt),
    }
    ADMIN_FILE.write_text(json.dumps(payload), encoding="utf-8")


def new_session() -> str:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = time.time() + SESSION_HOURS * 3600
    return token


def load_ai() -> dict:
    empty = {"api_url": "", "api_key": "", "model": ""}
    if not AI_FILE.exists():
        return empty
    try:
        raw = json.loads(AI_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    return {
        "api_url": str(raw.get("api_url") or "").strip(),
        "api_key": str(raw.get("api_key") or "").strip(),
        "model": str(raw.get("model") or "").strip(),
    }


def save_ai(settings: dict) -> None:
    DATA.mkdir(exist_ok=True)
    AI_FILE.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")


def ai_public() -> dict:
    settings = load_ai()
    return {
        "api_url": settings["api_url"],
        "model": settings["model"],
        "key_set": bool(settings["api_key"]),
    }


def chat_url(raw: str) -> str:
    url = raw.strip()
    parts = urlparse(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Адрес API должен начинаться с http:// или https://.")
    if parts.path.rstrip("/").endswith("chat/completions"):
        return url
    return url.rstrip("/") + "/chat/completions"


def joined(raw: object) -> str:
    if isinstance(raw, str):
        text = raw.strip()
        return text or "не указано"
    if isinstance(raw, list):
        parts = [str(item).strip() for item in raw if str(item).strip()]
        return ", ".join(parts) if parts else "не указано"
    return "не указано"


def review_text(payload: dict) -> str:
    content = payload.get("choices")
    if isinstance(content, list) and content:
        message = content[0].get("message") or {}
        text = message.get("content")
        if isinstance(text, str) and text.strip():
            return text.strip()
        if isinstance(text, list):
            parts = [
                str(block.get("text") or "").strip()
                for block in text
                if isinstance(block, dict) and str(block.get("text") or "").strip()
            ]
            if parts:
                return "\n".join(parts)
    for key in ("output_text", "text", "result"):
        if isinstance(payload.get(key), str) and payload[key].strip():
            return payload[key].strip()
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        raise ValueError(str(error["message"]))
    raise ValueError("API ответил без текста проверки.")


def check_contractor(raw: dict) -> str:
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("Сначала укажите название подрядчика.")
    settings = load_ai()
    if not settings["api_url"] or not settings["api_key"]:
        raise ValueError("Сначала сохраните адрес API и ключ. Подбор без них работает как раньше.")
    url = chat_url(settings["api_url"])
    model = settings["model"] or "gpt-4o-mini"
    question = (
        "Проверь подрядчика по открытым источникам. В первую очередь нужны отзывы о нём и его услугах. "
        "Если можешь посмотреть 2GIS, Instagram или другой источник, назови источник и только факты из него. "
        "Если доступа к этим источникам нет, первая фраза должна быть: "
        "«Живые отзывы из 2GIS и Instagram этим запросом не получены.» "
        "Не выдумывай оценки, число отзывов, цитаты и ссылки.\n\n"
        f"Название: {name}\n"
        f"Город: {str(raw.get('city') or '').strip() or 'не указан'}\n"
        f"Характер: {joined(raw.get('categories'))}\n"
        f"Формат: {joined(raw.get('formats'))}\n"
        f"Услуги: {joined(raw.get('services'))}\n"
        f"Языки: {joined(raw.get('languages'))}"
    )
    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты помогаешь администратору каталога. Этот ответ не выбирает подрядчика "
                        "и не меняет порядок карточек. Не выдумывай отзывы."
                    ),
                },
                {"role": "user", "content": question},
            ],
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + settings["api_key"],
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw_body = response.read(300_000)
    except urllib.error.HTTPError as exc:
        detail = exc.read(20_000).decode("utf-8", "replace")
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            parsed = {}
        message = ""
        if isinstance(parsed.get("error"), dict):
            message = str(parsed["error"].get("message") or "")
        raise ValueError(message or "API не принял запрос. Подбор при этом работает.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError("Не удалось связаться с API. Подбор при этом работает.") from exc
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("API вернул не JSON. Подбор при этом работает.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("API вернул неожиданный ответ. Подбор при этом работает.")
    return review_text(parsed)


def valid_session(token: str | None) -> bool:
    if not token or token not in SESSIONS:
        return False
    if SESSIONS[token] < time.time():
        SESSIONS.pop(token, None)
        return False
    return True


def init_db() -> None:
    DATA.mkdir(exist_ok=True)
    with connect() as link:
        link.execute(
            """
            CREATE TABLE IF NOT EXISTS contractors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                city TEXT NOT NULL,
                categories TEXT NOT NULL,
                formats TEXT NOT NULL,
                budget_min INTEGER NOT NULL,
                budget_max INTEGER NOT NULL,
                available_from TEXT NOT NULL,
                available_to TEXT NOT NULL,
                done_count INTEGER NOT NULL,
                capacity INTEGER NOT NULL,
                languages TEXT NOT NULL,
                services TEXT NOT NULL
            )
            """
        )
        columns = {row["name"] for row in link.execute("PRAGMA table_info(contractors)")}
        if "busy_from" not in columns:
            link.execute("ALTER TABLE contractors ADD COLUMN busy_from TEXT NOT NULL DEFAULT ''")
        if "busy_to" not in columns:
            link.execute("ALTER TABLE contractors ADD COLUMN busy_to TEXT NOT NULL DEFAULT ''")
        if "max_hours" not in columns:
            link.execute("ALTER TABLE contractors ADD COLUMN max_hours INTEGER NOT NULL DEFAULT 0")
        count = link.execute("SELECT COUNT(*) FROM contractors").fetchone()[0]
        if count == 0 and CATALOG.exists():
            import_csv(CATALOG.read_text(encoding="utf-8-sig"), link)


def row_to_contractor(row: sqlite3.Row) -> Contractor:
    return Contractor(
        id=row["id"],
        name=row["name"],
        city=row["city"],
        categories=split_list(row["categories"]),
        formats=split_list(row["formats"]),
        budget_min=row["budget_min"],
        budget_max=row["budget_max"],
        available_from=date.fromisoformat(row["available_from"]),
        available_to=date.fromisoformat(row["available_to"]),
        done_count=row["done_count"],
        capacity=row["capacity"],
        languages=split_list(row["languages"]),
        services=split_list(row["services"]),
        busy_from=optional_day(row["busy_from"]),
        busy_to=optional_day(row["busy_to"]),
        max_hours=int(row["max_hours"] or 0),
    )


def load_catalog() -> list[Contractor]:
    with connect() as link:
        rows = link.execute("SELECT * FROM contractors ORDER BY name").fetchall()
    return [row_to_contractor(row) for row in rows]


def contractor_public(item: Contractor) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "city": item.city,
        "categories": list(item.categories),
        "formats": list(item.formats),
        "budget_min": item.budget_min,
        "budget_max": item.budget_max,
        "available_from": item.available_from.isoformat(),
        "available_to": item.available_to.isoformat(),
        "done_count": item.done_count,
        "capacity": item.capacity,
        "languages": list(item.languages),
        "services": list(item.services),
        "busy_from": item.busy_from.isoformat() if item.busy_from else "",
        "busy_to": item.busy_to.isoformat() if item.busy_to else "",
        "max_hours": item.max_hours,
    }


def unique_values(catalog: list[Contractor], field: str) -> list[str]:
    found: list[str] = []
    for item in catalog:
        raw = getattr(item, field)
        values = raw if isinstance(raw, tuple) else (raw,)
        for value in values:
            if value and value not in found:
                found.append(value)
    return found


def merge_options(base: tuple[str, ...], extra: list[str]) -> list[str]:
    merged = list(base)
    for item in extra:
        if item not in merged:
            merged.append(item)
    return merged


def options_payload(lang: str) -> dict:
    catalog = load_catalog()
    return {
        "cities": choice(merge_options(CITIES, unique_values(catalog, "city")), lang),
        "formats": choice(merge_options(FORMATS, unique_values(catalog, "formats")), lang),
        "categories": choice(merge_options(CATEGORIES, unique_values(catalog, "categories")), lang),
        "services": choice(merge_options(SERVICES, unique_values(catalog, "services")), lang),
        "languages": choice(merge_options(EVENT_LANGS, unique_values(catalog, "languages")), lang),
        "budgets": [{"value": item, "label": f"{money(item)} тг"} for item in BUDGETS],
        "guests": [{"value": item, "label": str(item)} for item in GUESTS],
    }


def new_id(name: str, taken: set[str]) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    if not stem or not stem.isascii():
        stem = "c"
    candidate = stem[:24]
    while not ID_RE.match(candidate) or candidate in taken:
        candidate = f"{stem[:20]}-{secrets.token_hex(2)}"
    return candidate


def parse_int(raw: object, field: str, label: str, empty_zero: bool = False) -> int:
    text = plain_number(raw)
    if empty_zero and text == "":
        return 0
    if not text.isdigit():
        raise FieldError(field, f"Поле «{label}»: укажите число. Пробелы можно, например 1 500 000.")
    return int(text)


def parse_day(raw: object, field: str, label: str) -> date:
    try:
        return date.fromisoformat(str(raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise FieldError(field, f"Поле «{label}»: укажите дату.") from exc


def optional_day(raw: object) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    return date.fromisoformat(text)


def parse_optional_day(raw: object, field: str, label: str) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise FieldError(field, f"Поле «{label}»: укажите дату.") from exc


def parse_contractor(raw: dict, taken: set[str]) -> Contractor:
    name = str(raw.get("name") or "").strip()
    city = str(raw.get("city") or "").strip()
    if not name:
        raise FieldError("name", "Укажите название.")
    if not city:
        raise FieldError("city", "Укажите город.")
    categories = raw.get("categories") or []
    formats = raw.get("formats") or []
    if isinstance(categories, str):
        categories = split_list(categories)
    if isinstance(formats, str):
        formats = split_list(formats)
    categories = tuple(str(item).strip() for item in categories if str(item).strip())
    formats = tuple(str(item).strip() for item in formats if str(item).strip())
    if not categories:
        raise FieldError("categories", "Выберите характер мероприятия или напишите свой.")
    if not formats:
        raise FieldError("formats", "Выберите формат или напишите свой.")
    budget_min = parse_int(raw.get("budget_min"), "budget_min", "Бюджет от")
    budget_max = parse_int(raw.get("budget_max"), "budget_max", "Бюджет до")
    done_count = parse_int(raw.get("done_count"), "done_count", "Сделано работ", empty_zero=True)
    capacity = parse_int(raw.get("capacity"), "capacity", "Вместимость", empty_zero=True)
    start = parse_day(raw.get("available_from"), "available_from", "Свободен с")
    end = parse_day(raw.get("available_to"), "available_to", "Свободен по")
    busy_from = parse_optional_day(raw.get("busy_from"), "busy_from", "Занят с")
    busy_to = parse_optional_day(raw.get("busy_to"), "busy_to", "Занят по")
    max_hours = parse_int(raw.get("max_hours"), "max_hours", "Максимум часов", empty_zero=True)
    if budget_max < budget_min:
        raise FieldError("budget_max", "Бюджет «до» меньше бюджета «от».")
    if end < start:
        raise FieldError("available_to", "Дата «свободен по» раньше даты «свободен с».")
    if (busy_from is None) != (busy_to is None):
        missing = "busy_to" if busy_from else "busy_from"
        raise FieldError(missing, "Укажите обе даты занятости: «занят с» и «занят по».")
    if busy_from and busy_to and busy_to < busy_from:
        raise FieldError("busy_to", "Дата «занят по» раньше даты «занят с».")
    languages = raw.get("languages") or []
    services = raw.get("services") or []
    if isinstance(languages, str):
        languages = split_list(languages)
    if isinstance(services, str):
        services = split_list(services)
    supplied = str(raw.get("id") or "").strip()
    if supplied:
        if not ID_RE.match(supplied):
            raise FieldError("name", "Не удалось сохранить эту запись. Добавьте её ещё раз.")
        item_id = supplied
    else:
        item_id = new_id(name, taken)
    return Contractor(
        id=item_id,
        name=name,
        city=city,
        categories=categories,
        formats=formats,
        budget_min=budget_min,
        budget_max=budget_max,
        available_from=start,
        available_to=end,
        done_count=done_count,
        capacity=capacity,
        languages=tuple(str(item).strip() for item in languages if str(item).strip()),
        services=tuple(str(item).strip() for item in services if str(item).strip()),
        busy_from=busy_from,
        busy_to=busy_to,
        max_hours=max_hours,
    )


def save_contractor(item: Contractor, link: sqlite3.Connection) -> str:
    existed = link.execute("SELECT 1 FROM contractors WHERE id = ?", (item.id,)).fetchone()
    link.execute(
        """
        INSERT INTO contractors (
            id, name, city, categories, formats, budget_min, budget_max,
            available_from, available_to, done_count, capacity, languages, services,
            busy_from, busy_to, max_hours
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            city = excluded.city,
            categories = excluded.categories,
            formats = excluded.formats,
            budget_min = excluded.budget_min,
            budget_max = excluded.budget_max,
            available_from = excluded.available_from,
            available_to = excluded.available_to,
            done_count = excluded.done_count,
            capacity = excluded.capacity,
            languages = excluded.languages,
            services = excluded.services,
            busy_from = excluded.busy_from,
            busy_to = excluded.busy_to,
            max_hours = excluded.max_hours
        """,
        (
            item.id,
            item.name,
            item.city,
            "|".join(item.categories),
            "|".join(item.formats),
            item.budget_min,
            item.budget_max,
            item.available_from.isoformat(),
            item.available_to.isoformat(),
            item.done_count,
            item.capacity,
            "|".join(item.languages),
            "|".join(item.services),
            item.busy_from.isoformat() if item.busy_from else "",
            item.busy_to.isoformat() if item.busy_to else "",
            item.max_hours,
        ),
    )
    return "updated" if existed else "added"


def import_csv(text: str, link: sqlite3.Connection | None = None) -> dict:
    own = link is None
    if own:
        link = connect()
    assert link is not None
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "name" not in reader.fieldnames:
        raise ValueError("В файле нужна строка заголовков и колонка name.")
    taken = {row["id"] for row in link.execute("SELECT id FROM contractors")}
    added = 0
    updated = 0
    errors = []
    for index, raw in enumerate(reader, start=2):
        try:
            item = parse_contractor(raw, taken)
            state = save_contractor(item, link)
            taken.add(item.id)
            if state == "added":
                added += 1
            else:
                updated += 1
        except ValueError as exc:
            errors.append({"line": index, "error": str(exc)})
    if own:
        link.commit()
        link.close()
    return {"added": added, "updated": updated, "errors": errors}


TEXT = {
    "ru": {
        "fill": "Заполните поле «{name}».",
        "budget": "Бюджет укажите числом в тенге.",
        "date": "Дата нужна в формате ГГГГ-ММ-ДД.",
        "duration": "Длительность укажите целым числом часов.",
        "city": "Город в каталоге — {catalog}, запрос — {asked}.",
        "budget_fail": "Бюджет {budget} тг вне вилки {min}–{max} тг.",
        "date_fail": "Дата {date} вне окна {start}–{end}.",
        "format_fail": "Формат «{value}» не входит в форматы каталога: {options}.",
        "category_fail": "Категория «{value}» не входит в категории каталога: {options}.",
        "service_fail": "Нет услуг: {missing}. В каталоге: {options}.",
        "language_fail": "Язык «{asked}» не входит в языки каталога: {options}.",
        "guests_fail": "Вместимость {capacity} гостей меньше запроса на {guests}.",
        "busy_fail": "Дата {date} попадает в занятость {start}–{end}.",
        "duration_fail": "Длительность {hours} ч больше лимита {max} ч.",
        "reason": (
            "{city}, формат «{fmt}», категория «{cat}». "
            "Бюджет {budget} тг входит в вилку {min}–{max} тг. "
            "Дата {date} свободна ({start}–{end}). "
            "В каталоге {done} таких работ."
        ),
        "reason_services": "Нужные услуги есть: {services}.",
        "reason_language": "Язык «{language}» указан в каталоге.",
        "reason_guests": "Вместимость {capacity} гостей покрывает запрос на {guests}.",
        "reason_busy": "Занятость {start}–{end} не включает дату {date}.",
        "reason_duration": "Длительность {hours} ч не больше лимита {max} ч.",
        "fields": {
            "city": "город",
            "date": "дата",
            "format": "формат",
            "category": "категория",
            "budget": "бюджет",
        },
    },
    "kz": {
        "fill": "«{name}» өрісін толтырыңыз.",
        "budget": "Бюджетті теңгемен, санмен көрсетіңіз.",
        "date": "Күн ЖЖЖЖ-АА-КК форматында болуы керек.",
        "duration": "Ұзақтықты бүтін сағат санымен көрсетіңіз.",
        "city": "Каталогтағы қала — {catalog}, сұраныс — {asked}.",
        "budget_fail": "{budget} тг бюджет {min}–{max} тг ауқымынан тыс.",
        "date_fail": "{date} күні {start}–{end} аралығынан тыс.",
        "format_fail": "«{value}» форматы каталог форматтарына кірмейді: {options}.",
        "category_fail": "«{value}» санаты каталог санаттарына кірмейді: {options}.",
        "service_fail": "Мына қызметтер жоқ: {missing}. Каталогта: {options}.",
        "language_fail": "«{asked}» тілі каталог тілдеріне кірмейді: {options}.",
        "guests_fail": "Сыйымдылық {capacity} қонақ, сұраныс {guests}.",
        "busy_fail": "{date} күні бос емес аралыққа түседі: {start}–{end}.",
        "duration_fail": "{hours} сағат ұзақтық {max} сағат шегінен ұзақ.",
        "reason": (
            "{city}, «{fmt}» форматы, «{cat}» санаты. "
            "{budget} тг бюджет {min}–{max} тг ауқымына кіреді. "
            "{date} күні бос ({start}–{end}). "
            "Каталогта осындай {done} жұмыс бар."
        ),
        "reason_services": "Қажетті қызметтер бар: {services}.",
        "reason_language": "«{language}» тілі каталогта көрсетілген.",
        "reason_guests": "{capacity} қонақ сыйымдылығы {guests} сұранысын жабады.",
        "reason_busy": "Бос емес аралық {start}–{end} {date} күнін қамтымайды.",
        "reason_duration": "{hours} сағат ұзақтық {max} сағат шегінен аспайды.",
        "fields": {
            "city": "қала",
            "date": "күн",
            "format": "формат",
            "category": "санат",
            "budget": "бюджет",
        },
    },
    "en": {
        "fill": "Fill in “{name}”.",
        "budget": "Enter the budget as a number in tenge.",
        "date": "Use the date format YYYY-MM-DD.",
        "duration": "Enter the duration as a whole number of hours.",
        "city": "Catalog city is {catalog}; the request is {asked}.",
        "budget_fail": "A budget of {budget} KZT is outside {min}–{max} KZT.",
        "date_fail": "The date {date} is outside {start}–{end}.",
        "format_fail": "Format “{value}” is not among the catalog formats: {options}.",
        "category_fail": "Category “{value}” is not among the catalog categories: {options}.",
        "service_fail": "Missing services: {missing}. Catalog lists: {options}.",
        "language_fail": "Language “{asked}” is not among the catalog languages: {options}.",
        "guests_fail": "Capacity of {capacity} guests is below the request for {guests}.",
        "busy_fail": "The date {date} falls inside the busy window {start}–{end}.",
        "duration_fail": "A duration of {hours} h is above the catalog limit of {max} h.",
        "reason": (
            "{city}, format “{fmt}”, category “{cat}”. "
            "A budget of {budget} KZT sits inside {min}–{max} KZT. "
            "The date {date} is open ({start}–{end}). "
            "The catalog lists {done} jobs of this kind."
        ),
        "reason_services": "Requested services are covered: {services}.",
        "reason_language": "Language “{language}” is listed in the catalog.",
        "reason_guests": "Capacity of {capacity} guests covers the request for {guests}.",
        "reason_busy": "The busy window {start}–{end} does not include {date}.",
        "reason_duration": "A duration of {hours} h is within the limit of {max} h.",
        "fields": {
            "city": "city",
            "date": "date",
            "format": "format",
            "category": "category",
            "budget": "budget",
        },
    },
}


def normalize_lang(raw: str | None) -> str:
    value = (raw or "ru").strip().lower()
    if value in {"kk", "kaz", "kz"}:
        return "kz"
    if value == "en":
        return "en"
    return "ru"


def failure(contractor: Contractor, query: Query) -> tuple[str, str] | None:
    text = TEXT[query.lang]
    if contractor.city.casefold() != query.city.casefold():
        return "city", text["city"].format(catalog=contractor.city, asked=query.city)
    if not contractor.budget_min <= query.budget <= contractor.budget_max:
        return "budget", text["budget_fail"].format(
            budget=money(query.budget),
            min=money(contractor.budget_min),
            max=money(contractor.budget_max),
        )
    if not contractor.available_from <= query.event_date <= contractor.available_to:
        return "date", text["date_fail"].format(
            date=query.event_date.isoformat(),
            start=contractor.available_from.isoformat(),
            end=contractor.available_to.isoformat(),
        )
    if (
        contractor.busy_from
        and contractor.busy_to
        and contractor.busy_from <= query.event_date <= contractor.busy_to
    ):
        return "busy", text["busy_fail"].format(
            date=query.event_date.isoformat(),
            start=contractor.busy_from.isoformat(),
            end=contractor.busy_to.isoformat(),
        )
    if not has(query.event_format, contractor.formats):
        return "format", text["format_fail"].format(
            value=query.event_format, options=", ".join(contractor.formats) or "—"
        )
    if not has(query.category, contractor.categories):
        return "category", text["category_fail"].format(
            value=query.category, options=", ".join(contractor.categories) or "—"
        )
    if query.services:
        missing = [item for item in query.services if not has(item, contractor.services)]
        if missing:
            return "service", text["service_fail"].format(
                missing=", ".join(missing),
                options=", ".join(contractor.services) or "—",
            )
    if query.language and not has(query.language, contractor.languages):
        return "language", text["language_fail"].format(
            asked=query.language, options=", ".join(contractor.languages) or "—"
        )
    if query.guests and contractor.capacity < query.guests:
        return "guests", text["guests_fail"].format(capacity=contractor.capacity, guests=query.guests)
    if query.duration and contractor.max_hours and query.duration > contractor.max_hours:
        return "duration", text["duration_fail"].format(hours=query.duration, max=contractor.max_hours)
    return None


def fits(contractor: Contractor, query: Query) -> bool:
    return failure(contractor, query) is None


def budget_fit(contractor: Contractor, query: Query) -> float:
    span = max(contractor.budget_max - contractor.budget_min, 1)
    center = (contractor.budget_min + contractor.budget_max) / 2
    return 1 - abs(query.budget - center) / span


def score(contractor: Contractor, query: Query) -> float:
    return contractor.done_count + budget_fit(contractor, query)


def reason(contractor: Contractor, query: Query) -> str:
    text = TEXT[query.lang]
    parts = [
        text["reason"].format(
            city=contractor.city,
            fmt=query.event_format,
            cat=query.category,
            budget=money(query.budget),
            min=money(contractor.budget_min),
            max=money(contractor.budget_max),
            date=query.event_date.isoformat(),
            start=contractor.available_from.isoformat(),
            end=contractor.available_to.isoformat(),
            done=contractor.done_count,
        )
    ]
    if query.services:
        parts.append(text["reason_services"].format(services=", ".join(query.services)))
    if query.language:
        parts.append(text["reason_language"].format(language=query.language))
    if query.guests:
        parts.append(text["reason_guests"].format(capacity=contractor.capacity, guests=query.guests))
    if contractor.busy_from and contractor.busy_to:
        parts.append(
            text["reason_busy"].format(
                start=contractor.busy_from.isoformat(),
                end=contractor.busy_to.isoformat(),
                date=query.event_date.isoformat(),
            )
        )
    if query.duration and contractor.max_hours:
        parts.append(
            text["reason_duration"].format(hours=query.duration, max=contractor.max_hours)
        )
    return " ".join(parts)


def search(catalog: list[Contractor], query: Query) -> dict:
    matched = [item for item in catalog if fits(item, query)]
    matched.sort(key=lambda item: (-score(item, query), item.name))
    cards = []
    for item in matched[:3]:
        fit = budget_fit(item, query)
        cards.append(
            {
                "name": item.name,
                "reason": reason(item, query),
                "done_count": item.done_count,
                "budget_min": item.budget_min,
                "budget_max": item.budget_max,
                "available_from": item.available_from.isoformat(),
                "available_to": item.available_to.isoformat(),
                "busy_from": item.busy_from.isoformat() if item.busy_from else "",
                "busy_to": item.busy_to.isoformat() if item.busy_to else "",
                "max_hours": item.max_hours,
                "budget_fit": round(fit, 2),
                "score": round(item.done_count + fit, 2),
            }
        )
    buckets: dict[str, dict] = {}
    for item in catalog:
        found = failure(item, query)
        if found and found[0] not in buckets:
            buckets[found[0]] = {"name": item.name, "reason": found[1]}
    rejected = [
        buckets[kind]
        for kind in ("city", "budget", "date", "busy", "format", "category", "service", "language", "guests", "duration")
        if kind in buckets
    ][:3]
    return {
        "query": {
            "city": query.city,
            "date": query.event_date.isoformat(),
            "format": query.event_format,
            "category": query.category,
            "budget": query.budget,
            "services": list(query.services),
            "language": query.language,
            "guests": query.guests,
            "duration": query.duration,
        },
        "lang": query.lang,
        "cards": cards,
        "rejected": rejected,
    }


def parse_query(params: dict[str, list[str]]) -> Query:
    lang = normalize_lang((params.get("lang") or ["ru"])[0])
    text = TEXT[lang]

    def one(name: str) -> str:
        values = params.get(name) or []
        if not values or not values[0].strip():
            raise ValueError(text["fill"].format(name=text["fields"][name]))
        return values[0].strip()

    budget_raw = plain_number(one("budget"))
    if not budget_raw.isdigit():
        raise ValueError(text["budget"])
    try:
        event_date = date.fromisoformat(one("date"))
    except ValueError as exc:
        raise ValueError(text["date"]) from exc
    guests_raw = ((params.get("guests") or [""])[0] or "").strip()
    guests = int(guests_raw) if guests_raw.isdigit() else 0
    duration_raw = plain_number((params.get("duration") or [""])[0])
    if duration_raw and (not duration_raw.isdigit() or int(duration_raw) <= 0):
        raise ValueError(text["duration"])
    duration = int(duration_raw) if duration_raw else 0
    services = tuple(item.strip() for item in params.get("services", []) if item.strip())
    language = ((params.get("language") or [""])[0] or "").strip()
    return Query(
        city=one("city"),
        event_date=event_date,
        event_format=one("format"),
        category=one("category"),
        budget=int(budget_raw),
        services=services,
        language=language,
        guests=guests,
        duration=duration,
        lang=lang,
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
            return
        if parsed.path == "/admin":
            self._send(200, "text/html; charset=utf-8", ADMIN_PAGE.read_bytes())
            return
        if parsed.path == "/api/options":
            lang = normalize_lang((parse_qs(parsed.query).get("lang") or ["ru"])[0])
            self._send_json(options_payload(lang))
            return
        if parsed.path == "/api/match":
            try:
                query = parse_query(parse_qs(parsed.query))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json(search(load_catalog(), query))
            return
        if parsed.path == "/api/admin/me":
            self._send_json({"ok": self._authorized()})
            return
        if parsed.path == "/api/admin/contractors":
            if not self._authorized():
                self._send_json({"error": "Нужен вход администратора."}, 401)
                return
            self._send_json({"contractors": [contractor_public(item) for item in load_catalog()]})
            return
        if parsed.path == "/api/admin/ai":
            if not self._authorized():
                self._send_json({"error": "Нужен вход администратора."}, 401)
                return
            self._send_json(ai_public())
            return
        self._send(404, "text/plain; charset=utf-8", "Не найдено".encode())

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            raw = self._body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        if parsed.path == "/api/admin/login":
            self._login(raw)
            return
        if parsed.path == "/api/admin/logout":
            token = self._token()
            if token:
                SESSIONS.pop(token, None)
            self._send_json({"ok": True}, expire=True)
            return
        if not self._authorized():
            self._send_json({"error": "Нужен вход администратора."}, 401)
            return
        if parsed.path == "/api/admin/contractors":
            self._add_one(raw)
            return
        if parsed.path == "/api/admin/import":
            self._import(raw)
            return
        if parsed.path == "/api/admin/delete":
            self._delete(raw)
            return
        if parsed.path == "/api/admin/ai":
            self._save_ai(raw)
            return
        if parsed.path == "/api/admin/check":
            self._check(raw)
            return
        if parsed.path == "/api/admin/password":
            self._password(raw)
            return
        self._send(404, "text/plain; charset=utf-8", "Не найдено".encode())

    def _login(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw.decode() or "{}")
            username = str(payload.get("username") or "")
            password = str(payload.get("password") or "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "Не удалось прочитать запрос."}, 400)
            return
        if not check_password(username, password):
            self._send_json({"error": "Неверный логин или пароль."}, 401)
            return
        self._send_json({"ok": True}, token=new_session())

    def _password(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw.decode() or "{}")
            current = str(payload.get("current") or "")
            new_password = str(payload.get("password") or "")
            change_password(current, new_password)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "Не удалось прочитать запрос."}, 400)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        self._send_json({"ok": True})

    def _save_ai(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "Не удалось прочитать настройки."}, 400)
            return
        current = load_ai()
        url = str(payload.get("api_url") or "").strip()
        model = str(payload.get("model") or "").strip()
        if url:
            try:
                chat_url(url)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
        key = current["api_key"]
        if payload.get("clear_key"):
            key = ""
        elif str(payload.get("api_key") or "").strip():
            key = str(payload.get("api_key") or "").strip()
        save_ai({"api_url": url, "api_key": key, "model": model})
        self._send_json({"ok": True, **ai_public()})

    def _check(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw.decode() or "{}")
            text = check_contractor(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "Не удалось прочитать карточку."}, 400)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        self._send_json({"ok": True, "text": text})

    def _add_one(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw.decode())
            with connect() as link:
                taken = {row["id"] for row in link.execute("SELECT id FROM contractors")}
                item = parse_contractor(payload, taken)
                state = save_contractor(item, link)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "Не удалось прочитать карточку."}, 400)
            return
        except FieldError as exc:
            self._send_json({"error": str(exc), "field": exc.field}, 400)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        self._send_json({"ok": True, "id": item.id, "state": state})

    def _import(self, raw: bytes) -> None:
        try:
            result = import_csv(raw.decode("utf-8-sig"))
        except UnicodeDecodeError:
            self._send_json({"error": "Файл должен быть в UTF-8."}, 400)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        self._send_json(result)

    def _delete(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw.decode() or "{}")
            item_id = str(payload.get("id") or "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "Не удалось прочитать запрос."}, 400)
            return
        if not ID_RE.match(item_id):
            self._send_json({"error": "Неизвестный идентификатор."}, 400)
            return
        with connect() as link:
            link.execute("DELETE FROM contractors WHERE id = ?", (item_id,))
        self._send_json({"ok": True})

    def _authorized(self) -> bool:
        return valid_session(self._token())

    def _token(self) -> str | None:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "session":
                return value
        return None

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            raise ValueError("Файл больше 1 МБ.")
        return self.rfile.read(length)

    def _send_json(
        self,
        payload: dict,
        status: int = 200,
        token: str | None = None,
        expire: bool = False,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self._send(status, "application/json; charset=utf-8", body, token=token, expire=expire)

    def _send(
        self,
        status: int,
        content_type: str,
        body: bytes,
        token: str | None = None,
        expire: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if token:
            self.send_header(
                "Set-Cookie",
                f"session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_HOURS * 3600}",
            )
        if expire:
            self.send_header("Set-Cookie", "session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}")


def main() -> None:
    created = not ADMIN_FILE.exists()
    ensure_admin()
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Сервис слушает порт {PORT}")
    if created or check_password(DEFAULT_ADMIN, DEFAULT_PASSWORD):
        print(f"Админ: логин {DEFAULT_ADMIN}, пароль {DEFAULT_PASSWORD}")
    else:
        print(f"Админ: логин {DEFAULT_ADMIN}, пароль изменён в панели")
    server.serve_forever()


if __name__ == "__main__":
    main()
