"use client";

import { useState } from "react";
import { Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { portalApi, trainerPortalApi } from "@/lib/api/consultant-portal";

import { PortalNotice } from "./PortalShell";

interface LoginFormProps {
  /** Panel konsultanta przyjmuje logowanie (własny włącznik). */
  consultantOpen?: boolean;
  /** Panel trenera z rynku przyjmuje logowanie (0808, własny włącznik). */
  trainerOpen?: boolean;
}

/**
 * Prośba o link. Odpowiedź serwera jest taka sama dla każdego adresu. Jeden formularz
 * dla konsultanta i trenera z rynku: adres idzie do każdego otwartego wejścia, a link
 * przychodzi tylko z tego, które zna adres.
 */
export function LoginForm({ consultantOpen = true, trainerOpen = false }: LoginFormProps) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const address = email.trim();
      const calls = [
        ...(consultantOpen ? [portalApi.requestLink(address)] : []),
        ...(trainerOpen ? [trainerPortalApi.requestLink(address)] : []),
      ];
      const results = await Promise.allSettled(calls);
      const answer = results.find(
        (result): result is PromiseFulfilledResult<{ message: string }> => result.status === "fulfilled",
      );
      if (!answer) {
        throw (results[0] as PromiseRejectedResult | undefined)?.reason ?? new Error("no_entry");
      }
      setSent(answer.value.message);
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się wysłać linku. Spróbuj ponownie za chwilę."));
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <PortalNotice title="Sprawdź skrzynkę">
        <p>{sent}</p>
      </PortalNotice>
    );
  }
  return (
    <section className="mx-auto max-w-md space-y-4 py-6">
      <div>
        <h1 className="text-2xl font-semibold">{consultantOpen ? "Strefa konsultanta" : "Panel trenera"}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {consultantOpen
            ? "Bez konta i hasła. Podaj adres, którego używasz w umowie, a wyślemy Ci link."
            : "Bez konta i hasła. Podaj adres, na który przyszło zaproszenie do panelu trenera, a wyślemy Ci link."}
        </p>
      </div>
      <form onSubmit={submit} className="space-y-3">
        <FormField label="Adres e-mail" htmlFor="portal-email">
          <Input
            id="portal-email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </FormField>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <Button type="submit" className="w-full" disabled={busy || !email.trim()}>
          <Mail aria-hidden className="size-4" /> Wyślij link
        </Button>
      </form>
    </section>
  );
}
