"use client";

/**
 * Okno „Czy sama się do nas zgłosiła?” (off-limits, decyzja Artura 21.10.2026).
 *
 * Z firm, w których mamy aktywne zamówienie, nie wyciągamy ludzi. Gdy człowiek
 * dodaje do rekrutacji osobę, która dziś tam pracuje, backend odpowiada 409,
 * a interceptor `lib/api.ts` woła to okno przez `askOffLimits` i ponawia
 * żądanie z odpowiedziami. Okno jest jedno na aplikację (montuje je
 * `AppShell`), więc każda droga dodania pyta tak samo.
 */

import { useCallback, useEffect, useState } from "react";
import { Ban } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  OFF_LIMITS_HOW_OPTIONS,
  OFF_LIMITS_SKIP,
  registerOffLimitsHost,
  type OffLimitsAnswers,
  type OffLimitsHow,
  type OffLimitsPerson,
} from "@/lib/off-limits";
import { cn } from "@/lib/utils";

const FIELD_CLASS =
  "w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm text-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

type Choice = "self" | "left" | "us";

interface PendingAsk {
  people: OffLimitsPerson[];
  resolve: (answers: OffLimitsAnswers | null) => void;
}

interface PersonState {
  choice: Choice | null;
  how: Exclude<OffLimitsHow, "left_company">;
}

const SELF_OPTIONS = OFF_LIMITS_HOW_OPTIONS.filter((o) => o.value !== "left_company");

/** Odpowiedzi do nagłówka — `null`, dopóki ktoś nie ma odpowiedzi. */
export function answersFromState(
  people: OffLimitsPerson[],
  state: Record<number, PersonState>,
): OffLimitsAnswers | null {
  const answers: OffLimitsAnswers = {};
  for (const person of people) {
    const entry = state[person.candidate_id];
    if (!entry?.choice) return null;
    answers[person.candidate_id] =
      entry.choice === "us" ? OFF_LIMITS_SKIP : entry.choice === "left" ? "left_company" : entry.how;
  }
  return answers;
}

function sourceLabel(person: OffLimitsPerson): string {
  return person.source === "cv"
    ? `CV, „${person.company}” bez daty końca`
    : `LinkedIn, „${person.company}”`;
}

export function OffLimitsConfirmHost() {
  const [queue, setQueue] = useState<PendingAsk[]>([]);
  const [state, setState] = useState<Record<number, PersonState>>({});

  useEffect(
    () =>
      registerOffLimitsHost(
        (people) =>
          new Promise<OffLimitsAnswers | null>((resolve) => {
            setQueue((q) => [...q, { people, resolve }]);
          }),
      ),
    [],
  );

  const current = queue[0] ?? null;

  const finish = useCallback(
    (answers: OffLimitsAnswers | null) => {
      if (!current) return;
      current.resolve(answers);
      setState({});
      setQueue((q) => q.slice(1));
    },
    [current],
  );

  if (!current) return null;
  const { people } = current;
  const single = people.length === 1 ? people[0] : null;
  const answers = answersFromState(people, state);
  const nobodyAdded =
    answers !== null && Object.values(answers).every((a) => a === OFF_LIMITS_SKIP);

  const setPerson = (id: number, patch: Partial<PersonState>) =>
    setState((s) => {
      const prev: PersonState = s[id] ?? { choice: null, how: "linkedin_inbound" };
      return { ...s, [id]: { ...prev, ...patch } };
    });

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : finish(null))}>
      <DialogContent size="md" aria-describedby="off-limits-description">
        <DialogHeader>
          <DialogTitle>
            {single
              ? `Dodać do rekrutacji: ${single.name}?`
              : `${people.length} osoby z firm, z których nie wyciągamy ludzi`}
          </DialogTitle>
          <DialogDescription id="off-limits-description">
            {single
              ? "W tej firmie mamy aktywne zamówienie. Osobę stamtąd prowadzimy tylko wtedy, gdy sam(a) się do nas zgłosił(a)."
              : "W tych firmach mamy aktywne zamówienia. Osoby stamtąd prowadzimy tylko wtedy, gdy same się do nas zgłosiły."}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="max-h-[60dvh] space-y-4 overflow-y-auto">
          {people.map((person) => {
            const entry = state[person.candidate_id];
            const name = `off-limits-${person.candidate_id}`;
            return (
              <fieldset key={person.candidate_id} className="space-y-2">
                <legend className="sr-only">{person.name}</legend>
                <div className="flex gap-2.5 rounded-lg border border-warning/40 bg-warning-muted px-3 py-2.5 text-sm text-warning-muted-foreground">
                  <Ban className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  <div>
                    <p>
                      <strong>
                        {single ? "Pracuje" : `${person.name} pracuje`} w firmie{" "}
                        {person.client_name}
                      </strong>{" "}
                      — stamtąd nie wyciągamy ludzi.
                    </p>
                    <p className="text-xs">Skąd wiemy: {sourceLabel(person)}.</p>
                  </div>
                </div>

                <div
                  className={cn(
                    "rounded-lg border px-3 py-2",
                    entry?.choice === "self" ? "border-primary bg-primary/5" : "border-border",
                  )}
                >
                  <label className="flex cursor-pointer items-center gap-2 text-sm font-semibold text-foreground">
                    <input
                      type="radio"
                      name={name}
                      checked={entry?.choice === "self"}
                      onChange={() => setPerson(person.candidate_id, { choice: "self" })}
                      className="accent-[hsl(var(--primary))]"
                    />
                    Tak, sam(a) się do nas zgłosił(a)
                  </label>
                  {entry?.choice === "self" ? (
                    <div className="mt-1.5 pl-6">
                      <select
                        aria-label={`Jak zgłosił(a) się ${person.name}`}
                        value={entry.how}
                        onChange={(e) =>
                          setPerson(person.candidate_id, {
                            how: e.target.value as PersonState["how"],
                          })
                        }
                        className={FIELD_CLASS}
                      >
                        {SELF_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  ) : null}
                </div>

                <label
                  className={cn(
                    "flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold text-foreground",
                    entry?.choice === "left" ? "border-primary bg-primary/5" : "border-border",
                  )}
                >
                  <input
                    type="radio"
                    name={name}
                    checked={entry?.choice === "left"}
                    onChange={() => setPerson(person.candidate_id, { choice: "left" })}
                    className="accent-[hsl(var(--primary))]"
                  />
                  Już tam nie pracuje
                </label>

                <label
                  className={cn(
                    "flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm text-foreground",
                    entry?.choice === "us" ? "border-primary bg-primary/5" : "border-border",
                  )}
                >
                  <input
                    type="radio"
                    name={name}
                    checked={entry?.choice === "us"}
                    onChange={() => setPerson(person.candidate_id, { choice: "us" })}
                    className="mt-0.5 accent-[hsl(var(--primary))]"
                  />
                  <span>
                    <span className="font-semibold">Nie, to my się odezwaliśmy</span>
                    <span className="block text-xs text-muted-foreground">
                      Nie dodajemy. Osoba zostaje w bazie bez zmian.
                    </span>
                  </span>
                </label>
              </fieldset>
            );
          })}
          <p className="text-xs text-muted-foreground">
            Odpowiedź zostaje przy osobie w rekrutacji, z Twoim imieniem i datą.
          </p>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => finish(null)}>
            Anuluj
          </Button>
          <Button disabled={answers === null} onClick={() => finish(answers)}>
            {nobodyAdded ? "Nie dodawaj" : "Dodaj"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
