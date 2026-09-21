import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { mergeProposals } from "@/lib/proposals-merge";

vi.mock("@/components/talent-radar/RequirementVerificationDialog", () => ({
  RequirementVerificationDialog: ({ candidateName }: { candidateName: string }) => <button type="button">Zweryfikuj wymaganie ({candidateName})</button>,
}));

import { ProposalPanel } from "@/components/v2/recruitment/ProposalPanel";

const veto = { reason_code: "rejected_by_hiring_manager", reason: "Hiring manager odrzucił po rozmowie", assignment_allowed: false, visibility: "warn" as const, severity: "hard", secondary: [] };
const nda = { ...veto, reason_code: "client_nda", reason: "NDA z klientem do 01.10.2026", assignment_allowed: true, severity: "warning" };

function entry(eligibility: typeof veto | null = null, rate: number | null = 170) {
  return mergeProposals({
    inbox: [{
      candidate: { id: 5, name: "Jan", lastname: "Kowalski", title: "Java Developer", city: "Warszawa", availability_status: "actively_looking", availability_date: null, expected_rate_hourly: rate, expected_rate_redacted: rate === null },
      sources: ["full_base"], score: 91,
      evidence: { previously_dismissed: true, requirements: [{ name: "Java", level: "must", status: "met" }, { name: "AWS", level: "must", status: "unknown" }, { name: "Kafka", level: "nice", status: "not_met" }] },
      first_seen_at: null, last_seen_at: null, is_new: true, status: "proposed", eligibility,
    }],
    budgetHourly: 150,
  })[0];
}

function renderPanel(over: Partial<React.ComponentProps<typeof ProposalPanel>> = {}) {
  const handlers = { onAdd: vi.fn(), onShortlist: vi.fn(), onDismiss: vi.fn(), onWriteEmail: vi.fn(), onVerified: vi.fn() };
  render(<ProposalPanel jobId={42} entry={entry()} budgetHourly={150} canVerify {...handlers} {...over} />);
  return handlers;
}

describe("ProposalPanel", () => {
  it("akcje po nazwie dostępnej wołają rodzica z id kandydata", () => {
    const h = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do rekrutacji" }));
    fireEvent.click(screen.getByRole("button", { name: "Do shortlisty" }));
    fireEvent.click(screen.getByRole("button", { name: "Pomiń" }));
    fireEvent.click(screen.getByRole("button", { name: "Napisz" }));
    expect(h.onAdd).toHaveBeenCalledWith(5);
    expect(h.onShortlist).toHaveBeenCalledWith(5);
    expect(h.onDismiss).toHaveBeenCalledWith(5);
    expect(h.onWriteEmail).toHaveBeenCalledWith(5);
    expect(screen.getByRole("link", { name: "Pełny profil" })).toHaveAttribute("href", "/candidates/5?from=job&jobId=42");
  });

  it("pokazuje powód, wymagania ze statusami, stawkę wobec budżetu i powrót po pominięciu", () => {
    renderPanel();
    expect(screen.getByText("Spełnia: Java")).toBeInTheDocument();
    expect(screen.getByText(/170 zł\/h \/ budżet 150,00 PLN\/h — ponad budżet/)).toBeInTheDocument();
    expect(screen.getByText(/Wcześniej pominięta/)).toBeInTheDocument();
    expect(screen.getByText("Dopasowanie: 91")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Zweryfikuj wymaganie/ })).toBeInTheDocument();
    expect(screen.getByText("AWS").parentElement).toHaveTextContent("brak potwierdzenia");
  });

  it("konflikt z klientem ostrzega i NIE blokuje; weto HM blokuje dodanie", () => {
    const { unmount } = render(<ProposalPanel jobId={42} entry={entry(nda)} budgetHourly={150} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("NDA z klientem do 01.10.2026")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dodaj do rekrutacji" })).toBeEnabled();
    unmount();
    render(<ProposalPanel jobId={42} entry={entry(veto)} budgetHourly={150} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Hiring manager odrzucił po rozmowie");
    expect(screen.getByRole("button", { name: "Dodaj do rekrutacji" })).toBeDisabled();
  });

  it("zredagowana stawka mówi ukryta, a rola bez prawa dodawania nie widzi akcji zapisu", () => {
    render(<ProposalPanel jobId={42} entry={entry(null, null)} budgetHourly={150} canAdd={false} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText(/Stawka ukryta/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj do rekrutacji" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Pomiń" })).toBeNull();
  });

  it("niesie to, co dawny dok AI Matching: podsumowanie AI i linię „Bramka must-have: brak …”", () => {
    const base = entry();
    const withRun = {
      ...base,
      detail: { ...base.detail, aiSummary: "Senior Java, 8 lat w bankowości.", missingMustGate: ["AWS", "Kafka"] },
    };
    const { unmount } = render(<ProposalPanel jobId={42} entry={withRun} budgetHourly={150} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText("Podsumowanie")).toBeInTheDocument();
    expect(screen.getByText("Senior Java, 8 lat w bankowości.")).toBeInTheDocument();
    expect(screen.getByText("Bramka must-have: brak AWS, Kafka")).toBeInTheDocument();
    unmount();
    // Bez danych z przeglądu nie ma ani pustego nagłówka, ani pustej bramki.
    render(<ProposalPanel jobId={42} entry={base} budgetHourly={150} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.queryByText("Podsumowanie")).toBeNull();
    expect(screen.queryByText(/Bramka must-have/)).toBeNull();
  });

  it("bez aktywnej osoby pokazuje podpowiedź", () => {
    render(<ProposalPanel jobId={42} entry={null} budgetHourly={null} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText(/Wybierz osobę z listy/)).toBeInTheDocument();
  });
});
