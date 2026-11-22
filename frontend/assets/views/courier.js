import { api } from "../api.js";
import { money } from "../cuisine.js";
import { h, toast } from "../dom.js";
import { plural } from "../cart.js";

function minutesSince(iso) {
  const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  return min < 1 ? "только что" : `ждёт ${min} мин`;
}

function phoneLink(phone) {
  return phone ? h("a", { class: "route__phone", href: `tel:${phone.replace(/[^\d+]/g, "")}` }, phone) : null;
}

// Маршрут: две точки — где забрать и куда отвезти
function route(d, { full = false } = {}) {
  return h("ol", { class: "route" },
    h("li", { class: `route__stop ${d.status === "picked_up" ? "route__stop--done" : ""}` },
      h("span", { class: "route__label" }, "Забрать"),
      h("span", { class: "route__place" }, d.restaurant_name),
      h("span", { class: "route__addr" }, d.restaurant_address)),
    h("li", { class: "route__stop" },
      h("span", { class: "route__label" }, "Отвезти"),
      full ? h("span", { class: "route__place" }, d.customer_name || "Клиент") : null,
      h("span", { class: "route__addr" }, d.delivery_address),
      full ? phoneLink(d.customer_phone) : null,
      full && d.comment ? h("span", { class: "route__comment" }, d.comment) : null));
}

export async function courierView() {
  const page = h("div", { class: "page" });
  const routeHash = location.hash;

  async function act(path, okMessage) {
    try {
      await api(path, { method: path.endsWith("/me") ? "PUT" : "POST" });
      if (okMessage) toast(okMessage, "success");
    } catch (err) {
      toast(err.message, "error");
    }
    await refresh();
  }

  async function refresh() {
    const [me, active, available] = await Promise.all([
      api("/api/deliveries/couriers/me"),
      api("/api/deliveries/mine?active=true"),
      api("/api/deliveries/available"),
    ]);
    const current = active[0];

    const toggle = h("input", { type: "checkbox", checked: me.is_online });
    toggle.addEventListener("change", async () => {
      try {
        await api("/api/deliveries/couriers/me", { method: "PUT", body: { is_online: toggle.checked } });
        toast(toggle.checked ? "Вы на линии" : "Вы ушли с линии", "success");
      } catch (err) {
        toast(err.message, "error");
      }
      await refresh();
    });

    const head = h("header", { class: "page__head" },
      h("div", {},
        h("h1", { class: "page__title" }, "Доставки"),
        h("p", { class: "page__sub" },
          `Сегодня ${me.delivered_today} ${plural(me.delivered_today, "доставка", "доставки", "доставок")}, заработано ${money(me.earned_today)}`)),
      h("label", { class: `switch switch--big ${me.is_online ? "is-on" : ""}` }, toggle, h("span", { class: "switch__track" }),
        me.is_online ? "На линии" : "Не на линии"));

    let currentBlock = null;
    if (current) {
      const action = current.status === "assigned"
        ? h("button", { type: "button", class: "btn btn--primary btn--wide" }, "Забрал заказ в ресторане")
        : h("button", { type: "button", class: "btn btn--accent btn--wide" }, "Доставил клиенту");
      action.addEventListener("click", () => current.status === "assigned"
        ? act(`/api/deliveries/${current.id}/pickup`, "Отлично, везите заказ клиенту")
        : act(`/api/deliveries/${current.id}/deliver`, `Заказ № ${current.order_number} доставлен, +${money(current.courier_fee)}`));
      currentBlock = h("section", { class: "trip" },
        h("div", { class: "trip__head" },
          h("span", { class: "trip__num" }, `Заказ № ${current.order_number}`),
          h("span", { class: "chip chip--status chip--in_delivery" }, current.status_label)),
        route(current, { full: true }),
        h("p", { class: "trip__fee" }, `За доставку ${money(current.courier_fee)}, сумма заказа ${money(current.order_total)} (уже оплачен)`),
        action);
    }

    const canTake = me.is_online && !current;
    const list = available.length
      ? h("div", { class: "jobs" }, available.map((d) => {
          const take = h("button", { type: "button", class: "btn btn--primary btn--small", disabled: !canTake }, "Взять заказ");
          take.addEventListener("click", () => act(`/api/deliveries/${d.id}/claim`, `Заказ № ${d.order_number} ваш. Езжайте в ресторан`));
          return h("article", { class: "job" },
            h("div", { class: "job__top" },
              h("span", { class: "job__fee" }, money(d.courier_fee)),
              h("span", { class: "muted" }, minutesSince(d.created_at))),
            route(d),
            take);
        }))
      : h("p", { class: "muted" }, "Сейчас свободных заказов нет. Список обновляется сам.");

    page.replaceChildren(...[
      head,
      currentBlock,
      h("section", { class: "osection" },
        h("h2", { class: "panel__title" }, "Ждут курьера"),
        !me.is_online ? h("p", { class: "notice" }, "Выйдите на линию, чтобы брать заказы.") : null,
        me.is_online && current && available.length ? h("p", { class: "muted" }, "Сначала доставьте текущий заказ.") : null,
        list),
    ].filter(Boolean));
  }

  await refresh();
  const timer = setInterval(() => {
    if (location.hash !== routeHash) return clearInterval(timer);
    refresh().catch(() => {});
  }, 5000);
  return page;
}

export async function courierHistoryView() {
  const rows = (await api("/api/deliveries/mine")).filter((d) => d.status === "delivered");
  const total = rows.reduce((s, d) => s + d.courier_fee, 0);
  return h("div", { class: "page page--narrow" },
    h("header", { class: "page__head" },
      h("div", {}, h("h1", { class: "page__title" }, "История"),
        h("p", { class: "page__sub" }, `${rows.length} ${plural(rows.length, "доставка", "доставки", "доставок")}, всего ${money(total)}`))),
    rows.length
      ? h("div", { class: "olist" }, rows.map((d) => h("div", { class: "orow" },
          h("div", { class: "orow__main" },
            h("span", { class: "orow__place" }, `${d.restaurant_name} → ${d.delivery_address}`),
            h("span", { class: "muted" }, `№ ${d.order_number}, ${new Date(d.delivered_at).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })}`)),
          h("span", {}),
          h("span", { class: "orow__total" }, `+${money(d.courier_fee)}`),
          h("span", { class: "chip chip--status chip--delivered" }, "Доставлен"))))
      : h("div", { class: "empty" }, h("p", { class: "empty__title" }, "Доставок пока не было"),
          h("p", { class: "muted" }, "Выйдите на линию и возьмите первый заказ.")));
}
