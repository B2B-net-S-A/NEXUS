"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowLeft, ArrowRight, CheckCircle2, Eye, EyeOff, MailCheck } from "lucide-react";
import { authApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FormField } from "@/components/ui/form-field";
import { AuthShell } from "@/components/blocks/AuthShell";

/** Map backend error responses to a human Polish message.
 *  NB: the backend is anti-enumeration — a duplicate email returns the same
 *  generic 201 as a new one (never 409), so there is no "email taken" branch. */
function registerErrorMessage(status: number | undefined, detail: string | undefined): string {
  const d = (detail ?? "").toLowerCase();
  if (status === 503) {
    return detail || "Rejestracja jest obecnie wyłączona. Skontaktuj się z administratorem.";
  }
  if (status === 403 || d.includes("domain_forbidden")) {
    return "Rejestracja jest dostępna tylko dla firmowych adresów email (np. @b2bnetwork.pl).";
  }
  return detail || "Nie udało się utworzyć konta. Spróbuj ponownie.";
}

function RegisterForm() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [resent, setResent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (name.trim().length < 1) {
      setError("Podaj swoje imię i nazwisko.");
      return;
    }
    if (password.length < 8) {
      setError("Hasło musi mieć co najmniej 8 znaków.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Hasła nie są identyczne.");
      return;
    }

    setLoading(true);
    try {
      await authApi.register(name.trim(), email.trim(), password);
      setDone(true);
    } catch (err: unknown) {
      const e2 = err as { response?: { status?: number; data?: { detail?: string } } };
      setError(registerErrorMessage(e2.response?.status, e2.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    try {
      await authApi.resendVerification(email.trim());
      setResent(true);
    } catch {
      // Anti-enumeration: backend always 200; ignore client-side errors.
      setResent(true);
    }
  };

  if (done) {
    return (
      <div className="space-y-4">
        <div
          role="status"
          className="flex items-start gap-3 text-sm bg-muted/50 border border-border rounded-md px-4 py-3"
        >
          <MailCheck className="h-5 w-5 shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
          <div>
            <p className="font-medium text-foreground">Sprawdź swoją skrzynkę</p>
            <p className="text-muted-foreground">
              Jeśli to nowy adres, wysłaliśmy link aktywacyjny na{" "}
              <strong>{email.trim()}</strong> — kliknij go, aby potwierdzić email i
              zalogować się (po aktywacji masz dostęp w trybie do odczytu; o szersze
              uprawnienia poproś administratora). Jeśli masz już konto z tym adresem,
              po prostu się zaloguj.
            </p>
          </div>
        </div>

        {resent ? (
          <p className="text-center text-sm text-muted-foreground inline-flex items-center justify-center gap-1.5 w-full">
            <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
            Jeśli konto czeka na potwierdzenie, wysłaliśmy nowy link.
          </p>
        ) : (
          <button
            type="button"
            onClick={handleResend}
            className="w-full text-center text-sm text-primary hover:text-primary/80 hover:underline underline-offset-4"
          >
            Nie dostałeś maila? Wyślij link ponownie
          </button>
        )}

        <Link
          href="/login"
          className="flex items-center justify-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Wróć do logowania
        </Link>
      </div>
    );
  }

  return (
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

      <FormField label="Imię i nazwisko" htmlFor="register-name" required>
        <Input
          id="register-name"
          type="text"
          autoComplete="name"
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          placeholder="Jan Kowalski"
        />
      </FormField>

      <FormField
        label="Email służbowy"
        htmlFor="register-email"
        description="Tylko adresy firmowe (np. @b2bnetwork.pl)."
        required
      >
        <Input
          id="register-email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          placeholder="jan.kowalski@b2bnetwork.pl"
        />
      </FormField>

      <FormField label="Hasło" htmlFor="register-password" description="Min. 8 znaków." required>
        <div className="relative">
          <Input
            id="register-password"
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            placeholder="••••••••"
          />
          <button
            type="button"
            onClick={() => setShowPassword((s) => !s)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label={showPassword ? "Ukryj hasło" : "Pokaż hasło"}
          >
            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </FormField>

      <FormField label="Powtórz hasło" htmlFor="register-confirm" required>
        <Input
          id="register-confirm"
          type={showPassword ? "text" : "password"}
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          required
          minLength={8}
          placeholder="••••••••"
        />
      </FormField>

      <Button type="submit" variant="primary" size="lg" loading={loading} className="w-full">
        {loading ? "Tworzenie konta…" : "Utwórz konto"}
        {!loading && <ArrowRight className="h-4 w-4" />}
      </Button>

      <div className="text-center pt-1">
        <Link
          href="/login"
          className="text-sm text-primary hover:text-primary/80 hover:underline underline-offset-4"
        >
          Masz już konto? Zaloguj się
        </Link>
      </div>
    </form>
  );
}

export default function RegisterPage() {
  return (
    <AuthShell
      heading="Załóż konto w Nexus"
      subtitle="Konto firmowe — po potwierdzeniu adresu uzyskasz dostęp w trybie do odczytu."
    >
      <Suspense
        fallback={
          <div className="text-center text-sm text-muted-foreground">Ładowanie…</div>
        }
      >
        <RegisterForm />
      </Suspense>
    </AuthShell>
  );
}
