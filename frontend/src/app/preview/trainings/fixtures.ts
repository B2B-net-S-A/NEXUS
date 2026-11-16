// Dane fikcyjne harnessu „Szkolenia” (osoby, kontrakty i kwoty zmyślone).

import type {
  TrainingFees,
  TrainingFileRow,
  TrainingLibrary,
  TrainingPeople,
  TrainingRow,
  TrainingView,
  TrainingsMe,
} from "@/lib/api/trainings";

export const TCM_ME: TrainingsMe = {
  can_manage: true,
  can_read: true,
  can_pay: false,
  is_company_signer: false,
};

export const FINANCE_ME: TrainingsMe = {
  can_manage: false,
  can_read: true,
  can_pay: true,
  is_company_signer: false,
};

function fees(prep: string, delivery: string, presentation: string | null, audio: string | null, rights: string): TrainingFees {
  const items: TrainingFees["items"] = [
    { key: "fee_prep", label: "A. Przygotowanie programu i materiałów szkoleniowych", needs: null, amount: prep },
    { key: "fee_delivery", label: "B. Przeprowadzenie szkolenia", needs: null, amount: delivery },
    { key: "fee_presentation", label: "C. Przygotowanie i przekazanie prezentacji", needs: "presentation", amount: presentation },
    { key: "fee_audio", label: "D. Przygotowanie i przekazanie plików audio", needs: "audio", amount: audio },
    { key: "fee_rights", label: "E. Przeniesienie autorskich praw majątkowych", needs: null, amount: rights },
  ];
  const total = items.reduce((sum, item) => sum + Number(item.amount ?? 0), 0);
  return { items, total: total.toFixed(2) };
}

export const PREVIOUS_FEES = fees("2400.00", "1800.00", "600.00", "900.00", "500.00");

export const PREVIOUS_ROW: TrainingRow = {
  id: 901,
  title: "Cyberbezpieczeństwo w pracy z AI",
  status: "signed",
  status_label: "Umowa podpisana",
  trainer_contract_id: 4101,
  trainer_kind: "consultant",
  trainer_name: "Anna Przykładowa",
  session_date: "2026-10-07",
  total: PREVIOUS_FEES.total,
  invoice_ready_at: "2026-10-10T10:00:00Z",
  paid_at: "2026-10-20T10:00:00Z",
  published_at: "2026-10-21T09:00:00Z",
  can_publish: true,
};

const BASE: TrainingView = {
  id: 902,
  status: "quoted",
  status_label: "Wycena do decyzji",
  trainer_kind: "consultant",
  trainer_contract_id: 4101,
  trainer_user_id: null,
  trainer_name: "Anna Przykładowa",
  application_id: 31,
  join_url: "https://teams.microsoft.com/l/meetup-join/przyklad",
  order: {
    title: "Bezpieczne prompty w projekcie klienta",
    topic: "Bezpieczeństwo, AI w pracy",
    description: "Jak korzystać z asystentów AI w projekcie u klienta, nie wynosząc danych.",
    session_date: "2026-12-04",
    time_from: "16:00",
    time_to: "18:00",
    duration_minutes: 120,
    platform: "Microsoft Teams",
    expected_participants: 40,
    quote_due_on: "2026-11-20",
    participant_materials: "Podsumowanie i ćwiczenia z kluczem odpowiedzi.",
    deliverables: [
      { key: "materials", label: "Materiały dla uczestników", required: true, format: "PDF", due_days: 2 },
      { key: "presentation", label: "Prezentacja", required: true, format: "PPTX do edycji i PDF dla uczestników", due_days: 2 },
    ],
    knowledge_test: false,
    extra_terms: "",
  },
  quote: {
    agenda: [
      { title: "Jak AI zmienia ataki", minutes: 35 },
      { title: "Ćwiczenie 1: rozpoznaj atak", minutes: 25 },
      { title: "Bezpieczne korzystanie z narzędzi AI", minutes: 40 },
      { title: "Ćwiczenia 2–3", minutes: 20 },
    ],
    own_materials: "",
    third_party_materials: "",
    quote_note: "Prezentację przygotuję od zera pod ten temat.",
    return_note: null,
    quoted_at: "2026-11-12T09:30:00Z",
  },
  fees: fees("1600.00", "1200.00", "500.00", null, "800.00"),
  agreement: { number: null, generated_at: null, trainer_signed_at: null, company_signed_at: null },
  payment: { invoice_ready_at: null, paid_at: null },
  handover: [
    { key: "materials", label: "Materiały dla uczestników", format: "PDF", due_days: 2, required: true, state: "missing", files: [] },
    { key: "presentation", label: "Prezentacja", format: "PPTX do edycji i PDF dla uczestników", due_days: 2, required: true, state: "missing", files: [] },
  ],
  files: [],
  registrations: 0,
  attendance: 0,
  published_at: null,
  can_publish: false,
  chapters: [
    { title: "Jak AI zmienia ataki", start_minute: 0 },
    { title: "Ćwiczenie 1: rozpoznaj atak", start_minute: 35 },
    { title: "Bezpieczne korzystanie z narzędzi AI", start_minute: 60 },
    { title: "Ćwiczenia 2–3", start_minute: 100 },
  ],
  cancelled_at: null,
  cancel_reason: null,
  created_at: "2026-11-05T10:00:00Z",
  updated_at: "2026-11-12T09:30:00Z",
};

export const QUOTED: TrainingView = BASE;

const MATERIALS_FILE: TrainingFileRow = {
  id: 7001,
  kind: "deliverable",
  deliverable_key: "materials",
  status: "returned",
  file_name: "cwiczenia-i-klucze.pdf",
  content_type: "application/pdf",
  size_bytes: 412_000,
  uploaded_at: "2026-12-05T08:10:00Z",
  review_note: "W kluczu ćwiczenia 2 brakuje odpowiedzi do zadania 4.",
  reviewed_at: "2026-12-05T12:00:00Z",
  fix_due_on: "2026-12-10",
  for_participants: true,
};

const PRESENTATION_FILE: TrainingFileRow = {
  id: 7002,
  kind: "deliverable",
  deliverable_key: "presentation",
  status: "submitted",
  file_name: "prezentacja.pptx",
  content_type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  size_bytes: 8_400_000,
  uploaded_at: "2026-12-05T08:12:00Z",
  review_note: null,
  reviewed_at: null,
  fix_due_on: null,
  for_participants: false,
};

const RECORDING_FILE: TrainingFileRow = {
  id: 7003,
  kind: "recording",
  deliverable_key: null,
  status: "accepted",
  file_name: "nagranie-teams.mp4",
  content_type: "video/mp4",
  size_bytes: 143_000_000,
  uploaded_at: "2026-12-04T19:00:00Z",
  review_note: null,
  reviewed_at: null,
  fix_due_on: null,
  for_participants: true,
};

const INTERNAL_FILE: TrainingFileRow = {
  id: 7004,
  kind: "internal",
  deliverable_key: null,
  status: "accepted",
  file_name: "ankieta-po-szkoleniu.xlsx",
  content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  size_bytes: 24_000,
  uploaded_at: "2026-12-06T10:00:00Z",
  review_note: null,
  reviewed_at: null,
  fix_due_on: null,
  for_participants: false,
};

export const HANDOVER: TrainingView = {
  ...BASE,
  status: "signed",
  status_label: "Umowa podpisana",
  agreement: {
    number: "SZK/902/2026",
    generated_at: "2026-11-14T10:00:00Z",
    trainer_signed_at: "2026-11-15T09:00:00Z",
    company_signed_at: "2026-11-16T11:00:00Z",
  },
  handover: [
    { ...BASE.handover[0], state: "returned", files: [MATERIALS_FILE] },
    { ...BASE.handover[1], state: "submitted", files: [PRESENTATION_FILE] },
  ],
  files: [RECORDING_FILE, MATERIALS_FILE, PRESENTATION_FILE, INTERNAL_FILE],
  registrations: 38,
  attendance: 31,
};

export const PEOPLE: TrainingPeople = {
  registrations: [
    { name: "Bartosz Fikcyjny", email: "bartosz@example.com", who: "staff" },
    { name: "Celina Zmyślona", email: "celina@example.com", who: "consultant" },
  ],
  attendance: [
    { name: "Bartosz Fikcyjny", email: "bartosz@example.com", minutes: 118, matched: true },
    { name: "Gość spoza firmy", email: null, minutes: 42, matched: false },
  ],
};

export const LIBRARY: TrainingLibrary = {
  live: [
    {
      id: 902,
      title: "Bezpieczne prompty w projekcie klienta",
      topic: "Bezpieczeństwo",
      session_date: "2026-12-04",
      time_from: "16:00",
      time_to: "18:00",
      platform: "Microsoft Teams",
      registered: false,
      join_url: null,
    },
    {
      id: 903,
      title: "Onboarding w Teams",
      topic: "Narzędzia",
      session_date: "2026-11-20",
      time_from: "10:00",
      time_to: "11:00",
      platform: "Microsoft Teams",
      registered: true,
      join_url: "https://teams.microsoft.com/l/meetup-join/przyklad-2",
    },
  ],
  recordings: [
    {
      id: 901,
      title: "Cyberbezpieczeństwo w pracy z AI",
      topic: "Bezpieczeństwo",
      description: "Webinar dla konsultantów: ataki wspierane przez AI i dobre nawyki.",
      session_date: "2026-10-07",
      duration_minutes: 180,
      trainer_kind: "consultant",
      chapters: BASE.chapters,
      files: [
        { id: 8001, kind: "recording", file_name: "nagranie.mp4", content_type: "video/mp4", size_bytes: 143_000_000 },
        { id: 8002, kind: "deliverable", file_name: "prezentacja.pdf", content_type: "application/pdf", size_bytes: 2_100_000 },
        { id: 8003, kind: "deliverable", file_name: "cwiczenia-1-3-i-klucze.pdf", content_type: "application/pdf", size_bytes: 400_000 },
        { id: 8004, kind: "deliverable", file_name: "podcast.mp3", content_type: "audio/mpeg", size_bytes: 31_000_000 },
      ],
    },
    {
      id: 900,
      title: "DORA w praktyce projektu",
      topic: "Regulacje",
      description: "",
      session_date: "2026-09-27",
      duration_minutes: 90,
      trainer_kind: "employee",
      chapters: [],
      files: [
        { id: 8005, kind: "deliverable", file_name: "dora-podsumowanie.pdf", content_type: "application/pdf", size_bytes: 300_000 },
      ],
    },
  ],
};
