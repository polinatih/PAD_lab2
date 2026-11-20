"""Наполняет систему демо-данными: аккаунты, рестораны Кишинёва и их меню.

Работает через API Gateway, как обычный клиент, и использует только стандартную библиотеку Python.
Запускается автоматически контейнером demo-seed при `docker compose up`. Можно запустить и вручную:
    python scripts/seed_demo.py --base http://localhost:8080
Повторный запуск ничего не дублирует.

Демо-аккаунты (пароль у всех: demo12345):
    client@demo.md   — клиент
    courier@demo.md  — курьер
    owner1@demo.md, owner2@demo.md, owner3@demo.md — владельцы ресторанов
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

PASSWORD = "demo12345"

ACCOUNTS = [
    ("client@demo.md", "Мария Ионеску", "customer", "+373 69 111 222"),
    ("courier@demo.md", "Андрей Руссу", "courier", "+373 79 333 444"),
    ("owner1@demo.md", "Виктор Чебан", "restaurant", "+373 22 555 001"),
    ("owner2@demo.md", "Елена Бодиу", "restaurant", "+373 22 555 002"),
    ("owner3@demo.md", "Ион Морарь", "restaurant", "+373 22 555 003"),
]

RESTAURANTS = {
    "owner1@demo.md": [
        {
            "name": "Тесто", "cuisine": "Пицца", "address": "ул. Пушкина, 24",
            "description": "Неаполитанская пицца из дровяной печи. Тесто зреет 48 часов.",
            "delivery_fee": 25, "min_order": 120, "prep_minutes": 20,
            "menu": [
                ("Маргарита", "Пицца", 129, "Томаты, моцарелла, базилик"),
                ("Пепперони", "Пицца", 149, "Острая салями, моцарелла, томатный соус"),
                ("Четыре сыра", "Пицца", 165, "Моцарелла, горгонзола, пармезан, брынза"),
                ("Тирамису", "Десерты", 75, "Маскарпоне, савоярди, эспрессо"),
                ("Лимонад с мятой", "Напитки", 35, "0,4 л"),
            ],
        },
        {
            "name": "Гриль 22", "cuisine": "Бургеры", "address": "бул. Дачия, 22",
            "description": "Бургеры на углях и картофель, нарезанный вручную.",
            "delivery_fee": 30, "min_order": 100, "prep_minutes": 25, "is_open": False,
            "menu": [
                ("Классический", "Бургеры", 115, "Говядина, чеддер, маринованный огурец"),
                ("Двойной чизбургер", "Бургеры", 155, "Две котлеты, двойной чеддер"),
                ("Картофель по-деревенски", "Гарниры", 45, "С соусом из копчёного перца"),
                ("Ванильный милкшейк", "Напитки", 55, "0,4 л"),
            ],
        },
    ],
    "owner2@demo.md": [
        {
            "name": "Бабушкины плачинты", "cuisine": "Молдавская", "address": "ул. Митрополит Варлаам, 58",
            "description": "Плачинты, мамалыга и зама по семейным рецептам.",
            "delivery_fee": 20, "min_order": 80, "prep_minutes": 30,
            "menu": [
                ("Плачинта с брынзой", "Плачинты", 45, "Тонкое тесто, брынза, зелень"),
                ("Плачинта с картофелем", "Плачинты", 40, "Картофель, жареный лук"),
                ("Плачинта с тыквой", "Плачинты", 45, "Тыква, корица, немного сахара"),
                ("Мамалыга с брынзой и сметаной", "Горячее", 89, "Подаётся со шкварками"),
                ("Зама", "Супы", 55, "Куриный суп с домашней лапшой и борщем"),
                ("Компот из сухофруктов", "Напитки", 25, "0,5 л"),
            ],
        },
        {
            "name": "Мцвади", "cuisine": "Грузинская", "address": "ул. Алексея Матеевича, 77",
            "description": "Хинкали ручной лепки и хачапури из тандыра.",
            "delivery_fee": 30, "min_order": 150, "prep_minutes": 35,
            "menu": [
                ("Хинкали с говядиной, 5 шт.", "Хинкали", 95, "Говядина, свинина, зелень, бульон"),
                ("Хинкали с сыром, 5 шт.", "Хинкали", 90, "Сулугуни, имеретинский сыр"),
                ("Хачапури по-аджарски", "Выпечка", 120, "Сыр, яйцо, сливочное масло"),
                ("Лобио", "Горячее", 70, "Красная фасоль, кинза, орехи"),
                ("Тархун", "Напитки", 30, "0,5 л"),
            ],
        },
    ],
    "owner3@demo.md": [
        {
            "name": "Сакура Бокс", "cuisine": "Суши", "address": "пр. Штефан чел Маре, 132",
            "description": "Роллы и сеты. Рис варим каждые два часа.",
            "delivery_fee": 35, "min_order": 200, "prep_minutes": 30,
            "menu": [
                ("Филадельфия", "Роллы", 189, "Лосось, сливочный сыр, огурец"),
                ("Калифорния", "Роллы", 159, "Краб, авокадо, тобико"),
                ("Сет «На двоих», 32 шт.", "Сеты", 459, "Филадельфия, Калифорния, маки с огурцом и лососем"),
                ("Мисо-суп", "Супы", 49, "Тофу, вакамэ, зелёный лук"),
                ("Гёдза с курицей", "Закуски", 89, "6 шт., соус понзу"),
            ],
        },
        {
            "name": "Зелёная тарелка", "cuisine": "Здоровая еда", "address": "ул. Букурешть, 41",
            "description": "Боулы, салаты и смузи. Считаем калории за вас.",
            "delivery_fee": 25, "min_order": 90, "prep_minutes": 15,
            "menu": [
                ("Боул с киноа и курицей", "Боулы", 129, "Киноа, курица гриль, авокадо, эдамаме"),
                ("Боул с лососем", "Боулы", 159, "Рис, лосось, огурец, манго"),
                ("Салат с печёной свёклой", "Салаты", 85, "Свёкла, брынза, руккола, орехи"),
                ("Смузи «Шпинат и яблоко»", "Напитки", 55, "0,4 л"),
            ],
        },
    ],
}


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body=None, token: str | None = None):
        for attempt in range(5):  # gateway ограничивает частоту запросов (429) — подождём и повторим
            status, payload = self._call(method, path, body, token)
            if status != 429:
                return status, payload
            time.sleep(3 * (attempt + 1))
        return status, payload

    def _call(self, method: str, path: str, body=None, token: str | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                try:
                    return resp.status, json.loads(raw) if raw else None
                except ValueError:  # пришёл не JSON (например, HTML) — значит, маршрут ведёт не туда
                    return 502, {"raw": raw[:200].decode(errors="replace")}
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                return err.code, json.loads(raw)
            except ValueError:
                return err.code, {"raw": raw.decode(errors="replace")}

    def wait_ready(self, attempts: int = 60) -> None:
        print(f"Жду, пока сервисы станут доступны через {self.base} ...")
        status = None
        for _ in range(attempts):
            try:
                status, _ = self._call("GET", "/api/restaurants")
                if status == 200:
                    return
            except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
                status = repr(exc)
            time.sleep(2)
        hint = (" Gateway не знает маршрут /api/restaurants: перезапустите его командой"
                " docker compose restart gateway") if status == 404 else ""
        sys.exit(f"Сервисы не ответили (последний ответ: {status}), демо-данные не загружены.{hint}")

    def login(self, email: str, full_name: str, role: str, phone: str) -> str:
        status, body = self.call("POST", "/api/auth/register",
                                 {"email": email, "password": PASSWORD, "full_name": full_name, "role": role, "phone": phone})
        if status not in (201, 409):
            sys.exit(f"Не удалось создать {email}: {status} {body}")
        status, body = self.call("POST", "/api/auth/login", {"email": email, "password": PASSWORD})
        if status != 200:
            sys.exit(f"Не удалось войти как {email}: {status} {body}")
        return body["access_token"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    api = Api(ap.parse_args().base)
    api.wait_ready()

    tokens = {email: api.login(email, name, role, phone) for email, name, role, phone in ACCOUNTS}
    print(f"Аккаунты готовы: {', '.join(tokens)} (пароль {PASSWORD})")

    for owner, restaurants in RESTAURANTS.items():
        token = tokens[owner]
        _, mine = api.call("GET", "/api/restaurants/mine", token=token)
        existing = {r["name"] for r in mine or []}
        for spec in restaurants:
            if spec["name"] in existing:
                print(f"  {spec['name']}: уже есть")
                continue
            body = {k: v for k, v in spec.items() if k not in ("menu", "is_open")}
            status, rest = api.call("POST", "/api/restaurants", body, token=token)
            if status != 201:
                sys.exit(f"Не удалось создать {spec['name']}: {status} {rest}")
            for name, category, price, description in spec["menu"]:
                api.call("POST", f"/api/restaurants/{rest['id']}/menu",
                         {"name": name, "category": category, "price": price, "description": description}, token=token)
            if spec.get("is_open") is False:
                api.call("PATCH", f"/api/restaurants/{rest['id']}", {"is_open": False}, token=token)
            print(f"  {spec['name']}: создан, блюд в меню: {len(spec['menu'])}")
    print("Демо-данные загружены")


if __name__ == "__main__":
    main()
