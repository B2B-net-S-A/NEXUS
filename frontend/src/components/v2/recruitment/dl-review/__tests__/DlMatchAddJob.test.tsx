import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DlMatchJob } from "@/lib/dl-match-api";

const suggestions = vi.fn();
const search = vi.fn();
vi.mock("@/lib/dl-match-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/dl-match-api")>()),
  dlMatchApi: {
    suggestions: (...a: unknown[]) => suggestions(...a),
    search: (...a: unknown[]) => search(...a),
    send: vi.fn(),
  },
}));

import { otherLeadLabel } from "../DlMatchAddJob";
import { DlMatchSection, matchTargets, mergeJobs, useDlMatch } from "../DlMatchSection";

function job(id: number, extra: Partial<DlMatchJob> = {}): DlMatchJob {
  return {
    job_id: id,
    title: `IT Analyst ${id}`,
    client_name: "Nordea Bank Abp",
    client_reference: `${42900 + id}`,
    score: null,
    matching_must: [],
    gap_must: [],
    linked: false,
    destination: "cpro",
    sendable: true,
    ...extra,
  };
}

function Harness() {
  const model = useDlMatch(21, 31, true);
  const { targets } = matchTargets(model.jobs, model.selection, { rate: "161", unit: "hourly", currency: "PLN" });
  return (
    <>
      <DlMatchSection model={model} fallbackRate="161" />
      <output data-testid="targets">{targets.map((t) => t.job_id).join(",")}</output>
    </>
  );
}

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Harness />
    </QueryClientProvider>,
  );
}

describe("„+ Dodaj inną rekrutację” (prośba Igora 27.10.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    suggestions.mockResolvedValue({
      candidate_id: 21,
      from_job_id: 31,
      status: "ok",
      jobs: [],
      already_in: [{ job_id: 50, title: "Data Analyst", client_reference: "42700", column: "cv_sent" }],
    });
    search.mockResolvedValue([
      job(46, { in_portfolio: true }),
      job(50),
      job(77, { in_portfolio: false, delivery_lead_name: "Marta Lis" }),
    ]);
  });

  it("sekcja zostaje przy pustej ocenie i dodaje wskazaną rekrutację od razu zaznaczoną", async () => {
    renderSection();
    expect(await screen.findByText(/Nexus nie podsunął innej Twojej rekrutacji/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Dodaj inną rekrutację/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Szukaj otwartej rekrutacji" }), "analyst");

    const results = await screen.findByTestId("dl-match-add");
    await waitFor(() => expect(search).toHaveBeenCalledWith(21, 31, "analyst"));
    // Rekrutacja, w której osoba już jest, nie wraca w wynikach.
    expect(within(results).queryByTestId("dl-match-add-50")).toBeNull();
    expect(within(results).getByText("DL: Marta Lis")).toBeInTheDocument();

    await userEvent.click(within(results).getByTestId("dl-match-add-77"));
    const row = await screen.findByTestId("dl-match-row-77");
    expect(within(row).getByText("dodana przez Ciebie")).toBeInTheDocument();
    expect(within(row).getByText("DL: Marta Lis")).toBeInTheDocument();
    expect(within(row).getByRole("checkbox")).toBeChecked();
    expect(screen.getByTestId("targets")).toHaveTextContent("77");
  });

  it("„usuń” zdejmuje ręcznie dodaną z listy i z wysyłki", async () => {
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: /Dodaj inną rekrutację/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Szukaj otwartej rekrutacji" }), "analyst");
    await userEvent.click(await screen.findByTestId("dl-match-add-46"));
    await screen.findByTestId("dl-match-row-46");

    await userEvent.click(screen.getByRole("button", { name: /Usuń z listy/ }));
    expect(screen.queryByTestId("dl-match-row-46")).toBeNull();
    expect(screen.getByTestId("targets")).toHaveTextContent("");
  });

  it("jedna litera nie odpytuje serwera", async () => {
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: /Dodaj inną rekrutację/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Szukaj otwartej rekrutacji" }), "a");
    expect(await screen.findByText(/Otwarte rekrutacje całej firmy/)).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();
  });

  it("awaria wyszukiwania nie wygląda jak brak wyników", async () => {
    search.mockRejectedValue(new Error("boom"));
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: /Dodaj inną rekrutację/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Szukaj otwartej rekrutacji" }), "analyst");
    expect(await screen.findByRole("alert")).toHaveTextContent(/Nie udało się wyszukać rekrutacji/);
    expect(screen.queryByText(/Brak otwartej rekrutacji/)).toBeNull();
  });
});

describe("Match — lista z oceny i dodane ręcznie", () => {
  it("ocena wygrywa z ręcznym dodaniem tej samej rekrutacji", () => {
    const merged = mergeJobs([job(1, { score: 80 })], [job(1, { manual: true }), job(2, { manual: true })]);
    expect(merged.map((j) => [j.job_id, Boolean(j.manual)])).toEqual([
      [1, false],
      [2, true],
    ]);
  });

  it("cudza rekrutacja mówi, czyja jest", () => {
    expect(otherLeadLabel({ delivery_lead_name: "Marta Lis" })).toBe("DL: Marta Lis");
    expect(otherLeadLabel({ delivery_lead_name: null })).toBe("poza Twoim portfelem");
  });
});
