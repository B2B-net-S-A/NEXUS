/**
 * „Jakość podpowiedzi systemu” (23.10.2026): kafle, kosze odrzuceń, raport
 * z „Robimy / Nie” tylko dla admina i Head of Recruitment.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  };
  return { __esModule: true, default: client, api: client };
});
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn() }),
}));

import { AutofillQualityView } from "@/components/insights/AutofillQualityView";
import { useAuthStore } from "@/store/auth";

const SUMMARY = {
  since: "2026-10-16T00:00:00Z",
  until: "2026-10-23T00:00:00Z",
  added: 120,
  called: 30,
  rejected: 50,
  decided_pct: 66.7,
  called_pct: 37.5,
  search_error_pct: 40,
  verified: {
    system: { added: 120, verified: 7, verified_pct: 5.8 },
    manual: { added: 300, verified: 24, verified_pct: 8 },
  },
  waiting_now: 12,
  buckets: [
    {
      bucket: "search",
      label: "Błąd wyszukiwania",
      total: 20,
      reasons: [{ reason: "too_junior", label: "Za mało doświadczenia", count: 20 }],
    },
    {
      bucket: "data",
      label: "Brak danych",
      total: 30,
      reasons: [{ reason: "too_expensive", label: "Za droga", count: 30 }],
    },
    { bucket: "person", label: "Sprawa osoby", total: 0, reasons: [] },
    { bucket: "other", label: "Inne", total: 0, reasons: [] },
  ],
  worst_jobs: [
    {
      job_id: 77,
      job_title: "DevOps (Azure)",
      feedback: 9,
      search_errors: 7,
      search_pct: 77.8,
      top_reason: "other_level_or_role",
      top_reason_label: "Inny poziom lub inna rola",
    },
  ],
};

const REPORT = {
  id: 5,
  week_start: "2026-10-19",
  summary: {},
  proposals: [
    {
      title: "System dodaje młodszych do Seniora",
      kind: "search",
      evidence: "20 z 50 odrzuceń",
      fix: "liczyć poziom z tytułu roli",
      decision: null,
    },
  ],
  from_model: true,
  created_at: "2026-10-26T07:00:00Z",
};

function renderView() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AutofillQualityView />
    </QueryClientProvider>,
  );
}

describe("AutofillQualityView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    get.mockImplementation((url: string) =>
      Promise.resolve({ data: url.endsWith("/summary") ? SUMMARY : { items: [REPORT] } }),
    );
    post.mockResolvedValue({ data: { ...REPORT, proposals: [{ ...REPORT.proposals[0], decision: "yes" }] } });
  });

  it("pokazuje liczby kodu, kosze i najsłabsze rekrutacje", async () => {
    useAuthStore.setState({ user: { id: 1, role: "recruiter" } } as never);
    renderView();
    const tiles = await screen.findByTestId("autofill-quality-tiles");
    expect(tiles).toHaveTextContent("120");
    expect(tiles).toHaveTextContent("12 osób czeka > 2 dni");
    expect(tiles).toHaveTextContent("dodani ręcznie: 8%");
    expect(tiles).toHaveTextContent("40%");
    const reasons = screen.getByRole("region", { name: "Powody odrzuceń osób od systemu" });
    expect(reasons).toHaveTextContent("Brak danych");
    expect(reasons).toHaveTextContent("to uzupełniamy w bazie");
    expect(screen.getByRole("link", { name: "DevOps (Azure)" })).toHaveAttribute("href", "/jobs/77");
    // Rekruter widzi raport, ale nie decyduje.
    const report = await screen.findByRole("region", { name: "Raport poniedziałkowy" });
    expect(report).toHaveTextContent("System dodaje młodszych do Seniora");
    expect(within(report).queryByRole("button", { name: "Robimy" })).toBeNull();
  });

  it("admin klika „Robimy” — decyzja idzie do serwera", async () => {
    useAuthStore.setState({ user: { id: 1, role: "admin" } } as never);
    renderView();
    const report = await screen.findByRole("region", { name: "Raport poniedziałkowy" });
    await userEvent.click(within(report).getByRole("button", { name: "Robimy" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/autofill-quality/reports/5/proposals/0/decision", {
        decision: "yes",
      }),
    );
  });

  it("awaria liczb nie wygląda jak pusty ekran", async () => {
    useAuthStore.setState({ user: { id: 1, role: "admin" } } as never);
    get.mockImplementation((url: string) =>
      url.endsWith("/summary") ? Promise.reject(new Error("boom")) : Promise.resolve({ data: { items: [] } }),
    );
    renderView();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się");
  });
});
