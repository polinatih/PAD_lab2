import { api, session } from "../api.js";
import { plural } from "../cart.js";
import { money } from "../cuisine.js";
import { h, toast } from "../dom.js";
import { paymentPanel } from "./payment.js";
import { orderReviewBlock } from "./reviews.js";

const FINAL = new Set(["delivered", "cancelled"]);
const CUSTOMER_CANCELLABLE = new Set(["pending_payment", "paid"]);

// Порядок статусов: по нему считаем, какие шаги отслеживания уже пройдены
const ORDER = ["pending_payment", "paid", "cooking", "ready", "courier_assigned", "in_delivery", "delivered"];
const rank = (status) => ORDER.indexOf(status);

export function statusChip(order) {
  return h("span", { class: `chip chip--status chip--${order.status}` }, order.status_label);
}

function time(iso) {
  return new Date(iso).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function when(iso) {
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? `сегодня в ${time(iso)}` : d.toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
}

// Шаги отслеживания. done — шаг пройден, current — что происходит сейчас.
function trackingSteps(order) {
  const at = (status) => order.history.find((h) => h.status === status)?.at;
  const r = rank(order.status);
  const steps = [
    { label: "Заказ оформлен", time: order.created_at, done: true },
    { label: "Оплачен", time: at("paid"), done: r >= rank("paid"), wait: "ждём оплату" },
    { label: "Ресторан готовит", time: at("cooking"), done: r >= rank("ready"),
      wait: r === rank("cooking") ? `обычно ${order.prep_minutes}–${order.prep_minutes + 15} мин` : "ждём ресторан" },
    { label: "Курьер в пути", time: at("in_delivery"), done: r >= rank("delivered"),
      wait: { ready: "ищем курьера", courier_assigned: "курьер едет в ресторан", in_delivery: "курьер везёт заказ" }[order.status] },
    { label: "Доставлен", time: at("delivered"), done: order.status === "delivered" },
  ];
  const currentIndex = order.status === "cancelled" ? -1 : steps.findIndex((s) => !s.done);
  return steps.map((s, i) => ({ ...s, state: s.done ? "done" : i === currentIndex ? "current" : "next" }));
}

function ticket(order) {
  const steps = trackingSteps(order);
  const doneCount = steps.filter((s) => s.state === "done").length;
  const progress = order.status === "cancelled" ? 0 : Math.min(100, ((doneCount - 0.5) / (steps.length - 1)) * 100);

  return h("article", { class: "ticket ticket--live", "aria-label": `Заказ № ${order.number}` },
    h("div", { class: "ticket__head" },
      h("span", { class: "ticket__place" }, order.restaurant_name),
      h("span", { class: "ticket__number" }, `№ ${order.number}`)),
    h("ul", { class: "ticket__items" }, order.items.map((i) =>
      h("li", {}, h("span", {}, i.name), h("span", {}, `${i.quantity} × ${money(i.unit_price)}`)))),
    h("dl", { class: "ticket__totals" },
      h("div", {}, h("dt", {}, "Доставка"), h("dd", {}, money(order.delivery_fee))),
      h("div", { class: "ticket__total" }, h("dt", {}, "Итого"), h("dd", {}, money(order.total)))),
    order.status === "cancelled"
      ? h("div", { class: "ticket__cancelled" },
          h("p", { class: "ticket__cancelled-title" }, "Заказ отменён"),
          h("p", {}, order.cancel_reason || ""))
      : h("ol", { class: "ticket__steps", style: `--progress:${progress}%` }, steps.map((s) =>
          h("li", { class: `step step--${s.state}` },
            h("span", { class: "step__dot" }),
            h("span", { class: "step__label" }, s.label),
            h("span", { class: "step__time" }, s.time && s.state === "done" ? time(s.time) : s.state === "current" ? s.wait || "" : "")))));
}

export async function ordersView() {
  const orders = await api("/api/orders");
  const active = orders.filter((o) => !FINAL.has(o.status));
  const past = orders.filter((o) => FINAL.has(o.status));

  const row = (o) => {
    const count = o.items.reduce((n, i) => n + i.quantity, 0);
    return h("a", { class: "orow", href: `#/orders/${o.id}` },
      h("div", { class: "orow__main" },
        h("span", { class: "orow__place" }, o.restaurant_name),
        h("span", { class: "muted" }, `№ ${o.number}, ${when(o.created_at)}`)),
      h("span", { class: "orow__items muted" }, `${count} ${plural(count, "блюдо", "блюда", "блюд")}`),
      h("span", { class: "orow__total" }, money(o.total)),
      statusChip(o));
  };

  if (!orders.length) {
    return h("div", { class: "page page--narrow" },
      h("header", { class: "page__head" }, h("h1", { class: "page__title" }, "Мои заказы")),
      h("div", { class: "empty" },
        h("p", { class: "empty__title" }, "Заказов пока нет"),
        h("p", { class: "muted" }, "Выберите ресторан, соберите корзину, и заказ появится здесь."),
        h("a", { class: "btn btn--primary", href: "#/catalog" }, "Выбрать ресторан")));
  }

  return h("div", { class: "page page--narrow" },
    h("header", { class: "page__head" }, h("h1", { class: "page__title" }, "Мои заказы")),
    active.length ? h("section", { class: "osection" }, h("h2", { class: "panel__title" }, "Сейчас"), h("div", { class: "olist" }, active.map(row))) : null,
    past.length ? h("section", { class: "osection" }, h("h2", { class: "panel__title" }, "Раньше"), h("div", { class: "olist" }, past.map(row))) : null);
}

export async function orderView({ params }) {
  let order = await api(`/api/orders/${params.id}`);
  const route = location.hash;
  const holder = h("div", { class: "orderpage" });
  let payPanel = null;
  let reviewBlock = null;
  const reviewSlot = h("div", { class: "reviewslot" });

  async function reload() {
    const fresh = await api(`/api/orders/${order.id}`);
    const changed = fresh.status !== order.status;
    order = fresh;
    if (changed) draw();
    return changed;
  }

  // После оплаты статус меняется асинхронно (payment → RabbitMQ → order), проверяем чаще обычного
  async function afterPayment() {
    for (let i = 0; i < 10; i++) {
      await new Promise((r) => setTimeout(r, 700));
      if (await reload()) return;
    }
  }

  function draw() {
    const isCustomer = order.customer_id === session.user?.id;
    const cancel = isCustomer && CUSTOMER_CANCELLABLE.has(order.status)
      ? h("button", { type: "button", class: "btn btn--ghost" }, "Отменить заказ") : null;
    cancel?.addEventListener("click", async () => {
      const reason = prompt("Почему отменяете заказ? (необязательно)", "");
      if (reason === null) return;
      try {
        order = await api(`/api/orders/${order.id}/cancel`, { method: "POST", body: { reason } });
        toast("Заказ отменён", "success");
        draw();
      } catch (err) {
        toast(err.message, "error");
      }
    });

    if (isCustomer && order.status === "pending_payment") payPanel ||= paymentPanel(order, afterPayment);
    else payPanel = null;
    if (isCustomer && order.status === "delivered" && !reviewBlock) {
      // событие order.delivered доходит до review-service асинхронно — дадим ему секунду
      reviewBlock = setTimeout(async () => {
        const block = await orderReviewBlock(order);
        if (block) reviewSlot.replaceChildren(block);
      }, 800);
    }
    const paidNote = order.history.find((x) => x.status === "paid")?.note;

    holder.replaceChildren(
      ticket(order),
      h("aside", { class: "orderinfo" },
        h("div", { class: "orderinfo__status" }, statusChip(order),
          FINAL.has(order.status) ? null : h("span", { class: "muted" }, "Статус обновляется автоматически")),
        h("dl", { class: "facts facts--stack" },
          h("div", {}, h("dt", {}, "Куда"), h("dd", {}, order.delivery_address)),
          h("div", {}, h("dt", {}, "Откуда"), h("dd", {}, `${order.restaurant_name}, ${order.restaurant_address}`)),
          h("div", {}, h("dt", {}, "Телефон"), h("dd", {}, order.customer_phone || "не указан")),
          order.comment ? h("div", {}, h("dt", {}, "Комментарий"), h("dd", {}, order.comment)) : null,
          paidNote ? h("div", {}, h("dt", {}, "Оплата"), h("dd", {}, paidNote.replace("Оплачено: ", ""))) : null,
          order.courier_name ? h("div", {}, h("dt", {}, "Курьер"), h("dd", {}, order.courier_name,
            order.courier_phone && !FINAL.has(order.status)
              ? h("a", { class: "route__phone", href: `tel:${order.courier_phone.replace(/[^\d+]/g, "")}` }, order.courier_phone)
              : null)) : null,
          h("div", {}, h("dt", {}, "Оформлен"), h("dd", {}, when(order.created_at)))),
        payPanel,
        reviewSlot,
        cancel));
  }

  // Пока заказ не завершён, раз в 4 секунды спрашиваем свежий статус
  const timer = setInterval(async () => {
    if (location.hash !== route || FINAL.has(order.status)) return clearInterval(timer);
    try {
      if (await reload()) toast(`Заказ № ${order.number}: ${order.status_label.toLowerCase()}`, "info");
    } catch { /* сеть моргнула — попробуем в следующий раз */ }
  }, 4000);

  draw();
  return h("div", { class: "page" },
    h("a", { class: "backlink", href: "#/orders" }, "Мои заказы"),
    h("header", { class: "page__head" }, h("h1", { class: "page__title" }, `Заказ № ${order.number}`)),
    holder);
}
