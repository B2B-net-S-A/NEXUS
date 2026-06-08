"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { DynamindsLogo } from "@/components/brand/DynamindsLogo";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
} from "lucide-react";
import { authApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FormField } from "@/components/ui/form-field";

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
          className="flex items-start gap-3 text-sm bg-muted/50 border border-border rounded-md px-4 py-3"
        >
          <CheckCircle2 className="h-5 w-5 shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
          <div>
            <p className="font-medium text-foreground">Hasło zostało zmienione</p>
            <p className="text-muted-foreground">
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
          className="flex items-start gap-3 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-4 py-3"
        >
          <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Link jest nieprawidłowy</p>
            <p>Token ma niepoprawny format. Poproś o nowy link resetowy.</p>
          </div>
        </div>
        <Link
          href="/login/forgot-password"
          className="flex items-center justify-center gap-2 text-sm text-primary hover:text-primary/80 hover:underline underline-offset-4"
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
          className="flex items-start gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-3 py-2"
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
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label={showPassword ? "Ukryj hasło" : "Pokaż hasło"}
          >
            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
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
        className="flex items-center justify-center gap-2 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Wróć do logowania
      </Link>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-10 bg-background">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="flex items-center justify-center mb-6 text-foreground">
            <DynamindsLogo className="h-9 w-auto" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            Ustaw nowe hasło
          </h1>
          <p className="text-sm text-muted-foreground mt-1.5 text-center">
            Wybierz nowe hasło dla swojego konta w Nexus.
          </p>
        </div>

        <div className="bg-card border border-border rounded-xl shadow-sm p-6">
          <Suspense
            fallback={
              <div className="text-sm text-muted-foreground text-center">
                Ładowanie…
              </div>
            }
          >
            <ResetPasswordForm />
          </Suspense>
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">Nexus · B2B.net</p>
      </div>
    </div>
  );
}
