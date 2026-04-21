"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import api from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { AlertCircle, ArrowRight, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FormField } from "@/components/ui/form-field";

// Simple allowlist: only relative paths survive `?next=`.
function safeNextPath(raw: string | null): string {
  if (!raw) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = safeNextPath(searchParams.get("next"));
  const { setAuth, token } = useAuthStore();

  useEffect(() => {
    const storedToken =
      typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (storedToken || token) {
      router.replace(nextPath);
    }
  }, [token, router, nextPath]);

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
      router.push(nextPath);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Błąd logowania");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      data-ui="v2"
      className="min-h-screen flex items-center justify-center px-4 py-10 bg-[hsl(var(--bg-canvas))]"
    >
      {/* Subtle cinematic overlay — cream→plum-50 gradient, no bold gradient per brandbook */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 80% 60% at 50% 10%, hsl(var(--accent-soft)) 0%, transparent 60%)",
        }}
        aria-hidden="true"
      />

      <div className="relative z-10 w-full max-w-md">
        {/* Brand mark */}
        <div className="flex flex-col items-center mb-6">
          <div className="w-14 h-14 rounded-v2-m bg-[hsl(var(--bg-chrome))] text-[hsl(var(--accent))] flex items-center justify-center shadow-v2-l mb-4">
            <span className="font-display font-extrabold text-2xl">N</span>
          </div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[hsl(var(--accent))]">
            B2B.net · Nexus
          </p>
          <h1 className="font-display text-3xl font-extrabold tracking-[-0.025em] text-[hsl(var(--text-title))] mt-1">
            Zaloguj się
          </h1>
          <p className="text-sm text-[hsl(var(--text-muted))] mt-1">
            Twój pipeline rekrutacyjny w jednym miejscu.
          </p>
        </div>

        {/* Card */}
        <div className="bg-[hsl(var(--bg-surface))] border border-[hsl(var(--border-subtle))] rounded-v2-l shadow-v2-xl p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 text-sm text-[hsl(var(--accent-strong))] bg-[hsl(var(--accent-soft))] border border-[hsl(var(--accent))]/20 rounded-v2-s px-3 py-2"
              >
                <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <FormField label="Email" htmlFor="login-email" required>
              <Input
                id="login-email"
                type="email"
                autoComplete="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="rekruter@b2bnet.pl"
              />
            </FormField>

            <FormField label="Hasło" htmlFor="login-password" required>
              <Input
                id="login-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="••••••••"
              />
            </FormField>

            <Button type="submit" variant="primary" size="lg" loading={loading} className="w-full">
              {loading ? "Logowanie…" : "Zaloguj się"}
              {!loading && <ArrowRight className="h-4 w-4" />}
            </Button>
          </form>
        </div>

        {/* Footer */}
        <div className="mt-6 flex items-center justify-center gap-2 text-xs text-[hsl(var(--text-muted))]">
          <Sparkles className="h-3 w-3 text-[hsl(var(--accent))]" />
          <span>
            Nexus · <strong className="text-[hsl(var(--text-title))]">Define tomorrow.</strong>
          </span>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-[hsl(var(--bg-canvas))]">
          <div className="text-sm text-[hsl(var(--text-muted))]">Ładowanie…</div>
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
