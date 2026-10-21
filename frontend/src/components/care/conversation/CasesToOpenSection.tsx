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
import { CASE_AREAS, CASE_AREA_LABELS, useCaseAssignees, type CaseArea } from "@/lib/api/admin-cases";

import { MAX_CONVERSATION_CASES, emptyCase, type CaseDraft } from "./conversation-form";

const NOBODY = "none";

interface CasesToOpenSectionProps {
  drafts: CaseDraft[];
  onChange: (next: CaseDraft[]) => void;
  /** Lista osób spraw z `GET /api/care/case-assignees` (zapisujący opiekę); bez prawa zapisu — „przydzieli obsługa”. */
  canPickAssignee: boolean;
}

/**
 * „Coś do załatwienia?” — do pięciu spraw z tym kontraktem, zakładanych razem
 * z rozmową (jeden rejestr Spraw w „Ludziach”). Opis sprawy to link do
 * rozmowy — bez stawek i bez treści rozmowy.
 */
export function CasesToOpenSection({ drafts, onChange, canPickAssignee }: CasesToOpenSectionProps) {
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
          {drafts.map((draft, index) => (
            <li key={index} className="grid gap-1.5 rounded-md border border-border/60 p-2">
              <div className="flex items-center gap-1.5">
                <Input
                  aria-label={`Sprawa ${index + 1}: tytuł`}
                  value={draft.title}
                  maxLength={300}
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
              <div className={showAssignee ? "grid grid-cols-3 gap-1.5" : "grid grid-cols-2 gap-1.5"}>
                <Select value={draft.area} onValueChange={(next) => update(index, { area: next as CaseArea })}>
                  <SelectTrigger aria-label={`Sprawa ${index + 1}: obszar`} className="h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CASE_AREAS.map((key) => (
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
                      <SelectItem value={NOBODY}>Prowadzi: obsługa</SelectItem>
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
          ))}
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
    </section>
  );
}
