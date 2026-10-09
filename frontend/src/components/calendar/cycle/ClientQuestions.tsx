"use client";

import { useClientQuestions } from "@/lib/api/interviewCycle";

/**
 * Pytania, które klient zadawał poprzednim kandydatom (z debriefów).
 * Po to rekruter zapisuje pytania po rozmowie: następna osoba idzie na prep
 * z listą tego, o co ten klient naprawdę pyta.
 *
 * `roomy` — duża strefa podglądu w panelu osoby (09.10.2026): większy tekst
 * i cała pobrana lista zamiast sześciu pozycji.
 */
export function ClientQuestions({
  jobId,
  clientName,
  roomy = false,
}: {
  jobId: number;
  clientName: string | null;
  roomy?: boolean;
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
  const text = roomy ? "text-sm" : "text-xs";
  return (
    <div className={roomy ? "rounded-lg bg-muted/50 p-4" : "rounded-lg bg-muted/50 p-3"} data-testid="cycle-client-questions">
      <div className={`mb-1.5 font-semibold text-foreground ${text}`}>
        {heading}
      </div>
      {questions.length === 0 ? (
        <p className={`text-muted-foreground ${text}`}>
          Jeszcze nic — pytania pojawią się po pierwszym debriefie z tym klientem.
        </p>
      ) : (
        <ul className={roomy ? "space-y-1.5" : "space-y-1"}>
          {(roomy ? questions : questions.slice(0, 6)).map((q) => (
            <li key={q.id} className={`text-foreground ${text}`}>
              • {q.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
