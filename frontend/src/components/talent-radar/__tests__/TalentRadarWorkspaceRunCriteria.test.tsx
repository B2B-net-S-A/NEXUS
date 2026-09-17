import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, test, vi } from "vitest";
import { saveTalentRadarSession } from "@/lib/talent-radar-session";
import { RADAR_BUDGET_ERROR } from "@/components/talent-radar/run-criteria";

const mocks = vi.hoisted(() => ({ start: vi.fn(), page: vi.fn(), showError: vi.fn() }));
vi.mock("@/store/auth", () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: 7, role: "recruiter" } }) }));
vi.mock("@/lib/section-access", () => ({ hasSectionAccess: () => false }));
vi.mock("@/hooks/useCapability", () => ({ useCapability: () => true }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: mocks.showError, showSuccess: vi.fn() }) }));
vi.mock("@/components/talent-radar/TalentRadarClientPicker", () => ({
  TalentRadarClientPicker: ({ onChange }: { onChange: (c: { id: number; name: string }) => void }) =>
    <button type="button" onClick={() => onChange({ id: 8, name: "Beta" })}>Zmień klienta</button>,
}));
vi.mock("@/components/ChampionIntake", () => ({
  championErrorValidation: () => undefined,
  ChampionImportReview: () => null,
  ChampionImportButton: () => null,
  ChampionTemplateDownload: () => null,
  ChampionValidationPanel: () => null,
}));
vi.mock("@/lib/full-candidate-search-api", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/full-candidate-search-api")>(),
  candidateSearchApi: { start: (...args: unknown[]) => mocks.start(...args), page: (...args: unknown[]) => mocks.page(...args) },
}));

import { TalentRadarWorkspace } from "@/components/talent-radar/TalentRadarWorkspace";

const TEXT = "Szukamy osoby z Pythonem, FastAPI i Postgresem — min. 5 lat doświadczenia.";

beforeEach(() => {
  sessionStorage.clear(); localStorage.clear(); vi.clearAllMocks();
  // Formularz gotowy do startu: klient, treść i sprawdzone wymagania dla TEJ treści.
  saveTalentRadarSession({
    client: { id: 5, name: "Acme" }, title: "", text: TEXT, location: "Warszawa",
    budgetMax: "150", excludeRemoteOnly: false, onsiteDaysPerWeek: "2", officeLocation: "",
    championProfile: null, championSummary: null, championSkills: null,
    requirementsPreview: { source: JSON.stringify([TEXT, "", null]), must: "Python", nice: "", excluded: [], uncertain: [] },
    response: null,
  });
  mocks.start.mockResolvedValue({ run_id: "radar-run", state: "queued", population: 100, brief_status: "provided", versions: {} });
  mocks.page.mockResolvedValue({
    run_id: "radar-run", state: "complete", versions: {}, results: [], budget_hourly: 150, ranking_complete: true,
    counts: { population: 100, pending: 0, failed: 0, evaluated: 100, eligible: 0, excluded: 100, needs_verification: 0 },
  });
});

function mount() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><TalentRadarWorkspace /></QueryClientProvider>);
}

test("wyniki pokazują kryteria biegu, a zmiana budżetu je unieważnia jak zmiana klienta", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Szukaj w całej bazie" }));
  await waitFor(() => expect(mocks.start).toHaveBeenCalledTimes(1));
  const criteria = await screen.findByTestId("tr-run-criteria");
  expect(criteria).toHaveTextContent("Klient: Acme · budżet do 150 PLN/h · lokalizacja: Warszawa · biuro 2 dni/tydz.");

  fireEvent.change(screen.getByLabelText("Budżet PLN/h"), { target: { value: "170" } });
  await waitFor(() => expect(screen.queryByTestId("tr-run-criteria")).not.toBeInTheDocument());
  expect(sessionStorage.getItem("nexus-full-radar:7")).toBeNull();
  expect(mocks.start).toHaveBeenCalledTimes(1);
});

test("liczby poza limitem backendu blokują start z komunikatem po polsku", async () => {
  mount();
  const budget = await screen.findByLabelText("Budżet PLN/h");
  fireEvent.change(budget, { target: { value: "5000" } });
  expect(await screen.findByText(RADAR_BUDGET_ERROR)).toBeVisible();
  expect(screen.getByRole("button", { name: "Szukaj w całej bazie" })).toBeDisabled();
  expect(mocks.start).not.toHaveBeenCalled();
});

test("błąd odczytu przebiegu daje JEDEN toast na epizod, nie jeden na poll", async () => {
  const outage = Object.assign(new Error("Bad gateway"), { response: { status: 502 } });
  mocks.page.mockRejectedValue(outage);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Szukaj w całej bazie" }));
  await waitFor(() => expect(mocks.showError).toHaveBeenCalledTimes(1));
  fireEvent.click(await screen.findByRole("button", { name: "Spróbuj ponownie" }));
  await waitFor(() => expect(mocks.page.mock.calls.length).toBeGreaterThanOrEqual(2));
  expect(mocks.showError).toHaveBeenCalledTimes(1);
});
