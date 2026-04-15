import { create } from "zustand";

interface User {
  id: number;
  email: string;
  name: string;
  role: "admin" | "recruiter" | "manager" | "client";
}

interface AuthState {
  user: User | null;
  token: string | null;
  setAuth: (user: User, token: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: typeof window !== "undefined" ? localStorage.getItem("access_token") : null,
  setAuth: (user, token) => {
    localStorage.setItem("access_token", token);
    set({ user, token });
  },
  logout: () => {
    localStorage.removeItem("access_token");
    set({ user: null, token: null });
    // Redirect to login page
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  },
}));
