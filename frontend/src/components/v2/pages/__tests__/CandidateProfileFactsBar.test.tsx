import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CandidateProfileFactsBar } from "../CandidateProfileFactsBar";
import {
  candidateFactsApi,
  candidateProfileApi,
  type CandidateLanguage,
} from "@/lib/api";

const showError = vi.fn();
const showSuccess = vi.fn();
const auth = vi.hoisted(() => ({ role: "recruiter" }));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError, showSuccess }),
}));

// `getUserRoles` MUSI być w tej fabryce: bramka stawki idzie przez
// `useCapability` → `hasCapability` (realny `@/lib/capabilities`) →
// `getUserRoles` z TEGO mocka. Bez niego leci TypeError w renderze i pada
// CAŁY plik — objaw wygląda jak zepsuta bramka, przyczyną jest setup testu.
vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (state: { user: { role: string; roles: string[] } }) => unknown,
  ) => selector({ user: { role: auth.role, roles: [auth.role] } }),
  hasRole: (_user: unknown, ...roles: string[]) => roles.includes(auth.role),
  getUserRoles: (user: { role: string; roles?: string[] } | null) =>
    user ? Array.from(new Set([user.role, ...(user.roles ?? [])])) : [],
}));

vi.mock("@/lib/api", () => ({
  candidateFactsApi: {
    getLanguages: vi.fn(),
    updateLanguages: vi.fn(),
    getProfileRate: vi.fn(),
    updateProfileRate: vi.fn(),
  },
  candidateProfileApi: {
    updateLocation: vi.fn(),
  },
  extractErrorMsg: () => "Błąd serwera",
}));

const mockedFactsApi = vi.mocked(candidateFactsApi);
const mockedProfileApi = vi.mocked(candidateProfileApi);

const language: CandidateLanguage = {
  id: 11,
  language_code: "en",
  language_name: "Angielski",
  cefr_level: "C1",
  is_native: false,
  is_level_unknown: false,
  provenance: "manual",
  manual_lock: true,
  version: 3,
};

function prepareApi() {
  mockedFactsApi.getLanguages.mockResolvedValue({
    data: { candidate_id: 7, version: 3, languages: [language] },
    etag: '"candidate-languages-7-v3"',
  });
  mockedFactsApi.getProfileRate.mockResolvedValue({
    data: {
      candidate_id: 7,
      amount: "160.00",
      currency: "PLN",
      unit: "hour",
      tax_basis: "net",
      contract_type: "b2b",
      version: 2,
      updated_at: "2026-07-29T10:00:00Z",
    },
    etag: '"candidate-profile-rate-7-v2"',
  });
}

type FactsCandidate = ComponentProps<
  typeof CandidateProfileFactsBar
>["candidate"];

function renderBar(candidateOverrides: Partial<FactsCandidate> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CandidateProfileFactsBar
        candidate={{
          id: 7,
          city: "Warszawa",
          country: "PL",
          availability_status: "open_to_offers",
          availability_date: "2026-08-15",
          ...candidateOverrides,
        }}
      />
    </QueryClientProvider>,
  );
}

describe("CandidateProfileFactsBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.role = "recruiter";
    prepareApi();
  });

  it("shows typed facts and fixed B2B PLN net/hour semantics", async () => {
    renderBar();

    expect(await screen.findByText("Angielski · C1")).toBeInTheDocument();
    expect(screen.getByText("Warszawa, PL")).toBeInTheDocument();
    expect(screen.getByText(/Otwarty\/a na oferty/)).toBeInTheDocument();
    expect(screen.getByText("160 PLN netto/h")).toBeInTheDocument();
  });

  it("allows long fact tokens to wrap instead of overflowing the profile", async () => {
    const longCity = "MiastoBezPrzerw".repeat(20);
    renderBar({ city: longCity, country: null });

    await screen.findByText("Angielski · C1");
    expect(screen.getByText(longCity).classList).toContain(
      "[overflow-wrap:anywhere]",
    );
    expect(screen.getByText("Angielski · C1").classList).toContain(
      "[overflow-wrap:anywhere]",
    );
  });

  it("uses legacy location only as a read-only fallback", async () => {
    renderBar({
      city: null,
      country: null,
      location: "  Gdańsk, Polska  ",
    });

    expect(await screen.findByText("Gdańsk, Polska")).toBeInTheDocument();
    expect(mockedProfileApi.updateLocation).not.toHaveBeenCalled();
  });

  it("saves languages with the ETag returned by GET", async () => {
    mockedFactsApi.updateLanguages.mockResolvedValue({
      data: { candidate_id: 7, version: 4, languages: [language] },
      etag: '"candidate-languages-7-v4"',
    });
    const user = userEvent.setup();
    renderBar();

    await screen.findByText("Angielski · C1", {}, { timeout: 5_000 });
    await user.click(
      screen.getByRole("button", { name: "Edytuj języki" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz języki" }));

    await waitFor(() =>
      expect(mockedFactsApi.updateLanguages).toHaveBeenCalledWith(
        7,
        [
          {
            language_code: "en",
            language_name: "Angielski",
            cefr_level: "C1",
            is_native: false,
            is_level_unknown: false,
          },
        ],
        '"candidate-languages-7-v3"',
      ),
    );
  });

  it("generates a valid code when a new language is added", async () => {
    mockedFactsApi.getLanguages.mockResolvedValue({
      data: { candidate_id: 7, version: 3, languages: [] },
      etag: '"candidate-languages-7-v3"',
    });
    mockedFactsApi.updateLanguages.mockResolvedValue({
      data: {
        candidate_id: 7,
        version: 4,
        languages: [{ ...language, id: 12 }],
      },
      etag: '"candidate-languages-7-v4"',
    });
    const user = userEvent.setup();
    renderBar();

    await screen.findByText("Nie uzupełniono");
    await user.click(
      screen.getByRole("button", { name: "Edytuj języki" }),
    );
    await user.click(screen.getByRole("button", { name: "Dodaj język" }));
    await user.type(screen.getByLabelText("Język"), "Angielski");

    expect(screen.getByLabelText("Kod")).toHaveValue("en");
    await user.click(screen.getByRole("button", { name: "Zapisz języki" }));

    await waitFor(() =>
      expect(mockedFactsApi.updateLanguages).toHaveBeenCalledWith(
        7,
        [
          {
            language_code: "en",
            language_name: "Angielski",
            cefr_level: null,
            is_native: false,
            is_level_unknown: true,
          },
        ],
        '"candidate-languages-7-v3"',
      ),
    );
  });

  it("accepts the full 16-character language-code boundary", async () => {
    const boundaryCode = "a123456789012345";
    mockedFactsApi.updateLanguages.mockResolvedValue({
      data: {
        candidate_id: 7,
        version: 4,
        languages: [{ ...language, language_code: boundaryCode }],
      },
      etag: '"candidate-languages-7-v4"',
    });
    const user = userEvent.setup();
    renderBar();

    await screen.findByText("Angielski · C1");
    await user.click(
      screen.getByRole("button", { name: "Edytuj języki" }),
    );
    const code = screen.getByLabelText("Kod");
    await user.clear(code);
    await user.type(code, boundaryCode);
    await user.click(screen.getByRole("button", { name: "Zapisz języki" }));

    await waitFor(() =>
      expect(mockedFactsApi.updateLanguages).toHaveBeenCalledWith(
        7,
        [
          {
            language_code: boundaryCode,
            language_name: "Angielski",
            cefr_level: "C1",
            is_native: false,
            is_level_unknown: false,
          },
        ],
        '"candidate-languages-7-v3"',
      ),
    );
  });

  it("keeps the edited languages draft open after an ETag conflict", async () => {
    mockedFactsApi.updateLanguages.mockRejectedValue({
      response: { status: 412 },
    });
    const user = userEvent.setup();
    renderBar();

    await screen.findByText("Angielski · C1");
    await user.click(
      screen.getByRole("button", { name: "Edytuj języki" }),
    );
    const name = screen.getByLabelText("Język");
    await user.clear(name);
    await user.type(name, "English");
    await user.click(screen.getByRole("button", { name: "Zapisz języki" }));

    expect(
      await screen.findByText(/Zachowaliśmy Twój draft/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Język")).toHaveValue("English");
  });

  it("saves canonical city and country through the existing location endpoint", async () => {
    mockedProfileApi.updateLocation.mockResolvedValue({ data: {} } as never);
    const user = userEvent.setup();
    renderBar();

    await user.click(
      await screen.findByRole("button", { name: "Edytuj lokalizację" }),
    );
    const city = screen.getByLabelText("Miasto");
    await user.clear(city);
    await user.type(city, "Kraków");
    await user.click(
      screen.getByRole("button", { name: "Zapisz lokalizację" }),
    );

    await waitFor(() =>
      expect(mockedProfileApi.updateLocation).toHaveBeenCalledWith(7, {
        city: "Kraków",
        country: "PL",
      }),
    );
  });

  it("saves the B2B rate with profile-rate ETag and no selectable unit", async () => {
    mockedFactsApi.updateProfileRate.mockResolvedValue({
      data: {
        candidate_id: 7,
        amount: "175.50",
        currency: "PLN",
        unit: "hour",
        tax_basis: "net",
        contract_type: "b2b",
        version: 3,
        updated_at: "2026-07-30T10:00:00Z",
      },
      etag: '"candidate-profile-rate-7-v3"',
    });
    const user = userEvent.setup();
    renderBar();

    await screen.findByText("160 PLN netto/h", {}, { timeout: 5_000 });
    await user.click(
      screen.getByRole("button", {
        name: "Edytuj globalną stawkę B2B",
      }),
    );
    const input = screen.getByLabelText("Kwota");
    await user.clear(input);
    await user.type(input, "175,50");
    await user.click(screen.getByRole("button", { name: "Zapisz stawkę" }));

    await waitFor(() =>
      expect(mockedFactsApi.updateProfileRate).toHaveBeenCalledWith(
        7,
        "175.50",
        '"candidate-profile-rate-7-v2"',
      ),
    );
    expect(screen.queryByLabelText(/waluta|jednostka/i)).not.toBeInTheDocument();
  });

  it("accepts the full NUMERIC(10,2) profile-rate boundary", async () => {
    mockedFactsApi.updateProfileRate.mockResolvedValue({
      data: {
        candidate_id: 7,
        amount: "99999999.99",
        currency: "PLN",
        unit: "hour",
        tax_basis: "net",
        contract_type: "b2b",
        version: 3,
        updated_at: "2026-07-30T10:00:00Z",
      },
      etag: '"candidate-profile-rate-7-v3"',
    });
    const user = userEvent.setup();
    renderBar();

    await user.click(
      await screen.findByRole("button", {
        name: "Edytuj globalną stawkę B2B",
      }),
    );
    const input = screen.getByLabelText("Kwota");
    await user.clear(input);
    await user.type(input, "99999999,99");
    await user.click(screen.getByRole("button", { name: "Zapisz stawkę" }));

    await waitFor(() =>
      expect(mockedFactsApi.updateProfileRate).toHaveBeenCalledWith(
        7,
        "99999999.99",
        '"candidate-profile-rate-7-v2"',
      ),
    );
  });

  it("rejects nine integer digits before calling the profile-rate API", async () => {
    const user = userEvent.setup();
    renderBar();

    await user.click(
      await screen.findByRole("button", {
        name: "Edytuj globalną stawkę B2B",
      }),
    );
    const input = screen.getByLabelText("Kwota");
    await user.clear(input);
    await user.type(input, "100000000");
    await user.click(screen.getByRole("button", { name: "Zapisz stawkę" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /maksymalnie 8 cyframi/i,
    );
    expect(mockedFactsApi.updateProfileRate).not.toHaveBeenCalled();
  });

  it("keeps a rate mutation error inline and linked to the input", async () => {
    mockedFactsApi.updateProfileRate.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    renderBar();

    await user.click(
      await screen.findByRole("button", {
        name: "Edytuj globalną stawkę B2B",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz stawkę" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Błąd serwera");
    expect(alert).toHaveAttribute("id", "candidate-profile-rate-mutation-error");
    expect(screen.getByLabelText("Kwota")).toHaveAttribute(
      "aria-describedby",
      expect.stringContaining("candidate-profile-rate-mutation-error"),
    );
  });

  it("keeps the edited rate draft open after an ETag conflict", async () => {
    mockedFactsApi.updateProfileRate.mockRejectedValue({
      response: { status: 412 },
    });
    const user = userEvent.setup();
    renderBar();

    await screen.findByText("160 PLN netto/h");
    await user.click(
      screen.getByRole("button", {
        name: "Edytuj globalną stawkę B2B",
      }),
    );
    const input = screen.getByLabelText("Kwota");
    await user.clear(input);
    await user.type(input, "175,50");
    await user.click(screen.getByRole("button", { name: "Zapisz stawkę" }));

    expect(
      await screen.findByText(/Zachowaliśmy Twój draft/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Kwota")).toHaveValue("175,50");
  });

  it("renders a distinct forbidden state for languages", async () => {
    mockedFactsApi.getLanguages.mockRejectedValue({
      response: { status: 403 },
    });
    renderBar();

    expect(await screen.findByText("Brak dostępu")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Ponów pobieranie języków" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edytuj języki" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the 320px layout single-column and new touch controls at least 44px", async () => {
    const user = userEvent.setup();
    renderBar();

    await screen.findByText("Angielski · C1");
    const facts = screen.getByRole("region", {
      name: "Najważniejsze fakty o kandydacie",
    });
    expect(facts.classList.contains("grid-cols-4")).toBe(false);
    expect(facts.classList.contains("sm:grid-cols-2")).toBe(true);

    const editLanguages = screen.getByRole("button", {
      name: "Edytuj języki",
    });
    expect(editLanguages.classList.contains("min-h-11")).toBe(true);
    expect(editLanguages.classList.contains("min-w-11")).toBe(true);
    expect(editLanguages.classList.contains("sm:min-h-8")).toBe(false);

    await user.click(editLanguages);
    expect(screen.getByLabelText("Język").classList.contains("min-h-11")).toBe(
      true,
    );
    expect(screen.getByLabelText("Kod").classList.contains("min-h-11")).toBe(
      true,
    );
    expect(screen.getByLabelText("Poziom").classList.contains("h-11")).toBe(
      true,
    );
    expect(
      screen
        .getByRole("button", { name: "Zapisz języki" })
        .classList.contains("min-h-11"),
    ).toBe(true);
  });

  it("omits the global rate completely for the viewer role", async () => {
    auth.role = "user";
    renderBar();

    expect(await screen.findByText("Angielski · C1")).toBeInTheDocument();
    expect(screen.queryByText("Stawka B2B")).not.toBeInTheDocument();
    expect(mockedFactsApi.getProfileRate).not.toHaveBeenCalled();
  });

  // Fakty globalne stoją na _INTERNAL_OPERATIONAL_ROLES, a nie na węższym
  // RECRUITMENT_RATE_EDIT_ROLES (bramka stawki w pipelinie, bez HoR
  // i sourcera). Ten przypadek pilnuje, żeby nikt nie „poprawił" mapowania
  // na tamten zbiór — HoR straciłby uprawnienie, które backend mu jawnie daje.
  it("pokazuje stawkę HoR-owi (fakty globalne, nie RECRUITMENT_RATE_EDIT_ROLES)", async () => {
    auth.role = "head_of_recruitment";
    renderBar();

    expect(await screen.findByText("Stawka B2B")).toBeInTheDocument();
    expect(mockedFactsApi.getProfileRate).toHaveBeenCalled();
  });

  // Finance ma tier operacyjny od 19.08 — backend odpowiada 200, front chował.
  // Ten przypadek jest CZERWONY przed zmianą.
  it("pokazuje stawkę finansom (tier operacyjny 19.08)", async () => {
    auth.role = "finance";
    renderBar();

    expect(await screen.findByText("Stawka B2B")).toBeInTheDocument();
    expect(mockedFactsApi.getProfileRate).toHaveBeenCalled();
  });
});
