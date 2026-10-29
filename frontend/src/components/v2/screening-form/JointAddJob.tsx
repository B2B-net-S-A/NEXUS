"use client";

/**
 * „+ Dodaj inną rekrutację” w „Screening dla” (zgłoszenie Michała, decyzja
 * Artura 29.10.2026, wariant A). „Pasuje też do” to najwyżej 3 rekrutacje
 * ≥ 70 % — rekruter dorzuca sam tę, o której chce porozmawiać z osobą
 * („Fullstack też na backend”). Lustro „+ Dodaj inną rekrutację” DL-a
 * (`DlMatchAddJob`): otwarte rekrutacje całej firmy bez tej osoby, bez oceny,
 * Twoje zespoły na górze (serwer: `also_fits.search_open_jobs`).
 *
 * Rekrutacja, którą `joint-context` przyjąłby jako parę (`joinable`), wchodzi
 * do tej rozmowy („+ Dodaj i dołącz”); pozostała — i każda przy komplecie
 * rekrutacji w rozmowie — trafia tylko do „Nowych”. Rekruter tamtej
 * rekrutacji dostaje dzwonek. „Twój zespół” liczy serwer bez obejścia ról
 * (`in_my_team`) — od #1742 rekruter przechodzi bramkę zespołu wszędzie.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ClientReferenceTag } from "@/components/v2/jobs/JobPickName";
import {
  ALSO_FITS_SEARCH_MIN_CHARS,
  alsoFitsApi,
  alsoFitsKeys,
  type AlsoFitsManualJob,
} from "@/lib/also-fits-api";
import { apiErrorMessage } from "@/lib/api-error";
import { useDebouncedValue } from "@/lib/use-debounced-value";

/** Drugi wiersz wyniku: klient i czyj to zespół. */
export function manualJobContext(
  job: Pick<AlsoFitsManualJob, "client_name" | "in_my_team" | "delivery_lead_name">,
): string {
  const team = job.in_my_team
    ? "Twój zespół"
    : `inny zespół${job.delivery_lead_name ? ` · DL: ${job.delivery_lead_name}` : ""}`;
  return [job.client_name, team].filter(Boolean).join(" · ");
}

export interface JointAddJobProps {
  candidateId: number;
  fromJobId: number;
  /** Kotwica, pary i podpowiedzi — nie pokazujemy ich w wynikach. */
  listedIds: ReadonlySet<number>;
  onAdd: (job: AlsoFitsManualJob) => void;
  disabled?: boolean;
  /** Komplet rekrutacji w rozmowie — „dołącz” niemożliwe, „do Nowych” tak. */
  joinFull?: boolean;
}

export function JointAddJob({
  candidateId,
  fromJobId,
  listedIds,
  onAdd,
  disabled = false,
  joinFull = false,
}: JointAddJobProps) {
  const [open, setOpen] = useState(false);
  const [phrase, setPhrase] = useState("");
  const debounced = useDebouncedValue(phrase.trim(), 250);
  const search = useQuery({
    queryKey: alsoFitsKeys.search(fromJobId, candidateId, debounced),
    queryFn: () => alsoFitsApi.search(candidateId, fromJobId, debounced),
    enabled: open && debounced.length >= ALSO_FITS_SEARCH_MIN_CHARS,
    staleTime: 60 * 1000,
  });
  const results = (search.data ?? []).filter((j) => !listedIds.has(j.job_id));

  if (!open) {
    return (
      <button
        type="button"
        className="mt-2 flex items-center gap-1 text-xs font-semibold text-primary hover:underline disabled:opacity-50"
        onClick={() => setOpen(true)}
        disabled={disabled}
        data-testid="joint-add-open"
      >
        <Plus className="size-3.5" aria-hidden /> Dodaj inną rekrutację
      </button>
    );
  }

  const close = () => {
    setOpen(false);
    setPhrase("");
  };

  return (
    <div className="mt-2 space-y-1.5 rounded-lg border border-border bg-background p-2" data-testid="joint-add">
      <div className="flex items-center gap-2">
        <input
          autoFocus
          aria-label="Szukaj otwartej rekrutacji"
          className="h-8 w-0 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-xs"
          placeholder="Numer requestu, nazwa albo klient"
          value={phrase}
          onChange={(e) => setPhrase(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") close();
          }}
          disabled={disabled}
        />
        <button type="button" className="text-xs font-medium text-muted-foreground hover:underline" onClick={close}>
          Zamknij
        </button>
      </div>
      {debounced.length < ALSO_FITS_SEARCH_MIN_CHARS ? (
        <p className="text-[11px] text-muted-foreground">
          Otwarte rekrutacje całej firmy, w których tej osoby jeszcze nie ma. Twoje zespoły na górze.
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
        <ul className="max-h-56 divide-y divide-border/60 overflow-y-auto">
          {results.map((job) => {
            const join = job.joinable && !joinFull;
            return (
              <li key={job.job_id} className="flex items-center gap-2 py-1.5" data-testid={`joint-add-${job.job_id}`}>
                <span className="min-w-0 flex-1">
                  <span
                    className="block truncate text-xs font-semibold text-foreground"
                    title={[job.client_reference, job.title, job.client_name].filter(Boolean).join(" · ")}
                  >
                    <ClientReferenceTag className="mr-1.5 align-text-bottom" reference={job.client_reference} />
                    {job.title}
                  </span>
                  <span className="block truncate text-[11px] text-muted-foreground">{manualJobContext(job)}</span>
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 shrink-0 px-2 text-xs"
                  disabled={disabled}
                  onClick={() => {
                    onAdd(job);
                    close();
                  }}
                >
                  {join ? "+ Dodaj i dołącz" : "+ Dodaj do Nowych"}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-[11px] text-muted-foreground">
        „Dodaj i dołącz” — osoba trafia do „Nowych” tamtej rekrutacji z Twoją rezerwacją 12 h i wchodzi do tej rozmowy.
        W innym zespole — tylko do „Nowych”, jej rekruter dostaje dzwonek.
      </p>
    </div>
  );
}
