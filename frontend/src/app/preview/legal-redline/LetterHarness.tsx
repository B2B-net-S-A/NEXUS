"use client";

/**
 * Harness panelu pisma na kontrakcie (asystent prawny, część F) — widok
 * `/preview/legal-redline?widok=pismo`. Osobnej strony nie ma, bo liczba
 * harnessów może tylko maleć (`src/__tests__/preview-harness-limit.test.ts`).
 *
 * ZERO zapytań: `LetterPanelView` i `LegalTasksList` z lokalnym stanem.
 * „Zatwierdzam” tylko przestawia stan; mail i DOCX pokazują, co by poszło.
 * Dane są fikcyjne.
 */

import { useState } from "react";

import { LegalTasksList } from "@/components/legal-assistant/letters/LegalTasksStrip";
import { LetterPanelView } from "@/components/legal-assistant/letters/LetterPanelView";
import {
  LETTER_KINDS,
  type LegalTask,
  type LetterCheck,
  type LetterDraft,
  type LetterKindKey,
} from "@/lib/legal-letters";

const TASKS: LegalTask[] = [
  {
    key: "notice_reply:900:2026-11-12",
    kind: "notice_reply",
    severity: "info",
    title: "Jan Testowy: szkic odpowiedzi na wypowiedzenie czeka",
    detail: "Wypowiedzenie Partnera z 12.11.2026 · ostatni dzień umowy 31.12.2026 · Bank Przykładowy",
    action_label: "Otwórz szkic",
    href: "/preview/legal-redline?widok=pismo",
    client_id: 1,
    contract_id: 900,
    created_at: "2026-11-12T12:00:00",
  },
];

const check = (raw: string, status: LetterCheck["status"], message: string, label: string | null): LetterCheck => ({
  status,
  reason: status,
  message,
  citation: { raw, ref: raw, kind: raw.startsWith("art.") ? "law" : "contract", quote: null },
  source: label ? { kind: "contract", ref: raw, label, url: null, text: "" } : null,
});

const REPLY_TEXT = `Warszawa, 25 listopada 2026 r.

Jan Testowy
Przykładowe IT Jan Testowy
ul. Fikcyjna 1, 00-001 Warszawa

Dotyczy: Potwierdzenie wypowiedzenia umowy o współpracy B2B nr 41/2025 z dnia 03.03.2025 r.

Szanowny Panie,

potwierdzamy otrzymanie 12 listopada 2026 r. Pana oświadczenia o wypowiedzeniu umowy (art. 61 § 1 KC). Zgodnie z § 8 ust. 2 umowy okres wypowiedzenia wynosi 1 miesiąc, liczony od kolejnego miesiąca, dlatego umowa rozwiąże się z dniem 31 grudnia 2026 r. Do tego dnia prosimy o świadczenie usług na dotychczasowych zasadach oraz o zwrot powierzonego sprzętu.

Dziękujemy za współpracę.

Z poważaniem
B2B.net S.A.
`;

const NOTICE_TEXT = `Warszawa, 25.11.2026 r.

Wypowiedzenie umowy o współpracę B2B

Niniejszym wypowiadam umowę o współpracy B2B o numerze 41/2025 zawartą w dniu 03.03.2025 r. w Warszawie pomiędzy:

(…)

B2B.net S.A., działając zgodnie z § 8 ust. 2 umowy o współpracy B2B nr 41/2025 z dnia 03.03.2025 r., wypowiada niniejszą umowę z zachowaniem okresu wypowiedzenia 1 (jednego) miesiąca liczonego od kolejnego miesiąca. Wypowiedzenie zostaje doręczone Partnerowi w dniu 25.11.2026 r., a umowa ulega rozwiązaniu z dniem 31.12.2026 r.
`;

const BASE = {
  recipient: {
    kind: "partner" as const,
    name: "Jan Testowy",
    lines: ["Przykładowe IT Jan Testowy", "ul. Fikcyjna 1, 00-001 Warszawa"],
    email: "jan.testowy@example.com",
    candidate_id: 1,
  },
  issues: [],
  passages: [],
  notes: [],
  error: null,
  disclaimer: "Szkic asystenta nie jest poradą prawną. Pismo zatwierdza i wysyła człowiek.",
};

const DRAFTS: Partial<Record<LetterKindKey, LetterDraft>> = {
  notice_reply: {
    ...BASE,
    kind: "notice_reply",
    label: "Odpowiedź na wypowiedzenie Partnera",
    source: "model",
    editable: true,
    template: null,
    subject: "potwierdzenie wypowiedzenia umowy o współpracy B2B nr 41/2025 z dnia 03.03.2025 r.",
    text: REPLY_TEXT,
    facts: [
      { label: "Złożone", value: "12.11.2026", note: null, tone: "plain" },
      { label: "Okres", value: "1 miesiąc, liczony od kolejnego miesiąca", note: "umowa 41/2025 § 8 ust. 2", tone: "plain" },
      { label: "Rozwiązanie", value: "31.12.2026", note: "zgodne z NEXUSEM", tone: "ok" },
    ],
    steps: [
      "Doręczenie 12 listopada 2026 r.: okres liczy się od kolejnego miesiąca, czyli od 1 grudnia 2026 r.",
      "1 miesiąc od 1 grudnia 2026 r. upływa 31 grudnia 2026 r.",
    ],
    deadline_note: null,
    warning: {
      level: "question",
      title: "Zanim wyślesz: forma wypowiedzenia",
      message:
        "Umowa wymaga wypowiedzenia na piśmie, pod rygorem nieważności, doręczonego osobiście albo pocztą (umowa 41/2025 § 8 ust. 5). W Dokumentach jest plik „Wypowiedzenie_skan.pdf” z 12.11.2026. Jeśli to skan albo mail, a nie oryginał ani dokument z kwalifikowanym podpisem elektronicznym, wypowiedzenie może być nieskuteczne — bezpieczniej zawrzeć porozumienie o rozwiązaniu z tą samą datą.",
      clause_ref: "umowa 41/2025 § 8 ust. 5",
      document_name: "Wypowiedzenie_skan.pdf",
      actions: ["confirm_original", "switch_to_agreement"],
    },
    checks: [
      check("art. 61 § 1 KC", "ok", "Zgodne ze źródłem.", "Kodeks cywilny"),
      check("§ 8 ust. 2 umowy", "ok", "Zgodne ze źródłem.", "umowa_41_2025.pdf"),
    ],
    counts: { ok: 2, missing: 0, mismatch: 0 },
    blocked: true,
    block_reasons: ["Odpowiedz na pytanie o formę wypowiedzenia."],
    lawyer_review: [],
    model: "model-testowy",
    task_key: "notice_reply:900:2026-11-12",
  },
  termination_notice: {
    ...BASE,
    kind: "termination_notice",
    label: "Wypowiedzenie umowy przez B2B.net",
    source: "template",
    editable: false,
    template: "termination_notice",
    subject: "wypowiedzenie umowy o współpracy B2B nr 41/2025 z dnia 03.03.2025 r.",
    text: NOTICE_TEXT,
    facts: [
      { label: "Złożone", value: "25.11.2026", note: null, tone: "plain" },
      { label: "Okres", value: "1 miesiąc, liczony od kolejnego miesiąca", note: "umowa 41/2025 § 8 ust. 2", tone: "plain" },
      { label: "Rozwiązanie", value: "31.12.2026", note: null, tone: "plain" },
    ],
    steps: [],
    deadline_note: null,
    warning: {
      level: "info",
      title: "Forma wypowiedzenia",
      message:
        "Umowa wymaga wypowiedzenia na piśmie, pod rygorem nieważności, doręczonego osobiście albo pocztą. Mail z plikiem nie wystarczy: wyślij podpisany oryginał albo dokument z kwalifikowanym podpisem elektronicznym.",
      clause_ref: null,
      document_name: null,
      actions: [],
    },
    checks: [check("§ 8 ust. 2 umowy", "mismatch", "Cytat nie zgadza się z tekstem umowa 41/2025 § 8 ust. 2.", null)],
    counts: { ok: 0, missing: 0, mismatch: 1 },
    blocked: true,
    block_reasons: ["1 cytat nie ma pokrycia w źródłach."],
    lawyer_review: [],
    model: null,
    task_key: null,
  },
};

export function LetterHarness() {
  const [kind, setKind] = useState<LetterKindKey>("notice_reply");
  const draft = DRAFTS[kind] ?? null;
  const [text, setText] = useState(draft?.text ?? "");
  const [originalConfirmed, setOriginalConfirmed] = useState(false);
  const [approved, setApproved] = useState(false);
  const [shown, setShown] = useState<string | null>(null);

  const pick = (next: LetterKindKey) => {
    setKind(next);
    setText(DRAFTS[next]?.text ?? "");
    setApproved(false);
    setOriginalConfirmed(false);
    setShown(null);
  };

  return (
    <div className="space-y-3">
      <LegalTasksList tasks={TASKS} onAction={() => pick("notice_reply")} onDismiss={() => setShown("Pomiń: zadanie zniknęłoby z paska.")} />
      <div className="ml-auto h-[calc(100dvh-10rem)] max-w-[640px] overflow-hidden rounded-xl border border-border bg-card shadow-md">
        <LetterPanelView
          kinds={LETTER_KINDS.filter((k) => k.key !== "notice_withdrawal")}
          kind={kind}
          onKindChange={pick}
          draft={draft}
          loading={false}
          error={draft ? null : "W harnessie ten rodzaj nie ma przykładu — wybierz odpowiedź albo wypowiedzenie."}
          text={text}
          onTextChange={setText}
          instruction=""
          onInstructionChange={() => undefined}
          penaltyAmount=""
          onPenaltyAmountChange={() => undefined}
          onPrepare={() => undefined}
          originalConfirmed={originalConfirmed}
          onConfirmOriginal={() => setOriginalConfirmed(true)}
          onSwitchToAgreement={() => pick("termination_notice")}
          approved={approved}
          approvedChecks={null}
          busy={null}
          actionError={shown}
          savedName={null}
          canSave
          canMail
          generatorHref="/preview/legal-redline?widok=pismo"
          onApprove={() => setApproved(true)}
          onOpenMail={() => setShown(`Okno maila: „${draft?.subject ?? ""}” do ${draft?.recipient.email ?? "—"}`)}
          onSaveDocx={() => setShown("DOCX poszedłby do Dokumentów kontraktu, folder „Pisma asystenta”.")}
        />
      </div>
    </div>
  );
}
