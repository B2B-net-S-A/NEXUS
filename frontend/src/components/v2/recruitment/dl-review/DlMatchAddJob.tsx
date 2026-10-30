"use client";

/**
 * „+ Dodaj inną rekrutację” w „Pasuje też do Twoich rekrutacji” (prośba Igora
 * 27.10.2026): DL ma osoby, które pasują do kilku requestów, a ocena Nexusa
 * nie zawsze je podsuwa. Szuka we wszystkich otwartych rekrutacjach firmy
 * (decyzja Artura 27.10.2026; jego portfel na górze, przy cudzej — jej DL)
 * i dodaje wiersz od razu zaznaczony.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";

import { apiErrorMessage } from "@/lib/api-error";
import { dlMatchApi, dlMatchKeys, type DlMatchJob } from "@/lib/dl-match-api";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const MIN_CHARS = 2;

/** Cudza rekrutacja: czyja — DL dostanie dzwonek po wysyłce. */
export function otherLeadLabel(job: Pick<DlMatchJob, "delivery_lead_name">): string {
  return job.delivery_lead_name ? `DL: ${job.delivery_lead_name}` : "poza Twoim portfelem";
}

export interface DlMatchAddJobProps {
  candidateId: number;
  fromJobId: number;
  /** Już na liście — nie pokazujemy ich w wynikach. */
  listedIds: ReadonlySet<number>;
  onAdd: (job: DlMatchJob) => void;
  disabled?: boolean;
}

export function DlMatchAddJob({ candidateId, fromJobId, listedIds, onAdd, disabled = false }: DlMatchAddJobProps) {
  const [open, setOpen] = useState(false);
  const [phrase, setPhrase] = useState("");
  const debounced = useDebouncedValue(phrase.trim(), 250);
  const search = useQuery({
    queryKey: dlMatchKeys.search(fromJobId, candidateId, debounced),
    queryFn: () => dlMatchApi.search(candidateId, fromJobId, debounced),
    enabled: open && debounced.length >= MIN_CHARS,
    staleTime: 60 * 1000,
  });
  const results = (search.data ?? []).filter((j) => !listedIds.has(j.job_id));

  if (!open) {
    return (
      <button
        type="button"
        className="flex items-center gap-1 text-[11px] font-medium text-primary hover:underline disabled:opacity-50"
        onClick={() => setOpen(true)}
        disabled={disabled}
        data-testid="dl-match-add-open"
        data-tour="dl-review.match.add-job"
      >
        <Plus className="size-3" aria-hidden /> Dodaj inną rekrutację
      </button>
    );
  }

  return (
    <div className="space-y-1 rounded-md border border-border bg-background p-2" data-testid="dl-match-add">
      <div className="flex items-center gap-2">
        <input
          autoFocus
          aria-label="Szukaj otwartej rekrutacji"
          className="h-8 w-0 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-xs"
          placeholder="Numer requestu, nazwa albo klient"
          value={phrase}
          onChange={(e) => setPhrase(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
          }}
          disabled={disabled}
        />
        <button
          type="button"
          className="text-[11px] font-medium text-muted-foreground hover:underline"
          onClick={() => {
            setOpen(false);
            setPhrase("");
          }}
        >
          Zamknij
        </button>
      </div>
      {debounced.length < MIN_CHARS ? (
        <p className="text-[11px] text-muted-foreground">
          Otwarte rekrutacje całej firmy, w których tej osoby jeszcze nie ma. Twoje na górze.
        </p>
      ) : search.isLoading ? (
        <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden /> Szukam…
        </p>
      ) : search.isError ? (
        <p role="alert" className="text-[11px] text-destructive">
          {apiErrorMessage(search.error, "Nie udało się wyszukać rekrutacji.")}
        </p>
      ) : search.isSuccess && results.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">
          Brak otwartej rekrutacji „{debounced}” albo osoba już w niej jest.
        </p>
      ) : (
        <ul className="max-h-48 divide-y divide-border/60 overflow-y-auto">
          {results.map((job) => {
            const name = [job.client_reference, job.title].filter(Boolean).join(" · ");
            return (
              <li key={job.job_id}>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded px-1 py-1.5 text-left hover:bg-muted disabled:opacity-50"
                  onClick={() => {
                    onAdd(job);
                    setPhrase("");
                    setOpen(false);
                  }}
                  disabled={disabled || !job.sendable}
                  data-testid={`dl-match-add-${job.job_id}`}
                >
                  <span className="min-w-0 flex-1 truncate text-xs text-foreground" title={name}>
                    {name}
                    {job.client_name ? <span className="text-muted-foreground"> · {job.client_name}</span> : null}
                  </span>
                  {job.in_portfolio === false ? (
                    <span className="shrink-0 rounded-full bg-muted px-1.5 text-[11px] text-muted-foreground">
                      {otherLeadLabel(job)}
                    </span>
                  ) : null}
                  <span className="shrink-0 text-[11px] text-muted-foreground">
                    {job.sendable ? (job.destination === "cpro" ? "→ kolejka Cpro" : "→ CV wysłane") : "szablon bez etapu wysyłki"}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
