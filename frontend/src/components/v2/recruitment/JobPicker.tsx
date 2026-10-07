"use client";

/**
 * Wybór rekrutacji — jeden komponent dla wszystkich miejsc, w których rekruter
 * wskazuje „do której rekrutacji” (dodanie z listy kandydatów, z Talent Radaru,
 * wyszukiwarka, porównanie).
 *
 * Sekcje w kolejności, w jakiej rekruter ich szuka: „Moje otwarte”, „Ostatnio
 * otwierane” (pasek kart rekrutacji), a po wpisaniu frazy — wyniki szukania.
 *
 * Wyszukiwanie obejmuje WSZYSTKIE otwarte rekrutacje: rekruter dodaje
 * i przepina kandydatów także tam, gdzie nie jest w zespole (decyzja Artura
 * 07.10.2026; serwer nie wymaga członkostwa od 23.09.2026). „Moje otwarte”
 * to tylko skrót na górze.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Search } from "lucide-react";

import { jobsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { useTabsStore } from "@/store/tabs";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface JobPickerJob {
  id: number;
  title: string;
  client_name?: string | null;
}

interface JobPickerProps {
  value: JobPickerJob | null;
  onChange: (job: JobPickerJob) => void;
  /** Etykieta pola szukania (dostępność). */
  label?: string;
  className?: string;
}

interface JobListResponse {
  items: JobPickerJob[];
  total?: number;
}

const MINE_PARAMS = { mine: true, open_only: true, page_size: 20 } as const;

function JobRow({
  job,
  selected,
  onSelect,
}: {
  job: JobPickerJob;
  selected: boolean;
  onSelect: (job: JobPickerJob) => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(job)}
        aria-pressed={selected}
        className={cn(
          "flex w-full items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          selected && "border-primary bg-primary/5",
        )}
      >
        <span className="min-w-0">
          <span className="block truncate font-medium text-foreground">{job.title}</span>
          {job.client_name ? (
            <span className="block truncate text-xs text-muted-foreground">{job.client_name}</span>
          ) : null}
        </span>
        {selected ? <Check className="h-4 w-4 shrink-0 text-primary" aria-hidden /> : null}
      </button>
    </li>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

export function JobPicker({ value, onChange, label = "Szukaj rekrutacji", className }: JobPickerProps) {
  const [text, setText] = useState("");
  const q = useDebouncedValue(text.trim(), 250);

  const mine = useQuery({
    queryKey: ["job-picker", "mine"],
    queryFn: () => jobsApi.list(MINE_PARAMS).then((r) => r.data as JobListResponse),
    staleTime: 60_000,
  });

  const search = useQuery({
    queryKey: ["job-picker", "search", q],
    queryFn: () =>
      jobsApi
        .list({ q, page_size: 20, open_only: true })
        .then((r) => r.data as JobListResponse),
    enabled: q.length > 0,
    staleTime: 30_000,
  });

  const tabs = useTabsStore((s) => s.tabs);
  const recent = useMemo(
    () =>
      tabs
        .filter((t) => t.type === "job")
        .map((t) => ({ id: t.entityId, title: t.title }))
        .slice(0, 5),
    [tabs],
  );

  const mineItems = mine.data?.items ?? [];

  return (
    <div className={cn("space-y-4", className)}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input
          id="job-picker-search"
          aria-label={label}
          placeholder="Tytuł albo klient…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="pl-9"
        />
      </div>

      {q.length > 0 ? (
        <Section title="Wyniki">
          {search.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(search.error, "Nie udało się wyszukać rekrutacji.")}
            </p>
          ) : !search.isSuccess ? (
            <p role="status" className="text-sm text-muted-foreground">Szukam…</p>
          ) : search.data.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Brak otwartych rekrutacji pasujących do frazy.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {search.data.items.map((job) => (
                <JobRow key={job.id} job={job} selected={value?.id === job.id} onSelect={onChange} />
              ))}
            </ul>
          )}
        </Section>
      ) : (
        <>
          <Section title="Moje otwarte">
            {mine.isError ? (
              <p role="alert" className="text-sm text-destructive">
                {apiErrorMessage(mine.error, "Nie udało się wczytać rekrutacji.")}
              </p>
            ) : !mine.isSuccess ? (
              <p role="status" className="text-sm text-muted-foreground">Wczytuję rekrutacje…</p>
            ) : mineItems.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nie masz otwartych rekrutacji. Wpisz frazę, żeby wyszukać.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {mineItems.map((job) => (
                  <JobRow key={job.id} job={job} selected={value?.id === job.id} onSelect={onChange} />
                ))}
              </ul>
            )}
          </Section>
          {recent.length > 0 ? (
            <Section title="Ostatnio otwierane">
              <ul className="space-y-1.5">
                {recent.map((job) => (
                  <JobRow key={`recent-${job.id}`} job={job} selected={value?.id === job.id} onSelect={onChange} />
                ))}
              </ul>
            </Section>
          ) : null}
        </>
      )}
    </div>
  );
}
