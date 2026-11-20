import { session } from "../api.js";
import { h } from "../dom.js";

// Стартовая страница курьера (клиент, ресторан и админ сразу попадают в свои разделы).
const HOME = {
  customer: {
    title: (name) => `${name}, что будем есть?`,
    text: "Скоро здесь появится список ресторанов города. Пока можно заполнить профиль: телефон нужен курьеру.",
  },
  restaurant: {
    title: () => "Ваш ресторан",
    text: "Скоро здесь можно будет завести ресторан, собрать меню и принимать заказы. Пока проверьте контакты в профиле.",
  },
  courier: {
    title: (name) => `${name}, готовы к доставкам?`,
    text: "Скоро здесь появятся заказы, которые ждут курьера. Пока проверьте телефон в профиле: по нему с вами свяжется клиент.",
  },
  admin: {
    title: () => "Администрирование",
    text: "Управляйте пользователями и их ролями.",
  },
};

export function homeView() {
  const user = session.user;
  const content = HOME[user.role] || HOME.customer;
  const firstName = user.full_name.split(" ")[0];
  return h("div", { class: "page" },
    h("section", { class: "welcome" },
      h("h1", { class: "welcome__title" }, content.title(firstName)),
      h("p", { class: "welcome__text" }, content.text),
      h("div", { class: "welcome__actions" },
        user.role === "admin"
          ? h("a", { class: "btn btn--primary", href: "#/admin/users" }, "Открыть пользователей")
          : h("a", { class: "btn btn--primary", href: "#/profile" }, "Открыть профиль"))));
}
