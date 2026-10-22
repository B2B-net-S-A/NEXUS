"use client";

import { useCallback, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { searchSkills, type ClientQuestion } from "@/lib/api/care";
import { clientPeopleKeys, useClientOrg, type OrgPerson } from "@/lib/api/client-people";

import {
  emptyGapAnswer,
  questionText,
  type GapAnswerForm,
} from "./conversation/conversation-form";
import { TokenPicker } from "./TokenPicker";

const NONE = "none";
const NEW = "new";

/** Nowa osoba klienta (`POST /api/contacts`, prawo edycji kontaktów klienta). */
function useCreateClientPerson(clientId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (person: { name: string; position: string | null }) =>
      (await api.post<{ id: number; name: string }>("/api/contacts", { client_id: clientId, ...person })).data,
    onSuccess: () => {
      if (clientId != null) void queryClient.invalidateQueries({ queryKey: clientPeopleKeys.org(clientId) });
    },
  });
}

/**
 * „Komu podlega X?” — osoba klienta z listy albo nowa (imię i stanowisko);
 * nowa zakłada się od razu jako kontakt klienta i zostaje wybrana.
 */
function ReportsToPicker({
  clientId,
  label,
  people,
  value,
  onPick,
}: {
  clientId: number | null;
  label: string;
  people: OrgPerson[];
  value: number | null;
  onPick: (contactId: number | null) => void;
}) {
  const create = useCreateClientPerson(clientId);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [position, setPosition] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ id: number; name: string } | null>(null);
  const listed = created && !people.some((person) => person.id === created.id) ? [created] : [];

  const add = () => {
    setError(null);
    create.mutate(
      { name: name.trim(), position: position.trim() || null },
      {
        onSuccess: (person) => {
          setCreated({ id: person.id, name: person.name });
          onPick(person.id);
          setAdding(false);
          setName("");
          setPosition("");
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się dodać osoby klienta.")),
      },
    );
  };

  return (
    <div className="space-y-1.5">
      <Select
        value={adding ? NEW : value == null ? NONE : String(value)}
        onValueChange={(next) => {
          if (next === NEW) {
            setAdding(true);
            return;
          }
          setAdding(false);
          onPick(next === NONE ? null : Number(next));
        }}
      >
        <SelectTrigger aria-label={`Odpowiedź: ${label}`}>
          <SelectValue placeholder="Wybierz osobę klienta albo wpisz nową…" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>Wybierz osobę klienta albo wpisz nową…</SelectItem>
          {[...listed, ...people].map((person) => (
            <SelectItem key={person.id} value={String(person.id)}>
              {person.name}
              {"position" in person && person.position ? ` · ${person.position}` : ""}
            </SelectItem>
          ))}
          <SelectItem value={NEW}>Nowa osoba klienta…</SelectItem>
        </SelectContent>
      </Select>
      {adding ? (
        <div className="grid gap-1.5 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <Input
            aria-label="Nowa osoba: imię i nazwisko"
            value={name}
            maxLength={255}
            placeholder="Imię i nazwisko"
            onChange={(event) => setName(event.target.value)}
          />
          <Input
            aria-label="Nowa osoba: stanowisko"
            value={position}
            maxLength={255}
            placeholder="Stanowisko"
            onChange={(event) => setPosition(event.target.value)}
          />
          <Button size="sm" onClick={add} loading={create.isPending} disabled={name.trim().length < 2}>
            Dodaj osobę
          </Button>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

interface CareGapQuestionsProps {
  clientId: number | null;
  questions: ClientQuestion[];
  answers: Record<string, GapAnswerForm>;
  onChange: (key: string, answer: GapAnswerForm) => void;
}

/**
 * „Pytania z mapy klienta · N” w oknie rozmowy (makieta P3): luki mapy
 * klienta dotyczące działu konsultanta albo jego menedżera (najwyżej 4,
 * liczy serwer) z polem odpowiedzi — odpowiedź zasila mapę. „Komu podlega”
 * zapisuje się w strukturze klienta (osoba z listy albo nowa), technologie
 * działu i grupy kategorii („CI/CD i chmura”) — w mapie. Pytanie bez
 * odpowiedzi niczego nie zmienia. Wybór osoby widzi tylko ktoś z prawem
 * edycji struktury klienta (`can_edit_org`) — reszta odpowiada notatką
 * (serwer odmówiłby 403).
 */
export function CareGapQuestions({ clientId, questions, answers, onChange }: CareGapQuestionsProps) {
  const needsPeople = questions.some((question) => question.kind === "reports_to");
  const org = useClientOrg(clientId ?? 0, needsPeople && clientId != null);
  const skillSearch = useCallback((q: string) => searchSkills(q), []);
  if (!questions.length) return null;
  const people = (org.data?.departments ?? []).flatMap((department) => department.people);
  const canPickPerson = org.isSuccess && org.data.can_edit_org;

  return (
    <section aria-label="Pytania z mapy klienta" className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Pytania z mapy klienta · {questions.length}</h3>
        <span className="text-xs text-muted-foreground">odpowiedź zasila mapę</span>
      </div>
      <ul className="space-y-2.5">
        {questions.map((question) => {
          const answer = answers[question.key] ?? emptyGapAnswer();
          const set = (patch: Partial<GapAnswerForm>) => onChange(question.key, { ...answer, ...patch });
          const text = questionText(question);
          const category = question.kind === "category_stale";
          return (
            <li key={question.key} className="space-y-1.5 rounded-md border border-border/60 px-3 py-2">
              {category ? (
                <p className="text-sm text-foreground">
                  <span className="font-medium">{question.subject}</span>
                  {question.detail ? <span className="text-muted-foreground"> — {question.detail}</span> : null}
                </p>
              ) : question.kind === "reports_to" ? (
                // Serwer daje pytanie ze stanowiskiem („Komu podlega X (Head of Data)?”).
                <p className="text-sm text-foreground">{question.detail ? question.detail : text}</p>
              ) : (
                <p className="text-sm text-foreground">
                  {text}
                  {question.detail ? (
                    <span className="block text-xs text-muted-foreground">{question.detail}</span>
                  ) : null}
                </p>
              )}
              {question.kind === "reports_to" ? (
                org.isError ? (
                  <p className="text-xs text-muted-foreground">
                    Listy osób klienta nie udało się wczytać — odpowiedz notatką.
                  </p>
                ) : org.isLoading ? (
                  <p className="text-xs text-muted-foreground">Wczytywanie osób…</p>
                ) : !canPickPerson ? (
                  <p className="text-xs text-muted-foreground">
                    Osobę w strukturze klienta wskazuje Delivery Lead klienta — odpowiedz notatką.
                  </p>
                ) : (
                  <ReportsToPicker
                    clientId={clientId}
                    label={text}
                    people={people.filter((person) => person.id !== question.contact_id)}
                    value={answer.reportsToContactId}
                    onPick={(reportsToContactId) => set({ reportsToContactId })}
                  />
                )
              ) : null}
              {question.kind === "area_without_source" || category ? (
                <TokenPicker
                  label={`Technologie: ${question.subject}`}
                  value={answer.skills}
                  onChange={(next) => set({ skills: next })}
                  search={skillSearch}
                  placeholder={category ? "Technologie ze słownika…" : "Szukaj w słowniku…"}
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
