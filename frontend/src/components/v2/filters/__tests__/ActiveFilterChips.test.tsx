import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    default: {
      get: vi.fn((url: string) =>
        Promise.resolve({
          data: url === "/api/jobs-lookup" ? [{ id: 454, title: "Rekrutacja Testowa" }] : [],
        }),
      ),
    },
  };
});

import { ActiveFilterChips } from "@/components/v2/filters/ActiveFilterChips";
import { DEFAULT_FILTERS, type CandidateFilters } from "@/lib/url-filters";

function renderChips(
  patch: Partial<CandidateFilters>,
  onUpdate = vi.fn(),
  omitKey?: (key: string) => boolean,
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ActiveFilterChips
        filters={{ ...DEFAULT_FILTERS, ...patch }}
        onUpdate={onUpdate}
        omitKey={omitKey}
      />
    </QueryClientProvider>,
  );
  return onUpdate;
}

describe("ActiveFilterChips (UAT B-B06)", () => {
  it("shows the recruitment chip without a client filter, with the title", async () => {
    const onUpdate = renderChips({ recruitmentIds: [454], pipelineStage: ["new"] });
    expect(await screen.findByText("Rekrutacja: Rekrutacja Testowa #454")).toBeInTheDocument();
    expect(screen.getByText("Etap: Nowy")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Usuń filtr: Rekrutacja/ }));
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ recruitmentIds: [], recruitmentMatch: "assigned" }),
    );
  });

  it("does not hide or duplicate chips nested under other filters", () => {
    renderChips({
      openTo: ["side_projects"],
      recentlyChangedJobs: 2,
      pipelineStage: ["new", "screening"],
    });
    expect(screen.getAllByText("Otwartość: Side-projekty")).toHaveLength(1);
    expect(screen.getAllByText("Zmiana pracy: 2 mies.")).toHaveLength(1);
  });

  it("shows open-to chips without any stage filter", () => {
    renderChips({ openTo: ["side_projects"] });
    expect(screen.getByText("Otwartość: Side-projekty")).toBeInTheDocument();
  });
});

describe("ActiveFilterChips — etykiety etapów", () => {
  it("chip etapu „posting” pokazuje etykietę z panelu, nie slug", () => {
    renderChips({ pipelineStage: ["posting", "cv_sent"] });
    expect(screen.getByText("Etap: Ogłoszenia")).toBeInTheDocument();
    expect(screen.getByText("Etap: CV wysłane")).toBeInTheDocument();
    expect(screen.queryByText(/Etap: posting/)).not.toBeInTheDocument();
  });

  it("omitKey chowa chipy pokazane gdzie indziej, a bez pozostałych nic nie rysuje", () => {
    renderChips(
      { rateMax: 160, status: ["active"] },
      vi.fn(),
      (key) => key === "rate",
    );
    expect(screen.queryByText(/Stawka/)).toBeNull();
    expect(screen.getByText("Status: Aktywni")).toBeInTheDocument();
  });

  it("gdy wszystkie chipy są pominięte, nie zostaje samo „Wyczyść wszystko”", () => {
    renderChips({ rateMax: 160 }, vi.fn(), () => true);
    expect(screen.queryByText("Wyczyść wszystko")).toBeNull();
  });
});
