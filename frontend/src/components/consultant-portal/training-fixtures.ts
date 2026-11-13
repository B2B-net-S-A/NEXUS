// Fikcyjne szkolenia dla harnessu `/preview/consultant-panel` i testów ekranów (bez prawdziwych osób i kwot).

import type {
  PortalTraining,
  PortalTrainerApplication,
  PortalTrainings,
  TrainingStatus,
} from "@/lib/api/consultant-portal";

const STATUS_LABELS: Record<TrainingStatus, string> = {
  draft: "Szkic zamówienia",
  ordered: "Czeka na wycenę trenera",
  quoted: "Wycena do decyzji",
  returned: "Wycena odesłana do poprawy",
  accepted: "Umowa do podpisu trenera",
  trainer_signed: "Umowa czeka na podpis B2B Network",
  signed: "Umowa podpisana",
  cancelled: "Anulowane",
};

const AGENDA = [
  { title: "Jak AI zmienia ataki: deepfake, phishing, klonowanie głosu", minutes: 35 },
  { title: "Ćwiczenie 1: rozpoznaj atak", minutes: 25 },
  { title: "Bezpieczne korzystanie z narzędzi AI w projekcie", minutes: 40 },
  { title: "Ćwiczenia 2–3 i omówienie", minutes: 50 },
  { title: "Pytania", minutes: 30 },
];

export function previewTraining(id: number, status: TrainingStatus, extra: Partial<PortalTraining> = {}): PortalTraining {
  const quoted = status !== "ordered";
  const signed = status === "signed";
  return {
    id,
    status,
    status_label: STATUS_LABELS[status],
    order: {
      title: "Cyberbezpieczeństwo w erze AI",
      topic: "Bezpieczeństwo",
      description: "Webinar dla konsultantów: rozpoznawanie ataków z użyciem AI i bezpieczna praca z narzędziami.",
      session_date: signed ? "2026-10-07" : "2026-12-04",
      time_from: "16:00",
      time_to: "19:00",
      duration_minutes: 180,
      platform: "Microsoft Teams",
      expected_participants: 60,
      quote_due_on: "2026-11-20",
      participant_materials: "PDF: podsumowanie, ćwiczenia, klucze odpowiedzi",
      deliverables: [
        { key: "materials", label: "Materiały dla uczestników", required: true, format: "PDF", due_days: 2 },
        { key: "presentation", label: "Prezentacja", required: true, format: "PPTX do edycji i PDF dla uczestników", due_days: 2 },
        { key: "audio", label: "Pliki audio", required: true, format: "gotowy plik MP3 albo M4A, jeden na część", due_days: 7 },
      ],
      knowledge_test: false,
      extra_terms: "",
    },
    quote: {
      agenda: quoted ? AGENDA : [],
      own_materials: quoted ? "Grafiki z mojego kursu (slajdy 12–14)" : "",
      third_party_materials: "",
      quote_note: "",
      return_note: status === "returned" ? "Rozpisz proszę ćwiczenia na osobne moduły." : null,
      quoted_at: quoted ? "2026-11-14T10:00:00+01:00" : null,
    },
    fees: {
      items: [
        { key: "fee_prep", label: "A. Przygotowanie programu i materiałów szkoleniowych", needs: null, amount: quoted ? "2400.00" : null },
        { key: "fee_delivery", label: "B. Przeprowadzenie szkolenia", needs: null, amount: quoted ? "1800.00" : null },
        { key: "fee_presentation", label: "C. Przygotowanie i przekazanie prezentacji", needs: "presentation", amount: quoted ? "600.00" : null },
        { key: "fee_audio", label: "D. Przygotowanie i przekazanie plików audio", needs: "audio", amount: quoted ? "900.00" : null },
        { key: "fee_rights", label: "E. Przeniesienie autorskich praw majątkowych", needs: null, amount: quoted ? "500.00" : null },
      ],
      total: quoted ? "6200.00" : null,
    },
    agreement: {
      number: status === "accepted" || status === "trainer_signed" || signed ? "SZK/2026/11/1" : null,
      generated_at: null,
      trainer_signed_at: status === "trainer_signed" || signed ? "2026-10-01T09:00:00+02:00" : null,
      company_signed_at: signed ? "2026-10-01T12:00:00+02:00" : null,
    },
    payment: { invoice_ready_at: null, paid_at: null },
    handover: signed
      ? [
          {
            key: "materials",
            label: "Materiały dla uczestników",
            format: "PDF",
            due_days: 2,
            required: true,
            state: "returned",
            files: [
              {
                id: 11,
                kind: "deliverable",
                deliverable_key: "materials",
                status: "returned",
                file_name: "materialy-cw1-cw3.pdf",
                content_type: "application/pdf",
                size_bytes: 820_000,
                uploaded_at: "2026-10-09T10:00:00+02:00",
                review_note: "W kluczu ćwiczenia 2 brakuje odpowiedzi do zadania 4.",
                reviewed_at: "2026-11-13T10:00:00+01:00",
                fix_due_on: "2026-11-18",
                for_participants: true,
              },
            ],
          },
          {
            key: "presentation",
            label: "Prezentacja",
            format: "PPTX do edycji i PDF dla uczestników",
            due_days: 2,
            required: true,
            state: "accepted",
            files: [
              {
                id: 12,
                kind: "deliverable",
                deliverable_key: "presentation",
                status: "accepted",
                file_name: "prezentacja.pptx",
                content_type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                size_bytes: 5_400_000,
                uploaded_at: "2026-10-09T10:00:00+02:00",
                review_note: null,
                reviewed_at: "2026-10-10T10:00:00+02:00",
                fix_due_on: null,
                for_participants: false,
              },
            ],
          },
          { key: "audio", label: "Pliki audio", format: "gotowy plik MP3 albo M4A, jeden na część", due_days: 7, required: true, state: "missing", files: [] },
        ]
      : [],
    invoices: [],
    can_quote: status === "ordered" || status === "returned",
    can_sign: status === "accepted",
    can_deliver: signed,
    can_invoice: false,
    ...extra,
  };
}

export const PREVIEW_TRAININGS: PortalTrainings = {
  mine: [
    { id: 1, title: "Cyberbezpieczeństwo w erze AI", status: "signed", status_label: "Umowa podpisana", trainer_kind: "consultant", trainer_name: "", session_date: "2026-10-07", total: "6200.00", invoice_ready_at: null, paid_at: null, published_at: null, can_publish: false },
    { id: 2, title: "Bezpieczne prompty w projekcie", status: "accepted", status_label: "Umowa do podpisu trenera", trainer_kind: "consultant", trainer_name: "", session_date: "2026-12-04", total: "4100.00", invoice_ready_at: null, paid_at: null, published_at: null, can_publish: false },
    { id: 3, title: "NIS2 dla zespołów IT", status: "ordered", status_label: "Czeka na wycenę trenera", trainer_kind: "consultant", trainer_name: "", session_date: "2027-01-15", total: null, invoice_ready_at: null, paid_at: null, published_at: null, can_publish: false },
  ],
  library: {
    recordings: [
      {
        id: 21,
        title: "Tech Sessions #01: Cyberbezpieczeństwo w erze AI",
        topic: "Bezpieczeństwo",
        description: "Webinar dla konsultantów z ćwiczeniami i kluczami odpowiedzi.",
        session_date: "2026-10-07",
        duration_minutes: 180,
        trainer_kind: "consultant",
        chapters: [
          { title: "Jak AI zmienia ataki", start_minute: 0 },
          { title: "Ćwiczenie 1: rozpoznaj atak", start_minute: 35 },
          { title: "Bezpieczne korzystanie z narzędzi AI", start_minute: 60 },
          { title: "Ćwiczenia 2–3", start_minute: 100 },
          { title: "Pytania", start_minute: 150 },
        ],
        files: [
          { id: 31, kind: "recording", file_name: "nagranie.mp4", content_type: "video/mp4", size_bytes: 143_000_000 },
          { id: 32, kind: "deliverable", file_name: "podsumowanie.pdf", content_type: "application/pdf", size_bytes: 640_000 },
          { id: 33, kind: "deliverable", file_name: "cwiczenia-i-klucze.pdf", content_type: "application/pdf", size_bytes: 910_000 },
          { id: 34, kind: "deliverable", file_name: "podcast-czesc-1.mp3", content_type: "audio/mpeg", size_bytes: 24_000_000 },
        ],
      },
      {
        id: 22,
        title: "Scrum w zespole rozproszonym",
        topic: "Scrum",
        description: "",
        session_date: "2026-09-18",
        duration_minutes: 120,
        trainer_kind: "employee",
        chapters: [],
        files: [],
      },
    ],
    live: [
      { id: 2, title: "Bezpieczne prompty w projekcie", topic: "AI", session_date: "2026-12-04", time_from: "16:00", time_to: "18:00", platform: "Microsoft Teams", registered: false, join_url: null },
      { id: 4, title: "Kubernetes od środka", topic: "Kubernetes", session_date: "2026-12-11", time_from: "17:00", time_to: "19:00", platform: "Microsoft Teams", registered: true, join_url: "https://example.com/spotkanie" },
    ],
  },
  applied: true,
  wanted_topics: [
    { id: 51, title: "Terraform i IaC dla zespołów bankowych", description: "2 h na żywo z ćwiczeniami.", audience: "rekruterzy IT", applied: true },
    { id: 52, title: "Testy kontraktowe (Pact) w mikroserwisach", description: "", audience: "", applied: false },
  ],
};

export const PREVIEW_APPLICATION: PortalTrainerApplication = {
  topics: ["Bezpieczeństwo", "AI w pracy"],
  experience: "Szkolenia z bezpieczeństwa dla zespołów IT od 2021.",
  proposal_title: "Cyberbezpieczeństwo w erze AI",
  proposal_hours: "3 h",
  audience: "Wszyscy konsultanci",
  availability: "2 popołudnia w miesiącu",
  materials: "https://example.com/program",
  sample_name: "program.pdf",
  sent_at: "2026-11-10T10:00:00+01:00",
  waiting: { who: "us", label: "Po naszej stronie: Ewa Przykładowa" },
};
