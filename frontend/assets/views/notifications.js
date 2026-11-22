import { api, session } from "../api.js";
import { h, icon } from "../dom.js";

// Колокольчик в шапке. Счётчик непрочитанных опрашивается раз в 10 секунд одним общим таймером,
// а все колокольчики на странице получают его через событие notif:count.
let unread = 0;
let poller = null;

async function pollCount() {
  if (!session.token) return;
  try {
    const { unread: n } = await api("/api/notifications/unread-count");
    if (n !== unread) {
      unread = n;
      window.dispatchEvent(new CustomEvent("notif:count", { detail: n }));
    }
  } catch { /* сервис уведомлений недоступен — интерфейс работает и без него */ }
}

function startPolling() {
  if (poller) return;
  pollCount();
  poller = setInterval(pollCount, 10000);
}

function ago(iso) {
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "только что";
  if (min < 60) return `${min} мин назад`;
  const hours = Math.round(min / 60);
  if (hours < 24) return `${hours} ч назад`;
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

export function notificationsBell(navigate) {
  startPolling();
  const badge = h("span", { class: "bell__count", hidden: !unread }, unread);
  const button = h("button", { type: "button", class: "bell", "aria-haspopup": "true", "aria-expanded": "false",
                               title: "Уведомления" }, icon("bell", 20), h("span", { class: "sr-only" }, "Уведомления"), badge);
  const panel = h("div", { class: "notifs", hidden: true, role: "dialog", "aria-label": "Уведомления" });
  const wrap = h("div", { class: "bellwrap" }, button, panel);

  const onCount = (e) => {
    // при перерисовке страницы старый колокольчик удаляется — отписываем его
    if (!wrap.isConnected) return window.removeEventListener("notif:count", onCount);
    badge.textContent = e.detail;
    badge.hidden = !e.detail;
    if (!panel.hidden) load();
  };
  window.addEventListener("notif:count", onCount);

  async function load() {
    let items = [];
    try {
      items = await api("/api/notifications?limit=12");
    } catch (err) {
      panel.replaceChildren(h("p", { class: "notifs__empty" }, "Уведомления сейчас недоступны"));
      return;
    }
    const readAll = h("button", { type: "button", class: "notifs__readall", disabled: !items.some((n) => !n.is_read) },
      "Прочитать все");
    readAll.addEventListener("click", async () => {
      await api("/api/notifications/read-all", { method: "POST" });
      await pollCount();
      load();
    });
    panel.replaceChildren(
      h("div", { class: "notifs__head" }, h("span", { class: "notifs__title" }, "Уведомления"), readAll),
      items.length
        ? h("ul", { class: "notifs__list" }, items.map((n) => {
            const item = h("li", {},
              h("button", { type: "button", class: `notif notif--${n.level} ${n.is_read ? "" : "notif--unread"}` },
                h("span", { class: "notif__title" }, n.title),
                n.body ? h("span", { class: "notif__body" }, n.body) : null,
                h("span", { class: "notif__time" }, ago(n.created_at))));
            item.querySelector("button").addEventListener("click", async () => {
              close();
              if (!n.is_read) api(`/api/notifications/${n.id}/read`, { method: "POST" }).then(pollCount).catch(() => {});
              if (n.link) navigate(n.link);
            });
            return item;
          }))
        : h("p", { class: "notifs__empty" }, "Здесь будут новости о ваших заказах"));
  }

  function close() {
    panel.hidden = true;
    button.setAttribute("aria-expanded", "false");
    document.removeEventListener("click", outside);
  }
  function outside(e) {
    if (!wrap.contains(e.target)) close();
  }
  button.addEventListener("click", () => {
    if (!panel.hidden) return close();
    panel.hidden = false;
    button.setAttribute("aria-expanded", "true");
    panel.replaceChildren(h("p", { class: "notifs__empty" }, "Загрузка…"));
    load();
    setTimeout(() => document.addEventListener("click", outside));
  });
  wrap.addEventListener("keydown", (e) => { if (e.key === "Escape") { close(); button.focus(); } });

  return wrap;
}

export function resetNotifications() {
  unread = 0;
  clearInterval(poller);
  poller = null;
}
