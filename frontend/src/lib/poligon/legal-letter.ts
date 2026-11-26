// Pismo asystenta prawnego na Poligonie (lekcja z 26.11.2026).
//
// Prawdziwy szkic robi serwer (`POST /api/contracts/{id}/legal-letter/draft`):
// termin z podpisanej umowy, ostrzeżenie o formie, cytaty sprawdzone z bazą.
// Na Poligonie to stała odpowiedź w tym samym kształcie — bez modelu i bez
// zapisu. Daty idą z kontraktu ćwiczebnego (`@reld` / `@releom` w zestawie),
// więc „Rozwiązanie” zgadza się z tym, co pokazuje strona kontraktu.
// Wszystkie teksty są wymyślone (repo jest publiczne).

import { hasPartnerNotice, type ApproveResult, type LetterCheck, type LetterDraft } from "@/lib/legal-letters";

type Row = Record<string, unknown>;

export const PRACTICE_LETTER_ONLY_REPLY =
  "Na poligonie asystent przygotowuje tylko odpowiedź na wypowiedzenie Partnera — wybierz ją z listy rodzajów.";
const DISCLAIMER = "Szkic asystenta nie jest poradą prawną. Pismo zatwierdza i wysyła człowiek.";
const FORM_REASON = "Odpowiedz na pytanie o formę wypowiedzenia.";
const CLAUSE = "§ 8 ust. 2";
const FORM_CLAUSE = "§ 8 ust. 5";

/** `2026-11-24` → `24.11.2026`. */
function pl(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

function firstOfNextMonth(iso: string): string {
  const [y, m] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m, 1)).toISOString().slice(0, 10);
}

function checks(contractNumber: string): LetterCheck[] {
  const contractRef = `umowa ${contractNumber} ${CLAUSE}`;
  return [
    {
      status: "ok",
      reason: "",
      message: "",
      citation: { raw: `${CLAUSE} Umowy`, ref: contractRef, kind: "contract", quote: null },
      source: {
        kind: "contract",
        ref: contractRef,
        label: contractRef,
        url: null,
        text: "Każda ze Stron może wypowiedzieć Umowę z zachowaniem jednomiesięcznego okresu wypowiedzenia, liczonego od kolejnego miesiąca kalendarzowego.",
      },
    },
    {
      status: "ok",
      reason: "",
      message: "",
      citation: { raw: "art. 61 § 1 KC", ref: "KC art. 61 § 1", kind: "law", quote: null },
      source: {
        kind: "law",
        ref: "KC art. 61 § 1",
        label: "Kodeks cywilny, art. 61 § 1",
        url: null,
        text: "Oświadczenie woli, które ma być złożone innej osobie, jest złożone z chwilą, gdy doszło do niej w taki sposób, że mogła zapoznać się z jego treścią.",
      },
    },
  ];
}

function onlyReply(kind: string, contract: Row): LetterDraft {
  return {
    kind: kind as LetterDraft["kind"],
    label: "Pismo",
    source: "template",
    editable: false,
    template: null,
    subject: "",
    text: "",
    recipient: {
      kind: "partner",
      name: String(contract.candidate_name ?? ""),
      lines: [String(contract.candidate_name ?? "")],
      email: null,
      candidate_id: null,
    },
    facts: [],
    steps: [],
    deadline_note: null,
    warning: null,
    checks: [],
    counts: { ok: 0, missing: 0, mismatch: 0 },
    blocked: true,
    block_reasons: [PRACTICE_LETTER_ONLY_REPLY],
    issues: [],
    lawyer_review: [],
    passages: [],
    notes: [],
    model: null,
    error: PRACTICE_LETTER_ONLY_REPLY,
    task_key: null,
    disclaimer: DISCLAIMER,
  };
}

/**
 * Szkic na kontrakcie ćwiczebnym z wypowiedzeniem Partnera; `null`, gdy
 * kontrakt go nie ma (wtedy żądanie zostaje zablokowane jak każdy zapis).
 */
export function practiceLetterDraft(contract: Row, body: Row, now: number): LetterDraft | null {
  const facts = {
    contract_type: String(contract.contract_type ?? ""),
    agreement_termination_party: (contract.agreement_termination_party as string | null) ?? null,
    agreement_termination_mode: (contract.agreement_termination_mode as string | null) ?? null,
  };
  const signedOn = contract.agreement_termination_signed_on;
  const lastDay = contract.agreement_last_day;
  if (!hasPartnerNotice(facts) || typeof signedOn !== "string" || typeof lastDay !== "string") return null;
  const kind = String(body.kind ?? "notice_reply");
  if (kind !== "notice_reply") return onlyReply(kind, contract);

  const name = String(contract.candidate_name ?? "Partner");
  const number = String(contract.contract_number ?? "ĆW-B2B-0521");
  // Nagłówek pisma: dzień kalendarza firmy, nie UTC (po północy UTC to jeszcze wczoraj).
  const today = new Intl.DateTimeFormat("pl-PL", { timeZone: "Europe/Warsaw", day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date(now));
  const text = [
    `Warszawa, ${today}`,
    "",
    name,
    "",
    `Dotyczy: umowy o współpracy nr ${number}`,
    "",
    "Szanowny Panie,",
    "",
    `potwierdzamy otrzymanie Pana wypowiedzenia umowy w dniu ${pl(signedOn)}. Zgodnie z ${CLAUSE} Umowy okres wypowiedzenia wynosi 1 miesiąc i jest liczony od kolejnego miesiąca kalendarzowego, dlatego umowa rozwiąże się z dniem ${pl(lastDay)}. Oświadczenie o wypowiedzeniu jest złożone z chwilą, gdy doszło do nas w taki sposób, że mogliśmy zapoznać się z jego treścią (art. 61 § 1 KC).`,
    "",
    "Do dnia rozwiązania umowy prosimy o dalsze świadczenie usług na dotychczasowych zasadach oraz o przekazanie prac zgodnie z ustaleniami z klientem.",
    "",
    "Z poważaniem",
    "(podpis osoby z B2Bnetwork)",
  ].join("\n");
  const cited = checks(number);
  return {
    kind: "notice_reply",
    label: "Odpowiedź na wypowiedzenie Partnera",
    source: "model",
    editable: true,
    template: null,
    subject: `potwierdzenie otrzymania wypowiedzenia umowy nr ${number}`,
    text,
    recipient: {
      kind: "partner",
      name,
      lines: [name],
      email: null,
      candidate_id: typeof contract.candidate_id === "number" ? contract.candidate_id : null,
    },
    facts: [
      { label: "Złożone", value: pl(signedOn), note: null, tone: "plain" },
      { label: "Okres", value: "1 miesiąc, liczony od kolejnego miesiąca", note: `${CLAUSE} umowy ${number}`, tone: "plain" },
      { label: "Rozwiązanie", value: pl(lastDay), note: "zgodne z NEXUSEM", tone: "ok" },
    ],
    steps: [
      `Wypowiedzenie doręczone ${pl(signedOn)}.`,
      `Okres liczony od kolejnego miesiąca: biegnie od ${pl(firstOfNextMonth(signedOn))}.`,
      `1 miesiąc → umowa rozwiązuje się ${pl(lastDay)}.`,
    ],
    deadline_note: null,
    warning: {
      level: "question",
      title: "Zanim wyślesz: forma wypowiedzenia",
      message: `Umowa wymaga wypowiedzenia na piśmie (${FORM_CLAUSE}). W Dokumentach kontraktu nie ma pliku wypowiedzenia. Jeśli Partner przysłał je tylko mailem, wypowiedzenie może być nieskuteczne — bezpieczniej zawrzeć porozumienie o rozwiązaniu z tą samą datą.`,
      clause_ref: FORM_CLAUSE,
      document_name: null,
      actions: ["confirm_original", "switch_to_agreement"],
    },
    checks: cited,
    counts: { ok: cited.length, missing: 0, mismatch: 0 },
    blocked: true,
    block_reasons: [FORM_REASON],
    issues: [],
    lawyer_review: [],
    passages: [],
    notes: ["Na poligonie szkic jest przykładowy: asystent nie pisze go na żywo, a „Zatwierdzam” niczego nie zapisuje."],
    model: null,
    error: null,
    task_key: null,
    disclaimer: DISCLAIMER,
  };
}

/** „Zatwierdzam” na Poligonie: cytaty jak w szkicu, bez zapisu i bez zamknięcia zadania. */
export function practiceLetterApprove(draft: LetterDraft, body: Row): ApproveResult {
  return {
    approved: true,
    task_key: null,
    checks: draft.checks,
    counts: draft.counts,
    text: typeof body.text === "string" ? body.text : draft.text,
  };
}
