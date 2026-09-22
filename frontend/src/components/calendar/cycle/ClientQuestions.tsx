"use client";

import { useClientQuestions } from "@/lib/api/interviewCycle";

/**
 * Pytania, które klient zadawał poprzednim kandydatom (z debriefów).
 * Po to rekruter zapisuje pytania po rozmowie: następna osoba idzie na prep
 * z listą tego, o co ten klient naprawdę pyta.
 */
export function ClientQuestions({
  jobId,
  clientName,
}: {
  jobId: number;
  clientName: string | null;
}) {
  const query = useClientQuestions(jobId);
  // „Nordea pytał” — nazwa klienta nie ma rodzaju, więc zdanie bez czasownika.
  const heading = clientName
    ? `Pytania klienta ${clientName} z poprzednich rozmów`
    : "Pytania klienta z poprzednich rozmów";
  if (query.isPending) {
    return <p className="text-xs text-muted-foreground">Wczytuję pytania klienta…</p>;
  }
  if (query.isError) {
    return (
      <p role="alert" className="text-xs text-destructive">
        Nie udało się wczytać pytań klienta — lista może istnieć, spróbuj odświeżyć.
      </p>
    );
  }
  const questions = query.data ?? [];
  return (
    <div className="rounded-lg bg-muted/50 p-3" data-testid="cycle-client-questions">
      <div className="mb-1.5 text-xs font-semibold text-foreground">
        {heading}
      </div>
      {questions.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Jeszcze nic — pytania pojawią się po pierwszym debriefie z tym klientem.
        </p>
      ) : (
        <ul className="space-y-1">
          {questions.slice(0, 6).map((q) => (
            <li key={q.id} className="text-xs text-foreground">
              • {q.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
