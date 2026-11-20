export const ROLE_LABELS = {
  customer: "Клиент",
  restaurant: "Ресторан",
  courier: "Курьер",
  admin: "Администратор",
};

// Пункты меню для каждой роли. match — какие страницы подсвечивают пункт как текущий.
const CATALOG = { href: "#/catalog", label: "Рестораны", match: /^\/(catalog|restaurants\/.+)?$/ };

export const NAV = {
  customer: [CATALOG, { href: "#/orders", label: "Мои заказы", match: /^\/orders/ }],
  restaurant: [{ href: "#/my", label: "Мои рестораны", match: /^\/(my(\/.+)?)?$/ },
               { ...CATALOG, match: /^\/(catalog|restaurants\/.+)$/ }],
  courier: [],
  admin: [CATALOG, { href: "#/admin/users", label: "Пользователи" }],
};
