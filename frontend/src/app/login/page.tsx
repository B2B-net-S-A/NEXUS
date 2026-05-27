"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import api from "@/lib/api";
import { requiresOnboarding, useAuthStore } from "@/store/auth";
import { AlertCircle, ArrowRight, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FormField } from "@/components/ui/form-field";

function safeNextPath(raw: string | null): string {
  if (!raw) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

function ssoErrorMessage(rawCode: string | null): string | null {
  if (!rawCode) return null;
  const code = rawCode.toLowerCase();
  if (code === "domain_forbidden") {
    return "Twoja domena email nie jest dopuszczona do logowania przez Microsoft. Skontaktuj się z administratorem.";
  }
  if (code.includes("missing identity claims")) {
    return "Microsoft nie zwrócił wymaganych danych identyfikacyjnych. Spróbuj ponownie.";
  }
  if (code.includes("state expired")) {
    return "Sesja logowania wygasła. Kliknij ponownie 'Zaloguj się przez Microsoft'.";
  }
  if (code.includes("token exchange failed")) {
    return "Microsoft odrzucił prośbę o token. Spróbuj ponownie lub zgłoś administratorowi.";
  }
  return decodeURIComponent(rawCode);
}

// `?reason=session_expired` is set by the axios interceptor in lib/api.ts when
// it detects an expired JWT (401, or 403 on auth-scoped endpoints, or 3+ 403s
// in a 5s window). We surface it as an informational banner so the user knows
// why they were bounced here.
function sessionReasonMessage(rawReason: string | null): string | null {
  if (!rawReason) return null;
  if (rawReason === "session_expired") {
    return "Twoja sesja wygasła. Zaloguj się ponownie, aby kontynuować.";
  }
  return null;
}

function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ssoLoading, setSsoLoading] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = safeNextPath(searchParams.get("next"));
  const ssoErrorRaw = searchParams.get("error");
  const sessionReason = sessionReasonMessage(searchParams.get("reason"));
  const { setAuth, token } = useAuthStore();

  useEffect(() => {
    const storedToken =
      typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (storedToken || token) {
      router.replace(nextPath);
    }
  }, [token, router, nextPath]);

  useEffect(() => {
    const msg = ssoErrorMessage(ssoErrorRaw);
    if (msg) setError(msg);
  }, [ssoErrorRaw]);

  const handleMicrosoftLogin = async () => {
    setSsoLoading(true);
    setError(null);
    try {
      const { data } = await api.get("/api/auth/microsoft/authorize");
      if (!data?.authorize_url) throw new Error("Brak authorize_url w odpowiedzi");
      window.location.href = data.authorize_url;
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(
        e.response?.data?.detail ||
          e.message ||
          "Nie udało się uruchomić logowania Microsoft",
      );
      setSsoLoading(false);
    }
  };

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
            {sessionReason && !error && (
              <div
                role="status"
                className="flex items-start gap-2 text-sm text-foreground bg-muted/60 border border-border rounded-md px-3 py-2"
              >
                <Info className="h-4 w-4 shrink-0 mt-0.5 text-muted-foreground" />
                <span>{sessionReason}</span>
              </div>
            )}
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

          <div className="relative my-5">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-border" />
            </div>
            <div className="relative flex justify-center text-xs">
              <span className="bg-card px-2 text-muted-foreground">lub</span>
            </div>
          </div>

          <button
            type="button"
            onClick={handleMicrosoftLogin}
            disabled={ssoLoading}
            className="w-full flex items-center justify-center gap-2 rounded-md border border-border bg-background px-3 py-2.5 text-sm font-medium text-foreground hover:bg-muted/50 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 21 21"
              className="h-4 w-4"
              fill="none"
            >
              <path d="M0 0h10v10H0z" fill="#F25022" />
              <path d="M11 0h10v10H11z" fill="#7FBA00" />
              <path d="M0 11h10v10H0z" fill="#00A4EF" />
              <path d="M11 11h10v10H11z" fill="#FFB900" />
            </svg>
            {ssoLoading ? "Przekierowanie…" : "Zaloguj się przez Microsoft"}
          </button>
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
