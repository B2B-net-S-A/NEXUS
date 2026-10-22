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
import { formatIsoDatePl, monthYearPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { TokenPicker } from "../TokenPicker";
import {
  STATE_ROWS,
  effectiveTechnologies,
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
        state.team_externals != null ? `z zewnątrz ${state.team_externals}` : null,
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

/**
 * „Co u klienta” — dawna karta technologiczna wypełniona ostatnim stanem.
 * Przy każdym wierszu „bez zmian” albo „zmień”; nieruszona sekcja nic nie
 * zapisuje (karta technologiczna powstaje tylko po potwierdzeniu albo zmianie).
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
  const areas = useClientAreas(clientId ?? 0, modes.area === "change" && clientId != null);
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
  const allSame = () => {
    const nextModes: ClientStateForm["modes"] = {};
    for (const row of STATE_ROWS) {
      if (modes[row] === "change") nextModes[row] = "change";
      else if (stateValue(row, state) != null) nextModes[row] = "same";
    }
    onChange({ ...form, modes: nextModes });
  };

  const editor = (row: StateRow): ReactNode => {
    switch (row) {
      case "area":
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
                <SelectItem value={NONE}>Wybierz dział…</SelectItem>
                {(areas.data ?? []).map((area) => (
                  <SelectItem key={area.id} value={String(area.id)}>
                    {area.name}
                  </SelectItem>
                ))}
                <SelectItem value={NEW_AREA}>Nowy dział…</SelectItem>
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
        <h3 className="text-sm font-semibold text-foreground">Co u klienta</h3>
        {state ? (
          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={allSame}>
            Wszystko bez zmian
          </Button>
        ) : null}
      </div>
      {view?.source ? (
        <p className="text-xs text-muted-foreground">
          Ostatni stan {view.source.kind === "tech_card" ? "z karty technologicznej" : "z rozmowy"}{" "}
          {formatIsoDatePl(view.source.on)}
          {view.source.author_name ? ` · ${view.source.author_name}` : ""}. Zapisze się tylko to, co
          potwierdzisz albo zmienisz.
        </p>
      ) : state ? (
        <p className="text-xs text-muted-foreground">
          Znamy tylko to, co jest na kontrakcie — uzupełnij resztę z rozmowy.
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          {loading
            ? "Wczytywanie ostatniego stanu…"
            : failed
              ? "Nie udało się wczytać ostatniego stanu — możesz go uzupełnić od zera."
              : "Nic jeszcze nie wiemy o projekcie — uzupełnij to, czego się dowiesz."}
        </p>
      )}
      <ul className="divide-y divide-border/60 rounded-md border border-border/60">
        {STATE_ROWS.map((row) => {
          const value = stateValue(row, state);
          const mode = modes[row];
          return (
            <li key={row} className="space-y-1.5 px-3 py-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 text-sm">
                  <span className="block text-xs text-muted-foreground">{STATE_ROW_LABELS[row]}</span>
                  <span className={cn("block", value ? "text-foreground" : "text-muted-foreground")}>
                    {value ?? "nie wiemy"}
                  </span>
                </div>
                <div className="flex shrink-0 gap-1" role="group" aria-label={STATE_ROW_LABELS[row]}>
                  {value != null ? (
                    <ModeButton
                      pressed={mode === "same"}
                      label={`${STATE_ROW_LABELS[row]}: bez zmian`}
                      onClick={() => setMode(row, mode === "same" ? undefined : "same")}
                    >
                      bez zmian
                    </ModeButton>
                  ) : null}
                  <ModeButton
                    pressed={mode === "change"}
                    label={`${STATE_ROW_LABELS[row]}: ${value != null ? "zmień" : "uzupełnij"}`}
                    onClick={() => setMode(row, mode === "change" ? undefined : "change")}
                  >
                    {value != null ? "zmień" : "uzupełnij"}
                  </ModeButton>
                </div>
              </div>
              {mode === "change" ? editor(row) : null}
            </li>
          );
        })}
      </ul>
      {touchedRows(form).length && effectiveTechnologies(form, knownTechnologies) === 0 ? (
        <p className="text-xs text-warning-muted-foreground">
          Bez technologii zapisze się tylko zmiana menedżera — reszta stanu u klienta czeka na co najmniej
          jedną technologię („Technologie” → „uzupełnij”).
        </p>
      ) : null}
    </section>
  );
}
