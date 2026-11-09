import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
  user: { role: "delivery_lead", roles: ["delivery_lead"] } as Record<string, unknown>,
  canEdit: true,
  showError: vi.fn(),
  showSuccess: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: mocks.get, patch: mocks.patch, put: mocks.put },
}));
vi.mock("@/lib/permissions", () => ({ hasPermission: () => mocks.canEdit }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: unknown }) => unknown) =>
    selector({ user: mocks.user }),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.showError, showSuccess: mocks.showSuccess }),
}));

import { BnpMonthlyReportDialog } from "@/components/client-profile/BnpMonthlyReportDialog";

const ROW = {
  job_id: 7,
  title: "IT Analyst RITM1",
  start: "2026-10-08",
  closed: null,
  sla: "2026-10-22",
  ritm: null,
  ritm_source: "none",
  role: "IT Analyst",
  seniority: null,
  seniority_label: null,
  seniority_source: "none",
  rate_card_id: null,
  contract_role: null,
  contract_role_source: "none",
  cv: 4,
  cv_sla: 3,
  cv_in_budget: 2,
  percent_cv_sla: 0.75,
  ritm_sla: 1,
  ritm_sla_and_budget: 1,
  rejected_cv: 0,
  meetings: 1,
  rejected_after_meeting: 0,
  meetings_per_cv: 0.25,
  rejected_per_cv: 0,
  offers: 1,
  offer_min_md: 640,
  offer_max_md: 760,
  band_min_md: null,
  band_max_md: null,
  band_average_md: null,
  recommended_average_md: 700,
  percent_from_band_average: null,
  offer_min_minus_top: null,
  percent_difference: null,
  needs_attention: true,
};

const reportWith = (overrides: Record<string, unknown> = {}) => ({
  data: {
    month: "2026-10",
    rows: [ROW],
    bands: [{ id: 5, role: "IT Analyst", minimum: 50, maximum: 100, average: 75 }],
    bands_source: "saved",
    seniority_options: [{ value: "mid", label: "Regular" }],
    ...overrides,
  },
});

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BnpMonthlyReportDialog clientId={12} onClose={() => undefined} />
    </QueryClientProvider>,
  );
}

describe("BnpMonthlyReportDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.canEdit = true;
    mocks.get.mockResolvedValue(reportWith());
    mocks.patch.mockResolvedValue({ data: { ok: true } });
    mocks.put.mockResolvedValue({ data: { saved: 1 } });
  });

  it("pyta o poprzedni miesiąc i pokazuje braki w arkuszu", async () => {
    renderDialog();
    expect(await screen.findByText("IT Analyst")).toBeInTheDocument();
    expect(mocks.get.mock.calls[0][1].params.month).toMatch(/^\d{4}-\d{2}$/);
    expect(screen.getAllByText("brak").length).toBeGreaterThan(0);
    expect(screen.getByText("760")).toBeInTheDocument();
  });

  it("awaria nie wygląda jak pusty miesiąc", async () => {
    mocks.get.mockRejectedValue(new Error("boom"));
    renderDialog();
    expect(await screen.findByText(/Nie udało się załadować raportu/)).toBeInTheDocument();
    expect(screen.queryByText(/nie otwarto żadnego procesu/)).not.toBeInTheDocument();
  });

  it("pusty miesiąc mówi to wprost i blokuje pobieranie", async () => {
    mocks.get.mockResolvedValue(reportWith({ rows: [] }));
    renderDialog();
    expect(await screen.findByText(/nie otwarto żadnego procesu/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz Excel/ })).toBeDisabled();
  });

  it("zmiana seniority zapisuje się w rekrutacji", async () => {
    const user = userEvent.setup();
    renderDialog();
    await screen.findByText("IT Analyst");
    await user.click(screen.getByRole("tab", { name: /Do uzupełnienia/ }));
    await user.selectOptions(screen.getByLabelText(/Seniority:/), "mid");
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/clients/12/bnp-report/jobs/7", {
        seniority: "mid",
      }),
    );
  });

  it("rola z umowy czeka na zapis widełek", async () => {
    const user = userEvent.setup();
    mocks.get.mockResolvedValue(
      reportWith({
        bands_source: "contract",
        bands: [{ id: null, role: "IT Analyst", minimum: 50, maximum: 100, average: 75 }],
      }),
    );
    renderDialog();
    await screen.findByText("IT Analyst");
    await user.click(screen.getByRole("tab", { name: /Do uzupełnienia/ }));
    expect(screen.getByText(/po zapisaniu widełek/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Rola z umowy:/)).not.toBeInTheDocument();
  });

  it("zapisuje poprawione widełki", async () => {
    const user = userEvent.setup();
    renderDialog();
    await screen.findByText("IT Analyst");
    await user.click(screen.getByRole("tab", { name: /Widełki z umowy/ }));
    const maximum = screen.getByLabelText("Maksimum: IT Analyst");
    await user.clear(maximum);
    await user.type(maximum, "120");
    await user.click(screen.getByRole("button", { name: "Zapisz widełki" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/clients/12/bnp-report/rate-bands", {
        bands: [{ role: "IT Analyst", minimum: 50, maximum: 120 }],
      }),
    );
  });

  it("minimum większe od maksimum blokuje zapis", async () => {
    const user = userEvent.setup();
    renderDialog();
    await screen.findByText("IT Analyst");
    await user.click(screen.getByRole("tab", { name: /Widełki z umowy/ }));
    const minimum = screen.getByLabelText("Minimum: IT Analyst");
    await user.clear(minimum);
    await user.type(minimum, "500");
    expect(screen.getByRole("button", { name: "Zapisz widełki" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(/nie większą niż maksimum/);
  });

  it("bez uprawnienia pola są tylko do odczytu", async () => {
    const user = userEvent.setup();
    mocks.canEdit = false;
    renderDialog();
    await screen.findByText("IT Analyst");
    await user.click(screen.getByRole("tab", { name: /Do uzupełnienia/ }));
    expect(screen.getByLabelText(/Seniority:/)).toBeDisabled();
    await user.click(screen.getByRole("tab", { name: /Widełki z umowy/ }));
    expect(screen.queryByRole("button", { name: "Zapisz widełki" })).not.toBeInTheDocument();
  });
});
