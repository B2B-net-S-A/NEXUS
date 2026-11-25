"use client";

import { Suspense } from "react";

import { InterviewQuestionBank } from "@/components/v2/recruitment/InterviewQuestionBank";

/**
 * Rekrutacje → „Pytania z rozmów”: baza pytań klientów z debriefów i archiwum
 * Excela — lista stanowisk, a w stanowisku pytania z propozycją odpowiedzi.
 * `Suspense` jest dla `useSearchParams` (stanowisko w adresie).
 */
export default function InterviewQuestionsPage() {
  return (
    <div className="mx-auto max-w-[1440px] space-y-4 p-4 md:p-6">
      <div>
        <p className="text-sm text-muted-foreground">Rekrutacje</p>
        <h1 className="text-2xl font-bold tracking-[-0.02em] text-foreground">Pytania z rozmów</h1>
        <p className="mt-1 max-w-4xl text-sm text-muted-foreground">
          Pytania, które klienci zadali na rozmowach, pogrupowane po stanowisku. Wejdź w stanowisko, żeby
          zobaczyć pytania i propozycje odpowiedzi. Każdy debrief dopisuje pytania sam.
        </p>
      </div>
      <Suspense fallback={null}>
        <InterviewQuestionBank />
      </Suspense>
    </div>
  );
}
