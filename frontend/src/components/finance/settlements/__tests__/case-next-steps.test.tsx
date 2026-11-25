import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseStep, SettlementCase, SettlementCaseRow } from "@/lib/api/settlement-cases";

import { CaseNextSteps } from "../CaseNextSteps";
import { CasesView } from "../CasesView";
import { nowText, overdueText, stepWhen } from "../case-format";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  confirm: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, put: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.success, showError: mocks.error }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.confirm, askReason: vi.fn(), confirmDialog: null }),
}));

const step = (key: CaseStep["key"], due: string, state: CaseStep["state"], extra: Partial<CaseStep> = {}): CaseStep => ({
  key,
  label: { mail: "Mail", reminder: "Przypomnienie", call: "Telefon", escalation: "Eskalacja do DL/KAM", decision: "Decyzja Finansów" }[key],
  due,
  state,
  done_on: null,
  done_by: null,
  note: null,
  ...extra,
});

const consultantCase = (extra: Partial<SettlementCase> = {}): SettlementCase => ({
  key: "11:consultant",
  settlement_id: 11,
  contract_id: 21,
  client_id: 31,
  client_name: "Bank Przykładowy",
  person: "Anna Przykładowa",
  month: "2026-10",
  status: "warnings",
  actor: "consultant",
  actor_label: "Konsultant",
  reasons: [{ code: "proof.signed_pdf", title: "PDF z RCP bez podpisu elektronicznego", detail: null }],
  recipient: {
    kind: "consultant",
    label: "Konsultant",
    name: "Anna Przykładowa",
    address: "anna@example.com",
    cc: "opiekun@example.com",
    why: null,
    why_text: null,
  },
  day0: "2026-11-02",
  current: step("mail", "2026-11-02", "overdue"),
  overdue_days: 16,
  dl_card: null,
  steps: [
    step("mail", "2026-11-02", "overdue"),
    step("reminder", "2026-11-30", "planned"),
    step("call", "2026-12-02", "planned"),
    step("escalation", "2026-12-04", "planned"),
  ],
  mail: {
    to: "anna@example.com",
    cc: "opiekun@example.com",
    subject: "Rozliczenie za październik 2026: pdf z rcp bez podpisu elektronicznego",
    text: "Dzień dobry,\n\nw rozliczeniu za październik 2026 jest jedna rzecz do poprawy.",
  },
  mail_step: "mail",
  escalation: {
    to: { kind: "owner", label: "Opiekun kontraktu", name: "Opiekun Testowy", address: "opiekun@example.com", cc: null, why: null, why_text: null },
    mail: { to: "opiekun@example.com", cc: null, subject: "Eskalacja: rozliczenie za październik 2026", text: "Treść eskalacji" },
  },
  phones: [{ who: "Konsultant", name: "Anna Przykładowa", number: "+48 600 000 001", source: "z kontraktu" }],
  script: ["Dzień dobry, dzwonię z zespołu rozliczeń.", "Do poprawy: PDF z RCP bez podpisu elektronicznego."],
  log: [],
  ...extra,
});

function renderWith(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.success.mockReset();
  mocks.error.mockReset();
  mocks.confirm.mockReset();
});

describe("case-format", () => {
  it("mówi o zaległości w dniach roboczych z polską odmianą", () => {
    expect(overdueText(1)).toBe("zaległe 1 dzień rob.");
    expect(overdueText(3)).toBe("zaległe 3 dni rob.");
    expect(stepWhen(step("mail", "2026-11-02", "overdue"), 16)).toBe("od 02.11, zaległe 16 dni rob.");
    expect(stepWhen(step("mail", "2026-11-02", "overdue"), 16, true)).toBe("02.11 · zaległe");
  });

  it("krok zrobiony pokazuje datę, osobę i notatkę", () => {
    const done = step("call", "2026-12-02", "done", { done_on: "2026-11-25", done_by: "Back office", note: "nie odebrał(a)" });
    expect(stepWhen(done, 0)).toBe("25.11 · Back office · nie odebrał(a)");
    expect(nowText(step("reminder", "2026-11-30", "upcoming"), 0)).toBe("Przypomnienie: 30.11");
    expect(nowText(null, 0)).toBe("Wszystkie kroki zrobione: czekamy na poprawkę");
  });
});

describe("CaseNextSteps", () => {
  it("pokazuje kto działa, zaległy krok, mail, numer i skrypt", async () => {
    mocks.get.mockResolvedValue({ data: { cases: [consultantCase()] } });
    renderWith(<CaseNextSteps contractId={21} month="2026-10" canWrite version="v1" />);
    expect(await screen.findByText("Kto działa: Konsultant")).toBeInTheDocument();
    expect(screen.getByText("Teraz: Mail: od 02.11, zaległe 16 dni rob.")).toBeInTheDocument();
    expect(screen.getByText("PDF z RCP bez podpisu elektronicznego")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+48 600 000 001" })).toHaveAttribute("href", "tel:+48600000001");
    expect(screen.getByText("Dzień dobry, dzwonię z zespołu rozliczeń.")).toBeInTheDocument();
    const strip = screen.getByRole("list", { name: "Terminy" });
    expect(within(strip).getAllByRole("listitem").map((li) => li.getAttribute("data-state"))).toEqual([
      "overdue",
      "planned",
      "planned",
      "planned",
    ]);
    expect(mocks.get).toHaveBeenCalledWith("/api/finance/settlements/cases/contract/21", { params: { month: "2026-10" } });
  });

  it("brak numeru i brak adresata mówią to wprost", async () => {
    mocks.get.mockResolvedValue({
      data: {
        cases: [
          consultantCase({
            phones: [{ who: "Konsultant", name: "Anna Przykładowa", number: null, source: null }],
            mail: null,
            recipient: { kind: "none", label: "Brak adresata", name: null, address: null, cc: null, why: "no_recipient", why_text: "Brak adresata: nie ma adresu konsultanta ani opiekuna." },
          }),
        ],
      },
    });
    renderWith(<CaseNextSteps contractId={21} month="2026-10" canWrite version="v1" />);
    expect(await screen.findByText("brak numeru")).toBeInTheDocument();
    expect(screen.getByText("Brak adresata: nie ma adresu konsultanta ani opiekuna.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wyślij mail" })).not.toBeInTheDocument();
  });

  it("„Wyślij” najpierw pyta, a bez zgody nic nie wysyła", async () => {
    mocks.get.mockResolvedValue({ data: { cases: [consultantCase()] } });
    mocks.confirm.mockResolvedValue(false);
    renderWith(<CaseNextSteps contractId={21} month="2026-10" canWrite version="v1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Wyślij mail" }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    expect(mocks.confirm.mock.calls[0][0].title).toBe("Wysłać mail do anna@example.com?");
    expect(mocks.confirm.mock.calls[0][0].description).toContain("W kopii: opiekun@example.com.");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("po zgodzie wysyła aktora i odświeża sprawę z odpowiedzi", async () => {
    mocks.get.mockResolvedValue({ data: { cases: [consultantCase()] } });
    mocks.confirm.mockResolvedValue(true);
    const after = consultantCase({
      current: step("reminder", "2026-11-30", "upcoming"),
      mail_step: "reminder",
      steps: [
        step("mail", "2026-11-02", "done", { done_on: "2026-11-25", done_by: "Back office" }),
        step("reminder", "2026-11-30", "upcoming"),
        step("call", "2026-12-02", "planned"),
        step("escalation", "2026-12-04", "planned"),
      ],
    });
    mocks.post.mockResolvedValue({ data: { outcome: "sent", cases: [after] } });
    renderWith(<CaseNextSteps contractId={21} month="2026-10" canWrite version="v1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Wyślij mail" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/cases/11/send", { actor: "consultant", escalation: false }));
    expect(await screen.findByRole("button", { name: "Wyślij przypomnienie" })).toBeInTheDocument();
    expect(mocks.success).toHaveBeenCalledWith("Mail wysłany.");
  });

  it("odmowa serwera wraca jako błąd z komunikatem", async () => {
    mocks.get.mockResolvedValue({ data: { cases: [consultantCase()] } });
    mocks.confirm.mockResolvedValue(true);
    mocks.post.mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: "Ten mail poszedł już dziś." } } });
    renderWith(<CaseNextSteps contractId={21} month="2026-10" canWrite version="v1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Wyślij mail" }));
    await waitFor(() => expect(mocks.error).toHaveBeenCalled());
    expect(mocks.error.mock.calls[0][0]).toContain("Ten mail poszedł już dziś.");
  });

  it("„Zadzwoniłem” zapisuje wynik i notatkę", async () => {
    mocks.get.mockResolvedValue({ data: { cases: [consultantCase()] } });
    mocks.post.mockResolvedValue({ data: { cases: [consultantCase()] } });
    renderWith(<CaseNextSteps contractId={21} month="2026-10" canWrite version="v1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Zadzwoniłem" }));
    fireEvent.click(screen.getByRole("radio", { name: "Nie odebrał(a)" }));
    fireEvent.change(screen.getByLabelText("Notatka z rozmowy"), { target: { value: "  oddzwoni jutro " } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz telefon" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/cases/11/call", {
        actor: "consultant",
        result: "no_answer",
        note: "oddzwoni jutro",
      }),
    );
  });

  it("bez prawa zapisu nie ma przycisków wysyłki ani telefonu", async () => {
    mocks.get.mockResolvedValue({ data: { cases: [consultantCase()] } });
    renderWith(<CaseNextSteps contractId={21} month="2026-10" canWrite={false} version="v1" />);
    expect(await screen.findByText("Kto działa: Konsultant")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wyślij mail" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zadzwoniłem" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wyślij eskalację" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Kopiuj/ })).toBeInTheDocument();
  });

  it("sprawa Finansów bez maila i telefonu", async () => {
    mocks.get.mockResolvedValue({
      data: {
        cases: [
          consultantCase({
            key: "11:finance",
            actor: "finance",
            actor_label: "Finanse",
            reasons: [{ code: "finance.check", title: "MD ponad dni robocze miesiąca", detail: null }],
            recipient: null,
            mail: null,
            phones: [],
            script: [],
            steps: [step("decision", "2026-11-05", "overdue")],
            current: step("decision", "2026-11-05", "overdue"),
          }),
        ],
      },
    });
    renderWith(<CaseNextSteps contractId={21} month="2026-10" canWrite version="v1" />);
    expect(await screen.findByText(/Finanse rozstrzygają na tej karcie/)).toBeInTheDocument();
    expect(screen.queryByText("Telefon")).not.toBeInTheDocument();
  });

  it("bez spraw nie rysuje sekcji, a awaria nie wygląda jak brak spraw", async () => {
    mocks.get.mockResolvedValueOnce({ data: { cases: [] } });
    const { container } = renderWith(<CaseNextSteps contractId={21} month="2026-10" canWrite version="v1" />);
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container.querySelector("section")).toBeNull();

    mocks.get.mockRejectedValueOnce({ isAxiosError: true, response: { status: 500, data: {} } });
    renderWith(<CaseNextSteps contractId={22} month="2026-10" canWrite version="v1" />);
    expect(await screen.findByText(/Nie udało się pobrać „Co dalej”/)).toBeInTheDocument();
  });
});

const row = (extra: Partial<SettlementCaseRow>): SettlementCaseRow => {
  const { steps: _steps, mail: _mail, mail_step: _ms, escalation: _e, phones: _p, script: _s, log: _l, ...base } = consultantCase();
  return { ...base, ...extra };
};

describe("CasesView", () => {
  const month = {
    month: "2026-10",
    today: "2026-11-25",
    counts: { all: 3, consultant: 1, client: 0, dl: 1, finance: 1, overdue: 2 },
    clients: [
      { client_id: 31, name: "Bank Przykładowy", count: 2 },
      { client_id: 32, name: "Ubezpieczyciel Przykładowy", count: 1 },
    ],
    cases: [
      row({}),
      row({
        key: "12:dl",
        settlement_id: 12,
        contract_id: 22,
        person: "Jan Próbny",
        actor: "dl",
        actor_label: "Delivery Lead",
        reasons: [{ code: "order.md_over", title: "2 MD ponad pulę zamówienia PO-1", detail: null }],
        recipient: { kind: "owner", label: "Delivery Lead klienta", name: "Lider Testowy", address: "dl@example.com", cc: null, why: null, why_text: null },
      }),
      row({
        key: "13:finance",
        settlement_id: 13,
        contract_id: 23,
        client_id: 32,
        client_name: "Ubezpieczyciel Przykładowy",
        person: "Ewa Nowa",
        actor: "finance",
        actor_label: "Finanse",
        recipient: null,
        current: step("decision", "2026-11-28", "upcoming"),
        overdue_days: 0,
      }),
    ],
  };

  it("filtruje po kto działa, kliencie i zaległych, a wiersz otwiera kartę", async () => {
    mocks.get.mockResolvedValue({ data: month });
    const onOpen = vi.fn();
    renderWith(<CasesView month="2026-10" onOpen={onOpen} />);
    expect(await screen.findByRole("button", { name: "Anna Przykładowa" })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(4);

    fireEvent.click(screen.getByRole("button", { name: /Delivery Lead 1/ }));
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(screen.getByText("Lider Testowy")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Wszyscy 3/ }));
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.queryByText("Ewa Nowa")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(screen.getByLabelText("Klient spraw"), { target: { value: "32" } });
    expect(screen.getAllByRole("row")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Ewa Nowa" }));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ contract_id: 23, client_id: 32, month: "2026-10" }));
    expect(mocks.get).toHaveBeenCalledWith("/api/finance/settlements/cases", { params: { month: "2026-10" } });
  });

  it("pusty miesiąc dopiero po udanym odczycie, awaria osobno", async () => {
    mocks.get.mockResolvedValueOnce({
      data: { ...month, counts: { all: 0, consultant: 0, client: 0, dl: 0, finance: 0, overdue: 0 }, clients: [], cases: [] },
    });
    renderWith(<CasesView month="2026-10" onOpen={vi.fn()} />);
    expect(await screen.findByText(/nie ma spraw/)).toBeInTheDocument();

    mocks.get.mockRejectedValueOnce({ isAxiosError: true, response: { status: 500, data: {} } });
    renderWith(<CasesView month="2026-09" onOpen={vi.fn()} />);
    expect(await screen.findByText("Nie udało się pobrać spraw rozliczeń.")).toBeInTheDocument();
  });
});
