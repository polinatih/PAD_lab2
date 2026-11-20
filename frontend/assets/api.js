// Клиент API: все запросы идут через API Gateway (тот же адрес, что и сайт).
// Ошибки сервисов приходят в едином формате {"error": {"code", "message", "request_id", "details"}}.

const TOKEN_KEY = "lozhka.token";
const USER_KEY = "lozhka.user";

export class ApiError extends Error {
  constructor(status, error) {
    super(error?.message || `Ошибка ${status}`);
    this.status = status;
    this.code = error?.code;
    this.details = error?.details;
    this.requestId = error?.request_id;
  }
}

export const session = {
  get token() {
    return localStorage.getItem(TOKEN_KEY);
  },
  get user() {
    try {
      return JSON.parse(localStorage.getItem(USER_KEY));
    } catch {
      return null;
    }
  },
  save(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  updateUser(user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  },
};

export async function api(path, { method = "GET", body, form, headers: extra = {} } = {}) {
  const headers = { ...extra };
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(path, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, { message: "Нет связи с сервером. Проверьте, что система запущена." });
  }

  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && session.token) {
      // токен истёк или недействителен — выходим и просим войти заново
      session.clear();
      window.dispatchEvent(new CustomEvent("auth:expired"));
    }
    throw new ApiError(response.status, data?.error);
  }
  return data;
}
