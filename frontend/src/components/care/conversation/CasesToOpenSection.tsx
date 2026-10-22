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

/**
 * „Coś do załatwienia?” — do pięciu spraw z tym kontraktem, zakładanych razem
 * z rozmową (jeden rejestr Spraw w „Ludziach”). Opis sprawy to link do
 * rozmowy — bez stawek i bez treści rozmowy.
 */
export function CasesToOpenSection({ drafts, onChange, canPickAssignee, handler }: CasesToOpenSectionProps) {
  const areas = caseAreasFor(handler);
  const assignees = useCaseAssignees(canPickAssignee && drafts.length > 0, "care");
  const update = (index: number, patch: Partial<CaseDraft>) =>
    onChange(drafts.map((draft, i) => (i === index ? { ...draft, ...patch } : draft)));
  const remove = (index: number) => onChange(drafts.filter((_, i) => i !== index));
  const showAssignee = canPickAssignee && !assignees.isError;

  return (
    <section aria-label="Coś do załatwienia?" className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Coś do załatwienia?</h3>
        <span className="text-xs text-muted-foreground">
          {drafts.length ? `${drafts.length} z ${MAX_CONVERSATION_CASES}` : "sprawy z tym kontraktem"}
        </span>
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
              <div className={showAssignee ? "grid grid-cols-3 gap-1.5" : "grid grid-cols-2 gap-1.5"}>
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
                      <SelectItem value={NOBODY}>Bez osoby — przydzieli obsługa</SelectItem>
                      {(assignees.data ?? []).map((person) => (
                        <SelectItem key={person.id} value={String(person.id)}>
                          {person.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : null}
                <Input
                  aria-label={`Sprawa ${index + 1}: termin`}
                  type="date"
                  className="h-8"
                  value={draft.dueOn}
                  onChange={(event) => update(index, { dueOn: event.target.value })}
                />
              </div>
            </li>
            );
          })}
        </ul>
      ) : null}
      {drafts.length < MAX_CONVERSATION_CASES ? (
        <Button size="sm" variant="ghost" onClick={() => onChange([...drafts, emptyCase()])}>
          <Plus aria-hidden className="size-3.5" /> Dodaj sprawę
        </Button>
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
