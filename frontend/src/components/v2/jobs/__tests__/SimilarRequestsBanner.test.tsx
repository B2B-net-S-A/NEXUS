import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  preview: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  requestHistoryApi: {
    preview: (...args: unknown[]) => mocks.preview(...args),
  },
}));

vi.mock("@/lib/use-debounced-value", () => ({
  useDebouncedValue: (value: unknown) => value,
}));

import { SimilarRequestsBanner } from "@/components/v2/jobs/SimilarRequestsBanner";

function renderBanner(
  overrides: Partial<React.ComponentProps<typeof SimilarRequestsBanner>> = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onUseAsTemplate = vi.fn();
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <SimilarRequestsBanner
        clientId={42}
        title="Senior Java Developer"
        templateJobId={null}
        onUseAsTemplate={onUseAsTemplate}
        {...overrides}
      />
    </QueryClientProvider>,
  );
  return { ...utils, onUseAsTemplate };
}

const IN_PROGRESS_ENTRY = {
  job_id: 12,
  title: "Senior Java Developer",
  train_name: null,
  same_train: false,
  seniority: "senior",
  status: "published",
  is_in_progress: true,
  outcome: null,
  close_reason: null,
  similarity: 0.92,
  similarity_source: "sql_same_client",
  closed_at: null,
  created_at: "2026-01-01T00:00:00Z",
  tth_days: null,
  client_id: 42,
  client_name: "Acme",
  champion_name: null,
  champion_candidate_id: null,
  champions_count: 0,
  candidates_count: 4,
  fee_rate: null,
  fee_currency: null,
  rate_unit: null,
  tac_name: null,
  delivery_lead_name: null,
};

const CLOSED_ENTRY = {
  ...IN_PROGRESS_ENTRY,
  job_id: 13,
  is_in_progress: false,
  outcome: "filled",
  status: "closed",
  candidates_count: 2,
};

beforeEach(() => {
  mocks.preview.mockReset();
});

describe("SimilarRequestsBanner", () => {
  it("nie odpytuje, dopóki tytuł ma mniej niż 5 znaków", async () => {
    renderBanner({ title: "Java" });
    await new Promise((r) => setTimeout(r, 0));
    expect(mocks.preview).not.toHaveBeenCalled();
  });

  it("nie odpytuje bez wybranego klienta", async () => {
    renderBanner({ clientId: null, title: "Senior Java Developer" });
    await new Promise((r) => setTimeout(r, 0));
    expect(mocks.preview).not.toHaveBeenCalled();
  });

  it("renderuje się bez fromJobId — odpytuje samo, gdy klient i tytuł są gotowe", async () => {
    mocks.preview.mockResolvedValue({
      data: {
        closed: [],
        in_progress: [IN_PROGRESS_ENTRY],
        skill_frequency: {},
        meta: { sql_count: 0, voyage_count: 0, total: 1, skill_freq_sample: 0 },
      },
    });
    renderBanner();
    await waitFor(() => expect(mocks.preview).toHaveBeenCalledTimes(1));
    expect(mocks.preview).toHaveBeenCalledWith(
      expect.objectContaining({ client_id: 42, title: "Senior Java Developer" }),
    );
    expect(await screen.findByTestId("request-history-banner")).toBeInTheDocument();
  });

  it("pokazuje błąd zamiast twierdzić, że nic podobnego nie było", async () => {
    mocks.preview.mockRejectedValue(new Error("network"));
    renderBanner();
    expect(
      await screen.findByTestId("request-history-banner-error"),
    ).toBeInTheDocument();
  });

  it("nic nie renderuje, gdy nie ma podobnych requestów", async () => {
    mocks.preview.mockResolvedValue({
      data: {
        closed: [],
        in_progress: [],
        skill_frequency: {},
        meta: { sql_count: 0, voyage_count: 0, total: 0, skill_freq_sample: 0 },
      },
    });
    renderBanner();
    await waitFor(() => expect(mocks.preview).toHaveBeenCalled());
    expect(screen.queryByTestId("request-history-banner")).not.toBeInTheDocument();
  });

  it("„Otwórz istniejącą” pokazuje się tylko dla requestu w toku", async () => {
    mocks.preview.mockResolvedValue({
      data: {
        closed: [CLOSED_ENTRY],
        in_progress: [IN_PROGRESS_ENTRY],
        skill_frequency: {},
        meta: { sql_count: 0, voyage_count: 0, total: 2, skill_freq_sample: 0 },
      },
    });
    renderBanner();
    await screen.findByTestId("request-history-banner");

    const links = screen.getAllByRole("link", { name: "Otwórz istniejącą" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/jobs/12");
  });

  it("„Użyj jako szablon” woła onUseAsTemplate z job_id", async () => {
    mocks.preview.mockResolvedValue({
      data: {
        closed: [CLOSED_ENTRY],
        in_progress: [],
        skill_frequency: {},
        meta: { sql_count: 0, voyage_count: 0, total: 1, skill_freq_sample: 0 },
      },
    });
    const { onUseAsTemplate } = renderBanner();
    await screen.findByTestId("request-history-banner");

    await userEvent.click(
      screen.getByRole("button", { name: "Użyj jako szablon" }),
    );
    expect(onUseAsTemplate).toHaveBeenCalledWith(13);
  });

  it("wpis użyty jako szablon pokazuje „Użyto jako szablon” zamiast przycisku", async () => {
    mocks.preview.mockResolvedValue({
      data: {
        closed: [CLOSED_ENTRY],
        in_progress: [],
        skill_frequency: {},
        meta: { sql_count: 0, voyage_count: 0, total: 1, skill_freq_sample: 0 },
      },
    });
    renderBanner({ templateJobId: 13 });
    await screen.findByTestId("request-history-banner");

    expect(screen.getByText("Użyto jako szablon")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Użyj jako szablon" }),
    ).not.toBeInTheDocument();
  });
});
