// Небольшие помощники для работы с DOM без фреймворков.
// h() создаёт элементы через DOM API (не через innerHTML) — пользовательские данные не могут внедрить HTML.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === false || value === null || value === undefined) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

// Иконки — простые inline SVG, чтобы не тянуть внешние библиотеки.
const ICONS = {
  bowl: '<path d="M4 12h16a8 8 0 0 1-16 0Z"/><path d="M8 8c0-1.5 1-2 1-3.5M12 8c0-1.5 1-2 1-3.5M16 8c0-1.5 1-2 1-3.5"/>',
  store: '<path d="M4 10v10h16V10"/><path d="M3 10 5 4h14l2 6"/><path d="M3 10a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0"/><path d="M10 20v-5h4v5"/>',
  bike: '<circle cx="6" cy="17" r="3"/><circle cx="18" cy="17" r="3"/><path d="M6 17 10 9h5l3 8M10 9 8 6H6M15 9l-1-3h2"/>',
  shield: '<path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6Z"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.5-7 8-7s8 3 8 7"/>',
  logout: '<path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"/>',
  bag: '<path d="M5 8h14l-1 12H6Z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/>',
};

export function icon(name, size = 22) {
  const span = document.createElement("span");
  span.className = "icon";
  span.setAttribute("aria-hidden", "true");
  span.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
  return span;
}

export function toast(message, kind = "info") {
  const box = document.getElementById("toasts");
  const item = h("div", { class: `toast toast--${kind}` }, message);
  box.append(item);
  setTimeout(() => item.classList.add("toast--leaving"), 3600);
  setTimeout(() => item.remove(), 4000);
}

export function formatDate(iso) {
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

// Показывает ошибки валидации от API рядом с полями формы.
export function showFieldErrors(form, error) {
  form.querySelectorAll(".field__error").forEach((e) => e.remove());
  form.querySelectorAll("[aria-invalid]").forEach((e) => e.removeAttribute("aria-invalid"));
  for (const detail of error?.details || []) {
    const input = form.elements[detail.field];
    if (!input || !input.closest) continue;
    input.setAttribute("aria-invalid", "true");
    input.closest(".field")?.append(h("p", { class: "field__error" }, translateValidation(detail.message)));
  }
}

function translateValidation(message) {
  const rules = [
    [/at least (\d+) character/, (m) => `Минимум ${m[1]} символов`],
    [/at most (\d+) character/, (m) => `Максимум ${m[1]} символов`],
    [/valid email/i, () => "Введите корректный email"],
    [/should match pattern/, () => "Неверный формат"],
    [/Field required/, () => "Обязательное поле"],
  ];
  for (const [re, fn] of rules) {
    const m = message.match(re);
    if (m) return fn(m);
  }
  return message;
}
