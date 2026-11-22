# Справочник API

Сгенерирован из OpenAPI-схем сервисов. Интерактивная документация (Swagger UI): http://localhost:8080/docs

* **public** — без авторизации;
* **JWT** — нужен заголовок `Authorization: Bearer <token>` из `POST /api/auth/login`;
* **internal** — только для вызовов между сервисами (заголовок `X-Internal-Key`), через gateway недоступны.

## auth-service

Swagger: `/docs/auth/`

| Метод | Путь | Описание | Доступ |
|---|---|---|---|
| GET | `/health` | Liveness probe | public |
| GET | `/ready` | Readiness probe (проверяет зависимости) | public |
| POST | `/api/auth/register` | Регистрация | public |
| POST | `/api/auth/login` | Вход, получение JWT | public |
| GET | `/api/auth/me` | Мой профиль | JWT |
| PATCH | `/api/auth/me` | Изменить имя или телефон | JWT |
| GET | `/api/auth/users` | Список пользователей (admin) | JWT |
| PATCH | `/api/auth/users/{user_id}/role` | Изменить роль (admin) | JWT |
| GET | `/internal/users/{user_id}` | Данные пользователя (для других сервисов) | internal |

## restaurant-service

Swagger: `/docs/restaurants/`

| Метод | Путь | Описание | Доступ |
|---|---|---|---|
| GET | `/health` | Liveness probe | public |
| GET | `/ready` | Readiness probe (проверяет зависимости) | public |
| GET | `/api/restaurants` | Каталог ресторанов | public |
| POST | `/api/restaurants` | Открыть ресторан (роль restaurant) | JWT |
| GET | `/api/restaurants/cuisines` | Кухни, которые есть в каталоге | public |
| GET | `/api/restaurants/mine` | Мои рестораны (владелец) | JWT |
| GET | `/api/restaurants/{restaurant_id}` | Ресторан и его меню | public |
| PATCH | `/api/restaurants/{restaurant_id}` | Изменить ресторан, открыть или закрыть | JWT |
| POST | `/api/restaurants/{restaurant_id}/menu` | Добавить блюдо | JWT |
| PATCH | `/api/restaurants/{restaurant_id}/menu/{item_id}` | Изменить блюдо (цена, наличие) | JWT |
| DELETE | `/api/restaurants/{restaurant_id}/menu/{item_id}` | Удалить блюдо | JWT |
| GET | `/internal/restaurants/{restaurant_id}` | Данные ресторана | internal |
| POST | `/internal/restaurants/{restaurant_id}/quote` | Проверить блюда и посчитать стоимость заказа | internal |

## order-service

Swagger: `/docs/orders/`

| Метод | Путь | Описание | Доступ |
|---|---|---|---|
| GET | `/health` | Liveness probe | public |
| GET | `/ready` | Readiness probe (проверяет зависимости) | public |
| POST | `/api/orders` | Оформить заказ | JWT |
| GET | `/api/orders` | Мои заказы | JWT |
| GET | `/api/orders/{order_id}` | Заказ: состав и история статусов | JWT |
| POST | `/api/orders/{order_id}/cancel` | Отменить заказ | JWT |
| POST | `/api/orders/{order_id}/accept` | Ресторан: принять заказ и начать готовить | JWT |
| POST | `/api/orders/{order_id}/ready` | Ресторан: заказ готов, нужен курьер | JWT |
| GET | `/internal/orders` | Заказы по статусу (для сверки другими сервисами) | internal |
| GET | `/internal/orders/{order_id}` | Заказ (для других сервисов) | internal |

## payment-service

Swagger: `/docs/payments/`

| Метод | Путь | Описание | Доступ |
|---|---|---|---|
| GET | `/health` | Liveness probe | public |
| GET | `/ready` | Readiness probe (проверяет зависимости) | public |
| GET | `/api/payments/order/{order_id}` | Платёж по заказу | JWT |
| POST | `/api/payments/order/{order_id}/pay` | Оплатить заказ картой | JWT |
| GET | `/api/payments` | Все платежи (admin) | JWT |

## delivery-service

Swagger: `/docs/deliveries/`

| Метод | Путь | Описание | Доступ |
|---|---|---|---|
| GET | `/health` | Liveness probe | public |
| GET | `/ready` | Readiness probe (проверяет зависимости) | public |
| GET | `/api/deliveries/couriers/me` | Мой статус и статистика за сегодня | JWT |
| PUT | `/api/deliveries/couriers/me` | Выйти на линию или уйти с линии | JWT |
| GET | `/api/deliveries/available` | Заказы, которые ждут курьера | JWT |
| GET | `/api/deliveries/mine` | Мои доставки | JWT |
| GET | `/api/deliveries/order/{order_id}` | Доставка по заказу | JWT |
| POST | `/api/deliveries/{delivery_id}/claim` | Взять заказ | JWT |
| POST | `/api/deliveries/{delivery_id}/pickup` | Забрал заказ в ресторане | JWT |
| POST | `/api/deliveries/{delivery_id}/deliver` | Доставил заказ клиенту | JWT |

## notification-service

Swagger: `/docs/notifications/`

| Метод | Путь | Описание | Доступ |
|---|---|---|---|
| GET | `/health` | Liveness probe | public |
| GET | `/ready` | Readiness probe (проверяет зависимости) | public |
| GET | `/api/notifications` | Мои уведомления | JWT |
| GET | `/api/notifications/unread-count` | Сколько непрочитанных | JWT |
| POST | `/api/notifications/read-all` | Отметить все прочитанными | JWT |
| POST | `/api/notifications/{notification_id}/read` | Отметить прочитанным | JWT |

## review-service

Swagger: `/docs/reviews/`

| Метод | Путь | Описание | Доступ |
|---|---|---|---|
| GET | `/health` | Liveness probe | public |
| GET | `/ready` | Readiness probe (проверяет зависимости) | public |
| GET | `/api/reviews/restaurant/{restaurant_id}` | Отзывы о ресторане (публично) | public |
| GET | `/api/reviews/order/{order_id}` | Можно ли оценить заказ и отзыв на него | JWT |
| POST | `/api/reviews` | Оставить отзыв на доставленный заказ | JWT |
| GET | `/api/reviews/owner` | Отзывы о моих ресторанах (владелец) | JWT |
| POST | `/api/reviews/{review_id}/reply` | Ответить на отзыв (ресторан) | JWT |

## Формат ошибок

Все сервисы и gateway возвращают ошибки одинаково, без stack trace:

```json
{"error": {"code": "validation_error", "message": "Некорректные входные данные", "request_id": "…", "details": [...]}}
```
