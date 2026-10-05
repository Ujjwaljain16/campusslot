// Thin wrapper over fetch. The browser only ever calls relative /api/... URLs: nginx (Compose) or
// the Ingress (Kubernetes) decides where the backend actually lives, so no hostname is hard-coded.

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function messageFrom(detail, status) {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail) && detail.message) {
    return detail.message;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    // FastAPI validation errors (422): show the first problem in plain words.
    const first = detail[0];
    const field = Array.isArray(first.loc) ? first.loc.filter((p) => p !== "body").join(".") : "";
    return field ? `${field}: ${first.msg}` : first.msg;
  }
  return `Request failed (${status})`;
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new ApiError("Cannot reach the CampusSlot server. Check your connection and try again.", 0);
  }

  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(messageFrom(body?.detail, response.status), response.status, body?.detail);
  }
  return body;
}

const query = (params) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  });
  const text = search.toString();
  return text ? `?${text}` : "";
};

export const api = {
  info: () => request("/info"),
  listRooms: () => request(`/rooms${query({ active_only: true })}`),
  listBookings: ({ day, tzOffset }) =>
    request(`/bookings${query({ day, tz_offset_minutes: tzOffset, status: "confirmed" })}`),
  stats: ({ day, tzOffset }) => request(`/bookings/stats${query({ day, tz_offset_minutes: tzOffset })}`),
  createBooking: (payload) => request("/bookings", { method: "POST", body: JSON.stringify(payload) }),
  updateBooking: (id, payload) =>
    request(`/bookings/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteBooking: (id) => request(`/bookings/${id}`, { method: "DELETE" }),
};
