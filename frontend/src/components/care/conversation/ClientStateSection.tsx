"use client";

import { useCallback, useId, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  searchSkills,
  searchVendors,
  useClientAreas,
  type ClientProjectState,
  type ClientStateView,
} from "@/lib/api/care";
import { useClientOrg } from "@/lib/api/client-people";
import { apiErrorMessage } from "@/lib/api-error";
import { formatDayMonthPl, monthYearPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { TokenPicker } from "../TokenPicker";
import {
  STATE_ROWS,
  effectiveTechnologies,
  knownRows,
  techDiff,
  touchedRows,
  STATE_ROW_LABELS,
  type ClientStateForm,
  type StateMode,
  type StateRow,
} from "./conversation-form";

const NONE = "none";
const NEW_AREA = "new";

/** Tekst obecnego stanu wiersza; `null` = nic nie wiemy. */
export function stateValue(row: StateRow, state: ClientProjectState | null): string | null {
  if (!state) return null;
  switch (row) {
    case "area":
      return state.area?.name ?? null;
    case "manager":
      return state.manager
        ? `${state.manager.name}${state.manager.position ? ` · ${state.manager.position}` : ""}`
        : null;
    case "team": {
      const parts = [
        state.team_size ? `${state.team_size} osób` : null,
        state.team_externals != null ? `${state.team_externals} z zewnątrz` : null,
      ].filter(Boolean);
      return parts.length ? parts.join(" · ") : null;
    }
    case "technologies":
      return state.technologies.length ? state.technologies.map((tech) => tech.name).join(", ") : null;
    case "vendors":
      return state.vendors.length ? state.vendors.join(", ") : null;
    case "project_end":
      return state.project_end_month ? monthYearPl(state.project_end_month) : null;
  }
}

/** Formularz wiersza po „zmień” — startuje od obecnego stanu, żeby zmieniać, nie przepisywać. */
function prefill(row: StateRow, form: ClientStateForm, state: ClientProjectState | null): ClientStateForm {
  if (!state) return form;
  switch (row) {
    case "area":
      return { ...form, areaId: state.area?.id ?? null };
    case "manager":
      return { ...form, managerContactId: state.manager?.contact_id ?? null };
    case "team":
      return {
        ...form,
        teamSize: state.team_size ?? "",
        teamExternals: state.team_externals != null ? String(state.team_externals) : "",
      };
    case "technologies":
      return { ...form, skills: state.technologies.map((tech) => ({ id: tech.skill_id, name: tech.name })) };
    case "vendors":
      return { ...form, vendors: state.vendors.map((name) => ({ id: null, name })) };
    case "project_end":
      return { ...form, projectEndMonth: state.project_end_month ?? "" };
  }
}

function ModeButton({
  pressed,
  onClick,
  children,
  label,
}: {
  pressed: boolean;
  onClick: () => void;
  children: ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      aria-label={label}
      onClick={onClick}
      className={cn(
        "rounded-md border px-2 py-0.5 text-xs transition-colors",
        pressed
          ? "border-primary bg-primary/10 text-foreground"
          : "border-border text-muted-foreground hover:bg-muted",
      )}
    >
      {children}
    </button>
  );
}

interface ClientStateSectionProps {
  /** Technologie ostatniego stanu — bez żadnej karta się nie zapisze. */
  knownTechnologies: number;
  clientId: number | null;
  view: ClientStateView | undefined;
  loading: boolean;
  failed: boolean;
  form: ClientStateForm;
  onChange: (next: ClientStateForm) => void;
}

/** Technologie po „zmień”: zostają, „+ Azure” dochodzi, usunięte przekreślone (makieta P3). */
function TechDiffLine({ state, form }: { state: ClientProjectState | null; form: ClientStateForm }) {
  const diff = techDiff(state?.technologies ?? [], form.skills);
  if (!diff.kept.length && !diff.added.length && !diff.removed.length) {
    return <span className="block text-muted-foreground">bez technologii</span>;
  }
  const chip = "rounded-md border px-1.5 py-0.5 text-xs";
  return (
    <ul className="mt-0.5 flex flex-wrap gap-1" aria-label="Technologie po zmianie">
      {diff.kept.map((name) => (
        <li key={`k-${name}`} className={cn(chip, "border-border bg-muted/40")}>
          {name}
        </li>
      ))}
      {diff.added.map((name) => (
        <li key={`a-${name}`} className={cn(chip, "border-success/30 bg-success-muted text-success-muted-foreground")}>
          + {name}
        </li>
      ))}
      {diff.removed.map((name) => (
        <li key={`r-${name}`} className={cn(chip, "border-border text-muted-foreground line-through")}>
          <span className="sr-only">usunięta: </span>
          {name}
        </li>
      ))}
    </ul>
  );
}

/**
 * „Co u klienta” — dawna karta technologiczna wypełniona ostatnim stanem
 * (makieta P3: „potwierdzasz, nie przepisujesz”). Wiersz bez kliknięcia =
 * „bez zmian” i zapisze się jako potwierdzony datą rozmowy; „zmień” otwiera
 * pole, „cofnij” wraca do ostatniego stanu. „Nie rozmawialiśmy o kliencie”
 * wyłącza całą sekcję (nic się nie zapisuje ani nie potwierdza).
 */
export function ClientStateSection({
  knownTechnologies,
  clientId,
  view,
  loading,
  failed,
  form,
  onChange,
}: ClientStateSectionProps) {
  const ids = { area: useId(), newArea: useId(), manager: useId(), size: useId(), externals: useId(), end: useId() };
  const state = view?.state ?? null;
  const modes = form.modes;
  const known = knownRows(state);
  const areas = useClientAreas(clientId ?? 0, modes.area === "change" && clientId != null);
  // Bez klienta nie ma czego wczytywać — „Nowy dział…” jak dotąd.
  const areasReady = areas.isSuccess || clientId == null;
  const org = useClientOrg(clientId ?? 0, modes.manager === "change" && clientId != null);
  const skillSearch = useCallback((q: string) => searchSkills(q), []);
  const vendorSearch = useCallback((q: string) => searchVendors(q), []);
  const people = (org.data?.departments ?? []).flatMap((department) => department.people);

  const setMode = (row: StateRow, mode: StateMode | undefined) => {
    const nextModes = { ...modes };
    if (mode) nextModes[row] = mode;
    else delete nextModes[row];
    const base = { ...form, modes: nextModes };
    onChange(mode === "change" && modes[row] !== "change" ? prefill(row, base, state) : base);
  };
  const sourceDay = view?.source ? formatDayMonthPl(view.source.on) : null;

  const editor = (row: StateRow): ReactNode => {
    switch (row) {
      case "area":
        // Awaria listy działów nie może wyglądać jak klient bez działów z „Nowy dział…”
        // — inna pisownia założyłaby drugi dział (audyt 22.10, F88).
        if (areas.isError) {
          return (
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs text-muted-foreground">
                {apiErrorMessage(areas.error, "Nie udało się wczytać działów klienta.")}
              </p>
              <Button size="sm" variant="outline" className="h-7 px-2.5" onClick={() => void areas.refetch()}>
                Ponów
              </Button>
            </div>
          );
        }
        return (
          <div className="grid gap-2 sm:grid-cols-2">
            <Select
              value={form.areaId == null ? NONE : String(form.areaId)}
              onValueChange={(next) =>
                onChange({ ...form, areaId: next === NONE ? null : next === NEW_AREA ? "new" : Number(next) })
              }
            >
              <SelectTrigger id={ids.area} aria-label="Dział u klienta">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>{areasReady ? "Wybierz dział…" : "Wczytywanie działów…"}</SelectItem>
                {(areas.data ?? []).map((area) => (
                  <SelectItem key={area.id} value={String(area.id)}>
                    {area.name}
                  </SelectItem>
                ))}
                {areasReady ? <SelectItem value={NEW_AREA}>Nowy dział…</SelectItem> : null}
              </SelectContent>
            </Select>
            {form.areaId === "new" ? (
              <Input
                id={ids.newArea}
                aria-label="Nazwa nowego działu"
                value={form.newAreaName}
                maxLength={120}
                placeholder="np. Płatności kartowe"
                onChange={(event) => onChange({ ...form, newAreaName: event.target.value })}
              />
            ) : null}
          </div>
        );
      case "manager":
        return org.isError ? (
          <p className="text-xs text-muted-foreground">
            Listy osób klienta nie udało się wczytać — menedżera wskażesz w „Ludzie i technologie” klienta.
          </p>
        ) : (
          <Select
            value={form.managerContactId == null ? NONE : String(form.managerContactId)}
            onValueChange={(next) => onChange({ ...form, managerContactId: next === NONE ? null : Number(next) })}
          >
            <SelectTrigger id={ids.manager} aria-label="Menedżer u klienta">
              <SelectValue placeholder={org.isLoading ? "Wczytywanie osób…" : "Wybierz osobę…"} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Wybierz osobę…</SelectItem>
              {people.map((person) => (
                <SelectItem key={person.id} value={String(person.id)}>
                  {person.name}
                  {person.position ? ` · ${person.position}` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        );
      case "team":
        return (
          <div className="grid grid-cols-2 gap-2">
            <Input
              id={ids.size}
              aria-label="Wielkość zespołu"
              value={form.teamSize}
              maxLength={20}
              placeholder="ile osób, np. 8"
              onChange={(event) => onChange({ ...form, teamSize: event.target.value })}
            />
            <Input
              id={ids.externals}
              aria-label="Osób z zewnątrz"
              type="number"
              min={0}
              inputMode="numeric"
              value={form.teamExternals}
              placeholder="z zewnątrz"
              onChange={(event) => onChange({ ...form, teamExternals: event.target.value })}
            />
          </div>
        );
      case "technologies":
        return (
          <TokenPicker
            label="Technologie w projekcie"
            value={form.skills}
            onChange={(next) => onChange({ ...form, skills: next })}
            search={skillSearch}
            placeholder="Szukaj w słowniku…"
            freeTextHint="do przejrzenia"
          />
        );
      case "vendors":
        return (
          <TokenPicker
            label="Inni dostawcy u klienta"
            value={form.vendors}
            onChange={(next) => onChange({ ...form, vendors: next })}
            search={vendorSearch}
            placeholder="Szukaj dostawcy…"
            freeTextHint="nowy"
          />
        );
      case "project_end":
        return (
          <Input
            id={ids.end}
            aria-label="Koniec projektu (miesiąc)"
            type="month"
            value={form.projectEndMonth}
            onChange={(event) => onChange({ ...form, projectEndMonth: event.target.value })}
          />
        );
    }
  };

  return (
    <section aria-label="Co u klienta" className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">Co u klienta</h3>
          <p className="text-xs text-muted-foreground">
            {view?.source
              ? `stan ${view.source.kind === "tech_card" ? "z karty technologicznej" : "z rozmowy"} ${sourceDay}${
                  view.source.author_name ? ` · ${view.source.author_name}` : ""
                } — potwierdź albo zmień`
              : state
                ? "Znamy tylko to, co jest na kontrakcie — uzupełnij resztę z rozmowy."
                : loading
                  ? "Wczytywanie ostatniego stanu…"
                  : failed
                    ? "Nie udało się wczytać ostatniego stanu — możesz go uzupełnić od zera."
                    : "Nic jeszcze nie wiemy o projekcie — uzupełnij to, czego się dowiesz."}
          </p>
        </div>
        {state ? (
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs"
            aria-pressed={form.skipped}
            onClick={() => onChange({ ...form, skipped: !form.skipped })}
          >
            {form.skipped ? "Rozmawialiśmy o kliencie" : "Nie rozmawialiśmy o kliencie"}
          </Button>
        ) : null}
      </div>
      {form.skipped ? (
        <p className="text-xs text-muted-foreground">
          Stan u klienta zostaje jak był — bez potwierdzenia z tej rozmowy.
        </p>
      ) : (
        <ul className="divide-y divide-border/60 rounded-md border border-border/60">
          {STATE_ROWS.map((row) => {
            const value = stateValue(row, state);
            const mode = modes[row];
            const changing = mode === "change";
            return (
              <li key={row} className="space-y-1.5 px-3 py-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 text-sm">
                    <span className="block text-xs text-muted-foreground">{STATE_ROW_LABELS[row]}</span>
                    {row === "technologies" && changing ? (
                      <TechDiffLine state={state} form={form} />
                    ) : (
                      <span className={cn("block", value ? "text-foreground" : "text-muted-foreground")}>
                        {value ?? "nie wiemy"}
                      </span>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5" role="group" aria-label={STATE_ROW_LABELS[row]}>
                    {changing ? (
                      <>
                        <span className="text-xs font-medium text-primary">zmieniono</span>
                        <ModeButton
                          pressed={false}
                          label={`${STATE_ROW_LABELS[row]}: cofnij`}
                          onClick={() => setMode(row, undefined)}
                        >
                          cofnij
                        </ModeButton>
                      </>
                    ) : (
                      <>
                        {known.includes(row) ? (
                          <span className="text-xs text-muted-foreground">bez zmian</span>
                        ) : null}
                        <ModeButton
                          pressed={false}
                          label={`${STATE_ROW_LABELS[row]}: ${value != null ? "zmień" : "uzupełnij"}`}
                          onClick={() => setMode(row, "change")}
                        >
                          {value != null ? "zmień" : "uzupełnij"}
                        </ModeButton>
                      </>
                    )}
                  </div>
                </div>
                {changing ? editor(row) : null}
              </li>
            );
          })}
        </ul>
      )}
      {touchedRows(form, known).length && effectiveTechnologies(form, knownTechnologies) === 0 ? (
        <p className="text-xs text-warning-muted-foreground">
          Bez technologii zapisze się tylko zmiana menedżera — reszta stanu u klienta czeka na co najmniej
          jedną technologię („Technologie” → „uzupełnij”).
        </p>
      ) : null}
    </section>
  );
}
