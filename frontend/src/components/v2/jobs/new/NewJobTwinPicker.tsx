"use client";

/**
 * „Czy to bliźniak którejś z Twoich rekrutacji?” na stronie tworzenia (0614,
 * decyzja Artura 28.10.2026, makieta część 2). Delivery Lead widzi swoje
 * otwarte rekrutacje (najpierw tego klienta), Head of Recruitment i admin —
 * otwarte rekrutacje tego klienta. Nic nie jest zaznaczone samo (lekcja
 * z 23.09: zapis szkicu połączył rekrutacje, których nikt nie wybrał).
 *
 * Połączenie powstaje po utworzeniu rekrutacji, bez par pytań — Profil
 * Championa nowej rekrutacji jeszcze ich nie ma; pary DL ustawi z chipu
 * „⇄ Bliźniak” w nagłówku.
 */

import { useQuery } from "@tanstack/react-query";

import { budgetLabel, jobTwinsApi, jobTwinsKeys, twinRef, workModeLabel } from "@/lib/job-twins-api";

export interface NewJobTwinPickerProps {
  clientId: number | null;
  value: readonly number[];
  onChange: (ids: number[]) => void;
}

const MAX_TWINS = 3;

export function NewJobTwinPicker({ clientId, value, onChange }: NewJobTwinPickerProps) {
  const query = useQuery({
    queryKey: jobTwinsKeys.candidates(clientId),
    queryFn: () => jobTwinsApi.candidates(clientId),
    staleTime: 60_000,
    retry: false,
  });
  const items = query.data?.items ?? [];
  if (!query.isSuccess || items.length === 0) return null;
  const chosen = new Set(value);
  const toggle = (id: number) => {
    if (chosen.has(id)) onChange(value.filter((v) => v !== id));
    else if (value.length < MAX_TWINS) onChange([...value, id]);
  };
  const sameClient = items.filter((i) => i.client_id === clientId).length;
  return (
    <section
      aria-labelledby="new-job-twins"
      data-testid="new-job-twin-picker"
      className="space-y-2 rounded-xl border border-border bg-card p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="new-job-twins" className="text-sm font-semibold">
          Czy to bliźniak którejś z Twoich rekrutacji?
        </h2>
        <span className="text-xs text-muted-foreground">
          {clientId ? `tego klienta: ${sameClient}` : "wybierz klienta, żeby zobaczyć jego rekrutacje na górze"}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Bliźniak = ten sam profil kandydata. Każdą osobę weryfikujecie wtedy raz, w jednej rozmowie, pod obie
        rekrutacje. Najwyżej {MAX_TWINS}.
      </p>
      <ul className="max-h-64 divide-y divide-border overflow-y-auto rounded-lg border border-border">
        {items.map((item) => {
          const id = `new-job-twin-${item.id}`;
          const on = chosen.has(item.id);
          return (
            <li key={item.id} className="flex items-center gap-2 px-3 py-2">
              <input
                id={id}
                type="checkbox"
                className="h-4 w-4 shrink-0 accent-[hsl(var(--primary))]"
                checked={on}
                disabled={!on && value.length >= MAX_TWINS}
                onChange={() => toggle(item.id)}
              />
              <label htmlFor={id} className="min-w-0 flex-1 text-sm">
                <span className="mr-1.5 font-mono text-xs">{twinRef(item)}</span>
                <span className="font-medium">{item.title}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {item.client_name ?? "—"} · {workModeLabel(item)} · {budgetLabel(item)} · {item.people_count} os.
                </span>
              </label>
              {on ? <span className="shrink-0 text-xs font-semibold text-primary">⇄ bliźniak</span> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
