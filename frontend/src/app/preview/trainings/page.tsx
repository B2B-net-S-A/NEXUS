"use client";

/**
 * Harness „Szkolenia” (13.11.2026): prawdziwa karta szkolenia i biblioteka na
 * fikcyjnych danych, bez zapytań (komponenty dostają dane i akcje w propsach).
 *
 * Stany (`?state=`):
 * - `quote` (domyślnie) — TCM: wycena A–E do decyzji z porównaniem z poprzednim
 *   szkoleniem tej samej trenerki;
 * - `handover` — po szkoleniu: pliki do przyjęcia, jeden zwrócony do poprawy,
 *   nagranie z Teams, „Opublikuj” wyłączone do zapłaty;
 * - `finance` — ta sama karta oczami Finansów („Zapłacone” czeka na pliki);
 * - `library` — biblioteka: na żywo z zapisem, nagranie na górze, rozdziały, materiały.
 */

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { TrainingCard, type TrainingCardActions } from "@/components/trainings/TrainingCard";
import { TrainingCalendar } from "@/components/trainings/TrainingCalendar";
import { TrainingLibrary } from "@/components/trainings/TrainingLibrary";

import {
  FINANCE_ME,
  HANDOVER,
  LIBRARY,
  PEOPLE,
  PREVIOUS_FEES,
  PREVIOUS_ROW,
  QUOTED,
  TCM_ME,
} from "./fixtures";

const STATES = [
  { key: "quote", label: "Wycena do decyzji" },
  { key: "handover", label: "Przekazanie plików" },
  { key: "finance", label: "Finanse" },
  { key: "library", label: "Biblioteka" },
] as const;
type State = (typeof STATES)[number]["key"];

const TODAY = "2026-12-06";
const nothing = async () => false;
const pending = () => new Promise<string | null>(() => undefined);

const ACTIONS: TrainingCardActions = {
  saveOrder: nothing,
  send: nothing,
  cancel: nothing,
  returnQuote: nothing,
  acceptQuote: nothing,
  generateAgreement: nothing,
  companySign: nothing,
  downloadAgreement: () => undefined,
  downloadFile: () => undefined,
  reviewFile: nothing,
  toggleParticipants: nothing,
  uploadFile: nothing,
  mediaUrl: pending,
  markPaid: nothing,
  publish: nothing,
  importAttendance: nothing,
};

function Harness() {
  const requested = useSearchParams().get("state");
  const state: State = STATES.some((s) => s.key === requested) ? (requested as State) : "quote";
  return (
    <div className="min-h-dvh bg-background p-4 md:p-6">
      <nav aria-label="Stany harnessu" className="mb-4 flex flex-wrap gap-2 text-xs">
        {STATES.map((entry) => (
          <a
            key={entry.key}
            href={`?state=${entry.key}`}
            className={
              entry.key === state
                ? "rounded-full bg-primary px-3 py-1 text-primary-foreground"
                : "rounded-full border border-border px-3 py-1 text-foreground"
            }
          >
            {entry.label}
          </a>
        ))}
        <span className="text-muted-foreground">Dane fikcyjne, bez zapytań.</span>
      </nav>
      {state === "library" ? (
        <div className="space-y-6">
          <TrainingCalendar live={LIBRARY.live} today={TODAY} onRegister={nothing} />
          <TrainingLibrary library={LIBRARY} getMediaUrl={pending} onDownload={() => undefined} />
        </div>
      ) : (
        <TrainingCard
          view={state === "quote" ? QUOTED : HANDOVER}
          me={state === "finance" ? FINANCE_ME : TCM_ME}
          today={TODAY}
          previous={state === "quote" ? { row: PREVIOUS_ROW, fees: PREVIOUS_FEES } : null}
          people={PEOPLE}
          actions={ACTIONS}
        />
      )}
    </div>
  );
}

export default function TrainingsHarnessPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
