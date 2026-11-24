"use client";

import { InterviewQuestionBank } from "@/components/v2/recruitment/InterviewQuestionBank";

/**
 * Rekrutacje → „Pytania z rozmów”: baza pytań klientów
 * z debriefów i archiwum Excela, z filtrem po kliencie, stanowisku i managerze.
 */
export default function InterviewQuestionsPage() {
  return (
    <div className="mx-auto max-w-[1440px] space-y-4 p-4 md:p-6">
      <div>
        <p className="text-sm text-muted-foreground">Rekrutacje</p>
        <h1 className="text-2xl font-bold tracking-[-0.02em] text-foreground">Pytania z rozmów</h1>
        <p className="mt-1 max-w-4xl text-sm text-muted-foreground">
          Pytania, które klienci zadali na rozmowach. Każdy debrief dopisuje je sam, stanowisko i manager
          przychodzą z rekrutacji. To samo pytanie u tego samego klienta jest jednym wierszem.
        </p>
      </div>
      <InterviewQuestionBank />
    </div>
  );
}
