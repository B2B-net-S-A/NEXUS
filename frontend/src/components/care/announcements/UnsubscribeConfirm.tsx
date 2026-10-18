"use client";

/**
 * Formularz `/wypis/{token}` (O12): wypis konsultanta z komunikatów
 * informacyjnych. Strona niczego nie zmienia przy otwarciu — skanery linków
 * w poczcie otwierają adresy same — wypis to dopiero POST po kliknięciu.
 * Publiczne API przez zwykły `fetch` (nigdy instancja axios z sesją).
 */
import { useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";

function browserApiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

const FALLBACK = "Nie udało się zapisać wypisu. Spróbuj ponownie za chwilę.";

interface UnsubscribeConfirmProps {
  token: string;
  unsubscribed: boolean;
}

export function UnsubscribeConfirm({ token, unsubscribed }: UnsubscribeConfirmProps) {
  const [done, setDone] = useState(unsubscribed);
  const [justNow, setJustNow] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSending(true);
    setError(null);
    try {
      const res = await fetch(
        `${browserApiBase()}/api/public/consultant-mail/unsubscribe/${encodeURIComponent(token)}`,
        { method: "POST" },
      );
      if (!res.ok) {
        let data: unknown;
        try {
          data = await res.json();
        } catch {
          data = undefined;
        }
        setError(apiErrorMessage({ response: { status: res.status, data } }, FALLBACK));
        return;
      }
      setDone(true);
      setJustNow(true);
    } catch {
      setError(FALLBACK);
    } finally {
      setSending(false);
    }
  };

  if (done) {
    return (
      <div role="status" className="flex items-start gap-3 rounded-lg border border-border bg-card p-5">
        <CheckCircle2 className="mt-0.5 h-5 w-5 text-success" aria-hidden />
        <div className="space-y-1">
          <p className="font-medium">
            {justNow ? "Wypisano z wiadomości informacyjnych." : "Jesteś już wypisany z wiadomości informacyjnych."}
          </p>
          <p className="text-sm text-muted-foreground">
            Wiadomości obowiązkowe — w sprawach umowy, rozliczeń i bezpieczeństwa — będą dalej
            przychodzić. Jeśli zmienisz zdanie, odpisz na dowolny nasz mail.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-lg border border-border bg-card p-5">
      <p className="text-sm">
        Nie będziemy wysyłać Ci wiadomości informacyjnych (wydarzenia, życzenia). Wiadomości
        obowiązkowe — w sprawach umowy, rozliczeń i bezpieczeństwa — będą dalej przychodzić.
      </p>
      <Button loading={sending} onClick={() => void submit()}>
        Wypisz mnie
      </Button>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
