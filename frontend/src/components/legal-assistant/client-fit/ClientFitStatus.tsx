"use client";

// Stan sprawdzenia, gdy nie ma listy ustaleń do pokazania: w toku, brak
// modelu, awaria, brak umowy ramowej z treścią albo jeszcze nie sprawdzono.
// Żaden z tych stanów nie może wyglądać jak „wszystko zgodne”.

import { Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ClientFitResponse } from "@/lib/api/legalClientFit";
import { formatDateTimePl } from "@/lib/date-pl";

import { useRecheck } from "./parts";

export function ClientFitStatusNote({ data }: { data: ClientFitResponse }) {
  const recheck = useRecheck(data.client_id);
  const action = (label: string) => (
    <Button
      size="sm"
      variant="outline"
      className="h-7 text-[12px]"
      loading={recheck.isPending}
      disabled={recheck.isPending}
      onClick={() => recheck.mutate()}
    >
      <RefreshCw className="h-3 w-3" aria-hidden /> {label}
    </Button>
  );
  switch (data.status) {
    case "queued":
    case "running":
      return (
        <p role="status" className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
          Sprawdzam w tle umowę ramową i aneksy klienta z naszym wzorem — wynik pojawi się tu sam.
        </p>
      );
    case "unavailable":
      return (
        <div className="space-y-1">
          <p className="text-[13px] font-medium text-warning-muted-foreground">Sprawdzenie niedostępne</p>
          <p className="text-[12.5px] text-muted-foreground">
            {data.status_message ??
              "Asystent nie może teraz porównać umów. Wymagania klienta sprawdź w umowie ramowej samodzielnie."}
          </p>
        </div>
      );
    case "failed":
      return (
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-medium text-destructive">Sprawdzenie się nie udało</p>
            <p className="text-[12.5px] text-muted-foreground">
              {data.status_message ?? "Spróbuj ponownie za kilka minut."}
            </p>
          </div>
          {action("Sprawdź ponownie")}
        </div>
      );
    case "no_contract":
      return (
        <p className="text-[12.5px] text-muted-foreground">
          {data.status_message ??
            "Ten klient nie ma w NEXUSIE umowy ramowej ani aneksu z treścią do porównania."}
        </p>
      );
    case "never":
      return (
        <div className="flex flex-wrap items-center gap-2">
          <p className="min-w-0 flex-1 text-[12.5px] text-muted-foreground">
            Umów z tym klientem jeszcze nie sprawdzano z naszym wzorem B2B.
          </p>
          {action("Sprawdź teraz")}
        </div>
      );
    default:
      return null;
  }
}

/** „Umowa klienta zmieniła się od sprawdzenia” — wynik jest, ale stary. */
export function ClientFitStaleNote({ data }: { data: ClientFitResponse }) {
  const recheck = useRecheck(data.client_id);
  if (!data.stale) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-warning/25 bg-warning-muted px-3 py-1.5">
      <p className="min-w-0 flex-1 text-[12.5px] text-warning-muted-foreground">
        Umowa klienta zmieniła się od sprawdzenia
        {data.checked_at ? ` (${formatDateTimePl(data.checked_at)})` : ""} — wynik może być nieaktualny.
      </p>
      <Button
        size="sm"
        variant="outline"
        className="h-7 text-[12px]"
        loading={recheck.isPending}
        disabled={recheck.isPending}
        onClick={() => recheck.mutate()}
      >
        <RefreshCw className="h-3 w-3" aria-hidden /> Sprawdź ponownie
      </Button>
    </div>
  );
}
