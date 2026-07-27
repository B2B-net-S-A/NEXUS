"use client";

import { useState, useEffect, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { isAxiosError } from "axios";
import api, { extractErrorMsg } from "@/lib/api";
import { decodeJwtPayload, isJwtExpired } from "@/lib/jwt";
import { clearSessionArtifacts, hasAuthCookie } from "@/lib/session";
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

/** Które drogi wejścia pokazać — źródłem prawdy jest GET /api/auth/methods. */
interface AuthMethods {
  password: boolean
  microsoft: boolean
  self_registration: boolean
}

// Stan początkowy = docelowy stan produkcyjny (NEXUS jest narzędziem
// wewnętrznym: tylko Microsoft). Dzięki temu formularz hasła nie mignie przed
// odpowiedzią backendu, a gdy /methods jest nieosiągalne, ekran zostaje w
// wersji zamkniętej zamiast pokazywać drogę, której i tak nie ma.
//
// ``microsoft: true`` jest tu świadomym założeniem NEXUS-owym — na produkcji
// SSO jest zawsze skonfigurowane. Na środowisku bez SSO
// (M365_INTEGRATION_ENABLED=false) przycisk mignie i zniknie po odpowiedzi
// /methods. Zamiana na ``false`` dałaby gorszy kompromis: ekran bez ŻADNEJ
// drogi wejścia przez pierwszy render — tam, gdzie to boli najbardziej.
const LOCKED_DOWN: AuthMethods = {
  password: false,
  microsoft: true,
  self_registration: false,
}

function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ssoLoading, setSsoLoading] = useState(false);
  // Trwa weryfikacja zastanej sesji przez /api/auth/me — chowamy drogi wejścia,
  // żeby użytkownik z ważną sesją nie zaczął wpisywać hasła w formularz, który
  // zaraz zniknie pod nim wraz z przekierowaniem.
  const [checkingSession, setCheckingSession] = useState(false);
  const [methods, setMethods] = useState<AuthMethods>(LOCKED_DOWN);
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = safeNextPath(searchParams.get("next"));
  const ssoErrorRaw = searchParams.get("error");
  const sessionReason = sessionReasonMessage(searchParams.get("reason"));
  const { setAuth, token } = useAuthStore();
  // Komunikat z weryfikacji zastanej sesji wygrywa z ogólnym `?reason=` —
  // jest bardziej konkretny (np. token unieważniony serwerowo).
  const infoMessage = notice ?? sessionReason;

  // Auto-redirect osób, które mają JESZCZE ważną sesję — ale dopiero po
  // POTWIERDZENIU jej u backendu i po odtworzeniu cookie routingowego.
  //
  // Historia dwóch pętli, które ten efekt zamyka:
  //
  //  1. Kiedyś wystarczała sama OBECNOŚĆ tokenu (`storedToken || token`), więc
  //     wygasły JWT gnijący w localStorage odbijał usera z /login do aplikacji,
  //     skąd middleware natychmiast wykopywał go z powrotem.
  //  2. Sprawdzanie samego `exp` (poprzednia wersja) nie wystarczyło, bo
  //     middleware bramkuje po **cookie** `nexus_access`, a nie po localStorage.
  //     Gdy cookie zniknęło (wyczyszczone/zablokowane przez przeglądarkę), a w
  //     localStorage siedział niewygasły JWT, obie warstwy trwale się nie
  //     zgadzały: /login → replace(next) → middleware → /login → …
  //     Handler 401 z lib/api.ts (jedyne miejsce, które sprząta martwą sesję)
  //     nigdy się nie odpalał, bo w tej pętli NIE LECI żaden request do API —
  //     a na ścieżce /login* i tak robi early-return.
  //
  // Dlatego: (a) predykat wejściowy jest LUSTREM bramki z middleware.ts
  // (payload + nieprzeterminowany `exp` + obecny claim `role`) — inaczej token
  // bez roli przechodziłby tutaj, a middleware kasowałby cookie i zawracał;
  // (b) token jest walidowany przez GET /api/auth/me, więc JWT unieważniony
  // serwerowo (users.tokens_valid_after, PR #906) nie udaje żywej sesji;
  // (c) cookie jest odtwarzane RAZ przez setAuth i sprawdzane — bez tego
  // przeglądarka blokująca cookies dawała pętlę mimo poprawnego tokenu;
  // (d) każda porażka kończy się sprzątnięciem sesji i POZOSTANIEM na /login.
  const sessionProbed = useRef(false);
  // Odrzucaj wynik sondy TYLKO po realnym odmontowaniu. Sprzątaczka zwykłego
  // efektu odpalałaby się przy każdym ponownym renderze (identyczność `router`
  // / `setAuth` nie jest gwarantowana), więc anulowałaby własny, jeszcze
  // lecący request — sesja nigdy nie zostałaby ani potwierdzona, ani
  // sprzątnięta, i pętla wróciłaby tylnymi drzwiami.
  const disposed = useRef(false);
  useEffect(
    () => () => {
      disposed.current = true;
    },
    [],
  );
  useEffect(() => {
    if (sessionProbed.current) return;
    const storedToken =
      typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    const activeToken = token ?? storedToken;
    if (!activeToken) return;
    sessionProbed.current = true;

    const payload = decodeJwtPayload(activeToken);
    if (!payload || isJwtExpired(payload.exp) || !payload.role) {
      clearSessionArtifacts();
      return;
    }

    setCheckingSession(true);
    api
      .get("/api/auth/me", {
        // Jawny nagłówek — request-interceptor go NIE nadpisuje (patrz komentarz
        // w lib/api.ts) i to jest dokładnie ten kontrakt, na którym stoimy.
        headers: { Authorization: `Bearer ${activeToken}` },
      })
      .then(({ data }) => {
        if (disposed.current) return;
        // Persystuje usera i ODTWARZA cookie `nexus_access`.
        setAuth(data, activeToken);
        if (!hasAuthCookie()) {
          clearSessionArtifacts();
          setCheckingSession(false);
          setError(
            "Twoja przeglądarka blokuje pliki cookie dla tej strony, więc sesja nie może zostać utrzymana. Włącz obsługę cookies i zaloguj się ponownie.",
          );
          return;
        }
        router.replace(nextPath);
      })
      .catch((err: unknown) => {
        if (disposed.current) return;
        setCheckingSession(false);
        // 401 = sesja martwa → sprzątamy. 403 = „jesteś zalogowany, ale nie
        // wolno Ci tego zasobu" — nie kasujemy sesji (kontrakt 401 vs 403).
        // Błąd sieci / 5xx też nie kasuje: chwilowa awaria backendu nie może
        // niszczyć poprawnej sesji. W ŻADNYM z tych przypadków nie
        // przekierowujemy, więc pętla jest niemożliwa.
        if (isAxiosError(err) && err.response?.status === 401) {
          clearSessionArtifacts();
          setNotice(
            "Twoja sesja wygasła lub została unieważniona. Zaloguj się ponownie.",
          );
        }
      });
  }, [token, router, nextPath, setAuth]);

  useEffect(() => {
    const msg = ssoErrorMessage(ssoErrorRaw);
    if (msg) setError(msg);
  }, [ssoErrorRaw]);

  useEffect(() => {
    let cancelled = false;
    api
      .get<AuthMethods>("/api/auth/methods")
      .then(({ data }) => {
        if (!cancelled && data) setMethods(data);
      })
      .catch(() => {
        // Zostaw LOCKED_DOWN — bez odpowiedzi backendu nie zgadujemy, że
        // logowanie hasłem jest dostępne.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleMicrosoftLogin = async () => {
    setSsoLoading(true);
    setError(null);
    try {
      const { data } = await api.get("/api/auth/microsoft/authorize");
      if (!data?.authorize_url) throw new Error("Brak authorize_url w odpowiedzi");
      window.location.href = data.authorize_url;
    } catch (err: unknown) {
      // extractErrorMsg zamiast surowego `e.message` — inaczej 429 z limitera
      // (ciało slowapi nie ma klucza `detail`) wyświetlał się użytkownikowi
      // jako „Request failed with status code 429".
      setError(extractErrorMsg(err) || "Nie udało się uruchomić logowania Microsoft");
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
    } catch (err: unknown) {
      setError(extractErrorMsg(err) || "Błąd logowania");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell
      heading="Zaloguj się do Nexus"
      subtitle="Twój pipeline rekrutacyjny w jednym miejscu."
    >
      {/*
        Banery (wygasła sesja / błąd SSO) są POZA formularzem — muszą być
        widoczne także gdy logowanie hasłem jest wyłączone i formularza nie ma.
      */}
      <div className="space-y-4">
            {infoMessage && !error && (
              <div
                role="status"
                className="flex items-start gap-2 text-sm text-foreground bg-muted/60 border border-border rounded-md px-3 py-2"
              >
                <Info className="h-4 w-4 shrink-0 mt-0.5 text-muted-foreground" />
                <span>{infoMessage}</span>
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
      </div>

      {checkingSession && (
        <p
          role="status"
          className="pt-6 text-center text-sm text-muted-foreground"
        >
          Sprawdzam zapisaną sesję…
        </p>
      )}

      {!checkingSession && methods.password && (
          <form onSubmit={handleSubmit} className="space-y-4 pt-4">
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
      )}

      {/* Separator ma sens tylko gdy realnie są dwie drogi do wyboru. */}
      {!checkingSession && methods.password && methods.microsoft && (
          <div className="relative my-5">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-border" />
            </div>
            <div className="relative flex justify-center text-xs">
              <span className="bg-card px-2 text-muted-foreground">lub</span>
            </div>
          </div>
      )}

      {!checkingSession && methods.microsoft && (
          <button
            type="button"
            onClick={handleMicrosoftLogin}
            disabled={ssoLoading}
            // Gdy SSO jest jedyną drogą, przycisk przestaje być alternatywą
            // i dostaje wygląd akcji głównej.
            className={
              methods.password
                ? "w-full flex items-center justify-center gap-2 rounded-md border border-border bg-background px-3 py-2.5 text-sm font-medium text-foreground hover:bg-muted/50 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                : "mt-6 w-full flex items-center justify-center gap-2 rounded-md bg-primary px-3 py-3 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            }
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
      )}

      {checkingSession ? null : methods.self_registration ? (
          <p className="text-center text-sm text-muted-foreground pt-5">
            Nie masz konta?{" "}
            <Link
              href="/register"
              className="text-primary hover:text-primary/80 hover:underline underline-offset-4 font-medium"
            >
              Zarejestruj się
            </Link>
          </p>
      ) : (
          // Narzędzie wewnętrzne — kont nie zakłada się samodzielnie.
          <p className="text-center text-xs text-muted-foreground pt-5">
            Dostęp wyłącznie dla pracowników B2B.net. Konta zakłada administrator.
          </p>
      )}
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
