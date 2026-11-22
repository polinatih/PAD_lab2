# Лабораторная работа №2. Микросервисная система доставки еды

Backend сервиса доставки еды, построенный на микросервисной архитектуре. Клиент выбирает ресторан и блюда,
оформляет и оплачивает заказ. Ресторан готовит заказ, курьер его доставляет, а система уведомляет каждого
участника о смене статуса.

**Стек:** Python 3.12, FastAPI, PostgreSQL 16, RabbitMQ, nginx (API Gateway), Docker Compose.
Веб-интерфейс «Ложка»: HTML, CSS и JavaScript без сборки, раздаётся тем же gateway.

* **7 бизнес-микросервисов**, у каждого своя база данных;
* **5 синхронных REST-связей** и **14 типов событий** RabbitMQ (saga «заказ» с компенсациями);
* **60 тестов** (unit) + **7 сквозных e2e-сценариев** через gateway + CI на GitHub Actions;
* **60 endpoint'ов** с OpenAPI/Swagger — полный список в [docs/api.md](docs/api.md);
* веб-интерфейс для четырёх ролей: клиент, ресторан, курьер, администратор.

Документация: [архитектурные решения](docs/architecture.md) · [справочник API](docs/api.md) · [шпаргалка к защите](docs/defense.md)

---

## Архитектура

```
                              ┌───────────────────────────┐
           Client ──────────► │  API Gateway (nginx)      │  routing · X-Request-ID · rate limiting
                              └─────────────┬─────────────┘
     ┌──────────────┬──────────────┬────────┴─────┬──────────────┬──────────────┬──────────────┐
     ▼              ▼              ▼              ▼              ▼              ▼              ▼
 ┌────────┐   ┌────────────┐  ┌────────┐    ┌─────────┐    ┌──────────┐  ┌──────────────┐ ┌────────┐
 │  auth  │   │ restaurant │◄─│ order  │    │ payment │    │ delivery │  │ notification │ │ review │
 └───┬────┘   └─────┬──────┘  └───┬────┘    └────┬────┘    └────┬─────┘  └──────┬───────┘ └───┬────┘
     ▼              ▼     REST    ▼              ▼              ▼               ▼             ▼
  auth_db    restaurant_db     order_db     payment_db     delivery_db   notification_db  review_db

 ═════════════════════════ RabbitMQ: topic exchange "food.events" ═════════════════════════
```

### Сервисы

| Сервис | Ответственность | БД |
|---|---|---|
| **auth-service** | регистрация, вход, JWT; роли `customer`, `restaurant`, `courier`, `admin` | `auth_db` |
| **restaurant-service** | рестораны, меню, цены и наличие блюд | `restaurant_db` |
| **order-service** | оформление заказа, жизненный цикл заказа (state machine) | `order_db` |
| **payment-service** | оплата заказа и возврат денег (эмуляция платёжного шлюза) | `payment_db` |
| **delivery-service** | курьеры, назначение курьера, статусы доставки | `delivery_db` |
| **notification-service** | уведомления клиентам, ресторанам и курьерам | `notification_db` |
| **review-service** | отзывы и рейтинги ресторанов (только после доставки) | `review_db` |

### Главный сценарий (saga «заказ»)

```
customer ──POST /api/orders──► order-service ──REST──► restaurant-service (проверка блюд и цен)
                                    │ status = PENDING_PAYMENT
                                    ▼ order.created
                              payment-service ──► payment.succeeded ──► order: PAID ──► ресторан принимает
                                              └─► payment.failed ────► order: CANCELLED
ресторан: «готово» ──► order.ready ──► delivery-service: курьер берёт заказ ──► delivery.assigned
курьер: «забрал» / «доставил» ──► delivery.picked_up / delivery.delivered ──► order: DELIVERED
                                                                         └──► review-service: можно оставить отзыв
все события ──► notification-service
```

### События (RabbitMQ, exchange `food.events`)

| Событие | Кто публикует | Кто слушает | Что происходит |
|---|---|---|---|
| `order.created` | order-service | payment-service | создаётся платёж, ждём оплату |
| `payment.succeeded` | payment-service | order-service | заказ → «Оплачен» |
| `payment.failed` | payment-service | order-service | заказ → «Отменён» (компенсация: 3 отказа банка или 15 минут без оплаты) |
| `order.cancelled` | order-service | payment-service | если заказ был оплачен — возврат денег, `payment.refunded` |
| `order.paid`, `order.accepted` | order-service | notification-service | ресторану — «новый заказ», клиенту — «оплачен», «готовится» |
| `order.ready` | order-service | delivery-service | заказ появляется у курьеров в списке «Ждут курьера» |
| `delivery.assigned` | delivery-service | order-service | заказ → «Курьер назначен», клиент видит имя и телефон курьера |
| `delivery.picked_up` | delivery-service | order-service | заказ → «Курьер в пути» |
| `delivery.delivered` | delivery-service | order-service, notification-service | заказ → «Доставлен», событие `order.delivered`; курьеру — сумма заработка |
| `order.delivered` | order-service | review-service, notification-service | клиент может оценить ресторан |
| `review.created` | review-service | restaurant-service, notification-service | пересчёт рейтинга в каталоге, уведомление ресторану |
| `payment.refunded` | payment-service | notification-service | клиенту — «деньги вернутся на карту» |
| `user.registered` | auth-service | notification-service | приветствие |

notification-service слушает почти все события, но **никто не вызывает его напрямую**: если он недоступен,
события ждут в его очереди RabbitMQ, а остальная система работает как обычно.

События order-service, payment-service, delivery-service и review-service отправляются через **transactional outbox**: событие пишется в БД
в той же транзакции, что и изменение заказа или платежа, и не теряется, даже если брокер временно недоступен.

### Синхронные вызовы (REST)

Только там, где ответ нужен немедленно. Внутренние endpoint'ы `/internal/*` защищены ключом `X-Internal-Key`
и не проброшены наружу через gateway.

| Кто → кого | Зачем | Если сосед недоступен |
|---|---|---|
| order → restaurant `POST /internal/restaurants/{id}/quote` | проверить блюда и посчитать цену (браузеру не доверяем) | заказ не оформляется, клиент получает 503 |
| order → auth `GET /internal/users/{id}` | имя и телефон клиента для курьера | заказ оформляется с телефоном из формы |
| delivery → auth `GET /internal/users/{id}` | имя и телефон курьера для клиента | курьер берёт заказ, имя берётся из токена |
| delivery → order `GET /internal/orders?status=ready` | сверка при старте: заказы, событие о которых было пропущено | повтор через 3 секунды |
| review → order `GET /internal/orders?status=delivered` | сверка при старте: доставленные заказы, которые можно оценить | повтор через 3 секунды |

Все вызовы идут через общий [`ServiceClient`](libs/common/common/http.py): таймаут, повторы с паузой для
временных ошибок, проброс `X-Request-ID`, перевод ошибок соседа в понятные коды (404, 503, 504).

### Database per service

У каждого сервиса своя база PostgreSQL и свой пользователь. [`init-databases.sh`](infrastructure/postgres/init-databases.sh)
делает `REVOKE CONNECT ... FROM PUBLIC`, поэтому сервис физически не может подключиться к чужой базе.
Сервер PostgreSQL один (экономия ресурсов в учебном окружении), базы разные — разнести их по серверам можно,
поменяв `DATABASE_URL`. Данные, нужные другим сервисам, передаются в событиях (например, имя ресторана и
владелец — в `order.paid`), а не через общие таблицы.

### Общая инфраструктура (`libs/common`)

Код без бизнес-логики, одинаковый для всех сервисов:

| Модуль | Что делает |
|---|---|
| `logging.py` | структурированные JSON-логи: `timestamp`, `service`, `level`, `request_id`, `message` |
| `middleware.py` | `X-Request-ID` для каждого запроса + access-лог |
| `errors.py` | единый формат ошибок `{"error": {"code", "message", "request_id"}}`, без stack trace |
| `health.py` | `GET /health` (liveness) и `GET /ready` (readiness с проверкой БД и брокера) |
| `auth.py` | проверка JWT, роли, защита внутренних endpoint'ов ключом `X-Internal-Key` |
| `http.py` | HTTP-клиент для вызовов между сервисами: таймауты, повторы, проброс request_id |
| `messaging.py` | RabbitMQ: публикация и подписка, повтор при ошибке, dead-letter очереди |
| `db.py`, `config.py`, `app.py` | подключение к БД, настройки из env, фабрика FastAPI-приложения |

---

## Выбор технологий

| Технология | Где | Почему |
|---|---|---|
| **Python 3.12 + FastAPI** | все сервисы | асинхронный I/O (сервисы в основном ждут БД и сеть), OpenAPI/Swagger генерируется автоматически, валидация через Pydantic |
| **PostgreSQL 16** | 7 баз | транзакции (нужны для outbox и атомарного «взять заказ»), ограничения уникальности против дублей, надёжный стандарт |
| **SQLAlchemy 2 (async) + asyncpg** | доступ к БД | не блокирует event loop; в unit-тестах те же модели работают на SQLite |
| **RabbitMQ** | события | нужна именно очередь задач с подтверждением, повтором и dead-letter очередями; Kafka избыточна (не нужны replay и огромный поток), RabbitMQ проще и даёт наглядный UI |
| **nginx** | API Gateway | проверенный reverse proxy с rate limiting из коробки; в ЛР3 почти напрямую переходит в Kubernetes Ingress |
| **JWT (HS256)** | аутентификация | stateless: каждый сервис проверяет подпись сам, без запроса в auth-service на каждый вызов |
| **Vanilla JS (ES-модули)** | веб-интерфейс | не нужна сборка и Node.js; nginx раздаёт файлы как есть |
| **Docker Compose** | запуск | вся система одной командой; подготовка к Kubernetes в ЛР3 |

---

## Запуск

Требуется Docker Desktop (Compose v2.20+).

```bash
copy .env.example .env          # Linux/macOS: cp .env.example .env
docker compose up -d --build
```

| Что | Адрес |
|---|---|
| Веб-интерфейс | http://localhost:8080 |
| API Gateway | http://localhost:8080/api/... (проверка: http://localhost:8080/health) |
| Swagger UI | http://localhost:8080/docs |
| RabbitMQ UI | http://localhost:15672 (логин и пароль из `.env`) |

Администратор создаётся автоматически: `admin@example.com` / `admin12345` (меняется в `.env`).

При запуске контейнер `demo-seed` загружает демо-данные: 6 ресторанов Кишинёва с меню и тестовые аккаунты.
Пароль у всех демо-аккаунтов `demo12345`:

| Email | Роль |
|---|---|
| `client@demo.md` | клиент |
| `courier@demo.md` | курьер |
| `owner1@demo.md`, `owner2@demo.md`, `owner3@demo.md` | владельцы ресторанов |

> Новые колонки в существующих таблицах добавляются автоматически при старте сервиса (`libs/common/common/db.py`),
> поэтому базу между этапами пересоздавать не нужно.
>
> **После обновления проекта** (новый этап) выполните `docker compose up -d --build`, а затем
> `docker compose restart gateway`: nginx читает свою конфигурацию только при старте.

### Основные endpoint'ы

Полный список (60 endpoint'ов, включая `/health` и `/ready` у каждого сервиса) — в [docs/api.md](docs/api.md).

```
POST  /api/auth/register         регистрация (роль: customer | restaurant | courier)
POST  /api/auth/login            вход → JWT + данные пользователя
GET   /api/auth/me               мой профиль
PATCH /api/auth/me               изменить имя или телефон
GET   /api/auth/users            список пользователей (admin)
PATCH /api/auth/users/{id}/role  изменить роль (admin)

GET   /api/restaurants                     каталог (поиск ?q=, фильтры ?cuisine=, ?open_only=)
GET   /api/restaurants/{id}                ресторан и меню
GET   /api/restaurants/mine                мои рестораны (владелец)
POST  /api/restaurants                     открыть ресторан (роль restaurant)
PATCH /api/restaurants/{id}                изменить, открыть или закрыть приём заказов
POST  /api/restaurants/{id}/menu           добавить блюдо
PATCH /api/restaurants/{id}/menu/{item}    цена, наличие
POST  /internal/restaurants/{id}/quote     проверка блюд и расчёт стоимости (для order-service)

POST  /api/orders                          оформить заказ (заголовок Idempotency-Key защищает от двойного клика)
GET   /api/orders                          мои заказы (?active=true, ?status=paid,cooking)
GET   /api/orders/{id}                     заказ: состав и история статусов
POST  /api/orders/{id}/cancel              отменить заказ (клиент — до начала готовки, ресторан — отказаться)
POST  /api/orders/{id}/accept              ресторан: принять и начать готовить
POST  /api/orders/{id}/ready               ресторан: готово, нужен курьер

GET   /api/payments/order/{order_id}       платёж по заказу
POST  /api/payments/order/{order_id}/pay   оплатить картой (тест: 4242 4242 4242 4242 — успех, 4000 0000 0000 0002 — отказ)
GET   /api/payments                        все платежи (admin)

GET   /api/deliveries/couriers/me          курьер: на линии ли, статистика за сегодня
PUT   /api/deliveries/couriers/me          выйти на линию / уйти с линии
GET   /api/deliveries/available            заказы, которые ждут курьера
POST  /api/deliveries/{id}/claim           взять заказ (только один курьер получит заказ)
POST  /api/deliveries/{id}/pickup          забрал в ресторане
POST  /api/deliveries/{id}/deliver         доставил
GET   /api/deliveries/mine                 мои доставки

GET   /api/notifications                   мои уведомления
GET   /api/notifications/unread-count      сколько непрочитанных
POST  /api/notifications/read-all          прочитать все

GET   /api/reviews/restaurant/{id}         отзывы и рейтинг ресторана (публично)
GET   /api/reviews/order/{order_id}        можно ли оценить заказ
POST  /api/reviews                         оценить доставленный заказ (1–5 звёзд)
POST  /api/reviews/{id}/reply              ответ ресторана на отзыв

GET   /health, /ready            у каждого сервиса
```

---

## Сквозные требования

### Аутентификация и авторизация
* JWT выпускает auth-service, пароли хранятся как PBKDF2-SHA256 с солью; стать администратором через регистрацию нельзя.
* Каждый сервис проверяет подпись токена сам ([common/auth.py](libs/common/common/auth.py)) и проверяет права на свои данные:
  заказ видят только клиент, ресторан, назначенный курьер и админ; меню меняет только владелец ресторана; и т.д.
* Чужие объекты возвращают `404`, а не `403` — не раскрываем, что они существуют.

### Обработка ошибок
Единый формат во всех сервисах и в gateway, stack trace — только в логах:

```json
{"error": {"code": "restaurant_closed", "message": "Ресторан сейчас закрыт и не принимает заказы", "request_id": "e2e-trace-42"}}
```

| Ситуация | Код |
|---|---|
| неправильные входные данные | 422 `validation_error` (с `details` по полям), 400 `below_min_order`, … |
| нет ресурса | 404 `not_found` |
| нет или неверный токен / нет прав | 401 `invalid_token` / 403 `forbidden` |
| бизнес-конфликт | 409 `restaurant_closed`, `already_taken`, `invalid_status_transition`, … |
| отказ банка | 402 `card_declined`, `payment_failed` |
| соседний сервис недоступен / не ответил вовремя | 503 `service_unavailable` / 504 `upstream_timeout` |
| ошибка БД | 503 `database_error` |
| слишком много запросов | 429 `rate_limited` |

Ошибка соседнего сервиса пробрасывается с исходным кодом: если ресторан закрыт, клиент получает
`409 restaurant_closed`, а не абстрактную «ошибку».

### Logging
JSON-логи в stdout у каждого сервиса и у gateway ([common/logging.py](libs/common/common/logging.py)):

```json
{"timestamp": "2026-11-22T13:40:11.412+00:00", "service": "order-service", "level": "INFO",
 "request_id": "71f2428174e1e8c4", "logger": "orders", "message": "Order EB6562: Ожидает оплаты -> Оплачен"}
```

`X-Request-ID` создаётся на gateway и передаётся в HTTP-вызовах **и внутри событий RabbitMQ**, поэтому один
запрос можно проследить через все сервисы: `docker compose logs | findstr <request_id>` (Linux: `grep`).

### Configuration management
Каждый сервис описывает настройки классом `Settings` (pydantic-settings, `app/config.py`): типы, значения по умолчанию,
проверка при старте. Значения приходят из переменных окружения; в `docker-compose.yml` у каждого сервиса свой блок
`environment`, секреты — в `.env`.

### Health checks
* `GET /health` — liveness: процесс жив.
* `GET /ready` — readiness: доступны ли БД и RabbitMQ; если нет — `503` и `{"checks": {"database": "ok", "rabbitmq": "fail"}}`.
* Docker healthcheck использует `/ready`; в ЛР3 это станут `livenessProbe` и `readinessProbe`.

### Устойчивость
* **Transactional outbox** — событие не теряется, даже если брокер недоступен в момент изменения.
* **Идемпотентные обработчики** — повторная доставка события ничего не ломает (уникальные ключи, проверка статуса).
* **Dead-letter очереди** — сообщение, которое не удалось обработать дважды, не теряется и не зацикливается.
* **Сверка при старте** — delivery-service и review-service подхватывают события, пропущенные пока они не работали.
* **Компенсации в saga** — нет оплаты → заказ отменяется; ресторан отказался от оплаченного заказа → деньги возвращаются.
* **Idempotency-Key** — двойной клик «Оформить» не создаёт два заказа.
* **Атомарное «взять заказ»** — `UPDATE ... WHERE status = 'searching'`, заказ получает ровно один курьер.
* **Rate limiting** на gateway, строже для `/api/auth/login`.

---

## Тестирование

| Уровень | Что проверяется | Запуск |
|---|---|---|
| **Unit/API** (60 тестов) | каждый сервис изолированно: SQLite вместо PostgreSQL, in-memory шина событий, `httpx.MockTransport` вместо соседних сервисов. Проверены права доступа, state machine, saga, идемпотентность, недоступность и таймауты соседей | `python scripts/run_unit_tests.py` |
| **E2E** (7 сценариев) | вся система через gateway: полный путь заказа от оформления до отзыва, отказы банка и отмена, возврат денег, бизнес-правила, Idempotency-Key, Request ID, формат ошибок | `pytest tests/e2e -v` (система запущена) |
| **CI** | GitHub Actions на каждый push: unit-тесты и сборка всех Docker-образов | вкладка **Actions** на GitHub |

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r tests/requirements.txt
python scripts/run_unit_tests.py   # unit
pytest tests/e2e -v                # e2e (нужен запущенный docker compose)
```

---

## Соответствие критериям оценивания

| Критерий | Где в проекте |
|---|---|
| 5–6+ микросервисов (20%) | 7 бизнес-сервисов (gateway, БД и UI не считаются) — раздел «Сервисы» |
| Архитектура и разделение ответственности (20%) | у каждого сервиса своя ответственность, API, логика, БД, конфигурация и Dockerfile; общий код — только инфраструктурный; [docs/architecture.md](docs/architecture.md) |
| Взаимодействие сервисов (15%) | 5 REST-связей + 14 типов событий, saga с компенсациями, outbox, DLQ, сверка при старте |
| Database / persistence (10%) | 7 баз PostgreSQL с изоляцией, транзакции, ограничения уникальности, автодобавление колонок |
| API и документация (10%) | OpenAPI/Swagger у каждого сервиса, [docs/api.md](docs/api.md), этот README |
| Authentication / authorization (5%) | JWT, 4 роли, права на данные, внутренний ключ для `/internal/*` |
| Logging / error handling (10%) | JSON-логи с request_id через HTTP и RabbitMQ, единый формат ошибок, коды соседей пробрасываются |
| Тестирование (10%) | 60 unit + 7 e2e + CI |

---

## План разработки

- [x] **Этап 1.** Каркас: структура репозитория, общая библиотека, docker-compose (PostgreSQL, RabbitMQ), API Gateway
- [x] **Этап 2.** auth-service: регистрация, вход, JWT, роли + веб-интерфейс: вход, регистрация, профиль, управление пользователями
- [x] **Этап 3.** restaurant-service: рестораны и меню + UI: каталог ресторанов, кабинет ресторана, демо-данные
- [x] **Этап 4.** order-service: оформление заказа, синхронная проверка блюд в restaurant-service, outbox, Idempotency-Key + UI: корзина, мои заказы, отслеживание заказа
- [x] **Этап 5.** payment-service: оплата через события RabbitMQ (saga), возвраты, тайм-аут оплаты + UI: оплата картой, доска заказов ресторана
- [x] **Этап 6.** delivery-service: курьеры и доставка, сверка пропущенных заказов + UI: кабинет курьера, курьер в заказе клиента
- [x] **Этап 7.** notification-service и review-service + UI: колокольчик с уведомлениями, оценка заказа, отзывы и рейтинг ресторана, ответы ресторана
- [x] **Этап 8.** E2E-тесты, CI на GitHub Actions, документация API, архитектурные решения, шпаргалка к защите

## Структура репозитория

```
├── README.md
├── docker-compose.yml
├── .env.example
├── services/                 # микросервисы
│   ├── auth-service/         #   app/ (код), tests/, Dockerfile, requirements.txt
│   ├── restaurant-service/
│   ├── order-service/
│   ├── payment-service/
│   ├── delivery-service/
│   ├── notification-service/
│   └── review-service/
├── frontend/                 # веб-интерфейс (раздаётся gateway)
├── libs/common/              # общая инфраструктурная библиотека
├── gateway/                  # конфигурация nginx (API Gateway)
├── infrastructure/postgres/  # создание отдельной БД для каждого сервиса
├── tests/e2e/                # сквозные тесты через gateway
├── scripts/                  # seed_demo.py (демо-данные), run_unit_tests.py
├── .github/workflows/        # CI: тесты и сборка образов на каждый push
└── docs/                     # architecture.md, api.md, defense.md
```
