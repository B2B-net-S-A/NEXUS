"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { MapPin, X } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { ChipField } from "@/components/v2/filters/AdvancedSearchPopover";
import { AddedByMultiSelect } from "@/components/v2/filters/AddedByMultiSelect";
import {
  KEYWORD_SCOPE_OPTIONS,
  RADIUS_OPTIONS_KM,
  type CandidateFilters,
  type KeywordScope,
} from "@/lib/url-filters";

type Patch = (patch: Partial<CandidateFilters>) => void;

function SectionTitle({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <p
      id={id}
      className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
    >
      {children}
    </p>
  );
}

function SubLabel({ children, tone }: { children: ReactNode; tone: "success" | "info" | "destructive" }) {
  const dot = { success: "bg-success", info: "bg-info", destructive: "bg-destructive" }[tone];
  return (
    <span className="flex items-center gap-1.5 text-[11px] font-medium text-foreground">
      <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", dot)} />
      {children}
    </span>
  );
}

const SELECT_CLASS =
  "h-8 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground";

/**
 * Słowa kluczowe jak w Traffit: trzy pola (zielone „wszystkie”, niebieskie
 * „którekolwiek”, czerwone „żadne”) i „Szukaj w”. Dopasowanie całych słów
 * i gwiazdkę liczy serwer (`keyword_terms.py`); tu tylko je opisujemy.
 */
export function KeywordFields({ filters, onPatch }: { filters: CandidateFilters; onPatch: Patch }) {
  const scopeId = useId();
  const anyGroup0 = filters.qAny[0] ?? [];
  return (
    <div className="space-y-2">
      <SectionTitle>Słowa kluczowe</SectionTitle>
      <div className="space-y-1">
        <SubLabel tone="success">Zawiera wszystkie</SubLabel>
        <ChipField
          chips={filters.qAll}
          onChange={(next) => onPatch({ qAll: next })}
          placeholder="np. Java, Kafka"
          tone="emerald"
          ariaLabel="Zawiera wszystkie ze słów"
        />
      </div>
      <div className="space-y-1">
        <SubLabel tone="info">Zawiera którekolwiek</SubLabel>
        <ChipField
          chips={anyGroup0}
          onChange={(next) => onPatch({ qAny: [next, ...filters.qAny.slice(1)] })}
          placeholder="np. Spring, Quarkus"
          tone="sky"
          ariaLabel="Zawiera którekolwiek ze słów"
        />
      </div>
      <div className="space-y-1">
        <SubLabel tone="destructive">Nie zawiera żadnego</SubLabel>
        <ChipField
          chips={filters.qNone}
          onChange={(next) => onPatch({ qNone: next })}
          placeholder="np. junior, stażysta"
          tone="rose"
          ariaLabel="Nie zawiera żadnego ze słów"
        />
      </div>
      <div className="space-y-1">
        <label htmlFor={scopeId} className="block text-[11px] font-medium text-foreground">
          Szukaj w
        </label>
        <select
          id={scopeId}
          value={filters.qScope}
          onChange={(e) => onPatch({ qScope: e.target.value as KeywordScope })}
          className={SELECT_CLASS}
        >
          {KEYWORD_SCOPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <p className="text-[11px] leading-snug text-muted-foreground">
        Całe słowa: „java” nie znajdzie „JavaScript”. Gwiazdka szuka początku słowa:
        „bankow*” znajdzie „bankowość” i „bankowym”. Enter dodaje słowo.
      </p>
    </div>
  );
}

interface PlaceSuggestResponse {
  items: Array<{ name: string; voivodeship: string; population: number }>;
  voivodeships: string[];
}

/** Klucz nazwy jak na serwerze (`pl_places.place_key`): bez polskich znaków,
 *  małe litery, myślnik = spacja. Tylko do sprawdzenia, czy miasto jest znane. */
export function placeKey(value: string): string {
  const fold: Record<string, string> = { ł: "l", Ł: "l" };
  return value
    .split(",")[0]
    .replace(/[łŁ]/g, (c) => fold[c])
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[\s-]+/g, " ")
    .trim();
}

/**
 * Lokalizacja: miasto z podpowiedziami, promień w km (tylko dla miasta ze
 * spisu miejscowości) i województwa — jak „Miejscowość + KM / Województwo”
 * w Traffit. Kandydaci nie mają współrzędnych: promień liczy serwer ze spisu
 * miejscowości (GeoNames) po nazwie miasta.
 */
export function LocationFields({ filters, onPatch }: { filters: CandidateFilters; onPatch: Patch }) {
  const inputId = useId();
  const listId = useId();
  const radiusId = useId();
  const [local, setLocal] = useState(filters.location);
  const debounced = useDebouncedValue(local, 300);
  useEffect(() => {
    if (debounced !== filters.location) onPatch({ location: debounced });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);
  useEffect(() => {
    setLocal(filters.location);
  }, [filters.location]);

  const query = debounced.trim();
  const { data } = useQuery<PlaceSuggestResponse>({
    queryKey: ["places-suggest", query],
    queryFn: () =>
      api.get("/api/candidates/places/suggest", { params: { q: query } }).then((r) => r.data),
    staleTime: 5 * 60_000,
  });
  const items = data?.items ?? [];
  const voivodeships = data?.voivodeships ?? [];
  const known =
    query.length > 0 && items.some((p) => placeKey(p.name) === placeKey(query));
  const radiusValue = filters.locationRadiusKm === null ? "" : String(filters.locationRadiusKm);

  return (
    <div className="space-y-2">
      <SectionTitle>Lokalizacja</SectionTitle>
      <div className="space-y-1">
        <label htmlFor={inputId} className="sr-only">
          Miasto
        </label>
        <Input
          id={inputId}
          list={listId}
          leadingIcon={<MapPin className="h-4 w-4" />}
          placeholder="np. Warszawa"
          value={local}
          autoComplete="off"
          onChange={(e) => setLocal(e.target.value)}
        />
        <datalist id={listId}>
          {items.map((p) => (
            <option key={`${p.name}-${p.voivodeship}`} value={p.name}>
              {p.voivodeship}
            </option>
          ))}
        </datalist>
      </div>
      <div className="space-y-1">
        <label htmlFor={radiusId} className="block text-[11px] font-medium text-foreground">
          Promień
        </label>
        <select
          id={radiusId}
          value={radiusValue}
          disabled={!query}
          onChange={(e) =>
            onPatch({ locationRadiusKm: e.target.value ? Number(e.target.value) : null })
          }
          className={cn(SELECT_CLASS, "disabled:opacity-60")}
        >
          <option value="">Tylko to miasto</option>
          {RADIUS_OPTIONS_KM.map((km) => (
            <option key={km} value={km}>
              + {km} km
            </option>
          ))}
        </select>
        {filters.locationRadiusKm !== null && query && data && !known && (
          <p role="status" className="text-[11px] text-warning-muted-foreground">
            Nie znam miejscowości „{query}”. Wybierz ją z podpowiedzi, żeby liczyć promień.
          </p>
        )}
      </div>
      <div className="space-y-1">
        <span className="block text-[11px] font-medium text-foreground">Województwo</span>
        {filters.voivodeships.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {filters.voivodeships.map((v) => (
              <span
                key={v}
                className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-xs"
              >
                {v}
                <button
                  type="button"
                  aria-label={`Usuń województwo: ${v}`}
                  onClick={() =>
                    onPatch({ voivodeships: filters.voivodeships.filter((x) => x !== v) })
                  }
                  className="rounded hover:bg-accent"
                >
                  <X className="h-3 w-3" aria-hidden />
                </button>
              </span>
            ))}
          </div>
        )}
        <select
          aria-label="Dodaj województwo"
          value=""
          onChange={(e) =>
            e.target.value &&
            onPatch({ voivodeships: [...filters.voivodeships, e.target.value] })
          }
          className={SELECT_CLASS}
        >
          <option value="">Dodaj województwo…</option>
          {voivodeships
            .filter((v) => !filters.voivodeships.includes(v))
            .map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
        </select>
      </div>
    </div>
  );
}

const CONTACT_CHOICES: ReadonlyArray<{ value: "" | "yes" | "no"; label: string }> = [
  { value: "", label: "Bez znaczenia" },
  { value: "yes", label: "Był kontakt" },
  { value: "no", label: "Nie było kontaktu" },
];

/**
 * „Kontaktowaliśmy się w okresie …, przez …” (Traffit „Aktywności”).
 * Kontakt = notatka o kandydacie, rozmowa telefoniczna, mail/odpowiedź ze
 * skrzynki Traffita. Historia z Traffita ma datę importu (5 maja 2026).
 */
export function ContactFields({ filters, onPatch }: { filters: CandidateFilters; onPatch: Patch }) {
  const titleId = useId();
  return (
    <div className="space-y-1.5">
      <SectionTitle id={titleId}>Kontakt z kandydatem</SectionTitle>
      <div role="radiogroup" aria-labelledby={titleId} className="flex flex-wrap gap-1.5">
        {CONTACT_CHOICES.map((choice) => {
          const checked = (filters.contacted ?? "") === choice.value;
          return (
            <button
              key={choice.value || "any"}
              type="button"
              role="radio"
              aria-checked={checked}
              onClick={() =>
                onPatch(
                  choice.value
                    ? { contacted: choice.value }
                    : { contacted: null, contactedFrom: "", contactedTo: "", contactedByIds: [] },
                )
              }
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                checked
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-foreground hover:bg-accent",
              )}
            >
              {choice.label}
            </button>
          );
        })}
      </div>
      {filters.contacted && (
        <>
          <div className="flex items-center gap-1.5">
            <Input
              type="date"
              aria-label="Kontakt — od"
              value={filters.contactedFrom}
              max={filters.contactedTo || undefined}
              onChange={(e) => onPatch({ contactedFrom: e.target.value })}
              className="h-8 text-xs"
            />
            <Input
              type="date"
              aria-label="Kontakt — do"
              value={filters.contactedTo}
              min={filters.contactedFrom || undefined}
              onChange={(e) => onPatch({ contactedTo: e.target.value })}
              className="h-8 text-xs"
            />
          </div>
          <AddedByMultiSelect
            value={filters.contactedByIds}
            onChange={(ids) => onPatch({ contactedByIds: ids })}
            includeSystem={false}
            emptyLabel="Ktokolwiek z zespołu"
          />
          <p className="text-[11px] text-muted-foreground">
            Notatki, rozmowy i maile. Historia z Traffita jest od 5 maja 2026.
          </p>
        </>
      )}
    </div>
  );
}
