"use client";

/**
 * „Lokalizacja lub tryb pracy” w oknie odrzucenia — karta dojazdu (wariant D,
 * decyzja Artura 27.11.2026, makieta https://claude.ai/artifact/66p2W5u7cB9oPfC8ZEpoPm).
 *
 * Najpierw „Co nie pasuje?”: „Za daleko do biura” pyta, gdzie osoba mieszka
 * (domyślnie miasto z profilu), do jakich biur dojedzie, ile dni, o przeprowadzkę
 * i dojazd okazjonalny — wszystko poza powodem stoi na „Nie pytałem” i niczego
 * nie zapisuje. „Chce mniej dni w biurze” działa jak dotąd (dni → tryb pracy)
 * plus zgoda na więcej dni przy wyjątkowym projekcie. Bez tego podziału okno
 * zapisywało każdemu „Tylko zdalnie” (141 z 224 osób na kopii produkcji),
 * a miasto z notatki nie trafiało nigdzie.
 */

import * as React from "react";
import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  RejectionWorkModeField,
  type RejectionWorkModeChoice,
  type RejectionWorkModeIssue,
  type RejectionWorkModeJob,
  type RejectionWorkModeProfile,
} from "@/components/v2/modals/RejectionWorkModeField";
import type { RejectionResidenceProfile } from "@/components/v2/modals/RejectionResidenceField";
import api from "@/lib/api";
import { addCity, relocationLine, sameCity } from "@/lib/commute-preferences";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { formatWorkMode, jobWorkModeLine, officeDaysChoiceLabel } from "@/lib/work-mode";

/** Limity jak w `PipelineMove` (serwer odpowie 422 powyżej). */
export const MAX_COMMUTE_OFFICE_CITIES = 10;
export const MAX_RELOCATION_TARGETS = 5;
/** „Ile dni w biurze w tych miastach?” — 0–5, 5 to już biuro. */
const DISTANCE_DAY_CHOICES = [0, 1, 2, 3, 4, 5];

/** Odpowiedzi okna, zanim staną się `RejectionWorkModeChoice`. */
export interface RejectionWorkModeDraft {
  issue: RejectionWorkModeIssue | null;
  /** „Chce mniej dni w biurze”: dni jak dotąd, domyślnie „Tylko zdalnie”. */
  officeDays: number;
  /** „Za daleko”: dni w miastach, do których dojedzie; `null` = „Nie pytałem”. */
  distanceDays: number | null;
  /** `null` — rekruter nie ruszał pola, obowiązuje miasto z profilu. */
  residenceCity: string | null;
  officeCities: string[];
  occasionalCommute: boolean | null;
  relocationWilling: boolean | null;
  relocationTargets: string[];
  acceptsMoreOfficeDays: boolean | null;
}

export const EMPTY_WORK_MODE_DRAFT: RejectionWorkModeDraft = {
  issue: null,
  officeDays: 0,
  distanceDays: null,
  residenceCity: null,
  officeCities: [],
  occasionalCommute: null,
  relocationWilling: null,
  relocationTargets: [],
  acceptsMoreOfficeDays: null,
};

/** Miasto z profilu, od którego startuje „Gdzie mieszka?”. */
export function profileCityOf(profile: RejectionResidenceProfile | null | undefined): string | null {
  if (!profile) return null;
  const city = profile.canonicalCity !== undefined ? profile.canonicalCity : profile.city;
  return city?.trim() || null;
}

/** Wybór do ruchu karty; `null`, dopóki nie ma odpowiedzi na „Co nie pasuje?”. */
export function workModeChoiceFromDraft(
  draft: RejectionWorkModeDraft,
  opts: { several: boolean; profileCity: string | null; saveToProfile: boolean },
): RejectionWorkModeChoice | null {
  if (!draft.issue) return null;
  const base: RejectionWorkModeChoice = {
    issue: draft.issue,
    maxOnsiteDays: null,
    saveToProfile: opts.saveToProfile,
    residenceCity: null,
    officeCities: [],
    occasionalCommute: null,
    relocationWilling: null,
    relocationTargets: [],
    acceptsMoreOfficeDays: null,
  };
  if (draft.issue === "office_days") {
    return {
      ...base,
      maxOnsiteDays: draft.officeDays,
      acceptsMoreOfficeDays: opts.several ? null : draft.acceptsMoreOfficeDays,
    };
  }
  // Kilka osób naraz: samo „co nie pasuje” — miasto i reszta są osobiste.
  if (opts.several) return base;
  const city = (draft.residenceCity ?? opts.profileCity ?? "").trim();
  return {
    ...base,
    maxOnsiteDays: draft.distanceDays,
    residenceCity: city || null,
    officeCities: draft.officeCities,
    occasionalCommute: draft.occasionalCommute,
    relocationWilling: draft.relocationWilling,
    relocationTargets: draft.relocationWilling === true ? draft.relocationTargets : [],
  };
}

function daysPhrase(days: number): string {
  return days === 0 ? "tylko zdalnie" : `do ${days}`;
}

function change(label: string, before: string | null | undefined, after: string): string {
  if (before === undefined) return `${label} → ${after}`;
  if (before !== null && before === after) return `${label}: ${after} bez zmian`;
  return `${label}: ${before ?? "nie uzupełniono"} → ${after}`;
}

/**
 * „Miasto: Kraków bez zmian”, „Dojedzie do biura: nie uzupełniono → Kraków,
 * Katowice”, „Dni w biurze: do 5 → do 3” — tylko to, co okno zapisze.
 * Profil `undefined` (niewczytany) — sama nowa wartość.
 */
export function distanceProfileChanges(
  choice: RejectionWorkModeChoice,
  profileWorkMode: RejectionWorkModeProfile | null | undefined,
  profileResidence: RejectionResidenceProfile | null | undefined,
): string[] {
  const known = profileResidence !== undefined;
  const commute = profileResidence?.commute;
  const lines: string[] = [];
  if (choice.residenceCity) {
    const before = known ? profileCityOf(profileResidence) : undefined;
    lines.push(
      before && sameCity(before, choice.residenceCity)
        ? `Miasto: ${before} bez zmian`
        : change("Miasto", before, choice.residenceCity),
    );
  }
  if (choice.officeCities?.length) {
    const before = known ? (commute?.officeCities.length ? commute.officeCities.join(", ") : null) : undefined;
    lines.push(change("Dojedzie do biura", before, choice.officeCities.join(", ")));
  }
  if (choice.maxOnsiteDays != null) {
    const before =
      profileWorkMode === undefined
        ? undefined
        : profileWorkMode?.days != null
          ? daysPhrase(profileWorkMode.days)
          : null;
    lines.push(change("Dni w biurze", before, daysPhrase(choice.maxOnsiteDays)));
  }
  if (choice.occasionalCommute != null) {
    const phrase = (value: boolean) => (value ? "raz w miesiącu" : "nie");
    const before = known
      ? commute?.occasionalCommute != null
        ? phrase(commute.occasionalCommute)
        : null
      : undefined;
    lines.push(change("Dojazd do innego miasta", before, phrase(choice.occasionalCommute)));
  }
  if (choice.relocationWilling != null) {
    const after =
      relocationLine({ willing: choice.relocationWilling, targets: choice.relocationTargets ?? [] }) ?? "";
    const before = known ? relocationLine(commute?.relocation ?? null) : undefined;
    lines.push(change("Przeprowadzka", before, after));
  }
  return lines;
}

// ── Pola ──────────────────────────────────────────────────────────────────

type Tri = "unasked" | "yes" | "no";

function toTri(value: boolean | null): Tri {
  return value === null ? "unasked" : value ? "yes" : "no";
}

function fromTri(value: string): boolean | null {
  return value === "yes" ? true : value === "no" ? false : null;
}

function Pills({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: ReadonlyArray<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <RadioGroup
      value={value}
      onValueChange={onChange}
      aria-label={label}
      className="flex flex-wrap gap-2"
    >
      {options.map((option) => (
        <label
          key={option.value}
          className={`flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1 text-sm ${
            value === option.value
              ? "border-primary bg-primary/5 font-medium"
              : "border-border hover:bg-accent"
          }`}
        >
          <RadioGroupItem value={option.value} />
          {option.label}
        </label>
      ))}
    </RadioGroup>
  );
}

function OptionalLabel({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children} <span className="text-xs font-normal text-muted-foreground">opcjonalnie</span>
    </>
  );
}

/** Podpowiedzi z polskiego spisu miejscowości (`/api/candidates/places/suggest`);
 *  awaria = brak podpowiedzi, pole działa dalej. */
function usePlaceSuggestions(text: string): string[] {
  const query = useDebouncedValue(text.trim(), 300);
  const { data } = useQuery<{ items?: Array<{ name: string }> }>({
    queryKey: ["places-suggest", query],
    queryFn: () =>
      api.get("/api/candidates/places/suggest", { params: { q: query } }).then((r) => r.data),
    enabled: query.length >= 2,
    staleTime: 5 * 60_000,
    retry: false,
  });
  return Array.from(new Set((data?.items ?? []).map((p) => p.name)));
}

function CitySuggestions({ id, text }: { id: string; text: string }) {
  const names = usePlaceSuggestions(text);
  return (
    <datalist id={id}>
      {names.map((name) => (
        <option key={name} value={name} />
      ))}
    </datalist>
  );
}

function CityChips({
  label,
  cities,
  onChange,
  max,
}: {
  label: string;
  cities: string[];
  onChange: (cities: string[]) => void;
  max: number;
}) {
  const listId = useId();
  const [draft, setDraft] = useState("");
  const add = () => {
    const next = addCity(cities, draft, max);
    if (next) onChange(next);
    setDraft("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {cities.map((city, index) => (
        <span
          key={city}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 py-0.5 pl-2.5 pr-1 text-sm"
        >
          {city}
          <button
            type="button"
            aria-label={`Usuń miasto: ${city}`}
            onClick={() => onChange(cities.filter((_, i) => i !== index))}
            className="hit-area rounded-full p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        </span>
      ))}
      {cities.length < max ? (
        <span className="inline-flex min-w-0 items-center gap-1">
          <Input
            aria-label={label}
            list={listId}
            placeholder="+ miasto"
            autoComplete="off"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            // Miasto wpisane bez Enter nie przepada przed „Potwierdź”.
            onBlur={() => draft.trim() && add()}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
            className="h-8 w-36"
          />
          <Button type="button" size="sm" variant="outline" onClick={add} disabled={!draft.trim()}>
            Dodaj
          </Button>
          <CitySuggestions id={listId} text={draft} />
        </span>
      ) : null}
    </div>
  );
}

const ISSUE_OPTIONS: ReadonlyArray<{ value: RejectionWorkModeIssue; label: string }> = [
  { value: "distance", label: "Za daleko do biura" },
  { value: "office_days", label: "Chce mniej dni w biurze" },
];

const TRI_YES_NO = [
  { value: "unasked", label: "Nie pytałem" },
  { value: "yes", label: "Tak" },
  { value: "no", label: "Nie" },
] as const;

interface Props {
  job: RejectionWorkModeJob | null;
  /** Tylko przy jednej osobie; `undefined` — niewczytany albo kilka osób. */
  profileWorkMode?: RejectionWorkModeProfile | null;
  profileResidence?: RejectionResidenceProfile | null;
  several: boolean;
  draft: RejectionWorkModeDraft;
  onDraftChange: (draft: RejectionWorkModeDraft) => void;
  saveToProfile: boolean;
  onSaveToProfileChange: (save: boolean) => void;
}

export function RejectionWorkModeIssueField({
  job,
  profileWorkMode,
  profileResidence,
  several,
  draft,
  onDraftChange,
  saveToProfile,
  onSaveToProfileChange,
}: Props) {
  const cityId = useId();
  const cityListId = useId();
  const set = (patch: Partial<RejectionWorkModeDraft>) => onDraftChange({ ...draft, ...patch });
  const jobLine = jobWorkModeLine(job?.remotePolicy, job?.onsiteDaysPerWeek);
  const profileCity = profileCityOf(profileResidence);
  const cityValue = draft.residenceCity ?? profileCity ?? "";

  return (
    <div
      data-testid="rejection-work-mode-issue"
      data-tour="rejection.commute-issue"
      className="ml-6 space-y-3 rounded-md border border-border border-l-2 border-l-primary px-3 py-2.5"
    >
      <FormField
        label="Co nie pasuje?"
        required
        description={
          jobLine && draft.issue !== "office_days" ? `Ta rekrutacja: ${jobLine}.` : undefined
        }
      >
        <Pills
          label="Co nie pasuje"
          value={draft.issue ?? ""}
          options={ISSUE_OPTIONS}
          onChange={(value) => set({ issue: value as RejectionWorkModeIssue })}
        />
      </FormField>

      {draft.issue === "office_days" ? (
        <RejectionWorkModeField
          job={job}
          profile={several ? undefined : profileWorkMode}
          several={several}
          days={draft.officeDays}
          onDaysChange={(officeDays) => set({ officeDays })}
          saveToProfile={saveToProfile}
          onSaveToProfileChange={onSaveToProfileChange}
          framed={false}
          extra={
            several ? null : (
              <FormField
                label={
                  <OptionalLabel>Zgodzi się na więcej dni przy wyjątkowym projekcie?</OptionalLabel>
                }
              >
                <Pills
                  label="Zgodzi się na więcej dni przy wyjątkowym projekcie"
                  value={toTri(draft.acceptsMoreOfficeDays)}
                  options={TRI_YES_NO}
                  onChange={(value) => set({ acceptsMoreOfficeDays: fromTri(value) })}
                />
              </FormField>
            )
          }
          saveExtra={
            !several && draft.acceptsMoreOfficeDays !== null
              ? `Więcej dni przy wyjątkowym projekcie → ${draft.acceptsMoreOfficeDays ? "tak" : "nie"}`
              : null
          }
        />
      ) : null}

      {draft.issue === "distance" && several ? (
        <p className="text-xs text-muted-foreground" data-testid="rejection-commute-several">
          Przy kilku osobach okno nie pyta o miasto. Tryb pracy na profilach zostaje bez zmian.
        </p>
      ) : null}

      {draft.issue === "distance" && !several ? (
        <DistanceQuestions
          draft={draft}
          set={set}
          cityId={cityId}
          cityListId={cityListId}
          cityValue={cityValue}
          profileWorkMode={profileWorkMode}
          profileResidence={profileResidence}
          saveToProfile={saveToProfile}
          onSaveToProfileChange={onSaveToProfileChange}
          choice={workModeChoiceFromDraft(draft, { several, profileCity, saveToProfile })}
        />
      ) : null}
    </div>
  );
}

function DistanceQuestions({
  draft,
  set,
  cityId,
  cityListId,
  cityValue,
  profileWorkMode,
  profileResidence,
  saveToProfile,
  onSaveToProfileChange,
  choice,
}: {
  draft: RejectionWorkModeDraft;
  set: (patch: Partial<RejectionWorkModeDraft>) => void;
  cityId: string;
  cityListId: string;
  cityValue: string;
  profileWorkMode?: RejectionWorkModeProfile | null;
  profileResidence?: RejectionResidenceProfile | null;
  saveToProfile: boolean;
  onSaveToProfileChange: (save: boolean) => void;
  choice: RejectionWorkModeChoice | null;
}) {
  const changes = choice ? distanceProfileChanges(choice, profileWorkMode, profileResidence) : [];
  const currentWorkMode = profileWorkMode
    ? formatWorkMode(profileWorkMode.modes, profileWorkMode.days)
    : null;
  const dayOptions = [
    { value: "unasked", label: "Nie pytałem" },
    ...DISTANCE_DAY_CHOICES.map((days) => ({
      value: String(days),
      label: officeDaysChoiceLabel(days),
    })),
  ];

  return (
    <div className="space-y-3" data-testid="rejection-commute">
      <FormField label="Gdzie mieszka?" htmlFor={cityId}>
        <Input
          id={cityId}
          list={cityListId}
          autoComplete="off"
          placeholder="np. Kraków"
          maxLength={120}
          value={cityValue}
          onChange={(e) => set({ residenceCity: e.target.value })}
          className="h-9 max-w-xs"
        />
        <CitySuggestions id={cityListId} text={draft.residenceCity ?? ""} />
      </FormField>

      <FormField label={<OptionalLabel>Do jakich biur dojedzie?</OptionalLabel>}>
        <CityChips
          label="Do jakich biur dojedzie"
          cities={draft.officeCities}
          onChange={(officeCities) => set({ officeCities })}
          max={MAX_COMMUTE_OFFICE_CITIES}
        />
      </FormField>

      <FormField label={<OptionalLabel>Ile dni w biurze w tych miastach?</OptionalLabel>}>
        <Pills
          label="Ile dni w biurze w tych miastach"
          value={draft.distanceDays === null ? "unasked" : String(draft.distanceDays)}
          options={dayOptions}
          onChange={(value) => set({ distanceDays: value === "unasked" ? null : Number(value) })}
        />
      </FormField>

      <FormField label={<OptionalLabel>Przeprowadzka?</OptionalLabel>}>
        <Pills
          label="Przeprowadzka"
          value={toTri(draft.relocationWilling)}
          options={[
            { value: "unasked", label: "Nie pytałem" },
            { value: "no", label: "Nie" },
            { value: "yes", label: "Tak, do…" },
          ]}
          onChange={(value) => set({ relocationWilling: fromTri(value) })}
        />
        {draft.relocationWilling === true ? (
          <CityChips
            label="Dokąd się przeprowadzi"
            cities={draft.relocationTargets}
            onChange={(relocationTargets) => set({ relocationTargets })}
            max={MAX_RELOCATION_TARGETS}
          />
        ) : null}
      </FormField>

      <FormField label={<OptionalLabel>Dojazd okazjonalny do innego miasta?</OptionalLabel>}>
        <Pills
          label="Dojazd okazjonalny do innego miasta"
          value={toTri(draft.occasionalCommute)}
          options={[
            { value: "unasked", label: "Nie pytałem" },
            { value: "yes", label: "Raz w miesiącu tak" },
            { value: "no", label: "Nie" },
          ]}
          onChange={(value) => set({ occasionalCommute: fromTri(value) })}
        />
      </FormField>

      <label className="flex cursor-pointer items-start gap-2 rounded-md p-1.5 text-sm hover:bg-primary/10">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))] text-primary focus:ring-primary"
          checked={saveToProfile}
          onChange={(e) => onSaveToProfileChange(e.target.checked)}
        />
        <span className="min-w-0">
          Zapisz na profilu kandydata
          {changes.length ? ":" : null}
          {saveToProfile ? (
            changes.length ? (
              <span className="block" data-testid="rejection-commute-changes">
                {changes.map((line) => (
                  <span key={line} className="block break-words font-medium">
                    {line}
                  </span>
                ))}
              </span>
            ) : (
              <span className="block text-xs text-muted-foreground" data-testid="rejection-commute-changes">
                Nic się nie zmieni — odpowiedzi „Nie pytałem” niczego nie zapisują.
              </span>
            )
          ) : null}
        </span>
      </label>

      {draft.distanceDays === null && profileWorkMode !== undefined ? (
        <p className="text-xs text-muted-foreground" data-testid="rejection-commute-work-mode">
          Tryb pracy na profilu zostaje: {currentWorkMode ?? "nie uzupełniono"}.
        </p>
      ) : null}
    </div>
  );
}
