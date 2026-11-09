"use client";

import { useState } from "react";

import { TabbedNav } from "@/components/ds/TabbedNav";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { ACTIVITY_KIND_LABELS, useCreateActivity, type ActivityKind } from "@/lib/api/sales";

const COMPOSER_KINDS: ActivityKind[] = ["note", "call", "meeting", "email", "task"];

/** Datetime z pola `datetime-local` (czas lokalny) jako ISO; puste → null. */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function inDays(days: number, now = new Date()): string {
  const date = new Date(now);
  date.setDate(date.getDate() + days);
  date.setHours(9, 0, 0, 0);
  return date.toISOString();
}

export function followUpSteps(now = new Date()): { subject: string; due_at: string }[] {
  return [
    { subject: "Wyślij podsumowanie mailowe ze spotkania", due_at: inDays(0, now) },
    { subject: "Przygotuj ofertę", due_at: inDays(6, now) },
    { subject: "Umów drugie spotkanie", due_at: inDays(14, now) },
  ];
}

interface ActivityComposerProps {
  companyId?: number;
  opportunityId?: number;
}

/** Szybki wpis do historii: notatka, telefon, spotkanie, mail, zadanie. */
export function ActivityComposer({ companyId, opportunityId }: ActivityComposerProps) {
  const create = useCreateActivity();
  const { showError, showSuccess } = useToast();
  const [kind, setKind] = useState<ActivityKind>("note");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [due, setDue] = useState("");
  // Po spotkaniu przy szansie: trzy następne kroki jak w Atlasie
  // (`meeting_followup_seeder.py`): podsumowanie mailem dziś, oferta za 7 dni,
  // drugie spotkanie za 14 dni.
  const [withFollowUps, setWithFollowUps] = useState(true);

  const submit = () => {
    if (kind === "task" ? !subject.trim() : !(subject.trim() || body.trim())) {
      showError(kind === "task" ? "Wpisz, co jest do zrobienia." : "Wpisz temat albo treść.");
      return;
    }
    create.mutate(
      {
        kind,
        company_id: opportunityId ? null : (companyId ?? null),
        opportunity_id: opportunityId ?? null,
        subject: subject.trim() || null,
        body: body.trim() || null,
        due_at: kind === "task" || kind === "call" ? localInputToIso(due) : null,
      },
      {
        onSuccess: () => {
          setSubject("");
          setBody("");
          setDue("");
          if (kind === "meeting" && opportunityId && withFollowUps) {
            for (const step of followUpSteps()) {
              create.mutate({ kind: "task", opportunity_id: opportunityId, company_id: null, ...step, body: null });
            }
            showSuccess("Zapisano spotkanie i trzy następne kroki w zadaniach.");
            return;
          }
          showSuccess(kind === "task" ? "Dodano zadanie." : "Zapisano wpis.");
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać wpisu.")),
      },
    );
  };

  return (
    <div className="space-y-2 rounded-md border border-border p-3">
      <TabbedNav
        dense
        ariaLabel="Rodzaj wpisu"
        tabs={COMPOSER_KINDS.map((value) => ({ value, label: ACTIVITY_KIND_LABELS[value] }))}
        value={kind}
        onValueChange={(value) => setKind(value as ActivityKind)}
      />
      <Input
        aria-label={kind === "task" ? "Co jest do zrobienia" : "Temat"}
        placeholder={kind === "task" ? "Co jest do zrobienia?" : "Temat"}
        value={subject}
        onChange={(event) => setSubject(event.target.value)}
      />
      {(kind === "task" || kind === "call") && (
        <Input
          aria-label={kind === "call" ? "Termin telefonu (puste = już był)" : "Termin"}
          type="datetime-local"
          value={due}
          onChange={(event) => setDue(event.target.value)}
        />
      )}
      {kind !== "task" && (
        <Textarea
          aria-label="Treść"
          rows={3}
          placeholder="Co ustaliliście?"
          value={body}
          onChange={(event) => setBody(event.target.value)}
        />
      )}
      <div className="flex flex-wrap items-center justify-end gap-3">
        {kind === "meeting" && opportunityId && (
          <label className="mr-auto flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={withFollowUps}
              onChange={(event) => setWithFollowUps(event.target.checked)}
            />
            Dodaj następne kroki: podsumowanie mailem, oferta (7 dni), drugie spotkanie (14 dni)
          </label>
        )}
        <Button size="sm" onClick={submit} loading={create.isPending}>
          Zapisz
        </Button>
      </div>
    </div>
  );
}
