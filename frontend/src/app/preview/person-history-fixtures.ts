/**
 * Fikcyjna historia notatek osoby dla harnessów panelu rekrutacji
 * (`/preview/job-detail`, `/preview/screening-form`): notatki z innych
 * rekrutacji i bez rekrutacji, wynik tych rekrutacji i ruchy pary.
 * Wyłącznie dane zmyślone — żadnych nazwisk, klientów ani stawek z produkcji.
 */

import type { CandidateNotesResponse } from "@/components/v2/pages/candidate-notes-query";
import type { RecruitmentOutcomeRow } from "@/components/v2/pages/candidate-outcomes-query";
import type { JobMoveLogPage } from "@/components/v2/recruitment/JobMoveLog";

const SYSTEMS_JOB_ID = 4301;
const BUSINESS_JOB_ID = 4302;

const LONG_TRAFFIT_NOTE = [
  "Rozmowa wstępna, 35 minut. Od 2015 analityk biznesowy, najpierw motoryzacja, potem farmacja.",
  "",
  "Ostatnie dwa lata przy wdrożeniu CRM dla działu obsługi, prowadził warsztaty z biznesem.",
  "Mocne strony: zbieranie wymagań, modelowanie procesów, praca z interesariuszami po niemiecku.",
  "Słabiej: SQL tylko podstawy, brak doświadczenia z hurtowniami danych.",
  "Szuka projektów z analizą danych, nie chce wdrożeń portali intranetowych.",
  "Do biura w Warszawie może przyjechać najwyżej dwa razy w miesiącu.",
].join("\n");

function note(id: number, extra: Record<string, unknown>) {
  return {
    id,
    note_type: "general",
    author_id: null,
    author_name: null,
    job_id: null,
    job_title: null,
    pinned_at: null,
    is_system: false,
    content_hidden: false,
    group: "talks",
    replies: [],
    ...extra,
  };
}

/** Notatki osoby z bogatą historią: nic w bieżącej rekrutacji, dużo wcześniej. */
export function richHistoryNotes(candidateId: number): CandidateNotesResponse {
  const base = candidateId * 100;
  const items = [
    note(base + 1, {
      author_name: "Ewa Wzorcowa",
      created_at: "2025-04-02T09:40:00Z",
      job_id: SYSTEMS_JOB_ID,
      job_title: "Analityk systemowy",
      content:
        "Feedback klienta: mocna w modelowaniu procesów, za mało projektów z integracjami systemów. Przekazałam telefonicznie. Chce wracać do nas przy rolach czysto analitycznych.",
    }),
    note(base + 2, {
      author_name: "Karol Wzorcowy",
      created_at: "2025-03-28T08:15:00Z",
      job_id: SYSTEMS_JOB_ID,
      job_title: "Analityk systemowy",
      kind: "dl_rate",
      group: "delivery",
      content_hidden: true,
      content: "Notatka Delivery Leada o stawce do klienta — niewidoczna dla Twojej roli.",
    }),
    note(base + 3, {
      author_id: 7,
      author_name: "Marta Nowak",
      created_at: "2025-03-14T15:20:00Z",
      job_id: SYSTEMS_JOB_ID,
      job_title: "Analityk systemowy",
      content:
        "Rozmowa 20 min. Tylko B2B, oczekuje 130 zł/h. Zdalnie, w biurze najwyżej 2 razy w miesiącu. Miesiąc wypowiedzenia. UML na co dzień: przypadki użycia, diagramy sekwencji.",
    }),
    note(base + 4, {
      author_id: 7,
      author_name: "Marta Nowak",
      created_at: "2025-03-12T09:05:00Z",
      job_id: SYSTEMS_JOB_ID,
      job_title: "Analityk systemowy",
      kind: "contact_attempt",
      group: "contact",
      content: "Nie odebrała, zostawiłam SMS.",
    }),
    note(base + 5, {
      created_at: "2025-03-01T08:00:00Z",
      job_id: SYSTEMS_JOB_ID,
      job_title: "Analityk systemowy",
      external_source: "system",
      is_system: true,
      group: "automat",
      content: "Auto-match 70/100 — kandydat dodany automatycznie.",
    }),
    note(base + 6, {
      author_name: "Ewa Wzorcowa",
      created_at: "2024-09-18T12:30:00Z",
      job_id: BUSINESS_JOB_ID,
      job_title: "Business Analyst",
      content:
        "Zrezygnowała: przedłużyła kontrakt u obecnego klienta do końca 2025. Prosi o kontakt od października 2025.",
    }),
    note(base + 7, {
      author_name: "Ewa Wzorcowa",
      created_at: "2024-09-03T07:50:00Z",
      job_id: BUSINESS_JOB_ID,
      job_title: "Business Analyst",
      content: "Pierwsza rozmowa. 8 lat jako analityk, ostatnie 3 w telekomunikacji. Angielski B2, niemiecki C1.",
    }),
    // Import z Traffita bez powiązania z rekrutacją: bez autora, długa treść.
    note(base + 8, { created_at: "2023-06-20T11:05:00Z", content: LONG_TRAFFIT_NOTE }),
    note(base + 9, {
      created_at: "2023-05-11T07:12:00Z",
      content: "Nie dzwonić przed 10:00. Woli najpierw wiadomość, potem telefon.",
    }),
  ];
  return {
    items,
    total: items.length,
    group_counts: { talks: 6, contact: 1, delivery: 1, email: 0, automat: 1 },
  };
}

/** Osoba, o której pisano tylko w bieżącej rekrutacji. */
export function currentJobNotes(candidateId: number, jobId: number, jobTitle: string): CandidateNotesResponse {
  const items = [
    note(candidateId * 100 + 1, {
      author_id: 7,
      author_name: "Marta Nowak",
      created_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
      job_id: jobId,
      job_title: jobTitle,
      content: "Umówiony telefon na jutro 11:00.",
    }),
  ];
  return { items, total: 1, group_counts: { talks: 1, contact: 0, delivery: 0, email: 0, automat: 0 } };
}

export const NO_NOTES: CandidateNotesResponse = {
  items: [],
  total: 0,
  group_counts: { talks: 0, contact: 0, delivery: 0, email: 0, automat: 0 },
};

/** Wyniki wcześniejszych rekrutacji osoby z `richHistoryNotes`. */
export const RICH_HISTORY_OUTCOMES: RecruitmentOutcomeRow[] = [
  {
    job_id: SYSTEMS_JOB_ID,
    job_title: "Analityk systemowy",
    job_status: "published",
    client_name: "Bank Przykładowy",
    latest_stage: "rejected",
    latest_stage_name: null,
    first_seen: "2025-03-01T08:00:00Z",
    last_seen: "2025-04-02T09:00:00Z",
    rejection_reason: "Klient — za mało projektów z integracjami",
    stages: [
      { stage: "rejected", stage_name: null, moved_at: "2025-04-02T09:00:00Z" },
      { stage: "client_interview", stage_name: null, moved_at: "2025-03-20T09:00:00Z" },
      { stage: "cv_sent", stage_name: null, moved_at: "2025-03-17T09:00:00Z" },
      { stage: "new", stage_name: null, moved_at: "2025-03-01T08:00:00Z" },
    ],
  },
  {
    job_id: BUSINESS_JOB_ID,
    job_title: "Business Analyst",
    job_status: "closed",
    client_name: "Telekom Przykładowy",
    latest_stage: "withdrawn",
    latest_stage_name: null,
    first_seen: "2024-09-03T07:00:00Z",
    last_seen: "2024-09-18T12:30:00Z",
    rejection_reason: null,
    stages: [
      { stage: "withdrawn", stage_name: null, moved_at: "2024-09-18T12:30:00Z" },
      { stage: "verified", stage_name: null, moved_at: "2024-09-10T09:00:00Z" },
      { stage: "new", stage_name: null, moved_at: "2024-09-03T07:00:00Z" },
    ],
  },
];

/** Ruchy pary: wejście do rekrutacji i — gdy osoba stoi dalej — jeden ruch. */
export function pairMoves(candidateId: number, stageRowId: number, columnName: string): JobMoveLogPage {
  const first = "Nowi / Analiza CV";
  const added = {
    id: stageRowId * 10 + 1,
    candidate_id: candidateId,
    candidate_name: null,
    from_stage_name: null,
    to_stage_name: first,
    moved_by_name: "Marta Nowak",
    moved_at: new Date(Date.now() - 26 * 3_600_000).toISOString(),
    source: "nexus",
  };
  if (columnName === first) return { items: [added], total: 1 };
  return {
    items: [
      {
        ...added,
        id: stageRowId * 10 + 2,
        from_stage_name: first,
        to_stage_name: columnName,
        moved_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
      },
      added,
    ],
    total: 2,
  };
}
