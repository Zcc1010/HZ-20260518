import axios from "axios";
import { useAuthStore } from "../stores/authStore";
import { withBasePath } from "./basePath";

const api = axios.create({
  baseURL: withBasePath("/api"),
  timeout: 30000,
});

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const isLoginRequest = error.config?.url?.includes("/auth/login");
      const authlessEnabled = useAuthStore.getState().authlessEnabled;
      if (!isLoginRequest && !authlessEnabled) {
        useAuthStore.getState().clearAuth();
        window.location.href = withBasePath("/login");
      }
    }
    return Promise.reject(error);
  }
);

export default api;
