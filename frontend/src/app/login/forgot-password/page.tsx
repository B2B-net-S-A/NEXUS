"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, Send } from "lucide-react";
import { authApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FormField } from "@/components/ui/form-field";

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
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail;
      setError(detail ?? "Nie udało się wysłać linka. Spróbuj ponownie za chwilę.");
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
            Zapomniałeś hasła?
          </h1>
          <p className="text-sm text-muted-foreground mt-1.5 text-center">
            Wpisz email — wyślemy link do ustawienia nowego hasła.
          </p>
        </div>

        <div className="bg-card border border-border rounded-xl shadow-sm p-6">
          {sent ? (
            <div className="space-y-4">
              <div
                role="status"
                className="flex items-start gap-3 text-sm text-foreground bg-muted/50 border border-border rounded-md px-4 py-3"
              >
                <CheckCircle2 className="h-5 w-5 shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
                <div className="space-y-1">
                  <p className="font-medium">Sprawdź skrzynkę email</p>
                  <p className="text-muted-foreground">
                    Jeśli konto z adresem <strong className="text-foreground">{email}</strong> istnieje, wysłaliśmy
                    link do ustawienia nowego hasła. Link ważny 60 minut.
                  </p>
                  <p className="text-muted-foreground text-xs">
                    Mail nie przyszedł? Sprawdź spam lub skontaktuj się z administratorem.
                  </p>
                </div>
              </div>
              <Link
                href="/login"
                className="flex items-center justify-center gap-2 text-sm text-primary hover:text-primary/80 hover:underline underline-offset-4"
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
                  className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-3 py-2"
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
                className="flex items-center justify-center gap-2 text-sm text-muted-foreground hover:text-foreground"
              >
                <ArrowLeft className="h-4 w-4" />
                Wróć do logowania
              </Link>
            </form>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">Nexus · B2B.net</p>
      </div>
    </div>
  );
}
