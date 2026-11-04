"use client";

/**
 * Wybór konsultanta, z którym Delivery Lead rozmawiał o pracy u klienta.
 *
 * Do 14.10.2026 był to `<select>` z podpowiedzi serwera i nic więcej — gdy
 * osoby nie było na liście („miałem do wyboru z 20, a nie ma tego, z którym
 * rozmawiałem”), zostawało pole ręczne, które znikało po wybraniu kogokolwiek.
 * Teraz jedno pole szuka naraz na liście „U tego klienta” i w całej bazie,
 * a gdy osoby nie ma w NEXUSIE, wpisane imię i nazwisko da się zapisać wprost.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, PenLine, Search, UserCheck } from "lucide-react";

import { api, championApi } from "@/lib/api";
import { foldText, matchRank } from "@/lib/contract-client-filter";
import { useDebouncedValue } from "@/lib/use-debounced-value";

export interface ConsultantChoice {
  /** `null` = imię i nazwisko wpisane ręcznie, bez osoby w bazie. */
  candidateId: number | null;
  name: string;
  detail?: string | null;
}

interface BaseSearchItem {
  id: number;
  name?: string | null;
  lastname?: string | null;
  email?: string | null;
}

/** Tyle samo znaków co `min_length` parametru `q` listy kandydatów. */
const MIN_BASE_QUERY = 2;

const rowClass =
  "w-full flex items-baseline gap-1.5 px-2 py-1 text-left text-xs hover:bg-muted focus-visible:bg-muted focus-visible:outline-hidden";
const groupLabelClass =
  "px-2 pt-1.5 pb-0.5 text-[10px] uppercase tracking-wide text-muted-foreground";
const noteClass = "px-2 py-1 text-[11px] text-muted-foreground";

function personName(item: BaseSearchItem): string {
  return `${item.name ?? ""} ${item.lastname ?? ""}`.trim() || `Kandydat #${item.id}`;
}

export function ConsultantPicker({
  jobId,
  value,
  onChange,
}: {
  jobId: number;
  value: ConsultantChoice | null;
  onChange: (value: ConsultantChoice | null) => void;
}) {
  const [query, setQuery] = useState("");
  const term = query.trim();
  const debouncedTerm = useDebouncedValue(term, 300);

  const suggestionsQuery = useQuery({
    queryKey: ["champion-consultant-suggestions", jobId],
    queryFn: () => championApi.consultantSuggestions(jobId).then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  const baseQuery = useQuery({
    queryKey: ["champion-consultant-base-search", debouncedTerm],
    queryFn: () =>
      api
        .get<{ items?: BaseSearchItem[] }>("/api/candidates", {
          // `relevance` jak w palecie poleceń: domyślne „najnowsi” przy
          // popularnym imieniu oddawało ostatnio dodanych, bez szukanej osoby.
          params: { q: debouncedTerm, page_size: 8, sort: "relevance" },
        })
        .then((r) => r.data?.items ?? []),
    enabled: value === null && debouncedTerm.length >= MIN_BASE_QUERY,
    staleTime: 60 * 1000,
  });

  if (value) {
    return (
      <div
        className="flex items-center justify-between gap-2 px-2 py-1.5 border border-border rounded-md bg-card dark:bg-muted text-xs"
        data-testid="consultant-picker-selected"
      >
        <span className="inline-flex items-baseline gap-1.5 min-w-0">
          <UserCheck className="w-3.5 h-3.5 self-center shrink-0 text-success" />
          <span className="font-medium text-foreground truncate">{value.name}</span>
          {value.candidateId === null ? (
            <span className="text-muted-foreground shrink-0">· wpisane ręcznie</span>
          ) : value.detail ? (
            <span className="text-muted-foreground truncate">· {value.detail}</span>
          ) : null}
        </span>
        <button
          type="button"
          onClick={() => onChange(null)}
          className="shrink-0 text-primary hover:underline"
          data-testid="consultant-picker-change"
        >
          Zmień
        </button>
      </div>
    );
  }

  const suggestions = suggestionsQuery.data ?? [];
  const foldedTerm = foldText(term);
  const atClient = term
    ? suggestions.filter(
        (s) => matchRank(`${s.name} ${s.job_title ?? ""}`, foldedTerm) >= 0,
      )
    : suggestions;
  const atClientIds = new Set(suggestions.map((s) => s.candidate_id));
  const inBase = (baseQuery.data ?? []).filter((c) => !atClientIds.has(c.id));
  const searchingBase = term.length >= MIN_BASE_QUERY;
  const baseSettling = searchingBase && (debouncedTerm !== term || baseQuery.isFetching);

  return (
    <div className="space-y-1">
      <label className="block">
        <span className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
          Nasi konsultanci u tego klienta
          {suggestionsQuery.isSuccess ? ` · ${suggestions.length}` : ""}
        </span>
        <span className="relative block">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Szukaj po imieniu i nazwisku — także w całej bazie"
            className="w-full pl-7 pr-2 py-1 text-xs border border-border rounded-md bg-card dark:bg-muted"
            data-testid="consultant-picker-search"
          />
        </span>
      </label>

      <div
        className="max-h-56 overflow-y-auto border border-border rounded-md bg-card dark:bg-muted"
        data-testid="consultant-picker-list"
      >
        {suggestionsQuery.isLoading ? (
          <div className={`${noteClass} inline-flex items-center gap-1.5`}>
            <Loader2 className="w-3 h-3 animate-spin" /> Szukam konsultantów u klienta…
          </div>
        ) : suggestionsQuery.isError ? (
          // Awaria ≠ „nikogo nie ma”: szukanie w bazie i wpis ręczny dalej działają.
          <div className="px-2 py-1 text-[11px] text-destructive" role="alert">
            Nie udało się wczytać konsultantów tego klienta — wyszukaj osobę w bazie
            albo wpisz imię i nazwisko.{" "}
            <button
              type="button"
              onClick={() => suggestionsQuery.refetch()}
              className="underline"
            >
              Spróbuj ponownie
            </button>
          </div>
        ) : suggestions.length === 0 ? (
          <div className={noteClass} data-testid="consultant-picker-none-at-client">
            System nie znalazł naszych konsultantów u tego klienta — wyszukaj osobę
            w bazie albo wpisz imię i nazwisko.
          </div>
        ) : (
          <div role="group" aria-label="U tego klienta">
            <div className={groupLabelClass}>U tego klienta</div>
            {atClient.length === 0 ? (
              <div className={noteClass}>Nikt u tego klienta nie pasuje do „{term}”.</div>
            ) : (
              <ul>
                {atClient.map((s) => (
                  <li key={s.candidate_id}>
                    <button
                      type="button"
                      className={rowClass}
                      onClick={() =>
                        onChange({
                          candidateId: s.candidate_id,
                          name: s.name,
                          detail: s.job_title,
                        })
                      }
                      data-testid="consultant-picker-option"
                    >
                      <span className="text-foreground">{s.name}</span>
                      {s.job_title ? (
                        <span className="text-muted-foreground truncate">
                          · {s.job_title}
                        </span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {searchingBase ? (
          <div role="group" aria-label="W całej bazie" className="border-t border-border">
            <div className={groupLabelClass}>W całej bazie</div>
            {baseSettling ? (
              <div className={`${noteClass} inline-flex items-center gap-1.5`}>
                <Loader2 className="w-3 h-3 animate-spin" /> Szukam w bazie…
              </div>
            ) : baseQuery.isError ? (
              <div className="px-2 py-1 text-[11px] text-destructive" role="alert">
                Nie udało się przeszukać bazy kandydatów.
              </div>
            ) : inBase.length === 0 ? (
              <div className={noteClass}>Nikogo więcej w bazie.</div>
            ) : (
              <ul>
                {inBase.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      className={rowClass}
                      onClick={() =>
                        onChange({
                          candidateId: c.id,
                          name: personName(c),
                          detail: c.email,
                        })
                      }
                      data-testid="consultant-picker-base-option"
                    >
                      <span className="text-foreground">{personName(c)}</span>
                      {c.email ? (
                        <span className="text-muted-foreground truncate">· {c.email}</span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : suggestionsQuery.isSuccess && suggestions.length > 0 ? (
          <div className={`${noteClass} border-t border-border`}>
            Nie ma go na liście? Wpisz nazwisko — poszukam w całej bazie.
          </div>
        ) : null}

        {searchingBase ? (
          <button
            type="button"
            className={`${rowClass} border-t border-border text-primary`}
            onClick={() => onChange({ candidateId: null, name: term })}
            data-testid="consultant-picker-manual"
          >
            <PenLine className="w-3 h-3 self-center shrink-0" />
            <span>Nie ma go w NEXUSIE — zapisz jako „{term}”</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}
