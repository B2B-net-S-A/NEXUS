"use client";

import { useClientQuestionPool } from "@/lib/api/interviewCycle";

/**
 * „Klient pytał wcześniej (N)” na stronie nowej rekrutacji — pytania, które
 * wybrany klient zadawał kandydatom na rozmowach (debriefy po telefonie do
 * kandydata). Podpowiedź przy pisaniu pytań screeningowych i opisu; rekrutacja
 * jeszcze nie istnieje, więc pula idzie po kliencie (`client_id`).
 *
 * Brak pytań = nic nie renderujemy (to podpowiedź, nie sekcja formularza);
 * awaria odczytu jest za to widoczna — nie może udawać „klient o nic nie pytał”.
 */
export function ClientAskedBeforeHint({ clientId }: { clientId: number | null }) {
  const query = useClientQuestionPool("client", clientId, 20);
  if (clientId == null || query.isPending) return null;
  if (query.isError) {
    return (
      <p role="alert" className="text-xs text-destructive" data-testid="client-asked-before-error">
        Nie udało się wczytać pytań, które ten klient zadawał wcześniej.
      </p>
    );
  }
  const questions = Array.isArray(query.data) ? query.data : [];
  if (questions.length === 0) return null;
  return (
    <details
      className="rounded-xl border border-border bg-card p-4 text-sm"
      data-testid="client-asked-before"
    >
      <summary className="cursor-pointer font-semibold text-foreground">
        Klient pytał wcześniej ({questions.length})
      </summary>
      <p className="mt-2 text-xs text-muted-foreground">
        Pytania z rozmów u tego klienta — przydadzą się w pytaniach screeningowych
        profilu Championa.
      </p>
      <ul className="mt-2 space-y-1">
        {questions.map((q) => (
          <li key={q.id} className="text-xs text-foreground">
            • {q.text}
          </li>
        ))}
      </ul>
    </details>
  );
}
