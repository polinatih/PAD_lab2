import { api } from "../api.js";
import { money } from "../cuisine.js";
import { h, toast } from "../dom.js";

// Доска заказов ресторана: колонки по статусам, действия на карточках, автообновление.
const COLUMNS = [
  { title: "Новые", statuses: ["paid"], empty: "Новых заказов нет" },
  { title: "Готовятся", statuses: ["cooking"], empty: "Сейчас ничего не готовится" },
  { title: "Ждут курьера", statuses: ["ready", "courier_assigned"], empty: "Все готовые заказы забрали" },
  { title: "В пути", statuses: ["in_delivery"], empty: "Нет заказов в пути" },
];

function minutesSince(iso) {
  const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  return min < 1 ? "только что" : `${min} мин назад`;
}

export async function kitchenView() {
  const board = h("div", { class: "board" });
  const pendingNote = h("p", { class: "page__sub" });
  const route = location.hash;
  let known = null;

  async function act(order, action, body) {
    try {
      await api(`/api/orders/${order.id}/${action}`, { method: "POST", body });
      await refresh();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function card(o) {
    const paidAt = o.history.find((x) => x.status === "paid")?.at || o.created_at;
    const actions = [];
    if (o.status === "paid") {
      const accept = h("button", { type: "button", class: "btn btn--primary btn--small" }, "Принять");
      accept.addEventListener("click", () => act(o, "accept"));
      const reject = h("button", { type: "button", class: "btn btn--ghost btn--small" }, "Отказаться");
      reject.addEventListener("click", () => {
        const reason = prompt("Почему отказываетесь? Клиент увидит причину, деньги ему вернутся.", "Блюдо закончилось");
        if (reason !== null) act(o, "cancel", { reason });
      });
      actions.push(accept, reject);
    } else if (o.status === "cooking") {
      const ready = h("button", { type: "button", class: "btn btn--accent btn--small" }, "Готово, нужен курьер");
      ready.addEventListener("click", () => act(o, "ready"));
      actions.push(ready);
    }
    return h("article", { class: `kcard ${o.status === "paid" ? "kcard--new" : ""}` },
      h("header", { class: "kcard__head" },
        h("span", { class: "kcard__num" }, `№ ${o.number}`),
        h("span", { class: "muted" }, minutesSince(paidAt))),
      h("ul", { class: "kcard__items" }, o.items.map((i) =>
        h("li", {}, h("b", {}, `${i.quantity} ×`), ` ${i.name}`))),
      o.comment ? h("p", { class: "kcard__comment" }, o.comment) : null,
      h("p", { class: "kcard__meta muted" }, `${o.restaurant_name}, ${money(o.total)}`),
      o.status === "courier_assigned" ? h("p", { class: "kcard__meta" }, "Курьер едет за заказом") : null,
      actions.length ? h("div", { class: "kcard__actions" }, actions) : null);
  }

  async function refresh() {
    const orders = await api("/api/orders?active=true");
    const visible = orders.filter((o) => o.status !== "pending_payment");
    const waiting = orders.length - visible.length;
    pendingNote.textContent = waiting ? `Ещё ${waiting} ждут оплаты клиентом` : "";

    const fresh = visible.filter((o) => o.status === "paid").map((o) => o.id);
    if (known && fresh.some((id) => !known.has(id))) toast("Новый заказ!", "success");
    known = new Set(fresh);

    board.replaceChildren(...COLUMNS.map((col) => {
      const list = visible.filter((o) => col.statuses.includes(o.status));
      return h("section", { class: "board__col" },
        h("h2", { class: "board__title" }, col.title, h("span", { class: "board__count" }, list.length)),
        list.length ? list.map(card) : h("p", { class: "board__empty" }, col.empty));
    }));
  }

  await refresh();
  const timer = setInterval(() => {
    if (location.hash !== route) return clearInterval(timer);
    refresh().catch(() => {});
  }, 5000);

  return h("div", { class: "page page--wide" },
    h("header", { class: "page__head" },
      h("div", {}, h("h1", { class: "page__title" }, "Заказы"), pendingNote)),
    board);
}
