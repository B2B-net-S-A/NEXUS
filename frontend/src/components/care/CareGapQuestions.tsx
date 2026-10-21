"use client";

import { useCallback } from "react";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { searchSkills, type ClientQuestion } from "@/lib/api/care";
import { useClientOrg } from "@/lib/api/client-people";

import {
  emptyGapAnswer,
  questionText,
  type GapAnswerForm,
} from "./conversation/conversation-form";
import { TokenPicker } from "./TokenPicker";

const NONE = "none";

interface CareGapQuestionsProps {
  clientId: number | null;
  questions: ClientQuestion[];
  answers: Record<string, GapAnswerForm>;
  onChange: (key: string, answer: GapAnswerForm) => void;
}

/**
 * „Pytania z mapy klienta” w oknie rozmowy (22.10.2026): luki mapy klienta
 * dotyczące działu konsultanta albo jego menedżera (najwyżej 4, liczy
 * serwer) z polem odpowiedzi. Odpowiedź zapisuje się razem z rozmową —
 * „komu podlega” w strukturze klienta, technologie i notatka w mapie.
 * Pytanie bez odpowiedzi niczego nie zmienia.
 */
export function CareGapQuestions({ clientId, questions, answers, onChange }: CareGapQuestionsProps) {
  const needsPeople = questions.some((question) => question.kind === "reports_to");
  const org = useClientOrg(clientId ?? 0, needsPeople && clientId != null);
  const skillSearch = useCallback((q: string) => searchSkills(q), []);
  if (!questions.length) return null;
  const people = (org.data?.departments ?? []).flatMap((department) => department.people);

  return (
    <section aria-label="Pytania z mapy klienta" className="space-y-2">
      <h3 className="text-sm font-semibold text-foreground">Pytania z mapy klienta</h3>
      <ul className="space-y-2.5">
        {questions.map((question) => {
          const answer = answers[question.key] ?? emptyGapAnswer();
          const set = (patch: Partial<GapAnswerForm>) => onChange(question.key, { ...answer, ...patch });
          const text = questionText(question);
          return (
            <li key={question.key} className="space-y-1.5 rounded-md border border-border/60 px-3 py-2">
              <p className="text-sm text-foreground">
                {text}
                {question.detail ? (
                  <span className="block text-xs text-muted-foreground">{question.detail}</span>
                ) : null}
              </p>
              {question.kind === "reports_to" ? (
                org.isError ? (
                  <p className="text-xs text-muted-foreground">
                    Listy osób klienta nie udało się wczytać — odpowiedz notatką.
                  </p>
                ) : (
                  <Select
                    value={answer.reportsToContactId == null ? NONE : String(answer.reportsToContactId)}
                    onValueChange={(next) => set({ reportsToContactId: next === NONE ? null : Number(next) })}
                  >
                    <SelectTrigger aria-label={`Odpowiedź: ${text}`}>
                      <SelectValue placeholder={org.isLoading ? "Wczytywanie osób…" : "Wybierz osobę…"} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>Nie wiem</SelectItem>
                      {people
                        .filter((person) => person.id !== question.contact_id)
                        .map((person) => (
                          <SelectItem key={person.id} value={String(person.id)}>
                            {person.name}
                            {person.position ? ` · ${person.position}` : ""}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                )
              ) : null}
              {question.kind === "area_without_source" ? (
                <TokenPicker
                  label={`Technologie: ${question.subject}`}
                  value={answer.skills}
                  onChange={(next) => set({ skills: next })}
                  search={skillSearch}
                  placeholder="Szukaj w słowniku…"
                  freeTextHint="do przejrzenia"
                />
              ) : null}
              <Input
                aria-label={`Notatka: ${text}`}
                value={answer.note}
                maxLength={500}
                placeholder={question.kind === "single_source" ? "np. tak, używają od 2025" : "Notatka (opcjonalnie)"}
                onChange={(event) => set({ note: event.target.value })}
              />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
