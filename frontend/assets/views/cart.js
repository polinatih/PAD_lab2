import { api, session } from "../api.js";
import { cart, plural } from "../cart.js";
import { cover, money } from "../cuisine.js";
import { h, showFieldErrors, toast } from "../dom.js";

const ADDRESS_KEY = "lozhka.address";

export function stepper(restaurant, item, onChange) {
  const box = h("div", { class: "stepper" });
  function draw() {
    const qty = cart.quantity(item.id);
    if (!qty) {
      const add = h("button", { type: "button", class: "btn btn--small btn--add" }, "Добавить");
      add.addEventListener("click", () => { if (cart.setQuantity(restaurant, item, 1)) { draw(); onChange?.(); } });
      box.replaceChildren(add);
      return;
    }
    const minus = h("button", { type: "button", class: "stepper__btn", "aria-label": `Убрать одну порцию: ${item.name}` }, "−");
    const plus = h("button", { type: "button", class: "stepper__btn", "aria-label": `Добавить ещё одну порцию: ${item.name}` }, "+");
    minus.addEventListener("click", () => { cart.setQuantity(restaurant, item, qty - 1); draw(); onChange?.(); });
    plus.addEventListener("click", () => { cart.setQuantity(restaurant, item, qty + 1); draw(); onChange?.(); });
    box.replaceChildren(minus, h("span", { class: "stepper__qty", "aria-live": "polite" }, qty), plus);
  }
  draw();
  return box;
}

// Плашка внизу страницы ресторана: сколько в корзине и переход к оформлению
export function cartBar(restaurantId) {
  const bar = h("div", { class: "cartbar", hidden: true });
  function draw() {
    const s = cart.summary();
    if (!s.count || s.state.restaurant?.id !== restaurantId) {
      bar.hidden = true;
      return;
    }
    bar.hidden = false;
    bar.replaceChildren(
      h("span", { class: "cartbar__info" }, `${s.count} ${plural(s.count, "блюдо", "блюда", "блюд")} на ${money(s.subtotal)}`),
      h("a", { class: "btn btn--accent", href: "#/cart" }, "Оформить заказ"));
  }
  draw();
  window.addEventListener("cart:changed", draw);
  return bar;
}

export async function cartView({ navigate }) {
  const page = h("div", { class: "page" });

  function render() {
    // при пересчёте корзины сохраняем то, что уже введено в форму
    const prev = page.querySelector("form");
    const typed = prev ? Object.fromEntries(["delivery_address", "phone", "comment"].map((n) => [n, prev[n].value])) : null;
    const s = cart.summary();
    if (!s.count) {
      page.replaceChildren(
        h("header", { class: "page__head" }, h("h1", { class: "page__title" }, "Корзина")),
        h("div", { class: "empty" },
          h("p", { class: "empty__title" }, "Корзина пустая"),
          h("p", { class: "muted" }, "Выберите ресторан и добавьте блюда из меню."),
          h("a", { class: "btn btn--primary", href: "#/catalog" }, "Выбрать ресторан")));
      return;
    }
    const r = s.state.restaurant;
    const below = r.min_order > 0 && s.subtotal < r.min_order;

    const lines = h("ul", { class: "cartlines" }, s.items.map((item) =>
      h("li", { class: "cartline" },
        h("span", { class: "cartline__name" }, item.name),
        stepper({ id: r.id, name: r.name, ...r }, item, render),
        h("span", { class: "cartline__sum" }, money(item.price * item.quantity)))));

    const form = h("form", { class: "form", novalidate: true },
      h("label", { class: "field" }, h("span", { class: "field__label" }, "Адрес доставки"),
        h("input", { name: "delivery_address", autocomplete: "street-address", required: true,
                     placeholder: "Улица, дом, квартира, подъезд", value: localStorage.getItem(ADDRESS_KEY) || "" })),
      h("label", { class: "field" }, h("span", { class: "field__label" }, "Телефон"),
        h("input", { name: "phone", type: "tel", autocomplete: "tel", value: session.user?.phone || "",
                     placeholder: "+373 69 000 000" }),
        h("span", { class: "field__hint" }, "Курьер позвонит, когда подъедет")),
      h("label", { class: "field" }, h("span", { class: "field__label" }, "Комментарий"),
        h("textarea", { name: "comment", rows: 2, placeholder: "Например, без лука или код домофона" })),
      below ? h("p", { class: "notice" }, `Минимальная сумма заказа в «${r.name}» — ${money(r.min_order)}. Добавьте ещё на ${money(r.min_order - s.subtotal)}.`) : null,
      h("button", { class: "btn btn--primary btn--wide", type: "submit", disabled: below }, `Оформить заказ на ${money(s.total)}`));

    if (typed) for (const [n, v] of Object.entries(typed)) form[n].value = v;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        const order = await api("/api/orders", {
          method: "POST",
          headers: { "Idempotency-Key": s.state.idempotencyKey },
          body: {
            restaurant_id: r.id,
            items: s.items.map((i) => ({ menu_item_id: i.id, quantity: i.quantity })),
            delivery_address: form.delivery_address.value.trim(),
            phone: form.phone.value.trim() || null,
            comment: form.comment.value.trim(),
          },
        });
        localStorage.setItem(ADDRESS_KEY, form.delivery_address.value.trim());
        cart.clear();
        toast(`Заказ № ${order.number} оформлен`, "success");
        navigate(`#/orders/${order.id}`);
      } catch (err) {
        showFieldErrors(form, err);
        const details = (err.details || []).map((d) => d.message).filter(Boolean);
        toast(details.length && err.code === "items_unavailable" ? `${err.message}: ${details.join("; ")}` : err.message, "error");
        btn.disabled = false;
      }
    });

    page.replaceChildren(
      h("header", { class: "page__head" }, h("h1", { class: "page__title" }, "Корзина")),
      h("div", { class: "split split--checkout" },
        h("section", { class: "panel" },
          h("div", { class: "cartrest" }, cover({ ...r, is_open: true }, { size: "mini" }),
            h("div", {}, h("a", { class: "ownlist__name", href: `#/restaurants/${r.id}` }, r.name),
              h("p", { class: "muted" }, `${s.count} ${plural(s.count, "блюдо", "блюда", "блюд")}`))),
          lines,
          h("dl", { class: "totals" },
            h("div", {}, h("dt", {}, "Блюда"), h("dd", {}, money(s.subtotal))),
            h("div", {}, h("dt", {}, "Доставка"), h("dd", {}, money(s.fee))),
            h("div", { class: "totals__sum" }, h("dt", {}, "Итого"), h("dd", {}, money(s.total))))),
        h("section", { class: "panel" }, h("h2", { class: "panel__title" }, "Куда привезти"), form)));
  }

  render();
  return page;
}
