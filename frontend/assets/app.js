// Точка входа веб-интерфейса: маршрутизация по hash (#/...), оболочка приложения, проверка входа.
import { api, session } from "./api.js";
import { h, icon, toast } from "./dom.js";
import { NAV, ROLE_LABELS } from "./roles.js";
import { adminUsersView } from "./views/admin-users.js";
import { authView } from "./views/auth.js";
import { homeView } from "./views/home.js";
import { profileView } from "./views/profile.js";

const root = document.getElementById("app");

// path -> { view, roles?, public? }
const routes = {
  "/login": { view: (ctx) => authView({ ...ctx, mode: "login" }), public: true },
  "/register": { view: (ctx) => authView({ ...ctx, mode: "register" }), public: true },
  "/": { view: homeView },
  "/profile": { view: profileView },
  "/admin/users": { view: adminUsersView, roles: ["admin"] },
};

function navigate(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

function shell(content) {
  const user = session.user;
  const path = location.hash.slice(1) || "/";
  const links = (NAV[user.role] || []).map((item) =>
    h("a", { class: "nav__link", href: item.href, "aria-current": item.href === `#${path}` ? "page" : false }, item.label));

  const logout = h("button", { class: "btn btn--ghost btn--icon", type: "button", title: "Выйти" }, icon("logout", 20),
    h("span", { class: "sr-only" }, "Выйти"));
  logout.addEventListener("click", () => {
    session.clear();
    navigate("#/login");
  });

  return h("div", { class: "shell" },
    h("header", { class: "topbar" },
      h("a", { class: "wordmark", href: "#/" }, "Ложка"),
      h("nav", { class: "nav", "aria-label": "Основное меню" }, links),
      h("div", { class: "topbar__user" },
        h("a", { class: "userlink", href: "#/profile", "aria-current": path === "/profile" ? "page" : false },
          icon("user", 18), h("span", { "data-user-name": "" }, user.full_name),
          h("span", { class: `chip chip--${user.role}` }, ROLE_LABELS[user.role])),
        logout)),
    h("main", { class: "shell__main", id: "main", tabindex: "-1" }, content));
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
  const route = routes[path];
  const ctx = { navigate };

  if (!route) {
    root.replaceChildren(session.token ? shell(errorPage({ status: 404, message: "Такого раздела нет." })) : authView({ ...ctx }));
    return;
  }
  if (!route.public && !session.token) return navigate("#/login");
  if (route.public && session.token) return navigate("#/");
  if (route.roles && !route.roles.includes(session.user?.role)) return navigate("#/");

  if (route.public) {
    root.replaceChildren(route.view(ctx));
    return;
  }

  root.replaceChildren(shell(h("div", { class: "loading", "aria-busy": "true" }, "Загрузка…")));
  try {
    const content = await route.view(ctx);
    root.replaceChildren(shell(content));
  } catch (err) {
    if (err.status === 401) return; // обработает событие auth:expired
    root.replaceChildren(shell(errorPage(err)));
  }
  document.getElementById("main")?.focus?.();
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
