import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InsightsLinkPeople } from "../InsightsLinkPeople";
import { insightsApi } from "@/lib/insights-api";

const RESPONSE = {
  period: {},
  visits_tracked_from: "2026-11-03",
  totals: { links: 46, links_without_visits: 26, visits_total: 83, visits: 4, applications: 2 },
  rows: [
    {
      user_id: 1,
      name: "Marta Fikcyjna",
      general_link: true,
      job_links: 4,
      visits: 3,
      visits_total: 16,
      applications_general: 1,
      applications_job: 1,
      new_candidates: 1,
      in_process: 1,
      cv_sent: 0,
      hired: 0,
    },
  ],
};

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <InsightsLinkPeople period={{ period: "month", offset: 0 }} />
    </QueryClientProvider>,
  );
}

describe("InsightsLinkPeople", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("pokazuje kafle, wiersz osoby i od kiedy są dzienne wejścia", async () => {
    vi.spyOn(insightsApi, "linkPeople").mockResolvedValue(RESPONSE as never);
    renderIt();
    const section = await screen.findByTestId("insights-link-people");
    expect(within(section).getByText("Linki bez żadnego wejścia")).toBeInTheDocument();
    expect(within(section).getByText("Marta Fikcyjna")).toBeInTheDocument();
    expect(within(section).getByText(/zapisujemy od 03 lis 2026/)).toBeInTheDocument();
  });

  it("awaria nie wygląda jak brak linków", async () => {
    vi.spyOn(insightsApi, "linkPeople").mockRejectedValue(
      Object.assign(new Error("boom"), { response: { status: 500, data: {} } }),
    );
    renderIt();
    await screen.findByRole("button", { name: /Ponów|Spróbuj/ });
    expect(screen.queryByText(/Nikt nie ma jeszcze linku/)).not.toBeInTheDocument();
  });
});
