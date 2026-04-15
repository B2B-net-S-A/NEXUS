"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { Zap } from "lucide-react";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const { setAuth, token } = useAuthStore();

  // Auto-redirect if already logged in
  useEffect(() => {
    const storedToken = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (storedToken || token) {
      router.replace("/");
    }
  }, [token, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.post("/api/auth/login", { email, password });
      const me = await api.get("/api/auth/me", {
        headers: { Authorization: `Bearer ${data.access_token}` },
      });
      setAuth(me.data, data.access_token);
      router.push("/");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Błąd logowania");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center relative px-4
      bg-gradient-to-br from-blue-600 to-indigo-700
      dark:from-gray-900 dark:to-gray-950">

      {/* Subtle pattern overlay */}
      <div className="absolute inset-0 opacity-10 dark:opacity-5"
        style={{ backgroundImage: "radial-gradient(circle at 1px 1px, white 1px, transparent 0)", backgroundSize: "32px 32px" }}
      />

      {/* Logo above card */}
      <div className="relative z-10 flex flex-col items-center mb-6">
        <div className="w-14 h-14 bg-white/20 backdrop-blur-sm rounded-2xl flex items-center justify-center mb-4 shadow-lg">
          <Zap className="w-8 h-8 text-white" />
        </div>
        <h1 className="text-3xl font-bold text-white tracking-tight">DynaMinds</h1>
        <p className="text-blue-100 dark:text-gray-400 text-sm mt-1">Nexus dla agencji IT</p>
      </div>

      {/* Card */}
      <div className="relative z-10 bg-white dark:bg-gray-900 p-8 rounded-2xl border border-white/20 dark:border-gray-700 shadow-2xl w-full max-w-sm">
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 text-sm px-4 py-3 rounded-lg border border-red-200 dark:border-red-800">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500"
              placeholder="rekruter@firma.pl"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Hasło</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500"
              placeholder="••••••••"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 rounded-lg text-sm transition-colors disabled:opacity-50"
          >
            {loading ? "Logowanie..." : "Zaloguj się"}
          </button>
        </form>
      </div>

      {/* Footer */}
      <p className="relative z-10 mt-6 text-blue-200 dark:text-gray-500 text-xs">
        Powered by B2B.net S.A.
      </p>
    </div>
  );
}
