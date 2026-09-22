"use client";

/**
 * „Podobne rekrutacje" na stronie tworzenia (0341). Podpowiedzi liczy serwer
 * z roli i must-have wpisanych w formularzu (`POST /api/job-similarity/preview`,
 * rekrutacja jeszcze nie istnieje). Zaznaczenie trafia do `onChange`, a strona
 * po utworzeniu rekrutacji łączy je i przepina osoby wysłane do klienta.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Checkbox } from "@/components/ui/checkbox";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import {
  defaultSelection,
  selectedSentCount,
  similarJobsApi,
} from "@/lib/similar-jobs-api";
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
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const touched = useRef(false);
  // Stabilna tożsamość — `?? []` tworzyłoby nową tablicę w każdym renderze
  // i efekt `onChange` niżej kręciłby się bez końca.
  const items = useMemo(() => query.data ?? [], [query.data]);

  // Dopóki użytkownik nic nie kliknął, zaznaczenie idzie za podpowiedziami
  // (te z osobami wysłanymi do klienta). Po pierwszym kliknięciu — jego wybór.
  useEffect(() => {
    if (touched.current || !query.data) return;
    setSelected(new Set(defaultSelection(query.data)));
  }, [query.data]);

  useEffect(() => {
    onChange([...selected].filter((id) => items.some((i) => i.id === id)));
  }, [selected, items, onChange]);

  if (!enabled || (query.isSuccess && items.length === 0)) return null;

  const toggle = (id: number) => {
    touched.current = true;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const count = selectedSentCount(items, selected);

  return (
    <section
      aria-label="Podobne rekrutacje"
      className="rounded-xl border border-border bg-card p-4"
    >
      <h3 className="text-sm font-semibold text-foreground">Podobne rekrutacje</h3>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Zaznacz, a osoby wysłane tam do klienta trafią do „Do przejrzenia” tej
        rekrutacji.
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
      {selected.size > 0 && (
        <p className="mt-3 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-primary">
          Po utworzeniu przepniemy do {count} {plural(count)} wysłanych wcześniej do
          klienta. Kolejne osoby wysłane w połączonych rekrutacjach też trafią tu same.
        </p>
      )}
    </section>
  );
}
