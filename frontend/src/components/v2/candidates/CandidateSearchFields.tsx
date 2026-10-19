"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Info, MapPin, Search, X } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { type ChipFieldSuggest } from "@/components/v2/filters/AdvancedSearchPopover";
import { RequirementRowsField } from "@/components/v2/candidates/RequirementRowsField";
import { describeKeywordSearch, requirementRows } from "@/lib/keyword-requirements";
import { AddedByMultiSelect } from "@/components/v2/filters/AddedByMultiSelect";
import {
  KEYWORD_SCOPE_OPTIONS,
  RADIUS_OPTIONS_KM,
  type CandidateFilters,
  type KeywordScope,
} from "@/lib/url-filters";
import {
  MAX_LOCATION_PLACES,
  addLocationPlace,
  locationPlacesPatch,
  placeKey,
  removeLocationPlace,
  setLocationPlaceRadius,
  shownLocationPlaces,
  withPreferredCities,
  type LocationPlace,
} from "@/lib/location-places";
import { HideUnknownChoice } from "@/components/v2/candidates/UnknownFieldBadges";

type Patch = (patch: Partial<CandidateFilters>) => void;

/** Podpowiedzi w polach słów: słownik z bazy i ostatnio używane słowa. */
const KEYWORD_SUGGEST: ChipFieldSuggest = {};

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

const SELECT_CLASS =
  "h-8 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground";

/** „Szukaj w” w zdaniu podsumowania („Szukamy w: cały profil”). */
const SCOPE_SENTENCE: Record<KeywordScope, string> = {
  all: "cały profil",
  cv: "treść CV",
  title: "stanowisko",
  skills: "umiejętności",
  notes: "notatki",
};

/**
 * Słowa kluczowe jako lista wymagań (makiety i decyzje Artura 25.09.2026,
 * `RequirementRowsField`): wiersz = wymaganie, słowa w wierszu to warianty,
 * wiersze łączy „i”, na dole „Wyklucz”. Obok „Szukaj w”, pod spodem zdanie,
 * które mówi na żywo, czego szukamy, i „Szukaj”. Dopasowanie całych słów
 * i gwiazdkę liczy serwer (`keyword_terms.py`); zasady pod ikonką ⓘ.
 */
export function KeywordFields({
  filters,
  rows,
  onPatch,
  id,
  className,
  onSearch,
  pendingCount = 0,
  sourceNote,
}: {
  filters: CandidateFilters;
  /**
   * Wiersze w stanie roboczym (z pustym, świeżo dodanym wierszem) — w
   * `filters` puste wiersze są już odfiltrowane. Bez tego: z `filters`.
   */
  rows?: string[][];
  onPatch: Patch;
  id?: string;
  className?: string;
  /** „Szukaj” — zmiany słów i filtrów czekają na ten przycisk (25.09.2026). */
  onSearch?: () => void;
  pendingCount?: number;
  /** Zdanie o pochodzeniu wierszy (okno rekrutacji: „ustawione przy tworzeniu”). */
  sourceNote?: string;
}) {
  const scopeId = useId();
  const titleId = useId();
  const workingRows = rows ?? requirementRows(filters.qAll, filters.qAny);
  const summary = describeKeywordSearch({
    rows: workingRows,
    exclude: filters.qNone,
    scopeLabel: SCOPE_SENTENCE[filters.qScope],
  });
  return (
    // Układ pól liczy się od szerokości PANELU, nie okna (U8, audyt
    // 06.10.2026): w oknie rekrutacji panel jest węższy niż okno przeglądarki.
    <div className={cn("@container", className)}>
      <section
        id={id}
        aria-labelledby={titleId}
        className={cn(
          // Panel ≥ 56rem (laptop z Windows, okno ≈ 1280 × 650, 28.09.2026):
          // podsumowanie i „Szukaj” w rzędzie nagłówka, „Musi mieć” i
          // „Wyklucz” obok siebie — panel zabierał liście 1/3 wysokości.
          // Panel ≥ 94rem (okno ~1800 px z menu) — układ w kolumnie jak dotąd.
          "flex flex-col gap-2 rounded-lg border border-border bg-card p-3",
          "@4xl:grid @4xl:grid-cols-[auto_minmax(0,1fr)] @4xl:items-center @4xl:gap-x-4",
          "@min-[94rem]:flex @min-[94rem]:items-stretch @min-[94rem]:gap-3 @min-[94rem]:p-4",
        )}
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 @4xl:col-start-1 @4xl:row-start-1">
          <SectionTitle id={titleId}>Słowa kluczowe</SectionTitle>
          <span className="text-xs text-muted-foreground @4xl:hidden @min-[94rem]:inline">
            {sourceNote ?? "Każdy wiersz to jedno wymaganie. Słowa w wierszu to warianty — wystarczy jedno z nich."}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <label htmlFor={scopeId} className="text-xs font-medium text-foreground">
              Szukaj w
            </label>
            <select
              id={scopeId}
              value={filters.qScope}
              onChange={(e) => onPatch({ qScope: e.target.value as KeywordScope })}
              className={cn(SELECT_CLASS, "w-36")}
            >
              {KEYWORD_SCOPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  aria-label="Jak działają słowa kluczowe"
                  className="hit-area rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Info className="h-3.5 w-3.5" aria-hidden />
                </button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-80 text-xs leading-snug text-muted-foreground">
                Każdy wiersz musi się zgadzać. Enter albo przecinek zaczyna kolejne wymaganie;
                wariant tego samego wymagania dodasz przyciskiem „+ lub” albo wpisując
                „Kafka / RabbitMQ” — w wierszu wystarczy jedno ze słów. Całe słowa: „java” nie
                znajdzie „JavaScript”. Gwiazdka szuka początku słowa: „bankow*” znajdzie
                „bankowość” i „bankowym”. Pod polem są podpowiedzi — „+ z wariantami” dodaje też
                inne zapisy tej technologii. Wyniki zmieniają się po kliknięciu „Szukaj”.
              </PopoverContent>
            </Popover>
          </div>
        </div>

        <RequirementRowsField
          rows={workingRows}
          onRowsChange={(next) => onPatch({ qAll: [], qAny: next })}
          exclude={filters.qNone}
          onExcludeChange={(next) => onPatch({ qNone: next })}
          suggest={KEYWORD_SUGGEST}
          split
          className="@4xl:col-span-2 @4xl:row-start-2"
          onSubmitEmpty={onSearch}
          onUseLocation={(city) => onPatch({ location: city })}
          onUseExperience={(range) =>
            onPatch({ experienceMin: range.min, experienceMax: range.max })
          }
        />

        <div className="flex flex-col gap-3 rounded-lg border border-primary/20 bg-primary/5 px-3 py-1.5 sm:flex-row sm:items-center @4xl:col-start-2 @4xl:row-start-1 @min-[94rem]:py-2.5">
          <p className="min-w-0 flex-1 text-sm text-foreground @4xl:line-clamp-2 @min-[94rem]:line-clamp-none" aria-live="polite" title={summary}>
            {summary}
          </p>
          {onSearch && (
            <Button
              type="button"
              variant="primary"
              onClick={onSearch}
              className={cn(
                "h-10 w-full shrink-0 gap-2 sm:w-auto sm:min-w-[124px] @4xl:h-8 @min-[94rem]:h-10",
                pendingCount > 0 && "ring-4 ring-primary/20",
              )}
              data-help="candidates.list.search"
            >
              <Search className="h-4 w-4" aria-hidden />
              Szukaj
              {pendingCount > 0 && (
                <>
                  <span
                    aria-hidden
                    className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary-foreground px-1.5 text-xs font-bold text-primary"
                  >
                    {pendingCount}
                  </span>
                  <span className="sr-only">(niezastosowane zmiany: {pendingCount})</span>
                </>
              )}
            </Button>
          )}
        </div>
      </section>
    </div>
  );
}

interface PlaceSuggestResponse {
  items: Array<{ name: string; voivodeship: string; population: number }>;
  voivodeships: string[];
}

export { placeKey } from "@/lib/location-places";

/**
 * Lokalizacja kandydata · którekolwiek (D6, 19.10.2026): do 10 miast
 * z podpowiedziami, przy każdym własny promień (tylko dla miasta ze spisu
 * miejscowości), województwa i wybór D5 dla osób bez miasta. Osoba przechodzi,
 * gdy pasuje do KTÓREGOKOLWIEK miasta, promienia albo województwa. Kandydaci
 * nie mają współrzędnych: promień liczy serwer ze spisu miejscowości
 * (GeoNames) po nazwie miasta. Zapis: `locationPlacesPatch` (jedno miasto bez
 * województw = dawny kształt `loc`/`radius`).
 */
export function LocationFields({ filters, onPatch }: { filters: CandidateFilters; onPatch: Patch }) {
  const inputId = useId();
  const listId = useId();
  const radiusId = useId();
  const places = shownLocationPlaces(filters);
  const [draft, setDraft] = useState("");
  const [draftRadius, setDraftRadius] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const debounced = useDebouncedValue(draft, 300);

  const commit = (next: LocationPlace[], voivodeships = filters.voivodeships) =>
    onPatch(locationPlacesPatch(next, voivodeships));
  const addDraft = (): boolean => {
    const city = draft.trim();
    if (!city) return false;
    const result = addLocationPlace(places, { city, radiusKm: draftRadius });
    setNote(result.note);
    if (result.note) return false;
    commit(result.places);
    setDraft("");
    setDraftRadius(null);
    return true;
  };
  // Pole żyje w okienku, które znika po zamknięciu — miasto wpisane tuż przed
  // zamknięciem (bez Enter i „Dodaj”) nie może przepaść.
  const pending = useRef({ draft, draftRadius, places, filters, onPatch });
  useEffect(() => {
    pending.current = { draft, draftRadius, places, filters, onPatch };
  });
  useEffect(
    () => () => {
      const { draft: typed, draftRadius: radius, places: list, filters: f, onPatch: patch } =
        pending.current;
      if (!typed.trim()) return;
      const result = addLocationPlace(list, { city: typed.trim(), radiusKm: radius });
      if (!result.note) patch(locationPlacesPatch(result.places, f.voivodeships));
    },
    [],
  );

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
  const preferred = filters.locationPreferred.filter(
    (city) => !places.some((p) => placeKey(p.city) === placeKey(city)),
  );

  return (
    <div className="space-y-2">
      <SectionTitle>Lokalizacja kandydata · którekolwiek</SectionTitle>
      {places.length > 0 && (
        <ul aria-label="Wybrane miasta" className="max-h-48 space-y-1 overflow-y-auto pr-1">
          {places.map((place, index) => (
            <li key={`${place.city}-${index}`} className="flex items-center gap-1.5">
              <span className="min-w-0 flex-1 truncate text-sm text-foreground" title={place.city}>
                {place.city}
              </span>
              <select
                aria-label={`Promień: ${place.city}`}
                value={place.radiusKm === null ? "" : String(place.radiusKm)}
                onChange={(e) =>
                  commit(
                    setLocationPlaceRadius(
                      places,
                      index,
                      e.target.value ? Number(e.target.value) : null,
                    ),
                  )
                }
                className={cn(SELECT_CLASS, "w-32 shrink-0")}
              >
                <option value="">Tylko to miasto</option>
                {RADIUS_OPTIONS_KM.map((km) => (
                  <option key={km} value={km}>
                    + {km} km
                  </option>
                ))}
              </select>
              <button
                type="button"
                aria-label={`Usuń miasto: ${place.city}`}
                onClick={() => {
                  setNote(null);
                  commit(removeLocationPlace(places, index));
                }}
                className="hit-area shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="space-y-1">
        <label htmlFor={inputId} className="sr-only">
          Miasto
        </label>
        <div className="flex items-center gap-1.5">
          <Input
            id={inputId}
            list={listId}
            leadingIcon={<MapPin className="h-4 w-4" />}
            placeholder={places.length ? "Dodaj miasto" : "np. Warszawa"}
            value={draft}
            autoComplete="off"
            disabled={places.length >= MAX_LOCATION_PLACES}
            onChange={(e) => {
              setNote(null);
              setDraft(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && draft.trim()) {
                e.preventDefault();
                addDraft();
              }
            }}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={addDraft}
            disabled={!draft.trim()}
          >
            Dodaj
          </Button>
        </div>
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
          value={draftRadius === null ? "" : String(draftRadius)}
          disabled={!draft.trim()}
          onChange={(e) => setDraftRadius(e.target.value ? Number(e.target.value) : null)}
          className={cn(SELECT_CLASS, "disabled:opacity-60")}
        >
          <option value="">Tylko to miasto</option>
          {RADIUS_OPTIONS_KM.map((km) => (
            <option key={km} value={km}>
              + {km} km
            </option>
          ))}
        </select>
        {draftRadius !== null && query && data && !known && (
          <p role="status" className="text-[11px] text-warning-muted-foreground">
            Nie znam miejscowości „{query}”. Wybierz ją z podpowiedzi, żeby liczyć promień.
          </p>
        )}
        {places.length >= MAX_LOCATION_PLACES && (
          <p className="text-[11px] text-muted-foreground">
            Najwyżej {MAX_LOCATION_PLACES} miast.
          </p>
        )}
        {note && (
          <p role="status" className="text-[11px] text-warning-muted-foreground">
            {note}
          </p>
        )}
      </div>
      {preferred.length > 0 && (
        <button
          type="button"
          onClick={() => {
            const { places: next, skipped } = withPreferredCities(places, preferred);
            setNote(
              skipped.length
                ? `Nie zmieściły się: ${skipped.join(", ")} (najwyżej ${MAX_LOCATION_PLACES} miast).`
                : null,
            );
            onPatch({
              ...locationPlacesPatch(next, filters.voivodeships),
              locationPreferred: filters.locationPreferred.filter((city) =>
                skipped.includes(city),
              ),
            });
          }}
          className="text-left text-xs font-medium text-primary hover:underline"
          title="Miasta rekrutacji są teraz „Mile widziane” (tylko kolejność). Wstawione tutaj stają się filtrem."
        >
          Wstaw miasta rekrutacji ({preferred.join(", ")})
        </button>
      )}
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
                    commit(
                      places,
                      filters.voivodeships.filter((x) => x !== v),
                    )
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
            e.target.value && commit(places, [...filters.voivodeships, e.target.value])
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
      <HideUnknownChoice
        label="Osoby bez miasta w profilu"
        hidden={filters.hideUnknownLocation}
        onChange={(hidden) => onPatch({ hideUnknownLocation: hidden })}
        className="border-t border-border pt-2"
      />
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
      <p className="text-[11px] leading-4 text-muted-foreground">
        Liczą się rozmowy, maile i ustalone terminy — „nie odebrał” i wpisy automatu nie.
      </p>
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
