import { h } from "./dom.js";

// Обложки ресторанов без фотографий: у каждой кухни свой цвет, название ресторана набрано крупным шрифтом.
const PALETTE = {
  "Пицца": ["#e4572e", "#fff3e6"],
  "Бургеры": ["#3b2a20", "#f4b841"],
  "Суши": ["#1e3a5f", "#f7d9d9"],
  "Молдавская": ["#f4b841", "#2b2112"],
  "Грузинская": ["#7a2e3b", "#fce7c8"],
  "Азиатская": ["#2f5d50", "#f2e8cf"],
  "Выпечка": ["#e9c46a", "#3d2c0e"],
  "Здоровая еда": ["#8cb369", "#17301c"],
  "Десерты": ["#f2b5d4", "#4a1832"],
};
const FALLBACK = ["#2c6b4c", "#f4b841"];

export function cuisineColors(cuisine) {
  return PALETTE[cuisine] || FALLBACK;
}

export function cover(restaurant, { size = "card" } = {}) {
  const [bg, fg] = cuisineColors(restaurant.cuisine);
  return h("div", { class: `cover cover--${size} ${restaurant.is_open ? "" : "cover--closed"}`,
                    style: `--cover-bg:${bg};--cover-fg:${fg}` },
    h("span", { class: "cover__name" }, restaurant.name),
    h("span", { class: "cover__cuisine" }, restaurant.cuisine),
    restaurant.is_open ? null : h("span", { class: "cover__closed" }, "Закрыт"));
}

export function money(value) {
  const n = Number(value);
  return `${n.toLocaleString("ru-RU", { minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2 })} лей`;
}

export function restaurantFacts(r) {
  return [
    `${r.prep_minutes}–${r.prep_minutes + 15} мин`,
    r.delivery_fee > 0 ? `доставка ${money(r.delivery_fee)}` : "бесплатная доставка",
    r.min_order > 0 ? `заказ от ${money(r.min_order)}` : null,
    r.rating_count > 0 ? `★ ${r.rating_avg.toFixed(1)} (${r.rating_count})` : null,
  ].filter(Boolean);
}
