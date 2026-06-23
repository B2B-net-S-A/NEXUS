"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { AlertCircle, ArrowRight, CheckCircle2, Loader2 } from "lucide-react";
import { authApi } from "@/lib/api";
import { AuthShell } from "@/components/blocks/AuthShell";

type Status = "verifying" | "success" | "error";

function VerifyEmailInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [status, setStatus] = useState<Status>("verifying");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    // Guard against React 18 StrictMode double-invoke — the token is single-use,
    // so a second POST would always 400 and clobber a successful first call.
    if (started.current) return;
    started.current = true;

    if (token.length !== 64) {
      setStatus("error");
      setErrorMsg("Link aktywacyjny ma nieprawidłowy format. Poproś o nowy.");
      return;
    }

    (async () => {
      try {
        await authApi.verifyEmail(token);
        setStatus("success");
        setTimeout(() => router.push("/login"), 2500);
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })?.response
          ?.data?.detail;
        setStatus("error");
        setErrorMsg(
          detail ?? "Link aktywacyjny jest nieprawidłowy lub wygasł. Poproś o nowy.",
        );
      }
    })();
  }, [token, router]);

  if (status === "verifying") {
    return (
      <div className="flex flex-col items-center gap-3 py-4 text-center">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
        <p className="text-sm text-muted-foreground">Potwierdzamy Twój adres email…</p>
      </div>
    );
  }

  if (status === "success") {
    return (
      <div className="space-y-4">
        <div
          role="status"
          className="flex items-start gap-3 text-sm bg-muted/50 border border-border rounded-md px-4 py-3"
        >
          <CheckCircle2 className="h-5 w-5 shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
          <div>
            <p className="font-medium text-foreground">Adres email potwierdzony</p>
            <p className="text-muted-foreground">
              Twoje konto jest aktywne (tryb do odczytu). Za chwilę przekierujemy Cię do
              logowania.
            </p>
          </div>
        </div>
        <Link
          href="/login"
          className="flex items-center justify-center gap-2 text-sm text-primary hover:text-primary/80 hover:underline underline-offset-4"
        >
          Przejdź do logowania
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div
        role="alert"
        className="flex items-start gap-3 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-4 py-3"
      >
        <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
        <div>
          <p className="font-medium">Nie udało się potwierdzić adresu</p>
          <p>{errorMsg}</p>
        </div>
      </div>
      <Link
        href="/register"
        className="flex items-center justify-center gap-2 text-sm text-primary hover:text-primary/80 hover:underline underline-offset-4"
      >
        Wróć do rejestracji
      </Link>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <AuthShell
      heading="Aktywacja konta"
      subtitle="Potwierdzamy Twój adres email w Nexus."
    >
      <Suspense
        fallback={
          <div className="text-center text-sm text-muted-foreground">Ładowanie…</div>
        }
      >
        <VerifyEmailInner />
      </Suspense>
    </AuthShell>
  );
}
