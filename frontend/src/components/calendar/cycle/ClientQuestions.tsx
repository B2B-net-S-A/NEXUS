"use client";

import { useState } from "react";

import { AllClientQuestions } from "@/components/AllClientQuestions";
import { useClientQuestions } from "@/lib/api/interviewCycle";

/**
 * Pytania zadane poprzednim kandydatom na rozmowach w TEJ rekrutacji.
 * Po to rekruter zapisuje pytania po rozmowie: następna osoba idzie na prep
 * z listą tego, o co klient naprawdę pyta na tę rolę (zgłoszenie 02.11.2026:
 * lista całego klienta mieszała pytania z innych ról). Pełna lista klienta
 * jest pod przyciskiem i pobiera się dopiero po rozwinięciu.
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
  const [showAll, setShowAll] = useState(false);
  // „Nordea pytał” — nazwa klienta nie ma rodzaju, więc zdanie bez czasownika.
  const heading = clientName
    ? `Pytania klienta ${clientName} z rozmów w tej rekrutacji`
    : "Pytania klienta z rozmów w tej rekrutacji";
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
          Jeszcze nic — pytania pojawią się po pierwszym debriefie w tej rekrutacji.
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
      <button
        type="button"
        data-tour="jobs.client-questions.scope"
        aria-expanded={showAll}
        onClick={() => setShowAll((v) => !v)}
        className={`mt-2 font-medium text-primary hover:underline ${text}`}
      >
        {showAll ? "▾" : "▸"} Wszystkie pytania klienta
      </button>
      {showAll ? (
        <div className="mt-2">
          <AllClientQuestions
            jobId={jobId}
            renderQuestion={(q) => (
              <li key={q.id} className={`text-foreground ${text}`}>
                • {q.text}
              </li>
            )}
          />
        </div>
      ) : null}
    </div>
  );
}
