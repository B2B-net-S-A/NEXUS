/**
 * Dane fikcyjne harnessu „Zgodność z umową ramową klienta” (asystent prawny,
 * część G). Klient, umowy i klauzule są wymyślone — żadnego cytatu
 * z prawdziwej umowy klienta.
 */

import type {
  ClientFitFinding,
  ClientFitResponse,
} from "@/lib/api/legalClientFit";

const CLIENT = "Bank Przykładowy S.A.";
const DISCLAIMER =
  "Asystent nie jest poradą prawną. Kara umowna, spór z klientem i rozwiązanie ze skutkiem natychmiastowym — do prawnika.";

const FINDINGS: ClientFitFinding[] = [
  {
    id: 1,
    topic: "ict_training",
    topic_label: "Szkolenia ICT ludzi podwykonawcy",
    state: "gap",
    summary: "Bank wymaga szkoleń z bezpieczeństwa ICT od każdej osoby dostawcy; nasza umowa tego nie przenosi.",
    client_quote:
      "Dostawca zapewni, że każda osoba świadcząca usługi ukończy coroczne szkolenie z bezpieczeństwa teleinformatycznego wskazane przez Bank.",
    client_ref: "Aneks nr 2 (DORA) § 4 ust. 1",
    client_source: { kind: "amendment", id: 12, name: "Aneks nr 2 (DORA)" },
    our_quote: null,
    our_ref: null,
    next_step: "Dopisz obowiązek w aneksie do umów B2B u klienta",
    annex_text:
      "Partner zobowiązuje się ukończyć coroczne szkolenie z bezpieczeństwa teleinformatycznego wskazane przez Klienta B2BNET i przekazać B2BNET potwierdzenie jego ukończenia.",
    lawyer_review: [],
    affected_contracts: 14,
    clause_draft: null,
  },
  {
    id: 2,
    topic: "incident_reporting",
    topic_label: "Zgłaszanie incydentów",
    state: "gap",
    summary: "Bank wymaga zgłoszenia incydentu w 4 godziny; u nas jest tylko „bez zbędnej zwłoki”.",
    client_quote:
      "Dostawca zgłosi Bankowi każdy incydent związany z ICT nie później niż w ciągu 4 godzin od jego wykrycia.",
    client_ref: "Aneks nr 2 (DORA) § 5 ust. 2",
    client_source: { kind: "amendment", id: 12, name: "Aneks nr 2 (DORA)" },
    our_quote: "Partner informuje B2BNET o przeszkodach w świadczeniu Usług bez zbędnej zwłoki.",
    our_ref: "§ 9 ust. 3",
    next_step: "Dopisz termin zgłoszenia w aneksie",
    annex_text:
      "Partner zgłasza B2BNET każdy incydent związany z ICT dotyczący usług dla Klienta B2BNET nie później niż w ciągu 4 godzin od jego wykrycia.",
    lawyer_review: [],
    affected_contracts: 14,
    clause_draft: { requested_at: "2026-11-25T10:12:00+01:00", requested_by_name: "Anna Przykładowa" },
  },
  {
    id: 3,
    topic: "copyright",
    topic_label: "Prawa autorskie",
    state: "decide",
    summary: "Bank chce przeniesienia praw na dodatkowych polach eksploatacji; trzeba zdecydować, czy aneks ich dotyczy.",
    client_quote:
      "Dostawca przeniesie na Bank autorskie prawa majątkowe do utworów na polach eksploatacji wskazanych w Załączniku nr 5, w tym prawo do wprowadzania zmian.",
    client_ref: "Umowa ramowa § 14 ust. 2",
    client_source: { kind: "framework_contract", id: 7, name: "Umowa ramowa 2025–2028" },
    our_quote: "Z chwilą przekazania utworu Partner przenosi na B2BNET autorskie prawa majątkowe do utworu.",
    our_ref: "§ 5 ust. 1",
    next_step: "Zdecyduj z Delivery, czy przenosić pola eksploatacji z Załącznika nr 5",
    annex_text: null,
    lawyer_review: ["kara umowna"],
    affected_contracts: 14,
    clause_draft: null,
  },
  {
    id: 4,
    topic: "consultant_replacement",
    topic_label: "Wymiana konsultanta z uprzedzeniem",
    state: "ok",
    summary: "Nasz okres wypowiedzenia jest nie krótszy niż uprzedzenie wymagane przez Bank.",
    client_quote: "Dostawca uprzedzi Bank o zmianie osoby świadczącej usługi z co najmniej miesięcznym wyprzedzeniem.",
    client_ref: "Umowa ramowa § 8 ust. 4",
    client_source: { kind: "framework_contract", id: 7, name: "Umowa ramowa 2025–2028" },
    our_quote: "Każda ze Stron może wypowiedzieć Umowę z zachowaniem miesięcznego okresu wypowiedzenia ze skutkiem na koniec miesiąca kalendarzowego.",
    our_ref: "§ 12 ust. 1",
    next_step: null,
    annex_text: null,
    lawyer_review: [],
    affected_contracts: 0,
    clause_draft: null,
  },
  {
    id: 5,
    topic: "personal_data",
    topic_label: "Dane osobowe i dalsze powierzenie",
    state: "ok",
    summary: "Dalsze powierzenie danych wymaga zgody — tak samo u nas.",
    client_quote: "Dalsze powierzenie danych osobowych wymaga uprzedniej pisemnej zgody Banku.",
    client_ref: "Umowa ramowa § 16 ust. 3",
    client_source: { kind: "framework_contract", id: 7, name: "Umowa ramowa 2025–2028" },
    our_quote: "Partner nie powierza dalej przetwarzania danych bez uprzedniej zgody B2BNET.",
    our_ref: "Załącznik nr 2 § 4",
    next_step: null,
    annex_text: null,
    lawyer_review: [],
    affected_contracts: 0,
    clause_draft: null,
  },
];

const BASE: ClientFitResponse = {
  client_id: 9001,
  client_name: CLIENT,
  status: "done",
  status_message: null,
  checked_at: "2026-11-25T09:40:00+01:00",
  stale: false,
  sources: [
    { kind: "framework_contract", id: 7, name: "Umowa ramowa 2025–2028", readable: true, note: null },
    { kind: "amendment", id: 12, name: "Aneks nr 2 (DORA)", readable: true, note: null },
  ],
  template_label: "Wzór B2B (PL)",
  active_b2b_contracts: 14,
  counts: { gap: 2, decide: 1, ok: 2 },
  findings: FINDINGS,
  can_request_clause_draft: true,
  disclaimer: DISCLAIMER,
};

export interface ClientFitScenario {
  label: string;
  data: ClientFitResponse;
}

export const CLIENT_FIT_SCENARIOS: ClientFitScenario[] = [
  { label: "Sprawdzone — luki, do decyzji i zgodne", data: BASE },
  {
    label: "Umowa klienta zmieniła się od sprawdzenia",
    data: { ...BASE, client_id: 9002, stale: true },
  },
  {
    label: "Sprawdzanie w tle",
    data: {
      ...BASE,
      client_id: 9003,
      status: "running",
      checked_at: null,
      findings: [],
      counts: { gap: 0, decide: 0, ok: 0 },
    },
  },
  {
    label: "Bez modelu — sprawdzenie niedostępne",
    data: {
      ...BASE,
      client_id: 9004,
      status: "unavailable",
      status_message: "Funkcja AI „Zgodność umów z umową ramową klienta” jest wyłączona albo brak klucza dostawcy.",
      checked_at: null,
      findings: [],
      counts: { gap: 0, decide: 0, ok: 0 },
    },
  },
  {
    label: "Klient bez umowy ramowej z treścią",
    data: {
      ...BASE,
      client_id: 9005,
      client_name: "Firma Testowa sp. z o.o.",
      status: "no_contract",
      status_message: null,
      sources: [],
      checked_at: null,
      findings: [],
      counts: { gap: 0, decide: 0, ok: 0 },
    },
  },
];
