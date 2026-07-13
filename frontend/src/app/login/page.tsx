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
import { AuthShell } from "@/components/blocks/AuthShell";

function safeNextPath(raw: string | null): string {
  if (!raw) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

// Decodes a `?error=` query param into a user-facing banner. This param is set
// by the (now button-less) Microsoft SSO callback, which stays reachable during
// the login-migration window as an emergency direct-URL entry. Generic on
// purpose — no button-specific wording, since the SSO button has been removed.
function loginErrorMessage(rawCode: string | null): string | null {
  if (!rawCode) return null;
  const code = rawCode.toLowerCase();
  if (code === "domain_forbidden") {
    return "Twoja domena email nie jest dopuszczona do logowania. Skontaktuj się z administratorem.";
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
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = safeNextPath(searchParams.get("next"));
  const loginErrorRaw = searchParams.get("error");
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
    const msg = loginErrorMessage(loginErrorRaw);
    if (msg) setError(msg);
  }, [loginErrorRaw]);

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
    <AuthShell
      heading="Zaloguj się do Nexus"
      subtitle="Twój pipeline rekrutacyjny w jednym miejscu."
    >
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

          <p className="text-center text-sm text-muted-foreground pt-5">
            Nie masz konta?{" "}
            <Link
              href="/register"
              className="text-primary hover:text-primary/80 hover:underline underline-offset-4 font-medium"
            >
              Zarejestruj się
            </Link>
          </p>
    </AuthShell>
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
