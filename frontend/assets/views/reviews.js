import { api } from "../api.js";
import { h, toast } from "../dom.js";

export function stars(rating, label = true) {
  const full = Math.round(rating);
  return h("span", { class: "stars", "aria-label": label ? `Оценка ${rating} из 5` : null },
    [1, 2, 3, 4, 5].map((i) => h("span", { class: i <= full ? "star star--on" : "star", "aria-hidden": "true" }, "★")));
}

function when(iso) {
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

function reviewItem(r, { replyForm = false } = {}) {
  const item = h("li", { class: "review" },
    h("div", { class: "review__head" }, stars(r.rating), h("span", { class: "review__author" }, r.author),
      h("span", { class: "muted" }, when(r.created_at))),
    r.comment ? h("p", { class: "review__text" }, r.comment) : null,
    r.reply ? h("div", { class: "review__reply" }, h("span", { class: "review__reply-label" }, "Ответ ресторана"), h("p", {}, r.reply)) : null);

  if (replyForm && !r.reply) {
    const input = h("input", { name: "text", placeholder: "Ответить клиенту", "aria-label": "Ответ на отзыв" });
    const form = h("form", { class: "review__replyform" }, input,
      h("button", { type: "submit", class: "btn btn--ghost btn--small" }, "Ответить"));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const updated = await api(`/api/reviews/${r.id}/reply`, { method: "POST", body: { text: input.value.trim() } });
        item.replaceWith(reviewItem(updated, { replyForm }));
        toast("Ответ опубликован", "success");
      } catch (err) {
        toast(err.message, "error");
      }
    });
    item.append(form);
  }
  return item;
}

// Блок отзывов на странице ресторана: средняя оценка, распределение, последние отзывы
export async function restaurantReviews(restaurantId) {
  let data;
  try {
    data = await api(`/api/reviews/restaurant/${restaurantId}`);
  } catch {
    return null; // review-service недоступен — страница ресторана показывается без отзывов
  }
  const { stats, items } = data;
  if (!stats.rating_count) {
    return h("section", { class: "reviews" }, h("h2", { class: "menu__title" }, "Отзывы"),
      h("p", { class: "muted" }, "Отзывов пока нет. Оценить ресторан можно после доставки заказа."));
  }
  const max = Math.max(...Object.values(stats.distribution));
  return h("section", { class: "reviews" },
    h("h2", { class: "menu__title" }, "Отзывы"),
    h("div", { class: "reviews__layout" },
      h("div", { class: "rating" },
        h("span", { class: "rating__value" }, stats.rating_avg.toFixed(1).replace(".", ",")),
        stars(stats.rating_avg),
        h("span", { class: "muted" }, `${stats.rating_count} ${stats.rating_count === 1 ? "оценка" : stats.rating_count < 5 ? "оценки" : "оценок"}`),
        h("ul", { class: "rating__bars" }, [5, 4, 3, 2, 1].map((s) =>
          h("li", {}, h("span", {}, s), h("span", { class: "rating__bar" },
            h("span", { style: `width:${max ? (stats.distribution[s] / max) * 100 : 0}%` })),
            h("span", { class: "muted" }, stats.distribution[s]))))),
      h("ul", { class: "reviews__list" }, items.map((r) => reviewItem(r)))));
}

// Блок на странице доставленного заказа: оценить ресторан или посмотреть свою оценку
export async function orderReviewBlock(order) {
  let state;
  try {
    state = await api(`/api/reviews/order/${order.id}`);
  } catch {
    return null;
  }
  if (state.review) {
    return h("section", { class: "reviewbox" },
      h("h2", { class: "panel__title" }, "Ваша оценка"), h("ul", { class: "reviews__list" }, reviewItem(state.review)));
  }
  if (!state.can_review) return null;

  let rating = 0;
  const starButtons = [1, 2, 3, 4, 5].map((i) => {
    const b = h("button", { type: "button", class: "starpick", "aria-label": `${i} из 5`, "aria-pressed": "false" }, "★");
    b.addEventListener("click", () => {
      rating = i;
      starButtons.forEach((x, j) => {
        x.classList.toggle("starpick--on", j < i);
        x.setAttribute("aria-pressed", j === i - 1 ? "true" : "false");
      });
      submit.disabled = false;
    });
    return b;
  });
  const comment = h("textarea", { name: "comment", rows: 3, placeholder: "Что понравилось, что нет?" });
  const submit = h("button", { type: "submit", class: "btn btn--primary", disabled: true }, "Оставить отзыв");
  const form = h("form", { class: "form" },
    h("div", { class: "starpicker", role: "group", "aria-label": "Оценка" }, starButtons),
    comment, submit);
  const box = h("section", { class: "reviewbox" }, h("h2", { class: "panel__title" }, `Как вам «${order.restaurant_name}»?`), form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const review = await api("/api/reviews", { method: "POST", body: { order_id: order.id, rating, comment: comment.value.trim() } });
      box.replaceChildren(h("h2", { class: "panel__title" }, "Спасибо за отзыв!"), h("ul", { class: "reviews__list" }, reviewItem(review)));
    } catch (err) {
      toast(err.message, "error");
    }
  });
  return box;
}

// Отзывы для владельца ресторана, с формой ответа
export async function ownerReviews(restaurantId) {
  let items;
  try {
    items = await api(`/api/reviews/owner?restaurant_id=${restaurantId}`);
  } catch {
    return null;
  }
  return h("section", { class: "panel" },
    h("h2", { class: "panel__title" }, "Отзывы клиентов"),
    items.length
      ? h("ul", { class: "reviews__list" }, items.map((r) => reviewItem(r, { replyForm: true })))
      : h("p", { class: "muted" }, "Отзывов пока нет."));
}
