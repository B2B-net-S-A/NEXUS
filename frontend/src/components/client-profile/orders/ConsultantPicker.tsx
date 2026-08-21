"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { orderGroupsApi, type ConsultantOption } from "@/lib/api/orderGroups";

const inputClass =
  "w-full rounded-md border border-border bg-background py-2 pl-9 pr-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";

interface Props {
  clientId: number;
  value: ConsultantOption | null;
  onChange: (option: ConsultantOption | null) => void;
  /** Modal montuje picker także zamknięty — bez tego lista dociąga się w tle. */
  enabled?: boolean;
}

/** Znacznik pochodzenia. Dwie różne formy, nie dwa odcienie tego samego:
 *  rozróżnienie „znamy ją stąd" vs „z bazy" ma być czytelne także wtedy, gdy
 *  ktoś patrzy na monochromatyczny wydruk albo nie rozróżnia barw. */
export function ConsultantSourceBadge({ option }: { option: ConsultantOption }) {
  return (
    <Badge
      variant={option.source === "client_recruitment" ? "soft" : "outline"}
      size="sm"
    >
      {option.source_label}
    </Badge>
  );
}

/**
 * Wybór konsultanta do linii zamówienia — JEDNA lista z dwóch źródeł.
 *
 * Wcześniej był tu `<select>` z kontraktami u tego klienta, więc osoby, której
 * nie rekrutowaliśmy u tego klienta, nie dało się dołożyć do zamówienia.
 * Teraz lista scala oba źródła; wybór działa identycznie niezależnie od
 * etykiety, a różnicę „skąd ta osoba" widać przy nazwisku.
 */
export function ConsultantPicker({
  clientId,
  value,
  onChange,
  enabled = true,
}: Props) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!enabled) {
      setQuery("");
      setDebounced("");
    }
  }, [enabled]);

  const options = useQuery({
    queryKey: ["order-line-consultant-options", clientId, debounced],
    queryFn: async () =>
      (await orderGroupsApi.consultantOptions(clientId, debounced)).data,
    enabled: enabled && value === null,
  });

  if (value) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-background px-3 py-2">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">
            {value.full_name}
          </span>
          <ConsultantSourceBadge option={value} />
        </span>
        <button
          type="button"
          onClick={() => onChange(null)}
          className="shrink-0 text-xs text-muted-foreground hover:text-foreground"
        >
          Zmień
        </button>
      </div>
    );
  }

  const rows = options.data?.options ?? [];
  const total = options.data?.total ?? 0;

  return (
    <div>
      <div className="relative">
        <Search
          className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground"
          aria-hidden="true"
        />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Szukaj konsultanta po imieniu i nazwisku"
          placeholder="Imię i nazwisko"
          className={inputClass}
        />
      </div>

      <div className="mt-1 max-h-56 overflow-y-auto rounded-md border border-border bg-background">
        {options.isError ? (
          /* Awaria MUSI mieć własną gałąź: pusta lista czyta się jak „nie ma
             takiej osoby w bazie" i kończy założeniem duplikatu. */
          <p role="alert" className="px-3 py-3 text-sm text-destructive">
            Nie udało się wczytać listy konsultantów.{" "}
            <button
              type="button"
              onClick={() => options.refetch()}
              className="underline"
            >
              Ponów
            </button>
          </p>
        ) : !options.isSuccess ? (
          /* `isSuccess`, nie `!isLoading` — między ponowieniami react-query ma
             `isLoading === false` przy pustych danych, więc gałąź na `isLoading`
             przepuszczała ten stan do pustego stanu. */
          <p className="px-3 py-3 text-center text-xs text-muted-foreground">
            Wczytywanie…
          </p>
        ) : rows.length === 0 ? (
          <p className="px-3 py-3 text-center text-xs text-muted-foreground">
            {debounced
              ? `Brak osób pasujących do „${debounced}".`
              : "Brak aktywnych konsultantów do wyboru."}
          </p>
        ) : (
          rows.map((option) => (
            <button
              type="button"
              key={option.candidate_id}
              onClick={() => onChange(option)}
              className="w-full border-b border-border px-3 py-2 text-left transition-colors last:border-b-0 hover:bg-muted"
            >
              <span className="flex items-center gap-2">
                <span className="truncate text-sm font-medium text-foreground">
                  {option.full_name}
                </span>
                <ConsultantSourceBadge option={option} />
              </span>
              {option.job_title ? (
                <span className="block truncate text-xs text-muted-foreground">
                  {option.job_title}
                </span>
              ) : null}
            </button>
          ))
        )}
      </div>

      {options.isSuccess && total > rows.length ? (
        /* Bez tej linii przycięta lista czytałaby się jako komplet — i osoba
           spoza pierwszej setki wyglądałaby na nieobecną w bazie. */
        <p className="mt-1 text-xs text-muted-foreground">
          Pokazano {rows.length} z {total} — zawęź wyszukiwanie.
        </p>
      ) : null}
    </div>
  );
}
