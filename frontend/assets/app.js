// Точка входа веб-интерфейса: маршрутизация по hash (#/...), оболочка приложения, проверка входа.
import { api, session } from "./api.js";
import { h, icon, toast } from "./dom.js";
import { NAV, ROLE_LABELS } from "./roles.js";
import { adminUsersView } from "./views/admin-users.js";
import { cart } from "./cart.js";
import { authView } from "./views/auth.js";
import { cartView } from "./views/cart.js";
import { catalogView, restaurantView } from "./views/catalog.js";
import { courierHistoryView, courierView } from "./views/courier.js";
import { homeView } from "./views/home.js";
import { notificationsBell, resetNotifications } from "./views/notifications.js";
import { kitchenView } from "./views/kitchen.js";
import { orderView, ordersView } from "./views/orders.js";
import { manageRestaurantView, myRestaurantsView } from "./views/owner.js";
import { profileView } from "./views/profile.js";

const root = document.getElementById("app");

// Стартовая страница зависит от роли
const HOME_BY_ROLE = { customer: catalogView, admin: catalogView, restaurant: kitchenView, courier: courierView };

// Маршруты: шаблон пути (":id" — параметр) -> { view, roles?, public? }
const routes = [
  ["/login", { view: (ctx) => authView({ ...ctx, mode: "login" }), public: true }],
  ["/register", { view: (ctx) => authView({ ...ctx, mode: "register" }), public: true }],
  ["/", { view: (ctx) => (HOME_BY_ROLE[session.user?.role] || homeView)(ctx) }],
  ["/catalog", { view: catalogView }],
  ["/restaurants/:id", { view: restaurantView }],
  ["/cart", { view: cartView, roles: ["customer"] }],
  ["/orders", { view: ordersView }],
  ["/orders/:id", { view: orderView }],
  ["/kitchen", { view: kitchenView, roles: ["restaurant", "admin"] }],
  ["/courier", { view: courierView, roles: ["courier"] }],
  ["/courier/history", { view: courierHistoryView, roles: ["courier"] }],
  ["/my", { view: myRestaurantsView, roles: ["restaurant", "admin"] }],
  ["/my/:id", { view: manageRestaurantView, roles: ["restaurant", "admin"] }],
  ["/profile", { view: profileView }],
  ["/admin/users", { view: adminUsersView, roles: ["admin"] }],
].map(([pattern, route]) => ({
  ...route,
  regex: new RegExp(`^${pattern.replace(/:(\w+)/g, "(?<$1>[^/]+)")}$`),
}));

function match(path) {
  for (const route of routes) {
    const m = path.match(route.regex);
    if (m) return { route, params: { ...m.groups } };
  }
  return { route: null, params: {} };
}

function navigate(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

function shell(content) {
  const user = session.user;
  const path = location.hash.slice(1) || "/";
  const links = (NAV[user.role] || []).map((item) => {
    const active = item.match ? item.match.test(path) : item.href === `#${path}`;
    return h("a", { class: "nav__link", href: item.href, "aria-current": active ? "page" : false }, item.label);
  });

  const logout = h("button", { class: "btn btn--ghost btn--icon", type: "button", title: "Выйти" }, icon("logout", 20),
    h("span", { class: "sr-only" }, "Выйти"));
  logout.addEventListener("click", () => {
    session.clear();
    resetNotifications();
    navigate("#/login");
  });

  return h("div", { class: "shell" },
    h("header", { class: "topbar" },
      h("a", { class: "wordmark", href: "#/" }, "Ложка"),
      h("nav", { class: "nav", "aria-label": "Основное меню" }, links),
      h("div", { class: "topbar__user" },
        notificationsBell(navigate),
        user.role === "customer" ? cartLink() : null,
        h("a", { class: "userlink", href: "#/profile", "aria-current": path === "/profile" ? "page" : false },
          icon("user", 18), h("span", { "data-user-name": "" }, user.full_name),
          h("span", { class: `chip chip--${user.role}` }, ROLE_LABELS[user.role])),
        logout)),
    h("main", { class: "shell__main", id: "main", tabindex: "-1" }, content));
}

function cartLink() {
  const link = h("a", { class: "cartlink", href: "#/cart" }, icon("bag", 20), h("span", { class: "sr-only" }, "Корзина"));
  const badge = h("span", { class: "cartlink__count" });
  const update = () => {
    const { count } = cart.summary();
    badge.textContent = count;
    badge.hidden = !count;
    link.setAttribute("aria-label", count ? `Корзина, блюд: ${count}` : "Корзина");
  };
  link.append(badge);
  update();
  window.addEventListener("cart:changed", update);
  return link;
}

function errorPage(err) {
  return h("div", { class: "page page--narrow" },
    h("div", { class: "empty" },
      h("h1", { class: "empty__title" }, err.status === 404 ? "Страница не найдена" : "Не удалось загрузить страницу"),
      h("p", {}, err.message),
      err.requestId ? h("p", { class: "muted" }, `Код запроса для поддержки: ${err.requestId}`) : null,
      h("a", { class: "btn btn--primary", href: "#/" }, "На главную")));
}

async function render() {
  const path = location.hash.slice(1) || "/";
  const { route, params } = match(path);
  const ctx = { navigate, params };

  if (!route) {
    root.replaceChildren(session.token ? shell(errorPage({ status: 404, message: "Такого раздела нет." })) : authView({ ...ctx }));
    return;
  }
  if (!route.public && (!session.token || !session.user)) {
    session.clear();
    return navigate("#/login");
  }
  if (route.public && session.token) return navigate("#/");
  if (route.roles && !route.roles.includes(session.user?.role)) return navigate("#/");

  if (route.public) {
    root.replaceChildren(route.view(ctx));
    return;
  }

  root.replaceChildren(shell(h("div", { class: "loading", "aria-busy": "true" }, "Загрузка…")));
  try {
    const content = await route.view(ctx);
    // пока страница загружалась, пользователь мог выйти или перейти в другой раздел
    if (!session.user || (location.hash.slice(1) || "/") !== path) return;
    root.replaceChildren(shell(content));
  } catch (err) {
    if (err.status === 401) return; // обработает событие auth:expired
    root.replaceChildren(shell(errorPage(err)));
  }
  window.scrollTo(0, 0);
  document.getElementById("main")?.focus?.({ preventScroll: true });
}

window.addEventListener("hashchange", render);
window.addEventListener("auth:expired", () => {
  toast("Сессия истекла, войдите снова", "error");
  navigate("#/login");
});

// При загрузке проверяем, что сохранённый токен ещё действителен
if (session.token) {
  api("/api/auth/me").then((u) => session.updateUser(u)).catch(() => {});
}
render();
