import { api } from "../api.js";
import { cover, money } from "../cuisine.js";
import { h, showFieldErrors, toast } from "../dom.js";

const SUGGESTED = ["Пицца", "Бургеры", "Суши", "Молдавская", "Грузинская", "Азиатская", "Выпечка", "Здоровая еда", "Десерты"];

function field(label, input, hint) {
  return h("label", { class: "field" }, h("span", { class: "field__label" }, label), input,
    hint ? h("span", { class: "field__hint" }, hint) : null);
}

function restaurantFields(r = {}) {
  return [
    field("Название", h("input", { name: "name", value: r.name || "", required: true })),
    h("div", { class: "form__row" },
      field("Кухня", h("input", { name: "cuisine", value: r.cuisine || "", list: "cuisines", required: true })),
      field("Телефон", h("input", { name: "phone", type: "tel", value: r.phone || "", placeholder: "+373 22 000 000" }))),
    field("Адрес", h("input", { name: "address", value: r.address || "", required: true })),
    field("Описание", h("textarea", { name: "description", rows: 3 }, r.description || "")),
    h("div", { class: "form__row form__row--3" },
      field("Доставка, лей", h("input", { name: "delivery_fee", type: "number", min: 0, step: "0.5", value: r.delivery_fee ?? 25 })),
      field("Мин. заказ, лей", h("input", { name: "min_order", type: "number", min: 0, step: "1", value: r.min_order ?? 0 })),
      field("Готовка, мин", h("input", { name: "prep_minutes", type: "number", min: 5, max: 180, value: r.prep_minutes ?? 25 }))),
    h("datalist", { id: "cuisines" }, SUGGESTED.map((c) => h("option", { value: c }))),
  ];
}

function readRestaurant(form) {
  return {
    name: form.name.value.trim(),
    cuisine: form.cuisine.value.trim(),
    phone: form.phone.value.trim() || null,
    address: form.address.value.trim(),
    description: form.description.value.trim(),
    delivery_fee: Number(form.delivery_fee.value),
    min_order: Number(form.min_order.value),
    prep_minutes: Number(form.prep_minutes.value),
  };
}

function openSwitch(r, onChange) {
  const input = h("input", { type: "checkbox", checked: r.is_open });
  input.addEventListener("change", async () => {
    try {
      const updated = await api(`/api/restaurants/${r.id}`, { method: "PATCH", body: { is_open: input.checked } });
      toast(updated.is_open ? `«${r.name}» принимает заказы` : `«${r.name}» закрыт для заказов`, "success");
      onChange?.(updated);
    } catch (err) {
      input.checked = !input.checked;
      toast(err.message, "error");
    }
  });
  return h("label", { class: "switch" }, input, h("span", { class: "switch__track" }), "Принимаем заказы");
}

// Список ресторанов владельца и форма открытия нового.
export async function myRestaurantsView({ navigate }) {
  const mine = await api("/api/restaurants/mine");

  const form = h("form", { class: "form", novalidate: true }, restaurantFields(),
    h("button", { class: "btn btn--primary", type: "submit" }, "Открыть ресторан"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/restaurants", { method: "POST", body: readRestaurant(form) });
      toast(`«${r.name}» создан. Теперь добавьте блюда в меню`, "success");
      navigate(`#/my/${r.id}`);
    } catch (err) {
      showFieldErrors(form, err);
      toast(err.message, "error");
    }
  });

  const list = mine.length
    ? h("ul", { class: "ownlist" }, mine.map((r) => h("li", { class: "ownlist__item" },
        cover(r, { size: "mini" }),
        h("div", { class: "ownlist__info" },
          h("a", { class: "ownlist__name", href: `#/my/${r.id}` }, r.name),
          h("p", { class: "muted" }, `${r.cuisine}, ${r.address}`)),
        openSwitch(r, () => {}),
        h("a", { class: "btn btn--ghost", href: `#/my/${r.id}` }, "Меню и настройки"))))
    : h("div", { class: "empty" },
        h("p", { class: "empty__title" }, "У вас пока нет ресторана"),
        h("p", { class: "muted" }, "Заполните форму ниже, и ресторан появится в каталоге."));

  return h("div", { class: "page" },
    h("header", { class: "page__head" }, h("h1", { class: "page__title" }, "Мои рестораны")),
    list,
    h("section", { class: "panel" },
      h("h2", { class: "panel__title" }, mine.length ? "Открыть ещё один ресторан" : "Открыть ресторан"),
      form));
}

// Управление рестораном: меню (добавить, цена, наличие, удалить) и настройки.
export async function manageRestaurantView({ params, navigate }) {
  let r = await api(`/api/restaurants/${params.id}`);
  const base = `/api/restaurants/${r.id}`;

  function dishRow(item) {
    const price = h("input", { type: "number", min: "0.5", step: "0.5", value: item.price, class: "dishedit__price",
                               "aria-label": `Цена: ${item.name}` });
    price.addEventListener("change", async () => {
      try {
        await api(`${base}/menu/${item.id}`, { method: "PATCH", body: { price: Number(price.value) } });
        toast(`Цена «${item.name}»: ${money(price.value)}`, "success");
      } catch (err) {
        price.value = item.price;
        toast(err.message, "error");
      }
    });
    const available = h("input", { type: "checkbox", checked: item.is_available });
    available.addEventListener("change", async () => {
      try {
        await api(`${base}/menu/${item.id}`, { method: "PATCH", body: { is_available: available.checked } });
        row.classList.toggle("dish--off", !available.checked);
      } catch (err) {
        available.checked = !available.checked;
        toast(err.message, "error");
      }
    });
    const remove = h("button", { type: "button", class: "btn btn--ghost btn--small" }, "Удалить");
    remove.addEventListener("click", async () => {
      if (!confirm(`Удалить «${item.name}» из меню?`)) return;
      try {
        await api(`${base}/menu/${item.id}`, { method: "DELETE" });
        row.remove();
        toast(`«${item.name}» удалено из меню`, "success");
      } catch (err) {
        toast(err.message, "error");
      }
    });
    const row = h("li", { class: `dishedit ${item.is_available ? "" : "dish--off"}` },
      h("div", {}, h("p", { class: "dish__name" }, item.name),
        h("p", { class: "dish__desc" }, [item.category, item.description].filter(Boolean).join(". "))),
      h("label", { class: "dishedit__pricebox" }, price, "лей"),
      h("label", { class: "switch switch--small" }, available, h("span", { class: "switch__track" }), "В наличии"),
      remove);
    return row;
  }

  const menuList = h("ul", { class: "dishedits" }, r.menu.map(dishRow));
  const emptyHint = r.menu.length ? null : h("p", { class: "muted" }, "Добавьте первое блюдо, и оно сразу появится в каталоге.");

  const addForm = h("form", { class: "form", novalidate: true },
    h("div", { class: "form__row" },
      field("Блюдо", h("input", { name: "name", required: true, placeholder: "Плачинта с брынзой" })),
      field("Категория", h("input", { name: "category", list: "categories", placeholder: "Выпечка" }))),
    h("div", { class: "form__row" },
      field("Описание", h("input", { name: "description", placeholder: "Состав или вес порции" })),
      field("Цена, лей", h("input", { name: "price", type: "number", min: "0.5", step: "0.5", required: true }))),
    h("datalist", { id: "categories" }, [...new Set(r.menu.map((m) => m.category))].map((c) => h("option", { value: c }))),
    h("button", { class: "btn btn--primary", type: "submit" }, "Добавить в меню"));
  addForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const item = await api(`${base}/menu`, { method: "POST", body: {
        name: addForm.name.value.trim(),
        category: addForm.category.value.trim() || "Основное",
        description: addForm.description.value.trim(),
        price: Number(addForm.price.value),
      } });
      menuList.append(dishRow(item));
      emptyHint?.remove();
      addForm.reset();
      showFieldErrors(addForm, null);
      addForm.name.focus();
      toast(`«${item.name}» добавлено в меню`, "success");
    } catch (err) {
      showFieldErrors(addForm, err);
      toast(err.message, "error");
    }
  });

  const settings = h("form", { class: "form", novalidate: true }, restaurantFields(r),
    h("button", { class: "btn btn--primary", type: "submit" }, "Сохранить настройки"));
  settings.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      r = { ...r, ...(await api(base, { method: "PATCH", body: readRestaurant(settings) })) };
      showFieldErrors(settings, null);
      toast("Настройки сохранены", "success");
    } catch (err) {
      showFieldErrors(settings, err);
      toast(err.message, "error");
    }
  });

  return h("div", { class: "page" },
    h("a", { class: "backlink", href: "#/my" }, "Мои рестораны"),
    h("header", { class: "page__head" },
      h("div", {}, h("h1", { class: "page__title" }, r.name),
        h("p", { class: "page__sub" }, h("a", { href: `#/restaurants/${r.id}` }, "Как ресторан видят клиенты"))),
      openSwitch(r)),
    h("div", { class: "split" },
      h("section", { class: "panel" },
        h("h2", { class: "panel__title" }, "Меню"),
        addForm,
        emptyHint,
        menuList),
      h("section", { class: "panel" }, h("h2", { class: "panel__title" }, "Настройки ресторана"), settings)));
}
