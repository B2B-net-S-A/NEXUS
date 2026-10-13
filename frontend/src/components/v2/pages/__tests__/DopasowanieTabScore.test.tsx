import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const matchScores = vi.fn();

vi.mock("@/lib/api", () => ({
  matchScoringApi: {
    get: (...args: unknown[]) => get(...args),
    feedback: vi.fn(),
  },
  extractErrorMsg: () => "",
}));
vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: {
    matchScores: (...args: unknown[]) => matchScores(...args),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));

import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";

const justification = {
  candidate_id: 3,
  job_id: 9,
  job_title: "Java",
  summary: "Mocne dopasowanie.",
  pros: [],
  watchouts: [],
  model: "m",
  rating: null,
  rating_comment: null,
  generated_at: null,
};

function renderTab() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <DopasowanieTab candidateId={3} recruitments={[{ job_id: 9, job_title: "Java" }]} />
    </QueryClientProvider>,
  );
}

describe("DopasowanieTab score ring", () => {
  beforeEach(() => {
    get.mockReset();
    matchScores.mockReset();
    get.mockResolvedValue({ data: justification });
  });

  it("shows the canonical number from the scores endpoint", async () => {
    matchScores.mockResolvedValue({
      scores: { "3": 64 },
      breakdowns: { "3": { total: 64, measurement: "measured" } },
      profile_key: "p:1",
    });
    renderTab();
    expect(await screen.findByLabelText("Dopasowanie 64 na 100")).toBeInTheDocument();
    expect(matchScores).toHaveBeenCalledWith(9, [3], expect.anything());
  });

  it("an unmeasured pair shows 'ocena niepełna', never a 0", async () => {
    matchScores.mockResolvedValue({
      scores: {},
      breakdowns: { "3": { total: null, measurement: "missing_index" } },
      profile_key: null,
    });
    renderTab();
    expect(
      await screen.findByRole("img", {
        name: "Dopasowanie: ocena niepełna — kandydat nie ma jeszcze wektora w indeksie",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/Dopasowanie 0 na 100/)).not.toBeInTheDocument();
    expect(await screen.findByText("Mocne dopasowanie.")).toBeInTheDocument();
  });

  it("keeps the ring when the AI justification fails with 502", async () => {
    matchScores.mockResolvedValue({
      scores: { "3": 71 },
      breakdowns: { "3": { total: 71, measurement: "measured" } },
    });
    get.mockRejectedValue({
      response: {
        status: 502,
        data: { detail: "Nie udało się wygenerować uzasadnienia AI." },
      },
    });
    renderTab();
    expect(await screen.findByLabelText("Dopasowanie 71 na 100")).toBeInTheDocument();
    expect(
      await screen.findByText(
        "Nie udało się przygotować opisu dopasowania. Spróbuj za chwilę.",
      ),
    ).toBeInTheDocument();
  });

  it("says the viewer has no access instead of showing an empty ring", async () => {
    matchScores.mockRejectedValue({ response: { status: 403, data: {} } });
    renderTab();
    expect(
      await screen.findByText("Brak dostępu do oceny tej rekrutacji"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/Dopasowanie \d+ na 100/)).toBeNull();
  });

  it("offers a retry when scoring fails for another reason", async () => {
    matchScores.mockRejectedValue(new Error("offline"));
    renderTab();
    expect(await screen.findByText("nie policzono")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ponów" })).toBeInTheDocument();
  });
});

describe("DopasowanieTab — ocena jednej rekrutacji (wiersz w zakładce „Rekrutacje”)", () => {
  beforeEach(() => {
    get.mockReset();
    matchScores.mockReset();
    get.mockResolvedValue({ data: { ...justification, job_id: 12 } });
    matchScores.mockResolvedValue({
      scores: { "3": 58 },
      breakdowns: { "3": { total: 58, measurement: "measured" } },
    });
  });

  it("z `jobId` liczy tylko tę rekrutację i nie pokazuje wyboru rekrutacji", async () => {
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <DopasowanieTab
          candidateId={3}
          recruitments={[
            { job_id: 9, job_title: "Java" },
            { job_id: 12, job_title: "DevOps" },
          ]}
          defaultJobId={9}
          jobId={12}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByLabelText("Dopasowanie 58 na 100")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByText("Rekrutacja:")).toBeNull();
    expect(matchScores).toHaveBeenCalledTimes(1);
    expect(matchScores).toHaveBeenCalledWith(12, [3], expect.anything());
    expect(get).toHaveBeenCalledWith(3, 12);
    expect(screen.getByRole("button", { name: /Odśwież/ })).toBeInTheDocument();
  });

  it("z `jobId` nie pokazuje pustego stanu, nawet gdy lista rekrutacji jest pusta", async () => {
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <DopasowanieTab candidateId={3} recruitments={[]} jobId={12} readOnly />
      </QueryClientProvider>,
    );
    expect(await screen.findByLabelText("Dopasowanie 58 na 100")).toBeInTheDocument();
    expect(screen.queryByText("Brak rekrutacji do oceny")).toBeNull();
    // Tylko do odczytu i bez wyboru — pasek nad oceną znika w całości.
    expect(screen.queryByRole("button", { name: /Odśwież/ })).toBeNull();
  });

  it("bez `jobId` wybór rekrutacji zostaje", async () => {
    renderTab();
    expect(await screen.findByRole("combobox")).toHaveValue("9");
  });
});

