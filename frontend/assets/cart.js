// Корзина хранится в браузере (localStorage), отдельно для каждого пользователя.
// В корзине блюда только одного ресторана — как в любом сервисе доставки.
import { session } from "./api.js";

const key = () => `lozhka.cart.${session.user?.id || "guest"}`;

function empty() {
  return { restaurant: null, items: {}, idempotencyKey: crypto.randomUUID() };
}

export const cart = {
  get() {
    try {
      return JSON.parse(localStorage.getItem(key())) || empty();
    } catch {
      return empty();
    }
  },
  save(state) {
    localStorage.setItem(key(), JSON.stringify(state));
    window.dispatchEvent(new CustomEvent("cart:changed"));
  },
  clear() {
    localStorage.removeItem(key());
    window.dispatchEvent(new CustomEvent("cart:changed"));
  },
  // Возвращает false, если пользователь отказался заменить корзину другого ресторана
  setQuantity(restaurant, item, quantity) {
    let state = this.get();
    if (state.restaurant && state.restaurant.id !== restaurant.id && Object.keys(state.items).length) {
      if (!confirm(`В корзине блюда из «${state.restaurant.name}». Очистить её и добавить из «${restaurant.name}»?`)) {
        return false;
      }
      state = empty();
    }
    state.restaurant = {
      id: restaurant.id, name: restaurant.name, cuisine: restaurant.cuisine,
      delivery_fee: restaurant.delivery_fee, min_order: restaurant.min_order,
    };
    if (quantity <= 0) delete state.items[item.id];
    else state.items[item.id] = { id: item.id, name: item.name, price: item.price, quantity: Math.min(quantity, 50) };
    if (!Object.keys(state.items).length) state.restaurant = null;
    this.save(state);
    return true;
  },
  quantity(itemId) {
    return this.get().items[itemId]?.quantity || 0;
  },
  summary() {
    const state = this.get();
    const items = Object.values(state.items);
    const count = items.reduce((n, i) => n + i.quantity, 0);
    const subtotal = items.reduce((s, i) => s + i.price * i.quantity, 0);
    const fee = state.restaurant?.delivery_fee || 0;
    return { state, items, count, subtotal, fee, total: subtotal + (count ? fee : 0) };
  },
};

export function plural(n, one, few, many) {
  const mod10 = n % 10, mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
