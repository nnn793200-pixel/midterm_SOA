const API_BASE_URL =
  import.meta.env.VITE_API_GATEWAY_URL || "http://localhost:8000/api/v1";

export const MAILPIT_WEB_URL =
  import.meta.env.VITE_MAILPIT_WEB_URL || "http://localhost:8025";

export function generateUuid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function formatCurrency(amount) {
  if (
    amount === null ||
    amount === undefined ||
    amount === "" ||
    !Number.isFinite(Number(amount))
  ) {
    return "—";
  }
  return `${Number(amount).toLocaleString("vi-VN")} VNĐ`;
}

export function formatDateTime(isoString) {
  if (!isoString) return "—";
  try {
    return new Date(isoString).toLocaleString("vi-VN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  } catch {
    return isoString;
  }
}

async function request(path, options = {}) {
  const token = localStorage.getItem("ibanking_access_token");
  const correlationId = generateUuid();

  const headers = {
    "Content-Type": "application/json",
    "X-Request-ID": correlationId,
    ...(options.headers || {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  const respCorrelationId =
    response.headers.get("X-Request-ID") || correlationId;

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const detailObj =
      data?.detail && typeof data.detail === "object" ? data.detail : null;
    const errObj = data?.error ||
      detailObj || {
        code: `HTTP_${response.status}`,
        message:
          (typeof data?.detail === "string" && data.detail) ||
          "Đã xảy ra lỗi khi giao tiếp với hệ thống.",
        details: null,
        correlation_id: respCorrelationId,
      };
    const error = new Error(errObj.message || "Lỗi xử lý yêu cầu");
    error.status = response.status;
    error.code = errObj.code || `HTTP_${response.status}`;
    error.details = errObj.details ?? null;
    error.correlationId = errObj.correlation_id || respCorrelationId;
    throw error;
  }

  return data;
}

export const api = {
  login: (username, password) =>
    request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  getDemoUsers: () => request("/accounts/demo-users"),

  getMyAccount: () => request("/accounts/me"),

  listAllTuitions: () => request("/tuitions"),

  lookupTuitionByMssv: (studentId) =>
    request(`/tuitions/${encodeURIComponent(studentId.trim())}`),

  initiatePayment: (payload, idempotencyKey) =>
    request("/payments/initiate", {
      method: "POST",
      headers: {
        "Idempotency-Key": idempotencyKey || generateUuid(),
      },
      body: JSON.stringify(payload),
    }),

  confirmOtp: (transactionId, otpCode, idempotencyKey) =>
    request(`/payments/${transactionId}/confirm-otp`, {
      method: "POST",
      headers: {
        "Idempotency-Key": idempotencyKey || generateUuid(),
      },
      body: JSON.stringify({ otp_code: otpCode }),
    }),

  getDemoOtp: (transactionId) =>
    request(`/payments/${transactionId}/demo-otp`),

  getPaymentHistory: () => request("/payments/history"),

  getTransactionDetail: (transactionId) =>
    request(`/payments/${transactionId}`),

  getClusterHealth: () => request("/health/services"),

  resetDemoSystem: () =>
    request("/system/reset-demo", {
      method: "POST",
    }),
};
