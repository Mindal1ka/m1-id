"""«Сліпий API»: санітизація даних юзера перед передачею плагіну.

Принцип: не чорний список полів, а псевдонімізація — персональні
ідентифікатори (ПІБ, логін, пошта, телефон) підмінюються СТАБІЛЬНИМИ
псевдонімами (#T1, @u3), які генеруються детерміновано з (user_id,
plugin_id, значення). Мапа живе тільки в ядрі; на виході плагіна
рядки з псевдонімами відновлюються (unredact) перед TG/логом.

Лідерборд — свідомий виняток: імена учасників там публічні й у самому
MyStat, тому віддаємо як є (політика: «ми надаємо спільні речі»).
"""
from __future__ import annotations

import hashlib
import json
import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{8,}\d")

# поля, що містять персональні дані (T4: розширений список)
PII_FIELDS = {"fio", "full_name", "student_name", "teacher_fio", "teacher",
              "parent_fio", "parent", "parents", "mother", "father",
              "email", "mail", "phone", "phone_number", "mobile",
              "address", "city", "birthday", "birth_date", "dob",
              "mystat_login", "login", "username", "personal", "passport"}

# евристика «Прізвище Ім'я Батькович»: три слова, останнє з
# типовим закінченням по батькові (укр/рос правопис)
FIO_RE = re.compile(
    r"[А-ЯЇІЄҐA-Z][а-яїієґ'a-z]+\s+"
    r"[А-ЯЇІЄҐA-Z][а-яїієґ'a-z]+\s+"
    r"[А-ЯЇІЄҐA-Z][а-яїієґ'a-z]+"
    r"(?:ович|евич|йович|івна|ївна|івнa)\b")

SECTIONS_PUBLIC_NAMES = {"leader_points", "leader_table"}  # імена відкриті


class Redactor:
    """Одна сесія редагування: двонаправлена мапа псевдонім ↔ значення."""

    def __init__(self, user_id: int, plugin_id: str) -> None:
        self.user_id = user_id
        self.plugin_id = plugin_id
        self._to_alias: dict[str, str] = {}
        self._to_real: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def _alias(self, kind: str, real: str) -> str:
        key = f"{kind}:{real}"
        if key not in self._to_alias:
            n = self._counters.get(kind, 0) + 1
            self._counters[kind] = n
            alias = f"{kind}{n}"
            self._to_alias[key] = alias
            self._to_real[alias] = real
        return self._to_alias[key]

    # --------------------------------------------------------- основне

    def blind(self, section: str, payload) -> object:
        """Рекурсивно підмінює PII-поля псевдонімами (інше не чіпає)."""
        if section in SECTIONS_PUBLIC_NAMES:
            return payload  # імена в лідерборді публічні
        return self._walk(payload)

    def _walk(self, obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if str(k) in PII_FIELDS and isinstance(v, str) and v:
                    out[k] = self._alias("#T", v)
                else:
                    out[k] = self._walk(v)
            return out
        if isinstance(obj, list):
            return [self._walk(x) for x in obj]
        if isinstance(obj, str):
            # вільний текст теж чистимо (тема ДЗ з вчителькою в дужках тощо)
            s = EMAIL_RE.sub("[email]", obj)
            s = PHONE_RE.sub("[phone]", s)
            # T4: евристика «Прізвище Ім'я Батькович» → псевдонім
            s = FIO_RE.sub(lambda m: self._alias("#T", m.group(0)), s)
            return s
        return obj

    def unredact(self, text: str) -> str:
        """Зворотна підміна псевдонімів у виході плагіна."""
        if not self._to_real:
            return text
        # довгі псевдоніми спершу, щоб #T10 не з'їв #T1
        for alias in sorted(self._to_real, key=len, reverse=True):
            text = text.replace(alias, self._to_real[alias])
        return text

    def unredact_obj(self, obj):
        if isinstance(obj, str):
            return self.unredact(obj)
        if isinstance(obj, dict):
            return {k: self.unredact_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.unredact_obj(x) for x in obj]
        return obj


def blind_payloads(user_id: int, plugin_id: str,
                   payloads: dict[str, object]) -> tuple[dict, Redactor]:
    """Санітизує всі секції разом; → (сліпі payload-и, redactor)."""
    r = Redactor(user_id, plugin_id)
    return ({sec: r.blind(sec, data) for sec, data in payloads.items()}, r)


def log_safe(obj: object, limit: int = 4000) -> str:
    """Безпечний лог: знімає email/телефони з рядкового представлення."""
    try:
        s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(obj)
    s = EMAIL_RE.sub("[email]", s)
    s = PHONE_RE.sub("[phone]", s)
    return s[:limit]