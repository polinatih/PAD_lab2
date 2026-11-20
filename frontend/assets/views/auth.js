import { api, session } from "../api.js";
import { h, icon, showFieldErrors, toast } from "../dom.js";

const ROLES = [
  { value: "customer", icon: "bowl", title: "Заказываю еду", text: "Выбираю блюда и слежу за доставкой" },
  { value: "restaurant", icon: "store", title: "У меня ресторан", text: "Веду меню и готовлю заказы" },
  { value: "courier", icon: "bike", title: "Я курьер", text: "Забираю заказы и доставляю их" },
];

// Образец заказа на приветственном экране: так выглядит отслеживание доставки в приложении.
function sampleTicket() {
  const steps = [
    ["Оплачен", "18:02", "done"],
    ["Ресторан готовит", "18:05", "done"],
    ["Курьер в пути", "ещё 12 мин", "current"],
    ["Доставлен", "", "next"],
  ];
  return h("figure", { class: "ticket", "aria-label": "Пример отслеживания заказа" },
    h("div", { class: "ticket__head" },
      h("span", { class: "ticket__place" }, "Пиццерия «Тесто»"),
      h("span", { class: "ticket__number" }, "№ 1042")),
    h("ul", { class: "ticket__items" },
      h("li", {}, h("span", {}, "Маргарита"), h("span", {}, "1 × 129 лей")),
      h("li", {}, h("span", {}, "Лимонад с мятой"), h("span", {}, "2 × 35 лей"))),
    h("ol", { class: "ticket__steps" },
      steps.map(([label, time, state]) =>
        h("li", { class: `step step--${state}` },
          h("span", { class: "step__dot" }),
          h("span", { class: "step__label" }, label),
          h("span", { class: "step__time" }, time)))),
  );
}

function field(label, input, hint) {
  return h("label", { class: "field" },
    h("span", { class: "field__label" }, label),
    input,
    hint ? h("span", { class: "field__hint" }, hint) : null);
}

function loginForm(onDone) {
  const form = h("form", { class: "form", novalidate: true },
    field("Email", h("input", { name: "email", type: "email", autocomplete: "email", required: true })),
    field("Пароль", h("input", { name: "password", type: "password", autocomplete: "current-password", required: true })),
    h("button", { class: "btn btn--primary btn--wide", type: "submit" }, "Войти"),
  );
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button");
    btn.disabled = true;
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: { email: form.email.value.trim(), password: form.password.value },
      });
      session.save(data.access_token, data.user);
      onDone(data.user);
    } catch (err) {
      showFieldErrors(form, err);
      toast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  });
  return form;
}

function registerForm(onDone) {
  const roleOptions = h("fieldset", { class: "roles" },
    h("legend", { class: "field__label" }, "Кто вы?"),
    ROLES.map((r, i) =>
      h("label", { class: "role" },
        h("input", { type: "radio", name: "role", value: r.value, checked: i === 0 }),
        h("span", { class: "role__card" },
          icon(r.icon, 26),
          h("span", { class: "role__title" }, r.title),
          h("span", { class: "role__text" }, r.text)))));

  const form = h("form", { class: "form", novalidate: true },
    roleOptions,
    field("Имя", h("input", { name: "full_name", autocomplete: "name", required: true })),
    h("div", { class: "form__row" },
      field("Email", h("input", { name: "email", type: "email", autocomplete: "email", required: true })),
      field("Телефон", h("input", { name: "phone", type: "tel", autocomplete: "tel", placeholder: "+373 69 000 000" }))),
    field("Пароль", h("input", { name: "password", type: "password", autocomplete: "new-password", required: true }),
      "Не меньше 8 символов"),
    h("button", { class: "btn btn--primary btn--wide", type: "submit" }, "Создать аккаунт"),
  );

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    const body = {
      full_name: form.full_name.value.trim(),
      email: form.email.value.trim(),
      phone: form.phone.value.trim() || null,
      password: form.password.value,
      role: form.role.value,
    };
    try {
      await api("/api/auth/register", { method: "POST", body });
      const data = await api("/api/auth/login", { method: "POST", body: { email: body.email, password: body.password } });
      session.save(data.access_token, data.user);
      toast("Аккаунт создан", "success");
      onDone(data.user);
    } catch (err) {
      showFieldErrors(form, err);
      toast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  });
  return form;
}

export function authView({ mode = "login", navigate }) {
  const onDone = () => navigate("#/");
  const isLogin = mode === "login";

  return h("main", { class: "auth" },
    h("section", { class: "auth__intro" },
      h("a", { class: "wordmark wordmark--large", href: "#/login" }, "Ложка"),
      h("p", { class: "auth__lead" }, "Еда из ресторанов города. Видно, кто готовит ваш заказ и где сейчас курьер."),
      sampleTicket()),
    h("section", { class: "auth__panel" },
      h("div", { class: "auth__box" },
        h("nav", { class: "tabs", "aria-label": "Вход или регистрация" },
          h("a", { class: `tabs__item ${isLogin ? "is-active" : ""}`, href: "#/login", "aria-current": isLogin ? "page" : false }, "Вход"),
          h("a", { class: `tabs__item ${!isLogin ? "is-active" : ""}`, href: "#/register", "aria-current": !isLogin ? "page" : false }, "Регистрация")),
        h("h1", { class: "auth__title" }, isLogin ? "С возвращением" : "Новый аккаунт"),
        isLogin ? loginForm(onDone) : registerForm(onDone))),
  );
}
