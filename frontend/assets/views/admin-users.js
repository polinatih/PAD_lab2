import { api } from "../api.js";
import { formatDate, h, toast } from "../dom.js";
import { ROLE_LABELS } from "../roles.js";

export async function adminUsersView() {
  const users = await api("/api/auth/users");

  const rows = users.map((u) => {
    const select = h("select", { "aria-label": `Роль пользователя ${u.full_name}` },
      Object.entries(ROLE_LABELS).map(([value, label]) => h("option", { value, selected: value === u.role }, label)));
    select.addEventListener("change", async () => {
      try {
        await api(`/api/auth/users/${u.id}/role`, { method: "PATCH", body: { role: select.value } });
        toast(`${u.full_name}: роль изменена на «${ROLE_LABELS[select.value]}»`, "success");
      } catch (err) {
        select.value = u.role;
        toast(err.message, "error");
      }
    });
    return h("tr", {},
      h("td", {}, h("strong", {}, u.full_name), h("div", { class: "muted" }, u.email)),
      h("td", {}, u.phone || h("span", { class: "muted" }, "не указан")),
      h("td", {}, formatDate(u.created_at)),
      h("td", {}, select));
  });

  const counts = Object.keys(ROLE_LABELS).map((role) =>
    h("li", {}, h("span", { class: `chip chip--${role}` }, ROLE_LABELS[role]),
      h("b", {}, users.filter((u) => u.role === role).length)));

  return h("div", { class: "page" },
    h("header", { class: "page__head" },
      h("h1", { class: "page__title" }, "Пользователи"),
      h("ul", { class: "counts" }, counts)),
    h("div", { class: "panel panel--flush" },
      h("table", { class: "table" },
        h("thead", {}, h("tr", {}, h("th", {}, "Пользователь"), h("th", {}, "Телефон"), h("th", {}, "Регистрация"), h("th", {}, "Роль"))),
        h("tbody", {}, rows))));
}
