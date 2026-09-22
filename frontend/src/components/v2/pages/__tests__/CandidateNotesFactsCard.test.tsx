import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CandidateNotesFactsCard } from "../CandidateNotesFactsCard";
import { candidateFactsApi, type CandidateNotesFacts } from "@/lib/api";

const showError = vi.fn();
const showSuccess = vi.fn();
const caps = vi.hoisted(() => ({ manage: true }));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError, showSuccess }),
}));
vi.mock("@/hooks/useCapability", () => ({
  useCapability: () => caps.manage,
}));
vi.mock("@/lib/api", () => ({
  candidateFactsApi: {
    getNotesFacts: vi.fn(),
    applyNotesFact: vi.fn(),
  },
  extractErrorMsg: () => "Błąd serwera",
}));

const mockedApi = vi.mocked(candidateFactsApi);

function facts(overrides: Partial<CandidateNotesFacts> = {}): CandidateNotesFacts {
  return {
    candidate_id: 7,
    extracted_at: "2026-09-20T04:00:00+00:00",
    has_facts: true,
    rate: {
      value: "25200",
      currency: "PLN",
      period: "month",
      raw: "oczekuje 25 200 zł netto miesięcznie",
      as_of: "2026-09",
      hourly_pln: "150.00",
      flexibility: null,
      profile_amount: null,
      profile_rate_version: 3,
      can_apply: true,
    },
    work_mode: {
      modes: ["remote", "hybrid"],
      max_onsite_days: 2,
      profile_modes: [],
      profile_max_onsite_days: null,
      can_apply: true,
    },
    contract_form: { value: "b2b", profile_contract_types: ["b2b"], can_apply: false },
    availability: null,
    office_cities: null,
    relocation: { willing: true, targets: ["Kraków"] },
    current_engagement: { employer: "Bank X", project: null, ends_at: "2026-12", raw: null },
    not_looking_until: null,
    languages: [],
    sectors_prefer: [],
    sectors_avoid: [],
    client_vetoes: [{ client: "Firma Y", reason: null }],
    matching_facts: null,
    ...overrides,
  };
}

function renderCard(readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CandidateNotesFactsCard candidateId={7} readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

describe("CandidateNotesFactsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    caps.manage = true;
    mockedApi.getNotesFacts.mockResolvedValue(facts());
  });

  it("shows converted rate, office days and what the profile has", async () => {
    const user = userEvent.setup();
    renderCard();
    expect(await screen.findByText("150 PLN netto/h")).toBeInTheDocument();
    expect(
      screen.getByText(/W notatce: 25\s200 PLN \/ mies\. \(stawka miesięczna ÷ 168 h\)/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Hybrydowo lub zdalnie · do 2 dni w biurze w tygodniu"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Gotowy do przeprowadzki · Kraków")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Więcej z notatek (3)" }));
    expect(screen.getByText("Gotowy do przeprowadzki · Kraków")).toBeInTheDocument();
    expect(screen.getByText("Bank X · do 2026-12")).toBeInTheDocument();
    expect(screen.getByText("Firma Y")).toBeInTheDocument();
    // forma współpracy zgodna z profilem — bez przycisku zapisu
    expect(screen.getAllByRole("button", { name: "Zapisz w profilu" })).toHaveLength(2);
  });

  it("saves the rate with the profile-rate version it was shown with", async () => {
    const user = userEvent.setup();
    mockedApi.applyNotesFact.mockResolvedValue(
      facts({ rate: { ...facts().rate!, profile_amount: "150.00", can_apply: false } }),
    );
    renderCard();
    await screen.findByText("150 PLN netto/h");
    await user.click(screen.getAllByRole("button", { name: "Zapisz w profilu" })[0]);
    await waitFor(() =>
      expect(mockedApi.applyNotesFact).toHaveBeenCalledWith(7, "rate", 3),
    );
    expect(showSuccess).toHaveBeenCalledWith("Zapisano w profilu kandydata");
    expect(await screen.findByText("W profilu: 150 PLN netto/h")).toBeInTheDocument();
  });

  it("explains a version conflict instead of overwriting", async () => {
    const user = userEvent.setup();
    mockedApi.applyNotesFact.mockRejectedValue({ response: { status: 412 } });
    renderCard();
    await screen.findByText("150 PLN netto/h");
    await user.click(screen.getAllByRole("button", { name: "Zapisz w profilu" })[1]);
    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(mockedApi.applyNotesFact).toHaveBeenCalledWith(7, "work_mode", undefined);
    expect(showError.mock.calls[0][0]).toMatch(/innym oknie/);
  });

  it("hides save buttons in read-only mode and the whole card without capability", async () => {
    const { unmount } = renderCard(true);
    await screen.findByText("150 PLN netto/h");
    expect(screen.queryByRole("button", { name: "Zapisz w profilu" })).toBeNull();
    unmount();

    caps.manage = false;
    renderCard();
    expect(screen.queryByText("Z notatek rekruterów")).toBeNull();
    expect(mockedApi.getNotesFacts).toHaveBeenCalledTimes(1);
  });

  it("renders failure as an error with retry, never as emptiness", async () => {
    mockedApi.getNotesFacts.mockRejectedValue({ response: { status: 500 } });
    renderCard();
    expect(
      await screen.findByText("Nie udało się wczytać faktów z notatek."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument();
  });

  it("distinguishes not-yet-analysed from nothing-to-add", async () => {
    mockedApi.getNotesFacts.mockResolvedValue(
      facts({ has_facts: false, extracted_at: null }),
    );
    renderCard();
    expect(
      await screen.findByText("Notatki tego kandydata nie zostały jeszcze przeanalizowane."),
    ).toBeInTheDocument();
  });
});
