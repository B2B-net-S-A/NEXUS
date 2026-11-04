"use client";

import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CASE_AREA_LABELS, useCaseAssignees, type CaseArea } from "@/lib/api/admin-cases";

import {
  CASE_TITLE_MAX,
  MAX_CONVERSATION_CASES,
  caseAreasFor,
  caseTitleProblem,
  emptyCase,
  type CaseDraft,
} from "./conversation-form";

const NOBODY = "none";

interface CasesToOpenSectionProps {
  drafts: CaseDraft[];
  onChange: (next: CaseDraft[]) => void;
  /** Lista osób spraw z `GET /api/care/case-assignees` (zapisujący opiekę); bez prawa zapisu — „przydzieli obsługa”. */
  canPickAssignee: boolean;
  /**
   * Obsługa Spraw (uprawnienie „Sprawy” albo admin): pełna lista osób i obszar „Negocjacje”.
   * Reszta zostawia sprawę bez osoby albo bierze ją na siebie (trasa zwraca wtedy tylko ją).
   */
  handler: boolean;
}

/** Imię prowadzącego do podpowiedzi („Zofia dostanie dzwonek…”). */
function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}

/**
 * Podpowiedź pod sprawami (makieta S5): co dostanie sprawa i kto dostanie
 * dzwonek. `names` — prowadzący wybrani w wierszach (bez powtórzeń).
 */
export function casesHint(names: string[]): string {
  const base = "Sprawa dostanie kontrakt, opis z notatki i link do tej rozmowy.";
  const people = [...new Set(names.map(firstName))];
  if (!people.length) return `${base} Bez osoby trafi do „Bez osoby” u obsługi Spraw.`;
  const who = people.length === 1 ? people[0] : `${people.slice(0, -1).join(", ")} i ${people[people.length - 1]}`;
  return `${base} ${who} ${people.length === 1 ? "dostanie" : "dostaną"} dzwonek jak przy każdym przypisaniu.`;
}

/**
 * „Coś do załatwienia?” — do pięciu spraw z tym kontraktem, zakładanych razem
 * z rozmową (jeden rejestr Spraw w „Ludziach”). Opis sprawy to link do
 * rozmowy i notatka z rozmowy (opieka nie zbiera stawek ani danych o zdrowiu).
 */
export function CasesToOpenSection({ drafts, onChange, canPickAssignee, handler }: CasesToOpenSectionProps) {
  const areas = caseAreasFor(handler);
  const assignees = useCaseAssignees(canPickAssignee && drafts.length > 0, "care");
  const update = (index: number, patch: Partial<CaseDraft>) =>
    onChange(drafts.map((draft, i) => (i === index ? { ...draft, ...patch } : draft)));
  const remove = (index: number) => onChange(drafts.filter((_, i) => i !== index));
  const showAssignee = canPickAssignee && !assignees.isError;
  const byId = new Map((assignees.data ?? []).map((person) => [person.id, person.name]));
  const chosen = drafts
    .filter((draft) => draft.title.trim() && draft.assigneeUserId != null)
    .map((draft) => byId.get(draft.assigneeUserId as number))
    .filter((name): name is string => Boolean(name));
  const add = () => onChange([...drafts, emptyCase()]);

  return (
    <section aria-label="Coś do załatwienia?" className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Coś do załatwienia?</h3>
        {drafts.length && drafts.length < MAX_CONVERSATION_CASES ? (
          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={add}>
            <Plus aria-hidden className="size-3.5" /> dodaj kolejną
          </Button>
        ) : (
          <span className="text-xs text-muted-foreground">
            {drafts.length ? `${drafts.length} z ${MAX_CONVERSATION_CASES}` : "sprawy z tym kontraktem"}
          </span>
        )}
      </div>
      {drafts.length ? (
        <ul className="space-y-2">
          {drafts.map((draft, index) => {
            const titleProblem = caseTitleProblem(draft);
            const titleErrorId = `conversation-case-${index}-title-error`;
            return (
            <li key={index} className="grid gap-1.5 rounded-md border border-border/60 p-2">
              <div className="flex items-center gap-1.5">
                <Input
                  aria-label={`Sprawa ${index + 1}: tytuł`}
                  value={draft.title}
                  maxLength={CASE_TITLE_MAX}
                  aria-invalid={titleProblem ? true : undefined}
                  aria-describedby={titleProblem ? titleErrorId : undefined}
                  placeholder="np. Nowy laptop, aneks, dostęp do VPN"
                  onChange={(event) => update(index, { title: event.target.value })}
                />
                <Button
                  size="sm"
                  variant="quiet"
                  className="h-8 w-8 shrink-0 p-0"
                  aria-label={`Usuń sprawę ${index + 1}`}
                  onClick={() => remove(index)}
                >
                  <X aria-hidden className="size-4" />
                </Button>
              </div>
              {titleProblem ? (
                <p id={titleErrorId} role="alert" className="text-xs text-destructive">
                  {titleProblem}
                </p>
              ) : null}
              <div className="grid grid-cols-[minmax(0,1fr)_10rem] gap-1.5">
                <Select value={draft.area} onValueChange={(next) => update(index, { area: next as CaseArea })}>
                  <SelectTrigger aria-label={`Sprawa ${index + 1}: obszar`} className="h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {areas.map((key) => (
                      <SelectItem key={key} value={key}>
                        {CASE_AREA_LABELS[key]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  aria-label={`Sprawa ${index + 1}: termin`}
                  type="date"
                  className="h-8"
                  value={draft.dueOn}
                  onChange={(event) => update(index, { dueOn: event.target.value })}
                />
              </div>
              {showAssignee ? (
                <Select
                  value={draft.assigneeUserId == null ? NOBODY : String(draft.assigneeUserId)}
                  onValueChange={(next) =>
                    update(index, { assigneeUserId: next === NOBODY ? null : Number(next) })
                  }
                >
                  <SelectTrigger aria-label={`Sprawa ${index + 1}: prowadzi`} className="h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NOBODY}>Prowadzi: bez osoby — przydzieli obsługa</SelectItem>
                    {(assignees.data ?? []).map((person) => (
                      <SelectItem key={person.id} value={String(person.id)}>
                        Prowadzi: {person.name}
                        {person.handler ? " (obsługa skrzynki)" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : null}
            </li>
            );
          })}
        </ul>
      ) : null}
      {!drafts.length ? (
        <Button size="sm" variant="ghost" onClick={add}>
          <Plus aria-hidden className="size-3.5" /> Dodaj sprawę
        </Button>
      ) : null}
      {drafts.length ? (
        <p className="text-xs text-muted-foreground">{casesHint(showAssignee ? chosen : [])}</p>
      ) : null}
      {drafts.length && !showAssignee ? (
        <p className="text-xs text-muted-foreground">Osobę przydzieli obsługa Spraw.</p>
      ) : null}
      {drafts.length && showAssignee && !handler ? (
        <p className="text-xs text-muted-foreground">
          Sprawę zostaw bez osoby (przydzieli obsługa Spraw) albo weź na siebie.
        </p>
      ) : null}
    </section>
  );
}
