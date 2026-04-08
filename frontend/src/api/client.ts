import axios from "axios";

// В Docker/production: фронт и бэк на одном хосте, nginx проксирует /api/ → backend
// В dev: берём из VITE_API_URL или используем текущий хост:8000/api
function resolveBaseUrl(): string {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  // Если открыт через браузер — используем тот же хост, nginx отдаёт /api/
  const { protocol, hostname, port } = window.location;
  // dev vite (порт 5173) → бэкенд на 8000
  if (port === "5173" || port === "3000") {
    return `${protocol}//${hostname}:8000/api`;
  }
  // production (порт 80/443) → nginx проксирует /api/
  return `${protocol}//${hostname}${port ? `:${port}` : ""}/api`;
}

const BASE_URL = resolveBaseUrl();

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
  timeout: 5000,
});

// Attach token to every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On 401 redirect to login
apiClient.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("user");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  },
);
