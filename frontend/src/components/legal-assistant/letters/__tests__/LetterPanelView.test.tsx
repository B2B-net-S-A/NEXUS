import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LetterPanelView, type LetterPanelViewProps } from "@/components/legal-assistant/letters/LetterPanelView";
import { LETTER_KINDS, type LetterDraft } from "@/lib/legal-letters";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const DRAFT: LetterDraft = {
  kind: "notice_reply",
  label: "Odpowiedź na wypowiedzenie Partnera",
  source: "model",
  editable: true,
  template: null,
  subject: "potwierdzenie wypowiedzenia umowy nr 41/2025",
  text: "Szanowny Panie,\n\nzgodnie z § 8 ust. 2 umowy …",
  recipient: { kind: "partner", name: "Jan Testowy", lines: [], email: "jan@example.com", candidate_id: 1 },
  facts: [
    { label: "Złożone", value: "12.11.2026", note: null, tone: "plain" },
    { label: "Rozwiązanie", value: "31.12.2026", note: "zgodne z NEXUSEM", tone: "ok" },
  ],
  steps: ["Doręczenie 12 listopada 2026 r.: okres liczy się od kolejnego miesiąca."],
  deadline_note: null,
  warning: {
    level: "question",
    title: "Zanim wyślesz: forma wypowiedzenia",
    message: "Umowa wymaga wypowiedzenia na piśmie.",
    clause_ref: null,
    document_name: "Wypowiedzenie_skan.pdf",
    actions: ["confirm_original", "switch_to_agreement"],
  },
  checks: [
    {
      status: "mismatch",
      reason: "quote_mismatch",
      message: "Cytat nie zgadza się z tekstem.",
      citation: { raw: "§ 8 ust. 2 umowy", ref: "§ 8 ust. 2", kind: "contract", quote: "x" },
      source: null,
    },
  ],
  counts: { ok: 0, missing: 0, mismatch: 1 },
  blocked: true,
  block_reasons: ["1 cytat nie ma pokrycia w źródłach.", "Odpowiedz na pytanie o formę wypowiedzenia."],
  issues: [],
  lawyer_review: ["kara umowna"],
  passages: [],
  notes: [],
  model: "model-testowy",
  error: null,
  task_key: "notice_reply:1:2026-11-12",
  disclaimer: "Szkic asystenta nie jest poradą prawną.",
};

function props(overrides: Partial<LetterPanelViewProps> = {}): LetterPanelViewProps {
  return {
    kinds: LETTER_KINDS,
    kind: "notice_reply",
    onKindChange: vi.fn(),
    draft: DRAFT,
    loading: false,
    error: null,
    text: DRAFT.text,
    onTextChange: vi.fn(),
    instruction: "",
    onInstructionChange: vi.fn(),
    penaltyAmount: "",
    onPenaltyAmountChange: vi.fn(),
    onPrepare: vi.fn(),
    originalConfirmed: false,
    onConfirmOriginal: vi.fn(),
    onSwitchToAgreement: vi.fn(),
    approved: false,
    approvedChecks: null,
    busy: null,
    actionError: null,
    savedName: null,
    canSave: true,
    canMail: true,
    generatorHref: null,
    onApprove: vi.fn(),
    onOpenMail: vi.fn(),
    onSaveDocx: vi.fn(),
    ...overrides,
  };
}

describe("panel pisma", () => {
  it("pytanie o formę z dwiema odpowiedziami, zatwierdzenie zablokowane", () => {
    const p = props();
    render(<LetterPanelView {...p} />);
    expect(screen.getByTestId("letter-form-warning")).toHaveTextContent("Zanim wyślesz");
    fireEvent.click(screen.getByRole("button", { name: "To oryginał / podpis kwalifikowany" }));
    expect(p.onConfirmOriginal).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Zamień na porozumienie" }));
    expect(p.onSwitchToAgreement).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Zatwierdzam/ })).toBeDisabled();
    // Mail i DOCX dopiero po „Zatwierdzam”.
    expect(screen.getByRole("button", { name: /Otwórz w oknie maila/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /DOCX do Dokumentów/ })).toBeDisabled();
    expect(screen.getByTestId("letter-summary")).toHaveTextContent("0 z 1 cytatu sprawdzone · nic nie wysłano");
    expect(screen.getByTestId("letter-lawyer")).toHaveTextContent("do prawnika");
    expect(screen.getByText(/nie zgadza się ze źródłem/)).toBeInTheDocument();
  });

  it("zły cytat blokuje także po odpowiedzi o formie", () => {
    render(<LetterPanelView {...props({ originalConfirmed: true })} />);
    expect(screen.queryByTestId("letter-form-warning")).toBeNull();
    expect(screen.getByRole("button", { name: /Zatwierdzam/ })).toBeDisabled();
    expect(screen.getByTestId("letter-block-reason")).toHaveTextContent("pokrycia");
  });

  it("po zatwierdzeniu otwiera okno maila i zapis DOCX", () => {
    const p = props({ originalConfirmed: true, approved: true });
    render(<LetterPanelView {...p} />);
    fireEvent.click(screen.getByRole("button", { name: /Otwórz w oknie maila/ }));
    fireEvent.click(screen.getByRole("button", { name: /DOCX do Dokumentów/ }));
    expect(p.onOpenMail).toHaveBeenCalled();
    expect(p.onSaveDocx).toHaveBeenCalled();
  });

  it("wzór jest tylko do odczytu i prowadzi do Generatora", () => {
    const template: LetterDraft = {
      ...DRAFT,
      kind: "termination_notice",
      source: "template",
      editable: false,
      warning: null,
      checks: [],
      counts: { ok: 0, missing: 0, mismatch: 0 },
      blocked: false,
      block_reasons: [],
      lawyer_review: [],
      text: "Wypowiedzenie umowy o współpracę B2B",
    };
    render(
      <LetterPanelView
        {...props({ kind: "termination_notice", draft: template, text: template.text, generatorHref: "/contracts/b2b-generator?tab=documents" })}
      />,
    );
    expect(screen.queryByRole("textbox", { name: "Treść pisma" })).toBeNull();
    expect(screen.getByText("Wypowiedzenie umowy o współpracę B2B")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Otwórz w Generatorze" })).toHaveAttribute(
      "href",
      "/contracts/b2b-generator?tab=documents",
    );
    expect(screen.getByRole("button", { name: /Zatwierdzam/ })).toBeEnabled();
  });

  it("błąd szkicu nie wygląda jak pusty szkic", () => {
    render(<LetterPanelView {...props({ draft: null, text: "", error: "Nie udało się przygotować szkicu pisma." })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się przygotować szkicu pisma.");
    expect(screen.getByRole("button", { name: /Zatwierdzam/ })).toBeDisabled();
  });

  it("nota o karze prosi o kwotę i powód przed szkicem", () => {
    const p = props({ kind: "penalty_note", draft: null, text: "" });
    render(<LetterPanelView {...p} />);
    fireEvent.change(screen.getByLabelText("Kwota kary"), { target: { value: "5000" } });
    expect(p.onPenaltyAmountChange).toHaveBeenCalledWith("5000");
    fireEvent.click(screen.getByRole("button", { name: /Przygotuj szkic/ }));
    expect(p.onPrepare).toHaveBeenCalled();
  });
});
