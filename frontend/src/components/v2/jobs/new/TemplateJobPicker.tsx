"use client";

/**
 * „Wypełnij z: Inna rekrutacja” na `/jobs/new` (D2, 10.10.2026) — wybór
 * rekrutacji, z której formularz bierze wymagania, warunki i pytania.
 *
 * Do tej daty szablon dało się wskazać tylko linkiem `?from=<id>` z historii
 * requestów albo banerem podobnych requestów (który pojawia się dopiero po
 * wpisaniu roli). Lista szuka w rekrutacjach wybranego klienta, także
 * zamkniętych — to one są najczęściej wzorem; „Także inni klienci” zdejmuje
 * zawężenie. `JobPicker` się tu nie nadaje: pokazuje tylko otwarte i nie
 * filtruje po kliencie.
 */

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { jobsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatIsoDatePl } from "@/lib/date-pl";
import { jobClientTitle, jobDisplayTitle } from "@/lib/job-names";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";

/** Wiersz `GET /api/jobs` — tylko pola, które pokazuje lista. */
export interface TemplateJobOption {
  id: number;
  title: string;
  working_title?: string | null;
  client_name?: string | null;
  status?: string | null;
  opened_at?: string | null;
  created_at?: string | null;
}

interface TemplateJobPickerProps {
  clientId: number;
  /** Rekrutacja już użyta jako szablon — wiersz mówi to zamiast przycisku. */
  usedJobId: number | null;
  /** Rekrutacja, której dane właśnie się wczytują. */
  busyJobId: number | null;
  onPick: (job: TemplateJobOption) => void;
  disabled?: boolean;
  /** Harness `/preview/new-job`: gotowa lista, zero zapytań. */
  seed?: TemplateJobOption[];
}

const PAGE_SIZE = 20;

function statusLabel(status: string | null | undefined): string | null {
  if (status === "closed") return "zamknięta";
  if (status === "published") return "w toku";
  return null;
}

export function TemplateJobPicker({
  clientId,
  usedJobId,
  busyJobId,
  onPick,
  disabled = false,
  seed,
}: TemplateJobPickerProps) {
  const ids = { search: useId(), all: useId() };
  const [text, setText] = useState("");
  const [allClients, setAllClients] = useState(false);
  const q = useDebouncedValue(text.trim(), 250);

  const query = useQuery({
    queryKey: ["new-job-template-jobs", allClients ? null : clientId, q],
    enabled: seed == null,
    staleTime: 30_000,
    queryFn: () =>
      jobsApi
        .list({
          q: q || undefined,
          // Jedna wartość, nie tablica: `jobsApi.list` nie ustawia serializera
          // parametrów, więc tablica poszłaby jako `client_id[]`, a serwer
          // takiego pola nie zna — lista pokazałaby wszystkich klientów.
          client_id: allClients ? undefined : clientId,
          page_size: PAGE_SIZE,
        })
        .then((r) => r.data as { items?: TemplateJobOption[]; total?: number }),
  });

  const items = seed ?? query.data?.items ?? [];
  const total = seed ? seed.length : (query.data?.total ?? items.length);
  const loaded = seed != null || query.isSuccess;

  return (
    <div className="flex flex-col gap-3" data-testid="new-job-template-picker">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="relative min-w-0 flex-1 basis-64">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            id={ids.search}
            aria-label="Szukaj rekrutacji-szablonu"
            placeholder="Tytuł albo numer zapytania…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="pl-9"
          />
        </div>
        <label
          htmlFor={ids.all}
          className="inline-flex cursor-pointer items-center gap-2 text-sm text-foreground"
        >
          <Checkbox
            id={ids.all}
            checked={allClients}
            onCheckedChange={(checked) => setAllClients(checked === true)}
          />
          Także inni klienci
        </label>
      </div>

      {query.isError && seed == null ? (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(query.error, "Nie udało się wczytać rekrutacji.")}{" "}
          <button type="button" className="font-medium underline" onClick={() => void query.refetch()}>
            Ponów
          </button>
        </p>
      ) : !loaded ? (
        <p role="status" className="text-sm text-muted-foreground">
          Wczytuję rekrutacje…
        </p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {allClients
            ? "Brak rekrutacji pasujących do frazy."
            : "Ten klient nie ma rekrutacji pasujących do frazy — zaznacz „Także inni klienci”."}
        </p>
      ) : (
        <>
          <ul className="flex max-h-56 flex-col divide-y divide-border overflow-y-auto rounded-lg border border-border">
            {items.map((job) => {
              const title = jobDisplayTitle(job);
              const clientTitle = jobClientTitle(job);
              const opened = job.opened_at ?? job.created_at;
              const meta = [
                allClients ? job.client_name : null,
                clientTitle,
                statusLabel(job.status),
                opened ? formatIsoDatePl(opened) : null,
              ].filter(Boolean);
              return (
                <li key={job.id} className="flex items-center justify-between gap-3 px-3 py-2">
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-foreground">{title}</span>
                    {meta.length > 0 ? (
                      <span className="block truncate text-xs text-muted-foreground">
                        {meta.join(" · ")}
                      </span>
                    ) : null}
                  </span>
                  {usedJobId === job.id ? (
                    <span className="shrink-0 text-xs font-medium text-success-muted-foreground">
                      Użyto jako szablon
                    </span>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="shrink-0"
                      disabled={disabled || (busyJobId != null && busyJobId !== job.id)}
                      loading={busyJobId === job.id}
                      aria-label={`Użyj jako szablon: ${title}`}
                      onClick={() => onPick(job)}
                    >
                      Użyj jako szablon
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
          {total > items.length ? (
            <p className="text-xs text-muted-foreground">
              Pokazano {items.length} z {total} — zawęź frazą, żeby znaleźć starszą rekrutację.
            </p>
          ) : null}
        </>
      )}
      <p className="text-xs text-muted-foreground">
        Szablon wypełnia tylko puste pola. Rola i nazwa od klienta zostają do wpisania — nowa
        rekrutacja nie udaje starej.
      </p>
    </div>
  );
}
