import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ProposalFacts } from "@/lib/job-proposals-api";
import type { SentPerson, SimilarJobItem } from "@/lib/similar-jobs-api";

const facts = vi.fn();
const matchScores = vi.fn();
const apiGet = vi.fn();
const cvOpen = vi.fn();

vi.mock("@/lib/job-proposals-api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/job-proposals-api")>();
  return {
    ...actual,
    jobProposalsApi: { ...actual.jobProposalsApi, facts: (...a: unknown[]) => facts(...a) },
  };
});
vi.mock("@/lib/candidate-search-api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/candidate-search-api")>();
  return {
    ...actual,
    candidateSearchApi: {
      ...actual.candidateSearchApi,
      matchScores: (...a: unknown[]) => matchScores(...a),
    },
  };
});
vi.mock("@/lib/api", () => {
  const api = { get: (...a: unknown[]) => apiGet(...a) };
  return { default: api, api };
});
vi.mock("@/components/v2/candidates/CandidateCvCell", () => ({
  useCandidateCvPreview: () => ({ open: cvOpen, loading: false, modal: null }),
}));

import { SimilarPersonPreview } from "@/components/v2/jobs/SimilarPersonPreview";

const PERSON: SentPerson = {
  candidate_id: 10,
  name: "Ewa Marczak",
  furthest_stage: "cv_sent",
  sent_at: "2026-09-12",
  outcome: "in_progress",
  already_in_job: false,
  selectable: true,
};

const SOURCE: SimilarJobItem = {
  id: 1725,
  title: "Analityk Systemowy",
  reference_number: "DEMO-1725",
  status: "closed",
  closed_at: null,
  client_name: "Klient Demo",
  similarity: 70,
  sent_count: 3,
  linked: false,
};

function factsRow(overrides: Partial<ProposalFacts> = {}): ProposalFacts {
  return {
    candidate_id: 10,
    title: "Analityk Systemowy",
    company: null,
    years_experience: 7,
    city: "Kraków",
    max_onsite_days_per_week: 0,
    remote_modes: [],
    availability_status: null,
    availability_date: null,
    expected_rate_hourly: 140,
    expected_rate_currency: "PLN",
    expected_rate_redacted: false,
    client_history: null,
    ...overrides,
  };
}

function httpError(status: number) {
  return Object.assign(new Error(String(status)), { response: { status } });
}

const handlers = { onPrev: vi.fn(), onNext: vi.fn(), onClose: vi.fn(), onToggle: vi.fn() };

function renderPreview(
  overrides: Partial<React.ComponentProps<typeof SimilarPersonPreview>> = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SimilarPersonPreview
        jobId={5}
        person={PERSON}
        sourceJob={SOURCE}
        position={{ index: 1, total: 3 }}
        onPrev={handlers.onPrev}
        onNext={handlers.onNext}
        onClose={handlers.onClose}
        canOpenProfile
        selection={{ checked: true, disabled: false, onToggle: handlers.onToggle }}
        {...overrides}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  facts.mockResolvedValue({ job_id: 5, items: [factsRow()] });
  matchScores.mockResolvedValue({
    scores: { "10": 84 },
    breakdowns: {
      "10": { total: 84, measurement: "measured", matching_must: ["Java"], gap_must: ["Kafka"] },
    },
  });
  apiGet.mockResolvedValue({
    data: {
      recent_notes: [
        { id: 1, content: "Czeka na odpowiedź klienta.", created_at: "2026-09-12T10:00:00Z", author_name: "Marta N." },
      ],
    },
  });
});

describe("Karta osoby w „Podobnych rekrutacjach”", () => {
  it("pokazuje dopasowanie do TEJ rekrutacji, fakty, status źródłowy i notatkę", async () => {
    renderPreview();
    expect(await screen.findByLabelText("Dopasowanie: 84 na 100")).toBeInTheDocument();
    expect(matchScores).toHaveBeenCalledWith(5, [10], expect.anything());
    expect(facts).toHaveBeenCalledWith(5, [10], expect.anything());

    const must = screen.getByRole("list", { name: "Wymagania must-have" });
    expect(within(must).getByText("Java")).toBeInTheDocument();
    expect(within(must).getByText("Kafka — nie znaleziono")).toBeInTheDocument();

    expect(await screen.findByText("Kraków")).toBeInTheDocument();
    expect(screen.getByText("tylko zdalnie")).toBeInTheDocument();
    expect(screen.getByText("140 zł/h")).toBeInTheDocument();
    expect(screen.getByText("Analityk Systemowy · 7 lat dośw.")).toBeInTheDocument();

    expect(screen.getByText("CV wysłane 12.09.2026 · proces trwa")).toBeInTheDocument();
    expect(screen.getByText("Klient Demo · DEMO-1725")).toBeInTheDocument();
    expect(await screen.findByText("Czeka na odpowiedź klienta.")).toBeInTheDocument();
    expect(screen.getByText("2 z 3")).toBeInTheDocument();
  });

  it("w dopasowaniu pokazuje tylko technologie — wymagania opisane zdaniem pomija", async () => {
    const prose = "umiejętność dekompozycji wymagań na zadania.";
    matchScores.mockResolvedValue({
      scores: { "10": 77 },
      breakdowns: {
        "10": {
          total: 77,
          measurement: "measured",
          matching_must: ["Java", "język angielski B2"],
          gap_must: [prose, "Kafka"],
        },
      },
      non_technology_must: [prose, "język angielski B2"],
    });
    renderPreview();
    const must = await screen.findByRole("list", { name: "Wymagania must-have" });
    expect(within(must).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Java",
      "Kafka — nie znaleziono",
    ]);
    expect(screen.queryByText(/dekompozycji/)).not.toBeInTheDocument();
  });

  it("same wymagania opisane zdaniami = zdanie zamiast pustej sekcji", async () => {
    matchScores.mockResolvedValue({
      scores: { "10": 61 },
      breakdowns: {
        "10": { total: 61, measurement: "measured", matching_must: [], gap_must: ["praca w zespole"] },
      },
      non_technology_must: ["praca w zespole"],
    });
    renderPreview();
    expect(
      await screen.findByText(
        "Wymagania tej rekrutacji są opisane zdaniami — nie ma technologii do porównania.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Wymagania must-have" })).not.toBeInTheDocument();
  });

  it("para bez pomiaru to „Ocena niepełna” z powodem, nigdy zero", async () => {
    matchScores.mockResolvedValue({
      scores: {},
      breakdowns: { "10": { total: null, measurement: "missing_index" } },
    });
    renderPreview();
    expect(await screen.findByLabelText("Dopasowanie: Ocena niepełna")).toBeInTheDocument();
    expect(screen.getByText(/nie ma jeszcze wektora w indeksie/)).toBeInTheDocument();
    expect(screen.getByText(/To nie znaczy, że osoba nie pasuje/)).toBeInTheDocument();
  });

  it("awaria oceny: „Nie policzono” z „Ponów”, a nie pusta sekcja", async () => {
    matchScores.mockRejectedValueOnce(httpError(500));
    renderPreview();
    expect(await screen.findByText(/Nie policzono dopasowania\./)).toBeInTheDocument();
    const section = screen.getByRole("region", { name: "Dopasowanie do tej rekrutacji" });
    fireEvent.click(within(section).getByRole("button", { name: "Ponów" }));
    expect(await screen.findByLabelText("Dopasowanie: 84 na 100")).toBeInTheDocument();
  });

  it("403 oceny: komunikat o dostępie, bez „Ponów”", async () => {
    matchScores.mockRejectedValue(httpError(403));
    renderPreview();
    expect(await screen.findByText(/Nie masz dostępu do oceny dopasowania/)).toBeInTheDocument();
    const section = screen.getByRole("region", { name: "Dopasowanie do tej rekrutacji" });
    expect(within(section).queryByRole("button", { name: "Ponów" })).toBeNull();
  });

  it("nieznany fakt znika — bez „—” i bez pustej etykiety", async () => {
    facts.mockResolvedValue({
      job_id: 5,
      items: [factsRow({ expected_rate_hourly: null, max_onsite_days_per_week: null })],
    });
    renderPreview();
    expect(await screen.findByText("Kraków")).toBeInTheDocument();
    expect(screen.queryByText("Stawka")).toBeNull();
    expect(screen.queryByText("Tryb pracy")).toBeNull();
    expect(screen.queryByText("—")).toBeNull();
  });

  it("awaria faktów nie udaje pustego profilu", async () => {
    facts.mockRejectedValue(httpError(500));
    renderPreview();
    expect(await screen.findByText(/Nie udało się wczytać danych z profilu\./)).toBeInTheDocument();
    expect(screen.queryByText(/Profil nie ma jeszcze/)).toBeNull();
    // Ocena liczy się niezależnie od faktów.
    expect(await screen.findByLabelText("Dopasowanie: 84 na 100")).toBeInTheDocument();
  });

  it("notatki: 403 chowa sekcję, awaria mówi o awarii, pusta lista to „Brak notatek”", async () => {
    apiGet.mockRejectedValue(httpError(403));
    const first = renderPreview();
    await screen.findByLabelText("Dopasowanie: 84 na 100");
    expect(screen.queryByRole("region", { name: "Notatki" })).toBeNull();
    first.unmount();

    apiGet.mockRejectedValue(httpError(500));
    const second = renderPreview();
    expect(await screen.findByText(/Nie udało się wczytać notatek\./)).toBeInTheDocument();
    second.unmount();

    apiGet.mockResolvedValue({ data: { recent_notes: [] } });
    renderPreview();
    expect(await screen.findByText("Brak notatek.")).toBeInTheDocument();
  });

  it("„Otwórz profil” tylko dla roli z dostępem do profili; CV otwiera podgląd", async () => {
    const withAccess = renderPreview();
    const link = screen.getByRole("link", { name: /Otwórz profil/ });
    expect(link).toHaveAttribute("href", "/candidates/10?from=job&jobId=5");
    expect(link).toHaveAttribute("target", "_blank");
    fireEvent.click(screen.getByRole("button", { name: /Podgląd CV/ }));
    expect(cvOpen).toHaveBeenCalledTimes(1);
    withAccess.unmount();

    renderPreview({ canOpenProfile: false });
    expect(screen.queryByRole("link", { name: /Otwórz profil/ })).toBeNull();
  });

  it("↑ ↓ i przyciski zmieniają osobę; na końcu listy nie ma dokąd iść", () => {
    renderPreview({ position: { index: 2, total: 3 } });
    const card = screen.getByTestId("similar-person-preview");
    expect(card).toHaveFocus();
    fireEvent.keyDown(card, { key: "ArrowDown" });
    expect(handlers.onNext).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Następna osoba" })).toBeDisabled();
    fireEvent.keyDown(card, { key: "ArrowUp" });
    expect(handlers.onPrev).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Poprzednia osoba" }));
    expect(handlers.onPrev).toHaveBeenCalledTimes(2);
  });

  it("pole „Przepnij” woła to samo przełączenie co wiersz; zablokowana osoba mówi dlaczego", () => {
    const open = renderPreview();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(handlers.onToggle).toHaveBeenCalledTimes(1);
    open.unmount();

    renderPreview({
      person: { ...PERSON, outcome: "hired", furthest_stage: "hired", selectable: false },
      selection: { checked: false, disabled: true, onToggle: handlers.onToggle },
    });
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByText("Pracuje u klienta — nie da się jej przepiąć.")).toBeInTheDocument();
  });
});
