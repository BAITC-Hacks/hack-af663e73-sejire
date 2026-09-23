"""Веб-сервис подбора event-подрядчиков по каталогу из 66 профилей.

Запрос задаёт город, дату, тип мероприятия, категорию и бюджет.
Необязательны длительность и язык. Ответ — до трёх карточек
с объяснением по полям профиля.
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
from contextlib import contextmanager
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
PAGE = ROOT / "static" / "index.html"
ADMIN_PAGE = ROOT / "static" / "admin.html"
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0" if "PORT" in os.environ else "127.0.0.1")
DEFAULT_ADMIN = "admin"
LOGIN_LIMIT = 8
LOGIN_WINDOW = 600
ATTEMPTS: dict[str, list[float]] = {}
SESSION_HOURS = 12
MAX_BODY = 1_000_000
ID_RE = re.compile(r"^[A-Za-z0-9-]{1,40}$")

CITIES = ("Алматы", "Астана", "Зарубежье")
FORMATS = ("свадьба", "той", "корпоратив", "конференция", "юбилей", "день рождения")
CATEGORIES = (
    "Ведущий",
    "Фотограф",
    "Банкетный зал",
    "Ресторан",
    "Лайв-бэнд",
    "Шоу-программа",
    "Видеограф",
    "Национальный ансамбль",
    "Танцевальный коллектив",
    "Загородная площадка",
    "Флорист",
    "Декоратор",
    "Подарки и сувениры",
    "Ведущий церемонии",
    "Инструменталист",
    "Фото и видеобудки",
    "Отель",
)
EVENT_LANGS = ("русский", "казахский", "английский")

LABELS = {
    "Алматы": {"ru": "Алматы", "kz": "Алматы", "en": "Almaty"},
    "Астана": {"ru": "Астана", "kz": "Астана", "en": "Astana"},
    "Зарубежье": {"ru": "Зарубежье", "kz": "Шетел", "en": "Abroad"},
    "свадьба": {"ru": "свадьба", "kz": "үйлену тойы", "en": "wedding"},
    "той": {"ru": "той", "kz": "той", "en": "toi"},
    "корпоратив": {"ru": "корпоратив", "kz": "корпоратив", "en": "corporate party"},
    "конференция": {"ru": "конференция", "kz": "конференция", "en": "conference"},
    "юбилей": {"ru": "юбилей", "kz": "мерейтой", "en": "anniversary"},
    "день рождения": {"ru": "день рождения", "kz": "туған күн", "en": "birthday"},
    "Ведущий": {"ru": "Ведущий", "kz": "Жүргізуші", "en": "Host"},
    "Фотограф": {"ru": "Фотограф", "kz": "Фотограф", "en": "Photographer"},
    "Банкетный зал": {"ru": "Банкетный зал", "kz": "Банкет залы", "en": "Banquet hall"},
    "Ресторан": {"ru": "Ресторан", "kz": "Мейрамхана", "en": "Restaurant"},
    "Лайв-бэнд": {"ru": "Лайв-бэнд", "kz": "Лайв-бэнд", "en": "Live band"},
    "Шоу-программа": {"ru": "Шоу-программа", "kz": "Шоу-бағдарлама", "en": "Show"},
    "Видеограф": {"ru": "Видеограф", "kz": "Видеограф", "en": "Videographer"},
    "Национальный ансамбль": {"ru": "Национальный ансамбль", "kz": "Ұлттық ансамбль", "en": "Folk ensemble"},
    "Танцевальный коллектив": {"ru": "Танцевальный коллектив", "kz": "Би тобы", "en": "Dance group"},
    "Загородная площадка": {"ru": "Загородная площадка", "kz": "Қала сыртындағы алаң", "en": "Country venue"},
    "Флорист": {"ru": "Флорист", "kz": "Флорист", "en": "Florist"},
    "Декоратор": {"ru": "Декоратор", "kz": "Декоратор", "en": "Decorator"},
    "Подарки и сувениры": {"ru": "Подарки и сувениры", "kz": "Сыйлықтар мен кәдесыйлар", "en": "Gifts and souvenirs"},
    "Ведущий церемонии": {"ru": "Ведущий церемонии", "kz": "Рәсім жүргізушісі", "en": "Ceremony host"},
    "Инструменталист": {"ru": "Инструменталист", "kz": "Аспапшы", "en": "Instrumentalist"},
    "Фото и видеобудки": {"ru": "Фото и видеобудки", "kz": "Фото және видеобудка", "en": "Photo and video booth"},
    "Отель": {"ru": "Отель", "kz": "Қонақүй", "en": "Hotel"},
    "русский": {"ru": "русский", "kz": "орысша", "en": "Russian"},
    "казахский": {"ru": "казахский", "kz": "қазақша", "en": "Kazakh"},
    "английский": {"ru": "английский", "kz": "ағылшынша", "en": "English"},
}

SESSIONS: dict[str, float] = {}


@dataclass(frozen=True)
class Contractor:
    id: str
    name: str
    city: str
    categories: tuple[str, ...]
    formats: tuple[str, ...]
    price_from: int | None
    languages: tuple[str, ...]
    max_hours: int | None
    busy_dates: tuple[date, ...]
    description: str
    synthetic: bool = False
    city_imputed: bool = False
    price_imputed: bool = False


@dataclass(frozen=True)
class Query:
    city: str
    event_date: date
    event_format: str
    category: str
    budget: int
    language: str = ""
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


@contextmanager
def database():
    link = connect()
    try:
        yield link
        link.commit()
    except Exception:
        link.rollback()
        raise
    finally:
        link.close()


def hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return digest.hex()


def ensure_admin() -> None:
    if ADMIN_FILE.exists():
        return
    username = os.environ.get("ADMIN_USER", DEFAULT_ADMIN).strip() or DEFAULT_ADMIN
    password = os.environ.get("ADMIN_PASSWORD", "")
    if len(password) < 6:
        raise SystemExit(
            "Первый запуск: задайте переменную окружения ADMIN_PASSWORD "
            "(не короче 6 символов). Пароль не хранится в коде и не пишется в журнал."
        )
    salt = secrets.token_bytes(16)
    payload = {
        "username": username,
        "salt": salt.hex(),
        "hash": hash_password(password, salt),
    }
    DATA.mkdir(exist_ok=True)
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


def login_limited(ip: str) -> bool:
    now = time.time()
    recent = [stamp for stamp in ATTEMPTS.get(ip, []) if now - stamp < LOGIN_WINDOW]
    ATTEMPTS[ip] = recent
    return len(recent) >= LOGIN_LIMIT


def note_login_fail(ip: str) -> None:
    ATTEMPTS.setdefault(ip, []).append(time.time())


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


def valid_session(token: str | None) -> bool:
    if not token or token not in SESSIONS:
        return False
    if SESSIONS[token] < time.time():
        SESSIONS.pop(token, None)
        return False
    return True


def create_contractors(link: sqlite3.Connection) -> None:
    link.execute(
        """
        CREATE TABLE contractors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            categories TEXT NOT NULL,
            formats TEXT NOT NULL,
            price_from INTEGER,
            languages TEXT NOT NULL,
            max_hours INTEGER,
            busy_dates TEXT NOT NULL,
            description TEXT NOT NULL,
            synthetic INTEGER NOT NULL,
            city_imputed INTEGER NOT NULL,
            price_imputed INTEGER NOT NULL
        )
        """
    )


def init_db() -> None:
    DATA.mkdir(exist_ok=True)
    with database() as link:
        columns = {row["name"] for row in link.execute("PRAGMA table_info(contractors)")}
        if columns and "price_from" not in columns:
            link.execute("DROP TABLE contractors")
            columns = set()
        elif columns:
            price = next(row for row in link.execute("PRAGMA table_info(contractors)") if row["name"] == "price_from")
            if price["notnull"]:
                link.execute("ALTER TABLE contractors RENAME TO contractors_old")
                create_contractors(link)
                link.execute(
                    """
                    INSERT INTO contractors
                    SELECT id, name, city, categories, formats, price_from, languages,
                           max_hours, busy_dates, description, synthetic, city_imputed, price_imputed
                    FROM contractors_old
                    """
                )
                link.execute("DROP TABLE contractors_old")
        if not columns:
            create_contractors(link)
        count = link.execute("SELECT COUNT(*) FROM contractors").fetchone()[0]
        if count == 0 and CATALOG.exists():
            import_csv(CATALOG.read_text(encoding="utf-8-sig"), link)


def row_to_contractor(row: sqlite3.Row) -> Contractor:
    hours = row["max_hours"]
    return Contractor(
        id=row["id"],
        name=row["name"],
        city=row["city"],
        categories=split_list(row["categories"]),
        formats=split_list(row["formats"]),
        price_from=row["price_from"],
        languages=split_list(row["languages"]),
        max_hours=None if hours is None or hours == "" else int(hours),
        busy_dates=tuple(date.fromisoformat(item) for item in split_list(row["busy_dates"])),
        description=row["description"] or "",
        synthetic=bool(row["synthetic"]),
        city_imputed=bool(row["city_imputed"]),
        price_imputed=bool(row["price_imputed"]),
    )


def load_catalog() -> list[Contractor]:
    with database() as link:
        rows = link.execute("SELECT * FROM contractors ORDER BY name").fetchall()
    return [row_to_contractor(row) for row in rows]


def contractor_public(item: Contractor) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "city": item.city,
        "categories": list(item.categories),
        "formats": list(item.formats),
        "price_from": item.price_from,
        "languages": list(item.languages),
        "max_hours": item.max_hours,
        "busy_dates": [item.isoformat() for item in item.busy_dates],
        "description": item.description,
        "synthetic": item.synthetic,
        "city_imputed": item.city_imputed,
        "price_imputed": item.price_imputed,
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
        "languages": choice(merge_options(EVENT_LANGS, unique_values(catalog, "languages")), lang),
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


def as_bool(raw: object) -> bool:
    return str(raw if raw is not None else "").strip().casefold() in {"1", "true", "yes", "да"}


def as_list(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        return split_list(raw)
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def parse_price(raw: object) -> int | None:
    text = plain_number(raw)
    if text == "":
        return None
    if not text.isdigit():
        raise FieldError("price_from", "Поле «Цена от»: укажите число в тенге или оставьте пустым, если цена неизвестна.")
    return int(text)


def parse_hours(raw: object) -> int | None:
    text = plain_number(raw)
    if text == "":
        return None
    if not text.isdigit():
        raise FieldError("max_hours", "Поле «Максимум часов»: укажите число или оставьте пустым.")
    return int(text)


def parse_busy(raw: object) -> tuple[date, ...]:
    days: list[date] = []
    for item in as_list(raw):
        try:
            days.append(date.fromisoformat(item))
        except ValueError as exc:
            raise FieldError("busy_dates", f"Дата занятости «{item}» нужна в формате ГГГГ-ММ-ДД.") from exc
    return tuple(sorted(set(days)))


def parse_contractor(raw: dict, taken: set[str]) -> Contractor:
    name = str(raw.get("anon_name") or raw.get("name") or "").strip()
    city = str(raw.get("city") or "").strip()
    if not name:
        raise FieldError("name", "Укажите название.")
    if not city:
        raise FieldError("city", "Укажите город.")
    categories = as_list(raw.get("categories"))
    formats = as_list(raw.get("event_formats") if raw.get("event_formats") not in (None, "") else raw.get("formats"))
    if not categories:
        raise FieldError("categories", "Выберите категорию подрядчика.")
    if not formats:
        raise FieldError("formats", "Выберите тип мероприятия.")
    price_raw = raw.get("price_from_kzt")
    if price_raw in (None, ""):
        price_raw = raw.get("price_from")
    price_from = parse_price(price_raw)
    languages = as_list(raw.get("languages"))
    if not languages:
        raise FieldError("languages", "Укажите хотя бы один язык.")
    description = " ".join(str(raw.get("description") or "").split())
    if not description:
        raise FieldError("description", "Добавьте описание: из него берётся объяснение на карточке.")
    supplied = str(raw.get("id") or "").strip()
    if supplied:
        if not ID_RE.match(supplied):
            raise FieldError("name", "Не удалось сохранить эту запись. Добавьте её ещё раз.")
        item_id = supplied
        synthetic = as_bool(raw.get("synthetic"))
    else:
        item_id = new_id(name, taken)
        synthetic = True
    return Contractor(
        id=item_id,
        name=name,
        city=city,
        categories=categories,
        formats=formats,
        price_from=price_from,
        languages=languages,
        max_hours=parse_hours(raw.get("max_hours")),
        busy_dates=parse_busy(raw.get("busy_dates")),
        description=description,
        synthetic=synthetic,
        city_imputed=as_bool(raw.get("city_imputed")),
        price_imputed=as_bool(raw.get("price_imputed")),
    )


def save_contractor(item: Contractor, link: sqlite3.Connection) -> str:
    existed = link.execute("SELECT 1 FROM contractors WHERE id = ?", (item.id,)).fetchone()
    link.execute(
        """
        INSERT INTO contractors (
            id, name, city, categories, formats, price_from, languages, max_hours,
            busy_dates, description, synthetic, city_imputed, price_imputed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            city = excluded.city,
            categories = excluded.categories,
            formats = excluded.formats,
            price_from = excluded.price_from,
            languages = excluded.languages,
            max_hours = excluded.max_hours,
            busy_dates = excluded.busy_dates,
            description = excluded.description,
            synthetic = excluded.synthetic,
            city_imputed = excluded.city_imputed,
            price_imputed = excluded.price_imputed
        """,
        (
            item.id,
            item.name,
            item.city,
            "|".join(item.categories),
            "|".join(item.formats),
            item.price_from,
            "|".join(item.languages),
            item.max_hours,
            "|".join(day.isoformat() for day in item.busy_dates),
            item.description,
            int(item.synthetic),
            int(item.city_imputed),
            int(item.price_imputed),
        ),
    )
    return "updated" if existed else "added"


def import_csv(text: str, link: sqlite3.Connection | None = None) -> dict:
    if text.startswith("\ufeff"):
        text = text[1:]
    own = link is None
    if own:
        link = connect()
    assert link is not None
    reader = csv.DictReader(io.StringIO(text))
    names = set(reader.fieldnames or [])
    if "anon_name" not in names and "name" not in names:
        raise ValueError("В файле нужна строка заголовков и колонка anon_name.")
    taken = {row["id"] for row in link.execute("SELECT id FROM contractors")}
    added = 0
    updated = 0
    errors = []
    seen: set[str] = set()
    try:
        for index, raw in enumerate(reader, start=2):
            try:
                item = parse_contractor(raw, taken)
                if item.id in seen:
                    errors.append({"line": index, "error": "Повтор id в этом файле, строка пропущена."})
                    continue
                seen.add(item.id)
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
    except Exception:
        if own:
            link.rollback()
        raise
    finally:
        if own:
            link.close()
    return {"added": added, "updated": updated, "skipped": len(errors), "errors": errors}


def preview_csv(text: str) -> dict:
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.DictReader(io.StringIO(text))
    names = set(reader.fieldnames or [])
    if "anon_name" not in names and "name" not in names:
        raise ValueError("В файле нужна строка заголовков и колонка anon_name.")
    with database() as link:
        taken = {row["id"] for row in link.execute("SELECT id FROM contractors")}
    rows = []
    seen: set[str] = set()
    pool = set(taken)
    for index, raw in enumerate(reader, start=2):
        try:
            item = parse_contractor(raw, pool)
            if item.id in seen:
                rows.append({"line": index, "state": "duplicate", "id": item.id, "name": item.name, "error": "Повтор id в этом файле."})
                continue
            seen.add(item.id)
            pool.add(item.id)
            state = "update" if item.id in taken else "add"
            rows.append({
                "line": index,
                "state": state,
                "id": item.id,
                "name": item.name,
                "synthetic": item.synthetic,
                "city_imputed": item.city_imputed,
                "price_imputed": item.price_imputed,
            })
        except ValueError as exc:
            rows.append({"line": index, "state": "error", "error": str(exc)})
    problems = [
        {"line": row["line"], "error": row.get("error") or row["state"]}
        for row in rows
        if row["state"] in {"error", "duplicate"}
    ]
    return {
        "rows": rows,
        "added": sum(row["state"] == "add" for row in rows),
        "updated": sum(row["state"] == "update" for row in rows),
        "skipped": len(problems),
        "errors": problems,
    }


TEXT = {
    "ru": {
        "fill": "Заполните поле «{name}».",
        "budget": "Бюджет укажите числом в тенге.",
        "date": "Дата нужна в формате ГГГГ-ММ-ДД.",
        "duration": "Длительность укажите целым числом часов.",
        "fields": {
            "city": "город",
            "date": "дата",
            "format": "тип мероприятия",
            "category": "категория подрядчика",
            "budget": "бюджет",
        },
        "format_fail": "Тип «{value}» не входит в типы профиля: {options}.",
        "budget_fail": "Цена от {price} тг выше бюджета {budget} тг.",
        "busy_fail": "Дата {date} есть в списке занятых дат этого профиля.",
        "language_fail": "Язык «{asked}» не входит в языки профиля: {options}.",
        "duration_fail": "Запрос на {hours} ч больше лимита профиля {max} ч.",
        "facts": "Город {city}, категория «{category}». Цена от {price} тг не выше бюджета {budget} тг. Тип «{fmt}» есть в профиле, {date} нет в списке занятых дат. Языки профиля: {languages}. {hours}",
        "hours_open": "Лимит часов в профиле пустой: присутствие на площадке не требуется.",
        "hours_limit": "Лимит профиля — {max} ч на площадке.",
        "hours_skip": "Запрос на {hours} ч профиль не отсекает: лимит часов пустой.",
        "hours_ok": "Запрос на {hours} ч не больше лимита {max} ч.",
        "lang_ok": "Запрошенный язык «{language}» есть в профиле.",
        "synthetic": "Это синтетический профиль.",
        "price_flag": "Цена проставлена при подготовке датасета.",
        "city_flag": "Город проставлен при подготовке датасета.",
        "quote": "В описании профиля: «{text}».",
        "no_category": "В городе {city} нет подрядчиков категории «{category}».",
        "no_category_elsewhere": " Эта категория есть в других городах: {cities}.",
        "blocked": "В городе {city} есть {pool} в категории «{category}», ни один не проходит условия.",
        "few": "Подходят {passed} из {pool} в городе {city}.",
        "only": "В городе {city} только {passed} в категории «{category}», и все они проходят условия.",
        "price_unknown": "Цена не указана, поэтому профиль не входит в рекомендации.",
        "ranked": "Подходят {passed}. Показаны 3 с наименьшей ценой «от»; при равной цене порядок по id. Это порядок по цене, не оценка качества.",
        "also": " Дороже и тоже проходят: {names}.",
    },
    "kz": {
        "fill": "«{name}» өрісін толтырыңыз.",
        "budget": "Бюджетті теңгемен, санмен көрсетіңіз.",
        "date": "Күн ЖЖЖЖ-АА-КК форматында болуы керек.",
        "duration": "Ұзақтықты бүтін сағат санымен көрсетіңіз.",
        "fields": {
            "city": "қала",
            "date": "күн",
            "format": "іс-шара түрі",
            "category": "мердігер санаты",
            "budget": "бюджет",
        },
        "format_fail": "«{value}» түрі профиль түрлеріне кірмейді: {options}.",
        "budget_fail": "{price} тг бастапқы баға {budget} тг бюджеттен жоғары.",
        "busy_fail": "{date} күні осы профильдің бос емес күндер тізімінде бар.",
        "language_fail": "«{asked}» тілі профиль тілдеріне кірмейді: {options}.",
        "duration_fail": "{hours} сағат сұраныс профиль шегінен {max} сағаттан ұзақ.",
        "facts": "Қала {city}, санат «{category}». {price} тг бастапқы баға {budget} тг бюджеттен аспайды. «{fmt}» түрі профильде бар, {date} бос емес күндер тізімінде жоқ. Профиль тілдері: {languages}. {hours}",
        "hours_open": "Сағат шегі бос: алаңда болу талап етілмейді.",
        "hours_limit": "Профиль шегі — алаңда {max} сағат.",
        "hours_skip": "{hours} сағат сұраныс профильді шығармайды: сағат шегі бос.",
        "hours_ok": "{hours} сағат сұраныс {max} сағат шегінен аспайды.",
        "lang_ok": "Сұралған «{language}» тілі профильде бар.",
        "synthetic": "Бұл синтетикалық профиль.",
        "price_flag": "Баға деректерді дайындау кезінде қойылған.",
        "city_flag": "Қала деректерді дайындау кезінде қойылған.",
        "quote": "Профиль сипаттамасында: «{text}».",
        "no_category": "{city} қаласында «{category}» санатындағы мердігер жоқ.",
        "no_category_elsewhere": " Бұл санат басқа қалаларда бар: {cities}.",
        "blocked": "{city} қаласында «{category}» санатында {pool} профиль бар, біреуі де шарттан өтпейді.",
        "few": "{city} қаласындағы {pool} профильдің {passed} өтеді.",
        "only": "{city} қаласында «{category}» санатында тек {passed} бар, олардың бәрі өтеді.",
        "price_unknown": "Баға көрсетілмеген, сондықтан профиль ұсынысқа кірмейді.",
        "ranked": "{passed} өтеді. Ең төмен бастапқы бағасы бар 3-еуі көрсетілген; баға тең болса id бойынша. Бұл баға реті, сапа бағасы емес.",
        "also": " Қымбатырақ және де өтеді: {names}.",
    },
    "en": {
        "fill": "Fill in “{name}”.",
        "budget": "Enter the budget as a number in tenge.",
        "date": "Use the date format YYYY-MM-DD.",
        "duration": "Enter the duration as a whole number of hours.",
        "fields": {
            "city": "city",
            "date": "date",
            "format": "event type",
            "category": "contractor category",
            "budget": "budget",
        },
        "format_fail": "Event type “{value}” is not among this profile’s types: {options}.",
        "budget_fail": "A price from {price} KZT is above the budget of {budget} KZT.",
        "busy_fail": "The date {date} is in this profile’s busy dates.",
        "language_fail": "Language “{asked}” is not among this profile’s languages: {options}.",
        "duration_fail": "A request for {hours} h is above this profile’s limit of {max} h.",
        "facts": "City {city}, category “{category}”. A price from {price} KZT is within the budget of {budget} KZT. Event type “{fmt}” is on the profile, and {date} is not in the busy dates. Profile languages: {languages}. {hours}",
        "hours_open": "The hour limit is empty: the work is not tied to being on site.",
        "hours_limit": "The profile limit is {max} h on site.",
        "hours_skip": "A request for {hours} h does not exclude the profile: the hour limit is empty.",
        "hours_ok": "A request for {hours} h is within the limit of {max} h.",
        "lang_ok": "The requested language “{language}” is on the profile.",
        "synthetic": "This is a synthetic profile.",
        "price_flag": "The price was filled in when the dataset was prepared.",
        "city_flag": "The city was filled in when the dataset was prepared.",
        "quote": "From the profile description: “{text}”.",
        "no_category": "There are no contractors in {city} in the category “{category}”.",
        "no_category_elsewhere": " This category exists in other cities: {cities}.",
        "blocked": "{city} has {pool} profiles in “{category}”, and none of them pass the conditions.",
        "few": "{passed} of {pool} in {city} pass.",
        "only": "{city} has only {passed} in “{category}”, and all of them pass.",
        "price_unknown": "The price is missing, so the profile is not recommended.",
        "ranked": "{passed} pass. Three with the lowest starting price are shown; equal prices keep id order. This is a price order, not a quality score.",
        "also": " These also pass at a higher price: {names}.",
    },
}


def normalize_lang(raw: str | None) -> str:
    value = (raw or "ru").strip().lower()
    if value in {"kk", "kaz", "kz"}:
        return "kz"
    if value == "en":
        return "en"
    return "ru"


def excerpt(text: str) -> str:
    flat = " ".join(text.split())
    if not flat:
        return ""
    for index, char in enumerate(flat):
        if char in ".!?" and index >= 40:
            return flat[: index + 1]
    if len(flat) <= 220:
        return flat
    return flat[:220].rsplit(" ", 1)[0] + "…"


def pool_failure(contractor: Contractor, query: Query) -> tuple[str, str] | None:
    text = TEXT[query.lang]
    if not has(query.event_format, contractor.formats):
        return "format", text["format_fail"].format(
            value=query.event_format, options=", ".join(contractor.formats) or "—"
        )
    if contractor.price_from is None:
        return "price_unknown", text["price_unknown"]
    if contractor.price_from > query.budget:
        return "budget", text["budget_fail"].format(
            price=money(contractor.price_from), budget=money(query.budget)
        )
    if query.event_date in contractor.busy_dates:
        return "busy", text["busy_fail"].format(date=query.event_date.isoformat())
    if query.language and not has(query.language, contractor.languages):
        return "language", text["language_fail"].format(
            asked=query.language, options=", ".join(contractor.languages) or "—"
        )
    if query.duration and contractor.max_hours is not None and query.duration > contractor.max_hours:
        return "duration", text["duration_fail"].format(hours=query.duration, max=contractor.max_hours)
    return None


def explain(contractor: Contractor, query: Query) -> str:
    text = TEXT[query.lang]
    if query.duration and contractor.max_hours is None:
        hours = text["hours_skip"].format(hours=query.duration)
    elif query.duration and contractor.max_hours is not None:
        hours = text["hours_ok"].format(hours=query.duration, max=contractor.max_hours)
    elif contractor.max_hours is None:
        hours = text["hours_open"]
    else:
        hours = text["hours_limit"].format(max=contractor.max_hours)
    flags = []
    if contractor.synthetic:
        flags.append(text["synthetic"])
    if contractor.price_imputed:
        flags.append(text["price_flag"])
    if contractor.city_imputed:
        flags.append(text["city_flag"])
    language = (" " + text["lang_ok"].format(language=query.language)) if query.language else ""
    flag_text = (" " + " ".join(flags)) if flags else ""
    facts = text["facts"].format(
        city=contractor.city,
        category=query.category,
        price=money(contractor.price_from),
        budget=money(query.budget),
        fmt=query.event_format,
        date=query.event_date.isoformat(),
        languages=", ".join(contractor.languages) or "—",
        hours=hours,
    )
    return facts + language + flag_text + " " + text["quote"].format(text=excerpt(contractor.description))


def detail_lines(failed: list[dict]) -> str:
    return " ".join(f"{item['name']}: {item['reason']}" for item in failed)


def search(catalog: list[Contractor], query: Query) -> dict:
    text = TEXT[query.lang]
    pool = [
        item
        for item in catalog
        if item.city.casefold() == query.city.casefold() and has(query.category, item.categories)
    ]
    pool.sort(key=lambda item: item.id)
    base = {
        "query": {
            "city": query.city,
            "date": query.event_date.isoformat(),
            "format": query.event_format,
            "category": query.category,
            "budget": query.budget,
            "language": query.language,
            "duration": query.duration,
        },
        "lang": query.lang,
        "pool": len(pool),
        "passed": 0,
        "cards": [],
        "failed": [],
        "also": [],
    }
    if not pool:
        others = sorted({item.city for item in catalog if has(query.category, item.categories)})
        message = text["no_category"].format(city=query.city, category=query.category)
        if others:
            message += text["no_category_elsewhere"].format(cities=", ".join(others))
        return {**base, "outcome": "no_category", "summary": message}
    passed: list[Contractor] = []
    failed: list[dict] = []
    for item in pool:
        found = pool_failure(item, query)
        if found:
            failed.append({"name": item.name, "kind": found[0], "reason": found[1]})
        else:
            passed.append(item)
    passed.sort(key=lambda item: (item.price_from, item.id))
    failed.sort(key=lambda item: item["name"])
    if not passed:
        summary = text["blocked"].format(city=query.city, pool=len(pool), category=query.category)
        summary = summary + " " + detail_lines(failed)
        return {**base, "outcome": "blocked", "summary": summary, "failed": failed}
    if len(passed) < 3 and failed:
        summary = text["few"].format(passed=len(passed), pool=len(pool), city=query.city)
        summary = summary + " " + detail_lines(failed)
    elif len(passed) < 3:
        summary = text["only"].format(city=query.city, passed=len(passed), category=query.category)
    else:
        summary = text["ranked"].format(passed=len(passed))
        rest = ", ".join(item.name for item in passed[3:])
        if rest:
            summary += text["also"].format(names=rest)
    cards = []
    for item in passed[:3]:
        cards.append(
            {
                "id": item.id,
                "name": item.name,
                "category": query.category,
                "city": item.city,
                "price_from": item.price_from,
                "languages": list(item.languages),
                "max_hours": item.max_hours,
                "synthetic": item.synthetic,
                "city_imputed": item.city_imputed,
                "price_imputed": item.price_imputed,
                "explanation": explain(item, query),
            }
        )
    return {
        **base,
        "outcome": "matched",
        "passed": len(passed),
        "summary": summary,
        "cards": cards,
        "failed": failed,
        "also": [{"name": item.name, "price_from": item.price_from} for item in passed[3:]],
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
    duration_raw = plain_number((params.get("duration") or [""])[0])
    if duration_raw and (not duration_raw.isdigit() or int(duration_raw) <= 0):
        raise ValueError(text["duration"])
    return Query(
        city=one("city"),
        event_date=event_date,
        event_format=one("format"),
        category=one("category"),
        budget=int(budget_raw),
        language=((params.get("language") or [""])[0] or "").strip(),
        duration=int(duration_raw) if duration_raw else 0,
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
        self._send(404, "text/plain; charset=utf-8", "Не найдено".encode())

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            raw = self._body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        if parsed.path.startswith("/api/admin") and not self._same_origin():
            self._send_json({"error": "Запрос отклонён."}, 403)
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
        if parsed.path == "/api/admin/import-preview":
            self._import_preview(raw)
            return
        if parsed.path == "/api/admin/import":
            self._import(raw)
            return
        if parsed.path == "/api/admin/delete":
            self._delete(raw)
            return
        if parsed.path == "/api/admin/password":
            self._password(raw)
            return
        self._send(404, "text/plain; charset=utf-8", "Не найдено".encode())

    def _ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For") or ""
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def _same_origin(self) -> bool:
        if self.headers.get("X-Requested-With") != "fetch":
            return False
        origin = self.headers.get("Origin") or ""
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").split(",")[0].strip()
        return bool(host) and urlparse(origin).netloc.lower() == host.lower()

    def _import_preview(self, raw: bytes) -> None:
        try:
            self._send_json(preview_csv(raw.decode("utf-8-sig")))
        except UnicodeDecodeError:
            self._send_json({"error": "Файл должен быть в UTF-8."}, 400)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)

    def _login(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw.decode() or "{}")
            username = str(payload.get("username") or "")
            password = str(payload.get("password") or "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "Не удалось прочитать запрос."}, 400)
            return
        ip = self._ip()
        if login_limited(ip):
            self._send_json({"error": "Слишком много попыток входа. Подождите около 10 минут."}, 429)
            return
        if not check_password(username, password):
            note_login_fail(ip)
            self._send_json({"error": "Неверный логин или пароль."}, 401)
            return
        ATTEMPTS.pop(ip, None)
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

    def _add_one(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw.decode())
            with database() as link:
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
        with database() as link:
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
        secure = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower() == "https"
        secure_flag = "; Secure" if secure else ""
        if token:
            self.send_header(
                "Set-Cookie",
                f"session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_HOURS * 3600}{secure_flag}",
            )
        if expire:
            self.send_header(
                "Set-Cookie",
                f"session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0{secure_flag}",
            )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}")


def main() -> None:
    ensure_admin()
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Сервис слушает порт {PORT}")
    print("Пароль администратора задаётся через ADMIN_PASSWORD и в журнал не пишется.")
    server.serve_forever()


if __name__ == "__main__":
    main()
