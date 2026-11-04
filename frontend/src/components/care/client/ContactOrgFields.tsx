"use client";

import { useId } from "react";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ClientOrg, ContactOrgPayload, OrgPerson } from "@/lib/api/client-people";
import type { PersonRef } from "@/lib/api/care";

import { managerOptions, orgPeople } from "../client-people-format";

const NONE = "none";
const NEW_AREA = "__new__";

/**
 * „Dział” i „Podlega pod” w formularzu kontaktu klienta (22.10.2026, przy
 * otwartym module opieki). Dział wybiera się ze słownika działów klienta
 * (`client_areas`) albo zakłada „Nowy dział…”; tekst `department` kontaktu
 * zostaje i stoi pod polem jako podpowiedź. Zapis idzie po zapisie kontaktu
 * przez `PATCH /api/care/clients/{id}/contacts/{contact_id}` — tylko to, co
 * się zmieniło (`contactOrgPayload`).
 */
export interface ContactOrgDraft {
  areaId: number | null;
  /** Wpisywana nazwa nowego działu; niepusta = „Nowy dział…”. */
  newAreaName: string;
  addingArea: boolean;
  reportsToId: number | null;
}

export const EMPTY_CONTACT_ORG: ContactOrgDraft = {
  areaId: null,
  newAreaName: "",
  addingArea: false,
  reportsToId: null,
};

/** Stan pól dla kontaktu z drzewa (edycja) albo pusty (nowy kontakt). */
export function contactOrgDraftFor(org: ClientOrg | null, contactId: number | null): ContactOrgDraft {
  const person = contactId != null && org ? orgPeople(org).find((p) => p.id === contactId) : null;
  if (!person) return EMPTY_CONTACT_ORG;
  return {
    areaId: person.area_id,
    newAreaName: "",
    addingArea: false,
    reportsToId: person.reports_to?.id ?? null,
  };
}

/**
 * Ciało `PATCH …/contacts/{id}` z różnicy pól, `null` = nic do zapisania.
 * Nowy dział wygrywa z wybranym z listy (pole nazwy widać tylko po „Nowy dział…”).
 */
export function contactOrgPayload(
  draft: ContactOrgDraft,
  initial: ContactOrgDraft,
): ContactOrgPayload | null {
  const payload: ContactOrgPayload = {};
  const newName = draft.addingArea ? draft.newAreaName.trim() : "";
  if (newName) payload.new_area_name = newName;
  else if (draft.areaId !== initial.areaId) payload.client_area_id = draft.areaId;
  if (draft.reportsToId !== initial.reportsToId) {
    payload.reports_to_contact_id = draft.reportsToId;
  }
  return Object.keys(payload).length ? payload : null;
}

/** Kto może być przełożonym: osoby klienta bez samej osoby i jej podwładnych. */
function reportsToOptions(org: ClientOrg, contactId: number | null): PersonRef[] {
  const people = orgPeople(org);
  const person = contactId != null ? people.find((p) => p.id === contactId) : null;
  if (person) return managerOptions(people, person);
  return people
    .map((p) => ({ id: p.id, name: p.name }))
    .sort((a, b) => a.name.localeCompare(b.name, "pl"));
}

/** Dział z listy o tej samej nazwie co tekst kontaktu (podpowiedź „Przypisz: X”). */
function matchingArea(org: ClientOrg, text: string | null | undefined) {
  const key = (text ?? "").trim().toLocaleLowerCase("pl");
  if (!key) return null;
  return org.areas.find((area) => area.name.trim().toLocaleLowerCase("pl") === key) ?? null;
}

export function ContactOrgFields({
  org,
  contactId,
  departmentText,
  draft,
  onChange,
  disabled = false,
}: {
  org: ClientOrg;
  contactId: number | null;
  departmentText: string | null;
  draft: ContactOrgDraft;
  onChange: (next: ContactOrgDraft) => void;
  disabled?: boolean;
}) {
  const ids = { area: useId(), reports: useId(), name: useId() };
  const hint = matchingArea(org, departmentText);
  const people: OrgPerson[] = orgPeople(org);
  const options = reportsToOptions(org, contactId);
  // Przełożony spoza listy (np. podwładny po zmianie w drzewie) zostaje widoczny.
  const current =
    draft.reportsToId != null && !options.some((o) => o.id === draft.reportsToId)
      ? people.find((p) => p.id === draft.reportsToId) ?? null
      : null;
  const label = "text-xs font-semibold text-muted-foreground block mb-1";
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" data-contact-org-fields>
      <div>
        <label id={ids.area} className={label}>
          Dział
        </label>
        <Select
          value={draft.addingArea ? NEW_AREA : draft.areaId != null ? String(draft.areaId) : NONE}
          disabled={disabled}
          onValueChange={(next) =>
            next === NEW_AREA
              ? onChange({ ...draft, addingArea: true })
              : onChange({
                  ...draft,
                  addingArea: false,
                  newAreaName: "",
                  areaId: next === NONE ? null : Number(next),
                })
          }
        >
          <SelectTrigger aria-labelledby={ids.area} className="h-8">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>Bez działu</SelectItem>
            {org.areas.map((area) => (
              <SelectItem key={area.id} value={String(area.id)}>
                {area.name}
              </SelectItem>
            ))}
            <SelectItem value={NEW_AREA}>Nowy dział…</SelectItem>
          </SelectContent>
        </Select>
        {draft.addingArea ? (
          <Input
            id={ids.name}
            aria-label="Nazwa nowego działu"
            className="mt-1.5 h-8"
            maxLength={120}
            value={draft.newAreaName}
            placeholder="np. Płatności"
            disabled={disabled}
            onChange={(event) => onChange({ ...draft, newAreaName: event.target.value })}
          />
        ) : null}
        {departmentText ? (
          <p className="mt-1 text-xs text-muted-foreground">
            W kontakcie: „{departmentText}”.
            {hint && hint.id !== draft.areaId && !draft.addingArea ? (
              <>
                {" "}
                <button
                  type="button"
                  disabled={disabled}
                  className="text-primary hover:underline disabled:opacity-50"
                  onClick={() => onChange({ ...draft, areaId: hint.id })}
                >
                  Przypisz: {hint.name}
                </button>
              </>
            ) : null}
          </p>
        ) : null}
      </div>
      <div>
        <label id={ids.reports} className={label}>
          Podlega pod
        </label>
        <Select
          value={draft.reportsToId != null ? String(draft.reportsToId) : NONE}
          disabled={disabled}
          onValueChange={(next) =>
            onChange({ ...draft, reportsToId: next === NONE ? null : Number(next) })
          }
        >
          <SelectTrigger aria-labelledby={ids.reports} className="h-8">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>Nikt (najwyżej w strukturze)</SelectItem>
            {current ? <SelectItem value={String(current.id)}>{current.name}</SelectItem> : null}
            {options.map((option) => (
              <SelectItem key={option.id} value={String(option.id)}>
                {option.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
