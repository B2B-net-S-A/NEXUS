"use client";

// Publiczny harness okna odrzucenia z podglądem maila (13.10.2026). Renderuje
// PRAWDZIWY `RejectionV2`; podgląd (`POST /api/rejection-emails/preview`) jest
// zasiany w cache ze znacznikiem czasu w przyszłości, więc okno nie pyta API
// (sieć i tak odcina layout `/preview`). Dane fikcyjne.
// `?state=one` (domyślnie) — jedna osoba, mail może wyjść: zaznacz checkbox,
//   popraw treść, „Przywróć treść domyślną”.
// `?state=blocked` — brak skrzynki Microsoft 365: checkbox wyłączony z powodem.
// `?state=bulk` — trzy osoby, jedna bez maila: podgląd tylko do odczytu.

import { useEffect, useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { RejectionV2 } from "@/components/v2/modals/RejectionV2";
import {
  rejectionEmailPreviewKey,
  type RejectionEmailPreview,
} from "@/lib/rejection-email";

type State = "one" | "blocked" | "bulk";

const JOB_ID = 9001;
const BODY =
  "Cześć Anna,\n\n" +
  "dziękujemy za udział w rekrutacji na stanowisko Senior Data Architect. " +
  "Niestety został wybrany inny kandydat.\n\n" +
  "Życzymy powodzenia i zachęcamy do udziału w przyszłych procesach rekrutacyjnych!";
const SUBJECT = "Informacja zwrotna — Senior Data Architect";

const PEOPLE: Record<State, { candidateId: number; name: string }[]> = {
  one: [{ candidateId: 501, name: "Anna Przykładowa" }],
  // Inna osoba niż w `one` — każdy stan ma własny klucz podglądu w cache.
  blocked: [{ candidateId: 511, name: "Anna Przykładowa" }],
  bulk: [
    { candidateId: 501, name: "Anna Przykładowa" },
    { candidateId: 502, name: "Jan Testowy" },
    { candidateId: 503, name: "Ewa Fikcyjna" },
  ],
};

const PREVIEW: Record<State, RejectionEmailPreview> = {
  one: {
    subject: SUBJECT,
    body: BODY,
    people: [{ candidate_id: 501, to_email: "anna.przykladowa@example.com", skip_reason: null }],
  },
  blocked: {
    subject: null,
    body: null,
    people: [
      { candidate_id: 511, to_email: "anna.przykladowa@example.com", skip_reason: "no_mailbox" },
    ],
  },
  bulk: {
    subject: SUBJECT,
    body: BODY,
    people: [
      { candidate_id: 501, to_email: "anna.przykladowa@example.com", skip_reason: null },
      { candidate_id: 502, to_email: "jan.testowy@example.com", skip_reason: null },
      { candidate_id: 503, to_email: "ewa.fikcyjna@example.com", skip_reason: "not_client_visible" },
    ],
  },
};

const REASONS = [
  { id: "1", label: "Brak doświadczenia", applies_to: ["rejected" as const] },
  { id: "2", label: "Za wysokie oczekiwania finansowe", applies_to: ["rejected" as const] },
  { id: "3", label: "Nie spełnia wymagań technicznych", applies_to: ["rejected" as const] },
  { id: "4", label: "Zatrudniony gdzie indziej", applies_to: ["rejected" as const] },
];

function readState(): State {
  const raw = new URLSearchParams(window.location.search).get("state");
  return raw === "blocked" || raw === "bulk" ? raw : "one";
}

export default function RejectionEmailHarness() {
  const [state, setState] = useState<State | null>(null);
  useEffect(() => setState(readState()), []);

  const client = useMemo(() => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    // Znacznik w przyszłości: `staleTime: 0` w oknie nie uzna danych za stare.
    const future = Date.now() + 365 * 24 * 3600 * 1000;
    for (const key of Object.keys(PREVIEW) as State[]) {
      qc.setQueryData(
        rejectionEmailPreviewKey(
          JOB_ID,
          PEOPLE[key].map((p) => p.candidateId)
        ),
        PREVIEW[key],
        { updatedAt: future }
      );
    }
    return qc;
  }, []);

  if (state === null) return null;
  return (
    <QueryClientProvider client={client}>
      <main className="min-h-dvh bg-background p-6 text-sm text-muted-foreground">
        Harness okna odrzucenia: {state}
      </main>
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={REASONS}
        emailAvailable
        subject={
          state === "bulk" ? null : { name: "Anna Przykładowa", stageLabel: "Rozmowa u klienta" }
        }
        emailPreview={{ jobId: JOB_ID, people: PEOPLE[state] }}
        onConfirm={() => {}}
      />
    </QueryClientProvider>
  );
}
