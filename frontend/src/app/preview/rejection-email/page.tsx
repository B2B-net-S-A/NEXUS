"use client";

// Publiczny harness okna odrzucenia z podglądem maila (13.10.2026). Renderuje
// PRAWDZIWY `RejectionV2`; podgląd (`POST /api/rejection-emails/preview`) jest
// zasiany w cache ze znacznikiem czasu w przyszłości, więc okno nie pyta API
// (sieć i tak odcina layout `/preview`). Dane fikcyjne.
// `?state=one` (domyślnie) — jedna osoba po „CV wysłane”, mail może wyjść:
//   zaznacz checkbox, popraw treść, „Przywróć treść domyślną”.
// `?state=blocked` — brak skrzynki Microsoft 365: checkbox wyłączony,
//   „Podłącz skrzynkę” (17.10.2026).
// `?state=bulk` — trzy osoby z różnych etapów (17.10.2026): przełącznik treści
//   „przed klientem” / „po kliencie”, „+N w toku”, osoba ze „Screening” bez maila.
// `?state=others` — osoba z „Zweryfikowany”, która jest w dwóch innych
//   rekrutacjach (17.10.2026, D2): treść „przed klientem”, dopisek obok pola,
//   jedna rekrutacja bez nazwy dla kandydata.
// `?state=merge` — do osoby czeka już mail z innej rekrutacji (17.10.2026, D3):
//   „Jeden wspólny mail” (domyślnie) albo „Osobny mail”.
// `?state=work_mode` — powód „Nie akceptuje trybu pracy” (14.10.2026):
//   rekrutacja hybrydowa z 2 dniami w biurze, na profilu „Hybrydowo · do
//   3 dni”; po wyborze powodu pytanie o dni i podgląd zmiany na profilu.

import { useEffect, useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { RejectionV2 } from "@/components/v2/modals/RejectionV2";
import {
  rejectionEmailPreviewKey,
  type RejectionEmailPreview,
} from "@/lib/rejection-email";

type State = "one" | "blocked" | "bulk" | "others" | "merge" | "work_mode";

const JOB_ID = 9001;
const CLOSING =
  "Życzymy powodzenia i zachęcamy do udziału w przyszłych procesach rekrutacyjnych!";
const AFTER_BODY =
  "Cześć Anna,\n\n" +
  "dziękujemy za udział w rekrutacji na stanowisko Senior Data Architect. " +
  "Niestety został wybrany inny kandydat.";
const beforeBody = (name: string) =>
  `Cześć ${name},\n\n` +
  "dziękujemy za rozmowę i czas poświęcony na rekrutację na stanowisko Senior Data " +
  "Architect. Po przeanalizowaniu wymagań projektu zdecydowaliśmy, że w tym procesie " +
  "nie przedstawimy Twojej kandydatury.";
const SUBJECT = "Informacja zwrotna — Senior Data Architect";
const OTHERS_TEXT =
  "To dotyczy tylko tej rekrutacji — nadal bierzesz udział w naszych pozostałych " +
  "procesach:\n• Java Tech Lead\n• i jeszcze 1 inna rekrutacja\n\n" +
  "Odezwiemy się, gdy będziemy mieć w nich nowe informacje.";
const OTHERS = [
  { job_id: 9101, title: "Java Tech Lead · bankowość", mail_title: "Java Tech Lead", column: "client_interview" },
  { job_id: 9102, title: "Backend Kotlin · płatności", mail_title: null, column: "cv_qc" },
];

const PEOPLE: Record<State, { candidateId: number; name: string }[]> = {
  one: [{ candidateId: 501, name: "Anna Przykładowa" }],
  // Inna osoba niż w `one` — każdy stan ma własny klucz podglądu w cache.
  blocked: [{ candidateId: 511, name: "Anna Przykładowa" }],
  bulk: [
    { candidateId: 501, name: "Anna Przykładowa" },
    { candidateId: 502, name: "Jan Testowy" },
    { candidateId: 503, name: "Ewa Fikcyjna" },
  ],
  others: [{ candidateId: 531, name: "Ewa Fikcyjna" }],
  merge: [{ candidateId: 541, name: "Anna Przykładowa" }],
  work_mode: [{ candidateId: 521, name: "Tomasz Przykładowy" }],
};

const PREVIEW: Record<State, RejectionEmailPreview> = {
  one: {
    subject: SUBJECT,
    body: AFTER_BODY,
    closing: CLOSING,
    text_kind: "after_client",
    people: [
      {
        candidate_id: 501,
        to_email: "anna.przykladowa@example.com",
        skip_reason: null,
        text_kind: "after_client",
        other_processes: [],
      },
    ],
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
    body: AFTER_BODY,
    closing: CLOSING,
    text_kind: "after_client",
    people: [
      {
        candidate_id: 501,
        to_email: "anna.przykladowa@example.com",
        skip_reason: null,
        text_kind: "after_client",
        other_processes: [OTHERS[0]],
      },
      {
        candidate_id: 502,
        to_email: "jan.testowy@example.com",
        skip_reason: null,
        text_kind: "before_client",
        other_processes: [],
      },
      {
        candidate_id: 503,
        to_email: null,
        skip_reason: "not_client_visible",
        text_kind: null,
        other_processes: [],
      },
    ],
    samples: [
      {
        text_kind: "after_client",
        candidate_id: 501,
        subject: SUBJECT,
        body: AFTER_BODY,
        closing: CLOSING,
        other_processes_text: OTHERS_TEXT,
      },
      {
        text_kind: "before_client",
        candidate_id: 502,
        subject: SUBJECT,
        body: beforeBody("Jan"),
        closing: CLOSING,
        other_processes_text: null,
      },
    ],
  },
  others: {
    subject: SUBJECT,
    body: beforeBody("Ewa"),
    closing: CLOSING,
    other_processes_text: OTHERS_TEXT,
    text_kind: "before_client",
    title_warning: false,
    people: [
      {
        candidate_id: 531,
        to_email: "ewa.fikcyjna@example.com",
        skip_reason: null,
        text_kind: "before_client",
        other_processes: OTHERS,
      },
    ],
  },
  merge: {
    subject: SUBJECT,
    body: AFTER_BODY,
    closing: CLOSING,
    text_kind: "after_client",
    merged: {
      text_kind: "merged",
      candidate_id: 541,
      subject: "Informacja zwrotna — Java Tech Lead, Senior Data Architect",
      body:
        "Cześć Anna,\n\ndziękujemy za udział w rekrutacjach na stanowiska Java Tech Lead " +
        "i Senior Data Architect. W tych dwóch procesach nie przechodzisz dalej.",
      closing: CLOSING,
      other_processes_text:
        "To dotyczy tylko tych rekrutacji — nadal bierzesz udział w naszym pozostałym " +
        "procesie:\n• Backend Developer (Kotlin)\n\n" +
        "Odezwiemy się, gdy będziemy mieć w nim nowe informacje.",
    },
    people: [
      {
        candidate_id: 541,
        to_email: "anna.przykladowa@example.com",
        skip_reason: null,
        text_kind: "after_client",
        other_processes: [
          { job_id: 9103, title: "Backend Kotlin · płatności", mail_title: "Backend Developer (Kotlin)", column: "verified" },
        ],
        pending_mail: {
          id: 77,
          scheduled_at: "2026-10-17T09:42:00Z",
          sender_name: "Marta Testowa",
          job_titles: ["Java Tech Lead · bankowość"],
        },
      },
    ],
  },
  work_mode: {
    subject: SUBJECT,
    body: AFTER_BODY,
    closing: CLOSING,
    text_kind: "after_client",
    people: [{ candidate_id: 521, to_email: "tomasz.przykladowy@example.com", skip_reason: null }],
  },
};

const STAGE_LABEL: Record<State, string> = {
  one: "CV wysłane",
  blocked: "CV wysłane",
  bulk: "",
  others: "Zweryfikowany",
  merge: "Rozmowa u klienta",
  work_mode: "Rozmowa u klienta",
};

const REASONS = [
  { id: "1", label: "Brak doświadczenia", applies_to: ["rejected" as const] },
  { id: "2", label: "Za wysokie oczekiwania finansowe", applies_to: ["rejected" as const] },
  { id: "3", label: "Nie spełnia wymagań technicznych", applies_to: ["rejected" as const] },
  { id: "4", label: "Zatrudniony gdzie indziej", applies_to: ["rejected" as const] },
  {
    id: "5",
    name: "work_mode_mismatch",
    label: "Nie akceptuje trybu pracy (biuro / hybryda)",
    applies_to: ["rejected" as const],
  },
  { id: "6", label: "Inne", applies_to: ["rejected" as const] },
];

function readState(): State {
  const raw = new URLSearchParams(window.location.search).get("state");
  return raw === "blocked" ||
    raw === "bulk" ||
    raw === "others" ||
    raw === "merge" ||
    raw === "work_mode"
    ? raw
    : "one";
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
          state === "bulk"
            ? null
            : { name: PEOPLE[state][0].name, stageLabel: STAGE_LABEL[state] }
        }
        emailPreview={{ jobId: JOB_ID, people: PEOPLE[state] }}
        workModeJob={
          state === "work_mode" ? { remotePolicy: "hybrid", onsiteDaysPerWeek: 2 } : null
        }
        profileWorkMode={
          state === "work_mode" ? { modes: ["remote", "hybrid"], days: 3 } : undefined
        }
        onConfirm={() => {}}
      />
    </QueryClientProvider>
  );
}
