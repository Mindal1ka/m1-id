"""Українські назви міст для кодів філій MyStat (branch_alias).

Сирий код (`pl`) лишається в БД і в шляхах до MyStat API (він потрібен для
проксі). Назва міста додається лише при віддачі фронту окремим полем
`branch_name`.

Правило власника: якщо не впевнені, що код означає саме це місто, його тут
НЕ ДОДАЄМО. Невідомий код віддається без змін.
"""
from __future__ import annotations

# Ключі — у нижньому регістрі. Підтверджений реальний код: `pl`.
# Решта — повні латинські назви міст (однозначні); короткі двобуквені коди
# навмисно не вгадуємо.
BRANCH_CITY_UK: dict[str, str] = {
    "pl": "Полтава",
    "poltava": "Полтава",
    "kyiv": "Київ",
    "kiev": "Київ",
    "kharkiv": "Харків",
    "odesa": "Одеса",
    "odessa": "Одеса",
    "dnipro": "Дніпро",
    "lviv": "Львів",
    "zaporizhzhia": "Запоріжжя",
    "zaporozhye": "Запоріжжя",
    "vinnytsia": "Вінниця",
    "cherkasy": "Черкаси",
    "chernihiv": "Чернігів",
    "chernivtsi": "Чернівці",
    "zhytomyr": "Житомир",
    "sumy": "Суми",
    "rivne": "Рівне",
    "lutsk": "Луцьк",
    "ternopil": "Тернопіль",
    "khmelnytskyi": "Хмельницький",
    "ivano-frankivsk": "Івано-Франківськ",
    "uzhhorod": "Ужгород",
    "mykolaiv": "Миколаїв",
    "kherson": "Херсон",
    "kropyvnytskyi": "Кропивницький",
    "kryvyi-rih": "Кривий Ріг",
    "kryvyi_rih": "Кривий Ріг",
    "bila-tserkva": "Біла Церква",
    "bila_tserkva": "Біла Церква",
    "kremenchuk": "Кременчук",
}


def _has_cyrillic(text: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in text)


def branch_display_name(code: str | None) -> str:
    """Код філії → українська назва міста; невідомий/кириличний → як прийшов."""
    raw = code or ""
    value = raw.strip()
    if not value or _has_cyrillic(value):
        return raw
    return BRANCH_CITY_UK.get(value.lower(), raw)
