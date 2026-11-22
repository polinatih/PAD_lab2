# Лабораторная работа №2. Микросервисная система доставки еды

Backend сервиса доставки еды, построенный на микросервисной архитектуре. Клиент выбирает ресторан и блюда,
оформляет и оплачивает заказ. Ресторан готовит заказ, курьер его доставляет, а система уведомляет каждого
участника о смене статуса.

**Стек:** Python 3.12, FastAPI, PostgreSQL 16, RabbitMQ, nginx (API Gateway), Docker Compose.
Веб-интерфейс «Ложка»: HTML, CSS и JavaScript без сборки, раздаётся тем же gateway.

> Проект разрабатывается поэтапно, прогресс отмечен в разделе [План разработки](#план-разработки).

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
ресторан: «готово» ──► order.ready ──► delivery-service назначает курьера ──► delivery.assigned
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

### Тесты

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r tests/requirements.txt
python scripts/run_unit_tests.py
```

---

## План разработки

- [x] **Этап 1.** Каркас: структура репозитория, общая библиотека, docker-compose (PostgreSQL, RabbitMQ), API Gateway
- [x] **Этап 2.** auth-service: регистрация, вход, JWT, роли + веб-интерфейс: вход, регистрация, профиль, управление пользователями
- [x] **Этап 3.** restaurant-service: рестораны и меню + UI: каталог ресторанов, кабинет ресторана, демо-данные
- [x] **Этап 4.** order-service: оформление заказа, синхронная проверка блюд в restaurant-service, outbox, Idempotency-Key + UI: корзина, мои заказы, отслеживание заказа
- [x] **Этап 5.** payment-service: оплата через события RabbitMQ (saga), возвраты, тайм-аут оплаты + UI: оплата картой, доска заказов ресторана
- [x] **Этап 6.** delivery-service: курьеры и доставка, сверка пропущенных заказов + UI: кабинет курьера, курьер в заказе клиента
- [x] **Этап 7.** notification-service и review-service + UI: колокольчик с уведомлениями, оценка заказа, отзывы и рейтинг ресторана, ответы ресторана
- [ ] **Этап 8.** E2E-тесты, документация API, финальный README

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
├── tests/                    # e2e-тесты
├── scripts/                  # seed_demo.py (демо-данные), run_unit_tests.py
└── docs/                     # документация
```
