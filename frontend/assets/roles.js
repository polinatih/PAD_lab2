export const ROLE_LABELS = {
  customer: "Клиент",
  restaurant: "Ресторан",
  courier: "Курьер",
  admin: "Администратор",
};

// Пункты меню для каждой роли. Новые разделы добавляются сюда по мере появления сервисов.
export const NAV = {
  customer: [],
  restaurant: [],
  courier: [],
  admin: [{ href: "#/admin/users", label: "Пользователи" }],
};
