import { api } from "../api.js";
import { cover, money, restaurantFacts } from "../cuisine.js";
import { h } from "../dom.js";

function restaurantCard(r) {
  return h("a", { class: `rcard ${r.is_open ? "" : "rcard--closed"}`, href: `#/restaurants/${r.id}` },
    cover(r),
    h("div", { class: "rcard__body" },
      h("p", { class: "rcard__desc" }, r.description || r.address),
      h("p", { class: "rcard__facts" }, restaurantFacts(r).join(", "))));
}

// Каталог ресторанов: поиск, фильтр по кухне, только открытые.
export async function catalogView() {
  const state = { q: "", cuisine: "", openOnly: false };
  const [restaurants, cuisines] = await Promise.all([api("/api/restaurants"), api("/api/restaurants/cuisines")]);

  const grid = h("div", { class: "rgrid" });
  const counter = h("p", { class: "page__sub" });

  async function reload() {
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.cuisine) params.set("cuisine", state.cuisine);
    if (state.openOnly) params.set("open_only", "true");
    const list = await api(`/api/restaurants?${params}`);
    draw(list);
  }

  function draw(list) {
    counter.textContent = list.length
      ? `Открыто сейчас: ${list.filter((r) => r.is_open).length} из ${list.length}`
      : "";
    grid.replaceChildren(...(list.length
      ? list.map(restaurantCard)
      : [h("div", { class: "empty empty--wide" },
          h("p", { class: "empty__title" }, "Ничего не нашлось"),
          h("p", { class: "muted" }, "Попробуйте другое название или сбросьте фильтр по кухне."))]));
  }

  let timer;
  const search = h("input", { type: "search", placeholder: "Ресторан или блюдо", "aria-label": "Поиск ресторанов" });
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.q = search.value.trim(); reload(); }, 250);
  });

  const filterButtons = [{ cuisine: "", restaurants: null }, ...cuisines.present].map((c) => {
    const btn = h("button", { type: "button", class: "filter", "aria-pressed": c.cuisine === "" ? "true" : "false" },
      c.cuisine || "Все кухни");
    btn.addEventListener("click", () => {
      state.cuisine = c.cuisine;
      filterButtons.forEach((b) => b.setAttribute("aria-pressed", b === btn ? "true" : "false"));
      reload();
    });
    return btn;
  });

  const openToggle = h("label", { class: "switch" },
    h("input", { type: "checkbox" }), h("span", { class: "switch__track" }), "Только открытые");
  openToggle.querySelector("input").addEventListener("change", (e) => { state.openOnly = e.target.checked; reload(); });

  draw(restaurants);
  return h("div", { class: "page" },
    h("header", { class: "page__head" },
      h("div", {}, h("h1", { class: "page__title" }, "Рестораны"), counter),
      h("div", { class: "searchbox" }, search)),
    h("div", { class: "filters", role: "group", "aria-label": "Фильтр по кухне" }, filterButtons, openToggle),
    grid);
}

// Страница ресторана с меню, сгруппированным по категориям.
export async function restaurantView({ params }) {
  const r = await api(`/api/restaurants/${params.id}`);
  const groups = new Map();
  for (const item of r.menu) {
    if (!groups.has(item.category)) groups.set(item.category, []);
    groups.get(item.category).push(item);
  }

  const sections = [...groups.entries()].map(([category, items], i) =>
    h("section", { class: "menu__group", id: `cat-${i}` },
      h("h2", { class: "menu__title" }, category),
      h("ul", { class: "menu__list" }, items.map((item) =>
        h("li", { class: `dish ${item.is_available ? "" : "dish--off"}` },
          h("div", {},
            h("p", { class: "dish__name" }, item.name),
            item.description ? h("p", { class: "dish__desc" }, item.description) : null),
          h("div", { class: "dish__side" },
            h("span", { class: "dish__price" }, money(item.price)),
            item.is_available ? null : h("span", { class: "muted" }, "нет в наличии")))))));

  return h("div", { class: "page" },
    h("a", { class: "backlink", href: "#/catalog" }, "Все рестораны"),
    h("section", { class: "rhero" },
      cover(r, { size: "hero" }),
      h("div", { class: "rhero__info" },
        h("p", { class: "rhero__desc" }, r.description),
        h("dl", { class: "facts facts--inline" },
          h("div", {}, h("dt", {}, "Адрес"), h("dd", {}, r.address)),
          h("div", {}, h("dt", {}, "Приготовление"), h("dd", {}, `${r.prep_minutes}–${r.prep_minutes + 15} мин`)),
          h("div", {}, h("dt", {}, "Доставка"), h("dd", {}, money(r.delivery_fee))),
          h("div", {}, h("dt", {}, "Минимальный заказ"), h("dd", {}, money(r.min_order)))),
        r.is_open ? null : h("p", { class: "notice" }, "Ресторан сейчас закрыт. Меню можно посмотреть, но заказ оформить не получится."))),
    groups.size > 1
      ? h("nav", { class: "menu__nav", "aria-label": "Категории меню" },
          [...groups.keys()].map((c, i) => h("a", { href: `#/restaurants/${r.id}`, "data-target": `cat-${i}`,
            onclick: (e) => { e.preventDefault(); document.getElementById(`cat-${i}`).scrollIntoView({ behavior: "smooth" }); } }, c)))
      : null,
    r.menu.length
      ? h("div", { class: "menu" }, sections)
      : h("div", { class: "empty" }, h("p", { class: "empty__title" }, "Меню пока пустое")));
}
