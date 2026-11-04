import { fireEvent, render, screen, within } from "@testing-library/react";
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
    expect(screen.getByText(/170 zł\/h \/ budżet 150,00 PLN\/h — oczekuje \+13% ponad budżet/)).toBeInTheDocument();
    expect(screen.getByText(/Wcześniej pominięta/)).toBeInTheDocument();
    expect(screen.getByText("Dopasowanie: 91")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Zweryfikuj wymaganie/ })).toBeInTheDocument();
    expect(screen.getByText("AWS").parentElement).toHaveTextContent("brak potwierdzenia");
  });

  it("technologia sprzed ponad 3 lat: „?” z rokiem ostatniego użycia (27.10.2026)", () => {
    const base = entry();
    const [stale] = mergeProposals({
      inbox: [{
        candidate: { id: 5, name: "Jan", lastname: "Kowalski", title: "QA", city: null, availability_status: null, availability_date: null, expected_rate_hourly: null, expected_rate_redacted: false },
        sources: ["full_base"], score: 77,
        evidence: { requirements: [{ any_of: ["java"], level: "must", status: "met" }, { any_of: ["angular"], level: "must", status: "unknown", last_used_year: 2020 }] },
        first_seen_at: null, last_seen_at: null, is_new: false, status: "proposed", eligibility: null,
      }],
      budgetHourly: null,
    });
    expect(stale.detail.requirements[1]).toMatchObject({ label: "angular", status: "unknown", lastUsedYear: 2020 });
    expect(base.detail.requirements[0]).not.toHaveProperty("lastUsedYear");
    renderPanel({ entry: stale });
    const row = screen.getByText("angular").parentElement!;
    expect(row).toHaveTextContent("?angular· 2020");
    expect(row).toHaveTextContent("ostatnio używane w 2020, do potwierdzenia");
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

  it("kontekst podobnych projektów nazywa etap po polsku, nie kodem", () => {
    const base = entry();
    const withHistory = {
      ...base,
      detail: {
        ...base.detail,
        similarProjects: [{ jobId: 9, title: "PL - IT Operations - Senior", stage: "client_interview" }],
      },
    } as typeof base;
    render(<ProposalPanel jobId={42} entry={withHistory} budgetHourly={150} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText(/etap: Rozmowa u klienta/)).toBeTruthy();
    expect(screen.queryByText(/client_interview/)).toBeNull();
  });

  describe("wariant A (13.10.2026): sprawdzone w CV ≠ do rozmowy", () => {
    const PROSE = "Doświadczenie w projektach bankowych";
    function withProse() {
      return mergeProposals({
        inbox: [{
          candidate: { id: 5, name: "Jan", lastname: "Kowalski", title: null, city: null, availability_status: null, availability_date: null, expected_rate_hourly: null, expected_rate_redacted: false },
          sources: ["new_cv"], score: 80,
          evidence: { requirements: [{ name: "Java", level: "must", status: "met" }, { name: "AWS", level: "must", status: "unknown" }, { name: PROSE, level: "must", status: "unknown" }] },
          first_seen_at: null, last_seen_at: null, is_new: false, status: "proposed", eligibility: null,
        }],
      })[0];
    }
    const talk = {
      checks: [
        { label: "bankowość", kind: "domains" },
        { label: "angielski B2", kind: "language" },
        { label: "  doświadczenie w projektach  BANKOWYCH ", kind: "must" },
      ],
      notSearchableMust: [],
    };

    it("must-have do rozmowy nie dostaje „?” — stoi w „Zapytaj w rozmowie”", () => {
      render(<ProposalPanel jobId={42} entry={withProse()} budgetHourly={null} talk={talk} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
      expect(screen.getByText("Sprawdzone w CV, profilu i notatkach")).toBeInTheDocument();
      expect(screen.getByText("Java").parentElement).toHaveTextContent("spełnione");
      expect(screen.getByText("AWS").parentElement).toHaveTextContent("brak potwierdzenia");
      // Zdanie z must-have nie jest wymaganiem „nie znaleźliśmy”.
      expect(screen.queryByText(PROSE)).toBeNull();
      const chips = within(screen.getByRole("list", { name: "Zapytaj w rozmowie" }));
      expect(chips.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
        "bankowość",
        "Język: angielski B2",
        talk.checks[2].label,
      ]);
    });

    it("`not_searchable_must` też zdejmuje „?”; bez listy do rozmowy — dawny widok", () => {
      const { unmount } = render(<ProposalPanel jobId={42} entry={withProse()} budgetHourly={null} talk={{ checks: [], notSearchableMust: [PROSE] }} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
      expect(screen.queryByText(PROSE)).toBeNull();
      expect(screen.queryByRole("list", { name: "Zapytaj w rozmowie" })).toBeNull();
      unmount();
      render(<ProposalPanel jobId={42} entry={withProse()} budgetHourly={null} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
      expect(screen.getByText(PROSE).parentElement).toHaveTextContent("brak potwierdzenia");
    });

    it("same wymagania do rozmowy: bez pustego bloku „Sprawdzone…”; bramka i weryfikacja zostają", () => {
      const base = withProse();
      const onlyProse = {
        ...base,
        detail: { ...base.detail, missingMustGate: ["Kafka"], requirements: base.detail.requirements.filter((r) => r.label === PROSE) },
      };
      render(<ProposalPanel jobId={42} entry={onlyProse} budgetHourly={null} talk={talk} canVerify onVerified={vi.fn()} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
      expect(screen.queryByText("Sprawdzone w CV, profilu i notatkach")).toBeNull();
      expect(screen.queryByText(/Brak oceny wymagań/)).toBeNull();
      expect(screen.getByText("Bramka must-have: brak Kafka")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Zweryfikuj wymaganie/ })).toBeInTheDocument();
      expect(screen.getByRole("list", { name: "Zapytaj w rozmowie" })).toBeInTheDocument();
    });

    it("awaria odczytu listy do rozmowy mówi o awarii, nie znika po cichu", () => {
      render(<ProposalPanel jobId={42} entry={withProse()} budgetHourly={null} talkError="Błąd serwera" onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
      expect(screen.getByRole("alert")).toHaveTextContent("Nie wczytano listy „Zapytaj w rozmowie”: Błąd serwera");
    });
  });

  it("bez aktywnej osoby pokazuje podpowiedź", () => {
    render(<ProposalPanel jobId={42} entry={null} budgetHourly={null} onAdd={vi.fn()} onShortlist={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText(/Wybierz osobę z listy/)).toBeInTheDocument();
  });
});
