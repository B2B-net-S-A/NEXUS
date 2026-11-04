"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, Copy } from "lucide-react";

/**
 * Karta „zapisz teraz” dla sekretu pokazywanego JEDEN raz (secret klienta
 * OAuth, klucz API konta serwisowego). Serwer trzyma tylko skrót, więc po
 * zamknięciu karty sekretu nie da się odczytać — dlatego karta nie zamyka się
 * sama i nie ma jej w żadnym cache'u, tylko w stanie ekranu, który ją pokazał.
 */
export interface SecretRevealCardProps {
  title: ReactNode;
  description: ReactNode;
  secret: string;
  onClose: () => void;
  /** Dodatkowa treść pod sekretem (np. jak użyć klucza). */
  children?: ReactNode;
}

export function SecretRevealCard({
  title,
  description,
  secret,
  onClose,
  children,
}: SecretRevealCardProps) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const copy = async () => {
    if (timer.current) clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(secret);
      setCopyState("copied");
      timer.current = setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      // Schowek bywa niedostępny (strona bez HTTPS, odmowa uprawnienia) —
      // sekret dalej stoi na ekranie do zaznaczenia ręcznie.
      setCopyState("failed");
    }
  };

  return (
    <div
      role="region"
      aria-label="Sekret do zapisania"
      className="p-6 bg-warning-muted/40 border-2 border-warning/30 rounded-xl"
    >
      <div className="flex items-start gap-3 mb-4">
        <AlertCircle className="w-5 h-5 text-warning shrink-0 mt-0.5" aria-hidden />
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-foreground">{title}</h3>
          <p className="text-sm text-muted-foreground mt-1">{description}</p>
        </div>
      </div>

      <div
        data-testid="revealed-secret"
        className="bg-background border border-border rounded-md p-3 font-mono text-sm break-all select-all"
      >
        {secret}
      </div>

      {children ? <div className="mt-3">{children}</div> : null}

      {copyState === "failed" ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          Nie udało się skopiować do schowka — zaznacz sekret i skopiuj go ręcznie.
        </p>
      ) : null}

      <div className="flex gap-2 mt-4 justify-end">
        <button
          type="button"
          onClick={copy}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
        >
          {copyState === "copied" ? (
            <>
              <CheckCircle2 className="w-4 h-4" aria-hidden />
              Skopiowano
            </>
          ) : (
            <>
              <Copy className="w-4 h-4" aria-hidden />
              Skopiuj
            </>
          )}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="px-4 py-2 text-sm border border-border rounded-md hover:bg-muted"
        >
          Zamknij
        </button>
      </div>
    </div>
  );
}
