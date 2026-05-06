"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import api from "@/lib/api";
import { requiresOnboarding, useAuthStore } from "@/store/auth";
import { AlertCircle, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FormField } from "@/components/ui/form-field";

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
      if (requiresOnboarding(me.data)) {
        router.push("/onboarding");
      } else {
        router.push(nextPath);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || "Błąd logowania");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-10 bg-background">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="w-10 h-10 rounded-md bg-primary text-primary-foreground flex items-center justify-center mb-5">
            <span className="font-semibold text-base">N</span>
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            Zaloguj się do Nexus
          </h1>
          <p className="text-sm text-muted-foreground mt-1.5">
            Twój pipeline rekrutacyjny w jednym miejscu.
          </p>
        </div>

        <div className="bg-card border border-border rounded-xl shadow-sm p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-3 py-2"
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

            <div className="text-center pt-1">
              <Link
                href="/login/forgot-password"
                className="text-sm text-primary hover:text-primary/80 hover:underline underline-offset-4"
              >
                Zapomniałeś hasła?
              </Link>
            </div>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Nexus · B2B.net
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-background">
          <div className="text-sm text-muted-foreground">Ładowanie…</div>
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
