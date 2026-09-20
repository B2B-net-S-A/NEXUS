import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  matchScores: vi.fn(),
  requirements: vi.fn(),
  replace: vi.fn(),
}));
let urlParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => urlParams,
  useRouter: () => ({ push: vi.fn(), replace: mocks.replace }),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
}));

vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: { matchScores: (...args: unknown[]) => mocks.matchScores(...args) },
}));

vi.mock("@/lib/matching-requirements", () => ({
  matchingRequirementsApi: { get: (...args: unknown[]) => mocks.requirements(...args) },
}));

vi.mock("@/components/v2/recruitment/JobPicker", () => ({
  JobPicker: ({ onChange }: { onChange: (job: { id: number; title: string }) => void }) => (
    <button type="button" onClick={() => onChange({ id: 42, title: "Java Developer" })}>
      Wybierz Java Developer (mock)
    </button>
  ),
}));

import CompareCandidatesPage from "../page";

const CANDIDATES: Record<string, unknown> = {
  "/api/candidates/1": { id: 1, name: "Anna", lastname: "Nowak", skills: [{ name: "Java" }, "Spring"] },
  "/api/candidates/2": { id: 2, name: "Jan", lastname: "Kowalski", skills: ["python"] },
};

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CompareCandidatesPage />
    </QueryClientProvider>,
  );
}

describe("/candidates/compare — dopasowanie do rekrutacji (B6)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    urlParams = new URLSearchParams("ids=1,2");
    mocks.get.mockImplementation((url: string) =>
      url === "/api/jobs/42"
        ? Promise.resolve({ data: { id: 42, title: "Java Developer", client_name: "Bank" } })
        : Promise.resolve({ data: CANDIDATES[url] }),
    );
    mocks.matchScores.mockResolvedValue({
      scores: { "1": 83.6 },
      breakdowns: { "1": { total: 83.6, measurement: "measured" }, "2": { total: null, measurement: "stale" } },
    });
    mocks.requirements.mockResolvedValue({
      version: 1,
      reviewed: true,
      missing_evidence_policy: "review",
      all_of: [
        { any_of: ["java"], level: "must", source: "manual", evidence: "" },
        { any_of: ["spring", "quarkus"], level: "must", source: "manual", evidence: "" },
        { any_of: ["docker"], level: "nice", source: "manual", evidence: "" },
      ],
    });
  });

  it("bez rekrutacji nie liczy dopasowania", async () => {
    renderPage();
    await screen.findByText("Anna Nowak");
    expect(screen.queryByTestId("compare-match-1")).not.toBeInTheDocument();
    expect(mocks.matchScores).not.toHaveBeenCalled();
  });

  it("wybór rekrutacji zapisuje ?job= obok ?ids=", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Wybierz rekrutację" }));
    fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
    expect(mocks.replace).toHaveBeenCalledWith("/candidates/compare?ids=1%2C2&job=42");
  });

  it("pokazuje liczbę, ocenę niepełną i must-have obok siebie — nigdy 0", async () => {
    urlParams = new URLSearchParams("ids=1,2&job=42");
    renderPage();
    const first = await screen.findByTestId("compare-match-1");
    await waitFor(() => expect(within(first).getByText("84")).toBeInTheDocument());
    expect(mocks.matchScores).toHaveBeenCalledWith(42, [1, 2], expect.anything());
    expect(within(first).getByLabelText("java: jest w umiejętnościach")).toBeInTheDocument();
    expect(within(first).getByLabelText("spring lub quarkus: jest w umiejętnościach")).toBeInTheDocument();
    expect(within(first).queryByText("docker")).not.toBeInTheDocument();

    const second = screen.getByTestId("compare-match-2");
    expect(within(second).getByText(/Ocena niepełna: profil kandydata zmienił się/)).toBeInTheDocument();
    expect(within(second).queryByText("0")).not.toBeInTheDocument();
    expect(within(second).getByLabelText("java: brak w umiejętnościach")).toBeInTheDocument();
    expect(await screen.findByTestId("compare-job")).toHaveTextContent("Java Developer · Bank");
  });

  it("403 mówi o braku dostępu, inny błąd daje „nie policzono — ponów”", async () => {
    urlParams = new URLSearchParams("ids=1,2&job=42");
    mocks.matchScores.mockRejectedValueOnce(httpError(403));
    const { unmount } = renderPage();
    const first = await screen.findByTestId("compare-match-1");
    expect(await within(first).findByText("Brak dostępu do oceny tej rekrutacji")).toBeInTheDocument();
    unmount();

    mocks.matchScores.mockReset().mockRejectedValueOnce(httpError(503)).mockResolvedValueOnce({
      scores: { "1": 70, "2": 55 },
      breakdowns: {},
    });
    renderPage();
    const retry = await within(await screen.findByTestId("compare-match-2")).findByRole("button", {
      name: /nie policzono — ponów/,
    });
    fireEvent.click(retry);
    expect(await within(screen.getByTestId("compare-match-2")).findByText("55")).toBeInTheDocument();
  });
});
