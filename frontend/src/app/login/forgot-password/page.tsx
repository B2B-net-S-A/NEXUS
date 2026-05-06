"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, Send, Sparkles } from "lucide-react";
import { authApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FormField } from "@/components/ui/form-field";

/**
 * Forgot-password page — niezalogowany user wpisuje email, dostaje
 * generic-success message niezależnie czy konto istnieje (anti-enumeration
 * po stronie backendu). Backend zawsze zwraca 200 z tym samym tekstem.
 */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await authApi.forgotPassword(email);
      setSent(true);
    } catch (err: unknown) {
      // Rate limit (429) lub błąd walidacji — pokaż generic message.
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail;
      setError(detail ?? "Nie udało się wysłać linka. Spróbuj ponownie za chwilę.");
    } finally {
      setLoading(false);
    }
  };

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
            Zapomniałeś hasła?
          </h1>
          <p className="text-sm text-[hsl(var(--text-muted))] mt-1 text-center">
            Wpisz swój email — wyślemy Ci link do ustawienia nowego hasła.
          </p>
        </div>

        <div className="bg-[hsl(var(--bg-surface))] border border-[hsl(var(--border-subtle))] rounded-v2-l shadow-v2-xl p-6">
          {sent ? (
            <div className="space-y-4">
              <div
                role="status"
                className="flex items-start gap-3 text-sm text-[hsl(var(--text-body))] bg-emerald-50 border border-emerald-200 rounded-v2-s px-4 py-3"
              >
                <CheckCircle2 className="h-5 w-5 shrink-0 mt-0.5 text-emerald-600" />
                <div className="space-y-1">
                  <p className="font-medium text-emerald-900">
                    Sprawdź skrzynkę email
                  </p>
                  <p className="text-emerald-800">
                    Jeśli konto z adresem <strong>{email}</strong> istnieje, wysłaliśmy
                    link do ustawienia nowego hasła. Link jest ważny przez 60 minut.
                  </p>
                  <p className="text-emerald-800/80 text-xs">
                    Mail nie przyszedł? Sprawdź folder spam lub skontaktuj się z administratorem.
                  </p>
                </div>
              </div>
              <Link
                href="/login"
                className="flex items-center justify-center gap-2 text-sm text-[hsl(var(--accent))] hover:underline"
              >
                <ArrowLeft className="h-4 w-4" />
                Wróć do logowania
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div
                  role="alert"
                  className="text-sm text-[hsl(var(--accent-strong))] bg-[hsl(var(--accent-soft))] border border-[hsl(var(--accent))]/20 rounded-v2-s px-3 py-2"
                >
                  {error}
                </div>
              )}

              <FormField label="Email" htmlFor="forgot-email" required>
                <Input
                  id="forgot-email"
                  type="email"
                  autoComplete="email"
                  autoFocus
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  placeholder="rekruter@b2bnet.pl"
                />
              </FormField>

              <Button
                type="submit"
                variant="primary"
                size="lg"
                loading={loading}
                className="w-full"
              >
                {loading ? "Wysyłanie…" : "Wyślij link resetowy"}
                {!loading && <Send className="h-4 w-4" />}
              </Button>

              <Link
                href="/login"
                className="flex items-center justify-center gap-2 text-sm text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent))] hover:underline"
              >
                <ArrowLeft className="h-4 w-4" />
                Wróć do logowania
              </Link>
            </form>
          )}
        </div>

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
