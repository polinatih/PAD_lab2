import { api } from "../api.js";
import { money } from "../cuisine.js";
import { h, showFieldErrors, toast } from "../dom.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Платёж создаётся асинхронно (по событию order.created), поэтому сразу после оформления
// его может ещё не быть — подождём немного.
async function loadPayment(orderId) {
  for (let i = 0; i < 8; i++) {
    try {
      return await api(`/api/payments/order/${orderId}`);
    } catch (err) {
      if (err.code !== "payment_not_ready") throw err;
      await sleep(600);
    }
  }
  return null;
}

function formatCard(value) {
  return value.replace(/\D/g, "").slice(0, 19).replace(/(\d{4})(?=\d)/g, "$1 ");
}

function formatExpiry(value) {
  const d = value.replace(/\D/g, "").slice(0, 4);
  return d.length > 2 ? `${d.slice(0, 2)}/${d.slice(2)}` : d;
}

// Форма оплаты картой. onPaid вызывается после успешной оплаты.
export function paymentPanel(order, onPaid) {
  const panel = h("section", { class: "paycard", "aria-busy": "true" }, h("p", { class: "muted" }, "Готовим оплату…"));

  loadPayment(order.id).then((payment) => {
    panel.removeAttribute("aria-busy");
    if (!payment) {
      panel.replaceChildren(h("p", { class: "notice" }, "Платёжный сервис не ответил. Обновите страницу через минуту."));
      return;
    }
    if (payment.status !== "pending") return panel.remove();

    const number = h("input", { name: "card_number", inputmode: "numeric", autocomplete: "cc-number",
                                placeholder: "0000 0000 0000 0000", required: true });
    number.addEventListener("input", () => { number.value = formatCard(number.value); });
    const expiry = h("input", { name: "expiry", inputmode: "numeric", autocomplete: "cc-exp", placeholder: "ММ/ГГ", required: true });
    expiry.addEventListener("input", () => { expiry.value = formatExpiry(expiry.value); });
    const cvc = h("input", { name: "cvc", inputmode: "numeric", autocomplete: "cc-csc", placeholder: "123", maxlength: 4, required: true });
    const attempts = h("p", { class: "muted" });
    const drawAttempts = (left) => {
      attempts.textContent = left < 3 ? `Осталось попыток: ${left}` : "";
    };
    drawAttempts(payment.attempts_left);

    const form = h("form", { class: "form", novalidate: true },
      h("label", { class: "field" }, h("span", { class: "field__label" }, "Номер карты"), number),
      h("div", { class: "form__row" },
        h("label", { class: "field" }, h("span", { class: "field__label" }, "Срок действия"), expiry),
        h("label", { class: "field" }, h("span", { class: "field__label" }, "CVC"), cvc)),
      attempts,
      h("button", { class: "btn btn--accent btn--wide", type: "submit" }, `Оплатить ${money(payment.amount)}`),
      h("p", { class: "paycard__hint" },
        "Это учебный проект, деньги не списываются. Карта 4242 4242 4242 4242 оплачивает заказ, ",
        "4000 0000 0000 0002 — банк отклоняет платёж."));

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = form.querySelector("button[type=submit]");
      const [mm, yy] = expiry.value.split("/");
      btn.disabled = true;
      try {
        await api(`/api/payments/order/${order.id}/pay`, {
          method: "POST",
          body: { card_number: number.value, exp_month: Number(mm) || 0, exp_year: Number(yy) || 0, cvc: cvc.value },
        });
        panel.replaceChildren(h("p", { class: "paycard__ok" }, "Оплата прошла. Передаём заказ ресторану…"));
        toast("Оплачено", "success");
        onPaid?.();
      } catch (err) {
        showFieldErrors(form, err);
        if (err.code === "card_declined") drawAttempts(err.details?.attempts_left ?? 0);
        toast(err.message, "error");
        if (err.code === "payment_failed" || err.code === "payment_expired") onPaid?.();
        btn.disabled = false;
      }
    });

    panel.replaceChildren(h("h2", { class: "panel__title" }, "Оплата картой"), form);
  }).catch((err) => panel.replaceChildren(h("p", { class: "notice" }, err.message)));

  return panel;
}
