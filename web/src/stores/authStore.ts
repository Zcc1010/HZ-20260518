import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface UserInfo {
  id: string;
  username: string;
  role: "admin" | "user";
}

interface BootstrapState {
  authlessEnabled: boolean;
  initialized: boolean;
}

interface AuthState {
  user: UserInfo | null;
  token: string | null;
  authlessEnabled: boolean;
  initialized: boolean;
  setAuth: (user: UserInfo, token: string) => void;
  setBootstrap: (state: BootstrapState & { user?: UserInfo | null }) => void;
  markInitialized: () => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      authlessEnabled: false,
      initialized: false,
      setAuth: (user, token) => set({ user, token, authlessEnabled: false, initialized: true }),
      setBootstrap: ({ authlessEnabled, initialized, user }) =>
        set((state) => ({
          user: authlessEnabled ? (user ?? state.user) : (state.token ? state.user : null),
          token: authlessEnabled ? null : state.token,
          authlessEnabled,
          initialized,
        })),
      markInitialized: () => set({ initialized: true }),
      clearAuth: () =>
        set((state) =>
          state.authlessEnabled
            ? { token: null, initialized: true }
            : { user: null, token: null, initialized: true, authlessEnabled: false }
        ),
    }),
    {
      name: "nanobot-auth",
      partialize: (state) => ({
        user: state.authlessEnabled ? null : state.user,
        token: state.authlessEnabled ? null : state.token,
      }),
    }
  )
);
