"use client";

import * as React from "react";
import { AlertTriangle, Ban, RefreshCw, SearchX } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ViewState } from "@/lib/view-state";

/**
 * Jednolity komunikat dla stanów blokujących (audyt F-20): `forbidden`,
 * `not_found`, `error`. Celowo NIE obsługuje `empty` — pusty stan jest
 * specyficzny dla ekranu (ma własną ikonę i zwykle akcję „dodaj pierwszy"),
 * a mieszanie go z brakiem uprawnień to właśnie usterka, którą zamykamy.
 */
export type BlockingViewState = Extract<
  ViewState,
  "forbidden" | "not_found" | "error"
>;

const COPY: Record<
  BlockingViewState,
  { icon: React.ComponentType<{ className?: string }>; title: string; description: string }
> = {
  forbidden: {
    icon: Ban,
    title: "Brak uprawnień",
    description:
      "Twoja rola nie ma dostępu do tych danych. To nie znaczy, że są puste — poproś administratora o rozszerzenie uprawnień.",
  },
  not_found: {
    icon: SearchX,
    title: "Nie znaleziono",
    description: "Ten rekord nie istnieje albo został usunięty.",
  },
  error: {
    icon: AlertTriangle,
    title: "Nie udało się pobrać danych",
    description:
      "Wystąpił błąd po stronie serwera. Dane mogą istnieć — spróbuj ponownie za chwilę.",
  },
};

export interface QueryStateNoticeProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  state: BlockingViewState;
  /** Nadpisz domyślny opis (np. kontekst konkretnego ekranu). */
  description?: string;
  /** Pokazywane tylko dla `error` — pusty stan i 403 nie mają czego ponawiać. */
  onRetry?: () => void;
}

export const QueryStateNotice = React.forwardRef<
  HTMLDivElement,
  QueryStateNoticeProps
>(({ state, description, onRetry, className, ...props }, ref) => {
  const { icon: Icon, title, description: fallback } = COPY[state];
  return (
    <div
      ref={ref}
      role={state === "error" ? "alert" : "status"}
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-6 py-10 text-center",
        className
      )}
      {...props}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon className="h-6 w-6" aria-hidden="true" />
      </div>
      <p className="mt-2 text-sm font-medium text-foreground">{title}</p>
      <p className="max-w-sm text-sm text-muted-foreground">
        {description ?? fallback}
      </p>
      {state === "error" && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Spróbuj ponownie
        </button>
      ) : null}
    </div>
  );
});
QueryStateNotice.displayName = "QueryStateNotice";
