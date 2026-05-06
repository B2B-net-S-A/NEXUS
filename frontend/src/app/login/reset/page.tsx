"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Sparkles,
} from "lucide-react";
import { authApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FormField } from "@/components/ui/form-field";

/**
 * Reset-password page — niezalogowany user trafia tu z linka mailowego
 * (?token=xxx). Token jest sprawdzany dopiero przy submit (server-side).
 * Token z URL trzymamy w state, ale nie usuwamy z URL — Next.js
 * useSearchParams nie ma natywnego "replace state" przed user-action.
 */

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  // Token o złej długości — niech user kliknie "wyślij nowy link".
  const tokenInvalid = token.length !== 64;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (newPassword.length < 8) {
      setError("Hasło musi mieć co najmniej 8 znaków.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Hasła nie są identyczne.");
      return;
    }

    setLoading(true);
    try {
      await authApi.resetPasswordWithToken(token, newPassword);
      setDone(true);
      // Po 2s redirect do /login. Dajemy chwilę na przeczytanie sukcesu.
      setTimeout(() => router.push("/login"), 2000);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail;
      setError(
        detail ??
          "Nie udało się ustawić nowego hasła. Link mógł wygasnąć — poproś o nowy."
      );
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <div className="space-y-4">
        <div
          role="status"
          className="flex items-start gap-3 text-sm text-emerald-900 bg-emerald-50 border border-emerald-200 rounded-v2-s px-4 py-3"
        >
          <CheckCircle2 className="h-5 w-5 shrink-0 mt-0.5 text-emerald-600" />
          <div>
            <p className="font-medium">Hasło zostało zmienione</p>
            <p className="text-emerald-800/80">
              Za chwilę przekierujemy Cię do strony logowania.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (tokenInvalid) {
    return (
      <div className="space-y-4">
        <div
          role="alert"
          className="flex items-start gap-3 text-sm text-[hsl(var(--accent-strong))] bg-[hsl(var(--accent-soft))] border border-[hsl(var(--accent))]/20 rounded-v2-s px-4 py-3"
        >
          <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Link jest nieprawidłowy</p>
            <p>
              Token w adresie URL ma niepoprawny format. Poproś o nowy link
              resetowy.
            </p>
          </div>
        </div>
        <Link
          href="/login/forgot-password"
          className="flex items-center justify-center gap-2 text-sm text-[hsl(var(--accent))] hover:underline"
        >
          Wyślij nowy link resetowy
        </Link>
      </div>
    );
  }

  return (
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

      <FormField
        label="Nowe hasło"
        htmlFor="reset-new-password"
        description="Min. 8 znaków."
        required
      >
        <div className="relative">
          <Input
            id="reset-new-password"
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
            autoFocus
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            minLength={8}
            placeholder="••••••••"
          />
          <button
            type="button"
            onClick={() => setShowPassword((s) => !s)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text-body))]"
            aria-label={showPassword ? "Ukryj hasło" : "Pokaż hasło"}
          >
            {showPassword ? (
              <EyeOff className="h-4 w-4" />
            ) : (
              <Eye className="h-4 w-4" />
            )}
          </button>
        </div>
      </FormField>

      <FormField
        label="Powtórz nowe hasło"
        htmlFor="reset-confirm-password"
        required
      >
        <Input
          id="reset-confirm-password"
          type={showPassword ? "text" : "password"}
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          required
          minLength={8}
          placeholder="••••••••"
        />
      </FormField>

      <Button
        type="submit"
        variant="primary"
        size="lg"
        loading={loading}
        className="w-full"
      >
        {loading ? "Zapisywanie…" : "Ustaw nowe hasło"}
        {!loading && <KeyRound className="h-4 w-4" />}
      </Button>

      <Link
        href="/login"
        className="flex items-center justify-center gap-2 text-sm text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent))] hover:underline"
      >
        <ArrowLeft className="h-4 w-4" />
        Wróć do logowania
      </Link>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <div
      data-ui="v2"
      className="min-h-screen flex items-center justify-center px-4 py-10 bg-[hsl(var(--bg-canvas))]"
    >
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 80% 60% at 50% 10%, hsl(var(--accent-soft)) 0%, transparent 60%)",
        }}
        aria-hidden="true"
      />

      <div className="relative z-10 w-full max-w-md">
        <div className="flex flex-col items-center mb-6">
          <div className="w-14 h-14 rounded-v2-m bg-[hsl(var(--bg-chrome))] text-[hsl(var(--accent))] flex items-center justify-center shadow-v2-l mb-4">
            <span className="font-display font-extrabold text-2xl">N</span>
          </div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[hsl(var(--accent))]">
            B2B.net · Nexus
          </p>
          <h1 className="font-display text-3xl font-extrabold tracking-[-0.025em] text-[hsl(var(--text-title))] mt-1">
            Ustaw nowe hasło
          </h1>
          <p className="text-sm text-[hsl(var(--text-muted))] mt-1 text-center">
            Wybierz nowe hasło dla swojego konta w NEXUS.
          </p>
        </div>

        <div className="bg-[hsl(var(--bg-surface))] border border-[hsl(var(--border-subtle))] rounded-v2-l shadow-v2-xl p-6">
          <Suspense
            fallback={
              <div className="text-sm text-[hsl(var(--text-muted))] text-center">
                Ładowanie…
              </div>
            }
          >
            <ResetPasswordForm />
          </Suspense>
        </div>

        <div className="mt-6 flex items-center justify-center gap-2 text-xs text-[hsl(var(--text-muted))]">
          <Sparkles className="h-3 w-3 text-[hsl(var(--accent))]" />
          <span>
            Nexus ·{" "}
            <strong className="text-[hsl(var(--text-title))]">Define tomorrow.</strong>
          </span>
        </div>
      </div>
    </div>
  );
}
