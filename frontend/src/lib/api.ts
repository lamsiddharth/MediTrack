// Thin API client.
//
// Requests are same-origin: in production nginx serves this bundle and proxies
// /api to the backend, and in development Vite proxies it. So the session
// cookie travels automatically and there is no token to store.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...init,
  });

  if (response.status === 204) return undefined as T;

  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  return (await response.json()) as T;
}

/** Pull a human-readable message out of a failure response. */
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;

    if (typeof detail === "string") return detail;

    // FastAPI validation errors arrive as a list of per-field objects.
    if (Array.isArray(detail)) {
      const first = detail[0];
      if (first?.msg) {
        return String(first.msg).replace(/^Value error,\s*/, "");
      }
    }
  } catch {
    // fall through to a status-based message
  }

  if (response.status === 401) return "Your session has expired. Please sign in again.";
  if (response.status >= 500) return "The server could not complete that request.";
  return `Request failed (${response.status}).`;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) => request<T>(path, json("POST", body)),
  put: <T>(path: string, body: unknown) => request<T>(path, json("PUT", body)),
  patch: <T>(path: string, body: unknown) => request<T>(path, json("PATCH", body)),
  postForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form }),
};
