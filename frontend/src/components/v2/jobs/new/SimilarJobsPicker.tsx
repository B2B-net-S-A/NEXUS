"use client";

/**
 * „Podobne rekrutacje" na stronie tworzenia (0341). Podpowiedzi liczy serwer
 * z roli i must-have wpisanych w formularzu (`POST /api/job-similarity/preview`,
 * rekrutacja jeszcze nie istnieje). Zaznaczenie trafia do `onChange`, a strona
 * po utworzeniu rekrutacji łączy je i przepina osoby wysłane do klienta.
 *
 * NIC nie jest zaznaczone domyślnie (test na produkcji 23.09.2026). Połączenie
 * jest trwałe i symetryczne, a przepięcie wrzuca ludzi do „Do przejrzenia” —
 * do 23.09 podpowiedzi z osobami u klienta zaznaczały się same, więc zwykłe
 * „Zapisz szkic” połączyło nową rekrutację z dwiema zamkniętymi i przepięło
 * 41 osób, choć użytkownik niczego nie kliknął. Łączymy wyłącznie to, co ktoś
 * zaznaczył ręką.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Checkbox } from "@/components/ui/checkbox";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { selectedSentCount, similarJobsApi } from "@/lib/similar-jobs-api";
import { cn } from "@/lib/utils";
import { plural } from "@/components/v2/jobs/SimilarJobsDialog";

export function SimilarJobsPicker({
  title,
  must,
  onChange,
}: {
  title: string;
  must: string[];
  onChange: (jobIds: number[]) => void;
}) {
  const input = useDebouncedValue(
    useMemo(() => ({ title: title.trim(), must_skills: must.filter(Boolean) }), [title, must]),
    500,
  );
  const enabled = input.title.length >= 3 || input.must_skills.length > 0;
  const query = useQuery({
    queryKey: ["similar-jobs-preview", input.title, input.must_skills],
    queryFn: () => similarJobsApi.preview(input),
    enabled,
    staleTime: 60_000,
  });
  // Start zawsze pusty — patrz komentarz na górze pliku.
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // Stabilna tożsamość — `?? []` tworzyłoby nową tablicę w każdym renderze
  // i efekt `onChange` niżej kręciłby się bez końca.
  const items = useMemo(() => query.data ?? [], [query.data]);
  // Do zapisu idzie tylko zaznaczenie WIDOCZNE na liście: po zmianie roli
  // podpowiedź, która zniknęła z ekranu, nie może połączyć się po cichu.
  const visibleSelected = useMemo(
    () => [...selected].filter((id) => items.some((i) => i.id === id)),
    [selected, items],
  );

  useEffect(() => {
    onChange(visibleSelected);
  }, [visibleSelected, onChange]);

  if (!enabled || (query.isSuccess && items.length === 0)) return null;

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const count = selectedSentCount(items, selected);
  const selectedCount = visibleSelected.length;

  return (
    <section
      aria-label="Podobne rekrutacje"
      className="rounded-xl border border-border bg-card p-4"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold text-foreground">Podobne rekrutacje</h3>
        {items.length > 0 && (
          <span
            className="text-xs text-muted-foreground"
            data-testid="similar-jobs-selected-count"
          >
            Zaznaczone: {selectedCount} z {items.length}
          </span>
        )}
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Podpowiedzi — nic nie jest zaznaczone. Zaznacz tylko te, z którymi chcesz
        połączyć nową rekrutację: osoby wysłane tam do klienta trafią do „Do
        przejrzenia” tej rekrutacji.
      </p>
      {query.isLoading ? (
        <p className="mt-3 text-sm text-muted-foreground">Szukam podobnych…</p>
      ) : query.isError ? (
        <p className="mt-3 text-sm text-muted-foreground">
          Nie udało się pobrać podpowiedzi — podobne rekrutacje połączysz później
          w rekrutacji.
        </p>
      ) : (
        <ul className="mt-2 space-y-1">
          {items.map((item) => {
            const checked = selected.has(item.id);
            return (
              <li key={item.id}>
                <label
                  className={cn(
                    "flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2",
                    checked ? "bg-primary/5" : "hover:bg-muted",
                  )}
                >
                  <Checkbox
                    checked={checked}
                    data-testid={`similar-job-checkbox-${item.id}`}
                    onCheckedChange={() => toggle(item.id)}
                    aria-label={item.title}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{item.title}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {[
                        item.client_name,
                        item.reference_number,
                        item.status === "closed" ? "zamknięta" : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                  {item.similarity != null && (
                    <span className="text-sm font-semibold tabular-nums text-primary">
                      {item.similarity}%
                    </span>
                  )}
                  <span className="w-24 text-right text-xs text-muted-foreground">
                    <b className="font-semibold text-foreground">{item.sent_count}</b> u klienta
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {selectedCount === 0 && items.length > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">
          Nic nie zaznaczono — nowa rekrutacja nie zostanie połączona z żadną z nich.
        </p>
      )}
      {selectedCount > 0 && (
        <p className="mt-3 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-primary">
          Po utworzeniu przepniemy do {count} {plural(count)} wysłanych wcześniej do
          klienta. Kolejne osoby wysłane w połączonych rekrutacjach też trafią tu same.
        </p>
      )}
    </section>
  );
}
