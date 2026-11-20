import { api, session } from "../api.js";
import { formatDate, h, showFieldErrors, toast } from "../dom.js";
import { ROLE_LABELS } from "../roles.js";

export async function profileView() {
  const user = await api("/api/auth/me");
  session.updateUser(user);

  const form = h("form", { class: "form", novalidate: true },
    h("label", { class: "field" },
      h("span", { class: "field__label" }, "Имя"),
      h("input", { name: "full_name", value: user.full_name, autocomplete: "name" })),
    h("label", { class: "field" },
      h("span", { class: "field__label" }, "Телефон"),
      h("input", { name: "phone", type: "tel", value: user.phone || "", placeholder: "+373 69 000 000" }),
      h("span", { class: "field__hint" }, "Курьер позвонит по этому номеру")),
    h("button", { class: "btn btn--primary", type: "submit" }, "Сохранить"));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const updated = await api("/api/auth/me", {
        method: "PATCH",
        body: { full_name: form.full_name.value.trim(), phone: form.phone.value.trim() || null },
      });
      session.updateUser(updated);
      showFieldErrors(form, null);
      toast("Сохранено", "success");
      document.querySelector("[data-user-name]")?.replaceChildren(updated.full_name);
    } catch (err) {
      showFieldErrors(form, err);
      toast(err.message, "error");
    }
  });

  return h("div", { class: "page page--narrow" },
    h("header", { class: "page__head" },
      h("h1", { class: "page__title" }, "Профиль"),
      h("p", { class: "page__sub" }, `${ROLE_LABELS[user.role]}, с нами с ${formatDate(user.created_at)}`)),
    h("div", { class: "panel" },
      h("dl", { class: "facts" },
        h("div", {}, h("dt", {}, "Email"), h("dd", {}, user.email)),
        h("div", {}, h("dt", {}, "Роль"), h("dd", {}, h("span", { class: `chip chip--${user.role}` }, ROLE_LABELS[user.role])))),
      form));
}
