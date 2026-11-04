"use client";

import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";
import { useSalesCompanies, type Ref } from "@/lib/api/sales";

interface CompanyPickerProps {
  id?: string;
  value: Ref | null;
  onChange: (company: Ref | null) => void;
}

/** Wybór firmy z kartoteki sprzedaży: wpisz 2 litery, kliknij wynik. */
export function CompanyPicker({ id, value, onChange }: CompanyPickerProps) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(q.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [q]);
  const search = useSalesCompanies({ q: debounced }, debounced.length >= 2 && !value);

  if (value) {
    return (
      <div className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
        <span className="truncate">{value.name}</span>
        <button
          type="button"
          className="text-xs text-primary hover:underline"
          onClick={() => onChange(null)}
        >
          Zmień
        </button>
      </div>
    );
  }
  const items = search.data?.items ?? [];
  return (
    <div className="space-y-1">
      <Input
        id={id}
        value={q}
        placeholder="Szukaj firmy po nazwie albo NIP…"
        onChange={(event) => setQ(event.target.value)}
      />
      {debounced.length >= 2 && search.isSuccess && (
        <ul role="listbox" aria-label="Firmy" className="max-h-48 overflow-y-auto rounded-md border border-border">
          {items.length === 0 ? (
            <li className="px-3 py-2 text-sm text-muted-foreground">
              Nie ma takiej firmy — dodaj ją najpierw w zakładce Firmy.
            </li>
          ) : (
            items.map((company) => (
              <li key={company.id} role="option" aria-selected={false}>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
                  onClick={() => onChange({ id: company.id, name: company.name })}
                >
                  {company.name}
                  {company.hq_city && (
                    <span className="text-muted-foreground"> · {company.hq_city}</span>
                  )}
                </button>
              </li>
            ))
          )}
        </ul>
      )}
      {search.isError && (
        <p className="text-sm text-destructive">Nie udało się wyszukać firm. Spróbuj jeszcze raz.</p>
      )}
    </div>
  );
}
