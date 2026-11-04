"use client";

/**
 * Parametry ogłoszenia na RocketJobs / JustJoin.IT (`PortalListingOptions`).
 *
 * Kontrolowany formularz — stan trzyma rodzic (okno publikacji w oknie
 * zlecenia i krok „Ogłoszenie na portalach” na `/jobs/new`). Kategorie idą ze
 * słownika PIERWSZEGO zaznaczonego portalu dostawcy; awaria odczytu mówi
 * o sobie wprost, nigdy nie wygląda jak pusta lista. Widełki są opcjonalne
 * i wpisuje je Delivery Lead (decyzja 25.09.2026: nigdy z budżetu rekrutacji).
 */

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  fetchBoardDictionaries,
  isJobBoard,
  jobPortalKeys,
  type DictionaryEntry,
  type JobBoard,
  type JobPortal,
  type PortalConfigItem,
  type PortalListingOptions,
  type PortalSalary,
} from "@/lib/api/jobPortals";
import { cn } from "@/lib/utils";

// ── Logika (czyste funkcje, testowane osobno) ────────────────────────────────

/** Słowniki kategorii bierzemy z pierwszego zaznaczonego portalu dostawcy. */
export function dictionaryBoard(selected: readonly JobPortal[]): JobBoard | null {
  return selected.find(isJobBoard) ?? null;
}

/** Zmiana trybu pracy: dni w biurze mają sens tylko przy hybrydzie. */
export function withWorkplace(
  options: PortalListingOptions,
  workplace: string | null,
): PortalListingOptions {
  return {
    ...options,
    workplace_type: workplace,
    office_days: workplace === "hybrid" ? options.office_days : null,
  };
}

function parseAmount(raw: string): number | null {
  const normalized = raw.replace(/\s/g, "").replace(",", ".");
  if (!normalized) return null;
  const n = Number(normalized);
  return Number.isFinite(n) ? n : null;
}

/**
 * Pola „od / do” → widełki. Oba puste = `null` (ogłoszenie bez widełek).
 * Jedno puste daje 0 po jego stronie — walidacja powie wtedy, czego brakuje,
 * zamiast po cichu wysłać ogłoszenie bez widełek.
 */
export function salaryFromInputs(
  from: string,
  to: string,
  unit: PortalSalary["unit"],
): PortalSalary | null {
  const a = parseAmount(from);
  const b = parseAmount(to);
  if (a == null && b == null) return null;
  return { from: a ?? 0, to: b ?? 0, unit };
}

function amountText(value: number | undefined): string {
  return value ? String(value) : "";
}

// Gdy portal nie ma słownika (Pracuj.pl) albo słownik jeszcze się czyta.
const FALLBACK_EXPERIENCE: DictionaryEntry[] = [
  { key: "junior", name: "Junior" },
  { key: "mid", name: "Mid" },
  { key: "senior", name: "Senior" },
  { key: "c_level", name: "C-level / Manager" },
];
const FALLBACK_WORKING_TIME: DictionaryEntry[] = [
  { key: "full_time", name: "Pełny etat" },
  { key: "part_time", name: "Część etatu" },
  { key: "freelance", name: "Freelance" },
];
const FALLBACK_WORKPLACE: DictionaryEntry[] = [
  { key: "remote", name: "Zdalnie" },
  { key: "hybrid", name: "Hybrydowo" },
  { key: "office", name: "Biuro" },
];

function entriesOr(list: DictionaryEntry[] | undefined, fallback: DictionaryEntry[]) {
  return list && list.length > 0 ? list : fallback;
}

// ── Widok ────────────────────────────────────────────────────────────────────

const SELECT_CLASS =
  "h-10 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground disabled:cursor-not-allowed disabled:text-muted-foreground";

interface Props {
  value: PortalListingOptions;
  onChange: (next: PortalListingOptions) => void;
  /** Wybór portali — bez `onSelectedChange` lista się nie renderuje (edycja jednego). */
  portals?: PortalConfigItem[];
  selected: JobPortal[];
  onSelectedChange?: (next: JobPortal[]) => void;
  /** Braki z walidacji — renderowane pod formularzem. */
  problems?: string[];
  disabled?: boolean;
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-sm font-medium text-foreground">
        {label}
      </label>
      {children}
      {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
    </div>
  );
}

function SelectFrom({
  id,
  value,
  onChange,
  entries,
  placeholder,
  disabled,
}: {
  id: string;
  value: string | null;
  onChange: (next: string | null) => void;
  entries: DictionaryEntry[];
  placeholder: string;
  disabled?: boolean;
}) {
  return (
    <select
      id={id}
      className={SELECT_CLASS}
      value={value ?? ""}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">{placeholder}</option>
      {entries.map((entry) => (
        <option key={entry.key} value={entry.key}>
          {entry.name}
        </option>
      ))}
    </select>
  );
}

export function PortalListingForm({
  value,
  onChange,
  portals,
  selected,
  onSelectedChange,
  problems = [],
  disabled = false,
}: Props) {
  const id = useId();
  const board = dictionaryBoard(selected);
  const dictionaries = useQuery({
    queryKey: jobPortalKeys.dictionaries(board ?? "rocketjobs"),
    queryFn: () => fetchBoardDictionaries(board as JobBoard),
    enabled: board != null,
    staleTime: 60 * 60_000,
  });
  // Jednostka widełek żyje lokalnie, dopóki kwot nie ma (salary = null).
  const [unit, setUnit] = useState<PortalSalary["unit"]>(value.salary?.unit ?? "hour");
  const salaryUnit = value.salary?.unit ?? unit;
  const [fromText, setFromText] = useState(amountText(value.salary?.from));
  const [toText, setToText] = useState(amountText(value.salary?.to));

  const set = (patch: Partial<PortalListingOptions>) => onChange({ ...value, ...patch });
  const setSalary = (from: string, to: string, nextUnit: PortalSalary["unit"]) => {
    setFromText(from);
    setToText(to);
    setUnit(nextUnit);
    set({ salary: salaryFromInputs(from, to, nextUnit) });
  };
  const dict = dictionaries.data;
  const togglePortal = (portal: JobPortal, on: boolean) => {
    if (!onSelectedChange) return;
    onSelectedChange(on ? [...selected, portal] : selected.filter((p) => p !== portal));
  };

  return (
    <fieldset className="flex flex-col gap-4" disabled={disabled}>
      {onSelectedChange && portals ? (
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-foreground">Portale</span>
          {portals.length === 0 ? (
            <p className="text-xs text-muted-foreground">Żaden portal nie jest dziś gotowy do publikacji.</p>
          ) : (
            <div className="flex flex-wrap gap-4">
              {portals.map((item) => (
                <label key={item.portal} className="flex items-center gap-2 text-sm text-foreground">
                  <Checkbox
                    checked={selected.includes(item.portal)}
                    onCheckedChange={(checked) => togglePortal(item.portal, checked === true)}
                    aria-label={item.label}
                  />
                  {item.label}
                </label>
              ))}
            </div>
          )}
        </div>
      ) : null}

      <Field label="Kategoria" htmlFor={`${id}-category`}>
        {board == null ? (
          <p className="text-xs text-muted-foreground">
            Zaznacz portal RocketJobs albo JustJoin.IT — kategorie pochodzą z jego słownika.
          </p>
        ) : dictionaries.isError ? (
          <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-destructive">
            <span>
              Nie udało się wczytać kategorii portalu:{" "}
              {apiErrorMessage(dictionaries.error, "spróbuj ponownie.")}
            </span>
            <button
              type="button"
              className="font-medium text-primary hover:underline"
              onClick={() => void dictionaries.refetch()}
            >
              Ponów
            </button>
          </div>
        ) : dictionaries.isSuccess ? (
          <SelectFrom
            id={`${id}-category`}
            value={value.category}
            onChange={(category) => set({ category })}
            entries={dict?.categories ?? []}
            placeholder="Wybierz kategorię…"
          />
        ) : (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> Wczytuję kategorie portalu…
          </p>
        )}
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Poziom doświadczenia" htmlFor={`${id}-level`}>
          <SelectFrom
            id={`${id}-level`}
            value={value.experience_level}
            onChange={(experience_level) => set({ experience_level })}
            entries={entriesOr(dict?.experience_levels, FALLBACK_EXPERIENCE)}
            placeholder="Nie podano"
          />
        </Field>
        <Field label="Wymiar pracy" htmlFor={`${id}-time`}>
          <SelectFrom
            id={`${id}-time`}
            value={value.working_time}
            onChange={(working_time) => set({ working_time })}
            entries={entriesOr(dict?.working_times, FALLBACK_WORKING_TIME)}
            placeholder="Nie podano"
          />
        </Field>
        <Field label="Tryb pracy" htmlFor={`${id}-workplace`}>
          <SelectFrom
            id={`${id}-workplace`}
            value={value.workplace_type}
            onChange={(workplace) => onChange(withWorkplace(value, workplace))}
            entries={entriesOr(dict?.workplace_types, FALLBACK_WORKPLACE)}
            placeholder="Nie podano"
          />
        </Field>
        {value.workplace_type === "hybrid" ? (
          <Field label="Dni w biurze w tygodniu" htmlFor={`${id}-days`} hint="Od 1 do 4.">
            <Input
              id={`${id}-days`}
              type="number"
              min={1}
              max={4}
              step={1}
              value={value.office_days ?? ""}
              onChange={(e) => set({ office_days: e.target.value === "" ? null : Number(e.target.value) })}
            />
          </Field>
        ) : null}
        <Field label="Miasto" htmlFor={`${id}-city`}>
          <Input
            id={`${id}-city`}
            value={value.city ?? ""}
            onChange={(e) => set({ city: e.target.value || null })}
            placeholder="np. Warszawa"
          />
        </Field>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-sm font-medium text-foreground">Widełki (opcjonalnie)</span>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="Widełki od"
            className="w-28"
            inputMode="decimal"
            value={fromText}
            onChange={(e) => setSalary(e.target.value, toText, salaryUnit)}
            placeholder="od"
          />
          <span className="text-muted-foreground" aria-hidden>
            –
          </span>
          <Input
            aria-label="Widełki do"
            className="w-28"
            inputMode="decimal"
            value={toText}
            onChange={(e) => setSalary(fromText, e.target.value, salaryUnit)}
            placeholder="do"
          />
          <select
            aria-label="Jednostka widełek"
            className={cn(SELECT_CLASS, "w-auto")}
            value={salaryUnit}
            onChange={(e) => setSalary(fromText, toText, e.target.value as PortalSalary["unit"])}
          >
            <option value="hour">zł/h</option>
            <option value="month">zł/mc</option>
          </select>
        </div>
        <span className="text-xs text-muted-foreground">
          Netto B2B; puste = ogłoszenie bez widełek.
        </span>
      </div>

      {problems.length > 0 ? (
        <ul role="alert" className="list-disc space-y-0.5 pl-5 text-xs text-destructive">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}
    </fieldset>
  );
}
